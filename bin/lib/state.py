"""Shared YAML state load/save layer for the yitc-v2 CLI — the CHARTER §P5 "one parser library".

This is the single home for the canonical YAML parse/serialize primitives + the interpreter-shared
memo caches that bin/yitc-v2 previously hand-rolled inline at dozens of raw `yaml.safe_load` /
`yaml.dump` call-sites. bin/yitc-v2 imports these and re-binds them under their historical names
(`_read_yaml`, `_dump_state_yaml`, …) so every existing caller keeps working unchanged.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It holds NO
REPO_ROOT coupling: the error-relativization root is passed in as `rel_root` by the caller, so a
`-C` rebind in the host CLI is honored automatically (the caller reads the current REPO_ROOT and
passes it at call time). Behaviour is byte-identical to the inline originals (T-0274 fast loader,
T-0359 corpus-tree memo, T-0127 block-style state dumper) — the test suite is the oracle.
"""
from __future__ import annotations

import copy
import json
import time as _time
import os
import re
import sys
import types
from pathlib import Path

_YAML_FAST_LOADER = None


# ── T-12034 — the PROCESS-SCOPED card-read counter (SPEC-0190 / SPEC-0161 / SPEC-0025) ────────────
#
# The card-corpus twin of `journal._READ_COUNTERS`, and it lives HERE rather than beside its sibling
# for one structural reason: `lib.journal` imports `lib.state`, so a `load_path` call into journal
# would invert that edge and create an import cycle. This module imports nothing of ours and must
# keep it that way (it is the identity-agnostic kernel parser layer). `cli._emit_cli_invoked` merges
# `journal.read_counters()` with `state.read_counters()` into the one `cli_invoked.reads` payload —
# two accessors, one row, no new dependency.
#
# WHAT IS COUNTED: a PHYSICAL parse of a task card (`tasks/T-*.yaml`) — a cache MISS. The T-0359
# mtime-keyed memo HIT is deliberately NOT counted. The counter is a physical-primitive counter (a
# memo hit costs no parse), and counting hits would inflate the numerator against a denominator of
# real cards, so the very collapse T-12029 shipped would read as amplification. Measured: engine
# `debt` = 10,463 yaml loads over 3,319 cards.
#
# WHY THIS IS THE ONLY SITE: `load_path` is ALREADY the single canonical reader every `_read_yaml`
# routes through (CHARTER §P5, T-9207), so instrumenting it is a view over an existing chokepoint,
# not a new one. The card readers that still spelled their own parse over a whole-corpus glob were
# re-pointed here by this same card; the remainder are single-card point reads by id, recorded with
# that reason in the committed census allowlist.
_READ_COUNTERS = {"cards_parsed": 0, "wall_ms": 0.0}


def _is_task_card(path) -> bool:
    """True iff `path` is a task card — `tasks/T-*.yaml`.

    Both halves are required: the `T-` stem alone would admit a `T-*.yaml` sitting anywhere, and the
    `tasks/` parent alone would admit the directory's non-card residue. This is the same
    `tasks` + `T-*.yaml` shape every card glob in the corpus uses."""
    try:
        return (path.parent.name == "tasks" and path.name.startswith("T-")
                and path.suffix == ".yaml")
    except AttributeError:
        return False


def note_card_parsed(secs: float = 0.0) -> None:
    """Record ONE physical parse of a task card."""
    _READ_COUNTERS["cards_parsed"] += 1
    _READ_COUNTERS["wall_ms"] += secs * 1000.0


def read_counters() -> dict:
    """A SNAPSHOT of the card-side counters — a copy, so the emit site cannot mutate them."""
    return dict(_READ_COUNTERS)


def reset_read_counters() -> None:
    """Zero the counters. For TESTS ONLY (a CLI process reads and exits); see the journal twin."""
    _READ_COUNTERS.update({"cards_parsed": 0, "wall_ms": 0.0})


