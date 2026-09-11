"""followup verb family — one-command no-worktree capture of a small доделка (SPEC-0095, T-9396).

A `followup` is a lightweight capture recorded as APPEND-ONLY JOURNAL EVENTS in events.jsonl — it adds
NO new store / format / parser (CHARTER §P5: the one journal mechanism). Its 2-state lifecycle
(open -> promoted|dropped) is recorded as followup_added / followup_promoted / followup_dropped events
and FOLDED from the journal (no stored status — the cross inbox/outbox derived-view model).

THE ARMED PARTITION (SPEC-0095 §Armed / T-10309). An OPEN followup may carry an optional `trigger`
ATTRIBUTE — the NAMED future moment it waits for. It is set at capture (`add --trigger`) or later
(`arm`), cleared by `unarm`, and carried by the `followup_armed` event. It is an ATTRIBUTE, not a STATE:
`status` stays exactly {open, promoted, dropped} and an armed followup promotes/drops by the unchanged
legs, so the 2-state FSM above is REAFFIRMED, not extended. `_partition_open` derives — at READ time,
from nothing but the folded records plus the caller's terminal-task set — the three-way split that the
debt echo and `list` both render, so those two surfaces can never disagree.

AWAITED vs PROVENANCE — two fields, never one (T-10335). A followup names TWO different artifacts and
they must not be conflated:
  `relates_to` — PROVENANCE: what this followup is ABOUT (the task it was noticed under). Free-form,
                 printed as `[relates: ...]`. It is NEVER read by the fire check.
  `awaits`     — the AWAITED artifact: the machine-resolvable thing whose CLOSURE is the moment this
                 followup waits for. It is the SOLE fire key.
Before T-10335 the fire check read `relates_to`, so a followup fired the instant the task it was merely
ABOUT closed — which is precisely NOT what it was waiting for. On 2026-07-10 all 9 live `fired` rows were
false: each awaited a FUTURE event (the next revizia run, the next `-C` consumer init, trend-finder's next
land, the next owner-invoked T7 run, a plan's revival) that had not occurred. Worse, `arm` could not undo
it: firing derived from the irreversible fact that the provenance task was closed, so a re-armed followup
stayed fired forever. Fingerprints: `followup-fire-on-relates-to-not-awaited-condition`,
`followup-arm-noop-on-already-fired`. That is the failure that trains a reader to ignore the debt echo.

`arm` therefore rewrites BOTH attributes (last write wins), so re-arming a FIRED followup returns it to
`armed` — the operator saying "that fire was wrong, here is the real condition". No un-fire leg, no new
status, no store: the existing last-write-wins carrier already had the power.

Why an explicit marker and NOT a prose heuristic over the capture text: armedness is a human judgement
about a FUTURE event, and the two misclassifications are not symmetric. A false-ARMED item silently
drops OUT of the headline the owner reads to decide; a false-ACTIONABLE item merely stays visible. So
the trigger is DECLARED, never guessed, and every unknown falls to ACTIONABLE (T-10309 analysis (c)).
The same discipline governs `awaits`: it is DECLARED, never parsed out of the trigger prose. A legacy
record carrying no `awaits` therefore never auto-fires — it waits for an explicit `arm --awaits`,
`unarm`, or a promote/drop (the T-10335 migration; the honest direction — nothing is silenced).

`awaits` IS REQUIRED WHEREVER A TRIGGER IS WRITTEN (T-11863) — at `arm`, and at `add`'s born-armed
door, which is the same claim reached by a second route. Both refuse BEFORE any append, so a rejected
item stays open, actionable and disposable. The reasoning is the asymmetry above taken one step: a
false-ARMED item drops out of the headline, and an armed item with no `awaits` cannot even be brought
BACK by a firing, because `_partition_open` fires on `awaits` alone. So it is the one state strictly
worse than staying actionable, and it was also the CHEAPEST to reach — measured 2026-08-30, 200 of 207
open armed records carried no `awaits`. A bare future event with no machine-checkable artifact is now
kept ACTIONABLE (visible, awaiting an explicit disposition) rather than armed into silence. This is the
third and last optional field of this family closed by the X-0165 discipline, after `promote --into`
and `arm --trigger` — a tightening of existing refusals, adding no validator layer, event, or store.

Note the READ/WRITE split this creates, which is intended and is the reason the parsers above stay
faithful: the WRITE door refuses what the READ side must still tolerate, because the pre-existing
records are real history. Disposing of them is a separate concern from forbidding new ones.

Leaf-up (SPEC-0080 §P-A1): imports stdlib only; host collaborators (the append primitive, the events
path, die, and the shared `--from-stdin` mapping ingest) arrive by INJECTION — never back-imports the
host. The host residue passes the EFFECTIVE
events path (YITC_EVENTS_SINK precedence over EVENTS_PATH) so the fold read-path resolves the SAME
journal the append writes to.
"""
import contextlib
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path

# --- `followup {add,drop,arm} --from-stdin` × argv content-flag conflict (T-11244, E-0054) --------
# A followup's text / trigger / reason is free PROSE, and argv rides the SHELL: a backticked verb or
# path in it is command-substituted BEFORE this verb runs, so the followup is recorded — just wrong,
# with nothing failing closed (kupiclub X-0984 lost a token from a governance reason on
# fu_1c3790ba1e9b). `--from-stdin` is the shell-proof escape its siblings `task update` (T-11165) and
# `cross request` (T-10719) already carry: stdin bytes never reach the shell. Like every member of
# the family it reads the mapping and never looks at argv, so a content-bearing argv flag passed
# ALONGSIDE it would be silently dropped — it FAILS CLOSED instead, naming the offending flag and the
# stdin key that carries it (the T-10437/X-0304 refusal, via the ONE shared helper).
#
# Rows are counted per SOURCE of the value, not per field
# (`lessons/mirroring-a-stdin-route-onto-a-verb-with-two-argv-sources.md`): each field below reaches
# `args` exactly ONE way — its flag — and the `id` POSITIONAL of drop/arm is not carried by the stdin
# mapping at all (an id cannot carry prose), so it earns no row.
#
# `add --fingerprint` is deliberately absent from BOTH tuples: there is NO `--fingerprint` flag
# (`grep -n fingerprint bin/yitc-v2`) — the field has exactly one writer, the in-process
# `frontend-errors --promote` caller, which builds the Namespace directly and never sets from_stdin.
# A row names a CLI flag to refuse; naming one that cannot be typed would print a refusal about a
# flag the caller had no way to pass. It takes the row and the help steer with it if a flag is added.
#
# (attr, cli_flag, stdin_key, absent_value) — the ingest folds the same keys back onto `args`, so
# every downstream check keeps reading the ONE `args` path it always read: only the SOURCE of the raw
# values differs, which is what stops the escape becoming a second, weaker validator.
ADD_STDIN_CONFLICTING_ARGV_FLAGS = (
    ("text",       "--text",       "text",       None),
    ("relates_to", "--relates-to", "relates_to", None),
    ("trigger",    "--trigger",    "trigger",    None),
    ("awaits",     "--awaits",     "awaits",     None),
)
PROSE_BEARING_ADD_FIELDS = ("text", "relates_to", "trigger", "awaits")

DROP_STDIN_CONFLICTING_ARGV_FLAGS = (
    ("reason", "--reason", "reason", None),
)
PROSE_BEARING_DROP_FIELDS = ("reason",)

ARM_STDIN_CONFLICTING_ARGV_FLAGS = (
    ("trigger", "--trigger", "trigger", None),
    ("awaits",  "--awaits",  "awaits",  None),
)
PROSE_BEARING_ARM_FIELDS = ("trigger", "awaits")


def _stdin_ingest(args, table, prose_fields, *, die, carries, ingest=None) -> None:
    """Fold this verb's `--from-stdin` YAML mapping onto `args` (no-op when the flag is absent).

    A CALL SITE of the shared `textutil.stdin_mapping_ingest`, never a second reader: the conflict
    refusal, the YAML parse and the mapping shape-check all stay in that one helper (T-10720), so the
    family's wording cannot drift. What lives here is only the fold every consumer repeats — collected
    once because this file wires THREE subcommands to it.

    The helper arrives INJECTED (`ingest`), like every other collaborator of this leaf, rather than by
    importing `lib.textutil` here. §P-A1 would permit that import, but this module is loaded BOTH as
    `lib.followup` and — by three sibling test files — as a top-level `followup` off `bin/lib`, where a
    `lib.` import cannot resolve; injection keeps both embeddings working and this file stdlib-only, as
    its own header promises. Fail-closed: an embedding that offers no ingest REFUSES `--from-stdin`
    rather than silently reading the flag as absent and taking the argv values it was told not to.

    Each caller invokes this ABOVE its own non-empty/refusal checks, so the ONE pre-existing validator
    keeps covering both channels (the T-11008 hoist rule)."""
    if not getattr(args, "from_stdin", False):
        return
    if ingest is None:
        die("--from-stdin is not available in this embedding (no stdin-mapping ingest was injected). "
            "Pass the fields on argv, single-quoted if they carry backticks.")
    # T-11873: `prose_fields` doubles as the RECOGNISED set — it is already the enumeration of what
    # this verb folds back, so an unrecognised key is refused by the shared ingest instead of being
    # dropped in silence, with no second list to keep in step.
    fields = ingest(args, table, stdin_text=sys.stdin.read(), die=die, carries=carries,
                    recognised=prose_fields, argv_dests=set(vars(args)))
    for key in prose_fields:
        val = fields.get(key)
        if val is not None:
            setattr(args, key, str(val))


# T-11056: the EXACT shape `_fu_id` mints — `fu_` + 12 lowercase hex. A declared link is checked
# against it BEFORE the fold is consulted, so a malformed token is refused as a malformed token
# ("that is not a followup id") rather than as a mysteriously unknown one.
FOLLOWUP_ID_RE = re.compile(r"^fu_[0-9a-f]{12}$")

# T-11146: the TASK-id shape of a promote TARGET. `--into` accepts three carriers (T-11610) — a task
# id (this shape), an authored reference note (`NOTE_TARGET_RE` below) or a PLAN slug (anything else,
# which must resolve to a real plan draft). The three shapes are disjoint by construction (a plan slug
# is kebab-case, `PLAN_SLUG_RE`), so the leg is decided by the target itself and never by a flag the
# caller could get wrong.
TASK_TARGET_RE = re.compile(r"^T-\d{4,}$")

# T-11610: the AUTHORED REFERENCE NOTE shape of a promote TARGET — the THIRD carrier. SPEC-0140 names
# a lessons/ or patterns/ note as the LIGHTEST carrier for a captured followup and prescribes draining
# several of them in ONE work/<slug> land (avoiding the X-0148 ceremony-per-lesson cost), but that
# carrier is a FILE and promote's vocabulary could not name one — so the sanctioned lightest path
# terminated in `drop`, recording DELIVERED notes as decided-not-to.
#
# The shape is deliberately BOUNDED, not an arbitrary path: exactly one of the two sanctioned
# directories, exactly one slash, a `.md` leaf drawn from a charclass that admits no second separator
# — so `..` traversal and anything outside lessons/ and patterns/ cannot match. A carrier that can
# name any file records nothing. It is DISJOINT from the other two legs by construction:
# TASK_TARGET_RE needs `T-` + digits, and a plan slug is kebab-case (`PLAN_SLUG_RE`, ^[a-z0-9][a-z0-9-]*$)
# which admits neither `/` nor `.`, so no target can be read as two kinds.
NOTE_TARGET_RE = re.compile(r"^(?:lessons|patterns)/[A-Za-z0-9._-]+\.md$")


def _fu_id(text: str) -> str:
    """A collision-safe followup id: a hash of the text + a uuid4 nonce, so two identical captures at
    the same instant get DISTINCT ids (never merged into one logical followup)."""
    nonce = uuid.uuid4().hex
    return "fu_" + hashlib.sha256((text + "|" + nonce).encode("utf-8")).hexdigest()[:12]


def _clean_trigger(value):
    """Normalize a trigger field to a non-empty stripped phrase, else None.

    FAITHFUL, never fail-closed (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): this
    reports only what the event literally says. An absent / empty / whitespace-only / non-string trigger
    yields None, and each READER decides what that means — `_partition_open` reads None as ACTIONABLE
    (open and visible, the fail-SAFE direction), while `cmd_followup_arm` refuses to WRITE one. A single
    shared fail-closed predicate would be wrong for one of those two callers.
    """
    return value.strip() if isinstance(value, str) and value.strip() else None


def _clean_awaits(value):
    """Normalize an AWAITED-artifact ref to a non-empty stripped token, else None (T-10335).

    The sibling of `_clean_trigger`, under the same faithful-parse doctrine: report only what the event
    literally says, and let each READER decide what an absent value means. `_partition_open` reads None
    as "arrival not provable" => armed_waiting (the fail-SAFE direction: never fire on a guess), while
    `cmd_followup_add` refuses to WRITE an awaited artifact with no named trigger beside it.

    It is DELIBERATELY not parsed out of the trigger prose: an awaited artifact is a declaration, and a
    regex that guessed one would resurrect exactly the false-fire this field exists to end.
    """
    return value.strip() if isinstance(value, str) and value.strip() else None


# ── T-11964 — THE AWAITS GRAMMAR: three named shapes, and nothing else ────────────────────────────
# THE STATE THIS CLOSES. T-11863 made `--awaits` REQUIRED beside `--trigger`, closing the case
# `awaits is None` (200 of 207 armed records). It did NOT close the case of an awaits that is
# PRESENT, non-empty, accepted — and unfireable, because `_clean_awaits` above is a non-empty strip
# and nothing more, while the fire check is exact membership in an injected set of TASK ids. Measured
# on the kernel 2026-09-02: of 49 open armed records, 4 carried a task id (all 4 already terminal, i.e.
# exactly the 4 `armed_fired`), 4 a coordination id, 3 a plan slug, 35 a REPO PATH and 3 free prose —
# 45 of 49 unfireable, and the live resolvable population EMPTY. The parked T-11952 branch (@53f628e)
# adds 74 more of the same shape (39 paths, 32 spec ids, 2 coordination ids, 1 task id).
#
# WHY THE PATHS ARE THERE, read off the records rather than guessed: their trigger prose says
# "OWNER DECISION: bin/lib/debt.py:3268 ...", "WAITING ON FLEET DATA: ... bin/lib/nightly.py:1187".
# The path is WHERE the subject lives; the awaited moment is an owner decision or fleet data. The
# author needed a value for a REQUIRED flag and supplied the only concrete token in hand. So this is
# the T-11863 shape in a costume — that card closed "no awaits", this one closes "an awaits that is
# not an awaited artifact" — and the remedy is the same discipline, not a new mechanism.
#
# THE GRAMMAR. `awaits` is a DECLARED REFERENCE in one of three named shapes, each of which some
# reader can decide the ARRIVAL of. Anything else is refused at the write door (§cmd_followup_arm /
# §cmd_followup_add) and the author is told what IS resolvable:
#   T-NNNN                       — a task reaching a terminal status (done|wont-do). UNCHANGED: this
#                                  is the shape the fire check has always read, so every legacy
#                                  fireable record and every existing test is byte-identical.
#   X-NNNN                       — a SHARED-COORDINATION item reaching a terminal status. The honest
#                                  home for an obligation whose proof lives in ANOTHER repo, which is
#                                  never an acceptance-probe target from a V2 write
#                                  (`lessons/a-deferral-needs-a-named-carrier-before-it-reads-as-one`).
#                                  Four live records already name one, with trigger prose reading
#                                  "X-0460 reaches a terminal state" — the intent was there, the
#                                  reader was not.
#   events.jsonl#type=<type>     — a journal row of that EVENT CLASS appearing. This EXTENDS the
#                                  existing D-0030 load-bearing citation address space
#                                  (`task.py#_journal_locator`, which already resolves
#                                  `events.jsonl#ts=` / `#source_ref=` for --settle-observation), it
#                                  does NOT open a second one (CHARTER §P1 F1). It is the shape
#                                  T-11951's 20 kernel-side residuals need: each names a journal key
#                                  and its worker folded every one BY HAND to prove it had not fired.
#
# WHAT IS DELIBERATELY *NOT* IN THE GRAMMAR, so the next reader does not read the omissions as
# oversights. A REPO PATH: a file has no arrival — it exists from birth, so "fires when this path
# closes" is not a proposition, and firing on a path's next EDIT would fire on unrelated churn. A
# SPEC id: a spec's `active` status is its NORMAL state, not an awaited moment, and its terminal
# (`superseded`/`retired`) is almost never what these records wait for. A PLAN slug: 3 records name
# one and T-11951's worker already ruled that "a plan slug can never fire an arm"; plans have a
# terminal FSM, but the evidence (3 rows) does not carry a new resolver through CHARTER §P1 F4, and
# a plan-shaped need is expressible as the task that closes it. Each of these stays REFUSED, which
# is the honest answer: the item goes back to ACTIONABLE, where it is VISIBLE.
#
# THE PREFIX IS NAMED ONCE and printed in the refusal + the success line, so the fold, the two write
# doors, the operator and the tests cannot disagree about what an event-class awaits looks like
# (`lessons/subtract-on-a-declared-key-never-on-a-provenance-field`, corollary 1).
AWAITS_EVENT_PREFIX = "events.jsonl#type="

