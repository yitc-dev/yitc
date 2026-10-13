"""T-12567 (SPEC-0205 rules 2 + 2a) — spike CONTENT identity at land (L2a), refusal ENABLED by L2c.

ONE helper, run once per governed land attempt AFTER `_spike_land_verdict` and after the land
reservation is taken. It folds the canonical spike set from MAIN's live journal rows + their
projections (ACTIVE: stamp ⇄ `worktree_created{spike}` row; PARKED: annotated `spike/<slug>` tag ⇄
row), computes T1 (changed-blob identity) and T3 (canonical hunk-subset identity), journals ONE row
and prints the report line. The helper itself never refuses: the land's step 2d refuses an identity
verdict through `refusal_message` while REFUSE_SPIKE_CONTENT is ON (shipped ON since T-12573), and the
row's `report_only` / the report line say which mode ran. It NEVER raises: an internal error is
recorded on the row and the land proceeds (an uncomputed verdict never refuses).

T-13856 (SPEC-0205 rules 2/2a/5): a card that names its prototype may DECLARE, per path and with a
reason, a file that comes out byte-identical to the prototype's by construction. The declaration is
read at the landing tip, and only when a verdict of identity is about to be returned; a path is
admitted against the card's own prototype only when the card's audit-pre record shows the auditor was
handed that very entry. Every other file, and every other spike, is judged exactly as before.

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
DECLARATION_FIELD = "prototype_identical"         # T-13856 — the card field (SPEC-0028)
SHOWN_FIELD = "prototype_identical_shown"         # T-13856 — what a task audit-pre record says its packet showed

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


_C_ESCAPES = {b"a": 7, b"b": 8, b"t": 9, b"n": 10, b"v": 11, b"f": 12, b"r": 13, b'"': 34, b"\\": 92}


def unquote_git_path(raw: bytes) -> "bytes | None":
    """A path as git prints it in a patch header: as it is, or C-quoted between double quotes (a
    backslash escape or three octal digits per quoted byte). None when the quoting does not parse."""
    if not raw.startswith(b'"'):
        return raw
    if len(raw) < 2 or not raw.endswith(b'"'):
        return None
    body, out, i = raw[1:-1], bytearray(), 0
    while i < len(body):
        ch = body[i:i + 1]
        if ch == b'"':
            return None
        if ch != b"\\":
            out += ch
            i += 1
            continue
        nxt, octal = body[i + 1:i + 2], body[i + 1:i + 4]
        if nxt in _C_ESCAPES:
            out.append(_C_ESCAPES[nxt])
            i += 2
        elif len(octal) == 3 and all(48 <= d <= 55 for d in octal) and int(octal, 8) <= 255:
            out.append(int(octal, 8))
            i += 4
        else:
            return None
    return bytes(out)


def parse_hunks(diff_bytes: bytes) -> list:
    """Per file of a `git diff -M -U0` byte stream: {path, binary, hunks[(removed, added)]}. Hunk-state
    aware — `---`/`+++` are headers only between `diff --git` and the first `@@`. A file whose patch
    carries a `+++ b/<path>` header also gets `new_path` (T-13856), unquoted when git quoted it: that
    line names ONE path, where the `diff --git` line names two and cannot be split for a name
    containing ` b/` or for a quoted name."""
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
            if line.startswith(b"+++ "):        # git ends an unquoted name with ONE tab when it holds a space
                name = unquote_git_path(line[4:].removesuffix(b"\t"))
                if name is not None and name.startswith(b"b/"):
                    cur["new_path"] = name[2:].decode("utf-8", "surrogateescape")
            continue
        elif in_hunk:
            if line.startswith(b"+"):
                added.append(canon_line(line[1:]))
            elif line.startswith(b"-"):
                removed.append(canon_line(line[1:]))
    flush()
    return files


def exempt_paths(repo, main, paths, nul=False) -> set:
    """ONE batched `git check-attr --source <main> --stdin yitc-generated`: exempt iff `set` in MAIN's
    tree. A landing branch that adds the attribute itself exempts nothing (the self-grant). `nul`
    (T-13856) is for paths taken from NUL-separated git output: they are passed and read back
    NUL-framed, so a name git would quote compares as itself."""
    paths = sorted({p for p in paths if p})
    if not paths:
        return set()
    if nul:
        toks = _git(repo, "check-attr", "--source", main, "-z", "--stdin", EXEMPT_ATTR, inp="\0".join(paths) + "\0").split("\0")
        return {toks[i] for i in range(0, len(toks) - 2, 3) if toks[i + 1] == EXEMPT_ATTR and toks[i + 2] == "set"}
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


def changed_files(repo, base, tip) -> list:
    """[(path, post-change blob sha)] for files changed base..tip, deletions excluded: ONE row per
    path, the path as git stores it (NUL-separated output is never quoted)."""
    toks = _git(repo, "diff", "--raw", "-z", "-M", "--no-abbrev", f"{base}..{tip}").split("\0")
    rows, i = [], 0
    while i < len(toks) and toks[i].startswith(":"):
        meta = toks[i].split()
        width = 2 if meta[4][:1] in ("R", "C") else 1     # a rename / copy row carries source then destination
        if set(meta[3]) != {"0"}:
            rows.append((toks[i + width], meta[3]))
        i += 1 + width
    return rows


def _diff_files(repo, base, tip) -> list:
    return parse_hunks(_git(repo, "diff", "-M", "-U0", "--no-color", "--no-ext-diff", f"{base}..{tip}", raw=True))


def hunk_set(repo, base, tip, main, exempt_acc=None, by_path=None) -> Counter:
    """H(X) as a multiset of canonical hunk keys; binary files and MAIN-exempt paths skipped. `by_path`
    (T-13856), when given, receives — for each file this call counted whose patch header names a path
    — the keys it counted for that file, and nothing for a file it skipped: what a caller takes back
    out for a file is then something this call put in for it."""
    files = _diff_files(repo, base, tip)
    ex = exempt_paths(repo, main, [f["path"] for f in files])
    if exempt_acc is not None:
        exempt_acc.update(ex & {f["path"] for f in files})
    keys = Counter()
    for f in files:
        if f["binary"] or f["path"] in ex:
            continue
        for removed, added in f["hunks"]:
            key = hunk_key(removed, added)
            keys[key] += 1
            if by_path is not None and f.get("new_path"):
                by_path.setdefault(f["new_path"], Counter())[key] += 1
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


# ------------------------------------------------- the card's declaration (SPEC-0205 rules 2/2a/5)
def plain_text(text) -> bool:
    """One line of text, as this module checks it: a non-empty string with no surrounding space and
    no character that is a control character, a line or paragraph separator, or an unpaired surrogate
    (Unicode categories Cc, Zl, Zp, Cs)."""
    return (isinstance(text, str) and bool(text) and text == text.strip()
            and not any(unicodedata.category(ch) in ("Cc", "Zl", "Zp", "Cs") for ch in text))


def plain_path(path) -> bool:
    """A declared path is ONE literal repo-relative file path: plain text, never absolute, never a
    directory, no empty / `.` / `..` segment, and no character git quotes in a diff header (so it is
    compared as written). Nothing here reads a pattern: `*` is an ordinary character of a file name."""
    if not plain_text(path):
        return False
    if path.startswith("/") or any(seg in ("", ".", "..") for seg in path.split("/")):
        return False
    return not any(ch in '"\\' for ch in path)


def declaration_line(entry) -> str:
    """The one line an entry renders as in the audit-pre packet."""
    return f"- `{entry['path']}` — reason: {entry['reason']}\n"


def declaration_entries(card) -> "tuple[list, str | None]":
    """The card's declaration as ([{path, reason}], None), or ([], fault) when the stored value is not
    a well-formed one. An absent key, null and an empty list all declare nothing. A malformed value is
    never read in part: one bad entry and the whole declaration is unreadable. The entries' rendered
    lines are bounded together: the packet section that shows them is one the packet's size bound does
    not cut, so it has to be small on its own. For the same reason a fault names an entry by its
    NUMBER and carries no text of the card."""
    limit = 16_000      # bytes of rendered entry lines: the whole declaration, read by an auditor in one pass
    raw = card.get(DECLARATION_FIELD) if isinstance(card, dict) else None
    if raw is None or raw == []:
        return [], None
    if not isinstance(raw, list):
        return [], "is not a list of entries"
    out, seen = [], set()
    for n, entry in enumerate(raw, 1):
        if not isinstance(entry, dict) or set(entry) != {"path", "reason"}:
            return [], f"entry {n} is not a mapping of exactly `path` and `reason`"
        path, reason = entry["path"], entry["reason"]
        if not plain_path(path):
            return [], f"entry {n}: `path` is not one literal repo-relative file path"
        if not isinstance(reason, str) or not reason.strip():
            return [], f"entry {n} carries no reason"
        if not plain_text(reason):
            return [], f"entry {n}: the reason is not one plain line of text (no line break, control character or surrounding space)"
        if path in seen:
            return [], f"entry {n} declares a path an earlier entry already declares"
        seen.add(path)
        out.append({"path": path, "reason": reason})
    size = sum(len(declaration_line(e).encode("utf-8")) for e in out)
    if size > limit:
        return [], f"renders as {size} bytes of entries, over the {limit} its audit packet section holds"
    return out, None


def declaration_shown(card) -> "dict | None":
    """What a task audit-pre packet shows the auditor of the card's declaration — the value that pass
    records under SHOWN_FIELD, and the land compares entry by entry. None when the card declares
    nothing readable or names no prototype."""
    ref = card.get("prototype_ref") if isinstance(card, dict) else None
    entries, fault = declaration_entries(card)
    if fault or not entries or not isinstance(ref, str) or not plain_text(ref.strip()):
        return None
    return {"prototype_ref": ref.strip(), "declared": entries}


def declaration_packet_block(card) -> str:
    """The audit-pre packet text for the card's declaration — '' when it declares nothing. Rendered
    from the same entries `declaration_shown` records, so what the record says was shown IS this text."""
    entries, fault = declaration_entries(card)
    if fault:
        return ("\n### Declared identical to the prototype — UNREADABLE\n"
                f"The card's `{DECLARATION_FIELD}` value {fault}. Nothing is declared: `land` admits no "
                "file on it.\n")
    if not entries:
        return ""
    return ("\n### Declared identical to the prototype by construction (SPEC-0205 rule 5)\n"
            "The card declares that each file below will come out BYTE-IDENTICAL to the prototype's file "
            "at the same path — not because it is copied, but because any correct implementation of this "
            "card yields those exact bytes:\n"
            + "".join(declaration_line(e) for e in entries)
            + "JUDGE EACH ENTRY NOW, before any code is written: you are the only judge it gets. An entry "
            "holds only when its reason shows that the WHOLE content of the file is determined by the task "
            "— a generated or declarative file such as a route list, a lockfile or a registry, where this "
            "card's change leaves no other correct bytes. Check it against the prototype diff below. A "
            "reason that amounts to convenience, to «it is the same code», or that does not account for the "
            "whole file is a RED finding naming the path, never a YELLOW: an entry this pass does not block "
            "lets `land` admit exactly that path against exactly this prototype. Every file NOT listed here "
            "is still refused on exact identity.\n")


def _tip_file(repo, rev, directory, wanted, recursive=False) -> "str | None":
    """Text of the ONE file under `directory` at `rev` whose base name `wanted` accepts; None when
    there is none, or more than one."""
    args = ["ls-tree", "-z", "--name-only", *(["-r"] if recursive else []), rev, "--", directory + "/"]
    names = [n for n in _git(repo, *args).split("\0") if n and wanted(n.rsplit("/", 1)[-1])]
    return _git(repo, "show", f"{rev}:{names[0]}") if len(names) == 1 else None


def _blob_at(repo, rev, path) -> "str | None":
    """The blob sha `rev` holds at exactly `path` (the path is taken literally), or None."""
    oid = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}:{path}", check=False).strip()
    return oid if oid and _git(repo, "cat-file", "-t", oid, check=False).strip() == "blob" else None


def landing_declaration(repo, landing, task_id) -> dict:
    """The landing CARD's declaration and what its audit-pre RECORD shows of it, both read at the
    landing tip — the judged subject, never a working tree. Returns {prototype_ref, entries, shown,
    fault}: `shown` lists the declared paths whose very entry (path AND reason) the record says its
    packet carried, for this prototype, on a pass the auditor did not block. Never raises: whatever
    cannot be read admits nothing."""
    out = {"prototype_ref": None, "entries": [], "shown": [], "fault": None}
    tid = str(task_id or "")
    if not re.fullmatch(r"T-[0-9]+", tid):
        return out
    try:
        from lib import state as _state   # noqa: PLC0415 — the governed YAML reader
        text = _tip_file(repo, landing, "tasks",
                         lambda n: n.endswith(".yaml") and (n == f"{tid}.yaml" or n.startswith(f"{tid}-")))
        card = _state.load_str(text) if text is not None else None
        if not isinstance(card, dict) or str(card.get("id") or "") != tid:
            return out
        ref = card.get("prototype_ref")
        if isinstance(ref, str) and plain_text(ref.strip()):
            out["prototype_ref"] = ref.strip()
        entries, fault = declaration_entries(card)
        if fault:
            out["fault"] = f"the card's declaration {fault}"
            return out
        if entries and not out["prototype_ref"]:
            out["fault"] = "the card declares paths but names no prototype_ref"
            return out
        out["entries"] = entries
        if not entries:
            return out
        rec_text = _tip_file(repo, landing, "decisions", lambda n: n == f"{tid}-audit-pre.yaml", recursive=True)
        rec = _state.load_str(rec_text) if rec_text is not None else None
        shown = rec.get(SHOWN_FIELD) if isinstance(rec, dict) else None
        passed = ("GREEN", "YELLOW")
        if (isinstance(shown, dict) and rec.get("verdict") in passed
                and rec.get("verdict_as_returned", "GREEN") in passed   # absent = the verdict is the auditor's own
                and shown.get("prototype_ref") == out["prototype_ref"]
                and isinstance(shown.get("declared"), list)):
            out["shown"] = [e["path"] for e in entries if e in shown["declared"]]
    except Exception as e:  # noqa: BLE001 — an unreadable declaration admits nothing
        out.update(entries=[], shown=[], fault=f"the declaration could not be read ({type(e).__name__})")
    return out


def _admit_declared(repo, landing, decl, folds) -> "tuple[set, list]":
    """Which declared paths are admitted against the card's own prototype, and why each other one is
    not. Admitted = the prototype is a folded spike, the audit-pre record shows the entry, and the
    landing file at that path is the same blob as the prototype's file at that same path."""
    own, admitted, notes = decl.get("prototype_ref"), set(), []
    shown = set(decl.get("shown") or [])
    for entry in decl.get("entries") or []:
        path = entry["path"]
        if own not in folds:
            why = "the card's prototype is not in the declared spike set"
        elif path not in shown:
            why = "not shown to the auditor by the card's audit-pre"
        else:
            mine = _blob_at(repo, landing, path)
            if mine is not None and mine == _blob_at(repo, own, path):
                admitted.add(path)
                continue
            why = "not the same file as the prototype's at that path"
        notes.append({"file": path, "why": why})
    if decl.get("fault"):
        notes.append({"file": "(declaration)", "why": decl["fault"]})
    return admitted, notes