def yaml_loader():
    """Fastest available SafeLoader: libyaml `CSafeLoader` when built, else pure-python `SafeLoader`
    (T-0274). ~13x faster on the ~960-file graph walk; behaviour-identical — same safe schema, same
    `yaml.YAMLError` on malformed input, identical parsed objects. Memoized — the import + attribute
    lookup resolve once per process."""
    global _YAML_FAST_LOADER
    if _YAML_FAST_LOADER is None:
        import yaml
        _YAML_FAST_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    return _YAML_FAST_LOADER


def shared_cache(name: str) -> dict:
    """Interpreter-shared memo dicts (T-0359). Storage is a synthetic registry entry in `sys.modules`
    (stdlib-blessed interpreter-global dict), NOT a module global: the test suite loads `bin/yitc-v2`
    once per test FILE via SourceFileLoader (each gets a fresh module object), so a module-global cache
    would re-pay the same work once per file. One-shot CLI behavior is identical."""
    reg = sys.modules.get("_yitc_v2_shared_cache")
    if reg is None:
        reg = types.ModuleType("_yitc_v2_shared_cache")
        reg.caches = {}
        sys.modules["_yitc_v2_shared_cache"] = reg
    return reg.caches.setdefault(name, {})


def yaml_tree_cache() -> dict:
    """The `yaml_trees` lane of `shared_cache` (T-0365) — parsed trees of corpus `.yaml` reads. The
    JSON graph index does NOT use this lane (its json.loads parse is cheaper than a deepcopy hit)."""
    return shared_cache("yaml_trees")


def is_git_hexsha(s) -> bool:
    """True iff `s` is a real 40-hex git object id — the binary guard that keys the shared `drift`
    memo lane (T-0359): only content-addressed ids are stale-proof."""
    return isinstance(s, str) and len(s) == 40 and all(c in "0123456789abcdef" for c in s)


def _err_relpath(path: Path, rel_root) -> str:
    """Path string for an error record, relativized to rel_root (REPO_ROOT) exactly as the inline
    original did (`str(path.relative_to(REPO_ROOT))`). rel_root=None → the absolute path string.

    T-10842: a path OUTSIDE rel_root falls back to the absolute string instead of raising. `relative_to`
    raises ValueError when the path is not under rel_root, which put a THROW on the error-REPORTING path
    — the channel could crash at the exact moment it is meant to report, turning one corrupt file into a
    whole-verb traceback. Latent while every reader stayed under REPO_ROOT; reachable as soon as the
    channel is connected at a sweep run over an out-of-tree corpus (a test sandbox, or any future
    caller). In-tree behaviour is UNCHANGED — the relative form is still returned whenever it exists."""
    if rel_root is None:
        return str(path)
    try:
        return str(path.relative_to(rel_root))
    except ValueError:
        return str(path)


def load_str(text: str):
    """Parse YAML from a STRING via the fast safe loader — a FAITHFUL drop-in for
    `yaml.safe_load(<text>)`: it RAISES `yaml.YAMLError` on malformed input (it does NOT swallow) and
    returns the parsed object (which may be None for empty input). The single replacement for the raw
    `yaml.safe_load(<str>)` / `yaml.load(<str>, Loader=…)` sites that parse stdin / a slice / an
    already-generated buffer; each call-site keeps its own trailing `or {}` exactly as before."""
    import yaml
    return yaml.load(text, Loader=yaml_loader())


