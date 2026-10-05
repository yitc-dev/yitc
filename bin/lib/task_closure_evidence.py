"""task_closure_evidence — the task-closure EVIDENCE family, extracted byte-identical out of
bin/lib/task.py (T-12697, plan extract-the-13-over-budget-bin-lib-modules-into-le, card C8a).

A LEAF: imports only lib.state / lib.events-tier leaves + stdlib and NEVER `lib.task`. Every
host collaborator, host const and moved SIBLING a body names arrives as a keyword-only injected
parameter (the host residue under the historical name supplies them, so `task.<symbol>`
monkeypatches keep resolving at call time — lessons/library-extraction.md §full inject-residue).
The bodies below are VERBATIM copies of their bin/lib/task.py originals at baseline 02250d5;
this module is intentionally spec-less (SPEC-0005 admission test) — the governing specs keep their
homes and re-point their `implements:` anchors here.
"""
from __future__ import annotations
import datetime as _dt
import fnmatch
import json
import os
import re
from pathlib import Path
from lib import followup   # noqa: E402
from lib import init       # noqa: E402
from lib import inspection  # noqa: E402
from lib import journal as journal_mod  # noqa: E402
from lib import state      # noqa: E402
from lib import textutil   # noqa: E402
from lib import triage     # noqa: E402

# T-10282 (X-0246, SPEC-0015 §The EVENT carrier must resolve machine evidence + a differential) — the
# event types a P8 adoption payload may NOT cite as its machine evidence. Each entry earns its place:
#   consumer_read_evidence / live_trigger_evidence — the P8 types themselves. Session-HAND-emitted (V2
#     has no automated emitter, SPEC-0015 §Event-based P8), so citing one to prove another proves
#     nothing: the closing session issues both. This is the circularity the T-9416 incident rode.
#   tests_passed — CHARTER §Principle 8 states it outright: «"Tests green" BY ITSELF is NOT sufficient
#     for infrastructure closure». A test proves the code runs when CALLED, not that anything adopted it.
#   commit_landed / task_closed / land_completed — closure BOOKKEEPING every task earns for free by
#     reaching Stage 7/9. They prove the TASK closed; they can never distinguish an adopted mechanism
#     from an unadopted one, so they carry zero differential signal.
# Deliberately SHORT and charter-grounded, not an open-ended blocklist: anything else a mechanism
# genuinely emits (deploy_completed, live_probe_passed, spec_edited, …) is admissible evidence.
#   FOUR correlated exceptions, all on `land_completed`, each earning its way out by carrying a
#   correlation the bare type lacks — never by type.
#   (1) (T-10485 / X-0339 — SPEC-0015 §Land-emitted verify-layer ships): the
#     LAYER-ROW ref `land_completed@<ts>#<layer>` (`_resolve_layer_row_ref`). A verify-layer ship's
#     mechanism emits no event of its own — its only trace is a row land writes onto THIS same
#     land_completed — so the blanket refusal left the class with nothing citable. The row earns its
#     way out of the blocklist by carrying the correlation the bare event lacks (own land + a layer no
#     earlier land ran); the bare type stays refused, here and everywhere.
#   (2) (T-10937 — the never-landing-abort ship class; WIDENED by T-11421 to every LAND-TIME GATE
#     REFUSAL): the ABORT-ROW ref
#     `land_completed@<ts>#branch=<branch>` (`_resolve_abort_row_ref`). A mechanism whose OUTPUT IS
#     the abort row (T-10795 routes a `_LAND_NEVER_LANDING_ABORT_CLASSES` abort to the MAIN journal,
#     the discarded branch having no next land to fold it into) had likewise nothing citable. Its
#     correlation is the pinned ts + `status: abort` + an `abort_class` naming a land-time GATE
#     REFUSAL (`_ABORT_ROW_EVIDENTIAL_CLASSES`) + the named branch — a shape an ORDINARY closure row
#     (`status: ok`, no abort_class) can never wear.
#   (3) (T-11005 — the VERIFY-REFUSAL ship class): the ref
#     `land_completed@<ts>#refused=<test-node>&branch=<branch>` (`_resolve_verify_refusal_row_ref`).
#     A task whose shipped MECHANISM IS the land-verify gate can only ever emit the abort row the gate
#     writes when it REFUSES an integration — the mechanism RUNNING — and that row is this same
#     blocklisted type, so the class had nothing citable either. Its correlation is the pinned ts +
#     `status: abort` + a verify-refusal `abort_class` from the real (non-preflight) run + the branch
#     bound to the CLOSING TASK's own id + the row NAMING the test node the ref names. It does NOT
#     re-open (2)'s deliberate refusal of a bare `verify-failed` row (test_t10937 B3): that row carries
#     no `failing_tests`, so it fails this selector's naming condition and stays refused.
#   (4) (T-11570 — the POST-SHIP PAYLOAD-KEY READING ship class): the ref
#     `land_completed@<ts>#metric=<key>` (`_resolve_metric_row_ref`). A card whose acceptance is a
#     SPEC-0036 variant-(e) reading of a key the land runner writes onto `verify_metrics` cannot carry
#     that reading at its OWN closure — `land` runs from the MAIN checkout, so the key first appears
#     on a LATER, unrelated land — so its only honest proof is an ordinary `status: ok` row on ANOTHER
#     branch. That is why the three selectors above cannot serve it: two bind the CITING task's own
#     `task/<tid>` branch and all three require an ABORT row. Measured on T-11460, whose truthful
#     pinned-by-ts refs are honest and demonstrably do not resolve (T-11530 captured the gap rather
#     than dressing it with a ref that would resolve while proving nothing). Its correlation is the
#     pinned ts + the row CARRYING the named key + the key having HAD A BEGINNING (an earlier row
#     whose `verify_metrics` lacks it) — the last condition being what keeps a key every land has
#     always carried, like `verify_wall_ms`, from becoming free evidence for anyone.
_NON_EVIDENTIAL_EVIDENCE_TYPES = frozenset({
    "consumer_read_evidence", "live_trigger_evidence",
    "tests_passed",
    "commit_landed", "task_closed", "land_completed",
})
_LAYER_ROW_EVIDENCE_TYPE = "land_completed"   # the sole blocklisted type carrying a per-MECHANISM row


def _live_dependents(tasks_dir, tid: str, *, TASK_TERMINAL_STATUSES) -> list:
    """Cards whose `requires:` names `tid` and that are NOT themselves settled (T-12644).

    Args:
      tasks_dir: this repo's `tasks/` directory (missing / unreadable ⇒ `[]` — a repo with no cards
        strands nothing, so the seam is never charged for state it does not hold).
      tid: the id of the card being retired or parked.

    Returns a list of `{"task", "status", "title"}`, sorted by task id so the order is stable across
    folds. Pure: reads files, writes nothing, no clock, no subprocess — the
    `debt.unpickable_ready_cards` shape (SPEC-0149 §2), reused rather than re-invented.

    Never raises: a report-only reading must never break the seam it rides."""
    try:
        paths = list(state.scan_tasks(Path(tasks_dir)))
    except (OSError, TypeError):
        return []
    want = (tid or "").strip()
    if not want:
        return []
    out = []
    for path in paths:
        try:
            # `card_status` first, off the SAME memo `load_path` reads — a SETTLED dependent can be
            # stranded by nothing, so this skips materialising the bulk of a mature `tasks/` corpus
            # (the T-12030 narrowing, applied to this fold's own subject).
            status = state.card_status(path)
            if status in TASK_TERMINAL_STATUSES:
                continue
            doc = state.load_path(path)
            if not isinstance(doc, dict):
                continue
            did = doc.get("id")
            if not isinstance(did, str) or did.strip() == want:
                continue                 # never report the closing card against itself
            reqs = doc.get("requires")
            reqs = reqs if isinstance(reqs, list) else []
            if not any(isinstance(r, str) and r.strip() == want for r in reqs):
                continue
            title = doc.get("title")
            dstatus = doc.get("status")
            out.append({"task": did.strip(),
                        "status": dstatus.strip() if isinstance(dstatus, str) else None,
                        "title": title if isinstance(title, str) else None})
        except Exception:                # noqa: BLE001 — report-only: one bad card, never the seam
            continue
    return sorted(out, key=lambda d: d["task"])


def _closure_record_pathspecs(task_rel: str, audit_records: "list[str]", spec_ids: "list[str]",
                              *, repo_root, bookkeeping_allowlist=()) -> "list[str]":
    """T-11357 (X-1020) — the EXPLICIT staging set of `task close`'s closure-record commit, as sorted
    repo-relative posix pathspecs.

    The closure-record commit's own message says it stages the closure record — the task YAML, the
    journal delta and the task's audit-post verdict. It did not: it passed NO `pathspecs`, so
    `_commit_worktree` took its default `git add -A` and swept EVERYTHING dirty or untracked in the
    worktree. In <project> that put a `.close.yaml` stdin payload, written into the repo root only
    because /tmp was permission-denied, into closure-record commit ff4c8a9 — where it then surfaced as
    a branch-authored post-audit path at another verb's `worktree sync` pre-flight and forced a
    re-audit for a file that was no part of the ship.

    EXCLUDE rather than REFUSE, and the fork is by CONTEXT, not taste. The DIRECT-TO-MAIN self-commits
    (`memory consume` T-10307, `memory seed` T-10470, `task close --settle-probe` T-11162) refuse on
    preexisting dirt because they commit straight to `main`: nothing they mis-stage is reversible and
    nothing they leave behind is caught later. This commit is the OTHER family — the in-WORKTREE
    terminal record-commits (`task update --status wont-do` E-0037/T-9539, park T-9622, `task pause`
    T-10499/X-0359), which scope their staging and leave unrelated dirt in the working tree, where
    `land`'s pre-integrate dirt guard is the fail-closed backstop. Same core, same worktree, same
    terminal-record shape → reuse their `pathspecs` path, add no new gate (CHARTER §P1 F1/F2).

    The set is NOT read off the commit message — it is every path `cmd_task_close` itself writes before
    committing, so the tightening cannot become an UNDER-staging (the card's AC2):
      - `task_rel`         — the task YAML (`_write_task_transition` + the closes-fp / pv folds);
      - `audit_records`    — the task's own dirty audit records, from `_foldable_audit_records`
                             (tid-named lifecycle records PLUS the slug-named `*-audit-adhoc.yaml`
                             the tid glob can never match — T-10824/X-0682);
      - `spec_ids`         — the spec YAMLs THIS closure writes: `--reverify` re-stamps (T-1177) and
                             `_activate_task_proposed_specs` activations/supersessions (T-0199);
      - `bookkeeping_allowlist` — `events.jsonl` plus the `graph/` derived views close's own
                             `_auto_rebuild_graph("task_close")` regenerates (the host's
                             `_BOOKKEEPING_ALLOWLIST`, reused rather than re-listed — P5).
    Staging an UNMODIFIED path is a git no-op, so naming a path that this particular close did not
    touch cannot widen the commit. A path ABSENT from disk is dropped, because `git add -- <pathspec>`
    FAILS HARD on a pathspec that matches nothing ("did not match any files") — and a closure must not
    die because a repo has not yet generated one of the derived views the allowlist names. Absence is
    the only reason to drop one: this close writes no deletion, so nothing owed to the commit is lost
    by the filter. PURE: one `specs/` glob + an existence check, no git, no events, no writes."""
    out = {task_rel, *(audit_records or ()), *(bookkeeping_allowlist or ())}
    specs_dir = Path(repo_root) / "specs"
    for sid in spec_ids or ():
        for sp in specs_dir.glob(f"{sid}-*.yaml"):
            if sp.is_file():
                out.add(sp.relative_to(repo_root).as_posix())
    return sorted(x for x in out if x and (Path(repo_root) / x).exists())


def _closure_record_excluded(dirty: "list[str]", pathspecs: "list[str]") -> "list[str]":
    """T-11357 — the dirty paths the scoped closure-record commit will NOT stage, sorted.

    PURE f(dirty, pathspecs) → the report AC3 asks for: a close that cannot honour its documented
    staging set must SAY what it left out, never drop it silently. Report-only by construction — the
    caller prints it and proceeds (the E-0005 / T-0298 report-only precedent); nothing branches on it.

    `git status --porcelain` COLLAPSES a wholly-untracked directory to one bare `decisions/` entry
    (T-10518), so a collapsed dir whose contents ARE in the staged set must not be reported as
    excluded — hence the prefix arm. It is deliberately one-directional: only a `dir/`-shaped dirty
    entry is matched by prefix, so a real file never counts itself covered by an unrelated path."""
    staged = set(pathspecs or ())
    out = []
    for d in dirty or ():
        if d in staged:
            continue
        if d.endswith("/") and any(s.startswith(d) for s in staged):
            continue          # porcelain-collapsed dir whose contents are staged (T-10518)
        out.append(d)
    return sorted(set(out))


def _closure_record_exclusion_notice(tid: str, excluded: "list[str]") -> "str | None":
    """T-11357 (AC3) — the operator-facing text for `_closure_record_excluded`, or None when the
    closure record honours its staging set exactly. PURE, so the wording is testable without git."""
    if not excluded:
        return None
    return (f"WARN: {tid} closure record staged its documented set ONLY — these dirty path(s) were "
            f"left OUT of it: {', '.join(excluded)}\n"
            f"  A closure-record commit stages the closure record (the task YAML, the journal delta, "
            f"the task's own audit records + the spec/graph updates this closure itself wrote); an "
            f"unrelated path riding it ships un-audited and forces a re-audit at the next "
            f"`worktree sync` pre-flight (T-11357 / X-1020). They stay in the worktree — commit them "
            f"deliberately or remove them, or `land` will refuse (its dirt guard is the backstop).\n")


def _event_task_id(ev: dict) -> "str | None":
    """The task id an event is tied to — SPEC-0168 rule 2's DUAL carrier, resolved in ONE place.
    The corpus carries a task id BOTH at the row's TOP LEVEL (`task_id`, the `_append_event` shape)
    AND inside `data.task_id` (emitters that record the binding in the payload); both are in live use.
    A reader that checks only one carrier silently DROPS evidence — that is precisely the X-0558
    failure. Top level wins when both are present; returns None when neither carries one (such a row
    is never folded — rule 2's exactness is the caller's `== tid` test, not a truthiness test).

    T-11092 (X-0868) — THE THIRD, CLOSED, LAST-PRECEDENCE CARRIER `data.task`. The docstring above
    warns that each carrier a reader must remember is a place evidence can be dropped, and that
    warning is why this clause is LAST and why it is CLOSED rather than merely added:
      WHY IT IS HERE. `data.task` is not a new carrier this function invents — it is one the corpus
      already had and one ANOTHER reader over the SAME corpus has honored since run 9:
      `journal._dispatch_task_of` resolves exactly "top-level `task_id` OR the legacy `data.task`",
      and `journal._event_task_of` builds on it. Two readers disagreeing about one corpus IS the
      defect: 217 rows in this repo's journal bind their task ONLY this way (live_trigger_evidence
      90, bg_dispatch_halted 30, dispatch_outcome 28, startup_protocol_completed 27,
      deviation_captured 19, consumer_read_evidence 9, + a tail), and every one of them fell out of
      the AC-probe fold with NO trace — the T-10827 excluded-types sink cannot report them either,
      since its predicate requires the row to tie by task_id first. That silence is what burned
      <project> an audit-post pass against the ceiling with the evidence PRESENT.
      WHY IT IS CLOSED, so the set of carriers stops at three. The 217 were ALL hand-emitted through
      `cmd_event`; no code path emits this shape. `task` is now a RESERVED `--data` key there
      (RESERVED_DATA_KEY_REDIRECT), so no new row can take this form. This clause is therefore a
      bounded read over a FROZEN legacy population, not an open third ingress — the journal is
      append-only (one flock O_APPEND chokepoint), so those 217 rows cannot be made canonical by
      emission and a reader is the only thing that can ever reach them.
      WHY IT MUST BE LAST, proven on the corpus. 31 rows (all `spec_reverified`) carry a `data.task`
      that DISAGREES with their own canonical carrier — there the key is a payload field naming a
      RELATED task, not the row's subject. All 31 carry a canonical carrier, so they never reach a
      last-precedence fallback and their reading is unchanged; placed first, this clause would have
      mis-tied every one of them. Precedence: task_id -> data.task_id -> data.task."""
    subj = ev.get("task_id")
    if subj is not None:
        return subj
    d = ev.get("data")
    if not isinstance(d, dict):
        return None
    subj = d.get("task_id")
    if subj is not None:
        return subj
    return d.get("task")


def _p8_evidence_events_for(tid: str, *, EVENTS_PATH, P8_EVIDENCE_TYPES,
                            _event_dedup_key=None, _main_events_path=None, _event_task_id, _folded_journal_events) -> list:
    """Return the CHARTER §Principle 8 adoption-evidence events (consumer_read_evidence /
    live_trigger_evidence — AGENTS §Event-types) recorded for this task_id, in journal order.
    Read-only, tolerant of malformed lines. The single P8-event reader (T-0236): both the closure
    auto-detect (`_p8_evidence_event_exists`) and the audit-post prompt surface (`_build_audit_prompt`)
    derive from this — events.jsonl is excluded from the audit DIFF (T-0219), so the auditor cannot see
    these in the diff; this reader is how the prompt surfaces them WITHOUT re-including the noisy journal.

    T-10729 (SPEC-0168): the corpus is the CROSS-INSTANCE fold when the host injects the write-side
    dedupe key + main's journal path; the tie is the DUAL task-id carrier (rule 2). Both injections
    default to absent so an isolated / single-instance caller reads exactly the one journal it did
    before."""
    if _event_dedup_key is None:
        _event_dedup_key = lambda line: line          # noqa: E731 — byte identity: single instance
    p8 = set(P8_EVIDENCE_TYPES)
    # T-13330 — DECLARED, TASK-SCOPED (SPEC-0190 rule 4): the P8 rows of this task cannot predate its
    # id, so each instance contributes just the P8 types from the task horizon (`journal.task_floor`;
    # None outside a ReadScope = the whole instance, typed).
    return [ev for ev in _folded_journal_events(
                EVENTS_PATH=EVENTS_PATH, _event_dedup_key=_event_dedup_key,
                _main_events_path=_main_events_path,
                lines_of=lambda path: journal_mod.typed_lines(
                    path, tuple(sorted(p8)), since=journal_mod.task_floor(path, tid), lock=True))
            if ev.get("type") in p8 and _event_task_id(ev) == tid]


_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def p8_ref_horizon(refs, task_floor) -> tuple:
    """T-13330 — the journal slice the evidence refs of a P8 row ADDRESS: `(types, since)`, `since`
    None = the whole history. PURE (the reader's horizon declaration, SPEC-0190 rule 4).

    Each ref names the rows `_resolve_evidence_ref` can match, and the rows' own dates bound where they
    live (an archive segment holds the rows of exactly ONE UTC day — `events.segment_label`'s writer
    contract — and the live segment is always read):
      * `test:` — a FILE, no journal row;
      * bare `TYPE` — a row of TYPE carrying this task's id: the task horizon;
      * `TYPE@ts`, `exit:<verb>#seeded=<ts>&clean=<ts>` (cli_invoked), `nightly_run_completed@ts#surface=`,
        `land_completed@ts#branch=` / `#refused=` — rows PINNED by ts: that ts's day;
      * `land_completed@ts#gate=` — the pinned row's day AND the task's own ship land (task horizon);
      * `land_completed@ts#metric=` (condition iii, «some EARLIER land lacked the key») and
        `land_completed@ts#<layer>` (condition iv, «no EARLIER land ran the layer») ask a FIRST-EVER
        question over every earlier land row — no index answers it, so the WHOLE history (rare path
        R2, named in the rule-10 exemption); so does a pin whose ts carries no date.
    A ref the resolver refuses on its grammar alone reads nothing. The answer only ever WIDENS the
    corpus the resolvers saw toward what they could match; it never narrows a match away."""
    types: set = set()
    days: list = []
    whole = task_floor is None
    for ref in refs or ():
        if not isinstance(ref, str) or not ref.strip():
            continue
        ref = ref.strip()
        if ref.startswith(_IN_PROCESS_EVIDENCE_PREFIX):
            continue
        if ref.startswith(_EXIT_STATUS_EVIDENCE_PREFIX):
            _verb, sep, selector = ref[len(_EXIT_STATUS_EVIDENCE_PREFIX):].partition("#")
            seeded, amp, clean = selector.partition("&")
            if not sep or not amp:
                continue
            types.add(_CLI_INVOKED_EVIDENCE_TYPE)
            for part, prefix in ((seeded, _EXIT_SEEDED_SELECTOR_PREFIX), (clean, _EXIT_CLEAN_SELECTOR_PREFIX)):
                ts = part.strip()[len(prefix):].strip() if part.strip().startswith(prefix) else ""
                if _ISO_DAY.match(ts):
                    days.append(ts[:10])
                elif ts:
                    whole = True
            continue
        etype, _, rest = ref.partition("@")
        ts, sep, layer = rest.partition("#")
        etype, ts, layer = etype.strip(), ts.strip(), layer.strip()
        if not etype or (sep and (not layer or not ts)):
            continue
        types.add(etype)
        if not ts:
            continue                                   # bare TYPE: task-tied, the task horizon
        if not _ISO_DAY.match(ts):
            whole = True
            continue
        days.append(ts[:10])
        if sep and etype == _LAYER_ROW_EVIDENCE_TYPE and (
                layer.startswith(_METRIC_ROW_SELECTOR_PREFIX)
                or not layer.startswith((_ABORT_ROW_SELECTOR_PREFIX, _VERIFY_REFUSAL_SELECTOR_PREFIX,
                                         _GATE_ROW_SELECTOR_PREFIX))):
            whole = True                               # R2 — a first-ever question
    if whole:
        return frozenset(types), None
    return frozenset(types), min([task_floor] + days)


def _p8_evidence_event_exists(tid: str, *, _p8_evidence_events_for) -> bool:
    """True if events.jsonl carries an already-canonical CHARTER §Principle 8 adoption-evidence event
    (consumer_read_evidence либо live_trigger_evidence) for this task_id. One of the recognized P8
    carriers `task close` reads. Single reader — delegates to `_p8_evidence_events_for` (P5, T-0236).

    EXISTENCE only — it reads type + task_id, never the payload. Kept UNCHANGED (T-10282): the audit-post
    prompt surface + the AC-probe evidence readers want every P8 event of either FORM (T-0255 form-agnosticism);
    only the CLOSE-time adoption judgement tightened, via `_p8_substantive_evidence_exists` below."""
    return bool(_p8_evidence_events_for(tid))


def _resolve_layer_row_ref(layer: str, tid: str, ts: str, events: list) -> bool:
    """T-10485 (X-0339) — does the LAYER-ROW ref `land_completed@<ts>#<layer>` resolve?

    The land-emitted verify-layer ship class (SPEC-0015 §Land-emitted verify-layer ships): a task whose
    ship is a `verify.layers` wiring has NO mechanism event of its own — the layer's only trace is the
    `{layer, outcome}` row `land` writes onto `land_completed.data.consumer_verify_layers`. That is the
    SAME land_completed the blocklist above refuses as closure bookkeeping, so the class had no citable
    machine evidence at all: SPEC-0036 variant (d) sanctions the absence at Stage 8, Stage 9 refused it.

    A row on its own is NOT correlated to the citing task (audit-pre F-high): a consumer's every land
    carries a row per declared layer, so an ordinary task could cite a pre-existing `#default` row and
    read as adopted. Correlation is what makes this evidence rather than bookkeeping — all four hold:
      (i)   the exact (land_completed, ts) event exists;
      (ii)  it carries a row for `layer` with outcome `passed` — failed/timed-out/waived/malformed is
            not adoption;
      (iii) `data.branch == task/<tid>` — the SHIP'S OWN land. land_completed carries no task_id; the
            branch is the correlation it does carry, and it is what refuses ANOTHER task's land;
      (iv)  THIS SHIP is what put THIS command behind THIS layer name — proved EITHER way (T-10504):
              * NOVELTY — no EARLIER land ran that layer, so this land is the FIRST and the layer is
                new. X-0339's own evidence is this shape («the 2 lands before recorded 3 layers; this
                land is the first with the release-label-gate row»).
              * REWIRE — the layer already existed, and the ship's OWN row says `definition_changed`:
                land compared the layer's declared DEFINITION — its command and (T-13511) its declared
                bound, the layer's own `timeout:` else the section's `timeout_seconds:` — against the
                commit it integrated onto and recorded that THIS ship's diff changed it. A bound-only
                change is a rewire on the same terms as a command change (GitHub intake #13: a card
                whose whole deliverable was a `timeout:` had no resolvable ref); the reader is
                unchanged, since what counts as the definition is land's to decide, not this
                function's. Novelty alone was the pre-T-10504 test, and
                it fails BY CONSTRUCTION for a rewire — X-0368 (<project> T-0092: 6 prior rows for the
                layer, conditions (i)-(iii) all held, and real machine evidence was refused).
            The provenance is READ from the ship's own row, never INFERRED by diffing rows across
            lands: a gap in the row trail (a `--no-tests` land, an inert-retry skip, a waived outcome)
            would let a LATER unrelated task's land show the delta and inherit an earlier task's
            rewire (the T-10504 audit-pre pass-1 RED). Land knows the diff; the reader does not.
            FAIL-CLOSED: a missing / non-`True` `definition_changed` is UNKNOWN, never "changed" — so
            an ordinary task citing a pre-existing UNCHANGED layer row on its own land is refused (the
            anti-freeride bound), and every legacy row (none carry the field) refuses as it always did.
    Pure function of (layer, tid, ts, events) — no I/O."""
    own_branch = f"task/{tid}"
    hit = None
    layer_ran_before = False
    for ev in events:
        if ev.get("type") != "land_completed":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        rows = data.get("consumer_verify_layers")
        if not isinstance(rows, list):
            continue
        rows = [r for r in rows if isinstance(r, dict) and r.get("layer") == layer]
        if not rows:
            continue
        ev_ts = str(ev.get("ts") or "")
        if ev_ts < ts:
            layer_ran_before = True   # (iv) the layer is NOT new — only a recorded REWIRE can carry it now
            continue
        if ev_ts > ts:
            continue       # a LATER land re-running the layer is the mechanism WORKING, not a defect:
                           # once wired, every subsequent land runs it. Ignoring later lands is what
                           # keeps the ref resolvable at the post-land seam it is read at (audit-post
                           # F-high — the pinned land is otherwise un-cite-able the moment the next
                           # land runs, which in a live consumer is immediately).
        if data.get("branch") != own_branch:
            return False   # (iii) the row is on another task's land
        hit = rows
    if not hit:
        return False                                                    # (i)
    passed = [r for r in hit if r.get("outcome") == "passed"]           # (ii)
    if not passed:
        return False
    if not layer_ran_before:
        return True                                                     # (iv) NOVELTY — the layer is new
    # (iv) REWIRE — an earlier land ran this layer, so only the ship's OWN recorded provenance can prove
    # this ship is what changed what runs behind the name. `is True` — a truthy string or a missing key
    # buys nothing (fail-closed; the reader owns the missing-value judgement).
    return any(r.get("definition_changed") is True for r in passed)
