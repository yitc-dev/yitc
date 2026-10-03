"""task_card_io — the task-card I/O family (the `_parse_*` argument parsers, the `_print_*` filing
advisories, the `_overlap*` / `_overlapping_*` overlap folds and their text helpers), extracted
byte-identical from `bin/lib/task.py` (T-12702, card C8b of plan
`extract-the-13-over-budget-bin-lib-modules-into-le`).

WHAT IS IN HERE. The FROZEN manifest of the plan's §Extraction map C8b — 48 top-level defs: the
`_parse_*` (8), `_print_*` (10), `_overlap*` / `_overlapping_*` (8) families + `_amend_expected_touch`,
`_ac_names_test_or_waive`, `_ac_test_waive_status`, `_ac_unmeasured_bounds`, `_capture_text`,
`_card_texts`, `_declared_anchor_overlap`, `_expand_declared_glob`, `_followup_overlap_tokens`,
`_inflight_intent_hits`, `_is_concrete_touch_anchor`, `_non_active_spec_refs`, `_retired_flag_refs`,
`_split_anchor`, `_touch_entry_matches_diff`, `_touch_governed_by_spec`, `_truncate_advisory_text`,
`_undercite_touch_symbol`, `_undercited_active_specs`, `_unrouted_captures`, `criterion_names_test`,
`declared_test_globs`. NOT IN HERE: the `cmd_*` orchestrators, the lifecycle gates and every
commit/session helper — those stay in the host.

SEAM (the T-9340 / T-9341 / T-11519 / T-12697 full inject-residue shape, `lessons/library-extraction.md`
§AST-freeze generator): every body and signature below is spliced VERBATIM from the original source —
never `ast.unparse` — and every non-stdlib free name that is not an already-extracted lower leaf
(host stayers, host globals, AND moved siblings via their host residue) arrives as a keyword-only
injected parameter, computed with `symtable` over each function's scope SUBTREE. Constants exclusive
to the move-set live module-local below (the host keeps a re-export alias for each). The host keeps a
`functools.wraps` residue under every historical name, so every `yitc.<sym>` / `task.<sym>` monkeypatch
and every cross-module injection keeps resolving, and `inspect.getsource` unwraps to the body here.

A LEAF: imports only lib.state / lib.events-tier leaves + stdlib and NEVER `lib.task`
(`tests/test_bin_lib_leaf_no_host_import.py`). Intentionally spec-less (SPEC-0005 admission test): a
byte-identical relocation mints no standing rule — the governing specs keep their homes and point
their `implements:` anchors here.
"""
from __future__ import annotations
import datetime as _dt
import fnmatch
import os
import re
import sys
from pathlib import Path
from lib import cross   # noqa: E402
from lib import followup   # noqa: E402
from lib import graph as graph_lib   # noqa: E402
from lib import init   # noqa: E402
from lib import journal as journal_mod   # noqa: E402
from lib import textutil   # noqa: E402
from lib import triage   # noqa: E402


# ---------------------------------------------------------------------------
# Constants exclusive to the move-set (referenced by movers only — verified across the host,
# tests/ and bin/lib/ by the generator's fixpoint), moved module-local so the bodies read them
# 1:1, uninjected. The host keeps a re-export alias under each historical name.
# ---------------------------------------------------------------------------
FOLLOWUP_OVERLAP_STOPWORDS = frozenset("""
    the a an and or of to in on for with by is was be at as it its this that from into not no via
    any all can may must should when then than but if we you they new now per use used using make
    makes made does done doing
    spec specs verify reverify task tasks test tests event events jsonl land lands plan plans main
    after against code file files work works session sessions verb verbs stage stages repo commit
    commits audit audits fix fixes add adds only same each next real still
""".split())

FOLLOWUP_OVERLAP_MIN_TOKEN_LEN = 4   # shorter tokens are english glue or file extensions

FOLLOWUP_OVERLAP_TEXT_WIDTH = 110    # per-followup text shown on the advisory line

_BRACE_ALTERNATION_RE = re.compile(r"\{([^{}]*)\}")

_GLOB_BRACE_EXPANSION_CAP = 64

NON_ACTIVE_SPEC_STATUSES = frozenset({"superseded", "retired", "withdrawn", "rejected"})

_SPEC_ID_RE = re.compile(r"\bSPEC-\d{4}\b")

AC_MEASURED_BOUND_DISPOSITION = (
    "rewrite the criterion as the qualitative outcome and record the number as evidence — a named "
    "measurement does not make a bound a criterion; an observed exact outcome («zero delta», «exactly "
    "one row») stays legal, a hypothesis is measured at Analysis (from: SPEC-0060 item 4 — the "
    "Measured-bound cue; a missing-named-reference heuristic, authoring prompt, not a gate)")

_UNDERCITE_GENERATED_PREFIXES = ("graph/", "release-view/")

_LIVE_PROBE_SETTLED_KEYS = ("evidence", "probed_at", "method")

_LIVE_PROBE_OUTCOME_KEYS = ("result", "evidence", "probed_at")


def _print_stranded_filing_advisory(branch: "str | None", tid: str) -> bool:
    """T-11584 — the STRAND advisory: this filing allocated a NEW id inside a `task/T-XXXX` worktree.

    A `task file` inside a task worktree ALWAYS allocates an id that is NOT that worktree's own
    deliverable — the claimed task's work is authored UNDER its existing id, never by allocating
    another. So the branch prefix is an exact test here, not a heuristic, and no duplicate detector
    is needed. The new card is then invisible to the picker on `main` (which reads landed `tasks/`
    only) until this task's own land carries it in — which is how <project> filed T-0379 inside
    `task/T-0377` while T-0377 was blocked ON it, the controller re-filed the same payload as T-0380
    from main, and one change ended up with two ids and a duplicate ready card in the queue.

    The doctrine already answers this case (AGENTS-SESSIONS §Writes happen in a worktree — a brand-new
    card with no id yet is filed in a `work/<slug>` batch, and FILING IS NOT EXECUTING: the batch ends
    at `land`, after which the new id is claimed with `worktree new --task`). What was missing is
    saying it AT the moment the card is written rather than after it is stranded — so the line names
    the ROUTE, not just the problem.

    REPORT-ONLY BY DESIGN, and that is the whole posture: it prints, blocks nothing, emits no
    event and moves no exit code. A session may have a good reason to file here; a refusal would be a
    new gate the incident does not justify (CHARTER non-goal #7 / §P1 F4). No 'the author decided, so
    stay quiet' carve-out either — a report-only advisory is cheap by construction and must not buy
    quiet with a suppression rule ([[report-only-advisory-never-exempts-a-contradiction]]).

    Prints nothing (and returns False) for anything that is not a `task/` branch — a `work/<slug>` batch (the SANCTIONED
    route, already served by `_work_batch_next_hint`), `main`, and non-git / detached / unborn HEAD
    (fail-open, mirroring `_work_batch_next_hint` and `_require_work_batch_worktree`). The caller
    resolves the branch; the return value is the printed/not-printed fact, for tests."""
    branch = (branch or "").strip()
    if not branch.startswith("task/"):
        return False
    # The registry KEY is printed HERE, on a `print(` line, deliberately: the SPEC-0060 registry's
    # pinned key assertion (T-10666) derives the printed set by scanning task.py's `print(` lines for
    # the `(advisory — …)` phrase. A key composed inside a helper `return` and printed as
    # `print(_var)` at the call site is INVISIBLE to it — which would re-create the T-10609 half-b
    # miss (a printed advisory line with no registry row) while the assertion stayed green. So this
    # helper PRINTS, like `_print_ac_test_waive_status` and every other registry emitter.
    print(f"⚠ stranded-filing (advisory — filing NOT blocked): {tid} was allocated inside the "
          f"`{branch}` worktree, so it is a new card that `main` cannot see — the picker reads "
          f"landed `tasks/` only, and it stays invisible (and unclaimable, even by something "
          f"blocked ON it) until this task lands.")
    print(f"  route: a brand-new card with no id yet belongs in a `bin/yitc-v2 worktree new --work "
          f"<slug>` batch — and FILING IS NOT EXECUTING: that batch ENDS at `bin/yitc-v2 land "
          f"--branch work/<slug>`, after which you claim the new id with `bin/yitc-v2 worktree new "
          f"--task {tid}` and run its 9 stages THERE (AGENTS-SESSIONS §Writes happen in a worktree).")
    print(f"  if this filing is deliberate, nothing to do — it lands with this task; just do not "
          f"author {tid}'s deliverable in here.")
    return True


def _followup_overlap_tokens(text: str) -> set:
    """T-10288: the SIGNIFICANT lowercase tokens of a title / followup text — the lexical unit the
    filing-preview overlap compares. Pure. Splits on non-alphanumerics, keeps tokens at least
    FOLLOWUP_OVERLAP_MIN_TOKEN_LEN long that are not FOLLOWUP_OVERLAP_STOPWORDS. Numeric tokens are
    KEPT on purpose: `0143` / `10240` are id fragments (SPEC-0143, T-10240) and are the rarest, most
    discriminating tokens available."""
    return {t for t in re.split(r"[^a-z0-9]+", str(text or "").lower())
            if len(t) >= FOLLOWUP_OVERLAP_MIN_TOKEN_LEN and t not in FOLLOWUP_OVERLAP_STOPWORDS}


def _overlapping_open_followups(title: str, expected_touch, items: dict, *, FOLLOWUP_OVERLAP_MAX_REPORTED, _followup_overlap_tokens, _overlap_paths, _overlap_via) -> list:
    """T-10288 (X-0263): the OPEN followups whose text already records the work this card is being
    filed for. Pure — takes the ALREADY-folded `items` (followup._fold output), does no IO.

    The two match signals (PATH, then TITLE) live in the shared `_overlap_via` — no scorer, no index,
    no new store (the fold IS the store). §FOLLOWUP_OVERLAP_STOPWORDS explains why the domain-generic
    half of the stopword set is load-bearing for the TITLE signal.

    ONLY `status == "open"` is considered: a promoted followup already became a task and a dropped one
    was refused, so neither can be duplicated by this filing. That filter is what keeps the advisory
    from naming the whole backlog on every card.

    Returns [{id, text, shared, via}] sorted by shared-token count DESC then id ASC (a total order —
    no dict-iteration nondeterminism), capped at FOLLOWUP_OVERLAP_MAX_REPORTED."""
    title_tokens = _followup_overlap_tokens(title)
    paths = _overlap_paths(expected_touch)
    hits: list = []
    for fid, item in (items or {}).items():
        if not isinstance(item, dict) or item.get("status") != "open":
            continue
        text = str(item.get("text") or "")
        via, shared = _overlap_via(title_tokens, paths, text)
        if via:
            hits.append({"id": str(fid), "text": text, "shared": shared, "via": via})
    hits.sort(key=lambda h: (-len(h["shared"]), h["id"]))
    return hits[:FOLLOWUP_OVERLAP_MAX_REPORTED]


def _print_followup_overlap(tid: str, title: str, expected_touch, REPO_ROOT, declared=(), *, _followup_overlap_events_path, _overlapping_open_followups, _truncate_advisory_text) -> None:
    """T-10288 (X-0263): print the open-followup overlap advisory for a just-filed card, or NOTHING
    when nothing overlaps. ADVISORY ONLY, exactly like the sibling `_declared_surface_preview` line it
    is printed beside: the id is already allocated and the YAML already written, so this never blocks a
    filing, never emits an event, never changes the exit code. Fail-open: any fold/compute error
    suppresses the advisory rather than breaking a completed filing.

    Real incident: 3 of 4 cards filed by one session duplicated an open followup (X-0263), because the
    filing path never read the followup store at all.

    T-11056 — `declared` is this card's `promotes:` list, and the two halves stay strictly separated:
    the SCREEN advises, the DECLARATION acts. A hit the card DECLARED is already promoted by the time
    this runs, so it is dropped from the list — the advisory has nothing left to advise about it, and
    a card that declared every hit prints NOTHING. What remains — a followup the screen named that the
    card did NOT declare — earns the WARN below: the exact mirror of `_cites_cross_without_resolves`,
    which names an X-NNNN a card cites without linking. Report-only, both ways. This screen never
    promotes anything: SPEC-0095 settled that axis when keying the fire on a guessed relation made all
    9 live rows false (T-10335), so a match is a question for the filer, never a state change."""
    declared_ids = {str(d).strip() for d in (declared or [])}
    hits = [h for h in _overlapping_open_followups(
        title, expected_touch, followup._fold(_followup_overlap_events_path(REPO_ROOT),
                                              journal_mod.segment_fold_lines))
        if h["id"] not in declared_ids]
    if not hits:
        return
    print(f"followup overlap (advisory — filing not blocked): {len(hits)} open followup(s) may "
          f"already record this work")
    for h in hits:
        why = "path" if h["via"] == "path" else "title: " + ", ".join(h["shared"])
        print(f"  {h['id']}  [{why}]  {_truncate_advisory_text(h['text'])}")
    sys.stderr.write(
        f"WARN: {tid} does not declare {'these' if len(hits) > 1 else 'this'} followup(s) in "
        f"`promotes:` — an open followup this card may already carry keeps reading as actionable debt "
        f"until someone promotes it by hand (T-11056; the followup-axis mirror of "
        f"cites-without-resolves_cross). If this card carries it, re-file with `--promotes <id>` or "
        f"promote it now; if not, ignore this line.\n")
    print(f"  disposition: yitc-v2 followup promote <id> --into {tid}  |  "
          f"yitc-v2 followup drop <id> --reason ...")