def load_path(path: Path, errors: list | None = None, rel_root=None):
    """Read a YAML file (or the `.json` graph index); return parsed mapping or {} on error. The
    canonical reader (ex-`_read_yaml`). `.json` dispatch (T-0365): the DERIVED graph index is JSON,
    parsed with json.loads, NOT memoized. YAML path uses the libyaml fast loader (T-0274). Corpus-tree
    memo (T-0359): `.yaml` parses are memoized keyed by (absolute path, st_mtime_ns, st_size) — a HIT
    returns a `copy.deepcopy` of the cached tree; any rewrite misses the key. Only successful parses
    are cached. If `errors` is provided, append a {path, error} record on parse error instead of
    silently swallowing (T-0021); `rel_root` relativizes the recorded path (the caller passes the
    current REPO_ROOT, honoring a `-C` rebind)."""
    import yaml
    if path.suffix == ".json":
        try:
            return json.loads(path.read_text(encoding="utf-8")) or {}
        except ValueError as e:
            if errors is not None:
                errors.append({"path": _err_relpath(path, rel_root), "error": str(e)[:300]})
            return {}
    cacheable = path.suffix == ".yaml"
    if cacheable:
        try:
            st = os.stat(path)
            key = (str(path.resolve()), st.st_mtime_ns, st.st_size)
        except OSError:
            key = None
        if key is not None:
            cache = yaml_tree_cache()
            hit = cache.get(key)
            if hit is not None:
                return copy.deepcopy(hit)
    # T-12034: the card-parse counter site. Below the memo lookup on purpose — this counts PHYSICAL
    # parses (misses), never hits (see the `_READ_COUNTERS` block above for why).
    _t0 = _time.monotonic()
    try:
        parsed = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml_loader()) or {}
    except yaml.YAMLError as e:
        if errors is not None:
            errors.append({"path": _err_relpath(path, rel_root), "error": str(e)[:300]})
        return {}
    if cacheable and _is_task_card(path):
        note_card_parsed(_time.monotonic() - _t0)
    if cacheable and key is not None:
        cache = yaml_tree_cache()
        for stale in [k for k in cache if k[0] == key[0]]:
            del cache[stale]
        cache[key] = copy.deepcopy(parsed)
    return parsed


#: The task statuses that are TERMINAL — a card in one of these is shipped or abandoned history
#: (QUEUE §State transitions). Named once, here beside the reader, so a view that reports only OPEN
#: work asks the corpus the same question everywhere (the `_terminal_task_closures` reader in `cli`
#: already spells exactly this pair; this is that pair given a name the card-set filter can share).
TERMINAL_CARD_STATUSES = frozenset({"done", "wont-do"})


def card_status(path: Path) -> str:
    """The `status:` of the card at `path` — SERVED FROM THE SAME MEMO `load_path` fills, with no
    per-call deepcopy. `""` when absent, unreadable, or not a string.

    WHY IT EXISTS (T-12030). `load_path`'s T-0359 memo already guarantees ONE parse per card, which
    is what T-12029 bought. What it does not remove is the per-HIT `copy.deepcopy` of the whole
    parsed tree: a view that walks `tasks/` to report the handful of cards in ONE status still
    materialises all 3,319 of them, done cards included. Measured on the engine at session start
    (2026-09-04): 30,368 `load_path` calls, 7.5 s, of which 3.2 s is deepcopy alone.

    IT IS A VIEW OVER THE EXISTING MEMO, NOT A SECOND READER (CHARTER §P1 filter 2 / §P5). There is
    no new cache, no new key and no second parse path: on a miss it fills the memo through
    `load_path` itself, so the corpus is still parsed exactly once and every other caller keeps
    getting the same trees. It returns a `str`, which is immutable — the ONE thing that can be handed
    back out of the cache without the deepcopy that protects every mutable value in it.

    HOW A CALLER USES IT, and the bound that makes the use safe: ask this FIRST, and call `load_path`
    only for the cards whose status the view actually reports on. A view that reports on terminal
    cards too (the not-adopted lens, the overdue-recheck lens, the terminality scan) must keep
    reading the whole corpus — this filter is for the views whose subject is open work, and using it
    anywhere else would narrow an answer rather than a read."""
    if Path(path).suffix != ".yaml":
        return ""
    try:
        st = os.stat(path)
        key = (str(Path(path).resolve()), st.st_mtime_ns, st.st_size)
    except OSError:
        return ""
    hit = yaml_tree_cache().get(key)
    if hit is None:
        load_path(Path(path))                 # fill the ONE memo; never a second parse path
        hit = yaml_tree_cache().get(key)
    if not isinstance(hit, dict):
        return ""
    status = hit.get("status")
    return status.strip() if isinstance(status, str) else ""