# T-10937 — the SECOND correlated selector on the same blocklisted type, for the NEVER-LANDING ABORT
# ship class. Spelled `land_completed@<ts>#branch=<branch>` — the literal `branch=` prefix is what
# keeps it from shadowing (or being shadowed by) the T-10485 layer form, which addresses a bare layer
# name. `land_completed` is the only type honouring these selectors (four of them now — T-11005's
# `refused=` and T-11570's `metric=` joined this pair); every other type carrying one is still refused.
_ABORT_ROW_SELECTOR_PREFIX = "branch="
# T-11421 (<project> X-1087) — the abort classes that mean A LAND-TIME GATE DELIBERATELY REFUSED THIS
# BATCH'S SHAPE, admitted here IN ADDITION to `_LAND_NEVER_LANDING_ABORT_CLASSES` (see (iii) below).
# WHY A SECOND SET RATHER THAN A WIDER FIRST ONE: `_LAND_NEVER_LANDING_ABORT_CLASSES` is a ROUTING
# constant — it decides which abort row is written to MAIN's journal instead of dying with a discarded
# branch — so widening it for an EVIDENCE judgement would overload one constant with two unrelated
# jobs and change `land`'s behaviour as a side effect. The evidence question gets its own set, exactly
# as `_VERIFY_REFUSAL_ABORT_CLASSES` does two functions down (the F1 analog this reuses).
# DELIBERATELY NOT EVERY ABORT CLASS, and this is the fence: `work-batch-carrier-unreadable` is an
# ENVIRONMENT fault (the gate established that it COULD NOT TELL and refused fail-closed), so its row
# says nothing about a mechanism having fired; `uncommitted-dirt` / `on-main` / `detached-head` never
# reach a gate at all. Only a class whose row exists BECAUSE a gate READ a batch and REFUSED it.
_ABORT_ROW_EVIDENTIAL_CLASSES = frozenset({
    # T-11227's work-batch carrier gate (`lib.worktree`, the `work_batch_carrier_verdict` refuse leg):
    # a `work/<slug>` batch whose diff touches PRODUCT SOURCE with no card and no emergency marker.
    # Its entire observable output IS this row — the class X-1087 reported.
    "work-batch-uncarried-product-source",
    # T-13058's refusal arm of the same gate (`lib.worktree#_work_batch_unanswered_paths`): an
    # uncarried batch in a repo that has not answered `product_source:` touching a path its covers
    # recognised before T-11942. Same shape — the branch survives and the row IS the whole output.
    "work-batch-product-source-unanswered",
    # T-12786's wont-do unaudited-ship gate (`lib.worktree#_wont_do_unaudited_ship_refusal`): a
    # `task/T-NNNN` branch whose card is `status: wont-do` and whose diff carries authored content no
    # GREEN/YELLOW audit-post covers. Same shape as the row above — the branch is NOT discarded
    # (revert-the-ship or `worktree park` are the exits) and the gate's entire observable output IS
    # this row, so without membership here the mechanism's own live-trigger evidence (its card's AC4)
    # could not be cited (the X-1087 defect, one class over).
    "wont-do-unaudited-ship",
})


def _resolve_abort_row_ref(branch: str, ts: str, events: list) -> bool:
    """T-10937 (widened by T-11421) — does the ABORT-ROW ref
    `land_completed@<ts>#branch=<branch>` resolve?

    THE CLASS: a mechanism whose OUTPUT IS A LAND ABORT ROW. T-10795 routes a NEVER-LANDING abort
    (`_LAND_NEVER_LANDING_ABORT_CLASSES`, today `spike-branch`) to the MAIN journal, because the
    branch it aborted on is discarded and no next land exists to fold its row in. The mechanism's
    entire observable output is therefore a `land_completed{status:abort}` row — the same type the
    blocklist above refuses as closure bookkeeping, so the class had nothing citable and `task close`
    WARNed «no SUBSTANTIVE P8 artifact» at the very ship that produced the row. Same defect shape as
    X-0339, one class over.

    THE SECOND CLASS (T-11421, <project> X-1087): a mechanism whose OUTPUT IS A LAND-TIME REFUSAL that
    does NOT discard its branch. <project> T-0428 shipped a DECLARATION consumed by T-11227's
    work-batch carrier gate; when that gate fires, its entire observable output is again a
    `land_completed{status: abort}` row — `abort_class: work-batch-uncarried-product-source` on a
    `work/<slug>` branch. Identical defect shape to the never-landing class, one class over: a REAL
    adoption whose MECHANISM IS A REFUSAL was structurally unprovable under CHARTER §Principle 8,
    while the external audit-post read the same evidence and went GREEN — two readers disagreeing on
    one row. So (iii) below admits that class TOO, via its own evidence-side set. Nothing else moves:
    the spelling, the ref grammar, and conditions (i)/(ii)/(iv) are byte-unchanged.

    Correlation is again what makes it evidence rather than bookkeeping — all four must hold:
      (i)   the exact (land_completed, ts) event exists — the ref is PINNED, never match-any;
      (ii)  `data.status == "abort"` — an OK land is the closure row the blocklist exists to refuse;
      (iii) `data.abort_class` names a LAND-TIME GATE REFUSAL — a member of the NEVER-LANDING set
            (read from `lib.worktree`, the SAME constant that ROUTES the row to main in the first
            place — one SoT, CHARTER §P5; the import is function-local because worktree imports task
            and a module-level one would cycle) OR of `_ABORT_ROW_EVIDENTIAL_CLASSES` (T-11421 — the
            gates that refuse WITHOUT discarding the branch; the two sets are unioned, never merged,
            for the reason recorded on that constant). An untagged legacy abort has no class and
            refuses, fail-closed;
      (iv)  `data.branch` equals the branch NAMED IN THE REF — the correlation the row does carry
            (land_completed has no task_id), and a name no ordinary closure can earn: a never-landing
            class is reachable only on a branch the gate refused to land.

    THE BOUND HELD (card §BOUND / AC2, and T-11421 AC2 re-asserts it verbatim): an ordinary closure
    row is `status: ok` and carries no `abort_class`, so it fails (ii) AND (iii) — the bare type stays
    refused here and everywhere, and the carve-out admits only rows that exist BECAUSE a gated
    mechanism fired, never the bookkeeping every task earns for free by reaching Stage 7/9. If an
    ordinary row DID count, Principle 8 would be satisfiable by landing anything, which is the
    strongest closure gate the system has; that is why (iii) is an ENUMERATED membership test and
    never «has some abort_class» — an environment-fault abort (`work-batch-carrier-unreadable`) or a
    guard that never reached a gate is not a mechanism firing.

    UNCHANGED, deliberately: a bare `verify-failed` row is still refused by THIS selector (the
    recorded T-10937 test_b3 bound) — it carries no mechanism correlation, and the class whose ship IS
    the verify gate is served by the STRICTER `_resolve_verify_refusal_row_ref` below.

    Pure function of (branch, ts, events) apart from reading those two frozensets — no I/O."""
    from lib import worktree as _worktree   # function-local: worktree imports task (see (iii) above)
    evidential = _worktree._LAND_NEVER_LANDING_ABORT_CLASSES | _ABORT_ROW_EVIDENTIAL_CLASSES
    for ev in events:
        if ev.get("type") != "land_completed":
            continue
        if str(ev.get("ts") or "") != ts:                                   # (i)
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("status") != "abort":                                   # (ii)
            continue
        if data.get("abort_class") not in evidential:                       # (iii)
            continue
        if data.get("branch") != branch:                                    # (iv)
            continue
        return True
    return False
# T-11005 (X-0824, <project>) — the THIRD correlated selector on the same blocklisted type, for the
# VERIFY-REFUSAL ship class. Spelled `land_completed@<ts>#refused=<test-node>&branch=<branch>`; the
# literal `refused=` prefix is checked BEFORE `branch=` in `_resolve_evidence_ref`, so the three forms
# on this type never shadow one another.
_VERIFY_REFUSAL_SELECTOR_PREFIX = "refused="
# The abort classes that mean THE GATE REFUSED AN INTEGRATION (set at the `_die` origin in
# `lib.worktree`'s verify call-site). Deliberately NOT every abort class: an `uncommitted-dirt` /
# `on-main` / `detached-head` abort never ran the gate at all, so its row proves nothing about a
# mechanism — the same "admitted by correlation, never by type" line the two selectors above hold.
_VERIFY_REFUSAL_ABORT_CLASSES = frozenset({"verify-failed", "verify-timeout"})


def _resolve_verify_refusal_row_ref(node: str, branch: str, tid: str, ts: str, events: list) -> bool:
    """T-11005 — does the VERIFY-REFUSAL ref `land_completed@<ts>#refused=<node>&branch=<branch>` resolve?

    THE CLASS: a task whose shipped MECHANISM IS THE LAND-VERIFY GATE. Its mechanism running is the
    gate REFUSING an integration, and the only trace that refusal leaves is a
    `land_completed{status: abort}` row — the type the blocklist above refuses as closure bookkeeping.
    So the class had nothing citable and `task close` WARNed «no SUBSTANTIVE P8 artifact» at the very
    ship that produced the refusal (<project> T-0045 closed with E-0005 while carrying stronger
    live-trigger evidence than most infra closures). The consumer fallback does not fit either: no
    test can observe land aborting without invoking land. Same defect shape as X-0339 and X-0700, one
    class over.

    WHY THIS IS NOT A RE-OPENING OF THE T-10937 BOUND, and the whole design. Its sibling
    `_resolve_abort_row_ref` refuses a `verify-failed` row on purpose, and
    `tests/test_t10937_...::test_b3` pins that refusal with a recorded reason: such a row "folds into
    main at the next land like any other bookkeeping, and it says nothing about a mechanism". That
    guard is RIGHT for the row it was written against — a bare abort carrying no mechanism
    correlation — and it is left standing, unweakened. This selector admits a STRICTLY NARROWER
    shape: the row must NAME the test node that refused, and the ref must name it too. Status and
    branch ALONE would not have been enough — they would re-admit every task whose own land ever
    aborted on a failed verify, which is exactly the "ordinary closure bookkeeping becomes citable"
    outcome the blocklist exists to prevent (recorded as a deliberate divergence from this card's
    literally-written AC1/AC2; see the card and SPEC-0015).

    Correlation is again what makes it evidence rather than bookkeeping — all FIVE must hold:
      (i)   the exact (land_completed, ts) event exists — the ref is PINNED, never match-any;
      (ii)  `data.status == "abort"` — an OK land is the closure row the blocklist exists to refuse;
      (iii) `data.abort_class` is a VERIFY-REFUSAL class AND the row is not an `abort_preflight` one
            — the refusal came from the REAL verify run, not from a cheap pre-suite check that never
            ran the gate. An untagged legacy abort has no class and refuses, fail-closed;
      (iv)  `data.branch == branch == f"task/{tid}"` — the SHIP'S OWN land. STRICTER than the
            never-landing selector's (iv), which trusts the ref's branch alone: binding it to the
            CLOSING task's id is what refuses another task's refusal row outright, and this class
            (unlike a discarded spike branch) always lands on a `task/<tid>` branch, so nothing
            legitimate is excluded by asking;
      (v)   the row NAMES the node — `node` is an exact member of `data.failing_tests`, or a
            substring of one of `data.failing_assertions` (assertions are free text, test nodes are
            structured). This is the reporter's load-bearing distinction made machine-checkable: the
            row was written BECAUSE this named check refused an integration. A missing, empty or
            wrong-typed field is UNKNOWN, never a match — the reader owns the missing-value
            judgement (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`).

    THE BOUND HELD: an ordinary closure row is `status: ok`, carries no `abort_class` and no
    `failing_tests`, so it fails (ii), (iii) AND (v) — the bare type stays refused here and
    everywhere. RESIDUAL, stated rather than hidden: a task could still cite its OWN verify-failed
    land naming its OWN failing node without having shipped the gate. Closing that would mean reading
    the task's diff inside a function that is deliberately pure; the standing SPEC-0015 bound applies
    — `close` checks the claim is CHECKABLE, audit-post checks it is TRUE.

    Pure function of (node, branch, tid, ts, events) — no I/O."""
    own_branch = f"task/{tid}"
    for ev in events:
        if ev.get("type") != "land_completed":
            continue
        if str(ev.get("ts") or "") != ts:                                   # (i)
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("status") != "abort":                                   # (ii)
            continue
        if data.get("abort_class") not in _VERIFY_REFUSAL_ABORT_CLASSES:    # (iii)
            continue
        if data.get("abort_preflight") is True:                             # (iii) — never ran the gate
            continue
        if data.get("branch") != branch or branch != own_branch:            # (iv)
            continue
        tests = data.get("failing_tests")                                   # (v)
        if isinstance(tests, list) and any(isinstance(t, str) and t == node for t in tests):
            return True
        assertions = data.get("failing_assertions")
        if isinstance(assertions, list) and any(isinstance(a, str) and node in a for a in assertions):
            return True
    return False
# T-11570 (T-11530 / T-11460) — the FOURTH correlated selector on the same blocklisted type, for the
# PAYLOAD-KEY READING ship class. Spelled `land_completed@<ts>#metric=<key>`; the literal `metric=`
# prefix keeps it from shadowing (or being shadowed by) the three forms above, none of which can
# collide with it — `refused=`/`branch=` are distinct literals, and a bare layer name containing `=`
# was never addressable.
_METRIC_ROW_SELECTOR_PREFIX = "metric="


def _resolve_metric_row_ref(key: str, ts: str, events: list) -> bool:
    """T-11570 — does the METRIC-ROW ref `land_completed@<ts>#metric=<key>` resolve?

    THE CLASS: a card whose acceptance is a SPEC-0036 variant-(e) POST-SHIP READING of a payload key
    the land runner writes onto `land_completed.data.verify_metrics`. The shipping card cannot carry
    the reading at its own closure — `land` runs from the MAIN checkout, so its candidate verify is
    executed by main's PRE-change runner and the key first appears on a LATER, unrelated land — so the
    proof is an ordinary `status: ok` land row on ANOTHER branch, which is exactly the closure
    bookkeeping the blocklist above refuses. The class therefore had NOTHING citable: measured on
    T-11460, whose truthful refs are pinned by ts, are honest, and demonstrably do not resolve (a bare
    `land_completed@<ts>` carries no selector, so it falls through to the blocklist check). Same defect
    shape as X-0339 / X-0700 / X-0824, one class over.

    WHY THE THREE SELECTORS ABOVE CANNOT SERVE IT, read rather than assumed. `_resolve_layer_row_ref`
    demands `data.branch == task/<tid>` and a `consumer_verify_layers` row; `_resolve_verify_refusal_row_ref`
    demands `branch == f"task/{tid}"` plus `status: abort` plus a named failing node;
    `_resolve_abort_row_ref` trusts the ref's own branch but demands `status: abort` plus an ENUMERATED
    `abort_class`. So two of the three require the CITING task's OWN branch and all three require an
    ABORT row. This class has neither, by construction: its rows are ordinary successful lands belonging
    to other tasks entirely.

    CORRELATION is again what makes this evidence rather than bookkeeping — all THREE must hold:
      (i)   the exact (land_completed, ts) event exists — the ref is PINNED, never match-any. A
            fabricated ts resolves nothing;
      (ii)  `data.verify_metrics` is a dict CARRYING `key` with a non-None value. A real row whose
            metrics lack the named key refuses — the reading is about THIS key, not about the row;
      (iii) ANTI-FREERIDE — the key HAD A BEGINNING: some EARLIER `land_completed` row (strictly
            before the pinned ts) carries a `verify_metrics` dict that does NOT carry `key`. This is
            the condition that keeps the carve-out from re-opening the blocklist, and it is not
            decoration: without it, any task could cite `#metric=verify_wall_ms` — a key every land
            has always carried — and buy free P8 evidence, which is precisely the door
            `_NON_EVIDENTIAL_EVIDENCE_TYPES` exists to keep shut. It is also the MACHINE FORM of the
            differential this class writes in prose anyway: T-11530's own payload names its failing
            input as "a row whose verify_metrics carries `selection_full_suite_reason` but NO
            `selection_full_suite_globs`" — i.e. exactly what every land before T-11460 recorded.
            NOT a novelty test on the PINNED row (the layer-row selector's shape): the reading is
            legitimately taken from ANY qualifying row, not only the first one after the ship, so
            asking the pinned row to be the earliest would refuse 13 of T-11460's 14 real rows.

    THE BOUND HELD: an ordinary closure row proves nothing HERE either, because (ii)+(iii) are about
    the KEY, not the row — a key present on every land in history fails (iii) whatever row is pinned,
    and a row lacking the key fails (ii) however real it is. So the bare type stays refused here and
    everywhere, and this admits only a row that carries a payload some earlier land demonstrably did
    not. Every missing / wrong-typed field is UNKNOWN, never a match — the reader owns the
    missing-value judgement (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`).

    RESIDUAL, stated rather than hidden and identical in kind to the sibling selectors': a task could
    cite a key some OTHER task shipped. Closing that would mean reading the citing task's diff inside
    a function that is deliberately pure, and the standing SPEC-0015 bound applies — `close` checks
    the claim is CHECKABLE, audit-post checks it is TRUE. It is also NARROWER than it sounds for this
    class specifically: the class exists precisely so a card can record ANOTHER card's post-ship
    reading (T-11530 recording T-11460's), so cross-task citation is the sanctioned use, not the leak.

    Pure function of (key, ts, events) — no I/O and no cross-module import."""
    pinned = False
    key_had_a_beginning = False
    for ev in events:
        if ev.get("type") != "land_completed":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        metrics = data.get("verify_metrics")
        if not isinstance(metrics, dict):
            continue                                                    # UNKNOWN, never a match
        ev_ts = str(ev.get("ts") or "")
        if ev_ts == ts:
            if metrics.get(key) is not None:                            # (i) + (ii)
                pinned = True
            continue
        if ev_ts < ts and key not in metrics:                           # (iii)
            key_had_a_beginning = True
    return pinned and key_had_a_beginning
# T-12106 (fu_232faef9222b / T-12069) — the FIFTH correlated selector on the same blocklisted type,
# for the KERNEL-SIDE GATE ship class. Spelled `land_completed@<ts>#gate=<test-file-basename>`; the
# literal `gate=` prefix cannot collide with `refused=` / `branch=` / `metric=`, and a bare layer name
# containing `=` was never addressable.
#
# THE CLASS: a card whose ship IS a land-verify GATE — a check that runs inside the pinned suite at
# every kernel land and, on PASS, JOURNALS NOTHING. Its consumer is the NEXT kernel land. Measured on
# T-12069 (the SPEC-0161 payload-key gate): form (3) wants a `consumer_verify_layers` layer row kernel
# lands do not carry (0 rows in the whole journal), forms (4)/(5) demand an ABORT, form (6) addresses
# `verify_metrics` KEYS and a passing gate writes none, and a bare `land_completed` is blocklisted. So
# the class had NOTHING citable while its adoption was, in fact, proven at every green land.
#
# WHAT MAKES IT EVIDENCE RATHER THAN BOOKKEEPING — and why NO new payload was added to `land`. A green
# kernel land ALREADY records, in data it writes today, that it ran a named test FILE and that the run
# passed. So this selector is a READER over existing rows, not a new emit: no change to `land`,
# `verify_runner` or `worktree`, no new key, no new event class, no new store. That is what makes it
# preferable to having `land` write a per-gate outcome row, which would have grown EVERY land's
# payload forever and needed a gate->key registry to serve one class.
#
# All FIVE conditions must hold:
#   (i)   the exact (land_completed, ts) event exists — the ref is PINNED, never match-any;
#   (ii)  `data.status` is `ok` — the verify PASSED, so every gate it ran passed. An `abort` row
#         proves the OPPOSITE, and an absent/unknown status is UNKNOWN, never a match;
#   (iii) the row is a FULL, FAIL-CLOSED RUN OF THE SUITE DISCOVERABLE AT ITS OWN REVISION —
#         `_gate_row_full_run_reason` below: a `verify_mode` saying the verify actually ran and was
#         not the policy-off leg, NO `verify_metrics.selection_ran_tests` (the marker a NARROWED run
#         writes — it refuses INDEPENDENTLY of the counts, because count equality is an agreement of
#         numbers while the marker is the row's own statement that it selected), AND
#         `verify_metrics.test_file_count` EQUAL to the number of
#         `tests/test_*.py` files `git ls-tree <sha> tests/` finds at that row's landed revision.
#         This is the MEMBERSHIP condition, and the reason the earlier `ran >= discovered_count`
#         reading was not enough: those two payload counts prove every DISCOVERED file ran, but they
#         name none of them, so an existing-but-undiscovered file could resolve against counts that
#         never spoke of it (the post-ceiling consult's held residual). Discoverable-at-revision ==
#         ran ⇒ every discoverable file ran ⇒ a file discoverable at that revision BELONGED to the
#         suite that land enumerated. A SELECTED or partial run fails the equality and is therefore
#         not evidence for this form at all — green full-enumeration lands are the ordinary case, so
#         the class loses no reachable evidence;
#   (iv)  ANTI-SELF-CITE — `data.branch` is a NON-EMPTY STRING that is NOT the citing task's own
#         `task/<tid>`. Read POSITIVELY, never as an inequality against a coerced default: a row with
#         a MISSING, empty or non-string `branch` coerced to `""`, which is trivially != the own
#         branch, so a row that cannot say where it ran resolved as though it had said "elsewhere"
#         (round-4 consult, finding 1). An unanswerable row is not a foreign row. A gate's adoption
#         is proven by a land OTHER than the one that shipped it: this is what makes the row a REAL
#         POST-SHIP reading rather than the citing card's own verify, and it is the same
#         "ordinary status: ok lands on OTHER branches" reading `_resolve_metric_row_ref` relies on;
#   (v)   the named file matches the RUNNER'S OWN DISCOVERY RULE — `_GATE_DISCOVERY_GLOB_RE`, the flat
#         `tests/test_*.py` glob `verify_runner.py#_run_verify_tests` itself discovers with, NOT the
#         wider `_TEST_SURFACE_RE` the other forms use (which accepts any file at any depth beneath
#         `tests/`, so an UNDISCOVERABLE file passed its shape check) — AND it
#         EXISTED AT THE CITED ROW'S OWN LANDED REVISION (`data.sha`), read with
#         `git cat-file -e <sha>:<path>` under the injected repo root. Shape alone was not enough: a
#         full enumeration's row lists no filenames, so without an existence check any test-LOOKING
#         string resolved (audit-post pass 1, high). CURRENT-checkout existence was not enough
#         either: a file created AFTER the cited land made that older row resolve retrospectively,
#         when what the form claims is that the file was in THAT land's enumeration (audit-post
#         pass 2 / the held consult, high). The question is therefore asked AS OF the row — the same
#         class of read as before, made at the row's revision instead of now. With no injected root,
#         no `sha`, or an unresolvable sha/path the arm is DARK, never permissive;
#   (vi)  the row POST-DATES the citing task's own ship — `_own_ship_land_ts`, the latest successful
#         land of `task/<tid>`. Foreign-branch alone admitted a green land that PREDATED the card
#         entirely, which cannot be a reading of a gate not yet shipped (audit-post pass 1, high). A
#         task with no landed ship resolves nothing.
# Fail-closed on every unknown, the standing reading
# (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`): the reader owns the missing-value
# judgement, so a malformed or unanswerable row is never a match.
#
# HONEST BOUND, stated so no reader over-reads it: this proves the gate FILE was in the suite that
# land enumerated and that the verify PASSED. It does not, and cannot, single out one assertion inside that file — the standing SPEC-0015
# division is unchanged (close checks the claim is CHECKABLE, audit-post checks it is TRUE).
_GATE_ROW_SELECTOR_PREFIX = "gate="
# T-12106 — the RUNNER'S OWN discovery rule, and the marker of a run that was not fail-closed.
# `verify_runner.py#_run_verify_tests` discovers with the FLAT glob `test_dir.glob("test_*.py")`, so
# a gate ref may name ONLY a path that glob would find: `tests/<one segment>` matching `test_*.py`.
# The wider `_TEST_SURFACE_RE` (which accepts ANY file beneath `tests/`, at any depth) stays the
# shape check for the OTHER forms — for form (10) it was too wide, because an existing but
# UNDISCOVERABLE file (e.g. `tests/helpers/x.py`) would have satisfied a shape check while the
# run-vs-discovered counts said nothing about it (the post-ceiling consult's residual).
_GATE_DISCOVERY_GLOB_RE = re.compile(r"^tests/test_[^/]*\.py$")
# The `verify_mode` value recording a candidate leg SKIPPED by policy (`debt.py#_POLICY_OFF_VERIFY_MODE`,
# SPEC-0186 rule 7) — a run that is not fail-closed, so its counts cannot carry a membership claim.
_GATE_POLICY_OFF_VERIFY_MODE = "candidate_policy_off"
# T-12106 — the SPEC-0181 NARROWED-RUN MARKER. `verify_runner.py#_run_verify_tests` writes
# `verify_metrics.selection_ran_tests` under EXACTLY ONE condition — `0 < len(test_files) <
# _selection_discovered`, i.e. the run was NARROWED — and never on a full-suite or unmeasurable run
# (the key is ABSENT there, never an empty list). Its PRESENCE is therefore the row's own statement
# that it did not run the whole discovered suite, and it is checked INDEPENDENTLY of the counts: a
# row may carry the marker AND a `test_file_count` that happens to equal the revision's discoverable
# count (the post-ceiling consult's named failing input — a two-file sandbox row with
# `test_file_count: 2` and `selection_ran_tests` naming two files). Equality between those two
# numbers is a COUNT agreement, not a proof the run was unselected; the marker is the stated proof
# of the opposite, so it WINS over the arithmetic. Fail-closed on PRESENCE, never on truthiness: the
# key is ABSENT on a full or unmeasurable run, so its mere presence — whatever its value, including
# an empty list or a null the writer never produces — is the row saying it selected. Reading it with
# a truthiness test let `selection_ran_tests: []` through (round-4 consult, finding 2): a falsey
# marker is malformed evidence, and malformed evidence fails closed rather than resolving.
_GATE_NARROWED_RUN_MARKER = "selection_ran_tests"


def _gate_row_discoverable_count_at_rev(root: "Path", sha: str) -> "int | None":
    """T-12106 — how many test files the RUNNER'S OWN discovery would have found at revision `sha`?

    The membership half of condition (iii). `verify_runner.py#_run_verify_tests` discovers with the
    FLAT glob `test_dir.glob("test_*.py")`, so the discoverable set at a revision is exactly the
    direct children of `tests/` matching `tests/test_*.py`. `git ls-tree --name-only <sha> tests/`
    lists precisely those direct children (no `-r`, so a subdirectory appears as ONE tree entry and
    its contents — which the runner would not discover either — are never counted). Read-only: it
    touches no working tree and moves no ref.

    Returns None — never 0 — for every unanswerable case (no root, no sha, an unresolvable sha, a
    non-repo root): the caller must fail closed on an unknown, and a 0 would otherwise read as a
    real "nothing was discoverable"."""
    import subprocess
    if not sha:
        return None
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-tree", "--name-only", sha, "tests/"],
                           capture_output=True, text=True)
    except (OSError, ValueError):
        return None
    if r.returncode != 0:
        return None
    return sum(1 for line in r.stdout.splitlines()
               if _GATE_DISCOVERY_GLOB_RE.match(line.strip()))


def _gate_row_full_run_reason(data, discoverable: "int | None") -> "str | None":
    """T-12106 — why is this row NOT a FULL, fail-closed run of the discovered suite? None iff it is.

    Condition (iii), rewritten at the post-ceiling consult's direction. The prior reading
    (`test_file_count >= selection_discovered_count`, both counts from the row's own payload) proved
    that every DISCOVERED file ran, but it never tied the ref's named file to that discovered SET —
    the residual the consult named: an existing-but-undiscovered file could resolve against counts
    that spoke only of files nobody named. The equality below closes it with data the row ALREADY
    records: the number of files the run RAN (`verify_metrics.test_file_count`) equals the number of
    files the RUNNER'S OWN glob would have discovered at that row's landed revision
    (`_gate_row_discoverable_count_at_rev`). Discoverable-at-revision == ran ⇒ EVERY discoverable file
    ran ⇒ a file that is discoverable at that revision BELONGED to the suite that land enumerated.
    That is the membership claim the form makes, and now the only one it can make.

    The count equality is NOT the whole condition, and the reason is the consult's: equality between
    `test_file_count` and the revision's discoverable count is an agreement of two NUMBERS, and does
    not by itself prove the run was UNSELECTED. The row already carries the stated marker of a
    narrowed run — `verify_metrics.selection_ran_tests`, written by `verify_runner.py` under exactly
    the narrowed condition — so a row carrying it is REFUSED regardless of the counts
    (`_GATE_NARROWED_RUN_MARKER`). The marker is the row's own statement about what it ran; the
    arithmetic is an inference about it, and the statement wins.

    `verify_mode` is required alongside: it is the payload key present IFF the verify actually RAN
    (`debt.py#ABORT_PAID_VERIFY_MARKER`), and `candidate_policy_off` records a candidate leg SKIPPED
    by policy (`debt.py#_POLICY_OFF_VERIFY_MODE` / SPEC-0186 rule 7) — a run that is not fail-closed,
    so its counts cannot carry this weight.

    Fail-closed on every unknown, and BOTH counts are bool-guarded: in Python `True` IS an `int`, so
    a corrupt `test_file_count: true` would otherwise compare as 1."""
    if not isinstance(data, dict):
        return "the pinned row carries no `data` object"
    mode = data.get("verify_mode")
    if not isinstance(mode, str) or not mode.strip():
        return ("the pinned row records no `verify_mode`, so it is not provably a run that "
                "actually verified")
    if mode.strip() == _GATE_POLICY_OFF_VERIFY_MODE:
        return (f"the pinned row's `verify_mode` is `{_GATE_POLICY_OFF_VERIFY_MODE}` — the candidate "
                "leg was skipped by policy, so the run is not fail-closed")
    vm = data.get("verify_metrics")
    if not isinstance(vm, dict):
        return "the pinned row carries no `verify_metrics`, so it cannot answer what it ran"
    if _GATE_NARROWED_RUN_MARKER in vm:
        return (f"the pinned row carries `verify_metrics.{_GATE_NARROWED_RUN_MARKER}`, the marker a "
                "NARROWED run writes — so the run was selected, whatever its counts say")
    ran = vm.get("test_file_count")
    if isinstance(ran, bool) or not isinstance(ran, int):
        return "the pinned row carries no integer `verify_metrics.test_file_count`"
    if discoverable is None:
        return ("the number of discoverable `tests/test_*.py` files at the pinned row's landed "
                "revision could not be read")
    if discoverable <= 0:
        return "the pinned row's landed revision carries no discoverable `tests/test_*.py` files"
    if ran != discoverable:
        return (f"the pinned row ran {ran} test files but {discoverable} were discoverable at its "
                "landed revision — a SELECTED or partial run, which proves nothing about whether "
                "the named file was in the suite it enumerated")
    return None


