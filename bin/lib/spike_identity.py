"""T-12567 (SPEC-0205 rules 2 + 2a) — spike CONTENT identity at land (L2a), refusal ENABLED by L2c.

ONE helper, run once per governed land attempt AFTER `_spike_land_verdict` and after the land
reservation is taken. It folds the canonical spike set from MAIN's live journal rows + their
projections (ACTIVE: stamp ⇄ `worktree_created{spike}` row; PARKED: annotated `spike/<slug>` tag ⇄
row), computes T1 (changed-blob identity) and T3 (canonical hunk-subset identity), journals ONE row
and prints the report line. The helper itself never refuses: the land's step 2d refuses an identity
verdict through `refusal_message` while REFUSE_SPIKE_CONTENT is ON (shipped ON since T-12573), and the
row's `report_only` / the report line say which mode ran. It NEVER raises: an internal error is
recorded on the row and the land proceeds (an uncomputed verdict never refuses).

The algorithm is ported from the trial prototype `dev-utilities/trial-spike-content-identity.py`
(the RED-first reference). Stdlib only; never imports the host.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
EXEMPT_ATTR = "yitc-generated"
CHECKED_EVENT = "spike_content_checked"
PREVIEWED_EVENT = "spike_content_previewed"

# T-12570 (SPEC-0205 rule 2, L2b) — THE ONE enablement switch for the refusal arm. A code-level constant
# on purpose: not an env var, CLI flag or yitc-ops key, so no land override reaches it. SHIPPED ON since
# L2c (T-12573), after every existing legacy spike branch was adopted (T-12575); only tests force it OFF,
# where the report-only behaviour above is unchanged byte-for-byte. ON or OFF, an UNCOMPUTED verdict never
# refuses (SPEC-0205 rule 2, «Uncomputed verdict» — T-13238).
REFUSE_SPIKE_CONTENT = True
REFUSAL_ABORT_CLASS = "spike-content"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _git(repo, *args, raw=False, inp=None, check=True):
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=not raw, input=inp,
                       env=_git_env._git_child_env())
    if check and p.returncode != 0:
        err = p.stderr if isinstance(p.stderr, str) else p.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"git {' '.join(args)}: {err.strip()[:300]}")
    return p.stdout


# ------------------------------------------------------------------ canonical hunks (SPEC-0205 §2a)
def canon_line(b: bytes) -> bytes:
    """A line's canonical BYTES: valid UTF-8 → NFC-normalised UTF-8; anything else → raw bytes."""
    try:
        return unicodedata.normalize("NFC", b.decode("utf-8", "strict")).encode("utf-8")
    except UnicodeDecodeError:
        return bytes(b)


def hunk_key(removed, added) -> str:
    """Full sha256 over framed line bytes (tag, 4-byte length prefix, 0x1f per line, 0x1e per list).
    Path, line numbers and mode are NOT in the key."""
    h = hashlib.sha256()
    for tag, lines in ((b"R", removed), (b"A", added)):
        h.update(tag)
        for ln in lines:
            h.update(len(ln).to_bytes(4, "big") + ln + b"\x1f")
        h.update(b"\x1e")
    return "h:" + h.hexdigest()


def parse_hunks(diff_bytes: bytes) -> list:
    """Per file of a `git diff -M -U0` byte stream: {path, binary, hunks[(removed, added)]}. Hunk-state
    aware — `---`/`+++` are headers only between `diff --git` and the first `@@`."""
    files, cur = [], None
    removed, added = [], []
    in_hunk = in_header = False

    def flush():
        nonlocal removed, added, in_hunk
        if in_hunk and (removed or added):
            cur["hunks"].append((removed, added))
        removed, added, in_hunk = [], [], False

    for line in diff_bytes.split(b"\n"):
        if line.startswith(b"diff --git "):
            flush()
            cur = {"path": line.split(b" b/", 1)[-1].decode("utf-8", "surrogateescape"),
                   "binary": False, "hunks": []}
            files.append(cur)
            in_header = True
        elif cur is None:
            continue
        elif in_header and (line.startswith(b"Binary files ") or line.startswith(b"GIT binary patch")):
            cur["binary"] = True
        elif line.startswith(b"@@"):
            flush()
            in_hunk, in_header = True, False
        elif in_header:
            continue
        elif in_hunk:
            if line.startswith(b"+"):
                added.append(canon_line(line[1:]))
            elif line.startswith(b"-"):
                removed.append(canon_line(line[1:]))
    flush()
    return files


