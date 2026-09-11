"""Error case-file verb family for the yitc-v2 CLI — `error file|list|show|promote|resolve` (the
errors/E-XXXX.yaml nonconformity case files, D-0035 / D-0086 / SPEC-0056 / SPEC-0058). The third
layer-2 verb-family extraction.

bin/yitc-v2 keeps the thin argparse residue cmd_error_* (the `set_defaults(func=…)` entrypoints, wiring
unchanged) which delegate here, injecting the host collaborators each verb needs — the audit.py
verb-family precedent (family bodies in lib, host thin residue + injected host deps), so a `-C` REPO_ROOT
rebind and every `monkeypatch.setattr(yitc, …)` stay honored at call time.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It imports only
the already-extracted lower leaves `lib.state` (canonical YAML dump + error scan) and `lib.textutil`
(slug), plus stdlib; it NEVER back-imports the host. The shared / cross-called / triage helpers
(_find_error_yaml, _file_fix_task, _promote_owner_due_suffix, _journal_error_transition,
_reopen_resolved_error, _error_fingerprint_index, _remedy_verdict) DELIBERATELY stay host-side and are
injected here, since they are used by non-error verbs (cmd_audit_run / cmd_event / cmd_triage_run) or are
task-filing glue. Behaviour is byte-identical to the inline originals — the test suite is the oracle.
"""
from __future__ import annotations

import argparse
import sys

from lib import state
from lib import graph as graph_lib   # T-11992: the shared SPEC-0092 retrieval-hint renderer (`spec_query_hint`) — graph.py imports only lib.state + stdlib, so this stays acyclic
from lib import textutil

ERROR_KINDS = ("defect", "friction", "improvement")
ERROR_SEVERITIES = ("low", "medium", "high")

# A case file cites these stores as WHERE the deviation was RECORDED, never as the surface a fix
# EDITS. Forecasting them would be a WRONG forecast — strictly worse than none (SPEC-0028: a wrong
# `expected_touch` causes a mis-dispatch), so they are dropped from the derivation below.
PROVENANCE_ONLY_REFS = ("tasks/", "decisions/", "errors/", "events.jsonl")

# The case-file fields that can carry a code anchor. `fingerprint` is a slug (never a path) and
# `resolution` is written BY the promote, so neither is scanned.
_ANCHOR_BEARING_FIELDS = ("title", "relates_to", "rca", "prevention")


def derive_expected_touch(record: dict, *, extract_referenced_paths, repo_root) -> list:
    """Derive a fix task's `expected_touch` forecast from the error case-file that spawned it
    (T-10251). Applies SPEC-0046 §A ("persist the enumerated blast-radius, don't reason-then-discard
    it") to the promote path, as T-10180 already did to the plan-cut path.

    REUSES the host's existing scanner (`_extract_referenced_paths` → REFERENCED_PATH_RE +
    is_file() existence check) over the case file's anchor-bearing text — no second regex, no second
    scanner (CHARTER §P1 F1). The scanner is task-shaped, so the text is handed to it as a `scope`
    list; only its path-extraction is used.

    WHAT COUNTS AS A CODE ANCHOR — every EDITABLE repo surface REFERENCED_PATH_RE addresses: `bin/`
    code, `specs/*.yaml`, `patterns/*.md` and the handbook docs. NOT `bin/` alone: a fix for a
    friction routinely edits the spec or pattern that homes the rule, and a spec / handbook-seed touch
    is precisely the HIGH-blast-radius surface the frontier screen weights heaviest
    (`journal.py _is_governance_surface`). Restricting the forecast to code would leave the most
    collision-prone surface undeclared — the blind spot this derivation exists to close.

    Fail-closed: a token survives only if it BOTH resolves to a real file under `repo_root` AND is
    not a `PROVENANCE_ONLY_REFS` store. Emits coarse FILE-level units — a `path#symbol` anchor is
    never synthesized, since the reused regex does not span `#` and an unverifiable symbol is a
    worse forecast than a verified file. Pure f(record): sorted, deduped, no I/O of its own."""
    text: list = [record.get(f) for f in _ANCHOR_BEARING_FIELDS]
    text.extend(record.get("refs") or [])
    shim = {"scope": [t.strip() for t in text if isinstance(t, str) and t.strip()]}
    touch: set = set()
    for path in extract_referenced_paths(shim):
        try:
            rel = str(path.relative_to(repo_root))
        except ValueError:                       # outside the repo — never a forecastable surface
            continue
        if rel.startswith(PROVENANCE_ONLY_REFS):
            continue
        touch.add(rel)
    return sorted(touch)