def card_is_open(path: Path) -> bool:
    """True iff the card at `path` is NOT terminal — the predicate the open-work card views filter on.

    An unreadable / status-less card reads as OPEN (`""` is not in `TERMINAL_CARD_STATUSES`), which
    is the fail-safe direction for a filter that decides whether a file gets READ: an unknown card is
    handed to the view's own guards exactly as it was before, so no view can lose a row it used to
    report. Only a card PROVABLY terminal is skipped."""
    return card_status(path) not in TERMINAL_CARD_STATUSES


_DUPLICATE_OPS_KEY_ERROR = None


def duplicate_ops_key_error():
    """The exception type `load_ops` / `load_ops_str` raise on a duplicate TOP-LEVEL key (T-10240,
    X-0236). It subclasses `yaml.YAMLError`, so every existing `except yaml.YAMLError` ops-carrier
    handler keeps its fail-closed posture unchanged; a caller wanting a tailored refusal catches
    `state.duplicate_ops_key_error()` ahead of the generic branch. Built lazily — this module keeps
    `yaml` off its import path (the CLI imports state for every verb)."""
    global _DUPLICATE_OPS_KEY_ERROR
    if _DUPLICATE_OPS_KEY_ERROR is None:
        import yaml

        class DuplicateOpsKeyError(yaml.YAMLError):
            """A `yitc-ops.yaml` carrier declares the same top-level key more than once."""

        _DUPLICATE_OPS_KEY_ERROR = DuplicateOpsKeyError
    return _DUPLICATE_OPS_KEY_ERROR


def load_ops_str(text: str):
    """Parse the `yitc-ops.yaml` ops-contract carrier (SPEC-0093) from a STRING — the text-taking
    specialization `load_ops` reads through, and the single parse path for the init call-sites that
    must keep the carrier's TEXT (comment-preserving edits) alongside its parsed form.

    Identical to `load_str` except that a duplicate TOP-LEVEL key RAISES `duplicate_ops_key_error()`
    instead of silently LAST-WINNING (T-10240 / X-0236). The kernel owns the carrier's section SHAPE
    (SPEC-0093 rule 3 — declare-or-waive, fail-closed), so a second `deploy:` block silently erasing
    the first one's declaration defeats the very sweep that reads it. Scope is the top level, where
    the concern sections live; a nested duplicate keeps the plain safe-schema semantics. Single
    parse: the document is composed once, checked, then constructed."""
    import yaml
    loader = yaml_loader()(text)
    try:
        node = loader.get_single_node()
        if node is None:
            return None                                   # empty carrier — `safe_load("")` returns None too
        if isinstance(node, yaml.MappingNode):
            at_lines: dict = {}
            for key_node, _value_node in node.value:
                if isinstance(key_node, yaml.ScalarNode):
                    at_lines.setdefault(key_node.value, []).append(key_node.start_mark.line + 1)
            dups = {k: v for k, v in at_lines.items() if len(v) > 1}
            if dups:
                detail = "; ".join(f"{k!r} (lines {', '.join(str(n) for n in v)})"
                                   for k, v in sorted(dups.items()))
                raise duplicate_ops_key_error()(f"duplicate top-level key(s): {detail}")
        return loader.construct_document(node)
    finally:
        loader.dispose()


def load_ops(ops_path: Path):
    """Read + parse the `yitc-ops.yaml` ops-contract carrier (SPEC-0093), fail-closed. The single
    home for the read+parse idiom the ops consumers (deploy / live_probe / host_apply / init / task)
    each hand-rolled inline as `yaml.safe_load(ops_path.read_text(encoding="utf-8"))`. It reads the
    file and parses via `load_ops_str`, RAISING `yaml.YAMLError` on malformed input — INCLUDING a
    duplicate top-level key (T-10240) — (it does NOT swallow to {} like `load_path`, and does NOT
    memoize — the carrier is re-read after a rewrite, so a stale cache would be wrong), and returns
    the parsed object (None for an empty carrier). The caller resolves the path under REPO_ROOT and
    keeps its OWN existence guard + fail-closed policy (die vs None vs False) — mirroring `load_str`'s
    raise-don't-swallow contract, of which this is the file-reading specialization."""
    return load_ops_str(ops_path.read_text(encoding="utf-8"))