def exempt_paths(repo, main, paths) -> set:
    """ONE batched `git check-attr --source <main> --stdin yitc-generated`: exempt iff `set` in MAIN's
    tree. A landing branch that adds the attribute itself exempts nothing (the self-grant)."""
    paths = sorted({p for p in paths if p})
    if not paths:
        return set()
    out = _git(repo, "check-attr", "--source", main, "--stdin", EXEMPT_ATTR, inp="\n".join(paths) + "\n")
    ex = set()
    for line in out.splitlines():
        path, _, rest = line.rpartition(f": {EXEMPT_ATTR}: ")
        if rest.strip() == "set" and path:
            ex.add(path)
    return ex


def changed_blobs(repo, base, tip) -> dict:
    """{post-change blob sha: path} for files changed base..tip, deletions excluded."""
    blobs = {}
    for line in _git(repo, "diff", "--raw", "-M", "--no-abbrev", f"{base}..{tip}").splitlines():
        if not line.startswith(":"):
            continue
        meta, path = line.split("\t", 1)[0], line.split("\t")[-1]
        post = meta.split()[3]
        if set(post) != {"0"}:
            blobs[post] = path
    return blobs


def _diff_files(repo, base, tip) -> list:
    return parse_hunks(_git(repo, "diff", "-M", "-U0", "--no-color", "--no-ext-diff", f"{base}..{tip}", raw=True))


def hunk_set(repo, base, tip, main, exempt_acc=None) -> Counter:
    """H(X) as a multiset of canonical hunk keys; binary files and MAIN-exempt paths skipped."""
    files = _diff_files(repo, base, tip)
    ex = exempt_paths(repo, main, [f["path"] for f in files])
    if exempt_acc is not None:
        exempt_acc.update(ex & {f["path"] for f in files})
    keys = Counter()
    for f in files:
        if f["binary"] or f["path"] in ex:
            continue
        for removed, added in f["hunks"]:
            keys[hunk_key(removed, added)] += 1
    return keys


def tree_blobs(repo, ref) -> set:
    return {ln.split()[2] for ln in _git(repo, "ls-tree", "-r", ref).splitlines() if ln.split()[1] == "blob"}


def _subset(a: Counter, b: Counter) -> bool:
    return bool(a) and all(b[k] >= n for k, n in a.items())


# ------------------------------------------------------------------------------ the canonical set
def read_journal_rows(events_path) -> list:
    """MAIN's LIVE logical journal (every segment, oldest first), read at call time — no cache."""
    from lib import journal as _journal   # noqa: PLC0415 — the instrumented segment-aware reader
    return _journal.segment_rows(events_path, types=_FOLD_TYPES)


_FOLD_TYPES = frozenset({"worktree_created", "spike_declared_late", "worktree_create_failed"})


def _row_data(r: dict) -> dict:
    d = r.get("data")
    return d if isinstance(d, dict) else r


def _row_ref(r: dict) -> "tuple[str, str]":
    d = _row_data(r)
    return (str(r.get("ts") or d.get("ts") or ""), str(d.get("session_ref") or r.get("session_ref") or ""))


WORKTREE_STAMP_NAME = "yitc-session-stamp.json"   # mirrors lib/cli.py#WORKTREE_STAMP_NAME (T-0362)


def read_worktree_stamp(wt) -> "dict | None":
    """The worktree's owner stamp from its private git admin dir; None when absent/unreadable."""
    try:
        gd = _git(wt, "rev-parse", "--absolute-git-dir", check=False).strip()
        d = json.loads((Path(gd) / WORKTREE_STAMP_NAME).read_text(encoding="utf-8")) if gd else None
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _live_worktrees(repo) -> dict:
    """{abs path: branch} from `git worktree list --porcelain`."""
    out, cur = {}, None
    for line in _git(repo, "worktree", "list", "--porcelain", check=False).splitlines():
        if line.startswith("worktree "):
            cur = line[len("worktree "):]
            out[cur] = None
        elif line.startswith("branch ") and cur is not None:
            out[cur] = line[len("branch "):].removeprefix("refs/heads/")
    return out


def _tag_annotation(repo, tag) -> "dict | None":
    """The annotated tag's parsed `key: value` message, or None for a lightweight / unreadable tag."""
    if _git(repo, "cat-file", "-t", f"refs/tags/{tag}", check=False).strip() != "tag":
        return None
    body = _git(repo, "cat-file", "tag", f"refs/tags/{tag}", check=False)
    msg = body.split("\n\n", 1)[1] if "\n\n" in body else ""
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^([a-z_]+):[ \t]*(.*)$", msg, re.M)}