def cmd_error_file(args: argparse.Namespace, *, die, as_list, id_alloc_lock, errors_dir, repo_root,
                   write_text_atomic, append_event, utc_now_iso) -> str:
    """Open an errors/E-XXXX.yaml case file (records the synthesis). NOT the promotion —
    the forced file-or-waive resolution is `error promote` (D-0035 §PROMOTE).

    Returns the repo-relative path of the case file just written (T-10452) — the host residue
    uses it to scope a main-checkout direct-to-main self-commit; other callers ignore it."""
    import yaml
    title = (args.title or "").strip()
    if not title:
        die("--title required (non-empty)")
    if args.kind not in ERROR_KINDS:
        die(f"--kind must be one of {list(ERROR_KINDS)}")
    severity = args.severity or "medium"
    if severity not in ERROR_SEVERITIES:
        die(f"--severity must be one of {list(ERROR_SEVERITIES)}")
    refs = as_list("ref", args.ref or [])
    with id_alloc_lock(errors_dir, "E") as eid:
        path = errors_dir / f"{eid}-{textutil.slug(title, die=die)}.yaml"
        if path.exists():
            die(f"collision (post-lock): {path.name} already exists")  # defense in depth
        record = {
            "id": eid, "title": title, "kind": args.kind, "severity": severity,
            "relates_to": args.relates_to or "", "fingerprint": args.fingerprint or "",
            "refs": list(refs), "rca": None, "resolution": None,
            # single-status reopen-FSM (D-0086 §8) — triage_step collapsed INTO status
            "status": "open", "reopen_count": 0, "prevention": None, "adoption_probe": None,
            "created": utc_now_iso()[:10],
        }
        content = state.dump(record)
        write_text_atomic(path, content)
        append_event("error_filed", eid, {
            "path": str(path.relative_to(repo_root)), "kind": args.kind,
            "severity": severity, "fingerprint": args.fingerprint or ""})
    rel = str(path.relative_to(repo_root))
    print(f"error opened: {rel} (id={eid}, status: open)")
    print(f"next: resolve via `yitc-v2 error promote {eid} --to-task --owner <who> --due <YYYY-MM-DD>` "
          f"OR `--waive --reason <why>` — promotion-only case files MUST be resolved (D-0035 §PROMOTE).")
    # Return the repo-relative case-file path so the host residue can scope a main-checkout
    # self-commit to it (T-10452). Callers that ignore the return are byte-unaffected.
    return rel


def cmd_error_list(args: argparse.Namespace, *, errors_dir, read_yaml) -> None:
    """List errors/E-*.yaml (E-* glob excludes _template.yaml) with status/kind filters."""
    rows = []
    for p in state.scan_errors(errors_dir):
        d = read_yaml(p)
        if not d.get("id"):
            continue
        if args.status and d.get("status") != args.status:
            continue
        if args.kind and d.get("kind") != args.kind:
            continue
        rows.append(d)
    if not rows:
        print("(no error case files match)")
        return
    for d in rows:
        flag = "  ⚠ unresolved" if d.get("status") in ("open", "reopened") else ""
        rc = int(d.get("reopen_count") or 0)
        reopened = f"  ↻x{rc}" if rc else ""   # surface the reopen/resolved metric (D-0086 §8)
        print(f"{d['id']}  [{d.get('kind','')}/{d.get('severity','')}]  {d.get('status','')}{flag}{reopened}  "
              f"fp={d.get('fingerprint','') or '-'}  {d.get('title','')}")


def cmd_error_show(args: argparse.Namespace, *, die, find_error_yaml) -> None:
    path = find_error_yaml(args.id)
    if path is None:
        die(f"error case file not found (0 or >1 match): {args.id}")
    print(path.read_text(encoding="utf-8").rstrip())


