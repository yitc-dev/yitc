"""Spec verb family for the yitc-v2 CLI — `spec new|edit|reverify` (the specs/SPEC-XXXX.yaml graph
nodes, GRAPH §Schema / SPEC-0005 / SPEC-0006 / SPEC-0050 / SPEC-0073). The fourth layer-2 verb-family
extraction (after scenario.py / error.py).

bin/yitc-v2 keeps the thin argparse residue cmd_spec_* (the `set_defaults(func=…)` entrypoints, wiring
unchanged) which delegate here, injecting the host collaborators each verb needs — the audit.py
verb-family precedent (family bodies in lib, host thin residue + injected host deps), so a `-C` REPO_ROOT
rebind and every `monkeypatch.setattr(yitc, …)` stay honored at call time.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It imports only
the already-extracted lower leaf `lib.state` (canonical YAML load for the `spec edit` parse-validate) plus
stdlib; it NEVER back-imports the host. The shared signer `_reverify_spec_signature` (used by
`cmd_task_close --reverify` too — T-1177), its private `_strip_top_key`, and the scaffold toolkit
(`_scaffold_substitute` / `_scaffold_read_validate`) DELIBERATELY stay host-side and are injected here,
since they are cross-called or are a cohesive host-resident family. Behaviour is byte-identical to the
inline originals — the test suite is the oracle.
"""
from __future__ import annotations

import argparse
import re
import shlex
import sys

from lib import state
from lib import graph as graph_lib   # T-11992: the shared SPEC-0092 retrieval-hint renderer (`spec_query_hint`) — graph.py imports only lib.state + stdlib, so this stays acyclic
from lib import textutil

# ── T-10159 — the at-the-moment spec-body-edit cue (single-SoT string) ────────────────────────────
# The one-line reminder surfaced at every spec-edit-touching moment (SPEC-0005 spec-edit chokepoint;
# SUPPORTS the T-10135 `spec edit --bless` PRIMARY path). Homed here in the spec-domain owner and
# re-used by worktree.py (the T-9730 land-block recovery text) and host cmd_stage (the Execution
# stage-entry) — the SYNC_TO_LAND_RULE-in-dispatch.py precedent, so the four surfaces never diverge.
SPEC_BODY_EDIT_CUE = (
    "amend spec bodies via `spec edit` (--from-file / --bless for multi-line); "
    "raw Edit of an active spec body hard-blocks at land (T-9730). "
    "Placement (SPEC-0005 rule 3): history / incident / ids → `## Rationale`, not the rule text; "
    "code anchors → `implements:`; implementation notes → `## Implementation notes`."
)

# ── T-11717 — the STALE-BLESS remedy cue (single-SoT string, the SPEC_BODY_EDIT_CUE precedent) ────
# A bless is DIFF-BOUND (T-10135): the T-9730 land guard clears the spec only if the FINAL base..HEAD
# diff still matches the blessed fingerprint. MEASURED TWICE on 2026-08-27 (T-11700, fingerprint
# ae3698d80c43, invalidated by T-11706's edit to the SAME spec at 675c5007; T-11707 the same hour):
# the invalidator was not an author edit at all — it was the LAND'S OWN update-from-main. The author
# never performs that merge, so "re-bless if you edit further" (an AUTHOR action) does not describe
# it. This cue names the ORDER that converges, and is re-used by worktree.py's stale-fingerprint
# refusal so the diagnosis and the remedy never drift apart.
SPEC_STALE_BLESS_CUE = (
    "REMEDY (the working order): run `worktree sync` FIRST so the branch already carries main's "
    "version of the spec, THEN re-run `spec edit --bless` on the POST-MERGE body, THEN `land` — "
    "sync, then bless, then land. Blessing before the sync re-binds the fingerprint to a body the "
    "land is about to move again (T-11717)."
)

# T-10727 — the TRAVELS RE-PIN companion cue (single-SoT, the SPEC_BODY_EDIT_CUE precedent above).
# A `travels:` re-pin (the SPEC-0073 §3 explicit action at plan-accept) has a HAND-side consequence
# the re-pin path never said out loud: the §1 class column of kernel-vs-self-manifest.md is
# hand-maintained, and its auto-backfill (`graph._backfill_spec_placement_handrow`) runs ONLY at
# `spec new` — never on the edit path. So the row keeps the OLD realm's prefix, the manifest desyncs
# from the derived realm, and tests/test_t0890_placement_backfill.py probe (b2) fails at land verify
# → land ABORTs. The step is already KNOWN (SPEC-0166/0167/0168 carry re-pinned-at-plan-accept notes
# in that manifest — operators have done it by hand); only the cue at the moment of the re-pin was
# missing. Report-only prose: no gate, no event, no store, and no auto-write of the hand table.
SPEC_TRAVELS_REPIN_CUE = (
    "travels re-pin — COMPANION STEP REQUIRED: update this spec's row in the §1 HAND table of "
    "kernel-vs-self-manifest.md so its `class` column prefix matches the NEW realm (the prefix→realm "
    "key is that file's own «Reading the class column» section). The birth-time auto-backfill runs "
    "only at `spec new`, NOT on this edit path — leave the row stale and "
    "tests/test_t0890_placement_backfill.py probe (b2) fails at land verify and ABORTs land "
    "(SPEC-0073 §3)."
)


# T-12972 (SPEC-0073 §3) — the on-disk marker a DEFAULTED draft realm carries until a human decides it.
# `task close` refuses to activate an owned spec still carrying it (bin/lib/task.py#_unconfirmed_travels_specs);
# the decision is removing it through `spec edit` (with a travels: change for the kernel re-pin).
TRAVELS_DRAFT_DEFAULT_KEY = "travels_draft_default"


def _mark_travels_draft_default(content: str) -> str:
    """Insert the marker line directly after the scaffold's top-level `travels:` line (the template's
    trailing comment lines stay attached below it). No `travels:` line → appended at the end."""
    lines = content.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("travels:"):
            lines.insert(i + 1, f"{TRAVELS_DRAFT_DEFAULT_KEY}: true")
            return "\n".join(lines)
    return content.rstrip("\n") + f"\n{TRAVELS_DRAFT_DEFAULT_KEY}: true\n"


def _manifest_has_hand_table(_manifest_path) -> bool:
    """T-12399 — is the SPEC_TRAVELS_REPIN_CUE's companion step ACTIONABLE here? The cue asks the
    author to hand-update a row in kernel-vs-self-manifest.md; a CONSUMER corpus has no such file
    (the kernel-vs-self split is the ENGINE's own concern), so printing it there names a file that
    does not exist and a probe that cannot fail. FAIL-SAFE in both directions: an absent injector —
    any caller that has not been given `_manifest_path` — or a raising one keeps the cue, so the
    engine path and every legacy caller are unchanged; only a PROVABLY absent manifest silences it."""
    if _manifest_path is None:
        return True
    try:
        return bool(_manifest_path().exists())
    except Exception:
        return True

# ── T-10321 — body-composed `spec edit` matching (the indentation trap, X-0284) ───────────────────
# `spec edit` matches `old` against the RAW file text, but `--help` sells --from-file as a body
# replacement and `graph query <SPEC>` prints the body UNindented (YAML strips the block-scalar
# indent on parse). So an `old` composed from what the author READ can never match what is on DISK.
# These two helpers let the exact-match miss re-try at the body's own indentation before dying.

# The `body:` block-scalar header — `|`, `|-`, `>`, `|2+`, … (the indicator chars YAML allows after
# the style char). Anchored at line start: only the TOP-LEVEL `body:` key opens the spec body.
# The header may carry a TRAILING YAML COMMENT (T-10602 / X-0449): the `spec new` scaffold's own
# header does (`body: |    # fixed minimal section shape per D-0044 …`), so requiring a BARE header
# blinded this matcher to every fresh scaffold — the fallback below never fired and the governed
# `spec edit --from-file` path was unusable on a just-created spec. The comment must be space-
# separated: `body: |#x` is not a YAML comment (the `#` is glued to the indicator), so it must NOT
# match — a header this matcher cannot read must fail closed rather than guess an indent.
_BODY_BLOCK_RE = re.compile(r"^body:[ \t]*[|>][0-9+-]*(?:[ \t]+#[^\n]*)?[ \t]*$", re.MULTILINE)


def _body_block_indent(text: str) -> str | None:
    """The leading whitespace of a spec's `body:` block-scalar content, or None when there is no
    indented body block. Read off the first non-blank line after the header — that is the indent YAML
    strips on parse, so re-applying it maps parsed-body text back onto raw file text."""
    m = _BODY_BLOCK_RE.search(text)
    if m is None:
        return None
    for line in text[m.end():].split("\n")[1:]:
        if line.strip():
            indent = line[:len(line) - len(line.lstrip())]
            return indent or None
    return None


def _ws_normalise(s: str) -> str:
    """Collapse every whitespace run to one space and strip — the T-12933 payload-encoding probe."""
    return " ".join(s.split())


def _reindent(s: str, indent: str) -> str:
    """Prefix `indent` to every non-blank line. Blank lines stay blank — YAML block scalars carry no
    trailing indent on an empty line, so indenting them would fabricate text the file does not hold."""
    return "\n".join(indent + ln if ln.strip() else ln for ln in s.split("\n"))


def _reindent_continuation(s: str, indent: str) -> str:
    """`_reindent` for text that starts MID-LINE (T-13676): the first line is kept as written and
    only the lines after it gain `indent`. In the raw file the block indent sits at the START of the
    line the text begins in, ahead of the characters before it — never between them and the text."""
    first, sep, rest = s.partition("\n")
    return first + sep + _reindent(rest, indent) if sep else s


# ── T-13509 — the two READINGS of a block-body edit (GitHub issue #11) ─────────────────────
# A mid-line `old` with a multi-line `new` can be read two ways: as RAW FILE TEXT (the continuation
# lines land at the column they were typed at, in the file) or as an edit of the PARSED BODY (they
# land at the nesting they were typed at, in the body). When the two disagree the verb must say so in
# the author's terms, in the corrective note and in the refusal alike — one wording, built here.

def _body_reading_diff(raw_body, asked_body: str, added_keys) -> str:
    """One clause naming BOTH readings: the first body line where the raw write and the asked edit
    differ, plus any top-level key the raw write would have added."""
    got = raw_body.split("\n") if isinstance(raw_body, str) else []
    want = asked_body.split("\n")
    clause = (f"as raw file text the body would carry {len(got) - len(want)} more line(s) than as an "
              f"edit of the parsed body")
    for i, w in enumerate(want):
        g = got[i] if i < len(got) else None
        if g != w:
            raw_side = repr(g) if g is not None else "nothing (the body ends before it)"
            clause = (f"body line {i + 1} would read {raw_side} as raw file text, but {w!r} as an "
                      f"edit of the parsed body")
            break
    if added_keys:
        clause += ("; the raw write would also add top-level key(s) "
                   + ", ".join(f"`{k}`" for k in added_keys))
    return clause


# ── T-11109 — the FLOW-SCALAR sibling of the indentation trap (X-0882) ───────────────────────────
# A spec `body:` need not be a BLOCK scalar. <project>'s SPEC-0042 stores it as a double-quoted FLOW
# scalar: one physical line whose interior newlines are carried as literal `\n` escapes. There
# `_body_block_indent` reads None, so the T-10321 fallback above could never fire and every
# body-composed `old` refused — while `yaml.safe_load(spec)["body"]` contained that very text.
#
# WHY THE NARROW FIX (the trade-off, recorded where the code lives). The reported suggestion was to
# match the PARSED body and RE-SERIALIZE, so storage style stops being load-bearing. Rejected: the
# emitter would rewrite the WHOLE scalar, normalizing every edited spec's storage style and making
# the diff the entire body instead of the edit — for a verb whose whole value is that its diff IS
# the edit. Adopted instead: encode the CANDIDATE into the file's own stored form and re-count.
# Storage style stops being load-bearing FOR THE AUTHOR (the actual complaint) and not a byte
# outside the replacement site moves.
_BODY_FLOW_RE = re.compile(r"^body:[ \t]*(['\"])", re.MULTILINE)