# ---------------------------------------------------------------------------------- the verdict
def content_verdict(repo, landing, spikes, main="main", consumed_refs=(), declaration=None) -> dict:
    """T1 then T3 over the landing diff against the folded spikes. Returns the row payload fragment:
    verdict identity|report|none, t1_hits, t1_spikes, spikes_matched, t3_verdict, share, ambiguous, exempt.

    `declaration` (T-13856) is a zero-argument callable returning `landing_declaration`'s mapping. It
    is called at most once, and only when the verdict would otherwise be identity. A path it admits
    leaves BOTH tests and the share AGAINST THE CARD'S OWN PROTOTYPE ONLY and is listed in
    `declared_identical`; against every other spike the landing is judged whole, as before."""
    exempt = set()
    mb_l = _git(repo, "merge-base", main, landing).strip()
    counted = {}     # T-13856 — per landing path, the hunk keys H_L holds for it
    H_L = hunk_set(repo, mb_l, landing, main, exempt, by_path=counted)
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
           "exempt": sorted(exempt), "landing_hunks": nHL,
           "card_prototype_ref": None, "declared_identical": [], "declared_not_admitted": []}
    if not folds or (not H_L and not blobs_L):
        res["share"] = f"0/{nHL}"
        return res
    # T-13856 — `own` is the card's prototype once at least one declared path is admitted against it;
    # `open_blobs` then maps each landing blob to an OPEN path that carries it — one that is neither
    # admitted nor yitc-generated on main (a blob no open path carries is absent) — and `own_L` is the
    # landing hunk set without the hunks the admitted paths share with that prototype.
    # With nothing admitted `own` is None, so no spike equals it and every line below reads as before.
    own, open_blobs, own_L = None, {}, H_L

    def landing_for(s):
        return own_L if s == own else H_L

    def identity():
        hits = []
        for s, fd in folds.items():
            for blob, path in blobs_L.items():
                if blob == EMPTY_BLOB or blob in main_tree or path in ex_L:
                    continue
                if blob in fd["blobs"]:
                    if s == own:
                        if blob not in open_blobs:
                            continue
                        path = open_blobs[blob]
                    hits.append({"file": path, "spike": s, "spike_file": fd["blobs"][blob], "blob": blob})
        return hits, [s for s, fd in folds.items() if _subset(landing_for(s), fd["H"] - H_main)]

    first = identity()
    res["t1_hits"], res["spikes_matched"] = first
    if declaration is not None and (first[0] or first[1]):
        try:
            decl = declaration() or {}
            res["card_prototype_ref"] = decl.get("prototype_ref") if decl.get("prototype_ref") in folds else None
            admitted, notes = _admit_declared(repo, landing, decl, folds)
            if admitted:
                files = changed_files(repo, mb_l, landing)
                generated = exempt_paths(repo, main, [path for path, _ in files], nul=True)
                opened = {}
                for path, blob in files:      # an OPEN path: not admitted, and not yitc-generated on main
                    if path not in admitted and path not in generated:
                        opened.setdefault(blob, path)
                # what an admitted file takes out of the set is what the set COUNTED for it (nothing,
                # when it was skipped there) under each key the prototype carries — the whole count,
                # not that count less what main also carries and not capped by the prototype's own
                # count: a remainder left in the set would be judged against this prototype as the
                # branch's hunk. A hunk whose key the prototype does not carry counted as the
                # branch's own before, and still does
                carried = folds[decl["prototype_ref"]]["H"]
                mine = Counter()
                for path in admitted:
                    mine += counted.get(path, Counter())
                shared = Counter({key: n for key, n in mine.items() if carried[key] > 0})
                own, open_blobs, own_L = decl["prototype_ref"], opened, H_L - shared
                res["declared_identical"] = sorted(admitted)
                res["t1_hits"], res["spikes_matched"] = identity()
            res["declared_not_admitted"] = notes
        except Exception as e:  # noqa: BLE001 — a declaration that cannot be applied admits nothing:
            own, open_blobs, own_L = None, {}, H_L   # the verdict computed without it stands, computed
            res["t1_hits"], res["spikes_matched"] = first
            res["declared_identical"] = []
            res["declared_not_admitted"] = [{"file": "(declaration)", "why": f"could not be applied ({type(e).__name__})"}]
    res["t1_spikes"] = sorted({h["spike"] for h in res["t1_hits"]})
    res["t3_verdict"] = "identity" if res["spikes_matched"] else ("report" if nHL else "none")
    best = None
    for s, fd in folds.items():
        others = Counter()
        for k, o in folds.items():
            if k != s:
                others = others | o["H"]
        A = landing_for(s) & ((fd["H"] - H_main) - others)
        if best is None or sum(A.values()) > sum(best[1].values()):
            best = (s, A)
    if res["spikes_matched"]:
        res["best_spike"] = res["spikes_matched"][0]
        n = sum(landing_for(res["best_spike"]).values())
        res["share"] = f"{n}/{n}"
    elif best and best[1]:
        res["best_spike"] = best[0]
        res["share"] = f"{sum(best[1].values())}/{sum(landing_for(best[0]).values())}"
    else:
        res["share"] = f"0/{sum(own_L.values())}"
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
    if payload.get("declared_identical"):
        line += (f" — declared identical by construction, judged at audit-pre ({payload.get('card_prototype_ref')}): "
                 f"{', '.join(payload['declared_identical'])}")
    if payload.get("declared_not_admitted"):
        line += " — declared but not admitted: " + "; ".join(
            f"{n.get('file')} ({n.get('why')})" for n in payload["declared_not_admitted"])
    if _own_prototype_files(payload):
        line += (f" — this card names that prototype: a file identical BY CONSTRUCTION is declared on the card "
                 f"and judged at audit-pre BEFORE `task close` (SPEC-0205 rule 5)")
    if payload.get("unresolved"):
        line += f" — unresolved projection(s) not trusted: {', '.join(u.get('ref') or u.get('path') or '?' for u in payload['unresolved'])}"
    return line