# ── T-12057 — THE FOURTH SHAPE: `events.jsonl#type=<t>@after=<ISO ts>` ────────────────────────────
# THE STATE THIS CLOSES. The bare event shape above arrives on MEMBERSHIP — a class with rows already
# in the journal fires the moment it is armed. That reading is honest (the moment did in fact arrive)
# and it is the RIGHT one for the shape T-11964 built it for: a key that has NEVER fired. It is the
# WRONG one for the class that turned out to dominate. Measured on the kernel 2026-09-04, of the 212
# followups left actionable after the owner's sweep an estimated 40-60 wait on the NEXT occurrence of
# a class the journal already carries thousands of (`nightly_run_completed`, `inspection_completed`,
# `bg_dispatch_halted`, `cross_done`) — so they cannot be armed AT ALL, and stayed in the actionable
# headline the owner reads as spam. T-12055 recorded that limit in SPEC-0095 rather than extending the
# grammar; this card extends it.
#
# WHAT THE SUFFIX ADDS AND WHAT IT LEAVES ALONE. `@after=<ts>` ANCHORS the wait in time: the awaits
# arrives iff a row of that type carries an envelope `ts` STRICTLY LATER than the suffix. Strictly, not
# `>=`: the operator writes the timestamp of a moment that HAS happened (their own land, the sweep they
# just ran), and a row at exactly that instant is part of what they are anchoring PAST, not the next
# occurrence they are waiting for. The BARE form is UNCHANGED byte-for-byte — no `@after=` means
# membership, exactly as before, so every legacy record and every existing test reads identically.
#
# WHY A SUFFIX ON THE ONE GRAMMAR AND NOT A SECOND FIELD (CHARTER §P1 F1/F2). A `--since` flag would be
# a second declared key the fold, both write doors, the refusal and the three readers would each have
# to learn, and it would be settable on the two CLOSING grammars where it means nothing. The suffix
# rides the ONE value that is already DECLARED, already parsed in ONE place, and already the sole fire
# key — so `awaits` stays one field with one parse home, and nothing new is stored.
#
# THE TIMESTAMP SPELLING IS THE JOURNAL'S OWN, ENFORCED, AND THAT IS WHAT MAKES THE COMPARISON A
# STRING COMPARE. `_AWAITS_AFTER_TS_RE` admits exactly `%Y-%m-%dT%H:%M:%SZ` — the shape every emitter
# in this repo writes (`dispatch.py`, `journal.py`, `batch_landing.py`) and the shape the envelope
# carries. Fixed-width, zero-padded, single timezone: lexicographic order IS chronological order over
# that set, so no datetime parsing is needed and none is done (this module stays leaf-up, SPEC-0080
# §P-A1). Any OTHER spelling — a local offset, a fractional second, a bare date — is REFUSED at the
# write door rather than silently compared, because a shape the ordering is not provably correct over
# would fire on the wrong rows and do it invisibly. Fail-closed, like every other admission here.
AWAITS_AFTER_SEP = "@after="

_AWAITS_TASK_RE = re.compile(r"T-\d{4,}\Z")
_AWAITS_CROSS_RE = re.compile(r"X-\d{4,}\Z")
_AWAITS_EVENT_TYPE_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
_AWAITS_AFTER_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")

AWAITS_GRAMMAR_HELP = (
    "`--awaits` must be a DECLARED reference whose ARRIVAL a reader can decide — one of:\n"
    "  T-NNNN                      a task reaching a terminal status (done|wont-do)\n"
    "  X-NNNN                      a shared-coordination item reaching a terminal status — the home\n"
    "                              for an obligation whose proof lives in ANOTHER repo (route it with\n"
    "                              `yitc-v2 cross request --to <project>` first, then await its id)\n"
    "  events.jsonl#type=<type>    a journal row of that event class appearing (snake_case type).\n"
    "                              ARRIVES ON MEMBERSHIP: a class that ALREADY has rows fires\n"
    "                              IMMEDIATELY, which is the honest reading of an already-arrived\n"
    "                              moment — but it is NOT how you wait for the NEXT one\n"
    "  events.jsonl#type=<type>@after=<ISO ts>\n"
    "                              the same class, ANCHORED IN TIME: arrives only when a row of that\n"
    "                              type carries an envelope `ts` STRICTLY LATER than <ISO ts> (a row\n"
    "                              at exactly that instant does NOT fire). This is how you wait for\n"
    "                              the NEXT occurrence of a class the journal already carries. The\n"
    "                              timestamp is the journal's own spelling and nothing else:\n"
    "                              YYYY-MM-DDTHH:MM:SSZ (e.g. events.jsonl#type=cross_done"
    "@after=2026-09-04T08:25:51Z)")


def split_event_awaits(awaits):
    """Split an EVENT-class awaits into `(event_type, after_ts_or_None)`, else None (T-12057). PURE.

    THE SINGLE PARSE HOME of the event grammar — both its shapes. `awaits_kind` classifies through it
    and the fire predicate reads through it, so the write door and the read side can never disagree
    about what a suffixed awaits means (`lessons/subtract-on-a-declared-key-never-on-a-provenance-
    field`, corollary 1: name the shape once). Returning the PARTS rather than a bool is what lets the
    fire branch stay one predicate: the caller needs the type and the anchor, not a re-parse.

    None means "no reader can decide this reference's arrival" — the same fail-closed answer
    `awaits_kind` has always given, for the same reason (accepting an unresolvable reference removes
    the item from the headline FOREVER and silently; refusing leaves it ACTIONABLE, which is visible).
    So every rejection below is deliberate, not a gap:
      - not the `events.jsonl#type=` prefix     — a different grammar, or none.
      - a type that is not snake_case            — unchanged from T-11964.
      - `@after=` with a non-ISO / empty value   — the ordering is provably correct only over the
                                                   journal's own fixed-width UTC spelling, so a shape
                                                   it is NOT correct over is refused, never compared.
      - a SECOND `@` anywhere in the value       — `events.jsonl#type=t@after=<ts>@after=<ts>` and
                                                   `type=t@x@after=<ts>` are both nonsense the operator
                                                   must see refused, not silently truncated to the
                                                   first split. Checked on BOTH halves after the split.
    """
    if not isinstance(awaits, str):
        return None
    a = awaits.strip()
    if not a.startswith(AWAITS_EVENT_PREFIX):
        return None
    rest = a[len(AWAITS_EVENT_PREFIX):]
    after = None
    if AWAITS_AFTER_SEP in rest:
        rest, _sep, after = rest.partition(AWAITS_AFTER_SEP)
        if not _AWAITS_AFTER_TS_RE.match(after):
            return None
    # No `@` survives in EITHER half: the type never contains one (snake_case), and a second
    # `@after=`/stray `@` in the anchor is refused rather than truncated away by the partition above.
    if "@" in rest or (after is not None and "@" in after):
        return None
    if not _AWAITS_EVENT_TYPE_RE.match(rest):
        return None
    return (rest, after)


def event_after_arrived(awaits, latest_event_ts=None) -> bool:
    """Has a row of this SUFFIXED awaits' class arrived STRICTLY AFTER its anchor? (T-12057). PURE.

    The ONE predicate the fire branch gains, and it answers ONLY for the suffixed shape: an awaits with
    no `@after=` returns False here and is decided — unchanged — by exact membership in the
    `arrived_ids` set. Two disjoint answers, so neither shape can shadow the other.

    WHY THIS IS NOT A WIDENING OF `arrived_ids`. That function returns a frozenset of EXACT strings and
    the fire branch reads `awaits in <set>`. A suffix carries a FREE timestamp, so admitting it by
    membership would mean enumerating every timestamp any record might name — not a set anyone can
    build. The anchor is a COMPARISON, so it is expressed as one. `arrived_ids` is therefore untouched,
    and the three bare grammars resolve exactly as they did (CHARTER §P1 F2 — the smallest edit that
    carries the claim).

    `latest_event_ts` is the per-type MAXIMUM envelope `ts`, collected by `_fold` in the walk it was
    already making. The maximum is sufficient and necessary: "some row of type t is strictly later than
    the anchor" is true iff the LATEST row of type t is, so one scalar per type answers it without
    keeping the rows. Missing type -> `""`, which is strictly less than every real timestamp, so an
    unseen class simply does not fire — the ordinary armed case.

    STRICTLY later (`>`), never `>=`: the operator anchors on a moment that HAS happened, so a row at
    exactly that instant belongs to what they anchored PAST. Lexicographic comparison IS chronological
    here because `split_event_awaits` admits only the journal's fixed-width UTC spelling."""
    parts = split_event_awaits(awaits)
    if parts is None:
        return False
    etype, after = parts
    if after is None:
        return False
    return (latest_event_ts or {}).get(etype, "") > after


# The per-kind (VERB, gloss) the `arm` success line is built from. The VERB is per-kind and not a
# uniform word on purpose: a task and a coordination item genuinely CLOSE, an event class ARRIVES, and
# a single verb would be inaccurate for one of them. It also keeps `arm`'s task-shaped line byte-identical
# to what it has always printed, which `tests/test_t10335_followup_awaited_artifact.py` pins verbatim —
# a widening must not silently re-word the sentence an existing operator (and an existing tripwire) reads.
_AWAITS_KIND_GLOSS = {
    "task": ("closes", "a task reaching a terminal status"),
    "cross": ("closes", "a shared-coordination item reaching a terminal status"),
    "event": ("arrives", "a journal row of that event class appearing"),
}


def awaits_kind(awaits):
    """Classify a DECLARED `awaits` reference into its resolvable KIND, else None (T-11964). PURE.

    Returns "task" / "cross" / "event" / None. None means NO reader can decide this reference's
    arrival — which is precisely the state that produced 45 of the kernel's 49 armed records.

    THE ASYMMETRY THAT MAKES THIS A FAIL-CLOSED PREDICATE, unlike its `_clean_awaits` neighbour. That
    function is a faithful PARSER and is deliberately permissive: it reports what the event literally
    says, so a LEGACY record keeps folding exactly as it always has. This is a WRITE-DOOR predicate,
    and the two misclassifications are not symmetric — accepting an unresolvable reference removes the
    item from the headline FOREVER and silently, while refusing a resolvable-looking one leaves it
    ACTIONABLE, which is visible and one command from any disposition. So: enumerated shapes only,
    never a "looks like an identifier" heuristic. A regex that GUESSED an awaited artifact out of a
    path or a prose selector would be the inferred-not-declared mistake `awaits` exists to end.

    NOT called by `_fold` or `_partition_open`. The READ side stays untouched (the T-11863 posture,
    held verbatim): a legacy unresolvable record still folds to `armed_waiting` — open, visible,
    disposable by hand — and re-arming that population is a separate pass that must run AFTER this.

    T-12057 QUALIFIES THAT SENTENCE PRECISELY, so it is not read as broader than it is. `awaits_kind`
    ITSELF is still called by neither, and the posture is intact: `_partition_open` now reads
    `split_event_awaits` — the SHAPE splitter this classifier delegates to — through `event_after_arrived`,
    and only ever to decide a SUFFIXED awaits. A legacy record carries no suffix, so the predicate
    returns False for it and its verdict is decided, unchanged, by the exact-membership branch. No
    record's fold moves because this function's grammar widened.
    """
    if not isinstance(awaits, str):
        return None
    a = awaits.strip()
    if _AWAITS_TASK_RE.match(a):
        return "task"
    if _AWAITS_CROSS_RE.match(a):
        return "cross"
    if a.startswith(AWAITS_EVENT_PREFIX):
        # T-12057 — DELEGATED, never re-implemented: `split_event_awaits` is the one parse home for
        # both event shapes, so a suffix this classifier accepted and the fire branch could not read
        # (or the reverse) is impossible by construction.
        return "event" if split_event_awaits(a) else None
    return None


# T-12055 — THE CAPTURE-MOMENT ADVISORY. The born-armed mechanism above has existed since T-11863
# and is barely used: measured on the kernel 2026-09-04, the headline read 246 actionable / 9 armed,
# and well over a hundred of the 246 named a waiting moment IN PROSE ("fires when T-NNNN closes",
# "BLOCKED until …"). The mechanism was never the gap — DELIVERY at the moment of typing was, which
# is the reader-side class T-10856 named. So the capture door SAYS SO, once, report-only.
#
# IT NAMES, IT NEVER GUESSES (the whole reason this is admissible under CHARTER §P1). The scan below
# finds `T-NNNN` / `X-NNNN` TOKENS and then hands each to `awaits_kind` — the SAME predicate both
# write doors use — so the advisory can only ever name a reference the fire check itself would
# resolve. It parses no trigger phrase, infers no wait, and proposes no `--trigger` text: the operator
# writes that, because armedness is a human judgement (§Why the trigger is DECLARED). A regex that
# mined a WAIT out of prose would be exactly the inferred-not-declared mistake `awaits` exists to end.
#
# THE EVENT GRAMMAR IS DELIBERATELY OUT OF IT. `events.jsonl#type=<t>` fires on MEMBERSHIP — a class
# with rows already in the journal fires IMMEDIATELY — so a "next occurrence of <t>" wait has no
# artifact to name, and advising one would manufacture the false-armed state T-11964 measured. Only
# the two CLOSING grammars are advised.
_ADVISORY_REF_RE = re.compile(r"(?<![\w-])(?:T|X)-\d{4,}(?![\w-])")


def advisory_candidate_refs(text, relates_to=None) -> list:
    """The awaits-grammar references a capture's own TEXT names, order-preserving and unique. PURE.

    ADMISSION IS `awaits_kind`, NOT THE SCAN REGEX. The regex is a cheap pre-filter over the prose;
    every token it finds is then put through the one grammar predicate, so this function cannot admit
    a shape the write doors would refuse. Reuse, never a second grammar (CHARTER §P1 F1) — and if the
    grammar ever narrows, this narrows with it in the same edit.

    `relates_to` — the PROVENANCE ref — is EXCLUDED. A capture filed under a task nearly always names
    that task in its own text (the auto-filed `P8-CARRIER: T-XXXX …` is exactly this shape), and
    advising "arm this on the thing it is ABOUT" would teach the precise conflation T-10335 separated:
    `relates_to` is what this is about, `awaits` is what fires it, and they are never one field.
    """
    skip = (relates_to or "").strip()
    out: list = []
    for tok in _ADVISORY_REF_RE.findall(text or ""):
        if tok == skip or tok in out or awaits_kind(tok) is None:
            continue
        out.append(tok)
    return out


