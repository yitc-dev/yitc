"""land_verify_legs — the land VERIFY LEGS family (declared-surface readers, the selection ladder,
the layer prep / command runners, verify-admission, the flaky-sensitive knobs and the duration-drift /
scaling signals), extracted byte-identical from `bin/lib/worktree.py` (T-12700, card C4 of plan
`extract-the-13-over-budget-bin-lib-modules-into-le`).

WHAT IS IN HERE. The 39 REAL bodies of plan §Extraction map C4 (manifest as amended by the Controller
2026-09-17, plan Done criterion 1 (f)): the `_declared_*` readers of the yitc-ops verify contract, the
`_pinned_*` declared-check / baseline-parts / recovery-hint helpers, the `_selection_*` reachability
ladder (participating defs, host-injected roots, decision-reaches-root, changed-def owners, diff hunk
ranges, periphery / reachability freed), the layer prep + command runners and their timeout / cpu
signals, `_verify_under_admission`, the `_flaky_sensitive_*` / `_flaky_retry_isolated_passes` knobs,
the duration samples + drift + scaling signals, the deleg-registry readers and
`_running_engine_code_hash` — plus the constants EXCLUSIVE to them, module-local here AND handed to each
reader as a keyword-only inject whose DEFAULT is that module-local value: a direct call reads the leaf's
constant, while the host residue re-supplies the HOST alias at call time, so
`monkeypatch.setattr(worktree, "<CONST>", ...)` still reaches the moved body exactly as before
(the T-12695 audit-post r1 seam).

NOT IN HERE, AND THIS IS THE SEAM DECISION RATHER THAN AN OMISSION: the 32 `functools.wraps` forwarding
RESIDUES of the earlier T-11519 (verify_runner) / T-11523 (rebaseline_currency) / T-11524
(batch_landing) extractions that share these name prefixes — their bodies already live in those leaves
and their host-residue identity is a pinned behaviour contract, so they STAY in the host and reach this
module by injection where a mover needs them. The `cmd_*` orchestrators, `_run_verify_tests`'s host
callers, `_verify_admission` / `_verify_contention_context` / `_verify_slot_dir` / `_wait_heartbeat_line`
and the other host stayers likewise arrive by injection; non-exclusive host consts
(`_SELECTION_DECISION_ROOTS`, `_SELECTION_REACHABILITY_FILES`, `_PINNED_PREFIX`, …) stay host-owned.

SEAM (the T-9340 / T-9341 / T-11519 / T-11522 / T-11523 / T-11524 / T-12695 full inject-residue shape,
`lessons/library-extraction.md` §AST-freeze generator): bodies and signatures are spliced VERBATIM from
the original source — never `ast.unparse`, which reformats and loses byte-identity — and every
non-stdlib free name (host stayers, host globals, AND moved siblings via their host residue) arrives as a
keyword-only injected parameter, computed with `symtable` over each function's scope SUBTREE. The host
keeps a `functools.wraps` residue under every historical name, so the tests and every `worktree.<sym>`
reader keep resolving and stay out of this diff — and `inspect.getsource(worktree.<sym>)` unwraps to the
REAL body here. `_running_engine_code_hash` reads `Path(__file__).resolve().parents[1]` — `bin/` from
this file exactly as from the host (same directory), so the hash input is unchanged.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports only stdlib and the lower leaves
`lib.state` / `lib.journal` / `lib.test_discovery` / `lib.vocab`; it NEVER back-imports the host
(`tests/test_bin_lib_leaf_no_host_import.py`). Intentionally spec-less (SPEC-0005 admission test): a
byte-identical relocation mints no standing rule — the governing specs keep their homes and re-point
their `implements:` anchors here.
"""
from __future__ import annotations

import ast
import datetime
import fnmatch
import hashlib
import itertools
import json
import math
import os
import re
import sys
import threading
import time
from pathlib import Path

from lib import journal as journal_mod  # the shared bounded tail-scan journal reader
from lib import state
from lib import test_discovery  # T-12694 — the ONE `test_*.py` discovery home (stdlib-only leaf)


#: T-12587 (SPEC-0152 rule 16) — the OPTIONAL widen-only key a project may put on its `verify:` section
#: (beside the kernel-owned `verify.floor` sub-tree) to place ADDITIONAL verify-infrastructure paths
#: under the kernel floor: `verify.infra_globs: ["backend/tests/**"]`. Read ONLY by
#: `_declared_verify_infra_globs`; unioned into the trigger + would-skip surface by
#: `_declared_check_surface_globs`; its refusals surface through `_floor_declaration_refusals`.
VERIFY_INFRA_GLOBS_KEY = "infra_globs"
_SELECTION_REACHABILITY_HOST = "bin/lib/worktree.py"
_PREP_WAIT_DOMINATED_CPU_FRACTION = 0.20
# T-11073 (X-0860) — bounds on the registry read below. A layer `command:` is an arbitrary shell
# string, so following the scripts it names is a READ of untrusted-shaped input: keep it small,
# in-worktree, and shallow. These are safety bounds, never tuning knobs.
_DELEG_REGISTRY_MAX_FILES = 8
_DELEG_REGISTRY_MAX_BYTES = 256 * 1024
_VERIFY_TIERC_MEDIAN_MS = 5 * 60 * 1000    # Rule 4: median land verify > 5 min → build affected-test selection
_VERIFY_TIERC_P95_MS = 12 * 60 * 1000      # Rule 4: p95 land verify > 12 min → same
_VERIFY_TIERC_QUEUE_BLOCK_RATIO = 0.25     # Rule 4: verifier queueing blocks > 25% of lands
_VERIFY_QUEUE_BLOCK_FRACTION = 0.25        # a land is "queue-blocked" iff queue_wait dominates ≥25% of its verify wall
# T-11127 (SPEC-0132 Rule 7) — the duration-CREEP reading's parameters. Every one of these bars is
# on a DELTA; none of them is a duration TARGET, budget or level. T-11124 scoped OUT judging any
# duration and this card does not reopen that: there is deliberately no constant here answering
# "how slow is too slow", only constants answering "how much movement is more than noise".
_VERIFY_DRIFT_WINDOW = 10                  # lands per SIDE of the comparison. Both sides are a median
                                           # over a window, not a latest-vs-median: this host runs
                                           # contended parallel lands (SPEC-0132 Rule 1), so a single
                                           # land's percentile carries scheduling noise the median does
                                           # not. The sibling T-11125 uses the same window length.
_VERIFY_DRIFT_SCOPE_BIN = 0.10             # the relative width of a SCOPE COHORT. Two lands compare
                                           # only if they ran similarly-sized suites — see the cohort
                                           # rule in `_verify_duration_drift_signals`, which is the
                                           # load-bearing part of this reading, not a refinement.
_VERIFY_DRIFT_GROWTH_RATIO = 0.25          # the RELATIVE bar, scale-free. Matches the sibling
                                           # `SLOWEST_CHANGE_GROWTH_RATIO` (T-11125) on purpose: two
                                           # halves of one question should not disagree about how much
                                           # growth is worth a line.
_VERIFY_DRIFT_MIN_GROWTH_MS = 250          # the ABSOLUTE noise floor, and ONLY that. It exists so a
                                           # degenerate baseline cannot read as growth (a 2ms p50
                                           # becoming 4ms is +100% and means nothing). It is NOT the
                                           # sibling's 2000ms: that number guards ONE FILE's wall,
                                           # while a p50 here is ~1s, so re-using it would silence the
                                           # p50 axis entirely. Same role, different subject.
_VERIFY_DRIFT_PERCENTILES = ("p50", "p90")  # WHICH percentiles are read, in report order. p50 is the
                                           # broad body — the mode a tail-only reader is blind to by
                                           # construction (`_per_file_duration_record`: "a broad
                                           # uniform creep moves p50 while leaving the top-N
                                           # membership byte-identical"). p90 is the upper body BELOW
                                           # the tail that T-11125 already watches by name. p99/max
                                           # are deliberately NOT read: they ARE that tail, so reading
                                           # them here would say the sibling's thing again, less well.
# T-13522 (SPEC-0132 Rule 7, second subject) — the per-LAYER creep reading's parameters. Same shape
# and the same fence as the block above: every bar is on a DELTA, none is a duration level.
_VERIFY_LAYER_DRIFT_WINDOW = 10            # lands per SIDE, as above and for the same reason.
_VERIFY_LAYER_DRIFT_GROWTH_RATIO = 0.25    # the RELATIVE bar — the two siblings' value, on purpose.
_VERIFY_LAYER_DRIFT_MIN_GROWTH_MS = 5000   # the ABSOLUTE noise floor, sized for a LAYER and not for a
                                           # file percentile. A layer is a whole command (a runner
                                           # boot, often a container), and its run-to-run jitter is
                                           # seconds: measured 2026-10-04 on the 12 real layer series
                                           # with >= 20 ok lands (<project> + <project> journals), the
                                           # median consecutive-land delta of one layer is 0.06-19 s.
                                           # Replaying this rule over every 20-land tail of those
                                           # series: at 5000 ms <project> is silent on 154 of 154 and
                                           # <project> speaks on 31 of 716, all inside one episode in
                                           # which four layers slowed together; at 2000 ms an 8 s
                                           # layer starts speaking on jitter. The 250 ms above guards
                                           # a ~1 s percentile and would be noise here.
_LAYER_DRIFT_TS_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z")   # the journal's row stamp: it sorts as text
# ── T-12358 — the declared load-sensitive set: the two entry thresholds + the land-tail entry ──────
# Both are `config`-class PERFORMANCE tunables (SPEC-0193 / T-11967), SEEDED at the card's MEASURED
# fold and not at a hypothesis: over the 14 days to 2026-09-10 this repo's journal held 22 files that
# failed >= 5 times in that window against 126 that failed exactly once, so a threshold of 3
# isolated-pass retries inside 14 days separates the recidivists from the one-offs with room on both
# sides. `config set` is the only way to move either value. They resolve on the exact shape of
# `verify_runner._verify_retry_max_files` (env > machine settings file > the built-in; blank,
# non-numeric or out-of-band -> the built-in), so the three knobs of this family cannot drift into
# three precedence orders. They live HERE, beside the land tail that reads them, because the runner
# never reads them (a listed file is listed whatever the threshold is) — and an unreachable
# definition in `verify_runner.py` would be a foreign passenger under the T-11519 extraction contract.
_FLAKY_SENSITIVE_ENTER_DEFAULT = 3
_FLAKY_SENSITIVE_ENTER_ENV = "YITC_FLAKY_SENSITIVE_ENTER"
_FLAKY_SENSITIVE_ENTER_RANGE = (1, 100)
_FLAKY_SENSITIVE_WINDOW_DAYS_DEFAULT = 14
_FLAKY_SENSITIVE_WINDOW_DAYS_ENV = "YITC_FLAKY_SENSITIVE_WINDOW_DAYS"
_FLAKY_SENSITIVE_WINDOW_DAYS_RANGE = (1, 365)
#: T-14053 — the row types the entry fold counts isolated passes on: a land's own record, and a
#: governed Stage-6 run's (`task test --run`), whose routed pass keeps the venue-prefixed key.
_FLAKY_ENTRY_ROW_TYPES = ("land_completed", "tests_passed", "tests_failed")


def _running_engine_code_hash() -> str:
    """sha256 identity of the LIVE running engine's own verify CODE (every `bin/**/*.py` + the
    `bin/yitc-v2` entrypoint, resolved relative to THIS module's file). Folded into the cache key on
    every path so the §6b consumer/test-repo fallback — where merged_base carries NO `bin/yitc-v2`
    and the pinned verifier IS the live engine — still MISSES on an engine-code change (audit-pre
    high-1). In an engine self-land it is redundant with the candidate HEAD tree, never a false hit."""
    import hashlib
    h = hashlib.sha256()
    bin_dir = Path(__file__).resolve().parents[1]   # bin/lib/worktree.py → bin/
    for p in sorted(bin_dir.rglob("*.py")):
        try:
            h.update(p.relative_to(bin_dir).as_posix().encode("utf-8"))
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
        except OSError:
            h.update(b"<unreadable>\0")
    try:
        h.update(b"yitc-v2\0")
        h.update((bin_dir / "yitc-v2").read_bytes())
    except OSError:
        h.update(b"<no-entrypoint>\0")
    return h.hexdigest()


def _pinned_baseline_parts(W: Path, merged_base: str, *, _run_git_cap, CONSUMER_OPS_CONTRACT, _pinned_declared_check_paths, _running_engine_code_hash) -> "list[str]":
    """T-11517 — the BASELINE half of the pinned identity: everything in `_pinned_verify_cache_key`
    EXCEPT the candidate `subject=` tree. Extracted, not duplicated (CHARTER §P5, one definition):
    the cache key composes `subject=` + this list, and `_pinned_baseline_identity` digests this list
    on its own. Subject-INDEPENDENT by construction, which is what lets a formation row name the
    baseline in force at a moment when the candidate tree has not yet been merged.

    T-11184: the pinned VERIFIER surface includes the check paths the LAST-GREEN carrier DECLARES
    (`_pinned_declared_check_paths`), not just the hardcoded triple — so those ids must move the key
    too. Without this, a consumer whose `backend/tests/` changed on `main` between two lands of the
    SAME candidate tree would hit a cached GREEN and skip the re-run against the CHANGED old checks —
    a stale-green the pre-T-11184 key could not have (nothing outside the triple was overlaid)."""
    _declared: list = []
    _ops_raw = _run_git_cap(["show", f"{merged_base}:{CONSUMER_OPS_CONTRACT}"], W)
    if _ops_raw.returncode == 0 and (_ops_raw.stdout or "").strip():
        try:
            _declared = _pinned_declared_check_paths(state.load_str(_ops_raw.stdout))
        except Exception:
            _declared = []   # unparseable carrier → fall back to the triple (a MISS is fail-safe)
    parts = []
    for sub in ("bin", "tests", CONSUMER_OPS_CONTRACT, *_declared):
        r = _run_git_cap(["rev-parse", f"{merged_base}:{sub}"], W)
        parts.append(f"{sub}=" + ((r.stdout or "").strip() if r.returncode == 0 and (r.stdout or "").strip() else "<absent>"))
    parts.append("engine=" + _running_engine_code_hash())
    parts.append("py=" + ".".join(str(v) for v in sys.version_info[:3]))
    return parts


def _declared_verify_infra_globs(ops: "dict | None", *, CONSUMER_OPS_CONTRACT, VERIFY_INFRA_GLOBS_KEY=VERIFY_INFRA_GLOBS_KEY) -> "tuple[list, list]":
    """T-12587 — `(globs, refusals)` read from the carrier's OPTIONAL `verify.infra_globs` key.

    THE GAP THIS CLOSES (X-0938 class, SPEC-0185 §3(a)). The verify-infrastructure floor
    (`verify_wiring._verify_infrastructure_globs`) is ROOT-relative, and the only
    declaration-aware companion so far DERIVES a consumer's check surface from `verify.layers[].command`
    operands (`_pinned_declared_check_paths`). A layer whose command reveals no path (`make check`,
    `npm test`) with its verify implementation at `backend/tests/` therefore had NO key — in either
    direction — that placed that surface under the SPEC-0077 trigger: the pinned re-run never armed and
    its absence was invisible. This key lets the project SAY it. It clears SPEC-0185 §2's bar on the
    same terms as `tests.classes[].globs`: optional, checked only if present, enlarging what a project
    MAY declare and obliging no project to declare it.

    WIDEN-ONLY, BY CONSTRUCTION. The kernel constants are never read or touched here; a declared glob
    is only ever UNIONED with them by the caller. The narrowing direction was refused on the merits
    (X-0884: the hardcoded floor is what makes the pinned re-run fire on a verify-implementation touch,
    so a consumer must never be handed the power to shrink the surface that guards it) and <project>
    retracted that ask (X-0893). So every subtractive or replacing SHAPE is REFUSED BY NAME rather than
    parsed for intent: a MAPPING value (the only mapping forms this key could take — `remove:` /
    `exclude:` / `only:` / `waiver:` … — all narrow or replace), a non-list scalar, a `!`- or
    `-`-prefixed NEGATION entry (the one way to "name a kernel glob for removal"), an absolute or
    `..`-escaping entry, and a non-string entry. A refused entry contributes NOTHING; the accepted ones
    are returned sorted + deduped; an absent key is `([], [])`. Pure: no git, no filesystem, never
    raises. The fnmatch idiom is the constants' own (`_is_verify_implementation_touch`), so a declared
    `backend/tests/**` reads exactly as the kernel's `tests/**` does one level up."""
    ver = ops.get("verify") if isinstance(ops, dict) else None
    if not isinstance(ver, dict) or VERIFY_INFRA_GLOBS_KEY not in ver:
        return [], []          # ABSENT key — the only silent path; a PRESENT key is judged below
    raw = ver[VERIFY_INFRA_GLOBS_KEY]
    key = f"verify.{VERIFY_INFRA_GLOBS_KEY}"
    bound = (f"the key is WIDEN-ONLY — a flat list of repo-relative globs ADDED to the kernel "
             f"verify-infrastructure set, which is always applied and never removable "
             f"(SPEC-0152 rule 16; the narrowing direction was refused at X-0884)")
    if isinstance(raw, dict):
        names = ", ".join(sorted(str(k) for k in raw)) or "<empty>"
        return [], [f"land(verify-infra): {CONSUMER_OPS_CONTRACT} `{key}` is REFUSED — it is a mapping "
                    f"(keys: {names}), which can only narrow or replace the kernel set; {bound}."]
    if not isinstance(raw, list):
        # A PRESENT null / scalar is not an absence: the project wrote the key and said nothing
        # usable with it, so it is refused by name rather than read as "declares nothing" (audit-post
        # finding 1 — a silent `null` would be indistinguishable from an absent key).
        return [], [f"land(verify-infra): {CONSUMER_OPS_CONTRACT} `{key}` is REFUSED — it is "
                    f"{'null' if raw is None else type(raw).__name__}, not a list; {bound}."]
    globs: set = set()
    refusals: list = []
    for i, g in enumerate(raw):
        where = f"`{key}[{i}]`"
        if not isinstance(g, str):
            refusals.append(f"land(verify-infra): {CONSUMER_OPS_CONTRACT} {where} is REFUSED — not a "
                            f"string ({g!r}); {bound}.")
            continue
        # NORMALIZE FIRST, then judge the normalized form (audit-post finding 2): a `./` prefix is
        # stripped as many times as it occurs, so `./`, `.//abs/**` and `././-x` can never slip past
        # the checks below on their un-normalized spelling.
        s = g.strip()
        while s.startswith("./"):
            s = s[2:]          # `.//abs/**` becomes `/abs/**` and is refused as absolute below
        if not s or s == ".":
            refusals.append(f"land(verify-infra): {CONSUMER_OPS_CONTRACT} {where} = {g!r} is REFUSED — "
                            f"empty after normalization, not a glob; {bound}.")
            continue
        if s.startswith(("!", "-")):
            refusals.append(f"land(verify-infra): {CONSUMER_OPS_CONTRACT} {where} = {g!r} is REFUSED — a "
                            f"NEGATION names a glob for REMOVAL, and the kernel globs stay applied; {bound}.")
            continue
        if s.startswith("/") or ".." in s.split("/"):
            refusals.append(f"land(verify-infra): {CONSUMER_OPS_CONTRACT} {where} = {g!r} is REFUSED — "
                            f"not a repo-relative glob (absolute or escaping upward); {bound}.")
            continue
        globs.add(s)
    return sorted(globs), refusals


def _adapter_sources_under_root_bin(ops: "dict | None") -> list:
    """T-13915 — the `verify.layers[].adapter.sources` entries ONE parsed carrier declares at or
    under the root `bin/`, normalised as the adapter declaration reader normalises them
    (`posixpath.normpath`). Pure; any other shape — no carrier, no layers, a layer with no adapter
    mapping, a `sources:` that is not a list, an entry that is not a non-empty string — contributes
    nothing here (the declaration reader refuses it by name where the adapter is read)."""
    import posixpath
    out: set = set()
    ver = ops.get("verify") if isinstance(ops, dict) else None
    layers = ver.get("layers") if isinstance(ver, dict) else None
    for ly in layers if isinstance(layers, list) else ():
        adapter = ly.get("adapter") if isinstance(ly, dict) else None
        sources = adapter.get("sources") if isinstance(adapter, dict) else None
        for src in sources if isinstance(sources, list) else ():
            if not (isinstance(src, str) and src.strip()):
                continue
            norm = posixpath.normpath(src.strip())
            if norm == "bin" or norm.startswith("bin/"):
                out.add(norm)
    return sorted(out)


def _declared_check_surface_globs_of(ops: "dict | None", *, _declared_verify_infra_globs, _pinned_declared_check_paths) -> set:
    """The check-surface globs ONE parsed carrier declares — the per-carrier half of
    `_declared_check_surface_globs` below, factored out by T-13531 so that the reader which decides
    whether a changed test path may leave the full-run edge (`_owned_test_freed_paths`) excludes
    EXACTLY the set the declaration-aware rung would still run in full. Pure; `ops` may be None."""
    paths: set = set()
    # T-12587 — the project's EXPLICIT `verify.infra_globs` declaration joins the SAME union, from
    # BOTH carriers (the trigger's fail-OPEN-toward-arming bias, unchanged). Taken verbatim: an
    # explicit glob is the project's stated intent, so the root-level exclusion below — written for
    # DERIVED command operands, which are as likely the subject as a check — does not apply to it;
    # over-firing is the safe side (SPEC-0077 §1). Refused (subtractive) entries contribute nothing
    # here; they are REFUSED BY NAME at the declaration read (`_floor_declaration_refusals`).
    paths.update(_declared_verify_infra_globs(ops)[0])
    # T-13915 — an adapter's `sources:` under the root `bin/`. The fixed set no longer names a
    # project's root `bin/` (`verify_wiring._verify_infrastructure_globs`), and until then the
    # blanket glob was the only thing that put such a runner or script on the full run: `sources:`
    # is otherwise read inside its own layer only (`_adapter_shadow_decision`, rung (a)), after the
    # skip decision. Named here for what it is — the layer's declared verifier — so a change to it
    # runs every layer. Only the entries under the root `bin/`: what a `sources:` entry elsewhere
    # does is unchanged by this card.
    # Matched as the adapter ladder matches a `sources:` entry — the entry
    # itself or anything under it, LITERALLY (`_adapter_shadow_decision`): a glob metacharacter in
    # the name is escaped, never read as a pattern.
    import glob as _glob
    for src in _adapter_sources_under_root_bin(ops):
        paths.add(_glob.escape(src))
        paths.add(f"{_glob.escape(src)}/**")
    for p in _pinned_declared_check_paths(ops):
        if len(Path(p).parts) < 2:
            # The SAME root-level exclusion the overlay applies (see `_run_pinned_verify`): a
            # root-level operand is as likely to be the SUBJECT as a check. Keeping it out here too
            # is what stops the trigger OVER-firing on an ordinary product change — SPEC-0077's own
            # failure-threshold names «fires on a NON-verify-path land» as a defect of this gate.
            continue
        paths.add(p)
        paths.add(f"{p}/**")
    return paths


def _declared_check_surface_globs(W: Path, merged_base: str, *, _run_git_cap, CONSUMER_OPS_CONTRACT, _load_ops_carrier_text, _declared_check_surface_globs_of) -> list:
    """T-11184 (SPEC-0077 §1 coverage obligation) — the TRIGGER half of the same defect.

    §1 requires the verify-implementation-touch predicate's file set to cover the verifier's ENTIRE own
    executable/config surface, and states plainly that «an input the verify consumes but the helper OMITS
    is a self-approval hole». `_VERIFY_IMPLEMENTATION_GLOBS` is `("bin/**", "tests/**", "yitc-ops.yaml")`
    — the SAME root-level hardcode the overlay carried. So for a consumer whose checks live at
    `backend/tests/`, neutering one of them did not even FIRE the pinned leg: the overlay fix alone would
    have been unreachable for the reported shape. This supplies the missing globs from the DECLARATION.

    BOTH carriers are read here, and the union is taken — deliberately the OPPOSITE bias to the overlay,
    which reads the LAST-GREEN carrier only. The two answer different questions: the TRIGGER asks «could
    this diff touch a check surface?» and must fail OPEN toward running the extra verification, so a
    check surface named by EITHER the old or the new declaration arms it; the OVERLAY asks «which checks
    apply?» and must fail CLOSED to the old declaration, or the same commit would choose its own audit.
    Best-effort throughout: any git/parse failure contributes nothing and the established globs govern."""
    paths: set = set()
    for text in (
        (W / CONSUMER_OPS_CONTRACT).read_text(encoding="utf-8")
        if (W / CONSUMER_OPS_CONTRACT).exists() else None,
        (lambda r: (r.stdout if r.returncode == 0 else None))(
            _run_git_cap(["show", f"{merged_base}:{CONSUMER_OPS_CONTRACT}"], W)),
    ):
        # The per-carrier set (the `verify.infra_globs` union + the derived command operands, with the
        # root-level exclusion) is `_declared_check_surface_globs_of` — one definition, shared with the
        # owned-test reader (T-13531).
        paths.update(_declared_check_surface_globs_of(_load_ops_carrier_text(text)))
    return sorted(paths)


def _declared_check_surface_touch(changed_files, W: Path, merged_base: str, *, _run_git_cap, _is_verify_implementation_touch, _declared_check_surface_globs, matched: "list | None" = None) -> bool:
    """True iff any changed path falls on a check surface the ops carrier DECLARES (the globs above).
    The declaration-derived EXTENSION of `_is_verify_implementation_touch`'s static root-level set —
    same fnmatch idiom, same REPO_ROOT-relative paths, evaluated only when the static set did not
    already fire. Best-effort: no declared surface (the engine's own land, a carrier-less repo) → False,
    leaving the established predicate exactly as it was.

    `matched` (T-13916) — an OUT list for the one caller that records WHICH paths made the answer
    (the per-layer skip decision, for the selection record of SPEC-1006 rule 6): when a list is
    passed, the answer is taken path by path with the same matcher over the same globs — so it is
    the answer the one call below gives — and every changed path that matched is appended, under
    the name it was given. With `matched=None` (every other caller) nothing changes."""
    globs = _declared_check_surface_globs(W, merged_base, _run_git_cap=_run_git_cap)
    if not globs:
        return False
    if matched is not None:
        matched.extend(p for p in changed_files
                       if _is_verify_implementation_touch([p], _VERIFY_IMPLEMENTATION_GLOBS=globs))
        return bool(matched)
    return _is_verify_implementation_touch(changed_files, _VERIFY_IMPLEMENTATION_GLOBS=globs)


#: T-13528 (SPEC-0152 rule 16) — the ops-carrier sections that decide WHAT a land verifies: the layer
#: universe and its per-layer policy (`verify`), the pinned-leg gate (`verify_policy`) and the declared
#: test taxonomy the sweep / delegation / timing lanes read (`tests`). A carrier change that leaves all
#: three PARSED-equal cannot change which layers exist, what they run or how they are bounded.
_OPS_CARRIER_VERIFY_SECTIONS = ("verify", "verify_policy", "tests")
_OPS_CARRIER_SECTION_ABSENT = ("absent",)   # distinct from an explicit null (`verify:` with no value)
_YAML_MERGE_TAG = "tag:yaml.org,2002:merge"


def _changed_path_strings(paths) -> list:
    """T-13915, widened by T-14068 — the changed paths, each spelled as the verify-touch predicate
    spells a path (a leading `./` dropped). Pure; anything that is not a string contributes nothing.
    (Until T-14068 it kept only the paths at or under the root `bin/`.)"""
    out = []
    for raw in paths or ():
        if not isinstance(raw, str):
            continue
        p = raw
        while p.startswith("./"):
            p = p[2:]
        out.append(p)
    return out


def _root_bin_aware_touch(bound_touch, worktree: Path, base_ref: str, *, _run_git_cap, _declared_check_surface_touch):
    """T-13915, widened by T-14068 (SPEC-0152 rule 16) — the land's verify-implementation-touch
    predicate, made to answer for any changed path the project's OWN CONTRACT names.

    `bound_touch` is the predicate bound to the verify-infrastructure set of this repository (the one
    home, `verify_wiring._verify_infrastructure_globs`). A path the declared check surface names — a
    layer's `command:` path token (a root `bin/` script or a `scripts/check.sh` alike), an adapter's
    `sources:` entry under the root `bin/`, a `verify.infra_globs` entry — but the set does not hold
    would be an ordinary path to every reader of the land that asks the bound predicate ALONE (batch
    formation's cost rank, the failure attribution), while the per-layer skip decision and the pinned
    trigger, which ask the declared-check-surface companion beside it, run everything on that file.
    The returned predicate closes that: it answers True where `bound_touch` does, and otherwise asks
    the SAME companion about every changed path — the question the skip decision asks. T-13915 asked
    it about root `bin/` paths only, so a red on a named check path elsewhere was attributed to a
    layer the change "could not reach" (T-14068).

    Read at CALL time, over `worktree`'s carrier and the carrier at `base_ref`, as the companion
    reads them. Any doubt (the companion raises) is a touch: it arms more verification and exempts
    no layer. A repository whose carrier declares no check surface (the kernel's own) gets the
    companion's empty answer, so `bound_touch` decides alone there. Keyword arguments pass through
    to `bound_touch` unchanged."""
    def _touch(changed_files, **kw):
        if bound_touch(changed_files, **kw):
            return True
        try:
            paths = _changed_path_strings(changed_files)
            return bool(paths) and bool(_declared_check_surface_touch(
                paths, worktree, base_ref, _run_git_cap=_run_git_cap))
        except Exception:                  # noqa: BLE001 — a doubt is a touch
            return True
    return _touch


def _named_root_bin_touch(diff_paths, base_text, cand_text, *, _declared_check_surface_globs_of, _is_verify_implementation_touch) -> bool:
    """T-13915, widened by T-14068 (SPEC-0152 rule 16) — does THE PROJECT'S OWN CONTRACT name a
    changed path? (The name is T-13915's, when only root `bin/` paths were judged.)

    A path is verify infrastructure in a project exactly when the fixed set holds it or the declared
    check surface names it: a layer's `command:` path token, an adapter's `sources:` entry, a
    `verify.infra_globs` entry. The per-layer skip decision learns that from its
    declared-check-surface companion, for every changed path. The reader that takes the SAME answer
    about a land but holds only the two carrier TEXTS — the false-skip replay — asks it here,
    through the same per-carrier reader (`_declared_check_surface_globs_of`), so it cannot call such
    a file ordinary while the skip runs every layer on it. T-13915 judged root `bin/` paths only, so
    a named `scripts/` check or a `verify.infra_globs` entry elsewhere read as a false skip (T-14068).

    BOTH carriers are read and the union taken, as the companion does (a surface named at either side
    arms it). True also on every DOUBT about a carrier that is present — text that does not parse to
    a mapping, a reader that raises — because a doubt must never turn a named verifier file into an
    ordinary path. False when the diff holds no path, or neither carrier names a changed one."""
    paths = _changed_path_strings(diff_paths)
    if not paths:
        return False
    globs: set = set()
    for text in (base_text, cand_text):
        if text is None or (isinstance(text, str) and not text.strip()):
            continue                      # no carrier at this side declares nothing
        try:
            ops = state.load_ops_str(text)
            if not isinstance(ops, dict):
                return True
            globs.update(_declared_check_surface_globs_of(ops))
        except Exception:                 # noqa: BLE001 — a doubt keeps the file on the full run
            return True
    return bool(globs) and bool(_is_verify_implementation_touch(paths, _VERIFY_IMPLEMENTATION_GLOBS=sorted(globs)))


def _ops_carrier_duplicate_key(text: str) -> bool:
    """T-13528 — True when the carrier TEXT carries a duplicate key at ANY depth; RAISES on text the
    loader cannot compose (the caller treats both as «cannot prove equal»).

    WHY THE READER OWNS THIS AND THE PARSER DOES NOT. `state.load_ops_str` refuses a duplicate
    TOP-LEVEL key and nothing deeper, and the safe loader silently LAST-WINS a nested one — so a
    candidate writing `timeout_seconds: 1` and then `timeout_seconds: 300` inside `verify` parses to the
    base's `300` and would compare EQUAL (audit-pre finding 1). For every other carrier reader the
    last-wins value is simply the value; for a comparison that RELAXES a land gate an ambiguous text is
    a doubt, and a doubt is «changed» (lessons/fail-closed-belongs-to-the-reader-not-the-parser).

    ONE structural walk of the composed node graph, same loader class as the one parser. Three shapes
    answer True: two keys of one mapping that CONSTRUCT equal (exactly the collapse the loader performs
    — so `1` beside `true` is caught and a mere spelling difference is not), two merge keys, and a
    non-scalar key (whose equality this walk cannot judge). A node reached through an alias is visited
    once, by identity, so a self-referential alias terminates."""
    import yaml
    loader = state.yaml_loader()(text)
    try:
        root = loader.get_single_node()
        seen: set = set()
        stack = [root] if root is not None else []
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            if isinstance(node, yaml.MappingNode):
                keys: set = set()
                for key_node, value_node in node.value:
                    if not isinstance(key_node, yaml.ScalarNode):
                        return True
                    key = (_YAML_MERGE_TAG,) if key_node.tag == _YAML_MERGE_TAG \
                        else loader.construct_object(key_node, deep=True)
                    if key in keys:
                        return True
                    keys.add(key)
                    stack.append(value_node)
            elif isinstance(node, yaml.SequenceNode):
                stack.extend(node.value)
        return False
    finally:
        loader.dispose()


#: The EXACT value types a compared carrier section may be built from. A CLOSED vocabulary, not an
#: open «anything with a repr»: the safe loader also constructs tuples (`!!pairs`, `!!omap`) and sets
#: (`!!set`), and a canonical form that folded a tuple into a list would call `!!pairs [{k: v}]` and
#: `[[k, v]]` equal while a reader of the parsed value sees two different types (audit-post finding 1).
_OPS_CARRIER_SCALAR_TYPES = (str, int, float, bool, type(None), bytes, datetime.date, datetime.datetime)


def _ops_carrier_section_canon(value):
    """T-13528 — a TYPE-STRICT, ORDER-PRESERVING canonical form of one parsed carrier value. Python
    equality is too loose to stand behind a skip: `1 == True`, `1 == 1.0` and a mapping compares equal
    to its own re-ordering. Here a scalar carries its type name and a mapping keeps document order, so
    every difference a reader COULD observe is a difference.

    THE VOCABULARY IS CLOSED, and a value outside it is not compared at all: exactly a plain mapping, a
    plain list, and the scalar types of `_OPS_CARRIER_SCALAR_TYPES`, judged by EXACT type (a subclass
    is a different type). Anything else — a tuple, a set, any other constructed object — RAISES, which
    the caller reads as «changed». Refusing is deliberate rather than giving each exotic type a tag of
    its own: a section built from tagged constructs is rare enough that the full run costs nothing
    worth an open-ended canonical form. May also raise RecursionError on a self-referential structure."""
    kind = type(value)
    if kind is dict:
        return ("map", tuple((_ops_carrier_section_canon(k), _ops_carrier_section_canon(v))
                             for k, v in value.items()))
    if kind is list:
        return ("list", tuple(_ops_carrier_section_canon(v) for v in value))
    if kind in _OPS_CARRIER_SCALAR_TYPES:
        return (kind.__name__, repr(value))
    raise TypeError(f"carrier value of type {kind.__name__} is outside the compared vocabulary")


def _ops_carrier_strict_doc(text) -> dict:
    """The carrier TEXT parsed for a reader that RELAXES a land gate — the mapping, or a RAISE.

    The strict parse `_ops_carrier_freed_paths` has always applied (T-13528), factored out by T-13531
    so the owned-test reader below parses by the SAME rules rather than a second copy of them: the
    text is a non-blank string, carries no duplicate key at ANY depth (`_ops_carrier_duplicate_key`),
    and parses through `state.load_ops_str` — the ONE carrier parser — to a MAPPING. Every other state
    raises; both callers turn a raise into «nothing is freed», which is the behaviour without them."""
    if not (isinstance(text, str) and text.strip()):
        raise ValueError("carrier text is absent or blank")
    if _ops_carrier_duplicate_key(text):
        raise ValueError("carrier text carries a duplicate key")
    doc = state.load_ops_str(text)
    if not isinstance(doc, dict):
        raise ValueError("carrier document is not a mapping")
    return doc


def _ops_carrier_freed_paths(diff_paths, base_text, cand_text, *, CONSUMER_OPS_CONTRACT,
                             _declared_verify_infra_globs) -> "frozenset | None":
    """T-13528 (SPEC-0152 rule 16) — the `reachability_freed` set a carrier touch EARNS, or None.

    THE QUESTION. `yitc-ops.yaml` is in the verify-implementation glob set, so any change to it used to
    disable every layer's `subject_globs` skip — a card editing `audit_scrutiny:` paid the same full
    layer run as one rewriting `verify.layers`. This answers «did the change leave what a land VERIFIES
    untouched?» over the two carrier TEXTS, and returns `frozenset({<carrier>})` — the set the existing
    T-11463 seam frees at rung 4 — ONLY ON POSITIVE PROOF. PURE: no git, no filesystem.

    EVERY condition must hold, and each failure is the SAME answer, None — which is «changed», i.e.
    the behaviour before this function existed. There is no third value to route
    (lessons/carving-an-exception-into-a-fail-closed-gate §1):
      • the carrier is IN the diff (`./`-normalised) — otherwise there is nothing to free;
      • both texts are non-blank strings (a carrier absent at either side — born, deleted, renamed
        away — is not a comparison);
      • neither text carries a duplicate key at any depth (`_ops_carrier_duplicate_key`);
      • each parses through `state.load_ops_str` (the ONE carrier parser — it raises on malformed YAML
        and on a duplicate top-level key; aliases and merge keys are resolved by its constructor, so an
        anchor aliased INTO `verify` changes the parsed `verify`) to a MAPPING;
      • NEITHER carrier declares the carrier itself as verify infrastructure: an accepted
        `verify.infra_globs` glob matching the carrier path, or ANY refused entry of that key, withholds
        the freeing. This is the project's shipped opt-out, honoured INSIDE the one answer the skip, the
        attribution and the false-skip replay all read — so none of them can free what the land's
        declaration-aware rung (`_declared_check_surface_touch`) would still run in full;
      • the canonical forms of `verify`, `verify_policy` and `tests` are equal on both sides, where an
        ABSENT section is distinct from an explicit null.
    Any exception (a constructor error, a RecursionError on a self-referential alias) is None too."""
    carrier = str(CONSUMER_OPS_CONTRACT)
    try:
        paths = {str(p).strip()[2:] if str(p).strip().startswith("./") else str(p).strip()
                 for p in (diff_paths or ())}
        if carrier not in paths:
            return None
        canon: list = []
        for text in (base_text, cand_text):
            doc = _ops_carrier_strict_doc(text)        # raises on every doubt → None below
            globs, refusals = _declared_verify_infra_globs(doc, CONSUMER_OPS_CONTRACT=carrier)
            if refusals or any(fnmatch.fnmatch(carrier, g) for g in globs):
                return None
            canon.append(tuple(
                _ops_carrier_section_canon(doc[key]) if key in doc else _OPS_CARRIER_SECTION_ABSENT
                for key in _OPS_CARRIER_VERIFY_SECTIONS))
        return frozenset({carrier}) if canon[0] == canon[1] else None
    except Exception:                          # noqa: BLE001 — any doubt is «changed»
        return None


def _ops_carrier_live_texts(worktree: Path, base_ref: str, *, _run_git_cap,
                            CONSUMER_OPS_CONTRACT) -> "tuple | None":
    """`(merge-base carrier text, candidate carrier text)` for a LIVE land, or None on any read doubt.

    The acquisition `_ops_carrier_verify_freed` has always performed (T-13528), factored out by T-13531
    so the owned-test reader takes the SAME two texts by the same reads. The base text is
    `git show <base_ref>:<carrier>`; the candidate text is the WORKING-TREE file — exactly what the
    layer runner loads its layers from — and that file must ALSO be BYTE-IDENTICAL to HEAD's blob,
    because the diff is `base..HEAD`: the carrier the runner loads and the carrier the land
    fast-forwards have to be one file. The identity is taken on OBJECT IDS — the unfiltered hash of the
    working file against `HEAD:<carrier>` — never on decoded text, which would call a CRLF working copy
    equal to an LF blob. None on: no base ref or git runner, a carrier absent at the base, in the tree
    or at HEAD, a symlinked or non-UTF-8 candidate, a working copy that differs from HEAD by so much as
    a line ending, any git failure. May raise on an unreadable file; both callers treat that as None."""
    carrier = str(CONSUMER_OPS_CONTRACT)
    if not base_ref or _run_git_cap is None:
        return None
    cand = Path(worktree) / carrier
    if cand.is_symlink() or not cand.is_file():
        return None
    # BYTE identity with HEAD, by object id. `--no-filters` hashes the file exactly as it sits on
    # disk (no clean/eol conversion), so equal ids mean equal bytes; the git runner captures TEXT,
    # which is why the comparison is never made on its decoded output.
    work_oid = _run_git_cap(["hash-object", "--no-filters", "--", carrier], worktree)
    head_oid = _run_git_cap(["rev-parse", "--verify", "--quiet", f"HEAD:{carrier}"], worktree)
    if work_oid.returncode != 0 or head_oid.returncode != 0:
        return None
    if not work_oid.stdout.strip() or work_oid.stdout.strip() != head_oid.stdout.strip():
        return None
    cand_text = cand.read_text(encoding="utf-8")
    base = _run_git_cap(["show", f"{base_ref}:{carrier}"], worktree)
    if base.returncode != 0:
        return None
    return (base.stdout, cand_text)


def _ops_carrier_verify_freed(worktree: Path, base_ref: str, diff_paths, *, _run_git_cap,
                              CONSUMER_OPS_CONTRACT, _ops_carrier_freed_paths) -> "frozenset | None":
    """T-13528 — `_ops_carrier_freed_paths` for a LIVE land: the merge-base carrier against the
    candidate tree's. The ONE reader the per-layer skip and the land attribution both call, with the
    same inputs, so the two cannot disagree about one land.

    LAZY: it reads nothing unless the diff lists the carrier, so a land that does not touch
    `yitc-ops.yaml` pays no git call (and nothing here runs at session start). The base text is
    `git show <base_ref>:<carrier>`; the candidate text is the WORKING-TREE file — exactly what the
    layer runner loads its layers from — and that file must ALSO be BYTE-IDENTICAL to HEAD's blob,
    because the diff is `base..HEAD`: the carrier the runner loads and the carrier the land
    fast-forwards have to be one file. The identity is taken on OBJECT IDS — the unfiltered hash of the
    working file against `HEAD:<carrier>` — never on decoded text, which would call a CRLF working copy
    equal to an LF blob (audit-post finding 2). FAIL-CLOSED to None on every read doubt: no base ref or
    git runner, a carrier absent at the base, in the tree or at HEAD, a symlinked or non-UTF-8
    candidate, a working copy that differs from HEAD by so much as a line ending, any git failure, any
    exception."""
    carrier = str(CONSUMER_OPS_CONTRACT)
    try:
        if not base_ref or _run_git_cap is None or not diff_paths:
            return None
        if not any((str(p).strip()[2:] if str(p).strip().startswith("./") else str(p).strip()) == carrier
                   for p in diff_paths):
            return None
        # The two texts come from the ONE acquisition the owned-test reader also uses (T-13531).
        texts = _ops_carrier_live_texts(worktree, base_ref, _run_git_cap=_run_git_cap,
                                        CONSUMER_OPS_CONTRACT=carrier)
        if texts is None:
            return None
        return _ops_carrier_freed_paths(diff_paths, texts[0], texts[1])
    except Exception:                          # noqa: BLE001 — any doubt is «changed»
        return None


#: T-13531 (SPEC-0152 rule 16) — the member of the kernel verify-infrastructure glob set whose OWNED
#: paths the per-layer skip frees. It names WHICH floor member is narrowed, nothing more: what a test
#: file IS comes from the project's own `tests.classes[].globs`, never from a pattern held here.
_OWNED_TEST_KERNEL_GLOB = "tests/**"


def _owned_test_layer_claims(doc: dict) -> tuple:
    """`({layer: subject_globs | None}, {layer: [covers globs]})` of one strictly-parsed carrier, or a
    RAISE (T-13531). The layer half of the owned-test proof, read with the missing-value judgement of
    THIS use site (lessons/fail-closed-belongs-to-the-reader-not-the-parser): the per-layer judge
    `_subject_globs_would_skip` answers False for a MALFORMED glob list because its caller wants «run
    the layer», and read here that same False would say «this layer owns the path». So a `verify` that
    is not a mapping, a `layers` that is not a non-empty list, a layer that is not a mapping, a name
    that is not a non-blank string or is DUPLICATED, a present `subject_globs` that is not a non-empty
    list of non-blank strings, and a present `covers` that is not a list of strings all raise. An
    ABSENT (or null) `subject_globs` is None — a layer that always runs and claims nothing."""
    ver = doc.get("verify")
    layers = ver.get("layers") if isinstance(ver, dict) else None
    if not (isinstance(layers, list) and layers):
        raise ValueError("no usable verify.layers")
    subjects: dict = {}
    covers: dict = {}
    for ly in layers:
        if not isinstance(ly, dict):
            raise ValueError("a verify layer is not a mapping")
        name = ly.get("layer")
        if not (isinstance(name, str) and name.strip()):
            raise ValueError("a verify layer has no usable name")
        name = name.strip()
        if name in subjects:
            raise ValueError("duplicate verify layer name")
        sg = ly.get("subject_globs")
        if sg is None:
            subjects[name] = None
        elif isinstance(sg, list) and sg and all(isinstance(g, str) and g.strip() for g in sg):
            subjects[name] = list(sg)
        else:
            raise ValueError("malformed subject_globs")
        cv = ly.get("covers")
        if cv is None:
            covers[name] = []
        elif isinstance(cv, list) and all(isinstance(c, str) for c in cv):
            covers[name] = [c.strip() for c in cv if c.strip()]
        else:
            raise ValueError("malformed covers")
    return subjects, covers


def _owned_test_freed_paths(diff_paths, base_text, cand_text, *, CONSUMER_OPS_CONTRACT,
                            _declared_verify_infra_globs, _declared_check_surface_globs_of,
                            _declared_test_globs, _subject_globs_would_skip) -> "frozenset | None":
    """T-13531 (SPEC-0152 rule 16) — the changed TEST paths the layers that own them answer for, or None.

    THE QUESTION. `tests/**` is in the verify-implementation glob set, so a diff touching ANY test file
    used to disable every layer's `subject_globs` skip — a card adding one backend test paid a full run
    of every declared layer. This answers «is this changed test path provably one layer's own?» over
    the two carrier TEXTS and returns the set the existing T-11463 seam frees at rung 4. A freed path
    is then judged like any other: the layers whose `subject_globs` claim it run, the rest are judged
    by their own globs. PURE: no git, no filesystem.

    A path is freed ONLY ON POSITIVE PROOF ON EVERY AXIS, and each failure is the SAME answer —
    «not freed», the behaviour before this function existed
    (lessons/carving-an-exception-into-a-fail-closed-gate §1):
      (a) DECLARED TEST FILE — it matches the UNION of the project's own `tests.classes[].globs` at
          BOTH carriers (`_declared_test_globs`, the one reader of that declaration). A project that
          declares none frees nothing. The kernel carries no filename convention here: on a surface
          that gates, what a test file IS is the project's declaration (SPEC-0185 §1(c), §2a(ii));
      (b) both texts parse strictly (`_ops_carrier_strict_doc`) and neither carries a REFUSED
          `verify.infra_globs` entry;
      (c) it matches no declared check-surface glob of EITHER carrier — `verify.infra_globs`, which is
          how a project lists SHARED test files, or a layer command operand
          (`_declared_check_surface_globs_of`) — so nothing is freed here that the declaration-aware
          rung would still run in full;
      (d) `verify.layers` is well-formed (`_owned_test_layer_claims`) and the per-layer subject and
          covers maps are EQUAL at both carriers;
      (e) at least one glob-declaring layer CLAIMS it, where «claims» is the per-layer judge itself
          (`not _subject_globs_would_skip([path], globs)`) — so a freed path always forces a layer;
      (f) at least one glob-declaring layer does NOT claim it — a path every scoped layer claims is
          not freed;
      (g) no glob-declaring layer whose `covers:` matches it fails to claim it — a layer that says it
          verifies a path and also says the path cannot affect it has contradicted itself.
    A malformed `tests.classes` entry contributes no glob, so it can only shrink the freed set. Any
    exception is None. Only paths under the kernel `tests/**` glob are considered: every other
    verify-infrastructure path in the diff still fires rung 4."""
    carrier = str(CONSUMER_OPS_CONTRACT)
    try:
        tests: set = set()
        for raw in (diff_paths or ()):
            p = str(raw).strip()
            if p.startswith("./"):
                p = p[2:]
            if fnmatch.fnmatch(p, _OWNED_TEST_KERNEL_GLOB):
                tests.add(p)
        if not tests:
            return None
        claims = None
        surface: set = set()
        declared: list = []
        for text in (base_text, cand_text):
            doc = _ops_carrier_strict_doc(text)                                    # (b)
            if _declared_verify_infra_globs(doc, CONSUMER_OPS_CONTRACT=carrier)[1]:
                return None                                                        # (b) refused entry
            surface.update(_declared_check_surface_globs_of(doc))                  # (c)
            cur = _owned_test_layer_claims(doc)                                    # (d)
            if claims is not None and cur != claims:
                return None
            claims = cur
            declared.append(list(_declared_test_globs(doc)))                       # (a)
        subjects, covers = claims
        scoped = {name: globs for name, globs in subjects.items() if globs is not None}
        freed: set = set()
        for p in sorted(tests):
            if not all(any(fnmatch.fnmatch(p, g) for g in globs) for globs in declared):
                continue                                                           # (a)
            if any(fnmatch.fnmatch(p, g) for g in surface):
                continue                                                           # (c)
            owners = {name for name, globs in scoped.items() if not _subject_globs_would_skip([p], globs)}
            if not owners or owners == set(scoped):
                continue                                                           # (e), (f)
            if any(name not in owners and any(fnmatch.fnmatch(p, c) for c in covers.get(name, ()))
                   for name in scoped):
                continue                                                           # (g)
            freed.add(p)
        return frozenset(freed) or None
    except Exception:                          # noqa: BLE001 — any doubt frees nothing
        return None


def _owned_test_verify_freed(worktree: Path, base_ref: str, diff_paths, *, _run_git_cap,
                             CONSUMER_OPS_CONTRACT, _owned_test_freed_paths) -> "frozenset | None":
    """T-13531 — `_owned_test_freed_paths` for a LIVE land or Stage-6 run: the merge-base carrier
    against the candidate tree's. The ONE reader the per-layer skip and the land attribution both call,
    with the same inputs, so the two cannot disagree about one land.

    LAZY: it reads nothing unless the diff lists a path under the kernel `tests/**` glob. The two texts
    come from `_ops_carrier_live_texts` — the acquisition the section-aware carrier reader uses, with
    its conditions unchanged (the working carrier is a regular file byte-identical to HEAD's blob).
    FAIL-CLOSED to None on every read doubt and on any exception."""
    try:
        if not base_ref or _run_git_cap is None or not diff_paths:
            return None
        if not any(fnmatch.fnmatch(str(p).strip()[2:] if str(p).strip().startswith("./") else str(p).strip(),
                                   _OWNED_TEST_KERNEL_GLOB) for p in diff_paths):
            return None
        texts = _ops_carrier_live_texts(worktree, base_ref, _run_git_cap=_run_git_cap,
                                        CONSUMER_OPS_CONTRACT=CONSUMER_OPS_CONTRACT)
        if texts is None:
            return None
        return _owned_test_freed_paths(diff_paths, texts[0], texts[1])
    except Exception:                          # noqa: BLE001 — any doubt frees nothing
        return None


def _edge_own_test_paths(edge_paths, base_text, cand_text, *, CONSUMER_OPS_CONTRACT,
                         _declared_verify_infra_globs, _declared_test_globs) -> "frozenset | None":
    """T-13964 (SPEC-1006 rule 6, rung (a)) — the paths among `edge_paths` that are the project's OWN
    test files, or None. `edge_paths` are the changed paths that made the SPEC-0152 rule-16 skip
    decision answer `verify-implementation-touch` / `declared-check-surface`; the adapter ladder
    lets such an edge pass ONLY when every one of them is in this set AND its own layer places it
    (`_adapter_shadow_decision`). PURE: no git, no filesystem.

    A path is in the set ONLY ON POSITIVE PROOF, and every doubt is the same answer — «not in the
    set», which leaves the edge answering rung (a) exactly as before:
      (a) both carrier texts parse strictly (`_ops_carrier_strict_doc`) and neither carries a
          REFUSED `verify.infra_globs` entry;
      (b) it matches the project's declared `tests.classes[].globs` at BOTH carriers
          (`_declared_test_globs`, the one reader of that declaration) — a project that declares
          none has no own test file here;
      (c) it matches no explicit `verify.infra_globs` entry of EITHER carrier — how a project names
          a shared test helper it wants run whole;
      (d) it is no layer's adapter `sources:` entry, nor under one, at either carrier (matched
          literally, as rung (a) matches `sources:`);
      (e) it is not the carrier itself.
    Any exception is None."""
    import posixpath
    carrier = str(CONSUMER_OPS_CONTRACT)
    try:
        names = [str(p) for p in (edge_paths or ()) if isinstance(p, str)]
        if not names:
            return None
        declared: list = []
        infra: set = set()
        sources: set = set()
        for text in (base_text, cand_text):
            doc = _ops_carrier_strict_doc(text)                                    # (a)
            globs, refused = _declared_verify_infra_globs(doc, CONSUMER_OPS_CONTRACT=carrier)
            if refused:
                return None                                                        # (a)
            infra.update(globs)                                                    # (c)
            declared.append([g for g in _declared_test_globs(doc) if isinstance(g, str) and g.strip()])
            ver = doc.get("verify")
            for ly in (ver.get("layers") if isinstance(ver, dict) else None) or ():
                adapter = ly.get("adapter") if isinstance(ly, dict) else None
                for src in (adapter.get("sources") if isinstance(adapter, dict) else None) or ():
                    if isinstance(src, str) and src.strip():
                        sources.add(posixpath.normpath(src.strip()))               # (d)
        own: set = set()
        for p in names:
            q = p[2:] if p.startswith("./") else p
            if q == carrier:
                continue                                                           # (e)
            if not all(any(fnmatch.fnmatch(q, g) for g in globs) for globs in declared) \
                    or not all(declared):
                continue                                                           # (b)
            if any(fnmatch.fnmatch(q, g) for g in infra):
                continue                                                           # (c)
            if any(q == s or q.startswith(s + "/") for s in sources):
                continue                                                           # (d)
            own.add(p)
        return frozenset(own) or None
    except Exception:                          # noqa: BLE001 — any doubt frees nothing
        return None


def _edge_own_test_verify(worktree: Path, base_ref: str, edge_paths, *, _run_git_cap,
                          CONSUMER_OPS_CONTRACT, _edge_own_test_paths) -> "frozenset | None":
    """T-13964 — `_edge_own_test_paths` for a LIVE land or Stage-6 run: the merge-base carrier against
    the candidate tree's, taken by `_ops_carrier_live_texts` (the acquisition the owned-test and
    carrier readers use, conditions unchanged). Reads nothing without an edge path. FAIL-CLOSED to
    None on every read doubt and on any exception."""
    try:
        if not base_ref or _run_git_cap is None or not edge_paths:
            return None
        texts = _ops_carrier_live_texts(worktree, base_ref, _run_git_cap=_run_git_cap,
                                        CONSUMER_OPS_CONTRACT=CONSUMER_OPS_CONTRACT)
        if texts is None:
            return None
        return _edge_own_test_paths(edge_paths, texts[0], texts[1])
    except Exception:                          # noqa: BLE001 — any doubt frees nothing
        return None


def _pinned_declared_check_paths(ops: "dict | None", *, _pinned_declared_check_paths_by_layer) -> list:
    """The flat union of `_pinned_declared_check_paths_by_layer` — the form every caller but the
    land-time report needs. Kept as the single public shape; the by-layer map is its source."""
    out: set = set()
    for paths in _pinned_declared_check_paths_by_layer(ops).values():
        out.update(paths)
    return sorted(out)


def _pinned_declared_check_paths_by_layer(ops: "dict | None") -> dict:
    """T-11184 (SPEC-0077 §3/§6b, X-0938) — the repo-relative CHECK-surface candidates a consumer's
    `verify.layers` DECLARATION names, so the pinned last-green overlay reaches the checks a project
    actually has rather than a kernel-hardcoded root `tests/`.

    THE DEFECT THIS CLOSES. `_run_pinned_verify` overlaid exactly `("tests", yitc-ops.yaml)`. For a
    consumer whose tests are NOT at a root-level `tests/` — <project> keeps them at `backend/tests/`,
    declared as `verify.layers[backend].command: bash backend/scripts/verify.sh` — `git cat-file -e
    <base>:tests` MISSES, so the pinned run swapped ONLY the carrier and every check surface it executed
    came from the CANDIDATE tree. The leg still ran and still reported `verify_mode=pinned+candidate`,
    so it read as protection while applying the candidate's own checks to the candidate's own tree. That
    is a FALSE GREEN, not a coverage gap: a verifier-weakening change could self-approve unseen. The
    cause, stated for reuse: a governed gate resolved ONE of its two inputs — the declaration — from the
    project's contract and the OTHER — where the checks that declaration names physically live — from a
    kernel-hardcoded directory name, and degraded SILENTLY to a no-op for any project shaped differently.

    WHAT IS RETURNED. Path CANDIDATES only — this function is pure (no git, no filesystem); the caller
    asks merged_base what each path IS and applies the type/depth discrimination there. Two sources:
      (1) DECLARATION-LITERAL — the path-shaped tokens of each declared layer's `command:`. No
          option-position guessing: a token starting with `-` is dropped, and a token that could not be
          a path (no `/` and no `.`) is dropped, so a VALUELESS flag never swallows the operand behind it
          (`python3 -m pytest -q backend/tests` still yields `backend/tests` — audit-pre finding 2).
      (2) ROOT-ANCHORED CONVENTION — `<top-level segment of a declared path>/tests`
          (`backend/scripts/verify.sh` -> `backend/tests`). This is what covers the REPORTED shape,
          where the harness script names its tests only inside its own body, relative to a shell
          variable, and no static reading of the declaration can see them. It is NOT a re-run of the
          defect above: the defect is a check dir hardcoded at the REPO ROOT, blind to the declaration;
          this is the same conventional NAME resolved under a root the CARRIER ITSELF declares, ADDITIVE
          to (1), and bounded by exactly that anchoring — a root no layer declares is never probed.
          Converged option B of `decisions/T-11184-audit-consult-pre.yaml` (GREEN, sole survivor): a new
          explicit `checks:` carrier field was refuted because it leaves every existing consumer
          false-green until it opts in, and inverting the construction was refuted because
          <project>'s `covers`/`subject_globs` SUBSUME `backend/tests`.
    EXCLUSIONS, all fail-SAFE toward UNDER-overlay. An unparseable command contributes nothing. Absolute
    paths, `.`, anything containing `..`, and the bare top-level `bin` are dropped (`bin/**` stays
    CANDIDATE — it is the SUBJECT the pinned checks examine). Every path the SAME layer declares as
    dependency/subject infrastructure — `prep.workdir` / `prep.lockfile` / `prep.manifest` — is dropped:
    <project> declares `prep.workdir: frontend`, which is exactly the `npm --prefix frontend run build`
    operand, i.e. the layer's SUBJECT. The bias is deliberate and asymmetric: over-overlaying a subject
    path would make the pinned leg stop seeing the candidate change at all — the SAME false-green disease
    this function exists to end — whereas under-overlaying only narrows the pin, and the caller NAMES
    what it overlaid so a partial pin is auditable rather than implied.
    """
    import shlex
    layers = None
    if isinstance(ops, dict):
        ver = ops.get("verify")
        if isinstance(ver, dict):
            layers = ver.get("layers")
    if not isinstance(layers, list):
        return {}
    by_layer: dict = {}
    for i, ly in enumerate(layers):
        if not isinstance(ly, dict):
            continue
        name = str(ly.get("layer") or "").strip() or f"[{i}]"
        out = by_layer.setdefault(name, set())
        cmd = ly.get("command")
        if not (isinstance(cmd, str) and cmd.strip()):
            continue
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            continue   # unparseable command → contributes nothing (fail-safe)
        # The SAME layer's declared dependency/subject infrastructure — never a check surface.
        excluded = set()
        prep = ly.get("prep")
        if isinstance(prep, dict):
            for k in ("workdir", "lockfile", "manifest"):
                v = prep.get(k)
                if isinstance(v, str) and v.strip():
                    excluded.add(v.strip().strip("/"))
        for tok in tokens:
            if tok.startswith("-"):
                continue                       # a flag, valued or not — never a path operand
            if "/" not in tok and "." not in tok:
                continue                       # a bare argv word (`npm`, `run`, `build`, `pytest`)
            cand = tok.strip()
            if (not cand or cand.startswith("/") or cand in (".", "..", "bin")
                    or ".." in Path(cand).parts or Path(cand).is_absolute()):
                continue
            cand = cand.rstrip("/")
            if not cand or cand in excluded:
                continue
            out.add(cand)
            # The root-anchored convention: `<declared root>/tests`.
            root = Path(cand).parts[0]
            if root not in ("", ".", "bin") and root not in excluded:
                conv = f"{root}/tests"
                if conv not in excluded:
                    out.add(conv)
    return {k: sorted(v) for k, v in by_layer.items()}


def _covers_glob_test_dir(g, *, _ROOT_TEST_SWEEP_DIR) -> "str | None":
    """The repo-relative DIRECTORY a `covers:` glob names as a test surface, or None.

    `backend/tests/**` -> `backend/tests`; `tests/**/*.py` -> `tests`; `backend/tests` -> itself.
    The glob is TRUNCATED at its first `tests` segment, because everything past that segment is a
    file pattern inside the directory, not part of its name.

    NORMALISATION IS `_glob_names_sweep_dir`'s, verbatim and for its reasons (T-10438 audit-post,
    absorbed mode-a): ONE optional leading `./` is stripped, and an ABSOLUTE (`/tests/**`) or
    PARENT-RELATIVE (`../tests/**`) glob is REJECTED outright rather than normalised into a match --
    `covers:` is declared repo-relative (SPEC-0152 rule 16) and such a glob names a tree OUTSIDE this
    repo, so it cannot answer for a directory inside it. A glob carrying a wildcard in a segment
    BEFORE the `tests` segment (`*/tests/**`) is also rejected: the directory it names is not
    determined by the declaration, and guessing one is the root-layout guessing SPEC-0185 SS4 retires."""
    if not isinstance(g, str):
        return None
    head = g.strip()
    if head.startswith("./"):
        head = head[2:]
    if not head or head.startswith("/") or head.startswith("../"):
        return None
    parts = [seg for seg in head.split("/") if seg not in ("", ".")]
    for i, seg in enumerate(parts):
        if seg.lower() == _ROOT_TEST_SWEEP_DIR:
            prefix = parts[:i + 1]
            if any(ch in s for s in prefix for ch in "*?["):
                return None
            return "/".join(prefix)
    return None


def _declared_test_sweep_dirs(worktree: Path, ops: "dict | None" = None,
                              *, _read_yaml=None, CONSUMER_OPS_CONTRACT, _ROOT_TEST_SWEEP_DIR, _load_ops_carrier_text, _covers_glob_test_dir, _pinned_declared_check_paths_by_layer) -> "list[str]":
    """SPEC-0185 SS1 (T-11204) -- the repo-relative DIRECTORIES that hold THIS consumer's declared test
    surface: the one answer the delegation predicate and all three kernel test sweeps were each
    spelling as the literal `tests`.

    THE DEFECT THIS CLOSES, stated once for all seven call sites. Every kernel sweep resolved its
    directory from an ASSUMED root layout while the project had already SAID where its tests are.
    For a consumer whose suite is at `backend/tests/` -- <project>, declared as
    `verify.layers[backend].command: bash backend/scripts/verify.sh` -- `<repo>/tests` does not
    exist, so each sweep globbed an absent directory, found nothing, and reported that as a pass. The
    same literal on the READ side made `_glob_names_sweep_dir` reject a `covers: [backend/tests/**]`
    declaration BY CONSTRUCTION, so the delegation predicate could never fire however completely the
    project declared. This is SPEC-0185 SS1(a) -- a hardcoded literal where a declaration exists.

    TWO SOURCES, UNIONED, because reading either alone is SPEC-0185 SS1(b) (an UNDER-READ declaration):
      (1) `_pinned_declared_check_paths_by_layer` candidates whose LAST segment is `tests` -- the
          layer's `command:` operands plus its already-shipped `<declared root>/tests` convention.
          This is a CONSUMER of that function, not a second reader of the carrier: it is reused
          exactly as SPEC-0185 SS5 names it for reuse, and is deliberately NOT widened there, because
          its output also drives the pinned OVERLAY, where admitting `covers`-derived operands could
          overlay a SUBJECT path and re-open the false green T-11184 closed.
      (2) each layer's `covers:` globs, truncated at their `tests` segment. Needed on its own
          evidence: a project may name its dir ONLY on `covers:` while its `command:` names it
          nowhere a static read can see (`make test` + `covers: [backend/tests/**]`).

    WHAT IT DOES NOT DO -- it makes NO absence judgement, deliberately. Its seven callers do not agree
    on what an unresolvable declaration means: the sweeps and the zero-probe guard are GATES and fail
    CLOSED, while `_delegated_tests_execution_gap` is a report-only SIGNAL that must fail the OPPOSITE
    way (`lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate.md`,
    `lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`). Answering that centrally would
    make each half individually correct and the whole wrong, so this returns the SET and each caller
    keeps its own branch.

    EXISTENCE-FILTERED against `worktree`: a declared path that is not on disk is not a sweepable
    directory. Root `tests/` is always included when it exists, so declaring a second surface never
    costs a project the first. Returns `[_ROOT_TEST_SWEEP_DIR]` when nothing resolves -- the engine's
    own build, a carrier-less repo, an unparseable carrier -- so today's behaviour is the default
    rather than a special case. Sorted, unique, repo-relative. Pure but for the directory-existence
    stat; every read bounded; no git, no subprocess; total (every exception swallowed)."""
    out: set = set()
    try:
        if ops is None:
            ops_path = worktree / CONSUMER_OPS_CONTRACT
            if ops_path.exists():
                # The ONE carrier parser (CHARTER P5) — the same `_load_ops_carrier_text` the pinned
                # leg reads its carrier through, so an unparseable carrier degrades to "declares
                # nothing" here exactly as it does there. `_read_yaml` is honoured when a caller that
                # already holds one injects it, so no call site opens a second parse path.
                ops = (_read_yaml(ops_path) if _read_yaml is not None
                       else _load_ops_carrier_text(ops_path.read_text(encoding="utf-8")))
        for paths in _pinned_declared_check_paths_by_layer(ops).values():
            for cand in paths:
                if Path(cand).name.lower() == _ROOT_TEST_SWEEP_DIR:
                    out.add(cand)
        ver = ops.get("verify") if isinstance(ops, dict) else None
        layers = ver.get("layers") if isinstance(ver, dict) else None
        for ly in (layers if isinstance(layers, list) else []):
            if not isinstance(ly, dict):
                continue
            for g in (ly.get("covers") or []):
                d = _covers_glob_test_dir(g)
                if d:
                    out.add(d)
    except Exception:
        out = set()
    resolved = set()
    for cand in out:
        try:
            if (worktree / cand).is_dir():
                resolved.add(cand)
        except Exception:
            continue
    try:
        if (worktree / _ROOT_TEST_SWEEP_DIR).is_dir():
            resolved.add(_ROOT_TEST_SWEEP_DIR)
    except Exception:
        pass
    return sorted(resolved) or [_ROOT_TEST_SWEEP_DIR]


def _declared_test_sweep_probe_files(worktree: Path, ops: "dict | None" = None,
                                     *, _read_yaml=None, _declared_test_sweep_paths) -> "list[Path]":
    """The `test_*.py` probe files under this consumer's DECLARED test dirs, sorted by name.

    The READ-side twin of `_declared_test_sweep_paths`: the three kernel readers that ask "does this
    consumer have real probes, and which?" all spelled it `(worktree / "tests").glob("test_*.py")`.
    One helper so a reader can never disagree with the sweep about where the probes are. Total: any
    failure yields `[]`, which each caller's own absence branch then interprets — this function makes
    no such judgement (see `_declared_test_sweep_dirs`)."""
    out: list = []
    seen: set = set()
    try:
        for d in _declared_test_sweep_paths(worktree, ops, _read_yaml=_read_yaml):
            for f in test_discovery.test_files(d):
                if f.name not in seen:
                    seen.add(f.name)
                    out.append(f)
    except Exception:
        return []
    return sorted(out, key=lambda f: f.name)


def _declared_test_sweep_paths(worktree: Path, ops: "dict | None" = None,
                               *, _read_yaml=None, _declared_test_sweep_dirs) -> "list[Path]":
    """`_declared_test_sweep_dirs` as ABSOLUTE paths under `worktree` — the form the sweep call sites
    hand to `_run_verify_tests`. One helper so no call site re-joins the repo-relative names itself."""
    return [worktree / d for d in _declared_test_sweep_dirs(worktree, ops, _read_yaml=_read_yaml)]


def _pinned_entry_core(entry, *, _PINNED_PREFIX) -> str:
    """The identity LINE of a verify-fail entry: its first line with the optional
    `[pinned/last-green] ` prefix stripped. ONE place isolates it, so the two first-line parsers
    below (`_surface_failing_assertions` + `_pinned_failure_test_file`) cannot drift on what an
    entry IS."""
    s = str(entry)
    first = s.splitlines()[0] if s.strip() else ""
    prefix = _PINNED_PREFIX   # T-11002: one definition, shared with the backstop's admission reader
    return first[len(prefix):] if first.startswith(prefix) else first


def _selection_periphery_freed(changed_paths, *, _SELECTION_PERIPHERY_FREED_PATHS) -> frozenset:
    """T-11511 — the subset of `changed_paths` freed from the `bin/**` arm of the verifier-surface
    refusal by EXACT membership in `_SELECTION_PERIPHERY_FREED_PATHS`. PURE — the sibling of
    `_selection_leaf_test_freed` (the `tests/**` arm's classifier) at the same granularity a human
    reasons about: one module, named.

    IT IS A CLASSIFIER, NOT A PROVER, and the distinction is deliberate. `_selection_reachability_freed`
    above PROVES non-participation from the call graph and returns a smaller set on any doubt; this one
    ASSERTS it from an audited list. Keeping them as two functions — unioned by the caller rather than
    folded together — is what stops either docstring becoming a half-truth about how its members were
    established.

    The `./` normalisation mirrors `_verify_implementation_touch_globs`, the one matching carrier this
    result is consumed by, so a path spelled either way is judged identically at both ends. Anything
    unreadable, oddly shaped or simply absent from the list is not freed: the empty set is the
    fail-closed answer and reproduces today's refusal exactly."""
    freed = set()
    for raw in changed_paths or ():
        p = str(raw).strip()
        if p.startswith("./"):
            p = p[2:]
        if p in _SELECTION_PERIPHERY_FREED_PATHS:
            freed.add(p)
    return frozenset(freed)


def _selection_participating_defs(source: str, roots=None, *, _SELECTION_DECISION_ROOTS) -> "frozenset | None":
    """T-11463 — the top-level defs of ONE module that PARTICIPATE in the selection decision, computed
    by REACHABILITY over the module's call graph. Returns None when participation CANNOT be
    established (unparseable source, or a root that the module does not define — a rename would
    otherwise silently empty the root set and free the whole file). PURE.

    THE GRAPH. A node is a top-level `def`; an edge f→g exists when g's name appears ANYWHERE inside
    f's body — as a call, a bare reference, a default, a keyword argument or a parameter name. That
    last part is not sloppiness: this codebase injects its host residues BY KEYWORD
    (`_is_verify_implementation_touch=_is_verify_implementation_touch`), so a citation-by-name IS the
    call edge here, and reading only `ast.Call` funcs would miss most of them. Over-broad edges can
    only ADD participants, i.e. refuse more — the safe direction.

    PARTICIPATING = DESCENDANTS ∪ ANCESTORS of `_SELECTION_DECISION_ROOTS`. Descendants are the code
    the decision EXECUTES; ancestors are the code that FEEDS or INVOKES it. Both are required: the
    ancestor half is what keeps `_land_integrate` (which composes the diff the selector reads and
    opts the sweep into governing), and the descendant half is what keeps the coverage-map
    derivation. NEITHER half looks at a name's SPELLING — that is the whole point of the card.

    `roots` (T-11876) parameterises ONLY the root set, never the reasoning. Omitted, it IS
    `_SELECTION_DECISION_ROOTS` and every call below this line behaves exactly as before. Supplied, it
    carries a NON-HOST module's roots — the defs the host injects back, derived by
    `_selection_host_injected_roots` — because an extracted module defines none of the host's root
    names and the unparameterised prover therefore refuses it outright. An EMPTY root set yields an
    empty participating set, which would free the WHOLE module: the caller, not this function, is
    what refuses there (see `_selection_reachability_freed`), so that the fail-closed decision sits at
    the one site that knows whether an empty derivation means "no edge" or "derivation failed"."""
    try:
        tree = ast.parse(source)
    except Exception:
        return None                                        # unparseable → cannot decide → refuse
    bodies: dict = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bodies.setdefault(node.name, []).append(node)
    names = set(bodies)
    roots = tuple(_SELECTION_DECISION_ROOTS if roots is None else roots)
    if not set(roots) <= names:
        return None                                        # a root moved or was renamed → refuse
    out: dict = {n: set() for n in names}                   # f → names f cites
    into: dict = {n: set() for n in names}                  # g → names citing g
    for n, nodes in bodies.items():
        for node in nodes:
            for sub in ast.walk(node):
                ident = None
                if isinstance(sub, ast.Name):
                    ident = sub.id
                elif isinstance(sub, ast.Attribute):
                    ident = sub.attr
                elif isinstance(sub, ast.keyword):
                    ident = sub.arg
                elif isinstance(sub, ast.arg):
                    ident = sub.arg
                if ident and ident in names and ident != n:
                    out[n].add(ident)
                    into[ident].add(n)

    def _closure(graph):
        seen, stack = set(), [r for r in roots]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(graph[cur])
        return seen

    return frozenset(_closure(out) | _closure(into))


def _selection_host_injected_roots(host_source: str, module_source: str,
                                   roots=None, *, _selection_participating_defs) -> "frozenset | None":
    """T-11876 — a NON-HOST module's selection roots: its own top-level defs that the HOST cites from
    inside a def the host's own prover already calls PARTICIPATING. PURE.

    WHY THIS IS THE RIGHT EDGE, and not a weaker "is mentioned anywhere in the host". The host does not
    call an extracted module's functions by the `_SELECTION_DECISION_ROOTS` names; T-11519..T-11525 left
    behind `@functools.wraps` RESIDUES and keyword INJECTION (`_is_verify_implementation_touch=…`,
    `_land_batch_verify_path_touch` bound into the host's `_verify_path_touch`). So the module's
    participation is inherited THROUGH the host: a def of M is a root of M exactly when some
    participating host def names it. That is the same citation-by-name-IS-a-call-edge reading
    `_selection_participating_defs` already documents, read one module boundary out — not a new rule.

    Returns None when participation cannot be established at all: either source unparseable, or the
    host's own prover refusing (a renamed root). None and EMPTY are deliberately different answers and
    the caller must not collapse them — None is "could not decide", empty is "decided: no edge found",
    and the caller refuses on both, for different reasons it can state.

    OVER-BROAD BY CONSTRUCTION, in the safe direction: a host local, parameter or keyword that merely
    SHARES a name with one of M's defs adds a root, which can only grow M's participating set, i.e.
    free LESS. It can never free more.

    `roots` (T-12005) parameterises ONLY the HOST's root set, and is the exact sibling of the
    parameter T-11876 added to `_selection_participating_defs` itself — passed straight through to it,
    never used here. Omitted, it IS `_SELECTION_DECISION_ROOTS` and every pre-existing caller behaves
    byte-identically. Supplied, it lets a SECOND decision-bearing module serve as the host: the
    unparameterised prover refuses any module that does not define EVERY root, and
    `bin/lib/verify_runner.py` defines nine of them, so without this the read would go blind on the
    root module that holds the selector itself."""
    try:
        host_tree = ast.parse(host_source)
        module_tree = ast.parse(module_source)
    except Exception:
        return None                                        # unparseable → cannot decide → refuse
    host_participating = _selection_participating_defs(host_source, roots=roots)
    if host_participating is None:
        return None                                        # host root moved/renamed → cannot decide
    module_defs = {n.name for n in module_tree.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if not module_defs:
        return frozenset()
    cited = set()
    for node in host_tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in host_participating:
            continue
        for sub in ast.walk(node):
            ident = None
            if isinstance(sub, ast.Name):
                ident = sub.id
            elif isinstance(sub, ast.Attribute):
                ident = sub.attr
            elif isinstance(sub, ast.keyword):
                ident = sub.arg
            elif isinstance(sub, ast.arg):
                ident = sub.arg
            if ident and ident in module_defs:
                cited.add(ident)
    return frozenset(cited)


def _selection_decision_reaches_root_handlers(module_source: str,
                                              root_module_sources, *, _SELECTION_DECISION_ROOTS, _selection_host_injected_roots) -> "frozenset | None":
    """T-12005 — the defs of ONE periphery module that BOTH handle a selection root AND are REACHED
    by the selection decision. The discriminator that tells a READ-ONLY REPLAY of a root from a
    PARTICIPANT in the decision. PURE; None when it cannot be decided.

    THE QUESTION IT ANSWERS, and why the name read it replaces could not. The T-11654 membership
    test's limb B asked whether a module NAMES a `_SELECTION_DECISION_ROOTS` symbol anywhere in its
    AST. That refuses a module which calls a root purely to MEASURE past lands — an oracle importing
    the engine's own predicate rather than restating it, which is the shape a replica-measures-the-
    replica rule positively requires (T-11973). Such a module is UPSTREAM of the decision: the
    decision never runs through it, and nothing in it can change what the decision decides. Reading
    the name alone cannot see that difference; reachability can.

    THE RULE IS A CONJUNCTION, and BOTH halves are load-bearing — MEASURED on this tree at the time
    of the change, against the live 36-member allowlist plus the two modules T-11654 refuses:
      * REACHED ALONE (T-11876's edge — a participating def of a root module cites a def of M) refuses
        SIX live members (events.py, evidence_custody.py, lockfile.py, observe.py, task.py,
        textutil.py) on generic utility names — `slug`, `append_event`, `open_flock_target` — cited
        inside the host's ANCESTOR defs, because `_land_integrate` feeds the decision AND calls half
        the codebase. Being called by something that also calls the decision is not being reached by
        the decision.
      * HANDLES-A-ROOT ALONE is exactly the name read this replaces, and admits nothing new.
    Their CONJUNCTION admits all 36 live members with zero false refusals, keeps
    `bin/lib/batch_landing.py` REFUSED (its `_land_prequeue_known_broken_refusal` both invokes
    `_shadow_select` and is cited by the host's participating defs) and admits a read-only replayer.

    FAIL-CLOSED IN EVERY DIRECTION — this decides what a land may NOT run, so PARTICIPATION is the
    cheap answer and non-participation is the one that must be proven. None (= the caller must
    REFUSE) on: an unparseable module, no root-module sources at all, an unparseable root module, a
    root module that defines NONE of the roots (the derivation has gone blind — a rename, a module
    moved), or the cross-module prover refusing. `frozenset()` is the DIFFERENT, DECIDED answer «no
    def of this module both handles a root and is reached»; the caller must not collapse the two, and
    the split is the same one `_selection_host_injected_roots` documents one boundary out.

    `root_module_sources` is passed IN rather than read from disk so the function stays PURE and can
    be exercised against a synthetic decision — the differential that proves it discriminates on
    REACHABILITY rather than on the name is a fixture whose only mutation is a call edge added inside
    `_shadow_select`, and that mutation is impossible to express against files on disk."""
    try:
        module_tree = ast.parse(module_source)
    except Exception:
        return None                                        # unparseable → cannot decide → refuse
    root_names = set(_SELECTION_DECISION_ROOTS)
    handlers = set()
    for node in module_tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            ident = None
            if isinstance(sub, ast.Name):
                ident = sub.id
            elif isinstance(sub, ast.Attribute):
                ident = sub.attr
            elif isinstance(sub, ast.keyword):
                ident = sub.arg
            elif isinstance(sub, ast.arg):
                ident = sub.arg
            if ident and ident in root_names:
                handlers.add(node.name)
                break
    if not handlers:
        return frozenset()                                 # decided: nothing here handles a root
    sources = list(root_module_sources or ())
    if not sources:
        return None                                        # nothing to reason from → refuse
    reached = set()
    for root_source in sources:
        try:
            root_tree = ast.parse(root_source)
        except Exception:
            return None                                    # unparseable root module → refuse
        own_roots = tuple(n.name for n in root_tree.body
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and n.name in root_names)
        if not own_roots:
            return None                                    # a root module defining no root → blind
        injected = _selection_host_injected_roots(root_source, module_source, roots=own_roots)
        if injected is None:
            return None                                    # the prover refused → refuse
        reached |= (injected & handlers)
    return frozenset(reached)


def _selection_changed_def_owners(source: str, line_ranges) -> "tuple | None":
    """T-11463 — the top-level defs OWNING the changed lines of one module; None when ANY changed line
    cannot be attributed to one. PURE. `line_ranges` are 1-based inclusive (start, end) spans in the
    NEW file, as a `git diff -U0` hunk header gives them.

    None IS THE COMMON, CORRECT ANSWER and it means REFUSE. A changed line outside every top-level def
    is a module-level statement — an import, or a constant such as `_SELECTION_RULE_VERSION` whose
    value IS the governing window — and no call-graph reasoning covers those, so the fence must not
    free the file. Decorators count as part of their def (`ast` gives `lineno` after them, which would
    leave a decorator edit unattributed and therefore refusing — the safe direction either way, but
    attributing it is the honest reading)."""
    try:
        tree = ast.parse(source)
    except Exception:
        return None
    spans = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            spans.append((start, node.end_lineno, node.name))
    owners = set()
    for lo, hi in line_ranges:
        for ln in range(lo, hi + 1):
            owner = next((nm for s, e, nm in spans if s <= ln <= e), None)
            if owner is None:
                return None                                # module-level line → cannot free
            owners.add(owner)
    return tuple(sorted(owners))


def _selection_diff_hunk_ranges(diff_text: str) -> "list | None":
    """T-11463 — the NEW-file line spans of a `git diff -U0` text; None when the diff carries a shape
    this fence must not reason about. PURE.

    None on a PURE DELETION hunk (`+0` lines): the removed lines exist only in the OLD file, so the
    NEW-file AST cannot attribute them, and a deletion inside the selection decision would otherwise
    read as touching nothing. Refusing there costs a full suite on a delete-only diff and is the only
    honest answer. An unrecognised header is likewise None, never a silent skip."""
    ranges = []
    saw = False
    for line in diff_text.splitlines():
        if not line.startswith("@@"):
            continue
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
        if not m:
            return None                                    # unparseable header → cannot decide
        saw = True
        start = int(m.group(1))
        count = 1 if m.group(2) is None else int(m.group(2))
        if count == 0:
            return None                                    # pure deletion → cannot attribute
        ranges.append((start, start + count - 1))
    return ranges if saw else None                         # no hunk at all → nothing proven


def _selection_reachability_freed(worktree: Path, base_rev: str, changed_paths, *,
                                  _run_git_cap, _SELECTION_REACHABILITY_FILES, _selection_changed_def_owners, _selection_diff_hunk_ranges, _selection_host_injected_roots, _selection_participating_defs, _SELECTION_REACHABILITY_HOST=_SELECTION_REACHABILITY_HOST) -> frozenset:
    """T-11463 — the subset of `changed_paths` PROVEN to touch NO def participating in the selection
    decision. The land's ONE opt-in into the reachability fence; everything else keeps refusing on the
    path glob. IMPURE (reads the merged tree through git); the reasoning it delegates to is pure.

    FAIL-CLOSED IN EVERY DIRECTION — this decides what a land may NOT run, so freeing is the
    exceptional branch and must be PROVEN. An unreadable blob, an unparseable module, a missing
    decision root, a module-level line, a pure deletion, or ANY exception yields a SMALLER freed set,
    never a larger one; in the limit it yields `frozenset()` and the land refuses exactly as it does
    today."""
    freed = set()
    for raw in changed_paths or ():
        path = str(raw).strip()
        if path.startswith("./"):
            path = path[2:]
        if path not in _SELECTION_REACHABILITY_FILES:
            continue
        try:
            blob = _run_git_cap(["show", f"HEAD:{path}"], worktree)
            if blob.returncode != 0:
                continue
            source = blob.stdout
            if path == _SELECTION_REACHABILITY_HOST:
                participating = _selection_participating_defs(source)
            else:
                # T-11876 — a NON-HOST module: its roots are the defs the host injects back. THREE
                # fail-closed rungs, each yielding a SMALLER freed set: the host blob must be
                # readable, the derivation must decide (None = a renamed host root), and it must
                # find at least ONE edge. An EMPTY root set is refused rather than treated as "no
                # participation": these two modules are exactly the ones the T-11654 membership test
                # REFUSES for the periphery allowlist, so "the host cites nothing of mine" is far
                # likelier to mean the derivation went blind (a rename, a residue rewritten) than
                # that a module the land runs through has genuinely detached. Freeing a whole module
                # on a silent derivation failure is the one direction that fails invisibly.
                host_blob = _run_git_cap(["show", f"HEAD:{_SELECTION_REACHABILITY_HOST}"], worktree)
                if host_blob.returncode != 0:
                    continue
                roots = _selection_host_injected_roots(host_blob.stdout, source)
                if not roots:
                    continue                               # None (undecidable) or empty (no edge)
                participating = _selection_participating_defs(source, roots)
            if participating is None:
                continue
            d = _run_git_cap(["diff", "-U0", base_rev, "HEAD", "--", path], worktree)
            if d.returncode != 0:
                continue
            ranges = _selection_diff_hunk_ranges(d.stdout)
            if not ranges:
                continue
            owners = _selection_changed_def_owners(source, ranges)
            if not owners:
                continue
            if all(o not in participating for o in owners):
                freed.add(path)
        except Exception:
            continue                                       # never freed on an error
    return frozenset(freed)


def _children_cpu_seconds() -> "float | None":
    """T-12073 — total CPU (user+sys) charged so far to REAPED child processes, or None where the
    platform cannot report it.

    Sampled on BOTH sides of a prep so the DELTA is that prep's own CPU. The delta is trustworthy for
    a TIMED-OUT prep specifically because `subprocess.run` kills AND `wait()`s its child before
    re-raising, so the killed prep IS reaped and IS charged here — no sampler thread, no new store,
    two syscalls around a call that already happens. Bound, stated rather than hidden: `RUSAGE_CHILDREN`
    is process-wide and counts only reaped descendants, so a prep that leaves grandchildren behind is
    under-counted. That skews toward reporting LESS CPU, i.e. toward calling a stall a stall — the
    direction that cannot invent a WAIT-dominated verdict for work that actually ran on a CPU.

    NEVER RAISES (the `_verify_contention_context` contract, reused): a diagnostic must never mask the
    abort it annotates."""
    try:
        import resource
        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        return float(ru.ru_utime) + float(ru.ru_stime)
    except Exception:
        return None


def _prep_timeout_work_signal(cpu_seconds: "float | None", wall_seconds: "float | None",
                              stdout: "str | bytes | None", stderr: "str | bytes | None",
                              *, tail_lines: int = 12, tail_chars: int = 800, _PREP_WAIT_DOMINATED_CPU_FRACTION=_PREP_WAIT_DOMINATED_CPU_FRACTION) -> str:
    """T-12073 / X-1265 — say what a timed-out verify prep was WAITING ON, before naming the bound raise.

    The defect this closes is a message that was accurate and still misleading. The prep TIMEOUT refusal
    named exactly one remedy — raise the layer's `timeout:` / `verify.timeout_seconds:` — so on <project>
    T-0501 it steered a worker (T-0479) and then a card fix toward raising a 300s bound to absorb a ~375s
    wait that installs nothing: `npm ci` on a WARM cache ran 379.0s with the advisory security-audit HTTP
    call on versus 3.38s with it off, at ~2.9s CPU EITHER WAY. Both numbers that disambiguate that were
    obtainable at the seam and neither was printed, so the only named move was the blind stretch
    SPEC-0103 forbids — and a raised bound would have made the stall permanent rather than visible.

    So this reports, in order: the prep's CPU-seconds against its wall-seconds, ONE reading of that
    ratio (WAIT-dominated: low CPU, high wall — a stalled network/audit call, not work; vs
    WORK-dominated: the prep really was busy), and the tail of the output the prep had produced when its
    bound expired — which the timeout branch captured and then DISCARDED, though the non-zero-exit branch
    right below it already tails the same streams.

    REPORT-ONLY, exactly like its sibling `_verify_contention_context` (T-10566), whose shape this
    reuses: same fire, same `timed-out` outcome, same failed land, no exit code moved, no new store /
    flag / event / gate. The two are complementary and both print — contention answers "was the BOX
    starved", this answers "was the PREP waiting", and a quiet box stalled on a network call shows
    nothing on the first axis and everything on the second.

    DEGRADES rather than omits: an unreportable CPU figure yields a wall-only line (the reading is
    withheld, not guessed), and an empty capture STATES that it was empty — a silent gap is
    indistinguishable from a gap nobody looked for."""
    def _text(chunk) -> str:
        if chunk is None:
            return ""
        if isinstance(chunk, (bytes, bytearray)):
            # Measured (T-12073): under `capture_output=True, text=True` a `TimeoutExpired` still
            # carries BYTES — CPython's POSIX `_communicate` raises with the undecoded partial buffers
            # and run()'s text-mode decode only happens after the select loop it never leaves. So the
            # str-typed happy path is the one that does NOT occur here; decode defensively.
            return bytes(chunk).decode("utf-8", "replace")
        return str(chunk)

    lines = []
    # A nonsensical pair (either figure absent or negative, or a non-positive wall) is REFUSED a
    # reading rather than clamped into one — a fabricated 0%-of-a-core would read as a confident
    # WAIT-dominated verdict, which is precisely the claim the missing measurement cannot support.
    if (cpu_seconds is None or wall_seconds is None or wall_seconds <= 0 or cpu_seconds < 0):
        lines.append("WHAT THE PREP WAS DOING — wall {} (CPU time unavailable on this platform, so no "
                     "wait-vs-work reading is offered).".format(
                         "unmeasured" if wall_seconds is None else f"{wall_seconds:.1f}s"))
    else:
        frac = cpu_seconds / wall_seconds
        if frac <= _PREP_WAIT_DOMINATED_CPU_FRACTION:
            reading = ("WAIT-dominated — it burned almost no CPU while the clock ran, so it was BLOCKED "
                       "(a stalled network or registry/advisory-audit call, a hung DNS/proxy, a lock), "
                       "NOT doing work. Raising the bound would absorb the wait, not remove it: find and "
                       "cut the wait first")
        else:
            reading = ("WORK-dominated — it spent the wall time actually running, so this prep really is "
                       "this slow on this box (or was starved of CPU — see any contention line below)")
        lines.append(f"WHAT THE PREP WAS DOING — CPU {cpu_seconds:.1f}s over wall {wall_seconds:.1f}s "
                     f"({frac * 100:.1f}% of one core): {reading}.")

    captured = (_text(stdout) + _text(stderr)).strip()
    if captured:
        tail = "\n".join(captured.splitlines()[-tail_lines:])[-tail_chars:]
        lines.append(f"LAST PREP OUTPUT BEFORE THE BOUND EXPIRED:\n{tail}")
    else:
        lines.append("LAST PREP OUTPUT BEFORE THE BOUND EXPIRED: none — the prep produced no output at "
                     "all before it was killed (itself a signal: it was stuck before it got started).")
    return "\n".join(lines)


def _verify_bound_source(declared: "float | None", effective: float, rung: "str | None" = None) -> str:
    """T-10931 (AC2) — NAME which rung of the T-10257 precedence chain produced an already-resolved
    verify bound, so a killed-by-bound abort tells an operator WHERE to change the number (or that
    nobody declared one) instead of just quoting a bare figure.

    STRICTLY a labeller, NEVER a second resolver (CHARTER §P5): it takes the value
    `_verify_test_timeout_seconds` ALREADY returned and reports which input it matches. It cannot
    disagree with the resolver about the bound, because it never computes one — a divergence could only
    ever change the WORDS in a message, never which bound is enforced. The rungs are checked in the
    resolver's own precedence order, so an env override that happens to equal the declaration is
    attributed to the env, exactly as the resolver decided it. T-13969: `rung` is the resolver's own
    `source_out` answer for THIS resolution (env | declared | machine-file | default) — given, it is
    the label, so a settings file rewritten after the resolution cannot relabel the bound applied
    (audit-post pass-1 finding 1). Without it (a resolver that reports no rung) the env and
    machine-file rungs are read back through `machine_settings.in_force`, the resolver's own reader
    (SPEC-1031 rule 4 — the machine file sits just above the built-in default)."""
    labels = {"env": "set by the YITC_VERIFY_TEST_TIMEOUT env escape hatch",
              "declared": "set by the layer's declared `timeout:` / `verify.timeout_seconds:`",
              "machine-file": ("set by this machine's settings file (`config set YITC_VERIFY_TEST_TIMEOUT`) "
                               "— NO timeout was declared for this layer"),
              "default": "the built-in default — NO timeout was declared for this layer"}
    if rung in labels:
        return labels[rung]
    from lib import machine_settings              # deferred: the hot import graph is unchanged
    try:
        row = machine_settings.in_force("YITC_VERIFY_TEST_TIMEOUT")
    except Exception:                             # noqa: BLE001 — a labeller never breaks its caller
        row = {"source": "built-in", "value": None}
    if row["source"] == "env" and row["value"] == effective:
        return labels["env"]
    if declared is not None:
        try:
            if float(declared) == effective:
                return labels["declared"]
        except (TypeError, ValueError):
            pass
    if row["source"] == "machine-file" and row["value"] == effective:
        return labels["machine-file"]
    return labels["default"]


# T-13925 (X-1972) — the links the PINNED leg's own priming made (`rebaseline_currency._pinned_env_prime`,
# T-11182). A prep refuses a dependency directory that is a link or leads outside its worktree; these are
# the one exception, and they are recognised by PROVENANCE — the priming records each `(link, target)` pair
# here as it creates it — never by their shape: a hand-made link of exactly the primed form is not in the
# record and is refused (audit-pre finding fp1:46dccde22d48721e). Process-local by design: the pinned leg's
# layers run in the process that primed them, and a process that never primed can only refuse, never exempt.
_PRIMED_DEPENDENCY_LINKS: set = set()
_PRIMED_DEPENDENCY_LINKS_LOCK = threading.Lock()


def _primed_link_key(link) -> str:
    """The link's location with its PARENT resolved (the link itself is never followed)."""
    link = Path(link)
    return os.path.join(os.path.realpath(link.parent), link.name)


def _record_primed_dependency_link(link, target) -> None:
    """Record one link the pinned-leg priming created (T-13925). Called only by `_pinned_env_prime`."""
    with _PRIMED_DEPENDENCY_LINKS_LOCK:
        _PRIMED_DEPENDENCY_LINKS.add((_primed_link_key(link), str(target)))


def _is_primed_dependency_link(dep: Path) -> bool:
    """True only when `dep` is a link the priming recorded AND it still points where it was made to."""
    try:
        if not dep.is_symlink():
            return False
        pair = (_primed_link_key(dep), os.readlink(dep))
    except OSError:
        return False
    with _PRIMED_DEPENDENCY_LINKS_LOCK:
        return pair in _PRIMED_DEPENDENCY_LINKS


def _prep_dependency_link_refusal(root: Path, workdir: Path, layer_name: str) -> "str | None":
    """T-13925 (X-1972, SPEC-0152 rule 16 fail-closed) — the reason a dependency-installing prep must NOT
    start in `workdir`, or None. A `node_modules` there that is a LINK, or that resolves outside the
    worktree `root`, would have `npm ci` install into (or fail on) a tree that is not this worktree's —
    another checkout's dependencies, possibly owned by another user. The pinned leg's own primed links
    pass (`_is_primed_dependency_link`); no leg skips the check."""
    dep = workdir / "node_modules"
    try:
        is_link = dep.is_symlink()
        if not is_link and (not dep.exists() or dep.resolve().is_relative_to(root)):
            return None
    except OSError:
        is_link = True
    if _is_primed_dependency_link(dep):
        return None
    try:
        target = os.readlink(dep) if is_link else str(dep.resolve())
    except OSError:
        target = "<unreadable>"
    return (f"land(consumer): verify layer {layer_name!r} prep REFUSED before the install: the dependency "
            f"directory {dep} is {'a link' if is_link else 'a path'} leading to {target}, so `npm ci` "
            f"would install into (or fail on) a tree outside this worktree. Remove the link and let the "
            f"prep install a real node_modules in the worktree (for a hand run, run `npm ci` in the "
            f"worktree itself) — fail-closed (SPEC-0152 rule 16).")


def _run_layer_prep(worktree: Path, layer_name: str, prep: dict, *, _verify_test_timeout_seconds,
                    _live_land_frontier=None, _load_avg=None, _cpu_count=None,
                    declared_timeout: "float | None" = None, _verify_contention_context, _children_cpu_seconds, _prep_timeout_work_signal, _verify_bound_source) -> dict:
    """SPEC-0152 rule 16 (the `prep:` sub-field — T-10020 contract, T-10021 land-runner leg / X-0140).

    `declared_timeout` (T-10257) is the layer's resolved declared bound — the prep shares its layer's
    budget, so a project that declares a long-enough timeout for a slow layer does not have its prep
    cut short by the global default. `None` = no declaration; the resolver falls back as usual.

    Run a DECLARED verify layer's dependency-prep INSIDE the fresh land worktree BEFORE its `command:`,
    fail-closed. Returns `{'bad': [<reason>...], 'record': <dict|None>}` — `bad` non-empty means the prep
    FAILED the land (the caller does NOT run the layer's command best-effort against wrong deps — no
    false-green); `record` (present only on success) is the machine-checkable `verify_layer_prep` payload
    `{layer, lockfile_hash, package_manager, runtime}` the caller emits.

    The kernel BUILT-IN mode is `npm-ci`: a CLEAN install from the project LOCKFILE + declared RUNTIME
    (never a mutate-in-place `npm install`). FAIL-CLOSED (SPEC-0152 rule 16) if ANY prep-input dimension
    cannot be matched — the mode, the manifest, the lockfile, the package-manager, or the declared runtime
    is missing / un-resolvable / mismatched — OR a project-controlled path pin escapes the worktree (the
    audit-pre HIGH-1 containment floor: pins are worktree-RELATIVE only; an absolute pin or a `..`/symlink
    escape is refused, and — T-13925 — so is a dependency directory in the workdir that is a link or
    resolves outside the worktree, unless the pinned leg's own priming recorded it, so `npm ci` never runs
    against files outside the prepared worktree). The kernel
    checks the STANCE + resolvability, never the command's/lockfile's correctness (rule 3)."""
    import hashlib
    import shutil
    import subprocess
    root = worktree.resolve()

    def _contained(rel, kind):
        """Resolve a project-controlled path pin against the worktree; fail-closed unless it is
        worktree-relative AND lands inside the worktree (no absolute pin, no `..`/symlink escape).
        Returns (resolved_path_or_None, error_or_None)."""
        rel_s = str(rel or "").strip()
        if not rel_s:
            return None, None
        if os.path.isabs(rel_s):
            return None, (f"land(consumer): verify layer {layer_name!r} prep {kind} pin {rel_s!r} is "
                          f"ABSOLUTE — pins must be worktree-relative (SPEC-0152 rule 16 fail-closed).")
        p = (worktree / rel_s).resolve()
        if not p.is_relative_to(root):
            return None, (f"land(consumer): verify layer {layer_name!r} prep {kind} pin {rel_s!r} escapes "
                          f"the worktree ({p}) — refused (SPEC-0152 rule 16 fail-closed).")
        return p, None

    mode = str(prep.get("mode") or "").strip()
    if mode != "npm-ci":
        return {"bad": [f"land(consumer): verify layer {layer_name!r} prep mode {mode!r} is not a built-in "
                        f"prep mode (only `npm-ci` in this slice — SPEC-0152 rule 16 fail-closed)."],
                "record": None}
    # workdir — the sub-dir the install + layer command run in (default: the worktree root).
    wd, err = _contained(prep.get("workdir"), "workdir")
    if err:
        return {"bad": [err], "record": None}
    workdir = wd or root
    if not workdir.is_dir():
        return {"bad": [f"land(consumer): verify layer {layer_name!r} prep workdir {prep.get('workdir')!r} "
                        f"is not a directory in the worktree — fail-closed (SPEC-0152 rule 16)."],
                "record": None}
    # T-13925 (X-1972): before anything can start the install, refuse a dependency directory that would
    # carry it outside the worktree.
    _link_reason = _prep_dependency_link_refusal(root, workdir, layer_name)
    if _link_reason:
        return {"bad": [_link_reason], "record": None}
    # manifest (package.json) — required, else un-resolvable.
    mf, err = _contained(prep.get("manifest"), "manifest")
    if err:
        return {"bad": [err], "record": None}
    manifest = mf or (workdir / "package.json")
    if not manifest.is_file():
        return {"bad": [f"land(consumer): verify layer {layer_name!r} prep manifest not found ({manifest}) "
                        f"— fail-closed (SPEC-0152 rule 16)."], "record": None}
    # lockfile — required (npm ci installs FROM the lockfile), else un-resolvable.
    lf, err = _contained(prep.get("lockfile"), "lockfile")
    if err:
        return {"bad": [err], "record": None}
    lockfile = lf or (workdir / "package-lock.json")
    if not lockfile.is_file():
        return {"bad": [f"land(consumer): verify layer {layer_name!r} prep lockfile not found ({lockfile}) "
                        f"— fail-closed (npm ci needs the lockfile; SPEC-0152 rule 16)."], "record": None}
    # package-manager — for `npm-ci` mode it MUST be npm, and npm MUST be resolvable on PATH.
    pm = str(prep.get("package_manager") or "npm").strip()
    if pm != "npm":
        return {"bad": [f"land(consumer): verify layer {layer_name!r} prep package_manager {pm!r} does not "
                        f"match the `npm-ci` mode (needs `npm`) — fail-closed (SPEC-0152 rule 16)."],
                "record": None}
    if not shutil.which(pm):
        return {"bad": [f"land(consumer): verify layer {layer_name!r} prep package-manager {pm!r} is not on "
                        f"PATH — un-resolvable, fail-closed (SPEC-0152 rule 16)."], "record": None}
    # T-10931 — the prep's INNER subprocess bound is resolved ONCE, HERE, from the SAME declared
    # precedence chain as the outer one (`YITC_VERIFY_TEST_TIMEOUT` env · the layer's `timeout:` · the
    # section's `verify.timeout_seconds:` · the machine settings value · the built-in default — SPEC-1031
    # rule 4). It used to be hoisted only for `npm ci`
    # below, while the runtime probe carried a HARDCODED 30s — a bound nobody declared, silently
    # overriding the declaration T-10257 exists to honour, one level further in.
    # T-13969: the label names the rung THIS resolution took (the resolver's `source_out`), never a
    # second read of the settings; a resolver that takes no such keyword falls back to the read-back.
    _rung: list = []
    try:
        effective_timeout = _verify_test_timeout_seconds(declared_timeout, source_out=_rung)
    except TypeError:
        effective_timeout = _verify_test_timeout_seconds(declared_timeout)
    bound_source = _verify_bound_source(declared_timeout, effective_timeout, _rung[0] if _rung else None)
    # runtime — detect the actual node; match the declared `node@<major>` when pinned (else the npm-ci
    # install still needs a resolvable node runtime). A missing/mismatched runtime is fail-closed.
    node_bin = shutil.which("node")
    detected = None
    runtime_probe_timeout = None    # T-10931: set ONLY when the probe was KILLED BY ITS BOUND.
    if node_bin:
        try:
            nv = subprocess.run([node_bin, "--version"], capture_output=True, text=True,
                                timeout=effective_timeout)
            if nv.returncode == 0:
                detected = nv.stdout.strip().lstrip("v")
        except subprocess.TimeoutExpired:
            # T-10931 (AC2) — a KILLED-BY-BOUND probe is NOT the same fact as an unresolvable runtime,
            # and it must not be reported as one. The blanket `except Exception` below used to collapse
            # both into `detected = None`, so a STARVED host (load 77 on 32 cores, 2026-08-10) produced
            # the abort "node is not resolvable on PATH" for a node that IS installed and fine — a false
            # statement about the tree, indistinguishable from a real missing-runtime regression. Record
            # the bound + which declaration set it, and let the fail-closed branches below say so.
            runtime_probe_timeout = effective_timeout
            detected = None
        except Exception:
            detected = None
    # T-10931 — the ONE place the unresolved-runtime CAUSE is turned into the operator-facing reason, so
    # every fail-closed runtime branch below inherits it instead of each re-deriving (or omitting) it.
    # The two causes get DIFFERENT SENTENCES, not a shared claim plus a footnote (audit-post absorb): a
    # killed-by-bound probe must never LEAD with "node is not resolvable on PATH", because that states
    # something the run did not establish — the probe never answered, so node was not proven absent.
    _runtime_unresolved = (
        "node is not resolvable on PATH" if runtime_probe_timeout is None else
        f"the `node --version` runtime probe was KILLED BY ITS BOUND after {runtime_probe_timeout:g}s "
        f"({bound_source}) and never answered — node was NOT proven absent. This is host starvation, "
        f"not a missing runtime: re-run, or raise the layer's `timeout:` (or `verify.timeout_seconds:`) "
        f"if the box is legitimately this slow")
    declared_rt = str(prep.get("runtime") or "").strip()
    if declared_rt:
        name, _, want = declared_rt.partition("@")
        if name.strip() != "node":
            return {"bad": [f"land(consumer): verify layer {layer_name!r} prep runtime {declared_rt!r} names "
                            f"a runtime other than `node` — un-resolvable for `npm-ci`, fail-closed."],
                    "record": None}
        if detected is None:
            return {"bad": [f"land(consumer): verify layer {layer_name!r} prep runtime {declared_rt!r} "
                            f"declared but {_runtime_unresolved} — fail-closed (SPEC-0152 rule 16)."],
                    "record": None}
        want_major = want.strip().lstrip("v").split(".")[0]
        have_major = detected.split(".")[0]
        if want_major and want_major != have_major:
            return {"bad": [f"land(consumer): verify layer {layer_name!r} prep runtime MISMATCH — declared "
                            f"{declared_rt!r} but node {detected} is installed (major {have_major} != "
                            f"{want_major}) — fail-closed (SPEC-0152 rule 16, no false-green)."],
                    "record": None}
    elif detected is None:
        return {"bad": [f"land(consumer): verify layer {layer_name!r} prep needs a node runtime for `npm ci` "
                        f"but {_runtime_unresolved} — fail-closed (SPEC-0152 rule 16)."],
                "record": None}
    runtime_matched = f"node@{detected}" if detected else "node@unknown"
    # CLEAN install from the lockfile (`npm ci`), bounded by the layer's verify timeout (the prep shares
    # its layer's budget). Env inherited — the project/CI configures registry/offline; the runner never
    # forces flags. Non-zero/timeout is fail-closed (stale lockfiles, native-addon rebuilds — the 7 modes).
    # `effective_timeout` is the SAME resolution hoisted above the runtime probe (T-10931) — one resolve
    # per prep, so the probe and the install can never be bounded by two different numbers.
    # T-12073: sample the two figures a TIMEOUT refusal needs to say what the prep was WAITING ON.
    # Taken here, immediately around the call, so the delta is this prep's own — not the runtime probe's.
    _cpu_before, _wall_before = _children_cpu_seconds(), time.monotonic()
    try:
        r = subprocess.run([pm, "ci"], cwd=str(workdir), capture_output=True, text=True,
                           timeout=effective_timeout)
    except subprocess.TimeoutExpired as _te:
        # T-12073: the low-CPU-high-wall reading + the captured output tail, printed BEFORE the
        # bound-raise remedy below — which is unchanged. The remedy was accurate and still misleading
        # as the ONLY named move (X-1265): it sent a worker to raise a 300s bound to absorb a ~375s wait
        # that installed nothing. Report-only, like its T-10566 sibling; no gate, no store, no flag.
        _cpu_after = _children_cpu_seconds()
        # Raw deltas, deliberately un-clamped: `_run_layer_prep` is state-checked (T-10257 E5) to hold
        # no bound-stretching arithmetic anywhere in its body, and that guard reads the function TEXT —
        # so a clamp here, however diagnostic, would read as a stretch. Both clocks are monotonic
        # anyway, and it is the builder that refuses to read a nonsensical pair.
        _ws = _prep_timeout_work_signal(
            None if (_cpu_before is None or _cpu_after is None) else _cpu_after - _cpu_before,
            time.monotonic() - _wall_before,
            getattr(_te, "stdout", None), getattr(_te, "stderr", None))
        # T-10566: annotate with the contention context when the box was loaded — the prep SHARES its
        # layer's budget (T-10257), so it starves identically and must not be a diagnostic blind spot.
        # None on a quiet box ⇒ the message is unchanged.
        _cc = _verify_contention_context(_live_land_frontier=_live_land_frontier, _load_avg=_load_avg,
                                         _cpu_count=_cpu_count)
        return {"bad": [f"land(consumer): verify layer {layer_name!r} prep `{pm} ci` TIMED OUT after "
                        f"{effective_timeout}s ({bound_source}) in {workdir} — KILLED BY ITS BOUND, not a "
                        f"failing install: fail-closed (SPEC-0152 rule 16).\n{_ws}\nRaise the "
                        f"layer's `timeout:` (or `verify.timeout_seconds:`) if the prep is legitimately "
                        f"slower than that." + (f"\n{_cc}" if _cc else "")], "record": None,
                "output": (str(getattr(_te, "stdout", "") or "")
                           + str(getattr(_te, "stderr", "") or ""))}
    if r.returncode != 0:
        tail = (r.stdout + r.stderr).strip()[-500:]
        return {"bad": [f"land(consumer): verify layer {layer_name!r} prep `{pm} ci` FAILED (exit "
                        f"{r.returncode}) in {workdir} — fail-closed (a stale/mismatched lockfile never "
                        f"false-greens the layer).\n{tail}"], "record": None,
                "output": r.stdout + r.stderr}
    lockfile_hash = hashlib.sha256(lockfile.read_bytes()).hexdigest()
    print(f"land(consumer): verify layer {layer_name!r} prep OK: `{pm} ci` in {workdir} "
          f"(runtime {runtime_matched}, lockfile {lockfile.name})")
    return {"bad": [], "record": {"layer": layer_name, "lockfile_hash": lockfile_hash,
                                  "package_manager": pm, "runtime": runtime_matched}}


def _declared_verify_timeout(sec: dict, key: str) -> "float | None":
    """SPEC-0152 rule 16 (T-10257 / X-0204): read a DECLARED verify timeout — a layer's `timeout:` or the
    section's `timeout_seconds:` — as positive seconds. Returns None iff the key is ABSENT; raises ValueError
    on a PRESENT-but-malformed value so the caller fails CLOSED.

    A declared timeout is a positive NUMBER: not null, not a string (`timeout: "900"` is a typo, not a
    declaration), not a bool (`timeout: true` is a stance, not a bound), not non-positive. The accepted set
    is EXACTLY `_hook_verify`'s (`bin/lib/init.py`) — the land-time reader must never be LOOSER than the
    declare-time shape check, or a carrier `init` rejects would still run at land. Presence is keyed off
    the KEY, not the value, so an explicit `timeout: ~` is malformed rather than silently absent.

    Fail-CLOSED, unlike the ENV escape hatch's fail-safe fall-through: a typo'd declaration must never
    silently revert to the global default it was written to replace."""
    if key not in sec:
        return None
    raw = sec.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{raw!r} is not a number of seconds (declare an unquoted positive number)")
    if not (raw > 0):
        raise ValueError(f"{raw!r} is not a POSITIVE number of seconds")
    return float(raw)


def _declared_independent_layers(sec: dict, layers) -> set:
    """SPEC-0152 rule 16 §independent_layers (T-12585 / X-1396): read the OPT-IN section-level
    `verify.independent_layers:` — the names of the declared layers the project asserts share nothing
    with EACH OTHER (no host port / compose project / database / build cache / tree write, their `prep:`
    included), which the land runner may therefore run OVERLAPPED. Returns the EMPTY set iff the key is
    ABSENT (today's serial path, byte-identical); raises ValueError on a PRESENT-but-malformed value so
    the caller fails CLOSED before any layer runs.

    The accepted set is EXACTLY `_hook_verify`'s (`_independent_layers_shape_errors`, bin/lib/init.py):
    a list of non-empty strings, no duplicates, every name matching a `layers[].layer` declared in the
    same section — the land-time reader must never be LOOSER than the declare-time shape check, or a
    carrier `init` rejects would still run at land. Presence is keyed off the KEY, so an explicit
    `independent_layers: ~` is malformed rather than silently absent (the `timeout_seconds:` stance). A
    name matching no declared layer is a BROKEN declaration, never a silent no-op (the `health.layers`
    stance). Shape, not value (rule 3): whether the named layers ARE independent is the project's
    assertion — the kernel cannot infer it from arbitrary commands, exactly as for
    `combined_candidate_safe`."""
    if "independent_layers" not in sec:
        return set()
    raw = sec.get("independent_layers")
    if not isinstance(raw, list):
        raise ValueError(f"{raw!r} is not a list of layer names")
    declared = {str(ly.get("layer")).strip() for ly in (layers if isinstance(layers, list) else [])
                if isinstance(ly, dict) and isinstance(ly.get("layer"), str) and ly.get("layer").strip()}
    out: set = set()
    for j, name in enumerate(raw):
        if not (isinstance(name, str) and name.strip()):
            raise ValueError(f"independent_layers[{j}] = {name!r} is not a non-empty layer name string")
        name = name.strip()
        if name in out:
            raise ValueError(f"independent_layers[{j}] = {name!r} is a duplicate")
        if name not in declared:
            raise ValueError(f"independent_layers[{j}] = {name!r} matches no declared `layers[].layer`")
        out.add(name)
    return out


#: T-14205 (SPEC-0152 rule 16 §layer_worker_shares, public issue #204) — the variable naming, to every
#: layer command, the layers this verify run executes; written beside `YITC_VERIFY_LAYER_WORKERS`.
VERIFY_SELECTED_LAYERS_ENV = "YITC_VERIFY_SELECTED_LAYERS"


def _verify_selected_layers(layers, not_run, *, timeout_ok) -> list:
    """T-14205 (SPEC-0152 rule 16 §layer_worker_shares) — the names, in declaration order, of the
    declared layers whose command THIS verify run executes: every layer the runner's loop reaches
    RUNNABLE. It drops what that loop drops before a command runs — a non-mapping entry, a waived
    layer, a layer with no command, a layer whose `timeout:` is malformed (`timeout_ok(ly)` false) —
    and every name in `not_run` (the subject_globs skip, the Stage-6 credit, the pre-deploy
    exclusion, as the caller decided them). Computed BEFORE any layer runs, because the loop runs a
    layer as soon as it reaches it. A FACT the runner already holds, passed through: no share is
    read, nothing is divided. PURE."""
    out = []
    for i, ly in enumerate(layers if isinstance(layers, list) else ()):
        if not isinstance(ly, dict):
            continue
        name = str(ly.get("layer") or "").strip() or f"[{i}]"
        waiver = ly.get("waiver")
        if isinstance(waiver, dict) and str(waiver.get("reason") or "").strip():
            continue
        cmd = ly.get("command")
        if not (isinstance(cmd, str) and cmd.strip()) or not timeout_ok(ly) or name in not_run:
            continue
        out.append(name)
    return out


#: T-14190 (SPEC-0152 rule 16 §pre_deploy_layer_worker_shares) — the one home of the pre-deploy run's
#: share-table key: the table that run (and its lone-layer re-run) applies in place of `layer_worker_shares`.
PRE_DEPLOY_WORKER_SHARES_KEY = "pre_deploy_layer_worker_shares"


def _declared_layer_worker_shares(sec: dict, layers, key: str = "layer_worker_shares") -> dict:
    """SPEC-0152 rule 16 §layer_worker_shares (T-12585): read the OPT-IN section-level
    `verify.layer_worker_shares:` — a MAPPING from a declared layer name to that layer's FRACTION of
    the land's worker allotment. Returns `{}` iff the key is ABSENT; raises ValueError on a
    PRESENT-but-malformed value so the caller fails CLOSED before any layer runs.

    WHAT THE KERNEL DOES WITH IT, exactly, and what it deliberately does NOT (owner design,
    2026-09-16). The kernel declares the FORM and keeps publishing the land's allotment, whole, in the
    ONE universal variable `YITC_VERIFY_LAYER_WORKERS` (T-12589) — to EVERY layer, concurrent or
    serial, unchanged by this key. The kernel does NOT compute shares, does NOT divide, and does NOT
    publish a per-layer number: WHICH layer deserves WHICH share is the project's judgement, since only
    the project knows what its layers do, and the project scales its OWN runners from the allotment it
    reads. The declared share is RECORDED on the layer's outcome row (`declared_worker_share`),
    report-only, beside the CPU the layer actually consumed (T-12589 / T-12633) — so a project can
    check its own split against its own measurements. Nothing reads it to decide anything.

    A FRACTION, never a core count: a change to the kernel's allotment then re-splits automatically
    and no project is ever rewritten. The SUM across layers is deliberately NOT checked — there is no
    kernel-side over-allocation guard, because a normalized split cannot exceed the whole by
    construction, and the floor case (a share floors at one worker, so a small allotment with many
    layers can make those floors sum above it) belongs to the project's own arithmetic.

    The accepted set is EXACTLY `_hook_verify`'s (`_layer_worker_shares_shape_errors`,
    bin/lib/init.py) — the land-time reader must never be LOOSER than the declare-time shape check.
    Presence is keyed off the KEY, so an explicit `layer_worker_shares: ~` is malformed rather than
    silently absent (the `timeout_seconds:` / `independent_layers:` stance). Shape, not value (rule 3).
    A layer with no entry is simply unsplit — it reads the whole allotment, exactly as today.

    `key` names the table read (T-14190): the pre-deploy run reads `PRE_DEPLOY_WORKER_SHARES_KEY` with
    this same accepted set, so its table can never be looser than the ordinary one."""
    if key not in sec:
        return {}
    raw = sec.get(key)
    if not isinstance(raw, dict):
        raise ValueError(f"{raw!r} is not a mapping of layer name -> fraction")
    declared = {str(ly.get("layer")).strip() for ly in (layers if isinstance(layers, list) else [])
                if isinstance(ly, dict) and isinstance(ly.get("layer"), str) and ly.get("layer").strip()}
    out: dict = {}
    for name, share in raw.items():
        if not (isinstance(name, str) and name.strip()):
            raise ValueError(f"{key} key {name!r} is not a non-empty layer name string")
        lname = name.strip()
        if lname not in declared:
            raise ValueError(f"{key}[{lname!r}] matches no declared `layers[].layer`")
        if not (isinstance(share, (int, float)) and not isinstance(share, bool) and 0 < share <= 1):
            raise ValueError(f"{key}[{lname!r}] = {share!r} is not a fraction in (0, 1] "
                             f"— a SHARE of the allotment, never a core count")
        out[lname] = share
    return out


def _layer_share_load_record(rows, allotment, cores) -> "dict | None":
    """T-13876 (SPEC-0152 rule 16 §layer_worker_shares) — the REPORT-ONLY reading of what a project's
    declared shares ask for at the allotment one verify published: the sum of the shares of the
    layers that verify RAN, times that allotment, against the host's processor count.

    WHY IT EXISTS. The sum of the shares is deliberately unchecked (owner design, 2026-09-16) and
    stays so: a project may declare a sum above one. For such a declaration a change of the
    allotment — a machine setting, a new host, a changed default — multiplies the workers its layers
    ask for, and nothing said so (GitHub issue 85: 3.07 x 13 became 3.07 x 28 on 32 cores, unseen
    for three days). This returns the three numbers; it judges none of them.

    `rows` are the verify's layer outcome rows. THE SUM IS OVER WHAT EXECUTED — the membership
    `per_layer_durations` and `_layer_overlap_ratio_record` use, by the same predicate: a row with
    no int `duration_ms` (waived / malformed / skipped-disjoint-subject) ran nothing and asks for
    nothing. A row's `declared_worker_share` is read only when it is the shape the declaration
    reader admits (a non-bool number in (0, 1]); anything else contributes nothing.

    AN UPPER BOUND, NEVER A MEASUREMENT: `worker_slots` is what those layers would ask for if they
    ran at the same time, each applying its share. Whether they overlap is the runner's fact
    (`layer_overlap_ratio`), and what they consumed is `per_layer_cpu`.

    ABSENT, NOT EMPTY: `None` when no executed row carries a share, when `allotment` or `cores` is
    not a positive int (an unknown bound is not a bound — the reading is not fabricated), or when
    the product does not EXCEED `cores` (equality is within the bound; a relative 1e-9 guard keeps
    binary-fraction noise at exact equality from reading as an excess). So a land that declares no
    shares, and one within the bound, carry a byte-unchanged `verify_metrics`.

    Pure + total: no I/O, nothing raised. REPORT-ONLY: nothing consumes this to change an exit
    code, a verdict or an admission decision."""
    for value in (allotment, cores):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
    shares = []
    for row in rows or []:
        if not isinstance(row, dict) or isinstance(row.get("duration_ms"), bool) \
                or not isinstance(row.get("duration_ms"), int):
            continue
        share = row.get("declared_worker_share")
        if isinstance(share, (int, float)) and not isinstance(share, bool) and 0 < share <= 1:
            shares.append(float(share))
    if not shares:
        return None
    share_sum = math.fsum(shares)
    slots = share_sum * allotment
    if not slots > cores * (1 + 1e-9):
        return None
    return {"share_sum": share_sum, "allotment": allotment, "cores": cores,
            "worker_slots": slots, "layers": len(shares)}


def _layer_share_load_line(record) -> "str | None":
    """T-13876 — the operator-facing half of `_layer_share_load_record`. `None` (nothing printed)
    whenever no record exists, so a land without the reading has a byte-unchanged stdout. Four
    significant digits; the exact numbers are on the land row, which this line never replaces."""
    if not isinstance(record, dict):
        return None
    try:
        s, a, c, w, n = (float(record["share_sum"]), int(record["allotment"]), int(record["cores"]),
                         float(record["worker_slots"]), int(record["layers"]))
    except (KeyError, TypeError, ValueError):
        return None
    return (f"land: WARN the declared layer_worker_shares of the {n} layer(s) this verify ran sum to "
            f"{s:.4g}; at the worker allotment in force ({a}) that is up to {w:.4g} worker slots if "
            f"they run at the same time, and this host has {c} cores. Report-only: the sum stays the "
            f"project's to choose and nothing is refused (SPEC-0152 rule 16).")


def _fold_layer_share_load(verify_metrics, rows, allotment, cores, *, emit=print) -> "dict | None":
    """T-13876 — the WHOLE effect of the declared-share load reading on a land, in one place: when
    `_layer_share_load_record` yields a reading it is stored as `verify_metrics["layer_share_load"]`
    and its line is passed once to `emit`; otherwise nothing happens. Returns the record or None.

    The land calls this with ONE statement and reads nothing back, so «the reading changes nothing
    else» is a property of this function alone: it writes that one key, never touches another key
    of `verify_metrics` or any row, and has no other effect. A `verify_metrics` that is not a mapping
    is left alone (None)."""
    if not isinstance(verify_metrics, dict):
        return None
    record = _layer_share_load_record(rows, allotment, cores)
    if record is None:
        return None
    verify_metrics["layer_share_load"] = record
    emit(_layer_share_load_line(record))
    return record


_SHELL_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_SHELL_CHDIR_WORD_RE = re.compile(r"(?<![\w./-])(?:cd|pushd|popd)(?![\w./-])")


def _plain_command_words(command: str) -> "list | None":
    """T-13541 — the words of a layer `command:` that is ONE PLAIN simple command, else None.

    Returns `(word, plain_len)` pairs, where `plain_len` is how many leading characters of the word
    were written unquoted — what tells a real `NAME=value` assignment from a quoted word that merely
    looks like one. Single quotes, double quotes and backslash escapes are honoured.

    None — «not one plain command» — on ANYTHING the shell would treat as more than words: an unquoted
    `;` `|` `&` `(` `)` `<` `>` `#` or newline (a list, a pipeline, a redirection, a subshell, a
    comment), a `$` or a backtick outside single quotes (an expansion or substitution), an unbalanced
    quote, a trailing backslash. That is deliberately the WHOLE grammar: three audit passes on this
    card each found one more way a wider reading credited an `npm` the shell does not run
    (`echo npm run e2e`, `echo ok > npm run e2e`, bash's `echo ok &> out npm run e2e`), and shells
    disagree on some of them. A command with no operator at all has one reading in every shell.
    Pure: no I/O, no expansion, nothing executed."""
    words, word, plain, frozen, quote = [], None, 0, False, None
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if quote == "'":
            if ch == "'":
                quote = None
            else:
                word += ch
        elif ch in "$`":
            return None
        elif quote == '"':
            if ch == '"':
                quote = None
            elif ch == "\\" and i + 1 < n and command[i + 1] in '"\\\n':
                i += 1
                if command[i] != "\n":
                    word += command[i]
            else:
                word += ch
        elif ch == "\\":
            if i + 1 >= n:
                return None
            i += 1
            frozen = True
            if command[i] != "\n":
                word = (word or "") + command[i]
        elif ch in "'\"":
            quote, frozen = ch, True
            word = word or ""
        elif ch in ";|&()<>#\n":
            return None
        elif ch in " \t":
            if word is not None:
                words.append((word, plain))
                word, plain, frozen = None, 0, False
        else:
            word = (word or "") + ch
            if not frozen:
                plain += 1
        i += 1
    if quote is not None:
        return None
    if word is not None:
        words.append((word, plain))
    return words


def _npm_run_script(command: str) -> "tuple | None":
    """T-13541 — the package script a layer `command:` PROVABLY runs, as `(dir | None, name)` (`None`
    = the worktree root, where a layer command runs — `_run_layer_command`), else None.

    A CLOSED allow-list, never a skip-what-I-do-not-know scan, because its caller turns a hit into
    «this layer has a reader»: an unread script is only the miss that already existed, a wrongly read
    one would absolve a share nobody reads. The layer command must be, in full:

        [NAME=value ...] npm [-w <dir> | --workspace <dir> | --workspace=<dir>] run|run-script <name> [args] [-- args]

      - ONE plain simple command (`_plain_command_words`): no list, pipeline, redirection, subshell,
        substitution, expansion or comment. `npm ci && npm run e2e` is NOT followed.
      - `npm` is its command word, after real leading `NAME=value` assignments; an `npm_config_*`
        name anywhere in the command refuses it (it can point npm at another directory).
      - before a bare `--`: at most ONE workspace selector, and ANY other `-flag` (`--prefix`, `-C`,
        `--workspaces`, …) refuses — an unknown flag is never skipped. The first plain word is `run` |
        `run-script`, the next is the script name; later plain words and everything after `--` are
        the script's own arguments.
      - a name or dir carrying a glob / brace / tilde character is not a literal and is refused.

    BOUND, stated: `-w <dir>` is read as a DIRECTORY; whether it is a declared workspace is npm's own
    check, and npm refuses loudly when it is not. Pure + total."""
    try:
        # surrounding blank space is not an operator (a YAML block scalar ends in a newline)
        words = None if "npm_config_" in command.lower() else _plain_command_words(command.strip())
    except Exception:
        return None
    if not words:
        return None
    k = 0
    while k < len(words):
        m = _SHELL_ASSIGNMENT_RE.match(words[k][0])
        if not m or m.end() > words[k][1]:
            break
        k += 1
    rest = [w for w, _plain in words[k:]]
    if not rest or rest[0] != "npm":
        return None
    dirs, plain = [], []
    args = iter(rest[1:])
    for tok in args:
        if tok == "--":
            break
        if tok in ("-w", "--workspace"):
            val = next(args, None)
            if val is None or val.startswith("-"):
                return None
            dirs.append(val)
        elif tok.startswith("--workspace="):
            dirs.append(tok[len("--workspace="):])
        elif tok.startswith("-"):
            return None
        else:
            plain.append(tok)
    if len(dirs) > 1 or len(plain) < 2 or plain[0] not in ("run", "run-script"):
        return None
    rel_dir, name = (dirs[0] if dirs else None), plain[1]
    if rel_dir == "" or any(c in part for part in (name, rel_dir or "") for c in "*?[]{}~"):
        return None
    return (rel_dir, name)


def _registry_text(worktree: Path, command: str, *, _DELEG_REGISTRY_MAX_DEPTH, _DELEG_REGISTRY_MAX_BYTES=_DELEG_REGISTRY_MAX_BYTES, _DELEG_REGISTRY_MAX_FILES=_DELEG_REGISTRY_MAX_FILES) -> str:
    """T-11172 — ONE layer's REGISTRY TEXT: its `command:` PLUS the in-worktree script(s) it names,
    TRANSITIVELY to `_DELEG_REGISTRY_MAX_DEPTH` levels. Extracted verbatim from
    `_delegated_tests_execution_gap` so the union read (below) can run it PER LAYER, each with its own
    file cap and its own `seen` set — a shared cap would let one big layer starve the next, and a
    starved read removes text, which ACCUSES more (the wrong direction for a report-only signal).

    The X-0860 layer was `bash scripts/run-tests.sh`: the file names live in that script, not in the
    command string, so reading one level deep is what makes the check see the real registry at all. One
    level is not ENOUGH once a layer splits into a DRIVER plus per-surface scripts (X-0883 / X-0886) —
    then the suites are named two levels down and a depth-1 read accuses every one of them. So the walk
    goes level by level, bounded FOUR ways: the depth cap, the file cap (it counts across levels, not
    per level), an empty frontier, and a `seen` set of resolved paths so a cycle reads each file once
    and stops. Pure + total: every read is bounded and every exception swallowed.

    T-13541 (GitHub issue 28) — a PACKAGE SCRIPT is an in-repo script too. For
    `npm run e2e:browser` no command token is a file, so the walk read nothing and a share the runner
    does read was reported as read by nobody. When the layer command IS one plain `npm run <name>`
    invocation (`_npm_run_script` — the whole command, a closed flag grammar), that script's text from
    `<dir>/package.json` `scripts[name]` joins LEVEL 0: it is added to the text. The manifest read
    sits inside the SAME bounds as any other — no absolute or `..` dir, realpath containment, the byte
    cap, one read against the file cap, the `seen` set — and every failure (unreadable, oversized,
    escaping, bad JSON, no such script) adds nothing, which is exactly the pre-change text.

    The FILES that script names are followed (it joins the first frontier) ONLY where the walk's own
    resolution base is the directory the script runs in: a ROOT package script whose text names no
    `cd` / `pushd` / `popd` anywhere (quoted or not). The walk resolves every token against the
    worktree root, so following a WORKSPACE script's `-c e2e/pw.config.ts` would read the ROOT's
    unrelated `e2e/pw.config.ts` and credit it as this layer's reader; such a script contributes its
    own text and nothing more."""
    text = command
    reads = 0
    seen = set()
    frontier = [command]                # level 0: the command string itself
    npm_run = _npm_run_script(command)
    if npm_run is not None:
        rel_dir, name = npm_run
        try:
            # the walk's own rule: absolute paths and any escaping path are never read
            if rel_dir is None or not (rel_dir.startswith("/") or ".." in rel_dir):
                root = worktree.resolve()
                cand = (((worktree / rel_dir) if rel_dir is not None else worktree) / "package.json").resolve()
                # containment by realpath (a symlinked dir leaving the tree is refused) + the byte cap
                if (root in cand.parents and reads < _DELEG_REGISTRY_MAX_FILES and cand.is_file()
                        and cand.stat().st_size <= _DELEG_REGISTRY_MAX_BYTES):
                    body = cand.read_text(encoding="utf-8", errors="replace")
                    seen.add(cand)
                    reads += 1
                    data = json.loads(body)
                    scripts = data.get("scripts") if isinstance(data, dict) else None
                    script = scripts.get(name) if isinstance(scripts, dict) else None
                    if isinstance(script, str) and script:
                        text += "\n" + script
                        if rel_dir is None and not _SHELL_CHDIR_WORD_RE.search(script):
                            frontier.append(script)     # runs in the root: the files it names are read below
        except Exception:
            pass    # unreadable manifest / bad JSON -> contributes nothing; never an accusation
    for _depth in range(_DELEG_REGISTRY_MAX_DEPTH):
        nxt = []
        for chunk in frontier:
            if reads >= _DELEG_REGISTRY_MAX_FILES:
                break
            for tok in re.split(r"[\s;|&()<>'\"]+", chunk):
                if reads >= _DELEG_REGISTRY_MAX_FILES:
                    break
                tok = tok.strip()
                if not tok or tok.startswith("-") or tok.startswith("/") or ".." in tok:
                    continue    # flags, absolute paths, and any escaping path: never read
                try:
                    cand = (worktree / tok).resolve()
                    root = worktree.resolve()
                    if cand == root or root not in cand.parents:
                        continue  # containment: only files INSIDE this worktree (realpath, not a prefix test)
                    if cand in seen:
                        continue  # already read (also what makes a script cycle terminate)
                    if not cand.is_file() or cand.stat().st_size > _DELEG_REGISTRY_MAX_BYTES:
                        continue
                    body = cand.read_text(encoding="utf-8", errors="replace")
                    seen.add(cand)
                    text += "\n" + body
                    reads += 1
                    nxt.append(body)    # this body's own script references are the next level
                except Exception:
                    continue    # unreadable token → simply contributes nothing; never a false accusation
        if not nxt or reads >= _DELEG_REGISTRY_MAX_FILES:
            break
        frontier = nxt
    return text


def _registry_names_file(text: str, fname: str) -> bool:
    """True iff an execution-registry TEXT names this test file (T-11886 — extracted verbatim from
    `_delegated_tests_execution_gap`'s former `_names` closure; no behaviour change).

    Matched on the STEM at a token boundary, so `test_a` does not match inside `test_ab.py` — a
    substring test would silently absolve a file the layer never names, which is the exact miss the
    X-0860 checks exist to catch.

    WHY IT IS MODULE-LEVEL NOW. The same question is asked on TWO declaration axes: the `covers:`
    delegation gap below, and the `subject_globs:` fold `bin/lib/debt.py#unexecuted_subject_files`
    (SPEC-0119 rule 35). Two copies of «named» would drift into disagreeing about what counts as
    execution evidence, so there is ONE predicate (CHARTER §P1 F1 — extend, never parallel). It stays
    REGISTRY-based in both directions: a textual mention is not proof of execution either (a comment
    or a dead branch can name a file that never runs), so neither caller may render its complement as
    verified. Pure: no I/O, no clock, no state."""
    stem = fname[:-3] if fname.endswith(".py") else fname
    return re.search(r"(?<![\w.-])" + re.escape(stem) + r"(?![\w-])", text) is not None


def _delegated_tests_execution_gap(worktree: Path, layer: str, *, _read_yaml, CONSUMER_OPS_CONTRACT, _declared_test_sweep_probe_files, _registry_names_file, _registry_text) -> dict:
    """SPEC-0152 rule 16 §delegation-is-a-declaration (T-11073 / X-0860) — the DELEGATED surface's
    execution-registry gap. Returns
    `{"kind": "explicit"|"discovery"|"unknown", "covered": [names], "missing": [names]}`.

    WHY. `_consumer_tests_delegation` hands the whole root `tests/` surface to a declared layer on the
    strength of its `covers:` glob — and `covers:` is the consumer's ASSERTION, never a proof. In X-0860
    (<project>) the layer was a hand-written script registering each suite EXPLICITLY and one test file
    had ZERO references in it: `task test --run` printed an unqualified PASS while that file was
    executed by NOTHING, and four mutation-verified tripwires shipped through `land` believing they
    were gated. This helper is what lets the output name that file instead of laundering the claim.

    THE UNION, NOT THE ONE LAYER (T-11172 / X-0894). `_consumer_tests_delegation` names THE single
    layer whose `covers:` glob claims tests/, but real coverage in a consumer is per-UNION: a covered
    file is routinely executed by a DIFFERENT declared layer. So a covered file counts as named when
    ANY executable declared layer's registry names it — <project> moved `covers: [tests/**]` onto their
    `stack` layer and this check then accused 8 of 39 covered files that `scripts/verify-static.sh` (a
    SIBLING layer — the host-side tripwires the in-container pytest cannot run) executes by name.
    THIS IS A FALSE-ALARM FIX, NOT A HOLE BEING PATCHED — the error direction was OVER-reporting, and
    it stays that way: the per-file `missing` list survives unchanged, so a file named in NO layer's
    registry is STILL reported. A waived layer is excluded from the union (it does not run, so naming a
    file there absolves nothing), and the delegated layer must still carry a command of its own.

    WHAT IS ACTUALLY PROVABLE. There is no generic execution ledger — a layer is an arbitrary command,
    and instrumenting it is out of reach. So this asks the NARROW PROVABLE question, «does the layer's
    execution registry NAME this file?», never the unprovable «was it executed». A textual mention is
    not proof of execution either (a comment or a dead branch can name a file that never runs), so the
    complement is never rendered as verified — the caller's wording stays registry-based in BOTH
    directions (audit-pre finding, absorbed mode-b).

    THE SHAPE SPLIT — and why it fails toward NOT ACCUSING. This is a report-only SIGNAL describing
    what a layer did, not a gate guarding an action, so its fail-safe direction is INVERTED relative to
    the delegation predicate: unanswerable ⇒ the reading that does not accuse (the local craft note
    `lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate.md`; one false accusation
    gets the whole signal skimmed, while a missed detection only leaves the silence that already
    existed). Hence:
      * `explicit`  — the union registry names ≥1 covered file, so the declared layers demonstrably
        enumerate their suites; a covered file NONE of them names is a real, reportable gap (X-0860).
      * `discovery` — the union registry names NO covered file (a `pytest tests/`-style runner
        discovers them). It cannot be read file-by-file, so NO per-file claim is made at all: `missing` is [].
      * `unknown`   — any doubt (no tests dir / unreadable carrier / layer not found / empty command).
        Also `missing: []`.
    The `missing` list is therefore EMPTY unless the layer itself proves it enumerates files. What the
    caller prints UNCONDITIONALLY is the trust boundary — that half is never suppressed by a shape.

    Pure + total: every read is bounded and every exception swallowed. It gates nothing (no verdict
    reads it), so a wrong answer here can only cost an advisory line — never a land."""
    out = {"kind": "unknown", "covered": [], "missing": []}
    try:
        # T-11204 (SPEC-0185 §1(a)): the covered set is read from the DECLARED test dirs. Before this,
        # a consumer whose suite is at `backend/tests/` had an empty root `tests/` glob, so this helper
        # returned `kind: unknown` unconditionally and the X-0860 trust-boundary signal was silently
        # dead there. The ABSENCE BRANCH IS UNCHANGED and deliberately so: this is a report-only SIGNAL
        # about a reader, so any doubt still yields `unknown` with `missing: []` — the opposite
        # fail-safe direction to the gates above
        # (`lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate.md`).
        covered = [p.name for p in _declared_test_sweep_probe_files(worktree, _read_yaml=_read_yaml)]
    except Exception:
        return out
    if not covered:
        return out
    out["covered"] = covered

    try:
        ops_path = worktree / CONSUMER_OPS_CONTRACT
        ops = _read_yaml(ops_path) if ops_path.exists() else None
        ver = ops.get("verify") if isinstance(ops, dict) else None
        layers = ver.get("layers") if isinstance(ver, dict) else None
        command = ""
        commands = []
        for ly in (layers if isinstance(layers, list) else []):
            if not isinstance(ly, dict):
                continue
            cmd = str(ly.get("command") or "").strip()
            if (str(ly.get("layer") or "").strip() or "?") == layer:
                command = cmd
            # The UNION side (T-11172): every EXECUTABLE layer contributes its registry — a waived
            # layer does NOT run, so naming a file there must never absolve it.
            if cmd and not isinstance(ly.get("waiver"), dict):
                commands.append(cmd)
    except Exception:   # an unreadable/malformed carrier is the guard's problem, never this advisory's
        return out
    if not command:
        return out

    # The REGISTRY TEXT is read over the UNION of the executable declared layers (T-11172 / X-0894),
    # each via its OWN bounded walk (`_registry_text`), joined with a NEWLINE so no cross-layer
    # adjacency can forge a token-boundary match. No layer-count cap: capping would contradict the
    # claim — a file named only by the layer past the cap would still be accused — and each layer's
    # walk is already bounded, so the total read is bounded without one.
    text = "\n".join(_registry_text(worktree, c) for c in commands)

    named = [c for c in covered if _registry_names_file(text, c)]
    if not named:
        out["kind"] = "discovery"
        return out
    out["kind"] = "explicit"
    out["missing"] = [c for c in covered if c not in named]
    return out


def _group_runqueue_wait_seconds(pgid: int, *, _proc: "Path | None" = None) -> "float | None":
    """T-13811 — the LONGEST time any ONE live task (a thread of a member) of process group `pgid`
    has spent RUNNABLE BUT NOT RUNNING, in seconds: the largest second field of the kernel's per-task
    `/proc/<pid>/task/<tid>/schedstat` over the group. None when nothing could be read (no such
    group, no schedstat on this kernel), so a caller never mistakes "unmeasured" for "did not wait".

    It is the evidence that a lowered-priority group is being DENIED the CPU, as opposed to not asking
    for it: a command that waits on a container or a remote service sleeps and accumulates none, while
    a CPU-bound task outranked by foreign load accumulates nearly its whole wall. The LONGEST task, never
    the sum: many tasks that each waited briefly and then sleep add up to a long total while no task was
    held off the CPU for the attempt, and a sum read against one wall would call that starvation. A LOWER
    BOUND — the wait of a task that has already exited is gone with its /proc entry — so it can
    under-read starvation, never over-read it. `comm` may hold spaces and parentheses, hence the split
    after the LAST ')' (the `_process_group_cpu_seconds` parsing). `_proc` is the /proc root (a test
    hands in a fabricated tree)."""
    try:
        longest = None
        for entry in (_proc or Path("/proc")).iterdir():
            if not entry.name.isdigit():
                continue
            try:
                raw = (entry / "stat").read_text(encoding="utf-8", errors="replace")
                fields = raw[raw.rfind(")") + 2:].split()
                if int(fields[2]) != pgid:
                    continue
                tasks = list((entry / "task").iterdir())
            except (OSError, ValueError, IndexError):
                continue          # the process exited between the listing and the read
            for task in tasks:
                try:
                    waited = int((task / "schedstat").read_text(encoding="utf-8").split()[1])
                except (OSError, ValueError, IndexError):
                    continue
                longest = waited if longest is None else max(longest, waited)
        return None if longest is None else longest / 1e9
    except Exception:
        return None


_layer_tree = threading.local()   # T-13931: `.reading` = the open `_LayerProcessTree` of the layer this
                                  # THREAD is running, set and cleared by that layer's CPU sampler

# T-13993 (public issue #122) — at a layer's bound its process group gets SIGTERM and this long to
# exit before the SIGKILL, so a unit can clean up (its temp box, its own report) on the way out. A
# constant, not a setting (owner decision 2026-10-17); it never raises the bound or rescues the outcome.
_LAYER_TERM_GRACE_S = 5.0
_layer_kill = threading.local()   # T-13993: `.ending` = how the last bound-killed command of this THREAD
                                  # ended: None (no grace given), "exited-in-grace" or "killed-hard"
_layer_name = threading.local()   # T-14157: `.name` = the declared layer this THREAD runs (set by the
                                  # guard before each layer), the label a stopped run is recorded under

# T-14157 — a STOP of the verb running the verify layers (SIGTERM / SIGINT to `task test --run`). Each
# layer runs in a session of its own, so the signal that stops the verb never reaches it. The verb's
# run has ONE stop slot (`seq`), taken in one indivisible step either by the first signal — the handler
# (`request_layer_stop`) then RECORDS it here and, unless the main thread is inside a runner, raises
# `LayerRunStopped` on the main thread, as CPython raises KeyboardInterrupt — or by the run's own wall
# close (`close_layer_stop`), after which no signal stops the run; every later taker only notes its
# signal (`late`) — the wall close re-delivers one noted after it once the dispositions are back. A runner
# ends the group it started on every exit except the layer's own completion (its command exited and its
# output drained), and a stop met before completion ends it (`_end_layer_group`) before the runner gives
# up its token. No runner, handler or deadline ever ends the verb or writes its record.
# `_layer_runs` holds one token per runner that may own a live group: a runner reads the recorded
# signal and registers in ONE step under `_layer_runs_lock`, so the verb's single writer, waiting in
# `wait_layer_runs` after the unwind, sees either the token or a runner that started nothing.
_layer_stop = {"signo": None, "main_in_runner": False, "stopped": [], "late": [], "seq": itertools.count()}
_layer_runs: set = set()
_layer_runs_lock = threading.Lock()


class LayerRunStopped(BaseException):
    """T-14157 — the verify run was stopped by signal `signo` to the verb. A BaseException, like
    KeyboardInterrupt, so no `except Exception` between a runner and the verb can swallow it."""

    def __init__(self, signo):
        super().__init__(signo)
        self.signo = signo


def reset_layer_stop() -> None:
    """T-14157 — forget a recorded stop (a new run starts, or the last one is over)."""
    _layer_stop.update(signo=None, stopped=[], late=[], seq=itertools.count())


def request_layer_stop(signo) -> None:
    """T-14157 — called by the verb's signal handler. The FIRST call of a run records the stop, then
    raises it on the main thread unless that thread is inside a runner — there an exception could land
    between a fork and the assignment of its pid, so the runner raises it itself at its next tick. Every
    later call — a second signal, one nested in this handler, one during the record — only notes its
    signal and returns (`next()` on the counter is one indivisible step); the note is read only when
    the wall close took the slot (`late_layer_signal`). Takes no lock."""
    if next(_layer_stop["seq"]):
        _layer_stop["late"].append(signo)
        return
    _layer_stop["signo"] = signo
    if not _layer_stop["main_in_runner"] and threading.current_thread() is threading.main_thread():
        raise LayerRunStopped(signo)


def close_layer_stop():
    """T-14157 — the run is over: take its one stop slot. Returns the recorded signal when a signal took
    the slot first (the run was stopped), else None — and every later signal is then a no-op."""
    if next(_layer_stop["seq"]):
        return _layer_stop["signo"]
    return None


def late_layer_signal():
    """T-14157 — the first signal that met an already-taken stop slot, or None. Read after the wall
    close gave the dispositions back: such a signal came after the run was over, so it is the verb's."""
    late = _layer_stop["late"]
    return late[0] if late else None


def stopped_layer_labels() -> list:
    """T-14157 — the layers a recorded stop ended, in the order their groups were gone."""
    return list(_layer_stop["stopped"])


def wait_layer_runs() -> None:
    """T-14157 — return once no runner may own a live group, i.e. every runner has returned, each after
    its group had no live member left (`_end_layer_group`). No deadline."""
    while True:
        with _layer_runs_lock:
            if not _layer_runs:
                return
        time.sleep(0.02)


def _group_size(pgid) -> int:
    """T-14085 — how many live processes are in process group `pgid`, read from `/proc/<pid>/stat`
    (field 5, after the parenthesised name). 0 where `/proc` cannot be read."""
    n = 0
    try:
        pids = [d for d in os.listdir("/proc") if d.isdigit()]
    except OSError:
        return 0
    for d in pids:
        try:
            with open(f"/proc/{d}/stat", "rb") as f:
                fields = f.read().rsplit(b")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if len(fields) > 2 and fields[0] != b"Z" and fields[2] == str(pgid).encode():
            n += 1
    return n


def _wait_layer_group_gone(pgid) -> None:
    """T-14157 — return once process group `pgid` has no live member (`_group_size`; zombies excluded).
    Called only after the group was sent SIGKILL, so nothing in it can run again; a member in
    uninterruptible sleep is waited for. No deadline."""
    while _group_size(pgid):
        time.sleep(0.05)


def _end_layer_group(pgid) -> bool:
    """T-14157 — end process group `pgid` on the terms of a layer's bound — SIGTERM, up to
    `_LAYER_TERM_GRACE_S` for it to exit, then SIGKILL — and return only once no live member is left
    (`_group_size`; zombies excluded). No deadline: after the SIGKILL nothing in the group can run again,
    and a member in uninterruptible sleep is waited for. The group is signalled only while it has a live
    member, and a group with a live member keeps its id, so the signal never reaches another group.
    True when the group had a live member."""
    import signal
    if not _group_size(pgid):
        return False
    for sig, grace in ((signal.SIGTERM, _LAYER_TERM_GRACE_S), (signal.SIGKILL, None)):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        if grace is None:
            _wait_layer_group_gone(pgid)
            break
        until = time.monotonic() + grace
        while _group_size(pgid) and time.monotonic() < until:
            time.sleep(0.05)
        if not _group_size(pgid):
            break
    return True


def _layer_term_grace():
    """T-13993 — `(sentence, row_fields)` for the timeout this thread's last `_run_layer_command` hit:
    the sentence the TIMED OUT assertion appends and the `term_grace` key of the timed-out layer row.
    `("", {})` when that call gave no grace (it did not time out, or the bound passed before it ran)."""
    ended = getattr(_layer_kill, "ending", None)
    if ended is None:
        return "", {}
    how = ("it exited inside the grace" if ended == "exited-in-grace"
           else "it was still running when the grace ended and was killed hard (SIGKILL)")
    return (f" At the bound the layer's process group was sent SIGTERM and given a "
            f"{_LAYER_TERM_GRACE_S:g}s grace (T-13993): {how}.",
            {"term_grace": {"grace_s": _LAYER_TERM_GRACE_S, "ended": ended}})


class _LayerProcessTree:
    """T-13931 — the CPU a verify layer's commands burned in processes their reaped rusage never
    receives, read from /proc while the commands run. REPORT-ONLY: nothing that decides reads it.

    WHAT THE REAPED READING MISSES. `os.wait4` hands back the command's own CPU plus that of every
    descendant that was WAITED FOR, link by link, up to the command. A process whose parent exits
    without waiting for it drops out of that sum with everything it had itself reaped — a browser's
    renderer and GPU processes when the browser is killed, a helper left in the background.

    HOW THE TREE IS FOUND. A member is: a command (`start(pid)` names it, by pid AND start time,
    and only when /proc shows it as this process's own child leading its own session); a process
    whose parent is a member; a process in the session of a command that has not been reaped yet
    (the runner starts each command as the leader of a new session, and while it is unreaped —
    running or ended — its pid cannot be given to anything else, so that session holds its
    descendants only). A member stays one after it is re-parented, and is always known by pid AND
    start time, so a process that later gets a member's pid is not taken for it; and a child is
    taken on its parent's word only when that parent, read again after the listing, is still the
    same process. The parent rule finds a browser that a test driver started in a session of its
    own; the session rule finds a helper that was re-parented before any sample saw its parent.

    TWO RULES KEEP ANY CPU FROM BEING COUNTED TWICE.
    (1) Every reading of the members is CONSISTENT (`_settled`): /proc is read one process at a time,
        so a child may be read before its parent waited for it and the parent after — the child's CPU
        would then stand in both. The members are therefore read twice in a row, and a reading is
        used only when both passes hold the same processes with the same reaped-children times: no
        member was waited for while it was taken. Otherwise it is taken again, a few times, and a
        step with no consistent reading counts nothing. A member counts as gone only when /proc
        says there is no such process: one that exists and cannot be read (a permission, a file
        limit), or a command not yet reaped that reads as gone, leaves the step without a reading.
    (2) A command is read for the LAST time by `ended(pid)`, which the runner calls when the command
        has ended and is not yet reaped. Its figures are final then, and so are its session and its
        pid; after that the command is dropped and never looked up again.
    With those, per step: V = what the members that vanished since the previous reading held (own
    CPU plus reaped-children CPU), A = the growth of the reaped-children time of every member still
    there. What a vanished member held either moved into such a member or left the tree, so the tree
    lost at least V - A, less two clock ticks per vanished member (each /proc field is rounded down
    to a tick). A child that was waited for is in A and adds nothing. A command's own CPU, and what
    it reaped, is the runner's rusage and is never added here. What a member still alive at
    `close()` holds is in no rusage and is added as it stands.

    A LOWER BOUND, never above the truth: CPU burned after a member's last reading, and a process
    that lived and died between two samples, are not seen. `period` is the seconds between samples
    (the caller's, so a layer has one cadence); `_proc` is the /proc root."""

    def __init__(self, period, *, _proc: "Path | None" = None):
        self._period, self._proc = period, (_proc or Path("/proc"))
        self._held: dict = {}       # (pid, start) -> (own ticks, reaped-children ticks): one consistent reading
        self._roots: dict = {}      # pid of a command started and not yet reaped -> its (pid, start)
        self._lost = 0
        self._due = time.monotonic() + period
        self._started = False       # a command was started under this reading
        self._answered = False      # a consistent reading was taken

    def _read(self, pid) -> "tuple | None":
        """(start, ppid, session, own, reaped) of one process; None when there is NO such process.
        Raises when the process exists and its `stat` cannot be read or parsed. `comm` may hold
        spaces and parentheses, hence the split after the LAST ')'."""
        try:
            raw = (self._proc / str(pid) / "stat").read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, ProcessLookupError):
            return None
        f = raw[raw.rfind(")") + 2:].split()
        return (int(f[19]), int(f[1]), int(f[3]), int(f[11]) + int(f[12]), int(f[13]) + int(f[14]))

    def _look(self, pid) -> "tuple | None":
        """`_read` for a process that need not be this layer's: unreadable reads as not there."""
        try:
            return self._read(pid)
        except Exception:
            return None

    def _members(self) -> "set | None":
        """The (pid, start) of every member alive now (the rule: the class docstring), from one
        listing of /proc; None when /proc cannot be listed."""
        try:
            pids = [int(n) for n in os.listdir(self._proc) if n.isdigit()]
        except OSError:
            return None
        rows = {pid: row for pid in pids for row in (self._look(pid),) if row is not None}
        kids: dict = {}
        for pid, row in rows.items():
            kids.setdefault(row[1], []).append(pid)
        todo = [pid for pid, row in rows.items()
                if (pid, row[0]) in self._held or self._roots.get(pid) == (pid, row[0])
                or row[2] in self._roots]
        seen: set = set()
        while todo:
            pid = todo.pop()
            if (pid, rows[pid][0]) in seen:
                continue
            seen.add((pid, rows[pid][0]))
            # The rows were read one after another. A child is this member's only if the member
            # held its pid for the whole listing: read again now, it is still the same process.
            again = self._look(pid)
            if again is not None and again[0] == rows[pid][0]:
                todo.extend(kids.get(pid, ()))
        return seen

    def _settled(self, keys) -> "dict | None":
        """{(pid, start): (own, reaped)} of those of `keys` that still exist, taken CONSISTENTLY
        (rule (1) of the class docstring), or None when five passes never agreed or a command not
        yet reaped read as gone. Raises when a process of `keys` exists and cannot be read."""
        def once():
            got = {}
            for pid, start in keys:
                row = self._read(pid)
                if row is not None and row[0] == start:
                    got[(pid, start)] = (row[3], row[4])
            return got
        before = once()
        for _ in range(4):
            after = once()
            if after.keys() == before.keys() and all(after[k][1] == before[k][1] for k in after):
                return after if all(k in after for k in self._roots.values()) else None
            before = after
        return None

    def _step(self) -> bool:
        """One sample; False when no consistent reading could be taken (nothing is counted then)."""
        self._due = time.monotonic() + self._period
        try:
            keys = self._members()
            now = None if keys is None else self._settled(keys | set(self._held) | set(self._roots.values()))
        except (OSError, ValueError, IndexError):
            now = None      # a member exists and could not be read: it is not read as gone
        if now is None:
            return False
        gone = [k for k in self._held if k not in now]
        if gone:
            absorbed = sum(max(0, c - self._held[k][1]) if k in self._held else c
                           for k, (_own, c) in now.items())
            lost = sum(sum(self._held[k]) for k in gone) - absorbed - 2 * len(gone)
            if lost > 0:
                self._lost += lost
        self._held = now
        self._answered = True
        return True

    def start(self, pid: int) -> bool:
        """The runner started command `pid` and has not reaped it. False when the command cannot be
        read here (no /proc or another one, no `os.waitid`): the runner then waits for it as it
        always did and this reading learns nothing of it. Never raises."""
        try:
            row = self._read(pid) if hasattr(os, "waitid") else None
            # What /proc shows under this pid must be the command itself: this process's own child,
            # leading its own session. Under another /proc (another pid namespace) it would not be.
            if row is None or row[1] != os.getpid() or row[2] != pid:
                return False
            self._roots[pid] = (pid, row[0])
            self._started = True
            return True
        except Exception:
            return False

    def sample(self) -> None:
        """Called by the runner while a command runs: one sample when one is due. Never raises."""
        try:
            if (self._roots or self._held) and time.monotonic() >= self._due:
                self._step()
        except Exception:
            pass

    def ended(self, pid: int) -> None:
        """Command `pid` has ended and the runner is about to reap it: its last reading (rule (2) of
        the class docstring). Without a consistent reading here, what the command took in from the
        members it waited for is unknown, so everything held is forgotten rather than read, at the
        next sample, as CPU that left the tree. Never raises."""
        key = self._roots.get(pid)
        try:
            if key is not None and not self._step():
                self._held = {}
        except Exception:
            self._held = {}
        finally:
            self._roots.pop(pid, None)
            self._held.pop(key, None)

    def close(self) -> "int | None":
        """The CPU in milliseconds found outside every reaped rusage; None when no command was
        started under this reading or no consistent reading was ever taken (no /proc)."""
        try:
            last = self._started and self._step()
            if not (self._started and self._answered):
                return None
            # The members still alive are added only from a reading taken now, with every command
            # reaped: an older one may hold a process that a command has since waited for.
            alive = sum(own + kids for own, kids in self._held.values()) if (last and not self._roots) else 0
            return (self._lost + alive) * 1000 // os.sysconf("SC_CLK_TCK")
        except Exception:
            return None


def _run_layer_command(cmd, worktree, timeout, env, nice: int = 0, starved=None, shell: bool = True):
    """T-12589 — run ONE verify layer command on the terms `subprocess.run(cmd, shell=True, cwd,
    capture_output=True, text=True, timeout, env)` had, but reap it with `os.wait4` so the reading is
    the command's OWN rusage (the shell plus every descendant it waited for) — not the process-wide
    RUSAGE_CHILDREN, which also carries the CPU sampler's docker calls and any sibling child (audit-post
    fp1:c9c00b16712f099c). Returns `(CompletedProcess, process_cpu_ms)`, or `(None, process_cpu_ms)`
    when the bound expired and the command was killed.

    T-13806 (public issue #74) — `nice` > 0 starts the command AT that scheduler nice (the caller's
    `_verify_child_nice` decision: a dispatched worker's Stage-6 layer, never a land's): a TARGET, not
    an increment, so a parent already at 5 does not push a setting of 7 to 12. A parent already above
    the target keeps its own (an unprivileged process can only lower its priority). Every descendant
    inherits it. 0 (every land, every caller predating this) spawns byte-identically.

    T-13811 (SPEC-0071 rule 1) — `starved`, given with a `nice` > 0 and a bound, is the kernel
    runner's own decision (`verify_runner._priority_starved`, bound to its readers by the caller),
    asked as `starved(pgid, wall_s) -> (bool, cpu_s)` every fifth of the bound. A true answer kills
    the command's process group, prints one stderr line, and runs the command ONCE more at normal
    priority in the time LEFT of the same bound — that run is never probed, and its result is the
    invocation's (a hang is still killed at the first attempt's deadline and still returns None).
    The deadline is read again after the first attempt is reaped and its streams are collected: once
    it has passed, no second run starts and the invocation returns None as a timeout does.
    The CPU reading is the sum of both attempts; the captured stream is the first attempt's, one
    line saying it was restarted, then the second's. A probe that raises restarts nothing.

    T-14085 (public issue #166) — `shell=False` runs an argv list with no shell (the floor-atom
    caller, `land_floors._floor_project_commands`), on the same group-reaping launch. A bound kill
    leaves `_layer_kill.reaped` = `(pgid, N)`: the processes of the group alive just before the
    SIGTERM; it is None when the bound did not kill the command.

    T-14157 — the run ends normally only once the command has ended AND its output readers are done:
    until then the bound and a recorded stop apply on every tick, whatever the command's own state, so
    a descendant still holding the pipes after the command exited is ended by the bound like a hang.
    The command's end is observed without reaping it (`waitid` WNOWAIT), so its group id stays this
    layer's while the runner may still signal it. A stop recorded by the verb (`request_layer_stop`)
    is checked FIRST at every tick, before completion: the runner ends its group (`_end_layer_group`),
    reaps, and raises `LayerRunStopped`; it starts no restart. A layer that completed on its own is left
    as it is; on every other way out the runner ends its group before giving up its token. A run that
    would begin after the stop starts nothing (`_layer_runs` below)."""
    import signal
    import subprocess
    import threading
    # T-14157: the runner's part in a stop — refuse to start once one is recorded, hold a token while
    # this run may own a live group, and mark the main thread as inside a runner (where the handler
    # does not raise); a stop recorded while the main thread was inside is raised on the way out.
    on_main = threading.current_thread() is threading.main_thread()
    token, group = object(), None
    if on_main:
        _layer_stop["main_in_runner"] = True
    try:
        with _layer_runs_lock:
            if _layer_stop["signo"] is not None:
                raise LayerRunStopped(_layer_stop["signo"])
            _layer_runs.add(token)
        deadline = None if timeout is None else time.monotonic() + timeout
        proc_ms, streams = 0, []
        _layer_kill.ending = None       # T-13993: set below only when the bound kills this command
        _layer_kill.reaped = None       # T-14085: `(pgid, N)` set below only when the bound kills it
        tree = getattr(_layer_tree, "reading", None)    # T-13931: the layer's process-tree reading, if one is open
        label = getattr(_layer_name, "name", None) or str(cmd)   # T-14157: the name a stop is recorded under
        while True:     # at most twice: the attempt, and (T-13811) its ONE restart at normal priority
            if streams and _layer_stop["signo"] is not None:
                # T-14157: a stop never starts the restart — read right before its launch (the first
                # launch's read is the entry check above); the first group was ended before this point
                _layer_stop["stopped"].append(label)
                raise LayerRunStopped(_layer_stop["signo"])
            _nice_kw = {"preexec_fn": (lambda: os.nice(max(0, nice - os.nice(0))))} if nice else {}
            p = subprocess.Popen(cmd, shell=shell, cwd=str(worktree), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, env=env, start_new_session=True, **_nice_kw)
            group = p.pid       # T-14157: the group this runner started (its own session)
            box = {}
            readers = [threading.Thread(target=lambda k=k, s=s, b=box: b.__setitem__(k, s.read()), daemon=True)
                       for k, s in (("out", p.stdout), ("err", p.stderr))]
            for t in readers:
                t.start()
            began = time.monotonic()
            # T-13811: the next priority probe of a lowered attempt (None: not lowered, no decision
            # handed in, or no bound — the wait below is then the one it always was).
            probe_at = (began + timeout / 5) if (nice and starved is not None and timeout) else None
            timed_out = restart = False
            # T-13931: under a tree reading that can read this command, the command is read one last
            # time when it has ended and is NOT YET REAPED (`waitid` with WNOWAIT sees the end and leaves
            # the command in place), and only then reaped. Without one, the wait is the one it always was.
            read = tree if (tree is not None and tree.start(p.pid)) else None

            def reap(block: bool):
                if read is None:
                    return os.wait4(p.pid, 0 if block else os.WNOHANG)
                if os.waitid(os.P_PID, p.pid, os.WEXITED | os.WNOWAIT | (0 if block else os.WNOHANG)) is None:
                    return 0, 0, None
                read.ended(p.pid)
                return os.wait4(p.pid, 0)

            stopping = False
            while True:
                if _layer_stop["signo"] is not None:    # T-14157: the verb was stopped — end the group below
                    stopping = True
                    break
                # T-14157: leave only once the command has ended (observed, not reaped) AND its readers
                # are done — a descendant holding the pipes keeps the bound and the stop check in force.
                exited = os.waitid(os.P_PID, p.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
                if exited and not any(t.is_alive() for t in readers):
                    if _layer_stop["signo"] is not None:
                        # T-14157: read again once completion is observed, before acting on it — a stop
                        # recorded before the layer was seen complete ends it like any running layer
                        stopping = True
                        break
                    pid, status, ru = reap(True)
                    group = None        # T-14157: the layer completed on its own — left as it is
                    break
                now = time.monotonic()
                if (not exited and probe_at is not None and now >= probe_at
                        and now < deadline):
                    probe_at += timeout / 5
                    try:
                        restart, probe_cpu = starved(p.pid, now - began)
                    except Exception:
                        restart = False     # a probe that cannot answer restarts nothing
                if restart or (deadline is not None and now >= deadline):
                    # T-12849: signal the layer's whole process GROUP (its own session, above) — `sh` forks a
                    # simple command, so killing the shell alone leaves the grandchild holding the reader pipes
                    # open and the wall runs past the layer's own timeout.
                    reaped = None
                    if not restart:
                        # T-13993: the BOUND — SIGTERM the group and give it `_LAYER_TERM_GRACE_S` to exit
                        # (the T-12645 reap shape). It has exited when the shell is reaped AND no member
                        # of the group is left. A starvation restart (T-13811) stays an immediate kill.
                        _layer_kill.reaped = (p.pid, _group_size(p.pid))
                        try:
                            os.killpg(p.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        term_end = time.monotonic() + _LAYER_TERM_GRACE_S
                        _layer_kill.ending = "killed-hard"
                        while True:
                            if reaped is None:
                                got = reap(False)
                                reaped = got if got[0] else None
                            if reaped is not None:
                                try:
                                    os.killpg(p.pid, 0)
                                except ProcessLookupError:
                                    _layer_kill.ending = "exited-in-grace"
                                    break
                            if time.monotonic() >= term_end:
                                break
                            time.sleep(0.02)
                    if _layer_kill.ending != "exited-in-grace":
                        try:
                            os.killpg(p.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            if reaped is None:
                                p.kill()
                    _, status, ru = reaped if reaped is not None else reap(True)
                    # T-14157: the group is this runner's until no member of it is alive — a member that
                    # outlives the SIGKILL (uninterruptible sleep) holds the runner, so a stopped run's
                    # record, until it is gone (the restart's first group included)
                    _wait_layer_group_gone(p.pid)
                    timed_out = not restart
                    if timed_out:
                        group = None    # T-14157: the bound has ended the group (T-12849 / T-13993)
                    break
                if read is not None:
                    read.sample()
                time.sleep(0.02)
            if stopping:
                # T-14157: this runner ends the group it started; the command is reaped only after it.
                _end_layer_group(group)
                group = None
                _, status, ru = reap(True)
            p.returncode = os.waitstatus_to_exitcode(status)
            for t in readers:
                t.join(timeout=5 if (timed_out or restart or stopping) else None)   # a surviving grandchild may hold a pipe open
            proc_ms += int(round((ru.ru_utime + ru.ru_stime) * 1000))
            streams.append((box.get("out", "") or "") + (box.get("err", "") or ""))
            if stopping:
                _layer_stop["stopped"].append(label)
                raise LayerRunStopped(_layer_stop["signo"])
            if not restart:
                break
            if time.monotonic() >= deadline:
                # The first attempt's clean-up (a descendant outside the killed group can hold a reader
                # for seconds) used up the time left: the bound has passed, so nothing more is started
                # and the invocation is the timeout it would have been.
                timed_out = True
                break
            note = (f"yitc-v2: verify: layer command {str(cmd)[:120]!r} is starved at nice {nice} "
                    f"(wall={now - began:.1f}s cpu={probe_cpu or 0.0:.1f}s) — restarting it ONCE at normal "
                    f"priority within the same {timeout:g}s budget (T-13811).")
            print(note, file=sys.stderr, flush=True)
            streams.append(note)
            nice = 0            # the restarted run is at normal priority, and so is never probed
        # T-12758 (X-1478 item 8): the WHOLE captured stream, returned as a THIRD element on BOTH arms.
        # The timeout arm used to discard it entirely — `r is None` was the only thing the caller got, so a
        # layer KILLED BY ITS BOUND left no record of what it had printed before the kill. The caller
        # persists this as a land-log artifact on a failing outcome; the `r is None` timeout sentinel and
        # the exit-code gate are untouched.
        captured = "\n".join(streams)
    finally:
        # T-14157: `group` is cleared only where the layer completed or its group was ended; every
        # other way out (an error, a stop met before a restart) ends it here — no stop check, no window.
        if group is not None:
            _end_layer_group(group)
        with _layer_runs_lock:
            _layer_runs.discard(token)
        if on_main:
            _layer_stop["main_in_runner"] = False
    if on_main and _layer_stop["signo"] is not None:
        raise LayerRunStopped(_layer_stop["signo"])
    if timed_out:
        return None, proc_ms, captured
    return (subprocess.CompletedProcess(cmd, p.returncode, box.get("out", ""), box.get("err", "")),
            proc_ms, captured)


def _verify_under_admission(main_wt: Path, branch: "str | None", slots: int, run_verify,
                            *, _append_event, _interval_fn=None, wait_out=None,
                            rebaselining: bool = False, attempt: "int | None" = None,
                            no_tests: bool = False, queued_since=None,
                            merge_invalid_acceptance: bool = False,
                            merge_invalid_assertions: "list | None" = None,
                            withdraw_probe=None, _LandWithdrawn, _flock_holder, _proc_starttime, _verify_admission, _verify_heartbeat_interval, _verify_slot_dir, _wait_heartbeat_line):
    """T-10128 — run `run_verify()` inside the SPEC-0132 verify-admission slot, emitting a THROTTLED
    `waiting_for_verify_admission_slot` journal heartbeat WHILE blocked waiting for a slot. This is the
    seam the land call site actually runs, so a queued land is OBSERVABLE (a journal signal a headless
    worker + `--fleet-verdict` read as landing-queued, not hung — the F2 worker-death class), instead
    of a silent `flock(LOCK_EX)` block. Two DECOUPLED cadences: the slot POLL is short
    (`_ADMISSION_POLL_SEC`, responsive), the heartbeat EMIT is throttled to `_verify_heartbeat_interval()`
    (default 20s). hb<=0 DISABLES the heartbeat (YITC_VERIFY_HEARTBEAT_SECS<=0) → on_wait=None → the
    original single blocking admission, BYTE-IDENTICAL. The event carries a top-level `task_id` (parsed
    from a `task/T-XXXX` branch) so `_dispatch_status_events` scopes it into the `--fleet-verdict`
    classifier; a `work/<slug>` branch has no task id (task_id=None) — still emitted, just fleet-unscoped.

    T-11239: `rebaselining` rides the row as an ADDITIVE `rebaselining: true` and ONLY when true, so a
    non-rebaselining land's heartbeat stays byte-identical. It is what lets ANOTHER land's formation
    read this queued land's intent (`_land_rebaselining_branches`) and decline to batch a member that
    would redden the combined candidate — the same additive-key growth `queue_depth`/`solo` use, no new
    event type (D-0009 / SPEC-0025; the row's rule home stays SPEC-0132 §Observable admission wait).

    T-11681 — OPTIONAL `queued_since`: a CALLABLE (the `_interval_fn` idiom above) returning the
    `time.monotonic()` baseline at which THIS LAND PROCESS first parked at EITHER queue seam, seeding
    it on first call. It is a callable rather than a value BECAUSE THE SEEDING MOMENT MATTERS: passing
    a value would seed the baseline when this function is ENTERED, so a land that sails through an
    uncontended slot and parks at the reservation two attempts later would count its own verify run as
    queue time. Called only from inside `on_wait` — i.e. only on a tick this land is PROVABLY parked —
    so the baseline marks a real park and nothing else. When given, the row carries an ADDITIVE
    `queued_since_s`, on the same absent-unless-known terms as every sibling key here. It exists
    because `waited_s` is per-PARK — `_t0` is re-seeded on every entry to `_acquire_land_reservation`,
    so a land re-parked four times reports itself as new four times (measured: task/T-11525,
    2026-08-26, four restarts under one pid and one attempt). `_land_queue_wait_start` prefers this
    key, which is what makes queue order age-true across a re-park or a dissolution.
    `queued_since=None` (every existing caller and test) → the row is byte-identical.

    T-11692 — the row carries `holder`, the sibling of the key T-11691 put on
    `waiting_for_land_reservation`: WHO occupies the pool, resolved from the `_flock_holder` lookup
    this seam was already making for the T-11076 stderr line and discarding. ALWAYS PRESENT (the
    unknown recorded as `{"resolved": false, ...}`, never an absent key) — unlike every additive key
    above, because absent would read as "nothing held it". It carries `slot`, the slot it was read
    from, since this pool has N slots and only slot-0 is probed: `slot` + `slots` states the 1-of-N
    reading a reader would otherwise have to guess at. RECORDS ONLY — nothing reaps or times out.
    T-12258 (SPEC-0184 rule 16) — OPTIONAL `withdraw_probe`: a zero-argument callable answering "has a
    withdrawal been requested for THIS land attempt?" (the caller passes T-12257's
    `_land_withdraw_requested`, which is ONE `exists()` of this attempt's own path and never raises).
    `withdraw_probe=None` — every existing caller and every existing test — leaves BOTH branches below
    unreachable and this function BYTE-IDENTICAL.

    TWO OBSERVATION POINTS, AND ONLY ONE OF THEM MAY GRANT PROCEEDING. That asymmetry is the rule,
    not an implementation detail:
      (1) THE IN-FLOCK SEAM — inside the `with`, holding the slot, immediately before `run_verify()`.
          This is the LAST instant before the verify is PAID and it is the SOLE AUTHORITY for
          proceeding: whatever the poll tick did or did not see, a land is admitted only by getting
          past this read while holding the flock.
      (2) THE POLL-TICK PROBE — inside `on_wait`, i.e. on a tick this land is PROVABLY still parked
          waiting for a slot. It is ABORT-ONLY: its single reachable outcome is the raise below. It
          exists because a withdrawal is wanted precisely while a land is QUEUED, and honouring it
          only at (1) would make the withdrawal latency equal to the queue latency — the remedy
          arriving exactly when the problem ends (consult round-6 finding C1).

    WHY (2) CANNOT RE-OPEN AUDIT-PRE FINDING G2. G2's defect is check-then-ADMIT across two lock
    states: a read taken outside the flock can be invalidated between the check and the admission it
    grants. This read GRANTS NOTHING — there is no admission for a later event to invalidate. And it
    cannot go stale in the unsafe direction either: a request is addressed to ONE attempt key and, by
    T-12257's construction, the only process that can consume it is that attempt itself, so once this
    land reads True nothing any peer does can make False the right answer.

    IT IS RAISED BEFORE THE THROTTLE, deliberately. The throttle governs how often the wait is
    REPORTED; a decision must not inherit a reporting cadence.

    THE ONE BOUND, STATED RATHER THAN HIDDEN: `on_wait` exists only when the heartbeat is enabled, so
    under `YITC_VERIFY_HEARTBEAT_SECS<=0` the admission takes the original single blocking flock,
    there are no poll ticks, and the withdrawal is honoured at (1) alone. Forcing the polling path
    whenever a probe is passed would silently change what that documented escape hatch does. The
    degradation is in the family's fail-closed direction — the worst outcome is a withdrawal that
    happens LATER, never a wrong one and never an interrupted admitted land."""
    _interval_fn = _interval_fn or _verify_heartbeat_interval
    hb = _interval_fn()
    task_id = branch.split("/", 1)[1] if branch and branch.startswith("task/") else None
    on_wait = None
    if hb and hb > 0:
        _last = [0.0]   # monotonic ts of the last emit; 0.0 => never yet (so the first un-acquired tick emits)
        def on_wait(waited_s):
            # T-12258 (SPEC-0184 rule 16), OBSERVATION POINT (2) — ABORT-ONLY, and FIRST, above the
            # throttle. This tick is proof this land is still PARKED: it holds no slot and has paid
            # no verify, so withdrawing here costs the queue nothing and is the only point at which
            # a withdrawal beats the queue it was issued against. The single reachable outcome is
            # this raise — nothing below it can be reached from a True probe, which is what keeps the
            # in-flock seam the SOLE authority for PROCEEDING and is why this read cannot re-open
            # audit-pre finding G2 (see the docstring). Above the throttle because the throttle
            # governs REPORTING cadence and a decision must not inherit one.
            if withdraw_probe is not None and withdraw_probe():
                raise _LandWithdrawn("waiting_for_verify_admission_slot", waited_s)
            nowm = time.monotonic()
            if _last[0] and (nowm - _last[0]) < hb:
                return   # throttle: at most one heartbeat per hb, independent of the ~1s poll cadence
            _last[0] = nowm
            # T-11489 (AC2): the land's OWN pid rides the queue-wait row as an ADDITIVE key, on the
            # same absent-unless-known terms as every sibling key here. It is an OPTIONAL
            # corroborator for a reader on the same host — `_classify_queued_land_liveness` decides
            # from durable state (heartbeat freshness) WITHOUT it, and must keep doing so.
            _payload = {"branch": branch, "waited_s": int(waited_s), "slots": int(slots),
                        "pid": os.getpid()}
            # T-12256: the pid's DISCRIMINATOR — this attempt's own boot-relative start tick,
            # recorded beside the pid it qualifies. A pid alone is REUSABLE, so a later reader
            # addressing a queued attempt by pid can address a DIFFERENT process that inherited the
            # number after this one exited (consult finding B1, class security-boundary,
            # decisions/T-12243-audit-consult-pre.yaml). Recorded AT QUEUE TIME so no downstream
            # reader ever has to mint the pair from current /proc state, which is the read-to-write
            # window B1 names. Resolved through a per-process memo, so this costs no /proc read per
            # beat. ABSENT UNLESS KNOWN, exactly like every additive sibling on this row: a land
            # that cannot resolve the tick omits the key (never a null) and its row stays
            # BYTE-IDENTICAL to the pre-change row.
            _starttime = _proc_starttime()
            if _starttime:
                _payload["pid_starttime"] = _starttime
            if queued_since is not None:      # T-11681: absent unless the caller owns a baseline
                _payload["queued_since_s"] = int(max(0.0, time.monotonic() - queued_since()))
            if rebaselining:
                _payload["rebaselining"] = True   # T-11239: absent unless declared
            if merge_invalid_acceptance:
                # T-11939: the SECOND ground's key, on the OTHER member of `_LAND_QUEUE_WAIT_TYPES`.
                # BOTH rows must carry it for the same reason T-11278 gives for its pair: a peer
                # observed only at this seam would otherwise read as an ordinary batchable candidate
                # and be formed in, which is precisely the outcome the declaration exists to prevent.
                # Absent unless declared → a non-declaring land's heartbeat stays byte-identical.
                _payload["merge_invalid_acceptance"] = True
                _payload["merge_invalid_assertions"] = list(merge_invalid_assertions or [])
            # T-11278: the same two additive raw facts the reservation row carries, on the same
            # terms (absent unless known/true), so BOTH _LAND_QUEUE_WAIT_TYPES rows answer the
            # would-the-suite-run question and a land parked at either seam stays readable.
            if attempt:
                _payload["attempt"] = int(attempt)
            if no_tests:
                _payload["no_tests"] = True
            # T-11692: WHO occupies the pool this land is parked behind — the sibling key T-11691 put
            # on `waiting_for_land_reservation`, on the OTHER member of `_LAND_QUEUE_WAIT_TYPES`. The
            # holder dict was ALREADY resolved on every beat here and spent on the T-11076 stderr line
            # alone, then thrown away, so durable state could say how long a land waited but never
            # what it waited FOR. Hoisted to one local, reused by BOTH surfaces: no extra /proc read
            # per beat. Same as the sibling: ALWAYS PRESENT, the unknown RECORDED (`resolved: false`)
            # rather than left to be inferred from an absent key — absent means unrecorded, never
            # "no holder". RECORDS ONLY: no reaping, timeout, takeover or lock-breaking rides on it.
            #
            # THE ONE DIVERGENCE FROM THE SIBLING, and it is why this was a separate card: the
            # reservation has ONE holder, so `_flock_holder` there names THE blocker. This pool has
            # N slots and we probe slot-0 ONLY — a good guess (the pool packs onto low slots, so a
            # full pool always has one there, and it is the first slot this land re-tries) but NOT
            # the claim "this is the pool's only blocker". Probing all N would cost N `/proc/locks`
            # reads per beat on the busiest row in the journal to produce a set no reader asked for,
            # and there is no "the slot this land is retrying" to name instead — `_verify_admission`
            # polls the whole pool. So the meaning is STATED rather than left implicit: `slot` rides
            # BOTH branches (it says where we LOOKED, true whether or not anything was found) and
            # together with the existing `slots` reads as "1 of N, probed at slot-0". Without it a
            # reader would take slot-0's holder for the pool's only blocker.
            _slot_probed = 0
            _holder = _flock_holder(_verify_slot_dir(main_wt) / f"slot-{_slot_probed}")
            _payload["holder"] = ({"resolved": True, "slot": _slot_probed, "pid": _holder["pid"],
                                   "label": _holder.get("label"),
                                   "age_s": (None if _holder.get("age_s") is None
                                             else int(_holder["age_s"]))}
                                  if _holder else {"resolved": False, "slot": _slot_probed})
            _append_event("waiting_for_verify_admission_slot", task_id, _payload,
                          events_path=main_wt / "events.jsonl")
            # T-11076: the same beat, on STDERR, for the human watching the terminal. Inside the
            # SAME throttle branch as the journal emit — one cadence, one switch
            # (YITC_VERIFY_HEARTBEAT_SECS<=0 disables both). STDOUT stays clean for the `LAND:` token.
            # Reuses the `_holder` resolved just above (T-11692) — the line is unchanged.
            print(_wait_heartbeat_line("a verify-admission slot", "waiting_for_verify_admission_slot",
                                       waited_s, _holder,
                                       extra=f"all {int(slots)} slot(s) busy"),
                  file=sys.stderr, flush=True)
    # T-12258: the in-flock seam needs the acquire span as a NUMBER, and `_verify_admission` already
    # measures exactly that into `wait_out`. A caller that passes a probe but no sink gets its own
    # local one rather than a second measurement — one clock, one span (CHARTER §P5).
    _wait_sink = wait_out if wait_out is not None else ([] if withdraw_probe is not None else None)
    with _verify_admission(main_wt, slots, on_wait=on_wait, wait_out=_wait_sink):
        # T-12258 (SPEC-0184 rule 16), OBSERVATION POINT (1) — THE AUTHORITY. Inside the `with`, so
        # the slot flock is HELD, and BEFORE `run_verify()`, so this is the last instant before the
        # verify is PAID. Past this line the land is ADMITTED and the never-interrupt invariant
        # applies: no later path observes the request and no signal of any kind is ever sent.
        if withdraw_probe is not None and withdraw_probe():
            raise _LandWithdrawn("waiting_for_verify_admission_slot",
                                 _wait_sink[-1] if _wait_sink else 0.0)
        return run_verify()


def _verify_duration_samples_from_journal(main_wt: Path, limit: int, *, _run_git_cap, _VERIFY_DURATION_SERIES_UNIT_MS, sampled: "list | None" = None, credited: "dict | None" = None) -> "list":
    """T-11440 — the HISTORY half of the median window: up to `limit` prior green lands' per-file
    measurements, most recent first, as `[{name: wall_ms}, ...]`.

    THE PROBLEM THIS SOLVES, stated plainly because it is the one non-obvious thing here.
    `duration_series` (T-11315) publishes every started file's wall but DROPS THE NAMES — deliberately,
    since names are what the rejected raw dump spent its bytes on. So the values alone cannot be folded
    per file. What makes them foldable is that the series is laid out in file-NAME order and the row
    carries the `sha` that produced it: the names are RE-DERIVABLE from the tree itself
    (`git ls-tree <sha> -- tests/`, top-level `test_*.py`, sorted). No new field, no new store, no
    second metrics path — the journal already holds everything needed.

    AND IT IS VERIFIED, NEVER ASSUMED. A row is accepted ONLY when the reconstructed name count EQUALS
    the series' own `count`. That equality is the whole safety argument: a mismatch means the tree and
    the run disagree (a fail-fast run that stopped launching, a row whose sha no longer resolves, a
    layout change), and zipping them anyway would attribute every file's duration to the WRONG file
    from the divergence onward — an error that produces a complete, plausible, entirely wrong table.
    So a mismatched row is SKIPPED, silently and completely. Measured on three consecutive sampled
    lands the reconstruction matched exactly (952/952, 951/951, 951/951).

    FAIL-SOFT THROUGHOUT. Unparseable line, missing key, unresolvable sha, git failure — each skips its
    row. The worst outcome is a smaller sample window, which degrades the STATISTIC and can never
    corrupt it. Rows without a series at all are the NORMAL majority of history (the key only exists
    since T-11315: 188 of 4678 green lands carry one), so their absence is expected, not a defect.

    UNITS: `walls_ds` values are in `unit_ms` quanta and are multiplied here, ONCE, at the read. Every
    caller downstream works in milliseconds.

    STAGE-6 RUNS ARE SAMPLES TOO (T-14241). A runner-marked `tests_passed` row carries the same
    record (`verify_metrics.per_file_durations`), so a land that CREDITS that run (SPEC-0065 §Bound)
    and measures nothing itself still leaves the window something to read. Its names come from the
    tree it tested (`stage6_run.tree`) under the same count check; a NARROWED run, whose series names
    only the files it ran, takes them from its own `per_file_outcomes` sidecar instead — admitted
    only when the file's sha256 equals the locator's, so a pruned or rewritten sidecar skips the row.
    Each run is one row, so it is sampled once; a credited land carries no record of its own and adds
    nothing. ONLY A CREDITED RUN IS A SAMPLE: a Stage-6 row is taken when a land newer than it in the
    journal names it as its `stage6_credit`, or when it is the `credited` ref of the land refreshing
    now (not journaled yet) — an uncredited run was measured again by its land, so taking it too
    would count that change twice, and with no credit anywhere the window is exactly main's.
    The `credited` run of the land refreshing now holds ONE reserved slot: the other samples fill at
    most `limit - 1`, and the walk goes on past them until it meets that run (or a row older than it),
    so newer measured lands can never crowd it out of its own land's window.
    `sampled`, when given, collects the `(task_id, ts)` of each Stage-6 row taken."""
    out: list = []
    if limit < 1:
        return out
    path = Path(main_wt) / "events.jsonl"

    def _newest_first():
        """T-13138 (X-1687) — the live file's `land_completed` lines, NEWEST FIRST, walked BACKWARDS in
        bounded slices (`journal._backward_superset_chunks`, the shared token-superset walker) and
        abandoned once `limit` rows are found: the reader used to hold the whole live segment
        (`read_text().splitlines()`, ~116 MB on the kernel checkout, several times that as objects)
        on every land's tail to look at its last few green lands. Same horizon (this one file), same
        token prefilter, same `errors="replace"` decode; an unreadable file yields nothing, as the
        failed read did."""
        try:
            for slice_lines, _head, _start in journal_mod._backward_superset_chunks(
                    path, ['"land_completed"', '"tests_passed"']):
                for raw in reversed(slice_lines):
                    yield raw.decode("utf-8", "replace")
        except OSError:
            return

    credited_refs: set = set()
    own_key = None
    own_sample = None
    if isinstance(credited, dict):
        own_key = (credited.get("task"), credited.get("ts"))
        credited_refs.add(own_key)
    cap = limit - 1 if own_key is not None else limit
    for ln in _newest_first():
        if len(out) >= cap and own_key is None:
            break
        if '"land_completed"' not in ln and '"tests_passed"' not in ln:
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        kind = e.get("type")
        if kind not in ("land_completed", "tests_passed"):
            continue
        is_own = own_key is not None and kind == "tests_passed" and (e.get("task_id"), e.get("ts")) == own_key
        if own_key is not None and len(out) >= cap and not is_own:
            if own_sample is not None or str(e.get("ts") or "") < str(own_key[1] or ""):
                break                      # the window is full and its credited run is behind us
            continue
        d = e.get("data") or {}
        vm = d.get("verify_metrics") or {}
        if kind == "land_completed":
            _cr = d.get("stage6_credit")
            if d.get("status") == "ok" and isinstance(_cr, dict):
                credited_refs.add((_cr.get("task"), _cr.get("ts")))
            if d.get("status") != "ok" or vm.get("fail_class") != "ok":
                continue
            sha = d.get("sha")
        else:                              # a runner-marked green Stage-6 run (T-14241)
            if (e.get("task_id"), e.get("ts")) not in credited_refs:
                continue                   # no land credited it: its land measured it again
            run = d.get("stage6_run")
            sha = run.get("tree") if isinstance(run, dict) else None
        record = vm.get("per_file_durations") or {}
        series = (record.get("duration_series") if isinstance(record, dict) else None) or {}
        if series.get("order") != "alphabetical" or not series.get("walls_ds"):
            continue
        if not sha:
            continue
        try:
            vals = [int(v) for v in str(series["walls_ds"]).split(",")]
        except ValueError:
            continue
        if len(vals) != int(series.get("count") or -1):
            continue
        try:
            r = _run_git_cap(["ls-tree", "-r", "--name-only", str(sha), "--", "tests/"], main_wt)
        except Exception:
            continue
        if getattr(r, "returncode", 1) != 0:
            continue
        names = sorted(p.split("/", 1)[1] for p in r.stdout.splitlines()
                       if p.startswith("tests/") and "/" not in p.split("/", 1)[1]
                       and p.rsplit("/", 1)[-1].startswith("test_") and p.endswith(".py"))
        unit = max(1, int(series.get("unit_ms") or _VERIFY_DURATION_SERIES_UNIT_MS))
        if len(names) == len(vals):
            sample = {n: v * unit for n, v in zip(names, vals)}
        elif kind == "tests_passed":
            sample = _stage6_sidecar_walls(vm.get("per_file_outcomes"), set(names))
            if len(sample) != len(vals):
                continue                   # no sidecar, or one that is not this run's — skip it whole
        else:
            continue                       # the row and its tree disagree — skip it whole
        if is_own:
            own_sample = sample
        else:
            out.append(sample)
        if kind == "tests_passed" and sampled is not None:
            sampled.append((e.get("task_id"), e.get("ts")))
        if own_key is not None and own_sample is not None and len(out) >= cap:
            break
    return ([own_sample] if own_sample is not None else []) + out


def _stage6_sidecar_walls(locator, live: set) -> dict:
    """T-14241 — `{name: wall_ms}` of the files a NARROWED Stage-6 run started, read from the run's
    own T-12190 `per_file_outcomes` sidecar. Admitted only when the bytes hash to the locator's
    sha256 (the run that wrote it, not a later file at that path) and only for names the tested tree
    holds; a `not-started` row has no wall and is left out. Any fault returns `{}`."""
    try:
        if not isinstance(locator, dict) or not locator.get("path") or not locator.get("sha256"):
            return {}
        raw = Path(str(locator["path"])).read_bytes()
        if hashlib.sha256(raw).hexdigest() != locator["sha256"]:
            return {}
        out = {}
        for row in json.loads(raw.decode("utf-8")).get("files") or ():
            name, wall = row.get("file"), row.get("wall_ms")
            if isinstance(name, str) and name in live and isinstance(wall, int) and not isinstance(wall, bool):
                out[name] = wall
        return out
    except Exception:                      # noqa: BLE001 — an unreadable sidecar is no sample
        return {}


def _flaky_sensitive_knob(env_name: str, default: int, band: tuple, *, env: "dict | None" = None) -> int:
    """T-12358 — the ONE resolver behind both thresholds: env > machine settings > built-in, fail-safe
    to the built-in on anything blank / non-numeric / outside `band`. Copied in shape from
    `verify_runner._verify_retry_max_files` (the T-12357 sibling) so the family has one precedence."""
    _env = os.environ if env is None else env
    raw = _env.get(env_name)
    if raw is None or not str(raw).strip():
        try:
            from lib import machine_settings      # deferred: keeps the hot import graph unchanged
            raw = machine_settings.get_value(env_name)
        except Exception:
            raw = None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    lo, hi = band
    return value if lo <= value <= hi else default


def _flaky_sensitive_enter(*, env: "dict | None" = None, _flaky_sensitive_knob, _FLAKY_SENSITIVE_ENTER_DEFAULT=_FLAKY_SENSITIVE_ENTER_DEFAULT, _FLAKY_SENSITIVE_ENTER_ENV=_FLAKY_SENSITIVE_ENTER_ENV, _FLAKY_SENSITIVE_ENTER_RANGE=_FLAKY_SENSITIVE_ENTER_RANGE) -> int:
    """T-12358 — how many isolated-pass `flaky_retry` rows a file needs inside the window to ENTER
    the declared load-sensitive set automatically at the land tail. PERFORMANCE by construction: it
    changes WHERE a file runs (the serialized tail instead of the pool), never WHETHER its verdict
    counts, so no value can admit a failing check or excuse a file from the verdict."""
    return _flaky_sensitive_knob(_FLAKY_SENSITIVE_ENTER_ENV, _FLAKY_SENSITIVE_ENTER_DEFAULT,
                                 _FLAKY_SENSITIVE_ENTER_RANGE, env=env)


def _flaky_sensitive_window_days(*, env: "dict | None" = None, _flaky_sensitive_knob, _FLAKY_SENSITIVE_WINDOW_DAYS_DEFAULT=_FLAKY_SENSITIVE_WINDOW_DAYS_DEFAULT, _FLAKY_SENSITIVE_WINDOW_DAYS_ENV=_FLAKY_SENSITIVE_WINDOW_DAYS_ENV, _FLAKY_SENSITIVE_WINDOW_DAYS_RANGE=_FLAKY_SENSITIVE_WINDOW_DAYS_RANGE) -> int:
    """T-12358 — the window, in days back from the landing moment, over which the land tail folds
    isolated-pass `flaky_retry` rows per file. PERFORMANCE on the same terms as the threshold."""
    return _flaky_sensitive_knob(_FLAKY_SENSITIVE_WINDOW_DAYS_ENV, _FLAKY_SENSITIVE_WINDOW_DAYS_DEFAULT,
                                 _FLAKY_SENSITIVE_WINDOW_DAYS_RANGE, env=env)


def _flaky_retry_isolated_passes(journal_path, since: str, until: str, *,
                                 rows_out: "list | None" = None, rows_out_types=()) -> dict:
    """T-12358 — `{<test basename>: [<locator>, ...]}` of every ISOLATED-PASS `flaky_retry` row on a
    `land_completed` journal row whose `ts` lies in `[since, until]` — the fold the automatic entry is
    decided on. One record per file per retry, so a file's list length IS its count.

    T-14053 — AND on a governed Stage-6 run's `tests_passed` / `tests_failed` row: a file that flakes
    mostly in Stage-6 pools never reached this count, because `task test --run` keeps its routed
    record under the venue-prefixed `verify_metrics.venue_flaky_retry` (unfolded) and no land row
    carries it. Those rows are read on that key and on `flaky_retry` (the T-13545 layer fragment,
    whose rows name no `file` and so count nothing), under the SAME row predicate below; a
    `land_completed` row is read on `flaky_retry` alone, as before (the land folds the venue key onto
    it). The locator then names the Stage-6 row.

    READS THE ONE RECORD T-12357 ALREADY WRITES (CHARTER §P1 F1 — never a second counter):
    `data.verify_metrics.flaky_retry`, in BOTH shapes it takes — the LOCAL land's `{rows: [...]}` and a
    ROUTED land's per-leg `{cand: {rows}, pinned: {rows}}` (a leg that recorded nothing is `null`; the
    string `"unknown"` carries no rows and folds to nothing). A row counts iff `isolated == "pass"`
    AND it is not a T-12426 LANE retest (`lane: True`): an `isolated: fail` named a real defect,
    `unrunnable` proved nothing, and a lane row is an already-listed file's own retest — none is a
    pool flake this fold may enter.

    SEGMENT-AWARE (SPEC-0190 rule 4) THROUGH THE ONE READER: the rows arrive from
    `journal.segment_rows_since` — the same windowed fold the `debt` views use — so the segment set is
    pre-filtered off `since` and every row is parsed by the ONE instrumented primitive (T-12034 reads
    counters; a raw `read_text` + `json.loads` here was a SECOND scan the census flagged). The in-loop
    `ts` compare stays the sole decider of membership. The locator is
    `events.jsonl#ts=<ts>` (+`:<leg>` when the row was leg-stamped) — the same materialized-journal
    locator form the corpus cites everywhere, resolvable by `journal query --grep`. DEDUPED on
    (ts, leg, file) so a union-merged duplicate row can never count twice. FAIL-SOFT per row: an
    unparseable line or a malformed record skips ITSELF and can only shrink the fold.

    T-12501 — `rows_out`, when given, receives the SAME rows this read produced, so the timeout fold
    (`_timeout_at_bound_entries`) consumes them instead of opening the journal a second time: one
    reader site, one scan (the census identity is unchanged). A caller that omits it is byte-identical.

    T-13138 (X-1687) — the read is DECLARED: `land_completed` (the only type this fold reads) plus
    `rows_out_types`, the types the `rows_out` consumer reads — so a window's rows of every OTHER type
    (~1.4 GB of them parsed on the kernel checkout) are never held. Each consumer filters by type
    itself, so its answer is unchanged."""
    out: dict = {}
    seen: set = set()
    try:
        rows = journal_mod.segment_rows_since(journal_path, since, until=until,
                                              types=(*_FLAKY_ENTRY_ROW_TYPES, *rows_out_types))
    except OSError:
        return out
    if rows_out is not None:
        rows = list(rows)
        rows_out.extend(rows)
    for e in rows:
        etype = e.get("type") if isinstance(e, dict) else None
        if etype not in _FLAKY_ENTRY_ROW_TYPES:
            continue
        ts = str(e.get("ts") or "")
        if not ts or ts < since or ts > until:
            continue
        data = e.get("data")
        metrics = data.get("verify_metrics") if isinstance(data, dict) else None
        if not isinstance(metrics, dict):
            continue
        keys = ("flaky_retry",) if etype == "land_completed" else ("venue_flaky_retry", "flaky_retry")
        legs = []
        for rec in (metrics.get(k) for k in keys):
            if isinstance(rec, dict):
                legs += [(None, rec)] if "rows" in rec else [(k, v) for k, v in rec.items()]
        for leg, lrec in legs:
            if not isinstance(lrec, dict):
                continue
            for row in (lrec.get("rows") or []):
                if not isinstance(row, dict) or row.get("isolated") != "pass":
                    continue
                if row.get("lane"):
                    # T-12426 — a LANE retest is not this fold's evidence. The question here is «did
                    # this file pass ALONE after failing in the POOL»; a lane member never ran in the
                    # pool, so counting its isolated pass would re-add (or duplicate) a
                    # tests/load-sensitive.txt line for a file ALREADY in the lane — the T-12378
                    # re-add class, which the existing `n not in listed` guard cannot see when the
                    # card removed the line in this very ship diff. A plain POOL row is untouched.
                    continue
                name = row.get("file")
                if not isinstance(name, str) or not name:
                    continue
                stamped = row.get("leg") if isinstance(row.get("leg"), str) else leg
                key = (etype, ts, stamped, name)
                if key in seen:
                    continue
                seen.add(key)
                out.setdefault(name, []).append(
                    f"events.jsonl#ts={ts}" + (f":{stamped}" if stamped else ""))
    return out


def _unit_rescue_passes(rows, since: str, until: str, *, heads_out: "dict | None" = None,
                        stage6_commits: "dict | None" = None) -> dict:
    """T-13609 (SPEC-1006 rule 11) — `{(<layer>, <kind>, <project>, <name>): [<locator>, ...]}` of
    every RESCUED per-unit `flaky_retry` row on a `land_completed` row (and, T-14169, on a governed
    Stage-6 row) of `rows` whose `ts` lies in
    `[since, until]` — the fold the per-unit lane entry is decided on. `kind` is `unit` (name = the
    repo-relative test file) or `group` (name = the declared group's label, rescued and counted
    whole); `project` is "" where the runner has none. One record per unit per rescue, so a
    unit's list length IS its count.

    PURE over `rows` — the window rows `_flaky_retry_isolated_passes(rows_out=...)` above already
    read, as `worktree._timeout_at_bound_entries` consumes them — so this fold opens no journal and
    adds no reader site. It reads the ONE record T-13607 already writes,
    `data.verify_metrics.flaky_retry.rows[]`, and keeps no counter of its own. A row counts iff it
    is a UNIT row (it names a `layer` and a `unit` or a `group`), `rescued` is exactly true (it
    passed alone under the layer's `rescue: on` — a pass under `rescue: off` is
    diagnostic and no rescue), and it is not a LANE row (`lane: true`: a listed unit's own re-run,
    which never ran in the batch). The engine fold above counts rows by their `file` key, which a
    unit row does not carry, and this one requires `layer`, which an engine row does not carry:
    neither can count the other's rows.

    The locator form, the dedup — on (ts, leg, the key) — and the fail-soft per row are that
    fold's: a malformed row skips ITSELF and can only shrink the answer.

    T-13988 — `heads_out`, when given, receives `{(<key>, <locator>): <commit>}` for every counted
    rescue whose leg recorded the commit its units ran on (`flaky_retry.run_heads[<leg>]`, or the
    `run_head` of a record that was never folded per leg); a rescue whose leg recorded none is absent
    from it. Keyed by the unit as well as the locator, because two rows with one `ts` and leg can carry
    different units on different commits. The answer itself is unchanged.

    T-14169 — AND on a GOVERNED Stage-6 run's `tests_passed` / `tests_failed` row (one carrying the
    runner's `stage6_run` mark; a hand-recorded row has none and counts nothing): since a land may take
    a card's Stage-6 run as its candidate leg (SPEC-0065 §Bound) and then runs no verify of its own,
    rescues recorded only there never reached this count. Such a row is read on `venue_flaky_retry` and
    `flaky_retry` (a routed run keeps its record under the venue key — the engine fold's pair, T-14053),
    under the same row predicate and dedup. Its commit is NOT a leg's `run_heads` (a Stage-6 record keeps
    none) but `stage6_commits[<ts>]` — the caller's `worktree._rescue_run_commits` answer, the run's
    merge-base with main (T-14130). A `land_completed` row carrying `stage6_credit` gives no `cand`-leg
    rescue: that leg's verdict is the credited run's, counted once on the run's own row; its other legs
    are its own runs."""
    out: dict = {}
    seen: set = set()
    for e in rows or []:
        etype = e.get("type") if isinstance(e, dict) else None
        if etype not in _FLAKY_ENTRY_ROW_TYPES:
            continue
        ts = str(e.get("ts") or "")
        if not ts or ts < since or ts > until:
            continue
        data = e.get("data")
        metrics = data.get("verify_metrics") if isinstance(data, dict) else None
        if not isinstance(metrics, dict):
            continue
        stage6 = etype != "land_completed"
        if stage6 and not isinstance(data.get("stage6_run"), dict):
            continue                         # not the runner's governed row: no run to count
        credited = not stage6 and isinstance(data.get("stage6_credit"), dict)
        legs = []
        for rec in (metrics.get(k) for k in (("venue_flaky_retry", "flaky_retry") if stage6 else ("flaky_retry",))):
            if isinstance(rec, dict):
                legs += [(None, rec)] if "rows" in rec else [(k, v) for k, v in rec.items()]
        for leg, lrec in legs:
            if not isinstance(lrec, dict):
                continue
            heads = lrec.get("run_heads") if isinstance(lrec.get("run_heads"), dict) else {}
            own_head = lrec.get("run_head") if isinstance(lrec.get("run_head"), str) else None
            for row in (lrec.get("rows") or []) if isinstance(lrec.get("rows"), list) else []:
                if not isinstance(row, dict) or row.get("rescued") is not True or row.get("lane"):
                    continue
                if credited and (row.get("leg") if isinstance(row.get("leg"), str) else leg) == "cand":
                    continue                 # the credited run's verdict, counted on its own row
                kind = "group" if "group" in row else "unit"
                layer, name, proj = row.get("layer"), row.get(kind), row.get("project", "")
                if not all(isinstance(v, str) for v in (layer, name, proj)) or not layer or not name:
                    continue
                stamped = row.get("leg") if isinstance(row.get("leg"), str) else leg
                key = (layer, kind, proj, name)
                if (ts, stamped, key) in seen:
                    continue
                seen.add((ts, stamped, key))
                loc = f"events.jsonl#ts={ts}" + (f":{stamped}" if stamped else "")
                out.setdefault(key, []).append(loc)
                if stage6:
                    head = (stage6_commits or {}).get(ts)
                else:
                    head = heads.get(stamped) if isinstance(stamped, str) else None
                    head = head if isinstance(head, str) and head else own_head
                if heads_out is not None and head:
                    heads_out[(key, loc)] = head
    return out


def _per_unit_flaky_rate(events_path, since=None, until=None, *, _iter_events, _ev_dt,
                         joined_out: "list | None" = None) -> dict:
    """T-13608 (SPEC-1006 rule 13) — the PER-UNIT FLAKY RATE of adapter-backed consumer verify
    layers: for each unit, the first-attempt failures a re-run rescued, over the unit's runs.
    DERIVED at read time from the rows T-13606 / T-13607 already write (SPEC-0025) — it stores
    nothing, and a second run over the same rows returns the same answer.

    WHAT IS READ, per verify record — a `land_completed` row (landed or aborted) and a Stage-6
    `tests_passed` / `tests_failed` row:
      * the RUNS — `data.consumer_verify_layers[].adapter.units` of every layer whose adapter
        record is `usable: true` (a void report's rows decide nothing, SPEC-1006 rule 4, so they
        count nothing here; such records are counted under `records.not_usable`). A unit row
        whose `status` is `passed`, `failed` or `error` is one run of that unit; `failed` /
        `error` is a first-attempt failure;
      * the RESCUES — `data.verify_metrics.flaky_retry` rows that carry an `attempts` list (what
        tells a unit row from a layer or file row) and read `isolated: pass` with `rescued: true`.
        A row whose re-run passed under `rescue: off` (`isolated: pass`, `rescued: false`) or
        never passed (`isolated: fail`) is counted beside it (`passed_alone_unrescued`,
        `failed_alone`) and never in the rate.

    THE UNIT is SPEC-1006 rule 2's: `(layer, runner project, file)`. A declared group is counted
    WHOLE, as it is re-run — one entity `(layer, project, group)`, one run per record in which any
    member ran, a first-attempt failure when any member failed.

    A RE-RUN ROW COUNTS ONLY AGAINST A FAILED RUN OF THE SAME RECORD, ONCE: the numerator row and
    the denominator row are joined inside one journal row, so `rescued <= first_failed <= runs`
    and a rate is never above 1. The per-unit report rows are the candidate leg's. A `flaky_retry`
    unit row that cannot be joined is reported under `rows_outside_rate` with its reason and
    counted in no rate: `other-leg` (stamped with another leg), `no-run-on-record` (its unit has
    no run on its own record), `run-not-failed-on-record` (the unit's run there did not fail),
    `second-row-on-record` (the record already gave this unit a re-run row) or
    `outcome-unreadable` (its `isolated` / `rescued` pair is not one the writer records — a
    rescue is counted only for `isolated: pass` with `rescued: true`).

    IDENTITY IS READ, NEVER COERCED: a row whose layer, project, group or file name is not the
    string (or absent project) the writers record is skipped — it names no unit, so it adds no
    run, no rescue and no listed row.

    WINDOW: `[since, until)` over the row's `ts`, the journal lenses' shared predicate
    (`views._window_predicate`); both None = all time. An exact duplicate row (a union-merged
    journal line) is read once. FAIL-SOFT per row and per field: a malformed row or record skips
    itself. No adapter record in the window answers `no_data` naming what was absent, never a
    fabricated 0. REPORT-ONLY: nothing reads this to decide a verdict, a lane or a selection.

    T-13615 — `joined_out`, when a list is given, receives one `(entity, outcome, row)` per re-run
    row this fold JOINED to a failed run (`entity` = `(layer, project, "unit" | "group", name)`,
    `outcome` = the count it entered, `row` = the `flaky_retry` row as recorded), so the per-case
    reading (`_per_case_rescued_failures`) counts cases on exactly the rows this rate counted —
    one join, one journal read. A caller that omits it gets the same answer as before."""
    from lib import views as _views       # deferred: `views` reaches the land modules function-locally too
    in_window = _views._window_predicate(since, until, _ev_dt=_ev_dt)
    units: dict = {}
    outside: list = []
    records = {"read": 0, "usable": 0, "not_usable": 0}
    seen: set = set()

    kinds = ("land_completed", "tests_passed", "tests_failed")

    def _entity(layer, project, group, name):
        """The unit's identity, or None when a part of it is not what the writers record: a
        non-empty string layer, an absent or string project, and a non-empty string group or —
        with no group — file name. A malformed part is never turned into text: its row is skipped."""
        if not (isinstance(layer, str) and layer) or not (project is None or isinstance(project, str)):
            return None
        if group is not None and group != "":
            return (layer, project or "", "group", group) if isinstance(group, str) else None
        return (layer, project or "", "unit", name) if isinstance(name, str) and name else None

    for e in _iter_events(events_path, types=kinds):
        if not isinstance(e, dict) or e.get("type") not in kinds or not in_window(e):
            continue
        data = e.get("data")
        if not isinstance(data, dict):
            continue
        try:
            ident = json.dumps(e, sort_keys=True, default=str)
        except (TypeError, ValueError):
            continue
        if ident in seen:
            continue
        seen.add(ident)
        ran: dict = {}                               # entity -> a first-attempt failure in this record
        layers = data.get("consumer_verify_layers")
        for lrow in layers if isinstance(layers, list) else []:
            rec = lrow.get("adapter") if isinstance(lrow, dict) else None
            if not isinstance(rec, dict) or not (isinstance(lrow.get("layer"), str) and lrow["layer"]):
                continue
            records["read"] += 1
            if rec.get("usable") is not True:
                records["not_usable"] += 1
                continue
            records["usable"] += 1
            for u in rec.get("units") if isinstance(rec.get("units"), list) else []:
                if not isinstance(u, dict) or u.get("status") not in ("passed", "failed", "error"):
                    continue
                key = _entity(lrow["layer"], u.get("project"), u.get("group"), u.get("file"))
                if key is None:
                    continue
                ran[key] = ran.get(key, False) or u["status"] != "passed"
        for key, failed in ran.items():
            row = units.setdefault(key, {"runs": 0, "first_failed": 0, "rescued": 0,
                                         "passed_alone_unrescued": 0, "failed_alone": 0})
            row["runs"] += 1
            row["first_failed"] += 1 if failed else 0
        metrics = data.get("verify_metrics")
        retry = metrics.get("flaky_retry") if isinstance(metrics, dict) else None
        if not isinstance(retry, dict):
            continue
        legs = [(None, retry)] if "rows" in retry else list(retry.items())
        joined: set = set()                          # entities whose one re-run row this record has given
        for leg, lrec in legs:
            rrows = lrec.get("rows") if isinstance(lrec, dict) else None
            for r in rrows if isinstance(rrows, list) else []:
                if not isinstance(r, dict) or not isinstance(r.get("attempts"), list):
                    continue                         # `attempts` is what tells a unit row from the others
                key = _entity(r.get("layer"), r.get("project"), r.get("group"), r.get("unit"))
                if key is None:
                    continue
                stamped = r["leg"] if isinstance(r.get("leg"), str) else leg if isinstance(leg, str) else None
                iso, resc = r.get("isolated"), r.get("rescued")
                outcome = ("rescued" if iso == "pass" and resc is True else
                           "passed_alone_unrescued" if iso == "pass" and resc is False else
                           "failed_alone" if iso == "fail" and resc is not True else None)
                reason = ("other-leg" if stamped not in (None, "cand") else
                          "no-run-on-record" if key not in ran else
                          "run-not-failed-on-record" if not ran[key] else
                          "second-row-on-record" if key in joined else
                          "outcome-unreadable" if outcome is None else None)
                if reason:
                    outside.append({"layer": key[0], key[2]: key[3], **({"project": key[1]} if key[1] else {}),
                                    "reason": reason, **({"leg": stamped} if stamped else {}),
                                    "ts": e["ts"] if isinstance(e.get("ts"), str) else ""})
                    continue
                joined.add(key)
                units[key][outcome] += 1
                if joined_out is not None:
                    joined_out.append((key, outcome, r))
    # ONE TOTAL ORDER, from the rows' own fields: by rate, then rescues, then the whole identity
    # (layer, project, kind, name) — the kind included, since a group and a file may share a name.
    # So the answer is a function of the journal's rows as a multiset, never of their physical
    # order or of how they are split across segments (SPEC-0190 rule 5).
    rows = []
    for (layer, project, kind, name), c in sorted(units.items()):
        rows.append({"layer": layer, kind: name, **({"project": project} if project else {}),
                     "runs": c["runs"], "first_failed": c["first_failed"], "rescued": c["rescued"],
                     "flaky_rate": round(c["rescued"] / c["runs"], 4),
                     **{k: c[k] for k in ("passed_alone_unrescued", "failed_alone") if c[k]}})
    rows.sort(key=lambda r: (-r["flaky_rate"], -r["rescued"]))          # stable: ties keep identity order
    out = {"lens": "per-unit-flaky-rate (T-13608 / SPEC-1035 rule 13) — per unit of an adapter-backed "
                   "verify layer: first-attempt failures a re-run rescued, over the unit's runs. "
                   "Derived from the journal at read time; report-only.",
           "window": _views._window_block(since, until), "records": records}
    if not records["usable"]:
        out["no_data"] = ("no usable per-unit report (`consumer_verify_layers[].adapter`, usable: true) on a "
                          "`land_completed` / `tests_passed` / `tests_failed` row in this window — no layer "
                          "of this project ran through a declared adapter here, so there is no run to rate")
    elif not rows:
        out["no_data"] = ("the usable per-unit reports in this window carry no unit row with a readable "
                          "identity and a verdict (passed / failed / error) — there is no run to rate")
    out["unit_count"] = len(rows)
    out["units"] = rows
    if outside:
        out["rows_outside_rate"] = sorted(outside, key=lambda o: (
            o["ts"], o["layer"], o.get("project", ""), "group" not in o, o.get("group") or o["unit"],
            o["reason"], o.get("leg", "")))
    return out


def _per_case_rescued_failures(events_path, since=None, until=None, *, _iter_events, _ev_dt) -> dict:
    """T-13615 (SPEC-1006 rule 13, GRANULARITY) — the PER-CASE reading of adapter-backed consumer
    verify layers: for each test case, how often it failed on a first attempt that a re-run of its
    unit then rescued. It names WHICH test in a file is flaky. DERIVED at read time from the rows
    T-13607 already writes (SPEC-0025); it stores nothing and decides nothing.

    WHAT IS COUNTED. A RESCUE is exactly what the per-unit rate counts as one: a per-unit
    `flaky_retry` row joined by `_per_unit_flaky_rate` to a failed run of its own record, reading
    `isolated: pass` with `rescued: true` — this function takes those rows from that fold
    (`joined_out`) and reads the journal through it, never a second time. Each case the row names
    under `first_failed_cases` (the cases that failed on the FIRST attempt) gains one, once per
    row whatever the number of times the row names it. A case that failed only on a re-run
    attempt (`attempts[].failed_cases`) did not fail on a first attempt and gains nothing; a row
    whose re-run passed under `rescue: off`, or never passed, is no rescue and names no case here.

    THE CASE is `(layer, runner project, unit file or declared group, case id)`; the id is the
    string the row records (for a group the writer prefixes it with the member file). An entry
    whose id is not a non-empty string is never turned into text.

    WHAT A ROW DOES NOT NAME IS STATED, NEVER DROPPED — per unit, under `rescues_not_named`:
    `rescues_without_case` (every rescue whose row names no readable case, whatever else the row
    carries — a script-style unit has no case rows) and `unnamed_cases` (first-attempt failed cases
    the row counts but does not name: its `first_failed_cases_more`, plus every entry with an
    unreadable id).

    WINDOW, duplicate lines, void reports, legs and malformed rows: as `_per_unit_flaky_rate`
    reads them — its `records` block is carried here unchanged. No usable per-unit report in the
    window answers `no_data`; usable reports with no rescue answer an empty case list beside
    `rescues.rows: 0`. One total order from the rows' own fields (count, then the whole
    identity), so the answer is a function of the journal rows as a multiset. REPORT-ONLY."""
    joined: list = []
    per_unit = _per_unit_flaky_rate(events_path, since, until, _iter_events=_iter_events, _ev_dt=_ev_dt,
                                    joined_out=joined)
    cases: dict = {}
    unnamed: dict = {}
    rescues = {"rows": 0, "naming_a_case": 0}
    for key, outcome, row in joined:
        if outcome != "rescued":
            continue
        rescues["rows"] += 1
        listed = row.get("first_failed_cases")
        named, unreadable = set(), 0
        for c in listed if isinstance(listed, list) else []:
            cid = c.get("id") if isinstance(c, dict) else None
            if isinstance(cid, str) and cid:
                named.add(cid)
            else:
                unreadable += 1
        more = row.get("first_failed_cases_more")
        more = more if isinstance(more, int) and not isinstance(more, bool) and more > 0 else 0
        for cid in named:
            cases[key + (cid,)] = cases.get(key + (cid,), 0) + 1
        rescues["naming_a_case"] += 1 if named else 0
        if more or unreadable or not named:
            gap = unnamed.setdefault(key, {"rescues_without_case": 0, "unnamed_cases": 0})
            gap["unnamed_cases"] += more + unreadable
            gap["rescues_without_case"] += 0 if named else 1

    def _ident(key):
        return {"layer": key[0], key[2]: key[3], **({"project": key[1]} if key[1] else {})}

    rows = [{**_ident(key), "case": key[4], "rescued_first_failures": n}
            for key, n in sorted(cases.items(), key=lambda kv: (-kv[1], kv[0]))]
    out = {"lens": "per-case-rescued-failures (T-13615 / SPEC-1035 rule 13) — per test case of an "
                   "adapter-backed verify layer: how often it failed on a first attempt that a re-run "
                   "of its unit then rescued. Derived from the journal at read time; diagnostic, "
                   "report-only. The per-unit rate is the lens `per-unit-flaky-rate`.",
           "window": per_unit["window"], "records": per_unit["records"], "rescues": rescues}
    if "no_data" in per_unit:
        out["no_data"] = per_unit["no_data"]
    out["case_count"] = len(rows)
    out["cases"] = rows
    if unnamed:
        out["rescues_not_named"] = [{**_ident(key), **{k: v for k, v in gap.items() if v}}
                                    for key, gap in sorted(unnamed.items())]
    return out

def _verify_duration_drift_signals(series: "list", *, window: int = _VERIFY_DRIFT_WINDOW,
                                   scope_bin: float = _VERIFY_DRIFT_SCOPE_BIN,
                                   growth_ratio: float = _VERIFY_DRIFT_GROWTH_RATIO,
                                   min_growth_ms: int = _VERIFY_DRIFT_MIN_GROWTH_MS,
                                   percentiles: "tuple" = _VERIFY_DRIFT_PERCENTILES) -> "list":
    """T-11127 (SPEC-0132 Rule 7) — PURE, REPORT-ONLY: has the verify duration DISTRIBUTION drifted
    upward across lands? Folds the same OLDEST-FIRST `land_completed` `data` payloads its caller
    `_verify_scaling_signals` already holds, and returns human-readable lines — EMPTY when nothing
    moved. It reads one in-memory list, writes nothing, emits nothing, triggers nothing and moves no
    exit code (CHARTER §6 fence, the sibling's contract unchanged).

    THE HALF THIS READS, AND THE HALF IT DELIBERATELY DOES NOT. T-11124 made per-file duration a
    series with two complementary halves, and its own docstring names the blind spot: `slowest_files`
    is the TAIL, where one newly-pathological file shows first, while `wall_ms_pct` is the SHAPE, and
    "a broad uniform creep moves p50 while leaving the top-N membership byte-identical". The TAIL half
    is ALREADY WATCHED — `debt.slowest_decile_changes` (T-11125 / SPEC-0119 rule 19) reports entrants
    and grown members by name. This function is the SHAPE half and ONLY that: it never names a file.
    Re-deriving the tail reading here would be the parallel path CHARTER §P1 F1 forbids; a reader who
    wants "which file" goes to the sibling, which is where that answer lives.

    THE DELTA, NEVER THE LEVEL — the fence this card inherited and did not move. T-11124 scoped OUT
    judging any duration, so nothing here decrees how slow a suite may be: there is no budget, no
    target, and no threshold on a percentile's VALUE. Every bar is on MOVEMENT. This is also why the
    reading stays useful as the suite grows — an absolute bar falls silent exactly when everything
    settles just under it, which is when creep resumes unwatched.

    SCOPE COHORTS — the load-bearing rule, and the one a later reader must not "simplify" away.
    Percentiles here are NOT comparable across arbitrary lands. A land's `sample_count` equals its
    `test_file_count` in every recorded row, so a land is never SKIPPING files — it is running a
    DIFFERENTLY-SCOPED suite (the verify-layer scoping), and the recorded scopes span 84..1012 files.
    A naive fold over all lands reads +90% on p50 across one week from suite SCOPE alone. So rows are
    grouped into relative cohorts by `sample_count` and every cohort is judged against ITSELF. Two
    anchorings were measured and rejected before this one: anchoring on the LATEST land's scope makes
    the signal vocal or silent by accident of whichever suite ran last (the latest land had 2 peers),
    and anchoring on the median scope of a fixed horizon flipped its own reference population as the
    horizon changed. Judging every qualifying cohort independently depends on neither.

    THE FAIL DIRECTION IS SILENCE, inherited from the sibling deliberately. Too little history, an
    unparseable record, a non-positive percentile, a cohort astride a bin edge — every uncertainty
    resolves to SAYING NOTHING. A creep watch that cries wolf is unread within a week and its next
    real signal dies with it; a missed reading costs one more land's worth of delay.

    Args mirror the module constants and are injectable for tests only.
    Returns a list of `str`, deterministically ordered (cohort scope descending, then `percentiles`
    order). PURE: the input list and its dicts are never mutated."""
    def _median(values: "list") -> int:
        ordered = sorted(values)
        n = len(ordered)
        return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) // 2

    try:
        window = max(1, int(window))
        ratio = float(growth_ratio)
        floor_ms = int(min_growth_ms)
        bin_width = float(scope_bin)
    except (TypeError, ValueError):
        return []
    if not (bin_width > 0):
        return []
    log_base = math.log(1.0 + bin_width)

    cohorts: dict = {}
    for payload in series or []:
        if not isinstance(payload, dict):
            continue
        metrics = payload.get("verify_metrics")
        if not isinstance(metrics, dict):
            continue
        record = metrics.get("per_file_durations")
        if not isinstance(record, dict):
            continue
        pct = record.get("wall_ms_pct")
        scope = record.get("sample_count")
        if not isinstance(pct, dict):
            continue
        if isinstance(scope, bool) or not isinstance(scope, int) or scope <= 0:
            continue          # a scope-less record cannot be placed in a cohort ⇒ it is not an observation
        values = {}
        for key in percentiles:
            v = pct.get(key)
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                values = None
                break         # a partial record compares on no axis rather than on some
            values[key] = v
        if not values:
            continue
        cohorts.setdefault(int(math.floor(math.log(scope) / log_base)), []).append((scope, values))

    signals = []
    for cohort_key in sorted(cohorts, reverse=True):          # widest suite first, deterministic
        rows = cohorts[cohort_key]
        if len(rows) < 2 * window:
            continue          # no baseline to have moved from ⇒ silent (never a nag on an unknown)
        compared = rows[-2 * window:]
        older, recent = compared[:window], compared[window:]
        scope = _median([n for n, _v in compared])
        for key in percentiles:
            base = _median([v[key] for _n, v in older])
            now = _median([v[key] for _n, v in recent])
            delta = now - base
            if base > 0 and delta >= floor_ms and now >= base * (1.0 + ratio):
                signals.append(
                    f"[report-only] duration creep: {key} of the ~{scope}-file verify is "
                    f"{now/1000.0:.1f}s, +{int(round(100.0 * delta / base))}% over the median of the "
                    f"previous {window} scope-comparable lands ({base/1000.0:.1f}s) — the T-11124 "
                    f"per-file series, SPEC-0132 Rule 7. The DELTA, never the level: this names no "
                    f"budget and gates nothing. Which FILE moved is the sibling reading — "
                    f"`bin/yitc-v2 debt` (SPEC-0119 rule 19).")
    return signals


def _payload_partial_layers(payload) -> "frozenset | None":
    """T-13911 (SPEC-1030 rule 6) — the layers ONE projected land ran IN PART (`_partial_layers`,
    put there by `_scaling_series_projection`). An empty set when the key is absent: the land ran
    no layer in part. None when the key is present and is not a list of non-empty strings — which
    layers ran in part is then unknown, and the caller observes NO layer on that land (the two
    readings' own fail direction: silence). PURE."""
    if "_partial_layers" not in payload:
        return frozenset()
    names = payload["_partial_layers"]
    if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
        return None
    return frozenset(names)


def _verify_layer_duration_drift_signals(series: "list", *, window: int = _VERIFY_LAYER_DRIFT_WINDOW,
                                         growth_ratio: float = _VERIFY_LAYER_DRIFT_GROWTH_RATIO,
                                         min_growth_ms: int = _VERIFY_LAYER_DRIFT_MIN_GROWTH_MS) -> "list":
    """T-13522 (SPEC-0132 Rule 7, second subject) — PURE, REPORT-ONLY: has a declared CONSUMER verify
    layer's own duration crept upward across lands? The sibling above reads the kernel sweep's
    per-file walls; a project whose verify is its declared layers (SPEC-0152 rule 16) has none of
    those, and its layer durations — recorded on every land since T-11200 — had no reader for growth
    (measured on a consumer: one layer went 18 s → 278 s over 35 lands unnoticed). Same input as the
    sibling (the projected `land_completed` payloads; ordered HERE by each row's own `ts`, so the
    caller's order is not relied on), same contract: it reads one in-memory list, writes nothing,
    emits nothing and moves no exit code.

    A LAYER-RECORDING LAND is a payload whose `verify_metrics` carries a `per_layer_durations` key at
    all — whatever is under it. AN OBSERVATION is narrower: one `layers[]` entry of such a land with a
    positive int `duration_ms`, whose name appears ONCE in that land, on a land that also carries an
    int `layer_worker_budget`. The two are kept apart on purpose (audit-post finding, T-13522): which
    land is NEWEST is decided over the layer-recording lands, and what may be REPORTED is decided
    over that newest land's observations. Deciding "newest" over observations instead lets a newest
    land whose record is unreadable or ambiguous fall out of sight, and the reading then re-reports
    an older land's creep as if it were current.

    ONLY A LAYER THE NEWEST LAYER-RECORDING LAND OBSERVED is judged. So a layer removed from the
    carrier is not re-reported from its last rows at every later land, and a newest land that
    recorded layers without a usable budget, or recorded this layer twice or with no usable
    duration, says nothing about it.

    THE BUDGET COHORT — SPEC-0208 rule 5 applied to a reading. The worker budget a layer was handed is
    part of the regime its duration was measured under, so durations under two budgets are not one
    series. A layer is judged ONLY over its observations that share the newest land's budget; rows
    under any other budget are never compared against them.

    A PARTIAL RUN IS NOT AN OBSERVATION (T-13911, SPEC-1030 rule 6). A land that ran a layer IN PART
    (`_partial_layers` of the projection) recorded the duration of a part of it: that land observes
    the layer in no window, and as the newest land it leaves the layer silent.

    THE DELTA, NEVER THE LEVEL, and THE FAIL DIRECTION IS SILENCE — both inherited from the sibling,
    unchanged: no duration is judged, only movement of the recent-window median over the older-window
    median, past a relative bar AND an absolute floor; fewer than two windows of history says
    nothing. Silence also covers ORDER: a layer-recording land whose `ts` (`_row_ts`, put there by
    `_scaling_series_projection`) is missing or not the journal's canonical UTC stamp cannot be
    placed, so which land is newest is unknown and the whole reading says nothing; and lands tied on
    the newest `ts` report only what every one of them observed, under one budget.

    Each line CITES THE ROWS IT READ — the first and last `events.jsonl#ts=` of the older window and
    of the recent window. The windows are contiguous in the cohort, so the four locators bound them.

    Returns a list of `str`, one per drifting layer, in layer-name order. PURE: nothing is mutated."""
    def _median(values: "list") -> int:
        ordered = sorted(values)
        n = len(ordered)
        return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) // 2

    try:
        window = max(1, int(window))
        ratio = float(growth_ratio)
        floor_ms = int(min_growth_ms)
    except (TypeError, ValueError):
        return []

    observations: dict = {}        # layer name -> [(ts, budget, duration_ms), ...]
    newest_ts = ""                 # the greatest ts among the layer-recording lands
    newest_observed: set = set()   # the layers EVERY land at that ts observed
    newest_budgets: set = set()    # the budgets of the lands at that ts (None = no usable budget)
    for payload in series or []:
        if not isinstance(payload, dict):
            continue
        metrics = payload.get("verify_metrics")
        if not isinstance(metrics, dict) or "per_layer_durations" not in metrics:
            continue          # not a layer-recording land ⇒ it says nothing about layers either way
        ts = payload.get("_row_ts")
        if not isinstance(ts, str) or not _LAYER_DRIFT_TS_RE.match(ts):
            return []         # a layer-recording land that cannot be placed ⇒ "newest" is unknown
        budget = metrics.get("layer_worker_budget")
        if isinstance(budget, bool) or not isinstance(budget, int):
            budget = None
        record = metrics.get("per_layer_durations")
        rows = record.get("layers") if isinstance(record, dict) else None
        seen: dict = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name, ms = row.get("layer"), row.get("duration_ms")
            if not isinstance(name, str) or not name:
                continue
            ok = not isinstance(ms, bool) and isinstance(ms, int) and ms > 0
            seen[name] = None if name in seen or not ok else ms   # twice in one land ⇒ ambiguous
        in_part = _payload_partial_layers(payload)
        observed = ({name: ms for name, ms in seen.items() if ms is not None and name not in in_part}
                    if budget is not None and in_part is not None else {})
        if ts > newest_ts:
            newest_ts, newest_observed, newest_budgets = ts, set(observed), {budget}
        elif ts == newest_ts:
            newest_observed &= set(observed)
            newest_budgets.add(budget)
        for name, ms in observed.items():
            observations.setdefault(name, []).append((ts, budget, ms))

    if len(newest_budgets) != 1 or None in newest_budgets:
        return []             # no layer-recording land, or the newest one's regime is not one budget
    budget = next(iter(newest_budgets))

    signals = []
    for name in sorted(newest_observed):
        cohort = sorted((ts, ms) for ts, b, ms in observations[name] if b == budget)
        if len(cohort) < 2 * window:
            continue          # no baseline under this budget to have moved from ⇒ silent
        compared = cohort[-2 * window:]
        older, recent = compared[:window], compared[window:]
        base = _median([ms for _ts, ms in older])
        now = _median([ms for _ts, ms in recent])
        delta = now - base
        if base > 0 and delta >= floor_ms and now >= base * (1.0 + ratio):
            signals.append(
                f"[report-only] layer duration creep: verify layer `{name}` is {now/1000.0:.1f}s, "
                f"+{int(round(100.0 * delta / base))}% over the median of its previous {window} lands "
                f"under the same worker budget ({budget}) ({base/1000.0:.1f}s) — rows "
                f"events.jsonl#ts={older[0][0]} .. events.jsonl#ts={older[-1][0]} against "
                f"events.jsonl#ts={recent[0][0]} .. events.jsonl#ts={recent[-1][0]}; SPEC-0132 Rule 7. "
                f"The DELTA, never the level: this names no duration limit and gates nothing.")
    return signals


def _layer_slowest_unit(row) -> "list | None":
    """T-13645 — `[name, duration_ms]` of the slowest SPEC-1006 unit on ONE guard layer row (its
    `adapter.units[]`, each `{file, project?, duration_ms}`), or None when the row carries no usable
    unit. A unit with no positive int `duration_ms` or no `file` is skipped; ties go to the name
    that sorts first, so the answer does not depend on the report's order. PURE."""
    adapter = row.get("adapter") if isinstance(row, dict) else None
    units = adapter.get("units") if isinstance(adapter, dict) else None
    best = None
    for unit in units if isinstance(units, list) else []:
        if not isinstance(unit, dict):
            continue
        name, ms = unit.get("file"), unit.get("duration_ms")
        if not isinstance(name, str) or not name or isinstance(ms, bool) or not isinstance(ms, int) or ms <= 0:
            continue
        project = unit.get("project")
        if isinstance(project, str) and project:
            name = f"{project}:{name}"
        if best is None or ms > best[1] or (ms == best[1] and name < best[0]):
            best = [name, ms]
    return best


def _verify_layer_duration_step_signals(series: "list", *, current=None,
                                        window: int = _VERIFY_LAYER_DRIFT_WINDOW,
                                        growth_ratio: float = _VERIFY_LAYER_DRIFT_GROWTH_RATIO,
                                        min_growth_ms: int = _VERIFY_LAYER_DRIFT_MIN_GROWTH_MS) -> "list":
    """T-13645 (SPEC-0132 Rule 7, the layer subject's STEP reading) — PURE, REPORT-ONLY: did ONE
    observation of a declared consumer verify layer jump against that layer's own recent past? The
    creep sibling above compares two 10-land medians, so a one-card jump (150-170 s -> 364 s) is
    silent at the land that caused it and speaks about six lands later, on another card. This reads
    the NEWEST SINGLE observation against the median of the layer's previous `window` observations
    under the same worker budget, with the creep reading's two bars unchanged (the relative 25% and
    the absolute 5 s floor — the same constants, not new ones).

    THE OBSERVATION. `current=None` (the land tail): the newest layer-recording land of `series` —
    decided, as in the sibling, over the lands that recorded layers at all, so an unreadable newest
    record silences the reading instead of falling out of sight — and the baseline is the lands
    strictly older than it. `current={"budget": int, "layers": [guard rows]}` (the Stage-6 run, which
    is not a land): the run's own rows, and every land in `series` is baseline. Either way an
    observation is a layer named ONCE with a positive int `duration_ms`, under an int budget.
    A PARTIAL RUN IS NOT ONE (T-13911, SPEC-1030 rule 6): a layer a land ran IN PART
    (`_partial_layers`) is not observed on that land — in no baseline, and not as the newest
    observation — and a Stage-6 row that is a partial run (`_layer_row_is_partial_run`) is no
    observation of that run. So a full run after partial ones is never measured against them.

    THE BASELINE is that layer's last `window` observations under the observation's budget (SPEC-0208
    rule 5: rows under another budget are another series). Fewer than `window` ⇒ silent, so a budget
    change is silent until the new budget has its own history.

    HOST LOAD IS NOT A STEP. When two or more layers had a baseline and EVERY one of them moved past
    the RELATIVE bar, the whole verify moved together — a slow host, not a layer — and nothing is
    reported. Togetherness is judged on the relative bar alone: a short layer that doubled is still
    under the absolute floor, and must still count as having moved. One compared layer cannot tell
    the two apart, and is reported.

    THE FAIL DIRECTION IS SILENCE, as in the sibling: a layer-recording land whose `_row_ts` is not
    the journal's canonical stamp, two lands tied on the newest stamp (at either seam), a non-int budget, malformed
    rows — each yields nothing. On the land tail the step is reported only while its land is the
    NEWEST land of any kind: a later land that ran no layer does not re-print an earlier land's step
    (the creep reading, a trend, keeps speaking there). The line cites the first and last baseline row by locator and, when
    the observation carries SPEC-1006 unit rows (`_layer_slowest_unit`; on a land, the projection's
    `_slowest_units`), names the slowest unit.

    Returns a list of `str`, one per stepped layer, in layer-name order. PURE: nothing is mutated."""
    def _median(values: "list") -> int:
        ordered = sorted(values)
        n = len(ordered)
        return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) // 2

    def _observed(rows) -> dict:
        seen: dict = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name, ms = row.get("layer"), row.get("duration_ms")
            if not isinstance(name, str) or not name:
                continue
            ok = not isinstance(ms, bool) and isinstance(ms, int) and ms > 0
            seen[name] = None if name in seen or not ok else ms   # twice in one record ⇒ ambiguous
        return {name: ms for name, ms in seen.items() if ms is not None}

    def _budget(value):
        return None if isinstance(value, bool) or not isinstance(value, int) else value

    try:
        window = max(1, int(window))
        ratio = float(growth_ratio)
        floor_ms = int(min_growth_ms)
    except (TypeError, ValueError):
        return []

    lands = []                     # (ts, budget, {layer: ms}, {layer: [unit, ms]})
    newest_any = ""                # the newest placeable land of ANY kind (the land tail's own land)
    for payload in series or []:
        if not isinstance(payload, dict):
            continue
        any_ts = payload.get("_row_ts")
        if isinstance(any_ts, str) and _LAYER_DRIFT_TS_RE.match(any_ts) and any_ts > newest_any:
            newest_any = any_ts
        metrics = payload.get("verify_metrics")
        if not isinstance(metrics, dict) or "per_layer_durations" not in metrics:
            continue          # not a layer-recording land ⇒ it says nothing about layers either way
        ts = payload.get("_row_ts")
        if not isinstance(ts, str) or not _LAYER_DRIFT_TS_RE.match(ts):
            return []         # a layer-recording land that cannot be placed ⇒ the order is unknown
        record = metrics.get("per_layer_durations")
        budget = _budget(metrics.get("layer_worker_budget"))
        observed = _observed(record.get("layers") if isinstance(record, dict) else None)
        in_part = _payload_partial_layers(payload)
        observed = ({name: ms for name, ms in observed.items() if name not in in_part}
                    if in_part is not None else {})
        units = payload.get("_slowest_units")
        lands.append((ts, budget, observed if budget is not None else {},
                      units if isinstance(units, dict) else {}))
    lands.sort(key=lambda land: land[0])
    if len(lands) > 1 and lands[-1][0] == lands[-2][0]:
        return []             # two lands tied on the newest stamp: which is newest is unknown, at both seams

    if current is None:
        if not lands:
            return []         # no layer-recording land
        if lands[-1][0] < newest_any:
            return []         # a later land ran no layer: the step belongs to an earlier land's tail
        ts_now, budget, now_obs, now_units = lands[-1]
        baseline_lands = lands[:-1]
        where = f"on the newest land (events.jsonl#ts={ts_now})"
    else:
        if not isinstance(current, dict):
            return []
        budget = _budget(current.get("budget"))
        rows = current.get("layers")
        # T-13911: a name is read only when it is a string — a partial row that names no layer
        # (as `_observed` reads a name) names none here, and nothing unhashable reaches the set.
        in_part = {row["layer"] for row in (rows if isinstance(rows, list) else [])
                   if _layer_row_is_partial_run(row) and isinstance(row.get("layer"), str)}
        now_obs = {name: ms for name, ms in _observed(rows).items() if name not in in_part}
        now_units = {}
        for row in rows if isinstance(rows, list) else []:
            unit = _layer_slowest_unit(row)
            if unit is not None and isinstance(row.get("layer"), str) and row["layer"] in now_obs:
                now_units[row["layer"]] = unit
        baseline_lands = lands
        where = "on this run"
    if budget is None or not now_obs:
        return []

    compared, moved, crossed = 0, 0, []
    for name in sorted(now_obs):
        cohort = [(ts, obs[name]) for ts, b, obs, _u in baseline_lands if b == budget and name in obs]
        if len(cohort) < window:
            continue          # no baseline under this budget ⇒ silent
        base_rows = cohort[-window:]
        base = _median([ms for _ts, ms in base_rows])
        now = now_obs[name]
        compared += 1
        delta = now - base
        if base > 0 and now >= base * (1.0 + ratio):
            moved += 1        # past the RELATIVE bar — what "moved together" is judged on
        if base > 0 and delta >= floor_ms and now >= base * (1.0 + ratio):
            crossed.append((name, now, base, delta, base_rows[0][0], base_rows[-1][0]))
    if compared >= 2 and moved == compared:
        return []             # every compared layer moved together ⇒ host load, not a layer step

    signals = []
    for name, now, base, delta, first_ts, last_ts in crossed:
        unit = now_units.get(name)
        unit_text = ""
        if (isinstance(unit, list) and len(unit) == 2 and isinstance(unit[0], str)
                and isinstance(unit[1], int) and not isinstance(unit[1], bool)):
            unit_text = f"; slowest unit `{unit[0]}` ({unit[1]/1000.0:.1f}s)"
        signals.append(
            f"[report-only] layer duration step: verify layer `{name}` took {now/1000.0:.1f}s {where}, "
            f"+{int(round(100.0 * delta / base))}% over the median of its previous {window} lands under "
            f"the same worker budget ({budget}) ({base/1000.0:.1f}s) — rows "
            f"events.jsonl#ts={first_ts} .. events.jsonl#ts={last_ts}{unit_text}; SPEC-0132 Rule 7. "
            f"One observation against its own past, never a level: this names no duration limit and "
            f"gates nothing.")
    return signals


# T-14243 (SPEC-0065 §Bound) — a CREDITED land ran no verify of its own: its `verify_duration_ms` is the
# land's ~20 s prep, and the run it took its verdict from is the Stage-6 row its `stage6_credit` (or, per
# layer, `stage6_layer_credit`) names by `(task, ts)`. A reader of land verify data follows that pointer
# and counts the run ONCE, from that row. These three are the one home of the follow; the weekly readings
# (patterns/inspection-criteria-roster-*.md, lessons/*-report.md) import them rather than restate them.
def _stage6_rows_index(events) -> dict:
    """`{(task_id, ts): data}` over the `tests_passed` events in `events` — a credit is taken from a green
    run only (SPEC-0065 condition 3), so a `tests_failed` row, any other row, or one without a `str` task
    id and ts is never a target. A repeated key keeps its first row: it is one run."""
    out = {}
    for e in events or ():
        if not isinstance(e, dict) or e.get("type") != "tests_passed":
            continue
        key = (e.get("task_id"), e.get("ts"))
        if isinstance(key[0], str) and isinstance(key[1], str) and isinstance(e.get("data"), dict):
            out.setdefault(key, e["data"])
    return out


def _stage6_credited_row(d, index):
    """The Stage-6 row (its `data`) a land's credit names, or None — no credit, a malformed pointer, or a
    row `index` does not hold. A whole-land `stage6_credit` is read first, then the per-layer one."""
    if not isinstance(d, dict) or not isinstance(index, dict):
        return None
    for key in ("stage6_credit", "stage6_layer_credit"):
        c = d.get(key)
        if isinstance(c, dict) and isinstance(c.get("task"), str) and isinstance(c.get("ts"), str):
            return index.get((c["task"], c["ts"]))
    return None


def _stage6_run_wall_ms(s6):
    """A Stage-6 run's wall: its `verify_metrics.verify_wall_ms`, else the row's `duration_ms`; None when
    neither is an int (a bool is not one)."""
    if not isinstance(s6, dict):
        return None
    vm = s6.get("verify_metrics")
    w = vm.get("verify_wall_ms") if isinstance(vm, dict) else None
    if not isinstance(w, int) or isinstance(w, bool):
        w = s6.get("duration_ms")
    return w if isinstance(w, int) and not isinstance(w, bool) else None


# T-13138 (X-1687) — THE FIELDS the two scaling-signal folds below read from each land's `data`, and
# nothing else. The land tail keeps only this projection of every ok `land_completed` row: measured on
# the kernel checkout, the full `data` of its 7,798 ok land rows is ~30 MB of JSON (~150 MB parsed —
# `selection_ran_tests` alone is 13.6 MB) while these fields are 1.6 MB. A signal that reads a NEW field
# must add it here; `tests/test_t13138_land_journal_memory.py` pins projected == full on every field.
_SCALING_METRICS_FIELDS = ("verify_wall_ms", "queue_wait_ms", "serial_lane_ms", "serial_lane_files",
                           "layer_worker_budget")   # T-13522: the per-layer creep reading's cohort key
_SCALING_PER_FILE_FIELDS = ("wall_ms_pct", "sample_count")
_SCALING_PER_LAYER_FIELDS = ("layers",)             # T-13522: `{layer, duration_ms}` per executed layer


def _scaling_series_projection(d, ts=None):
    """`d` (one land's `data`) reduced to what `_verify_scaling_signals` and its two duration-drift
    siblings read — the same values, the same key presence, and a non-dict left AS IS so every
    `isinstance` test in the folds takes the same branch it took on the full row (T-13138).

    `ts` (T-13522) is the ROW's own timestamp — it lives on the event, not in `data`, so the caller
    passes it — kept as `_row_ts` for the one fold that cites the rows it read. Omitted or not a `str`,
    nothing is added."""
    if not isinstance(d, dict):
        return d
    out = {}
    if isinstance(ts, str) and ts:
        out["_row_ts"] = ts
    if "verify_duration_ms" in d:
        out["verify_duration_ms"] = d["verify_duration_ms"]
    if "stage6_credit" in d:   # T-14243: a credited land's own wall is never read (`_verify_scaling_signals`)
        out["stage6_credit"] = d["stage6_credit"]
    # T-13645: each layer's slowest SPEC-1006 unit, the only part of the land's layer rows the step
    # reading names — `{layer: [unit, ms]}`, ABSENT when no row carries a usable unit (so a land with
    # no adapter-backed layer projects exactly as before). A layer named twice is left out.
    rows = d.get("consumer_verify_layers")
    if isinstance(rows, list):
        names = [r.get("layer") for r in rows if isinstance(r, dict)]
        slowest = {}
        for r in rows:
            unit = _layer_slowest_unit(r)
            if unit is not None and isinstance(r.get("layer"), str) and names.count(r["layer"]) == 1:
                slowest[r["layer"]] = unit
        if slowest:
            out["_slowest_units"] = slowest
        # T-13911 (SPEC-1030 rule 6): the layers this land ran IN PART — the names the two layer
        # duration readings leave out of every series. ABSENT when the land ran none in part, so a
        # land without a partial run projects exactly as before.
        in_part = sorted({r["layer"] for r in rows if _layer_row_is_partial_run(r)
                          and isinstance(r.get("layer"), str) and r["layer"]})
        if in_part:
            out["_partial_layers"] = in_part
    if "verify_metrics" in d:
        vm = d["verify_metrics"]
        if isinstance(vm, dict):
            kept = {k: vm[k] for k in _SCALING_METRICS_FIELDS if k in vm}
            if "per_file_durations" in vm:
                pf = vm["per_file_durations"]
                kept["per_file_durations"] = ({k: pf[k] for k in _SCALING_PER_FILE_FIELDS if k in pf}
                                              if isinstance(pf, dict) else pf)
            if "per_layer_durations" in vm:
                pl = vm["per_layer_durations"]
                kept["per_layer_durations"] = ({k: pl[k] for k in _SCALING_PER_LAYER_FIELDS if k in pl}
                                               if isinstance(pl, dict) else pl)
            vm = kept
        out["verify_metrics"] = vm
    return out


def _verify_scaling_signals(series: "list", *, stage6_rows=None, _verify_duration_drift_signals, _VERIFY_QUEUE_BLOCK_FRACTION=_VERIFY_QUEUE_BLOCK_FRACTION, _VERIFY_TIERC_MEDIAN_MS=_VERIFY_TIERC_MEDIAN_MS, _VERIFY_TIERC_P95_MS=_VERIFY_TIERC_P95_MS, _VERIFY_TIERC_QUEUE_BLOCK_RATIO=_VERIFY_TIERC_QUEUE_BLOCK_RATIO) -> "list":
    """T-10071 (SPEC-0132 Rules 3-4) — PURE, REPORT-ONLY scaling signals computed from a series of
    `land_completed` `data` payloads (ok lands; order-independent). Returns a list of human-readable
    signal lines, EMPTY when nothing crosses a threshold (suppressed-when-clean). It NEVER performs an
    action or triggers a build (CHARTER §6 fence) — it returns strings and has no side effects; the
    OWNER/plan decides whether to act on a fired signal (SPEC-0132 Rules 1/3/4).

    Rule 4 (Tier-C deferral triggers — WHEN to build affected-test selection): median land verify
    > 5 min, OR p95 > 12 min, OR verifier queueing blocks > 25% of lands. (SPEC-0132's "for 7
    consecutive days" day-window is a future refinement — here the ratio is computed over the SUPPLIED
    series as a report-only proxy, never an auto-build.)
    Rule 3 (watch-points — targeted-fix triggers): the serial resource-lane watch-point (> 10% of verify
    wall OR > 25 files). The pinned-cache hit-rate watch-point was RETIRED by T-11222 — see the note at
    its former site below for the measured reason. (The timing-flakiness watch-point needs fields not yet
    captured — omitted, not fabricated, until its capture site exists — the SPEC-0132 §2 MAY-follow set.)

    Rule 7 (T-11127) — the duration-CREEP reading, appended from `_verify_duration_drift_signals`. Read
    the two kinds of line here as what they are, because they are NOT the same kind of judgement and
    collapsing them would be a real error. Rules 3-4 above are LEVEL crossovers: they compare a measured
    value against a decreed threshold and say "this is now big enough to act on". Rule 7 decrees NO level
    at all — it names no budget, no target and no duration a suite may not exceed (T-11124 scoped out
    judging any duration, and this function did not reopen that). It reports only that the distribution
    MOVED, against its own recent past, among lands that ran a comparably-sized suite. A future editor
    adding a duration threshold here should know it belongs to neither rule.

    Rule 7 has a SECOND subject (T-13522): a declared consumer verify LAYER's own duration, read by
    `_verify_layer_duration_drift_signals` on the same terms — a delta, among lands under one worker
    budget, citing its rows. It orders by each payload's `_row_ts`, so this function stays
    order-independent.

    `stage6_rows` (T-14243) — the window's `tests_passed` / `tests_failed` events. A land carrying a
    `stage6_credit` ran no verify: its own `verify_duration_ms` is NEVER read as a wall, and its wall is the
    Stage-6 run it names (`_stage6_credited_row`), counted once; with no such row it has no wall. A Stage-6
    row no land credits is not a land and is not counted here."""
    s6_index = _stage6_rows_index(stage6_rows)

    def _wall(d):
        if isinstance(d.get("stage6_credit"), dict):
            return _stage6_run_wall_ms(_stage6_credited_row(d, s6_index))
        vm = d.get("verify_metrics")
        w = vm.get("verify_wall_ms") if isinstance(vm, dict) else None
        if not isinstance(w, int):
            w = d.get("verify_duration_ms")   # fallback to the top-level field (pre-verify_metrics rows)
        return w if isinstance(w, int) else None

    walls = sorted(w for d in series for w in [_wall(d)] if w is not None)
    signals = []
    if walls:
        n = len(walls)
        median = walls[n // 2] if n % 2 else (walls[n // 2 - 1] + walls[n // 2]) // 2
        p95 = walls[min(n - 1, max(0, -(-95 * n // 100) - 1))]   # nearest-rank p95
        if median > _VERIFY_TIERC_MEDIAN_MS:
            signals.append(f"[report-only] Tier-C: median land verify {median/60000:.1f} min > 5 min "
                           f"(n={n}) — SPEC-0132 Rule 4 crossover: consider building affected-test selection.")
        if p95 > _VERIFY_TIERC_P95_MS:
            signals.append(f"[report-only] Tier-C: p95 land verify {p95/60000:.1f} min > 12 min "
                           f"(n={n}) — SPEC-0132 Rule 4 crossover: consider building affected-test selection.")

    # Queue-block ratio (Rule 4): a land is queue-blocked iff its queue wait dominates ≥25% of its wall.
    queued = 0
    q_total = 0
    for d in series:
        vm = d.get("verify_metrics")
        if not isinstance(vm, dict):
            continue
        qw, w = vm.get("queue_wait_ms"), _wall(d)
        if isinstance(qw, int) and isinstance(w, int) and w > 0:
            q_total += 1
            if qw >= _VERIFY_QUEUE_BLOCK_FRACTION * w:
                queued += 1
    if q_total and (queued / q_total) > _VERIFY_TIERC_QUEUE_BLOCK_RATIO:
        signals.append(f"[report-only] Tier-C: verifier queueing blocks {queued}/{q_total} lands "
                       f"({100*queued/q_total:.0f}% > 25%) — SPEC-0132 Rule 4 crossover (report-only proxy).")

    # Rule 3 watch-point: a serial resource-lane exceeds 10% of verify wall time OR 25 files → refactor
    # to unique-resource helpers. Evaluated PER-LAND, guarded on the (currently DEFERRED) serial-lane
    # fields being present in verify_metrics — INERT until a real capture site populates them
    # (`serial_lane_ms` / `serial_lane_files`), then it fires without any further wiring (SPEC-0132 §2
    # MAY-follow). Reported on the most recent land that carries the data.
    for d in reversed(series):
        vm = d.get("verify_metrics")
        if not isinstance(vm, dict):
            continue
        sl_ms, sl_files, w = vm.get("serial_lane_ms"), vm.get("serial_lane_files"), _wall(d)
        over_wall = isinstance(sl_ms, int) and isinstance(w, int) and w > 0 and sl_ms > 0.10 * w
        over_files = isinstance(sl_files, int) and sl_files > 25
        if over_wall or over_files:
            _detail = (f"{100*sl_ms/w:.0f}% of verify wall" if over_wall else f"{sl_files} files")
            signals.append(f"[report-only] watch-point: a serial resource-lane spans {_detail} "
                           f"(> 10% wall OR 25 files) — SPEC-0132 Rule 3: refactor to unique-resource helpers.")
            break

    # Rule 3 pinned-cache HIT-RATE watch-point: RETIRED by T-11222 (X-0968), deleted rather than
    # re-tuned, because no threshold is reachable — the expectation was wrong, not the number.
    #
    # It compared the measured hit-rate against an 80% floor. Measured kernel-side 2026-08-17
    # (events.jsonl#ts=2026-08-17T13:58:43Z): over 7032 `land_completed` rows, 1390 ran the pinned leg,
    # 0 of them recorded `pinned_cache_hit`, and NONE were layout-excused — so all 1390 were clean
    # GREENs that ran `_pinned_cache_put`, and `.git/yitc-pinned-verify-cache` held 1135 markers, ALL
    # DISTINCT. 1135 writes, zero hits: no key has ever repeated. (This also refutes the earlier
    # reading, carried in T-11182's own commit body, that no GREEN pinned verdict was ever reached.)
    #
    # TWO INDEPENDENT SUFFICIENT CAUSES, either alone fatal to any floor:
    #   1. The SUBJECT term is `HEAD^{tree}`, and the cache is consulted ONLY when `_verify_path_touch`
    #      is true — i.e. only when this land's diff touches the very `bin`/`tests` surfaces that
    #      guarantee its tree differs from every earlier land's. The condition that OPENS the cache is
    #      the condition that BUSTS it. A retry is the only unchanged-tree case, and `land` runs
    #      update-from-main before verify, so a retry's tree (and merged base) moves too.
    #   2. The `_running_engine_code_hash()` term invalidates GLOBALLY, for every consumer at once.
    #      438 commits touched `bin/**/*.py` or `bin/yitc-v2` in the 7 days to 2026-08-17 — a full-cache
    #      kill roughly every 23 minutes, far shorter than the interval between two lands of one project.
    #
    # Nothing here is a defect to fix: a MISS is fail-safe (it re-runs), so the cache costs a few git
    # calls and never risks a stale green. What is retired is the EXPECTATION of a payoff, and with it a
    # report-only line that fired at every seam saying so. `land_completed.pinned_cache_hit` is
    # DELIBERATELY KEPT as the observable, so anyone can re-measure this rather than trust the comment.

    # Rule 7 (T-11127): the duration-CREEP lines, computed by the pure sibling below. Appended LAST so
    # the level-crossover lines above keep their existing order byte-for-byte, and concatenated rather
    # than interleaved so a reader can tell the two kinds apart by position as well as by wording.
    signals.extend(_verify_duration_drift_signals(series))
    # Rule 7, second subject (T-13522): the per-LAYER creep lines, after the per-file ones so every
    # earlier line keeps its position. Called directly — it was born in this leaf, not extracted from
    # the host, so it has no host residue to arrive through.
    signals.extend(_verify_layer_duration_drift_signals(series))
    # Rule 7, the layer subject's STEP reading (T-13645): the newest land's single observation against
    # its own past, LAST so every earlier line keeps its position.
    signals.extend(_verify_layer_duration_step_signals(series))
    return signals


def _pinned_recovery_hint(*, REBASELINE_KINDS) -> str:
    return (
            "\n\nRECOVERY (only if this pinned check is obsolete, NOT a real regression): if you "
            "deliberately revised the old behaviour OR a new test legitimately needs a new harness/"
            "setup the pinned last-green tree lacked, re-land with "
            "`land --rebaseline --rebaseline-kind <" + "|".join(REBASELINE_KINDS) + "> "
            "--rebaseline-reason '<why>'` — it waives ONLY the superseded pinned "
            "check and requires a fresh GREEN/YELLOW audit-post over the current tree (SPEC-0077 §3)."
            # T-10898: the hint names the KIND because the flag is REQUIRED with `--rebaseline` — a
            # recovery line that prints a command the very next preflight refuses is not a recovery
            # (the X-0683/X-0685 class one layer down: a sanctioned path an operator cannot type).
            " Declare `broken` when the pinned failure is REAL here (a superseded old-behaviour "
            "assertion — the ordinary case for this hint), or `unrunnable-here` when the check is "
            "HEALTHY but cannot RUN in this checkout at all. The kind is RECORDED, never a "
            "permission: it widens nothing, and neither value changes what you must satisfy below."
            # T-10819 (X-0658) — the text is reconciled WITH SPEC-0121, not against it. The hint above
            # read as an unconditional self-serve recovery, so a Worker standing under
            # default-under-uncertainty=STOP saw the print say its escalation was unnecessary. The
            # SPEC-0121 default is the side held CORRECT; this names the AUTHORITY the recovery
            # actually requires and the escalation that is the right outcome without it. Message-only
            # — the gates are unchanged (SPEC-0077 §3a stays the canonical authority home).
            "\nAUTHORITY (SPEC-0077 §3a A-prime): the owner ACKs, OR a dispatched Worker SELF-CLEARS "
            "— the latter ONLY when candidate verify is GREEN, a FRESH audit-post for this branch's "
            "task is GREEN, `--no-tests` is absent, the `>=30-char` reason is recorded, AND that "
            "reason is MECHANICALLY TIED to the EXACT assertion(s) in the FAILING ASSERTION(S) block "
            "above plus the declared behaviour/harness change that obsoletes them. Free-form 'this "
            "looks stale' is NOT sufficient.\n"
            "IF YOU CANNOT MAKE THAT TIE: ESCALATE — `blocked-on-land <task> <reason>`, worktree "
            "intact. That escalation is the CORRECT outcome, not a failure: SPEC-0121's "
            "default-under-uncertainty is STOP, and this hint never overrides it."
    )


# ───────── T-13606 — adapter-backed verify layers: the declaration, the report profiles and the
# REPORT-ONLY pass (SPEC-1006 rules 1-4; the contract is `proposed` until its activation card) ─────────
#
# A declared `verify.layers[]` entry (SPEC-0152 rule 16) MAY carry `adapter:` — three project-owned
# commands that let the kernel see the layer's tests one by one. THIS SLICE IS REPORT-ONLY: the
# layer's full `command:` runs and its exit code decides exactly as before; afterwards the adapter's
# `list` and `run` are invoked inside the same prepared worktree and what they report is recorded
# as ONE additive key `adapter` on that layer's outcome row. Nothing here changes `bad`, an outcome
# or an exit code. The cards that follow EXTEND this interface (the per-unit re-run, the shadow
# selection, the would-be credit); they never redefine the three things defined here:
#   1. the DECLARATION reader `_declared_layer_adapters` — the one definition of the key set;
#   2. the kernel<->adapter PROTOCOL — a manifest file named by `YITC_VERIFY_ADAPTER_MANIFEST`;
#   3. the ROW — `_layer_adapter_report_pass`'s record, built from `_classify_adapter_report`.
#
# THE PROTOCOL. Before each adapter invocation the kernel writes a fresh directory holding
# `manifest.json` and publishes its path in the environment variable above. The manifest is
#   {schema: 1, run_id, layer, action: "list" | "run", profile, project, units, output, report,
#    second_report}
# `list` writes its answer to `output` as JSON `{schema: 1, units: [{file, project?, report_id?,
# group?, cases?}], errors: []}` — `file` repo-relative, `project` the runner project ("" when the
# runner has one), `report_id` the name the runner's OWN report gives that unit when it is not the
# repo-relative path (a runner rooted in a sub-directory, a pytest module path), `group` a label
# shared by the units of one indivisible group. `run` executes exactly `units` (null = no inventory:
# everything the layer runs) and makes the runner write its native JUnit report to `report` and,
# where the profile names one, its second report to `second_report`.
#
# T-13610 EXTENDS the protocol, additively (SPEC-1006 rules 3, 8): `list`'s answer MAY carry
# `versions` — `{name: version}` strings, the resolved versions of the runner and of any dependency
# tracker it uses, an input of the layer's recorded identity. A THIRD action, `related`, is invoked
# only on a layer declaring `selection: shadow`: its manifest carries `units` (the whole inventory)
# plus `base` (the kernel's comparison base) and `changed` (the kernel's changed paths), and it
# writes to `output` the JSON `{schema: 1, units: [{file, project?}], errors: []}` — the units the
# change reaches, enumerated WITHOUT executing a test body. The manifests of `list` and `run` are
# unchanged. T-13612 (rule 14) invokes `related` a second time on a layer declaring `credit:
# shadow` whose previous attempt failed — the same manifest, with `base` the previous attempt's
# recorded tree (or a commit over it) and `changed` the paths between that tree and the candidate's.
#
# T-13607 (SPEC-1006 rule 10) — ONE additive manifest key, present only on a re-run invocation:
# `isolated: true` asks `run` to execute the named units ONE AT A TIME (no file parallelism), so
# several failed units share one invocation and a layer's setup is paid once per attempt. A first
# attempt's manifest is byte-identical to the one above.
#
# T-13985 (SPEC-1033 rule 10) — ONE additive key on a re-run's UNIT entry: `cases`, the case ids the
# first attempt's report named failed for that unit (`_adapter_rerun_entities` says when). `run`
# executes only those cases of that file, or the whole file — the kernel reads either alike.
#
# T-14206 (SPEC-1046) — TWO additive keys on a `run` manifest's UNIT entry, first attempt and re-run
# alike: `median_ms` and `runs`, that unit's median duration and run count from the project's own
# journal inside the SPEC-0190 summary window (`_adapter_unit_medians`). A unit with no recorded
# duration carries neither. They are facts for the project's own split; the kernel divides nothing.
_VERIFY_ADAPTER_MANIFEST_ENV = "YITC_VERIFY_ADAPTER_MANIFEST"


def _adapter_unit_medians(root, *, floor=None) -> dict:
    """T-14206 (SPEC-1046) — per unit of the project's adapter-backed layers, `{median_ms, runs}` over
    the SPEC-0190 summary window, keyed `(layer, project, "unit" | "group", name)` as the
    verify-unit-cost lens keys a unit, read from the journal of the checkout at `root` (its
    `events.jsonl` and that journal's segments). The numbers ARE the lens's (`views._view_verify_unit_cost`:
    `median_ms` and `runs_in_window` of its unit row) — one derivation, nothing re-derived here; a
    unit whose row has no median is absent. The caller reads this ONCE per verify run, before any
    layer runs. Any fault answers {} — no unit carries the keys and the run is otherwise unchanged —
    and so does a summary window that cannot be read (never the whole history in its place).
    `floor` (ISO instant) moves the window's start; None, the production value, is the summary window."""
    try:
        from lib import events as _events
        from lib import task_card_io
        from lib import views
        floor = _events.summary_window_floor() if floor is None else floor
        since = task_card_io._parse_iso_utc(floor) if floor else None
        if since is None:
            return {}                    # no window to read inside: a whole-history figure is not recent

        def _rows(path, *, types=None):
            return journal_mod.segment_rows_since(path, floor, types=types)

        def _ev_dt(ts):
            return views._ev_dt(ts, _parse_iso_utc=task_card_io._parse_iso_utc)

        answer = views._view_verify_unit_cost(Path(root) / "events.jsonl", since, None, None, None,
                                              _iter_events=_rows, _ev_dt=_ev_dt)
        out: dict = {}
        for row in answer.get("units") or []:
            med, runs = row.get("median_ms"), row.get("runs_in_window")
            if not (isinstance(med, int) and isinstance(runs, int)) or isinstance(med, bool):
                continue
            kind = "group" if "group" in row else "unit"
            out[(row.get("layer"), row.get("project") or "", kind, row.get(kind))] = {
                "median_ms": med, "runs": runs}
        return out
    except Exception:                                      # noqa: BLE001 — no facts, never a refusal
        return {}


def _adapter_units_with_medians(layer: str, units, project, medians) -> "list | None":
    """T-14206 — `units` of one `run` invocation, each entry given its `median_ms` / `runs` from
    `medians` (`_adapter_unit_medians`) when the lens has a median for it; copies, so the caller's
    list is never touched. A unit in a declared group takes its group's numbers. No medians, or no
    unit list (`run` of everything), is returned as given."""
    if not medians or not isinstance(units, list):
        return units
    out = []
    for u in units:
        if not isinstance(u, dict):
            out.append(u)
            continue
        proj = str(u.get("project") or project or "")
        key = ((layer, proj, "group", u["group"]) if u.get("group")
               else (layer, proj, "unit", u.get("file")))
        got = medians.get(key)
        out.append({**u, **got} if got else u)
    return out
# The reason key each DECIDING mode is declared with (SPEC-1030 rule 1): required IFF its mode
# reads `deciding`, refused beside any other value of that mode.
_ADAPTER_REASON_KEYS = {"selection": "selection_deciding_reason", "credit": "credit_deciding_reason"}
_ADAPTER_KEYS = ("list", "related", "run", "report_profile", "sources", "required", "modelled",
                 "triggers", "selection", "credit", "rescue", *_ADAPTER_REASON_KEYS.values())
# The operating modes and their DEFAULT (first value). `deciding` is the mode in which the
# decision SPEC-1006 records ACTS; its admission contract is SPEC-1030.
_ADAPTER_MODES = {"selection": ("off", "shadow", "deciding"), "credit": ("off", "shadow", "deciding"),
                  "rescue": ("on", "off")}
# The versioned report profiles — how each runner's NATIVE report reads (SPEC-1006 rule 4). One
# entry per runner family; `vitest/1` covers Vitest 4 and 5 (their JUnit reports matched on every
# planted case of the trial). Per profile:
#   unit_from          where a record names its unit: the suite `name`, the suite `name` plus its
#                      `hostname` (the runner project), or a testcase `classname` prefix;
#   project_in_report  False = the report names no runner project, so `run` is invoked once PER
#                      project and the invocation supplies it;
#   case_error         how an `<error>` on a test case reads: the unit's own failure, or a
#                      collection / setup / teardown failure the runner marks APART (void);
#   file_named_case    True = a failing case NAMED BY ITS FILE is a file-level failure (void);
#   outside_suites     suite names that carry an error outside every unit (void);
#   second_report      the report written beside the JUnit one that shows what JUnit cannot — a
#                      native retry, and for Playwright a run-level error beside a test failure;
#   report_id          how a unit is named in the report when `list` gives no `report_id`: its
#                      repo-relative `file`, or that path as a dotted module (pytest's classname);
#   cases              False = a script-style suite: the verdict is the file's, no case rows;
#   retries_off        what the adapter's `run` must pass so every retry is the kernel's;
#   unrevealable       the void conditions this runner's reports cannot reveal. While a profile
#                      names any, no selection and no rescue may rest on its rows (rule 4 LIMIT).
#   related_diff       T-13610 (rule 3 iii) — the diff the runner's OWN `related` answers for:
#                      `kernel` = the adapter answers from the manifest's `changed` list, so it
#                      sees exactly the kernel's paths; `merge-base` = the runner diffs
#                      `<base>...HEAD` plus staged, unstaged and untracked files (Vitest);
#                      `worktree` = the working tree against `<base>` plus untracked files
#                      (Playwright). The kernel derives that set with git
#                      (`_adapter_change_facts`) and trusts no answer for a path outside it.
_ADAPTER_REPORT_PROFILES = {
    "vitest/1": {"unit_from": "suite", "project_in_report": False, "case_error": "unit",
                 "file_named_case": True, "outside_suites": ("vitest unhandled errors",),
                 "second_report": "vitest-json", "report_id": "file", "cases": True,
                 "retries_off": "--retry=0",
                 "unrevealable": (), "related_diff": "merge-base"},
    "playwright/1": {"unit_from": "suite+hostname", "project_in_report": True, "case_error": "unit",
                     "file_named_case": False, "outside_suites": (),
                     "second_report": "playwright-json", "report_id": "file", "cases": True,
                     "retries_off": "--retries=0",
                     "unrevealable": (), "related_diff": "worktree"},
    "pytest/1": {"unit_from": "classname", "project_in_report": False, "case_error": "apart",
                 "file_named_case": False, "outside_suites": (), "second_report": None,
                 "report_id": "dotted-module", "cases": True, "retries_off": "no rerun plugin",
                 "unrevealable": (), "related_diff": "kernel"},
    "script/1": {"unit_from": "suite", "project_in_report": False, "case_error": "unit",
                 "file_named_case": False, "outside_suites": (), "second_report": None,
                 "report_id": "file", "cases": False,
                 "retries_off": "one process per file, no retry loop",
                 "unrevealable": (), "related_diff": "kernel"},
}


def _adapter_shell_words(text: str, depth: int = 0) -> list:
    """The words of a shell command text, QUOTE-AWARE: single quotes, double quotes and backslash
    escapes are honoured, so `"other/my adapter.py"` is ONE word; unquoted whitespace and the shell
    operators `; | & ( ) < >` separate words. A word that itself holds whitespace or a quote may be
    a quoted COMMAND (`sh -c 'python3 tools/x.py'`), so it is read again as one (bounded depth) and
    its words are added beside it. An unbalanced quote ends at the end of the text. Pure."""
    words, cur, quote = [], None, None
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if quote == "'":
            if ch == "'":
                quote = None
            else:
                cur += ch
        elif quote == '"':
            if ch == '"':
                quote = None
            elif ch == "\\" and i + 1 < n and text[i + 1] in '"\\$`':
                i += 1
                cur += text[i]
            else:
                cur += ch
        elif ch == "\\" and i + 1 < n:
            i += 1
            cur = (cur or "") + text[i]
        elif ch in "'\"":
            quote, cur = ch, cur or ""
        elif ch in " \t\n;|&()<>":
            if cur is not None:
                words.append(cur)
                cur = None
        else:
            cur = (cur or "") + ch
        i += 1
    if cur is not None:
        words.append(cur)
    if depth < 3:
        for word in list(words):
            if re.search(r"[\s'\"]", word):
                words.extend(_adapter_shell_words(word, depth + 1))
    return words


def _adapter_command_repo_paths(command: str, repo_files, repo_dirs=None) -> list:
    """The repo files an adapter command NAMES — the decidable reading of «a command that invokes a
    tracked repo file» (SPEC-1006 rule 1).

    CANDIDATE WORDS are read off the command TEXT three ways and united, so the reading only ever
    widens: (1) its quote-aware words (`_adapter_shell_words` — a quoted name with a space is one
    word, a quoted command is read again); (2) each such word split on `=`, `:` and `,`
    (`--config=x.cfg`, `-v ./dir:/app`); (3) the text split on every space, operator, quote and
    brace (a path glued to anything else). Every word is then read TWICE: as spelled — a `$` may be
    a literal character of a file name (`'other/$literal.py'`) — and with each `$NAME` / `${…}` /
    `$1` reference dropped, so a path glued to an expansion (`$PWD/tools/x.sh`,
    `$(git rev-parse --show-toplevel)/tools/x.sh`) is read as the repo path it ends in.

    WHAT A WORD CAN DENOTE (`_reach`), from a directory the command may stand in:
      - a relative word is joined to that directory and normalised, so `../other/run.py` read from
        `tools` is `other/run.py` — a parent-directory step is RESOLVED, never discarded;
      - a word OUTSIDE the repository's own namespace — an absolute path, a home-relative one, or
        one that climbs above the root — is read as EVERY repository path it ENDS in. Its prefix
        cannot be compared: the checkout's absolute spelling differs between a land's worktree, a
        Tests-stage run and the main checkout, and through any link above it. So
        `/srv/app/other/run.py` and `../app/other/run.py` both name `other/run.py`.

    DIRECTORIES. A reading that is a directory of the repository may be where the command goes on
    to run (`cd tools && cd sub && …`, `git -C tools …`, `npm --prefix web …`,
    `cd /srv/app/tools && …`), so every word is ALSO read from each such directory, and from each
    directory reached by composing them in any order — no keyword (`cd`, `-C`) is looked for,
    because any spelling of «go there» names the directory. A word names a repo file when one of
    those readings equals a path in `repo_files`.

    WIDER than «invokes» on purpose: a file passed as a plain argument is named too, so the refusal
    errs toward listing more under `sources:`. NARROWER in one stated way: a file the text never
    SPELLS — produced by a glob or brace pattern, or reached through an interpreter's module
    lookup, a package script or `PATH` — is not seen; the adapter is project-authored, and
    SPEC-1006 rule 4's LIMIT says what that means. Pure; sorted, no duplicates."""
    import posixpath
    text = str(command or "")
    if repo_dirs is None:
        repo_dirs = {f[:k] for f in repo_files for k in range(len(f)) if f[k] == "/"}
    raw = set(_adapter_shell_words(text))
    for word in list(raw):
        raw.update(re.split(r"[=:,]+", word))
    raw.update(re.split(r"[\s;|&()<>{}=\"'`,:]+", text))
    words = set()
    for word in raw:
        words.add(word)                                    # as spelled: a `$` may be literal
        words.add(re.sub(r"\$\{[^}]*\}|\$[A-Za-z0-9_]+|\$[@*#?!$-]", "", word))
    words.discard("")

    def _tails(parts):
        return {"/".join(parts[k:]) for k in range(len(parts))}

    def _reach(base, word):
        """The repository paths `word` can denote when the command stands in `base`."""
        if word.startswith(("/", "~")):
            # Absolute or home-relative: every repository path it ends in — and, since the root may
            # be what a dropped expansion stood for, the path under `base` as well.
            parts = [p for p in posixpath.normpath(word).split("/") if p not in ("", ".", "..")]
            if word.startswith("~") and parts:
                parts = parts[1:]                          # the `~` / `~user` component itself
            under = posixpath.normpath(posixpath.join(base, *parts)) if parts else ""
            return _tails(parts) | ({under} if under and under != "." else set())
        norm = posixpath.normpath(posixpath.join(base, word) if base else word)
        if norm == ".." or norm.startswith("../"):
            # Climbs above the repository root: where it comes back down cannot be compared either.
            return _tails([p for p in norm.split("/") if p != ".."])
        return set() if norm == "." else {norm}

    bases = {""}
    grew = True
    while grew:                                            # every directory the text can compose
        grew = False
        for base in list(bases):
            for word in words:
                for step in _reach(base, word):
                    if step in repo_dirs and step not in bases:
                        bases.add(step)
                        grew = True
    named = set()
    for base in bases:
        for word in words:
            named.update(path for path in _reach(base, word) if path in repo_files)
    return sorted(named)


def _adapter_dependency_manifest(path: str) -> bool:
    """SPEC-1006 rule 6 rung (b) — is `path` a dependency manifest, a lockfile or a toolchain /
    browser version pin? Judged by the file's NAME alone, in any directory, against the names the
    package managers and version managers in common use give such files, plus three SHAPES every
    one of them shares (a `.lock` family, `*-lock.json|yaml|yml`, a dot-file ending in `version`). The
    list errs toward naming more, because this rung only ever answers «run the full layer». It is
    a FLOOR, not the project's whole knowledge: a pin under a name only this project uses is
    declared by the project as a trigger naming the full layer (rule 7), which the ladder honours
    one rung later. Case-sensitive, as the files are. Pure."""
    name = str(path).rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in (
        # the shapes
        "*.lock", "*.lockb", "*.lockfile", "*-lock.json", "*-lock.yaml", "*-lock.yml",
        "*.lock.json", "*.lock.hcl", "*.resolved", ".*version", ".*-versions",
        # JavaScript / TypeScript
        "package.json", "npm-shrinkwrap.json", "pnpm-workspace.yaml", ".npmrc", ".yarnrc",
        ".yarnrc.yml", ".pnpmfile.cjs", "bunfig.toml", "deno.json", "deno.jsonc", "lerna.json",
        ".nvmrc", "browserslist", ".browserslistrc",
        # Python
        "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "requirements*.txt",
        "requirements*.in", "constraints*.txt", "environment.yml", "environment.yaml",
        "conda*.yml", "conda*.yaml", "tox.ini", "uv.toml", "runtime.txt",
        # Go, Rust, Ruby, PHP, Elixir, Erlang
        "go.mod", "go.sum", "go.work", "go.work.sum", "Cargo.toml", "rust-toolchain",
        "rust-toolchain.toml", "Gemfile", "gems.rb", "*.gemspec", "composer.json", "mix.exs",
        "rebar.config",
        # JVM, .NET, Swift, Dart, native
        "pom.xml", "toolchains.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
        "settings.gradle.kts", "gradle.properties", "gradle-wrapper.properties",
        "libs.versions.toml", "build.sbt", "*.csproj", "*.fsproj", "*.vbproj", "*.props",
        "*.targets", "global.json", "nuget.config", "NuGet.Config", "packages.config",
        "Package.swift", "Podfile", "Cartfile", "pubspec.yaml", "vcpkg.json", "conanfile.txt",
        "conanfile.py", "CMakeLists.txt", "MODULE.bazel", "WORKSPACE", "WORKSPACE.bazel",
        # version managers, environments, containers
        ".tool-versions", ".sdkmanrc", "mise.toml", ".mise.toml", "flake.nix", "shell.nix",
        "default.nix", "Brewfile", "Dockerfile", "Dockerfile.*", "*.Dockerfile", "Containerfile",
        "Containerfile.*", "docker-compose*.yml", "docker-compose*.yaml", "compose*.yml",
        "compose*.yaml"))


def _adapter_file_digest(path) -> "str | None":
    """The COMPLETE content of ONE `sources:` file as an identity input: `sha256:<hex>`; `absent`
    when git lists the path and the working tree holds NO entry of that name (a deletion not yet
    committed — a state of the tree, hashed as such); or None when no content hash can be
    completed — the entry is not a regular file, cannot be read (a dangling or looping link is an
    entry that EXISTS and has no readable content, never an absent one), or its size moved while
    it was read. A None WITHHOLDS the layer's identity: a hash of part of a file, of its size, or
    of a word standing for unread content, would be equal for two different contents.

    Never blocks, never raises, bounded: the file is opened non-blocking and the OPENED descriptor
    is what is examined (the stance of `_adapter_read_output`); exactly the size that descriptor
    reported is hashed, in 1 MiB steps, so memory is constant and the read ends — a file that
    proves shorter or longer than its reported size is None."""
    import hashlib
    import stat
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        try:
            return None if os.path.lexists(str(path)) else "absent"
        except (OSError, ValueError):
            return None
    except (OSError, ValueError):
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None
        digest, left = hashlib.sha256(), info.st_size
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 20))
            if not chunk:
                return None                                # shorter than the size it reported
            digest.update(chunk)
            left -= len(chunk)
        if os.read(fd, 1):
            return None                                    # longer: it grew while it was read
        return "sha256:" + digest.hexdigest()
    except OSError:
        return None
    finally:
        os.close(fd)


def _adapter_sources_snapshot(worktree, decl: dict, *, _run_git_cap) -> "str | None":
    """SPEC-1006 rule 8 — ONE reading of what a layer's `sources:` hold AT THIS MOMENT: a digest
    over the complete content of every repository file under them. The file set is asked of git
    each time (tracked plus untracked-and-not-ignored, by LITERAL pathspec — a source's name is
    never read as a glob), so a file the layer's command or its adapter created under a source is
    part of the reading and an ignored by-product is not. None when the reading cannot be
    completed: no git runner, a failed listing, or a file whose content cannot be hashed
    (`_adapter_file_digest`).

    The identity needs this reading TWICE — just before the adapter runs and just after
    (`_adapter_stamp_identity`): once would describe sources the layer's own `prep:` or command
    may since have rewritten, or that the adapter rewrote under itself. Never raises."""
    import hashlib
    try:
        sources = list(decl.get("sources") or ())
        files: list = []
        if sources:
            if _run_git_cap is None:
                return None
            listing = _run_git_cap(["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
                                    *[f":(literal){s}" for s in sources]], worktree)
            if listing is None or listing.returncode != 0:
                return None
            files = sorted({name for name in (listing.stdout or "").split("\0") if name})
        digests = {}
        for rel in files:
            digests[rel] = _adapter_file_digest(Path(worktree) / rel)
            if digests[rel] is None:
                return None
        return hashlib.sha256(json.dumps(digests, sort_keys=True, ensure_ascii=True,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()
    except Exception:                                      # an unreadable tree is «cannot be completed»
        return None


def _adapter_identity_static(decl: dict) -> str:
    """SPEC-1006 rule 8 — the hash over the DECLARED identity inputs: the layer's `command:`,
    `subject_globs` and `covers_classes`, the adapter's three commands, its report profile,
    `modelled:` and triggers. The operating modes (`selection`, `credit`, `rescue`) and
    `required:` are NOT inputs. The content of its `sources:` and the versions the runner reports
    join it per run (`_adapter_stamp_identity`). Deterministic: a canonical JSON text, keys
    sorted; a value JSON cannot carry is read through `repr`. Pure."""
    import hashlib
    doc = {"layer": decl.get("layer"), "list": decl.get("list"), "related": decl.get("related"),
           "run": decl.get("run"), "report_profile": decl.get("report_profile"),
           "modelled": decl.get("modelled"), "triggers": decl.get("triggers")}
    try:
        text = json.dumps(doc, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=repr)
    except (TypeError, ValueError, RecursionError):   # a self-referencing YAML value, a mixed-type key
        text = repr(doc)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _adapter_stamp_identity(rec: dict, decl: dict, before: "str | None", after: "str | None") -> dict:
    """SPEC-1006 rule 8 — write the layer's IDENTITY onto an adapter record, or say why there is
    none. `before` / `after` are the two `_adapter_sources_snapshot` readings taken around the
    adapter pass that produced `rec`.

    AN IDENTITY IS ISSUED ONLY WHEN EVERY INPUT IS KNOWN FOR THE RUN — a hash over less would let
    two runs that differ in an unknown input read as one identity. Otherwise the record carries
    `identity_unavailable`, the FIRST of these that holds:
      no-inventory          `list` did not answer this run (failed, not run, or the layer declares
                            none), so no runner version was reported;
      pass-incomplete       the adapter pass kept no rows: it hit the layer's bound, faulted, or a
                            `required:` check failed before `run`;
      versions-unreported   `list` answered and reported no version;
      source-unreadable     a reading of the `sources:` could not be completed;
      source-changed        the `sources:` read differently after the adapter ran than before it —
                            the evidence was not produced under one adapter.
    Exactly one of `identity` / `identity_unavailable` is written. The identity hashes the declared
    inputs (`_adapter_identity_static`), the sources reading and the reported `versions`; the
    operating modes are outside it, and nothing reads it to decide. Returns `rec`. Pure."""
    import hashlib
    rec.pop("identity", None)
    rec.pop("identity_unavailable", None)
    versions = rec.get("versions")
    if rec.get("list") != "ok":
        why = "no-inventory"
    elif rec.get("outer") or rec.get("error") or "units" not in rec:
        why = "pass-incomplete"
    elif not (isinstance(versions, dict) and versions):
        why = "versions-unreported"
    elif not (isinstance(before, str) and before and isinstance(after, str) and after):
        why = "source-unreadable"
    elif before != after:
        why = "source-changed"
    else:
        rec["identity"] = hashlib.sha256("\n".join((
            _adapter_identity_static(decl), before,
            json.dumps(versions, sort_keys=True, ensure_ascii=True))).encode("utf-8")).hexdigest()
        return rec
    rec["identity_unavailable"] = why
    return rec


def _declared_layer_adapters(layers, *, repo_files) -> dict:
    """SPEC-1006 rule 1 — read every declared `verify.layers[].adapter`. Returns `{layer index:
    normalized declaration}` for the layers that carry the key (EMPTY when none does — a layer
    without `adapter:` is not touched by anything in this block); raises ValueError on a
    PRESENT-but-malformed declaration so the caller fails CLOSED before any layer runs (the
    `timeout_seconds:` / `independent_layers:` stance). Presence is keyed off the KEY: an explicit
    `adapter: ~` is malformed, never silently absent.

    The accepted shape — a CLOSED key set, so a typo (`selecton:`) is refused rather than ignored:
      run             REQUIRED, a non-empty command string;
      list, related   optional; omitted = the runner has none (rule 3's two safe fallbacks). A
                      present key is a non-empty command string — `list: ~` is malformed;
      report_profile  REQUIRED, a key of `_ADAPTER_REPORT_PROFILES`;
      sources         optional list of repo-relative paths (files or directories), no duplicates,
                      each naming at least one repo file;
      required        optional list of non-empty command strings (rule 5);
      modelled        optional list of file-name SUFFIXES (rule 3) — the input kinds the
                      runner's dependency graph resolves, each beginning with a dot and holding no
                      `/`, whitespace or glob character. OMITTED = source modules only
                      (`.ts .tsx .js .jsx .mjs .cjs`); an explicit empty list = no input is
                      modelled, so every change is `unknown`;
      triggers        optional list of mappings (rule 7), each a CLOSED key set: `globs` (a
                      non-empty list of globs, matched as `subject_globs` are) and EXACTLY ONE of
                      `units` (a non-empty list of repo-relative unit files, canonical, no
                      duplicate) or `full: true` (the full layer);
      selection, credit   `off` (default) | `shadow` | `deciding`;   rescue   `on` (default) | `off`;
      selection_deciding_reason, credit_deciding_reason   the reason a DECIDING mode is declared
                      with (SPEC-1030 rule 1) — a non-empty string, required IFF its mode reads
                      `deciding`.
    YAML reads a bare `on` / `off` as a boolean, so `true` / `false` are accepted as those two
    words and nothing else is coerced — `on` is no value of `selection` or `credit`, and its
    refusal lists `deciding` among the values that are.

    A DECIDING MODE (SPEC-1030 rule 1) is malformed, each with its cause named, when its reason is
    absent, empty, blank or not a string; when a reason is present while its mode is not
    `deciding`; and when one of the two keys reads `deciding` while the other reads `shadow` (a
    shadow key promises the full run its record is compared against, a deciding key removes it).
    The parsed record carries a deciding mode's reason as written, beside the mode; nothing in the
    kernel reads it to decide anything — it is the project's own statement in its own contract.

    THE `sources:` CHECK. Every repo file a `list` / `related` / `run` / `required[]` command names
    (`_adapter_command_repo_paths`) must be listed under `sources:` — itself, or a directory above
    it. `repo_files` is the set of repo-relative paths git tracks or would track (tracked plus
    untracked-and-not-ignored, so a Stage-6 run before the commit reads the same set the land
    will); None — the set could not be read — fails closed, because the check cannot run.

    The declaration keys later cards consume (`required`, the `credit` / `rescue` modes) are
    validated HERE for their container shape only; the card that consumes one tightens its inner
    shape in this reader (`modelled` and `triggers`: T-13610).

    WHAT THE RECORD ALSO CARRIES (T-13610, rules 6 and 8): `layer` — the layer's own `command`,
    `subject_globs` and `covers_classes`, as declared (identity inputs, and the ladder's
    eligibility and browser-class readings); `prep_files` — its `prep:` manifest and lockfile,
    where declared (rung (b) reads them). Pure over its arguments."""
    import posixpath
    out: dict = {}
    repo_dirs = None           # the repository's directories, derived once on first need
    for i, ly in enumerate(layers if isinstance(layers, list) else []):
        if not isinstance(ly, dict) or "adapter" not in ly:
            continue
        name = str(ly.get("layer") or "").strip() or f"[{i}]"
        where = f"verify.layers[{i}] ({name}) `adapter:`"
        raw = ly.get("adapter")
        if not (isinstance(raw, dict) and raw):
            raise ValueError(f"{where} is not a non-empty mapping")
        unknown = sorted(str(k) for k in raw if k not in _ADAPTER_KEYS)
        if unknown:
            raise ValueError(f"{where} carries unknown key(s) {unknown} — the key set is closed: "
                             f"{', '.join(_ADAPTER_KEYS)}")
        decl: dict = {}
        for key in ("list", "related", "run"):
            if key in raw:
                if not (isinstance(raw[key], str) and raw[key].strip()):
                    raise ValueError(f"{where} `{key}:` = {raw[key]!r} is not a non-empty command "
                                     f"string (omit the key when the runner has no `{key}`)")
                decl[key] = raw[key]
        if "run" not in decl:
            raise ValueError(f"{where} declares no `run:` command")
        profile = raw.get("report_profile")
        if not (isinstance(profile, str) and profile in _ADAPTER_REPORT_PROFILES):
            raise ValueError(f"{where} `report_profile:` = {profile!r} is not a known profile "
                             f"({', '.join(sorted(_ADAPTER_REPORT_PROFILES))})")
        decl["report_profile"] = profile
        for key in ("sources", "required", "modelled"):
            val = raw.get(key, [])
            if not (isinstance(val, list) and all(isinstance(x, str) and x.strip() for x in val)):
                raise ValueError(f"{where} `{key}:` = {val!r} is not a list of non-empty strings")
            decl[key] = list(val)
        if "modelled" not in raw:
            decl["modelled"] = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]
        else:
            modelled: list = []
            for j, suffix in enumerate(decl["modelled"]):
                word = suffix.strip()
                if not (len(word) >= 2 and word.startswith(".") and not re.search(r"[\s/\\*?\[\]]", word)):
                    raise ValueError(f"{where} `modelled[{j}]` = {suffix!r} is not a file-name suffix "
                                     f"(a dot and the extension, e.g. `.ts` — no `/`, space or glob)")
                if word not in modelled:
                    modelled.append(word)
            decl["modelled"] = modelled
        triggers = raw.get("triggers", [])
        if not (isinstance(triggers, list) and all(isinstance(t, dict) and t for t in triggers)):
            raise ValueError(f"{where} `triggers:` = {triggers!r} is not a list of non-empty mappings")
        decl["triggers"] = []
        for j, trig in enumerate(triggers):
            at = f"{where} `triggers[{j}]`"
            extra = sorted(str(k) for k in trig if k not in ("globs", "units", "full"))
            if extra:
                raise ValueError(f"{at} carries unknown key(s) {extra} — a trigger is `globs` plus "
                                 f"exactly one of `units` / `full: true`")
            globs = trig.get("globs")
            if not (isinstance(globs, list) and globs
                    and all(isinstance(g, str) and g.strip() for g in globs)):
                raise ValueError(f"{at} `globs:` = {globs!r} is not a non-empty list of non-empty strings")
            if ("units" in trig) == ("full" in trig):
                raise ValueError(f"{at} names {'both' if 'units' in trig else 'neither'} `units` "
                                 f"{'and' if 'units' in trig else 'nor'} `full` — a trigger maps its "
                                 f"globs to exactly one of them")
            entry = {"globs": [g.strip() for g in globs]}
            if "full" in trig:
                if trig["full"] is not True:
                    raise ValueError(f"{at} `full:` = {trig['full']!r} is not `true` (a trigger can "
                                     f"only widen: omit it, or name `units`)")
                entry["full"] = True
            else:
                named = trig["units"]
                if not (isinstance(named, list) and named
                        and all(isinstance(u, str) and u.strip() for u in named)):
                    raise ValueError(f"{at} `units:` = {named!r} is not a non-empty list of non-empty strings")
                for u in named:
                    if u.startswith("/") or posixpath.normpath(u) != u or u in (".", "..") \
                            or u.startswith("../"):
                        raise ValueError(f"{at} `units:` names {u!r}, which is not a canonical "
                                         f"repo-relative file")
                if len(set(named)) != len(named):
                    raise ValueError(f"{at} `units:` = {named!r} names a unit twice")
                entry["units"] = list(named)
            decl["triggers"].append(entry)
        for key, allowed in _ADAPTER_MODES.items():
            val = raw.get(key, allowed[0])
            if isinstance(val, bool):
                val = "on" if val else "off"
            if not (isinstance(val, str) and val in allowed):
                raise ValueError(f"{where} `{key}:` = {raw.get(key)!r} is not one of: {', '.join(allowed)}")
            decl[key] = val
        for key, reason_key in _ADAPTER_REASON_KEYS.items():
            if decl[key] == "deciding":
                reason = raw.get(reason_key)
                if not (isinstance(reason, str) and reason.strip()):
                    said = "is absent" if reason_key not in raw else f"= {reason!r} is not a non-empty string"
                    raise ValueError(f"{where} declares `{key}: deciding` without its reason — `{reason_key}:` "
                                     f"{said}; a deciding mode names, in the same `adapter:` block, who "
                                     f"accepted the risk and why (SPEC-1030 rule 1)")
                decl[reason_key] = reason
            elif reason_key in raw:
                raise ValueError(f"{where} carries `{reason_key}:` while `{key}:` reads `{decl[key]}`, not "
                                 f"`deciding` — a reason is declared only with its mode (SPEC-1030 rule 1)")
        for key, other in (("selection", "credit"), ("credit", "selection")):
            if decl[key] == "deciding" and decl[other] == "shadow":
                raise ValueError(f"{where} declares `{key}: deciding` beside `{other}: shadow` — a shadow key "
                                 f"promises the full run its record is compared against and a deciding key "
                                 f"removes that run; beside a deciding key the other key is `off` or "
                                 f"`deciding` (SPEC-1030 rule 1)")
        if repo_files is None:
            raise ValueError(f"{where} cannot be checked — the repository's file set could not be read "
                             f"(`git ls-files` failed), so the `sources:` check cannot run")
        sources: list = []
        for j, src in enumerate(decl["sources"]):
            norm = posixpath.normpath(src.strip())
            # A parent-directory COMPONENT escapes the repository; a name that merely begins with
            # two dots (`..fixtures`) is an ordinary repo-relative name and is accepted.
            if norm.startswith("/") or norm in (".", "..") or norm.startswith("../"):
                raise ValueError(f"{where} `sources[{j}]` = {src!r} is not a repo-relative path")
            if norm in sources:
                raise ValueError(f"{where} `sources[{j}]` = {src!r} is a duplicate")
            if not any(f == norm or f.startswith(norm + "/") for f in repo_files):
                raise ValueError(f"{where} `sources[{j}]` = {src!r} names no file of this repository")
            sources.append(norm)
        decl["sources"] = sources
        prep = ly.get("prep") if isinstance(ly.get("prep"), dict) else {}
        decl["layer"] = {"command": ly.get("command"), "subject_globs": ly.get("subject_globs"),
                         "covers_classes": ly.get("covers_classes")}
        decl["prep_files"] = sorted(str(prep[k]).strip() for k in ("manifest", "lockfile")
                                    if isinstance(prep.get(k), str) and prep[k].strip())
        commands = [(k, decl[k]) for k in ("list", "related", "run") if k in decl]
        commands += [(f"required[{j}]", c) for j, c in enumerate(decl["required"])]
        if repo_dirs is None:
            repo_dirs = {f[:k] for f in repo_files for k in range(len(f)) if f[k] == "/"}
        for key, cmd in commands:
            for path in _adapter_command_repo_paths(cmd, repo_files, repo_dirs):
                if not any(path == s or path.startswith(s + "/") for s in sources):
                    raise ValueError(f"{where} `{key}:` names the repository file {path!r}, which "
                                     f"`sources:` does not list — list every script and runner "
                                     f"configuration the adapter's commands use (SPEC-1035 rule 1)")
        out[i] = decl
    return out


# ───────── T-13610 — the SHADOW selection decision (SPEC-1006 rules 3, 6-9) ─────────
#
# On a layer declaring `selection: shadow` the FULL layer runs exactly as on any adapter-backed
# layer and the decision the rule-6 ladder gives for this change is RECORDED beside it: the rung,
# the units it would run and would omit, and every unit it would have omitted that failed in the
# full run (a DISAGREEMENT). Nothing reads the record to decide what runs. Three pieces:
#   `_adapter_change_facts`     each self-diffing runner's own diff, read with git;
#   `_adapter_shadow_decision`  the ladder — pure over the declaration, the change and the inventory;
#   `_layer_adapter_report_pass` invokes `related` where the ladder asks, and compares.
def _adapter_change_facts(worktree, base_ref: str, forms, *, _run_git_cap) -> dict:
    """SPEC-1006 rule 3 (iii) — the paths each runner's OWN diff contains, derived with git so that
    no `related` answer is trusted for a path its runner never looked at. `forms` names the diff
    forms wanted (`related_diff` of the report profiles in play); returns `{form: frozenset | None}`:

      merge-base   `<base>...HEAD` (from the merge base) plus the staged, unstaged and untracked
                   files — Vitest's reading;
      worktree     the working tree against `<base>` plus the untracked files — Playwright's.

    None when any read of that form failed: the ladder reads it as «every eligible path is
    `unknown`», never as an empty diff. A form this reader does not know is None too. Renames are
    left ON (git's default, and so the runner's): a renamed file is seen under its new name only.
    Every listing is NUL-separated (`-z`), so a path is the name git holds, never a quoted
    spelling. Reads only — at most five git calls, made once per verify and only when a
    `selection: shadow` layer's runner diffs by itself."""
    def _names(argv):
        r = _run_git_cap(argv, worktree)
        if r is None or r.returncode != 0:
            return None
        return [t for t in (r.stdout or "").split("\0") if t]

    reads = {"merge-base": (["diff", "--name-only", "-z", f"{base_ref}...HEAD", "--"],
                            ["diff", "--name-only", "-z", "HEAD", "--"],
                            ["diff", "--name-only", "-z", "--cached", "HEAD", "--"]),
             "worktree": (["diff", "--name-only", "-z", base_ref, "--"],)}
    seen: dict = {}
    untracked = False                                      # False = not read yet
    for form in sorted(set(forms)):
        if form not in reads:
            seen[form] = None
            continue
        if untracked is False:
            untracked = _names(["ls-files", "-z", "--others", "--exclude-standard"])
        parts = [_names(argv) for argv in reads[form]] + [untracked]
        seen[form] = (frozenset(path for part in parts for path in part)
                      if all(part is not None for part in parts) else None)
    return seen


#: T-13964 — the two SPEC-0152 rule-16 edge reasons the ladder lets the project's own test files pass
#: (`_edge_own_test_paths`); byte-equal to the tokens the skip decision records
#: (`worktree._SKIP_EDGE_VERIFY_TOUCH`, the declared-check-surface companion's reason).
_ADAPTER_OWN_TEST_EDGES = ("verify-implementation-touch", "declared-check-surface")


def _related_changed_paths(paths) -> list:
    """T-14317 (SPEC-1046 rule 3) — the changed paths `related` is handed: `paths` less every path the
    SPEC-0064 authority classifies inert (the journal, task cards, audit records, the derived graph),
    asked per path and path-only exactly as `_stage6_inert_paths` asks it — one authority, no second
    list. Order and spelling are kept; an all-inert change hands an empty list. No runner can place a
    bookkeeping path, so handing one made `related` answer the whole layer on every real card.
    T-14319: the ladder applies it at its ENTRY too (`_adapter_shadow_decision`), so every rung reads
    the same set `related` is handed. A classifier that cannot be asked hands the whole list — the
    wider answer, never a narrower one."""
    paths = [str(p) for p in paths]
    try:
        from lib.cli import _classify_inert_paths      # lazy: cli is loaded by every verb that gets here
        return [p for p in paths if _classify_inert_paths([p])[0] != "inert"]
    except Exception:
        return paths


def _adapter_shadow_decision(decl: dict, change: dict, inventory, ask_related, exists=None, *,
                             _subject_globs_would_skip) -> dict:
    """SPEC-1006 rule 6 — the selection ladder for ONE layer and ONE change, in the rule's order.
    Returns the record that rides the adapter record as `selection` (registered in SPEC-0025).
    PURE apart from two callables: `ask_related()` (invoked at most once, and only when the ladder
    reaches the `related` answer) and `exists(path)` (is the changed path still a file of the
    candidate tree; omitted = every path is). ELIGIBILITY is judged by the injected
    `_subject_globs_would_skip` — the SPEC-0152 rule-16 per-layer judge itself, asked one path at
    a time, so «a path the layer's globs admit» has one definition for the skip and for this
    ladder (a layer with no usable globs admits every path, as that judge answers).

    `change` is what the kernel knows of the change: `paths` (its changed-path list, None when it
    has none — each path is judged under the EXACT name git gives it: a name is never trimmed or
    rewritten, since `a.sh ` and `a.sh` are two files), `edge` (the reason the SPEC-0152 rule-16 skip decision ran every layer, or None),
    `edge_paths` (T-13916 — the changed paths that made that decision answer `edge`, as the
    decision itself reports them; absent or None where it named none), `edge_test_paths` (T-13964 —
    the subset of them `_edge_own_test_paths` proved the project's own test files; absent = none),
    `base`, and `seen` from
    `_adapter_change_facts`. `inventory` is `list`'s unit list, or None
    when this run has none.

    THE ORDER. The default is RUN: every answer but the last is the full layer.
      no changed paths    the kernel has no path list for this run (no comparison base, a diff that
                          could not be read, an empty diff): `rung` null, the full layer.
      (a)                 a verify-infrastructure touch — the SPEC-0152 rule-16 edge fired
                          (`edge`) — or a changed path under the layer's own `sources:`. T-13964:
                          a `verify-implementation-touch` / `declared-check-surface` edge does NOT
                          answer here when `edge_paths` is a non-empty list and every path in it is
                          in `edge_test_paths` (the project's own test files, `_edge_own_test_paths`)
                          and this layer places it — a unit file of `inventory`, or no longer a
                          file and eligible (rung (d) then answers it as deleted, whether or not a
                          trigger names it). Those files join the units chosen at rung (f).
      (b)                 a changed dependency manifest, lockfile or toolchain pin
                          (`_adapter_dependency_manifest`, plus the layer's own `prep:` files).
      (c)                 a changed path matches a trigger naming the full layer.
      no inventory        `list` is absent or failed for this run, or the report profile names a
                          void condition it cannot reveal: no selection rests on such a layer
                          (rules 3 and 4) — `rung` null, the full layer. A trigger naming a unit
                          the inventory does not hold cannot be honoured unit by unit either: it
                          widens to the full layer, rung (c).
      (d)                 no `related` command; or a path is `unknown`; or `related` failed or
                          timed out. `unknown` is DERIVED here, never taken from the runner — every
                          changed path the layer's eligibility admits (its `subject_globs`; all of
                          them where the layer declares none) that no trigger names and that is
                          (i) deleted or renamed — no longer a file of the candidate tree: the
                          kernel's path list is rename-free, so a rename is its old name gone
                          beside a new file — (ii) outside the `modelled:` suffixes, or (iii)
                          absent from the runner's own diff, for a profile whose runner diffs by
                          itself (`related_diff`). `related` is asked only when no path is unknown.
      (e)                 a browser-class layer (`covers_classes` holds `e2e`): an eligible changed
                          path that is neither one of the layer's unit files nor named by a trigger.
      (f)                 the selected units: `related`'s answer plus the units of every matching
                          trigger plus the own test files rung (a) let pass, each widened to its
                          whole declared group.
    Every rung reads the change less its SPEC-0064 inert paths (T-14319 — dropped once, at the
    entry; an all-inert change answers `units` with nothing to run, reason `inert-only`).
    Rungs (a)-(c) read EVERY such path — inside a layer a glob never subtracts; `unknown` and
    rung (e) read the eligible ones, a path outside the globs being no input of this layer.

    THE RECORD: `{schema: 1, mode: "shadow", decision: "full" | "units", rung, reason, related,
    related_reason?, base?, changed?, eligible?, units_total?, fired_paths?, fired_paths_more?,
    unknown?, unknown_more?, would_run?, would_omit?, would_credit}`. `decision: "full"` = every unit of the layer would run and none
    would be omitted, so the two lists are written only for `units`, each entry `{file, project?}`
    in inventory order. `would_credit` is always empty here: a credit is the previous attempt's
    (rule 14), and this decision reads no previous attempt — on a layer that also declares
    `credit: shadow` the pass writes the would-credit units of `_adapter_credit_decision` into
    it. `unknown` holds at most 20 `{path, why}` entries, the rest counted in `unknown_more`.
    `fired_paths` (T-13916) is written on a rung-(a) answer ONLY, and names the changed paths that
    produced it — the paths under the layer's own `sources:` for `adapter-sources`, the caller's
    `edge_paths` for an edge — in the order the change lists them, never a path the change does
    not hold. It holds at most 20 paths, the rest counted in `fired_paths_more` (the bound of
    `unknown`). Where the answer has no path the kernel can name — an edge that reported none —
    both keys are absent, never an empty list. It changes no answer: the rung and the reason are
    decided before it is written."""
    sel = {"schema": 1, "mode": "shadow", "decision": "full", "rung": None, "reason": "",
           "related": "absent" if "related" not in decl else "not-run", "would_credit": []}
    if change.get("base"):
        sel["base"] = str(change["base"])
    if inventory is not None:
        sel["units_total"] = len(inventory)

    def _full(rung, reason):
        sel["rung"], sel["reason"] = rung, reason
        return sel

    paths = change.get("paths")
    if not paths:
        return _full(None, str(change.get("edge") or "no-diff"))
    # T-14319 (SPEC-1046 rule 3) — THE LADDER'S ENTRY: the SPEC-0064 inert paths (the journal, task
    # cards, audit records, the derived graph) leave the change here, ONCE, so every rung below and
    # `related` read the same non-inert set. No runner places a bookkeeping path, so reading it at
    # rung (d) made every real card the full layer. `changed` still counts the whole change.
    sel["changed"] = len(paths)
    paths = _related_changed_paths(paths)                   # git's own spelling, never trimmed
    if not paths and not change.get("edge"):
        # an all-inert change: nothing of it is an input of this layer — no unit is selected
        sel["eligible"] = 0
        if inventory is None:
            return _full(None, "no-inventory")
        sel.update({"decision": "units", "rung": "f", "reason": "inert-only", "would_run": [],
                    "would_omit": [{"file": u["file"], **({"project": u["project"]} if u.get("project") else {})}
                                   for u in inventory]})
        return sel
    layer = decl.get("layer") or {}
    eligible = [p for p in paths if not _subject_globs_would_skip([p], layer.get("subject_globs"))]
    sel["eligible"] = len(eligible)
    # (a)
    def _fired(named):
        # only a list of names can name a path: any other report names none
        named = {p for p in named if isinstance(p, str)} if isinstance(named, (list, tuple)) else set()
        fired = [p for p in paths if p in named]
        if fired:
            sel["fired_paths"] = fired[:20]
            if len(fired) > 20:
                sel["fired_paths_more"] = len(fired) - 20

    exists = exists or (lambda _path: True)
    # T-13964 — the consumer arm of the edge: a SPEC-0152 rule-16 touch made ONLY by the project's own
    # test files that THIS layer places (a unit of its inventory, or a deleted eligible one, which
    # rung (d) then answers) does not answer here; the files join the selected units at rung (f).
    own_tests: set = set()
    if change.get("edge"):
        fired_by = change.get("edge_paths")
        own = change.get("edge_test_paths")
        placed = {u["file"] for u in inventory} if inventory is not None else set()
        changed, admitted = set(paths), set(eligible)
        if not (str(change["edge"]) in _ADAPTER_OWN_TEST_EDGES and inventory is not None
                and isinstance(fired_by, (list, tuple)) and fired_by
                and isinstance(own, (set, frozenset, list, tuple))
                and all(isinstance(p, str) and p in own and p in changed
                        and (p in placed or (not exists(p) and p in admitted)) for p in fired_by)):
            _fired(fired_by)
            return _full("a", str(change["edge"]))
        own_tests = set(fired_by)
    under_sources = [p for p in paths if any(p == s or p.startswith(s + "/") for s in decl.get("sources") or ())]
    if under_sources:
        _fired(under_sources)
        return _full("a", "adapter-sources")
    # (b)
    prep_files = set(decl.get("prep_files") or ())
    if any(_adapter_dependency_manifest(p) or p in prep_files for p in paths):
        return _full("b", "dependency-manifest")
    # (c)
    matched = [t for t in decl.get("triggers") or ()
               if any(fnmatch.fnmatch(p, g) for p in paths for g in t["globs"])]
    if any(t.get("full") for t in matched):
        return _full("c", "trigger-full")
    if inventory is None:
        return _full(None, "no-inventory")
    if _ADAPTER_REPORT_PROFILES[decl["report_profile"]]["unrevealable"]:
        return _full(None, "unrevealable-void")
    unit_files = {u["file"] for u in inventory}
    trigger_files = {f for t in matched for f in t.get("units") or ()}
    if not trigger_files <= unit_files:
        return _full("c", "trigger-unit-not-listed")
    # (d)
    if "related" not in decl:
        return _full("d", "related-absent")
    named = [g for t in decl.get("triggers") or () for g in t["globs"]]
    form = _ADAPTER_REPORT_PROFILES[decl["report_profile"]]["related_diff"]
    seen = None if form == "kernel" else (change.get("seen") or {}).get(form)
    unknown = []
    for p in eligible:
        if p in own_tests and not exists(p):
            unknown.append({"path": p, "why": "deleted-or-renamed"})
            continue                                        # T-13964: a deleted own test file is rung (d), named by a trigger or not
        if any(fnmatch.fnmatch(p, g) for g in named):
            continue                                        # a path a trigger names is MODELLED (rule 7)
        if not exists(p):
            why = "deleted-or-renamed"
        elif not any(p.endswith(suffix) for suffix in decl.get("modelled") or ()):
            why = "outside-modelled"
        elif form != "kernel" and seen is None:
            why = "runner-diff-unreadable"
        elif form != "kernel" and p not in seen:
            why = "not-in-runner-diff"
        else:
            continue
        unknown.append({"path": p, "why": why})
    if unknown:
        sel["unknown"] = unknown[:20]
        if len(unknown) > 20:
            sel["unknown_more"] = len(unknown) - 20
        return _full("d", "unknown-path")
    state, why, reached = ask_related()
    sel["related"] = state
    if state != "ok":
        if why:
            sel["related_reason"] = why
        return _full("d", f"related-{state}")
    # (e)
    classes = layer.get("covers_classes")
    if isinstance(classes, list) and any(isinstance(c, str) and c.strip() == "e2e" for c in classes) \
            and any(p not in unit_files and not any(fnmatch.fnmatch(p, g) for g in named) for p in eligible):
        return _full("e", "browser-layer-change")
    # (f)
    chosen = set(reached) | {(u.get("project") or "", u["file"]) for u in inventory
                             if u["file"] in trigger_files or u["file"] in own_tests}
    groups = {u["group"] for u in inventory
              if u.get("group") and (u.get("project") or "", u["file"]) in chosen}
    would_run, would_omit = [], []
    for u in inventory:
        key = {"file": u["file"], **({"project": u["project"]} if u.get("project") else {})}
        if (u.get("project") or "", u["file"]) in chosen or u.get("group") in groups:
            would_run.append(key)
        else:
            would_omit.append(key)
    sel.update({"decision": "units", "rung": "f", "reason": "related-and-triggers",
                "would_run": would_run, "would_omit": would_omit})
    return sel


# ───────── T-13612 — the would-be CREDIT of a fix attempt (SPEC-1006 rule 14) ─────────
#
# On a layer declaring `credit: shadow` the FULL layer runs, as on every adapter-backed layer, and
# two things are recorded on its adapter record. `attempt` says WHICH run this was — the tree it
# tested (the tree git would commit from the files on disk: `bin/lib/worktree.py#_worktree_disk_tree`,
# the notion T-13532 records for a Stage-6 green), its base and its branch — so a later run can
# read it as its PREVIOUS attempt from the row alone. `credit` is the decision rule 14 describes
# for a run whose previous attempt of the layer FAILED: the units it would re-run, the units it
# would credit with their recorded pass, and every would-credit unit that failed in this full run
# (a DISAGREEMENT). Nothing reads either to decide what runs. Three pieces:
#   `_adapter_previous_attempt`  the newest earlier run of the layer on this branch, off journal rows;
#                                rows it cannot order credit nothing;
#   `_adapter_credit_basis`      what that row allows before any diff is read;
#   `_adapter_credit_decision`   the decision — the rule-6 ladder over the fix's own diff.
def _adapter_previous_attempt(journals, layer: str, branch, *, whole: bool = False) -> "dict | None":
    """SPEC-1006 rule 14 — the PREVIOUS attempt of ONE layer, read from its record alone.
    `journals` is one list of parsed rows PER JOURNAL FILE read, each in that file's own order (a
    journal is append-only, so the order of two rows inside one file is the order they were
    written in). A row is read when it
      • is a `land_completed`, `tests_passed` or `tests_failed` row whose `ts` is a timestamp in
        the kernel's own form (`YYYY-MM-DDTHH:MM:SSZ` — any other value cannot be ordered),
      • carries a `consumer_verify_layers` row for `layer` whose `outcome` says the layer
        EXECUTED (`passed` / `failed` / `timed-out` / `prep-failed` — a waived, malformed or
        skipped layer ran nothing and is no attempt of it), and
      • belongs to `branch`: a land row naming it (`data.branch`), a Tests-stage row of the task
        the branch is named after (`task/<task_id>`), or a row whose own `attempt` record names it.
    The answer is the NEWEST such row: `{type, ts, outcome, adapter}` — `adapter` the layer row's
    adapter record, or None when it carries none. None when no such row exists, or `branch` is
    not known (a detached checkout has no line of work to read a previous attempt for).

    WHICH ROW IS NEWEST. The greatest `ts` decides. A row present in several journals (the same
    content) is ONE row. When several DISTINCT rows share the greatest `ts` — the stamp has
    one-second resolution — a journal that holds ALL of them orders them (the one written last
    there is the newest); when no single journal holds them all, or two such journals disagree,
    their order cannot be established and the answer is `{type: None, ts, outcome: None, adapter: None, ambiguous:
    True}`, which `_adapter_credit_basis` reads as a record nothing may be credited from. The
    order in which the journals are handed over never changes the answer. PURE.

    `whole=True` (T-13909 — SPEC-1030 rule 3) is the reading a DECIDING
    credit takes; without it the answer is the one described above, byte for byte. The previous
    attempt is then the CARD's: the newest such row of `branch` that carries a layer trail,
    WHICHEVER layers it holds (a row also belongs to the branch when any of its layers' `attempt`
    records names it) — so a later attempt that did not run `layer` is not skipped over in favour
    of an older one that did. The answer gains `attempt`: `failed` when the row itself shows the
    attempt did not pass as a whole — a `tests_failed` row, or a `land_completed` row whose
    `status` is `abort` and which records, of its CANDIDATE leg, a layer that did not pass
    (`failed` / `timed-out` / `prep-failed` / `malformed` in its layer trail) or a failed test
    sweep (`candidate_sweep_failures`, a count of at least 1, which the land writes beside the
    trail) — and `passed` for every other row: a row that does not show its own failure is read
    as a whole pass, after which nothing is credited. `failing_tests` is NOT read for it: that
    list also names the pinned last-green leg's failures, so an aborted land whose layers are
    green and which carries no sweep count (a row written before the count existed included)
    credits nothing. `outcome` and `adapter` are `layer`'s in that row when it EXECUTED there
    (`passed-partial` counts: a partial run executed), else both None."""
    if not (isinstance(branch, str) and branch):
        return None
    found: dict = {}             # the row's content -> (ts, what it says, {journal index: last position})
    for j, rows in enumerate(journals or ()):
        for n, ev in enumerate(rows if isinstance(rows, (list, tuple)) else ()):
            if not isinstance(ev, dict) or ev.get("type") not in ("land_completed", "tests_passed", "tests_failed"):
                continue
            ts = ev.get("ts")
            if not (isinstance(ts, str) and re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", ts)):
                continue
            data = ev.get("data")
            layers = data.get("consumer_verify_layers") if isinstance(data, dict) else None
            if not isinstance(layers, list):
                continue
            row = next((r for r in layers if isinstance(r, dict) and r.get("layer") == layer), None)
            ran = row is not None and any(row.get("outcome") == o for o in (
                ("passed", "passed-partial", "failed", "timed-out", "prep-failed") if whole
                else ("passed", "failed", "timed-out", "prep-failed")))
            if not (ran or whole):
                continue
            rec = row.get("adapter") if ran and isinstance(row.get("adapter"), dict) else None
            told = rec.get("attempt") if rec is not None and isinstance(rec.get("attempt"), dict) else {}
            tid = ev.get("task_id")
            named = whole and any(
                isinstance(r, dict) and isinstance(r.get("adapter"), dict)
                and isinstance(r["adapter"].get("attempt"), dict)
                and r["adapter"]["attempt"].get("branch") == branch for r in layers)
            if not (data.get("branch") == branch or told.get("branch") == branch or named
                    or (isinstance(tid, str) and tid and branch == f"task/{tid}")):
                continue
            try:
                same = json.dumps(ev, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=repr)
            except (TypeError, ValueError, RecursionError):
                same = repr(ev)
            says = {"type": ev["type"], "ts": ts, "outcome": row["outcome"] if ran else None, "adapter": rec}
            if whole:
                # T-13909: did the ATTEMPT pass as a whole — read off what the row itself records
                swept = data.get("candidate_sweep_failures")
                swept = isinstance(swept, int) and not isinstance(swept, bool) and swept >= 1
                says["attempt"] = "failed" if ev["type"] == "tests_failed" or (
                    ev["type"] == "land_completed" and data.get("status") == "abort" and (swept or any(
                        isinstance(r, dict) and any(r.get("outcome") == o for o in (
                            "failed", "timed-out", "prep-failed", "malformed")) for r in layers))) else "passed"
            found.setdefault(same, (ts, says, {}))[2][j] = n
    if not found:
        return None
    newest = max(ts for ts, _says, _where in found.values())
    tied = [(says, where) for ts, says, where in found.values() if ts == newest]
    if len(tied) == 1:
        return tied[0][0]
    # Every journal that holds ALL the tied rows names the one it wrote last; they must agree.
    last = {max(range(len(tied)), key=lambda i: tied[i][1][j])
            for j in set.intersection(*(set(where) for _says, where in tied))}
    if len(last) == 1:
        return tied[last.pop()][0]
    return {"type": None, "ts": newest, "outcome": None, "adapter": None, "ambiguous": True}


def _adapter_credit_basis(previous, base, *, deciding: bool = False) -> dict:
    """SPEC-1006 rule 14 — what the PREVIOUS attempt's record (`_adapter_previous_attempt`) allows
    a run on `base` (a full commit id) to credit, decided BEFORE any diff is read. Returns
    `{record, units, change}`: `record` is the credit record so far (`{schema: 1, mode: "shadow",
    decision, reason, previous?}`), `units` the previous attempt's `{(project, file): status}`
    when its record can be credited from (else None), and `change` None — the caller fills it
    with the fix's own diff (`_adapter_credit_decision` reads it). First match wins:

      none  no-previous-attempt      the rows read hold no earlier run of this layer on this
                                     branch (the caller reads a bounded journal tail: an attempt
                                     older than it is not seen) — not a fix attempt, nothing credited;
      none  previous-attempt-passed  the layer PASSED there (a rescued layer reads passed) — the
                                     rule speaks of a run of the layer that FAILED;
      void  record-ambiguous         (iii) several distinct rows share the newest timestamp and
                                     no journal orders them: which one is the previous attempt
                                     cannot be established;
      void  record-missing           (iii) the failed run's row carries no `attempt` record;
      void  record-incomplete        (iii) that record names no tree or no base, or its per-unit
                                     results are absent, not well-formed rows, or name one
                                     unit twice;
      void  base-moved               (i) its base is not this run's base;
      void  previous-report-void     (ii) its report was not usable (void, an unusable `list`, an
                                     outer failure, a failed `required:` check, a faulted pass).
    A record that passes every check is returned as `void` / `diff-unreadable` WITH its `units`:
    it credits nothing until the caller has supplied the diff, so a caller that cannot read one
    leaves a record that already says so. PURE.

    `deciding=True` (T-13909 — SPEC-1030 rule 3) is the basis of a credit
    that ACTS; without it the answer is the one described above, byte for byte. `previous` is
    then `_adapter_previous_attempt(..., whole=True)`'s answer, the record's `mode` reads
    `deciding`, and the premise is the WHOLE attempt's, in place of the second line above:
      none  previous-attempt-passed-whole  that attempt is not shown to have failed as a whole
                                           (`attempt` is not `failed`) — after a whole pass
                                           nothing is credited.
    A layer that PASSED in an attempt that failed elsewhere therefore goes on to the same checks
    a failed layer takes — the widened premise; a layer that attempt did not execute has no
    record there and is `void` / `record-missing`. Every other line is unchanged."""
    rec = {"schema": 1, "mode": "deciding" if deciding else "shadow", "decision": "none",
           "reason": "no-previous-attempt"}
    out = {"record": rec, "units": None, "change": None}
    if not isinstance(previous, dict):
        return out
    rec["previous"] = {k: previous[k] for k in ("type", "ts", "outcome") if isinstance(previous.get(k), str)}
    if previous.get("ambiguous"):
        rec.update({"decision": "void", "reason": "record-ambiguous"})
        return out
    if deciding:
        if previous.get("attempt") != "failed":
            rec["reason"] = "previous-attempt-passed-whole"
            return out
    elif previous.get("outcome") == "passed":
        rec["reason"] = "previous-attempt-passed"
        return out
    rec["decision"] = "void"
    was = previous.get("adapter")
    told = was.get("attempt") if isinstance(was, dict) else None
    if not isinstance(told, dict):
        rec["reason"] = "record-missing"
        return out
    tree, its_base = told.get("tree"), told.get("base")
    rows = was.get("units")
    if not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{40}", v) for v in (tree, its_base)):
        rec["reason"] = "record-incomplete"
        return out
    rec["previous"].update({"tree": tree, "base": its_base})
    if its_base != base:
        rec["reason"] = "base-moved"
        return out
    if was.get("usable") is not True:
        rec["reason"] = "previous-report-void"
        return out
    units = {}
    if isinstance(rows, list):
        for u in rows:
            if not (isinstance(u, dict) and isinstance(u.get("file"), str) and u["file"]
                    and isinstance(u.get("status"), str) and isinstance(u.get("project", ""), str)
                    and (u.get("project", ""), u["file"]) not in units):
                units = {}
                break
            units[(u.get("project", ""), u["file"])] = u["status"]
    if not units:
        rec["reason"] = "record-incomplete"
        return out
    rec["reason"] = "diff-unreadable"
    out["units"] = units
    return out


def _adapter_credit_decision(decl: dict, basis: dict, inventory, ask_related, exists=None, *,
                             _subject_globs_would_skip) -> dict:
    """SPEC-1006 rule 14 — the would-be credit of ONE layer's fix attempt. Returns the record that
    rides the adapter record as `credit` (registered in SPEC-0025). PURE apart from the two
    callables of `_adapter_shadow_decision`, which it hands on unchanged.

    `basis` is `_adapter_credit_basis`'s answer. With no `change` on it the record it already
    holds is returned as it is (`none`, or `void` with its reason): nothing is read. `change` is
    the FIX's own diff — `{base, tree, paths, edge, seen}`: `paths` the changed paths between the
    previous attempt's recorded tree and this candidate's (`tree`), the journal's own files left
    out; `base` what `related` is to diff the candidate against (the recorded tree, or a commit
    over it); `edge` the SPEC-0152 rule-16 fail-closed edge over those paths; `seen` the runner's
    own diff against `base` (`_adapter_change_facts`).

    THE DECISION. With changed paths, the rule-6 ladder (`_adapter_shadow_decision`, the same
    function a `selection: shadow` layer records) decides over THEM; any answer but its last —
    a rung (a)-(e), or a full layer with no rung (no inventory, an unrevealable void) — is case
    (iv): `void` / `full-layer`, with the ladder's `rung` and its reason as `ladder_reason`. With
    NO changed path (the same tree run again) the ladder is not asked and nothing is reached;
    no inventory, or an unrevealable void, is `full-layer` there too. Otherwise `units`:
      would_rerun   every inventory unit that did not read `passed` in the previous attempt
                    (`why: failed`), that its record does not hold (`not-recorded`), that the
                    ladder reaches (`reached`), or that shares a declared group with one of those
                    (`group`) — `{file, project?, why}`, inventory order;
      would_credit  every other unit: it passed in the previous attempt and the fix does not
                    reach it — `{file, project?}`.
    The record also carries `changed` (the fix's path count), `tree` (this candidate's),
    `units_total`, and from the ladder `related`, `related_reason`, `eligible`, `unknown` and
    `unknown_more`. The caller adds `compared` and `disagreements`."""
    rec = {**basis["record"]}
    if isinstance(rec.get("previous"), dict):
        rec["previous"] = dict(rec["previous"])
    change, was = basis.get("change"), basis.get("units")
    if not isinstance(change, dict) or was is None:
        return rec
    paths = [str(p) for p in change.get("paths") or ()]
    rec["changed"] = len(paths)
    if change.get("tree"):
        rec["tree"] = str(change["tree"])
    if inventory is not None:
        rec["units_total"] = len(inventory)

    def _void(rung, why):
        rec.update({"decision": "void", "reason": "full-layer", "rung": rung, "ladder_reason": why})
        return rec

    reached: set = set()
    if paths:
        sel = _adapter_shadow_decision(
            decl, {"base": change.get("base"), "paths": paths, "edge": change.get("edge"),
                   "seen": change.get("seen") or {}}, inventory, ask_related, exists,
            _subject_globs_would_skip=_subject_globs_would_skip)
        rec.update({k: sel[k] for k in ("related", "related_reason", "eligible", "unknown", "unknown_more")
                    if k in sel})
        if sel["decision"] != "units":
            return _void(sel["rung"], sel["reason"])
        reached = {(u.get("project") or "", u["file"]) for u in sel["would_run"]}
    elif inventory is None:
        return _void(None, "no-inventory")
    elif _ADAPTER_REPORT_PROFILES[decl["report_profile"]]["unrevealable"]:
        return _void(None, "unrevealable-void")
    why: dict = {}
    for u in inventory:
        key = (u.get("project") or "", u["file"])
        if key not in was:
            why[key] = "not-recorded"
        elif was[key] != "passed":
            why[key] = "failed"
        elif key in reached:
            why[key] = "reached"
    groups = {(u.get("project") or "", u["group"]) for u in inventory
              if u.get("group") and (u.get("project") or "", u["file"]) in why}
    would_rerun, would_credit = [], []
    for u in inventory:
        key = (u.get("project") or "", u["file"])
        entry = {"file": u["file"], **({"project": u["project"]} if u.get("project") else {})}
        cause = why.get(key) or ("group" if u.get("group") and (key[0], u["group"]) in groups else None)
        if cause:
            would_rerun.append({**entry, "why": cause})
        else:
            would_credit.append(entry)
    rec.update({"decision": "units", "reason": "failed-and-reached",
                "would_rerun": would_rerun, "would_credit": would_credit})
    return rec


def _adapter_report_time(raw) -> "datetime.datetime | None":
    """A JUnit suite `timestamp` as an aware UTC datetime, or None when it does not parse. A value
    with no zone is the runner's LOCAL time (pytest's older reports)."""
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp.astimezone(datetime.timezone.utc)


class _AdapterPassDeadline(Exception):
    """The adapter pass's ONE deadline passed while an output was being read or classified. Raised
    by the checkpoint the pass hands to its readers and caught by the pass alone: a reader only
    CALLS the checkpoint between its steps and lets whatever it raises through."""


def _adapter_second_report_signals(kind: str, doc, checkpoint=None) -> "list | None":
    """Read a profile's SECOND report strictly. Returns the void reasons it shows (possibly none),
    or None when `doc` is not that runner's report — which the caller records as
    `second-report-malformed`, never as «nothing seen».

    EVERY node on the path this reader walks is type-checked, down to the leaves it reads: a
    container of another type, a member that is not an object, a missing field the walk relies on
    or a leaf of another type each make the whole document None. Nothing is skipped, defaulted or
    coerced on that path — a reader that tolerates one malformed member can be handed a report
    whose only retry evidence sits in exactly that member.
      vitest-json      {testResults: [{assertionResults: [{status: str, failureMessages: [str]}]}]}
                       Vitest does not reset a case's errors between its own retry attempts — the
                       trial recorded a retried-then-PASSED case still carrying its first attempt's
                       failure message (journaled `trial_run` 19). So a PASSED case that carries a
                       failure message was retried by the runner, and a case retried and FAILED
                       AGAIN carries one message per attempt: a FAILED case with more than one. A
                       single attempt that records several errors reads the same and voids too —
                       the reading errs toward void, never past it.
      playwright-json  {errors: [object], stats: {flaky: int >= 0},
                        suites: [{specs: [{tests: [{results: [{status: str, retry?: int >= 0}]}]}],
                                  suites?: [the same]}]}
                       A non-empty `errors` is an error outside every unit; `stats.flaky` above
                       zero, a test with more than one result, or a result whose `retry` is above
                       zero is a native retry.
    Pure; `checkpoint`, when given, is called once per walked result / suite node."""
    def _count(value):
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    tick = checkpoint or (lambda: None)
    reasons: list = []
    if not isinstance(doc, dict):
        return None
    if kind == "vitest-json":
        results = doc.get("testResults")
        if not isinstance(results, list):
            return None
        for res in results:
            tick()
            asserts = res.get("assertionResults") if isinstance(res, dict) else None
            if not isinstance(asserts, list):
                return None
            for a in asserts:
                status = a.get("status") if isinstance(a, dict) else None
                msgs = a.get("failureMessages") if isinstance(a, dict) else None
                if not (isinstance(status, str) and status and isinstance(msgs, list)
                        and all(isinstance(m, str) for m in msgs)):
                    return None
                if ((status == "passed" and msgs) or (status == "failed" and len(msgs) > 1)) \
                        and "native-retry" not in reasons:
                    reasons.append("native-retry")
        return reasons
    stats, errors, suites = doc.get("stats"), doc.get("errors"), doc.get("suites")
    if not (isinstance(stats, dict) and _count(stats.get("flaky")) and isinstance(errors, list)
            and all(isinstance(e, dict) for e in errors) and isinstance(suites, list)):
        return None
    if errors:
        reasons.append("error-outside-units")
    retried = stats["flaky"] > 0
    stack = list(suites)
    while stack:
        tick()
        node = stack.pop()
        specs = node.get("specs") if isinstance(node, dict) else None
        subs = node.get("suites", []) if isinstance(node, dict) else None
        if not (isinstance(specs, list) and isinstance(subs, list)):
            return None
        stack.extend(subs)
        for spec in specs:
            tests = spec.get("tests") if isinstance(spec, dict) else None
            if not isinstance(tests, list):
                return None
            for test in tests:
                attempts = test.get("results") if isinstance(test, dict) else None
                if not isinstance(attempts, list):
                    return None
                for attempt in attempts:
                    status = attempt.get("status") if isinstance(attempt, dict) else None
                    if not (isinstance(status, str) and status and _count(attempt.get("retry", 0))):
                        return None
                    retried = retried or attempt.get("retry", 0) > 0
                retried = retried or len(attempts) > 1
    if retried:
        reasons.append("native-retry")
    return reasons


def _classify_adapter_report(profile_id: str, *, requested, exit_code, report_text, second_text=None,
                             started_at=None, project=None, outer=None, checkpoint=None,
                             excerpt_chars: int = 300, max_failed_cases: int = 20) -> dict:
    """SPEC-1006 rule 4 — read ONE adapter `run` invocation's native report against the kernel's
    manifest. PURE (texts in, a dict out; no I/O, no clock of its own). Returns `{void: [reason,
    ...], units: [row, ...]}`, or `{outer, void: [], units: []}` when an outer failure decided first.

    INTERRUPTIBLE. `checkpoint`, when given, is CALLED between the steps of the reading — before
    every 64 KiB handed to the XML parser, every 2048 elements of the placement count, every suite,
    every case, around the second report's decode and at every node of its walk, every 256 rows
    — and whatever it raises ends the reading there and passes through unchanged. That is how the
    pass holds its ONE deadline while a report is read: the longest stretch between two calls is
    one such step, or the single decode of a second report that the pass has already bounded in
    size.

    OUTER FAILURES DECIDE FIRST: with `outer` set (`timed-out` — the invocation hit the layer's
    bound — or `prep-failed`) NOTHING is read, whatever the report says.

    `requested` is the manifest's unit list (`[{project, file, report_id?, group?}]`), or None when
    the layer has no inventory (no `list`): the rows are then keyed by what the report names and no
    completeness can be judged. `project` is the invocation's runner project where the profile's
    report names none. `started_at` is the invocation's start (aware datetime); None skips the
    freshness check (a caller with no clock reading — never the pass below).

    THE VOID CONDITIONS, each a reason in `void` (consistency, not authenticity — rule 4 LIMIT):
      report-missing / report-malformed    no report at the manifest's path / not the JUnit subset
                                           (a suite with no parseable `timestamp`, a suite or a
                                           case with no `name`, a `testcase` that is not a direct
                                           child of a suite or a `failure` / `error` that is not a
                                           direct child of a case — at any depth, so no record is
                                           passed over — or a document type DECLARATION (the
                                           parser's own event: the same characters inside CDATA
                                           or a comment are content and are read as such);
      report-stale                         a suite stamped before the invocation started;
      second-report-missing / -malformed   the profile's second report — absent, or not that
                                           runner's report (`_adapter_second_report_signals`);
      unit-missing                         a requested unit has no record;
      unit-only-skipped                    a requested unit has only skipped records;
      unit-unrequested                     a record for a unit that was not requested;
      unit-duplicate                       one unit reported by two suites;
      non-test-failure                     a collection / setup / teardown failure the runner marks
                                           apart from a test's own failure;
      error-outside-units                  an error outside every unit (an unhandled error);
      native-retry                         the runner retried a case itself;
      nonzero-exit-all-passed              the command exits nonzero while every unit reads passed.
    A failure a runner records ON a unit's own test cases is that UNIT's failure, never a void. A
    skipped CASE never voids and decides nothing: it is counted on the unit's row.

    A unit row: `{project?, file, group?, status, duration_ms?, cases?, skipped?, failed_cases?,
    failed_cases_more?, excerpt?, failed_tests?, named?, unrequested?}` — `project` is ABSENT for a runner with one project
    (a layer may list hundreds of units; the row stays small), while `skipped` is recorded on every
    unit that has a record, zero included; `status` is `passed` / `failed` / `error` (a
    non-test failure recorded on the unit and no failed case) / `skipped` (only skipped records) /
    `missing` (requested, no record); `cases` counts the unit's own case records and
    `skipped` the skipped ones; `failed_cases` carries `{id, excerpt}` for the failed cases, at most
    `max_failed_cases` (the rest counted in `failed_cases_more`); a script-style unit carries no
    case rows and its failure text rides `excerpt`, as does a non-test failure's. A `failed` /
    `error` row also carries `failed_tests` + `named` (T-14298): the names the adapter gave itself as
    `<property name="failed_test" value=...>` on a failed case of the unit, else the ids of its
    `failed_cases`, else what `_failed_test_names` reads off its whole failure text — none when that
    text reports a timeout (`_UNIT_TIMEOUT_RE`), since a killed unit's partial output is not its
    verdict; `[]` / `false` when none names a test — never a guess."""
    import xml.etree.ElementTree as ET
    if outer:
        return {"outer": outer, "void": [], "units": []}
    prof = _ADAPTER_REPORT_PROFILES[profile_id]
    void: list = []

    def _flag(reason):
        if reason not in void:
            void.append(reason)

    def _clip(el):
        text = " ".join(x for x in (el.get("message") or "", (el.text or "").strip()) if x)
        return text[:excerpt_chars]

    def _secs(raw):
        """A report's `time` attribute as non-negative finite seconds; anything else reads 0."""
        try:
            val = float(raw or 0)
        except (TypeError, ValueError):
            return 0.0
        return val if math.isfinite(val) and val >= 0 else 0.0

    tick = checkpoint or (lambda: None)

    def _note_failure(rec, case, bad_el):
        """T-14298: what names a failed unit's tests — the failure's whole text (never the clipped
        excerpt) and the adapter's own `failed_test` properties on the failed case."""
        rec["texts"].append("\n".join(x for x in (bad_el.get("message") or "", bad_el.text or "") if x))
        props = case.find("properties")
        for pr in props.findall("property") if props is not None else ():
            val = (pr.get("value") or "").strip()
            if pr.get("name") == "failed_test" and val and val not in rec["given"]:
                rec["given"].append(val)

    class _DoctypeDeclared(Exception):
        pass

    class _Tree(ET.TreeBuilder):
        def doctype(self, name, pubid, system):
            # The PARSER reports a document type declaration here, so the same characters inside
            # CDATA or a comment (a test that logs an HTML page) never reach this method. No
            # runner's report declares one, and a declaration is where entity definitions live, so
            # the report is refused AT it: the raise ends the feed loop below, and no later chunk
            # of the document is handed to the parser.
            raise _DoctypeDeclared()

    if report_text is None:
        return {"void": ["report-missing"], "units": []}
    text = report_text.lstrip("\ufeff")
    parser = ET.XMLParser(target=_Tree())
    try:
        for at in range(0, len(text), 65536):
            tick()
            parser.feed(text[at:at + 65536])
        root = parser.close()
    except (ET.ParseError, ValueError, _DoctypeDeclared):
        return {"void": ["report-malformed"], "units": []}
    if root.tag not in ("testsuites", "testsuite"):
        return {"void": ["report-malformed"], "units": []}
    # EVERY RECORD IS CONSUMED, OR THE REPORT IS REJECTED. The walk below reads a case as a direct
    # child of a suite, and a failure / error as a direct child of a case. A `testcase` placed
    # anywhere else (under the root, under a nested `testsuites`, inside another record) or a
    # `failure` / `error` placed anywhere else would be read by nothing — so every element of the
    # WHOLE document, whatever the nesting, is counted once under its parent, and a record that is
    # not where the walk reads makes the report malformed.
    all_cases = placed_cases = all_marks = placed_marks = 0
    for n, parent in enumerate(root.iter()):
        if n % 2048 == 0:
            tick()
        for child in parent:
            if child.tag == "testcase":
                all_cases += 1
                placed_cases += parent.tag == "testsuite"
            elif child.tag in ("failure", "error"):
                all_marks += 1
                placed_marks += parent.tag == "testcase"
    if all_cases != placed_cases or all_marks != placed_marks:
        _flag("report-malformed")          # a record outside where the walk reads names no unit
    # ── the manifest's side: which unit a report name maps to ───────────────────────────────────
    wanted: dict = {}        # report key -> (project, file, group)
    if requested is not None:
        for u in requested:
            proj = str(u.get("project") or "")
            rid = str(u.get("report_id") or u.get("file"))
            if not u.get("report_id") and prof["report_id"] == "dotted-module":
                rid = re.sub(r"\.py$", "", rid).replace("/", ".")
            key = (proj, rid) if prof["unit_from"] == "suite+hostname" else rid
            wanted[key] = (proj, str(u.get("file")), u.get("group"))
    seen: dict = {}          # unit id (project, file) -> its accumulating record
    order: list = []
    suites_of: dict = {}     # unit id -> how many suites reported it

    def _unit(uid, group=None, unrequested=False):
        if uid not in seen:
            seen[uid] = {"group": group, "unrequested": unrequested, "passed": 0, "failed": 0,
                         "errors": 0, "skipped": 0, "time": 0.0, "failed_cases": [], "excerpt": None,
                         "texts": [], "given": []}
            order.append(uid)
        return seen[uid]

    case_seen: dict = {}     # (classname, name) -> [is an <error> record, ...] — pytest's rerun trace
    for suite in root.iter("testsuite"):
        tick()
        cases = suite.findall("testcase")
        sname = suite.get("name") or ""
        if sname in prof["outside_suites"]:
            _flag("error-outside-units")
            continue
        if not cases and suite.find("testsuite") is not None:
            continue                                     # a pure container suite
        stamp = _adapter_report_time(suite.get("timestamp"))
        if stamp is None or not sname or any(not c.get("name") for c in cases):
            _flag("report-malformed")      # an unstamped suite, a nameless suite or a nameless case
        elif started_at is not None and stamp < started_at.replace(microsecond=0):
            _flag("report-stale")
        suite_uid = None
        in_suite: set = set()            # classname profile: the units THIS suite reports
        if prof["unit_from"] != "classname":
            key = (suite.get("hostname") or "", sname) if prof["unit_from"] == "suite+hostname" else sname
            if requested is None:
                suite_uid = (key[0], key[1]) if isinstance(key, tuple) else (str(project or ""), key)
                _unit(suite_uid)
            elif key in wanted:
                proj, file_, group = wanted[key]
                suite_uid = (proj, file_)
                _unit(suite_uid, group)
            else:
                _flag("unit-unrequested")
                suite_uid = (key[0], key[1]) if isinstance(key, tuple) else (str(project or ""), key)
                _unit(suite_uid, unrequested=True)
            suites_of[suite_uid] = suites_of.get(suite_uid, 0) + 1
            if suites_of[suite_uid] > 1:
                _flag("unit-duplicate")
            if not cases:
                seen[suite_uid]["time"] += _secs(suite.get("time"))
        for case in cases:
            tick()                       # every case: a classname profile reads the manifest per case
            cname, tname = case.get("classname") or "", case.get("name") or ""
            failure, error = case.find("failure"), case.find("error")
            skipped = case.find("skipped") is not None
            uid, case_id = suite_uid, tname
            if prof["unit_from"] == "classname":
                if requested is None:
                    uid = (str(project or ""), cname) if cname else None
                else:
                    hit = max((k for k in wanted if cname == k or cname.startswith(k + ".")),
                              key=len, default=None)
                    if hit is not None:
                        proj, file_, group = wanted[hit]
                        uid = (proj, file_)
                        _unit(uid, group)
                        if cname != hit:
                            case_id = f"{cname[len(hit) + 1:]}::{tname}"
                    elif cname:
                        _flag("unit-unrequested")
                        uid = (str(project or ""), cname)
                        _unit(uid, unrequested=True)
                    else:
                        uid = None
                if uid is not None:
                    _unit(uid)
                    in_suite.add(uid)
                case_seen.setdefault((cname, tname), []).append(error is not None)
            apart = (error is not None and prof["case_error"] == "apart") or (
                prof["file_named_case"] and (failure is not None or error is not None) and tname == sname)
            if apart or (uid is None and (failure is not None or error is not None)):
                # A collection / setup / teardown failure the runner marks APART from a test's own
                # failure: it voids the report and is never the unit's failure.
                _flag("non-test-failure")
                if uid is not None:
                    seen[uid]["errors"] += 1
                    seen[uid]["excerpt"] = seen[uid]["excerpt"] or _clip(error if error is not None else failure)
                    _note_failure(seen[uid], case, error if error is not None else failure)
                continue
            if uid is None:
                if requested is not None:
                    _flag("unit-unrequested")       # a record that names no unit of the manifest
                continue
            rec = seen[uid]
            rec["time"] += _secs(case.get("time"))
            if failure is not None or error is not None:
                rec["failed"] += 1
                bad_el = failure if failure is not None else error
                _note_failure(rec, case, bad_el)
                if prof["cases"]:
                    rec["failed_cases"].append({"id": case_id, "excerpt": _clip(bad_el)})
                else:
                    rec["excerpt"] = rec["excerpt"] or _clip(bad_el)
            elif skipped:
                rec["skipped"] += 1
            else:
                rec["passed"] += 1
        for uid in in_suite:             # one unit reported by two suites of one report
            suites_of[uid] = suites_of.get(uid, 0) + 1
            if suites_of[uid] > 1:
                _flag("unit-duplicate")
    if any(sum(1 for is_error in v if not is_error) > 1 for v in case_seen.values()):
        # pytest: the same case recorded more than once APART from its `<error>` records. A
        # teardown error beside one attempt is not a retry; beside two attempts it hides none.
        _flag("native-retry")
    # ── the profile's second report: what JUnit cannot show ─────────────────────────────────────
    if prof["second_report"]:
        if second_text is None:
            _flag("second-report-missing")
        else:
            tick()
            try:
                doc = json.loads(second_text)
            except (ValueError, RecursionError):
                doc = None
            tick()
            signals = _adapter_second_report_signals(prof["second_report"], doc, checkpoint)
            for reason in ["second-report-malformed"] if signals is None else signals:
                _flag(reason)
    # ── completeness against the manifest, then the rows ────────────────────────────────────────
    rows: list = []
    if requested is not None:
        for u in requested:
            uid = (str(u.get("project") or ""), str(u.get("file")))
            if uid not in seen:
                _flag("unit-missing")
                _unit(uid, u.get("group"))
                seen[uid]["missing"] = True
    for n, uid in enumerate(order):
        if n % 256 == 0:
            tick()
        rec = seen[uid]
        row = {"project": uid[0], "file": uid[1]} if uid[0] else {"file": uid[1]}
        if rec["group"]:
            row["group"] = rec["group"]
        if rec.get("missing"):
            row["status"] = "missing"
            rows.append(row)
            continue
        total = rec["passed"] + rec["failed"] + rec["skipped"]
        if rec["failed"]:
            row["status"] = "failed"
        elif rec["errors"]:
            row["status"] = "error"
        elif rec["passed"]:
            row["status"] = "passed"
        elif rec["skipped"]:
            row["status"] = "skipped"
            if not rec["unrequested"]:
                _flag("unit-only-skipped")
        else:
            row["status"] = "missing"                    # a suite with no case record at all
            if not rec["unrequested"]:
                _flag("unit-missing")
        row["duration_ms"] = int(round(rec["time"] * 1000))
        if prof["cases"]:
            row["cases"] = total
        row["skipped"] = rec["skipped"]
        if rec["failed_cases"]:
            row["failed_cases"] = rec["failed_cases"][:max_failed_cases]
            if len(rec["failed_cases"]) > max_failed_cases:
                row["failed_cases_more"] = len(rec["failed_cases"]) - max_failed_cases
        if rec["excerpt"]:
            row["excerpt"] = rec["excerpt"]
        if row["status"] in ("failed", "error"):
            # T-14298: the failed tests by name — the adapter's own names win; else a case
            # profile's recorded failed case ids; else the one reader over the failure text.
            if rec["given"]:
                names = list(rec["given"])
            elif row.get("failed_cases"):
                names = list(dict.fromkeys(c["id"] for c in row["failed_cases"] if c.get("id")))
            elif any(_UNIT_TIMEOUT_RE.search(t) for t in rec["texts"]):
                names = []          # a killed unit's partial output is not its verdict
            else:
                names = _failed_test_names(["test failed: " + uid[1] + "\n" + "\n".join(rec["texts"])],
                                           timeout_marker="")
                names = names[0]["failed_tests"] if names else []
            row["failed_tests"], row["named"] = names, bool(names)
        if rec["unrequested"]:
            row["unrequested"] = True
        rows.append(row)
    judged = [r for r in rows if not r.get("unrequested")]
    if exit_code not in (0, None) and all(r["status"] == "passed" for r in judged):
        _flag("nonzero-exit-all-passed")
    return {"void": void, "units": rows}


def _adapter_read_output(path, max_bytes: int, checkpoint=None) -> "str | None":
    """ONE file an adapter invocation left behind, read WITHOUT blocking and within a size bound.
    Returns None when nothing is at `path`, and "" when something is there that is not a readable
    regular file of at most `max_bytes` — a FIFO, a device, a directory, a dangling or looping
    link, an oversize or unreadable file. Every caller reads "" as MALFORMED (it parses as
    neither report), never as absent.

    The path is project-written, so its SHAPE is not trusted: it is opened non-blocking (opening a
    FIFO for reading otherwise waits for a writer that may never come), the OPENED descriptor is
    what is examined (so the file cannot change between the check and the read), and at most
    `max_bytes` + 1 bytes are read — a file that reports no size (a pseudo-file) is bounded too.
    `checkpoint`, when given, is called before the open and before every 256 KiB read; whatever it
    raises passes through (the descriptor is closed first)."""
    import stat
    tick = checkpoint or (lambda: None)
    tick()
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        return "" if os.path.lexists(str(path)) else None     # a dangling link is not «absent»
    except OSError:
        return ""
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            return ""
        chunks, left = [], max_bytes + 1
        while left > 0:
            tick()
            chunk = os.read(fd, min(left, 1 << 18))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
        data = b"".join(chunks)
        return "" if len(data) > max_bytes else data.decode("utf-8", errors="replace")
    except OSError:
        return ""
    finally:
        os.close(fd)


def _layer_adapter_report_pass(worktree, layer: str, decl: dict, *, timeout, env=None, outer=None,
                               outer_at=None, _run_layer_command, _load_avg=None, _monotonic=None,
                               max_output_bytes: int = 16 * 1024 * 1024, first_attempt: bool = False,
                               rerun=None, sink=None, max_kept_output_chars: int = 1024 * 1024,
                               change=None, _subject_globs_would_skip=None, credit=None,
                               lane=None, one_card_candidate: bool = False, shipped=None,
                               pre_deploy=None, unit_medians=None) -> dict:
    """SPEC-1006 rules 3-4 — the REPORT-ONLY adapter pass of ONE layer: `list`, then `run`, inside
    the layer's prepared worktree, read through the layer's report profile. Returns the record that
    rides the layer's outcome row as `adapter` (registered in SPEC-0025):

      {schema: 1, mode: "report-only", profile, usable, list, list_reason?, outer?, outer_at?,
       exit?, void?, load1?, duration_ms?, units?, error?, versions?, selection?, credit?, lane?,
       partial?}
    (the caller adds `identity` or `identity_unavailable` — `_adapter_stamp_identity` — and, on a
    layer declaring `credit: shadow`, `attempt` or `attempt_unavailable`)

    `usable` is True only when `list` gave a complete inventory, no outer failure decided first and
    the report voided on nothing — the one flag the cards that let a report DECIDE key on. `list` is
    `ok` / `absent` (the runner has none — no inventory, so the rows are diagnostics) / `failed`
    (nonzero exit, a timeout, an unreadable or empty answer, another protocol `schema` than 1, a
    reported collection error, a unit that is not a canonical repo-relative path, a file declared
    twice — `list_reason` says which; the adapter path is then unusable for this run and
    `run` is not invoked) / `not-run` (an outer failure decided before it). `outer` records an outer failure (`timed-out` / `prep-failed`) and
    `outer_at` where (`prep` / `command` / `run`, or `report` — the pass's bound passed while a
    report was being read); nothing is read then, and nothing read is kept. `exit` is the `run`
    command's exit code (the first nonzero one across per-project invocations); `load1` the host
    1-minute load read just before `run` (ABSENT when unmeasurable — never a fabricated 0);
    `duration_ms` the wall of the whole pass.

    REPORT-ONLY, AND IT CANNOT FAIL A VERIFY: the caller has already taken the layer's verdict from
    its `command:` exit code; this function returns a record and raises nothing — an unexpected
    error inside the pass is recorded as `error` with `usable: false`. The whole pass shares ONE
    bound — `timeout`, the layer's own — kept as one absolute deadline: an invocation is handed
    exactly the time left, and once none is left nothing more is started (`_monotonic` is the
    clock, injectable so the bound is testable without sleeping). Every invocation gets a FRESH
    directory (so a runner that cannot start leaves no older report to read) removed afterwards.
    The runner is the injected `_run_layer_command`, under the layer's own bound and environment.

    WHAT AN INVOCATION LEAVES BEHIND IS READ WITHOUT TRUSTING ITS SHAPE. An invocation that hit the
    bound has NOTHING read. Every other output goes through `_adapter_read_output`: opened without
    blocking, a regular file of at most `max_output_bytes` or it reads as malformed — so a FIFO, a
    device or an endless file at the manifest's path can neither stall the pass nor exhaust it.

    THE DEADLINE HOLDS WHILE AN OUTPUT IS READ, not only between invocations. The pass hands its
    readers ONE checkpoint — it raises once the bound has passed — and they call it between their
    steps (every 256 KiB read, every 64 KiB parsed, every suite, every case, every 256 listed
    units or rows: `_adapter_read_output`, `_classify_adapter_report`). So a reading that would
    outlast the bound STOPS at the first step past it: `list` is then a failed list (`timed-out`),
    a `run` report records `outer: timed-out` at `report`, and no rows are kept. What cannot be
    interrupted is one such step, or one decode of a document already bounded in size.

    T-13607 (SPEC-1006 rules 4, 5, 10) — THE SAME PASS, THREE KEYWORD-ONLY EXTENSIONS. With none of
    them given the pass is the one described above, byte for byte.
      first_attempt  the pass IS the layer's first attempt (the caller reads the verdict off the
                     record with `_adapter_first_attempt`): after a usable `list` the declaration's
                     `required:` commands run in order, inside the same deadline and environment,
                     BEFORE `run`. The first one that exits nonzero ends the pass — `required:
                     {ran, failed, exit}`, `run` not invoked; one that hits the bound is an outer
                     timeout at `required`. All passing records `required: {ran}`.
      rerun          the units of a RE-RUN attempt (inventory entries: `{project, file,
                     report_id?, group?}`): `list` and `required:` are not invoked, `list` reads
                     `given`, and every `run` manifest carries `isolated: true`.
      sink           a dict the pass fills for its caller, never part of the record: `inventory`
                     (the listed units) — and, when the caller seeds the key `memberships`, that
                     answer's `{(project, file): _pre_deploy_membership(classes)}` (T-14111) —, `proc_ms` (the summed process CPU of every invocation
                     that reported one), and `invocations` — ONE entry per `required:` and `run`
                     invocation, in order: `{label, command, exit, output}`, `exit` None when it
                     hit the bound, `output` its whole captured stream. Nothing an invocation
                     printed is dropped or overwritten by a later one: a runner whose report
                     names no project is invoked once per project, and the project that failed
                     need not be the last (`_adapter_invocations_output` renders them). ONE
                     bound, stated where it applies: an invocation's stream longer than
                     `max_kept_output_chars` keeps its END (where a failing run names its
                     cause) under a first line saying how many earlier characters were not
                     kept — so what the pass holds is bounded per invocation, never silently.

    THE REPORTED VERSIONS (T-13610 — SPEC-1006 rule 8). When `list` answers and reports
    `versions` — `{name: version}` strings for the runner and any dependency tracker — the record
    carries them (project-reported, as `list` and `run` are: rule 4's LIMIT). They are an input of
    the layer's IDENTITY, which the caller writes onto this record AFTER the pass
    (`_adapter_stamp_identity`), because one of its inputs — what the layer's `sources:` hold — has
    to be read on both sides of the adapter's own execution.

    THE SHADOW SELECTION (T-13610 — SPEC-1006 rules 3, 6-9). With `change` given — the caller
    passes it for a layer declaring `selection: shadow` and for no other, together with the
    rule-16 subject judge `_subject_globs_would_skip` the ladder needs — the pass ALSO records
    `selection`: the decision of `_adapter_shadow_decision` for this change, taken after the
    report is read so that nothing it costs can starve the report. `run` was already invoked with
    the WHOLE inventory, as on every adapter-backed layer: the decision narrows nothing. Where the
    ladder reaches it, `related` is invoked ONCE, inside the same deadline (none left = `related:
    timed-out`, rung (d)); its answer is read as strictly as `list`'s, and a unit it names that
    the inventory does not hold makes it a failed answer. Then the comparison (rule 9):
    `disagreements` lists every unit the decision would have OMITTED whose row in this full run
    reads `failed` or `error` — `{file, project?, would: "omit", status}` — and `compared` says
    whether that comparison saw a complete report (`usable`); with a void report or no rows it is
    false and the list holds what the rows that were read show. No selection is recorded when an
    outer failure decided first or the pass's bound passed (nothing of such a pass is kept).
    NOTHING THE SELECTION DOES CAN COST THE REPORT, AND IT FAILS TOWARD THE FULL LAYER: `related`
    is asked after the rows are final; an exception raised while it is invoked or its answer is
    read is a FAILED `related` (rung (d), `related_reason: error: <type>`); an exception anywhere
    else in the decision or the comparison is recorded as the full layer with no rung (`reason:
    selection-error`, its cause under the selection's own `error`). In both the record keeps its
    rows and its `usable` flag, and carries no `error` key of its own.
    A RE-RUN pass and a pass whose `required:` check failed record no selection either: the
    first has no change to decide over (its caller passes none) and the second invoked no
    `run`, so there is no full run to hold the decision against.

    THE WOULD-BE CREDIT (T-13612 — SPEC-1006 rule 14). With `credit` given — the caller passes
    `_adapter_credit_basis`'s answer, with the fix's own diff on it, for a layer declaring
    `credit: shadow` and for no other — the pass ALSO records `credit`: the decision of
    `_adapter_credit_decision`, taken where the selection is and on its terms. `run` was invoked
    with the WHOLE inventory before it: the decision credits nothing in this run. Where its
    ladder reaches the `related` answer, `related` is invoked ONCE more, inside the same deadline,
    with the fix's diff (`base` = the previous attempt's recorded tree, or a commit over it;
    `changed` = the paths between that tree and this candidate's). Then the comparison (rule 9):
    `disagreements` lists every unit the decision would have CREDITED whose row in this full run
    reads `failed` or `error` — `{file, project?, would: "credit", status}` — and `compared` says
    whether that comparison saw a complete report; both are written on every credit record (a
    decision that credits nothing has none to compare). Where the layer also records a
    `selection`, its `would_credit` — which that decision leaves empty — receives the same
    would-credit units: rule 8 names them as part of the one effective record. It fails toward
    NOTHING CREDITED: an exception while `related` is invoked or read is a failed `related`
    (rung (d) — case (iv)); an exception anywhere else is `decision: void`, `reason:
    credit-error`, its cause under the credit's own `error`. The rows, the `usable` flag and the
    selection stand in both. Recorded exactly where a selection would be: not on an outer failure,
    a passed bound, a failed `required:` check or a re-run pass.

    THE LOAD-SENSITIVE LANE (T-13609 — SPEC-1006 rule 11). `lane` is the layer's declared
    load-sensitive list — a set of `(kind, project, name)` entries, `kind` being `unit` or `group`
    (`_unit_lane_set`) — or None. Where the pass has an inventory (`list`
    answered) and is not a re-run, `_adapter_lane_split` takes the listed units OUT of the batch:
    `run` is invoked for the remaining units as described above, and AFTER it once more (per
    project, where the batch is) for the listed ones, with `isolated: true` on the manifest — one
    at a time. Both invocations share the pass's one deadline, are read through the same profile
    and feed the same `units` rows, so a listed unit's row decides exactly as any other row does;
    its row carries `lane: true`. The record then carries `lane: {units, unmatched}` — how many
    units ran in the lane and how many listed entries name no unit of this inventory. With no
    listed entry for the layer nothing changes: no key, no second invocation.

    A DECIDING SELECTION (T-13907 — SPEC-1030 rules 2, 4, 5). Only a layer whose declaration reads
    `selection: deciding` (SPEC-1030 rule 1) reaches this paragraph; under `off` and `shadow` the
    pass is the one described above, byte for byte. With such a declaration, on a pass that is
    not a re-run:
      • THE `required:` CHECKS RUN ON EVERY FIRST ATTEMPT — after `list`, whatever it answered
        (an unusable or absent `list` included) and whatever is then selected, a run of no unit
        included. A failing one fails the layer where it stands, and so does a fault of the pass
        before they had all run (`required: {ran: n, failed: n, exit: None}` — `n` checks had
        passed and check `n` did not complete): on such a layer the full `command:` never
        decides in place of a check that did not pass.
      • THE DECISION IS TAKEN BEFORE `run` and recorded as `selection` with the mode `deciding`
        (`_adapter_deciding_record`) on EVERY exit of the pass — an outer failure, a failed
        `required:` check and a fault included, each under its own reason. `one_card_candidate`
        says whether this run is the candidate run of ONE card (the Tests-stage run, the land's
        candidate leg of one member). False, the default — or no `change` — the ladder is not
        asked and nothing is narrowed (the pinned last-green leg, a batch's combined candidate,
        the attribution re-run). True: the rule-6 ladder (`_adapter_shadow_decision`, unchanged)
        decides and `_adapter_run_plan` — the ONE place that names a run's unit set — turns its
        answer into the units `run` is invoked with. Rung (f) runs the selected units and no
        other (a selection naming none invokes no `run`); every other answer, and a rung-(f)
        answer naming every unit, runs the whole inventory. `decision` reads `units` only on a
        narrowed run.
      • WITH NO INVENTORY on a first attempt (`list` absent or unusable) `run` is not invoked:
        the layer's full `command:` decides.
      • A NARROWED run carries `partial` (`_adapter_partial_record`), written when the pass ENDS
        from what it did: `ran` holds the units of the `run` invocations that were STARTED,
        `not_reached` the selected units whose invocation never started (the bound passed
        first), `left_out` the units the selection left out. Every other run carries no such key.
    The lane split, the report check and the per-unit rows apply to the units requested: a unit
    left out has no row, and on a narrowed run `lane.units` counts the listed units whose
    invocation was started. A fault while the decision is taken is the full layer (`reason:
    selection-error`). No comparison is recorded — there is no full run to compare with — and a
    `credit: shadow` basis is not read on a narrowed run. A re-run pass takes no decision.

    A DECIDING CREDIT (T-13909 — SPEC-1030 rules 3, 4, 5). With a declaration that reads
    `credit: deciding`, on a pass that is
    not a re-run, the two rules of the first two bullets above hold as for a deciding selection
    (the `required:` checks on every first attempt; no `run` ahead of the full `command:` where
    there is no inventory), and:
      • THE `credit` RECORD carries the mode `deciding` on EVERY exit of the pass
        (`_adapter_deciding_credit_record`). It is decided BEFORE `run`, where the selection is.
        Nothing is credited, each under its own reason, when the run is not the candidate run of
        one card or has no change; when the caller handed no basis; when the layer's selection is
        `shadow`; and when the basis (`credit` — `_adapter_credit_basis(deciding=True)` with the
        fix's diff) already credits nothing: no previous attempt, an attempt that passed as a
        whole, and the rule-14 cases (i)-(iii).
      • THE PRIORITY. Otherwise the rule-6 ladder is asked for the card's WHOLE change (`change`),
        whatever the layer's `selection:`. Any answer but rung (f) credits nothing — `void` /
        `card-full-layer`, with the ladder's `rung` and its reason as `ladder_reason` — and the
        whole inventory runs. ONE exception (T-13949): where the fix's diff names NO path — this
        run's tree is the one the previous attempt recorded — and the answer is not rung (a), the
        decision goes on as on rung (f) below, over that empty diff.
      • ON RUNG (f) `_adapter_credit_decision` decides over the fix's diff (`related` is invoked
        once more for it, inside the same deadline; a rung (a)-(e) there is case (iv)), and
        `_adapter_run_plan` turns the selection — where it acts — and that decision into the
        units `run` is invoked with: of the units the run needs, the ones the decision would
        re-run. The others are CREDITED: not requested, no row in `units`, named in
        `partial.credited` beside `partial.previous`. A run that credits is a narrowed run in
        every respect above, a run that requests no unit included.
    A fault while the credit decision is taken credits nothing (`credit-error`); a fault of the
    ladder is `selection-error` on both records.

    A SHIPPED DECISION (T-13973 — SPEC-1032 rule 4). `shipped` is the decision the HOST took for
    this layer, carried to a box that runs the pass over the same tree (`_adapter_shipped_decision`
    builds it from the host's own pass, `worktree._consumer_zero_probe_guard(plan_out=...)`):
    `{selection, credit, units, left_out, credited?, previous?}` — the two records as the host wrote them and
    `_adapter_run_plan`'s answer. Given one, on a layer that reads a deciding mode and a pass that
    is not a re-run, the decision is NOT taken again: no ladder, no `related`, no credit decision
    and no previous attempt is read. The records are the host's, copied; `units` None runs the
    whole inventory; otherwise the units run are this pass's own `list` entries named by
    `units`, and the rest is the host's `left_out` / `credited`, recorded through
    `_adapter_partial_record` exactly as a local narrowed run. A plan this pass cannot follow —
    a malformed `shipped`, no inventory, a narrowed plan whose run / left-out / credited units are
    not, each exactly once, the units this pass's `list` names, a narrowed plan without the host's
    record for each deciding mode the layer reads, or credits on a layer that reads no deciding
    credit or with no previous-attempt reference — narrows nothing: the whole
    inventory runs, each deciding record reads `void` / `shipped-plan-mismatch` (toward MORE
    testing, never fewer). The host's pass fills the caller's `sink["plan"]` with
    the plan it took, which is where a shipped decision comes from.

    THE PRE-DEPLOY EXCLUSION (T-14104 — SPEC-1042 rules 1-2, `proposed`). `pre_deploy` is the PARSED
    pre-deploy declaration (`_pre_deploy_declaration`'s `{classes, layers}`, plus `change` — `{paths,
    edge}`), handed by a land's candidate leg or a Stage-6 run only; None, the default, changes
    nothing, byte for byte. Given one, `list` units' `classes:` are read, and on a pass that is not a
    re-run `_pre_deploy_exclusion` is applied LAST — after the deciding selection and credit — to
    the units `run` is invoked with: a removed unit has no row, the run is a narrowed one
    (`partial`, so a pass reads `passed-partial`), and the record's `pre_deploy` names each removed
    unit with its class, or says why the layer ran whole. Its `run: true` (T-14105) is the deploy's
    pre-deploy run: nothing is removed and the record names every pre-deploy unit with its class."""
    import posixpath
    import shutil
    import tempfile
    rec = {"schema": 1, "mode": "report-only", "profile": decl["report_profile"], "usable": False,
           "list": "given" if rerun is not None else ("absent" if "list" not in decl else "not-run")}
    # T-13907 (SPEC-1030 rule 5): EVERY run of a layer whose parsed declaration reads `selection:
    # deciding` records the mode — `_no_decision` is that record where no decision was taken.
    deciding = decl.get("selection") == "deciding" and rerun is None
    # T-13909 (SPEC-1030 rules 3, 5): ... and so does every run of one that reads `credit: deciding`.
    crediting = decl.get("credit") == "deciding" and rerun is None

    def _no_decision(why):
        return _adapter_deciding_record(None, why=why,
                                        related="absent" if "related" not in decl else "not-run")

    def _no_credit(why):
        return _adapter_deciding_credit_record(None, why=why)

    if outer:
        rec.update({"outer": outer, "outer_at": outer_at})
        if deciding:
            rec["selection"] = _no_decision("outer-failure")
        if crediting:
            rec["credit"] = _no_credit("outer-failure")
        return rec
    memberships: dict = {}  # T-14104: `list` units' `classes:` — read only when `pre_deploy` is given
    planned: dict = {}      # T-13907: `narrowed` (the run plan, when it leaves units out) and the
    launched: list = []     # units of every `run` invocation that was STARTED
    checks_passed: list = []    # ... and the index of every `required:` check that ran and passed
    prof = _ADAPTER_REPORT_PROFILES[decl["report_profile"]]
    clock = _monotonic or time.monotonic
    t0 = clock()
    # ONE absolute deadline for the WHOLE pass. Each invocation is handed exactly what is left of
    # it, and an invocation that would start at or past it is not started.
    deadline = None if timeout is None else t0 + float(timeout)
    scratch = None
    try:
        scratch = Path(tempfile.mkdtemp(prefix="yitc-adapter-"))
        counter = [0]

        def _note(command, got, label=None):
            """Hand the caller's `sink` what one invocation cost and — for a `required:` or `run`
            invocation, which carries a `label` — what it printed, APPENDED as its own entry.
            `got` is the runner's own tuple, read by position."""
            if sink is None:
                return
            if len(got) > 1 and isinstance(got[1], (int, float)) and not isinstance(got[1], bool):
                sink["proc_ms"] = sink.get("proc_ms", 0) + got[1]
            if label is not None:
                printed = got[2] if len(got) > 2 else None
                keep = max(0, int(max_kept_output_chars))
                if isinstance(printed, str) and len(printed) > keep:
                    printed = (f"[… {len(printed) - keep} earlier character(s) of this invocation's "
                               f"output not kept]\n" + printed[len(printed) - keep:])
                sink.setdefault("invocations", []).append({
                    "label": label, "command": command,
                    "exit": None if got[0] is None else got[0].returncode, "output": printed})

        def _invoke(action, units=None, project=None, more=None, in_lane=False):
            """One adapter invocation in a fresh directory. Returns (run result | None on the
            bound, the directory, the invocation's start); the result is None as well when the
            pass's deadline had already passed, in which case nothing is started."""
            left = None if deadline is None else deadline - clock()
            if left is not None and left <= 0:
                return None, None, None
            counter[0] += 1
            box = scratch / f"{counter[0]}-{action}"
            box.mkdir()
            manifest = {"schema": 1, "run_id": f"{os.getpid()}-{counter[0]}", "layer": layer,
                        "action": action, "profile": decl["report_profile"], "project": project,
                        "units": (units if action != "run" else      # T-14206: `median_ms` / `runs`
                                  _adapter_units_with_medians(layer, units, project, unit_medians)),
                        "output": str(box / "list.json"),
                        "report": str(box / "report.xml"),
                        "second_report": str(box / "report.json") if prof["second_report"] else None,
                        **(more or {})}
            if rerun is not None or in_lane:
                manifest["isolated"] = True                # T-13607: these units, one at a time
            (box / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            started = datetime.datetime.now(datetime.timezone.utc)
            run_env = {**(env if env is not None else os.environ),
                       _VERIFY_ADAPTER_MANIFEST_ENV: str(box / "manifest.json")}
            got = _run_layer_command(decl[action], worktree, left, run_env)
            _note(decl[action], got, label=(None if action != "run" else
                                            (f"run [project {project}]" if project else "run")
                                            + (" [load-sensitive lane]" if in_lane else "")))
            return got[0], box, started

        def _checkpoint():
            """Raise once the pass's deadline has PASSED (AT it, `_invoke` starts nothing more).
            Handed to every reader, which calls it between its steps."""
            if deadline is not None and clock() > deadline:
                raise _AdapterPassDeadline()

        def _read_list_answer(box):
            """`list`'s answer as (units, None) — or (None, why it is not an inventory)."""
            answer = _adapter_read_output(box / "list.json", max_output_bytes, _checkpoint)
            try:
                doc = json.loads(answer) if answer is not None else None
            except (ValueError, RecursionError):
                doc = None
            _checkpoint()
            raw_units = doc.get("units") if isinstance(doc, dict) else None
            errors = doc.get("errors", []) if isinstance(doc, dict) else None
            if not (isinstance(raw_units, list) and isinstance(errors, list)):
                return None, "malformed-answer"
            if isinstance(doc.get("schema"), bool) or doc.get("schema") != 1:
                return None, "unsupported-schema"          # the protocol this reader speaks is 1
            if errors:
                return None, "collection-error"
            if not raw_units:
                return None, "empty"
            # T-13610 (rule 8): the OPTIONAL `versions` — a mapping of at most 16 names to version
            # strings, every one a non-empty string of at most 100 characters. Anything else is a
            # malformed answer: an identity must not rest on a value this reader had to guess at.
            told = doc.get("versions", {})
            if not (isinstance(told, dict) and len(told) <= 16 and all(
                    isinstance(k, str) and isinstance(v, str) and 0 < len(k) <= 100 and 0 < len(v) <= 100
                    for k, v in told.items())):
                return None, "malformed-answer"
            listed, files = [], {}
            for n, u in enumerate(raw_units):
                if n % 256 == 0:
                    _checkpoint()
                ok = isinstance(u, dict) and isinstance(u.get("file"), str) and u["file"].strip() \
                    and all(isinstance(u.get(k, ""), str) for k in ("project", "report_id", "group"))
                if not ok:
                    return None, "malformed-answer"
                unit = {"project": u.get("project") or "", "file": u["file"]}
                # A unit is a REPO-RELATIVE file in canonical form: not absolute, no
                # parent-directory component, nothing a normalisation would rewrite.
                if unit["file"].startswith("/") or posixpath.normpath(unit["file"]) != unit["file"] \
                        or unit["file"] in (".", "..") or unit["file"].startswith("../"):
                    return None, "unit-not-repo-relative"
                for k in ("report_id", "group"):
                    if u.get(k):
                        unit[k] = u[k]
                if pre_deploy is not None or (sink is not None and "memberships" in sink):   # T-14104/T-14111: membership, beside the unit — never in it
                    memberships[(unit["project"], unit["file"])] = _pre_deploy_membership(u.get("classes"))
                if unit["project"] in files.setdefault(unit["file"], set()):
                    return None, "duplicate-unit"
                if files[unit["file"]] and not prof["project_in_report"]:
                    return None, "file-in-two-projects"
                files[unit["file"]].add(unit["project"])
                listed.append(unit)
            if told:
                rec["versions"] = dict(told)
            return listed, None

        def _ask_related(inventory, chg):
            """ONE `related` invocation over the change `chg` → (state, why, {(project, file)}):
            `ok` with the units reached, else `timed-out` / `failed` with the reason. The answer
            is read as `list`'s is: every node on the path is type-checked, and nothing is
            defaulted or skipped."""
            try:
                res, box, _started = _invoke("related", inventory, None, {
                    "base": chg.get("base"), "changed": _related_changed_paths(chg.get("paths") or ())})
                if res is None:
                    return "timed-out", None, None
                if res.returncode != 0:
                    return "failed", f"exit {res.returncode}", None
                answer = _adapter_read_output(box / "list.json", max_output_bytes, _checkpoint)
                try:
                    doc = json.loads(answer) if answer is not None else None
                except (ValueError, RecursionError):
                    doc = None
                _checkpoint()
                raw_units = doc.get("units") if isinstance(doc, dict) else None
                errors = doc.get("errors", []) if isinstance(doc, dict) else None
                if not (isinstance(raw_units, list) and isinstance(errors, list)):
                    return "failed", "malformed-answer", None
                if isinstance(doc.get("schema"), bool) or doc.get("schema") != 1:
                    return "failed", "unsupported-schema", None
                if errors:
                    return "failed", "collection-error", None
                known = {(u["project"], u["file"]) for u in inventory}
                reached = set()
                for n, u in enumerate(raw_units):
                    if n % 256 == 0:
                        _checkpoint()
                    if not (isinstance(u, dict) and isinstance(u.get("file"), str)
                            and isinstance(u.get("project", ""), str)):
                        return "failed", "malformed-answer", None
                    key = (u.get("project", ""), u["file"])
                    if key not in known:
                        return "failed", "unit-not-listed", None
                    reached.add(key)
                return "ok", None, reached
            except _AdapterPassDeadline:
                return "timed-out", None, None
            except Exception as e:                         # a runner that cannot start, an unreadable box
                return "failed", f"error: {type(e).__name__}", None

        def _select(inventory, rows):
            """Record the shadow selection (`change` given) and compare it with the full run. It
            cannot raise: a fault anywhere in it leaves the record's rows and `usable` flag as
            they are and is recorded as the full layer, no rung, `reason: selection-error`."""
            if change is None or decl.get("selection") == "deciding" \
                    or (crediting and decl.get("selection") != "shadow"):   # T-13909: handed for the credit alone
                return
            try:
                _select_into_record(inventory, rows)
            except Exception as e:
                # A selection already recorded stands (the fault came after it); otherwise the
                # fault IS the record — toward the full layer, with its cause.
                rec.setdefault("selection", {
                    "schema": 1, "mode": "shadow", "decision": "full", "rung": None,
                    "reason": "selection-error", "related": "not-run", "would_credit": [],
                    "compared": False, "disagreements": [], "error": f"{type(e).__name__}: {e}"[:300]})

        def _still_a_file(path) -> bool:
            try:
                full = os.path.join(str(worktree), path)
                return os.path.isfile(full) or os.path.islink(full)
            except (OSError, ValueError):                  # a name the file system cannot hold
                return False

        def _select_into_record(inventory, rows):
            sel = _adapter_shadow_decision(
                decl, change, inventory, lambda: _ask_related(inventory, change), exists=_still_a_file,
                _subject_globs_would_skip=_subject_globs_would_skip)
            omitted = {(u.get("project") or "", u["file"]) for u in sel.get("would_omit") or ()}
            sel["compared"] = bool(rec.get("usable"))
            sel["disagreements"] = [
                {"file": row["file"], **({"project": row["project"]} if row.get("project") else {}),
                 "would": "omit", "status": row["status"]}
                for row in rows or () if row.get("status") in ("failed", "error")
                and (row.get("project") or "", row["file"]) in omitted]
            rec["selection"] = sel
            told = (f"rung ({sel['rung']})" if sel["rung"] else "no rung") + f" — {sel['reason']}: "
            if sel["decision"] == "units":
                told += (f"would run {len(sel['would_run'])} of {len(inventory)} unit(s), would omit "
                         f"{len(sel['would_omit'])}")
            else:
                told += "the full layer"
            if sel["disagreements"]:
                told += (f"; {len(sel['disagreements'])} DISAGREEMENT(S) — would-omit unit(s) that "
                         f"FAILED in this full run: "
                         + ", ".join(d["file"] for d in sel["disagreements"][:5]))
            print(f"land(consumer): verify layer {layer!r} shadow selection (recorded, never acted "
                  f"on — the full layer ran): {told}")

        def _credit(inventory, rows):
            """Record the would-be credit (`credit` given) and compare it with the full run. It
            cannot raise: a fault anywhere in it leaves the rows, the `usable` flag and the
            selection as they are and is recorded as `void` / `credit-error` — nothing credited."""
            if credit is None or "narrowed" in planned or decl.get("credit") == "deciding":
                return                  # T-13909: a deciding credit was decided before `run` (`_decide`)
            try:
                got = _adapter_credit_decision(
                    decl, credit, inventory, lambda: _ask_related(inventory, credit["change"]),
                    exists=_still_a_file, _subject_globs_would_skip=_subject_globs_would_skip)
                credited = {(u.get("project") or "", u["file"]) for u in got.get("would_credit") or ()}
                got["compared"] = got["decision"] == "units" and bool(rec.get("usable"))
                got["disagreements"] = [
                    {"file": row["file"], **({"project": row["project"]} if row.get("project") else {}),
                     "would": "credit", "status": row["status"]}
                    for row in rows or () if row.get("status") in ("failed", "error")
                    and (row.get("project") or "", row["file"]) in credited]
                rec["credit"] = got
                if got["decision"] == "units" and isinstance(rec.get("selection"), dict):
                    rec["selection"]["would_credit"] = [dict(u) for u in got["would_credit"]]
                if got["decision"] == "units":
                    told = (f"would re-run {len(got['would_rerun'])} of {len(inventory)} unit(s), would "
                            f"credit {len(got['would_credit'])} with the pass of the previous attempt")
                elif got["decision"] == "void":
                    told = (f"would credit NOTHING — {got['reason']}"
                            + (f" (rung ({got['rung']}), {got.get('ladder_reason')})" if got.get("rung")
                               else f" ({got['ladder_reason']})" if got.get("ladder_reason") else ""))
                else:
                    told = f"not a fix attempt — {got['reason']}"
                if got["disagreements"]:
                    told += (f"; {len(got['disagreements'])} DISAGREEMENT(S) — would-credit unit(s) that "
                             f"FAILED in this full run: "
                             + ", ".join(d["file"] for d in got["disagreements"][:5]))
                print(f"land(consumer): verify layer {layer!r} shadow credit (recorded, never acted on "
                      f"— the full layer ran): {told}")
            except Exception as e:
                rec.setdefault("credit", {
                    "schema": 1, "mode": "shadow", "decision": "void", "reason": "credit-error",
                    "compared": False, "disagreements": [], "error": f"{type(e).__name__}: {e}"[:300]})

        def _follow_shipped(inventory):
            """T-13973 (SPEC-1032 rule 4) — follow the decision the host shipped for this layer
            (see the docstring's last paragraph). Returns what `_decide` returns: the inventory
            entries `run` is to be invoked with, or None for the whole inventory."""
            got = shipped if isinstance(shipped, dict) else {}
            want = got.get("units")
            # T-13994 (SPEC-1032 rule 5) — the host's `list` named units for this layer and this
            # pass's `list` answered with NONE (`list_reason: empty`, an answer the reader above
            # already refuses as an inventory): the run here cannot verify what the plan was taken
            # over. The record says so; the host names the layer on the Stage-6 row and the land
            # takes no verdict for it from this pass. Whatever follows below runs exactly as before.
            plan_listed = got.get("listed")
            if isinstance(plan_listed, int) and not isinstance(plan_listed, bool) and plan_listed > 0 \
                    and rec.get("list") == "failed" and rec.get("list_reason") == "empty":
                rec["listed_none"] = {"plan_listed": plan_listed}
                print(f"land(consumer): verify layer {layer!r} lists NO unit here, while the shipped "
                      f"plan was taken over {plan_listed} listed unit(s) — the layer is named on the "
                      f"Stage-6 row and the land takes no verdict for it from this pass (SPEC-1032 rule 5)")

            def _keys(units):
                if not (isinstance(units, list) and all(isinstance(u, dict) and isinstance(u.get("file"), str)
                                                        for u in units)):
                    return None
                return [(u.get("project") or "", u["file"]) for u in units]

            keys, out_keys, cred_keys = _keys(want), _keys(got.get("left_out") or []), _keys(got.get("credited") or [])
            listed = [(u.get("project") or "", u["file"]) for u in inventory or ()]
            # A narrowed plan must ACCOUNT for every unit this pass's `list` names — run, left out or
            # credited, each exactly once — or a unit the host never saw would neither run nor be
            # recorded (toward MORE testing: such a plan narrows nothing).
            accounted = None if None in (keys, out_keys, cred_keys) else keys + out_keys + cred_keys
            # ...and a narrowed plan carries the host's record for every deciding mode it acts under
            # (the record says WHY it narrowed), and a credit only where the layer credits, with the
            # previous attempt it credits from.
            records = (not deciding or isinstance(got.get("selection"), dict)) \
                and (not crediting or isinstance(got.get("credit"), dict)) \
                and (not cred_keys or (crediting and isinstance(got.get("previous"), dict)))
            follows = isinstance(shipped, dict) and "units" in got and out_keys is not None \
                and cred_keys is not None and (want is None or (
                    inventory is not None and accounted is not None and records
                    and len(accounted) == len(set(accounted)) and set(accounted) == set(listed)))
            if not follows:
                if deciding:
                    rec["selection"] = _no_decision("shipped-plan-mismatch")
                if crediting:
                    rec["credit"] = _no_credit("shipped-plan-mismatch")
                print(f"land(consumer): verify layer {layer!r} shipped plan cannot be followed here "
                      f"(shipped-plan-mismatch) — nothing is narrowed, the whole layer runs")
                return None
            if deciding:
                rec["selection"] = (json.loads(json.dumps(got["selection"])) if isinstance(got.get("selection"), dict)
                                    else _no_decision("shipped-plan-mismatch"))
            if crediting:
                rec["credit"] = (json.loads(json.dumps(got["credit"])) if isinstance(got.get("credit"), dict)
                                 else _no_credit("shipped-plan-mismatch"))
            if want is None:
                print(f"land(consumer): verify layer {layer!r} shipped plan (decided on the host): "
                      f"nothing is narrowed")
                return None
            chosen = set(keys)
            to_run = [u for u in inventory if (u.get("project") or "", u["file"]) in chosen]
            plan = {"units": to_run, "left_out": [dict(u) for u in got.get("left_out") or ()]}
            if got.get("credited"):
                plan.update({"credited": [dict(u) for u in got["credited"]], "previous": dict(got["previous"])})
            planned["narrowed"] = {"inventory": inventory, **plan}
            print(f"land(consumer): verify layer {layer!r} shipped plan (decided on the host): a PARTIAL "
                  f"run — {len(to_run)} of {len(inventory)} unit(s) requested, {len(plan['left_out'])} "
                  f"left out, {len(plan.get('credited') or ())} credited, none selected here")
            return to_run

        def _decide(inventory):
            """T-13907 (SPEC-1030 rules 2, 5) — a DECIDING selection, taken BEFORE `run`. Records
            `selection` and returns the inventory entries `run` is to be invoked with, or None
            for the whole inventory. It cannot raise: a fault anywhere in it is the full layer,
            no rung, `reason: selection-error`."""
            if not (deciding or crediting):
                return None
            if shipped is not None:
                return _follow_shipped(inventory)     # T-13973: the host decided; nothing is selected here
            ladder, asked = None, []

            def _credit_line():
                got = rec.get("credit") or {}
                print(f"land(consumer): verify layer {layer!r} deciding credit: nothing is credited "
                      f"({got.get('decision')} — {got.get('reason')})")

            basis = None    # T-13909: the previous attempt's reading, where it can be credited from
            try:
                if not (one_card_candidate and change is not None):
                    why = "not-one-card-candidate" if not one_card_candidate else "no-change"
                    if deciding:
                        rec["selection"] = _no_decision(why)
                        print(f"land(consumer): verify layer {layer!r} deciding selection not applied "
                              f"({rec['selection']['reason']}) — nothing is narrowed")
                    if crediting:
                        rec["credit"] = _no_credit(why)
                        _credit_line()
                    return None
                if crediting:
                    # What the previous attempt's record allows is known before the ladder is asked.
                    if decl.get("selection") == "shadow":
                        rec["credit"] = _no_credit("selection-shadow")
                    elif not (isinstance(credit, dict) and isinstance(credit.get("record"), dict)):
                        rec["credit"] = _no_credit("no-basis")
                    elif not (isinstance(credit.get("units"), dict) and isinstance(credit.get("change"), dict)):
                        rec["credit"] = _adapter_deciding_credit_record(credit["record"])
                    else:
                        basis = credit
                if not deciding and basis is None:
                    _credit_line()      # nothing can be credited and no selection acts:
                    return None         # the ladder is not asked and the whole inventory runs
                ladder = _adapter_shadow_decision(
                    decl, change, inventory,
                    lambda: (asked.append(1), _ask_related(inventory, change))[1],
                    exists=_still_a_file, _subject_globs_would_skip=_subject_globs_would_skip)
                got = None
                # T-13949: on the very tree the previous attempt recorded (the fix's diff names no
                # path) a layer that PASSED WHOLE there — every unit its record holds passed — is
                # credited whatever the card reaches (SPEC-1030 rule 3's one exception); never on
                # rung (a), a change to the verify contract itself, which never becomes a partial
                # run (rule 2). A layer with a failed unit keeps the card-full-layer answer.
                same_tree = basis is not None and basis["change"].get("paths") == [] \
                    and ladder["rung"] != "a" and bool(basis.get("units")) \
                    and all(v == "passed" for v in basis["units"].values())
                if basis is not None and ladder["decision"] != "units" and not same_tree:
                    # THE PRIORITY (SPEC-1030 rule 3): a full-layer answer for the card's own
                    # change credits nothing, whatever the fix's diff alone would allow.
                    rec["credit"] = _adapter_deciding_credit_record(
                        {**basis["record"], "decision": "void", "reason": "card-full-layer",
                         "rung": ladder["rung"], "ladder_reason": ladder["reason"]})
                elif basis is not None:
                    try:
                        got = _adapter_credit_decision(
                            decl, basis, inventory, lambda: _ask_related(inventory, basis["change"]),
                            exists=_still_a_file, _subject_globs_would_skip=_subject_globs_would_skip)
                    except Exception as e:                 # toward nothing credited
                        got = None
                        rec["credit"] = {**_no_credit("credit-error"), "error": f"{type(e).__name__}: {e}"[:300]}
                plan = _adapter_run_plan(inventory, ladder if deciding else None, got)
                if sink is not None:
                    sink["plan"] = plan             # T-13973: the plan this run took, for a box to follow
                if got is not None:
                    rec["credit"] = _adapter_deciding_credit_record(got, acted=bool(plan.get("credited")))
                sel = _adapter_deciding_record(ladder, narrowed=bool(plan["left_out"]))
            except Exception as e:
                planned.clear()
                if crediting and (basis is not None or "credit" not in rec):
                    rec["credit"] = {**_no_credit("selection-error"), "error": f"{type(e).__name__}: {e}"[:300]}
                    _credit_line()
                if not deciding:
                    return None
                sel = {**_no_decision("selection-error"), "error": f"{type(e).__name__}: {e}"[:300]}
                if isinstance(ladder, dict):
                    sel["related"] = ladder["related"]     # the ladder had answered: its own word
                elif asked:
                    del sel["related"]                     # asked, and what it answered is not known
                rec["selection"] = sel
                print(f"land(consumer): verify layer {layer!r} deciding selection could not be taken "
                      f"({type(e).__name__}) — nothing is narrowed")
                return None
            if plan["units"] is not None:
                planned["narrowed"] = {"inventory": inventory, **plan}
            if deciding:
                rec["selection"] = sel
                told = (f"rung ({sel['rung']})" if sel["rung"] else "no rung") + f" — {sel['reason']}: "
                if plan["left_out"]:
                    told += (f"a PARTIAL run — {len(plan['units'])} of {len(inventory)} unit(s) "
                             f"requested, {len(plan['left_out'])} left out and NOT run")
                else:
                    told += "nothing is narrowed"
                print(f"land(consumer): verify layer {layer!r} deciding selection: {told}")
            if crediting and plan.get("credited"):
                was = plan["previous"]
                print(f"land(consumer): verify layer {layer!r} deciding credit: a PARTIAL run — "
                      f"{len(plan['credited'])} of {len(inventory)} unit(s) CREDITED with their pass in "
                      f"the previous attempt ({was.get('type')} {was.get('ts')}) and NOT run, "
                      f"{len(plan['units'])} requested")
            elif crediting:
                _credit_line()
            return plan["units"]

        units = None
        _given = ((pre_deploy.get("inventories") or {}).get(layer)
                  if pre_deploy is not None and rerun is None and isinstance(pre_deploy.get("inventories"), dict)
                  else None)
        if rerun is not None:
            units = list(rerun)                            # T-13607: the inventory is the first attempt's
        elif "list" in decl and isinstance(_given, dict):
            # T-14211 (SPEC-1051 rules 2-3): the run's decision over every layer's inventory — the skip
            # set's closure, the union's allocation — was taken on THIS answer, read before any layer
            # ran (`_pre_deploy_inventories`); the layer executes exactly it, so the decision and the
            # execution share one inventory and `list` is not asked a second time.
            units = list(_given["units"])
            memberships.update(_given.get("memberships") or {})
            if isinstance(_given.get("versions"), dict):
                rec["versions"] = dict(_given["versions"])
            rec["list"] = "ok"
            if sink is not None:
                sink["inventory"] = units
                if "memberships" in sink:
                    sink["memberships"] = memberships
        elif "list" in decl:
            res, box, _started = _invoke("list")
            reason = None
            if res is None:
                reason = "timed-out"                       # nothing this invocation left is read
            elif res.returncode != 0:
                reason = f"exit {res.returncode}"
            else:
                try:
                    units, reason = _read_list_answer(box)
                except _AdapterPassDeadline:
                    units, reason = None, "timed-out"      # the bound passed while the answer was read
            if reason:
                rec["list"] = "failed"
                rec["list_reason"] = reason
                tail = ((res.stdout or "") + (res.stderr or ""))[-300:].strip() if res is not None else ""
                print(f"land(consumer): verify layer {layer!r} adapter `list` is unusable for this run "
                      f"({reason}) — no per-unit report; the layer's verdict is its `command:` exit code"
                      + (f"\n{tail}" if tail else ""))
                if pre_deploy is not None and rerun is None:    # T-14104: the layer runs whole
                    rec["pre_deploy"] = {"applied": False, "reason": "list-unanswered"}
                    if isinstance(pre_deploy.get("union"), dict):
                        # T-14211: with no inventory the run cannot tell which of this layer's units
                        # another layer ran — the layer runs whole and the row says the union could not
                        # be kept for it (a `command:`-only layer is the same case, SPEC-1051 rule 3).
                        rec["pre_deploy_union"] = {"list_unanswered": True}
                if not ((deciding or crediting) and first_attempt):
                    _decide(None)
                    _select(None, None)
                    _credit(None, None)
                    return rec
                # T-13907 (SPEC-1030 rule 4): a deciding layer's first attempt goes on to its
                # `required:` checks — they run whatever `list` answered.
            else:
                rec["list"] = "ok"
                if sink is not None:
                    sink["inventory"] = units
                    if "memberships" in sink:              # T-14111: asked by the weekly reading only
                        sink["memberships"] = memberships
        if first_attempt and rerun is None and decl.get("required") \
                and (units is not None or deciding or crediting):
            # T-13607 (SPEC-1006 rule 5): the layer's mandatory non-test checks. They run on every
            # first attempt the adapter's `run` stands in for the full `command:`, and a failing
            # one fails the layer where it stands — `run` is not invoked and nothing re-runs it.
            for j, check in enumerate(decl["required"]):
                left = None if deadline is None else deadline - clock()
                got = (None,) if left is not None and left <= 0 else \
                    _run_layer_command(check, worktree, left, env)
                _note(check, got, label=f"required[{j}]")
                if got[0] is None:
                    rec.update({"outer": "timed-out", "outer_at": "required"})
                    print(f"land(consumer): verify layer {layer!r} `required:` check {j + 1} hit the "
                          f"layer's bound ({timeout}s) — the layer fails; no report is read")
                    if deciding:        # T-13907: the layer failed before any decision
                        rec["selection"] = _no_decision("outer-failure")
                    if crediting:
                        rec["credit"] = _no_credit("outer-failure")
                    return rec
                if got[0].returncode != 0:
                    rec["required"] = {"ran": j + 1, "failed": j, "exit": got[0].returncode}
                    print(f"land(consumer): verify layer {layer!r} `required:` check {j + 1} FAILED "
                          f"(exit {got[0].returncode}) — the layer fails; `run` is not invoked and "
                          f"nothing re-runs a required check (SPEC-1035 rule 5)")
                    if deciding:        # T-13907: the layer failed before any decision
                        rec["selection"] = _no_decision("required-failed")
                    if crediting:
                        rec["credit"] = _no_credit("required-failed")
                    return rec
                checks_passed.append(j)
            rec["required"] = {"ran": len(decl["required"])}
        # T-14211 (SPEC-1051 rule 2): the LISTED order's skip set leaves the inventory BEFORE anything is
        # selected — the deciding selection, the credit and the lane read what is left; the record names
        # what left (`pre_deploy_skip`), and the run is partial. Never on a re-run or the deploy's run.
        _skipped: list = []
        _whole_inventory = units
        if pre_deploy is not None and rerun is None and units is not None \
                and isinstance(pre_deploy.get("skip"), dict) and not pre_deploy.get("run"):
            units, _skipped, _held = _pre_deploy_skip_units(units, pre_deploy["skip"])
            if _skipped or _held:
                rec["pre_deploy_skip"] = {"applied": bool(_skipped), "removed": _skipped,
                                          **({"held_for_group": _held} if _held else {})}
            if _skipped:
                print(f"land(consumer): verify layer {layer!r} pre-deploy skip set: {len(_skipped)} listed "
                      f"unit(s) NOT run here, before selection ("
                      + ", ".join(f"{u['file']} [{u['class']}]" for u in _skipped[:5])
                      + ("" if len(_skipped) <= 5 else f" (+{len(_skipped) - 5} more)")
                      + ") — the deploy's pre-deploy run runs them (SPEC-1051 rule 2)")
        # T-13907 (SPEC-1030 rule 2): the units THIS run executes — None = the whole inventory.
        to_run = _decide(units)
        if _skipped:
            if to_run is None:
                to_run = list(units)
            if "narrowed" not in planned:
                planned["narrowed"] = {"inventory": _whole_inventory, "units": to_run, "left_out": []}
        if pre_deploy is not None and rerun is None and "pre_deploy" not in rec:
            # T-14104 (SPEC-1042 rule 2): the pre-deploy exclusion, LAST — over what the run needs now.
            # T-14211: on a land or Stage-6 run, only the classes reading adapter `classes:` (the
            # fallback order); the deploy's run names the listed classes' units too (`listed`).
            _run = bool(pre_deploy.get("run"))
            to_run, _pd = _pre_deploy_exclusion(
                units, to_run, memberships,
                [c for c in pre_deploy.get("classes") or ()
                 if _run or c not in (pre_deploy.get("listed_classes") or ())], decl=decl,
                change=pre_deploy.get("change"), first_attempt=first_attempt,
                run=_run,                                  # T-14105: the deploy's pre-deploy run
                listed=pre_deploy.get("listed") if _run else None,
                listed_classes=pre_deploy.get("listed_classes") or ())
            if _pd is not None:
                rec["pre_deploy"] = _pd
                if _pd.get("reason") in _PRE_DEPLOY_WHOLE_REASONS and to_run is not None:
                    to_run = None                          # the layer runs whole: no narrowing stands
                    planned.pop("narrowed", None)
                    if sink is not None and "plan" in sink:
                        sink["plan"] = {"units": None, "left_out": None}
                    _adapter_pre_deploy_whole(rec)
                if _pd["applied"]:
                    gone = {(u.get("project") or "", u["file"]) for u in _pd["removed"]}
                    if "narrowed" in planned:
                        planned["narrowed"]["units"] = [u for u in planned["narrowed"]["units"]
                                                        if (u.get("project") or "", u["file"]) not in gone]
                    else:
                        planned["narrowed"] = {"inventory": units, "units": to_run, "left_out": []}
                    print(f"land(consumer): verify layer {layer!r} pre-deploy exclusion: "
                          f"{len(_pd['removed'])} unit(s) of a pre-deploy class NOT run here ("
                          + ", ".join(f"{u['file']} [{u['class']}]" for u in _pd["removed"][:5])
                          + ("" if len(_pd["removed"]) <= 5 else f" (+{len(_pd['removed']) - 5} more)")
                          + ") — the deploy's pre-deploy run runs them (SPEC-1042 rule 2)")
                elif _pd.get("refused"):
                    print(f"land(consumer): verify layer {layer!r} pre-deploy declaration REFUSED "
                          f"({_pd['reason']}) — the layer runs whole and the verify fails on it")
                else:
                    print(f"land(consumer): verify layer {layer!r} pre-deploy exclusion NOT applied "
                          f"({_pd['reason']}) — the layer runs whole, pre-deploy units included")
        _alloc = ((pre_deploy.get("union") or {}).get(layer)
                  if pre_deploy is not None and pre_deploy.get("run") and rerun is None
                  and isinstance(pre_deploy.get("union"), dict) else None)
        if isinstance(_alloc, dict) and units is not None:
            # T-14211 (SPEC-1051 rule 3): the deploy's pre-deploy run runs the UNION once — the units the
            # run's allocation (`_pre_deploy_allocate`, decided before any layer ran) gives another
            # layer are not run here, and are named; the class reading counts each where it ran.
            def _named(keys):
                return [{"file": f, **({"project": p} if p else {})} for p, f in keys]
            if _alloc.get("again"):
                rec.setdefault("pre_deploy_union", {})["ran_again_in_group"] = _named(_alloc["again"])
            _taken = {tuple(k) for k in _alloc.get("drop") or ()}
            _base = units if to_run is None else to_run
            _dup = [u for u in _base if (u.get("project") or "", u["file"]) in _taken]
            if _dup:
                to_run = [u for u in _base if (u.get("project") or "", u["file"]) not in _taken]
                rec.setdefault("pre_deploy_union", {})["already_run"] = _named(
                    (u.get("project") or "", u["file"]) for u in _dup)
                if isinstance(rec.get("pre_deploy"), dict) and isinstance(rec["pre_deploy"].get("units"), list):
                    rec["pre_deploy"]["units"] = [n for n in rec["pre_deploy"]["units"]
                                                  if (n.get("project") or "", n.get("file")) not in _taken]
                if "narrowed" in planned:
                    planned["narrowed"]["units"] = [u for u in planned["narrowed"]["units"]
                                                    if (u.get("project") or "", u["file"]) not in _taken]
                else:
                    planned["narrowed"] = {"inventory": units, "units": to_run, "left_out": []}
                print(f"land(consumer): verify layer {layer!r} {len(_dup)} unit(s) another layer of this "
                      f"pre-deploy run runs — not run again here (SPEC-1051 rule 3)")
        if (deciding or crediting) and first_attempt and units is None:
            # No inventory on a deciding layer's first attempt (`list` absent or unusable): the
            # full `command:` decides, and `run` is not invoked ahead of it.
            _credit(None, None)
            return rec
        try:
            load1 = round(float(_load_avg()[0]), 2) if _load_avg is not None else None
        except Exception:                                  # unmeasurable — recorded ABSENT
            load1 = None
        if load1 is not None:
            rec["load1"] = load1
        def _batches(of):
            if of is None or prof["project_in_report"]:
                return [(None, of)]
            # One walk of the inventory, projects in the order `list` first names them: the split
            # costs the same whether the answer names one project or one per unit.
            by_project: dict = {}
            for u in of:
                by_project.setdefault(u["project"], []).append(u)
            return list(by_project.items())

        # T-13609 (SPEC-1006 rule 11): the layer's listed units leave the batch and run after it,
        # one at a time. Only a pass with an inventory has units to move; a re-run is alone already.
        laned: list = []
        if lane and units is not None and rerun is None:
            in_batch, laned, unmatched = _adapter_lane_split(units, lane)
            if to_run is not None:      # T-13907: the lane takes its units among the ones requested
                asked = {(u["project"], u["file"]) for u in to_run}
                in_batch = [u for u in in_batch if (u["project"], u["file"]) in asked]
                laned = [u for u in laned if (u["project"], u["file"]) in asked]
                planned["laned"] = laned
            rec["lane"] = {"units": len(laned), "unmatched": unmatched}
            batches = ([(p, b, False) for p, b in _batches(in_batch)] if in_batch else []) \
                + ([(p, b, True) for p, b in _batches(laned)] if laned else [])
        elif to_run is not None:        # T-13907: a selection naming no unit invokes no `run`
            batches = [(p, b, False) for p, b in _batches(to_run)] if to_run else []
        else:
            batches = [(p, b, False) for p, b in _batches(units)]
        void: list = []
        rows: list = []
        for proj, batch, in_lane in batches:
            res, box, started = _invoke("run", batch, proj, in_lane=in_lane)
            if box is not None:         # T-13907: this invocation was STARTED (a bound hit inside
                launched.extend(batch or ())    # it included); one never started names no unit
            if res is None:
                rec.pop("exit", None)                      # nothing of this pass is read
                rec.update({"outer": "timed-out", "outer_at": "run"})
                print(f"land(consumer): verify layer {layer!r} adapter `run` hit the layer's bound "
                      f"({timeout}s) — no report is read; the layer's verdict is its `command:` exit code")
                return rec
            if res.returncode != 0 and not rec.get("exit"):
                rec["exit"] = res.returncode
            rec.setdefault("exit", 0)
            try:
                got = _classify_adapter_report(
                    decl["report_profile"], requested=batch, exit_code=res.returncode,
                    report_text=_adapter_read_output(box / "report.xml", max_output_bytes, _checkpoint),
                    second_text=(_adapter_read_output(box / "report.json", max_output_bytes, _checkpoint)
                                 if prof["second_report"] else None),
                    started_at=started, project=proj, checkpoint=_checkpoint)
                _checkpoint()                              # and once more when the reading is done
            except _AdapterPassDeadline:
                # The bound passed WHILE the report was being read: the reading stopped there.
                rec.pop("exit", None)                      # nothing of this pass is kept
                rec.update({"outer": "timed-out", "outer_at": "report"})
                print(f"land(consumer): verify layer {layer!r} adapter pass passed the layer's bound "
                      f"({timeout}s) while its report was being read — the reading stops, no rows are "
                      f"kept; the layer's verdict is its `command:` exit code")
                return rec
            void.extend(r for r in got["void"] if r not in void)
            for row in got["units"] if in_lane else ():
                row["lane"] = True
            rows.extend(got["units"])
        if void:
            rec["void"] = void
        rec["units"] = rows
        rec["usable"] = rec["list"] in ("ok", "given") and not void and not prof["unrevealable"]
        tally = {}
        for row in rows:
            tally[row["status"]] = tally.get(row["status"], 0) + 1
        _kind = ("isolated re-run" if rerun is not None else
                 "first attempt" if first_attempt else "report-only")
        print(f"land(consumer): verify layer {layer!r} adapter report ({decl['report_profile']}, "
              f"{_kind}): {len(rows)} unit(s)"
              + (" — " + ", ".join(f"{n} {k}" for k, n in sorted(tally.items())) if tally else "")
              + ("; report usable" if rec["usable"] else
                 "; rows are diagnostics only"
                 + (f" (void: {', '.join(void)})" if void else " (no `list` inventory)")))
        if laned:
            print(f"land(consumer): verify layer {layer!r} load-sensitive lane: {len(laned)} listed "
                  f"unit(s) ran AFTER the batch, one at a time ("
                  + ", ".join(u["file"] for u in laned[:5])
                  + ("" if len(laned) <= 5 else f" (+{len(laned) - 5} more)")
                  + ") — each decides the verdict as any unit does (SPEC-1035 rule 11)")
        _select(units, rows)
        _credit(units, rows)
        return rec
    except Exception as e:                                 # report-only: never raise into a verify
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
        rec["usable"] = False
        if deciding:                                       # T-13907: the mode is on every record
            rec.setdefault("selection", _no_decision("pass-error"))
        if crediting:
            rec.setdefault("credit", _no_credit("pass-error"))
        if deciding or crediting:
            if first_attempt and decl.get("required") and "required" not in rec:
                # The fault came before the layer's `required:` checks had all run. On a deciding
                # layer they are owed on every first attempt (SPEC-1030 rule 4), so the layer
                # FAILS here as on a failed check, and the full `command:` does not decide in
                # their place. `ran` is the number of checks that had run and passed; `failed`
                # names the first one that had not completed; `exit: None` — it has no exit code.
                rec["required"] = {"ran": len(checks_passed), "failed": len(checks_passed), "exit": None}
        return rec
    finally:
        rec["duration_ms"] = int(round((clock() - t0) * 1000))
        if "narrowed" in planned:
            # T-13907 (SPEC-1030 rule 5): what a narrowed run DID, written once the pass ends —
            # on every way out of it — from the `run` invocations that were started.
            rec["partial"] = _adapter_partial_record(planned["narrowed"], launched)
            if isinstance(rec.get("lane"), dict) and "laned" in planned:
                # ... and the lane's count is the listed units whose invocation was started
                begun = {(u["project"], u["file"]) for u in launched}
                rec["lane"]["units"] = sum(1 for u in planned["laned"] if (u["project"], u["file"]) in begun)
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


#: T-13609 (SPEC-1006 rule 11) — the PER-UNIT sibling of the engine suite's load-sensitive carrier
#: (`verify_runner._LOAD_SENSITIVE_FILE`): the load-sensitive list of a consumer's adapter-backed verify
#: layers, one committed file at the repository root beside the ops carrier. It lives here, beside the
#: adapter pass that reads it, not in the runner module, whose membership is the runner's own reach. Entries are APPENDED by the land tail
#: (`worktree._unit_lane_entry_at_land_tail`) and only ever REMOVED by a card.
_UNIT_LANE_FILE = "yitc-load-sensitive-units.txt"


def _unit_lane_parse(text) -> dict:
    """The entries of a per-unit load-sensitive carrier text: `{<layer>: {(<kind>, <project>,
    <name>): <its line>}}`. PURE.

    One entry per line, its fields separated by TAB characters: the layer's name, the entry's kind
    (`unit` — a test file — or `group` — a declared indivisible group), the runner project (empty
    where the runner has none), the unit's repo-relative file or the group's label; whatever
    follows is provenance for humans and the ratifying card, read by nobody here. A blank line and
    a line whose first non-blank character is `#` are skipped. A line with fewer than four fields,
    another kind, an empty layer or an empty name is NOT an entry: it lists nothing, so the unit
    it meant runs in the batch as before. The first line of an entry stands."""
    out: dict = {}
    for raw in str(text or "").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 4 or parts[1] not in ("unit", "group") or not parts[0] or not parts[3]:
            continue
        out.setdefault(parts[0], {}).setdefault((parts[1], parts[2], parts[3]), raw)
    return out


def _unit_lane_set(root) -> dict:
    """T-13609 (SPEC-1006 rule 11) — the declared per-unit load-sensitive lists of the checkout at
    `root`, by layer (`_unit_lane_parse` over `<root>/yitc-load-sensitive-units.txt`).

    FAIL-SAFE IN THE DIRECTION OF TODAY, as `verify_runner._load_sensitive_set`: a missing or unreadable
    carrier lists NOTHING — every unit runs in its layer's batch. The list moves WHERE a unit
    runs, never WHETHER, so a lost carrier can only run a unit under more load, never excuse it."""
    try:
        return _unit_lane_parse(
            (Path(root) / _UNIT_LANE_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}


def _adapter_lane_split(units, lane) -> tuple:
    """SPEC-1006 rule 11 — WHICH units of a layer's inventory run in its load-sensitive lane.
    `units` are the listed inventory entries (`{project, file, report_id?, group?}`), `lane` the
    layer's declared entries — `(kind, project, name)`, `kind` `unit` (name = the file) or `group`
    (name = the group's label). Returns `(batch, laned, unmatched)`: the inventory split in two,
    each half in inventory order, and the number of entries that name no unit of this inventory.

    A unit is laned when an entry names its file or its group — and a declared group is
    indivisible (rule 2), so a group one of whose members is named goes to the lane WHOLE. PURE,
    and linear in the inventory plus the entries: two walks of the inventory, none per entry."""
    lane = set(lane or ())
    hit, groups = set(), set()
    for u in units or []:
        proj = str(u.get("project") or "")
        keys = {("unit", proj, str(u.get("file")))}
        if u.get("group"):
            keys.add(("group", proj, u["group"]))
        if keys & lane:
            hit |= keys & lane
            groups.add((proj, u["group"]) if u.get("group") else None)
    groups.discard(None)
    batch, laned = [], []
    for u in units or []:
        proj = str(u.get("project") or "")
        named = ("unit", proj, str(u.get("file"))) in lane or \
            (bool(u.get("group")) and (proj, u["group"]) in groups)
        (laned if named else batch).append(u)
    return batch, laned, len(lane - hit)


# ───────── T-13607 — the adapter's `run` as the layer's FIRST ATTEMPT, and the per-unit re-run
# (SPEC-1006 rules 4, 5, 10; the contract is `proposed` until its activation card) ─────────
#
# T-13606 recorded the per-unit report beside a verdict the layer's `command:` had already given.
# This slice lets a USABLE report decide: on a layer whose adapter declares `list`, the pass above
# runs FIRST (`first_attempt=True`) and `_adapter_first_attempt` reads the layer's first-attempt
# outcome off its record. Every reading that is not a usable report or a failed attempt answers
# `command` — the layer's full `command:` then runs and decides exactly as on a layer with no
# adapter (SPEC-0152 rule 16), and the per-unit rows stay diagnostics.
#
# ───────── T-13907 — a DECIDING selection ACTS (SPEC-1030 rules 2, 4, 5) ─────────────────────────
#
# A layer reaches this block by declaring `selection: deciding` with its reason (SPEC-1030 rule 1,
# read by `_declared_layer_adapters`). On such a layer the rule-6 ladder
# (`_adapter_shadow_decision`, unchanged) is asked BEFORE `run`, and on the candidate run of ONE
# card its answer acts. The pure pieces:
#   `_adapter_deciding_record`   the `selection` record of a deciding layer;
#   `_adapter_run_plan`          THE ONE PLACE that names the units a run executes;
#   `_adapter_partial_record`    what a narrowed run did, from the invocations it started;
#   `_adapter_passed_outcome`    the row outcome of a layer whose adapter report passed;
#   `_adapter_full_command_ran`  a narrowed first attempt the layer's full `command:` followed;
#   `_one_card_candidate_kw`     the keyword the land's candidate leg hands the layer runner.
#
# ───────── T-13909 — a DECIDING credit ACTS (SPEC-1030 rules 3, 5) ───────────────────────────────
#
# A layer reaches this block by declaring `credit: deciding` with its reason. On such a layer, on
# the candidate run of ONE card whose previous attempt failed as
# a whole on the same recorded base, the rule-14 decision (`_adapter_credit_decision`, unchanged)
# is taken BEFORE `run` — after the rule-6 ladder has answered rung (f) for the card's WHOLE change
# — and `_adapter_run_plan` leaves the credited units out of what `run` is invoked with.
#   `_adapter_previous_attempt(whole=True)`  the card's previous attempt and whether it failed;
#   `_adapter_credit_basis(deciding=True)`   what its record allows — the widened premise;
#   `_adapter_deciding_credit_record`        the `credit` record of a layer declaring the mode.
def _adapter_deciding_record(ladder, narrowed: bool = False, *, why: str = "not-one-card-candidate",
                             related: str = "not-run") -> dict:
    """SPEC-1030 rule 5 — the `selection` record of ONE run of a layer whose parsed declaration
    reads `selection: deciding` (registered in SPEC-0025). `ladder` is the rule-6 ladder's answer
    for this run's change (`_adapter_shadow_decision`'s record) and `narrowed` whether the run
    plan made of it leaves a unit out (`_adapter_run_plan`). `ladder` None = NO decision was taken
    on this run, and `why` says which case: `not-one-card-candidate` (rule 4 — not the candidate
    run of one card), `no-change` (no change to decide over), `outer-failure` and
    `required-failed` (the layer failed before a decision), `pass-error`, `selection-error`;
    `related` is then `absent` or `not-run` as the adapter has the command or not.

    THE RECORD: `{schema: 1, mode: "deciding", decision: "full" | "units", rung, reason, related,
    related_reason?, base?, changed?, eligible?, fired_paths?, fired_paths_more?, unknown?,
    unknown_more?}`. `decision` says what
    the RUN is: `units` only when it is narrowed, `full` on every other run — a rung-(f) answer
    that names every unit included, which keeps its rung and reason. `rung` and `reason` are the
    ladder's, as they are, with its diagnostic keys. The record carries NEITHER a total NOR a unit
    list: what a narrowed run executed and left out is the `partial` record's
    (`_adapter_partial_record`), so a run that is not narrowed states no count and no list (rule 5
    — a field the kernel does not know is absent, never zero and never an empty list). PURE."""
    if not isinstance(ladder, dict):
        return {"schema": 1, "mode": "deciding", "decision": "full", "rung": None, "reason": str(why),
                "related": str(related)}
    sel = {"schema": 1, "mode": "deciding", "decision": "units" if narrowed else "full",
           "rung": ladder["rung"], "reason": ladder["reason"], "related": ladder["related"]}
    sel.update({k: ladder[k] for k in ("related_reason", "base", "changed", "eligible", "fired_paths",
                                       "fired_paths_more", "unknown", "unknown_more") if k in ladder})
    return sel


def _adapter_deciding_credit_record(got, acted: bool = False, *, why: str = "not-one-card-candidate") -> dict:
    """SPEC-1030 rule 5 — the `credit` record of ONE run of a layer whose parsed declaration reads
    `credit: deciding` (registered in SPEC-0025). `got` is what was decided for this run — the
    record of `_adapter_credit_basis(deciding=True)` or of `_adapter_credit_decision` — and
    `acted` whether the run plan made of it credits at least one unit (`_adapter_run_plan`).
    `got` None = NO decision was taken, and `why` says which case: `not-one-card-candidate`
    (rule 4), `no-change`, `no-basis` (the caller handed no previous-attempt reading),
    `selection-shadow` (the layer's selection is `shadow`, which needs the full run it is
    compared with), `outer-failure` and `required-failed` (the layer failed before a decision),
    `pass-error`, `selection-error` (the ladder for the card's whole change could not be taken),
    `credit-error`.

    THE RECORD: `{schema: 1, mode: "deciding", decision: "units" | "none" | "void", reason,
    previous?, changed?, tree?, rung?, ladder_reason?, related?, related_reason?, eligible?,
    unknown?, unknown_more?}`. `decision` says what the RUN did: `units` only when it credited a
    unit; a decision that names units to credit of which the run needs none is `void` /
    `no-creditable-unit`; every `none` and `void` of `got` stands with its reason. The record
    carries NEITHER a total NOR a unit list — what a run executed and credited is the `partial`
    record's (`_adapter_partial_record`) — and no comparison: there is no full run to compare
    with. PURE."""
    if not isinstance(got, dict):
        return {"schema": 1, "mode": "deciding", "decision": "void", "reason": str(why)}
    rec = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
           for k, v in got.items()
           if k not in ("would_rerun", "would_credit", "units_total", "compared", "disagreements")}
    rec.update({"schema": 1, "mode": "deciding"})
    if rec.get("decision") == "units" and not acted:
        rec.update({"decision": "void", "reason": "no-creditable-unit"})
    elif rec.get("decision") not in ("units", "none", "void") or not isinstance(rec.get("reason"), str):
        return {"schema": 1, "mode": "deciding", "decision": "void", "reason": "credit-error"}
    return rec


def _adapter_run_plan(inventory, ladder, credit=None) -> dict:
    """SPEC-1030 rules 2, 3 — WHICH units ONE run of a layer executes: the ONE place that turns a
    decision that ACTS into the unit set `run` is invoked with. A further deciding mode extends
    THIS function; the pass asks it and holds no second branch. `inventory` is `list`'s unit list
    (None = this run has none); `ladder` the rule-6 ladder's answer for a deciding selection that
    acts on this run, or None where none acts; `credit` (T-13909) the rule-14 decision
    (`_adapter_credit_decision`'s record) for a deciding credit that acts on this run, or None.

    THE UNITS THE RUN NEEDS are the ladder's selection where it answered rung (f), every unit of
    the inventory otherwise. Of those, a `credit` whose decision is `units` CREDITS the ones it
    names as would-credit — units the previous attempt itself ran and passed and the fix does not
    reach — and the run executes the others; a unit the run does not need is never credited.

    Returns `{units, left_out}`. Both None — the run is NOT narrowed: `run` gets the whole
    inventory (with no inventory, every unit the layer runs). Otherwise the run is NARROWED — it
    leaves a unit out or credits one: `units` are the inventory entries to run, in inventory order
    (possibly none), and `left_out` the units the selection left out, each `{file, project?}` in
    inventory order (possibly none). A run that credits carries two more keys: `credited` — the
    credited units, same shape and order — and `previous`, the previous attempt's reference as the
    decision holds it. A rung-(f) answer that names EVERY unit, with nothing credited, is not
    narrowed. PURE."""
    whole = {"units": None, "left_out": None}
    if inventory is None:
        return whole
    chosen = reuse = None
    if isinstance(ladder, dict) and ladder.get("decision") == "units":
        chosen = {(u.get("project") or "", u["file"]) for u in ladder.get("would_run") or ()}
    if isinstance(credit, dict) and credit.get("decision") == "units":
        reuse = {(u.get("project") or "", u["file"]) for u in credit.get("would_credit") or ()}
    units, left_out, credited = [], [], []
    for u in inventory:
        key = (u.get("project") or "", u["file"])
        name = {"file": u["file"], **({"project": u["project"]} if u.get("project") else {})}
        if chosen is not None and key not in chosen:
            left_out.append(name)
        elif reuse is not None and key in reuse:
            credited.append(name)
        else:
            units.append(u)
    if not (left_out or credited):
        return whole
    plan = {"units": units, "left_out": left_out}
    if credited:
        plan.update({"credited": credited,
                     "previous": dict(credit["previous"]) if isinstance(credit.get("previous"), dict) else {}})
    return plan


def _adapter_partial_record(narrowed: dict, launched) -> dict:
    """SPEC-1030 rule 5 — what ONE narrowed run DID; rides the adapter record as `partial`
    (registered in SPEC-0025). `narrowed` is `{inventory, units, left_out}` — the inventory and
    its run plan (`_adapter_run_plan`); `launched` the units of every `run` invocation that was
    STARTED (one that then hit the bound included).

    `{units_total, ran, not_reached, left_out, credited, previous?}` — entries `{file,
    project?}`, each list in inventory order: `ran` the requested units whose invocation was
    started; `not_reached` the requested units whose invocation never started (the bound passed
    before it); `left_out` the units the selection left out; `credited` (T-13909) the units the
    plan credits — not run, and never in `ran` — empty where no credit acted, which the kernel
    knows is none. Where a unit is credited `previous` is the previous attempt's reference
    (`{type, ts, outcome, tree, base}`, as the plan holds it); absent otherwise. `ran` and
    `not_reached` together are the units requested. PURE."""
    begun = {(u.get("project") or "", u["file"]) for u in launched or ()}
    ran, not_reached = [], []
    for u in narrowed["units"]:
        key = {"file": u["file"], **({"project": u["project"]} if u.get("project") else {})}
        (ran if (u.get("project") or "", u["file"]) in begun else not_reached).append(key)
    credited = [dict(u) for u in narrowed.get("credited") or ()]
    return {"units_total": len(narrowed["inventory"]), "ran": ran, "not_reached": not_reached,
            "left_out": [dict(u) for u in narrowed["left_out"]], "credited": credited,
            **({"previous": dict(narrowed.get("previous") or {})} if credited else {})}


def _one_card_candidate_kw(batch_members) -> dict:
    """SPEC-1030 rule 4 — the keyword the land's candidate leg hands the layer runner:
    `{"one_card_candidate": True}` when the candidate holds ONE member (no batch formed, or a
    batch of one), `{}` for a combined candidate of several — which runs every layer in full.
    `batch_members` is the land's member list at the moment the candidate is verified (None
    before any batch formed). PURE."""
    return {"one_card_candidate": True} if len(batch_members or ()) <= 1 else {}


def _adapter_shipped_decision(rec, sink) -> dict:
    """T-13973 (SPEC-1032 rule 4) — the decision ONE host-side pass of a deciding layer took, in the
    form a box follows (`_layer_adapter_report_pass(shipped=...)`): `{selection, credit, units,
    left_out, credited?, previous?}`. `rec` is the pass's record, `sink` the dict it was handed:
    `selection` / `credit` are the record's two deciding records as written (None where the layer
    reads no such mode); `units`, `left_out`, `credited` and `previous` are the run plan the pass
    took (`sink["plan"]`, `_adapter_run_plan`'s answer), each unit `{file, project?}`. `units` None
    — the plan narrows nothing, or the pass never reached a plan — runs the whole inventory.
    `listed` (T-13994, SPEC-1032 rule 5) is how many units the host's `list` named (`sink["inventory"]`),
    None when it named none usable; a box whose own `list` names none of them says so on its row. PURE."""
    def _names(units):
        return [{"file": u["file"], **({"project": u["project"]} if u.get("project") else {})}
                for u in units or () if isinstance(u, dict) and isinstance(u.get("file"), str)]

    rec = rec if isinstance(rec, dict) else {}
    plan = (sink or {}).get("plan") if isinstance(sink, dict) else None
    plan = plan if isinstance(plan, dict) else {}
    out = {"selection": json.loads(json.dumps(rec["selection"])) if isinstance(rec.get("selection"), dict) else None,
           "credit": json.loads(json.dumps(rec["credit"])) if isinstance(rec.get("credit"), dict) else None,
           "units": _names(plan["units"]) if isinstance(plan.get("units"), list) else None,
           "left_out": _names(plan.get("left_out")),
           "listed": (len(sink["inventory"]) if isinstance(sink, dict)
                      and isinstance(sink.get("inventory"), list) else None)}
    if plan.get("credited"):
        out.update({"credited": _names(plan["credited"]),
                    "previous": dict(plan["previous"]) if isinstance(plan.get("previous"), dict) else {}})
    return out


def _adapter_passed_outcome(rec) -> str:
    """SPEC-1030 rule 5 — the row outcome of a layer whose adapter report PASSED: `passed-partial`
    when the record is a narrowed run's (it carries `partial`), `passed` otherwise — a run that is
    not narrowed, and every layer under `off` or `shadow`. PURE."""
    return "passed-partial" if isinstance(rec, dict) and isinstance(rec.get("partial"), dict) else "passed"


# ───────── T-14104 — the PRE-DEPLOY exclusion, applied LAST (SPEC-1042 rule 1, SPEC-1044 rule 2) ─────────
#
# A pre-deploy class names its units in the ONE adapter inventory (each `list` unit's optional
# `classes:`, SPEC-1035 rule 3) or whole layers (`layers:`). On a land's candidate leg and a Stage-6
# run the units of such a class leave the set the layer would run today — after the selection
# ladder, the SPEC-1030 deciding selection and credit and the `command:` fallback — and the row
# names each with its class — on a forced full run too (T-14174). Never on a `shadow` layer's full
# side, a re-run or the pinned last-green leg. No contract reaches this before the turn-on card: the contract reader
# refuses `moment: pre-deploy` (init.py `_hook_tests`), and only a caller handed the PARSED
# declaration (`pre_deploy=`) applies it.
def _pre_deploy_declaration(classes) -> "dict | None":
    """SPEC-1042 rule 1 — the pre-deploy part of a PARSED `tests.classes[]`: `{classes, layers}` —
    `classes` the names of the `moment: pre-deploy` entries, `layers` `{layer: class}` for the layers
    such an entry names whole in `layers:`. None when no entry is a pre-deploy one. The entry shape
    is the contract reader's to refuse; here an entry that is not a mapping, or names no class, is
    no pre-deploy class. T-14211 (SPEC-1051 rule 1): where an entry declares `units:` (the LISTED
    order) the record also carries `listed_classes` (their names), `listed` (`{file: class}`, every
    listed file) and `never_move` (every pre-deploy entry's `never_move:` globs) — keys absent when no
    entry declares `units:`, so a fallback-only declaration reads exactly as before. PURE."""
    names, layers = [], {}
    listed_classes, listed, never = [], {}, []
    for c in classes if isinstance(classes, list) else ():
        if not (isinstance(c, dict) and str(c.get("moment") or "").strip() == "pre-deploy"):
            continue
        name = str(c.get("class") or "").strip()
        if not name:
            continue
        names.append(name)
        for ly in c.get("layers") if isinstance(c.get("layers"), list) else ():
            if isinstance(ly, str) and ly.strip():
                layers.setdefault(ly.strip(), name)
        never += [g.strip() for g in c.get("never_move") if isinstance(g, str) and g.strip()] \
            if isinstance(c.get("never_move"), list) else []
        if isinstance(c.get("units"), list):          # T-14211: the LISTED order (SPEC-1051 rule 1)
            listed_classes.append(name)
            for u in c["units"]:
                if isinstance(u, str) and u.strip():
                    listed.setdefault(u.strip(), name)
    if not names:
        return None
    out = {"classes": names, "layers": layers}
    if listed_classes:      # T-14211: absent unless a class declares `units:` — the fallback reads as before
        out.update({"listed_classes": listed_classes, "listed": listed, "never_move": never})
    return out


def _pre_deploy_contract_verdict(ops) -> dict:
    """T-14114 (SPEC-1042 rule 1) — the contract read's verdict on the pre-deploy declaration of the
    parsed contract `ops`: `{"classes": <its tests.classes>, "refused": [errors]}` when it carries a
    `moment: pre-deploy` entry (`refused` = `init.pre_deploy_declaration_errors`, [] when admitted),
    else `{"classes": None, "refused": []}`. PURE."""
    tests = ops.get("tests") if isinstance(ops, dict) else None
    classes = tests.get("classes") if isinstance(tests, dict) else None
    if _pre_deploy_declaration(classes) is None:
        return {"classes": None, "refused": []}
    from lib import init as _init                        # lazy: init reaches worktree, which imports this module
    return {"classes": classes, "refused": _init.pre_deploy_declaration_errors(ops)}


def _pre_deploy_admitted_classes(ops) -> "list | None":
    """T-14114 — the PARSED `tests.classes` of `ops` when it declares a pre-deploy class the contract
    read admits, else None. A refused declaration skips no land unit and owes no stand probe — the
    land runs every unit — while the deploy refuses on it (`_pre_deploy_contract_read`). PURE."""
    v = _pre_deploy_contract_verdict(ops)
    return None if v["refused"] else v["classes"]


def _pre_deploy_contract_read(tree) -> dict:
    """T-14114 — `_pre_deploy_contract_verdict` of the contract `tree/yitc-ops.yaml`; no carrier, or
    one that cannot be read, declares nothing. The ONE reader the land, Stage-6 and deploy seams
    share."""
    path = Path(tree) / "yitc-ops.yaml"
    try:
        ops = state.load_ops(path) if path.is_file() else None
    except Exception:                                    # noqa: BLE001 — unreadable = not declared
        ops = None
    return _pre_deploy_contract_verdict(ops)


def _pre_deploy_contract_kw(tree) -> dict:
    """T-14114 (SPEC-1044 rule 2) — the keyword a land's candidate leg and a Stage-6 run hand the layer
    runner: `{"pre_deploy": <the declaration>}` when `tree`'s contract declares an admitted pre-deploy
    class (`_pre_deploy_contract_read`), else `{}` — so a project declaring none, or one whose
    declaration the contract read refuses, calls the runner exactly as before: every unit runs."""
    v = _pre_deploy_contract_read(tree)
    decl = None if v["refused"] else _pre_deploy_declaration(v["classes"])
    return {"pre_deploy": decl} if decl is not None else {}


#: a unit whose `classes:` is not a list of non-empty strings
_PRE_DEPLOY_MALFORMED = object()
#: the `pre_deploy` reasons that read the `list` answer as one that did not answer for the exclusion:
#: the layer runs WHOLE — a narrowing the deciding modes took is undone (`_adapter_pre_deploy_whole`)
_PRE_DEPLOY_WHOLE_REASONS = frozenset(("mixed-group", "membership-malformed", "unit-names-two-pre-deploy-classes"))


def _adapter_pre_deploy_whole(rec):
    """SPEC-1042 rule 1 — a run whose `list` answer did not answer for the pre-deploy exclusion
    (`_PRE_DEPLOY_WHOLE_REASONS`) runs its layer WHOLE, so a narrowing a deciding mode took is not
    kept: a deciding `selection` that narrowed reads `decision: full`, `reason: pre-deploy-whole`,
    the ladder's reason kept as `ladder_reason`; a deciding `credit` that credited reads `void` /
    `pre-deploy-whole`. Changes `rec` in place and returns it."""
    sel = rec.get("selection")
    if isinstance(sel, dict) and sel.get("mode") == "deciding" and sel.get("decision") == "units":
        sel.update({"ladder_reason": sel.get("reason"), "decision": "full", "reason": "pre-deploy-whole"})
    cred = rec.get("credit")
    if isinstance(cred, dict) and cred.get("mode") == "deciding" and cred.get("decision") == "units":
        cred.update({"decision": "void", "reason": "pre-deploy-whole"})
    return rec


def _pre_deploy_membership(raw):
    """SPEC-1035 rule 3 — a `list` unit's `classes:` as a tuple of names, or the malformed mark. A
    unit with no `classes:` belongs to no class (the empty tuple). PURE."""
    if raw is None:
        return ()
    if isinstance(raw, list) and all(isinstance(c, str) and c.strip() for c in raw):
        return tuple(c.strip() for c in raw)
    return _PRE_DEPLOY_MALFORMED


def _pre_deploy_exclusion(inventory, to_run, memberships, declared, *, decl, change,
                          first_attempt=True, run=False, listed=None, listed_classes=()) -> tuple:
    """SPEC-1044 rule 2 — the pre-deploy exclusion of ONE run of an adapter-backed layer, applied
    LAST: `to_run` is the set the run would execute today (`_adapter_run_plan`'s units, None = the
    whole `inventory`), `memberships` `{(project, file): _pre_deploy_membership(...)}` from the
    `list` answer, `declared` the declared pre-deploy class names. Returns `(units, record)`:
    the units to run (None = unchanged whole) and the `pre_deploy` record of the adapter record, or
    None where there is nothing to say (no unit of the inventory is a pre-deploy unit — the run and
    its row are exactly today's).

    THE RECORD: `{applied, reason?, removed?, units?, groups?}`, entries `{file, project?, class?}`
    in inventory order. `applied: true` with `removed` — the units taken out of this run, each with
    its class. Otherwise `applied: false` and `reason` says why the layer runs whole:
    `list-unanswered` (no inventory — the `command:` fallback), `membership-malformed` /
    `unit-names-two-pre-deploy-classes` (`units` names them; both carry `refused: true` — a malformed
    declaration the verify then fails on, `_pre_deploy_refusal_line`), `mixed-group` (`groups` names each
    declared group mixing a class and none), `shadow-full-side` or `command-decided` (not the
    layer's first attempt) — `units` then names the pre-deploy units that ran. A FORCED full run (a
    change the SPEC-0152 rule-16 skip names, or the adapter's `sources:`) is excluded like any other
    first attempt (T-14174): `change` is no longer read here, and the pre-deploy run covers the units.

    `run` (T-14105 — SPEC-1042 rule 3) marks the deploy's PRE-DEPLOY RUN: nothing is removed, and
    the record reads `pre-deploy-run` with `units` naming every pre-deploy unit of the inventory with
    its class (`groups` beside them for a declared group mixing a class and none — the run names its
    units all the same), so the deploy can give each class its own units. The malformed-membership
    refusals above hold in the run as on a land. T-14211 (SPEC-1051 rule 1): `listed` — `{file: class}`
    of the classes declaring `units:` — gives every inventory unit of a listed file that class, in
    every execution context (project) it runs in, and `listed_classes` names the classes declaring
    `units:` — an adapter `classes:` naming one of them is not read (their membership is the list
    alone); the land and Stage-6 seams pass only the fallback classes and no `listed` (their skip set
    leaves before selection, `_pre_deploy_skip_units`). PURE."""
    if inventory is None:
        return to_run, {"applied": False, "reason": "list-unanswered"}
    declared = set(declared or ())
    listed_from = set((listed or {}).values()) | set(listed_classes or ())   # T-14211: membership from `units:` only

    def _name(u, **more):
        return {"file": u["file"], **({"project": u["project"]} if u.get("project") else {}), **more}

    cls, bad, two = {}, [], []
    for u in inventory:
        key = (u.get("project") or "", u["file"])
        got = (memberships or {}).get(key, ())
        if got is _PRE_DEPLOY_MALFORMED:
            bad.append(_name(u))
            continue
        hit = sorted({c for c in got if c in declared and c not in listed_from}
                     | ({listed[u["file"]]} if listed and u["file"] in listed else set()))
        if len(hit) > 1:
            two.append(_name(u, classes=hit))
        cls[key] = hit[0] if hit else None
    if bad:
        return to_run, {"applied": False, "reason": "membership-malformed", "refused": True, "units": bad}
    if two:                 # SPEC-1042 rule 1: a malformed declaration — the land refuses it
        return to_run, {"applied": False, "reason": "unit-names-two-pre-deploy-classes", "refused": True,
                        "units": two}
    members = [u for u in inventory if cls[(u.get("project") or "", u["file"])]]
    if not members:
        return to_run, None
    by_group: dict = {}
    for u in inventory:
        if u.get("group"):
            by_group.setdefault((u.get("project") or "", u["group"]), set()).add(
                cls[(u.get("project") or "", u["file"])])
    mixed = [{"group": g, **({"project": p} if p else {})}
             for (p, g), seen in by_group.items() if len(seen) > 1]
    if run:                 # T-14105: the pre-deploy run removes nothing and names every class unit
        named = [_name(u, **{"class": cls[(u.get("project") or "", u["file"])]}) for u in inventory
                 if cls.get((u.get("project") or "", u["file"]))]
        return to_run, {"applied": False, "reason": "pre-deploy-run", "units": named,
                        **({"groups": mixed} if mixed else {})}
    if mixed:
        return to_run, {"applied": False, "reason": "mixed-group", "groups": mixed}
    base = inventory if to_run is None else to_run
    named = [_name(u, **{"class": cls[(u.get("project") or "", u["file"])]}) for u in base
             if cls.get((u.get("project") or "", u["file"]))]       # the pre-deploy units this run requests
    if (decl or {}).get("selection") == "shadow":
        return to_run, {"applied": False, "reason": "shadow-full-side", "units": named}
    if not first_attempt:
        return to_run, {"applied": False, "reason": "command-decided", "units": named}
    keep, removed = [], []
    for u in base:
        c = cls.get((u.get("project") or "", u["file"]))
        (removed.append(_name(u, **{"class": c})) if c else keep.append(u))
    if not removed:         # the selection already left every pre-deploy unit out
        return to_run, None
    return keep, {"applied": True, "removed": removed}


def _pre_deploy_refusal_line(layer, record) -> str:
    """SPEC-1042 rule 1 — the `bad` line of a layer whose `list` answer carries a malformed class
    membership (`record` is its `pre_deploy` record, `refused: true`): a unit in TWO declared
    pre-deploy classes, or a `classes:` that is not a list of names. The verify fails on it. PURE."""
    if record.get("reason") == "unit-names-two-pre-deploy-classes":
        named = ", ".join(f"{u.get('file')} [{', '.join(u.get('classes') or ())}]" for u in record.get("units") or ())
        what = (f"names a unit in TWO pre-deploy classes ({named}); a unit belongs to at most one "
                f"pre-deploy class")
    else:
        named = ", ".join(str(u.get("file")) for u in record.get("units") or ())
        what = f"gives a unit a `classes:` that is not a list of class names ({named})"
    return (f"land(consumer): verify layer {layer!r} — its adapter `list` {what} (SPEC-1042 rule 1, "
            f"SPEC-1035 rule 3). Fix the unit's `classes:` in the adapter's `list` answer, then re-land.")


def _pre_deploy_layer_skip_row(name: str, cls: str, change, decl=None) -> "dict | None":
    """SPEC-1044 rule 2 — the row of a layer a pre-deploy class names WHOLE (`layers:`) on a run the
    exclusion applies to: `{layer, outcome: passed-partial, pre_deploy: {applied: true, layer: {class}}}`
    — the layer is skipped and the skip is never silent. `decl` is the layer's parsed adapter
    declaration, None for a layer with no adapter. None — the layer runs whole as today — on a
    `selection: shadow` layer only: a forced full run skips it too (T-14174), so `change` is no
    longer read. PURE."""
    if (decl or {}).get("selection") == "shadow":
        return None
    return {"layer": name, "outcome": "passed-partial",
            "pre_deploy": {"applied": True, "layer": {"class": str(cls)}}}


# ───────── T-14211 — THE SKIP SET of the LISTED order, taken out BEFORE selection (SPEC-1051 rules 1-2) ─────────
#
# A class declaring `units:` lists its test FILES in the project's contract. A land's candidate leg and a
# Stage-6 run take its SKIP SET out of the units they may run before anything is selected, so every
# selection rule works over the rest as written; the row names it (`verify_metrics.pre_deploy_skip`, and an
# adapter layer's record `pre_deploy_skip`). ONE computation (`_pre_deploy_skip_set`, pure) over ONE read
# (`_pre_deploy_skip_read`) — the land, the Stage-6 run and the land's Stage-6 credit ask the same pair, so a
# land credits a Stage-6 run only when the two records carry the same key (`_pre_deploy_skip_key`).

#: SPEC-1051 rule 7 — the uncovered rule's threshold: no complete between-deploys result this recent → skip nothing.
PRE_DEPLOY_UNCOVERED_KEY = "pre_deploy_class_max_uncovered_hours"
#: the row type a between-deploys run (SPEC-1047 rule 5, `run_kind: scheduled`) and a deploy's
#: pre-deploy run (SPEC-1051 rule 4) record their units' results on
_PRE_DEPLOY_RESULT_EVENT = "test_class_executed"


#: the unit statuses that are a run's RESULT for a unit (SPEC-1035 §4); `skipped`, `missing` and any
#: other value are no result
_PRE_DEPLOY_FINAL_STATUSES = frozenset(("passed", "failed", "error"))


def _pre_deploy_row_results(data) -> dict:
    """T-14211 — `{file: (verdict, complete)}` of ONE `test_class_executed` row, the two judged APART.
    `verdict`: `failed` for a file its `failing` list names (a run's FINAL failures — a rescued unit is
    not on it, SPEC-1051 rule 4); else `passed` when EVERY execution context the row records for the
    file reads `passed`; else `other`. `complete`: every context the row records for the file carries a
    final status (passed/failed/error) — a context `skipped`, `missing`, without a status or with any
    other value is no result, and a file `failing` names but no context records is not complete. A
    failure never makes a file complete, so a missing context is never hidden by one (audit-pre
    fp1:52b9914eaa62e877). One file is one unit across its contexts. PURE."""
    statuses: dict = {}
    for ly in data.get("consumer_verify_layers") or () if isinstance(data.get("consumer_verify_layers"), list) else ():
        ad = ly.get("adapter") if isinstance(ly, dict) else None
        for u in (ad.get("units") or ()) if isinstance(ad, dict) and isinstance(ad.get("units"), list) else ():
            if isinstance(u, dict) and isinstance(u.get("file"), str) and u["file"]:
                statuses.setdefault(u["file"], []).append(u.get("status"))
    failed = {f["file"] for f in data.get("failing") or () if isinstance(f, dict)
              and isinstance(f.get("file"), str) and f["file"]} if isinstance(data.get("failing"), list) else set()
    out = {}
    for f in set(statuses) | failed:
        got = statuses.get(f) or []
        complete = bool(got) and all(st in _PRE_DEPLOY_FINAL_STATUSES for st in got)
        out[f] = ("failed" if f in failed else
                  "passed" if got and all(st == "passed" for st in got) else "other", complete)
    return out


def _pre_deploy_parse_ts(ts) -> "float | None":
    """An ISO `...Z` stamp as epoch seconds; None when it is not one. PURE."""
    try:
        return datetime.datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def _pre_deploy_skip_set(decl, *, rows, known_broken, always, changed, now, bound_hours, is_ancestor) -> "dict | None":
    """T-14211 (SPEC-1051 rule 2) — THE SKIP SET of one run, or None where no pre-deploy class declares
    `units:` (the fallback order, SPEC-1044 — nothing here is asked).

    `decl` is `_pre_deploy_declaration`'s record; `rows` the `(ts, data)` of every `test_class_executed`
    row of the MAIN checkout's journal IN THE ORDER the segment-aware reader returns them (None: it could
    not be read) — «later» is later in that order, never a later stamp (SPEC-1038 §Tests, order of
    journal rows); a stamp is read only for an age. `known_broken` the test files of the open
    known-broken-on-main records (SPEC-0181); `always` the `# yitc: selection: always` files; `changed`
    the paths the card's diff changes (None: unknown); `now` epoch seconds; `bound_hours` the uncovered
    bound; `is_ancestor(a, b)` git's answer (True/False/None) whether candidate `a` is `b` or an
    ancestor of it. A file's result in a row is `_pre_deploy_row_results`'.

    Returns `{order: "listed", classes, state, reason?, units, kept}`:
      `units` — `{file, class}` of each listed file the run leaves out, in file order;
      `kept`  — `{file, class, why}` of each listed file it runs: `never-move` (a `never_move:` glob in
                force matches it), `always`, `known-broken`, `final-failure` (a FINAL failure in a
                between-deploys or pre-deploy run, not followed by a row passing that file on the SAME
                candidate or a DESCENDANT of it — ordered as SPEC-1047 rule 6 orders candidates: an
                ancestor's later pass never clears it, and a pair git cannot order leaves it standing),
                `card-changed` (the card's diff changes the file itself);
      `state` — `skipping`; or `uncovered` (every listed file runs, `units` empty) while the LAST
                between-deploys run (`run_kind: scheduled`; one run = one `(run_ref, attempt)`, the last
                = the one whose last row comes last) is absent, unreadable, incomplete for the current
                list (a listed file without a result in every context it records) or older than the
                bound — `reason` names which; or `not-applied` (every listed file runs) when `changed`
                is unknown — the card exception cannot be decided.
    A row with `run_outcome: contended` (an attempt the contended re-run replaces) is read by neither
    the coverage nor the return: its re-run's row is the run's result (SPEC-1044 rule 3).
    A group is the adapter inventory's and is kept whole where the units are taken out
    (`_pre_deploy_skip_units`). PURE but for `is_ancestor`."""
    if not isinstance(decl, dict) or not decl.get("listed_classes"):
        return None
    listed = decl.get("listed") or {}
    base = {"order": "listed", "classes": sorted(decl["listed_classes"])}

    def _all_run(state, reason):
        return {**base, "state": state, "reason": reason, "units": [], "kept": []}

    if rows is None:
        return _all_run("uncovered", "unreadable")
    ordered = [(i, ts, data, _pre_deploy_row_results(data)) for i, (ts, data) in enumerate(rows)
               if isinstance(data, dict)]
    # a contended attempt is not a run's result — its re-run is (SPEC-1044 rule 3, SPEC-1051 rule 7)
    ordered = [o for o in ordered if o[2].get("run_outcome") != "contended"]
    runs: dict = {}
    for i, ts, data, res in ordered:
        if not (data.get("run_kind") == "scheduled" and isinstance(data.get("run_ref"), str)
                and data["run_ref"].strip()):
            continue
        attempt = data.get("attempt") if isinstance(data.get("attempt"), int) and not isinstance(
            data.get("attempt"), bool) else 0
        run = runs.setdefault((data["run_ref"].strip(), attempt), {"last": i, "ts": ts, "results": {}})
        run["last"], run["ts"] = i, ts
        for f, (_verdict, complete) in res.items():
            run["results"].setdefault(f, []).append(complete)
    if not runs:
        return _all_run("uncovered", "absent")
    last = max(runs.values(), key=lambda r: r["last"])
    if any(not last["results"].get(f) or not all(last["results"][f]) for f in listed):
        return _all_run("uncovered", "incomplete")
    stamp = _pre_deploy_parse_ts(last["ts"])
    if stamp is None or stamp > now:
        return _all_run("uncovered", "unreadable")
    if now - stamp > float(bound_hours) * 3600:
        return _all_run("uncovered", "older-than-bound")
    if changed is None:
        return _all_run("not-applied", "changed-paths-unknown")
    # the RETURN: a final failure stands until a LATER row passes the file on the same or a descendant candidate
    results = [(i, data["candidate"].strip(), res) for i, _ts, data, res in ordered
               if isinstance(data.get("candidate"), str) and data["candidate"].strip()
               and isinstance(data.get("run_outcome"), str)
               and (data.get("run_kind") == "scheduled" or "run_kind" not in data)]
    standing: set = set()
    for i, cand, res in results:
        for f in [f for f, v in res.items() if v[0] == "failed" and f in listed and f not in standing]:
            if not any(j > i and pres.get(f, ("",))[0] == "passed" and (pc == cand or is_ancestor(cand, pc) is True)
                       for j, pc, pres in results):
                standing.add(f)
    changed_set = {str(p)[2:] if str(p).startswith("./") else str(p) for p in changed}
    broken = set(known_broken or ())
    units, kept = [], []
    for f in sorted(listed):
        why = ("never-move" if any(fnmatch.fnmatch(f, g) for g in decl.get("never_move") or ()) else
               "always" if f in (always or ()) else
               "known-broken" if f in broken or os.path.basename(f) in broken else
               "final-failure" if f in standing else
               "card-changed" if f in changed_set else None)
        (kept.append({"file": f, "class": listed[f], "why": why}) if why
         else units.append({"file": f, "class": listed[f]}))
    return {**base, "state": "skipping", "units": units, "kept": kept}


def _pre_deploy_skip_key(rec) -> "tuple | None":
    """T-14211 (SPEC-1051 rule 2, SPEC-0065 §Bound) — what two skip-set records are compared by: the
    state and the files the COMPUTATION leaves out — those the run left out (`units`) and those it held
    back for the run's inventories (`held`, `_pre_deploy_close_skip`), so a record of the set a run
    actually applied compares with the set a land computes without inventories. None for no record
    (no listed class). PURE."""
    if not isinstance(rec, dict):
        return None
    return (rec.get("state"), tuple(sorted(str(u.get("file")) for key in ("units", "held")
                                           for u in rec.get(key) or () if isinstance(u, dict))))


def _selection_set_key(names, *, rule_version, skip=None) -> "dict | None":
    """T-14228 (SPEC-0065 §Bound condition 4) — what a narrowed Stage-6 run's selected test set and a
    land's own selection are compared by, the way `_pre_deploy_skip_key` compares two skip sets: the
    SPEC-0181 rule version, the file count and a sha256 over the sorted file names (the WHOLE set that
    runs — the selected files and the always-run ones together, never a count), with the files the
    pre-deploy skip record `skip` left out (`units`) taken away first, so the two compare after the
    skip-set equality. None when `names` is not a non-empty list of names (nothing to compare). PURE."""
    if not isinstance(names, (list, tuple)) or not names \
            or not all(isinstance(n, str) and n for n in names):
        return None
    gone = {Path(str(u.get("file"))).name for u in ((skip or {}).get("units") or ())
            if isinstance(u, dict)} if isinstance(skip, dict) else set()
    kept = sorted(set(names) - gone)
    import hashlib
    return {"rule_version": str(rule_version), "count": len(kept),
            "sha256": hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()}


def _pre_deploy_main_checkout(tree) -> "Path | None":
    """The main checkout of `tree`'s repository (`cli._main_worktree`), None when none resolves."""
    try:
        from lib.cli import _main_worktree           # lazy: cli is loaded by every verb that gets here
        return _main_worktree(Path(tree))
    except Exception:                                # noqa: BLE001 — unresolved: the caller skips nothing
        return None


def _pre_deploy_skip_read(tree, decl, *, changed, main_root=None, now=None, _rows=None,
                          _known_broken=None, _is_ancestor=None) -> "dict | None":
    """T-14211 (SPEC-1051 rule 2) — `_pre_deploy_skip_set` of the run over `tree`, its inputs read: the
    final failures, passes and between-deploys results from the MAIN checkout's journal through the
    segment-aware reader (`main_root`, else `_pre_deploy_main_checkout(tree)`), the open known-broken
    records by the SPEC-0181 fold, the `always` files of `tree/tests`, the uncovered bound in force for
    `tree`'s contract. None where `decl` lists no unit class. A read that fails skips nothing: the
    journal → `uncovered` (`unreadable`), anything else → `not-applied` naming it. The record also
    names the bound (`{key, value, source}`). Reads only."""
    if not isinstance(decl, dict) or not decl.get("listed_classes"):
        return None
    base = {"order": "listed", "classes": sorted(decl["listed_classes"])}

    def _not_applied(why):
        return {**base, "state": "not-applied", "reason": why, "units": [], "kept": []}

    main = Path(main_root) if main_root is not None else _pre_deploy_main_checkout(tree)
    if main is None:
        return _not_applied("main-checkout-unresolved")
    from lib import machine_settings
    try:
        path = Path(tree) / "yitc-ops.yaml"
        bound = machine_settings.in_force(PRE_DEPLOY_UNCOVERED_KEY,
                                          ops=state.load_ops(path) if path.is_file() else None)
    except Exception as e:                           # noqa: BLE001
        return _not_applied(f"bound-unreadable: {type(e).__name__}")
    try:
        if _rows is not None:
            rows = list(_rows)
        else:
            rows = [(ev.get("ts"), ev.get("data")) for ev in journal_mod.segment_rows(
                main / "events.jsonl", types=(_PRE_DEPLOY_RESULT_EVENT,))
                if isinstance(ev, dict) and ev.get("type") == _PRE_DEPLOY_RESULT_EVENT]
    except Exception:                                # noqa: BLE001 — unreadable: uncovered, skip nothing
        rows = None
    try:
        if _known_broken is not None:
            broken = set(_known_broken)
        else:
            from lib import debt as _debt, debt_adoption as _da
            broken = {_da._known_broken_file(r.get("pair")) for r in
                      _debt.open_known_broken(main / "events.jsonl", root=main).get("broken") or ()
                      if isinstance(r, dict)}
        from lib import verify_runner as _vr
        tests_dir = Path(tree) / "tests"
        always = ({f"tests/{n}" for n in _vr._selection_always_set(tests_dir)[0]}
                  if tests_dir.is_dir() else set())
    except Exception as e:                           # noqa: BLE001
        return _not_applied(f"protected-set-unreadable: {type(e).__name__}")
    if _is_ancestor is None:
        from lib import debt as _debt
        _is_ancestor = lambda a, b: True if a == b else _debt._git_is_ancestor(main, a, b)   # noqa: E731
    rec = _pre_deploy_skip_set(decl, rows=rows, known_broken=broken, always=always, changed=changed,
                               now=time.time() if now is None else now, bound_hours=bound["value"],
                               is_ancestor=_is_ancestor)
    rec["bound"] = {"key": bound["key"], "value": bound["value"], "source": bound["source"]}
    return rec


def _pre_deploy_run_skip(tree, *, changed) -> "dict | None":
    """T-14211 — the skip set of a run over `tree` as its own contract declares it
    (`_pre_deploy_contract_kw` → `_pre_deploy_skip_read`); None where it declares no listed class or
    the declaration is refused. Never raises: a fault is a `not-applied` record."""
    try:
        decl = _pre_deploy_contract_kw(tree).get("pre_deploy")
        return _pre_deploy_skip_read(tree, decl, changed=changed) if decl is not None else None
    except Exception as e:                           # noqa: BLE001 — a fault skips nothing, said on the row
        return {"order": "listed", "state": "not-applied", "reason": f"error: {type(e).__name__}",
                "units": [], "kept": []}


def _pre_deploy_skip_units(inventory, rec) -> tuple:
    """T-14211 (SPEC-1051 rule 2) — an adapter layer's `list` inventory with the skip set `rec` taken
    out: `(kept, removed, held)`; `removed` `{file, project?, class}` in inventory order, `held` the
    files of the skip set this inventory keeps. ONE closure decides what stays, so a file is never kept
    in one context and removed in another: a file stays when it is not in the skip set, or when ANY of
    its units sits in an indivisible group with a unit that stays — repeated until nothing changes —
    and every unit of a file that stays, stays. PURE."""
    gone = {u.get("file"): u.get("class") for u in (rec or {}).get("units") or () if isinstance(u, dict)}
    if not gone or not inventory:
        return inventory, [], []
    stays = {u["file"] for u in inventory if u["file"] not in gone}
    while True:
        groups = {(u.get("project") or "", u["group"]) for u in inventory if u.get("group") and u["file"] in stays}
        more = {u["file"] for u in inventory if u.get("group") and (u.get("project") or "", u["group"]) in groups
                and u["file"] not in stays}
        if not more:
            break
        stays |= more
    kept = [u for u in inventory if u["file"] in stays]
    removed = [{"file": u["file"], **({"project": u["project"]} if u.get("project") else {}), "class": gone[u["file"]]}
               for u in inventory if u["file"] not in stays]
    held = sorted({u["file"] for u in inventory if u["file"] in gone and u["file"] in stays})
    return kept, removed, held


def _pre_deploy_close_skip(rec, inventories) -> dict:
    """T-14211 (SPEC-1051 rule 2; audit-pre fp1:6ce9da53ee97b05f) — the skip set `rec` a run APPLIES,
    closed over EVERY adapter layer inventory of the run BEFORE any layer takes anything out:
    `inventories` `{layer: listed units | None}`. A file stays when it is not in the skip set or when
    ANY of its units, in ANY layer, sits in an indivisible group (layer, project, group) with a unit
    that stays — repeated until nothing changes — so a file kept anywhere is kept everywhere. A layer
    whose `list` did not answer (None) runs whole, so no listed file can leave anywhere: every file of
    the set is held. Returns the record with `units` the files the run leaves out and `held`
    (`{file, class, why: group | inventory-unanswered}`, absent when none) the files it keeps for that
    reason; any other record is returned unchanged. PURE."""
    if not isinstance(rec, dict) or rec.get("state") != "skipping" or not rec.get("units"):
        return rec
    gone = {u["file"]: u["class"] for u in rec["units"]}
    if any(inv is None for inv in inventories.values()):
        stays, why = set(gone), "inventory-unanswered"
    else:
        every = [(ly, u) for ly, inv in inventories.items() for u in inv]
        stays, why = {u["file"] for _ly, u in every if u["file"] not in gone}, "group"
        while True:
            groups = {(ly, u.get("project") or "", u["group"]) for ly, u in every
                      if u.get("group") and u["file"] in stays}
            more = {u["file"] for ly, u in every if u.get("group") and u["file"] not in stays
                    and (ly, u.get("project") or "", u["group"]) in groups}
            if not more:
                break
            stays |= more
    held = [{"file": f, "class": gone[f], "why": why} for f in sorted(gone) if f in stays]
    out = {**rec, "units": [u for u in rec["units"] if u["file"] not in stays]}
    if held:
        out["held"] = held
    return out


def _pre_deploy_allocate(inventories) -> dict:
    """T-14211 (SPEC-1051 rule 3; audit-pre fp1:b42a307a5cb4d1f4, fp1:b5bbfdb3707da850) — the deploy's
    pre-deploy run runs the UNION once: given every adapter layer's inventory in declaration order
    (`{layer: listed units | None}`), decided BEFORE any layer runs, which units each layer drops
    because another layer runs them. A unit is `(project, file)` — one execution context. Groups are
    allocated FIRST and WHOLE: a group whose every unit an earlier group already runs is dropped
    whole; any other group runs whole in its layer. Then each ungrouped unit runs in the first layer
    that lists it and no group already runs it; every other listing drops it. So a unit an ungrouped
    listing took never runs again because a group needs it — the group takes it. What only a second run
    can satisfy — two groups in two layers sharing a unit — is named (`again`), never split. A layer
    whose `list` did not answer (None) runs whole as SPEC-1044 runs it and drops nothing. Returns
    `{layer: {drop: [(project, file)], again: [(project, file)]}}`. Never fewer than once: every dropped
    unit is run by the layer it was allocated to. PURE."""
    out = {ly: {"drop": [], "again": []} for ly in inventories}
    taken: set = set()
    for ly, inv in inventories.items():
        groups: dict = {}
        for u in inv or ():
            if u.get("group"):
                groups.setdefault((u.get("project") or "", u["group"]), []).append((u.get("project") or "", u["file"]))
        for keys in groups.values():
            if all(k in taken for k in keys):
                out[ly]["drop"] += keys
            else:
                out[ly]["again"] += [k for k in keys if k in taken]
                taken.update(keys)
    for ly, inv in inventories.items():
        for u in inv or ():
            if not u.get("group"):
                k = (u.get("project") or "", u["file"])
                (out[ly]["drop"].append(k) if k in taken else taken.add(k))
    return out


def _pre_deploy_inventories(worktree, items, *, _run_layer_command) -> dict:
    """T-14211 — each adapter layer's `list` answer, read ONCE per run BEFORE any layer runs: `items`
    `[(layer, adapter declaration, timeout)]` in declaration order; `{layer: {units, memberships,
    versions} | None}` — None where `list` did not answer. `_pre_deploy_close_skip` and
    `_pre_deploy_allocate` decide over `units`, and the layer's own pass then EXECUTES that same answer
    (`pre_deploy["inventories"]`) instead of asking `list` again, so what was decided is what runs. The
    layer's adapter pass, through a launcher that starts `list` and declines every other invocation
    (the `_stage6_partial_needs` way): no `prep:`, no `required:` check, no `run`."""
    def _list_only(cmd, wt, timeout, env, **kw):
        try:
            action = json.loads(Path(env[_VERIFY_ADAPTER_MANIFEST_ENV]).read_text(encoding="utf-8")).get("action")
        except Exception:                                  # noqa: BLE001 — no readable manifest: not started
            action = None
        return _run_layer_command(cmd, wt, timeout, env, **kw) if action == "list" else (None, 0, "")

    import contextlib
    import io
    out: dict = {}
    for name, decl, timeout in items:
        sink: dict = {"memberships": {}}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rec = _layer_adapter_report_pass(worktree, name, decl, timeout=timeout, sink=sink,
                                                 _run_layer_command=_list_only)
        except Exception:                                  # noqa: BLE001 — no inventory: the layer lists itself
            rec = {}
        inv = sink.get("inventory")
        out[name] = ({"units": inv, "memberships": dict(sink.get("memberships") or {}),
                      "versions": rec.get("versions")}
                     if rec.get("list") == "ok" and isinstance(inv, list) else None)
    return out


def _pre_deploy_inventory_units(inventories) -> dict:
    """`{layer: listed units | None}` of `_pre_deploy_inventories`' answer — what the decisions read. PURE."""
    return {ly: (v["units"] if isinstance(v, dict) else None) for ly, v in inventories.items()}


def _pre_deploy_skip_line(where: str, rec) -> str:
    """T-14211 — the one line a run prints for its skip-set record `rec`. PURE."""
    if rec.get("state") != "skipping":
        return (f"{where}: pre-deploy skip set EMPTY — {rec.get('state')} ({rec.get('reason')}); every "
                f"listed unit runs here (SPEC-1051 rule 2)")
    names = [u["file"] for u in rec.get("units") or ()]
    return (f"{where}: pre-deploy skip set: {len(names)} listed unit(s) NOT run here ("
            + ", ".join(names[:5]) + ("" if len(names) <= 5 else f" (+{len(names) - 5} more)")
            + f"), {len(rec.get('kept') or ())} listed unit(s) kept — the deploy's pre-deploy run runs "
            f"them (SPEC-1051 rule 2)")


def _layer_row_listed_none(row) -> bool:
    """T-13994 (SPEC-1032 rule 5) — is this `consumer_verify_layers[]` row the row of a layer whose
    `list` named NO unit on the consumer venue while the plan the host shipped had listed units for it?
    True when the row's `adapter` record carries the box follower's `listed_none` mark (a mapping).
    Such a row's outcome is whatever the run gave, and no land takes a verdict for that layer from
    it. PURE."""
    rec = row.get("adapter") if isinstance(row, dict) else None
    return isinstance(rec, dict) and isinstance(rec.get("listed_none"), dict)


def venue_empty_layers(rows) -> list:
    """T-13994 (SPEC-1032 rule 5) — the layers a consumer venue pass names on its Stage-6 row
    (`verify_metrics.venue_empty_layers`): `[{layer, plan_listed}]`, one per layer name, in row order,
    for every row `_layer_row_listed_none` reads as marked. Empty when none is. PURE."""
    out, seen = [], set()
    for r in rows or ():
        name = r.get("layer") if isinstance(r, dict) else None
        if not isinstance(name, str) or name in seen or not _layer_row_listed_none(r):
            continue
        seen.add(name)
        listed = r["adapter"]["listed_none"].get("plan_listed")
        out.append({"layer": name, "plan_listed": listed if isinstance(listed, int)
                    and not isinstance(listed, bool) else None})
    return out


def _layer_row_is_partial_run(row) -> bool:
    """SPEC-1030 rule 6 (T-13911) — is this `consumer_verify_layers[]` row the row of a PARTIAL run
    of its layer: a run that executed fewer than all of the layer's units? True on EITHER mark the
    writers leave (SPEC-0025): the row's `adapter` record carries the key `partial` (every narrowed
    run — one that failed or timed out, whose outcome says nothing of breadth, included), or the
    row `outcome` is `passed-partial`. The key counts whatever it holds: the writers remove it when
    a run stops being narrowed, so its presence alone says the run was. A row with neither mark —
    every row of a layer under `off` or `shadow`, a full run of a deciding layer, a run whose full
    `command:` ran after a narrowed first attempt — is not one. The ONE predicate the derived
    readings ask (the zero-skip fold, the layer duration creep and step readings). PURE."""
    if not isinstance(row, dict):
        return False
    rec = row.get("adapter")
    return row.get("outcome") == "passed-partial" or (isinstance(rec, dict) and "partial" in rec)


# T-13961 — the CONSUMER arm of the bare `verify-durations` report (SPEC-0132 §6). A consumer whose verify
# is its declared layers (SPEC-0152 rule 16) has no per-file table; its journal already records every
# layer run on `land_completed` / `tests_passed` / `tests_failed` `consumer_verify_layers[]`. This is a
# VIEW over those rows: no store, no event, no gate, nothing written.
# the layer neither ran nor was skipped on such a row, so it is no observation at all
_CONSUMER_LAYER_NOT_OBSERVED = frozenset(("waived", "credited-stage6-run"))
_CONSUMER_LAYER_RED = frozenset(("failed", "prep-failed", "malformed"))
_CONSUMER_LAYER_SOURCES = ("land_completed", "tests_passed", "tests_failed")


def _consumer_layer_ms(v):
    """An int millisecond reading, or None — a bool, a string, a negative, NaN or an infinity (a JSON
    `1e309` decodes to one) is no reading."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        return None
    return int(v)


def _consumer_layer_timeout_s(v):
    """A declared timeout in seconds, or None — the same non-reading shapes as above, and zero."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
        return None
    return float(v)


def _nearest_rank(sorted_vals, q):
    """Nearest-rank percentile of an ascending non-empty list: the value at rank ceil(q*n)."""
    return sorted_vals[max(1, math.ceil(q * len(sorted_vals))) - 1]


def _consumer_layer_duration_fold(rows, *, window=100, top_k=5):
    """PURE — journal rows -> the per-layer duration table (T-13961, SPEC-0132 §6 consumer arm).

    The window is the newest `window` `land_completed` rows and the newest `window` Stage-6 rows
    (`tests_passed` / `tests_failed`), ordered by `ts`, whose `consumer_verify_layers` is a non-empty
    list. Per layer: `observed` = rows naming it, minus a row whose layer did not run and was not skipped
    (waived, credited to a Stage-6 run) and a partial run (`_layer_row_is_partial_run`); `skipped` = the
    observed rows whose outcome is `skipped-disjoint-subject`; `runs` = the observed rows carrying a
    millisecond `duration_ms`, over which median / p90 / max / sum are taken (nearest rank); `timeouts` =
    outcome `timed-out`; `reds` = failed / prep-failed / malformed; `timeout_s` = the declared timeout on
    the newest row naming the layer that carries one — ANY such row, skipped and not-observed rows
    included, since the declaration is not a run. An adapter-backed layer adds its `units[]` (per file: runs, median, sum,
    share of the layer's summed unit time), top `top_k` by sum."""
    lands, stage6 = [], []
    for e in rows:
        if not isinstance(e, dict):
            continue
        d = e.get("data")
        layers = d.get("consumer_verify_layers") if isinstance(d, dict) else None
        if not isinstance(layers, list) or not layers:
            continue
        t = e.get("type")
        if t == "land_completed":
            lands.append(e)
        elif t in ("tests_passed", "tests_failed"):
            stage6.append(e)
    key = lambda e: str(e.get("ts") or "")
    lands = sorted(lands, key=key)[-window:] if window > 0 else []
    stage6 = sorted(stage6, key=key)[-window:] if window > 0 else []
    table: dict = {}
    declared: dict = {}                    # layer -> [timeouts in ts order], from every row naming it
    for e in sorted(lands + stage6, key=key):
        for r in e["data"]["consumer_verify_layers"]:
            if not isinstance(r, dict):
                continue
            name = r.get("layer")
            if not isinstance(name, str) or not name.strip():
                continue
            tmo = _consumer_layer_timeout_s(r.get("timeout_s"))
            if tmo is not None:
                declared.setdefault(name.strip(), []).append(tmo)
            outcome = r.get("outcome")
            if outcome in _CONSUMER_LAYER_NOT_OBSERVED or _layer_row_is_partial_run(r):
                continue
            L = table.setdefault(name.strip(), {"observed": 0, "skipped": 0, "durations": [],
                                                "timeouts": 0, "reds": 0, "units": {}})
            L["observed"] += 1
            if outcome == "skipped-disjoint-subject":
                L["skipped"] += 1
                continue
            if outcome == "timed-out":
                L["timeouts"] += 1
            elif outcome in _CONSUMER_LAYER_RED:
                L["reds"] += 1
            ms = _consumer_layer_ms(r.get("duration_ms"))
            if ms is None:
                continue
            L["durations"].append(ms)
            rec = r.get("adapter")
            units = rec.get("units") if isinstance(rec, dict) else None
            for u in units if isinstance(units, list) else ():
                if not isinstance(u, dict) or not isinstance(u.get("file"), str) or not u["file"]:
                    continue
                ums = _consumer_layer_ms(u.get("duration_ms"))
                if ums is not None:
                    L["units"].setdefault(u["file"], []).append(ums)
    out = {}
    for name, L in table.items():
        ds = sorted(L["durations"])
        tmos = declared.get(name, [])
        row = {"observed": L["observed"], "skipped": L["skipped"], "runs": len(ds),
               "median_ms": _nearest_rank(ds, 0.5) if ds else None,
               "p90_ms": _nearest_rank(ds, 0.9) if ds else None,
               "max_ms": ds[-1] if ds else None, "sum_ms": sum(ds) if ds else None,
               "timeouts": L["timeouts"], "reds": L["reds"], "timeout_s": tmos[-1] if tmos else None,
               "timeout_range": (min(tmos), max(tmos)) if tmos else None, "units": []}
        total = sum(sum(v) for v in L["units"].values())
        if total > 0:
            ranked = sorted(L["units"].items(), key=lambda kv: (-sum(kv[1]), kv[0]))[:top_k]
            row["units"] = [{"file": f, "runs": len(v), "median_ms": _nearest_rank(sorted(v), 0.5),
                             "sum_ms": sum(v), "share": sum(v) / total} for f, v in ranked]
        out[name] = row
    return {"lands": len(lands), "stage6": len(stage6), "layers": out}


def _consumer_layer_durations_report(events_path, *, window=None) -> list:
    """T-13961 — the printed lines of the consumer arm (read through the segment-aware reader, SPEC-0190)."""
    window = window or 100        # the `--last` default: the newest 100 records of EACH source
    try:
        rows = journal_mod.segment_rows(events_path, types=_CONSUMER_LAYER_SOURCES)
    except (OSError, UnicodeDecodeError):
        rows = []
    fold = _consumer_layer_duration_fold(rows, window=window)
    if not fold["layers"]:
        return [f"verify-durations: {events_path} records no consumer verify-layer row "
                f"(`consumer_verify_layers` on land_completed / tests_passed / tests_failed) — "
                f"nothing to tabulate."]
    s = lambda ms: "-" if ms is None else f"{ms / 1000.0:.1f}s"
    w = max(5, max(len(n) for n in fold["layers"]))
    lines = [f"verify-durations: consumer verify layers from {events_path} — the newest "
             f"{fold['lands']} land record(s) and {fold['stage6']} Stage-6 run record(s) that carry "
             f"layer rows (at most {window} of each, `--last`):",
             f"  {'layer':<{w}} {'obs':>4} {'skip%':>6} {'runs':>5} {'median':>8} {'p90':>8} "
             f"{'max':>8} {'sum':>9} {'tmo':>4} {'reds':>5}  timeout"]
    for name in sorted(fold["layers"]):
        r = fold["layers"][name]
        skip = f"{100.0 * r['skipped'] / r['observed']:.0f}%" if r["observed"] else "-"
        tmo = r["timeout_s"]
        flag = (" !" if tmo is not None and r["p90_ms"] is not None and r["p90_ms"] / 1000.0 > tmo
                else "")
        rng = r["timeout_range"]
        tmo_txt = ("-" if tmo is None else f"{tmo:.0f}s" if rng is None or rng[0] == rng[1]
                   else f"{tmo:.0f}s (window {rng[0]:.0f}-{rng[1]:.0f}s)")
        lines.append(f"  {name:<{w}} {r['observed']:>4} {skip:>6} {r['runs']:>5} {s(r['median_ms']):>8} "
                     f"{s(r['p90_ms']):>8} {s(r['max_ms']):>8} {s(r['sum_ms']):>9} {r['timeouts']:>4} "
                     f"{r['reds']:>5}  {tmo_txt}{flag}")
    for name in sorted(fold["layers"]):
        units = fold["layers"][name]["units"]
        if not units:
            continue
        lines.append(f"  top units of '{name}' by summed duration (adapter rows):")
        for i, u in enumerate(units, 1):
            lines.append(f"    {i}. {s(u['sum_ms']):>9} {100.0 * u['share']:5.1f}%  {u['file']} "
                         f"({u['runs']} run(s), median {s(u['median_ms'])})")
    lines.append("  Report-only: read from journal rows, nothing written. '!' = the newest declared "
                 "timeout is under the measured p90; obs excludes waived, Stage-6-credited and "
                 "partial-run rows.")
    return lines


def _adapter_full_command_ran(rec):
    """SPEC-1030 rule 4 — the layer's full `command:` ran after a first attempt whose record is
    `rec` (a void report with a zero exit, a faulted pass, the SPEC-0152 rule-16 isolated layer
    re-run). The run as a whole is then NOT narrowed, whatever the first attempt requested: the
    `partial` key is removed and a deciding `selection` reads `decision: full`, `reason:
    full-command-ran`, its rung unchanged and the ladder's own reason kept as `ladder_reason`; a
    deciding `credit` that had credited (`decision: units`) reads `void` / `full-command-ran`
    (T-13909): every unit ran, so nothing is credited. A
    record that carries no `partial` is returned as it is. Changes `rec` in place and returns it."""
    if not (isinstance(rec, dict) and isinstance(rec.get("partial"), dict)):
        return rec
    del rec["partial"]
    pd = rec.get("pre_deploy")
    if isinstance(pd, dict) and pd.get("applied"):      # T-14104: every unit ran after all
        rec["pre_deploy"] = {"applied": False, "reason": "full-command-ran", "units": pd.get("removed") or []}
    sel = rec.get("selection")
    if isinstance(sel, dict) and sel.get("mode") == "deciding":
        sel.update({"ladder_reason": sel.get("reason"), "decision": "full", "reason": "full-command-ran"})
    cred = rec.get("credit")
    if isinstance(cred, dict) and cred.get("mode") == "deciding" and cred.get("decision") == "units":
        cred.update({"decision": "void", "reason": "full-command-ran"})
    return rec


def _adapter_first_attempt(rec) -> str:
    """SPEC-1006 rule 4 — what ONE first-attempt adapter record (`_layer_adapter_report_pass(...,
    first_attempt=True)`) says about its layer. PURE; first match wins:

      command          the record decides NOTHING and the layer's full `command:` runs and decides
                       as the first attempt: the pass faulted (`error`), `list` is absent or
                       unusable for this run, the report is VOID with a ZERO exit, or the profile
                       names a void condition its reports cannot reveal (rule 4 LIMIT);
      timed-out        an invocation (`required:`, `run`) or the reading of its report hit the
                       layer's bound — an OUTER failure: no fallback, no re-run, no rescue;
      required-failed  a `required:` check exited nonzero (rule 5) — the layer fails and nothing
                       re-runs it;
      void-failed      the report is VOID and `run` exited NONZERO: the first attempt failed by its
                       exit code, exactly as a layer without an adapter fails;
      units-failed     the report is USABLE and at least one unit is not `passed` (whatever the
                       exit code says — a failed row is never overridden by a zero exit);
      passed           the report is USABLE and every unit passed — or (T-13907, SPEC-1030
                       rule 2) the record is a NARROWED run's that requested no unit: `run` was
                       not invoked, the `required:` checks ran, and nothing failed.
    Anything this function does not recognise answers `command` — the reading errs toward the full
    layer. A failed `required:` check is read BEFORE a fault of the pass and BEFORE the state of
    `list` (T-13907): on a deciding layer the checks run whatever `list` answered, so one can fail
    where `list` was unusable, and a pass that faulted before they had run records them as failed
    (`exit: None`).
    Under `off` and `shadow` a failed check ends the pass at once, after a usable `list`, so
    there the order changes nothing."""
    if not isinstance(rec, dict):
        return "command"
    if rec.get("outer") == "timed-out":
        return "timed-out"
    required = rec.get("required")
    if isinstance(required, dict) and "failed" in required:
        return "required-failed"
    if rec.get("error") or rec.get("outer") or rec.get("list") != "ok":
        return "command"
    units = rec.get("units")
    if not isinstance(units, list):
        return "command"
    if rec.get("void"):
        return "void-failed" if rec.get("exit") not in (0, None) else "command"
    partial = rec.get("partial")
    none_requested = isinstance(partial, dict) and partial.get("ran") == [] \
        and partial.get("not_reached") == [] and "exit" not in rec
    if rec.get("usable") is not True or (not units and not none_requested):
        return "command"
    return "passed" if all(isinstance(u, dict) and u.get("status") == "passed" for u in units) \
        else "units-failed"


def _adapter_invocations_output(invocations) -> "tuple[str, str | None]":
    """Render what a pass's `required:` and `run` invocations printed (`sink["invocations"]`) as
    ONE text, every invocation under its own header line

        ── <n>. <label> (exit <code> | hit the bound): <command> ──

    where `<n>` is the invocation's order in the pass. The invocations that PASSED (exit 0) come
    first and the ones that did not come LAST, each group in invocation order: the layer output
    log is bounded tail-preserving, so what a failing invocation printed is what survives the
    bound — whichever project ran last. Returns `(text, command)`: `command` is the command of the
    last invocation that did not pass (None when every one passed, or none ran). PURE."""
    rows = [(n, inv) for n, inv in enumerate(invocations or [], start=1) if isinstance(inv, dict)]
    ordered = [r for r in rows if r[1].get("exit") == 0] + [r for r in rows if r[1].get("exit") != 0]
    parts = []
    for n, inv in ordered:
        how = "hit the bound" if inv.get("exit") is None else f"exit {inv['exit']}"
        body = str(inv.get("output") or "")
        parts.append(f"── {n}. {inv.get('label')} ({how}): {inv.get('command')} ──\n"
                     + body + ("" if body.endswith("\n") or not body else "\n"))
    failing = [inv for _n, inv in rows if inv.get("exit") != 0]
    return "".join(parts), (failing[-1].get("command") if failing else None)


#: T-14298 — a unit failure text carrying a runner's STOP message for a timeout — a line that BEGINS
#: with it (go's `panic: test timed out`, pytest-timeout's `+++ Timeout +++`, a bare `Timeout` /
#: `Timed out` notice): the text's names are not read, as for a kernel file killed by its bound. A
#: test merely NAMED after a timeout (`● Client › handles timeout`, `--- FAIL: TestTimeout`) begins
#: with its own marker, so it is still named.
_UNIT_TIMEOUT_RE = re.compile(r"^\s*(?:panic: test timed out|\+{3,} ?Timeout|Timeout\b|Timed out\b)",
                              re.IGNORECASE | re.MULTILINE)


def _failed_test_names(bad: list, *, timeout_marker: "str | None" = None,
                       test_dir: str = "tests") -> "list[dict]":
    """T-14229 — WHICH TEST inside each failed test file failed: one
    `{"file", "failed_tests", "named"}` record per `test failed: <file>` entry of a verify `bad` list
    (the `[pinned/last-green] ` prefix stripped; a file named twice is one record, its names merged in
    first-seen order). Other entries (a consumer layer banner, a graph-build line) yield nothing. The
    kernel runner's callers reach it through `worktree._failed_test_names`, which supplies the
    verify-timeout marker; the adapter report reader (T-14298) calls it here with none.

    The names are read ONLY from that file's own captured text — the lines after its first — and only
    from these positive markers: a pytest summary line `FAILED|ERROR <path>::<name>` whose path IS the
    file (`<file>` or `<test_dir>/<file>`, a leading `./` dropped — a nested fixture run naming any
    other path, a same-named file elsewhere included, is refused); a `FAIL` / `FAIL:` / `ERROR:`
    marker followed by one `test_`-first identifier that ends the line or is followed by `:`, `(`, `[`
    or a spaced dash (the unittest header and the script drivers' `FAIL: test_<fn>` / `FAIL test_<fn>`;
    a label such as `FAIL smoke` / `FAIL: AC5: ...` and prose such as `FAIL: expected X` name nothing);
    T-14298: a go test `--- FAIL: <Name>` line, and the jest / vitest `✕ <name>` line (a trailing
    `(N ms)` dropped) and `● <suite> › <name>` header — a `●` line without ` › ` names nothing, and a
    `✕` name that a `●` name equals or ends with (` › <name>`) is the same test, named once. A file
    whose text carries no such line — a crash, a script printing prose, or a whole-file timeout (its
    entry carries `timeout_marker`, and a killed file's partial output is not its verdict) — records
    `failed_tests: []`, `named: false`: never a guess. PURE: text in, records out."""
    pytest_re = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)::(.+?)(?:\s+-\s.*)?$")
    marker_re = re.compile(r"^\s*(?:FAIL:?|ERROR:)\s+(test_\w*)"
                           r"(?=\s*$|\s*:|\s*\(|\[|\s+[-\u2013\u2014]\s)")
    go_re = re.compile(r"^\s*--- FAIL: (\S+)")
    jest_x_re = re.compile(r"^\s*\u2715\s+(.+?)(?:\s+\(\d+(?:\.\d+)?\s*m?s\))?\s*$")
    jest_dot_re = re.compile(r"^\s*\u25cf\s+(.+\s\u203a\s.+?)\s*$")
    out: dict = {}
    for b in bad or []:
        s = str(b)
        lines = s.splitlines()
        first = lines[0].replace("[pinned/last-green] ", "", 1).strip() if lines else ""
        if not first.startswith("test failed: "):
            continue
        name = first[len("test failed: "):].strip()
        if not name:
            continue
        rec = out.setdefault(name, {"file": name, "failed_tests": [], "named": False})
        if timeout_marker and timeout_marker in s:
            continue
        own = {name, f"{test_dir}/{name}"}
        crosses: list = []           # jest `✕` names, kept apart until the `●` names are known
        for ln in lines[1:]:
            got = None
            m = pytest_re.match(ln.strip())
            if m:
                path = m.group(1)[2:] if m.group(1).startswith("./") else m.group(1)
                got = m.group(2) if path in own else None
            else:
                m = marker_re.match(ln) or go_re.match(ln) or jest_dot_re.match(ln)
                got = m.group(1) if m else None
                if got is None:
                    m = jest_x_re.match(ln)
                    if m and m.group(1) not in crosses:
                        crosses.append(m.group(1))
            if got and got not in rec["failed_tests"]:
                rec["failed_tests"].append(got)
        for x in crosses:
            if not any(n == x or n.endswith(f" \u203a {x}") for n in rec["failed_tests"]):
                rec["failed_tests"].append(x)
        rec["named"] = bool(rec["failed_tests"])
    return list(out.values())


def _adapter_unit_failure_lines(rows, max_lines: int = 20) -> list:
    """One line per failed case of the failed unit rows of an adapter record, in pytest's
    short-summary shape `FAILED <file>::<case id> - <excerpt>` — the shape the failing-assertion
    surface and the Stage-6 attribution already read off a layer's tail. A unit with no case rows
    (a script-style file) reads `FAILED <file>::(file) - <excerpt>`; a runner project is named
    after the case id. The excerpt is collapsed onto the line. At most `max_lines`, the rest
    stated as a count — whole lines only. PURE."""
    lines: list = []
    for u in rows or []:
        if not isinstance(u, dict) or u.get("status") == "passed":
            continue
        name = str(u.get("file"))
        proj = f" [project {u['project']}]" if u.get("project") else ""
        cases = [c for c in (u.get("failed_cases") or []) if isinstance(c, dict)]
        for c in cases:
            lines.append(f"FAILED {name}::{c.get('id')}{proj} - " + " ".join(str(c.get("excerpt") or "").split()))
        if u.get("failed_cases_more"):
            lines.append(f"FAILED {name}::(and {u['failed_cases_more']} more failed case(s)){proj}")
        if not cases:
            lines.append(f"FAILED {name}::(file){proj} - " + " ".join(str(u.get("excerpt") or u.get("status")).split()))
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... and {len(lines) - max_lines} more failed line(s) not shown"]
    return lines


def _adapter_rerun_entities(units, inventory) -> list:
    """SPEC-1006 rules 2, 10 — WHAT is re-run for the failed units of a usable first attempt. A
    unit that belongs to no declared group is re-run alone; a unit of a declared indivisible group
    takes its WHOLE group with it (every inventory unit of the same runner project carrying the
    same `group` label), and the group is re-run and counted as ONE. Returns one entity per failed
    unit or group, in the order the report first names a failed member:

      {"project", "unit" | "group", "units": [inventory entries to run], "first": [the failed unit
       rows of the first attempt]}

    `units` are the first attempt's unit rows, `inventory` the listed units (`sink["inventory"]`).
    A failed row the inventory does not hold makes no entity (it cannot be asked for). PURE, and
    LINEAR in the inventory plus the rows: the inventory is walked ONCE — into the unit index and
    the group membership index — so a report with many failed units costs no scan per unit.

    T-13985 (SPEC-1033 rule 10) — THE FAILED CASES OF A UNIT. A unit entity (never a group) whose
    first-attempt row reads `failed` and names EVERY failed case of the unit — `failed_cases`
    non-empty, each `id` a non-empty string, and no `failed_cases_more` (the row's bound left none
    uncounted) — runs a COPY of its inventory entry carrying `cases`: those ids, deduplicated, in
    the report's order. Any other failed unit runs its entry as listed — the whole unit. The
    inventory itself is never changed, and the entity's identity (`unit`, `project`) is the unit's
    either way."""
    def _rerun_case_ids(row):
        named = row.get("failed_cases")
        if row.get("status") != "failed" or row.get("failed_cases_more") or not isinstance(named, list) \
                or not named or not all(isinstance(c, dict) and isinstance(c.get("id"), str) and c["id"]
                                        for c in named):
            return None
        return list(dict.fromkeys(c["id"] for c in named))

    listed: dict = {}
    grouped: dict = {}       # (project, group label) -> its inventory units, in inventory order
    for u in inventory or []:
        if not isinstance(u, dict):
            continue
        uid = (str(u.get("project") or ""), str(u.get("file")))
        listed[uid] = u
        if u.get("group"):
            grouped.setdefault((uid[0], u["group"]), []).append(u)
    entities, by_key = [], {}
    for row in units or []:
        if not isinstance(row, dict) or row.get("status") == "passed":
            continue
        uid = (str(row.get("project") or ""), str(row.get("file")))
        entry = listed.get(uid)
        if entry is None:
            continue
        group = entry.get("group")
        key = (uid[0], "group", group) if group else (uid[0], "unit", uid[1])
        ent = by_key.get(key)
        if ent is None:
            cases = None if group else _rerun_case_ids(row)
            ent = {"project": uid[0], "units": grouped[(uid[0], group)] if group else
                   [entry if cases is None else {**entry, "cases": cases}], "first": []}
            ent["group" if group else "unit"] = group or uid[1]
            by_key[key] = ent
            entities.append(ent)
        ent["first"].append(row)
    return entities


def _layer_unit_reruns(worktree, layer: str, decl: dict, entities, *, timeout, env=None,
                       _run_layer_command, _load_avg=None, _monotonic=None, attempts: int = 2,
                       max_failed_cases: int = 20, outputs=None, unit_medians=None) -> list:
    """SPEC-1006 rule 10 — re-run the failed units of ONE layer's usable first attempt, alone
    within this verify (the caller runs this after every layer has finished), up to `attempts`
    (R) times, stopping per unit at its first pass. Returns one `flaky_retry` row per entity
    (`_adapter_rerun_entities`), registered in SPEC-0025:

      {layer, unit | group, project?, isolated, lane?, first_failed_cases?, first_failed_cases_more?,
       first_excerpt?, attempts: [{status, load1?, duration_ms?, failed_cases?,
       failed_cases_more?, excerpt?, void?}]}

    `isolated` is `pass` when an attempt ran the entity and EVERY one of its units read passed,
    else `fail`. `lane` is true when a failed unit of the entity ran in the layer's load-sensitive
    lane on the first attempt (T-13609): the row then is no evidence for lane entry. `first_*` are the FIRST attempt's failed cases (`{id, excerpt}`; for a group the
    id is prefixed with its file) and are present whatever happens next. A row carries at most
    `max_failed_cases` case records per attempt, the rest counted in `*_more` — so a row is
    bounded whatever the size of a declared group (its member files are on the layer row's
    `adapter.units`, each naming its `group`). An attempt's `status` is
    `passed` / `failed` (its failed cases recorded the same way), or one of three readings that
    END the layer's re-runs — nothing rests on a re-run that cannot be read (rule 4):
    `void` (its report voided, the reasons under `void`), `timed-out` (the invocation or its
    reading hit the bound) and `error` (the pass faulted). `load1` is the host 1-minute load read
    just before that attempt's `run` (absent when unmeasurable).

    ONE INVOCATION PER ATTEMPT: every still-failing entity of the layer is handed to one pass
    (`rerun=`), whose manifest asks the adapter to run the units one at a time; a runner whose
    report names no project gets one `run` per project, as on the first attempt.

    ONE BOUND FOR ALL OF A LAYER'S RE-RUNS: `timeout` — the layer's own — is kept as one absolute
    deadline over every attempt, so a layer's re-runs cost at most one more bound, whatever R is.
    An attempt that would start at or past it is recorded `timed-out` and not started.

    `outputs`, when a list is given, receives one `(attempt number, text)` per attempt that ran:
    everything that attempt's invocations printed (`_adapter_invocations_output`), so the caller
    can keep a re-run's own stream beside the first attempt's.

    The verdict is the CALLER's: this function reads and records, and decides nothing."""
    clock = _monotonic or time.monotonic
    deadline = None if timeout is None else clock() + float(timeout)

    def _cases(rows, prefixed):
        out, more, excerpt = [], 0, None
        for r in rows:
            for c in r.get("failed_cases") or []:
                out.append({"id": f"{r.get('file')}::{c.get('id')}" if prefixed else c.get("id"),
                            "excerpt": c.get("excerpt")})
            more += int(r.get("failed_cases_more") or 0)
            excerpt = excerpt or (f"{r.get('file')}: {r['excerpt']}" if prefixed and r.get("excerpt")
                                  else r.get("excerpt"))
        keep = max(0, int(max_failed_cases))
        return out[:keep], more + max(0, len(out) - keep), excerpt

    def _detail(prefix, rows, prefixed):
        cases, more, excerpt = _cases(rows, prefixed)
        got = {}
        if cases:
            got[f"{prefix}failed_cases"] = cases
        if more:
            got[f"{prefix}failed_cases_more"] = more
        if excerpt:
            got[f"{prefix}excerpt"] = excerpt
        return got

    out = []
    for ent in entities:
        row = {"layer": layer}
        if "group" in ent:
            row["group"] = ent["group"]
        else:
            row["unit"] = ent["unit"]
        if ent.get("project"):
            row["project"] = ent["project"]
        row["isolated"] = "fail"
        if any(r.get("lane") for r in ent["first"]):
            row["lane"] = True       # T-13609: a listed unit's re-run is no evidence for lane ENTRY
        row.update(_detail("first_", ent["first"], "group" in ent))
        row["attempts"] = []
        out.append(row)
    pending = list(range(len(out)))
    for _n in range(max(0, int(attempts))):
        if not pending:
            break
        left = None if deadline is None else deadline - clock()
        if left is not None and left <= 0:
            for i in pending:
                out[i]["attempts"].append({"status": "timed-out"})
            break
        attempt_sink: dict = {}
        rec = _layer_adapter_report_pass(
            worktree, layer, decl, timeout=left, env=env, _run_layer_command=_run_layer_command,
            _load_avg=_load_avg, _monotonic=_monotonic, sink=attempt_sink, unit_medians=unit_medians,
            rerun=[u for i in pending for u in entities[i]["units"]])
        if outputs is not None:
            outputs.append((_n + 1, _adapter_invocations_output(attempt_sink.get("invocations"))[0]))
        measured = {k: rec[k] for k in ("load1", "duration_ms") if k in rec}
        unreadable = ("timed-out" if rec.get("outer") else "error" if rec.get("error") else
                      "void" if rec.get("usable") is not True else None)
        if unreadable:
            for i in pending:
                out[i]["attempts"].append({"status": unreadable, **measured,
                                           **({"void": list(rec["void"])} if rec.get("void") else {})})
            break
        got = {(str(u.get("project") or ""), str(u.get("file"))): u for u in rec.get("units") or []}
        still = []
        for i in pending:
            rows = [got.get((str(u.get("project") or ""), str(u.get("file")))) for u in entities[i]["units"]]
            passed = bool(rows) and all(r is not None and r.get("status") == "passed" for r in rows)
            attempt = {"status": "passed" if passed else "failed", **measured}
            if passed:
                out[i]["isolated"] = "pass"
            else:
                attempt.update(_detail("", [r for r in rows if r is not None and r.get("status") != "passed"],
                                       "group" in entities[i]))
                still.append(i)
            out[i]["attempts"].append(attempt)
        pending = still
    return out