def _own_prototype_files(payload) -> list:
    """The T1 files that hit the prototype the landing card itself names (empty when it names none)."""
    own = payload.get("card_prototype_ref")
    return sorted({h.get("file") for h in payload.get("t1_hits") or []
                   if own and isinstance(h, dict) and h.get("spike") == own and h.get("file")})


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
    msg = (f"land: REFUSED — {payload.get('branch')} integrates declared spike CONTENT: {'; '.join(routes)}. "
           f"Matching spike(s): {', '.join(refs)}. A spike's content never integrates by any route "
           f"(SPEC-0205 rule 2) — no land override flag (--rebaseline, --no-tests, …) and no `emergency:` "
           f"commit marker admits it.\n"
           f"  THE GOVERNED EXIT: `bin/yitc-v2 worktree park` the spike → it is kept as the annotated tag "
           f"`spike/<slug>` → file a card with `prototype_ref: spike/<slug>` and re-implement it there "
           f"under audit-pre and audit-post. Remove the copied content from this branch to land the rest.")
    own_files = _own_prototype_files(payload)
    if own_files:
        # T-13856 — the card is ALREADY on the route above, so that exit cannot be taken for these files.
        branch = str(payload.get("branch") or "")
        tid = branch.split("/", 1)[1] if branch.startswith("task/") else "<T-XXXX>"
        msg += (f"\n  THIS CARD ALREADY NAMES THAT PROTOTYPE (prototype_ref: {payload.get('card_prototype_ref')}), "
                f"so for {', '.join(own_files)} the exit is a different one. A file that comes out byte-identical "
                f"to the prototype's BY CONSTRUCTION is DECLARED on the card, per path and with a reason — "
                f"`bin/yitc-v2 task update {tid} --set-field prototype_identical --from-file <path>` (a YAML list "
                f"of `path:` + `reason:` entries) — and JUDGED by the external auditor at `bin/yitc-v2 audit pre "
                f"--task {tid}`, before the work; `land` then admits exactly the declared paths against exactly "
                f"this prototype and still refuses every other file. A card already closed on this branch takes "
                f"that route from a fresh claim — the discard-and-re-claim recipe, `bin/yitc-v2 graph query "
                f"rare-task-recovery-recipes` — and declares before its audit-pre. A file that is NOT "
                f"identical by construction is re-implemented so that it differs.")
    notes = payload.get("declared_not_admitted") or []
    if notes:
        msg += "\n  Declared on the card but NOT admitted: " + "; ".join(
            f"{n.get('file')} — {n.get('why')}" for n in notes if isinstance(n, dict)) + "."
    return msg


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
               "ambiguous": False, "ambiguous_spikes": [], "exempt": [], "landing_hunks": None,
               "card_prototype_ref": None, "declared_identical": [], "declared_not_admitted": []}
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
        payload.update(content_verdict(repo, branch, refs, main=main, consumed_refs=ships,
                                       declaration=lambda: landing_declaration(repo, branch, task_id)))
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
