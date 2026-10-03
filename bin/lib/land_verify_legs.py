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
import json
import math
import os
import re
import sys
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
    (`_VERIFY_IMPLEMENTATION_GLOBS` / `_SUBJECT_VERIFY_INFRA_GLOBS`) is ROOT-relative, and the only
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


def _declared_check_surface_globs(W: Path, merged_base: str, *, _run_git_cap, CONSUMER_OPS_CONTRACT, _load_ops_carrier_text, _declared_verify_infra_globs, _pinned_declared_check_paths) -> list:
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
        ops = _load_ops_carrier_text(text)
        # T-12587 — the project's EXPLICIT `verify.infra_globs` declaration joins the SAME union, from
        # BOTH carriers (the trigger's fail-OPEN-toward-arming bias, unchanged). Taken verbatim: an
        # explicit glob is the project's stated intent, so the root-level exclusion below — written for
        # DERIVED command operands, which are as likely the subject as a check — does not apply to it;
        # over-firing is the safe side (SPEC-0077 §1). Refused (subtractive) entries contribute nothing
        # here; they are REFUSED BY NAME at the declaration read (`_floor_declaration_refusals`).
        paths.update(_declared_verify_infra_globs(ops)[0])
        for p in _pinned_declared_check_paths(ops):
            if len(Path(p).parts) < 2:
                # The SAME root-level exclusion the overlay applies (see `_run_pinned_verify`): a
                # root-level operand is as likely to be the SUBJECT as a check. Keeping it out here too
                # is what stops the trigger OVER-firing on an ordinary product change — SPEC-0077's own
                # failure-threshold names «fires on a NON-verify-path land» as a defect of this gate.
                continue
            paths.add(p)
            paths.add(f"{p}/**")
    return sorted(paths)


def _declared_check_surface_touch(changed_files, W: Path, merged_base: str, *, _run_git_cap, _is_verify_implementation_touch, _declared_check_surface_globs) -> bool:
    """True iff any changed path falls on a check surface the ops carrier DECLARES (the globs above).
    The declaration-derived EXTENSION of `_is_verify_implementation_touch`'s static root-level set —
    same fnmatch idiom, same REPO_ROOT-relative paths, evaluated only when the static set did not
    already fire. Best-effort: no declared surface (the engine's own land, a carrier-less repo) → False,
    leaving the established predicate exactly as it was."""
    globs = _declared_check_surface_globs(W, merged_base, _run_git_cap=_run_git_cap)
    if not globs:
        return False
    return _is_verify_implementation_touch(changed_files, _VERIFY_IMPLEMENTATION_GLOBS=globs)


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


def _verify_bound_source(declared: "float | None", effective: float) -> str:
    """T-10931 (AC2) — NAME which rung of the T-10257 precedence chain produced an already-resolved
    verify bound, so a killed-by-bound abort tells an operator WHERE to change the number (or that
    nobody declared one) instead of just quoting a bare figure.

    STRICTLY a labeller, NEVER a second resolver (CHARTER §P5): it takes the value
    `_verify_test_timeout_seconds` ALREADY returned and reports which input it matches. It cannot
    disagree with the resolver about the bound, because it never computes one — a divergence could only
    ever change the WORDS in a message, never which bound is enforced. The rungs are checked in the
    resolver's own precedence order, so an env override that happens to equal the declaration is
    attributed to the env, exactly as the resolver decided it."""
    raw = os.environ.get("YITC_VERIFY_TEST_TIMEOUT")
    if raw:
        try:
            if float(raw) == effective:
                return "set by the YITC_VERIFY_TEST_TIMEOUT env escape hatch"
        except (TypeError, ValueError):
            pass
    if declared is not None:
        try:
            if float(declared) == effective:
                return "set by the layer's declared `timeout:` / `verify.timeout_seconds:`"
        except (TypeError, ValueError):
            pass
    return "the global default — NO timeout was declared for this layer"


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
    escape is refused, so `npm ci` never runs against files outside the prepared worktree). The kernel
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
    # section's `verify.timeout_seconds:` · the 300s default). It used to be hoisted only for `npm ci`
    # below, while the runtime probe carried a HARDCODED 30s — a bound nobody declared, silently
    # overriding the declaration T-10257 exists to honour, one level further in.
    effective_timeout = _verify_test_timeout_seconds(declared_timeout)
    bound_source = _verify_bound_source(declared_timeout, effective_timeout)
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