def _expand_declared_glob(pattern: str) -> list:
    """`frontend/src/**/*.test.{js,ts}` → the brace-free, zero-depth-inclusive globs `fnmatch` can
    actually match. TWO expansions, and each closes a silent false negative of its own:

    (1) BRACES. Path-vs-glob matching in this codebase is ONE idiom — `fnmatch`, where `*` spans `/`
    (`_is_verify_implementation_touch`, `_subject_globs_would_skip` and every sibling). `fnmatch` has
    no brace operator, so `*.test.{js,ts}` matches NOTHING and a project declaring the ordinary vitest
    convention reads as declaring a glob that never fires.

    (2) `**/` AT ZERO DEPTH. Under `fnmatch` a literal `**/` still requires its slash, so
    `frontend/src/**/*.test.ts` misses `frontend/src/panel.test.ts` — a file directly in the declared
    directory. Every shell globstar and every JS test runner reads `**/` as "zero OR MORE
    directories", which is precisely how a project means it when it writes one. So each `**/` also
    contributes a variant with that segment ELIDED. Measured: without this, two of the three sandbox
    declarations in `tests/test_ac_test_ref_declared_globs.py` recognised nothing.

    Both expansions only ever WIDEN what the project's own declaration covers toward what it plainly
    meant — neither invents a convention the project did not write. Expanding here, before the idiom,
    keeps the matcher single (no second glob engine) and the declaration honest.

    Bounded: a pattern that would expand past `_GLOB_BRACE_EXPANSION_CAP` variants is returned AS
    WRITTEN (it then simply matches nothing rather than costing a report-only advisory an unbounded
    expansion — a declaration nobody can satisfy is a declaration problem, not a reason for the reader
    to spend). Pure."""
    raw = str(pattern or "")
    out = [raw]
    while True:                                    # (1) braces, one alternation group at a time
        grew = []
        for p in out:
            m = _BRACE_ALTERNATION_RE.search(p)
            if not m:
                grew.append(p)
                continue
            for alt in m.group(1).split(","):
                grew.append(p[:m.start()] + alt.strip() + p[m.end():])
        if grew == out:
            break
        if len(grew) > _GLOB_BRACE_EXPANSION_CAP:
            return [raw]
        out = grew
    with_zero_depth = list(out)                    # (2) `**/` also means zero directories
    for p in out:
        while "**/" in p:
            p = p.replace("**/", "", 1)
            if p and p not in with_zero_depth:
                with_zero_depth.append(p)
    if len(with_zero_depth) > _GLOB_BRACE_EXPANSION_CAP:
        return [raw]
    return with_zero_depth


def declared_test_globs(repo_root, ops: "dict | None" = None, *, _expand_declared_glob) -> list:
    """T-12013 (SPEC-0185 §5 / SPEC-0160 rule 10) — the UNION of the globs this project DECLARES its
    test files live under: every `tests.classes[].globs` entry in its `yitc-ops.yaml`, expanded.
    `[]` when the project declares none — which is what routes `criterion_names_test` to the regex.

    THE UNION SHAPE IS THE SIBLING'S, REUSED, NOT A SECOND RESOLVER: `worktree._declared_check_surface_globs`
    already establishes it — read the carrier, take the union across classes, and let ANY parse failure
    contribute nothing. Parsing goes through that sibling's OWN entry point,
    `worktree._load_ops_carrier_text` (itself `state.load_str`, CHARTER §P5) — this helper adds NO
    ops-carrier reader of its own, which is the T-11280/T-11281 guard `tests/test_pinned_verify.py`
    holds and which caught the first draft of this function opening the carrier itself.

    FAIL-OPEN, deliberately and in the SAME direction `_load_ops_carrier_text` takes: an absent,
    unreadable or malformed carrier — and a `tests:` section that is waived or carries no usable
    globs — all return `[]`, i.e. "this project declares nothing", so recognition falls back to the
    kernel regex. Both readers of this value are REPORT-ONLY advisories; failing toward the
    pre-T-12013 behaviour costs a reader nothing it had before, while raising here would break a
    completed filing or an audit packet over a fact neither gates on.

    `ops` (optional) — an ALREADY-PARSED carrier, for a caller that has one; supplying it skips the
    read entirely and makes the helper pure."""
    if ops is None:
        try:
            from lib import worktree as _worktree   # lazy: worktree imports THIS module
            path = Path(repo_root) / init.CONSUMER_OPS_CONTRACT
            if not path.exists():
                return []
            ops = _worktree._load_ops_carrier_text(path.read_text(encoding="utf-8"))
        except Exception:      # noqa: BLE001 — an unreadable declaration declares nothing
            return []
    if not isinstance(ops, dict):
        return []
    classes = ((ops.get("tests") or {}) if isinstance(ops.get("tests"), dict) else {}).get("classes")
    if not isinstance(classes, list):
        return []
    out: set = set()
    for c in classes:
        if not isinstance(c, dict):
            continue
        for g in (c.get("globs") or []) if isinstance(c.get("globs"), list) else ():
            if isinstance(g, str) and g.strip():
                out.update(_expand_declared_glob(g.strip()))
    return sorted(out)


def criterion_names_test(text: str, declared_globs=(), *, _AC_TEST_KERNEL_FORM_RE, _AC_TEST_REF_RE) -> bool:
    """T-12013 — the ONE test-reference recognizer, read by BOTH advisories (the SPEC-0060 filing
    advisory here and the audit-post packet-readiness advisory in `audit.packet_readiness_section`).
    True iff this criterion string NAMES an executable test.

    THE DEFECT IT CLOSES (X-1235). `_AC_TEST_REF_RE` encodes the kernel's OWN test conventions —
    `tests/`, `test_x`, `x_test`, `*.test|spec.[jt]sx?`. A project whose tests live somewhere else
    (rspec's `spec/**/*_spec.rb`) read UNNAMED however honestly its criteria named a verifier, and the
    only remedy on offer was to teach the regex one more language — the growth path SPEC-0185 §4
    retires. Since T-12012 a project can DECLARE where its test files live
    (`tests.classes[].globs`); this reads that declaration instead of guessing from a filename.

    WITH a declaration, NAMED means any of:
      • a path token in the criterion matches the UNION of the declared globs — the project's own
        convention, whatever it is. Tokens come from `textutil.derive_path_tokens` (the ONE extraction
        home, T-10586), matched with this codebase's ONE `fnmatch` idiom where `*` spans `/`;
      • the explicit `(test: <ref>)` marker, or a `::node` id — the kernel-owned forms above, which a
        globs declaration says nothing about and therefore does not displace.
    WITHOUT one (`declared_globs` empty — absent, waived, or classes carrying no globs), the answer is
    `_AC_TEST_REF_RE.search` BYTE-FOR-BYTE: the fallback is the whole of the previous behaviour, so an
    undeclared project sees no change whatsoever.

    NOT A WIDENING OF THE DECLARED CASE. A declaring project is judged by its OWN declaration plus the
    two kernel-owned forms — the regex's convention branches do NOT also apply. That is the point: a
    project that says "my tests are `spec/**/*_spec.rb`" has stated its convention, and reading
    `frontend/src/calendar.js` as a test because some other project spells tests that way would make
    the declaration decorative. It is the sharper answer, so it is the one a project has to ask for.

    The `test-not-applicable:` waive is NOT this predicate's business — `_AC_WAIVE_RE` stays the
    caller's separate limb (both callers keep asking it first), unchanged.

    Pure. Report-only in both readers: nothing here gates, emits, or moves an exit code."""
    if not isinstance(text, str):
        return False
    globs = [str(g) for g in (declared_globs or ()) if str(g).strip()]
    if not globs:
        return bool(_AC_TEST_REF_RE.search(text))
    if _AC_TEST_KERNEL_FORM_RE.search(text):
        return True
    for token in textutil.derive_path_tokens(text):
        if any(fnmatch.fnmatch(token, g) for g in globs):
            return True
    return False


def _ac_names_test_or_waive(criterion: str, declared_globs=(), *, _AC_WAIVE_RE, criterion_names_test) -> bool:
    """T-10678 — True iff this ONE acceptance-criterion string names an executable test OR carries a
    valid `test-not-applicable: <reason>` waive. Pure text predicate — no judgement of test QUALITY
    (non-goal #7); it only asks whether SOMETHING is named.

    T-12013: the test-naming half is answered by `criterion_names_test`, which reads the project's
    declared `tests.classes[].globs` when it has them and falls back to the regex when it does not.
    The waive limb is unchanged."""
    if not isinstance(criterion, str):
        return False
    return bool(_AC_WAIVE_RE.search(criterion)
                or criterion_names_test(criterion, declared_globs))


def _ac_unmeasured_bounds(acceptance, *, _AC_MEASUREMENT_REF_RE, _AC_NUMERIC_BOUND_RE) -> list:
    """T-12251 — the acceptance criteria (in order) that compare to a BARE number with no measurement
    named. Empty list ⇒ every numeric bound is measured or directional. Pure; the advisory printer
    renders the result. A criterion with no numeric comparison at all is never flagged."""
    flagged = []
    for crit in (acceptance or []):
        text = str(crit)
        if _AC_NUMERIC_BOUND_RE.search(text) and not _AC_MEASUREMENT_REF_RE.search(text):
            flagged.append(text)
    return flagged


def _ac_test_waive_status(acceptance, declared_globs=(), *, _ac_names_test_or_waive) -> list:
    """T-10678 — the acceptance criteria (in order) that name NEITHER an executable test NOR a valid
    waive. Empty list ⇒ every AC is covered. Pure; the advisory printer renders the result.
    `declared_globs` (T-12013) is passed straight through to the recognizer."""
    unnamed = []
    for crit in (acceptance or []):
        if not _ac_names_test_or_waive(str(crit), declared_globs):
            unnamed.append(str(crit))
    return unnamed


def _card_texts(title, scope, acceptance) -> list:
    """The card's free-text fields as one flat list of strings (title + every scope/acceptance entry)."""
    out = [str(title or "")]
    for field in (scope, acceptance):
        for entry in (field or []):
            out.append(str(entry or ""))
    return out


def _non_active_spec_refs(cites, scope, acceptance, specs, *, _card_texts) -> list:
    """T-12339 — the pure selector for line (a): every SPEC-XXXX the card cites OR names in its scope/
    acceptance text that resolves in `specs` (the graph index's spec node map) to a NON-ACTIVE status.
    Returns sorted [{spec, status, superseded_by}] — `superseded_by` is the spec whose `supersedes` names
    it (the index carries that edge on the SUPERSEDER), or None. An id absent from the index is NOT a
    hit (a dangling cite is another advisory's concern). PURE over passed-in data."""
    specs = specs if isinstance(specs, dict) else {}
    named = {c for c in (cites or []) if isinstance(c, str) and _SPEC_ID_RE.fullmatch(c.strip())}
    for text in _card_texts("", scope, acceptance):
        named.update(_SPEC_ID_RE.findall(text))
    out = []
    for sid in sorted(named):
        node = specs.get(sid.strip()) or {}
        status = node.get("status")
        if status not in NON_ACTIVE_SPEC_STATUSES:
            continue
        superseder = next((k for k, v in sorted(specs.items())
                           if isinstance(v, dict) and str(v.get("supersedes") or "") == sid), None)
        out.append({"spec": sid, "status": status, "superseded_by": superseder})
    return out


def _retired_flag_refs(texts, *, audit) -> list:
    """T-12339 — the pure selector for line (b): the RETIRED `audit` flags (read IN PLACE off the one
    carrier `audit.RETIRED_AUDIT_FLAGS`) that any of `texts` names as a WHOLE flag token, via the VP6
    probe's own matcher so `--owner-reset=1` matches and `--owner-reset-something` does not. Sorted."""
    return sorted(tok for tok in audit.RETIRED_AUDIT_FLAGS
                  if any(graph_lib._names_flag_token(t, tok) for t in (texts or [])))


def _print_premise_advisory(tid, title, cites, scope, acceptance, specs, *, _card_texts, _non_active_spec_refs, _retired_flag_refs, _truncate_advisory_text, audit) -> None:
    """T-12339 (SPEC-0060 item 3, advisory registry rows 12 + 13) — print the two premise-verify floor
    lines for a card's EFFECTIVE fields, or NOTHING when the card cites only active specs and names no
    retired flag. ONE printer, TWO callers: `task file` (the grafted `_preview_index["specs"]`) and the
    `task update --old/--new` field-edit arm (the POST-edit parse). ADVISORY ONLY at both seams: never
    blocks, never emits an event, never changes the exit code; callers own the fail-open wrapping."""
    spec_hits = _non_active_spec_refs(cites, scope, acceptance, specs)
    if spec_hits:
        print(f"non-active spec cited (advisory — filing not blocked): {len(spec_hits)} spec(s) {tid} "
              f"cites or names resolve to a NON-ACTIVE status — only `active` governs (SPEC-0005)")
        for h in spec_hits:
            tail = f"; superseded by {h['superseded_by']}" if h["superseded_by"] else ""
            print(f"  {h['spec']}  ({h['status']}{tail})")
        print("  disposition: re-check the premise against the ACTIVE successor and amend the card "
              "(cites + the scope/acceptance lines that name it) — SPEC-0060 item 3 premise-verify cue; "
              "authoring prompt, not a gate")
    flag_hits = _retired_flag_refs(_card_texts(title, scope, acceptance))
    if flag_hits:
        print(f"retired flag named (advisory — filing not blocked): {len(flag_hits)} retired `audit` CLI "
              f"flag(s) named in {tid}'s text (SPEC-0204 rule 6)")
        for tok in flag_hits:
            print(f"  {tok}  — {_truncate_advisory_text(audit.RETIRED_AUDIT_FLAGS[tok])}")
        print("  disposition: a card that extends or amends a retired surface rests on a false premise — "
              "re-read SPEC-0204 and re-aim it at the live route; a mention of the same token on a "
              "NON-audit surface (`plan stage --owner-reset`) is a different flag — ignore this line")