def _own_ship_land_ts(tid: str, events: list) -> "str | None":
    """T-12106 — the citing task's OWN ship boundary: the LATEST successful land of `task/<tid>`.

    The machine-resolved instant a gate ref must be LATER than to be a POST-ship reading. Returns
    None when the corpus carries no such row — the citing task has not landed, so NOTHING can yet be
    a reading of its ship, and the caller fails closed. Latest (not earliest) is the honest pick: a
    card may land more than once (a re-land, a post-close rebaseline), and the gate it shipped is only
    certainly present after the LAST of them."""
    best = None
    for ev in events:
        if ev.get("type") != _LAYER_ROW_EVIDENCE_TYPE:
            continue
        data = ev.get("data")
        if not isinstance(data, dict) or data.get("status") != "ok":
            continue
        if str(data.get("branch") or "") != f"task/{tid}":
            continue
        row_ts = str(ev.get("ts") or "")
        if row_ts and (best is None or row_ts > best):
            best = row_ts
    return best


def _path_existed_at_rev(root: "Path", sha: str, rel: str) -> bool:
    """T-12106 — did `rel` exist in the tree of revision `sha`? Fail-closed on every unknown.

    The as-of-row half of condition (v). `git cat-file -e <sha>:<rel>` is the cheapest read that
    answers exactly this and nothing else: it touches no working tree, moves no ref, and exits
    non-zero for an unknown sha, an unknown path, or a non-repo root alike — all of which are the
    same answer here, NOT AN ERROR TO SURFACE: the ref simply does not resolve. Kept a read-only
    subprocess rather than an injected collaborator so this resolver stays callable from every
    surface that already reaches it with only `REPO_ROOT` (`task close`, the E-0005 cue, the
    SPEC-0119 rule-31 fold) — the same reason the sibling existence check reads the filesystem
    directly."""
    import subprocess
    if not sha or not rel:
        return False
    try:
        r = subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{sha}:{rel}"],
                           capture_output=True, text=True)
    except (OSError, ValueError):
        return False
    return r.returncode == 0


def _resolve_gate_row_ref(test_file: str, tid: str, ts: str, events: list, *, REPO_ROOT=None,
                          reason_out=None, _gate_row_discoverable_count_at_rev, _gate_row_full_run_reason, _own_ship_land_ts, _path_existed_at_rev) -> bool:
    """T-12106 — does the GATE-ROW ref `land_completed@<ts>#gate=<test-file>` resolve?

    The conditions are stated in the block above, in the order checked. The three that make this a
    MEMBERSHIP claim rather than a co-existence one were each added by an audit pass that showed how
    the form could otherwise be satisfied by something that is not a reading of this ship:

      (v) THE PATH MATCHES THE RUNNER'S OWN DISCOVERY RULE, and the file EXISTED AS OF THE CITED ROW.
          Without any existence check a syntactically test-like string that names no file at all
          satisfied the form (audit-post pass 1). Checking the CURRENT checkout closed that but left
          retrospective resolution — a file created AFTER the cited land made an older row resolve
          (audit-post pass 2). And a mere test-SURFACE shape (`_TEST_SURFACE_RE`, which accepts any
          file at any depth beneath `tests/`) left the last hole the post-ceiling consult named: an
          existing but UNDISCOVERABLE file could resolve. So the path must match
          `_GATE_DISCOVERY_GLOB_RE` — the flat `tests/test_*.py` glob `verify_runner.py` itself
          discovers with — and must exist at the row's own landed `sha`.

      (iii) THE ROW IS A FULL, FAIL-CLOSED RUN, read as an EQUALITY against the revision it landed:
          `verify_metrics.test_file_count` equals the number of discoverable `tests/test_*.py` files
          at that `sha`, with a `verify_mode` that says the verify actually ran and was not the
          policy-off leg (`_gate_row_full_run_reason`). Discoverable-at-revision == ran ⇒ every
          discoverable file ran ⇒ a file discoverable at that revision was IN the suite that land
          enumerated. This is what upgrades "the file existed then" to "the file belonged to that
          enumeration" — the residual the post-ceiling consult held the form on.

      (iv) FOREIGN IS A POSITIVE READING. The check asks the row to SAY it ran elsewhere: a missing,
          empty or non-string `branch` coerced to `""` compared unequal to `task/<tid>` and so passed
          as foreign, letting a row that cannot answer the question resolve (round-4 consult, high).
          Fail-closed: silence is not "elsewhere".

      (vi) POST-SHIP, not merely FOREIGN. The anti-self-cite check alone admitted a green foreign-
          branch land that PREDATED the citing task entirely — a row that cannot be evidence of a
          gate the card had not yet shipped. The row must post-date the citing task's own ship
          boundary (`_own_ship_land_ts`), and a task with no landed ship resolves nothing.

    Pure function of its arguments apart from two read-only git queries against the row's own
    revision (does the path exist there; how many files were discoverable there).

    `reason_out`, when a list is passed, receives the FIRST unmet condition's reason — read by the
    E-0005 diagnostic so an author is told WHICH condition failed rather than "no ref resolves".
    It never moves the verdict."""
    def _no(reason):
        if reason_out is not None and not reason_out:
            reason_out.append(reason)
        return False

    if not test_file or not ts:
        return _no("the ref names no gate file or no timestamp")
    if os.path.isabs(test_file) or not _GATE_DISCOVERY_GLOB_RE.match(test_file):   # (v) shape
        return _no(f"`{test_file}` is not a path the verify runner would discover — a gate ref names "
                   "a file matching the runner's own flat glob `tests/test_*.py`")
    if REPO_ROOT is None:
        return _no("no repo root is available, so the as-of-revision questions cannot be answered")
    try:
        root = Path(REPO_ROOT).resolve()
    except (OSError, ValueError):
        return _no("the injected repo root could not be resolved")
    ship_ts = _own_ship_land_ts(tid, events)                            # (vi) boundary
    if ship_ts is None:
        return _no("this task has no successful land of its own, so nothing can yet be a POST-ship "
                   "reading of its gate")
    own_branch = f"task/{tid}"
    seen = False
    for ev in events:
        if ev.get("type") != _LAYER_ROW_EVIDENCE_TYPE:
            continue
        if str(ev.get("ts") or "") != ts:                               # (i)
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        seen = True
        if data.get("status") != "ok":                                  # (ii)
            _no("the pinned `land_completed` row did not succeed, so it proves the opposite")
            continue
        branch = data.get("branch")                                     # (iv)
        if not isinstance(branch, str) or not branch.strip():
            _no("the pinned row records no usable `branch`, so it cannot be shown to be a land "
                "OTHER than the one that shipped the gate")
            continue
        if branch.strip() == own_branch:
            _no("the pinned row ran on the citing task's OWN branch — a gate's adoption is proven "
                "by a land other than the one that shipped it")
            continue
        if ts <= ship_ts:                                               # (vi)
            _no("the pinned row PREDATES the citing task's own ship, so it cannot be a reading of "
                "a gate that had not landed yet")
            continue
        # (v)+(iii) THE AS-OF-ROW READS, checked last because they are the only conditions that cost
        # a subprocess, and they are per-ROW: both answers are properties of the row's own landed
        # revision, not of the checkout the reader happens to be standing in.
        sha = str(data.get("sha") or "")
        if not sha:
            _no("the pinned row carries no `sha`, so neither the file's existence nor the "
                "discoverable count can be asked at its own revision")
            continue
        if not _path_existed_at_rev(root, sha, test_file):
            _no(f"`{test_file}` did not exist at the pinned row's landed revision (or that revision "
                "is unresolvable here), so it cannot have been in that land's enumeration")
            continue
        why = _gate_row_full_run_reason(data, _gate_row_discoverable_count_at_rev(root, sha))
        if why:
            _no(why)
            continue
        return True
    if not seen:
        _no(f"no `land_completed` row is pinned at {ts}")
    return False


def _gate_ref_diagnosis(ref: str, tid: str, events: list, *, REPO_ROOT=None, _resolve_gate_row_ref) -> "str | None":
    """T-12106 — for a form-(10) ref that did NOT resolve, WHICH condition failed?

    Read ONLY by the E-0005 no-ref-resolves diagnostic, and only on the already-failing path, so a
    clean payload pays nothing. It re-runs the SAME resolver with its reason channel open rather
    than re-deciding anything — a parallel judgement is exactly what would let the two drift
    (CHARTER §P5 / §P1 F1). Returns None for a ref that is not this form, or that resolves."""
    if not isinstance(ref, str):
        return None
    etype, at, rest = ref.strip().partition("@")
    if not at or etype != _LAYER_ROW_EVIDENCE_TYPE:
        return None
    row_ts, hashmark, layer = rest.partition("#")
    if not hashmark or not layer.startswith(_GATE_ROW_SELECTOR_PREFIX):
        return None
    reasons = []
    _resolve_gate_row_ref(layer[len(_GATE_ROW_SELECTOR_PREFIX):].strip(), tid, row_ts.strip(),
                          events, REPO_ROOT=REPO_ROOT, reason_out=reasons)
    return reasons[0] if reasons else None
# T-10914 (X-0730, <project>) — the IN-PROCESS mechanism observation ref, the CONSUMER-only
# machine-evidence spelling. Every spelling below `_resolve_evidence_ref` resolves against a JOURNAL
# row, which silently assumes the audited MECHANISM emits journal lines. That is true of the KERNEL's
# own mechanisms and false of PRODUCT code: a consumer boundary such as <project>'s
# `backend/app/outbox.py` emits its `outbound_blocked` event IN-PROCESS to a listener, observed by
# pytest — it never becomes a journal row. So the contract was unsatisfiable BY CONSTRUCTION for a
# consumer product task: T-0016 emitted a substantive `live_trigger_evidence` (a concrete blocked
# recipient, zero transport calls, a named differential failing input), audit-post read it GREEN, and
# `task close` still WARNed E-0005 — the consumer's own words for its only remaining path were
# "without fabricating a journal ref". That is the OVER-CUT signature
# (`lessons/kernel-consumer-boundary-evidence.md`): a consumer whose only path to GREEN is fabricating
# kernel-shaped structure onto its product artifacts. The fix is the T-10541 (X-0408/X-0409) shape —
# the `_is_consumer_build()` branch a kernel-realm assertion was missing.
# THE FORM WIDENS, THE REQUIREMENT DOES NOT. The honest machine artifact a product boundary produces
# is the executable TEST NODE that OBSERVED its in-process emission, so that is what a ref may name:
#   `test:<repo-relative test path>::<node>`
# It resolves iff the path is a TEST SURFACE that EXISTS under the repo root AND its text contains the
# named node (audit-pre: scoped to test surfaces, so an arbitrary repo file carrying the node text
# cannot satisfy the shape). `failing_input` stays MANDATORY — this buys no escape from the
# differential, only from the journal-row assumption.
# NOT a `tests_passed` re-admission. That blocklisted row is an AGGREGATE "the suite was green"
# bookkeeping line, bound to no mechanism and earned by every task alike — CHARTER §P8's "tests green
# BY ITSELF is not adoption". This names ONE node asserting the mechanism's OWN emission, and it is
# admitted only alongside the named differential. The HONEST BOUND is the standing one (SPEC-0015):
# close checks the claim is CHECKABLE, audit-post checks it is TRUE.
_IN_PROCESS_EVIDENCE_PREFIX = "test:"
# A test SURFACE, spelled to cover the shapes a consumer actually uses (pytest / go / jest-style),
# never a general repo path: a `tests/` (or `test/`) path segment, OR a `test_*` / `*_test` /
# `*.test.*` / `*.spec.*` basename.
_TEST_SURFACE_RE = re.compile(r"(?:^|/)tests?/|(?:^|/)test_[^/]*$|_test\.[^/.]+$|\.(?:test|spec)\.[^/.]+$")
# T-12106 — the KERNEL arm's RED-CONTRAST selector: `test:<path>::<node>&contrast=<node>`.
# On a CONSUMER the arm is unchanged and this selector is OPTIONAL (checked only when present). On
# the KERNEL it is REQUIRED, and it is the whole reason the arm may be admitted there at all — see
# the `_resolve_evidence_ref` form-(9) branch for why the realm gate moved and what the bound buys.
_IN_PROCESS_CONTRAST_SELECTOR_PREFIX = "&contrast="


def _test_node_is_defined(text: str, node: str) -> bool:
    """T-12106 — is `node` DEFINED in this test surface, rather than merely MENTIONED in it?

    A bare substring test is what the kernel arm cannot rest on: a comment, a docstring, a call site
    or an unrelated identifier all satisfy it, so ordinary static text would pass for a differential
    (audit-pre pass 1 finding 2, high). A DEFINITION is the smallest thing that is statically decidable
    and is not free — matched anchored at line start, allowing the leading indentation a nested
    definition carries, so `def <node>(` counts and `# see test_foo(...)` or `test_foo()` do not.

    HONEST BOUND, stated here and in the grammar and in SPEC-0015 so no reader over-reads it: this
    proves the node EXISTS as a definition in a real test surface. It does NOT prove the node RAN, and
    it cannot prove the contrast produced the opposite outcome — a resolver that does not execute the
    suite cannot decide that, and a check claiming otherwise would be exactly the prose-asserting-its-
    own-precision this contract rejects in the payloads it judges. The standing SPEC-0015 division is
    unmoved: close checks the claim is CHECKABLE, audit-post checks it is TRUE. Adjudicated at the
    SPEC-0191 §5 rung-2 on-demand consult for T-12106, which converged GREEN on exactly this bound."""
    return re.search(rf"^[ \t]*def[ \t]+{re.escape(node)}[ \t]*\(", text, re.MULTILINE) is not None


def _resolve_in_process_evidence_ref(ref: str, *, REPO_ROOT, require_contrast: bool = False, _test_node_is_defined) -> bool:
    """T-10914 — does an IN-PROCESS `test:<path>::<node>[&contrast=<node>]` ref resolve?

    Fail-closed on EVERY missing half — an empty path, an empty node, a path that is not a test
    surface, an absent/unreadable file, or a file in which the node is not DEFINED all return False
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`: the reader owns the missing-value
    judgement, so a malformed ref is never a match-any). The path is resolved STRICTLY inside
    REPO_ROOT — a `..` escape or an absolute path names something this repo does not ship and
    resolves nothing.

    T-12106 — `require_contrast` is the KERNEL arm's bound (False for a consumer, so every consumer
    judgement is byte-identical to before this card). When a `&contrast=` selector is present it is
    CHECKED in either realm rather than swallowed into the node name; when `require_contrast` is set
    and it is ABSENT, or names the SAME node as the assertion, the ref does not resolve. Both nodes
    must be real DEFINITIONS in the one named surface (`_test_node_is_defined`)."""
    body = ref[len(_IN_PROCESS_EVIDENCE_PREFIX):]
    path, sep, node = body.partition("::")
    node, amp, contrast = node.partition(_IN_PROCESS_CONTRAST_SELECTOR_PREFIX)
    path, node, contrast = path.strip(), node.strip(), contrast.strip()
    if not sep or not path or not node:
        return False
    if amp and not contrast:
        return False                          # a spelled-but-empty selector is MALFORMED, not absent
    if require_contrast and (not contrast or contrast == node):
        return False
    if contrast == node:
        return False                          # one node cannot be both halves of a differential
    if os.path.isabs(path) or not _TEST_SURFACE_RE.search(path):
        return False
    try:
        root = Path(REPO_ROOT).resolve()
        target = (root / path).resolve()
        if target != root and root not in target.parents:
            return False                      # `..` escape — not a file this repo ships
        if not target.is_file():
            return False
        text = target.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return False
    if require_contrast or contrast:
        # The KERNEL bound (and, when a consumer opts into the selector, its check too): BOTH halves
        # must be real definitions in this one surface.
        return _test_node_is_defined(text, node) and _test_node_is_defined(text, contrast)
    # The CONSUMER arm, byte-identical to T-10914: the node need only be CARRIED by the surface.
    return node in text
# T-11015 (SPEC-0177) — the READ-ONLY CONFORMANCE SURFACES: the mechanism class whose whole production
# surface is a verb that only LOOKS. It reads current state, reports, and BY DESIGN writes nothing — no
# journal row, no stored state — which is precisely what makes it a safe observer (SPEC-0133 rule 1).
# Every spelling above resolves against a row the MECHANISM wrote, so this class had nothing of its own
# to point at on the KERNEL: the `test:` arm is consumer-only, and the generic `cli_invoked@<ts>`
# receipt the CLI harness writes for EVERY verb carries no differential and no tie to the surface named
# — a smoke check, not a probe (CHARTER §P3). Recorded bind: T-10984, fingerprint
# `read-only-conformance-guard-cannot-satisfy-substantive-p8-on-kernel`.
#
# THIS SET IS THE CLASS BOUND (SPEC-0177 rule 5) and it is deliberately tiny: a surface that is NOT
# here cannot be named by an `exit:` ref at all, so a card whose production surface DOES emit a journal
# row stays on the ordinary contract. A vocabulary that widened to every infra verb would be the
# general author-run escape hatch rule 5 forbids.
#   key   — the verb label EXACTLY as `cli_invoked.data.verb` spells it; what a ref names and what row
#           matching compares against.
#   argv  — the exact argument VECTOR the nightly execs (`lib/nightly.py::_check_conformance_surfaces`),
#           never a shell split of the label: the label is prose, argv is the command.
#   impl  — the implementation this entry VOUCHES for as non-emitting; read by the standing AC4
#           state-check, which fails the moment that implementation learns to write.
# By construction this is ALSO the set the nightly exercises, so "could a scheduled run have exercised
# this guard?" is answered by membership — no second flag to keep in sync.
_READ_ONLY_CONFORMANCE_SURFACES = {
    "graph conformance": {"argv": ("graph", "conformance"), "impl": "lib.graph:cmd_graph_conformance"},
}
_EXIT_STATUS_EVIDENCE_PREFIX = "exit:"        # `exit:<verb>#seeded=<iso-ts>&clean=<iso-ts>`
_EXIT_SEEDED_SELECTOR_PREFIX = "seeded="
_EXIT_CLEAN_SELECTOR_PREFIX = "clean="
_CLI_INVOKED_EVIDENCE_TYPE = "cli_invoked"    # the harness receipt an exit-status ref is read from
# The SCHEDULED-RUN row (SPEC-0105) + its selector: `nightly_run_completed@<iso-ts>#surface=<verb>`.
_SCHEDULED_RUN_EVIDENCE_TYPE = "nightly_run_completed"
_SCHEDULED_RUN_SELECTOR_PREFIX = "surface="
# A surface RAN under the scheduled runner only on these verdicts. `skip` (not the engine / paths
# absent) and `error` (a runner fault) mean it never executed, so they witness nothing — fail-closed.
_SCHEDULED_RUN_RAN_VERDICTS = frozenset({"ok", "fail"})


def _resolve_exit_status_evidence_ref(ref: str, events: list) -> bool:
    """T-11015 — does an EXIT-STATUS ref `exit:<verb>#seeded=<iso-ts>&clean=<iso-ts>` resolve?

    THE VOCABULARY (SPEC-0177 rule 1): for a read-only conformance surface the honest machine artifact
    is the verb's EXIT STATUS — and it counts only WITH its DIFFERENTIAL: a seeded violation makes the
    verb exit non-zero, a clean tree makes it exit zero. The differential is not decoration here, it IS
    the correlation: `cli_invoked` carries no task_id, and a single receipt saying "a command ran and
    exited 0" is earned by every invocation alike. A PAIR of pinned receipts on the SAME named surface,
    one failing and one passing, is a thing only a wired-up guard can produce.

    All four conditions must hold:
      (i)   `<verb>` is a `_READ_ONLY_CONFORMANCE_SURFACES` key — the class bound (rule 5). A surface
            that emits a journal row of its own is not here, and is held to the ordinary contract;
      (ii)  both timestamps are present and DISTINCT — one run cannot be both halves of a differential;
      (iii) the exact (`cli_invoked`, seeded-ts) row exists, its `data.verb` is `<verb>`, and its
            `data.exit_code` is an int that is NOT zero — the seeded violation made the PRODUCTION
            surface fail, which is what a test node cannot prove (rule 2: this is surface fidelity);
      (iv)  the exact (`cli_invoked`, clean-ts) row exists, same verb, `data.exit_code == 0`.
    A missing, empty or wrong-typed half is UNKNOWN and never a match — the reader owns the
    missing-value judgement (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`). A bool is NOT
    accepted as the exit code: `isinstance(True, int)` is True in Python, and an exit status is a number.

    WHAT THIS IS NOT (SPEC-0177 rule 2, enforced in `_infra_adoption_seen`, not here): resolving is not
    adoption. Both halves are author-run at authoring time, so on the KERNEL an `exit:` ref alone leaves
    the card un-adopted — the scheduled run is the preferred proof. This predicate answers only "is the
    claim CHECKABLE"; the standing SPEC-0015 bound is unchanged.

    Pure function of (ref, events) — no I/O."""
    body = ref[len(_EXIT_STATUS_EVIDENCE_PREFIX):]
    verb, sep, selector = body.partition("#")
    verb, selector = verb.strip(), selector.strip()
    if not sep or not verb or not selector:
        return False
    if verb not in _READ_ONLY_CONFORMANCE_SURFACES:                         # (i)
        return False
    seeded_part, amp, clean_part = selector.partition("&")
    if not amp or not seeded_part.startswith(_EXIT_SEEDED_SELECTOR_PREFIX) \
            or not clean_part.startswith(_EXIT_CLEAN_SELECTOR_PREFIX):
        return False
    seeded_ts = seeded_part[len(_EXIT_SEEDED_SELECTOR_PREFIX):].strip()
    clean_ts = clean_part[len(_EXIT_CLEAN_SELECTOR_PREFIX):].strip()
    if not seeded_ts or not clean_ts or seeded_ts == clean_ts:              # (ii)
        return False

    def _exit_code_at(ts: str):
        """The int exit code of the pinned `cli_invoked` row for THIS verb, else None (unknown)."""
        for ev in events:
            if ev.get("type") != _CLI_INVOKED_EVIDENCE_TYPE:
                continue
            if str(ev.get("ts") or "") != ts:
                continue
            data = ev.get("data")
            if not isinstance(data, dict) or data.get("verb") != verb:
                continue
            code = data.get("exit_code")
            if isinstance(code, bool) or not isinstance(code, int):
                continue
            return code
        return None

    seeded_code = _exit_code_at(seeded_ts)
    if seeded_code is None or seeded_code == 0:                             # (iii)
        return False
    return _exit_code_at(clean_ts) == 0                                     # (iv)


def _resolve_scheduled_run_ref(surface: str, ts: str, events: list) -> bool:
    """T-11015 — does a SCHEDULED-RUN ref `nightly_run_completed@<iso-ts>#surface=<verb>` resolve?

    THE PREFERRED PROOF (SPEC-0177 rule 3): the bounded methodology-nightly (SPEC-0105) exercising the
    real verb — a DIFFERENT actor, at a DIFFERENT time than the authoring session — recorded on the ONE
    durable `nightly_run_completed` row that run already emits. That is what "adopted" means: behaviour
    exercised outside the session that authored it. The closure LATENCY this imposes is the price of
    proving adoption rather than intent, not a defect to engineer around.

    Correlated, never a bare type: (i) the ref is PINNED to an exact (type, ts) row; (ii) that row's
    `data.conformance_surfaces` NAMES this surface; (iii) that entry's verdict is one the runner uses
    to mean the surface actually RAN, alongside an int exit code. A `skip`/`error` entry means it never
    executed and witnesses nothing; a bare `nightly_run_completed` (some nightly ran) proves nothing
    about a guard and is not this spelling.

    Pure function of (surface, ts, events) — no I/O."""
    if not surface or not ts:
        return False
    for ev in events:
        if ev.get("type") != _SCHEDULED_RUN_EVIDENCE_TYPE:
            continue
        if str(ev.get("ts") or "") != ts:                                   # (i)
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        recorded = data.get("conformance_surfaces")
        if not isinstance(recorded, list):
            continue
        for entry in recorded:                                              # (ii)
            if not isinstance(entry, dict) or entry.get("surface") != surface:
                continue
            code = entry.get("exit_code")                                   # (iii)
            if entry.get("verdict") in _SCHEDULED_RUN_RAN_VERDICTS \
                    and not isinstance(code, bool) and isinstance(code, int):
                return True
    return False