def _declared_layer_worker_shares(sec: dict, layers) -> dict:
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
    A layer with no entry is simply unsplit — it reads the whole allotment, exactly as today."""
    if "layer_worker_shares" not in sec:
        return {}
    raw = sec.get("layer_worker_shares")
    if not isinstance(raw, dict):
        raise ValueError(f"{raw!r} is not a mapping of layer name -> fraction")
    declared = {str(ly.get("layer")).strip() for ly in (layers if isinstance(layers, list) else [])
                if isinstance(ly, dict) and isinstance(ly.get("layer"), str) and ly.get("layer").strip()}
    out: dict = {}
    for name, share in raw.items():
        if not (isinstance(name, str) and name.strip()):
            raise ValueError(f"layer_worker_shares key {name!r} is not a non-empty layer name string")
        key = name.strip()
        if key not in declared:
            raise ValueError(f"layer_worker_shares[{key!r}] matches no declared `layers[].layer`")
        if not (isinstance(share, (int, float)) and not isinstance(share, bool) and 0 < share <= 1):
            raise ValueError(f"layer_worker_shares[{key!r}] = {share!r} is not a fraction in (0, 1] "
                             f"— a SHARE of the allotment, never a core count")
        out[key] = share
    return out


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
    and stops. Pure + total: every read is bounded and every exception swallowed."""
    text = command
    reads = 0
    seen = set()
    frontier = [command]                # level 0: the command string itself
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


def _run_layer_command(cmd, worktree, timeout, env):
    """T-12589 — run ONE verify layer command on the terms `subprocess.run(cmd, shell=True, cwd,
    capture_output=True, text=True, timeout, env)` had, but reap it with `os.wait4` so the reading is
    the command's OWN rusage (the shell plus every descendant it waited for) — not the process-wide
    RUSAGE_CHILDREN, which also carries the CPU sampler's docker calls and any sibling child (audit-post
    fp1:c9c00b16712f099c). Returns `(CompletedProcess, process_cpu_ms)`, or `(None, process_cpu_ms)`
    when the bound expired and the command was killed."""
    import signal
    import subprocess
    import threading
    p = subprocess.Popen(cmd, shell=True, cwd=str(worktree), stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, env=env, start_new_session=True)
    box = {}
    readers = [threading.Thread(target=lambda k=k, s=s: box.__setitem__(k, s.read()), daemon=True)
               for k, s in (("out", p.stdout), ("err", p.stderr))]
    for t in readers:
        t.start()
    deadline = None if timeout is None else time.monotonic() + timeout
    timed_out = False
    while True:
        pid, status, ru = os.wait4(p.pid, os.WNOHANG)
        if pid:
            break
        if deadline is not None and time.monotonic() >= deadline:
            # T-12849: signal the layer's whole process GROUP (its own session, above) — `sh` forks a
            # simple command, so killing the shell alone leaves the grandchild holding the reader pipes
            # open and the wall runs past the layer's own timeout.
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                p.kill()
            _, status, ru = os.wait4(p.pid, 0)
            timed_out = True
            break
        time.sleep(0.02)
    p.returncode = os.waitstatus_to_exitcode(status)
    for t in readers:
        t.join(timeout=5 if timed_out else None)   # a surviving grandchild may hold a pipe open
    proc_ms = int(round((ru.ru_utime + ru.ru_stime) * 1000))
    # T-12758 (X-1478 item 8): the WHOLE captured stream, returned as a THIRD element on BOTH arms.
    # The timeout arm used to discard it entirely — `r is None` was the only thing the caller got, so a
    # layer KILLED BY ITS BOUND left no record of what it had printed before the kill. The caller
    # persists this as a land-log artifact on a failing outcome; the `r is None` timeout sentinel and
    # the exit-code gate are untouched.
    captured = (box.get("out", "") or "") + (box.get("err", "") or "")
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