def fold_spike_set(repo, rows, read_stamp, exclude_branch=None) -> dict:
    """The canonical spike set from the declaring rows and their projections.

    Declaring rows: `worktree_created{spike: true}` + `spike_declared_late`, minus rows retired by
    `worktree_create_failed` (declared_ts + declared_session_ref). ACTIVE = a live worktree at the row's
    path whose stamp.declared_row equals the row's ref (ref = branch). PARKED = an annotated
    `refs/tags/spike/*` whose annotation names a declaring row (ref = the tag). A projection whose row
    cannot be resolved is returned in `unresolved` and never folded. The landing branch is excluded."""
    retired = {(str(_row_data(r).get("declared_ts") or ""), str(_row_data(r).get("declared_session_ref") or ""))
               for r in rows if r.get("type") == "worktree_create_failed"}
    declaring = {}
    for r in rows:
        d = _row_data(r)
        if (r.get("type") == "worktree_created" and d.get("spike") is True) or r.get("type") == "spike_declared_late":
            ref = _row_ref(r)
            if ref not in retired:
                declaring[ref] = d
    spikes, unresolved = [], []
    live = _live_worktrees(repo)
    for path, br in live.items():
        stamp = (read_stamp or read_worktree_stamp)(Path(path))
        if not (isinstance(stamp, dict) and stamp.get("spike") is True):
            continue
        dr = stamp.get("declared_row") or {}
        ref = (str(dr.get("ts") or ""), str(dr.get("session_ref") or ""))
        row = declaring.get(ref)
        if row is None or str(row.get("path") or "") != path or not br:
            unresolved.append({"projection": "stamp", "path": path, "branch": br, "reason": "no matching declaring row"})
            continue
        if br != exclude_branch:
            spikes.append({"ref": br, "state": "active", "row_ts": ref[0]})
    for tag in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/tags/spike/", check=False).split():
        ann = _tag_annotation(repo, tag)
        if ann is None:
            unresolved.append({"projection": "tag", "ref": tag, "reason": "lightweight tag carries no row ref"})
            continue
        ref = (ann.get("declared_row_ts", ""), ann.get("declared_session_ref", ""))
        if ref not in declaring:
            unresolved.append({"projection": "tag", "ref": tag, "reason": "annotation names no declaring row"})
            continue
        spikes.append({"ref": tag, "state": "parked", "row_ts": ref[0]})
    return {"spikes": spikes, "unresolved": unresolved}


def consumed_prototype_ships(tasks_dir, spike_refs) -> list:
    """Ship commits of DONE cards whose `prototype_ref` names a spike IN the folded set — bounded by the
    set's size: a card whose prototype is not in the set is never read past its header keys."""
    wanted = set(spike_refs)
    if not wanted or not tasks_dir or not Path(tasks_dir).is_dir():
        return []
    from lib import state as _state   # noqa: PLC0415 — the governed card reader (memoized)
    ships = []
    for f in sorted(Path(tasks_dir).glob("T-*.yaml")):
        card = _state.load_path(f)
        if not isinstance(card, dict) or str(card.get("prototype_ref") or "") not in wanted:
            continue
        commit = str(card.get("commit") or "")
        if card.get("status") == "done" and re.fullmatch(r"[0-9a-f]{7,40}", commit):
            ships.append(commit)
    return ships


