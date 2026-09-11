"""MEMORY.md buffer substrate — the audience self-filter + the onboarding seed-pointer helpers.

The machine-checked leg of SPEC-0039 (the project MEMORY.md buffer rule). SPEC-0039 §5(a) states the
READ-ONLY reader self-filter — "ignore entries whose audience is not self or whose lifetime has
passed" — as reader discipline; this module is the ONE code site that decides the audience half of
that predicate, so the rule stops being prose-only. The drain/authorship half stays
DISTRIBUTED-ENFORCEMENT (SPEC-0005 rule 7a): no code can enforce "delete the entry you consumed".

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine), built to the
`lib/textutil.py` shape: stdlib only, no REPO_ROOT / *_DIR coupling, no host back-import, and NO file
I/O — every pointer helper is pure `text in -> text out`. The seed-WRITE entrypoints that own the
MEMORY.md file (project `init`, access-grant) are a separate concern (SPEC-0147 §7) and call these.

Two surfaces:

  1. `audience_matches` — the SPEC-0039 §3 audience axis:
         all | interactive | background | auto | session(<ref>) | user(<name>)
     `user(<name>)` (T-10263) is the RECIPIENT selector, a +1 mirroring the existing `session(<ref>)`
     form: it scopes an entry to one PERSON, matched against the session's own provisioned user
     identity (the OS launch-context user, whose vocabulary is the host registry's `users.<name>`).

  2. The `[onboarding:<id>]` seed-pointer helpers (SPEC-0147 §3) over the line shape
         [onboarding:<station-id>] [audience: user(<name>)] [until: consume-once]
     MEMORY.md stays POINTER-ONLY — station bodies live in the companion SoT, never in the buffer.
     `catalog_station_ids` derives the id vocabulary FROM that SoT, and `seed_pointers` is the ONE
     seed-write path both entrypoints (project `init`, `memory seed`) fold through (SPEC-0147 §7).

FAIL-CLOSED throughout: an audience value this module does not RECOGNIZE matches NOTHING and surfaces
to no one (SPEC-0039 §3). Ambiguity never escalates into a broadcast.
"""
from __future__ import annotations

import getpass
import os
import pwd
import re
from typing import Iterable, Optional

# ── SPEC-0039 §3 audience axis ────────────────────────────────────────────────────────────────────
# The bare (non-parameterized) values. `all` matches every session; the three ROLE values match a
# session's SELF-DECLARED role (owner dialogue = interactive; a dispatch prompt naming a
# background/auto worker = that role) — no journal field carries it (P1 F1).
AUDIENCE_ALL = "all"
SESSION_ROLES = ("interactive", "background", "auto")

# The two parameterized selectors. `session(<ref>)` predates this module; `user(<name>)` is T-10263.
_SESSION_RE = re.compile(r"^session\((?P<ref>[^()]+)\)$")
_USER_RE = re.compile(r"^user\((?P<name>[^()]+)\)$")

# SPEC-0147 §3 pointer line. Bracketed groups, order-fixed at write time but parsed order-tolerantly
# for `audience`/`until` so a hand-written pointer is still read correctly.
_POINTER_RE = re.compile(r"^\s*\[onboarding:(?P<station>[^\]\s]+)\]\s*(?P<rest>.*?)\s*$")
_TAG_RE = re.compile(r"\[(?P<key>audience|until)\s*:\s*(?P<val>[^\]]+)\]")

# The station catalog's own heading grammar (`## [A] Start`) — the id VOCABULARY (SPEC-0147 §3).
_STATION_HEADING_RE = re.compile(r"^##\s*\[(?P<id>[^\]\s]+)\]")

# Characters the pointer grammar cannot encode in a name: the two selector delimiters, the tag
# delimiters, and any newline (a pointer is one line). See `is_valid_pointer_user`.
_ILLEGAL_USER_CHARS = "()[]\r\n"


