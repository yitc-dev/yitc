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

import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from lib import lockfile  # the ONE flock-target open (X-0226 / T-10189 / T-10250 idiom, T-10336)

SOURCE_TAG = "yitc-v2-cli"
MAX_EVENT_BYTES = 3500     # SPEC-0002 per-line byte cap (PIPE_BUF 4096 − margin)

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
    for seg in segment_paths(journal_path):
        try:
            fh = Path(seg).open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                ts = _row_ts(line)
                if ts is None or ts[:10] > ceiling:      # an impossible anchor is not an anchor
                    continue
                if newest is None or ts > newest:
                    newest = ts
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
    keep, moving = [], {}
    for line in live.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line:
            continue
        ts = _row_ts(line)
        if ts is None or ts >= boundary:        # rule 2: `ts >= boundary` STAYS; undatable never moves
            keep.append(line)
        else:
            moving.setdefault(ts[:10], []).append(line)
    if not moving:
        return None                              # a no-op is cheap and VISIBLE — never a silent pass
    moved_keys = {k for lines in moving.values() for k in map(_dedup_identity, lines)}

    # ── HALF 1: the archive, written and made DURABLE FIRST (rule 3a).
    adir = archive_dir(live)
    adir.mkdir(parents=True, exist_ok=True)
    written = []
    for label in sorted(moving):
        seg = archive_segment_path(live, label)
        existing = seg.read_text(encoding="utf-8", errors="replace").splitlines() if seg.exists() else []
        merged = dedup([ln for ln in existing if ln] + moving[label])
        write_text_atomic(seg, "".join(ln + "\n" for ln in merged))
        written.append(seg)
    _fsync_dir(adir)

    # ── VALIDATION, BEFORE the live file is truncated. Read the archives BACK OFF DISK — not from the
    # in-memory `merged` above, which would only prove this process's own arithmetic to itself.
    on_disk = set()
    for seg in written:
        for line in seg.read_text(encoding="utf-8", errors="replace").splitlines():
            if line:
                on_disk.add(_dedup_identity(line))
    missing = moved_keys - on_disk
    if missing:
        raise RuntimeError(
            f"rotate_journal: {len(missing)} row(s) did not survive the archive write — "
            f"live segment {live} left UNTOUCHED (SPEC-0190 rule 3a: durable before truncate)")
    if _at:
        _at("archive-write")

    # ── HALF 2: the live segment, rewritten the same atomic way, only now.
    if _at:
        _at("live-truncate")
    write_text_atomic(live, "".join(ln + "\n" for ln in keep))
    _fsync_dir(live.parent)
    return {"moved": len(moved_keys), "kept": len(keep), "boundary": boundary,
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


def _journal_lock_path(resolved_journal, key):
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
    byte-identical whenever the two roots coincide — which is every ordinary host."""
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
            return persistent_root / f"yitc-journal-{key}.lock"   # PERSISTENT — env-independent (T-10755)
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
    return lock_dir / f"{key}.lock"


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


def known_event_types(events_path=None) -> frozenset:
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
    a non-existent event type — the unsatisfiable-by-construction probe class (T-9694 / X-0134)."""
    key = str(events_path) if events_path else ""
    cached = _known_event_types_cache.get(key)
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
    if events_path:
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
    # not a placeholder). Scope note (pass-2 F2): only text-bearing payloads are bounded
    # here; arbitrary `event --data` payloads are caller-sized lifecycle data (small by
    # construction) and are NOT force-truncated — no incident warrants a whole-event
    # truncator (anti-complexity Principle 1).
    line = json.dumps(event, ensure_ascii=False, default=_json_default)
    if len(line.encode("utf-8")) > MAX_EVENT_BYTES and isinstance(payload.get("text"), str):
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