def _print_ac_measured_bound_status(acceptance, *, _ac_unmeasured_bounds, _truncate_advisory_text) -> None:
    """T-12251 / T-12283 (SPEC-0060 item 4, advisory registry row 11) — print the `AC measured-bound
    status` block for `acceptance`, or NOTHING when no numeric bound lacks a named reference.

    T-12551 (from: SPEC-0060 item 4): the block is a report-only MISSING-NAMED-REFERENCE heuristic,
    never the rule. Its disposition points at the rule — rewrite the criterion as the qualitative
    outcome, the number as evidence — and deliberately offers no «name the measurement» alternative:
    a named measurement does not make a decreed bound a criterion.

    EXTRACTED from `_print_ac_test_waive_status` by T-12283 so the SAME block renders at BOTH
    authoring seams — `task file` (via that printer) and the `task update --old/--new` FIELD-EDIT
    that changes a card's `acceptance`. ONE printer, two callers: no second predicate, no second
    wording, no new flag/event/mechanism (CHARTER §P1 F1/F2). The text is unchanged from the filing
    seam's, so that seam's stdout is byte-identical to before the extraction.

    ADVISORY ONLY at both seams: never blocks, never emits an event, never changes the exit code.
    Its callers own the fail-open wrapping — a completed filing or a completed governed field-edit is
    never broken by an advisory that failed to compute."""
    unmeasured = _ac_unmeasured_bounds(acceptance)
    if unmeasured:
        print(f"AC measured-bound status (advisory — filing not blocked): {len(unmeasured)} of "
              f"{len(list(acceptance or []))} acceptance criteria compare to a bare number with no "
              f"measurement named")
        for crit in unmeasured:
            print(f"  [unmeasured] {_truncate_advisory_text(crit)}")
        print(f"  disposition: {AC_MEASURED_BOUND_DISPOSITION}")


def _print_ac_test_waive_status(tid: str, acceptance, repo_root=None, *, _ac_test_waive_status, _print_ac_measured_bound_status, _truncate_advisory_text, declared_test_globs) -> None:
    """T-10678 (SPEC-0060 item 4, registry line 9): print the per-AC test/waive advisory for a
    just-filed card, or NOTHING when every AC names a test or an explicit waive. ADVISORY ONLY — same
    posture as the sibling `_print_followup_overlap` line: the id is allocated and the YAML is written
    by now, so this never blocks a filing, never emits an event, never changes the exit code. Fail-open:
    any compute error suppresses the advisory rather than breaking a completed filing.

    Real driver: an AC that names no test and no waive is a claim with no named verifier — "done" is
    asserted with nothing that runs to prove it (SPEC-0060 item 4 / CHARTER §P3 done=adopted).

    `repo_root` (T-12013): the checkout whose `tests.classes[].globs` declaration decides what counts
    as a test reference here. Resolved ONCE per filing and handed to the recognizer; `None` (or a
    project declaring none) reads exactly as before, through the kernel regex."""
    unnamed = _ac_test_waive_status(
        acceptance, declared_test_globs(repo_root) if repo_root is not None else ())
    if unnamed:
        print(f"AC test/waive status (advisory — filing not blocked): {len(unnamed)} of "
              f"{len(list(acceptance or []))} acceptance criteria name neither an executable test nor an "
              f"explicit waive")
        for crit in unnamed:
            print(f"  [unnamed] {_truncate_advisory_text(crit)}")
        print(f"  disposition: name the verifying test (a path / pinned-suite id) in the AC, or waive it "
              f"explicitly `test-not-applicable: <reason>` (SPEC-0060 item 4 — authoring prompt, not a gate)")
    # T-12251 (SPEC-0060 item 4, the Measured-bound cue): the second block, INDEPENDENT of the first —
    # a criterion can name its test and still carry a hypothesis threshold. Same posture: report-only.
    # CALLER 1 of 2 (T-12283): the printer moved to its own function so the SECOND authoring seam —
    # `cmd_task_update`'s FIELD-EDIT arm — renders the identical block. One printer, two callers.
    _print_ac_measured_bound_status(acceptance)


def _split_anchor(anchor: str) -> tuple:
    """T-10942: an `expected_touch` entry as (file, symbol) — `bin/lib/task.py#_overlap_via` →
    (`bin/lib/task.py`, `_overlap_via`), a BARE path → (`bin/lib/task.py`, ""). Lowercased, so the
    comparison is case-stable. File component via the shared `textutil.anchor_file` (the same
    normalisation `_overlap_paths` uses — one rule, not a second parser). Pure."""
    a = str(anchor or "").strip().lower()
    file = textutil.anchor_file(a).strip()
    sym = a[len(file):].lstrip("#:").strip() if a.startswith(file) else ""
    return file, sym


def _declared_anchor_overlap(mine: list, theirs: list, *, _split_anchor) -> list:
    """T-10942: MY declared `expected_touch` anchors that overlap a CARD-BEARING peer's anchor list.

    ASYMMETRIC ON PURPOSE. A peer intent's `paths` merges its cards' declared anchors with its
    CHANGED FILES, and a bare entry is indistinguishable between the two — so only a peer entry
    carrying an explicit `#symbol` is provably DECLARED, and only those are matched. An overlap is
    the same file component plus symbol agreement:

      task.py#a  vs task.py#a  → overlap (the same declared symbol)
      task.py    vs task.py#a  → overlap (my whole-file declaration subsumes their symbol)
      task.py#a  vs task.py#b  → NO overlap — disjoint declared surfaces that merely share a file
      task.py#a  vs task.py    → NO overlap — their bare entry may be nothing but a changed file,
                                 and that coarse file-level co-occurrence (the three files nearly
                                 every kernel card touches) is what produced the measured false
                                 positives. Silence over a guess; a cardless peer's changed files
                                 are handled by the caller's own file-level leg.

    Returns the sorted matched anchors as `<file>#<sym>` strings (what the advisory names as its
    reason). Pure."""
    theirs_pairs = [_split_anchor(a) for a in (theirs or [])]
    matched = set()
    for file, sym in (_split_anchor(a) for a in (mine or [])):
        if not file:
            continue
        for tfile, tsym in theirs_pairs:
            if tfile != file or not tsym or (sym and sym != tsym):
                continue
            matched.add(f"{file}#{tsym}")
    return sorted(matched)


def _inflight_intent_hits(title: str, expected_touch, intents, *, FOLLOWUP_OVERLAP_MAX_REPORTED, _declared_anchor_overlap, _overlap_paths) -> list:
    """T-10579 (X-0430): the OTHER live sessions' in-flight worktree intents that overlap THIS card's
    concern. `intents` is the host `_inflight_worktree_intents` fold (already self-branch-excluded).

    The match is DERIVED FROM DECLARED SURFACES ONLY (T-10942) — never from title / scope word
    tokens. A card that declares NO `expected_touch` gets SILENCE, not a guess: the prose derivation
    this used to run (`_overlap_via` over the peer's title(s)+scope(s)+slug words) fired twice in one
    session against a card that was already done — and a wolf-crying advisory trains the filer to
    skip the duplicate-check exactly when the one true overlap arrives. `_overlap_via` itself is
    untouched — the three sibling filing-preview lines still share it.

    Two carriers, because a peer's `paths` merges its cards' declared anchors with its changed files
    and a BARE entry is indistinguishable between them:
      - a CARD-BEARING peer (`tids` non-empty) is compared declared-to-declared at ANCHOR
        granularity (`_declared_anchor_overlap`), so same-file disjoint symbols stay silent;
      - a CARDLESS `work/<slug>` batch declares nothing, so its changed files are matched at file
        level — file evidence, never prose. That is X-0430's cardless carrier, the case a
        declared-only rule would otherwise delete.

    Pure. Returns [{branch, tids, shared_paths}] sorted by overlap-size DESC then branch ASC (a total
    order), capped at FOLLOWUP_OVERLAP_MAX_REPORTED."""
    declared = [str(a) for a in (expected_touch or []) if str(a).strip()]
    if not declared:
        return []                                  # no forecast → silence (never a token guess)
    my_files = set(_overlap_paths(declared))
    hits: list = []
    for it in (intents or []):
        if not isinstance(it, dict):
            continue
        intent_paths = [str(p) for p in (it.get("paths") or [])]
        tids = list(it.get("tids") or [])
        if tids:
            shared_paths = _declared_anchor_overlap(declared, intent_paths)
        else:
            shared_paths = sorted(my_files & {p.strip().lower() for p in intent_paths})
        if not shared_paths:
            continue
        hits.append({"branch": str(it.get("branch") or "?"), "tids": tids,
                     "shared_paths": shared_paths})
    hits.sort(key=lambda h: (-len(h["shared_paths"]), h["branch"]))
    return hits[:FOLLOWUP_OVERLAP_MAX_REPORTED]


def _print_inflight_intent_overlap(title: str, expected_touch, intents, *, _inflight_intent_hits) -> None:
    """T-10579 (X-0430): print the cross-session in-flight-intent advisory for a card being filed or
    claimed, or NOTHING when nothing overlaps. ADVISORY ONLY — same posture as the sibling
    `_print_followup_overlap` line: never blocks, never emits an event, never changes the exit code.
    Fail-open: any compute error suppresses the advisory rather than breaking a completed filing/claim.

    Real incident (X-0430): two live controller sessions drove the SAME owner concern concurrently and
    built duplicates twice in one day — neither session's filing/claim read saw the other's un-landed
    filed card / work-batch intent, because both surfaces read only landed (index) state.

    `title` is no longer a match signal (T-10942 — the reason is always a DECLARED surface); it stays
    in the signature because both wire sites pass it."""
    hits = _inflight_intent_hits(title, expected_touch, intents)
    if not hits:
        return
    print(f"in-flight intent overlap (advisory — not blocked): {len(hits)} other live session(s) may "
          f"already be working this concern")
    for h in hits:
        tids = (" " + ", ".join(h["tids"])) if h["tids"] else ""
        print(f"  {h['branch']}{tids}  [files: {', '.join(h['shared_paths'])}]")
    print("  check: is this a duplicate of that live session's in-flight work? "
          "(X-0430 / §Sole-controller — two live controllers on one concern)")


def _overlap_via(title_tokens: set, paths: list, text: str, *, FOLLOWUP_OVERLAP_SHARED_MIN, _followup_overlap_tokens) -> tuple:
    """T-10300: the ONE match rule the three filing-preview overlap lines share — the followup line's
    rule (T-10288), lifted verbatim so the three axes cannot drift apart. Returns (via, shared):

      - ("path",  shared) — an expected_touch anchor's FILE component appears verbatim in `text`. A path
                            is specific enough to stand alone, so it needs no token quorum.
      - ("title", shared) — `text` shares >= FOLLOWUP_OVERLAP_SHARED_MIN significant tokens with the title.
      - (None,    shared) — no match.

    Pure. `shared` is always the sorted shared-token list (also on a path hit, where it may be empty)."""
    shared = sorted(title_tokens & _followup_overlap_tokens(text))
    if any(p in text.lower() for p in paths):
        return "path", shared
    if len(shared) >= FOLLOWUP_OVERLAP_SHARED_MIN:
        return "title", shared
    return None, shared


def _overlap_paths(expected_touch) -> list:
    """T-10300: the lowercased FILE components of an `expected_touch` anchor list
    (`bin/lib/task.py#cmd_task_file` → `bin/lib/task.py`). Extracted from `_overlapping_open_followups`
    so all three overlap lines derive their path signal identically. Pure."""
    return [p for p in (textutil.anchor_file(a).strip().lower() for a in (expected_touch or [])) if p]


def _capture_text(data: dict) -> str:
    """T-10300 (audit-pre F2): the free-text a capture actually carries — the PATH/token signal the
    filing-overlap matcher runs over. Pure.

    T-11890: this used to fold `impact` + `finding` and nothing else, which is exactly the per-reader
    field choice that read a rich capture as EMPTY when its prose lived under another key. It now
    delegates to the ONE reader-owned accessor, so the vocabulary is chosen in a single place
    (`journal_mod.CAPTURE_CONTENT_KEYS`) and a future alias reaches this matcher for free. `capture_text`
    is the SUPERSET view — every content value, not just the best one — because a matcher wants all
    the signal; it is de-duplicated, and `content`-first ordering lets the same function serve both a
    raw payload and an already-scanned `triage._scan_captures` row. The old {impact, finding} fold is
    preserved by the vocabulary order."""
    return journal_mod.capture_text(data)


def _unrouted_captures(events_path, *, _capture_text, consumer: bool = False) -> list:
    """T-10300: the FINGERPRINTED nonconformity captures SINCE THE LAST TRIAGE WATERMARK — the pool the
    filing preview matches a new card against. Resolves WHICH journal via the
    `_followup_overlap_events_path` precedent (same read-path==write-path contract, SPEC-0095).

    WHY THE WATERMARK, not a wall-clock window (audit-pre F1): a fixed N-day window both over- and
    under-shoots — it re-suggests captures a triage run already ROUTED, and it hides an older capture
    nobody has triaged yet. The routed boundary is the honest "still an open input" line, and it is what
    the card scope asks for. Bootstrap (no watermark yet) sweeps from journal start — the
    `plan.py#_require_captures_routed` precedent.

    Boundary + scan derive from the SINGLE shared lib home `triage._last_triage_watermark` /
    `triage._scan_captures` (T-10339 converged the T-10300 inline re-derivation onto them, once the
    contending host-scope task T-10297 landed — fp triage-watermark-derivation-duplicated-in-task-py).
    The watermark is the latest NON-probe `triage_run_completed`'s `data.window_through` (falling back
    to the event `ts` for pre-T-0542 rows), selected by completion-`ts` chronology, and the window is
    the CLOSED `ts > prior` (D-0086/T-0152). `_scan_captures` reads BOTH capture names — the current
    `deviation_captured` and the legacy read-only `friction_captured` (the D-0086 rename never reset
    recurrence) — and already drops `data.probe: true` schema demos; here we additionally drop a capture
    with no `fingerprint` (it cannot be closed by `--closes-fp`, so naming it is an unactionable hint).

    Captures COLLAPSE by fingerprint (a recurring fingerprint is ONE remediable subject, not N hits):
    each row is {fp, text, count, latest_ts}, `text` = the LATEST capture's `_capture_text` (impact +
    legacy finding, folded off the shared scan row). Sorted by count DESC then fp ASC (a total order —
    no dict-iteration nondeterminism). Fail-open on an absent journal (the shared scanners return
    []/None → returns []).

    T-13188: under a CONSUMER build (`consumer=True`) a capture whose enumerated realm is `kernel`
    (`cross.deviation_realm`) is EXCLUDED — it routes to the kernel via the land auto-file, so a
    consumer card cannot remediate it and naming it is an unactionable hint. The kernel's own filing
    reads every capture, unchanged."""
    ep = Path(events_path)
    prior = triage._last_triage_watermark(ep)
    by_fp: dict = {}
    for c in triage._scan_captures(ep):
        fp, ts = c["fp"], c["ts"]
        if not fp:                                  # unclosable by --closes-fp → not a hint
            continue
        if consumer and cross.deviation_realm(c) == cross.DEVIATION_REALM_KERNEL:   # T-13188
            continue
        if prior is not None and not ts > prior:    # the CLOSED routed boundary
            continue
        row = by_fp.setdefault(str(fp), {"fp": str(fp), "text": "", "count": 0, "latest_ts": ""})
        row["count"] += 1
        if ts >= row["latest_ts"]:
            row["latest_ts"], row["text"] = ts, _capture_text(c)
    return sorted(by_fp.values(), key=lambda r: (-r["count"], r["fp"]))