def born_armed_advisory_line(fid: str, refs) -> str:
    """The ONE report-only sentence `followup add` prints over an actionable capture whose text names
    a still-open awaited artifact. PURE, so the wording is pinned without a subprocess.

    It states the CURRENT state ("born ACTIONABLE"), the FACT it noticed (the text names these refs),
    and the exact command that would change it — with the `--trigger` phrase left as a placeholder the
    operator fills, never a guess. It is CONDITIONAL by construction ("if that closure is what this
    waits for"), because the reference being present is evidence of a wait, not proof of one: the
    honest actionable case — a capture that merely MENTIONS a task — must read as fine here, and does.
    """
    named = ", ".join(refs)
    return (f"  born ACTIONABLE — the text names {named}; if that closure is what this waits for, "
            f"arm it: `yitc-v2 followup arm {fid} --trigger '<the moment in words>' "
            f"--awaits {refs[0]}` (report-only — nothing was changed)")


def arrived_ids(terminal_ids=frozenset(), terminal_cross_ids=frozenset(), seen_event_types=()) -> frozenset:
    """The ARRIVED set the fire check reads — the union of the three grammars' arrived members (T-11964).

    ONE set, built from three INJECTED corpora, exactly as `terminal_ids` has always been injected: the
    host owns the paths and the stores, this leaf owns the spelling. So `_partition_open`'s fire branch
    is UNCHANGED — it is still `awaits in <a set>`, and NOTHING new is stored (CHARTER §P1 F2: a wider
    view over reads that were already happening, not a new entity).

    WHY IT IS A SEPARATE SET FROM `terminal_ids` AND NOT A WIDENING OF IT. `_partition_open` reads
    `terminal_ids` TWICE — once for the fire check (`awaits in ...`) and once for the T-10658/T-11604
    stale-provenance marker (`relates_to in ...`). `relates_to` DOES carry X-NNNN refs today
    (`cli.py#_arm_cross_re_entry` writes them), so silently widening the one parameter would change the
    marker's population as a side effect of a change to the FIRE key — the exact ADD-vs-SUBTRACT
    blurring T-10335 and `lessons/subtract-on-a-declared-key-never-on-a-provenance-field` separated
    three cards apart. Two parameters, two claims.

    An event class ARRIVES the moment a row of that type EXISTS in the journal — membership, no
    ordering check. A class that already has rows at arm time therefore fires IMMEDIATELY, and that
    is the honest reading, not a defect: the awaited moment has in fact already happened, and
    `armed_fired` is surfaced UNFLOORED by the debt echo, so the outcome is LOUDER than the
    `armed_waiting` it replaces. The write door reports that row count at arm time (§cmd_followup_arm)
    so nobody arms one by accident.
    """
    return (frozenset(terminal_ids) | frozenset(terminal_cross_ids)
            | frozenset(AWAITS_EVENT_PREFIX + t for t in seen_event_types))


def _clean_fingerprint(value):
    """Normalize a SOURCE-CLUSTER fingerprint to a non-empty stripped token, else None (T-10779).

    The third sibling of `_clean_trigger` / `_clean_awaits`, under the same faithful-parse doctrine
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): report only what the event
    literally says, and let each READER decide what an absent value means. `_fold` reads None as "this
    followup was not born of a cluster" — which is the overwhelming majority and carries no obligation
    — while `cmd_followup_promote` reads a PRESENT value as a provenance obligation it must enforce.

    It is DELIBERATELY not parsed out of the text or out of `relates_to`: a fingerprint is `kind |
    normalized message`, which is free prose after the first `|`, and a regex mining one out of a
    capture would resurrect exactly the route-on-prose defect T-10335 and
    `lessons/report-only-advisory-never-exempts-a-contradiction` rule 1 both record. Declared or absent.
    """
    return value.strip() if isinstance(value, str) and value.strip() else None


def _instance_lines(events_path, _segment_lines=None) -> list:
    """The non-empty journal lines `_fold` replays, from ONE instance or from the SPEC-0168 instance
    PAIR. T-11208 (X-0952).

    `events_path` is either a single path (a str/Path — today's contract, and what almost every caller
    passes) or an ITERABLE of paths. The pair case exists because a followup captured on the MAIN
    checkout with no worktree is SANCTIONED (D-0049), while the card that promotes it is filed from a
    worktree branched BEFORE that capture — so the sanctioned order put the `followup_added` in an
    instance the filing verb never read, and `--promotes` refused a real open followup as unknown.

    INSTANCE SET = SPEC-0168 rule 1's, reused verbatim, never re-derived here: the repo-root
    `events.jsonl` on the checkout the verb runs in AND on that repo's MAIN checkout. This function
    RESOLVES nothing — the caller hands it the paths (bin/lib/task.py#_promote_lookup_events_paths,
    fed by the already-shipped bin/yitc-v2#_main_events_path). An ABSENT instance is ORDINARY: skip it,
    never a fault and never an empty-evidence signal.

    DE-DUPE BY RAW LINE, keep-first. The two instances share every landed row (`land` folds main's
    journal into the branch's — evidence_custody.py#_fold_main_journal_into_branch), so a plain concatenation
    would replay most of the corpus twice. Raw-line identity is enough because the journal is
    append-only and land's own fold dedupes the identical lines; a followup event replayed twice is
    idempotent anyway, so this is a cost guard, not a correctness one.

    ORDERING IS NOT DONE HERE — `_fold` owns it, for every input shape (T-11735). A followup's
    `status` is a FOLD over an FSM, not a bag of rows: replayed in physical line order, a
    `followup_promoted` that precedes its own `followup_added` is silently dropped by the replay's
    `fid in items` guard and the item then reads OPEN when it is terminal — journal LAYOUT deciding
    FSM outcome. T-11208 fixed that for the PAIR by stable-sorting here, and deliberately left the
    SINGLE-instance branch in file order for byte-identity. That asymmetry was itself the defect
    (X-1172/X-1175): a union-merged journal can invert a birth and its transition WITHIN one
    instance, so `followup list`/`show` (single) stranded a promoted row open while the `--promotes`
    gate (pair) read it correctly — identical content, two answers, decided by how many instances
    were replayed. The sort therefore moved DOWN into `_fold`, which ALREADY json-parses every line:
    ordering there costs zero extra parses, where sorting here would have added a second full parse
    pass over the whole journal (measured +336ms on a 112639-line journal, on a fold the SPEC-0119
    debt echo runs every session start). This function now returns de-duped lines in FILE order for
    both branches.

    `_segment_lines` — THE INJECTED PHYSICAL READ `(path) -> [stripped non-empty lines]`, applied to
    EVERY instance in `paths`. It arrives by INJECTION, never by import: this module is leaf-up and
    stdlib-only (SPEC-0080 §P-A1) — three sibling test files load it as a top-level `followup` off
    `bin/lib`, where a `lib.` import cannot resolve — so back-importing the journal lib would break
    the embedding contract. Every host injection site hands it `journal.segment_fold_lines`, which
    reads the WHOLE logical journal (every segment) through the same `fold_lines` primitive.

    SEGMENT-AWARENESS IS THE POINT, and it is why the parameter was RENAMED from `_fold_lines`
    (T-11734, X-1140/X-1181). It was born as a PERFORMANCE knob: the SPEC-0119 debt echo folds this
    same local journal alongside ~14 other readers in one invocation, and the host installs a
    request-scoped memo so the read happens ONCE (`journal.fold_rows` / `journal.rows_memo`). But it
    was handed `journal.fold_lines` — the SINGLE-FILE primitive, which sees the LIVE segment alone —
    and the default read below is a single `read_text` of one path, so the whole chain judged an
    UNBOUNDED horizon off a 7-day window. A followup whose `followup_added` row had rotated did not
    lose detail, it DISAPPEARED: the replay's `fid in items` guard drops every later transition for an
    id whose birth it never saw, so the record neither listed, showed, promoted nor dropped, while its
    row sat intact in an archive segment and `journal query --grep` found it. Measured on the kernel's
    own journal at the time of the fix: 357 of 1047 `followup_added` rows were inside the live segment,
    so 65.9% of the history was already out of reach — and the share grows with every rotation. The
    rename is the guard the migration leaves behind (the T-11596 precedent): the leaf can no longer
    declare a single-file reader while being handed a segment-aware one.

    APPLIED TO BOTH BRANCHES — the `not multi` gate is GONE (T-11734). It confined the injected reader
    to the SINGLE-instance branch, so the SPEC-0168 instance PAIR would have kept its live-only
    `read_text` and `--promotes` would still have refused a rotated followup as unknown. Both branches
    now take the same read, which is also what makes the two agree.

    THE STRIP IS UNCONDITIONAL, over whatever the source yields. `fold_lines` (and so
    `segment_fold_lines`) already returns stripped non-empty lines, making it a no-op there; doing it
    at the one read seam means an embedding that injects a reader with the RAW-line contract (the
    streaming `journal.segment_lines`) cannot silently widen the admitted set. De-dupe by raw line is
    unchanged and now spans segments — which is what keeps a row present in both a rotated archive
    segment and the live file from folding twice.

    Default None ⇒ the plain single-file read below. That fallback is kept deliberately, for the
    top-level test embeddings that inject nothing; every PRODUCTION call site injects, and
    `tests/test_t11734_followup_fold_segment_aware.py` asserts that no un-injected one is added.

    P5-safe throughout: an unreadable instance contributes nothing rather than raising."""
    if isinstance(events_path, (str, Path)) or events_path is None:
        paths = [events_path]
    else:
        paths = [p for p in events_path]

    lines: list = []
    seen: set = set()
    for raw_path in paths:
        if not raw_path:
            continue
        p = Path(raw_path)
        if _segment_lines is not None:
            # T-11734 — the injected reader spans the segment SET; applied to EVERY instance, so the
            # SPEC-0168 pair is segment-aware too. The strip below is a no-op on its contract.
            try:
                source = _segment_lines(p)
            except OSError:
                continue
        else:
            try:
                if not p.exists():
                    continue
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            source = text.splitlines()
        for raw_line in source:
            line = raw_line.strip()
            if not line or line in seen:
                continue
            seen.add(line)
            lines.append(line)
    return lines                                   # ordering is `_fold`'s — see the docstring


def _instance_rows(events_path, _segment_lines=None, _segment_rows=None):
    """T-12202 — the ALREADY-PARSED lane for `_fold_uncached`, or None when the line lane must be
    kept. Never a second reader: `_segment_rows` is the host's `journal.segment_rows`, which reads the
    SAME segment set through the SAME `fold_rows` primitive `_segment_lines` rides, so inside a
    `journal.rows_memo` scope it is SERVED, not re-read.

    WHY IT EXISTS. `_fold_uncached` is defined over LINES and `json.loads`-es every one of them
    itself, so inside `cli._debt_echo_lines` the corpus is parsed a SECOND time even though the
    request-scoped memo already holds it parsed (measured 2026-09-06 on this repo's 641,658-row
    journal: 10.8 s of a 56.2 s echo). Consuming the memo's parsed lane removes that parse; nothing
    about the replay, the FSM, the sort or any folded field moves.

    RETURNS None — the CALLER KEEPS THE LINE LANE — in every case where the two lanes could differ,
    which is what makes this byte-identical by construction rather than by care:
      - no injected rows reader, or no injected LINE reader (the un-injected test embeddings, whose
        default is a single `read_text`): nothing to pair the lanes on;
      - the SPEC-0168 instance PAIR (an iterable of paths): `_instance_lines` de-dupes ACROSS the two
        instances by raw line, which is where that guard earns its keep — the pair shares every
        landed row. The pair path is not moved, at all;
      - the two lanes are not INDEX-ALIGNED, which is the one thing this pairing rests on: an
        EMPTY/whitespace line (the line lane drops it, the rows lane tries to parse it) or an
        UNPARSEABLE line (`_rows_from_lines` skips it, so the rows list is shorter). Both are
        detected by construction — a blank in the stripped lines, or `len(rows) != len(lines)` —
        and answered by falling back, never by guessing an alignment;
      - any read error: the caller's own fallback path handles it exactly as before.

    THE DE-DUPE IS NOT DROPPED, IT IS APPLIED TO THE PAIRED LANE. `_instance_lines` de-dupes by RAW
    LINE, keep-first, and that guard IS live even on a single instance (measured on this repo's
    641,698-line journal, 2026-09-06: 2 duplicate lines). So the mask is computed on the LINE lane —
    one hash pass over strings the memo already holds, no parse — and applied to the row at the SAME
    index, which reproduces `[json.loads(l) for l in _instance_lines(...)]` element for element.

    P5-safe: reads, returns, never raises."""
    if _segment_rows is None or _segment_lines is None:
        return None
    # The input shape is `_instance_lines`': a single path, OR an iterable of paths. `_fold` RESOLVES
    # it to a list before calling down (so a one-shot iterable is not consumed by the memo key), so a
    # single instance reaches here as a 1-element list — normalise both, and take ONLY the single
    # case. A genuine PAIR (2+ instances) returns None: its cross-instance de-dupe is the guard this
    # function must not move.
    if isinstance(events_path, (str, Path)) or events_path is None:
        paths = [events_path]
    else:
        try:
            paths = list(events_path)
        except TypeError:
            return None
    if len(paths) != 1 or not paths[0]:
        return None
    p = Path(paths[0])
    try:
        lines = [ln.strip() for ln in _segment_lines(p)]
    except Exception:                              # noqa: BLE001 — an unreadable instance falls back
        return None
    if not all(lines):
        return None                                # a blank line un-aligns the lanes — line lane
    try:
        rows = _segment_rows(p)
    except Exception:                              # noqa: BLE001 — same fallback
        return None
    if not isinstance(rows, list) or len(rows) != len(lines):
        return None                                # an unparseable line un-aligns them — line lane
    seen: set = set()
    out: list = []
    for line, row in zip(lines, rows):
        if line in seen:
            continue                               # keep-first, exactly as `_instance_lines` does
        seen.add(line)
        out.append(row)
    return out


# ── T-12031 — the request-scoped FOLD-RESULT memo (the T-11453 / T-11438 shape, third instance) ──
#
# WHY A RESULT MEMO RATHER THAN A READ ONE. `journal.rows_memo` (T-11453, widened to the segment set
# by T-12029) already collapses the PHYSICAL read this fold rides on, and it also carries a
# parsed-ROWS lane — but `_fold` cannot consume that lane: `_instance_lines` dedupes by RAW-LINE
# identity for the SPEC-0168 instance pair, so the fold is defined over lines and json-parses every
# one of them itself. Measured inside one `cli._debt_echo_lines` (2026-09-03, T-12029's after-profile):
# `_fold` is invoked EXACTLY TWICE — `cli._open_followup_counts` and, through
# `_uncarried_p8_view -> debt.uncarried_p8_warns -> _p8_carrier_task_ids -> debt.p8_carrier_followups`,
# a second time — and the pair accounted for 1,192,248 of the session's 1,822,540 `json.loads` calls:
# exactly 2x the 596,129-row logical journal, paid at EVERY session-start and EVERY land tail.
#
# THE OUT-PARAMETERS ARE THE WHOLE HAZARD, so the memo is built around them. `_fold` takes
# `seen_event_types` + `closing_sessions` + `latest_event_ts` (T-12057) as OUT-parameters and the call
# sites pass DIFFERENT ones (one passes all three, another none). Keying the memo on the caller's out-param SHAPE
# would keep two entries and so two parses; keying it on the shape and reusing across shapes would
# silently DROP a fill. Neither is done: the entry is computed ONCE with BOTH out-parameters filled
# into MEMO-OWNED containers, and each call then copies out of them into whichever containers ITS
# caller passed. Every call shape therefore gets an out-parameter filled identically to the
# uncached fold, in any call order, off ONE parse.
#
# SCOPE DISCIPLINE, taken verbatim from `journal.rows_memo` / `cli._dispatch_events_memo`: the prior
# value is SAVED and RESTORED, so a nested scope degrades to the outer memo rather than leaking, and
# an exception inside the body can never leave a stale snapshot installed for a later, unrelated
# verb. OUTSIDE a scope `_fold` is a plain pass-through, so `followup list|promote|drop|arm`,
# `validate_promotes` and the audit-packet readers are byte-identical.
#
# STDLIB ONLY. `contextlib` keeps followup.py leaf-up (SPEC-0080 §P-A1) — this module still imports
# no host module, which is the property T-11453's own tripwire pins.
_FOLD_MEMO = None


