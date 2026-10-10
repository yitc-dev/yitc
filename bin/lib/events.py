"""Event-emit primitive for the yitc-v2 CLI — the single journal-write path (CHARTER §P5 "one journal").

This is the home for the one append path into events.jsonl: envelope build + provenance fields
(D-0030) + the SPEC-0002 per-line byte cap + the flock-serialized O_APPEND write. bin/yitc-v2 keeps a
thin `_append_event` wrapper that resolves the host-coupled inputs (session_ref, the target path incl.
the YITC_EVENTS_SINK test quarantine + the current EVENTS_PATH, and the SPEC-0078 consumer→engine write
guard) and delegates here — so this module reads NO host global and stays identity-agnostic.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). The
REPO_ROOT/EVENTS_PATH coupling and the session-identity resolver deliberately STAY in the host: this
primitive takes the already-resolved `session_ref`, `ts`, and `events_path` by INJECTION (the state.py
`rel_root` precedent), so a `-C` rebind and the test monkeypatch of `yitc.EVENTS_PATH` are honored by the
host wrapper at call time. Behaviour is byte-identical to the inline original (T-0357 sink precedence and
T-0464 flock live in the wrapper + here respectively) — the test suite is the oracle.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from lib import vocab  # T-12930: the prescribed temp-file recipe (help-text vocabulary)
from lib import lockfile  # the ONE flock-target open (X-0226 / T-10189 / T-10250 idiom, T-10336)

SOURCE_TAG = "yitc-v2-cli"
MAX_EVENT_BYTES = 3500     # SPEC-0002 per-line byte cap (PIPE_BUF 4096 − margin)

# T-12488 (SPEC-0025 §deviation_captured): the OPTIONAL `class` key of a capture — a CHARTER §AI failure
# class id from the SPEC-0023 table (ids only; the test pins this tuple against that table). Absent stays
# legal (capture is a reflex, D-0086 §2); a present value must be an id, so the T3 class tally can count it.
FAILURE_CLASS_IDS = tuple(range(1, 21))
_FAILURE_CLASS_RE = re.compile(r"\A#?([0-9]+)\Z")


def normalize_failure_class(value):
    """Return (int id, None) for a valid failure-class id — an int, or "N" / "#N" — else (None, error).
    A bool is refused (it is an int subclass in Python, never a class id)."""
    n = None
    if isinstance(value, int) and not isinstance(value, bool):
        n = value
    elif isinstance(value, str):
        m = _FAILURE_CLASS_RE.match(value)   # raw — only "N" / "#N", no surrounding whitespace
        n = int(m.group(1)) if m else None
    if n in FAILURE_CLASS_IDS:
        return n, None
    return None, (f"invalid `class` {value!r} — a CHARTER §AI failure class id is required: one of "
                  f"{FAILURE_CLASS_IDS[0]}..{FAILURE_CLASS_IDS[-1]} (int, \"N\" or \"#N\"; the SPEC-0023 "
                  f"list). Free text belongs in `relates_to`; omit `class` when unsure.")

# T-10401 — the TEST-RUN journal hermeticity guard: an os.pathsep-joined list of LIVE journals that the
# CURRENT process must never append to. Set by the test harness ONLY (tests/conftest.py for a pytest run;
# worktree.py `_hermetic_child_env` for each non-allowlisted child of the standalone pinned suite) — it is
# UNSET in production, where this whole guard is inert.
#
# It lives HERE, at the single journal-write path (T-9247), because that is the ONLY seam that sees the
# FINAL resolved target: the yitc `_append_event` wrapper resolves it through THREE routes (YITC_EVENTS_SINK
# > explicit `events_path=` > EVENTS_PATH), and the leak this closes came through the explicit-arg route
# (lib/dispatch.py passes `events_path=_main_worktree(REPO_ROOT)/"events.jsonl"`), which OVERRIDES a test's
# EVENTS_PATH patch AND outranks the T-10073 low-precedence YITC_EVENTS_PATH_DEFAULT sandbox — so no
# call-site patch and no path-default override could have caught it. A test that trips this FAILS loudly and
# the row is NEVER written: the journal is append-only, so a phantom row cannot be taken back (80+ leaked
# rows re-entered the fleet-verdict recency window and woke armed `dispatch --watch` monitors — 3 spurious
# WATCH:WAKE incidents 2026-07-11).
#
# Read ONCE at import, not per call: the arming env var is set before the test process imports us, and
# several suites CLEAR os.environ mid-test to drive a known identity surface (test_dispatch's
# `_identity_env`) — a per-call env read would let exactly those suites disarm the guard.
#
# SCOPE (T-10404): the guard covers the test interpreter's OWN appends AND those of every child it spawns
# — the var is inherited, and the CLI no longer disarms it when run as __main__ (it did until T-10404,
# leaving a test that SHELLS OUT to the real CLI against the real checkout free to write the real journal:
# same append-only log, same phantom rows, only a process boundary away). A child pointed at its own
# sandbox repo resolves an unguarded journal and is untouched. A probe that must drive the REAL CLI over
# the REAL journal (a read lens — test_t10317) quarantines only its WRITE via the T-0357
# YITC_EVENTS_SINK (top precedence over the append target; reads stay on EVENTS_PATH): it reads the real
# corpus, its `cli_invoked` receipt lands in its sandbox. There is no disarm — a leak fails, closed.
def scope_guarded_default(root, *, ev_default=None, ev_guard=None):
    """The SPEC-0131 rule-1 scope-guarded journal DEFAULT for `root` — the ONE resolver (T-11445).

    Re-homed here from `cli._scope_guarded_events_default` (T-10859), which now delegates, because a
    caller OUTSIDE cli.py needs the same answer and a second copy is exactly the drift the original
    docstring warned about: the T-10840 territory breach was a SECOND resolution site. `lib.events`
    is the honest home — it already owns the journal WRITE path and the hermeticity guard that reads
    the same harness declaration.

    `ev_default` / `ev_guard` default to a CALL-TIME read of the pair; cli.py passes its module-load
    SNAPSHOT of them, deliberately preserving its own long-standing semantics (see the guard above on
    why a snapshot, not a per-call read, is right for a process whose env a test may clear mid-run).
    Under the harness the two agree — the harness sets the pair before the child starts and does not
    change it — so the difference is one of provenance, not of answer.

    No pair, or a `root` that is not the guarded checkout ⇒ the ordinary `<root>/events.jsonl`."""
    import os as _os                                    # module idiom: os is imported at top; explicit here
    from pathlib import Path as _Path
    ev_default = _os.environ.get("YITC_EVENTS_PATH_DEFAULT") if ev_default is None else ev_default
    ev_guard = _os.environ.get("YITC_EVENTS_GUARD_ROOT") if ev_guard is None else ev_guard
    if ev_default and ev_guard and _os.path.realpath(str(root)) == _os.path.realpath(ev_guard):
        return _Path(ev_default).resolve()
    return _Path(root) / "events.jsonl"


# ── SPEC-0190 — the journal SEGMENT SET (T-11444, the definer of this surface) ────────────────────
#
# SPEC-0190 rule 1: the journal is ONE LOGICAL append-only history realized as an ordered set of
# physical segments — exactly one LIVE segment (the appendable `events.jsonl`) plus zero or more
# ARCHIVE segments. An archive segment is a physical unit of the SAME logical journal: same line
# format, same parser, same append+union-merge discipline (CHARTER §P5, and the reading SPEC-0084
# already ratified — "one journal" means one MECHANISM, explicitly not one physical FILE).
#
# THIS IS THE ONE PLACE THE SEGMENT SET IS RESOLVED. It lives HERE, in the leaf, because `events.py`
# already owns the journal WRITE path, the hermeticity guard and the SPEC-0131 scope-guarded default
# — and because `journal.py` imports `events.py` and NEVER the reverse, so the resolver must sit
# BELOW every fold built on it (a fold in the leaf would be an import cycle). The corresponding FOLDS
# — text / lines / rows / size, and the rule-4b git-revision enumeration — live one layer up in
# `lib/journal.py`; the one journal reader inside THIS leaf (`known_event_types`) therefore iterates
# `segment_paths()` with its own existing per-line loop rather than importing upward.
#
# NAMING — REUSED, not invented (CHARTER §P1 filter 1 / SPEC-0190 rule 1). SPEC-0052 already
# displaces closed-task audit YAMLs out of the active `decisions/` directory into in-git archives
# under `<subject-dir>/archive/`, precisely so the active corpus stays loadable while provenance
# stays git-tracked. That is the same shape for the same reason, so the journal's archive extends it:
# for a journal at `<dir>/events.jsonl` the archive segments are `<dir>/archive/events-*.jsonl`. The
# stem prefix is what makes the whole family ONE literal pattern — one `.gitattributes` line, one
# housekeeping-allowlist entry (both A3/T-11446's to admit, deliberately NOT this card's).
#
# ORDERING IS PART OF THE CONTRACT, not an implementation detail. `segment_paths` returns the
# archives sorted by NAME ascending and the live segment LAST, because a reader that folds the set
# must see the oldest history first and the appendable tail last. That makes the label a CONTRACT the
# rotation card (A5/T-11448) must honour: an archive label MUST sort lexicographically in
# chronological order. An ISO date (`events-2026-08-16.jsonl`) does; a bare counter that wraps or a
# `%-d`-style label does not. Stated here, at the definer, so a rotation writer cannot pick a label
# that silently inverts every reader's fold.
#
# ROTATION IS OFF AND NO ARCHIVE EXISTS TODAY, so with no `archive/` directory beside the journal
# this returns exactly `(journal,)` and every reader built on it is byte-for-byte what it was before
# — inert by construction, and its rollback is an ordinary revert.
#
# SCOPE (SPEC-0190 rule 1b): this contract governs the ROOT journal only. The resolver is keyed on
# the path it is GIVEN and looks only for a sibling `archive/` directory, so the `.yitc/` hook-tail
# and the kernel-owned SHARED coordination store (SPEC-0084) resolve to themselves and are untouched.
# That is stated rather than left to silence: `worktree.py#_is_foldable_journal` treats the root
# journal and the hook-tail as a PAIR, so "the journal" alone would leave a reader guessing which
# half segments.
ARCHIVE_DIRNAME = "archive"
#: The ROOT journal's filename — the SCOPE fence `logical_journal` applies (SPEC-0190 rule 1b:
#: this contract governs the root journal only). Named once, here at the definer.
_ROOT_JOURNAL_NAME = "events.jsonl"


def archive_dir(journal_path) -> Path:
    """The directory holding `journal_path`'s ARCHIVE segments — `<journal.parent>/archive`.

    Derived from the journal path, never a repo-root literal, so a `-C` consumer checkout, a test
    sandbox and the engine's own root all resolve their own archive without a second rule."""
    return Path(journal_path).parent / ARCHIVE_DIRNAME


def archive_glob(journal_path) -> str:
    """The ONE filename pattern matching every archive segment of `journal_path`.

    `<stem>-*<suffix>` — for `events.jsonl` that is `events-*.jsonl`. Returned as a pattern rather
    than a list so the same literal serves the on-disk glob here, the git pathspec in
    `journal.revision_segment_paths`, and the single `.gitattributes` / allowlist line A3 admits."""
    p = Path(journal_path)
    return f"{p.stem}-*{p.suffix}"


def archive_segment_path(journal_path, label: str) -> Path:
    """The archive segment of `journal_path` carrying `label` — the WRITER's half of the naming.

    Exposed at the definer so the rotation card constructs its target through this function instead
    of re-spelling the convention; `label` must sort lexicographically in chronological order (see
    the ordering contract above)."""
    p = Path(journal_path)
    return archive_dir(p) / f"{p.stem}-{label}{p.suffix}"


def is_archive_segment(path, journal_path) -> bool:
    """True iff `path` is an archive segment of `journal_path`'s logical journal.

    A membership test, not a reader: a caller deciding whether a path belongs to the journal (a fold
    set, a dirt classification) asks THIS rather than comparing against the live filename."""
    p = Path(path)
    return p.parent == archive_dir(journal_path) and p.match(archive_glob(journal_path))


def segment_paths(journal_path) -> tuple:
    """The ORDERED physical segment set of the ONE logical journal at `journal_path`.

    Archive segments (sorted by name ascending — oldest first, per the ordering contract above) then
    the LIVE segment LAST. The live segment is ALWAYS the final element and is returned whether or
    not it exists on disk, so a caller's own missing-file handling is unchanged.

    An unreadable / absent archive directory yields no archive segments — this resolver never raises,
    because every reader in the corpus is downstream of it and a resolver that can fail would hand
    each of them a new way to fail."""
    live = Path(journal_path)
    try:
        archives = sorted(archive_dir(live).glob(archive_glob(live)))
    except OSError:
        archives = []
    return (*archives, live)


def segment_label(path, journal_path) -> "str | None":
    """The DATED label of `path` as an archive segment of `journal_path`, or None.

    The WRITER's half of this naming is `archive_segment_path`, and `rotate_journal` fixes what the
    label MEANS: it is the moving row's OWN UTC DATE (`ts[:10]`), so an archive segment holds rows
    of EXACTLY ONE calendar day. That is a contract, not an observation — it is what makes the label
    readable as a date range at all, and it is stated at the writer for the same reason.

    None where the label cannot be read as a calendar date: a path that is not an archive segment of
    this journal, or one whose label does not parse. A caller must treat None as UNDATABLE and
    therefore UNSKIPPABLE — see `segment_paths_since`, which is the only reason this function
    returns the label instead of a boolean."""
    if not is_archive_segment(path, journal_path):
        return None
    p = Path(path)
    stem = Path(journal_path).stem
    label = p.stem[len(stem) + 1:] if p.stem.startswith(stem + "-") else ""
    try:
        datetime.datetime.strptime(label, "%Y-%m-%d")
    except ValueError:
        return None
    return label


def segment_paths_since(journal_path, since, *, until=None) -> tuple:
    """The ORDERED subset of `segment_paths(journal_path)` that can OVERLAP the window `[since, until]`.

    WHAT IT IS FOR (SPEC-0190 rule 4, T-12030). Rule 4 names it directly: a reader DECLARES its
    horizon, and a WINDOWED reader's horizon is its window — not the whole logical journal. Folding
    every segment to answer a 7-, 14- or 30-day question opens 93 archive segments (216 MB on this
    engine, 2026-09-03) whose dated names already prove they cannot hold an in-window row. This is
    the resolver that reads those names, and it lives HERE, beside `segment_paths`, because this is
    the ONE place the segment set is resolved (see the surface header above) — a second membership
    rule spelled at a reader is precisely the class rule 3 names as dangerous.

    IT IS A PRE-FILTER, NEVER A PREDICATE, and that bound is what makes it safe to route an existing
    reader through it. It decides only which FILES are opened; every routed reader keeps its own
    in-loop `ts` comparison unchanged, and that comparison remains the sole decider of membership. So
    an over-inclusive answer here costs a little time and changes NO output, while an under-inclusive
    one would silently narrow a view — which is why every ambiguity below resolves toward inclusion.

    THE THREE INCLUSION RULES, all in the safe direction:
      * the LIVE segment is returned ALWAYS and LAST, exactly as `segment_paths` returns it (it is
        appendable, so it can hold a row of any date, and its own contract says it is returned
        whether or not it exists on disk);
      * an UNDATABLE archive label is INCLUDED — an unreadable name proves nothing about its
        contents, so it can never be the ground for skipping a file;
      * a datable archive label is included iff its DAY can overlap the window: `label >= since[:10]`
        and, when `until` is given, `label <= until[:10]`. Both comparisons are on the ISO date
        PREFIX, which is exactly the lexicographic-orders-chronologically property the ordering
        contract above already requires of a label.

    `since` / `until` are ISO-8601 strings (a date or a timestamp — only the first 10 characters are
    read) or None. `since=None` returns the whole set, so this is a faithful drop-in for
    `segment_paths` whenever a caller cannot resolve its own floor.

    THE CALLER OWNS THE SAFETY MARGIN. This function compares against the floor it is GIVEN; a reader
    whose in-loop predicate admits a row slightly older than its nominal window (a `.days`
    truncation, a clock skew, a union-merge reordering) must widen the floor it passes IN. `debt`'s
    routed readers do that through one shared helper (`debt._window_segment_floor`) rather than each
    re-deciding the margin."""
    live = Path(journal_path)
    segs = segment_paths(live)
    if not since:
        return segs
    floor = str(since)[:10]
    ceiling = str(until)[:10] if until else None
    out = []
    for seg in segs[:-1]:                       # archives only — the live segment is unconditional
        label = segment_label(seg, live)
        if label is None:                       # undatable ⇒ unskippable
            out.append(seg)
            continue
        if label < floor:
            continue
        if ceiling is not None and label > ceiling:
            continue
        out.append(seg)
    return (*out, segs[-1])


_SUMMARY_WINDOW_RE = re.compile(r"READ_SUMMARY_WINDOW_DAYS:\s*([0-9]+)")
_SUMMARY_WINDOW_MEMO: list = []


def read_summary_window_days() -> "int | None":
    """SPEC-0190 §Parameters — the SUMMARY WINDOW (rule 4 horizon class 2, T-13288), read FROM the
    spec that sets it, the `worktree.journal_live_window_days` idiom (kernel copy, located from this
    module, never REPO_ROOT). None when the token cannot be read; a caller then keeps its whole-history
    read — the safe direction, since a missing bound only costs time. Read once per process."""
    if not _SUMMARY_WINDOW_MEMO:
        val = None
        try:
            specs = Path(__file__).resolve().parent.parent.parent / "specs"
            for sp in sorted(specs.glob("SPEC-0190-*.yaml")):
                m = _SUMMARY_WINDOW_RE.search(sp.read_text(encoding="utf-8"))
                if m:
                    val = int(m.group(1))
                    break
        except (OSError, ValueError):
            val = None
        _SUMMARY_WINDOW_MEMO.append(val)
    return _SUMMARY_WINDOW_MEMO[0]


def summary_window_floor(now=None) -> "str | None":
    """The ISO-8601 UTC instant the summary window starts at (now minus `read_summary_window_days`),
    or None. Its first 10 characters are the date `segment_paths_since` compares segment labels to."""
    days = read_summary_window_days()
    if days is None:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def logical_journal(path) -> Path:
    """The LIVE segment identifying the LOGICAL journal `path` belongs to — the LOCK IDENTITY.

    SPEC-0190 rule 1: *one logical journal means ONE LOCK IDENTITY, keyed to the logical journal and
    never to a physical segment.* `journal_lock` derives its advisory sidecar from the journal's
    resolved PATH, so a second physical segment would get a second sidecar BY CONSTRUCTION — and
    `flock` does not serialise two different inodes. Rotation (`rotate_journal`) writes TWO paths
    while an appender holds one and a reader folds both, so per-file locking there is not a weaker
    guarantee, it is no guarantee. This function is what makes the two writes share one lock.

    THIS IS A REPEAT, NOT A HYPOTHESIS, which is why it ships WITH rotation rather than after it: the
    same shape was already paid for at T-10755, where two processes derived two different sidecars for
    the SAME journal, the reader lock went inert for precisely the audience it was added for, and a
    partial-journal read followed 2h38m later. The route differed (the key followed the ENVIRONMENT
    rather than the path); the failure was identical.

    THE MAPPING IS ROUND-TRIP VERIFIED, never a name guess. An archive segment is recognised only when
    reconstructing the live journal from it (`<archive>/../<stem-before-first-dash><suffix>`) yields a
    path `is_archive_segment` then AGREES the input belongs to — so a file that merely happens to sit
    in a directory called `archive` cannot be silently re-keyed onto some unrelated journal's lock.
    Anything that does not round-trip is its OWN identity, returned unchanged.

    SCOPE (rule 1b) — THE ROOT JOURNAL ONLY, enforced by NAME and not left to the path shape. Rule 1b
    is explicit that this contract governs the root journal and that the `.yitc/` hook-tail is OUT, so
    the reconstructed live journal must literally BE a root journal (`events.jsonl`). Without that
    narrowing the derivation is purely structural and over-reaches: any `<archive>/<stem>-<x><suffix>`
    round-trips, so a stray `archive/notes-2026-08-16.txt` would be silently re-keyed onto a
    `notes.txt` lock — an unrelated file borrowing another surface's serialisation. This literal is
    therefore a NARROWING, which is the safe direction for the one hand-spelled name in this function:
    an unmatched path keeps its own identity and simply locks as it always did. (Caught by this
    card's own fail-closed arm, not by review.)

    The hook-tail and the kernel-owned SHARED coordination store are not segmented, so neither ever
    reaches the archive branch and both keep the identity they have always had. INERT TODAY in the
    same sense as every other member of this surface: with no archive on disk, no caller ever passes
    an archive path, so every lock key is byte-identical to the pre-rotation one."""
    p = Path(path)
    if p.parent.name != ARCHIVE_DIRNAME or "-" not in p.stem:
        return p
    live = p.parent.parent / f"{p.stem.split('-', 1)[0]}{p.suffix}"
    if live.name != _ROOT_JOURNAL_NAME:
        return p
    return live if is_archive_segment(p, live) else p


def live_segment(journal_path) -> Path:
    """The LIVE (appendable) segment of the logical journal at `journal_path`.

    The declared-horizon escape hatch for a reader that must NOT fold the archive, so that choice is
    made in this surface's own vocabulary instead of by quietly reverting to a raw open() — which
    would read as an un-migrated site rather than as a decision.

    WHEN IT IS THE RIGHT ANSWER (SPEC-0190 rules 3+4): a read-modify-WRITE whose write targets ONE
    physical file. Folding the segment set on the read side and writing the union back to the live
    file would move archived rows into the live segment — undoing segmentation, the exact hazard rule
    3 names. A reader in that shape declares a LIVE-segment horizon until the rotation writer (A5)
    owns per-segment writes. `deploy.cmd_deploy`'s rollback snapshot/union-restore pair is the
    instance; `append_event` is the same class by construction (appends write the live segment only,
    rule 1)."""
    return segment_paths(journal_path)[-1]