def current_user() -> str:
    """The session's provisioned user identity — the OS user this session runs as.

    SELF-DECLARED from launch context, exactly like the SPEC-0039 §3 role values: the identity
    already exists on the host (registry `users.<name>` keys ARE OS usernames, each with
    `home: /home/<name>`), so nothing new is stored and no journal field is added (P1 F1).

    A module-level seam by design — tests and callers monkeypatch THIS function rather than the
    process environment, so no new `YITC_*` env var / config surface is introduced.
    """
    try:
        return getpass.getuser() or ""
    except Exception:
        # getpass raises when there is no controlling terminal AND no passwd entry (some sandboxes).
        # An unknown identity must not silently match a `user(...)` entry — return "" and let
        # `audience_matches` fail closed.
        return ""


def os_identity() -> str:
    """The UNFORGEABLE server-issued identity — the passwd name of the uid this process RUNS AS.

    DELIBERATELY NOT `current_user()` above, and the difference is the whole point (T-11363).
    `getpass.getuser()` consults LOGNAME, USER, LNAME and USERNAME *before* the passwd database, so a
    caller who exports `USER=<someone-else>` changes what it returns. Measured on this host: with
    `USER=<collaborator>` set and the real uid name `dev`, `getpass.getuser()` returns `<collaborator>` — and `<collaborator>` is a
    provisioned registry user, so the value would pass every vocabulary check downstream. An
    attribution a caller can move is not an attribution, so a record meant to say WHO ACTED derives
    from the uid, which no environment variable can reach.

    Reads no argv and no environment variable — that is a property of `os.getuid()`, not a promise in
    prose. Any failure (a uid with no passwd entry, as in some sandboxes) returns "" and the caller's
    `unresolved` sentinel takes over: absence stays distinguishable, never fabricated (T-0358).

    A module-level seam by design, like `current_user()` — tests and callers monkeypatch THIS function
    rather than the process state, so no new `YITC_*` env var is introduced (which would reopen the
    very channel this closes).
    """
    try:
        return pwd.getpwuid(os.getuid()).pw_name or ""
    except Exception:
        return ""


def registry_roles(registry_text: str) -> dict[str, str]:
    """The host registry's `users:` block as {name: role} — the identity VOCABULARY plus each user's role.

    Read-only over EXTERNAL territory (D-0019): the caller reads the file, this parses the text. A
    missing / unreadable / malformed registry degrades to an EMPTY mapping and NEVER blocks a match —
    `audience_matches` is authoritative on identity (it compares against the live launch context),
    and this mapping exists only for authoring-time validation (`is_known_user`) and actor attribution
    (`resolve_actor`). Fail-closed on the surfacing decision, fail-open on the advisory check: an
    unreachable host file must not make a user's own entries invisible to them.

    A user with no declared `role:` maps to "" — known, but of unknown role.

    Deliberately a block scan, not a YAML load: the registry is a large comment-rich host file outside
    this repo, and only its top-level `users:` keys + their `role:` are wanted (lib.state's parser is
    not imported — this module stays a stdlib-only leaf).
    """
    roles: dict[str, str] = {}
    in_users = False
    current: Optional[str] = None
    for line in registry_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():                      # a top-level key ends the users: block
            in_users = line.split(":", 1)[0].strip() == "users"
            current = None
            continue
        if not in_users:
            continue
        if re.match(r"^ {2}(?![ #])", line):            # exactly one nesting level in — a user key
            key = line.split(":", 1)[0].strip()
            current = key or None
            if current:
                roles.setdefault(current, "")
        elif current and re.match(r"^ {3,}(?![ #])", line):   # deeper — that user's own fields
            k, _, v = line.partition(":")
            if k.strip() == "role":
                roles[current] = v.split("#", 1)[0].strip()
    return roles


def registry_users(registry_text: str) -> frozenset[str]:
    """The `users:` key set — the VOCABULARY of legal `user(<name>)` names. A view over `registry_roles`
    (ONE registry parser, never two — CHARTER §P5)."""
    return frozenset(registry_roles(registry_text))


def is_known_user(name: str, registry_text: str) -> bool:
    """Authoring-time check: is `name` a provisioned user in the registry? Empty registry => False."""
    return name in registry_users(registry_text)


# The registry `role:` whose sessions keep the DEFAULT attribution: the owner's own host user is the
# one the primary AI agent runs as, so its records stay `ai-agent` exactly as they always have.
OWNER_ROLE = "owner"

# The attribution a record carries when no PERSON is distinguishable — the historical `created_by`
# default. THE one home for the value (the host + the followup/cross views read it here, never re-spell
# it — CHARTER §P5). `is_named_actor` is the ONE "is this a real person?" predicate every view asks.
DEFAULT_ACTOR = "ai-agent"