# ---------------------------------------------------------------------------------- the verdict
def content_verdict(repo, landing, spikes, main="main", consumed_refs=()) -> dict:
    """T1 then T3 over the landing diff against the folded spikes. Returns the row payload fragment:
    verdict identity|report|none, t1_hits, t1_spikes, spikes_matched, t3_verdict, share, ambiguous, exempt."""
    exempt = set()
    mb_l = _git(repo, "merge-base", main, landing).strip()
    H_L = hunk_set(repo, mb_l, landing, main, exempt)
    blobs_L = {b: p for b, p in changed_blobs(repo, mb_l, landing).items()}
    ex_L = exempt_paths(repo, main, blobs_L.values())
    exempt |= ex_L
    main_tree = tree_blobs(repo, main)
    H_main = hunk_set(repo, mb_l, main, main)
    for ship in consumed_refs:
        H_main = H_main | hunk_set(repo, f"{ship}^", ship, main)
    folds = {}
    for s in spikes:
        mb_s = _git(repo, "merge-base", main, s).strip()
        folds[s] = {"H": hunk_set(repo, mb_s, s, main), "blobs": changed_blobs(repo, mb_s, s)}
    nHL = sum(H_L.values())
    res = {"verdict": "none", "t1_hits": [], "t1_spikes": [], "spikes_matched": [], "t3_verdict": "none",
           "share": None, "best_spike": None, "ambiguous": False, "ambiguous_spikes": [],
           "exempt": sorted(exempt), "landing_hunks": nHL}
    if not folds or (not H_L and not blobs_L):
        res["share"] = f"0/{nHL}"
        return res
    for s, fd in folds.items():
        for blob, path in blobs_L.items():
            if blob == EMPTY_BLOB or blob in main_tree or path in ex_L:
                continue
            if blob in fd["blobs"]:
                res["t1_hits"].append({"file": path, "spike": s, "spike_file": fd["blobs"][blob], "blob": blob})
    res["t1_spikes"] = sorted({h["spike"] for h in res["t1_hits"]})
    res["spikes_matched"] = [s for s, fd in folds.items() if _subset(H_L, fd["H"] - H_main)]
    res["t3_verdict"] = "identity" if res["spikes_matched"] else ("report" if nHL else "none")
    best = None
    for s, fd in folds.items():
        others = Counter()
        for k, o in folds.items():
            if k != s:
                others = others | o["H"]
        A = H_L & ((fd["H"] - H_main) - others)
        if best is None or sum(A.values()) > sum(best[1].values()):
            best = (s, A)
    if res["spikes_matched"]:
        res["best_spike"] = res["spikes_matched"][0]
        res["share"] = f"{nHL}/{nHL}"
    elif best and best[1]:
        res["best_spike"] = best[0]
        res["share"] = f"{sum(best[1].values())}/{nHL}"
    else:
        res["share"] = f"0/{nHL}"
    if len(folds) >= 2 and H_L:
        shared = [k for k in H_L if sum(1 for fd in folds.values() if fd["H"][k] > 0) >= 2]
        if shared:
            res["ambiguous"] = True
            res["ambiguous_spikes"] = sorted({s for s, fd in folds.items() if any(fd["H"][k] > 0 for k in shared)})
    res["verdict"] = "identity" if (res["t1_hits"] or res["spikes_matched"]) else "report"
    return res


def report_line(payload: dict) -> str:
    # the mode is derived through refusal_message, so the switch keeps ONE reader (the T-12570 purity pin)
    enforcing = refusal_message({"verdict": "identity"}) is not None
    if payload.get("error"):
        return (f"spike-content: not computed ({payload['error']}) — "
                + ("enforcing, but an uncomputed verdict never refuses — land proceeds" if enforcing
                   else "report-only, land proceeds"))
    mode = "enforcing — land refused" if enforcing else "report-only (L2a), land proceeds"
    parts = []
    if payload.get("t1_hits"):
        files = ", ".join(sorted({h["file"] for h in payload["t1_hits"]}))
        parts.append(f"spike-content: IDENTITY (T1 blob) {files} match {' ∪ '.join(payload['t1_spikes'])} — {mode}")
    if payload.get("spikes_matched"):
        parts.append(f"spike-content: IDENTITY (T3) {payload['share']} hunks match {' ∪ '.join(payload['spikes_matched'])} — {mode}")
    if not parts:
        best = payload.get("best_spike")
        parts.append(f"spike-content: {payload.get('share')} hunks match {best}" if best
                     else f"spike-content: {payload.get('share')} hunks match any declared spike ({len(payload.get('spikes') or [])} folded)")
        if enforcing:
            parts[-1] += " — enforcing"
    line = "; ".join(parts)
    if payload.get("ambiguous"):
        line += f" — ambiguous attribution ({' ∪ '.join(payload['ambiguous_spikes'])})"
    if payload.get("exempt"):
        line += f" — exempt: {', '.join(payload['exempt'])}"
    if payload.get("unresolved"):
        line += f" — unresolved projection(s) not trusted: {', '.join(u.get('ref') or u.get('path') or '?' for u in payload['unresolved'])}"
    return line