def journal_pathspecs(journal_path, root) -> list:
    """Every PRESENT physical segment of the ONE logical journal at `journal_path`, as pathspecs
    relative to `root` — the STAGING half of this surface (T-11536).

    WHAT IT IS FOR. A governed scoped commit stages "the journal" by NAME, and by SPEC-0190 rule 1 the
    journal is the segment SET, not the live path. Every such site needs the same three lines — take
    `segment_paths`, drop the ones not on disk, relativise — and rule 3 names a re-spelled membership
    set as the DANGEROUS class precisely because a missed member does not raise, it silently leaves an
    archive segment uncommitted and wedges the next land on non-allowlisted dirt (the X-0274 shape).
    So the set is resolved ONCE, here, beside the resolver it is a view of, rather than six times at
    six call sites. It adds no state and no new entity: it is `segment_paths` in the vocabulary a
    `git add --` caller speaks.

    THE LIVE SEGMENT IS RETURNED UNCONDITIONALLY AND LAST, exactly as `segment_paths` returns it —
    whether or not it exists on disk. That is what makes this a drop-in for the literal it replaces:
    a caller that already filters its pathspec list through `.exists()` keeps deciding the live
    segment's fate with its own existing filter, and gains only the archives. Archive segments are
    glob-derived, so their presence is true by construction and needs no second check.

    WHICH QUESTION IS YOURS. This is the answer for a set that must carry the WHOLE journal — a
    staging/commit pathspec set, a fold set. A caller whose write targets ONE physical file must NOT
    use it: that shape declares a live-segment horizon through `live_segment` and says so (see its
    contract above), because folding the set on the read side and writing the union back to the live
    file would move archived rows forward and undo segmentation."""
    live = Path(journal_path)
    base = Path(root)
    return [seg.relative_to(base).as_posix() for seg in segment_paths(live)]