# What a record carries when the identity could NOT BE RESOLVED AT ALL — distinct from DEFAULT_ACTOR,
# which is a positive statement ("the owner's own agent acted"). Collapsing the two would make a
# record NAME an actor that may not have acted, which is the T-0358 non-fabrication line; keeping them
# apart is what lets a reader tell "nobody was distinguishable" from "not recorded" from "the agent".
# THE one home for the value, exactly as DEFAULT_ACTOR is (CHARTER §P5). Opt-in per use site: only a
# caller that passes `unresolved=` ever receives it — see `_actor_for` (T-11363).
UNRESOLVED_ACTOR = "unresolved"

# The non-person attributions: the derivation's default plus the hand-authored provenance values that
# name a ROLE, not a human (SPEC-0028 `created_by` enum). UNRESOLVED_ACTOR joins them because it names
# no one at all — `is_named_actor` must not surface it as an author.
IMPERSONAL_ACTORS = frozenset({DEFAULT_ACTOR, UNRESOLVED_ACTOR, "owner", "external"})


def is_named_actor(actor) -> bool:
    """Does `actor` name a real PERSON (<collaborator>) rather than a role (ai-agent / owner / external)?

    The single predicate behind every author-surfacing view: a view shows the author when there IS one to
    show and stays silent otherwise (suppressed-when-clean). Absent / empty => False.
    """
    return bool(actor) and actor not in IMPERSONAL_ACTORS


def _actor_for(user: str, default: str, registry_text: str, unresolved) -> str:
    """THE mapping — identity -> attribution. One rule, expressed over whichever identity the caller's
    resolver read (`resolve_actor` reads `current_user()`, `resolve_server_actor` reads
    `os_identity()`). Factored out so the two resolvers are two VIEWS of one rule rather than two
    parallel paths that can drift apart (CHARTER §P1 filter 2).

      • the owner-role user (the host user the primary AI agent runs as) => `default` (`ai-agent`) —
        the existing corpus keeps its existing meaning, and nothing churns;
      • any OTHER provisioned registry user (e.g. <collaborator>, role: developer) => that NAME;
      • an empty identity / an unknown user / an unreadable registry => `unresolved` when the caller
        supplied one, else `default`.

    `unresolved` is the READER'S judgement, not the mapping's: for `created_by` on a task card the
    historical `ai-agent` default is right, while for a record whose whole purpose is to say WHO ACTED
    a fabricated name is worse than an honest "could not tell". Fail-closed is a property of a use
    site, not of a shared predicate — `lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`.
    """
    if not user:
        return default if unresolved is None else unresolved
    role = registry_roles(registry_text).get(user)
    if role is None:
        return default if unresolved is None else unresolved
    if role == OWNER_ROLE:
        return default
    return user


def resolve_actor(default: str, registry_text: str = "", *, unresolved=None) -> str:
    """The REAL actor behind an authoring verb — derived, never asked for (T-10405).

    Attribution must cost the human ZERO extra input (owner directive 2026-07-11), so the actor is read
    from the launch context via `current_user()` — the same seam `audience_matches` already trusts for
    `user(<name>)`. The mapping is `_actor_for`.

    Fail-CLOSED on vocabulary, fail-OPEN on the write: only a registry-provisioned name can ever be
    stamped (free text never reaches `created_by`), and a failure to resolve degrades to the default
    rather than blocking the authoring verb. Attribution is a record, not a gate.

    `unresolved` (T-11363) is OPTIONAL and defaults to None, which is today's behaviour EXACTLY — every
    existing caller (`task file` / `followup add` / `cross request` / `deviation_captured`) is
    unaffected. A caller that needs "could not resolve" to stay distinguishable from "the agent" passes
    a sentinel; see `resolve_server_actor`.

    IDENTITY SOURCE CAVEAT: `current_user()` is `getpass.getuser()`, which an exported `USER` /
    `LOGNAME` can move. That is acceptable for a zero-friction authoring stamp and NOT acceptable for a
    record that attributes a privileged act — use `resolve_server_actor` for the latter.
    """
    return _actor_for(current_user(), default, registry_text, unresolved)


