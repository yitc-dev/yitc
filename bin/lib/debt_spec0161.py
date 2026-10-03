"""debt_spec0161 — the SPEC-0161 payload-key family of `bin/yitc-v2 debt`, extracted byte-identical
from `bin/lib/debt.py` (T-12703, card C9b of plan `extract-the-13-over-budget-bin-lib-modules-into-le`).

WHAT IS IN HERE. The 18-def `spec0161_*` (8) + `_spec0161_*` (10) family frozen at baseline 02250d5
(plan §Extraction map C9b): the payload-key coverage measure, the comment/docstring-blanking code-text
reader and its structural-key scanners, the added-emit-pair fold over a diff, the unnamed-key
attribution, the recorded-span reader, the branch-added-code fold, the engine-record predicate, the
branch-unnamed verdict, the consumer fingerprint + message, and the two corpus/input resolvers. The
12 constants that ONLY this family reads (its regexes, token sets and the consumer-fingerprint prefix)
moved with it and live module-local; a body-read constant is ALSO injected by the host residue, so
rebinding the historical host name (`debt._SPEC0161_EVENT_TYPE = …`) stays honoured on every call
through the host — a module attribute is not a live alias across modules (the T-12698 seam).

NOT IN HERE. `recorded_measurement_drift` (the host caller of `spec0161_payload_key_coverage` and
`_spec0161_inputs`), `SPEC0161_COVERAGE_FLOOR` / `SPEC0161_RECORD_HEADING` (the spec-anchored, test-read
host constants) and `_SEARCH_SKIP_DIRS` (shared with the host's `_walk_for_source`) — those arrive
by injection.

SEAM (the T-9340 / T-9341 / T-11519 / T-12698 full inject-residue shape, `lessons/library-extraction.md`
§AST-freeze generator): bodies and signatures are spliced VERBATIM from the original source — never
`ast.unparse` — and every non-stdlib, non-import free name (host stayers, host globals, moved siblings
via their host residue, AND body-read moved constants) arrives as a keyword-only injected parameter,
computed with `symtable` over each function's scope SUBTREE. The host keeps a `functools.wraps`
residue under every historical name and a re-export alias for every moved constant, so every
`debt.<symbol>` reader (cli / graph / task / views / worktree + the tests) keeps resolving.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports only stdlib + the lower leaf
`lib.journal` (+ `lib.host_paths` lazily inside one body); it NEVER back-imports its host `lib.debt`.
"""
from __future__ import annotations

import ast
import bisect
import hashlib
import io
import re
import tokenize
from pathlib import Path

from lib import journal  # the ONE parsed journal fold + its request-scoped memo (CHARTER §P5)


#: A backticked token — a bare identifier (the CATALOG shape `` `task_picked` ``) or a dotted
#: `<type>.<key>` pair (the RECORD shape `` `spike_channel_grant.compose_project` ``).
_SPEC0161_DECL_TOKEN = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")

#: The markdown list bullet a declaration line opens with, and what may appear BETWEEN the tokens of
#: one declaration run: whitespace, `/`, `,` and the bare conjunction `and` — the four the record
#: actually uses to join co-declared tokens. NOTHING else does, which is what makes the run END at
#: descriptive prose (in practice at the ` — ` that opens every description).
_SPEC0161_DECL_BULLET = re.compile(r"^\s*-\s+")
_SPEC0161_DECL_SEPARATORS = " \t/,"
_SPEC0161_DECL_CONJUNCTION = "and"


def _spec0161_leading_token_run(text):
    """The LEADING run of backticked identifiers in `text` — the identifiers that appear BEFORE any
    other content, separated only by whitespace and `/`. Returns them in order.

    This is the SPAN-level half of the declaration head-parse (T-12819). `` `stage_entry` /
    `stage_exit` `` yields both; `` `worktree_created` payload keys `path` / `spike` `` yields
    `worktree_created` ALONE, because the word "payload" is not a separator and ENDS the run — so
    the payload keys a declaration line goes on to name are never mistaken for event types."""
    out, i, n = [], 0, len(text)
    while i < n:
        while i < n and text[i] in _SPEC0161_DECL_SEPARATORS:
            i += 1
        if text.startswith(_SPEC0161_DECL_CONJUNCTION, i) and out:
            # «`a` and `b`» — a conjunction JOINING co-declared tokens, admitted only BETWEEN them
            # (never as the run's opener), so it can neither start a run nor survive into prose.
            j = i + len(_SPEC0161_DECL_CONJUNCTION)
            if j < n and text[j] in _SPEC0161_DECL_SEPARATORS:
                i = j
                continue
        if i >= n:
            break
        m = _SPEC0161_DECL_TOKEN.match(text, i)
        if not m:
            break
        out.append(m.group(1))
        i = m.end()
    return out


def spec0161_declared_types(spec_text):
    """T-12819: WHICH EVENT TYPES DOES THE KERNEL RECORD STRUCTURALLY DECLARE? Pure, no I/O, no
    policy — the membership set the consumer arm of `spec0161_payload_key_coverage` measures against.

    WHY IT IS A HEAD-PARSE AND NOT A TOKEN SCAN, which is the whole reason this function exists.
    T-12798 tried to derive this set from ANY code-span/bold token in the record and was refused at
    the audit-pre ceiling (fp1:2f31e8b4fc104185): markup alone cannot tell a catalog DECLARATION from
    a formatted PROSE MENTION, so a consumer-private type merely mentioned in a backticked span would
    read as kernel-declared and stay in the denominator — the exact defect the card exists to remove.
    A first revision of THIS card's plan scanned the whole declaration LINE and was refused for the
    sibling reason (fp1:7cc38c9b5b0e6b38): a real declaration line's descriptive remainder
    (`- **`real_type`** — emitter — meaning that mentions **`foo_bar`**`) carries prose markup too.

    SO THE PARSE IS BOUNDED TWICE, at two nesting levels, by ONE scanner:
      * LINE level — after the markdown list bullet, consume a RUN of bold spans separated ONLY by
        whitespace and `/`, and STOP at the first thing that is not such a span. Everything after
        that stop — the ` — <emitter> — <meaning>` remainder and every markup token in it — is NEVER
        read.
      * SPAN level — inside each consumed bold span, take only the LEADING run of backticked
        identifiers (`_spec0161_leading_token_run`).
    A line qualifies at all only when its FIRST bold span yields a non-empty leading run, which is
    what excludes the sibling shape `- **SPEC-0025** — …` (bold, not backticked) and every ordinary
    prose line. Verified against the live record 2026-09-22: 51 declaration lines.

    Membership downstream is EXACT-TOKEN set membership — `foo` is never declared by a declaration of
    `foo_bar`. Never raises: an empty, None or unparseable text yields an empty set, which the caller
    treats as a NAMED DEGRADED state, never as licence to fall back to the unfiltered reading."""
    declared = set()
    if not spec_text:
        return declared
    for line in spec_text.splitlines():
        bullet = _SPEC0161_DECL_BULLET.match(line)
        if not bullet:
            continue
        if not line.startswith("**", bullet.end()):
            # SHAPE 2 — the RECORD's own PAYLOAD-KEY declaration line: a list item whose leading run
            # is backticked `<type>.<key>` pairs (`- `spike_channel_grant.compose_project` — …`, 27
            # such lines, verified 2026-09-22). The kernel record NAMES those keys, so their type is
            # addressed BY the record and must stay in the denominator — dropping it would silently
            # erase a pair the record already answers for (<project>, named via X-1263 -> T-12069).
            # A DOT IS REQUIRED, which is what makes this shape fail CLOSED: SPEC-0025's own
            # backticked list items are SCHEMA FIELDS (`- `ts` — …`, `- `task_id` — …`) carrying no
            # dot, so that hazard shape declares nothing here even if such text ever reached this
            # parser. Head-bounded exactly like shape 1 — the description past the run is never read.
            for token in _spec0161_leading_token_run(line[bullet.end():]):
                head, dot, key = token.partition(".")
                if dot and key and head:
                    declared.add(head)
            continue
        i, n, first = bullet.end(), len(line), True
        while i < n:
            while i < n and line[i] in _SPEC0161_DECL_SEPARATORS:
                i += 1
            if not line.startswith("**", i):
                break
            close = line.find("**", i + 2)
            if close == -1:
                break
            run = _spec0161_leading_token_run(line[i + 2:close])
            if first and not run:
                # The line's FIRST bold span declares nothing — this is not a declaration line at
                # all, so nothing on it is read (fail-closed on shape, not on content).
                break
            first = False
            declared.update(tok.partition(".")[0] for tok in run)
            i = close + 2
    return declared