def _overlapping_unrouted_captures(title: str, expected_touch, captures: list, *, FOLLOWUP_OVERLAP_MAX_REPORTED, _followup_overlap_tokens, _overlap_paths, _overlap_via) -> list:
    """T-10300: the un-routed deviation fingerprints this card may already be the remediation for. Pure —
    takes the ALREADY-scanned `captures` (`_unrouted_captures` output), does no IO.

    A fingerprint is kebab-cased prose (`card-expected-touch-cannot-satisfy-its-own-ac`), so the shared
    tokenizer splits it into exactly the significant tokens a card title would share. Both the fingerprint
    AND the capture text feed the match: the fingerprint carries the subject, the text (impact + legacy
    finding — `_capture_text`) carries the file paths the PATH signal needs.

    Returns [{fp, count, via, shared}] in `captures` order (already count-DESC / fp-ASC), capped at
    FOLLOWUP_OVERLAP_MAX_REPORTED."""
    title_tokens = _followup_overlap_tokens(title)
    paths = _overlap_paths(expected_touch)
    hits: list = []
    for c in captures or []:
        via, shared = _overlap_via(title_tokens, paths, f"{c['fp']} {c.get('text') or ''}")
        if via:
            hits.append({"fp": c["fp"], "count": c["count"], "via": via, "shared": shared})
    return hits[:FOLLOWUP_OVERLAP_MAX_REPORTED]


def _overlapping_sibling_tasks(tid: str, title: str, expected_touch, tasks: dict, *, FOLLOWUP_OVERLAP_MAX_REPORTED, TASK_TERMINAL_STATUSES, _followup_overlap_tokens, _overlap_paths, _overlap_via) -> list:
    """T-10300: the NON-TERMINAL sibling tasks whose title already claims this card's work — the
    semantic-duplication check the filing path never ran. Pure — takes the ALREADY-grafted `tasks` node
    map (`_with_live_nodes(graph_build_index())["tasks"]`: {id: {title, status, expected_touch, …}}),
    does no IO.

    The card being filed is ALREADY on disk by the time the preview runs, so it is in that map — `tid`
    is excluded, else every filing would name itself as its own duplicate.

    Match text = the sibling's title PLUS its own `expected_touch` anchors, so two cards that name the
    same file surface hit on the PATH signal even when their titles were written in different words —
    which is exactly the duplication a title-only check misses.

    Returns [{id, title, status, shared, via}] sorted by shared-token count DESC then id ASC (a total
    order), capped at FOLLOWUP_OVERLAP_MAX_REPORTED."""
    title_tokens = _followup_overlap_tokens(title)
    paths = _overlap_paths(expected_touch)
    hits: list = []
    for sid, node in (tasks or {}).items():
        if not isinstance(node, dict) or str(sid) == str(tid):
            continue
        if str(node.get("status") or "") in TASK_TERMINAL_STATUSES:
            continue
        stitle = str(node.get("title") or "")
        text = " ".join([stitle] + [str(a) for a in (node.get("expected_touch") or [])])
        via, shared = _overlap_via(title_tokens, paths, text)
        if via:
            hits.append({"id": str(sid), "title": stitle, "status": str(node.get("status") or ""),
                         "shared": shared, "via": via})
    hits.sort(key=lambda h: (-len(h["shared"]), h["id"]))
    return hits[:FOLLOWUP_OVERLAP_MAX_REPORTED]


def _overlap_ts(value) -> "_dt.datetime | None":
    """T-10790: parse a card timestamp (`closed_at` / the filing `now`) to an aware UTC datetime, or
    None when it is absent/unparseable. Pure. A card whose timestamp does not parse is simply OUT of
    the recency window — fail-QUIET on the noise side, matching the advisory posture (an unnamed
    shipped card costs a glance, a flood costs the reader's attention on every filing)."""
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    try:
        parsed = _dt.datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)


def _overlapping_shipped_tasks(tid: str, title: str, tasks: dict, now_iso, *, FOLLOWUP_OVERLAP_MAX_REPORTED, FOLLOWUP_OVERLAP_SHARED_MIN, SHIPPED_OVERLAP_WINDOW_DAYS, TASK_TERMINAL_STATUSES, _followup_overlap_tokens, _overlap_ts) -> list:
    """T-10790: the RECENTLY-SHIPPED tasks whose title already claims this card's work — the other
    half of the same duplication question `_overlapping_sibling_tasks` asks of LIVE work. Pure — takes
    the SAME already-grafted `tasks` node map, does no IO.

    The sibling selector reports only NON-TERMINAL cards, so a card duplicating an already-DONE task
    was outside the screen BY CONSTRUCTION — the gap T-0581 (vs the done T-0464) and T-9360 (vs the
    done T-9306) both fell through. This selector covers exactly that class, under two bounds that are
    the deliverable, not decoration (§SHIPPED_OVERLAP_WINDOW_DAYS carries the measurements):

      - RECENCY. Only a terminal card that closed within SHIPPED_OVERLAP_WINDOW_DAYS of this filing is
        considered. Both incidents duplicated work that had closed ONE DAY earlier; unbounded, the
        ~2000-card done log floods every filing.
      - TITLE ONLY — no path signal, and the sibling's `expected_touch` is NOT folded into the match
        text (both of which `_overlapping_sibling_tasks` DOES use, legitimately, over its small live
        pool). Against the done log the path signal alone returned up to 387 hits on one card: every
        card touching a hot file matches hundreds of shipped ones. Dropping it is the decisive
        precision lever, and it is why the quorum could stay at FOLLOWUP_OVERLAP_SHARED_MIN — raising
        the quorum instead would have silenced both named incidents (2 shared tokens each).

    A closure stamped AFTER `now` is excluded too (a filing cannot duplicate a not-yet-closed card;
    this also keeps a clock-skewed or hand-edited stamp from widening the window).

    Everything else is the shared machinery, unchanged: the same tokenizer, the same quorum, the same
    shared-count DESC / id ASC total order, the same FOLLOWUP_OVERLAP_MAX_REPORTED cap.

    Returns [{id, title, status, closed_at, shared, via}] — `via` is always "title" here."""
    now = _overlap_ts(now_iso)
    if now is None:
        return []
    title_tokens = _followup_overlap_tokens(title)
    window = _dt.timedelta(days=SHIPPED_OVERLAP_WINDOW_DAYS)
    hits: list = []
    for sid, node in (tasks or {}).items():
        if not isinstance(node, dict) or str(sid) == str(tid):
            continue
        if str(node.get("status") or "") not in TASK_TERMINAL_STATUSES:
            continue
        closed = _overlap_ts(node.get("closed_at"))
        if closed is None or closed > now or (now - closed) > window:
            continue
        stitle = str(node.get("title") or "")
        shared = sorted(title_tokens & _followup_overlap_tokens(stitle))
        if len(shared) >= FOLLOWUP_OVERLAP_SHARED_MIN:
            hits.append({"id": str(sid), "title": stitle, "status": str(node.get("status") or ""),
                         "closed_at": str(node.get("closed_at") or ""), "shared": shared,
                         "via": "title"})
    hits.sort(key=lambda h: (-len(h["shared"]), h["id"]))
    return hits[:FOLLOWUP_OVERLAP_MAX_REPORTED]


def _truncate_advisory_text(text: str) -> str:
    """T-10300: one-line, width-bounded rendering of an advisory's subject text (the
    `_print_followup_overlap` rule, shared so the three lines render identically)."""
    text = str(text or "").replace("\n", " ")
    if len(text) > FOLLOWUP_OVERLAP_TEXT_WIDTH:
        text = text[:FOLLOWUP_OVERLAP_TEXT_WIDTH - 1].rstrip() + "…"
    return text


def _print_capture_overlap(tid: str, title: str, expected_touch, REPO_ROOT, *, _followup_overlap_events_path, _overlapping_unrouted_captures, _truncate_advisory_text, _unrouted_captures, consumer: bool = False) -> None:
    """T-10300: print the un-routed-deviation-fingerprint advisory for a just-filed card, or NOTHING when
    nothing overlaps. ADVISORY ONLY, exactly like the two lines it is printed beside: the id is already
    allocated and the YAML already written, so this never blocks a filing, never emits an event, never
    changes the exit code.

    The disposition it names is the EXISTING `task close --closes-fp <fp>` linkage (SPEC-0069) — the card
    can close the fingerprint it remediates, instead of the deviation staying open beside a card that
    silently fixed it. Nothing new is stored: the fingerprint is HUMAN-ASSERTED at closure, never derived
    from this hint."""
    hits = _overlapping_unrouted_captures(
        title, expected_touch, _unrouted_captures(_followup_overlap_events_path(REPO_ROOT), consumer=consumer))
    if not hits:
        return
    print(f"deviation overlap (advisory — filing not blocked): {len(hits)} un-routed fingerprint(s) "
          f"this card may remediate")
    for h in hits:
        why = "path" if h["via"] == "path" else "title: " + ", ".join(h["shared"])
        seen = f" ×{h['count']}" if h["count"] > 1 else ""
        print(f"  {_truncate_advisory_text(h['fp'])}{seen}  [{why}]")
    print(f"  disposition: yitc-v2 task close {tid} --closes-fp <fingerprint> (SPEC-0069)")


def _print_sibling_task_overlap(tid: str, title: str, expected_touch, tasks: dict,
                                now_iso=None, *, SHIPPED_OVERLAP_WINDOW_DAYS, _overlapping_shipped_tasks, _overlapping_sibling_tasks, _truncate_advisory_text) -> None:
    """T-10300: print the sibling-task advisory for a just-filed card, or NOTHING when nothing
    overlaps. ADVISORY ONLY (same posture as every line around it).

    Real incident (owner observation, 2026-07-09): the filing path checked open FOLLOWUPS and
    expected_touch CLASHES but never the live task queue itself, so a card semantically duplicating a
    `ready` sibling filed silently. The disposition is a HUMAN judgement — merge, `requires:`-order, or
    proceed (two cards may legitimately share a surface) — so this line names, and never decides.

    T-10790 — TWO GROUPS under this ONE registry line (SPEC-0060 line 2; no new screen, no new store):
      - LIVE work — the non-terminal siblings, unchanged in both selection and wording.
      - SHIPPED work — terminal cards that closed within SHIPPED_OVERLAP_WINDOW_DAYS, title-only
        (`_overlapping_shipped_tasks`). Its disposition differs and so it is a distinct block: a card
        duplicating a DONE task is not merged or ordered, it is re-scoped or dropped once the shipped
        card is read (T-0581 re-prescribed what T-0464 had already shipped; T-9360 re-cut T-9306).
    ONE printed KEY, not two: the shipped block is a SUB-BLOCK under line 2's existing
    `sibling-task overlap (advisory — …)` key (its sub-header deliberately carries no `(advisory — `
    phrase), so the SPEC-0060 registry keeps 9 rows and this card adds no registry line — the bound
    the card's own scope set. The header names both counts so a shipped-only hit is never keyless.
    `now_iso` is the filing timestamp the recency window is measured from; omitted (None) the shipped
    group is skipped entirely, so every existing caller keeps the pre-T-10790 behaviour exactly."""
    hits = _overlapping_sibling_tasks(tid, title, expected_touch, tasks)
    shipped = _overlapping_shipped_tasks(tid, title, tasks, now_iso) if now_iso else []
    if not hits and not shipped:
        return
    head = f"{len(hits)} non-terminal task(s) may already cover this work"
    if shipped:
        head += (f"; {len(shipped)} task(s) closed in the last {SHIPPED_OVERLAP_WINDOW_DAYS} days "
                 f"may already have SHIPPED it")
    print(f"sibling-task overlap (advisory — filing not blocked): {head}")
    if hits:
        for h in hits:
            why = "path" if h["via"] == "path" else "title: " + ", ".join(h["shared"])
            print(f"  {h['id']}  ({h['status']})  [{why}]  {_truncate_advisory_text(h['title'])}")
        print(f"  disposition: merge into the sibling, or order them via `requires:` on {tid} "
              f"(judgement — two cards MAY share a surface)")
    if shipped:
        print(f"  shipped-work group — {len(shipped)} task(s) closed in the last "
              f"{SHIPPED_OVERLAP_WINDOW_DAYS} days may already have SHIPPED this work")
        for h in shipped:
            print(f"  {h['id']}  ({h['status']} {h['closed_at']})  [title: {', '.join(h['shared'])}]"
                  f"  {_truncate_advisory_text(h['title'])}")
        print(f"  disposition: read the closed card before building {tid} — if it already shipped "
              f"this, re-scope to the genuine residual or drop the card (judgement)")
        print(f"  bound: recently-closed + title-match only — work shipped more than "
              f"{SHIPPED_OVERLAP_WINDOW_DAYS} days ago is OUTSIDE this line by design (T-10790)")


