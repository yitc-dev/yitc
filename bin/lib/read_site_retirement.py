"""`retire-read-site` — the covering verb for retiring a TRACKED root-cwd read-site (T-11779).

WHY A VERB AT ALL, AND WHY THIS NARROW ONE. Removing a root-cwd subprocess site from a test is
ordinary, wanted work — the test-cheapening programme generates it in bulk (T-11095 converted 37
sites across 27 files; T-11144 five e2e chains; T-11727 two). But the site is TRACKED: the read-set
ledger (`dev-utilities/root-cwd-read-sets-*.json`) carries a row for it, and the pinned probes
assert the ledger reconciles with the tree. So the removal strands the row, the probes redden, and
until now the only cure was an owner-ACKed `land --rebaseline` with a `--rebaseline-kind` and a
reason — per removal. That round-trip is what this verb retires, and the external auditor made that
retirement the CONDITION of the verb existing at all (GREEN, 0 findings,
`decisions/retire-tracked-read-site-verb-audit-adhoc.yaml`): a verb that did not remove the
operational burden would be worse than no verb.

WHAT IT IS DELIBERATELY NOT. Not a rebaseline path. It names specific previously-tracked sites,
proves each ABSENT by re-running the instrument over the current tree, regenerates the report from
that measurement, and records a retirement entry tied to task + fingerprint + reason. It permits no
arbitrary report edits, no threshold changes, no new-site acceptance, no broad baseline churn, and
there is no force flag and no "retire everything stale" mode — the set of retired sites is always a
set the caller NAMED. The rules live in SPEC-0192; the primitive that enforces them lives with the
instrument that owns the report format (`retire_sites`), never re-implemented here.

HOST BOUNDARY. This module is the verb's own home rather than a section of `verify_runner.py`,
whose documented boundary is the verify runner's own execution closure (audit-pre finding, pass 1).
The SHAPE it follows is `verify-durations` (T-11316): a narrow verb over a measurement-derived
record the verify path pins, with a thin residue in `cli.py`.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

INSTRUMENT_REL = "dev-utilities/trace-root-cwd-child-reads.py"
LEDGER_GLOB = "root-cwd-read-sets-*.json"
MIN_REASON_CHARS = 20


def load_instrument(repo_root: Path):
    """Load the tracer as a module. It is the SINGLE home of the report format and of the
    retirement primitive — this verb never re-implements either (SPEC-0192 rule 5)."""
    path = Path(repo_root) / INSTRUMENT_REL
    if not path.exists():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location("root_cwd_tracer", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def discover_ledgers(repo_root: Path) -> list[Path]:
    return sorted((Path(repo_root) / "dev-utilities").glob(LEDGER_GLOB))


def resolve_selector(selector: str, rows: list[dict]) -> list[str]:
    """Resolve one `--site` selector against RECORDED rows: an exact `site_key`, else the
    `file:line` label, else the bare `file` — and an AMBIGUOUS selector resolves to several keys so
    the caller can refuse it rather than guess. Guessing here would retire the wrong row, and the
    wrong row is exactly the site whose read-set nobody would notice was gone."""
    sel = selector.strip()
    exact = [r["site_key"] for r in rows if r.get("site_key") == sel]
    if exact:
        return exact
    labelled = [r["site_key"] for r in rows
                if f"{r.get('file')}:{r.get('line')}" == sel or r.get("file") == sel]
    return labelled


def plan_retirement(repo_root: Path, selectors, *, task: str, reason: str,
                    fingerprint: str | None, reports: list[Path] | None = None):
    """Compute the retirement over EVERY affected ledger without writing anything.

    ALL-OR-NOTHING ACROSS REPORTS as well as within one. The two shipped ledgers describe the same
    corpus, so retiring a site in one and refusing in the other would leave the pair disagreeing
    about what the tree contains — the very drift the probes exist to catch, introduced by the tool
    that is supposed to end it. So every report is computed first and the caller writes only if all
    of them retire cleanly.
    """
    tracer = load_instrument(repo_root)
    ledgers = list(reports) if reports else discover_ledgers(repo_root)
    if not ledgers:
        raise FileNotFoundError(f"no {LEDGER_GLOB} under {Path(repo_root) / 'dev-utilities'}")

    live = tracer.enumerate_sites(Path(repo_root))   # ONE measurement, shared by every report
    loaded = [(p, json.loads(p.read_text(encoding="utf-8"))) for p in ledgers]

    resolved: dict[str, list[str]] = {}
    for sel in selectors:
        keys: list[str] = []
        for _p, rep in loaded:
            for k in resolve_selector(sel, rep.get("sites") or []):
                if k not in keys:
                    keys.append(k)
        resolved[sel] = keys

    unmatched = [s for s, k in resolved.items() if not k]
    if unmatched:
        raise tracer.RetirementRefused(
            "selector-unmatched",
            f"{len(unmatched)} selector(s) match no recorded row in any ledger — a retirement "
            f"removes a TRACKED site, so a selector that names nothing tracked is refused rather "
            f"than treated as already-retired: {unmatched}",
            {"unmatched": unmatched})
    ambiguous = {s: k for s, k in resolved.items() if len(k) > 1}
    if ambiguous:
        raise tracer.RetirementRefused(
            "selector-ambiguous",
            f"{len(ambiguous)} selector(s) match more than one recorded site — name the exact "
            f"`site_key` instead; guessing would retire a row whose read-set nobody would notice "
            f"was gone: {ambiguous}",
            {"ambiguous": ambiguous})

    keys = [k for ks in resolved.values() for k in ks]
    planned = []
    for path, rep in loaded:
        here = [k for k in keys if any(r.get("site_key") == k for r in rep.get("sites") or [])]
        if not here:
            continue
        new_rep, entries = tracer.retire_sites(
            Path(repo_root), rep, here, task=task, reason=reason,
            fingerprint=fingerprint, live=live)
        planned.append((path, new_rep, entries))
    return tracer, planned, keys, live


def write_planned(tracer, planned) -> list[Path]:
    """Write both halves of every affected artifact through the instrument's OWN writers.

    Never a hand-edit of the JSON or the markdown: the writers hold the one-line-per-site layout the
    audit packet depends on (T-11128) and the authored closure section a re-run must carry across.
    """
    written = []
    for path, rep, _entries in planned:
        tracer.write_report_json(rep, path)
        md_path = path.with_suffix(".md")
        out = tracer.render_md(rep)
        if md_path.exists():
            prior = md_path.read_text(encoding="utf-8")
            if tracer.CLOSURE_MARKER in prior:
                out += "\n" + tracer.CLOSURE_MARKER + prior.split(tracer.CLOSURE_MARKER, 1)[1]
        md_path.write_text(out, encoding="utf-8")
        written.extend([path, md_path])
    return written


def cmd_retire_read_site(args, *, REPO_ROOT, _die, _append_event) -> None:
    """`retire-read-site --task T-XXXX --site <key|file:line> [--site ...] --reason <why>`."""
    repo_root = Path(REPO_ROOT)
    reason = (args.reason or "").strip()
    if len(reason) < MIN_REASON_CHARS:
        _die(f"retire-read-site: --reason must be >= {MIN_REASON_CHARS} chars — a retirement with "
             f"no recorded why is exactly the silent-drift case the pinned probes exist to keep "
             f"visible (SPEC-0192 rule 2).")
    try:
        tracer, planned, keys, live = plan_retirement(
            repo_root, args.site, task=args.task, reason=reason,
            fingerprint=args.fingerprint,
            reports=[Path(p) for p in (args.report or [])] or None)
    except FileNotFoundError as e:
        _die(f"retire-read-site: {e}")
        return
    except Exception as e:                      # the instrument's RetirementRefused
        if type(e).__name__ != "RetirementRefused":
            raise
        _die(f"retire-read-site: REFUSED [{e.reason}] {e}")
        return

    if not planned:
        _die("retire-read-site: no ledger carries the named site(s) — nothing to retire.")
        return

    written = write_planned(tracer, planned)
    _append_event("read_site_retired", args.task, {
        "site_keys": keys,
        "fingerprint": args.fingerprint,
        "reason": reason,
        "reports": [str(p.relative_to(repo_root)) for p in written],
        "live_site_count": len(live),
        "absence_established_by": tracer.RETIREMENT_ABSENCE_METHOD,
    })
    print(f"retire-read-site: retired {len(keys)} tracked site(s) across "
          f"{len(planned)} ledger(s) — absence MEASURED over the current tree "
          f"({len(live)} live site(s) re-derived), rows removed and recorded.")
    for _p, _rep, entries in planned:
        for e in entries:
            print(f"  - {e['file']}:{e['line']}  {e['site_key']}")
    for p in written:
        print(f"  -> {p.relative_to(repo_root)}")
    print("  no --rebaseline, no --rebaseline-waive, no owner ACK: the ledger now reconciles "
          "against the tree by measurement.")