def dump_state(obj) -> str:
    """Single serializer for task-state YAML (T-0127, CHARTER §P5). Preserves LITERAL BLOCK style
    ('|') for multi-line string fields so a lifecycle re-write does not churn them into folded
    scalars. Value-preserving — yaml.safe_load round-trips to the same dict (SPEC-0001)."""
    import yaml

    class _BlockDumper(yaml.SafeDumper):
        pass

    def _str_rep(dumper, data):
        style = "|" if "\n" in data else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)

    _BlockDumper.add_representer(str, _str_rep)
    return yaml.dump(obj, Dumper=_BlockDumper, sort_keys=False, allow_unicode=True,
                     default_flow_style=False)


def dump(obj, sort_keys: bool = False) -> str:
    """Plain YAML serializer (the non-block-style companion of dump_state) — the single home for the
    `yaml.safe_dump(obj, sort_keys=…, allow_unicode=True, default_flow_style=False)` sites (audit
    verdicts, view renders, record writes). `default_flow_style=False` + `allow_unicode=True` are
    fixed (the universal call shape); `sort_keys` is the only varying knob. NOTE: PyYAML defaults
    default_flow_style to False, so a legacy call that omitted it is byte-identical here."""
    import yaml
    return yaml.safe_dump(obj, sort_keys=sort_keys, allow_unicode=True, default_flow_style=False)


# T-11930 — the block-scalar extent, by INDENTATION only. String surgery, the same idiom
# `strip_top_key` below uses: a second (round-trip-safe) YAML parser is what CHARTER §P5 forbids
# and what `dropped_comment_lines` exists to compensate for, so it cannot be the thing that fixes it.
_BLOCK_SCALAR_HEADER = re.compile(
    r"^(?P<indent>[ \t]*)"                                  # leading indentation
    r"(?P<dash>(?:-[ \t]+)*)"                               # optional sequence-item indicator(s)
    r"(?P<key>(?:\"[^\"]*\"|'[^']*'|[^#:'\"][^#:]*):[ \t]*)?"  # optional `key:` (a bare `- |` has none)
    r"[|>][0-9+-]*[ \t]*(?:\#.*)?$"                          # the block indicator, + inline comment
)


def _lines_outside_block_scalars(text: str) -> list:
    """The lines of `text` that are NOT block-scalar CONTENT (T-11930).

    A block scalar's extent is determined by its own indentation, so no parser is needed: content
    runs until the first non-blank line indented no deeper than the scalar's OWN node. Which column
    that is depends on the header shape, and getting it wrong fails in both directions:
      * `key: |` / `  key: |`   -> the node is the KEY, so the threshold is the key's column. A
        sibling key of the same mapping sits AT that column and correctly ENDS the scalar.
      * `- |` (no key)          -> the node is the sequence ITEM, so the threshold is the DASH's
        column; its content is dumped one level deeper. Using the post-dash column here would end
        the scalar on its own first content line.
    Blank lines are content while a scalar is open (they may separate paragraphs of prose) and are
    dropped either way — they carry no comment. The header line itself is OUTSIDE the scalar and is
    kept; it can hold only an INLINE `#`, which this function's caller does not track.
    """
    out: list = []
    threshold = None
    for line in (text or "").splitlines():
        if threshold is not None:
            if not line.strip():
                continue
            if (len(line) - len(line.lstrip())) > threshold:
                continue
            threshold = None
        m = _BLOCK_SCALAR_HEADER.match(line)
        if m:
            threshold = len(m.group("indent"))
            if m.group("key"):
                threshold += len(m.group("dash"))
        out.append(line)
    return out