def resolve_server_actor(default: str, registry_text: str = "", *,
                         unresolved: str = UNRESOLVED_ACTOR) -> str:
    """`resolve_actor`'s SERVER-ISSUED sibling — the same mapping over the UNFORGEABLE `os_identity()`.

    For a record that attributes an ACT rather than an authorship: the acting identity is derived
    exclusively from the uid the process runs as, so no argument and no environment variable can change
    what gets recorded (SPEC-0169 rule 3's substance, applied to a record). There is no parameter
    through which a caller could supply an identity — that is the placement obligation made structural
    rather than documented.

    Still a RECORD and never a gate: unlike `grants.derive_server_identity`, which RAISES on an
    unresolvable identity because it guards an operation, this returns `unresolved` and lets the write
    proceed. A land must not start refusing because a passwd lookup failed.
    """
    return _actor_for(os_identity(), default, registry_text, unresolved)


def actor_vocabulary(registry_text: str) -> frozenset[str]:
    """The named actors `resolve_actor` may stamp — the registry users (an alias of `registry_users`,
    named for the attribution caller so `task file`'s validator needs no second registry reader)."""
    return registry_users(registry_text)


def audience_matches(
    audience: Optional[str],
    *,
    sess_type: Optional[str] = None,
    user: Optional[str] = None,
    session_ref: Optional[str] = None,
) -> bool:
    """Does an entry tagged `audience` surface to THIS session? (SPEC-0039 §5(a), audience leg.)

    `sess_type`   — the session's SELF-DECLARED role: interactive | background | auto.
    `user`        — the session's provisioned user identity (defaults to `current_user()`).
    `session_ref` — the session's own ref, for the `session(<ref>)` selector.

    The axes are INDEPENDENT: `user(<name>)` says WHO the person is, not which role their session
    runs in. An UNTAGGED entry (`audience is None`) is a plain read-by-all to-do-NOW line, not an
    instruction (SPEC-0039 §1) — it surfaces to everyone, and callers that care about the
    instruction/to-do distinction check the `[instruction]` marker, not this predicate.

    Fail-closed: any value not recognized above returns False.
    """
    if audience is None:
        return True                                  # unmarked to-do-NOW line — read-by-all (§1)

    value = audience.strip()
    if not value:
        return False                                 # an EMPTY tag is malformed, not "all" (§3)

    if value == AUDIENCE_ALL:
        return True

    if value in SESSION_ROLES:
        return value == (sess_type or "").strip()

    m = _SESSION_RE.match(value)
    if m:
        ref = (session_ref or "").strip()
        return bool(ref) and m.group("ref").strip() == ref

    m = _USER_RE.match(value)
    if m:
        me = (current_user() if user is None else user).strip()
        return bool(me) and m.group("name").strip() == me

    return False                                     # unknown / malformed selector — surfaces to no one


# ── SPEC-0147 §3 seed pointers (MEMORY.md stays pointer-only) ─────────────────────────────────────

def is_valid_pointer_user(name: str) -> bool:
    """Can `name` be encoded in the `[audience: user(<name>)]` grammar and read back?

    The write-side half of fail-closed. `_USER_RE` matches `user\\((?P<name>[^()]+)\\)` and `_TAG_RE`
    reads to the first `]`, so a name carrying `(` `)` `[` `]` or a newline renders a line that no
    reader can parse: `format_pointer("bob)")` -> `[audience: user(bob))]`. Such a pointer is
    INVISIBLE to `read_pointers` (which drops unparseable audiences) and undrainable by
    `delete_pointer` — a station silently seeded to nobody, retirable by no one.

    The read paths already fail closed on that line, so the defect is not a crash but a SILENT
    no-op; the only place to stop it is before it is written. `format_pointer` therefore refuses an
    illegal name outright, which covers every seed path since all of them fold through it.

    Legal: non-empty after strip, equal to its stripped form (no leading/trailing space, which
    `parse_pointer` would silently trim away, making `user(" bob")` and `user("bob")` collide), and
    free of the grammar's own delimiters.
    """
    if not name or name != name.strip():
        return False
    return not any(ch in name for ch in _ILLEGAL_USER_CHARS)