def _body_flow_quote(text: str) -> str | None:
    """The quote character of a spec's top-level `body:` QUOTED FLOW scalar, or None when the body
    is not stored that way (a block scalar, an unquoted plain scalar, or no body at all).

    Anchored at line start like `_BODY_BLOCK_RE`: only the TOP-LEVEL `body:` key opens the body."""
    m = _BODY_FLOW_RE.search(text)
    return m.group(1) if m else None


# The candidate encoder now lives in `lib/textutil.py` (T-11166): `task update`'s field-edit hit the
# SAME root on a WRAPPED single-quoted scalar, so the encoder was hoisted to the one shared home and
# both verbs call it. Behaviour here is unchanged BY CONSTRUCTION — this name is a thin alias to the
# moved function, not a copy (CHARTER §P1 F1: extend the analog, never fork a second matcher).
_flow_encode_variants = textutil.flow_encode_variants


# ── T-13581 — a quoted body WRAPPED across physical lines (GitHub issue #11, follow-up) ──────────
# The T-11109 encoder above renders a candidate on ONE line, so it can never equal text a generic
# YAML dump stored wrapped at 80 columns: one parsed line of 1-3 kB spans some thirty physical
# lines, and "narrow `old` to a single line" is then no route at all. No kernel writer produces
# that form (`spec new` scaffolds a literal block, and the status flips are single-line edits) —
# it arrives with a whole-segment replacement written outside these verbs.
#
# T-11109 rejected re-serialising the parsed body AS THE GENERAL ROUTE, because it rewrites the
# whole scalar where a narrow splice exists. That stays true and stays the primary path. These two
# helpers serve ONLY the case with no narrow splice — the one the verb used to refuse: the edit is
# applied to the parsed text and the scalar is re-emitted as a literal `|` block, the form every
# kernel-written spec already has, accepted only when the result reparses to the expected record.


def _literal_block_blocker(value: str) -> str | None:
    """The character class that keeps `value` from being stored as a literal block without changing
    a character, or None when nothing does. Named, because the refusal has to say WHICH.

    Deliberately conservative on whitespace: a literal block CAN carry a trailing space, but only
    until the next editor or formatter strips it, and then the body changes with no diff a reader
    would notice — PyYAML's own emitter declines the block style for such text for that reason. A
    tab where a line starts sits where YAML reads indentation. Both stay in the quoted form."""
    for ch in value:
        o = ord(ch)
        if ch in "\r\x85\u2028\u2029":
            return f"a line-break character other than LF (U+{o:04X})"
        if not (ch in "\t\n" or 0x20 <= o <= 0x7e or 0xa0 <= o <= 0xd7ff
                or 0xe000 <= o <= 0xfffd or o >= 0x10000):
            return f"a control character (U+{o:04X})"
    for i, ln in enumerate(value.split("\n"), 1):
        if ln != ln.rstrip(" \t"):
            return f"trailing whitespace (body line {i})"
        if ln.startswith("\t"):
            return f"a tab-led line (body line {i})"
    return None