def dropped_comment_lines(old_text: str, new_text: str) -> list:
    """Which FULL-LINE YAML comments the rewrite `old_text -> new_text` DESTROYS (T-11245).

    `dump_state` is PyYAML, which has no comment model — so any comment in a card is silently gone
    the first time a verb writes the card back (kupiclub X-0982: authored prose vanished on the next
    worker's stage-entry, with no diff, no warning, no gate failing closed). This is the DETECTION
    half of the LOUD-DETECT answer: preserving comments would need a round-trip-safe parser, i.e. a
    second parser path, which CHARTER §P5 forbids outright. Its counterpart is `strip_top_key`, which
    AVOIDS the loss for a keyed block by string surgery; this one REPORTS it for a full round-trip.

    Returns ONE ENTRY PER DROPPED OCCURRENCE, in first-appearance order in `old_text`: each comment
    text is counted in both sides and emitted `old_count - new_count` times, so two identical lost
    comments report twice, never once (audit-pre mode-b absorption).

    BOUND, stated rather than left silent: FULL-LINE comments only (the stripped line starts with
    `#`), and only OUTSIDE a block scalar. An INLINE trailing `# ...` is not separable from a
    `#`-bearing VALUE (`bin/yitc-v2#symbol` anchors are corpus-wide) without a real YAML parser —
    which is the rejected preserve path. A `#` line INSIDE a BLOCK SCALAR is not a comment at all
    but prose (a markdown heading in a spec `body: |`), so `_lines_outside_block_scalars` EXCLUDES
    it from the comparison on both sides (T-11930).

    That exclusion replaces an earlier bound which claimed such a line "appears in both sides and
    never reports, so the comparison makes this free of false positives". That held only while the
    scalar's text was IDENTICAL on both sides — which is exactly what a body rewrite (`spec edit
    --from-file`) changes: a markdown heading whose text moved or changed read as a destroyed YAML
    comment, in the WARN and in the merge resolver's hard refusal alike (X-1213). Comparison alone
    was never the thing making this free of false positives; the exclusion is.
    """
    def _counts(lines):
        out = {}
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                out[stripped] = out.get(stripped, 0) + 1
        return out

    old_lines = _lines_outside_block_scalars(old_text)
    before, after = _counts(old_lines), _counts(_lines_outside_block_scalars(new_text))
    if not before:
        return []
    lost, seen = [], {}
    for line in old_lines:
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        seen[stripped] = seen.get(stripped, 0) + 1
        if seen[stripped] > before[stripped] - after.get(stripped, 0):
            continue
        lost.append(stripped)
    return lost


def strip_top_key(text: str, key: str) -> str:
    """Remove a top-level YAML block `<key>:` plus its indented continuation lines from raw record
    text, preserving every other line/comment verbatim (T-0506). Blank lines are NOT consumed (they
    may separate sections), so only the header + its indented body are dropped. The string-surgery
    counterpart of `dump` — used to REPLACE a machine-managed block without a full yaml round-trip
    (which would strip a spec's human comments). Callers: `_reverify_spec_signature` (writes the
    `implements_signature:` block) and worktree.py's `_merge_spec_signature_conflict` (T-10548 —
    splits a conflict stage into body + keyed block); homed here, the leaf both already import, so
    the surgery rule has ONE source (P5)."""
    lines = text.split("\n")
    out: list = []
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        if ln == f"{key}:" or ln.startswith(f"{key}:"):
            i += 1
            while i < n and lines[i][:1] in (" ", "\t"):   # consume indented continuation only
                i += 1
            continue
        out.append(ln)
        i += 1
    return "\n".join(out)


def scalar(s: str) -> str:
    """Render a string as a YAML-safe inline scalar — single-quote when the plain form would be
    ambiguous (indicator chars or leading/trailing space). Keeps scaffolded titles valid."""
    s = str(s)
    if s == "" or s != s.strip() or re.search(r"""[:#\[\]{}&*!|>'"%@`,]""", s):
        return "'" + s.replace("'", "''") + "'"
    return s


# ── Canonical store scans (T-9208, CHARTER §P5 "one scan per store") ──────────────────────
# The `sorted(<STORE>_DIR.glob("<id-prefix>.yaml" | "*.md"))` traversal idiom was copy-pasted
# ~46x across bin/yitc-v2. Centralized here: ONE sorted+glob core (`_scan`) + one named helper
# per canonical store. The caller passes the CURRENT store-dir global (TASKS_DIR/SPECS_DIR/…),
# so a `-C` rebind (_rebind_root reassigns those globals) is honored automatically — the same
# caller-passes-the-current-root contract used by load_path(rel_root=…). `Path.glob` on a
# missing/non-dir path yields empty, so a `… if DIR.is_dir() else []` guard is result-redundant.
# Byte-identical to the inline idiom: the id-prefix globs still exclude `_template.yaml`.