# T-12021 — the AUTHOR-FACING render of every form accepted below is `P8_EVIDENCE_REF_GRAMMAR`
# (above, beside `P8_EVIDENCE_PAYLOAD_CUE`). ADD A FORM HERE => ADD ITS LINE THERE: the surfaces
# that tell an author how to write a ref read that constant and nothing else.
def _resolve_evidence_ref(ref: str, tid: str, events: list, *,
                          _is_consumer_build=None, REPO_ROOT=None, _resolve_abort_row_ref, _resolve_exit_status_evidence_ref, _resolve_gate_row_ref, _resolve_in_process_evidence_ref, _resolve_layer_row_ref, _resolve_metric_row_ref, _resolve_scheduled_run_ref, _resolve_verify_refusal_row_ref) -> bool:
    """T-10282 — does `ref` RESOLVE to a real, non-circular, correlated journal event?

    CORRELATION is the point (audit-pre F2): "an event of this type exists SOMEWHERE in the journal" is
    not evidence of anything — every busy journal has one. Three accepted spellings:
      - a bare TYPE (`deploy_completed`) resolves only against an event of that type whose `task_id`
        equals THIS closing task's id — the mechanism fired FOR this task;
      - a concrete `TYPE@<iso-ts>` ref (`deploy_completed@2026-07-09T12:00:00Z`) resolves against the
        exact (type, ts) event — the escape for a mechanism event that carries NO task_id, so such
        evidence stays citable without loosening the correlation rule for the types that DO carry one;
      - (T-10485) a LAYER-ROW ref `land_completed@<iso-ts>#<layer>` — a sanctioned spelling of an
        otherwise-blocklisted type, for the land-emitted verify-layer ship class. It is NOT a general
        `#fragment` address space: the selector is honored for `land_completed` alone (the sole
        blocklisted type carrying a per-MECHANISM row) and its four correlation conditions live in
        `_resolve_layer_row_ref`. Every other type carrying a selector is refused;
      - (T-10937, widened by T-11421) an ABORT-ROW ref `land_completed@<iso-ts>#branch=<branch>` — the
        second such spelling, for the LAND-TIME REFUSAL ship class (a never-landing abort, or a gate
        that refuses without discarding its branch — T-11227's work-batch carrier gate); conditions in
        `_resolve_abort_row_ref`. Same type, same `#` address space, disambiguated by the literal
        `branch=` prefix. The SPELLING is unchanged — T-11421 widened only condition (iii).
      - (T-11005) a VERIFY-REFUSAL ref `land_completed@<iso-ts>#refused=<test-node>&branch=<branch>` —
        the third such spelling, for the class whose shipped mechanism IS the land-verify gate;
        conditions in `_resolve_verify_refusal_row_ref`. Checked BEFORE the `branch=` form so the two
        abort spellings never shadow each other.
      - (T-12106) a GATE-ROW ref `land_completed@<iso-ts>#gate=<test-file>` — the FIFTH such spelling,
        for the KERNEL-SIDE GATE ship class (a land-verify gate that journals nothing on PASS, whose
        consumer is the NEXT kernel land); conditions in `_resolve_gate_row_ref`. Same type, same `#`
        address space, disambiguated by the literal `gate=` prefix. It reads only data `land` already
        writes — no new payload, no new emit.
      - (T-11570) a METRIC-ROW ref `land_completed@<iso-ts>#metric=<key>` — the fourth such spelling,
        for the POST-SHIP PAYLOAD-KEY READING class (a SPEC-0036 variant-(e) reading of a key the land
        runner writes onto `verify_metrics`, whose qualifying rows are ordinary `status: ok` lands on
        OTHER branches — so none of the three above can express it); conditions in
        `_resolve_metric_row_ref`. Same type, same `#` address space, disambiguated by the literal
        `metric=` prefix.
    A ref naming a `_NON_EVIDENTIAL_EVIDENCE_TYPES` member never resolves (circular / free-for-every-task),
    the five correlated `land_completed` selectors above being its only exceptions.

    (T-10914, widened by T-12106) A FURTHER spelling — the in-process observation ref
    `test:<repo-relative test path>::<node>[&contrast=<node>]` — resolves against the REPO instead of the
    journal, for the mechanism class that emits no journal row at all (rationale + bound: the block
    above). On a CONSUMER it is admitted exactly as T-10914 shipped it. On the KERNEL (or an UNKNOWN
    realm — the stricter reading) it is admitted only WITH the `&contrast=` red-contrast node, both
    halves being real `def` definitions in one real test surface. The injected `REPO_ROOT` is still
    required in either realm, so an un-injected / isolated caller reads exactly what it read before
    (the established `_event_dedup_key` / `_main_events_path` injection precedent).

    Pure function of (ref, tid, events) for the journal spellings — no I/O, so both call-sites share one
    honest computation (P5); only the consumer arm reads the repo, and only when it is admitted."""
    if not isinstance(ref, str) or not ref.strip():
        return False
    ref = ref.strip()
    if ref.startswith(_IN_PROCESS_EVIDENCE_PREFIX):
        # Checked BEFORE the `@`/`#` partition below: this ref addresses a FILE, not an event type, so
        # the journal-ref grammar must not shred it. With no injected root the arm is DARK in either
        # realm ⇒ False, never a fallthrough to the type loop — the prefix is not a legal event type.
        #
        # T-12106 — THE REALM GATE MOVED, THE REQUIREMENT DID NOT. The arm was KERNEL-DARK because the
        # assumption the rest of this grammar rests on — the audited MECHANISM emits journal rows —
        # HOLDS for most kernel mechanisms, so a soft form would have been an escape from a hard one
        # that exists. It does NOT hold for a named class ON the kernel: a report-only STDOUT view
        # that writes nothing, and a reading whose carrier is a committed artifact (measured on
        # T-12081 and T-11133, whose honest, audit-GREEN P8 events could not resolve for exactly this
        # structural reason — SPEC-0119 rule 31 records the same class). So the kernel is admitted
        # under a STRICTLY STRONGER bound than the consumer arm has ever carried: a REQUIRED
        # `&contrast=` naming a SECOND, DISTINCT node, with BOTH halves real DEFINITIONS in one real
        # test surface. An UNKNOWN realm takes the STRICTER reading — the same fail-closed convention
        # `_infra_adoption_seen`'s realm subtraction uses — so nothing is loosened by a missing probe.
        # Every consumer judgement is byte-identical to before this card (`require_contrast=False`).
        if REPO_ROOT is None:
            return False
        is_consumer = bool(_is_consumer_build and _is_consumer_build())
        return _resolve_in_process_evidence_ref(ref, REPO_ROOT=REPO_ROOT,
                                                require_contrast=not is_consumer)
    if ref.startswith(_EXIT_STATUS_EVIDENCE_PREFIX):
        # (T-11015) the FIFTH spelling — an EXIT-STATUS differential over a read-only conformance
        # surface. Checked here for the same reason as `test:` above: it addresses a VERB and a PAIR of
        # pinned receipts, not one event type, so the `@`/`#` grammar below must not shred it. Realm-
        # AGNOSTIC by design (unlike the consumer-only `test:` arm): the class it serves lives on the
        # kernel, and what the kernel asks of it EXTRA — the scheduled run — is asked at the adoption
        # verdict (`_infra_adoption_seen`), never by making the ref itself unresolvable here.
        return _resolve_exit_status_evidence_ref(ref, events)
    etype, _, rest = ref.partition("@")
    ts, sep, layer = rest.partition("#")
    etype, ts, layer = etype.strip(), ts.strip(), layer.strip()
    if not etype:
        return False
    if sep:
        # The READER owns the missing-value judgement (lessons/fail-closed-belongs-to-the-reader-not-
        # the-parser): an empty selector is MALFORMED, never a match-any, and an unpinned or
        # wrong-typed selector buys no escape from the blocklist.
        if not layer or not ts:
            return False
        if etype == _SCHEDULED_RUN_EVIDENCE_TYPE:
            # (T-11015) the SCHEDULED-RUN form `surface=<verb>` — the second TYPE admitted into this
            # `#` address space, and the first that is not blocklisted. It is here for the same reason
            # the land_completed selectors are: the bare type says only "some nightly ran", which
            # proves nothing about a guard, so the row is citable only through a selector that NAMES
            # the surface it exercised. Any other selector on this type is MALFORMED (fail-closed).
            if not layer.startswith(_SCHEDULED_RUN_SELECTOR_PREFIX):
                return False
            surface = layer[len(_SCHEDULED_RUN_SELECTOR_PREFIX):].strip()
            return bool(surface) and _resolve_scheduled_run_ref(surface, ts, events)
        if etype != _LAYER_ROW_EVIDENCE_TYPE:
            return False
        if layer.startswith(_VERIFY_REFUSAL_SELECTOR_PREFIX):
            # (T-11005) the VERIFY-REFUSAL form `refused=<node>&branch=<branch>`. Checked BEFORE the
            # `branch=` arm so the two abort forms never shadow each other. BOTH halves are required:
            # a missing `&branch=`, an empty node, or an empty branch is MALFORMED — never a
            # match-any, the same fail-closed reading the other selectors get.
            body = layer[len(_VERIFY_REFUSAL_SELECTOR_PREFIX):]
            node, amp, branch_part = body.partition("&")
            node = node.strip()
            if not amp or not node or not branch_part.startswith(_ABORT_ROW_SELECTOR_PREFIX):
                return False
            branch = branch_part[len(_ABORT_ROW_SELECTOR_PREFIX):].strip()
            return bool(branch) and _resolve_verify_refusal_row_ref(node, branch, tid, ts, events)
        if layer.startswith(_ABORT_ROW_SELECTOR_PREFIX):
            # (T-10937) the ABORT-ROW form — an empty branch value is MALFORMED, same fail-closed
            # reading as an empty selector above, never a match-any branch.
            branch = layer[len(_ABORT_ROW_SELECTOR_PREFIX):].strip()
            return bool(branch) and _resolve_abort_row_ref(branch, ts, events)
        if layer.startswith(_GATE_ROW_SELECTOR_PREFIX):
            # (T-12106) the GATE-ROW form `gate=<test-file>` — an empty file value is MALFORMED, the
            # same fail-closed reading its four siblings get, never a match-any file. Checked BEFORE
            # `metric=` only for readability; the literals are mutually exclusive, so no arm here can
            # shadow another, and a bare layer name has never been able to contain `=`.
            gate_file = layer[len(_GATE_ROW_SELECTOR_PREFIX):].strip()
            return bool(gate_file) and _resolve_gate_row_ref(gate_file, tid, ts, events,
                                                             REPO_ROOT=REPO_ROOT)
        if layer.startswith(_METRIC_ROW_SELECTOR_PREFIX):
            # (T-11570) the METRIC-ROW form `metric=<key>` — an empty key value is MALFORMED, the
            # same fail-closed reading the three selectors above get, never a match-any key. Placed
            # LAST among the prefixed forms and before the bare-layer fallback: the three literals are
            # mutually exclusive, so this arm's position cannot shadow (or be shadowed by) them, and
            # a bare layer name has never been able to contain `=`.
            key = layer[len(_METRIC_ROW_SELECTOR_PREFIX):].strip()
            return bool(key) and _resolve_metric_row_ref(key, ts, events)
        return _resolve_layer_row_ref(layer, tid, ts, events)
    if etype in _NON_EVIDENTIAL_EVIDENCE_TYPES:
        return False
    # T-13139 — a corpus that carries an exact existence index for this question (the debt seam's
    # one-pass `P8ResolutionCorpus`, which does not hold every row) answers it from the index; the
    # answer is the loop's below, by construction of that index. A plain list takes the loop.
    index = getattr(events, "type_index", None)
    if index is not None:
        return index.has_ts(etype, ts) if ts else index.has_task(etype, tid)
    for ev in events:
        if ev.get("type") != etype:
            continue
        if ts:
            if str(ev.get("ts") or "") == ts:
                return True
        elif ev.get("task_id") == tid:
            return True
    return False
# ── T-12021 (X-1245) — the CHARTER §P2 commit-locator SHAPE ──────────────────────────────────────
# Read ONLY by the no-ref-resolves diagnostic, and ONLY to NAME what the author wrote. It is
# deliberately NOT an arm of `_resolve_evidence_ref`: admitting this shape as evidence was the
# decision this card made and DECLINED, because it names no event type (so it cannot carry the
# correlation the grammar exists for) and because its own "maps unambiguously to ONE row"
# precondition fails — 35.1% of this journal's rows share a timestamp with another (208,844 of
# 595,737 at the measurement, worst second = 34 rows), so it would resolve for one author and refuse
# for the next for a reason invisible in the ref. Recognising a shape in order to REFUSE IT BY NAME
# is the opposite of accepting it. Pure string read; never raises.
_P2_COMMIT_LOCATOR_PREFIX = "events.jsonl#"


def _is_p2_commit_locator_ref(ref) -> bool:
    """True for a ref written in the CHARTER §Principle-2 `from:` commit-locator spelling
    (`events.jsonl#ts=<ISO>` / `events.jsonl#source_ref=<locator>`) — correct in a commit trailer,
    and never an `evidence_events` ref. See the block above for why this is a diagnostic, not an arm."""
    return isinstance(ref, str) and ref.strip().startswith(_P2_COMMIT_LOCATOR_PREFIX)


def p8_payload_missing_keys(data) -> list:
    """T-12866 — the KEY-SHAPE clause of the P8 payload contract (SPEC-0015), in ONE place.

    Returns the required keys `data` fails, in contract order: `failing_input` (a non-empty string)
    and `evidence_events` (a non-empty list). Its two readers apply the SAME clause at the two ends of
    a row's life: `_p8_evidence_is_substantive` (READ — close / debt / audit packet) and
    `events.cmd_event` (WRITE — refuses the row before it can exist). One function, so the write
    admits exactly the key shape the read requires, never two lists kept in agreement by hand
    (CHARTER §P5). Ref RESOLUTION is deliberately not here: a ref may legitimately resolve only at
    close (e.g. against main's journal, SPEC-0168), so it stays read-side."""
    if not isinstance(data, dict):
        return list(P8_PAYLOAD_REQUIRED_KEYS)
    missing = []
    failing_input = data.get("failing_input")
    if not isinstance(failing_input, str) or not failing_input.strip():
        missing.append("failing_input")
    refs = data.get("evidence_events")
    if not isinstance(refs, list) or not refs:
        missing.append("evidence_events")
    return missing


P8_PAYLOAD_REQUIRED_KEYS = ("failing_input", "evidence_events")


def _p8_evidence_is_substantive(ev: dict, tid: str, events: list, *,
                                _is_consumer_build=None, REPO_ROOT=None, with_reason=False, _gate_ref_diagnosis, _is_p2_commit_locator_ref, _resolve_evidence_ref):
    """T-10282 (X-0246) — is this P8 adoption event SUBSTANTIVE, or prose asserting its own conclusion?

    Substantive iff its `data` carries BOTH:
      - `failing_input` — a non-empty string naming the input that must make the criterion FAIL (the
        SPEC-0060 §4 differential, now DEMANDED here rather than merely prompted at authoring), AND
      - `evidence_events` — a non-empty list of refs, at least ONE of which `_resolve_evidence_ref`s to a
        real, correlated, non-circular machine event (T-10914: on a CONSUMER instance a ref may instead
        name the executable test node that observed an IN-PROCESS mechanism emission — the FORM widens,
        this both-keys requirement does not).

    The incident (T-9416): a hand-emitted `live_trigger_evidence` whose whole payload was
    {relates_to, impact, fingerprint} — free text ASSERTING "restore-drill OK". `_infra_adoption_seen`
    matched it on type + task_id and never opened `data`, so the adoption claim was self-issued prose.

    HONEST BOUND (SPEC-0015): this rejects prose and circularity and forces a resolvable machine
    reference + a named differential. It does NOT judge whether that event is SEMANTICALLY the right
    evidence for the mechanism under test — that judgement is the OTHER verify surface's (the SPEC-0036
    audit-post differential-probe lens). Close checks the claim is CHECKABLE; audit-post checks it is TRUE.

    T-12003 — `with_reason` RETURNS THE REASON THIS PREDICATE ALREADY COMPUTES AND THREW AWAY.
    Default False, so every existing caller's return TYPE and VERDICT are byte-identical; with True
    the return is `(verdict, reason)`, `reason` None iff substantive. The verdict logic below is
    untouched — the reason is read off the same clauses, never a second judgement, because a
    parallel predicate is exactly what would let the two drift (CHARTER §P5 / §P1 F1).

    ITS ONE READER is the SPEC-0119 rule-31 debt line (`debt.py#_p8_later_evidence_clears`), which
    could previously print only THAT a recorded P8 event did not clear a row, never WHY. The
    measured shape (<project> 2026-09-02): two genuine, task-tied `live_trigger_evidence` rows whose
    payload carried `instrument`/`reading`/`baseline_at_card_close`/`differential` — a real
    differential, in PROSE, under keys this contract does not read — leaving the author to choose
    between a false "still owed" carrier and an unexplained debt line.

    THE TWO KEY CHECKS REPORT TOGETHER, not first-unmet-only (audit-pre finding, absorbed mode-a).
    The verdict short-circuits on the first failure and always did; the REASON does not, because
    that measured payload is missing BOTH keys and naming one would send the author back to compose
    a payload that still fails on the key nobody named — the extra round-trip this reader exists to
    remove. Widening the REPORT cannot move the verdict: either key alone already fails.

    AND IT NAMES NO DISTINCTION IT CANNOT MAKE. `_resolve_evidence_ref` answers a bool, so
    "unresolvable" and "circular" are ONE reason here, not two. Inventing the split would be prose
    asserting its own precision — the very thing this predicate rejects in the payloads it judges."""
    def _verdict(ok, reason=None):
        return (ok, reason) if with_reason else ok

    data = ev.get("data")
    if not isinstance(data, dict):
        return _verdict(False, "the event carries no `data` object")
    refs = data.get("evidence_events")
    missing = [f"`{k}`" for k in p8_payload_missing_keys(data)]
    if missing:
        return _verdict(False, "payload is missing " + " and ".join(missing))
    if not any(_resolve_evidence_ref(r, tid, events, _is_consumer_build=_is_consumer_build,
                                     REPO_ROOT=REPO_ROOT) for r in refs):
        # T-12021 (X-1245) — NAME THE LOOK-ALIKE. The verdict here is UNMOVED: a P2-locator ref never
        # resolved and still does not. What is retired is the UNDIAGNOSED refusal — the shape has no
        # `@`, so the parse below reads the whole string as an event type, no row has that type, and
        # the author was told only "no ref resolves", which reads identically to "the mechanism has
        # not fired yet". That is what burned two emissions on <project>: the author had just read
        # CHARTER §Principle 2, where the durable journal locator IS spelled this way. The extra
        # clause is REPORT-ONLY and fires only on the failing path, so a clean payload pays nothing.
        if any(_is_p2_commit_locator_ref(r) for r in refs):
            return _verdict(False, "no `evidence_events` ref resolves — and at least one is written "
                                   "as `events.jsonl#ts=…` / `events.jsonl#source_ref=…`, which is "
                                   "the CHARTER §Principle-2 COMMIT `from:` locator, NOT this "
                                   "grammar: it names no event type, so it can carry none of the "
                                   "correlation an adoption ref needs. Cite the SAME row as "
                                   "`<event_type>@<iso-ts>` (or, when the row carries this task's "
                                   "`task_id`, as the bare `<event_type>`)")
        # T-12106 — NAME THE UNMET CONDITION for a form-(10) `gate=` ref. The verdict is UNMOVED;
        # what is retired is a refusal an author cannot act on. Form (10) is the only form whose
        # conditions are read off ANOTHER land's row and a git revision, so "no ref resolves" gave
        # the author nothing to fix — unlike the payload-key clauses above, which name their key.
        # Report-only, and only on the already-failing path, so a clean payload pays nothing.
        gate_why = next((w for w in (_gate_ref_diagnosis(r, tid, events, REPO_ROOT=REPO_ROOT)
                                     for r in refs) if w), None)
        if gate_why:
            return _verdict(False, "no `evidence_events` ref resolves — the `gate=` ref did not "
                                   f"resolve because {gate_why}")
        return _verdict(False, "no `evidence_events` ref resolves "
                               "(unresolvable, or circular — a ref that proves only that the task closed)")
    return _verdict(True)


def _p8_substantive_evidence_exists(tid: str, *, EVENTS_PATH, _p8_evidence_events_for,
                                    _event_dedup_key=None, _main_events_path=None,
                                    _is_consumer_build=None, REPO_ROOT=None, _p8_adoption_verdict,
                                    matched_out: "list | None" = None) -> bool:
    """True iff SOME P8 adoption event for this task is SUBSTANTIVE (T-10282). The close-time replacement
    for `_p8_evidence_event_exists` inside `_infra_adoption_seen` — the ONE call-site that tightened.
    The journal is re-read only when a candidate P8 event exists (short-circuit), so a normal infra close
    with no P8 event pays exactly the reads it did before.

    T-10796 — THE RESOLUTION CORPUS IS THE CROSS-INSTANCE FOLD, exactly as the candidate lookup's is.
    Until this card the candidates came from the SPEC-0168 fold while the events they were resolved
    AGAINST came from a second, SINGLE-instance read of `EVENTS_PATH` — so a payload could be folded in
    and then judged unresolvable, which is the defect (not the lookup). It bit T-10781 live: its
    `live_trigger_evidence` cited `worktree_created` + `work_batch_discarded`, every ref resolving True
    against MAIN's journal, and `task close` still raised the E-0005 "no SUBSTANTIVE event" WARN. Those
    types are written to main BY DESIGN (`_discard_work_batch` passes `events_path=main_wt/"events.jsonl"`),
    so the class is structural: ANY mechanism firing in a checkout other than the closing one was
    uncitable at close. Rule 7 promises a D-0049 main-checkout append stays legal; it is only KEEPABLE if
    the close-time reader folds too.

    NARROWED, NEVER WEAKENED. The fold adds rows to resolve AGAINST; `_resolve_evidence_ref`'s
    correlation (task-id exactness / pinned-ts / the layer-row conditions) and
    `_p8_evidence_is_substantive`'s payload demands are untouched, so evidence absent from BOTH
    instances still fails. The rule-4 provenance mark and rule-5 `_evidence_key` the fold stamps are
    additive keys no resolver reads.

    NO SECOND READER — this rides `_p8_evidence_events_for`'s OWN seam: the same two host deps
    (`_event_dedup_key`, rule 3's write-side identity, which lives in the unimportable `bin/yitc-v2`
    script; and `_main_events_path`, rule 1's landable main instance), both defaulting to absent so an
    isolated / un-injected caller reads exactly the one journal it did before.

    T-10914 (X-0730) — the same seam carries the two deps of the CONSUMER in-process arm
    (`_is_consumer_build`, whose repo-identity read lives in the unimportable script, and `REPO_ROOT`,
    the corpus the test node is resolved inside). Both default to absent on the identical principle:
    un-injected ⇒ the arm is dark and this predicate judges exactly what it judged before.

    T-11015 (SPEC-0177 rule 2/3) — DELEGATES to `_p8_adoption_verdict`, which carries the same reading
    plus the kernel scheduled-run preference. Signature and meaning are UNCHANGED for every caller.

    T-13072 — `matched_out` (optional out-param, absent ⇒ unchanged): when the verdict is True, the
    matched row is appended as `{"ref": "events.jsonl#ts=<ts>", "type": <P8 type>}` — the D-0030
    locator `task._journal_locator` parses, plus the row type (the ts grammar alone collides at
    whole-second resolution; two SAME-type rows for this task in the SAME second stay ambiguous)."""
    verdict = _p8_adoption_verdict(tid, EVENTS_PATH=EVENTS_PATH,
                                   _p8_evidence_events_for=_p8_evidence_events_for,
                                   _event_dedup_key=_event_dedup_key,
                                   _main_events_path=_main_events_path,
                                   _is_consumer_build=_is_consumer_build,
                                   REPO_ROOT=REPO_ROOT)
    if verdict["substantive"] and matched_out is not None and verdict.get("matched"):
        row = verdict["matched"]
        matched_out.append({"ref": f"events.jsonl#ts={row.get('ts')}", "type": row.get("type")})
    return verdict["substantive"]


def _exit_status_ref_surface(ref) -> "str | None":
    """The read-only conformance SURFACE an `exit:` ref names, or None when the ref is not one. Pure
    string read — resolution is `_resolve_exit_status_evidence_ref`'s job, this only reads the label."""
    if not isinstance(ref, str) or not ref.strip().startswith(_EXIT_STATUS_EVIDENCE_PREFIX):
        return None
    verb = ref.strip()[len(_EXIT_STATUS_EVIDENCE_PREFIX):].partition("#")[0].strip()
    return verb or None


def _is_undifferentiated_receipt_ref(ref) -> bool:
    """True for a ref naming a receipt that records only THAT SOMETHING RAN, naming no mechanism:
      · any `cli_invoked` ref — the harness receipt EVERY verb invocation earns, carrying no
        differential and no tie to a surface (the very shape `exit:` exists to replace);
      · a `nightly_run_completed` ref with NO `#surface=` selector — some nightly ran, but it names
        no surface it exercised.

    Read ONLY by `_p8_adoption_verdict`, and ONLY to decide whether something DISCHARGES the kernel
    scheduled-run preference. It does NOT change whether either ref RESOLVES: both spellings predate
    this card, other mechanisms legitimately cite them, and re-judging that is a separate concern with
    its own consumers. Pure string read."""
    if not isinstance(ref, str):
        return False
    etype, _, rest = ref.strip().partition("@")
    etype = etype.strip()
    if etype == _CLI_INVOKED_EVIDENCE_TYPE:
        return True
    return etype == _SCHEDULED_RUN_EVIDENCE_TYPE and "#" not in rest


def _p8_adoption_verdict(tid: str, *, EVENTS_PATH, _p8_evidence_events_for,
                         _event_dedup_key=None, _main_events_path=None,
                         _is_consumer_build=None, REPO_ROOT=None, _exit_status_ref_surface, _folded_journal_events, _is_undifferentiated_receipt_ref, _p8_evidence_is_substantive, _resolve_evidence_ref) -> dict:
    """T-11015 (SPEC-0177 rules 2+3) — the P8 adoption reading, in ONE computation:
      {"substantive": bool, "exit_status_only_surface": str|None}

    `substantive` is the T-10282 judgement UNCHANGED — some P8 event for this task resolves a
    non-circular machine ref and names its differential — with ONE subtraction, which is this card:

    **EXIT-STATUS EVIDENCE IS NOT, BY ITSELF, ADOPTION ON THE KERNEL (rule 2).** An `exit:` differential
    proves SURFACE FIDELITY — the production path wired end to end: CLI dispatch, discovery, inputs, the
    read-only observation path, failure reporting, exit semantics. That is strictly more than a test
    node proves, and the difference is principled. But both halves are run BY THE AUTHOR, AT AUTHORING
    TIME, so admitting them alone as closure evidence is "tests green = done" wearing a CLI-shaped
    wrapper — the precise failure CHARTER §Principle 8 exists to refuse (external consult 2026-08-13,
    which corrected the controller's original position on exactly this point). So when EVERY resolving
    ref of a kernel card is an `exit:` ref, this returns `substantive: False` and NAMES the surface: the
    EXISTING E-0005 WARN fires and `adoption_evidence_seen: false` is recorded on `task_closed` — a
    durable, greppable flag. What discharges it is the preferred proof (rule 3): the bounded nightly
    (SPEC-0105) exercising the real verb, a DIFFERENT actor at a DIFFERENT time, cited as
    `nightly_run_completed@<ts>#surface=<verb>`. The CLOSURE LATENCY that imposes is not a defect to
    engineer around; it is the price of proving adoption rather than intent.

    NOT A GATE, and deliberately so: closure still PROCEEDS (SPEC-0015 — P8 evidence is semantic, so a
    dumb hard gate would false-positive-strand legitimate closures; adding one would also be a new
    blocking mechanism, CHARTER §P1 F4 + §6). The preference lands on the recorded VERDICT, not on a
    refusal — which is what makes it stronger than a bare advisory line while adding no mechanism.

    REALM ASYMMETRY (the half the settling consult asked to see justified). On a CONSUMER instance an
    `exit:` ref alone DOES satisfy adoption: the nightly never exercises a consumer's surfaces (that
    would be the D-0019 cross-territory write its own contract forbids), so the preferred evidence is
    UNREACHABLE there. Demanding it anyway is the over-cut signature — a consumer whose only path to
    GREEN is fabricating kernel-shaped structure (`lessons/kernel-consumer-boundary-evidence`). The
    stricter rule is scoped to the realm that can actually satisfy it. `_is_consumer_build` un-injected
    ⇒ read as KERNEL: unknown realm takes the STRICTER reading (the reader owns the missing-value
    judgement), and nothing that resolved before this card is affected — the `exit:` spelling is new,
    so no pre-existing evidence can fall into this subtraction.

    Rides `_p8_evidence_events_for`'s own seam with the same injected deps as its caller — one folded
    read, no second reader (SPEC-0168 rule 7)."""
    empty = {"substantive": False, "exit_status_only_surface": None, "matched": None}
    candidates = _p8_evidence_events_for(tid)
    if not candidates:
        return empty
    if _event_dedup_key is None:
        _event_dedup_key = lambda line: line          # noqa: E731 — byte identity: single instance
    # T-13330 — the resolution corpus is DECLARED by the refs themselves (`p8_ref_horizon`): the types
    # they name, from the earliest day they pin (or the task horizon) — the whole history only for the
    # two first-ever ref forms. Every row a resolver below can match is in that slice, so the verdict
    # is the one the whole-journal corpus gave.
    _refs = [r for ev in candidates if isinstance(ev.get("data"), dict)
             and isinstance(ev["data"].get("evidence_events"), list) for r in ev["data"]["evidence_events"]]
    _types, _since = p8_ref_horizon(_refs, journal_mod.task_floor(EVENTS_PATH, tid))
    events = (_folded_journal_events(EVENTS_PATH=EVENTS_PATH, _event_dedup_key=_event_dedup_key,
                                     _main_events_path=_main_events_path,
                                     lines_of=lambda path: journal_mod.typed_lines(
                                         path, tuple(sorted(_types)), since=_since, lock=True))
              if _types else [])
    # REUSED, never re-implemented: the substantive judgement stays `_p8_evidence_is_substantive`'s, so
    # this reading and the T-10282 one can never diverge (CHARTER §P5).
    substantive = [ev for ev in candidates
                   if _p8_evidence_is_substantive(ev, tid, events,
                                                  _is_consumer_build=_is_consumer_build,
                                                  REPO_ROOT=REPO_ROOT)]
    if not substantive:
        return empty
    exit_surfaces: list = []
    other_evidence = False
    first_independent = None     # T-13072 — the first row carrying evidence the preference admits
    for ev in substantive:
        for ref in (ev.get("data") or {}).get("evidence_events") or []:
            if not _resolve_evidence_ref(ref, tid, events, _is_consumer_build=_is_consumer_build,
                                         REPO_ROOT=REPO_ROOT):
                continue
            surface = _exit_status_ref_surface(ref)
            if surface:
                exit_surfaces.append(surface)
            elif _is_undifferentiated_receipt_ref(ref):
                # THE BYPASS THIS BRANCH EXISTS TO CLOSE (audit-post pass 1, high): a receipt that
                # records only that something RAN — a bare `cli_invoked@<ts>`, or a
                # `nightly_run_completed@<ts>` naming no surface — witnesses no mechanism. Counting
                # either as independent adoption would be the cheapest possible escape from the rule
                # below: cite the author-run differential plus any invocation receipt and the
                # preference evaporates, which is self-contradictory — an undifferentiated
                # `cli_invoked` is precisely the smoke check the `exit:` differential was introduced
                # to replace. So they are INERT here: neither exit-status evidence nor other evidence.
                # They are NOT refused as refs — that grammar predates this card and other mechanisms
                # legitimately cite them — they just do not discharge THIS preference, which rule 3
                # states in terms of the run that EXERCISED the verb.
                continue
            else:
                other_evidence = True       # independent adoption exists — the preference does not bite
                if first_independent is None:
                    first_independent = ev
    # T-13072 — `matched`: the row the True verdict rests on, so `task_closed` can name its carrier
    # instead of a bare boolean. When exit-only rows sit beside independent evidence, it is the FIRST
    # row carrying INDEPENDENT evidence (the one the preference admits), never an exit-only row.
    if not exit_surfaces or other_evidence:
        return {"substantive": True, "exit_status_only_surface": None,
                "matched": first_independent or substantive[0]}
    if _is_consumer_build and _is_consumer_build():
        return {"substantive": True, "exit_status_only_surface": None,     # unreachable proof — see above
                "matched": first_independent or substantive[0]}
    return {"substantive": False, "exit_status_only_surface": exit_surfaces[0], "matched": None}