def _verify_duration_samples_from_journal(main_wt: Path, limit: int, *, _run_git_cap, _VERIFY_DURATION_SERIES_UNIT_MS) -> "list":
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
    caller downstream works in milliseconds."""
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
                    path, ['"land_completed"']):
                for raw in reversed(slice_lines):
                    yield raw.decode("utf-8", "replace")
        except OSError:
            return

    for ln in _newest_first():
        if len(out) >= limit:
            break
        if '"land_completed"' not in ln:
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e.get("type") != "land_completed":
            continue
        d = e.get("data") or {}
        vm = d.get("verify_metrics") or {}
        if d.get("status") != "ok" or vm.get("fail_class") != "ok":
            continue
        series = ((vm.get("per_file_durations") or {}).get("duration_series") or {})
        if series.get("order") != "alphabetical" or not series.get("walls_ds"):
            continue
        sha = d.get("sha")
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
        if len(names) != len(vals):
            continue                       # the row and its tree disagree — skip it whole
        unit = max(1, int(series.get("unit_ms") or _VERIFY_DURATION_SERIES_UNIT_MS))
        out.append({n: v * unit for n, v in zip(names, vals)})
    return out


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
                                              types=("land_completed", *rows_out_types))
    except OSError:
        return out
    if rows_out is not None:
        rows = list(rows)
        rows_out.extend(rows)
    for e in rows:
        if not isinstance(e, dict) or e.get("type") != "land_completed":
            continue
        ts = str(e.get("ts") or "")
        if not ts or ts < since or ts > until:
            continue
        data = e.get("data")
        metrics = data.get("verify_metrics") if isinstance(data, dict) else None
        rec = metrics.get("flaky_retry") if isinstance(metrics, dict) else None
        if not isinstance(rec, dict):
            continue
        legs = [(None, rec)] if "rows" in rec else [(k, v) for k, v in rec.items()]
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
                key = (ts, stamped, name)
                if key in seen:
                    continue
                seen.add(key)
                out.setdefault(name, []).append(
                    f"events.jsonl#ts={ts}" + (f":{stamped}" if stamped else ""))
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


# T-13138 (X-1687) — THE FIELDS the two scaling-signal folds below read from each land's `data`, and
# nothing else. The land tail keeps only this projection of every ok `land_completed` row: measured on
# the kernel checkout, the full `data` of its 7,798 ok land rows is ~30 MB of JSON (~150 MB parsed —
# `selection_ran_tests` alone is 13.6 MB) while these fields are 1.6 MB. A signal that reads a NEW field
# must add it here; `tests/test_t13138_land_journal_memory.py` pins projected == full on every field.
_SCALING_METRICS_FIELDS = ("verify_wall_ms", "queue_wait_ms", "serial_lane_ms", "serial_lane_files")
_SCALING_PER_FILE_FIELDS = ("wall_ms_pct", "sample_count")


def _scaling_series_projection(d):
    """`d` (one land's `data`) reduced to what `_verify_scaling_signals` + `_verify_duration_drift_signals`
    read — the same values, the same key presence, and a non-dict left AS IS so every `isinstance` test
    in the folds takes the same branch it took on the full row (T-13138)."""
    if not isinstance(d, dict):
        return d
    out = {}
    if "verify_duration_ms" in d:
        out["verify_duration_ms"] = d["verify_duration_ms"]
    if "verify_metrics" in d:
        vm = d["verify_metrics"]
        if isinstance(vm, dict):
            kept = {k: vm[k] for k in _SCALING_METRICS_FIELDS if k in vm}
            if "per_file_durations" in vm:
                pf = vm["per_file_durations"]
                kept["per_file_durations"] = ({k: pf[k] for k in _SCALING_PER_FILE_FIELDS if k in pf}
                                              if isinstance(pf, dict) else pf)
            vm = kept
        out["verify_metrics"] = vm
    return out


def _verify_scaling_signals(series: "list", *, _verify_duration_drift_signals, _VERIFY_QUEUE_BLOCK_FRACTION=_VERIFY_QUEUE_BLOCK_FRACTION, _VERIFY_TIERC_MEDIAN_MS=_VERIFY_TIERC_MEDIAN_MS, _VERIFY_TIERC_P95_MS=_VERIFY_TIERC_P95_MS, _VERIFY_TIERC_QUEUE_BLOCK_RATIO=_VERIFY_TIERC_QUEUE_BLOCK_RATIO) -> "list":
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
    adding a duration threshold here should know it belongs to neither rule."""
    def _wall(d):
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