def spec0161_payload_key_coverage(*, corpus, code_blob, type_keys, spec_text,
                                 borrowed_record=False, SPEC0161_RECORD_HEADING):
    """SPEC-0119 rule 28 (T-11396): THE ONE ORACLE for SPEC-0161's payload-key coverage — pure, no
    I/O, no policy. Both readers call THIS: the `tests/test_event_catalog_completeness.py` AC2 gate
    and the rule-28 debt fold below.

    Inputs are handed in rather than read, which is what makes the rule fixture-drivable (the card's
    AC1 differential probe needs a corpus sitting just above the floor and one comfortably clear,
    neither of which exists on disk) and what keeps this function honest about having no ambient
    state:
      corpus     — the concatenated `specs/*.yaml` text.
      code_blob  — the concatenated `bin/**` text (where a payload key is READ BACK).
      type_keys  — {event type -> set of data keys} folded from the journal.
      spec_text  — SPEC-0161's own YAML text.

    THE RULE. A (type, key) pair is GOVERNING when the type is mentioned somewhere in the spec
    corpus, the key is NOT mentioned anywhere in that corpus (with SPEC-0161's own recorded-run
    paragraph excised — see SPEC0161_RECORD_HEADING), and the key IS read back by some code in
    `bin/`. That last conjunct is what separates a key that MATTERS from incidental payload: code
    reads it, so its meaning is load-bearing, yet no spec says what it means. A pair is NAMED when
    SPEC-0161's recorded run mentions both halves.

    `borrowed_record` (T-12819) — THE RECORD THIS ARM IS JUDGED AGAINST IS NOT THIS REPO'S OWN.
    True exactly on the CONSUMER arm, where `spec_text` is the KERNEL's SPEC-0161 borrowed through
    `_spec0161_corpus_inputs`' `engine_specs_dir` (T-12412/T-12618) — the same one predicate
    `recorded_measurement_drift` already reports as `borrowed_record` and `spec0161_branch_unnamed`
    as `_consumer`. There a pair GOVERNS only when its event TYPE is STRUCTURALLY DECLARED by that
    record (`spec0161_declared_types`).

    WHY, measured: `governing` admits a pair on "the type is mentioned in THIS repo's corpus", so a
    CONSUMER-PRIVATE event type sat in the denominator; `named` then asks the KERNEL record, which
    can never name a type the kernel neither emits nor owns — so the pair was permanently unnamed,
    the consumer was told every session it was beneath the floor, and the T-12412 remedy routed that
    pair to the kernel as a `cross request` the kernel cannot execute (<project> 2026-09-21, X-1516).
    Unclearable debt with an impossible remedy.

    NO FALL-BACK-TO-UNFILTERED ARM — an EMPTY declared set is a NAMED DEGRADED state (audit-pre
    fp1:4dc4a7cff8d585b8). When the record is unresolved, empty or its catalog unparseable, membership
    is STILL applied: nothing governs, `coverage` is None, every candidate type is reported in
    `excluded_types`, and `declared_types_resolved` is False. That is refusing to measure rather than
    measuring wrongly, and it fails CLOSED in the direction that matters — a private type can no
    longer be counted or routed to the kernel. `coverage: None` is an ALREADY-CONTRACTED reading
    here: `recorded_measurement_drift` folds an empty denominator to count 0 precisely because "the
    probe found nothing to measure" is a different condition from a stale record, so the degraded
    state reuses that reading instead of inventing a second one.

    Returns {governing, named, unnamed, coverage, excluded_types, declared_types_resolved}.
    `coverage` is None when nothing governs — an empty denominator is not 100% coverage, and a caller
    must not read it as clean. `excluded_types` is a SORTED list of the types dropped from the
    denominator — types that WOULD have contributed at least one governing pair — and is `[]` on the
    kernel arm, whose governing/named/unnamed/coverage are byte-identical to before this parameter
    existed (`declared_types_resolved` is True there: no membership question is asked)."""
    record_start = spec_text.find(SPEC0161_RECORD_HEADING)
    record_end = spec_text.find("## Verification", record_start) if record_start != -1 else -1
    corpus_for_keys = corpus
    if record_start != -1:
        corpus_for_keys = corpus.replace(spec_text[record_start:record_end], "")
    # T-13139 — the SETS are built straight from `finditer`: `set(re.findall(...))` first materialised
    # every match (every word of the spec corpus, every `.get("...")` of `bin/`) as a list only to
    # dedupe it — the debt echo's single largest transient (~150 MB on the kernel). Same sets.
    corpus_words = {m.group(0) for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", corpus_for_keys)}

    readback = {m.group(1) for m in re.finditer(r"\.get\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']", code_blob)}
    readback |= {m.group(1) for m in re.finditer(r"\[\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*\]", code_blob)}

    declared = spec0161_declared_types(spec_text) if borrowed_record else None

    governing, excluded = [], set()
    for t, ks in type_keys.items():
        if t not in corpus:
            continue
        candidates = [(t, k) for k in sorted(ks) if k not in corpus_words and k in readback]
        if not candidates:
            continue
        if declared is not None and t not in declared:
            # A type this repo authored and the kernel record does not declare. Dropping it from the
            # DENOMINATOR is the point: it could never be named there, so counting it produced an
            # unclearable measurement and a remedy the kernel cannot execute. Reported, never silent.
            excluded.add(t)
            continue
        governing.extend(candidates)

    named = [pair for pair in governing if pair[0] in spec_text and pair[1] in spec_text]
    unnamed = [pair for pair in governing if pair not in named]
    return {
        "governing": governing,
        "named": named,
        "unnamed": unnamed,
        "coverage": (len(named) / len(governing)) if governing else None,
        "excluded_types": sorted(excluded),
        "declared_types_resolved": True if declared is None else bool(declared),
    }


# ---------------------------------------------------------------------------
# T-12232 / SPEC-0161 — WHO IS CHARGED FOR AN UNNAMED PAYLOAD KEY
#
# The oracle above answers "which governing (type, key) pairs does the record fail to name?" over the
# LIVE corpus + code + journal. That question has no branch in it, and for a land-verify gate that is
# the defect: the journal is a SHARED, GROWING input while the record moves only by a human edit, so
# the instant one branch's emitter row reaches main carrying an unnamed governing key, the gate reds
# EVERY branch's candidate leg — including every branch whose diff never went near that emitter.
#
# MEASURED, 2026-09-07, both faces of it. T-12150's `queued_premerge` reached main's journal at
# 10:45Z; from 10:50Z every land reddened on `tests/test_spec0161_payload_key_refresh.py` — 7 aborted
# lands, 4 workers halted `blocked-on-land`, ~70 minutes of wall on `queued_premerge` — until T-12225
# named the pairs at 12:01Z. Then T-12222 introduced `measurement_recorded.test_files` and reddened
# its OWN land 3x the same way. The first face is a branch charged for a key it did not introduce;
# the second is the branch that DID introduce it being told minutes in, past the venue slot, by a
# whole-suite verify — when a `git diff` at the door knew it for free.
#
# WHAT THIS ADDS IS ONE PREDICATE, NOT A SECOND ORACLE. Attribution is a pure split of the ONE
# oracle's existing `unnamed` list by a question about the branch's own diff: does the key literal
# appear on a line this branch ADDED under `bin/`? Everything below is that predicate plus the
# smallest materialiser it needs. No new store, no new event type, no new journal payload key, and
# the oracle itself is untouched — the T-11216 one-oracle discipline its docstring names.
#
# THE TWO FAIL-SAFE DIRECTIONS ARE DELIBERATELY OPPOSITE, AND THAT IS THE POINT. When the diff
# cannot be computed the attribution is UNKNOWN, and unknown must not read the same at a gate as at
# a test. The `land` preflight and the commit WARN ADMIT on unknown — a guard whose whole purpose is
# to make a refusal CHEAPER must never invent one out of a fact about the checker (the codebase's
# own words at the T-11718 arm). The land-verify TESTS fall back to today's whole-corpus bar on
# unknown — a governance gate that cannot attribute keeps its old strictness rather than going
# quiet. `attributable: False` is what lets each caller take its own direction; it is the reason the
# unknown case is a NAMED third state and not an empty `introduced` list.
# ---------------------------------------------------------------------------


#: The two triple-quote openers, kept only as the shape a docstring is written in — the tokenizer
#: below is what actually decides, so nothing here re-implements Python's own lexing.
_SPEC0161_TRIPLE_QUOTES = ('"""', "'''")

#: The token types after which a STRING token is a DOCSTRING (an expression statement whose whole
#: content is a literal) rather than a value in an expression.
_SPEC0161_DOCSTRING_PRECEDERS = frozenset(
    {tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT})


def _spec0161_blank(grid, start, end):
    """Blank the half-open region `start`..`end` of `grid` (a list of per-line char lists), keeping
    every line and every column position — so line numbers survive the removal exactly."""
    (r0, c0), (r1, c1) = start, end
    for r in range(r0 - 1, min(r1, len(grid))):
        row = grid[r]
        lo = c0 if r == r0 - 1 else 0
        hi = c1 if r == r1 - 1 else len(row)
        for c in range(lo, min(hi, len(row))):
            row[c] = " "


#: A string literal whose CONTENT is exactly one identifier — the only shape a payload-key literal
#: can wear. Any other literal (an expression, a sentence, a path, a template) is blanked with the
#: comments and docstrings, so a quoted code example can never be read as a structural occurrence.
_SPEC0161_STRING_LITERAL = re.compile(
    r"\A[A-Za-z]*(\"\"\"|\'\'\'|\"|\')(?P<body>.*)\1\Z", re.DOTALL)
_SPEC0161_IDENTIFIER = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


def _spec0161_is_identifier_literal(token_text, *, _SPEC0161_IDENTIFIER, _SPEC0161_STRING_LITERAL):
    """True iff `token_text` (a STRING token, prefixes and quotes included) holds exactly one
    identifier — see `spec0161_code_text`\'s finding-B3 paragraph. PURE."""
    m = _SPEC0161_STRING_LITERAL.match(token_text or "")
    return bool(m) and bool(_SPEC0161_IDENTIFIER.match(m.group("body")))


def spec0161_code_text(text, lines=None, *, _SPEC0161_DOCSTRING_PRECEDERS, _spec0161_blank, _spec0161_is_identifier_literal):
    """The CODE of a POST-IMAGE FILE — comments and docstrings blanked out — restricted to `lines`
    (1-based line numbers; None = the whole file). PURE.

    WHY THE POST-IMAGE AND NOT THE ADDED-LINE BLOB (audit-post pass-3 residual B2). The scan below
    charges a branch for a key that appears in a structural position, and a QUOTED CODE EXAMPLE
    inside a comment or a docstring wears exactly those forms. Deciding comment/docstring status
    from the diff's `+` lines alone CANNOT WORK: a line added INSIDE a PRE-EXISTING docstring
    carries no opening delimiter, so the blob has no way to see the docstring enclosing it and
    scans prose as code — the exact edited-docstring shape the original finding named. A blob is
    not a parseable unit, and no amount of hunk-bounding makes it one.

    So the status is derived from the FILE, which IS parseable: the post-image is tokenised by
    Python's own lexer, COMMENT tokens and DOCSTRING tokens are blanked IN PLACE (spaces, so every
    line and column keeps its position), and only then are the added line numbers selected. An
    added line inside an untouched docstring is blank; an added line of real code is intact; and the
    question "is this position code?" is answered by the language, not by a heuristic.

    A STRING LITERAL THAT IS NOT A BARE IDENTIFIER IS BLANKED TOO (audit-post episode-2 finding B3).
    A docstring is not the only place a quoted code EXAMPLE hides: `EXAMPLE = \'row.get("k")\'` is a
    plain string token in real code, and the structural regexes below, being lexical, read straight
    through the outer quotes and charge a branch that added no emitter and no readback. The
    tokenizer already tells us where every string literal is, so the fix is to keep only the string
    literals that could BE a payload key — ones whose whole content is a single identifier, exactly
    the shape `.get("k")` / `["k"]` / `"k":` require — and blank every other one. A string holding an
    expression, a sentence, a path or a format template can then never contribute a key.

    THIS FUNCTION ONLY BLANKS AND SELECTS; the structural matching is `spec0161_structural_keys`,
    which runs over the WHOLE blanked file and filters by the key literal\'s own line (episode-2
    findings B4 / B4a). A `lines` selection here is still exact for reading back what a branch
    added, but it must not be what a structural form is matched against — a wrapped readback does
    not fit inside one physical line.

    FAILS OPEN ON AN UNPARSEABLE POST-IMAGE — returns "", charging nothing. Inventing a charge at a
    REFUSING gate out of a fact about the checker is the expensive error (the codebase\'s own words
    at the T-11718 arm), and a file that does not tokenise is a fact about the checker\'s reach."""
    src = text or ""
    grid = [list(row) for row in src.splitlines()]
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return ""
    prev = tokenize.NEWLINE
    for tok in toks:
        if tok.type == tokenize.COMMENT:
            _spec0161_blank(grid, tok.start, tok.end)
            continue                                    # a comment does not move `prev`
        if tok.type == tokenize.STRING:
            if prev in _SPEC0161_DOCSTRING_PRECEDERS or not _spec0161_is_identifier_literal(
                    tok.string):
                _spec0161_blank(grid, tok.start, tok.end)
        if tok.type != tokenize.NL:
            prev = tok.type
    if lines is None:
        return "\n".join("".join(row) for row in grid)
    wanted = {int(n) for n in lines}
    return "\n".join("".join(grid[n - 1]) for n in sorted(wanted) if 1 <= n <= len(grid))


#: The three STRUCTURAL forms, as ONE alternation over the WHOLE blanked post-image, each capturing
#: the key in the group named `key` — so a match carries the OFFSET of the key LITERAL itself and
#: `spec0161_structural_keys` can ask which LINE that literal sits on. The first two are VERBATIM the
#: readback regexes `spec0161_payload_key_coverage` derives its `readback` conjunct from; the third is
#: the mapping-key literal an emitter's payload dict writes.
_SPEC0161_STRUCTURAL = re.compile(
    r"\.get\(\s*[\"'](?P<key>[A-Za-z_][A-Za-z0-9_]*)[\"']"
    r"|\[\s*[\"'](?P<key2>[A-Za-z_][A-Za-z0-9_]*)[\"']\s*\]"
    r"|[\"'](?P<key3>[A-Za-z_][A-Za-z0-9_]*)[\"']\s*:")


def spec0161_structural_keys(text, lines=None, *, spec0161_structural_key_sites):
    """The payload keys a branch INTRODUCES in one post-image file: the keys appearing in a
    STRUCTURAL position whose KEY LITERAL sits on one of `lines` (1-based; None = the whole file).
    PURE.

    A VIEW OVER `spec0161_structural_key_sites` (T-12411), which answers the same question one
    notch finer (WHERE each key sits). Keeping ONE matcher is what lets the three readers that need
    only the key set, the message that needs the charging SITE, and the merge-base side of the
    attribution all be judged by the same predicate — a second scanner could disagree with this one
    about what a structural position is, and at a REFUSING gate that disagreement is a false charge.

    THE MATCH IS RUN OVER THE WHOLE BLANKED FILE AND FILTERED BY THE LITERAL'S OWN LINE — which is
    what makes it exact in BOTH directions, the two ways a line-based selection gets this wrong:

      * SELECTING THE ADDED LINES FIRST severs a wrapped readback (`row.get(` on one line, `"k")` on
        the next): the key literal loses the `.get(` that makes it structural and the branch that
        added it reads as INHERITED — the preflight then admits an introduced key (episode-2
        finding B4).
      * WIDENING TO THE ENCLOSING LOGICAL LINE fixes that but over-reaches the other way: a branch
        adding an unrelated entry to a multi-line dict is charged for every PRE-EXISTING key in the
        same statement, a false charge at a REFUSING gate (episode-2 finding B4a).

    Matching over the whole file keeps every structural form intact, and requiring the KEY LITERAL —
    not the statement, not the `.get(` — to be on an added line asks exactly the question the rule
    asks: did THIS branch write this key here? A wrapped readback puts the literal on the added line;
    an untouched neighbour in the same dict does not."""
    return set(spec0161_structural_key_sites(text, lines))


def spec0161_structural_key_sites(text, lines=None, *, _SPEC0161_STRUCTURAL, spec0161_code_text):
    """T-12411: `spec0161_structural_keys` with the LINE each key was found on kept — returns
    `{key: [1-based line numbers, ascending]}` over the same blanked post-image, by the same match,
    with the same `lines` filter. PURE.

    THE LINE IS NOT DECORATION — it is what makes a charge CHECKABLE BY THE CHARGED PARTY. The
    refusal this feeds says "your diff introduces these keys"; without a `<path>:<line>` the operator
    must re-derive the scan by hand to find out WHERE, which at a gate that fires seconds before a
    venue slot is the expensive minutes the whole seam exists to save. The path is added by the
    caller that knows it (`_spec0161_branch_added_code`); this function owns the line.

    ONE SCANNER, TWO READERS: `spec0161_structural_keys` is `set()` of this, so the key set a gate
    charges and the sites a message prints can never come from two different notions of "structural".
    """
    scanned = spec0161_code_text(text, None)
    if not scanned:
        return {}
    wanted = None if lines is None else {int(n) for n in lines}
    starts = []                                         # cumulative offset of each line's start
    off = 0
    for row in scanned.split("\n"):
        starts.append(off)
        off += len(row) + 1
    sites = {}
    for m in _SPEC0161_STRUCTURAL.finditer(scanned):
        for group in ("key", "key2", "key3"):
            if m.group(group) is None:
                continue
            lineno = bisect.bisect_right(starts, m.start(group))
            if wanted is not None and lineno not in wanted:
                continue
            sites.setdefault(m.group(group), set()).add(lineno)
    return {k: sorted(v) for k, v in sites.items()}


#: The shape an EVENT TYPE literal wears — the same lowercase-identifier grammar the journal's own
#: types are written in (`_SPEC0161_RECORD_ROW`'s left-hand side). A `Call` whose first positional
#: argument is a string constant of this shape is what `spec0161_added_emit_pairs` reads as an emit.
_SPEC0161_EVENT_TYPE = re.compile(r"\A[a-z][a-z0-9_]*\Z")


def _spec0161_payload_dict_keys(node, lines, *, _spec0161_payload_dict_keys):
    """The TOP-LEVEL string keys of one payload dict LITERAL whose key literal sits on an added line.
    PURE. `lines` is a set of 1-based added line numbers, or None for the whole file.

    TOP-LEVEL ONLY, and `**{...}` unpacked AT that top level counts as top level — because that is
    exactly what the journal's own candidate set is (`data.keys()`), so this derivation and the
    oracle agree BY CONSTRUCTION about what a payload key IS. A dict nested as a VALUE inside the
    payload contributes nothing: its keys could no more appear in `type_keys` than they can here."""
    keys = set()
    if not isinstance(node, ast.Dict):
        return keys
    for k, v in zip(node.keys, node.values):
        if k is None:                                   # `**expr` at the payload's top level
            if isinstance(v, ast.Dict):
                keys |= _spec0161_payload_dict_keys(v, lines)
            continue
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            continue
        if lines is not None and getattr(k, "lineno", None) not in lines:
            continue
        keys.add(k.value)
    return keys


def spec0161_added_emit_pairs(added_files, *, _SPEC0161_EVENT_TYPE, _spec0161_payload_dict_keys):
    """T-12423: the {event_type -> set(keys)} map read STRUCTURALLY FROM THIS BRANCH'S ADDED CODE —
    the SECOND candidate source for the ONE oracle, which otherwise learns a (type, key) pair only
    from a row that ALREADY EXISTS in the journal. PURE; never raises.

    WHY A SECOND SOURCE AND NOT A SECOND ORACLE (the T-11379 precedent — one rule, second
    quantifier). `spec0161_payload_key_coverage` walks `type_keys`, which `_spec0161_inputs` folds
    FROM THE JOURNAL, so a pair is not a CANDIDATE until a row carrying the key exists. A branch that
    ADDS THE EMITTER carries no such row — the first one is written at RUNTIME, after the land — so
    at its own land the preflight had nothing to see and ADMITTED it. MEASURED, 2026-09-11: T-12373's
    land brought `bg_dispatch_launched.land_regime` unnamed and was not refused; once a later dispatch
    emitted the first row ON MAIN, the census tripwire reddened EVERY candidate tree for 2h10m until
    the key was named by hand. The refusal that DID fire on <project> fired on a key whose rows already
    existed — i.e. the gate only ever caught the case it was not built for.

    `added_files` — the same contract `_spec0161_branch_added_code` returns and
    `spec0161_attribute_unnamed` takes: a sequence of `(post_image_text, added_line_numbers_or_None)`
    pairs. `{}` on None, so a caller with an unknowable diff contributes no candidates (the
    fail-OPEN direction, which is the only safe one at a REFUSING gate).

    THE STRUCTURAL BOUNDARY, stated exactly (audit-pre finding 2). An EMIT CALL is a `Call` whose
    FIRST POSITIONAL argument is a string constant of event-type shape (`[a-z][a-z0-9_]*`). Its
    PAYLOAD KEYS are the TOP-LEVEL string keys of a dict LITERAL that is a DIRECT argument of that
    call — a positional argument or a keyword value — plus the top-level keys of any `**{...}` dict
    unpacked at that same top level (`_spec0161_payload_dict_keys`). A dict nested as a VALUE inside
    the payload is NOT a key source, and neither is a dict passed to some INNER call. That boundary
    is not a taste: the journal's candidate set is `data.keys()`, which is top-level only.

    A KEY COUNTS ONLY WHEN ITS LITERAL SITS ON A LINE THIS BRANCH ADDED — the same question arm (i)
    of the attribution asks, so a branch adding one entry to a pre-existing payload dict is charged
    for that entry alone and not for its untouched neighbours. The TYPE literal is deliberately NOT
    required to be on an added line: adding a new key to an EXISTING emit call is precisely the shape
    that reddened main, and requiring the type too would exempt it.

    NAMED BOUND, honest and fail-OPEN: an emitter whose payload dict is built in a VARIABLE and
    passed by name is not a literal at the call site and is not seen — the same residue the journal
    leg already documents. Unparseable text (a shell script, a file mid-edit) contributes nothing and
    never raises, because a file that does not parse is a fact about the CHECKER, and inventing a
    charge at a refusing gate out of one is the expensive error (the T-11718 arm's own words)."""
    pairs = {}
    for text, lines in (added_files or ()):
        try:
            tree = ast.parse(text or "")
        except (SyntaxError, ValueError, RecursionError):
            continue                                    # not Python, or mid-edit — charges nothing
        wanted = None if lines is None else {int(n) for n in lines}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)
                    and _SPEC0161_EVENT_TYPE.match(first.value)):
                continue
            keys = set()
            for arg in list(node.args[1:]) + [kw.value for kw in node.keywords if kw.arg]:
                keys |= _spec0161_payload_dict_keys(arg, wanted)
            if keys:
                pairs.setdefault(first.value, set()).update(keys)
    return pairs


