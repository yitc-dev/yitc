"""bin/lib/views.py — the _view_* reporting/query-lens family (T-9378, byte-identical
extraction from bin/yitc-v2). Full inject-residue seam (plan.py/T-9341 AST-FREEZE pattern):
host collaborators + host globals + moved siblings arrive by keyword-only injection;
module-local view-domain consts live here. The host keeps a thin residue wrapper per moved fn.
The view-registry dispatch (_run_view) STAYS host and calls these via the host residue, so
the function-ref identity contract is preserved (mirrors AUDIT_PROVIDERS staying host)."""
from __future__ import annotations
import json
import re
import statistics
import time
from pathlib import Path

from lib import inspection  # single calibration home for BYTES_PER_TOKEN (T-10313/T-10316 shared axis)
from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)
from lib import journal as journal_mod  # T-11444: the SPEC-0190 segment-aware journal folds
from lib import plan  # T-10927: the run-scoped plan→task link index (read-only accessor)
from lib import observe  # SPEC-0135 §6: read-time provider normalization (patch-version bucket collapse, T-10605)

# --- module-local view-domain constants (moved from host) ---
_CURRENCY_PROBLEM_FLAGS = frozenset({"stale", "dangling", "multi-proposer-unordered"})
_DISCIPLINE_RATIO_KINDS = ("read-check", "stage-correspondence", "verification-exists")
_READ_GATE_KIND_ALIASES = {"stage": "read-check"}
# The events.jsonl rotation trigger (D-0030 `> 10 MB` rotation_policy — authoritative home there /
# SPEC-0190 §Rotation policy, re-homed out of SPEC-0002 by T-11447; value mirrored here ONCE).
# Single source for EVERY view that checks journal size: BOTH
# the displacement-retention surface #1 and the journal-hygiene digest read THIS constant, so the
# threshold is never a second hard-coded literal (T-9738 audit-pre finding, P5 single-source).
_JOURNAL_ROTATION_BYTES = 10 * 1024 * 1024

# ── T-11968 (SPEC-0189 §Parameters) — THE SHARED GROWTH FOLD ──────────────────────────────────────
#
# The growth window is a GOVERNING PARAMETER, homed in SPEC-0189 and READ from it — never a literal
# here. That is not stylistic: SPEC-0189 owns the value precisely so the fold consumes it and does not
# define it, and a constant in this file would silently become a second home the spec could not move.
# The read is the SAME read-only regex scan `worktree.py#journal_live_window_days` performs on
# SPEC-0190 and `_rotation_rereview_bound_mb` performs above — one carrier, one idiom, no second
# config path, no new parser family.
_GROWTH_WINDOW_RE = re.compile(r"GROWTH_WINDOW_DAYS:\s*([0-9]+)")

# The land rows the fold counts. Already emitted by every land in every repo, which is what makes the
# card's "no new instrumentation" literally true — and, per SPEC-0189 rule 2, a signal emitted as a
# by-product of ordinary work rather than one requiring anybody to CLASSIFY anything.
_GROWTH_EVENT_TYPE = "land_completed"
_GROWTH_OK_STATUS = "ok"


def growth_window_days(specs_dir=None) -> "int | None":
    """SPEC-0189 §Parameters — `growth_window_days`, read FROM the spec that governs it. None when the
    token cannot be read.

    `specs_dir` defaults to the kernel's own `specs/` and is a PARAMETER for the reason
    `mandatory_migration_violations(entries=None)` takes one: so a fixture carrying a DIFFERENT value
    can be read through THIS function, rather than through a re-implementation of it in a test. That
    matters more than it looks — it is what makes the AC2 differential real. A probe that only exercises
    the regex leaves `return 30` passing every arm, since the live carrier genuinely says 30 (caught by
    the audit-post on this card's first ship). Production callers pass nothing and resolve the kernel
    carrier below, unchanged.

    THE VALUE IS NOT A CONSTANT IN CODE, and SPEC-0189 says so in as many words: *the growth window is a
    GOVERNING scalar and is homed here, not in the code that reads it: the fold consumes this value, it
    does not define it.*

    FAIL-CLOSED, WITH NO DEFAULT, and the direction is the whole point. An unreadable carrier or a
    missing token yields None and the fold does not run; it never falls back to a number, because a
    fallback would BE the local literal this parameter exists to forbid — a fold quietly answering on a
    guessed window is worse than one that answers nothing, since the guess is invisible in the answer.

    THE CARRIER IS THE KERNEL'S OWN COPY, resolved from this module's location rather than from
    REPO_ROOT: SPEC-0189 is a kernel spec and a `-C` consumer checkout has no copy of it, so resolving
    through the repo root would silently answer None for every consumer. Same self-locating idiom
    `worktree.py#journal_live_window_days` uses for SPEC-0190."""
    try:
        specs = Path(specs_dir) if specs_dir is not None else (
            Path(__file__).resolve().parent.parent.parent / "specs")
        for sp in sorted(specs.glob("SPEC-0189-*.yaml")):
            m = _GROWTH_WINDOW_RE.search(sp.read_text(encoding="utf-8"))
            if m:
                return int(m.group(1))
    except (OSError, ValueError):
        return None
    return None


def _growth_row_ts(event) -> "object | None":
    """The timestamp of one qualifying growth row, else None.

    FAITHFUL, NEVER FAIL-CLOSED (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): this
    reports only what the row literally says. A non-dict row, a foreign event type, a missing or
    non-`ok` status, and an absent or unparseable `ts` all yield None and are simply not counted — the
    single READER below decides what that means."""
    import datetime as _dt
    if not isinstance(event, dict) or event.get("type") != _GROWTH_EVENT_TYPE:
        return None
    data = event.get("data")
    if not isinstance(data, dict) or data.get("status") != _GROWTH_OK_STATUS:
        return None
    raw = event.get("ts")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        ts = _dt.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=_dt.timezone.utc)


def project_growth(project: str, events, *, window_days: int, now=None) -> dict:
    """T-11968 (SPEC-0189) — THE SHARED GROWTH FOLD: for a NAMED project, the number of
    `land_completed(status=ok)` rows in that project's OWN journal over the trailing `window_days`.
    Returns {"project", "window_days", "count"}.

    THE RESULT IS LABELLED WITH THE PROJECT, so the reading is per-project BY CONSTRUCTION. A bare int
    can be summed across projects by a caller that did not mean to; a labelled reading cannot be
    aggregated by accident, and a cross-project total is not a thing this fold offers.

    IT TAKES ITS EVENTS AS AN INPUT rather than resolving a journal path itself, for two independent
    reasons. First, territory: AGENTS §Scope-boundary keeps another project's repo read-only and
    explicitly NOT monitored or probed, and a fold that went hunting across `projects/` would be doing
    exactly that from the kernel. The caller runs in — and supplies — its own repo. Second, testability:
    the fixture journal AC1's differential requires is then just a list of dicts, with no filesystem and
    no clock.

    NO NEW INSTRUMENTATION: `land_completed` rows carrying `data.status` are already emitted everywhere.

    WHAT THIS NUMBER IS FOR, AND WHAT IT MAY NEVER DO (SPEC-0189 rule 3 — stated here because this is
    where a future caller reads it). Growth MAY gate RELEVANCE: whether a proposal is worth making now.
    It MUST NOT, alone, be the EVIDENCE that an absence is costing anything — only a surface's own
    rule-2 signal carries that, and a proposal whose sole support is a count is malformed. A count is
    not a liveness probe (`lessons/a-presence-count-is-not-a-liveness-probe.md`). Accordingly this
    function RETURNS A READING AND DECIDES NOTHING: nothing in this card branches on it, which is a
    structural property the tests assert rather than a convention anyone must remember."""
    import datetime as _dt
    if now is None:
        now = _dt.datetime.now(_dt.timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    cutoff = now - _dt.timedelta(days=int(window_days))
    count = 0
    for ev in (events or ()):
        ts = _growth_row_ts(ev)
        if ts is not None and cutoff <= ts <= now:
            count += 1
    return {"project": project, "window_days": int(window_days), "count": count}



def _live_segment_bytes(path) -> int:
    """The LIVE segment's byte size — the quantity a rotation ACTION can move (T-11843).

    The sibling of `journal_mod.segment_size`, which sums EVERY segment. Both readings are
    legitimate and neither replaces the other; what T-11843 fixed is WHICH ONE a GOVERNANCE BOUND
    reads. SPEC-0190 rule 8 requires the aggregate to stay visible and governed so rotation cannot
    silently retire the mechanism that judges rotation — and that concern is real. But the aggregate
    is not a quantity any permitted action can REDUCE: archive segments are append-only history that
    is never deleted, and SPEC-0002 §Violations forbids an in-place rewrite. A trigger bound to it is
    unsatisfiable BY CONSTRUCTION — permanently lit, which is the class this corpus already retired
    twice (T-11028 report-only rows, T-10651 the done-log count-gate). So the TRIGGER and the DEFER's
    currency bound read the live segment (what their own action moves, and the unit
    `ROTATION_VERDICT_REREVIEW_MB: 220` was calibrated on — SPEC-0190 §Rotation policy's Origin
    datum is an `ls -l events.jsonl`), while the aggregate is reported beside them as a trajectory.

    A missing journal is 0, matching `segment_size`'s missing-segment behaviour exactly, so a caller
    swapping one for the other inherits no new failure mode."""
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0

# T-10846 — memoized plan-independent journal pass for `_dispositionless_infra_closures`. Keyed by the
# journal's identity AND its (mtime_ns, size), so an appended journal recomputes; a bare path key would
# be the stale-read bug this cache must not introduce. Bounded by construction: one entry per distinct
# journal STATE, and callers within a process see at most a handful (the engine journal, plus a test's
# tmp fixtures). Read-only value — every caller consumes it without mutating.
_ANY_CLOSE_MISSING_DISPOSITION_CACHE: dict = {}


def _any_close_missing_disposition(events_path: "Path") -> dict:
    """{task_id: did ANY `task_closed` for it lack `data.propagation_disposition`} over `events_path`.

    The any-missing accumulation (NOT "latest close wins") is the T-0670 semantic, unchanged — see
    `_dispositionless_infra_closures`. Pure read; a missing file yields {}; a malformed line is skipped
    exactly as before. Memoized per journal state (see the cache note above)."""
    # T-11444 — the memo key spans the SEGMENT SET (`journal.segment_stat_key`). A key taken off the
    # live segment alone would serve a STALE cached answer after an archive segment changed — the same
    # class of miss as SPEC-0190 rule 8's: correct-looking and wrong. An absent journal is still the
    # empty answer, but that is now decided by the fold below rather than by a `stat()` that raised.
    key = journal_mod.segment_stat_key(events_path)
    cached = _ANY_CLOSE_MISSING_DISPOSITION_CACHE.get(key)
    if cached is not None:
        return cached
    any_missing: dict = {}
    for line in journal_mod.segment_lines(events_path):  # T-11444: segment-aware fold (SPEC-0190 r4)
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") != "task_closed":
            continue
        tid = e.get("task_id")
        if not tid:
            continue
        d = e.get("data") or {}
        missing = d.get("propagation_disposition") is None
        any_missing[tid] = any_missing.get(tid, False) or missing
    _ANY_CLOSE_MISSING_DISPOSITION_CACHE[key] = any_missing
    return any_missing


# --- moved view functions (byte-identical bodies; injects spliced into signatures) ---
def _dispositionless_infra_closures(slug: str, events_path: "Path | None" = None, *, EVENTS_PATH=None, _find_task_yaml=None, _plan_tasks=None, _read_yaml=None) -> list:
    """T-0670 — READ-ONLY backstop detection at SPEC-0034 §postcheck: the plan's infra-class
    implementing tasks that CLOSED with NO forward-propagation disposition recorded. The
    propagation-disposition RULE is SPEC-0053 (active since T-0669) — REFERENCED here, NOT restated
    (P5, one home): SPEC-0053's presence-gate makes a FRESH infra close without a
    `propagation_disposition` structurally impossible, so this surfaces ONLY the LEGACY /
    emergency-bypass / pre-gate anomalies (closes that predate or bypassed the gate). It REPORTS,
    it NEVER refuses — a backstop detection, NOT a second enforcement path (CHARTER non-goal #7;
    the T-0670 ACCEPTANCE BOUND). Mirrors the surface-not-gate shape of the captures_routed advisory
    (`_require_captures_routed`, demoted to a non-blocking WARN, T-0644).

    A task is surfaced IFF: it is in the plan's implementing-task corpus (`_plan_tasks(slug)` —
    cites:slug) AND `done` AND `class: infra` (the SAME infra FLOOR SPEC-0053 gates on) AND it has
    ≥1 `task_closed` event of which AT LEAST ONE lacked `data.propagation_disposition`. The
    any-missing accumulation (NOT "latest close wins") is deliberate (audit-pre F1): a later
    dispositioned re-close must not MASK an earlier dispositionless one — a backstop fails toward
    SURFACING (a false surface is owner-judged + cheap; a missed anomaly is the failure it exists to
    prevent). A `done` infra task with NO `task_closed` event on record (hand-closed / not via the
    verb) is OUT of scope — not surfaced (no closure event to judge). Returns sorted [tid]. Pure
    read — no `_die`, no write (D-0053 report-not-block)."""
    events_path = events_path if events_path is not None else EVENTS_PATH
    # First pass: per task_id, did ANY task_closed lack a propagation_disposition? (and did it close
    # at all?). `any_missing[tid] is True` ⇒ surface; `False` ⇒ closed but every close dispositioned;
    # absent ⇒ never closed-via-verb (out of scope).
    #
    # T-10846 — this pass is plan-INDEPENDENT (it reads only the journal), so it is computed ONCE per
    # journal STATE and reused across slugs. `postcheck-plans-readiness` calls this helper once per
    # postcheck plan; at 13 plans that was 13 identical json.loads passes over a 270k-line / 120MB
    # events.jsonl — 40.6s of that lens's 41s, and the single largest cost in tests/test_views.py's
    # AC6 loop (the file was aborting land-verify under contention). The cache key carries the file's
    # identity AND its mtime/size, so an APPENDED journal (the only way it changes — append-only,
    # CHARTER §P5) misses and recomputes; a same-process caller can never read a stale map. The cached
    # value is only ever READ here and the returned list is rebuilt per call, so output is unchanged.
    any_missing = _any_close_missing_disposition(events_path)
    # T-10927 — the `class` of a LINKED card: when a `plan._plan_link_index_scope()` is OPEN, the ONE
    # corpus sweep that scope already did carries it, so this helper does NOT re-open every done
    # member's card just to test `class == infra` (that per-member re-read is what kept the
    # postcheck-plans-readiness lens at ~2 reads per card instead of the card's ONE-read claim). With
    # no scope open, `linked_class` is None and the original `_find_task_yaml` + `_read_yaml` per
    # member runs unchanged — same answer either way (both read the SAME canonical `class:` field).
    idx = plan._plan_link_index()
    linked_class = None if idx is None else {t: c for t, _st, _rt, c in idx.get(slug, [])}
    out = []
    for tid, status in _plan_tasks(slug):
        if status != "done":
            continue
        if any_missing.get(tid) is not True:   # never closed-via-verb, or every close dispositioned
            continue
        if linked_class is not None:
            if linked_class.get(tid) == "infra":
                out.append(tid)
            continue
        tpath = _find_task_yaml(tid)
        if tpath is None:
            continue
        td = _read_yaml(tpath)
        if isinstance(td, dict) and td.get("class") == "infra":
            out.append(tid)
    return sorted(out)

def _list_views(*, include_kernel: bool = False, VIEWS_DIR=None, _kernel_overlay_files=None, _read_yaml=None) -> list:
    """Catalog of saved views — read views/*.yaml on demand (D-0053: derived, not a stored index).
    Returns sorted (name, description) pairs; the stem is the canonical name if `name:` is absent.

    include_kernel (T-0865): the DELIVERY/discoverability knob for `graph query --type view` — when True
    AND this is a -C consumer build, the engine's saved views are merged UNDER the consumer's own
    (own-WINS per view NAME) so the kernel saved-lenses are DISCOVERABLE on a blank consumer (their lens
    runs against the engine-index fallback / the consumer's own journal). DEFAULT False keeps it own-only;
    engine self-build takes no overlay."""
    out: dict = {}
    own = sorted(VIEWS_DIR.glob("*.yaml")) if VIEWS_DIR.exists() else []
    for p in own + (_kernel_overlay_files("views", "*.yaml") if include_kernel else []):
        v = _read_yaml(p)
        if isinstance(v, dict):
            name = v.get("name") or p.stem
            if name not in out:               # own-WINS per-name: own files listed first
                out[name] = (v.get("description") or "").strip()
    return sorted(out.items())   # by canonical name (audit-post F2)

def _view_verb_map(index: dict, *, _live_cli_verbs=None) -> dict:
    """verb-map lens (D-0053): per-verb governance, PURE f(graph). The verb universe is derived from
    the REAL argparse surface — `build_parser()` subparsers (via `_live_cli_verbs`) — so it can never
    drift into a hand list (audit-pre F1). Governance is FILE-level today (code_to_specs is keyed by file
    component, T-0064): every verb lives in bin/yitc-v2, so the same specs govern the file as a whole. The
    precise symbol-level verb→spec gap is deferred to the reverse-index follow-up; output labels itself
    `file-level approximation` so the limit is visible (D-0053)."""
    verbs = sorted(_live_cli_verbs())
    governing = sorted(index.get("code_to_specs", {}).get("bin/yitc-v2", []))
    # One record PER VERB (audit-post F1) — a real verb→spec map, not two detached lists. At file-level
    # every verb shares the same governing specs (all live in bin/yitc-v2); `status` makes the
    # approximation explicit per row so a consumer never mistakes it for a precise symbol-level map.
    return {
        "verbs": [
            {"verb": v, "governing_specs": list(governing), "status": "file-level approximation"}
            for v in sorted(set(verbs))   # per-verb copy → clean YAML (no shared-ref anchors)
        ],
        "note": ("file-level approximation — every verb lives in bin/yitc-v2, so the same specs govern "
                 "the whole file; the precise symbol-level verb→spec mapping is gated on the "
                 "symbol-level reverse index (separate follow-up, D-0053)."),
    }

def _view_binding_bundle(index: dict, binding_token: str, *, engine_index: "dict | None" = None) -> dict:
    """binding-bundle lens (D-0053 saved view, T-9443): the active specs carrying ONE binding token —
    the REF_AVAILABLE discovery surface over a floor-trigger obligation set (e.g.
    `before-project-dimension-judgement`, T-9442). PURE reuse of the SINGLE carrier: membership is read
    straight from `index["verb_to_specs"][binding_token]` — the EXACT list `_build_binding_views`
    inverts from each spec's `binding:` field and that `floor_trigger_map` is itself built from
    (graph.py:197). So this view and the floor-map are TWO SURFACES over ONE source: a spec
    added/removed from the bundle reflects in both without a second list (AC2). No new store, no new
    node/edge. Each member is enriched with its title/status from the specs node-table (display only —
    the membership set is the carrier's, not re-derived here).

    engine_index (T-10239, X-0235): the ENGINE's index, passed by the host ONLY on a -C consumer build
    (else None → every leg below is a no-op and the engine-self output is unchanged). A binding token is
    a KERNEL constant and the specs carrying it are KERNEL specs, so a consumer's own `verb_to_specs`
    holds none of them: reading own-only printed `specs: [] / count: 0` for a BUILT consumer, a silent
    fail-OPEN on a MANDATORY floor (the consumer reads "no doctrine bound" instead of "wrong realm").
    Membership is therefore the UNION of own + kernel, never a fallback: the floor obligation is
    kernel-defined, so a consumer that binds one of its OWN specs to the token must ADD to the kernel
    members, never shadow them. Enrichment resolves BY PROVENANCE, KERNEL-FIRST on a collision — an id
    the kernel binds reads the engine table even when the consumer owns a spec at the same id, so a
    SPEC-0092 same-id collision cannot mis-title a kernel member. This is the 4th instance of the
    established engine-index fallback idiom (T-0860 spec point-lookup / T-1144 pattern point-lookup /
    T-0865 view catalog), not a parallel path."""
    engine_index = engine_index or {}
    own_ids = set((index.get("verb_to_specs") or {}).get(binding_token) or [])
    kernel_ids = set((engine_index.get("verb_to_specs") or {}).get(binding_token) or [])
    specs_tbl = index.get("specs") or {}
    kernel_tbl = engine_index.get("specs") or {}
    members = []
    for sid in sorted(own_ids | kernel_ids):
        # By provenance, KERNEL-FIRST on a collision: an id the KERNEL binds to this token is a kernel
        # member, so it enriches from the engine table even when the consumer owns a spec at the same id
        # (the SPEC-0092 collision — own-first there would let a consumer's same-id spec shadow the kernel
        # member's title/status). Only a purely own-bound id (absent from the kernel membership) reads the
        # own table first. Each falls back to the other table when its first choice has no node.
        tables = (kernel_tbl, specs_tbl) if sid in kernel_ids else (specs_tbl, kernel_tbl)
        node = next((t[sid] for t in tables if t.get(sid)), {})
        members.append({"spec": sid, "title": node.get("title"), "status": node.get("status")})
    return {
        "binding_token": binding_token,
        "specs": members,
        "count": len(members),
        "source": ("index.verb_to_specs[binding_token] — the SAME binding carrier the floor-trigger-map "
                   "is built from (graph.py _build_binding_views); single source, no new store (D-0053). "
                   "Under -C the consumer's own membership is UNIONED with the kernel's (T-10239)."),
    }

def _view_projection_currency(index: dict, *, _graph_query_projected=None) -> dict:
    """projection-currency lens (D-0053 saved view, T-0212): a PURE filter over the existing
    `_graph_query_projected` output — it reuses the projection, adds NO store and NO new flag.
    Surfaces only `proposed` specs carrying a currency-problem flag (_CURRENCY_PROBLEM_FLAGS);
    report-not-block. Clean corpus → problem_count 0 (AP-G1)."""
    projection = _graph_query_projected(index)
    problems: dict = {}
    summary: dict = {}
    for sid, entry in (projection.get("projected_specs") or {}).items():
        hit = [f for f in (entry.get("flags") or []) if f in _CURRENCY_PROBLEM_FLAGS]
        if not hit:
            continue
        rec = {"status": entry.get("status"), "flags": sorted(hit)}
        if "supersedes" in entry:
            rec["supersedes"] = entry["supersedes"]
        problems[sid] = rec
        for f in hit:
            summary[f] = summary.get(f, 0) + 1
    return {
        "currency_problems": dict(sorted(problems.items())),
        "problem_summary": dict(sorted(summary.items())),
        "problem_count": len(problems),
    }

def _view_propagation_surfaces(index: dict, target: "str | None") -> dict:
    """propagation-surfaces lens (T-0668, D-0053 saved view): given a SPEC id, return the candidate
    propagation/application surfaces for that (multi-site) spec — the sweep-set behind SPEC-0053's
    «now that this exists, where ELSE must it be applied?» disposition. PURE reuse of the EXISTING
    reverse-index (index["tasks_citing"] + index["code_to_specs"], the SAME maps `graph query <SPEC>`
    already reads) — adds NO store, NO new edge. Recomputed fresh (D-0053).

    No target → a non-erroring usage record (keeps the AC6 every-view-executable sweep green; a no-arg
    run must never raise — same contract as task-scorecard). With `target` = SPEC-XXXX:
      - citing_tasks: index["tasks_citing"][target] — the tasks that already CITE the spec (candidate
        consequent-change sites where the propagation likely lands), sorted.
      - implementing_code: code files whose code_to_specs entry names the spec (the inverse the
        point-lookup `implemented_by_code` uses), sorted — the code application surfaces.
      - implements_anchors: the spec node's declared `implements:` code anchors (fine-grained symbols).
      - surface_count = len(citing_tasks) + len(implementing_code) — the candidate-site tally.
      - title/status carried from the spec node when present (a spec absent from the index is NOT an
        error — citing_tasks may still be populated; found flags whether the spec node itself is known).
    Report-not-block: it surfaces CANDIDATES, never asserts completeness (the disposition decision
    stays owner/closer judgement)."""
    if not target:
        return {"spec": None,
                "usage": "graph query propagation-surfaces SPEC-XXXX",
                "note": ("candidate propagation/application surfaces for a multi-site spec — pass a "
                         "SPEC id as the second positional; reuses the tasks_citing / code_to_specs "
                         "reverse-index, no new store (SPEC-0053 disposition sweep tool)")}
    spec_node = (index.get("specs") or {}).get(target)
    citing_tasks = sorted(index.get("tasks_citing", {}).get(target, []))
    implementing_code = sorted(loc for loc, sp in (index.get("code_to_specs") or {}).items()
                               if target in (sp or []))
    implements_anchors = sorted(spec_node.get("implements") or []) if isinstance(spec_node, dict) else []
    return {
        "spec": target,
        "found": spec_node is not None,
        "title": spec_node.get("title") if isinstance(spec_node, dict) else None,
        "status": spec_node.get("status") if isinstance(spec_node, dict) else None,
        "citing_tasks": citing_tasks,
        "implementing_code": implementing_code,
        "implements_anchors": implements_anchors,
        "surface_count": len(citing_tasks) + len(implementing_code),
        "note": ("candidate propagation/application surfaces (report-not-block) — citing_tasks are the "
                 "sites already engaging the spec; the disposition decision stays owner/closer judgement"),
    }

def _view_extensions_catalog(index: dict) -> dict:
    """extensions-catalog lens (T-9489, D-0053 saved view — REALIZES SPEC-0101 rule 2). The DERIVED
    catalog of reusable «дополнения» / extensions: every spec carrying the `extension:` marker
    (landed T-9488, carried into the index spec node by graph.py), surfaced with its adoptability
    state + a DERIVED entry-point. PURE filter over index["specs"] — adds NO store, NO new node-type,
    NO new event (the marker is a field on the existing spec node; CHARTER §P1 F2). Recomputed fresh
    on every read (D-0053: store the query, never the output) — never a hand-maintained list, so it
    CANNOT drift from the spec corpus (the single source of truth, SPEC-0101 rule 3).

    Per entry (sorted by spec id): adoptability = the `extension` value (`adoptable` = a consumer-
    installable shared capability with an adopt-path; `internal-only` = a kernel-OWN tool, catalogued
    for discoverability but NOT consumer-adoptable — SPEC-0101 rule 1). entry_points = the spec's
    `implements:` anchors as a DETERMINISTIC SORTED list (the capability's code home — empty list if
    none; a list not a scalar so a multi-anchor spec is stable across recomputes). adopt_path =
    keyed on adoptability (adoptable → the SPEC-0093 yitc-ops `extensions:` adopt-declaration, rule 4;
    internal-only → None, no install-path). read = the spec's own read anchor.

    Report-only (D-0053): a discovery surface, never a gate. Discovered via `graph query --type view`
    (the canonical "look here first"); run `graph query extensions-catalog` for this content."""
    specs = index.get("specs") or {}
    entries = []
    for sid in sorted(specs):
        node = specs.get(sid) or {}
        marker = node.get("extension")
        if not marker:
            continue
        entry_points = sorted(node.get("implements") or [])
        adopt_path = (
            "declare + cite in the consumer's yitc-ops.yaml `extensions:` block "
            "(SPEC-0093 ops-contract amendment / SPEC-0101 rule 4) — adopt-and-cite, never copy/fork"
            if marker == "adoptable" else None  # internal-only: kernel-own, no install-path (rule 1)
        )
        entries.append({
            "spec": sid,
            "title": node.get("title"),
            "status": node.get("status"),
            "adoptability": marker,
            "entry_points": entry_points,
            "adopt_path": adopt_path,
            "read": f"bin/yitc-v2 graph query {sid}",
        })
    return {
        "lens": "extensions-catalog (T-9489 / SPEC-0101 rule 2) — the DERIVED catalog of reusable "
                "extensions (the `extension:`-marked specs), recomputed on read; never hand-maintained",
        "invariant": "DERIVED from the spec corpus (the single source of truth, SPEC-0101 rule 3) — "
                     "the marker is a field on the existing spec node, NOT a new node-type/store/event "
                     "(CHARTER §P1 F2). Store the query, never the output (D-0053) — cannot go stale.",
        "adoptability_states": {
            "adoptable": "a consumer-installable shared capability — has an adopt-path (rule 4)",
            "internal-only": "a kernel-OWN tool, catalogued for discoverability but NOT "
                             "consumer-adoptable (no install-path) — SPEC-0101 rule 1",
        },
        # T-12048 (SPEC-0197 rule 6) — the catalog is a DISCOVERY surface, and a discovery surface
        # that stays silent about it is read as a recommendation. Stated on the view itself rather
        # than only in the published policy, because this is what a reader choosing an extension
        # actually has in front of them.
        "non_endorsement": "listing is not endorsement (SPEC-0197 rule 6) — a listed extension is "
                           "catalogued for discoverability, not vouched for. A third-party "
                           "extension is runnable code the installer must review before adopting "
                           "it; an extension pin names an EXACT version (a moving ref is refused).",
        "count": len(entries),
        "extensions": entries,
        "note": "report-only discovery surface (D-0053), never a gate. Discovered via "
                "`graph query --type view`; the adopt/promote transaction is OUT of this slice "
                "(SPEC-0101 rule 6).",
    }

def _view_plans_pending_finalization(index: dict, *, _plan_open_citing_tasks=None) -> dict:
    """plans-pending-finalization lens (T-0227 PULL safety net, AC2/AC4). Accepted plans that have
    ZERO open citing tasks left — the finalization-not-forgotten backlog the PUSH WARN might have
    missed (a plan accepted before this trigger shipped, or whose hint scrolled past).

    Pure f over committed artifacts, recomputed fresh, no stored output (D-0053). Plan STATUS comes
    from index["plans"] (kind:plan); the citing-task side reuses the SAME _plan_open_citing_tasks
    helper the PUSH layer uses — ONE computation across both layers (P5, no drift). The graph index
    carries NO plan→task edge by design (tasks_citing keys only T-/D-/SPEC- ids, per _plan_tasks), so
    that side legitimately reads the canonical cites:<plan> field, NOT a parallel index. Output shape:
      {plans_pending_finalization: {<slug>: {citing_tasks_open: 0, closed_into: [...]}}, count: <int>}."""
    pending: dict = {}
    for slug, node in sorted((index.get("plans") or {}).items()):
        if not isinstance(node, dict):
            continue
        if node.get("kind") != "plan" or node.get("status") != "accepted":
            continue
        if _plan_open_citing_tasks(slug):
            continue   # still has open work — not yet a finalization candidate
        rec = {"citing_tasks_open": 0}
        closed_into = node.get("closed_into") or []
        if closed_into:
            rec["closed_into"] = sorted(str(c) for c in closed_into)
        pending[slug] = rec
    return {"plans_pending_finalization": pending, "count": len(pending)}

def _view_postcheck_plans_readiness(index: dict, *, AUDIT_VERDICT_CLOSURE_OK=None, DECISIONS_DIR=None, EVENTS_PATH=None, PLANS_DIR=None, SPEC_ABANDONED_TERMINAL=None, _dispositionless_infra_closures=None, _find_draft=None, _last_triage_watermark=None, _plan_corpus_signature=None, _plan_specs=None, _plan_task_carrier=None, _postcheck_probe_block_declared=None, _read_yaml=None, _retire_on_proof_unresolved=None, _scan_captures=None, _split_frontmatter=None) -> dict:
    """postcheck-plans-readiness lens (T-0483, triage promote fingerprint
    no-view-postcheck-plans-exit-status-grep-fallback N=2). For every plan at status==postcheck
    (index["plans"], kind:plan), report its realize-readiness against the 3 CODED realize-exit clauses
    the `plan stage realized` close-gate enforces (`_plan_close_core` realized path), PLUS a clearly-
    labelled `postcheck_probe_block_declared` ADVISORY. This RETIRES the manual grep the 2026-06-06 Review
    sweep ran by hand across all 7 postcheck plans.

    The 3 coded clauses are RE-DERIVED from the SAME canonical helpers the gates read — the view NEVER
    calls the `_die`-ing gate functions (`_require_plan_finalization_ready` etc.), it recomputes the same
    booleans for a NON-BLOCKING report (P5, one computation, no drift; D-0053 report-not-block):
      - finalization_ready          — every `_plan_specs` spec REACHED `active` (active/superseded/retired,
                                      the SPEC_REACHED_ACTIVE whitelist) AND a `decisions/<slug>-audit-post.yaml`
                                      exists with verdict ∈ GREEN/YELLOW AND its corpus_signature equals the
                                      current `_plan_corpus_signature(slug, body)` AND its recorded `tasks:`
                                      carrier equals the current `_plan_task_carrier(slug)` — the exact
                                      conjunction `_require_plan_finalization_ready` enforces (specs-active +
                                      fresh GREEN aggregate audit). A spec-bearing plan with no corpus
                                      (`_plan_specs` empty) is vacuously finalization-ready (the gate `return`s
                                      early for a task-only plan — backward-compat).
      - retire_on_proof_resolved    — every `_plan_retire_on_proof` member is TERMINAL (`done`|`wont-do`;
                                      the old mechanism retired — `_require_plan_retire_on_proof_resolved`).
      - captures_routed             — ADVISORY (T-0644 / Option B): zero un-routed `deviation_captured`
                                      since the last triage watermark (`_last_triage_watermark` +
                                      `_scan_captures`, GLOBAL backlog, the exact window the now-advisory
                                      `_require_captures_routed` reads). REPORTED, with `unrouted_captures`
                                      (the count), but NOT a realize_ready clause — the realize-EXIT gate
                                      WARNs, it no longer blocks (report-not-block, D-0040 / non-goal #7).
    realize_ready = the TWO gating clauses (finalization_ready + retire_on_proof_resolved). `blockers` names
    the failing gating clause(s) for the at-a-glance read. captures_routed + postcheck_probe_block_declared +
    dispositionless_infra_closures (T-0670) are reported SEPARATELY as advisories and are NOT part of
    realize_ready (owner-judgement support, not gates).
      - dispositionless_infra_closures — ADVISORY (T-0670 backstop, SPEC-0034 §postcheck → SPEC-0053):
                                      the plan's infra-class cited tasks (`_plan_tasks` ∩ done ∩ class:infra)
                                      whose `task_closed` recorded NO `propagation_disposition`
                                      (`_dispositionless_infra_closures`). Post-SPEC-0053 a fresh such close
                                      is structurally impossible (the presence-gate), so this surfaces ONLY
                                      legacy/emergency-bypass anomalies. REPORTED, never a realize_ready gate
                                      — read-only detection, NOT a second enforcement path (non-goal #7).

    Pure read, recomputed fresh, writes nothing (D-0053). The plan body (for the corpus signature + the
    advisory) is read from the canonical `plans/<slug>.md` via `_split_frontmatter`; a missing/malformed
    plan file is surfaced as `plan_file_readable: false` + a blocker rather than killing the listing
    (tolerant, like the other views) — it is NOT a realize_ready gate (realize_ready = the 2 coded gating
    clauses only — T-0644 dropped captures_routed to advisory). Output:
      {postcheck_plans: {<slug>: {realize_ready, finalization_ready, retire_on_proof_resolved,
                                  captures_routed (advisory), unrouted_captures (advisory count),
                                  plan_file_readable, postcheck_probe_block_declared (advisory),
                                  dispositionless_infra_closures (advisory, T-0670),
                                  blockers:[...]}},
       count: <int>}."""
    # captures_routed is plan-independent (the GLOBAL since-watermark backlog) — compute ONCE.
    prior = _last_triage_watermark(EVENTS_PATH)
    unrouted = [c for c in _scan_captures(EVENTS_PATH)
                if c["type"] == "deviation_captured" and (prior is None or c["ts"] > prior)]
    captures_routed = not unrouted

    out: dict = {}
    for slug, node in sorted((index.get("plans") or {}).items()):
        if not isinstance(node, dict):
            continue
        if node.get("kind") != "plan" or node.get("status") != "postcheck":
            continue
        rec: dict = {}
        blockers: list = []
        # load the plan body (corpus signature + advisory) — tolerant per-plan
        path = _find_draft(slug, dirs=(PLANS_DIR,))
        body = ""
        read_error = None
        if path is None:
            read_error = "plan file not found in plans/"
        else:
            try:
                _fm, body = _split_frontmatter(path)
            except SystemExit as exc:   # _split_frontmatter _die()s on malformed frontmatter
                read_error = f"malformed plan file ({exc})"

        # --- clause (a): finalization_ready — specs-active + fresh GREEN/YELLOW aggregate audit ---
        # T-0627: mirror the gate's deliberate-terminal exemption (SPEC_ABANDONED_TERMINAL) so this
        # read-only view recomputes the SAME boolean `_require_plan_finalization_ready` enforces (P5, no
        # view↔gate drift): a withdrawn/rejected corpus spec is exempt; unknown still counts as non-active.
        specs = _plan_specs(slug)
        non_active = [sid for sid, st in specs
                      if st not in ("active", "superseded", "retired")
                      and st not in SPEC_ABANDONED_TERMINAL]
        fin_reasons: list = []
        if non_active:
            fin_reasons.append(f"specs not reached-active: {', '.join(non_active)}")
        if specs:   # spec-bearing → the audit-post gate applies (task-only plan skips it, gate `return`s early)
            ap = DECISIONS_DIR / f"{slug}-audit-post.yaml"
            if not ap.exists():
                fin_reasons.append("no `audit post --plan` verdict on record")
            else:
                av = _read_yaml(ap) or {}
                verdict = str(av.get("verdict") or "").upper()
                if verdict not in AUDIT_VERDICT_CLOSURE_OK:
                    fin_reasons.append(f"aggregate audit verdict {verdict or 'MISSING'} (need GREEN/YELLOW)")
                else:
                    recorded_sig = av.get("corpus_signature")
                    if not recorded_sig:
                        fin_reasons.append("aggregate audit predates corpus_signature (re-run)")
                    elif read_error is not None:
                        fin_reasons.append("cannot verify corpus_signature (" + read_error + ")")
                    elif recorded_sig != _plan_corpus_signature(slug, body):
                        fin_reasons.append("aggregate audit stale (corpus_signature mismatch)")
                    if list(av.get("tasks") or []) != _plan_task_carrier(slug):
                        fin_reasons.append("aggregate audit stale (implementing-task set changed)")
        finalization_ready = not fin_reasons

        # --- clause (b): retire_on_proof_resolved — every retire-on-proof task TERMINAL (done|wont-do) ---
        # Same single-source predicate the realize-EXIT gate uses (P5 — byte-for-byte parity, no drift #10).
        retire_unresolved = _retire_on_proof_unresolved(slug)
        unresolved = [f"{tid}({st})" for tid, st in retire_unresolved]
        retire_on_proof_resolved = not retire_unresolved

        # `realize_ready` mirrors EXACTLY the 3 coded `plan stage realized` exit clauses — no hidden
        # fourth gate (audit-post pass-2 F0). A missing/malformed plan file is surfaced as its OWN explicit
        # `plan_file_readable: false` field + a blocker (loud, not hidden): for a spec-bearing plan it
        # already fails finalization_ready (the signature can't be verified — "cannot verify
        # corpus_signature (...)"), and for a task-only plan it shows as a visible non-readable flag the
        # reader weighs, NOT a silent extra AND-term that contradicts the documented 3-clause contract.
        # T-0644 / Option B: captures_routed is DEMOTED to an ADVISORY — it is NO LONGER one of the
        # realize_ready clauses (the `_require_captures_routed` realize-EXIT gate now WARNs, does not
        # block). realize_ready = the 2 CODED gating clauses only; captures_routed + its un-routed count
        # stay REPORTED (like postcheck_probe_block_declared) so the COUNT is visible, but never gate.
        rec["realize_ready"] = bool(finalization_ready and retire_on_proof_resolved)
        rec["finalization_ready"] = finalization_ready
        rec["retire_on_proof_resolved"] = retire_on_proof_resolved
        rec["captures_routed"] = captures_routed                       # ADVISORY (not a realize_ready gate)
        rec["unrouted_captures"] = len(unrouted)                       # ADVISORY count (global backlog)
        rec["plan_file_readable"] = read_error is None   # explicit (not a realize_ready gate)
        rec["postcheck_probe_block_declared"] = _postcheck_probe_block_declared(body)   # ADVISORY
        # T-0670 backstop ADVISORY (SPEC-0034 §postcheck → references SPEC-0053): infra cited tasks
        # that CLOSED with no propagation_disposition (legacy/emergency-bypass anomalies; SPEC-0053's
        # presence-gate makes a fresh such close impossible). REPORTED, never a realize_ready gate —
        # read-only detection, not a second enforcement path (CHARTER non-goal #7).
        rec["dispositionless_infra_closures"] = _dispositionless_infra_closures(slug)   # ADVISORY
        if not finalization_ready:
            blockers.append("finalization: " + "; ".join(fin_reasons))
        if not retire_on_proof_resolved:
            blockers.append("retire-on-proof not terminal (done|wont-do): " + ", ".join(unresolved))
        if read_error is not None:
            blockers.append(read_error)
        if blockers:
            rec["blockers"] = blockers
        out[slug] = rec
    return {"postcheck_plans": out, "count": len(out)}

def usage_token_classes(u: dict) -> dict:
    """The SINGLE transcript-usage parse home (CHARTER §P5 / SPEC-0115 §1) — extract the five token
    classes from ONE provider `message.usage` record. The cache-WRITE split: when `cache_creation`
    carries the per-tier `ephemeral_5m/1h_input_tokens` breakdown use it exactly; else fall back to the
    aggregate `cache_creation_input_tokens` at the default 5m tier (token-rollup F0 behaviour, preserved
    byte-identically). Both `_view_token_rollup` (cumulative cost) and `session context` (last-turn
    occupancy) call THIS — neither re-parses a usage record (resolves the second-parser-home concern)."""
    cc = u.get("cache_creation")
    if isinstance(cc, dict):       # per-tier split present — exact
        w5 = cc.get("ephemeral_5m_input_tokens") or 0
        w1 = cc.get("ephemeral_1h_input_tokens") or 0
    else:                          # fallback: aggregate at the default 5m tier
        w5 = u.get("cache_creation_input_tokens") or 0
        w1 = 0
    return {
        "input_tokens": u.get("input_tokens") or 0,
        "output_tokens": u.get("output_tokens") or 0,
        "cache_read_tokens": u.get("cache_read_input_tokens") or 0,
        "cache_write_5m_tokens": w5,
        "cache_write_1h_tokens": w1,
    }

def _provider_of(model: str):
    """Normalized `provider` vocab (SPEC-0025) from a model-id PREFIX: claude-* → anthropic,
    gpt* → openai, else None. Mirrors the documented model→provider rule (bin/pricing-config.yaml
    `provider_subscription:` comment) + the bench sibling window_utilization.provider_of — same
    rule, two non-cross-importable runtime worlds (bin/lib vs dev-utilities/bench). Kept tiny +
    prefix-only so the two stay trivially in sync; the rule's SoT is the config comment / SPEC-0025."""
    m = str(model or "")
    if m.startswith("claude-"):
        return "anthropic"
    if m.startswith("gpt"):
        return "openai"
    return None

def price_tokens(rates_by_model: dict, rates_by_provider: dict, model: str, tok: dict):
    """Read-time cost (USD) for one model's token totals — the SINGLE pricing-lookup home
    (T-0394/T-0377 read-time cost, SPEC-0135 source-fact-vs-derived-cost: cost is DERIVED, never
    stored). Resolution order: the EXACT model rate in `rates_by_model` FIRST (byte-identical to
    the historical per-model path — no long_context tiering here, that lives in the bench scorecard,
    not token-rollup); only when the model is ABSENT, fall back to the model's PROVIDER-level rate
    in `rates_by_provider` (provider via `_provider_of`, keyed by the SPEC-0025 provider vocab).
    Returns None (unpriced — never guessed) when neither resolves. A pure function of its args →
    fixture-testable with NO transcript archive (T-10126 acceptance #2)."""
    r = (rates_by_model or {}).get(model)
    if not isinstance(r, dict):
        prov = _provider_of(model)
        r = (rates_by_provider or {}).get(prov) if prov else None
    if not isinstance(r, dict):
        return None
    cost = (tok["input_tokens"] * r.get("input", 0)
            + tok["output_tokens"] * r.get("output", 0)
            + tok["cache_read_tokens"] * r.get("cache_read", 0)
            + tok["cache_write_5m_tokens"] * r.get("cache_write_5m", 0)
            + tok["cache_write_1h_tokens"] * r.get("cache_write_1h", 0))
    return round(cost / 1_000_000, 4)

def _rollup_unavailable_totals(status: str) -> dict:
    """The `totals` block of an honest-degrade rollup (T-10743, X-0594) — the SAME keys a healthy rollup
    carries, but every value the self-describing string `n/a (<status>)` instead of a number.

    WHY NOT ZERO (the fix): both degrade builders used to fill these keys with numeric 0 / 0.0. The
    `status` key made the unavailability legible to a CALLER that branches on it (both in-repo consumers
    do — `_view_observation`, `_view_task_scorecard`), but the reader who sees the RENDERED totals — the
    human running `graph query token-rollup`, and the T4 cost-per-closed-task axis — read a real,
    measured zero-cost result off a checkout that simply has no data. Fail-closed is a property of a USE
    SITE, not of a parse result (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): the
    reader's use site is the value itself, so the value has to carry the absence. SPEC-0135's own
    init_concern already decrees the target — the degrade is 'never a silent zero-cost reading' and 'the
    cost dimension stays n/a on that project'; this makes the figures conform to that text.

    A non-numeric value is deliberate, not merely cosmetic: arithmetic on an unavailable total now raises
    at the mis-use site instead of silently summing to a plausible number. The KEYS are unchanged, so the
    uniform-shape / never-KeyError contract both degrade builders promise still holds. ONE home for the
    block so the two degrade paths cannot drift apart (CHARTER §Principle 5)."""
    na = f"n/a ({status})"
    return {"input_tokens": na, "output_tokens": na, "cache_read_tokens": na,
            "cache_write_5m_tokens": na, "cache_write_1h_tokens": na,
            "cost_usd_priced_sessions": na}

def _rollup_archive_absent(status: str, reason: str, rsync_fix: str) -> dict:
    """The token-rollup HONEST-DEGRADE outcome (T-10454, X-0315): a fail-closed NAMED unavailability
    returned when .yitc/transcript-archive is missing/empty/stale on a consumer that has not populated it
    (the SPEC-0135 declare-or-waive archive-population duty). NOT a silent zero and NOT a crash — the
    `status` key (absent on a healthy rollup) names the unavailability, and every token/cost figure is a
    NAMED-UNAVAILABLE string (`n/a (<status>)`, T-10743) rather than a zero a reader could mistake for a
    measured zero-cost result. Uniform rollup shape (same keys as the healthy return) so existing
    consumers never KeyError; a caller may still branch on `status`."""
    return {
        "status": status,                       # archive_missing | archive_empty | archive_stale
        "reason": f"token-rollup unavailable: {reason}",
        "fix": rsync_fix,
        "concern": "SPEC-0135 archive-population duty (declare-or-waive init_concern)",
        "sessions": {},
        "session_count": 0,
        "totals": _rollup_unavailable_totals(status),   # T-10743: n/a strings, never a misleading 0
        "unpriced_models": [],
        "estimate": True,
    }

def _rollup_pricing_absent(cfg_path, ENGINE_ROOT) -> dict:
    """The token-rollup HONEST-DEGRADE outcome for a MISSING pricing config (T-10526): the engine-owned
    `bin/pricing-config.yaml` resolved on NEITHER REPO_ROOT (own copy) NOR ENGINE_ROOT — a real kernel
    breakage (the engine's own config deleted), never a normal consumer state. NOT a silent `{}` that would
    price every session at $0 and read as a real, cheap rollup — a fail-closed NAMED unavailability instead,
    same uniform shape + named-unavailable figures as `_rollup_archive_absent` (T-10743: `n/a (<status>)`
    strings, so the totals block itself cannot be read as a measured $0) so consumers never KeyError and a
    caller may still branch on `status` (SPEC-0115 §5 config home)."""
    _eng = (str(Path(ENGINE_ROOT) / "bin" / "pricing-config.yaml")
            if ENGINE_ROOT is not None else "<no ENGINE_ROOT injected>")
    return {
        "status": "pricing_config_missing",
        "reason": f"token-rollup unavailable: pricing-config.yaml resolved on neither REPO_ROOT ({cfg_path}) "
                  f"nor ENGINE_ROOT ({_eng}) — costs cannot be priced (they would read a misleading $0).",
        "fix": f"restore the engine-owned bin/pricing-config.yaml (SPEC-0115 §5 config home) at {_eng}",
        "concern": "SPEC-0115 §5 pricing-config home",
        "sessions": {},
        "session_count": 0,
        "totals": _rollup_unavailable_totals("pricing_config_missing"),   # T-10743
        "unpriced_models": [],
        "estimate": True,
    }

def _view_token_rollup(index: dict, *, REPO_ROOT=None, _die=None, _kernel_content_file=None,
                       _read_yaml=None, ENGINE_ROOT=None, _main_worktree=None,
                       only_sessions=None) -> dict:
    """token-rollup lens (T-0394, the T-0377 reroute read-side): per-session token usage + read-time
    cost from RAW provider transcripts — NOT from the journal (no session_usage event exists; owner
    2026-06-05: archive the raw sources, compute at read-time, price never stored). Pure read, no
    store, recomputed fresh (D-0053). Sources: <main-checkout>/.yitc/transcript-archive/*/*.jsonl UNION live
    ~/.claude/projects/*/*.jsonl, deduped by session uuid — newest mtime wins, tie -> archive (the
    stable source; audit-pre pass-2 F1 absorption — deterministic, not size-based). Pre-flight
    HONEST-DEGRADES on missing/empty/stale archive (T-10454, X-0315): returns a fail-closed NAMED
    outcome (`status: archive_missing|archive_empty|archive_stale`, figures rendered `n/a (<status>)`
    rather than zeroed — T-10743/X-0594) via
    _rollup_archive_absent instead of aborting — never a silent zero, never a crash; the fix = the
    Duty-1 rsync (the SPEC-0135 declare-or-waive archive-population duty), named in the outcome. The
    kernel populates its own archive so it never reaches the degrade branch (byte-identical rollup).
    `_die` is retained in the signature (unused — like `index`) for the uniform lens signature. Cost:
    per-model rates from bin/pricing-config.yaml (estimate-marked
    owner data); cache_creation priced PER TIER via the usage.cache_creation 5m/1h split when
    present, else aggregate x 5m rate (audit-pre pass-2 F0 absorption); a model absent from the
    per-model table falls back to its PROVIDER-level rate (rates_per_provider, keyed by the SPEC-0025
    provider vocab — T-10126); only a model whose provider is ALSO unknown -> cost null +
    unpriced_models (never a guess). `index` is unused (lens reads raw transcripts, not the graph) —
    kept for the uniform _run_view lens signature.

    T-10646: the archive resolves on the CANONICAL MAIN checkout, not the current one. `.yitc/` is
    gitignored (.gitignore:27/:56), so a task worktree NEVER carries the archive — it is a
    main-checkout-only store by construction, not per-checkout state. Resolving it off the running
    checkout made every worktree run return the `archive_missing` degrade below on a FALSE premise
    (session_count 0 + zeroed costs from a worktree; live data from main — the fp
    transcript-archive-views-per-checkout-worktree-blind), and made the degrade's own `fix:` string
    point the reader at a gitignored, land-destroyed worktree path. So resolve via the shipped
    canonical-main idiom `(_main_worktree(X) or X)` — the same routing the sibling main-resolved
    store reads use (the events.jsonl fold + `_main_task_status` + the cross self_name in bin/yitc-v2)
    — rather than a parallel resolver (CHARTER §P1 F1). Generalizes under `-C <consumer>`: REPO_ROOT
    is then the consumer path, so `_main_worktree` resolves THAT repo's main. The `or REPO_ROOT`
    fallback keeps a self-contained checkout (a temp test repo, a repo with no separate main
    worktree) reading REPO_ROOT — so the T-10454 honest-degrade branches stay fully reachable for a
    TRUE absence and that contract is unweakened. `_main_worktree` absent (not injected) = no
    resolution: an explicitly-injected REPO_ROOT stays authoritative, which is what the unit tests
    rely on to control archive presence.

    T-11143: `only_sessions` (optional set of session ids) narrows WHICH transcripts are OPENED. The
    default None is today's behaviour byte-for-byte — every caller that wants the whole corpus passes
    nothing. `_view_task_scorecard` is the one caller that does NOT: it resolves exactly ONE session
    ref and reads only `sessions[<that sid>]`, yet was paying a full-corpus parse to get it (measured
    2026-08-15 on this checkout: 9,662 chosen sessions / 6.7GB / 2.3M json.loads, 94% of a 35.5s
    `graph query task-scorecard T-0391`). Each session's entry is computed independently from its own
    file in the loop below — no cross-session state feeds a session's figures — so a narrowed run
    yields a bit-for-bit identical `sessions[sid]`. The filter is applied AFTER the archive/live
    dedupe and AFTER the pre-flight above, so the T-10454 honest-degrade branches and the pricing
    read are reached identically whatever the filter says (they read the archive glob, never
    `chosen`). It narrows reading only; it retains nothing between runs — NOT a cache layer (GRAPH
    §What graph is NOT). The corpus-wide keys it necessarily narrows (`session_count`, `totals`,
    `unpriced_models`) are read by no caller that passes a filter."""
    import json as _json
    archive_root = (_main_worktree(REPO_ROOT) or REPO_ROOT) if _main_worktree is not None else REPO_ROOT
    archive_dir = archive_root / ".yitc" / "transcript-archive"
    # --- pre-flight (fail-closed, HONEST-DEGRADE): missing OR empty OR stale > 1 day (T-10454, X-0315).
    # The archive-population duty is declare-or-waive on a consumer (SPEC-0135 init_concern); the kernel
    # populates its own (nightly Duty-1 rsync) so it never reaches these branches → byte-identical below.
    # Rather than _die (an ABORT that crashes every caller + makes the whole cost dimension unmeasurable),
    # return a NAMED honest-degrade outcome: a fail-closed named unavailability — never a silent zero-cost
    # reading, never a crash. The `status` key (absent on a healthy rollup) is the degrade discriminator. --
    # T-10646: built from `archive_dir` — hence from `archive_root` — so a TRUE-absence degrade points the
    # reader at the CANONICAL MAIN archive, never at the gitignored (land-destroyed) worktree path the
    # pre-fix string named. Asserted both directions in tests/test_t10646_rollup_main_store_resolution.py.
    rsync_fix = ("fix: rsync -a ~/.claude/projects/ " + str(archive_dir) + "/  "
                 "(Duty 1, plans/cron-auto-sessions-duty-roster-transcript-archive-.md; "
                 "declare-or-waive: SPEC-0135 init_concern)")
    if not archive_dir.is_dir():
        return _rollup_archive_absent("archive_missing", f"archive dir missing ({archive_dir})", rsync_fix)
    archived = sorted(archive_dir.glob("*/*.jsonl"))
    if not archived:
        return _rollup_archive_absent("archive_empty", f"archive dir empty ({archive_dir})", rsync_fix)
    newest = max(p.stat().st_mtime for p in archived)
    if (time.time() - newest) > 86400:
        return _rollup_archive_absent("archive_stale",
                                      "archive stale (newest transcript mtime > 1 day)", rsync_fix)

    # T-9313 (F-018): engine-owned DATA -> ENGINE path under -C. T-10526: `_kernel_content_file` alone is
    # NOT enough where REPO_ROOT's OWN copy is absent (a -C worktree, or a land that removed it) — the own
    # path then does not exist and the config would silently read as `{}`, degrading EVERY rate lookup to
    # unpriced with no warning. ENGINE_ROOT is captured at import and never rebound by -C, so it survives the
    # removal: fall back to the engine copy (the session._load_pricing_cfg fix, T-10495). Absent on BOTH
    # roots (a real kernel breakage — the engine's own pricing-config deleted) is a NAMED honest-degrade, NOT
    # a silent {} that zeroes every cost (the _rollup_archive_absent precedent above).
    cfg_path = _kernel_content_file("bin/pricing-config.yaml")
    if not cfg_path.exists() and ENGINE_ROOT is not None:
        engine_cfg = Path(ENGINE_ROOT) / "bin" / "pricing-config.yaml"
        if engine_cfg.exists():
            cfg_path = engine_cfg
    if not cfg_path.exists():
        return _rollup_pricing_absent(cfg_path, ENGINE_ROOT)
    cfg = _read_yaml(cfg_path)
    rates = (cfg.get("rates_per_mtok") or {}) if isinstance(cfg, dict) else {}
    rates_prov = (cfg.get("rates_per_provider") or {}) if isinstance(cfg, dict) else {}  # T-10126 provider-level fallback

    live = sorted(Path.home().glob(".claude/projects/*/*.jsonl"))
    # dedupe by session uuid (filename stem): newest mtime wins; tie -> archive copy.
    chosen: dict = {}
    for p in list(archived) + list(live):
        sid = p.stem
        prev = chosen.get(sid)
        if prev is None:
            chosen[sid] = p
            continue
        m_new, m_old = p.stat().st_mtime, prev.stat().st_mtime
        if m_new > m_old or (m_new == m_old and archive_dir in p.parents):
            chosen[sid] = p

    # T-11143: narrow to the requested sessions BEFORE the read loop, so an unwanted transcript is
    # never opened. Applied after the dedupe so the surviving entry is the SAME file the unfiltered
    # run would have chosen — the filter selects, it never re-resolves.
    if only_sessions is not None:
        chosen = {sid: p for sid, p in chosen.items() if sid in only_sessions}

    def _price(model: str, tok: dict):
        return price_tokens(rates, rates_prov, model, tok)   # T-10126: model rate first, then provider fallback

    sessions: dict = {}
    unpriced: set = set()
    for sid, path in sorted(chosen.items()):
        per_model: dict = {}
        ts_first = ts_last = None
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        rec = _json.loads(line)
                    except ValueError:
                        continue
                    ts = rec.get("timestamp") or rec.get("ts")
                    if isinstance(ts, str):
                        ts_first = ts if ts_first is None else min(ts_first, ts)
                        ts_last = ts if ts_last is None else max(ts_last, ts)
                    msg = rec.get("message") or {}
                    u = msg.get("usage")
                    if not isinstance(u, dict):
                        continue
                    model = msg.get("model") or "unknown"
                    t = per_model.setdefault(model, {
                        "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                        "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0})
                    for _cls, _n in usage_token_classes(u).items():   # SINGLE parse home (P5)
                        t[_cls] += _n
        except OSError:
            continue
        if not per_model:
            continue   # transcript carries no usage records (non-conversation file) — skip
        costs = []
        for model, tok in per_model.items():
            c = _price(model, tok)
            tok["cost_usd"] = c
            if c is None:
                unpriced.add(model)
            else:
                costs.append(c)
        totals = {k: sum(m[k] for m in per_model.values())
                  for k in ("input_tokens", "output_tokens", "cache_read_tokens",
                            "cache_write_5m_tokens", "cache_write_1h_tokens")}
        totals["cost_usd"] = round(sum(costs), 4) if costs and len(costs) == len(per_model) else None
        sessions[sid] = {"project": path.parent.name, "ts_first": ts_first, "ts_last": ts_last,
                         "models": per_model, "totals": totals}
    grand = {k: sum(s["totals"][k] for s in sessions.values())
             for k in ("input_tokens", "output_tokens", "cache_read_tokens",
                       "cache_write_5m_tokens", "cache_write_1h_tokens")}
    priced = [s["totals"]["cost_usd"] for s in sessions.values() if s["totals"]["cost_usd"] is not None]
    grand["cost_usd_priced_sessions"] = round(sum(priced), 4)
    return {
        "sessions": sessions,
        "session_count": len(sessions),
        "totals": grand,
        "unpriced_models": sorted(unpriced),
        "rates_source": (cfg.get("rates_source") if isinstance(cfg, dict) else None)
                        or "bin/pricing-config.yaml missing — all models unpriced",
        "estimate": True,   # cost is rates-table-derived, never an invoice figure
    }

def _ev_dt(ts, *, _parse_iso_utc=None):
    """Event `ts` (ISO string) → tz-aware UTC datetime, or None if absent/unparseable. Best-effort
    (the journal is the source of truth; a malformed ts is skipped, not fatal)."""
    if not isinstance(ts, str):
        return None
    try:
        return _parse_iso_utc(ts)
    except ValueError:
        return None

def _median(vals: list):
    """Median of a numeric list (None for empty). Plain, stdlib-free (statistics import avoided for
    the uniform lens-helper style)."""
    s = sorted(v for v in vals if v is not None)
    if not s:
        return None
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else round((s[mid - 1] + s[mid]) / 2, 2)

def _dur_stats(vals: list, *, _median=None):
    """min/median/max over a duration list, or the string 'n/a' when empty (the never-silently-drop
    contract — an empty trend is VISIBLE, not absent)."""
    nums = [v for v in vals if isinstance(v, (int, float))]
    if not nums:
        return "n/a"
    return {"min": min(nums), "median": _median(nums), "max": max(nums), "n": len(nums)}

def _view_trend_report(index: dict, since=None, until=None, *, EVENTS_PATH=None, TASKS_DIR=None, _dur_stats=None, _ev_dt=None, _median=None, _read_yaml=None) -> dict:
    """trend-report lens (T-0396, PART-2 scope 2): L4 system-trend report over a [since, until) date
    window — the D-0087 ревизия feed. JOURNAL-ONLY: pure f over events.jsonl (full `data` payloads,
    which the slim graph-index `events` projection lacks) + the committed `index` for current task
    STATUS counts (a derived journal+corpus projection, NOT a second authored store — audit-pre
    pass-2 F1). Reads nothing else, writes nothing (D-0053: store the query, recompute fresh).

    Window: `since`/`until` are tz-aware UTC datetimes (normalized by _parse_iso_utc — audit-pre
    pass-2 F0); since INCLUSIVE, until EXCLUSIVE; either may be None (open-ended). Every section
    reports numeric values OR an explicit `n/a` — an empty section is NEVER silently dropped (the
    central correctness point + the task probe)."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)

    def _in_window(dt) -> bool:
        if dt is None:
            return False
        if since is not None and dt < since:
            return False
        if until is not None and dt >= until:
            return False
        return True

    # --- single journal pass: collect the windowed events we need (full data payloads) ---
    win = []                         # (type, dt, data) for in-window events
    total_events = 0                 # whole-journal size (growth baseline)
    leak_total = 0                   # whole-journal non-cli-source residue
    filed_ts: dict = {}              # task_id -> earliest task_filed dt (any time)
    picked_ts: dict = {}             # task_id -> earliest task_picked dt (any time)
    closed_ts: dict = {}             # task_id -> latest task_closed dt (any time)
    if EVENTS_PATH.exists():
        for line in journal_mod.segment_lines(EVENTS_PATH, errors="replace"):  # T-11444: segment-aware fold (SPEC-0190 r4)
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            total_events += 1
            d = e.get("data") if isinstance(e.get("data"), dict) else {}
            if d.get("source") != "yitc-v2-cli":
                leak_total += 1
            t = e.get("type")
            dt = _ev_dt(e.get("ts"))
            tid = e.get("task") or e.get("task_id")
            # whole-history task milestones (for queue-flow latency — not window-clipped on the
            # FILED side, since a task filed before the window may be picked inside it)
            if t == "task_filed" and tid and dt is not None:
                filed_ts[tid] = dt if tid not in filed_ts else min(filed_ts[tid], dt)
            elif t == "task_picked" and tid and dt is not None:
                picked_ts[tid] = dt if tid not in picked_ts else min(picked_ts[tid], dt)
            elif t == "task_closed" and tid and dt is not None:
                closed_ts[tid] = dt if tid not in closed_ts else max(closed_ts[tid], dt)
            if _in_window(dt):
                win.append((t, dt, d, tid))

    win_count = len(win)
    win_leak = sum(1 for (_t, _dt2, d, _tid) in win if d.get("source") != "yitc-v2-cli")

    # ---- journal section ----
    span_days = None
    if since is not None or until is not None:
        lo = since or (min((w[1] for w in win), default=now))
        hi = until or now
        span_days = max((hi - lo).total_seconds() / 86400.0, 0.0)
    growth_per_day = round(win_count / span_days, 2) if span_days and span_days > 0 else "n/a"
    journal = {
        "events_total_all_time": total_events,
        "events_in_window": win_count,
        "growth_per_day": growth_per_day,
        "test_leak_share_all_time": (round(leak_total / total_events, 4) if total_events else "n/a"),
        "test_leak_share_in_window": (round(win_leak / win_count, 4) if win_count else "n/a"),
        "leak_definition": "events whose data.source != 'yitc-v2-cli' (legacy/non-CLI residue, T-0357 leak proxy)",
    }

    # ---- durations section (PART-1 fields, T-0358/T-0375) ----
    graph_ms, suite_ms, land_ms, verify_ms = [], [], [], []
    for (t, _dt2, d, _tid) in win:
        if t == "graph_built" and isinstance(d.get("duration_ms"), (int, float)):
            graph_ms.append(d["duration_ms"])
        elif t == "tests_passed" and isinstance(d.get("duration_ms"), (int, float)):
            suite_ms.append(d["duration_ms"])
        elif t == "land_completed":
            if isinstance(d.get("duration_ms"), (int, float)):
                land_ms.append(d["duration_ms"])
            if isinstance(d.get("verify_duration_ms"), (int, float)):
                verify_ms.append(d["verify_duration_ms"])
    durations = {
        "graph_build_ms": _dur_stats(graph_ms),
        "suite_ms": _dur_stats(suite_ms),
        # T-12008: a POINTER, deliberately not a second per-stage table here. These four figures are
        # OPERATION durations (what one suite / land / build costs); the per-STAGE decomposition of a
        # task's lifecycle is a different question with its own home, and duplicating it here would
        # give it two homes that drift (CHARTER §P1 F3 — one home).
        "per_stage_cost": "see `graph query stage-profile [--since <date>]` — per-stage n/median/p90/sum "
                          "over the tasks closed in a window, with each stage's machine-time share",
        "land_ms": _dur_stats(land_ms),
        "land_verify_ms": _dur_stats(verify_ms),
    }

    # ---- queue_flow section ----
    # filed->picked latency for tasks PICKED in the window (journal milestones)
    latencies = []
    for tid, p in picked_ts.items():
        if _in_window(p) and tid in filed_ts and p >= filed_ts[tid]:
            latencies.append(round((p - filed_ts[tid]).total_seconds() / 86400.0, 2))
    throughput = sum(1 for (t, _dt2, _d, _tid) in win if t == "task_closed")
    # Task CORPUS read (created_at + class + status) — the AUTHORED task YAMLs are the source for
    # age, infra-detection, AND task STATUS (T-0492: re-sourced off the to-be-cut graph-index `tasks`
    # section onto the same authored SoT one layer earlier — CHARTER §P5, no parallel reader). The
    # corpus is a journal+authored projection, not a second store (the "journal-only" framing holds).
    # created_at falls back to the journal task_filed ts when a file lacks it.
    task_meta: dict = {}
    if TASKS_DIR.exists():
        for p in TASKS_DIR.glob("T-*.yaml"):
            d = _read_yaml(p)
            if isinstance(d, dict) and d.get("id"):
                task_meta[d["id"]] = {"created_at": _ev_dt(d.get("created_at")),
                                      "class": d.get("class"), "status": d.get("status")}

    def _task_born(tid):
        """Age origin for a task: authored created_at, else the journal task_filed ts."""
        m = task_meta.get(tid)
        return (m.get("created_at") if m else None) or filed_ts.get(tid)

    # status counts from the authored corpus (was index['tasks'] — T-0492 cut migration)
    status_counts: dict = {}
    for m in task_meta.values():
        st = m.get("status")
        status_counts[st] = status_counts.get(st, 0) + 1
    # WIP age: in-progress tasks (status from the corpus), now - earliest pick (journal), in days
    wip_ages = [round((now - picked_ts[tid]).total_seconds() / 86400.0, 2)
                for tid, m in task_meta.items()
                if m.get("status") == "in-progress" and tid in picked_ts]
    # parked/blocked AGING (audit-post pass-2 F1): the L4 contract is AGE, not a bare count — how
    # long has a stuck task been stuck (now - task birth). Counts kept alongside for context.
    def _age_stats_for_status(status: str):
        ages = [round((now - _task_born(tid)).total_seconds() / 86400.0, 1)
                for tid, m in task_meta.items()
                if m.get("status") == status and _task_born(tid) is not None]
        return ({"oldest": max(ages), "median": _median(ages), "n": len(ages)} if ages else "n/a")

    queue_flow = {
        "filed_to_picked_latency_days": ({"oldest": max(latencies), "median": _median(latencies),
                                          "n": len(latencies)} if latencies else "n/a"),
        "throughput_closed_in_window": throughput,
        "wip_age_days": ({"oldest": max(wip_ages), "median": _median(wip_ages), "n": len(wip_ages)}
                         if wip_ages else "n/a"),
        "parked_age_days": _age_stats_for_status("parked"),
        "blocked_age_days": _age_stats_for_status("blocked"),
        "ready_count": status_counts.get("ready", 0),
        "in_progress_count": status_counts.get("in-progress", 0),
    }

    # ---- adoption_debt section (AGING — audit-pre pass-1 F0 + audit-post pass-1 F0) ----
    # proposed-spec age: from the activation_owner_task's birth (authored created_at, else the
    # journal task_filed ts — the corpus fallback the audit flagged was missing).
    specs = index.get("specs", {}) if isinstance(index, dict) else {}
    prop_ages = []
    for sid, v in specs.items():
        if not isinstance(v, dict) or v.get("status") != "proposed":
            continue
        owner = v.get("activation_owner_task") or v.get("proposed_by")
        born = _task_born(owner) if owner else None
        if born is not None:
            prop_ages.append(round((now - born).total_seconds() / 86400.0, 1))
    # open infra follow-ups (audit-post F0): the FULL set of open (not-done, not-terminal) infra-class
    # tasks — the inspection's "built-but-not-invoked / adoption-debt" backlog — derived from the task
    # CLASS in the corpus, NOT title keyword matching.
    _OPEN_STATES = ("ready", "in-progress", "parked", "blocked")
    followup_ages = []
    for tid, m in task_meta.items():
        if m.get("class") != "infra" or m.get("status") not in _OPEN_STATES:
            continue
        born = _task_born(tid)
        if born is not None:
            followup_ages.append(round((now - born).total_seconds() / 86400.0, 1))
    adoption_debt = {
        "proposed_spec_age_days": ({"oldest": max(prop_ages), "median": _median(prop_ages),
                                    "n": len(prop_ages)} if prop_ages else "n/a"),
        "open_infra_followup_age_days": ({"oldest": max(followup_ages), "median": _median(followup_ages),
                                          "n": len(followup_ages)} if followup_ages else "n/a"),
    }

    # ---- churn section (LEADING indicator) ----
    reaudit_passes = 0
    land_aborts = 0
    for (t, _dt2, d, _tid) in win:
        if t in ("audit_pre_completed", "audit_post_completed", "external_audit_completed"):
            p = d.get("passes") if d.get("passes") is not None else d.get("pass")
            if isinstance(p, (int, float)) and p > 1:
                reaudit_passes += 1
        elif t == "land_completed" and d.get("status") == "abort":
            land_aborts += 1
    # post-close collateral: a commit_landed for a task AFTER its task_closed ts (window-scoped on the commit)
    post_close = 0
    for (t, dt, _d, tid) in win:
        if t == "commit_landed" and tid and tid in closed_ts and dt is not None and dt > closed_ts[tid]:
            post_close += 1
    # deviation recurrence: deviation_captured grouped by fingerprint, N>=2 (window-scoped)
    fp_counts: dict = {}
    for (t, _dt2, d, _tid) in win:
        if t == "deviation_captured":
            fp = d.get("fingerprint")
            if fp:
                fp_counts[fp] = fp_counts.get(fp, 0) + 1
    recurring_fp = {fp: n for fp, n in sorted(fp_counts.items(), key=lambda x: -x[1]) if n >= 2}
    churn = {
        "reaudit_multipass_events": reaudit_passes,
        "land_aborts": land_aborts,
        "post_close_collateral_commits": post_close,
        "recurring_deviation_fingerprints": (recurring_fp if recurring_fp else "n/a"),
    }

    # ---- overhead section ----
    # methodology-time proxy = suite + land (+verify) wall over the window; productive wall not
    # journal-derivable per-task, so report the proxy pieces + n/a the share (NO fabricated number).
    method_ms = sum(suite_ms) + sum(land_ms) + sum(verify_ms)
    overhead = {
        "methodology_ms_proxy": method_ms if method_ms else "n/a",
        "methodology_ms_breakdown": {"suite": sum(suite_ms), "land": sum(land_ms),
                                     "land_verify": sum(verify_ms)} if method_ms else "n/a",
        "productive_share": "n/a",
        "note": ("methodology-time proxy = suite + land (+verify) wall in window; productive wall is "
                 "not journal-derivable per task — share stays n/a, never fabricated"),
    }

    return {
        "window": {"since": since.isoformat() if since else None,
                   "until": until.isoformat() if until else None,
                   "span_days": round(span_days, 2) if span_days is not None else None},
        "journal": journal,
        "durations": durations,
        "queue_flow": queue_flow,
        "adoption_debt": adoption_debt,
        "churn": churn,
        "overhead": overhead,
    }

def _handbook_size_totals(*, REPO_ROOT=None, CANONICAL_DOCS=None) -> dict:
    """Aggregate size across the FULL generated HANDBOOK_READ_ORDER set — every split part included
    (CHARTER §Principle 2 cap surface; the set grows by SPEC-0120 splitting, so the members arrive
    INJECTED from the one carrier, never as a literal here — T-10356).

    Reports BOTH axes (T-10316): total LINES (the CHARTER §P2 cap's stated unit AND the gate) AND total
    BYTES (+ derived est_tokens, REPORT-ONLY). A dense seed set can sit under the 2500-LINE cap while its
    aggregate TOKEN weight — what a session actually pays to load at startup — runs past what the line
    number implies (density spread ~1.7x, T-10219). This mirrors, one altitude up, the per-doc byte axis
    T-10313 gave SPEC-0120 §3. Bytes→est_tokens reuses the SAME ~2.52 B/token calibration home as the
    per-doc probe (inspection.BYTES_PER_TOKEN — single source, T-10217). The owner ruled the byte axis
    stays report-only (owner_directive 2026-07-10, declining a token bound); est_tokens is never a gate
    input.

    Each axis is None when NO member is readable (reported n/a then — never a fabricated number)."""
    lines, nbytes, seen = 0, 0, False
    for f in (CANONICAL_DOCS or ()):
        p = REPO_ROOT / f
        if p.exists():
            seen = True
            raw = p.read_text(encoding="utf-8", errors="replace")
            lines += len(raw.splitlines())
            nbytes += len(raw.encode("utf-8"))
    if not seen:
        return {"lines": None, "bytes": None, "est_tokens": None}
    return {"lines": lines, "bytes": nbytes,
            "est_tokens": round(nbytes / inspection.BYTES_PER_TOKEN)}

def _view_displacement_retention(index: dict, *, DECISIONS_DIR=None, EVENTS_PATH=None, TASKS_DIR=None, SPECS_DIR=None, REPO_ROOT=None, ENGINE_ROOT=None, _closed_task_ids=None, _handbook_size_totals=None, _id_from_artifact_ref=None, _is_consumer_build=None, _read_yaml=None) -> dict:
    """displacement-retention lens (T-0527 / SPEC-0052): the FIRST step of an inspection launch + the
    weekly Review backstop. For EACH un-capped surface it MEASURES the current value AND looks up that
    surface's GOVERNING trigger (threshold + home), then flags `fired?` (value crossed the threshold)
    and `acted?` (a resolving action is on record). A `fired AND NOT acted` surface is a FLAGGED action
    (never a bare number) — the exact 2026-06-07 ревизия gap (measured events.jsonl=13.1MB but never
    checked it vs the D-0030 10 MB trigger). Pure read over the corpus + journal; writes nothing
    (D-0053: store the query, recompute fresh)."""
    # CURRENT-STATE acted? for the audit-YAML surface (audit-post F0): NOT a historical event (a single
    # past drain must NOT suppress a future real gap — that is the very measure-but-stale bug this lens
    # exists to kill). acted ⇔ NO closed-task audit YAML remains in the ACTIVE decisions/ lane right now,
    # i.e. the drain is CURRENTLY caught up. Computed fresh from disk below.
    # For surfaces whose remedy is a tracked task (CHARTER §Filing rule: file-for-later is the
    # sanctioned action), acted? is resolved from a DURABLE cited-task linkage (T-0540 / T-0527 audit-post F0), NOT loose
    # keyword text over title/scope: a remediation task must explicitly `cites:` the surface's governing
    # artifact to count as acted (the D-0086 §9 cites: LINK-RULE analog). This kills the keyword
    # false-positive where an unrelated open task that merely MENTIONS "events.jsonl" (as a probe
    # substrate) masked a real fired-unacted gap.
    _TERMINAL = ("done", "wont-do")
    open_task_cites: list = []        # each entry = one open task's cites list (strings)
    if TASKS_DIR.exists():
        for p in TASKS_DIR.glob("T-*.yaml"):
            d = _read_yaml(p)
            if isinstance(d, dict) and d.get("status") not in _TERMINAL:
                open_task_cites.append([str(c) for c in (d.get("cites") or [])])

    def _open_task_cites(token: str) -> bool:
        """True iff some open task `cites:` the surface's governing artifact `token`. An id-token
        (T-/D-/SPEC-) matches via the repo's one cite-id grammar (`_id_from_artifact_ref`); a
        handbook-home token (e.g. QUEUE.md / CHARTER.md, no id) matches a cites entry equal to it OR
        carrying a section anchor (`token#...`), case-insensitively."""
        tok_id = _id_from_artifact_ref(token)
        tl = token.lower()
        for cites in open_task_cites:
            for c in cites:
                if tok_id:
                    if _id_from_artifact_ref(c) == tok_id:
                        return True
                else:
                    cl = c.lower()
                    if cl == tl or cl.startswith(tl + "#"):
                        return True
        return False

    def _rotation_verdict_source():
        """The ONE file whose text carries this repo's standing rotation verdict — resolved,
        not hard-coded (T-10810 / X-0642). Two carriers, one per audience:

        - **`-C` CONSUMER** (`_is_consumer_build()` — a SEPARATE repository): the consumer's OWN
          `<repo>/yitc-ops.yaml` — the EXISTING per-project governed ops carrier (SPEC-0093
          rule 1: one file, one section per concern; same `Path(repo_root) / "yitc-ops.yaml"`
          idiom `_view_live_revision_drift` already uses). A consumer CANNOT carry the kernel
          spec file below: its filename embeds the KERNEL's spec id and a consumer may already
          own its own spec at that id (a second `SPEC-0190-*.yaml` would collide in the
          graph), so pre-T-10810 the acted disjunct was UNREACHABLE under `-C` and the only
          path left was an artificially-open sentinel task — the exact anti-pattern the
          standing-verdict token exists to retire.
        - **ENGINE-SELF** (the engine's own checkout OR any linked WORKTREE of it, or either root
          not injected): `SPECS_DIR/SPEC-0190-journal-physical-storage-contract-one-logical-jour.yaml`
          — the verdict's home since T-11447 re-homed §Rotation policy there out of SPEC-0002.
          Only the resolved FILENAME moved: same text scan, same tokens, same fail-closed bound.

        This widens WHERE the verdict may be read; it changes NOTHING about WHETHER one counts
        (the bound parse + size comparison below are untouched, so an unbounded or absent token
        still fails closed). No new store, no new file class, no new `yitc-ops.yaml` section or
        declare-or-waive concern: a consumer that records nothing simply reads not-acted.

        CONSUMER TEST — the canonical `_is_consumer_build()` (T-0952), NOT a bare
        `REPO_ROOT != ENGINE_ROOT` (T-11027). A `-C` flag pointing at one of the engine's OWN linked
        worktrees rebinds REPO_ROOT while ENGINE_ROOT stays the main checkout, so the bare path
        inequality mis-read an engine `work/`/`task/` worktree as a consumer and went looking for a
        `yitc-ops.yaml` the engine has none of by design — making the recorded bounded DEFER
        invisible and flipping this row acted:true→false on the FIRST step of every ревизия (the
        launch runbook mandates the `-C <worktree>` form). A linked worktree of the engine IS the
        engine: same git common-dir == same repo. Same idiom class as the T-0952 graph-attribution
        fix and the T-1101 write-boundary guard. When the predicate is not injected, fall back to the
        path inequality — the pre-existing degraded behaviour, and the same fallback
        `_is_consumer_build` itself takes in a non-git sandbox (a genuine consumer never fails
        open)."""
        if REPO_ROOT is not None and ENGINE_ROOT is not None:
            is_consumer = (_is_consumer_build() if _is_consumer_build is not None
                           else Path(REPO_ROOT) != Path(ENGINE_ROOT))
            if is_consumer:
                return Path(REPO_ROOT) / "yitc-ops.yaml"
        if not SPECS_DIR:
            return None
        return SPECS_DIR / "SPEC-0190-journal-physical-storage-contract-one-logical-jour.yaml"

    def _rotation_verdict_text():
        """The verdict carrier's TEXT, or None when absent/unreadable. ONE read-only text scan
        path for both tokens (CHARTER §P5) — no new parser family, and identical in mechanism to
        the pre-T-10810 single-spec scan it generalizes."""
        sp = _rotation_verdict_source()
        if sp is None or not sp.exists():
            return None
        try:
            return sp.read_text(encoding="utf-8")
        except OSError:
            return None

    def _rotation_rereview_bound_mb():
        """The re-review bound (MB) recorded WITH the standing DEFER verdict in this repo's
        verdict carrier (`ROTATION_VERDICT_REREVIEW_MB: <number>` — SPEC-0190 §Rotation policy
        for the engine, the consumer's own `yitc-ops.yaml` under `-C`; see
        `_rotation_verdict_source`), or None when the carrier / token / bound is absent or
        unparseable. Read-only text scan — no new store, no new parser family (CHARTER §P5)."""
        text = _rotation_verdict_text()
        if text is None:
            return None
        m = re.search(r"ROTATION_VERDICT_REREVIEW_MB:\s*([0-9]+(?:\.[0-9]+)?)", text)
        return float(m.group(1)) if m else None

    def _standing_rotation_defer(live_mb: float) -> bool:
        """True iff this repo's verdict carrier (`_rotation_verdict_source` — SPEC-0190
        §Rotation policy engine-self, the consumer's own `yitc-ops.yaml` under `-C`) records a
        STANDING DEFER verdict (the
        machine-readable `ROTATION_STANDING_VERDICT: DEFER` token) AND that verdict has NOT
        EXPIRED BY SIZE. This is the SPEC-0052 rule-1 `acted` disjunct «a rotation/split/
        compaction DECISION on record» — distinct from the open-follow-up-task disjunct below.
        A standing DEFER (T-0528 @13.7 MB + T-9445 @49 MB + T-10728 @110 MB) means the fired
        `> 10 MB` trigger HAS been acted on (reviewed, perf healthy, defer) WITHOUT keeping a
        task artificially open and WITHOUT physical rotation.

        BOUNDED VERDICT (T-10728 — the rule this implements, homed in SPEC-0190 §Rotation
        policy; re-homed out of SPEC-0002 by T-11447, rule unchanged): a DEFER decided at one
        size does NOT stand forever. It satisfies `acted` only
        while the LIVE journal is at or below the `ROTATION_VERDICT_REREVIEW_MB` bound recorded
        beside the token; past that bound the surface FLAGS again and the mandated perf review
        must be re-run. `live_mb` IS the live segment (T-11843): the parameter has always been named
        for that quantity, and the caller now passes it. The bound is calibrated on it — SPEC-0190
        §Rotation policy's Origin datum is an `ls -l events.jsonl` of the single live file, with 220
        as headroom above 171.44 MB — so measuring the all-segment aggregate here EXPIRED the DEFER
        on a unit change rather than on growth. FAIL-CLOSED: a token with no parseable bound does
        NOT count as acted —
        that is what retires the never-expiring token (the journal grew 49 → 110 MB, through the
        2026-08-07 four-lost-builds afternoon, while this row read `acted: true` throughout).

        The T-10810 carrier widening does NOT touch that fail-closed posture: a CONSUMER's token
        with no parseable bound (or no carrier at all) is `acted: false` exactly as the kernel's
        would be — the widening makes the disjunct REACHABLE, never a bypass."""
        text = _rotation_verdict_text()
        if text is None or "ROTATION_STANDING_VERDICT: DEFER" not in text:
            return False
        bound = _rotation_rereview_bound_mb()
        return bound is not None and live_mb <= bound

    surfaces = []

    def _surface(name, measured, unit, threshold, home, fired, acted, note="", *, report_only=False):
        """Build one surface row. DEFAULT = the SPEC-0052 rule-1 fired/acted verdict row.

        `report_only=True` (T-11028) builds a MEASUREMENT with NO trigger semantics: the row carries
        no `fired` / `acted` / `flagged_action` at all — deliberately ABSENT, not present-and-False.
        A `fired: False` would still assert that a live threshold sits behind the row; the whole
        point of a retired count-gate is that there is none. Such a row can never reach
        `flagged_actions`. Rule-1 is unweakened: a surface with no governing trigger is still
        REPORTED, never silently dropped."""
        row = {"surface": name, "measured": measured, "unit": unit, "threshold": threshold,
               "governing_trigger": home}
        if report_only:
            row["report_only"] = True
        else:
            row.update({"fired": fired, "acted": acted,
                        "flagged_action": bool(fired and not acted)})
        if note:
            row["note"] = note
        surfaces.append(row)

    # 1. events.jsonl size vs D-0030 `> 10 MB` rotation_policy (THE gap-closing surface) — TWO rows
    #    since T-11843: a GOVERNED row on the LIVE segment (the quantity the trigger's own action can
    #    move, and the unit ROTATION_VERDICT_REREVIEW_MB was calibrated on) and a REPORT-ONLY
    #    trajectory row carrying the all-segment aggregate. Before the split ONE aggregate figure was
    #    compared against BOTH the `> 10 MB` trigger and the 220 MB bound, so the lens read
    #    `EXPIRED — re-run the review` purely because the measured UNIT changed underneath a number
    #    nobody re-set (live 79.3 MB vs aggregate 252.62 MB, measured 2026-08-30). Full reasoning:
    #    `_live_segment_bytes` above.
    ev_bytes = _live_segment_bytes(EVENTS_PATH)  # T-11843: the LIVE segment (SPEC-0190 r8 qualified)
    ev_mb = round(ev_bytes / (1024 * 1024), 2)
    ev_all_bytes = journal_mod.segment_size(EVENTS_PATH)  # logical size across segments (SPEC-0190 r8)
    ev_all_mb = round(ev_all_bytes / (1024 * 1024), 2)
    ev_fired = ev_bytes > _JOURNAL_ROTATION_BYTES
    _rot_bound = _rotation_rereview_bound_mb()
    _rot_src = _rotation_verdict_source()
    # Name the RESOLVED carrier (T-10810): under `-C` the verdict is read from the consumer's OWN
    # yitc-ops.yaml, engine-self from the kernel spec — so the row explains WHICH file it read.
    _rot_home = _rot_src.name if _rot_src is not None else "no verdict carrier resolved"
    _surface("events.jsonl size", ev_mb, "MB (live segment)", "> 10 MB",
             "D-0030 rotation_policy", ev_fired,
             _open_task_cites("D-0030") or _standing_rotation_defer(ev_mb),
             "MEASURED ON THE LIVE SEGMENT (T-11843) — the quantity this trigger's own action can "
             "move; the all-segment aggregate is the report-only trajectory row below. "
             "acted = an open task CITES D-0030 (rotation_policy home) OR this repo's verdict "
             f"carrier ({_rot_home} — SPEC-0190 §Rotation policy engine-self, the consumer's own "
             "yitc-ops.yaml under -C, T-10810) records a "
             "standing DEFER rotation verdict (ROTATION_STANDING_VERDICT: DEFER — the SPEC-0052 "
             "rule-1 decision-on-record disjunct; no rotation, history intact) that has NOT "
             "EXPIRED BY SIZE (T-10728): the DEFER counts only while the live journal is <= the "
             "re-review bound recorded beside it — "
             + (f"bound {_rot_bound} MB, live {ev_mb} MB "
                + ("(within bound)" if ev_mb <= _rot_bound else "(EXPIRED — re-run the review)")
                if _rot_bound is not None
                else "no ROTATION_VERDICT_REREVIEW_MB bound on record (fail-closed: an unbounded "
                     "DEFER does not count as acted)"))

    # 1b. events.jsonl ALL-SEGMENT total — REPORT-ONLY trajectory (T-11843). SPEC-0190 rule 8 requires
    # the aggregate to stay VISIBLE and GOVERNED so rotation cannot silently retire the mechanism that
    # judges whether rotation is warranted — that concern is real and is served HERE, by a row the lens
    # can never drop (SPEC-0052 rule 1 unweakened: a surface with no governing trigger is REPORTED,
    # never silently dropped). What it must NOT be is a VERDICT row: archive segments are append-only
    # history that is never deleted and SPEC-0002 §Violations forbids an in-place rewrite, so no
    # permitted action can reduce this number — a `fired` on it would be lit forever, the exact
    # permanently-lit-flag class T-11028 and T-10651 retired, and the shape SPEC-0190's own disk-volume
    # axis says this section must never become. So: MEASURE the trajectory, and say nothing more.
    _surface("events.jsonl all-segment total", ev_all_mb, "MB (live + archive)",
             "none — reported TRAJECTORY, no numeric trigger",
             "SPEC-0190 §Rotation policy (disk-volume axis)", None, None,
             "REPORT-ONLY measurement, no fired/acted verdict (T-11843): the logical journal's size "
             "across every segment, read as a CURVE against SPEC-0190 §Rotation policy's Origin datum "
             "and never against a threshold. The GOVERNED `> 10 MB` trigger and the standing DEFER's "
             "ROTATION_VERDICT_REREVIEW_MB currency bound both read the LIVE segment row above — the "
             "quantity their own action moves, and the unit the 220 MB bound was calibrated on. A "
             "reading here, however large, authorizes a REVIEW conversation and nothing more; physical "
             "rotation stays reserved to explicit owner approval (SPEC-0002 §Violations).",
             report_only=True)

    # 2. tasks/ done-count — REPORT-ONLY (T-11028). The `> 500` count-gate this row used to fire is
    # RETIRED at its own governing home: QUEUE §Done log records the dated KEEP-FLAT re-decision
    # (T-10651, 2026-07-17) that the ~500/~1500 marks are HISTORY and the SOLE trigger is observed
    # grep/tooling friction — the count-gate class SPEC-0031 §Node-volume retired at T-0488 (counts
    # grow with the work, so a fixed number signals nothing). The row was therefore permanently
    # fired-and-unacted: the count only grows, and its ONE acted disjunct was an open task CITING
    # QUEUE.md — an artificially-open sentinel task, the exact anti-pattern the standing-verdict token
    # (T-10810) exists to retire. A permanently-lit flag on a withdrawn trigger teaches readers to
    # ignore the flag, which costs the OTHER rows their signal. So: MEASURE, and say nothing more.
    # The retained path is NAMED below and is MANUAL by construction — real friction is captured as a
    # deviation (D-0035/D-0086), never derived from this number.
    done_n = len(_closed_task_ids())
    _surface("tasks/ done-log count", done_n, "tasks",
             "none — count-gate RETIRED (T-10651); no numeric trigger",
             "QUEUE §Done log", None, None,
             "REPORT-ONLY measurement, no fired/acted verdict: QUEUE §Done log retired the ~500/~1500 "
             "count-gate (T-10651, 2026-07-17; the count-gate class at SPEC-0031 §Node-volume, T-0488). "
             "The RETAINED trigger is OBSERVED grep or tooling friction — a real incident, raised "
             "MANUALLY as a deviation capture (`bin/yitc-v2 event deviation_captured`), never from this "
             "count. The number is reported for orientation only.",
             report_only=True)

    # 3. handbook aggregate vs CHARTER hard-cap 2500 (RED) / warn 2000 (YELLOW). The LINE axis is the
    # cap's stated unit and stays THE gate; the BYTE(+est-token) axis is REPORTED alongside (T-10316) —
    # the aggregate a session actually pays to load is tokens, not lines, and the seed density spread
    # (~1.7x, T-10219) lets the set sit under 2500 lines while its token weight runs ahead of what that
    # number implies. The owner RULED (owner_directive 2026-07-10) to DECLINE a token bound: the byte
    # axis stays report-only and NEVER gates.
    hb_t = _handbook_size_totals()
    hb = hb_t["lines"]
    hb_bytes, hb_tokens = hb_t["bytes"], hb_t["est_tokens"]
    hb_fired = hb is not None and hb > 2000     # warn threshold fired (LINE axis — the stated cap)
    hb_red = hb is not None and hb > 2500       # hard cap (LINE axis)
    _byte_str = (f"{hb_bytes} B / ~{hb_tokens} est tok" if hb_bytes is not None else "n/a")
    _surface("handbook aggregate", (hb if hb is not None else "n/a"), "lines",
             "warn 2000 / hard 2500 lines", "CHARTER §Principle 2", hb_fired,
             _open_task_cites("CHARTER.md"),
             (("OVER HARD CAP 2500 — RED" if hb_red else
               ("over warn 2000" if hb_fired else "under warn threshold")) +
              f" · byte axis (report-only, no gate): {_byte_str}"))

    # 4. CLOSED-task audit YAMLs still in the active decisions/ lane — the acute surface (this task's
    # drain target). No numeric cap is HOMED elsewhere (it was ungoverned — the accretion the sweep
    # retires); the governing ACTION is SPEC-0052's drain. fired = any CLOSED-task audit YAML is still
    # in active decisions/ (there is something to drain); acted ⇔ CURRENT state is caught up (zero such
    # files remain) — NOT a historical archive event (audit-post F0: a past run must not mask a new gap).
    closed_ids = set(_closed_task_ids())
    undrained = sorted({p.name for p in DECISIONS_DIR.glob("*-audit-*.yaml")
                        if (m := re.match(r"^(T-\d{4,})-audit-", p.name)) and m.group(1) in closed_ids})
    total_active_audits = len(list(DECISIONS_DIR.glob("*-audit-*.yaml")))
    _surface("closed-task audit YAMLs in active decisions/", len(undrained), "files",
             "drain on close (SPEC-0052)", "SPEC-0052 rule 3", bool(undrained), not undrained,
             f"acted ⇔ zero closed-task audit YAMLs remain in active decisions/ (current state); "
             f"{total_active_audits} total active audit YAMLs incl. in-flight/adhoc/consult/plan (not drained)")

    # `.get` — a report-only row (T-11028) carries no `flagged_action` key at all, so it can never
    # reach this headline.
    flagged = [s["surface"] for s in surfaces if s.get("flagged_action")]
    return {
        "lens": "displacement-retention (SPEC-0052) — the FIRST inspection step + weekly Review backstop",
        "invariant": "for each surface: MEASURE the value AND check its governing trigger — a "
                     "fired-but-unacted trigger is a FLAGGED action, not a bare number",
        "flagged_actions": flagged if flagged else "none — every fired trigger has a recorded action",
        "surfaces": surfaces,
        # T-11850: the hint names the verb that can ACTUALLY clear this surface. Until that card
        # the drain skipped any active record whose NAME already existed in the archive — which is
        # exactly what a post-close re-audit writes — so the hint recommended a verb that provably
        # could not act, and the flag above stayed lit permanently (the T-11028 class). The
        # reconciliation is named here because a reader deciding whether to run the drain needs to
        # know the older twin is PRESERVED, not overwritten.
        "drain_hint": ("run `yitc-v2 triage sweep` to drain closed-task audit YAMLs into "
                       "decisions/archive/ (SPEC-0052). A post-close re-audit twin — an active "
                       "record whose name already exists in the archive — is RECONCILED, not "
                       "skipped: the active record is the newer one and takes the canonical "
                       "archived name, while the older archived copy is preserved beside it as "
                       "`<stem>.superseded-<hash>.yaml` (T-11850)"),
    }

def _view_observation(events_path: "Path", project: "str | None" = None, *,
                      _view_token_rollup=None) -> dict:
    """observation lens (T-10123 / SPEC-0135): per-PROJECT observation slices keyed by the normalized
    provider×model×effort triple, folded from the enriched `session_started` fields (T-10121) + the
    read-time `token-rollup` cost lens. Journal-DERIVED (reads events.jsonl, the SoT) + read-time cost
    — no new store/event (D-0053, SPEC-0135 §1 read-time analysis). The SPEC-0135 §6 slice key is
    (project, provider×model×effort); an absent/"unknown" axis collapses to the one `unknown` bucket.

    ONE ROW PER SESSION (T-11638): rows are folded by session ref (`data.resolved_session_ref`, else
    the TOP-LEVEL `session_ref`) under the resolved-wins rule before counting, so the two
    `session_started` rows one dispatched worker emits count as the one session they are. See the fold
    below for the full reasoning. A row with no ref at all has no identity to fold on and is counted
    as its own session.

    `project` (optional CLI arg) filters to one project — `graph query observation [project]`; a no-arg
    run returns all projects (never errors — keeps the every-view-executable sweep green). Cost is
    READ-TIME DERIVED (SPEC-0135 §3): token-rollup HARD-FAILS on an absent/stale archive → the cost
    column DEGRADES to n/a (the task-scorecard precedent), never inheriting the hard-fail."""
    import json as _json
    slices: dict = {}
    by_ref: dict = {}       # (project, session_ref) -> triple, folded RESOLVED-WINS (T-11638)
    refless: list = []      # rows carrying no identity to fold on — counted per row, as before
    if events_path and Path(events_path).exists():
        for line in journal_mod.segment_lines(events_path, errors="replace"):  # T-11444: segment-aware fold (SPEC-0190 r4)
            try:
                e = _json.loads(line)
            except ValueError:
                continue
            if e.get("type") != "session_started":
                continue
            d = e.get("data") or {}
            proj = d.get("project") or "unknown"
            if project and proj != project:
                continue
            # read-time provider normalization (T-10605): historical events stored the raw
            # harness-versioned descriptor `claude-code_2-1-<patch>_agent` in `provider` (pre the
            # capture-side observe.normalize_provider fix), fragmenting one vendor across ~8 patch
            # buckets; collapse to the stable vendor key so slices don't dilute (SPEC-0135 §6).
            trip = (observe.normalize_provider(d.get("provider")),
                    d.get("model") or "unknown", d.get("effort") or "unknown")
            # ONE ROW PER SESSION, not per EVENT (T-11638). This lens's unit is a SESSION — its
            # payload field is literally `sessions` and the SPEC-0135 §6 slice key is per-session —
            # but it used to count matching ROWS. A dispatched worker emits TWO `session_started`
            # rows for ONE session: the T-10083 launcher bootstrap row on main (`{type: build,
            # bootstrap: dispatch}`, carrying NO provider/model/effort) and the worker's own
            # in-worktree `session start`, which carries the full T-10121 triple. Counting rows made
            # the bare row a session that never existed, inflating (unknown, unknown, unknown) by
            # roughly one per dispatched worker — the T-11035 row read through DIFFERENT arithmetic:
            # ref-counting made it a displacement in the pair rollup, event-counting makes it an
            # addition here (same row, different defect).
            #
            # The ref is read TOP-LEVEL as the fallback, and that is half the fix: the bootstrap row
            # carries its ref ONLY at `e["session_ref"]` — `data.resolved_session_ref` is an ENRICHED
            # field it does not have — so the old read could not even SEE the two rows as one session.
            #
            # RESOLVED-WINS (the sibling fold's rule, `_read_pair_observations_for_project`), sharing
            # the file's ONE `_triple_resolved` predicate so the two folds cannot drift on what
            # "resolved" means (CHARTER §P5): an unresolved row still SEEDS an unseen ref, it merely
            # never DISPLACES a resolved one. So this can only remove phantoms, never under-count — a
            # ref that only ever emitted bare rows stays counted, in its all-"unknown" slice. It
            # upgrades what the record already says and never infers a triple the record lacks.
            #
            # NOT "exclude the bootstrap row": that fixes one known emitter while leaving the
            # row-vs-session conflation standing (any second row under one ref would still
            # double-count), and it would DROP a dispatched worker that never reached its own
            # `session start`. The emitter itself is untouched, and so is the pair rollup.
            ref = d.get("resolved_session_ref") or e.get("session_ref")
            if not ref:
                refless.append((proj, trip))
                continue
            rk = (proj, ref)
            prior = by_ref.get(rk)
            if prior is None or (not _triple_resolved(prior) and _triple_resolved(trip)):
                by_ref[rk] = trip
    for (proj, ref), trip in by_ref.items():
        s = slices.setdefault((proj,) + trip, {"sessions": 0, "refs": set()})
        s["sessions"] += 1
        s["refs"].add(ref)
    for proj, trip in refless:
        s = slices.setdefault((proj,) + trip, {"sessions": 0, "refs": set()})
        s["sessions"] += 1
    # best-effort read-time cost join (SPEC-0135 §3); token-rollup HONEST-DEGRADES on an absent archive
    # → a NAMED `status` outcome (T-10454), so cost stays n/a. (SystemExit guard kept — a belt for any
    # other _die path; the archive-absent path no longer raises.)
    cost_by_ref: dict = {}
    cost_note = "n/a — token-rollup unavailable (transcript archive absent/stale, gitignored in worktrees)"
    if _view_token_rollup is not None:
        try:
            rollup = _view_token_rollup({})
            if not rollup.get("status"):   # healthy rollup (no honest-degrade status) → real cost join
                cost_note = "read-time derived (token-rollup × pricing-config; estimate)"
                for sid, sess in (rollup.get("sessions") or {}).items():
                    cost_by_ref[sid] = (sess.get("totals") or {}).get("cost_usd")
        except SystemExit:
            pass   # documented archive-absent hard-fail → cost degrades to n/a (task-scorecard precedent)
        except Exception:
            pass
    projects: dict = {}
    for (proj, prov, model, eff), s in slices.items():
        costs = []
        for r in s["refs"]:
            c = cost_by_ref.get(r)
            if c is None and isinstance(r, str) and "=" in r:   # 'env:NAME=<uuid>' → match by the uuid tail
                c = cost_by_ref.get(r.split("=", 1)[1])
            if c is not None:
                costs.append(c)
        projects.setdefault(proj, []).append({
            "provider": prov, "model": model, "effort": eff,
            "sessions": s["sessions"],
            "cost_usd": round(sum(costs), 4) if costs else None})
    for p in projects:
        projects[p].sort(key=lambda x: (-x["sessions"], x["provider"], x["model"], x["effort"]))
    return {
        "projects": dict(sorted(projects.items())),
        "project_count": len(projects),
        "slice_count": len(slices),
        "keyed_by": "provider×model×effort (per project)",
        "cost": cost_note,
        "filter": project,
        "source": ("events.jsonl session_started enriched fields (T-10121) + token-rollup (T-0394) — "
                   "read-time derived, no new store (D-0053, SPEC-0135 §1/§3)"),
    }

# SPEC-0135 §5 / SPEC-0057 §4 fence — the sample-size-qualified-findings-only contract, stated on
# every observation-rollup payload so a reader never mistakes the confidence sort for a quality ranking.
_NO_BEST_PAIR_NOTE = (
    "FINDINGS not scores: this view NEVER declares a universal best worker×auditor pair. Pairs are "
    "ordered by sample_size (confidence), NOT by any quality score — read each pair only against its own "
    "sample_size (SPEC-0135 §5 output-is-findings; SPEC-0057 §4 no-composite-score fence held).")

# T-10647 — the ROUTING CONFOUNDER, stated wherever the pair table is, because a pooled pair mix READS
# like a pair finding and is not one. SPEC-0072 routes effort_tier:critical -> a high-effort worker and
# normal -> a low-effort one, so a pair's WORKER-EFFORT axis is bound to its tasks' STAKES by
# construction: a high-effort pair is mostly critical work, which REDs more for reasons that are nothing
# to do with the pair. Comparing pooled mixes across pairs therefore measures the routing, not the pair
# (this is exactly how the 2026-07-16 "effort-tier inversion" arose — fp
# observation-effort-tier-verdict-mix-inversion-routing-confounded; it dissolved under control).
#
# T-10804 — THE BUCKET-ADEQUACY DECISION, recorded HERE because this note is where the rule it scopes
# already lives. QUESTION: does T-10746's declared `_SAMPLE_ADEQUACY_FLOOR` (a pair-level marker)
# extend DOWN to the three marginals' buckets, each of which renders its own mix at its own n?
# ANSWER: NO — declined, deliberately, and the thin-bucket sentence below IS the whole adequacy rule
# at bucket altitude. Three grounds, so the question is not re-opened per reader:
#   1. THE EVIDENCE CITED FOR EXTENDING REFUTES IT. T-10745's live trigger reads a 0.54 RED share in
#      ticket-review at n=13 and calls it "a thin bucket read as a thin finding". n=13 is ABOVE the
#      floor (5) — an extended floor would have stamped that bucket `verdict_mix_claimed: true` and
#      ENDORSED the very read it was invoked to prevent. A floor calibrated on a POOLED sample does
#      not transfer to a bucket's n; there is no second calibrated number to import, and inventing
#      one would put a second unrelated adequacy constant in this file (the exact defect T-10746's
#      "reuse the in-corpus n<5 line" rationale avoided).
#   2. IT WOULD ADD NOISE AND REMOVE NOTHING (CHARTER §Principle 1 filters 2+3). A per-bucket marker
#      on potentially dozens of buckets per pair is the T-10605 phantom-cell class this note ALREADY
#      names one sentence down — the marginals were shaped to avoid it. The governing rule already
#      travels with every bucket that renders; prose is the correct altitude for a rule that has no
#      threshold to declare.
#   3. NO NEW RULE ⇒ NO NEW TRIPWIRE (SPEC-0165 rule 1/5). Declining changes no behaviour, so there
#      is nothing that can break silently and nothing to guard; extending would have owed a
#      differential tripwire in tests/test_t10124_observation_rollup.py.
# BOUND ON ANY FUTURE REVISIT (inherited, not re-litigable): SPEC-0057 §4 — whatever is decided stays
# REPORT-ONLY (nothing filtered, reordered or gated) and introduces no score, rank, share or weight.
# This is a scope call on a report-only view, not an AUTHORITY-class decision (SPEC-0121 §5), so it
# is decided in the artifact rather than escalated.
_STAKES_NOTE = (
    "CONTROL BEFORE YOU COMPARE: a pair's pooled `verdicts` is NOT a like-for-like read. SPEC-0072 "
    "routing binds worker-effort to task STAKES (critical -> high-effort, normal -> low-effort), so a "
    "high-effort pair's sample is mostly critical-tier work — which carries a worse verdict mix by "
    "STAKES, not by pair quality. Compare pairs ONLY within a matching bucket of `by_effort_tier` "
    "(the routed confounder) — `by_task_class` is the secondary stratifier (SPEC-0072 rule 4 routes on "
    "stakes explicitly NOT on class). `by_project` is the DIVERGENCE marginal (T-10745): the T10 theme's "
    "own mandated read — the same pair healthy in one project and poor in another — which the pooled mix "
    "hides and `project_count`/`projects` cannot express. Each bucket carries its OWN sample_size: a thin "
    "bucket is a thin finding — and THIS SENTENCE IS THE ANSWER'S HOME (T-10804): the declared "
    "`sample_adequacy_floor` marker is pair-level ONLY and is deliberately NOT extended to buckets, "
    "because a floor calibrated on a POOLED n does not transfer to a bucket's n (the n=13 bucket that "
    "prompted the question sits ABOVE the floor and would have been marked ADEQUATE) and a marker on "
    "dozens of buckets per pair is the phantom-cell noise named next. Judge a bucket by its own "
    "sample_size, here, in prose. Buckets are the three MARGINALS, not a tier×class×project product grid — a "
    "product would be hundreds of mostly-n<5 cells per pair, un-decision-readable noise (the T-10605 "
    "phantom-cell lesson); the raw rows remain a one-line fold if a specific cell is ever needed.")


# T-10746 (X-0596) — the SAMPLE-ADEQUACY FLOOR, declared HERE and read from here by the render path.
# THE DECLARATION + ITS RATIONALE (the one named place; a literal in the render path would put the
# line back in each reader's head, which is the defect):
#   Below this many observations a pair's VERDICT MIX is not a claim — it is a handful of runs. The
#   value is 5 because `_STAKES_NOTE` already names "mostly-n<5 cells" as the un-decision-readable
#   band (the T-10605 phantom-cell lesson): reusing that in-corpus line keeps ONE adequacy number in
#   this file rather than inventing a second, unrelated one.
# WHY IT EXISTS: measured 2026-08-06, four of eight pairs sat at n=35/19/3/1 and the NEWEST worker
# model — the configuration most likely to be asked about — carried n=3 and n=1. The view was honest
# about the counts and SILENT about their adequacy, so every reader redrew that line by judgement,
# per run. Declaring it once replaces that repeated private judgement.
# REPORT-ONLY, and that bound is the whole design: the marker CHANGES NOTHING but what is SAID. A
# below-floor pair is still listed, still carries its full `verdicts` and all three marginals, keeps
# its place in the sample_size sort, and is never filtered, suppressed, or made to fail anything.
# NOT A SCORE (SPEC-0057 §4 fence, held): a floor is a declared threshold on n — never a confidence
# value, rank, share or weight. §4 blesses exactly this shape: "the only per-theme signal is the
# trivially derived binary". `verdict_mix_claimed` is that binary over a declared n, nothing more.
_SAMPLE_ADEQUACY_FLOOR = 5

_SAMPLE_ADEQUACY_NOTE = (
    "SAMPLE-ADEQUACY FLOOR (declared, report-only — T-10746): a pair whose sample_size is below "
    f"`sample_adequacy_floor` ({_SAMPLE_ADEQUACY_FLOOR}) carries `verdict_mix_claimed: false` + a "
    "`verdict_mix_not_claimed` reason — its verdict mix is NOT a finding, it is a handful of runs, "
    "and the view now SAYS so instead of leaving each reader to redraw that line per run (X-0596: "
    "n=35 and n=1 rendered identically). Report-only means literally nothing is gated: the pair is "
    "still listed with its full `verdicts` and all three marginals, its position in the sample_size "
    "order is unchanged, and no read is filtered or refused — the floor changes what is SAID about "
    "the mix, never what is shown. An at-or-above-floor pair carries `verdict_mix_claimed: true` and "
    "no reason; adequacy is stated on EVERY pair, both polarities, never inferred from silence. The "
    "floor applies to the pooled mix; a MARGINAL's bucket carries its own sample_size and `_STAKES_"
    "NOTE`'s thin-bucket-is-a-thin-finding rule continues to govern it — a DECIDED boundary, not an "
    "accident of T-10746's scope: T-10804 weighed extending the floor to buckets and DECLINED (the "
    "rationale + the bound on any revisit live beside `_STAKES_NOTE`, the one named home). A declared threshold on n is "
    "NOT a score, rank or weight (SPEC-0057 §4 fence held).")


_UNATTRIBUTED_REASONS_NOTE = (
    "unattributed_reasons breaks unattributed_observations down by WHY the pair join failed, over "
    "the join conditions the view ALREADY evaluates (T-10744): `no_session_ref` (the audit record "
    "carries no session_ref — nothing to join on), `worker_session_absent` (session_ref present but "
    "no session_started for it in that project's journal), `worker_triple_incomplete` (worker "
    "session found, an axis unresolved), `auditor_triple_incomplete` (worker fully resolved, an "
    "auditor axis unresolved). Reasons are MUTUALLY EXCLUSIVE and worker-side takes precedence (the "
    "upstream cause), so the counts SUM to unattributed_observations — losslessly; a residual "
    "`unclassified` key appears ONLY if they ever fail to sum (a named degrade, never a silent "
    "under-count, T-0358). Pre-instrumentation history has NO label of its own: it is not observable "
    "from the record and surfaces as the same reasons a live leak would — DECAYING LEGACY vs ONGOING "
    "LEAK is read from a named reason's trend, which the flat count could not support. A COUNT "
    "breakdown, not a score (SPEC-0057 §4 fence holds)."
)


_ABSENCE_NOTE = (
    "PRESENCE IS NOT ABSENCE (T-11035). A pair missing from `pairs` used to be unreadable: the "
    "reader could not tell a real gap (both sides ran, never together) from a combination nobody "
    "has ever observed. Three states are now distinguishable, and every pair is in exactly one: "
    "(1) LISTED in `pairs` — observed, with its counts; (2) LISTED in `zero_run_pairs` — a cell of "
    "the OBSERVED GRID (`observed_workers` × `observed_auditors`, both drawn from the attributed "
    "window) that carries ZERO observations, i.e. both sides are in live use and were never run "
    "together — a REAL gap, and the only absence this view is entitled to assert; (3) IN NEITHER — "
    "UNOBSERVED, and NOT evidence of disuse: at least one side falls outside the attributed window, "
    "so the record simply does not say. The grid is bounded by what was observed — never a "
    "cross-product of the whole provider×model×effort vocabulary, which would manufacture the "
    "phantom cells `stakes` warns about. Membership + counts only, no score (SPEC-0057 §4)."
)


def _triple_resolved(t) -> bool:
    """Is a provider×model×effort triple FULLY resolved — no axis left at the "unknown" fallback
    (SPEC-0135 §6)? The ONE predicate for that question: the fold's resolved-wins rule, the
    attribution classifier and the attributed-window bound must agree on what "resolved" means, or
    the rollup's own arithmetic drifts against its reason breakdown (CHARTER §P5)."""
    return all(axis != "unknown" for axis in t)


def _classify_attribution_failure(*, session_ref, worker_found: bool, worker, auditor):
    """WHY this observation falls outside the attributed window — or None when it falls INSIDE it
    (T-10744). Ordered contract, FIRST match wins, so every observation carries exactly ONE label and
    the rollup's per-reason counts sum to unattributed_observations losslessly:

      (0) both triples fully resolved                 -> None (attributed; no failure to report)
      (1) no session_ref on the audit record          -> "no_session_ref"
      (2) session_ref present, worker session missing  -> "worker_session_absent"
      (3) worker session found, an axis unresolved    -> "worker_triple_incomplete"
      (4) worker resolved, an auditor axis unresolved -> "auditor_triple_incomplete"

    Worker-side (1)-(3) precede the auditor side (4) because a worker failure is the UPSTREAM cause:
    an observation with no session_ref has no worker triple to complete, so billing it to the auditor
    would misdirect the operator reading the breakdown."""
    _ok = _triple_resolved   # ONE definition of "resolved" (see `_triple_resolved`)

    if _ok(worker) and _ok(auditor):
        return None
    if not _ok(worker):
        if not session_ref:
            return "no_session_ref"
        if not worker_found:
            return "worker_session_absent"
        return "worker_triple_incomplete"
    return "auditor_triple_incomplete"


def _read_pair_observations_for_project(events_path: "Path", proj_name: str) -> list:
    """Read ONE v2 project's events.jsonl (READ-ONLY, D-0019) and fold it into worker×auditor PAIR
    observations (SPEC-0135 §4). Two passes over the journal: (1) session_ref → the worker triple from
    `session_started` (the enriched T-10121 fields; absent axis → "unknown"); (2) each
    `external_audit_completed` (which carries the auditor triple + verdict, T-10121) is JOINED to its
    worker session by `session_ref` → one PAIR observation {worker, auditor, verdict, project}. An
    audit whose worker session_started is absent from this journal folds to an all-"unknown" worker
    (never dropped — the auditor side is still a real observation). Fail-OPEN: an unreadable/missing
    journal yields [] (a broken project must not crash the kernel rollup — the consumer-deploy-policy
    precedent). Identity + verdict only; NO usage/cost (SPEC-0135 §3).

    Each observation ALSO carries its task's CONTROL dimensions (T-10647) — `effort_tier` (from
    `bg_dispatch_launched.source_tier`, the tier SPEC-0072 routing actually dispatched on) and
    `task_class` (from `task_filed.data["class"]`) — both joined by `task_id` in the SAME single pass
    over the SAME journal. Neither needs a task-card read or any cross-project filesystem reach, so the
    kernel rollup stays a pure read-only journal fold. An unresolved dimension folds to "unknown"
    (never drops the observation — the T-10605 unknown discipline). The observation's `project` — read
    here for the cross-project fold — is ALSO a control dimension in the rollup (the T-10745
    `by_project` divergence marginal); it is always resolved, so it needs no "unknown" bucket.

    Each observation FINALLY carries `attribution_failure` (T-10744) — WHY this observation falls
    outside the attributed window, or None when it falls inside it. Classified HERE because this is
    the only place that sees the join CONDITIONS themselves (was there a session_ref at all? did the
    lookup miss? which side's triple is incomplete?) — the rollup only sees the folded triples. See
    `_classify_attribution_failure` for the ordered contract."""
    import json as _json
    from pathlib import Path
    worker_by_ref: dict = {}
    tier_by_task: dict = {}
    class_by_task: dict = {}
    audits: list = []
    p = Path(events_path) if events_path is not None else None
    if p is None or not p.exists():
        return []
    try:
        for line in journal_mod.segment_lines(p, errors="replace"):  # T-11444: segment-aware fold (SPEC-0190 r4)
            if ("session_started" not in line and "external_audit_completed" not in line
                    and "bg_dispatch_launched" not in line and "task_filed" not in line):
                continue
            try:
                e = _json.loads(line)
            except ValueError:
                continue
            et = e.get("type")
            if et == "session_started":
                ref = e.get("session_ref")
                if ref:
                    d = e.get("data") or {}
                    trip = (observe.normalize_provider(d.get("provider")),
                            d.get("model") or "unknown",
                            d.get("effort") or "unknown")
                    # RESOLVED-WINS, never last-line-wins (T-11035). ONE dispatched worker emits TWO
                    # session_started rows under the SAME session_ref: the T-10083 launcher bootstrap
                    # row on main (`{type: build, bootstrap: dispatch}` — it predates the worker and
                    # carries NO provider/model/effort) and the worker's own in-worktree `session
                    # start`, which carries the full T-10121 triple. Their FILE order is set by land's
                    # union-merge, not by which row knows more — so a plain assignment let the bare
                    # bootstrap row OVERWRITE a fully resolved triple with all-"unknown" and the
                    # observation was billed `worker_triple_incomplete` while its triple sat in the
                    # same journal. Measured over all 11 registry v2 projects, 2026-08-25:
                    # attributed_share 0.170 -> 0.546 (2395 -> 7691 of 14078) once a resolved triple
                    # can no longer be displaced. An unresolved row still SEEDS an unseen ref, so a
                    # ref that only ever emitted bare rows is unchanged (still "unknown", still
                    # counted as unattributed — this upgrades what the record ALREADY says, it never
                    # infers a triple the record does not carry).
                    prior = worker_by_ref.get(ref)
                    if prior is None or (not _triple_resolved(prior) and _triple_resolved(trip)):
                        worker_by_ref[ref] = trip
            elif et == "external_audit_completed":
                d = e.get("data") or {}
                audits.append((e.get("session_ref"), e.get("task_id"), d))
            elif et == "bg_dispatch_launched":
                # the effort TIER the dispatch actually routed on (SPEC-0072) — the confounder the
                # controlled cross-tab exists to expose. Last launch wins (a re-dispatch is the
                # tier that produced the later audits).
                tid = e.get("task_id")
                st = (e.get("data") or {}).get("source_tier")
                if tid and st:
                    tier_by_task[tid] = st
            elif et == "task_filed":
                tid = e.get("task_id")
                cls = (e.get("data") or {}).get("class")
                if tid and cls:
                    class_by_task[tid] = cls
    except OSError:
        return []
    out: list = []
    for ref, task_id, d in audits:
        w = worker_by_ref.get(ref, ("unknown", "unknown", "unknown"))
        # normalize the auditor provider too (T-10605): the auditor-side descriptor is subject to the
        # same patch-version fragmentation; collapse to the stable vendor key (SPEC-0135 §6).
        a = (observe.normalize_provider(d.get("provider")),
             d.get("model") or "unknown", d.get("effort") or "unknown")
        out.append({"project": proj_name, "session_ref": ref, "worker": w, "auditor": a,
                    "verdict": (d.get("verdict") or "unknown").upper(), "stage": d.get("stage"),
                    "effort_tier": tier_by_task.get(task_id, "unknown"),
                    "task_class": class_by_task.get(task_id, "unknown"),
                    "attribution_failure": _classify_attribution_failure(
                        session_ref=ref, worker_found=(ref in worker_by_ref), worker=w, auditor=a)})
    return out


def _view_observation_rollup(*, registry_path=None, engine_root=None, kernel_name=None,
                             _v2_projects=None) -> dict:
    """observation-rollup lens (T-10124 / SPEC-0135 §2/§4/§5): the KERNEL cross-project fold of the
    real-work observation loop. Where the per-project `observation` view (T-10123) keys by the WORKER
    triple within ONE project, this KERNEL-ONLY view enumerates EVERY registry `yitc_v2` project (the
    kernel INCLUDED — every v2 project measures itself and the kernel aggregates across ALL, SPEC-0135
    §2), reads each project's events.jsonl READ-ONLY, and rolls the observations up to the
    worker×auditor PAIR (SPEC-0135 §4 — provider×model×effort on each side, joined by session_ref).

    Enumeration REUSES `_v2_projects(registry_path, engine_root, kernel_name)` — the SAME read-only
    registry scan the nightly (SPEC-0105 §2, the cross-project seam SPEC-0135 §2 names) + the
    consumer-deploy-policy lens already use (D-0019 territory-safe). A pure DERIVED view (D-0053): it
    stores the QUERY, recomputes fresh on read, adds NO store/event/node/edge/daemon (CHARTER §P1).

    Each pair slice ALWAYS carries `sample_size` (the count of audited task-runs contributing) +
    `project_count`/`projects` (how many + which projects) + `sessions` (distinct worker sessions) +
    raw `verdicts` counts + the three CONTROLLED cross-tabs `by_effort_tier` / `by_task_class` (T-10647 —
    the pooled mix is confounded by SPEC-0072 routing, which binds worker-effort to task stakes; the
    per-bucket verdicts are what make a cross-pair comparison like-for-like, see `_STAKES_NOTE`) and
    `by_project` (T-10745 — the DIVERGENCE marginal: the same pair healthy in one project and poor in
    another is a T10-mandated discipline/environment finding that `project_count` + the bare `projects`
    LIST structurally cannot express, X-0596). All three are COMPLETE partitions of the pair's sample.
    Each pair ALSO carries `verdict_mix_claimed` (T-10746) — whether its sample_size reaches the
    DECLARED `_SAMPLE_ADEQUACY_FLOOR`, plus a `verdict_mix_not_claimed` reason when it does not.
    REPORT-ONLY: a below-floor pair is still listed with its full counts + marginals in its usual
    sort position — the floor changes what the view SAYS about the mix, never what it shows or
    admits (X-0596: n=1 and n=35 rendered identically, so each reader redrew that line per run).

    FINDINGS not scores (SPEC-0135 §5 / SPEC-0057 §4 fence): NO composite score,
    NO best-pair marker — pairs are sorted by sample_size (CONFIDENCE, explicitly not quality) and the
    `no_best_pair` note states the sample-size-qualified-findings-only contract.

    ABSENCE IS READABLE (T-11035): beside `pairs` the payload names the OBSERVED GRID
    (`observed_workers` × `observed_auditors`) and the cells of it that carry ZERO observations
    (`zero_run_pairs`), so a pair MISSING from `pairs` is no longer ambiguous between "both sides run,
    never together" (a real gap) and "never observed" (no evidence either way) — see `_ABSENCE_NOTE`.
    Its companion is the COVERAGE the payload already states (`attributed_share` +
    `unattributed_reasons`, T-10744): the fold's resolved-wins rule (see
    `_read_pair_observations_for_project`) is what makes that share describe the record rather than an
    artefact of journal line order. Cost is OUT of scope
    here (cross-project cost needs each project's LOCAL transcript archive the kernel can't reach —
    SPEC-0135 §3; the per-project `observation` view owns read-time cost). Fail-OPEN throughout: a bad
    registry or an unreadable project journal degrades to a note/skip, never a crash."""
    from pathlib import Path
    projects_scanned: list = []
    skipped: list = []
    try:
        projects = _v2_projects(registry_path, engine_root, kernel_name)
    except Exception as exc:  # noqa: BLE001 — a bad registry must never crash the rollup lens
        return {
            "keyed_by": "worker×auditor (provider×model×effort) pair",
            "pair_count": 0, "pairs": [], "total_observations": 0,
            "project_count": 0, "projects_scanned": [],
            "no_best_pair": _NO_BEST_PAIR_NOTE,
            "stakes": _STAKES_NOTE,
            # same reason as the adequacy declaration below: the absence CONTRACT is a property of
            # the VIEW, not of a successful scan — a degraded payload must not read as "no gaps".
            "observed_workers": [], "observed_auditors": [],
            "zero_run_pairs": [], "zero_run_pair_count": 0,
            "absence": _ABSENCE_NOTE,
            # the declaration is a property of the VIEW, not of a successful scan — so the
            # degraded payload states it too (T-10746); it just has no pairs to mark.
            "sample_adequacy_floor": _SAMPLE_ADEQUACY_FLOOR,
            "sample_adequacy": _SAMPLE_ADEQUACY_NOTE,
            "notes": [f"registry unreadable ({type(exc).__name__}: {exc}) — no projects to aggregate."],
        }
    agg: dict = {}
    total_obs = 0
    reason_counts: dict = {}
    for proj in projects:
        name = proj.get("name")
        path = proj.get("path")
        try:
            events_path = (Path(path) / "events.jsonl") if path is not None else None
            obs = _read_pair_observations_for_project(events_path, name)
        except Exception:  # noqa: BLE001 — a broken project journal must not abort the whole rollup
            skipped.append(name)
            continue
        projects_scanned.append(name)
        for o in obs:
            total_obs += 1
            # WHY the join failed, tallied per observation (T-10744) — the reader classified it where
            # the join conditions are visible; here it only folds. None == inside the attributed window.
            reason = o.get("attribution_failure")
            if reason:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            key = (o["worker"], o["auditor"])
            s = agg.setdefault(key, {"sample_size": 0, "projects": set(), "sessions": set(),
                                     "verdicts": {}, "by_effort_tier": {}, "by_task_class": {},
                                     "by_project": {}})
            s["sample_size"] += 1
            s["projects"].add(o["project"])
            if o["session_ref"]:
                s["sessions"].add(o["session_ref"])
            v = o["verdict"]
            s["verdicts"][v] = s["verdicts"].get(v, 0) + 1
            # CONTROLLED cross-tabs (T-10647): the same verdict, additionally bucketed by each control
            # dimension. Every observation lands in exactly ONE bucket per cross-tab, so each cross-tab's
            # per-bucket verdict counts SUM to the pooled `verdicts` above — complete, never lossy.
            # `by_project` (T-10745) is the THIRD marginal, over the `project` the fold already reads:
            # the T10 theme MANDATES surfacing "a pair healthy in one project, poor in another", which
            # `project_count` + the bare `projects` LIST cannot express (the divergence is exactly what
            # a pooled verdict mix hides). Same partition property, and no "unknown" bucket can arise
            # here — an observation always names its project (X-0596).
            for dim, bucket in (("by_effort_tier", o["effort_tier"]),
                                ("by_task_class", o["task_class"]),
                                ("by_project", o["project"])):
                b = s[dim].setdefault(bucket, {"sample_size": 0, "verdicts": {}})
                b["sample_size"] += 1
                b["verdicts"][v] = b["verdicts"].get(v, 0) + 1
    # ATTRIBUTION WINDOW (T-10605): a pair is decision-readable ONLY when BOTH triples are fully
    # resolved (no "unknown" on any axis) — an "unknown" worker or auditor tells no pair story. The
    # bulk of the raw scan is pre-instrumentation / unjoined observations that fold to all-"unknown";
    # reporting them alongside real pairs made the rollup un-readable (fu observation-rollup-attribution-
    # unknown-majority). So BOUND the reported `pairs` to the attributed window (SPEC-0135 §5 findings-
    # readable) while SURFACING the full-scan split (total / attributed / unattributed / share) so the
    # bound is a NAMED honest degrade, never a silent truncation (T-0358).
    _fully_attributed = _triple_resolved   # ONE definition of "resolved" (see `_triple_resolved`)

    pairs: list = []
    attributed_obs = 0
    for (w, a), s in agg.items():
        if not (_fully_attributed(w) and _fully_attributed(a)):
            continue
        attributed_obs += s["sample_size"]
        # SAMPLE-ADEQUACY (T-10746): read the DECLARED floor, never a literal — the value lives in
        # `_SAMPLE_ADEQUACY_FLOOR` with its rationale, so changing the declaration changes what the
        # view claims. Stated on EVERY pair, both polarities: silence is not an adequacy verdict.
        claimed = s["sample_size"] >= _SAMPLE_ADEQUACY_FLOOR
        pairs.append({
            "worker": {"provider": w[0], "model": w[1], "effort": w[2]},
            "auditor": {"provider": a[0], "model": a[1], "effort": a[2]},
            "sample_size": s["sample_size"],
            "project_count": len(s["projects"]),
            "projects": sorted(s["projects"]),
            "sessions": len(s["sessions"]),
            # the adequacy marker sits BESIDE the mix it qualifies, so a reader cannot take the
            # counts without the verdict on whether they support a claim. A bool + (below the
            # floor) one reason string — no scalar, no ordering, nothing gated (SPEC-0057 §4).
            "verdict_mix_claimed": claimed,
            **({} if claimed else {"verdict_mix_not_claimed": (
                f"sample_size {s['sample_size']} is below the declared sample_adequacy_floor "
                f"{_SAMPLE_ADEQUACY_FLOOR} — this pair's verdict mix is NOT claimed as a finding "
                "(the counts below are still shown in full, and nothing about this pair is "
                "filtered, reordered or gated by this marker — T-10746)")}),
            "verdicts": dict(sorted(s["verdicts"].items())),
            "by_effort_tier": {k: {"sample_size": b["sample_size"],
                                   "verdicts": dict(sorted(b["verdicts"].items()))}
                               for k, b in sorted(s["by_effort_tier"].items())},
            "by_task_class": {k: {"sample_size": b["sample_size"],
                                  "verdicts": dict(sorted(b["verdicts"].items()))}
                              for k, b in sorted(s["by_task_class"].items())},
            # the DIVERGENCE marginal (T-10745): counts only, same shape as its two siblings — no
            # share, no rate, no ranking, no composite scalar (SPEC-0057 §4 fence).
            "by_project": {k: {"sample_size": b["sample_size"],
                               "verdicts": dict(sorted(b["verdicts"].items()))}
                           for k, b in sorted(s["by_project"].items())},
        })
    # CONFIDENCE order (sample_size desc), NOT a quality ranking (no_best_pair note); tie-break stable.
    pairs.sort(key=lambda x: (-x["sample_size"], x["worker"]["provider"], x["worker"]["model"],
                              x["worker"]["effort"], x["auditor"]["provider"], x["auditor"]["model"],
                              x["auditor"]["effort"]))
    # WHY-breakdown of the unattributed remainder (T-10744): report-only, and SUM-CHECKED against the
    # window arithmetic. If the labels ever disagree with the window (they cannot by construction —
    # both read the same triples — but a future edit could drift them), the difference is NAMED under
    # `unclassified` rather than shipped as a silently under-counting breakdown (T-0358).
    unattributed_obs = total_obs - attributed_obs
    unattributed_reasons = dict(sorted(reason_counts.items()))
    residual = unattributed_obs - sum(unattributed_reasons.values())
    if residual:
        unattributed_reasons["unclassified"] = residual
    # THE OBSERVED GRID + its empty cells (T-11035) — derived from the pairs just folded, no second
    # scan and no new store. The axes are the DISTINCT worker / auditor triples that actually appear
    # in the attributed window, so a "zero-run" claim is only ever made about two sides the record has
    # SEEN; a combination outside the grid stays unclaimed (see `_ABSENCE_NOTE`). Identity only — a
    # zero-run cell has no counts to carry, and inventing a zeroed `verdicts` block for it would read
    # as an observation that never happened.
    _seen_pairs = {(tuple(p["worker"].values()), tuple(p["auditor"].values())) for p in pairs}
    observed_workers = sorted({tuple(p["worker"].values()) for p in pairs})
    observed_auditors = sorted({tuple(p["auditor"].values()) for p in pairs})
    zero_run_pairs = [
        {"worker": {"provider": w[0], "model": w[1], "effort": w[2]},
         "auditor": {"provider": a[0], "model": a[1], "effort": a[2]}}
        for w in observed_workers for a in observed_auditors if (w, a) not in _seen_pairs
    ]
    out = {
        "keyed_by": "worker×auditor (provider×model×effort) pair",
        "pair_count": len(pairs),
        "pairs": pairs,
        "total_observations": total_obs,
        "attributed_observations": attributed_obs,
        "unattributed_observations": unattributed_obs,
        "unattributed_reasons": unattributed_reasons,
        "unattributed_reasons_note": _UNATTRIBUTED_REASONS_NOTE,
        "attributed_share": round(attributed_obs / total_obs, 3) if total_obs else None,
        "window": ("pairs are BOUNDED to the attributed window — observations whose worker AND auditor "
                   "triples are both fully resolved (no 'unknown' axis); the un-joined / pre-instrumentation "
                   "remainder is counted in unattributed_observations, never shown as a phantom pair "
                   "(T-10605, SPEC-0135 §5)."),
        # the absence block: what the view is entitled to call a GAP, and what it must leave unclaimed
        "observed_workers": [{"provider": w[0], "model": w[1], "effort": w[2]}
                             for w in observed_workers],
        "observed_auditors": [{"provider": a[0], "model": a[1], "effort": a[2]}
                              for a in observed_auditors],
        "zero_run_pairs": zero_run_pairs,
        "zero_run_pair_count": len(zero_run_pairs),
        "absence": _ABSENCE_NOTE,
        "project_count": len(projects_scanned),
        "projects_scanned": sorted(projects_scanned),
        "no_best_pair": _NO_BEST_PAIR_NOTE,
        "stakes": _STAKES_NOTE,
        # the floor is DECLARED to the reader, not only to the code — a threshold nobody can see is
        # one every reader re-guesses, which is the defect this closes (T-10746 / X-0596).
        "sample_adequacy_floor": _SAMPLE_ADEQUACY_FLOOR,
        "sample_adequacy": _SAMPLE_ADEQUACY_NOTE,
        "controls": ("each pair carries three CONTROLLED cross-tabs: `by_effort_tier` (from "
                     "bg_dispatch_launched.source_tier — the tier SPEC-0072 routing dispatched on) and "
                     "`by_task_class` (from task_filed.class), both T-10647, plus `by_project` (T-10745 — "
                     "the divergence marginal the T10 theme mandates: one pair healthy in project A and "
                     "poor in project B, which the pooled mix hides). Each bucket holds its own "
                     "sample_size + verdicts. Per-bucket counts SUM to the pooled `verdicts` (complete, "
                     "not lossy) in EVERY cross-tab; an unresolved dimension folds to the 'unknown' "
                     "bucket, never dropping the observation (`by_project` needs no such bucket — an "
                     "observation always names its project). COUNTS only, no score (SPEC-0057 §4)."),
        "source": ("each v2 project's events.jsonl — session_started worker triple (T-10121) JOINED "
                   "by session_ref to external_audit_completed auditor triple (T-10121); enumerated via "
                   "the read-only nightly._v2_projects registry scan (SPEC-0105 §2). Read-time DERIVED, "
                   "no new store (D-0053, SPEC-0135 §2/§4)."),
    }
    if skipped:
        out["skipped_projects"] = sorted(skipped)
    return out

def _view_triage_state(events_path: "Path", *, _last_triage_watermark=None, _scan_captures=None) -> dict:
    """triage-state lens (T-0533 / SPEC-0055): the per-capture routed-marker, DERIVED — never a
    persisted stamp. It answers «which captures are ROUTED vs the GENUINELY-UNROUTED true backlog»
    for EACH deviation_captured, keyed off the SAFE routed boundary (`window_through`, T-0542) — NOT
    off `kind` presence. `kind` is OPTIONAL at capture (D-0086 §2) and routing never backfills it, so
    a naive `kind:none == untriaged` read overcounts the backlog (the 535/660 mis-read). This lens is
    the corrective: routed-state is read from the boundary, kind is IGNORED for routing.

    NO new store, NO mutation of the append-only capture line, NO parallel cursor — the prior
    ceiling-convergence consult REJECTED those; this is the D-0053 view family (Filter 2: a view over
    a derived verdict, not a new entity). The per-capture routed-marker is FULLY determined by the
    latest boundary because the boundary only ADVANCES (windows are closed + non-regressing, T-0542),
    so every earlier window is subsumed — no per-capture persistence is needed to know a specific
    capture was routed. Reuses `_scan_captures` + `_last_triage_watermark` verbatim (Principle 1 F1 —
    one scanner, one boundary reader; no second parse path). Recomputed fresh, writes nothing (D-0053).

    Per-capture bucket (boundary = the latest `window_through`, or None at bootstrap):
      - ROUTED        ts <  boundary  (inside a completed, closed window)
      - UNROUTED      ts >  boundary  (the TRUE backlog) — also EVERY capture when boundary is None
      - BOUNDARY-TIE  ts == boundary  (residual (a): the irreducible exact-equal-second tie — SURFACED
                      per-capture so a same-second capture is never silently mis-bucketed; this also
                      keeps residual (b)'s read->complete-gap capture VISIBLE rather than silently
                      swept-routed — closing both SPEC-0055-deferred residuals at the per-capture level)
    Legacy `friction_captured` is the read-only old name; like the routing window it is EXCLUDED from
    the backlog (it feeds recurrence, not routing — symmetric with `cmd_triage_run`'s window)."""
    boundary = _last_triage_watermark(events_path)
    routed: list = []
    unrouted: list = []
    boundary_tie: list = []
    for c in _scan_captures(events_path):
        if c["type"] != "deviation_captured":   # legacy friction_captured is not a routing subject
            continue
        ts = c["ts"]
        # A capture with no ts cannot be placed against the boundary — treat as UNROUTED (fail-safe:
        # surface it in the backlog rather than silently mark it routed).
        if boundary is None or not ts or ts > boundary:
            unrouted.append(c)
        elif ts == boundary:
            boundary_tie.append(c)
        else:
            routed.append(c)

    def _row(c: dict) -> dict:
        # The per-capture marker row — derived verdict only (no kind-based routing field). `kind` is
        # echoed purely for human context (it may be null — that is fine; it is NEVER read for routing).
        return {"ts": c["ts"], "fingerprint": c["fp"], "relates_to": c["relates_to"] or None,
                "kind": c["kind"]}

    total = len(routed) + len(unrouted) + len(boundary_tie)
    return {
        "lens": "triage-state (SPEC-0055 / T-0533) — per-capture routed-marker, DERIVED from the "
                "window_through boundary; NOT a persisted stamp, NOT kind-based",
        "routed_boundary": boundary or "(bootstrap — no watermark yet; every capture is UNROUTED)",
        "invariant": "routed-state is derived from the SAFE window_through boundary (T-0542) + "
                     "_scan_captures, NEVER from kind presence (kind is OPTIONAL at capture, D-0086 "
                     "§2; routing never backfills it). The true backlog = UNROUTED, not kind-absent.",
        "counts": {"total_deviation_captures": total, "routed": len(routed),
                   "unrouted_true_backlog": len(unrouted), "boundary_tie": len(boundary_tie)},
        # Every deviation_captured gets an EXPLICIT per-capture verdict (audit-post F0: the routed side
        # is not reduced to a bare count — the per-capture routed-MARKER is the deliverable). The three
        # lists partition the captures; `routed` is the marker for the already-routed side.
        "routed": [_row(c) for c in routed],
        "unrouted_true_backlog": [_row(c) for c in unrouted],
        "boundary_tie": [_row(c) for c in boundary_tie],
        "boundary_tie_note": (
            "the exact-equal-second tie at the boundary (residual (a), SPEC-0055) — SURFACED "
            "per-capture so a same-second capture is never silently mis-bucketed; route it explicitly "
            "(it is NOT auto-counted as routed). Close gap-free at completion with "
            "`triage run --complete --through <ts>` (residual (b))."),
        "next": "the UNROUTED set is the genuine backlog to route — run `yitc-v2 triage run`.",
    }

def _view_journal_hygiene(events_path: "Path", *, _last_triage_watermark=None, _scan_captures=None) -> dict:
    """journal-hygiene lens (T-9738): a THIN report-only WEEKLY-hygiene digest pairing the two
    operational-pressure numbers into ONE glance — journal GROWTH + untriaged deviation-capture
    PRESSURE. It COMPOSES existing derived readers, adds NO store / reader / event / command family
    (D-0053 view family, P1 F1): the growth half reads the LIVE segment via `.stat()` + a line count
    vs the shared `_JOURNAL_ROTATION_BYTES` constant (the SAME threshold + the SAME quantity
    displacement-retention surface #1 checks — D-0030 `> 10 MB` rotation home, one source) and
    REPORTS the all-segment aggregate beside it as a trajectory (T-11843), and the pressure half reuses
    `_last_triage_watermark` + `_scan_captures` VERBATIM (the triage-state basis). Recomputed fresh,
    writes nothing (D-0053).

    Why a dedicated digest vs the three neighbours: trend-report is the WINDOWED multi-section L4
    ревизия feed (needs --since/--until), triage-state is the per-capture routed-MARKER list, and
    displacement-retention is the multi-surface fired/acted trigger checklist — none is a one-glance
    weekly pairing of exactly these two headline numbers. This lens retires the ad-hoc "eyeball two
    views / re-measure journal size by hand weekly" step (P1 F3), pointed at by a weekly roster row.

    UNTRIAGED PRESSURE = the watermark-derived UNROUTED backlog (ts > boundary), NOT kind-absence:
    kind is OPTIONAL at capture (D-0086 §2) and routing never backfills it, so `kind:null == untriaged`
    OVERCOUNTS (the SPEC-0055 / triage-state doctrine). `kind_absent` is reported as a LABELLED
    informational aside only — never the backlog measure (P7)."""
    # --- journal growth (size pressure vs the shared rotation threshold) ---
    ev_bytes = _live_segment_bytes(events_path)  # T-11843: the LIVE segment — what the trigger measures
    ev_all_bytes = journal_mod.segment_size(events_path)  # logical size across segments (SPEC-0190 r8)
    total_events = 0
    if events_path.exists():
        for line in journal_mod.segment_lines(events_path, errors="replace"):  # T-11444: segment-aware fold (SPEC-0190 r4)
            if line.strip():
                total_events += 1
    journal_growth = {
        "size_bytes": ev_bytes,
        "size_mb": round(ev_bytes / (1024 * 1024), 2),
        "measures": "the LIVE segment (T-11843)",
        "total_events": total_events,
        "rotation_threshold": "> 10 MB",
        "fired": ev_bytes > _JOURNAL_ROTATION_BYTES,
        "all_segment_size_bytes": ev_all_bytes,
        "all_segment_size_mb": round(ev_all_bytes / (1024 * 1024), 2),
        "all_segment_note": "REPORT-ONLY TRAJECTORY (T-11843) — the logical journal across every "
                            "segment, carrying NO trigger. The `> 10 MB` trigger annotates the LIVE "
                            "segment (the quantity rotation's own action moves); annotating the "
                            "aggregate lit a flag no permitted action could clear, since archive "
                            "segments are append-only and SPEC-0002 §Violations forbids a rewrite.",
        "governing_trigger": "D-0030 rotation_policy (SPEC-0190 §Rotation policy); the acted-check + "
                             "the standing-DEFER disjunct live in the displacement-retention lens",
    }

    # --- untriaged capture pressure (watermark-derived backlog; NOT kind-absence) ---
    boundary = _last_triage_watermark(events_path)
    unrouted = routed = boundary_tie = 0
    kind_absent = 0
    for c in _scan_captures(events_path):
        if c["type"] != "deviation_captured":   # legacy friction_captured feeds recurrence, not routing
            continue
        if c.get("kind") is None:
            kind_absent += 1
        ts = c["ts"]
        if boundary is None or not ts or ts > boundary:
            unrouted += 1
        elif ts == boundary:
            boundary_tie += 1
        else:
            routed += 1
    total_captures = routed + unrouted + boundary_tie
    untriaged_capture_pressure = {
        "routed_boundary": boundary or "(bootstrap — no watermark yet; every capture is UNROUTED)",
        "unrouted_true_backlog": unrouted,
        "boundary_tie": boundary_tie,
        "routed": routed,
        "total_deviation_captures": total_captures,
        "kind_absent_informational": kind_absent,
        "kind_absent_note": "INFORMATIONAL ONLY — kind-absence is NOT the backlog measure (kind is "
                            "optional at capture, D-0086 §2; routing never backfills it). The genuine "
                            "backlog = unrouted_true_backlog (ts > watermark boundary), SPEC-0055.",
    }

    return {
        "lens": "journal-hygiene (T-9738) — report-only WEEKLY digest: journal growth + untriaged "
                "deviation-capture pressure; COMPOSES existing readers, NO new store",
        "weekly_hygiene": (
            f"journal live segment {journal_growth['size_mb']} MB "
            f"({'OVER 10MB rotation trigger' if journal_growth['fired'] else 'under 10MB trigger'}) / "
            f"all segments {journal_growth['all_segment_size_mb']} MB (trajectory, no trigger) / "
            f"{total_events} events; "
            f"{unrouted} untriaged capture(s) in the backlog"
            + (f" + {boundary_tie} boundary-tie" if boundary_tie else "")),
        "journal_growth": journal_growth,
        "untriaged_capture_pressure": untriaged_capture_pressure,
        "next": ("size fired? → see the displacement-retention lens for the fired/acted trigger check. "
                 "Backlog > 0? → run `yitc-v2 triage run` (per-capture detail: `graph query triage-state`)."),
    }

_CAPTURE_ROUTING_ROWS = [
    # (situation, home, owning_spec_id, note)
    ("a one-off deviation / friction / nonconformity",
     "a `deviation_captured` event (event-only by default; from anywhere, no worktree)",
     "SPEC-0056", "capture is a reflex — most stay event-only forever; AGENTS §Deviation-capture."),
    ("a recurring or hard-defect ROOT (N>=2 / owner-requested)",
     "promote to an `errors/E-XXXX.yaml` case file (file-or-waive)",
     "SPEC-0056", "the promote boundary; cluster the root once, members route `linked` (SPEC-0055)."),
    ("a MULTI-ERROR incident ARC narrative",
     "the promoted `errors/E-XXXX.yaml` case BODY — ONE arc = ONE E-case, cites-linked",
     "SPEC-0056", "§4a (T-10537); NO new doc class / node type — reference-first, cite the arc."),
    ("a mid-work adjacent to-do (drained later)",
     "`followup add` — a staged followup, or a bare `tasks/<id>.yaml`",
     "SPEC-0095", "the carrier sieve (plan vs task vs followup) is SPEC-0140."),
    ("a standing RULE / invariant / contract / governing param",
     "a `proposed` spec (`spec new`), activated at its owner task's close",
     "SPEC-0005", "the before-rule-change floor delivers SPEC-0005/0073/0128."),
    ("a general, TRAVELING reusable practice",
     "a `patterns/<name>.md` doc (cross-project methodology)",
     "SPEC-0005", "traveling = pattern; LOCAL = lesson (the SPEC-0090 boundary)."),
    ("a per-repo LOCAL craft note (non-traveling)",
     "a `lessons/<slug>.md` node",
     "SPEC-0090", "the local counterpart of a pattern; project realm (SPEC-0073)."),
    ("an ENVIRONMENT FACT — neighbor-contracts / data-quirks / glossary",
     "a FACT-FLAVORED `lessons/<slug>.md` (human-read local fact)",
     "SPEC-0090", "X-0403: a fact is not a practice and not a rule — it is local craft."),
    ("an ENVIRONMENT FACT — machine-read baseline (startup_checks / verify rows / deploy policy / config)",
     "the `yitc-ops.yaml` carrier",
     "SPEC-0093", "X-0403: machine-consumed project contract, not prose."),
    ("a user-path narration",
     "a `scenarios/<slug>.md` node (zero-normative, cites the specs)",
     "SPEC-0076", "the 7th graph node; authored at the plan draft->specs seam."),
    ("a CROSS-PROJECT coordination item",
     "`cross request` on the kernel-owned SHARED coordination log (`to:<project>`)",
     "SPEC-0084", "protocol SPEC-0085; verbs SPEC-0086; never edit another repo."),
    ("a WORKER ESCALATION rationale (blocked-on-land / audit halt)",
     "a `decisions/<task>-escalation.md` doc (the de-facto convention, NOW named)",
     "SPEC-0157", "R3: over the EXISTING `decisions/` store — no new store/node."),
    ("a design DELIBERATION / rejected alternatives / trial-on-real-data",
     "a `plans/<slug>.md` (the plan carrier)",
     "SPEC-0140", "the carrier sieve routes plan vs one-or-a-few tasks vs followup."),
    ("a near-term, consume-once cross-session note",
     "the `MEMORY.md` buffer (non-authoritative; deleted after use)",
     "SPEC-0039", "NEVER a durable rule home — route by purpose (SPEC-0091)."),
]

def _view_capture_routing(index: dict) -> dict:
    """capture-routing lens (T-10539 / SPEC-0157, D-0053 saved view): the situation->home routing table
    — at the MOMENT of a capture, WHERE does it go? Each row names the SITUATION, its HOME (the
    artifact/node/store), and the OWNING SPEC that homes the rule; the rule text is NEVER duplicated
    (SPEC-0005 rule 8) — the view ROUTES, the specs GOVERN. Composes existing homes, adds NO store /
    node-type / edge (CHARTER §P1 F2), recomputed fresh on read.

    Sources rows from the owning specs (X-0402 G3 closed): each row's `owning_spec` is enriched with its
    live title/status from `index["specs"]`, so a renamed/removed/retired owning spec surfaces here
    rather than drifting silently (the E-case narrative row is SPEC-0056 §4a, T-10537). Names the
    de-facto worker escalation-doc convention (R3) and the environment-facts flavors (X-0403)."""
    specs_tbl = (index or {}).get("specs") or {}
    rows = []
    for situation, home, sid, note in _CAPTURE_ROUTING_ROWS:
        meta = specs_tbl.get(sid) or {}
        title = (meta.get("title") or "").strip()
        status = (meta.get("status") or "").strip()
        owning = f"{sid} — {title}" if title else sid
        if status and status not in ("active", "proposed"):
            owning += f"  [!{status}]"   # surface a retired/superseded owning spec (drift signal)
        elif not title:
            owning += "  [!unresolved]"  # the owning spec id no longer resolves in the index
        rows.append({
            "situation": situation,
            "home": home,
            "owning_spec": owning,
            "note": note,
        })
    return {
        "lens": ("capture-routing (T-10539 / SPEC-0157) — situation->home routing table: where each "
                 "capture goes, anchored to the owning spec (the rule's one home). View over existing "
                 "homes, no new store (D-0053)."),
        "routing": rows,
        "conventions": {
            "worker_escalation_doc": "decisions/<task>-escalation.md (SPEC-0157 §3 — the de-facto home, now named)",
            "environment_facts": ("neighbor-contracts / data-quirks / glossary -> a fact-flavored "
                                  "lessons/<slug>.md (SPEC-0090); machine-read baselines -> yitc-ops.yaml "
                                  "(SPEC-0093) [X-0403]"),
            "incident_narrative": "a multi-error arc -> the promoted errors/E-XXXX.yaml BODY, one arc = one E-case (SPEC-0056 §4a)",
        },
        "next": ("read the row for your situation, then route to its HOME; the OWNING SPEC holds the "
                 "actual rule (`graph query <SPEC>`). Unsure plan vs task vs followup? -> SPEC-0140."),
    }

def _window_predicate(since, until, *, _ev_dt=None):
    """Build the `[since, until)` in-window test shared by the journal-windowed lenses (T-10361).

    Reuses the trend-report window semantics VERBATIM (since INCLUSIVE, until EXCLUSIVE; either may be
    None = open-ended) — one semantic, not a second dialect (Principle 1: extend, don't parallel).

    Fail-closed on an unparseable/absent `ts` WHEN a window is active: an event whose time cannot be
    read cannot be PROVEN in-window, so it is excluded rather than silently counted into the window.
    With no window the predicate is a constant True — an unwindowed run therefore counts exactly the
    events it counted before this change (the all-time reading stays byte-identical)."""
    if since is None and until is None:
        return lambda e: True

    def _in_window(e) -> bool:
        dt = _ev_dt(e.get("ts"))
        if dt is None:
            return False
        if since is not None and dt < since:
            return False
        if until is not None and dt >= until:
            return False
        return True

    return _in_window

def _window_block(since, until) -> dict:
    """The self-describing `window:` block a windowed lens reports (T-10361), so a windowed run is never
    mistaken for an all-time one: `active` states plainly which reading the numbers are."""
    return {
        "active": since is not None or until is not None,
        "since": since.isoformat() if since is not None else None,
        "until": until.isoformat() if until is not None else None,
        "semantics": "since INCLUSIVE, until EXCLUSIVE; an event with an unparseable ts is EXCLUDED "
                     "when a window is active (fail-closed — it cannot be proven in-window).",
    }

def _view_discipline_ratio(events_path: "Path", since=None, until=None, *,
                           _iter_events=None, _ev_dt=None) -> dict:
    """discipline-ratio lens (T-0603 / SPEC-0059): the kind-AWARE read-gate discipline metric — the
    `read_gate_refused` NUMERATOR split BY `kind` over the `cli_invoked` DENOMINATOR. NEVER one mixed
    ratio (plan-check F3): a SEPARATE ratio per canonical kind — a MAIN read-check ratio + sibling
    ratios for stage-correspondence + verification-exists — so the three legs of the universal stage
    contract (SPEC-0059) stay analyzable independently, never conflated. Pure f over the journal,
    recomputed fresh, writes nothing (D-0053 view family); reuses the line-by-line json.loads journal
    scan (Principle 1 — one reader, no new parse path). NO new store/hook/flag/event.

    Denominator = the count of `cli_invoked` events (the activity baseline; the T-0113 emitter). Numerator
    = `read_gate_refused` events bucketed by `data.kind`, where the legacy T-0531 interim "stage" literal
    is folded into read-check (the `_emit_read_gate_refused` reconciliation) so the historical read-check
    refusals bucket correctly. Each canonical kind ALWAYS appears (even at zero — fail-visible); a
    non-canonical kind surfaces in `other` rather than being silently dropped. denom==0 → every ratio is
    null (bootstrap — no activity to divide by).

    WINDOW (T-10361): the optional `[since, until)` pair bounds the journal scan to a time window, so the
    metric reads CURRENT discipline instead of an all-time average in which a fixed historical backlog of
    refusals permanently dominates a growing denominator. Semantics + fail-closed ts handling are shared
    with the sibling lenses via `_window_predicate`. An EMPTY window yields denom==0 → null ratios, which
    is the correct reading: "no activity to divide by" is NOT "perfect discipline" (T-0358).

    Lower ratio = better discipline (fewer refusals of that kind per invocation). Report-not-block: a
    non-zero ratio is a signal to investigate the verb/stage behind the refusals, NOT a gate (D-0053).
    A reviewer RUNNING this lens IS the P8 consumer-read adoption evidence (the `cli_invoked` emit on
    `graph query discipline-ratio` is the durable run-evidence row)."""
    denom = 0
    numer = {k: 0 for k in _DISCIPLINE_RATIO_KINDS}
    other: dict = {}
    legacy_folded = 0
    in_window = _window_predicate(since, until, _ev_dt=_ev_dt)
    # Reuse the ONE journal reader (`_iter_events`, Principle 1 — single parse path, no second loop);
    # the explicit path keeps the lens isolatable (a test sandbox journal) through that same reader.
    for e in _iter_events(events_path):
        t = e.get("type")
        if t not in ("cli_invoked", "read_gate_refused"):
            continue
        if not in_window(e):
            continue
        if t == "cli_invoked":
            denom += 1
        else:
            raw = (e.get("data") or {}).get("kind")
            kind = _READ_GATE_KIND_ALIASES.get(raw, raw)
            if raw in _READ_GATE_KIND_ALIASES:
                legacy_folded += 1
            if kind in numer:
                numer[kind] += 1
            else:
                key = kind if kind is not None else "(none)"
                other[key] = other.get(key, 0) + 1

    def _ratio(n: int):
        # null when there is no denominator — NEVER a fabricated 0.0 (the T-0358 no-fabricated-zero
        # precedent): "no activity to divide by" is not "perfect discipline".
        return round(n / denom, 6) if denom else None

    def _per_1k(n: int):
        return round(n / denom * 1000, 3) if denom else None

    ratios = {
        k: {"refusals": numer[k], "ratio": _ratio(numer[k]), "per_1k_cli_invoked": _per_1k(numer[k])}
        for k in _DISCIPLINE_RATIO_KINDS
    }
    result = {
        "lens": "discipline-ratio (SPEC-0059 / T-0603) — read_gate_refused numerator SPLIT BY kind over "
                "the cli_invoked denominator; kind-aware, NEVER one mixed ratio (plan-check F3)",
        # T-10361: self-describing — a `--since`-windowed run is never read as an all-time one.
        "window": _window_block(since, until),
        "denominator": {"cli_invoked": denom},
        "invariant": "ONE ratio PER canonical kind (read-check / stage-correspondence / "
                     "verification-exists) — NEVER a single mixed ratio summing the kinds (plan-check "
                     "F3). Each ratio = read_gate_refused[kind] / cli_invoked; lower = better discipline. "
                     "Every kind is reported even at zero (fail-visible).",
        # The three canonical kinds, each its OWN ratio (the F3-honoring split) — the MAIN read-check
        # ratio + the two sibling ratios. Never reduced to a single aggregate figure.
        "ratios": ratios,
        # Provenance: how many refusals were folded from the legacy "stage" literal into read-check.
        "legacy_stage_literal_folded_into_read_check": legacy_folded,
    }
    if other:
        # Fail-visible: a kind outside the locked enum is SURFACED, never silently dropped — a new/unknown
        # kind appearing here is itself a signal (the enum may need extending, or a typo at an emit site).
        result["other_kinds"] = dict(sorted(other.items()))
    result["next"] = ("a non-zero ratio is a discipline SIGNAL, not a gate — investigate the verb/stage "
                      "behind the refusals of that kind (report-not-block, D-0053).")
    return result

# The audit gates whose first-pass verdict the outcome-ratio lens reports, each keyed by its event type.
# Reported PER GATE and never summed: a pre-audit RED (the plan was wrong) and a post-audit RED (the diff
# was wrong) are different failure modes with different fixes — the same kind-split discipline the
# discipline-ratio lens holds across its refusal kinds (plan-check F3).
_OUTCOME_AUDIT_GATES = {"pre": "audit_pre_completed", "post": "audit_post_completed"}
# The canonical audit verdicts (SPEC-0036). A verdict outside this set is surfaced, never dropped.
_OUTCOME_VERDICTS = ("GREEN", "YELLOW", "RED", "ABORT")
# The deviation-capture event + its retired legacy name (D-0086 renamed friction_captured →
# deviation_captured; the historical rows keep the old type, so BOTH count or the metric under-reports).
_OUTCOME_DEVIATION_TYPES = ("deviation_captured", "friction_captured")

def _normalize_audit_verdict(data: dict) -> "str | None":
    """An audit event's verdict, normalized (T-10361).

    TWO shapes exist in the journal and BOTH are load-bearing: `data.verdict` (the current key) and
    `data.final_verdict` (the early-history key). Reading only one silently under-counts the other's rows.

    Values also carry absorption suffixes (`YELLOW-absorbed`, `GREEN-on-absorption`, `RED-absorbed`), so
    the leading token before `-` is the verdict. Returns None when neither key is present."""
    raw = data.get("verdict", data.get("final_verdict"))
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip().split("-", 1)[0].upper()

def _view_outcome_ratio(events_path: "Path", since=None, until=None, *,
                        _iter_events=None, _ev_dt=None) -> dict:
    """outcome-ratio lens (T-10361): the aggregate OUTCOME metrics of the lifecycle — what a closed task
    actually COSTS and how often it passes its gates on the first try. Three ratios over one journal pass:

      - `audits_per_close`      = (audit_pre_completed + audit_post_completed) / task_closed
      - `first_pass_green_pct`  = per gate, the share of tasks whose EARLIEST audit at that gate was GREEN
      - `red_rate`              = per gate, the share of verdicted audit PASSES that came back RED
      - `deviations_per_close`  = (deviation_captured + friction_captured) / task_closed

    RED RATE vs FIRST-PASS-GREEN are different POPULATIONS and the split is load-bearing (T-11047):
    first-pass counts each TASK once per gate (its earliest pass), red_rate counts every verdicted PASS.
    "How often does this gate come back RED" is a question about passes; "how often does a task clear on
    the first try" is a question about tasks. Neither figure is derivable from the other.

    Sibling to `discipline-ratio` (that lens measures read-gate REFUSALS per invocation; this one measures
    audit COST + first-pass success + deviation pressure per CLOSED task). Same posture throughout: pure f
    over the existing journal, recomputed fresh, writes nothing (D-0053 view family); reuses the one
    line-by-line reader (`_iter_events`) and the one window predicate. NO new store, NO new query surface,
    NO metrics daemon, NO new event type (CHARTER §6 non-goal: no observability layer).

    FIRST-PASS, precisely: a task is counted at a gate iff it has ≥1 audit event there; its first pass is
    the EARLIEST such event by `ts`. Ties on an identical ts resolve to journal order (append-only ⇒ the
    earlier line is the earlier pass). A task audited pre but never post appears in the pre denominator
    only — the gates are independent populations, never one mixed figure.

    NO FABRICATED ZEROS (T-0358): every metric whose denominator is 0 is `null`, not 0.0 — "no closes to
    divide by" is not "zero cost". An event with an unparseable ts is excluded under an active window
    (fail-closed, `_window_predicate`).

    Report-not-block (D-0053): these are SIGNALS — a rising audits-per-close or a falling first-pass-GREEN
    is a prompt to look at what changed, never a gate. A reviewer RUNNING this lens IS the P8 consumer-read
    adoption evidence (the `cli_invoked` emit on `graph query outcome-ratio` is the durable run-evidence row)."""
    closes = 0
    deviations = 0
    audits = {g: 0 for g in _OUTCOME_AUDIT_GATES}
    # T-11047: the PASS-population verdict histogram per gate — every verdicted audit row, NOT one row
    # per task. This is a DIFFERENT population from `first` below (which keeps one earliest row per
    # task), and the difference is the point: "how often does this gate come back RED" is a question
    # about PASSES, while first-pass-GREEN is a question about TASKS. Counting either with the other's
    # denominator silently answers a question nobody asked.
    passes = {g: {} for g in _OUTCOME_AUDIT_GATES}
    # per gate: task_id -> (ts, verdict) of the EARLIEST audit event seen at that gate
    first: dict = {g: {} for g in _OUTCOME_AUDIT_GATES}
    other_verdicts: dict = {}
    event_to_gate = {ev: g for g, ev in _OUTCOME_AUDIT_GATES.items()}
    in_window = _window_predicate(since, until, _ev_dt=_ev_dt)

    # ONE pass over the ONE reader (Principle 1 — no second parse path).
    for e in _iter_events(events_path):
        t = e.get("type")
        if not in_window(e):
            continue
        if t == "task_closed":
            closes += 1
        elif t in _OUTCOME_DEVIATION_TYPES:
            deviations += 1
        elif t in event_to_gate:
            gate = event_to_gate[t]
            audits[gate] += 1
            tid = e.get("task_id")
            if not tid:
                continue   # an audit event with no task_id cannot join a first-pass population
            verdict = _normalize_audit_verdict(e.get("data") or {})
            if verdict is None:
                continue   # unverdicted row: counted as an audit, but it cannot be a first-pass outcome
            passes[gate][verdict] = passes[gate].get(verdict, 0) + 1
            if verdict not in _OUTCOME_VERDICTS:
                # Fail-visible: an unknown verdict is SURFACED (a new verdict, or a typo at an emit site),
                # never silently folded into not-GREEN.
                other_verdicts[verdict] = other_verdicts.get(verdict, 0) + 1
            dt = _ev_dt(e.get("ts"))
            prev = first[gate].get(tid)
            if prev is None:
                first[gate][tid] = (dt, verdict)
            elif dt is not None and (prev[0] is None or dt < prev[0]):
                # Earliest wins, and a parseable ts displaces an unparseable one. A tie keeps the
                # already-seen row — the append-only journal orders same-ts events by line.
                first[gate][tid] = (dt, verdict)

    total_audits = sum(audits.values())

    def _per_close(n: int):
        # null when there is no denominator — NEVER a fabricated 0.0 (T-0358 no-fabricated-zero).
        return round(n / closes, 6) if closes else None

    # T-11047 (AC3): when the denominator is absent, SAY SO and NAME the instrument. A bare null reads as
    # "the metric is missing"; this reads as "the journal had no task_closed rows here" — the difference
    # between an unavailable input and a measured zero, which is the whole distinction this card carries.
    no_close_data = (None if closes else
                     "no-data: no `task_closed` rows in window — the per-close denominator is ABSENT, "
                     "not zero (nothing closed here, so cost-per-close is unmeasured, not free)")

    first_pass = {}
    for gate in _OUTCOME_AUDIT_GATES:
        tasks = first[gate]
        green = sum(1 for _, v in tasks.values() if v == "GREEN")
        n = len(tasks)
        first_pass[gate] = {
            "tasks_audited": n,
            "first_pass_green": green,
            # Per-gate percent; null (never 0.0) when no task reached this gate in the window.
            "first_pass_green_pct": round(green / n * 100, 3) if n else None,
            "verdict_breakdown": {
                v: sum(1 for _, fv in tasks.values() if fv == v) for v in _OUTCOME_VERDICTS
            },
        }
        if not n:
            # AC3 applies to THIS figure too (ceiling-consult finding): a bare null reads as "the metric
            # is missing", where the fact is that no task reached this gate in the window.
            first_pass[gate]["no_data"] = (
                f"no-data: no task reached the {gate} gate in window (no `{_OUTCOME_AUDIT_GATES[gate]}` "
                f"row with a task_id and a verdict) — the first-pass denominator is ABSENT, not zero")

    # T-11047 (AC1): RED RATE — the share of audit PASSES at each gate that came back RED. Per gate and
    # never summed (the same F3 kind-split the first-pass figure holds): a pre-audit RED says the PLAN was
    # wrong, a post-audit RED says the DIFF was wrong. `red_pct` is null — never 0.0 — when the gate saw no
    # verdicted pass in the window, because "no passes to divide by" is not "no REDs" (T-0358); the
    # accompanying `no_data` line NAMES the instrument that had nothing to read rather than reporting a
    # zero a reader would take for a measurement.
    red_rate = {}
    for gate, ev in _OUTCOME_AUDIT_GATES.items():
        hist = passes[gate]
        n = sum(hist.values())
        red = hist.get("RED", 0)
        entry = {
            "verdicted_passes": n,
            "red_passes": red,
            "red_pct": round(red / n * 100, 3) if n else None,
            "verdict_histogram": dict(sorted(hist.items())),
        }
        if not n:
            entry["no_data"] = (f"no-data: no verdicted `{ev}` rows in window — the {gate}-gate RED-rate "
                                f"denominator is ABSENT, not zero (no passes to divide by is not no REDs)")
        red_rate[gate] = entry

    result = {
        "lens": "outcome-ratio (T-10361; red_rate T-11047) — aggregate lifecycle OUTCOME metrics over the "
                "journal: audits-per-close, first-pass-GREEN percent (PER GATE), RED rate (PER GATE), "
                "deviations-per-close",
        "window": _window_block(since, until),
        "denominator": {"task_closed": closes},
        "invariant": "first-pass-GREEN is reported PER GATE (pre / post) — NEVER one mixed figure summing "
                     "the gates (the discipline-ratio kind-split discipline, plan-check F3): a pre-audit "
                     "RED means the PLAN was wrong, a post-audit RED means the DIFF was wrong — different "
                     "failure modes, different fixes. Every denominator==0 metric is null, never a "
                     "fabricated 0.0 (T-0358).",
        "audits_per_close": {
            "audits_total": total_audits,
            "by_gate": dict(audits),
            "ratio": _per_close(total_audits),
            **({} if closes else {"no_data": no_close_data}),
        },
        # Each gate its OWN first-pass population + percent (the F3-honoring split).
        "first_pass_green_pct": first_pass,
        # T-11047: the PASS-population sibling of the above — same F3 split, different denominator.
        "red_rate": red_rate,
        "deviations_per_close": {
            "deviations_total": deviations,
            "ratio": _per_close(deviations),
            **({} if closes else {"no_data": no_close_data}),
        },
    }
    if other_verdicts:
        # Fail-visible, mirroring discipline-ratio's `other_kinds`.
        result["other_verdicts"] = dict(sorted(other_verdicts.items()))
    result["next"] = ("these are SIGNALS, not gates (report-not-block, D-0053) — a rising audits-per-close "
                      "or a falling first-pass-GREEN says look at what changed upstream (plan quality at "
                      "the pre gate, execution fidelity at the post gate); pair with `graph query "
                      "discipline-ratio --since <date>` for the read-gate side of the same window.")
    return result

# ── admission-series lens (T-11047 / SPEC-0132 Rule 4) ────────────────────────────────────────────
# SPEC-0132 Rule 4 defers Tier-C affected-test selection until, among other triggers, "verifier queueing
# blocks > 25% of lands for 7 CONSECUTIVE days". That is a PER-DAY series with a run-length, and nothing
# computed it: admission queueing was read as one aggregate, so fired-versus-acted could not be
# adjudicated against the threshold at all. This lens is that instrument.
_ADMISSION_THRESHOLD_PCT = 25.0     # SPEC-0132 Rule 4 — READ from the rule, never re-tuned here (the lens
                                    # REPORTS against the threshold; moving it is an owner ladder decision).
_ADMISSION_CONSECUTIVE_DAYS = 7     # Rule 4's "7 consecutive days" — the run-length that makes it FIRE.
# THE FOLDED QUEUE-WAIT TYPES ARE NOT LISTED HERE — they are READ from the engine's own
# `journal.LAND_QUEUE_WAIT_TYPES`, the single carrier `land` already consults at four sites. This
# lens formerly declared ONE type of its own (`waiting_for_verify_admission_slot`), and that private
# copy is exactly how it went blind: T-11117 moved the dominant park UPSTREAM to the land-fairness
# RESERVATION seam, `land` followed (it reads both), and the lens did not. Measured 2026-08-26 — the
# type this lens read last produced a row on 2026-08-19T09:30:33Z, while the seam it did not read
# produced 2018 rows in a single eight-hour window that the lens rendered as `queued_pct: 0.0`.
# Re-listing the set here would rebuild the same divergence, so it is imported instead (T-11614).
# The import is FUNCTION-LOCAL (inside `_view_admission_series`): `lib.worktree` is a heavy module
# and the T-11320/T-11540 lazy-import discipline pins what a bare CLI load may pull. There is
# deliberately NO fallback tuple — a fallback would BE the second drifting list this removes.
# The Rule-4 ACT: the escalation a fired trigger is supposed to PRODUCE. Absence of any of these in a
# window where the trigger fired is exactly the "fired but not acted" reading the revizia could not make.
_ADMISSION_ACT_MARKERS = ("tier_c", "affected-test", "affected_test", "test-selection", "test_selection")

def _view_admission_series(events_path: "Path", since=None, until=None, *,
                           _iter_events=None, _ev_dt=None) -> dict:
    """admission-series lens (T-11047): the PER-DAY land-queueing series over the SEVEN-day window
    SPEC-0132 Rule 4 governs, with the threshold comparison and the consecutive-day run-length.

    THE INSTRUMENT, precisely. A queued land is folded from the engine's queue-wait heartbeats
    (`journal.LAND_QUEUE_WAIT_TYPES` — BOTH the SPEC-0132 verify-admission slot and the T-11117
    land-fairness reservation) by `(session_ref, branch)` — one land per key, carrying its PEAK
    `waited_s` across every seam it parked at. A land parked at BOTH seams is ONE queued land, never
    two: the union is taken at the fold key, which is what keeps the existing fold-once property
    intact. That fold is
    then JOINED to the `land_completed` row of the same key and the land is bucketed by the LAND's UTC
    day, NOT by the heartbeat's: numerator and denominator must sit on the same day or a wait crossing
    UTC midnight produces a false daily percent (audit-pre finding, 2026-08-25). A fold with NO matching
    land_completed row is NOT in any day's numerator — it is reported under `unmatched_queue_folds`
    (still-queued or abandoned lands), never silently dropped and never inflating a ratio.

    WHY BOTH SEAMS, AND WHY LABELLED (T-11614). They are two genuinely DIFFERENT queues, not one
    wait under a renamed emit: `waiting_for_verify_admission_slot` is emitted while blocked on one of
    N verify-concurrency `slot-i` flocks, `waiting_for_land_reservation` while parked on the single
    reservation flock that serializes merge->verify->ff. A land can be parked at either, and since
    T-11117 serializes that span, a queued peer is normally parked at the RESERVATION and only the
    holder ever reaches the admission slot. Both are "verifier queueing blocks a land" in Rule 4's own
    words, so both belong in the numerator — but folding one INTO the other silently would redefine
    the series, so `instrument.streams` NAMES each folded type and reports what it actually
    contributed. A folded type with ZERO rows in the queried window is reported ABSENT rather than
    rendered as a quiet queue: the same no-fabricated-zeros discipline this lens already applies
    per-day, on the INSTRUMENT axis.

    WHICH FIELD MEASURES THE QUEUE (load-bearing — the wrong one has already produced a published false
    figure). The heartbeat fold is the PRIMARY instrument. `land_completed.data.admission_wait_ms` is
    NOT: T-11119 established it under-reports (root cause followup fu_ea1d38d32ef0) — the "median and
    p90 admission wait = 0.0s" reading drawn from it was an artefact, and the pool it declared
    uncontended was in fact severely contended. It is reported here BESIDE the primary as a labelled
    `secondary_instrument` precisely so the divergence stays VISIBLE: a reader sees two instruments
    disagreeing and knows which one to trust, instead of inheriting one field's blind spot.

    FIRED vs ACTED. A day FIRES when queued_pct > 25.0. The trigger MEETS Rule 4 only on a run of 7
    CONSECUTIVE fired days — a per-day series without the run-length still cannot adjudicate the rule.
    When it is met, the window is scanned for a Rule-4 ACT (a Tier-C / affected-test-selection
    escalation), so "threshold crossed" is distinguishable from "crossed and nothing happened".

    NO FABRICATED ZEROS (T-0358, and the distinction this card carries): a day with no lands reports
    `no_data` NAMING the absent instrument, never 0.0% — an unmeasured day is not a quiet day. The
    reported `journal_segment_covers` states the span the journal actually holds, so a window reaching
    past the live segment's start is VISIBLE rather than silently short.

    THE SEVEN-DAY DEFAULT IS THE CLI'S, NOT THIS FUNCTION'S. Called with no window this lens reads
    ALL-TIME, like every other windowed lens in the family — the `graph query admission-series` dispatch
    branch is what substitutes the governed seven-day window when the caller names none, because the
    rule's unit is a seven-day run and an all-time reading cannot adjudicate it. The default lives at the
    CLI seam deliberately: a lens that silently re-dated its own window would make every programmatic
    caller (the census multiset-identity driver among them) read a different corpus than it passed.

    Posture: pure f over the journal, ONE pass over the shared reader, recomputed fresh, writes nothing
    (the D-0053 view family). No new store, no new event type, no daemon (CHARTER §6)."""
    in_window = _window_predicate(since, until, _ev_dt=_ev_dt)
    lands_by_day: dict = {}          # day -> land count (the DENOMINATOR)
    land_rows: dict = {}             # (session_ref, branch) -> [(dt, day)] land_completed rows
    folds: dict = {}                 # (session_ref, branch) -> {"first": dt, "peak": int}
    wait_ms_seen, wait_ms_nonzero = 0, 0
    # T-11614 — the folded set is never re-listed here (see the module note above
    # `_view_admission_series` for why a private copy is what went blind). T-11831 moved the carrier
    # DOWN to `journal.LAND_QUEUE_WAIT_TYPES`, the leaf this module already imports eagerly, so this
    # lens no longer reaches up into `lib.worktree` for it — and rule 27's aborted-land phase split
    # now resolves ITS wait series through the SAME home rather than through the
    # `secondary_instrument` field this lens forbids quoting.
    wait_types = tuple(journal_mod.LAND_QUEUE_WAIT_TYPES)
    # Per-stream row counts, so the label below is DERIVED from what was read rather than asserted.
    # Counted IN-WINDOW: the question `instrument.streams` answers is "did this seam speak during the
    # window you asked about", and a heartbeat outside it is not evidence that it did. (The FOLD
    # itself stays un-windowed — see the fold branch — because window membership is the LAND's.)
    stream_rows = {wt: 0 for wt in wait_types}
    stream_last = {wt: None for wt in wait_types}
    act_events: list = []
    segment_first, segment_last = None, None

    for e in _iter_events(events_path):
        ts = e.get("ts")
        dt = _ev_dt(ts)
        if dt is not None:
            if segment_first is None or dt < segment_first:
                segment_first = dt
            if segment_last is None or dt > segment_last:
                segment_last = dt
        t = e.get("type")
        d = e.get("data") or {}
        if t in stream_rows:
            if in_window(e):
                stream_rows[t] += 1
                if ts and (stream_last[t] is None or ts > stream_last[t]):
                    stream_last[t] = ts
            # The heartbeat fold is deliberately NOT window-filtered (audit-post finding, 2026-08-25):
            # a land INSIDE the window can have begun queueing BEFORE `since`, and filtering its
            # heartbeats out would silently drop its queued mark — under-reporting exactly the days the
            # rule is evaluated on. WINDOW MEMBERSHIP IS THE LAND'S, not the heartbeat's: a fold only
            # ever reaches a numerator through the join below, and that join's day comes from an
            # in-window `land_completed` row. A fold whose land is out of window therefore counts
            # nowhere, so admitting every heartbeat cannot widen the series.
            # T-11831: the key and the value come from the ONE shared reader, so this lens and
            # rule 27 cannot drift on what a wait observation IS. A wait row whose `waited_s` is
            # unusable still counts as a PARK (the `types` set below) and contributes 0 to the peak —
            # exactly as before; the helper additionally refuses a bool, which no emitter writes.
            _obs = journal_mod.land_queue_wait_observation(e)
            key, waited = _obs if _obs is not None else ((e.get("session_ref"), d.get("branch")), 0)
            waited = waited if waited is not None else 0
            f = folds.get(key)
            if f is None:
                # T-11614: `types` records WHICH seams this one land parked at. The fold key is
                # unchanged, so a land parked at both is still ONE queued land — this only remembers
                # which streams it came from, so the per-stream report below is derived, not asserted.
                folds[key] = {"first": dt, "peak": waited, "types": {t}}
            else:
                f["peak"] = max(f["peak"], waited)
                f["types"].add(t)
                if dt is not None and (f["first"] is None or dt < f["first"]):
                    f["first"] = dt
            continue
        if not in_window(e):
            continue
        if t == "land_completed":
            day = (ts or "")[:10]
            if not day:
                continue     # a land whose day cannot be read cannot join a daily denominator
            lands_by_day[day] = lands_by_day.get(day, 0) + 1
            key = (e.get("session_ref"), d.get("branch"))
            land_rows.setdefault(key, []).append((dt, day))
            ms = d.get("admission_wait_ms")
            if isinstance(ms, (int, float)):
                wait_ms_seen += 1
                if ms > 0:
                    wait_ms_nonzero += 1
        elif t in ("task_created", "decision_recorded", "spec_activated", "deviation_captured"):
            blob = json.dumps(d).lower()
            if any(m in blob for m in _ADMISSION_ACT_MARKERS):
                act_events.append({"type": t, "ts": ts, "task_id": e.get("task_id")})

    # JOIN each queue fold to its land, and bucket it by the LAND's day (never the heartbeat's).
    queued_by_day: dict = {}
    peaks_by_day: dict = {}
    # Queued LANDS each stream contributed to (a land parked at both seams counts under BOTH here —
    # this is a per-stream attribution, deliberately NOT a partition, so these do not sum to the
    # numerator and are never used as one). T-11614.
    stream_queued: dict = {wt: 0 for wt in wait_types}
    unmatched = []
    for key, f in folds.items():
        rows = sorted((r for r in land_rows.get(key, []) if r[0] is not None), key=lambda r: r[0])
        match = None
        for r_dt, r_day in rows:
            if f["first"] is None or r_dt >= f["first"]:
                match = r_day          # EARLIEST land at-or-after the fold's first heartbeat
                break
        # NO fallback to an earlier land (audit-post finding): a fold whose first heartbeat is AFTER
        # every land_completed row for this key is post-land queue noise or a wait whose land has not
        # happened yet — joining it backwards to the last earlier land would count it as THAT land's
        # queue and inflate a day that is already closed. It is unmatched, and reported as such.
        if match is None:
            # Under an ACTIVE window a fold with no in-window land is simply out of scope — it is not
            # this window's still-queued land, and reporting it would turn every earlier window's
            # history into "unmatched". Unmatched means: in scope, and no land to join.
            if in_window({"ts": f["first"].isoformat() if f["first"] is not None else None}):
                unmatched.append({"session_ref": key[0], "branch": key[1], "peak_wait_s": f["peak"]})
            continue
        queued_by_day[match] = queued_by_day.get(match, 0) + 1
        peaks_by_day.setdefault(match, []).append(f["peak"])
        for _wt in f.get("types") or ():
            stream_queued[_wt] = stream_queued.get(_wt, 0) + 1

    # THE CALENDAR IS FILLED, not just the days that carry rows (ceiling-consult finding, 2026-08-25).
    # Rule 4 is a run of CONSECUTIVE days, and an unmeasured day must BREAK that run — but a day derived
    # only from the data is ABSENT when nothing landed, and an absent day breaks nothing: two fired days
    # a week apart would sit adjacent in the series and read as a run. So every calendar day in the
    # window is emitted, zero-land days included, each carrying its no_data line. With an ACTIVE window
    # the calendar is the window's own [since, until); with no window it spans the first to the last day
    # the journal actually shows, which is the only honest calendar an all-time reading has.
    def _dstr(x):
        return x.strftime("%Y-%m-%d")

    observed = sorted(set(lands_by_day) | set(queued_by_day))
    cal_lo = cal_hi = None
    if since is not None or until is not None:
        import datetime as _dt
        cal_lo = since.date() if since is not None else (
            _dt.date.fromisoformat(observed[0]) if observed else None)
        if until is not None:
            # `until` is EXCLUSIVE: a window ending at midnight does not include that day; one ending
            # mid-day does (rows before the cut are in-window).
            hi = until.date()
            cal_hi = hi if (until.hour or until.minute or until.second or until.microsecond) \
                else hi - _dt.timedelta(days=1)
        elif observed:
            cal_hi = _dt.date.fromisoformat(observed[-1])
    elif observed:
        import datetime as _dt
        cal_lo = _dt.date.fromisoformat(observed[0])
        cal_hi = _dt.date.fromisoformat(observed[-1])

    if cal_lo is not None and cal_hi is not None and cal_hi >= cal_lo:
        import datetime as _dt
        days, cur = [], cal_lo
        while cur <= cal_hi:
            days.append(_dstr(cur))
            cur += _dt.timedelta(days=1)
        # A row outside the computed calendar (an unparseable-but-present day) is never dropped.
        days = sorted(set(days) | set(observed))
    else:
        days = observed
    series = []
    for day in days:
        lands = lands_by_day.get(day, 0)
        queued = queued_by_day.get(day, 0)
        peaks = sorted(peaks_by_day.get(day, []))
        row = {
            "day": day,
            "lands": lands,
            "queued_lands": queued,
            # null, never 0.0, when the day has no lands — a day nothing landed on is UNMEASURED, not quiet.
            "queued_pct": round(queued / lands * 100, 3) if lands else None,
            # A REAL median (statistics.median averages the two middle values on an even sample) —
            # `peaks[len//2]` is the upper-middle element, which is not the median and reads high.
            "peak_wait_s_median": (statistics.median(peaks) if peaks else None),
            "peak_wait_s_max": (peaks[-1] if peaks else None),
            "fires": (queued / lands * 100 > _ADMISSION_THRESHOLD_PCT) if lands else None,
        }
        if not lands:
            row["no_data"] = ("no-data: no `land_completed` rows on this day — the admission DENOMINATOR "
                              "is absent, so this day is UNMEASURED, not 0%")
        series.append(row)

    # Longest run of CONSECUTIVE fired days (Rule 4 is a run, not a count of fired days anywhere).
    longest, run = 0, 0
    for row in series:
        if row["fires"] is True:
            run += 1
            longest = max(longest, run)
        else:
            run = 0          # an unmeasured day BREAKS the run — it cannot be proven to have fired
    trigger_met = longest >= _ADMISSION_CONSECUTIVE_DAYS
    fired_days = [r["day"] for r in series if r["fires"] is True]

    total_lands = sum(lands_by_day.values())
    result = {
        "lens": "admission-series (T-11047 / SPEC-0132 Rule 4) — the PER-DAY land-queueing series over "
                "the governed seven-day window, folded over BOTH queue-wait seams (the verify-admission "
                "slot and the land-fairness reservation), with the 25% threshold comparison and the "
                "consecutive-day run-length",
        "window": _window_block(since, until),
        "rule": {
            "spec": "SPEC-0132 Rule 4 (Tier-C deferral trigger)",
            "threshold_pct": _ADMISSION_THRESHOLD_PCT,
            "consecutive_days_required": _ADMISSION_CONSECUTIVE_DAYS,
            "text": "verifier queueing blocks > 25% of lands for 7 consecutive days",
        },
        "instrument": {
            # DERIVED from the folded set, never a hard-coded sentence: the label cannot say it read
            # something it did not, nor go stale when the engine's set changes (T-11614, AC2).
            "primary": (", ".join(f"`{wt}`" for wt in wait_types) +
                        " heartbeats (`journal.LAND_QUEUE_WAIT_TYPES`, the SAME set "
                        "`land` reads) folded TOGETHER by (session_ref, branch) to ONE queued land "
                        "carrying its PEAK waited_s across every seam it parked at, then joined to "
                        "that land's `land_completed` row and bucketed by the LAND's UTC day"),
            "streams": [
                {
                    "type": wt,
                    "rows_in_window": stream_rows[wt],
                    "last_row_ts": stream_last[wt],
                    "queued_lands_contributed": stream_queued.get(wt, 0),
                    # Contribution, not merely in-window rows: the fold is deliberately UN-windowed
                    # (a land inside the window may have begun queueing before `since`), so a stream
                    # can reach the series with zero rows in the window. Calling that "absent" would
                    # be the mirror of the error this block exists to stop.
                    "status": "present" if (stream_rows[wt] or stream_queued.get(wt, 0)) else "absent",
                    **({} if (stream_rows[wt] or stream_queued.get(wt, 0)) else {"absent_note": (
                        f"`{wt}` contributed NOTHING to this series — no rows in the window and no "
                        "queued land folded from it. Read the numbers below as measuring the OTHER "
                        "listed stream(s) only: they are NOT evidence that THIS seam was quiet, and "
                        "an emitter that has stopped is indistinguishable here from a seam nothing "
                        "waited at. Check `last_row_ts` and the stream's emit site before concluding "
                        "either.")}),
                }
                for wt in wait_types
            ],
            "streams_note": ("every folded type is listed, contributing or not — a fold over a type "
                             "that produced no rows in the window must not render as a quiet queue "
                             "(T-11614). `queued_lands_contributed` is per-stream ATTRIBUTION, not a "
                             "partition: a land parked at both seams counts under both, so these do "
                             "not sum to `queued_lands`."),
            # A reported FACT, never acted on: with a live emitter, zero rows legitimately means no
            # land waited (a MEASURED quiet queue). Absence of rows cannot prove absence of an
            # emitter — see [[a-presence-count-is-not-a-liveness-probe]] — so this flags the state
            # for a reader and the lens draws no conclusion from it.
            "all_streams_absent": not any(stream_rows[wt] or stream_queued.get(wt, 0)
                                          for wt in wait_types),
            "why_not_admission_wait_ms": "T-11119: `land_completed.data.admission_wait_ms` UNDER-REPORTS "
                                         "(root-cause followup fu_ea1d38d32ef0) — the 0.0s median/p90 "
                                         "reading drawn from it was an artefact of the metric, not a "
                                         "quiet pool. Reported below as a labelled SECONDARY only.",
        },
        "journal_segment_covers": {
            "first_event": segment_first.isoformat() if segment_first is not None else None,
            "last_event": segment_last.isoformat() if segment_last is not None else None,
            "note": "the span the journal FILE holds — a window reaching past `first_event` reads a "
                    "SHORT series, and that is a missing input, not a quiet stretch",
        },
        "series": series,
        "adjudication": {
            "days_in_series": len(series),
            "fired_days": fired_days,
            "longest_consecutive_fired_run": longest,
            "trigger_met": trigger_met,
            "verdict": (f"Rule-4 crossover MET — {longest} consecutive days above "
                        f"{_ADMISSION_THRESHOLD_PCT}%" if trigger_met else
                        f"Rule-4 crossover NOT met — longest consecutive fired run is {longest} day(s), "
                        f"below the required {_ADMISSION_CONSECUTIVE_DAYS}"),
            # FIRED-vs-ACTED: only meaningful once something fired. Reported as an explicit not-applicable
            # rather than an empty list, so "nothing to adjudicate" never reads as "fired and ignored".
            "acted": ({"rule4_act_events": act_events,
                       "reading": ("FIRED and ACTED" if act_events else "FIRED but NOT ACTED — the "
                                   "threshold was crossed and no Tier-C escalation appears in the window")}
                      if trigger_met else
                      {"reading": "not-applicable: the trigger did not fire, so there is nothing to act on"}),
        },
        "secondary_instrument": {
            "field": "land_completed.data.admission_wait_ms",
            "lands_carrying_field": wait_ms_seen,
            "lands_with_nonzero_wait": wait_ms_nonzero,
            "status": "UNDER-REPORTING (T-11119) — shown to keep the divergence from the primary VISIBLE, "
                      "never as the queue series. Do not quote these figures as admission waits.",
        },
    }
    if unmatched:
        # Input completeness, surfaced not swallowed: a queue fold with no land is a land still queued or
        # abandoned. Counting it into a day's numerator would inflate a ratio with work that never landed.
        result["unmatched_queue_folds"] = {
            "count": len(unmatched),
            "folds": unmatched[:20],
            "note": "queue folds with NO matching `land_completed` row — EXCLUDED from every daily "
                    "numerator (still-queued or abandoned lands), reported rather than dropped",
        }
    if not total_lands:
        result["no_data"] = ("no-data: no `land_completed` rows in window — the admission DENOMINATOR is "
                             "ABSENT, so the Rule-4 comparison is UNMEASURED, not a passing 0%. The "
                             "instrument that had nothing to read is `land_completed` (and "
                             + ", ".join(f"`{wt}`" for wt in wait_types) + " for the numerator).")
        result["adjudication"]["trigger_met"] = None
        result["adjudication"]["verdict"] = ("UNMEASURED — no lands in window; the trigger can be neither "
                                             "met nor cleared on absent data")
    result["next"] = ("report-not-block (D-0053): a met crossover is a SIGNAL for the owner-judged Rule-1 "
                      "ladder step, never an automatic escalation — no code auto-escalates (CHARTER §6). "
                      "Pair with `graph query outcome-ratio --since <date>` for the audit-cost side.")
    return result

def _git_read(repo_root, *gitargs) -> "str | None":
    """Read-only `git -C <repo_root> <gitargs>` → stdout (stripped) on exit-0, else None. A pure
    READER (rev-parse / rev-list / merge-base) — never a write. Module-local so the not-adopted lens
    is self-contained + isolatable against a test sandbox repo (the SAME `git -C` shape the test
    sandbox + host `_git_resolve_sha` use; not a new git path — one invocation helper)."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(repo_root), *gitargs],
                           capture_output=True, text=True, check=False)
    except (FileNotFoundError, OSError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()

_LIVE_REVISION_CMD_TIMEOUT = 30   # seconds — bound a kind:command live-revision adapter run (a hung adapter degrades)
_UNSET = object()                 # sentinel: default the live-revision adapter to the module impl (None DISABLES it)


def _default_live_revision_adapter(repo_root) -> "dict | None":
    """The OPTIONAL declared read-only live-revision ADAPTER (T-10521 / SPEC-0093 rule 23 / SPEC-0119
    rule 16). Read `<repo_root>/yitc-ops.yaml` `deploy.live_revision` (OPT-IN / declare-or-waive; precedent:
    the SPEC-0110 L3 freshness adapter shape) and report the ACTUALLY-RUNNING revision, which REPLACES the
    `deploy_completed` proxy as the live baseline in `_view_not_adopted` (X-0376: a bind-mount / container
    recreate ships code with NO deploy_completed, so the proxy proxies live by the last DEPLOY — invisible).

    Returns:
      None                    — the section is ABSENT / WAIVED / names no usable adapter → the proxy is
                                unchanged (the engine kernel has no carrier → never runs this).
      {"revision": "<sha>"}   — the adapter reported the running revision.
      {"error": "<detail>"}   — EVERY failure mode (bad argv, spawn error, timeout, non-zero exit, non-JSON
                                stdout, adapter-reported `error`, missing/empty revision) → a FAIL-CLOSED
                                NAMED degrade so the caller keeps the proxy AND surfaces it (never silent).

    A `kind: command` decl RUNS its declared read-only argv (list form, NO shell, bounded timeout, cwd =
    repo). Mirrors the freshness command-runner discipline (nightly._run_command_freshness_adapter) — its
    OWN contract (a revision, not pipelines), so a small dedicated reader, no import cycle. Never raises."""
    try:
        import yaml as _yaml
    except ImportError:
        return None
    ops_path = Path(repo_root) / "yitc-ops.yaml" if repo_root is not None else None
    if ops_path is None or not ops_path.is_file():
        return None
    try:
        carrier = state.load_ops(ops_path)
    except (OSError, UnicodeDecodeError, _yaml.YAMLError, TypeError):
        return None
    if not isinstance(carrier, dict):
        return None
    deploy = carrier.get("deploy")
    decl = deploy.get("live_revision") if isinstance(deploy, dict) else None
    if not isinstance(decl, dict):
        return None
    # A waive is a deliberate opt-out (declare-or-waive) — not a degrade, not a run.
    if decl.get("waived") is True or decl.get("state") == "waived" or isinstance(decl.get("waiver"), dict):
        return None
    if decl.get("kind") != "command":
        return None   # only the kind:command adapter is defined today; an absent/other kind is not a usable decl
    cmd = decl.get("command")
    if not (isinstance(cmd, list) and cmd and all(isinstance(a, str) for a in cmd)):
        return {"error": "live-revision adapter kind:command but no usable command (non-empty list of str)"}
    import subprocess
    try:
        proc = subprocess.run(cmd, cwd=str(ops_path.parent), capture_output=True, text=True,
                              timeout=_LIVE_REVISION_CMD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"error": f"live-revision adapter command timed out after {_LIVE_REVISION_CMD_TIMEOUT}s"}
    except (OSError, ValueError, TypeError) as e:
        return {"error": f"live-revision adapter command failed to start/run: {e}"}
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:200]
        return {"error": f"live-revision adapter command exited {proc.returncode}: {detail}"}
    try:
        parsed = json.loads(proc.stdout)
    except (ValueError, TypeError) as e:
        return {"error": f"live-revision adapter command stdout not JSON: {e}"}
    if not isinstance(parsed, dict):
        return {"error": "live-revision adapter command stdout is not a {revision} object"}
    if parsed.get("error"):
        return {"error": str(parsed["error"])}   # the adapter ITSELF reported a source failure
    rev = parsed.get("revision")
    if isinstance(rev, str) and rev.strip():
        return {"revision": rev.strip()}
    if "surfaces" in parsed:
        return _normalize_live_revision_surfaces(parsed.get("surfaces"))
    return {"error": "live-revision adapter reported no revision"}


def _normalize_live_revision_surfaces(surfaces) -> dict:
    """T-11751 (X-1142) — normalize the MULTI-SURFACE form of a live-revision adapter's stdout.

    A project that deploys ONE image says `{"revision": "<sha>"}` and nothing here runs (that form is
    untouched, and its whole code path downstream is unchanged — a project that does not need this pays
    nothing). A project whose surfaces advance INDEPENDENTLY (aiseller: a backend and a frontend image,
    the frontend NEWER and already carrying a change the lens counted as debt) could not EXPRESS itself
    at all through a contract of cardinality one: reporting the newest surface under-counts real debt on
    the older one, reporting the oldest counts a live change as debt — unclearable by any action short of
    an unnecessary rebuild. So the adapter may instead say:

        {"surfaces": {"<name>": {"revision": "<sha>", "paths": ["backend/", ...]}, ...}}

    `paths` are the repo-relative path PREFIXES that surface ships (optional; a surface that names none
    owns no path explicitly and is only ever consulted by the fail-closed unowned-path rule in the fold).

    Returns `{"surfaces": {name: {"revision": <sha>, "paths": [<prefix>...]}}}`, or `{"error": <why>}` for
    EVERY malformed shape — the SAME fail-closed NAMED degrade the single-revision failure modes above
    return (T-10521's contract is not relaxed: a broken adapter keeps the proxy and surfaces why, never
    a silent zero). Pure: a dict in, a dict out; never raises."""
    if not isinstance(surfaces, dict) or not surfaces:
        return {"error": "live-revision adapter reported `surfaces` that is not a non-empty mapping of "
                         "<surface> to {revision, paths}"}
    out: dict = {}
    for name, decl in surfaces.items():
        if not isinstance(name, str) or not name.strip():
            return {"error": "live-revision adapter reported a surface with no usable name"}
        if not isinstance(decl, dict):
            return {"error": f"live-revision adapter surface {name!r} is not a {{revision, paths}} mapping"}
        rev = decl.get("revision")
        if not (isinstance(rev, str) and rev.strip()):
            return {"error": f"live-revision adapter surface {name!r} reported no revision"}
        paths = decl.get("paths", [])
        if not isinstance(paths, list) or not all(isinstance(x, str) and x.strip() for x in paths):
            return {"error": f"live-revision adapter surface {name!r} `paths` must be a list of "
                             f"non-empty repo-relative path prefixes"}
        out[name.strip()] = {"revision": rev.strip(), "paths": [x.strip() for x in paths]}
    return {"surfaces": out}


def _surface_owns_path(path: str, paths) -> bool:
    """True iff `path` sits under one of a surface's declared path PREFIXES (T-11751). A prefix matches
    the path itself or anything beneath it (`backend` and `backend/` both own `backend/app/main.py`); a
    bare prefix never matches a sibling that merely starts with the same characters (`back` does NOT own
    `backend/x`). Pure string work — the classifier reuses the touched-path evidence the not-adopted walk
    already reads, adding no new declaration surface."""
    p = (path or "").strip().strip("/")
    for pref in paths or []:
        q = (pref or "").strip().strip("/")
        if not q:
            continue
        if p == q or p.startswith(q + "/"):
            return True
    return False


# ── T-11752 (X-1143): the COUNTER-LOCAL extension to the SPEC-0094 §3 non-runtime allowlist ────────
# The shared allowlist (`task._path_is_non_runtime_surface`) is read by THREE consumers: the live_probe
# close-gate (§3), the deploy build-source gate (§6), and this counter. It names `yitc-ops.yaml` a
# RUNTIME surface DELIBERATELY — a deploy-config change must keep the explicit declare-or-waive at
# close — so the names below are added HERE, on top of the shared base term, and NOT to the shared
# tuple: widening the shared one would silently weaken two gates this card has no scope over.
# The counter's question is the narrower one: "would DEPLOYING this commit change what is running?"
#   • `yitc-ops.yaml` — the ops contract a deploy reads from the CURRENT checkout at deploy time,
#     never from the live revision, so an edit to it is already in effect and carries no undeployed
#     runtime content;
#   • `.yitc-tmp/` — the worktree-local scratch directory workers compose event payloads under;
#   • a ROTATED ARCHIVE SEGMENT — asked of the DEFINER (`events.is_archive_segment`), never re-spelled
#     as a literal (CHARTER §P1 F1). NOT the whole of `archive/`: a segment is `archive/events-*.jsonl`
#     and nothing else, so an unrelated file parked under `archive/` still counts.
# FAIL-CLOSED IS UNTOUCHED in both directions — this adds NAMES to a vocabulary, it does not move the
# default. An unrecognised path still reads deployable; NO path evidence still reads deployable.
_NOT_ADOPTED_ALSO_NON_RUNTIME_FILES = ("yitc-ops.yaml",)
_NOT_ADOPTED_ALSO_NON_RUNTIME_DIRS = (".yitc-tmp/",)


def _path_is_non_runtime_for_counting(path: str) -> bool:
    """True iff a single touched path carries no runtime content FOR THE NOT-ADOPTED COUNTER.

    The SPEC-0094 §3 shared allowlist is the BASE TERM (one answer, not a fork of it); the three
    names above extend it for this reader only (T-11752 / X-1143 — rationale in the block above)."""
    from lib import events as events_mod   # lazy, like the task import below (no import cycle)
    from lib import task as task_mod
    p = (path or "").strip()
    if p.startswith("./"):
        p = p[2:]
    if not p:
        return False
    if task_mod._path_is_non_runtime_surface(p):
        return True
    if p in _NOT_ADOPTED_ALSO_NON_RUNTIME_FILES:
        return True
    if any(p.startswith(d) for d in _NOT_ADOPTED_ALSO_NON_RUNTIME_DIRS):
        return True
    return events_mod.is_archive_segment(p, "events.jsonl")


def _commit_is_deployable(paths) -> bool:
    """True iff a commit's touched-path set carries DEPLOYABLE (runtime) content — the classifier the
    not-adopted counter is scoped by (T-10747 / X-0580 / SPEC-0094 §2).

    REUSES the ONE existing declaration — the SPEC-0094 §3 non-runtime allowlist
    (`task._path_is_non_runtime_surface`: `*.md`, `events.jsonl`, and tasks/ specs/ decisions/ plans/
    ideas/ graph/ patterns/ lessons/ tests/) — as the BASE TERM of `_path_is_non_runtime_for_counting`
    (above), which extends it by THREE counter-local names (T-11752 / X-1143). That same allowlist
    already classifies paperwork for the live_probe close-gate (§3) and the deploy build-source gate
    (§6, `_deploy_ignorable_dirt`), so this THIRD reader keeps ONE answer to "is this deployable?" —
    no new store, no new declaration surface, no second classifier (CHARTER §P1 F1/F2 + §P5); the
    extension is layered ON that answer rather than forking it.

    FAIL-CLOSED TOWARD COUNTING, in both of its directions:
      - ANY touched path outside the allowlist ⇒ deployable (a project whose runtime layout the kernel
        does not recognise keeps today's behaviour — everything counted, never a silent zero);
      - NO path evidence at all (an empty commit; a merge whose first-parent diff is empty) ⇒
        deployable. Absence of evidence that nothing runtime was touched is NOT evidence of absence —
        the same posture `_all_touched_non_runtime_surface` takes on its empty touched set. A MERGE is
        normally classifiable, not blanket-counted: its caller reads merges with
        `--diff-merges=first-parent`, i.e. by what the merge actually brought onto main.
    Imported lazily (the `from lib import debt` idiom in init.py) so views/task stay cycle-free."""
    rows = [p for p in (paths or []) if p and p.strip()]
    if not rows:
        return True   # no path evidence ⇒ counted (fail-closed)
    return not all(_path_is_non_runtime_for_counting(p) for p in rows)


def _view_not_adopted(events_path: "Path | None" = None, project: "str | None" = None,
                      repo_root=None, *, EVENTS_PATH=None, REPO_ROOT=None, _iter_events=None,
                      _live_revision_adapter=_UNSET) -> dict:
    """not-adopted lens (T-9392 / SPEC-0094 §2): the DERIVED "which shipped changes are not yet live"
    surface. Computed at READ time from commit ancestry between the current-live revision (the latest
    `deploy_completed` event's `revision`, SPEC-0094 §1) and `main` HEAD. ZERO new persisted state
    (SPEC-0093 rule 7 / P5) — a saved query, recomputed fresh every run, writes nothing (D-0053 view
    family). Reuses the ONE journal reader (`_iter_events`, Principle 1 — no second parse path) for the
    deploy record + a read-only `git rev-list` for the ancestry; no new store/hook/flag/event.

    The current-live revision = the latest `deploy_completed` event by `ts` (a rollback is itself a
    `deploy_completed`, kind="rollback", so the latest record is always the live one — SPEC-0094 §1).
    An optional `project` filter selects deploy records for that project only. Not-adopted = the
    DEPLOYABLE-PATH commits in `(live, HEAD]` — i.e. shipped (committed to main), not yet covered by a
    deploy, AND carrying runtime content (T-10747 / X-0580 / SPEC-0094 §2). Counting the whole range
    broke the signal in BOTH directions: a pure-governance range read as production debt (a controller
    read 33 and recommended a deploy that would have shipped zero code change), and — worse — a genuine
    undeployed code change was buried inside a permanently-large count. Classification is
    `_commit_is_deployable` (above), which REUSES the SPEC-0094 §3 allowlist rather than declaring a
    second one; the excluded commits are reported as `governance_only` / `governance_only_count`, so
    nothing is silently dropped and every delta is explainable. Statuses below are unchanged:
      - live == HEAD                 → 0 not-adopted (clean; everything shipped is live) — probe (a)
      - live an ANCESTOR of HEAD     → exactly the commits in (live, HEAD] — probe (b)
      - NO deploy_completed on record→ status "no-deploy-recorded"; nothing is known-live, so every
                                       commit reachable from HEAD is not-adopted (the honest read)
      - live SHA not in the repo     → status "live-revision-not-found" (the recorded revision is not in
                                       this checkout's history) — surfaced, never a crash
      - live NOT an ancestor of HEAD → status "live-revision-not-ancestor" (divergent/rolled-back) — the
                                       rev-list is still emitted (commits on HEAD not reachable from live)

    Report-not-block (D-0053): a non-empty surface is a SIGNAL (these shipped changes are not yet
    deployed live), never a gate. Running this lens IS the P8 consumer-read adoption evidence (the
    `cli_invoked` emit on `graph query not-adopted`)."""
    events_path = events_path if events_path is not None else EVENTS_PATH
    repo_root = repo_root if repo_root is not None else REPO_ROOT

    # 1. Current-live revision = the LATEST deploy_completed (by ts), optionally project-filtered.
    live = None
    live_kind = None
    live_ts = None
    live_project = None
    for e in _iter_events(events_path):
        if e.get("type") != "deploy_completed":
            continue
        d = e.get("data") or {}
        if project is not None and d.get("project") != project:
            continue
        ts = e.get("ts") or ""
        if live_ts is None or ts >= live_ts:   # latest by ts (ties → later in file wins; append-order)
            live_ts = ts
            live = d.get("revision")
            live_kind = d.get("kind")
            live_project = d.get("project")

    # The upper bound is MAIN HEAD (SPEC-0094 §2 — "main HEAD"): `main` is the SOLE integration branch
    # (AGENTS §Writes-happen-in-a-worktree), so the not-adopted surface is the shipped-and-INTEGRATED
    # delta — NOT a task/work worktree's un-landed HEAD. Resolve `main` explicitly; fall back to the
    # checkout HEAD only when no `main` ref exists (a fresh sandbox / a repo using another default name),
    # so the lens never crashes on a repo without a literal `main`.
    head_ref = "main"
    head = _git_read(repo_root, "rev-parse", "--verify", "refs/heads/main")
    if head is None:
        head_ref = "HEAD"
        head = _git_read(repo_root, "rev-parse", "--verify", "HEAD")

    def _unscoped_commits(*rev_args: str) -> list:
        # The CHEAP, un-classified walk (the pre-T-10747 read, unchanged): sha + subject only.
        # `git rev-list <range>` newest-first; we emit oldest-first (chronological ship order).
        # %x1f = unit separator (subjects may contain anything).
        # Takes N rev args (T-11751) so the multi-surface UNION range `<head> ^rev1 ^rev2 …` uses the
        # same one walker; the single-range call is byte-identical to before.
        raw = _git_read(repo_root, "rev-list", "--format=%h%x1f%s", "--no-commit-header", *rev_args)
        out = []
        for line in (raw or "").splitlines():
            if not line.strip():
                continue
            short, _, subject = line.partition("\x1f")
            out.append({"sha": short, "subject": subject})
        out.reverse()   # oldest → newest (ship order)
        return out

    def _commits(*rev_args: str, with_paths: bool = False) -> tuple:
        # `git log <range> --name-only` newest-first; we emit oldest-first (chronological ship order)
        # with a short sha + subject per commit, PARTITIONED by the deployable-path classifier
        # (T-10747 / X-0580): returns `(deployable, governance_only)`.
        # ONE git call carries both the commit headers and their touched paths (not N calls): %x1f =
        # unit separator (subjects may contain anything), %x1e = record separator between commits.
        # `--diff-merges=first-parent` is what makes a MERGE classifiable: plain `--name-only` lists
        # NO files for a merge, so every merge would fall to the fail-closed count-it rule — and on a
        # real corpus (boomrocket, 2026-08-06) merges were HALF the surviving count, re-burying the
        # genuine code commits this card exists to surface. First-parent is the honest question here:
        # "what did this commit bring onto main?"
        raw = _git_read(repo_root, "log", "--format=%x1e%h%x1f%s", "--name-only",
                        "--diff-merges=first-parent", *rev_args)
        if raw is None:
            # The path-carrying read FAILED (an older git without `--diff-merges`, or any other git
            # error). Degrade to the un-scoped `rev-list` read and count EVERY commit — the pre-T-10747
            # behaviour. A failed classifier must never present itself as "nothing to deploy": the one
            # unacceptable degrade for this counter is a silent zero.
            return _unscoped_commits(*rev_args), []
        if not raw:
            return [], []
        deployable, governance = [], []
        for record in raw.split("\x1e"):
            if not record.strip():
                continue
            header, _, body = record.partition("\n")
            short, _, subject = header.partition("\x1f")
            if not short.strip():
                continue
            paths = [ln for ln in body.splitlines() if ln.strip()]
            commit = {"sha": short.strip(), "subject": subject}
            if with_paths:
                # T-11751: the touched paths, carried on a private key for the multi-surface fold to
                # classify by OWNERSHIP and then strip — the public commit shape stays {sha, subject}.
                commit["_paths"] = paths
            (deployable if _commit_is_deployable(paths) else governance).append(commit)
        deployable.reverse()    # oldest → newest (ship order)
        governance.reverse()
        return deployable, governance

    # 1b. OPTIONAL declared live-revision adapter (T-10521 / SPEC-0093 rule 23 / SPEC-0119 rule 16). When
    #     the consumer DECLARES `deploy.live_revision` (opt-in), its read-only adapter reports the
    #     ACTUALLY-RUNNING revision, which REPLACES the deploy_completed proxy as the live baseline below —
    #     the reverse-coherence fold reads `live_revision` from THIS view, so it renders the divergence from
    #     the ADAPTER value with no second git walk (P5: ONE live-revision source, ONE ancestry walk). A
    #     bind-mount/container-recreate ships code with NO deploy_completed (X-0376), invisible to the proxy;
    #     the adapter closes that. Report-only, fail-closed to the proxy with a NAMED degrade (never silent):
    #     an adapter that ERRORS keeps the proxy live baseline + surfaces `live_revision_degrade`. OPT-IN via
    #     the declaration ⇒ a repo that does not declare is byte-unchanged (the engine kernel never runs it).
    _adapter = (_default_live_revision_adapter if _live_revision_adapter is _UNSET
                else _live_revision_adapter)
    live_revision_source = "deploy_completed"
    live_revision_degrade = None
    live_surfaces = None       # T-11751: {surface: {revision, paths}} when the adapter reports per-surface
    if _adapter is not None:
        _out = _adapter(repo_root)
        if isinstance(_out, dict):
            if _out.get("error"):
                live_revision_source = "adapter-degraded"
                live_revision_degrade = str(_out["error"])
            elif isinstance(_out.get("revision"), str) and _out["revision"].strip():
                live = _out["revision"].strip()
                live_kind = "adapter"
                live_ts = None
                live_revision_source = "adapter"
            elif "surfaces" in _out:
                # T-11751 (X-1142) — the adapter reports ONE REVISION PER DEPLOYED SURFACE. A project
                # running several images that advance independently has no single live revision, and
                # folding it into one made every commit after the OLDEST surface read as debt regardless
                # of which surface it belongs to (a frontend change that IS live reported as debt,
                # unclearable short of an unnecessary backend rebuild). Each commit is judged below
                # against the surface its PATHS belong to. The scalar `live_revision` below still carries
                # a string for every existing consumer (debt._delivery_result, the reverse line): the
                # MOST-BEHIND surface's revision — the conservative representative.
                # RE-NORMALIZED HERE, not trusted from the caller: the default adapter above already
                # validates its command's stdout, but `_live_revision_adapter` is an INJECTION point, so
                # this branch must hold the fail-closed contract on its own input rather than on its
                # producer's discipline (audit-post finding, T-11751). A malformed shape takes the SAME
                # named degrade every other adapter failure takes — never a crash, never a silent pass.
                _norm = _normalize_live_revision_surfaces(_out["surfaces"])
                if _norm.get("error"):
                    live_revision_source = "adapter-degraded"
                    live_revision_degrade = str(_norm["error"])
                else:
                    live_surfaces = _norm["surfaces"]
                    live_kind = "adapter"
                    live_ts = None
                    live_revision_source = "adapter"

    base = {
        "lens": "not-adopted (SPEC-0094 §2 / T-9392) — shipped changes (committed to main) NOT yet live, "
                "DERIVED at read time from ancestry between the latest deploy_completed revision and HEAD, "
                "SCOPED to commits touching DEPLOYABLE paths (T-10747 / X-0580 — a governance-only commit "
                "carries no production risk, so counting it made the number mean nothing in either "
                "direction). Zero stored state (SPEC-0093 r7 / P5); recomputed fresh.",
        "project_filter": project,
        # T-10747: the deployable-path scoping is REPORTED, never silent — the excluded commits keep
        # their own count + list, so any delta in `not_adopted_count` is always explainable. The
        # branches below override these; the defaults keep one shape across every status.
        "governance_only_count": 0,
        "governance_only": [],
        "path_filter": "deployable-path scoped — a commit counts iff it touches at least one path "
                       "OUTSIDE the SPEC-0094 §3 non-runtime allowlist (the SAME declaration the "
                       "live_probe close-gate and the deploy build-source gate read). Fail-closed: an "
                       "unrecognised path, or a commit with no path evidence, COUNTS. Applies where a "
                       "deploy baseline exists; the no-deploy-recorded branch (whole history, nothing "
                       "known live) stays un-scoped.",
        "live_revision": live,
        "live_kind": live_kind,
        "live_project": live_project,
        # T-10521: the source of `live_revision` — "deploy_completed" (the proxy), "adapter" (a declared
        # live-revision adapter replaced the proxy), or "adapter-degraded" (the adapter errored → proxy
        # retained + `live_revision_degrade` names why). Absent degrade key ⇒ no degrade.
        "live_revision_source": live_revision_source,
        **({"live_revision_degrade": live_revision_degrade} if live_revision_degrade else {}),
        # T-11751: the PER-SURFACE live revisions when the adapter reported them ({surface: {revision,
        # paths}}), with `live_surface` naming the most-behind one the scalar above represents. Absent
        # keys ⇒ the single-revision reading (the whole prior contract, unchanged).
        **({"live_surfaces": {k: v["revision"] for k, v in live_surfaces.items()}} if live_surfaces else {}),
        "head_ref": head_ref,   # "main" (the integration branch, the canonical upper bound) or "HEAD"
                                # (fallback when no `main` ref exists — a fresh sandbox / other default)
        "head": head,
    }

    # 2-surfaces. T-11751 (X-1142) — the MULTI-SURFACE fold: one revision per DEPLOYED SURFACE, each
    # commit judged against the surface its paths belong to. Placed BEFORE the single-revision branches
    # and returning its own `base`, so every branch below is byte-unchanged for a project reporting one
    # revision (the whole prior contract, AC2). Statuses are the SAME four the single read uses,
    # generalized over the surface set; the counting posture is the fail-closed one
    # `_commit_is_deployable` already takes — a path no surface claims is judged against EVERY surface,
    # so an unrecognised runtime layout keeps today's behaviour (counted), never a silent zero.
    if live_surfaces:
        if not head:
            base.update({"status": "no-head", "not_adopted_count": 0, "not_adopted": [],
                         "next": "cannot resolve HEAD — is this a git repository with a commit?"})
            return base
        resolved = {}
        for _name, _decl in live_surfaces.items():
            _full = _git_read(repo_root, "rev-parse", "--verify", f"{_decl['revision']}^{{commit}}")
            if _full is None:
                base.update({
                    "status": "live-revision-not-found",
                    "live_revision": _decl["revision"],
                    "live_surface": _name,
                    "not_adopted_count": None,
                    "not_adopted": [],
                    "next": f"surface {_name!r}'s reported live revision "
                            f"{str(_decl['revision'])[:12]} is not present in this checkout's history — "
                            f"cannot derive ancestry (fetch the revision, or it was force-removed).",
                })
                return base
            resolved[_name] = _full
        if all(v == head for v in resolved.values()):
            base.update({"status": "clean", "not_adopted_count": 0, "not_adopted": [],
                         "live_revision": head, "live_surface": sorted(resolved)[0],
                         "next": "all shipped changes are live on every declared surface "
                                 "(HEAD == each surface's deployed revision)."})
            return base
        # Per-surface membership: the cheap sha-only "what is NOT yet live on THIS surface" set.
        member = {}
        for _name, _full in resolved.items():
            _raw = _git_read(repo_root, "rev-list", "--format=%h", "--no-commit-header", f"{_full}..{head}")
            member[_name] = {ln.strip() for ln in (_raw or "").splitlines() if ln.strip()}
        # ONE path-carrying walk over the UNION range (`<head> ^rev1 ^rev2 …`) — not one per surface
        # (P5: one ancestry walk, the same reader + classifier the single-revision read uses).
        _dep, _gov = _commits(head, *[f"^{v}" for v in resolved.values()], with_paths=True)
        counted = []
        for c in _dep:
            _paths = c.pop("_paths", [])
            owners = [n for n in resolved
                      if any(_surface_owns_path(p, live_surfaces[n].get("paths")) for p in _paths)]
            if not owners:
                owners = list(resolved)   # unowned path ⇒ judged against EVERY surface (fail-closed)
            if any(c["sha"] in member[n] for n in owners):
                counted.append(c)
        for c in _gov:
            c.pop("_paths", None)
        _behind = max(sorted(resolved), key=lambda n: len(member[n]))
        _is_ancestor = all(_git_read(repo_root, "merge-base", "--is-ancestor", v, head) is not None
                           for v in resolved.values())
        base.update({
            "status": "shipped-not-live" if _is_ancestor else "live-revision-not-ancestor",
            "live_revision": resolved[_behind],
            "live_surface": _behind,
            "not_adopted_count": len(counted),
            "not_adopted": counted,
            "governance_only_count": len(_gov),
            "governance_only": _gov,
            "next": ((f"these commits are shipped (on main) but NOT yet live on the surface that ships "
                      f"them — each commit is judged against the declared surface its paths belong to "
                      f"({', '.join(sorted(resolved))}), so a change already live on ITS surface is not "
                      f"counted (T-11751 / X-1142). Deploy the surface(s) concerned."
                      + (f" {len(_gov)} further commit(s) in the range touch ONLY non-runtime paperwork "
                         f"and are excluded (SPEC-0094 §2/§3)." if _gov else "")) if _is_ancestor else
                     "at least one declared surface's live revision is NOT an ancestor of HEAD "
                     "(divergent / rolled-back history); the listed commits are reachable from HEAD but "
                     "not yet live on a surface that ships them — review before deploying."),
        })
        return base

    # 2a. No deploy ever recorded — nothing is known-live; the honest read is "all of HEAD's history
    #     is not-yet-live". (A brand-new project before its first deploy.)
    if live is None:
        # Use the RESOLVED upper bound (`head` = main HEAD when present), NOT a literal "HEAD" — on a
        # task-branch checkout with `main` present the literal would list the branch's local commits
        # instead of main's (audit-post F1, pass 2). Aligns the no-deploy surface with the rest of the
        # lens semantics (the integration branch is the canonical upper bound, SPEC-0094 §2).
        # NOT deployable-path scoped, deliberately (T-10747). This branch means "nothing is known
        # live", so its range is the repo's WHOLE history — scoping it answers no question anyone
        # asks (its count is status-gated OUT of the debt echo and out of the runtime-delivery
        # reading, both of which read `shipped-not-live` only), while a `--name-only` walk of full
        # history is genuinely expensive: on the kernel corpus, 23s and 6MB of git output per call
        # versus 0.6s for this read — paid at every session start and every land tail. So this
        # branch keeps the cheap un-scoped walk, byte-identical to the pre-T-10747 behaviour.
        commits = _unscoped_commits(head) if head else []
        base.update({
            "status": "no-deploy-recorded",
            "not_adopted_count": len(commits),
            "not_adopted": commits,
            "next": "no deploy_completed event on record — nothing is known live. Run `bin/yitc-v2 "
                    "deploy` to ship + record a live revision (SPEC-0094 §1).",
        })
        return base

    if not head:
        base.update({"status": "no-head", "not_adopted_count": 0, "not_adopted": [],
                     "next": "cannot resolve HEAD — is this a git repository with a commit?"})
        return base

    # 2b. Resolve the live SHA in this checkout.
    live_full = _git_read(repo_root, "rev-parse", "--verify", f"{live}^{{commit}}")
    if live_full is None:
        base.update({
            "status": "live-revision-not-found",
            "not_adopted_count": None,
            "not_adopted": [],
            "next": f"the recorded live revision {str(live)[:12]} is not present in this checkout's "
                    f"history — cannot derive ancestry (fetch the revision, or it was force-removed).",
        })
        return base

    # 2c. Clean — live IS HEAD (everything shipped is live). Probe (a).
    if live_full == head:
        base.update({"status": "clean", "not_adopted_count": 0, "not_adopted": [],
                     "next": "all shipped changes are live (HEAD == the deployed revision)."})
        return base

    # 2d. live is an ancestor of HEAD → exactly the commits in (live, HEAD]. Probe (b).
    is_ancestor = _git_read(repo_root, "merge-base", "--is-ancestor", live_full, head) is not None
    commits, governance = _commits(f"{live_full}..{head}")
    base.update({
        "status": "shipped-not-live" if is_ancestor else "live-revision-not-ancestor",
        "not_adopted_count": len(commits),
        "not_adopted": commits,
        "governance_only_count": len(governance),
        "governance_only": governance,
        "next": ((f"these commits are shipped (on main) but NOT yet live — run `bin/yitc-v2 deploy` to "
                  f"make HEAD live (SPEC-0094 §1)."
                  + (f" {len(governance)} further commit(s) in the range touch ONLY non-runtime "
                     f"paperwork and are excluded — they carry no production risk (SPEC-0094 §2/§3)."
                     if governance else "")) if is_ancestor else
                 "the live revision is NOT an ancestor of HEAD (divergent / rolled-back history); the "
                 "listed commits are reachable from HEAD but not from the live revision — review before "
                 "deploying."),
    })
    return base

# T-12076 — THE FIRING MOMENT of a deferred acceptance probe, on the READ side. ONE predicate, and
# it REUSES the followup `armed -> fired` machinery rather than growing a second one: `arrived_ids`
# (the exact-membership union of terminal task ids + terminal coordination ids + observed event
# classes, T-11964) and `event_after_arrived` (the `@after=` anchor comparison, T-12057). A moment
# this predicate can decide is exactly a moment `_probe_moment_declaration` admits at the write door,
# because that door calls `awaits_kind`, which classifies through the same splitter.
#
# THE LEGACY READING IS *DUE*, DELIBERATELY. A key-only deferral (the ~96 recorded before this card)
# names no moment, so "now" is the only truthful reading of it — and DUE is the SAFE direction: it
# stays headlined, visible and settleable, exactly as it was before this change. The alternative
# (defaulting it to pending) would silently empty the headline of the entire existing population,
# which is the disappearance SPEC-0119 rule 3 exists to forbid.
def _deferred_probe_due(moment, today, fire_ids=frozenset(), latest_event_ts=None) -> bool:
    """Is this deferred probe's moment HERE? PURE. No moment recorded -> True (legacy reads DUE)."""
    import datetime as _dt
    from lib import followup as _followup
    if not isinstance(moment, dict) or not moment:
        return True
    if "due_by" in moment:
        v = moment.get("due_by")
        if isinstance(v, _dt.datetime):
            return True                    # time-bearing: undecidable as a date -> the safe direction
        if isinstance(v, _dt.date):
            d = v
        else:
            try:
                d = _dt.date.fromisoformat(str(v).strip())
            except (ValueError, AttributeError):
                return True                # malformed -> DUE, never silently hidden
        # The SAME predicate the observations leg uses for `overdue` (`due < today`), reused verbatim
        # so the two dated carriers can never disagree about what "due" means.
        return d < today
    ref = str(moment.get("awaits") or "").strip()
    if not ref:
        return True
    return ref in fire_ids or _followup.event_after_arrived(ref, latest_event_ts)


# ── SPEC-0200 rule 9 — the consult POSTCHECK fold (T-12181, plan card C4) ────────────────────────
#
# The plan's realization reading, as a saved VIEW rather than a new verb class or a stored metric
# (CHARTER §P1 F2: a view over an existing entity beats a new one; D-0053: store the QUERY, never the
# output). It is READ-ONLY in the strongest sense the family has: it folds the journal, emits no
# event, writes no file and touches no state — a probe asserts the journal is byte-identical after
# the call.
#
# WHY IT READS THE ROWS AND NEVER THE RECORDS (rule 9 / B13). The consult RECORD
# (`decisions/<id>-audit-consult-<key>.yaml`, the `saved_to` path) is REWRITTEN IN PLACE by each
# round, so a fold that read it would see only the last round of each episode and would lose every
# earlier round's R, violations and escapes. The eleven episode fields therefore ride the DURABLE
# journal row, and this fold reads exactly those. The probe deletes every `saved_to` file before
# folding, so «it happened to read the record» cannot pass unnoticed.
#
# HONEST BOUND ON THE DENOMINATOR, STATED RATHER THAN HIDDEN (T-12181 analysis, deviation
# `consult-postcheck-denominator-passes-absent-on-live-audit-rows`). Rule 9 defines the denominator as
# the existing audit completion rows «whose `passes` reached the SPEC-0124 ceiling». Measured on this
# repo 2026-09-06: NO live `external_audit_completed` row carries a `passes` key at all — it lives on
# the saved YAML record only. So over a SYNTHETIC journal (and over any future journal whose emit
# carries the field) the denominator is exact, and over TODAY's real journal the ceilinged-row leg
# contributes nothing. That is reported in the output (`denominator.ceilinged_rows_seen` plus a
# `bound` line when it is zero) instead of reading as a healthy empty result. Adding the emit is the
# LIVE-EMISSION axis, which is card C3's (T-12182) and out of C4's scope by construction.

#: Rule 9 — an episode ENDS at one of these outcomes (the rule-4 terminal set, plus the ordinary
#: PROCEED). `hold` and `malformed` are mid-episode: a group whose last episode sits on one has not
#: finished, and folds `open`.
_CONSULT_ENDING_OUTCOMES = ("proceed", "owner-held", "terminal")

#: The plan FSM terminals rule 7 names as a plan target's own exit (a plan has no park / wont-do).
_CONSULT_PLAN_TERMINALS = frozenset({"rejected", "cancelled"})

#: The four shares. Named once so the summation invariant and the per-model split cannot disagree.
_CONSULT_SHARE_KEYS = ("proceed_share", "terminal_share", "owner_held_share", "open_share")


def _consult_episode_parts(episode_id):
    """Split rule 1's `<target>/<stage|gate>/<attempt n>` into `(group_key, n)`.

    The GROUP is the episode id minus its attempt ordinal — i.e. `(target, stage|gate)`, which is the
    unit the shares are computed over. Grouping by EPISODE instead is the named failing input: a
    target that was reopened once would then count twice, and a group that converged on its second
    episode would still carry its first episode's owner-held as if it were a separate subject."""
    if not isinstance(episode_id, str) or "/" not in episode_id:
        return (str(episode_id), 0)
    head, tail = episode_id.rsplit("/", 1)
    return (head, int(tail)) if tail.isdigit() else (episode_id, 0)


def _consult_owner_route_complete(group_key, outcome_n, episode_ns, *, _find_task_yaml, _read_yaml,
                                  _plan_status) -> bool:
    """Rule 9 / B10 — is an ENDED `terminal` / `owner-held` group's OWNER ROUTE complete?

    Read from the TARGET's OWN durable state, using EXISTING carriers only (no new field): a TASK is
    disposed when its card is `parked` WITH a `return_trigger` naming the carrier, or `wont-do`, or
    already closed, or a LATER episode was opened; a PLAN has no park and no `wont-do`, so it is
    disposed by a later episode on the gate or by its own FSM terminal (rule 7).

    An ended-but-UNDISPOSED group folds `open`, not `terminal` — which is the whole point of B10: a
    card that hit the ceiling, ended on an owner HOLD and was then simply left alone is UNRESOLVED
    work, and counting it as `terminal` would let the postcheck read a stalled fleet as a finished
    one."""
    if any(n > outcome_n for n in episode_ns):
        return True
    target = group_key.rsplit("/", 1)[0] if "/" in group_key else group_key
    path = _find_task_yaml(target) if _find_task_yaml else None
    if path is not None:
        card = _read_yaml(path)
        card = card if isinstance(card, dict) else {}
        status = card.get("status")
        if card.get("closed_at") or status in ("wont-do", "done"):
            return True
        return status == "parked" and bool(card.get("return_trigger"))
    status = _plan_status(target) if _plan_status else None
    return status in _CONSULT_PLAN_TERMINALS


def _consult_target_closed(group_key, *, _find_task_yaml, _read_yaml, _plan_status) -> bool:
    """Rule 9 / C4.4 — is this group's TARGET closed on its own durable state?

    A task carrying `closed_at`, or a plan at an FSM terminal. The fold DERIVES `terminal_reason:
    target-closed` from this; no round ever emits it, because a round cannot know that the card it is
    judging will later close. Without the derivation a closure-ended episode would fold `open`
    forever — an unfinishable debt that no owner action can ever clear."""
    target = group_key.rsplit("/", 1)[0] if "/" in group_key else group_key
    path = _find_task_yaml(target) if _find_task_yaml else None
    if path is not None:
        card = _read_yaml(path)
        return bool(isinstance(card, dict) and card.get("closed_at"))
    return (_plan_status(target) if _plan_status else None) in _CONSULT_PLAN_TERMINALS


def _consult_shares(groups: dict) -> dict:
    """The four shares over a group→outcome map, as exact fractions plus their float reading.

    They SUM TO 1 by construction rather than by care: every group is assigned exactly one of the
    four outcomes, so the numerators partition the denominator. `null` on an empty denominator —
    never a fabricated 0.0 (the T-0358 no-fabricated-zero convention this family holds)."""
    denom = len(groups)
    counts = {"proceed": 0, "terminal": 0, "owner-held": 0, "open": 0}
    for outcome in groups.values():
        counts[outcome] = counts.get(outcome, 0) + 1
    key_of = {"proceed_share": "proceed", "terminal_share": "terminal",
              "owner_held_share": "owner-held", "open_share": "open"}
    out = {"groups": denom}
    for share, outcome in key_of.items():
        n = counts[outcome]
        out[share] = {"n": n, "of": denom,
                      "fraction": f"{n}/{denom}" if denom else None,
                      "value": round(n / denom, 6) if denom else None}
    out["shares_sum_to_1"] = (sum(counts[key_of[s]] for s in _CONSULT_SHARE_KEYS) == denom) if denom else None
    return out


def _consult_r_stats(values: list) -> dict:
    """Per-episode R: count, `median_low` and max.

    `statistics.median_low` EVERYWHERE in this contract (rule 9 / the plan): an even count must never
    yield a half value. R is a count of auditor RETESTS — «1.5 retests» is not a reading anyone can
    act on, and a plain `median` produces exactly that on an even set."""
    vals = sorted(int(v) for v in values)
    return {"episodes": len(vals),
            "median_low": statistics.median_low(vals) if vals else None,
            "max": max(vals) if vals else None,
            "values": vals}


def _view_consult_postcheck(events_path: "Path", since=None, until=None, *,
                            _iter_events=None, _ev_dt=None, _read_yaml=None,
                            _find_task_yaml=None, _plan_status=None, ceiling=2,
                            _group_by_episode=False) -> dict:
    """consult-postcheck lens (T-12181 / SPEC-0200 rule 9): the plan's realization fold over the
    ceiling-consult EPISODES — per-episode R, the four per-group outcome shares, the contract-violation
    kinds and the completeness-failure total, rendered again split by auditor model.

    Journal-derived, recomputed fresh, READ-ONLY: no event, no write, no stored state (D-0053). The
    window semantics are the family's shared pair (`_window_predicate` / `_window_block`), never a
    second dialect. Reads through the INJECTED `_iter_events`, which folds the SEGMENT SET (SPEC-0190
    rule 4), so an archived segment is part of the reading rather than invisible to it.

    `_group_by_episode` exists ONLY for the differential probe: it is the NAMED FAILING INPUT (grouping
    by episode instead of by `(target, stage)`), kept here so the tripwire exercises THIS function
    rather than a re-implementation of it that could drift away from what ships. It is never reachable
    from the CLI — `_run_view` never passes it."""
    in_window = _window_predicate(since, until, _ev_dt=_ev_dt)
    rounds: list = []
    ceilinged: set = set()
    pending_model: dict = {}
    for e in _iter_events(events_path):
        etype = e.get("type")
        if etype not in ("audit_prompt_sent", "external_audit_completed"):
            continue
        if not in_window(e):
            continue
        data = e.get("data")
        if not isinstance(data, dict):
            continue
        stage = data.get("stage")
        key = (data.get("target_id"), stage)
        if etype == "audit_prompt_sent":
            # The prompt row IMMEDIATELY precedes its completion row on every emit path, so pairing
            # by (target, stage) in row order is the join — and POPPING it is what keeps the pairing
            # honest: a completion with no prompt of its own takes no model rather than inheriting a
            # stale one from an earlier round.
            pending_model[key] = data.get("model")
            continue
        model = pending_model.pop(key, None)
        episode_id = data.get("episode_id")
        if not episode_id:
            # Not an episode row. It is still a DENOMINATOR candidate when it is a non-consult audit
            # (stage pre / post / a plan gate) whose `passes` reached the SPEC-0124 ceiling — rule 9's
            # left-join input, so a key that hit the ceiling and consulted NOTHING never leaves the
            # denominator (R2.3, the worst case).
            passes = data.get("passes")
            if (isinstance(stage, str) and not stage.startswith("consult-")
                    and isinstance(passes, int) and not isinstance(passes, bool)
                    and passes >= ceiling and data.get("target_id")):
                ceilinged.add(f"{data['target_id']}/{stage}")
            continue
        group, n = _consult_episode_parts(episode_id)
        if _group_by_episode:
            group, n = str(episode_id), 0
        rounds.append({
            "episode_id": episode_id, "group": group, "n": n,
            "round_kind": data.get("round_kind"),
            "outcome": data.get("outcome"),
            "terminal_reason": data.get("terminal_reason"),
            "non_admissible": data.get("non_admissible"),
            "contract_violations": data.get("contract_violations") or [],
            "completeness_failures_delta": data.get("completeness_failures_delta") or 0,
            "model": model,
        })

    # ── episodes ──────────────────────────────────────────────────────────────────────────────
    episodes: dict = {}
    for r in rounds:
        ep = episodes.setdefault(r["episode_id"], {"group": r["group"], "n": r["n"], "rounds": []})
        ep["rounds"].append(r)
    for ep in episodes.values():
        # R counts rounds of kind `retest` ONLY, malformed or not — rule 4's reading rule, which
        # every surface of this contract states identically. Read from the ROWS, never from a
        # rewritable `saved_to` record.
        ep["r"] = sum(1 for r in ep["rounds"] if r["round_kind"] == "retest")
        ending = [r for r in ep["rounds"] if r["outcome"] in _CONSULT_ENDING_OUTCOMES]
        ep["outcome"] = ending[-1]["outcome"] if ending else None
        ep["terminal_reason"] = ending[-1]["terminal_reason"] if ending else None
        ep["model"] = next((r["model"] for r in reversed(ep["rounds"]) if r["model"]), None)

    # ── groups: the denominator is the UNION of the ceilinged keys and the consulted groups ──────
    # The LEFT JOIN rule 9 specifies keeps a ceilinged-but-unconsulted key IN; taking the union keeps
    # a consulted group in as well, which is the same fail-safe direction (a consult only happens
    # AFTER a ceiling, so an episode is itself evidence of one). Neither leg can shrink the reading.
    group_names = set(ceilinged) | {ep["group"] for ep in episodes.values()}
    by_group: dict = {}
    for eid, ep in episodes.items():
        by_group.setdefault(ep["group"], []).append((ep["n"], eid, ep))

    outcomes: dict = {}
    details: dict = {}
    for group in sorted(group_names):
        members = sorted(by_group.get(group, []))
        if not members:
            outcomes[group] = "open"          # ceilinged, never consulted (R2.3)
            details[group] = {"episodes": 0, "reason": "ceilinged key with no consult row"}
            continue
        n, eid, last = members[-1]
        ns = [m[0] for m in members]
        outcome, reason = last["outcome"], last["terminal_reason"]
        if outcome is None:
            # The last episode has not ended. It folds `open` UNLESS the target itself closed, in
            # which case rule 9 / C4.4 derives the terminal — never emitted by a round.
            if _consult_target_closed(group, _find_task_yaml=_find_task_yaml,
                                      _read_yaml=_read_yaml, _plan_status=_plan_status):
                outcome, reason = "terminal", "target-closed"
            else:
                outcomes[group] = "open"
                details[group] = {"episodes": len(members), "last_episode": eid,
                                  "reason": "last episode still open at the window end"}
                continue
        if outcome in ("terminal", "owner-held") and reason != "target-closed":
            if not _consult_owner_route_complete(group, n, ns, _find_task_yaml=_find_task_yaml,
                                                 _read_yaml=_read_yaml, _plan_status=_plan_status):
                outcomes[group] = "open"
                details[group] = {"episodes": len(members), "last_episode": eid,
                                  "ended": outcome, "terminal_reason": reason,
                                  "reason": "ended with NO owner disposition on record (B10)"}
                continue
        outcomes[group] = outcome
        details[group] = {"episodes": len(members), "last_episode": eid, "ended": outcome,
                          "terminal_reason": reason, "model": last["model"]}

    # ── the rows' own quality measurements (B13) — never from a `saved_to` file ──────────────────
    kinds: dict = {}
    escapes = 0
    for r in rounds:
        escapes += int(r["completeness_failures_delta"] or 0)
        for v in r["contract_violations"] or ():
            k = v.get("kind") if isinstance(v, dict) else None
            key = k if k is not None else "(none)"
            kinds[key] = kinds.get(key, 0) + 1

    # ── the SAME fold, split by auditor model (plan owner ask 2026-09-06) ────────────────────────
    models: dict = {}
    for group, outcome in outcomes.items():
        model = (details[group] or {}).get("model")
        if model is None:
            members = sorted(by_group.get(group, []))
            model = members[-1][2]["model"] if members else None
        models.setdefault(model or "(unknown)", {"groups": {}, "r": []})["groups"][group] = outcome
    for eid, ep in episodes.items():
        models.setdefault(ep["model"] or "(unknown)", {"groups": {}, "r": []})["r"].append(ep["r"])

    result = {
        "lens": "consult-postcheck (SPEC-0200 rule 9 / T-12181) — the ceiling-consult EPISODE fold: "
                "per-episode R, the four per-group outcome shares, the contract-violation kinds and "
                "the completeness-failure total, split again by auditor model",
        "window": _window_block(since, until),
        "invariant": "GROUPED BY (target, stage|gate) — the episode id minus its attempt ordinal — "
                     "NEVER by episode: a reopened target would otherwise count twice. R counts "
                     "rounds of kind `retest` ONLY, malformed or not (SPEC-0200 rule 4's one "
                     "definition). Every number here is read from the JOURNAL ROWS; the `saved_to` "
                     "consult record is rewritten in place each round and is provenance only (B13). "
                     "median_low everywhere — an even count never yields a half retest.",
        "denominator": {
            "groups": len(group_names),
            "ceilinged_rows_seen": len(ceilinged),
            "consulted_groups": len(by_group),
            "rule": "the ceilinged audit keys (non-consult rows whose `passes` reached the "
                    f"SPEC-0124 ceiling of {ceiling}) LEFT-JOINED with the consult episodes — a "
                    "ceilinged key with NO consult row folds `open` and never leaves the "
                    "denominator (R2.3, the worst case).",
        },
        "episode_r": _consult_r_stats([ep["r"] for ep in episodes.values()]),
        "outcome_shares": _consult_shares(outcomes),
        "groups": {g: details[g] for g in sorted(details)},
        "contract_violation_kinds": dict(sorted(kinds.items())),
        "completeness_failures": escapes,
        "by_model": {m: {"outcome_shares": _consult_shares(v["groups"]),
                         "episode_r": _consult_r_stats(v["r"])}
                     for m, v in sorted(models.items())},
    }
    if not ceilinged:
        # HONEST BOUND, stated rather than left to read as health (see this block's header). A zero
        # here is a MISSING INSTRUMENT, not a clean fleet — the T-0358 no-fabricated-zero discipline
        # applied to a denominator leg instead of to a ratio.
        result["denominator"]["bound"] = (
            "NO ceilinged audit row was found: no live `external_audit_completed` row carries a "
            "`passes` key today (measured 2026-09-06 — `passes` lives on the saved YAML record "
            "only), so this leg of the denominator contributes nothing until an emit site adds the "
            "field. The consulted groups below are still exact. Deviation: "
            "`consult-postcheck-denominator-passes-absent-on-live-audit-rows`; the live-emission "
            "axis is card C3 (T-12182), not this lens.")
    result["next"] = ("report-not-block (D-0053): a low `proceed_share` or a non-zero "
                      "`completeness_failures` is a SIGNAL for the plan's postcheck reading, never a "
                      "gate. Nothing here is emitted or stored — re-run it for a current answer.")
    return result


def _view_overdue_recheck(today=None, *, TASKS_DIR=None, _read_yaml=None,
                          _terminal_cross_ids=None, _seen_event_types=None,
                          _latest_event_ts=None) -> dict:
    """overdue-recheck lens (T-9394 / SPEC-0094 §3): the DERIVED "which user-facing `none` waivers are
    PAST their recheck_by date" surface — the overdue-`recheck_by` revisit path raised at the weekly
    Review sweep (QUEUE.md §Re-review triggers). A user-facing `none` waiver is a DATED non-adoption
    debt (SPEC-0094 §3 P3 honesty floor): the change is closed but NOT proven live, and STAYS visible
    until its `recheck_by` falls due. When that date passes the debt is OVERDUE — unresolved, owed a
    real per-change live_probe at the deploy seam.

    DERIVED, NEVER a stored status field (SPEC-0093 rule 7 / P5): zero new persisted state, no new
    event / command / store. Computed fresh at read time from the CARRIER of the waiver — the task
    YAML's `live_probe` field (the same field the close-gate authored, T-9391) — paired with today's
    date. Reuses the ONE task reader (`_read_yaml`, Principle 1), adding only one more saved-view lens
    of the established shape (the displacement-retention / not-adopted precedent). It is the task-local
    companion of the commit-ancestry not-adopted surface (T-9392): not-adopted answers "what shipped
    isn't live", this answers "which declared-non-adoption debts have now fallen due".

    A waiver is OVERDUE iff: `live_probe` is a waiver (`none` present) AND it is user-facing
    (`user_facing` absent defaults TRUE — the same fail-closed read as the close-gate, SPEC-0094 §3)
    AND `recheck_by` is a valid ISO date that is STRICTLY BEFORE `today`. Report-not-block (D-0053): a
    non-empty surface is a SIGNAL for the weekly sweep, never a gate. Running this lens IS the P8
    consumer-read adoption evidence (the `cli_invoked` emit on `graph query overdue-recheck`)."""
    import datetime as _dt
    # T-10750 — the settled-waiver predicate has ONE home (lib.task, beside the grammar it validates).
    # Imported function-locally, matching this file's existing local-import style and keeping the
    # module import graph unchanged.
    from lib.task import (_live_probe_settled_grammar_error, _live_probe_waiver_settled,
                          _live_probe_attested_grammar_error, _live_probe_attested_result,
                          _live_probe_settled_terminal)
    today = today if today is not None else _dt.date.today()
    if isinstance(today, str):
        today = _dt.date.fromisoformat(today.strip())

    def _as_date(v):
        """Parse a recheck_by value (ISO string OR a YAML-native date) → date, else None. Rejects a
        datetime (time-bearing) the same way the close-gate grammar does (T-9391 _is_iso_date)."""
        if isinstance(v, _dt.datetime):
            return None
        if isinstance(v, _dt.date):
            return v
        if isinstance(v, str):
            try:
                return _dt.date.fromisoformat(v.strip())
            except ValueError:
                return None
        return None

    overdue = []
    # T-11748 (X-1163) — THE TWO HONEST TERMINALS OF A WAIVER, each on its OWN counted set, exactly as
    # T-11657 gave the acceptance-probe carrier below. They are collected here and reported on their
    # own keys, so `overdue` / `overdue_count` keep their EXACT prior meaning: what is left there is
    # what someone can still act on. Kept SEPARATE from each other for the same reason the probe leg
    # keeps them separate — `unreachable` says a proof can NEVER arrive (a permanent floor; the remedy,
    # if any, is an authoring or instrumentation fix, never work on this card), `falsified` says a
    # reading ARRIVED and came back negative (a real finding someone may need to act on).
    unreachable_waivers = []
    falsified_waivers = []
    if TASKS_DIR is not None and TASKS_DIR.exists():
        for p in sorted(TASKS_DIR.glob("T-*.yaml")):
            d = _read_yaml(p)
            if not isinstance(d, dict):
                continue
            lp = d.get("live_probe")
            if not isinstance(lp, dict):
                continue
            # T-11674 (X-1130) — the ATTESTED leg. A card declaring a live proof the PROJECT runs
            # (SPEC-0094 §4b) carries the SAME dated debt as a waiver until its reading is recorded,
            # and this lens is the surface that reading has to reach. THREE states, and the middle one
            # is the whole point of the card:
            #   * `passing`  → DISCHARGED. The declared proof ran and passed; the row leaves the lens,
            #                  exactly as a grammar-valid `settled_by` does.
            #   * `failing`  → LISTED UNCONDITIONALLY, marked `failing`, with NO date test at all. A
            #                  recorded negative is not a discharge and it is not a pending item either:
            #                  time is irrelevant to a known failure, so gating its visibility on
            #                  `recheck_by` would let a real failure sit invisible until a date passed.
            #                  This is the property that stops bad news being filed as no data.
            #   * ungraded   → the ordinary dated-debt shape, identical to the waiver leg below.
            # A MALFORMED attested declaration is NAMED rather than silently skipped, the same fix
            # T-11673 made for a near-miss `settled_by` — an author debugging a rejected field by hand
            # is the friction that change measured.
            if "attested" in lp:
                _att_error = _live_probe_attested_grammar_error(lp)
                _att_result = _live_probe_attested_result(lp)
                if _att_result == "passing" and _att_error is None:
                    continue
                if lp.get("user_facing", True) is not True and _att_result != "failing":
                    continue
                _oc = lp.get("outcome") if isinstance(lp.get("outcome"), dict) else {}
                if _att_result == "failing":
                    row = {
                        "task": d.get("id") or p.stem,
                        "recheck_by": (lp.get("recheck_by").isoformat()
                                       if isinstance(lp.get("recheck_by"), _dt.date)
                                       and not isinstance(lp.get("recheck_by"), _dt.datetime)
                                       else lp.get("recheck_by")),
                        "days_overdue": 0,
                        "reason": (f"attested proof {lp.get('attested')!r} (run at "
                                   f"{lp.get('runs_at')!r}) reported FAILING"
                                   + (f": {_oc.get('detail')}" if _oc.get("detail") else "")),
                        "status": d.get("status"),
                        "state": "failing",
                        "attested": lp.get("attested"),
                        "probed_at": _oc.get("probed_at"),
                        "evidence": _oc.get("evidence"),
                    }
                    if _att_error is not None:
                        row["settle_error"] = _att_error
                    overdue.append(row)
                    continue
                rb = _as_date(lp.get("recheck_by"))
                if rb is None or rb >= today:
                    continue
                row = {
                    "task": d.get("id") or p.stem,
                    "recheck_by": rb.isoformat(),
                    "days_overdue": (today - rb).days,
                    "reason": (f"attested proof {lp.get('attested')!r} (run at "
                               f"{lp.get('runs_at')!r}) declared but NOT yet graded — record it with "
                               f"`liveprobe --report pass|fail`"),
                    "status": d.get("status"),
                    "state": "ungraded",
                    "attested": lp.get("attested"),
                }
                if _att_error is not None:
                    row["settle_error"] = _att_error
                overdue.append(row)
                continue
            if "none" not in lp:
                continue
            if lp.get("user_facing", True) is not True:   # explicit user_facing: false → no recheck debt
                continue
            # T-10750 (X-0575) — a SETTLED waiver is DISCHARGED debt, not deferred debt: it names the
            # probe run that proved it (`settled_by`), so it leaves this lens without the dishonest
            # re-date the card exists to retire. ONE predicate home in `lib.task` (CHARTER §P5) so the
            # lens and the close-gate can never drift. Read-time and PURE: the lens sees only that the
            # marker is WELL-FORMED — the close-gate is what proves the locator RESOLVES, and it is the
            # only door into the landed corpus this lens reads, so an unresolvable settle never lands.
            # T-11673 (X-1127) — a PRESENT-but-MALFORMED `settled_by` is NAMED, not silently ignored.
            # `_live_probe_waiver_settled` is a BOOLEAN over the grammar below, so a near-miss shape
            # (aiseller: `probed_at` not an ISO date) read EXACTLY like an absent one: the row kept its
            # ordinary overdue shape and the author got zero feedback, having to bisect the field by
            # hand — on a 108-item sweep, a debugging session per item. The grammar ALREADY computes the
            # field + expected shape one call down, so this names it instead of adding a validator.
            # WHAT DOES NOT CHANGE — the safe failure direction: the malformed branch does NOT
            # `continue`, so the only exit from this lens is still a grammar-CLEAN `settled_by`.
            _settle_error = (_live_probe_settled_grammar_error(lp)
                             if lp.get("settled_by") is not None else None)
            if lp.get("settled_by") is not None and _settle_error is None:
                # T-11748 — a GRAMMAR-VALID discharge leaves the actionable set either way, but the two
                # kinds are not the same news: a proof discharge is PAID and vanishes (unchanged), a
                # TERMINAL is recorded on its own floor set with the reason it was discharged with. A
                # MALFORMED settle never reaches here (the `and` above), so a terminal missing its
                # reason keeps its ordinary overdue row — the safe direction, unchanged.
                _terminal = _live_probe_settled_terminal(lp)
                if _terminal is not None:
                    (unreachable_waivers if _terminal == "unreachable" else falsified_waivers).append({
                        "task": d.get("id") or p.stem,
                        "waiver": lp.get("none"),
                        # NAME THE REASON, never just the count — the reason IS the record for a
                        # terminal (an empty one is refused at the discharge AND by the grammar, so its
                        # absence here means a hand-edited card and is reported as absent, not guessed).
                        "reason": str((lp.get("settled_by") or {}).get("reason") or "").strip()
                                  or "(no reason recorded)",
                        "recheck_by": (lp.get("recheck_by").isoformat()
                                       if isinstance(lp.get("recheck_by"), _dt.date)
                                       and not isinstance(lp.get("recheck_by"), _dt.datetime)
                                       else lp.get("recheck_by")),
                        "status": d.get("status"),
                    })
                continue
            rb = _as_date(lp.get("recheck_by"))
            if rb is None or rb >= today:                 # absent/invalid or not yet due → not overdue
                continue
            row = {
                "task": d.get("id") or p.stem,
                "recheck_by": rb.isoformat(),
                "days_overdue": (today - rb).days,
                "reason": lp.get("none"),
                "status": d.get("status"),
            }
            if _settle_error is not None:
                row["settle_error"] = _settle_error
            overdue.append(row)
    # Sort oldest-debt-first; a `failing` row has no meaningful date, so it sorts FIRST — a
    # recorded negative outranks every dated pending item (T-11674).
    overdue.sort(key=lambda r: ("" if r.get("state") == "failing" else (r.get("recheck_by") or "")))
    malformed_settles = [r for r in overdue if r.get("settle_error")]
    for _wb in (unreachable_waivers, falsified_waivers):     # T-11748 — oldest-dated debt first
        _wb.sort(key=lambda r: (str(r.get("recheck_by") or ""), r["task"]))

    # T-10916 (SPEC-0036 / X-0710) — the SECOND dated-deferred-proof CARRIER folded by this SAME lens: a
    # `post_ship_observation` declaration, the trust anchor of the Stage-8 --post-ship-observation
    # carve-out. Structurally the identical debt to the waiver above (a closed-but-not-proven change,
    # carried by a task-YAML field, dated, discharged only by naming where the proof landed), so it
    # EXTENDS this lens instead of adding a parallel one (CHARTER §P1 F1/F2) — same reader, same
    # zero-stored-state derivation, same report-not-block posture.
    #
    # TWO deliberate differences from the waiver leg, both in service of "an overlay that defers a proof
    # without naming where the proof lands is how deferred adoption turns into never-adopted":
    #   (1) an unsettled observation is listed from the MOMENT it is declared, not only once its window
    #       closes — the deferral is visible for its whole life, so a reader can see what is owed while it
    #       is still owed. `state` distinguishes `pending` (window still open) from `overdue` (due date
    #       passed, the reading is now owed).
    #   (2) NOTHING but `settled_by` discharges it. Time passing moves it pending → overdue; it never
    #       removes it. The only exit is naming where the recorded observation landed.
    # The waiver keys (`overdue` / `overdue_count`) keep their EXACT prior meaning — this leg reports on
    # its own keys, so no existing consumer of this lens changes shape.
    from lib.task import (_post_ship_observation_declaration_error, _post_ship_observation_settled,
                          _post_ship_observation_settled_terminal)
    observations = []
    deferred = []
    # T-11950 — the SAME two terminals a third carrier over, on the shape T-11657 (probes) and T-11748
    # (waivers) already established: TWO SEPARATE counted sets, never merged with each other and never
    # folded into the actionable `observations_*` counts, because the two ask for DIFFERENT remedies —
    # `unreachable` is a permanent floor whose remedy is an AUTHORING fix for the next card, `falsified`
    # is a real finding someone may need to act on. This is the half that makes the terminal ADOPTABLE:
    # a discharge the view still counted as work owed would not be a discharge at all.
    unreachable_observations = []
    falsified_observations = []
    # T-11657 — the two HONEST NON-PASS TERMINALS a deferred probe can now reach. They ride this SAME
    # single pass for the same reason leg (b) does (a third glob+parse over ~2.7k cards buys nothing),
    # and they are collected into TWO SEPARATE sets rather than one merged non-pass set BECAUSE THE
    # TWO ASK FOR DIFFERENT REMEDIES: `unreachable` is an AUTHORING defect (the criterion should never
    # have been written that way — T-11656 / SPEC-0060), `falsified` is a REAL FINDING someone may need
    # to act on. A reader who cannot see at a glance how much of the floor is proof-can-never-arrive
    # versus proof-came-back-negative learns the wrong thing about the population.
    unreachable = []
    falsified = []
    _terminal_task_ids: set = set()      # T-12076 — filled by the pass below, read by the fire set
    if TASKS_DIR is not None and TASKS_DIR.exists():
        for p in sorted(TASKS_DIR.glob("T-*.yaml")):
            d = _read_yaml(p)
            if not isinstance(d, dict):
                continue
            # T-11408 leg (b) rides this SAME pass rather than opening a third glob+parse over
            # `tasks/` — at ~2.7k cards a third read-every-card sweep cost this lens ~50% more wall
            # clock for a card set it had already parsed. Each leg keeps its own independent block
            # (no shared `continue`), so neither can silently skip the other.
            # T-12076 — the terminal-task corpus for the fire predicate, collected in the glob pass
            # this lens ALREADY makes (no new read on a hot surface). It is the SAME terminal-status
            # set `followup`'s host injects as `terminal_ids`, derived here from the cards themselves
            # so that an `awaits T-NNNN` moment resolves with ZERO injection — which is what keeps the
            # lens answerable in a bare fixture and in every existing caller (the cross/event halves
            # arrive only when a host has already folded them).
            if str(d.get("status") or "").strip() in ("done", "wont-do"):
                _terminal_task_ids.add(str(d.get("id") or p.stem))
            probes = d.get("probes")
            if isinstance(probes, dict):
                acs = sorted(k for k, v in probes.items() if str(v or "").strip() == "deferred")
                if acs:
                    _moments = d.get("probe_moments")
                    _moments = _moments if isinstance(_moments, dict) else {}
                    deferred.append({
                        "task": d.get("id") or p.stem,
                        "probes": acs,
                        "count": len(acs),
                        "status": d.get("status"),
                        "closed_at": d.get("closed_at"),
                        # T-12076 — the recorded moments travel with the row, so a reader of the lens
                        # sees WHY a probe is due or pending without re-opening the card. The DUE/
                        # PENDING split itself is applied after the pass (the fire set is complete
                        # only once every card has been read).
                        "moments": {k: _moments.get(k) for k in acs if _moments.get(k)},
                    })
                # T-11657 — the two terminals, each on its OWN set. This is NOT a silent decrement:
                # a settled terminal leaves the PENDING set BY CONSTRUCTION (its recorded value is no
                # longer `deferred`, and the discharge stays keyed on the value the settle itself
                # writes — never a parallel marker), and what leaves the pending line ARRIVES here on
                # its own named, counted line. An implementation that simply stopped counting them
                # would satisfy the settle path and fail exactly here.
                _settlements = d.get("probe_settlements")
                _settlements = _settlements if isinstance(_settlements, dict) else {}
                for _terminal, _bucket in (("unreachable", unreachable), ("falsified", falsified)):
                    _hit = sorted(k for k, v in probes.items()
                                  if str(v or "").strip() == _terminal)
                    if not _hit:
                        continue
                    _bucket.append({
                        "task": d.get("id") or p.stem,
                        # NAME THE REASON, never just the count — the reason IS the record for a
                        # terminal (an empty one is refused at the settle, so a missing reason here
                        # means a hand-edited card, and it is reported as absent rather than guessed).
                        "probes": [{"ac": k,
                                    "reason": str((_settlements.get(k) or {}).get("reason") or "").strip()
                                              or "(no reason recorded)"}
                                   for k in _hit],
                        "count": len(_hit),
                        "status": d.get("status"),
                        "closed_at": d.get("closed_at"),
                    })
            pso = d.get("post_ship_observation")
            if not isinstance(pso, dict):
                continue
            if _post_ship_observation_declaration_error(pso) is not None:
                continue           # malformed → the guard refuses it at the overlay; the lens never guesses
            if _post_ship_observation_settled(pso):
                # RECORDED — the debt is discharged. A LOCATOR discharge leaves the lens entirely (the
                # reading landed and is cited); a TERMINAL discharge is NOT a silent decrement — what
                # leaves the pending line ARRIVES here on its own named, counted line, carrying the
                # mandatory reason that IS the record. An implementation that merely stopped counting
                # a terminal would satisfy the settle path and fail exactly here.
                _terminal = _post_ship_observation_settled_terminal(pso)
                if _terminal:
                    _due = _as_date(pso.get("due_by"))
                    (unreachable_observations if _terminal == "unreachable"
                     else falsified_observations).append({
                        "task": d.get("id") or p.stem,
                        "observation": str(pso.get("observation") or "").strip(),
                        "due_by": _due.isoformat() if _due else pso.get("due_by"),
                        # NAME THE REASON, never just the count — an empty one is refused at the
                        # settle, so a missing reason here means a hand-edited card and is reported
                        # as absent rather than guessed (the T-11657 rendering rule).
                        "reason": str((pso.get("settled_by") or {}).get("reason") or "").strip()
                                  or "(no reason recorded)",
                        "status": d.get("status"),
                     })
                continue
            due = _as_date(pso.get("due_by"))
            if due is None:
                continue           # unreachable for a grammar-valid declaration; tolerant by construction
            observations.append({
                "task": d.get("id") or p.stem,
                "observation": str(pso.get("observation") or "").strip(),
                "due_by": due.isoformat(),
                "state": "overdue" if due < today else "pending",
                "days_overdue": max(0, (today - due).days),
                "status": d.get("status"),
            })
    observations.sort(key=lambda r: r["due_by"])   # nearest/oldest due first
    for _b in (unreachable_observations, falsified_observations):
        _b.sort(key=lambda r: (str(r.get("due_by") or ""), r["task"]))     # oldest due first, as above
    observations_overdue = [r for r in observations if r["state"] == "overdue"]

    # T-11408 leg (b) (SPEC-0119 rule 3 / kupiclub X-1066) — the THIRD deferred-proof CARRIER folded by
    # this SAME lens: an acceptance probe DEFERRED at closure (`probes: {ACx: deferred}`). The state is
    # first-class and its settle exists (`task close --settle-probe`, T-11107, fail-closed against a
    # probe that was never deferred) — what was missing is the RETURN: `bin/lib/debt.py` contains zero
    # occurrences of `defer` and no session-start echo clause named one, so kupiclub T-0466 closed with
    # both its probes deferred and nothing but the card remembered. That is the shipped-but-not-adopted
    # shape the methodology exists to prevent, arriving through the one door left open — an HONEST
    # deferral — and the incentive ran the wrong way: the more scrupulous the worker, the quieter the
    # disappearance (an overclaim gets caught by the auditor; a correct deferral got silence).
    #
    # It EXTENDS this lens rather than adding a parallel one (CHARTER §P1 F1/F2) for the same reason the
    # observations leg did: same debt (a closed change whose proof is owed), same reader, same
    # zero-stored-state derivation, same report-not-block posture. Its own keys, so no existing consumer
    # of this lens changes shape.
    #
    # THREE deliberate properties:
    #   (1) UNDATED, so it is listed from the moment the deferral is recorded — unlike the two legs
    #       above, a deferred probe carries no due date at all, which is precisely why it could go quiet
    #       forever. There is no `pending`/`overdue` split to make.
    #   (2) NOTHING but the SETTLE discharges it. `task close --settle-probe` flips the recorded value
    #       `deferred → pass` and records `probe_settlements`, so the discharge is keyed on the value the
    #       settle itself writes — never on a parallel marker that could drift from it.
    #   (3) It reports, never gates. Deferring stays the honest move and stays cheap: nothing here
    #       changes what may be deferred, and nothing gates closing with a deferral.
    # (collected in the observations pass above — one read per card, not two.)
    deferred.sort(key=lambda r: (str(r.get("closed_at") or ""), r["task"]))   # oldest deferral first
    deferred_probe_count = sum(r["count"] for r in deferred)
    # T-12076 — THE DUE / PENDING SPLIT, applied once the whole card set has been read (the fire set
    # is complete only then). The pre-existing `deferred_probes` / `_count` /
    # `deferred_probe_criteria_count` keys keep their EXACT prior meaning — the WHOLE deferred set —
    # so no existing consumer of this lens changes shape; the split arrives on its own keys, which is
    # the same own-keys discipline every leg of this lens has followed since T-10916.
    from lib import followup as followup_mod   # function-local: the lazy-import contract (T-11320)
    _fire_ids = followup_mod.arrived_ids(_terminal_task_ids,
                                         frozenset(_terminal_cross_ids or ()),
                                         tuple(_seen_event_types or ()))
    for _row in deferred:
        _m = _row.get("moments") or {}
        _row["due_probes"] = [k for k in _row["probes"]
                              if _deferred_probe_due(_m.get(k), today, _fire_ids, _latest_event_ts)]
        _row["pending_probes"] = [k for k in _row["probes"] if k not in _row["due_probes"]]
    deferred_due = [r for r in deferred if r["due_probes"]]
    deferred_pending = [r for r in deferred if r["pending_probes"]]
    deferred_probe_due_count = sum(len(r["due_probes"]) for r in deferred)
    deferred_probe_pending_count = sum(len(r["pending_probes"]) for r in deferred)
    for _b in (unreachable, falsified):
        _b.sort(key=lambda r: (str(r.get("closed_at") or ""), r["task"]))     # oldest first, as above
    unreachable_probe_count = sum(r["count"] for r in unreachable)
    falsified_probe_count = sum(r["count"] for r in falsified)

    return {
        # T-11748 (X-1163) — the WAIVER's two terminals, as TWO SEPARATE counted sets, on the same
        # shape and bounds T-11657 settled for the acceptance probes below. Deliberately NOT folded
        # into `overdue_count` (which means "still actionable"), not merged with each other, and not
        # merged with the probe sets: a waiver terminal and a probe terminal are different carriers.
        "unreachable_waivers": unreachable_waivers,
        "unreachable_waivers_count": len(unreachable_waivers),
        "unreachable_waivers_note": (
            "live_probe WAIVERS discharged UNREACHABLE (T-11748 / X-1163) — the differential can NEVER "
            "be read: it needs a WRITE against production, or data that does not exist there. Each "
            "carries the mandatory free-text reason it was discharged with. This is a PERMANENT FLOOR, "
            "not a backlog: nothing anyone does moves it, which is why it is not folded into the "
            "actionable overdue count. It NEVER satisfies CHARTER Principle 8 adoption evidence."
            if unreachable_waivers else
            "no live_probe waiver is discharged unreachable — no permanent-floor waiver debt."),
        "falsified_waivers": falsified_waivers,
        "falsified_waivers_count": len(falsified_waivers),
        "falsified_waivers_note": (
            "live_probe WAIVERS discharged FALSIFIED (T-11748 / X-1163) — the reading ARRIVED and came "
            "back NEGATIVE, each carrying the mandatory free-text reason. Read these: unlike an "
            "unreachable one, a falsified waiver is a REAL FINDING about a shipped change that someone "
            "may need to act on. It is the OPPOSITE of adoption evidence, not a weaker form of it, so "
            "it never satisfies CHARTER Principle 8."
            if falsified_waivers else
            "no live_probe waiver is discharged falsified — no negative-reading waiver debt."),
        # T-11657 — the two terminals, as TWO SEPARATE counted sets. Deliberately NOT folded into
        # `deferred_probes*` (which means "still owed") nor into each other: three states, three
        # remedies. Own keys, so no existing consumer of this lens changes shape.
        "unreachable_probes": unreachable,
        "unreachable_probes_count": len(unreachable),
        "unreachable_probe_criteria_count": unreachable_probe_count,
        "unreachable_probes_note": (
            "acceptance probes discharged UNREACHABLE (T-11657) — a proof that can NEVER arrive, each "
            "carrying the mandatory free-text reason it was settled with. This is the PERMANENT FLOOR "
            "the pending count used to hide: it is not a backlog and nothing anyone does will move it. "
            "The remedy is an AUTHORING fix for the next card, not work on this one (T-11656 / "
            "SPEC-0060 — e.g. a criterion whose evidence lives in a consumer repository was "
            "mis-authored, the scope boundary already forbids it). It NEVER satisfies CHARTER "
            "Principle 8 adoption evidence."
            if unreachable else
            "no acceptance probe is discharged unreachable — no permanent-floor debt."),
        "falsified_probes": falsified,
        "falsified_probes_count": len(falsified),
        "falsified_probe_criteria_count": falsified_probe_count,
        "falsified_probes_note": (
            "acceptance probes discharged FALSIFIED (T-11657) — the reading ARRIVED and came back "
            "NEGATIVE, each carrying the mandatory free-text reason it was settled with. Read these: "
            "unlike an unreachable one, a falsified criterion is a REAL FINDING about a shipped change "
            "and someone may need to act on it. It is the OPPOSITE of adoption evidence, not a weaker "
            "form of it, so it never satisfies CHARTER Principle 8."
            if falsified else
            "no acceptance probe is discharged falsified — no negative-reading debt."),
        "deferred_probes": deferred,
        "deferred_probes_count": len(deferred),
        "deferred_probe_criteria_count": deferred_probe_count,
        # T-12076 — the DUE / PENDING split, on its OWN keys. `due` = the moment has arrived (its
        # `due_by` is past, or its awaited artifact fired) or the deferral names NO moment at all (the
        # legacy population, which can only truthfully read as due now). `pending` = a moment is
        # recorded and has not arrived. The two are counted at BOTH altitudes — cards and criteria —
        # because the echo headlines cards carrying criteria, exactly as the un-split line always did.
        "deferred_probes_due": deferred_due,
        "deferred_probes_due_count": len(deferred_due),
        "deferred_probe_criteria_due_count": deferred_probe_due_count,
        "deferred_probes_pending": deferred_pending,
        "deferred_probes_pending_count": len(deferred_pending),
        "deferred_probe_criteria_pending_count": deferred_probe_pending_count,
        "deferred_probes_moment_note": (
            "a deferred probe carries its FIRING MOMENT beside `probes:` in `probe_moments` "
            "(T-12076): `{ACx: {due_by: <ISO date>}}` or `{ACx: {awaits: <T-NNNN|X-NNNN|"
            "events.jsonl#type=<t>[@after=<ISO ts>]>}}`. DUE is decided by the SAME predicate the "
            "followup `armed -> fired` fold uses (`followup.arrived_ids` / `event_after_arrived`), "
            "never a second one. A LEGACY key-only deferral reads DUE — it names no moment, so `now` "
            "is the only truthful reading, and DUE is the safe direction: it stays visible."),
        "deferred_probes_note": (
            "acceptance probes DEFERRED at closure and not yet SETTLED (T-11408 / SPEC-0119 rule 3 / "
            "X-1066) — each is a proof the card itself recorded as owed. Settle one with `bin/yitc-v2 "
            "task close <T-XXXX> --settle-probe <AC>:pass --settle-evidence <locator>` (T-11107), which "
            "is the ONLY thing that clears it — time passing never does. Report-only: deferring stays "
            "the honest move, and nothing here gates a close."
            if deferred else
            "no acceptance probe is deferred-and-unsettled — no deferred-probe debt."),
        # T-11950 — the OBSERVATION's two terminals, as TWO SEPARATE counted sets on the same shape
        # and bounds T-11657 settled for the acceptance probes and T-11748 for the waivers.
        # Deliberately NOT folded into `observations_count` / `observations_overdue_count` (which mean
        # "still owed"), not merged with each other, and not merged with the probe or waiver sets: a
        # discharged observation, a discharged probe and a discharged waiver are three carriers.
        "unreachable_observations": unreachable_observations,
        "unreachable_observations_count": len(unreachable_observations),
        "unreachable_observations_note": (
            "post-ship observations discharged UNREACHABLE (T-11950) — the declared reading can NEVER "
            "arrive: its specimen is gone with an empty live cohort, its baseline was never recorded, "
            "or the mechanism it would attribute to is pre-empted. Each carries the mandatory "
            "free-text reason it was discharged with. This is a PERMANENT FLOOR, not a backlog: "
            "nothing anyone does moves it, which is why it is not folded into the actionable "
            "observation counts. The remedy is an AUTHORING fix for the next card (T-11656 / "
            "SPEC-0060), not work on this one. It NEVER satisfies CHARTER Principle 8 adoption "
            "evidence."
            if unreachable_observations else
            "no post-ship observation is discharged unreachable — no permanent-floor observation debt."),
        "falsified_observations": falsified_observations,
        "falsified_observations_count": len(falsified_observations),
        "falsified_observations_note": (
            "post-ship observations discharged FALSIFIED (T-11950) — the reading ARRIVED and came back "
            "NEGATIVE, each carrying the mandatory free-text reason. Read these: unlike an unreachable "
            "one, a falsified observation is a REAL FINDING about a shipped change that someone may "
            "need to act on. It is the OPPOSITE of adoption evidence, not a weaker form of it, so it "
            "never satisfies CHARTER Principle 8."
            if falsified_observations else
            "no post-ship observation is discharged falsified — no negative-reading observation debt."),
        "observations": observations,
        "observations_count": len(observations),
        "observations_overdue_count": len(observations_overdue),
        "observations_note": (
            "post-ship observations DECLARED but not yet RECORDED (T-10916 / SPEC-0036 §POST-SHIP "
            "OBSERVATION) — each is an acceptance proof a Stage-8 audit-post deferred under the "
            "--post-ship-observation carve-out. `pending` = the observation window is still open; "
            "`overdue` = its due_by passed and the reading is now owed. Take the reading, record it, "
            "then settle the card with `bin/yitc-v2 task close <T-XXXX> --settle-observation "
            "<locator>` (T-11529) — a `settled_by` locator naming where the recorded observation "
            "landed clears one, and time passing never does. When the reading can NEVER arrive, or "
            "arrived NEGATIVE, discharge it terminally instead: `--settle-observation "
            "unreachable|falsified --settle-reason <why>` (T-11950) — it lands on its own counted set "
            "below and never satisfies CHARTER Principle 8."
            if observations else
            "no post-ship observation is awaiting its reading — no deferred-observation debt."),
        "lens": "overdue-recheck (SPEC-0094 §3 / T-9394) — user-facing `none` waivers PAST their "
                "recheck_by date: dated non-adoption debts now fallen due, owed a real live_probe at "
                "the deploy seam — PLUS (T-11674, SPEC-0094 §4b) the ATTESTED project-run proofs: an "
                "UNGRADED one carries the same dated debt, and one whose reading came back FAILING is "
                "listed UNCONDITIONALLY (`state: failing`, no date test) because a recorded negative "
                "is neither a discharge nor a pending item — PLUS (T-10916) the post-ship OBSERVATIONS declared but not yet "
                "recorded (see `observations`) — PLUS (T-11408) the acceptance probes DEFERRED at "
                "closure and not yet settled (see `deferred_probes`) — PLUS (T-11657) the two HONEST "
                "NON-PASS TERMINALS a deferred probe can now reach, each on its OWN counted set: "
                "`unreachable_probes` (a proof that can never arrive — a permanent floor, remedied by "
                "an authoring fix, never by work on the card) and `falsified_probes` (a reading that "
                "arrived and came back negative — a real finding). Neither is folded into the pending "
                "count, and they are never merged with each other. PLUS (T-11748 / X-1163) THE SAME "
                "TWO TERMINALS one carrier over, for the WAIVER itself: `unreachable_waivers` and "
                "`falsified_waivers`, each on its own counted set, neither folded into the actionable "
                "`overdue` count nor merged with the probe sets — a waiver whose differential needs a "
                "WRITE, or data absent from prod, can never be settled by proof and would otherwise "
                "only be re-datable forever. PLUS (T-11950) THOSE SAME TWO TERMINALS a THIRD carrier "
                "over, for the post-ship OBSERVATION: `unreachable_observations` and "
                "`falsified_observations`, each on its own counted set, neither folded into the "
                "actionable observation counts nor merged with the probe or waiver sets — an "
                "observation whose specimen is gone, or whose baseline was never recorded, could "
                "otherwise only sit on this lens forever. All three of the first group are deferred-proof "
                "debts; the first two are dated, the third is not, which is why it could go quiet "
                "forever. DERIVED at read time from the task-YAML live_probe / post_ship_observation / "
                "probes carriers + today; "
                "zero stored state (SPEC-0093 r7 / P5). Recomputed fresh.",
        "today": today.isoformat(),
        "overdue_count": len(overdue),
        "overdue": overdue,
        # T-11673 (X-1127) — the malformed settles counted on their OWN key, so the defect is stated by
        # the surface rather than left for a reader to spot in a per-row field. It is a SUBSET of
        # `overdue` (never a separate set), so `overdue_count` keeps its exact prior meaning.
        "malformed_settle_count": len(malformed_settles),
        "malformed_settle_note": (
            "these rows carry a `settled_by` that is PRESENT but MALFORMED — each names its own field "
            "and the expected shape in `settle_error` (T-11673 / X-1127). The debt is NOT discharged "
            "and the row stays here, which is the safe direction; what the named error buys is that the "
            "author does not have to bisect the field to find out why. Fix the named field — or write "
            "it through `bin/yitc-v2 task update --live-probe-settled-evidence/-probed-at/-method` "
            "(T-11413), which refuses a malformed shape at authoring time."
            if malformed_settles else
            "no waiver carries a malformed `settled_by` — every present settle marker is grammar-valid."),
        "next": ("these closed-but-not-proven-live changes are OVERDUE recheck — run their per-change "
                 "`live_probe` against prod at the deploy seam (SPEC-0094 §4); each remains on the "
                 "not-adopted surface until it passes."
                 + (f" {len(malformed_settles)} of them carry a MALFORMED `settled_by` / attested "
                    f"declaration — see each row's `settle_error` for the field and the expected shape "
                    f"(T-11673 / T-11674)."
                    if malformed_settles else "")
                 + (f" {len([r for r in overdue if r.get('state') == 'failing'])} of them are RECORDED "
                    f"FAILING attested proofs (`state: failing`) — these are not stale rechecks, they "
                    f"are live negative readings: fix the product or the proof, then record a new "
                    f"reading on a new card (T-11674)."
                    if any(r.get("state") == "failing" for r in overdue) else "")
                 if overdue else
                 "no user-facing `none` waiver is past its recheck_by date — no overdue revisit debt."),
    }


def _declared_subject(entry, cadence: dict):
    """Resolve a CONSUMER-declared inspection theme entry (SPEC-0093 rule 12) to the `(subject, tier,
    days)` triple the review-due semaphore needs, or None when it cannot be resolved HONESTLY — a
    slug-less entry, an absent/mistyped `cadence:` tier, or a tier with no `<tier>_days` value in the
    parsed cadence block. Tolerant by construction (T-10238 audit-pre): it never raises on a malformed
    carrier, and an unresolvable entry is SKIPPED rather than guessed — the never-nag-on-unknown
    guarantee has to hold for a missing key exactly as it does for an unrecognized tier."""
    if not isinstance(entry, dict):
        return None
    subject = str(entry.get("theme") or "").strip()
    tier = str(entry.get("cadence") or "").strip()
    if not subject or not tier:
        return None
    days = (cadence or {}).get(f"{tier}_days")
    if not isinstance(days, int):
        return None
    return (subject, tier, days)


def _parsed_journal_lines(events_path):
    """The lens's own default journal read — the pre-T-11453 loop, verbatim, kept so that a caller
    which injects no fold behaves byte-identically."""
    for line in journal_mod.segment_lines(events_path):  # T-11444: segment-aware fold (SPEC-0190 r4)
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _view_review_due(now=None, *, EVENTS_PATH=None, cadence=None, themes=(),
                     declared_themes=(), declared_cadence=None, _segment_rows=None) -> dict:
    """review-due lens (T-10134): the DERIVED, ACTIVITY-GATED "which periodic reviews are now DUE"
    surface — the review-axis companion of the overdue-recheck lens. A review SUBJECT is DUE iff it is
    past its cadence AND substantive work happened since its last run; a quiet period (no work) is NEVER
    due (the owner's no-work->no-nag guarantee). Zero stored state — re-derived every call from the
    `inspection_completed` anchors + the journal's substantive events (CHARTER §P5 / SPEC-0119 discipline).

    SUBJECTS: the WEEKLY operational-hygiene tier (anchored by `inspect record --tier weekly`, cadence
    `weekly_days`) + each T1-T10 system-inspection THEME (anchored by `inspect record --theme T<n>`,
    cadence `monthly_days`) + each CONSUMER-DECLARED theme (`declared_themes` — the project's own
    `yitc-ops.yaml inspection.themes[]` entries, SPEC-0093 rule 12 / SPEC-0057 §9 relationship (iii),
    anchored by the SAME `inspect record --theme <slug>` event; T-10238). A declared theme honors ITS
    OWN `cadence: weekly|monthly|quarterly` tier, resolved to `<tier>_days` — never one uniform monthly.
    PER-SUBJECT coverage (audit fix #1 — a recently-run sibling can NEVER hide a stale/never-run subject;
    NOT a tier-max). Cadence VALUES come from the injected `cadence` dict, which the host parses from the
    roster's `<!--CADENCE-->` block (inspection.parse_cadence) — the CLI holds NO cadence literal (AC3);
    `declared_cadence` (defaulting to `cadence`) is the day-value source for the DECLARED themes, so a
    `-C` consumer with no roster of its own can still resolve them from the engine's roster WITHOUT
    thereby surfacing the engine's own kernel subjects. Resolution is PER-SUBJECT: a subject whose
    day-value is missing/unparseable is skipped, not guessed (never nags on unknown).

    NO-DATA runs do NOT anchor (SPEC-0173 rule 1, T-10837): an `inspection_completed` carrying the
    contract's no-data discriminator is skipped entirely, so an aborted / crashed / unstarted run
    leaves its subject exactly as due as it was. A record without the field is a completed run.

    UNCOUNTED runs do NOT anchor either (T-12063, X-1262): a run carrying `semaphore_counted: false`
    — today, a declared sweep theme whose `surfaces:` glob matched ZERO FILES — is skipped on the same
    terms, so a theme that inspects nothing stays DUE instead of reading reviewed. The two skips share
    ONE reader (`inspection.counts_for_semaphore`), and it reads an ABSENT field as counted, so rows
    written before the field existed are never retro-graded into never-reviewed. When any row is
    skipped for this cause the `next:` line SAYS so — suppressed when clean, like every other line
    here (SPEC-0119 rule 3).

    SUBSTANTIVE event = HEAVY work only — {task_closed, land_completed, spec_activated, plan_stage_entered}
    — NOT followups / deviation_captured / reads (the no-work->no-nag gate). `now` defaults to UTC now.
    Report-only (D-0053): it NEVER runs, schedules, or gates an inspection — surfacing due-ness is not
    running one (SPEC-0057 §2 manual-first UNCHANGED). Returns counts only (token-frugal — SPEC-0119)."""
    import datetime as _dt
    SUBSTANTIVE = {"task_closed", "land_completed", "spec_activated", "plan_stage_entered"}

    def _ts(v):
        if not isinstance(v, str):
            return None
        try:
            return _dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None

    now = now if now is not None else _dt.datetime.now(_dt.timezone.utc)
    cadence = cadence or {}
    declared_cadence = declared_cadence if declared_cadence else cadence
    weekly_days = cadence.get("weekly_days")
    monthly_days = cadence.get("monthly_days")
    # No parseable cadence for ANY subject → cannot honestly judge due-ness → suppress (never nag on
    # unknown). The check is PER-SUBJECT below (a declared theme resolves its own tier from
    # `declared_cadence`), so this early return fires only when NOTHING is resolvable at all.
    if (not isinstance(weekly_days, int) and not isinstance(monthly_days, int)
            and all(_declared_subject(e, declared_cadence) is None for e in declared_themes)):
        return {"count": 0, "weekly_due": False, "themes_due": [],
                "next": "no parseable cadence block in the roster — review-due suppressed."}

    last_by_subject: dict = {}          # subject -> latest inspection_completed ts
    substantive_ts: list = []
    uncounted_seen = False              # did any run get skipped for semaphore standing? (T-12063)
    if EVENTS_PATH is not None and EVENTS_PATH.exists():
        # T-11453 — `_segment_rows` is the OPTIONAL injected journal fold, so inside the debt echo's
        # request scope this lens shares the ONE parse its ~14 sibling readers share instead of
        # re-reading the same 176 MB itself. It arrives by INJECTION beside `EVENTS_PATH`, the way
        # every host-coupled input reaches this module. Default None ⇒ the read below,
        # byte-identical for every other caller of the lens.
        #
        # T-11596 — IT MUST BE THE SEGMENT-AWARE FOLD (`journal.segment_rows`), and the parameter is
        # NAMED for it. This lens judges over 30-day (monthly themes) and 90-day (quarterly declared
        # themes) horizons — 4x to 13x the 7-day live window — so SPEC-0190 rule 4 puts it squarely in
        # the archive branch. The default read below was migrated at T-11444; the INJECTION was not,
        # and an injected `journal.fold_rows` silently OVERRODE that already-correct default on the
        # one path the real surface takes. The consequence was in the direction that costs trust: each
        # subject is anchored on its LATEST `inspection_completed` row, so a theme reviewed three weeks
        # ago read as NEVER RUN and the surface nagged to redo it — a false accusation of staleness,
        # which teaches the reader to skim the whole surface
        # (`lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate`). The activity gate
        # could not save it either: the substantive-work scan folds the same truncated history.
        # The old name is not kept as an alias deliberately — `_fold_rows` is a member of the
        # single-file-primitive set the SPEC-0165 tripwire detects injection sites by
        # (tests/test_raw_journal_reader_sweep.py), so a leaf still declaring that name would keep
        # advertising a live-only reader while being handed a segment-aware one.
        # The memo collapse T-11453 bought is PRESERVED: `segment_rows` folds each segment THROUGH
        # `fold_rows`, so a caller inside `journal.rows_memo` still gets the shared parse.
        for e in (_segment_rows(EVENTS_PATH) if _segment_rows is not None
                  else _parsed_journal_lines(EVENTS_PATH)):
            if not isinstance(e, dict):
                continue
            et = e.get("type")
            if et == "inspection_completed":
                d = e.get("data") or {}
                # T-10837 (SPEC-0173 rule 1): a run that produced NO VERDICT never anchors the clock.
                # This fold keys on the LATEST timestamp alone, so before this the mere EXISTENCE of
                # an aborted run marked its subject reviewed and reset its cadence — a no-data run was
                # not merely LIKE a clean one here, it was indistinguishable in principle (P2-run-2).
                # An event with NO such field is a completed run (inspection.is_no_data reads absence
                # as not-no-data), so every record written before the field existed folds unchanged.
                if inspection.is_no_data(d):
                    continue
                # T-12063 (X-1262): a run that swept ZERO FILES never anchors either. A declared
                # theme whose `surfaces:` glob matches nothing records a real, well-formed
                # `inspection_completed` carrying matched 0 / surfaces_bytes 0 — so before this it
                # re-anchored the clock on every run and the subject read REVIEWED while nothing was
                # ever inspected. Read through the discriminator's own reader, which treats an ABSENT
                # field as a counted run, so every row written before the field existed folds
                # unchanged.
                if not inspection.counts_for_semaphore(d):
                    uncounted_seen = True
                    continue
                subject = d.get("tier") or d.get("theme")   # weekly-tier run OR a T<n> theme run
                ts = _ts(e.get("ts"))
                if subject and ts is not None:
                    prev = last_by_subject.get(subject)
                    if prev is None or ts > prev:
                        last_by_subject[subject] = ts
            elif et in SUBSTANTIVE:
                ts = _ts(e.get("ts"))
                if ts is not None:
                    substantive_ts.append(ts)
    substantive_ts.sort()
    oldest_work = substantive_ts[0] if substantive_ts else None

    def _due(subject, cadence_days):
        """DUE = past-cadence AND >=1 substantive event since last run. never-run => due once there has
        been unreviewed work for at least one cadence period (bootstrap). Returns (due, age_days|None)."""
        last = last_by_subject.get(subject)
        if last is None:                                    # never reviewed
            if oldest_work is None:
                return (False, None)                        # no work at all → nothing to review
            aged = (now - oldest_work).days >= cadence_days
            return (aged, None)
        worked_since = any(ts > last for ts in substantive_ts)
        aged = (now - last).days >= cadence_days
        return (aged and worked_since, (now - last).days)

    # PER-SUBJECT cadence resolution (T-10238): each subject is judged only against ITS OWN parseable
    # day-value; an unresolvable one is skipped, never folded onto a neighbour's cadence.
    weekly_due, weekly_age = (_due("weekly", weekly_days) if isinstance(weekly_days, int)
                              else (False, None))
    themes_due = []
    if isinstance(monthly_days, int):
        for th in themes:                       # the kernel roster T1-T10 — monthly by construction
            d, age = _due(th, monthly_days)
            if d:
                themes_due.append({"subject": th, "age_days": age, "cadence": "monthly"})
    for entry in declared_themes:               # the consumer's own declared themes — each at ITS tier
        resolved = _declared_subject(entry, declared_cadence)
        if resolved is None:
            continue
        subject, tier, days = resolved
        d, age = _due(subject, days)
        if d:
            themes_due.append({"subject": subject, "age_days": age, "cadence": tier})
    # oldest theme first (largest age; never-run (age None) sorts last but is still surfaced by count)
    themes_due.sort(key=lambda r: (r["age_days"] is not None, r["age_days"] or 0), reverse=True)
    count = (1 if weekly_due else 0) + len(themes_due)
    return {
        "count": count,
        "weekly_due": weekly_due,
        "weekly_age_days": weekly_age,
        "themes_due": themes_due,
        "next": ("run the due review(s) then record via `bin/yitc-v2 inspect record --tier weekly` / "
                 "`--theme T<n>` (activity-gated — surfaced only because work happened since the last run)."
                 if count else "no review is past its cadence with unreviewed work — nothing due.")
                + (" NOTE: a recorded run did NOT count as a review (it produced no verdict, or its "
                   "`surfaces:` glob matched 0 files) — its subject was left DUE rather than "
                   "re-anchored (T-12063)." if uncounted_seen else ""),
    }


def _mount_clause(evidence: list, cap: int = 3) -> str:
    """The named-mounts clause both runtime-delivery arms print — `service:mount (in <compose>)`, capped.

    NAMING THE COMPOSE FILE per row is the point (T-10905 / X-0711): a headline that asserts a fact about
    the production runtime must let the reader CHECK it against the file the claim came from, rather than
    trust it. aiseller acted on the un-named version and was steered toward declaring the exact INVERSE of
    its true runtime. ONE home, so the two arms cannot drift apart (CHARTER §P5). Empty ⇒ empty string."""
    rows = [e for e in evidence if isinstance(e, dict) and e.get("service")]
    named = [f"{e.get('service')}:{e.get('mount')}"
             + (f" (in {e.get('compose')})" if e.get("compose") else "") for e in rows]
    if not named:
        return ""
    return " — " + ", ".join(named[:cap]) + (f" +{len(named) - cap} more" if len(named) > cap else "")


# T-11842 — THE ONE abort-cost breakdown formatter, at module level rather than sealed inside
# `_render_debt_echo`. It is still exactly ONE formatter (T-11607 — deliberately shared so a clause
# cannot drift from its siblings); the hoist moves it, never forks it. It sits out here because the
# differential that proves this render must drive an INLINE LITERAL reconstruction of the
# pre-change formatter through the SAME render path (SPEC-0165), and a closure is unreachable from
# a probe.
_ABORT_NAMED_CAP = 3               # top 3 named per group, then `+N more` — the sibling convention


def _int_or_none(v):
    """The debt echo's int guard — a bool is NOT a count. Module-level so the hoisted formatter and
    `_render_debt_echo` share ONE implementation rather than carrying a copy each (CHARTER §P5)."""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _abort_named_rows(rows, totals=None, cap=_ABORT_NAMED_CAP):
    # T-11607 — the formatter, over an EXPLICIT row list, so a clause may name a SUBSET
    # of a group (its caught-defect arms, or its bookkeeping ones) with the identical
    # cap + trend shape. One formatter, never a second that could drift from it.
    # NAMED BY ITS `label`, never by its bare `class` — for a class name that unions two
    # refusals of different movability the label carries the ARM (`<class>[<arm>]`,
    # T-11426). The arm vocabulary has one home, in the fold; this render only prints what
    # the fold decided, so it can never re-union what the fold separated.
    #
    # T-11842 (owner-reported, 2026-08-30) — `totals` is the (n, minutes) pair the
    # ENCLOSING clause has ALREADY printed. Every call site sits inside `<M> min across
    # <N> abort(s) (...)`, so when the row list holds exactly ONE class that class's
    # numbers ARE the clause's numbers and the parenthetical restated them verbatim:
    # `RECLAIMABLE: 388.8 min across 20 abort(s) ... (rebaseline-unauthorized
    # [waive-coverage] 20x 388.8min)`. The repetition is what makes a reader look for a
    # second fact that is not there, and it fell precisely on the groups with the LEAST
    # to say. So the redundant `Nx Mmin` is dropped — and ONLY it: the LABEL and the
    # TREND are the information the parenthetical genuinely adds, and both survive
    # (X-1039's requirement that a trend is never separated from its cost is untouched —
    # the minutes are still stated, one clause-width away, by the sentence itself).
    #
    # THE GUARD IS ON EQUALITY, NOT ON CARDINALITY. A single-class list whose n or
    # minutes DIFFER from the enclosing totals — what the `_CAP`, a filtered subset or a
    # rounding difference produces — still prints them, because there the parenthetical
    # is genuinely saying something the clause has not. Suppressing on `len == 1` alone
    # would delete a real number. Minutes are compared at the 1-decimal precision the
    # fold itself rounds to, so a pair that READS equal is treated as equal.
    def _same_as_totals(c):
        if not totals or len(rows) != 1:
            return False
        t_n, t_m = totals
        if (_int_or_none(c.get("n")) or 0) != (_int_or_none(t_n) or 0):
            return False
        return round(float(c.get("minutes") or 0), 1) == round(float(t_m or 0), 1)

    def _one(c):
        numbers = "" if _same_as_totals(c) else \
            f" {_int_or_none(c.get('n')) or 0}x {c.get('minutes')}min"
        trend = (" " + str(c.get("trend")).upper()) \
            if c.get("trend") in ("decaying", "growing") else ""
        return f"{c.get('label') or c['class']}{numbers}{trend}"

    out = [_one(c) for c in rows[:cap]]
    tail = f" +{len(rows) - cap} more" if len(rows) > cap else ""
    return (", ".join(out) + tail) if out else ""


def _render_growth_relevance(reading) -> str:
    """T-11969 (SPEC-0189 rule 3) — the growth READING as a RELEVANCE clause on a restoration proposal.

    A PURE FORMATTER, and that is the load-bearing property rather than a style choice. Its ONLY branch
    is over its own WORDING — whether it has a readable reading to state — and it returns a string in
    every case. It cannot suppress a proposal, cannot reorder one, and is called only AFTER the caller
    has already decided to emit: a proposal with a count of 0, and a proposal with no reading at all,
    both render. That is rule 3 made structural — growth may gate RELEVANCE for the human weighing the
    proposal, and may never be the evidence that an absence is costing anything.

    THE CLAUSE STATES ITS OWN LIMIT, in the line, rather than trusting the reader to remember it: a
    count is not a liveness probe (`lessons/a-presence-count-is-not-a-liveness-probe.md`), and a reader
    who sees a number beside a proposal will otherwise read it as support for the proposal.

    An absent or unreadable reading is NAMED, not silently omitted — a missing measurement that renders
    as no clause at all is indistinguishable from a measurement of zero, and those mean opposite things."""
    if not isinstance(reading, dict):
        return (" Growth over the review window: not available (the reading could not be taken) — "
                "relevance context only; it is never the evidence (SPEC-0189 rule 3).")
    _c = reading.get("count")
    _w = reading.get("window_days")
    return (f" Growth alongside: {_c} land(s) in the last {_w} day(s) — RELEVANCE context for whoever "
            f"weighs this, never the evidence for it, and it did not decide whether this proposal "
            f"was made (SPEC-0189 rule 3).")


def _ref_grammar() -> str:
    """T-12021 — the accepted `evidence_events` ref grammar, read from its ONE home in `lib.task`.

    Imported LAZILY, the idiom this file already uses for `lib.task` / `lib.debt` (no import cycle).
    Fails toward SILENCE, like every other arm of this report-only surface: if the constant cannot be
    read the line simply omits the grammar rather than printing a stale copy or dying — a debt view
    must never nag on, or die of, an unknown."""
    try:
        from lib import task as task_mod
        return str(task_mod.P8_EVIDENCE_REF_GRAMMAR)
    except Exception:                              # noqa: BLE001 — see docstring
        return ""


def debt_mod_gap_window() -> int:
    """The triage-window number the gap line prints, read from its ONE home in `lib.debt`.

    Imported LAZILY — the idiom this file already uses for `lib.task` / `lib.debt` (no import
    cycle) — and failing toward the constant's own default rather than toward a stale literal, so
    the sentence can never quote a window the fold no longer uses."""
    try:
        from lib import debt as _debt
        return int(_debt.GAP_TRIAGE_WINDOW_DAYS)
    except Exception:                              # noqa: BLE001 — see docstring
        return 14


def abort_cause_breadth_cause_line(c) -> str:
    """T-12392 — THE one per-cause line of the SPEC-0119 rule-26 land-abort cause-breadth fold.

    HOISTED VERBATIM out of `_render_debt_echo`'s nested `_one_cause` closure, and module-level for
    exactly one reason: a SECOND reader of this fold now exists — the land HEAD, which prints the
    unresolved causes BEFORE paying the SPEC-0132 admission wait and the verify behind it
    (`worktree.cmd_land`, wired at cli.py's cmd_land residue). Two renderings of one fold would drift,
    and the identity digest is precisely what ties a land-head note to the `debt` line a reader then
    goes and reads — so there is ONE renderer and both seams call it (CHARTER §P5). The body is
    unmoved: the digest, the branch list, the T-12052 `, K since landed` suffix, the T-11900
    `, last fired Xh ago` age and the T-11810 failing-assertion sample all render exactly as before,
    so every suite asserting the session-start / land-tail / `debt` text keeps its answer.

    Pure and never raises: a non-dict cause yields "", and each annotation independently degrades to
    absent rather than to a guess (SPEC-0165 item 11). The duration formatting lives HERE and not in
    the fold because `bin/lib/debt.py` carries no duration vocabulary (SPEC-0149's structural
    tripwire) — the reason it sat in this module to begin with."""
    if not isinstance(c, dict):
        return ""
    _brs = [str(b) for b in (c.get("branches") or [])]
    _named = ", ".join(_brs[:3]) + (f" +{len(_brs) - 3} more" if len(_brs) > 3 else "")
    # T-11810 — NAME WHAT IS FAILING, BESIDE the digest and never instead of it. Measured
    # on the 2026-08-28 incident: this line fired correctly, and the controller who got it
    # at session start read past it, because `verify-failed#67dd68e5dcff` names nothing a
    # reader can act on and the row's own next step was another manual hop. The digest
    # STAYS — it is what ties this line to the repeated-abort backstop and to
    # `worktree._land_abort_cause_identity`. Deliberately BOUNDED (at most 2 names, each
    # truncated): this is one suppressed-when-clean line on a seam that already carries a
    # dozen others, and a failing-set dump gets read past for a different reason. A cause
    # whose rows carried no assertion text renders exactly as before rather than guessing.
    _asrt = [" ".join(str(a).split()) for a in (c.get("assertions") or [])][:2]
    _asrt = [(a[:60] + "…") if len(a) > 60 else a for a in _asrt if a]
    # T-11900 — SAY WHEN THE CAUSE LAST FIRED. The branch COUNT is a 24h-windowed
    # number and the line reads in the present tense, so a cause that stopped firing
    # hours ago is indistinguishable from one failing branches right now. Measured
    # 2026-08-30: this line's named cause last fired at 10:55:22Z, four lands passed
    # the same leg afterwards, and at 15:13Z it was still reported to the owner as
    # «one cause is STILL failing seven branches» — the second windowed-counter
    # misread of the same day, both owner-surfaced. The datum needs no fold change:
    # `land_abort_cause_breadth` already returns `last_ts` per cause and this render
    # simply dropped it. Same reason and same idiom as the sibling rule-34 span
    # directly below — a bare count cannot tell a live burn from a dead one — and the
    # formatting sits HERE for the same reason it does there: the fold carries no
    # duration vocabulary (SPEC-0149's structural tripwire over `bin/lib/debt.py`).
    # A cause whose `last_ts` is absent or unparseable — and a future stamp, which is
    # a clock skew and not an age — renders exactly as before rather than showing a
    # guessed or zero age (SPEC-0165 item 11: a value that cannot be answered is not
    # rendered as an answer), the same discipline the assertion sample above uses.
    _age_txt = ""
    _lts = c.get("last_ts")
    if isinstance(_lts, str) and _lts:
        from datetime import datetime as _dtc, timezone as _tzc
        try:
            _then = _dtc.fromisoformat(_lts.replace("Z", "+00:00"))
        except ValueError:
            _then = None
        if _then is not None:
            if _then.tzinfo is None:
                _then = _then.replace(tzinfo=_tzc.utc)
            # Sign-test the RAW delta, never the truncated one (audit-post finding):
            # `int()` truncates toward ZERO, so a stamp half a second in the future
            # gives int(-0.5) == 0 and would print a fabricated `0m ago` — the exact
            # guessed-value this branch exists to withhold, arriving through the guard
            # meant to stop it.
            _delta = (_dtc.now(_tzc.utc) - _then).total_seconds()
            _sec = int(_delta)
            if _delta >= 0:
                _age = (f"{_sec // 3600}h{(_sec % 3600) // 60:02d}m" if _sec >= 3600
                        else f"{_sec // 60}m")
                _age_txt = f", last fired {_age} ago"
    # T-12052 — SAY HOW MANY OF THE NAMED BRANCHES HAVE SINCE LANDED. The fold now
    # drops a branch from the cause once it lands, so a cause reaches this render only
    # while at least `min_branches` of them are still unresolved; the count and list
    # above stay the TOTAL refused set (a reader chasing the cause wants every lane it
    # hit), and this suffix says how much of that total is already history. Emitted
    # ONLY when K > 0, so a cause with nothing resolved — every cause that could reach
    # this line before T-12052 — renders byte-for-byte as it did.
    _res = c.get("resolved_count")
    _res_txt = (f", {_res} since landed"
                if isinstance(_res, int) and not isinstance(_res, bool) and _res > 0
                else "")
    return (f"{c.get('abort_class') or '?'}#{c.get('identity')} on "
            f"{c.get('branch_count')} branches ({_named}){_res_txt}{_age_txt}"
            + (f" — failing: {'; '.join(_asrt)}" if _asrt else ""))


def abort_cause_breadth_land_head_lines(view) -> list:
    """T-12392 — the LAND-HEAD note for the SPEC-0119 rule-26 fold: the abort cause(s) still
    unresolved on several DIFFERENT branches, named BEFORE this land spends anything.

    THE GAP, MEASURED (aiseller X-1365, 2026-09-10): one unresolved cause
    (`verify-failed#e7ab35cc1f71`) refused FOUR different branches, and each paid a FULL verify to
    re-diagnose what another branch had already surfaced. The fold that sees it has existed since
    T-11380, but it was read at SESSION START and at the land TAIL only — both of which are after
    the spend, or in a different process. This adds no fold, no store, no event and no gate: it
    reads the SAME view at an EARLIER seam.

    WHY EVERY CAUSE IS NAMED, with no cap and no `+N more` — deliberately UNLIKE the sibling debt
    echo this shares its renderer with. That echo truncates at 2 because it rides a seam already
    carrying a dozen report-only lines. This one fires ONLY when the fold is non-empty, which is
    rare, and it fires immediately before a 430-560s spend the reader may be about to waste — so
    completeness is worth more than brevity here, and a truncated list would leave a named cause
    unprinted at the one moment it could still save the verify (audit-pre pass-1 F2).

    REPORT-ONLY and SUPPRESSED-WHEN-CLEAN: `[]` for an absent, malformed or zero-count view, so a
    land with nothing unresolved prints byte-identically to before. Never raises — a report-only
    surface must never break the seam it rides."""
    if not isinstance(view, dict):
        return []
    # SUPPRESSION IS KEYED ON THE FOLD'S OWN DECLARED `count`, not merely on an empty `causes` list
    # (audit-post pass-1). The fold keeps the two in step — `count` IS `len(causes)` — so in
    # production they cannot disagree; the point is that this reader must not be the place where a
    # disagreement gets RESOLVED IN FAVOUR OF PRINTING. `count` is the field the suppressed-when-clean
    # contract is stated over, so an absent, non-numeric or non-positive one is read as «nothing to
    # say» and returns before rendering anything. Fail-closed toward silence, the direction every
    # error in this family already leans.
    count = view.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        return []
    causes = view.get("causes")
    if not isinstance(causes, list):
        return []
    rendered = [t for t in (abort_cause_breadth_cause_line(c) for c in causes) if t]
    if not rendered:
        return []
    out = [f"land: NOTE — {len(rendered)} land-abort cause(s) are STILL UNRESOLVED on several "
           f"DIFFERENT branches (SPEC-0119 rule 26). This land has not spent its verify yet:"]
    out += [f"land:   - {t}" for t in rendered]
    out.append("land:   if your verify fails on the same cause, do NOT re-diagnose it — read the "
               "named branch's abort row, fix the cause ON MAIN, and the rest stop paying for it. "
               "Report-only: this refuses nothing and changes no verdict (`bin/yitc-v2 debt` for "
               "the full rendering).")
    return out


def _render_debt_echo(*, _view_not_adopted, _view_overdue_recheck, _open_followup_count,
                      followup_floor: int = 5, _concern_conformance=None, _review_due=None,
                      _proof_obligations=None, _armed_fired_count=None,
                      _armed_waiting_count=None, _security_findings=None,
                      _unmonitored_dispatches=None, _adapter_conformance=None,
                      _unratified_adoptions=None, _unproven_checks=None,
                      _runtime_delivery=None, _security_gate_overrides=None,
                      _late_findings=None,
                      _unexecuted_test_classes=None,
                      _undeclared_subject_layers=None,
                      _unexecuted_subject_files=None,
                      _zero_skip_layers=None,
                      _slowest_decile_changes=None,
                      _broken_outcome_invariants=None,
                      _plan_census=None,
                      _unpickable_ready=None,
                      _unresolved_halts=None,
                      _remote_lag=None,
                      _own_evidence_patterns=None,
                      _dead_lands=None,
                      _ahead_branches=None,
                      _behind_branches=None,
                      _concurrent_sessions=None,
                      _abort_cause_breadth=None,
                      _branch_attempt_burn=None,
                      _aborted_land_cost=None,
                      _recorded_measurement=None,
                      _known_broken=None,
                      _prequeue_known_broken_refusals=None,
                      _selection_rollback=None,
                      _uncarried_p8=None,
                      _queue_jump_firings=None,
                      _tail_writes_withheld=None,
                      _load_sensitive_lane=None,
                      _seam_read_amplification=None,
                      _nightly_verdict_changes=None,
                      _restoration_proposals=None,
                      _profile_line=None,
                      _gap_register=None,
                      _load_sensitive_uncarded=None) -> list:
    """proactive-debt echo (SPEC-0119 / T-9754): the SHARED render helper. Computes the 3 DERIVED debt
    counts from the EXISTING views — not-adopted (SPEC-0094 §2, `_view_not_adopted`) / open-followups
    (SPEC-0095, the journal fold) / overdue-rechecks (SPEC-0094 §3, `_view_overdue_recheck`) — and
    returns a compact REPORT-ONLY line set: ONE `debt: …` line per view whose count > 0, an EMPTY list
    when every count is 0 (SUPPRESSED-WHEN-CLEAN). Reuses the SPEC-0086 `cross-coord:` echo discipline
    verbatim — report-only, count-derived, suppressed-when-clean, ZERO stored state (re-derived every
    call). NEVER gates / blocks / auto-acts. The open-followups line names the DISPOSITION FORK (SPEC-0119
    rule 4 — subsumes X-0141): разобрать (promote → a task / drop --reason) OR take straight into work.

    The three collaborators are INJECTED zero-arg callables (leaf-up, testable): `_view_not_adopted` /
    `_view_overdue_recheck` RETURN the view dict (count read from `not_adopted_count` / `overdue_count`);
    `_open_followup_count` RETURNS the int ACTIONABLE open-followup count. A count that is None or non-int
    (a view that could not derive — e.g. not-adopted with no resolvable live revision) is treated as
    NOTHING-TO-REPORT and suppressed: a report-only surface must never nag on an unknown.

    THE ARMED SPLIT (SPEC-0095 §Armed / SPEC-0119 rule 4, T-10309). An open followup carrying a `trigger`
    attribute is an ARMED WAITER — not stale, not yet actionable — so it must not inflate the headline
    "awaiting disposition" number the owner reads to decide what needs a decision NOW. `_open_followup_count`
    therefore now means the ACTIONABLE count, and the two armed halves arrive as TWO OPTIONAL injected
    collaborators (`_armed_fired_count` / `_armed_waiting_count`, both zero-arg → int; the host derives all
    three from the ONE `followup.open_followup_counts` fold). Absent/None ⇒ they contribute nothing and
    the line renders exactly as it did before the split — the same optional-collaborator discipline as
    `_concern_conformance` / `_review_due` / `_proof_obligations`, and the reason a caller that has not
    been updated degrades to today's behaviour instead of silently losing its followup line. The three
    counts print under three DIFFERENT disciplines:
      - actionable   → the HEADLINE count, FLOORED by `followup_floor` exactly as the single count was.
      - armed_fired  → its OWN clause, UNFLOORED, printed whenever > 0 (the armed record's AWAITED
                       artifact `awaits` went terminal, so its awaited moment ARRIVED — never its
                       `relates_to` provenance ref, T-10335). Unfloored on the same ground
                       as overdue-rechecks: a fired trigger is a dated obligation, never count-hidden.
                       This is what forbids "arm it and it silently disappears forever".
      - armed_waiting→ a TAIL on whichever followup line already prints; it NEVER forces a line, and it
                       rides exactly one line, never both.
    So arming DEFERS a followup out of the headline, and the fired clause guarantees it comes back.

    NOT-ADOPTED status gate (T-9754 in-build refinement): the genuine "shipped-but-not-live debt" — the
    X-0142 incident — is ONLY the `shipped-not-live` status (a real deploy baseline with HEAD strictly
    ahead). The `no-deploy-recorded` status returns the ENTIRE history as the count (a repo with no
    `deploy_completed` — e.g. the engine kernel itself), which is a baseline-absent signal, NOT
    shipped-but-not-live debt; surfacing it would false-nag thousands of commits every session-start /
    land (SPEC-0119 rule 3 — report-only NEVER nags). So only `shipped-not-live` contributes; every
    other status (no-deploy-recorded / clean / no-head / live-revision-not-found / -not-ancestor) is
    suppressed. The open-followups + overdue-recheck views have no such ambiguous baseline state.

    OPEN-FOLLOWUPS FLOOR (T-9789 / X-0157): a SMALL open-followup backlog should not spam the echo. The
    open-followups line prints only when its count is AT/ABOVE `followup_floor` (default 5); a count of
    1..floor-1 is treated as CLEAN (suppressed). `followup_floor` is host-supplied from the env knob
    `YITC_DEBT_FOLLOWUP_FLOOR` (see `_debt_followup_floor`); a non-positive / None / non-int floor disables
    the floor (effective floor 1 — any count > 0 fires). The floor is scoped to open-followups ONLY:
    not-adopted is already status-gated to `shipped-not-live` and its motivating incident (X-0142) was a
    LARGE count a floor would risk re-hiding; overdue-rechecks are date-triggered genuine past-due
    obligations, never count-hidden. Both stay unfloored (SPEC-0119 §Print discipline).

    CONCERN-CONFORMANCE view (SPEC-0119 rule 8 / SPEC-0128 Rule 2, T-10030): an OPTIONAL 4th injected
    collaborator `_concern_conformance` (zero-arg, RETURNS `{count, stance_issues, expired_waivers}` for
    THIS repo's ops carrier — see `init.concern_conformance`). When count > 0 it appends ONE report-only
    line naming the declare-or-waive stance drift + expired-waiver currency; when None/absent/clean it
    contributes nothing (suppressed). It NEVER gates — same discipline as the 3 base views.

    PROOF-OBLIGATION view (SPEC-0149, T-10296): an OPTIONAL injected collaborator `_proof_obligations`
    (zero-arg, RETURNS `{count, obligations, …}` — see `debt.open_proof_obligations`), the journal fold
    over deploys whose STAMPED obligation window has passed with no discharging recheck event. When
    count > 0 it appends ONE report-only line; when None/absent/clean it contributes nothing. It NEVER
    gates. Like the overdue-recheck view it is UNFLOORED — a past-due obligation is a dated,
    deadline-triggered debt, never count-hidden.

    SECURITY-FINDINGS view (SPEC-0119 rule 11, T-10440 / X-0306): an OPTIONAL injected collaborator
    `_security_findings` (zero-arg, RETURNS `{count, findings, floor_days, …}` — see
    `debt.open_subcritical_findings`), the fold over the security-audit report series naming the
    sub-critical (warning/info) findings open past the AGE floor. Only CRITICAL findings reach a
    mandatory reading moment today (the deploy gate); this line is the sub-critical ones' — they
    otherwise sit open indefinitely in a gitignored report nobody must read. Same discipline as every
    view above: report-only, count-derived, suppressed-when-clean, NEVER gates. Its floor is an AGE
    floor applied INSIDE the fold, not a count floor (rule 3): one warning open for a year is real
    debt, so the count is never hidden — only youth suppresses. ONE exception to suppressed-when-clean
    (T-10843): when the fold reports `authority_degrade` — it could not READ the latest report, its own
    sole authority on OPEN — that degrade renders as its own report-only line REGARDLESS of the count,
    because a broken subject rendering as clean is the one thing this view must never do. Still never
    gates; the named-degrade shape is the rule-23 live-revision adapter's, verbatim.

    UNMONITORED-DISPATCH view (SPEC-0119 rule 12, T-10471 / X-0336): an OPTIONAL injected collaborator
    `_unmonitored_dispatches` (zero-arg, RETURNS `{count, dispatches, floor_minutes, …}` — see
    `debt.unmonitored_dispatches`), the fold over the in-flight fleet naming the dispatched tasks whose
    worker has been flying past the AGE floor with no journaled monitoring read. `dispatch` OBLIGES the
    controller to arm a watcher (patterns/background-session-monitoring.md §Watcher, T-0620) — an
    obligation nothing could previously OBSERVE being skipped, which is what this line changes. Same
    discipline as every view above: report-only, count-derived, suppressed-when-clean, NEVER gates. It is
    NOT a behavioural detector (CHARTER non-goal 7): it reports fleet STATE — an undischarged obligation,
    exactly like an overdue recheck — never the agent's discipline, and it keeps no counter and no FSM.

    UNRATIFIED-ADOPTION view (SPEC-0119 rule 13, T-10508): an OPTIONAL injected collaborator
    `_unratified_adoptions` (zero-arg, RETURNS `{status, count, records}` — see
    `init.unratified_adoptions`), the carrier-stance view naming the `adoption:` records that still read
    `owner: init` — the BIRTH SENTINEL — over a section the carrier genuinely DECLARES. Such a record is
    TRUTHFUL but UNRATIFIED: the bootstrap act wrote it, no human reviewed it. The T-10493 init sweep
    passes it BY DESIGN (variant A: blocking it would fail-close honest consumers), so this line is that
    residual's ONE reading moment — without it the un-asked question stays invisible forever
    (`lessons/a-stance-mirror-is-only-sound-at-birth`). Same discipline as every view above: report-only,
    count-derived, suppressed-when-clean, NEVER gates, and it never auto-ratifies (ratification is the
    owner's act). UNFLOORED, on the same ground as rules 11/12: one unratified adoption is real debt, and
    count-hiding it would restore the silence the view exists to end. A no-carrier repo (the engine kernel
    itself) yields count 0 → suppressed.

    UNPROVEN-CHECKS view (SPEC-0156, T-10509): an OPTIONAL injected collaborator `_unproven_checks`
    (zero-arg, RETURNS `{count, checks, …}` — see `debt.unproven_checks`), the fold over this repo's ops
    carrier + journal naming the kernel-graded checks DECLARED with no recorded FAILING DEMONSTRATION of
    their current definition. It is the admission invariant's surface: a check nobody has ever seen fail
    is admitted UNPROVEN and says so here, rather than being silently counted as coverage (the aiseller
    2026-07-13 class — 8h of prod-auth death behind six kernel-accepted greens). Same discipline as every
    view above: report-only, count-derived, suppressed-when-clean, NEVER gates — SPEC-0156 §3 adds no
    hard-gate class, and where a surface's own contract already fails closed, that stricter rule stands.
    UNFLOORED, like overdue-rechecks: one check that has never been seen to fail is real debt, never
    count-hidden.

    RUNTIME-DELIVERY view (SPEC-0119 rule 16, T-10511 / X-0370): an OPTIONAL injected collaborator
    `_runtime_delivery` — the ONE collaborator here that takes an ARGUMENT (the already-computed
    not-adopted view; RETURNS `{count, kind, model, evidence, commits, …}` — see
    `debt.runtime_delivery_coherence`), because it is a REVERSE READING of that very view and must consume
    the SAME derivation rather than re-deriving a second, possibly-disagreeing one (P5). That first line
    calls the commits between the last `deploy_completed` and `main` "shipped-but-not-live" — TRUE only if
    the deploy verb is the sole path to prod. Where the runtime reads the SOURCE TREE (a bind mount / hot
    reload) it is not: a container recreate ships `main` with no verb, so those same commits are ALREADY
    LIVE and passed no gate (X-0370 — half a paired change shipped, 8h outage). This line says so, in the
    two shapes the incoherence takes: an UNDECLARED bypass (detected from the repo's own compose
    bind-mounts) and a DECLARED bypassable model whose live revision has fallen behind `main`. Same
    discipline as every view above: report-only, count-derived, suppressed-when-clean, NEVER gates.
    UNFLOORED — one commit live behind no gate is exactly the debt this view exists to name.

    UNEXECUTED-TEST-CLASSES view (SPEC-0152 rule 24, T-10513 / X-0375): an OPTIONAL injected collaborator
    `_unexecuted_test_classes` (zero-arg, RETURNS `{count, classes, floor_days, …}` — see
    `debt.unexecuted_test_classes`), the fold over this repo's carrier + journal naming the declared
    `tests.classes` with no recorded successful execution (`never`) or one aged past the staleness floor
    (`stale`). It is the EXECUTION axis of the SPEC-0156 admission doctrine printed one line above: a
    demonstration proves a check CAN fail, this proves it has actually RUN — a class nobody ran is not
    coverage (aiseller's e2e suite: browsers never installed, nothing ran, nothing failed). Same discipline
    as every view above: report-only, count-derived, suppressed-when-clean, NEVER gates. UNFLOORED (a class
    never seen to run is debt at count 1) and a repo that declares no test class — the engine kernel itself
    — folds to 0, so history is never retro-charged.

    ZERO-SKIP-VERIFY-LAYERS view (SPEC-0119 / SPEC-0152 rule 16 subject_globs, T-11080): an OPTIONAL
    injected collaborator `_zero_skip_layers` (zero-arg, RETURNS `{count, layers, window_lands, …}` — see
    `debt.zero_skip_verify_layers`), the fold over the JOURNAL naming the executable verify layers that
    skipped 0% of the time over the recent-lands window, i.e. ran on EVERY land. It is the OBSERVED
    counterpart of the CARRIER-read undeclared-subject line printed beside it, and the pair is deliberate:
    the carrier can only answer "is a subject DECLARED?", which a layer declaring a SUPERSET answers while
    still never skipping — that layer is invisible to the carrier and visible only here (aiseller: 0% skip
    on all four layers across 453 lands at an 84.6s median, against boomrocket's 0.9s median with globs on
    all 8). Same discipline as every view above: report-only, count-derived, suppressed-when-clean, NEVER
    gates. UNFLOORED at the LINE — the evidence floor lives inside the fold, which does not score a layer
    until it has been observed enough times to mean anything, and which never reads an ABSENT per-layer row
    as a non-skip (rows begin only once a project declared its layers). A repo with no layered land — the
    engine kernel itself — folds to 0, so history is never retro-charged. It carries ONE companion line
    that is deliberately NOT suppressed-when-clean (T-11749 / kupiclub X-1165): the RUN-level skip rate,
    the share of LANDS in the same window that skipped at least one layer, read off the same fold's
    `run_skip`. A rate is not owed work, so for it silence and 0% would be indistinguishable — and an
    unwatched rate halving from 40% to 18% while nothing printed it is precisely what produced the ask.
    It stays silent only with NO denominator (no land in the window recorded a per-layer trail), which is
    no measurement rather than a rate of zero.

    BROKEN-OUTCOME-INVARIANTS view (SPEC-0119 rule 17, T-10554 / X-0419): an OPTIONAL injected collaborator
    `_broken_outcome_invariants` (zero-arg, RETURNS `{count, invariants, …}` — see
    `debt.broken_outcome_invariants`), the fold over this repo's declared `outcome_invariants:` (SPEC-0093
    rule 24) + the journal + the declared read-only probes. Every OTHER view here reports debt ABOUT the
    process — what was shipped, declared, owed, watched. This one reports whether the PRODUCT still works:
    P3/P8 adoption evidence is framed on the DIFF, so a long-lived subsystem no card owns has no outcome
    probe at all and cannot be observed broken (X-0419 — five remediation cards closed green over three days
    while the product stayed broken, and the owner was the only monitor). Its three states are worded APART
    because their remedies differ: `broken` (the probe says the invariant is violated NOW — fix the
    subsystem), `degraded` (the probe could not answer — fix the probe; an invariant whose probe is broken is
    not covered, and silence would hide a broken subsystem behind a broken probe), and `unproven` (no
    recorded RED demonstration of the CURRENT definition — SPEC-0156 reused verbatim, so its green proves
    nothing and is never trusted-green). Same discipline as every view above: report-only, count-derived,
    suppressed-when-clean, NEVER gates. UNFLOORED — one broken product outcome is debt at count 1, and
    count-hiding it would restore the exact silence the view exists to end. Only the DECLARED, non-waived
    set can interrupt (`lessons/scope-the-trigger-not-the-view`); a repo that declares no invariant — the
    engine kernel itself — folds to 0, so history is never retro-charged.

    NON-TERMINAL PLAN CENSUS (SPEC-0119 rule 21, T-11181): an OPTIONAL injected collaborator
    `_plan_census` (zero-arg, RETURNS `{count, by_status, unknown, terminal, total}` — see
    `debt.nonterminal_plan_census`), the fold over `plans/*.md` frontmatter naming how many plans sit
    in each NON-TERMINAL stage of the plan FSM. Plans are the one tracked work class NO seam
    surfaced: the picker reads `tasks/` ONLY, and no sibling view above opens `plans/` — so a plan
    parked mid-FSM, most concretely one sitting in `postcheck` (the real-data soak), is unfinished
    work that simply goes quiet. TERMINAL plans are NOT counted, which is most of the corpus and
    exactly the noise a census of everything would be. UNFLOORED, on the same ground as rules 11-18:
    one plan out of sight is real debt, and count-hiding it restores the silence this line ends.
    Same discipline as every view above: report-only, count-derived, suppressed-when-clean, NEVER
    gates.

    AHEAD-WORK-BRANCHES view (SPEC-0119 rule 24, T-11303 / kupiclub X-1001, corrected by X-1003): an
    OPTIONAL injected collaborator `_ahead_branches` (zero-arg, RETURNS `{count, branches, floor_hours,
    …}` — see `debt.ahead_work_branches`), the fold over the git branch frontier naming the `task/*` /
    `work/*` branches that carry commits `main` does not have. Whether a branch is AHEAD of main is the
    ONE fact separating a benign stale branch from a serious one, and NO surface reported it: the
    dispatch census counts live WORKTREES rather than branches, the not-adopted view walks main→live
    (the INVERSE leg, so a branch that never reached main is invisible to it by construction), and
    `worktree sweep` removes the desk copy without deleting the branch and says nothing at any seam. It
    is the COMPLEMENT of rule 23, not an overlap: that view owns branches whose land STARTED and never
    reported, this owns branches where a land never started at all, and the two are partitioned by rule
    23's own tip predicate under an `ahead == 1` bound (an unbounded tip test would drop a marker-tipped
    branch whose EARLIER commits are real work — which rule 23 also misses once its land reported —
    restoring the blind spot inside the predicate meant to divide them). The count is of commits main
    lacks BY SHA and the line SAYS so: a change that reached main by another commit still shows as a
    difference, which is exactly the reading the reporter retracted in X-1003, so this view reports the
    fact as the fact it is and judges nothing. FLOORED BY AGE, never by count (rule 3): every healthy
    in-flight build has a branch ahead of main, so youth is precisely what must not fire. Same
    discipline as every view above: report-only, count-derived, suppressed-when-clean, NEVER gates.

    CONCURRENT-SESSION-HOLDS view (SPEC-0119 rule 25, T-11353 / kupiclub X-1025): an OPTIONAL
    injected collaborator `_concurrent_sessions` (zero-arg, RETURNS `{count, worktrees, holders, …}`
    — see `debt.concurrent_session_holds`), the fold over the LIVE worktree list + the T-0362 session
    stamps naming the holds carried by a session OTHER than the reading one. Every default surface
    renders this repo as single-actor, and the one that looks like coverage is not: the in-progress
    count folds card STATUS on the reading checkout, while a claim lives in the claiming worktree
    until `land` — so a card another session already holds still reads `ready` on main. Two bounds
    are stated IN THE LINE rather than left to the reader: the count is of DISTINCT SESSION STAMPS
    and NEVER of independent actors (a controller and its dispatched fleet share one provider session
    id, T-0412), and liveness is ADVISORY, separate from presence, never authority (T-0351,
    `lessons/a-presence-count-is-not-a-liveness-probe`). SEAM SET (rule 21's discipline, reused): the
    caller WITHHOLDS this collaborator at the LAND TAIL — it is a CHECKOUT fold, and the land tail is
    the seam that deletes a checkout, so it cannot honour that seam's agree-with-the-`debt`-verb
    contract (T-11139); it rides session-start and the on-demand `debt` re-fold. Same discipline as
    every view above: report-only, count-derived, suppressed-when-clean, NEVER gates — and here that is the whole
    design, not a default: making a concurrent session VISIBLE is not making it EXCLUSIVE. It builds
    no lock, no lease, no owner-election and no refusal to dispatch; concurrency is NORMAL (D-0083).
    UNFLOORED — one unseen concurrent holder is exactly the case that re-litigates a settled decision
    or duplicates a dispatch, so count-hiding it restores the silence the rule ends.

    RESTORATION-PROPOSAL view (SPEC-0189, T-11969): an OPTIONAL injected collaborator
    `_restoration_proposals` (zero-arg, RETURNS `{count, proposals, …}` — see
    `debt.restoration_proposals`), the fold over the concerns born PERMISSIVE whose NAMED detector has
    fired. One report-only line per proposal, naming the PROJECT, the SURFACE and the OBSERVED SIGNAL,
    plus the specific tightening proposed and the growth reading as a stated RELEVANCE clause that
    decides nothing (SPEC-0189 rule 3 — a low-growth project still proposes). It PROPOSES and never
    applies (rule 4): nothing on this path writes a project's contract. The renderer independently
    re-checks each proposal and DROPS one missing project / surface / signal, so a proposal assembled
    from a growth count alone is refused at the render door as well as at the assembler's
    (§Verification R3). Same discipline as every view above: report-only, suppressed-when-clean, NEVER
    gates. UNFLOORED — one surface whose absence has begun to cost something is the whole subject.

    SURFACING IS NOT PICKING — the boundary this line is built against, and why it renders a COUNT
    and nothing else. It names no candidate, ranks nothing, and selects nothing; taking a plan into
    work stays an owner cue. That is the same boundary SPEC-0085 §8 already draws for the sibling
    cross-coordination surface («surfacing != queue-scan»), and the one T-0510 drew when it removed
    the startup picker while KEEPING the waiting-on-owner surfacing as "a safety signal, not
    queue-exploration". The plan-status `unknown` count rides this ONE line as a tail clause rather
    than forcing a second: it is the same headline debt (a plan nobody is tracking) reached by a
    different route, and it is NAMED rather than folded away because its remedy differs — repair the
    frontmatter, then read the plan."""
    lines = []

    _n = _int_or_none

    # open-followups floor: a non-positive / None / non-int floor disables it (effective floor 1).
    _fu_floor = followup_floor if (isinstance(followup_floor, int) and not isinstance(followup_floor, bool)
                                   and followup_floor > 0) else 1

    _na_view = _view_not_adopted() or {}
    na = _n(_na_view.get("not_adopted_count")) if _na_view.get("status") == "shipped-not-live" else None
    if na and na > 0:
        # T-10747 / X-0580: the count is DEPLOYABLE-PATH scoped, and the line SAYS so — the previous
        # wording ("N not-adopted commit(s)") is what a controller read as production risk over a range
        # that was pure governance. When commits were excluded, name how many: a reader who sees the
        # number must be able to explain it without diffing the range by hand. One line reworded, still
        # report-only, no new row (SPEC-0119 rule 3).
        _gov = _n(_na_view.get("governance_only_count")) or 0
        _gov_tail = (f" ({_gov} governance-only commit(s) in the range excluded — no runtime content)"
                     if _gov > 0 else "")
        lines.append(
            f"debt: {na} deployable-path commit(s) shipped-but-not-live{_gov_tail} — report-only "
            f"(SPEC-0094 §2). See `bin/yitc-v2 graph query not-adopted`.")
    # LIVE-REVISION-ADAPTER DEGRADE (T-10521 / SPEC-0093 rule 23): a declared `deploy.live_revision` adapter
    # that ERRORED — the live baseline fell back to the deploy_completed proxy, so the divergence readings
    # above/below may be stale. NAMED, never silent (a broken adapter must not silently zero the debt).
    # Report-only, suppressed when the adapter is absent/healthy, NEVER gates.
    _lr_degrade = _na_view.get("live_revision_degrade")
    if isinstance(_lr_degrade, str) and _lr_degrade.strip():
        lines.append(
            f"debt: live-revision adapter degraded — falling back to the deploy_completed proxy for the "
            f"live baseline: {_lr_degrade.strip()} (SPEC-0093 rule 23). Fix or waive `deploy.live_revision` "
            f"in yitc-ops.yaml.")
    # OPEN-FOLLOWUP three-way partition (SPEC-0095 §Armed / T-10309). `_open_followup_count` keeps its
    # int contract and its meaning NARROWS to the ACTIONABLE count (the headline). The two armed halves
    # arrive as OPTIONAL injected collaborators — the same idiom `_concern_conformance` / `_review_due` /
    # `_proof_obligations` use below — so a caller that injects neither renders exactly today's line, and
    # a stale caller can never silently lose its followup line.
    fu = _n(_open_followup_count())
    fired = _n(_armed_fired_count()) if _armed_fired_count is not None else None
    waiting = _n(_armed_waiting_count()) if _armed_waiting_count is not None else None
    # The armed-waiting TAIL rides whichever followup line already prints; it NEVER forces one (a waiter
    # is not yet actionable, so it must never nag — that is the whole point of the split).
    _wait_tail = (f" (+{waiting} armed, awaiting a named trigger — `bin/yitc-v2 followup list "
                  f"--status armed`)") if waiting else ""
    _headline_printed = bool(fu and fu >= _fu_floor)
    if _headline_printed:
        lines.append(
            f"debt: {fu} open followup(s) awaiting disposition — triage (promote → a task / "
            f"drop --reason) OR take straight into work (SPEC-0095). See `bin/yitc-v2 followup list`."
            + _wait_tail)
    # ARMED-FIRED is UNFLOORED and prints on its OWN clause whenever > 0: the named artifact CLOSED, so
    # this waiter's moment ARRIVED and it is now due. Unfloored on the same ground as overdue-rechecks
    # (rule 3) — a fired trigger is a dated, event-triggered obligation, never count-hidden. Without it,
    # an armed item suppressed below the floor could stay hidden forever after its trigger fired
    # (T-10309 audit-pre finding 1); with it, arming can DEFER a followup but never LOSE it.
    if fired and fired > 0:
        lines.append(
            f"debt: {fired} armed followup(s) whose TRIGGER FIRED — their named artifact closed; dispose "
            f"(promote → a task / drop --reason) (SPEC-0095). See `bin/yitc-v2 followup list --status fired`."
            + ("" if _headline_printed else _wait_tail))   # the tail rides exactly ONE line, never both
    _or_view = _view_overdue_recheck() or {}
    ov = _n(_or_view.get("overdue_count"))
    if ov and ov > 0:
        lines.append(
            f"debt: {ov} overdue recheck(s) past recheck_by — run their live_probe at the deploy seam "
            f"(SPEC-0094 §3). See `bin/yitc-v2 graph query overdue-recheck`.")
    # POST-SHIP OBSERVATIONS (T-10916 / SPEC-0036 / X-0710) — its OWN clause, off the SAME existing view
    # call (no new collaborator, no new call site). Deliberately NOT folded into the count above: that
    # count means "waivers past recheck_by" and its remedy is a live_probe at the deploy seam, while this
    # one means "an acceptance proof a Stage-8 audit deferred is still unrecorded" and its remedy is to
    # take the reading and record it. Two signals, two lines, two remedies — never conflated. UNFLOORED
    # and printed while still PENDING, on the same ground as overdue-rechecks (SPEC-0119 rule 3): a
    # deferred proof that goes quiet until it is late is exactly how deferred adoption becomes
    # never-adopted, which is the failure this whole carve-out was built to avoid.
    #
    # THE HEADLINE IS THE ACTIONABLE COUNT — the followup ARMED SPLIT, applied here (T-11949). This is
    # NOT a second discipline: it is the SAME ratified rule the OPEN-FOLLOWUP clause ~40 lines above
    # already states verbatim (SPEC-0095 §Armed / SPEC-0119 rule 4, T-10309) — an item that is "not
    # stale, not yet actionable" must not inflate the headline number the owner reads to decide what
    # needs a decision NOW, so it rides a TAIL instead. ONE rule, TWO consumers: an armed followup
    # awaiting its trigger there, a PENDING observation whose `due_by` has not arrived here. This
    # clause used to do the exact INVERSE — headline the whole declared set, parenthesise the overdue
    # subset (`57 ... (13 past due_by)`, measured 2026-09-01) — which reads as 57 things owed when 44
    # of them owe nothing yet. So: OVERDUE is the headline, PENDING is the tail.
    # The pending count MOVES SLOT, it never DISAPPEARS — that is the other half of the borrowed rule
    # (the armed-fired clause exists so arming can DEFER a followup but never LOSE it). Hence the
    # zero-overdue branch below still PRINTS, reporting the pending count and saying out loud that
    # none of it is actionable yet: filtering the view down to overdue would headline the right number
    # by making 44 declared obligations silently vanish, which is precisely the failure this rule
    # guards against. The `_obs > 0` guard is UNCHANGED, so suppressed-when-clean still holds: a
    # repo with no declared observation at all prints nothing.
    _obs = _n(_or_view.get("observations_count"))
    if _obs and _obs > 0:
        _obs_over = _n(_or_view.get("observations_overdue_count")) or 0
        _obs_pending = max(0, _obs - _obs_over)
        _settle_tail = (
            "settle the card with `bin/yitc-v2 task close <T-XXXX> --settle-observation <locator>` "
            "(T-11529), which writes `post_ship_observation.settled_by` and is the ONLY thing that "
            "clears it (T-10916, SPEC-0036). See `bin/yitc-v2 graph query overdue-recheck`.")
        if _obs_over > 0:
            _pending_tail = (f" (+{_obs_pending} more declared, not yet due)" if _obs_pending else "")
            lines.append(
                f"debt: {_obs_over} post-ship observation(s) PAST due_by and NOT yet recorded"
                f"{_pending_tail} — take the reading and record it, then {_settle_tail}")
        else:
            lines.append(
                f"debt: no post-ship observation is PAST due_by — {_obs_pending} declared and awaiting "
                f"their reading, none actionable yet. Nothing is owed today; when a due_by arrives, "
                f"take the reading and {_settle_tail}")
    # DEFERRED ACCEPTANCE PROBES (T-11408 / SPEC-0119 rule 3 / kupiclub X-1066) — a FIFTH clause, off the
    # SAME `_view_overdue_recheck` call (no new collaborator, no new call site). Its own line for the
    # same reason the observations clause has one: the remedy differs (settle the probe with the
    # evidence, `task close --settle-probe`), and conflating two remedies into one count tells the
    # reader neither. UNFLOORED, so the `_defp > 0` suppressed-when-clean guard is the only silence.
    #
    # COUNTED FROM DEFERRAL, HEADLINED FROM DUE (T-12076) — the SAME split T-11949 made one clause
    # up, and for the same reason, now that a deferral records its firing moment. The clause used to
    # headline the WHOLE deferred set from the moment of deferral, on the ground that a deferred
    # probe carried no due date at all; it does now, so that ground is gone and what the old shape
    # produced was 94 cards / 96 probes on 2026-09-04, most of whose readings could not be taken that
    # day. A debt line that names what nobody can act on today teaches the reader to skip the line
    # that also carries the real ones.
    #
    # THE PENDING COUNT MOVES SLOT, IT NEVER DISAPPEARS — the other half of the borrowed rule, and
    # the reason the zero-due branch still PRINTS instead of falling silent: filtering the view down
    # to due would headline the right number by making every not-yet-due obligation silently vanish,
    # which is precisely the failure SPEC-0119 rule 3 exists to prevent. A LEGACY key-only deferral
    # reads DUE (`_deferred_probe_due`), so no pre-T-12076 deferral is hidden by this change.
    _defp = _n(_or_view.get("deferred_probes_count"))
    if _defp and _defp > 0:
        _defc = _n(_or_view.get("deferred_probe_criteria_count")) or 0
        _def_due_raw = _or_view.get("deferred_probes_due_count")
        _def_due = _n(_def_due_raw) or 0
        _def_due_c = _n(_or_view.get("deferred_probe_criteria_due_count")) or 0
        _def_pend_c = _n(_or_view.get("deferred_probe_criteria_pending_count")) or 0
        _settle_how = (
            "settle each with `bin/yitc-v2 task close <T-XXXX> --settle-probe <AC>:pass "
            "--settle-evidence <locator>` (T-11107, T-11408), or — when the proof can NEVER arrive / "
            "the reading came back NEGATIVE — discharge it honestly with `--settle-probe "
            "<AC>:unreachable|falsified --settle-reason <why>` (T-11657). See `bin/yitc-v2 graph "
            "query overdue-recheck`.")
        if _n(_def_due_raw) is None:
            # A view that predates the T-12076 split (or a caller supplying an old-shaped dict)
            # carries no due/pending keys. Degrade to the UN-SPLIT headline rather than announce
            # "nothing is due" off keys that simply are not there — the same optional-collaborator
            # discipline every injected view on this renderer follows, and the safe direction: an
            # un-split count over-reports rather than hides.
            lines.append(
                f"debt: {_defp} card(s) carrying {_defc} DEFERRED acceptance probe(s) not yet "
                f"settled — the card recorded the proof as owed and nothing else did; {_settle_how}")
        elif _def_due > 0:
            _pending_tail = (f" (+{_def_pend_c} deferred, not yet due)" if _def_pend_c else "")
            lines.append(
                f"debt: {_def_due} card(s) carrying {_def_due_c} DUE deferred acceptance probe(s)"
                f"{_pending_tail} — the card recorded the proof as owed and its moment has arrived; "
                f"{_settle_how}")
        else:
            lines.append(
                f"debt: no deferred probe is due — {_def_pend_c} awaiting their moment, none "
                f"actionable yet. Nothing is owed today; when a moment arrives, {_settle_how}")
    # T-11657 — the two NON-PASS TERMINALS, as TWO SEPARATE counted lines. Never one merged
    # "non-pass" line: a reader must be able to see AT A GLANCE how much of the floor is
    # proof-can-never-arrive versus proof-came-back-negative, because those ask for DIFFERENT
    # remedies — the first is an authoring fix (T-11656 / SPEC-0060), the second is a real finding
    # someone may need to act on. Same discipline as every line above: report-only, count-derived,
    # unfloored, suppressed-when-clean, NEVER gates.
    _unrp = _n(_or_view.get("unreachable_probes_count"))
    if _unrp and _unrp > 0:
        _unrc = _n(_or_view.get("unreachable_probe_criteria_count")) or 0
        lines.append(
            f"debt: {_unrp} card(s) carrying {_unrc} UNREACHABLE acceptance probe(s) — a proof that "
            f"can NEVER arrive, each discharged with a recorded reason (T-11657). This is a PERMANENT "
            f"FLOOR, not a backlog: nothing anyone does will move it, and it is deliberately not "
            f"folded into the deferred count that reads as work owed. The remedy is an AUTHORING fix "
            f"for the NEXT card (T-11656 / SPEC-0060), never work on these. Neither this nor the "
            f"falsified line satisfies CHARTER Principle 8 adoption evidence. See `bin/yitc-v2 graph "
            f"query overdue-recheck`.")
    _falp = _n(_or_view.get("falsified_probes_count"))
    if _falp and _falp > 0:
        _falc = _n(_or_view.get("falsified_probe_criteria_count")) or 0
        lines.append(
            f"debt: {_falp} card(s) carrying {_falc} FALSIFIED acceptance probe(s) — the reading "
            f"ARRIVED and came back NEGATIVE, each discharged with a recorded reason (T-11657). READ "
            f"THESE: unlike an unreachable one, a falsified criterion is a REAL FINDING about a "
            f"shipped change that someone may need to act on. It is the OPPOSITE of adoption "
            f"evidence, not a weaker form of it. See `bin/yitc-v2 graph query overdue-recheck`.")
    # CONCERN-CONFORMANCE view (SPEC-0119 rule 8 / SPEC-0128 Rule 2, T-10030): the OPTIONAL injected
    # collaborator returns {count, stance_issues, expired_waivers} for THIS repo's ops carrier (a no-carrier
    # repo — the engine kernel itself — yields count 0 → suppressed). Report-only, suppressed-when-clean,
    # NEVER gates; best-effort (a None/absent collaborator or a non-dict return contributes nothing). The
    # SAME `concern_conformance` source feeds the nightly runner (SPEC-0105), so both surfaces agree.
    if _concern_conformance is not None:
        _cc = _concern_conformance() or {}
        cc = _n(_cc.get("count")) if isinstance(_cc, dict) else None
        if cc and cc > 0:
            _si = len(_cc.get("stance_issues") or [])
            _ew = len(_cc.get("expired_waivers") or [])
            _parts = []
            if _si:
                _parts.append(f"{_si} unanswered/contradictory stance(s)")
            if _ew:
                _parts.append(f"{_ew} expired waiver(s)")
            lines.append(
                f"debt: {cc} concern-conformance issue(s) in yitc-ops.yaml ({', '.join(_parts)}) — "
                f"declare-or-waive each vs the concern registry (SPEC-0128) then re-run "
                f"`bin/yitc-v2 -C . init`. Report-only (SPEC-0119 rule 8).")
        # CARRIER COMMENT-CONTRACT gap (T-10536 / X-0401) — its OWN line, on its OWN arm, read from the
        # SAME injected view (no new collaborator → all three debt seams light up from this one existing
        # wiring site). Deliberately NOT folded into the `count` above: that count means declare-or-waive
        # issues, its remedy is "declare-or-waive each concern", and this gap's remedy is a different one
        # (restore the contract comment text). Two signals, two lines, two remedies — never conflated.
        _cg = len(_cc.get("comment_contract") or []) if isinstance(_cc, dict) else 0
        if _cg:
            # TWO CAUSES, OPPOSITE REMEDIES (T-10568 / X-0423). The detector already knows which one this
            # is (`comment_contract_kind`); before, this line hardcoded the X-0401 restore for BOTH — and
            # against boomrocket's T-0203 (a SPEC-0152 re-home, 3 anchors, comments intact) a literal
            # reading would have destroyed ~150 lines of the consumer's own prose. So the text now follows
            # the cause. A view that omits the key reads `full-strip` → today's line, verbatim, unchanged.
            _kind = (_cc.get("comment_contract_kind") or "full-strip") if isinstance(_cc, dict) else "full-strip"
            if _kind == "partial":
                _rh = _cc.get("comment_contract_rehome") or []
                _named = (f" Re-home candidate(s): {'; '.join(_rh)}." if _rh else
                          f" No re-home candidate found — compare the named section(s)' citations against "
                          f"`graph/born-ops.yaml` by hand.")
                lines.append(
                    f"debt: {_cg} missing kernel contract-comment anchor(s) in yitc-ops.yaml — PARTIAL gap: "
                    f"the carrier's other contract comments are INTACT, so this is NOT the X-0401 strip but "
                    f"a kernel spec SPLIT/re-home (a rule moved to a new spec home).{_named} Reconcile the "
                    f"citation(s) only — do NOT restore the born template over your own prose. "
                    f"Report-only (SPEC-0119 rule 8).")
            else:
                lines.append(
                    f"debt: {_cg} missing kernel contract-comment anchor(s) in yitc-ops.yaml — the carrier's "
                    f"contract is delivered THROUGH its comments, and a YAML round-trip edit "
                    f"(safe_load->dump) silently strips them (X-0401). Restore the comment text for the named "
                    f"section(s) from the kernel's born template (`graph/born-ops.yaml`); edit the carrier as "
                    f"TEXT, never via a YAML round-trip. Report-only (SPEC-0119 rule 8).")
    # VENDOR-ADAPTER view (SPEC-0125 VP1/VP2, T-10480): the OPTIONAL injected collaborator returns
    # {status, count, violations} for THIS repo's adapter→neutral-home chain (`init.adapter_conformance`).
    # It is what gives a CONSUMER a per-repo `-C` surface for the check WITHOUT a new verb: injected at the
    # one shared host residue, it rides all three debt seams at once — the consumer's `-C` session-start,
    # the land-tail, and the on-demand `bin/yitc-v2 -C <repo> debt` re-fold — so they cannot drift apart
    # (the rule-11 / rule-12 wiring precedent). A repo with no CLAUDE.md (`no-adapter` — the engine kernel
    # itself) yields count 0 → suppressed. Report-only, suppressed-when-clean, NEVER gates; best-effort (a
    # None/absent collaborator or a non-dict return contributes nothing). The SAME `adapter_conformance`
    # source feeds the nightly runner (SPEC-0105), so both surfaces agree (CHARTER §P5).
    if _adapter_conformance is not None:
        _ac = _adapter_conformance() or {}
        ac = _n(_ac.get("count")) if isinstance(_ac, dict) else None
        if ac and ac > 0:
            _kinds = sorted({str(v.get("kind")) for v in (_ac.get("violations") or [])
                             if isinstance(v, dict) and v.get("kind")})
            lines.append(
                f"debt: {ac} vendor-adapter issue(s) in CLAUDE.md ({', '.join(_kinds)}) — the "
                f"adapter→neutral-home chain an AI session reads does not resolve: keep CLAUDE.md THIN "
                f"and put the operating-context in the provider-neutral home (SPEC-0125 Rule 1/2). "
                f"Report-only (SPEC-0119).")
    # UNRATIFIED-ADOPTION view (SPEC-0119 rule 13, T-10508): the OPTIONAL injected collaborator returns
    # {status, count, records} for THIS repo's `adoption:` records still stamped with the BIRTH SENTINEL
    # (`owner: init`) over a section the carrier DECLARES — truthful, but nobody ratified them. The
    # T-10493 init sweep passes them by design (variant A), so this is their ONE reading moment. Injected
    # at the same shared host residue as its siblings → all three debt seams at once. Report-only,
    # suppressed-when-clean, UNFLOORED, NEVER gates; best-effort (a None/absent collaborator or a non-dict
    # return contributes nothing). It never auto-ratifies — the exit it NAMES is the owner's own act.
    if _unratified_adoptions is not None:
        _ua = _unratified_adoptions() or {}
        ua = _n(_ua.get("count")) if isinstance(_ua, dict) else None
        if ua and ua > 0:
            _ids = [str(r.get("concern")) for r in (_ua.get("records") or [])
                    if isinstance(r, dict) and r.get("concern")]
            _CAP = 6
            _named = (" — " + ", ".join(_ids[:_CAP]) +
                      (f" +{len(_ids) - _CAP} more" if len(_ids) > _CAP else "")) if _ids else ""
            lines.append(
                f"debt: {ua} unratified adoption(s) in yitc-ops.yaml{_named} — the record says `adopt` "
                f"but is still stamped `owner: init` (the BIRTH sentinel: the bootstrap wrote it, nobody "
                f"reviewed it) over a section this project DECLARES. Ratify each — `bin/yitc-v2 -C . init "
                f"--adopt-concern <concern>:adopt:<owner>` — or waive the section if the mechanism is not "
                f"truly adopted (SPEC-0143 Rule 2). Report-only (SPEC-0119 rule 13).")
    # SECURITY-GATE-OVERRIDE view (SPEC-0119 rule 14 / SPEC-0155 rule 7, T-10502): the OPTIONAL injected
    # collaborator returns {count, window_days, overrides} — governed deploys that OVERRODE a REJECTING
    # pre-deploy security gate inside the window. UNFLOORED: unlike a followup backlog, ONE deliberate gate
    # bypass must never be count-hidden — an override nobody reads back is indistinguishable from a gate
    # quietly switched off, and the findings it bypassed are still live in production. Report-only,
    # suppressed-when-clean (a repo that never overrode the gate → 0 → silent), NEVER gates. The line names
    # the FIX (the findings are still open) and the meta-signal: a REPEATING override means the blocking
    # rule, not the deploy, is what needs changing.
    if _security_gate_overrides is not None:
        _go = _security_gate_overrides() or {}
        go = _n(_go.get("count")) if isinstance(_go, dict) else None
        if go and go > 0:
            _adv = sorted({str(a) for o in (_go.get("overrides") or [])
                           if isinstance(o, dict) for a in (o.get("advisories") or [])})
            _CAP = 4
            _named = (" — " + ", ".join(_adv[:_CAP]) +
                      (f" +{len(_adv) - _CAP} more" if len(_adv) > _CAP else "")) if _adv else ""
            lines.append(
                f"debt: {go} security-gate override(s) in the last {_go.get('window_days')}d{_named} — a "
                f"REJECTING pre-deploy gate was owner-overridden (SPEC-0155 rule 7) and the bypassed "
                f"finding(s) are still OPEN in the deployed code: fix each (or record an accepted-risk "
                f"waiver with an expiry) + re-run the security producer. A REPEATING override means the "
                f"BLOCKING RULE needs the change, not the deploy. Report-only (SPEC-0119 rule 14).")
    # LATE-FINDINGS view (SPEC-0204 rule 8 / SPEC-0119, T-12288): the OPTIONAL injected collaborator
    # returns {count, passes, window_days, findings} — defects the auditor raised at a pass >= 2 as
    # `pre-existing-in-subject`, i.e. ones its own pass-1 survey missed. UNFLOORED, like the
    # gate-override line above and for the same reason: each one is an un-adjudicated defect that
    # BLOCKS its card's closure until a `ceiling_decision` is recorded, so a single one is worth
    # naming and count-hiding it would hide a closure blocker. Report-only, suppressed-when-clean
    # (a repo whose audits surface nothing late → 0 → silent), NEVER gates — owner ruling D8 settled
    # that the auditor's completeness is RECORDED, never a gate, and this is the recording read back.
    if _late_findings is not None:
        _lf = _late_findings() or {}
        lf = _n(_lf.get("count")) if isinstance(_lf, dict) else None
        if lf and lf > 0:
            _tasks = sorted({str(f.get("task")) for f in (_lf.get("findings") or [])
                             if isinstance(f, dict) and f.get("task")})
            _CAP = 4
            _named = (" — " + ", ".join(_tasks[:_CAP]) +
                      (f" +{len(_tasks) - _CAP} more" if len(_tasks) > _CAP else "")) if _tasks else ""
            lines.append(
                f"debt: {lf} late audit finding(s) across {_n(_lf.get('passes')) or 0} pass(es) in the "
                f"last {_lf.get('window_days')}d{_named} — raised at a pass >= 2 with `causality: "
                f"pre-existing-in-subject`, so the pass-1 whole-subject survey MISSED them (SPEC-0204 "
                f"rule 8). Each was recorded and drove NO verdict, and each BLOCKS its card's "
                f"`task close` until `yitc-v2 audit decide` records fix/accept/defer. A rising count "
                f"on one stage means the pass-1 PACKET needs the change, not the auditor. "
                f"Report-only (SPEC-0119).")
    # REVIEW-DUE view (SPEC-0119 / T-10134): the OPTIONAL injected activity-gated periodic-review
    # semaphore (views._view_review_due). Same discipline as the views above — report-only,
    # suppressed-when-clean, NEVER gates. Two token-frugal lines (count + oldest, never review content):
    # the weekly operational-hygiene sweep and/or the N due T1-T10 system-inspection themes.
    if _review_due is not None:
        _rd = _review_due() or {}
        if isinstance(_rd, dict) and _n(_rd.get("count")):
            # T-10134 audit-post AC4 was COUNT + POINTER only (no theme ids/ages/content). T-10147
            # AMENDS it per owner directive 2026-07-05: name the due theme id(s) + label the tier so the
            # owner need not hand-compute WHICH review is due and of WHAT type — still NO ages or
            # per-theme review content (token-frugality held; SPEC-0119 rule 10 amended to match).
            if _rd.get("weekly_due"):
                lines.append(
                    "review-due: the WEEKLY operational-hygiene review (weekly tier) is due — run the "
                    "weekly sweep, then record `bin/yitc-v2 inspect record --tier weekly`. Activity-gated, "
                    "report-only (SPEC-0119 / SPEC-0057 §9).")
            _td = _rd.get("themes_due") or []
            _td_count = len(_td)
            if _td_count:
                _ids = [str(r.get("subject")) for r in _td if isinstance(r, dict) and r.get("subject")]
                _CAP = 6
                _named = (" — " + ", ".join(_ids[:_CAP]) +
                          (f" +{len(_ids) - _CAP} more" if len(_ids) > _CAP else "")) if _ids else ""
                # T-10238: the tier word is DERIVED from the due set, not hardcoded — a consumer's
                # declared theme carries its own cadence (weekly|monthly|quarterly), so a mixed set must
                # not be mislabelled "monthly". A label-less entry reads as monthly (the kernel roster's
                # tier — the T-10147 render contract, unchanged for a roster-only due set).
                _cads = {str(r.get("cadence") or "monthly") for r in _td if isinstance(r, dict)}
                _tier_word = _cads.pop() if len(_cads) == 1 else "mixed-cadence"
                # The pointer stays SUBJECT-NEUTRAL (`<theme>`, not the kernel-only `T<n>` placeholder):
                # a due subject may be a consumer-declared slug, and `inspect record --theme` takes both.
                lines.append(
                    f"review-due: {_td_count} {_tier_word} system-inspection theme(s) due for review"
                    f"{_named} — run per `bin/yitc-v2 inspect record --theme <theme>`. Activity-gated, "
                    f"report-only (SPEC-0057 §9).")
    # QUEUE-JUMP FIRING view (SPEC-0184 rule 9, T-11663): the OPTIONAL injected fold over the
    # journal — the marks that ACTUALLY REORDERED land admission (`debt.queue_jump_firings`). This
    # line IS safeguard (c): the mark buys a card an emergency place at the front of a SINGLE, SERIAL
    # slot, so overuse is a real cost paid by everybody else's land, and it must be visible without
    # anyone running an audit. Same discipline as every view here — derived, report-only,
    # suppressed-when-clean, NEVER gates. UNFLOORED (one card jumping the queue is worth seeing) but
    # WINDOWED, so the line decays into silence when the practice stops rather than standing forever.
    # A mark that never fired contributes NOTHING: the subject is the reordering, not the field.
    if _queue_jump_firings is not None:
        _qj = _queue_jump_firings() or {}
        qj = _n(_qj.get("count")) if isinstance(_qj, dict) else None
        if qj and qj > 0:
            _rows = _qj.get("firings") if isinstance(_qj.get("firings"), list) else []
            _cards = [str(r.get("task")) for r in _rows if isinstance(r, dict) and r.get("task")]
            _named = ", ".join(dict.fromkeys(_cards))
            lines.append(
                f"debt: {qj} queue-jump firing(s) in the last {_n(_qj.get('window_days')) or 14}d — "
                f"a card's opt-in `queue_jump` mark took the land-admission slot ahead of the cost "
                f"order (SPEC-0184 rule 9)"
                f"{': ' + _named if _named else ''}. Each firing is an emergency somebody declared; "
                f"a run of them means the queue itself needs fixing, not more marks. Clear a mark "
                f"whose blockage is gone with `bin/yitc-v2 task update <id> --queue-jump-clear`.")

    # WITHHELD TAIL-WRITE view (SPEC-0119 rule 42 / SPEC-0188 rule 7, T-12420): the OPTIONAL injected
    # fold over `land_tail_write_withheld`. A withheld write is INVISIBLE on its own — the land is
    # GREEN and the tree is exactly the verified one — so without this line an automatic writer that
    # its own readers keep rejecting would be silently disabled forever. Report-only, windowed,
    # suppressed-when-clean, NEVER gates: the withholding already happened, this is only its reading.
    if _tail_writes_withheld is not None:
        _tw = _tail_writes_withheld() or {}
        tw = _n(_tw.get("count")) if isinstance(_tw, dict) else None
        if tw and tw > 0:
            _by = _tw.get("writers") if isinstance(_tw.get("writers"), dict) else {}
            _named = ", ".join(f"{k} x{v}" for k, v in sorted(_by.items()))
            _last = _tw.get("latest") if isinstance(_tw.get("latest"), dict) else {}
            lines.append(
                f"debt: {tw} post-ff tail write(s) WITHHELD in the last "
                f"{_n(_tw.get('window_days')) or 7}d — a land's bookkeeping write could not prove "
                f"the tests that read it green, so it was restored instead of committed and `main` "
                f"stayed green (SPEC-0188 rule 7)"
                f"{': ' + _named if _named else ''}."
                + (f" Last: {_last.get('reason')}"
                   + (f" on {_last.get('test')}" if _last.get('test') else "") + "."
                   if _last else "")
                + " One withholding is a deferral the next land re-derives; a RUN of them means the "
                  "writer and its readers genuinely disagree — fix that, do not re-enable the write.")

    # LOAD-SENSITIVE LANE view (SPEC-0132 §3 as extended by T-12360): the OPTIONAL injected fold over
    # the declared load-sensitive carrier + the FIXED duration table (`debt.load_sensitive_lane`).
    # This is the SEQUENTIAL-TAIL reading the weekly review disposes against — the whole point of the
    # line is that the reviewer never has to compute the lane's wall by hand, which is the reason a
    # watch-point nobody is obliged to read had gone unread.
    #
    # UNLIKE ITS SUPPRESSED-WHEN-CLEAN SIBLINGS IT PRINTS UNDER BOUND TOO, and that asymmetry is
    # deliberate, not an oversight: a lane growing toward its bound is exactly what the review needs
    # to see BEFORE the crossing, and a number that appears only once the bound is passed gives the
    # reviewer no trajectory at all. What it never does is print for an EMPTY lane — with no listed
    # file there is nothing to dispose, so silence is the honest reading and the engine's own
    # zero-file state stays quiet. Report-only; it NEVER gates (CHARTER §6 fence).
    if _load_sensitive_lane is not None:
        _ls = _load_sensitive_lane() or {}
        _ls_count = _n(_ls.get("count")) if isinstance(_ls, dict) else None
        if _ls_count and _ls_count > 0:
            _crossed = [str(c) for c in (_ls.get("crossed") or [])]
            _bs, _bf = _ls.get("bound_share_pct"), _ls.get("bound_files")
            _which = {"share": f"share > {_bs}%", "files": f"count > {_bf}"}
            _mark = (" — OVER BOUND (" + ", ".join(_which.get(c, c) for c in _crossed) + ")"
                     if _crossed else "")
            _unrec = _n(_ls.get("unrecorded")) or 0
            lines.append(
                f"debt: load-sensitive lane — {_ls_count} file(s), {_ls.get('wall_s')}s serialized "
                f"tail = {_ls.get('share_pct')}% of the duration table's {_ls.get('suite_wall_s')}s "
                f"of per-file work (bounds: {_bs}% / {_bf} files){_mark}"
                f"{f'; {_unrec} listed file(s) carry no recorded duration and count as 0s' if _unrec else ''}. "
                f"The lane runs SERIALIZED after the pool on both legs, so this is wall a land pays "
                f"in sequence (SPEC-0132 §3, T-12358/T-12360). Past either bound the weekly review must "
                f"DISPOSE a named global-rework question — box-admission width / stage-6-beside-land "
                f"policy / harness isolation — with a dated line in `inspect record --tier weekly` "
                f"that either files that card or records why not plus a re-check date; another "
                f"per-file card is not a disposition. Report-only; nothing here acts.")

    # RESTORATION-PROPOSAL view (SPEC-0189 / T-11969): the OPTIONAL injected collaborator
    # `_restoration_proposals` (zero-arg, RETURNS `{count, proposals, …}` — see
    # `debt.restoration_proposals`), the fold over the concerns born PERMISSIVE whose named detector
    # has FIRED. One line per proposal, each naming the PROJECT, the SURFACE and the OBSERVED SIGNAL,
    # then the specific tightening proposed — never a bare "consider reviewing this" (SPEC-0189 rule 4).
    #
    # IT RIDES THIS ECHO RATHER THAN A SECOND ONE, which is the whole placement decision. A born-
    # permissive default's failure is silent by construction, so the restoring review is the entire
    # safety argument — and a review nobody reads is worse than none, because it is believed in. This
    # echo already has the two deterministic seams a controller reads before acting (session-start and
    # the on-demand re-fold) plus the land tail, so the proposal reaches a reader with no new seam, no
    # new store and no new schedule (CHARTER §P1 F1/F2).
    #
    # PROPOSE, NEVER APPLY (rule 4) — and the line SAYS so rather than leaving it to convention. Nothing
    # on this path writes a project's contract; restoration is an explicit project act.
    #
    # THE GROWTH READING RIDES ALONGSIDE AND DECIDES NOTHING (rule 3). It is rendered as a stated
    # RELEVANCE clause for the human weighing the proposal, and a proposal is emitted identically
    # whether the count is 500, 0, or missing entirely — a low-growth project still proposes. The clause
    # is built by a pure formatter whose only branch is over its own WORDING; the emit decision above it
    # never reads the number. Growth may gate relevance; it may never be the evidence that an absence is
    # costing anything.
    #
    # THE RENDERER RE-CHECKS EACH PROPOSAL AND DROPS AN INCOMPLETE ONE (SPEC-0189 §Verification R3 — "a
    # proposal assembled from a growth count alone is malformed: the renderer refuses to emit it"). The
    # assembler already refuses one, so this is the second, independent door: it holds even if a future
    # caller assembles proposals some other way, and it is what makes the rule a property of the RENDER
    # path rather than of one collaborator's care.
    #
    # Same discipline as every view above: report-only, suppressed-when-clean, NEVER gates. UNFLOORED —
    # one surface whose absence has started to cost something is exactly what this exists to name, and
    # count-hiding it would restore the silence the rule ends.
    if _restoration_proposals is not None:
        _rp = _restoration_proposals() or {}
        _rp_rows = _rp.get("proposals") if isinstance(_rp, dict) else None
        for _p in (_rp_rows if isinstance(_rp_rows, list) else []):
            if not isinstance(_p, dict):
                continue
            _proj = str(_p.get("project") or "").strip()
            _surf = str(_p.get("surface") or "").strip()
            _sig = str(_p.get("signal") or "").strip()
            if not (_proj and _surf and _sig):
                continue          # malformed — refused, never emitted (rule 3 / §Verification R3)
            _tighten = str(_p.get("tightening") or "").strip()
            _tclause = (f" Proposed tightening: {_tighten}."
                        if _tighten else
                        " No specific tightening was named by the detector — read the surface's own "
                        "spec before acting.")
            lines.append(
                f"debt: restoration proposal — project `{_proj}`, surface `{_surf}`: born PERMISSIVE, "
                f"and its detector has now observed a signal that the absence is costing something — "
                f"{_sig}.{_tclause}{_render_growth_relevance(_p.get('growth'))} PROPOSAL ONLY — "
                f"restoration is an explicit project act performed by the project in its own contract; "
                f"nothing here writes it (SPEC-0189 rule 4). Report-only, nothing gated.")

    # PROJECT GROWTH PROFILE line (SPEC-0198 / T-12080): the OPTIONAL injected collaborator
    # `_profile_line` (zero-arg, RETURNS the ONE rendered line or None — see `profile.echo_line`,
    # which the host feeds from `profile.resolve_profile`). Exactly the `_restoration_proposals`
    # shape above, for the same reason: a caller that does not inject it degrades to today's
    # behaviour rather than losing a line it never knew about.
    #
    # IT RIDES THIS ECHO RATHER THAN A SEAM OF ITS OWN, which is the whole placement decision and
    # the reason this card needed no new surface. SPEC-0198 rule 5 confines resolution to verbs that
    # are ALREADY RUNNING; this echo is fed from ONE host residue that serves all three of them —
    # session start, the land tail, and the on-demand `bin/yitc-v2 debt` re-fold — so one wiring
    # site makes the profile readable at every seam, with no new store, event, schedule or gate.
    #
    # THE LINE IS BUILT UPSTREAM, NOT HERE. This block renders what it is handed and derives nothing
    # — SPEC-0198 rule 3 puts the whole derivation in one library, and a formatter that reached into
    # the dimensions to decide something would be the second derivation site the AC2 tripwire exists
    # to catch. Hence a str-or-None collaborator rather than the dict every sibling above takes.
    #
    # SUPPRESSION is the collaborator's own call (it returns None when the profile is entirely
    # unknown AND no lens activates), so the suppressed-when-clean discipline is decided once,
    # beside the profile, rather than re-derived from a rendered string here.
    #
    # Report-only, like every view above: it NEVER gates, blocks, files or auto-acts. Nothing in
    # this echo has ever caused a crossing to execute anything, and rule 5's fence keeps it that way.
    if _profile_line is not None:
        _pl = _profile_line()
        if isinstance(_pl, str) and _pl.strip():
            lines.append(_pl)

    # BROWNFIELD GAP REGISTER (SPEC-0119 rule 39 / SPEC-0198 rules 5+7, T-12085): the OPTIONAL
    # injected collaborator `_gap_register` (zero-arg, RETURNS `debt.profile_gap_register`'s dict).
    # Registered into this echo exactly as `_profile_line` above and `_restoration_proposals`
    # before it — an unwired caller degrades to today's behaviour instead of losing a line it never
    # knew about.
    #
    # ONE CAPPED LINE, NEVER ONE LINE PER ITEM, and that is the rule rather than a formatting
    # preference. A register renders the count plus the TOP TWO labels by `debt.gap_rank` and then
    # a pointer; a project with 20 gaps therefore costs the same two lines of the owner's attention
    # as a project with 3. An uncapped register is what made the design this rule replaces
    # unusable — it is the difference between a signal and a wall of text at every session start.
    #
    # THE ORDER IS THE FOLD'S, NEVER THIS FORMATTER'S. `top_labels` arrives already ranked, so the
    # writer's cap selection and this line's top-2 can never disagree about which gaps matter most
    # (the audit-pre finding this answers). This block renders what it is handed and derives nothing.
    #
    # SUPPRESSED-WHEN-CLEAN like every sibling: a count of 0 — which is every repo with no ops
    # carrier, including the engine kernel itself — prints nothing at all.
    #
    # Report-only, ALWAYS: it never gates, blocks, dispatches or auto-acts. The FILING half is the
    # host's, at the same seam; nothing in this formatter writes anything.
    if _gap_register is not None:
        _gr = _gap_register() or {}
        _gc = _n(_gr.get("count")) if isinstance(_gr, dict) else None
        if _gc and _gc > 0:
            _labels = [str(x) for x in (_gr.get("top_labels") or [])][:2]
            _named = "; ".join(_labels)
            _more = _gc - len(_labels)
            _overdue = _n(_gr.get("overdue")) or 0
            _od = (f" {_overdue} of them are past the {debt_mod_gap_window()}-day triage window."
                   if _overdue else "")
            lines.append(
                f"debt: {_gc} profile-required baseline item(s) this project does not meet — "
                f"{_named}{f' (+{_more} more)' if _more > 0 else ''}.{_od} Each is a followup you "
                f"close by ANSWERING its `yitc-ops.yaml` section (declare / adapt / waive / "
                f"out-of-scope) or by promoting it into a task. Read them with `bin/yitc-v2 "
                f"followup list`; the register is derived (SPEC-0119 rule 39 / SPEC-0198). "
                f"Report-only — nothing is gated, dispatched or deployed by it.")

    # PROOF-OBLIGATION view (SPEC-0149, T-10296): the OPTIONAL injected fold over the journal —
    # deploys whose STAMPED obligation window passed with no matching `deploy_recheck_completed`
    # (`debt.open_proof_obligations`). Same discipline as every view above: report-only,
    # count-derived, suppressed-when-clean, NEVER gates. UNFLOORED, like overdue-rechecks: a
    # deadline-triggered genuine past-due obligation is never count-hidden (SPEC-0119 §Print
    # discipline). A still-open window contributes nothing — only a PASSED deadline is debt, and
    # window-less history never enters the fold at all (the one-window rule, SPEC-0149 §1).
    if _proof_obligations is not None:
        _po = _proof_obligations() or {}
        po = _n(_po.get("count")) if isinstance(_po, dict) else None
        if po and po > 0:
            lines.append(
                f"debt: {po} deploy(s) past their proof-obligation window — APPLIED but not PROVEN "
                f"(SPEC-0149). Run each delayed re-check / Class-S post-deploy assertion, then record "
                f"`bin/yitc-v2 event deploy_recheck_completed`. Where the window is too far gone for a "
                f"late re-check to mean anything, discharge it HONESTLY — `bin/yitc-v2 event "
                f"deploy_recheck_missed` with a stated judgement — never by emitting the recheck late. "
                f"See `bin/yitc-v2 debt`.")
        # THE MISS COUNT (T-11169, owner refinement (b)): a discharged miss leaves the line above, and
        # this is what keeps it from leaving the DATA. That windows are systematically not being met is
        # the most valuable signal in here, and it must not vanish with the obligation it silenced. Same
        # discipline as every line above — derived, report-only, suppressed-when-clean, never gates —
        # and windowed like the security-gate-override line (SPEC-0119 rule 14) so it decays into
        # silence when the pattern stops, rather than standing as a permanent monument nobody reads.
        _miss = _n(_po.get("missed_count")) if isinstance(_po, dict) else None
        if _miss and _miss > 0:
            _w = _n(_po.get("window_days")) or 30
            lines.append(
                f"debt: {_miss} deploy proof-obligation(s) closed as MISSED rather than PROVEN in the "
                f"last {_w}d (SPEC-0149). Each was discharged honestly with a stated judgement — but a "
                f"REPEATING miss says the window itself, not the deploy, is what needs the change. "
                f"Read them with `bin/yitc-v2 debt`.")
    # KNOWN-BROKEN-ON-MAIN view (SPEC-0119 rule 29 / SPEC-0181 §Known-broken-on-main, T-11468): the
    # OPTIONAL injected fold over the journal — tests a land's own attribution probe REPRODUCED at the
    # merge-base (main WITHOUT that branch's diff) with no later evidence of them passing there
    # (`debt.open_known_broken`). Same discipline as every view above: report-only, count-derived,
    # suppressed-when-clean, NEVER gates. UNFLOORED, like overdue-rechecks and proof-obligations: ONE
    # test broken on main blocks EVERY branch, so it is never count-hidden.
    #
    # THIS LINE IS THE POINT OF THE FOLD, not decoration on it. A record nobody can see is
    # indistinguishable from no record — the fold's whole value is that the SECOND branch to hit a
    # broken main learns it in a session-start line instead of paying a 420-570s verify to
    # rediscover what the first one already proved. It rides the one shared residue, so it reaches
    # all three debt seams (session-start, land-tail, the on-demand `debt` re-fold) at once.
    #
    # IT NAMES A CAUSE; IT NEVER EXCUSES ONE. Nothing here waives a gate, skips an assertion or makes
    # a land pass — the same bound the attribution record it reads was built under. A reader who took
    # this line as licence to bypass would turn the one mechanism that makes a broken main cheap to
    # DIAGNOSE into one that makes it cheap to IGNORE.
    if _known_broken is not None:
        _kb = _known_broken() or {}
        kb = _n(_kb.get("count")) if isinstance(_kb, dict) else None
        if kb and kb > 0:
            _rows = [r for r in (_kb.get("broken") or []) if isinstance(r, dict)][:3]
            _named = ", ".join(f"{r.get('file')} (since {str(r.get('since'))[:10]})" for r in _rows)
            _more = f" (+{kb - len(_rows)} more)" if kb > len(_rows) else ""
            lines.append(
                f"debt: {kb} test(s) KNOWN BROKEN ON MAIN — {_named}{_more}. Each was RE-RUN at the "
                f"merge-base by a land's own attribution probe and failed there too, so it is not any "
                f"one branch's: every branch that lands pays a full verify to rediscover it. Fix it "
                f"ON MAIN (or wait for the fix to land) — this line NEVER waives a gate or excuses a "
                f"red land. It clears when a land runs that test on a fresh main and it PASSES, never "
                f"by time (SPEC-0181). See `bin/yitc-v2 debt`.")
        # VACATED — the honest third disposition, and it is reported rather than dropped for the same
        # reason the miss count above is: a record silenced because its test FILE disappeared from the
        # tree that ran green is a different fact from one silenced by a pass, and a reader who cannot
        # tell them apart is being told the suite proved something it never executed.
        _vac = _n(_kb.get("vacated_count")) if isinstance(_kb, dict) else None
        if _vac and _vac > 0:
            lines.append(
                f"debt: {_vac} known-broken-on-main record(s) VACATED — the test file was absent from "
                f"the tree of the green land that would otherwise have cleared them, so they were "
                f"NOT proven to pass; the test was deleted or renamed while broken (SPEC-0181). Read "
                f"them with `bin/yitc-v2 debt`.")
    # PRE-QUEUE KNOWN-BROKEN REFUSAL view (SPEC-0119 rule 33 / T-11799): the OPTIONAL injected
    # WINDOWED fold over the journal — lands REFUSED before the queue because main was already known
    # broken (`debt.prequeue_known_broken_refusals`). Same discipline as every view above:
    # report-only, count-derived, suppressed-when-clean, NEVER gates.
    #
    # IT IS THE SIBLING OF THE RULE-29 LINE ABOVE, NOT A SECOND SPELLING OF IT. Rule 29 answers "what
    # is broken on main"; this answers "what did that cost, and who was stopped by it" — two facts
    # that move independently: a record can stand all day refusing nobody, and a burst of refusals
    # can be the whole story of a morning that produced no rows of its own. Before this, the second
    # question had no answer at all — the rule-27 abort-cost views count lands that reached a verify,
    # and a pre-queue refusal reaches none, so the cheapest refusal in the system was the one
    # invisible in the very statistics used to reason about land cost.
    #
    # WINDOWED so it DECAYS INTO SILENCE once the refusals stop (the rule-14 / rule-27 discipline),
    # rather than standing as a permanent monument to a main that was fixed weeks ago.
    #
    # IT NAMES A COST; IT NEVER EXCUSES ONE. Nothing here waives a gate, retries a land or re-queues
    # anything — and deliberately so: whether a refused land should be resumed at all, and by whom,
    # is a separate question this line does not answer and must not appear to.
    # SEAM READ AMPLIFICATION view (SPEC-0119 rule 37 / SPEC-0190 rule 10, T-12037): the OPTIONAL
    # injected windowed fold over the JOURNAL — which verb PHYSICALLY read more of the corpus than
    # the corpus it composed (`debt.seam_read_amplification`)? Same discipline as every view above:
    # report-only, derived, suppressed-when-clean, ZERO stored state, NEVER gates.
    #
    # WHY IT IS A LINE AT ALL, which is the same reason its three siblings are. Since T-12034 every
    # verb has recorded what it physically read — folds against segments, parsed rows against real
    # rows, card parses against real cards — onto the `cli_invoked` row it already emits, and NOTHING
    # read any of it back. That silence is not hypothetical: T-12029's session start ran 383 s, of
    # which 378 s was ~20 whole-corpus passes, and it was found by a human waiting rather than by an
    # instrument. Rule 10 makes the NEXT such seam a test failure; this line makes the CURRENT one
    # visible at the three moments a controller already reads before acting.
    #
    # IT NAMES A COST AND PROPOSES NO CACHE. The remedy it points at is the seam's ONE request-scoped
    # ReadScope at its wiring site, or a narrower horizon/slice. A cache bolted onto a view inside a
    # composed seam is a proposal to SKIP rule 10 — N caches have N invalidation stories and leave the
    # composition itself unmeasured — so this line must never appear to suggest one.
    if _seam_read_amplification is not None:
        _sr = _seam_read_amplification() or {}
        sr = _n(_sr.get("count")) if isinstance(_sr, dict) else None
        if sr and sr > 0:
            _seams = [s for s in (_sr.get("seams") or []) if isinstance(s, dict)]
            _w = _sr.get("worst") if isinstance(_sr.get("worst"), dict) else (_seams[0] if _seams else {})
            _named = _seams[:3]
            _more = f" (+{len(_seams) - len(_named)} more)" if len(_seams) > len(_named) else ""
            _fixes = [f for f in (_sr.get("instance_fixes") or []) if isinstance(f, dict)]
            lines.append(
                f"debt: {sr} seam(s) READ MORE THAN THEY COMPOSED in the last "
                f"{_n(_sr.get('window_days')) or 7}d — worst: "
                f"`{_w.get('verb')}` in {_w.get('project')} at {_w.get('ratio')}x "
                f"({_w.get('axis')}, over a bound of {_w.get('bound')})"
                + ("; also " + ", ".join(f"`{s.get('verb')}` {s.get('ratio')}x"
                                         for s in _named if s is not _w) if len(_named) > 1 else "")
                + _more
                + ("; BLOCKING — a seam a human waits on is reading the corpus more than twice"
                   if any(s.get("blocking") for s in _seams) else "")
                + (f"; {len(_fixes)} card(s) closed in the window declared a touch of the debt/echo "
                   f"view surface while that stood — "
                   f"{', '.join(f.get('task') for f in _fixes[:3] if f.get('task'))}"
                   f"{f' (+{len(_fixes) - 3} more)' if len(_fixes) > 3 else ''}. That is a JOIN, not a "
                   f"verdict: it says work was landing ON this surface while it was over bound, not "
                   f"that each card was an amplification fix. Read it for the SHAPE — a class paid off "
                   f"one instance at a time needs a rule, not another instance (roster T5)"
                   if _fixes else "")
                + f". The remedy is the seam's ONE request-scoped ReadScope at its WIRING SITE, or a "
                  f"narrower horizon/slice — NEVER another per-view cache, which is a proposal to skip "
                  f"the rule this line reports (SPEC-0190 rule 10 / SPEC-0119 rule 37). A seam that "
                  f"genuinely cannot hold the bound declares it in `yitc-ops.yaml reads.exemptions[]` "
                  f"(seam + ratio_bound + reason + until, all four). Report-only: nothing here waives "
                  f"a gate or slows a verb. See `bin/yitc-v2 debt`.")
    # NIGHTLY VERDICT CHANGES view (SPEC-0119 rule 38 / SPEC-0105, T-12078): the OPTIONAL injected
    # fold over the last TWO `nightly_run_completed` rows (`debt.nightly_verdict_changes`) — what the
    # last nightly said that the night before it did not. Same discipline as every view above:
    # report-only, derived, suppressed-when-clean, ZERO stored state, NEVER gates.
    #
    # WHY IT IS A LINE AT ALL. The nightly has run daily and written one full per-project verdict row
    # per night, and until this card NOTHING read it back — a fleet-wide report reaching no seam a
    # session opens. It is the rules 29/30/33/37 silence again, on the largest payload of the four.
    #
    # WHY CHANGES RATHER THAN STATE, which is the part a reader must not mistake for a summary. The
    # row's own headline has read `projects_flagged=11/11` every night since 2026-08-31, because two
    # chronic conditions paint every project the same colour; re-printing the flag would re-print
    # that saturation and be skimmed. So the per-project line prints ONLY what MOVED, and the two
    # chronic conditions get a dated line each — count, the first night of the CURRENT spell, and a
    # NAMED remedy. Naming the remedy is the whole of it: neither remedy is run, scheduled or offered.
    if _nightly_verdict_changes is not None:
        _nv = _nightly_verdict_changes() or {}
        if isinstance(_nv, dict):
            _nights = _nv.get("nights") if isinstance(_nv.get("nights"), dict) else {}
            _prev_n, _last_n = (str(_nights.get("previous") or "")[:10],
                                str(_nights.get("latest") or "")[:10])
            for _proj in (_nv.get("projects") or []):
                if not isinstance(_proj, dict) or not _proj.get("flips"):
                    continue
                _fl = [f for f in _proj["flips"] if isinstance(f, dict)]
                lines.append(
                    f"debt: nightly CHANGED for {_proj.get('project')} — "
                    + ", ".join(f"{f.get('check')} {f.get('from')}→{f.get('to')}" for f in _fl)
                    + f" (vs the previous night, {_prev_n} → {_last_n}). The nightly row said this "
                      f"and nothing read it: only what MOVED is printed, because the run flag itself "
                      f"has been saturated by two chronic conditions and says the same thing every "
                      f"night. A check that reported on only ONE of the two nights is a schema "
                      f"change, not a flip, and is not listed. Report-only: nothing here re-runs the "
                      f"nightly, waives a gate or moves an exit code (SPEC-0119 rule 38 / "
                      f"SPEC-0105). See `bin/yitc-v2 debt`.")
            for _ch in (_nv.get("chronic") or []):
                if not isinstance(_ch, dict) or not _ch.get("count"):
                    continue
                lines.append(
                    f"debt: nightly CHRONIC — `{_ch.get('check')}` = {_ch.get('verdict')} on "
                    f"{_ch.get('count')} project(s) every night since {str(_ch.get('since') or '')[:10]} "
                    f"({_ch.get('nights')} night(s) unbroken)"
                    + (f"; {_ch.get('detail')}" if _ch.get("detail") else "")
                    + f". It is EXCLUDED from the per-project change line above — a condition present "
                      f"every night contributes only noise to a differential — and dated here instead, "
                      f"so it reads as a standing debt with a first night rather than a permanent flag. "
                      f"Remedy: {_ch.get('remedy')}. This line NAMES that remedy and does not perform "
                      f"it; doing so is its own card. Report-only (SPEC-0119 rule 38 / SPEC-0105).")
    if _prequeue_known_broken_refusals is not None:
        # T-11841: the DEFAULT window is read from the fold's own constant, never re-typed here. A
        # fallback carrying its own copy of the number is a stale-number carrier by construction —
        # exactly the defect this rule's shrink retires — so a degraded render (an injected stub, a
        # malformed answer) still cannot disagree with the fold about what the window is. Lazy
        # `from lib import debt` is the idiom views.py already uses (P5 one-vocabulary), so this
        # borrows an existing seam rather than opening a new coupling style.
        from lib import debt as _debt_window                # the ONE window constant (P5)
        _pq_default_days = _debt_window.PREQUEUE_REFUSAL_WINDOW_DAYS
        _pq = _prequeue_known_broken_refusals() or {}
        pq = _n(_pq.get("count")) if isinstance(_pq, dict) else None
        if pq and pq > 0:
            _brs = [b for b in (_pq.get("branches") or []) if b][:3]
            _more = (f" (+{len(_pq.get('branches') or []) - len(_brs)} more)"
                     if len(_pq.get("branches") or []) > len(_brs) else "")
            _files = sorted({f for r in (_pq.get("refusals") or [])
                             if isinstance(r, dict) for f in (r.get("files") or [])})
            lines.append(
                f"debt: {pq} land(s) REFUSED BEFORE THE QUEUE in the last "
                f"{_n(_pq.get('window_days')) or _pq_default_days}d because main was already KNOWN BROKEN — "
                f"{', '.join(_brs) or 'branch unrecorded'}{_more}"
                + (f"; broken: {', '.join(_files[:2])}" if _files else "")
                + f". Each was refused in seconds having taken NOTHING — no reservation, no verify "
                  f"slot, no batch membership — which is the mechanism working, and is exactly why "
                  f"it was previously counted nowhere. The count is of REFUSALS, not of branches: a "
                  f"branch refused repeatedly is a freeze, not a statistic. This line makes them "
                  f"VISIBLE; it resumes NOTHING, waives no gate and excuses no red (SPEC-0181 / "
                  f"SPEC-0119 rule 33). The remedy is the same one the known-broken line names — fix "
                  f"the named test ON MAIN. See `bin/yitc-v2 debt`.")
    # ROLLED-BACK AFFECTED-TEST SELECTION view (SPEC-0119 rule 30 / SPEC-0181, T-11486): the OPTIONAL
    # injected fold over the JOURNAL — has the auto-rollback taken governing affected-test selection
    # OFF (`debt.selection_rollback`)? Same discipline as every view above: report-only, derived,
    # suppressed-when-clean, NEVER gates. UNFLOORED, and there is nothing to floor: the fold is a
    # BOOLEAN state, not a count of instances.
    #
    # WHY IT IS A LINE AT ALL. Before this, a firing was recorded in
    # `land_completed.verify_metrics.selection_govern_reason` and read by nobody. From outside it
    # showed up only as lands getting slower — indistinguishable from host load or a long admission
    # queue — so the safety valve built to catch silent test loss was itself silent. This is its ONE
    # reading moment; the owner accepted (2026-08-23, option B of four) that a firing is learned at
    # the NEXT SESSION START rather than at the moment of firing, which is why there is no land-tail
    # line and no new event.
    #
    # THE LINE TELLS THE READER WHAT TO DO, not merely that something happened. It names the recorded
    # count against the threshold, says the counter does NOT self-clear (so this is a mechanism
    # switched off, not a temporary revert), and names the rule-version bump as the route back to
    # governing. A line reading only "selection is off" would pass any presence check and still leave
    # its reader stuck.
    #
    # BOTH NUMBERS COME FROM THE GOVERNOR'S OWN TOKEN, never restated here — the fold reads them back
    # out of `miss-threshold:<n>/<t>`, so this view cannot drift from the rule it reports on. It
    # neither reads nor moves the threshold: `_SELECTION_MISS_THRESHOLD` is out of scope by the same
    # owner ruling.
    if _selection_rollback is not None:
        _sr = _selection_rollback() or {}
        if isinstance(_sr, dict) and _sr.get("rolled_back"):
            _m, _t = _n(_sr.get("misses")), _n(_sr.get("threshold"))
            lines.append(
                f"debt: governing affected-test selection is ROLLED BACK — {_m} recorded "
                f"disagreement(s) against a threshold of {_t}, so every land now runs the FULL suite "
                f"(SPEC-0181). This is not a slow patch and it does NOT self-clear: the counter only "
                f"ever grows under the rule version in force, so selection stays off until someone "
                f"acts. The route back to governing is to FIX the coverage map that let a failing "
                f"test be omitted and then BUMP `_SELECTION_RULE_VERSION` in `bin/lib/worktree.py`, "
                f"which opens a fresh window — never to raise the threshold. Read the disagreeing "
                f"lands with `bin/yitc-v2 journal query --type land_completed`. Report-only, nothing "
                f"gated (SPEC-0119 rule 30).")
    # UNCARRIED P8 ADOPTION-WARN view (SPEC-0119 rule 31, T-11563): the OPTIONAL injected fold over
    # the journal — `class: infra` closures whose CHARTER §P8 adoption WARN fired
    # (`task_closed.adoption_evidence_seen: false`) and which NOTHING declares a carrier for. Same
    # discipline as every view above: report-only, count-derived, suppressed-when-clean, NEVER gates.
    #
    # WHY IT IS A LINE AT ALL. The E-0005 WARN is NON-BLOCKING BY DESIGN — semantic adoption evidence
    # cannot be a false-positive-free hard gate — so before this it was one line on a closing
    # session's stdout and then nothing held it. Two infra closures went out that way in two days
    # (T-11442, T-11473) with no followup, no post-ship observation and no armed waiter between them.
    # This is the WARN's reading moment, not a second WARN: nothing here gates a close, re-opens a
    # card or moves an exit code, and the close-time WARN is exactly as non-blocking as it was.
    #
    # THE LINE NAMES THE CARRIER FORM, which is the half that makes it actionable. A reader told only
    # "3 closures are uncarried" has to go find out what a carrier IS; the remedy prints the exact
    # `P8-CARRIER: <task-id>` marker the fold reads, so the fix is one command away at the one moment
    # it is needed. `relates_to` is deliberately NOT the key (see the fold) — a carrier is DECLARED.
    if _uncarried_p8 is not None:
        _up = _uncarried_p8() or {}
        up = _n(_up.get("count")) if isinstance(_up, dict) else None
        if up and up > 0:
            _rows = [r for r in (_up.get("rows") or []) if isinstance(r, dict)][:3]

            def _entry(r) -> str:
                # T-12003 — NAME WHY, not only THAT. A row whose task DID carry a later P8 event
                # that the close-time contract rejected reads identically, until here, to one that
                # carried nothing: the author who did the work saw the same bare id as the author
                # who did not (measured on kupiclub 2026-09-02 — two genuine task-tied
                # live_trigger_evidence rows whose differential was PROSE under keys the contract
                # does not read). The reason is the fold's, never composed here.
                _e = f"{r.get('task_id')} (closed {str(r.get('closed_at'))[:10]}"
                _why = r.get("unproved_reason")
                _e += f"; a later P8 event did NOT count: {_why}" if isinstance(_why, str) and _why.strip() else ""
                return _e + ")"

            _named = ", ".join(_entry(r) for r in _rows)
            _more = f" (+{up - len(_rows)} more)" if up > len(_rows) else ""
            _w = _n(_up.get("window_hours")) or 168
            lines.append(
                f"debt: {up} infra closure(s) in the last {_w}h fired the CHARTER §P8 adoption WARN "
                f"with NOTHING holding it — {_named}{_more}. The WARN is non-blocking by design "
                f"(E-0005), so unless something carries the obligation it was the LAST anyone heard "
                f"of it. Discharge each by recording the adoption evidence — a "
                f"consumer_read_evidence/live_trigger_evidence event whose `data` carries BOTH "
                f"`failing_input` (the input that must make the claim FAIL) and `evidence_events` "
                f"(refs to journal rows the MECHANISM emitted, at least one resolving); a payload "
                f"that names its differential in prose under other keys does NOT read as adoption "
                f"and will not clear the row (the closure contract is SPEC-0015). "
                # T-12021 (X-1245) — THE REMEDY NOW SPELLS THE GRAMMAR IT PRESCRIBES. This sentence
                # said "refs to journal rows the MECHANISM emitted" and stopped, so an author who had
                # just read CHARTER §Principle 2 wrote its `events.jsonl#ts=<ISO>` locator and burned
                # two emissions before finding the real grammar in `task.py`. The string is CONSUMED
                # from its single-SoT home (never respelled here, or this line and the E-0005 WARN
                # would drift apart again) and rendered ONCE per line, not per row — the per-card
                # `unproved_reason` above stays short.
                f"{_ref_grammar()} "
                f"Or give it a carrier: "
                f"`bin/yitc-v2 followup add --text 'P8-CARRIER: T-XXXX <what is owed and what "
                f"fires it>' --relates-to T-XXXX` (add `--trigger` AND `--awaits T-NNNN` together — "
                f"only a named artifact can fire it). The marker is what this view reads — `relates_to` "
                f"alone is provenance and does NOT carry. Report-only, nothing gated "
                f"(SPEC-0119 rule 31).")
    # SECURITY-FINDINGS view (SPEC-0119 rule 11, T-10440 / X-0306 half 1): the OPTIONAL injected fold
    # over the repo's security-audit report series — sub-critical (warning/info) findings OPEN in the
    # LATEST report past the AGE floor. Same discipline as every view above: report-only,
    # suppressed-when-clean, NEVER gates. The line names the OLDEST finding's age, because the age IS
    # the signal here (a warning open since April is a different fact from one open since Tuesday), and
    # a bare count would leave the owner to go dig it out of a gitignored file.
    if _security_findings is not None:
        _sf = _security_findings() or {}
        sf = _n(_sf.get("count")) if isinstance(_sf, dict) else None
        # T-10843: a BROKEN authority is its own debt line, fired on the DEGRADE and not on the count —
        # otherwise suppressed-when-clean swallows it, and an unreadable latest report (the fold's own
        # sole authority on OPEN) renders exactly like a repo with nothing owed. Same named-degrade shape
        # as the rule-23 live-revision adapter: report the degrade, keep the best baseline, never gate.
        _degrade = _sf.get("authority_degrade") if isinstance(_sf, dict) else None
        if isinstance(_degrade, str) and _degrade.strip():
            lines.append(
                f"debt: the sub-critical security-findings view could not read its authority — "
                f"{_degrade.strip()} (SPEC-0119 rule 11). Re-run `bin/security-audit`; until then this "
                f"view's count is INCOMPLETE, never clean. See `bin/yitc-v2 debt`.")
        if sf and sf > 0:
            _oldest = (_sf.get("findings") or [{}])[0]
            _age = _n(_oldest.get("age_days")) if isinstance(_oldest, dict) else None
            _oldest_clause = f" (oldest: {_age}d)" if _age else ""
            lines.append(
                f"debt: {sf} open sub-critical security finding(s) past the age floor{_oldest_clause} — "
                f"only CRITICAL findings reach the deploy gate, so these have no other reading moment "
                f"(SPEC-0119 rule 11). Fix each, or record an accepted risk with an expiry, then re-run "
                f"the security audit. See `bin/yitc-v2 debt`.")
    # UNMONITORED-DISPATCH view (SPEC-0119 rule 12, T-10471 / X-0336): the OPTIONAL injected fold over
    # the in-flight fleet — dispatched tasks flying past the age floor with NO journaled monitoring read
    # (`debt.unmonitored_dispatches`). Same discipline as every view above: report-only,
    # suppressed-when-clean, NEVER gates. UNFLOORED IN COUNT, like overdue-rechecks — the floor is an AGE
    # floor applied inside the fold, so one abandoned dispatch is never count-hidden. The line names the
    # oldest age (a worker unwatched for 4 hours is a different fact from one unwatched for 91 minutes)
    # and the REMEDY, and it states what the JOURNAL shows — "no journaled monitoring read" — never that
    # the controller failed to look: a hand read is real but leaves no trace, and the fix for both is the
    # same blessed watcher.
    if _unmonitored_dispatches is not None:
        _ud = _unmonitored_dispatches() or {}
        ud = _n(_ud.get("count")) if isinstance(_ud, dict) else None
        if ud and ud > 0:
            _oldest_d = (_ud.get("dispatches") or [{}])[0]
            _mins = _n(_oldest_d.get("age_minutes")) if isinstance(_oldest_d, dict) else None
            _oldest_clause = f" (oldest: {_mins}m)" if _mins else ""
            lines.append(
                f"debt: {ud} in-flight dispatch(es) with no journaled monitoring read{_oldest_clause} — "
                f"a dispatched worker sends NO completion notification, so nothing wakes you without an "
                f"armed watcher (SPEC-0119 rule 12). Arm it: `bin/yitc-v2 dispatch --watch --task "
                f"T-XXXX`. See `bin/yitc-v2 debt`.")
    # UNRESOLVED-WORKER-HALT view (SPEC-0119 rule 18, T-10858): the OPTIONAL injected fold over the
    # dispatch journal — halts whose CAUSE `journal._halt_resolution` has not recorded as cleared
    # (`debt.unresolved_worker_halts`). The sibling of rule 12 directly above, differing in its DROP
    # CRITERION: rule 12 is bounded by the wave window, this one by RESOLUTION — an unresolved halt
    # stays here however old it is, which is the whole rule. Same discipline as every view above:
    # report-only, suppressed-when-clean, NEVER gates, no age floor (age is REPORTED, never applied).
    # The line names the oldest halt by TASK ID, not just a count: the remedy is per-halt (re-dispatch /
    # resolve / close), and a bare number would leave the reader to go re-derive which worker it means —
    # which is the hand-reconstruction this row exists to end. The wording is TERMINAL-ATTENTION debt,
    # never fleet liveness: it says a worker STOPPED and nothing cleared its cause, and it claims
    # nothing about who is flying now (that is `--fleet-verdict`'s job, and widening it was rejected).
    if _unresolved_halts is not None:
        _uh = _unresolved_halts() or {}
        uh = _n(_uh.get("count")) if isinstance(_uh, dict) else None
        if uh and uh > 0:
            _oldest_h = (_uh.get("halts") or [{}])[0]
            _oldest_h = _oldest_h if isinstance(_oldest_h, dict) else {}
            _task = _oldest_h.get("task")
            _days = _n(_oldest_h.get("age_days"))
            _oldest_clause = ""
            if _task:
                _oldest_clause = (f" (oldest: {_task}, {_days}d)" if _days is not None
                                  else f" (oldest: {_task})")
            # T-11351 — THE ATTRIBUTION CLAUSE. The count and the oldest id are both true and neither is
            # attributable, so a controller could read its own stopped fleet as somebody else's (X-1014,
            # 2026-08-20: six halts, three of them the reader's own, unrecognised for half an hour).
            # Printed ONLY when the reading session was actually established (`attribution_known`) —
            # otherwise nothing was compared, and "0 of them are yours" would be a claim the fold never
            # made. It PRINTS AT ZERO on purpose: "none of these are yours" is the direct answer to the
            # question the incident asked, and suppressing it would leave the reader re-deriving by hand
            # exactly as before. Ids are named oldest-first (the remedy is per-halt), capped so one line
            # stays one line. The unattributable tail is stated whenever it exists, so a reader can never
            # infer that the remainder must be someone else's — an unjoinable halt belongs to nobody
            # here, and saying so is what keeps the attributed number honest.
            _att_clause = ""
            if _uh.get("attribution_known"):
                _mine = [h for h in (_uh.get("halts") or [])
                         if isinstance(h, dict) and h.get("by_this_session")]
                _m = len(_mine)
                _CAP = 3
                _ids = [str(h.get("task")) for h in _mine if h.get("task")][:_CAP]
                _id_clause = (" — " + ", ".join(_ids) +
                              (f" +{_m - len(_ids)} more" if _m > len(_ids) else "")) if _ids else ""
                _att_clause = f", {_m} of them dispatched by this session{_id_clause}"
                _unattr = _n(_uh.get("unattributable_count")) or 0
                if _unattr:
                    _att_clause += f"; {_unattr} with no resolvable dispatcher"
            lines.append(
                f"debt: {uh} worker halt(s) with no recorded resolution{_oldest_clause}"
                f"{_att_clause} — a dispatched "
                f"worker STOPPED and nothing on record has cleared its cause, so it is still awaiting a "
                f"terminal decision (SPEC-0119 rule 18). These do NOT age out: `--fleet-verdict` and the "
                f"rule-12 line both go quiet on a halt as it gets older, which is when it needs you "
                f"most. Read each with `bin/yitc-v2 journal query --dispatch-status --task T-XXXX`, then "
                f"re-dispatch / resolve / close the card. See `bin/yitc-v2 debt`.")
    # UNPROVEN-CHECKS view (SPEC-0156, T-10509): the OPTIONAL injected fold over this repo's ops carrier +
    # journal — declared kernel-graded checks with no recorded RED demonstration of their CURRENT
    # definition (`debt.unproven_checks`). Same discipline as every view above: report-only,
    # suppressed-when-clean, NEVER gates. UNFLOORED (a check never seen to fail is debt at count 1) and a
    # repo that declares no check — the engine kernel itself — folds to 0, so history is never
    # retro-charged. The line SPLITS the two states, because they call for different work: a `rewired`
    # check HAD a demonstration until its definition changed (so it names WHEN that proof went stale — the
    # only honest date here), while a `never` check was admitted on a promise. It names the checks
    # themselves, not just a count: the remedy is per-check, and a bare number would leave the owner to go
    # diff the carrier against the journal by hand.
    if _unproven_checks is not None:
        _uc = _unproven_checks() or {}
        uc = _n(_uc.get("count")) if isinstance(_uc, dict) else None
        if uc and uc > 0:
            _checks = [c for c in (_uc.get("checks") or []) if isinstance(c, dict)]
            _rewired = [c for c in _checks if c.get("state") == "rewired"]
            _stale_clause = ""
            if _rewired:
                _since = _rewired[0].get("superseded_at")
                _stale_clause = (f" ({len(_rewired)} REWIRED — the recorded demonstration proved a "
                                 f"definition that no longer exists"
                                 + (f", stale since {_since}" if _since else "") + ")")
            _CAP = 4
            _names = [str(c.get("check")) for c in _checks if c.get("check")]
            _named = (" — " + ", ".join(_names[:_CAP]) +
                      (f" +{len(_names) - _CAP} more" if len(_names) > _CAP else "")) if _names else ""
            # NEAR-MISS clause (T-11178 / X-0921): when a row WAS emitted for one of these checks and
            # did not count, say so and say WHY. Without it the line reads identically whether the
            # author emitted nothing or emitted something the fold rejected — and a reader who has just
            # emitted concludes the mechanism is broken, or that the check was cleared. The wording is
            # rendered by the fold (`debt._near_miss_clause`, ONE home); this seam only appends it, and
            # inherits suppressed-when-clean from the `uc > 0` guard it sits inside. Report-only.
            _near_miss = _uc.get("near_miss_clause") or ""
            lines.append(
                f"debt: {uc} declared check(s) admitted UNPROVEN{_stale_clause}{_named} — no recorded "
                f"failing demonstration, so nothing shows they can fail when their subject breaks "
                f"(SPEC-0156). Break each one's subject deliberately, watch it go RED, then record "
                f"`bin/yitc-v2 event check_admission_demonstrated`. See `bin/yitc-v2 debt`."
                f"{_near_miss}")
    # RUNTIME-DELIVERY view (SPEC-0119 rule 16, T-10511 / X-0370): the OPTIONAL injected fold over the
    # carrier + the repo's compose bind-mounts + the not-adopted view ALREADY computed above
    # (`debt.runtime_delivery_coherence`). It renders the REVERSE of the first line in this echo, so the two
    # readings must never print the same commits as the same debt: the not-adopted line says "shipped, not
    # yet live"; this one says "already live, never gated" — and only ONE of them is true for a given
    # project, decided by the DECLARED model. The two arms are deliberately worded apart, because they call
    # for different work: an UNDECLARED bypass is answered by declaring it (a carrier edit), while a
    # DECLARED bypassable model whose live revision has fallen behind main is answered by reconciling the
    # deploy record — or by closing the bypass. Report-only, suppressed-when-clean, UNFLOORED, never gates.
    # UNLIKE its zero-arg siblings this collaborator takes ONE argument — the not-adopted view already
    # computed at the top of this function. That is not a style break but the P5 contract: arm (b) IS a
    # re-reading of that view's delta, so handing it the existing derivation is what keeps ONE live-revision
    # source and ONE git ancestry walk (a zero-arg collaborator would have to re-derive both, and could then
    # disagree with the line printed 30 lines above it).
    if _runtime_delivery is not None:
        _rd = _runtime_delivery(_na_view) or {}
        rd = _n(_rd.get("count")) if isinstance(_rd, dict) else None
        _kind = _rd.get("kind") if isinstance(_rd, dict) else None
        if rd and rd > 0 and _kind == "undeclared-bypassable":
            _ev = [e for e in (_rd.get("evidence") or []) if isinstance(e, dict)]
            _named = _mount_clause(_ev)
            lines.append(
                f"debt: the deploy verb is BYPASSABLE here and nothing says so — this project's PRODUCTION "
                f"compose bind-mounts its own SOURCE into {rd} service(s){_named}, so a container recreate "
                f"ships `main` with no gate and no deploy_completed (X-0370: half a paired change shipped, "
                f"8h outage). DECLARE it in yitc-ops.yaml — `deploy.runtime_delivery.model:` source-mounted "
                f"| hot-reload | hybrid | image-baked — or waive it with a reason (SPEC-0093 rule 22). "
                f"Report-only (SPEC-0119 rule 16).")
        elif rd and rd > 0 and _kind == "live-without-deploy":
            _model = _rd.get("model") or "bypassable"
            lines.append(
                f"debt: {rd} commit(s) are ALREADY LIVE but passed NO deploy gate — this project declares "
                f"`runtime_delivery: {_model}`, so its runtime reads the source tree and these commits "
                f"reached prod without the deploy verb (no class check, no backup, no live probe, no "
                f"deploy_completed). They are NOT the 'not-adopted' debt above — that line's reading is "
                f"INVERTED here (X-0370). Reconcile with `bin/yitc-v2 deploy`, or close the bypass "
                f"(SPEC-0119 rule 16).")
        elif rd and rd > 0 and _kind == "unwaived-prod-mount":
            # T-10621 — the DECLARED-yet-unwaived arm (the runtime-delivery doctrine, T-10620). A bypassable
            # model whose executable-code mounts still sit in the PROD compose with no waiver: the doctrine's
            # bake / dev-split / waive prescription is unmet. Names the pattern doc + the dev/prod split, per
            # the card. Report-only, suppressed-when-clean; PROD-scoped so a dev-overlay mount is silent.
            _model = _rd.get("model") or "bypassable"
            _ev = [e for e in (_rd.get("evidence") or []) if isinstance(e, dict)]
            _named = _mount_clause(_ev)
            lines.append(
                f"debt: this project declares `runtime_delivery: {_model}` but its executable-code mounts sit "
                f"in the PROD compose with NO waiver{_named} — under the runtime-delivery doctrine (SPEC-0093 "
                f"rule 22, T-10620) image-baked is the normative prod default and a bypassable prod runtime is "
                f"a waiver-only exception (X-0370). Do the aiseller dev/prod compose SPLIT (source mounts → "
                f"`docker-compose.dev.yaml`), migrate to `image-baked`, or WAIVE it with its compensating "
                f"controls — see patterns/deploy-coherence.md. Report-only (SPEC-0119 rule 16).")
    # UNEXECUTED-TEST-CLASSES view (SPEC-0152 rule 24, T-10513 / X-0375): the OPTIONAL injected fold over
    # the carrier + journal — declared `tests.classes` with no recorded successful execution (`never`) or
    # one aged past the staleness floor (`stale`). The EXECUTION axis of the SPEC-0156 line above: a
    # demonstration proves a check CAN fail, this proves it has actually RUN. Same discipline as every view
    # above: report-only, suppressed-when-clean, NEVER gates. UNFLOORED (a class never seen to run is debt at
    # count 1); a repo that declares no class folds to 0 → suppressed, so history is never retro-charged. The
    # line SPLITS `never` from `stale` — they call for the same act (run it, record it) but a `stale` class
    # ran once and names WHEN, while a `never` class was declared and never seen to run at all. It names the
    # classes, not just a count: the remedy is per-class.
    if _unexecuted_test_classes is not None:
        _ut = _unexecuted_test_classes() or {}
        ut = _n(_ut.get("count")) if isinstance(_ut, dict) else None
        if ut and ut > 0:
            _cls = [c for c in (_ut.get("classes") or []) if isinstance(c, dict)]
            _stale = [c for c in _cls if c.get("state") == "stale"]
            _stale_clause = ""
            if _stale:
                _oldest = max((c.get("stale_days") for c in _stale
                               if isinstance(c.get("stale_days"), int)), default=None)
                _stale_clause = (f" ({len(_stale)} STALE — ran once but not since"
                                 + (f", oldest {_oldest}d" if _oldest is not None else "") + ")")
            _CAP = 4
            _names = [str(c.get("class")) for c in _cls if c.get("class")]
            _named = (" — " + ", ".join(_names[:_CAP]) +
                      (f" +{len(_names) - _CAP} more" if len(_names) > _CAP else "")) if _names else ""
            # The emit shape is named INLINE, not left to `bin/yitc-v2 debt` (X-0470 / T-10635): boomrocket
            # read this exact line, emitted `outcome: green` with `run:`, and the record was silently
            # dropped — the debt line did not move and nothing said why, so they read kernel source to
            # learn the contract. A remedy command whose payload is wrong is not a remedy.
            _nm = [n for n in (_ut.get("near_misses") or []) if isinstance(n, dict)] \
                if isinstance(_ut, dict) else []
            _nm_clause = ""
            if _nm:
                _nm_clause = (" SEEN BUT DID NOT CLEAR — " + "; ".join(
                    f"`{n.get('class')}` ({n.get('reason')})" for n in _nm if n.get("class")) +
                    ": the emit was journaled but records no run, so it cleared nothing — fix the payload "
                    "and re-emit.")
            lines.append(
                f"debt: {ut} declared test class(es) with NO recorded successful execution{_stale_clause}"
                f"{_named} — a class nobody ran is not coverage, it just catches nothing (X-0375: browsers "
                f"never installed, nothing ran, nothing failed). Run each for real, then record "
                f"`bin/yitc-v2 event test_class_executed --data "
                f"'{{\"class\":…,\"outcome\":\"pass\",\"evidence\":…}}'` naming the run — `outcome` must be "
                f"the literal `pass` (not `green`/`ok`) and `evidence` (a CI url / log ref) is REQUIRED; "
                f"any other payload clears nothing (SPEC-0152 rule 24).{_nm_clause} "
                f"See `bin/yitc-v2 debt`.")
    # UNDECLARED-SUBJECT-VERIFY-LAYERS view (SPEC-0152 rule 16 subject_globs / SPEC-0119, T-10575): the
    # OPTIONAL injected fold over the carrier — EXECUTABLE verify.layers with no `subject_globs:` yet. UNLIKE
    # every sibling above this is NOT owed debt: subject_globs is OPT-IN and fail-closed (absent → the layer
    # ALWAYS runs), so an un-scoped layer is the SAFE default. It is a ROLLOUT OPPORTUNITY nudge — declare a
    # layer's diff-subject and a disjoint diff REAL-skips its run and its prep at land, recording a {layer,
    # outcome: skipped-disjoint-subject} row (T-10573), trimming land time. Same
    # discipline as its siblings otherwise: report-only, suppressed-when-clean, UNFLOORED (an un-scoped layer
    # is a candidate at count 1), never gates. A repo with no executable layer (the engine kernel itself)
    # folds to 0 → suppressed, so history is never retro-charged. Names the layers, not a bare count: the
    # remedy is per-layer (audit each command, then declare its subject). The wording is deliberately an
    # invitation ("could be scoped"), never a violation — leaving a layer un-scoped is always safe.
    if _undeclared_subject_layers is not None:
        _sl = _undeclared_subject_layers() or {}
        sl = _n(_sl.get("count")) if isinstance(_sl, dict) else None
        if sl and sl > 0:
            _CAP = 4
            _names = [str(l) for l in (_sl.get("layers") or []) if l]
            _named = (" — " + ", ".join(_names[:_CAP]) +
                      (f" +{len(_names) - _CAP} more" if len(_names) > _CAP else "")) if _names else ""
            lines.append(
                f"debt: {sl} executable verify layer(s) not yet SUBJECT-SCOPED{_named} — each ALWAYS runs at "
                f"land, even on a diff it does not touch. subject_globs is opt-in and always safe to omit "
                f"(the layer just always runs), so this is an OPPORTUNITY not a defect: AUDIT each layer's "
                f"command (its file reads / mounts / sub-scripts, a SUPERSET of `covers:` — never a naive "
                f"covers-copy) and add `subject_globs: [<globs>]` in yitc-ops.yaml, so a disjoint diff "
                f"REAL-skips its run and its prep at land — recording a {{layer, outcome: skipped-disjoint-subject}} "
                f"row (SPEC-0152 rule 16 subject_globs; T-10573). See `bin/yitc-v2 debt`.")
    # UNEXECUTED-SUBJECT-FILES view (SPEC-0119 rule 35 / SPEC-0152 rule 16 subject_globs, T-11886): the
    # OPTIONAL injected fold over the carrier + the checkout — suite files INSIDE a declared
    # `subject_globs:` subject that NO executable layer's execution registry names. UNLIKE the two
    # siblings around it this IS owed work, not an opportunity: the two of them report a layer that runs
    # more often than it needs to (a cost), while this reports a file that is believed covered and is run
    # by NOTHING (the X-0860 false GREEN — kupiclub, 2026-08-13, where `task test --run` printed PASS over
    # two such files and four mutation-verified tripwires shipped believing they were gated).
    #
    # THE WORDING IS REGISTRY-BASED IN BOTH DIRECTIONS and must stay that way: the fold can prove that no
    # command NAMES the file, never that it was not executed — and equally, a clean read is not a proof
    # of execution (a comment or a dead branch can name a file that never runs). Rendering either half as
    # verified would launder the claim this line exists to expose.
    #
    # Same discipline as every sibling otherwise: report-only, suppressed-when-clean, UNFLOORED (one
    # unexecuted declared file is already the whole defect), never gates — nothing here reaches a `bad`
    # list or an exit status, so no consumer's PASS can become a FAIL through it (the card's AC3 rollout
    # order). Names the files, not a bare count: the remedy is per-file. A repo with no carrier (the
    # engine kernel itself) folds to 0 → suppressed, so history is never retro-charged.
    if _unexecuted_subject_files is not None:
        _us = _unexecuted_subject_files() or {}
        us = _n(_us.get("count")) if isinstance(_us, dict) else None
        if us and us > 0:
            _CAP = 4
            _files = [str(f) for f in (_us.get("files") or []) if f]
            _named = (" — " + ", ".join(_files[:_CAP]) +
                      (f" +{len(_files) - _CAP} more" if len(_files) > _CAP else "")) if _files else ""
            lines.append(
                f"debt: {us} suite file(s) inside a DECLARED `subject_globs:` subject that NO executable "
                f"verify layer's execution registry names{_named} — declared, therefore believed covered; "
                f"named by nothing, therefore run by nothing. That is the X-0860 shape: the verdict reads "
                f"PASS while the file's absence and its success are indistinguishable from outside. "
                f"Answer each: REGISTER it in the layer's command (or in a script that command runs), make "
                f"the layer DISCOVER its test directory so no file depends on being listed, or — if it is "
                f"genuinely not that layer's subject — NARROW `subject_globs:` in yitc-ops.yaml so the "
                f"declaration stops claiming it. Registry-based: this proves no command NAMES the file, "
                f"never that it did not run — and a clean read is likewise not proof that one did "
                f"(SPEC-0152 rule 16 subject_globs; SPEC-0119 rule 35). Report-only, no verdict changed. "
                f"See `bin/yitc-v2 debt`.")
    # ZERO-SKIP-VERIFY-LAYERS view (SPEC-0119 / SPEC-0152 rule 16 subject_globs, T-11080): the OPTIONAL
    # injected fold over the JOURNAL — the executable layers whose skip rate over the recent-lands window
    # is 0%, i.e. they ran on EVERY land. It is the OBSERVED counterpart of the carrier-read
    # `_undeclared_subject_layers` line directly above, and the overlap between them is deliberate and
    # bounded: that one asks "is a subject DECLARED?" (and a layer declaring a SUPERSET answers it while
    # still never skipping — the blind spot), this one asks "does it ever actually skip?". Same discipline
    # as every sibling: report-only, suppressed-when-clean, UNFLOORED at the LINE (the evidence floor
    # lives INSIDE the fold, where a thinly-observed layer is never scored at all), never gates. A repo
    # with no layered land — the engine kernel itself — folds to 0 → suppressed, so history is never
    # retro-charged. Names the layers with their observation counts, not a bare count: the remedy is
    # per-layer (audit that command's real reads, then narrow its subject), and the count is what makes
    # the claim checkable rather than asking the reader to trust it.
    if _zero_skip_layers is not None:
        _zs = _zero_skip_layers() or {}
        zs = _n(_zs.get("count")) if isinstance(_zs, dict) else None
        if zs and zs > 0:
            _CAP = 4
            _rows = [l for l in (_zs.get("layers") or []) if isinstance(l, dict) and l.get("layer")]
            _named = (" — " + ", ".join(f"{r.get('layer')} ({r.get('observations')} lands)"
                                        for r in _rows[:_CAP]) +
                      (f" +{len(_rows) - _CAP} more" if len(_rows) > _CAP else "")) if _rows else ""
            lines.append(
                f"debt: {zs} executable verify layer(s) NEVER SKIPPED over the last "
                f"{_zs.get('window_lands')} recorded land(s){_named} — a 0% skip rate means each runs on "
                f"EVERY land, so its `subject_globs:` are absent or declared WIDER than the layer's "
                f"command really covers. AUDIT each command's real reads (its files / mounts / "
                f"sub-scripts — a SUPERSET of `covers:`, never a naive covers-copy) and NARROW "
                f"`subject_globs:` in yitc-ops.yaml, so a disjoint diff REAL-skips its run and its prep "
                f"at land (SPEC-0152 rule 16 subject_globs; T-10573). Opt-in — always safe to leave as "
                f"is (the layer just always runs). See `bin/yitc-v2 debt`.")
        # RUN-LEVEL VERIFY SKIP RATE (T-11749, kupiclub X-1165 / X-1160): the same fold's `run_skip`
        # companion — the share of LANDS in the window that skipped at least one layer. It is rendered
        # here, beside the per-layer line, because it is a second reading of ONE fold: standing a
        # separate surface next to the view we already print is the duplication CHARTER P5 forbids, and
        # is the reason this ask resolved as an EXTENSION rather than a new seam.
        #
        # THIS IS THE ONE LINE IN THIS ECHO THAT IS NOT SUPPRESSED-WHEN-CLEAN, and that is the ask's one
        # stated requirement rather than an oversight. Every sibling here reports OWED WORK, so silence
        # means "nothing owed"; this reports a RATE, where silence and 0% are indistinguishable — and an
        # unwatched rate is exactly the failure that produced the ask (the reporter advised four peers to
        # narrow their globs, citing their own skip rate as the prize, while their own rate quietly
        # halved from 40% to 18% because nothing printed it). Our own graph-cache hit-rate line prints at
        # 0% for the identical reason: 1135 markers written, none read across 1390 lands, invisible until
        # someone went looking. It IS silent with no denominator — a window holding no land that recorded
        # a per-layer trail (this engine kernel) has taken no measurement, which is not a rate of zero,
        # and printing `0 of 0` on every land would train the reader to skip the line. Report-only: no
        # gate, no threshold, no alert (all three explicitly out of the ask's scope).
        _rs = _zs.get("run_skip") if isinstance(_zs, dict) else None
        _rs_lands = _n(_rs.get("lands")) if isinstance(_rs, dict) else None
        if _rs_lands and _rs_lands > 0:
            lines.append(
                f"debt: run-level verify skip rate {_rs.get('rate_pct')}% over the last {_rs_lands} "
                f"recorded land(s) — {_n(_rs.get('skipped')) or 0} of {_rs_lands} skipped at least one "
                f"verify layer. This is the share of LANDS that got to skip anything, which the "
                f"per-layer line beside it cannot state: layer-by-layer answers can all look fine while "
                f"this halves underneath them as `subject_globs:` widen (each widening buys a little "
                f"coverage and charges EVERY future land the whole layer). Report-only — no gate, no "
                f"threshold; printed even at 0% so a dead view and a working one never look alike. "
                f"See `bin/yitc-v2 debt`.")
    # SLOWEST-TEST-FILE-CHANGES view (SPEC-0119 rule 19, T-11125): the OPTIONAL injected fold over the
    # JOURNAL — what MOVED in the recorded slowest test files (T-11124's per-file duration series)
    # between the latest land and the median of the previous window. It reports the DELTA and NEVER the
    # level, which is the entire design: a slowest set exists by definition, so a line that printed the
    # set itself would print on every land and train its reader to skip it — the same silent failure by
    # another route as having no surface at all. Suppressed-when-clean is therefore load-bearing here,
    # not polish. UNFLOORED at the LINE: the evidence floor lives INSIDE the fold, where a series too
    # short to have a "previous state" is not scored at all (so a freshly-started series says nothing).
    # Each item is named WITH ITS KIND, because NEW and GREW are different readings with different
    # responses, and a bare count would leave the reader to diff the journal by hand. Report-only,
    # never a gate — nothing here is optimised, blocked, or measured against any absolute bar.
    if _slowest_decile_changes is not None:
        _sd = _slowest_decile_changes() or {}
        sd = _n(_sd.get("count")) if isinstance(_sd, dict) else None
        if sd and sd > 0:
            _CAP = 4
            _new = [e for e in (_sd.get("entrants") or []) if isinstance(e, dict) and e.get("file")]
            _grew = [g for g in (_sd.get("grown") or []) if isinstance(g, dict) and g.get("file")]

            def _secs(ms):
                try:
                    return f"{int(ms) / 1000.0:.1f}s"
                except (TypeError, ValueError):
                    return "?"

            _items = ([f"NEW {e['file']} ({_secs(e.get('wall_ms'))})" for e in _new] +
                      [f"GREW {g['file']} {_secs(g.get('baseline_ms'))}->{_secs(g.get('wall_ms'))} "
                       f"(+{g.get('growth_pct')}%)" for g in _grew])
            _named = (" — " + ", ".join(_items[:_CAP]) +
                      (f" +{len(_items) - _CAP} more" if len(_items) > _CAP else "")) if _items else ""
            lines.append(
                f"debt: {sd} change(s) in the recorded SLOWEST test files vs the median of the previous "
                f"{_sd.get('window_lands')} land(s){_named} — a NEW entrant climbed into the recorded "
                f"slow tail, or a member GREW past both the relative and the absolute bar. This is the "
                f"DELTA, never the level: nothing prints while the tail is unchanged, and nothing here "
                f"is gated or optimised. Read the named file's recent change and either accept the cost "
                f"deliberately or file a card to bring it back down (T-11124's per-file series; "
                f"SPEC-0119 rule 19). See `bin/yitc-v2 debt`.")
    # ABORTED-LAND COST view (SPEC-0119 rule 27, T-11368 / kupiclub X-1036, corrected by X-1039): the
    # OPTIONAL injected fold over the JOURNAL — what the last window of ABORTED lands COST, split by
    # `abort_class`, with the aborts that PAID a full verify separated from those that refused EARLY.
    # It is the first line here whose subject is money ALREADY SPENT rather than work still pending:
    # every sibling reports something owed, and nothing reported what a project burned on runs that
    # shipped nothing (X-1036 — it surfaced only because an owner went looking).
    #
    # THE RENDER'S ONE HARD RULE, and it is why this block is shaped the way it is: there is NO single
    # headline number. A high `verify-failed` count is the gate EARNING ITS KEEP — a real defect caught
    # before it landed — and a line that summed caught defects together with paperwork refusals would
    # present the gate's best work as the project's worst waste, sending someone to weaken the very
    # thing that paid for itself. So RECLAIMABLE names the process-refusal group ALONE, gate-caught is
    # stated separately and explicitly as not-waste, and preflight-refused, inconclusive and early
    # each get their own clause. No two group totals are ever added together in this text.
    #
    # THE TREND IS PRINTED BESIDE EVERY NAMED CLASS, never left to the reader to infer, because the
    # requester's own correction (X-1039) is exactly the failure this prevents: most of the cost they
    # first attributed to one leg had already been removed by a ONE-LINE project declaration, and a
    # surface ranking by raw minutes would have sent someone to fix a cost that no longer existed. A
    # DECAYING class is therefore labelled in the text, at the same prominence as its minutes.
    #
    # Report-only, suppressed-when-clean, and clean here means "nothing cost anything worth reporting"
    # rather than "nothing aborted" — a window of instant `uncommitted-dirt` refusals prints nothing,
    # while the two early-but-expensive classes this repo measured (764 min/week) are never hidden.
    # T-11682 — the dead-land fold is now read by TWO arms (the abort-cost line below and the rule-23
    # line further down), so it is computed ONCE here rather than per-arm: it costs a `for-each-ref`
    # over the whole frontier plus a unioned journal read, and paying that twice at a session seam is
    # exactly the kind of quiet cost a report-only surface has no right to add. Guarded — a raising
    # fold degrades to an empty dict and BOTH arms then behave exactly as they did before this change.
    _dl_once: dict = {}
    if _dead_lands is not None:
        try:
            _dl_once = _dead_lands() or {}
        except Exception:  # noqa: BLE001 — a report-only view must never break the seam it rides
            _dl_once = {}
        if not isinstance(_dl_once, dict):
            _dl_once = {}

    if _aborted_land_cost is not None:
        _al = _aborted_land_cost() or {}
        alc = _n(_al.get("count")) if isinstance(_al, dict) else None
        # T-12396 — the park-limit EVICTIONS, read here so the block's ENTRY can account for them.
        # They are no longer in any abort figure this line prints (the fold drops them from the
        # population), so a window whose only aborts were evictions now folds to `count == 0` and
        # would print NOTHING — turning a cost that is visible today into a silence. That is the
        # disappearance the exclusion is explicitly not allowed to cause, so the block also opens on
        # an eviction alone. SUPPRESSION IS OTHERWISE UNTOUCHED: clean still means "nothing cost
        # anything worth reporting" and never "nothing aborted" (SPEC-0119 rule 27).
        # GUARDED ON `_al` ITSELF, not only on the field: the fold result is an INJECTED
        # collaborator and its degenerate shapes (a string, a partial dict, an older probe's
        # return) are exercised by the rule-27 suite. `alc` above takes the same precaution; a
        # bare `.get` here would raise inside a report-only render and break the seam it rides.
        _ev = _al.get("evicted") if isinstance(_al, dict) else None
        _ev = _ev if isinstance(_ev, dict) else {}
        _ev_n = _n(_ev.get("n")) or 0
        if (alc and alc > 0) or _ev_n:
            _CAP = 3               # top 3 named per group, then `+N more` — the sibling convention
            _groups = _al.get("groups") if isinstance(_al.get("groups"), dict) else {}
            _classes = [c for c in (_al.get("classes") or []) if isinstance(c, dict) and c.get("class")]

            def _grp(name):
                g = _groups.get(name) if isinstance(_groups.get(name), dict) else {}
                return _n(g.get("n")) or 0, g.get("minutes") or 0

            def _named_rows(rows, totals=None):
                # Delegates to the ONE module-level formatter above (T-11842 hoist) —
                # looked up on the module so a probe can swap in the pre-change replica.
                return _abort_named_rows(rows, totals, cap=_CAP)

            def _named(name):
                # Each class NAMED WITH ITS TREND: a bare minutes ranking is the reading X-1039
                # disproved, so the two are never separable in this text.
                return _named_rows([c for c in _classes if c.get("group") == name], _grp(name))

            _pr_n, _pr_m = _grp("process-refusal")
            _gc_n, _gc_m = _grp("gate-caught")
            _pf_n, _pf_m = _grp("preflight-refused")
            _ic_n, _ic_m = _grp("inconclusive")
            _ea_n, _ea_m = _grp("early")
            # T-11851 — THE HEADLINE NAMES THE POPULATION THE BUCKETS COVER. Until this card the
            # headline printed `count` — the aborts ABOVE the cost-reporting floor — while every
            # bucket clause beside it printed `n`, which covers the WHOLE window, and no clause
            # related the two. Measured on this repo 2026-08-30: headline 371, group counts summing
            # 501, and a trailing clause offering "130 FURTHER abort(s)" — so a reader who added
            # them computed 631, a quantity that does not exist, while one who trusted the headline
            # understated the window's aborts by 26%. Every number was individually correct; the
            # sentence containing them was not, and this is the view the corpus points operators at
            # to judge landing-pipeline health. So the headline is now the WINDOW TOTAL — what the
            # buckets sum to, by construction — with the reportable sub-count and its floor named
            # beside it, and the sub-floor clause below states INCLUSION rather than addition. It is
            # the same move the T-11514 coverage count ("N of M abort(s)") and the T-11607
            # gate-caught split already make: name the population a number is true of, never leave
            # it to be inferred.
            #
            # SUPPRESSION IS UNTOUCHED — still keyed on `count`, so CLEAN keeps meaning "nothing
            # cost anything worth reporting" and never "nothing aborted" (SPEC-0119 rule 27). And
            # this is NOT the cross-group sum the render's one hard rule forbids: that rule fences
            # MINUTES summed across never-summed groups and presented as waste; this is a COUNT of
            # the window's own population, stated as that.
            #
            # NEVER CLAIMED WITHOUT ITS PROOF: a result that does not carry a usable `aborts` (a
            # partial dict, an older probe) keeps the pre-change headline exactly and makes no
            # reconciling claim — a total we cannot prove is not asserted, the same never-fabricate
            # discipline the fold applies to an undetermined cost.
            _ab = _n(_al.get("aborts"))
            alc = alc or 0
            _hdr = _ab if (_ab is not None and _ab >= alc) else alc
            # T-12396 — a window whose aborts were ALL evictions has no aborted-land subject at all,
            # and printing "0 aborted land(s) ... cost wall-clock that shipped nothing" would assert
            # that emptiness as this line's finding. The line then OPENS with the eviction clause
            # instead; every other window keeps today's headline byte-for-byte.
            if _hdr:
                _line = (f"debt: {_hdr} aborted land(s) in the last {_al.get('window_days')} day(s) "
                         f"cost wall-clock that shipped nothing")
            else:
                _line = f"debt: in the last {_al.get('window_days')} day(s)"
            if _hdr and _hdr != alc:
                _line += (f" ({alc} of them above the cost-reporting floor; the group counts below "
                          f"cover all {_hdr})")
            if _pr_n:
                _line += (f" — RECLAIMABLE: {_pr_m} min across {_pr_n} abort(s) that paid a FULL "
                          f"verify and then refused on BOOKKEEPING ({_named('process-refusal')})")
            if _pf_n:
                # T-11777 — the group that exists so the RECLAIMABLE sentence above stays TRUE. These
                # rows carry a verify marker AND their own `abort_preflight` marker: they refused at
                # the step-4a preflight, before the suite and before the admission slot, so the
                # "paid a FULL verify" sentence is not sayable of them however their abort_class is
                # named. Measured on this repo, 25 such rows carried 579.1 min of wall-clock into the
                # reclaimable total on 12.9 min of actual verify. Their minutes are printed HERE, in
                # full — dropping them would trade an overstatement for a disappearance — and the
                # clause states what the number is NOT, because the remedy the reclaimable sentence
                # prescribes (move the refusal earlier) is already done for a preflight refusal.
                _line += (f". REFUSED AT THE STEP-4a PREFLIGHT: {_pf_m} min across {_pf_n} abort(s) "
                          f"that carry a verify marker but stopped BEFORE the suite and the admission "
                          f"slot ({_named('preflight-refused')}) — bucketed by the row's OWN recorded "
                          f"refusal point, not by its abort_class name, so these minutes are NOT in "
                          f"the reclaimable total above and moving the refusal earlier would reclaim "
                          f"almost none of them: that refusal is already as early as it goes. What "
                          f"the wall-clock IS remains open — read it as measured, not as diagnosed "
                          f"(T-11777)")
            if _gc_n:
                # T-11607 — THE NOT-WASTE CLAIM IS COMPUTED FROM THE ROWS IT IS TRUE OF, not merely
                # caveated afterwards (audit-post finding 1). `verify-failed` is emitted by ONE
                # `_die` over a SHARED `bad` list, and three corpus-integrity guards append to that
                # list after the suite — so some rows in this group refused on the branch's
                # BOOKKEEPING, not on its code. Stating the WHOLE group's count and minutes and then
                # qualifying them further down still ASSERTS the number: a reader who stops at the
                # first sentence has been told that every one of those aborts caught a defect. So
                # the sentence carries the CAUGHT-DEFECT rows' own count and minutes, and the rest of
                # the group is reported beside it with no defect claimed of it. The arm vocabulary is
                # the FOLD's (CHARTER §P5); this render only asks it which arms may be claimed.
                from lib import debt as debt_arms                  # the ONE arm vocabulary (P5)
                abort_arm_is_caught_defect = debt_arms.abort_arm_is_caught_defect
                _gc_rows = [c for c in _classes if c.get("group") == "gate-caught"]
                _gc_def = [c for c in _gc_rows if abort_arm_is_caught_defect(c.get("arm"))]
                # THREE BUCKETS, NOT TWO. A row the reader could not PLACE is not evidence of
                # bookkeeping any more than it is of a defect, so it gets its own clause: sweeping it
                # into the bookkeeping sentence would be the same over-claim as the one this card
                # removes, pointed the other way.
                _gc_book = [c for c in _gc_rows if c.get("arm") in
                            (debt_arms.ABORT_ARM_CORPUS_BOOKKEEPING, debt_arms.ABORT_ARM_MIXED)]
                # T-12406 — A FOURTH BUCKET, AND IT MUST BE TAKEN BEFORE THE REMAINDER. `_gc_unk` is
                # computed as "neither defect nor bookkeeping", so a new arm added to the fold and
                # nowhere here would be absorbed by it and reported as a row that COULD NOT BE
                # PLACED. That would be false in the one way this block exists to prevent: a
                # layer-timeout row places precisely — the trail names the layer and its outcome —
                # and what it places as is not a defect at all.
                _gc_to = [c for c in _gc_rows if c.get("arm") == debt_arms.ABORT_ARM_LAYER_TIMEOUT]
                _gc_unk = [c for c in _gc_rows
                           if c not in _gc_def and c not in _gc_book and c not in _gc_to]

                def _sub(rows):
                    return (sum(_int_or_none(c.get("n")) or 0 for c in rows),
                            round(sum(c.get("minutes") or 0 for c in rows), 1))

                _df_n, _df_m = _sub(_gc_def)
                _bk_n, _bk_m = _sub(_gc_book)
                _to_n, _to_m = _sub(_gc_to)
                _uk_n, _uk_m = _sub(_gc_unk)
                if _df_n:
                    _line += (f". SEPARATELY, AND NOT WASTE: {_df_m} min across {_df_n} abort(s) "
                              f"whose verify FAILED ON THE CODE ({_named_rows(_gc_def, (_df_n, _df_m))}) — that is "
                              f"the gate EARNING ITS KEEP, a real defect caught before it landed, "
                              f"and it is deliberately not added to any total above")
                if _bk_n:
                    _line += (f". A FURTHER {_bk_n} abort(s) in that same group, {_bk_m} min "
                              f"({_named_rows(_gc_book, (_bk_n, _bk_m))}), refused wholly or partly on CORPUS "
                              f"BOOKKEEPING (a decision content-freeze, an off-path spec edit, a "
                              f"card-shape rationale) rather than on a failing test — NO caught "
                              f"defect is claimed of them, and they are not inside the minutes "
                              f"above. A `[mixed]` arm refused on BOTH and is attributed to neither "
                              f"alone (T-11607)")
                if _to_n:
                    _line += (f". A FURTHER {_to_n} abort(s) in that same group, {_to_m} min "
                              f"({_named_rows(_gc_to, (_to_n, _to_m))}), refused because a verify "
                              f"LAYER RAN OUT OF WALL-CLOCK — the layer's command hit its timeout "
                              f"while the other layers passed, which is a HOST/LIMITS signal, not a "
                              f"statement about the code. NO caught defect is claimed of them, and "
                              f"their minutes are not inside the minutes above. Read the remedy off "
                              f"the layer, not off the branch: either the host was too loaded to "
                              f"finish work it normally finishes, or the layer's declared `timeout:` "
                              f"is below what it honestly needs (T-12406)")
                if _uk_n:
                    _line += (f". And {_uk_n} abort(s), {_uk_m} min ({_named_rows(_gc_unk, (_uk_n, _uk_m))}), could "
                              f"not be placed in EITHER arm from what the row records — reported "
                              f"`[unattributed]` rather than guessed into whichever reading is "
                              f"convenient, and claimed as neither a caught defect nor bookkeeping")
            if _ic_n:
                _line += (f". Inconclusive: {_ic_m} min across {_ic_n} abort(s) whose verify "
                          f"concluded nothing ({_named('inconclusive')})")
            if _ea_n:
                _line += (f". Refused EARLY without paying a verify: {_ea_m} min across {_ea_n} "
                          f"abort(s) ({_named('early')})")
            # T-12396 — THE EVICTIONS, BESIDE THE ABORT FIGURES AND INSIDE NONE OF THEM. Until this
            # card a T-11819 land-reservation park-limit halt was counted as an abort, which read one
            # congestion twice: once as the reservation wait the clause below reports, and once again
            # as a failed attempt that never happened (measured 2026-09-11: 4 of 14 aborts in one
            # 2-hour window, each after 149 min queued). It is not a cheap abort — the land verified
            # nothing and merged nothing; it stopped WAITING — so it is stated as its own kind of
            # thing rather than folded into a group, and the clause says what it is NOT, because the
            # remedy it points at (the queue, and the peer holding the reservation) is not the one
            # any abort figure above points at.
            #
            # THE MINUTES CARRY THEIR COVERAGE, never a bare figure: `waited_n of n`, the same shape
            # the split and reservation clauses above use. With NO covered row the minutes are
            # SUPPRESSED and the wait is reported UNRECORDED — a stated `0.0 min` would assert a
            # measurement no row proves, which is the zero-for-absent reading this whole line refuses.
            if _ev_n:
                _ev_wn = _n(_ev.get("waited_n")) or 0
                _line += ("." if _hdr else "") + (
                    f" SEPARATELY, AND NOT AN ABORT: evicted from the queue (park-limit): {_ev_n}")
                if _ev_wn:
                    _line += (f" — waited nothing-shipped {_ev.get('waited_minutes')} min "
                              f"(over {_ev_wn} of {_ev_n})")
                else:
                    _line += " — none of them recorded the wait it served, reported as unrecorded"
                _line += (". Each verified nothing, merged nothing and spent no CPU: it waited out "
                          "the LAND RESERVATION behind a holder that would not release and then "
                          "STOPPED rather than racing for the ff (T-11819). It is EXCLUDED from "
                          "every abort count, group and minute above — counting it as a failed "
                          "attempt reads the same congestion twice — and what it asks for is the "
                          "QUEUE, not the gate: read why a PEER held the reservation that long "
                          "(T-12396)")
            # T-11514 (AC3) — WAIT vs WORK, the clause that makes the split CONSUMED rather than
            # merely stored. Every class above is priced by its whole-land wall, which answers "what
            # did this cost" and not "what was it doing" — and the two answers point at DIFFERENT
            # remedies: across 352 aborts on this repo the reservation WAIT was the majority of the
            # cost while the verify RUN was 1.6% of it (T-11236), so a reader who assumed the minutes
            # above were gate cost would build against the wrong 1.6%. Until T-11514 the abort row
            # carried neither field and this clause could not be written at all; the 337/352
            # SINGLE-ATTEMPT aborts had no split anywhere, not even in `attempt_breakdown`.
            #
            # IT RE-PARTITIONS THE SAME MINUTES and is never added to any group total — the render's
            # one hard rule is untouched, because this is a PHASE partition sitting orthogonally to
            # the never-summed GROUPS, not a group of its own and not a headline.
            #
            # COVERAGE IS PRINTED BESIDE THE MINUTES, never left implicit: pre-T-11514 rows carry no
            # split and a land that never reached the timed verify carries none either, so `over N of
            # M abort(s)` is what stops a partial reading being taken for a complete one. Suppressed
            # entirely when NO row carries the split, which is every window until the first
            # post-T-11514 abort lands — an empty split stated as `0.0 min` would read as "no time
            # was spent queueing", the exact zero-for-absent misreading this card exists to remove.
            _sp = _al.get("split") if isinstance(_al.get("split"), dict) else {}
            _sp_n = _n(_sp.get("split_n")) or 0
            if _sp_n:
                _line += (f". OF THE ABORTS THAT CARRY THE WALL-CLOCK SPLIT ({_sp_n} of "
                          f"{_n(_al.get('aborts')) or 0}), {_sp.get('wait_minutes')} min was QUEUE "
                          f"WAIT for a verify-admission slot and {_sp.get('work_minutes')} min was "
                          f"the verify RUN — a re-partition of the SAME minutes by PHASE, added to no "
                          f"group total above. It tells you WHICH remedy the cost is asking for: "
                          f"wait-dominated cost is a QUEUEING problem, not a gate one (T-11514 / "
                          f"T-11236)")
                _ns = _n(_sp.get("no_split_n")) or 0
                if _ns:
                    _line += (f". The other {_ns} carry NO split — a land that never reached the "
                              f"timed verify, or a row emitted before the fields existed; reported "
                              f"as uncovered rather than as zero")
            # T-11690 — THE SECOND QUEUE, printed BESIDE the verify-phase clause and never inside it.
            # That clause names the verify-admission queue only, so on this repo it read
            # "2.6 min was QUEUE WAIT ... 1250.8 min was the verify RUN" over 174 aborts — a
            # reader would conclude queueing costs nothing and go optimise the verify. The
            # reservation queue (T-11117) is a DIFFERENT wait with a DIFFERENT remedy and sits
            # OUTSIDE `verify_duration_ms`, so it is attributed here as queue wait rather than
            # left in the unexplained residual between the phase split and the whole-land wall.
            # Its own coverage count is printed for the same reason the split's is: it is proven
            # by a different key on a different population of rows. SUPPRESSED when no row
            # carries it — a stated `0.0 min` would re-assert the very zero this removes.
            _rn = _n(_sp.get("reservation_n")) or 0
            if _rn:
                _line += (f". SEPARATELY, AND A DIFFERENT QUEUE ({_rn} of "
                          f"{_n(_al.get('aborts')) or 0}), {_sp.get('reservation_minutes')} min "
                          f"was QUEUE WAIT for the LAND RESERVATION — the serialized "
                          f"merge->verify->ff window a peer land holds (T-11117). It is NOT "
                          f"inside the verify wall and is never added to it: a "
                          f"verify-admission wait asks for slot-pool capacity, a reservation "
                          f"wait asks why a PEER is holding the window, and one summed number "
                          f"would name neither remedy. Total time spent QUEUEING at all: "
                          f"{_sp.get('queue_wait_minutes')} min (T-11690)")
            _un = _n(_al.get("undetermined")) or 0
            if _un:
                _line += (f". {_un} abort(s) carried no determinable cost — reported UNDETERMINED, "
                          f"never as free")
            _tr = _n(_al.get("trivial")) or 0
            if _tr:
                # T-11851 — "FURTHER" WAS THE WHOLE MISREADING. These rows are already inside the
                # group counts printed above; the word said they were additional to them, which is
                # what made 371, 501 and 130 compose in no stated way. The clause now states the
                # subset relationship and spells the arithmetic, so a reader can close it from the
                # line alone rather than from the fold's source.
                if _hdr != alc:
                    _line += (f". {_tr} of those cost too little to be worth reporting "
                              f"individually — they are INSIDE the group counts above, not "
                              f"additional to them ({alc} above the floor + {_tr} below it "
                              f"= {_hdr})")
                else:
                    _line += (f". {_tr} abort(s) in the window cost too little to be worth "
                              f"reporting individually")
            # T-12396 — the TREND sentence is about the CLASSES above, so it is stated only when
            # there are any: on an eviction-only window it would counsel reading a trend over an
            # empty partition.
            if _hdr:
                _line += (f". Read the TREND before acting: a DECAYING class is already going "
                          f"away under its own steam — usually a declaration or a fix that has "
                          f"landed — and building against it spends effort on a cost that no "
                          f"longer exists (X-1039)")
            # T-11426 (kupiclub X-1096): a class NAME that unions two refusals of different MOVABILITY
            # is named as such, at the same prominence as its minutes — printed only when such a class
            # is actually in this render, so nothing is asserted about a window that has none. Without
            # this the reader gets a correctly-partitioned line and no reason to know why one name now
            # appears twice.
            _armed = sorted({str(c.get("class")) for c in _classes if c.get("arm")})
            if "rebaseline-unauthorized" in _armed:
                _line += (f". rebaseline-unauthorized appears ONCE PER ARM because one class name carries "
                          f"two refusals whose MOVABILITY differs — the authorization arm moved WHOLE "
                          f"to the step-4a preflight (T-10850) and is cheap, while the waive-coverage "
                          f"arm (T-10754) moved only in PART: its TOKEN-BINDING half now refuses at "
                          f"that same step-4a preflight off one file (T-11479), and its COVERAGE half "
                          f"still reads `pinned_bad` after a full pinned run — so they are two "
                          f"remedies, not one, and a trend over their union describes neither "
                          f"(T-11426). An `[unattributed]` arm is a row the reader could not place, "
                          f"reported as such rather than guessed")
            # T-11607 — the SECOND split class, and it unions something DIFFERENT, so it gets its own
            # sentence rather than being absorbed into the one above (which describes preflight
            # placement, a thing `verify-failed` has no analog of).
            if "verify-failed" in _armed:
                _line += (f". verify-failed appears ONCE PER ARM for a different reason: it is emitted "
                          f"by ONE refusal over a SHARED failing list that the test suite and three "
                          f"CORPUS-INTEGRITY guards both feed (SPEC-0054 decision freeze, SPEC-0005 "
                          f"off-path spec edit, SPEC-0165 card shape), whose inputs are the branch's "
                          f"committed delta rather than its behaviour — so a `[corpus-bookkeeping]` "
                          f"row is paperwork and a `[test-failure]` row is a caught defect, and they "
                          f"are two remedies. A `[mixed]` row refused on BOTH and is attributed to "
                          f"neither alone; an `[unattributed]` one could not be placed and is reported "
                          f"as such rather than guessed (T-11607). A `[layer-timeout]` row is a THIRD "
                          f"thing again: a consumer verify LAYER hit its wall-clock timeout, whose "
                          f"sentence reaches that same shared failing list without the marker the "
                          f"class fork keys on — so it arrives labelled `verify-failed` while saying "
                          f"nothing about the code. Its remedy is the host or the layer's declared "
                          f"`timeout:`, never the branch (T-12406)")
            # T-11682 — THE CLASS THIS LINE CANNOT COST, NAMED HERE WITH ITS CAUSE. This fold's
            # subject is `land_completed{status:abort}` rows and their MINUTES; a land that DIED wrote
            # no such row, no abort class and no duration, so it contributes nothing here and a reader
            # can finish this line believing they have seen every land that shipped nothing. They have
            # not. The remedy is NOT to invent a cost — that would report minutes nobody measured, and
            # a fabricated figure inside a cost report is worse than an absent one — but to state the
            # class as UNCOVERED and to carry its RECOVERED CAUSE inline, which is the identical
            # uncovered-rather-than-zero shape this line already uses for the aborts carrying no
            # wall-clock split (`no_split_n`, just above).
            #
            # The cause text comes from the ONE shared `dead_land_cause_clause` renderer the rule-23
            # line uses, so the two surfaces cannot describe the same death differently — including
            # its CULPRIT UNNAMED arm, which is why an undecided attribution can never be read here as
            # a named member. NO total, group, minute or count in the line above is touched, and the
            # clause is absent entirely when no dead land exists.
            _dlc = _n(_dl_once.get("count")) or 0
            if _dlc:
                from lib.debt import dead_land_cause_clause as _dl_cause
                _dls = _dl_once.get("lands") if isinstance(_dl_once.get("lands"), list) else []
                _caused = [(r, _dl_cause(r)) for r in _dls if isinstance(r, dict)]
                _caused = [(r, c) for r, c in _caused if c]
                _line += (f". SEPARATELY, AND NOT COUNTED IN ANY TOTAL ABOVE: {_dlc} land(s) DIED "
                          f"without writing any `land_completed` row at all — not even an abort — so "
                          f"they carry NO abort class and NO measurable cost here and are reported as "
                          f"UNCOVERED rather than as zero, exactly like the no-split aborts above")
                if _caused:
                    _line += (". What they died on IS on record, recovered from the member verdicts "
                              "their own batch wrote before the head died: "
                              + "; ".join(f"{r.get('branch')} — {c}" for r, c in _caused[:_CAP])
                              + (f" (+{len(_caused) - _CAP} more)" if len(_caused) > _CAP else ""))
                else:
                    _line += (". None of them left a recorded red cause — reported as unrecorded, "
                              "never as uneventful")
                _line += ". They are listed with their remedy on the dead-lands line (rule 23)"
            lines.append(
                _line + f". Report-only, nothing gated (SPEC-0119 rule 27). See `bin/yitc-v2 debt`.")
    # NON-TERMINAL PLAN CENSUS (SPEC-0119 rule 21, T-11181): the OPTIONAL injected fold over
    # `plans/*.md` frontmatter — how many plans sit in each non-terminal stage of the plan FSM.
    # Wired at the SAME shared host residue as every sibling, but — UNLIKE every sibling — it does
    # NOT ride all three debt seams: T-11212 (owner-surfaced) narrowed rule 21 to the SESSION-START
    # seam plus the explicitly-invoked `debt` re-fold, and the LAND TAIL simply does not inject this
    # collaborator (`_debt_echo_lines_land_tail` passes None, so the branch below is never taken
    # there). Nothing in THIS leaf is seam-aware: the collaborator stays optional exactly as built,
    # and which seams pass it is the caller's decision. It names
    # the per-stage counts rather than a bare total because the remedy differs by stage (a `draft`
    # awaits a decision; a `postcheck` plan is a soak somebody has to judge), and a single number
    # would leave the reader to go re-derive the split by hand. The `unknown` tail is a named clause
    # on this SAME line, never a second one: it is the same debt (a plan nobody is tracking) reached
    # by a different route, and naming it is what keeps an unreadable plan from being silently
    # dropped by the filter it could not answer. Report-only, suppressed-when-clean, UNFLOORED,
    # never gates — and it SURFACES plans without ever picking, ranking or suggesting one.
    if _plan_census is not None:
        _pc = _plan_census() or {}
        pc = _n(_pc.get("count")) if isinstance(_pc, dict) else None
        if pc and pc > 0:
            _by = _pc.get("by_status") or {}
            _named = ", ".join(f"{s} {n}" for s, n in _by.items()
                               if isinstance(n, int) and n > 0) if isinstance(_by, dict) else ""
            _unk = _n(_pc.get("unknown")) or 0
            _unk_clause = (f" (+{_unk} with NO parseable `status:` — counted as unknown rather than "
                           f"dropped; repair the frontmatter, then read them)") if _unk else ""
            # T-12081 (SPEC-0119 rule 21, slice staleness) — the suppressed-when-clean TAIL on this
            # SAME line: the counts named no plan, and that is how a multi-slice umbrella realizes one
            # slice and lets the rest rot while every count reads healthy. Naming a stale candidate is
            # SURFACING, not PICKING — the sibling rule-36 line names STUCK cards on identical terms —
            # so this ranks nothing and the remedy stays an owner cue. Absent when the list is empty.
            _stale = [c for c in (_pc.get("stale") or []) if isinstance(c, dict)]
            _stale_clause = ""
            if _stale:
                _bounds = _pc.get("bounds") if isinstance(_pc.get("bounds"), dict) else {}
                _CAP_ST = 3

                def _one_stale(c):
                    return (f"{c.get('plan')}/{c.get('card')}" if c.get("card")
                            else str(c.get("plan")))

                _by_kind = {}
                for c in _stale:
                    _by_kind.setdefault(c.get("kind"), []).append(c)
                _label = {
                    "decomposition-age": f"mid-cut >={_bounds.get('decomposition_days')}d",
                    "stale-cut-card": f"cut card untouched >={_bounds.get('cut_card_days')}d",
                    "umbrella-age": f"umbrella >={_bounds.get('umbrella_days')}d since `accepted`, "
                                    f"no `renewed_at`",
                }
                _parts = []
                for _kind in ("decomposition-age", "stale-cut-card", "umbrella-age"):
                    _got = _by_kind.get(_kind) or []
                    if not _got:
                        continue
                    _shown = ", ".join(_one_stale(c) for c in _got[:_CAP_ST])
                    _more = f", +{len(_got) - _CAP_ST} more" if len(_got) > _CAP_ST else ""
                    _parts.append(f"{_label.get(_kind, _kind)}: {_shown}{_more}")
                _stale_clause = (" STALE SLICES — " + "; ".join(_parts) +
                                 ". Age is read from the stage rows the plan FSM already emits, and "
                                 "a plan young enough to prove it is never named. Advance it, renew "
                                 "it (`renewed_at:`), or close it honestly — SURFACING ONLY, this "
                                 "names candidates and picks none.")
            lines.append(
                f"debt: {pc} non-terminal plan(s) parked mid-lifecycle"
                + (f" — {_named}" if _named else "") + _unk_clause +
                f". Plans are the one tracked work class no seam surfaces (the picker reads `tasks/` "
                f"ONLY), so a plan sitting in `postcheck` — the real-data soak that PROVES the change "
                f"— goes quiet indefinitely. Terminal plans are not counted. Read one with "
                f"`bin/yitc-v2 plan show <slug>`, list them with `bin/yitc-v2 plan list`, then "
                f"advance or close it. SURFACING ONLY — this names no candidate and selects nothing; "
                f"taking a plan into work stays an OWNER CUE (SPEC-0119 rule 21)." + _stale_clause)
    # UNPICKABLE-READY-CARDS view (SPEC-0119 rule 36, T-11868): the OPTIONAL injected fold over
    # `tasks/` — cards sitting `ready` whose `requires:` names a `wont-do` target. `requires:` is the
    # picker's BLOCKING edge and `wont-do` never satisfies it, so the card can NEVER be picked while
    # reading `ready` at every surface that folds card status. The picker's own refusal does not cover
    # this: it fires at SELECTION, and a card nobody selects is never refused — the blockage is exactly
    # what stops anyone taking that path. Report-only, suppressed-when-clean, UNFLOORED (one card stuck
    # forever is debt at count 1, and count-hiding it restores the silence the rule ends), NEVER gates.
    # It names the STUCK cards, which is the opposite of naming a candidate: the remedy is a DECISION
    # (drop the dead edge, or close the card wont-do) and this line picks neither.
    if _unpickable_ready is not None:
        _ur = _unpickable_ready() or {}
        urc = _n(_ur.get("count")) if isinstance(_ur, dict) else None
        if urc and urc > 0:
            _cards = [c for c in (_ur.get("cards") or []) if isinstance(c, dict)]
            _CAP_UR = 3

            def _one_stuck(c):
                _bl = [b.get("id") for b in (c.get("blockers") or [])
                       if isinstance(b, dict) and b.get("id")]
                return f"{c.get('task')} (requires {', '.join(str(b) for b in _bl)})" if _bl \
                    else str(c.get("task"))

            _named_ur = ", ".join(_one_stuck(c) for c in _cards[:_CAP_UR])
            _more_ur = f" (+{urc - _CAP_UR} more)" if urc > _CAP_UR else ""
            lines.append(
                f"debt: {urc} READY card(s) blocked FOREVER by a `wont-do` requirement — "
                f"{_named_ur}{_more_ur}. `requires:` is the picker's blocking edge and `wont-do` is the "
                f"terminal status that never satisfies it, so these can NEVER be picked — yet they read "
                f"`ready` everywhere card status is folded, and the picker's refusal is reachable only "
                f"by selecting the card, which is precisely what the blockage prevents. TWO honest "
                f"exits, and choosing between them is a judgement about the WORK: DROP the dead "
                f"`requires:` edge if the requirement is no longer needed, or CLOSE the card itself "
                f"`wont-do` if it was the point. SURFACING ONLY — this names no candidate, ranks nothing "
                f"and selects nothing (SPEC-0119 rule 36).")
    # LOAD-SENSITIVE-UNCARDED view (SPEC-0119 rule 41, T-12359): the OPTIONAL injected fold over the
    # declared load-sensitive carrier + `tasks/` — files that entered `tests/load-sensitive.txt` and
    # that NO non-terminal card is holding. Entry is automatic and exit is never automatic BY DESIGN
    # (T-12358): a listed file no longer runs in the concurrent pool, so nothing can prove it
    # pool-robust again and only a card can remove its line. A listed file with no live card is
    # therefore a permanent serialization nobody agreed to, and until this line nothing said so.
    #
    # DATED, in the rule-38 chronic shape, and for the same reason: the entry date is what turns "this
    # file is serialized" into "this file has been serialized since <date>" — a standing debt with a
    # first day rather than a permanent flag. Report-only, suppressed-when-clean, UNFLOORED (one file
    # serialized forever is debt at count 1), NEVER gates: it removes no line and files no card.
    if _load_sensitive_uncarded is not None:
        _ls = _load_sensitive_uncarded() or {}
        lsc = _n(_ls.get("count")) if isinstance(_ls, dict) else None
        if lsc and lsc > 0:
            _lsf = [f for f in (_ls.get("files") or []) if isinstance(f, dict)]
            # EVERY file is named, and this view is deliberately UNCAPPED where its siblings
            # truncate at 3. The contract is "naming every listed file without a live card", and a
            # cap would break it in the direction that matters: the set is MONOTONIC (entry is
            # automatic, exit is a card's decision), so the files a cap hides are the ones that have
            # been serialized longest with nobody holding them — the exact rows this rule exists to
            # surface. The list is bounded by the carrier, which only a card shrinks, so it cannot
            # run away on its own; and the rule-40 table folds this to a single counted row at the
            # two ECHO seams, leaving the full enumeration to `bin/yitc-v2 debt` where it belongs.
            _named_ls = ", ".join(
                f"{f.get('file')} (since {f.get('entered')})" if f.get("entered") else
                f"{f.get('file')} (entry date unrecorded)" for f in _lsf)
            _more_ls = ""
            lines.append(
                f"debt: {lsc} declared load-sensitive file(s) that NO live card is holding — "
                f"{_named_ls}{_more_ls}. Each entered `tests/load-sensitive.txt` automatically and "
                f"now runs SERIALIZED after the concurrent pool on both verify legs. Exit is never "
                f"automatic by design: a file in that lane cannot prove itself pool-robust, so only a "
                f"card removes a line. TWO honest exits, and which one applies is a judgement about "
                f"the TEST: FILE a card to make the file load-robust (`bin/yitc-v2 task file`, "
                f"carrying `load-sensitive:<file>` in its `cites:` so this line stops firing for it, "
                f"and remove the carrier line in its ship diff), or RATIFY the line by appending a "
                f"reason to it in `tests/load-sensitive.txt`. Never delete the line to silence this "
                f"row — that returns the file to the pool with nothing re-justified. Report-only "
                f"(SPEC-0119 rule 41). See `bin/yitc-v2 debt`.")
    # DEAD-LANDS view (SPEC-0119 rule 23, T-11254 / kupiclub X-0976): the OPTIONAL injected fold over
    # the branch frontier + the journal — branches whose `land` STARTED (its step-1 bookkeeping commit
    # is the tip) and never emitted a terminal row in EITHER direction. This is the one failure mode
    # every other surface is blind to AT ONCE: the `LAND:` token is stdout of a process that is gone,
    # the repeated-abort backstop counts abort ROWS, and every sibling view here folds halts/followups/
    # plans. So the only trace is the commit, and this is the only reader that looks at it. An ABORTED
    # land is deliberately absent — it reported, and the backstop owns it. Report-only,
    # suppressed-when-clean, FLOORED BY AGE at 90 minutes (`cli._debt_dead_land_floor_minutes`,
    # `YITC_DEBT_DEAD_LAND_FLOOR_MINUTES`) — the rule was DRAFTED unfloored, on the reasoning that a
    # dead land is debt from its first minute, and its own live probe refuted that: between land
    # step-1's bookkeeping commit and its terminal row a HEALTHY IN-FLIGHT land is byte-for-byte
    # indistinguishable from a dead one, so unfloored the live repo named 6 branches of which 5 were
    # healthy lands still verifying. Nagging a controller about workers that are working is how a
    # report-only line teaches its reader to ignore it — the exact silence the rule exists to break
    # (retraction recorded in SPEC-0119 rule 23 §THE AGE FLOOR). It NAMES a branch without ever
    # recovering one: no marker, no watcher, no stored state, it starts nothing (CHARTER §6 named
    # retirement (d)). The remedy it points at is the EXISTING idempotent `worktree recover-land` —
    # rendered PER BRANCH via `debt.dead_land_remedy` (T-11385), so the form it names is one that verb
    # ACCEPTS for that branch's namespace. This line and the `debt` re-fold's `next:` share that ONE
    # renderer: two surfaces naming different remedies for the same branch is how a reader learns to
    # distrust both.
    if _dead_lands is not None:
        # T-11385 — the remedy renderer lives in `debt` (ONE home, shared with the `debt` re-fold's
        # `next:`), and `debt` is a DEFERRED module (T-11320): importing it at module scope would
        # re-eagerize it on every `views` import, undoing exactly what that deferral bought. So it is
        # imported HERE, inside the arm that is already about to run the dead-land fold.
        from lib.debt import dead_land_cause_clause as _dead_land_cause_clause
        from lib.debt import dead_land_remedy as _dead_land_remedy
        _dl = _dl_once            # T-11682 — the ONE fold, shared with the abort-cost arm above
        dlc = _n(_dl.get("count")) if isinstance(_dl, dict) else None
        if dlc and dlc > 0:
            _ls = _dl.get("lands") or []
            _ls = _ls if isinstance(_ls, list) else []
            def _one(r):
                if not isinstance(r, dict):
                    return ""
                br = str(r.get("branch") or "?")
                age = r.get("age_hours")
                return f"{br} ({age}h)" if isinstance(age, int) else br
            _named = ", ".join(x for x in (_one(r) for r in _ls[:3]) if x)
            _more = f" (+{dlc - 3} more)" if dlc > 3 else ""
            # The worktree clause is REMEDY CONTEXT and is stated only when it is actually known —
            # the fold degrades it to None per branch rather than suppressing the row, so the line
            # must not imply a path it does not have.
            _wt = next((str(r.get("worktree")) for r in _ls
                        if isinstance(r, dict) and r.get("worktree")), None)
            lines.append(
                f"debt: {dlc} branch(es) whose `land` STARTED and never reported"
                + (f" — {_named}{_more}" if _named else "") +
                f". The land committed its step-1 bookkeeping and then died before emitting any "
                f"`land_completed` row — not even an abort — so whatever it carries is unmerged and "
                f"INVISIBLE on main, and no other surface can see it (the `LAND:` token is stdout of a "
                f"dead process; the abort backstop counts rows that were never written)."
                # T-11682 — the explanation is printed ONLY when a cause is actually shown. A line
                # that always explained the [bracket] notation would teach the reader to expect one
                # on every row, and a row without a recorded cause would then read as a cause of
                # NOTHING rather than as unrecorded. Silence about a thing that is not there.
                + (f" Where the dead land was a BATCH HEAD, what killed the batch is recovered from "
                   f"the member verdicts its own batch wrote before it died and is shown in "
                   f"[brackets] below — including, where the attribution DECLINED, an explicit "
                   f"CULPRIT UNNAMED, which is never a guess at which member owned the red "
                   f"(T-11682)." if any(_dead_land_cause_clause(r) for r in _ls[:3]
                                        if isinstance(r, dict)) else "") +
                f" Read what is "
                f"stranded with `git log --oneline main..<branch>`, then recover each with the form "
                f"that ACCEPTS it (T-11385): "
                + "; ".join(f"{r.get('branch')} -> {_dead_land_remedy(r.get('branch'))}"
                            + (f" [{_dead_land_cause_clause(r)}]" if _dead_land_cause_clause(r) else "")
                            for r in _ls[:3] if isinstance(r, dict))
                + (f" (worktree still present: {_wt})" if _wt else "") +
                f". SURFACING ONLY — this recovers nothing and arms nothing; the row drops by itself "
                f"the moment a terminal row lands for that branch (SPEC-0119 rule 23).")
    # AHEAD-WORK-BRANCHES view (SPEC-0119 rule 24, T-11303 / kupiclub X-1001, corrected by X-1003): the
    # OPTIONAL injected fold over the git branch frontier — `task/*` / `work/*` branches carrying commits
    # main does not have, aged past the floor. The COMPLEMENT of the rule-23 arm directly above (that one
    # owns branches whose land STARTED; this one owns branches where it never started at all), so the two
    # partition the frontier rather than double-reporting it. Report-only, suppressed-when-clean, NEVER
    # gates, and FLOORED BY AGE rather than by count — the count is never hidden, only youth suppresses,
    # because every healthy in-flight build has a branch ahead of main. It NAMES branches and nothing
    # more: no candidate, no ranking, no next-action verb, and its only pointer is a read-only `git log`.
    if _ahead_branches is not None:
        _ab = _ahead_branches() or {}
        abc = _n(_ab.get("count")) if isinstance(_ab, dict) else None
        if abc and abc > 0:
            _bs = _ab.get("branches") or []
            _bs = _bs if isinstance(_bs, list) else []
            def _one_ahead(r):
                if not isinstance(r, dict):
                    return ""
                br = str(r.get("branch") or "?")
                n = r.get("ahead")
                age = r.get("age_hours")
                _n_txt = f"{n} commit(s)" if isinstance(n, int) else "? commit(s)"
                _a_txt = f", {age}h" if isinstance(age, int) else ""
                return f"{br} ({_n_txt}{_a_txt})"
            _CAP = 4
            _named_ab = ", ".join(x for x in (_one_ahead(r) for r in _bs[:_CAP]) if x)
            _more_ab = f" (+{abc - _CAP} more)" if abc > _CAP else ""
            lines.append(
                f"debt: {abc} work branch(es) AHEAD of main"
                + (f" — {_named_ab}{_more_ab}" if _named_ab else "") +
                f". Each carries commits main does not have and no seam was naming them; whether a "
                f"branch is ahead is the one fact separating a benign stale branch from a serious one, "
                f"and the dispatch census (live worktrees), the not-adopted view (the inverse main->live "
                f"leg) and worktree sweep (deletes no branch) all miss it. The count is of commits "
                f"main lacks BY SHA, and NEVER evidence that their content is absent from main — a change "
                f"that reached main another way still shows here (kupiclub X-1003). Read what each carries "
                f"with `git log --oneline main..<branch>`. SURFACING ONLY — this names no candidate, "
                f"ranks nothing and selects nothing; the row drops by itself once the branch merges or "
                f"is deleted (SPEC-0119 rule 24).")
    # BEHIND-WORK-BRANCHES view (SPEC-0119 rule 32, T-11579 / kupiclub X-1105): the OPTIONAL injected
    # fold over the FULL git branch frontier — LIVE `task/*` / `work/*` worktrees whose branch main has
    # run far ahead of. The OTHER HALF of the rule-24 arm above: that one reports how far AHEAD a branch
    # is (does it hold work nobody else has), this reports how far BEHIND (is it about to hit a painful
    # merge, or to run a suite against a tree main fixed hours ago). Report-only, suppressed-when-clean,
    # NEVER gates — and the requester made that bound their own: a stale copy is very often perfectly
    # fine, so a threshold that refused would turn a surfacing view into a fence. FLOORED BY COMMIT
    # COUNT rather than by age, the deliberate departure from every sibling floor here: a fast repo makes
    # a morning-cut copy hundreds behind by noon while a quiet day barely moves it, so elapsed time
    # carries no information and distance from main does.
    if _behind_branches is not None:
        _bb = _behind_branches() or {}
        bbc = _n(_bb.get("count")) if isinstance(_bb, dict) else None
        if bbc and bbc > 0:
            _bbs = _bb.get("branches") or []
            _bbs = _bbs if isinstance(_bbs, list) else []
            _floor = _n(_bb.get("floor_commits"))

            def _one_behind(r):
                if not isinstance(r, dict):
                    return ""
                br = str(r.get("branch") or "?")
                n = r.get("behind")
                return f"{br} ({n} commit(s))" if isinstance(n, int) else f"{br} (? commit(s))"
            _CAP_B = 4
            _named_bb = ", ".join(x for x in (_one_behind(r) for r in _bbs[:_CAP_B]) if x)
            _more_bb = f" (+{bbc - _CAP_B} more)" if bbc > _CAP_B else ""
            lines.append(
                f"debt: {bbc} live work branch(es) BEHIND main"
                + (f" by more than {_floor} commit(s)" if isinstance(_floor, int) and _floor > 0 else "")
                + (f" — {_named_bb}{_more_bb}" if _named_bb else "") +
                f". Each is a tree someone can still run something in while main has moved well past it, "
                f"which is the half the ahead-count cannot tell you: whether the branch is about to hit a "
                f"painful merge, or to run a suite against a tree main fixed hours ago. Behind-ness is "
                f"otherwise computed in exactly one place in the engine — inside `worktree sync`, the verb "
                f"that also cures it — so its record is a receipt for the cure, never a signal of the "
                f"disease, and a branch nobody synced is measured by nothing. The count is of commits main "
                f"has BY SHA that the branch lacks, and NEVER evidence that their content is absent from "
                f"the branch (kupiclub X-1003). Read what each is missing with "
                f"`git log --oneline <branch>..main`. SURFACING ONLY — this names no candidate, ranks "
                f"nothing and selects nothing, and a stale copy is often perfectly fine; the row drops by "
                f"itself once the branch catches up or its worktree goes away (SPEC-0119 rule 32).")
    # CONCURRENT-SESSION-HOLDS view (SPEC-0119 rule 25, T-11353 / kupiclub X-1025): the OPTIONAL
    # injected fold over the live worktree list + the T-0362 session stamps — the holds carried by a
    # session OTHER than the reading one. Report-only, suppressed-when-clean, UNFLOORED, and it makes
    # concurrency VISIBLE without making it EXCLUSIVE: no lock, no lease, no owner-election, no
    # refusal to dispatch (D-0083 makes concurrent sessions NORMAL). The line carries its own two
    # bounds — stamps are not actors (T-0412), presence is not liveness (T-0351) — because a reader
    # who over-reads either one gets a worse answer than the silence this replaces.
    if _concurrent_sessions is not None:
        _cs = _concurrent_sessions() or {}
        csc = _n(_cs.get("count")) if isinstance(_cs, dict) else None
        if csc and csc > 0:
            _hs = _cs.get("holders") or []
            _hs = _hs if isinstance(_hs, list) else []
            _wt_n = _n(_cs.get("worktrees")) or 0

            def _one_holder(h):
                if not isinstance(h, dict):
                    return ""
                ref = str(h.get("session_ref") or "?")
                held = h.get("held")
                what = h.get("tasks") or h.get("branches") or []
                what = ", ".join(str(x) for x in what[:3]) if isinstance(what, list) else ""
                # ADVISORY liveness, and it says which of the three states it is in — a probe that
                # could not tell must not read as either answer (the presence/liveness split).
                alive = h.get("alive")
                _live = ("advisory: holder process seen alive" if alive is True else
                         "advisory: holder process NOT seen — presence is not proof it died"
                         if alive is False else "advisory: liveness undetermined")
                _n_txt = f"{held} worktree(s)" if isinstance(held, int) else "worktree(s)"
                return f"{ref} ({_n_txt}{': ' + what if what else ''}; {_live})"

            _CAP_CS = 3
            _named_cs = "; ".join(x for x in (_one_holder(h) for h in _hs[:_CAP_CS]) if x)
            _more_cs = f" (+{csc - _CAP_CS} more)" if csc > _CAP_CS else ""
            # OWN-FLEET ATTRIBUTION (T-11606) — an ADDED clause, never a subtraction from the count
            # above: the headline is the FOREIGN stamps, and the reader's own dispatched workers are
            # named here so the 19-of-19 case that hid a real foreign holder cannot recur. Rendered
            # only when the fold positively attributed something; absent ⇒ this line is byte-identical
            # to before the attribution existed.
            _own = _cs.get("own_fleet") if isinstance(_cs.get("own_fleet"), dict) else None
            _own_txt = ""
            if _own:
                _own_wt = _n(_own.get("worktrees")) or 0
                _own_st = _n(_own.get("stamps")) or 0
                _own_tasks = _own.get("tasks") or []
                _own_named = ", ".join(str(t) for t in _own_tasks[:3]) if isinstance(_own_tasks, list) else ""
                _own_more = (f" +{len(_own_tasks) - 3} more"
                             if isinstance(_own_tasks, list) and len(_own_tasks) > 3 else "")
                _own_txt = (
                    f" SEPARATELY, AND NOT ANOTHER CONTROLLER: a further {_own_wt} live worktree(s) "
                    f"under {_own_st} stamp(s) here are held by workers YOU dispatched"
                    + (f" ({_own_named}{_own_more})" if _own_named else "") +
                    f", attributed from your own `bg_dispatch_launched` records and deliberately NOT "
                    f"counted above. They are excluded because `dispatch` assigns each worker a FRESH "
                    f"session ref, so one fleet would otherwise read as that many foreign stamps and "
                    f"bury the one holder you needed to see (T-11606). Attribution requires a launch "
                    f"record of YOUR OWN naming that exact ref — anything unattributable stays counted "
                    f"above, because a wrong attribution would hide a real holder.")
            lines.append(
                f"debt: {csc} OTHER session stamp(s) hold {_wt_n} live worktree(s) in this repo"
                + (f" — {_named_cs}{_more_cs}" if _named_cs else "") +
                f". You are not alone in this checkout, and no other seam says so: a claim "
                f"(ready->in-progress) lives in the claiming worktree until `land`, so a card held by "
                f"another session still reads `ready` on main and the in-progress count stays "
                f"silent. READ before you dispatch or claim — `git worktree list`, then `bin/yitc-v2 "
                f"journal query --dispatch-status` for per-task liveness."
                + _own_txt +
                f" TWO BOUNDS, both load-bearing: "
                f"this counts DISTINCT SESSION STAMPS, NEVER independent actors — a controller and the "
                f"workers that INHERIT its provider session id share one stamp (T-0412), so such a "
                f"fleet reads as one; a DISPATCH-LAUNCHED worker instead gets a fresh ref, and that "
                f"fleet is attributed away above rather than counted (T-11606); and liveness is "
                f"ADVISORY, never authority — a worktree's presence is "
                f"not proof its holder is alive (T-0351). SURFACING ONLY — concurrent sessions are "
                f"NORMAL here (D-0083); this makes them VISIBLE, not exclusive. It takes no lock, "
                f"elects no owner, refuses no dispatch, and adopts or cleans up nothing "
                f"(SPEC-0119 rule 25).")
    # OWN-EVIDENCE UNCITED-PATTERN view (SPEC-0119 rule 22, T-11211 / kupiclub X-0956 + X-0961): the
    # OPTIONAL injected fold over the KERNEL patterns catalog read against THIS repo. A kernel SPEC that
    # is active+adoptable reaches every consumer through its OWN fail-closed `init` (SPEC-0112); a
    # PATTERN has no such gate, so a practice built from a project's own evidence can never return to it.
    # Report-only, suppressed-when-clean, UNFLOORED — and it SURFACES without ever prescribing: whether
    # adopting the pattern is right stays the project's call, and NO fleet-wide threshold is implied.
    if _own_evidence_patterns is not None:
        _oe = _own_evidence_patterns() or {}
        oc = _n(_oe.get("count")) if isinstance(_oe, dict) else None
        if oc and oc > 0:
            _names = _oe.get("names") or []
            _named = ", ".join(str(s) for s in _names[:3]) if isinstance(_names, list) else ""
            _more = (f" (+{oc - 3} more)" if isinstance(_names, list) and oc > 3 else "")
            lines.append(
                f"debt: {oc} kernel pattern(s) built partly from THIS project's own evidence that this "
                f"project has never cited"
                + (f" — {_named}{_more}" if _named else "") +
                f". A kernel spec reaches you through your own `init` whether or not anyone writes to "
                f"you; a PATTERN has no such gate, so a practice distilled from your reports can fail "
                f"to come back to you. Read one with `bin/yitc-v2 graph query <slug>`. SURFACING ONLY "
                f"— this prescribes nothing and derives no fleet-wide threshold: not adopting it may "
                f"well be right for this project, and that stays YOUR call (SPEC-0119 rule 22).")
    # BROKEN-OUTCOME-INVARIANTS view (SPEC-0119 rule 17, T-10554 / X-0419): the OPTIONAL injected fold over
    # this repo's declared `outcome_invariants:` (SPEC-0093 rule 24) + the journal + the declared read-only
    # probes. Wired at the SAME shared host residue as every sibling → all three debt seams from one site.
    # This is the only line in this echo that reports on the PRODUCT rather than the process, which is why it
    # renders LAST and loudest: the others say what the process still owes, this says the thing is broken.
    # THREE lines, not one, because the three states have three different remedies and merging them would
    # make the count unactionable: `broken` → fix the subsystem; `degraded` → fix the probe (an invariant
    # whose probe cannot answer is not covered — the rule-23 named-degrade discipline: never a silent pass);
    # `unproven` → record the SPEC-0156 failing demonstration. Each names the invariants, not a bare count:
    # the remedy is per-invariant, and a number alone would leave the owner to diff the carrier by hand.
    # Report-only, suppressed-when-clean, UNFLOORED, never gates.
    if _broken_outcome_invariants is not None:
        _oi = _broken_outcome_invariants() or {}
        oi = _n(_oi.get("count")) if isinstance(_oi, dict) else None
        if oi and oi > 0:
            _inv = [i for i in (_oi.get("invariants") or []) if isinstance(i, dict)]
            _CAP = 3

            def _name_inv(rows):
                # `id (subsystem)` — the subsystem is what makes the line legible at a glance ("stats is
                # broken"), and it is the whole reason the declaration carries one.
                out = []
                for i in rows[:_CAP]:
                    _id = str(i.get("id"))
                    _sub = i.get("subsystem")
                    out.append(f"{_id} ({_sub})" if _sub else _id)
                return ", ".join(out) + (f" +{len(rows) - _CAP} more" if len(rows) > _CAP else "")

            _broken = [i for i in _inv if i.get("state") == "broken"]
            _degraded = [i for i in _inv if i.get("state") == "degraded"]
            _unproven = [i for i in _inv if i.get("state") == "unproven"]
            if _broken:
                # Name the first probe's own detail: the probe said WHY, and dropping it would make the
                # owner re-run by hand the very check that just answered.
                _detail = next((str(i.get("detail")) for i in _broken if i.get("detail")), None)
                # An invariant that is broken AND never demonstrated is a WEAKER signal than a broken one
                # whose probe was proven — say so rather than letting the reader assume the probe is sound.
                _undem = [i for i in _broken if i.get("admission") != "proven"]
                lines.append(
                    f"debt: {len(_broken)} declared outcome-invariant(s) BROKEN — {_name_inv(_broken)}"
                    + (f": {_detail}" if _detail else "")
                    + (f" ({len(_undem)} of them carry NO failing demonstration, so the probe itself is "
                       f"unproven too)" if _undem else "")
                    + f". A standing product outcome this project declared is NOT holding right now "
                      f"(SPEC-0093 rule 24). This line exists so the owner is not the monitor (X-0419: five "
                      f"remediation cards closed green over three days while the product stayed broken). "
                      f"See `bin/yitc-v2 debt`.")
            if _degraded:
                _detail = next((str(i.get("detail")) for i in _degraded if i.get("detail")), None)
                lines.append(
                    f"debt: {len(_degraded)} declared outcome-invariant probe(s) DEGRADED — "
                    f"{_name_inv(_degraded)}"
                    + (f": {_detail}" if _detail else "")
                    + f". The probe could not produce a verdict, so the invariant is NOT covered — a broken "
                      f"subsystem behind a broken probe reads exactly like a healthy one. Repair the declared "
                      f"`probe:` (a read-only `{{kind: command, command: [argv…]}}` whose stdout is "
                      f"`{{\"ok\": true|false}}`), or waive the entry with a reason (SPEC-0093 rule 24). "
                      f"Report-only (SPEC-0119 rule 17).")
            if _unproven:
                # NEAR-MISS clause (T-11868) — the SAME tail the sibling unproven-CHECKS line already
                # carries, from the SAME renderer (`debt._near_miss_clause`, ONE wording home); this
                # seam only appends it. Without it this line reads identically whether the author
                # emitted nothing at all or emitted a `check_admission_demonstrated` row the fold
                # rejected — and a reader who has just emitted concludes the mechanism is broken.
                # Inherits suppressed-when-clean from the `oi > 0` guard it sits inside. Report-only.
                _inv_near_miss = _oi.get("near_miss_clause") or ""
                _rewired = [i for i in _unproven if i.get("admission") == "rewired"]
                _stale_clause = ""
                if _rewired:
                    _since = _rewired[0].get("superseded_at")
                    _stale_clause = (f" ({len(_rewired)} REWIRED — the recorded demonstration proved a "
                                     f"definition that no longer exists"
                                     + (f", stale since {_since}" if _since else "") + ")")
                lines.append(
                    f"debt: {len(_unproven)} declared outcome-invariant(s) UNPROVEN{_stale_clause} — "
                    f"{_name_inv(_unproven)}: no recorded failing demonstration, so nothing shows the probe "
                    f"can go RED when its subsystem breaks — its green means nothing (SPEC-0156). Break each "
                    f"one's subject deliberately, watch it go RED, then record `bin/yitc-v2 event "
                    f"check_admission_demonstrated`. See `bin/yitc-v2 debt`."
                    f"{_inv_near_miss}")
    # REMOTE-LAG view (SPEC-0119 rule 20 / SPEC-0163, T-11187 / X-0932): the OPTIONAL injected fold over
    # THIS repo's ops carrier + LOCAL git refs — how far a project's declared OFFSITE copy has fallen
    # behind its integration branch (`debt.remote_lag`). The collaborator answers the ask X-0932 made
    # (an offsite copy must not SILENTLY fall behind) WITHOUT giving `land` a network side effect: the
    # harm <collaborator> named is the SILENCE, and a surfaced count removes it while a push inside land would add
    # an outbound external mutation (SPEC-0116) and a new mid-land failure class. Opt-in through the
    # EXISTING SPEC-0163 `remote_sync.remote` declaration — a project declaring nothing or WAIVING folds
    # to `not-declared` and contributes NOTHING, i.e. behaves exactly as today. Same discipline as every
    # sibling: report-only, suppressed-when-clean, NEVER gates.
    #
    # UNFLOORED, deliberately: an offsite copy ONE commit behind is already the state this exists to
    # make visible, and the whole failure mode is a count that grows unwatched — so a floor would
    # re-hide precisely the early reading that is cheapest to act on.
    #
    # THE DEGRADES PRINT TOO, and that is the point. `not-declared` is silent (a real opt-out), but a
    # carrier that could not be READ, a MALFORMED declaration, a declared remote that is NOT CONFIGURED,
    # and a MISSING tracking ref each get their own line rather than rendering as "in sync". A project
    # that MEANT to declare must never be silently read as having declared nothing — the false-zero this
    # view must never have (the rule-23 live-revision adapter's named-degrade discipline).
    if _remote_lag is not None:
        _rl = _remote_lag() or {}
        if isinstance(_rl, dict):
            _st = _rl.get("status")
            _rem = _rl.get("remote")
            _br = _rl.get("branch")
            _remc = f" `{_rem}`" if _rem else ""
            # THE REMEDY MUST CLEAR THE SIGNAL IT PRINTS (T-11424 / kupiclub X-1094). The prose names
            # the DECLARED remote (what the project wrote); the `git push` names the RESOLVED
            # CONFIGURED NAME. They differ exactly when the declaration is a URL — and a push BY URL
            # updates the offsite copy while leaving refs/remotes/<name>/<branch>, this view's own
            # baseline, untouched. Printing the declared value there handed the reader a command that
            # succeeded and left the line saying the same thing (measured: pushed, exit 0, still "2
            # commit(s) BEHIND" naming the two commits just pushed). `or _rem` keeps any caller
            # injecting a pre-T-11424 dict rendering exactly as before rather than crashing.
            _push = _rl.get("push_remote") or _rem
            if _st == "behind":
                _cnt = _n(_rl.get("count"))
                if _cnt and _cnt > 0:
                    _CAP = 3
                    _cs = [c for c in (_rl.get("commits") or []) if isinstance(c, dict) and c.get("sha")]
                    _named = (" — " + ", ".join(f"{c.get('sha')} {c.get('subject')}" for c in _cs[:_CAP])
                              + (f" +{len(_cs) - _CAP} more" if len(_cs) > _CAP else "")) if _cs else ""
                    lines.append(
                        f"debt: the declared remote{_remc} is {_cnt} commit(s) BEHIND {_br}{_named} — this "
                        f"project's offsite copy has fallen behind and nothing else says so (SPEC-0119 rule "
                        f"20 / SPEC-0163). PUSH it (you, or the declared `pusher:` in yitc-ops.yaml): "
                        f"`git push {_push} {_br}`. Read LOCALLY from the remote-tracking ref, so this is "
                        f"the lag as of the last push/fetch from THIS machine and may over-report if "
                        f"someone else already pushed; `land` never contacts the remote and never will. "
                        f"See `bin/yitc-v2 debt`.")
            elif _st == "declared-remote-not-configured":
                lines.append(
                    f"debt: yitc-ops.yaml declares remote_sync.remote{_remc} but NO configured git remote "
                    f"matches it — this project believes it syncs somewhere it cannot push to, so its "
                    f"offsite copy is not merely behind, it does not exist (SPEC-0119 rule 20 / "
                    f"SPEC-0163). Either add the remote (`git remote add …`) or correct the declaration. "
                    f"See `bin/yitc-v2 debt`.")
            elif _st == "no-tracking-ref":
                _why = _rl.get("detail")
                lines.append(
                    f"debt: the declared remote{_remc} has no local tracking ref for {_br}"
                    + (f" ({_why})" if _why else "") +
                    f" — the lag CANNOT be computed, which is not the same as being in sync (SPEC-0119 "
                    f"rule 20). Push once, or fetch, and this line becomes a real reading. "
                    f"See `bin/yitc-v2 debt`.")
            elif _st in ("carrier-unreadable", "malformed-declaration"):
                _why = _rl.get("detail")
                lines.append(
                    f"debt: the remote-sync declaration could not be read ({_st}"
                    + (f": {_why}" if _why else "") +
                    f") — an INTENDED opt-in must never be silently read as declaring nothing, so this "
                    f"reports rather than suppresses (SPEC-0119 rule 20). Fix the `remote_sync:` section "
                    f"in yitc-ops.yaml (SPEC-0163). See `bin/yitc-v2 debt`.")
    # ABORT-CAUSE-BREADTH view (SPEC-0119 rule 26, T-11380 / the 2026-08-21 04:27-04:49 window): the
    # OPTIONAL injected fold over the journal — ONE land-abort cause that has refused several DIFFERENT
    # branches inside the window. The gap it fills is a partition gap, not a threshold gap: every
    # existing surface for a repeating abort is scoped to ONE lane (the re-run-vs-resolve discipline to a
    # SESSION, the T-0655 backstop to a BRANCH, the SPEC-0124 ceiling to a TASK), so a cause failing ONCE
    # on each of four branches trips none of them — measured, each branch re-diagnosed it independently
    # at 430-560s of verify apiece. Keyed on the SAME fine identity the backstop streaks on, so N aborts
    # of DIFFERENT causes CANNOT fire this (a line that fired on any burst of aborts would be filtered by
    # its reader inside a day, which is how a surface stops being read). Report-only,
    # suppressed-when-clean, no store, no event, and it names a CAUSE, never a candidate. A MITIGATION:
    # the freeze itself is fixed by making the gate branch-attributable (T-11379), not by this line.
    # T-11810 — the fold behind it now spans BOTH refusal shapes (a land abort AND a red-batch
    # requeue, `land_member_verdict`), because a red batch lands nobody and every member pays a full
    # verify that ships nothing; and each cause NAMES a failing assertion beside its digest, since the
    # digest alone was correct and unreadable (measured 2026-08-28 — the line fired and was read past).
    if _abort_cause_breadth is not None:
        _ab = _abort_cause_breadth() or {}
        abc = _n(_ab.get("count")) if isinstance(_ab, dict) else None
        if abc and abc > 0:
            _cs = _ab.get("causes") or []
            _cs = _cs if isinstance(_cs, list) else []
            _txt = "; ".join(x for x in (abort_cause_breadth_cause_line(c) for c in _cs[:2]) if x)
            _more = f" (+{abc - 2} more cause(s))" if abc > 2 else ""
            lines.append(
                f"debt: {abc} land-abort cause(s) refused SEVERAL DIFFERENT branches in the last "
                f"{_ab.get('window_hours')}h"
                + (f" — {_txt}{_more}" if _txt else "") +
                f". Each of those branches diagnosed the SAME cause independently and paid a full "
                f"verify to do it: no existing surface spans branches (the re-run-vs-resolve discipline "
                f"is per SESSION, the repeated-abort backstop per BRANCH, the audit-loop ceiling per "
                f"TASK), so nothing folded the recurrence. Read ONE of the named branches' abort rows, "
                f"then fix the cause ON MAIN — or make the gate branch-attributable (T-11379), which is "
                f"the actual fix; this line only makes an ongoing freeze visible sooner. SURFACING "
                f"ONLY — it names a CAUSE, selects nothing and refuses nothing; a branch drops off "
                f"the row the MOMENT IT LANDS and the whole row goes silent when the last one does, "
                f"not when the window expires (SPEC-0119 rule 26, T-12052). See `bin/yitc-v2 debt`.")

    # STUCK-BRANCH UNLANDED-ATTEMPT view (SPEC-0119 rule 34, T-11821): the TRANSPOSE of the fold
    # directly above — ONE BRANCH burning repeated unlanded land attempts, WHATEVER the cause each
    # time. Rule 26 reads one cause across many branches; this reads one branch across many causes,
    # over the SAME already-emitted rows and the SAME two refusal shapes. The gap is a KEYING gap,
    # not a threshold gap: every surface that could catch a stuck branch is keyed on the REPETITION
    # OF A CAUSE (the T-0655 backstop arms only on consecutive aborts sharing a cause key, the
    # SPEC-0124 ceiling counts audit passes per TASK, re-run-vs-resolve is per SESSION, rule 27
    # groups BY CLASS so one branch's several classes never sum), so a branch failing for a
    # different reason each time trips none of them. Sharper, and measured 2026-08-28: a whole
    # FAMILY of abort classes carries NO cause identity at all, so consecutive aborts within it are
    # INCOMPARABLE rather than merely different — such a branch is structurally UN-ARMABLE, and no
    # threshold on a key that does not exist will ever fire. The COUNT of attempts is the key; the
    # elapsed span and the distinct-class count ride IN the line as annotations, because a bare
    # count cannot tell a three-hour burn from a three-minute one. Report-only, suppressed-when-
    # clean, no store, no event: the external adjudication rejected a cause-agnostic GATE as a first
    # move because it would confuse stuckness with LEGITIMATE ITERATION — a branch that resolves a
    # merge conflict, then refreshes audit currency, then fixes verify fallout is making real
    # forward progress, which is exactly what task/T-11810 did before landing on its sixth attempt.
    if _branch_attempt_burn is not None:
        _bb = _branch_attempt_burn() or {}
        bbc = _n(_bb.get("count")) if isinstance(_bb, dict) else None
        if bbc and bbc > 0:
            _brs = [b for b in (_bb.get("branches") or []) if isinstance(b, dict)]
            def _one_burn(b):
                # The two ANNOTATIONS the adjudication named, both IN the line: the elapsed span
                # and the distinct-class count. Rendered in whole minutes/hours from the fold's
                # seconds — the fold carries no duration vocabulary (SPEC-0149's structural
                # tripwire over `bin/lib/debt.py`), so the formatting belongs on this side.
                _el = b.get("elapsed_seconds")
                _el = _el if isinstance(_el, int) else 0
                _span = (f"{_el // 3600}h{(_el % 3600) // 60:02d}m" if _el >= 3600
                         else f"{max(_el // 60, 0)}m")
                _cls = [str(c) for c in (b.get("classes") or [])][:3]
                _cls_txt = ", ".join(_cls) + ("…" if b.get("class_count", 0) > 3 else "")
                # The INCOMPARABLE clause — printed only when it applies, and worded as the
                # measurement found it. These attempts carry NO cause identity, so their keys cannot
                # be COMPUTED: it is not that the reasons differed, it is that they cannot be
                # compared at all, which is why the repeated-abort backstop never armed.
                _inc = b.get("incomparable")
                _inc_txt = (f", {_inc} of them carrying NO cause identity at all (INCOMPARABLE, "
                            f"not merely different — the backstop cannot arm on them)"
                            if isinstance(_inc, int) and _inc > 0 else "")
                return (f"{b.get('branch')} — {b.get('attempts')} attempt(s) over {_span} across "
                        f"{b.get('class_count')} distinct abort class(es)"
                        + (f" ({_cls_txt})" if _cls_txt else "") + _inc_txt)
            _txt = "; ".join(x for x in (_one_burn(b) for b in _brs[:2]) if x)
            _more = f" (+{bbc - 2} more branch(es))" if bbc > 2 else ""
            lines.append(
                f"debt: {bbc} branch(es) burned {_bb.get('min_attempts')}+ UNLANDED land attempts "
                f"in the last {_bb.get('window_hours')}h, whatever the cause each time"
                + (f" — {_txt}{_more}" if _txt else "") +
                f". Each attempt paid a verify and shipped nothing, and no existing surface can see "
                f"it: every one of them is keyed on the REPETITION OF A CAUSE (the repeated-abort "
                f"backstop arms only on consecutive aborts sharing a cause key, the audit-loop "
                f"ceiling counts audit passes per TASK, re-run-vs-resolve is per SESSION, and the "
                f"aborted-land cost view groups BY CLASS so one branch's several classes never "
                f"sum), so a branch that fails for a different reason each time trips none of them. "
                f"Read that branch's abort rows END TO END rather than the latest one — the "
                f"question is whether the attempts are converging or circling. SURFACING ONLY — it "
                f"names a BRANCH, selects nothing, refuses nothing and excludes nothing from a "
                f"batch; the row drops by itself once the branch lands or falls out of the window "
                f"(SPEC-0119 rule 34). See `bin/yitc-v2 debt`.")

    # T-11396 (SPEC-0119 rule 28): A RECORDED MEASUREMENT DRIFTING TOWARD ITS OWN FLOOR.
    # SPEC-0161's recorded payload-key candidate set is a number written down once, which a land-verify
    # gate re-computes live and compares against. It drifts by construction as the corpus grows, and
    # that drift is NOT a defect — the gate's own comment says so. What is a defect is being told about
    # it by a hard land refusal: on 2026-08-21 coverage reached 79% against the 0.80 bar and refused
    # `work/spec0161-name-acceptance-probe-recorded` — the land of the very card filed to unblock a
    # frozen branch — with ten governing pairs unnamed, on a session that had not caused any of it.
    # This line reports the APPROACH, so the refresh is ordinary maintenance done when someone chooses.
    # It GATES nothing, refuses nothing, refreshes nothing and moves no floor (a record that refreshed
    # itself would stop being a measurement). Suppressed-when-clean, like every sibling here.
    if _recorded_measurement is not None:
        _rm = _recorded_measurement() or {}
        rmc = _n(_rm.get("count")) if isinstance(_rm, dict) else None
        if rmc and rmc > 0:
            _cov, _flr = _rm.get("coverage"), _rm.get("floor")
            _un = [f"{t}.{k}" for t, k in (_rm.get("unnamed") or [])]
            _un_txt = ", ".join(_un[:3]) + (f" +{len(_un) - 3} more" if len(_un) > 3 else "")
            _at_or_under = isinstance(_cov, (int, float)) and isinstance(_flr, (int, float)) and _cov <= _flr
            lines.append(
                f"debt: SPEC-0161's recorded payload-key measurement is at "
                f"{_cov:.0%} coverage of {_rm.get('governing_count')} governing pair(s) against its own "
                f"{_flr:.0%} floor"
                + (" — ALREADY AT OR BENEATH IT, so a land is being refused right now"
                   if _at_or_under else
                   f" (headroom {_rm.get('headroom'):.0%})")
                + (f"; {len(_un)} pair(s) unnamed: {_un_txt}" if _un else "")
                + ". That record is a MEASUREMENT a land-verify gate re-computes and compares against, "
                "and it drifts as the corpus grows — the drift is not a defect, but discovering it as a "
                "hard land refusal is: on 2026-08-21 it refused the land of the very card filed to "
                "unblock a frozen branch, on a session that had not caused it. Re-run SPEC-0161's "
                "PAYLOAD-KEY half and refresh its recorded candidate set + counts. Doing it now is one "
                "ordinary edit; doing it after the floor is crossed costs a refused land plus the "
                "re-measurement, paid by whoever happens to be landing. REPORT-ONLY — this gates "
                "nothing, refuses nothing, refreshes nothing and moves no floor (SPEC-0119 rule 28). "
                "See `bin/yitc-v2 debt`.")
    return lines


_CONSUMER_DEPLOY_POLICY_LENS = (
    "consumer-deploy-policy (T-10047 / X-0187 / SPEC-0097) — every registry yitc_v2 CONSUMER's "
    "deploy-autonomy stance side by side: the deploy.policy classes DECLARED (A/S/C1/C2 opt-in) vs "
    "WAIVED (owner-gated every deploy), and the security section DECLARED (probes) vs WAIVED (with its "
    "compensating_control + expiry). DERIVED at read time from each consumer's yitc-ops.yaml carrier "
    "(SPEC-0093); zero stored state (P5). Read-only review lens — NO gate, NO event; the engine itself "
    "is excluded (not a deploy consumer, no yitc-ops.yaml)."
)


def _view_consumer_deploy_policy(*, registry_path=None, engine_root=None, kernel_name=None,
                                 _v2_projects=None, _read_yaml=None) -> dict:
    """consumer-deploy-policy lens (T-10047 / X-0187 / SPEC-0097): the deploy-autonomy stance of EVERY
    registry yitc_v2 CONSUMER, side by side, so divergence + declare-or-waive gaps are visible in one
    glance (the X-0187 incident: boomrocket born-WAIVED despite JWT/telegram auth + PII, social-parser
    opted-in A/S/C1 — same SPEC-0097 vocab, ad-hoc per-project). A pure DERIVED review view (D-0053):
    stores the QUERY, recomputes fresh on read from each consumer's yitc-ops.yaml carrier (SPEC-0093
    rule 7 / P5) — no new store, no new node/edge, no gate, no event.

    Enumeration REUSES `_v2_projects(registry_path, engine_root, kernel_name)` (the read-only registry
    scan the nightly + cross-peer set already use, D-0019-safe) and EXCLUDES the engine/kernel itself
    (name == kernel_name OR resolved path == engine_root): the engine is not a deploy consumer and owns
    no yitc-ops.yaml, so it belongs in a note, never a table row (audit-pre finding 2). Reading a
    consumer's yitc-ops.yaml is read-only (territory-safe, like the `cross inbox` fold / nightly scan).

    Fail-OPEN per row (the test-orientation precedent): a missing / unreadable / non-mapping carrier
    yields a `no-carrier` / `unreadable` stance, never a crash — a broken consumer carrier must not
    take down the whole review.

    Per consumer two stances are surfaced:
      - deploy.policy: `declared` (a non-empty `classes:` mapping → the opted-in A/S/C1/C2 keys) vs
        `waived` (owner-gated every deploy — the pre-policy default) vs `no-policy` (no deploy.policy
        block) vs `malformed`.
      - security: `declared` (a `probes:` list → count) vs `waived` (+ whether a compensating_control
        and an expiry are present — the STRICT-waiver shape, SPEC-0093 rule 6) vs `no-section`.
    A `divergence` summary counts declared-vs-waived across consumers so an at-a-glance gap is obvious."""
    from pathlib import Path
    consumers: list = []
    notes: list = []
    excluded: list = []

    engine_resolved = Path(engine_root).resolve() if engine_root is not None else None
    try:
        projects = _v2_projects(registry_path, engine_root, kernel_name)
    except Exception as exc:  # noqa: BLE001 — a bad registry must never crash the review lens
        return {
            "lens": _CONSUMER_DEPLOY_POLICY_LENS,
            "consumer_count": 0, "consumers": consumers,
            "notes": [f"registry unreadable ({type(exc).__name__}: {exc}) — no consumers to review."],
        }

    for proj in projects:
        name = proj.get("name")
        path = proj.get("path")
        # Exclude the engine/kernel itself (audit-pre finding 2) — not a deploy consumer.
        try:
            resolved = Path(path).resolve() if path is not None else None
        except Exception:  # noqa: BLE001
            resolved = None
        if name == kernel_name or (engine_resolved is not None and resolved == engine_resolved):
            excluded.append(name)
            continue

        ops_path = (Path(path) / "yitc-ops.yaml") if path is not None else None
        # FAIL-OPEN per row: a broken carrier (unreadable / non-decodable / non-mapping) must NOT abort
        # the whole review. `_read_yaml` swallows a YAMLError to {}, but a read-side fault (permissions,
        # a non-UTF8 file, a path that is a dir) can still raise — so guard the read itself.
        if ops_path is None or not ops_path.is_file():
            ops = None
        else:
            try:
                ops = _read_yaml(ops_path)
            except Exception:  # noqa: BLE001 — one bad consumer carrier must never crash the lens
                ops = "__unreadable__"
        if not isinstance(ops, dict):
            stance = "no-carrier" if ops is None else "unreadable"
            consumers.append({
                "name": name,
                "deploy_policy": {"stance": stance},
                "security": {"stance": stance},
            })
            continue

        # deploy.policy stance
        deploy = ops.get("deploy")
        policy = deploy.get("policy") if isinstance(deploy, dict) else None
        dp: dict = {}
        if not isinstance(policy, dict):
            dp["stance"] = "no-policy"
        else:
            classes = policy.get("classes")
            if isinstance(classes, dict) and len(classes) > 0:
                dp["stance"] = "declared"
                dp["classes"] = sorted(classes.keys())
            elif isinstance(classes, dict):  # empty mapping — not a declaration (init sweep rejects it)
                dp["stance"] = "waived"
                dp["note"] = "empty classes: {} — not a declaration (owner-gated)"
            elif classes is not None:
                dp["stance"] = "malformed"
                dp["note"] = f"classes: is {type(classes).__name__}, expected a mapping"
            else:
                waiver = policy.get("waiver")
                dp["stance"] = "waived" if isinstance(waiver, dict) else "no-policy"
                if isinstance(waiver, dict) and isinstance(waiver.get("reason"), str):
                    dp["waiver_reason"] = waiver["reason"]
            # surface a recommended-template presence flag (born default, this task) — informational
            if isinstance(policy.get("recommended"), dict) and policy["recommended"]:
                dp["has_recommended_template"] = True

        # security stance
        sec = ops.get("security")
        sc: dict = {}
        if not isinstance(sec, dict):
            sc["stance"] = "no-section"
        else:
            probes = sec.get("probes")
            waiver = sec.get("waiver")
            if isinstance(probes, list) and len(probes) > 0:
                sc["stance"] = "declared"
                sc["probe_count"] = len(probes)
            elif isinstance(waiver, dict):
                sc["stance"] = "waived"
                sc["compensating_control"] = bool(waiver.get("compensating_control"))
                sc["expiry"] = waiver.get("expiry")
            else:
                sc["stance"] = "no-section"

        consumers.append({"name": name, "deploy_policy": dp, "security": sc})

    dp_declared = sum(1 for c in consumers if c["deploy_policy"].get("stance") == "declared")
    dp_waived = sum(1 for c in consumers if c["deploy_policy"].get("stance") == "waived")
    sec_declared = sum(1 for c in consumers if c["security"].get("stance") == "declared")
    sec_waived = sum(1 for c in consumers if c["security"].get("stance") == "waived")

    if excluded:
        notes.append("engine/kernel excluded (not a deploy consumer, no yitc-ops.yaml): "
                     + ", ".join(str(e) for e in excluded if e is not None))
    notes.append("stance is DECLARED-config only (SPEC-0093 rule 7) — the review surfaces divergence; "
                 "close a gap with a per-project card / `cross request` (NOT in this lens, X-0187 follow-on).")

    return {
        "lens": _CONSUMER_DEPLOY_POLICY_LENS,
        "consumer_count": len(consumers),
        "divergence": {
            "deploy_policy_declared": dp_declared,
            "deploy_policy_waived": dp_waived,
            "security_declared": sec_declared,
            "security_waived": sec_waived,
        },
        "consumers": consumers,
        "notes": notes,
    }


_MANDATORY_CONCERN_GAPS_LENS = (
    "mandatory-concern-gaps (T-11016 / SPEC-0128 / SPEC-0093) — WHO OWES WHAT RIGHT NOW: every registry "
    "yitc_v2 project with an UNANSWERED MANDATORY concern, in one read, without waiting for a session to "
    "open in that project. Per concern the projects that owe an answer, per project the concerns it owes. "
    "DERIVED at read time from the kernel concern registry (`presence_policy: mandatory`) + each project's "
    "yitc-ops.yaml declare-or-waive stance, evaluated through the SAME `_ops_carrier_violations` the init "
    "sweep fails closed on (CHARTER §P5 — one stance evaluator, no parallel ladder); zero stored state. "
    "Read-only review lens — NO gate, NO event, NO nag report. OPT-IN concerns are excluded BY "
    "CONSTRUCTION, so a project that genuinely owes nothing never appears; a project that has ANSWERED "
    "(declared OR waived) does not appear for that concern."
)


def _view_mandatory_concern_gaps(*, registry_path=None, engine_root=None, kernel_name=None,
                                 _v2_projects=None, _read_yaml=None) -> dict:
    """mandatory-concern-gaps lens (T-11016): the fleet-altitude answer to "which projects owe an
    unanswered MANDATORY concern right now?".

    WHY A FLEET ALTITUDE (the card's surviving justification). The per-project concern seams are sound
    but LATENT: the `-C` session-start drift echo only speaks when someone OPENS a session in that
    project, so a dormant project accrues an unanswered mandatory concern and learns nothing until it is
    visited. That is a delivery-latency property of a per-project seam, not a defect in it. This lens
    answers the same question at fleet altitude, on demand, recomputed fresh.

    IT IS A DIFFERENT PREDICATE FROM THE NIGHTLY'S DRIFT CHECK, deliberately (measured 2026-08-13).
    `nightly._check_concern_drift` / `init.concern_drift` (SPEC-0143) asks whether the consumer's
    `adoption:` LEDGER kept up with contract-VERSION moves; this asks whether the CARRIER answers the
    concern at all (declare-or-waive). They diverge in both directions: drift reported
    boomrocket/spike_sandbox `un-adopted` while that carrier DECLARES `spike_sandbox.bridge` (already
    answered — no gap here), and drift reports non-mandatory concerns (kupiclub/freshness) that this
    lens excludes. Reading drift as "who owes an answer" over-reports; that conflation is what produced
    a wrong fleet answer by hand.

    A pure DERIVED review view (D-0053), built to the `consumer-deploy-policy` precedent (T-10047):
    stores the QUERY, recomputes on read from state that already exists — no new store, no cache, no
    fourth concern, no parallel concern registry. Enumeration REUSES `_v2_projects` (the read-only
    registry scan the nightly + cross-peer set use, D-0019 territory-safe) and EXCLUDES the
    engine/kernel itself (name == kernel_name OR resolved path == engine_root): it owns no yitc-ops.yaml.
    Reading a peer's carrier is read-only; nothing is ever written to another repo.

    THREE PROPERTIES THAT ARE THE POINT, not incidental:
      - MANDATORY-ONLY, by construction. The concern set is filtered on `presence_policy: mandatory`, so
        an OPT-IN concern (`sandbox_entry`, `coverage`, `extensions`, …) can never enter it. Opt-in
        silence is therefore never reported as debt — a view that manufactured fleet-wide obligation out
        of an opt-in concern would be worse than no view.
      - DIFFERENTIAL. A project appears for a concern ONLY when it has answered NEITHER way; a coherent
        `waiver:` is an ANSWER (ticket-review waiving `spike_sandbox` as a pure library is absent from
        that concern's row). A project with no gaps is omitted entirely — a view listing everyone proves
        nothing.
      - DECLARE-OR-WAIVE ONLY. The match is on the stance verdict for the concern's own carrier label; a
        NESTED shape-hook residual (`spike_sandbox.bridge: …`) is not a missing ANSWER and is left to
        `concern_conformance` / the init sweep. Stated in `notes` so the boundary is read, not inferred.

    Fail-OPEN per row (the consumer-deploy-policy precedent): a missing / unreadable / non-mapping
    carrier becomes a `not_assessed` row carrying its reason — NEVER a gap row (inventing debt for a
    project we could not read is the same manufacturing this lens exists to avoid) and never a crash. A
    broken REGISTRY yields an empty result plus a note. The kernel concern registry itself is NOT
    fail-opened: `_load_concern_registry` is fail-closed by contract (a silent empty roster would render
    every project spuriously clean), so a broken kernel registry surfaces loudly."""
    from pathlib import Path

    from lib import init as initmod   # CHARTER §P5 — the one concern-registry + stance-evaluator home

    by_project: list = []
    not_assessed: list = []
    notes: list = []
    excluded: list = []
    owing: dict = {}

    # The MANDATORY slice of the kernel registry, in registry order. `label` is the dotted carrier path
    # the stance evaluator prefixes its verdict strings with (`carrier_path` falls back to `section`).
    concerns: list = []
    for entry in initmod._load_concern_registry():
        if not isinstance(entry, dict) or entry.get("presence_policy") != "mandatory":
            continue
        section = entry.get("section")
        label = entry.get("carrier_path") or section
        if not (isinstance(label, str) and label.strip() and isinstance(section, str)):
            continue                                  # a mis-declared registry entry — `graph build` flags it
        concerns.append({"section": section, "label": label, "spec": entry.get("spec")})

    engine_resolved = Path(engine_root).resolve() if engine_root is not None else None
    try:
        projects = _v2_projects(registry_path, engine_root, kernel_name)
    except Exception as exc:  # noqa: BLE001 — a bad registry must never crash the review lens
        return {
            "lens": _MANDATORY_CONCERN_GAPS_LENS,
            "gap_count": 0, "concerns_assessed": [c["section"] for c in concerns],
            "by_concern": [], "by_project": [], "not_assessed": [],
            "notes": [f"registry unreadable ({type(exc).__name__}: {exc}) — no projects to assess."],
        }

    for proj in projects:
        name = proj.get("name")
        path = proj.get("path")
        try:
            resolved = Path(path).resolve() if path is not None else None
        except Exception:  # noqa: BLE001
            resolved = None
        if name == kernel_name or (engine_resolved is not None and resolved == engine_resolved):
            excluded.append(name)
            continue

        ops_path = (Path(path) / "yitc-ops.yaml") if path is not None else None
        if ops_path is None or not ops_path.is_file():
            not_assessed.append({"name": name, "status": "no-carrier"})
            continue
        try:
            ops = _read_yaml(ops_path)
        except Exception:  # noqa: BLE001 — one bad carrier must never crash the lens
            ops = None
            not_assessed.append({"name": name, "status": "unreadable"})
            continue
        if not isinstance(ops, dict):
            not_assessed.append({"name": name, "status": "unreadable"})
            continue
        try:
            violations = initmod._ops_carrier_violations(ops)
        except Exception:  # noqa: BLE001 — the evaluator is pure, but a report-only lens never raises
            not_assessed.append({"name": name, "status": "unreadable"})
            continue

        unanswered: list = []
        reasons: dict = {}
        for c in concerns:
            hit = next((v for v in violations if v.startswith(c["label"] + ": ")), None)
            if hit is None:
                continue                              # DECLARED or WAIVED — answered, so no row
            unanswered.append(c["section"])
            reasons[c["section"]] = hit
        if unanswered:                                # a project with zero gaps is omitted entirely
            by_project.append({"name": name, "unanswered": unanswered, "reasons": reasons})
            for section in unanswered:
                owing.setdefault(section, []).append(name)

    by_concern = [{"concern": c["section"], "spec": c["spec"],
                   "project_count": len(owing[c["section"]]), "projects": list(owing[c["section"]])}
                  for c in concerns if owing.get(c["section"])]

    if excluded:
        notes.append("engine/kernel excluded (owns no yitc-ops.yaml): "
                     + ", ".join(str(e) for e in excluded if e is not None))
    notes.append("MANDATORY-ONLY by construction — an OPT-IN concern (sandbox_entry, coverage, "
                 "extensions, …) is never in the assessed set, so a project that genuinely owes nothing "
                 "never appears here.")
    notes.append("DECLARE-OR-WAIVE stance only (the same `_ops_carrier_violations` verdict the init "
                 "sweep fails closed on) — a coherent `waiver:` IS an answer. Deep shape residuals, "
                 "non-mandatory sections and adopted-version drift are OTHER questions: see "
                 "`bin/yitc-v2 debt` / the nightly's concern_conformance + concern_drift checks.")
    if not_assessed:
        notes.append(f"{len(not_assessed)} project(s) not assessed (no or unreadable yitc-ops.yaml) — "
                     "reported as-is, never counted as owing (fail-open per row).")
    notes.append("Read-only: answering a gap is the project's OWN governed `-C` carrier op (declare the "
                 "concern's key, or `waiver: {reason: <why>}`) — never a kernel push, never an edit "
                 "from here (D-0019).")

    return {
        "lens": _MANDATORY_CONCERN_GAPS_LENS,
        "gap_count": sum(len(p["unanswered"]) for p in by_project),
        "project_count": len(by_project),
        "concerns_assessed": [c["section"] for c in concerns],
        "by_concern": by_concern,
        "by_project": by_project,
        "not_assessed": not_assessed,
        "notes": notes,
    }


_SANDBOX_FAMILY_LENS = (
    "sandbox-family (T-11018 / SPEC-0169 / SPEC-0172 / SPEC-0175) — THE SANDBOX QUESTION ANSWERED FROM "
    "ANY ONE OF ITS THREE KEY NAMES: `sandbox_entry` (WHERE a collaborator enters — opt-in), "
    "`spike_sandbox` (WHETHER a caged bridge exists, its pinned release — declare-or-waive) and "
    "`spike_data_safety` (WHAT the restored copy carries — mandatory) are three DISTINCT concerns, and a "
    "reader who knows only one of the names cannot see the other two. This lens groups them: per project, "
    "does it run a sandbox at all, and what has it answered. NAVIGATION ONLY — it merges nothing, renames "
    "nothing, adds no fourth concern and no store, and turns the opt-in `sandbox_entry` into no one's "
    "obligation. DERIVED on read from the kernel concern registry (SPEC-0128) x each project's "
    "yitc-ops.yaml stance, through the SAME `_ops_carrier_violations` evaluator the init sweep fails "
    "closed on. Read-only: NO gate, NO event, NO nag."
)

# The presence-bearing family members — the concerns whose DECLARATION asserts a sandbox EXISTS. Absorbed
# audit-pre finding (T-11018, mode-a): `spike_data_safety` answers what a restored copy CARRIES, so a
# project must not be classified as HAVING a sandbox from its data floor alone while entry/bridge are
# absent or waived. It is still reported as a family answer, and a lone declaration of it is surfaced as a
# signal to read (`evidence`) — never as the verdict.
_SANDBOX_PRESENCE_MEMBERS = ("sandbox_entry", "spike_sandbox")


def _view_sandbox_family(members=None, *, registry_path=None, engine_root=None, kernel_name=None,
                         _v2_projects=None, _read_yaml=None) -> dict:
    """sandbox-family lens (T-11018): "does this project run a sandbox, and which of the sandbox
    questions has it answered?" — answerable from ANY ONE of the three concern key names.

    THE INCIDENT IS THE SPEC (2026-08-13, X-0852). A controller searched the fleet for the key name
    `spike_sandbox`, found none in kupiclub, and concluded kupiclub had no sandbox. It has one — declared
    under `sandbox_entry`. A second miss followed on boomrocket, where the key was present but its VALUE
    unread. A reader with full repo access navigated wrong twice in one sitting. The three concerns are
    CORRECT and stay distinct (an external consult confirmed: the schema is not what failed, navigation
    is) — so this is the consult's option (ii): a derived GROUPING that makes the family reachable from
    any one member. The hop back the other way (member -> family) is the one-line cross-reference each of
    SPEC-0169 / SPEC-0172 / SPEC-0175 carries in its body.

    MEMBERSHIP IS THE STORED QUERY, EVERYTHING ELSE IS DERIVED (D-0053 — a view stores the query, never a
    materialized output). `members` comes from `views/sandbox-family.yaml`'s `lens.members` (the
    `node-list` `lens.node_type` precedent), each row naming a `concern` section + the plain `question`
    that concern answers. Every other datum — spec id, carrier_path, declare_key/type, presence_policy —
    is read from the kernel concern registry (SPEC-0128) at read time, so a member cannot drift from its
    own contract. FAIL-CLOSED on membership: a named concern absent from the live registry is dropped
    from the assessed set and reported in `notes` (a silently-missing member would under-report the
    family, which is the exact failure this lens exists to end).

    THE VERDICT, AND WHY IT IS DERIVED THIS WAY:
      - `yes`     — a PRESENCE-BEARING member (`_SANDBOX_PRESENCE_MEMBERS`) is DECLARED. `sandbox_entry`
                    ALONE is sufficient — that IS the incident's differential: a carrier with no
                    `spike_sandbox` key still reads as HAVING a sandbox.
      - `no`      — no presence-bearing member declared AND at least one of them coherently WAIVED. A
                    pure library that waived both is the intended reading here.
      - `unknown` — neither. Silence is never read as either answer.
    It reads DECLARATIONS, never values (a value heuristic is the behavioral-detector class CHARTER §6
    forbids): `enabled: false` under a declared bridge is an ANSWER, and nothing here parses a URL.

    THE OPT-IN BOUND IS THE POINT, not a detail. `open_questions` lists unanswered MANDATORY members —
    and is EMPTY for a `no` project: one that has coherently waived having a sandbox has no restored copy,
    so THIS family asks it nothing further. That scopes this lens's question; it erases no debt. The
    declare-or-waive stance itself stays fully visible in the sibling `mandatory-concern-gaps` view and in
    `bin/yitc-v2 debt`, and `notes` says so out loud so the boundary is read, not inferred. A project that
    genuinely runs no sandbox must never read as a gap — manufacturing obligation out of an opt-in concern
    would be worse than no view at all.

    Same fleet shape as `mandatory-concern-gaps` (T-11016): enumeration REUSES the read-only
    `_v2_projects` registry scan (D-0019 territory-safe — peer carriers are READ, never written), the
    engine/kernel is excluded (it owns no yitc-ops.yaml), and each row FAILS OPEN — a missing/unreadable/
    non-mapping carrier becomes a `not_assessed` row carrying its reason, never a verdict and never a
    crash. The kernel registry itself is NOT fail-opened (`_load_concern_registry` is fail-closed by
    contract). Zero stored state; recomputed fresh on every run."""
    from pathlib import Path

    from lib import init as initmod   # CHARTER §P5 — the one concern-registry + stance-evaluator home

    notes: list = []
    projects_out: list = []
    not_assessed: list = []
    excluded: list = []

    # ── membership (the stored query) x the live registry (the contract) ────────────────────────────
    registry = {}
    for entry in initmod._load_concern_registry():
        if isinstance(entry, dict) and isinstance(entry.get("section"), str):
            registry[entry["section"]] = entry

    assessed: list = []
    unknown_members: list = []
    for row in (members or []):
        if isinstance(row, str):
            row = {"concern": row}
        if not isinstance(row, dict):
            continue
        section = row.get("concern")
        if not (isinstance(section, str) and section.strip()):
            continue
        section = section.strip()
        entry = registry.get(section)
        if entry is None:
            unknown_members.append(section)           # named by the view, unknown to the kernel registry
            continue
        assessed.append({
            "concern": section,
            "question": row.get("question"),
            "spec": entry.get("spec"),
            "carrier_path": entry.get("carrier_path") or section,
            "declare_key": entry.get("declare_key"),
            "declare_type": entry.get("declare_type"),
            "presence_policy": entry.get("presence_policy"),
        })

    if unknown_members:
        notes.append("MEMBERSHIP INCOMPLETE — the view names concern(s) the live kernel registry does not "
                     "carry (" + ", ".join(sorted(unknown_members)) + "): they are NOT assessed. Fix the "
                     "member name in views/sandbox-family.yaml, or the concern's own `concern:` block.")

    engine_resolved = Path(engine_root).resolve() if engine_root is not None else None
    try:
        projects = _v2_projects(registry_path, engine_root, kernel_name)
    except Exception as exc:  # noqa: BLE001 — a bad registry must never crash the review lens
        return {
            "lens": _SANDBOX_FAMILY_LENS, "family": "spike-sandbox",
            "members": assessed, "projects": [], "not_assessed": [],
            "notes": notes + [f"registry unreadable ({type(exc).__name__}: {exc}) — no projects to assess."],
        }

    for proj in projects:
        name = proj.get("name")
        path = proj.get("path")
        try:
            resolved = Path(path).resolve() if path is not None else None
        except Exception:  # noqa: BLE001
            resolved = None
        if name == kernel_name or (engine_resolved is not None and resolved == engine_resolved):
            excluded.append(name)
            continue

        ops_path = (Path(path) / "yitc-ops.yaml") if path is not None else None
        if ops_path is None or not ops_path.is_file():
            not_assessed.append({"name": name, "status": "no-carrier"})
            continue
        try:
            ops = _read_yaml(ops_path)
        except Exception:  # noqa: BLE001 — one bad carrier must never crash the lens
            not_assessed.append({"name": name, "status": "unreadable"})
            continue
        if not isinstance(ops, dict):
            not_assessed.append({"name": name, "status": "unreadable"})
            continue
        try:
            violations = initmod._ops_carrier_violations(ops)
        except Exception:  # noqa: BLE001 — the evaluator is pure, but a report-only lens never raises
            not_assessed.append({"name": name, "status": "unreadable"})
            continue

        answers: dict = {}
        evidence: list = []
        declared_presence = False
        waived_presence = False
        open_questions: list = []
        for m in assessed:
            label = m["carrier_path"]
            present, section_val = initmod._ops_navigate(ops, label)
            declared = present and isinstance(section_val, dict) and initmod._ops_declared(
                section_val.get(m["declare_key"]), m["declare_type"])
            waived = present and isinstance(section_val, dict) and isinstance(
                section_val.get("waiver"), dict)
            # The stance verdict itself comes from the ONE evaluator — a label-prefixed violation means
            # the concern is UNANSWERED (neither coherently declared nor coherently waived).
            unanswered = any(v.startswith(label + ": ") for v in violations)
            if unanswered:
                stance = "unanswered"
            elif declared:
                stance = "declared"
            elif waived:
                stance = "waived"
            elif not present and m["presence_policy"] == "opt-in":
                # An OPT-IN concern the carrier is simply silent about owes nothing and asserts nothing.
                # Reporting that silence as "answered" would read as a stance the project never took.
                stance = "silent"
            else:                                     # answered per the evaluator, shape unrecognised here
                stance = "answered"
            answers[m["concern"]] = stance
            if stance == "declared":
                evidence.append(f"{label}.{m['declare_key']} declared")
                if m["concern"] in _SANDBOX_PRESENCE_MEMBERS:
                    declared_presence = True
            elif stance == "waived" and m["concern"] in _SANDBOX_PRESENCE_MEMBERS:
                waived_presence = True
                evidence.append(f"{label} waived")
            if stance == "unanswered" and m["presence_policy"] == "mandatory":
                open_questions.append(m["concern"])

        if declared_presence:
            sandbox = "yes"
        elif waived_presence:
            sandbox = "no"
        else:
            sandbox = "unknown"

        if sandbox == "no":
            # THE OPT-IN BOUND (AC3): a project that coherently waived having a sandbox owes this family
            # nothing further — it has no restored copy for a data floor to describe. Scoping, not erasure:
            # the declare-or-waive stance debt stays visible in `mandatory-concern-gaps` / `debt`.
            deferred = list(open_questions)
            open_questions = []
            if deferred:
                evidence.append("no sandbox declared — this family asks nothing further; the "
                                + ", ".join(deferred) + " stance itself is `mandatory-concern-gaps`' "
                                "question, not this one")
        elif sandbox == "unknown" and answers.get("spike_data_safety") == "declared":
            evidence.append("spike_data_safety declared while neither sandbox_entry nor spike_sandbox "
                            "declares one — a signal to read, not a verdict")

        # `answered` counts the questions this project actually TOOK a stance on — an opt-in concern it is
        # silent about is neither answered nor owed, so it counts as neither.
        projects_out.append({"name": name, "sandbox": sandbox, "answered": sum(
            1 for s in answers.values() if s in ("declared", "waived", "answered")), "answers": answers,
            "evidence": evidence, "open_questions": open_questions})

    notes.append("NAVIGATION ONLY — the three concerns stay DISTINCT and are neither merged nor renamed: "
                 "sandbox_entry = WHERE a collaborator enters (opt-in, a location never a credential, "
                 "SPEC-0169); spike_sandbox = WHETHER a caged bridge exists + its pinned release "
                 "(declare-or-waive, SPEC-0172); spike_data_safety = WHAT the restored copy carries "
                 "(mandatory, SPEC-0175). This view adds no fourth concern and no store.")
    notes.append("`sandbox: yes` is derived from a DECLARED presence-bearing member (sandbox_entry OR "
                 "spike_sandbox) — sandbox_entry ALONE suffices, which is the 2026-08-13 miss this lens "
                 "exists to end. `no` = none declared and one of them coherently WAIVED. `unknown` = "
                 "silence, never read as either answer. Declarations are read, values never are.")
    notes.append("OPT-IN BOUND: a `no` project owes this family nothing — `open_questions` is empty for "
                 "it by construction, so a pure library with a coherent waiver never reads as a gap. That "
                 "scopes THIS lens's question and erases no debt: an unanswered mandatory concern stays "
                 "fully visible in `bin/yitc-v2 graph query mandatory-concern-gaps` and `bin/yitc-v2 debt`.")
    if excluded:
        notes.append("engine/kernel excluded (owns no yitc-ops.yaml): "
                     + ", ".join(str(e) for e in excluded if e is not None))
    if not_assessed:
        notes.append(f"{len(not_assessed)} project(s) not assessed (no or unreadable yitc-ops.yaml) — "
                     "reported as-is, never given a verdict (fail-open per row).")
    notes.append("Read-only: answering a question is the project's OWN governed `-C` carrier op (declare "
                 "the concern's key, or `waiver: {reason: <why>}`) — never a kernel push, never an edit "
                 "from here (D-0019).")

    return {
        "lens": _SANDBOX_FAMILY_LENS,
        "family": "spike-sandbox",
        "members": assessed,
        "with_sandbox": [p["name"] for p in projects_out if p["sandbox"] == "yes"],
        "projects": projects_out,
        "not_assessed": not_assessed,
        "notes": notes,
    }


_TEST_ORIENTATION_LENS = (
    "test-orientation (T-9720 / X-0140 Card 3) — the project's DECLARED test rows bound to their "
    "moment/layer: the class×moment taxonomy (SPEC-0093 rule 10 `tests.classes[]`) + the land-verify "
    "layers (rule 16 `verify.layers[]`, moment=verify). DERIVED at read time from the yitc-ops.yaml "
    "carrier; zero stored state (rule 7 / P5). Read-only orientation — NO gate, NO event."
)

def _view_test_orientation(repo_root=None, *, _read_yaml=None) -> dict:
    """test-orientation lens (T-9720 / X-0140 Card 3): the project's DECLARED test rows bound to their
    `moment`/layer — the minimal class×moment orientation vocabulary X-0140 pulls (a read-only view, NOT
    a gate). DERIVED at read time from the SPEC-0093 `yitc-ops.yaml` carrier the project already
    declares; zero stored state (rule 7 / P5), recomputed fresh every run. Two declared sources, one flat
    `rows` binding:
      - `tests.classes[]` (rule 10 — the descriptive class×moment INVENTORY): each {class, moment}
        becomes a row {kind: class, class, moment, command?}.
      - `verify.layers[]` (rule 16 / T-9718 — the moment:verify executable LAND layers): each layer
        becomes a row {kind: layer, layer, moment: verify, status: declared|waived}.
    Each section is declare-OR-WAIVE (SPEC-0093): a section-level `waiver:` is surfaced as a `waived`
    note (not an error — this is a reader, never the fail-closed sweep). A consumer-only surface:
    OPT-IN / fail-OPEN like the overdue-recheck / not-adopted precedent — an absent/malformed carrier,
    or an absent/non-mapping section, yields clean-empty rows (the kernel's own repo has no
    `yitc-ops.yaml`, so it no-ops there), NEVER a crash. Read-only: adds NO gate and NO event (running
    the lens emits only the ambient cli_invoked P8 evidence, like every saved view)."""
    from pathlib import Path
    rows: list = []
    notes: list = []
    ops_path = (Path(repo_root) / "yitc-ops.yaml") if repo_root is not None else None
    ops = _read_yaml(ops_path) if (ops_path is not None and ops_path.is_file()) else None
    if not isinstance(ops, dict):
        if ops_path is None or not ops_path.is_file():
            notes.append("no yitc-ops.yaml carrier — no declared test taxonomy (the kernel's own repo "
                         "has none; this is a consumer surface).")
        else:
            notes.append("yitc-ops.yaml present but unreadable/non-mapping — nothing to orient.")
        return {
            "lens": _TEST_ORIENTATION_LENS,
            "row_count": 0, "rows": rows, "notes": notes,
            "next": "declare a `tests.classes:` (class×moment) and/or a `verify.layers:` list in "
                    "yitc-ops.yaml (SPEC-0093 rule 10 / SPEC-0152 rule 16) to populate this orientation.",
        }

    # tests.classes[] — the descriptive class×moment taxonomy (rule 10), declare-OR-waive (rule 6 loose).
    tests = ops.get("tests")
    if isinstance(tests, dict):
        if tests.get("waiver") is not None:
            notes.append("tests: section WAIVED — no class×moment taxonomy declared yet (rule 10).")
        classes = tests.get("classes")
        if isinstance(classes, list):
            for c in classes:
                if not isinstance(c, dict):
                    continue
                row = {"kind": "class", "class": c.get("class"), "moment": c.get("moment")}
                if c.get("command") is not None:
                    row["command"] = c.get("command")
                rows.append(row)

    # verify.layers[] — the moment:verify executable LAND layers (rule 16 / T-9718), per-layer declare-or-waive.
    verify = ops.get("verify")
    if isinstance(verify, dict):
        if verify.get("waiver") is not None:
            notes.append("verify: section WAIVED — no land-verify layer declared yet (rule 16).")
        layers = verify.get("layers")
        if isinstance(layers, list):
            for ly in layers:
                if not isinstance(ly, dict):
                    continue
                rows.append({
                    "kind": "layer",
                    "layer": ly.get("layer"),
                    "moment": "verify",
                    "status": "waived" if ly.get("waiver") is not None else "declared",
                })

    return {
        "lens": _TEST_ORIENTATION_LENS,
        "row_count": len(rows),
        "rows": rows,
        "notes": notes,
        "next": ("a test row's `moment` is the lifecycle seam its risk guards: `verify` rows run at "
                 "`land` (the per-layer gate, SPEC-0152 rule 16); `deploy-gate`/`post-deploy` rows run at "
                 "the deploy seam (SPEC-0094). Orientation only — adjust the declarations in yitc-ops.yaml."
                 if rows else
                 "the yitc-ops.yaml carrier declares no `tests.classes:` nor `verify.layers:` rows yet "
                 "(both absent or waived) — nothing to orient."),
    }

def _fmt_duration(seconds: float) -> str:
    """Human h/m/s for a wall-clock span (the scorecard's readable column beside raw seconds)."""
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m{s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h{m}m" if m else f"{h}h"

def _ts_delta_seconds(a: str, b: str):
    """Seconds between two ISO-Z timestamps (b − a). None if either is unparseable."""
    from datetime import datetime
    try:
        ta = datetime.fromisoformat(a.replace("Z", "+00:00"))
        tb = datetime.fromisoformat(b.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return (tb - ta).total_seconds()

def _stage_walls_from_boundaries(boundaries: list, last_close, *, _ts_delta_seconds=None,
                                 _fmt_duration=None) -> dict:
    """The per-stage WALL walk over one task's `stage_entered` boundaries (T-12008, extracted from
    `_view_task_scorecard` unchanged).

    `boundaries` is that task's (ts, stage) pairs in ts order; a stage's wall is the delta to the NEXT
    boundary, and the LAST stage runs to `last_close` (the task's final `task_closed` ts). A stage
    RE-ENTERED (the RED-loop case) sums into that stage's total and increments its `entries` count, so a
    re-entry is visible rather than averaged away. A boundary whose successor is missing or unparseable
    contributes NO seconds but still counts an entry — an unmeasurable span is never silently a zero.

    Extracted so the per-task lens (`task-scorecard`) and the windowed AGGREGATE (`stage-profile`) walk
    stages through ONE function: a second implementation could drift, and an aggregate that disagreed
    with the per-task figures it sums would be worse than no aggregate (CHARTER §Principle 5)."""
    per_stage: dict = {}
    for i, (ts, stage) in enumerate(boundaries):
        nxt = boundaries[i + 1][0] if i + 1 < len(boundaries) else last_close
        wall = _ts_delta_seconds(ts, nxt) if nxt else None
        rec = per_stage.setdefault(stage or "?", {"seconds": 0.0, "entries": 0})
        rec["entries"] += 1
        if wall is not None:
            rec["seconds"] += wall
    return {st: {"seconds": round(r["seconds"]), "human": _fmt_duration(r["seconds"]),
                 "entries": r["entries"]}
            for st, r in per_stage.items()}

def _view_task_scorecard(index: dict, target: "str | None", *, _find_task_yaml=None, _fmt_duration=None, _iter_events=None, _read_yaml=None, _ts_delta_seconds=None, _view_token_rollup=None) -> dict:
    """task-scorecard lens (T-0395): per-task lifecycle metrics for a closed task, ALL journal-derived
    (events.jsonl, the SoT) + the token-rollup lens (T-0394) reused verbatim for the cost column. Pure
    read, no store, recomputed fresh (D-0053). `index` is unused (the lens reads the journal, not the
    graph) — kept for the uniform _run_view lens signature.

    No target → a non-erroring usage record (keeps the every-view-executable sweep green; a no-arg run
    must never raise). With `target` = T-XXXX:
      - lead_time: FIRST task_picked.ts → LAST task_closed.ts (audit-pre F0 absorption — exact slice
        for reopen/red-loop tasks), + pick_count/close_count so a reopen is VISIBLE, not silently sliced.
      - per_stage_walls: per stage_entered, wall = next stage_entered.ts − this one (last → task_closed);
        repeated entries of one stage (RED-loop re-entry) summed into that stage's total + entries count.
      - audits: per stage (pre|post) → passes (count of audit_<stage>_completed), green_first, verdicts[].
      - land_attempts: land_completed on branch `task/T-XXXX` (BOTH ok+abort outcomes per scope).
      - deviations: deviation_captured whose data.relates_to carries an EXACT \\bT-XXXX\\b token
        (audit-pre F1 absorption — word-boundary, NOT naive substring; labelled heuristic since
        deviation events carry no structured task_id).
      - tokens_cost: distinct session_ref over the task's events; EXACTLY ONE → clean attribution
        (that session's totals from the token-rollup lens); 0/>1 → explicit n/a. token-rollup _die()s
        on a missing/stale archive (its raw source is gitignored, absent in worktrees) — WRAPPED in a
        SystemExit guard, degrading to n/a, never inheriting the hard-fail."""
    if not target:
        return {"task": None,
                "usage": "graph query task-scorecard T-XXXX",
                "note": "per-task scorecard for a closed task — pass a task id as the second positional"}

    import re as _re
    token = _re.compile(r"\b" + _re.escape(target) + r"\b")
    branch = "task/" + target

    own = []          # events carrying task_id == target
    lands = []        # land_completed on this task's branch
    deviations = 0    # deviation_captured relating to this task (token-matched)
    for e in _iter_events():
        if e.get("task_id") == target:
            own.append(e)
            continue
        typ = e.get("type")
        data = e.get("data") or {}
        if typ == "land_completed" and data.get("branch") == branch:
            lands.append(e)
        elif typ == "deviation_captured" and token.search(str(data.get("relates_to") or "")):
            deviations += 1

    def _by_ts(evs):
        return sorted(evs, key=lambda e: e.get("ts") or "")

    picks = [e for e in own if e.get("type") == "task_picked"]
    closes = [e for e in own if e.get("type") == "task_closed"]
    # title/status from the AUTHORED task YAML (was index['tasks'] — T-0492 cut migration). title lives
    # ONLY in the YAML and status IS the YAML `status:` field — neither is journal-derivable; the cut
    # index `tasks` section was a build-time projection OF this same SoT (CHARTER §P5, no parallel reader).
    _task_yaml = _find_task_yaml(target)
    _task_doc = _read_yaml(_task_yaml) if _task_yaml else None
    title = _task_doc.get("title") if isinstance(_task_doc, dict) else None
    status = _task_doc.get("status") if isinstance(_task_doc, dict) else None

    # --- lead_time: first pick → last close (F0) -------------------------------------------------
    lead = {"pick_count": len(picks), "close_count": len(closes)}
    first_pick = _by_ts(picks)[0]["ts"] if picks else None
    last_close = _by_ts(closes)[-1]["ts"] if closes else None
    if first_pick and last_close:
        secs = _ts_delta_seconds(first_pick, last_close)
        lead.update({"first_picked": first_pick, "last_closed": last_close,
                     "seconds": round(secs) if secs is not None else None,
                     "human": _fmt_duration(secs) if secs is not None else None})
    else:
        lead.update({"first_picked": first_pick, "last_closed": last_close,
                     "seconds": None, "human": "n/a", "reason": "missing task_picked or task_closed"})

    # --- per-stage walls (stage_entered deltas; last → close) ------------------------------------
    # T-12008: the walk itself lives in `_stage_walls_from_boundaries` — the SAME function the
    # stage-profile AGGREGATE calls per task, so the aggregate can never disagree with this lens
    # about what a stage cost (CHARTER §P5, one walk). This lens's output is unchanged.
    stage_evs = _by_ts([e for e in own if e.get("type") == "stage_entered"])
    boundaries = [(e["ts"], (e.get("data") or {}).get("stage")) for e in stage_evs if e.get("ts")]
    per_stage_walls = _stage_walls_from_boundaries(
        boundaries, last_close, _ts_delta_seconds=_ts_delta_seconds, _fmt_duration=_fmt_duration)

    # --- audits: passes + GREEN-first per stage --------------------------------------------------
    audits: dict = {}
    for stage_key, etype in (("pre", "audit_pre_completed"), ("post", "audit_post_completed")):
        verdicts = [(e.get("data") or {}).get("verdict") for e in _by_ts([x for x in own if x.get("type") == etype])]
        if verdicts:
            audits[stage_key] = {"passes": len(verdicts),
                                 "green_first": verdicts[0] == "GREEN",
                                 "verdicts": verdicts}

    # --- land attempts (both outcomes) -----------------------------------------------------------
    land_recs = [{"ts": e.get("ts"), "status": (e.get("data") or {}).get("status")} for e in _by_ts(lands)]
    land_block = {"attempts": land_recs,
                  "attempt_count": len(land_recs),
                  "ok_count": sum(1 for r in land_recs if r["status"] == "ok")}

    # --- tokens / cost via the token-rollup lens (reuse, session-level attribution) --------------
    sess_refs = sorted({e.get("session_ref") for e in own if e.get("session_ref")})
    if len(sess_refs) == 1:
        sid = sess_refs[0]
        rollup = None
        try:
            # T-11143: reuse T-0394 verbatim, narrowed to the ONE session this scorecard attributes
            # to. Only `sessions[sid]` (plus `status`/`estimate`, both filter-independent) is read
            # below, and each session's figures are computed from its own transcript alone — so the
            # rendered output is byte-identical while the full-corpus parse (9,662 sessions / 6.7GB)
            # is not paid.
            rollup = _view_token_rollup(index, only_sessions={sid})
        except SystemExit:                                # belt: any other _die path → degrade, never abort
            rollup = None
        # archive missing/empty/stale → the rollup HONEST-DEGRADES to a NAMED `status` outcome (T-10454);
        # the scorecard must NOT inherit the unavailability — the cost column is best-effort over a
        # gitignored raw archive (T-0394).
        if rollup is None or rollup.get("status"):
            reason = (rollup.get("reason") if isinstance(rollup, dict) and rollup.get("reason")
                      else "token-rollup unavailable (transcript archive missing/stale — "
                           "absent in worktrees; see the rsync fix)")
            tokens_cost = {"attribution": "n/a", "reason": reason}
        else:
            sess = (rollup.get("sessions") or {}).get(sid)
            if sess:
                totals = sess.get("totals") or {}
                # surface cost_usd as a first-class column (audit-post F0 — the tokens/cost column the
                # scope/AC calls for must be explicit, not only buried inside `totals`).
                tokens_cost = {"attribution": "clean", "session": sid,
                               "cost_usd": totals.get("cost_usd"), "totals": totals,
                               "estimate": rollup.get("estimate", True)}
            else:
                tokens_cost = {"attribution": "n/a", "session": sid,
                               "reason": "session has no token usage in the transcript archive"}
    else:
        tokens_cost = {"attribution": "n/a",
                       "reason": (f"{len(sess_refs)} sessions span this task — per-task token "
                                  "attribution in multi-task sessions is deferred "
                                  "(idea: per-task-token-attribution-in-multi-task-sessions)"),
                       "session_count": len(sess_refs)}

    return {
        "task": target,
        "title": title,
        "status": status,
        "lead_time": lead,
        "per_stage_walls": per_stage_walls,
        "audits": audits,
        "land_attempts": land_block,
        "deviations": {"count": deviations, "linkage": "heuristic: relates_to-token-match"},
        "tokens_cost": tokens_cost,
    }



# ── T-12008 — the stage-profile lens (the windowed AGGREGATE of task-scorecard) ────────────────────

# WHICH duration-bearing journal rows each lifecycle stage OWNS. The MACHINE-TIME share of a stage's
# wall is computed from these rows and from NOTHING else — a stage absent from this map owns no
# duration row at all, which the lens STATES rather than reporting as 0% (the difference between "the
# machine spent none of this stage" and "we cannot see what the machine spent" is the whole point).
# `land_completed` is the Closure owner: a land's own `duration_ms` is the machine time closure pays,
# with `verify_duration_ms` as the fallback for a row that carries only the verify leg.
_STAGE_DURATION_OWNERS = {
    "Tests": ("tests_passed", "tests_failed"),
    "Audit-pre": ("audit_pre_completed",),
    "Audit-post": ("audit_post_completed",),
    # Closure's rows are the one CASE that is NOT contained in its own stage wall: a `land` runs
    # AFTER `task_closed`, which is exactly where the Closure wall ends. Its machine time is real and
    # worth reporting, but it is not a SHARE of that wall — see the containment guard in
    # `_stage_machine_time`, which reports the seconds and refuses the ratio.
    "Closure": ("land_completed",),
}
_STAGE_PROFILE_DEFAULT_DAYS = 14

def _p90(vals: list):
    """The 90th percentile by NEAREST RANK over a numeric list (None for empty).

    Nearest-rank — the order statistic at ceil(0.9 * n) — deliberately, not an interpolating
    percentile: every value it can return is a wall this project ACTUALLY paid, so a reader who asks
    "which task was that?" can always be answered. n < 10 therefore returns the maximum, which is the
    honest reading of "the 90th percentile of eight observations" rather than a smoothed number that
    implies a resolution eight samples do not have."""
    s = sorted(v for v in vals if isinstance(v, (int, float)))
    if not s:
        return None
    import math as _math
    return s[min(len(s) - 1, max(0, _math.ceil(0.9 * len(s)) - 1))]

def _stage_profile_dt(ts, _ev_dt=None):
    """Resolve an event `ts` to a tz-aware UTC datetime through the ONE window-boundary normalizer.

    `_ev_dt` is the resolver every windowed lens already receives from the CLI seam (wired to
    `_parse_iso_utc`). A caller OUTSIDE that seam — the nightly per-project fold, which reads another
    checkout's journal directly — passes none, and falls back to that SAME normalizer via a lazy
    import. One parser, no second dialect (CHARTER §P5); the lazy import also keeps `lib.nightly` free
    of an import-time cycle back through `lib.cli`."""
    if _ev_dt is not None:
        return _ev_dt(ts)
    try:
        from lib.cli import _parse_iso_utc as _p   # noqa: PLC0415 — lazy, breaks the import cycle
    except ImportError:
        return None
    return _ev_dt_from_parser(ts, _p)

def _ev_dt_from_parser(ts, parser):
    """`_ev_dt`'s body with the parser passed positionally (the fallback path of `_stage_profile_dt`).
    Best-effort exactly as `_ev_dt` is: a malformed ts yields None and its row is skipped, never fatal."""
    if not isinstance(ts, str):
        return None
    try:
        return parser(ts)
    except ValueError:
        return None

def _view_stage_profile(events_path, since=None, until=None, *, _fmt_duration=None, _median=None,
                        _ts_delta_seconds=None, _ev_dt=None) -> dict:
    """stage-profile lens (T-12008): the AGGREGATE of `task-scorecard` over the tasks CLOSED in a
    window — per stage, for ONE project. Pure f over `events.jsonl`; no store, no event, recomputed
    fresh on every run (D-0053 / CHARTER §P1 F2 — a VIEW, never a new entity).

    THE QUESTION IT ANSWERS, which nothing else did: "over the last N days, in THIS project, what does
    each lifecycle stage cost (median / p90 / sum) and how much of that is MACHINE time?" It was
    reachable only by a by-hand journal fold, re-derived (and re-mis-derived) per review.

    POPULATION — tasks whose LAST `task_closed` falls in [since, until): `since` INCLUSIVE, `until`
    EXCLUSIVE, the trend-report window pair reused verbatim (T-0396), not a second dialect. A task
    closed OUTSIDE the window is excluded whatever else it emitted inside it, so the profile always
    describes a set of COMPLETED lifecycles rather than a slice through open ones. With NEITHER bound
    given the window defaults to the last 14 days — the `admission-series` precedent (a default
    that matches the question the lens exists for); an explicit window is always honored as given.

    PER-STAGE WALLS REUSE the per-task walk (`_stage_walls_from_boundaries`, the function
    `task-scorecard` itself calls) — so `sum(stage-profile)` cannot disagree with the per-task lens it
    aggregates (CHARTER §P5). Per stage: `n` (tasks that entered it), `median` / `p90` / `sum` of wall
    seconds, each with a human form.

    MACHINE TIME IS REPORTED HONESTLY OR NOT AT ALL — the load-bearing rule of this lens. `duration_ms`
    became universal only at T-12007, so a window reaching back before it sees a MIXED population, and
    a share computed over rows that lack the field would silently understate every stage. So each
    stage that owns duration rows (`_STAGE_DURATION_OWNERS`) reports `rows`, `rows_with_duration` (k),
    the literal `"k of n with duration"` string, and a share computed over THOSE k ROWS ONLY — against
    the walls of the tasks those rows belong to, so numerator and denominator describe the same tasks.
    k == 0 reports `"no duration rows"` and a NULL share, NEVER 0%: an unmeasured stage and a stage the
    machine spent nothing in are different facts and the output says which one it is (SPEC-0135 §5 —
    findings, not fabricated figures; the `_dur_stats` never-silently-drop contract). A stage that owns
    no duration row at all says SO, rather than reading as a stage with no machine time.

    An EMPTY population returns every figure as null beside a `no_data` line naming the empty window
    (the `outcome-ratio` no-fabricated-zeros rule) — never a page of zeros that reads like a measured
    result. Fail-OPEN: a missing or unreadable journal degrades to that same empty payload, never a
    crash. Segment-aware throughout (`journal_mod.segment_lines`, SPEC-0190 rule 4) — a raw read of the
    live segment alone would silently answer for recent history only."""
    import datetime as _dt
    from pathlib import Path as _Path

    now = _dt.datetime.now(_dt.timezone.utc)
    defaulted = since is None and until is None
    if defaulted:
        since = now - _dt.timedelta(days=_STAGE_PROFILE_DEFAULT_DAYS)
    window = {"since": since.isoformat() if since else None,
              "until": until.isoformat() if until else None,
              "defaulted": defaulted,
              "default_days": _STAGE_PROFILE_DEFAULT_DAYS if defaulted else None,
              "population": "tasks whose LAST task_closed falls in [since, until)"}

    def _in_window(dt) -> bool:
        if dt is None:
            return False           # fail-closed: an unparseable ts cannot be PROVEN in-window
        if since is not None and dt < since:
            return False
        if until is not None and dt >= until:
            return False
        return True

    # ---- one segment-aware pass: per-task boundaries, closes, and duration-bearing rows ----------
    owner_types: dict = {}
    for _stage, _types in _STAGE_DURATION_OWNERS.items():
        for _t in _types:
            owner_types.setdefault(_t, []).append(_stage)
    boundaries: dict = {}          # task_id -> [(ts, stage), ...]
    closes: dict = {}              # task_id -> latest task_closed ts (raw string)
    close_dts: dict = {}           # task_id -> latest task_closed dt
    picks: dict = {}               # task_id -> earliest task_picked ts (raw string)
    dur_rows: dict = {}            # (task_id, stage) -> [duration_ms or None, ...]

    p = _Path(events_path) if events_path is not None else None
    if p is not None and p.exists():
        try:
            for line in journal_mod.segment_lines(p, errors="replace"):   # SPEC-0190 rule 4
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(e, dict):
                    continue
                typ, ts = e.get("type"), e.get("ts")
                d = e.get("data") if isinstance(e.get("data"), dict) else {}
                tid = e.get("task_id") or e.get("task")
                if typ == "stage_entered" and tid and ts:
                    boundaries.setdefault(tid, []).append((ts, d.get("stage")))
                elif typ == "task_closed" and tid and ts:
                    # LATEST close wins (the `task-scorecard` lead-time rule): a reopened/re-closed
                    # task is placed in the window by its FINAL closure. A row whose ts will not parse
                    # is kept only until a parseable one arrives — it can never displace one, and on
                    # its own it leaves the task out of every window (fail-closed).
                    dt = _stage_profile_dt(ts, _ev_dt)
                    prev = close_dts.get(tid, "absent")
                    if prev == "absent" or prev is None or (dt is not None and dt > prev):
                        closes[tid], close_dts[tid] = ts, dt
                elif typ == "task_picked" and tid and ts:
                    if tid not in picks or ts < picks[tid]:
                        picks[tid] = ts
                elif typ in owner_types:
                    # `land_completed` is the one owner row that may carry its task on the BRANCH
                    # rather than in `task_id` (the `task-scorecard` land matcher, T-0395) — resolve
                    # the same way so a Closure row is not silently dropped.
                    if not tid and typ == "land_completed":
                        br = d.get("branch")
                        if isinstance(br, str) and br.startswith("task/"):
                            tid = br[len("task/"):]
                    if not tid:
                        continue
                    ms = d.get("duration_ms")
                    if not isinstance(ms, (int, float)) or isinstance(ms, bool):
                        ms = d.get("verify_duration_ms") if typ == "land_completed" else None
                        if not isinstance(ms, (int, float)) or isinstance(ms, bool):
                            ms = None
                    for _stage in owner_types[typ]:
                        dur_rows.setdefault((tid, _stage), []).append(ms)
        except OSError:
            pass               # fail-OPEN: an unreadable journal degrades to the empty payload below

    population = sorted(tid for tid, dt in close_dts.items() if _in_window(dt))

    if not population:
        return {
            "lens": "stage-profile (T-12008) — the aggregate of task-scorecard over the tasks CLOSED "
                    "in a window, per stage",
            "window": window,
            "closed_tasks": 0,
            "stages": {},
            "lead_time": {"n": 0, "median_seconds": None, "p90_seconds": None},
            "audits_per_close": None,
            "no_data": ["no task was CLOSED in this window — every per-stage, lead-time and "
                        "audits-per-close figure is null rather than 0 (an absent population is not a "
                        "measured zero); widen the window with --since/--until"],
        }

    # ---- per-task walls through the SAME walk `task-scorecard` uses -------------------------------
    walls: dict = {}               # task_id -> {stage: {seconds, human, entries}}
    for tid in population:
        rows = sorted(boundaries.get(tid, []), key=lambda b: b[0])
        walls[tid] = _stage_walls_from_boundaries(
            rows, closes.get(tid), _ts_delta_seconds=_ts_delta_seconds, _fmt_duration=_fmt_duration)

    stages: dict = {}
    seen_stages = {st for w in walls.values() for st in w}
    for stage in sorted(seen_stages):
        secs = [w[stage]["seconds"] for w in walls.values() if stage in w]
        total = sum(secs)
        med, p90 = _median(secs), _p90(secs)
        rec = {
            "n": len(secs),
            "median_seconds": med,
            "median_human": _fmt_duration(med) if med is not None else None,
            "p90_seconds": p90,
            "p90_human": _fmt_duration(p90) if p90 is not None else None,
            "sum_seconds": round(total),
            "sum_human": _fmt_duration(total),
        }
        rec["machine_time"] = _stage_machine_time(stage, population, dur_rows, walls)
        stages[stage] = rec

    lead = []
    for tid in population:
        a, b = picks.get(tid), closes.get(tid)
        if a and b:
            s = _ts_delta_seconds(a, b)
            if s is not None:
                lead.append(round(s))
    lead_med, lead_p90 = _median(lead), _p90(lead)
    lead_block = {
        "n": len(lead),
        "of_closed": len(population),
        "median_seconds": lead_med,
        "median_human": _fmt_duration(lead_med) if lead_med is not None else None,
        "p90_seconds": lead_p90,
        "p90_human": _fmt_duration(lead_p90) if lead_p90 is not None else None,
    }
    if not lead:
        lead_block["no_data"] = ("no task in the population carries BOTH a task_picked and a "
                                 "task_closed — lead time is unmeasurable here, not zero")

    audit_rows = sum(len(v) for (tid, st), v in dur_rows.items()
                     if tid in set(population) and st in ("Audit-pre", "Audit-post"))
    return {
        "lens": "stage-profile (T-12008) — the aggregate of task-scorecard over the tasks CLOSED in a "
                "window, per stage",
        "window": window,
        "closed_tasks": len(population),
        "stages": stages,
        "lead_time": lead_block,
        "audits_per_close": round(audit_rows / len(population), 2),
        "machine_time_note": ("each share is computed over the duration-bearing rows ONLY, against the "
                              "walls of the tasks those rows belong to; `duration_ms` became universal "
                              "at T-12007, so a window reaching further back reports a partial sample "
                              "AS partial — never a silent 0%"),
    }

def _stage_machine_time(stage: str, population: list, dur_rows: dict, walls: dict) -> dict:
    """The MACHINE-TIME share of one stage's wall, reported with its own sample size (T-12008).

    Three OUTCOMES, kept distinct because collapsing any two of them is the dishonesty this block
    exists to prevent:
      · the stage owns NO duration row TYPE at all      -> `owns_duration_rows: false` + why,
      · it owns rows but NONE carries a duration (k==0)  -> `"no duration rows"`, share null,
      · k >= 1                                           -> a share over THOSE k rows, labelled
                                                            `"k of n with duration"`.
    The DENOMINATOR is the summed wall of exactly the tasks whose rows carry a duration — not of the
    whole population — so numerator and denominator describe the SAME tasks and a partial sample
    yields a like-for-like ratio instead of a figure diluted by tasks the instrument never saw."""
    types = _STAGE_DURATION_OWNERS.get(stage)
    if not types:
        return {"owns_duration_rows": False,
                "note": f"stage {stage!r} owns no duration-bearing journal row — its wall is not "
                        f"decomposable into machine and worker time from the journal alone"}
    rows_total = 0
    machine_ms = 0.0
    contributing: set = set()
    for tid in population:
        vals = dur_rows.get((tid, stage)) or []
        rows_total += len(vals)
        for ms in vals:
            if ms is not None:
                machine_ms += ms
                contributing.add(tid)
    k = sum(1 for tid in population for ms in (dur_rows.get((tid, stage)) or []) if ms is not None)
    block = {"owns_duration_rows": True, "row_types": list(types),
             "rows": rows_total, "rows_with_duration": k,
             "sample": f"{k} of {rows_total} with duration"}
    if k == 0:
        block.update({"share_of_wall": None, "machine_seconds": None,
                      "sample": "no duration rows",
                      "note": f"none of the {rows_total} {'/'.join(types)} row(s) this stage owns "
                              f"carries a duration — the machine share is UNKNOWN here, not 0%"})
        return block
    wall_secs = sum(walls[tid][stage]["seconds"] for tid in contributing
                    if stage in walls.get(tid, {}))
    machine_secs = machine_ms / 1000.0
    block["machine_seconds"] = round(machine_secs)
    block["over_wall_seconds"] = round(wall_secs)
    if wall_secs <= 0:
        block["share_of_wall"] = None
        block["note"] = ("the tasks carrying a duration have a ZERO measured wall for this stage, so "
                         "the share has no denominator — unmeasurable, not 0%")
    elif machine_secs > wall_secs:
        # CONTAINMENT GUARD. A share only means anything when the rows are INSIDE the wall they are
        # divided by. Measuring more machine time than wall proves they are not, and printing the
        # resulting >100% "share" would publish a number whose own arithmetic disproves its label.
        # The known instance is Closure, whose `land` rows complete AFTER `task_closed` (see
        # `_STAGE_DURATION_OWNERS`) — but the guard is stated on the ARITHMETIC, not on that stage, so
        # any future owner mapping with the same flaw is caught rather than trusted. The seconds are
        # still reported: they are a real measurement, and only the RATIO is unavailable.
        block["share_of_wall"] = None
        block["note"] = (f"the {'/'.join(types)} row(s) this stage owns are NOT CONTAINED in its wall "
                         f"({block['machine_seconds']}s of machine time against a "
                         f"{block['over_wall_seconds']}s wall), so no share of that wall exists — the "
                         f"machine seconds are reported on their own. For Closure this is structural: "
                         f"a land completes AFTER the task_closed the Closure wall ends at")
    else:
        block["share_of_wall"] = round(machine_secs / wall_secs, 4)
    return block


def _view_ceiling_clusters(*, DECISIONS_DIR=None, pass_ceiling: int = 2,
                           pass_finding_class=None, _read_yaml=None) -> dict:
    """audit-ceiling-clusters lens (T-10742 / X-0587): the ROOT-CAUSE clustering of audit-ceiling cases
    that the T5 inspection matrix mandates and that the corpus could not answer — because the pass record
    kept a COUNT and a verdict and nothing about WHY each pass failed. With the per-pass `finding_class`
    tag retained on the pass record (bin/lib/audit.py), every subject that ran past the ceiling reads as a
    SEQUENCE of causes, and this lens groups those causes over the whole corpus.

    SPLIT BY GATE, never one mixed figure — the `outcome-ratio` kind-split invariant (plan-check F3),
    and precisely the pre-vs-post distinction X-0587 could only HYPOTHESISE from four data points: an
    audit-PRE ceiling means the PLAN kept failing (plan quality / auditor-expectation mismatch), an
    audit-POST ceiling means the shipped DIFF kept failing. Different failure modes, different fixes.

    A subject's cause sequence is `passes_trail[*].finding_class` + the record's OWN `finding_class`.
    A record written BEFORE this field existed is not skipped and is not a hole: its own findings are
    still on disk in its own file, so the lens classifies them at read time (`pass_finding_class`),
    marking the record `retro_tagged: true` — the trail entries of such a record legitimately carry no
    tag, and the count of those unrecoverable earlier passes is reported as `untagged_passes` rather than
    silently dropped (no silent cap — a reader must see what the corpus cannot answer yet).

    DERIVED, report-only, zero stored state (D-0053 / SPEC-0093 r7): recomputed fresh from the existing
    `decisions/<subject>-audit-{pre,post}.yaml` records on every run — no new store, no new event, no
    new command family. Consult / ad-hoc / plan-gate records are NOT ceiling-pass records of this shape
    and are excluded. Running this lens IS the P8 consumer-read adoption evidence (the `cli_invoked`
    emit on `graph query audit-ceiling-clusters`)."""
    from pathlib import Path as _Path
    decisions = _Path(DECISIONS_DIR) if DECISIONS_DIR is not None else None
    gates = ("pre", "post")
    by_gate = {g: {"subjects": [], "clusters": {}, "untagged_passes": 0} for g in gates}
    scanned = 0

    for gate in gates:
        paths = sorted(decisions.glob(f"*-audit-{gate}.yaml")) if decisions and decisions.is_dir() else []
        for p in paths:
            # `*-audit-consult-<stage>.yaml` matches the same glob tail — exclude the consult family
            # explicitly (a consult adjudicates the ceiling, it is not a ceiling PASS record).
            if "-audit-consult-" in p.name:
                continue
            data = _read_yaml(p) if _read_yaml else None
            if not isinstance(data, dict):
                continue
            scanned += 1
            passes = data.get("passes")
            if not isinstance(passes, int) or isinstance(passes, bool) or passes <= pass_ceiling:
                continue   # not a ceiling case — the ceiling is EXCEEDED passes, not merely reached
            trail = [e for e in (data.get("passes_trail") or []) if isinstance(e, dict)]
            causes = [e.get("finding_class") for e in trail if e.get("finding_class")]
            untagged = len(trail) - len(causes)
            own = data.get("finding_class")
            retro = False
            if not own and pass_finding_class:
                own = pass_finding_class(data.get("findings"))   # legacy record — classify at read time
                retro = True
            if own:
                causes.append(own)
            entry = {
                "subject": p.name.rsplit(f"-audit-{gate}.yaml", 1)[0],
                "passes": passes,
                "verdict": data.get("verdict"),
                "causes": causes,
                "untagged_passes": untagged,
            }
            if retro:
                entry["retro_tagged"] = True
            by_gate[gate]["subjects"].append(entry)
            by_gate[gate]["untagged_passes"] += untagged
            for c in causes:
                by_gate[gate]["clusters"][c] = by_gate[gate]["clusters"].get(c, 0) + 1

    for gate in gates:
        g = by_gate[gate]
        g["subjects"].sort(key=lambda e: (-e["passes"], e["subject"]))
        g["clusters"] = dict(sorted(g["clusters"].items(), key=lambda kv: (-kv[1], kv[0])))
        g["ceiling_subjects"] = len(g["subjects"])

    return {
        "lens": "audit-ceiling-clusters (T-10742 / X-0587) — audit-ceiling cases clustered by ROOT CAUSE, "
                "from the per-pass finding_class tag retained on the pass record",
        "ceiling": {"pass_ceiling": pass_ceiling,
                    "selection": f"records with passes > {pass_ceiling} (the ceiling EXCEEDED)"},
        "records_scanned": scanned,
        "invariant": "clusters are reported PER GATE (pre / post) and NEVER summed — an audit-PRE ceiling "
                     "means the PLAN kept failing, an audit-POST ceiling means the shipped DIFF kept "
                     "failing; different failure modes, different fixes (the outcome-ratio kind-split "
                     "discipline). Passes predating the finding_class tag are reported as "
                     "`untagged_passes`, never silently dropped.",
        "by_gate": by_gate,
        "next": ("report-only (D-0053) — a dominant cluster names WHERE the ceiling cost is actually "
                 "generated, so a remedy can be evidenced instead of hypothesised (X-0587). Pair with "
                 "`graph query outcome-ratio` for the first-pass-GREEN side of the same gates."),
    }