@contextlib.contextmanager
def fold_memo():
    """Serve `_fold` from ONE parse per (journal, injected reader) for the duration of the scope.

    RE-ENTRANT (T-12208), on the same terms as `journal.rows_memo`: when a scope is already
    installed, the inner `with` is a pass-through that keeps the OUTER entries rather than replacing
    them with an empty dict. There is no path declaration to compare — the key already carries the
    resolved paths AND the injected reader (`_fold_memo_key`), so an outer scope can only ever SERVE
    a call the inner one would have made, never answer a different one."""
    global _FOLD_MEMO
    prior = _FOLD_MEMO
    if prior is not None:
        yield
        return
    _FOLD_MEMO = {}
    try:
        yield
    finally:
        _FOLD_MEMO = prior


def _fold_memo_key(paths, _segment_lines):
    """The entry key: the RESOLVED instance paths + the INJECTED physical reader.

    The reader is part of the key because it IS the read: `segment_fold_lines` spans the segment set
    while `None` reads the single live file, so two calls differing only in it are two different
    folds and must never be served from one another's entry."""
    return (tuple(str(p) if p else "" for p in paths), _segment_lines)


def _fold(events_path, _segment_lines=None, seen_event_types=None, closing_sessions=None,
          latest_event_ts=None, _segment_rows=None) -> dict:
    """The fold's front door — memo-served inside a `fold_memo()` scope, a plain fold outside one.

    Pass-through by default, so no caller's behaviour moves. See the block comment above for why the
    memo stores the out-parameter fills rather than keying on them.

    THE RECORDS ARE COPIED PER CALL, and that is not defensive habit: `_partition_open` WRITES
    derived `stale_provenance` / `provenance_closed_at` keys onto the records it walks (a render-time
    view field, by design). Handing the same dict objects to the next consumer would leak one
    consumer's render fields into the other's input — a behaviour change smuggled in by a read
    optimisation. The copy is O(followups) — hundreds — never O(journal lines), so it costs nothing
    against the full parse it replaces."""
    memo = _FOLD_MEMO
    if memo is None:
        return _fold_uncached(events_path, _segment_lines, seen_event_types, closing_sessions,
                              latest_event_ts, _segment_rows)

    # Resolve the instance list exactly as `_instance_lines` does, and pass THAT list down: the input
    # may legitimately be a one-shot iterable (SPEC-0168's instance pair), which the key would
    # otherwise consume before the fold could read it.
    if isinstance(events_path, (str, Path)) or events_path is None:
        paths = [events_path]
    else:
        paths = [p for p in events_path]

    key = _fold_memo_key(paths, _segment_lines)
    entry = memo.get(key)
    if entry is None:
        seen: set = set()
        closing: dict = {}
        latest: dict = {}
        # T-12202 — `_segment_rows` is deliberately NOT part of the memo key (`_fold_memo_key`):
        # the two lanes are the SAME rows off the SAME read, so an entry computed through either one
        # serves both, and keying on it would split the entry and re-pay the parse it removes.
        items = _fold_uncached(paths, _segment_lines, seen, closing, latest, _segment_rows)
        entry = (items, seen, closing, latest)
        memo[key] = entry
    items, seen, closing, latest = entry

    if seen_event_types is not None:
        seen_event_types.update(seen)
    if closing_sessions is not None:
        for tid, refs in closing.items():
            closing_sessions.setdefault(tid, set()).update(refs)
    # T-12057 — the THIRD out-parameter joins the entry on the SAME terms as the other two: filled
    # into a memo-owned container once, then copied out per call. `max` on the merge, not a blind
    # overwrite, so a caller passing a pre-seeded dict is never regressed to an older timestamp.
    if latest_event_ts is not None:
        for etype, ts_val in latest.items():
            if ts_val > latest_event_ts.get(etype, ""):
                latest_event_ts[etype] = ts_val
    return {fid: dict(rec) for fid, rec in items.items()}


def _fold_uncached(events_path, _segment_lines=None, seen_event_types=None, closing_sessions=None,
                   latest_event_ts=None, _segment_rows=None) -> dict:
    """Fold events.jsonl into {followup_id: {id, text, relates_to, status, trigger, awaits, into?, reason?, added_at}}.
    open = added and not yet promoted|dropped (the 2-state FSM, derived — nothing stored). P5-safe:
    an unparseable line / unknown id transition is skipped, never raised.

    `events_path` may be a single path OR an iterable of the SPEC-0168 instance pair — see
    `_instance_lines`, which owns that whole question (T-11208). Nothing below changes with the input
    shape: the replay, the 3-state FSM and every folded field are identical either way.

    `trigger` + `awaits` (SPEC-0095 §Armed) are ATTRIBUTES of an OPEN record, born from `followup_added`
    and re-set TOGETHER by any later `followup_armed` (last write wins; an absent/`null` key CLEARS that
    attribute — `trigger: null` DISARMS, `awaits: null` un-pins the awaited artifact). They are applied
    ONLY to a record that is still OPEN: arming a promoted/dropped item is meaningless, and silently
    honoring it would let a terminal record re-enter the armed view. Status is NEVER touched here — the
    FSM legs stay the sole writers of `status`.

    `relates_to` is folded as PROVENANCE ONLY and is never re-written by an arm: what a followup is ABOUT
    does not change when the operator re-states what it WAITS FOR (T-10335).

    TIMESTAMP ORDER, for EVERY input shape (T-11735 — X-1172/X-1175). `status` is a fold over an FSM,
    so the replay ORDER decides the outcome: a transition leg replayed before its own
    `followup_added` hits the `fid in items` guard, takes the P5-safe unknown-id skip, and the later
    birth then re-creates the record as `open` — permanently stranded. Physical line order does NOT
    guarantee ts order: the journal is append-only per instance, but a union-merge can interleave two
    instances' appends and invert a birth against its own transition WITHIN the merged file. So the
    parsed events are STABLE-sorted by the envelope `ts` before the replay. Sorting HERE rather than
    in `_instance_lines` is deliberate: this function already parses every line, so ordering is free,
    where sorting the raw lines needs a second full parse pass. Stable ⇒ equal-ts rows keep their
    file order, so a well-ordered journal replays exactly as before. Missing / mis-shaped `ts` sorts
    as "" (earliest) — deterministic and never raising, and the P5-safe skips below run BEFORE the
    sort, so a malformed row is dropped rather than sorted.

    The FSM legs, the `fid in items` guard and every folded field are UNCHANGED by that ordering — a
    transition with no birth ANYWHERE is still skipped, never raised.

    `seen_event_types` (T-11964) is an OPTIONAL OUT-PARAMETER: pass a set and this fold ADDS every
    journal event TYPE it walks past to it. It is an out-param rather than a second return value, and
    rather than a second helper, for one reason — this function ALREADY parses every line of the
    journal, so collecting the type set here costs NOTHING, where any separate reader would pay a
    second full parse of a 167k-line file on every session-start debt echo. Nothing about the returned
    items changes, and every existing caller (which passes nothing) is byte-identical. The set is what
    `arrived_ids` turns into the `events.jsonl#type=` half of the fire set.

    `latest_event_ts` (T-12057) is a THIRD out-parameter of exactly that shape and for exactly that
    reason: pass a dict and this fold fills it with `event type -> the LATEST envelope ts seen for that
    type`. It is filled in the SAME walk, on the same row, one dict write per row — the map the
    `events.jsonl#type=<t>@after=<ts>` fire predicate (`event_after_arrived`) compares against. The
    MAXIMUM is all it keeps, because "some row of type t is strictly later than the anchor" is true iff
    the LATEST row of type t is. A row whose `ts` is missing OR NOT THE JOURNAL'S OWN FIXED-WIDTH UTC
    SHAPE is skipped for THIS map — admitted by the very regex `split_event_awaits` admits the ANCHOR
    with, because the comparison is chronological only over that set and a mis-shaped `ts` can sort
    ABOVE every real timestamp. It still counts toward `seen_event_types`, whose claim is mere
    existence, so the bare membership grammar is untouched. Every existing caller passes nothing and is
    byte-identical.

    `closing_sessions` (T-12019) is a SECOND out-parameter of exactly the same shape and for exactly
    the same reason: pass a dict and this fold fills it with `task id -> set of session refs that
    CLOSED that task and landed the closure` — the `session_ref` of its `task_closed` row, and the
    `session_ref` of the `land_completed` row whose branch is `task/<id>`. Both rows are already
    walked by this loop, so collecting them costs nothing, where a separate reader would pay a second
    full parse of the journal on every session-start debt echo. They are collected ABOVE the
    `followup_id` early-continue below, because neither row carries one. Every existing caller passes
    nothing and is byte-identical.
    """
    items: dict = {}
    parsed: list = []
    # T-12202 — `_segment_rows` is an OPTIONAL injected ALREADY-PARSED lane, taken ONLY on the
    # single-instance shape and only when `_instance_rows` can prove the two lanes identical (it owns
    # that whole question, and answers None whenever they could differ, keeping the line lane). Given
    # it, this loop stops re-`json.loads`-ing a corpus the request-scoped memo already holds parsed;
    # everything below — the P5 skips, the out-parameters, the stable ts sort, the FSM replay and
    # every folded field — is the same code on the same events.
    _rows = _instance_rows(events_path, _segment_lines, _segment_rows)
    _source = (_rows if _rows is not None
               else _instance_lines(events_path, _segment_lines))
    for idx, entry in enumerate(_source):
        if _rows is None:
            try:
                ev = json.loads(entry)
            except Exception:
                continue
        else:
            ev = entry
        if not isinstance(ev, dict):
            continue
        if seen_event_types is not None or latest_event_ts is not None:
            et_seen = ev.get("type")
            if isinstance(et_seen, str) and et_seen:
                if seen_event_types is not None:
                    seen_event_types.add(et_seen)
                if latest_event_ts is not None:
                    # T-12057 — ADMITTED BY THE SAME REGEX THE ANCHOR IS (audit-post finding,
                    # 2026-09-04). This map is compared against an `@after=` anchor by STRING
                    # ordering, and that ordering is chronological ONLY over the journal's
                    # fixed-width UTC shape. A row carrying a mis-shaped `ts` — `"zzzz"`, a local
                    # offset, a bare date — is not merely unordered against the anchor, it can sort
                    # ABOVE every real timestamp and fire an armed waiter that nothing legitimate
                    # arrived for. `split_event_awaits` already refuses that shape on the ANCHOR
                    # side; admitting it on the ROW side would leave the guarantee true at the write
                    # door and false at the fold, which is the half-enforced shape the write-door
                    # regex exists to prevent. Both sides, one regex.
                    #
                    # SKIPPED, never coerced: this map's claim is "the latest COMPARABLE ts of this
                    # type", so a row it cannot order simply does not participate. The row still
                    # counts toward `seen_event_types`, whose claim is mere EXISTENCE — so the BARE
                    # membership grammar is completely unaffected by this narrowing, and a class
                    # whose only rows are mis-shaped still fires the bare form exactly as before.
                    ts_seen = ev.get("ts")
                    if (isinstance(ts_seen, str) and _AWAITS_AFTER_TS_RE.match(ts_seen)
                            and ts_seen > latest_event_ts.get(et_seen, "")):
                        latest_event_ts[et_seen] = ts_seen
        # stable key: ts first, then arrival index — `sorted` is stable anyway, but carrying the
        # index makes the tie-break explicit rather than an implementation detail of the sort.
        parsed.append((str(ev.get("ts") or ""), idx, ev))
    parsed.sort(key=lambda r: (r[0], r[1]))
    for _ts, _idx, ev in parsed:
        et = ev.get("type")
        data = ev.get("data") or {}
        if closing_sessions is not None:
            # T-12019 — the closure-window session refs, collected here because this loop already
            # walks these rows. A task's closure reaches `main` through TWO sessions in the ordinary
            # shape: the one that recorded `task_closed` (a worker, in its worktree) and the one that
            # ran the `land` folding it (often another). Both are the card's OWN closure window, so
            # both are collected into ONE set per task id; a followup captured by either was captured
            # BY CONSTRUCTION at that closure, not independently of it.
            _sref = ev.get("session_ref")
            if isinstance(_sref, str) and _sref:
                _closing_tid = None
                if et == "task_closed":
                    _closing_tid = ev.get("task_id") or data.get("task_id")
                elif et == "land_completed":
                    _branch = data.get("branch")
                    if isinstance(_branch, str) and _branch.startswith("task/"):
                        _closing_tid = _branch[len("task/"):]
                if isinstance(_closing_tid, str) and _closing_tid:
                    closing_sessions.setdefault(_closing_tid, set()).add(_sref)
        fid = data.get("followup_id")
        if not fid:
            continue
        if et == "followup_added":
            items[fid] = {"id": fid, "text": data.get("text", ""),
                          "relates_to": data.get("relates_to"), "status": "open",
                          "trigger": _clean_trigger(data.get("trigger")),
                          "awaits": _clean_awaits(data.get("awaits")),
                          "actor": data.get("actor"),   # T-10405 — WHO captured it (born-only, immutable)
                          # T-10779 — the SOURCE cluster this followup was promoted FROM, when it was
                          # born of one (a frontend-error fingerprint, SPEC-0170). Born-only and
                          # immutable, exactly like `actor`: an arm/unarm re-states what a followup
                          # WAITS FOR, never what it CAME FROM. Absent for every ordinary capture.
                          "fingerprint": _clean_fingerprint(data.get("fingerprint")),
                          # T-12019 — WHICH SESSION captured it. Born-only and immutable, exactly
                          # like `actor` and `fingerprint`: an arm/unarm re-states what a followup
                          # WAITS FOR, never where it CAME FROM. Read by the stale-marker's
                          # by-construction check alone.
                          "session_ref": ev.get("session_ref"),
                          "added_at": ev.get("ts")}
        elif et == "followup_armed" and fid in items and items[fid]["status"] == "open":
            # arm/unarm re-state the WHOLE awaited condition: an omitted key clears its attribute, so a
            # re-arm can always pull a wrongly-FIRED item back to armed (T-10335 AC2). Never touches
            # `relates_to` (provenance) nor `status` (the FSM).
            items[fid]["trigger"] = _clean_trigger(data.get("trigger"))
            items[fid]["awaits"] = _clean_awaits(data.get("awaits"))
        elif et == "followup_promoted" and fid in items:
            items[fid]["status"] = "promoted"
            items[fid]["into"] = data.get("into")
        elif et == "followup_dropped" and fid in items:
            items[fid]["status"] = "dropped"
            items[fid]["reason"] = data.get("reason")
    return items