def _overlapping_open_cross(title: str, expected_touch, items: dict, self_name: str, *, FOLLOWUP_OVERLAP_MAX_REPORTED, _followup_overlap_tokens, _overlap_paths, _overlap_via) -> list:
    """T-10311 (X-0263): the OPEN to:<self> cross (coordination) items whose brief already asks for the
    work this card is being filed for — the FOURTH related-input line. Pure — takes the ALREADY-folded
    `items` (cross.fold output: {id: {id,kind,from,to,brief,status,…}}), does no IO.

    Only an item addressed TO self (`to == self_name`) in a NON-TERMINAL status (cross.TERMINAL_STATUSES
    excluded) can be duplicated by this filing: a closed/acked/rejected/withdrawn ask is settled, and a
    from:me ask is a PEER's job to satisfy, not this card's. Match text = the item's `brief`, run through
    the SAME `_overlap_via` rule the three sibling lines share (no scorer, no index, no new store — the
    fold IS the store).

    Returns [{id, brief, status, shared, via}] sorted by shared-token count DESC then id ASC (a total
    order — no dict-iteration nondeterminism), capped at FOLLOWUP_OVERLAP_MAX_REPORTED."""
    title_tokens = _followup_overlap_tokens(title)
    paths = _overlap_paths(expected_touch)
    hits: list = []
    for xid, item in (items or {}).items():
        if not isinstance(item, dict) or item.get("to") != self_name:
            continue
        if str(item.get("status") or "") in cross.TERMINAL_STATUSES:
            continue
        brief = str(item.get("brief") or "")
        via, shared = _overlap_via(title_tokens, paths, brief)
        if via:
            hits.append({"id": str(xid), "brief": brief, "status": str(item.get("status") or ""),
                         "shared": shared, "via": via})
    hits.sort(key=lambda h: (-len(h["shared"]), h["id"]))
    return hits[:FOLLOWUP_OVERLAP_MAX_REPORTED]


def _print_cross_overlap(tid: str, title: str, expected_touch, items: dict, self_name: str, *, _overlapping_open_cross, _truncate_advisory_text) -> None:
    """T-10311 (X-0263): print the open to:me cross-item advisory for a just-filed card, or NOTHING when
    nothing overlaps. ADVISORY ONLY (same posture as the three lines beside it — report-not-block,
    non-goal #7): the id is allocated and the YAML is written by now, so this never blocks a filing,
    never emits an event, never changes the exit code.

    The disposition it names is the EXISTING resolves_cross linkage (SPEC-0085): `--resolves-cross <X-id>`
    at file/close time links the card to the inbound ask so the card CARRIES the linkage instead of the
    filing silently duplicating it (X-0263 class). Nothing new is stored — the link is human-asserted.

    Real incident: the filing preview named followups / deviations / sibling tasks but never read the
    shared coordination log, so a card filed for an open to:me ask duplicated it (X-0263)."""
    hits = _overlapping_open_cross(title, expected_touch, items, self_name)
    if not hits:
        return
    print(f"cross-item overlap (advisory — filing not blocked): {len(hits)} open to:me coordination "
          f"item(s) may already ask for this work")
    for h in hits:
        why = "path" if h["via"] == "path" else "title: " + ", ".join(h["shared"])
        print(f"  {h['id']}  ({h['status']})  [{why}]  {_truncate_advisory_text(h['brief'])}")
    print(f"  disposition: link it via --resolves-cross <X-id> on {tid} (SPEC-0085)")


def _undercite_touch_symbol(anchor) -> "str | None":
    """T-10556: the `#symbol` component of an implements/expected_touch anchor, or None when the anchor
    is FILE-GRANULAR (no `#symbol`). The symbol is everything after the first `#` (a legacy `:line-range`
    anchor carries no symbol — textutil.anchor_file strips both)."""
    s = str(anchor)
    return s.split("#", 1)[1] if "#" in s else None


def _is_concrete_touch_anchor(anchor, REPO_ROOT) -> bool:
    """T-10556: the NOISE BOUND (consult finding 2). An expected_touch anchor is CONCRETE — worth
    resolving to governing specs — iff its FILE component is an existing REGULAR FILE in the repo AND is
    NOT under a generated/derived tree. A broad directory (`bin/lib/`), a typo'd path, or a generated
    artifact (`graph/index.json`) is therefore SKIPPED — never resolved, never warned on. Pure over the
    filesystem + REPO_ROOT (deterministic given the checkout)."""
    f = textutil.anchor_file(anchor).strip()
    if not f:
        return False
    if any(f == p.rstrip("/") or f.startswith(p) for p in _UNDERCITE_GENERATED_PREFIXES):
        return False
    try:
        return (Path(REPO_ROOT) / f).is_file()
    except OSError:
        return False


def _touch_governed_by_spec(touch_anchor, spec_anchors, *, _undercite_touch_symbol) -> bool:
    """T-10556: does a spec (via its implements `spec_anchors`) GOVERN a card's `touch_anchor`? True iff
    the spec has an implements anchor on the SAME file that governs this touch — a FILE-GRANULAR spec
    anchor governs the whole file; a FILE-GRANULAR card touch is governed by ANY anchor on that file;
    otherwise the two `#symbol`s must match. This symbol-aware precision is what keeps a spec governing
    an UNRELATED symbol in the same file from being named (consult finding 2 — the file-level reverse
    index alone would over-name every spec sharing a monolithic file)."""
    tfile = textutil.anchor_file(touch_anchor)
    tsym = _undercite_touch_symbol(touch_anchor)
    for sa in spec_anchors:
        if textutil.anchor_file(sa) != tfile:
            continue
        ssym = _undercite_touch_symbol(sa)
        if ssym is None or tsym is None or ssym == tsym:
            return True
    return False


def _undercited_active_specs(expected_touch, cites, index, REPO_ROOT, *, FOLLOWUP_OVERLAP_MAX_REPORTED, _is_concrete_touch_anchor, _touch_governed_by_spec) -> list:
    """T-10556: the pure selector. For each CONCRETE expected_touch anchor, resolve the ACTIVE specs
    that GOVERN it (symbol-aware) and are NOT already in the card's `cites:`. Returns [{spec, anchors}]
    where `anchors` are the touch anchors that spec governs — sorted by spec id, capped at
    FOLLOWUP_OVERLAP_MAX_REPORTED. Pure / read-only over the grafted graph `index`.

    Deliberately REPORT-ONLY: an active spec whose anchor governs a surface this card touches, absent
    from cites, is UNDER-CITED — NOT proof the card conflicts with the spec (a deliberate non-cite is
    legitimate). The WARN wording carries that honesty (consult finding 1)."""
    cited = {str(c).strip() for c in (cites or [])}
    specs = index.get("specs", {}) or {}
    c2s = index.get("code_to_specs", {}) or {}
    hits: dict = {}   # spec_id -> set(touch anchors it governs)
    for et in (expected_touch or []):
        if not _is_concrete_touch_anchor(et, REPO_ROOT):
            continue
        tfile = textutil.anchor_file(et)
        for sid in c2s.get(tfile, []):
            if sid in cited:
                continue
            snode = specs.get(sid) or {}
            if snode.get("status") != "active":
                continue
            if _touch_governed_by_spec(et, snode.get("implements") or []):
                hits.setdefault(sid, set()).add(str(et))
    out = [{"spec": sid, "anchors": sorted(anchors)} for sid, anchors in hits.items()]
    out.sort(key=lambda h: h["spec"])
    return out[:FOLLOWUP_OVERLAP_MAX_REPORTED]


def _print_undercitation_preview(tid, expected_touch, cites, index, REPO_ROOT, *, _undercited_active_specs) -> None:
    """T-10556: print the under-citation advisory for a just-filed card, or NOTHING when the card cites
    every active spec governing the concrete surfaces it declares. ADVISORY ONLY, same posture as the
    four filing-preview siblings beside it (report-not-block, fail-open, emits no event, never changes
    the exit code). HONEST: it names UNDER-CITATION, states it does NOT prove a contradiction, and its
    disposition is add-the-cite (which silences it) OR ack a deliberate non-cite via `task update --note`."""
    hits = _undercited_active_specs(expected_touch, cites, index, REPO_ROOT)
    if not hits:
        return
    print(f"under-citation preview (advisory — filing not blocked): {len(hits)} active spec(s) govern "
          f"a surface {tid} declares in expected_touch but does NOT cite")
    for h in hits:
        print(f"  {h['spec']}  (governs {', '.join(h['anchors'])})")
    print("  this flags UNDER-CITATION, not a contradiction — it does NOT prove the card conflicts "
          "with these specs (SPEC-0060).")
    print(f"  disposition: add the spec to cites: to silence this, or ack a deliberate non-cite via "
          f"yitc-v2 task update {tid} --note ...")


def _parse_probe(arg: str, *, _die) -> tuple[str, str]:   # single home = bin/lib/textutil.py (T-9260); _die injected
    return textutil.parse_probe(arg, _die)


def _parse_live_probe_settled_by(evidence, probed_at, method, *, flag_prefix: str):
    """Compose the three settle flags into a `settled_by` mapping — the ONE composer both legs use.

    Returns the mapping, or None when NO flag was passed (the leg is dormant). Raises ValueError on a
    PARTIAL triple. PURE — the grammar itself is `_live_probe_settled_grammar_error`'s job and is NOT
    re-implemented here; this only refuses BY FLAG NAME, which the grammar SoT cannot do because it
    sees a mapping and not the argv that composed it. Same discipline as the
    `--live-probe-url`/`--live-probe-expect-status` pairing refusal: half an assertion asserts nothing,
    and "which flag did I forget" is the one question the operator actually has."""
    vals = {"evidence": evidence, "probed_at": probed_at, "method": method}
    given = {k: str(v).strip() for k, v in vals.items() if v is not None and str(v).strip()}
    if not given:
        return None
    missing = [k for k in _LIVE_PROBE_SETTLED_KEYS if k not in given]
    if missing:
        raise ValueError(
            f"the settled-discharge flags are a TRIPLE, never part of one — missing "
            f"{', '.join(f'{flag_prefix}-' + k.replace('_', '-') for k in missing)}. "
            f"`settled_by` must name WHAT proved it ({flag_prefix}-evidence, a materialized-journal "
            f"locator), WHEN ({flag_prefix}-probed-at, an ISO date) and HOW ({flag_prefix}-method) — "
            f"a partial discharge proves nothing and would leave the waiver silently un-dated "
            f"(SPEC-0094 §3). Nothing was written.")
    return {k: given[k] for k in _LIVE_PROBE_SETTLED_KEYS}


def _parse_live_probe_settled_terminal(result, reason, *, flag_prefix: str, _SETTLE_TERMINAL_RESULTS):
    """Compose the TERMINAL discharge flags into a `settled_by` mapping {result, reason} (T-11748).

    The sibling of `_parse_live_probe_settled_by`, and refuses BY FLAG NAME for the same reason: the
    grammar SoT sees a mapping and cannot say which flag the operator forgot. Returns the mapping, or
    None when NEITHER flag was passed (the leg is dormant). Raises ValueError on a PARTIAL pair — a
    terminal with no reason is the reasonless discharge this whole leg is fail-closed against, and a
    reason with no terminal names no outcome at all. PURE: the vocabulary + the non-empty judgement
    are `_live_probe_settled_grammar_error`'s and are NOT re-implemented here; this refuses only what
    the grammar cannot see, which is the argv that composed the mapping."""
    result_s = str(result).strip() if result is not None else ""
    reason_s = str(reason).strip() if reason is not None else ""
    if not result_s and not reason_s:
        return None
    if not result_s:
        raise ValueError(
            f"{flag_prefix}-reason was passed with NO {flag_prefix}-terminal — a reason names WHY a "
            f"terminal was reached, so on its own it discharges nothing. Pass "
            f"{flag_prefix}-terminal {'|'.join(_SETTLE_TERMINAL_RESULTS)} too. Nothing was written.")
    if not reason_s:
        raise ValueError(
            f"{flag_prefix}-terminal {result_s!r} REQUIRES a non-empty {flag_prefix}-reason. This "
            f"terminal records that the waiver's debt will NEVER be proven "
            f"({'a proof that can never arrive' if result_s == 'unreachable' else 'a reading that arrived and came back negative'})"
            f" — WHY is the entire content of that record, so an empty reason discharges the debt "
            f"while saying nothing. Nothing was written.")
    return {"result": result_s, "reason": reason_s}


def _parse_live_probe_outcome(result, evidence, probed_at, detail):
    """Compose the attested-outcome flags into an `outcome` mapping (SPEC-0094 §4b). PURE.

    The sibling of `_parse_live_probe_settled_by`, and refuses BY FLAG NAME for the same reason: the
    grammar SoT sees a mapping and cannot say which flag the operator forgot. `--live-probe-outcome-detail`
    is genuinely OPTIONAL and so is NOT part of the required triple — but passing detail ALONE is still a
    partial record and is refused, since a detail with no result records nothing."""
    vals = {"result": result, "evidence": evidence, "probed_at": probed_at}
    given = {k: str(v).strip() for k, v in vals.items() if v is not None and str(v).strip()}
    _detail = str(detail).strip() if detail is not None and str(detail).strip() else None
    if not given:
        if _detail is None:
            return None
        raise ValueError(
            "--live-probe-outcome-detail was given with no reading to attach it to — an attested "
            "outcome needs --live-probe-outcome-result (passing|failing), "
            "--live-probe-outcome-evidence (the locator `liveprobe --report` printed) and "
            "--live-probe-outcome-probed-at (an ISO date). Nothing was written.")
    missing = [k for k in _LIVE_PROBE_OUTCOME_KEYS if k not in given]
    if missing:
        raise ValueError(
            f"the attested-outcome flags are a TRIPLE, never part of one — missing "
            f"{', '.join('--live-probe-outcome-' + k.replace('_', '-') for k in missing)}. An `outcome` "
            f"must name WHAT the reading was (--live-probe-outcome-result: passing|failing), WHICH "
            f"proof run says so (--live-probe-outcome-evidence, the locator `liveprobe --report` "
            f"printed) and WHEN (--live-probe-outcome-probed-at, an ISO date). A partial record is "
            f"exactly the half-filed reading SPEC-0094 §4b exists to prevent. Nothing was written.")
    out = {k: given[k] for k in _LIVE_PROBE_OUTCOME_KEYS}
    if _detail is not None:
        out["detail"] = _detail
    return out