def cmd_error_promote(args: argparse.Namespace, *, die, find_error_yaml, read_yaml, file_fix_task,
                      promote_owner_due_suffix, write_text_atomic, append_event,
                      journal_error_transition, extract_referenced_paths, repo_root,
                      is_consumer_build=None) -> None:
    """The forced file-or-waive resolution (D-0035 §PROMOTE). Exactly one of --to-task / --waive."""
    import yaml
    if bool(args.to_task) == bool(args.waive):
        die("exactly one of --to-task or --waive required (D-0035 forced file-or-waive)")
    # `--by-design-residual` DECLARES that this waive expects its residual to keep recurring, which is
    # what suppresses the capture-time reopen (T-10924, SPEC-0056 §4). It is meaningless on a fix_task
    # route — that route's whole claim is that the recurrence will GO AWAY once the fix lands.
    by_design_residual = bool(getattr(args, "by_design_residual", False))
    if by_design_residual and args.to_task:
        die("--by-design-residual applies only to --waive: a fix_task promotion claims the recurrence "
            "will STOP once the fix lands, so it cannot also declare the residual by-design (T-10924)")
    path = find_error_yaml(args.id)
    if path is None:
        die(f"error case file not found (0 or >1 match): {args.id}")
    record = read_yaml(path)
    if not record.get("id"):
        die(f"{path.name}: unreadable / missing id")
    # Migrate-on-touch to the D-0086 §8 single-status reopen-FSM: drop the legacy triage_step
    # (collapsed INTO status) and ensure the reopen-FSM fields exist on any pre-D-0086 record.
    record.pop("triage_step", None)
    record.setdefault("reopen_count", 0)
    record.setdefault("adoption_probe", None)
    if getattr(args, "prevention", None) and args.prevention.strip():
        record["prevention"] = args.prevention.strip()
    else:
        record.setdefault("prevention", None)
    if args.to_task:
        # OWNER+DUE OPTIONAL for solo (T-0460, D-0086 §PROMOTE / rejected_ideas): the forced owner+due
        # is DROPPED — QUEUE has no owner/due fields, V2 is solo-author, so "done=adopted" is carried by
        # routing + the reopen-FSM + the STALE open-N>=2 flag (Section B), NOT a forced owner field the
        # queue cannot even store. If given they are still recorded (back-compat); if absent the fix-task
        # is filed ownerless and the resolution omits the empty keys. This makes code + D-0086 §PROMOTE +
        # the pattern §PROMOTE agree (the prior `_die` contradicted the decision's rejected_ideas).
        owner = (args.owner or "").strip()
        due = (args.due or "").strip()
        # SURFACE-DECLARATION (T-10251, SPEC-0046 §A): forecast the fix's touch surface from the case
        # file's own code anchors, rather than birthing a card with NO `expected_touch`. That field is
        # what the filing preview + the in-flight-frontier screen read to forecast collisions, so an
        # undeclared card is INVISIBLE to clash-detection (bin/lib/journal.py `no_forecast`). When
        # nothing derives, SAY SO below — the defect this closes is the SILENCE, not the empty list.
        expected_touch = derive_expected_touch(
            record, extract_referenced_paths=extract_referenced_paths, repo_root=repo_root)
        tid = file_fix_task(record["id"], record.get("title", ""), record.get("fingerprint", ""),
                            owner, due, expected_touch=expected_touch)
        if expected_touch:
            print(f"  expected_touch (derived from {record['id']}'s code anchors): "
                  f"{', '.join(expected_touch)}")
            print(f"  (advisory forecast — SPEC-0028; refine it on {tid} at Analysis if wrong.)")
        else:
            print(f"  ⚠ no expected_touch derived for {tid}: {record['id']} names no code anchor its "
                  f"text fields could resolve to a repo file (only provenance refs — tasks/ decisions/ "
                  f"errors/ events.jsonl — if any).")
            print(f"  The card is filed with NO surface declaration, so the in-flight-frontier screen's "
                  f"clash-detection is BLIND on it. Declare `expected_touch:` on {tid} at Analysis "
                  f"(`{graph_lib.spec_query_hint('SPEC-0046', is_consumer=bool(is_consumer_build and is_consumer_build()), cli='yitc-v2')}`).")
        resolution = {"kind": "fix_task", "fix_task": tid}
        if owner:
            resolution["owner"] = owner
        if due:
            resolution["due"] = due
        record["resolution"] = resolution
        # SPLIT-STATUS (T-0459, D-0086 §4/§8): promote --to-task makes the case `investigating` —
        # a fix is FILED but not yet LANDED. `resolved` is reserved for after the root-fix lands
        # (per §4: resolved = a LANDED root-fix removes the recurrence). Filing != fixed; the prior
        # write of `resolved` at file-time was the bug this closes.
        record["status"] = "investigating"
        od = promote_owner_due_suffix(owner, due, sep=", ", label_sep=" ",
                                      open_=" (", close=")", solo=" (solo: no owner/due)")
        outcome = f"fix_task {tid}{od} — status: investigating"
    else:
        if not (args.reason and args.reason.strip()):
            die("--waive requires --reason (no silent drop — D-0035)")
        record["resolution"] = {"kind": "waived", "waive_reason": args.reason.strip()}
        record["status"] = "waived"
        outcome = f"waived ({args.reason.strip()})"
        if by_design_residual:
            # The declaration the capture-time reopen reads (`_reopen_resolved_error`): a recurrence of
            # THIS case surfaces as `error_residual_recurrence` and leaves the case file untouched,
            # instead of flipping it to `reopened` and mutating the corpus under an unrelated card.
            record["resolution"]["by_design_residual"] = True
            outcome += " [by-design residual: recurrences surface, they do not reopen]"
    # NUDGE, not a gate (audit-post T-0150 F1 + CHARTER non-goal #7): D-0086 §6 wants the ROOT-fix
    # recorded, but a waive legitimately may have none ("accepted, not prevented"), so --prevention
    # stays OPTIONAL. Surface the gap instead of blocking — observability over enforcement.
    if not (record.get("prevention") or "").strip():
        print(f"  note: no --prevention recorded for {record['id']} (SPEC-0056 §2 prefers the root-fix "
              f"be named; OK to omit for a pure 'accept' waive).", file=sys.stderr)
    content = state.dump(record)
    write_text_atomic(path, content)
    # Journal the FSM transition through the single canonical point (T-0459): error_investigating
    # (the --to-task in-flight transition) or error_waived (the --waive terminal). The umbrella
    # error_promoted stays for back-compat (additive, P5-safe — consumers ignore unknown types, D-0009).
    append_event("error_promoted", record["id"], {
        "resolution": record["resolution"]["kind"], "status": record["status"]})
    journal_error_transition(record["id"], record["status"],
                             {"resolution": record["resolution"]["kind"]})
    print(f"{record['id']} promoted -> {outcome}")