def _closed_before_capture(rel: str, it: dict, closed_at_by_id) -> bool:
    """True iff the provenance task PROVABLY closed BEFORE this followup was captured (T-11604).

    The ordering half of the stale-provenance marker. Both timestamps are already in hand — the
    record's `added_at` (already read; it is the sort key) and the card's `closed_at` (handed over by
    the host's one terminality scan) — so nothing new is computed or stored.

    Returns True ONLY on proof. Any missing half — no mapping supplied, no recorded `closed_at`, no
    `added_at` — is UNPROVEN, not safe: it returns False, and the caller's marker fires exactly as it
    did before this check existed. Comparison is a plain string compare, which is correct and exact
    for the ISO-8601 `...Z` stamps every one of these fields carries (`_fold` reads `ev["ts"]`, and
    `closed_at` is written by `task close` in the same shape); a value that is not such a stamp
    compares as an ordinary string and, being unprovable either way, only ever leaves the marker on.
    """
    if not closed_at_by_id:
        return False
    closed_at = closed_at_by_id.get(rel)
    added_at = it.get("added_at")
    if not closed_at or not added_at:
        return False
    return added_at > closed_at


def _captured_in_closure_window(rel: str, it: dict, closing_sessions) -> bool:
    """True iff this followup was captured BY CONSTRUCTION at its provenance's own closure (T-12019).

    The by-construction half of the stale-provenance marker, and the reason X-1239/X-1241 were
    filed. `relates_to` names the card its author was working on, and the overwhelmingly common
    shape is a followup FILED AT THAT CARD'S CLOSURE — noticed while writing the closure, captured
    minutes before the `task_closed` row. Such a row is younger than the closure, so the T-11604
    ordering check below never suppresses it, and the marker fired on essentially every one of them.
    MEASURED on kupiclub (X-1241): of 134 marked rows 125 were still LIVE against the checkout — a
    reader trusting the marker would have dropped ~93% of rows wrongly.

    THE PROOF IS AN EXACT MATCH ON RECORDED SESSION REFS, never an inference. A task's closure
    reaches `main` through TWO sessions in the ordinary shape — the one that recorded `task_closed`
    (a worker, inside its worktree) and the one that ran the `land` that folded it (often another) —
    and `closing_sessions` carries BOTH as one set per task id. A capture from either session was
    made INSIDE that closure, so "the closing land may already have fixed it" is not a possibility
    about it: the capture and the closure are the same act.

    FAIL-OPEN, on the same terms as `_closed_before_capture`. No mapping, no set for this task, or a
    record with no `session_ref` (every row born before T-12019) is UNPROVEN, not safe: it returns
    False and the marker fires exactly as it did before. This check only ever SUBTRACTS a firing it
    can prove is by-construction, so it cannot re-open X-0486 by guessing a row safe.
    """
    if not closing_sessions:
        return False
    refs = closing_sessions.get(rel)
    mine = it.get("session_ref")
    if not refs or not mine:
        return False
    return mine in refs


def _partition_open(items: dict, terminal_ids=frozenset(), closed_at_by_id=None,
                    fire_ids=None, closing_sessions=None, latest_event_ts=None) -> dict:
    """Partition the OPEN followups into the three DERIVED groups the debt echo and `list` both render.

    Computed at READ time from the folded records + `terminal_ids` (the caller's set of task ids whose
    status is terminal — done|wont-do). NOTHING is stored: this is a view, exactly as `open` itself is.

      actionable    — open, no trigger. Needs a disposition NOW; the debt echo's headline count.
      armed_fired   — open, triggered, and `awaits` has ARRIVED — either a member of `fire_ids`
                      (the three bare grammars), or a `@after=`-suffixed event awaits whose class has
                      a row strictly later than its anchor in `latest_event_ts` (T-12057). The artifact it
                      WAITED FOR arrived, so the moment it awaited has ARRIVED: it is due, and the echo
                      surfaces it UNFLOORED. This is the check that makes an armed waiter impossible to
                      suppress indefinitely (T-10309 audit-pre finding 1).
      armed_waiting — open, triggered, moment not yet provably arrived. Not stale, not yet actionable;
                      counted but never allowed to nag.

    TWO SETS, TWO CLAIMS (T-11964) — and the second one DEFAULTS to the first, so every existing caller
    and every existing test is byte-identical. `fire_ids` is the set whose membership means AN AWAITED
    MOMENT ARRIVED; `terminal_ids` stays the set of TERMINAL TASK ids and is read ONLY by the
    stale-provenance marker below. They were one parameter until the fire set widened past task ids
    (the `arrived_ids` grammar), and they had to separate at that moment rather than later: `relates_to`
    ALREADY carries X-NNNN refs (`cli.py#_arm_cross_re_entry` writes them), so a single widened set
    would have changed the MARKER's population as an invisible side effect of a change to the FIRE key.
    That is precisely the ADD-vs-SUBTRACT blurring T-10335 and T-11563 separated — and the marker's own
    "NOT the fire key returning" argument below only holds while the two sets are actually distinct.
    `fire_ids=None` means "the fire set is the terminal-task set", which is what it was before.

    THE STALE-PROVENANCE MARKER — a REPORT, never a route (T-10658 / X-0486). Each ACTIONABLE row also
    gets a derived `stale_provenance` flag. The task it was noticed under has CLOSED, so the followup
    may already be fixed by that very land — the X-0486 hole, where a landed fix left its source
    capture open and later sessions re-promoted it into duplicate cards (3 wasted dispatch cycles + 3
    wont-do cards in one revizia).

    THE FLAG'S CONDITION IS THREE-PART (T-11604 + T-12019) — membership, ordering AND provenance:
      (i)   `relates_to` names a task in `terminal_ids`, and
      (ii)  the closing land could POSSIBLY have fixed the row — i.e. the row is NOT provably younger
            than the closure. Suppressed only where BOTH timestamps are in hand AND `added_at` is
            strictly after the provenance's `closed_at`, and
      (iii) the row was not captured BY CONSTRUCTION at that closure — i.e. its own `session_ref` is
            not a recorded closure-window session of that card (`_captured_in_closure_window`).

    WHY (iii) EXISTS (T-12019, resolving X-1239 + X-1241). (ii) subtracts only rows captured AFTER
    the closure. The dominant real shape is the opposite: a followup FILED AT the closing session is
    captured minutes BEFORE the `task_closed` row, so (ii) never reached it and (i) always held —
    the marker fired on essentially every close-time filing. kupiclub measured it twice: 125 of 134
    marked rows still LIVE, and — worse — four rows where even a CORRECT "already fixed" conclusion
    named the WRONG mechanism (two were fixed by later, unrelated cards, not by the closing land the
    marker named). A marker that offers a reason the reader can go and check, whose reason does not
    hold, costs more than a plain miss. (iii) removes exactly the by-construction population, and
    §The wording below removes the mechanism claim from what survives.

    WHY (ii) EXISTS, and why the original one-part condition had to change. T-10658 justified the
    marker on a cost argument written into this docstring: "a false marker costs one glance while a
    missed one costs exactly nothing". That is true at LOW prevalence and false at high. MEASURED on
    this repo's live open set, 2026-08-26, BEFORE this change: of 63 actionable rows, 52 named a
    terminal task and 52 of those 52 were flagged — the marker fired on 100% of the rows it was
    ELIGIBLE to fire on, so it partitioned the eligible set into one bucket and the one glance was
    paid 52 times rather than once. A flag that is on almost always distinguishes almost nothing.

    AND IT CONVERGES THERE STRUCTURALLY, not by bad luck. `relates_to` names the card its author was
    WORKING ON when they noticed the thing, and that card closes as a matter of course. Folding
    capture-time minus closure-time over those 52 rows, the deciles run -21.7h, -1.3h, -0.4h, -0.19h,
    -0.06h, -0.05h, -0.03h, -0.01h, +0.28h, +6.6h — the mass sits within MINUTES of the closure. The
    one-part flag therefore tracked TIME PASSING, which in this store is immediate, and not the thing
    it claimed.

    (ii) IS A RULE, NOT A TUNING (SPEC-0165). It asserts a NECESSARY CONDITION on the marker's own
    claim: for a land to have fixed a row, the row must have existed when the land ran. A followup
    captured AFTER its provenance reached terminal status provably CANNOT have been fixed by it,
    because the closure happened first. Nothing here is calibrated to today's ratio, and no prevalence
    number is asserted anywhere in the code or its tests — a tripwire on the ratio would be a bell on
    a door meant to open.

    FAIL-OPEN ON THE MARKER, DELIBERATELY. Unknown ordering — a terminal card with no `closed_at`, a
    record with no `added_at`, or a caller that passes no `closed_at_by_id` at all — leaves the marker
    firing exactly as it did before. The rule only ever SUBTRACTS a proven impossibility, so it can
    never re-open X-0486 by guessing a row safe.

    WHAT (ii) DOES NOT DO, so the next reader does not mistake its reach. It removes the rows the
    closure PROVABLY could not have fixed. It does not remove a row whose closing diff simply never
    touched its subject — on the live set it took the flagged count from 52 of 52 eligible to 41 of
    52. That residual is real and is reported rather than claimed away. Three richer routes were
    considered and REJECTED at analysis:
      - keying on the card's `created_at` ("the row predates the card, so the card may have been
        created to fix it") cuts far deeper, but the task's AC2 explicitly requires that a followup
        captured DURING its provenance card, on that card's own subject, STAY marked — the X-0486
        shape. Fenced off by acceptance, not overlooked;
      - keying on the provenance's last SHIP commit is stricter than `closed_at` in principle, but
        measured it removes FEWER rows (8 vs 11), because `commit_landed` also carries the Stage-9
        closure-record and land bookkeeping commits that post-date `closed_at`. Separating ship from
        bookkeeping means classifying commit SUBJECTS — a prose heuristic buying 2 further rows;
      - matching the followup's named surface against the closing diff means parsing free-form prose
        for file paths — the inferred-not-declared mistake `awaits` exists to end.

    THIS IS NOT THE T-10335 FIRE KEY RETURNING — the distinction is ADD vs SUBTRACT. Firing on
    `relates_to` claimed an awaited moment had ARRIVED, which RECLASSIFIED the row out of the headline;
    its false positives silenced captures, and that is what makes it a defect. This marker claims
    nothing about arrival and moves no row between groups: a flagged followup stays `actionable`, stays
    in the headline count, and merely gains a hint for the human who reads it. So `awaits` remains the
    SOLE fire key (the invariant below is untouched), and a missed marker still costs exactly nothing
    — the row keeps the visibility it already had. What a FALSE marker costs is no longer waved off as
    "one glance": at the measured prevalence it was one glance per eligible row, which is why the
    condition above has a second part.

    Membership is an EXACT match against `terminal_ids`: `relates_to` is free-form prose, and a regex
    that guessed a task id out of it would be the inferred-not-declared mistake `awaits` exists to end
    (`lessons/report-only-advisory-never-exempts-a-contradiction` Rule 1 — route on the enumerated
    half, never the prose; here nothing routes at all, which is why the prose key is admissible). Prose
    naming no id simply never matches, and that unmarked row is exactly as visible as it is today.
    Only ACTIONABLE rows are marked: an armed row already carries its own DECLARED fire key, and a
    second provenance-keyed hint beside it would re-blur the two fields T-10335 separated.

    THE FIRE KEY IS `awaits`, NEVER `relates_to` (T-10335). `relates_to` is PROVENANCE — what the
    followup is ABOUT — and reading it as the awaited condition fired 9 live followups whose real
    awaited moment (the next revizia run, the next `-C` consumer init, ...) had not happened. A
    followup fires because the thing it WAITED FOR arrived, never because the thing it was ABOUT closed.

    HONEST LIMIT — a trigger naming a plan slug or a bare future EVENT ("next real dispatch") has no
    machine-resolvable awaited artifact, so it declares no `awaits`, can never auto-fire, and stays
    `armed_waiting` until disposed by an explicit act (`unarm` when the trigger goes moot, or
    promote/drop). The fire check proves arrival for the artifact-named class only; it never GUESSES
    arrival for the rest. Unknown => not fired. This is also the MIGRATION path: every record captured
    before `awaits` existed folds to `awaits: None` and so reads `armed_waiting` — open, visible, and
    disposable by hand, never silently fired and never silently dropped.

    Every group is sorted by `added_at` (oldest first), the order `list` has always printed in.
    """
    if fire_ids is None:
        fire_ids = terminal_ids
    groups: dict = {"actionable": [], "armed_waiting": [], "armed_fired": []}
    for it in items.values():
        if it.get("status") != "open":
            continue
        if not it.get("trigger"):
            # Derived at READ time, exactly like the partition itself — nothing is stored, and the row's
            # group is UNCHANGED by the flag (report, not route).
            rel = it.get("relates_to")
            it["stale_provenance"] = (bool(rel) and rel in terminal_ids
                                      and not _closed_before_capture(rel, it, closed_at_by_id)
                                      # T-12019 — the by-construction conjunct. Suppresses the
                                      # close-time filing the marker fired on by construction.
                                      and not _captured_in_closure_window(rel, it, closing_sessions))
            if it["stale_provenance"]:
                # T-12019 — the FACT the surviving marker states. Read off the mapping the ordering
                # check already holds; nothing is computed or stored beyond this render-time field.
                it["provenance_closed_at"] = (closed_at_by_id or {}).get(rel)
            groups["actionable"].append(it)
        # T-12057 — TWO DISJOINT ARRIVAL TESTS, or-ed at the ONE fire branch. The first is exact
        # membership in the injected `fire_ids` set and decides all THREE bare grammars byte-for-byte
        # as it always has; the second answers ONLY for a `@after=`-suffixed event awaits, which no
        # set can express (see `event_after_arrived`). Neither can shadow the other: a suffixed awaits
        # is never a member of `fire_ids` (its literal string is not in it), and an unsuffixed one
        # makes the predicate return False. `latest_event_ts=None` therefore reads as "no suffixed
        # awaits can fire", which is what every caller that does not inject the map already means.
        elif it.get("awaits") in fire_ids or event_after_arrived(it.get("awaits"), latest_event_ts):
            groups["armed_fired"].append(it)
        else:
            groups["armed_waiting"].append(it)
    for rows in groups.values():
        rows.sort(key=lambda r: r.get("added_at") or "")
    return groups


def open_followup_counts(events_path, terminal_ids=frozenset(), closed_at_by_id=None,
                         _segment_lines=None, terminal_cross_ids=frozenset(),
                         _segment_rows=None) -> dict:
    """The 3 OPEN-followup counts — the host's injection point for the SPEC-0119 debt echo.

    Reuses the ONE fold + the ONE partition, so the echo can never disagree with `followup list`.

    `actionable_stale` rides along as a 4th key: the SUBSET of `actionable` whose provenance task has
    closed (T-10658) and could still have been fixed by that closure (the T-11604 ordering check —
    `closed_at_by_id` maps each terminal id to its `closed_at`; omit it and the marker behaves exactly
    as it did before that check existed). It is a subset, NOT a 4th group — `actionable` still counts
    every actionable row, stale ones included, so the headline the owner reads is unchanged.

    `terminal_cross_ids` + the fold's observed event types widen the FIRE set only (T-11964,
    `arrived_ids`): the stale-provenance marker keeps reading `terminal_ids` alone. Omit the cross set
    and the fire behaviour is exactly what it was — the event-class half comes free from the fold this
    call already runs.
    """
    seen: set = set()
    closing: dict = {}
    latest: dict = {}   # T-12057 — per-type latest ts, filled by the SAME walk (no second pass)
    items = _fold(events_path, _segment_lines, seen_event_types=seen, closing_sessions=closing,
                  latest_event_ts=latest, _segment_rows=_segment_rows)
    groups = _partition_open(items, terminal_ids, closed_at_by_id,
                             fire_ids=arrived_ids(terminal_ids, terminal_cross_ids, seen),
                             closing_sessions=closing,   # T-12019 — the by-construction suppression
                             latest_event_ts=latest)     # T-12057 — the `@after=` anchor comparison
    counts = {k: len(v) for k, v in groups.items()}
    counts["actionable_stale"] = sum(1 for it in groups["actionable"] if it.get("stale_provenance"))
    return counts


