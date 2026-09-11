"""Cross-project coordination verb family for the yitc-v2 CLI — the `cross
request|inbox|outbox|pick|done|reject|close|ack` verbs over the kernel-owned SHARED coordination log
(SPEC-0085 the event-FSM/kind/write protocol + SPEC-0086 the verb contract). The `archive` verb (rule 1)
is DEFERRED to a follow-up plan — this cut ships the other 8.

Built CODE-BEFORE-ACTIVATION (D-0047 B5): SPEC-0085/0086 are `proposed`; the cutover task (T-9293)
flips them active + wires the `implements:` anchors. This module adds the code only.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It imports only
stdlib and the stdlib-only `lib.host_paths` leaf; it NEVER back-imports the host. bin/yitc-v2 keeps thin `cmd_cross_*` residue (the error.py /
events.py injection precedent) that resolves the host-coupled inputs and injects them, so a `-C`
REPO_ROOT rebind + every `monkeypatch.setattr(yitc, …)` stay honored at call time:
  - cross_log_path: the canonical OUT-OF-REPO shared store path (host CROSS_LOG_PATH; owner-tunable
    infra per SPEC-0084 r3, env-overridable).
  - self_name: the STABLE participant id — the host resolves the MAIN checkout name (git-common-dir
    resolved, IDENTICAL across the main checkout, any worktree, and a `-C` consumer, NOT the
    worktree-leaf `REPO_ROOT.name` — consult-A F1) and then CANONICALIZES it through `peer_aliases`.
  - peer_aliases: {alias -> canonical} — the host reads registry.yaml and maps BOTH the registry KEY
    and the checkout BASENAME of every yitc_v2 project onto the ONE canonical id. See §Peer identity.
  - registry_peers: the CANONICAL ids of the registered yitc_v2 projects — the `cross request --to`
    fail-closed membership set AND the routability test behind the unroutable WARN.
  - cross_emit: append a PROTOCOL event to the shared log via the SAME events.py primitive (one
    format/parser — D-0049 single-line atomic append + flock + union-merge).
  - local_append: the host `_append_event` — used ONLY for the journal-observable `cross_refused`
    refusal trace, which lives in the session's OWN events.jsonl (the `read_gate_refused` precedent),
    keeping the coordination log pure (protocol events only).

The shared log is the SAME journal mechanism (the `cross_*` family extends SPEC-0025's OPEN catalog).
An item's status is the FOLD of its events by immutable verb-allocated id (rule 1): the fold DROPS
illegal emit-role / illegal-verb-for-kind events (rule 2 defense-in-depth) and resolves conflicting
terminals by a FIXED TOTAL ORDER (earliest `ts`, content-hash tiebreak) + a surfaced `contested` flag.

§Peer identity (T-10260 / X-0259 — SUPERSEDES the pre-T-10260 basename contract).
A participant id is the project's CANONICAL REGISTRY KEY; its main-checkout BASENAME is an ALIAS of
that key, normalized away at read time. The two used to be different ids: `_cross_self` minted the
basename while the nightly concern-drift auto-file addressed the registry key, so for the one project
whose key != basename (`trend-finder` at `.../social-parser`) three live inbound items were folded by
NO session and stayed invisible for weeks. T-9587's fail-closed `--to` validation could not catch it —
it guards `cross request` only, and the nightly appends via `cross_emit` directly.

Canonicalization happens at ONE choke point: `read_events(path, aliases)` rewrites `from`/`to`/`by`
before anything folds them. `fold()` and every pure helper below therefore take NO `aliases` argument
and simply compare canonical to canonical — one seam, no threading (guarded by a signature test).
Writes are canonical too (`cmd_cross_request` normalizes `--to`; `self_name` arrives canonical), so
exactly ONE spelling ever reaches the log: the alias is a NORMALIZATION, not a second addressable
name — which is what T-9587 rejected when it declined "two names per peer".
"""
from __future__ import annotations

import argparse
import difflib
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path      # T-11171: the guard set holds resolved Paths, so the compare needs one

# The ONE flock-target open (X-0226 / T-10189 / T-10250 idiom, hoisted to a shared home by T-10336).
# Every caller imports this module as the package member `lib.cross` (bin/yitc-v2, the tests, and
# bin/verify-backup.sh since T-10382 put bin/ on sys.path), so the sibling import is a plain
# package import — the former flat-context compat shim (T-10336) is retired.
from lib import host_paths  # T-12024: the stdlib-only host-home leaf (no cycle — it imports nothing from lib)
from lib import events     # T-11171: the T-10401 guard set — already loaded via textutil below
from lib import lockfile
from lib import graph as graph_lib   # T-11992: the shared SPEC-0092 retrieval-hint renderer (`spec_query_hint`) — graph.py imports only lib.state + stdlib, so this stays acyclic
from lib import state       # stdin YAML mapping ingest (`cross request --from-stdin`, T-10719)
from lib import textutil    # the shared argv-rides-the-shell substrate (E-0054, T-10719)

# ── The shared store's location + multi-user appendability (SPEC-0084 rules 1 + 3) ────────────
# THE CANONICAL SHARED-STORE LOCATION. SPEC-0084 rule 1 says the WHOLE peer-set appends to and reads
# THE ONE instance; rule 3 makes the concrete path owner-tunable INFRA config rather than a normative
# constant. A `Path.home()`-derived default cannot satisfy rule 1 the moment the peer-set spans OS
# USERS — each user silently gets their OWN empty store, so inbound items are invisible, outbound
# requests never arrive, and the two stores allocate X-ids independently and COLLIDE (X-0663, live
# once SPEC-0169 opened the collaborator lane). So the default is ONE fixed absolute path, identical
# for every uid. Shape copied from `REGISTRY_PATH` in bin/yitc-v2 — an owner-tunable host-infra
# default written as an absolute constant, overridden by its own env var.
#
# WHY THIS PATH AND NOT AN FHS-NEUTRAL ONE (/var/lib/…): SPEC-0084 rule 3 also REQUIRES the store to
# be backed up, and it is backed up for exactly one reason — it sits under the host home, which the
# host's own offsite-backup script already rsyncs offsite every 4h (see bin/verify-backup.sh). That
# host script is EXTERNAL read-only territory (D-0019 / AGENTS §Scope-boundary), so a v2 write cannot
# follow the store elsewhere; moving it would silently drop the backup the spec demands. The location
# is reachable by every peer: the host home is group-traversable and every collaborator is in the
# owner's group. Owner-tunable via YITC_CROSS_LOG if that ever changes.
#
# DERIVED, NOT LITERAL (T-12024). The home is resolved by `host_paths.host_home()` rather than spelled
# out, so an engine copied to another machine anchors the store on THAT machine instead of inheriting
# this one's path — the code-side half of what SPEC-0074 rule 4 already enforces for the docs. This
# does NOT reintroduce the per-uid split X-0663 hit: `host_home()` resolves the home the ENGINE lives
# under, which is one value per MACHINE and not one per caller, so every peer still reads THE ONE
# store SPEC-0084 rule 1 requires. On this host the derived value is byte-identical to the literal it
# replaces. Read the branch rule in `lib/host_paths.py`.
CANONICAL_LOG_PATH = str(host_paths.host_home() / ".yitc-coordination" / "coordination.jsonl")

# Multi-uid append modes. The dir is SETGID so a row created by any peer inherits the store's group
# (without it a file <collaborator-2> creates is group `<collaborator-2>`, which <collaborator-3> is not in — the same split one
# layer down); the store + lock are group-writable because appending is what every peer does. 0664 is
# not a new judgement: it is the already-decided journal-class mode (the W1-W8 multi-user plan's W7
# pinned "governance files 0644, but events.jsonl + journal-sync-state STAY 0664 — journal append
# needs group-write"), and the coordination log is an instance of that same journal mechanism.
SHARED_DIR_MODE = 0o2775    # rwxrwsr-x
SHARED_FILE_MODE = 0o664    # rw-rw-r--


# ── The MACHINE SCOPE of the store (SPEC-0084 rule 3 — T-12047) ───────────────────────────────
# The store is a PER-INSTALLATION instance: one per MACHINE, shared by that machine's peer-set, its
# CONTENTS never travelling and no two instances ever connecting (a coordination transport across
# machines would be a second journal mechanism over a network, which CHARTER §P5 forbids). The
# DEFAULT already has that property since T-12024 anchored it at `host_paths.host_home()`. What did
# not was the OVERRIDE: `YITC_CROSS_LOG` pointed at a network mount would quietly make two machines
# share one store and the boundary would be nominal only (the off-server release plan's retirement
# (a), "execution care", concept-audit C6). So the override is CLASSIFIED here, at the one resolution
# site, and a target outside the machine is refused by name.
#
# SCOPE, deliberately narrow: the OVERRIDE only. The derived default is not re-judged — a host whose
# home directory itself sits on a network filesystem is a legitimate installation, and refusing it
# would brick every verb over a reading this card was not filed to make.


class CrossLogScopeError(RuntimeError):
    """`YITC_CROSS_LOG` points OUTSIDE this machine — the override is refused (SPEC-0084 rule 3)."""


# A remote URI (`ssh://host/...`, `smb://...`, `s3://...`) and the scp/rsync `[user@]host:path` form.
# Both are unambiguous: neither can name a file on THIS machine. The scp form deliberately requires a
# colon BEFORE any `/`, so every absolute local path — including the legal-but-odd `/tmp/a:b/log` —
# is out of its reach.
_REMOTE_URI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")
_SCP_TARGET_RE = re.compile(r"^[^/\s:]+(@[^/\s:]+)?:(?!//)")

# Filesystem types whose storage lives on ANOTHER machine. Enumerated rather than pattern-matched:
# `fuse.*` covers local things too (`fuse.gvfsd-fuse`, `fuse.portal`, `fuse.snapfuse`), so only the
# remote fuse backends are named. A type absent from this set reads as LOCAL — the same
# fail-toward-working posture as the unreadable-mount-table branch below.
REMOTE_FSTYPES = frozenset({
    "9p", "afs", "beegfs", "ceph", "cifs", "coda", "fuse.davfs", "fuse.davfs2", "fuse.rclone",
    "fuse.s3fs", "fuse.sshfs", "gfs2", "glusterfs", "lustre", "ncpfs", "nfs", "nfs3", "nfs4",
    "ocfs2", "smb3", "smbfs", "sshfs",
})