def refusal_message(payload) -> "str | None":
    """T-12570 — the refusal text for an IDENTITY verdict, or None. Pure and flag-blind: its ONLY input
    is the verdict payload, so no land override flag and no `emergency:` commit marker can reach it.
    None when the switch is OFF, when the verdict could not be computed, or when it is not identity."""
    if not REFUSE_SPIKE_CONTENT or not isinstance(payload, dict) or payload.get("error"):
        return None
    if payload.get("verdict") != "identity":
        return None
    refs = sorted(set(payload.get("t1_spikes") or []) | set(payload.get("spikes_matched") or []))
    routes = []
    if payload.get("t1_hits"):
        files = ", ".join(sorted({h["file"] for h in payload["t1_hits"]}))
        routes.append(f"T1 whole-file blob identity ({files} → {' ∪ '.join(payload['t1_spikes'])})")
    if payload.get("spikes_matched"):
        routes.append(f"T3 change-set identity ({payload.get('share')} hunks ⊆ {' ∪ '.join(payload['spikes_matched'])})")
    return (f"land: REFUSED — {payload.get('branch')} integrates declared spike CONTENT: {'; '.join(routes)}. "
            f"Matching spike(s): {', '.join(refs)}. A spike's content never integrates by any route "
            f"(SPEC-0205 rule 2) — no land override flag (--rebaseline, --no-tests, …) and no `emergency:` "
            f"commit marker admits it.\n"
            f"  THE GOVERNED EXIT: `bin/yitc-v2 worktree park` the spike → it is kept as the annotated tag "
            f"`spike/<slug>` → file a card with `prototype_ref: spike/<slug>` and re-implement it there "
            f"under audit-pre and audit-post. Remove the copied content from this branch to land the rest.")


def _run(repo, branch, *, events_path, append_event, read_stamp, task_id, preview, reservation_ts,
         tasks_dir, main, _before_fold, _print, row_events_path=None) -> dict:
    t0 = time.perf_counter()
    # every contract key present up front, so the error path still writes the full AC2 payload
    # report_only is TRUE only when no refusal can follow: a preview never refuses; a governed check refuses
    # an identity verdict iff the switch is ON (read through refusal_message, the switch's one reader)
    payload = {"branch": branch, "report_only": bool(preview) or refusal_message({"verdict": "identity"}) is None,
               "reservation_ts": reservation_ts, "spikes": [],
               "unresolved": [], "consumed_ships": [], "verdict": "none", "t1_hits": [], "t1_spikes": [],
               "spikes_matched": [], "t3_verdict": "none", "share": None, "best_spike": None,
               "ambiguous": False, "ambiguous_spikes": [], "exempt": [], "landing_hunks": None}
    if preview:
        payload["preview"] = True
    try:
        if _before_fold is not None:
            _before_fold()
        rows = read_journal_rows(events_path)
        payload["fold_read_ts"] = _now_iso()
        fold = fold_spike_set(repo, rows, read_stamp, exclude_branch=branch)
        refs = [s["ref"] for s in fold["spikes"]]
        payload["spikes"] = refs
        payload["unresolved"] = fold["unresolved"]
        ships = consumed_prototype_ships(tasks_dir if tasks_dir is not None else Path(repo) / "tasks", refs)
        payload["consumed_ships"] = ships
        payload.update(content_verdict(repo, branch, refs, main=main, consumed_refs=ships))
    except Exception as e:  # noqa: BLE001 — report-only arm: never raises, never aborts the land
        payload.setdefault("fold_read_ts", _now_iso())
        payload["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    payload["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    try:
        append_event(PREVIEWED_EVENT if preview else CHECKED_EVENT, task_id, payload,
                     events_path=row_events_path or events_path)
    except Exception as e:  # noqa: BLE001
        payload["append_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    try:
        _print(report_line(payload))
    except Exception:  # noqa: BLE001
        pass
    return payload


def check_spike_content(repo, branch, *, events_path, append_event, reservation_ts=None, read_stamp=None,
                        task_id=None, tasks_dir=None, main="main", row_events_path=None, _before_fold=None,
                        _print=print) -> dict:
    """The land entry: ONE `spike_content_checked` row per call. `events_path` is MAIN's journal (the
    fold source); `row_events_path` is where the row is written (land: the branch journal), default
    `events_path`."""
    return _run(repo, branch, events_path=events_path, append_event=append_event, read_stamp=read_stamp,
                task_id=task_id, preview=False, reservation_ts=reservation_ts, tasks_dir=tasks_dir, main=main,
                _before_fold=_before_fold, _print=_print, row_events_path=row_events_path)


def preview_spike_content(repo, branch, *, events_path, append_event, read_stamp=None, task_id=None,
                          tasks_dir=None, main="main", _print=print) -> dict:
    """The pre-land dry run: writes ONLY `spike_content_previewed{preview: true}`, never `_checked`.
    Its governed caller is the audit packet (T-12571)."""
    return _run(repo, branch, events_path=events_path, append_event=append_event, read_stamp=read_stamp,
                task_id=task_id, preview=True, reservation_ts=None, tasks_dir=tasks_dir, main=main,
                _before_fold=None, _print=_print)