def format_pointer(station_id: str, user: str, *, until: str = "consume-once") -> str:
    """Render one onboarding pointer line, recipient-scoped to `user`.

    RAISES `ValueError` on a name the pointer grammar cannot round-trip (`is_valid_pointer_user`).
    This is the ONE write site every seed path folds through, so no caller can mint a malformed,
    unreadable, undrainable pointer into a person's buffer.
    """
    if not is_valid_pointer_user(user):
        raise ValueError(
            f"illegal onboarding-pointer user {user!r}: a recipient name must be non-empty, "
            f"unpadded, and free of {_ILLEGAL_USER_CHARS.strip()!r} / newlines — the "
            f"`[audience: user(<name>)]` grammar cannot encode it, and the pointer would be "
            f"unreadable and undrainable once written."
        )
    return f"[onboarding:{station_id}] [audience: user({user})] [until: {until}]"


def parse_pointer(line: str) -> Optional[dict]:
    """Parse one `[onboarding:<id>]` pointer line -> {station, audience, until}, else None.

    A line that is not an onboarding pointer returns None (it is some other buffer entry, left alone).
    A pointer with no `[audience: …]` yields `audience: None` — parsing stays FAITHFUL and reports
    what the line says. Deciding what an audience-less POINTER means is the reader's job, and
    `read_pointers` fails it closed: unlike an ordinary unmarked to-do line (which §1 makes read-by-all),
    a pointer is recipient-scoped BY DEFINITION (SPEC-0147 §3), so a missing audience is MALFORMED, not
    a broadcast licence.
    """
    m = _POINTER_RE.match(line)
    if not m:
        return None
    tags = {t.group("key"): t.group("val").strip() for t in _TAG_RE.finditer(m.group("rest"))}
    return {
        "station": m.group("station"),
        "audience": tags.get("audience"),
        "until": tags.get("until"),
    }


def read_pointers(
    text: str,
    *,
    user: Optional[str] = None,
    sess_type: Optional[str] = None,
    session_ref: Optional[str] = None,
) -> list[dict]:
    """The self-filtered onboarding pointers a session may see, in buffer order (SPEC-0039 §5(a)).

    READ-ONLY — never writes the buffer. A pointer addressed to another PERSON is filtered out here,
    which is the whole point of the `user(<name>)` selector (SPEC-0147 §4 VP4).

    An UNTAGGED pointer surfaces to NO ONE. A pointer carries a recipient by definition (SPEC-0147 §3),
    so a missing `[audience: …]` is a MALFORMED pointer, not the §1 unmarked read-by-all to-do line —
    reading it as read-by-all would let one typo'd seed line broadcast a person's onboarding to every
    user, the exact leak the `user(<name>)` selector exists to close. `audience_matches(None) is True`
    stays correct for ordinary buffer to-dos; it is simply not this reader's default.
    """
    out: list[dict] = []
    for line in text.splitlines():
        p = parse_pointer(line)
        if p is None or p["audience"] is None:
            continue
        if audience_matches(p["audience"], sess_type=sess_type, user=user, session_ref=session_ref):
            out.append(p)
    return out


def write_pointer(text: str, station_id: str, user: str, *, until: str = "consume-once") -> str:
    """Append one recipient-scoped pointer. IDEMPOTENT — re-writing an existing (station, user) is a no-op.

    Idempotence is required by the SPEC-0039 §4 ×N-reader authorship norm: a seed write that reruns
    (project `init` is idempotent by contract) must not accumulate duplicate lines.

    Rendering FIRST makes the `format_pointer` name-validation fail closed even when an equivalent
    (malformed) line already sits in the buffer — an illegal recipient raises rather than reading as
    an idempotent no-op.
    """
    line = format_pointer(station_id, user, until=until)
    for p in _pointers(text):
        if p["station"] == station_id and p["audience"] == f"user({user})":
            return text
    if text and not text.endswith("\n"):
        return f"{text}\n{line}\n"
    return f"{text}{line}\n"


def delete_pointer(text: str, station_id: str, user: str) -> str:
    """Remove one consumed pointer — the SPEC-0039 §5(b) consume-once delete, scoped to ONE recipient.

    Deleting another user's pointer is impossible through this helper: the audience must match the
    named `user`, so a session consuming its own station can never drain a peer's onboarding.
    """
    kept = [
        line for line in text.splitlines(keepends=True)
        if not _is_pointer_for(line, station_id, user)
    ]
    return "".join(kept)