def _parse_settle_live_probe_attested(flag, attested, runs_at, asserts, recheck_by, *, _LIVE_PROBE_ATTESTED_DECLARATION_KEYS):
    """T-12328 — compose the `--settle-live-probe-attested` quartet into a DECLARATION mapping. PURE.

    Returns the mapping, or None when the arm was not requested and no quartet flag was given.

    Refuses BY FLAG NAME, the reason its `_parse_live_probe_outcome` sibling does: the grammar SoT
    (`_live_probe_attested_grammar_error`) sees a mapping and can only say which KEY is missing, not
    which flag the operator forgot to type. Two symmetric refusals, so neither half can go silently
    dormant (the E-0057 silent-drop shape):
      (a) the switch WITHOUT its quartet — refuse naming every missing flag, rather than writing a
          declaration that names no gradeable proof;
      (b) quartet values WITHOUT the switch — refuse rather than ignore them, because a caller who
          typed `--attested X --runs-at Y ...` and got a zero exit would read success while nothing
          was written. `--recheck-by` is deliberately EXCLUDED from this direction: it is a generic
          date flag, so treating a bare one as an implied attested request would hijack it.

    Grammar is a property of the ARGV, not of the card, so this runs UP FRONT in `cmd_task_close` and
    a malformed quartet dies before any status branch and before any write."""
    vals = {"attested": attested, "runs_at": runs_at, "asserts": asserts, "recheck_by": recheck_by}
    given = {k: str(v).strip() for k, v in vals.items() if v is not None and str(v).strip()}
    if not flag:
        naming = [k for k in given if k != "recheck_by"]
        if naming:
            raise ValueError(
                "--" + "/--".join(k.replace("_", "-") for k in naming) + " was given without "
                "`--settle-live-probe-attested`, so nothing would be written. These flags compose the "
                "ATTESTED declaration that arm writes onto an already-DONE card (T-12328, SPEC-0094 "
                "§4b) — add the switch, or drop them. Nothing was written.")
        return None
    missing = [k for k in _LIVE_PROBE_ATTESTED_DECLARATION_KEYS if k not in given]
    if missing:
        raise ValueError(
            f"--settle-live-probe-attested is a QUARTET, never part of one — missing "
            f"{', '.join('--' + k.replace('_', '-') for k in missing)}. An attested declaration must "
            f"name WHICH instrument the project runs (--attested), WHERE it is gated (--runs-at), WHAT "
            f"it proves live (--asserts) and the dated debt it owes until its reading is recorded "
            f"(--recheck-by, an ISO date). A declaration naming fewer is a `none` waiver in a different "
            f"key, which is the state this form exists to LEAVE rather than to re-spell (SPEC-0094 "
            f"§4b). Nothing was written.")
    return {k: given[k] for k in _LIVE_PROBE_ATTESTED_DECLARATION_KEYS}


def _parse_settle_pairs(probe_args, evidence_args, reason_args=None, *, _SETTLE_PROBE_RESULT_VOCAB, _SETTLE_TERMINAL_RESULTS, _cross_settle_locator, _journal_locator) -> list:
    """Parse the settlement flags into [(ac, result, locator_or_None, reason_or_None)].

    PURE + total: returns the parsed tuples or raises ValueError with the caller-facing reason, so the
    whole grammar is refusable BEFORE any write and on ANY task status. Every flag is positionally
    paired with `--settle-probe` (the Nth companion settles the Nth probe) — the sibling shape of
    --pv-criterion/--pv-signal, which must likewise come TOGETHER.

    T-11657 — TWO COMPANION KINDS, and a run carries exactly ONE of them:
      * a `pass` settlement takes `--settle-evidence <locator>` — the NAMED, RESOLVING proof. UNCHANGED:
        this branch is byte-identical to the pre-T-11657 grammar, which is the criterion a careless
        vocabulary edit has to fail.
      * a NON-PASS TERMINAL settlement (`unreachable` / `falsified`) takes `--settle-reason <text>` —
        a MANDATORY, NON-EMPTY, FREE-TEXT reason. It takes NO evidence locator, and that is the whole
        point of the terminal rather than an oversight: an `unreachable` criterion has no evidence row
        to cite BY DEFINITION (the proof can never arrive), so requiring one would re-create the exact
        dead end this path exists to open.
    A MIXED run is REFUSED. The pairing is POSITIONAL, and two different companion kinds cannot be
    positionally paired without a placeholder sentinel — and inventing a sentinel to skip a slot is
    precisely the parallel path CHARTER §P1 F1 forbids. Settling passes and terminals in separate runs
    costs one extra invocation and keeps the grammar answerable by reading the argv.

    ALL-OR-NOTHING: every refusal here is raised BEFORE the caller's write block is reached, so a
    refused run — an empty reason above all — writes NOTHING."""
    probe_args = list(probe_args or [])
    evidence_args = list(evidence_args or [])
    reason_args = list(reason_args or [])
    if not probe_args and not evidence_args and not reason_args:
        return []
    if not probe_args:
        raise ValueError(
            f"--settle-evidence/--settle-reason were passed with NO --settle-probe (got "
            f"{len(evidence_args)} --settle-evidence and {len(reason_args)} --settle-reason). A "
            f"companion names the proof or the reason for a PROBE; there is nothing here to settle.")
    # Pre-parse the RESULT half of every probe arg so the companion-shape refusal below can name the
    # actual mistake ("this is a terminal run, it takes --settle-reason") instead of a generic count
    # mismatch. The per-pair grammar below re-derives and validates each result independently.
    _results = [str(rp or "").strip().rsplit(":", 1)[-1].strip() for rp in probe_args]
    _terminals = [r for r in _results if r in _SETTLE_TERMINAL_RESULTS]
    if _terminals and len(_terminals) != len(_results):
        raise ValueError(
            f"a settle run carries EITHER `pass` settlements (with --settle-evidence) OR non-pass "
            f"TERMINAL settlements ({'/'.join(_SETTLE_TERMINAL_RESULTS)}, with --settle-reason) — "
            f"never both in one run (got results: {', '.join(_results)}). The two take DIFFERENT "
            f"positionally-paired companions, and a mixed run could only be paired through a "
            f"placeholder sentinel. Settle them in separate runs.")
    _terminal_run = bool(_terminals)
    if _terminal_run:
        if evidence_args:
            raise ValueError(
                f"a TERMINAL settlement ({'/'.join(_SETTLE_TERMINAL_RESULTS)}) takes --settle-reason, "
                f"NOT --settle-evidence (got {len(evidence_args)} --settle-evidence). An `unreachable` "
                f"criterion has no evidence row to cite by definition, and a `falsified` one records "
                f"WHY the reading came back negative — put the locator inside the free-text reason "
                f"when there is one.")
        if len(probe_args) != len(reason_args):
            raise ValueError(
                f"--settle-probe and --settle-reason must be passed TOGETHER, one reason per probe "
                f"(got {len(probe_args)} --settle-probe and {len(reason_args)} --settle-reason). The "
                f"Nth --settle-reason gives the reason for the Nth --settle-probe; a terminal without "
                f"its reason is an escape hatch with nothing recorded, which is what this refuses.")
    else:
        if reason_args:
            raise ValueError(
                f"--settle-reason is for a NON-PASS TERMINAL settlement "
                f"({'/'.join(_SETTLE_TERMINAL_RESULTS)}) only — a `pass` settlement names its proof "
                f"with --settle-evidence (got {len(reason_args)} --settle-reason on a pass-only run). "
                f"A reason is not a substitute for a resolving evidence locator.")
        if len(probe_args) != len(evidence_args):
            raise ValueError(
                f"--settle-probe and --settle-evidence must be passed TOGETHER, one evidence locator per "
                f"probe (got {len(probe_args)} --settle-probe and {len(evidence_args)} --settle-evidence). "
                f"The Nth --settle-evidence names the proof for the Nth --settle-probe; a settlement "
                f"without its NAMED evidence is exactly the assertion this path refuses.")
    _companions = reason_args if _terminal_run else evidence_args
    pairs = []
    seen = set()
    for raw_probe, raw_companion in zip(probe_args, _companions):
        raw_probe = str(raw_probe or "").strip()
        if ":" not in raw_probe:
            raise ValueError(
                f"--settle-probe {raw_probe!r} must be in the form 'AC2:pass' (probe key, colon, "
                f"result) — the same grammar as --probe")
        # T-11531 — split on the LAST colon, not the first. The RESULT half is a CLOSED vocabulary
        # (`_SETTLE_PROBE_RESULT_VOCAB`) and no member contains a colon, so last-colon is a strict
        # SUPERSET of first-colon: every well-formed `AC2:pass` parses identically (the card's AC3
        # differential pins that), while a probe key that itself CARRIES colons resolves to the key
        # AS RECORDED instead of being truncated at its first one.
        #
        # Why that matters: before T-11531's sibling guard below, `task close` accepted any string as
        # a probe key, so `--probe-deferred` / `--from-stdin` could record an entire explanatory
        # sentence into the KEY (T-11339 recorded `AC4_independent_card_half:tracked ARMED at
        # followup fu_af73197ff7ad awaiting T-11306 ...`). First-colon splitting parsed that argument
        # back to `AC4_independent_card_half`, which is not a recorded key, so
        # `_settle_probe_admission_error` refused — and NO quoting form could reach it, because the
        # split happens after argv parsing. A genuinely proven criterion was unsettleable forever.
        #
        # The stored key is NOT rewritten to fit the parser — the parser reaches the key as it
        # stands. Silently normalising a closure record to satisfy a parser is the opposite of a fix.
        ac, result = raw_probe.rsplit(":", 1)
        ac, result = ac.strip(), result.strip()
        if not ac:
            raise ValueError(f"--settle-probe {raw_probe!r} names an empty probe key")
        if result not in _SETTLE_PROBE_RESULT_VOCAB:
            raise ValueError(
                f"--settle-probe {raw_probe!r}: result {result!r} is not a settleable probe result. "
                f"Allowed: {', '.join(_SETTLE_PROBE_RESULT_VOCAB)}. ('deferred' is what is being "
                f"settled, so re-recording it is a no-op, not a settlement.)")
        if ac in seen:
            raise ValueError(f"--settle-probe names {ac!r} twice — settle each criterion once per run")
        seen.add(ac)
        if result in _SETTLE_TERMINAL_RESULTS:
            # T-11657 — the REASON is REQUIRED and NON-EMPTY, and this refusal runs BEFORE any write,
            # so a whitespace-only reason settles NOTHING. This is the fail-closed half of an escape
            # hatch: without it the two terminals would be a cheap way to make a criterion stop
            # asking, which is the opposite of the honesty they exist to record.
            reason = str(raw_companion or "").strip()
            if not reason:
                raise ValueError(
                    f"--settle-probe {raw_probe!r}: a {result!r} settlement REQUIRES a non-empty "
                    f"--settle-reason. This terminal records that the criterion will never be proven "
                    f"({'a proof that can never arrive' if result == 'unreachable' else 'a reading that arrived and came back negative'}) "
                    f"— WHY is the entire content of that record, so an empty reason discharges the "
                    f"debt while saying nothing. Nothing was written.")
            pairs.append((ac, result, None, reason))
            continue
        loc_raw = str(raw_companion or "").strip()
        if _journal_locator(loc_raw) is None and _cross_settle_locator(loc_raw) is None:
            raise ValueError(
                f"--settle-evidence {loc_raw!r} must name a MATERIALIZED evidence row — either a "
                f"MATERIALIZED-JOURNAL locator, `events.jsonl#ts=<ISO-instant>` or "
                f"`events.jsonl#source_ref=<ref>` (the D-0030 citation form), or a COORDINATION-LOG "
                f"locator, `coordination.jsonl#cross=X-NNNN` (T-11297 — for a criterion whose "
                f"evidence is a report-back on the shared store, which lives outside every repo by "
                f"design, SPEC-0084 r5). A bare T-NNNN or a commit sha names WORK, never the evidence "
                f"ROW, so it cannot prove the deferred criterion is now met.")
        pairs.append((ac, result, loc_raw, None))
    return pairs


def _parse_observation_settle(value, reason_args, evidence_args, probe_args, *, _SETTLE_TERMINAL_RESULTS):
    """Parse `--settle-observation`'s value into (locator | None, terminal_mapping | None). PURE.

    Returns (None, None) when the flag is ABSENT (the leg is dormant); raises ValueError with the
    caller-facing reason otherwise, so the whole grammar is refusable BEFORE any write and on ANY task
    status. It refuses ONLY what the grammar SoT cannot see — the argv that composed the value — which
    is the `_parse_live_probe_settled_terminal` / `_parse_settle_pairs` discipline: the vocabulary and
    the non-empty-reason judgement stay in `_post_ship_observation_declaration_error`, not restated here.

    THE LOCATOR PATH IS UNTOUCHED (the T-11950 AC3 regression bound, and the absorbed audit-pre
    finding). A locator run NEVER consumes `--settle-reason`: the same invocation may legitimately
    settle an acceptance-probe TERMINAL (which owns that flag) and an observation LOCATOR together, so
    the reason list is passed on to `_parse_settle_pairs` untouched and its refusals fire exactly as
    before. Only a TERMINAL value diverts the reason — and in that one case a `--settle-probe` in the
    same run is REFUSED, because two carriers cannot positionally own one reason list.
    """
    if value is None:
        return None, None
    raw = str(value).strip()
    if raw not in _SETTLE_TERMINAL_RESULTS:
        return raw, None                     # today's locator path — grammar-checked by the caller
    reasons = [str(r).strip() for r in (reason_args or []) if r is not None]
    if probe_args:
        raise ValueError(
            f"--settle-observation {raw!r} is a TERMINAL discharge and takes --settle-reason, but this "
            f"run also carries {len(probe_args)} --settle-probe, which owns that same flag. One "
            f"reason list cannot be positionally owned by two carriers. Settle the probe(s) and the "
            f"observation in separate runs.")
    if evidence_args:
        raise ValueError(
            f"a TERMINAL --settle-observation ({'/'.join(_SETTLE_TERMINAL_RESULTS)}) takes "
            f"--settle-reason, NOT --settle-evidence (got {len(evidence_args)} --settle-evidence). An "
            f"`unreachable` observation has no evidence row to cite BY DEFINITION — the reading can "
            f"never be taken — and a `falsified` one records that the reading came back NEGATIVE, "
            f"which is not a proof either. Put any locator you do have inside the free-text reason.")
    if len(reasons) != 1 or not reasons[0]:
        raise ValueError(
            f"--settle-observation {raw!r} REQUIRES exactly one non-empty --settle-reason (got "
            f"{len(reasons)}). This terminal records that the declared observation will never be read "
            f"({'the reading can never arrive' if raw == 'unreachable' else 'a reading arrived and came back negative'})"
            f" — WHY is the entire content of that record, so a reasonless terminal discharges the "
            f"debt while saying nothing. Nothing was written.")
    return None, {"result": raw, "reason": reasons[0]}