def spec0161_attribute_unnamed(unnamed, *, added_files, unnamed_by_branch=None,
                               base_structural_keys=None, spec0161_structural_keys):
    """T-12232: split the ONE oracle's `unnamed` pairs into the ones THIS BRANCH INTRODUCED and the
    ones it INHERITED from main. PURE — no I/O, no policy; the caller supplies both facts.

      unnamed           — `spec0161_payload_key_coverage(...)["unnamed"]`, a list of (type, key) pairs.
      added_files       — the contract `_spec0161_branch_added_code` returns: a sequence of
                          `(post_image_text, added_line_numbers)` pairs, one per touched `bin/`
                          file, where `added_line_numbers` is the set of 1-based line numbers this
                          branch ADDED (None = the whole file is new). None — not an empty
                          sequence — when the diff could not be determined.
      unnamed_by_branch — the SET of keys this branch removed from SPEC-0161's record span (may be
                          empty; ignored when `added_files` is None).
      base_structural_keys — T-12411: the SET of keys that ALREADY had a structural occurrence under
                          `bin/` AT THE MERGE-BASE. Subtracted from arm (i) below. None/absent = the
                          pre-T-12411 reading (nothing subtracted), which is what keeps this
                          function independently exercisable without a git repo.

    FOURTH MEMBER OF THE DIFF-AWARE FAMILY (`graph.seed_growth_warnings`,
    `graph.new_test_file_warnings`, `graph.uncatalogued_type_findings`) — same question, one level
    down: of a repo-wide condition, which part is THIS BRANCH answerable for? The three siblings
    answer it by a BASELINE-vs-CURRENT set comparison whose two sides the host resolves against
    `git merge-base HEAD main`. The un-naming arm below IS that shape exactly. The code arm is not,
    for a measured reason: this condition's base side would be the whole `bin/` tree AND the whole
    segmented journal re-folded at the merge-base — the two expensive inputs of `_spec0161_inputs` —
    and paying that twice inside a refusal whose entire promise is "seconds, before the venue slot"
    would spend the saving it exists to make.

    TWO WAYS A BRANCH BECOMES ANSWERABLE, and a diff-scoped derivation must carry BOTH or it exempts
    half the class silently:
      (i)  it ADDS the key TO CODE — the key appears on an added `bin/` line in one of the STRUCTURAL
           forms below, AND NO STRUCTURAL OCCURRENCE OF IT EXISTED UNDER `bin/` AT THE MERGE-BASE
           (T-12411, `base_structural_keys`);
      (ii) it UN-NAMES the key — the key was in SPEC-0161's record span at the merge-base and is not
           in it now (`unnamed_by_branch`). Editing a name out of the record makes the pair
           govern-and-unnamed exactly as surely as adding the emitter does.

    ARM (i) IS ALSO BASELINE-VS-CURRENT NOW (T-12411, <project> X-1343 / T-0500). "The key is on a
    line this branch added" is not by itself "this branch INTRODUCED the key": a branch that adds a
    SECOND readback of a key already read back elsewhere under `bin/` on main added no new governing
    key at all, and charging it re-reads a key that governed before it existed. Measured: T-0500's
    land was REFUSED for `spike_channel_grant.compose_project` because it added
    `meta.get("compose_project")` in `bin/tests/spike_live_support.py`, while
    `bin/spike-lib.sh:46` had carried `m.get("compose_project")` at the merge-base all along. So arm
    (i) now subtracts `base_structural_keys` and the docstring's old concession — that the code arm
    could not afford the family's baseline-vs-current shape — is RETIRED: the base side is not the
    whole `bin/` tree, it is TARGETED at the handful of keys THIS branch added, which is cheap (see
    `_spec0161_branch_added_code`). Arm (ii) is deliberately NOT filtered by it: un-naming a recorded
    key is a charge whatever the code says, and a key un-named from the record is by definition one
    whose readback already existed.

    ARM (i) IS STRUCTURAL, NOT A WORD SCAN, and that distinction is load-bearing (audit-post finding
    1). A bare word scan charges a branch for MENTIONING the key — in a comment, a docstring, a
    refusal message, a test name — which is a false charge at a REFUSING gate, the one place a false
    positive is most expensive. So a key counts only where it appears in a position that actually
    makes it a payload key:
      * `.get("k")` and `["k"]` — VERBATIM the two regexes `spec0161_payload_key_coverage` derives
        its `readback` conjunct from. Not a lookalike: the same expressions, so "the branch added the
        readback that makes this key govern" is decided by the oracle's own notion of a readback.
      * `"k":` — the key as a MAPPING KEY LITERAL, which is how an emitter's payload dict names it.
        Needed because a branch may add the emitting dict while the readback already existed on main;
        without it that branch is charged nothing.
    Both forms require the key QUOTED, so prose can never trip them.

    ATTRIBUTION IS BY KEY, NOT BY (type, key). A diff that adds the key to ANY emitter under `bin/`
    owes the record its name, whichever type carries it — the record names keys. Requiring the TYPE
    in the diff too would let a branch add a new key to an EXISTING event type and be charged nothing.

    THE NAMED RESIDUE (the honest bound this shape inherits from its family). A pair that becomes
    govern-and-unnamed without this branch adding a structural occurrence or removing a recorded
    name — a row appended from the main checkout with no worktree (D-0049), or a key that becomes
    governing because an unrelated spec edit removed its only other corpus mention — reads as
    INHERITED on every branch, so no branch is failed for it. That is deliberate and is the same
    trade `graph.uncatalogued_type_findings` documents: a gate that cannot name a responsible party
    can only punish bystanders. It is not dropped — the SPEC-0119 rule-28 debt echo reads the raw
    corpus-wide coverage and surfaces it report-only.

    Returns {"introduced": [...], "inherited": [...], "attributable": bool}. `added_files=None`
    returns EVERY pair as inherited with `attributable: False` — an honest "cannot tell", NOT an
    empty `introduced` list that a caller could mistake for "this branch introduced nothing"."""
    pairs = [tuple(p) for p in (unnamed or [])]
    if added_files is None:
        return {"introduced": [], "inherited": pairs, "attributable": False}
    # THE POST-IMAGE IS MATCHED WHOLE AND FILTERED BY THE KEY LITERAL'S OWN LINE (residual B2, then
    # episode-2 findings B3/B4/B4a). Comment, docstring and quoted-example positions are blanked
    # from the parseable FILE; the structural forms are then matched across the whole of it, and a
    # key counts only when the LITERAL itself sits on a line this branch added — neither severed by
    # an added-lines-first selection nor over-reaching to a statement's untouched neighbours. See
    # `spec0161_structural_keys`.
    keys = set()
    for text, lines in added_files:
        keys |= spec0161_structural_keys(text, lines)
    # T-12411: ARM (i) MINUS the merge-base. A key whose structural readback pre-exists under `bin/`
    # on main was not introduced HERE, whichever line of this diff it also appears on. The
    # subtraction is applied to the CODE arm only — arm (ii) is unioned AFTER it, so an un-naming is
    # never cancelled by the readback whose existence is precisely what makes the un-naming matter.
    keys -= set(base_structural_keys or ())
    keys |= set(unnamed_by_branch or ())
    introduced = [p for p in pairs if p[1] in keys]
    inherited = [p for p in pairs if p[1] not in keys]
    # T-13295 — `keys` (K|U) rides out beside the verdict (additive): `introduced` is exactly the
    # pairs whose key is in it, so an EMPTY set proves no journal pair can be introduced at all.
    return {"introduced": introduced, "inherited": inherited, "attributable": True, "keys": keys}