# ── SPEC-0147 §5 station ↔ seam bindings (delivery rides seams the system already emits) ─────────
# The plan's "Station <-> seam binding" table, in code. Each seam token names a lifecycle juncture the
# engine ALREADY crosses — the `session start` read, or a verb the AI itself invokes, or (C) a moment
# only the AI can recognize. NOTHING here DETECTS a seam: the verb call IS the crossing, and the
# AI-judged seam carries no emitter at all. A detector would be CHARTER non-goal #7 (SPEC-0147 §1).
#
# The prose SoT of this table (with the station BODIES) is `onboarding/newcomer-stations.md`; the two
# are pinned to each other by tests/test_t10268. A station may bind to MORE than one seam (I: land +
# deploy) — whichever is crossed first voices it, and consuming it retires the station for both.
STATION_SOT = "onboarding/newcomer-stations.md"

STATION_SEAMS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("A", ("session start",),  "Start"),
    ("B", ("scenario",),       "Scenarios"),
    ("C", ("design fork",),    '"How do we build this" fork'),
    ("D", ("init",),           "The project's mandatory answers (and secrets)"),
    ("E", ("plan file",),      "The first plan and its stages"),
    ("F", ("audit",),          "Auditors and models"),
    ("G", ("worktree new",),   "Tasks, Workers — and the worktree at its moment"),
    ("H", ("followup",),       "Small things for later — followup"),
    ("I", ("land", "deploy"),  "Finishing: land and deploy"),
    ("J", ("inspect",),        "Reviews, debt, coordination — and memory"),
    ("K", ("shared library",),   "External shared libraries"),
    ("L", ("kernel signal",),    "Signalling a fix to the kernel"),
    ("M", ("parallel sessions",),"Parallel sessions"),
    ("N", ("drive to the end",), "Driving the plan to the end"),
    ("O", ("plan trial",),       "Plan trial and postcheck"),
    ("P", ("session refresh",),  "Session refresh and context"),
    ("Q", ("dictated list",),    "Dictating a list of wishes"),
)

# The seams with NO verb emitter: the AI recognizes the moment itself (a structural fork, or the first
# time one of stations K-Q's topics arises) and voices from the pointer it holds — station C's verbless
# shape, generalized (SPEC-0147 §5). Named here so the session-start digest can say so out loud.
AI_JUDGED_SEAMS = ("design fork", "shared library", "kernel signal", "parallel sessions",
                   "drive to the end", "plan trial", "session refresh", "dictated list")


def station_seams(station_id: str) -> tuple[str, ...]:
    """The seam token(s) a station binds to; `()` for an unknown id (fail-closed — it voices nowhere)."""
    for sid, seams, _title in STATION_SEAMS:
        if sid == station_id:
            return seams
    return ()


def station_title(station_id: str) -> str:
    """The station's heading title, `""` for an unknown id."""
    for sid, _seams, title in STATION_SEAMS:
        if sid == station_id:
            return title
    return ""


def held_at_seam(pointers: Iterable[dict], seam: str) -> list[str]:
    """Which HELD pointers bind to `seam`, in table order. An unknown seam token matches nothing.

    `pointers` is `read_pointers(...)` output — already recipient-filtered, so this can never surface
    another person's station (SPEC-0147 §4).
    """
    held = {p["station"] for p in pointers}
    return [sid for sid, seams, _t in STATION_SEAMS if sid in held and seam in seams]


def _sot_display(sot: str, kernel_provided: bool) -> str:
    """How the bodies-SoT path is NAMED to the reader — the engine-content resolution (T-0860/T-0861).

    `sot` is repo-relative for an engine-self session (the bodies sit in this checkout) and an ABSOLUTE
    engine path for a `-C <consumer>` one, where the consumer checkout has no `onboarding/` of its own
    (`kernel_provided`). The caller resolves it; this only labels it, so the reader can tell a path that
    resolves HERE from one the kernel lends. Mirrors how `session start` echoes the handbook read-order
    to a consumer: absolute engine path + a kernel-provided note.
    """
    return f"{sot} (kernel-provided)" if kernel_provided else sot