def _awaits_shape_refusal(awaits: str, verb: str) -> str:
    """The T-11964 unresolvable-shape refusal, worded ONCE for both write doors.

    Two doors, ONE claim — the same rule T-11863 established for the missing-awaits refusal: a
    followup reaches `armed` via `arm` AND via `add --trigger`, so a check on only one leaves the hole
    open at the other. Sharing the text (rather than copying it) also keeps the named grammar in
    `AWAITS_GRAMMAR_HELP` the single thing an author has to learn.

    It NAMES THE ALTERNATIVE, not just the refusal. An author refused here has a real obligation in
    hand and needs somewhere to put it, or the refusal just relocates the problem: leave it ACTIONABLE
    (visible, awaiting disposition — the honest state for a bare future event), route it as a `cross
    request` when the proof lives in another repo and await the resulting X-NNNN
    (`lessons/a-deferral-needs-a-named-carrier-before-it-reads-as-one`), or discard it. That third
    branch is exactly what T-11951's 40 residuals needed and could not express.
    """
    return (f"followup {verb} --awaits {awaits!r} names no resolvable awaited artifact — refusing, "
            f"because an armed followup LEAVES the actionable headline and this one could never fire, "
            f"which is strictly worse than staying visible (the T-11863 defect in a new shape: that "
            f"card closed `awaits` ABSENT, this closes `awaits` PRESENT but unresolvable).\n"
            f"{AWAITS_GRAMMAR_HELP}\n"
            f"A repo PATH, a SPEC id or a plan slug is NOT an awaited artifact: a file has no arrival, "
            f"and a spec's `active` status is its normal state, not a moment. If the awaited moment is "
            f"a bare future event, an owner decision or fleet data, LEAVE THE ITEM ACTIONABLE "
            f"(visible, awaiting an explicit disposition); if its proof lives in ANOTHER repo, route it "
            f"with `yitc-v2 cross request --to <project>` and await the X-NNNN it allocates; otherwise "
            f"discard it with `yitc-v2 followup drop <id> --reason ...`.")


def cmd_followup_add(args, *, append_event, die, actor=None, stdin_ingest=None,
                     open_refs=None) -> None:
    """`followup add --text <t> [--relates-to <ref>] [--trigger <phrase>] [--awaits <artifact>]` — append
    followup_added, print the id. NO worktree (the D-0049 append-only-journal exception: same MECHANISM
    as `event`).

    `--trigger` captures the followup BORN-ARMED: it names the future moment this item waits for, so it
    does not inflate the actionable debt headline. An empty/whitespace-only `--trigger` REFUSES rather
    than silently dropping to actionable — passing the flag is a claim that a trigger exists.

    `--relates-to` is PROVENANCE (what this is ABOUT); `--awaits` is the AWAITED artifact whose closure
    IS the trigger's arrival — the only thing the fire check reads (T-10335). The two flags are now
    REQUIRED TOGETHER, in BOTH directions: `--awaits` without `--trigger` REFUSES (an awaited artifact
    with no named moment would be armed-but-unnamed), and `--trigger` without `--awaits` REFUSES too
    (T-11863 — a named moment with no artifact to fire it is an unfireable waiter, the state the 200
    measured records were in). So `armed <=> trigger AND awaits` at this door exactly as at `arm`'s,
    which is the same stranding `promote --into` learned from X-0165, and it holds the invariant
    the partition branches on.

    `--from-stdin` (T-11244, E-0054) reads those same fields as a YAML mapping on stdin — the
    shell-proof path for prose carrying backticks. Hoisted ABOVE every check below, so the refusals
    that already govern each field (empty text / empty trigger / either of the two required-together
    refusals) cover the stdin channel unchanged.

    `open_refs` (T-12055) is the INJECTED openness reader behind the born-armed ADVISORY — a callable
    `refs -> the subset still open`, supplied by the host, which owns `tasks/` and the shared
    coordination store while this module stays a stdlib-only leaf (SPEC-0080 §P-A1), exactly as
    `terminal_ids` reaches `list`. It changes NOTHING about the capture: the event is appended and the
    id printed identically whether the advisory fires or not."""
    _stdin_ingest(args, ADD_STDIN_CONFLICTING_ARGV_FLAGS, PROSE_BEARING_ADD_FIELDS, die=die,
                  carries="the capture fields (text / relates_to / trigger / awaits)",
                  ingest=stdin_ingest)
    text = (getattr(args, "text", None) or "").strip()
    if not text:
        die("followup text must be non-empty (--text)")
    fid = _fu_id(text)
    data: dict = {"followup_id": fid, "text": text}
    relates_to = (getattr(args, "relates_to", None) or "").strip()
    if relates_to:
        data["relates_to"] = relates_to
    raw_trigger = getattr(args, "trigger", None)
    trigger = _clean_trigger(raw_trigger)
    if raw_trigger is not None and trigger is None:
        die("followup add --trigger must name a non-empty trigger (an armed followup waits for a NAMED "
            "moment). Omit --trigger to capture an actionable followup.")
    raw_awaits = getattr(args, "awaits", None)
    awaits = _clean_awaits(raw_awaits)
    if raw_awaits is not None and awaits is None:
        die("followup add --awaits must name a non-empty artifact (the thing whose closure IS the "
            "awaited moment, e.g. --awaits T-1234). Omit BOTH --awaits and --trigger when no artifact "
            "is awaited — the followup then waits for an explicit disposition.")
    if awaits and not trigger:
        die("followup add --awaits requires --trigger: `--awaits` names the artifact whose closure fires "
            "this followup, `--trigger` names the moment in words. Without a trigger the item would be "
            "armed-but-unnamed and would vanish from the actionable headline (X-0165 discipline).")
    # T-11863 — and the CONVERSE, so `armed` means `trigger AND awaits` at BOTH doors. Born-armed and
    # later-armed are ONE claim reached two ways: closing only `arm` would leave this one open.
    # T-11964 — the SECOND, STRICTER refusal, landing AFTER the T-11863 pair above (so the
    # missing/empty cases keep their own precise wording) and BEFORE any append. It does not loosen
    # that guard by one character; it narrows what a PRESENT awaits may be.
    if awaits and awaits_kind(awaits) is None:
        die(_awaits_shape_refusal(awaits, "add"))
    if trigger and not awaits:
        die("followup add --trigger requires --awaits — the AWAITED ARTIFACT whose closure fires this "
            "followup (e.g. --awaits T-1234). `awaits` is the SOLE fire key, and capturing an item "
            "born-armed keeps it OUT of the actionable headline: without one it would be invisible at "
            "session start AND unable to ever auto-fire, which is strictly worse than capturing it "
            "actionable. If the awaited moment is a bare future event with no artifact to name, omit "
            "--trigger too and capture it ACTIONABLE — visible, awaiting an explicit disposition.")
    if trigger:
        data["trigger"] = trigger
    if awaits:
        data["awaits"] = awaits
    # T-10779 — the SOURCE-CLUSTER fingerprint, set by a promotion capture (`frontend-errors
    # --promote`, SPEC-0170). Passed-but-empty REFUSES rather than dropping to a provenance-less
    # capture: passing it is a CLAIM that this followup came from a cluster, and a silently-dropped
    # claim is exactly how the promoted card would later lose the chain back to its errors.
    raw_fp = getattr(args, "fingerprint", None)
    fingerprint = _clean_fingerprint(raw_fp)
    if raw_fp is not None and fingerprint is None:
        die("followup add --fingerprint must name a non-empty source-cluster fingerprint (the handle "
            "the promoted task card is checked against). Omit it for an ordinary capture.")
    if fingerprint:
        data["fingerprint"] = fingerprint
    # T-10405: WHO captured this — derived host-side from the launch context (`_actor`), never asked for.
    if actor:
        data["actor"] = actor
    append_event("followup_added", None, data)
    state = f"open, armed — awaiting: {trigger}" if trigger else "open"
    if awaits:
        state += f" (fires when {awaits} closes)"
    if fingerprint:
        state += f" (from cluster {fingerprint})"
    print(f"followup added: {fid} ({state}) — {text}")
    print(f"  promote: yitc-v2 followup promote {fid} --into T-XXXX  |  drop: yitc-v2 followup drop {fid} --reason ...")
    # T-12055 — the born-armed advisory. LAST, so it can never come between the capture and the id
    # the operator needs; and only over an ACTIONABLE capture (`not trigger`), so a born-armed one is
    # silent BY CONSTRUCTION rather than by a second condition that could drift from the first.
    #
    # FAIL-OPEN TO SILENCE, and the direction is the load-bearing half. This is a REPORT-ONLY signal,
    # not a guard, and the two fail the opposite ways (`lessons/a-signal-about-a-reader-fails-safe-
    # the-opposite-way-to-a-gate`): a guard that cannot read its input must refuse, while a signal
    # that cannot read its input must say nothing. The capture has ALREADY been appended by the time
    # this runs, so an exception here would turn a COMPLETED capture into a failure — the exact
    # inversion `_autofile_p8_carrier` was corrected for. No injection (the in-process `task close`
    # carrier path) is likewise plain silence, not a degraded guess.
    if not trigger:
        try:
            refs = advisory_candidate_refs(text, relates_to) if open_refs else []
            still_open = list(open_refs(refs)) if refs else []
            if still_open:
                print(born_armed_advisory_line(fid, still_open))
        except Exception:                          # noqa: BLE001 — see FAIL-OPEN TO SILENCE above
            pass


def _transition(args, *, append_event, events_path, die, event_type: str, extra_key: str,
                extra_attr: str, label: str, _segment_lines=None) -> None:
    """Shared open->terminal leg: fold-validate the id is OPEN, then append the terminal event."""
    fid = (getattr(args, "id", None) or "").strip()
    if not fid:
        die("followup id required")
    items = _fold(events_path, _segment_lines)
    it = items.get(fid)
    if it is None:
        die(f"unknown followup id: {fid}")
    if it["status"] != "open":
        die(f"followup {fid} is already {it['status']} — only an OPEN followup transitions")
    data: dict = {"followup_id": fid}
    val = (getattr(args, extra_attr, None) or "").strip()
    if val:
        data[extra_key] = val
    append_event(event_type, None, data)
    print(f"followup {label}: {fid}" + (f" — {val}" if val else ""))


def _require_promote_target(into: str, *, die, read_task_text, read_plan_text, read_note_text=None):
    """T-11146 — resolve WHICH carrier `--into` names, and refuse a PLAN slug that does not exist.
    Returns the reader for the resolved leg, which the provenance gate below then uses.

    Three carriers, decided by the target's own SHAPE (no flag to get wrong):
      `T-NNNN`  — the TASK leg, byte-for-byte as before: no existence refusal is added here, because
                  the task leg's only target check has always been the fingerprint provenance gate,
                  and widening it would change behaviour this card does not own.
      lessons/… — an AUTHORED REFERENCE NOTE (T-11610), `NOTE_TARGET_RE`: the carrier SPEC-0140 calls
      patterns/…  the lightest for a captured followup. Existence-checked on the SAME fail-closed
                  terms as the plan slug — the file must EXIST or the promote is refused — because the
                  only honest alternative before this was `drop`, which records a DELIVERED note as
                  decided-not-to and is indistinguishable from an abandoned one.
      anything  — a PLAN slug. This is the widening: the followup's real carrier is a plan draft
      else      — the case that previously had no honest target at all, so such a followup was either
                  mis-linked to a task (fu_cbb23cc25d01 --into T-11056, recorded and irreversible —
                  promote is terminal) or left open forever.

    The note and plan legs are FAIL-CLOSED and LOUD. A silent accept would be strictly worse than today's state:
    it would record a carrier that does not exist while LOOKING successful, stranding the followup
    against nothing — the X-0165 class the required `--into` was introduced to close. So a slug that
    resolves to no plan draft is refused NAMING the slug, and — because this runs before
    `_transition` — nothing is appended: the fold still shows the followup OPEN and disposable. The
    note leg holds the SAME terms for the same reason: widening what counts as a RESOLVABLE carrier
    never loosens the requirement that the carrier resolve."""
    into = (into or "").strip()
    if TASK_TARGET_RE.match(into):
        return read_task_text
    if NOTE_TARGET_RE.match(into):
        if read_note_text is None:
            die(f"followup promote --into {into}: that names an authored reference note, but this "
                f"session cannot read reference notes, so the note cannot be shown to exist. "
                f"Refusing rather than recording a carrier that may not exist (the check fails "
                f"CLOSED).")
            return read_task_text                # pragma: no cover — die() exits; belt for a test double
        if read_note_text(into) is None:
            die(f"followup promote --into {into}: no such reference note in this corpus (looked for "
                f"the file `{into}` under the repo root). A promote is TERMINAL, so recording a "
                f"carrier that does not exist could not be walked back — author the note first, name "
                f"an existing note, an existing plan slug (`yitc-v2 plan list`), an existing task id "
                f"(T-NNNN), or `followup drop <id> --reason ...`.")
            return read_task_text                # pragma: no cover — die() exits; belt for a test double
        return read_note_text
    if read_plan_text is None:
        die(f"followup promote --into {into}: that is not a task id (T-NNNN), so it is read as a PLAN "
            f"slug — but this session cannot read plan drafts, so the plan cannot be shown to exist. "
            f"Refusing rather than recording a carrier that may not exist (the check fails CLOSED).")
        return read_task_text                    # pragma: no cover — die() exits; belt for a test double
    if read_plan_text(into) is None:
        die(f"followup promote --into {into}: no such plan in this corpus (looked for the draft "
            f"`{into}` in plans/ then ideas/). A promote is TERMINAL, so recording a carrier that "
            f"does not exist could not be walked back — name an existing plan slug (`yitc-v2 plan "
            f"list`), an existing task id (T-NNNN), or `followup drop <id> --reason ...`.")
        return read_task_text                    # pragma: no cover — die() exits; belt for a test double
    return read_plan_text


def _require_provenance_in_card(fid, into: str, *, events_path, die, read_target_text,
                                _segment_lines=None) -> None:
    """Refuse a promote that would DROP the source cluster's provenance (T-10779). No-op — by design,
    silently — for the ordinary fingerprint-less followup, which is nearly all of them.

    The refusal names the fingerprint and how to satisfy it, because the fix is one edit to the card
    and a refusal the reader cannot act on is just an obstacle.

    `read_target_text` is the reader for the carrier `--into` actually named (T-11146/T-11610) — the
    task-card reader for a `T-NNNN` target, the note reader for an authored reference note, the
    plan-draft reader for a plan slug. ONE gate, one wording, all three carriers: a plan or note
    carrier that drops a cluster's provenance is exactly as untraceable as a task one.
    """
    fid = (fid or "").strip()
    if not fid:
        return                                   # `_transition` owns the missing-id refusal
    it = _fold(events_path, _segment_lines).get(fid) or {}
    fingerprint = it.get("fingerprint")
    if not fingerprint:
        return
    if read_target_text is None:
        die(f"followup {fid} carries the source cluster {fingerprint!r}, but this session cannot read "
            f"the promote target, so the provenance of the promotion cannot be verified. Refusing "
            f"rather than promoting unchecked (the check fails CLOSED — SPEC-0170).")
    text = read_target_text(into)
    if text is None:
        die(f"followup promote --into {into}: no such task card in this corpus. File it first "
            f"(`yitc-v2 task file …`), carrying the source cluster fingerprint {fingerprint!r}.")
    msg = _provenance_refusal(fid, fingerprint, into, text)
    if msg:
        die(msg)


def _provenance_refusal(fid: str, fingerprint: str, into: str, card_text: str):
    """The T-10779 source-cluster check as a PURE predicate: the refusal message, or None when the
    card carries the fingerprint. Extracted (T-11056) so the FILING-time declared link and the
    standalone `promote` leg share ONE gate and ONE wording — a second copy of this check is exactly
    the parallel path CHARTER §P5 forbids."""
    if fingerprint in (card_text or ""):
        return None
    return (f"followup {fid} was promoted FROM the confirmed cluster {fingerprint!r}, and {into} does "
            f"not carry that fingerprint anywhere in its card — promoting would DROP the provenance, "
            f"leaving a task nobody can trace back to the errors that justified it (SPEC-0170: the "
            f"promoted card cites the cluster fingerprint). Add the fingerprint to {into} (its "
            f"description or scope), then re-run this promote.")