def _quoted_body_as_literal_block(text: str, value: str) -> str | None:
    """`text` with its top-level QUOTED `body:` scalar replaced by `value` as a literal block, or None
    when the file does not have that shape. Every byte outside the scalar is kept as it is.

    The chomping indicator carries the body's own ending (`|` one final newline, `|-` none, `|+`
    several) and an indentation indicator is added when the first content line starts with a space,
    so the block needs no change to the text to be read back — an empty body is `|-` with no line,
    a body of newlines alone is `|+` over that many blank lines. A comment trailing the closing
    quote moves onto the block header. The one byte that can be ADDED outside the scalar is a final
    newline, when the scalar ended a file that had none: a block's last line needs its line end.
    The CALLER verifies the reparse."""
    import yaml
    try:
        root = yaml.compose(text, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    except Exception:                                # noqa: BLE001 — unparseable → not this case
        return None
    node = None
    if isinstance(root, yaml.MappingNode):
        for key, val in root.value:
            if isinstance(key, yaml.ScalarNode) and key.value == "body":
                node = val
    if not isinstance(node, yaml.ScalarNode) or node.style not in ('"', "'"):
        return None
    if not value.strip("\n"):
        # No content line at all: nothing to clip, so the newlines are kept or there are none.
        header, block = ("|+" if value else "|-"), value
    else:
        if value.endswith("\n\n"):
            chomp, content = "+", value[:-1]
        elif value.endswith("\n"):
            chomp, content = "", value[:-1]
        else:
            chomp, content = "-", value
        lines = content.split("\n")
        first = next(ln for ln in lines if ln)
        header = "|" + ("2" if first.startswith(" ") else "") + chomp
        block = "".join(("  " + ln if ln else "") + "\n" for ln in lines)
    # The rest of the scalar's last physical line. YAML admits only blanks and a comment there, and
    # a block header may carry both, so it moves up beside the header byte for byte.
    tail = text[node.end_mark.index:]
    eol = tail.find("\n")
    rest, tail = (tail, "") if eol < 0 else (tail[:eol], tail[eol + 1:])
    if rest.strip(" \t") and not rest.lstrip(" \t").startswith("#"):
        return None
    return text[:node.start_mark.index] + header + rest + "\n" + block + tail


# ── T-12839 / X-1525 — spec-id ALLOCATION ZONES (rule home: SPEC-0092 §Allocation zones) ────────
# Every repo used to allocate own-max+1, so the kernel and each consumer walked the SAME number line and
# the kernel's next ids collided with ids consumers already held (<project> SPEC-0206..0214 vs kernel
# SPEC-0209). New ids now come from disjoint zones of the same 4-digit shape: the kernel from 1000-4999,
# every consumer from 5000-9999 on its own counter (equal numbers across consumers are harmless — no
# consumer sees another's specs). The legacy band 0001-0999 is CLOSED to new ids but every existing id
# in it stays valid and is never renamed. This table is the ONE policy home: sequential allocation and
# `--id` validation both read it through `spec_id_zone`.
SPEC_ID_ZONES = {"kernel": (1000, 4999), "consumer": (5000, 9999)}


def spec_id_zone(is_consumer: bool) -> "tuple[str, int, int]":
    """(role, lo, hi) for the repo being written. `is_consumer` is the authoritative repo-context
    predicate the caller already holds (`_is_consumer_build`: a different git common-dir than the
    engine), never a guess from the corpus contents."""
    role = "consumer" if is_consumer else "kernel"
    lo, hi = SPEC_ID_ZONES[role]
    return role, lo, hi


# The T-12397 allocation-time kernel-collision WARN is RETIRED here: with disjoint zones a NEW consumer
# id can never be an id the kernel owns, so the WARN could no longer fire. Historical collisions in the
# legacy band keep the SPEC-0092 `--kernel` escape and the T-10700 lookup-time disclosure.
_EXPLICIT_ID_RE = re.compile(r"^SPEC-(\d{4})$")


def _parse_explicit_spec_id(raw, *, _die) -> "int | None":
    """`--id SPEC-NNNN` → the integer the allocator admits, or None when the flag was omitted. SHAPE
    only (T-12397): whether the id is FREE is the allocator's call under the lock, because only there
    is the answer race-free."""
    raw = (raw or "").strip()
    if not raw:
        return None
    m = _EXPLICIT_ID_RE.match(raw.upper())
    if not m:
        _die(f"--id: invalid {raw!r} — expected the canonical SPEC-NNNN form (4 digits), e.g. SPEC-0062")
    return int(m.group(1))


# ── T-10298 / SPEC-0151 — the active-behavioral-mandate ANCHOR RULE (report-only) ────────────────
# An ACTIVE spec that tells the system to BEHAVE somehow must answer "who executes this?" with a code
# anchor, a binding-delivered human obligation, or an honest not-executed marker. The real incident:
# SPEC-0097 §5 said "execution lives in tasks T-9416/17/18"; the tasks closed; no code existed. A task
# id is PROVENANCE, never an execution carrier (SPEC-0151 §Internal 2).

# A behavioral MANDATE, detected by the RFC-2119 uppercase modal the v2 corpus uses for normative
# emphasis. This is the rule's SCOPING half: a documentary spec that merely describes a shape carries
# none of these, so it is out of scope BY CONSTRUCTION (§Internal 3) rather than by an exception list.
_MANDATE_RE = re.compile(r"\b(?:MUST NOT|MUST|SHALL|REQUIRED)\b")

# A bare artifact id is provenance, NOT a code anchor — the defect this rule exists to name. Anchored
# at both ends so a real anchor that merely CONTAINS an id (`bin/yitc-v2#_t9416_gate`) still counts.
_PROVENANCE_ID_RE = re.compile(r"^(?:T|D|E|X|SPEC)-\d+$", re.IGNORECASE)

# `code-enforced` is a marker CLAIMING code enforcement — it reaches no person at a moment of use, so
# it is not a satisfier on the human-obligation leg; it must pay the `implements:` leg instead. Every
# other binding token (`spec-new`, `commit`, `close`, `stage-entry:*`, `floor`, `before-*`) IS a
# delivery trigger: it puts the rule in front of a human before the gated action.
_NON_DELIVERING_BINDING = frozenset({"code-enforced"})

# The honest third answer: "nothing executes this; a person owns it." A DECLARATION, never a mention:
# the marker is a line-anchored `execution: not-executed|operator-owned` directive (optionally quoted /
# bolded / block-quoted, as a markdown body allows). A bare substring search is what SPEC-0151 itself
# first failed — its own body DESCRIBES the two tokens while defining satisfier (c), which silenced the
# check on the very spec that defines it. Same class the sibling SPEC-0150 chain-check names: a prose or
# log mention (`print("restore_drill")`) is not a read site. Prose about a marker is not a marker.
# The trailing `(?![\w-])` is a token boundary, not decoration: without it the match is a PREFIX, so a
# malformed `execution: not-executedness` (or `operator-owned-ish`) would silence the rule — a satisfier
# must be the exact token (audit-post finding, T-10298 pass 1).
_NOT_EXECUTED_MARKER_RE = re.compile(
    r"^\s*(?:>\s*)?\**execution\**\s*:\s*[`'\"]?(?:not-executed|operator-owned)(?![\w-])",
    re.IGNORECASE | re.MULTILINE)

# T-12973 — the FOURTH honest answer: "this spec is documentary; nothing executes it, by design" — the
# machine-recognizable form of SPEC-0005 §7 empty-implements mode (a). Same line-anchored DECLARATION
# shape (and token boundary) as the marker above, but it MUST carry a reason on the same line: a bare
# `execution: documentary` is an unexplained opt-out, which is exactly the silence the rule forbids.
_DOCUMENTARY_MARKER_RE = re.compile(
    r"^\s*(?:>\s*)?\**execution\**\s*:\s*[`'\"]?documentary(?![\w-])(?P<rest>[^\n]*)$",
    re.IGNORECASE | re.MULTILINE)
# What separates the token from its reason (closing quote/bold, dashes, colon) is not itself a reason.
_DOCUMENTARY_SEPARATOR_CHARS = "`'\"*\u2014\u2013-:;,. \t"

_ANCHOR_RULE_STATUSES = ("active",)


def _has_disposition_marker(body: str) -> bool:
    """Satisfier (c): a not-executed/operator-owned marker, or a documentary marker WITH a reason."""
    if _NOT_EXECUTED_MARKER_RE.search(body):
        return True
    return any(re.search(r"\w", m.group("rest").strip(_DOCUMENTARY_SEPARATOR_CHARS))
               for m in _DOCUMENTARY_MARKER_RE.finditer(body))


def _is_code_anchor(entry) -> bool:
    """An `implements:` entry that names CODE, not an artifact id (SPEC-0151 §Internal 2)."""
    text = str(entry or "").strip()
    return bool(text) and not _PROVENANCE_ID_RE.match(text)


def anchor_rule_violation(rec, *, statuses: tuple = _ANCHOR_RULE_STATUSES, all_specs: bool = False):
    """SPEC-0151 §Internal 1 — pure f(spec record) → a reason string, or None when the rule holds.

    A spec in `statuses` whose `body:` carries a behavioral mandate must name AT LEAST ONE of:
      (a) an `implements:` CODE anchor (a bare task/spec id does not count — provenance != execution);
      (b) a `binding:`-delivered HUMAN obligation (a delivery trigger; `code-enforced` claims code and
          so pays leg (a) instead — it reaches nobody);
      (c) an explicit `not-executed` / `operator-owned` body marker, or `execution: documentary`
          followed by a non-empty reason on the same line (T-12973; a bare one does not count).

    REPORT-ONLY by contract (§Internal 3): callers WARN, never refuse. Hardening to a hard gate needs
    its own incident (CHARTER §P1 F4) — a WARN that provably fails to change behaviour.

    `statuses` widens the check for the AUTHORING surfaces: the RULE governs `active` specs (what the
    conformance sweep walks), but a `proposed` head is the pre-image of an active spec, and catching a
    missing anchor at authoring is the entire point of an authoring-time warning — by the time it
    activates at `task close`, the author has moved on. Pure: no I/O, no host deps.

    `all_specs=True` (T-12973) drops the mandate SCOPING half: `_MANDATE_RE` is the English RFC-2119
    modal set, so a body written in another natural language is never evaluated by default. Under this
    scope every spec in `statuses` must carry one of the dispositions above. The default stays
    mandate-scoped so the existing callers are unchanged — except that a `code-enforced` binding is in
    scope regardless of body wording (T-13070): the token itself claims code enforcement."""
    if not isinstance(rec, dict):
        return None
    if (rec.get("status") or "").strip() not in statuses:
        return None
    binding = [str(b).strip() for b in (rec.get("binding") or []) if str(b).strip()]
    # T-13070: `code-enforced` IS the claim that code enforces the spec — in scope whatever the body says.
    scoped = all_specs or "code-enforced" in binding
    body = rec.get("body")
    if not isinstance(body, str):
        if not scoped:
            return None
        body = ""
    elif not scoped and not _MANDATE_RE.search(body):
        return None                                  # documentary / no mandate — out of scope
    if _has_disposition_marker(body):
        return None                                  # (c) an honest "nothing executes this"
    if any(_is_code_anchor(a) for a in (rec.get("implements") or [])):
        return None                                  # (a) a code anchor
    if any(b not in _NON_DELIVERING_BINDING for b in binding):
        return None                                  # (b) a binding-delivered human obligation
    impl = [str(a).strip() for a in (rec.get("implements") or []) if str(a).strip()]
    if impl:
        detail = (f"names only provenance in `implements:` ({', '.join(impl)}) — a task/spec id records "
                  f"WHO shipped it, not WHAT executes it")
    elif binding:
        detail = (f"carries `binding: [{', '.join(binding)}]`, which claims code enforcement but names "
                  f"no `implements:` anchor")
    else:
        detail = "names no `implements:` anchor and no `binding:` delivery"
    if all_specs:
        what = "spec"
    elif _MANDATE_RE.search(body):
        what = "body carries a behavioral mandate but"
    else:
        what = "spec claims `code-enforced` but"         # T-13070: in scope by binding, not by modal
    return (f"{what} {detail}. Name a code anchor, a binding-delivered human obligation, or an explicit "
            f"not-executed/operator-owned marker or `execution: documentary — <reason>` "
            f"(SPEC-0151 §Internal 1)")


def pending_successors(sid: str, records) -> list:
    """[(successor id, its `activation_owner_task` or None), …] sorted — the `proposed` specs among
    `records` whose `supersedes:` names `sid` (T-13672). Pure f(records): no I/O.

    Reads exactly what the activation writer acts on (`bin/lib/task.py#_activate_task_proposed_specs`):
    a `proposed` head, and its `supersedes:` as ONE scalar id. Any other shape of that field is one
    the writer never flips a target from, so it is not reported as a pending supersession here."""
    out = []
    for rec in records or ():
        if not isinstance(rec, dict) or rec.get("status") != "proposed":
            continue
        target, succ = rec.get("supersedes"), rec.get("id")
        if not isinstance(target, str) or target.strip() != sid:
            continue
        if not isinstance(succ, str) or not succ.strip():
            continue
        owner = rec.get("activation_owner_task")
        out.append((succ.strip(), owner.strip() if isinstance(owner, str) and owner.strip() else None))
    return sorted(out, key=lambda pair: (pair[0], pair[1] or ""))


def _pending_supersession_note(sid: str, successors) -> str:
    """The sentence the anchor-rule WARN gains when `sid` has pending successors; "" when it has none."""
    if not successors:
        return ""
    named = ", ".join(f"{succ} (activation_owner_task {owner})" if owner
                      else f"{succ} (no activation_owner_task named yet)" for succ, owner in successors)
    return (f" Pending supersession: proposed {named} names {sid} in `supersedes:`, so {sid} is due to "
            f"flip to `superseded` when that spec is activated by the close of its "
            f"activation_owner_task. If this edit moved the anchors to that successor, an anchor-less "
            f"{sid} is the expected state until then.")


def _warn_anchor_rule(sid: str, rec, *, verb: str, specs_dir=None) -> None:
    """Report-only WARN for the two authoring verbs. Never refuses, never touches the exit code — the
    authoring half of SPEC-0151 §Internal 3 (its other half is the graph-conformance sweep line).

    Widened to `proposed` for the reason in `anchor_rule_violation`. On `spec new` this is near-silent
    by construction (the scaffold's template body carries no mandate) — it stands as the symmetric
    guard the spec names, and it fires the moment a template or a `--from-file` birth carries one.

    `specs_dir` (T-13672, passed by `spec edit`): when the rule fires on an ACTIVE record, the spec
    files beside it are read for a `proposed` spec that supersedes it, and the WARN names each one —
    the activation-owner card of a successor empties the old spec's anchors on purpose. The read
    happens only on that path and is fail-soft: an unreadable directory or file names no successor,
    and the WARN then reads exactly as it does with none."""
    reason = anchor_rule_violation(rec, statuses=("active", "proposed"))
    if not reason:
        return
    note = ""
    if specs_dir is not None and rec.get("status") == "active":
        records = []
        try:
            paths = state.scan_specs(specs_dir)
        except Exception:
            paths = []
        for p in paths:
            try:
                records.append(state.load_str(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        note = _pending_supersession_note(sid, pending_successors(sid, records))
    print(f"⚠ anchor-rule (SPEC-0151) after `{verb}`: {sid} {reason}{note}", file=sys.stderr)


def cmd_spec_new(args: argparse.Namespace, *, _require_writing_worktree, _die, _yaml_scalar,
                 _utc_now_iso, PLANS_DIR, _require_reads, PLACEMENT_REALMS, _SPEC_CLASS_DEFAULT,
                 _kernel_content_file, _scaffold_read_validate, _id_alloc_lock, SPECS_DIR, _slug,
                 _scaffold_substitute, write_text_atomic, _append_event, REPO_ROOT,
                 _governing_contract_for, _manifest_path, _backfill_spec_placement_handrow,
                 _is_consumer_build=None) -> None:
    """Allocate the next SPEC-NNNN under flock + scaffold from specs/_template.yaml. Emits
    spec_filed + а reminder. Filename convention: specs/SPEC-NNNN-<slug>.yaml (matches the corpus)."""
    _require_writing_worktree()
    title = (args.title or "").strip()
    if not title:
        _die("--title required (non-empty)")
    subs = {"title": _yaml_scalar(title), "created_at": _utc_now_iso()}
    # T-0186 Part A — `--draft` BIRTHS a draft spec (status: draft, below proposed in the FSM,
    # SPEC-0005 §4): plan-LOCAL, non-authoritative, governs nothing. A draft is owned by a plan,
    # so `--proposed-by <plan>` is MANDATORY with `--draft` and the plan MUST EXIST (audit-pre
    # F1/F2 — no dangling plan refs). NO draft→proposed verb here: that promotion is Part B's
    # `plan accept` / task-staging (part-b-narrow §3) — this verb only creates.
    if getattr(args, "draft", False):
        plan_slug = (getattr(args, "proposed_by", None) or "").strip()
        if not plan_slug:
            _die("--draft requires --proposed-by <plan-slug> (a draft is plan-local; SPEC-0005 §4 FSM)")
        if not (PLANS_DIR / f"{plan_slug}.md").exists():
            _die(f"--proposed-by: no such plan plans/{plan_slug}.md — reject dangling plan ref (audit-pre F2)")
        # T-0599 — read-check graduation onto the plan-axis `specs` work-verb (SPEC-0050 §6 / SPEC-0059):
        # `spec new --draft` composes a plan's draft specs (the plan `specs` stage), so it REFUSES — before
        # allocating an id — unless THIS session fetched the plan `specs` stage bundle
        # (plan-stage-entry:specs = [SPEC-0034]). The NON-draft `spec new` path below is UNTOUCHED — its
        # before-rule-change->SPEC-0005 floor trigger is the RESERVED kind=action path (T-0420 territory).
        _require_reads("stage", {"axis": "plan", "stage": "specs", "verb": "spec new --draft",
                                 "action": "compose a draft spec"})
        subs["status"] = "draft"
        subs["proposed_by"] = plan_slug
    elif getattr(args, "proposed_by", None):
        _die("--proposed-by is only valid with --draft (a proposed spec is born via its activation flow)")
    # T-0888 placement write-point. The placement decision is an explicit in-flow OUTPUT of `spec new`
    # (the external-audit HIGH hardening: capture at the governed authoring path, not audit-only).
    # `--travels {kernel|v2-self|project|default}` is REQUIRED for an authoritative NON-draft (proposed)
    # birth and FAILS CLOSED when omitted; `default` consciously affirms the spec class-default (kernel).
    # A `--draft` is plan-LOCAL and governs nothing (SPEC-0005 §4) → travels is OPTIONAL there (defaults
    # to class-default; the placement is pinned when the draft is promoted to proposed). Checked AFTER the
    # draft read-gate (so a draft's read-check still fires first) but BEFORE the template read /
    # `_id_alloc_lock`, so a missing decision burns no SPEC-id (F-011). Contract: SPEC-0073.
    is_draft = bool(getattr(args, "draft", False))
    travels_arg = (getattr(args, "travels", None) or "").strip().lower()
    # T-12399 (<project> X-1335) — the predicate is bound ONCE here and drives BOTH the hint text (as
    # before) and the realm resolution below. It was previously computed inline for the hint ALONE, so
    # a consumer's own spec silently resolved an ENGINE realm: a draft to `v2-self` (the engine's own
    # development history) and a non-draft `default` to `kernel` (the pinned methodology). SPEC-0073
    # rule 1 gives a consumer's own specs exactly ONE legitimate realm — `project`.
    is_consumer = bool(_is_consumer_build and _is_consumer_build())
    if travels_arg and travels_arg not in (*PLACEMENT_REALMS, "default"):
        _die(f"--travels: invalid '{travels_arg}' — choose one of kernel | v2-self | project | default")
    # Refused BEFORE the non-draft fail-closed check below and BEFORE `_id_alloc_lock`, so a refused
    # realm burns no SPEC-id (F-011) — and a consumer that omits `--travels` on a non-draft still gets
    # the unchanged fail-closed message, not this one.
    if is_consumer and travels_arg in ("kernel", "v2-self"):
        _die(f"--travels {travels_arg}: refused on a CONSUMER corpus — SPEC-0073 rule 1 gives this "
             "project's own specs exactly ONE legitimate realm: `project` (`v2-self` names the ENGINE's "
             "own development history and `kernel` is the pinned methodology, neither of which a "
             "consumer authors locally). Author it as `--travels project` (or omit `--travels` on a "
             "`--draft`, which now resolves `project` here); to change the KERNEL, propose it with "
             "`bin/yitc-v2 cross request --kind task --to yitc-v2 …` — never by a local travels:kernel.")
    if not is_draft and not travels_arg:
        _die("--travels {kernel|v2-self|project|default} required — the corpus-wide placement contract "
             "(SPEC-0073) fails closed: a new proposed spec MUST carry an explicit placement decision at "
             f"authoring (`{graph_lib.spec_query_hint('SPEC-0073', is_consumer=is_consumer, cli='')}`). "
             "`default` affirms the spec class-default (kernel).")
    if is_consumer:
        # SPEC-0073 rule 1/§3 consumer clause: the ONE legitimate realm. `kernel`/`v2-self` are already
        # dead above, so the only survivor an explicit arg can carry is `project` — the draft default and
        # `--travels default` resolve there too. The engine arms below are reached UNCHANGED.
        resolved_realm = "project"
    elif is_draft:
        # A DRAFT is plan-local (SPEC-0005 §4) and governs nothing; SPEC-0073 §8 requires a non-active
        # spec to NOT resolve the kernel export realm, so a draft DEFAULTS to v2-self — the §3↔§8
        # coherence fix (T-9285): a kernel-default draft otherwise fails `graph conformance` the moment
        # it is born. EXPLICITLY map only the documented kernel-aliases (omitted / `default` / `kernel`)
        # to v2-self; an explicit `v2-self`/`project` is HONORED (an out-of-set value cannot reach here —
        # the argparse `choices` above already fail-closed it). The kernel re-pin is an EXPLICIT action
        # at plan-accept, never a `_birth_plan_draft_specs` side-effect.
        resolved_realm = "v2-self" if (not travels_arg or travels_arg in ("default", "kernel")) else travels_arg
    else:
        resolved_realm = _SPEC_CLASS_DEFAULT if (not travels_arg or travels_arg == "default") else travels_arg
    # Body marker ONLY for a NON-default exception (default/kernel → no redundant marker; unmarked =
    # class-default). The decision itself is recorded DURABLY in the spec_filed event below. A draft's
    # resolved v2-self is a non-default exception, so the marker IS written (T-9285).
    if resolved_realm != _SPEC_CLASS_DEFAULT:
        subs["travels"] = resolved_realm
    # T-12972 — the realm was DEFAULTED, not decided: a kernel-destined draft (omitted / `default` /
    # `kernel`) resolved to v2-self. Marked on disk so activation can refuse until someone decides.
    draft_defaulted = is_draft and not is_consumer and resolved_realm == "v2-self" and (
        not travels_arg or travels_arg in ("default", "kernel"))
    # T-0860: resolve the template with an ENGINE_ROOT fallback for a -C consumer (F-010/F-012) AND read
    # + validate it BEFORE allocating the id (F-011 no-ID-burn — see _scaffold_read_validate). The id is
    # the OUTPUT of a successful scaffold precondition, not a cost paid up front.
    template = _kernel_content_file("specs/_template.yaml")
    template_text = _scaffold_read_validate(template, ["id", *subs.keys()])
    # T-13013: the template is KERNEL-authored; its comment cites name KERNEL specs. In a consumer a bare
    # id resolves the consumer's own spec first (SPEC-0092), so realm-qualify them (SPEC-0073 r6). Done
    # BEFORE the id substitution, so the new spec's own (consumer) id is never qualified.
    template_text = graph_lib.kernel_qualify(template_text, is_consumer=is_consumer)
    # T-12397 — `--id SPEC-NNNN` overrides the sequential allocation. Parsed BEFORE the lock so a
    # malformed value never opens one; ADMISSION (strictly above the floor) is the allocator's, under
    # the lock, and fails closed with no id burned and no file written.
    explicit = _parse_explicit_spec_id(getattr(args, "id", None), _die=_die)
    # T-12839 — the zone this repo allocates from (SPEC-0092 §Allocation zones). An `--id` outside it is
    # refused HERE, before the lock, so it opens nothing and burns no id; the sequential path is lifted
    # into the zone (and refused at its ceiling) by the allocator's `band`, under the lock.
    zone_role, zone_lo, zone_hi = spec_id_zone(is_consumer)
    if explicit is not None and not zone_lo <= explicit <= zone_hi:
        _die(f"spec-id-outside-zone: --id SPEC-{explicit:04d} is outside this {zone_role}'s spec-id zone "
             f"SPEC-{zone_lo:04d}..SPEC-{zone_hi:04d} (SPEC-0092 §Allocation zones). New ids are never "
             f"allocated below SPEC-1000; the kernel allocates 1000-4999 and every consumer 5000-9999. "
             f"Pick an id in the zone, or omit --id to take the next one.")
    alloc_kw = {"explicit": explicit} if explicit is not None else {}
    with _id_alloc_lock(SPECS_DIR, "SPEC", band=(zone_lo, zone_hi), **alloc_kw) as sid:
        path = SPECS_DIR / f"{sid}-{_slug(title, die=_die)}.yaml"
        if path.exists():
            _die(f"collision (post-lock): {path.name} already exists")
        content = _scaffold_substitute(template_text, template.name, {"id": sid, **subs})
        if draft_defaulted:
            content = _mark_travels_draft_default(content)
        write_text_atomic(path, content)
        _append_event("spec_filed", sid, {
            "path": str(path.relative_to(REPO_ROOT)), "title": title,
            "status": subs.get("status", "proposed"),
            "travels": resolved_realm,          # T-0888 — the DURABLE placement decision for EVERY new
            "id_explicit": explicit is not None,  # T-12397 — the id was CHOSEN, not sequentially allocated
            "id_zone": zone_role,               # T-12839 — the zone the id was allocated from (kernel|consumer)
            "travels_explicit": bool(travels_arg),  # spec (distinguishable from a legacy unmarked spec, even
                                                # when the body marker is omitted for the default case). True
                                                # iff --travels was passed (always for a non-draft; optional draft).
            "governing_contract": _governing_contract_for("spec-new")})  # delivery-observability (T-0272/SPEC-0013)
    # T-9497 — auto-backfill the kernel-vs-self manifest §1 HAND-table row IN-FLOW (E-0029), so a new
    # spec never discovers a missing §1 row late at land (test_t0890 §B2). Idempotent + fail-safe: an
    # absent manifest / hand table / unknown realm leaves the manifest untouched (a -C consumer with no
    # such manifest is the absent-file case). The §1-derived GEN block stays graph-build-regenerated.
    manifest = _manifest_path()
    if manifest.exists():
        before = manifest.read_text(encoding="utf-8")
        after = _backfill_spec_placement_handrow(before, sid, subs.get("status", "proposed"),
                                                 resolved_realm, title)
        if after != before:
            write_text_atomic(manifest, after)
    print(f"spec filed: {path.relative_to(REPO_ROOT)} (id={sid})")
    if draft_defaulted:
        # teach the workflow only when a kernel-DESTINED draft was DEFAULTED to v2-self (the common
        # case); an explicit `--travels v2-self`/`project` is the author's deliberate choice, no notice.
        print(f"note: draft → travels:v2-self (plan-local, governs nothing) and marked "
              f"`{TRAVELS_DRAFT_DEFAULT_KEY}: true` — `task close` REFUSES to activate it until the realm "
              f"is decided: re-pin to kernel, or confirm v2-self/project, by removing the marker via "
              f"`spec edit` (SPEC-0073 §3, T-12972).")
    print("next: fill implements: durable anchors — PREFER <file>#<symbol> over a bare <file> "
          "(the code-decompose rule, SPEC-0088); NOT line ranges (D-0036) + body "
          "Statement/Rationale/Verification (GRAPH §Schema for specs).")
    print(f"cue: {SPEC_BODY_EDIT_CUE}")  # T-10159 (a-d single-SoT)
    # T-10298 (SPEC-0151) — report-only anchor-rule WARN on the born record. Parsed from the text just
    # written (never re-read from disk): the scaffold IS the record. A parse failure here must never
    # break the birth of a spec whose file is already on disk, so it degrades to silence.
    try:
        _warn_anchor_rule(sid, state.load_str(content), verb="spec new")
    except Exception:
        pass


def _spec_edit_target(base_path, base_rec, old, *, _read_yaml, _die):
    """T-12925: the ONE file of a spec's SPEC-0120 part chain that `spec edit --old` should edit, with
    its parsed record. An un-split spec is its base. `old` counts as present in a file on a raw match
    OR a match in that file's parsed `body:` (the two tests the indentation/flow fallbacks apply).
    Present in NO file → the base, so the existing old-not-found diagnostics speak unchanged. Present
    in MORE than one → refused: a replacement never spans files silently, not even with --replace-all."""
    chain = state.spec_part_paths(base_path)
    if len(chain) == 1:
        return base_path, base_rec
    hits = []
    for p in chain:
        rec = base_rec if p == base_path else (_read_yaml(p) or {})
        body = rec.get("body") if isinstance(rec, dict) else None
        if old in p.read_text(encoding="utf-8") or (isinstance(body, str) and old in body):
            hits.append((p, rec))
    if len(hits) > 1:
        _die(f"`old` occurs in {len(hits)} files of this spec's part chain "
             f"({', '.join(p.name for p, _r in hits)}) — narrow it to the one file you mean; "
             f"a replacement never spans files (T-12925).")
    return hits[0] if hits else (base_path, base_rec)


def _spec_chain_with_main_parts(base_path, *, _run_git_cap, REPO_ROOT) -> list:
    """T-12925: the files a `--bless` must compare against `main` — the on-disk part chain PLUS any part
    that exists on `main` but not on disk (a DELETED part moves the spec's body too). Discovered off
    `git ls-tree main`, never a declared list, with the same name rule `state.spec_part_paths` uses."""
    chain = state.spec_part_paths(base_path)
    listing = _run_git_cap(["ls-tree", "--name-only", "main",
                            f"{base_path.parent.relative_to(REPO_ROOT)}/"], REPO_ROOT)
    if listing.returncode == 0:
        for ln in listing.stdout.splitlines():
            p = REPO_ROOT / ln.strip()
            m = state._SPEC_PART_RE.match(p.name)
            if m and m.group(1) == base_path.stem and state.is_spec_part(p) and p not in chain:
                chain.append(p)
    return chain


def governed_content_digest(rec: dict) -> str:
    """The GOVERNED-CONTENT digest of a parsed spec record — sha256 over `body:` + `implements:` only
    (T-11207 / X-0951). This is EXACTLY the T-9730 land guard's own trigger surface: that guard fires
    on an active spec whose `body:` OR `implements:` moved, and explicitly skips a status/metadata-only
    change. Fingerprinting the WHOLE spec-file blob (the original T-10135 basis) measured a strictly
    WIDER surface than the guard guards, so any write that touched the file WITHOUT touching either
    governed field silently invalidated a fresh bless.

    The measured burn (<project> task/T-0326, 2026-08-16): `spec edit --bless` at 13:30, then the
    `spec reverify` the engine's OWN anchor-drift WARN asks for — which rewrites ONLY the
    `implements_signature:` key — then land REJECTED at 14:33 naming the spec an off-path raw edit.
    Two engine recommendations, followed in the order the engine printed them, cost a full land cycle.
    The REFUSAL was correct and stays correct; what was wrong was the fingerprint's breadth.

    Both sides of the fingerprint (the bless emit + the land guard's recompute) call THIS one helper,
    so the thing signed and the thing guarded can never drift apart again. Takes the ALREADY-PARSED
    record — both call sites have one — so there is no re-parse and no unparseable-input branch."""
    import hashlib
    payload = state.dump({"body": rec.get("body"), "implements": rec.get("implements")}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cmd_spec_edit(args: argparse.Namespace, *, _require_writing_worktree, _die, _find_spec_path,
                  _read_yaml, SPEC_ABANDONED_TERMINAL, write_text_atomic, _governing_contract_for,
                  _append_event, REPO_ROOT, _run_git_cap=None,
                  _require_before_rule_change_read=None, _manifest_path=None,
                  _deliver_before_rule_change=None) -> None:
    """In-place chokepoint for editing an EXISTING active/proposed spec (T-0273) — the before-rule-change
    gate for MODIFYING a spec, the inverse of `spec new` (which gates CREATION). Resolves the spec by id,
    refuses superseded/retired (post-active frozen history), but ALLOWS a `draft` (plan-local, SPEC-0005
    §4 «draft governs NOTHING» — so a body/metadata edit is drift-safe, exactly parallel to the terminals
    carve-out; T-1164 closed E-0024's recurring no-verb-for-draft-spec-edit gap — the prior refusal
    pointed at a NON-existent «edit via plan flow» path, forcing journal-invisible hand-edits) AND the
    DELIBERATE never-active terminals withdrawn/rejected (SPEC_ABANDONED_TERMINAL, T-0627) so a
    deliberately-abandoned spec's NON-normative metadata (e.g. a `proposed_by` provenance re-attach) can
    be corrected via the verb instead of a forbidden hand-edit (a withdrawn/rejected spec governs nothing,
    so this is not a normative rule change — SPEC-0005 rule 7 in-place boundary). Performs
    an exact-string in-place replacement (mirrors the Edit
    primitive: single occurrence unless --replace-all; 0 or >1 matches die cleanly BEFORE any write),
    DELIVERS the before-rule-change contract (SPEC-0005) at the end of its output through the stage
    deliverer (T-13706 — `_deliver_before_rule_change`, injected; a caller that injects none gets the
    earlier binding-derived forward-pointer line), and
    emits `spec_edited` carrying the `governing_contract` DERIVED from the binding map (the delivery-
    observability projection, SPEC-0013 — so the gate's consumption is journal-visible, not transcript-
    only). V2 enforces by sanctioning + observing this path, NOT by hard-blocking raw Edit (a CHARTER
    non-goal — no hook-laden enforcement); an off-path raw edit shows up as a spec-file diff with NO
    spec_edited event, which is exactly what makes the bypass detectable (finding-3 no longer invisible)."""
    _require_writing_worktree()
    sid = (args.id or "").strip()
    if not sid:
        _die("spec id required (SPEC-NNNN)")
    path = _find_spec_path(sid)
    if path is None:
        _die(f"spec not found: {sid} (specs/{sid}-*.yaml)")
    rec = _read_yaml(path)
    status = rec.get("status")
    if status not in ("active", "proposed", "draft") and status not in SPEC_ABANDONED_TERMINAL:
        _die(f"`spec edit` is for active/proposed/draft specs (and the deliberate terminals "
             f"withdrawn/rejected, T-0627) only — {sid} is status={status!r}. "
             f"superseded/retired are frozen history (a post-active record is immutable).")
    if getattr(args, "bless", False):
        # T-10135: BLESS an ALREADY-MADE in-place edit of an ACTIVE spec. Derive its diff vs `main`
        # (the base the T-9730 land guard fingerprints against — worktree.py cmd_land passes
        # `merged_base = rev-parse main`), emit a DIFF-BOUND spec_edited, and let the guard clear THIS
        # spec ONLY when the final base..HEAD diff matches the recorded fingerprint. Without the
        # fingerprint bind, a stale bless event would clear a LATER raw edit — the loophole the auditor
        # flagged (spec-edit-ergonomics-audit-adhoc). Solves the rework: after a raw Edit, `spec edit`
        # (which re-performs the edit + rejects a no-op old==new) cannot ride the change; bless does.
        if args.old is not None or args.new is not None \
                or getattr(args, "from_file", None) or getattr(args, "from_stdin", False):
            _die("--bless blesses an ALREADY-MADE in-place edit — do NOT also pass "
                 "--old/--new/--from-file/--from-stdin")
        if status != "active":
            _die(f"--bless is for ACTIVE specs only ({sid} is status={status!r}); the T-9730 land guard "
                 f"governs only active specs (SPEC-0005 §4), so a non-active spec body edit needs no bless.")
        if _run_git_cap is None:
            _die("--bless unavailable: git runner not injected (host-wiring error)")
        # before-rule-change gate — the bless path ENFORCES the SPEC-0005 read receipt (the normal edit
        # path delivers the contract and refuses nothing; bless is higher-risk — it clears a guard post-hoc).
        contract = _governing_contract_for("spec-edit")
        contract_specs = contract.get("specs") or []
        if _require_before_rule_change_read is not None:
            _require_before_rule_change_read("spec edit --bless", contract_specs)
        import hashlib
        base_relpath = str(path.relative_to(REPO_ROOT))
        # T-12925: a SPEC-0120 split spec's body spans its part chain, and the land guard judges each
        # part file on its own — so the bless walks the chain (plus any part deleted since `main`) and
        # signs EVERY file whose governed content moved, one diff-bound spec_edited per file. A part
        # absent on one side reads as an empty record (an added or deleted part).
        blessed = []
        for fpath in _spec_chain_with_main_parts(path, _run_git_cap=_run_git_cap, REPO_ROOT=REPO_ROOT):
            relpath = str(fpath.relative_to(REPO_ROOT))
            base_show = _run_git_cap(["show", f"main:{relpath}"], REPO_ROOT)
            if base_show.returncode != 0 and fpath == path:
                _die(f"--bless cannot resolve {relpath} at `main` (the land-guard diff base) — a brand-new "
                     f"spec rides `spec new`, not bless ({base_show.stderr.strip()[:100]}).")
            base_blob = base_show.stdout if base_show.returncode == 0 else None
            new_blob = fpath.read_text(encoding="utf-8") if fpath.exists() else None
            try:
                base_rec = (state.load_str(base_blob) if base_blob is not None else None) or {}
                new_rec = (state.load_str(new_blob) if new_blob is not None else None) or {}
            except Exception as e:
                _die(f"--bless: cannot parse {relpath} at main/working ({str(e)[:120]})")
            body_moved = base_rec.get("body") != new_rec.get("body")
            impl_moved = base_rec.get("implements") != new_rec.get("implements")
            fields = [fld for fld, moved in (("body", body_moved), ("implements", impl_moved)) if moved]
            if fields:
                blessed.append((fpath, relpath, base_rec, new_rec, fields))
        if not blessed:
            _die("--bless: neither `body:` nor `implements:` changed vs `main` — nothing to bless "
                 "(the T-9730 land guard fires only on a body/implements diff).")
        if contract_specs:
            print(f"→ `spec edit --bless` (before-rule-change): governed by "
                  f"{', '.join(contract_specs)} (read-receipt verified this session)")
        for fpath, relpath, base_rec, new_rec, fields in blessed:
            # T-11207 (X-0951): sign the GOVERNED CONTENT (`body:` + `implements:`), NOT the whole file
            # blob — the guard's trigger surface, so a write that moves neither governed field (the
            # `spec reverify` the drift WARN asks for, which rewrites only `implements_signature:`) no
            # longer invalidates this bless. A later raw edit of body/implements still moves the digest,
            # so the T-10135 stale-bless loophole stays closed. `fingerprint` derivation is unchanged.
            base_sha = governed_content_digest(base_rec)
            new_sha = governed_content_digest(new_rec)
            fingerprint = hashlib.sha256(f"{base_sha}:{new_sha}".encode("utf-8")).hexdigest()
            # Records the SAME base fields as a normal spec_edited (path/status/trigger/governing_contract/
            # binding_source — audit-pre mode-b absorption) PLUS the bless-specific diff-bound fields.
            blessed_ev = {
                "path": relpath, "status": status,
                "replacements": 0, "trigger": "before-rule-change",
                "governing_contract": contract,
                "binding_source": "specs/*.yaml#binding (inverted via _build_binding_views)",
                "bless": True, "base_sha": base_sha, "new_sha": new_sha,
                "fingerprint": fingerprint, "fields": fields}
            if fpath != path:
                blessed_ev["part_of"] = base_relpath
            _append_event("spec_edited", sid, blessed_ev)
            print(f"spec blessed: {relpath} — diff-bound spec_edited emitted (fields: {', '.join(fields)}; "
                  f"fingerprint {fingerprint[:12]}…).")
        print("The T-9730 land guard clears THIS spec only if the final base..HEAD diff matches this "
              "fingerprint. Commit the edit (+ this event); re-run `spec edit --bless` if you edit the "
              "spec BODY or IMPLEMENTS further before land.")
        # T-11717: the AUTHOR edit above is not the only invalidator, and it was the only one named —
        # the land's OWN update-from-main can move the diff out from under a perfectly valid bless.
        print("NOT ONLY YOUR OWN EDITS invalidate this (T-11717): the LAND'S OWN update-from-main "
              "does too — if a sibling branch lands an edit to THIS spec before you land, the merge "
              "changes the final diff and this fingerprint goes stale, without you touching "
              f"anything. {SPEC_STALE_BLESS_CUE}")
        print("Safe to run now (T-11207): `spec reverify` does NOT invalidate this bless — the "
              "fingerprint covers body+implements only, so re-signing `implements_signature:` (what "
              "the anchor-drift WARN asks for) leaves it intact. Order between the two does not matter.")
        return
    # Input resolution (T-10051): old/new may come flat via --old/--new OR — for the multi-line /
    # full-section body replacements the flat CLI cannot carry — as a YAML mapping {old, new,
    # replace_all?} from a file (--from-file) or stdin (--from-stdin), mirroring `task file
    # --from-stdin`. This lets a multi-line spec-body edit RIDE the verb (+ its spec_edited emit)
    # instead of being hand-edited into the YAML off-path (the bypass this task closes). getattr
    # keeps back-compat with callers (older tests) that pass a bare id/old/new/replace_all namespace.
    from_file = getattr(args, "from_file", None)
    from_stdin = getattr(args, "from_stdin", False)
    payload_src = "--from-file" if from_file else ("--from-stdin" if from_stdin else None)
    replace_all = getattr(args, "replace_all", False)
    if from_file or from_stdin:
        if args.old is not None or args.new is not None:
            _die("--from-file/--from-stdin carry old+new themselves — do not also pass --old/--new")
        if from_file and from_stdin:
            _die("pass --from-file OR --from-stdin, not both")
        if from_file:
            import sys as _sys  # noqa: F401 (kept symmetric; stdin path below uses it)
            from pathlib import Path as _Path
            src = _Path(from_file)
            try:
                raw = src.read_text(encoding="utf-8")
            except (FileNotFoundError, PermissionError, OSError) as e:
                _die(f"--from-file {from_file!r} unreadable: {e}")
        else:
            import sys as _sys
            raw = _sys.stdin.read()
        try:
            mapping = state.load_str(raw)
        except Exception as e:
            _die(f"input is not valid YAML ({str(e)[:160]})")
        if not isinstance(mapping, dict):
            _die("input must be a YAML mapping with `old:` and `new:` keys "
                 "(mirrors `task file --from-stdin`)")
        if "old" not in mapping or "new" not in mapping:
            _die("input mapping must carry both `old:` and `new:` keys")
        old, new = mapping["old"], mapping["new"]
        if not isinstance(old, str) or not isinstance(new, str):
            _die("`old:` and `new:` must be strings (use a YAML block scalar `|` for multi-line text)")
        m_ra = mapping.get("replace_all", False)
        if not isinstance(m_ra, bool):
            _die("`replace_all:` in the input must be a boolean (true/false)")
        # OR the two carriers — a CLI --replace-all must never be silently overridden by a mapping
        # that omits it or sets it false (audit-pre YELLOW absorption, T-10051).
        replace_all = bool(m_ra) or replace_all
    else:
        if args.old is None or args.new is None:
            _die("spec edit needs an input: either --old/--new (CLI) OR --from-file/--from-stdin "
                 "(a YAML mapping {old, new, replace_all?}, for multi-line body edits)")
        old, new = args.old, args.new
    if old == new:
        _die("old and new are identical (no-op)")
    # T-12925 — a SPEC-0120 split spec is ONE body across a part chain (base, part2, …; T-12498), but
    # `_find_spec_path` resolves the BASE only, so text living in a part died old-not-found and the
    # part could only be hand-edited. Locate `old` across the chain and edit the ONE file holding it
    # (the same two tests the fallbacks below use: a raw match, or a match in the parsed body). The
    # status gate above stays on the BASE record — a part carries no status of its own.
    base_path, base_rec = path, rec
    path, rec = _spec_edit_target(base_path, base_rec, old, _read_yaml=_read_yaml, _die=_die)
    text = path.read_text(encoding="utf-8")
    n = text.count(old)
    # T-11109 — the author's own pair, kept for the AC3 integrity check further down: the fallbacks
    # below REBIND old/new to storage-form candidates, and the round-trip must be judged against
    # what the author actually asked for, not against the candidate that happened to match.
    orig_old, orig_new = old, new
    # T-13600 — which of the two readings the write below takes; printed on every successful edit.
    # Raw until a branch re-shapes the author's text so the PARSED body reads as asked.
    # `raw_reindented` marks the one raw write that is not verbatim: the T-10920 retry also serves
    # a match OUTSIDE the body (any indented block field), where no body reading exists.
    reading, raw_reindented = "raw replacement", False
    # T-13676 — the mid-line body form was found in the raw file but not proven to edit the body alone.
    mid_line_unproven = False
    if n == 0:
        # T-10321 (X-0284) — the indentation trap. The exact raw match above stays PRIMARY (every
        # currently-working call is byte-identical). Only on a miss: if `old` is a substring of the
        # PARSED body, the author composed it from the unindented body `graph query` prints, so
        # re-indent BOTH old and new to the block-scalar level and re-count. The `old in body` guard
        # is what keeps this honest — a genuinely absent `old` cannot be resurrected by re-indenting.
        indent = _body_block_indent(text)
        body = rec.get("body")
        if indent and isinstance(body, str) and old in body:
            cand_old, cand_new = _reindent(old, indent), _reindent(new, indent)
            cand_n = text.count(cand_old)
            if cand_n:
                print(f"note: `old` matched the parsed body, not the raw file — re-indented it (and "
                      f"`new`) by {len(indent)} space(s) to the `body:` block-scalar level (T-10321).")
            else:
                # T-13676 (GitHub issue #66) — the candidate above indents the FIRST line too, which
                # holds only when `old` begins where a body line begins (or after at least a block
                # indent of that line's own leading spaces). A multi-line `old` that begins MID-LINE
                # — the tail of one bullet, then the next bullet — has other text before it on disk,
                # so that candidate can never be there. Try once more with the first line as written
                # and only the continuation lines at the block level. Tried second, so every call the
                # candidate above already serves is written exactly as before.
                #   Accepted only on proof, like the flow re-encode retry further down: a first line
                # with no indent in front of it can also sit OUTSIDE the body (a top-level `key:`
                # followed by its list), so the replacement is tried on a copy and taken only when
                # the whole record reparses as before with the body alone edited as asked. `n` is
                # then the BODY's own count, so the ambiguity refusal below judges the text the
                # author addressed; what the write replaces is what the trial replaced.
                mid_old = _reindent_continuation(old, indent)
                mid_new = _reindent_continuation(new, indent)
                if text.count(mid_old):
                    trial = (text.replace(mid_old, mid_new) if replace_all
                             else text.replace(mid_old, mid_new, 1))
                    want = body.replace(old, new) if replace_all else body.replace(old, new, 1)
                    try:
                        trial_ok = state.load_str(trial) == {**state.load_str(text), "body": want}
                    except Exception:                # noqa: BLE001 — an unusable trial is no proof
                        trial_ok = False
                    if trial_ok:
                        cand_old, cand_new, cand_n = mid_old, mid_new, body.count(old)
                        print(f"note: `old` matched the parsed body, not the raw file — it starts "
                              f"mid-line, so its first line (and the first line of `new`) was kept as "
                              f"written and the lines after it were re-indented by {len(indent)} "
                              f"space(s) to the `body:` block-scalar level (T-13676).")
                    else:
                        mid_line_unproven = True
            if cand_n:
                old, new, n = cand_old, cand_new, cand_n
                reading = "edited as body text"
    if n == 0:
        # T-11109 (X-0882) — the FLOW-scalar sibling of the branch above. Same shape, same honesty
        # guard: only when `old` is in the PARSED body do we look for its stored ESCAPED form, and
        # only a candidate actually present in the raw text is accepted. `old` and `new` are encoded
        # by the SAME emitter setting (paired by index), so a match can never mix encodings.
        quote = _body_flow_quote(text)
        body = rec.get("body")
        if quote and isinstance(body, str) and old in body:
            cand_olds = _flow_encode_variants(old, quote)
            cand_news = _flow_encode_variants(new, quote)
            for cand_old, cand_new in zip(cand_olds, cand_news):
                if cand_old is None or cand_new is None:
                    continue
                cand_n = text.count(cand_old)
                if cand_n:
                    print(f"note: `old` matched the parsed body, not the raw file — the `body:` is a "
                          f"quoted flow scalar, so `old` (and `new`) were encoded to its stored "
                          f"escaped form before matching (T-11109).")
                    old, new, n = cand_old, cand_new, cand_n
                    reading = "edited as body text"
                    break
    # T-13581 — the quoted body no candidate could reach (line-WRAPPED, or escaped by a setting
    # the encoder does not reproduce). `old` is demonstrably text of the parsed body, so apply the
    # edit THERE and store the result as a literal block. Reached only where the verb used to refuse:
    # a one-line quoted body the encoder matches keeps its narrow splice above, byte for byte.
    wrapped_fix = None
    if n == 0:
        body = rec.get("body")
        if _body_flow_quote(text) and isinstance(body, str) and orig_old in body:
            hits = body.count(orig_old)
            if hits > 1 and not replace_all:
                _die(f"`old` matches {hits} times in the parsed body of {path.name} — make it unique, "
                     f"or replace every occurrence with `bin/yitc-v2 spec edit {sid} --replace-all "
                     f"--from-file <payload.yaml>`. The file is untouched.")
            want = body.replace(orig_old, orig_new)
            blocker = _literal_block_blocker(want)
            if blocker:
                _die(f"refusing to write — `old` is text of the parsed body of {path.name}, whose "
                     f"`body:` is a quoted scalar this verb could not match in its stored form, so "
                     f"the edit can only be applied by re-emitting the body as a literal `|` block — "
                     f"and the edited body cannot be one without changing a character: it carries "
                     f"{blocker} (T-13581). Take that out first with a raw replacement — copy `old` "
                     f"and `new` from `{path.name}` in its stored, escaped form and re-run "
                     f"`bin/yitc-v2 spec edit {sid} --from-file <payload.yaml>`. The file is untouched.")
            fixed = _quoted_body_as_literal_block(text, want)
            try:
                fixed_rec = state.load_str(fixed) if fixed is not None else None
                base_rec = state.load_str(text)
            except Exception:                        # noqa: BLE001 — an unusable re-emission
                fixed_rec = base_rec = None
            # Accepted only on proof: the WHOLE record must read as before with the body alone
            # replaced. Anything else falls through to the refusal below, the file untouched.
            if isinstance(fixed_rec, dict) and isinstance(base_rec, dict) \
                    and fixed_rec == {**base_rec, "body": want}:
                wrapped_fix = (fixed, fixed_rec, hits)
    if n == 0 and wrapped_fix is None:
        # T-11109 defect (2) — the diagnostic is COMPUTED from the file in hand, not a fixed string.
        # The old wording asserted a block-scalar indentation trap unconditionally, so a flow-scalar
        # body (and a plainly absent `old`) both sent the reader to debug indentation that was never
        # the cause. A correct fix with a misleading refusal still costs the next reader a pass.
        body = rec.get("body")
        in_body = isinstance(body, str) and orig_old in body
        # T-13676 — the form a block-scalar refusal names when body text cannot be edited as body text.
        raw_form_route = (f"Write the edit in the RAW form: copy `old` and every line of `new` WITH "
                          f"the file's own indentation from `{path.name}`, the first line included, "
                          f"then re-run `bin/yitc-v2 spec edit {sid} --from-file <payload.yaml>`. The "
                          f"file is untouched.")
        # T-12933 (<project> X-1581) — "not an indentation problem" is true of the SPEC side only. A
        # --from-file/--from-stdin payload is itself YAML, and its block scalar (often a heredoc) can
        # drop `old`'s own nested indentation before the verb ever sees it. So for a payload, when a
        # WHITESPACE-NORMALISED `old` matches exactly once, name the payload encoding instead.
        ws_hits = 0
        if not in_body and payload_src:
            norm_old = _ws_normalise(orig_old)
            if norm_old:
                ws_hits = _ws_normalise(body if isinstance(body, str) else text).count(norm_old)
        if ws_hits == 1:
            cause = (f"It is absent verbatim from both the raw file and the parsed body of {sid}, but "
                     f"a WHITESPACE-NORMALISED `old` matches exactly once — so the likely cause is "
                     f"the {payload_src} PAYLOAD's own YAML encoding: its block scalar (or the heredoc "
                     f"that wrote it) changed `old`'s indentation/whitespace before this verb read it. "
                     f"Indentation INSIDE the payload is significant — nest `old:`'s lines exactly as "
                     f"they sit in `{path.name}`, relative to the block scalar's own indent (T-12933).")
        elif not in_body:
            cause = (f"It is absent from BOTH the raw file and the parsed body of {sid} — so this is "
                     f"NOT an indentation or storage-style problem (text composed from the body is "
                     f"matched for you automatically). Re-check the text against `{path.name}` itself.")
        elif mid_line_unproven:
            cause = (f"It IS present in the parsed body and starts mid-line there, and its "
                     f"re-indented form is found in the raw file — but replacing that form would not "
                     f"leave `{path.name}` reading as before with the body alone edited as asked "
                     f"(for example, the same lines also sit outside the `body:` block) (T-13676). "
                     f"{raw_form_route}")
        elif _body_block_indent(text):
            cause = (f"It IS present in the parsed body, and the `body:` is a block scalar — but "
                     f"re-indenting it to that block's own level still did not match the raw file "
                     f"(the T-10321 INDENTATION trap): the on-disk indentation is not what stripping "
                     f"the block indent implies. The body form cannot be matched for this text. "
                     f"{raw_form_route}")
        elif _body_flow_quote(text):
            cause = (f"It IS present in the parsed body, which is stored as a QUOTED FLOW scalar — "
                     f"but no encoding of it matched the raw file's escaped form (T-11109). The "
                     f"scalar is most likely line-WRAPPED across physical lines, or escaped by an "
                     f"emitter setting this matcher does not reproduce. Compare against "
                     f"`{path.name}` directly, or narrow `old` to a single line.")
        else:
            cause = (f"It IS present in the parsed body, but the `body:` storage form in "
                     f"`{path.name}` is one this matcher cannot map onto — neither a block scalar "
                     f"nor a quoted flow scalar. Match against the raw file text instead.")
        _die(f"`old` not found in {path.name} (exact match required — like the Edit primitive). "
             f"{cause}")
    if n > 1 and not replace_all:
        _die(f"`old` matches {n} times in {path.name} — make it unique or pass --replace-all")
    count = n if replace_all else 1
    import yaml
    # T-11109 — the AC3 integrity guard for a QUOTED FLOW body: the flow analog of the T-10920
    # insert-side fix, and the nastier half of it. Inside a quoted scalar a verbatim `new` can break
    # the document (an embedded quote or backslash) OR — worse — still PARSE while meaning something
    # else: a real newline inside a quoted scalar FOLDS to a space, so the damage is SILENT, not a
    # refusal. So for a flow-stored body the RESULT is judged on the PARSED body against what the
    # AUTHOR asked for, and `new` is re-encoded to the scalar's stored form when the verbatim
    # insertion does not round-trip. Verification-driven, never a guess: a candidate is accepted only
    # if the reparsed body equals the expected body EXACTLY, so a wrong encoding cannot slip through.
    # T-13509 — the SAME judgement now covers a BLOCK-scalar body (the evidence this comment used to
    # wait for is GitHub issue #11): there too a raw insertion can parse and mean something
    # else, so the expected body is computed for both storage styles and the two differ only in how a
    # mismatch is repaired (re-encode `new` for a flow scalar; re-emit the block for a block scalar).
    _flow_quote = _body_flow_quote(text)
    _block_body = not _flow_quote and bool(_body_block_indent(text))
    _pre_body = rec.get("body")
    _expected_body = None
    if wrapped_fix is None and (_flow_quote or _block_body) and isinstance(_pre_body, str) \
            and orig_old in _pre_body:
        _expected_body = (_pre_body.replace(orig_old, orig_new) if replace_all
                          else _pre_body.replace(orig_old, orig_new, 1))
    _FLOW_REENCODE_NOTE = (
        "note: `new` was encoded to the `body:` flow scalar's stored escaped form — inserting it "
        "verbatim would have changed the parsed body (a newline inside a quoted scalar folds to a "
        "space; a quote or backslash re-escapes) (T-11109).")

    def _flow_reencode_retry():
        """Retry the replacement with `new` encoded into the flow scalar's stored form. Returns
        `(updated_text, record)` only when the retry round-trips to the expected body, else None."""
        if _expected_body is None or not _flow_quote:
            return None
        for cand_new in _flow_encode_variants(new, _flow_quote):
            if cand_new is None:
                continue
            cand = (text.replace(old, cand_new) if replace_all
                    else text.replace(old, cand_new, 1))
            try:
                cand_rec = state.load_str(cand)
            except yaml.YAMLError:
                continue
            if isinstance(cand_rec, dict) and cand_rec.get("body") == _expected_body:
                return cand, cand_rec
        return None

    updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    # Failure-behaviour guard (audit-post F1): a spec file IS YAML — validate the RESULT parses before
    # writing, so a replacement that corrupts the document (or mangles a frontmatter field) clean-fails
    # with the file untouched, rather than landing a broken spec the graph would then choke on.
    try:
        updated_rec = state.load_str(updated)
    except yaml.YAMLError as e:
        # T-10920 (X-0727) — the INSERT-side half of the indentation trap. The T-10321 fallback above
        # normalizes BOTH halves, but only when `old` MISSES the raw text. When a dedented one-line
        # `old` RAW-matches mid-line inside an indented body line, that fallback never fires: `old` is
        # matched at column N while a multi-line `new` written at the same (dedented) altitude has its
        # CONTINUATION lines inserted at column 0 — they terminate the block scalar and the parse above
        # fails. The author's pair is correct; only the insertion column is not. So re-indent `new`'s
        # continuation lines to the match site's own indent and retry ONCE.
        #   Symmetry, made safe by WHERE it sits: this runs only in the branch that is already about to
        # die, and is accepted only if the retry PARSES. An author whose `new` is already correctly
        # indented never reaches here (their first attempt parsed), so nobody gets double-indented —
        # an unconditional re-indent would silently corrupt exactly that case, strictly worse than the
        # loud refusal it replaced. A genuinely invalid pair fails both attempts and still dies below.
        retried = None
        if count == 1 and "\n" in new:
            # `old` is the string actually counted in `text` (possibly the re-indented candidate), so
            # index() resolves the site that was replaced.
            start = text.index(old)
            line_start = text.rfind("\n", 0, start) + 1
            prefix = text[line_start:start]
            # The match must begin AFTER indentation only: a `new` continuation line inherits the
            # LINE's indent, which is meaningful only when the whole prefix is that indent. A match
            # that starts at column 0, or mid-content, is not the reported shape.
            if prefix and not prefix.strip():
                # First line stays where the match put it; only continuations gain the indent.
                cand_new = _reindent(new, prefix)[len(prefix):]
                cand_updated = text.replace(old, cand_new, 1)
                try:
                    retried = (cand_updated, state.load_str(cand_updated))
                except yaml.YAMLError:
                    retried = None
        if retried is None:
            # T-11109 — the flow-scalar sibling of the retry above: a `new` carrying the scalar's own
            # quote (or a backslash) terminates it, and the T-10920 re-indent cannot help because the
            # match site's prefix inside `body: "…"` is not pure indentation.
            flow_retried = _flow_reencode_retry()
            if flow_retried is None:
                _die(f"refusing to write — the replacement makes {path.name} invalid YAML "
                     f"({str(e)[:160]}). Narrow --old to the intended text (the file is untouched).")
            updated, updated_rec = flow_retried
            reading = "edited as body text"
            print(_FLOW_REENCODE_NOTE)
        else:
            updated, updated_rec = retried
            if _expected_body is not None:
                reading = "edited as body text"
            else:
                raw_reindented = True
            print(f"note: `new` was inserted at a matched line indented by {len(prefix)} space(s), so "
                  f"its continuation lines were re-indented to match — inserting them verbatim would "
                  f"have broken the `body:` block scalar (T-10920). Write both halves at the file's "
                  f"own body indent to skip this.")
    # T-11109 — the SILENT half: the result parsed, but for a flow-stored body "it parsed" is not
    # "it means the same". Judge the reparsed body against the author's intent and re-encode `new`
    # when it does not match; refuse if no encoding reproduces it, rather than writing a body that
    # quietly folded a newline into a space.
    if _block_body and _expected_body is not None and isinstance(updated_rec, dict) \
            and updated_rec.get("body") != _expected_body:
        # T-13509 (GitHub issue #11) — the BLOCK-scalar sibling of the check below. `old` is
        # text of the parsed body, yet the raw write would NOT produce the body the author asked for:
        # a continuation line typed as nested lands as a sibling, or a `key: value` line at column 0
        # ends the block and becomes a new top-level key. Both parse, so the YAML guard above is blind
        # to them. The repair is gated on that mismatch — an edit whose raw write already means what
        # was asked never reaches here and stays byte-identical — and it proves its own output: the
        # shared literal-block editor (`task update`'s, T-12920) applies the edit to the PARSED body,
        # re-emits the block at its own indent, and returns a text only if it reparses to the expected
        # record EXACTLY. Anything it cannot hold (a folded `>` body, an ambiguous `old`) is refused
        # naming both readings, never written as the raw one.
        readings = _body_reading_diff(updated_rec.get("body"), _expected_body,
                                      sorted(set(updated_rec) - set(rec)))
        # T-13600 (GitHub issue #42) — the repair below assumes the author typed `new` as BODY text.
        # That is certain only when the raw write would be malformed. When every continuation line
        # of `new` already carries the block's own indent, the raw write is a well-formed body too:
        # an `old` written without its indent is found both ways, and the same input is typed by an
        # author who copied `new` from the FILE (each line at its file column) and by one who wrote
        # a nested line in the BODY. Taking it as body text put the first author's lines one block
        # indent too deep, exit 0. Nothing in the input separates the two, so the verb refuses and
        # names both forms. A `new` with any continuation line short of the block indent keeps the
        # repair: as raw text that line would leave the block, so only the body reading holds.
        block_indent = _body_block_indent(text)
        continuation = [ln for ln in orig_new.split("\n")[1:] if ln.strip()]
        if continuation and all(ln.startswith(block_indent) for ln in continuation):
            _die(f"refusing to write — `old` is found in {path.name} both as raw file text and as "
                 f"text of the parsed body, and the two readings write different bodies: {readings}. "
                 f"Every continuation line of `new` already carries the `body:` block's own "
                 f"{len(block_indent)}-space indent, so either reading may be the one you meant and "
                 f"this verb does not pick one (T-13600). Re-run `bin/yitc-v2 spec edit {sid} "
                 f"--from-file <payload.yaml>` in one of two forms. RAW form: copy `old` and every "
                 f"line of `new` WITH the file's own indentation from `{path.name}`, the first line "
                 f"included — each line lands at the column you typed. BODY form: write `old` and "
                 f"every line of `new` without the block indent, as `bin/yitc-v2 graph query {sid}` "
                 f"prints the body — with this `old`, a continuation line indented "
                 f"{len(block_indent)} or more spaces is found both ways again, so write such a "
                 f"line in the RAW form. The file is untouched.")
        fixed, fixed_n = textutil.literal_block_field_edit(
            text, state.load_str(text), orig_old, orig_new, replace_all=replace_all)
        fixed_rec = state.load_str(fixed) if fixed is not None else None
        if not isinstance(fixed_rec, dict) or fixed_rec.get("body") != _expected_body:
            _die(f"refusing to write — `old` is text of the parsed body of {path.name}, but replacing "
                 f"it in the raw file text would not write the body you asked for: {readings}. The "
                 f"edit could not be re-applied to the parsed body either (the `body:` is not a "
                 f"literal `|` block this verb can re-emit, or `old` is ambiguous there) (T-13509). "
                 f"For a raw replacement, copy `old` and every line of `new` WITH the file's own "
                 f"indentation from `{path.name}` and re-run `bin/yitc-v2 spec edit {sid} --from-file "
                 f"<payload.yaml>`. The file is untouched.")
        updated, updated_rec, count = fixed, fixed_rec, fixed_n
        reading = "edited as body text"
        print(f"note: `old` is text of the parsed body, and inserting `new` verbatim into the raw "
              f"file would have written a body that means something else — {readings}. Applied as an "
              f"edit of the parsed body instead: the `body:` block was re-emitted at its own indent so "
              f"it reads exactly as `new` says (T-13509). For a raw replacement, copy `old` and every "
              f"line of `new` WITH the file's own indentation.")
    elif _expected_body is not None and isinstance(updated_rec, dict) \
            and updated_rec.get("body") != _expected_body:
        flow_retried = _flow_reencode_retry()
        if flow_retried is None:
            _die(f"refusing to write — inside `{path.name}`'s quoted flow `body:` scalar this "
                 f"replacement does not round-trip: the reparsed body would NOT equal the body you "
                 f"asked for (a newline inside a quoted scalar folds to a space; a quote or "
                 f"backslash re-escapes), and no encoding of `new` reproduced it (T-11109). The "
                 f"file is untouched.")
        updated, updated_rec = flow_retried
        reading = "edited as body text"
        print(_FLOW_REENCODE_NOTE)
    if wrapped_fix is not None:
        # T-13581 — nothing above touched the text (`old` is absent from the raw file, so the raw
        # replace was a no-op and no repair branch ran); the verified re-emission is the write.
        updated, updated_rec, count = wrapped_fix
        reading = "edited as body text"
        print(f"note: `old` matched the parsed body, not the raw file — the `body:` is a quoted "
              f"scalar whose stored form could not be matched (most likely line-wrapped), so the "
              f"edit was applied to the parsed body and the body is now stored as a literal `|` "
              f"block. Every other field reads as before; the diff of this edit is the whole "
              f"`body:` segment (T-13581).")
    write_text_atomic(path, updated)
    is_part = path != base_path
    # T-10298 (SPEC-0151) — report-only anchor-rule WARN on the POST-edit record (reusing the record the
    # write-guard above already parsed). Reads the updated record's OWN status, not the pre-edit `status`
    # captured from disk: an edit may itself change it. Report-only — the edit has already succeeded.
    # A part (T-12925) carries no status/implements, so the rule has nothing of its own to judge there.
    if not is_part:
        _warn_anchor_rule(sid, updated_rec, verb="spec edit", specs_dir=base_path.parent)
    # governing_contract carries the SINGLE documented shape `{specs, status}` (SPEC-0025 / T-9254 —
    # `_governing_contract_for`), NOT a bare list, so EVERY floor-gated emitter is uniform. The printed
    # forward-pointer reads the `specs` list off that dict (the same auditable binding derivation — not
    # graph/index.json, which audit-post excludes — T-0219; the audit-post finding objected to both).
    contract = _governing_contract_for("spec-edit")
    contract_specs = contract.get("specs") or []
    if contract_specs and _deliver_before_rule_change is None:
        print(f"→ before `spec edit` (before-rule-change): read the governing rule(s) "
              f"{', '.join(contract_specs)} (`yitc-v2 graph query <SPEC>`; always-loaded map: "
              f"graph/floor-trigger-map.md)")
    elif not contract_specs:
        print("→ before `spec edit` (before-rule-change): read the before-rule-change rule — see the "
              "always-loaded floor trigger-map (graph/floor-trigger-map.md); no active spec bound yet")
    edited = {
        "path": str(path.relative_to(REPO_ROOT)), "status": status,
        "replacements": count, "trigger": "before-rule-change",
        "governing_contract": contract,
        "binding_source": "specs/*.yaml#binding (inverted via _build_binding_views)"}
    if is_part:
        # T-12925: `path` names the part that changed; `part_of` names the spec it continues.
        edited["part_of"] = str(base_path.relative_to(REPO_ROOT))
    _append_event("spec_edited", sid, edited)
    print(f"spec edited: {path.relative_to(REPO_ROOT)} ({count} replacement"
          f"{'s' if count != 1 else ''}) — before-rule-change governing contract: "
          f"{', '.join(contract_specs) or '(none active-bound yet — run graph build)'}")
    # T-13600 — say which reading the write took, on every edit: the corrective notes above fire
    # only when a repair ran, so a plain raw write used to be told from a body edit by their absence.
    if raw_reindented:
        print("reading: raw replacement — `old` was matched as file text; the continuation lines of "
              "`new` were indented to the matched line's own indent, nothing else was re-shaped.")
    elif reading == "raw replacement":
        print("reading: raw replacement — `old` and `new` went into the file text exactly as given.")
    else:
        print("reading: edited as body text — `old` was taken as text of the parsed body, and `new` "
              "was stored so the body reads as given.")
    print("next: `yitc-v2 graph build` to refresh rules/binding views if the body changed governing text.")
    print(f"cue: {SPEC_BODY_EDIT_CUE}")  # T-10159 (a-d single-SoT)
    # T-10727 — fire the re-pin companion cue ONLY when this edit actually CHANGED `travels:`. Both
    # records are already in hand (`rec` pre-edit from disk, `updated_rec` from the write-guard parse),
    # so the detection costs no extra read/parse and cannot fail the edit — it runs after the atomic
    # write, on the success path. Any realm change fires it: a DRAFT row desyncs exactly like an
    # active one. Report-only (SPEC-0073 §3 stays the rule's home; this only points at it).
    # T-12399 — and ONLY when the manifest it names EXISTS. The cue's entire content is a COMPANION
    # STEP in kernel-vs-self-manifest.md, a kernel-vs-self file a CONSUMER corpus does not have, so
    # there it named a nonexistent file and a test that cannot fail. Fail-SAFE by construction: no
    # injector (or a raising one) keeps the cue, so the engine path is unchanged.
    if not is_part and (rec or {}).get("travels") != (updated_rec or {}).get("travels") \
            and _manifest_has_hand_table(_manifest_path):
        print(f"cue: {SPEC_TRAVELS_REPIN_CUE} "
              f"({(rec or {}).get('travels')!r} → {(updated_rec or {}).get('travels')!r})")
    # T-13706 — the before-rule-change contract(s), LAST: the verb's own lines above stay together and
    # the contract text follows them. First time in a context epoch each is rendered as its contract
    # view and credited by an ordinary receipt; later in the same epoch it is one pointer line.
    if contract_specs and _deliver_before_rule_change is not None:
        _deliver_before_rule_change("spec-edit", contract_specs)


def cmd_spec_reverify(args: argparse.Namespace, *, _require_writing_worktree, _die,
                      _reverify_spec_signature, _append_event, REPO_ROOT,
                      _merge_base_with_main) -> None:
    """T-0506 (E-0019 kind-B): record the DURABLE freshness baseline — the content signature each
    `implements:` anchor was last VERIFIED-ACCURATE against. The author re-reads the spec against its
    anchored code, confirms the body still holds, and runs this to BLESS the current content; the
    freshness detector (`_anchor_drift_warning`) then fires `possibly-stale` only when an anchor's
    content later DIFFERS from this blessed signature — not from the non-durable git last-touch (the
    E-0019 recurrence root, where any commit touching the spec moved the baseline).

    SEPARATE from `spec edit` BY NECESSITY: re-verification frequently confirms accuracy with NO text
    change, and `spec edit` rejects a no-op (--old==--new) — so the bless cannot ride that verb. This
    writes `implements_signature: {<anchor>: <sha256>}` (one key per signed anchor; symbol anchors hash
    `_symbol_region`, file anchors hash the whole file), then emits spec_reverified. Active/proposed
    specs only (a non-normative spec governs nothing). Anchors whose file/symbol cannot be signed
    (absent/unreadable) are reported and LEFT OUT of the map (they keep the legacy last-touch path) —
    the deliberate durable successor that retires the point-in-time re-touch ritual for symbol anchors
    (E-0019 prevention filter-3 removal).

    SCOPING (T-10324). A bare `reverify` re-signs the WHOLE spec, which silently re-baselined anchors
    the caller's diff never touched (T-10300, T-10318). So: `--anchor <a>` (repeatable) re-signs ONLY
    the named anchors, leaving every other baseline byte-identical; and by default (a bare, unscoped
    reverify) the signer is armed with this branch's merge-base, so it REFUSES to re-sign an
    already-drifted anchor whose content this branch never moved.

    UNTOUCHED-ANCHOR GUARD SCOPE (T-10374, fu_dc5550c88d16). The guard exists to stop a SILENT
    whole-spec re-baseline — so it arms ONLY for a bare (unscoped) reverify. Naming `--anchor <a>` is
    the OPPOSITE of silent: an explicit anchor set IS the human/AI assertion that you re-read the spec
    against exactly those anchors, so the guard is DISARMED for a scoped call (unnamed anchors still keep
    their baseline byte-identical via the signer's merge, so scoping loses no protection). This is what
    makes the escape the refusal recommends actually reachable — before this, a `--anchor` re-sign of a
    drifted-untouched anchor re-triggered the very refusal that named it, leaving a verification-only
    task (whose diff touches no code) no non-blanket way to bless an accuracy-verified drifted anchor.
    `--include-untouched` remains the explicit opt-in that keeps the whole-spec re-sign available for the
    author who really did re-read the spec against ALL of its anchored code; it stays mutually exclusive
    with `--anchor` (whole-spec vs scoped — pick one).

    NEVER-SIGNED ANCHORS (T-13674). A signature says the code was read against the spec, so the bare
    form signs nothing it was not asked to: it re-signs the anchors that already carry a signature
    (under the guard above), leaves every anchor with NO signature unsigned, and LISTS those. The
    first baseline is given on request only: `--first-baseline` signs them all in the same guarded
    run, `--anchor <a>` signs a named one, and `--include-untouched` covers them as part of the whole
    spec. `--first-baseline` with `--anchor` is refused (two different scopes — pick one)."""
    _require_writing_worktree()
    sid = (args.id or "").strip()
    if not sid:
        _die("spec id required (SPEC-NNNN)")
    only_anchors = {a.strip() for a in (getattr(args, "anchor", None) or []) if a.strip()} or None
    if getattr(args, "include_untouched", False) and only_anchors:
        _die("`--anchor` and `--include-untouched` are contradictory: --anchor SCOPES the re-sign "
             "to what you verified, --include-untouched re-signs the whole spec. Pick one.")
    first_baseline = bool(getattr(args, "first_baseline", False))
    if first_baseline and only_anchors:
        _die("`--anchor` and `--first-baseline` are contradictory: --anchor signs exactly the anchors "
             "you name (a never-signed one included), --first-baseline signs every anchor of the spec "
             "that has no signature yet. Pick one: "
             f"`yitc-v2 spec reverify {shlex.quote(sid)} --anchor=<anchor>` or "
             f"`yitc-v2 spec reverify {shlex.quote(sid)} --first-baseline`.")
    # T-13674 — the bare form alone leaves the never-signed anchors unsigned and collects them here;
    # every explicit form (a named scope, the whole-spec opt-in, the first-baseline request) signs them.
    unsigned_left = None if (first_baseline or only_anchors is not None
                             or getattr(args, "include_untouched", False)) else []
    if getattr(args, "include_untouched", False) or only_anchors is not None:
        # Guard DISARMED. --include-untouched: the explicit whole-spec opt-in. --anchor (T-10374): the
        # named scope IS the verification assertion for exactly those anchors, so the anti-silent-
        # re-baseline guard does not apply — see the UNTOUCHED-ANCHOR GUARD SCOPE docstring above.
        base_rev = None
    else:
        base_rev = _merge_base_with_main()
        if base_rev is None:
            # Fail-closed, mirroring `_zero_ship_diff_extra_paths`'s convention: with no merge-base the
            # guard cannot PROVE an anchor was untouched, and running unguarded is the very defect this
            # flag-set exists to prevent.
            _die("cannot resolve this branch's merge-base with `main` (git failed, or no common base), "
                 "so `spec reverify` cannot tell which anchors your change actually moved.\n"
                 "  Re-run once the branch has a merge-base with `main`, or — having re-read the "
                 f"spec against its anchored code — re-sign explicitly: yitc-v2 spec reverify {sid} "
                 "--include-untouched")
    path, status, signed, unsignable, changed = _reverify_spec_signature(
        sid, only_anchors=only_anchors, base_rev=base_rev, leave_unsigned=unsigned_left)
    _append_event("spec_reverified", sid, {
        "path": str(path.relative_to(REPO_ROOT)), "status": status,
        "signed": signed, "unsignable": unsignable, "changed": changed,
        "scoped_to": sorted(only_anchors) if only_anchors else None,
        "include_untouched": bool(getattr(args, "include_untouched", False))})
    scope = f" (scoped to {len(signed)} named anchor(s); others left unchanged)" if only_anchors else ""
    # T-11762 (X-1169) — report what was COMPUTED, not the guarantee it stands for (SPEC-0165). The
    # old single line printed "N anchor(s) signed (durable freshness baseline recorded)" for BOTH a
    # real re-sign and a run that wrote nothing, so a caller read a no-op as evidence it had cured a
    # drift it never touched. The two outcomes must not read the same.
    if changed:
        print(f"spec reverified: {path.relative_to(REPO_ROOT)} — {len(changed)} of {len(signed)} "
              f"anchor(s) re-signed (baseline updated); {len(signed) - len(changed)} already "
              f"current{scope}.")
    else:
        # "no signature changed" — NOT "nothing written": the signer rewrites the file
        # unconditionally (byte-identically here), so a nothing-written claim would be a
        # guarantee this line never computed (the SPEC-0165 error this card exists to fix).
        print(f"spec reverified: {path.relative_to(REPO_ROOT)} — 0 of {len(signed)} anchor(s) "
              f"re-signed; all {len(signed)} already current, no signature changed{scope}.")
    if unsignable:
        print(f"  ⚠ {len(unsignable)} anchor(s) un-signable (absent/unreadable), left on the legacy "
              f"last-touch path: {', '.join(unsignable)}")
    if unsigned_left:
        # T-13674 — one anchor per line, so a name is never split or joined by a separator it contains.
        print(f"  {len(unsigned_left)} anchor(s) of {sid} have no signature yet and were LEFT UNSIGNED "
              f"(a signature says the code was read against the spec):")
        for a in unsigned_left:
            print(f"    {a}")
        print(f"  After reading them against the spec, give the first baseline to one with "
              f"`yitc-v2 spec reverify {shlex.quote(sid)} --anchor=<anchor>`, or to all of them with "
              f"`yitc-v2 spec reverify {shlex.quote(sid)} --first-baseline`.")
    print("next: the freshness detector now fires only when a signed anchor's content DIFFERS from "
          "this baseline — re-run `yitc-v2 spec reverify` after a future legitimate re-verification.")