#: A RECORD ROW, by the record's own grammar: a backtick-quoted `<event_type>.<key>[|<key>...]`.
#: Anchored `\A`/`\Z` so it matches a WHOLE token, never a fragment of a longer backticked run.
_SPEC0161_RECORD_ROW = re.compile(
    r"\A`([a-z_][a-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*(?:\|[A-Za-z_][A-Za-z0-9_]*)*)`\Z")

#: Any backticked token in the span, WITH the text around it, so a candidate row can be judged by
#: its NEIGHBOURS — which is what separates an enumerated row from a prose mention (see below).
_SPEC0161_BACKTICKED = re.compile(r"`[^`\n]+`")

#: The separator the recorded set is written with. A row is a member of that enumeration iff the
#: separator sits immediately beside it.
_SPEC0161_ROW_SEPARATOR = "\u00b7"

#: What may precede a row: the separator, or the COLON that introduces the enumeration. The colon is
#: what lets a record holding a SINGLE row still read as one — without it a one-row set, having no
#: separator anywhere, would parse as zero rows and silently stop detecting un-namings.
_SPEC0161_ENUMERATION_DELIMITERS = (_SPEC0161_ROW_SEPARATOR, ":")


def _spec0161_record_span_keys(spec_text, *, SPEC0161_RECORD_HEADING, _SPEC0161_BACKTICKED, _SPEC0161_ENUMERATION_DELIMITERS, _SPEC0161_RECORD_ROW, _SPEC0161_ROW_SEPARATOR):
    """The keys NAMED BY THE RECORD ROWS inside SPEC-0161's record span — parsed by the record's own
    grammar, NOT by a word scan of the span (audit-post pass-2 finding B1).

    The span is located from the SAME shared `SPEC0161_RECORD_HEADING` constant the oracle uses, so
    this and the oracle cannot disagree about where the record starts. Empty set when it is absent.

    WHY A GRAMMAR AND NOT A WORD SCAN. The only caller is the un-naming arm of
    `_spec0161_branch_added_code`, which charges a branch for a key that was in the span at the
    merge-base and is not in it now. Under a word scan that difference is taken over EVERY
    identifier in the span, prose included — so deleting a key-shaped word from an explanatory
    sentence, with every record row untouched, charges the branch and REFUSES its land. A false
    positive at a refusing gate is the expensive direction, which is why the baseline must read the
    ROWS and nothing else.

    THE ROW GRAMMAR, AND HOW A ROW IS TOLD FROM A PROSE MENTION. A row is a backticked
    `type.key|key` token that is a MEMBER OF THE `\u00b7`-SEPARATED ENUMERATION — i.e. the separator sits
    immediately beside it, before or after (whitespace-skipping). That neighbour test is what the
    shape of the record affords: the recorded set is written as one `\u00b7`-separated run, while prose
    names a pair in a sentence (`nightly_run_completed.quiet_lane` (T-12097) and \u2026) and names module
    attributes in the same backticks (`events.segment_paths`), neither of which touches a separator.
    Both of those read as rows under a bare dotted-token scan; neither does here.

    Returns the KEY names only (the right-hand side, `|`-split), because that is what the caller
    compares against — the oracle's pairs are matched by key, per `spec0161_attribute_unnamed`'s
    attribution-is-by-key rule."""
    if not spec_text:
        return set()
    start = spec_text.find(SPEC0161_RECORD_HEADING)
    if start == -1:
        return set()
    end = spec_text.find("## Verification", start)
    span = spec_text[start:(end if end != -1 else len(spec_text))]

    keys = set()
    for m in _SPEC0161_BACKTICKED.finditer(span):
        row = _SPEC0161_RECORD_ROW.match(m.group(0))
        if row is None:
            continue
        before = span[:m.start()].rstrip()
        after = span[m.end():].lstrip()
        if not (before.endswith(_SPEC0161_ENUMERATION_DELIMITERS)
                or after.startswith(_SPEC0161_ROW_SEPARATOR)):
            continue                                    # a prose mention, not an enumerated row
        keys.update(row.group(2).split("|"))
    return keys