def cmd_followup_promote(args, *, append_event, events_path, die, read_task_text=None,
                         read_plan_text=None, read_note_text=None, _segment_lines=None) -> None:
    """`followup promote <id> --into <T-XXXX | lessons|patterns/<note>.md | plan-slug>` — the
    open->promoted leg. `--into` is
    REQUIRED (X-0165): a bare promote would fold to status=promoted with into=None, stranding a
    promoted-but-carrierless item. `promote` means "this followup BECAME <target>", so it MUST name
    that target — file the task / author the plan first, then promote --into it, or `followup drop` it.

    THE NOTE CARRIER (T-11610). Some followups are carried by neither a task nor a plan but by an
    AUTHORED REFERENCE NOTE — a lessons/ or patterns/ file, which SPEC-0140 names as the LIGHTEST
    carrier and drains in one batched work/<slug> land rather than a worktree cycle per note. That
    carrier is a FILE, and promote's vocabulary could not name a file, so the sanctioned lightest path
    had only `drop` left: on 2026-08-26 four DELIVERED notes were recorded `dropped`, each with prose
    naming the file it became. The 2-state fold is what later readers count, and `dropped` means
    decided-not-to, so a delivered note recorded there is indistinguishable from an abandoned one —
    and the recommended carrier was the only one whose outcome could not be recorded truthfully. So
    `--into` now also resolves a repo-relative `lessons/<name>.md` or `patterns/<name>.md`, on the
    SAME fail-closed terms the plan leg already holds: the file must EXIST or the promote is REFUSED.
    `drop` is untouched and stays the right leg for a note genuinely abandoned; nothing already
    recorded is rewritten (the journal is append-only, and the four notes above keep their reasons).

    TWO CARRIERS (T-11146). Some followups are genuinely carried by a PLAN, not a task: their body is
    authored verbatim into a plan draft, and the plan is what disposes of them. Before this, such a
    followup had no honest target — fu_cbb23cc25d01 was promoted `--into T-11056` in error, and
    because promote is TERMINAL that mis-link cannot be walked back (T-11056's amend_notes record it
    rather than rewriting it). So `--into` now resolves by SHAPE: `T-NNNN` is the unchanged task leg;
    anything else is a PLAN slug, which must resolve to a real draft or the verb REFUSES naming the
    slug and appends NOTHING (`_require_promote_target`). This is a widening of the ONE target
    validation plus a plan-existence check — no second link store, no second event, no parallel
    promote path (CHARTER §P1 F1 / §P5).

    THE PROVENANCE GATE (T-10779). When the record carries a source-cluster `fingerprint` — it was
    born of a promoted frontend-error cluster (SPEC-0170) — the target card MUST contain that
    fingerprint, or the promote is REFUSED. This is the one moment provenance can be dropped
    SILENTLY: the hand-off is where the cluster stops being the carrier and the card starts, and a
    card filed without the fingerprint looks entirely ordinary — nothing else in the system would ever
    notice that the task can no longer be traced to the errors that justified it. The check is a
    substring test over the card TEXT (not a `cites:` entry) because a fingerprint is not a graph id:
    it is `kind | normalized message`, and the card's own prose is where it belongs.

    `read_task_text` / `read_plan_text` are INJECTED (the leaf takes host collaborators, SPEC-0080
    §P-A1): `(id_or_slug) -> str | None`. `read_task_text` is optional ONLY for the fingerprint-LESS
    majority; a fingerprint-bearing record with no reader available REFUSES rather than promoting
    unchecked — the gate fails CLOSED, since a provenance check that quietly skips itself is worth
    less than none at all. `read_plan_text` is what makes the plan leg checkable at all, so its
    absence refuses that leg outright, for the same fail-closed reason; `read_note_text`
    (`(repo-relative path) -> str | None`) is the same collaborator for the note leg, and its absence
    refuses that leg for the same reason.
    """
    into = (getattr(args, "into", None) or "").strip()
    if not into:
        die("followup promote requires --into <T-XXXX | lessons|patterns/<note>.md | plan-slug> — a "
            "promoted followup must name the task, note or plan it became, else it is stranded "
            "promoted-but-carrierless (X-0165). File the task (`yitc-v2 task file …`), author the "
            "note or the plan first, then `followup promote <id> --into <target>`, or `followup drop "
            "<id>`.")
    read_target_text = _require_promote_target(into, die=die, read_task_text=read_task_text,
                                               read_plan_text=read_plan_text,
                                               read_note_text=read_note_text)
    _require_provenance_in_card(getattr(args, "id", None), into, events_path=events_path, die=die,
                               read_target_text=read_target_text, _segment_lines=_segment_lines)
    _transition(args, append_event=append_event, events_path=events_path, die=die,
                event_type="followup_promoted", extra_key="into", extra_attr="into", label="promoted",
                _segment_lines=_segment_lines)


def validate_promotes(fids, *, events_path, die, _segment_lines=None) -> list:
    """T-11056 — validate a card's DECLARED `promotes:` list at FILING time, fail-closed, and return
    the cleaned de-duped ids (order preserved). The mirror of `task file`'s `--resolves-cross`
    member check (T-9362), extended with the existence + open-ness legs the cross axis gets from its
    own log.

    THE LINK IS DECLARED, NEVER INFERRED. This validates what the FILER stated; nothing here reads a
    title, a keyword screen, or an overlap hit. SPEC-0095 settled that axis once already — keying the
    fire on `relates_to` made all 9 live rows false (T-10335) — so a screen may only ADVISE and only
    a declaration ever mutates state.

    Three refusal shapes, each named LOUDLY with the offending id, because the alternative is the
    X-0304 silent-drop class the stdin path already burned once — a declared link that vanishes
    without a word leaves the filer believing the followup was disposed:
      malformed token   — not the `fu_` + 12-hex shape `_fu_id` mints;
      unknown id        — well-shaped but absent from the fold (a typo, or another repo's capture);
                          `events_path` may be the SPEC-0168 instance PAIR (this checkout's journal +
                          the repo MAIN checkout's — T-11208/X-0952), so "absent" means absent from
                          BOTH. Widening WHERE the id may be found never widens WHAT is accepted: an
                          id present in NEITHER instance still refuses here, fail-closed, exactly as
                          it did when one journal was read;
      already-terminal  — a real followup that is already promoted or dropped. Re-promoting it would
                          claim a second carrier for one item and silently overwrite `into` in the
                          fold (last write wins), so the first card's link would just disappear.

    Runs BEFORE anything is written. `die` is expected to exit; the loop never continues past a bad
    member (fail-closed on the FIRST offender, exactly like the resolves_cross check)."""
    cleaned: list = []
    seen: set = set()
    items = None
    for raw in (fids or []):
        fid = str(raw).strip()
        if not FOLLOWUP_ID_RE.match(fid):
            die(f"--promotes entries must be followup ids of the form fu_<12 hex> (the shape "
                f"`followup add` prints); got {fid!r}. Run `yitc-v2 followup list --status open` to "
                f"find the id you meant.")
            return cleaned                       # pragma: no cover — die() exits; belt for a test double
        if items is None:                        # fold ONCE, and only when a well-shaped id exists
            items = _fold(events_path, _segment_lines)
        it = items.get(fid)
        if it is None:
            die(f"--promotes {fid}: unknown followup id — nothing in this checkout's journal NOR the "
                f"main checkout's ever captured it. A "
                f"declared link must name a REAL open followup (SPEC-0095); check "
                f"`yitc-v2 followup list --status open`.")
            return cleaned                       # pragma: no cover — die() exits
        if it.get("status") != "open":
            die(f"--promotes {fid}: this followup is already {it['status']}"
                + (f" (into {it['into']})" if it.get("into") else "")
                + " — only an OPEN followup can be promoted, and re-promoting a terminal one would "
                  "overwrite the carrier already on record. Drop the flag, or name an open followup.")
            return cleaned                       # pragma: no cover — die() exits
        if fid not in seen:
            seen.add(fid)
            cleaned.append(fid)
    return cleaned


def require_promote_provenance(fids, into: str, *, events_path, die, card_text: str,
                               _segment_lines=None) -> None:
    """T-11056 — the T-10779 source-cluster provenance gate for a FILING-time declared link.

    Same gate, same wording as the standalone `promote` leg (both go through `_provenance_refusal`),
    but the card text is SUPPLIED by the caller rather than read off disk: at filing the target card
    does not exist yet, so `task file` passes the COMPOSED content it is about to write. That is what
    lets every fail-closed check run BEFORE the write — a refusal here leaves no card on disk, no id
    consumed, and no `task_filed` emitted, so the filing cannot half-succeed (audit-pre finding,
    2026-08-15). No-op for the fingerprint-less majority."""
    items = _fold(events_path, _segment_lines)
    for fid in (fids or []):
        fingerprint = (items.get(fid) or {}).get("fingerprint")
        if not fingerprint:
            continue
        msg = _provenance_refusal(fid, fingerprint, into, card_text)
        if msg:
            die(msg)
            return                               # pragma: no cover — die() exits


def promote_at_filing(fids, into: str, *, append_event) -> list:
    """T-11056 — append one `followup_promoted {followup_id, into}` per DECLARED id, and return the
    promoted ids. EMIT-ONLY by construction: it validates nothing, because `validate_promotes` +
    `require_promote_provenance` already decided every question BEFORE the card was written. Keeping
    the emit leg free of checks is what makes the pre-write/post-write split honest — there is no
    second place a filing can fail after the YAML is on disk.

    The event is IDENTICAL to the one `followup promote --into` appends: one promote mechanism, one
    event shape, one fold. What this card adds is the moment (filing), never a second FSM."""
    promoted: list = []
    for fid in (fids or []):
        append_event("followup_promoted", None, {"followup_id": fid, "into": into})
        promoted.append(fid)
    return promoted


def cmd_followup_drop(args, *, append_event, events_path, die, stdin_ingest=None,
                      _segment_lines=None) -> None:
    """`followup drop <id> [--reason ...]` — the open->dropped leg.

    `--from-stdin` (T-11244, E-0054) reads the reason as a YAML mapping (`reason: <text>`) — the
    shell-proof path. This reason is the recorded WHY a governance item was discarded and the journal
    row is immutable once appended, so a shell-eaten fragment here is permanent (kupiclub X-0984).
    The `id` positional stays on argv: it carries no prose."""
    _stdin_ingest(args, DROP_STDIN_CONFLICTING_ARGV_FLAGS, PROSE_BEARING_DROP_FIELDS, die=die,
                  carries="the drop reason", ingest=stdin_ingest)
    _transition(args, append_event=append_event, events_path=events_path, die=die,
                event_type="followup_dropped", extra_key="reason", extra_attr="reason", label="dropped",
                _segment_lines=_segment_lines)


def _arm_target(args, *, events_path, die, _segment_lines=None) -> str:
    """Resolve the followup id an arm/unarm applies to: it must exist and still be OPEN.

    Arming a terminal followup is meaningless (it has no pending disposition to defer), and `_fold`
    ignores such an event anyway — so refuse LOUDLY here rather than append a line the fold will drop."""
    fid = (getattr(args, "id", None) or "").strip()
    if not fid:
        die("followup id required")
    it = _fold(events_path, _segment_lines).get(fid)
    if it is None:
        die(f"unknown followup id: {fid}")
    if it["status"] != "open":
        die(f"followup {fid} is already {it['status']} — only an OPEN followup can be armed/unarmed")
    return fid