# ── SPEC-0190 rules 2+3 — ROTATION: the crash-safe transaction, and its rehearsed undo (T-11448) ──
#
# This is the WRITER half of the segment surface T-11444 defined above. Rules 2 and 3 govern it:
# rule 2 fixes the BOUNDARY (age, from the newest row PRESENT — never a decreed byte number and never
# wall-clock), rule 3 fixes WHERE it runs (the land seam, after every union that could reintroduce a
# row) and the two crash constraints — (a) the archive is DURABLE BEFORE the live file is truncated,
# and (b) both writes take the tempfile-then-replace path.
#
# THE ASYMMETRY THIS CODE IS BUILT AROUND, stated once here because every choice below follows from
# it: A SURVIVING DUPLICATE IS HARMLESS — the union+dedup collapses it. A LOST ROW IS NOT RECOVERABLE
# BY ANYTHING. So every decision that could go either way goes toward the live file: an undatable row
# never moves, a validation shortfall aborts before the live rewrite, and an interrupted run leaves
# rows in BOTH places rather than in neither.
#
# THE HOST-COUPLED COLLABORATORS ARRIVE BY INJECTION (`dedup`, `write_text_atomic`), which is this
# module's stated contract (see the module docstring — the state.py `rel_root` precedent) and not a
# seam invented here: `events.py` is a LEAF that `journal.py` imports and never the reverse, so it
# must not reach UP into `cli.py`. `_land_integrate`, the only production caller of the seam helper,
# already holds both as injected deps and simply passes through what it has. The corpus keeps exactly
# ONE atomic-write implementation and ONE dedup identity.
def _row_ts(line: str) -> "str | None":
    """The TOP-LEVEL ENVELOPE `ts` of a journal row, or None when it has none / is unparseable.

    PARSED, NOT PATTERN-MATCHED, and the difference decides whether a row can be moved by mistake.
    An earlier form of this function scanned the raw line for the FIRST `"ts": "..."` and argued from
    the envelope's key order that the first match must be the envelope's. That argument is not sound:
    a row whose ENVELOPE carries no `ts` but whose nested `data` payload does would hand back the
    NESTED value, and the caller would then file the row under a date that describes something else
    entirely — moving a row the contract says must never move (external audit finding, high). A
    top-level parse cannot make that mistake, and it is the only form that cannot.

    THE COST IS PAID DELIBERATELY. Rotation reads every row of a ~175 MB journal, and a full
    `json.loads` per line measures ~0.8 s at 110 MB on this corpus (SPEC-0190 §Rotation policy, third
    firing) — order a second and a half here, inside a land seam that already runs for minutes. A
    cheaper scan that can mis-attribute a timestamp is not a saving worth making in the one function
    that decides which rows leave the live file.

    Returning None is the SAFE answer in every failure mode — a malformed line, a non-object row, a
    missing or non-string `ts`, a value that is not an ISO-8601 date: the row stays LIVE. That is the
    asymmetry this whole transaction is built around, applied at the level of a single row."""
    try:
        row = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(row, dict):
        return None
    ts = row.get("ts")                       # TOP-LEVEL only — never a nested `data.ts`
    if not isinstance(ts, str) or len(ts) < 10:
        return None
    # THE DATE IS VALIDATED AS A CALENDAR DATE, not merely as a SHAPE. A digit/hyphen check admits
    # `2026-02-31`, which is not a date at all, and the consequences are not cosmetic: such a row
    # sorts perfectly well lexicographically, so it would be MOVED and filed under an archive label
    # naming a day that never existed — and if it were the NEWEST row it would reach
    # `rotation_boundary`'s `strptime`, raise, and return None, silently disabling rotation for the
    # whole repo from then on. One impossible timestamp is enough for that. `strptime` is the only
    # check that actually answers the question the shape check was standing in for.
    try:
        datetime.datetime.strptime(ts[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return ts


def rotation_boundary(journal_path, window_days: int) -> "str | None":
    """SPEC-0190 rule 2 — the age boundary separating the live segment from the archive, or None.

    MEASURED FROM THE NEWEST ROW PRESENT IN THE LOGICAL JOURNAL, never from wall-clock `now`. Rule 2
    says why in its own words: wall-clock would make the same corpus segment differently on two
    machines and make a rotation unreproducible. It also makes every fixture self-consistent whatever
    its absolute dates, which is what disarms the hand-stamped-fixture-clock hazard
    (`lessons/a-seeded-fixture-clock-can-invert-a-ts-ordered-fold.md`) by construction rather than by
    the test author remembering it.

    THE COMPARISON IS FULLY SPECIFIED, because rule 2 requires it to be: `ts < boundary` MOVES,
    `ts >= boundary` STAYS. A reader declaring a horizon EQUAL to the live window sits exactly on that
    comparison — there are two such readers in this corpus — so an unstated inclusivity would be an
    off-by-one discovered in production rather than here.

    A ROW STAMPED IN THE FUTURE CANNOT BE THE ANCHOR, and this bound is not defensive decoration —
    without it ONE outlier row archives the ENTIRE live journal in a single land. Measured, not
    imagined: a synthetic corpus in `tests/test_land.py` carries `cli_invoked` rows stamped 2099-01-01
    beside real ones, so the anchor jumped 73 years, every genuine row fell before the boundary, and
    the live segment was emptied of all real history in one pass (caught by that suite, 2026-08-24).
    The same shape reaches production through a skewed clock or a malformed row, and its consequence
    is severe in a quiet way: nothing is LOST — the rows are in the archive and the fold still returns
    them — but every LIVE-SEGMENT reader goes blind at once, which is the failure mode hardest to
    notice because the journal still looks healthy.

    WALL-CLOCK IS USED ONLY AS A CEILING ON THE ANCHOR, NEVER AS THE ANCHOR — and that distinction is
    exactly what rule 2 forbids and permits. Rule 2 bans measuring FROM `now` because that would make
    the same corpus segment differently on two machines and make a rotation unreproducible. A ceiling
    that only ever REJECTS an impossible value changes nothing for any corpus whose rows are in the
    past — which is every real one — so reproducibility is preserved precisely where the rule cares
    about it. A future-stamped row needs no separate keep-rule: it is trivially `>= boundary`, so the
    ordinary comparison already leaves it live.

    Returns an ISO-8601 prefix comparable against a raw `ts` STRING: ISO-8601 UTC timestamps of one
    fixed shape order lexicographically the same way they order chronologically, so no row needs
    parsing into a datetime. None when the journal carries no datable row at all (nothing can move)."""
    ceiling = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    newest = None

    def _scan(seg):
        nonlocal newest
        try:
            fh = Path(seg).open("r", encoding="utf-8", errors="replace")
        except OSError:
            return
        with fh:
            for line in fh:
                ts = _row_ts(line)
                if ts is None or ts[:10] > ceiling:      # an impossible anchor is not an anchor
                    continue
                if newest is None or ts > newest:
                    newest = ts

    # T-13257 — WHICH SEGMENTS ARE READ, never what the anchor is. `rotate_journal` (the only archive
    # writer) files a row under its OWN UTC date, so a segment labelled L holds rows of day L alone and
    # cannot beat a newest row dated after L. So: the live segment first, then the archives NEWEST LABEL
    # FIRST, stopping at the first label older than the newest date found — a land no longer re-reads
    # the whole archive (7.78 s on the kernel, growing with it). An UNDATABLE label proves nothing about
    # its rows and is always read (the `segment_label` contract); a label past the ceiling cannot come
    # from rotation, so it is read rather than trusted. The ceiling and the comparison are unchanged.
    # THE BOUND, exactly: archive opens = the OFF-CONTRACT segments (undatable / past-the-ceiling label,
    # or a dated one holding no eligible row — rotation writes none of them, and each is read, never
    # trusted) + the dated labels on or after the newest date found (at most 1 under the contract). It
    # does not grow with the archive while no label is past THIS reader's ceiling; a rotation done under a
    # later clock leaves such labels, and then every one is read (cost grows, answer exact). Exactness assumes the label contract `segment_paths_since`
    # already relies on: no row is dated AFTER the label of the file it sits in.
    segs = segment_paths(journal_path)
    live = Path(journal_path)
    _scan(segs[-1])
    dated = []
    for seg in segs[:-1]:
        label = segment_label(seg, live)
        if label is None or label > ceiling:            # off-contract: read, never trusted
            _scan(seg)
        else:
            dated.append((label, seg))
    for label, seg in sorted(dated, key=lambda t: t[0], reverse=True):
        if newest is not None and label < newest[:10]:
            break
        _scan(seg)
    if newest is None:
        return None
    try:
        anchor = datetime.datetime.strptime(newest[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return (anchor - datetime.timedelta(days=int(window_days))).strftime("%Y-%m-%d")


def rotate_journal(journal_path, *, window_days, dedup, write_text_atomic, _at=None) -> "dict | None":
    """SPEC-0190 rules 2+3 — MOVE rows older than the live window out of the live segment into
    ARCHIVE segments, as a crash-safe transaction. Returns None when nothing moves, else a summary.

    THE CALLER OWNS THE LOCK AND THE INDEX. This function is pure of git and of the host: it takes the
    logical journal's lock as a PRECONDITION (`journal_lock`, which since T-11448 keys on the LOGICAL
    journal so one lock covers both writes) and it never stages or commits anything. The index update
    is the SEAM's object, so it lives in `worktree.rotate_branch_journal` — putting its failure seam
    here would test a boundary this transaction does not have.

    THE ORDER, AND WHY IT IS NOT NEGOTIABLE (rule 3a). The archive segments are written and made
    durable FIRST; only then is the live file rewritten. The reverse order has a window in which the
    rows exist NOWHERE. Between those two halves sits the POST-WRITE VALIDATION: every archive segment
    just written is re-READ OFF DISK and proved to carry every row this run is about to remove from
    the live file. A shortfall raises with the live file UNTOUCHED — the whole point of validating
    before the truncation rather than after it.

    ATOMICITY (rule 3b): both writes go through the injected `write_text_atomic` (tempfile -> fsync ->
    os.replace), and the archive DIRECTORY is fsynced so the rename itself survives a power loss. A
    crash therefore leaves an orphan tempfile and an untouched original, never a truncated journal —
    `patterns/atomic-state-file-writes.md` names this journal explicitly as that risk class.

    IDEMPOTENCE IS STRUCTURAL, not bookkeeping. The archive LABEL is the moving row's OWN UTC DATE, so
    a given row deterministically resolves to the same segment file on every run; a re-run unions into
    that file through the same keep-first `dedup` and lands on an identical multiset. There is no
    retry counter, no marker file and no transaction log to go stale — the second run of an
    interrupted rotation simply finds most of its work already done. The label also satisfies the
    ordering CONTRACT the segment resolver states above: an ISO date sorts lexicographically in
    chronological order, so it can never invert a reader's fold.

    AN UNDATABLE ROW NEVER MOVES. `_row_ts` returning None keeps the row in the live file — the safe
    side of the asymmetry, since a row left live is merely not-yet-archived while a row moved on a
    guess could be filed under a date no reader would look for.

    `_at` is the TEST-ONLY interruption seam, called with `archive-write` (after the archives are
    durable, before the live rewrite) and `live-truncate` (immediately before it). It exists because
    the card requires this crash behaviour DEMONSTRATED rather than argued, and two points inside one
    transaction cannot be reached by monkeypatching a shared primitive by call count. Production never
    passes it; `index-update`, the third point, belongs to the seam helper."""
    live = live_segment(journal_path)
    boundary = rotation_boundary(journal_path, window_days)
    if boundary is None or not live.exists():
        return None
    # T-13138 (X-1687) — STREAMED, never held: resident memory is bounded by the largest single
    # moving day, never by the live segment or by how far behind rotation has fallen.
    # T-13202 (SPEC-0190 rule 10) — and the live file is READ ONCE. The T-13138 form re-streamed the
    # whole live segment once per expired UTC day plus once more to rewrite it (N+2 passes — a first
    # rotation after a gap measured ~120 days), so time grew with journal size x backlog. Now ONE pass
    # PARTITIONS every row into bounded spill files in a private temp directory — one per moving day,
    # one for the rows that stay — and each spill is then consumed exactly once. Same lines (the shared
    # `journal.stream_lines` splitter, and a spill round-trips a line unchanged: written `line + "\n"`,
    # re-split by the same splitter), same partition, same per-day `dedup` union, same order (days
    # ascending, rows in live-file order within each spill), so the output is byte-identical. A crash
    # leaves only the temp directory behind; the live file and archive are untouched until HALF 1/2.
    import hashlib
    import tempfile
    from lib import journal as _journal   # noqa: PLC0415 — journal imports this module at load

    def _read(path):
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in _journal.stream_lines(fh):
                if line:
                    yield line

    def _digest(line):
        # the read-back identity, held as a 16-byte digest rather than the line (a collision, 2^-128,
        # is the one way a missing row could validate)
        return hashlib.blake2b(_dedup_identity(line).encode("utf-8"), digest_size=16).digest()

    with tempfile.TemporaryDirectory(prefix="yitc-rotate-") as tmp:
        spill_dir = Path(tmp)
        keep_path = spill_dir / "keep"
        handles, kept, days = {}, 0, set()
        try:
            handles["keep"] = keep_path.open("w", encoding="utf-8")
            for line in _read(live):
                ts = _row_ts(line)
                if ts is None or ts >= boundary:     # rule 2: `ts >= boundary` STAYS; undatable never moves
                    kept += 1
                    handles["keep"].write(line + "\n")
                    continue
                label = ts[:10]
                fh = handles.get(label)
                if fh is None:
                    if len(handles) >= 256:          # bound open descriptors; a reopen appends
                        for k in [k for k in handles if k != "keep"]:
                            handles.pop(k).close()
                    fh = handles[label] = (spill_dir / f"day-{label}").open("a", encoding="utf-8")
                days.add(label)
                fh.write(line + "\n")
        finally:
            for fh in handles.values():
                fh.close()
        if not days:
            return None                              # a no-op is cheap and VISIBLE — never a silent pass

        # ── HALF 1: the archive, written and made DURABLE FIRST (rule 3a) — one day at a time.
        # ── VALIDATION, BEFORE the live file is truncated: each day's archive is read BACK OFF DISK —
        # not from the in-memory `merged`, which would only prove this process's own arithmetic to
        # itself — and every row this run moved into it must be there.
        adir = archive_dir(live)
        adir.mkdir(parents=True, exist_ok=True)
        written, moved, missing = [], 0, 0
        for label in sorted(days):
            day = list(_read(spill_dir / f"day-{label}"))
            seg = archive_segment_path(live, label)
            existing = seg.read_text(encoding="utf-8", errors="replace").splitlines() if seg.exists() else []
            merged = dedup([ln for ln in existing if ln] + day)
            write_text_atomic(seg, "".join(ln + "\n" for ln in merged))
            written.append(seg)
            want = {_digest(ln) for ln in day}
            del day, existing, merged
            moved += len(want)
            for line in _read(seg):
                want.discard(_digest(line))
            missing += len(want)
        _fsync_dir(adir)
        if missing:
            raise RuntimeError(
                f"rotate_journal: {missing} row(s) did not survive the archive write — "
                f"live segment {live} left UNTOUCHED (SPEC-0190 rule 3a: durable before truncate)")
        if _at:
            _at("archive-write")

        # ── HALF 2: the live segment, rewritten the same atomic way, only now — from the keep spill.
        if _at:
            _at("live-truncate")
        write_text_atomic(live, (ln + "\n" for ln in _read(keep_path)))   # streamed, never joined
    _fsync_dir(live.parent)
    return {"moved": moved, "kept": kept, "boundary": boundary,
            "segments": [str(s) for s in written]}


def recombine_journal(journal_path, *, dedup, write_text_atomic) -> "dict | None":
    """THE DOCUMENTED UNDO of `rotate_journal` — and it is EXECUTED, not merely written down.

    Concatenate every archive segment and the live segment, in segment order, through the SAME
    union+dedup identity `land` already uses; write the result back as ONE file; drop the archive. An
    undo that has never been run is not a rollback path, which is why this card rehearses it once over
    a two-segment fixture rather than shipping it as prose.

    THE GUARANTEE IS MULTISET IDENTITY, NOT BYTE IDENTITY (rule 5), and the caller must not assert
    otherwise: rows are routinely appended out of `ts` order — union-merge makes that ordinary,
    measured at 3.64% of rows — so partitioning and re-joining legitimately reorders them across the
    old boundary. A byte-identity gate would encode a test the design cannot pass even when correct.

    ORDER, mirroring the rotation's: the recombined LIVE file is written and made durable FIRST, and
    only then are the archive segments unlinked. The same asymmetry decides it — a crash between the
    two leaves the rows in both places, which the next fold collapses, rather than in neither.
    Returns None when there is no archive to fold back."""
    live = live_segment(journal_path)
    segs = segment_paths(journal_path)
    archives = [s for s in segs[:-1]]
    if not archives:
        return None
    lines = []
    for seg in segs:
        try:
            lines.extend(ln for ln in Path(seg).read_text(encoding="utf-8", errors="replace").splitlines() if ln)
        except OSError:
            continue
    merged = dedup(lines)
    write_text_atomic(live, "".join(ln + "\n" for ln in merged))
    _fsync_dir(live.parent)
    for seg in archives:                          # only AFTER the recombined live file is durable
        with contextlib.suppress(OSError):
            Path(seg).unlink()
    with contextlib.suppress(OSError):
        archive_dir(live).rmdir()                 # only when empty — never a recursive delete
    return {"rows": len(merged), "segments_dropped": len(archives)}


def _dedup_identity(line: str) -> str:
    """The keep-first identity used to VALIDATE the archive write — deliberately the raw line.

    This is NOT a second dedup key competing with land's (`_event_dedup_key`, which the injected
    `dedup` carries): it never decides what to KEEP, only whether the exact bytes this run moved came
    back off disk. Land's key is canonical-object identity, so it is coarser than the raw line; using
    it here would let a row whose bytes were mangled in flight validate against a DIFFERENT row that
    happens to canonicalize the same. For a read-back check the stricter answer is the correct one."""
    return line


def _fsync_dir(path) -> None:
    """fsync a DIRECTORY so a rename inside it is itself durable — the half of atomic-replace that a
    file-level fsync does not cover. Best-effort: a filesystem that refuses a directory fsync must not
    turn a completed rotation into a failed one, and every write it guards is atomic regardless."""
    with contextlib.suppress(OSError, AttributeError):
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


_GUARDED_JOURNALS = frozenset(
    Path(p).resolve()
    for p in os.environ.get("YITC_TEST_JOURNAL_GUARD", "").split(os.pathsep)
    if p.strip()
)


def _resolve_git_common_dir(repo_dir):
    """The git common-dir governing `repo_dir`, or None if `repo_dir` is not a git repo root.
    Pure path inspection — NO subprocess (keeps this leaf module minimal + identity-agnostic):
      - `.git` is a DIRECTORY → a self-contained repo; its `.git` IS the common-dir.
      - `.git` is a FILE ("gitdir: <path>") → a linked worktree; follow gitdir, then its
        `commondir` file (relative → resolved against gitdir) to the shared common-dir.
    Any OS/parse error → None (fail to the safe beside-journal placement)."""
    gp = repo_dir / ".git"
    try:
        if gp.is_dir():
            return gp
        if gp.is_file():
            content = gp.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir:"):
                gitdir = Path(content.split(":", 1)[1].strip())
                if not gitdir.is_absolute():
                    gitdir = repo_dir / gitdir
                gitdir = gitdir.resolve()
                cf = gitdir / "commondir"
                if cf.is_file():
                    cd = Path(cf.read_text(encoding="utf-8").strip())
                    return (cd if cd.is_absolute() else (gitdir / cd)).resolve()
                return gitdir
    except OSError:
        return None
    return None


# T-10755 — the deterministic system temp roots, used ONLY when the process ENV is what imposed the
# temp root (see `_persistent_lock_root`). Ordered by preference.
_PERSISTENT_LOCK_ROOT_CANDIDATES = ("/tmp", "/var/tmp")
_ENV_TEMP_VARS = ("TMPDIR", "TEMP", "TMP")     # exactly what `tempfile.gettempdir()` consults first


_PRE_LEVER_TEMP_BASE: "str | None" = None
"""T-12185 — the process temp base as it stood BEFORE `YITC_VERIFY_TMPDIR` moved it (None if it never
did). Recorded by `verify_runner._install_verify_tmpdir`, read by `pre_lever_temp_base` below."""


def record_pre_lever_temp_base(base: str) -> None:
    """T-12185 — remember the temp base the T-12185 verify lever is about to move away from. Records
    the FIRST one only: the lever installs at most one root per process, and a later re-install must
    not overwrite the original with the relocated one."""
    global _PRE_LEVER_TEMP_BASE
    if _PRE_LEVER_TEMP_BASE is None:
        _PRE_LEVER_TEMP_BASE = base


def pre_lever_temp_base() -> Path:
    """The temp base to hang a CROSS-PROCESS identity off — the pre-lever one when
    `YITC_VERIFY_TMPDIR` moved it, otherwise the live `tempfile.gettempdir()`. Today's one caller
    pair: the SPEC-0132 admission slot pool (`worktree._verify_slot_dir` + its nightly twin), where
    two lands of the SAME repo must resolve the SAME directory or each believes it holds slot 0.

    NARROWER than `_persistent_lock_root` below, ON PURPOSE, which is why they are two functions and
    not one. That one neutralises the temp ENV entirely — right for a journal sidecar lock EVERY party
    must share. Here it would be wrong: SPEC-0131 Rule 1 gives each hermetic verify child a private
    TMPDIR and a child's slot pool must stay INSIDE its box; neutralising the env would point a test
    that takes slots at the REAL land-verify pool and make it contend with a live 13-worker verify
    (measured: a 300s land-verify timeout, class=stalled, in test_t11089_nightly_host_sandbox.py).
    So only the T-12185 lever is undone, and nothing else about the temp base is.

    It lives HERE, beside its sibling, because BOTH readers (`bin/lib/worktree.py` and the
    `bin/lib/nightly.py` twin, which deliberately never back-imports the host) already import this
    module — one home, no cycle, no third copy of the convention."""
    return Path(_PRE_LEVER_TEMP_BASE or tempfile.gettempdir())


def _persistent_lock_root() -> Path:
    """The directory a PERSISTENT journal's sidecar lock lives in — DETERMINISTIC and ENV-INDEPENDENT.

    WHY NOT `tempfile.gettempdir()` (the T-10755 root cause, measured — not theorised). `gettempdir()`
    honours TMPDIR, and `worktree.py#_hermetic_child_env` gives every land-verify test subprocess a
    PRIVATE TMPDIR — which SPEC-0131 Rule 1 REQUIRES and this fix does not touch. So for the SAME
    journal and the SAME key `a2931693e09042ee`, two processes computed two DIFFERENT sidecars:
        land (ambient TMPDIR):        /tmp/yitc-journal-a2931693e09042ee.lock
        verify child (private TMPDIR): <box>/tmp/yitc-journal-a2931693e09042ee.lock
    Two inodes ⇒ `flock` never serialises them ⇒ the SPEC-0168 rule-6 READER lock that T-10730 added
    to `task.py#_folded_journal_events` was INERT for exactly the audience that needed it. That is why
    the pinned-verify partial-journal read (T-10755, `UnicodeDecodeError` at ~57 MB of a ~110 MB file)
    happened 2h38m AFTER that reader lock landed. A lock is only a lock if every party resolves the
    SAME file, so the sidecar's identity must be a pure function of the JOURNAL — never of whichever
    process happens to be looking.

    WHAT IS NEUTRALISED IS THE **ENV**, NOT `gettempdir()` ITSELF — the distinction is load-bearing.
    The defect is precisely that the sidecar followed the temp root the process ENVIRONMENT imposed.
    So: if `gettempdir()` resolves to something OTHER than the env override (nothing set, or an
    in-process `tempfile` rebinding — the hermeticity hook `test_t10189_journal_lock_multiuser` uses to
    keep its sidecar out of the real `/tmp`), that answer is HONOURED unchanged. Only when the root IS
    the env override is it discarded for the deterministic candidate list. A blanket "always /tmp"
    would have been simpler and wrong: it silently defeats every module-level test hook and would have
    leaked that suite's sidecars into the live `/tmp`.

    No migration window either way: on any ordinary host `gettempdir()` already returned `/tmp` for
    every ambient process, which is also the first candidate — so no existing sidecar MOVES and an old
    and a new engine never disagree. Only a private-TMPDIR child changes behaviour, converging onto the
    path land was always using. `tempfile.gettempdir()` stays the last-resort fallback for a host
    carrying neither candidate, so this can never fail closed on an exotic layout.

    This resolves a genuine artifact dissonance (CHARTER §P7) rather than picking a side: SPEC-0131
    Rule 1 (private per-child TMPDIR) and SPEC-0168 Rule 6 (the reader observes under the SAME lock
    discipline as the fold) were both true as written and could not both hold while lock IDENTITY was
    derived from TMPDIR. Separating the two concerns — ephemerality is still asked of the CURRENT
    process's temp container, lock PLACEMENT is not — satisfies both unchanged."""
    root = Path(tempfile.gettempdir())
    env_override = next((os.environ[v] for v in _ENV_TEMP_VARS if os.environ.get(v)), None)
    if env_override is None:
        return root.resolve()          # nothing imposed by the env — the honest answer, unchanged
    try:
        imposed = Path(root).resolve() == Path(env_override).resolve()
    except OSError:
        imposed = False
    if not imposed:
        return root.resolve()          # gettempdir was decided by something OTHER than the env
    for cand in _PERSISTENT_LOCK_ROOT_CANDIDATES:
        try:
            p = Path(cand)
            if p.is_dir() and os.access(cand, os.W_OK):
                return p.resolve()
        except OSError:                # unreadable/exotic mount — try the next candidate
            continue
    return root.resolve()              # last resort — never fail closed on layout


# T-11061 — the DEFAULT name shape `tempfile.mkdtemp()` mints: the literal prefix `tmp` plus 8
# characters drawn from tempfile's own random alphabet. It is the only marker a throwaway scratch
# directory carries once it sits OUTSIDE every temp root (inside a persistent tree it looks like any
# other directory). Measured 2026-08-13: all 210 `TemporaryDirectory(dir=…REPO_ROOT)` call sites in
# this repo's suite use that default prefix — none passes a custom `prefix=`.
_SCRATCH_DIR_RE = re.compile(r"\Atmp[a-z0-9_]{8}\Z")


def _throwaway_container(resolved_journal):
    """The throwaway container a NON-temp-root journal lives in, or None if it is a checkout's OWN
    journal (the real repo / a linked worktree) — the T-11061 extension of the T-10227 classification.

    WHY (measured, not theorised). `_journal_lock_path` classified "under no temp root" as PERSISTENT
    and sent the sidecar to the temp ROOT, where nothing ever removes it. But the suite creates 210
    scratch journals per run INSIDE the repo tree (`TemporaryDirectory(dir=REPO_ROOT)`) — each a fresh
    path ⇒ a fresh key ⇒ a NEW never-reaped `/tmp/yitc-journal-<key>.lock`. That is the SAME leak class
    T-10227 closed for temp-root journals (~130K files/day; 808615 present on 2026-08-13), reaching the
    engine through the one door that classification left open. Ephemerality is a property of the
    journal's CONTAINER, not of which root the container happens to sit under.

    THE CONTAINER IS THE UNIT — the OUTERMOST `tempfile`-shaped ancestor directory (`_SCRATCH_DIR_RE`),
    whether or not it was `git init`-ed (29 test files do that, which puts the journal AT a git toplevel
    so it LOOKS like a checkout's own journal). Co-location is only ever CORRECT for a directory that is
    itself torn down; that teardown is the whole guarantee, so a journal with no throwaway container is
    reported as None and keeps the persistent path.

    DELIBERATELY NOT WIDENED to "any journal nested below a checkout root". That widening was tried and
    is WRONG in both directions: a fresh-per-run journal written DIRECTLY into a tracked directory (the
    measured `tests/events-t10600-<random>.jsonl` population) has no container to be reaped with, so
    co-locating it beside the journal only converts a temp-root leak into TRACKED-TREE DIRT — caught at
    audit-post, 15 `.lock` files staged into a commit. Those journals leak a stable-but-fresh key per run
    and need their own fix (a tracked follow-up), not a placement that dirties the repo.

    WHAT STAYS PERSISTENT (the T-10755 / X-0226 constraint this must not break): the real repo journal
    `<REPO_ROOT>/events.jsonl` and a linked worktree's journal both sit AT their checkout's toplevel and
    carry no tempfile-shaped ancestor → None → the historical env-independent
    `<persistent-root>/yitc-journal-<key>.lock` path, unchanged byte for byte.

    REJECTED (measured refutation, so it is not re-proposed): "a git repo nested inside another git
    repo's tree is scratch". `/home/dev` is itself a git repo, so that rule re-classifies the REAL
    `/home/dev/projects/yitc-v2` journal and breaks the very serialization the sidecar exists for.

    Pure path inspection, NO subprocess — the same discipline `_resolve_git_common_dir` keeps, so this
    leaf module stays minimal and identity-agnostic."""
    journal_dir = resolved_journal.parent
    scratch = None
    d = journal_dir
    while True:                                  # remember the OUTERMOST tempfile-shaped ancestor
        if _SCRATCH_DIR_RE.match(d.name):
            scratch = d
        if d.parent == d:
            break
        d = d.parent
    return scratch                               # None ⇒ no throwaway container ⇒ persistent (unchanged)


# ── the PERSISTENT sidecar's IDENTITY, published for its reaper (T-11062) ─────────────────────────
# The sidecar's name and root are facts of the CREATOR. `worktree sweep`'s Category E reaps stranded
# persistent sidecars, and it must resolve the SAME name shape and the SAME root this module mints —
# so both are published here rather than re-spelled at the cleanup site. That is the T-10855 lesson
# applied to a NAME instead of a cohort: a hand-kept copy at the cleanup site is exactly how
# `yitc-verify-sandbox-*` came to be missed for months while the cleaner reported success. The
# T-11089 discipline is the same one level up — reader and reaper resolve to ONE function object, and
# the suite asserts that identity rather than resemblance.
_PERSISTENT_LOCK_STEM = "yitc-journal-"
PERSISTENT_LOCK_GLOB = f"{_PERSISTENT_LOCK_STEM}*.lock"
PERSISTENT_LOCK_NAME_RE = re.compile(rf"\A{re.escape(_PERSISTENT_LOCK_STEM)}([0-9a-f]{{16}})\.lock\Z")


def journal_lock_key(resolved_journal) -> str:
    """The E-0021 sidecar KEY for an already-`.resolve()`d journal path (T-11062 extraction).

    A pure function of the JOURNAL — never of whichever process is looking (the T-10755 invariant).
    Extracted verbatim from `journal_lock`, which now calls it, so the creator and `worktree sweep`'s
    orphan-lock keep-set derive the key through ONE code path. One-way by construction: a key cannot
    be inverted to its journal, which is why the reaper must work from a keep-set of live journals
    rather than from the lock's own name."""
    return hashlib.sha256(str(resolved_journal).encode("utf-8")).hexdigest()[:16]


def persistent_lock_root() -> Path:
    """PUBLIC name for `_persistent_lock_root` — the directory a PERSISTENT journal's sidecar lives in.

    The reaper needs the same answer the creator gets, and must not re-derive it (a second spelling
    could drift from `_persistent_lock_root`'s env-independence rules, T-10755, and then the sweep
    would glob a directory nothing writes to and report a healthy zero forever)."""
    return _persistent_lock_root()


def _journal_lock_path(resolved_journal, key, discriminator: str = ""):
    """Where the E-0021 sidecar lock lives for `resolved_journal` (already `.resolve()`d), `key`.

    PERSISTENT journal (resolved path NOT under any temp root — the real repo) → the historical
    bounded, stable, cross-user `<temp-root>/yitc-journal-<key>.lock` (X-0226 O_RDONLY fallback
    intact). The root is `_persistent_lock_root()` — ENV-INDEPENDENT (T-10755), and equal to what
    `tempfile.gettempdir()` returned on any ordinary host, so the path itself is UNCHANGED.

    EPHEMERAL journal (resolved path UNDER the system tempdir — a tmp test repo / a `/tmp/yitc-pinned-*`
    verify worktree) → CO-LOCATE the sidecar INSIDE the owning temp container so it is torn down WITH the
    TemporaryDirectory / worktree (no /tmp-root leak — the ~1.5M-file leak this fixes) while its inode
    stays STABLE for the journal's whole life (never unlinked mid-life → E-0021 serialization preserved,
    no unlink race). A self-contained temp git repo (its git-common-dir is itself under the tempdir) →
    `<git-common-dir>/yitc-locks/<key>.lock` (inside `.git/`, which land/test working-tree cleanliness
    checks ignore → no tree dirt); otherwise (a non-git temp dir, OR a linked worktree whose common-dir
    is a PERSISTENT repo we must NOT leak locks into) → `<journal-dir>/.yitc-locks/<key>.lock` (a hidden
    subdir beside the journal, inside the temp container). All writers of ONE journal resolve the SAME
    lock path (deterministic from the resolved journal path), so the shared-inode serialization holds.

    T-11061 — A THROWAWAY SCRATCH CONTAINER IN A PERSISTENT TREE IS EPHEMERAL TOO. "Under no temp root"
    is NOT the same question as "persistent": the suite mints 210 scratch journals per run inside the
    REPO tree, and each one leaked a never-reaped `<persistent-root>/yitc-journal-<key>.lock` (the T-10227
    leak class, through the door classification left open — measured 2026-08-13). So when no temp root
    contains the journal, `_throwaway_container` is consulted; when it names a container the SAME
    co-location walk runs against it, and only a checkout's OWN journal keeps the persistent path.

    T-10755 — EPHEMERALITY IS TESTED AGAINST BOTH TEMP ROOTS, never one process's TMPDIR alone. The
    CLASSIFICATION legitimately asks "is this journal inside MY temp container?", so it keeps consulting
    `tempfile.gettempdir()`; but it ALSO accepts `_persistent_lock_root()`. That extra clause is the
    guard against the one regression the env-independent root could introduce: a journal under `/tmp`
    read by a process whose TMPDIR points ELSEWHERE would otherwise be re-classified PERSISTENT and
    leak a sidecar into the temp root — the exact ~1.5M-file class T-10227 closed. The clause strictly
    WIDENS ephemerality and never narrows it. The container-bounded walk below is bounded by whichever
    root actually CONTAINS the journal (the most specific match), so co-location placement is
    byte-identical whenever the two roots coincide — which is every ordinary host.

    T-12621 — `discriminator` appends to the lock's STEM (never its directory), so a second lock over
    the SAME logical journal gets its own inode under the same placement rules. `trail_lock` passes
    `-trail`. The discriminated name deliberately does NOT match `PERSISTENT_LOCK_NAME_RE` (which
    pins exactly 16 hex before `.lock`), so the orphan-sidecar reaper never considers it — correct,
    since a persistent repo's trail lock is alive for the repo's whole life, while an ephemeral
    journal's is co-located in its temp container and torn down with it."""
    tmpdir = Path(tempfile.gettempdir()).resolve()
    persistent_root = _persistent_lock_root()
    # The temp container owning this journal = the most SPECIFIC root it lives under (the private
    # TMPDIR box beats the shared /tmp when the journal is inside the box). None ⇒ PERSISTENT.
    container = None
    for root in (tmpdir, persistent_root):
        if resolved_journal.is_relative_to(root) and (container is None or len(str(root)) > len(str(container))):
            container = root
    own_root = container                                     # the lock MUST resolve inside this dir
    if container is None:
        # T-11061 — not under any temp root, but possibly inside a THROWAWAY scratch container in a
        # persistent tree (an in-repo test scratch dir). Same co-location, same reaping guarantee.
        scratch = _throwaway_container(resolved_journal)
        if scratch is None:
            return persistent_root / f"yitc-journal-{key}{discriminator}.lock"   # PERSISTENT — env-independent (T-10755)
        own_root = scratch
        container = scratch.parent   # the walk below stops BELOW `container`, i.e. it considers `scratch`
    journal_dir = resolved_journal.parent
    common = None                                            # the governing git-common-dir, if under the container
    d = journal_dir
    # Walk up toward — but NEVER into — the container ROOT: the shared temp root is not any single
    # journal's owning container, and an unrelated `.git` right at the root (a stray /tmp/.git) must
    # not be mistaken for this journal's repo. Stop below the root (d == container ends the walk).
    while d != container and d.is_relative_to(container):
        cd = _resolve_git_common_dir(d)
        if cd is not None:
            # The common-dir is adopted ONLY when it lives inside the OWNING container — for a temp-root
            # journal that is the root itself; for a T-11061 scratch container it is the scratch dir, which
            # is what stops a `git worktree add`-ed scratch (whose common-dir is the REAL repo's `.git/`)
            # from placing a never-reaped lock inside that persistent repo.
            common = cd if (cd != own_root and cd.is_relative_to(own_root)) else None
            break
        if d.parent == d:
            break
        d = d.parent
    lock_dir = (common / "yitc-locks") if common is not None else (journal_dir / ".yitc-locks")
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / f"{key}{discriminator}.lock"


@contextlib.contextmanager
def journal_lock(journal_path):
    """E-0021 fix — the SHARED, STABLE advisory lock both `append_event` AND `land`'s pre-ff/ff
    critical section hold, so a direct append and the land read-modify-write SERIALIZE on ONE target.

    Why a SEPARATE sidecar and not the data file itself (the external-consult correctness condition):
    the data file is opened mode='w'/write_text by land (truncates AT open, before any flock could be
    taken) and a future temp-file+rename would swap its inode — either breaks a data-fd flock. The
    sidecar is O_CREAT-only, never truncated/renamed, so its inode is stable and every writer of the
    SAME journal flocks the SAME inode. It is kept OUTSIDE the tracked working tree (never tree dirt /
    land residue) while staying deterministic per journal — its DIRECTORY is derived from the journal's
    ephemerality by `_journal_lock_path` (T-10227): a PERSISTENT real-repo journal keeps the historical
    `<system_tempdir>/yitc-journal-<key>.lock`; an EPHEMERAL journal (under the system tempdir) co-locates
    the sidecar INSIDE its temp container (`.git/yitc-locks/` for a self-contained temp repo, else a
    hidden `.yitc-locks/` beside the journal) so it is reaped WITH the container instead of leaking a
    never-removed file into the /tmp root (the ~1.5M-file leak). Extends T-0464 (which flocked only the
    append fd, missing the land RMW — the E-0021 silent-loss window). Advisory + process-local is
    sufficient: every writer is bin/yitc-v2 (same idiom as `_with_repo_lock` / `_id_alloc_lock`). NOT
    safe over NFS.

    Cross-user open (X-0226 fix, T-10189): the sidecar is opened via `lockfile.open_flock_target` —
    the ONE flock-target open in the codebase (T-10336 hoisted the idiom this function invented into
    `bin/lib/lockfile.py`, which carries the full rationale). It never truncates and never demands
    WRITE permission, so a second group-dev user reaching a sidecar the first user created opens it
    cleanly instead of dying on `session start` with EACCES. The SAME create-or-open fallback serves
    the co-located ephemeral sidecar too (shared users are still possible in a temp container)."""
    # SPEC-0190 rule 1 — LOCK ON THE LOGICAL JOURNAL, never on a physical segment. `logical_journal`
    # maps an archive segment back to its live segment (and everything else to itself), so rotation's
    # two writes, a concurrent `append_event`, and a land's read-modify-write all flock ONE inode.
    # Resolve AFTER the mapping: the mapping is a pure path derivation and resolving first would only
    # move the same question behind a symlink.
    resolved = logical_journal(journal_path).resolve()
    key = journal_lock_key(resolved)
    lock_path = _journal_lock_path(resolved, key)
    fd = lockfile.open_flock_target(lock_path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)   # releases the advisory flock

@contextlib.contextmanager
def trail_lock(journal_path):
    """T-12621 (X-1437) — the SPEC-0169 rule-9 TRAIL lock: a sibling of `journal_lock` over the same
    logical journal, on its OWN inode.

    THE RACE IT CLOSES. `grants.append_trail_record` reads the trail head, chains `prev` off it,
    appends, then asserts its own record is the TAIL. That is a read-modify-write, and two concurrent
    appenders therefore (a) fork the `prev` chain and (b) make the loser's tail assertion fail —
    which is exactly X-1437: two deploys ~1s apart, the loser refused with «the trail record was not
    readable back … SPEC-0169 rule 9» before running anything. The grants gate runs BEFORE the `-C`
    rebind (necessarily — argparse has not run), so in production the record lands in the ENGINE
    journal whatever project is targeted: two deploys of DIFFERENT projects append to ONE file. A
    per-project deploy lock provably cannot cover that without breaking per-project concurrency, so
    the fix belongs here, at the trail's own seam.

    WHY A SEPARATE INODE AND NOT `journal_lock`. `journal_lock` is NOT re-entrant within a process
    (`evidence_custody.py` states this and hand-codes a skip to avoid the self-deadlock) and
    `append_event` takes it INTERNALLY — and `append_trail_record` calls `append_event` inside the
    critical section this must cover. Sharing one inode would therefore deadlock every trail append.
    The `-trail` discriminator reuses `logical_journal` + `journal_lock_key` + `_journal_lock_path`
    placement UNCHANGED (SPEC-0190 rule 1: lock on the LOGICAL journal, never a physical segment), so
    there is no second placement policy to drift.

    The window held is the whole read-modify-write, which is the smallest window that is still a
    lock, and it serializes exactly the trail-appender population — the only population that can
    change what `read_trail` returns."""
    resolved = logical_journal(journal_path).resolve()
    key = journal_lock_key(resolved)
    lock_path = _journal_lock_path(resolved, key, "-trail")
    fd = lockfile.open_flock_target(lock_path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)   # releases the advisory flock


@contextlib.contextmanager
def redact_lock(journal_path):
    """T-12779 (SPEC-0163 rule 4c) — the REDACTION lock: a THIRD instance of the discriminated
    sidecar `trail_lock` (T-12621) parameterized, over the same logical journal, on its OWN inode.

    THE RACE IT CLOSES. `journal redact` is RECEIPT-BEFORE-REWRITE: it appends one
    `journal_redacted` receipt and then rewrites the named row. Two concurrent invocations against
    the SAME row would therefore each append a receipt, and the loser's rewrite would either lose to
    the winner's or find the row already redacted — leaving a SECOND receipt that describes a
    redaction that never happened and that the orphan-receipt reader can never complete (the reader
    completes an orphan under the SAME receipt; it cannot reconcile two contradictory ones). That is
    the X-1437 shape the sibling `trail_lock` closed, one seam over.

    P1 FILTERS, written down (CHARTER §Principle 1). (F1) EXISTING ANALOG — `trail_lock` is the
    analog, and the `discriminator` parameter it introduced on `_journal_lock_path` is REUSED
    verbatim: this is a third CALLER of ONE primitive, not a second locking mechanism. (F2) VIEW OVER
    ENTITY — no new state; a lock is not storage. (F3) WHAT IS REMOVED — the "two concurrent
    redactions each append a receipt" window, and with it the un-completable second orphan that
    window creates. (F4) REAL INCIDENT / PRIOR-ART — X-1437 is the measured sibling incident that
    produced `trail_lock`; this card's audit-pre r1 finding 3 names the identical shape here.

    WHY A SEPARATE INODE AND NOT `journal_lock`: identical to `trail_lock`'s reason — `journal_lock`
    is NOT re-entrant within a process and `append_event` takes it INTERNALLY, while the critical
    section here must span an `append_event` AND two `journal_lock`-held segment reads. Sharing one
    inode would deadlock every redaction.

    LOCK ORDERING IS FIXED AND ACYCLIC: `redact_lock` is always taken FIRST and `journal_lock` only
    INSIDE it; nothing else ever takes `redact_lock`, so no cycle exists. The window held is the
    WHOLE operation (orphan lookup -> read -> receipt -> rewrite), which is what makes "at most one
    receipt per row" an invariant rather than a hope, and it serializes exactly the redaction
    population — one logical journal at a time, so redactions in different repos never contend."""
    resolved = logical_journal(journal_path).resolve()
    key = journal_lock_key(resolved)
    lock_path = _journal_lock_path(resolved, key, "-redact")
    fd = lockfile.open_flock_target(lock_path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)   # releases the advisory flock


# T-9694: the engine's known event-type vocabulary — DERIVED, never a hardcoded duplicate list
# (CHARTER §P5; SPEC-0025 "Other event types emerge organically... no upfront catalog"). Two regexes:
# (a) the first STRING-LITERAL arg of an `_append_event("…"` / `append_event("…"` call site (the verbs
# that emit); (b) the TOP-LEVEL `type` of each events.jsonl line (types that emerged organically via the
# generic `event` verb — parsed as JSON so a nested `data.type` is NOT mistaken for an event type). The
# `append_event` definition line itself has no quoted first arg after the paren → never matched.
_EVENT_LITERAL_RE = re.compile(r"""append_event\(\s*["']([a-z][a-z0-9_]+)["']""")
_EVENT_TYPE_SHAPE_RE = re.compile(r"[a-z][a-z0-9_]+\Z")
_known_event_types_cache: dict = {}


def _declared_cross_event_types() -> set:
    """Source 3 — the `cross_*` protocol vocabulary, DERIVED from `cross.py`'s own FSM constants
    (never a hardcoded copy, CHARTER §P5). Those events reach the kernel-owned SHARED coordination
    log (out-of-repo, SPEC-0084) through `cross_emit`, NOT an `append_event('<literal>')` call site,
    so neither the call-site scan nor this repo's `events.jsonl` can see them — yet they are as real
    as any emitted type (`cross show X-0240`). Every declared event necessarily appears in at least
    one of these containers, so a NEW cross event added to `cross.py` joins the catalog with zero
    edits here. Fail-OPEN: any import/attribute fault yields the empty set, never a crash."""
    names: set = set()
    try:
        from lib import cross  # leaf module, stdlib-only — no cycle back into events.py
        for attr in ("AUTHOR_EVENTS", "RECEIVER_EVENTS", "TERMINAL_EVENTS",
                     "EVENT_KINDS", "EVENT_STATUS"):
            names.update(n for n in getattr(cross, attr, ()) or ()
                         if isinstance(n, str) and _EVENT_TYPE_SHAPE_RE.match(n))
    except Exception:
        return set()
    return names


def _declared_operator_emit_event_types() -> set:
    """Source 4 — the OPERATOR-EMIT vocabulary, DERIVED from the engine constants that NAME an event
    an operator fires by hand through the generic `event` verb (never a hardcoded copy, CHARTER §P5).
    SPEC-0156's admission-demonstration event (`debt.ADMISSION_EVENT`, `check_admission_demonstrated`)
    rides `bin/yitc-v2 event check_admission_demonstrated --data …` (SPEC-0156 §2 admits NO new verb,
    NO new emitter) — so it has NO `append_event('<literal>')` call site (source 1 is blind), and until
    an operator has actually demonstrated one it is ABSENT from this repo's `events.jsonl` too (source 2
    is blind). Yet the type is as DECLARED as any emitted one, and the `task file` probe-lint false-WARNs
    a correct SPEC-0156 acceptance naming it — the same shared-log blindness `_declared_cross_event_types`
    fixed for `cross_*` (T-10287). Deriving from the constant means the day the name changes there, the
    catalog follows with zero edits here. Fail-OPEN: any import/attribute fault yields the empty set."""
    names: set = set()
    try:
        from lib import debt  # leaf import — no cycle back into events.py
        name = getattr(debt, "ADMISSION_EVENT", None)
        if isinstance(name, str) and _EVENT_TYPE_SHAPE_RE.match(name):
            names.add(name)
    except Exception:
        return set()
    return names


def known_event_types(events_path=None, observed=None) -> frozenset:
    """The set of journal event-type names the engine ACTUALLY emits — DERIVED, never hardcoded
    (CHARTER §P5). Three unioned + per-process-cached sources: (1) the engine's own `_append_event`
    call-site literals scanned from the colocated engine source (this module's dir *.py + the sibling
    `yitc-v2` host script) — the verbs that emit; (2) `type` values OBSERVED in `events_path` (the
    organic catalog, SPEC-0025); (3) the `cross_*` vocabulary DECLARED by `cross.py`'s FSM constants
    (`_declared_cross_event_types` — the shared-log family sources 1+2 are structurally blind to,
    whose absence false-WARNed correct probes naming `cross_done`, T-10287); (4) the operator-emit
    vocabulary DECLARED by engine constants (`_declared_operator_emit_event_types`, e.g.
    `debt.ADMISSION_EVENT` — a `event`-verb-fired type with no emit call site, absent until first
    demonstrated, whose absence false-WARNed the SPEC-0156 admission probe, T-10692). Best-effort + fail-OPEN:
    any unreadable source is skipped (a
    report-only authoring aid must never crash a write); an empty result tells the caller to no-op.
    Consumed by the `task file` structural pre-pass (SPEC-0046) to WARN on an acceptance probe naming
    a non-existent event type — the unsatisfiable-by-construction probe class (T-9694 / X-0134).

    `observed` (T-13334): the journal's type set ALREADY COLLECTED by a caller's one-pass walk of
    `events_path` (`task file`'s scope — the followup reducer sees every row's type). Given, it is
    source 2, in place of this function's own segment read, and the result is not cached (it belongs
    to that walk). The shape filter below applies to it unchanged."""
    key = str(events_path) if events_path else ""
    cached = _known_event_types_cache.get(key) if observed is None else None
    if cached is not None:
        return cached
    names: set = set()
    # source 1: engine emit call sites (stable per process) — colocated modules + host script
    lib_dir = Path(__file__).resolve().parent
    src_files = list(lib_dir.glob("*.py"))
    host = lib_dir.parent / "yitc-v2"
    if host.exists():
        src_files.append(host)
    for f in src_files:
        try:
            names.update(_EVENT_LITERAL_RE.findall(f.read_text(encoding="utf-8")))
        except OSError:
            continue
    # source 2: organically-emitted types observed in the journal (best-effort). Parse each line as
    # JSON and take ONLY the top-level `type` — a nested `data.type` must NOT pollute the catalog (it
    # would mask a genuinely-unknown probe token). Per-line fail-open: a malformed line is skipped.
    # T-11444 — the ORGANIC catalog is a property of the WHOLE logical journal, so this folds the
    # SEGMENT SET (SPEC-0190 rule 4), not the live segment alone: a type last emitted before the live
    # window would otherwise drop out of the catalog and false-WARN a correct acceptance probe.
    # It iterates `segment_paths` with its OWN loop rather than calling `journal.segment_rows`
    # BECAUSE OF THE LAYERING: `journal.py` imports THIS module and never the reverse, so a fold
    # call from the leaf would be an import cycle. One segment ⇒ byte-identical to the prior read.
    if observed is not None:
        names.update(t for t in observed if isinstance(t, str) and _EVENT_TYPE_SHAPE_RE.match(t))
    elif events_path:
        for seg in segment_paths(events_path):
            try:
                text = Path(seg).read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                t = obj.get("type") if isinstance(obj, dict) else None
                if isinstance(t, str) and _EVENT_TYPE_SHAPE_RE.match(t):
                    names.add(t)
    # source 3: the shared coordination log's declared `cross_*` vocabulary (never call-site-visible)
    names.update(_declared_cross_event_types())
    # source 4: the operator-emit vocabulary DECLARED by engine constants (e.g. debt.ADMISSION_EVENT):
    # events fired by hand through the generic `event` verb — no emit call site, absent until demonstrated
    names.update(_declared_operator_emit_event_types())
    result = frozenset(names)
    if observed is None:
        _known_event_types_cache[key] = result
    return result


def _byte_head(text: str, nbytes: int) -> str:
    return text.encode("utf-8")[:nbytes].decode("utf-8", "ignore")


def _byte_tail(text: str, nbytes: int) -> str:
    return text.encode("utf-8")[-nbytes:].decode("utf-8", "ignore")


def _event_summary(data: dict, width: int = 100) -> str:
    """One-line human render of an event's `data` payload (k=v, compact). Dict/list values
    serialize to compact JSON; the whole string is ellipsis-truncated to `width`."""
    if not data:
        return ""
    parts = []
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        parts.append(f"{k}={v}")
    s = " ".join(parts)
    return s if len(s) <= width else s[: width - 1] + "…"


def _json_default(o):
    """json.dumps `default=` hook for the single journal-append chokepoint.

    Normalizes ONLY datetime.date / datetime.datetime payload values to ISO-8601 strings — the
    class of crash where an unquoted YAML timestamp (yaml.safe_load → datetime) reaches an event
    payload and json.dumps raises `Object of type datetime is not JSON serializable` (nightly
    exit-1, 2026-07-21; T-10701). datetime.datetime is a subclass of datetime.date, so the single
    isinstance covers both and .isoformat() exists on both. Any OTHER unsupported type STILL raises
    TypeError loudly — this is NOT a swallow-everything str() fallback (SPEC-0165 loud-failure).
    """
    if isinstance(o, (datetime.datetime, datetime.date)):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def witness_path(events_path) -> str:
    """The journal path AS THE WITNESS REPORTS IT — always ABSOLUTE (T-10949).

    A relative target (a relative `YITC_EVENTS_SINK`, a relative explicit `events_path=`) would
    otherwise produce a witness interpretable only against the emitting process's cwd — which the
    later investigator does not have, so it would name no file and attribute no absence. That is the
    very defect the witness exists to close, so BOTH legs here are absolute:
      - `resolve()` is preferred — it also normalizes symlinks, so the witness names the same file a
        later investigator would `stat`;
      - `abspath` is the lexical belt, taken when resolve() cannot run. It must NOT degrade to the
        raw string: that would reinstate the defect for exactly the caller unlucky enough to trip it
        (audit-post pass-2 finding).
    If `abspath` ITSELF raises, the process cannot determine its own cwd — raising LOUDLY beats
    returning a cwd-relative witness that silently attributes nothing (SPEC-0165 loud-failure).

    A named helper rather than an inline expression so both legs are directly reachable by the
    tripwire: forcing the fallback in-process is otherwise impossible without breaking the journal
    lock, which resolves the same path.
    """
    try:
        return str(Path(events_path).resolve())
    except (OSError, ValueError):
        return os.path.abspath(str(events_path))


#: T-12844 — the SPEC-0191 §5 halt-row classification literals (SPEC-0161 `block_classification`).
BLOCK_CLASSIFICATION_UNCLASSIFIED = "unclassified"
#: T-12844 — `block_classified` is RETIRED: it never had an emitter, and the halt row itself carries
#: the classification now. `event` refuses a new append; historical rows stay read-only.
RETIRED_BLOCK_CLASSIFIED_TYPE = "block_classified"


def is_blocked_on_land_halt(data) -> bool:
    """T-12844 — is this `bg_dispatch_halted` payload a blocked-on-land halt? True for the SPEC-0103
    §3 shape (`blocked_on_land: true` — the verb and the land repeated-abort backstop) and for the
    audit-loop ceiling halt (it carries `residual_fingerprints`, SPEC-0204 rule 6). Pure."""
    return isinstance(data, dict) and (bool(data.get("blocked_on_land"))
                                       or "residual_fingerprints" in data)


def derive_block_classification(data) -> "str | None":
    """T-12844 — the `block_classification` a blocked-on-land halt row must carry, or None when the
    payload is not such a halt. A present value wins; a drifted `ladder_rung` / `rung` naming rung
    1..3 (int, "2" or "rung-2") normalizes to `rung-N`; anything else is the explicit `unclassified`,
    never a blank. Pure f(data); never raises."""
    if not is_blocked_on_land_halt(data):
        return None
    present = data.get("block_classification")
    if isinstance(present, str) and present.strip():
        return present.strip()
    for key in ("ladder_rung", "rung"):
        raw = str(data.get(key) if data.get(key) is not None else "").strip().lower()
        raw = raw[len("rung-"):] if raw.startswith("rung-") else raw
        if raw in ("1", "2", "3"):
            return f"rung-{raw}"
    return BLOCK_CLASSIFICATION_UNCLASSIFIED


def append_event(
    event_type: str,
    task_id: str | None,
    data: dict | None,
    *,
    agent: str = "main",
    session_ref: str,
    spawned_by: str | None = None,
    source_ref: str | None = None,
    ts: str,
    events_path,
    guard=None,
    text_cap: bool = False,
) -> dict:
    """Single emission path for events.jsonl — shared by all subcommands (Principle 5).

    RETURNS THE WITNESS (T-10949 — closing T-10948 residual R3). Until this change the function
    returned None: the resolved target, the ts and the exact bytes written all existed inside the
    write and were thrown away at the return, so a SUCCESSFUL emit left exactly ONE artifact — the
    row. That is why the 2026-08-11 lost capture (fingerprint
    `journal-append-lost-across-concurrent-land-ff`) could not separate «overwritten» from «never
    written»: with the row absent there was no second thing to inspect. The witness returned here is
    a VIEW over values this write already holds — nothing new is persisted, no store, no receipts
    file, no sidecar (CHARTER §Principle 5: one journal, one format, one parser). It answers R3's
    question, «did it write, and WHERE»:
      path   — the RESOLVED target, so a redirect (YITC_EVENTS_SINK / --read-only / -C) is
               distinguishable from a row written here and later lost;
      ts     — the canonical, greppable row locator (`events.jsonl#ts=<ISO>`, CHARTER §Principle 2);
      offset/bytes — where in the file the row went, so a file now SHORTER than the offset reads as
               truncate-and-rewrite while a longer one missing that ts reads as overwrite-in-place;
      sha256 — a 12-hex prefix of the exact line, so a candidate row can be CONFIRMED to be the row
               (a ts alone can repeat under concurrency).
    Callers are free to ignore it — every existing call site does; `cmd_event` prints it.

    The host-coupled inputs are RESOLVED BY THE CALLER (the bin/yitc-v2 `_append_event` wrapper) and
    passed in: `session_ref` (the fail-closed-resolved identity), `ts` (the host `_utc_now_iso()` or an
    adapter-supplied source ts, T-0095), `events_path` (the final target — the wrapper applies the
    YITC_EVENTS_SINK quarantine + the worktree-new override + the current EVENTS_PATH, T-0357/D-0054),
    and `guard` (the optional SPEC-0078 consumer→engine write-boundary check, invoked on the target
    before the write). This keeps the module free of REPO_ROOT / env / identity coupling.

    O_APPEND: atomic для writes < PIPE_BUF (typically 4 KiB on Linux).
    patterns/atomic-state-file-writes.md §When NOT к apply — events.jsonl
    = append-only journal; tempfile+os.replace inappropriate, would erase history.

    Provenance fields (D-0030 provenance_fields_schema) are envelope-level siblings of
    ts/type/task_id (writer-origin metadata, distinct from semantic `data`):
      - agent: writer identity (default 'main'; param accepts audit-subprocess/cron/manual
        for future genuine subprocess/cron writers — current callsites all = main).
      - session_ref: fail-closed-resolved this-writer session identifier.
      - spawned_by: parent session_ref for subprocess writers; None for all current callsites.
      - source_ref: source-log entry locator for parser-captured events (T-0051); None for
        CLI lifecycle emits.
      - text_cap: OPT-IN to the SPEC-0002 verbatim-text overflow shape (T-12732). ONLY the
        transcript adapter passes True — its rows are the «parser-captured rows» SPEC-0002 §Size cap
        scopes the shape to. Every other caller stores its payload WHOLE: a CLI capture
        (`followup add`, `event --data '{"text":…}'`) is a record whose whole point is the text, and a
        silently shrunk record that still renders as complete is the capture-axis false GREEN
        (<project> X-1490 — a design measurement lost past ~2800 bytes, exit 0, re-read the document
        to recover it). Append atomicity does not depend on the cap (the sidecar flock, E-0021).
    """
    payload = dict(data or {})
    payload["source"] = SOURCE_TAG
    event: dict = {"ts": ts, "type": event_type}   # T-0095: adapter may supply
                                                    # the source-entry (utterance) ts
    if task_id:
        event["task_id"] = task_id
    event["agent"] = agent
    event["session_ref"] = session_ref
    event["spawned_by"] = spawned_by
    event["source_ref"] = source_ref
    event["data"] = payload
    # SPEC-0002 byte cap for parser-captured TEXT events: shrink payload['text'] against
    # the REAL serialized envelope until ≤ MAX_EVENT_BYTES (audit-post F2 — real envelope,
    # not a placeholder). SCOPED BY `text_cap` (T-12732): until then the condition read ANY
    # text-bearing payload, so a CLI capture with a `text` key was silently shrunk past ~2800
    # bytes while the comment here claimed caller-sized payloads were «NOT force-truncated» —
    # the code contradicted its own scope note and SPEC-0002's «parser-captured rows». Now the
    # adapter that shaped the row through `cap_text` declares it, and every other row is
    # stored whole; no whole-event truncator and no new ceiling (anti-complexity Principle 1 —
    # the lock, not the cap, carries atomicity).
    line = json.dumps(event, ensure_ascii=False, default=_json_default)
    if text_cap and len(line.encode("utf-8")) > MAX_EVENT_BYTES and isinstance(payload.get("text"), str):
        full = payload["text"]
        payload.setdefault("original_size_chars", len(full))
        payload.setdefault("sha256", hashlib.sha256(full.encode("utf-8")).hexdigest())
        payload["truncated"] = True
        keep = len(full)
        while len(json.dumps(event, ensure_ascii=False, default=_json_default).encode("utf-8")) > MAX_EVENT_BYTES and keep > 80:
            keep = int(keep * 0.8)
            payload["text"] = _byte_head(full, keep * 3 // 4) + "\n…[elided]…\n" + _byte_tail(full, keep // 4)
        line = json.dumps(event, ensure_ascii=False, default=_json_default)
    if guard is not None:
        guard(events_path)  # SPEC-0078: reject consumer→ENGINE_ROOT journal writes (host-injected)
    if _GUARDED_JOURNALS:   # T-10401: inert in production (unset var); armed only under the test harness
        try:
            target = Path(events_path).resolve()
        except OSError:     # unresolvable target — let the real write path report it
            target = None
        if target in _GUARDED_JOURNALS:
            raise AssertionError(
                f"T-10401 test-hermeticity guard: this test appended to the LIVE journal ({target}). "
                "A test must emit only into its own sandbox — the real events.jsonl is append-only, so a "
                "phantom row cannot be taken back (it re-enters the fleet-verdict recency window and wakes "
                "armed `dispatch --watch` monitors). Patch EVERY path that resolves the journal, including "
                "the REPO_ROOT-derived ones an EVENTS_PATH patch does NOT reach: lib/dispatch.py appends "
                "with an explicit events_path=_main_worktree(REPO_ROOT)/'events.jsonl', so patch "
                "yitc.REPO_ROOT to your sandbox too."
            )
    # E-0021: take the SHARED sidecar journal lock around the append (supersedes the T-0464 data-fd
    # flock). This serializes appends with each OTHER (O_APPEND atomicity beyond PIPE_BUF — the
    # `startup-event-emit-silent-loss-concurrent-main-checkout` root, events.jsonl#ts=2026-06-03T07:56:59Z)
    # AND with `land`'s pre-ff read-modify-write of main (which holds the SAME sidecar lock) — closing
    # the E-0021 window where a direct append landing between land's re-fold READ and its ff WRITE was
    # silently overwritten (events.jsonl#ts=2026-06-09T08:45:44Z). The sidecar (not the data fd) is the
    # lock target so land's truncating rewrite / a future temp+rename cannot swap the locked inode.
    row = (line + "\n").encode("utf-8")
    with journal_lock(events_path):
        with open(events_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            # The offset is read INSIDE the lock, from the fd that just wrote — under O_APPEND the
            # post-write position IS the row's end, so `end - len(row)` is where this row starts. Read
            # outside the lock it would be a race (a sibling append could advance the file first).
            end = fh.tell()
    # The path is ABSOLUTE-resolved (audit-post finding, T-10949). A relative target — a relative
    # `YITC_EVENTS_SINK`, a relative explicit `events_path=` — would produce a witness that is only
    # interpretable against the emitting process's cwd, which the later investigator does not have.
    return {
        "path": witness_path(events_path),
        "ts": ts,
        "type": event_type,
        "offset": end - len(row),
        "bytes": len(row),
        "sha256": hashlib.sha256(row).hexdigest()[:12],
    }


# ---------------------------------------------------------------------------------------------
# T-12704 (C11a) — the `event` verb + the CLI-invoked emit, relocated here byte-identical from
# `bin/lib/cli.py` (plan extract-the-13-over-budget-bin-lib-modules-into-le §Extraction map C11a;
# lessons/library-extraction.md — Design B full inject-residue seam). Bodies are VERBATIM copies of
# the host originals; every non-stdlib, non-moved free name is a keyword-only inject the host residue
# supplies from ITS live globals at call time (so `-C` rebinds + `monkeypatch.setattr(yitc, ...)` stay
# honoured). The two closed inject tuples below are what the residues iterate.
# ---------------------------------------------------------------------------------------------


_MID_TURN_MACHINERY_MARKERS = ("<task-notification>", "<cross-session-message", "<system-reminder>")


def _mid_turn_owner_text_refusal(data: dict, source_ref, *, _classify_cc_entry, _extract_text):
    """T-12801 — prove a mid-turn delegated owner_directive's `owner_text` at the write, or return the
    refusal reason (None = proven). Pure read of the transcript the locator names.

    The locator must be ANCHORED `<transcript>#uuid:<uuid>`; that entry must be OWNER-authored — a
    `user` entry `_classify_cc_entry` labels owner_directive, or a `queued_command` attachment with
    `commandMode: prompt` (the mid-turn entrance the T-12649 parser dropped) that is not harness
    machinery (a peer/cross-session message or a task-notification); and `owner_text` must EQUAL that
    entry's COMPLETE text, whitespace-collapsed — or, when omitted, is set to it in `data` (T-13196). Equality, not containment: a fragment such as «go»
    lifted from a message about another card must not ride as authority (audit-pre fp1:03161efc)."""
    if data.get("mid_turn") is not True:
        return "`mid_turn` must be the JSON literal true"
    if data.get("captured_via") != "controller-delegated":
        return "a mid-turn row is a `captured_via: controller-delegated` capture"
    owner_text = data.get("owner_text")
    # T-13196: an OMITTED owner_text is taken from the anchored entry (the verb already reads it);
    # a SUPPLIED one must still EQUAL it.
    derive = owner_text is None
    if not derive and (not isinstance(owner_text, str) or not owner_text.strip()):
        return "`owner_text` must carry the owner's verbatim words (non-empty string), or be omitted"
    loc = str(source_ref or "")
    path_part, sep, anchor = loc.partition("#")
    if not sep or not anchor.startswith("uuid:") or not anchor[5:].strip():
        return "the source_ref must be ANCHORED `<transcript>#uuid:<entry uuid>`"
    want = anchor[5:].strip()
    entry = None
    try:
        with open(path_part, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if want not in line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(e, dict) and e.get("uuid") == want:
                    entry = e
                    break
    except OSError as exc:
        return f"the transcript cannot be read: {exc}"
    if entry is None:
        return f"no transcript entry carries uuid {want!r}"
    att = entry.get("attachment") if isinstance(entry.get("attachment"), dict) else None
    if entry.get("type") == "attachment" and att is not None and att.get("type") == "queued_command":
        origin = att.get("origin") if isinstance(att.get("origin"), dict) else {}
        text = _extract_text(att.get("prompt")) if not isinstance(att.get("prompt"), str) else att.get("prompt")
        if att.get("commandMode") != "prompt" or origin.get("kind") == "peer" \
                or any(m in (text or "") for m in _MID_TURN_MACHINERY_MARKERS):
            return "the anchored queued_command is harness machinery, not an owner prompt"
    elif _classify_cc_entry(entry) == "owner_directive":
        text = _extract_text(entry.get("message", {}).get("content"))
    else:
        return "the anchored entry is not owner-authored"
    if derive:
        if not str(text or "").strip():
            return "the anchored owner entry carries no text to record"
        data["owner_text"] = str(text)
        return None
    if " ".join(str(text or "").split()) != " ".join(owner_text.split()):
        return "`owner_text` does not EQUAL the anchored owner entry's complete text"
    return None

CMD_EVENT_INJECTS = (
    "EVENTS_PATH",
    "KERNEL_NAME",
    "PLACEMENT_REALMS",
    "REPO_ROOT",
    "RESERVED_DATA_KEYS",
    "RESERVED_DATA_KEY_REDIRECT",
    "SANDBOX_LIFECYCLE_PAYLOAD_KEYS",
    "SOURCE_REF_REQUIRED_TYPES",
    "TASK_ID_RE",
    "TRIAGE_CONTENT_EVENT_TYPES",
    "_actor",
    "_append_event",
    "_auto_file_kernel_deviations",
    "_capture_fingerprint_counts",
    "_classify_cc_entry",
    "_die",
    "_git_resolve_sha",
    "_pre_claim_refuse_hint",
    "_reopen_resolved_error",
    "_resolve_owner_directive_source_ref",
    "_uncatalogued_emit_refusal",
    "_near_synonym_emit_warning",
    "_packet_fold_emit_warning",
    "_utc_now_iso",
    "_extract_text",
    "_validated_explicit_source_ref",
    "audit",
    "cross",
    "debt_mod",
    "events",
    "journal",
    "observe",
    "validate_sandbox_lifecycle_payload",
    "P8_EVIDENCE_TYPES",
)


def cmd_event(args: argparse.Namespace, *, EVENTS_PATH, KERNEL_NAME, PLACEMENT_REALMS, REPO_ROOT, RESERVED_DATA_KEYS, RESERVED_DATA_KEY_REDIRECT, SANDBOX_LIFECYCLE_PAYLOAD_KEYS, SOURCE_REF_REQUIRED_TYPES, TASK_ID_RE, TRIAGE_CONTENT_EVENT_TYPES, _actor, _append_event, _auto_file_kernel_deviations, _capture_fingerprint_counts, _classify_cc_entry, _die, _extract_text, _git_resolve_sha, _pre_claim_refuse_hint, _reopen_resolved_error, _resolve_owner_directive_source_ref, _uncatalogued_emit_refusal, _near_synonym_emit_warning, _packet_fold_emit_warning, _utc_now_iso, _validated_explicit_source_ref, audit, cross, debt_mod, events, journal, observe, validate_sandbox_lifecycle_payload, P8_EVIDENCE_TYPES=("consumer_read_evidence", "live_trigger_evidence")) -> None:
    # Boundary note (T-0048 audit, per D-0030): this generic verb + every other
    # _append_event callsite in this file emit LIFECYCLE / diagnostic events only
    # (task_filed/closed/parked/wont_do, audit_{stage}_completed,
    # external_audit_completed, graph_built). Chat-class events
    # (owner_directive / instruction_injection / slash_command / audit_prompt_sent)
    # are NOT emitted here by AI discretion — they are parser-captured from the
    # provider session log by the adapter (T-0051). D-0024/D-0030 retired the
    # AI-must-remember-to-emit obligation; it was never a CLI callsite, so there is
    # nothing to retire in code (audit: zero chat-class emit callsites found).
    # Do NOT add an owner_directive/instruction_injection emit path here.
    #
    # T-10600 (X-0447) — the note above states the DESIGN, but this verb accepts a free-form type, and
    # an owner-register session walked straight through it: a hand-emitted owner_directive landed with
    # `source_ref: null` + an identity session_ref naming no transcript. The registration is real and
    # legitimate (a live owner cue the adapter never sees), so it is GATED, not forbidden: an
    # AUTHORITY-class type must carry a locator that resolves, or registration refuses.
    event_type = (args.type or "").strip()
    if not event_type:
        _die("event type must be non-empty")

    # T-11601: the TYPE NAME is judged FIRST, above every other pre-append check, because it is the
    # one property of this row that becomes unfixable the instant the row exists (append-only). A
    # refusal here leaves the journal byte-identical and prints no witness and no WARN. Contract,
    # rationale and the fail-open set live in `_uncatalogued_emit_refusal`; this stays a call site.
    _cat_refusal = _uncatalogued_emit_refusal(event_type)
    if _cat_refusal:
        _die(_cat_refusal)
    # T-13115: report-only, never a refusal — contract and fail-open set in `_near_synonym_emit_warning`.
    _near_warn = _near_synonym_emit_warning(event_type)
    if _near_warn:
        print(_near_warn, file=sys.stderr)

    # Resolve BEFORE any append: a refusal must leave the journal untouched (no null-source_ref row).
    # Also ABOVE the `--check` early return further down, so a no-write validation exercises the
    # identical locator contract.
    # `getattr`, not attribute access — matching the `check` flag's idiom just below: several in-repo
    # callers construct the Namespace by hand and omit the optional flags. Before this branch existed
    # `args.source_ref` was only ever touched inside the authority arm, so those callers never hit it;
    # reading it unconditionally would turn an omitted OPTIONAL flag into an AttributeError.
    _explicit_source_ref = getattr(args, "source_ref", None)
    source_ref = None
    if event_type in SOURCE_REF_REQUIRED_TYPES:
        source_ref = _resolve_owner_directive_source_ref(_explicit_source_ref)
    elif _explicit_source_ref is not None:
        # T-11741 (X-1174): an EXPLICIT locator persists for ANY event type — or the emit refuses
        # naming the reason. What is NOT admissible is the third outcome this replaces: accepting the
        # flag, exiting 0, and storing null. The AUTHORITY branch above still wins for its types (it
        # both derives and filesystem-verifies); this branch is reached only when the caller
        # explicitly passed a value, so every omitted-flag emit keeps `_append_event`'s legitimately
        # open null default, bit-for-bit unchanged.
        source_ref = _validated_explicit_source_ref(_explicit_source_ref)

    if args.task is not None and not TASK_ID_RE.match(args.task):
        _die(f"invalid --task id: {args.task!r}")

    data: dict = {}
    # (the declared-class check on a `test_class_executed` payload runs just below, once `data` is
    #  parsed — still inside this pre-append block, so a refusal leaves the journal untouched)

    # T-11676 (X-1132): `--data` PRESENT but BLANK is a payload that VANISHED, and it is refused here,
    # inside the pre-append block, so the journal stays byte-identical. The reported shape: a session
    # wrote its payload to a fixed shared temp name and piped it in as `--data "$(cat <that path>)"`
    # on the SAME shell line. The write was refused (the path already existed, owned by a concurrently
    # running sibling session) and the `cat` in that same line then read the FOREIGN file — so the verb
    # appended another session's payload under this task id, unrecoverably, into an append-only store.
    # The EMPTY arrival is the earlier, catchable symptom of that same line, and this is where it fails
    # closed. Concurrent sessions are the NORMAL configuration here (D-0083), so a shared temp name is
    # a collision surface by construction, not by bad luck.
    #
    # THE DISCRIMINATOR — present-but-blank, never absent. `--data` OMITTED is a caller deliberately
    # emitting no payload and is UNTOUCHED: it stays governed by T-11417's content-free WARN, which
    # records the row because capture is a one-command reflex (D-0035/D-0086) and a lost capture is
    # strictly worse than a thin one. Only a `--data` the caller REACHED FOR and that arrived empty is
    # refused — nothing is lost there, because nothing ever existed. (T-11417's own probes spelled
    # "no payload" as `--data ""`; that spelling, and only that spelling, moves with this change —
    # its stated intents are carried unchanged by the flag-omitted form. Fork adjudicated at the
    # T-11676 audit-pre, FULL tier, GREEN: "O1 accepted".)
    if args.data is not None and not args.data.strip():
        _die("--data was given but arrived EMPTY — the payload never reached this verb, and the "
             "journal is append-only, so a row written now could not be corrected later. A common "
             "cause is a command substitution that produced nothing: `--data \"$(cat <file>)\"` "
             "where the file was missing or the write to it was refused. NEVER compose a payload at "
             "a fixed shared temp name — concurrent sessions on this host share that namespace and a "
             "`cat` can silently succeed against ANOTHER session's file (X-1132). Compose it under a "
             "per-invocation temp file in the gitignored `.scratch/` dir (`"
             + vocab.SCRATCH_TEMPFILE_RECIPE + "`) — never the checkout root, where a commit "
             "verb's add-all would stage it (T-12930) — or inline the "
             "JSON. To emit no payload at all, OMIT --data — that is a different, permitted thing and "
             "is not refused. Nothing was appended.")

    if args.data:
        try:
            parsed = json.loads(args.data)
        except json.JSONDecodeError as e:
            _die(f"--data must be valid JSON: {e}")
        if not isinstance(parsed, dict):
            _die("--data must be a JSON object (not array/scalar)")
        reserved = RESERVED_DATA_KEYS.intersection(parsed)
        if reserved:
            # T-10735 (X-0603): name the offending key AND where its value belongs instead. Listing
            # the set alone told the caller what NOT to do and nothing else — it cost a debug cycle
            # and left junk in an append-only journal. The `.get` fallback keeps the redirect total
            # for any key that joins RESERVED_DATA_KEYS without its own entry.
            _die(f"--data may not contain reserved keys: {sorted(reserved)}; "
                 + "; ".join(
                     f"{k} -> {RESERVED_DATA_KEY_REDIRECT.get(k, 'envelope-owned — move the value under a non-reserved key')}"
                     for k in sorted(reserved)))
        data.update(parsed)

    # T-11417: the CALLER-SUPPLIED payload, snapshotted BEFORE any verb stamp reaches `data`. The
    # content-free judgement below must read exactly this and nothing else — every later stamp
    # (`--commit`, `--stage`, the derived `wait_reason`/`realm`/`disposition`, the unconditional
    # `actor`) is the VERB's own bookkeeping, so counting any of them would make a payload-free
    # capture look populated. The first cut excluded `actor` BY NAME and audit-post caught the
    # obvious sequel: `--stage Tests --data ''` slipped past a blocklist that named one key. A
    # snapshot cannot be outgrown the way a blocklist is — a stamp added later is excluded by
    # construction, with no second site to remember.
    caller_data = dict(data)

    # T-12801 (X-1465 / X-1519): the NAMED MID-TURN delegated route (SPEC-0204 rule 2). A mid-turn
    # owner decision reaches no parser-born owner row on a consumer whose transcript parser/hook-tail
    # yields none, so no delegation chain can ground it. The route admits the delegated row on its
    # OWN proof instead — and the proof is taken HERE, at the write, never trusted from the payload.
    if event_type == "owner_directive":
        if "owner_text_verified" in caller_data:
            _die("--data may not contain `owner_text_verified`: it is stamped by this verb only after "
                 "it proves `owner_text` against the anchored transcript entry (T-12801). Nothing was appended.")
        if caller_data.get("mid_turn") is not None:
            _proof = dict(caller_data)
            _mid_turn_refusal = _mid_turn_owner_text_refusal(
                _proof, source_ref, _classify_cc_entry=_classify_cc_entry, _extract_text=_extract_text)
            if _mid_turn_refusal:
                _die(f"mid-turn owner_directive refused: {_mid_turn_refusal}. Nothing was appended.\n"
                     "  the route (SPEC-0204 rule 2): --source-ref <transcript>#uuid:<owner entry uuid> "
                     "--data '{\"captured_via\": \"controller-delegated\", \"mid_turn\": true, "
                     "\"cards\": [\"T-XXXX\"], ...}'  (owner_text omitted = taken from the entry; "
                     "if supplied it must be the owner's COMPLETE message, verbatim)")
            data["owner_text"] = _proof["owner_text"]
            data["owner_text_verified"] = True

    if args.commit and event_type == "live_trigger_evidence":
        # T-12592 — `--commit` IS live_trigger_evidence's custody writer (it has no dedicated emitter):
        # record it through the one custody-sha helper, and refuse BEFORE append a value that is no
        # commit of this repo or is ambiguous. Every other event type keeps the verbatim stamp below.
        _ltc = args.commit.strip()
        _ltc_full = _git_resolve_sha(f"{_ltc}^{{commit}}")
        if _ltc_full is None:
            _die(audit.unresolved_ref_refusal(
                "--commit", _ltc, repo_root=REPO_ROOT,
                plain=f"--commit {_ltc!r} is no commit of this repo")
                 + " A live_trigger_evidence row must name a commit it can be read back from. "
                   "Nothing was appended.")
        data["commit"] = audit.recorded_sha(_ltc_full, repo_root=REPO_ROOT)
    elif args.commit:
        data["commit"] = args.commit
    if args.stage is not None:
        data["stage"] = args.stage

    # T-11415 (X-1057, SPEC-0152 rule 24): the DECLARED-CLASS chokepoint for `test_class_executed`.
    # A row naming a class the project never declared is a COMPLETE record — it is written, it reads as
    # coverage, and it matches no declared class, so it clears nothing and appears on no surface (the
    # near-miss report is scoped to declared names). <project> emitted two such rows naming verify LAYER
    # ids; nothing complained and the debt fold reported the same unproven count the next morning.
    # Checked HERE, at the write, in the same fail-closed family as the realm/disposition vocabulary
    # checks above and inside the same pre-append block — a refusal must leave the journal untouched.
    # The remedy TEXT is the fix, not the refusal: it names every legal value and, for a value that is a
    # declared LAYER id, the classes that layer carries (X-1057 asked for a fix that fails by IMPROVING
    # the artifact — a bare refusal was named the weaker one). Contract + the whole abstain set (no
    # carrier / waived / nothing declared / unparseable ⇒ "" and the emit proceeds) live single-SoT in
    # `debt.undeclared_class_remedy`; this call site stays plumbing (SPEC-0007 §3).
    if event_type == debt_mod.EXECUTION_EVENT:
        _remedy = debt_mod.undeclared_class_remedy(REPO_ROOT / "yitc-ops.yaml", data.get("class"))
        if _remedy:
            _die(f"{debt_mod.EXECUTION_EVENT}: {_remedy}")

    # T-12620 (X-1419 / X-1422, SPEC-0161): the SANDBOX-LIFECYCLE payload chokepoint — the WRITE side of
    # a validator that, until now, existed only on the READ side. `validate_sandbox_lifecycle_payload`
    # had exactly ONE caller, inside the audit-packet evidence fold, so a malformed row APPENDED,
    # exited 0, and was first heard from as an evidence section that silently EXCLUDED it. <project>
    # measured it by accident: a probe run EXPECTING a refusal
    # (`--data '{"ok":"yes","producer":"..."}'` — `ok` a string where a real bool is required, and both
    # `compose_project` and `evidence_ref` absent) was ACCEPTED, and the junk row is permanent
    # (<project>/events.jsonl#ts=2026-09-14T19:52:59Z). The consumer's workaround was to prove every
    # payload through the validator DIRECTLY rather than through this verb's exit code (X-1422) — a
    # workaround is the tell that the verb was not load-bearing.
    #
    # FOURTH measured instance of one named family — fail-open-at-WRITE / fail-closed-at-READ — after
    # X-1371, X-1380 and X-1388 (all three on `audit decide`). The remedy is the family's standing one:
    # consult the SAME validator at the write, where the bad row can still be stopped from existing.
    #
    # FAIL-CLOSED, unlike the WARN-and-record posture of the `deviation_captured` surfaces below, and
    # the split is the one the siblings already draw. Those are a TRIAGE REFLEX where a lost capture is
    # strictly worse than a thin one (D-0035/D-0086). A sandbox-lifecycle row is the opposite: it is
    # EVIDENCE an audit packet reads, it is emitted by an INSTRUMENT (a script, re-runnable at zero
    # cost, not a human mid-flight), and a malformed one is both unusable and — the journal being
    # append-only — unremovable. So it joins the fail-closed family it sits in: the realm/disposition
    # vocabulary checks, the obligation `judgement` gate and the abbreviated-revision near-miss.
    #
    # NO TYPE TEST OF OUR OWN: the validator's own first line returns [] for every non-sandbox event
    # type, so the scoping IS the validator's and the type list has no second home to drift from
    # (CHARTER §P5). Judged on `data` like every sibling here; the verb's own stamps (`--commit`,
    # `--stage`, `actor`) cannot collide with the four required keys. Placed inside the pre-append
    # block — so a refusal leaves the append-only journal byte-identical — and ABOVE the `--check`
    # early return, so a no-write validation run exercises this identical gate.
    #
    # The REMEDY is the fix, not the refusal (the house style of every message in this block): the
    # problem list the validator already returns is printed verbatim, so the emitter is told exactly
    # which keys are missing or ill-typed and re-runs corrected.
    _sandbox_problems = validate_sandbox_lifecycle_payload(event_type, data)
    if _sandbox_problems:
        _die(f"{event_type}: malformed sandbox-lifecycle payload — "
             f"{', '.join(_sandbox_problems)}. This event type is EVIDENCE an audit packet folds "
             f"(SPEC-0161), and the journal is append-only, so a row written now could not be "
             f"corrected later: it would append, exit 0, and then be silently EXCLUDED from the "
             f"evidence section that was supposed to read it (X-1419 / X-1422). Required keys: "
             f"{', '.join(SANDBOX_LIFECYCLE_PAYLOAD_KEYS)} — `ok` must be a real JSON bool (`true` / "
             f"`false`, never the STRING \"true\"), and the other three must be non-empty strings; "
             f"`evidence_ref` must name where the proof actually lives (a name alone only renames "
             f"the gap). Extra keys are fine — the row is open. e.g. --data "
             f"'{{\"ok\":true,\"producer\":\"bin/spike-cage-check.sh\","
             f"\"compose_project\":\"<project>\",\"evidence_ref\":\"<path-or-locator>\"}}'. "
             f"Nothing was appended.")

    # T-12648 (X-1456, SPEC-0156 §2): the ADMISSION-DEMONSTRATION payload chokepoint — the same
    # fail-open-at-WRITE / fail-closed-at-READ defect as the sandbox block directly above, on the event
    # that clears SPEC-0156 debt. SPEC-0156 §2 enumerates five fields the debt-clearing fold needs
    # (`check`, `declaration`, `broken_input`, `outcome` — "red", compared after stripping surrounding
    # whitespace and lowercasing, the fold's own rule (T-12656) — and `definition_identity`),
    # and `debt._admission_demonstrations` silently DROPS any row missing one. Nothing checked them at
    # the write. <project> measured it on itself twice inside two minutes (X-1456): a first row carrying
    # check + definition only, a second adding definition_identity but still no declaration, no
    # broken_input and no outcome — BOTH accepted at exit 0, BOTH now permanent rows in an append-only
    # journal, neither clearing anything. FIFTH measured instance of the named family (X-1371, X-1380,
    # X-1388, X-1419).
    #
    # WHY THIS ONE IS WORSE THAN A DROPPED ROW, and why the existing read-side feedback was not enough:
    # the debt line the row failed to clear keeps reading UNPROVEN and keeps quoting the OLD recorded
    # identity — which reads as THE DEMONSTRATION HAVING FAILED, not as the payload having been ignored.
    # That is precisely the rewire-vs-wrong-key confusion SPEC-0156 §2 warns about in its own paragraph,
    # and it sends the next author to break their subject and re-demonstrate work that was never the
    # problem. The T-11178 near-miss clause does say N rows were SEEN and did not count — but it is
    # READ-side and fires only where an unproven line already prints; the WRITE is what was silent.
    #
    # SPEC-0156 §3 IS NOT WEAKENED — the distinction is between a DECLARATION and an EVIDENCE ROW. §3
    # says an absent demonstration never refuses a DECLARATION: the check is admitted UNPROVEN and
    # surfaces report-only, and that is untouched here. This refuses a MALFORMED EVIDENCE ROW. Nothing
    # about which checks are declared, which are unproven, or what the debt line says changes; a refused
    # emit leaves the project in the exact state it was already in, with the check still visible as
    # owed, and the operator re-emits corrected. No new gate class — one new member of the pre-append
    # fail-closed family already in this verb.
    #
    # NO TYPE TEST OF OUR OWN, and no second copy of the contract: `validate_admission_payload` returns
    # [] for every other event type, and it is the SAME function `_admission_demonstrations` applies to
    # decide whether a row COUNTS (T-12648 rewired the fold onto it). So the write admits exactly what
    # the read admits BY CONSTRUCTION — not by two lists kept in agreement by hand (CHARTER §P5).
    # Placed inside the pre-append block so a refusal leaves the append-only journal byte-identical, and
    # ABOVE the `--check` early return so a no-write validation run exercises this identical gate.
    #
    # The REMEDY is the fix, not the refusal (the house style of this block): the problem list is
    # printed verbatim, the five required keys are named (free — SPEC-0156 §2 enumerates them), the
    # one-legal-outcome rule is STATED rather than left to be inferred from a bare miss, and a
    # copy-pasteable --data example follows.
    _admission_problems = debt_mod.validate_admission_payload(event_type, data)
    if _admission_problems:
        _die(f"{event_type}: malformed admission-demonstration payload — "
             f"{', '.join(_admission_problems)}. This row exists to CLEAR a SPEC-0156 debt line, and "
             f"the fold that reads it requires every field of the §2 contract: "
             f"{', '.join(debt_mod.ADMISSION_PAYLOAD_KEYS)} — the four besides `outcome` must be "
             f"non-empty strings, and `outcome` must be "
             f"\"{debt_mod.ADMISSION_RED_OUTCOME}\" — compared after stripping surrounding whitespace "
             f"and lowercasing, the fold's own rule, so \" RED \" clears too (a demonstration exists "
             f"to show the check FAILING against a named broken input, so a green — or any other "
             f"value — clears nothing). The "
             f"journal is append-only, so a row written now could not be corrected later: it would "
             f"append, exit 0, clear nothing, and leave the debt line still quoting the OLD identity — "
             f"which reads as the DEMONSTRATION having failed rather than as this payload having been "
             f"ignored (X-1456, measured twice). e.g. --data "
             f"'{{\"check\":\"<surface>[<id>]\",\"declaration\":\"<carrier-locator>\","
             f"\"broken_input\":\"<what you deliberately broke>\","
             f"\"outcome\":\"{debt_mod.ADMISSION_RED_OUTCOME}\","
             f"\"definition_identity\":\"<the identity `bin/yitc-v2 debt` prints beside the check>\"}}'. "
             f"Nothing was appended.")

    # T-12866 (SPEC-0015, T-10282/T-10486): the P8 ADOPTION-EVIDENCE payload chokepoint — sixth member
    # of the fail-open-at-WRITE / fail-closed-at-READ family above. `_p8_evidence_is_substantive` has
    # demanded `failing_input` + `evidence_events` since T-10282, but only at READ time, so a row keyed
    # `differential_failing_input` (the recurring self-chosen spelling — 8 captures since 2026-07-11
    # despite the T-10486 cue; T-12589/T-12724/T-12792/T-12805) appended at exit 0 and silently did not
    # count. Same helper the reader uses, so the write admits exactly the read's key shape. KEY SHAPE
    # ONLY: ref resolution stays read-side (a ref may resolve only at close, SPEC-0168). The close-time
    # E-0005 WARN is untouched — rows written before this gate, or by hand, still meet it.
    if event_type in P8_EVIDENCE_TYPES:
        from lib import task_closure_evidence as _tce
        _p8_missing = _tce.p8_payload_missing_keys(data)
        if _p8_missing:
            _wrong = [k for k in ("differential_failing_input", "differential") if k in data]
            _hint = (f" You supplied {', '.join('`'+k+'`' for k in _wrong)} — the contract does not read "
                     f"that key: move the named differential into `failing_input`." if _wrong else "")
            _die(f"{event_type}: P8 adoption payload is missing "
                 f"{' and '.join('`'+k+'`' for k in _p8_missing)}. The contract (SPEC-0015, T-10282) "
                 f"requires BOTH `failing_input` (non-empty string: the input that must make the "
                 f"criterion FAIL) and `evidence_events` (non-empty list of refs to real machine "
                 f"events, e.g. `<event_type>@<iso-ts>`); a row without them appends, exits 0, and "
                 f"then silently does NOT count at `task close`.{_hint} e.g. --data "
                 f"'{{\"failing_input\":\"<what, if broken, makes this fail>\","
                 f"\"evidence_events\":[\"<event_type>@<iso-ts>\"]}}'. Nothing was appended.")

    # T-10121 (SPEC-0135 §5, SPEC-0025 §wait_reason): the BLOCK-side chokepoint. bg_dispatch_halted is
    # HAND-emitted by dispatched workers via this generic verb (there is no dedicated code emit), and a
    # pause may also be hand-emitted here. When such an event carries a free `reason` but no explicit
    # `wait_reason`, derive the normalized reason so the block/pause wait is categorizable — ALONGSIDE
    # the free `reason` detail (additive, P5-safe). A caller-supplied wait_reason is left untouched.
    # T-12844 — `block_classified` is RETIRED: the classification rides the halt row itself
    # (`bg_dispatch_halted.block_classification`, stamped at the `_append_event` chokepoint).
    if event_type == RETIRED_BLOCK_CLASSIFIED_TYPE:
        _die("event block_classified: RETIRED (T-12844, SPEC-0161) — it never had an emitter and a "
             "hand-appended row is read by nothing that decides. The SPEC-0191 classification rides "
             "the halt row: `yitc-v2 blocked-on-land <task> --rung 1|2|3 <reason>` (or "
             "--unclassified). Nothing was appended.")
    if event_type in ("bg_dispatch_halted", "task_paused") and "wait_reason" not in data:
        _wr = observe.normalize_wait_reason(data.get("reason"))
        if _wr:
            data["wait_reason"] = _wr

    # T-10248 (X-0253, SPEC-0085 §3): the deviation `realm` is the ENUMERATED routable half of the old
    # free-text `relates_to` carrier, so its vocabulary is checked HERE, at the write. Fail-CLOSED: a
    # typo'd realm that appended silently would simply never route — reproducing the very silent loss
    # this field exists to close. Nothing is lost by refusing: the capture reflex is one command, and
    # the legal set is printed, so it is re-issued immediately. Unset stays legal (the realm is
    # optional; the legacy exact `relates_to: kernel` marker still resolves — cross.deviation_realm).
    if event_type == "deviation_captured" and data.get(cross.DEVIATION_REALM_KEY) is not None:
        _realm = str(data[cross.DEVIATION_REALM_KEY]).strip()
        if _realm not in PLACEMENT_REALMS:
            _die(f"deviation_captured: invalid {cross.DEVIATION_REALM_KEY!r} {_realm!r} — choose one of "
                 f"{' | '.join(PLACEMENT_REALMS)} (the SPEC-0073 placement realms). The free-text aspect "
                 f"belongs in `relates_to`, not here; only `{cross.DEVIATION_REALM_KERNEL}` auto-routes.")
        data[cross.DEVIATION_REALM_KEY] = _realm
    # T-12488 (SPEC-0025 §deviation_captured): the optional failure `class` is checked in the same
    # fail-closed family as the realm — ids only, stored as the int; absent stays legal.
    if event_type == "deviation_captured" and data.get("class") is not None:
        _cls, _cls_err = events.normalize_failure_class(data["class"])
        if _cls_err:
            _die(f"deviation_captured: {_cls_err}")
        data["class"] = _cls

    # T-10453 (X-0317): a `deviation_resolved` event is the GOVERNED stale-dismiss silencer for a
    # verified-stale kernel near-miss WARN row (the land near-miss fold joins on `fingerprint`).
    # Fail-CLOSED at the write on ALL THREE governed fields — `fingerprint` (the join key; without it the
    # event silences NOTHING), `resolved_by` (who/what resolved it) and `evidence` (the durable proof the
    # row is genuinely stale). A silencer that permanently mutes a WARN MUST carry its audit trail: a bare
    # "shut up" with no evidence is exactly the un-accountable dismissal this governed marker exists to
    # avoid. Mirrors the fail-closed realm check above.
    #
    # T-10752 (X-0599): `disposition` joins that trail as its THIRD leg — WHICH of the three
    # legitimate travel paths applied (cross.DEVIATION_DISPOSITIONS). A bare "resolved" says the row
    # was muted but not why it was safe to mute, so nobody can later separate "we filed it
    # elsewhere" from "we judged it not ours" — the accountability gap X-0599 measured (5 rows
    # dispositioned by hand, 5 with nowhere to record the conclusion). Vocabulary CLOSED and checked
    # here at the write, mirroring the `deviation_captured` realm check above: a typo'd disposition
    # that appended silently would record an un-auditable dismissal, which is the very defect.
    # WRITE-side only — `cross.resolved_deviation_fps` still silences on `fingerprint` alone, so the
    # already-landed resolving events keep silencing (no reader migration, no regression).
    if event_type == "deviation_resolved":
        _missing = [k for k in ("fingerprint", "resolved_by", "evidence", "disposition")
                    if not str(data.get(k, "")).strip()]
        if _missing:
            _die(f"deviation_resolved: requires non-empty {', '.join('`'+k+'`' for k in _missing)} in "
                 "--data — the governed stale-dismiss silencer must carry its audit trail (fingerprint = "
                 "the join key the near-miss fold silences on; resolved_by + evidence = the durable proof "
                 "the row is stale; disposition = WHICH legitimate path the signal already took, one of "
                 f"{' | '.join(cross.DEVIATION_DISPOSITIONS)}). e.g. --data "
                 "'{\"fingerprint\":\"<fp>\",\"resolved_by\":\"<who/what>\",\"evidence\":\"<ref>\","
                 "\"disposition\":\"already-fixed\"}'")
        _disp = str(data["disposition"]).strip()
        if _disp not in cross.DEVIATION_DISPOSITIONS:
            _die(f"deviation_resolved: invalid `disposition` {_disp!r} — choose one of "
                 f"{' | '.join(cross.DEVIATION_DISPOSITIONS)}. routed-by-hand = the content reached "
                 "the kernel by another route (hand-filed as a cross item); not-kernel = run to "
                 "ground and genuinely project-realm; already-fixed = the kernel problem is already "
                 "shipped. The free-text WHY belongs in `evidence`, not here — a free-text "
                 "disposition cannot be audited later (X-0599).")
        data["disposition"] = _disp
        # T-13189: the SENT mark must name WHERE it was sent — a `submitted-upstream` with no locator
        # would silence the intake notice while leaving nobody able to find the upstream report.
        if _disp == "submitted-upstream" and not str(data.get("locator", "")).strip():
            _die("deviation_resolved: disposition `submitted-upstream` requires a non-empty `locator` in "
                 "--data — the upstream issue URL or id the capture was sent to. e.g. "
                 "`bin/yitc-v2 event deviation_resolved --data '{\"fingerprint\":\"<fp>\","
                 "\"disposition\":\"submitted-upstream\",\"locator\":\"<issue url>\","
                 "\"resolved_by\":\"<who>\",\"evidence\":\"<issue url>\"}'`")

    # T-11169 (SPEC-0149 §1, <project> X-0923): the HONEST-MISS discharge of an expired post-deploy
    # proof obligation, gated fail-closed at the write for exactly the reason the `deviation_resolved`
    # trail above is. Rule 1 used to define ONE exit — a matching later recheck — so an obligation whose
    # window had already passed could only be silenced by emitting that recheck LATE, recording a proof
    # nobody performed. This event is the honest alternative, and its `judgement` is what keeps it from
    # decaying into a "remove the line" button (the owner's refinement (a), 2026-08-16): the operator
    # must SAY why a late re-check is or is not meaningful here — the revision was superseded six deploys
    # ago, the observation moment has passed, or conversely it IS still worth running, in which case run
    # it and record the real recheck instead. `project` + `revision` are the discharge key
    # (`debt._obligation_key`); without them the row silences nothing, so it is refused rather than
    # appended as a no-op nobody would ever notice. The fold's own admission gates are separate and
    # stricter (the window must ALREADY have expired) and live in `debt.open_proof_obligations` — this
    # is the write floor, not the whole rule. No new verb, no new store: SPEC-0149 §2 holds.
    if event_type == debt_mod.OBLIGATION_MISS_EVENT:
        _missing = [k for k in ("project", "revision", debt_mod.OBLIGATION_MISS_JUDGEMENT_KEY)
                    if not str(data.get(k, "")).strip()]
        if _missing:
            _die(f"{debt_mod.OBLIGATION_MISS_EVENT}: requires non-empty "
                 f"{', '.join('`'+k+'`' for k in _missing)} in --data — this discharge closes an EXPIRED "
                 "proof obligation by recording the miss honestly, so it must say WHOSE (project + "
                 "revision = the discharge key) and, above all, `judgement`: why a late re-check is or "
                 "is not meaningful here. A bare flag would be a 'remove the line' button; the judgement "
                 "is the record that makes it a decision. e.g. --data '{\"project\":\"<project>\","
                 "\"revision\":\"<sha>\",\"judgement\":\"revision superseded by 6 later deploys; a 24h "
                 "write-path re-check run on day 6 would not be the observation the window meant\"}'. "
                 "If the re-check IS still worth running, run it and record `deploy_recheck_completed` "
                 "instead — this event never asserts a proof was performed.")

    # T-11224 (SPEC-0149 §1, <project> X-0963): the SHORT-SHA near-miss, refused at the WRITE. Both
    # discharges above key on `(project, revision)` EXACTLY, so a row carrying `git rev-parse --short`
    # output — a 7-char prefix of the sha the obligation was stamped against — matched nothing,
    # discharged nothing, and produced NO signal at all: silence indistinguishable from success, the
    # loud-failure class (SPEC-0165). The cost is measured: seven <project> governance events had to be
    # re-authored and re-emitted, and the journal is append-only, so the seven superseded rows are
    # permanent. That is why this is caught HERE and not reported by the fold afterwards — the write is
    # the only place the bad row can still be stopped from existing, and it is the only entry path for
    # these rows (SPEC-0149 §2 admits no dedicated verb or emitter — they ride this verb).
    #
    # REFUSE, never silently normalize: rewriting an operator-supplied governance key would make the
    # append-only journal say something the operator did not write, and an abbreviation only grows more
    # ambiguous against a longer history. The refusal NAMES the full form instead, and the operator
    # re-emits it deliberately — the same posture as the `judgement` gate above.
    #
    # It fires ONLY on a demonstrated near-miss (`debt.revision_key_near_miss`): a strict prefix of a
    # revision THIS project actually deployed. A full-sha row, a project with no matching deploy, and a
    # project using non-sha revision keys are all untouched — a fix that starts warning on healthy rows
    # would re-create the alarm erosion it exists to reduce. Placed BEFORE `_append_event`, so a refusal
    # leaves the append-only journal byte-identical.
    if event_type in (debt_mod.OBLIGATION_CLOSING_EVENT, debt_mod.OBLIGATION_MISS_EVENT):
        _near = debt_mod.revision_key_near_miss(EVENTS_PATH, data.get("project"), data.get("revision"))
        if _near:
            _full = ", ".join(_near["candidates"])
            _die(f"{event_type}: `revision` {_near['supplied']!r} is an ABBREVIATED form of a revision "
                 f"{_near['project']} actually deployed — {_full}. The discharge key is "
                 f"`(project, revision)` matched EXACTLY (SPEC-0149 §1), so this row would append, "
                 f"discharge NOTHING, and say nothing — you would read silence as nothing-to-do. "
                 f"Re-emit it with the FULL revision as deployed (the value stamped into the "
                 f"`deploy_completed` event, e.g. `--data '{{\"project\":\"{_near['project']}\","
                 f"\"revision\":\"{_near['candidates'][0]}\"}}'`). Nothing was appended.")

    # T-10410 (SPEC-0025 §deviation_captured): WHO captured this. The capture reflex is the ONE
    # nonconformity sink every session hand-emits into, so its record now names its capturer — the SAME
    # `resolve_actor` seam T-10405 stamped at `task file` / `followup add` / `cross request`, reaching
    # its last emit site. DERIVED from the launch context, never asked for (attribution costs the human
    # ZERO added input) and never caller-asserted (`actor` is a RESERVED data key above). Stamped
    # UNCONDITIONALLY: the derive is the only writer, so a capture cannot carry a forged author.
    # NOT a gate — `resolve_actor` degrades to the DEFAULT_ACTOR on an unknown user / empty identity /
    # unreadable registry, so attribution can never block a capture (capture is a reflex, D-0035/D-0086).
    if event_type == "deviation_captured":
        data["actor"] = _actor()

    # T-10665 (T-10642 leg (b), SPEC-0056 §1/§2): a deviation_captured with NO `fingerprint` cannot be
    # recurrence-matched or root-clustered — the recurrence/reopen analysis (§1) and the root-clustering
    # rollup (§2) both KEY on the fingerprint, so a fingerprint-less capture silently drops out of triage
    # (45 such lines had already accreted in the journal). REPORT-ONLY, never a gate: the fingerprint stays
    # OPTIONAL (SPEC-0025 §deviation_captured) and capture is a one-command reflex (D-0035/D-0086), so this
    # WARNs to stderr and the capture still appends below. Mirrors the report-not-block posture of the other
    # deviation surfaces here (unlike the fail-CLOSED deviation_resolved silencer, which MUST carry its fp).
    # T-11417 (X-1071's general claim, SPEC-0165): a TRIAGE-CLASS event carrying NO content is the
    # loud-failure class — it appends, returns 0, and says nothing, so the author reads success while
    # the fold gains a row nobody can act on. WARNED, NOT REFUSED: capture is a one-command reflex
    # (D-0035/D-0086) and gating it would trade a useless row for a LOST one, which is strictly worse.
    # That is the opposite posture from `cross request` (cross.py), which REFUSES a content-free brief
    # — there the artifact is permanent and addressed to somebody else, and the author is present to
    # re-issue. Same defect class, two artifacts, two correct answers.
    # Judged on the CALLER-SUPPLIED payload only (`caller_data`, snapshotted at parse time above):
    # every key this verb stamps itself — `actor`, `--commit`, `--stage`, the derived `wait_reason` /
    # realm / `disposition` — is the verb's bookkeeping, not triageable content, so counting any of
    # them would make an empty capture look populated. Placed BEFORE the `fingerprint` WARN below and
    # SUBSUMING it (an empty payload has no fingerprint either), so one cause produces one message.
    # T-11775 (X-1120's second observation, three measured instances): the SAME defect one notch
    # narrower — a payload that is not EMPTY but still carries no subject, because the only prose in
    # it is a severity word. `{fingerprint: <fp>, impact: "medium"}` has two non-blank values, so the
    # emptiness test above cannot see it, and the three items that arrived that way each cost a
    # reader a trip into the peer journal and then into kernel source to reconstruct the meaning.
    # Deliberately NARROW, and the narrowness is the design: a fingerprint ALONE stays acceptable
    # (the card's line — that session acted on three fingerprint-only captures), so this fires only
    # on an `impact` the author DID reach for. Classification is single-SoT in
    # `journal.untriageable_impact`; this stays a plumbing call site (SPEC-0007 §3). Same
    # REPORT-ONLY posture as everything in this block — the row still appends below, unconditionally.
    # T-13119 (SPEC-0057 §6): `inspect record` is the governed emitter of `inspection_completed` and
    # always writes a non-empty `criteria_ref` plus a `theme` or `tier` — the run schema the readers key
    # on (views._view_review_due groups by tier/theme). A hand-emitted row without them appends fine and
    # then reads as an inspection run that no fold can place (<project> T-0086, measured 2026-09-27).
    # REPORT-ONLY, never a refusal: schema-carrying hand rows stay silent, and the row appends below.
    if event_type == "inspection_completed" and not (
            str(caller_data.get("criteria_ref") or "").strip()
            and any(str(caller_data.get(k) or "").strip() for k in ("theme", "tier"))):
        print("yitc-v2: WARN inspection_completed lacks the run schema its readers key on — a "
              "non-empty `criteria_ref` plus a `theme` or `tier`. The row still appends, but the "
              "review-due fold cannot place it. The governed route is `yitc-v2 inspect record "
              "--theme|--tier ... [--task T-NNNN]`, which writes that schema itself (SPEC-0057 §6).",
              file=sys.stderr)
    _payload_empty = (event_type in TRIAGE_CONTENT_EVENT_TYPES
                      and not any(str(v).strip() for v in caller_data.values() if v is not None))
    _severity_only = (event_type in TRIAGE_CONTENT_EVENT_TYPES
                      and not _payload_empty
                      and journal.untriageable_impact(caller_data))
    # The fingerprint WARN below is bounded against the EMPTY case only (a payload with no key at
    # all), which is what `_content_free` has always meant there; a severity-only payload names its
    # own fingerprint and must not change that bound.
    _content_free = _payload_empty
    if _severity_only:
        print(f"yitc-v2: WARN {event_type} carries NO triageable SUBJECT — its `impact` is "
              f"{str(caller_data.get('impact') or '').strip()!r}, which is a SEVERITY word (or "
              f"blank), not a description of what happened. It reads as content and is not: a later "
              f"reader gets a rating with nothing rated, and must leave this row, open the origin "
              f"journal and read source to reconstruct what you meant (three inbound items cost "
              f"exactly that, and all three were real defects — X-1120 / T-11775). THE LINE: a "
              f"descriptive `fingerprint` ALONE is fine and is NOT warned — nothing here asks for "
              f"more prose in general. What is not fine is reaching for `impact` and putting a "
              f"severity word in it. Re-emit with what the severity is ABOUT: what breaks, where, "
              f"and what it costs (e.g. \"impact\": \"land admits product source with no carrier — "
              f"fails OPEN\"). The row IS recorded (capture is a reflex, never gated — "
              f"D-0035/D-0086).",
              file=sys.stderr)
    # T-11880: this WARN owns the empty-payload cause end to end, so it also STATES the derivation
    # rather than letting a second line below repeat the same cause (the subsumption discipline this
    # WARN already applies to T-10665's fingerprint WARN). A `deviation_captured` here has no
    # fingerprint because it has nothing at all — one was derived from the row's ENVELOPE, which
    # makes the row addressable without pretending it is informative.
    _content_free_derived_tail = (
        " and, since T-11880, it is still ROUTABLE — a fingerprint was DERIVED from the row's own "
        "envelope, so it can be cited, routed and promoted even though it says nothing. Routable is "
        "not the same as useful: re-emit with content."
        if event_type == "deviation_captured" else ".")
    if _content_free:
        print(f"yitc-v2: WARN {event_type} carries NO triageable content — its `--data` payload is "
              f"empty, so the row records only that something happened, to nobody's benefit: it "
              f"cannot be recurrence-matched, root-clustered or acted on, and in the fold it is "
              f"indistinguishable from noise. A common cause is a payload that never arrived — an "
              f"unquoted `--data \"$(cat …)\"` whose command substitution produced nothing, or a "
              f"redirect from a fixed /tmp path (use `mktemp` per invocation). Re-emit with what a "
              f"later reader needs: what happened, where, what it cost, and a stable `fingerprint`. "
              f"The row IS recorded (capture is a reflex, never gated — D-0035/D-0086)"
              f"{_content_free_derived_tail}",
              file=sys.stderr)

    # T-11890 — THE WRITE SIDE: normalize alias content INTO `impact`, so new rows stop adding to the
    # scatter the reader-owned accessor exists to absorb. The accessor (`journal.capture_content`)
    # already makes every historical row readable — the journal is append-only, so those keys are
    # permanent — but leaving the write side alone would mean the alias set keeps growing forever.
    #
    # REPAIR, NOT REJECTION, and that is the load-bearing choice (external consult 2026-08-30,
    # finding 3): a strict write-time schema would suppress capture VOLUME, which is the behaviour the
    # system most wants to keep. Capture is a one-command reflex and is NEVER gated (D-0035/D-0086) —
    # so this adds no refusal, in the same posture as every WARN above. The card's scope prose asks for
    # a refusal "when there is no content at all"; that is declined deliberately and the dissonance is
    # captured (fp card-scope-asks-capture-refusal-while-handbook-forbids-gating-the-reflex): a
    # fingerprint-only capture is acceptable BY DESIGN (`journal.untriageable_impact`), and exactly ONE
    # row in the 5967-row history carries neither content nor fingerprint, so the refusal would gate
    # the reflex to buy nothing.
    #
    # NON-DESTRUCTIVE by construction: the alias key is LEFT IN PLACE (the row keeps saying what its
    # author wrote), and a severity-only `impact` is NOT overwritten — it keeps its severity meaning
    # and still earns the T-11775 WARN above. So this fires only where `impact` is absent or blank,
    # which is the 276-of-431 measured case where the prose lives under another key.
    if event_type in TRIAGE_CONTENT_EVENT_TYPES and not str(data.get("impact") or "").strip():
        _alias_content = journal.capture_content(caller_data)
        if _alias_content:
            _alias_key = next((k for k in journal.CAPTURE_CONTENT_KEYS
                               if k != "impact" and str(caller_data.get(k) or "").strip() == _alias_content),
                              None)
            data["impact"] = _alias_content
            print(f"yitc-v2: NOTE {event_type} carried its content under `{_alias_key}`, not `impact` — "
                  f"normalized into `impact` so later readers find it where the canonical key is. Your "
                  f"`{_alias_key}` is untouched and the row is recorded unchanged otherwise; nothing is "
                  f"refused (capture is a reflex — D-0035/D-0086). Every reader goes through "
                  f"`journal.capture_content`, so a capture under any measured alias was already "
                  f"readable — this just stops the scatter growing (T-11890).",
                  file=sys.stderr)

    # T-11880: DERIVE the missing recurrence key — the disposition that REPLACES T-10665's
    # report-only WARN. That WARN named the loss accurately and then landed the unroutable row
    # anyway, which is the silent accept this change removes: 92 rows in the 2026-08-30 triage
    # window carried no fingerprint, every one emitted through this sanctioned path, and every one
    # unroutable because each routing carrier triage owns — a task `cites:`, a cross `origin_fp`, an
    # E-XXXX file — is keyed BY fingerprint. Nothing is deleted by that loss and `journal query
    # --grep` still finds those rows; what evaporates is their ROUTING, silently, the moment the
    # watermark passes them.
    #
    # DERIVE, NOT REFUSE, and the choice is this block's own standing posture rather than a new one:
    # capture is a one-command REFLEX (D-0035/D-0086), so gating it trades a useless row for a LOST
    # one, "which is strictly worse" (T-11417, three inches up; T-10410's actor stamp degrades rather
    # than blocks for the same reason). A refusal here would meet an author mid-flight in other work
    # who reached for the reflex precisely because it costs one command. So the row still appends,
    # unconditionally, and it now appends ROUTABLE. `fingerprint_derived` marks it, because a reader
    # must be able to tell a key the author CHOSE from one this verb COMPUTED — the derived key is a
    # real recurrence key, not an authored description, and a triage reader weighing a promotion
    # should see which it is. The derivation itself is single-SoT in `journal.derived_fingerprint`
    # (pure + total by construction — a derivation that could raise would re-gate the reflex through
    # the back door); this stays a plumbing call site (SPEC-0007 §3).
    #
    # An AUTHORED fingerprint is passed through untouched — the condition is the same
    # blank/null/absent test the WARN used, so a caller who supplied one is bit-for-bit unaffected.
    # Placed BEFORE the `--check` early return, so a validation run exercises the identical path.
    # ONE timestamp, used for BOTH the derivation and the appended row (audit-post YELLOW, absorbed
    # mode-a). The envelope arm derives from `ts + task_id + actor`, so the row's stored `ts` must be
    # the SAME value the key was derived from, or the documented contract — "derived from the row's
    # own envelope" — would be a claim nobody could verify from the row: two `_utc_now_iso()` calls
    # straddling a second boundary would silently produce a key derived from a timestamp the row does
    # not carry. Resolved here and threaded into `_append_event`'s explicit `ts` parameter, so the
    # relationship is guaranteed by construction rather than by the two calls happening to be fast.
    _event_ts = _utc_now_iso()
    _derive_note_due = False
    if event_type == "deviation_captured" and not str(data.get("fingerprint") or "").strip():
        _derived = journal.derived_fingerprint(caller_data, ts=_event_ts,
                                               task_id=args.task, actor=data.get("actor"))
        data["fingerprint"] = _derived
        data["fingerprint_derived"] = True
        # ONE CAUSE, ONE MESSAGE — the discipline the content-free WARN above already established
        # when it subsumed T-10665's fingerprint WARN. An empty payload has no fingerprint BECAUSE it
        # has nothing at all, so that WARN is the whole story and states the derivation in its own
        # tail; a second line here would report the same cause twice. The derivation itself is
        # UNCONDITIONAL — it already ran, above this line — so the quiet row is routable either way.
        _derive_note_due = not _content_free
    if _derive_note_due:
        print(f"yitc-v2: NOTE deviation_captured carried no `fingerprint`, so one was DERIVED from "
              f"the payload: {_derived!r} (marked `fingerprint_derived: true`). The capture is "
              f"recorded and is ROUTABLE — a fingerprint-less row could never be routed at all, "
              f"because every carrier (a task `cites:`, a cross `origin_fp`, an E-XXXX file) is "
              f"keyed by it, and `triage run` would withhold it while the watermark advanced past it "
              f"(T-11880). A DESCRIPTIVE fingerprint you choose yourself still reads better to the "
              f"next person; pass one via --data '{{\"fingerprint\":\"<short-stable-slug>\"}}'.",
              file=sys.stderr)

    # T-11770 (X-1189): NAME THE REFUSAL VERB WHERE THE FALSE PREMISE IS DISCOVERED. `task refuse` is
    # the governed pre-claim exit, but this generic verb is the seam a worker actually reaches at the
    # moment it finds a card's premise false — `bg_dispatch_halted` is HAND-emitted here (the T-10121
    # chokepoint above says so), and it said nothing about the refusal verb. The reporter's instance
    # is the whole argument: the author CITED the rule in the halt text and still took the halt path,
    # because that is the path that was reachable. So the gap is not knowledge, it is surfacing.
    # Report-only, in the same family as the two WARNs above and placed BEFORE the `--check` early
    # return so a validation run exercises it exactly like a real emit; the classification + the
    # naming-not-routing bound live single-SoT in `journal.premise_false_halt_hint`.
    _premise_hint = journal.premise_false_halt_hint(event_type, data)
    if _premise_hint:
        print(_premise_hint, file=sys.stderr)

    # T-13508: will this task-tied row be folded OUT of its task's audit-post packet by the card
    # opt-in? Report-only and fail-open — contract in `_packet_fold_emit_warning`; this stays a call
    # site. Same family and same placement as the hints above: BEFORE the `--check` early return, so a
    # validation run prints it exactly as a real emit does.
    _fold_warn = _packet_fold_emit_warning(event_type, args.task, data)
    if _fold_warn:
        print(_fold_warn, file=sys.stderr)

    # T-11666 (X-1120, <project>): the NO-WRITE validation mode. THE flag is one early return placed
    # HERE — at the single append site, below every pre-append check — and that placement is the whole
    # design. Everything above runs UNCHANGED, so `--check` does not have a validation path of its own
    # that could drift from the real one: the refusals refuse identically (`_die`, same text, same
    # nonzero exit), the WARNs print identically, and a check added to this verb tomorrow is covered
    # with no second site to remember. Anything ELSE would have been the defect being fixed — <project>
    # verified T-11417 by EMITTING two junk `deviation_captured` rows (an empty payload, a
    # whitespace-only impact), because running the gate was the only way to see it. The journal is
    # append-only, so those rows are permanent and now fold, recurrence-match and triage exactly like
    # real captures — the indistinguishable-from-noise harm that fix's own WARN text names. The
    # alternative — reading the source instead of running it — is what the standing lesson forbids:
    # prove a claim by re-running the gate, not by finding the code.
    #
    # Returns BEFORE the append and therefore before every side-effect below it, each of which is a
    # consequence of a row that does not exist: the witness line names a byte offset nothing was
    # written at, the recurrence reopen would reopen a case file for a capture nobody made, and the
    # kernel-bound auto-file would send the kernel a cross item for a deviation that was never
    # recorded. The verdict says so out loud rather than letting a reader infer that `--check` proved
    # more than it did.
    if getattr(args, "check", False):
        print(f"event: CHECK {event_type} — payload valid, NOTHING appended (no row, no witness). "
              f"Every pre-append check ran on the real path: refusals refuse and WARNs print exactly "
              f"as a real emit would. NOT judged (they run only on an appended row): the recurrence "
              f"reopen and the kernel-bound cross auto-file. Re-run without --check to record it.")
        return

    # T-13036: the near-match offer reads the capture index BEFORE the append — after it, the authored
    # fingerprint is always an exact key and the offer could never fire. AUTHORED keys only (a derived
    # one is already reported above). Report-only: any failure here is swallowed, never a gate.
    _near: list = []
    if event_type == "deviation_captured" and not data.get("fingerprint_derived") \
            and str(data.get("fingerprint") or "").strip():
        try:
            from lib import triage as _triage
            _near = _triage._capture_near_matches(str(data["fingerprint"]).strip(),
                                                  _capture_fingerprint_counts(EVENTS_PATH))
        except Exception:   # noqa: BLE001 — an advisory must never break the capture reflex
            _near = []

    witness = _append_event(event_type, args.task, data, source_ref=source_ref, ts=_event_ts)

    # T-10949 (T-10948 residual R3): SUCCESS IS NOT SILENT. Before this line a successful emit wrote
    # exactly one thing — the row — so when a row later turned out to be missing there was no exit
    # record and no resolved events_path left to inspect, and «overwritten» could not be separated
    # from «never written» (the 2026-08-11 incident, fingerprint
    # `journal-append-lost-across-concurrent-land-ff`). One line on stdout puts the SECOND witness in
    # the caller's own transcript, so an ABSENT row stays attributable to a named path + offset. It
    # is a REPORT, not a store: no receipts file, no sidecar index, no new parser path (CHARTER §P5 —
    # one journal, one format, one parser), and the locator form is the ALREADY-canonical
    # `events.jsonl#ts=<ISO>` (CHARTER §Principle 2 / D-0030), not a new id scheme. Printed here and
    # not inside `_append_event` deliberately: the incident class is the hand-emitted no-worktree
    # D-0049 capture — this verb — while the other ~76 emit call sites would only gain output noise
    # (analysis (c) A5). AFTER the append (a refusal must print no witness) and BEFORE the advisory
    # side-effects below, so the witness leads the caller's transcript.
    print(f"event: {witness['type']} -> {witness['path']}#ts={witness['ts']}  "
          f"(row sha256:{witness['sha256']}, offset {witness['offset']}, {witness['bytes']}B)")

    # Capture-time reopen (D-0086 §2): a manual `event deviation_captured` is a real capture site, so
    # an incoming fingerprint already in a resolved/waived E-XXXX reopens it. Gated to this event type
    # (NOT inside _append_event) so only real captures reopen (audit-pre T-0150 F1). Defensive helper.
    # BOUNDARY (audit-post T-0150 F0): `event` IS the LIVE capture verb — reopen here is correct. A
    # future replay / import / backfill MUST append journal lines DIRECTLY (the events-union model `land`
    # already uses), NOT loop this verb per line — so it cannot reopen historical cases. Deliberate
    # non-gate per anti-complexity F4 (no real replay path exists) + CHARTER non-goal #7 (no FSM creep).
    if event_type == "deviation_captured" and data.get("fingerprint"):
        _reopen_resolved_error(data.get("fingerprint"))

    if _near:
        print(f"yitc-v2: NOTE fingerprint {str(data['fingerprint']).strip()!r} is new, but triage "
              f"already groups it with existing key(s): {', '.join(repr(m) for m in _near)}. If this is "
              f"the same root, REUSE that key next time, or declare the root as `<root>:<subject>` "
              f"(T-11898). The row was recorded as authored (report-only, T-13036).", file=sys.stderr)

    # Cheap adoption belt (T-10385): a dispatched worker capturing a deviation about a still-ready,
    # UNCLAIMED task at pre-claim gets pointed at the covering verb `task refuse` — closing the
    # capture-then-silent-exit miss (2/2 on 2026-07-10). Advisory, print-only, never breaks capture.
    if event_type == "deviation_captured" and args.task is not None:
        _pre_claim_refuse_hint(args.task)

    # T-11419 (X-1073 / SPEC-0085 §3): route a KERNEL-BOUND capture HERE, at the capture, instead of
    # waiting for a `land`. The structural trap this closes: the auto-file's only trigger was the land
    # tail, reading MAIN's journal — so a capture made inside a BRANCH reached the kernel only when that
    # branch landed, and a capture whose OWN SUBJECT is what blocks the land could never route at all.
    # The worse the defect, the less likely its report escaped: <project>'s T-0422 worker captured a
    # kernel defect, halted with the worktree intact, and all three rows sat in the branch journal
    # invisible to `cross outbox` and to the kernel until a controller went looking and re-emitted them
    # BY HAND — a manual fallback with no covering verb, and the stranded finding later cost us an
    # answered-as-resolved item (X-1074).
    #
    # This is a TRIGGER move, not a new mechanism (CHARTER §P1 F1/F2): the same marker, the same
    # `_auto_file_kernel_deviations` closure, the same idempotent origin_fp dedup. Legal exactly where
    # the capture is — a `cross *` append needs no worktree and is territory-in-bounds from any
    # checkout (D-0049 / SPEC-0084 rule 5), and `_cross_self()` already resolves the MAIN checkout name
    # from inside a worktree (T-10260), so a branch-side capture files under the project's real identity.
    # The land sweep STAYS as the backstop for rows that predate this seam (the T-9634 backlog case) and
    # for a capture written by any other path; it files nothing here, because it folds the shared log's
    # existing origin_fps FIRST and this fingerprint is already among them (no duplicate — AC2).
    #
    # FAIL-OPEN and print-only, like the land call-site: the capture is ALREADY appended above, and a
    # cross-log hiccup must never turn a one-command reflex into an error (D-0035/D-0086). The skip is
    # NAMED, never silent (Principle 8) — and the next land re-evaluates the unfiled fingerprint.
    if event_type == "deviation_captured" and cross.is_kernel_bound_deviation(data, KERNEL_NAME):
        try:
            for _rl in _auto_file_kernel_deviations(
                    [{"type": event_type, "ts": witness.get("ts"),
                      "source_ref": source_ref, "data": data}], surface="event"):
                print(_rl)
        except Exception as _rte:
            print(f"event: kernel-bound cross auto-file skipped (non-fatal — the capture IS recorded; "
                  f"the next land re-files it): {_rte}", file=sys.stderr)


EMIT_CLI_INVOKED_INJECTS = (
    "EVENTS_PATH",
    "KERNEL_NAME",
    "REPO_ROOT",
    "SELF_REF_ENV",
    "TASKS_DIR",
    "_append_event",
    "_cli_invoked_shape",
    "_cross_self",
    "_is_consumer_build",
    "_lookup_identity_env",
    "_resolve_session_ref_for_envelope_with_source",
    "_session_epoch",
    "_stdout_was_delivered",
    "_try_resolve_session_ref",
    "_try_resolve_session_ref_with_source",
    "_warn_stdout_discarded",
    "events",
    "gates",
    "journal_mod",
    "state",
)


def _emit_cli_invoked(verb_label: str, argv: list[str], nbytes: int, nlines: int, exit_code: int,
                      args: "argparse.Namespace | None" = None,
                      duration_ms: "int | None" = None,
                      session_ref: "str | None" = None,
                      source_kind: "str | None" = None, reads_since: "dict | None" = None,
                      events_path: "Path | None" = None,
                      content_sha: "str | None" = None, epoch: "int | None" = None,
                      *, EVENTS_PATH, KERNEL_NAME, REPO_ROOT, SELF_REF_ENV, TASKS_DIR, _append_event, _cli_invoked_shape, _cross_self, _is_consumer_build, _lookup_identity_env, _resolve_session_ref_for_envelope_with_source, _session_epoch, _stdout_was_delivered, _try_resolve_session_ref, _try_resolve_session_ref_with_source, _warn_stdout_discarded, events, gates, journal_mod, state) -> None:
    """Emit the cli_invoked observability event for one of the 6 read/query verbs (T-0113, draft §3).
    Append-only, D-0009-safe; task_id=null. session_ref is resolved upstream by _auto_sync, but since
    T-0304 a read verb fail-OPENS on an unwritable journal, so this emit is best-effort (its own
    OSError is swallowed below).

    `session_ref` (T-10246) is the AUTHORITATIVE id a gate-bearing caller already resolved — pass it and
    the receipt is stamped under exactly that id, never RE-DERIVED. `session start` passes the very ref its
    `session_started` anchor was emitted under, so the anchor and the seed receipt share ONE id by
    construction rather than by two independent derivations coinciding. Omit it and the pre-T-10246
    fallbacks apply (the carrier read, then `_append_event`'s best-effort envelope) — kept for direct /
    synthetic callers that emit this verb-label with no resolved ref of their own.

    `source_kind` (T-10318) is the PROVENANCE twin of that param: a caller that already resolved a ref
    KNOWS which selector produced it, so it hands that down rather than letting this function re-derive one
    (re-deriving is exactly what split the two gate-bearing ids in T-10246). `session start` passes the
    class `_session_start_identity` returned (`arg` | `env:<carrier>` | `worktree_stamp` |
    `minted_self_ref`). Pass a `session_ref` WITHOUT a `source_kind` and the row records `explicit` — the
    honest label for a direct/synthetic caller supplying a ref of undeclared provenance.

    `content_sha` + `epoch` (T-13510) ride a `graph query` POINT-LOOKUP receipt only. `epoch` is the
    context-epoch stamp the seed receipt already carries (SPEC-0050 §8; since T-13789 the reading's mark,
    SPEC-1023 rule 6): the caller's value when it established one, else `_session_epoch()`. `content_sha` is the sha256 of the bytes the lookup
    rendered, recorded ONLY when the caller measured it (the stage deliverer does) — it is what lets
    that deliverer tell "this epoch already holds this exact render" from "deliver it". Both are
    additive, D-0009 P5-safe keys: no gate reads either, and read-gate credit stays session-scoped."""
    # T-12840 — FREEZE the measured span FIRST, before this function resolves the session identity:
    # that resolution (`_try_resolve_session_ref`, `_session_epoch`, the envelope resolver below) can
    # fold the whole journal — the T-10115 bounded retry on an unbacked carry measured 684 folds — and
    # it is the emit's own envelope, not the work the row names. Resolution order: see the `reads`
    # block below. Best-effort: a failure leaves `_reads_frozen` None and the block is omitted.
    _reads_frozen = None
    try:
        _span = None
        if reads_since is not None:
            _span = journal_mod.read_counters(since=reads_since)
        elif journal_mod.verb_body_mark() is not None:
            _span = (journal_mod.body_span(verb_label)
                     or journal_mod.read_counters(since=journal_mod.verb_body_mark()))
        if _span is not None:
            _reads_frozen = (_span, {"cards_parsed": _span["cards_parsed"],
                                     "wall_ms": _span["card_wall_ms"]})
        else:
            _reads_frozen = (journal_mod.read_counters(), state.read_counters())
    except Exception:                          # noqa: BLE001 — observability never breaks a verb
        _reads_frozen = None
    shape = _cli_invoked_shape(verb_label, argv)
    fingerprint = hashlib.sha1(f"{verb_label}|{shape}".encode("utf-8")).hexdigest()[:12]
    data = {
        "verb": verb_label,
        "shape": shape,
        "arg_fingerprint": fingerprint,
        "stdout_bytes": nbytes,
        "stdout_lines": nlines,
        # T-11010 (<project> X-0842): `stdout_bytes`/`stdout_lines` count what the verb WROTE, which is
        # identical whether those bytes reached a reader or the null device — so no field on this
        # receipt distinguished a real read from a receipt-only one. This ADDITIVE key records which
        # it was (see `_stdout_was_delivered` for the discriminator + its fail-safe direction).
        # GATE-BEARING since T-11411 (X-1068): `gates.py#_fetched_spec_ids` skips a receipt recorded
        # False, so a fetch sent to the null device no longer opens the read gate (SPEC-0050 §4).
        # Computed at emit time, when both tee call sites have already restored the real stream (and
        # `_CountingTee.__getattr__` delegates `fileno` to its target regardless).
        "stdout_delivered": _stdout_was_delivered(sys.stdout),
        "exit_code": exit_code,
    }
    # T-0358: verb wall-clock (speed observability) — main() measures the verb's OWN execution
    # (symmetric with the tee, which measures the verb's OWN stdout, not _auto_sync's) and passes
    # it here. ADDITIVE key, D-0009 P5-safe (same pattern as node_id/verdict below); only present
    # when measured (the real dispatch path always passes it; a synthetic direct call may omit —
    # no fabricated 0s).
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    # T-13305: the invocation's PEAK resident memory in KiB (RUSAGE_SELF ru_maxrss is KiB on Linux) — the
    # process high-water mark, so it bounds the verb's own peak. ADDITIVE key, omitted on failure.
    try:
        import resource
        _peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if _peak > 0:
            data["peak_rss_kb"] = _peak
    except Exception:                          # noqa: BLE001 — observability never breaks a verb
        pass
    # T-13192 (SPEC-1003 rule 3): a run SERVED from an immutable per-sha kernel checkout stamps the sha
    # that served it — read from the running code's own location (never ENGINE_ROOT) and only while that
    # copy is clean, so it is true by construction. ADDITIVE key, D-0009-safe; ABSENT on every main /
    # worktree run, whose row is therefore byte-identical.
    try:
        from lib import engine_route
        _served = engine_route.running_served_sha()
    except Exception:                          # noqa: BLE001 — observability never breaks a verb
        _served = None
    if _served:
        data["engine_sha"] = _served
    # T-10317 (read-tolerant lane, scope §2): when a read verb ran under a carried YITC_SESSION_REF that
    # is UNBACKED (no live record backs it — the mid-watch concurrent-land window), the envelope
    # session_ref degrades to the best-effort "unresolved" and DISCARDS the carried value. Preserve it
    # VERBATIM + FLAGGED here so a read-tolerated run stays forensically visible (the key name IS the
    # flag). Uses the NON-DYING twin (`_try_resolve_session_ref`) — a backed/resolvable ref adds nothing
    # (no noise on the happy path). ADDITIVE key, D-0009 P5-safe.
    carried_ref = os.environ.get(SELF_REF_ENV, "").strip()
    if carried_ref and _try_resolve_session_ref() is None:
        data["carried_session_ref_unbacked"] = carried_ref
    # T-0260: `graph query`'s shape + arg_fingerprint are OPAQUE — two distinct spec queries collide
    # to one fingerprint (T-0255: SPEC-0016 @05:08 + SPEC-0005 @05:10), so the journal can't attribute
    # a query to its node. Record the queried node-id (cmd_graph_query's own `args.id` positional) as
    # an ADDITIVE key — restores T-0113's stated "payload: verb + args" intent. D-0009 P5-safe
    # (unknown key ignored by consumers); shape/fingerprint UNCHANGED. Point-lookups only — args.id is
    # None for --type/--projected/--recurring, so the key is absent there (bounded, id-only).
    if verb_label == "graph query" and args is not None:
        nid = getattr(args, "id", None)
        if nid:
            data["node_id"] = nid
        # T-11077 (X-0865): the receipt ALSO records WHICH REALM answered — "kernel" or "own"
        # (`cmd_graph_query` stamps `args.resolved_realm` off the branch that resolved). ADDITIVE key,
        # D-0009 P5-safe, and ABSENT for any lookup that resolved no realm (a non-spec/error node, a
        # --type/view/whole-graph form, a failed lookup) — an unstamped row therefore carries NO realm
        # claim at all, which is what lets the SPEC-0042 read-gate fail CLOSED on it under -C rather
        # than credit a kernel contract with a same-id consumer fetch.
        realm = getattr(args, "resolved_realm", None)
        if nid and realm:
            data["node_realm"] = realm
    # T-9786 (X-0158): the top-level `--help` fetch-receipt records the verb-inventory sentinel as its
    # node_id — the SAME ADDITIVE key `graph query` uses — so `_require_help_read` credits the scan via
    # the existing `_fetched_spec_ids` reader (NO new event/store, P1 F1). Emitted from `_HelpInventoryAction`.
    # T-10149 (SPEC-0137, audit-post finding): a GATE-BEARING cli_invoked receipt (the --help
    # fetch-receipt `_require_help_read` matches, the session-start seed receipt `_require_seed_read`
    # matches, and — T-12900 — the `graph query` point-lookup receipt `_require_reads` matches) MUST be stamped under an EXPLICIT strict session_ref — NEVER `_append_event`'s best-effort
    # envelope default. The gates resolve the reader identity via the FAIL-CLOSED keyer
    # (`_resolve_session_ref`); the best-effort envelope resolver would stamp an UNBACKED carry (or
    # 'unresolved'), so with a resolvable strict ref present the receipt lands under a DIFFERENT ref than
    # the keyer resolves → the gate can't find it → false refusal. Set per gate-bearing verb below; None
    # otherwise (an ordinary observability row is fine on best-effort provenance).
    bootstrap_sref = None
    bootstrap_source = None   # T-10318: the selector that produced `bootstrap_sref`, when one is resolved
    if verb_label == "--help":
        data["node_id"] = gates.HELP_INVENTORY_NODE_ID
        # Stamp the help receipt under the SAME ref `_require_help_read` (the keyer `_resolve_session_ref`)
        # resolves — via the NON-DYING twin `_try_resolve_session_ref` (T-10167): a truly unresolvable env →
        # None → best-effort fallback (the gate then refuses too — consistent, no false CREDIT under a
        # mismatched ref). The twin never `_die`s, so `--help` on the happy path leaks NO stderr (the prior
        # `_resolve_session_ref()`-in-a-try swallowed the SystemExit but not `_die`'s already-printed line).
        # T-10318: take the twin's `source` too — the receipt names the selector that won instead of
        # collapsing to `explicit` (audit-pre finding 1). Unresolvable → (None, None) → the envelope
        # resolver below stamps AND labels the row, so the label always describes the ref that is there.
        bootstrap_sref, bootstrap_source = _try_resolve_session_ref_with_source()
    # T-12900 (X-1552): a `graph query` POINT-LOOKUP receipt is gate-bearing too — it is exactly the row
    # `gates._fetched_spec_ids` credits for the SPEC-0042 read-check — so it takes the same strict stamp.
    # Left on the envelope it recorded the raw carry, while the keyer (which honours a carry only when it
    # is BACKED in this locus) resolved the worktree STAMP: in a worktree that outlived its creating
    # session the reader's fetch landed under the reader and the gate looked under the creator, so no
    # re-read could clear `task file`. An explicit, already-resolved ref from the caller (the T-11550
    # stage-bundle delivery hands one down) is used as-is; otherwise the keyer's non-dying twin, as above.
    # Non-lookup forms (no node_id) credit nothing and stay ordinary observability rows.
    if verb_label == "graph query" and data.get("node_id"):
        if session_ref:
            bootstrap_sref, bootstrap_source = session_ref, source_kind
        else:
            bootstrap_sref, bootstrap_source = _try_resolve_session_ref_with_source()
        # The strict stamp DISCARDS a differing carry from the envelope — the case the T-10317 forensic
        # key above exists for, which its keyer-returns-None condition does not reach when the keyer fell
        # through to the stamp. Keep the carried reader visible on the row.
        if carried_ref and bootstrap_sref and bootstrap_sref != carried_ref:
            data["carried_session_ref_unbacked"] = carried_ref
        # T-13510: the point-lookup receipt gains the epoch stamp the seed receipt already has (a
        # receipt without one reads `none`), plus the render's fingerprint when the
        # caller took it. T-13789: the stamp is the reading's MARK (SPEC-1023 rule 6), a string.
        data["epoch"] = (epoch if isinstance(epoch, (int, str)) and not isinstance(epoch, bool)
                         else _session_epoch())
        if content_sha:
            data["content_sha"] = content_sha
    # T-10081 (SPEC-0042 §seed floor): `session start` records the audience-seed READ receipt the SAME
    # ADDITIVE way — a cli_invoked row whose node_id is the seed sentinel, so `_require_seed_read` credits
    # it via the existing `_fetched_spec_ids` reader (NO new event/store, P1 F1; the exact analog of the
    # --help fetch-receipt just above). Emitted from the cmd_session_start residue AFTER seed delivery.
    if verb_label == "session start":
        data["node_id"] = gates.SEED_READ_NODE_ID
        # T-10082 (SPEC-0050 §8): stamp the seed receipt with the CURRENT context epoch so
        # `_require_seed_read` can reject a pre-compact receipt. T-13789 (SPEC-1023 rule 6): the stamp is
        # the reading's MARK — `marker:<identity>` / `none` / `unknown` (this run's «epoch unknown»
        # receipt, rule 6a; also what a provider whose detection is not observed records — its verbs
        # proceed on any receipt) — compared by identity. A pre-change NUMBER equals no mark.
        data["epoch"] = _session_epoch() or "unknown"
        # T-10149 (SPEC-0137 Rule 1 bootstrap-exemption): this seed receipt is the very evidence that BACKS
        # a carried self-ref (`_carried_ref_backed`), so resolving its OWN session_ref through the
        # fail-closed rediscovery resolver would be chicken-and-egg (the receipt is not there yet → _die).
        # `session start` is the record's WRITER, so it must NOT route this receipt through the rediscovery
        # resolver.
        #
        # T-10246: take the ref the CALLER already resolved — `cmd_session_start` passes the very
        # `resolved_ref` its `session_started` anchor was emitted under. Both gate-bearing emits therefore
        # derive from ONE value, which is what SPEC-0137 Rule 2 demands of them ("an emit that WRITES
        # read-gate evidence ... passes an EXPLICIT strict/bootstrap session_ref — never the best-effort
        # default"). Re-deriving it here is what split them: inside a stamped worktree the carrier read
        # below yields None for a carrier-less agent, `_append_event` falls back to the best-effort envelope
        # resolver, and that rediscovers the WORKTREE STAMP — while the anchor had been emitted under the
        # freshly-minted ref. Neither ref then carried both, so `_ref_current_epoch_anchored` was False and
        # the read-gate keyed on an id the agent was never told to carry.
        #
        # The carrier read remains the FALLBACK for a caller that passes nothing (tests/synthetic emits):
        # a present carrier → its value; a carrier-less env → None (the best-effort envelope resolver then
        # stamps it). Read via the NON-DYING registry reader `_lookup_identity_env` (T-10167) — exactly the
        # prior `_resolve_session_ref_with_source()[0]` MINUS the `_die`/assert (SELF_REF_ENV is the sole
        # registry env carrier), so a fresh mint no longer leaks `_die`'s already-printed stderr line.
        #
        # T-10318: label the ref with the selector that ACTUALLY produced it. A caller-passed ref carries
        # the authoritative `_session_start_identity` class (threaded down as `source_kind` — the T-10246
        # "don't re-derive" move, one field wider); the carrier FALLBACK is by construction `env:<NAME>`,
        # read from the same non-dying registry reader. Neither branch re-resolves anything.
        if session_ref:
            bootstrap_sref, bootstrap_source = session_ref, source_kind
        else:
            _carrier_name, _carrier_val = _lookup_identity_env()
            bootstrap_sref = _carrier_val or None
            bootstrap_source = f"env:{_carrier_name}" if _carrier_val else None
    # T-0310: `graph conformance`'s verdict (GREEN/RED) maps bijectively to exit_code (0/1 —
    # cmd_graph_conformance prints GREEN+exit 0 OR RED+sys.exit(1)), but exit_code is a generic
    # field a verdict-grep won't hit. Record the verdict as an ADDITIVE key (same pattern as the
    # node_id key above) so a conformance RUN + its VERDICT are directly greppable in events.jsonl.
    # D-0009 P5-safe (unknown key ignored by consumers); shape/arg_fingerprint UNCHANGED.
    if verb_label == "graph conformance":
        data["verdict"] = "GREEN" if exit_code == 0 else "RED"
    # T-10318 (session-id resolution telemetry): record WHICH selector resolved the session_ref that
    # actually stamps THIS row, and — when nothing resolved — WHY. Placed HERE, after every per-verb branch
    # has finally settled `bootstrap_sref`, because the two caller CLASSES answer "what does a missing
    # value mean?" differently and the READER owns that judgement, not the resolver
    # (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`):
    #   - a resolved bootstrap ref (gate-bearing `--help` / `session start`) → the selector its own resolver
    #     named; `explicit` ONLY when a direct/synthetic caller passed a ref of undeclared provenance.
    #   - NO bootstrap ref (an ordinary observability row, OR a gate-bearing verb whose resolution came up
    #     empty) → `_append_event` falls back to the best-effort ENVELOPE resolver, so the row must be
    #     labeled by THAT resolver. Labeling it `explicit` here would describe a ref that never stamped it.
    # ENVELOPE role only (`lessons/read-gate-session-ref-provider-carrier-flap.md`): this reads the
    # best-effort provenance resolver, NEVER the fail-closed keyer — unlike the T-10317
    # `carried_session_ref_unbacked` block above, which deliberately asks the KEYER's question ("would the
    # keyer back this carry?"). Two roles, two questions; keeping them distinct is what the decouple buys.
    # Both keys are ADDITIVE, D-0009 P5-safe; `shape`/`arg_fingerprint` unchanged. Resolution itself is
    # untouched — this records the decision, it does not make one.
    if bootstrap_sref is not None:
        data["source_kind"] = bootstrap_source or "explicit"
    else:
        _env_ref, _env_source, _env_fallback = _resolve_session_ref_for_envelope_with_source()
        data["source_kind"] = _env_source
        # Present ONLY on the `unresolved` sentinel (`ambiguous` vs `absent` — the two OPPOSITE operator
        # situations it used to collapse). Omit-when-default: no happy-path noise.
        if _env_fallback is not None:
            data["fallback_reason"] = _env_fallback
    # T-11963 — SAY IT AT THE PRODUCER. Every per-verb `node_id` branch above has now settled, so this
    # is the first point that knows BOTH halves of the question: was this receipt CREDIT-BEARING, and
    # was its stdout DELIVERED. Placed here for that reason, and it re-uses the value already in `data`
    # rather than asking `_stdout_was_delivered` a second time (one computation, one answer).
    if data["stdout_delivered"] is False and data.get("node_id"):
        _warn_stdout_discarded(verb_label, data["node_id"])
    # T-12034 — the ADDITIVE `reads` block: what this process physically READ, with its denominators,
    # so read amplification is reportable per verb per project. SPEC-0190 rule 4 already names the
    # defect ("a reader that folds the whole archive to answer a question about the last seven days")
    # — this is the measurement behind that rule. Measured before it existed: engine `debt` = 2,052
    # physical segment reads over 93 segments (22x) and 11.1M json.loads over ~596k rows; <project>
    # under `-C` = 27x on the SAME code; even `bin/yitc-v2 --help` parses ~54k rows. Nothing reported
    # any of it, so T-11453's 32.6 s became 378 s with no site changing.
    #
    # ADDITIVE ON THE EXISTING ROW — deliberately NOT a second telemetry file or store (the external
    # consult's F1/Q2, the gate-specs F7): this event is already emitted once per verb, already
    # carries `duration_ms`, and already grows by additive keys (`node_id`, `source_kind`,
    # `stdout_delivered`). A parallel store would be a second journal for a number the journal can
    # carry. Readers were checked BEFORE adding, per
    # `lessons/an-additive-payload-needs-its-readers-checked-before-adding`: no reader of this payload
    # asserts an exact key set, and `reads` was unused on it.
    #
    # NUMERATORS come from the primitives (`journal.read_counters()` / `state.read_counters()`); the
    # counters are merged HERE rather than in either module, because `journal` imports `state` and the
    # reverse call would be a cycle. DENOMINATORS: `rows` is the folds' OWN line counts (no extra
    # read at all); `segments` and `cards` are one directory listing each, taken once per process.
    # The counters therefore add NO reads to any verb.
    #
    # BEST-EFFORT, on the same terms as the append below (T-0304): a verb must not die because an
    # observability number could not be computed. A failure omits the key rather than fabricating a
    # zero, so an ABSENT `reads` reads as "not measured", never as "measured nothing".
    #
    # T-12840 — THE ROW MEASURES THE WORK IT NAMES, and the resolution lives HERE, at the one
    # producer, so no caller can bypass it (see `journal.py` above `verb_body` for the measurement).
    # Most specific first: (1) `reads_since`, an explicit mark (`main` passes its body mark); (2)
    # inside a verb body, the SPAN the seam's own ReadScope recorded for THIS label — which is how an
    # in-process render (the stage-bundle delivery loop) is measured with no step of its own; (3)
    # inside a body with no such span, the WHOLE body so far — FAIL-LOUD: an unspanned nested emit
    # over-reports and trips the bound, it is never omitted and never hidden; (4) outside any body,
    # the whole process, as before (synthetic callers, the pre-dispatch `--help` emit).
    # `artifacts` = distinct physical files folded in that span — SPEC-0190 rule 10's "per artifact
    # in scope" denominator, which SPEC-0119 rule 37 divides by.
    try:
        _jr, _sr = _reads_frozen
        data["reads"] = {
            "folds": _jr["folds"],
            "segments": len(events.segment_paths(EVENTS_PATH)),
            "artifacts": _jr["artifacts"],
            "segments_skipped": _jr.get("segments_skipped", 0),   # T-12494 — verified-shared, not read
            "rows_parsed": _jr["rows_parsed"],
            "rows": _jr["rows"],
            "cards_parsed": _sr["cards_parsed"],
            "cards": sum(1 for _ in TASKS_DIR.glob("T-*.yaml")) if TASKS_DIR.exists() else 0,
            # `project` / `realm` make the row foldable per project — the plan folds ratios per verb
            # per project, and a `-C` consumer run emits onto its OWN journal under the SAME kernel
            # code, so the row must say which corpus it measured. Both reuse the existing helpers.
            # T-13030: `_cross_self()` (git common dir → canonical key), NOT `REPO_ROOT.name` — inside a
            # task worktree the latter is the leaf (`T-0728`), fragmenting one project's seams per worktree.
            "project": (_cross_self() if _is_consumer_build() else KERNEL_NAME),
            "realm": ("consumer" if _is_consumer_build() else "kernel"),
            # Recorded, never a target (auditor Q6): this is a shared host under load 25-33, so the
            # governing numbers are the RATIOS above. Milliseconds spent inside the read primitives.
            "wall_ms": round(_jr["wall_ms"] + _sr["wall_ms"], 3),
        }
    except Exception:                          # noqa: BLE001 — observability never breaks a verb
        pass
    # T-0304: observability is BEST-EFFORT — a read verb must not die because its cli_invoked append
    # hit an unwritable journal. Only OSError (the I/O class) is swallowed; a serialization/contract
    # bug (any non-OSError) still surfaces (audit-pre f1).
    try:
        _append_event("cli_invoked", None, data, session_ref=bootstrap_sref,
                      **({"events_path": events_path} if events_path is not None else {}))
    except OSError:
        pass
    # T-10784 (X-0615): hand the GATE-BEARING ref back to the caller. The `--help` action needs to know
    # whether this receipt carries an identity the read-gate can credit, and re-resolving it there would
    # be a second, parallel resolution that could disagree with the one actually stamped (P1 F2 — a view
    # over the existing value, not a new path). Also set for a `graph query` point-lookup (T-12900), whose
    # callers ignore it. None on every non-gate-bearing verb (the ordinary
    # observability rows above, stamped by the best-effort envelope resolver) AND on a gate-bearing verb
    # whose resolution came up empty — the two the caller must not confuse, so the caller asks only where
    # the distinction is meaningful. Every existing caller ignores the return; additive.
    return bootstrap_sref