def cmd_error_resolve(args: argparse.Namespace, *, die, find_error_yaml, read_yaml, find_task_yaml,
                      write_text_atomic, journal_error_transition) -> None:
    """Mark a promoted case `resolved` AFTER its root-fix has LANDED (T-0459, D-0086 §4/§8). This is
    the real resolve-FSM writer that the split-status created room for: `promote --to-task` files the
    fix and leaves the case `investigating`; once the root-fix lands, `error resolve E-XXXX` flips it
    `investigating|reopened → resolved` and JOURNALS `error_resolved` (the single journaling point).
    Refuses a case that is not in-flight (open/waived/already-resolved) so `resolved` always attests a
    landed fix, never a bare hand-flip. --prevention records the root-fix that stops recurrence (§6).

    GATE on the linked fix-task being DONE (T-0484): `resolved` means the root-fix LANDED (D-0086 §4),
    but the in-flight check alone only proves the case was promoted, NOT that the fix shipped — a bare
    `error resolve` could flip `investigating → resolved` while the linked fix-task is still `ready` /
    `in-progress`, making `resolved` lie. So before the write, read the case's `resolution.fix_task`
    (the task `promote --to-task` filed) and REFUSE unless that task is `status: done`. Absent fix_task
    link / unreadable-or-missing task YAML → also refuse (the resolve cannot attest a landed fix it
    cannot see). Reuses the existing `_find_task_yaml` + `_read_yaml` — no new reader, no schema change."""
    import yaml
    path = find_error_yaml(args.id)
    if path is None:
        die(f"error case file not found (0 or >1 match): {args.id}")
    record = read_yaml(path)
    if not record.get("id"):
        die(f"{path.name}: unreadable / missing id")
    record.pop("triage_step", None)                       # migrate-on-touch (D-0086 §8)
    record.setdefault("reopen_count", 0)
    record.setdefault("adoption_probe", None)
    record.setdefault("prevention", None)
    cur = record.get("status")
    # NON-FIX_TASK LANDED-ROOT-FIX ROUTE (T-9746, SPEC-0056 §4): a case whose root-fix landed via a
    # carrier that is NOT a promote-filed fix-task — an open/never-promoted friction fixed elsewhere
    # (E-0014), or a `deferred_to_plan` case whose plan realized (E-0020) — has no `fix_task` to gate
    # on, so the fix_task done-gate below can never pass. `--root-fix <ref>` is the explicit
    # attestation of that landed carrier (a task id / plan slug / spec / verb change). It REQUIRES
    # `--prevention` (resolved must still NAME the landed fix — never a bare hand-flip) and, because a
    # never-promoted case is still `open`, it ALSO admits `open` as resolvable. Terminal resolved/waived
    # stay refused. The ordinary fix_task path (no --root-fix) is UNCHANGED below.
    root_fix = getattr(args, "root_fix", None)
    root_fix = root_fix.strip() if isinstance(root_fix, str) else None
    if root_fix:
        if cur not in ("open", "investigating", "reopened"):
            die(f"{record['id']} is '{cur}', not resolvable — --root-fix resolves an "
                "open/investigating/reopened case whose root-fix LANDED (SPEC-0056 §4); it is already terminal.")
        if not (getattr(args, "prevention", None) and args.prevention.strip()):
            die(f"{record['id']}: --root-fix requires --prevention naming the landed root-fix — "
                "`resolved` must attest the fix, never a bare hand-flip (SPEC-0056 §4).")
        record["prevention"] = args.prevention.strip()
        resolution = record.get("resolution") or {}
        resolution["root_fix"] = root_fix
        resolution.setdefault("kind", "root_fix_landed")
        record["resolution"] = resolution
        record["status"] = "resolved"
        content = state.dump(record)
        write_text_atomic(path, content)
        journal_error_transition(record["id"], "resolved", {"from_status": cur, "root_fix": root_fix})
        print(f"{record['id']} resolved (was {cur}) — landed root-fix: {root_fix} (SPEC-0056 §4)")
        return
    if cur not in ("investigating", "reopened"):
        die(f"{record['id']} is '{cur}', not in-flight — resolve applies to an investigating/reopened "
            "case whose root-fix has LANDED (SPEC-0056 §4). promote it first, or it is already terminal.")
    # FIX-TASK DONE-GATE (T-0484): `resolved` attests a LANDED root-fix (D-0086 §4). The in-flight
    # check above only proves the case was promoted, so verify the linked fix-task ACTUALLY shipped
    # before flipping — never silently resolve on an un-landed fix. A fix_task resolution is the only
    # kind that links a task; a waived case is already refused (status != in-flight) above.
    resolution = record.get("resolution") or {}
    fix_task_id = resolution.get("fix_task") if resolution.get("kind") == "fix_task" else None
    if not fix_task_id:
        die(f"{record['id']} has no resolution.fix_task linked — cannot attest a landed root-fix. "
            "`resolved` requires a fix-task (promote --to-task), and that task must be done (SPEC-0056 §4). "
            "If the root-fix landed via a non-fix_task carrier (a plan / spec / verb change), use "
            "--root-fix <ref> --prevention <naming the fix>.")
    task_path = find_task_yaml(fix_task_id)
    if task_path is None:
        die(f"{record['id']}: fix-task {fix_task_id} not found (0 or >1 match) — unreadable, cannot "
            "verify the root-fix landed. resolve refuses rather than silently attesting (SPEC-0056 §4).")
    fix_status = (read_yaml(task_path) or {}).get("status")
    if fix_status != "done":
        die(f"{record['id']}: fix-task {fix_task_id} is '{fix_status}', not 'done' — the root-fix has "
            "NOT landed. resolve only after the fix-task closes (SPEC-0056 §4: resolved = a LANDED root-fix).")
    if getattr(args, "prevention", None) and args.prevention.strip():
        record["prevention"] = args.prevention.strip()
    record["status"] = "resolved"
    content = state.dump(record)
    write_text_atomic(path, content)
    journal_error_transition(record["id"], "resolved", {"from_status": cur})
    if not (record.get("prevention") or "").strip():
        print(f"  note: no --prevention recorded for {record['id']} (SPEC-0056 §2 prefers the root-fix "
              f"be named on resolve).", file=sys.stderr)
    print(f"{record['id']} resolved (was {cur}) — root-fix landed (SPEC-0056 §4)")