def _mount_fstype(path, mounts_path="/proc/mounts") -> "tuple[str | None, str]":
    """`(fstype, mountpoint)` of the filesystem `path` lives on — or `(None, why-not)`.

    Read from the mount table rather than hand-listed, the same reason (and the same octal-unescape
    idiom) as `worktree_lifecycle._mount_roots`: a mount that appears later must be covered without
    editing this site. The LONGEST matching mount point wins, which is what makes a network mount
    nested under a local one classify as the network mount it is.
    """
    try:
        with open(mounts_path, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError as e:
        return None, f"{mounts_path} unreadable ({e.strerror or e})"
    best = None
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        mp = fields[1].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
        if path == mp or path.startswith(mp.rstrip("/") + "/"):
            if best is None or len(mp) > len(best[1]):
                best = (fields[2], mp)
    if best is None:
        return None, f"no mount point in {mounts_path} covers {path}"
    return best


def classify_log_override(override, mounts_path="/proc/mounts") -> "tuple[str, str]":
    """Is this override target on THIS machine? Returns `(verdict, detail)`.

    `local` — accept silently. `remote` — refuse. `unknown` — the target could not be classified
    (no readable mount table: a non-Linux installation, which is exactly the portability SPEC-0084
    rule 3 exists to enable), so it is accepted with a LOUD report rather than bricking the engine.
    """
    if _REMOTE_URI_RE.match(override):
        return "remote", "a remote URI — it names a host, not a file on this machine"
    if _SCP_TARGET_RE.match(override):
        return "remote", "an scp/rsync `host:path` target — it names a host, not a file on this machine"
    fstype, where = _mount_fstype(os.path.realpath(override), mounts_path)
    if fstype is None:
        return "unknown", where
    if fstype in REMOTE_FSTYPES:
        return "remote", f"its mount point {where} is a {fstype} network filesystem"
    return "local", f"its mount point {where} is a local {fstype} filesystem"


def resolve_log_path(env=None, mounts_path="/proc/mounts", stderr=None) -> str:
    """Resolve the ONE shared coordination-store path — the single resolution site (SPEC-0084 r3).

    `YITC_CROSS_LOG` (owner-tunable infra config) wins; otherwise the canonical location above. Every
    caller routes through here — the bin/yitc-v2 `CROSS_LOG_PATH` global, bin/verify-backup.sh, and
    the migration utility — so no second copy of "where the store lives" can drift.

    The override is bounded to THIS MACHINE (rule 3, T-12047 — see the block above): a target outside
    it RAISES `CrossLogScopeError` naming it; an unclassifiable target is accepted with a loud report.
    `mounts_path` / `stderr` are injection seams for the verifier; production passes neither.
    """
    env = os.environ if env is None else env
    override = env.get("YITC_CROSS_LOG")
    if override:
        verdict, detail = classify_log_override(override, mounts_path)
        if verdict == "remote":
            raise CrossLogScopeError(
                f"YITC_CROSS_LOG points OUTSIDE this machine: {override} ({detail}). The coordination "
                f"store is a PER-INSTALLATION instance (SPEC-0084 rule 3) — ONE per machine, shared by "
                f"that machine's peer-set; no two instances connect and no network transport exists, so "
                f"a shared target would silently merge two machines' coordination state. Point it at a "
                f"LOCAL path on this machine, or unset it to use {CANONICAL_LOG_PATH}."
            )
        if verdict == "unknown":
            print(
                f"yitc-v2: WARNING: cannot verify that YITC_CROSS_LOG target {override} is on THIS "
                f"machine ({detail}) — accepting it. SPEC-0084 rule 3: the coordination store is a "
                f"PER-INSTALLATION instance; a target on a network filesystem would silently share one "
                f"store between machines.",
                file=sys.stderr if stderr is None else stderr,
            )
        return os.path.realpath(override)
    return CANONICAL_LOG_PATH


def _widen(path, mode) -> None:
    """Best-effort: add `mode`'s bits to `path`, never narrowing, never raising.

    A peer-owned path we may not chmod is LEFT ALONE — silence here is correct, because the append
    that follows still fails loudly if the mode really is wrong. Widening (`cur | mode`) rather than
    setting keeps any extra bits an owner deliberately added.
    """
    try:
        cur = stat.S_IMODE(os.stat(str(path)).st_mode)
        if cur & mode != mode:
            os.chmod(str(path), cur | mode)
    except OSError:
        pass


def ensure_shared_store(store_path, lock_path=None) -> None:
    """Make the ONE shared store appendable by EVERY OS user in the peer-set (SPEC-0084 r1).

    Create the store's directory, the store file, and (when given) its id-allocation lock with the
    multi-uid modes above, and widen them when a peer created them under a restrictive umask — a
    umask of 022 leaves a 0644 file only its creator can append to, which is the same cross-user
    permission failure X-0226 hit on the flock target. The fix there (assert the mode at create so a
    umask cannot lock a peer out, `bin/lib/lockfile.open_flock_target`) is the analog this extends
    from the lock to the store itself; `write_text_atomic`'s umask-respecting default is NOT enough
    here precisely because it respects a umask that differs per collaborator.

    WRITE PATHS ONLY. Never call this from a read/fold path: it creates the store file, and a
    spuriously-created empty store would mask `bin/verify-backup.sh`'s pre-cutover soft-skip and turn
    "no store yet" into "an empty store".

    T-11171 — the guarded-target refusal. This runs BEFORE any filesystem call because `_cross_emit`
    calls us BEFORE `events.append_event`, and it is `append_event` that carries the T-10401
    test-hermeticity guard. So a harnessed test with no $YITC_CROSS_LOG override had its APPEND
    refused but still reached the PRODUCTION store first: makedirs on its directory, O_CREAT on the
    store and the id-alloc lock, and `_widen`'s chmod on all three. The row never landed; the
    metadata mutation did. Reusing the SAME already-armed signal (no new env var, no second notion of
    "this is a test process") closes that last step of the write path — the one place a test could
    still touch the real store. Inert in production, where the var is unset.
    """
    guarded = getattr(events, "_GUARDED_JOURNALS", frozenset())
    if guarded:
        for target in (store_path, lock_path):
            if target is None:
                continue
            try:
                resolved = Path(os.path.realpath(str(target)))
            except OSError:
                continue        # unresolvable — let the makedirs/open below report it
            if resolved in guarded:
                raise AssertionError(
                    f"T-11171 test-hermeticity guard: this test reached the LIVE shared coordination "
                    f"store ({resolved}) through `ensure_shared_store`. Even without an append this "
                    f"creates + chmods the real store and its directory. Point $YITC_CROSS_LOG at "
                    f"your own sandbox before driving any cross WRITE path."
                )
    try:
        parent = os.path.dirname(str(store_path)) or "."
        os.makedirs(parent, exist_ok=True)
    except OSError:
        return          # unwritable parent — let the append itself report it, loudly
    _widen(parent, SHARED_DIR_MODE)
    for target in (store_path, lock_path):
        if target is None:
            continue
        try:
            os.makedirs(os.path.dirname(str(target)) or ".", exist_ok=True)
            os.close(os.open(str(target), os.O_CREAT | os.O_WRONLY | os.O_APPEND, SHARED_FILE_MODE))
        except OSError:
            continue    # peer-owned or unwritable — nothing to widen, and not ours to fix
        _widen(target, SHARED_FILE_MODE)


# ── Event FSM (SPEC-0085 rule 2) — who may EMIT, which kinds, which are terminal ──────────────
CROSS_KINDS = ("note", "task", "bugfix")

# Author = the item's `from`; receiver = its `to`. Role decides who may legally emit each event.
AUTHOR_EVENTS = frozenset({"cross_requested", "cross_closed", "cross_withdrawn", "cross_disputed"})
RECEIVER_EVENTS = frozenset({"cross_picked", "cross_done", "cross_rejected", "cross_acked"})

# Per-kind protocol shapes (rule 3): which kinds each event is legal for.
EVENT_KINDS = {
    "cross_requested": frozenset(CROSS_KINDS),
    "cross_picked":    frozenset({"task", "bugfix"}),
    "cross_done":      frozenset({"task", "bugfix"}),
    # T-10954: `note` joins this row so an AUTHOR can honestly terminate a one-way note, whose only
    # other terminal (`cross_acked`) belongs to the RECEIVER — who has no cause to ack an FYI that
    # asks nothing, leaving the note `requested` forever. This row is COARSE (event x kind), and a
    # note closes in the OUT-OF-BAND MODE ONLY, so it is paired with the `_legality` clause below;
    # never widen this row without that clause.
    "cross_closed":    frozenset({"task", "bugfix", "note"}),
    "cross_rejected":  frozenset({"task", "bugfix"}),
    # T-11423 — the AUTHOR's negative verdict on a `done` fix (`cross dispute`). The exact kind
    # set of `cross_rejected` one role over: a `note` never reaches `done`, so there is nothing
    # for an author to disprove on it.
    "cross_disputed":  frozenset({"task", "bugfix"}),
    "cross_acked":     frozenset({"note"}),
    "cross_withdrawn": frozenset(CROSS_KINDS),   # the author may retract any kind
}

TERMINAL_EVENTS = frozenset({"cross_closed", "cross_acked", "cross_rejected", "cross_withdrawn"})

# Event → the status label the fold assigns.
EVENT_STATUS = {
    "cross_requested": "requested", "cross_picked": "picked", "cross_done": "done",
    "cross_closed": "closed", "cross_acked": "acked", "cross_rejected": "rejected",
    "cross_withdrawn": "withdrawn",
}
TERMINAL_STATUSES = frozenset({"closed", "acked", "rejected", "withdrawn"})

# T-11423 — PROTOCOL events that carry NO status of their own. `cross_disputed` is deliberately absent
# from `EVENT_STATUS` (and from `TERMINAL_EVENTS`/`TERMINAL_STATUSES`): it introduces NO new status
# class. It CANCELS the `done` an earlier `cross_done` established, so the item falls back to the
# status its other events already support (`picked`) — see `fold`. Both readers that walk an item's
# events (`fold`, `item_events`) skip `et not in EVENT_STATUS`, so this is the ONE seam that admits
# such an event to the legality check + the rendered chain; a future statusless protocol event joins
# HERE rather than growing a second skip-list.
NONSTATUS_PROTOCOL_EVENTS = frozenset({"cross_disputed"})

# --- `cross request --from-stdin` × argv content-flag conflict (T-10719, mirroring T-10437/X-0304) ---
# `--brief` is free PROSE that is PUBLISHED to another project, and argv rides the SHELL: a backticked
# identifier in a brief is substituted away BEFORE this verb runs, so the item is filed — just wrong,
# invisibly to author and recipient alike (the E-0054 class; hit on X-0569). `--from-stdin` is the
# shell-proof escape (stdin bytes never reach the shell), and — exactly as on `task file` — it reads the
# WHOLE field set from the stdin mapping and never looks at argv, so a content-bearing argv flag passed
# ALONGSIDE it would be silently dropped. It FAILS CLOSED instead, naming the offending flag + the
# stdin key that carries it.
#
# (attr, cli_flag, stdin_key, absent_value) — every CONTENT-bearing `cross request` flag. The MODE
# flags carry no content and are deliberately excluded: `--from-stdin` selects this path, and
# `--force` is an authority override (the known-participant escape) that the stdin mapping does not
# carry — the same exclusion `task file` makes for --from-stdin/--skeleton.
STDIN_CONFLICTING_ARGV_FLAGS = (
    ("to",         "--to",         "to",         None),
    ("kind",       "--kind",       "kind",       None),
    ("brief",      "--brief",      "brief",      None),
    ("origin_fp",  "--origin-fp",  "origin_fp",  None),
    ("origin_ref", "--origin-ref", "origin_ref", None),
    # T-11747: the author-side card link is read from BOTH sources, so it belongs in the table like
    # every other field this verb accepts twice. Without the row a stdin payload plus an argv
    # `--task` would silently prefer one — and a link that landed from the wrong source is invisible
    # afterwards (the item is permanent, and nothing downstream can tell which id was meant).
    ("task",       "--task",       "task",       None),
)

# --- `cross close --from-stdin` × argv content-flag conflict (T-11582, X-1111) ---
# The AUTHOR's TERMINAL prose, and terminal is the whole point: once `cross close --withdraw --reason
# ...` appends, the text cannot be corrected, so a shell-eaten fragment is what every future reader
# gets. That is exactly what X-1111 cost (kupiclub, 2026-08-25): a retraction naming three verbs in
# backticks reached the log with all three gone, leaving a retraction that no longer says what it
# retracts — noticed only because bash happened to print three command-not-found lines.
#
# `--from-stdin` is the same shell-proof escape `cross request` and `work commit` already carry, and
# this is a THIRD CALLER of the shared `textutil.stdin_mapping_ingest`, never a third reader
# (CHARTER §P1 F1). One row per SOURCE of a value, not per field
# (lessons/mirroring-a-stdin-route-onto-a-verb-with-two-argv-sources.md): each of these five reaches
# `args` through exactly ONE long flag — no positional, no short alias — so five rows cover them and
# the two-signal scan does the rest. The `id` positional gets no row: it carries no prose and the
# stdin mapping does not carry it (the `task refuse` shape, whose `task` positional is excluded the
# same way). The MODE flags are excluded for the sibling's reason — they carry no content:
# `--from-stdin` selects this path, and `--withdraw` / `--out-of-band` select the terminal.
CLOSE_STDIN_CONFLICTING_ARGV_FLAGS = (
    ("reason",          "--reason",          "reason",          None),
    ("note",            "--note",            "note",            None),
    ("re_entry",        "--re-entry",        "re_entry",        None),
    ("re_entry_awaits", "--re-entry-awaits", "re_entry_awaits", None),
    ("no_re_entry",     "--no-re-entry",     "no_re_entry",     None),
)
PROSE_BEARING_CLOSE_FIELDS = ("reason", "note", "re_entry", "re_entry_awaits", "no_re_entry")
# T-11873: the same derivation for the closure mapping — its table's stdin-key column IS the set.
CLOSE_STDIN_RECOGNISED_KEYS = tuple(k for _a, _f, k, _d in CLOSE_STDIN_CONFLICTING_ARGV_FLAGS)

# --- degenerate `--brief` classification (T-11417, X-1071's general claim) ---
# `cross request` validated the PRESENCE of `--brief` and nothing about its CONTENT, so five items
# reached the receiver carrying either a bare severity word (X-1064, brief 'low') or a VERBATIM copy
# of their own `origin_fp` (X-1070, X-1074, X-1078, X-1089). Each is a permanent, well-formed,
# content-free item the receiver cannot act on and — worse — cannot distinguish from a deliberately
# terse one, so it costs a round-trip to find out there was never anything there.
#
# FAIL-CLOSED here, unlike the report-only capture WARN in `cmd_event` (cli.py). The postures differ
# because the ARTIFACTS differ: a `deviation_captured` is the author's own one-command reflex over
# their own journal (D-0035/D-0086 — never gated), while a cross item is a PERMANENT artifact
# ADDRESSED TO SOMEBODY ELSE. The author is present at the keystroke and re-issues in seconds; the
# receiver can never recover content that was never written.
#
# NARROW BY MEASUREMENT, not by intuition (the audit-pre RED on this task, absorbed mode-a): only
# shapes PROVEN degenerate refuse. Over the whole 1099-item coordination corpus the two refusing
# legs fire on exactly 10 items and every one is a bare word or a verbatim fp-repeat; a brief of 2-3
# words gets a report-only WARN instead, because a substantive short brief ("cross inbox crashes")
# is plausible and must not be rejected. That is the difference between a guard and an obstacle.
BRIEF_TERSE_WORDS = 4          # below this: report-only WARN (a plausible-but-thin brief)
def degenerate_brief(brief, origin_fp) -> tuple:
    """Classify a `--brief` for CONTENT. Returns `(verdict, reason)` where verdict is
    'refuse' | 'warn' | None (fine), and reason is the human sentence naming what fired.

    A NAMED classifier rather than an inline `if` in the verb: its calibration is an empirical claim
    over the real corpus (10 refused / 1 warned / 1088 untouched in 1099), and a test can only assert
    that claim against a function it can call. Pure — no I/O, no journal, no die."""
    b = str(brief or "").strip()
    fp = str(origin_fp or "").strip()
    if fp and b.lower() == fp.lower():
        return ("refuse", f"the brief is a VERBATIM copy of `origin_fp` ({fp!r}) — the item already "
                          f"carries that field, so the brief adds nothing the receiver did not have")
    words = b.split()
    if len(words) < 2:
        return ("refuse", f"the brief is a SINGLE token ({b!r}) — a bare word (a severity, a slug) is "
                          f"not a one-line WHAT, and the receiver cannot act on it or ask about it")
    if len(words) < BRIEF_TERSE_WORDS:
        return ("warn", f"the brief is {len(words)} words ({b!r}) — thin for a one-line WHAT")
    return (None, "")

# The PROSE-bearing `cross request` field — the one whose free text the shell can eat (ids and enums
# cannot carry a backtick meaningfully). Mirrors task.py#PROSE_BEARING_TASK_FIELDS.
PROSE_BEARING_REQUEST_FIELDS = ("brief",)
# T-11873: what `cross request --from-stdin` legitimately reads off the mapping. DERIVED from the
# conflict table's own stdin-key column rather than re-listed — that table already IS the enumeration
# of every field this verb accepts from both sources, so a field added there is recognised here with
# no second edit (the derivation discipline `textutil.classify_stdin_keys` documents).
REQUEST_STDIN_RECOGNISED_KEYS = tuple(k for _a, _f, k, _d in STDIN_CONFLICTING_ARGV_FLAGS)
# Non-terminal precedence (later in the requested→picked→done path wins when several are present).
_NONTERMINAL_RANK = {"requested": 0, "picked": 1, "done": 2}
# T-10636 — the non-terminal post-`requested` states in which an item is under a LIVE intake (someone
# holds it). A terminal item is settled, so a second intake of it is the `already_addressed` staleness
# case, not a concurrent double-pick.
_HELD_STATUSES = frozenset({"picked", "done"})

_ID_RE = re.compile(r"^X-(\d+)$")

# Prose-scanning sibling of `_ID_RE` (T-10816). `_ID_RE` is ANCHORED — it VALIDATES one whole id
# string (the allocation scan) and by design cannot find an id embedded in a human sentence. Rather
# than weaken that anchor, citation-scanning gets its own word-bounded token pattern; the two never
# share a call site.
_CITED_ID_RE = re.compile(r"\bX-\d{4,}\b")

# T-11747 — the AUTHOR-side `--task` link's shape. Anchored (`fullmatch`), not the prose-scanning
# posture of `_CITED_ID_RE` above: this value is an EXACT id the caller typed, and the fold's tie
# compares it to a card id by equality, so anything that is not exactly one id must REFUSE rather
# than be silently stored as an unmatchable string.
_TASK_LINK_RE = re.compile(r"T-\d{4,}")


# ── log read + fold ───────────────────────────────────────────────────────────────────────────

def _content_hash(event: dict) -> str:
    """Stable canonical-JSON sha256 — for union-merge dedup AND the conflicting-terminal tiebreak."""
    return hashlib.sha256(
        json.dumps(event, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# The event `data` keys that carry a participant id — the exhaustive canonicalization surface.
_PEER_KEYS = ("from", "to", "by")


def canonical_peer(name, aliases=None):
    """PURE — the ONE canonical id for a participant spelling (T-10260). `aliases` is {alias -> canonical}
    (registry KEY and checkout BASENAME both map onto the key). An UNREGISTERED name maps to ITSELF: never
    invented, never dropped — it stays addressable and stays visible to the unroutable WARN. A falsy name
    or a missing/None map is returned unchanged, so an unreadable registry degrades to the pre-T-10260
    basename behaviour rather than crashing a read."""
    if not name:
        return name
    return (aliases or {}).get(name, name)


def _canonicalize(event: dict, aliases) -> dict:
    """Rewrite an event's participant ids through `canonical_peer`. Returns the event UNCHANGED (same
    object) when nothing moves — so the no-aliases path allocates nothing and stays byte-identical."""
    data = event.get("data")
    if not aliases or not isinstance(data, dict):
        return event
    moved = {k: canonical_peer(data[k], aliases) for k in _PEER_KEYS
             if data.get(k) and canonical_peer(data[k], aliases) != data[k]}
    if not moved:
        return event
    return {**event, "data": {**data, **moved}}


class Events(list):
    """The event list `read_events` returns — a plain `list` PLUS one read-degrade attribute,
    `unparseable` (T-10844).

    A `list` SUBCLASS on purpose: ~30 call sites consume this return, and two of them PIN plain-list
    equality (`tests/test_t10260_cross_peer_identity.py` — `read_events(log) == raw`). Equality,
    `len`, iteration, indexing and slicing are all inherited unchanged, so the degrade rides along
    without touching a single consumer. It is a RETURNED signal, never a stored one: nothing is
    written, and the next read re-derives it.

    Why the attribute exists at all: the fold's LENGTH used to be its only observable, so a line
    truncated mid-JSON by a concurrent peer append made a coordination item vanish with NOTHING to
    compare the short count against.
    """

    __slots__ = ("unparseable",)

    def __init__(self, iterable=(), *, unparseable: int = 0):
        super().__init__(iterable)
        self.unparseable = unparseable


def unparseable_count(events) -> int:
    """How many lines the reader could not decode in the read that produced `events` — the ONE
    accessor every surface asks through. Tolerant by design (`getattr` default 0): a caller holding a
    hand-built plain list (a test fixture, a filtered comprehension) reads a clean 0 rather than
    raising, so adding a degrade surface can never break a consumer that never had one."""
    return getattr(events, "unparseable", 0)


def read_events(cross_log_path, aliases=None) -> Events:
    """Parse the `cross_*` events from the shared log via per-line json.loads (the SAME parser the
    journal uses — SPEC-0084 r4). Un-parseable / non-dict / non-`cross_*` lines are skipped (P5
    tolerance). Duplicate identical lines (union-merge) collapse by content-hash → idempotent fold.

    THE READ-DEGRADE (T-10844). Skipping an un-parseable line stays the behaviour — the store is
    append-only, union-merged and written CONCURRENTLY by several peers, so failing closed on one
    torn byte would wedge every reader out of the whole log. What changes is that the loss is now
    COUNTED and RETURNED (`Events.unparseable`) instead of vanishing: a fold over a damaged log is
    distinguishable from a fold over a clean one, and the read views render that as a loud
    report-only WARN. Only a DECODE failure counts as damage — a non-dict or non-`cross_*` line is
    the documented P5 tolerance for a shared log carrying other event types, not a torn write.
    Keeping the parser tolerant while each read SITE decides what the damage means is the discipline
    in `lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`.

    THE canonicalization choke point (T-10260 — §Peer identity): each event's `from`/`to`/`by` is
    rewritten through `aliases` BEFORE the content-hash dedup, so (a) everything downstream — `fold`,
    `_legality`, `_guard`, every view and pure helper — compares canonical to canonical with no
    `aliases` argument of its own, and (b) two semantically identical events that differ ONLY in peer
    spelling collapse into one (a strict improvement to the union-merge, not a new dedup mechanism).
    `aliases=None` → identity map → byte-for-byte the pre-T-10260 behaviour."""
    if not os.path.exists(str(cross_log_path)):
        return Events()          # every path returns Events — the attribute is always readable
    seen: set = set()
    out: list = []
    unparseable = 0
    with open(str(cross_log_path), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                unparseable += 1     # COUNTED, still skipped — never a raise, never a refusal
                continue
            if not isinstance(e, dict):
                continue
            if not str(e.get("type", "")).startswith("cross_"):
                continue
            e = _canonicalize(e, aliases)
            h = _content_hash(e)
            if h in seen:
                continue
            seen.add(h)
            out.append(e)
    return Events(out, unparseable=unparseable)


def known_participants_from_events(events, registry_peers, self_name) -> set:
    """The set of valid `--to` participant ids for `cross request` fail-closed validation (T-9587),
    derived from an ALREADY-READ event list: the registry-derived CANONICAL peers (INJECTED — the host
    reads registry.yaml and yields one canonical id per yitc_v2 project per §Peer identity; cross.py never
    reads the registry itself, identity-agnostic kernel module) UNION every participant already present in
    the shared log (any item's `from`/`to`) UNION self. The log-union lets a peer that is mid-conversation
    but not (yet) in the registry still be addressed; self is included so the membership test never
    collides with the prior to==self refusal. Takes the events (not a path) so the caller can derive this
    from the SAME under-lock read it uses for id allocation — closing the validate-then-append TOCTOU.

    The log-union USED to be the split's ratchet: once one bad spelling landed it was "known" forever and
    validation could never refuse it again. `events` now arrives canonicalized (`read_events`), so the
    union can no longer teach an alias — only a genuinely unregistered id survives it, and the unroutable
    WARN (`unroutable_rows`) is what surfaces those."""
    peers = set(registry_peers or ())
    for e in events:
        d = e.get("data") or {}
        for k in ("from", "to"):
            v = d.get(k)
            if v:
                peers.add(v)
    peers.add(self_name)
    return peers


def known_participants(cross_log_path, registry_peers, self_name, aliases=None) -> set:
    """Path-reading convenience wrapper over `known_participants_from_events` (reads the log, then folds
    the participant set). For callers without an already-read event list."""
    return known_participants_from_events(read_events(cross_log_path, aliases), registry_peers, self_name)


def _order_key(event: dict):
    """The FIXED TOTAL ORDER over an item's events (earliest ts, content-hash tiebreak) — the ONE
    ordering the fold's birth/terminal selection and the `cross show` chain both read by, so a rendered
    chain can never disagree with the status the fold derived from it."""
    return (event.get("ts") or "", _content_hash(event))


def _birth(evs: list):
    """The item's meta-establishing `cross_requested` (earliest in `_order_key`), or None for an orphan
    (no birth event → not a coordination item)."""
    reqs = [e for e in evs if e.get("type") == "cross_requested"]
    return min(reqs, key=_order_key) if reqs else None


def _legality(event: dict, kind, frm, to):
    """Is this non-birth protocol event legal for the item (rule 2/3)? → (accepted, why). The emitter
    ROLE must match the event's side (author=`from` / receiver=`to`) and the item KIND must permit the
    event. The SINGLE legality definition — the fold drops what this rejects, and `item_events` marks
    the same events DROPPED, so no second model can drift from it."""
    et = event.get("type")
    by = (event.get("data") or {}).get("by")
    ok_role = (by == frm) if et in AUTHOR_EVENTS else (by == to)
    if not ok_role and et == "cross_closed" and by == to:
        # T-11252 — THE ONE BOUNDED ROLE CARVE-OUT: the RECEIVER's ORPHAN-AUTHOR close. An item whose
        # author is not a real project is terminable by NOBODY (withdraw is author-only, reject needs
        # `picked|requested`, ack is `note`-only, a second `done` is a note-attach), so `cross_closed`
        # is ALSO legal from the receiver — measured on X-0905/X-0907/X-0909, filed by the phantom
        # sender `clone` (T-11171). Without this clause the verb would emit the event and the fold
        # would DROP it on `role`: the item stays `done` while every surface reports success.
        #
        # Require the marker POSITIVELY — `orphan_author is True` plus a non-empty STRING `note` —
        # the EXACT shape of the `out_of_band` clause below (isinstance-checked, never inferred from
        # an absence), so a receiver's orphan close never reads as an author-verified one.
        #
        # The fold's boundary is the MARKER, NEVER a registry lookup: this log is folded by MANY peers
        # whose registries differ, and a fold that consulted one would make status reader-dependent,
        # breaking the order- and reader-independence rule 2 exists to guarantee. The registry is read
        # on the WRITE side (`cmd_cross_close`), where it fails CLOSED.
        d = event.get("data") or {}
        note = d.get("note")
        if d.get("orphan_author") is True and isinstance(note, str) and note.strip():
            ok_role = True
    if not ok_role:
        return False, "role"
    if kind not in EVENT_KINDS.get(et, frozenset()):
        return False, "kind"
    # T-10954 — the fold-boundary discriminator for the one CONDITIONAL member of EVENT_KINDS.
    # `note` is legal for `cross_closed` in the OUT-OF-BAND MODE ONLY (SPEC-0085 §3 / SPEC-0086):
    # a note never reaches `done`, so the plain close can never apply to it. EVENT_KINDS alone is
    # too coarse to say that, and it is the defense-in-depth gate for a shared log that is
    # append-only and written by MANY peers' CLI versions — so the verb branch is not this
    # boundary. Require the marker POSITIVELY (present + a non-empty reason), never infer the mode
    # from an absence: a marker-less `cross_closed` on a note is dropped here exactly as a
    # wrong-kind event is, reusing the "kind" drop-reason rather than adding a vocabulary.
    if et == "cross_closed" and kind == "note":
        d = event.get("data") or {}
        reason = d.get("reason")
        # `isinstance(str)`, NOT `str(reason)`: coercing would render `[]` as the non-empty "[]" and
        # accept a malformed close. The log is JSON from many writers, so a non-string here is a
        # real shape, and a TEXTUAL reason is what the mode requires (audit-post pass-1 finding).
        if not (d.get("out_of_band") is True and isinstance(reason, str) and reason.strip()):
            return False, "kind"
    return True, None


def fold(events: list) -> dict:
    """Derive every item's status from the SET of its events by immutable id (rule 1) — ORDER-
    INDEPENDENT. The earliest-ts `cross_requested` establishes meta (kind/from/to/brief/origin_fp); a
    later event is DROPPED (rule 2 defense-in-depth) unless its emitter ROLE and the item KIND are both
    legal for it. Conflicting terminals resolve by a FIXED TOTAL ORDER (earliest ts, content-hash
    tiebreak) and surface `contested`. Returns {id: {id,kind,from,to,brief,origin_fp,status,
    contested,dropped[]}}."""
    by_id: dict = {}
    for e in events:
        iid = (e.get("data") or {}).get("id")
        if iid:
            by_id.setdefault(iid, []).append(e)

    out: dict = {}
    for iid, evs in by_id.items():
        req = _birth(evs)
        if req is None:
            continue   # orphan — no birth event, cannot derive meta (skip, not a coordination item)
        rd = req.get("data") or {}
        kind, frm, to = rd.get("kind"), rd.get("from"), rd.get("to")
        item = {"id": iid, "kind": kind, "from": frm, "to": to,
                "brief": rd.get("brief", ""), "origin_fp": rd.get("origin_fp"),
                "origin_ref": rd.get("origin_ref"),
                "actor": rd.get("actor"),   # T-10405 — the PERSON who authored it (birth meta; `from` is the project)
                "task": rd.get("task"),     # T-11747 — the AUTHOR's card link (`cross request --task`), birth meta
                "contested": False, "dropped": [], "held": None}
        terminals: list = []
        picks: list = []              # T-10636 — the ACCEPTED cross_picked events (the holder source)
        dones: list = []              # T-11423 — the ACCEPTED cross_done events (the disputable ones)
        disputes: list = []           # T-11423 — the ACCEPTED cross_disputed events (the author's no)
        nonterminal = {"requested"}   # the request itself
        for e in evs:
            et = e.get("type")
            if et == "cross_requested" or (et not in EVENT_STATUS
                                           and et not in NONSTATUS_PROTOCOL_EVENTS):
                continue   # already meta, OR a non-protocol cross_* (e.g. cross_refused — local-only)
            accepted, why = _legality(e, kind, frm, to)
            if not accepted:
                item["dropped"].append({"type": et, "by": (e.get("data") or {}).get("by"),
                                        "why": why})
                continue
            if et == "cross_disputed":
                disputes.append(e)
            elif et in TERMINAL_EVENTS:
                terminals.append(e)
            else:
                nonterminal.add(EVENT_STATUS[et])
                if et == "cross_picked":
                    picks.append(e)
                elif et == "cross_done":
                    dones.append(e)
        # T-11423 — the AUTHOR's negative verdict CANCELS the `done` it disproves. Resolved under the
        # SAME `_order_key` total order the terminals use (earliest ts, content-hash tiebreak), so the
        # outcome is a property of the event SET and cannot change with arrival order — the rule-2
        # invariant a naive "latest event wins" would break. LAST dispute vs LAST done, because the
        # pair alternates: dispute -> re-fix -> dispute again, and whichever is later governs. A
        # dispute with no `cross_done` at all (reachable only by a union-merged append, never by the
        # verb, which gates from `done`) simply discards a status that was never there — a no-op, not
        # an error. `picked` is untouched, so the item falls back to the receiver's court.
        if disputes and (not dones
                         or _order_key(max(disputes, key=_order_key))
                         > _order_key(max(dones, key=_order_key))):
            nonterminal.discard("done")
        if terminals:
            winner = min(terminals, key=_order_key)
            item["status"] = EVENT_STATUS[winner.get("type")]
            item["contested"] = len({e.get("type") for e in terminals}) > 1
        else:
            item["status"] = max(nonterminal, key=lambda s: _NONTERMINAL_RANK.get(s, -1))
        # T-10636 (X-0456) — the HOLDER of a picked item, derived from the EARLIEST accepted
        # `cross_picked` under the SAME `_order_key` total order the terminals use above (so `held` is
        # order-independent + deterministic, exactly like `status`). A DERIVED VIEW over the existing
        # event chain — no new store, no new event type, no FSM change (CHARTER §P1 F2). `task` is the
        # picker's resolving card when the payload carries one (the T-9399 auto-pick-on-file emits
        # `task: tid`; an explicit `cross pick` emits {id, by} only → None). None when never picked.
        # WHY: without it BOTH intake surfaces can refuse/skip a second intake but cannot NAME who holds
        # it — the X-0456 gap (two controllers intook X-0452 → duplicate cards T-0297 + T-0302).
        if picks:
            first = min(picks, key=_order_key)
            pd = first.get("data") or {}
            item["held"] = {"by": pd.get("by"), "ts": first.get("ts"), "task": pd.get("task")}
        out[iid] = item
    return out


def _next_id(events: list) -> str:
    """Next sequential `X-NNNN` join key — scanned from the existing `cross_requested` events. MUST be
    called UNDER the id-alloc lock + before the append in the same critical section (rule 4)."""
    mx = 0
    for e in events:
        if e.get("type") == "cross_requested":
            m = _ID_RE.match(str((e.get("data") or {}).get("id", "")))
            if m:
                mx = max(mx, int(m.group(1)))
    return f"X-{mx + 1:04d}"


# ── refusal (journal-observable, verb-design §3) ───────────────────────────────────────────────

def _refuse(local_append, die, item_id, verb: str, by: str, reason: str) -> None:
    """A role/state/kind guard refusal is journal-observable, NOT stderr-only: emit a `cross_refused`
    trace into the session's OWN journal (the `*_refused` open-catalog convention — read_gate_refused /
    claim_refused precedent) THEN exit nonzero. So a blocked cross-write is analyzable across sessions."""
    local_append("cross_refused", None,
                 {"id": item_id, "verb": verb, "by": by, "reason": reason})
    die(f"cross {verb} refused [{item_id}]: {reason}")


def _resolve_or_die(cross_log_path, item_id: str, die, *, events=None, aliases=None):
    """Fold-resolve `item_id` or fail closed. `events` lets a caller that ALREADY read the log (e.g.
    `cross show`, which also renders the chain) reuse that read instead of re-reading the file — that
    pre-read is already canonicalized, so `aliases` applies only to the self-read branch."""
    item = fold(read_events(cross_log_path, aliases) if events is None else events).get(item_id)
    if item is None:
        die(f"unknown coordination id: {item_id!r} (no cross_requested births it)")
    return item


def unresolved_cited_ids(text, items: dict, *, self_id: str) -> list:
    """PURE — the `X-NNNN` ids MENTIONED in a human string that do NOT exist in the folded log
    (T-10816). Deduped, in first-mention order.

    The re-file ordering hazard: an author whose `cross request` was REFUSED (and who missed the
    refusal) closes the superseded items with a note citing the replacement id — an id nothing ever
    allocated. The log is APPEND-ONLY, so that dangling citation is published to the peer and cannot
    be retracted. Answering "does this id exist?" from the SAME fold the verbs already resolve
    against is what makes the ordering safe by construction.

    `self_id` (the item being closed) is dropped: an item legitimately names itself in its own
    resolution note, and that is a self-reference, never a forward one."""
    seen, missing = set(), []
    for cid in _CITED_ID_RE.findall(text or ""):
        if cid == self_id or cid in seen:
            continue
        seen.add(cid)
        if cid not in items:
            missing.append(cid)
    return missing


# ── audit-packet evidence: a task-tied coordination item (T-10915, X-0695) ────────────────────────
# THE JOINT BREAKAGE these three PURE helpers close. The shared coordination store lives OUTSIDE every
# repo (SPEC-0084 rule 5) and the audit packet counts evidence from the repo journal (SPEC-0168 rule 1).
# Both designs are right; TOGETHER they make one class of card unprovable — a card whose acceptance
# PROBE **is** a filed coordination item. Its artifact provably exists in the store, the packet renders
# nothing, and the auditor honestly reports the criterion unmet (kupiclub X-0695, reported off X-0674).
#
# What this is NOT: it does NOT fold the store into `events.jsonl` (rule 5 stands — one store, outside
# the repos) and it does NOT widen SPEC-0168 rule 1's COUNTED set. A cross row can never land in THIS
# repo, so entering it into the rule-5 custody set would fire that check forever on a row unlandable by
# construction — the rule-5 mode (c) reader-set defect, verbatim. It is a SEPARATE rendered section.
#
# What it REUSES rather than re-inventing (CHARTER §P1 F1/F2):
#   * the TRIGGER shape of the T-10708 card-opt-in route — the tie is the audited card's OWN acceptance
#     text naming the artifact, and the fail-closed direction is "renders nothing", never "renders a
#     stranger's artifact";
#   * `_CITED_ID_RE`, the existing word-bounded prose scanner for `X-NNNN` (T-10816) — no second regex;
#   * `read_events`/`fold`, the existing store reader — no new store, no new parser, no new event;
#   * the SPEC-0168 rule-4 PROVENANCE shape — a row from outside the audit checkout carries a VISIBLE
#     mark naming its source and its not-in-the-journal status, and an empty tie renders NOTHING, so
#     the mark stays a real discriminator rather than an unconditional decoration.


def card_cited_item_ids(task: dict) -> list:
    """PURE — the `X-NNNN` ids the AUDITED CARD'S OWN `acceptance` text names, in first-mention order
    (T-10915). Reads the card only: no store, no journal, no fold.

    The exact sibling of `_card_named_event_types` (T-10708) one axis over: there the card names an
    event TYPE, here it names a coordination ITEM. Naming an id in prose renders nothing by itself —
    the caller ALSO requires the store to actually carry that item — so over-capture is inert by
    construction and the failure direction is always "renders nothing"."""
    acc = task.get("acceptance") or []
    if isinstance(acc, str):
        acc = [acc]
    seen, out = set(), []
    for cid in _CITED_ID_RE.findall(" ".join(str(a) for a in acc)):
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def card_tied_items(task: dict, items: dict) -> list:
    """PURE — the folded store items THIS card ties to, card-cited first, then filed-for (T-10915,
    extended T-11747).

    TWO TIE ROUTES, and the whole of them — both are a NAMED, deliberate link between one card and one
    item, never a proximity guess:
      (a) CARD → ITEM: the audited card's acceptance NAMES the item's id (T-10915). The INBOUND route:
          the item already existed when the acceptance was written.
      (b) ITEM → CARD: the item's own birth meta names this card (`cross request --task`, T-11747). The
          OUTBOUND route, and route (a) cannot serve it EVEN IN PRINCIPLE — a request filed in service
          of a card gets its id only after that acceptance is written, so the card can never name it in
          advance. Reported by kupiclub as X-1152 off T-0492, where a substantial request WAS filed, the
          packet rendered nothing, and the auditor correctly read the evidence as absent.
    Everything else is unchanged, including the failure direction. An item tied by NEITHER route is
    NEVER returned — an untied coordination artifact is some OTHER card's proof, and rendering it here
    would let any card claim the store's contents as its own evidence. An id the card names that the
    store does not carry yields nothing (fail-closed; `unresolved_cited_ids` is the surface that reports
    such a dangling citation), and an item naming a card the fold cannot see is simply not this card's.

    ORDER: cited first (route (a)'s first-mention order, byte-identical to the pre-change render for
    every card that uses only that route), then filed-for in the store's own id order. Deduped, so an
    item tied BOTH ways — a card that names in acceptance the very id it later filed with --task —
    renders exactly once, at its cited position."""
    items = items or {}
    cited = [cid for cid in card_cited_item_ids(task) if cid in items]
    tid = str(task.get("id") or "").strip()
    seen = set(cited)
    # Fail-closed on an id-less card: with no `tid` there is nothing to compare against, and an empty
    # string must never match an item whose `task` is likewise absent — hence the `tid and` guard AND
    # the strip-compare below, never a bare `it.get("task") == tid`.
    filed_for = [cid for cid in sorted(items)
                 if tid and cid not in seen
                 and str(items[cid].get("task") or "").strip() == tid]
    return [items[cid] for cid in cited + filed_for]


def card_evidence_section(items: list, store_path, events: list = None) -> str:
    """PURE — render task-tied coordination items as an auditor-facing evidence block with VISIBLE
    cross-instance provenance (T-10915, the SPEC-0168 rule-4 shape).

    Returns "" for an empty list, so a card that ties to nothing produces a packet BYTE-IDENTICAL to
    the pre-change one. That is the rule-4 discriminator property: the mark means something precisely
    because it is absent when there is nothing to mark.

    The header states the boundary OUT LOUD, because an auditor reading a row it cannot find in the
    diff or the journal would otherwise be right to distrust it: the store is deliberately outside
    every repo (SPEC-0084 rule 5), so these rows are NOT part of SPEC-0168 rule 1's counted/landable
    evidence set and can never appear in the shipped diff — their absence there is expected, never a
    finding.

    `events` (T-10981) — the SAME store events the caller already folded into `items`, passed in so
    each row can carry its RESOLUTION NOTE. Passed rather than read here for two reasons, both load-
    bearing: the note is NOT on the folded item (`fold` derives status/meta, never the note), and the
    note IS chain-derived — `resolution_note(item_events(...))`, the accepted-only reader `cross show`
    already prints. Reusing that ONE reader is what keeps the two surfaces from drifting; re-reading
    the store here would instead cost a second read and break this function's purity, and widening
    `fold` would grow a shared structure for a single reader. Optional (`None` ⇒ no note rendered), so
    every existing 2-arg caller stays byte-identical.

    WHY THE NOTE AT ALL (the defect this closes): a card whose acceptance is of the ordinary shape
    "close X-NNNN with a resolution note" had that note rendered NOWHERE in the packet, though the
    store carried it in full. The auditor saw done-with-no-note and refused — correctly, on what it
    could see (T-10975 burned two audit-post passes plus a non-converged consult on exactly this).
    The failure is SILENT by construction: the packet renders fine and the refusal reads as a card
    defect rather than a renderer one.

    NOT truncated: the section has no size discipline (`brief` renders in full on the same row), and a
    truncated note would risk re-creating this very blind spot — a note's operative clause is as often
    last as first. NOT `auto_note` either: T-10785/X-0618 separated the keys deliberately, `note` being
    the receiver's substantive return and `auto_note` machine provenance."""
    if not items:
        return ""
    lines = []
    for it in items:
        bits = [f"`{it.get('id')}` [{it.get('kind')}] {it.get('from')} → {it.get('to')}",
                f"status: {it.get('status')}"]
        if it.get("contested"):
            bits.append("CONTESTED (conflicting terminal events)")
        if it.get("origin_fp"):
            bits.append(f"origin_fp: {it.get('origin_fp')}")
        if it.get("origin_ref"):
            bits.append(f"origin_ref: {it.get('origin_ref')}")
        bits.append(f"brief: {it.get('brief')}")
        # CONDITIONAL exactly as origin_fp/origin_ref above: an item with no note renders no `note:`
        # bit at all. An unconditional append would emit a literal `note: None`, which is WORSE than
        # silence — it asserts to the auditor that no note exists when the reader simply never ran.
        note = resolution_note(item_events(events, it.get("id"))) if events else None
        if note:
            bits.append(f"resolution note: {note}")
        lines.append("- " + " — ".join(bits))
    return (
        "\n\nCROSS-INSTANCE EVIDENCE — TASK-TIED COORDINATION ITEM(S), SOURCED FROM THE SHARED STORE "
        "(T-10915 / SPEC-0168 rule 4):\n"
        f"source: {store_path} — the kernel-owned SHARED coordination log, deliberately OUTSIDE every\n"
        "repo (SPEC-0084 rule 5). These rows are NOT in this repo's `events.jsonl` and are NOT part of\n"
        "the counted/landable evidence set (SPEC-0168 rule 1); they can never appear in the shipped\n"
        "diff, and that absence is EXPECTED, never a finding.\n"
        "TIE: each row below is rendered because the audited card and the item NAME EACH OTHER — either\n"
        "the card's OWN acceptance text names the item's id (T-10915), or the item was FILED IN SERVICE\n"
        "of this card and carries its id (`cross request --task`, T-11747); either way the store must\n"
        "carry the item. An item tied by neither route is never rendered here. Read a row as evidence\n"
        "that the item exists and is linked to this card — NOT as evidence that its acceptance text\n"
        "named it, since the outbound route cannot work that way (the item's id postdates the card).\n"
        + "\n".join(lines)
    )


def _guard(local_append, die, item: dict, verb: str, by: str, *, role: str, kinds, from_states) -> None:
    """Refuse (journal-observably) unless the emitter ROLE, the item KIND, and the current STATE all
    permit `verb`. The three FSM axes (rule 2/3)."""
    expect = item["from"] if role == "author" else item["to"]
    if by != expect:
        _refuse(local_append, die, item["id"], verb, by,
                f"wrong-role: {verb} is {role}-only (expected {expect!r}, got {by!r})")
    if item["kind"] not in kinds:
        _refuse(local_append, die, item["id"], verb, by,
                f"bad-kind: {verb} illegal for kind={item['kind']!r} (legal: {sorted(kinds)})")
    if item["status"] not in from_states:
        _refuse(local_append, die, item["id"], verb, by,
                f"wrong-state: {verb} requires status in {sorted(from_states)} (current: {item['status']!r})")


# ── mirror-on-intake (SPEC-0085 rule 6) ─────────────────────────────────────────────────────────

# The captured_via tag marking a deviation_captured as a kernel intake mirror (not a first-hand capture).
MIRROR_VIA = "cross-intake-mirror"


def _mirror_on_intake(item: dict, local_append, *, is_kernel: bool) -> None:
    """SPEC-0085 rule 6 — at KERNEL intake of a `bugfix` (a `cross pick`), mirror the ORIGINATING
    deviation into the kernel's OWN journal, origin-linked, so ALL consumers' routed deviations
    accumulate in ONE journal and the EXISTING SPEC-0055/0056 triage/recurrence machinery clusters them
    with NO new cross-consumer sweep (P1 F1 reuse / F3). The three guardrails are upheld BY CONSTRUCTION:

      (a) the mirror carries the origin ref (`mirrored_from`) and is a plain append — never edited, never
          cited as canon; the consumer's deviation stays canonical. The ref is the originating
          events.jsonl SOURCE ref the author supplied VERBATIM (`origin_ref`, the rule-6
          `<consumer>/events.jsonl#<id>` locator) — mandatory for a bugfix at request time, so the mirror
          is never a synthetic / non-verbatim locator (audit-pre absorbed).
      (b) recurrence counts by ORIGIN-IDENTITY: the mirror's `fingerprint` IS the origin fingerprint, so
          the existing _scan_captures/_capture_fingerprint_counts cluster item + mirror under one identity
          and count it ONCE (the coordination item lives in the shared cross log, NOT events.jsonl, so it
          is never itself a second capture). `fingerprint` is used for RECURRENCE only; the stable source
          ref lives in `mirrored_from`. No idempotency scan: re-pick is FSM-blocked, and two distinct
          filings of one deviation are genuine recurrence (N≥2), which triage wants (P1 F4 — no mechanism
          without an incident).
      (c) the mirror is a `deviation_captured` in the LOCAL events.jsonl, NEVER a `cross_*` event in the
          shared log — so the fold (which reads only `cross_*` from the shared log) can NEVER surface it
          in any inbox/outbox view or let it drive a coordination item's status/closure. Triage-analytics
          ONLY, structurally — not a flag that could be forgotten.

    KERNEL-INTAKE ONLY: a `bugfix` is the project→kernel case (SPEC-0085 §3), so its receiver is the
    kernel — but the mirror must land in the KERNEL journal, so it is gated on `is_kernel` (the host's
    REPO_ROOT == ENGINE_ROOT). A non-kernel picker mirrors NOTHING (it would otherwise pollute its own
    journal, not the single kernel journal the rule accumulates into). No-op also for any non-`bugfix`
    kind or a bugfix with no `origin_fp` (nothing to mirror)."""
    if not is_kernel or item.get("kind") != "bugfix":
        return
    origin_fp = (item.get("origin_fp") or "").strip()
    origin_ref = (item.get("origin_ref") or "").strip()
    if not origin_fp or not origin_ref:
        return   # defensive — a well-formed bugfix carries both (enforced at `cross request`)
    local_append("deviation_captured", None, {
        "fingerprint": origin_fp,
        "mirrored_from": origin_ref,
        "captured_via": MIRROR_VIA,
        "cross_id": item["id"],
        "relates_to": item.get("brief", ""),
    })


# ── land-time auto-file of already-classified kernel-bound deviations (X-0042 / SPEC-0085 §3) ────
# The consumer-friction cadence (patterns/error-friction-tracking.md §CADENCE step-3) makes the
# kernel hand-off work WITHOUT the owner for items the agent ALREADY classified kernel-bound. The
# marker is REUSED, not re-derived — NO new auto-classifier (answers X-0037's hard part): a deviation
# the session already tagged `relates_to:kernel` + `target:<kernel>` IS the consumability signal. Only
# that subclass auto-fires (not every idea), and the file is IDEMPOTENT (dedup by origin fingerprint).

DEVIATION_REALM_KEY = "realm"
DEVIATION_REALM_KERNEL = "kernel"

# The one lexical probe (T-10248): does a free-text aspect NAME the kernel realm? Used ONLY to WARN on
# a near-miss — never to route. Routing off a prose match is exactly what SPEC-0085 §3 forbids for the
# dangling-resolved advisory ("prose is overloaded"); the same fence applies here.
_KERNEL_WORD_RE = re.compile(rf"\b{DEVIATION_REALM_KERNEL}\b", re.IGNORECASE)


def deviation_realm(data: dict) -> str:
    """PURE — the deviation's ENUMERATED realm: the ROUTABLE half of what `relates_to` used to carry
    alone (T-10248 / X-0253). `relates_to` is free text (a CHARTER failure-class id and/or a prose
    aspect; one consumer repo carries 50+ distinct values), so an exact match on it silently dropped
    every kernel-shaped deviation worded as prose. The realm now lives in its own key, whose vocabulary
    is the SPEC-0073 `PLACEMENT_REALMS` enum validated host-side at capture (`cmd_event`) — this module
    stays identity-agnostic and only needs to know WHICH realm routes.

    LEGACY fallback: a pre-split capture (and the pre-split session-start echo) put the bare token
    `kernel` in `relates_to`. That exact value always WAS the realm, so it is read as one — the same
    equality the old predicate ran, relocated. Prose is NEVER re-interpreted into a realm: no new
    classifier (the X-0042 marker semantics are reused, not re-derived).

    Returns "" when no realm is declared. Tolerant of non-dict / missing keys (never raises)."""
    if not isinstance(data, dict):
        return ""
    realm = str(data.get(DEVIATION_REALM_KEY, "") or "").strip()
    if realm:
        return realm
    legacy = str(data.get("relates_to", "") or "").strip()
    return DEVIATION_REALM_KERNEL if legacy == DEVIATION_REALM_KERNEL else ""


def is_kernel_bound_deviation(data: dict, kernel_name: str) -> bool:
    """PURE — True iff this deviation_captured `data` was ALREADY classified kernel-bound by the
    session: enumerated `realm == "kernel"` AND `target == <kernel_name>` (the X-0042 marker, REUSED —
    no new classifier). Both halves required: the realm is the aspect-free classification, `target`
    names the routed peer. Tolerant of a non-dict / missing keys (returns False — never raises in the
    land path)."""
    if not isinstance(data, dict):
        return False
    return deviation_realm(data) == DEVIATION_REALM_KERNEL \
        and str(data.get("target", "")).strip() == kernel_name


def existing_cross_origin_fps(events: list) -> set:
    """The set of `origin_fp`s ALREADY carried by coordination items (folded by id) — the idempotent
    dedup source for the land-time auto-file. Folds ALL items (incl. terminal): an already-filed
    deviation must not re-file even after its item closed/withdrew (a re-file would be a duplicate)."""
    # inloop-journal-read: one-shot — the outermost comprehension iterable, evaluated exactly once.
    return {it.get("origin_fp") for it in fold(events).values() if it.get("origin_fp")}


# ── Auto-routed brief budget (T-10272) ───────────────────────────────────────────────────────────
# The auto-routed brief used to be a bare `[:200]` slice: it severed X-0240/X-0241/X-0250/X-0251/
# X-0252 mid-word in the shared log, so the ASK was absent and kernel triage had to open each
# consumer's origin_ref journal to learn what was being requested. The shared log is meant to be
# self-sufficient. The cap is not removed, though — the shared-log append rides
# `events.append_event`, whose MAX_EVENT_BYTES (3500 = PIPE_BUF 4096 minus margin, SPEC-0002) keeps a
# single-line append atomic under concurrent flock-serialized writers. That elision loop rescues only
# a `text` payload key; a `brief` is never salvaged and no error is raised, so an unbounded brief
# would silently emit an over-cap line. The bound is therefore kept, raised far above real briefs,
# and made self-describing (word boundary + ellipsis + a see-origin_ref pointer).
#
# The budget is in ENCODED BYTES, not characters: UTF-8 reaches 4 bytes per character (non-BMP), so a
# character budget cannot bound the line. 2000 bytes of brief + a bounded origin_ref (below) + the
# cross_requested envelope and sibling keys (id/from/to/kind/origin_fp/ts/session_ref — a few hundred
# bytes) + JSON escaping stays under 3500 with margin. 2000 also clears the largest observed real
# brief (X-0257, hand-filed, 996 chars), so a full-length brief still passes through untouched.
#
# MAX_EVENT_BYTES is cited by name, never imported: this module is the identity-agnostic stdlib-only
# kernel module (SPEC-0073 bin/ HARD class) and must not back-import `events`. The cross-module
# relationship is pinned by the test, which may import both.
BRIEF_MAX_BYTES = 2000

# ONE bound, two sites: the emitted `origin_ref` payload field AND the locator displayed inside the
# truncation pointer. Bounding it is what makes the body budget below positive by construction rather
# than by a hoped-for floor.
_ORIGIN_REF_MAX_BYTES = 200

# The LAST whitespace run in a string: the only position whose following characters are all non-space
# through the end. `re.search` returns the first such position, which is by construction the last
# whitespace. Any whitespace, not just " " — a brief broken by newlines or tabs is still word-cuttable.
_LAST_WS_RE = re.compile(r"\s(?=\S*\Z)")


def _byte_head(text: str, nbytes: int) -> str:
    """The leading `nbytes` UTF-8 bytes of `text`, never splitting a codepoint (errors="ignore" drops
    a trailing partial sequence). Mirrors the proven `events.py` idiom — duplicated across a
    deliberate module boundary that exists precisely to forbid importing it (see BRIEF_MAX_BYTES)."""
    if nbytes <= 0:
        return ""
    return text.encode("utf-8")[:nbytes].decode("utf-8", "ignore")


def _truncate_brief(text: str, origin_ref: str) -> str:
    """PURE — bound an auto-routed brief to BRIEF_MAX_BYTES, cutting on a WORD boundary and appending
    an explicit ellipsis + a see-origin_ref pointer, so a reader of the shared log learns both that
    the text was cut and exactly where the full text lives.

    A brief already within budget is returned UNCHANGED — no ellipsis, no pointer where none is
    needed. That passthrough is the differential half of the contract, not an optimization. "Unchanged"
    is byte-identical to the TRIMMED input: surrounding whitespace is stripped first, the same
    normalization the `[:200]` slice this replaces always applied. The strip is inherited, not
    introduced — dropping it would alter the brief of every live input.

    Post-condition, for EVERY input (incl. non-BMP text and a pathological origin_ref):
        len(result.encode("utf-8")) <= BRIEF_MAX_BYTES."""
    s = (text or "").strip()
    if len(s.encode("utf-8")) <= BRIEF_MAX_BYTES:
        return s
    # The displayed locator is bounded, so the suffix is bounded (~250 bytes), so the body budget is
    # positive by construction — no arbitrary floor, no starved body.
    ref = _byte_head(origin_ref or "", _ORIGIN_REF_MAX_BYTES)
    suffix = f"… [truncated — full text at {ref}]" if ref else "… [truncated]"
    head = _byte_head(s, BRIEF_MAX_BYTES - len(suffix.encode("utf-8")))
    # Cut back to the last whitespace: a word boundary, not a severed word. An unbroken token (no
    # whitespace at all) keeps the hard byte cut — nothing better exists, and the pointer still
    # carries the ask.
    ws = _LAST_WS_RE.search(head)
    body = (head[:ws.start()] if ws else head).rstrip()
    return f"{body}{suffix}" if body else suffix.lstrip()


def _deviation_origin_ref(event: dict, self_name: str) -> str:
    """The REAL originating journal locator for a folded deviation_captured event (SPEC-0085 rule 6 —
    a verbatim `<consumer>/events.jsonl#<id>` SOURCE ref, never a synthetic fp-keyed string). Prefer
    the event's OWN `source_ref` when the capture recorded one; else derive the stable ts-locator over
    the consumer's journal (`events.jsonl#ts=<ISO>` — the recovery-search-order convention), which
    points at the ACTUAL captured line. The fingerprint remains the dedup join key (origin_fp), never
    the locator (rule 6: provenance LINK, not the join key).

    BOUNDED at _ORIGIN_REF_MAX_BYTES (T-10272): this value is emitted as a payload field AND embedded
    in a truncated brief's pointer, so an unbounded one would breach the event-line budget. An
    over-long `source_ref` is NOT truncated — a cut locator resolves to nothing, strictly worse than
    the alternative — it is SUBSTITUTED by the derived ts-locator, the second form rule 6 already
    sanctions. Every real ref (tens of bytes) is far under the bound and passes through verbatim."""
    src = str(event.get("source_ref") or "").strip()
    if src and len(src.encode("utf-8")) <= _ORIGIN_REF_MAX_BYTES:
        return src
    ts = str(event.get("ts") or "").strip()
    derived = f"{self_name}/events.jsonl#ts={ts}" if ts else f"{self_name}/events.jsonl"
    # Final backstop: a pathological self_name/ts. No locator resolves at that point anyway, so the
    # line-budget invariant is what remains worth protecting.
    return _byte_head(derived, _ORIGIN_REF_MAX_BYTES)


def kernel_deviations_to_file(deviation_events: list, existing_origin_fps, self_name: str,
                              kernel_name: str) -> list:
    """PURE — given the folded deviation_captured events of a land, the cross-request payloads to
    auto-file: kernel-bound (is_kernel_bound_deviation), NOT the kernel's own land (self==kernel never
    routes to itself), deduped vs `existing_origin_fps` AND within this batch (idempotent). Each
    payload reuses the bugfix-routing shape (SPEC-0085 §3): brief + origin_fp + the REAL origin_ref
    (the captured line's own source_ref, or the ts-locator over the consumer journal — never a
    synthetic fp string, rule 6). Returns them in input order. A kernel-bound deviation with no
    `fingerprint` is skipped (no dedup key).

    The brief is bounded by `_truncate_brief` (T-10272): within budget it passes through
    byte-identical; over budget it is cut on a word boundary and carries an ellipsis + a pointer at
    the origin_ref, so the shared log stays self-sufficient instead of stopping mid-word."""
    if self_name == kernel_name:
        return []
    out: list = []
    seen = set(existing_origin_fps or ())
    for e in deviation_events:
        if not isinstance(e, dict):
            continue
        data = e.get("data") or {}
        if not is_kernel_bound_deviation(data, kernel_name):
            continue
        fp = str(data.get("fingerprint", "")).strip()
        if not fp or fp in seen:
            continue
        seen.add(fp)
        # origin_ref first: it is an input to the truncation pointer now, and the payload field and
        # the pointer must carry the identical bounded locator (one computation, one value).
        origin_ref = _deviation_origin_ref(e, self_name)
        # DEFERRED, not module-level: `journal` is not on cross.py's eager import set, and a
        # top-level import here would widen every traced dependency set that reaches this module for
        # one helper (the T-11540 per-test verify-cache keying reason; same call shape as
        # journal.py's own deferred `from lib import error`). `sys.modules` makes the repeat cost nil.
        from lib import journal   # noqa: PLC0415 — deliberate, see above
        # T-11890: the ONE reader-owned capture-content accessor, replacing this reader's own
        # finding-then-impact choice. The preference is PRESERVED, not overridden — the accessor skips
        # an `untriageable_impact` (a bare severity word), which is precisely the 237 measured rows
        # shaped `{"impact": "low", "finding": "<the prose>"}` this reader was right about. What it
        # gains is every other alias key, which this reader silently read as empty.
        raw = str(journal.capture_content(data) or fp)
        brief = _truncate_brief(raw, origin_ref) or fp
        out.append({"brief": brief, "origin_fp": fp, "origin_ref": origin_ref})
    return out


# T-10752 (X-0599 / SPEC-0085): the CLOSED disposition vocabulary a `deviation_resolved` carries —
# the third leg of the silencer's audit trail, alongside `resolved_by` (who) and `evidence` (proof).
# It names WHICH of the three legitimate ways a near-miss signal already travelled, so a permanently
# muted SAFETY warning is auditable after the fact:
#   routed-by-hand — the CONTENT reached the kernel by another route (hand-filed as a cross item
#                    under its own id/fingerprint), so the origin_fp dedup could never match it;
#   not-kernel     — run to ground and judged genuinely project-realm (the shape-3 prose match was
#                    the false positive);
#   already-fixed  — the kernel problem is SHIPPED (the capture predates the fix that closed it).
# CLOSED by construction: a free-text disposition is un-auditable — nobody could later separate
# "we filed it elsewhere" from "we judged it not ours", which is exactly the accountability gap
# X-0599 measured (5 rows dispositioned by hand, 5 with nowhere to record the conclusion). The
# followup family's `open -> promoted | dropped` is the named-state analog (CHARTER §P1 F1).
# READ-SIDE UNAFFECTED: `resolved_deviation_fps` below still silences on `fingerprint` alone, so
# every already-landed resolving event keeps silencing — this vocabulary is a WRITE-side contract
# (validated in `cmd_event`), never a reader migration.
DEVIATION_DISPOSITIONS = ("routed-by-hand", "not-kernel", "already-fixed")


def resolved_deviation_fps(events: list) -> set:
    """PURE — the set of deviation fingerprints marked resolved by a governed `deviation_resolved`
    journal event (T-10453 / X-0317). A fingerprint-keyed RESOLVING event is the ONLY silencer of a
    verified-stale near-miss WARN row: a near-miss whose kernel problem is since FIXED (or no longer
    relevant) would otherwise re-WARN on every land forever — routing it would file a bogus kernel ask,
    not routing it is permanent noise. FAIL-CLOSED by construction: this gathers ONLY explicit resolving
    events; an UNRESOLVED row is NEVER aged out — there is no time window, only an explicit fingerprint
    silences. The fingerprint is the same origin_fp join key used everywhere in this module. Tolerant of
    a non-dict / missing key (skipped, never raises in the land path)."""
    out: set = set()
    for e in events:
        if not isinstance(e, dict) or e.get("type") != "deviation_resolved":
            continue
        data = e.get("data") or {}
        if not isinstance(data, dict):
            continue
        fp = str(data.get("fingerprint", "")).strip()
        if fp:
            out.add(fp)
    return out


def kernel_near_miss_deviations(deviation_events: list, existing_origin_fps, self_name: str,
                                kernel_name: str, resolved_fps=None) -> list:
    """PURE — the folded deviations that LOOK kernel-bound but do NOT route: the near-miss WARN set
    (T-10248 / X-0253). Before the realm split, a kernel-shaped deviation whose marker was one half
    short was skipped SILENTLY at `kernel_deviations_to_file`, while the session-start echo advertised
    the reflex as automatic — so a capture believed delivered was dropped. These rows make that
    non-silent. REPORT-ONLY: a near-miss is never routed (nothing is auto-mutated onto the shared log
    off a prose match — the SPEC-0085 §3 dangling-resolved fence).

    Three shapes, first match wins:
      1. realm IS kernel but `target` is absent/other  — declared the realm, missed the peer.
      2. `target` IS the kernel but realm is absent/other — addressed the peer, missed the realm.
      3. realm is not kernel (absent OR explicitly another realm) and the free-text aspect NAMES the
         kernel — the reported class ("kernel: dispatch-status reader…"). An explicit non-kernel realm
         is NOT exempt: realm-says-project + prose-says-kernel is a contradiction (CHARTER §P7), and
         exempting it would re-open the silent drop this function exists to close.

    Guards mirror `kernel_deviations_to_file` exactly: the kernel's own land never warns about itself,
    and an already-cross-filed deviation (by origin fingerprint) is not re-warned — nor is one warned
    twice within a batch. A deviation with no fingerprint has no dedup key, so it warns on every land
    until its marker is fixed (it can never route either — that is the point).

    `resolved_fps` (T-10453 / X-0317) is the governed stale-dismiss silencer set — fingerprints marked
    resolved by a `deviation_resolved` event (`resolved_deviation_fps`). A resolved fingerprint is
    treated exactly like an already-filed one (added to `seen`), so the verified-stale row drops from the
    WARN. FAIL-CLOSED: only an explicit resolving event silences — a fingerprintless near-miss still has
    no dismiss key and warns until its marker is fixed."""
    if self_name == kernel_name:
        return []
    out: list = []
    seen = set(existing_origin_fps or ())
    seen |= set(resolved_fps or ())
    for e in deviation_events:
        if not isinstance(e, dict):
            continue
        data = e.get("data") or {}
        if not isinstance(data, dict) or is_kernel_bound_deviation(data, kernel_name):
            continue                                   # routes → not a miss
        fp = str(data.get("fingerprint", "")).strip()
        if fp and fp in seen:
            continue                                   # already filed, or already warned this batch
        realm = deviation_realm(data)
        aspect = str(data.get("relates_to", "") or "")
        target = str(data.get("target", "")).strip()
        if realm == DEVIATION_REALM_KERNEL:
            reason = f"realm:kernel but target:{target or '(unset)'} — expected target:{kernel_name}"
        elif target == kernel_name:
            reason = f"target:{kernel_name} but realm:{realm or '(unset)'} — expected realm:kernel"
        elif _KERNEL_WORD_RE.search(aspect):
            reason = (f"aspect names the kernel but realm:{realm or '(unset)'} — "
                      f"set realm:kernel + target:{kernel_name} to route it")
        else:
            continue
        if fp:
            seen.add(fp)
        out.append({"reason": reason, "fingerprint": fp, "aspect": aspect.strip()[:120],
                    "origin_ref": _deviation_origin_ref(e, self_name)})
    return out


def unregistered_self_refusal_reason(self_name, kernel_name, registry_peers):
    """PURE — why THIS checkout must not auto-file into the shared store, or None when it may (T-11177).

    The incident (2026-08-15, reproduced under T-11171): a throwaway COPY of a governed repo landed at
    a directory named `clone`, `_cross_self()` fail-softed that unregistered basename to itself, and
    `auto_file_kernel_cross_requests`' only guard — `self_name == kernel_name` — does not survive a
    rename. The copy carried the ORIGIN's events.jsonl verbatim, so the kernel's own deviations were
    re-filed as a phantom consumer's: 20 rows into an append-only store shared by every project, 15 of
    which read as live peer requests and burned a controller triage pass. They cannot be taken back.

    This is NOT a new posture — it is the T-10338 asymmetry (WRITE-side fail-CLOSED on an unresolvable
    identity, READ-side fail-SOFT) extended to the one write path it never reached. T-10338 covered the
    unreadable-registry case on the INTERACTIVE `cross request`; the land-time AUTO-file was the hole.
    `_cross_self()` is deliberately NOT touched: read-side softness is decided behaviour (T-10260 /
    X-0259), and guarding here keeps `cross inbox`/`outbox`/session-start working in a legitimate
    ad-hoc checkout instead of refusing.

    WHY THE EMPTY SET ALSO REFUSES (the 'cannot tell' case — registry missing, unreadable, or empty).
    The asymmetry between the two errors is total. A wrong REFUSAL is cheap and self-healing: the
    auto-file is idempotent by origin_fp and retried at every land, so the row files itself once the
    registry reads again. A wrong FILE is PERMANENT — the store is append-only, so it can only be
    withdrawn, never retracted. So an unconfirmable identity refuses.

    Returns None (MAY file) when: the name is falsy; self IS the kernel (the pre-existing
    short-circuit, semantics unchanged — the kernel never routes to itself); `registry_peers` is None;
    or self is in the peer set. `registry_peers=None` is the LEGACY call shape — a caller that has not
    wired the check keeps the pre-T-11177 behaviour rather than silently refusing; the production
    caller always passes the set."""
    if not self_name or self_name == kernel_name:
        return None
    if registry_peers is None:
        return None
    if not registry_peers:
        return (f"this checkout's identity ({self_name!r}) cannot be confirmed — the registry lists no "
                f"yitc_v2 projects (missing, unreadable, or empty). Refusing to auto-file into the "
                f"append-only shared store on an unconfirmable identity; the auto-file is idempotent "
                f"and retries at the next land once the registry reads (T-11177)")
    if self_name not in registry_peers:
        return (f"{self_name!r} is not a registered yitc_v2 project, so this checkout is not the peer "
                f"its directory name claims — most likely a COPY or clone of a governed repo carrying "
                f"the ORIGIN's journal. Refusing to auto-file its deviations into the append-only "
                f"shared store as a phantom peer; register the project to enable this (T-11177)")
    return None


def auto_file_kernel_cross_requests(*, deviation_events, cross_log_path, lock_path, self_name,
                                    kernel_name, cross_emit, registry_peers=None) -> list:
    """Land-time auto-file (X-0042): for each folded kernel-bound deviation not already cross-filed,
    allocate an id + append `cross_requested` (kind=bugfix, to=kernel) under the SAME id-alloc flock
    critical section cmd_cross_request uses (rule 4 — no read-max-then-append race). REUSES the cross
    mechanism — no new write path. DEDUP is idempotent: a re-land of the SAME deviation files nothing
    (origin_fp already on the log). Returns the filed ids (empty list = nothing to file).

    T-11177: refuses entirely when this checkout's identity is not registry-confirmed — see
    `unregistered_self_refusal_reason` for the incident and the fail-closed rationale. The refusal
    lands BEFORE `ensure_shared_store`, so a phantom peer never even creates or chmods the store (the
    ordering T-11171's own E2 belt test pins). It is REPORT-ONLY and never raises: this runs in the
    `land` tail, and aborting would break `land` in every legitimate unregistered ad-hoc checkout —
    the very class the read-side fail-soft exists to protect."""
    refusal = unregistered_self_refusal_reason(self_name, kernel_name, registry_peers)
    if refusal is not None:
        # Surfaced, never silent — the T-10547 posture already used in this module: stderr, never
        # blocking. A silently-skipped auto-file would be indistinguishable from having nothing to file.
        sys.stderr.write(f"yitc-v2: land: kernel-bound cross auto-file REFUSED — {refusal}\n")
        return []
    if self_name == kernel_name:
        return []
    filed: list = []
    # T-10806: the store + its lock are created with the multi-uid modes (SPEC-0084 r1) — this
    # REPLACES the raw lock-dir makedirs, which left both at the caller's umask.
    ensure_shared_store(cross_log_path, lock_path)
    lock_fd = lockfile.open_flock_target(lock_path)   # never truncating, cross-user safe (X-0226)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)                # one critical section for the whole batch
        # T-11439 — ONE read of the shared log for the whole batch. This loop used to re-read and
        # re-parse the ENTIRE coordination log once PER FILED ITEM, because `_next_id` is a scan-max
        # and each `cross_emit` below appends the very row the NEXT allocation must see. Hoisting the
        # read alone would hand every item the same id; hoisting it TOGETHER with an in-memory append
        # of what we just allocated is exact. `_next_id` reads nothing but `type == "cross_requested"`
        # and `data.id`, so a row carrying exactly those two fields is indistinguishable to it from
        # the one `cross_emit` wrote, and LOCK_EX means this loop is the sole writer for its duration
        # — no other appender can exist to be missed. Same in-batch accumulate shape as the
        # `existing.add(fp)` already used by the sibling escalation loop below.
        log_events = read_events(cross_log_path)          # ONE read for the whole batch, under the lock
        existing = existing_cross_origin_fps(log_events)
        payloads = kernel_deviations_to_file(deviation_events, existing, self_name, kernel_name)
        for p in payloads:
            nid = _next_id(log_events)                     # scan-max UNDER the lock, over the hoisted read
            cross_emit("cross_requested", {
                "id": nid, "from": self_name, "to": kernel_name, "kind": "bugfix",
                "brief": p["brief"], "origin_fp": p["origin_fp"], "origin_ref": p["origin_ref"]})
            log_events.append({"type": "cross_requested", "data": {"id": nid}})   # what the next `_next_id` must see
            filed.append(nid)
    finally:
        os.close(lock_fd)   # releases the flock — identical to the prior `with open(...)` close
    return filed


def concern_drift_escalation_fp(to: str, concern: str, current: str) -> str:
    """The STABLE dedup fingerprint for a concern-drift escalation (SPEC-0143 Rule 4). Keyed on
    (consumer, concern, current-registry-version): re-running the nightly files NOTHING while the drift
    is unresolved (same fp already on the log), and a LATER contract move (new `current`) yields a NEW fp
    → a fresh escalation. Mirrors the origin_fp dedup of auto_file_kernel_cross_requests (no new dedup
    mechanism)."""
    return f"concern-drift:{to}:{concern}:{current}"


def auto_file_concern_drift_escalations(*, escalations, cross_log_path, lock_path, self_name,
                                        cross_emit) -> list:
    """Nightly-time escalation auto-file (SPEC-0143 Rule 4): for each drift on a concern that a
    PRE-EXISTING governed blocking gate already blocks on (the caller's gate-backed filter), allocate an
    id + append ONE `cross_requested` (kind=note, to=consumer) under the SAME id-alloc flock critical
    section cmd_cross_request uses (rule 4 — no read-max-then-append race). REUSES the cross mechanism
    verbatim (the auto_file_kernel_cross_requests analog) — NO new write path, NO stored review-request
    entity, NO new blocking gate (the report-only reconcile stays the default for every other concern).
    DEDUP is idempotent by the concern_drift_escalation_fp origin_fp: a re-run of an unresolved drift
    files nothing; a version move re-escalates. `escalations` is a list of
    {to, concern, current, adopted, reason}. Returns the filed ids (empty = nothing to file)."""
    filed: list = []
    if not escalations:
        return filed
    # T-10806: the store + its lock are created with the multi-uid modes (SPEC-0084 r1) — this
    # REPLACES the raw lock-dir makedirs, which left both at the caller's umask.
    ensure_shared_store(cross_log_path, lock_path)
    lock_fd = lockfile.open_flock_target(lock_path)   # never truncating, cross-user safe (X-0226)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)                # one critical section for the whole batch
        # T-11439 — ONE read for the whole batch, exactly as in the sibling loop above (the exactness
        # argument is stated there and is not restated here).
        log_events = read_events(cross_log_path)          # ONE read for the whole batch, under the lock
        existing = existing_cross_origin_fps(log_events)
        for e in escalations:
            to = str(e.get("to") or "").strip()
            concern = str(e.get("concern") or "").strip()
            current = str(e.get("current") or "").strip()
            if not (to and concern and current) or to == self_name:
                continue                                   # a self-addressed or malformed drift never escalates
            fp = concern_drift_escalation_fp(to, concern, current)
            if fp in existing:
                continue                                   # already escalated for this (consumer, concern, version)
            adopted = e.get("adopted") or "none"
            brief = (f"[concern-drift] {concern} moved (current={current}, {to} adopted={adopted}, "
                     f"{e.get('reason')}) — a pre-existing governed gate blocks on this concern; review "
                     f"+ re-adopt/waive/na (SPEC-0143 Rule 4).")
            nid = _next_id(log_events)                     # scan-max UNDER the lock, over the hoisted read
            cross_emit("cross_requested", {
                "id": nid, "from": self_name, "to": to, "kind": "note",
                "brief": brief, "origin_fp": fp})
            log_events.append({"type": "cross_requested", "data": {"id": nid}})   # what the next `_next_id` must see
            existing.add(fp)                               # in-batch dedup (two projects, same fp — impossible, but cheap)
            filed.append(nid)
    finally:
        os.close(lock_fd)   # releases the flock — identical to the prior `with open(...)` close
    return filed


# ── receiver-side auto cross-done + intake hygiene (T-9362, SPEC-0085 §3 / SPEC-0086) ────────────
# The RECEIVER half of the cross cadence (pairs with the T-9353 author-side auto-file at land). A task
# carries a STRUCTURED link (`resolves_cross: [X-NNNN]`) to the coordination item(s) it resolves; at
# `task close` the receiver auto-emits `cross_done` for each linked item, so a shipped fix never leaves
# its cross request dangling (the manual-reconcile class). At `cross pick` an intake-hygiene pre-check
# REFUSES a stale pick (a DONE local task already resolves it) and SURFACES a not-actionable-for-this-
# side item, so no side re-picks already-addressed or irrelevant work (the duplicate-intake class).
# Cadence home: patterns/error-friction-tracking.md §CADENCE step-3.


def resolution_note_for_close(task: dict, tid: str):
    """PURE — the resolution PROVENANCE text derived from the resolving task (T-10496, X-0356), or None
    when the task carries too little to say anything (never a blank note). The ONE emitter of this
    wording — both auto-`cross_done` paths (`_auto_cross_done_for_close` at task close, and the land-side
    `_auto_cross_done_for_landed_closes` that reuses it) go through it, so the note cannot drift between
    them (the `premise_review_cue` single-emitter precedent).

    WHY it exists: the manual `cross done --note` (T-10273) let a receiver say WHAT they did, but the
    AUTO-emit carried `{id, by, task}` only — so an auto-resolved item reached its author note-less
    (X-0346 / X-0351 arrived bare; boomrocket filed X-0356 on exactly this) and the author had to re-ask.
    The task card already HOLDS the answer (its title + the closing commit), so the note is DERIVED at
    emit time — no new field, no new store, nothing for a receiver to remember to type.

    THE EXCLUSION CLAUSE (T-11764, X-1179). A fix can resolve the reported CLASS while structurally
    failing to reach the reported INSTANCE, and until now the derived note could not say so: it read as
    a plain resolution either way. Measured on the shared log — X-1124's `cross_done` (2026-08-27T16:19:34Z)
    carried only `auto_note=resolved by T-11670: ...`, although the fix was fail-closed on a carrier the
    reporting record predated and could never reach it. The requester read that as resolved, unparked the
    card, re-claimed it and spent an external auditor invocation before the guard correctly refused; they
    then had to write the divergence themselves, on their OWN close, after paying for it (X-1179).
    So the resolving card may DECLARE the limitation in `resolution_excludes` (SPEC-0028) and this one
    emitter appends it — the exclusion is DECLARED, never inferred from prose (the SPEC-0095 discipline
    the re-entry guard rests on: a machine that guesses at reach would guess wrong in the fail-open
    direction). NOT a new obligation on the common case: a card that omits the field emits the identical
    note it emits today, so an ordinary closure gains no ceremony to describe the rare one. It rides
    `auto_note` with the rest of the derived text — never `note`, the receiver's own-words slot (T-10785).
    THE HONEST BOUND: this makes a KNOWN limitation legible, it cannot discover an unknown one — a
    resolver who has not realized their fix excludes the reporter still closes silently. What it removes
    is the case where the resolver KNEW (T-11670's own session did) and the surface had nowhere to say it."""
    if not isinstance(task, dict):
        return None
    title = str(task.get("title") or "").strip()
    if not title:
        return None                       # nothing substantive to say → emit no note at all (never blank)
    commit = str(task.get("commit") or "").strip()
    note = f"resolved by {tid}: {title}"
    note += (f" (commit {commit})" if commit else "")
    excludes = str(task.get("resolution_excludes") or "").strip()
    if excludes:
        note += f" — DOES NOT REACH: {excludes}"
    return note


def cross_done_for_close(item: dict, self_name: str, *, task: dict = None, tid: str = None):
    """PURE — the `cross_done` payload the RECEIVER should auto-emit when closing a task that resolves
    `item`, or None when not applicable (idempotent + fail-open). cross_done is FSM-legal ONLY
    for the RECEIVER (`by == item.to`) from the `picked` state (SPEC-0085 rule 2/3), so the auto-emit
    fires EXACTLY there: self must be the receiver AND the item must be `picked`. Every other case —
    self is the author, the item is still `requested` (never picked), already `done`, or terminal —
    returns None (skip, never a duplicate, never raises). The host emits the returned payload directly
    under the cross-log append (REUSING the cross mechanism, like the T-9353 land auto-file bypasses
    cmd_cross_request); the FSM legality the verb's _guard would check is upheld BY CONSTRUCTION here.

    The RESOLVING TASK (`task` + its `tid`) is OPTIONAL context (T-10496): given, the payload carries the
    receiver's `task` provenance AND the derived text (resolution_note_for_close above). Omitted, the
    payload is the bare `{id, by}` it always was — so a caller without a task in hand is unchanged.

    THE DERIVED TEXT RIDES `auto_note`, NEVER `note` (T-10785 / X-0618). It used to land on `note` — the
    receiver's SUBSTANTIVE-return slot (`_NOTE_KEYS`) — and since this emit fires at LAND, the generated
    one-liner always got there FIRST and the resolver's real return then had nowhere to go: the slot was
    taken and `cross done` refused a second emit. Both sides read a completed handoff while the payload
    was silently truncated (X-0616 had to re-deliver a whole trial return as its OWN item; X-0620 asked
    for that re-delivery; X-0622 was it). So the two are SEPARATED at the key: `auto_note` is machine-
    derived PROVENANCE (rendered by `cross show` as `auto-resolution:`), `note` stays the receiver's own
    words. T-10496/X-0356 is fully preserved — an auto-resolved item still never reaches its author bare,
    it just says so on the provenance line instead of squatting the return slot."""
    if not isinstance(item, dict):
        return None
    if item.get("to") != self_name:
        return None                       # not the receiver → cross_done is wrong-role (skip)
    if item.get("status") != "picked":
        return None                       # only picked → done is FSM-legal (idempotent for done/terminal)
    payload = {"id": item["id"], "by": self_name}
    if tid:
        payload["task"] = tid             # the receiver's resolving task (provenance)
        note = resolution_note_for_close(task, tid)
        if note:
            payload["auto_note"] = note   # DERIVED provenance — never `note`, the receiver's return slot
    return payload


def cross_pick_for_file(item: dict, self_name: str):
    """PURE — the symmetric MIRROR of cross_done_for_close (T-9399): the `cross_picked` payload {id, by}
    the RECEIVER should auto-emit when FILING a task that resolves `item`, or None when not applicable
    (idempotent + fail-open). cross_picked is FSM-legal ONLY for the RECEIVER (`by == item.to`) from the
    `requested` state and ONLY for a PICKABLE kind (`task`/`bugfix` — mirror cmd_cross_pick's kinds
    guard), so the auto-emit fires EXACTLY there: self must be the receiver, the item EXACTLY `requested`,
    and the kind pickable. Every other case — self is the author, a non-pickable `note` (which CAN sit at
    `requested`, unlike a closed-side item — so the status check alone is not enough), the item already
    `picked`/`done`/terminal — returns None (skip, never a duplicate, never raises). The host emits the
    returned payload directly under the cross-log append (REUSING the cross mechanism, like the close-side
    cross_done_for_close); the FSM legality the verb's _guard would check is upheld BY CONSTRUCTION here."""
    if not isinstance(item, dict):
        return None
    if item.get("kind") not in EVENT_KINDS["cross_picked"]:
        return None                       # only task/bugfix are pickable → a note pick is wrong-kind (skip)
    if item.get("to") != self_name:
        return None                       # not the receiver → cross_picked is wrong-role (skip)
    if item.get("status") != "requested":
        return None                       # only requested → picked is FSM-legal (idempotent otherwise)
    return {"id": item["id"], "by": self_name}


def intake_advisories(item: dict, self_name: str, *, resolved_by=None) -> list:
    """PURE — the intake-hygiene advisories for a `cross pick`, computed BEFORE the FSM guard (T-9362):
      - "already_addressed" — `resolved_by` names a DONE local task that already resolves this item (a
        shipped fix / the resolves_cross link IS the "fix already landed" evidence). The host resolves
        it deterministically (the first done resolver task by id); naming ANY done resolver is sufficient.
      - "not_for_this_side" — the item is addressed to a DIFFERENT peer (`item.to != self_name`), so it
        is not actionable for this side (the relevance signal; the FSM _guard then refuses it wrong-role).
      - "already_held" (T-10636 / X-0456) — the item is ALREADY under a live intake: it carries a `held`
        holder (the fold's derived earliest-`cross_picked` view) AND its status is a non-terminal
        post-`requested` state (`picked`/`done`). A SETTLED item (terminal) is excluded — it is the
        `already_addressed` case above, not a concurrent double-intake. This is the datum that names WHO
        holds it, so a second concurrent intake is visible instead of silent (two controllers both intook
        X-0452 → duplicate cards T-0297 + T-0302).
    Order-stable (staleness → relevance → holding), tolerant of a non-dict item (returns [])."""
    if not isinstance(item, dict):
        return []
    out: list = []
    if resolved_by:
        out.append("already_addressed")
    if item.get("to") != self_name:
        out.append("not_for_this_side")
    if item.get("held") and item.get("status") in _HELD_STATUSES:
        out.append("already_held")
    return out


def describe_holder(item: dict) -> str:
    """PURE — render an item's `held` view as a human line naming WHO holds it, WHEN they picked it, and
    under WHICH task (when known). The ONE renderer both intake surfaces share (`cmd_cross_pick`'s
    refusal + the `task file` already-linked advisory), so the holder wording cannot drift between them —
    the `premise_review_cue` single-emitter precedent. Returns "" when there is no holder."""
    held = (item or {}).get("held") if isinstance(item, dict) else None
    if not held:
        return ""
    who = held.get("by") or "an unknown peer"
    when = held.get("ts") or "an unrecorded time"
    task = held.get("task")
    return f"{who} at {when}" + (f" under task {task}" if task else " (no resolving task recorded)")


def unanswered_cross_link_advice(xid: str, item, self_name: str) -> "str | None":
    """PURE — the WARN line for a `resolves_cross` link that will NOT be answered when this task
    closes, or None when the link is fine (it will auto-answer, or it is already settled). T-11183.

    WHY (X-0943, measured by social-scraper on three items in one session): the close-side auto-emit
    `cross_done_for_close` fires ONLY when self is the receiver AND the item is EXACTLY `picked`. So
    PICKED is the discriminator — an UNPICKED linked item is silently never answered. The T-9399
    file-side auto-pick covers the happy path, but every case IT declines is silent except the
    T-10636 `already_held` one: a non-pickable `note` kind, a wrong-role link, and a non-`ready`
    filing all skip with no signal at all. Their three items stayed `[note/requested]` after the
    resolving task landed done, `cross pick` then REFUSED them naming that same done task, and
    `cross show` printed `task: (none)` — three surfaces, three different answers about one item.
    Their PICKED pair auto-closed correctly, which is what isolates PICKED as the cause.

    THE ORACLE IS `cross_done_for_close` ITSELF, not a re-derived copy of its conditions — so this
    advisory and the emit it warns about can never drift apart (if the close-side ever learns to
    answer a new state, this warn goes quiet for it in the same commit, by construction).

    THE KIND AXIS IS LOAD-BEARING (the trap this exists to avoid): a `note` can NEVER take
    `cross_done` — `EVENT_KINDS["cross_done"]` is `{task, bugfix}` and `EVENT_KINDS["cross_acked"]`
    is `{note}`, so its ONLY receiver terminal is `cross ack`. Advising a note-holder toward
    `cross pick` / `cross done` would name a command the verb REFUSES, which is worse than no warn.
    The advice is therefore computed FROM the item's kind, never from a single canned string.

    REPORT-ONLY by construction: this returns text. It emits no event, changes no state, and its
    caller never gates on it — gating a card on a peer-log state is CHARTER non-goal #7."""
    if cross_done_for_close(item, self_name) is not None:
        return None                       # it WILL auto-answer at close — nothing to warn about
    head = f"WARN: {xid} is linked by this card but will NOT be answered when it closes"
    tail = "(report-only — the filing succeeded, T-11183/SPEC-0086)"
    if not isinstance(item, dict):
        return (f"{head}: it is not in the coordination log at all. Check the id — a typo'd or "
                f"withdrawn X-id links to nothing. {tail}")
    kind = item.get("kind") or "unknown-kind"
    status = item.get("status") or "unknown-status"
    if status in TERMINAL_STATUSES or status == "done":
        return None                       # already answered/settled — nothing is left dangling
    where = f"[{kind}/{status}]"
    if item.get("to") != self_name:
        # Wrong ROLE: the close-side auto-emit is receiver-only, so this side never answers it.
        if item.get("from") == self_name:
            return (f"{head} {where}: {self_name} is the AUTHOR here, not the receiver — the "
                    f"close-side auto `cross_done` is receiver-only. The peer answers it; you "
                    f"terminate it with `yitc-v2 cross close {xid}` once you have verified their "
                    f"fix. {tail}")
        return (f"{head} {where}: it is addressed to {item.get('to') or 'an unrecorded peer'}, not "
                f"to {self_name} — neither side of it is yours to answer. Drop the "
                f"--resolves-cross link if this card is genuinely separate. {tail}")
    # Receiver side, non-terminal, yet the close-side emit declined → the kind or the status is why.
    if kind not in EVENT_KINDS["cross_done"]:
        return (f"{head} {where}: a `{kind}` item can never take `cross_done` (legal kinds are "
                f"{', '.join(sorted(EVENT_KINDS['cross_done']))}) — its receiver terminal is "
                f"`yitc-v2 cross ack {xid}` (add `--note <what you did>` to return a result on it). "
                f"{tail}")
    return (f"{head} {where}: the close-side auto `cross_done` fires only from `picked`, and this "
            f"item is `{status}`. Run `yitc-v2 cross pick {xid}` — then closing this card answers "
            f"it automatically. {tail}")


def print_unanswered_cross_link_warns(xids, items, self_name: str, *, skip=()) -> list:
    """Print one WARN per `resolves_cross` link that will not be answered at close, and return the
    ids warned about. The ONE print site for `unanswered_cross_link_advice` (the
    `print_premise_review_cue` / `describe_holder` single-emitter precedent, so the wording cannot
    drift across surfaces). T-11183.

    `skip` carries the ids a caller has ALREADY reported through another advisory in the same
    breath — today the T-10636 already-linked (`already_held`) lines, which name the holder and say
    strictly more about that id than this warn could. One filing must not double-signal one item.

    Order-preserving + de-duped over `xids`; tolerant of a missing/odd `items` fold."""
    warned: list = []
    skipped = {str(x).strip() for x in (skip or [])}
    seen: set = set()
    for raw in (xids or []):
        # Self-defend on the SHAPE, not on a distant caller's invariant (`cmd_task_file` validates
        # resolves_cross members to X-NNNN, but this helper must not rely on that). A non-string
        # member is dropped silently — `str(None)` is the truthy "None", which would otherwise print
        # a warn about an id that does not exist.
        if not isinstance(raw, str):
            continue
        xid = raw.strip()
        if not xid or xid in seen or xid in skipped:
            continue
        seen.add(xid)
        line = unanswered_cross_link_advice(xid, (items or {}).get(xid), self_name)
        if line:
            print(line)
            warned.append(xid)
    return warned


def premise_review_cue(xids, self_name: str, *, is_consumer: bool = False) -> "str | None":
    """PURE — the receiver-side premise-review CUE line (T-10439, SPEC-0086 rule 7), or None when there
    is nothing being taken in (empty ids). The ONE emitter both intake surfaces share — `cmd_cross_pick`
    and the `task file` resolves_cross association — so the wording cannot drift between them (the
    `_warn_unlinked_cross` single-emitter precedent).

    The intake advisories above check the request's SHAPE (already-addressed / not-for-this-side); NOTHING
    checked its central CLAIM against the receiver's CURRENT state — X-0297 arrived with a factually-
    outdated claim (the parity it asked for was already fixed) and only ad-hoc Controller discipline
    caught it.

    CUE + POINTER ONLY (SPEC-0005 §8): the line names the DISCIPLINE and points at its one home; it does
    NOT restate the four outcomes' rule-text. An aid that restated them would be a second home for the
    rule → drift the moment SPEC-0086 rule 7 changes. Report-only — it never gates a pick or a filing."""
    ids = [str(x).strip() for x in (xids or []) if str(x).strip()]
    if not ids:
        return None
    return (f"premise review (report-only, SPEC-0086 rule 7): verify the central claim of "
            f"{', '.join(ids)} against {self_name}'s CURRENT state before accepting — the request text is "
            f"the FROZEN original ask, not current state. Outcomes (incl. the requester-visible reframe "
            f"duty): `{graph_lib.spec_query_hint('SPEC-0086', is_consumer=is_consumer, cli='yitc-v2')}`")


def print_premise_review_cue(xids, self_name: str, *, is_consumer: bool = False) -> None:
    """Print the premise-review cue, or NOTHING when there is no intake to review. The single print
    site for both surfaces (see `premise_review_cue`)."""
    line = premise_review_cue(xids, self_name, is_consumer=is_consumer)
    if line:
        print(line)


# ── verbs ──────────────────────────────────────────────────────────────────────────────────────

# ── Premature availability announcement (T-11388, X-1048) ────────────────────────────────────────
# The narrow target is an announcement of AVAILABILITY — «this is shipped, go run it» — NOT coordination
# in general. A deviation capture, a question, a reframe and an ordinary note must stay untouched: the
# no-worktree coordination path exists so the capture reflex stays ONE command (D-0049), and a fix that
# taxes that reflex is worse than the defect it closes.
#
# There is no ENUMERATED half to route on here (the sibling rule for `relates_to` — SPEC-0085 §3): an
# availability claim exists only as PROSE in `brief`. So this is a bounded phrase list, deliberately
# NOT an NLP model and NOT a negation-aware parser — it recognises the assertive shapes the incident
# produced and says out loud, in the WARN it feeds, that a differently-worded announcement escapes it.
_AVAILABILITY_CLAIM_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\b(?:is|are|it'?s)\s+now\s+(?:shipped|live|landed|available|delivered|in\s+place|in\s+main)\b",
    r"\bnow\s+(?:shipped|live|landed|available)\b",
    r"\b(?:is|are)\s+(?:shipped|landed)\b",
    r"\b(?:has|have)\s+(?:shipped|landed)\b",
    r"\bjust\s+(?:shipped|landed)\b",
    r"\bnow\s+ships\b",
    r"\bhas\s+been\s+shipped\b",
))


def availability_claim_findings(brief) -> list:
    """PURE — the AVAILABILITY-CLAIM phrases a coordination brief asserts, in order of appearance
    (deduplicated, lowercased). Empty list = the brief does not read as «this deliverable is now
    available»; that is the answer for a deviation capture, a question, a reframe and an ordinary
    note, which is exactly why the WARN this feeds cannot reach them.

    HONEST BOUND, and it is the rule not a caveat: this is a HEURISTIC over prose. A silent result is
    NOT proof the brief makes no availability claim — it means none of the bounded phrases matched.
    The WARN says so to its reader rather than implying a guarantee it cannot give (the posture the
    sibling shell-substitution WARN already sets in this verb).

    No I/O, no state, no event. Fail-open by construction: a non-string input yields []."""
    text = str(brief or "")
    if not text:
        return []
    spans = []
    for rx in _AVAILABILITY_CLAIM_RES:
        spans.extend((m.start(), m.end(), " ".join(m.group(0).split()).lower())
                     for m in rx.finditer(text))
    # The phrase set OVERLAPS by design (a narrow shape and a broader one may both match the same
    # words), so report the WIDEST match per position and drop anything CONTAINED in an already-kept
    # span: a reader must see one phrase per claim, not the same claim spelled two ways.
    spans.sort(key=lambda t: (t[0], -(t[1] - t[0])))
    kept, out = [], []
    for start, end, phrase in spans:
        if any(start >= ks and end <= ke for ks, ke in kept):
            continue
        kept.append((start, end))
        if phrase not in out:
            out.append(phrase)
    return out


def premature_announcement_warning(nid: str, brief, unlanded_claim) -> "str | None":
    """PURE — the report-only WARN text for a premature availability announcement, or None.

    Fires ONLY on the CONJUNCTION: (i) the sending session HOLDS AN UNLANDED WRITING CLAIM
    (`unlanded_claim`, host-derived and injected — None whenever that cannot be established, so an
    undecidable read is SILENT, never an accusation) AND (ii) the brief READS AS AN AVAILABILITY
    announcement. Either alone is silent: a claim-holding session filing an ordinary note is the
    normal, protected case (AC2), and an announcement filed with no live claim is the post-land case
    that must pass unchanged (AC3).

    The text NAMES the branch, the task id it carries and how far ahead of `main` it is, so the author
    can act instead of guessing (AC4)."""
    if not unlanded_claim:
        return None
    hits = availability_claim_findings(brief)
    if not hits:
        return None
    branch = str(unlanded_claim.get("branch") or "").strip() or "(unknown branch)"
    tid = str(unlanded_claim.get("task") or "").strip()
    ahead = unlanded_claim.get("ahead")
    ahead_txt = (f"{ahead} commit(s) `main` does not have"
                 if isinstance(ahead, int) and ahead > 0 else
                 "nothing of it is on `main`")
    land_cue = (f"bin/yitc-v2 land --task {tid}" if tid
                else f"bin/yitc-v2 land --branch {branch}")
    return (
        f"WARN: {nid} is filed, but it reads as an announcement of AVAILABILITY and this session "
        f"HOLDS AN UNLANDED CLAIM — branch `{branch}`"
        + (f" (task {tid})" if tid else "") + f", {ahead_txt}.\n"
        f"  matched: " + "; ".join(f"{h!r}" for h in hits) + "\n"
        f"  A worktree is INVISIBLE to `main` until `land` fast-forwards it, so a peer who acts on "
        f"this now measures an ABSENCE and audits your source. Measured instance (X-1041 / X-1048, "
        f"2026-08-21): announced 04:05:33Z, landed 07:56:52Z — the consumer ran the verb it was told "
        f"to run 43 minutes before the deliverable existed, found nothing, and spent an init run, a "
        f"source audit and a cross request measuring the gap.\n"
        f"  If this announcement depends on that branch: `{land_cue}` FIRST, then re-file it. If it "
        f"does not, ignore this line — nothing was refused and {nid} stands as filed.\n"
        f"  NOT a guarantee (this is a heuristic over prose, not a gate): an availability claim worded "
        f"outside the matched set is NOT detected — silence here is not proof the brief makes none.\n")


def cmd_cross_request(args: argparse.Namespace, *, cross_log_path, lock_path, self_name,
                      cross_emit, die, registry_peers=None, no_team_receivers=None,
                      aliases=None, actor=None, unlanded_claim=None) -> str:
    """`cross request` — the AUTHOR verb. Allocates the immutable id under flock + atomically appends
    `cross_requested` INSIDE the same critical section (rule 4 — no read-max-then-append race).

    `registry_peers` (INJECTED — host-resolved, T-9587) is the set of CANONICAL ids of the registry's
    yitc_v2 projects. When provided (production), `--to` is FAIL-CLOSED-validated against the known
    participants (registry ∪ log ∪ self) so a misaddressed item cannot be silently folded by no one; an
    unknown peer is REFUSED with the closest 'did you mean' suggestion unless `--force` (a genuinely-new
    not-yet-registered peer). When None (legacy/test path) the membership check is skipped.

    `--to` is CANONICALIZED before the self-check, the validation and the append (T-10260), so addressing
    a peer by its checkout basename or by its registry key both write the ONE canonical id. That is what
    keeps the alias a normalization rather than a second addressable name (§Peer identity), and it is why
    the self-check below cannot be evaded by spelling self the other way.

    `no_team_receivers` (INJECTED — host-resolved, T-10697/X-0547) is the set of CANONICAL ids of
    REGISTERED projects that can NEVER process a cross intake — no yitc_v2 session and no active AI team
    (team_mode/ai_team both off). Addressing one is a guaranteed DEAD-LETTER (it stays non-terminal
    forever; only the author's own withdraw can dispose of it). When `--to` resolves to such a receiver we
    print a REPORT-ONLY WARN naming the risk + the host-infra routing hint AND let the request SUCCEED —
    never a gate (CHARTER non-goal #7): a no-team project may still be a legitimate FYI-note target, but
    the author must SEE the risk. Independent of the membership check + `--force` (both concern identity,
    not intake-capability). When None (legacy/test path) the WARN is skipped.

    `unlanded_claim` (INJECTED — host-resolved, T-11388/X-1048) describes the writing claim this
    session HOLDS but has not landed ({"branch", "task", "ahead"}), or None when there is none / it
    cannot be established. It feeds ONLY the third report-only WARN below — never a gate, never the
    stored item; None means SILENCE, so an undecidable git read never accuses (the fail-safe direction
    for a signal that describes what a session did, not one that guards an action)."""
    # T-10719 (E-0054): the shell-proof INGEST fork. `--from-stdin` carries the WHOLE field set as a
    # YAML mapping, so a backticked identifier in `brief` reaches the log intact; argv stays the
    # default. Only the SOURCE of the five raw values differs — everything below (kind enum, self-check,
    # canonicalization, the bugfix origin requirements, the membership check) is the ONE downstream
    # path both modes share, so the stdin escape can never become a second, weaker validator.
    if getattr(args, "from_stdin", False):
        # T-11873: through the SHARED `textutil.stdin_mapping_ingest`, like every sibling. This block
        # used to hand-roll the identical refuse→parse→shape-check with its OWN copy of the conflict
        # wording — a second definition site of a paragraph that must not drift from the one the
        # sibling `cross close` (:2418 below) prints. `carries="the WHOLE field set"` reproduces the
        # subject of that sentence exactly; its closing clause becomes the shared helper's ("drop
        # --from-stdin and pass it on argv" rather than "…and file entirely from argv") — the same
        # instruction, and the price of having ONE of these paragraphs instead of three.
        fields = textutil.stdin_mapping_ingest(
            args, STDIN_CONFLICTING_ARGV_FLAGS, stdin_text=sys.stdin.read(), die=die,
            carries="the WHOLE field set",
            recognised=REQUEST_STDIN_RECOGNISED_KEYS, argv_dests=set(vars(args)),
            verb="cross request")
        raw_to = fields.get("to")
        raw_kind = fields.get("kind")
        raw_brief = fields.get("brief")
        raw_origin_fp = fields.get("origin_fp")
        raw_origin_ref = fields.get("origin_ref")
        raw_task = fields.get("task")                 # T-11747 — the author-side card link
        # T-11417 (X-1089, ACCEPTED as written): SHOW THE CALLER WHAT WAS ACTUALLY READ. `--from-stdin`
        # is shell-proof against SUBSTITUTION *within* a payload, but it is not proof against
        # substitution of the WHOLE payload — a redirect from a fixed `/tmp/<generic-name>` on a
        # multi-user host can hand this verb another session's file, complete and well-formed, and no
        # verb can tell (the measured X-1086 instance: a foreign `fix(T-11352)` message arrived at
        # `task commit` by exactly this route). Nothing here DETECTS a swap — the parsed fields are
        # simply echoed back before the record, so a swap is VISIBLE to the one party who can
        # recognise it. Kernel-side half only; it does not replace per-invocation `mktemp` on the
        # author side, which is the actual remedy for the collision.
        # STDERR, not stdout: this verb RETURNS the allocated id on stdout and callers capture it in
        # `$(...)`, so a witness line there would corrupt the very thing it is meant to protect.
        # BEFORE every validation below, so the echo appears even when the next line REFUSES — a
        # refusal is exactly when the caller most needs to see what the verb read.
        def _shown(v) -> str:                      # bounded, and it SAYS when it cut (never a silent clip)
            t = str(v).strip()
            return t if len(t) <= 200 else t[:200] + "… [echo truncated; full text is recorded]"
        _echo = "; ".join(f"{k}={_shown(v)!r}"
                          for k, v in (("to", raw_to), ("kind", raw_kind), ("brief", raw_brief),
                                       ("origin_fp", raw_origin_fp), ("origin_ref", raw_origin_ref))
                          if str(v or "").strip())
        print(f"cross request --from-stdin: parsed capture -> {_echo or '(no fields parsed)'}\n"
              f"  Read that back before trusting it: these are the values THIS verb will record. If "
              f"they are not what you wrote, your stdin carried another payload (a fixed /tmp path is "
              f"a cross-session collision surface — use `mktemp` per invocation).", file=sys.stderr)
    else:
        raw_to, raw_kind, raw_brief = args.to, args.kind, args.brief
        raw_origin_fp = getattr(args, "origin_fp", None)
        raw_origin_ref = getattr(args, "origin_ref", None)
        raw_task = getattr(args, "task", None)        # T-11747 — the author-side card link

    kind = str(raw_kind or "").strip()
    if kind not in CROSS_KINDS:
        die(f"--kind must be one of {list(CROSS_KINDS)}")
    to = canonical_peer(str(raw_to or "").strip(), aliases)
    if not to:
        die("--to <peer> required")
    if to == self_name:
        die(f"--to must be a PEER, not self ({self_name})")
    validate_to = registry_peers is not None and not bool(getattr(args, "force", False))
    brief = str(raw_brief or "").strip()
    if not brief:
        die("--brief required (one-line what)")
    # T-11417 (X-1071's general claim): PRESENCE was the whole check; content was never looked at.
    # Classifier + calibration live at `degenerate_brief` above; this is only the wiring of its two
    # verdicts — refuse (proven degenerate) and a report-only WARN (thin but plausible).
    _brief_verdict, _brief_reason = degenerate_brief(brief, raw_origin_fp)
    if _brief_verdict == "refuse":
        die(f"--brief carries nothing triageable: {_brief_reason}. The brief is the ONE field the "
            f"receiver reads to decide whether to act, and a cross item is PERMANENT and addressed "
            f"to somebody else — nobody downstream can recover content that was never written, and a "
            f"content-free item is indistinguishable from a deliberately terse one. Write the "
            f"one-line WHAT: what is broken/needed, where, and what it cost you. The fingerprint, "
            f"the origin ref and the kind are separate fields — the brief must not repeat them. "
            f"(Long or shell-hostile prose: pass the whole field set as a YAML mapping via "
            f"`--from-stdin`.) Nothing was filed.")
    if _brief_verdict == "warn":
        print(f"yitc-v2: WARN --brief {_brief_reason} — accepted, but the receiver acts on this line "
              f"alone. Say what is broken/needed, where, and what it cost (filed anyway).",
              file=sys.stderr)
    origin_fp = str(raw_origin_fp or "").strip()
    origin_ref = str(raw_origin_ref or "").strip()
    # T-11747 (X-1152) — the OPTIONAL author-side card link, validated FAIL-CLOSED on shape. Optional
    # because most requests serve no card; fail-closed because the tie is an EQUALITY against a card
    # id, so a malformed value would store quietly and match nothing forever — the exact silent-miss
    # class this card exists to remove. Existence of the card is deliberately NOT checked: the store
    # is shared and the card lives in a repo the reader may not have (SPEC-0084 rule 5), so shape is
    # the only thing checkable from here without reaching across a project boundary.
    task_link = str(raw_task or "").strip()
    if task_link and not _TASK_LINK_RE.fullmatch(task_link):
        die(f"--task must be a T-NNNN card id (got {task_link!r}). It names the card this request is "
            f"filed IN SERVICE OF, so that the card's audit-post packet can see the request as its "
            f"own evidence (T-11747). Omit it for a request that serves no card.")
    # A `bugfix` routes a DEVIATION (SPEC-0085 §3) — it MUST carry both the recurrence fingerprint
    # (origin_fp) and the stable originating journal ref (origin_ref) so the kernel intake mirror is
    # origin-linked VERBATIM (rule 6), never a synthetic locator. Required only for bugfix.
    if kind == "bugfix":
        if not origin_fp:
            die("--origin-fp required for a bugfix (the originating deviation fingerprint — SPEC-0085 §3)")
        if not origin_ref:
            die("--origin-ref required for a bugfix (the originating events.jsonl source ref — rule 6 mirror)")

    # T-10806: the store + its lock are created with the multi-uid modes (SPEC-0084 r1) — this
    # REPLACES the raw lock-dir makedirs, which left both at the caller's umask.
    ensure_shared_store(cross_log_path, lock_path)
    lock_fd = lockfile.open_flock_target(lock_path)   # never truncating, cross-user safe (X-0226)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)                # one critical section: validate + alloc + append (rule 4)
        events_now = read_events(cross_log_path, aliases)  # single read UNDER the lock — no TOCTOU
        # FAIL-CLOSED --to validation INSIDE the lock (T-9587): the known set is derived from the SAME
        # under-lock log read as the id scan, so a peer concurrently added between check and append can
        # never make a valid --to fail spuriously (the audit-pre TOCTOU finding).
        if validate_to:
            known = known_participants_from_events(events_now, registry_peers, self_name)
            if to not in known:
                candidates = sorted(known - {self_name})
                # cutoff=0.0 → ALWAYS surface the closest known peer when any exists (acceptance: a
                # 'did you mean' line on every refusal), not only when a default-similarity match clears.
                close = difflib.get_close_matches(to, candidates, n=1, cutoff=0.0) if candidates else []
                hint = f" — did you mean {close[0]!r}?" if close else ""
                die(f"--to {to!r} is not a known participant{hint} "
                    f"(a participant id is the project's CANONICAL REGISTRY KEY; its checkout basename is "
                    f"an alias of it — SPEC-0086 §Peer identity; known: {candidates}). "
                    f"Pass --force for a genuinely-new not-yet-registered peer.")
        nid = _next_id(events_now)                         # scan-max UNDER the lock
        data = {"id": nid, "from": self_name, "to": to, "kind": kind, "brief": brief}
        # T-10405: `from` is the PROJECT that raised the item; `actor` is the PERSON who authored it —
        # derived host-side from the launch context, never asked for. Birth-only meta (immutable, like
        # kind/from/to), so the fold reads it off `cross_requested` alone.
        if actor:
            data["actor"] = actor
        if origin_fp:
            data["origin_fp"] = origin_fp
        if origin_ref:
            data["origin_ref"] = origin_ref               # the originating events.jsonl SOURCE ref (rule 6)
        if task_link:
            # T-11747: BIRTH meta, exactly like kind/from/to/origin_fp — the fold reads it off
            # `cross_requested` alone, so no new event type and no second store. Conditional like
            # every optional sibling above: an item serving no card carries no key at all, which is
            # what keeps the packet's empty-tie render byte-identical to the pre-change one.
            data["task"] = task_link
        cross_emit("cross_requested", data)                # append (its own flock on the log file)
    finally:
        # flock released on close, AFTER the append completes — so a concurrent requester scans it next.
        # `die()` above raises SystemExit through here; the fd closes either way (as the `with` did).
        os.close(lock_fd)
    print(f"cross requested: {nid} [{kind}] {self_name} → {to}  {brief}")
    # DEAD-LETTER WARN (T-10697, X-0547) — report-only, AFTER the successful emit: the request stands, but
    # the author is told this receiver cannot process intake so the item will never reach a terminal state.
    if no_team_receivers and to in no_team_receivers:
        print(f"\nWARN: {to!r} is a REGISTERED but NO-TEAM project (no yitc_v2 session, no active AI team) "
              f"— it can never `cross pick/reject/ack`, so {nid} is a likely DEAD-LETTER (it stays "
              f"non-terminal forever; only your own `cross close {nid} --withdraw` can dispose of it). "
              f"For host-infra coordination, route via the server ops channel instead of the cross log.")

    # T-10719 (E-0054): report-only shell-substitution artifact WARN on the PROSE field — the reactive
    # half of the mitigation whose proactive half is the `--brief` steer to --from-stdin. Keeps the
    # T-10547 posture EXACTLY: stderr, AFTER the successful emit, never blocks, never alters the item,
    # emits no event, fail-open (a heuristic bug must never break a filed request). Report-not-block is
    # deliberate — a false positive costs one ignored line, whereas refusing on a heuristic would cost
    # the coordination item.
    try:
        eaten = textutil.shell_substitution_findings({"brief": [brief]})
        if eaten:
            sys.stderr.write(
                f"WARN: {nid} filed, but its brief looks like the shell ate a `...` command "
                f"substitution before `cross request` ran (T-10719 / E-0054):\n")
            for _field, _excerpt in eaten:
                sys.stderr.write(f"  {_field}: ...{_excerpt.strip()}...\n")
            sys.stderr.write(
                "  argv rides the SHELL, which substitutes `...` inside double quotes/heredocs — so the "
                "item PUBLISHED to the peer stores the damage, not what you wrote. Check it with "
                f"`yitc-v2 cross show {nid}`; to re-file prose safely use the shell-proof path (pipe a "
                "YAML mapping via `--from-stdin`), or single-quote the argv.\n"
                "  NOT a guarantee (this is a heuristic, not a gate): a substitution that PRINTS "
                "something (`echo hi` -> \"hi\") splices in seamlessly and leaves NO residue — so "
                "silence here is not proof the brief is intact.\n")
    except Exception:  # noqa: BLE001 — advisory; never fatal to a filed request
        pass

    # T-11388 (X-1048): the PREMATURE-AVAILABILITY-ANNOUNCEMENT WARN — the third member of this verb's
    # report-only family, same posture as both siblings above: stderr, AFTER the successful emit, never
    # blocks, never alters the item, emits no event, fail-open. It fires only on the CONJUNCTION of an
    # unlanded writing claim (host-derived, injected) and an availability claim in the brief, so the
    # protected coordination forms — a deviation capture, a question, a reframe, an ordinary note — are
    # untouched from a worktree, with no added step (D-0049: the capture reflex stays one command).
    try:
        warn = premature_announcement_warning(nid, brief, unlanded_claim)
        if warn:
            sys.stderr.write(warn)
    except Exception:  # noqa: BLE001 — advisory; a heuristic bug must never break a filed request
        pass
    return nid


def cmd_cross_pick(args, *, cross_log_path, self_name, cross_emit, local_append, die,
                   is_kernel: bool = False, resolver_task=None, aliases=None) -> None:
    """`cross pick` — RECEIVER accepts a task/bugfix (requested → picked). A `bugfix` pick at the KERNEL
    is the intake point: it mirrors the originating deviation into the kernel's OWN journal (rule 6).

    INTAKE HYGIENE (T-9362) — BEFORE the FSM guard: `resolver_task` is the id of a DONE local task that
    already resolves this item (host-injected, deterministic). If present, the pick is STALE — REFUSE
    (journal-observable) naming the resolver, UNLESS `--force` (`args.force`). A not-actionable-for-this-
    side item (addressed to a different peer) is SURFACED as a clear skip line, then the FSM guard refuses
    it wrong-role as before. So no side re-picks already-addressed or irrelevant work.

    DOUBLE-INTAKE VISIBILITY (T-10636, X-0456) — an `already_held` item (one a peer already picked) is
    REFUSED naming the HOLDER + its pick ts + its task. The FSM guard already refused this state; this
    only makes the refusal name WHO holds it, so a raced second intake is legible rather than a bare
    wrong-state code.

    PREMISE REVIEW (T-10439, SPEC-0086 rule 7) — the intake hygiene above checks the request's SHAPE;
    the cue printed just before the emit reminds the receiver to check its CENTRAL CLAIM against current
    state. Report-only (a cue + a pointer, never a gate)."""
    item = _resolve_or_die(cross_log_path, args.id, die, aliases=aliases)
    force = bool(getattr(args, "force", False))
    advisories = intake_advisories(item, self_name, resolved_by=resolver_task)
    if "already_addressed" in advisories and not force:
        _refuse(local_append, die, item["id"], "pick", self_name,
                f"already-addressed: done task {resolver_task} already resolves {item['id']} "
                f"(its fix already landed) — skip the stale intake (re-pick with --force to override)")
    if "not_for_this_side" in advisories:
        print(f"cross pick: {item['id']} is addressed to {item.get('to')!r}, not {self_name!r} — "
              f"not actionable for this side; skip it (relevance check, T-9362)")
    # T-10636 (X-0456) — NAME the holder on a second concurrent pick. This adds NO gate: the FSM _guard
    # below ALREADY refuses this exact case (from_states={"requested"}), but its message names only the
    # STATUS ("current: 'picked'"), never WHO holds it — so a controller hitting it could not tell whether
    # it had raced a peer or mis-typed an id. Same journal-observable `cross_refused` path, holder-naming
    # message. NOT --force-overridable: --force overrides only the T-9362 staleness advisory above, and a
    # second pick is FSM-illegal regardless, so this refusal is unconditional.
    if "already_held" in advisories:
        _refuse(local_append, die, item["id"], "pick", self_name,
                f"already-held: {item['id']} is already under intake by {describe_holder(item)} "
                f"(status: {item['status']!r}) — a second concurrent intake would duplicate that work "
                f"(X-0456). Coordinate with the holder instead of re-picking.")
    _guard(local_append, die, item, "pick", self_name,
           role="receiver", kinds={"task", "bugfix"}, from_states={"requested"})
    # T-10439 (SPEC-0086 rule 7): the receiver-side premise-review cue — this pick IS one of the two
    # operations the rule fires before. Printed AFTER the guard passes (a refused pick creates no intake,
    # so it earns no cue) and BEFORE the emit. Report-only: it never blocks the pick (non-goal #7).
    # T-11992: `is_kernel` is already the realm this verb was handed — reuse it, no new plumbing.
    print_premise_review_cue([item["id"]], self_name, is_consumer=not is_kernel)
    cross_emit("cross_picked", {"id": item["id"], "by": self_name})
    _mirror_on_intake(item, local_append, is_kernel=is_kernel)   # rule 6 — kernel bugfix intake only
    print(f"cross picked: {item['id']} by {self_name}")


def cmd_cross_done(args, *, cross_log_path, self_name, cross_emit, local_append, die,
                   aliases=None) -> None:
    """`cross done` — RECEIVER finishes (picked → done; may carry the receiver's T-NNNN), optionally
    carrying `--note <text>`: WHAT the receiver actually did.

    The `--note` (T-10273) is the receiver-side mirror of `cross close --note` (T-10256). A receiver whose
    outcome DIVERGES from the request had no in-verb way to say so: X-0227 asked the kernel to harden
    consumer governance files to 0644; two external-auditor consults said the opposite, so the kernel
    RETIRED the hardening (T-10232) and authored SPEC-0146 — then closed X-0227 with a bare `cross_done`.
    The author (bc-community) could not learn that outcome from the item and re-filed the identical ask as
    X-0256 a day later: duplicate intake, wasted triage on both sides. The note lands on
    `cross_done.data.note` — the key `resolution_note`'s `_NOTE_KEYS` already reads on ANY accepted event —
    so `cross show` surfaces it with no read-side change. (`resolution_note` takes the LAST accepted note,
    so a later author-side `cross close --note` supersedes it, as it should.)

    Optional by construction: a bare `cross done` emits the same `{id, by}` it always did (a REQUIRED flag
    would be a new gate, which CHARTER §Principle 1 forbids here), and `getattr(args, "note", ...)` keeps
    callers lacking the field — `_auto_cross_done_for_close` / `_auto_cross_done_for_landed_closes` emit
    note-less `cross_done` directly — working unchanged.

    NOTE-ATTACH from `done` (T-10785 / X-0618). `from_states` is `{picked, done}`, not `{picked}`: after
    the land-time auto-close the item is ALREADY `done`, and the resolver's substantive return is written
    exactly THEN (it cites the landed sha). With `picked` alone the receiver was locked out of its own
    item and had to re-deliver the return as a separate coordination item (X-0616 / X-0620 / X-0622). The
    attach adds NO state and NO event type and is NOT terminal reanimation — `done` is not a terminal
    (SPEC-0085 rule 2), the fold's `_legality` never checked state, a repeat folds to the SAME `done`, and
    `resolution_note` already prefers the LAST accepted note. So the read side needs no change at all.
    From `done` a `--note` is REQUIRED: the transition already happened, so a bare repeat would resolve
    nothing and is refused."""
    item = _resolve_or_die(cross_log_path, args.id, die, aliases=aliases)
    note = (getattr(args, "note", None) or "").strip()
    _guard(local_append, die, item, "done", self_name,
           role="receiver", kinds={"task", "bugfix"}, from_states={"picked", "done"})
    if item["status"] == "done" and not note:
        # NOTE-ATTACH ONLY from `done` (T-10785): the transition already happened, so a bare repeat
        # would resolve nothing — refuse it (journal-observably) rather than append a no-op event.
        _refuse(local_append, die, item["id"], "done", self_name,
                "already-done: a second `done` is a NOTE-ATTACH — pass --note <the substantive return>")
    data = {"id": item["id"], "by": self_name}
    if getattr(args, "task", None):
        data["task"] = args.task
    if note:
        data["note"] = note
    cross_emit("cross_done", data)
    print(f"cross done: {item['id']} by {self_name}" + (f" — {note}" if note else ""))


# T-11116 — the CONDITIONAL-DECLINE predicate. A resolution that declines an ask *for now* and names
# the moment to come back ("Re-entry: declare subject_globs when verify.layers gain executable
# entries", X-0472) is the one closure shape that strands an obligation: the item goes terminal, the
# condition lives only as prose in a note nothing watches, and on the AUTHOR side the ask becomes
# invisible. X-0472's condition has since FIRED and nobody on this side knows.
#
# What this predicate is FOR, exactly: deciding whether the closing author must ANSWER a question. It
# never builds a trigger, never writes one, never touches the shared log's content. The trigger text is
# always DECLARED (`--re-entry`) — SPEC-0095 settles that axis normatively, and T-10335 is the incident
# (a fire keyed on inferred data made all 9 live `fired` rows false).
#
# It requires an EXPLICIT re-entry marker and deliberately NOT a bare "when"/"once": a loose version
# scored ~60% false over the live log (verification notes matching on "once the fix landed"), and this
# value now GUARDS AN ACTION, so precision was measured before it was trusted
# (`lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate.md` — a gate fails closed, a
# report-only signal fails generous; this one became a gate). Measured on the same 439 noted terminal
# items: 19 hits, of which the 13 on the AUTHOR side — the only side this seam gates — are 13/13
# genuine conditional declines (X-0461..X-0468, X-0471, X-0472, X-0474, X-0499, X-0502, X-0785).
_RE_ENTRY_MARKER_RE = re.compile(
    r"re-?ent(?:er|ry|ering)|re-?ask|re-?raise|re-?visit|revisit|re-?open|come back to (?:this|it)",
    re.I)


def names_re_entry_condition(text) -> bool:
    """Does this closure text name a RE-ENTRY condition — a decline that says "come back when X"?

    Faithful and narrow, the discipline of `_clean_trigger`'s docstring one module over: it reports
    only what the text literally SAYS, on an explicit marker. A non-string / empty text is False —
    a close that publishes nothing declines nothing conditionally."""
    return bool(isinstance(text, str) and text.strip() and _RE_ENTRY_MARKER_RE.search(text))


def _re_entry_disposition(args, *, item, events, self_name, local_append, die, arm_re_entry,
                          counterparty):
    """The re-entry disposition, shared by EVERY terminal that can strand a condition (T-11180).

    T-11116 built this inside `cmd_cross_close`, wired to the AUTHOR's two terminals. But an item
    goes terminal by FOUR routes and the other two are the RECEIVER's: `cross reject` (declines,
    terminal) and `cross ack` (the note kind's only terminal, given a substantive-return slot by
    T-11106). On a REJECT the asymmetry is total — the author never gets a close to be gated at, so
    the disposition has to be captured where the RECEIVER acts or it is never captured at all. X-0387
    is that shape live on the log: `rejected`, carrying "please FIX the ai-safety record + re-issue",
    with nothing gating it and no close that will ever come.

    So the guard is HOISTED here rather than copied: one predicate, one guard, one arming path, three
    call sites (CHARTER §P1 F1 extend-don't-parallel; what F3 removes is the close-local copy). The
    returned triple is called in the same order at every site — refusals, then `require` BEFORE the
    emit, then `attach` onto the event data, then `arm` after it.

    WHOSE DEBT ECHO does a receiver-side re-entry belong in? **The RECEIVER's** — the journal of the
    session that runs the verb — and NOT by mirroring the author case. Four grounds:

    1. MECHANICAL BOUND, not a preference. A followup is an append to the LOCAL journal
       (`bin/lib/cli.py#_arm_cross_re_entry` -> the ordinary `followup add`). Writing another
       project's repo is forbidden (AGENTS §Scope-boundary), and SPEC-0084 rule 5 carves out exactly
       ONE cross-party writable surface: the shared coordination store. Arming into the AUTHOR's echo
       is unreachable by any sanctioned path, and building a path would be the cross-repo write the
       boundary exists to forbid.
    2. THE CONDITION IS THE RECEIVER'S OWN UTTERANCE. They wrote "come back when X". They are the
       party that knows the condition and the party that will be asked again, so the waiter reads as
       a real obligation they can act on, not manufactured debt.
    3. THE AUTHOR IS NOT LEFT BLIND. The condition is PUBLISHED to them on the shared log, on this
       verb's own `--reason`/`--note`, which rides `_NOTE_KEYS` — `cross show <id>` renders it as the
       resolution note with no read-side change. The shared log is the cross-party carrier, it is the
       only one, and it already carries the text.
    4. THE HONEST BOUND, SAID OUT LOUD. This puts NO debt in the author's echo and no kernel
       mechanism can. The party who must RE-ASK learns of the condition by reading `cross show`,
       because a terminal item leaves the outbox. That residual is real and named in SPEC-0086 — it
       is the price of the territory boundary, not an oversight.

    `counterparty` is the OTHER party, so the armed row names them in both directions: `item["to"]`
    on the author side, `item["from"]` on the receiver side.

    COVERAGE BOUND, stated so it is not rediscovered as a bug: the predicate is MARKER-KEYED, and
    X-0387's "re-issue" is not one of its markers, so this gate would not have fired on it. Widening
    was measured and DECLINED — over the live log `re-?issue|re-?file|re-?submit|re-?send` adds 26
    hits of which ~2 are genuine, the rest NARRATING a past re-file ("re-filed to:social-parser").
    The predicate GUARDS AN ACTION, so it fails closed and its precision is the property that must
    not erode (`lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate.md`). X-0387 is
    dispositioned by the T-11180 backfill instead."""
    re_entry = (getattr(args, "re_entry", None) or "").strip()
    re_entry_awaits = (getattr(args, "re_entry_awaits", None) or "").strip()
    no_re_entry = (getattr(args, "no_re_entry", None) or "").strip()
    if re_entry and no_re_entry:
        die("--re-entry and --no-re-entry are two answers to one question — pass exactly one "
            "(--re-entry <condition> arms a waiter for it; --no-re-entry <why> records that this "
            "closure leaves nothing to come back on)")
    if re_entry_awaits and not re_entry:
        # The same rule `followup add --awaits` enforces one module over: an awaited artifact with no
        # named moment is armed-but-unnamed (the X-0165 discipline). Refuse rather than drop it.
        die("--re-entry-awaits names the artifact whose closure FIRES the watcher, so it requires "
            "--re-entry <condition> to name the moment in words. Pass both, or neither.")

    def require(text: str, verb: str) -> None:
        """FAIL CLOSED (T-11116): an item whose RESOLUTION names a re-entry condition may not go
        terminal until the acting party says what happens to it.

        THE RESOLUTION, NOT THIS INVOCATION'S TEXT — checked against the motivating incident, not
        assumed. X-0472 was closed by the author with NO note at all: the conditional decline
        ("Re-entry: declare subject_globs when verify.layers gain executable entries") was the
        RECEIVER's, written on `cross_done --note`. A guard reading only the acting party's own
        string would sail straight past the one case this exists for. So it reads BOTH: the text
        this invocation publishes, and the item's chain-derived `resolution_note` — the same
        accepted-only read `cross show` displays, i.e. exactly the text that would be stranded.

        The gate asks a question; it never answers one. Both escapes are explicit, and the refusal
        is journal-observable via the same `cross_refused` trace every other guard here uses, so a
        blocked terminal is analyzable across sessions (SPEC-0086 §Failure-behaviour).

        Runs BEFORE the emit — the append-only log never receives a terminal whose condition nothing
        carries, the same by-construction ordering `_require_resolvable_citations` relies on."""
        if re_entry or no_re_entry:
            return
        peer_note = resolution_note(item_events(events, item["id"]))
        if not (names_re_entry_condition(text) or names_re_entry_condition(peer_note)):
            return
        _refuse(local_append, die, item["id"], verb, self_name,
                "re-entry condition named but nothing would carry it — this item's resolution names a "
                "condition to come back on, and this verb terminates the item, so the condition would "
                "survive only as prose nobody watches (X-0472: bc-community's 'declare subject_globs "
                "when verify.layers gain executable entries' fired weeks later and the author side "
                "never learned). Declare ONE of:\n"
                f"  --re-entry \"<the condition, in your words>\" [--re-entry-awaits <T-NNNN>]  "
                f"→ arms a followup that returns to YOUR debt echo\n"
                f"  --no-re-entry \"<why nothing needs watching>\"  → records that, on the item\n"
                "The condition is never parsed out of your prose — you name it (SPEC-0095: a trigger "
                "is DECLARED, never inferred).")

    def attach(data: dict) -> None:
        """Attach the acting party's re-entry answer to this event. Called with the event data dict
        BEFORE the emit, so a dismissal rides the SAME terminal event (an additive
        `re_entry_dismissed` key — no new event type, and deliberately OUTSIDE `_NOTE_KEYS`, so it
        can never occupy the resolution-note slot). The ARM happens after the emit, in `arm`: a
        followup that outlived a refused terminal would be a watcher for something that never
        happened."""
        if no_re_entry:
            data["re_entry_dismissed"] = no_re_entry

    def arm() -> None:
        if not re_entry:
            if no_re_entry:
                print(f"  re-entry: none — {no_re_entry}")
            return
        if arm_re_entry is None:
            # Leaf-up: this module never reaches for the followup machinery itself. A host that did
            # not wire the collaborator gets a LOUD line rather than a silently-unarmed condition —
            # the terminal already fired, so refusing here would misreport a completed terminal.
            print(f"  WARNING re-entry NOT captured: {re_entry!r} — this session wired no followup "
                  f"collaborator. Capture it by hand: yitc-v2 followup add --text "
                  f"\"re-entry for {item['id']}: {re_entry}\" --relates-to {item['id']}"
                  f"   (add --trigger + --awaits T-NNNN together only if a LOCAL artifact fires it)")
            return
        fid = arm_re_entry(item["id"], counterparty or "", re_entry, re_entry_awaits or None)
        if re_entry_awaits:
            print(f"  re-entry ARMED: {fid} — awaiting: {re_entry}")
            print(f"  it FIRES when {re_entry_awaits} closes, and returns UNFLOORED to `yitc-v2 debt`")
        else:
            # The honest limit, said out loud at the seam rather than discovered later: `awaits` is
            # the sole fire key (SPEC-0095), and a condition about the OTHER party's repo state has
            # no local terminal task to name. T-11863: such a watcher is therefore captured
            # ACTIONABLE rather than armed — arming it would remove it from the headline while
            # leaving it unable to ever fire, the one state worse than staying visible. The declared
            # condition rides the followup TEXT, so nothing is lost.
            print(f"  re-entry CAPTURED ACTIONABLE: {fid} — condition: {re_entry}")
            print(f"  no awaited artifact named, so it is NOT armed: it stays VISIBLE in the "
                  f"`yitc-v2 debt` actionable headline until disposed. Pin a fire key later if a "
                  f"local artifact appears: "
                  f"yitc-v2 followup arm {fid} --trigger \"{re_entry}\" --awaits T-NNNN")

    return require, attach, arm


def cmd_cross_dispute(args, *, cross_log_path, self_name, cross_emit, local_append, die,
                      aliases=None) -> None:
    """`cross dispute` — the AUTHOR records that a peer-declared `done` fix does NOT reach the case
    (`done` -> back to `picked`, carrying the disproof). The symmetric sibling of `cross reject`, one
    role over: the receiver has always been able to say "no" with a reason; the author could not.

    WHY IT EXISTS (X-1093, reported by kupiclub and caused by us). An author who VERIFIES that a peer's
    fix does not work had exactly two moves and both were wrong. `cross close` ASSERTS verification —
    "I verified the peer fixed it", `cmd_cross_close` above — so closing on a disproof writes a FALSE
    record into an append-only log. Doing nothing leaves the item in `outbox_awaiting_close_rows`
    (status == `done`), re-surfacing at EVERY session start as work awaiting a close that must never
    come, carrying no trace of the verification that already happened. Measured 2026-08-22 on X-1044 +
    X-1045: both sat `done` on a fix we had ourselves retracted, and the retraction could only be
    attached by the RECEIVER re-emitting `cross done --note` (the T-10785 attach) — a route available
    only to the other party, and one that leaves the item still reading `done`.

    WHAT IT IS NOT. It does NOT widen `cross close`: that verb's role, kinds and from_states are
    untouched, so closing still means verified, and from the disputed state (`picked`) a close is
    refused wrong-state by the ordinary guard. It adds NO status class — `cross_disputed` is absent
    from `EVENT_STATUS`/`TERMINAL_EVENTS`, and the fold reads it as CANCELLING the `done` (see `fold`),
    so the item falls back to `picked`, in the receiver's court, and stays fully terminable: a real fix
    emits a new `cross_done`, which wins by the same total order, and the author then closes for real.
    It is not terminal reanimation either — `done` is not a terminal (SPEC-0085 rule 2).

    `--reason` is REQUIRED, exactly as on `cross reject`: a dispute with no disproof is indistinguishable
    from a mistake, and the reason is the whole point of the edge (it rides `_NOTE_KEYS`, so `cross show`
    surfaces it as the resolution note with no read-side change). The citation check is the one every
    other human string on this log takes (T-10816): a published `X-NNNN` that nothing allocated cannot be
    retracted from an append-only log, so it is refused BEFORE the emit."""
    reason = (getattr(args, "reason", None) or "").strip()
    if not reason:
        die("--reason required for dispute — state WHAT you verified and how it still fails; a "
            "dispute without the disproof is indistinguishable from a mis-click, and the peer has "
            "nothing to act on")
    events = read_events(cross_log_path, aliases)
    items = fold(events)
    item = _resolve_or_die(cross_log_path, args.id, die, events=events)
    _guard(local_append, die, item, "dispute", self_name,
           role="author", kinds={"task", "bugfix"}, from_states={"done"})
    missing = unresolved_cited_ids(reason, items, self_id=item["id"])
    if missing:
        _refuse(local_append, die, item["id"], "dispute", self_name,
                f"dangling citation: {', '.join(missing)} — no cross_requested allocates "
                f"{'them' if len(missing) > 1 else 'it'} yet. Required ORDER: file the replacement "
                "FIRST (`yitc-v2 cross request --to <peer> --kind <kind> --brief …`, which allocates "
                f"and PRINTS the id), THEN `cross dispute {item['id']}` citing the id it printed. An "
                "id cited here is published to the peer on an append-only log — it cannot be retracted.")
    cross_emit("cross_disputed", {"id": item["id"], "by": self_name, "reason": reason})
    print(f"cross disputed: {item['id']} by {self_name} — {reason}")
    print(f"  {item['id']} is back with {item.get('to')} (status: picked) — it has LEFT your "
          f"fixed-to-verify outbox and is theirs to re-fix; `cross close` stays for a verified fix.")


def cmd_cross_reject(args, *, cross_log_path, self_name, cross_emit, local_append, die,
                     aliases=None, arm_re_entry=None) -> None:
    """`cross reject` — RECEIVER declines with a reason (terminal).

    RE-ENTRY DISPOSITION (T-11180). A reject is the sharpest case the disposition exists for, and the
    one T-11116 could not reach: the ask is declined FOR NOW and the reason names the moment to come
    back ("please FIX the ai-safety record + re-issue" — X-0387, live on the log). It is TERMINAL and
    the AUTHOR NEVER GETS A CLOSE to be gated at, so if the condition is not captured HERE it is not
    captured at all. The guard is the SAME module-level `_re_entry_disposition` the author terminals
    use — see its docstring for the whose-echo decision (the RECEIVER's, on four grounds) and for the
    predicate's measured coverage bound.

    `--reason` stays REQUIRED and unchanged; the three disposition flags are read via getattr and
    `arm_re_entry` defaults to None, so every pre-existing call site keeps working untouched."""
    reason = (getattr(args, "reason", None) or "").strip()
    if not reason:
        die("--reason required for reject")
    events = read_events(cross_log_path, aliases)
    item = _resolve_or_die(cross_log_path, args.id, die, events=events)
    require, attach, arm = _re_entry_disposition(
        args, item=item, events=events, self_name=self_name, local_append=local_append, die=die,
        arm_re_entry=arm_re_entry, counterparty=item.get("from"))
    _guard(local_append, die, item, "reject", self_name,
           role="receiver", kinds={"task", "bugfix"}, from_states={"requested", "picked"})
    require(reason, "reject")
    data = {"id": item["id"], "by": self_name, "reason": reason}
    attach(data)
    cross_emit("cross_rejected", data)
    print(f"cross rejected: {item['id']} by {self_name} — {reason}")
    arm()


def cmd_cross_ack(args, *, cross_log_path, self_name, cross_emit, local_append, die,
                  aliases=None, arm_re_entry=None) -> None:
    """`cross ack` — RECEIVER acknowledges a note (terminal), optionally carrying `--note <text>`:
    the receiver's SUBSTANTIVE RETURN on that id.

    THE RETURN SLOT (T-11106 / X-0889). A `note` has exactly ONE receiver terminal — this one — and it
    used to emit `{id, by}` and nothing else, while `cross done` is kind-guarded to `{task, bugfix}`.
    So a receiver who did work an item ASKED for had no governed way to answer ON that id: the only
    terminal available silently discarded the answer. Measured, not supposed: the kernel filed X-0872
    as a `note` although it instructed kupiclub to RETIRE a covering waiver — a work ask. They did the
    work, held checkable evidence (layer rows, a tombstone comment, a `land_completed` locator), and
    had to re-file it as a SEPARATE item X-0890, leaving `cross show X-0872` reading
    `resolution note: (none)` and their card T-0289 unsatisfiable by any governed path. This is the
    third time the same gap has been closed on this verb family — `cross done --note` (T-10273),
    `cross close --note` (T-10256), `cross close --out-of-band --reason` (T-10909/T-10954) — and
    `note` was the kind left behind.

    NO READ-SIDE CHANGE: the text lands on `cross_acked.data.note`, the key `resolution_note`'s
    `_NOTE_KEYS` already reads off ANY accepted event, so `cross show` surfaces it as the item's
    resolution note with nothing added on the read side.

    Optional by construction from `requested`: a bare `cross ack` emits the same `{id, by}` it always
    did (a REQUIRED flag would be a new gate CHARTER §Principle 1 forbids here — most notes genuinely
    are one-way FYI with nothing to return), and `getattr(args, "note", ...)` keeps callers lacking
    the field working unchanged.

    NOTE-ATTACH from `acked` — the T-10785 edge, one kind over. `from_states` is `{requested, acked}`,
    not `{requested}`, because the reported incident is exactly the late return: X-0872 was acked at
    2026-08-14T07:49:49Z and the evidence was written AFTER. With `requested` alone the receiver stays
    locked out of its own item and the separate-id workaround survives the fix. Unlike the `done`
    attach, `acked` IS terminal — checked, not assumed, that this stays safe at the FOLD and is not
    terminal reanimation: a second `cross_acked` makes `terminals` two events of the SAME type, so
    `winner = min(terminals, key=_order_key)` still yields `cross_acked` and the status stays `acked`,
    `contested = len({types}) > 1` stays False, `_legality` never reads state, and `resolution_note`
    already prefers the LAST accepted note. The item's STATE therefore does not move — only its text
    slot fills (SPEC-0085 rule 3 / SPEC-0086 §cross ack). From `acked` a `--note` is REQUIRED: the
    transition already happened, so a bare repeat would resolve nothing and is refused
    journal-observably rather than appended as a no-op — the same shape `cross done` uses from `done`.
    """
    events = read_events(cross_log_path, aliases)
    item = _resolve_or_die(cross_log_path, args.id, die, events=events)
    note = (getattr(args, "note", None) or "").strip()
    # RE-ENTRY DISPOSITION (T-11180) — the note kind's ONLY terminal, so it strands a conditional
    # decline exactly as `cross reject` does, and for the same reason no author close will ever
    # gate it. Same shared guard, same receiver-side echo; see `_re_entry_disposition`.
    require, attach, arm = _re_entry_disposition(
        args, item=item, events=events, self_name=self_name, local_append=local_append, die=die,
        arm_re_entry=arm_re_entry, counterparty=item.get("from"))
    _guard(local_append, die, item, "ack", self_name,
           role="receiver", kinds={"note"}, from_states={"requested", "acked"})
    if item["status"] == "acked" and not note:
        # NOTE-ATTACH ONLY from `acked` (mirrors cmd_cross_done's already-done branch): the terminal
        # already fired, so a bare repeat resolves nothing — refuse it journal-observably rather than
        # append an event that changes neither the status nor the note.
        _refuse(local_append, die, item["id"], "ack", self_name,
                "already-acked: a second `ack` is a NOTE-ATTACH — pass --note <the substantive return>")
    require(note, "ack")
    data = {"id": item["id"], "by": self_name}
    if note:
        data["note"] = note
    attach(data)
    cross_emit("cross_acked", data)
    print(f"cross acked: {item['id']} by {self_name}" + (f" — {note}" if note else ""))
    arm()


def cmd_cross_close(args, *, cross_log_path, self_name, cross_emit, local_append, die,
                    aliases=None, arm_re_entry=None, registry_peers=None) -> None:
    """`cross close` — the AUTHOR's terminal verb. Default: `cross_closed` (work done + verified, from
    `done`), optionally carrying `--note <text>`: WHAT the author verified. `--out-of-band --reason
    <why>` (T-10909): the same `cross_closed` for substance delivered OUTSIDE the peer return path —
    see the branch comment below. `--withdraw <reason>`: `cross_withdrawn` (retract a not-done item,
    any non-terminal).

    The `--note` (T-10256) backs the assertion this verb already MAKES. Closing is DEFINED as "I verified
    the peer fixed it", yet the event carried only `{id, by}` — so the evidence lived in the closing
    session's transcript and nowhere on the item (`cross show X-0229` printed `resolution note: (none)`
    for an item that WAS genuinely verified). The note lands on `cross_closed.data.note` — the key
    `resolution_note`'s `_NOTE_KEYS` already reads — so `cross show` surfaces it with no read-side change.

    Optional by construction: a bare close emits the same `{id, by}` it always did (the item then simply
    shows no verification record), and `getattr(args, "note", ...)` keeps callers lacking the field working.

    T-10816 (X-0643) — whichever human string this invocation publishes (`--note` on a close, `--reason`
    on a withdraw) is REFUSED when it cites an `X-NNNN` that does not resolve, with a message naming the
    required order. The check runs BEFORE the emit, so the append-only log never receives a citation of an
    id nothing allocated."""
    # T-11582 (E-0054, X-1111): the shell-proof INGEST fork, and it is the FIRST statement on purpose.
    # Hoisted ABOVE every existing validity check — the required-`--reason` checks in the out-of-band
    # and withdraw branches, the orphan-author `--note` requirement, the citation and re-entry guards —
    # so those ONE-COPY checks serve BOTH input paths and the stdin route can never become a second,
    # weaker validator (lessons/mirroring-a-stdin-route-onto-a-verb-with-two-argv-sources.md). Only the
    # SOURCE of the five prose values differs; everything downstream is untouched, which is what makes
    # the two paths emit an identical event.
    if getattr(args, "from_stdin", False):
        _fields = textutil.stdin_mapping_ingest(
            args, CLOSE_STDIN_CONFLICTING_ARGV_FLAGS, stdin_text=sys.stdin.read(), die=die,
            carries="the closure prose",
            recognised=CLOSE_STDIN_RECOGNISED_KEYS, argv_dests=set(vars(args)), verb="cross close")
        for _pk in PROSE_BEARING_CLOSE_FIELDS:
            _pv = _fields.get(_pk)
            if _pv is not None:
                setattr(args, _pk, str(_pv))
    events = read_events(cross_log_path, aliases)
    items = fold(events)
    # `events` is already canonicalized by the read above — the `events=` reuse path (one read, one fold).
    item = _resolve_or_die(cross_log_path, args.id, die, events=events)
    note = (getattr(args, "note", None) or "").strip()

    def _require_resolvable_citations(text: str, verb: str) -> None:
        missing = unresolved_cited_ids(text, items, self_id=item["id"])
        if missing:
            _refuse(local_append, die, item["id"], verb, self_name,
                    f"dangling citation: {', '.join(missing)} — no cross_requested allocates "
                    f"{'them' if len(missing) > 1 else 'it'} yet. Required ORDER: file the replacement "
                    "FIRST (`yitc-v2 cross request --to <peer> --kind <kind> --brief …`, which allocates "
                    f"and PRINTS the id), THEN `cross {verb} {item['id']}` citing the id it printed. An "
                    "id cited here is published to the peer on an append-only log — it cannot be retracted.")

    # ── T-11116, hoisted to the shared home by T-11180 ───────────────────────────────────────────
    # Three mutually-exclusive answers to one question — "does this closure leave a condition to come
    # back on?". The machinery is now the module-level `_re_entry_disposition`, shared with the two
    # RECEIVER terminals (`cross reject` / `cross ack`), so there is ONE guard rather than a copy per
    # role. Behaviour on this verb is unchanged. All fields are read via getattr, so the callers that
    # predate T-11116 (20+ in tests/test_cross_mechanism.py) are untouched.
    _require_re_entry_disposition, _arm_or_record, _arm_after_emit = _re_entry_disposition(
        args, item=item, events=events, self_name=self_name, local_append=local_append, die=die,
        arm_re_entry=arm_re_entry, counterparty=item.get("to"))
    re_entry = (getattr(args, "re_entry", None) or "").strip()
    re_entry_awaits = (getattr(args, "re_entry_awaits", None) or "").strip()
    no_re_entry = (getattr(args, "no_re_entry", None) or "").strip()

    out_of_band = bool(getattr(args, "out_of_band", False))
    if out_of_band and getattr(args, "withdraw", False):
        die("--out-of-band and --withdraw are two different terminals — pass exactly one "
            "(--out-of-band closes work that WAS delivered; --withdraw retracts an item that was not)")

    if out_of_band:
        # T-10909 (X-0721) — the AUTHOR's close for substance delivered OUTSIDE the peer return path.
        # The plain close below gates on `done`, i.e. it is reachable only after a `cross_done`; when
        # delivery happened out of band that event never comes, so the author had NO terminal but
        # `--withdraw` — a RETRACTION, which misreports delivered work as never-wanted. The item then
        # stayed non-terminal forever and every session's outbox echoed finished work as open, eroding
        # the one surface built to be trusted at a glance (a reader who learns the outbox lies stops
        # reading it). This is a MODE of the existing verb on the existing terminal event — no new verb,
        # no new event type, no new store (CHARTER §P1).
        #
        # It is NOT a mute button, and two fences keep it honest: `--reason` is REQUIRED (rides
        # `_NOTE_KEYS`, so `cross show` prints it as the resolution note with no read-side change), and
        # `out_of_band: true` is recorded on the event so the closure reads as REQUESTER-closed rather
        # than peer-returned — the chain carries no `cross_done`, and `cross show` says so on its own
        # `closure:` line. The role/kind guard is the ordinary author one, so a peer still cannot use it.
        if note:
            # Same shape as the withdraw branch: refuse rather than drop, so the author never believes
            # evidence was recorded on a slot this mode does not publish.
            die("--note applies to a plain close — pass the out-of-band close text as --reason")
        reason = (getattr(args, "reason", None) or "").strip()
        if not reason:
            die("--out-of-band requires --reason — the closure must state WHY it was closed without a "
                "peer return, or it is a silent delete of an item the peer still believes is open")
        # T-10954 — `note` is in this set (unlike the plain close below) because a one-way note has
        # exactly one terminal and it belongs to SOMEONE ELSE: `cross ack` is the receiver's, and an
        # informational note asks nothing, so nobody has cause to ack it and it stays `requested`
        # forever (40 of 70 non-terminal outbox rows on 2026-08-11, oldest X-0347). The author's only
        # remaining terminal was `--withdraw` — a RETRACTION, which misreports delivered information
        # as never-wanted. The identical hole one kind over is T-10909/X-0721; `note` was left behind.
        # `cross ack` is UNCHANGED: this ADDS a terminal, it does not move one, and the fold takes
        # whichever fires first.
        _guard(local_append, die, item, "close --out-of-band", self_name,
               role="author", kinds={"task", "bugfix", "note"},
               from_states={"requested", "picked", "done"})
        _require_resolvable_citations(reason, "close --out-of-band")
        _require_re_entry_disposition(reason, "close --out-of-band")   # T-11116
        data = {"id": item["id"], "by": self_name, "reason": reason, "out_of_band": True}
        _arm_or_record(data)
        cross_emit("cross_closed", data)
        print(f"cross closed (out of band): {item['id']} by {self_name} — {reason}")
        _arm_after_emit()
    elif getattr(args, "withdraw", False):
        if note:
            # A retraction's human string is `--reason` (required, and it lands on `cross_withdrawn`).
            # Refuse rather than drop: a silently-ignored --note would leave the author believing the
            # retraction recorded evidence the item never carries.
            die("--note applies to a close, not --withdraw — pass the retraction text as --reason")
        if re_entry or re_entry_awaits or no_re_entry:
            # T-11116 — same shape as the --note refusal above. A withdraw RETRACTS an ask ("we should
            # never have asked"), so there is nothing to come back on: arming a watcher for a retracted
            # ask would manufacture debt out of a decision to want less. Refuse rather than drop, so the
            # author never believes a condition was recorded on a terminal that does not carry one.
            die("--re-entry / --no-re-entry apply to a CLOSE, not --withdraw. A withdraw retracts the "
                "ask itself, so there is no condition to re-enter on. If the ask still stands but is "
                "declined for now, close it (--out-of-band --reason ... --re-entry ...) instead.")
        reason = (getattr(args, "reason", None) or "").strip()
        if not reason:
            die("--withdraw requires --reason")
        _guard(local_append, die, item, "withdraw", self_name,
               role="author", kinds=set(CROSS_KINDS), from_states={"requested", "picked", "done"})
        _require_resolvable_citations(reason, "withdraw")
        cross_emit("cross_withdrawn", {"id": item["id"], "by": self_name, "reason": reason})
        print(f"cross withdrawn: {item['id']} by {self_name} — {reason}")
    else:
        # NOT widened to `note` by T-10954, deliberately: this branch gates from `done`, a state a
        # note can never reach (no `cross_done` is legal for it), so admitting the kind here would
        # add an unreachable path, not a terminal. A note's author terminal is the out-of-band mode.
        # T-11252 — ORPHAN-AUTHOR CLOSE: the ROLE axis, and ONLY the role axis, relaxes to the
        # RECEIVER when the item's `from` names no registered peer. kinds and from_states are
        # UNCHANGED, so this adds no transition that did not already exist — it only answers "who may
        # emit it" for an item whose author provably cannot (a phantom sender never returns, T-11171).
        # The predicate is the SAME one the inbox/outbox WARN is built from (one home), and it FAILS
        # CLOSED: an empty/unreadable registry cannot prove a sender phantom, so the widening does not
        # fire and close stays author-only. Mirrors --out-of-band one role over: same verb, same event,
        # a REQUIRED human string, and a truth-marker so the closure never reads as author-verified.
        orphan = sender_is_unregistered(item, registry_peers, self_name)
        if orphan:
            _guard(local_append, die, item, "close (orphan author)", self_name,
                   role="receiver", kinds={"task", "bugfix"}, from_states={"done"})
            if not note:
                _refuse(local_append, die, item["id"], "close (orphan author)", self_name,
                        "--note is REQUIRED for the orphan-author close — the item's sender "
                        f"{item.get('from')!r} is not a registered project, so no author will ever "
                        "verify this closure; a bare close would assert a verification nobody "
                        "performed. State what was delivered (SPEC-0086 §cross close).")
        else:
            _guard(local_append, die, item, "close", self_name,
                   role="author", kinds={"task", "bugfix"}, from_states={"done"})
        _require_resolvable_citations(note, "close")
        _require_re_entry_disposition(note, "close")   # T-11116
        data = {"id": item["id"], "by": self_name}
        if note:
            data["note"] = note
        if orphan:
            data["orphan_author"] = True
        _arm_or_record(data)
        cross_emit("cross_closed", data)
        print(f"cross closed{' (orphan author)' if orphan else ''}: {item['id']} by {self_name}"
              + (f" — {note}" if note else ""))
        _arm_after_emit()


# ── views (read-only — fold-derived, no stored status) ──────────────────────────────────────────

def _render(rows: list, view: str, self_name: str) -> None:
    if not rows:
        print(f"(cross {view}: nothing for {self_name})")
        return
    for it in sorted(rows, key=lambda r: r["id"]):
        flag = "  ⚑contested" if it.get("contested") else ""
        print(f"{it['id']}  [{it.get('kind','')}/{it.get('status','')}]  "
              f"{it.get('from','')} → {it.get('to','')}{flag}  {it.get('brief','')}")


# Fold-derived membership predicates — the SINGLE definition of each view, shared by the `cross`
# verbs AND the session-start surface (SPEC-0086 rule 2/4: derived, no stored status; one fold, no
# divergence between the verb and the startup count).

def inbox_rows(events: list, self_name: str) -> list:
    """The INBOX set — fold-derived non-terminal items addressed `to:me` (rule 5a)."""
    # inloop-journal-read: one-shot — the outermost comprehension iterable, evaluated exactly once.
    return [it for it in fold(events).values()
            if it["to"] == self_name and it["status"] not in TERMINAL_STATUSES]


def inbox_actionable_rows(events: list, self_name: str, *, linked_cross_ids=()) -> list:
    """The NEEDS-DECISION inbox subset (T-9400) — the SESSION-START surface (SPEC-0086 rule 4): items
    addressed `to:me` that are EXACTLY `requested` (a fresh inbound still awaiting a decision) AND not
    yet tracked by a local task via `resolves_cross`. NARROWER than `inbox_rows` (the full non-terminal
    `to:me` set, which `cross inbox` still renders as the SUPERSET): a `picked`/`done` item (already
    being worked / finished) is excluded by the `status == requested` filter, and a `requested` item a
    local task already links — auto-`cross_picked` to `picked` since T-9399, but DEFENDED here for any
    pre-T-9399 or non-pickable edge — is excluded by `linked_cross_ids`. So "requested-AND-not-linked"
    captures both exclusions cleanly. `linked_cross_ids` is the set of X-NNNN ids a local CARRIER
    DECLARES it tracks — a TASK's `resolves_cross`, or a NON-TERMINAL PLAN's frontmatter
    `resolves_cross` (T-11585; host-scanned, OWN-repo only — D-0019-safe). Empty = nothing excluded on
    that axis. REUSES the fold (via `inbox_rows`) — no second state model (SPEC-0086 rule 2)."""
    linked = set(linked_cross_ids or ())
    return [it for it in inbox_rows(events, self_name)
            if it["status"] == "requested" and it["id"] not in linked]


def inbox_picked_untracked_rows(events: list, self_name: str, *, linked_cross_ids=()) -> list:
    """The ACCEPTED-BUT-UNTRACKED inbox subset (T-11202) — items `to:me` this side has PICKED that NO
    local task names in its `resolves_cross`. The MIRROR of `inbox_actionable_rows` one status over,
    and the exact structural twin of the `unroutable_rows`/`unregistered_sender_rows` pair: same fold,
    same report-only contract, opposite direction of the same asymmetry.

    WHY IT EXISTS — the structure is the defect, not any session's forgetfulness. The session-start
    inbox surface is deliberately the `requested`-AND-untracked cut (T-9400), so PICKING an item is the
    act that REMOVES it from the only surface naming it, while LINKING a task — the thing that would
    restore visibility — is exactly what has not happened. The system is therefore quietest about the
    items it has already promised to do. Measured on the live ledger 2026-08-16: 8 of 8 picked items
    read `task: (none)`; re-measured at this task's Stage 1 the same day, 6 of 11 picked were unlinked
    while the requested cut had fallen to ZERO — the existing line fully silent with six accepted items
    tracked by nothing. HARM CONFIRMED on X-0595 (boomrocket): picked, then FULLY delivered (SPEC-0174
    active, activation_owner_task T-10801 done), yet it sat at `picked` with no resolution note, so the
    reporter who volunteered as the first exercise ground was never told — closed by hand ~10 days late.

    THE TWO EXCLUSIONS ARE STRUCTURAL, not a list to keep in sync. `inbox_rows` drops every TERMINAL
    item by fold (rule 5a — no stored status), `status == "picked"` drops `requested` (the T-9400 cut,
    untouched) and `done` (the peer-side outbox concern), and `id not in linked` drops the item a local
    carrier already DECLARES it tracks. That fence is the whole discriminator: a surface that also counted the tracked
    and the terminal ones would fire always and mean nothing — which is precisely why the existing
    counts were narrowed in the first place.

    `linked_cross_ids` is the set of X-NNNN ids a local CARRIER DECLARES it tracks — a TASK's
    `resolves_cross`, or a NON-TERMINAL PLAN's frontmatter `resolves_cross` (host-scanned, OWN-repo only
    — D-0019-safe); empty = nothing excluded on that axis. TWO CARRIERS, ONE MEANING (T-11585): the
    SPEC-0140 sieve routes an ask needing a spec corpus or a coordinated cut to a PLAN, so before this
    the act of routing an item to its CORRECT carrier made it read as tracked by nothing forever —
    measured on the live ledger 2026-08-26, X-0560 and X-1113 were both named here while each had a
    live plan carrying it. The set stays DECLARED-never-inferred and keyed on `resolves_cross`, never
    on `cites:` (provenance): a subtraction keyed on provenance goes quiet exactly where it should
    speak (`lessons/subtract-on-a-declared-key-never-on-a-provenance-field.md`). A TERMINAL plan's
    declaration does NOT count — a dead carrier tracks nothing forward. This predicate itself is
    carrier-AGNOSTIC: it excludes whatever the host declares, so the widening happened in the host
    scan, NOT in the fence below. REUSES the fold via `inbox_rows` — no second state model (SPEC-0086 rule 2). Sorted by id, so the ids a caller renders
    are deterministic. PURE — renders nothing, emits nothing, gates nothing (a LOG, not a queue —
    SPEC-0086; auto-LINKING an item to a task would be a guess about intent and is deliberately absent)."""
    linked = set(linked_cross_ids or ())
    return sorted((it for it in inbox_rows(events, self_name)
                   if it["status"] == "picked" and it["id"] not in linked),
                  key=lambda r: r["id"])


def outbox_rows(events: list, self_name: str) -> list:
    """The OUTBOX set (the full author ledger) — fold-derived non-terminal items `from:me` (rule 5a).
    Includes items still in the RECEIVER's court (requested/picked) as well as done-awaiting-close."""
    # inloop-journal-read: one-shot — the outermost comprehension iterable, evaluated exactly once.
    return [it for it in fold(events).values()
            if it["from"] == self_name and it["status"] not in TERMINAL_STATUSES]


def outbox_awaiting_close_rows(events: list, self_name: str) -> list:
    """The author-ACTIONABLE outbox subset — `from:me` items a peer has FINISHED (`status==done`) that
    now await MY close: "fixed-awaiting-close" / fixed→verify (T-9289, the session-start surface set).
    The ball is in the AUTHOR's court (unlike requested/picked, which await the receiver); the author
    terminal `cross close` clears it from the surface, so it cannot over-count. `cross_rejected` is a
    FSM terminal with no author-close-after-reject verb (SPEC-0085), so "rejected-awaiting-close" is
    not a reachable surface state — the surface is done-only (audit-pre F1, consult GREEN option 1)."""
    return [it for it in outbox_rows(events, self_name) if it["status"] == "done"]


def unroutable_rows(events: list, known_peers) -> list:
    """The UNROUTABLE set (T-10260) — non-terminal items whose `to` names no registered peer, so NO
    session's inbox will ever fold them. `events` arrives canonicalized, so an aliased spelling is
    already resolved and never counted here; what remains is a genuinely unaddressable id (X-0067's
    `to:__invalid__`). These items are otherwise INVISIBLE — the author's outbox shows them and the
    receiver has no inbox, so nobody is prompted. Report them, never silently drop them.

    NON-TERMINAL only: a withdrawn/rejected item needed no route and warning about it forever is noise.
    Empty/None `known_peers` (an unreadable registry) → [] : we cannot tell routable from unroutable, so
    we say NOTHING rather than warn about every item. Sorted by id. PURE — renders nothing."""
    if not known_peers:
        return []
    known = set(known_peers)
    # inloop-journal-read: one-shot — the outermost generator iterable, evaluated exactly once.
    return sorted((it for it in fold(events).values()
                   if it["status"] not in TERMINAL_STATUSES and it.get("to") not in known),
                  key=lambda r: r["id"])


def _render_unroutable(rows: list) -> None:
    """The LOUD unroutable WARN, printed under `cross inbox` / `cross outbox`. Names each id and its bad
    `to:` value verbatim so the reader can fix or withdraw the item. Report-only: a read view never gates."""
    if not rows:
        return
    print(f"\nWARN: {len(rows)} coordination item(s) addressed to an UNROUTABLE peer — no session folds "
          f"these, they reach nobody (SPEC-0086 §Peer identity):")
    for it in rows:
        print(f"  {it['id']}  [{it.get('kind','')}/{it.get('status','')}]  from:{it.get('from','')}  "
              f"to:{it.get('to','')!r}  ← not a registered peer")
    print("  fix: `cross close <id> --withdraw` and re-file to the canonical peer id, "
          "or register the peer in registry.yaml.")


def sender_is_unregistered(item, registry_peers, self_name) -> bool:
    """Does this item's `from` name NO registered peer? The SINGLE definition of "unregistered
    sender" (CHARTER P5 one home, T-11252) — extracted from `unregistered_sender_rows`, which now
    CALLS it, so the READ view's WARN and the WRITE path's orphan-author close can never disagree:
    the verb cannot admit a close the WARN would not have flagged, nor refuse one it did.

    `registry_peers` DIRECTLY, never `known_participants_from_events` — the union would launder a
    phantom sender into "known" the instant its own row lands (the load-bearing note on the row
    builder below). `self_name` is EXEMPT.

    Empty/None `registry_peers` (an unreadable registry) → False. On the READ side that keeps the
    row builder's existing fail-soft [] ("we cannot tell, so say nothing"); on the WRITE side the
    SAME line is fail-CLOSED ("we cannot tell, so the widening does not fire and close stays
    author-only"). One predicate, and its degraded answer is safe in both directions."""
    if not registry_peers:
        return False
    return item.get("from") not in (set(registry_peers) | {self_name})


def unregistered_sender_rows(events, registry_peers, self_name) -> list:
    """The UNREGISTERED-SENDER set (T-11171) — non-terminal items whose `from` names no registered
    peer, so the row reads as a live ask from a project that does not exist. The exact structural
    twin of `unroutable_rows` one field over: that one flags a bad `to:` (nobody folds it), this one
    flags a bad `from:` (nobody sent it). Same report-only contract, same fail-soft, same shape.

    WHY `registry_peers` DIRECTLY AND NOT `known_participants_from_events` (load-bearing, T-11171).
    That helper UNIONS in every `from`/`to` already present on the log — which is correct for
    validating a `--to` (a peer mid-conversation is addressable before it is registered), and exactly
    WRONG here: the union would launder a phantom sender into "known" the instant its own first row
    lands, so the 20 rows this task was filed over would each have vouched for themselves.

    This is a LABEL, not a gate (the card is explicit). It would NOT have prevented the incident —
    the `clone` checkout existed on disk at the moment of the append — but it makes the rows
    identifiable as non-peer at READ time, which is where the cost actually fell: 15 of them sat in
    the inbox reading as live peer requests and consumed a full controller triage pass.

    NON-TERMINAL only (a withdrawn/rejected item needs no warning forever — same rule as the twin).
    `self_name` is EXEMPT so an unregistered local checkout does not flag its own outbound rows.
    Empty/None `registry_peers` (an unreadable registry) → [] : we cannot tell registered from
    phantom, so we say NOTHING rather than flag every row. Sorted by id. PURE — renders nothing."""
    # inloop-journal-read: one-shot — the outermost generator iterable, evaluated exactly once.
    return sorted((it for it in fold(events).values()
                   if it["status"] not in TERMINAL_STATUSES
                   and sender_is_unregistered(it, registry_peers, self_name)),
                  key=lambda r: r["id"])


def unregistered_sender_advice(item, self_name) -> str:
    """The PER-ROW remedy printed under an unregistered-sender WARN row (T-11252) — derived from the
    row's role + kind + state, never a canned string.

    WHY IT IS COMPUTED. The WARN previously prescribed one canned `cross close <id> --withdraw` to
    every row it printed. `--withdraw` is AUTHOR-only, and the row set EXEMPTS `self_name`, so the
    reader of this WARN is NEVER the author: the one command it named was unfollowable for 100% of
    the rows it appeared under, and it failed on a role guard that says nothing about the WARN. That
    is the misdirection this card exists for. Same single-emitter shape as `describe_holder` /
    `unanswered_cross_link_advice`: one function owns the advice string, so no caller re-derives it.

    PURE — returns the line, prints nothing. Names ONLY commands the reader's role and the item's
    state actually admit; when the reader is neither side it names NO command rather than a wrong one."""
    iid, kind, status = item["id"], item.get("kind"), item.get("status")
    if item.get("to") != self_name:
        return ("  → you are neither side of this item; nothing here is yours to terminate "
                "(register the sender if it is a real peer)")
    if kind == "note":
        return f"  → yours to terminate: `yitc-v2 cross ack {iid} --note <what you did with it>`"
    if status in ("requested", "picked"):
        return f"  → yours to terminate: `yitc-v2 cross reject {iid} --reason <why not>`"
    if status == "done":
        return (f"  → yours to terminate: `yitc-v2 cross close {iid} --note <what you delivered>` "
                f"— the orphan-author close: the author cannot return to close it (SPEC-0086 §cross close)")
    return "  → no receiver terminal applies in this state; register the sender if it is a real peer"


def _render_unregistered_senders(rows: list, self_name: str) -> None:
    """The LOUD unregistered-sender WARN, printed under `cross inbox` / `cross outbox` (T-11171).
    Names each id and its bad `from:` value verbatim so the reader can tell a real peer ask from a
    phantom one before spending triage on it. Report-only: a read view never gates."""
    if not rows:
        return
    print(f"\nWARN: {len(rows)} coordination item(s) sent by an UNREGISTERED sender — these are NOT "
          f"asks from a known peer, so do not triage them as live work (SPEC-0086 §Peer identity):")
    for it in rows:
        print(f"  {it['id']}  [{it.get('kind','')}/{it.get('status','')}]  from:{it.get('from','')!r}  "
              f"to:{it.get('to','')}  ← not a registered project")
        # T-11252 — the remedy is PER ROW, computed from that row's role/kind/state, because the one
        # canned line this replaced named an author-only `--withdraw` to a reader who is never the author.
        print(unregistered_sender_advice(it, self_name))
    print("  cause: typically a COPY of a governed repo run under its directory basename — the copy "
          "resolves that basename as its own identity and files against the shared store (T-11171).")
    print("  fix: register the sender in registry.yaml if it is a real peer whose entry is merely "
          "missing; otherwise terminate each row with the command named under it.")


def _render_read_degrade(events, cross_log_path) -> None:
    """The LOUD read-degrade WARN, printed under `cross inbox` / `cross outbox` (T-10844). Says how many
    lines the reader could not decode and that the view just rendered may therefore be MISSING an item —
    the view's silence is no longer evidence of an empty inbox.

    The log PATH is a parameter, never a canonical default: the store lives outside every repo and the
    path is configurable, so a renderer that guessed it could name a file the reader never folded.
    Report-only in the exact `_render_unroutable` shape — prints nothing when clean, moves no exit code,
    emits no event, and repairs nothing (the log is append-only + union-merged; a reader never rewrites
    it)."""
    n = unparseable_count(events)
    if not n:
        return
    print(f"\nWARN: {n} line(s) in the shared coordination log could NOT be parsed and were skipped — "
          f"this view may be MISSING coordination item(s), so its silence does NOT mean clean "
          f"(SPEC-0084 r4 read-degrade):")
    print(f"  log: {cross_log_path}")
    print("  cause: a torn/truncated line (several peers append concurrently). The log is append-only "
          "and union-merged — a reader never repairs it.")
    print("  fix: inspect the damaged line(s) in the log; a peer's re-append of the same item folds "
          "back in by content-hash (idempotent), so ask the author to re-file if an item is lost.")


def cmd_cross_inbox(args, *, cross_log_path, self_name, aliases=None, registry_peers=None, **_) -> None:
    """`cross inbox` (read-only) — the fold-derived non-terminal items addressed `to:me` (rule 5a), plus
    the unroutable WARN (T-10260) and the read-degrade WARN (T-10844). ONE read, all three views."""
    events = read_events(cross_log_path, aliases)
    _render(inbox_rows(events, self_name), "inbox", self_name)
    _render_unroutable(unroutable_rows(events, registry_peers))
    _render_unregistered_senders(unregistered_sender_rows(events, registry_peers, self_name),
                                self_name)
    _render_read_degrade(events, cross_log_path)


def cmd_cross_outbox(args, *, cross_log_path, self_name, aliases=None, registry_peers=None, **_) -> None:
    """`cross outbox` (read-only) — the fold-derived non-terminal items `from:me` awaiting my action
    (e.g. done-awaiting-close). Terminal items are invisible by fold (rule 5a). Plus the unroutable WARN
    (T-10260) — the AUTHOR is exactly who can withdraw + re-file a misaddressed item — and the
    read-degrade WARN (T-10844)."""
    events = read_events(cross_log_path, aliases)
    _render(outbox_rows(events, self_name), "outbox", self_name)
    _render_unroutable(unroutable_rows(events, registry_peers))
    _render_unregistered_senders(unregistered_sender_rows(events, registry_peers, self_name),
                                self_name)
    _render_read_degrade(events, cross_log_path)


# ── the per-item inspector (T-10255) ────────────────────────────────────────────────────────────
# `inbox`/`outbox` render ONE line per item and discard the chain the fold walks — so the author-side
# `cross close` ("I verified the peer fixed it") had no cheap way to see WHAT resolved an item: it
# meant hand-folding the out-of-repo shared log with python (observed closing X-0229, and again across
# a 14-item batch). `cross show` is that missing READ: a VIEW over the SAME fold — no stored status, no
# new event, no FSM change, no write path.

# The data keys that can carry a human resolution note, in preference order within one event: `note`
# (what `cross close --note` adds, T-10256) then `reason` (what reject/withdraw carry today).
_NOTE_KEYS = ("note", "reason")

# The data key carrying MACHINE-DERIVED resolution provenance (T-10785 / X-0618) — deliberately OUTSIDE
# `_NOTE_KEYS`, so an auto-emitted one-liner can never occupy the receiver's substantive-return slot.
_AUTO_NOTE_KEY = "auto_note"


def item_events(events: list, item_id: str) -> list:
    """The item's protocol events in `_order_key` order, each marked ACCEPTED or DROPPED by the SAME
    legality the fold applies (`_legality`) — so the chain a reader sees is exactly what the fold
    counted. Returns [{event, type, ts, by, accepted, why}]; `[]` for an orphan/unknown id. Non-protocol
    `cross_*` lines (e.g. the local-only `cross_refused` trace) are omitted, as the fold omits them.
    A statusless PROTOCOL event (`NONSTATUS_PROTOCOL_EVENTS` — the T-11423 `cross_disputed`) IS part of
    the chain: the fold counts it, so a reader who could not see it would be shown a `picked` item whose
    events say `done` with nothing in between."""
    evs = [e for e in events if (e.get("data") or {}).get("id") == item_id]
    req = _birth(evs)
    if req is None:
        return []
    rd = req.get("data") or {}
    kind, frm, to = rd.get("kind"), rd.get("from"), rd.get("to")
    chain: list = []
    for e in sorted(evs, key=_order_key):
        et = e.get("type")
        if et == "cross_requested":
            # The birth is accepted; any FURTHER `cross_requested` on the same id is a duplicate birth
            # the fold ignores (it reads only the earliest) — surface it as dropped, never as history.
            accepted, why = (e is req), (None if e is req else "duplicate-birth")
        elif et not in EVENT_STATUS and et not in NONSTATUS_PROTOCOL_EVENTS:
            continue
        else:
            accepted, why = _legality(e, kind, frm, to)
        chain.append({"event": e, "type": et, "ts": e.get("ts"),
                      "by": (e.get("data") or {}).get("by") or rd.get("from"),
                      "accepted": accepted, "why": why})
    return chain


def resolution_note(chain: list):
    """The item's resolution note — the last `note`/`reason` on an ACCEPTED event, or None. A DROPPED
    event resolved nothing (the fold ignores it), so it never supplies the note: sourcing one from an
    illegal-role/kind event would misreport the resolution the fold never counted (audit-pre, T-10255)."""
    for entry in reversed(chain):
        if not entry["accepted"]:
            continue
        data = entry["event"].get("data") or {}
        for key in _NOTE_KEYS:
            if (data.get(key) or "").strip():
                return data[key].strip()
    return None


def auto_resolution_note(chain: list):
    """The item's AUTO-DERIVED resolution provenance — the last `auto_note` on an ACCEPTED event, or
    None (T-10785). The exact mirror of `resolution_note` above, on the OTHER key: same accepted-only
    rule (a dropped event resolved nothing), same last-wins preference. Two readers rather than one
    widened `_NOTE_KEYS` precisely so the two texts stay separable — the receiver's own words on
    `note`, the machine's on `auto_note`."""
    for entry in reversed(chain):
        if not entry["accepted"]:
            continue
        value = ((entry["event"].get("data") or {}).get(_AUTO_NOTE_KEY) or "").strip()
        if value:
            return value
    return None


def resolved_by_task(chain: list):
    """The receiver-side `T-NNNN` that did the work — from the last ACCEPTED `cross_done` carrying a
    `task` link (`cross done --task`). None when the peer linked no task. Same accepted-only rule as
    `resolution_note`: a dropped `cross_done` never resolved the item."""
    for entry in reversed(chain):
        if entry["accepted"] and entry["type"] == "cross_done":
            task = ((entry["event"].get("data") or {}).get("task") or "").strip()
            if task:
                return task
    return None


def out_of_band_closure(chain: list) -> bool:
    """Did an ACCEPTED `cross_closed` close this item OUT OF BAND (T-10909)? Same accepted-only rule as
    `resolution_note`/`auto_resolution_note`: a DROPPED event closed nothing, so it cannot claim the
    provenance. A DERIVED read over the existing chain — the flag is never stored as status."""
    for entry in chain:
        if not entry["accepted"] or entry["event"].get("type") != "cross_closed":
            continue
        if (entry["event"].get("data") or {}).get("out_of_band"):
            return True
    return False


# ── linked-id references: an out-of-repo disposition delivered under ANOTHER id (T-11150, f1) ────
# THE BLINDNESS this closes. `item_events` keys strictly on `data.id == item_id` (rule 1, immutable
# id) — correct, and it means an item's view can only ever see events that name ITSELF. But the
# protocol FORBIDS re-emitting onto a settled item, so a disposition that arrives AFTER an item went
# terminal can only be delivered as a NEW item whose text names the old one. MEASURED 2026-08-16:
# `cross show X-0584` printed `resolution note: (none)` although its reframe had been returned as
# note X-0755, whose brief opens "DISPOSITION OF X-0584 …". Grepping the repo journal for that
# disposition then found nothing — because it was never IN the repo — and the absence was read as a
# false false-green alarm (T-10841, fingerprint
# cross-disposition-verified-absent-by-grepping-repo-journal-instead-of-out-of-repo-shared-store).
#
# What this is: a DERIVED READ over the SAME fold, in the shape of `resolution_note` /
# `auto_resolution_note` / `resolved_by_task` beside it. No new event, no new store, no stored
# status, no FSM change, no schema change (CHARTER §P1 F2 — view over new entity). The link is
# ALREADY written, in the text, and was simply never read.
#
# What it is NOT: it does NOT touch the `resolution note:` slot. A reference is a reference — that a
# neighbouring item names this id is NOT evidence that this id was disposed, and promoting one into
# the resolution slot would FABRICATE a disposition the fold never derived. A genuinely undisposed
# id still reads `(none)`; the fix adds references, never a guess.

# The text fields on a cross event that can carry a human/machine reference to another item, in the
# order they are scanned. `brief` rides the birth; `_NOTE_KEYS` + `_AUTO_NOTE_KEY` ride the returns.
_REF_TEXT_KEYS = ("brief",) + _NOTE_KEYS + (_AUTO_NOTE_KEY,)


def _item_ref_text(events: list, item_id: str) -> str:
    """The ACCEPTED text an item publishes, joined — the surface a reference can be written on.
    Accepted-only, the same rule `resolution_note` applies: a DROPPED event is one the fold never
    counted, so a reference written on it was never published by this item either."""
    parts = []
    for entry in item_events(events, item_id):
        if not entry["accepted"]:
            continue
        data = entry["event"].get("data") or {}
        for key in _REF_TEXT_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)
    return " ".join(parts)


def linked_item_refs(events: list, items: dict, item_id: str):
    """The OTHER folded items linked to `item_id` by TEXT — `(inbound, outbound)`, each a list of
    folded item dicts in id order (T-11150).

      * OUTBOUND — ids THIS item's own accepted text names. The item is pointing somewhere.
      * INBOUND  — other items whose accepted text names THIS id. Something points here; this is the
        direction that carries a disposition delivered under a linked NEW id.

    Reuses `_CITED_ID_RE`, the existing word-bounded `X-NNNN` prose scanner (T-10816) — no second
    regex. SELF is dropped on both sides (an item legitimately names itself, and that is a
    self-reference, never a link — the same rule `unresolved_cited_ids` states). Only ids the FOLD
    actually carries are returned: a dangling citation renders nothing here (fail-closed;
    `unresolved_cited_ids` is the surface that REPORTS such a citation). An id in BOTH directions is
    reported in both — the two directions are different facts about the same pair, and collapsing
    them would hide which side wrote the link.

    PURE over (events, items): no store read, no journal append, no emit."""
    items = items or {}
    outbound = sorted({cid for cid in _CITED_ID_RE.findall(_item_ref_text(events, item_id))
                       if cid != item_id and cid in items})
    inbound = sorted({other for other in items
                      if other != item_id
                      and item_id in set(_CITED_ID_RE.findall(_item_ref_text(events, other)))})
    return ([items[i] for i in inbound], [items[o] for o in outbound])


# The bytes of a referenced item's brief shown per row — enough to recognise WHAT the link says
# (a "DISPOSITION OF X-NNNN …" opener is legible well inside it) without turning the inspector into
# a second `cross show` of every neighbour. Truncated on a byte boundary via the existing `_byte_head`.
REF_BRIEF_HEAD_BYTES = 160


def _render_linked_refs(inbound: list, outbound: list) -> None:
    """Render the `references:` block, or NOTHING when there is neither an inbound nor an outbound
    ref. The empty case emits ZERO lines DELIBERATELY: an item with no links must render exactly the
    pre-change output, so the block stays a real discriminator rather than an unconditional
    decoration (the T-10915 rule-4 shape) — and so an operator never reads a `references: (none)`
    header as a claim that the store was exhaustively searched."""
    rows = [("inbound ", item) for item in inbound] + [("outbound", item) for item in outbound]
    if not rows:
        return
    print("references:")
    for direction, item in rows:
        head = _byte_head(item.get("brief", "") or "", REF_BRIEF_HEAD_BYTES)
        suffix = "…" if len((item.get("brief", "") or "").encode("utf-8")) > REF_BRIEF_HEAD_BYTES else ""
        print(f"  {direction}  {item['id']}  [{item.get('kind','')}/{item.get('status','')}]  "
              f"{item.get('from','')} → {item.get('to','')}  {head}{suffix}")


def cmd_cross_show(args, *, cross_log_path, die, aliases=None, **_) -> None:
    """`cross show <X-NNNN>` (read-only) — the per-item inspector: the fold-derived header, the linked
    task, the resolution note, and the full event chain. Fails closed on an unknown id (`_resolve_or_die`
    — no `cross_requested` births it). Emits nothing: no protocol event, no journal append."""
    item_id = (getattr(args, "id", "") or "").strip()
    events = read_events(cross_log_path, aliases)
    item = _resolve_or_die(cross_log_path, item_id, die, events=events)   # fail-closed, one read
    chain = item_events(events, item_id)

    flag = "  ⚑contested" if item.get("contested") else ""
    print(f"{item['id']}  [{item.get('kind','')}/{item.get('status','')}]  "
          f"{item.get('from','')} → {item.get('to','')}{flag}")
    print(f"brief: {item.get('brief','')}")
    for key in ("actor", "origin_fp", "origin_ref"):   # T-10405: `actor` = WHO authored it (when recorded)
        if item.get(key):
            print(f"{key}: {item[key]}")
    # T-11747: the AUTHOR-side link, on its OWN line and above the receiver-side one. Two lines, not a
    # widened `task:`, because the two say different things and are written by different parties at
    # opposite ends of the item's life: `filed for task` is what the AUTHOR was working on when they
    # raised it; `task` is the RECEIVER's card that resolved it. Conditional like `actor`/`origin_*`
    # above — an item serving no card prints nothing, so an operator never reads an absence as a claim.
    if item.get("task"):
        print(f"filed for task: {item['task']}  (author-side link — `cross request --task`)")
    print(f"task: {resolved_by_task(chain) or '(none)'}")
    print(f"resolution note: {resolution_note(chain) or '(none)'}")
    auto = auto_resolution_note(chain)      # T-10785 — provenance, on its OWN line, never the slot above
    if auto:
        print(f"auto-resolution: {auto}")
    # T-11150 (f1) — the ids LINKED to this one by text, so a disposition delivered under a linked
    # NEW id is legible from the referenced id's own view. Rendered AFTER the resolution note and
    # NEVER into it: references, not a guessed resolution.
    _render_linked_refs(*linked_item_refs(events, fold(events), item_id))
    if out_of_band_closure(chain):   # T-10909 — requester-closed, so the missing cross_done is EXPLAINED
        print("closure: requester-closed out of band — delivered outside the peer return path "
              "(no cross_done)")
    print("events:")
    for entry in chain:
        mark = "" if entry["accepted"] else f"  DROPPED ({entry['why']})"
        print(f"  {entry['ts'] or '(no ts)'}  {entry['type']}  by={entry['by']}{mark}")