def _operator_sentence(sot_display: str, consume_cmd: str) -> str:
    """The ONE imperative sentence both renderers end on (T-10314, post-ship review finding 2).

    A `-C` consumer AI holds no SPEC-0147 context, so the digest/nudge must state the whole operator
    contract in-line: read the exact body, voice it ONCE in the person's language WITHOUT inventing
    rules, then retire it. Shared by both renderers so the two can never drift apart.
    """
    return (f"Read the station body from {sot_display}, voice it ONCE in the person's language "
            f"without adding new rules (never show the raw body), then retire it via {consume_cmd}")


def seam_nudge(pointers: Iterable[dict], seam: str, *, cli: str = "bin/yitc-v2",
               sot: str = STATION_SOT, kernel_provided: bool = False) -> Optional[str]:
    """The ONE line a seam emitter prints when the person still holds a station bound to that seam.

    Returns `None` when nothing is due here — the zero-steady-state-cost guarantee (SPEC-0147 §2): a
    seasoned user, or a person already past this station, sees no output at all. A RENDERER, not a
    gate: it returns text, decides nothing, blocks no verb, and writes nothing.

    The emitted `memory consume --station <id>` is the ONE canonical printed form (T-10306 / X-0273):
    the CLI accepts it verbatim, so a session obeying this hint literally succeeds. Keep it identical
    to `pointer_digest`'s — a hint the parser rejects leaves the station silently un-drained.

    `sot` / `kernel_provided` carry the caller's engine-content resolution (T-10314): under `-C` the
    bodies live in the engine, not in the consumer checkout, so the relative default would name a path
    that does not exist there. Defaults keep the engine-self rendering unchanged.
    """
    due = held_at_seam(pointers, seam)
    if not due:
        return None
    parts = ", ".join(f"[{sid}] {station_title(sid)}" for sid in due)
    cmds = " ; ".join(f"`{cli} memory consume --station {sid}`" for sid in due)
    return (f"onboarding station due at seam `{seam}`: {parts} — "
            f"{_operator_sentence(_sot_display(sot, kernel_provided), cmds)} (SPEC-0147 §5/§6)")


def pointer_digest(pointers: Iterable[dict], *, cli: str = "bin/yitc-v2",
                   sot: str = STATION_SOT, kernel_provided: bool = False) -> Optional[str]:
    """The session-start digest: which stations are still un-voiced, and at which seam each is due.

    Returns `None` when the session holds no pointers (zero footprint). Station A's OWN seam IS session
    start, so for a freshly-seeded person this digest is both the map and A's delivery moment.

    Emits the same canonical `memory consume --station <id>` form as `seam_nudge` (T-10306 / X-0273) —
    here with a literal `<id>` placeholder, since the digest names several stations and the AI picks the
    one whose seam it just crossed. Substituting a held id yields a verbatim-executable command.

    `sot` / `kernel_provided`: as `seam_nudge` — the caller-resolved bodies path (T-10314).
    """
    held = [p["station"] for p in pointers]
    if not held:
        return None
    known = [sid for sid, _q, _t in STATION_SEAMS if sid in held]
    rows = [f"{sid}({'/'.join(station_seams(sid))})" for sid in known]
    rows += [f"{s}(no bound seam)" for s in held if not station_seams(s)]
    consume = f"`{cli} memory consume --station <id>`"
    return (f"onboarding pointers held by this person: {', '.join(rows)}. "
            f"{_operator_sentence(_sot_display(sot, kernel_provided), consume)}. "
            f"Voice a station ONLY when you next cross its seam (never all at once). These seams have "
            f"no verb — you recognize the moment yourself (SPEC-0147 §5): "
            f"{', '.join('`' + s + '`' for s in AI_JUDGED_SEAMS)}.")

def catalog_station_ids(catalog_text: str) -> list[str]:
    """The station ids the companion SoT defines, in catalog order (SPEC-0147 §3).

    The catalog's `## [<id>] <title>` headings ARE the id vocabulary — DERIVED here, never duplicated
    as a list in code (CHARTER §P5). Adding, removing, or reordering a station in
    `onboarding/newcomer-stations.md` therefore reshapes what a seed writes, with no code change and
    no way for the two to desync.

    Duplicate ids collapse to their first occurrence: a seed must not write the same pointer twice,
    and `write_pointer` would idempotently drop the second anyway — de-duplicating here keeps the
    reported `added_ids` honest.
    """
    ids: list[str] = []
    for line in catalog_text.splitlines():
        m = _STATION_HEADING_RE.match(line)
        if m and m.group("id") not in ids:
            ids.append(m.group("id"))
    return ids


