"""Pure text / parse / format substrate for the yitc-v2 CLI — the first layer-2 CORE leaf.

The single home for the small, host-independent text helpers that bin/yitc-v2 previously carried
inline: slug/id/anchor parsing, scalar→list coercion, ISO-timestamp parsing, `--probe key:value`
parsing, YAML-scalar rendering, template-header substitution, Claude-message text extraction, and
the SPEC-0002 verbatim-text cap. bin/yitc-v2 imports these and re-binds them under their historical
names (`_slug`, `_as_list`, …) so every existing caller keeps working unchanged.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It holds NO
REPO_ROOT / *_DIR coupling and never back-imports the host: it depends ONLY on the already-extracted
lower leaves `lib.state` (for `yaml_scalar` → `state.scalar`) and `lib.events` (for `cap_text`'s
byte-window helpers) plus stdlib. The host fail primitive `_die` is NOT moved — it is INJECTED as a
`die` argument by the three helpers that need it (`as_list`, `parse_probe`, `scaffold_substitute`),
so the host residue wrapper reads the current `yitc._die` at call time and any monkeypatch on it
stays honored. Behaviour is byte-identical to the inline originals — the test suite is the oracle.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import re
import sys
import unicodedata
from pathlib import Path  # T-12435 — the re-homed `symbol_region` binds a file suffix to its grammar

from lib import events
from lib import state

MAX_TEXT_CHARS = 3000      # SPEC-0002 verbatim text soft cap


def extract_text(content) -> str:
    """Claude Code message.content (str | list[text-blocks]) → joined text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return "\n".join(parts)
    return ""


def cap_text(text: str) -> dict:
    """SPEC-0002 text cap → data dict with text + overflow metadata when truncated."""
    raw = text.encode("utf-8")
    if len(text) <= MAX_TEXT_CHARS and len(raw) <= 2800:
        return {"text": text}
    sha = hashlib.sha256(raw).hexdigest()
    capped = events._byte_head(text, 1500) + "\n…[elided]…\n" + events._byte_tail(text, 500)
    return {"text": capped, "truncated": True,
            "original_size_chars": len(text), "sha256": sha}