def _p8_blocking_followup_link_exists(tid: str, *, events_path, matched_out: "list | None" = None) -> bool:
    """T-11296 — CHARTER §Principle 8's THIRD adoption branch: "explicitly blocking adoption follow-up
    filed (with trigger condition + ownership)". True iff the journal at `events_path` folds to an
    OPEN followup that is ABOUT this task and carries BOTH halves the principle names.

    The admission test, and why each conjunct is there rather than one fewer:
      - `status == "open"`  — a PROMOTED followup already became a task and a DROPPED one released the
        obligation; in neither does a blocking follow-up still exist, so neither may go on silencing
        the WARN. Status is a FOLD over the FSM (`followup._fold`), never a stored field.
      - non-empty `trigger` — the ARMED partition (SPEC-0095 §Armed) IS the principle's "trigger
        condition", and it is exactly what a bare note lacks. Without this conjunct any related
        scribble would silence a genuine adoption gap — the failure this card was written NOT to
        create, and the direction that fails SILENTLY (SPEC-0165 rule 1).
      - non-empty `actor` — the "ownership" half. It is the SHIPPED owner field (T-10405: who captured
        it, host-derived at capture, born-only + immutable), reused rather than re-invented
        (CHARTER §P1 F1/F2). A legacy row without one fails CLOSED: the WARN stays, which is safe.
      - `relates_to == tid` — EXACT string match. `relates_to` is free-form PROVENANCE prose (T-10335:
        it is emphatically NOT the fire key), so a prefix/regex match would let a neighbouring id's
        followup answer for this task.

    NO NEW FIELD, NO NEW EVENT TYPE, NO SECOND READER: this reads the link the followup already
    stores, through the shipped fold. Fail-soft — an absent or unreadable journal returns False, i.e.
    the WARN keeps firing (never the silent direction)."""
    try:
        if not events_path or not Path(events_path).exists():
            return False
        # T-13330 — TASK-SCOPED (SPEC-0190 rule 4): a follow-up ABOUT this card is added after its id
        # exists (`relates_to` is written once, at followup_added) and every later row of it follows,
        # so the fold reads the four follow-up types from the task horizon (None outside a ReadScope).
        _floor = journal_mod.task_floor(Path(events_path), tid)
        items = followup._fold(Path(events_path), lambda path: journal_mod.typed_lines(
            path, ("followup_added", "followup_armed", "followup_promoted", "followup_dropped"),
            since=_floor))
    except (OSError, ValueError):
        return False
    for fid, it in items.items():
        if it.get("status") != "open":
            continue
        if not (it.get("trigger") or "").strip():
            continue
        if not str(it.get("actor") or "").strip():
            continue
        if (it.get("relates_to") or "") == tid:
            if matched_out is not None:      # T-13072 — name the followup that carried the flag
                matched_out.append(fid)
            return True
    return False


def _post_verification_gap(task: dict) -> bool:
    """SPEC-0038 §3 (T-0354) — True iff this close should WARN: non-hygiene task whose
    `post_verification` is neither FILLED nor explicitly WAIVED. ONE predicate shared by the
    forward close path and `_recover_close_tail` (P5 — same honest computation both ways).

    - FILLED  = a mapping with non-empty `criterion` AND non-empty `signal`.
    - WAIVED  = a mapping whose `none` is a non-empty free-text REASON (`none: <reason>`,
      SPEC-0038 §1) AND which carries NO criterion/signal keys — the waive is mutually
      exclusive with the filled shape (audit-pre F1: a mixed/malformed dict still WARNs;
      reason QUALITY is not machine-judged — non-goal #7).
    - class:hygiene auto-waives (no check, no marker — mirrors the fast-path skipping audits)."""
    if task.get("class") == "hygiene":
        return False
    pv = task.get("post_verification")
    if not isinstance(pv, dict):
        return True

    def _scalar(v) -> bool:
        # SPEC-0038 grammar: criterion / signal / none are prose STRINGS. A non-scalar (dict/list/
        # number) is malformed and must still WARN (audit-post F1 — no str()-coercion laundering).
        return isinstance(v, str) and bool(v.strip())

    # Mutual exclusivity is SYMMETRIC (audit-post pass-2 finding): a payload mixing the filled
    # shape WITH `none` is contradictory (fills and waives at once) — neither branch accepts it.
    filled = _scalar(pv.get("criterion")) and _scalar(pv.get("signal")) and "none" not in pv
    waived = _scalar(pv.get("none")) and not ("criterion" in pv or "signal" in pv)
    return not (filled or waived)


def _is_iso_date(v) -> bool:
    """True iff v is a strict ISO date (YYYY-MM-DD). Accepts a datetime.date — unquoted YAML
    `recheck_by: 2026-07-01` parses as a date, not a string — but REJECTS a datetime.datetime (a
    `date` SUBCLASS: unquoted `2026-07-01T12:34:56` parses to a datetime, which the grammar does NOT
    permit — date-only, no time component)."""
    if isinstance(v, _dt.datetime):   # datetime is a subclass of date — reject the time-bearing form
        return False
    if isinstance(v, _dt.date):
        return True
    if not isinstance(v, str):
        return False
    try:
        _dt.date.fromisoformat(v.strip())   # strict YYYY-MM-DD; a date+time string raises ValueError
        return True
    except ValueError:
        return False
_SECURITY_DIALECT_FIELDS = ("assert_header_present", "assert_header_absent", "assert_cookie_flags")
_COOKIE_FLAGS = ("Secure", "HttpOnly", "HostOnly")   # SPEC-0098 §1 cookie security flags (case-insensitive)
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})  # SPEC-0094 §4 no-follow dialect — the Location-bearing redirect statuses


def _security_dialect_error(lp: dict) -> "str | None":
    """Validate the SPEC-0094 §4 / SPEC-0098 §1 header/cookie security DIALECT fields on an ASSERTION.
    Returns an error STRING if malformed, else None. Called only from the assertion branch — the dialect
    rides ON TOP of the {url, expect_status} GET. `property` (the event label) is REQUIRED the moment any
    security field is present (so `security_live_probe_passed` always carries a property name)."""
    has_dialect = any(f in lp for f in _SECURITY_DIALECT_FIELDS)
    prop = lp.get("property")
    if "property" in lp and not (isinstance(prop, str) and prop.strip()):
        return "`property:` must be a non-empty string (the security-property name, the event label)"
    if has_dialect and not (isinstance(prop, str) and prop.strip()):
        return ("a security assertion (assert_header_present/absent or assert_cookie_flags) requires a "
                "non-empty `property:` name — the security property it proves (SPEC-0098 §1/§3)")
    if "property" in lp and not has_dialect:
        # A bare `property:` on an ASSERTION with no assert_* asserts NOTHING — it would emit a hollow
        # security_live_probe_passed (empty expect/actual). Reject: `property` ⟺ a real security assertion
        # (or, on the escalation form, `unprobeable` — handled in its own branch). SPEC-0098 §1.
        return ("`property:` on an assertion needs at least one security assertion "
                "(assert_header_present/absent or assert_cookie_flags) — a property with nothing to assert "
                "is meaningless; use a plain assertion (no `property`), or add an assert_*, or the "
                "`{property, unprobeable}` escalation form")
    for fld in ("assert_header_present", "assert_header_absent"):
        if fld in lp:
            val = lp[fld]
            names = val if isinstance(val, list) else [val]
            if not names or not all(isinstance(h, str) and h.strip() for h in names):
                return f"`{fld}:` must be a non-empty header name or a list of non-empty header names"
    if "assert_cookie_flags" in lp:
        cf = lp["assert_cookie_flags"]
        if not isinstance(cf, dict) or not cf:
            return "`assert_cookie_flags:` must be a non-empty mapping {cookie-name: [flag, …]}"
        allowed = {f.lower() for f in _COOKIE_FLAGS}
        for name, flags in cf.items():
            if not (isinstance(name, str) and name.strip()):
                return "`assert_cookie_flags:` keys must be non-empty cookie names"
            if not isinstance(flags, list) or not flags:
                return f"`assert_cookie_flags.{name}:` must be a non-empty list of flags {list(_COOKIE_FLAGS)}"
            bad = [f for f in flags if not (isinstance(f, str) and f.lower() in allowed)]
            if bad:
                return f"`assert_cookie_flags.{name}:` has unknown flag(s) {bad} — allowed: {list(_COOKIE_FLAGS)}"
    return None
# ── T-10750 (X-0575) — the SETTLED discharge for a live-probed `none` waiver ──────────────────────
# A waiver whose debt was genuinely discharged by a REAL non-GET probe (docker-exec import, prod SQL
# invariant, served-bundle marker, live-container differential) had no grammar-conformant way to say so:
# the only shapes were an assertion {url, expect_status} or a waiver {none, user_facing?, recheck_by?},
# and a user-facing waiver REQUIRES recheck_by (fail-closed). So a discharged item could only leave the
# overdue-recheck lens by being RE-DATED as if still owed, or by the dishonest `user_facing: false`.
# `settled_by` is the honest third exit. THE EVIDENCE IS NAMED, NEVER ASSERTED — a free-text "we checked"
# would reproduce the defect in a new spelling.
_LIVE_PROBE_PROBE_EVIDENCE_TYPES = (
    "live_probe_passed",              # SPEC-0094 §4 — the per-change probe at the deploy seam
    "security_live_probe_passed",     # SPEC-0098 — the security-property probe
    "live_trigger_evidence",          # CHARTER §P8 — the live-fire adoption evidence
    "consumer_read_evidence",         # CHARTER §P8 — the consumer-side adoption evidence
)


def _journal_locator_matches(kind: str, wanted: str, events) -> list:
    """Return the journal rows a (kind, value) locator resolves to, over an INJECTED event list.

    Shared by `_live_probe_settled_evidence_unresolved` and the T-11107 probe-settlement resolution
    check — the matching rule for a locator belongs with the locator grammar, not duplicated per
    caller (CHARTER §P5)."""
    matched = []
    for ev in events or ():
        if not isinstance(ev, dict):
            continue
        if kind == "ts":
            if str(ev.get("ts") or "").strip() == wanted:
                matched.append(ev)
        else:
            data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
            if str(ev.get("source_ref") or data.get("source_ref") or "").strip() == wanted:
                matched.append(ev)
    return matched


def _live_probe_settled_locator(lp, *, _journal_locator):
    """Return (kind, value) for a waiver's `settled_by.evidence` MATERIALIZED-JOURNAL locator, else None.

    kind ∈ {"ts", "source_ref"}. Delegates the grammar to `_journal_locator` (the one home)."""
    if not isinstance(lp, dict):
        return None
    sb = lp.get("settled_by")
    if not isinstance(sb, dict):
        return None
    return _journal_locator(sb.get("evidence"))


def _live_probe_settled_terminal(lp, *, _SETTLE_TERMINAL_RESULTS) -> "str | None":
    """Return the TERMINAL result of a waiver's `settled_by` (unreachable|falsified), else None.

    THE one home of the predicate (CHARTER §P5) — the lens, the grammar and both authoring legs read
    it, so they can never drift on what counts as a terminal. PURE. Returns the raw declared result
    whenever `settled_by.result` is a member of the vocabulary; it does NOT re-judge the reason (that
    is `_live_probe_settled_grammar_error`'s refusal), so a caller wanting a VALID terminal pairs this
    with that grammar check exactly as the lens does."""
    if not isinstance(lp, dict):
        return None
    sb = lp.get("settled_by")
    if not isinstance(sb, dict):
        return None
    result = sb.get("result")
    return result if result in _SETTLE_TERMINAL_RESULTS else None
_LIVE_PROBE_SETTLED_PROOF_KEYS = ("evidence", "probed_at", "method")


def _live_probe_settled_grammar_error(lp, *, _SETTLE_TERMINAL_RESULTS, _is_iso_date, _live_probe_settled_locator) -> "str | None":
    """Grammar half of the `settled_by` discharge (PURE — no host/journal deps, so the SPEC-0094 §3
    close-gate stays STATIC). Returns an error string when a PRESENT `settled_by` is malformed, else None.
    An ABSENT `settled_by` returns None and leaves today's fail-closed `recheck_by` floor byte-for-byte.

    TWO SHAPES, forked on `result:` (T-11748): PRESENT ⇒ the terminal shape {result, reason}; ABSENT ⇒
    today's proof triple {evidence, probed_at, method}, judged byte-for-byte as before."""
    sb = lp.get("settled_by")
    if sb is None:
        return None
    if not isinstance(sb, dict):
        return ("`settled_by:` must be a mapping — either the PROOF triple {evidence, probed_at, method} "
                "naming the real probe that discharged this waiver's debt, or the TERMINAL pair "
                "{result, reason} recording that no such proof can arrive (SPEC-0094 §3)")
    if "result" in sb:
        result = sb.get("result")
        if result not in _SETTLE_TERMINAL_RESULTS:
            return (f"`settled_by.result:` must be one of {list(_SETTLE_TERMINAL_RESULTS)} — "
                    f"`unreachable` (a proof that can NEVER arrive) or `falsified` (a reading that "
                    f"ARRIVED and came back negative). Got {result!r}. A discharge that is neither a "
                    f"named proof nor one of these two terminals is the dishonest exit this field "
                    f"replaces (SPEC-0094 §3, T-11748)")
        reason = sb.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            return (f"`settled_by.reason:` must be non-empty text — a {result!r} terminal records that "
                    f"this waiver's debt will never be proven, and WHY is the ENTIRE content of that "
                    f"record. An empty reason discharges the debt while saying nothing")
        present_proof = [k for k in _LIVE_PROBE_SETTLED_PROOF_KEYS if sb.get(k) is not None]
        if present_proof:
            return (f"`settled_by` carries BOTH a {result!r} terminal AND the proof key(s) "
                    f"{present_proof} — a discharge cannot at once NAME the probe run that proved the "
                    f"debt and record that no such run can exist. Drop one: name the proof "
                    f"({', '.join(_LIVE_PROBE_SETTLED_PROOF_KEYS)}), or record the terminal "
                    f"(result + reason)")
        return None
    loc = _live_probe_settled_locator(lp)
    if loc is None:
        ev = sb.get("evidence")
        return ("`settled_by.evidence:` must be a MATERIALIZED-JOURNAL locator — `events.jsonl#ts=<ISO-instant>` "
                "or `events.jsonl#source_ref=<ref>` (the D-0030 citation form). A bare `T-NNNN` or a commit sha "
                "names WORK, never the probe RUN, so it cannot prove the debt was discharged"
                + (f"; got {ev!r}" if ev is not None else " (absent)"))
    if not _is_iso_date(sb.get("probed_at")):
        return "`settled_by.probed_at:` must be an ISO date (YYYY-MM-DD) — WHEN the probe was run"
    method = sb.get("method")
    if not (isinstance(method, str) and method.strip()):
        return ("`settled_by.method:` must be non-empty text naming HOW it was probed (docker-exec import / "
                "prod SQL invariant / served-bundle marker / live-container differential)")
    return None


def _live_probe_waiver_settled(lp, *, _live_probe_settled_grammar_error) -> bool:
    """TRUE iff `lp` is a waiver carrying a GRAMMAR-VALID `settled_by` (the discharged state).

    ONE home for the predicate — `bin/lib/views.py` imports it so the overdue lens and the close-gate
    can never drift apart (CHARTER §P5). PURE and read-time-safe: it proves the marker is WELL-FORMED,
    never that the locator RESOLVES — resolution needs the journal and lives at the close-gate
    (`_live_probe_settled_evidence_unresolved`), the only door into the landed corpus the lens reads."""
    if not isinstance(lp, dict) or "none" not in lp:
        return False
    if lp.get("settled_by") is None:
        return False
    return _live_probe_settled_grammar_error(lp) is None


def _live_probe_settled_evidence_unresolved(lp, events, *, _journal_locator_matches, _live_probe_settled_locator) -> "str | None":
    """RESOLUTION half — run at the CLOSE-GATE, which already reads the journal. Returns a refusal
    reason when a grammar-valid `settled_by` locator does NOT resolve to a real probe-evidence event,
    else None. PURE with INJECTED events (the caller folds worktree+main via `_folded_journal_events`),
    so it stays unit-testable without touching the host.

    TWO ways a settle is dishonest and both are refused:
      (a) the locator names NO existing journal line — a made-up citation;
      (b) it resolves to a line that is not PROBE EVIDENCE — resolving to an arbitrary event would let
          any waiver settle against any journal line, which is the same defect one layer down."""
    loc = _live_probe_settled_locator(lp)
    if loc is None:
        return None  # not a settled waiver (or malformed) — the grammar half owns that refusal
    kind, wanted = loc
    matched = _journal_locator_matches(kind, wanted, events)
    if not matched:
        return (f"`settled_by.evidence` names {kind}={wanted!r}, which resolves to NO event in the journal "
                f"(worktree+main fold) — a settled waiver must cite a probe run that actually happened")
    types = {str(ev.get("type") or "") for ev in matched}
    if not (types & set(_LIVE_PROBE_PROBE_EVIDENCE_TYPES)):
        return (f"`settled_by.evidence` resolves to event type(s) {sorted(t for t in types if t)} — none is "
                f"PROBE EVIDENCE. Cite one of {list(_LIVE_PROBE_PROBE_EVIDENCE_TYPES)}: a settle must name the "
                f"probe RUN that discharged the debt, not an unrelated journal line")
    return None
# ── T-11674 (X-1130) — THE ATTESTED FORM: the kernel GRADES a proof the PROJECT already runs ──────
# THE MISMATCH <project> measured (25 overdue rechecks, ONE structural cause). The declaration grammar
# above offers exactly two outcomes for a real change: an assertion the KERNEL runs (an anonymous GET)
# or `none` — "there is no probe". A business cabinet answers an anonymous GET with the SPA shell and
# a 401 behind it, so nearly every meaningful change is honestly waived, takes a dated recheck, and
# that recheck falls due with no better instrument than the one that did not exist at closure.
#
# THE SHARPER HALF: a REAL live proof already runs at every one of those deploys and has nowhere to be
# recorded — an authenticated POST probe gated in the project's own deploy script, a headless-browser
# gate against the live origin, a served-bundle-marker fetch proving the shipped code is what
# production serves. Each is STRONGER evidence than the GET the kernel models. A project with a
# stronger proof than the kernel's must currently file "no data" for it.
#
# THE BOUND, and the whole reason this is a FORM and not a second runner: THE KERNEL GRADES WHAT THE
# PROJECT PRODUCES; IT NEVER ISSUES AN OUTBOUND REQUEST OF ITS OWN. The project runs its own
# instrument at its own gate; the kernel records the reported outcome and judges it. That keeps the
# runner GET-only/read-only exactly as SPEC-0094 §4 fixed it — the attested path issues no request at
# all, rather than issuing a wider one.
#
# THE FAILING ARM is the load-bearing half and the easy one to get backwards. `settled_by` above is
# DISCHARGE-ONLY: it says "paid", and has no way to say "the named proof ran and did NOT pass". A
# failing kernel GET likewise emits no event, by design (a failure must never write an ADOPTION
# record). So today BAD NEWS CAN ONLY BE FILED AS ABSENCE. A design that let a failed probe collapse
# into absence would be worse than the gap it closes, because permanent silence would read as health.
# Hence: a reported non-pass records `failing` — never missing, never stale — and stays on the
# overdue-recheck lens UNCONDITIONALLY, independent of any `recheck_by` date, because time is
# irrelevant to a known negative. ONLY a `passing` outcome discharges.
#
# WHAT IS REUSED, so this adds no address space: the outcome's `evidence` is the SAME
# materialized-journal locator `settled_by` uses (`_journal_locator`), resolved by the SAME matcher
# (`_journal_locator_matches`) at the SAME seam (the close-gate, the one door into the landed corpus
# the lens reads). The grammar half stays PURE, so SPEC-0094 §3 remains a STATIC declaration gate.
_ATTESTED_OUTCOME_RESULTS = ("passing", "failing")
# Which journal event type each outcome result must resolve to — EXACTLY ONE per result, and
# deliberately NOT the wider probe-evidence set `settled_by` accepts (`_LIVE_PROBE_PROBE_EVIDENCE_TYPES`).
# The two fields answer different questions and the difference is load-bearing. A `settled_by` says
# "this waiver's debt was discharged by SOME real probe", so any probe-evidence type can honestly
# discharge it. An attested `outcome` says "THIS declared instrument was run and here is what it
# read" — so it must resolve to the row THIS grading seam emitted for THIS declaration. Admitting the
# wider set would let a generic `live_trigger_evidence` or `consumer_read_evidence` row — types
# emitted for unrelated adoption reasons, often on the very same card — certify an attested reading
# that never happened, which is the named-never-asserted property collapsing into an assertion again.
# And a `passing` citing a `live_probe_failed` row (or the reverse) stays refused: a failure may never
# certify a pass, and a pass may never stand in for a reported failure.
_ATTESTED_RESULT_EVIDENCE_TYPES = {
    "passing": ("live_probe_passed",),
    "failing": ("live_probe_failed",),
}
# The declaration fields a resolving row must ECHO. Type-matching alone is not enough: a
# `live_probe_passed` row can also come from the §4 kernel GET path (no `reported` flag, no
# `attested`), and a card carrying several readings over its life would otherwise let ANY of them
# certify ANY declaration. So the row must be a REPORTED one AND name the same instrument, gate and
# assertion this card declares.
_ATTESTED_ROW_ECHOED_FIELDS = ("attested", "runs_at", "asserts")


def _live_probe_attested_outcome_grammar_error(lp, *, _is_iso_date, _journal_locator) -> "str | None":
    """Grammar half of the attested `outcome:` record (PURE — no host/journal deps, so the SPEC-0094 §3
    close-gate stays STATIC). Returns an error string when a PRESENT `outcome` is malformed, else None.
    An ABSENT `outcome` returns None: the declaration is legal before its proof has run (the close-gate
    is a DECLARATION gate, never an execution gate), and the `recheck_by` floor below carries the debt."""
    oc = lp.get("outcome")
    if oc is None:
        return None
    if not isinstance(oc, dict):
        return ("`outcome:` must be a mapping {result, evidence, probed_at} — the GRADED reading of the "
                "attested proof, recorded by `liveprobe --task T-XXXX --report pass|fail` (SPEC-0094 §4b)")
    result = oc.get("result")
    if result not in _ATTESTED_OUTCOME_RESULTS:
        return (f"`outcome.result:` must be one of {list(_ATTESTED_OUTCOME_RESULTS)} — got {result!r}. A "
                f"proof that ran and did NOT pass records `failing`; it is NEVER recorded as missing or "
                f"stale (SPEC-0094 §4b)")
    if _journal_locator(oc.get("evidence")) is None:
        ev = oc.get("evidence")
        return ("`outcome.evidence:` must be a MATERIALIZED-JOURNAL locator — `events.jsonl#ts=<ISO-instant>` "
                "or `events.jsonl#source_ref=<ref>` (the D-0030 citation form, the SAME address space "
                "`settled_by` uses). A bare `T-NNNN` or a commit sha names WORK, never the proof RUN"
                + (f"; got {ev!r}" if ev is not None else " (absent)"))
    if not _is_iso_date(oc.get("probed_at")):
        return "`outcome.probed_at:` must be an ISO date (YYYY-MM-DD) — WHEN the attested proof was run"
    detail = oc.get("detail")
    if detail is not None and not (isinstance(detail, str) and detail.strip()):
        return "`outcome.detail:` must be non-empty text when present (what the reading said)"
    return None


def _live_probe_attested_grammar_error(lp, *, _is_iso_date, _live_probe_attested_outcome_grammar_error) -> "str | None":
    """Validate the ATTESTED form (SPEC-0094 §4b). Returns an error STRING if malformed, else None.

    FORM attested — flat key `attested`:
      { attested: <instrument>, runs_at: <where it is gated>, asserts: <what it proves>,
        user_facing: <bool?>, recheck_by: <ISO-date?>,
        outcome: {result: passing|failing, evidence: <journal locator>, probed_at: <ISO>, detail: <str?>} }

    The three NAMING fields are all REQUIRED and non-empty on purpose: an attested declaration that does
    not say WHICH instrument, WHERE it is gated and WHAT it asserts is a free-text `none` waiver wearing
    a different key — which is the state this form exists to leave, not to re-spell."""
    instrument = lp.get("attested")
    if not (isinstance(instrument, str) and instrument.strip()):
        return ("an attested declaration needs a non-empty `attested:` value naming the INSTRUMENT the "
                "project itself runs (e.g. `authenticated-post-probe` / `headless-browser-gate` / "
                "`served-bundle-marker`)")
    for fld, what in (("runs_at", "WHERE the instrument is gated (e.g. `scripts/deploy.sh`)"),
                      ("asserts", "WHAT it proves live (the assertion, in the project's own terms)")):
        val = lp.get(fld)
        if not (isinstance(val, str) and val.strip()):
            return (f"an attested declaration needs a non-empty `{fld}:` — {what}. Without it the "
                    f"declaration names no gradeable proof and is a `none` waiver in a different key")
    user_facing = lp.get("user_facing", True)
    if not isinstance(user_facing, bool):
        return "`user_facing:` must be a boolean when present"
    outcome_err = _live_probe_attested_outcome_grammar_error(lp)
    if outcome_err:
        return outcome_err
    graded = lp.get("outcome") is not None
    recheck_by = lp.get("recheck_by")
    if user_facing and not graded:
        # The SAME fail-closed floor the waiver leg carries, unchanged: a declared-but-not-yet-graded
        # proof is a DATED debt. The attested form does not weaken it — what it changes is that the
        # debt now has a real exit (record the outcome) instead of a recheck with no better instrument.
        if recheck_by is None:
            return ("an UNGRADED user-facing attested declaration requires `recheck_by: <ISO-date>` — a "
                    "dated, surfaced non-adoption debt until its proof is recorded (SPEC-0094 §3 P3 "
                    "honesty floor). Record the reading with `bin/yitc-v2 liveprobe --task T-XXXX "
                    "--report pass|fail` instead of re-dating it")
        if not _is_iso_date(recheck_by):
            return "`recheck_by:` must be an ISO date (YYYY-MM-DD)"
    elif recheck_by is not None and not _is_iso_date(recheck_by):
        return "`recheck_by:` must be an ISO date (YYYY-MM-DD)"
    return None