#: SPEC-0161's record file, by name, so the BASE side of arm (ii) can be located in the base tree
#: rather than assumed to sit at the CURRENT path (finding B5 — a rename or a deletion moves it).
_SPEC0161_SPEC_NAME = re.compile(r"(?:\A|/)SPEC-0161-[^/]*\.yaml\Z")


def _spec0161_base_structural_keys(_git, base_sha, branch_keys, repo_root, *, spec0161_structural_keys):
    """T-12411: of `branch_keys` (the keys THIS branch added in a structural position under `bin/`),
    the ones that ALREADY had a structural occurrence under `bin/` AT `base_sha`. Returns a set, or
    None when a git call FAULTED (the unknowable third state its caller propagates).

    TARGETED, WHICH IS THE WHOLE POINT. The cost objection that kept arm (i) off the family's
    baseline-vs-current shape priced a base side that re-read the whole `bin/` tree. This asks a
    strictly smaller question — "did any of THESE FEW key literals appear under `bin/` at the base?"
    — so one `git grep -l -F` yields a handful of candidate paths, and only those are read at the
    base rev. On the common case (a genuinely new key) the grep matches nothing and this returns
    after ONE git call.

    THE GREP IS A FILE FILTER, NEVER THE VERDICT. `-F` fixed strings (`"k"` and `'k'`) are used
    deliberately: no regex dialect of git's is relied on, and being over-broad here is harmless
    because every candidate is then judged by the SAME pure `spec0161_structural_keys` the branch
    side is judged by — tokenizer-blanked, so a comment, a docstring or a non-identifier literal at
    the base exempts nothing. Being over-broad in the FILTER only costs a `git show`; being
    over-broad in the VERDICT would silently exempt a branch, which is why the filter does not get
    to decide.

    rc 1 IS "NO MATCH", AN ANSWER (audit-pre finding 1): the empty set, so the keys stay charged.
    rc > 1 — and any failing `git show` — is a FAULT: None. Reading a fault as an empty base set
    would restore the exact over-charge this function exists to remove."""
    if not branch_keys:
        return set()
    args = []
    for k in sorted(branch_keys):
        args += ["-e", f'"{k}"', "-e", f"'{k}'"]
    grep = _git("grep", "-l", "-F", *args, base_sha, "--", "bin")
    if grep is None or grep.returncode > 1:
        return None
    if grep.returncode == 1:
        return set()                                    # no candidate file — nothing pre-existed
    base_keys = set()
    for row in grep.stdout.splitlines():
        row = row.strip()
        if not row:
            continue
        # `git grep -l <rev>` prints `<rev>:<path>`; the rev is a full sha here, so one split on the
        # FIRST colon is exact (a path may itself contain a colon, the rev may not).
        rel = row.split(":", 1)[1] if row.startswith(f"{base_sha}:") else row
        shown = _git("show", f"{base_sha}:{rel}")
        if shown is None or shown.returncode != 0:
            return None
        base_keys |= spec0161_structural_keys(shown.stdout) & branch_keys
    return base_keys