def _touch_entry_matches_diff(entry: str, touched, *, audit) -> bool:
    """T-11358 — does this `expected_touch`-shaped ENTRY name at least one path in `touched` (the
    recorded commit's diff)? This is the LIST-LEVEL wrapper only: the per-PAIR question «does this
    entry cover this path» is asked of the ONE shared definition, `audit.touch_entry_matches`.

    T-12329 (X-1332) DELETED the local per-pair predicate this function used to spell. It was the
    same idiom as the shared one but not the same SET of alternatives: it had the directory-subtree
    rule and lacked SPEC-id equality, while the shared matcher had SPEC-id and lacked
    directory-subtree. Two definitions of coverage over ONE field is a P5 violation that pays out as
    a contradiction between surfaces, and it did: on <project> T-0602, with `tasks/` declared and 16
    files under `tasks/` shipped, the audit-post readiness row (which reads the shared matcher)
    reported `tasks/` as declared-but-NOT-audited while this fence refused to withdraw it because
    the diff «shows WAS touched». The advisory surface invited precisely the correction this gate
    then refused as a scope change, leaving the card uncorrectable. The shared matcher now carries
    the union of the alternatives (both readers gained the one they lacked), so both surfaces
    necessarily agree.

    The old comment justified keeping it local because the sibling `_agr_covered_by` lives in the
    host (`bin/lib/cli.py`), which this module must not back-import (the inject-residue seam). That
    reason never applied to `lib.audit`, which this module ALREADY imports at load time (see the
    module header) — `lib.audit` back-imports `lib.task` lazily, so the edge stays acyclic.

    Pure; an empty/non-string entry matches nothing, and an empty `touched` matches nothing."""
    if not str(entry or "").strip():
        return False
    return any(audit.touch_entry_matches(entry, raw) for raw in (touched or []))