# ── T-11876 (SPEC-0131 rule 1, second surface) — the CORPUS-scoped redirect pair ────────────────
# The journal has had a scope-guarded low-precedence redirect since T-10073: YITC_EVENTS_PATH_DEFAULT
# (the raw default only) guarded by YITC_EVENTS_GUARD_ROOT (applies ONLY when this process's repo root
# IS the checkout the verify harness is protecting). specs/ and tasks/ had NO equivalent, and that
# absence is what leaves T-11566's AC2 blind: its bound is an AST rule over SOURCE, so a test that
# spawns a `bin/yitc-v2` CHILD reads the corpus in full and the rule cannot see it. An env pair is the
# one carrier that crosses a process boundary, which is exactly why the journal half is one.
#
# THIS IS THE SAME MECHANISM ONE DIRECTORY OVER, deliberately — not a second mechanism with its own
# precedence story. Both halves are load-bearing and neither is optional:
#   • LOW-PRECEDENCE — it redirects the RAW `<root>/specs`|`<root>/tasks` default only. A caller that
#     passes an explicit store dir (every `scan_*` takes one) is untouched, so the ~40 tests that build
#     their own corpus in a tmp dir keep working exactly as they do today.
#   • SCOPE-GUARDED — the redirect applies ONLY when THIS process's root IS the guarded checkout. A
#     test's NESTED CLI subprocess running against its OWN sandbox repo (a different root, via
#     YITC_REPO_ROOT / `-C` / its own bin/ location) is ALREADY isolated, and diverting ITS corpus
#     would make a governed verb read cards that are not the ones it is operating on — the one
#     direction that fails silently and wrongly. Only the guarded checkout's own raw default is moved.
# Production/interactive (both vars unset) = byte-unchanged. Test-harness-only, like its sibling.
#
# FAIL-CLOSED, and the direction is REFUSE-TO-REDIRECT: any half missing, any path unresolvable, any
# OSError -> return `root` untouched. A redirect that cannot be PROVEN to apply does not apply.
def scope_guarded_corpus_root(root, *, default=None, guard=None):
    """The corpus-root a caller should derive `specs/` and `tasks/` from, for `root`.

    Returns `root` unchanged unless BOTH the default and the guard are declared AND `root` IS the
    guarded checkout (compared by realpath, so a symlinked worktree and its target are one checkout).
    `default`/`guard` are read from the environment when not passed — read AT CALL TIME, never
    captured at import, so a test can set or clear the pair without re-importing this module.

    PURE of policy and of I/O beyond the realpath resolution. It decides ONE thing: does the declared
    redirect apply to this root. It does not create, validate or scan the redirected tree — a caller
    pointing at a directory that does not exist gets empty scans, which is what `Path.glob` on a
    missing path already yields and is the honest answer for a redirect the caller declared."""
    default = os.environ.get("YITC_CORPUS_ROOT_DEFAULT") if default is None else default
    guard = os.environ.get("YITC_CORPUS_GUARD_ROOT") if guard is None else guard
    if not default or not guard:
        return root
    try:
        if os.path.realpath(str(root)) != os.path.realpath(str(guard)):
            return root
        return Path(default)
    except OSError:
        return root


def _scan(store_dir, pattern):
    """Sorted glob of one store dir — the single home for the store-traversal idiom."""
    return sorted(store_dir.glob(pattern))


def scan_tasks(tasks_dir):
    """Canonical task-record scan (T-*.yaml; excludes _template.yaml)."""
    return _scan(tasks_dir, "T-*.yaml")


def scan_specs(specs_dir):
    """Canonical spec scan (SPEC-*.yaml; excludes _template.yaml)."""
    return _scan(specs_dir, "SPEC-*.yaml")