def _spec0161_branch_added_code(repo_root, *, consumer=False, _SPEC0161_SPEC_NAME, _spec0161_base_structural_keys, _spec0161_record_span_keys, spec0161_structural_key_sites):
    """T-12232: the two diff facts the attribution needs, or None when they are unknowable.

    `consumer` (T-12412) — this root does not own the SPEC-0161 record (see
    `_spec0161_engine_record_specs`). ARM (ii) IS SKIPPED, and the skip is the correct answer rather
    than a shortcut: arm (ii) asks "did THIS branch REMOVE names from the record?", and a consumer
    branch cannot touch the kernel record at all (it is query-only under `-C`, and a consumer write
    into the engine corpus is refused by `cli._guard_consumer_engine_write`, SPEC-0078). Asking it
    anyway means running `git show <consumer-base>:specs/SPEC-0161…` against a tree that has never
    contained that file — putting a question only the kernel tree can answer to the consumer tree.
    ARM (i) is UNCHANGED for a consumer: keys added on `bin/` lines this branch added are its own
    genuine charge, and that is exactly the list the downgraded WARN reports.

    The impure sibling of `_spec0161_inputs`, written to its rules — best-effort, never raises, so a
    git fault degrades the seam rather than breaking a `land` or a `task commit`.

    ARM (i) RETURNS PER-FILE ADDED LINE NUMBERS, NOT A BLOB (audit-post pass-3 residual B2). The
    diff is read for WHICH LINES this branch added in WHICH file; the text handed on is the file's
    POST-IMAGE. That is what lets `spec0161_code_text` decide comment/docstring status from a
    parseable unit — a line added inside a PRE-EXISTING docstring has no opening delimiter of its
    own, so no blob-level reading can ever tell it from code.

    ARM (i), ONE DIFF COMMAND SERVING BOTH CALLERS. base = `git merge-base HEAD main`; the diff is
    `git diff <base> -- bin`, which compares the merge-base to the WORKING TREE. That covers the
    branch's committed emitters AND its uncommitted ones in a single call, which is what lets the
    pre-commit WARN (`task commit`, working tree dirty) and the post-commit `land` preflight (working
    tree clean) share this one materialiser instead of each growing its own range logic. An untracked
    NEW file under `bin/` is added separately — `git diff` cannot show a file git has never seen, so
    a brand-new emitter module would otherwise be attributed to nobody.

    ARM (ii) IS A BASELINE COMPARISON, NOT A DELETED-LINE SCAN (audit-post finding 1). Scanning every
    removed `specs/` line charges a branch for any spec deletion that happens to contain the key
    literal — a false charge at a REFUSING gate. Instead the RECORD SPAN is read at the merge-base
    (`git show <base>:<spec>`) and compared against the span on disk NOW: a key is un-named by this
    branch iff it was in the base span and is not in the current one. Exact, and cheap — one small
    file at one rev, which is why this arm can afford the family's baseline-vs-current shape while
    arm (i) cannot.

    ARM (i) IS BASELINE-VS-CURRENT AS OF T-12411 — TARGETED, which is what makes it affordable. The
    docstring of `spec0161_attribute_unnamed` used to concede that the code arm could not have the
    diff-aware family's baseline-vs-current shape, because its base side would be the whole `bin/`
    tree plus the re-folded journal at the merge-base. That objection prices the WRONG question. The
    only keys whose base state can change an answer are the FEW this branch actually added, so the
    base side asks about those alone: one `git grep -l -F` over `<base>:bin` restricted to those key
    literals gives a handful of CANDIDATE FILES, and each candidate is read at the base rev and
    judged by the SAME pure `spec0161_structural_keys`. The grep is a FILE FILTER ONLY — every
    verdict still comes from the tokenizer-blanked matcher, so a quoted example or a comment at the
    base can no more exempt a branch than it can charge one.

    EXIT STATUS 1 IS AN ANSWER, NOT A FAULT (audit-pre finding 1), and conflating the two would
    DISABLE this gate rather than narrow it. `git grep` exits 1 when nothing matches — which is the
    NORMAL case this whole mechanism exists for: a genuinely new key has no base occurrence, so the
    branch IS charged. Only rc > 1 (or a subprocess that did not run), and a failing `git show` of a
    candidate, are git FAULTS; those return None, never an empty base set, because an empty one
    would silently restore the over-charge at a REFUSING gate (episode-2 finding B6, applied in the
    opposite direction: an unknown base must not be read as "nothing pre-existed").

    Returns `(added_files, unnamed_by_branch_keys, base_structural_keys, sites)` — `added_files` a
    list of `(post_image_text, added_line_numbers_or_None)`, `base_structural_keys` the subset of
    this branch's added keys that already read back under `bin/` at the merge-base, and `sites` a
    `{key: "<relpath>:<line>"}` map of one charging site per added key (T-12411) — or None, never a
    partial answer, when there is no merge-base or any git call fails. `([], set(), set(), {})` is a
    real answer (this branch touched neither); None is the ABSENCE of one, and the callers take
    opposite fail-safe directions on it. The tuple GREW at the tail, so every existing reader of
    `[0]` / `[1]` is unchanged by construction."""
    import subprocess

    def _git(*args):
        try:
            return subprocess.run(["git", "-C", str(repo_root), *args],
                                  capture_output=True, text=True, check=False, timeout=30)
        except Exception:
            return None

    base = _git("merge-base", "HEAD", "main")
    if base is None or base.returncode != 0 or not base.stdout.strip():
        return None
    base_sha = base.stdout.strip()

    diff = _git("diff", base_sha, "--", "bin")
    if diff is None or diff.returncode != 0:
        return None
    # WHICH LINES, IN WHICH FILE. The new-side line counter is advanced by added and context lines
    # (a removed line does not exist on the new side), so every `+` line is recorded at its POSITION
    # IN THE POST-IMAGE — the index `spec0161_code_text` selects by.
    per_file, current, newno = {}, None, 0
    for ln in diff.stdout.splitlines():
        if ln.startswith("+++ "):
            path = ln[4:].strip()
            current = None if path == "/dev/null" else (path[2:] if path.startswith("b/") else path)
        elif ln.startswith("@@"):
            m = re.search(r"\+(\d+)", ln)
            newno = int(m.group(1)) if m else 0
        elif current is None:
            continue
        elif ln.startswith("+"):
            per_file.setdefault(current, set()).add(newno)
            newno += 1
        elif ln.startswith(" ") or ln == "":
            newno += 1                                  # context: present on the new side too
        # a `-` removal, a `\ No newline` marker and every header line advance nothing

    # A FAILED READ IS UNKNOWABLE, NOT AN EMPTY ONE (audit-post episode-2 finding B6). A file that
    # the diff says this branch touched but that cannot be read is a fact about the CHECKER, and
    # skipping it returns a PARTIALLY populated answer wearing `attributable: True` — a land refusal
    # that then misses the key the unread file introduced. A deletion is not this case: `+++
    # /dev/null` already excluded deleted paths from `per_file` above, so any OSError here is a
    # genuine read fault and the whole answer becomes None.
    # `added` is the contract the pure attributor takes (text, lines); `paths` is the PARALLEL list
    # of the relative path each entry came from, kept because only THIS layer knows it and the
    # charging-site rendering (T-12411) needs it. Built in the same two loops, so the two lists
    # cannot drift.
    added, paths = [], []
    for rel, lines in sorted(per_file.items()):
        try:
            added.append((Path(repo_root, rel).read_text(encoding="utf-8", errors="ignore"), lines))
        except OSError:
            return None
        paths.append(rel)

    untracked = _git("ls-files", "-o", "--exclude-standard", "--", "bin")
    if untracked is None or untracked.returncode != 0:
        return None
    for rel in untracked.stdout.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        try:
            # A brand-new file is added in its ENTIRETY — `lines=None`, the whole post-image.
            added.append(
                (Path(repo_root, rel).read_text(encoding="utf-8", errors="ignore"), None))
        except OSError:
            return None
        paths.append(rel)

    # T-12411 — the CHARGING SITES and the MERGE-BASE side, both derived from `added` and therefore
    # shared by the consumer arm below (a consumer's arm (i) charge is as over-chargeable as the
    # kernel's, and its WARN names a site for the same reason a refusal does).
    _sites, _branch_keys = {}, set()
    for _rel, (_text, _lines) in zip(paths, added):
        for _k, _ls in spec0161_structural_key_sites(_text, _lines).items():
            _branch_keys.add(_k)
            _sites.setdefault(_k, f"{_rel}:{_ls[0]}")
    _base = _spec0161_base_structural_keys(_git, base_sha, _branch_keys, repo_root)
    if _base is None:
        return None

    # ARM (ii): the record span, then vs now — BOTH SIDES RESOLVED INDEPENDENTLY (audit-post
    # episode-2 finding B5). Reading the base side at the CURRENT path silently returns an empty
    # removal set whenever the branch DELETED or RENAMED the record file: the glob finds no current
    # path (or a new one `git show <base>:` cannot resolve), the arm charges nothing, and the branch
    # that removed the record — un-naming EVERY key at once — is admitted as having introduced
    # nothing. So the base side is located in the BASE TREE (`git ls-tree`) and the current side on
    # disk, and their span keys are differenced whichever way the file moved. A git fault on either
    # side is UNKNOWABLE (None, finding B6), never an empty set.
    if consumer:
        # Skipped, not silently empty. Both sides of arm (ii) would resolve to nothing in a consumer
        # tree today, so the observable answer is the same — but writing the skip down is what stops
        # a future consumer that grows an unrelated `specs/SPEC-0161-*` from being compared against
        # the WRONG record. Arm (i) above still carries this branch's real charge.
        return added, set(), _base, _sites

    base_tree = _git("ls-tree", "-r", "--name-only", base_sha, "--", "specs")
    if base_tree is None or base_tree.returncode != 0:
        return None
    base_specs = sorted(r.strip() for r in base_tree.stdout.splitlines()
                        if _SPEC0161_SPEC_NAME.search(r.strip()))
    base_keys = set()
    if base_specs:
        shown = _git("show", f"{base_sha}:{base_specs[0]}")
        if shown is None or shown.returncode != 0:
            return None
        base_keys = _spec0161_record_span_keys(shown.stdout)
    now_keys = set()
    spec_paths = sorted(Path(repo_root, "specs").glob("SPEC-0161-*.yaml"))
    if spec_paths:
        try:
            now_keys = _spec0161_record_span_keys(
                spec_paths[0].read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            return None
    return added, base_keys - now_keys, _base, _sites


def _spec0161_engine_record_specs(repo_root):
    """T-12412: THE ONE PREDICATE for "does this root own the SPEC-0161 record, or borrow it?".

    Returns the ENGINE's `specs/` dir when this root carries no `SPEC-0161-*.yaml` of its own and the
    engine root is a genuinely different path; returns None otherwise. `None` therefore means exactly
    "kernel-shaped root — read your own record", which is what keeps the engine's own checkout (and
    every engine worktree, which carries the file too) on the UNCHANGED path by construction.

    THE DISCRIMINATOR IS THE CORPUS, NOT A BUILD FLAG, on purpose. The fact that makes `spec_text`
    empty IS the fact that makes the remedy unexecutable IS the fact that makes the land refusal
    unfair — so one predicate answers all three, and they cannot drift apart. It also gets the
    SPEC-0092 id-collision case right for free: a consumer that owns its OWN `SPEC-0161-*.yaml` reads
    as kernel-shaped and keeps its own text and its own hard refusal, which is correct — it CAN edit
    that file.

    Never raises: the engine root is derived from `host_paths._engine_root()` (off `__file__`, so a
    copied or published engine tree resolves to the copy it is actually running from), and any fault
    resolving or globbing degrades to None — i.e. to today's behaviour."""
    try:
        from lib import host_paths as _hp
        root = Path(repo_root).resolve()
        if any(root.glob("specs/SPEC-0161-*.yaml")):
            return None
        engine = Path(_hp._engine_root()).resolve()
        if engine == root:
            return None
        return engine / "specs"
    except Exception:
        return None


def spec0161_branch_unnamed(repo_root, *, oracle=None, _spec0161_branch_added_code, _spec0161_corpus_inputs, _spec0161_engine_record_specs, _spec0161_inputs, spec0161_added_emit_pairs, spec0161_attribute_unnamed, spec0161_payload_key_coverage, journal_if_attributable=False):
    """T-12232: THE SINGLE ENTRY POINT for "which unnamed SPEC-0161 pairs does THIS branch owe?".

    Materialise -> the ONE oracle -> attribute. All four readers call THIS: the `task commit` WARN,
    the `work commit` WARN, the cheap `land` preflight refusal, and the two live-corpus land-verify
    gates. One implementation, so a refusal, a warning and a test verdict can never disagree about
    who introduced a key (SPEC-0188 rule 4's one-implementation discipline).

    TWO CANDIDATE SOURCES AS OF T-12423, ONE ORACLE. The journal fold can only offer a (type, key)
    pair once a row CARRYING the key exists, so the branch that ADDS the emitter was admitted at its
    own land and reddened every other tree once the first row arrived at runtime (measured
    2026-09-11: `bg_dispatch_launched.land_regime`, 2h10m of fleet-wide main-red). So the oracle is
    ALSO run over a candidate set read structurally from this branch's ADDED CODE
    (`spec0161_added_emit_pairs`), with the SAME corpus / code blob / record text, and its `unnamed`
    is UNIONED into `introduced` (deduped, and minus the T-12411 merge-base keys). ALONGSIDE, never
    instead of: `inherited`, `governing`, `named`, `unnamed` and `coverage` are the JOURNAL leg's
    verbatim, so an inherited pair still reads inherited and is still charged to nobody (T-12423 AC2).

    THE RESIDUE THIS SECOND SOURCE ADDS, named rather than papered over. `spec0161_added_emit_pairs`
    reads an emit by SHAPE (first positional string constant + a payload dict literal), so a
    non-emitting call wearing that shape — `d.setdefault("state", {"x": 1})` — offers a candidate
    pair. It is only ever a CANDIDATE: the oracle still requires the type to be mentioned in the
    corpus, the key to be absent from it, and the key to be read back under `bin/`, and T-12411's
    merge-base subtraction still applies. A pair surviving all four is one the record genuinely does
    not name.

    Returns the `spec0161_attribute_unnamed` dict plus `governing` / `unnamed` / `coverage` from the
    oracle, so a caller needing the corpus-wide reading beside the attributed one (the floor gate)
    does not have to run the oracle a second time. Never raises.

    `oracle` — a `spec0161_payload_key_coverage(...)` result the CALLER already computed, reused
    verbatim instead of recomputing (audit-post episode-2 finding B1). Both live gates compute the
    oracle for their own arms and then call this function; recomputing here re-read the `bin/` tree
    and re-folded the journal a SECOND time, so a row appended between the two reads gave the gate
    two DIFFERENT snapshots — a numerator attributed against one denominator and compared against
    another, i.e. a false failure from a concurrent write. Passing the snapshot makes the pair
    consistent BY CONSTRUCTION; omitting it keeps the self-contained behaviour the verbs use."""
    root = Path(repo_root)
    # T-12412 — computed ONCE and reported, so the three things that depend on it (which record to
    # read, which remedy to name, whether the land refuses) can never disagree. It describes the
    # ROOT, not the snapshot, so it is reported even when the caller injected its own `oracle`.
    _engine_specs = _spec0161_engine_record_specs(root)
    _consumer = _engine_specs is not None
    result = oracle
    _corpus_side = None
    # T-13295 — `journal_if_attributable` (the `task commit` + `work commit` WARNs — T-13377; default
    # False = unchanged for debt / land): the diff is derived FIRST, and when it is unknowable or names no key
    # (K|U empty) the journal fold is skipped — `introduced` is provably identical, since it is the
    # journal pairs whose key is in K|U plus the added-code leg, which never reads the journal. The
    # corpus-wide fields (`inherited` / `unnamed` / `coverage`) then describe an empty journal, which
    # that caller never reads. Otherwise the fold reads WHOLE history as before (no type->key index
    # exists — routed T-13288), served inside `task commit`'s one-pass scope by extension.
    _diff = _spec0161_branch_added_code(root, consumer=_consumer) if journal_if_attributable else None
    _skip_journal = journal_if_attributable and (
        _diff is None or not spec0161_attribute_unnamed(
            [], added_files=_diff[0], unnamed_by_branch=_diff[1],
            base_structural_keys=_diff[2]).get("keys"))
    if result is None and _skip_journal:
        corpus, code_blob, spec_text = _spec0161_corpus_inputs(
            root / "specs", root / "bin", engine_specs_dir=_engine_specs)
        _corpus_side = (corpus, code_blob, spec_text)
        result = spec0161_payload_key_coverage(
            corpus=corpus, code_blob=code_blob, type_keys={}, spec_text=spec_text,
            borrowed_record=_consumer)
    if result is None:
        corpus, code_blob, type_keys, spec_text = _spec0161_inputs(
            root / "specs", root / "bin", root / "events.jsonl",
            engine_specs_dir=_engine_specs)
        _corpus_side = (corpus, code_blob, spec_text)
        # T-12819 — the CONSUMER arm judges membership against the BORROWED kernel catalog, so a
        # branch key on this repo's OWN private type never becomes `introduced`, never reaches the
        # `--brief` list of `spec0161_unnamed_key_message`, and never becomes a `cross request` the
        # kernel cannot execute. `_consumer` is the same one predicate computed above.
        result = spec0161_payload_key_coverage(
            corpus=corpus, code_blob=code_blob, type_keys=type_keys, spec_text=spec_text,
            borrowed_record=_consumer)
    if not journal_if_attributable:
        _diff = _spec0161_branch_added_code(root, consumer=_consumer)
    attribution = spec0161_attribute_unnamed(
        result["unnamed"],
        added_files=None if _diff is None else _diff[0],
        unnamed_by_branch=None if _diff is None else _diff[1],
        base_structural_keys=None if _diff is None else _diff[2])
    # T-12423 — THE SECOND CANDIDATE SOURCE, run through THE SAME ORACLE. The journal leg above can
    # only see a pair a row already carries, so the branch that ADDS the emitter is admitted at its
    # own land and reddens main for everyone once the first row arrives at runtime. Here the
    # candidate set is read from the branch's ADDED CODE instead (`spec0161_added_emit_pairs`), the
    # oracle answers the SAME governing/named question over the SAME corpus / code / record, and its
    # `unnamed` is UNIONED into `introduced`. ALONGSIDE, never instead of: `inherited`, `governing`,
    # `named`, `unnamed` and `coverage` stay the journal leg's verbatim, so a pair whose rows predate
    # this branch is still charged exactly as before (AC2).
    _introduced = list(attribution["introduced"])
    if _diff is not None and attribution["attributable"]:
        _added_pairs = spec0161_added_emit_pairs(_diff[0])
        if _added_pairs:
            if _corpus_side is None:
                # The caller injected its own `oracle`, so the corpus side was never materialised
                # here. Read it WITHOUT the journal fold — which is what the `_spec0161_corpus_inputs`
                # split exists for: this leg must not consult the journal, and re-folding it would
                # also pay the expensive input twice.
                _corpus_side = _spec0161_corpus_inputs(
                    root / "specs", root / "bin", engine_specs_dir=_engine_specs)
            _added_result = spec0161_payload_key_coverage(
                corpus=_corpus_side[0], code_blob=_corpus_side[1],
                type_keys={t: set(ks) for t, ks in _added_pairs.items()},
                spec_text=_corpus_side[2],
                # T-12819 — the SAME membership on the added-code leg: both quantifiers ask the one
                # oracle the same question, so a private-type key cannot slip in through the leg the
                # journal leg cannot see yet.
                borrowed_record=_consumer)
            # T-12411's rule, unchanged and applied to this leg too: a key that ALREADY read back
            # structurally under `bin/` at the merge-base was not introduced HERE.
            _base = set(_diff[2] or ())
            for _pair in _added_result["unnamed"]:
                _pair = tuple(_pair)
                if _pair[1] in _base or _pair in _introduced:
                    continue
                _introduced.append(_pair)
    attribution = dict(attribution, introduced=_introduced)
    return dict(attribution,
                consumer=_consumer,
                # T-12411 — the charging SITES, carried out beside the verdict so the ONE message
                # every reader pastes can name `<path>:<line>` without re-deriving the scan. Empty
                # on an unknowable diff, where there is nothing charged to site anyway.
                sites={} if _diff is None else _diff[3],
                governing=result["governing"],
                named=result["named"],
                unnamed=result["unnamed"],
                coverage=result["coverage"])


#: The `deviation_captured` fingerprint the consumer land-preflight downgrade records, and the value
#: the downgrade's own message hands the operator to paste into `cross request --origin-fp`. ONE
#: derivation, so the row that is recorded and the request that discharges it name the SAME thing.
SPEC0161_CONSUMER_FP_PREFIX = "spec0161-key-unnamed-consumer"


def spec0161_consumer_fingerprint(pairs, *, SPEC0161_CONSUMER_FP_PREFIX):
    """T-12412: the stable fingerprint for "this consumer branch owes these SPEC-0161 names".

    Derived from the SORTED pair set alone, so the same owed set always clusters to the same value
    however the pairs were discovered. It is for CLUSTERING, never for suppression: nothing reads it
    to skip a row, and every consumer land that still owes the pairs records another
    `deviation_captured` — the recurrence COUNT is the signal an aspect-audit folds
    (`patterns/error-friction-tracking.md`), and deduping would hide exactly how often a consumer is
    paying this."""
    body = ";".join(f"{t}.{k}" for t, k in sorted(pairs))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    return f"{SPEC0161_CONSUMER_FP_PREFIX}-{digest}"


def spec0161_unnamed_key_message(pairs, *, verb, consumer=False, sites=None, SPEC0161_RECORD_HEADING, spec0161_consumer_fingerprint):
    """T-12232: THE ONE TEXT the commit WARN and the land refusal both paste, so they cannot drift.

    This string IS the line the Controller had been hand-adding to every dispatch brief («a NEW
    journal payload key in your diff MUST be named in the SPEC-0161 record in the SAME diff»), moved
    into the verb that can actually detect the condition. A hand-carried rule reaches only the
    briefs someone remembered to write it into; this reaches every branch that introduces a key.

    `consumer` (T-12412) — ONLY THE REMEDY LINE FORKS, and it forks because the kernel remedy is
    UNEXECUTABLE by the party it is handed to. SPEC-0161 is a kernel spec: under `-C` it is
    query-only (SPEC-0092) and a consumer write into the engine corpus is refused outright
    (`cli._guard_consumer_engine_write`, SPEC-0078). Telling a consumer to `spec edit SPEC-0161` is
    telling it to run a command the engine will refuse — measured as a HARD land refusal with no
    consumer-side exit at all (<project> X-1349, `T-0500`). The consumer is instead pointed at the
    route that actually gets a key named for it: `cross request` to the kernel — the same X-1263 ->
    T-12069 route by which `spike_channel_grant.compose_project` got into the record in the first
    place. The finding, the why, and the inherited-pairs footer stay ONE shared text: a consumer and
    the kernel must never disagree about WHAT was found, only about what to do next.

    `sites` (T-12411) — the `{key: "<path>:<line>"}` map `spec0161_branch_unnamed` returns. Each
    listed pair is rendered WITH its charging site when one is known, so the charged party can go
    look at the line rather than re-deriving the structural scan by hand to find out where the claim
    comes from. A pair charged by the UN-NAMING arm has no code site and is listed bare — correctly:
    its charge is in the record, not in the diff. Optional and absent-tolerant, so the pure callers
    and every existing test keep the unchanged text."""
    def _listed(t, k):
        where = (sites or {}).get(k)
        return f"    {t}.{k}" + (f"  ({where})" if where else "")
    listed = "\n".join(_listed(t, k) for t, k in sorted(pairs))
    if consumer:
        brief = "; ".join(f"{t}.{k}" for t, k in sorted(pairs))
        fp = spec0161_consumer_fingerprint(pairs)
        remedy = (
            f"  SPEC-0161 is a KERNEL spec — this repo cannot edit it (query-only under `-C`, and a "
            f"consumer write into the engine corpus is refused), so the fix is NOT a spec edit here. "
            f"Route it to the kernel, which is how these keys get named (the X-1263 -> T-12069 "
            f"route):\n"
            f"    bin/yitc-v2 cross request --to yitc-v2 --kind bugfix \\\n"
            f"      --origin-fp {fp} \\\n"
            f"      --origin-ref <this-repo>/events.jsonl#ts=<the deviation_captured row just "
            f"recorded> \\\n"
            f"      --brief 'name these governing journal payload keys in the SPEC-0161 record: "
            f"{brief}'\n"
            f"  (`--kind bugfix` requires both origin flags — SPEC-0085 §3. The fingerprint above is "
            f"the one this run recorded, so the request and the capture join up.)\n"
            f"  Your land is NOT blocked by this — it is recorded and reported, not refused.\n")
    else:
        remedy = (
            f"  Fix it here, for free: `bin/yitc-v2 spec edit SPEC-0161` and add the key(s) to the "
            f"set under \"{SPEC0161_RECORD_HEADING}\", then commit that edit with this change.\n")
    return (
        f"{verb}: this branch's diff introduces {len(pairs)} governing journal payload key(s) that "
        f"SPEC-0161's record does not name:\n{listed}\n"
        f"  A key is named in the SPEC-0161 record BY THE BRANCH THAT INTRODUCES IT, in the SAME "
        f"diff — otherwise the land-verify recomputation reds every later land until someone edits "
        f"the record by hand (measured 2026-09-07: 7 aborted lands, 4 halted workers, ~70 min).\n"
        + remedy +
        f"  Inherited pairs — ones your diff did not introduce — are NOT your charge and are not "
        f"listed here; they are reported by `bin/yitc-v2 debt` (SPEC-0119 rule 28).")


def _spec0161_corpus_inputs(specs_dir, code_dir, *, engine_specs_dir=None, _SEARCH_SKIP_DIRS):
    """The THREE CORPUS-SIDE materialisations the oracle needs — corpus, code blob, record text —
    kept out of the oracle so the oracle stays pure, and kept out of `_spec0161_inputs` (which is
    this plus the journal fold) so a second CANDIDATE SOURCE can reuse them WITHOUT re-folding the
    journal (T-12423). Every read is best-effort: an unreadable file contributes nothing rather than
    raising, because this feeds a report-only seam that must never break `session start` or `land`.

    THE SPLIT IS THE WHOLE POINT, not tidiness. The journal fold is the expensive input AND the one
    the T-12423 leg must NOT consult: a branch that ADDS an emitter has no row carrying its key yet,
    so the added-code candidate source asks the oracle the same question against the same corpus /
    code / record while supplying its OWN `type_keys`. One oracle, two quantifiers.

    `engine_specs_dir` (T-12412) — WHERE TO FIND THE RECORD WHEN THIS ROOT DOES NOT OWN IT. SPEC-0161
    is a KERNEL spec; a `-C` consumer's `specs/` has no `SPEC-0161-*.yaml`, so `spec_text` came back
    EMPTY and the oracle's `named` test — `pair[0] in spec_text and pair[1] in spec_text` — was
    ALWAYS false there. Every governing pair read UNNAMED under `-C`, INCLUDING the pairs the kernel
    record does name (<project> X-1349: `T-0500`'s land hard-refused on `spike_channel_grant.
    compose_project`, a pair the kernel record has named since T-12069 / X-1263). Given this dir, the
    record is resolved from it when — and only when — this root carries none of its own.

    THE CORPUS IS DELIBERATELY NOT EXTENDED, only `spec_text`. `governing` asks two questions about
    THIS repo's corpus (is the TYPE mentioned in it, is the KEY absent from it); folding kernel text
    into the corpus would make a consumer's key read as MENTIONED merely because the kernel happens
    to name it elsewhere, silently erasing the consumer's own coverage measurement. `named` is a
    question about the RECORD, and the record is the kernel's — that one, and only that one, moves.

    Keyword-only and defaulted, so omitting it reads exactly as this did before T-12412: the
    positional form every caller uses is byte-identical in behaviour."""
    corpus_parts, spec_text = [], ""
    for path in sorted(Path(specs_dir).glob("*.yaml")):
        try:
            blob = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        corpus_parts.append(blob)
        if "SPEC-0161-" in path.name:
            spec_text = blob

    if not spec_text and engine_specs_dir is not None:
        # Best-effort, like every other read here: an unreadable or absent engine record leaves
        # `spec_text` empty, which is exactly today's behaviour — never an exception at a seam that
        # must not break `session start` or `land`.
        try:
            for path in sorted(Path(engine_specs_dir).glob("SPEC-0161-*.yaml")):
                spec_text = path.read_text(encoding="utf-8", errors="ignore")
                break
        except OSError:
            pass

    code_parts = []
    _code_root = Path(code_dir)
    for path in sorted(_code_root.rglob("*")):
        if not path.is_file():
            continue
        # T-11868 — SKIP the dependency / VCS / build trees this module ALREADY names
        # (`_SEARCH_SKIP_DIRS`, the sibling bounded source-search's set, reused rather than a second
        # list). Unfiltered, the sweep read every `__pycache__/*.pyc` under the tree: compiled blobs
        # that are not source, whose interned strings make a governing key read as MENTIONED IN CODE
        # when only a stale bytecode copy holds it — a false green in the rule-28 coverage fold, and
        # cost paid to produce it. The skip is on the path's PARTS, so a nested `.venv/…/x.py` drops
        # too, not merely a top-level one.
        try:
            _rel_parts = path.relative_to(_code_root).parts[:-1]
        except ValueError:
            _rel_parts = path.parts[:-1]
        if any(part in _SEARCH_SKIP_DIRS for part in _rel_parts):
            continue
        try:
            code_parts.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue

    return "".join(corpus_parts), "".join(code_parts), spec_text


def _spec0161_inputs(specs_dir, code_dir, events_path, *, engine_specs_dir=None, _spec0161_corpus_inputs):
    """The four materialisations rule 28's fold needs: the corpus side (`_spec0161_corpus_inputs`)
    plus the JOURNAL fold that turns emitted rows into the oracle's candidate set.

    Signature and return order are UNCHANGED (T-12423 split only the corpus side out), so every
    existing caller and test reads exactly as it did before — `engine_specs_dir` stays keyword-only
    and defaulted, and the positional three-arg form is byte-identical in behaviour."""
    corpus, code_blob, spec_text = _spec0161_corpus_inputs(
        specs_dir, code_dir, engine_specs_dir=engine_specs_dir)

    type_keys = {}
    try:
        # SPEC-0190 rule 4 — the WHOLE journal (T-11649). This fold's declared horizon is the
        # root journal's SEGMENT SET, which is what the census records for it; reading the live
        # segment alone silently drops every archived row (the X-1100 class, and the reason the
        # cohort sibling `_test_class_executions` already takes this branch).
        # T-13139 — it reads EVERY type (which types matter is decided at runtime against the spec
        # corpus), so it is a REDUCER, not a typed read: inside the debt seam's scope the one pass
        # already fed it; outside, one bounded walk. It keeps type -> data keys, never a row.
        _fed = journal.reduce_journal(events_path, TypeKeysReducer, name="spec0161_type_keys")
        type_keys = {t: set(keys) for t, keys in _fed.type_keys.items()}   # a fresh copy per call
    except OSError:
        pass

    return corpus, code_blob, type_keys, spec_text


class TypeKeysReducer:
    """`_spec0161_inputs`' journal fold as a reducer (T-13139): event type -> the union of its rows'
    top-level `data` keys, types in first-seen order."""

    def __init__(self):
        self.type_keys: dict = {}

    def add(self, seq, seg, obj, line) -> None:
        t, data = obj.get("type"), obj.get("data")
        if isinstance(t, str) and isinstance(data, dict):
            self.type_keys.setdefault(t, set()).update(data.keys())

    def prepend(self, older) -> None:
        """T-13295 — merge `older` (the same reducer fed the segments logically BEFORE this one's) AHEAD
        of this one: its types first, keys unioned — exactly one logical-order walk's answer, so a
        horizon-bounded scope can extend over the older segments without re-walking its own."""
        merged = {t: set(ks) for t, ks in older.type_keys.items()}
        for t, ks in self.type_keys.items():
            merged.setdefault(t, set()).update(ks)
        self.type_keys = merged

    # T-13309 — the whole-history index's summary protocol (`journal._summary_identity`): types in
    # first-seen order as a pair list (the index sorts JSON object keys), keys sorted (a set).
    def summary_key(self):
        return {"v": 1}

    def summary(self):
        return [[t, sorted(ks)] for t, ks in self.type_keys.items()]

    def load_summary(self, state) -> None:
        self.type_keys = {t: set(ks) for t, ks in state}