def _live_probe_attested_result(lp, *, _live_probe_attested_outcome_grammar_error) -> "str | None":
    """Return a GRAMMAR-VALID attested outcome's `result` (`passing` / `failing`), else None.

    ONE home for the predicate — `bin/lib/views.py` imports it so the overdue lens and the close-gate
    can never drift apart (CHARTER §P5), the exact shape `_live_probe_waiver_settled` already has for
    the same reason. PURE and read-time-safe: it proves the record is WELL-FORMED, never that the
    locator RESOLVES — resolution needs the journal and lives at the close-gate."""
    if not isinstance(lp, dict) or "attested" not in lp:
        return None
    if lp.get("outcome") is None:
        return None
    if _live_probe_attested_outcome_grammar_error(lp) is not None:
        return None
    return lp["outcome"]["result"]


def _live_probe_attested_outcome_unresolved(lp, events, tid=None, *, _journal_locator, _journal_locator_matches, _live_probe_attested_outcome_grammar_error) -> "str | None":
    """RESOLUTION half — run at the CLOSE-GATE, which already reads the journal. Returns a refusal
    reason when a grammar-valid attested `outcome` does NOT resolve to a real journal row of the type
    its `result` requires, else None. PURE with INJECTED events (the caller folds worktree+main via
    `_folded_journal_events`), exactly like its `settled_by` sibling.

    TWO refusals, the same two the sibling has plus the direction check:
      (a) the locator names NO existing journal line — a made-up citation;
      (b) it resolves to a line whose type does not match the RESULT — a `passing` outcome citing a
          `live_probe_failed` row would let a failure certify a pass, and a `failing` outcome citing a
          pass row would let good news stand in for the bad news that was actually reported;
      (c) it resolves to a row belonging to ANOTHER CARD. This is the identity bound, and it is not
          hypothetical: a project's deploy gate runs the SAME instrument for every change it ships, so
          two cards routinely declare an identical `attested`/`runs_at`/`asserts` triple and would
          cross-certify on the echo check alone. `tid` is therefore REQUIRED for an attested outcome —
          absent, the check FAILS CLOSED rather than silently skipping, because an identity check that
          quietly does nothing is worse than none (it reads as enforced). The sibling
          `_live_probe_settled_evidence_unresolved` needs no tid: a settle claims only that SOME real
          probe discharged the debt, not that one particular run belongs to this card."""
    if not isinstance(lp, dict) or "attested" not in lp:
        return None
    oc = lp.get("outcome")
    if not isinstance(oc, dict):
        return None
    if _live_probe_attested_outcome_grammar_error(lp) is not None:
        return None  # the grammar half owns that refusal
    tid = str(tid or "").strip()
    if not tid:
        return ("the attested-outcome resolver was called without the card id, so the row could not be "
                "checked to belong to THIS card — refusing fail-closed rather than certifying an outcome "
                "against another card's reading (SPEC-0094 §4b identity bound)")
    loc = _journal_locator(oc.get("evidence"))
    kind, wanted = loc
    matched = _journal_locator_matches(kind, wanted, events)
    if not matched:
        return (f"`outcome.evidence` names {kind}={wanted!r}, which resolves to NO event in the journal "
                f"(worktree+main fold) — an attested outcome must cite a proof run that actually happened")
    result = oc["result"]
    wanted_types = _ATTESTED_RESULT_EVIDENCE_TYPES[result]
    typed = [ev for ev in matched if str(ev.get("type") or "") in wanted_types]
    if not typed:
        types = {str(ev.get("type") or "") for ev in matched}
        return (f"`outcome.result: {result}` cites event type(s) {sorted(t for t in types if t)} — none is "
                f"{'/'.join(wanted_types)}. A failure may never certify a pass, a pass may never stand in "
                f"for a reported failure, and a generic adoption row may not certify either; cite the row "
                f"`liveprobe --report` emitted for THIS reading")
    # The row must be a REPORTED one and must ECHO this declaration. Without this, a `live_probe_passed`
    # minted by the §4 kernel GET path — or one recorded for a DIFFERENT attested declaration on the same
    # card — would certify this outcome, and the citation would name a run that is not the one claimed.
    for ev in typed:
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        if data.get("reported") is not True:
            continue
        # IDENTITY: the row must belong to THIS card. The emit writes the id in BOTH places (`task_id`
        # on the row, `task` in the payload), and the row is this card's only if NEITHER CONTRADICTS
        # it. That is stricter than first-non-empty (`task_id or data.task`), deliberately: under
        # first-non-empty a row whose `task_id` matches while its payload `task` names a DIFFERENT card
        # is accepted, and a row that disagrees with itself about whose reading it is cannot honestly
        # certify either card. So EVERY PRESENT carrier must equal `tid`, and a row carrying NEITHER is
        # rejected rather than passed — fail-closed on absence as well as on contradiction.
        carriers = [str(v or "").strip()
                    for v in (ev.get("task_id"), data.get("task"))
                    if str(v or "").strip()]
        if not carriers or any(c != tid for c in carriers):
            continue
        if all(data.get(f) == lp.get(f) for f in _ATTESTED_ROW_ECHOED_FIELDS):
            return None
    return (f"`outcome.evidence` resolves to a {'/'.join(wanted_types)} row, but no such row is a REPORTED "
            f"attested reading for THIS card ({tid}) ECHOING this declaration (task identity, plus "
            f"reported: true, plus matching {', '.join(_ATTESTED_ROW_ECHOED_FIELDS)}). A row minted by "
            f"the kernel-GET path, one recorded for a different declaration, or one belonging to ANOTHER "
            f"card that happens to run the same instrument at the same gate, all name a run other than "
            f"the one this outcome claims — cite the row `liveprobe --report` emitted for THIS card")
# The two coordination events that mean "the item was answered": the RECEIVER's terminal and the
# AUTHOR's. A `cross_picked` says work started, never that a report-back happened, so it can settle
# nothing — this set is the whole vocabulary of a settleable coordination outcome.
_CROSS_SETTLE_EVIDENCE_TYPES = ("cross_done", "cross_closed")
# T-12322 — the types that may carry the IDENTITY link, which is a STRICTLY WIDER set than the
# ANSWERING types above and must never be conflated with them. `cross_requested` joins it because the
# item's BIRTH row carries the AUTHOR's own card when it was filed in service of one (`cross request
# --task`, T-11747) — the same named, author-written link `cross.card_tied_items` route (b) already
# trusts. It does NOT join `_CROSS_SETTLE_EVIDENCE_TYPES`: a request says an ask was FILED, never that
# anyone answered it, so admitting it as an ANSWER would let a card settle a criterion by having filed
# an item nobody ever returned — the exact false green that keeps `cross_picked` out of the set above.
_CROSS_SETTLE_NAMING_TYPES = _CROSS_SETTLE_EVIDENCE_TYPES + ("cross_requested",)


def _cross_settle_evidence_unresolved(item_id: str, tid: str, cross_events) -> "str | None":
    """RESOLUTION half for a coordination-log locator — PURE with INJECTED rows, exactly like its
    journal sibling `_settle_evidence_unresolved`, so the store's paths stay at the one seam that
    owns them. Returns a refusal reason, else None.

    THE IDENTITY BOUND — this is the load-bearing half, not the existence check. The shared store is
    IDENTITY-AGNOSTIC and every participant folds the SAME log, so resolving on item id alone would
    let ANY project's row settle ANY card's criterion: a card could cite an item another peer
    answered and call its own criterion met. The row must therefore NAME THIS TASK — `data.task` on a
    `cross_done`/`cross_closed` for that item — which is the field the receiver already writes when
    it reports back (`cross done --task T-NNNN`, and the auto-emit at close/land carries it too).

    TWO DISTINCT REFUSALS, because they are two different authoring mistakes: an item nobody has
    heard of (a typo'd / invented id) and a real item whose answer belongs to someone else.

    T-12322 — THE TWO BOUNDS ARE NOW EVALUATED SEPARATELY, which is what they always meant. They were
    collapsed into ONE row predicate ("a row that is BOTH an answer AND names this card"), and that
    collapse silently required the ANSWERING party to be the party that owns the settling card. It is
    not: `cross done --task` is the RECEIVER's card and `cross close` had no `--task` at all, so the
    AUTHOR of an item could never name its own card on any row read here (measured on T-11674 /
    X-1171, 2026-09-10). Split, the two bounds are:
      (i)  ANSWERED — some row for the item is a `cross_done`/`cross_closed`. Vocabulary UNCHANGED;
           this is the bound that keeps a merely-filed or merely-picked item from settling anything.
      (ii) NAMES THIS CARD — some row for the item carries `data.task == tid`: the answering row
           (the receiver's `cross done --task`, or the author's `cross close --task`), or the item's
           BIRTH row (`cross request --task`, the author-side link).
    The split is strictly TIGHTENING-NEUTRAL on bound (i) and only widens WHO may satisfy (ii); the
    identity bound itself is untouched, so a row belonging to a DIFFERENT card still settles nothing.
    """
    item_id = str(item_id or "").strip()
    tid = str(tid or "").strip()
    rows = [e for e in (cross_events or ())
            if isinstance(e, dict) and isinstance(e.get("data"), dict)
            and str(e["data"].get("id") or "").strip() == item_id]
    if not rows:
        return (f"--settle-evidence names cross={item_id!r}, which resolves to NO item in the shared "
                f"coordination log — a settlement must cite a coordination row that actually exists")
    answering = [e for e in rows if str(e.get("type") or "") in _CROSS_SETTLE_EVIDENCE_TYPES]
    naming = [e for e in rows
              if str(e.get("type") or "") in _CROSS_SETTLE_NAMING_TYPES
              and str(e["data"].get("task") or "").strip() == tid]
    if not answering or not naming:
        answered = sorted({str(e.get("type") or "") for e in rows
                           if str(e.get("type") or "") in _CROSS_SETTLE_EVIDENCE_TYPES})
        # ONE message naming WHICH bound failed. Both halves are reported on every refusal rather
        # than short-circuiting on the first: an author who reads only "not answered" would report
        # back and then hit the identity refusal on the very next run, which is two round trips for
        # one authoring mistake.
        return (f"--settle-evidence names cross={item_id!r}, but no "
                f"{'/'.join(_CROSS_SETTLE_EVIDENCE_TYPES)} row for that item NAMES this task ({tid}) "
                f"— the shared store is identity-agnostic and every peer folds the same log, so a row "
                f"that does not name this card proves nothing about it. TWO bounds must BOTH hold: "
                f"ANSWERED = {'yes' if answering else 'NO — nothing has answered this item yet'}; "
                f"NAMES THIS CARD = {'yes' if naming else 'NO'} (rows seen for the item: "
                f"{', '.join(answered) if answered else 'none of those types'}). The RECEIVER names "
                f"its card with `cross done {item_id} --task <its T-NNNN> --note <what shipped>`; "
                f"YOU, as the item's AUTHOR, name YOUR OWN card with `cross close {item_id} --task "
                f"{tid}` (admitted as an idempotent naming amend when the item is already closed). "
                f"Then settle")
    return None


def _settle_probe_admission_error(task: dict, ac: str, result: str, *, _SETTLE_TERMINAL_RESULTS) -> "str | None":
    """FAIL-CLOSED admission for ONE settlement (AC3 leg 1). Returns the refusal reason, else None.

    Three refusals, each a way a settlement would be dishonest:
      (a) the card has no such probe key — settling invents a criterion the closure never recorded;
      (b) the recorded result is NOT `deferred` — this is the no-back-dating guard: it refuses both
          painting a `pass`/`fail` criterion green after the fact AND silently re-settling an
          already-settled one behind different evidence;
      (c) the result is neither `pass` NOR one of the two honest NON-PASS TERMINALS
          (`_SETTLE_TERMINAL_RESULTS`) — i.e. `fail` stays refused, and its refusal now ROUTES.

    T-11657 NARROWED (c), and the narrowing is exact. It used to refuse EVERY non-`pass` result on the
    ground that a done card carries `probe_passed: true` (QUEUE §Done log), so recording a failing
    deferred probe would quietly break that invariant. That reasoning is unchanged FOR `fail` — a bare
    `fail` asserts the criterion was tested and did not hold, with nothing recorded about why, which is
    indeed new work rather than a settlement. But it over-reached: it also refused the two cases where
    the criterion will NEVER be proven and saying so IS the honest record — `unreachable` (the proof
    can never arrive) and `falsified` (a reading arrived and came back negative). Both are admitted
    here, each with a MANDATORY free-text reason enforced upstream in `_parse_settle_pairs`, and
    NEITHER claims the criterion passed — so the `probe_passed` invariant the old (c) protected is not
    weakened by them: the stored field is untouched, and a terminal is by its own definition not a
    pass-claim. Refusals (a) and (b) are UNTOUCHED, which is what stops a terminal being re-settled
    behind a different reason later (only a `deferred` probe is settleable, ever)."""
    probes = task.get("probes")
    if not isinstance(probes, dict) or ac not in probes:
        known = ", ".join(sorted(probes)) if isinstance(probes, dict) and probes else "(none recorded)"
        return (f"probe key {ac!r} is not in this card's recorded probes — a settlement records the "
                f"result of a criterion the CLOSURE deferred, it cannot introduce a new one. "
                f"Recorded probe key(s): {known}")
    recorded = str(probes.get(ac) or "").strip()
    if recorded != "deferred":
        return (f"probe {ac!r} is recorded {recorded!r}, not 'deferred' — only a DEFERRED probe can be "
                f"settled (no back-dating: this refuses painting a criterion green after the fact, and "
                f"refuses re-settling an already-settled one behind different evidence). If the "
                f"recorded result is wrong, that is new work — file a task (a landed done card has no "
                f"reopen, LIFECYCLE §Stage 9).")
    if result != "pass" and result not in _SETTLE_TERMINAL_RESULTS:
        return (f"probe {ac!r} cannot be settled {result!r} — a done card carries `probe_passed: true` "
                f"(QUEUE §Done log), so recording a bare failing deferred probe here would silently "
                f"break that invariant. A deferred criterion that turned out NOT to hold is new work: "
                f"file a task (a landed done card has no reopen, LIFECYCLE §Stage 9). If the reading "
                f"ARRIVED and came back negative, that is `falsified` WITH a --settle-reason, not "
                f"{result!r}; if the proof can never arrive at all, that is `unreachable` WITH a "
                f"--settle-reason (T-11657).")
    return None


def _settle_evidence_unresolved(locator: str, events, *, cross_events=None,
                                tid: str = None, flag: str = "--settle-evidence", _cross_settle_evidence_unresolved, _cross_settle_locator, _journal_locator, _journal_locator_matches) -> "str | None":
    """RESOLUTION half (AC3 leg 2) — PURE with INJECTED events, so it stays unit-testable and the
    host binding (the worktree+main journal fold) lives at the one seam that owns paths, exactly like
    the `_live_probe_settled_evidence_unresolved` sibling. Returns a refusal reason, else None.

    DELIBERATELY NOT type-restricted, unlike that sibling: this card's whole family is the SPEC-0036
    variant-(d) ship whose acceptance event is an ARBITRARY land-emitted type. Restricting the
    resolved row's TYPE here would be a ruling on what counts as substantive evidence — explicitly
    out of scope for T-11107. What IS enforced is that the citation is real: a locator naming no
    journal line at all is a made-up citation and is refused.

    T-11297 — this is THE settlement resolver for BOTH stores. A `coordination.jsonl#cross=X-NNNN`
    locator dispatches to `_cross_settle_evidence_unresolved` over the INJECTED shared-store rows
    (`cross_events`) and the closing task id (`tid`), which the caller supplies from the store's one
    reader; every other locator takes the journal branch below, unchanged. Adding the branch HERE
    rather than beside this function is the AC4 bound: one entry point, one grammar home, and the
    journal fold untouched.

    T-13416 — `flag` names the argument the locator arrived through, so the same resolver words its
    refusal for the verb that ran (`work commit --from`, not `--settle-evidence`)."""
    xid = _cross_settle_locator(locator)
    if xid is not None:
        # T-11297 — the COORDINATION-LOG kind. ONE entry point, dispatching on which STORE the
        # locator addresses; the fork is over injected corpora, never a second evidence path (AC4).
        # FAIL-CLOSED on a caller that did not inject that corpus: an unverifiable citation is
        # exactly the false-green this whole path exists to refuse (the `_settle_evidence_unresolved_host
        # is None` posture at the call site, applied one level in).
        if cross_events is None or not str(tid or "").strip():
            return ("--settle-evidence names a coordination-log locator, but this caller wired no "
                    "shared-store corpus / no closing task id, so the row could not be resolved. "
                    "Refusing fail-closed rather than recording an unverified citation (T-11297)")
        return _cross_settle_evidence_unresolved(xid, tid, cross_events)
    loc = _journal_locator(locator)
    if loc is None:
        return None  # grammar half owns that refusal (_parse_settle_pairs, before any write)
    kind, wanted = loc
    matched = _journal_locator_matches(kind, wanted, events)
    if not matched:
        return (f"{flag} names {kind}={wanted!r}, which resolves to NO event in the journal "
                f"(worktree+main fold) — a citation must name a journal row that actually exists")
    if kind == "ts" and len(matched) > 1:
        return _ts_locator_ambiguity(wanted, matched, tid, flag=flag)
    return None


# T-13416 — rows a ts= citation never means: per-invocation receipts the CLI writes in the same
# second as the row being cited (an owner_directive and its `cli_invoked` receipts share a second).
_TS_RECEIPT_TYPES = ("cli_invoked",)


def _ts_locator_ambiguity(wanted: str, matched, tid, flag: str = "--settle-evidence") -> "str | None":
    """T-13342 (X-1843) — a `ts=` pin is second-granularity, so two rows emitted in the same second
    share it (measured: <project> T-0784/T-0785 acceptance_probe rows at 2026-10-01T10:15:19Z). It
    still resolves when EXACTLY ONE of the rows ties to the closing card (`_event_task_id`, the one
    tie reader); zero or several ties is a citation that names no single row, so it is refused with
    the unambiguous form: a `source_ref=` locator, which the emitter chooses and so cannot collide.

    T-13416 — receipt rows (`_TS_RECEIPT_TYPES`) are not candidates: when exactly ONE citable row
    shares the second the locator names it (the handbook's `events.jsonl#ts=` owner-row form, cited
    from a filing batch with no closing card). Two citable rows still fall to the tie rule above."""
    citable = [r for r in matched if r.get("type") not in _TS_RECEIPT_TYPES]
    if len(citable) == 1:
        return None
    tid = str(tid or "").strip()
    tied = [r for r in citable if tid and _event_task_id(r) == tid]
    if len(tied) == 1:
        return None
    rows = "; ".join(f"{r.get('type')}({_event_task_id(r) or 'no task'})" for r in citable)
    alt = (f"re-emit the evidence as its own row with a unique source_ref (`bin/yitc-v2 event <type> "
           f"--task {tid or 'T-XXXX'} --source-ref <unique-ref>`) and cite "
           f"`events.jsonl#source_ref=<unique-ref>`")
    return (f"{flag} names ts={wanted!r}, which is AMBIGUOUS — it matches {len(citable)} citable "
            f"journal rows [{rows}] and {len(tied)} of them tie to {tid or 'the closing card'}, so the "
            f"citation names no single row (T-13342). Cite an unambiguous locator instead: {alt}")


def _live_probe_declaration_error(lp, *, _is_iso_date, _live_probe_attested_grammar_error, _live_probe_settled_grammar_error, _security_dialect_error) -> "str | None":
    """Validate a PRESENT `live_probe` against the SPEC-0094 §3/§4 + SPEC-0028 grammar. Returns an error
    STRING if malformed, else None. ABSENCE is not handled here (the deploying-project presence
    requirement is the close-gate's job). THREE mutually-exclusive forms. `assertion` / `waiver` /
    `escalation` are FORM NAMES, not mapping keys — there is NO nesting level: every key sits FLAT in
    `lp`, and the FLAT key named below is the one this function discriminates on (T-11243 / X-0972):
      FORM assertion  — flat key `url`:          { url: <str>, expect_status: <int>, body_contains: <str?> }
                  # GET vs carrier live_base_url
                  + the OPTIONAL SPEC-0098 §1 security DIALECT (property + assert_header_present/absent /
                    assert_cookie_flags) — a security assertion proves a named security property at the seam.
      FORM waiver     — flat key `none`:         { none: <reason-str>, user_facing: <bool?>, recheck_by: <ISO-date?> }
      FORM attested   — flat key `attested`:     { attested: <instrument>, runs_at: <str>, asserts: <str>,
                                                   user_facing: <bool?>, recheck_by: <ISO-date?>,
                                                   outcome: {result, evidence, probed_at, detail?} }
                  # SPEC-0094 §4b — a live proof the PROJECT itself runs at its own gate. The kernel
                    GRADES the reported outcome and never issues an outbound request of its own.
      FORM escalation — flat key `unprobeable`:  { property: <str>, unprobeable: <reason-str> }
                  # SPEC-0098 §2 — un-probeable read-only →
                    escalate to owner (never silent-pass); the runner emits security_live_probe_escalated.
    Fail-closed on user-facing: an OMITTED `user_facing` on a waiver reads as user-facing, so `recheck_by`
    is REQUIRED unless `user_facing: false` is explicit (SPEC-0094 §3 P3 honesty floor)."""
    if not isinstance(lp, dict):
        return ("must be a mapping, with its keys FLAT one level under `live_probe:` — e.g. "
                "`live_probe: {url: /health, expect_status: 200}`. `assertion` / `waiver` / "
                "`escalation` are FORM NAMES, never keys to nest under (T-11243 / X-0972)")
    is_waiver = "none" in lp
    is_assertion = "url" in lp
    is_escalation = "unprobeable" in lp
    is_attested = "attested" in lp
    if sum((is_waiver, is_assertion, is_escalation, is_attested)) > 1:
        return ("carries more than one of `url` (assertion) / `none` (waiver) / `attested` (project-run "
                "proof) / `unprobeable` (escalation) — they are mutually exclusive")
    if is_assertion:
        url = lp.get("url")
        if not (isinstance(url, str) and url.strip()):
            return "assertion needs a non-empty `url:` (a path joined to the carrier live_base_url, or absolute)"
        es = lp.get("expect_status")
        if not isinstance(es, int) or isinstance(es, bool):
            return "assertion needs an integer `expect_status:`"
        bc = lp.get("body_contains")
        if bc is not None and not isinstance(bc, str):
            return "`body_contains:` must be a string when present"
        # No-follow / redirect dialect (SPEC-0094 §4): an OPTIONAL `expect_location` asserts the
        # `Location` header of an IMMEDIATE redirect (the runner stops following). It is meaningful
        # ONLY for an actual Location-bearing redirect status, so it REQUIRES an `expect_status` in
        # the redirect set {301,302,303,307,308} — a 304/300/305/306 is not a redirect target.
        el = lp.get("expect_location")
        if el is not None:
            if not (isinstance(el, str) and el.strip()):
                return "`expect_location:` must be a non-empty string when present"
            if es not in _REDIRECT_STATUSES:
                return (f"`expect_location:` requires a redirect `expect_status:` in "
                        f"{sorted(_REDIRECT_STATUSES)} (it asserts the Location header of an immediate "
                        f"redirect, the SPEC-0094 §4 no-follow dialect); got {es}")
        return _security_dialect_error(lp)
    if is_attested:
        # SPEC-0094 §4b — a live proof the PROJECT already runs (an authenticated probe, a headless-browser
        # gate, a served-bundle marker). The kernel GRADES its reported outcome; it issues no request.
        return _live_probe_attested_grammar_error(lp)
    if is_escalation:
        # SPEC-0098 §2 un-probeable→escalate form: a NAMED property the seam cannot assert read-only.
        prop = lp.get("property")
        if not (isinstance(prop, str) and prop.strip()):
            return "an `unprobeable` escalation needs a non-empty `property:` name (the security property that cannot be asserted read-only, SPEC-0098 §2)"
        reason = lp.get("unprobeable")
        if not (isinstance(reason, str) and reason.strip()):
            return "`unprobeable:` needs a non-empty reason string (why the property is not assertable by a read-only GET, SPEC-0098 §2)"
        return None
    if is_waiver:
        # `none:` carries the reason text directly (the documented single form — one SoT, no parallel
        # `reason:` key, audit-post). Must be a non-empty string.
        none_val = lp.get("none")
        if not (isinstance(none_val, str) and none_val.strip()):
            return "waiver needs a non-empty reason as the `none:` value (e.g. `none: <why no probe>`)"
        user_facing = lp.get("user_facing", True)
        if not isinstance(user_facing, bool):
            return "`user_facing:` must be a boolean when present"
        # T-10750 (X-0575) — the SETTLED discharge. Validate a PRESENT `settled_by` FIRST; only a
        # grammar-VALID one drops the `recheck_by` requirement below. A malformed `settled_by` is a
        # grammar ERROR, never a silent settle — so the fail-closed floor can only be left through the
        # honest door, and an ABSENT `settled_by` leaves this branch byte-for-byte as it was.
        settled_err = _live_probe_settled_grammar_error(lp)
        if settled_err:
            return settled_err
        settled = lp.get("settled_by") is not None
        recheck_by = lp.get("recheck_by")
        if user_facing and not settled:
            if recheck_by is None:
                return ("a USER-FACING `none` waiver requires `recheck_by: <ISO-date>` — a dated, surfaced "
                        "non-adoption debt (SPEC-0094 §3 P3 honesty floor); set `user_facing: false` only "
                        "for a change with no live surface. If the debt was ACTUALLY discharged by a real "
                        "non-GET probe, record `settled_by: {evidence: events.jsonl#ts=<ISO>, probed_at: "
                        "<ISO-date>, method: <how>}` instead of re-dating it")
            if not _is_iso_date(recheck_by):
                return "`recheck_by:` must be an ISO date (YYYY-MM-DD)"
        elif recheck_by is not None and not _is_iso_date(recheck_by):
            return "`recheck_by:` must be an ISO date (YYYY-MM-DD)"
        return None
    return ("names no form. The form is SELECTED by a FLAT top-level key of `live_probe:` — `url:` "
            "(assertion), `none:` (waiver), `attested:` (a live proof the project itself runs) or "
            "`unprobeable:` (escalation); `assertion` / `waiver` / "
            "`escalation` are FORM NAMES, never keys to nest under, so there is NO nesting level here. "
            "Flat example: `live_probe: {url: /health, expect_status: 200}` — NOT "
            "`live_probe: {assertion: {url: ...}}` (T-11243 / X-0972)")