def parse_iso_ts(ts):
    """Parse an ISO-8601 `ts` to an aware datetime, or None (a parse miss only degrades the advisory
    recency text, never the class decision — same tolerance as _session_last_event_ts)."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        return _dt.datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


# T-11164 (X-0926) — lowercase Cyrillic → latin. Applied AFTER `.lower()`, so lowercase keys suffice.
# Russian а..я plus the Ukrainian/Belarusian extras that cost one entry each. Multi-char values where
# the sound needs them; ъ/ь carry no sound and map to ''. EVERY key is non-ASCII — that is what makes
# the latin corpus byte-identical BY CONSTRUCTION (a latin title never reaches a map entry, AC4).
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g", "ў": "u",
}


def slug(title: str, *, die=None) -> str:
    """Title → kebab-case id. NO meaning-bearing character is ever SILENTLY DROPPED (T-11164/X-0926).

    THE DEFECT THIS CLOSES. The body used to be a bare `[^a-z0-9]+` collapse with an `or "task"`
    fallback, so whatever latin/digit RESIDUE survived became the id, however meaningless:
        slug('Карточка статьи на двух вкладках') -> 'task'   (the generic fallback)
        slug('Отчёт 2026')                       -> '2026'   (a PARTIALLY non-latin title kept digits)
    Two harms, both real: the id carries none of the title's meaning, AND a SECOND non-latin-titled
    plan collapses onto the SAME degenerate id. It is the NORMAL path, not an edge case — owner-facing
    titles are Russian by our own Language rule (AGENTS §Language), so a consumer filing a plan the
    intended way lands here.

    THE RULE, in order — deliberately construction-level rather than an alphabet enumeration (the
    audit-pre pass-2 finding: a Cyrillic-only fix still let 'レポート 2026' → '2026', the same defect
    wearing another script):
      1. NFC-normalize + lowercase, so the map sees canonical PRECOMPOSED characters regardless of how
         the title was typed/encoded.
      2. Transliterate Cyrillic via `_TRANSLIT`.
      3. NFKD-fold + drop combining marks — handles ALL accented latin (é→e, ü→u, ñ→n) in one stdlib
         step, and is provably a no-op on pure ASCII. ORDER IS LOAD-BEARING: NFKD decomposes the
         Cyrillic diacritics too (ё→е, й→и, ў→у, ї→і), so folding FIRST would silently kill four map
         entries and turn 'Отчёт' into 'otchet' rather than 'otchyot'. Cyrillic is consumed before the
         fold ever runs; by then nothing but latin is left for it to touch.
      4. REFUSE if any SURVIVING character is alphanumeric but outside [a-z0-9] — i.e. a script we
         cannot transliterate (CJK, Arabic, Greek). This is the step that makes the guarantee
         alphabet-INDEPENDENT: the digits-only residue is no longer reachable from ANY script, because
         the dropped characters themselves refuse BEFORE the strip can silently eat them.
      5. The original collapse + 50-char truncation, unchanged. An empty result also refuses.

    Refusing on even ONE untransliterable alnum char ('Sprint α') is deliberate: a threshold would be a
    heuristic, and a loud refusal naming the character beats a silent drop.

    COLLISION (AC3) is closed at the two identity-bearing call sites, which already refuse loudly and
    are unchanged by this: `plan.cmd_plan_file` (`_find_draft` → "slug collision: …") and
    `scenario.cmd_scenario_new` (target.exists + a frontmatter `scenario:` key scan). The other three
    callers (task/spec/error) are id-PREFIXED, so two artifacts cannot share a filename. What the old
    body did was make collision CERTAIN — every non-latin title mapped to 'task', so the second such
    plan could not be filed at all; transliteration removes that systematic collapse and the
    pre-existing refusals stay the backstop for the residual shared-50-char-prefix case (which is
    today's behaviour for latin titles too).

    `die` is INJECTED, exactly as this module already does for as_list / parse_probe /
    scaffold_substitute (SPEC-0073 HARD — this leaf never exits the process). Default None raises
    ValueError instead, so a programmatic/test caller still gets a clean exception and an unwired
    caller stays valid (the T-0404 pattern).
    """
    composed = unicodedata.normalize("NFC", str(title)).lower()
    s = "".join(_TRANSLIT.get(c, c) for c in composed)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    unsupported = sorted({c for c in s if c.isalnum() and not ("a" <= c <= "z" or "0" <= c <= "9")})
    if unsupported:
        msg = (f"title {title!r} contains character(s) {''.join(unsupported)!r} that cannot be "
               f"transliterated into an id — retitle using latin or Cyrillic characters, or the id "
               f"would silently drop the title's meaning")
        if die is not None:
            die(msg)
        raise ValueError(msg)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:50]
    if not s:
        msg = (f"title {title!r} yields an empty id — retitle with latin or Cyrillic letters or "
               f"digits (an id must carry some of the title's meaning)")
        if die is not None:
            die(msg)
        raise ValueError(msg)
    return s


def as_list(name: str, val, die) -> list:
    """Coerce scalar→[scalar], pass lists, reject other shapes (audit-post F1)."""
    if val is None:
        return []
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return val
    die(f"{name} must be a string or list, got {type(val).__name__}")


# ── THE COLON-SPACE BULLET FOOTGUN — a card bullet that YAML parsed as a MAPPING (T-11990, X-1232) ──
# `as_list` above validates the CONTAINER shape and stops there; nothing has ever inspected the ELEMENT
# types. So a scope/acceptance bullet authored UNQUOTED and containing a `: ` — which is ordinary in card
# prose («… every other card touching it lands after: T-0574, then T-0581.») — is not a string at all. YAML
# reads the span before the colon as a KEY and the rest as its VALUE, and the bullet becomes a one-key
# mapping the MOMENT the card is filed. Nothing announces this: the card looks fine, `graph query` prints
# something plausible, and every later re-dump faithfully re-emits a mapping, because a serializer handed a
# dict has no way to know a human meant a sentence.
#
# HOW IT SURFACES, always late and always somewhere else: once the key exceeds YAML's 128-char simple-key
# limit the emitter switches to the `? ` complex-key form, so a verb asked to edit an UNRELATED field
# rewrites the card into a shape no author wrote. Measured on kupiclub T-0574: authored unquoted at the
# decomposition cut, carried silently through two more commits, then made visible by an
# `--amend-expected-touch` that merely re-dumped it — at the cost of a Stage-8 RED pass spent on a defect
# that had been on disk since filing. The re-dumping verb is the messenger, never the cause.
#
# WHY A DETECTOR AND NOT A COERCION: re-joining the key and value cannot recover the author's text. The
# original spacing is gone, a value that itself parsed as a list or a number is unrecoverable, and a bullet
# with two colons yields a nested shape no join reconstructs. Guessing would write a governed artifact the
# author never approved. So this REPORTS, and the caller refuses — the fix is one the author makes by
# quoting the bullet, which is the only place the intended text still exists.
#
# Pure, no I/O; the {field: values} mapping is caller-named, exactly like `shell_substitution_findings`
# below, so one detector serves every verb without knowing any verb's schema.

_BULLET_EXCERPT_CHARS = 80


def non_string_bullet_findings(fields) -> list:
    """Which card bullets are not plain strings — the colon-space footgun (T-11990).

    `fields` is an ordered mapping {field_name: iterable-of-entries}. Returns a list of
    (field, index, value) for every entry that is not a `str`, in field then index order; empty when
    every bullet is a string. A non-iterable / absent field contributes nothing (the container shape is
    `as_list`'s question, not this one).
    """
    out = []
    for field, entries in (fields or {}).items():
        if not isinstance(entries, (list, tuple)):
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, str):
                out.append((field, i, entry))
    return out


def non_string_bullet_excerpt(value, limit: int = _BULLET_EXCERPT_CHARS) -> str:
    """The offending bullet as the AUTHOR would recognise it — the text they typed, not `{'k': 'v'}`.

    A refusal that echoes a repr sends the reader hunting for a mapping they never wrote (the
    name-the-locus discipline in lessons/a-refusal-remedy-must-name-which-locus-it-repairs). For the
    one-key mapping this class produces, the author's line is recoverable for DISPLAY by re-joining
    key and value with `: ` — which is emphatically NOT a repair (see the module note above; the
    original spacing and any non-scalar value are already lost), only the most legible way to point at
    the line in the file. Any other shape falls back to a plain string rendering.
    """
    if isinstance(value, dict) and len(value) == 1:
        (k, v), = value.items()
        text = f"{k}: {'' if v is None else v}"
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def non_string_bullet_message(findings, *, locus: str, repair: str = None) -> str:
    """The ONE rendering of the refusal/warning text for `non_string_bullet_findings` (CHARTER §P5).

    Three call sites share it — the filing chokepoint, the card-write chokepoint and the load-seam
    WARN — so the wording cannot drift into three descriptions of one defect. `locus` names what the
    caller was doing; `repair`, when given, is appended as the concrete next command.
    """
    lines = [f"{locus}: {len(findings)} scope/acceptance bullet(s) are NOT plain strings — YAML parsed "
             f"them as mappings, so they are not the sentences they look like:"]
    for field, i, value in findings:
        lines.append(f"  {field}[{i}]: {non_string_bullet_excerpt(value)}")
    lines.append("CAUSE: the bullet was authored UNQUOTED and contains a colon followed by a space "
                 "(`lands after: T-0574`). YAML reads the text before that colon as a KEY and the rest "
                 "as its value, so the bullet becomes a one-key mapping — silently, at authoring time. "
                 "Once the key grows past 128 characters the emitter writes it back in the `? ` "
                 "complex-key form, and a verb asked to edit some OTHER field appears to corrupt the "
                 "card.")
    lines.append("FIX: quote the bullet — wrap the whole line in single quotes (doubling any internal "
                 "single quote), or rewrite it so no colon is followed by a space.")
    if repair:
        lines.append(f"REPAIR: {repair}")
    return "\n".join(lines)


def _item_key(value):
    """A stable, hashable identity for a YAML node — for sequence alignment only, never for output.

    `SequenceMatcher` needs hashable elements and a card's list items are frequently unhashable
    (a dict, once the colon-space footgun fires). The type name is part of the key so two nodes that
    RENDER alike but parse to different types never align as `equal`.
    """
    return (type(value).__name__, repr(value))


def type_change_findings(before, after, *, skip_fields=()) -> list:
    """Which nodes this edit RE-TYPED — the generic half of the field-edit type guard (T-11998).

    `before` / `after` are the two parses of ONE document (the same-loader parse of the raw text
    before and after a `--old/--new` substitution). Returns `(locus, before_type, after_type)` for
    every node whose Python type the edit changed, in field then index order; empty when nothing was
    re-typed. Pure — no I/O, no schema knowledge, so any caller can supply its own field mapping.

    Three deliberate non-findings, each a legitimate edit this guard must not block:
      * a key present on only ONE side — adding an absent key is the T-10546 superset-add, and
        dropping one is a removal; neither re-types an existing node;
      * a value that did not change at all;
      * `None` on EITHER side — filling `analysis: null` with prose, or clearing a field back to
        null, changes the type by definition and is exactly what those fields are for.

    LISTS are walked POSITIONALLY, not by an item-type SET. A set is blind to an item-level retype
    whenever the target type already occurs elsewhere in the list (before `[str, dict]` → after
    `[dict, dict]` reads as "both types already present" and passes). So the two item sequences are
    aligned with `difflib.SequenceMatcher`: an `equal` block is a RETAINED item and yields nothing; a
    `replace` block is paired by offset and each paired position whose type differs is a finding at
    `field[i]`; surplus AFTER items in a `replace` block, plus every `insert` block, are ADDITIONS.
    An addition is admitted when its type appears among the RETAINED items' types — falling back to
    the BEFORE list's item types when nothing was retained, and admitting anything when BEFORE is
    empty — so appending another string bullet stays legal while appending a mapping does not.
    """
    import difflib

    def _repair(was, now):
        """Is this a REPAIR rather than a retype? — a node collapsing INTO a plain string.

        The colon-space footgun only ever turns a string INTO a structure; going the other way is
        the fix for it. Refusing that direction would close the one route that repairs an
        already-corrupt card — the same reason T-11990 made its load seam WARN instead of refuse.
        A repair can introduce no structure, so admitting it costs this guard nothing.
        """
        return was is not str and now is str

    out = []
    skip = set(skip_fields or ())
    for field in before:
        if field in skip or field not in after:
            continue
        b, a = before[field], after[field]
        if b is None or a is None or b == a:
            continue
        if type(b) is not type(a):
            if not _repair(type(b), type(a)):
                out.append((field, type(b).__name__, type(a).__name__))
            continue
        if not isinstance(b, list):
            continue
        bk = [_item_key(x) for x in b]
        ak = [_item_key(x) for x in a]
        opcodes = difflib.SequenceMatcher(a=bk, b=ak, autojunk=False).get_opcodes()
        retained_types = {type(b[i]).__name__
                          for tag, i1, i2, _j1, _j2 in opcodes if tag == "equal"
                          for i in range(i1, i2)}
        additions = []
        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                continue
            if tag == "insert":
                additions.extend(range(j1, j2))
                continue
            if tag == "delete":
                continue
            # `replace` — pair by offset, the surplus on the AFTER side is an addition
            paired = min(i2 - i1, j2 - j1)
            for k in range(paired):
                bi, aj = b[i1 + k], a[j1 + k]
                if type(bi) is not type(aj) and not _repair(type(bi), type(aj)):
                    out.append((f"{field}[{j1 + k}]", type(bi).__name__, type(aj).__name__))
            additions.extend(range(j1 + paired, j2))
        allowed = retained_types or {type(x).__name__ for x in b}
        if not b:
            continue
        for j in sorted(additions):
            if type(a[j]) is not str and type(a[j]).__name__ not in allowed:
                out.append((f"{field}[{j}]", "/".join(sorted(allowed)), type(a[j]).__name__))
    return out


def type_change_message(findings, *, locus: str) -> str:
    """The ONE rendering of the `type_change_findings` refusal (CHARTER §P5) — sibling of
    `non_string_bullet_message`, which owns the scope/acceptance wording."""
    lines = [f"{locus}: {len(findings)} node(s) changed YAML TYPE — the replacement did not edit the "
             f"text in place, it turned the node into something else:"]
    for where, was, now in findings:
        lines.append(f"  {where}: {was} -> {now}")
    lines.append("CAUSE: the most common one is a colon followed by a space inside an UNQUOTED "
                 "scalar — YAML then reads the text before the colon as a KEY and the rest as its "
                 "value, so the node silently becomes a one-key mapping. A `--new` that opens a "
                 "list, or that drops the quoting the value needed, does the same.")
    lines.append("FIX: make --new produce the SAME YAML type it replaced — wrap the value in single "
                 "quotes (doubling any internal single quote), e.g. --new '\"...\"', or rewrite it "
                 "so no colon is followed by a space.")
    return "\n".join(lines)


def yaml_scalar(s: str) -> str:
    """Thin wrapper → state.scalar (YAML-safe inline scalar rendering, T-9207)."""
    return state.scalar(s)


# ── THE STORED-FORM MATCHER — one home for the RAW-vs-PARSED matching primitives ────────────────
# The recurring root, named across X-0284 (T-10321), X-0882 (T-11109) and X-0927 (T-11166): a
# field-edit verb counts occurrences in the RAW file text while the AUTHOR composed `old` from the
# PARSED value that `graph query` printed. Every storage style the emitter may choose — a block
# scalar's indentation, a quoted flow scalar's escapes, a long value WRAPPED across physical lines —
# then reads as "old not found", although the text is demonstrably in the parsed value.
#
# The adopted fix (designed in T-11109, extended here, never re-derived per verb): encode the
# CANDIDATE into the file's own stored form and re-count — rather than re-serializing the parsed
# document, which would rewrite every byte of the value and make the diff the whole field instead of
# the edit. These two primitives are that fix's shared parts; `spec.py` and `task.py` both call them,
# so there is ONE encoder and ONE folder (CHARTER §P1 F1 — no second matcher).


def flow_encode_variants(s: str, quote: str) -> list:
    """`s` rendered as the INNER text of a `quote`-style YAML flow scalar — one CANDIDATE per
    emitter setting the file does not record, `None` where unusable.

    Candidates rather than one guess, deliberately: whether a file stores `—` or `\\u2014` depends on
    the `allow_unicode` the writer used, which the file itself does not record. The caller accepts
    only a candidate ACTUALLY PRESENT in the raw text (or one that provably round-trips), so trying
    several cannot fabricate a match — it only avoids blinding the matcher to half the corpus.

    Fail-closed on line WRAPPING: a candidate carrying an emitter line break is dropped, because a
    wrapped candidate cannot be mapped onto a single replacement site. (The WRAPPING of the FILE is
    handled by `folded_match_spans` below, on the other side of the comparison — the candidate itself
    stays one line.) Order is stable (allow_unicode True, then False) so `old` and `new` can be paired
    BY INDEX and never mix encodings."""
    import yaml
    out = []
    for allow_unicode in (True, False):
        try:
            dumped = yaml.dump(s, default_style=quote, allow_unicode=allow_unicode,
                               width=10 ** 9).rstrip("\n")
        except Exception:                            # noqa: BLE001 — any emitter refusal is unusable
            out.append(None)
            continue
        if len(dumped) >= 2 and dumped[0] == quote and dumped[-1] == quote and "\n" not in dumped:
            out.append(dumped[1:-1])
        else:
            out.append(None)
    return out


def fold_text(text: str) -> tuple:
    """Fold `text` the way YAML folds a WRAPPED scalar, keeping a map back to the raw offsets.

    Returns `(folded, starts, ends)`: `folded[i]` is the i-th folded character and `starts[i]`/
    `ends[i]` are the half-open RAW span that produced it. A newline followed by continuation
    INDENTATION (one or more spaces/tabs) collapses — newline + indent together — into the single
    space YAML folds it to; every other character maps to itself.

    Only an INDENTED continuation folds. A newline followed by a column-0 line is a structural break
    (the next list item, the next key), and folding across it would let a candidate span two
    different values. Two further shapes deliberately do NOT fold, so an ambiguous case REFUSES
    rather than guessing: a blank line (YAML folds it to a literal newline, not a space) and trailing
    whitespace before the break. A caller that cannot find its candidate in this folded view falls
    back to refusing — the fail-closed direction."""
    folded, starts, ends = [], [], []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            j = i + 1
            while j < n and text[j] in " \t":
                j += 1
            if j < n and text[j] == "\n":
                # A BLANK line: YAML folds it to a literal newline, not to a space. The whole
                # whitespace run is emitted verbatim so NOTHING around it folds — a candidate can
                # then never match across it, which is the fail-closed direction (refuse, not guess).
                k = j
                while k < n and text[k] in " \t\n":
                    k += 1
                for p in range(i, k):
                    folded.append(text[p])
                    starts.append(p)
                    ends.append(p + 1)
                i = k
                continue
            # `j > i + 1` = there IS a continuation indent (an unindented next line is a STRUCTURAL
            # break — the next list item, the next key — and folding across it would let a candidate
            # span two different values).
            if j > i + 1 and j < n:
                folded.append(" ")
                starts.append(i)
                ends.append(j)
                i = j
                continue
        folded.append(ch)
        starts.append(i)
        ends.append(i + 1)
        i += 1
    return "".join(folded), starts, ends


def folded_match_spans(text: str, candidate: str) -> list:
    """Every RAW `(start, end)` span of `text` whose FOLDED content equals `candidate`.

    This is the wrap-aware half of the stored-form matcher: the candidate is the logical, unwrapped
    string (as the parsed value holds it), while the file may store it broken across physical lines
    with a continuation indent. Spans are returned in file order and never overlap.

    Returning ALL spans rather than the first is what keeps ambiguity FAILING CLOSED: the caller
    names the count and refuses a >1 match exactly as the raw-count path does, so folding can never
    turn a genuine 2-match into a silent single replace."""
    if not candidate:
        return []
    folded, starts, ends = fold_text(text)
    spans, at = [], 0
    while True:
        k = folded.find(candidate, at)
        if k < 0:
            return spans
        spans.append((starts[k], ends[k + len(candidate) - 1]))
        at = k + len(candidate)


def scaffold_substitute(text: str, template_name: str, field_subs: dict, die) -> str:
    """Replace each `^<field>:` header line in `text` with `<field>: <value>`. The pure-text half of
    _scaffold_doc (T-0860 split) — callers that pre-read the template (cmd_spec_new, no-id-burn) reuse
    THIS without a second file read, so there is one substitution implementation (P5)."""
    for field, value in field_subs.items():
        text, n = re.subn(rf"(?m)^{re.escape(field)}:.*$", f"{field}: {value}", text, count=1)
        if n == 0:
            die(f"template {template_name} has no '{field}:' header line — cannot scaffold")
    return text


def parse_probe(arg: str, die) -> tuple[str, str]:
    """Parse --probe key:value form (split on FIRST colon — value may contain more colons)."""
    if ":" not in arg:
        die(f"--probe argument {arg!r} must be in form 'key:value'")
    key, value = arg.split(":", 1)
    return key.strip(), value.strip()


def id_from_artifact_ref(ref: str) -> str | None:
    m = re.search(r"\b(T-\d{4,}|D-\d{4,}|SPEC-\d{4,})\b", ref)
    return m.group(1) if m else None


def anchor_file(anchor: str) -> str:
    """File component of an implements anchor — strips both `#<symbol>` (durable, D-0036)
    and legacy `:<line-range>`. Used to key the reverse index + match `graph query <file>`."""
    return re.split(r"[:#]", str(anchor), 1)[0]


# T-12435 — RE-HOMED from bin/lib/cli.py, verbatim. These two were the corpus's ONE region
# extractor, but they lived in the HOST module, so a leaf that needs them (bin/lib/audit.py's
# SPEC-0204 rule-8 locator derivation) could not import them without a cycle and would have had to
# write a SECOND resolver — the thing CHARTER §P1 F1 forbids. They join `anchor_file` here for the
# same reason it is here (T-9260): a pure, stdlib-only text primitive shared by host and leaves.
# cli.py keeps re-export residue, so every existing call site is unedited and behaviour-identical.


def symbol_bearing_lines(text: str, sym: str) -> list:
    """The `(line_index, line_text)` pairs for every DISTINCT line of `text` containing the literal
    `sym` (T-10797). The shared prefilter behind both anchor scans: every `<file>#<symbol>` pattern
    embeds `re.escape(sym)`, so no line without that literal can match, and a build resolves
    hundreds of anchors against files up to 1.1 MB. `str.find` walks the handful of hits at memchr
    speed instead of testing every line; newline counting accumulates FORWARD, never re-counting,
    and lines are sliced by offset so the caller need not split the whole text. Order is ascending,
    so a caller's «first matching line wins» tie-break is preserved."""
    out = []
    scanned = idx = 0
    pos = text.find(sym)
    while pos != -1:
        idx += text.count("\n", scanned, pos)
        scanned = pos
        if not out or out[-1][0] != idx:
            begin = text.rfind("\n", 0, pos) + 1
            stop = text.find("\n", pos)
            out.append((idx, text[begin:] if stop == -1 else text[begin:stop]))
        pos = text.find(sym, pos + 1)
    return out


def symbol_region(text: str, sym: str, file_rel: str) -> str | None:
    """Return the SOURCE SUBSTRING of `sym`'s region within `text`, or None if absent (T-0214).
    Reuses the SAME def/const/heading shapes as `_resolve_implements_anchor` — no parallel parser.

    GRAMMAR IS BOUND TO THE FILE TYPE (T-10310), never raced on line order. `file_rel` selects the ONE
    grammar that file's language actually has: `.md` -> markdown headings; everything else (incl. an
    EXTENSIONLESS python script like `bin/yitc-v2`) -> python def/const. Previously all three patterns
    were tried against every line and the first LINE matching ANY of them won — so a python `# ...`
    comment naming the symbol matched the markdown head_pat BEFORE the scan reached the real `def`,
    collapsing the region to that one comment line. The signature then hashed a comment: body edits
    never moved it, `graph build` reported 0 anchor drift, and `spec reverify` could not re-stamp it
    (live incident: SPEC-0133's `bin/lib/journal.py#cmd_journal_fleet_verdict` signed identically on
    main and on a branch that rewrote the function body — blocked T-10291's audit-post). `file_rel` is
    REQUIRED, not defaulted, so no call site can silently inherit the old grammar-race.

    Boundary heuristic (report-only, so a conservative bound is acceptable):
      - def/class/async-def: from its line (INCLUDING contiguous leading `@decorator` lines at the
        same indent — audit-pre F0: a decorator change must be in-region) until the next non-blank
        line at indent <= the def's. Multi-line signatures are covered: their continuation lines
        indent past the def, so they fall inside the region.
      - module const / annotation (`<sym> [:=]` at col 0): its line until the next non-blank col-0 line.
      - markdown heading (`#..# ... <sym>`): until the next heading of level <= its own."""
    # LITERAL PREFILTER (T-10797) — all three patterns below are matched LINE-BOUND (`.match` on one
    # line, never across the text) and embed `re.escape(sym)`, so `symbol_bearing_lines` yields
    # EXACTLY the lines the scan-every-line loop could have matched, in the same ascending order.
    # That loop ran up to 3 regex matches over EVERY line of files up to 1.1 MB — 2.3 M
    # python-level `re.match` calls per build.
    is_md = Path(file_rel).suffix.lower() == ".md"
    def_pat = re.compile(rf"^(\s*)(?:async\s+def|def|class)\s+{re.escape(sym)}\b")
    const_pat = re.compile(rf"^{re.escape(sym)}\s*[:=]")
    head_pat = re.compile(rf"^(#{{1,6}})\s+.*\b{re.escape(sym)}\b")
    start = indent = level = None
    kind = None
    for idx, ln in symbol_bearing_lines(text, sym):
        if is_md:                                 # markdown: headings ONLY — a fenced `def` is a sample
            hm = head_pat.match(ln)
            if hm:
                start, level, kind = idx, len(hm.group(1)), "head"
                break
            continue
        m = def_pat.match(ln)                     # code: def/const ONLY — a `#` line is a comment
        if m:
            start, indent, kind = idx, len(m.group(1)), "def"
            break
        if const_pat.match(ln):
            start, indent, kind = idx, 0, "const"
            break
    if start is None:
        return None
    lines = text.split("\n")                  # split only once a region exists to bound
    body_from = start                         # the matched def/const/head line; end-scan starts AFTER it
    if kind == "def":
        # extend the region START upward over contiguous leading decorators at the def's indent (F0).
        # `body_from` stays the def line so the end-scan below isn't truncated by the decorator lines.
        j = start - 1
        while j >= 0:
            dl = lines[j]
            if dl.strip() and (len(dl) - len(dl.lstrip())) == indent and dl.lstrip().startswith("@"):
                start = j
                j -= 1
            else:
                break
    end = len(lines)
    if kind == "head":
        for j in range(body_from + 1, len(lines)):
            hm = re.match(r"^(#{1,6})\s+", lines[j])
            if hm and len(hm.group(1)) <= level:
                end = j
                break
    else:
        for j in range(body_from + 1, len(lines)):
            ln = lines[j]
            if not ln.strip():
                continue
            if (len(ln) - len(ln.lstrip())) <= indent:
                end = j
                break
    return "\n".join(lines[start:end])


# Path-shaped token: a token carrying a `/` and a file extension (bin/lib/x.py, specs/SPEC-0036.yaml,
# an optional #symbol anchor), OR a bare filename with a source extension. Deliberately conservative —
# a low-confidence derivation must not manufacture noise, so only clearly path-shaped tokens qualify.
# T-10545 (X-0410) — the slash-branch extension MUST contain a LETTER. Its char class admits digits and
# dots, so a bare `\.[A-Za-z0-9]+` tail also matched a dotted VERSION TUPLE: `1.43.46/1.43.48` parsed as
# path `1.43.46/1.43` + extension `.48`, and the leg-2 advisor derived version tuples (1.43.46/1.43.48,
# 2.55.2/2.56.0) as expected_touch entries — boomrocket hand-corrected the field. A real path's extension
# is alphabetic; a numeric tail is the tuple's tell, and by shape alone it is the ONLY thing separating
# the two. Letter-ANYWHERE (not letter-first) keeps real extensions like .7z/.mp4/.h5 admissible.
# BOUND (honest, not the whole X-0410 story): by SHAPE this rejects the numeric-tail FALSE POSITIVE only.
# T-10563 closed the extension-LESS half via the `exists` WIDENER below; a prose-MENTIONED path the task
# never touches (`app/__init__.py`) is STILL derived — killing that needs a FILTER, the one direction the
# existence-coupling must never take (it would drop the to-be-CREATED paths expected_touch is for).
# Carried as a followup; see the T-10545 + T-10563 analyses.
# T-12113 (fu_30cf90e32a5a) — the classes below are UNICODE-aware, not ASCII. They used to be spelled
# [A-Za-z0-9_.-], so a project whose TEST FILENAMES carry non-ASCII letters (spec/models/подписка_spec.rb)
# yielded NO token at all, and task.criterion_names_test read its criterion as UNNAMED however faithfully
# it named the file — excluding that whole class of project from the declaration-first promise (T-12013).
# `\w` is Unicode for str patterns in py3, so this is a pure WIDENING: every token the ASCII classes
# admitted is still admitted (the new classes are supersets), which is what makes the existing
# recognizer tests the regression floor. The X-0410 numeric-tail discriminator is PRESERVED, only
# restated in Unicode terms: an extension must still contain a LETTER ([^\W\d_]) among alnum-but-not-
# underscore chars ([^\W_], the Unicode reading of the old [A-Za-z0-9]), so a version tuple like
# `1.43.46/1.43.48` is rejected exactly as before.
_PATH_TOKEN_RE = re.compile(
    r"[\w.\-]+(?:/[\w.\-]+)+\.[^\W_]*[^\W\d_][^\W_]*(?:#[\w.\-]+)?"
    r"|[\w\-]+\.(?:py|yaml|yml|md|json|sh|txt|cfg|toml|ini)\b")
# T-10563 (the X-0410 half T-10545 declined) — a slash-bearing token with NO extension requirement:
# `backend/Dockerfile`, `bin/lib`, and also junk like `1.43.46/1.43.48`. Shape CANNOT tell these apart,
# so this RE alone would be pure noise — it is only ever consulted together with the caller-injected
# `exists` predicate, which admits the ones that RESOLVE. Deliberately a superset of the shape branch's
# path part (same char class + optional `#anchor`); the widener skips anything already shape-admitted.
_PATH_LIKE_RE = re.compile(r"[\w.\-]+(?:/[\w.\-]+)+(?:#[\w.\-]+)?")  # T-12113: widened in lockstep


# T-10586 (X-0440) — the DECLARED-touch surface. `expected_touch` is a SCOPE-BOUNDARY declaration
# (SPEC-0103): every entry AUTHORIZES an edit. The two helpers below are what the Stage-1 write-back
# reads INSTEAD of regexing the analysis prose. The distinction they encode: `derive_path_tokens`
# above answers "what paths does this text MENTION" — a question whose answer can never be an
# authorization, because a thorough analysis mentions the read-only prior-art it eliminated, the
# scratch repro it ran, and the directories it searched. On boomrocket T-0262 that mention-set was
# written into expected_touch and declared 6 paths where 1 was real. A declaration must be DECLARED.
_TOUCH_MARKER_RE = re.compile(r"^[ \t]*expected_touch[ \t]*:[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_GLOB_META = ("*", "?", "[")


def declared_touch_entries(text: str) -> list:
    """The EXPLICIT `expected_touch: a, b` declaration line(s) in an analysis decision-record —
    NOT a prose scan (T-10586 / X-0440). Only a marker LINE counts: a path merely named in the
    narrative is a mention, never a declaration. Entries split on comma/whitespace; de-duped,
    order-preserving. Returns [] when the record declares nothing — the fail-closed default, which
    the caller must render as a BLIND advisor (a WARN), never as a derived set.

    Pure f(text) — no fs coupling (SPEC-0073 HARD, this module is the identity-agnostic leaf)."""
    out, seen = [], set()
    for m in _TOUCH_MARKER_RE.finditer(str(text or "")):
        for tok in re.split(r"[,\s]+", m.group(1).strip()):
            tok = tok.strip().strip("`'\"")
            if tok and tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out


def validate_touch_entries(entries, *, repo_contained, is_dir, exists) -> tuple:
    """FAIL-CLOSED validation of a declared `expected_touch` set (T-10586 / X-0440). Returns
    `(admitted, rejections)` where rejections is a list of `(entry, reason)` — the caller REFUSES on
    any rejection and names them; a silent drop would be the same authorization bug wearing a
    quieter face.

    THREE predicates, INJECTED (SPEC-0073 HARD — the caller owns REPO_ROOT, exactly as
    `derive_path_tokens`'s `exists` is injected), and deliberately NOT collapsed into one:
      - `repo_contained(p)` — LEXICAL: is this path even expressible as a repo path (not absolute,
        no `..` escape)? Answers "may this be authorized at all".
      - `is_dir(p)`        — does it resolve to a DIRECTORY? A bare dir entry authorizes a whole
        subtree, which no card intends.
      - `exists(p)`        — does it resolve? Used ONLY to disambiguate a slash-less token.
    Conflating containment with existence is what makes these rules ambiguous: it cannot separate a
    repo-contained to-be-CREATED file from an out-of-repo scratch name.

    Rejection rules, in order — each maps to one X-0440 over-capture class:
      not repo_contained   -> 'non-repo'            (/tmp/buftest.py — the scratch repro)
      is_dir, not a glob   -> 'bare-directory'      (backend/app, backend/tests — subtree authz)
      no '/', not exists   -> 'unanchored-scratch'  (bare `buftest.py`)

    A to-be-CREATED path (`tests/test_new.py`) is repo_contained, resolves to no directory, and is
    ANCHORED by its `/` — so `exists` is never consulted for it and it is ADMITTED. That is the
    load-bearing asymmetry: existence is NEVER a gate on an anchored path, keeping closed the exact
    false-negative direction T-10545/T-10563 declined this filter for. An explicit glob
    (`backend/app/**`) is an intentional subtree declaration and bypasses the is_dir rule."""
    admitted, rejections = [], []
    for raw in (entries or []):
        e = str(raw).strip()
        if not e:
            continue
        if not repo_contained(e):
            rejections.append((e, "non-repo"))
        elif is_dir(e) and not any(c in e for c in _GLOB_META):
            rejections.append((e, "bare-directory"))
        elif "/" not in e and not exists(e):
            rejections.append((e, "unanchored-scratch"))
        else:
            admitted.append(e)
    return admitted, rejections


def derive_path_tokens(text: str, *, exists=None) -> list:
    """Extract path-shaped FILE tokens from free text — the ONE home of the touch-derivation
    extraction (CHARTER §P5), used by BOTH the leg-2 dispatch advisor (journal._derive_card_touch —
    deriving low-confidence candidates from a card's title+scope) and the leg-3 Stage-1 write-back
    (task.cmd_task_analyze — reading the smallest-concrete-edit files the analysis names, and scoring
    the leg-2 guess against them). Normalizes each token to its FILE part (drops a `#symbol` anchor,
    mirroring anchor_file), de-dupes, returns sorted.

    `exists` (T-10563, the X-0410 half T-10545 declined) — an OPTIONAL caller-injected predicate
    `(path: str) -> bool`. When given, it WIDENS the result: a slash-bearing token that carries NO
    letter-extension (`backend/Dockerfile`) is admitted IFF it RESOLVES. It is NEVER a FILTER — a
    shape-admitted (extension-bearing) token is admitted on shape alone and `exists` is not even
    consulted for it, so a to-be-CREATED path (`tests/test_new.py`, which expected_touch legitimately
    names) can never be dropped. That one-way direction IS the contract: T-10545 declined the literal
    existence GATE precisely because it would introduce that false negative. Free corroboration, not
    a second mechanism: a version tuple (`1.43.46/1.43.48`) is extension-less by the letter rule, so
    it reaches the widener and fails to resolve → still dropped.

    INJECTED, never imported: this module is the identity-agnostic kernel leaf (SPEC-0073 HARD) and
    holds no REPO_ROOT / fs coupling — the caller owns the root and hands in the predicate, exactly as
    `die` is injected into as_list/parse_probe/scaffold_substitute. Default `exists=None` → no widener,
    byte-identical to the pre-T-10563 behaviour. Pure f(text) when `exists` is None; otherwise as pure
    as the predicate handed in."""
    out, seen = [], set()
    for m in _PATH_TOKEN_RE.finditer(str(text or "")):
        path = m.group(0).split("#", 1)[0]
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    if exists is not None:
        # WIDENER pass (never a filter): only tokens the shape pass did NOT already admit are offered
        # to the predicate, so no shape-admitted path can be revoked by a failing existence check.
        for m in _PATH_LIKE_RE.finditer(str(text or "")):
            path = m.group(0).split("#", 1)[0]
            if path and path not in seen and exists(path):
                seen.add(path)
                out.append(path)
    return sorted(out)


# --- argv rides the shell: the prose-bearing-flag substrate (E-0054) -------------------------------
# The three helpers below are the SHARED core of the two-part mitigation T-10547/T-10437 first shipped
# for `task file`, relocated here (T-10719) when `cross request` became its second consumer. They live
# in this pure-text leaf rather than in either verb module because they are PURE (no I/O, no shell, no
# host coupling) and now serve >1 verb — a second copy in cross.py would be the parallel path CHARTER
# §P5 forbids. Every task.py NAME is preserved as a thin delegation, so no caller changed.


# An INTERNAL run of 2+ HORIZONTAL SPACES between two non-space chars, where the char before it is
# not sentence punctuation. Horizontal-only is load-bearing (T-10547 audit-pre p2 F1): `\s{2,}` would
# also match a newline + YAML indentation, false-WARNing on ordinary multiline prose. An eaten span
# always leaves its gap on ONE line, so staying horizontal loses no real signal. The lookbehind
# independently excludes the "word\n  next" case (the char before the indent run is the newline).
#
# The exclusion set is `.!?:` — the punctuation a writer legitimately double-spaces after (T-11199):
#   `.` `!` `?`  the double-space-after-sentence convention;
#   `:`          the label/definition shape ("One:  two.", "probe:  green").
# `;` was dropped from that set (T-11199 / X-0948): it is NOT a sentence terminator and no typographic
# convention double-spaces after it, so excluding it only blinded the detector — kupiclub's REAL damage
# ("rather than a tab;" + eaten span + " is described as an address") sat exactly there and shipped
# silently. The four that REMAIN are a KNOWN, DELIBERATE blind spot, not an oversight: an eaten span
# after `.` `!` `?` or `:` is indistinguishable at the character level from a legitimate double space,
# so the claim is NARROWED rather than the guard traded for the false positives it was built to stop.
#
# The gap is SPACES ONLY — the `\t` arm was removed (T-11199). Residue is the literal characters the
# author typed either side of the backticks, and those are spaces; a tab is indentation or column
# layout, never substitution residue. Keeping `\t` would also have been DEAD: LAYOUT_RUN_RE below reads
# any tab on the line as layout, so a tab-bearing gap would suppress itself while the source still
# advertised the branch (audit-pre p1 finding, T-11199).
EATEN_SPAN_GAP_RE = re.compile(r"(?<=[^\s.!?:])[ ]{2,}(?=\S)")

# COLUMN-ALIGNMENT residue, which is NOT eaten-span residue (T-11199 / X-0947). An eaten span leaves
# the one space before the backtick plus the one after it. Alignment instead PADS to a width, so it
# leaves a wider run — and it leaves that run on a line laid out as columns. So a line carrying a
# padding run (3+ spaces, or any tab) is LAYOUT, and no gap on it is read as residue.
#
# Grounds: kupiclub's INTACT brief embedded a three-row aligned table ("kupiclub    55 throwaway ...")
# and the WARN fired on it six times. They byte-compared the stored item against its source to prove
# the guard wrong — the exact cost the X-0599 erosion class predicts, and the reason this narrows
# rather than silences. (Their reported cause, an apostrophe, was NOT it: reproduction put all six
# matches inside the table's padding.) This suppresses the whole LINE, not just wide gaps: the table
# also carried a genuinely 2-space gap (",  10 exec") whose line is unambiguously layout.
#
# KNOWN LIMIT this buys, stated rather than hidden: two eaten spans landing ADJACENT ("the `a` `b`
# verb" -> "the   verb") leave a 3-space run and now read as layout. SEPARATED spans still fire.
LAYOUT_RUN_RE = re.compile(r"[ ]{3,}|\t")

# ALIGNMENT IS A PROPERTY OF A BLOCK, AND THE RUN ABOVE IS READ PER LINE — the gap that closes
# (T-11933 / X-1205). A table padded to a common width gives its NARROWER rows a 3+ run, which
# LAYOUT_RUN_RE catches, but its WIDEST row is padded to exactly the separator minimum, so that one row
# carries a 2-space gap and nothing on its own line vouches for it. Measured on kupiclub's reported
# shape — a churn table in a commit body — one row of three fired while the other two were suppressed:
#     scripts/deploy-lib.sh   27 (0)     <- 3-space pad, layout
#     scripts/check-stack.sh  12 (3)     <- 2-space pad, FIRED
#     compose.yml             4 (1)      <- wide pad, layout
# Widening LAYOUT_RUN_RE to 2 would silence X-0948's damage verbatim, so the fix is to widen the
# WINDOW instead of the run: a gap is also layout when an ADJACENT non-blank line carries a LAYOUT run
# ENDING at the same column. End-column is the alignment invariant of a left-aligned table — rows pad
# to a common width, so their runs START at different columns and END at the same one.
#
# The voucher must itself be a LAYOUT run (3+ spaces or a tab), never any 2-space run. If a bare
# 2-space run could vouch, the prose pair "the phase ended.  next" above "rather than a tab;  is
# described" would silence each other and re-open X-0948 — the exact false negative T-11199 closed.


def _layout_run_end_cols(line: str) -> set:
    """The end COLUMNS of every LAYOUT run on one line — what an adjacent row pads to (T-11933).

    Columns, not offsets: the caller compares against a gap's end measured from ITS own line start.
    """
    return {m.end() for m in LAYOUT_RUN_RE.finditer(line)}


def _eaten_span_hit(text: str):
    """The first gap in `text` that reads as eaten-span residue, or None (T-11199, T-11933).

    A match on a COLUMN-ALIGNED line is skipped — see LAYOUT_RUN_RE. Alignment is judged over the
    line AND its two neighbours (T-11933): a table's widest row has no wide run of its own, so the
    per-line reading alone false-fires on it. The clauses live together here (rather than as one
    unreadable regex) because they are one rule: residue is a narrow gap on a PROSE line. Pure, like
    everything else in this module.
    """
    lines = text.split("\n")
    bols, off = [], 0
    for one in lines:
        bols.append(off)
        off += len(one) + 1
    idx = 0
    for hit in EATEN_SPAN_GAP_RE.finditer(text):
        while idx + 1 < len(bols) and bols[idx + 1] <= hit.start():
            idx += 1                     # matches arrive in order, so the line cursor only moves forward
        line = lines[idx]
        if LAYOUT_RUN_RE.search(line):
            continue                     # column layout, not residue
        end_col = hit.end() - bols[idx]
        if any(end_col in _layout_run_end_cols(lines[j])
               for j in (idx - 1, idx + 1) if 0 <= j < len(lines)):
            continue                     # an adjacent row pads to this same column — this is a table
        return hit
    return None


def shell_substitution_findings(fields, *, from_stdin=None, argv=None) -> list:
    """Report-only: which prose fields carry the residue of a shell-eaten `...` span (T-10547).

    `fields` is an ordered mapping {field_name: iterable-of-values} — the CALLER names its own prose
    fields (`task file`: title/scope/acceptance; `cross request`: brief), so one detector serves every
    verb without knowing any verb's schema. Returns a list of (field, excerpt); empty when nothing
    looks eaten. Pure: no I/O, no shell. Id-shaped fields carry no prose and are never passed in.

    Observed in a real shell — the cases this must and must not fire on:
        "run the `echo` verb now"   -> "run the  verb now"    <- the eaten span leaves SPACES
        'run the `land` verb now'   -> intact                 <- single-quoted: quoting held
        "run the `echo hi` verb"    -> "run the hi verb"       <- BLIND SPOT: output splices in cleanly
    So the backticks are GONE in the damaged case (matching on backticks would flag the SAFE case), and
    the only residue of an empty-output span is the horizontal gap it left. The last line is
    undetectable by construction — hence a report-only WARN that DISCLAIMS it, never a guarantee.

    WHAT THIS DOES *NOT* CATCH — the honest bound, and it is longer than one line (T-11199). Three
    named blind spots, all deliberate, all pinned by tests so silence is never read as coverage:
      (a) a substitution that PRINTED output (above) — no residue exists at all;
      (b) a span after `.` `!` `?` or `:` — the double-space-after-sentence and label shapes are
          character-for-character identical to residue there, so those stay excluded. `;` is NOT in
          that company and was removed from the exclusion set: it terminates no sentence and no
          convention double-spaces after it, and kupiclub's real damage (X-0948) landed exactly
          there and shipped silently. Fix what is provable; narrow the CLAIM for the rest;
      (c) residue that reads as COLUMN PADDING (LAYOUT_RUN_RE), which is two shapes, not one:
          two eaten spans landing ADJACENT leave a combined 3-space run on their own line; and — since
          T-11933 — a gap whose end column matches a LAYOUT run on the line directly above or below it,
          which is what a table's widest row looks like. The second is the price of not false-firing on
          every aligned table (X-1205): a genuine span on a prose line that happens to end where a
          neighbouring line's 3+ run ends is now silent. Separated spans on unaligned prose still fire.
    A guard whose advertised reach exceeds its real reach teaches the same skimming as one that cries
    wolf, so the bound is stated here rather than discovered later.

    PATH-AWARE (T-10769): the residue above is a question about the ARGV route ONLY — it asks what the
    SHELL did between the author's keystrokes and argv. On the `--from-stdin` route there is no shell in
    that position (the field arrives as a YAML mapping on a pipe), which is precisely the escape THIS
    WARN's own text prescribes — so a finding there can only be a FALSE POSITIVE, and the WARN was
    firing at the safe path it recommends (fingerprint backtick-warn-false-fires-on-the-shell-proof-
    from-stdin-path). A guard that cries wolf on correct usage teaches the reader to skim it, so the one
    real hazard gets skimmed with the noise (the X-0599 erosion class). Hence: silent on --from-stdin,
    UNCHANGED on argv. Both halves are load-bearing — silencing it everywhere would be worse than the
    defect, because a silenced guard reads as a passing guard.

    `from_stdin` defaults to None = DERIVE the route from argv presence of `--from-stdin`
    (`flag_in_argv`), the same signal T-10437 already trusts for the conflict refusal. Argv-presence is
    faithful for all four consumers: `task file` / `task close --from-stdin` read the WHOLE field set
    from the stdin mapping, and `cross request` / the commit core read their one prose field from it —
    so the flag being on argv means every field passed here came off the pipe. Deriving it here rather
    than at the four call sites keeps ONE home for the rule (CHARTER §P5): the commit core does not even
    carry its caller's Namespace. Pass `from_stdin` explicitly to state the route (a programmatic caller
    with no argv), and `argv` to inject one in tests. FAIL DIRECTION: an unknowable route reads as argv,
    so the guard errs toward FIRING, never toward silence.
    """
    if from_stdin is None:
        from_stdin = flag_in_argv("--from-stdin", argv)
    if from_stdin:
        return []
    findings = []
    for field, values in (fields or {}).items():
        for value in (values or ()):
            if value is None:
                continue
            text = str(value)
            hit = _eaten_span_hit(text)
            if hit:
                lo, hi = max(0, hit.start() - 25), min(len(text), hit.end() + 25)
                findings.append((field, text[lo:hi]))
            elif "``" in text:      # an empty inline-code run: the span's content vanished
                findings.append((field, text[:60]))
    return findings


def flag_in_argv(flag: str, argv=None) -> bool:
    """Was `flag` EXPLICITLY passed on the command line (`--flag` or `--flag=value`)?

    The PRIMARY conflict signal (T-10437, audit-pre pass-1): a value-vs-default comparison alone
    cannot distinguish "flag absent" from "flag explicitly passed WITH the default value" — so
    `--status ready` / `--created-by ai-agent` / `--effort-tier normal` would slip through it. Argv
    presence is true regardless of the value. `argv` is injectable so the check is testable.
    """
    argv = sys.argv if argv is None else argv
    return any(a == flag or a.startswith(flag + "=") for a in argv)


def stdin_argv_flag_conflicts(args, table, argv=None) -> list:
    """The (cli_flag, stdin_key) pairs a --from-stdin caller ALSO passed on argv (T-10437).

    `table` is the CALLER's own tuple of (attr, cli_flag, stdin_key, absent_value) rows — every
    CONTENT-bearing flag of that verb; MODE flags (--from-stdin / --skeleton / --force) carry no
    content and are excluded by the caller. Two-signal, refuse if EITHER fires: (a) explicit argv
    presence (above); (b) the Namespace value differs from the flag's argparse-absent value — which
    covers a programmatic caller that builds a Namespace directly, with no argv. getattr-defaulted so
    a hand-built Namespace that omits the newest flag stays valid (the T-0404 pattern).
    """
    conflicts = []
    for attr, flag, stdin_key, absent in table:
        if flag_in_argv(flag, argv) or getattr(args, attr, absent) != absent:
            conflicts.append((flag, stdin_key))
    return conflicts


def classify_stdin_keys(fields, ingested, argv_dests) -> tuple[list, list]:
    """Split a `--from-stdin` mapping's top-level keys into (argv_only, unknown).

    T-11873 — the hoist of `task update`'s private `_classify_update_stdin_keys` (T-11742 / X-1157),
    which was the ONLY caller of the shared ingest that classified at all. Every other caller took the
    mapping bare, so a key the verb does not read was DROPPED IN SILENCE at exit 0 — and where the same
    mapping also carried a recognised field, the verb wrote that one and the caller read the exit 0 as
    "all of it applied". One classifier, one home, beside the ingest that drives it.

    Pure — no I/O, no exit, no `args` mutation: `stdin_mapping_ingest` owns the refusal, matching the
    posture the original carried (a leaf that classifies must not become a second, weaker validator).
    A key in `ingested` is honoured by the caller's fold-back and reported in neither list. Both
    returned lists are sorted, so a refusal names every offending key once, in a stable order, rather
    than one key per run.

    BOTH memberships are the CALLER's to DERIVE, never to hand-list (CHARTER §P5; the anti-pattern in
    lessons/a-widening-log-means-invert-the-whitelist.md is a kernel-owned whitelist that can only ever
    be behind): `ingested` is the constant that already drives that verb's fold-back, and `argv_dests`
    is the argparse Namespace's own dests, which IS the set the verb accepts on argv. A flag added to
    a verb tomorrow is classified correctly with no change here.
    """
    argv_only, unknown = [], []
    for key in fields:
        if key in ingested:
            continue
        (argv_only if key in argv_dests else unknown).append(key)
    return sorted(argv_only), sorted(unknown)


def stdin_mapping_ingest(args, table, *, stdin_text, die, carries="the field set", argv=None,
                         recognised=None, argv_dests=None, verb=None) -> dict:
    """The whole `--from-stdin` INGEST step: refuse argv conflicts, parse the mapping, return it.

    T-10720 (E-0054). `task file` and `cross request` each hand-rolled this identical
    refuse→parse→shape-check block; the THIRD and FOURTH consumers (`task commit` / `work commit`)
    would have made four copies of a paragraph whose refusal wording must not drift, so the block
    lands here beside the two helpers it composes. `carries` names — in the refusal text — what the
    stdin mapping holds for THIS verb (`task file`: "the WHOLE field set"; the commit verbs: "the
    commit message"), which is the only per-verb variation the message had.

    Pure by the same contract as its neighbours: the caller reads stdin and injects the text, and
    `die` is injected (this leaf never exits the process, SPEC-0073 HARD). Returns the parsed mapping
    ({} for an empty document); `die` is called — never returns — on a conflict, a YAML parse error,
    a non-mapping document, or (when `recognised` is given) an unrecognised / argv-only key.

    T-11873 — `recognised` / `argv_dests` / `verb` are the OPTIONAL classification triple. Give
    `recognised` the constant that drives THIS verb's fold-back and `argv_dests` the Namespace's own
    dests (`set(vars(args))`) and a key the verb does not read is REFUSED here, naming it, instead of
    dropped in silence. Omit them and the behaviour is exactly what it was before — the escape hatch
    `task file` uses, since its own 3-bucket classifier already covers the same ground with a
    deliberate passthrough this must not overrule. `carries` doubles as the refusal's description of
    what the mapping legitimately holds, so no verb needs a second copy of that sentence.
    """
    conflicts = stdin_argv_flag_conflicts(args, table, argv)
    if conflicts:
        flags = ", ".join(f for f, _ in conflicts)
        keys = ", ".join(sorted({k for _, k in conflicts}))
        die(f"--from-stdin carries {carries} in the stdin YAML — do not also pass {flags}. Move it "
            f"into the stdin mapping (key(s): {keys}), or drop --from-stdin and pass it on argv.")
    try:
        fields = state.load_str(stdin_text) or {}
    except Exception as e:                       # noqa: BLE001 — any YAML parse failure
        die(f"stdin YAML parse error: {e}")
    if not isinstance(fields, dict):
        die("stdin must be a YAML mapping")
    # T-11873: the UNRECOGNISED-KEY classification, run here so EVERY caller of this ingest gets it
    # rather than only the one verb that grew it (T-11742 / X-1157). OPT-IN by `recognised`: absent
    # means the pre-T-11873 behaviour EXACTLY, which is what leaves `task file` — whose own 3-bucket
    # classifier and deliberate unknown-key PASSTHROUGH are a richer contract this must not overrule —
    # untouched. REFUSAL, not a WARN, and BEFORE the caller's fold-back, so no verb can write half a
    # mapping and exit 0 while the caller reads that as "the edit applied".
    if recognised is not None:
        argv_only, unknown = classify_stdin_keys(fields, frozenset(recognised), set(argv_dests or ()))
        who = f"`{verb}`" if verb else "this verb"
        # UNKNOWN first: a key naming no input at all is the sharper end (the typo class) and the
        # likelier author error, so it is the one a mixed mapping should be told about.
        if unknown:
            die(f"stdin carries key(s) {who} does not read: " + ", ".join(unknown)
                + f" — refusing before any write (T-11742/T-11873). The stdin mapping carries "
                  f"{carries}; check the spelling against `--help`. An unrecognised key used to be "
                  f"dropped in SILENCE at exit 0 while a recognised key in the SAME mapping WAS "
                  f"written (X-1157) — leaving the caller reading that exit 0 as 'all of it applied'.")
        if argv_only:
            die(f"stdin carries key(s) {who} reads from ARGV, not from the stdin mapping: "
                + ", ".join(argv_only)
                + f" — refusing before any write (T-11742/T-11873). The stdin mapping carries "
                  f"{carries}; these are flags and keep working ALONGSIDE --from-stdin, so pass them "
                  f"on the command line (`--help`). Sending one via stdin used to drop it in SILENCE "
                  f"at exit 0, which reads as 'the edit applied' (X-1157).")
    return fields


def git_unquote_path(raw) -> str:
    """T-11772 (kupiclub X-1148) — decode git's QUOTED path form, so a caller reads the path git
    actually means. With `core.quotepath` at its DEFAULT, git wraps any path holding non-ASCII (or
    otherwise special) bytes in double quotes and C-escapes them, e.g. `"bin/\\321\\204.py"` in a
    `--name-only` listing and `diff --git "a/\\321\\204.py" "b/\\321\\204.py"` in a diff header. Such
    a string matches no glob and no forecast entry.

    Why HERE and not `-c core.quotepath=false` on the git calls: that flag un-quotes only the
    non-ASCII case — git still quotes a path containing a double quote, a backslash or a control
    byte — so it would leave the same shape for a narrower input class, and it would have to be
    remembered at every future call site. Decoding at the point of READING covers the whole quoted
    vocabulary with one mechanism (CHARTER §P1).

    IDENTITY ON ANYTHING ELSE, and that is load-bearing: an unquoted path is returned byte-identical
    (so paths that were never quoted behave exactly as before), and any decode failure returns the
    ORIGINAL string rather than a guess — a malformed input can never crash a caller nor silently
    become a DIFFERENT path than the one git named.

    HOMED HERE (T-11999), moved verbatim out of `worktree.py`, because it has a SECOND reader: the
    work-batch carrier gate that birthed it (`worktree._work_batch_product_paths`, which keeps its
    `_git_unquote_path` name as a re-export) and the audit packet's diff readers
    (`audit._diff_segment_path`, `task._task_diff_files`) — where an undecoded Cyrillic path was
    counted BOTH as declared-not-audited and, in its escaped form, as audited-not-declared (X-1237).
    One decoder, not two (CHARTER §P5)."""
    p = str(raw)
    if len(p) < 2 or not (p.startswith('"') and p.endswith('"')):
        return p
    try:
        return p[1:-1].encode("latin-1").decode("unicode_escape").encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return p


def git_porcelain_paths(stdout) -> list:
    """T-12014 — the paths a `git status --porcelain` (v1) listing NAMES, decoded. The LIST sibling of
    `git_unquote_path` above, built ON it: this is not a second decoder, it is the one decoder applied
    to the one line shape every porcelain reader in the kernel had been re-slicing by hand.

    THE LINE SHAPE, stated once here instead of at each caller: porcelain v1 prints `XY<space>PATH`,
    so the path is `ln[3:]` — NEVER `ln.strip().split()`, which eats the leading status-column space of
    an unmodified-index line and mis-slices (`" M events.jsonl"` → `"vents.jsonl"`), and never
    `.split()`, which shatters a path holding a space. A rename/copy prints `OLD -> NEW`; the
    DESTINATION is what a `git add -A` would stage, so that is the side returned. Each path is then run
    through `git_unquote_path`, because `core.quotepath` quotes a status path exactly as it quotes a
    `--name-only` one — an escaped `"tasks/\321\204.yaml"` matches no allow-list entry, no glob and no
    forecast entry, so the reader silently drops it (or, where two sides are compared, counts it twice).

    WHY IT LIVES HERE (CHARTER §P1 F1/F3). The slice-plus-rename idiom above was copy-pasted at eight
    call sites across `task.py` / `worktree.py` / `cli.py` — one of which documented the duplication in
    its own comment («mirrors line ~2738») rather than removing it. Homing it beside the decoder it
    delegates to gives the two halves of "read a path out of git" ONE home, so a future quoting fix
    lands in one place. Adding a `-c core.quotepath=off` flag instead was rejected at this card's
    Analysis: there is no single git wrapper to hang it on (several modules define local `_git`
    subprocess helpers), so it would decode some readers and leave others escaped — a parallel path
    (§P5) — over a NARROWER input class than the decoder covers.

    PURE, and total: no git, no I/O, never raises. `None` / an empty listing yields `[]`; blank lines
    and a line with no path are skipped; order is the listing's. ASCII is unaffected by construction —
    `git_unquote_path` returns an unquoted path byte-identically."""
    out: list = []
    for ln in str(stdout or "").splitlines():
        if not ln.strip():
            continue
        p = ln[3:]
        if " -> " in p:                          # rename/copy: the staged DESTINATION is what lands
            p = p.split(" -> ", 1)[1]
        p = git_unquote_path(p.strip()).strip()
        if p:
            out.append(p)
    return out


def git_porcelain_path_statuses(stdout) -> dict:
    """T-12371 — the STATUS-BEARING sibling of `git_porcelain_paths` above: `{path: "XY"}` over the
    same `git status --porcelain` (v1) listing, keyed by the same decoded paths that reader returns.

    WHY IT EXISTS. `git_porcelain_paths` slices `ln[3:]` and throws the two status columns away, so
    every caller built on it can see THAT a path is dirty and never HOW. `_red_fix_authored_paths`
    (the `--fix-red` door) is one of those callers, and the one where the missing letters cost
    something measurable: it called a path the staged set only DELETES "authored content", while the
    audit-post subject guard `_bookkeeping_commit_authored_paths` — reading the resulting commit's
    own `--name-status` — reads a pure `D` as carrying nothing (T-11668). Custody could therefore be
    re-pinned by the door onto a commit no audit form would take (T-12345 / e086597).

    NOT A SECOND DECODER (CHARTER §P1 F1/F5). The line shape, the `ln[3:]` slice, the rename
    DESTINATION rule and the `core.quotepath` decode are the ONES stated and implemented in
    `git_porcelain_paths`; this function is that function with the prefix KEPT, so a future quoting
    or slicing fix still lands in one place. The keys are IDENTICAL to `git_porcelain_paths`' list by
    construction — a caller may filter one by the other without a second notion of "which path".

    THE PREFIX IS RETURNED RAW, two characters wide, blanks included (`" D"`, `"D "`, `"DM"`) —
    interpretation belongs to the reader, not here. A line shorter than its prefix, or one that
    decodes to no path, is skipped exactly as the sibling skips it. On a DUPLICATE path (a porcelain
    listing should not produce one, but an unmerged entry can be printed more than once) the LAST
    occurrence wins, which is the state git reports most recently.

    PURE, and total: no git, no I/O, never raises. `None` / an empty listing yields `{}`; order is
    irrelevant to a mapping. ASCII is unaffected by construction, as in the sibling."""
    out: dict = {}
    for ln in str(stdout or "").splitlines():
        if not ln.strip():
            continue
        status = ln[:2]
        p = ln[3:]
        if " -> " in p:                          # rename/copy: the staged DESTINATION is what lands
            p = p.split(" -> ", 1)[1]
        p = git_unquote_path(p.strip()).strip()
        if p:
            out[p] = status
    return out