def consumed_stations(events: Iterable[dict], user: str) -> frozenset[str]:
    """Station ids `user` has EVER consumed on this project — the DERIVED retirement record (T-10319).

    Folded from the `onboarding_station_consumed` events the `memory consume` verb already emits
    (payload `{station, user}`). This exists because consuming a station DELETES its pointer (SPEC-0147
    §2), so buffer-ABSENCE alone cannot tell "never seeded" from "already consumed" — and a re-seed of
    a drained buffer would RESURRECT retired stations (the live incident
    `onboarding-seed-resurrects-consumed-stations`, boomrocket 2026-07-10). The retirement fact is
    recovered by reading the events that ALREADY exist — NO new state, store, learned flag, or FSM
    (CHARTER §P1; this is the RETIREMENT record, NOT the forbidden per-person learning state SPEC-0147
    §1 rules out).

    Pure data-in → set-out over already-parsed event dicts, keeping this module file-I/O-free (the
    caller reads the journal — the same split as `read_pointers` vs the verb). RECIPIENT-SCOPED: only
    THIS user's consumptions count, so a peer's consume never suppresses this user's seed (SPEC-0147 §4).
    Fail-closed: a row that is not a well-shaped `onboarding_station_consumed` for `user` is ignored.
    """
    out: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "onboarding_station_consumed":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):                  # a non-mapping payload is malformed — ignore it
            continue
        station = data.get("station")
        if data.get("user") == user and isinstance(station, str) and station:
            out.add(station)
    return frozenset(out)


def seed_pointers(text: str, station_ids: Iterable[str], user: str,
                  *, exclude: Iterable[str] = ()) -> tuple[str, list[str]]:
    """Write one recipient-scoped pointer per station — the ONE seed-write path (SPEC-0147 §7).

    Both seed entrypoints (project `init` for its owner, `memory seed` for an access-granted or
    manually-named user) fold through here, so there is exactly one place that decides what a seeded
    buffer looks like. A fold of the EXISTING idempotent `write_pointer` — no new line grammar.

    Returns `(new_text, added_ids)` where `added_ids` names ONLY the pointers this call created. A
    re-seed of an already-seeded (station, recipient) pair returns `[]`, which is what lets the
    callers emit `onboarding_seeded` exactly once per REAL seed and stay idempotent on re-run
    (project `init` is idempotent by contract).

    `exclude` is the set of station ids to NOT (re-)seed — the caller's `consumed_stations` fold
    (T-10319). A station the person already CONSUMED has had its pointer deleted (SPEC-0147 §2), so
    pointer-absence alone would let a routine re-seed (a consumer re-`init`) RESURRECT it; excluding
    the ever-consumed set closes that. Both callers pass the SAME fold, so the exclusion is decided in
    one place. Absent `exclude` (the default `()`), behaviour is unchanged — an idempotent re-seed of a
    LIVE buffer is still a no-op via `write_pointer`; `exclude` only covers the DRAINED-buffer case
    that idempotence cannot see.

    RAISES `ValueError` (via `format_pointer`) on an illegal recipient name, before any pointer is
    written — a partially-seeded buffer is never left behind.
    """
    if not is_valid_pointer_user(user):
        format_pointer("_", user)                       # raises the one canonical message
    skip = set(exclude)
    added: list[str] = []
    for station_id in station_ids:
        if station_id in skip:                          # already consumed — never resurrect it (T-10319)
            continue
        grown = write_pointer(text, station_id, user)
        if grown != text:
            added.append(station_id)
            text = grown
    return text, added


def _pointers(text: str) -> Iterable[dict]:
    for line in text.splitlines():
        p = parse_pointer(line)
        if p:
            yield p


def _is_pointer_for(line: str, station_id: str, user: str) -> bool:
    p = parse_pointer(line)
    return bool(p and p["station"] == station_id and p["audience"] == f"user({user})")