def _post_ship_observation_declaration_error(pso, *, _SETTLE_TERMINAL_RESULTS, _is_iso_date) -> "str | None":
    """Validate a PRESENT `post_ship_observation:` against the SPEC-0028 / SPEC-0036 grammar (T-10916 /
    X-0710). Returns an error STRING if malformed, else None; ABSENCE is not handled here (the
    `--post-ship-observation` overlay guard owns the presence requirement).

    ONE form — a DEFERRED PROOF, dated:
      { observation: <what will be observed, non-empty>, due_by: <ISO date the window closes>,
        settled_by: <locator naming where the proof landed — OPTIONAL, added when RECORDED> }

    This is the EIGHTH deferred-adoption variant's carrier and the reason the overlay is not a blanket
    excuse: an overlay that defers a proof without naming WHERE the proof lands is how deferred
    adoption turns into never-adopted, so both the WHAT (`observation`) and the WHEN (`due_by`) are
    REQUIRED — a card that names neither cannot take the carve-out at all. `settled_by` is the
    discharge (`_post_ship_observation_settled`), mirroring the `live_probe` waiver's settle.

    `sensitivity:` (T-11672 / X-1126) is OPTIONAL and is DELIBERATELY NOT VALIDATED HERE — read it via
    `_post_ship_observation_sensitivity` below. It carries the evidence that the observation's predicate
    FIRES when the defect IS present, and the requirement to name it is a DISCIPLINE surfaced as a
    report-only PROMPT at the declaring seam, never a grammar rule: validating it here would make this
    function refuse a declaration for omitting or malforming it, which is exactly the gate the card that
    added the key excluded (CHARTER non-goals #2/#7). Unknown keys were already tolerated by this
    validator, so the addition changes no verdict this function has ever returned."""
    if not isinstance(pso, dict):
        return ("must be a mapping — {observation: <what will be observed>, due_by: <ISO date>} "
                "(+ optional `settled_by:` once the observation is RECORDED)")
    obs = pso.get("observation")
    if not (isinstance(obs, str) and obs.strip()):
        return ("needs a non-empty `observation:` — the concrete post-ship reading that will prove the "
                "acceptance (e.g. 'the daily error count is flat or falling over 7 days')")
    due_by = pso.get("due_by")
    if due_by is None:
        return ("needs `due_by: <ISO-date>` — the date the observation window closes. A deferred proof "
                "with no due window is an undated debt, which is how deferred adoption becomes "
                "never-adopted (T-10916 / X-0710)")
    if not _is_iso_date(due_by):
        return "`due_by:` must be an ISO date (YYYY-MM-DD)"
    settled_by = pso.get("settled_by")
    # T-11950 — TWO DISCHARGE SHAPES, forked on TYPE, exactly as the `live_probe` sibling forks on the
    # presence of a `result:` key (`_live_probe_settled_grammar_error`, T-11748): a STRING is the
    # LOCATOR naming where the recorded reading landed (T-11529, judged byte-for-byte as before); a
    # MAPPING is the TERMINAL pair {result, reason} recording that no reading can arrive, or that one
    # arrived NEGATIVE. ONE CARRIER, NO NEW ADDRESS SPACE — the terminal is a shape of the SAME field
    # the lens, the overlay guard, the audit prompt and both write legs already read, which is what
    # keeps the discharge keyed on the value the settle itself writes rather than on a parallel marker
    # that could drift from it. The VOCABULARY is `_SETTLE_TERMINAL_RESULTS` READ, never restated: the
    # two terminals mean the same thing on all three carriers (probe / waiver / observation), so a
    # fourth spelling would be the parallel path CHARTER §P1 F1 forbids.
    if isinstance(settled_by, dict):
        result = settled_by.get("result")
        if result not in _SETTLE_TERMINAL_RESULTS:
            return (f"`settled_by.result:` must be one of {list(_SETTLE_TERMINAL_RESULTS)} — "
                    f"`unreachable` (the reading can NEVER arrive) or `falsified` (a reading ARRIVED "
                    f"and came back negative). Got {result!r}. A discharge that is neither a named "
                    f"locator nor one of these two terminals records nothing (T-11950)")
        reason = settled_by.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            return (f"`settled_by.reason:` must be non-empty text — a {result!r} terminal records that "
                    f"this observation will never be read (or that its reading was negative), and WHY "
                    f"is the ENTIRE content of that record. An empty reason discharges the debt while "
                    f"saying nothing")
        return None
    if settled_by is not None and not (isinstance(settled_by, str) and settled_by.strip()):
        return ("`settled_by:` must be either a non-empty LOCATOR string naming where the recorded "
                "observation landed (e.g. `events.jsonl#ts=<ISO>`) or the TERMINAL pair "
                "{result, reason} recording that no such reading can arrive (T-11950)")
    return None


def _post_ship_observation_settled(pso, *, _post_ship_observation_declaration_error) -> bool:
    """TRUE iff `pso` is a GRAMMAR-VALID post-ship-observation declaration carrying a `settled_by` — the
    DISCHARGED state (T-10916). ONE home for the predicate — `bin/lib/views.py` imports it so the debt
    lens and the overlay guard can never drift (CHARTER §P5). PURE and read-time-safe: it proves the
    marker is WELL-FORMED, never that the locator RESOLVES (the same split the `live_probe` settle
    draws — resolution needs the journal and belongs at a gate, not at a read-time lens)."""
    if not isinstance(pso, dict) or pso.get("settled_by") is None:
        return False
    return _post_ship_observation_declaration_error(pso) is None


def _post_ship_observation_settled_terminal(pso, *, _SETTLE_TERMINAL_RESULTS) -> "str | None":
    """Return the TERMINAL result of an observation's `settled_by` (unreachable|falsified), else None
    (T-11950). The verbatim sibling of `_live_probe_settled_terminal` one carrier over.

    THE one home of the predicate (CHARTER §P5) — the debt lens and the authoring leg both read it, so
    they can never drift on what counts as a terminal. PURE. Returns the raw declared result whenever
    `settled_by.result` is a member of the vocabulary; it does NOT re-judge the reason (that is
    `_post_ship_observation_declaration_error`'s refusal), so a caller wanting a VALID terminal pairs
    this with that grammar check exactly as the lens does."""
    if not isinstance(pso, dict):
        return None
    sb = pso.get("settled_by")
    if not isinstance(sb, dict):
        return None
    result = sb.get("result")
    return result if result in _SETTLE_TERMINAL_RESULTS else None


# T-12733 (<project> X-1491) — the ONE home mapping each DECLARABLE `post_ship_observation` key to the
# `task update` flag that WRITES it. Two seams read it and neither restates it (CHARTER §P5 — the
# T-12725 rule: a judgement two seams read is homed once): the report-only sensitivity prompt in
# `bin/lib/cli.py#_require_post_ship_observation` names its remedy FROM this map (so the prompt can
# never again name a field no verb writes — the defect X-1491 measured: it told the operator to hand
# edit the card, which the verb-execution discipline forbids), and the AC2 test asserts every key the
# prompt names is a member AND its flag is registered on the real `task update` parser. `settled_by`
# is deliberately ABSENT: it is a DISCHARGE, not a declaration — written by `task close
# --settle-observation`, never by `task update`.
POST_SHIP_OBSERVATION_FLAGS = {
    "observation": "--observation",
    "due_by": "--observation-due",
    "sensitivity": "--observation-sensitivity",
}


def _post_ship_observation_sensitivity(pso) -> str:
    """The declared SENSITIVITY evidence of a `post_ship_observation:` — the historical proof that its
    predicate FIRES when the defect IS present — stripped, or "" when none is declared (T-11672 / X-1126).

    ONE read-home for the key, so the two consumers cannot drift (CHARTER §P5): the declaring seam
    `bin/lib/cli.py#_require_post_ship_observation` (which prints the report-only prompt on "") and the
    SPEC-0036 variant-(e) overlay in `bin/lib/audit.py#_build_audit_prompt` (which names the evidence to
    the auditor). `audit.py` reads it through the EXISTING function-local `from lib.task import ...` it
    already uses for this same field family — `task.py` imports `audit.py` at module level, so the
    reverse import stays lazy and the direction is unchanged.

    PURE and read-time-safe, and it JUDGES NOTHING: a non-dict, a missing key, a non-string and a
    whitespace-only value all answer "" — the same answer as an honest omission. That is deliberate.
    This accessor is the read side of a DISCIPLINE, not of a validator: nothing downstream refuses on
    what it returns, so it has no failure mode to report and no reason to raise."""
    if not isinstance(pso, dict):
        return ""
    val = pso.get("sensitivity")
    return val.strip() if isinstance(val, str) else ""


def _post_ship_observation_settle_locator_error(locator, *, _journal_locator) -> "str | None":
    """GRAMMAR half of the settle (PURE — no host/journal deps, the split
    `_live_probe_settled_grammar_error` draws). Returns a refusal when `locator` is not a
    MATERIALIZED evidence locator, else None. Resolution is the caller's second half.

    The address space is the EXISTING `_journal_locator` (the D-0030 citation form) — reused, never a
    second one (CHARTER §P1 F1 / §P5). It is the JOURNAL half of that space only; the T-11297
    coordination-log form is deliberately NOT admitted here (see the note below the return)."""
    if not (isinstance(locator, str) and locator.strip()):
        return ("`--settle-observation` needs a non-empty evidence locator naming WHERE the recorded "
                "observation landed")
    loc = locator.strip()
    if _journal_locator(loc) is not None:
        return None
    # SCOPED TO THE JOURNAL, deliberately (CHARTER §P1 F4). The T-11297 coordination-log locator kind
    # exists for a cross-project report-back, which is a measured need for an acceptance criterion and
    # is NOT one here: a post-ship observation is a reading taken off THIS project's own production and
    # recorded in THIS repo's journal, and no incident names an observation settled from the shared
    # store. Admitting the form on speculation would also put a SECOND reader of that store in this
    # verb, which the T-11297 AC4 bound exists to prevent. Deferred, not forgotten — the address space
    # is shared, so the day a real case appears the form is one call away.
    return (f"--settle-observation {loc!r} must name a MATERIALIZED evidence row — "
            f"`events.jsonl#ts=<ISO-instant>` or `events.jsonl#source_ref=<ref>` (the D-0030 citation "
            f"form). A bare `T-NNNN`, a decision id or a commit "
            f"sha names WORK, never the READING — and a post-ship observation's entire claim is that a "
            f"reading was actually taken, so an id-shaped citation would settle the debt by assertion "
            f"(T-11529). Nothing was written.")
#: T-10975 — the main-side statuses a GENUINELY unlanded closure can leave behind. An ALLOWLIST, never
#: a "not done" denylist (audit-pre pass-1 HIGH): `ready` is the canonical shape (the claim itself is
#: branch-local until `land`, T-0124/D-0037, so main still reads ready), and `in-progress` is the
#: legitimately multi-land task (an earlier land integrated the claim or a pause/park bookkeeping
#: commit, but NOT the closure). Everything else — `done` (LANDED), `parked`/`wont-do` (a terminal
#: decision that DID reach main), a missing/unknown value — stays out, fail-closed.
_UNLANDED_CLOSURE_MAIN_STATUSES = ("ready", "in-progress")


def _closure_is_unlanded(tid: str, task_path: "Path", *, REPO_ROOT, _run_git_cap, _card_status_on_main) -> bool:
    """T-10975 — DETERMINE (never accept an assertion) whether this task's `done` closure is still
    branch-local, i.e. never reached `main`.

    The distinction is load-bearing, not cosmetic: a done-but-UNLANDED card may be reworked in place
    (QUEUE §Prematurely-closed), while a card whose closure LANDED has NO reopen at all — that is a
    NEW task (LIFECYCLE §Stage 9, T-0367 / T-10110). The prior post-close carve-outs (T-9412 /
    T-10094 / T-10507) gate on `status: done` alone and let the CALLER assert unlanded-ness with a
    flag; this predicate is what lets the ADMISSION itself be derived, so an over-broad fix that keys
    only on `status == done` cannot pass (the card's ATOM 2).

    Derived from git, no new marker — the same `main:<rel>` read `_require_batch_born` (T-0590 2b)
    already uses, extended from "is it on main at all" to "what does main SAY". FAIL-CLOSED in every
    undeterminable direction (unlike `_require_batch_born`, which fails OPEN): a state we cannot read
    is treated as LANDED, because the cost of wrongly admitting is reopening a shipped task while the
    cost of wrongly refusing is one clear message pointing at a new task. Never raises.

    T-12328 — the `main:<rel>` READ itself now lives ONCE in `_card_status_on_main` below, because a
    SECOND predicate (`_closure_is_on_main`) reads the same state pointed the other way. Two copies of
    one git read is exactly the drift CHARTER §P5 forbids; the fail-closed POSTURE stays per-predicate,
    since "undeterminable" resolves to the safe answer in OPPOSITE directions for the two of them."""
    status, determinable = _card_status_on_main(task_path, REPO_ROOT=REPO_ROOT,
                                                _run_git_cap=_run_git_cap)
    if not determinable:
        return False                       # undeterminable — fail-closed: treat as LANDED
    if status is None:
        return True                        # absent from main: batch-born, the closure never landed
    return status in _UNLANDED_CLOSURE_MAIN_STATUSES


def _card_status_on_main(task_path: "Path", *, REPO_ROOT, _run_git_cap) -> "tuple[str | None, bool]":
    """T-12328 — the ONE reader of what `main` SAYS about a card. Returns `(status, determinable)`:

      * `(None, True)`   — `main` is readable and the card is ABSENT from it (batch-born).
      * `(<status>, True)` — `main` is readable and the card is there carrying that status
                             (`""` when the card parses but names no status).
      * `(None, False)`  — the state could NOT be read: path outside REPO_ROOT, no `main` ref, a git
                           or parse failure, or a card that does not parse to a mapping.

    Extracted from `_closure_is_unlanded` (T-10975) UNCHANGED so its two callers cannot drift
    (CHARTER §P5). It reports determinability rather than deciding it, deliberately: the two
    predicates over it fail closed in OPPOSITE directions — `_closure_is_unlanded` reads an unreadable
    state as LANDED (refusing to reopen a possibly-shipped card), `_closure_is_on_main` reads the same
    state as NOT-on-main (refusing to write onto a card whose landing it cannot prove). A single
    boolean here would have to pick one of those and would be wrong for the other. Never raises."""
    try:
        rel = str(task_path.relative_to(REPO_ROOT))
    except (ValueError, AttributeError, TypeError):
        return None, False                 # path outside REPO_ROOT (sandbox) — undeterminable
    try:
        if _run_git_cap(["rev-parse", "--verify", "--quiet", "main"], REPO_ROOT).returncode != 0:
            return None, False             # no `main` ref (non-git / unborn) — undeterminable
        r = _run_git_cap(["show", f"main:{rel}"], REPO_ROOT)
        if r.returncode != 0:
            return None, True              # readable main, card ABSENT from it
        on_main = state.load_str(r.stdout)
    except Exception:
        return None, False                 # any git/parse failure — undeterminable
    if not isinstance(on_main, dict):
        return None, False
    return str(on_main.get("status") or ""), True


def _closure_is_on_main(task_path: "Path", *, REPO_ROOT, _run_git_cap, _card_status_on_main) -> bool:
    """T-12328 — DETERMINE (never accept an assertion) whether this card's `done` CLOSURE has LANDED,
    i.e. `main` itself says `done`. The MIRROR of `_closure_is_unlanded` over the one shared reader.

    This is the admission of `task close --settle-live-probe-attested`, and it is NOT the negation of
    its sibling: `not _closure_is_unlanded(...)` is True for a LANDED card AND for an UNDETERMINABLE
    one, because that predicate's fail-closed direction protects a DIFFERENT act (never reopen a card
    that might have shipped). Here the protected act is the opposite — writing a governed declaration
    onto a card on the strength of its landing — so an unreadable state must REFUSE, not admit. Using
    the negation would have inverted the safety of every undeterminable case.

    FAIL-CLOSED in every undeterminable direction: no `main` ref, a git or parse failure, a path
    outside REPO_ROOT, or a card absent from `main` all read as NOT landed. Never raises."""
    status, determinable = _card_status_on_main(task_path, REPO_ROOT=REPO_ROOT,
                                                _run_git_cap=_run_git_cap)
    return bool(determinable and status == "done")


def _live_worktree_notice(tid: str, *, REPO_ROOT, _live_task_worktrees) -> "str | None":
    """The AC2 advisory for ONE card: a live `task/<tid>` worktree exists elsewhere, so the state
    may be newer there. None when there is no such worktree, or when that worktree IS this checkout
    (reading your own card must not warn you about yourself).

    AC3 BOUND, deliberate: this reads the worktree LIST only — never the other checkout's card. It
    reports that a newer copy MAY exist, never what that copy says. Reading across checkouts would
    trade a stale answer for a dependency on a file this verb does not own, in a checkout that may
    be mid-write. Fail-open: `_live_task_worktrees` returns {} on git error by design (T-0566)."""
    try:
        wt = (_live_task_worktrees() or {}).get(tid)
    except Exception:  # noqa: BLE001 — advisory, mirrors the fail-OPEN posture of its source
        return None
    if wt is None:
        return None
    try:
        if Path(wt).resolve() == Path(REPO_ROOT).resolve():
            return None
    except OSError:
        pass
    return (f"  live worktree: {wt} — this card is claimed there and its state may be NEWER than the "
            f"view above; the claim/stage lands from that worktree (not read here — SPEC-0060).")


def _case_out_of_path_observation(case, ship_paths, *, _case_valid) -> "dict | None":
    """SPEC-0178 rule 6 — the OUT-OF-PATH observation for a `paths:`-declared audit_scrutiny case.
    REPORT-ONLY by construction: a PURE f(case, ship_paths) → one report row, or None when there is
    nothing to surface. It never gates, never refuses, never raises, and touches no git/disk (AC3).

    **WHICH DIFF — the SHIP diff ONLY, and deliberately NOT rule 3's boundary (trial cycle 18).**
    `ship_paths` is the card's SHIP diff (`_task_diff_files(<recorded sha>)` at the Closure seam,
    where the closure-record commit does not exist yet). Rule 3 reads the ship diff PLUS the
    governance writes `task close` is itself about to make, because it guards SAFETY; rule 6 shows a
    reviewer the scope the AUTHOR chose, so a write the author did not make is not evidence about
    their declaration. Cycle 12 measured 26 of 28 closure-commit governance writes to be `task
    close`'s OWN (the `proposed → active` activation) — a rule 6 reading rule 3's diff would flag
    nearly every spec-activating card under a `paths:` case for something nobody wrote, i.e. noise in
    exactly the population the observation exists to inform. The differential probe (VP7 / AC1) holds
    this: a SHIP-diff escape surfaces, a closure-only governance write does not.

    Returns None (nothing surfaced) when:
      (a)+(b) the case does not APPLY at all — not a mapping, no non-empty `case:` name, or a
          missing/empty `reason:` (rule 1). Delegated to `_case_valid`, the ONE home for that
          question since T-11156 (the checks were inlined here when this was the only reader).
          Applicability ONLY: a case `_case_declaration_refusal` rejects is still OBSERVED here —
          rule 6 reports what a declaration covered, it does not adjudicate the declaration.
      (c) it declares no usable `paths:` (a list of non-empty strings) — rule 6's stated ASYMMETRY:
          a `class:`-only case computes NO observation, because no class-to-path source of truth
          exists and none is invented here (AC2);
      (d) the ship diff does not intersect the declared paths at all — the card is not read under
          that case;
      (e) every ship-diff path is inside the declared paths — the declaration held, nothing to report.
    Otherwise returns {"case", "declared_paths", "out_of_path"} — the reviewer-facing evidence for a
    rule 7 proposal to NARROW the declaration.

    Glob matching REUSES the existing fnmatch idiom of `_subject_globs_would_skip` (SPEC-0152 rule 16,
    `bin/lib/worktree.py`): a `*` crosses `/`, and a leading `./` is normalised to the repo-relative
    form the globs are written in. No new matcher (CHARTER §P1 filter 1)."""
    ok, _why = _case_valid(case)          # T-11156: rule-1 applicability has ONE home (P5)
    if not ok:
        return None
    name = case.get("case")
    match = case.get("match")
    globs = match.get("paths") if isinstance(match, dict) else None
    if not (isinstance(globs, list) and globs
            and all(isinstance(g, str) and g.strip() for g in globs)):
        return None                       # class-only (or malformed) — NOT computed, rule 6
    globs = [g.strip() for g in globs]

    inside, outside = [], []
    for raw in (ship_paths or []):
        p = str(raw).strip()
        if not p:
            continue
        if p.startswith("./"):
            p = p[2:]
        (inside if any(fnmatch.fnmatch(p, g) for g in globs) else outside).append(p)
    if not inside or not outside:
        return None                       # not read under this case / the declaration held
    return {"case": name.strip(), "declared_paths": globs, "out_of_path": sorted(set(outside))}


def _case_declaration_refusal(case, *, governance_globs, _case_valid) -> "str | None":
    """SPEC-0178 rule 3, CONTROL POINT 1 (T-11156) — the DECLARATION-TIME belt. Returns a refusal
    string when this case's OWN `match.paths` name a governance surface, else None. PURE, never raises.

    Rule 3 calls this belt "early and REDUNDANT": it is not the guard, it is a second, cheaper place to
    catch the same mistake at the moment it is written rather than at the seam where the exemption
    would have been taken. Redundant means BOTH fire — a refusal here never suppresses the seam guard
    (see `_case_governance_guard`), which is what lets one carrier-naming case on a carrier-touching
    card record two refusals in one close (AC1).

    Matched in BOTH directions, deliberately: a declaration is refused when a declared glob COVERS a
    governance surface (`specs/**` covering `specs/*.yaml`) and when it IS covered BY one
    (`specs/SPEC-0001.yaml` under `specs/*.yaml`). One direction alone leaves the other spelling of the
    same declaration admissible, and a declarer picking the narrower or wider form is making the same
    request either way.

    Returns None for a case declaring no usable `paths:`. A `class:`-only case is LEGAL and explicitly
    NOT fully guarded (rule 1 says so, and states the exposure at the point of declaration): no
    class-to-path source of truth exists, so none is invented here. Such a case is covered by the SEAM
    guard, which reads the diff and needs no mapping — that asymmetry is the design, not a gap.

    An empty/absent `governance_globs` yields None: with no set to compare against there is nothing
    provable, and the SEAM is the load-bearing control point (see `_case_governance_guard`, which
    fails closed for the exemption instead)."""
    ok, _why = _case_valid(case)
    if not ok or not governance_globs:
        return None
    match = case.get("match")
    globs = match.get("paths") if isinstance(match, dict) else None
    if not (isinstance(globs, list) and globs):
        return None
    hits: list = []
    for raw in globs:
        if not (isinstance(raw, str) and raw.strip()):
            continue
        g = raw.strip()
        for surf in governance_globs:
            # BOTH directions: the declared glob covers the surface, or the surface covers it.
            if fnmatch.fnmatch(surf, g) or fnmatch.fnmatch(g, surf):
                hits.append(f"{g} (governance surface {surf})")
                break
    if not hits:
        return None
    return (f"case '{str(case.get('case')).strip()}' declares `paths:` naming a GOVERNANCE SURFACE — "
            f"{'; '.join(hits)}. SPEC-0178 rule 3: a case never reaches a spec, the pinned-test "
            "surface, an always-loaded seed, or the declaration carrier itself, so declaring one buys "
            "nothing and a contract that can exempt changes to itself stops being auditable.")


def _case_governance_guard(case, paths, *, governance_globs, _case_valid) -> "dict | None":
    """SPEC-0178 rule 3, CONTROL POINT 2 (T-11156) — the GOVERNANCE-SURFACE GUARD at the Closure seam.
    Returns `{"case", "governance_paths"}` when this card's diff touches a governance surface, so the
    case is TAKEN BACK for it (audit-post applies whatever the case says), else None. PURE, never
    raises, no I/O.

    Computed on the DIFF, NEVER on the match: it therefore holds identically for a case declared by
    `paths:` and for one declared by `class:`, neither of which needs a class-to-path mapping in order
    to be safe — and no such mapping exists to be relied on.

    `paths` is the CALLER's union — the guard never chooses a boundary of its own. `cmd_task_close`
    hands it the ship diff ∪ `_pending_governance_writes` (rule 3's boundary, wider than rule 6's ship
    diff; see that helper for why).

    APPLICABILITY ONLY (`_case_valid`), deliberately NOT `_case_declaration_refusal`: a case refused at
    declaration is still evaluated here. The belt reinforces this guard, it must never suppress it —
    the guard's question is "does this card touch a governance surface", not "was this case
    well-declared" — and suppressing it would make a carrier-naming case UNGUARDED at the one control
    point that reads reality (audit-pre pass-2 finding).

    FAIL-CLOSED CONTRACT FOR THE CARD THAT WIRES THE EXEMPTION (T-11157): an absent/empty
    `governance_globs` returns None, which means "no takeback computed" — NOT "safe to exempt". The
    caller that skips audit-post must consult this guard BEFORE the gate and treat an unavailable glob
    set as "take audit-post", per LIFECYCLE's fail-closed classification. Today nothing can be exempt
    (no `cases:` carrier exists and SPEC-0178 is `proposed`), so this contract is stated, not yet
    load-bearing."""
    ok, _why = _case_valid(case)
    if not ok or not governance_globs:
        return None
    hits: list = []
    for raw in (paths or []):
        p = str(raw).strip()
        if not p:
            continue
        if p.startswith("./"):
            p = p[2:]
        if any(fnmatch.fnmatch(p, g) for g in governance_globs):
            hits.append(p)
    if not hits:
        return None
    return {"case": str(case.get("case")).strip(), "governance_paths": sorted(set(hits))}
_CASE_DEFECT_KIND = "defect"                   # the triage judgement rule 5 counts, spelled EXACTLY


def _case_ts(value) -> "object | None":
    """SPEC-0178 rule 5 (T-11158) — parse one ISO-8601 date/datetime into an aware UTC datetime, or
    None when it cannot be read. PURE, total, never raises.

    THREE input shapes, because the two ends of the join arrive from different parsers and neither can
    be normalised at its source: a journal `ts` is a STRING (`2026-08-16T04:58:04Z`), while a case's
    `declared_at:` comes through `yaml.safe_load`, which turns an unquoted `2026-08-13` into a
    `datetime.date` and a quoted one into a `str`. A reader that handled only strings would silently
    read the ORDINARY spelling of `declared_at` as malformed.

    A naive datetime is read as UTC — the journal writes `Z`-suffixed UTC and a date has no zone, so
    there is no second interpretation to choose between."""
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day, tzinfo=_dt.timezone.utc)
    if not (isinstance(value, str) and value.strip()):
        return None
    try:
        parsed = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)


def _case_closure_index(events_path) -> dict:
    """SPEC-0178 rule 5 (T-11158) — the CLOSURE end of the derived join, folded from the journal:
    `{task_id: {"case": <exempted_case or None>, "closed_at": <closure ts>, "out_of_path": [<case>…]}}`.
    Read-only, tolerant — an unreadable journal or a mis-shaped row yields no entry, never an exception.

    `out_of_path` is ADDITIVE (T-11159): the case names this closure's `case_out_of_path` rows carry —
    rule 6's report-only observation, which rule 7's periodic review is named as the reader of. It rides
    THIS fold rather than a second traversal because it is a field of the same `task_closed` row, and a
    second walk of the journal for one adjacent key would be a parallel derivation of the same record
    (CHARTER §P5). Purely additive: `_case_attribution` reads `case`/`closed_at` and is untouched.

    NO NEW STORE, and the carrier is the one the spec names. Rule 5 derives the link "through the
    EXISTING `deviation_captured` event" and rule 4 records the exempting case as
    `task_closed.data.exempted_case`; SPEC-0025 catalogues BOTH ends as event payloads (VP10). So both
    halves are read from the journal and nothing is remembered between reads — rule 5's "State is
    DERIVED, never stored".

    THE CLOSURE INSTANT IS THE EVENT'S OWN `ts`. The `task_closed` payload carries no `closed_at` field
    (see the emit in `cmd_task_close`), and the event ts IS the moment the closure record was written.
    Joining instead to the task YAML's `closed_at:` would put one half of a two-payload join in a
    different carrier for no gain, and would make the bound unreadable for a card whose YAML has since
    been archived or renamed.

    LAST WRITE WINS for a task with more than one `task_closed` row (a `--reverify`/recovery re-close):
    the newest record is the one describing the regime the card actually closed under."""
    idx: dict = {}
    try:
        path = Path(events_path)
        if not path.exists():
            return idx
        for line in journal_mod.segment_lines(path):  # T-11892: segment-aware fold (SPEC-0190 r4)
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("type") != "task_closed":
                continue
            tid = str(e.get("task_id") or "").strip()
            if not tid:
                continue
            d = e.get("data") if isinstance(e.get("data"), dict) else {}
            case = d.get("exempted_case")
            _oop_rows = d.get("case_out_of_path")
            oop = [str(r.get("case")).strip()
                   for r in (_oop_rows if isinstance(_oop_rows, list) else [])
                   if isinstance(r, dict) and str(r.get("case") or "").strip()]
            idx[tid] = {"case": case.strip() if isinstance(case, str) and case.strip() else None,
                        "closed_at": str(e.get("ts") or ""), "out_of_path": oop}
    except Exception:
        return idx                             # a corpus read must never break a close (read-only)
    return idx