def scan_errors(errors_dir):
    """Canonical error/friction case-file scan (E-*.yaml)."""
    return _scan(errors_dir, "E-*.yaml")


def scan_decisions(decisions_dir):
    """Canonical decision-record scan (D-*.yaml; excludes audit/*-audit-*.yaml)."""
    return _scan(decisions_dir, "D-*.yaml")


def scan_plans(plans_dir):
    """Canonical plan scan (*.md)."""
    return _scan(plans_dir, "*.md")


def scan_ideas(ideas_dir):
    """Canonical idea scan (*.md)."""
    return _scan(ideas_dir, "*.md")


def scan_patterns(patterns_dir):
    """Canonical pattern scan (*.md)."""
    return _scan(patterns_dir, "*.md")


def scan_scenarios(scenarios_dir):
    """Canonical scenario scan (*.md)."""
    return _scan(scenarios_dir, "*.md")


def scan_lessons(lessons_dir):
    """Canonical lesson scan (*.md) — per-repo local-craft notes (8th node type, SPEC-0090)."""
    return _scan(lessons_dir, "*.md")


# ── T-11663 (SPEC-0184 rule 9) — the `queue_jump` card field: ONE home for its two semantics ───────
#
# The field lifts ONE card to the front of the land-admission order and does nothing else. Its WRITE
# side lives in `lib/task.py` (the `task update` verb) and its READ side in `lib/batch_landing.py`
# (the yield ranking); both already import this module, so the semantics live HERE rather than being
# spelled twice and drifting on exactly the question that decides who gets the road (CHARTER §P5).
#
# THE EXPIRY IS DERIVED FROM THE CARD, NOT STORED BESIDE IT, and that is the whole of safeguard (b).
# A mark with its own lifetime is a second store that goes stale: ATOM3 was a hand-set pin that
# outlived its card by two days and reddened four unrelated batches before anyone found it. Reading
# the card's OWN status means the mark cannot outlive the card by construction — there is no sweep to
# forget to run, and nothing to clean up on close.
QUEUE_JUMP_FIELD = "queue_jump"

# The two statuses QUEUE.md §State-transitions names TERMINAL (`done` is shipped history, `wont-do`
# is decided-against; both are ends). A `parked` card is NOT terminal — it can return — so a park does
# not silently drop a mark the owner may still need when the card comes back.
TASK_TERMINAL_STATUSES = frozenset({"done", "wont-do"})


def queue_jump_write_error(reason) -> "str | None":
    """The WRITE-time refusal (safeguard a), or None when `reason` is admissible.

    The reason IS the mark: it carries, in itself, the blockage the jump claims to clear. A mark with
    no stated blockage is REFUSED here rather than discouraged in prose — an unexplained pin is
    exactly the artifact nobody can later judge, and «discouraged» has never yet stopped one being
    written. Returns the operator-facing message so the one caller can `_die` with it verbatim."""
    if not isinstance(reason, str) or not reason.strip():
        return ("--queue-jump needs the BLOCKAGE this card clears, in words: it is what makes the "
                "mark judgeable later and what the firing record names. An empty reason is refused")
    return None


def queue_jump_reason(card) -> "str | None":
    """The card's LIVE queue-jump reason, or None — the READ side, expiry included.

    None means «grants no precedence», and every unclear shape answers None: no field, a non-mapping
    field, a blank reason, an unreadable card, and — the expiry — a card whose own status is TERMINAL.
    That polarity is load-bearing and matches `_land_addressee_gone`'s: a reader that GUESSED a jump
    from something it could not parse would hand the road away on a misread, which is strictly worse
    than the arrival-order lottery this mechanism replaces."""
    if not isinstance(card, dict):
        return None
    mark = card.get(QUEUE_JUMP_FIELD)
    if not isinstance(mark, dict):
        return None
    reason = mark.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return None
    if str(card.get("status") or "").strip() in TASK_TERMINAL_STATUSES:
        return None            # the expiry: the mark dies with its card, derived not swept
    return reason.strip()