def _amend_expected_touch(tid: str, declared: list, *, REPO_ROOT, _append_event, _die,
                          _dump_state_yaml, _load_task_for_transition, write_text_atomic,
                          correction: bool = False, reason: "str | None" = None,
                          _recorded_commit_sha=None, _task_diff_files=None,
                          _run_git_cap=None, _prior_audit_record=None, _AMEND_TOUCH_STAGES, _FORECAST_CORRECTION_STAGE, _closure_is_unlanded, _expected_touch_seed_route, _touch_entry_matches_diff) -> None:
    """`task analyze --amend-expected-touch PATH …` — the governed AMENDMENT of an expected_touch
    forecast the card ALREADY carries (T-11251, closing <project> X-0971).

    THE GAP. T-10586 gave the field a seeding path and made the filing-time forecast WIN untouched
    (`if not existing and declared:`), because a prose-derived write had once produced 6 paths where 1
    was real (X-0440). That rule is right and is UNCHANGED here — but it left the field's OWNING verb
    unable to amend a forecast at all, so a coherence sweep that finds one more file (or a forecast
    that turns out simply wrong) had to fall back to `task update --old/--new`: a blunt text
    substitution on a SCOPE-BOUNDARY field, running NONE of the admissibility validation below.

    SEMANTIC: the flags state the COMPLETE amended set — a REPLACE, not a union. A union would make
    the field grow-only, so a wrongly-forecast path could never be withdrawn and would keep
    authorizing an edit forever. To keep replacement from losing an entry silently, the verb prints
    the added/removed diff and carries both on the event.

    The validation is the load-bearing part and is the SAME call the seeding path makes — same three
    injected predicates, same fail-closed die naming every rejection with its reason — but it is
    scoped to the ADDED entries ONLY (T-12329, closing X-1333; see the block at the call site for the
    grounds and the verbatim prior art in `cmd_task_analyze`'s write-back). An entry the card already
    carries, restated unchanged in the complete set, authorizes nothing NEW and is admitted whatever
    its shape; that is what stops one legacy entry from walling off every unrelated correction on a
    pre-rule card. A stated set of nothing is refused rather than written: a scope boundary of
    nothing is not a declaration. And it AMENDS only — a card carrying NO forecast is refused and
    routed to the seeding path, so this never becomes a second writer of the field with different
    semantics (audit-post RED, T-11251).

    TWO ARMS (T-11358, closing <project> X-1023). `correction=False` is the ORDINARY amendment
    above, unchanged: admitted at `_AMEND_TOUCH_STAGES` and free to WIDEN the declared scope, which is
    exactly why it stops at Plan. `correction=True` is the NARROW forecast CORRECTION, admitted at
    `_FORECAST_CORRECTION_STAGE` (Audit-post) ONLY — the seam where the external auditor actually
    catches a mistyped path by reading the forecast against the diff, and until now the seam where no
    route remained at all.

    WHY THE CORRECTION IS ADMITTED WHERE THE AMENDMENT IS NOT, and it is not a loosening. T-11251's
    lock protects against a post-audit WIDENING. A correction cannot widen, and that is enforced
    MECHANICALLY off the recorded commit's diff, never trusted from a flag: an entry the diff never
    touched authorized nothing that happened, so WITHDRAWING it removes authority; an entry the diff
    DID touch was already shipped and already graded, so ADDING it grants none. Anything outside those
    two shapes — withdrawing a path that was really touched, or adding one that was not — is a scope
    change and is REFUSED here, back to the SPEC-0103 / SPEC-0121 §5 escalation that exists today. An
    undeterminable recorded commit or an empty diff refuses fail-closed: a correction that cannot be
    checked against the diff is not admitted.

    IT MOVES NOTHING ABOUT THE AUDIT — the fence the requester's ask most needed. It writes the CARD
    and commits NOTHING (the T-11223 / T-11209 `--live-probe-*` posture): the dirty card is folded by
    `task close`'s own closure-record commit (T-0275), so the recorded audited commit does not move —
    and a standalone `task commit` here would be refused by `_audit_commit_shift_hazard` anyway. It
    never opens `decisions/<tid>-audit-post.yaml`, so the verdict and its pinned `commit:` are
    untouched by construction and a RED stays RED. The recorded sha rides the event as
    `audited_commit`, so the no-move claim is checkable from the journal rather than merely asserted.
    It records that the forecast was WRONG; it does not make the ship RIGHT.

    THIRD ADMISSION — THE POST-CLOSE REWORK (T-11931, <project> X-1212). The two arms above BOTH sit
    behind a flat `status == "in-progress"` gate, so a card in a SANCTIONED post-close rework — the
    DEFAULT recovery QUEUE §Prematurely-closed names for a `done` card whose closure never reached
    `main` — was refused before either stage gate was even consulted, and routed to escalation. That
    rework may legitimately ADD a file (<project> 2026-08-31 added
    `backend/app/tasks/pipeline_ozon_fbs_warehouses.py`, re-audited GREEN), leaving the forecast
    under-reporting the shipped footprint with no way to fix it.

    It is the SAME leg T-11458 opened for `acceptance`, on the SAME terms and no looser ones: the
    admission is DERIVED by `_closure_is_unlanded` reading what `main` SAYS about the card (`ready` /
    `in-progress` = the closure is still branch-local; `done`, a terminal decision that reached main,
    or ANY undeterminable state refuses fail-closed), never asserted by a flag — so a card whose
    closure LANDED cannot reach this route at all, and the T-0367 / T-10110 no-reopen boundary is
    untouched. It is the FOURTH leg of that recovery beside `task test --run` (T-10975), `work commit`
    (T-0367) and `audit post --reaudit-after-close` (T-9412 / T-10094).

    WHAT THE POST-CLOSE ARM CHANGES, AND IT IS ONLY THIS: which commit supplies the fence's `touched`
    set. The `_FORECAST_CORRECTION_STAGE` lock is SKIPPED — a `done` card has no live Audit-post stage
    (`stage Audit-post` hard-refuses one), so the stage check is structurally unsatisfiable here and
    the DERIVED post-close admission stands in its place; that is a substitution, not a widening, and
    `_AMEND_TOUCH_STAGES` / `_FORECAST_CORRECTION_STAGE` are both untouched. The graded commit is read
    from the LATEST audit-post RECORD's `commit:` (`_prior_audit_record(tid, "post")`), because
    `audit post --reaudit-after-close` always grades HEAD and pins it there (bin/lib/audit.py) — the
    recorded `commit_landed` the in-progress arm uses is the PRE-rework ship and would fence against
    the wrong diff. Everything downstream — the entry validation, the replace semantics, and the two
    no-widening refusals — is the SAME code, unmodified: the correction still cannot add a path the
    graded diff did not touch, nor withdraw one it did. Fail-closed in every undeterminable direction,
    exactly as the in-progress arm: an un-injected collaborator, a missing audit-post record, a record
    pinning no commit, or an empty diff all REFUSE, back to the SPEC-0103 / SPEC-0121 §5 escalation
    that exists today. The `task_amended` row carries `post_close: true` so a later reader sees the
    closure PRECEDED the correction (the T-11458 marker, same key, same meaning).
    """
    yaml, path, task = _load_task_for_transition(tid)
    tid = task.get("id") or tid
    # ── T-11931 (X-1212): the THIRD admission — a post-close REWORK, derived, never asserted ───────
    # The status gate below used to be flat, so a `done` card was refused here BEFORE either stage
    # gate was consulted: the sanctioned rework-in-place had no governed route to correct the
    # forecast its own re-audited diff had outgrown. This admits exactly ONE further shape, on
    # T-11458's terms: a CORRECTION on a `done` card whose closure `_closure_is_unlanded` PROVES is
    # still branch-local. `correction` is required — the ordinary (widening-capable) amendment gains
    # nothing here. Fail-closed by construction: an un-injected `_run_git_cap`, an unreadable `main`,
    # or a `main` that says anything outside _UNLANDED_CLOSURE_MAIN_STATUSES leaves this False, and
    # the unchanged refusal below fires with `main`-side authority intact.
    from pathlib import Path as _Path
    post_close = bool(
        correction and task.get("status") == "done" and _run_git_cap is not None
        and REPO_ROOT is not None
        and _closure_is_unlanded(tid, path, REPO_ROOT=_Path(REPO_ROOT), _run_git_cap=_run_git_cap))
    if task.get("status") != "in-progress" and not post_close:
        _extra = ""
        if task.get("status") == "done":
            _extra = (" This card is done and its closure REACHED `main` (or could not be proven "
                      "otherwise), so the post-close forecast-correction route does NOT apply: a "
                      "LANDED done task has NO reopen — file a NEW task (LIFECYCLE §Stage 9, T-0367 "
                      "/ T-10110). Unlanded-ness is determined from `main`, never asserted; and the "
                      "route is the CORRECTION arm only (`--forecast-correction --reason <why>`), "
                      "never the widening-capable ordinary amendment.")
        _die(f"{tid} status={task.get('status')!r} — amend the forecast on a CLAIMED card "
             f"(`worktree new --task {tid}` is the claim per T-0124/D-0037).{_extra}")
    stage = task.get("current_stage")
    touched: list = []
    audited_sha = None
    if not correction:
        # ORDINARY AMENDMENT — unchanged (T-11251). The refusal now NAMES the correction route, so a
        # worker at Audit-post reading this message is not told merely "no" at the one stage where a
        # governed route does exist; being told "escalate" while a covering verb existed is the shape
        # of miss this card was filed against.
        if stage not in _AMEND_TOUCH_STAGES:
            hint = ""
            if stage == _FORECAST_CORRECTION_STAGE:
                hint = (f" At {_FORECAST_CORRECTION_STAGE} a wrong forecast IS correctable, but only "
                        f"as a CORRECTION fenced against the ship diff: re-run with "
                        f"`--forecast-correction --reason \"<why the forecast was wrong>\"` (T-11358). "
                        f"That arm can withdraw an entry the diff never touched and add one it did — "
                        f"it cannot widen the scope, which is what this refusal protects.")
            _die(f"{tid}: expected_touch may be amended at {' or '.join(_AMEND_TOUCH_STAGES)} only — this "
                 f"card is at {stage!r}. From Audit-pre onward you need not amend it at all: expected_touch "
                 f"is a forecast that `task commit` refreshes from the ship diff (T-12302), so a file "
                 f"the forecast missed — a re-signed spec, a test — is simply committed (a spec re-sign "
                 f"via `task commit {tid} --reverify <SPEC>`). Only a genuine change of the task's "
                 f"intended scope is an escalation (SPEC-0103 — `blocked-on-land {tid} <reason>`, "
                 f"worktree intact)."
                 f"{hint} The card is untouched.")
    else:
        # ── T-11358 CORRECTION ARM (<project> X-1023) ──────────────────────────────────────────
        # One route per stage, never two overlapping ones: the correction is admitted at Audit-post
        # ONLY, and at Analysis/Plan the ORDINARY amendment is the route (it is strictly more capable
        # there — it may widen). So this refusal routes rather than merely refusing.
        if stage != _FORECAST_CORRECTION_STAGE and not post_close:
            if stage in _AMEND_TOUCH_STAGES:
                _die(f"{tid}: --forecast-correction is the {_FORECAST_CORRECTION_STAGE} arm — this card "
                     f"is at {stage!r}, where the ORDINARY amendment applies and is strictly more "
                     f"capable (it may widen the forecast; the correction may not). Drop "
                     f"--forecast-correction/--reason and re-run the plain "
                     f"`--amend-expected-touch`. The card is untouched.")
            _die(f"{tid}: --forecast-correction is admitted at {_FORECAST_CORRECTION_STAGE} ONLY — the "
                 f"seam where the external auditor reads the forecast against the diff and catches a "
                 f"mistyped path. This card is at {stage!r}: at "
                 f"{' or '.join(_AMEND_TOUCH_STAGES)} use the ordinary `--amend-expected-touch`; "
                 f"anywhere else a scope change is an ESCALATION, not self-service (SPEC-0103 / "
                 f"SPEC-0121 §5 — `blocked-on-land {tid} <reason>`, worktree intact). The card is "
                 f"untouched.")
        # THE REASON IS A CONTRACT, NOT A COURTESY — fail-closed, the none-with-reason discipline the
        # sibling `--live-probe-none` / `--pv-waive` legs apply. A correction carrying no ground is
        # indistinguishable from a silent post-audit scope edit, which is the thing the stage lock
        # exists to catch; accepting it would have removed the gate rather than covered it.
        reason = (str(reason).strip() if reason is not None else "")
        if not reason:
            _die(f"{tid}: --forecast-correction requires --reason \"<why the forecast was wrong>\" "
                 f"(non-empty). The reason is recorded on the task_amended row — it is what makes this "
                 f"a CORRECTION on the record rather than an unexplained post-audit edit of a "
                 f"scope-boundary field. The card is untouched.")
        # THE FENCE IS COMPUTED, NEVER TRUSTED. Everything below reads the diff of the commit the
        # auditor actually graded; a flag asserts nothing here. FAIL-CLOSED in every undeterminable
        # direction — an un-injected collaborator, no recorded commit, or an empty diff all refuse,
        # because the alternative is an UNCHECKED correction and the fallback (escalate per SPEC-0103)
        # is the path that exists today. This is the opposite posture from a report-only observer:
        # the fence adds a permission, so an unreadable state must never manufacture one.
        if post_close:
            # ── T-11931: the POST-CLOSE fence SOURCE, and it is the only thing this arm forks ──────
            # `audit post --reaudit-after-close` always grades HEAD and pins it as the verdict's
            # `commit:` (bin/lib/audit.py), so the commit the auditor ACTUALLY graded is the latest
            # audit-post RECORD's — not the card's recorded `commit_landed`, which on a post-close
            # rework is the PRE-rework ship and would fence the correction against the wrong diff
            # (silently refusing exactly the file the rework added — the X-1212 case). Read from the
            # record, never guessed. Fail-closed on every undeterminable direction, as above.
            if _prior_audit_record is None or _task_diff_files is None:
                _die(f"{tid}: the post-close --forecast-correction cannot be checked — this "
                     f"invocation has no audit-record / diff collaborator wired, so the fence that "
                     f"keeps a correction from becoming a scope change cannot be computed. Refusing "
                     f"fail-closed (T-11931); the card is untouched.")
            _rec = _prior_audit_record(tid, "post") or {}
            audited_sha = str(_rec.get("commit") or "").strip() or None
            if not audited_sha:
                _die(f"{tid}: the post-close --forecast-correction needs the commit the auditor "
                     f"GRADED to fence against, and no audit-post record for this card pins one. The "
                     f"correction is defined against what the re-audited ship diff actually touched, "
                     f"so with no graded commit there is nothing to check it with: re-audit the "
                     f"current tree first (`audit post --task {tid} --reaudit-after-close`, the "
                     f"T-9412 leg of the same rework route). The card is untouched.")
        elif _recorded_commit_sha is None or _task_diff_files is None:
            _die(f"{tid}: --forecast-correction cannot be checked — this invocation has no "
                 f"recorded-commit / diff collaborator wired, so the fence that keeps a correction "
                 f"from becoming a scope change cannot be computed. Refusing fail-closed (T-11358); "
                 f"the card is untouched.")
        else:
            audited_sha = _recorded_commit_sha(tid)
            if not audited_sha:
                _die(f"{tid}: --forecast-correction needs a RECORDED commit to fence against, and this "
                     f"card has none (no `commit_landed` — D-0082). The correction is defined against "
                     f"what the ship diff actually touched, so before Stage 7 there is nothing to check "
                     f"it with: at {' or '.join(_AMEND_TOUCH_STAGES)} use the ordinary "
                     f"`--amend-expected-touch`. The card is untouched.")
        touched = list(_task_diff_files(audited_sha) or [])
        if not touched:
            _die(f"{tid}: the recorded commit {audited_sha[:12]} yields an EMPTY diff, so no entry can "
                 f"be checked against what the ship touched. A correction that cannot be verified is "
                 f"not admitted (fail-closed, T-11358) — escalate instead (SPEC-0103 / SPEC-0121 §5). "
                 f"The card is untouched.")
    before = [str(x) for x in (task.get("expected_touch") or []) if str(x).strip()]
    if not before:
        # This mode AMENDS; it does not SEED. Letting it write a forecast onto a card that carries
        # none would give the field a SECOND writer with different semantics (replace, admitted at
        # two stages) beside the T-10586 seeding path — the separation AC2 exists to keep, and the
        # one the audit-post RED named. Refuse and route to the seeding verb.
        # T-12028 (X-1254): the refusal is UNCHANGED in what it refuses — this mode still never
        # seeds (T-11251) — but it now hands the reader the SAME route string the WARN does, from
        # the one carrier. Previously it named the flags in an order that is not the admitted shape
        # and said nothing about the stage bound, so a reader who followed it from Plan hit a second
        # dead end. Refusing while a covering route exists is fine; refusing without NAMING it is
        # the miss this card was filed against.
        _die(f"{tid} carries NO expected_touch forecast — there is nothing to amend, and this mode "
             f"does not SEED one (that would give the field a second writer beside T-10586's "
             f"declaration path, with different semantics). "
             f"{_expected_touch_seed_route(tid)} "
             f"(An `expected_touch:` line in the analysis record is the equivalent declaration.) "
             f"The card is untouched.")
    # ── T-12329 (X-1333) — VALIDATE ONLY WHAT THIS AMENDMENT ADDS ────────────────────────────────
    # The delta is computed FIRST, and `textutil.validate_touch_entries` then runs over the ADDED
    # subset ALONE. A CARRIED entry — one already in the card's forecast and restated unchanged in
    # this complete set — never reaches an admissibility predicate, so it is admitted whatever its
    # shape.
    #
    # WHY. Both amend arms state the COMPLETE amended set (a replace, not a merge), so correcting
    # ANY entry means restating EVERY other one. Validating the whole stated set therefore made a
    # single legacy entry a wall in front of every unrelated correction: a card filed before the
    # bare-directory rule (X-0440) carries e.g. `tasks/`, which cannot be WITHDRAWN (the fence below
    # reads the diff as having touched it) and could not be RESTATED either (rejected
    # `bare-directory`) — so no correction to any other entry could be expressed at all, and a whole
    # generation of pre-rule cards was uncorrectable through the governed verb. The admissibility
    # rules exist to stop a NEW authorization being written (SPEC-0103: each entry authorizes an
    # edit); a carried entry authorizes nothing new, because the card already authorized it.
    #
    # PRIOR ART, verbatim and in this same field's sibling writer — `cmd_task_analyze`'s Stage-1
    # write-back: "Validate ONLY what we are about to WRITE (the declaration). `existing` is the
    # analyst's own filing-time forecast, which by contract WINS untouched — re-validating it here
    # would refuse cards over a field this verb is not authoring." This is that rule, owed to the
    # amend mode.
    #
    # NOTHING ELSE IS RELAXED: an entry this amendment ADDS takes the full fail-closed validation,
    # by name — so a NEW bare directory, a non-repo path or an unanchored scratch name is refused
    # exactly as before.
    wanted, seen = [], set()
    for raw in (declared or []):
        e = str(raw).strip()
        if e and e not in seen:
            seen.add(e)
            wanted.append(e)
    before_set = {str(x).strip() for x in before}
    added = [e for e in wanted if e not in before_set]
    removed = [e for e in before if str(e).strip() not in seen]
    _, rejections = textutil.validate_touch_entries(
        added,
        repo_contained=lambda p: (not os.path.isabs(p)
                                  and not os.path.normpath(p).startswith("..")),
        is_dir=lambda p: (REPO_ROOT / p).is_dir(),
        exists=lambda p: (REPO_ROOT / p).exists())
    if rejections:
        detail = "\n".join(f"    {e}  → {why}" for e, why in rejections)
        _die(f"{tid}: refusing {len(rejections)} inadmissible expected_touch "
             f"entr{'y' if len(rejections) == 1 else 'ies'} this amendment ADDS:\n{detail}\n"
             f"  expected_touch is a SCOPE-BOUNDARY declaration (SPEC-0103) — every entry authorizes "
             f"an edit, so it takes in-repo FILES (or an explicit glob like `backend/app/**` for a "
             f"deliberate subtree), never an out-of-repo path, a bare directory, or an unanchored "
             f"scratch name. Only ADDED entries are checked (T-12329): an entry the card already "
             f"carries, restated unchanged in this complete set, is admitted whatever its shape. "
             f"The card is untouched; fix the declaration and re-run (X-0440).")
    # The FLOOR is a NON-EMPTINESS check on the STATED set, and nothing more: it asks "did the
    # operator state anything at all", never "is every stated entry admissible" (T-12329 audit-pre
    # mode-b absorption). So a stated set consisting ONLY of carried entries — including a
    # carried-only legacy bare directory — passes it and writes.
    if not wanted:
        _die(f"{tid}: an amendment must declare at least one path — a scope boundary of "
             f"nothing is not a declaration. The card is untouched.")
    after = list(wanted)
    if correction:
        # ── T-11358 THE FENCE, computed on the delta this verb already derives ────────────────────
        # Two shapes are admitted and NOTHING else, both read off the graded diff:
        #   WITHDRAW an entry the diff never touched  — it authorized nothing; this REMOVES authority.
        #   ADD an entry the diff DID touch           — already shipped, already graded; grants none.
        # The two refusals below are the whole difference between this and a post-audit scope edit,
        # so they name the entry and say which shape was violated. Both leave the card untouched
        # (nothing is written until after this block).
        bad_removed = [e for e in removed if _touch_entry_matches_diff(e, touched)]
        if bad_removed:
            _die(f"{tid}: refusing to WITHDRAW {len(bad_removed)} forecast entr"
                 f"{'y' if len(bad_removed) == 1 else 'ies'} the ship diff shows WAS touched: "
                 f"{', '.join(bad_removed)}. A correction withdraws a forecast that named a path the "
                 f"work never went near — that is the mistype. Withdrawing a path that WAS touched "
                 f"un-declares a real edit after the auditor graded it, which is a scope change: "
                 f"escalate instead (SPEC-0103 / SPEC-0121 §5 — `blocked-on-land {tid} <reason>`, "
                 f"worktree intact). Checked against commit {audited_sha[:12]}; the card is untouched.")
        bad_added = [e for e in added if not _touch_entry_matches_diff(e, touched)]
        if bad_added:
            _die(f"{tid}: refusing to ADD {len(bad_added)} forecast entr"
                 f"{'y' if len(bad_added) == 1 else 'ies'} the ship diff did NOT touch: "
                 f"{', '.join(bad_added)}. At {_FORECAST_CORRECTION_STAGE} a forecast may only be "
                 f"corrected to what the ship ACTUALLY touched — adding an untouched path would widen "
                 f"the scope boundary after the auditor blessed it, and every entry AUTHORIZES an edit "
                 f"(SPEC-0103). That is the escalation SPEC-0121 §5 keeps for the owner, not "
                 f"self-service. Checked against commit {audited_sha[:12]}; the card is untouched.")
    task["expected_touch"] = after
    # The CARD ONLY, and nothing is committed — the `--live-probe-*` posture (T-11223 / T-11209). The
    # dirty card is folded by `task close`'s own closure-record commit (T-0275), so the recorded
    # audited commit does not move; `decisions/<tid>-audit-post.yaml` is never opened, so the verdict
    # and its pinned `commit:` are untouched by construction and a RED stays RED.
    write_text_atomic(path, _dump_state_yaml(task))
    _append_event("task_amended", tid, {"amend_expected_touch": True,
                                        "fields": ["expected_touch"],   # T-11174 qualification key
                                        "before": before, "after": after,
                                        "added": added, "removed": removed,
                                        "current_stage": stage,
                                        # T-11358 — the correction's own record. `audited_commit` is
                                        # what makes the no-move claim CHECKABLE from the journal
                                        # rather than merely asserted in a docstring.
                                        **({"forecast_correction": True,
                                            "correction_reason": reason,
                                            "audited_commit": audited_sha} if correction else {}),
                                        # T-11931 — the SAME marker T-11458 writes for the sibling
                                        # post-close acceptance amend: a later reader must see that
                                        # the closure PRECEDED this correction.
                                        **({"post_close": True} if post_close else {})})
    print(f"{tid} expected_touch {'CORRECTED' if correction else 'amended'} at stage {stage}"
          f"{' (POST-CLOSE — closure still branch-local)' if post_close else ''} "
          f"({len(before)} → {len(after)} entr{'y' if len(after) == 1 else 'ies'} — REPLACED, "
          f"not merged: the flags stated the COMPLETE set) — "
          f"task_amended({'amend_expected_touch,forecast_correction' if correction else 'amend_expected_touch'}) emitted")
    if added:
        print(f"  + {', '.join(added)}")
    if removed:
        print(f"  - {', '.join(removed)}  (withdrawn — no longer authorizes an edit)")
    if not added and not removed:
        print("  (unchanged — the declaration already said exactly this)")
    if correction:
        print(f"  reason: {reason}")
        print(f"  fenced against the {'GRADED audit-post' if post_close else 'RECORDED audit'} "
              f"commit {audited_sha[:12]} ({len(touched)} path(s) in its diff)")
        print("  the audit is UNMOVED: nothing was committed, the audit-post verdict and its pinned "
              "`commit:` were never opened, and a RED stays RED. This records that the forecast was "
              "wrong; it does not make the ship right. `task close` folds the dirty card into its own "
              "closure-record commit, so the audited commit does not move (T-11358).")


def _parse_iso_utc(raw: str):
    """An ISO-8601 instant → an aware UTC datetime, or None when it is not one (T-11174). Accepts
    both spellings the two sources use: the journal's `...Z` and git `%cI`'s `...+03:00`. A naive
    value is read as UTC (the journal's own convention). Never raises."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        dt = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)