def _case_attribution(capture, *, closure_index, _case_ts) -> dict:
    """SPEC-0178 rule 5 (T-11158) — resolve ONE capture to the case it is attributed to, and say
    whether it ADVANCES that case's restoration counter. PURE, total, never raises, no I/O.

    `capture` is a `triage._scan_captures` row (the ONE capture-scan home); `closure_index` is
    `_case_closure_index`. Returns
    `{ts, task_id, derived, manual, case, counts, disagreement, why}` — `case` is the resolved
    attribution (what the triage router is handed), `counts` is whether it moves the counter, and `why`
    always names the reason it does not. The two are SEPARATE on purpose: rule 5's bounds are about
    what may be COUNTED, and a capture that resolves to a case but cannot count is still the reviewer's
    evidence — collapsing them would silently hide it.

    PRECEDENCE, fail-closed (rule 5):
      • the DERIVED case is CANONICAL wherever it can be computed — the capture names a `task_id`, and
        that card's closure record carries an `exempted_case`;
      • a hand-supplied `exempted_case` applies ONLY where no derived case exists (no task id, or a
        card that closed under no case);
      • where both exist and DISAGREE, NEITHER wins: the row carries both, resolves to no case, and
        advances nothing until a human resolves it. Counting nothing errs toward UNDER-restoring, which
        a human can still correct by hand; silently over-restoring on a wrong link is the direction
        nobody would notice.

    THE POSTDATES BOUND IS THE DERIVED LINK'S ONLY (rule 5, trial cycle 13): "a DERIVED attribution
    counts only if the capture's `ts` is later than the `closed_at` of the card it is derived through".
    A hand-supplied attribution that APPLIES at all is one where no derived case exists, so there is no
    closure for it to postdate — the bound would have no referent. An unprovable closure instant does
    not count either: rule 5 says counts ONLY IF later, and a comparison that cannot be made has not
    been satisfied. Note the row still RESOLVES to the case in both halves — the link is provenance
    either way, and VP20 is differential on the counter, not on the link.

    THE `kind` FILTER IS ONE EXACT STRING, deliberately. Rule 5 counts a capture "case-linked AND judged
    a DEFECT at triage", and the cycle-15 measurement is explicit that `kind` is free text in practice
    while this rule counts one exact spelling (`bugfix` / `process` / `probe-evidence` do NOT count) —
    normalising that vocabulary was measured to gain ONE capture across four projects and is explicitly
    not the fix. Widening it here would be the brake-that-fires-on-everything rule 5 rejects: the corpus
    carries ~1.7 captures per closed card, so counting `kind`-less captures would drive K=3 within days
    on any case of ordinary width."""
    cap = capture if isinstance(capture, dict) else {}
    ts = str(cap.get("ts") or "")
    tid = str(cap.get("task_id") or "").strip()
    manual_raw = cap.get("exempted_case")
    manual = manual_raw.strip() if isinstance(manual_raw, str) and manual_raw.strip() else None
    closure = (closure_index or {}).get(tid) if tid else None
    derived = (closure or {}).get("case")
    closed_at = (closure or {}).get("closed_at") or ""

    row = {"ts": ts, "task_id": tid or None, "derived": derived, "manual": manual,
           "case": None, "counts": False, "disagreement": False,
           "why": "no case — the capture names no card that closed under one, and supplies none"}
    if derived and manual and derived != manual:
        row["disagreement"] = True
        row["why"] = (f"DISAGREEMENT — derived '{derived}' (from {tid}'s closure record) vs supplied "
                      f"'{manual}'; advances NO counter until a human resolves it (rule 5 precedence)")
        return row
    case = derived or manual
    if not case:
        return row
    row["case"] = case
    if derived:
        cap_at, close_at = _case_ts(ts), _case_ts(closed_at)
        if not (cap_at and close_at and cap_at > close_at):
            row["why"] = (f"does not POSTDATE the closure it is derived through ({tid} closed "
                          f"{closed_at or 'at an unreadable ts'}) — provenance, not causal attribution")
            return row
    kind = cap.get("kind")
    if not (isinstance(kind, str) and kind.strip() == _CASE_DEFECT_KIND):
        row["why"] = (f"not judged `kind: {_CASE_DEFECT_KIND}` at triage (kind="
                      f"{kind if kind else 'absent'}) — an unclassified capture does not count")
        return row
    row["counts"], row["why"] = True, ""
    return row


def _case_attributions(captures, *, closure_index, _case_attribution) -> list:
    """SPEC-0178 rule 5 (T-11158) — `_case_attribution` over a capture set, order preserved. The ONE
    place both readers (the Closure-seam gate and the triage surfacing) build their input from, so the
    counter the seam computes and the rows a triager is shown can never be two different derivations."""
    return [_case_attribution(c, closure_index=closure_index) for c in (captures or [])]


def _case_covered_share(case, *, closures, now, _CASE_WINDOW_DAYS_DEFAULT, _case_positive_int_override, _case_ts) -> dict:
    """SPEC-0178 rule 9 (T-11159) — what a case is ACTUALLY covering: the SHARE of closed cards it
    exempted, over the case's OWN window. PURE, total, never raises, no I/O.

    Returns `{case, applies, w, window_start, closed, exempted, share, why}`. `share` is
    `exempted / closed` as a float, or **None** when the denominator is empty — see the last paragraph.

    THE WINDOW IS THE CASE'S OWN `window_days`, NOT "since the last review", and this reader takes NO
    last-review argument AT ALL. That absence is the design, not an omission: rule 9's own text says
    reviews arrive in BURSTS — the median inter-review gap is 0 days on all four projects (trial cycle
    19), the kernel has zero closed cards in its most recent such window — so a since-last-review
    denominator is usually ~0 days long and empty, and a "drift" between two same-day reviews is noise.
    Reusing W costs no new parameter (CHARTER §P1 F1/F2), is stable however irregularly reviews run,
    and puts the two numbers a reviewer weighs together — attributions within W (rule 5) and the
    covered share within W — on the SAME period. Because the signature cannot express a previous run,
    two reviews the same day over one journal report the SAME number BY CONSTRUCTION, and the only
    thing that moves it is the case's own W. That is the AC3 differential, and it is a property of the
    interface rather than of a branch that could be edited away.

    W IS READ THROUGH THE SHIPPED `_case_positive_int_override`, so a malformed `window_days:` makes
    the case NOT APPLY here exactly as it does at the Closure seam (rule 5), never a silent fallback to
    90. One declaration, one reading — a case that cannot be read exempts nothing AND reports nothing,
    rather than exempting nothing while reporting a number computed under a default nobody declared.

    THE WINDOW IS A TRAILING SPAN ENDING AT `now`, deliberately UNLIKE rule 5's span-between-
    attributions. The two answer different questions: rule 5 asks "have K defects landed close
    together" and must take no clock, because a clock would let a RESTORED case silently un-restore
    itself as its attributions aged out — automation REMOVING a gate, which rule 5 forbids. Rule 9 asks
    "what is this case covering NOW", which is a question about the present population and has no
    answer without one. `now` is passed in rather than read, so the fold stays pure and a test can fix
    the instant.

    AN EMPTY DENOMINATOR YIELDS `share: None`, NOT 0.0 — a share over zero closed cards is undefined,
    and rendering it as 0% would read as "this case is covering nothing", the most reassuring possible
    reading of a measurement that was never taken. The no-data JUDGEMENT belongs to the reader, which
    is why this fold hands back the raw `closed`/`exempted` counts and the caller spells the
    discriminator through `inspection.no_data_fields` (`lessons/fail-closed-belongs-to-the-reader-not-
    the-parser`). A case that exempted NOTHING over a NON-empty denominator is a different fact and
    reports `share: 0.0` — present, never omitted (rule 9 is report-only and reports every case).

    NO CEILING, NO THRESHOLD, NOTHING REFUSED — there is no comparison in this function and no caller
    branches on its value. The owner DECLINED the external auditor's outer caps (CHARTER §Project-
    declared audit-post exemption), and an "informational" number that quietly gated something would
    reintroduce them under another name."""
    name = str(case.get("case") or "").strip() if isinstance(case, dict) else ""
    out = {"case": name or None, "applies": False, "w": None, "window_start": None,
           "closed": 0, "exempted": 0, "share": None, "why": ""}
    if not isinstance(case, dict):
        out["why"] = "not a mapping"
        return out
    w, why_w = _case_positive_int_override(case, "window_days", _CASE_WINDOW_DAYS_DEFAULT)
    out["w"] = w
    if why_w:
        out["why"] = why_w
        return out
    end = _case_ts(now)
    if end is None:
        out["why"] = "unreadable `now` — a trailing window has no end, so no share is computed"
        return out
    start = end - _dt.timedelta(days=w)
    out["applies"] = True
    out["window_start"] = start.isoformat()
    for row in (closures or {}).values():
        if not isinstance(row, dict):
            continue
        at = _case_ts(row.get("closed_at"))
        if at is None or not (start < at <= end):
            continue
        out["closed"] += 1
        if row.get("case") == name:
            out["exempted"] += 1
    if out["closed"]:
        out["share"] = out["exempted"] / out["closed"]
    else:
        out["why"] = (f"no card closed in the {w}-day window — the share is UNDEFINED, not zero "
                      "(rule 9 / trial cycle 19: an empty denominator is a measurement not taken)")
    return out


def _case_revision_proposal(case, *, attributions, closures, now, _case_covered_share, _case_restoration_state, _case_share_basis) -> dict:
    """SPEC-0178 rule 7 (T-11159) — ONE revision proposal for ONE declared case. PURE, total, never
    raises, no I/O. Returns the four contract fields (`inspection.PROPOSAL_FIELDS`) plus the `share`
    block rule 9 contributes as a basis datum:
    `{case, action, basis, strength, share, restored, counted, uncounted, out_of_path}`.

    THE FOUR FIELDS ARE THE CONTRACT AND THE TOKENS COME FROM ITS ONE DEFINITION SITE
    (`bin/lib/inspection.py`, the revision-proposal contract banner). This fold imports them; it does
    not spell them. Rule 9's number rides HERE rather than on a surface of its own precisely because
    rule 7 already requires a BASIS for every proposal and the share IS a basis datum — "no new
    surface is introduced: the review that exists gains a number it can read".

    THE ACTION IS A CANDIDATE FOR A HUMAN, never an applied change. Precedence, and why each branch is
    where it is:
      1. the case is ALREADY RESTORED by the automatic path (rule 5) -> `leave`, DIRECT. The gate is
         back; there is nothing left for the review to carry, and the basis names the attributions
         that did it.
      2. rule-6 OUT-OF-PATH rows exist -> `narrow`, DIRECT. Rule 6 describes itself in exactly these
         words — "it is the evidence a reviewer needs to propose narrowing a declaration" — so this is
         the branch that rule reports INTO.
      3. counted `kind: defect` attributions exist but have not reached K -> `leave`, DIRECT. Rule 5 is
         explicit that a single attributed defect does not change the regime, and here the automatic
         brake is demonstrably OPERATIVE (the judgement is being made) — so the review defers to it
         rather than pre-empting a counter that is working.
      4. otherwise -> `restore` CANDIDATE, ABSENCE. This is the cycle-15 carrier: where no case-linked
         post-close capture is judged a defect, the automatic path CANNOT fire, and rule 5 names this
         review as what carries restoration there.

    `widen` IS NEVER REACHED, and that is the rule, not an omission: "The periodic review does not
    compute whether to loosen." It stays in the vocabulary because a HUMAN may propose it.

    THE BASIS NAMES EVERY RECORD READ, not only the ones that decided the action. A `restore` proposal
    still carries its out-of-path rows and its covered share, because a basis a reader cannot audit is
    not a basis — and because collapsing the evidence to whichever branch won would hide the narrow
    case inside a restore case. `uncounted` is load-bearing for the same reason: case-linked captures
    that exist but were never judged are the DIFFERENCE between "nothing happened" and "nobody
    looked", and branch 4 cannot tell a reader which without naming them."""
    name = str(case.get("case") or "").strip() if isinstance(case, dict) else ""
    share = _case_covered_share(case, closures=closures, now=now)
    rest = _case_restoration_state(case, attributions=attributions)
    rows = [a for a in (attributions or []) if isinstance(a, dict) and a.get("case") == name]
    counted = [a for a in rows if a.get("counts")]
    uncounted = [a for a in rows if not a.get("counts")]
    out_of_path = sorted(tid for tid, row in (closures or {}).items()
                         if isinstance(row, dict) and name in (row.get("out_of_path") or []))

    basis = [_case_share_basis(share)]
    if out_of_path:
        basis.append(f"{len(out_of_path)} closed card(s) whose SHIP diff went outside the declared "
                     f"`paths:` (rule 6, report-only): {', '.join(out_of_path)}")
    if counted:
        basis.append(f"{len(counted)} case-linked post-close capture(s) judged `kind: "
                     f"{_CASE_DEFECT_KIND}` at triage, of the K={rest['k']} that restore the case")
    if uncounted:
        basis.append(f"{len(uncounted)} case-linked capture(s) that do NOT count toward restoration "
                     f"— first reason: {uncounted[0].get('why') or 'unstated'}")
    if not rows:
        basis.append("no capture resolves to this case at all over the journal read")

    if rest["restored"]:
        action, strength = "leave", inspection.STRENGTH_DIRECT
        basis.append("the AUTOMATIC restoration has already fired for this case (rule 5) — audit-post "
                     "is back without anyone acting, so the review proposes no change")
    elif out_of_path:
        action, strength = "narrow", inspection.STRENGTH_DIRECT
    elif counted:
        action, strength = "leave", inspection.STRENGTH_DIRECT
        basis.append("the automatic brake is OPERATIVE for this case — the `kind` judgement is being "
                     "made — so restoration stays with rule 5 and the review defers to it")
    else:
        action, strength = "restore", inspection.STRENGTH_ABSENCE
        basis.append("the AUTOMATIC restoration cannot fire for this case: no case-linked post-close "
                     "capture is judged a defect, so rule 5's counter can never advance and THIS "
                     "review is the restoration carrier (rule 5, trial cycle 15)")
    # The action is checked against the contract's OWN vocabulary rather than trusted from the branch
    # above: this is the fold that produces every proposal in the corpus, and a token that drifted from
    # `PROPOSAL_ACTIONS` would ship a fifth action nobody declared. Fail loud — a silently-unknown
    # action is worse than a crash, because it renders perfectly.
    assert action in inspection.PROPOSAL_ACTIONS, f"action {action!r} is outside rule 7's vocabulary"
    row = {"case": name or None, "action": action, "basis": basis, "strength": strength,
           "share": share, "restored": rest["restored"], "counted": len(counted),
           "uncounted": len(uncounted), "out_of_path": out_of_path}
    assert all(f in row for f in inspection.PROPOSAL_FIELDS), "a proposal must carry all FOUR fields"
    return row


def _case_share_basis(share) -> str:
    """Rule 9's number, rendered as ONE basis line. PURE. Kept beside the proposal so the undefined
    case cannot be rendered as a percentage anywhere: an empty denominator SAYS it is undefined,
    because "0%" over zero closed cards is the most reassuring possible reading of a measurement that
    was never taken."""
    if not share.get("applies"):
        return f"covered share NOT computed — {share.get('why') or 'the case does not apply'}"
    if share.get("share") is None:
        return (f"covered share UNDEFINED over the case's own {share['w']}-day window — "
                f"{share['closed']} closed card(s) in it (an empty denominator is a measurement not "
                f"taken, never 0%)")
    return (f"covered share {share['exempted']}/{share['closed']} = {share['share'] * 100:.1f}% of "
            f"cards closed in the case's own {share['w']}-day window (report-only: no ceiling, no "
            f"threshold, nothing refused)")


def _case_revision_review(repo_root, *, now=None, _audit_scrutiny_cases, _case_attributions, _case_closure_index, _case_revision_proposal, _followup_overlap_events_path) -> dict:
    """SPEC-0178 rules 7+9 (T-11159) — the whole revision fold for THIS repo: one proposal per declared
    `audit_scrutiny` case. Read-only; the injected collaborator `inspect record --theme T8` calls.

    Returns `{declared, proposals}`. A project that declares NO case yields `{declared: 0,
    proposals: []}` — a real, checkable statement, which the renderer prints as no-data rather than
    swallowing (an absent block and an empty one must not read alike).

    ONE TRAVERSAL, THROUGH THE SHIPPED READERS. The carrier is `_audit_scrutiny_cases` (rule 1's named
    reader), the journal is resolved by `_followup_overlap_events_path` — the read-path==write-path
    resolver (SPEC-0095), so a `YITC_EVENTS_SINK` quarantine or a `-C` rebind is honoured exactly as
    the Closure seam honours it — and both ends of the join come from `_case_closure_index` +
    `_case_attributions`, the SAME pair `cmd_task_close` folds. Nothing here re-derives an attribution:
    a review that computed the counter differently from the gate would report a regime the system is
    not in.

    NO STORE. Rule 5's "State is DERIVED, never stored" governs this fold too — the review reads the
    journal and the ops contract, remembers nothing between runs, and (rule 9) takes no record of when
    it last ran, because the window is the case's own W.

    `now` defaults to the wall clock — the ONLY impure line, isolated here so every fold beneath it
    stays a pure function of its inputs and a test can fix the instant."""
    cases = _audit_scrutiny_cases(repo_root, ops_contract=init.CONSUMER_OPS_CONTRACT)
    if not cases:
        return {"declared": 0, "proposals": []}
    ev_path = _followup_overlap_events_path(repo_root)
    closures = _case_closure_index(ev_path)
    attributions = _case_attributions(triage._scan_captures(ev_path), closure_index=closures)
    at = now if now is not None else _dt.datetime.now(_dt.timezone.utc)
    return {"declared": len(cases),
            "proposals": [_case_revision_proposal(c, attributions=attributions, closures=closures,
                                                  now=at) for c in cases]}


def _post_action_hint(text: str) -> str:
    """A work-verb's OPTIONAL post-action note — the "optional post-hint" half of the SPEC-0033 meta-rule
    ("a verb = its own self-check + an optional post-hint"). A post-action note is a forward OPERATIONAL
    nudge (e.g. 'cd back to main', 'run audit post next'); it MUST NOT carry a what/when ROUTING payload —
    routing (which spec to read at which stage) is the binding-derived LENS, never a per-verb payload.
    Formats `text` with the NEUTRAL, note-shaped `next:` prefix (audit-pre F1 — the existing operational-
    nudge convention; no directive arrow) and returns the line. This is the STRUCTURED emitter; the
    no-routing-payload INVARIANT is held by the report-at-land conformance test
    `tests/test_t0297_post_action_hint.py` (REPORT-ONLY — not a runtime/land enforcement gate, per CHARTER
    non-goal #7 + GRAPH not-a-validation-layer + D-0036)."""
    return f"next: {text}"


def _batch_sibling_task_ids(*, REPO_ROOT, _run_git_cap) -> "set[str]":
    """T-10252 — the ids of the task cards filed into THIS unlanded work batch: every `tasks/T-*.yaml`
    that is NOT YET ON `main`. Reuses the _require_batch_born predicate (T-0590 2b — "batch-born" IS
    "absent from main"), expressed as two capped git reads instead of one `cat-file` per card:

      • `status --porcelain -- tasks/`                     → filed, still uncommitted
      • `diff --name-only --diff-filter=A main -- tasks/`  → filed and `work commit`ed, still unlanded

    Their union is the batch. Only the ADDED/UNTRACKED porcelain entries count: a card that is merely
    MODIFIED (or deleted) already exists on `main`, so it is not batch-born and must not be screened as
    a sibling. Ids are read from the canonical `tasks/T-NNNN-<slug>.yaml` filename (QUEUE §Active-queue).
    Fail-open `set()` on any nonzero git rc (non-git sandbox / detached / unborn `main`) — mirrors
    _worktree_dirty_paths' posture: a preview must NEVER break a filing. Pure, read-only, never raises."""
    paths: list[str] = []
    st = _run_git_cap(["status", "--porcelain", "--", "tasks/"], REPO_ROOT)
    if st.returncode == 0:
        for ln in st.stdout.splitlines():
            if not ln.strip():
                continue
            xy = ln[:2]                          # porcelain: XY<space>PATH (mirrors _worktree_dirty_paths)
            if xy != "??" and "A" not in xy:     # a MODIFIED/deleted/renamed card is already on main
                continue
            # T-12014: the XY columns are read RAW (the filter above needs them), so the path is decoded
            # one line at a time through the shared decoder rather than via `git_porcelain_paths`.
            paths.extend(textutil.git_porcelain_paths(ln))
    added = _run_git_cap(["diff", "--name-only", "--diff-filter=A", "main", "--", "tasks/"], REPO_ROOT)
    if added.returncode == 0:
        # T-12014: `--name-only` quotes a non-ASCII card path exactly as porcelain does.
        paths.extend(q for q in (textutil.git_unquote_path(ln).strip()
                                 for ln in added.stdout.splitlines()) if q)
    ids: set[str] = set()
    for p in paths:
        # T-12014: the trailing `.strip('"')` is gone — it removed the QUOTES and left the octal
        # escapes, so a Cyrillic-slugged card never matched the `T-NNNN` prefix. The decoder does both.
        m = re.match(r"^(T-\d+)\b", os.path.basename(p.strip()))
        if m:
            ids.add(m.group(1))
    return ids


def _requires_ordered(a: str, b: str, tasks: dict) -> bool:
    """T-10252 — are tasks `a` and `b` ordered relative to each other by the `requires:` edges in the
    index task-node map? True iff either is reachable from the other. SPEC-0044 §2.2 treats a shared
    lineage that IS `requires:`-ordered as a silent WAIT (deterministic sequencing), never an owner
    question; the code-surface altitude mirrors that — two cards that already declare their order do
    not collide, they serialize. Bounded, cycle-safe BFS; pure, never raises."""
    def _reaches(src: str, dst: str) -> bool:
        seen, frontier = {src}, [src]
        while frontier:
            cur = frontier.pop()
            for nxt in (tasks.get(cur, {}) or {}).get("requires") or []:
                nxt = str(nxt).strip()
                if nxt == dst:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        return False
    return _reaches(a, b) or _reaches(b, a)


def _declared_surface_preview(*, tid: str, cls: "str | None", requires: list, cites: list,
                              expected_touch: list, index: dict,
                              _live_claimed_task_ids, _task_safety_verdict, live_claimed: "set[str] | None" = None,
                              batch_siblings: "set[str] | None" = None, _batch_sibling_task_ids=None, _requires_ordered) -> dict:
    """FILE-TIME declared-surface safety PREVIEW (T-0440 — the file-and-take-immediately case). The
    task is NOT in the index yet, so its hypothetical DECLARED surface (expected_touch + cites +
    requires) is the input. REUSES the shipped T-0439 _task_safety_verdict by injecting the
    hypothetical state into an index COPY (the T-0439 audit-consult GREEN shape — NO parallel carve
    branch). Returns the _task_safety_verdict shape {"task","verdict","detail"}; PURE / read-only
    (deepcopies its inputs, writes nothing, emits no event). ADVISORY ONLY — the claim-moment screen
    (worktree new / task pick, T-0439) stays authoritative (report-not-block, non-goal #7).

    Two SPEC-0044 altitudes, BOTH the spec's own (no new mechanism):
      • spec-lineage screen (§2.2 normative): driven by declared `cites:` to a still-unlanded spec —
        we inject the hypothetical task as that spec's activation_owner_task in the copy, exactly the
        link a plan-decomposed task would carry, then project _task_safety_verdict.
      • code-surface overlay (§2.2 — "MAY consume the optional expected_touch forecast by plain list
        intersection"): when the lineage screen is SAFE, intersect declared expected_touch against
        each in-flight task's expected_touch (read from the index task node, T-0440 2-pre). A
        non-empty intersection → CLASH (the sanctioned plain intersection, NOT an automated
        spec-screen). Lineage WAIT/CLASH dominates and is never downgraded.

    The code-surface overlay runs over BOTH halves SPEC-0044 §2.2 names — the dispatchable set is
    "∩ collision-free vs the in-flight set AND each other" (T-10252 shipped the second conjunct; the
    overlay screened only the in-flight frontier before, so two cards filed into ONE work batch that
    declared the same path both previewed SAFE and the collision surfaced by hand at dispatch —
    T-0104/T-0105 on yitc-ops.yaml). `batch_siblings` is the sibling half: the cards filed into this
    unlanded batch (default None → derived via the injected _batch_sibling_task_ids). An UNORDERED
    co-declarer → CLASH; a `requires:`-ordered one does not clash (it serializes — the §2.2 silent-WAIT
    treatment of an ordered shared lineage, mirrored at the code-surface altitude)."""
    import copy
    if live_claimed is None:
        live_claimed = _live_claimed_task_ids()      # §2.3 substrate read: the LIVE frontier
    if batch_siblings is None:                       # the batch half (git-derived; [] without the injection)
        batch_siblings = _batch_sibling_task_ids() if _batch_sibling_task_ids else set()
    idx2 = {
        "tasks": copy.deepcopy(index.get("tasks", {}) or {}),
        "specs": copy.deepcopy(index.get("specs", {}) or {}),
        "decisions": copy.deepcopy(index.get("decisions", {}) or {}),
    }
    # Inject the hypothetical ready node (the task not yet on disk/index).
    idx2["tasks"][tid] = {"status": "ready", "class": (cls or ""),
                          "requires": [str(r) for r in (requires or [])]}
    # Derive the hypothetical activating spec from declared cites: a freshly-filed task has no
    # activation_owner_task carrier yet, so the lineage screen would never see it. For each cited
    # SPEC-id present in the index and NOT yet active on main (proposed / absent), supply the link.
    for c in (cites or []):
        sid = str(c).strip()
        if not sid.startswith("SPEC-"):
            continue
        snode = idx2["specs"].get(sid)
        if snode is None:
            continue                                  # an unknown cited spec contributes no lineage
        if (snode.get("status") or "") == "active":
            continue                                  # landed lineage → not a conflict source
        snode["activation_owner_task"] = tid          # screenable exactly like a decomposed task
    verdict = _task_safety_verdict(tid, idx2, live_claimed=live_claimed)

    # §2.2 code-surface overlay — only when the authoritative lineage screen is SAFE (it dominates).
    if verdict.get("verdict") == "SAFE":
        declared = {str(x).strip() for x in (expected_touch or []) if str(x).strip()}
        held_tasks = index.get("tasks", {}) or {}
        # The batch siblings screened below: this batch's OTHER cards. A sibling that is already
        # live-claimed belongs to the frontier loop (screened first, same verdict) — never twice.
        siblings = sorted(s for s in batch_siblings if s != tid and s not in live_claimed)
        if declared:
            for held in sorted(live_claimed):
                held_et = {str(x).strip() for x in (held_tasks.get(held, {}).get("expected_touch") or [])}
                shared = declared & held_et
                if shared:
                    return {"task": tid, "verdict": "CLASH",
                            "detail": ("declared expected_touch overlaps in-flight " + held + " on "
                                       + ", ".join(sorted(shared))
                                       + " (SPEC-0044 §2.2 code-surface — serialize or split the region)")}
            # …AND each other (§2.2): the sibling cards of this unlanded work batch. The hypothetical
            # node injected into idx2 carries THIS card's declared requires:, so an ordered pair is
            # recognised in both directions even before the card reaches disk.
            for sib in siblings:
                if _requires_ordered(tid, sib, idx2["tasks"]):
                    continue                      # ordered → serialized, not a collision (silent WAIT)
                sib_et = {str(x).strip() for x in (held_tasks.get(sib, {}).get("expected_touch") or [])}
                shared = declared & sib_et
                if shared:
                    return {"task": tid, "verdict": "CLASH",
                            "detail": ("declared expected_touch overlaps sibling card " + sib
                                       + " filed in this work batch on " + ", ".join(sorted(shared))
                                       + " (SPEC-0044 §2.2 code-surface — order them via requires: "
                                         "or split the region)")}
        verdict = dict(verdict)
        # Name the SCOPE of what was checked: an unqualified "SAFE" reads as a full-collision
        # clearance, which this screen never was (T-10252).
        if declared:
            verdict["detail"] = ("no spec-lineage conflict; expected_touch forecast checked clear vs the "
                                 "in-flight frontier and the " + str(len(siblings))
                                 + " unlanded sibling card(s) in this work batch")
        else:
            verdict["detail"] = ("no spec-lineage conflict; no expected_touch declared — "
                                 "no code-surface check ran")
    return verdict