def cmd_followup_arm(args, *, append_event, events_path, die, stdin_ingest=None,
                     _segment_lines=None) -> None:
    """`followup arm <id> --trigger <phrase> [--awaits <artifact>]` — mark an OPEN followup as ARMED:
    waiting for the NAMED moment in `<phrase>`, so it stops inflating the actionable debt headline
    (SPEC-0095 §Armed).

    `--trigger` is REQUIRED and must be non-empty (the same discipline `promote --into` learned from
    X-0165: an armed followup is BY DEFINITION awaiting a NAMED trigger, so a bare `arm` would strand an
    armed-but-triggerless item invisible to the headline).

    `--awaits` names the AWAITED ARTIFACT whose closure fires this followup — the SOLE fire key — and is
    REQUIRED beside `--trigger` (T-11863). It is the THIRD field of this family held to the X-0165
    discipline, after `promote --into` and `--trigger` itself, and for the sharpest version of the same
    reason: arming REMOVES the item from the actionable headline, so an armed record with no `awaits` is
    invisible at session start AND unfireable by construction (`_partition_open` reads `awaits` and
    nothing else). That is strictly WORSE than leaving the item actionable, where it at least stays
    visible — which made the shortest path to arming the path that produced an unfireable waiter: of 207
    open armed followups measured 2026-08-30, 200 carried no `awaits`. A bare future EVENT with no
    machine-checkable artifact ("the next real revizia run") is therefore NOT armed at all — it stays
    ACTIONABLE, or is dropped.

    The READ side is deliberately untouched: `_clean_awaits` stays a faithful parser, so the legacy
    awaits-less records still fold to `armed_waiting` — open, visible, disposed by hand. This closes the
    WRITE door only.

    RE-ARMING IS THE CORRECTION PATH (T-10335 AC2). `arm` re-states the WHOLE awaited condition, so it
    works on an already-FIRED followup and RETURNS IT TO `armed` — the operator saying "that fire was
    wrong, here is the real condition". Before T-10335 this was a silent no-op: firing keyed on
    `relates_to`, which `arm` could not touch, so a wrongly-fired item was fired forever
    (`followup-arm-noop-on-already-fired`). A `fired` followup is `open` — the FSM never held it — so
    this needs no un-fire leg and no new state: the last-write-wins carrier already had the power.

    Sets ATTRIBUTES, never a status — the 2-state FSM is untouched. `relates_to` (provenance) is never
    rewritten. NO worktree (D-0049).

    `--from-stdin` (T-11244, E-0054) reads trigger + awaits as a YAML mapping — the shell-proof path
    for a trigger phrase naming a verb or a path in backticks. Hoisted ABOVE the non-empty trigger
    refusal, which therefore governs both channels unchanged."""
    _stdin_ingest(args, ARM_STDIN_CONFLICTING_ARGV_FLAGS, PROSE_BEARING_ARM_FIELDS, die=die,
                  carries="the awaited condition (trigger / awaits)", ingest=stdin_ingest)
    trigger = _clean_trigger(getattr(args, "trigger", None))
    if not trigger:
        die("followup arm requires a non-empty --trigger — an armed followup waits for a NAMED moment "
            "(e.g. --trigger 'next -C consumer init'). Without one it would vanish from the actionable "
            "headline with nothing to bring it back. Use `followup drop <id> --reason ...` to discard it.")
    raw_awaits = getattr(args, "awaits", None)
    awaits = _clean_awaits(raw_awaits)
    if raw_awaits is not None and awaits is None:
        die("followup arm --awaits must name a non-empty artifact (the thing whose closure IS the "
            "awaited moment, e.g. --awaits T-1234).")
    if not awaits:
        die("followup arm requires --awaits beside --trigger — the AWAITED ARTIFACT whose closure "
            "fires this followup (e.g. --awaits T-1234). `awaits` is the SOLE fire key, and arming "
            "REMOVES the item from the actionable headline: without one it would be invisible at "
            "session start AND unable to ever auto-fire, which is strictly worse than leaving it "
            "actionable. This is the same discipline `promote --into` (X-0165) and `--trigger` "
            "already carry. If the awaited moment is a bare future event with no artifact to name, "
            "LEAVE IT ACTIONABLE (visible, awaiting an explicit disposition) or discard it with "
            "`followup drop <id> --reason ...`.")
    # T-11964 — the SECOND, STRICTER refusal, landing AFTER the two T-11863 refusals above (which keep
    # their own precise wording for the missing/empty cases) and BEFORE any append. It does not loosen
    # that guard by one character; it narrows what a PRESENT awaits may be.
    kind = awaits_kind(awaits)
    if kind is None:
        die(_awaits_shape_refusal(awaits, "arm"))
    fid = _arm_target(args, events_path=events_path, die=die, _segment_lines=_segment_lines)
    append_event("followup_armed", None, {"followup_id": fid, "trigger": trigger, "awaits": awaits})
    print(f"followup armed: {fid} — awaiting: {trigger}")
    _verb, _gloss = _AWAITS_KIND_GLOSS[kind]
    print(f"  fires when {awaits} {_verb} ({_gloss}); "
          f"provenance (`relates_to`) is unchanged and is never a fire key")
    if kind == "event":
        # The event grammar is the only one whose referent the write door cannot confirm EXISTS — a
        # task/coordination id is misspelled visibly, an event class is not. So report the CURRENT row
        # count of that class: 0 is the ordinary awaited-future case and says so, while a non-zero
        # count warns that this arm fires IMMEDIATELY on the next read. Reporting beats refusing here,
        # because a class with zero rows today is precisely the useful case (T-11951's residuals each
        # name a key that has never fired), so a catalog check would refuse exactly the good arms.
        # T-12057 — the type is taken from the ONE parse home, so a suffixed awaits reports the row
        # count of its BARE class (which is the useful reading: the anchor is what makes it not fire).
        _etype, _after = split_event_awaits(awaits)
        _seen: set = set()
        _fold(events_path, _segment_lines, seen_event_types=_seen)
        # T-12118 — the VERDICT half of that line is CONDITIONED on the anchor. The row count answers
        # a MEMBERSHIP question, and membership is what decides a BARE awaits — so for the suffixed
        # shape the same count is CONTEXT, not a verdict: the fire predicate compares the anchor, and
        # an arm whose class has thousands of rows still reads `armed_waiting` when none is later than
        # it (measured on the five T-12057 AC5 arms, 2026-09-04 — the arm door said FIRED while the
        # fold said waiting, deviation fp arm-report-says-FIRED-over-a-time-anchored-awaits). Stating
        # the anchored reading is the honest sentence there; the bare form's verdict is unchanged,
        # byte-for-byte, because for it membership IS the answer.
        _present = "PRESENT" if _etype in _seen else "ABSENT"
        if _after is not None:
            print(f"  journal today: `{_etype}` rows {_present} — CONTEXT, not a verdict: this arm is "
                  f"time-anchored, so it fires only on a `{_etype}` row STRICTLY LATER than {_after}, "
                  f"never on the rows already there")
        else:
            print(f"  journal today: `{_etype}` rows {_present} — "
                  + ("this arm therefore reads as FIRED on the next `followup list`; that is the honest "
                     "reading (the moment already arrived), not a defect"
                     if _etype in _seen else
                     "the awaited moment has not arrived yet, which is the ordinary armed case. If you "
                     "expected rows, check the spelling of the event type"))
        # T-12057 — THE REMEDY, in the line that already reports the problem. A PRESENT class fires
        # immediately, and until now the report said so and stopped there: the operator was told their
        # arm was useless without being told what to type instead, which is why ~40-60 of the kernel's
        # actionable followups could not be armed at all. So the SAME line now names the fourth shape
        # and prints the exact command, with `<now ISO>` spelled as a command the operator can run
        # rather than a placeholder they must decode.
        #
        # REPORT-ONLY, AND THAT IS THE LOAD-BEARING HALF. The arm they asked for has ALREADY been
        # appended above; nothing here rewrites it, re-arms it, or changes the exit code. `awaits` is
        # DECLARED, never inferred (§Why the trigger is DECLARED / T-10335) — silently anchoring an
        # operator's bare awaits would be exactly the inferred-not-declared mistake the field exists to
        # end, and it would also be WRONG whenever the immediate fire was what they meant.
        #
        # Suppressed when it has nothing to add: an ALREADY-suffixed awaits has taken this remedy, and
        # an ABSENT class is the ordinary armed case with no problem to remedy.
        if _after is None and _etype in _seen:
            print(f"  to wait for the NEXT `{_etype}` instead of firing on the rows already there, "
                  f"re-arm with the time-anchored shape:\n"
                  f"    yitc-v2 followup arm {fid} --trigger '{trigger}' "
                  f"--awaits '{awaits}{AWAITS_AFTER_SEP}'\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"\n"
                  f"  it then arrives only on a row STRICTLY LATER than that anchor "
                  f"(report-only — your arm above was NOT changed)")
    print(f"  it leaves the actionable headline; it returns when its trigger fires "
          f"(`followup list --status fired`) or via `yitc-v2 followup unarm {fid}`")


def cmd_followup_unarm(args, *, append_event, events_path, die, _segment_lines=None) -> None:
    """`followup unarm <id>` — clear an OPEN followup's trigger, returning it to the ACTIONABLE headline.

    The explicit re-actionable path for a waiter whose trigger went MOOT (a plan abandoned, a gate
    dropped) — the moment never arrives, so auto-fire never rescues it. Appends the SAME `followup_armed`
    event with `trigger: null` AND `awaits: null` (one event type carries every leg; last write wins):
    clearing the trigger without clearing the awaited artifact would leave an actionable item still
    carrying a stale fire key. NO worktree."""
    fid = _arm_target(args, events_path=events_path, die=die, _segment_lines=_segment_lines)
    append_event("followup_armed", None, {"followup_id": fid, "trigger": None, "awaits": None})
    print(f"followup unarmed: {fid} — back in the actionable set (awaiting disposition)")


def _fmt_row(it: dict, label: str, is_named_actor=None) -> str:
    """One `list` row. `label` is the DERIVED group name for an open row (actionable / armed / fired),
    or the stored status for a terminal one — the column has always shown 'what this item is now'.

    A fired row names the AWAITED artifact that closed (`awaits`), never the provenance ref: the reader
    must see the thing this followup was WAITING FOR, not the thing it was about (T-10335).

    `[by: <actor>]` shows only when a real PERSON captured the row (T-10405) — an ai-agent capture, the
    overwhelming majority, stays silent (suppressed-when-clean: signal only where there is signal). The
    "is this a person?" predicate is INJECTED (`lib/memory.py#is_named_actor`, threaded from the host) —
    this module stays a stdlib-only leaf, importable as a bare top-level module, which is a property its
    callers and tests rely on. Absent injection the row stays silent: a view never INVENTS an author."""
    by = f"  [by: {it['actor']}]" if (is_named_actor and is_named_actor(it.get("actor"))) else ""
    # T-10779: a promoted-from-a-cluster row shows its SOURCE, so the provenance the promote gate
    # enforces is also VISIBLE to the human reading the list — an enforced link nobody can see is an
    # audit surface missing exactly where it is needed (the `--acked` reasoning, one card earlier).
    rel = f"  [relates: {it['relates_to']}]" if it.get("relates_to") else ""
    if it.get("fingerprint"):
        rel = f"  [cluster: {it['fingerprint']}]"
    tail = ""
    if it["status"] == "promoted" and it.get("into"):
        tail = f"  -> {it['into']}"
    elif it["status"] == "dropped" and it.get("reason"):
        tail = f"  ({it['reason']})"
    elif label == "fired":
        tail = f"  [trigger FIRED: awaited {it['awaits']} closed — {it['trigger']}]"
    elif label == "armed":
        tail = f"  [trigger: {it['trigger']}]"
        if it.get("awaits"):
            tail += f"  [awaits: {it['awaits']}]"
    elif label == "actionable" and it.get("stale_provenance"):
        # Report-only (T-10658): the row is NOT reclassified — it is flagged so the reader checks the
        # landed task before re-promoting it into a duplicate card (X-0486).
        #
        # T-12019 — THE MARKER STATES A FACT, NOT A HYPOTHESIS (X-1239 / X-1241). It used to append a
        # clause saying the closing land may already have fixed the row, and to verify before
        # promoting. That clause named a
        # MECHANISM, and kupiclub measured the mechanism wrong even where the conclusion was right:
        # of four rows judged by measurement, two WERE fixed — but by later, unrelated cards, not by
        # the closing land the marker named. A stated reason the reader can go and check, that does
        # not hold, is worse than a plain miss. So what survives is the two timestamps and nothing
        # else: the provenance closed THEN, this was captured THEN. The verdict — whether that
        # closure touched THIS row's subject — was never derivable here and now returns, visibly, to
        # the reader. `provenance_closed_at` is absent only when the card records no `closed_at`
        # (the fail-open path), and the fact then states the half it has.
        _closed = it.get("provenance_closed_at")
        _when = f" closed {_closed}" if _closed else " closed (no recorded time)"
        tail = (f"  [provenance {it['relates_to']}{_when}; "
                f"this was captured {it.get('added_at') or '(no recorded time)'}]")
    return f"  {it['id']}  {label:10}  {it['text']}{by}{rel}{tail}"


def _open_label(fid: str, groups: dict):
    """The DERIVED open-lens label (`actionable` / `fired` / `armed`) for one folded id, read off the
    SAME `_partition_open` result `list` renders — so `show` and `list` can never disagree about which
    lens a followup is in. None when the id is not open (a terminal record wears its stored status)."""
    for key, label in (("actionable", "actionable"), ("armed_fired", "fired"), ("armed_waiting", "armed")):
        if any(row["id"] == fid for row in groups[key]):
            return label
    return None


def cmd_followup_show(args, *, events_path, die, terminal_ids=frozenset(), closed_at_by_id=None,
                      terminal_cross_ids=frozenset(),
                      is_named_actor=None, _segment_lines=None) -> None:
    """`followup show <fu_XXXXXXXXXXXX>` (read-only) — resolve ONE followup by id (T-11225 / X-0962).

    The read-one counterpart of `list`, modelled leg-for-leg on `cross show` (bin/lib/cross.py
    #cmd_cross_show): resolve one id, print the fold-derived record, FAIL CLOSED on an unknown id,
    mutate nothing. It exists because resuming a handoff that NAMES followups by id otherwise means
    `followup list` piped through a grep, once per id — a manual fallback that gets WORSE as the
    backlog grows (77 open + 118 armed in this kernel at filing time).

    A VIEW, never a write: no `append_event` is even accepted in the signature, so no write path is
    reachable from here. Status stays DERIVED — the row is re-read from `_fold` + `_partition_open` on
    every call, and the lens label comes from that SAME partition (`_open_label`) rather than a second
    classifier that could drift out of agreement with `list`.

    FAIL-CLOSED, in TWO shapes, because silence on a missing id reads as an empty followup (AC2):
      - a MALFORMED token is refused AS malformed (`FOLLOWUP_ID_RE`, the T-11056 distinction: "that is
        not a followup id" beats "mysteriously unknown"),
      - a well-formed but UNRESOLVED id is refused with the `_arm_target` wording (`unknown followup
        id: <id>`), naming the id, so one refusal message is learned once across the verb group.
    """
    fid = (getattr(args, "id", None) or "").strip()
    if not fid:
        die("followup id required")
    if not FOLLOWUP_ID_RE.match(fid):
        die(f"not a followup id: {fid} — expected `fu_` + 12 lowercase hex (see `followup list`)")
    seen: set = set()
    closing: dict = {}
    latest: dict = {}   # T-12057 — per-type latest ts, filled by the SAME walk (no second pass)
    items = _fold(events_path, _segment_lines, seen_event_types=seen, closing_sessions=closing,
                  latest_event_ts=latest)
    it = items.get(fid)
    if it is None:
        die(f"unknown followup id: {fid}")
    # T-11964 — the SAME `arrived_ids` union `list` and the debt echo build, so all three agree about
    # which lens a followup is in (the read-path==write-path property this verb group already holds).
    groups = _partition_open(items, terminal_ids, closed_at_by_id,   # also derives `stale_provenance`
                             fire_ids=arrived_ids(terminal_ids, terminal_cross_ids, seen),
                             closing_sessions=closing,   # T-12019 — the by-construction suppression
                             latest_event_ts=latest)     # T-12057 — the `@after=` anchor comparison
    label = _open_label(fid, groups) or it["status"]
    print(_fmt_row(it, label, is_named_actor).strip())
    # The detail `list` has no room for on a one-line row — printed only when present
    # (suppressed-when-clean, the `_fmt_row` house style).
    if it.get("added_at"):
        print(f"  added: {it['added_at']}")
    if it.get("actor"):
        print(f"  by: {it['actor']}")


def cmd_followup_list(args, *, events_path, terminal_ids=frozenset(), closed_at_by_id=None,
                      is_named_actor=None, _segment_lines=None, terminal_cross_ids=frozenset()) -> None:
    """`followup list [--status open|actionable|armed|fired|promoted|dropped|all]` — fold + print.

    Default `open` renders the DERIVED three-way partition as labelled groups with their own counts, so
    the armed waiters never inflate the actionable headline (SPEC-0095 §Armed / T-10309 AC1). The three
    open lenses (`actionable` / `armed` / `fired`) are VIEWS over that partition, NOT stored statuses —
    `--status promoted|dropped` still selects on the FSM's real stored status.

    T-11964 — the `fired` lens reads the `arrived_ids` union (terminal tasks + terminal coordination
    items + the event classes this fold observed), built from the SAME fold, while the
    stale-provenance marker keeps reading `terminal_ids` alone. `show` and the debt echo build the
    identical union, so the three surfaces still cannot disagree."""
    status = (getattr(args, "status", None) or "open")
    seen: set = set()
    closing: dict = {}
    latest: dict = {}   # T-12057 — per-type latest ts, filled by the SAME walk (no second pass)
    items = _fold(events_path, _segment_lines, seen_event_types=seen, closing_sessions=closing,
                  latest_event_ts=latest)
    groups = _partition_open(items, terminal_ids, closed_at_by_id,
                             fire_ids=arrived_ids(terminal_ids, terminal_cross_ids, seen),
                             closing_sessions=closing,   # T-12019 — the by-construction suppression
                             latest_event_ts=latest)     # T-12057 — the `@after=` anchor comparison

    open_lenses = {"actionable": ("actionable",), "armed": ("armed_waiting",), "fired": ("armed_fired",)}
    if status in open_lenses:
        rows = [(it, "fired" if status == "fired" else status) for k in open_lenses[status] for it in groups[k]]
    elif status == "open":
        rows = ([(it, "actionable") for it in groups["actionable"]]
                + [(it, "fired") for it in groups["armed_fired"]]
                + [(it, "armed") for it in groups["armed_waiting"]])
    else:
        rows = [(it, it["status"]) for it in sorted(items.values(), key=lambda r: r.get("added_at") or "")
                if status == "all" or it["status"] == status]

    if not rows:
        print(f"followups ({status}): none")
        return

    if status == "open":
        # The headline is ACTIONABLE alone; the armed halves are reported beside it, never inside it.
        n_act, n_fired, n_wait = (len(groups["actionable"]), len(groups["armed_fired"]),
                                  len(groups["armed_waiting"]))
        n_stale = sum(1 for it in groups["actionable"] if it.get("stale_provenance"))
        summary = f"followups (open): {n_act} actionable"
        if n_stale:
            # A SUBSET of the actionable count, never a separate group — the headline is not reduced.
            summary += f" ({n_stale} possibly stale — provenance closed)"
        if n_fired:
            summary += f" · {n_fired} armed, TRIGGER FIRED"
        if n_wait:
            summary += f" · {n_wait} armed, awaiting trigger"
        print(summary)
    else:
        print(f"followups ({status}): {len(rows)}")

    for it, label in rows:
        print(_fmt_row(it, label, is_named_actor))
