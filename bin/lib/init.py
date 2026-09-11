"""cmd_init verb — the `-C <path>` consumer scaffold-delivery bootstrap (T-9380 leaf extraction).

Byte-identical relocation of bin/yitc-v2#cmd_init. A SINGLE low-coupling verb; it back-imports
NOTHING (no host, no lib) — every host global/helper/const it reads is INJECTED as a keyword-only
param by the host residue wrapper at call time, so monkeypatches on the host names stay honored.
Justified spec-less (SPEC-0005 admission — mechanical relocation mints no standing rule).
"""
from __future__ import annotations

import argparse


def _journal_pathspecs(journal_path, root) -> list:
    """The SPEC-0190 logical-journal pathspec view (`lib.events.journal_pathspecs`), for the
    scoped-commit staging sets below — T-11536.

    THE IMPORT IS DEFERRED INTO THE CALL, and that is load-bearing rather than stylistic. This module
    is not always reached through `bin/yitc-v2` (which puts `bin/` on `sys.path`): the verify sandbox
    COPIES the engine and imports `engine/bin/lib/init.py` DIRECTLY, where `lib` is not an importable
    package — a module-level `from lib import ...` there is a hard `ModuleNotFoundError` at import and
    takes the whole file down (measured: test_t10569_derived_read_race.py, on this card's own first
    verify run). Deferring it keeps IMPORTING this module dependency-free, in the same spirit as the
    module-level-constants note below that keeps `cmd_init`'s injected-deps contract untouched; by the
    time any of these staging sites RUNS, the real entry point has long since set `sys.path`."""
    from lib import events as _events
    return _events.journal_pathspecs(journal_path, root)

# ── yitc-ops.yaml ops-contract carrier (SPEC-0093) — MODULE-LEVEL, NOT host-injected ───────────────
# These are pure DATA + a self-contained read/fail-closed, kept local to init.py ON PURPOSE: the seed
# is born declare-or-waive and the deps it would otherwise need (_read_yaml / _die) are host helpers
# whose injection would change cmd_init's signature — and the SPEC-0077 pinned last-green verify runs
# the last-green test_t9380 (which asserts cmd_init's injected-deps via == on a hardcoded list) against
# the new code, so an added injected dep is structurally un-landable for a purely-additive change
# (deviation `pinned-verify-blocks-additive-injected-deps-on-extracted-verb`). Module-level constants +
# an inline yaml read + an inline fail-closed keep the injected-deps contract UNCHANGED.
CONSUMER_OPS_CONTRACT = "yitc-ops.yaml"   # single-SoT filename (SPEC-0093 rule 1: one file at repo root)

# The ops-carrier sweep is GENERIC + registry-driven (T-10037, SPEC-0128 Rule 2): _sweep_ops_carrier
# iterates the KERNEL-derived concern registry (graph/concern-registry.json) instead of a hand-maintained
# per-section branch ladder. Each concern's `presence_policy` + `declare_key` + `waiver_policy` drive the
# generic declare-or-waive stance; a concern whose residual shape is richer than the generic stance NAMES a
# kernel-owned deep-shape validator via its `concern.shape_hook`. The retired hand-maintained slice-1
# constant (deploy/rollback/live_probe) is now just the `presence_policy: mandatory` entries of the
# registry — the mandatory set is derived on demand (`_registry_mandatory_sections`).

# T-10037 (SPEC-0128 Rule 2, decisions/T-10029-audit-adhoc.yaml finding 3): the set of implemented
# kernel-owned deep-shape validators a concern's `concern.shape_hook` may NAME. The `concern:` block is
# the SOLE owner of concern↔hook membership (a hook is referenced from EXACTLY ONE concern block); `graph
# build` cross-checks THIS set against the registry to WARN on a missing (referenced-but-unimplemented) /
# orphan (implemented-but-unreferenced) / duplicate hook. This is a set of validator NAMES only — it holds
# NO concern membership, so it is NOT a second concern registry (the whole point of the exactly-one rule).
# Each name maps to a `_hook_<name>` residual-shape validator (the `_SHAPE_HOOKS` dispatch, defined with
# the sweep below); the generated sweep dispatches to it AFTER the generic stance/XOR check.
_CONCERN_SHAPE_HOOKS: frozenset = frozenset({
    "security_shape", "deploy_policy_shape", "host_config_shape", "tests_shape",
    "inspection_shape", "ui_shape", "verify_shape", "extensions_shape",
    "runtime_delivery_shape", "live_revision_shape", "remote_sync_shape",
    "alert_routing_shape", "sandbox_entry_shape", "freshness_shape",
    "spike_data_safety_shape", "spike_sandbox_shape",
    "verify_policy_pinned_last_green", "reads_exemptions_shape",
    "override_ledger_shape", "runbook_shape",
})

# The BORN-WAIVER SIGNATURE (T-9642) — the literal markers every born-waived section carries verbatim
# in the GENERATED born template (graph/born-ops.yaml, T-10038). The nightly born-waiver-freshness check (bin/lib/nightly.py, SPEC-0105 rule 1)
# matches these to surface a born waiver whose init PLACEHOLDER was never replaced (X-0130). Single SoT:
# the template below MUST embed these exact strings (a coherence test pins it). `MARKER` is the reason
# substring carried by ALL born waivers; `PLACEHOLDER_EXPIRY` is the security waiver's born review-date.
BORN_WAIVER_MARKER = "Initialized via `bin/yitc-v2 init`"
BORN_WAIVER_PLACEHOLDER_EXPIRY = "2026-12-31"

# T-10569 — the born template's COMPLETENESS SENTINEL, the twin of `_BORN_OPS_TERMINATOR` in
# bin/lib/graph.py (which RENDERS it). Duplicated rather than imported because init.py back-imports
# NOTHING by design (module docstring) — the same cross-module-literal shape as BORN_WAIVER_MARKER above,
# and pinned the same way by a coherence probe (tests/test_t10569_derived_read_race.py#P7d) that fails the
# moment the two drift. `_born_ops_template` checks it to decide COMPLETENESS: YAML, unlike the concern
# registry's JSON, still parses after truncation (a shorter-but-valid mapping), so parse-success cannot
# detect a partial read of a concurrent git materialization — a terminator that cannot survive truncation
# can.
BORN_OPS_TERMINATOR = "# ── END born-ops template (generated completeness sentinel — T-10569) ──"

# Born carrier: GENERATED, no longer a literal (T-10038, SPEC-0128 Rule 2 + born decision (i)). The born
# ops-contract carrier TEMPLATE is DERIVED at `graph build` from each concern's `born:` + `born_order:`
# companion on its OWN governing spec (the per-section born-guidance PROSE relocated there — no shape-DSL,
# render-only concat); `_render_born_ops` (bin/lib/graph.py) renders graph/born-ops.yaml and init READS it
# below (the concern-registry.json precedent — _load_concern_registry). The 3 slice-1 sections are still
# born DECLARE-OR-WAIVE (a fresh consumer has no deploy yet — rule 3/6, fail-closed); the `verify:` section
# (rule 16, X-0140) is still the per-layer LAND-VERIFY carrier + legacy-yitc-verify migration (T-9719). The
# BORN_WAIVER_MARKER / _BORN_VERIFY_SECTION_NO_LAYERS_REASON / _BORN_DEPLOY_WAIVER_NO_COMMAND_REASON anchors
# below are pinned (a coherence test) to still appear in the GENERATED template.
# ── Derived-artifact read resilience (T-10569) ─────────────────────────────────────────────────────
# The GENERATED graph/ artifacts this module reads (concern-registry.json, born-ops.yaml) are COMMITTED
# (CHARTER §P5 "derived artifacts are committed"). Their WRITER is already atomic — write_text_atomic =
# mkstemp + fsync + os.replace, established by T-10070 — so it never publishes an empty or partial file.
# GIT does: `worktree new`'s checkout and `land`'s update-from-main merge materialize the working tree
# NON-atomically, so a concurrent reader can catch the file mid-creation. That is the flake class these
# helpers close (3 journaled occurrences: land-verify-flake-concern-registry-rebuild-race-init-read
# 2026-07-12; land-verify-concern-registry-empty-read-under-concurrent-land 2026-07-13;
# fresh-worktree-empty-derived-registry-verify-abort 2026-07-15 — all three `Expecting value: line 1
# column 1`, i.e. json.loads("")). Design = the single survivor of the SPEC-0124 ceiling-convergence
# consult, decisions/T-10569-audit-consult-pre.yaml.
_DERIVED_READ_ATTEMPTS = 6          # 20+40+80+160+320ms = ~620ms budget; see the exhaustion asymmetry
_DERIVED_READ_BACKOFF_S = 0.02


def _committed_derived_blob(path):
    """The artifact's COMMITTED blob (`git show HEAD:graph/<name>`) — read from the object store, which
    no working-tree materialization can race. None when git / HEAD / the path is unavailable (a
    non-repo install), which leaves the caller's fail-closed path intact."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(path.parents[1]), "show", f"HEAD:graph/{path.name}"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _read_derived_artifact(path, *, is_complete):
    """Read a GENERATED graph/ artifact, tolerating the TRANSIENT window in which a concurrent git
    materialization has created the file but not yet written its bytes (T-10569).

    SUCCESS IS COMPLETENESS, NOT NON-BLANKNESS: return early IFF the text is non-blank AND
    `is_complete(text)` — the CALLER's own parse (json for the registry, yaml for the born template).
    A truncated/partial read therefore can never be returned as data: truncated JSON/YAML does not
    parse, so it fails the predicate and is retried. The happy path returns on attempt 0, adding no
    latency to a complete artifact.

    AT EXHAUSTION (~620ms) the two byte-states are treated ASYMMETRICALLY. Both legs are provable, not
    heuristic — which is what a two-identical-reads "stability" test could not be (a slow writer can
    leave identical partial bytes across two retry intervals):

      (i)  NON-EMPTY but still incomplete -> returned VERBATIM so the CALLER's parse/shape check
           fail-closes on it. The committed blob is NEVER consulted for this state, so a stably
           malformed artifact can never be masked by it. Sound because no governed writer can leave a
           non-empty INCOMPLETE artifact standing for 620ms: write_text_atomic publishes only whole
           files, and git's materialization window for these blobs is microseconds — orders of
           magnitude under the budget. Persistence past the budget IS the proof of a real break.

      (ii) ABSENT / EMPTY -> recovered from the COMMITTED blob, announced on stderr. Sound because no
           governed writer ever publishes a 0-byte artifact as a real state, so EMPTY is unambiguously
           not-an-artifact and the committed (conformance-verified, land-gated) blob is restoration,
           not masking. REQUIRED, not just an optimization: the 2026-07-15 occurrence records an empty
           file that PERSISTED until a manual `graph build`, which retry alone cannot recover.

    Returns the artifact TEXT, or None when disk AND blob both yield nothing. Owns NO fail-closed
    judgement of its own — what an unusable artifact MEANS is per-caller
    (lessons/fail-closed-belongs-to-the-reader-not-the-parser.md: fail-closed is a property of a use
    site, not of a parse result)."""
    import sys
    import time

    text = None
    for attempt in range(_DERIVED_READ_ATTEMPTS):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = None
        if text and text.strip() and is_complete(text):
            return text
        if attempt < _DERIVED_READ_ATTEMPTS - 1:
            time.sleep(_DERIVED_READ_BACKOFF_S * (2 ** attempt))

    if text and text.strip():
        return text     # leg (i) — STABLE malformed: the caller fail-closes; never blob-masked

    blob = _committed_derived_blob(path)                     # leg (ii) — ABSENT / EMPTY
    if blob and blob.strip() and is_complete(blob):
        print(f"yitc-v2: init: {path} read EMPTY (a concurrent git materialization left it "
              f"un-written); recovered its COMMITTED blob HEAD:graph/{path.name}. Run `yitc-v2 graph "
              f"build` if this persists.", file=sys.stderr)
        return blob
    return text


def _born_ops_template() -> str:
    """The born ops-contract carrier TEMPLATE — READ from the GENERATED graph/born-ops.yaml (T-10038,
    SPEC-0128 Rule 2). Retires the per-SECTION `_BORN_OPS_YAML` literal: the born is GENERATED at `graph
    build` from each concern's `born:`/`born_order:` companion (the concern-registry.json precedent —
    _load_concern_registry). ENGINE-anchored (parents[2]/graph) so a `-C <consumer>` init reads the KERNEL's
    born template regardless of cwd. GRAPH-FREE plain file read; fail-closed if absent (a derived committed
    artifact is always present after `graph build`).

    T-10569: the read goes through `_read_derived_artifact`, so a concurrent git materialization cannot
    hand back an empty/partial template. This ALSO closes a latent fail-OPEN — the previous body caught
    only OSError, so a transient EMPTY read returned "" and init seeded a silently empty born template
    (strictly worse than the registry's SystemExit, and on a 35KB artifact whose materialization window
    is the wider of the two).

    The `_complete` RE-CHECK below is load-bearing, not belt-and-braces. `_read_derived_artifact` leg (i)
    hands a non-empty INCOMPLETE artifact back VERBATIM precisely so the CALLER fail-closes on it — the
    registry caller does that implicitly (its json.loads raises), but a bare non-blank check here would
    RETURN a truncated template and init would seed it. Fail-closed is a property of a use site, not of
    a parse result (lessons/fail-closed-belongs-to-the-reader-not-the-parser.md), so this caller states
    its own completeness answer explicitly.

    And that answer is NOT "does it parse". This caller's completeness signal is the generated
    BORN_OPS_TERMINATOR sentinel, because a truncated prefix of a YAML mapping still parses as a valid,
    merely-smaller dict — so parse-success would wave a partial read straight through (unlike the concern
    registry, whose truncated JSON always fails to parse). The two callers of `_read_derived_artifact`
    genuinely differ here; each states its own."""
    import sys
    import yaml
    from pathlib import Path

    from lib import state  # CHARTER §P5 one parser library — the derived-artifact reader (T-9740)
    p = Path(__file__).resolve().parents[2] / "graph" / "born-ops.yaml"

    def _complete(t: str) -> bool:
        if not t.rstrip().endswith(BORN_OPS_TERMINATOR):
            return False        # truncated: the terminator cannot survive a partial write
        try:
            return isinstance(state.load_str(t), dict)
        except yaml.YAMLError:
            return False

    text = _read_derived_artifact(p, is_complete=_complete)
    if not (text and text.strip() and _complete(text)):
        print(f"yitc-v2: init: born template {p} is missing, unreadable, or incomplete — run "
              f"`yitc-v2 graph build` to regenerate the derived born carrier (SPEC-0128).", file=sys.stderr)
        raise SystemExit(1)
    return text


def _legacy_cross_tasks_first_content_line(text: str):
    """The FIRST line of a pre-existing CROSS-TASKS.md that is a real un-migrated CROSS ITEM, or None
    when the carrier holds none (T-9492, retombstoned T-10906 / X-0712).

    Returns `(lineno, kind, text)` — 1-based line number, `"cross-item row"` (a markdown list row, the
    shape a cross task was written in) or `"orphan prose"`, and the stripped line — so the caller can
    NAME what it found instead of asserting a bare "has content" (the T-10906 AC3 affordance).

    CROSS-TASKS.md is the RETIRED per-repo cross surface (SPEC-0075/SPEC-0079, both superseded at the
    T-9293 cutover; the live surface is the shared coordination log, SPEC-0084/85/86). A brownfield
    consumer (the X-0083 ai-gateway case) can carry a pre-existing one holding an un-migrated
    feature-request as orphan prose — which init would otherwise SKIP silently (init.py scaffold loop).

    Era-robust detection (NO byte-compare to one template, so an older-era born-empty file is not a false
    positive): strip the MARKUP/scaffold lines — blank lines; headings (`#…`); blockquotes / usage notes
    (`>…`); HTML comments (`<!-- … -->`, INCLUDING every line of a multi-line comment block); and the
    KNOWN born-scaffold parenthetical markers ONLY (a whole-line `(…)` that BEGINS with a known born
    prefix — the born `(empty — born from …)` / `(archive resolved items here …)`). If ANY line remains —
    a cross-task ROW (`- [..]`) or orphan PROSE, INCLUDING an un-migrated note that merely happens to be
    wrapped in parentheses — the file carries un-migrated content.

    NARROWED (T-9796): the parenthetical exemption was formerly ANY whole-line `(…)`, which fail-OPENed —
    an orphan note wholly wrapped in parens (`(remember to migrate the X request)`) read as scaffold and
    the file wrongly counted empty. Only the two known born parenthetical markers are scaffold now
    (fail-closed: an unknown parenthetical is content).

    HTML COMMENTS ARE MARKUP (T-10906 / X-0712 — the load-bearing change). T-10434 deliberately reduced
    migrated v1 carriers to pure TOMBSTONES: an HTML-comment header ("RETIRED v1 CARRIER — …; items moved
    to the cross log at P3") + a `>` archive banner + a `#` heading, carrying ZERO cross items. Those
    comment lines start with `<`, matched no scaffold branch, and so read as un-migrated content — i.e.
    completing the migration CORRECTLY locked a consumer out of `init` on every run (aiseller, reported
    as X-0712). A comment is markup that renders to nothing; it is not a cross item, and the migrated
    end-state is precisely what the guard should let through. The discriminator is POSITIVE and
    structural (the line lies inside an `<!-- … -->` span), never "the bytes differ from one template".
    It stays FAIL-CLOSED at the edges: an UNTERMINATED `<!--` (a comment left open at EOF) is reported as
    content, so a truncated/mangled carrier cannot silently swallow the items after it. The accepted
    bound: an item hidden INSIDE a comment (`<!-- - [open] … -->`) reads as scaffold — it is invisible in
    the rendered document, so it is not an actionable cross item (asserted deliberately in the tests)."""
    in_comment = False
    for i, raw in enumerate(text.splitlines(), start=1):
        ln = raw.strip()
        if in_comment:
            # inside a multi-line `<!-- … -->` block: skip until the terminator, then re-read the tail.
            if "-->" not in ln:
                continue
            in_comment = False
            ln = ln.split("-->", 1)[1].strip()
        while ln.startswith("<!--"):
            if "-->" in ln:
                ln = ln.split("-->", 1)[1].strip()       # comment closed on this line — keep any tail
                continue
            in_comment = True                            # comment stays OPEN into the following lines
            ln = ""
            break
        if not ln:
            continue
        if ln.startswith("#") or ln.startswith(">"):
            continue
        if ln.startswith("(") and ln.endswith(")") and (
                ln.startswith("(empty") or ln.startswith("(archive resolved items here")):
            continue
        kind = "cross-item row" if ln[:2] in ("- ", "* ", "+ ") else "orphan prose"
        return (i, kind, ln)
    if in_comment:
        # fail-closed: an unterminated comment hides the rest of the file from this walk.
        return (len(text.splitlines()), "unterminated HTML comment", "<!-- … (never closed)")
    return None


def _legacy_cross_tasks_has_content(text: str) -> bool:
    """True iff a pre-existing CROSS-TASKS.md carries REAL cross items beyond the migrated end-state
    (T-9492; keyed on items rather than on bytes-differ-from-template since T-10906). Thin predicate over
    `_legacy_cross_tasks_first_content_line` — both callers (the `cmd_init` guard and
    `_sweep_retired_surfaces`) share the ONE classification."""
    return _legacy_cross_tasks_first_content_line(text) is not None


def _sweep_retired_surfaces(repo_root, _run_git_cap, *, apply: bool = True) -> list:
    """ACTIVELY remove a lingering BORN-EMPTY / tombstone retired per-repo surface (T-9610 / X-0110).

    Currently sweeps CROSS-TASKS.md — the RETIRED per-repo cross log (SPEC-0075/SPEC-0079, both superseded
    at the T-9293 cutover; the live surface is the shared coordination log, SPEC-0084/85/86). A consumer
    bootstrapped before the cutover can carry a now-stale born-empty / tombstone CROSS-TASKS.md that
    current init no longer seeds (T-9470) yet never actively removed — so it just lingers (the trend-finder
    X-0110 case: its CROSS-TASKS.md survived migration). init now sweeps it.

    Scope is NARROW and fail-CLOSED: ONLY an empty / tombstone file (`_legacy_cross_tasks_has_content`
    == False) is swept. A CONTENT-BEARING CROSS-TASKS.md is OUT OF SCOPE here — it is already handled by
    the T-9492 hard-fail guard at the TOP of `cmd_init` (it blocks init + tells the operator to migrate),
    so a content-bearing file never reaches this sweep on a non-waived run; on a conscious `--waive` run we
    must STILL NOT delete its un-migrated content. The has-content check fail-closes in either case — this
    sweep adds NO behavior for content-bearing (no dead warn path behind the hard-fail).

    Stages the deletion via `git rm --cached --ignore-unmatch` so a TRACKED file's removal is recorded by
    the bootstrap commit; an UNTRACKED file is just unlinked. Returns the swept relative paths (for the
    event + output); [] when nothing to sweep. Idempotent: a re-run finds nothing to sweep.

    `apply=False` (the T-10271 `--dry-run` preview) computes the WOULD-sweep list without unlinking: the
    unlink is one of the few writes that bypasses the `write_text_atomic` seam, so it needs its own guard."""
    swept: list = []
    ct = repo_root / "CROSS-TASKS.md"
    if ct.exists() and not _legacy_cross_tasks_has_content(ct.read_text(encoding="utf-8")):
        if apply:
            ct.unlink()
            _run_git_cap(["rm", "--cached", "--quiet", "--ignore-unmatch", "--", "CROSS-TASKS.md"],
                         repo_root)
        swept.append("CROSS-TASKS.md")
    return swept


def _is_iso_date(v) -> bool:
    """True iff `v` is a DATE-ONLY ISO date `YYYY-MM-DD` (SPEC-0093 §8): an unquoted YAML date round-trips
    to a `datetime.date`, OR a string of exactly that form. A YAML TIMESTAMP (`datetime.datetime`) or a
    string carrying a time component is REJECTED — the spec requires date-only. SHAPE/FORMAT check only —
    NOT a currency check (whether the date is in the FUTURE is the report-only overdue-recheck view,
    SPEC-0094 §3; the carrier sweep judges shape, never stores/judges computed status — rule 3/7)."""
    import datetime
    if isinstance(v, datetime.datetime):   # a YAML timestamp is NOT a date-only value — reject
        return False
    if isinstance(v, datetime.date):       # an unquoted YAML date (date-only) is accepted
        return True
    if isinstance(v, str):
        s = v.strip()
        # exactly YYYY-MM-DD (10 chars, dashes at 5/8) AND parseable — rejects datetime/longer ISO forms
        if len(s) != 10 or s[4] != "-" or s[7] != "-":
            return False
        try:
            datetime.date.fromisoformat(s)
            return True
        except ValueError:
            return False
    return False


def _load_concern_registry() -> list:
    """Load the KERNEL-derived concern registry (graph/concern-registry.json) — the SINGLE declaration
    source the generic sweep engine iterates (SPEC-0128 Rule 2, T-10037). ENGINE-owned: resolved relative
    to THIS module (bin/lib/init.py → ENGINE_ROOT/graph/concern-registry.json), NOT the consumer cwd, so a
    `-C <consumer>` sweep reads the kernel's concern set regardless of where it runs. GRAPH-FREE — a plain
    JSON read; it never touches the graph builder. FAIL-CLOSED: a missing / unparseable / mis-shaped
    registry is a kernel bug, not a consumer error → SystemExit (never a silent empty roster, which would
    fail-OPEN the whole sweep).

    T-10569: the read goes through `_read_derived_artifact`, so a concurrent git materialization
    (checkout / merge) cannot false-fail it with an empty/partial read. FAIL-CLOSED IS UNCHANGED — both
    SystemExits below still fire on every genuinely broken registry, including a STABLE malformed one
    (which the helper hands back verbatim rather than masking with the committed blob)."""
    import json
    import sys
    from pathlib import Path

    reg = Path(__file__).resolve().parents[2] / "graph" / "concern-registry.json"

    def _complete(t: str) -> bool:
        try:
            json.loads(t)
            return True
        except ValueError:
            return False

    try:
        text = _read_derived_artifact(reg, is_complete=_complete)
        if text is None:
            raise ValueError("unreadable in the working tree and no recoverable committed blob")
        data = json.loads(text)
    except (OSError, ValueError) as e:
        print(f"yitc-v2: init: concern registry {reg} is missing or unreadable ({e}) — run "
              f"`yitc-v2 graph build` to regenerate the derived registry.", file=sys.stderr)
        raise SystemExit(1)
    concerns = data.get("concerns") if isinstance(data, dict) else None
    if not isinstance(concerns, list):
        print(f"yitc-v2: init: concern registry {reg} has no `concerns` list — run `yitc-v2 graph build`.",
              file=sys.stderr)
        raise SystemExit(1)
    return concerns


def _registry_mandatory_sections() -> set:
    """The `presence_policy: mandatory` concern section names — the registry-derived replacement for the
    retired hand-maintained slice-1 triple (deploy/rollback/live_probe). Used by _update_ops_carrier to
    keep the slice-1 mandatory sections from being auto-seeded (a missing mandatory section must stay the
    sweep's fail-closed ERROR, never silently re-added)."""
    return {e.get("section") for e in _load_concern_registry()
            if e.get("presence_policy") == "mandatory" and isinstance(e.get("section"), str)}


def _ops_nonempty(v) -> bool:
    """Type-generic non-emptiness for a declaration value: a non-blank string, OR a non-empty list/dict,
    OR any other truthy non-None value. The defensive fallback when a concern carries no `declare_type`."""
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return v is not None and v is not False


def _ops_declared(v, declare_type) -> bool:
    """TYPE-AWARE `declared` check keyed off the registry `declare_type` (string | list | mapping). A
    declaration counts ONLY when it is non-empty AND of its declared TYPE — so a WRONG-TYPED declare_key
    (e.g. `deploy.command: ["x"]`, `security.probes: "scalar"`, `verify.layers: {a: 1}`,
    `deploy.host_config.vhost_files: "scalar"`) does NOT count as declared and falls through to the
    fail-closed error, matching the retired ladder's per-type `isinstance` checks (audit-post finding,
    T-10037). A missing/unknown `declare_type` falls back to the type-generic non-emptiness (defensive —
    every kernel concern declares its type, so this never widens a known concern's contract)."""
    if declare_type == "string":
        return isinstance(v, str) and bool(v.strip())
    if declare_type == "list":
        return isinstance(v, list) and len(v) > 0
    if declare_type == "mapping":
        return isinstance(v, dict) and len(v) > 0
    return _ops_nonempty(v)


def _ops_navigate(ops: dict, carrier_path: str):
    """Walk a dotted `carrier_path` (e.g. `deploy`, `deploy.policy`, `deploy.host_config`) into the ops
    mapping. Returns `(present, value)`: present=True iff the LEAF key exists in its (mapping) parent —
    an absent parent OR a non-mapping intermediate yields (False, None). The leaf VALUE may itself be a
    non-mapping (the caller's is-a-mapping check catches that)."""
    parts = carrier_path.split(".")
    cur = ops
    for p in parts[:-1]:
        if not isinstance(cur, dict) or p not in cur:
            return (False, None)
        cur = cur.get(p)
    leaf = parts[-1]
    if not isinstance(cur, dict) or leaf not in cur:
        return (False, None)
    return (True, cur.get(leaf))


def _ops_waiver_errors(label: str, waiver, policy: str) -> list:
    """Generic waiver validation keyed off `waiver_policy` (SPEC-0093 rule 6). `loose` = a mapping with a
    non-empty `reason:`; `strict` (currently security only) ALSO requires a non-empty `compensating_control:`
    and a real ISO-date `expiry:` review-by date — a bare waiver fails closed. Returns a list of error
    strings naming `<label>.waiver`."""
    errs: list = []
    if not isinstance(waiver, dict):
        errs.append(f"{label}.waiver: not a mapping")
        return errs
    if not (isinstance(waiver.get("reason"), str) and waiver.get("reason").strip()):
        errs.append(f"{label}.waiver: missing/empty `reason:`")
    if policy == "strict":
        if not (isinstance(waiver.get("compensating_control"), str)
                and waiver.get("compensating_control").strip()):
            errs.append(f"{label}.waiver: a strict waiver REQUIRES a non-empty `compensating_control:` "
                        "(SPEC-0093 rule 6 — no bare waiver)")
        if not _is_iso_date(waiver.get("expiry")):
            errs.append(f"{label}.waiver: a strict waiver REQUIRES an `expiry:` that is a real ISO date "
                        "(YYYY-MM-DD) review-by date (SPEC-0093 rule 6)")
    return errs


# ── kernel-owned deep-shape validators ("shape hooks", SPEC-0128 Rule 2 / decisions/T-10029-audit-adhoc) ─
# Each hook validates a concern's RESIDUAL entry-level shape AFTER the generic stance/XOR check — the narrow
# escape hatch for shape richer than declare-or-waive. Signature: (label, sec, ops) -> list[str]. `label`
# is the concern's carrier_path (message prefix); `sec` is the present section value (a mapping for a
# stance-checked concern; the RAW value for an opt-in concern, so opt-in hooks self-check the type); `ops`
# is the whole carrier (for cross-section rules, e.g. tests↔verify). Hooks NEVER own membership (that lives
# in the `concern:` block) and are referenced from EXACTLY ONE concern each (graph build warns otherwise).
def _hook_security(label: str, sec: dict, ops: dict) -> list:
    """SPEC-0093 rule 8 / SPEC-0098 residual: the per-probe ENTRY shape (property/assertion/url) when
    probes are declared, plus the OPTIONAL broader keys checked whenever present regardless of stance —
    `authz_model` (non-empty string) and `accepted_risks` (each entry risk + compensating_control + a real
    ISO-date expiry). The STRICT security WAIVER is handled generically (waiver_policy: strict)."""
    errs: list = []
    probes = sec.get("probes")
    if isinstance(probes, list) and len(probes) > 0:
        for i, p in enumerate(probes):
            if not isinstance(p, dict):
                errs.append(f"{label}.probes[{i}]: not a mapping (need property/assertion/url)")
                continue
            missing = [k for k in ("property", "assertion", "url")
                       if not (isinstance(p.get(k), str) and p.get(k).strip())]
            if missing:
                errs.append(f"{label}.probes[{i}]: missing/empty " + ", ".join(missing)
                            + " (the per-probe ENTRY shape — SPEC-0093 rule 8)")
    if "authz_model" in sec and not (isinstance(sec.get("authz_model"), str)
                                     and sec.get("authz_model").strip()):
        errs.append(f"{label}.authz_model: present but not a non-empty string")
    if "accepted_risks" in sec:
        risks = sec.get("accepted_risks")
        if not isinstance(risks, list):
            errs.append(f"{label}.accepted_risks: present but not a list")
        else:
            for i, r in enumerate(risks):
                if not isinstance(r, dict):
                    errs.append(f"{label}.accepted_risks[{i}]: not a mapping "
                                "(need risk + compensating_control + a real ISO-date expiry)")
                    continue
                bad = [k for k in ("risk", "compensating_control")
                       if not (isinstance(r.get(k), str) and r.get(k).strip())]
                if not _is_iso_date(r.get("expiry")):
                    bad.append("expiry (real ISO date)")
                if bad:
                    errs.append(f"{label}.accepted_risks[{i}]: missing/empty " + ", ".join(bad)
                                + " (rule 8 — accepted-risks-WITH-EXPIRY)")
    return errs


def _hook_host_config(label: str, sec: dict, ops: dict) -> list:
    """SPEC-0093 rule 14 / SPEC-0111 residual: when the host_config DECLARATION is present (declare_key
    `vhost_files` a non-empty list), the full 3-key declaration shape — vhost_files entries are non-empty
    path strings, plus a non-empty `live_base_url:` and a non-empty `apply:` recipe (the kernel checks the
    STANCE + SHAPE, never the VALUES — no path-existence / URL-reachability judgement). The declare-or-waive
    exclusivity + waiver `reason:` are handled generically."""
    errs: list = []
    vhosts = sec.get("vhost_files")
    if isinstance(vhosts, list) and len(vhosts) > 0:
        if not all(isinstance(v, str) and v.strip() for v in vhosts):
            errs.append(f"{label}.vhost_files: must be a non-empty list of non-empty path strings "
                        "(the owned vhost file(s) — SPEC-0093 rule 14)")
        if not (isinstance(sec.get("live_base_url"), str) and sec.get("live_base_url").strip()):
            errs.append(f"{label}: missing/empty `live_base_url:` (a non-empty host live base URL — "
                        "SPEC-0093 rule 14)")
        if not (isinstance(sec.get("apply"), str) and sec.get("apply").strip()):
            errs.append(f"{label}: missing/empty `apply:` (a non-empty apply recipe — SPEC-0093 rule 14)")
    return errs


def _glob_list_errors(value, where: str, purpose: str) -> list:
    """T-12039 — the ONE repo-relative-glob-LIST shape check the `tests.classes[]` entry now applies at
    three places (`globs:`, `timing_lane:`, `timing_lane_waiver.globs:`). Extracted from the T-12012
    `globs:` branch VERBATIM rather than copied twice: the three fields carry the same shape for the
    same reason (a test surface lives inside the repo that declares it), so they must fail identically —
    a second hand-rolled copy is exactly how two of them would drift apart.

    A non-empty list of non-empty repo-relative glob strings: NOT absolute, NO upward `..` traversal.
    The CALLER decides presence — this helper is only ever reached for a key that IS present, because an
    absent one is a valid STANCE, not a defect. Pure; returns the (possibly empty) error list."""
    errs: list = []
    if not (isinstance(value, list) and len(value) > 0):
        errs.append(f"{where}: present but not a NON-EMPTY list — it must name at least one "
                    f"repo-relative glob for {purpose}, or be omitted entirely (rule 10 — shape, not "
                    "value). An absent declaration is a valid stance; an empty one declares nothing "
                    "while appearing to declare something.")
        return errs
    for j, g in enumerate(value):
        at = f"{where}[{j}]"
        if not (isinstance(g, str) and g.strip()):
            errs.append(f"{at}: not a non-empty string (rule 10 — shape, not value)")
            continue
        g = g.strip()
        if g.startswith("/"):
            errs.append(f"{at}: {g!r} is ABSOLUTE — a test-class glob is repo-relative "
                        "(rule 10). A test class lives inside the repo that declares it.")
        if g == ".." or g.startswith("../") or "/../" in g or g.endswith("/.."):
            errs.append(f"{at}: {g!r} TRAVERSES UPWARD (`..`) — a test-class glob is "
                        "repo-relative and may not reach outside the declaring repo "
                        "(rule 10).")
    return errs


def _hook_tests(label: str, sec: dict, ops: dict) -> list:
    """SPEC-0093 rule 10 residual: the per-class TAXONOMY entry shape (class/moment non-empty strings, an
    OPTIONAL non-empty `command:`), plus the cross-section rule 10/16 — once the carrier `verify:` section
    has landed, a `command:` for `moment: verify` is FORBIDDEN (the executable land command belongs
    single-home in `verify.layers`). Gated on `"verify" in ops` so a pre-verify carrier is not retro-broken.

    Also the OPTIONAL per-class `globs:` (T-12012, rule 10 / SPEC-0185 half (c)) — WHERE that class's test
    FILES live, so a project can DECLARE the convention the kernel would otherwise GUESS from a filename
    regex (X-1235). Shape only, checked ONLY IF PRESENT (absence is a stance, not a defect, so no existing
    carrier is retro-broken): a non-empty list of non-empty repo-relative glob strings — NOT absolute, NO
    `..` traversal, because a test class lives inside the repo that declares it. It is inert DATA, never a
    command home (rule 16 untouched), so nothing here executes or resolves it.

    Also the OPTIONAL per-class `timing_lane:` + its sibling `timing_lane_waiver: {globs, reason}`
    (T-12039, rule 10 / SPEC-0160 rule 10) — WHICH of that class's tests are TIMING-SENSITIVE, so the
    SPEC-0077 pinned last-green leg can REFUSE to pin them (a wall-clock check run inside a land
    measures the host, not the change). `timing_lane:` carries the `globs:` shape VERBATIM — the same
    non-empty-list / non-empty-string / not-absolute / no-`..` checks, applied by the same
    `_glob_list_errors` helper, checked ONLY IF PRESENT. The waiver is the rule-6 LOOSE shape reused: a
    mapping whose `globs:` is that same list shape and whose `reason:` records who accepted the flake
    risk. FAIL-CLOSED on the waiver (a malformed one is an ERROR, not a silent no-op) — it is the key
    that BUYS a pin, so an unreadable one must say so. Both are inert DATA (rule 16 untouched)."""
    errs: list = []
    classes = sec.get("classes")
    if isinstance(classes, list) and len(classes) > 0:
        for i, c in enumerate(classes):
            if not isinstance(c, dict):
                errs.append(f"{label}.classes[{i}]: not a mapping (need class/moment)")
                continue
            missing = [k for k in ("class", "moment")
                       if not (isinstance(c.get(k), str) and c.get(k).strip())]
            if missing:
                errs.append(f"{label}.classes[{i}]: missing/empty " + ", ".join(missing)
                            + " (the per-class TAXONOMY shape — SPEC-0093 rule 10)")
            if "command" in c and not (isinstance(c.get("command"), str) and c.get("command").strip()):
                errs.append(f"{label}.classes[{i}].command: present but not a non-empty string "
                            "(rule 10 — shape, not value)")
            if ("verify" in ops and str(c.get("moment") or "").strip() == "verify"
                    and isinstance(c.get("command"), str) and c.get("command").strip()):
                errs.append(f"{label}.classes[{i}]: a `command:` for `moment: verify` is FORBIDDEN once "
                            "the carrier `verify:` section has landed — the executable land command belongs "
                            "in `verify.layers` (SPEC-0093 rule 10 / SPEC-0152 rule 16, no second command home)")
            if "globs" in c:
                errs.extend(_glob_list_errors(
                    c.get("globs"), f"{label}.classes[{i}].globs",
                    "where this class's test FILES live"))
            # T-12039 — the OPTIONAL timing-lane declaration + its waiver, same glob shape, reused.
            if "timing_lane" in c:
                errs.extend(_glob_list_errors(
                    c.get("timing_lane"), f"{label}.classes[{i}].timing_lane",
                    "which of this class's tests are TIMING-SENSITIVE (so the pinned last-green leg "
                    "refuses to pin them — SPEC-0160 rule 10)"))
            if "timing_lane_waiver" in c:
                where = f"{label}.classes[{i}].timing_lane_waiver"
                waiver = c.get("timing_lane_waiver")
                if not isinstance(waiver, dict):
                    errs.append(f"{where}: present but not a mapping — it must carry a `globs:` list "
                                "naming what the waiver covers plus a non-empty `reason:` recording who "
                                "accepted the flake risk (rule 10 / SPEC-0160 rule 10). A waiver is what "
                                "BUYS a pin for a declared timing test, so a malformed one is an ERROR, "
                                "never a silent no-op.")
                else:
                    errs.extend(_glob_list_errors(
                        waiver.get("globs"), f"{where}.globs",
                        "which declared timing tests this waiver RE-ADMITS to the pinned set"))
                    if not (isinstance(waiver.get("reason"), str) and waiver.get("reason").strip()):
                        errs.append(f"{where}: missing/empty `reason:` — a non-empty string recording "
                                    "who accepted the flake risk of pinning a declared timing test, and "
                                    "why (rule 10 / SPEC-0160 rule 10 — the rule-6 LOOSE waiver shape).")
    return errs


def _hook_inspection(label: str, sec: dict, ops: dict) -> list:
    """SPEC-0093 rule 12 residual: the per-theme entry shape — a non-empty `theme:` slug, a `probe:` mapping
    declaring EXACTLY ONE probe KIND (`view:` XOR `sweep:`), and a `cadence:` of weekly|monthly|quarterly.
    `view:` is a `graph query <view>` lens name (a non-empty string). `sweep:` is a non-view product-realm
    sweep DERIVED from the `security.probes[]` declare-shape (rule 8): a mapping with REQUIRED `surfaces:`
    (a non-empty string) + `checks:` (a non-empty list of non-empty strings) + an OPTIONAL `against:` (a
    non-empty string). BOTH kinds together → contradiction ERROR; NEITHER → ERROR (fail-closed). Pure
    declared config, no kernel runner/events (the run stays MANUAL; still emits the existing
    `inspection_completed`, SPEC-0057 §6 unchanged)."""
    errs: list = []
    themes = sec.get("themes")
    if isinstance(themes, list) and len(themes) > 0:
        _cadences = ("weekly", "monthly", "quarterly")
        for i, t in enumerate(themes):
            if not isinstance(t, dict):
                errs.append(f"{label}.themes[{i}]: not a mapping (need theme/probe/cadence)")
                continue
            if not (isinstance(t.get("theme"), str) and t.get("theme").strip()):
                errs.append(f"{label}.themes[{i}]: missing/empty `theme:` (a non-empty slug — "
                            "SPEC-0093 rule 12)")
            probe = t.get("probe")
            if not isinstance(probe, dict):
                errs.append(f"{label}.themes[{i}].probe: needs a mapping declaring EXACTLY ONE of "
                            "`view:` or `sweep:` (SPEC-0093 rule 12)")
            else:
                pfx = f"{label}.themes[{i}].probe"
                has_view = "view" in probe
                has_sweep = "sweep" in probe
                if has_view and has_sweep:
                    errs.append(f"{pfx}: declares BOTH `view:` and `sweep:` — a probe is EXACTLY ONE KIND "
                                "(SPEC-0093 rule 12)")
                elif not (has_view or has_sweep):
                    errs.append(f"{pfx}: needs EXACTLY ONE of `view: <graph-query-view>` OR "
                                "`sweep: {surfaces, checks}` (SPEC-0093 rule 12)")
                elif has_view:
                    if not (isinstance(probe.get("view"), str) and probe.get("view").strip()):
                        errs.append(f"{pfx}: needs a `view: <graph-query-view>` non-empty string "
                                    "(SPEC-0093 rule 12)")
                else:  # has_sweep — the security.probes[]-derived declare-shape (rule 8)
                    sweep = probe.get("sweep")
                    if not isinstance(sweep, dict):
                        errs.append(f"{pfx}.sweep: needs a mapping with `surfaces:` + `checks:` "
                                    "(SPEC-0093 rule 12, derived from security.probes[])")
                    else:
                        if not (isinstance(sweep.get("surfaces"), str) and sweep.get("surfaces").strip()):
                            errs.append(f"{pfx}.sweep: missing/empty `surfaces:` (a non-empty glob string "
                                        "of the surfaces to sweep — SPEC-0093 rule 12)")
                        checks = sweep.get("checks")
                        if not (isinstance(checks, list) and len(checks) > 0
                                and all(isinstance(c, str) and c.strip() for c in checks)):
                            errs.append(f"{pfx}.sweep: missing/empty `checks:` (a non-empty list of "
                                        "non-empty named hand-run assertions — the security.probes[] "
                                        "analog, SPEC-0093 rule 12)")
                        if "against" in sweep and not (isinstance(sweep.get("against"), str)
                                                       and sweep.get("against").strip()):
                            errs.append(f"{pfx}.sweep.against: present but not a non-empty string "
                                        "(rule 12 — shape, not value)")
            if t.get("cadence") not in _cadences:
                errs.append(f"{label}.themes[{i}].cadence: must be one of weekly|monthly|quarterly "
                            "(SPEC-0093 rule 12)")
    errs += _kernel_theme_violations(label, sec)
    return errs


def _kernel_theme_violations(label: str, sec: dict) -> list:
    """SPEC-0160 rule 12 (T-12053) — the ONE kernel-owned seeded entry is MANDATORY and a project
    `waiver:` never covers it. ABSENT, DE-OWNED (`owner: kernel` stripped or changed) or WAIVER-WRAPPED
    is an ERROR naming the entry AND the pattern path, so the message says what to restore.

    Deliberately INDEPENDENT of `_seed_kernel_theme` — it judges the carrier as it finds it and writes
    nothing, so it refuses a tampered carrier on EVERY surface the sweep reaches (the fail-closed
    `init` sweep and the report-only `concern_conformance` views alike), not only where an init ran."""
    errs: list = []
    themes = sec.get("themes")
    entries = [x for x in themes if isinstance(x, dict)] if isinstance(themes, list) else []
    found = next((x for x in entries
                  if str(x.get("theme") or "").strip() == _KERNEL_THEME_SLUG), None)
    if found is None:
        waived = "waiver" in sec
        errs.append(
            f"{label}.themes: the KERNEL-OWNED `{_KERNEL_THEME_SLUG}` entry is MISSING — it is a "
            f"BASELINE mechanism in every consumer, seeded by `init`, with NO opt-out (SPEC-0160 rule "
            f"12; owner directive 2026-09-04)."
            + (f" A project `waiver:` covers only PROJECT-OWN themes and does NOT reach this entry, so "
               f"waiving the section does not answer for it." if waived else "")
            + f" Restore it by re-running `init` on a carrier that still records the waive, or re-add "
              f"the entry: {{theme: {_KERNEL_THEME_SLUG}, owner: {_KERNEL_THEME_OWNER}, probe: {{sweep: "
              f"{{surfaces, checks, against: {_KERNEL_THEME_AGAINST}}}}}, cadence: "
              f"{_KERNEL_THEME_CADENCE}}}. The checklist lives at {_KERNEL_THEME_AGAINST}.")
        return errs
    where = f"{label}.themes[{entries.index(found)}]"
    if str(found.get("owner") or "").strip() != _KERNEL_THEME_OWNER:
        errs.append(f"{where}: `{_KERNEL_THEME_SLUG}` is the KERNEL-OWNED baseline entry and must carry "
                    f"`owner: {_KERNEL_THEME_OWNER}` — stripping it does not make the entry the "
                    f"project's to remove (SPEC-0160 rule 12, no opt-out; checklist "
                    f"{_KERNEL_THEME_AGAINST}).")
    probe = found.get("probe")
    sweep = probe.get("sweep") if isinstance(probe, dict) else None
    if not isinstance(sweep, dict):
        errs.append(f"{where}.probe: the kernel-owned `{_KERNEL_THEME_SLUG}` entry is a `sweep:` probe "
                    f"over the project's product code (SPEC-0160 rule 12; checklist "
                    f"{_KERNEL_THEME_AGAINST})")
    elif str(sweep.get("against") or "").strip() != _KERNEL_THEME_AGAINST:
        errs.append(f"{where}.probe.sweep.against: must name the kernel checklist "
                    f"`{_KERNEL_THEME_AGAINST}` — the entry POINTS at the single-SoT lens and never "
                    f"restates it (SPEC-0160 rule 12)")
    if str(found.get("cadence") or "").strip() != _KERNEL_THEME_CADENCE:
        errs.append(f"{where}.cadence: the kernel-owned `{_KERNEL_THEME_SLUG}` entry runs "
                    f"`{_KERNEL_THEME_CADENCE}` (SPEC-0160 rule 12)")
    return errs


def _hook_ui(label: str, sec: dict, ops: dict) -> list:
    """SPEC-0093 rule 9 residual: the OPTIONAL broader keys (styleguide/tokens/lint/archetype) must each be
    a non-empty string when present (shape, not value). The baseline-or-waive stance is generic."""
    errs: list = []
    for k in ("styleguide", "tokens", "lint", "archetype"):
        if k in sec and not (isinstance(sec.get(k), str) and sec.get(k).strip()):
            errs.append(f"{label}.{k}: present but not a non-empty string (rule 9 — shape, not value)")
    return errs


def _is_positive_seconds(v) -> bool:
    """T-10257: a DECLARED verify timeout is positive seconds — a number, never a bool (`timeout: true` is a
    stance, not a bound). Shape, not value: the kernel never judges whether the number is big enough."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def _hook_verify(label: str, sec: dict, ops: dict) -> list:
    """SPEC-0152 rule 16 residual: the PER-LAYER declare-or-waive when `layers:` is declared — each entry a
    non-empty `layer:` id + a `command:` XOR a per-layer `waiver:` {reason} (NEITHER → UNANSWERED layer;
    BOTH → contradiction), an OPTIONAL `covers:` list of non-empty glob strings, and an OPTIONAL `timeout:`
    (positive seconds — T-10257). The section-level layers-XOR-waiver stance is generic; the section-level
    OPTIONAL `timeout_seconds:` (the default bound for layers declaring no `timeout:`) is checked here."""
    errs: list = []
    if "timeout_seconds" in sec and not _is_positive_seconds(sec.get("timeout_seconds")):
        errs.append(f"{label}.timeout_seconds: present but not a positive number of seconds — the default "
                    "land-verify bound for layers declaring no `timeout:` (rule 16 — shape, not value)")
    layers = sec.get("layers")
    if isinstance(layers, list) and len(layers) > 0:
        for i, ly in enumerate(layers):
            if not isinstance(ly, dict):
                errs.append(f"{label}.layers[{i}]: not a mapping (need `layer:` + a `command:` or per-layer "
                            "`waiver:`)")
                continue
            if not (isinstance(ly.get("layer"), str) and ly.get("layer").strip()):
                errs.append(f"{label}.layers[{i}]: missing/empty `layer:` (a non-empty layer id — "
                            "SPEC-0152 rule 16)")
            ly_has_cmd_key = "command" in ly
            ly_has_waiver_key = "waiver" in ly
            ly_cmd = isinstance(ly.get("command"), str) and ly.get("command").strip()
            ly_w = ly.get("waiver")
            ly_waived = isinstance(ly_w, dict) and str(ly_w.get("reason") or "").strip()
            if ly_has_cmd_key and ly_has_waiver_key:
                errs.append(f"{label}.layers[{i}]: declares BOTH a `command:` and a `waiver:` — a layer is "
                            "EITHER declared OR waived (SPEC-0152 rule 16)")
            elif not (ly_cmd or ly_waived):
                errs.append(f"{label}.layers[{i}]: UNANSWERED layer — neither a non-empty `command:` "
                            "(declared) nor a `waiver: {reason: <why>}` (waived) — SPEC-0152 rule 16 "
                            "(per-layer declare-or-waive)")
            if "covers" in ly and not (isinstance(ly.get("covers"), list)
                    and all(isinstance(g, str) and g.strip() for g in ly.get("covers"))):
                errs.append(f"{label}.layers[{i}].covers: present but not a list of non-empty glob strings "
                            "(rule 16 — shape, not value)")
            if "timeout" in ly and not _is_positive_seconds(ly.get("timeout")):
                errs.append(f"{label}.layers[{i}].timeout: present but not a positive number of seconds — "
                            "this layer's land-verify bound (rule 16 — shape, not value)")
    return errs


# ── Which adoptable extension demands a qualifying SOURCE declaration (T-10775, SPEC-0170) ──────────
# ONE home for the per-spec residual, resolved by BOTH sides of the adoption declaration: the READ side
# (`_hook_extensions`, the declare-or-waive sweep) and the WRITE side (`_adopt_extensions`, behind
# `init --adopt-extension`). Before this, the read side carried a bare `SPEC-0170` literal and the write
# side knew nothing at all — so the governed verb could WRITE a bare `- spec: SPEC-0170` entry that the
# very next sweep fail-closed on all six properties, wedging the carrier it had just written with no
# verb-covered exit (the X-0401 / T-10535 "the only path left was a hand-edit" shape). Keyed by spec id;
# the VALUE is the evaluator that answers the residual (a pure `(source, label) -> [violation]`), so a
# future member declares its own contract here rather than growing a branch.
#
# NOT a registry/store/FSM (CHARTER §P1 F2): a module-level dict read by the two existing call sites.
def _extension_source_evaluators() -> dict:
    """The spec-id -> source-evaluator map. Imported function-locally (the same in-function import shape
    `_hook_runtime_delivery` uses for `lib.debt`), so `cmd_init`'s injected-deps contract stays unchanged
    and there is no import cycle."""
    from lib import frontend_errors  # stdlib-only — no cycle
    return {"SPEC-0170": frontend_errors.qualifying_source_violations}


#: The spec ids whose `extensions.adopts[]` entry MUST carry a qualifying `source:` mapping.
_EXTENSION_SOURCE_SPECS = ("SPEC-0170",)


def _extension_source_violations(spec_id, source, *, label: str) -> list:
    """Evaluate the per-spec `source:` residual for ONE adopts entry. Returns [] for a spec that demands
    no source (the common case — every other extension), else the evaluator's refusals, each NAMING the
    failing property. PURE: no I/O, no raise — the caller decides whether that is a sweep error (read
    side) or a write-time refusal (write side)."""
    sid = spec_id.strip() if isinstance(spec_id, str) else ""
    evaluator = _extension_source_evaluators().get(sid)
    if evaluator is None:
        return []
    return list(evaluator(source, label=label))


def _hook_extensions(label: str, sec, ops: dict) -> list:
    """SPEC-0093 rule 13 / SPEC-0101 residual (OPT-IN — no declare-or-waive stance): the section (if present)
    must be a mapping; `adopts:` (if present) must be a LIST (`[]` for none) of mappings each carrying a
    non-empty `SPEC-XXXX`-shaped `spec:`. A present-but-null/scalar `adopts:` fails closed (never widens the
    contract past absent-or-list). Adoptability is enforced at WRITE-time by `--adopt-extension`, not here
    (graph-free). NOTE `sec` is the RAW section value here (opt-in bypasses the generic is-a-mapping check).

    PLUS the per-member declare-XOR-waive arm (T-10475, fu_e0e14db83ac9): a spec in BOTH `adopts:` and
    `waives:` is a CONTRADICTION — the carrier declaring and refusing the same capability at once. This is
    the per-MEMBER altitude of the same exclusivity the generic section-level stance enforces (:1016, the
    `declares BOTH … EITHER declared OR waived` idiom); the generic arm never reaches here because
    `extensions` is `presence_policy: opt-in`, which bypasses the stance and runs this hook alone. Homed
    here rather than in `_sweep_extension_catalog_completeness` because the contradiction is CARRIER-INTERNAL
    — judging it needs no catalog, so it stays graph-free AND catches a contradiction on ANY spec, not only
    on a current catalog member."""
    import re as _re
    errs: list = []
    if not isinstance(sec, dict):
        errs.append(f"{label}: present but not a mapping (SPEC-0093 rule 13)")
        return errs
    if "adopts" in sec:
        adopts = sec.get("adopts")
        if not isinstance(adopts, list):
            errs.append(f"{label}.adopts: present but not a list — use `adopts: []` for none, or omit the "
                        "key entirely (SPEC-0093 rule 13)")
        else:
            for i, a in enumerate(adopts):
                if not isinstance(a, dict):
                    errs.append(f"{label}.adopts[{i}]: not a mapping (need `spec: SPEC-XXXX`)")
                    continue
                sp = a.get("spec")
                if not (isinstance(sp, str) and _re.match(r"^SPEC-\d{4,}$", sp.strip())):
                    errs.append(f"{label}.adopts[{i}]: missing/malformed `spec:` (a non-empty SPEC-XXXX id "
                                "citing an adoptable extension — SPEC-0093 rule 13)")
                    continue
                # The per-spec SOURCE PREFLIGHT (T-10774 read side; T-10775 made it one home) — carried
                # by THIS declaration, no second declaration path and no checker of its own. Which specs
                # demand one is `_EXTENSION_SOURCE_SPECS`, the SINGLE home both this READ side and the
                # `_adopt_extensions` WRITE side resolve through (CHARTER §P5) — the spec id is no longer
                # a literal in either. Per-member and opt-in by construction: an entry citing any other
                # spec is untouched, so a consumer that has not adopted it sees no change at all.
                errs += _extension_source_violations(sp, a.get("source"),
                                                    label=f"{label}.adopts[{i}].source")
    # Reuses `_extensions_coverage` — the SINGLE reader of this section's declared/waived sets (CHARTER
    # §P5; the same one `_seed_catalog_waives` / `_sweep_extension_catalog_completeness` / `_adopt_extensions`
    # resolve stance through), never a re-derivation by hand.
    declared, waived = _extensions_coverage(ops if isinstance(ops, dict) else {})
    for sid in sorted(declared & set(waived)):
        errs.append(f"{label}: {sid} is in BOTH `adopts:` and `waives:` — a spec is EITHER declared OR "
                    f"waived, never both (SPEC-0112 rule 1 / SPEC-0093 rule 3). Keep the stance that is "
                    f"true: to ADOPT it, drop its `waives:` entry (or re-run `init --adopt-extension "
                    f"{sid}`, which retires the waive for you); to WAIVE it, drop its `adopts:` entry.")
    return errs


def _hook_runtime_delivery(label: str, sec: dict, ops: dict) -> list:
    """RESIDUAL shape for `deploy.runtime_delivery` (SPEC-0093 rule 22, T-10511 / X-0370) — the CLOSED enum.

    The generic stance check already accepts any non-empty `model:` string. That is not enough here: a
    mis-spelt model (`source_mounted`, `baked`, `mounted`) would read as a DECLARATION, silence the
    SPEC-0119 rule-14 surface, and restore the exact silence this concern exists to end — a bypassable
    deploy that nothing names. So the enum is enforced, fail-CLOSED: an unknown model is not a declaration.

    The vocabulary is IMPORTED from the reading side (`lib.debt`, the way this module already imports the
    deploy boundary in `_hook_deploy_policy`) — one home for the enum + the bypassable set (CHARTER §P5), so
    the sweep can never accept a model the debt view does not understand.
    """
    from lib import debt  # CHARTER §P5 — one home for the runtime-delivery vocabulary
    errs: list = []
    if not isinstance(sec, dict) or "model" not in sec:
        return errs                                   # absent / waived — the generic stance check owns it
    model = sec.get("model")
    model = model.strip() if isinstance(model, str) else model
    if model and model not in debt.RUNTIME_DELIVERY_MODELS:
        errs.append(f"{label}.model: unknown runtime-delivery model {model!r} — declare ONE of "
                    f"{' | '.join(debt.RUNTIME_DELIVERY_MODELS)} (SPEC-0093 rule 22). A mis-spelt model "
                    f"would read as a declaration and silence the bypassable-deploy surface (X-0370).")
    return errs


def _hook_live_revision(label: str, sec: dict, ops: dict) -> list:
    """RESIDUAL shape for `deploy.live_revision` (SPEC-0093 rule 23, T-10521 / X-0376) — an OPTIONAL declared
    read-only live-revision adapter feeding the SPEC-0119 rule-16 reverse-coherence line.

    OPT-IN (the rule-13 `extensions:` model): an ABSENT section is a clean default (the deploy_completed
    proxy stands) — the opt-in presence policy skips it and this hook is NEVER called for absence (init.py
    `_sweep_ops_carrier`: opt-in runs the hook only when `present`). But a PRESENT block must be USABLE,
    fail-CLOSED: a present-but-EMPTY `{}` (or a decl of an unknown kind / a non-list command) is malformed
    opt-in config, NOT absence — accepting it would let malformed config silently fall back to the proxy,
    the very silence rule 23 exists to end (audit-post finding, T-10521). Today the only defined adapter is
    `kind: command` with a non-empty list-of-str `command`; a `waiver:` is a deliberate opt-out."""
    errs: list = []
    if not isinstance(sec, dict):
        errs.append(f"{label}: present but not a mapping — declare `kind: command` with a read-only "
                    f"`command:`, or `waiver: {{reason: <why>}}` (SPEC-0093 rule 23).")
        return errs
    if isinstance(sec.get("waiver"), dict):
        return errs                                   # a reasoned waiver — a deliberate opt-out
    if sec.get("kind") != "command":
        errs.append(f"{label}: a PRESENT live_revision section must declare `kind: command` with a read-only "
                    f"`command:` (or a `waiver:`) — got kind {sec.get('kind')!r}. An empty/malformed opt-in "
                    f"block must not silently fall back to the deploy_completed proxy (SPEC-0093 rule 23).")
        return errs
    cmd = sec.get("command")
    if not (isinstance(cmd, list) and cmd and all(isinstance(a, str) for a in cmd)):
        errs.append(f"{label}.command: a kind:command live-revision adapter must name a non-empty list of "
                    f"str argv (read-only, prints `{{\"revision\": <sha>}}`) (SPEC-0093 rule 23).")
    return errs


def _hook_remote_sync(label: str, sec: dict, ops: dict) -> list:
    """RESIDUAL shape for `remote_sync` (SPEC-0163 rule 4) — a DECLARED section answers ALL THREE parts.

    The three parts are ONE concern (rule 1): `remote:` (where the code syncs), `pusher:` (which identity
    pushes there), `ci:` (is CI live on the far side, and is it a GATE or an extra check). The generic
    stance sweep counts the section DECLARED on `remote:` alone, so without this hook a section could
    declare a remote and silently drop the other two — two of the three parts gone without a word, which
    is the coverage-shaped silence this concern exists to end (X-0346 / T-10419).

    FAIL-CLOSED on a PRESENT, NON-WAIVED declaration ONLY. An ABSENT (checked-if-present) or WAIVED
    section is a STANCE the generic check owns: this hook returns nothing and never backfills, mirrors or
    auto-heals it (`lessons/a-stance-mirror-is-only-sound-at-birth.md`). It judges COMPLETENESS only —
    never the remote's reachability, the pusher's credentials, or the CI system's quality (the SPEC-0093
    rule-3 boundary: the kernel checks the stance, not the command's correctness) — and it mandates no
    forge and no CI system (rule 2): `ci: none` is a COMPLETE answer, silence is not."""
    errs: list = []
    if not isinstance(sec, dict):
        return errs                                   # not a mapping — the generic stance check owns it
    if "waiver" in sec:
        return errs                                   # a reasoned waiver (LOOSE, rule 5) — a stance
    if not _ops_declared(sec.get("remote"), "string"):
        return errs                                   # undeclared/blank remote — the generic check owns it
    for key, what in (("pusher", "WHO pushes to it (a real named identity + credential path — an "
                                 "auto-pusher that dies with a retired system leaves the remote "
                                 "silently un-synced, T-10419)"),
                      ("ci", "whether CI is LIVE on the far side and in what ROLE — a blocking GATE or "
                             "an extra check beside `verify.layers` (rule 3). `ci: none` is a complete "
                             "answer; a workflow file's mere existence is not a stance")):
        if not _ops_declared(sec.get(key), "string"):
            errs.append(f"{label}.{key}: `remote:` is declared but `{key}:` is missing or blank — a "
                        f"declared remote_sync answers ALL THREE parts (remote + pusher + ci); they are "
                        f"ONE stance (SPEC-0163 rule 1/4). Declare {what}.")
    return errs


#: The pseudo-"half" a reasonless per-key `slo.waiver:` is missing — a waiver with no reason is not a
#: stance, so it is reported as an absent REASON rather than as absent objective/target.
SLO_WAIVER_REASON = "waiver.reason"


def _ops_waiver_reasoned(waiver) -> bool:
    """Is this `waiver:` REASONED — i.e. terminal under SPEC-0119 rule 39? — asked at its ONE home.

    THIS FUNCTION DECIDES NOTHING ITSELF. It is a thin, fail-closed adapter onto
    `debt._gap_waiver_answer`, which is rule 39's single home and what the gap register itself
    applies. It exists so that the birth-time hooks and the register cannot drift on the question
    "does this waiver close the obligation" — they contradicted each other twice on exactly that
    (T-12088 audit-post, 2026-09-05), and both times the fix was to delegate rather than to grow a
    second reading (CHARTER §P5).

    FAIL-CLOSED on an unimportable `lib.debt` (this file's convention, and the function-local import
    is its own established precedent here): an unanswerable waiver is NOT reasoned, so it is
    REFUSED rather than silently accepted."""
    try:
        from lib import debt as _debt   # CHARTER §P5 — one home for the waiver-reason rule
        return bool(_debt._gap_waiver_answer(waiver))
    except Exception:                     # noqa: BLE001 — see FAIL-CLOSED
        return False


def _alert_routing_slo_missing(value) -> list:
    """WHICH halves of a present, non-waived `slo:` are absent — SPEC-0164 rule 5's ONE home.

    TWO SURFACES ASK THIS, AND THEY MUST NOT DRIFT (T-12088 audit-post finding, 2026-09-05): the
    BIRTH-time shape hook below refuses an incomplete `slo:`, and the gap register
    (`debt.profile_gap_register`) must not count one as ANSWERING `one-slo-declared`. Shipped as two
    independent readings they contradicted each other — the hook refused `slo: {objective: …}` while
    the register marked the item adopted, so a live project could close its SLO obligation with a
    promise carrying no number, which is precisely the coverage-shaped silence rule 5 exists to end.
    One predicate, two callers (CHARTER §P5).

    A per-key `waiver:` is a STANCE — but ONLY A REASON-BEARING ONE, and that question is NOT answered
    here either: it is `debt._gap_waiver_answer`, SPEC-0119 rule 39's own home for "a waiver is
    terminal only with a reason". Deferring is the whole point. When this function decided waivers by
    itself (`"waiver" in value`), `slo: {waiver: {owner: alice}}` PASSED the hook while the register —
    correctly applying rule 39 — kept the item UNMET: the same two-surfaces contradiction one layer
    down, found on the very next audit pass. A reasonless waiver is indistinguishable from someone
    having started to write one and stopped, and neither surface may accept it.

    The register still renders WHICH terminal state a stance is (`waived` / `out-of-scope`); this
    answers only WHETHER the declaration falls short. A non-mapping, an empty mapping and a lone
    `task:` pointer are all missing BOTH halves.

    FAIL-CLOSED on an unanswerable waiver — carried by `_ops_waiver_reasoned` above, the one adapter
    both this predicate and the section-level short-circuit ask."""
    if isinstance(value, dict) and "waiver" in value:
        return [] if _ops_waiver_reasoned(value["waiver"]) else [SLO_WAIVER_REASON]
    if not isinstance(value, dict):
        return ["objective", "target"]
    return [k for k in ("objective", "target") if not _ops_declared(value.get(k), "string")]


def _hook_runbook(label: str, sec: dict, ops: dict) -> list:
    """RESIDUAL shape for `runbook` (SPEC-0199 VP2) — a DECLARED runbook answers ALL THREE parts.

    The three are ONE stance: `logs:` (where a human reads them), `rollback:` (how the change is
    undone) and `contact:` (who is called, in what order). The generic stance sweep counts the
    section DECLARED on its `declare_key` (`logs:`) alone, so without this hook a project could name
    a log location and silently drop the two parts that matter at 3 a.m. — a runbook that says where
    the logs are and not who to call is not a runbook, which is the half-answered shape SPEC-0199's
    VP2 names (the aiseller X-0345 rotation outage is the incident: a surface map nobody could act on).

    FAIL-CLOSED on a PRESENT, NON-WAIVED declaration ONLY — the `_hook_alert_routing` posture, and
    the same boundary: an ABSENT (checked-if-present) or WAIVED section is a stance the generic check
    owns, and this hook returns nothing, never backfills and never auto-heals it
    (`lessons/a-stance-mirror-is-only-sound-at-birth.md`). It judges COMPLETENESS only — never
    whether the rollback command works, whether the contact answers, or whether the logs exist. It is
    the WHAT-to-do companion of `alert_routing`'s WHO-is-told (SPEC-0199 §Internal item 5): the two
    are separable by the SPEC-0005 delete-test, which is why each keeps its own section and hook."""
    errs: list = []
    if not isinstance(sec, dict):
        return errs                                   # not a mapping — the generic stance check owns it
    if "waiver" in sec:
        return errs                                   # a reasoned waiver (LOOSE) — a stance
    if not _ops_declared(sec.get("logs"), "string"):
        return errs                                   # undeclared/blank logs — the generic check owns it
    for key, what in (("rollback", "HOW the change is undone — the command, or the pointer to the "
                                   "`rollback:` section, and how long it takes"),
                      ("contact", "WHO is called, in what order — a named human, rota or on-call "
                                  "identity")):
        if not _ops_declared(sec.get(key), "string"):
            errs.append(f"{label}.{key}: `logs:` is declared but `{key}:` is missing or blank — a "
                        f"declared runbook answers ALL THREE parts (logs + rollback + contact); they "
                        f"are ONE stance (SPEC-0199). Declare {what}. A runbook that only says where "
                        f"the logs are cannot be acted on; if this project has no such surface, WAIVE "
                        f"the section with a reason.")
    return errs


def _hook_alert_routing(label: str, sec: dict, ops: dict) -> list:
    """RESIDUAL shape for `alert_routing` (SPEC-0164 rule 2) — a DECLARED section answers BOTH parts.

    The two parts are ONE stance (rule 2): `sink:` (WHERE an incident alert is delivered) and `receiver:`
    (WHO reads it and ACTS). The generic stance sweep counts the section DECLARED on `sink:` alone, so
    without this hook a section could name a destination and silently drop the receiver — and an alert
    nobody reads is not routing, it is the coverage-shaped silence this concern exists to end (the same
    class as a remote whose auto-pusher died and left it silently un-synced, X-0346 / T-10419).

    FAIL-CLOSED on a PRESENT, NON-WAIVED declaration ONLY. An ABSENT (checked-if-present) or WAIVED
    section is a STANCE the generic check owns: this hook returns nothing and never backfills, mirrors or
    auto-heals it (`lessons/a-stance-mirror-is-only-sound-at-birth.md`). It judges COMPLETENESS only —
    never the sink's reachability, deliverability, latency or quality, and it never contacts the sink or
    sends a test alert (SPEC-0164 rule 3 grade-only / the SPEC-0093 rule-3 boundary: the kernel checks the
    stance, not the command's correctness). It mandates no alerting product and no transport (rule 4): any
    sink a human really reads is a complete answer; silence is not."""
    errs: list = []
    if not isinstance(sec, dict):
        return errs                                   # not a mapping — the generic stance check owns it
    if "waiver" in sec:
        # A REASONED waiver (LOOSE, rule 1) is a stance and closes the whole section. A REASONLESS
        # one is NOT: SPEC-0119 rule 39 (the register's own home, applied here through its ONE
        # predicate) makes a waiver terminal only when it says WHY, and shipped as a bare
        # `"waiver" in sec` this hook short-circuited on `{waiver: {owner: alice}}` while the gap
        # register — correctly — left every item under the section UNMET (T-12088 audit-post
        # finding, 2026-09-05). A half-written waiver must not be a quieter way to answer a concern
        # than not writing one, so it is a SHAPE ERROR rather than a pass.
        if _ops_waiver_reasoned(sec["waiver"]):
            return errs
        return errs + [
            f"{label}.waiver: waived with no reason — a waiver is a STANCE only when it says WHY "
            f"(SPEC-0119 rule 39, the same rule the gap register applies). A reasonless waiver is "
            f"indistinguishable from one somebody started writing and stopped, so it neither "
            f"answers this section nor closes its gaps. Give the waiver a non-blank `reason:` "
            f"string (or make it a bare string, which IS its own reason), or drop it and declare "
            f"the section."]

    # SPEC-0164 rule 5 — the HALF-DECLARED `slo:`, the ONE observability shape that fail-closes.
    #
    # PLACED BEFORE THE `sink:` EARLY RETURN ON PURPOSE: this rule is INDEPENDENT of whether a sink is
    # declared. A section that declares only a broken `slo:` and no sink must still be refused —
    # behind the sink gate it would have been silently skipped, which is the coverage-shaped silence
    # this concern exists to end.
    #
    # An objective with no target is the same defect as a sink with no receiver (rule 2): it READS as
    # a promise while committing to nothing measurable, so nobody can ever say it was missed. EITHER
    # half missing is the refusal, and the message names WHICH half. `_ops_declared(..., "string")` is
    # the existing type-aware predicate the hook already uses for sink/receiver — reused, so there is
    # no parallel type logic and a wrong-typed half (`objective: ["a"]`) does not read as declared.
    #
    # `health:` and `logs:` are FREE PROSE and are never shape-refused — the kernel has no opinion
    # about what a good health endpoint looks like (rule 3, grade-only). And ABSENCE of all three
    # stays a PASS: a missing key is a STANCE the profile-gated gap register asks about, never a
    # shape defect the hook invents (`lessons/a-stance-mirror-is-only-sound-at-birth.md`).
    # PRESENCE IS `"slo" in sec`, NOT `sec.get("slo") is not None` (T-12088 audit-post finding,
    # 2026-09-05). An explicitly written `slo:` with a null value is PRESENT, and the gap register
    # reads it exactly as it reads any other non-answer: `one-slo-declared` stays UNMET. Keyed off
    # the VALUE, this hook silently skipped it — so `slo:` with nothing after it passed birth while
    # the register kept nagging, the two surfaces disagreeing yet again. An ABSENT key is untouched
    # by this: it never enters the hook at all, because absence is a stance the register asks about
    # rather than a shape defect (`lessons/a-stance-mirror-is-only-sound-at-birth.md`).
    if "slo" in sec:
        missing = _alert_routing_slo_missing(sec["slo"])
        if missing == [SLO_WAIVER_REASON]:
            errs.append(f"{label}.slo: waived with no reason — a waiver is a STANCE only when it says "
                        f"WHY (SPEC-0119 rule 39, the same rule the gap register applies). A "
                        f"reasonless waiver is indistinguishable from one somebody started writing "
                        f"and stopped, so it neither answers `slo:` nor closes its gap. Give the "
                        f"waiver a non-blank `reason:` (or a bare string, which IS its own reason), "
                        f"declare `objective:` + `target:`, or omit `slo:` entirely.")
        elif missing:
            errs.append(f"{label}.slo: declared but missing/blank " + " and ".join(
                f"`{k}:`" for k in missing) + " — a declared SLO answers BOTH parts: `objective:` "
                f"(what is promised) AND `target:` (the number that decides whether it was kept) "
                f"(SPEC-0164 rule 5). An objective with no target reads as a promise while "
                f"committing to nothing measurable — the same coverage-shaped silence as a sink "
                f"with no receiver (rule 2). If this project declares no objective yet, OMIT `slo:` "
                f"entirely (absence is a stance, not an error) or waive it with a reason.")

    if not _ops_declared(sec.get("sink"), "string"):
        return errs                                   # undeclared/blank sink — the generic check owns it
    if not _ops_declared(sec.get("receiver"), "string"):
        errs.append(f"{label}.receiver: `sink:` is declared but `receiver:` is missing or blank — a "
                    f"declared alert_routing answers BOTH parts (sink + receiver); they are ONE stance "
                    f"(SPEC-0164 rule 2). Declare WHO reads it and ACTS — a named human, rota, or "
                    f"on-call identity (or the automation that escalates to one). An alert nobody reads "
                    f"is not routing; if this project routes nowhere, WAIVE with a reason (rule 1).")
    return errs


def _hook_deploy_policy(label: str, sec: dict, ops: dict) -> list:
    """RESIDUAL shape for `deploy.policy` (SPEC-0097 §4) — the Class-C1 pre-deploy `pg_dump` carrier.

    Guards the shape where a carrier is BORN, so a third shape cannot appear silently in prod. Before
    this hook the sweep checked only that `classes:` was declared, and two production consumers carried a
    `pg_dump` shape the deploy verb refused — they classified autonomous at the gate and then exited 3 on
    every Class-C1 deploy (T-10286 / X-0267).

    The UNIT is the DECLARED, non-waived `classes.C1` BLOCK, not the `pg_dump` key: a C1 block with no
    `pg_dump` at all passes a key-scoped check and still refuses at deploy. A `waiver:`'d C1 is
    owner-gated, never autonomous, so it needs no runnable dump. The two accepted shapes and the budget
    predicate are IMPORTED from the deploy boundary (`lib.deploy`, the way this module already imports
    `lib.state`) — a birth check that re-implemented them would drift, and a carrier that passes init
    would refuse at deploy: the declare-vs-execute gap this hook exists to close (CHARTER §P5).

    FAIL-CLOSED on a PRESENT declaration only. It never backfills, auto-heals, or mirrors a consumer's
    stance — an absent `classes:`/`C1` is a stance, not a defect (`lessons/a-stance-mirror-is-only-sound-at-birth.md`)."""
    from lib import deploy  # CHARTER §P5 — one home for the pg_dump carrier shape + budget predicate

    errs: list = []
    classes = sec.get("classes")
    if not isinstance(classes, dict) or "C1" not in classes:
        return errs                                  # waived / undeclared / C1 not declared — a stance
    c1 = classes.get("C1")
    key = f"{label}.classes.C1.pg_dump"
    shapes = f"declare {deploy.PG_DUMP_SHAPES}"
    if not isinstance(c1, dict):
        errs.append(f"{label}.classes.C1: present but not a mapping, so it can carry no {key} — {shapes}")
        return errs
    if "waiver" in c1:
        return errs                                  # explicitly non-applicable (SPEC-0097 §6) — no dump needed
    if "pg_dump" not in c1:
        errs.append(f"{key}: a declared Class-C1 block carries NO pre-deploy backup command — an "
                    f"autonomous C1 deploy REFUSES without one (SPEC-0097 §4). {shapes}, or waive the "
                    f"class (`waiver: {{reason: <why>}}`)")
        return errs
    command, budget, shape_error = deploy._normalize_pg_dump(c1)
    if shape_error:
        errs.append(f"{key}: {shape_error}")
        return errs
    if not (isinstance(command, str) and command.strip()):
        errs.append(f"{key}: the backup command is absent or blank — {shapes}")
    if not deploy._positive_budget(budget):
        errs.append(f"{key}: the duration budget is absent or not a positive integer — without it the "
                    f"SPEC-0097 §4 over-budget ⇒ Class-C2 rule cannot be enforced. {shapes}")
    return errs


def _hook_sandbox_entry(label: str, sec: dict, ops: dict) -> list:
    """RESIDUAL shape for `sandbox_entry` (SPEC-0169) — a PRESENT section must NAME the entry.

    The concern is OPT-IN, and that half is owned by the GENERIC sweep, not by this hook: most projects
    have no collaborator sandbox, so an ABSENT section is never reached here and such a project is asked
    NOTHING (SPEC-0128 Rule 2 — the opt-in branch runs a hook only when the section is `present`). This
    hook exists because the same branch checks a PRESENT section ONLY through the named hook: without one,
    ANY `sandbox_entry:` content — `{}`, a leftover placeholder, a non-mapping — sweeps CLEAN, so an entry
    that is hand-wired elsewhere and answered nowhere stays invisible to conformance. That is the exact
    invisibility this concern exists to end (SPEC-0169 §8 — reach is DECLARED, never implied).

    So: a PRESENT block must be USABLE, fail-CLOSED (the `live_revision` precedent, T-10521/rule 23 — a
    present-but-EMPTY `{}` is malformed opt-in config, NOT absence). It is ANSWERED by a non-empty
    `entry:` string (the registry's own `declare_key`/`declare_type`, read through the shared
    `_ops_declared` — no parallel type logic) OR by a `waiver:` mapping (the declaration's own
    `waiver_policy: loose` — a recorded, reasoned opt-out is the OPPOSITE of the silence this closes).

    The entry is a LOCATION, never a credential (SPEC-0169's born prose / SPEC-0100 §Security). This hook
    deliberately does NOT sniff the VALUE for secrets: that is the behavioral-detector class CHARTER §6
    forbids, and no incident pulls it. It judges PRESENCE of an answer only — never the entry's
    reachability or its cage (the SPEC-0093 rule-3 boundary: the kernel checks the stance, not the
    correctness of what was declared), and it never backfills a stance it was not given."""
    errs: list = []
    if not isinstance(sec, dict):
        errs.append(f"{label}: present but not a mapping — declare `entry: <the address or handle a "
                    f"collaborator enters through>` (a LOCATION, never a credential), or "
                    f"`waiver: {{reason: <why>}}` (SPEC-0169).")
        return errs
    if isinstance(sec.get("waiver"), dict):
        return errs                                   # a reasoned waiver (LOOSE) — a recorded stance
    if not _ops_declared(sec.get("entry"), "string"):
        errs.append(f"{label}.entry: a PRESENT sandbox_entry section must NAME the entry point a "
                    f"collaborator enters through (a LOCATION, never a credential), or carry a "
                    f"`waiver: {{reason: <why>}}`. A section that answers neither leaves the entry "
                    f"hand-wired and invisible to conformance — the silence this concern ends "
                    f"(SPEC-0169). An absent section is fine: the concern is OPT-IN and a project "
                    f"with no collaborator sandbox owes nothing.")
    return errs


def _hook_freshness(label: str, sec: dict, ops: dict) -> list:
    """RESIDUAL shape for `freshness` (SPEC-0110 rule 6, T-10799) — a REACHABILITY-KIND declaration must
    NAME the address its probe reaches.

    THE DISCRIMINATOR IS THE PRESENCE OF THE `reachability` KEY, and it is the whole risk of this hook
    (`lessons/carving-an-exception-into-a-fail-closed-gate`). It is a key of its OWN because `kind:`
    already names how the kernel INVOKES the adapter (`command`|`file`, dispatched by nightly.py
    `_default_freshness_adapter`) and must keep meaning only that. A section carrying NO `reachability`
    key is not of this kind and is asked NOTHING — which is how the existing cohort (the kernel's own
    carrier and every consumer declaring plain pipeline freshness) keeps validating unchanged. That
    non-breakage is a REQUIREMENT of rule 6, not an accident of this implementation.

    FAIL-CLOSED ON THE DISCRIMINATOR ITSELF: a PRESENT `reachability:` that is unusable — not a mapping
    (`~`, a bare string, `true`) or a mapping with a missing/blank/wrong-typed `target` — is REFUSED, never
    read as "not of this kind". Otherwise a broken declaration would DISABLE the requirement it was
    written to satisfy, which is the bypass class that lesson names.

    IT JUDGES PRESENCE OF AN ANSWER ONLY — never the address's VALUE, its reachability, or its EDGE-ness,
    and it issues no request of its own (SPEC-0093 rule 3 / SPEC-0110 rule 6 / SPEC-0174 rule 2: the
    kernel cannot confirm an address IS the live edge without REQUESTING it, and requesting is exactly
    what the grade-only boundary forbids — so edge-ness stays ADVISORY and a declaration naming an
    INTERNAL address is ACCEPTED, with the named address left readable from the parsed declaration).
    Deliberately NO url parse, NO localhost/scheme sniff, NO normalization: a value heuristic here is the
    behavioral-detector class CHARTER §6 forbids, and normalizing would cost the very legibility rule 6
    buys. And it never backfills a stance — a non-mapping section or a `waiver:` is the GENERIC
    declare-or-waive check's business (`lessons/a-stance-mirror-is-only-sound-at-birth`)."""
    errs: list = []
    if not isinstance(sec, dict):
        return errs                                   # not a mapping — the generic stance check owns it
    if isinstance(sec.get("waiver"), dict):
        return errs                                   # a reasoned waiver (LOOSE) — a recorded stance
    if "reachability" not in sec:
        return errs                                   # not a reachability-kind declaration — owes nothing
    reach = sec.get("reachability")
    if not isinstance(reach, dict):
        errs.append(f"{label}.reachability: present but not a mapping, so it can carry no `target:` — a "
                    f"declaration of the REACHABILITY KIND must NAME the address its probe reaches "
                    f"(`reachability: {{target: <the address>}}`). Remove the key if this adapter grades "
                    f"no reachability (SPEC-0110 rule 6).")
        return errs
    if not _ops_declared(reach.get("target"), "string"):
        errs.append(f"{label}.reachability.target: a REACHABILITY-KIND freshness declaration must NAME "
                    f"the address its probe reaches — declare `target: <the address>`. An INTERNAL "
                    f"(non-edge) address is a COMPLETE answer and is accepted: reaching the live edge is "
                    f"ADVISORY and never enforced, because the kernel cannot confirm an address IS the "
                    f"edge without REQUESTING it, which the grade-only boundary forbids (SPEC-0174 rule "
                    f"4). What naming buys is LEGIBILITY — a probe quietly reaching past the live edge "
                    f"stops being invisible. If this adapter grades no reachability, remove the "
                    f"`reachability:` key entirely (SPEC-0110 rule 6).")
    return errs


# SPEC-0175 rule 5's SIGNAL TABLE, carried as data (T-10958). Each row is (human name, carrier paths,
# kind) — the ONLY thing this module says about what "contradicts a spike_data_safety waiver" means; the
# normative home is the rule-5 table itself, which names these exact paths, so a drift is visible by
# reading the two side by side. `bool` = the boolean-shaped bridge switch; `declared` = read
# TYPE-GENERICALLY through `_ops_declared(v, None)`, so a command string, a list of steps and a mapping
# all count as declared while `~` / `""` / `[]` / `{}` do not (audit-pre finding, absorbed mode-(b)).
_SPIKE_DATA_SAFETY_SIGNALS = (
    ("an ENABLED spike bridge", ("spike_sandbox.bridge.enabled",), "bool"),
    ("a DECLARED refresh/export step", ("spike_sandbox.bridge.refresh", "spike_sandbox.bridge.export",
                                        "spike_sandbox.refresh", "spike_sandbox.export"), "declared"),
    ("recorded evidence of a RESTORED COPY", ("spike_sandbox.restored_copy",
                                              "spike_data_safety.restored_copy"), "declared"),
)


def _hook_spike_data_safety(label: str, sec: dict, ops: dict) -> list:
    """RESIDUAL shape for `spike_data_safety` (SPEC-0175 rule 5, T-10958) — a WAIVER that the project's
    own declarations CONTRADICT is refused, naming the contradicting path.

    THE ASSERTION A WAIVER MAKES IS CHECKABLE. Waiving this section asserts a FACT — "this project fills
    no sandbox from a production-derived copy" — and the carrier already holds declarations that can
    contradict it. Until this hook, the concern's `waiver_policy: loose` accepted any reasoned waiver as
    written, so the assertion was taken at its word: rule 5 called its own refusal DISCIPLINE for exactly
    that reason. This is the check that makes it performed, and it adds NO store, parser or registry — it
    is one registry-NAMED validator on the sweep's existing residual-hook seam (SPEC-0128 rule 2), fed the
    whole parsed carrier the sweep had already read.

    SCOPED TO THE WAIVED STANCE, which is the whole anti-over-refusal boundary (card `OUT:`). A section
    that DECLARES `data_safety:` is asked NOTHING here even beside an enabled bridge — that project
    answered the question, and judging its answer is rule 6's proof obligation, not this hook's. An ABSENT
    section is the GENERIC stance check's business (`presence_policy: mandatory` already refuses it), and
    a non-mapping section likewise. The hook never backfills a stance it was not given
    (`lessons/a-stance-mirror-is-only-sound-at-birth`), and a check that refused EVERY waiver would break
    the declare-or-waive contract for every project that legitimately runs no spike sandbox — the honest
    one-line answer rule 5 keeps cheap.

    THE DISCRIMINATOR ITSELF FAILS TOWARDS REFUSAL, never towards silence
    (`lessons/carving-an-exception-into-a-fail-closed-gate`): a signal is read as PRESENT whenever its path
    resolves to a truthy switch / a non-empty declaration, and an unreadable intermediate simply does not
    resolve — no shape of malformed spike wiring turns a contradicted waiver into a clean sweep, because
    the generic sweep is separately fail-closed on those sections' own stances.

    IT READS DECLARATIONS, NEVER VALUES. `enabled: false` is a real answer, not a contradiction; nothing
    here parses a URL, sniffs a dump path or judges whether a refresh step is "really" production-derived.
    A value heuristic would be the behavioral-detector class CHARTER §6 forbids, and rule 5's refusal is
    about a project's own DECLARED facts contradicting its own DECLARED waiver."""
    errs: list = []
    if not isinstance(sec, dict):
        return errs                                   # not a mapping — the generic stance check owns it
    if not isinstance(sec.get("waiver"), dict):
        return errs                                   # DECLARED / unanswered — not this hook's business
    if _ops_declared(sec.get("data_safety"), "mapping"):
        return errs                                   # a BOTH-keys section: the generic XOR error owns it
    for name, paths, kind in _SPIKE_DATA_SAFETY_SIGNALS:
        for path in paths:
            present, val = _ops_navigate(ops, path)
            if not present:
                continue
            if kind == "bool":
                if not isinstance(val, bool) or not val:
                    continue                          # `enabled: false` is an ANSWER, not a contradiction
            elif not _ops_declared(val, None):
                continue                              # `~` / `""` / `[]` / `{}` declares nothing
            errs.append(
                f"{label}: the waiver asserts this project fills no sandbox from a production-derived "
                f"copy, but the carrier CONTRADICTS it — `{path}` declares {name}. A waiver that the "
                f"project's own declarations contradict is REFUSED (SPEC-0175 rule 5). Two honest exits: "
                f"declare `data_safety: {{reachability, disclosure, operational_state, "
                f"none_of_the_three, proof}}` for the copy this project actually restores, or remove the "
                f"contradicting declaration if the spike sandbox is genuinely gone.")
            break                                     # one error per SIGNAL, not per alias path
    return errs


_SPIKE_SANDBOX_SIGNALS = (
    ("a DECLARED restored-copy data-safety inventory", ("spike_data_safety.data_safety",), "declared"),
)


def _hook_spike_sandbox(label: str, sec: dict, ops: dict) -> list:
    """RESIDUAL shape for `spike_sandbox` (SPEC-0172 rule 2a, T-11060) — a WAIVER that the project's own
    declarations CONTRADICT is refused, naming the contradicting path. The MIRROR of
    `_hook_spike_data_safety` (SPEC-0175 rule 5), deliberately built to the same structure so the pair
    cannot drift into two different readings of one contradiction.

    WHAT THE TWO ANSWERS EACH ASSERT, which is why they cannot stand together. Waiving `spike_sandbox`
    asserts this project keeps no caged spike stack. A declared `spike_data_safety.data_safety` inventory
    describes what a RESTORED PRODUCTION COPY carries — and a restored copy is filled INTO a spike stack.
    The refusal is not a judgement about the project; it is the carrier disagreeing with itself.

    WHY THIS IS REFUSED RATHER THAN WARNED (SPEC-0172 rule 2a carries the full reason). Rule 4's cage
    atoms are read over the project's DECLARED cage, so a waiver retires the cage question entirely —
    nothing declared, nothing read. A report-only line would leave this contract's strongest answer
    switched off by the very answer claiming it is unneeded.

    SCOPED TO THE WAIVED STANCE, which is the whole anti-over-refusal boundary (card `BOUND:`). A section
    that DECLARES `bridge:` is asked NOTHING here even beside a declared `data_safety` — that project
    answered the question. An ABSENT section is the GENERIC stance check's business (`presence_policy:
    mandatory` already refuses it), and a non-mapping section likewise. The hook never backfills a stance
    it was not given (`lessons/a-stance-mirror-is-only-sound-at-birth`), and a check that refused EVERY
    waiver would break the declare-or-waive contract for every project that legitimately runs no spike
    sandbox — the honest one-line answer rule 2 keeps cheap. Measured at authoring: of the 10 registry
    consumers, TWO carry that plain-waiver shape and MUST stay clean.

    THE DISCRIMINATOR ITSELF FAILS TOWARDS REFUSAL, never towards silence
    (`lessons/carving-an-exception-into-a-fail-closed-gate`): a signal is read as PRESENT whenever its
    path resolves to a non-empty declaration, and an unreadable intermediate simply does not resolve — no
    shape of malformed data-safety wiring turns a contradicted waiver into a clean sweep, because the
    generic sweep is separately fail-closed on that section's own stance.

    IT READS DECLARATIONS, NEVER VALUES. Nothing here parses a dump path, resolves a pin, or judges
    whether a stack is "really" a spike. A value heuristic would be the behavioral-detector class
    CHARTER §6 forbids, and rule 2a's refusal is about a project's own DECLARED facts contradicting its
    own DECLARED waiver.

    ONE SIGNAL, DELIBERATELY. The card's HARD BOUND scopes this to the single contradiction shape; a
    second signal would begin the cross-concern consistency engine rule 2a explicitly refuses to become."""
    errs: list = []
    if not isinstance(sec, dict):
        return errs                                   # not a mapping — the generic stance check owns it
    if not isinstance(sec.get("waiver"), dict):
        return errs                                   # DECLARED / unanswered — not this hook's business
    if _ops_declared(sec.get("bridge"), "mapping"):
        return errs                                   # a BOTH-keys section: the generic XOR error owns it
    for name, paths, kind in _SPIKE_SANDBOX_SIGNALS:
        for path in paths:
            present, val = _ops_navigate(ops, path)
            if not present:
                continue
            if not _ops_declared(val, None):
                continue                              # `~` / `""` / `[]` / `{}` declares nothing
            errs.append(
                f"{label}: the waiver asserts this project keeps no caged spike stack, but the carrier "
                f"CONTRADICTS it — `{path}` declares {name}, which describes what a RESTORED PRODUCTION "
                f"COPY carries, and a restored copy is filled into a spike stack. A waiver that the "
                f"project's own declarations contradict is REFUSED (SPEC-0172 rule 2a). Two honest "
                f"exits: declare `bridge: {{pin, enabled, cage_checks}}` for the stack this project "
                f"actually keeps (`enabled: false` is a real answer if no shared bridge is pinned), or "
                f"remove the contradicting declaration if the spike sandbox is genuinely gone.")
            break                                     # one error per SIGNAL, not per alias path
    return errs


# SPEC-0186 rules 1+3 (T-11281) — the CLOSED value set of `verify_policy.pinned_last_green`, held in
# EXACTLY ONE place in the kernel. The spec names this hook as the single enforcement carrier precisely so
# no second list exists: the runtime reader (`bin/lib/task.py#_verify_policy_pinned_last_green`) compares
# against `never` and defaults `all` — a comparison, not a table — and asks THIS validator whether a
# `never` declaration is valid at all. Anything that would need a second copy of these two values is a
# sign the rule grew a second home.
VERIFY_POLICY_PINNED_LAST_GREEN_VALUES = ("all", "never")


def _hook_verify_policy_pinned_last_green(label: str, sec: dict, ops: dict) -> list:
    """RESIDUAL shape for `verify_policy` (SPEC-0186 rules 1+3, T-11281) — the KERNEL-OWNED validator the
    concern block NAMES, carrying the closed `all|never` enum AND the value-dependent `reason` condition.

    IT IS THE ONE ENFORCEMENT CARRIER, and that is the point rather than an implementation taste. The
    plan's anti-complexity F3 filter is candidly weak (no mechanism is removed, only an obligation), so
    the only thing making the addition honest is that the declaration's SURFACES are generated from the
    one `concern:` block and its SHAPE is checked by one named hook — no hand-kept schema, no second
    value list, no parallel parser. `graph build`'s concern↔hook cross-check pins the membership.

    OPT-IN (`presence_policy: opt-in`, and rule 1's fail-closed default): an ABSENT section is VALID and
    reads `all`, so the generic sweep never calls this hook for absence and there is no declare-or-waive
    stance to mirror. A PRESENT section, however, must be USABLE — the `_hook_live_revision` posture:
    accepting a malformed block would let broken config silently REMOVE a verification layer, which is the
    one direction this concern must never fail in.

    THE `reason` CONDITION IS VALUE-DEPENDENT, and both directions are enforced here because rule 1 states
    both: `never` REQUIRES a non-empty reason (a whitespace-only string is not a reason), while `all` MAY
    carry an absent or null one — which is exactly what the generated born entry ships
    (`pinned_last_green: all` + `reason: ~`), so the template must validate under its own hook.

    A `never` THAT FAILS THIS CHECK DOES NOT TAKE EFFECT. The runtime reader consults this validator and
    resolves such a declaration to `all` (fail-closed, the same direction as its unparseable-carrier
    default), so an invalid declaration can never silently disable the leg while its own contract is
    refused at `init`. That is why the condition lives HERE and is CALLED there, rather than being
    restated at the reader: one rule, one home (CHARTER §P5).

    IT JUDGES THE DECLARATION, NEVER THE REASON'S MERIT — the SPEC-0093 rule-3 boundary. Whether "we
    measured zero catches" is a GOOD reason is the audit's question (the declaration is fast-path
    INELIGIBLE and takes both audits, SPEC-0186 rule 5); whether a reason was GIVEN is this hook's."""
    errs: list = []
    if sec is None:
        # THE BORN SHAPE: an uncommented `verify_policy:` header whose two keys are COMMENTED parses to
        # None. That is the state every project is born in and it is exactly equivalent to absence —
        # nothing is declared, so nothing is owed, and the project reads `all` (rule 1). Distinguished
        # from the malformed cases below on purpose: a header with nothing under it is DOCUMENTATION,
        # while a header carrying a string/list/empty-mapping is a declaration that failed to say
        # anything, and only the second can quietly remove a verification layer.
        return errs
    if not isinstance(sec, dict):
        errs.append(f"{label}: present but not a mapping — declare `pinned_last_green: all` (the default) "
                    f"or `pinned_last_green: never` with a non-empty `reason:` (SPEC-0186 rule 1). An "
                    f"absent section is valid and reads `all`; a malformed one must not disable the leg.")
        return errs
    value = sec.get("pinned_last_green")
    if value is None:
        errs.append(f"{label}: present but declares no `pinned_last_green:` — a PRESENT section must say "
                    f"which of {' | '.join(VERIFY_POLICY_PINNED_LAST_GREEN_VALUES)} this project pays "
                    f"(SPEC-0186 rule 1). Remove the section to keep the `all` default, or declare it.")
        return errs
    if value not in VERIFY_POLICY_PINNED_LAST_GREEN_VALUES:
        errs.append(f"{label}.pinned_last_green: {value!r} is not one of "
                    f"{' | '.join(VERIFY_POLICY_PINNED_LAST_GREEN_VALUES)} — the value set is CLOSED "
                    f"(SPEC-0186 rule 1). An unrecognised value reads `all` at runtime, so this contract "
                    f"does not say what it appears to say.")
        return errs
    if value == "never":
        reason = sec.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            shown = "missing" if reason is None else repr(reason)
            errs.append(f"{label}.reason: `pinned_last_green: never` REQUIRES a non-empty `reason:` and "
                        f"this one is {shown} (SPEC-0186 rule 1). Turning off the SPEC-0077 pinned "
                        f"last-green leg is an act that names who accepted the risk and why; without it "
                        f"the declaration is INVALID and this project still reads `all`.")
    return errs


# The shape-hook dispatch — name (from the `concern.shape_hook` registry field) → validator. The name set
# MUST equal _CONCERN_SHAPE_HOOKS (graph build's orphan/missing check enforces the concern↔hook mapping).
def _hook_reads_exemptions(label: str, sec, ops: dict) -> list:
    """SPEC-0160 rule 25 / SPEC-0190 rule 10 residual (OPT-IN — no declare-or-waive stance): the
    `reads.exemptions[]` per-entry shape for a composed seam that cannot hold rule 10's bound.

    Each entry needs ALL FOUR of `seam` / `ratio_bound` / `reason` / `until`, and the refusal NAMES
    which are missing. The naming is the point, not ergonomics: this surface has NO reader that fails
    visibly (nothing renders an exemption back to a human, unlike rule 24's `outcome_invariants:`
    whose degraded debt line is its own alarm), so a half-registered entry would be inert AND
    invisible — the seam would read as exempted while nothing recorded what was accepted, by whom, or
    until when. That is strictly worse than an absent entry, which is why this hook exists at all.

    `ratio_bound` must be a POSITIVE NUMBER because an exemption with no ceiling is a repeal: the seam
    would be released from rule 10 rather than held to a wider bound. `bool` is excluded explicitly —
    it is a subclass of `int` in Python, so `ratio_bound: true` would otherwise pass as the number 1.

    NOTE `sec` is the RAW section value (opt-in bypasses the generic is-a-mapping check), so this
    hook self-checks the type — the `_hook_extensions` model. Shape only, never VALUES (rule 3): a
    `seam` naming no real symbol and a generous `ratio_bound` are the project's business."""
    errs: list = []
    if not isinstance(sec, dict):
        errs.append(f"{label}: present but not a mapping (SPEC-0160 rule 25)")
        return errs
    if "exemptions" not in sec:
        return errs
    entries = sec.get("exemptions")
    if not isinstance(entries, list):
        errs.append(f"{label}.exemptions: present but not a list — use `exemptions: []` for none, or "
                    "omit the key entirely (SPEC-0160 rule 25)")
        return errs
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            errs.append(f"{label}.exemptions[{i}]: not a mapping "
                        "(need seam + ratio_bound + reason + until — SPEC-0160 rule 25)")
            continue
        missing = [k for k in ("seam", "reason")
                   if not (isinstance(e.get(k), str) and e.get(k).strip())]
        rb = e.get("ratio_bound")
        if isinstance(rb, bool) or not isinstance(rb, (int, float)) or rb <= 0:
            missing.append("ratio_bound (a positive number — an exemption with no ceiling is a repeal)")
        if not _is_iso_date(e.get("until")):
            missing.append("until (a real ISO date YYYY-MM-DD review-by date)")
        if missing:
            errs.append(f"{label}.exemptions[{i}]: missing/malformed " + ", ".join(missing)
                        + " — all four of seam/ratio_bound/reason/until are REQUIRED, fail-closed "
                          "(SPEC-0160 rule 25 / SPEC-0190 rule 10)")
    return errs


# ── T-12046 (SPEC-0196 rules 1 + 3) — THE OVERRIDE-LEDGER ENTRY SHAPE ─────────────────────────────
# The CLOSED `upstream_intent` vocabulary of SPEC-0196 rule 1. Closed is the whole point: the four
# words are the machine-readable STATE of a divergence, and a fifth word invented at a keyboard is
# not a fifth state, it is an entry nobody can act on. `not-forwarded` is admitted deliberately — it
# is a RECORDED DECISION with its own review trigger, which is exactly what makes it different from
# an entry that simply never says.
OVERRIDE_INTENTS: tuple = ("temporary-patch", "forwarded", "accepted-exception", "not-forwarded")

# The four fields rule 1 says an entry carries EXACTLY. Named here, once, so the sweep and the
# report-only drift check cannot disagree about what "malformed" means.
OVERRIDE_ENTRY_FIELDS: tuple = ("path", "rationale", "upstream_intent", "review_trigger")


def override_entry_errors(entry, index=None) -> list:
    """The SINGLE entry-shape judgement for one override-ledger entry (SPEC-0196 rule 1).

    TWO readers call THIS function and nothing else: the fail-closed init sweep (via
    `_hook_override_ledger` below) and the REPORT-ONLY drift check that rides `update` and the
    nightly (`release.ledger_drift`). That is not tidiness — a divergence between the two would mean
    a ledger the sweep accepts and the report calls malformed, or worse the reverse, and the entry's
    whole purpose is to be the ONE place a local override is visible. One function, two readers.

    Returns the ordered list of plain-language reasons this entry is malformed; EMPTY means
    well-formed. It judges SHAPE, never VALUES (SPEC-0093 rule 3): whether the rationale is a GOOD
    reason, and whether the review date has PASSED, are not shape questions — the second is the
    report's OVERDUE finding, computed by the reader that knows what "now" is.

    `review_trigger` is admitted as EITHER a date-only ISO date OR a named artifact (rule 1: "an ISO
    date OR a named artifact whose close re-opens the entry"). A non-empty string is the widest the
    rule allows, and widening no further is deliberate: refusing an artifact id shape the kernel has
    not met would make the rule narrower than its own text."""
    label = "entry" if index is None else f"entries[{index}]"
    if not isinstance(entry, dict):
        return [f"{label}: not a mapping — an override entry carries "
                + "/".join(OVERRIDE_ENTRY_FIELDS) + " (SPEC-0196 rule 1)"]
    errs: list = []
    for key in ("path", "rationale"):
        v = entry.get(key)
        if not (isinstance(v, str) and v.strip()):
            errs.append(f"{label}.{key}: missing or empty — required (SPEC-0196 rule 1)")
    intent = entry.get("upstream_intent")
    if not (isinstance(intent, str) and intent.strip() in OVERRIDE_INTENTS):
        errs.append(f"{label}.upstream_intent: {intent!r} is not one of the CLOSED vocabulary "
                    + "|".join(OVERRIDE_INTENTS) + " (SPEC-0196 rule 1)")
    trigger = entry.get("review_trigger")
    if not (_is_iso_date(trigger) or (isinstance(trigger, str) and trigger.strip())):
        errs.append(f"{label}.review_trigger: missing — an override carries an EXPIRY, either an ISO "
                    f"date (YYYY-MM-DD) or a named artifact whose close re-opens it (SPEC-0196 "
                    f"rules 1 + 4). An override with no review trigger is a fork with a comment.")
    # EXACTLY those four fields — the closed half of rule 1, which the required-field checks above
    # cover only in one direction. Rule 1 ends "No other fields; no free-form policy text", and that
    # sentence is what keeps the ledger a divergence RECORD instead of a second methodology: an entry
    # free to carry `policy:` or `exception_scope:` becomes a place to write normative text, which is
    # precisely what rule 2 forbids and what no reader would ever act on. Rejecting the extra key by
    # NAME (rather than a bare "unexpected fields" count) is deliberate — the author needs to know
    # which word to delete.
    # `str(k)` before sorting: a YAML mapping may carry a non-string key, and sorting a mixed set
    # would raise where this function's whole contract is to RETURN reasons, never raise.
    for key in sorted(str(k) for k in entry if k not in OVERRIDE_ENTRY_FIELDS):
        errs.append(f"{label}.{key}: unknown field — an override entry carries EXACTLY "
                    + "/".join(OVERRIDE_ENTRY_FIELDS)
                    + " and no others (SPEC-0196 rule 1). A ledger entry is a divergence RECORD, "
                      "not a place for policy text (rule 2).")
    return errs


def _hook_override_ledger(label: str, sec, ops: dict) -> list:
    """SPEC-0196 rules 1-2 residual (OPT-IN — no declare-or-waive stance): the `overrides.entries[]`
    per-entry shape of the override ledger.

    OPT-IN is the right presence policy and worth stating: a project that diverges from NOTHING is
    the commonest and the healthiest state, so absence must be silence, not an unanswered question.
    Only the shape of what IS present is checked.

    NOTE `sec` is the RAW section value (opt-in bypasses the generic is-a-mapping check), so this
    hook self-checks the type — the `_hook_reads_exemptions` / `_hook_extensions` model. The
    per-entry judgement is DELEGATED to `override_entry_errors`, which the report-only drift check
    calls too; nothing about an entry is decided twice."""
    errs: list = []
    if not isinstance(sec, dict):
        errs.append(f"{label}: present but not a mapping (SPEC-0196 rule 1 — one `overrides:` "
                    f"section of yitc-ops.yaml, never a second file)")
        return errs
    if "entries" not in sec:
        return errs
    entries = sec.get("entries")
    if not isinstance(entries, list):
        errs.append(f"{label}.entries: present but not a list — use `entries: []` for no local "
                    f"divergence, or omit the section entirely (SPEC-0196 rule 1)")
        return errs
    for i, e in enumerate(entries):
        errs += [f"{label}.{m}" for m in override_entry_errors(e, i)]
    return errs


_SHAPE_HOOKS = {
    "security_shape": _hook_security,
    "deploy_policy_shape": _hook_deploy_policy,
    "host_config_shape": _hook_host_config,
    "tests_shape": _hook_tests,
    "inspection_shape": _hook_inspection,
    "ui_shape": _hook_ui,
    "verify_shape": _hook_verify,
    "extensions_shape": _hook_extensions,
    "runtime_delivery_shape": _hook_runtime_delivery,
    "live_revision_shape": _hook_live_revision,
    "remote_sync_shape": _hook_remote_sync,
    "alert_routing_shape": _hook_alert_routing,
    "runbook_shape": _hook_runbook,
    "sandbox_entry_shape": _hook_sandbox_entry,
    "freshness_shape": _hook_freshness,
    "spike_data_safety_shape": _hook_spike_data_safety,
    "spike_sandbox_shape": _hook_spike_sandbox,
    "verify_policy_pinned_last_green": _hook_verify_policy_pinned_last_green,
    "reads_exemptions_shape": _hook_reads_exemptions,
    "override_ledger_shape": _hook_override_ledger,
}


def _render_init_source_layer_prompt(items: list) -> str:
    """SPEC-0152 rule 16 (T-10312 / X-0140) — the BOOTSTRAP-context declare-or-waive prompt for the
    silently-absent source layers `worktree._undeclared_source_layers` found. The land guard (T-10303) draws
    the same finding at a consumer's FIRST land; drawing it here answers it at bootstrap instead.

    REPORT-ONLY: the caller prints it and appends NOTHING to the fail-closed `unanswered` list — a
    detected-but-unnamed LAYER is a prompt, never an ERROR (T-9372's blocking multi-layer gate stays
    wont-do). The detection registry keeps ONE carrier (`worktree._SOURCE_LAYER_MARKERS`, imported and never
    re-declared here — CHARTER §P5); only the per-call-site WORDING is local, since the land renderer's
    `land(consumer):` prefix does not name this moment."""
    head = (f"init: {len(items)} source layer(s) present in code but ABSENT from `verify.layers` "
            f"— declare-or-waive (report-only; SPEC-0152 rule 16, X-0140):")
    lines = [head]
    for layer, marker in items:
        lines.append(
            f"  - {layer}: detected via {marker}, named by no verify.layers entry — this layer would be "
            f"SILENTLY UNTESTED at land. Answer it now in {CONSUMER_OPS_CONTRACT} `verify.layers`: DECLARE "
            f"it (`- layer: {layer}` + a hermetic `command:`) OR WAIVE it (`- layer: {layer}` + `waiver: "
            f"{{reason: <why there is no harness yet + the GROW-TRIGGER that will pull one>}}`).")
    return "\n".join(lines)


def _render_init_runtime_delivery_prompt(evidence: list) -> str:
    """SPEC-0093 rule 22 / SPEC-0119 rule 16 (T-10511 / X-0370) — the BOOTSTRAP-context declare-or-waive
    prompt for a repo that bind-mounts its own SOURCE into a running service while declaring no
    runtime-delivery model. The standing debt echo draws the same finding at every later seam; drawing it
    HERE answers it at bootstrap instead — the moment the carrier is being filled in anyway.

    REPORT-ONLY: the caller prints it and appends NOTHING to the fail-closed `unanswered` list — a detected
    bypass is a PROMPT, never an init ERROR (the `_render_init_source_layer_prompt` posture, verbatim). The
    detector + the enum live in ONE home on the reading side (`lib.debt`, imported by the caller, never
    re-declared here — CHARTER §P5); only the per-call-site WORDING is local, since the debt echo's standing
    line does not name this moment."""
    head = (f"init: this project's PRODUCTION compose bind-mounts its own SOURCE into {len(evidence)} "
            f"service(s) while `deploy.runtime_delivery` is UNDECLARED — declare-or-waive (report-only; "
            f"SPEC-0093 rule 22, X-0370; PROD-scoped per T-10905 — each row names its compose file):")
    lines = [head]
    for e in evidence:
        lines.append(f"  - {e.get('service')}: {e.get('mount')} (in {e.get('compose')}) — the runtime reads "
                     f"this tree, so a container recreate ships `main` WITHOUT the deploy verb: no class "
                     f"gate, no pre-deploy backup, no live probe, no `deploy_completed`.")
    lines.append(f"  Answer it now in {CONSUMER_OPS_CONTRACT} `deploy.runtime_delivery`: DECLARE the model "
                 f"(`model: source-mounted` | `hot-reload` | `hybrid` — or `image-baked` if the compose named "
                 f"above is NOT what runs in prod; say which one is via the `-f` operand of your "
                 f"`deploy.command`) OR WAIVE it (`waiver: {{reason: <why this project has no runtime-delivery "
                 f"stance>}}`). Declaring a bypassable model gates NOTHING — it makes the kernel's own "
                 f"not-adopted reading honest (X-0370: half a paired change shipped on a recreate, 8h outage).")
    return "\n".join(lines)


def _render_init_unwaived_prod_mount_prompt(evidence: list, model: str) -> str:
    """T-10621 (the runtime-delivery doctrine — SPEC-0093 rule 22, T-10620) — the BOOTSTRAP-context prompt
    for a repo that DECLARES a bypassable runtime-delivery model yet keeps its executable-code bind mounts
    in the PROD compose with no waiver. The init sibling of the standing debt-echo `unwaived-prod-mount`
    line, drawn HERE at the moment the carrier is being filled in. Same REPORT-ONLY posture as the arm-(a)
    prompt above: the caller prints it and appends NOTHING to the fail-closed `unanswered` list. The detector
    + the doctrine vocabulary live in ONE home on the reading side (`lib.debt`, imported by the caller —
    CHARTER §P5); only the per-call-site WORDING is local."""
    head = (f"init: this project declares `runtime_delivery: {model}` but bind-mounts its own SOURCE into "
            f"{len(evidence)} PROD-compose service(s) with NO waiver — the runtime-delivery doctrine "
            f"(report-only; SPEC-0093 rule 22, T-10620, X-0370):")
    lines = [head]
    for e in evidence:
        lines.append(f"  - {e.get('service')}: {e.get('mount')} (in {e.get('compose')}) — a bypassable prod "
                     f"runtime is a WAIVER-ONLY exception off the image-baked default; a bare `model:` is not "
                     f"that waiver.")
    lines.append(f"  Take the doctrine route ({CONSUMER_OPS_CONTRACT} / patterns/deploy-coherence.md): the "
                 f"aiseller dev/prod compose SPLIT (source mounts → `docker-compose.dev.yaml`, prod on the "
                 f"baked image), OR migrate to `model: image-baked` after a measure-first bake, OR WAIVE it "
                 f"(`deploy.runtime_delivery.waiver: {{reason: <why + its compensating controls>}}`). Gates "
                 f"NOTHING — it keeps the kernel honest about what reaches prod.")
    return "\n".join(lines)


def _render_pending_scaffold_refresh(pending: list, cli_form: str) -> str:
    """T-10498 (X-0358 / X-0365) — the REPORT-ONLY pending-refresh notice: the staleness SIGNAL that a
    kernel-managed scaffold in this checkout has drifted from the engine and was deliberately NOT
    rewritten.

    Before this, a drifted scaffold had NO signal surface at all: init silently re-derived it (dragging a
    +31-line runner refresh into an unrelated task's diff when a sweep ran inside a task worktree —
    X-0358), and a consumer whose stale kernel-delivered producer deadlocked its own gate had nothing
    naming the staleness (X-0365). Reporting it NAMES each stale path and the one command that applies
    it, so the operator decides WHEN the refresh lands — in its own diff, not in someone else's.

    REPORT-ONLY by construction: the caller prints this and adds nothing to any fail-closed list, so a
    pending refresh never fails an init and never enters `material_delivery` (no write ⇒ no commit).
    `cli_form` is the caller's already-computed verb-invocation form (the engine `-C` form for a
    consumer, which has no local `bin/yitc-v2`) — one carrier, never recomputed here."""
    head = (f"init: {len(pending)} kernel-managed scaffold(s) are STALE vs the engine and were NOT "
            f"rewritten (report-only — T-10498):")
    lines = [head]
    for rel in pending:
        lines.append(f"  ↻ {rel}: drifted from the kernel scaffold — pending refresh")
    lines.append(f"  Apply when you want it in ITS OWN diff: {cli_form} init --refresh-scaffolds")
    return "\n".join(lines)


def _scaffold_is_kernel_ancestor(ENGINE_ROOT, rel: str, consumer_text: str):
    """T-10886 (X-0713) — is the consumer's copy of `rel` a PREVIOUS KERNEL RELEASE rather than locally
    authored work? Returns True (it is: purely BEHIND), False (it is not: the kernel never produced these
    bytes at this path), or None (UNDETERMINED — no git, not a checkout, or the probe errored).

    THE PROBLEM THIS SOLVES. `_scaffold_refresh_loss` below refuses a re-derive that would DELETE lines,
    which is the X-0713 shape. But a NEWER kernel legitimately deletes old scaffold lines too, so the
    line test ALONE would also refuse an honestly-behind consumer and wedge the ordinary path — the very
    divergence SPEC-0154 rule 5 exists to end (AC4's cohort complement). The distinguishing question is
    ancestry, and a real base IS available without inventing a delivered-content ledger (CHARTER §P1 F2 —
    a view over data already on disk): the ENGINE checkout's OWN git history of that path. If the
    consumer's exact bytes ever existed as the engine's blob at `rel`, the consumer carries a kernel
    release and nothing local can be lost by re-deriving. If they never did, the consumer authored
    something — and only then does a deletion mean destroyed work.

    UNDETERMINED FAILS CLOSED at the CALLER: the caller treats None like False and falls through to the
    deletion test, so an unavailable probe can only ever make init MORE conservative (report + refuse),
    never license a silent overwrite. Bounded: the revision walk stops at `_ANCESTRY_REV_CAP` commits
    touching that path, so a deep engine history cannot make init slow. Exceeding the cap without a hit
    returns None (undetermined — "not found within the bound" is not "never existed")."""
    import subprocess
    from pathlib import Path
    if not (Path(ENGINE_ROOT) / ".git").exists():
        return None
    def _git(args, stdin_text=None):
        return subprocess.run(["git", "-C", str(ENGINE_ROOT), *args], input=stdin_text,
                              capture_output=True, text=True, timeout=60)
    try:
        h = _git(["hash-object", "--stdin"], stdin_text=consumer_text)
        if h.returncode != 0:
            return None
        want = h.stdout.strip()
        if not want:
            return None
        # `--follow` is deliberately NOT used: a rename would change the path this scaffold is delivered
        # at, and we are asking about THIS path's kernel bytes, not the file's biography.
        r = _git(["rev-list", f"--max-count={_ANCESTRY_REV_CAP + 1}", "--all", "--", rel])
        if r.returncode != 0:
            return None
        revs = [x for x in r.stdout.split() if x]
        capped = len(revs) > _ANCESTRY_REV_CAP
        for rev in revs[:_ANCESTRY_REV_CAP]:
            b = _git(["rev-parse", "--verify", "--quiet", f"{rev}:{rel}"])
            if b.returncode == 0 and b.stdout.strip() == want:
                return True
        return None if capped else False
    except (OSError, subprocess.SubprocessError):
        return None


# The engine-history walk bound for `_scaffold_is_kernel_ancestor`. Scaffolds are low-churn files, so a
# few hundred path-touching commits reaches far past any real consumer's birth release; the cap exists so
# init's cost stays bounded on a deep history, not to express a policy about how old a copy may be.
_ANCESTRY_REV_CAP = 300


def _scaffold_refresh_loss(consumer_text: str, kernel_text: str) -> str:
    """T-10886 (X-0713) — would re-deriving this scaffold from the kernel DELETE lines the consumer copy
    carries? Returns "" when nothing is lost (identical, or the consumer copy is a strict SUBSEQUENCE of
    the kernel copy — purely additive on the kernel side); otherwise the rendered unified-diff HUNKS that
    contain the deletions, consumer-side as `-`.

    On aiseller T-0121 a `--refresh-scaffolds` re-derive of `bin/security-audit` performed a 24-LINE
    DELETION, removing an unreadable-vs-foreign producer guard that consumer had landed. The kernel copy
    was OLDER than the consumer's, so re-deriving from it destroyed work — with no diff, no confirmation,
    and no warning that the local copy was AHEAD. The only test on that path was `!=`.

    Loss is decided on line opcodes: `delete` AND `replace` both remove consumer bytes, so both count;
    `insert` does not. Rendering is a unified diff filtered to the hunks that carry a deletion — a
    refusal that merely said "no" would fix the loss and leave the BLINDNESS the reporter complained
    about (AC2). This test is the SECOND question, asked only when `_scaffold_is_kernel_ancestor` could
    not establish that the consumer copy is a previous kernel release."""
    import difflib
    if consumer_text == kernel_text:
        return ""
    a = consumer_text.splitlines(keepends=True)
    b = kernel_text.splitlines(keepends=True)
    # THE LOSS TEST IS AN EXACT SUBSEQUENCE SCAN, NOT difflib's opcodes. `SequenceMatcher` is a greedy
    # longest-matching-block recursion, NOT an LCS: it reports `replace` runs for line sets that ARE
    # order-preserved in the kernel copy, so a consumer copy that loses NOTHING would be refused (AC4(ii)
    # caught exactly this — and `autojunk=False` alone does not fix it, the greediness does it). "Every
    # consumer line still appears, in order" is the precise claim, and a two-pointer scan decides it
    # exactly in O(n+m). difflib is kept for RENDERING only, where approximation is cosmetic.
    it = iter(b)
    if all(any(x == line for x in it) for line in a):
        return ""
    hunks: list = []
    cur: list = []
    for line in difflib.unified_diff(a, b, fromfile="consumer (local)", tofile="kernel (engine)", n=2):
        if line.startswith("@@"):
            if cur and any(x.startswith("-") and not x.startswith("---") for x in cur):
                hunks.append("".join(cur))
            cur = [line if line.endswith("\n") else line + "\n"]
        elif cur:
            cur.append(line if line.endswith("\n") else line + "\n")
    if cur and any(x.startswith("-") and not x.startswith("---") for x in cur):
        hunks.append("".join(cur))
    return "".join(hunks)


def _scaffold_refresh_refusal(ENGINE_ROOT, rel: str, consumer_text: str, kernel_text: str,
                              accept_loss) -> str:
    """T-10886 — the ONE question every kernel-scaffold re-derivation asks before it writes: may this
    overwrite proceed? Returns "" (proceed) or the rendered deleting hunks (REFUSE, and show them).

    Order is load-bearing. (1) An explicit PER-FILE acknowledgement (`--accept-scaffold-loss <rel>`) is
    the operator saying "yes, I know, take the kernel copy" — it short-circuits, because the card's own
    fallback option is refuse-OR-acknowledge and a consumer that has read the diff must retain a way to
    adopt the kernel bytes. (2) ANCESTRY: a consumer copy that IS a previous kernel release proceeds
    even when the newer kernel deletes lines. (3) Only then the DELETION test. Undetermined ancestry
    falls through to (3) — more conservative, never less."""
    if rel in (accept_loss or ()):
        return ""
    if _scaffold_is_kernel_ancestor(ENGINE_ROOT, rel, consumer_text) is True:
        return ""
    return _scaffold_refresh_loss(consumer_text, kernel_text)


def _render_diverged_scaffold_refusal(diverged: list, cli_form: str) -> str:
    """T-10886 (X-0713) — the REFUSAL notice for a re-derive that would delete consumer-authored lines.

    `diverged` is an ordered list of `(rel, hunks)`. The reporter's complaint had two halves — the
    deletion happened, AND it was invisible — so this names each file AND renders what would be lost,
    then names the per-file acknowledgement that adopts the kernel copy anyway. Unlike the T-10498
    pending-refresh notice this is NOT report-only: the caller exits non-zero after it."""
    head = (f"init: REFUSED to re-derive {len(diverged)} scaffold(s) — the local copy has DIVERGED AHEAD "
            f"of the kernel and the overwrite would DELETE lines (T-10886 / X-0713):")
    lines = [head]
    for rel, hunks in diverged:
        lines.append(f"  ✗ {rel}: refusing --refresh-scaffolds; what would be LOST:")
        for h in (hunks or "").splitlines():
            lines.append(f"      {h}")
    lines.append("  Nothing was written for these paths. Either UPSTREAM your lines into the kernel "
                 "scaffold, or — having read the diff above — adopt the kernel copy explicitly:")
    lines.append(f"    {cli_form} init --refresh-scaffolds "
                 + " ".join(f"--accept-scaffold-loss {rel}" for rel, _ in diverged))
    return "\n".join(lines)


def _sweep_ops_carrier(ops_path) -> None:
    """SPEC-0093 rule 3 + SPEC-0128 Rule 2 (T-10037) — the GENERIC, registry-driven fail-closed sweep of the
    ops-contract carrier. Replaces the retired per-section branch ladder: it iterates the KERNEL-derived
    concern registry (graph/concern-registry.json — the single declaration source) and, per concern, applies

      1. `presence_policy` — `mandatory` (missing → ERROR), `checked-if-present` (absent → skip, the
         earlier-slice backward-compat), or `opt-in` (absent → skip, never a neither-error);
      2. the is-a-mapping check (a present non-mapping section → ERROR);
      3. a GENERIC declare-or-waive STANCE keyed off `declare_key` + `waiver_policy` (loose|strict): the
         section is ANSWERED iff it carries a non-empty declaration XOR a policy-valid `waiver:`. Declaring
         BOTH is a contradiction; NEITHER is unanswered; a present-but-empty declaration / malformed waiver
         fails closed;
      4. the concern's `shape_hook` (if named) for RESIDUAL entry-level shape only (probe/layer/theme entry
         shape, the host_config 3-key declaration, the tests↔verify command rule, optional broader keys).

    The message label is the concern's `carrier_path` (so nested subfields read `deploy.policy` /
    `deploy.host_config`). NON-WHITELIST invariant (owner hard constraint): the sweep iterates the
    kernel-KNOWN registry entries ONLY and IGNORES a project's own extra/unknown carrier sections. A missing
    mandatory / unanswered / contradictory / wrong-typed section is an ERROR (exit non-zero) — never a silent
    skip. Self-contained (inline yaml + SystemExit) so cmd_init's injected-deps contract stays unchanged
    (see the module header)."""
    import sys
    import yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)

    def _fail(msg: str) -> None:
        print(f"yitc-v2: {msg}", file=sys.stderr)
        raise SystemExit(1)

    try:
        ops = state.load_ops(ops_path) if ops_path.exists() else None
    except state.duplicate_ops_key_error() as e:
        # A duplicate top-level key silently LAST-WINS under the safe schema, so a later block can erase
        # an earlier section's declaration and the stance check below would never see it (T-10240/X-0236).
        # Refused here, not "re-seeded": the kernel owns the section SHAPE (SPEC-0093 rule 3), so the
        # redundant key is the consumer's to delete — a re-run of init cannot repair it.
        ops = None
        _fail(f"init: {CONSUMER_OPS_CONTRACT} is REFUSED — {e}. The kernel owns the section SHAPE "
              f"(SPEC-0093 rule 3): a repeated section silently overrides the earlier one, so its "
              f"declaration would be lost. Delete the redundant key(s), keeping ONE block per section.")
    except yaml.YAMLError as e:
        ops = None
        _fail(f"init: {CONSUMER_OPS_CONTRACT} failed to parse ({e}); re-run init to re-seed it.")
    if not isinstance(ops, dict):
        _fail(f"init: {CONSUMER_OPS_CONTRACT} is missing or not a mapping — the ops-contract carrier "
              f"(SPEC-0093) must declare-or-waive its sections; re-run init to re-seed it.")

    # SPEC-0152 rule 16 (T-10312 / X-0140) — the layer-PRESENCE prompt, the init sibling of the T-10303 land
    # guard. ONE call site, here — so it precedes the `unanswered` fail below and a consumer that is BOTH
    # unanswered AND frontend-bearing still sees it (the same ahead-of-the-returns placement the land guard
    # uses). REPORT-ONLY: nothing is appended to `unanswered`, so `_ops_carrier_violations` stays the single
    # stance verdict `concern_conformance` shares (no drift, CHARTER §P5) and no init can ever fail on this.
    # The marker registry is IMPORTED, never re-declared (one carrier per datum); the detector is pure and
    # fail-OPEN, so a malformed `verify:` yields no false "everything undeclared" here either.
    from lib.worktree import _undeclared_source_layers   # stdlib + lib.state/events/observe only — no cycle

    _absent = _undeclared_source_layers(ops_path.parent, ops.get("verify"))
    if _absent:
        print(_render_init_source_layer_prompt(_absent))

    # SPEC-0093 rule 22 / SPEC-0119 rule 16 (T-10511 / X-0370) — the bypassable-deploy prompt, the init
    # sibling of the standing debt-echo line. Same placement + posture as the layer prompt above: AHEAD of
    # the `unanswered` fail, so a consumer that is BOTH unanswered elsewhere AND source-mounted still sees
    # it; REPORT-ONLY, appending nothing to `unanswered`, so no init can ever fail on it. The fold is the
    # ONE home for both the detector and the born-placeholder rule (a born waiver is not an answer — the
    # X-0088 class), so this seam and the debt seams can never disagree about what "undeclared" means.
    from lib import debt as _debt   # stdlib + yaml only — no cycle (the lib.deploy import precedent)

    _delivery = _debt.runtime_delivery_coherence(ops_path, ops_path.parent)
    if _delivery.get("kind") == "undeclared-bypassable":
        print(_render_init_runtime_delivery_prompt(_delivery.get("evidence") or []))
    # T-10621 — the DECLARED-yet-unwaived arm (the runtime-delivery doctrine, T-10620). Same placement +
    # report-only posture: a declared bypassable model whose executable-code mounts still sit in the PROD
    # compose with no waiver gets the doctrine's bake/dev-split/waive prompt at bootstrap. Appends nothing to
    # `unanswered`, so no init can fail on it.
    elif _delivery.get("kind") == "unwaived-prod-mount":
        print(_render_init_unwaived_prod_mount_prompt(_delivery.get("evidence") or [],
                                                      _delivery.get("model") or "bypassable"))

    unanswered = _ops_carrier_violations(ops)

    if unanswered:
        _fail(f"init: {CONSUMER_OPS_CONTRACT} has UNANSWERED section(s) — declare-or-waive is fail-closed "
              f"(SPEC-0093 rule 3). Fix each: " + "; ".join(unanswered))

    # CROSS-CHECK the `adoption:` RECORDS against the stance the sections just passed (T-10481 / SPEC-0143
    # Rule 2 — the record MIRRORS the declare-or-waive stance). Runs AFTER the section sweep, because the
    # question it asks ("does the record tell the truth about its section?") is only meaningful once every
    # section IS answered — the same precondition `_mirror_adoption_status` is documented to need. A
    # SEPARATE verdict + fail, deliberately NOT folded into `_ops_carrier_violations`: that function is the
    # single source of the per-SECTION stance verdict and is SHARED with the report-only
    # `concern_conformance` view (SPEC-0119 rule 8), so merging a RECORD-level check into it would silently
    # change that view's semantics. Different subject, own function, one call site — and no parallel stance
    # LOGIC, since both resolve stance through `_mirror_adoption_status` (CHARTER §P5).
    contradictions = _adoption_stance_violations(ops)
    if contradictions:
        _fail(f"init: {CONSUMER_OPS_CONTRACT} has adoption record(s) that CONTRADICT the carrier's own "
              f"declared stance — the ledger is lying about this project (SPEC-0143 Rule 2, fail-closed; "
              f"the X-0088 half-registration class). Fix each: " + "; ".join(contradictions))


def _ops_carrier_violations(ops: dict) -> list:
    """PURE registry-driven declare-or-waive STANCE evaluation of a parsed ops carrier (SPEC-0093 rule 3 +
    SPEC-0128 Rule 2) — the SINGLE SOURCE of the per-concern stance verdict, with NO I/O and NO raise. It
    returns the ordered list of stance-violation strings (empty = every registry concern conformant).
    `_sweep_ops_carrier` wraps this and FAILS CLOSED at init time; the report-only concern-conformance view
    (`concern_conformance`, SPEC-0119 rule 8) calls the SAME function so the two surfaces can never drift
    (CHARTER §P5 — no parallel stance logic). Iterates the KERNEL-known registry entries ONLY (the
    NON-WHITELIST invariant — a project's own extra/unknown carrier sections are ignored)."""
    unanswered: list = []
    for entry in _load_concern_registry():
        cp = entry.get("carrier_path") or entry.get("section")
        if not (isinstance(cp, str) and cp.strip()):
            continue                                     # a mis-declared registry entry — skip (graph build flags it)
        label = cp
        declare_key = entry.get("declare_key")
        declare_type = entry.get("declare_type")
        presence = entry.get("presence_policy")
        waiver_policy = entry.get("waiver_policy") or "loose"
        hook = _SHAPE_HOOKS.get(entry.get("shape_hook"))

        present, val = _ops_navigate(ops, cp)

        if presence == "opt-in":
            # OPT-IN (e.g. extensions): absence adopts nothing (valid); only the SHAPE of what IS present is
            # checked — no declare-or-waive stance, no neither-error. The hook self-checks the raw type.
            if present and hook:
                unanswered += hook(label, val, ops)
            continue

        if not present:
            if presence == "mandatory":
                unanswered.append(f"{label}: missing or not a mapping")
            continue                                     # checked-if-present + absent → valid skip

        if not isinstance(val, dict):
            unanswered.append(f"{label}: present but not a mapping")
            continue

        # generic declare-or-waive STANCE (declare_key XOR waiver, per waiver_policy)
        has_decl_key = isinstance(declare_key, str) and declare_key in val
        has_waiver_key = "waiver" in val
        declared = has_decl_key and _ops_declared(val.get(declare_key), declare_type)
        if has_decl_key and has_waiver_key and not _themes_are_wholly_kernel_owned(cp, val):
            unanswered.append(f"{label}: declares BOTH `{declare_key}:` and a `waiver:` — a section is "
                              f"EITHER declared OR waived (SPEC-0093 rule 3/6)")
        elif declared:
            pass                                         # a valid declaration — residual shape via the hook
        elif has_waiver_key:
            unanswered += _ops_waiver_errors(label, val.get("waiver"), waiver_policy)
        elif has_decl_key:
            _ty = f" (expected {declare_type})" if declare_type else ""
            unanswered.append(f"{label}: `{declare_key}:` present but empty or wrong-typed{_ty} — declare a "
                              f"non-empty `{declare_key}:` or `waiver: {{reason: <why>}}` (SPEC-0093 rule 3)")
        else:
            unanswered.append(f"{label}: neither `{declare_key}: <...>` nor `waiver: {{reason: <why>}}` "
                              f"(SPEC-0093 rule 3)")

        # RESIDUAL deep shape — runs whenever the section is present + a mapping (the hook decides what to
        # check from the keys actually present, so it is safe alongside the stance errors above).
        if hook:
            unanswered += hook(label, val, ops)

    return unanswered


def _themes_are_wholly_kernel_owned(carrier_path, val) -> bool:
    """Does this `inspection:` section declare NOTHING BUT kernel-owned themes (SPEC-0160 rule 12,
    T-12053)? True = the section is declared, but the PROJECT declared nothing — the kernel did.

    TWO callers, one question, deliberately sharing one predicate:

      * the declare-or-waive XOR. The rule-12 XOR is REFINED, not broken: a project `waiver:` is the
        project's stance on its OWN themes, and the kernel-owned entry sits OUTSIDE it — so a waiver
        beside a wholly-kernel-owned `themes:` is the NORMAL born state of every consumer, not a
        contradiction. Declare a theme of your OWN beside that waiver and the contradiction is real
        again, the generic arm firing unchanged (which is why `_append_theme_entries` retires the
        waiver when appending a project-own theme).
      * the UNRATIFIED-ADOPTION debt view. Its subject is a declaration "nobody reviewed" — but there
        is nothing here for a consumer's owner to review: the entry is seeded by the kernel on an
        owner directive and is not the project's to decline, so ratifying it would record a human
        decision nobody was asked for. Counting it would put an un-actionable row in EVERY consumer's
        debt view permanently. The moment the project declares a theme of its own, the declaration IS
        a project decision and the row appears normally.

    Narrow BY CONSTRUCTION: scoped to the `inspection` concern by carrier path, and true only when
    EVERY entry IS the one permitted kernel-owned entry. Every other concern is untouched on both
    surfaces.

    `owner: kernel` ALONE IS NOT THE TEST, and that distinction is the whole safety of this predicate:
    `owner:` is a value the PROJECT writes into its own carrier, so a project could stamp it onto a
    theme of its own and thereby buy both exemptions this predicate grants — standing a waiver beside a
    real project declaration, and dropping its unratified-adoption row. So the entry must ALSO BE the
    kernel's: its `theme:` is the ONE seeded slug. There is exactly one kernel-owned entry, so
    "every entry is that entry" is exact rather than approximate, and a project theme wearing
    `owner: kernel` fails it."""
    if carrier_path != "inspection" or not isinstance(val, dict):
        return False
    themes = val.get("themes")
    if not (isinstance(themes, list) and len(themes) > 0):
        return False
    return all(isinstance(x, dict)
               and str(x.get("theme") or "").strip() == _KERNEL_THEME_SLUG
               and str(x.get("owner") or "").strip() == _KERNEL_THEME_OWNER
               for x in themes)


def _section_values_are_wholly_kernel_rendered(carrier_path, val, repo_root) -> bool:
    """Does this section carry NOTHING BUT values the KERNEL RENDERED (T-12165)? True = the section is
    declared, but every value in it is a DERIVED value `init` computed — not an answer any human gave.

    ONE caller, the UNRATIFIED-ADOPTION debt view. That view's subject is a declaration «nobody
    reviewed»; a wholly kernel-rendered section has nothing to review. `security.audit.profile_snapshot`
    is the shape it was written for: its `command:` is the ROUTE from a byte-copied producer to the ONE
    profile derivation site, rendered from `__YITC_CLI__` at init and self-healed by
    `_refresh_baked_engine_path` whenever the engine moves. SPEC-0198's doctrine is that a DERIVED value
    is never asked as a question, so such a section is ratified BY CONSTRUCTION — counting it would put
    an un-actionable row in EVERY consumer's debt view permanently, for a decision nobody was asked to
    make. The moment the project writes a value of its OWN there, the declaration IS a project decision
    and the row appears normally.

    The narrowing is the SAME shape as `_themes_are_wholly_kernel_owned`'s, and for the same reason.
    This predicate is DERIVED, never a hand list of exempt concerns: the born fragment for the concern
    (the generated `graph/born-ops.yaml`, whose SOURCE is the spec) is the reference, so a concern earns
    the exclusion only by being born wholly kernel-rendered.

      * EVERY born value in the section must carry the `__YITC_CLI__` render token — one born value the
        kernel does NOT render means the section asks the project something, and the whole section
        counts as before.
      * The consumer's key set must EQUAL the born one — a key of the project's own is a project value.
      * Each declared value must MATCH its born template with the token resolved to THIS consumer's own
        engine invocation (`<engine>/bin/yitc-v2 -C <this repo>`). Only the engine INSTALL ROOT is free,
        because that is the one part `_refresh_baked_engine_path` legitimately rewrites. So a project
        that edits the command — pointing it elsewhere, wrapping it, aiming it at another repo — fails
        the match and its row appears: the exemption cannot be inherited by a hand-written value.

    `T-12053`'s predicate is not reused here: that one asks whether the kernel OWNS the entry, this one
    whether the kernel RENDERED the value. Two questions, deliberately two predicates."""
    import re
    import textwrap
    from lib import state  # CHARTER §P5 one parser library — `load_str` is the governed text parse
    if not (isinstance(carrier_path, str) and carrier_path and isinstance(val, dict) and val):
        return False
    fragment = (_ops_born_nested_fragment(carrier_path) if "." in carrier_path
                else _ops_born_sections().get(carrier_path))
    if not fragment:
        return False
    try:
        born = state.load_str(textwrap.dedent(fragment))
    except Exception:                                    # noqa: BLE001 — a report-only surface never raises
        return False
    leaf = born.get(carrier_path.split(".")[-1]) if isinstance(born, dict) else None
    if not (isinstance(leaf, dict) and leaf) or set(leaf) != set(val):
        return False
    cli = r"\S+/bin/yitc-v2 -C " + re.escape(str(repo_root))
    for key, born_val in leaf.items():
        declared = val.get(key)
        if not (isinstance(born_val, str) and "__YITC_CLI__" in born_val
                and isinstance(declared, str)):
            return False                                 # a value the kernel does not render
        pattern = "^" + re.escape(born_val).replace("__YITC_CLI__", cli) + "$"
        if not re.match(pattern, declared.strip()):
            return False                                 # the project rewrote it — a project value
    return True


# the birth sentinel `_preseed_concern_adoptions` stamps as `owner:` — the bootstrap ACT, not a human
# decision. ONE carrier for the literal (the pre-seed writes it, this cross-check refuses it over a
# DECLARED section), so the two can never disagree about what "nobody reviewed this" looks like.
_ADOPTION_INIT_SENTINEL = "init"


def _adoption_stance_violations(ops: dict) -> list:
    """PURE cross-check of the `adoption:` RECORDS against the carrier's ACTUAL declare-or-waive stance
    (SPEC-0143 Rule 2 — the record MIRRORS the stance) — the READ-time sibling of `_ops_carrier_violations`
    (which judges SECTIONS). No I/O, no raise; returns the ordered violation strings (empty = every record
    is true about its section). `_sweep_ops_carrier` wraps it and FAILS CLOSED at init time.

    THE GAP THIS CLOSES (T-10415 / X-0088 — the half-registration class). Rule 2's mirror was enforced only
    at the two WRITE moments: the birth pre-seed (`_preseed_concern_adoptions`) derives the record FROM the
    stance, and `_adopt_concerns` (T-10484) REFUSES an `adopt` over an undeclared section. Nothing
    re-validated a record that was TRUE when written and became FALSE when the carrier LATER grew a
    declaration — so aiseller carried 9 records still reading the born `waive@init` while the carrier
    DECLARED those very sections (deploy, live_probe, rollback, security, tests, ui, verify, …), and the
    init sweep reported CLEAN the whole time: the ledger denying mechanisms the project actively runs.

    ONE ERROR arm, scoped to a section the carrier GENUINELY DECLARES (stance `adopt`):
      - RECORD-STATUS: a `waive`/`na` record over a DECLARED section — the record denies a live mechanism.
    (Variant-A decision, owner-approved 2026-07-13: a still-`owner: init` record whose status reads
    `adopt` over a DECLARED section is TRUTHFUL-but-unratified — DEBT, not a contradiction; it routes
    to the SPEC-0119 report view (fu_4a0e0f4c5f05), never a blocking gate. Blocking on it would
    fail-close consumers whose records are true.)

    NOT gated (the anti-false-positive boundary): a record over a WAIVED or ABSENT section (`waive`/`na`
    assert no active mechanism — they cannot lie in this direction), and the ABSENCE of a record entirely
    (the SPEC-0143 Rule-3 drift reconcile owns absence, not this check).

    The stance comes from the EXISTING `_mirror_adoption_status` — the SAME reader the pre-seed and the
    T-10484 write gate use (one stance home, CHARTER §P5). That reuse is load-bearing, not tidiness: it
    inherits `_ops_declared`'s rule that an EMPTY opt-in declare-key is NOT a declaration (`coverage:
    {load_bearing: []}` / `extensions: {adopts: []}`), so an honest `na@init`/`waive@init` record over an
    un-opted opt-in section is NOT flagged. Re-deriving that emptiness test by hand is exactly how the
    T-10415 hand-check's first draft false-flagged two honest records.

    This check WRITES NOTHING — it refuses a contradiction and names both honest exits, leaving the
    question the owner's (`lessons/a-stance-mirror-is-only-sound-at-birth`: the trap is writing a mirrored
    stance AFTER birth, which is why the fix is never auto-applied here)."""
    violations: list = []
    if not isinstance(ops, dict):
        return violations                                # a degenerate carrier holds no records to check
    records = ops.get("adoption")
    if not isinstance(records, list):
        return violations                                # no `adoption:` block yet (a virgin carrier — the
                                                         # pre-seed runs AFTER this sweep on the first init)
    by_concern: dict = {}
    for rec in records:
        if isinstance(rec, dict) and rec.get("concern") and str(rec["concern"]) not in by_concern:
            by_concern[str(rec["concern"])] = rec        # first record wins (the upsert keeps one per concern)

    for entry in _load_concern_registry():
        section = entry.get("section")
        if not (isinstance(section, str) and section.strip()):
            continue                                     # a mis-declared registry entry — skip (graph build flags it)
        rec = by_concern.get(section)
        if not rec:
            continue                                     # no record → SPEC-0143 Rule-3 drift's business, not ours
        if _mirror_adoption_status(ops, entry) != "adopt":
            continue                                     # the section is WAIVED or ABSENT — a waive/na record
                                                         # over it is honest, and an `adopt` over it is the
                                                         # REVERSE direction (gated at write time, T-10484)
        label = entry.get("carrier_path") or section     # nested subfields read `deploy.policy` / `deploy.host_config`
        declare_key = entry.get("declare_key") or "the declaration key"
        status = str(rec.get("status") or "")
        owner = str(rec.get("owner") or "")
        exits = (f"Two honest exits: (a) re-record it to MIRROR the declaration — `init --adopt-concern "
                 f"{section}:adopt:<owner>`; or (b) if the mechanism truly is NOT adopted, WAIVE the section "
                 f"in {CONSUMER_OPS_CONTRACT} (`{label}.waiver: {{reason: <why>}}`, removing its "
                 f"`{declare_key}:`) and record `--adopt-concern {section}:waive:<owner>`.")
        if status != "adopt":
            violations.append(
                f"{label}: the adoption record says `status: {status or '(none)'}` while "
                f"{CONSUMER_OPS_CONTRACT} DECLARES that concern (a non-empty `{declare_key}:`) — the record "
                f"DENIES a mechanism this project actively runs (SPEC-0143 Rule 2: the record MIRRORS the "
                f"declare-or-waive stance). {exits}")
        # NOTE (variant A, owner-approved 2026-07-13): a still-`owner: init` record with status `adopt`
        # over a DECLARED section is truthful-but-unratified DEBT — surfaced by the SPEC-0119 report
        # view (fu_4a0e0f4c5f05), deliberately NOT an error arm here.
    return violations


def _expired_waiver_paths(obj, today, path: str = "") -> list:
    """Recursively walk a parsed ops carrier and return the dotted PATHs whose `expiry:` is a real ISO
    date STRICTLY IN THE PAST relative to `today` (a `datetime.date`) — the waiver-CURRENCY half of the
    concern-conformance view (SPEC-0119 rule 8). This is the currency complement to the init sweep's
    SHAPE check (`_ops_waiver_errors` verifies a strict waiver's expiry is a real ISO date, NEVER whether
    it has passed — `_is_iso_date` is explicit that future-vs-past is a report-only concern). Catches both
    a strict `waiver.expiry:` and an `accepted_risks[i].expiry:` that has lapsed. Order-stable, de-duped."""
    import datetime
    out: list = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            child = f"{path}.{k}" if path else str(k)
            if k == "expiry" and _is_iso_date(v):
                d = v if isinstance(v, datetime.date) else datetime.date.fromisoformat(str(v).strip())
                if d < today:
                    out.append(path or "expiry")
            else:
                out.extend(_expired_waiver_paths(v, today, child))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_expired_waiver_paths(v, today, f"{path}[{i}]"))
    seen: set = set()
    return [p for p in out if not (p in seen or seen.add(p))]


def _born_comment_anchors() -> dict:
    """The kernel's CONTRACT-COMMENT ANCHORS, per carrier section — derived from the born template
    (T-10536 / X-0401). Returns {section: [rule-citation, …]} for every born top-level section whose
    COMMENT lines cite a governing rule (`SPEC-0093 rule 12`, `SPEC-0152 rule 16`, …); a section whose
    born comments carry no citation contributes no anchors.

    WHY THESE ARE THE ANCHORS. `yitc-ops.yaml` is a kernel-shaped carrier whose contract is delivered
    largely THROUGH its comments — the declare-or-waive rules, the per-section semantics, the view-XOR-
    sweep rule are all comment text, not schema. The rule-citations inside those comments are the
    "which kernel rule governs this section" pointers: the load-bearing, machine-checkable residue of
    that contract. Their absence is the signal that the contract text is gone.

    Single-SoT: the born template (`_born_ops_template`) — the same schema source `_ops_born_sections` /
    `_update_ops_carrier` already treat as authoritative. NEVER a hand-maintained anchor list, which
    would rot the moment a born comment is re-worded.

    ATTRIBUTION — a citation belongs to the section it DOCUMENTS, not to the nearest preceding column-0
    line (T-10911 / X-0720). A born section may ship COMMENTED OUT — `startup_checks` is: it is OPT-IN,
    so the template carries it as a commented-out example block rather than a live section. Reading only
    live `name:` headers left that block's `SPEC-0152 rule 17` citation credited to whichever section was
    still open above it (`coverage`), and a consumer that legitimately DECLARED `startup_checks` with the
    rule cited in its OWN bounds was still reported `coverage: SPEC-0152 rule 17` missing — a geometric
    false positive on a section it had done nothing to (hit by aiseller AND kupiclub). So a commented-out
    column-0 section header opens its own attribution scope too.

    The commented-header shape is deliberately TIGHT — `# <name>:` with NOTHING after the colon. Do not
    loosen it: the template's commented-out blocks also contain indented mapping lines (`#     command:
    "…"`) and its prose header block contains `# <name>: SECTION (…)` / `# sections: ABSENT = …`. All of
    those carry text after the colon, and a looser pattern would let prose or a nested key silently open a
    bogus section and steal the following citations — the very failure this arm exists to end."""
    import re
    anchors: dict = {}
    section = None
    for line in _born_ops_template().splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):", line)
        if m:
            section = m.group(1)
            continue
        cm = re.match(r"^#\s?([A-Za-z_][\w-]*):\s*$", line)
        if cm:
            section = cm.group(1)      # a COMMENTED-OUT born section opens its own scope (see ATTRIBUTION)
            continue
        if section and line.lstrip().startswith("#"):
            for cite in re.findall(r"SPEC-\d{4}\s+rule\s+\d+", line):
                anchors.setdefault(section, set()).add(cite)
    return {sec: sorted(cites) for sec, cites in anchors.items()}


def _carrier_comment_contract_verdict(text: str) -> dict:
    """REPORT-ONLY: the kernel contract-comment anchors MISSING from one consumer's carrier TEXT, AND
    which of the two DIFFERENT defects the gap is (T-10536 / X-0401; discriminator + re-home naming
    added by T-10568 / X-0423). Returns `{"gaps", "kind", "rehome"}`:

      - `gaps`: ordered `"<section>: <anchor>"` strings; [] = the contract is intact.
      - `kind`: `intact` (no gaps) | `full-strip` | `partial` — see THE DISCRIMINATOR below.
      - `rehome`: ordered `"<section>: <carrier cite> -> <born cite>"` strings — a gap whose section
        still cites the SAME RULE NUMBER under a DIFFERENT spec, i.e. the named re-home candidate.

    THE INCIDENT. trend-finder's T-0141 edited its carrier with a `yaml.safe_load` -> `yaml.dump`
    round-trip, which silently destroyed all 436 comment lines — i.e. the kernel contract delivered
    through them — and nothing kernel-side noticed. They caught it only by luck (a self-test that
    happened to break). This is the check that would have noticed.

    Reads the RAW TEXT on purpose: comments do not survive a YAML parse, so a parsed-carrier check is
    structurally blind to this defect — the very reason the class went undetected.

    THE DISCRIMINATOR (T-10568). A missing anchor has TWO causes with OPPOSITE remedies, and the
    detector must not conflate them: X-0401 is a whole-file round-trip that strips EVERY section's
    comments at once (remedy: restore the born template's comment text), whereas a kernel spec SPLIT
    re-homes a rule to a new spec while the consumer's comments stay fully INTACT (remedy: reconcile
    ONE citation — restoring the template there would DESTROY the consumer's own prose). So:
    `full-strip` = the checked sections retain NO comment lines at all (the comments are gone, hence
    the anchors); `partial` = comments survive, so the gap is citation drift, not a strip. Read off
    the same raw text already sliced here — no count threshold, and none is wanted: a 1-section
    carrier round-tripped is still a full strip, and boomrocket's T-0203 tripped 3 of 15 anchors with
    every comment intact (a literal restore reading would have cost it ~150 lines of project prose).

    ANTI-FALSE-POSITIVE (both AC requirements): an anchor counts as present if the section's comments
    contain the citation SUBSTRING, so a consumer that RE-WORDS or extends the kernel's prose (or adds
    its own comments) stays silent as long as it keeps the rule pointers; and only sections the consumer
    ACTUALLY HAS are checked, so a carrier that legitimately omits a section is never nagged for it.

    HONEST BOUND (stated, not designed around): two born sections (`product_cron`, `freshness`) ship
    comments carrying no rule-citation, so they contribute no anchors and a gutting confined to JUST
    those two would not trip this signal. Accepted deliberately for a report-only signal: adding a
    second "any comment at all" fallback rule would be a second mechanism for a case the real incident
    does not exhibit (CHARTER §P1). The X-0401 shape — a whole-file round-trip — strips every section's
    comments at once and trips 9+ anchors.

    SECOND HONEST BOUND: `rehome` is a CANDIDATE, not a verdict — a same-numbered cite under another
    spec is strong evidence of a re-home but the operator confirms it against `graph/born-ops.yaml`.
    A `partial` gap with no candidate still reports as partial (the split-aware text says compare by
    hand); guessing a remedy there would be the very over-claim this task exists to remove."""
    import re
    anchors = _born_comment_anchors()
    if not text or not anchors:
        return {"gaps": [], "kind": "intact", "rehome": []}
    # slice the carrier text into its column-0 sections (the same section geometry the append family uses)
    lines = text.splitlines()
    bounds: dict = {}
    cur = None
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z_][\w-]*):", line)
        if m:
            if cur:
                bounds[cur][1] = i
            cur = m.group(1)
            bounds[cur] = [i, len(lines)]
    gaps: list = []
    rehome: list = []
    any_comment = False          # ← the discriminator: did ANY checked section keep its comments?
    for section in sorted(anchors):
        if section not in bounds:
            continue                                     # the consumer does not carry this section — not a gap
        start, end = bounds[section]
        comments = "\n".join(ln for ln in lines[start:end] if ln.lstrip().startswith("#"))
        if comments.strip():
            any_comment = True
        for anchor in anchors[section]:
            if anchor in comments:
                continue
            gaps.append(f"{section}: {anchor}")
            # RE-HOME CANDIDATE: the born anchor is `SPEC-A rule N`; if this section's surviving
            # comments cite `SPEC-B rule N` — same rule NUMBER, different spec home — that is the
            # split (SPEC-0152 re-homing rules out of SPEC-0093 is the real case), so NAME it.
            am = re.match(r"^(SPEC-\d{4})\s+rule\s+(\d+)$", anchor)
            if not am:
                continue
            for other in re.findall(rf"SPEC-\d{{4}}\s+rule\s+{am.group(2)}\b", comments):
                if not other.startswith(am.group(1)):
                    rehome.append(f"{section}: {other} -> {anchor}")
    if not gaps:
        return {"gaps": [], "kind": "intact", "rehome": []}
    return {"gaps": gaps, "kind": "partial" if any_comment else "full-strip", "rehome": rehome}


def _carrier_comment_contract_gaps(text: str) -> list:
    """The `gaps` arm of `_carrier_comment_contract_verdict` — ordered `"<section>: <anchor>"` strings;
    [] = intact. Kept as its own name because callers (and the T-10536 tests) that only ask "is the
    contract intact?" should not have to know about the T-10568 discriminator."""
    return _carrier_comment_contract_verdict(text)["gaps"]


def concern_conformance(ops_path, *, today=None) -> dict:
    """REPORT-ONLY concern-conformance view (SPEC-0119 rule 8 / SPEC-0128 Rule 2) — the standing
    declare-or-waive STANCE + waiver-CURRENCY signal derived from the kernel concern registry, for ONE
    repo's ops carrier at `ops_path`. Read-only, NEVER raises, NEVER gates (the debt-echo + nightly
    contract). Returns `{"status", "count", "stance_issues", "expired_waivers"}`:

      - `status`: `no-carrier` (no yitc-ops.yaml — e.g. the engine kernel itself; count 0 → suppressed),
        `unreadable` (present but absent/malformed mapping; count 0 → NOT nagged, the SPEC-0093 init
        sweep owns malformed-carrier errors), or `checked`.
      - `count`: len(stance_issues) + len(expired_waivers) — 0 ⇒ CLEAN ⇒ the caller suppresses the line.
      - `stance_issues`: the pure `_ops_carrier_violations` verdict (unanswered / contradictory / wrong-typed
        stances — the SAME source the init sweep fails closed on, so the standing view and the init gate can
        never disagree, CHARTER §P5).
      - `expired_waivers`: dotted carrier paths whose `expiry:` has lapsed (waiver-currency, `_expired_waiver_paths`).
      - `comment_contract`: the kernel CONTRACT-COMMENT anchors missing from the carrier (T-10536 /
        X-0401 — `_carrier_comment_contract_gaps`). Derived from the carrier's raw TEXT, because comments
        do not survive a YAML parse: a parsed-only view is structurally blind to the very defect (a
        `yaml.dump` round-trip gutting all 436 comment lines) that this signal exists to catch.
      - `comment_contract_kind` / `comment_contract_rehome`: WHICH defect that gap is (`intact` |
        `full-strip` | `partial`) and the named re-home candidate(s) — the T-10568 discriminator, so the
        debt line can prescribe the remedy that MATCHES the cause instead of one hardcoded restore. Own
        sibling keys, not folded into `comment_contract`: that arm's meaning (the missing anchors) is
        already keyed on, and a kind is not an anchor.

    THIS SIGNAL IS REPORT-ONLY BY CONSTRUCTION — it is added HERE (the standing view) and deliberately NOT
    to `_ops_carrier_violations`, which is what `_sweep_ops_carrier` FAILS CLOSED on at init. A comment gap
    must never REFUSE a consumer's init: that would fail-close every consumer that ever re-worded a comment,
    turning a debt nudge into an outage. The card's "extend the existing conformance surface, report-only,
    no new gate class" is exactly this placement.

    IT IS ALSO ITS OWN ARM, NOT PART OF `count` (T-10536, caught by the T-10030 tests). `count` has an
    ESTABLISHED meaning — the DECLARE-OR-WAIVE issue count — and callers key on it (the nightly's alert
    arm, the debt echo's line). Folding a third, unrelated signal into it silently redefined "a
    stance-conformant carrier is clean" for every existing caller: a comment-less carrier began reading as
    stance-unclean. So `count` keeps its meaning (stance + expired), and the comment gap is surfaced as a
    SEPARATE list with its own debt line and its own nightly alert arm. Callers read the signal they mean.

    `today` (a `datetime.date`) is injectable for tests; the default is the real UTC date."""
    import datetime

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)

    if today is None:
        today = datetime.datetime.now(datetime.timezone.utc).date()

    def _empty(status: str) -> dict:
        return {"status": status, "count": 0, "stance_issues": [], "expired_waivers": [],
                "comment_contract": [], "comment_contract_kind": "intact", "comment_contract_rehome": []}

    try:
        ops = state.load_ops(ops_path) if ops_path.exists() else None
    except Exception:  # noqa: BLE001 — a report-only surface must never nag on a parse failure
        return _empty("unreadable")
    if ops is None:
        return _empty("no-carrier")
    if not isinstance(ops, dict):
        return _empty("unreadable")

    stance_issues = _ops_carrier_violations(ops)
    expired = _expired_waiver_paths(ops, today)
    try:                                        # best-effort — a report-only surface never raises
        verdict = _carrier_comment_contract_verdict(ops_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        verdict = {"gaps": [], "kind": "intact", "rehome": []}
    return {"status": "checked",
            "count": len(stance_issues) + len(expired),   # the declare-or-waive count — meaning unchanged
            "stance_issues": stance_issues, "expired_waivers": expired,
            "comment_contract": verdict["gaps"],          # its own arm (see the docstring)
            "comment_contract_kind": verdict["kind"],     # …and WHICH defect it is (T-10568)
            "comment_contract_rehome": verdict["rehome"]}


def concern_drift(ops_path) -> dict:
    """REPORT-ONLY per-concern DRIFT view (SPEC-0143 Rule 3, T-10172) — the sibling of
    `concern_conformance`: it compares the consumer's PER-CONCERN adopted version (the SPEC-0093 /
    SPEC-0143-Rule-2 `adoption:` block, written by card B / T-10171) against the KERNEL-derived registry
    `version` (card A / T-10170) and surfaces every concern that has MOVED under the consumer. Read-only,
    NEVER raises, NEVER gates (the session-start / nightly report-only contract). Returns
    `{"status", "count", "drifts"}`:

      - `status`: `no-carrier` (no yitc-ops.yaml — e.g. the engine kernel itself; count 0 → suppressed),
        `unreadable` (present but malformed mapping; count 0 → NOT nagged, the SPEC-0093 init sweep owns
        malformed-carrier errors), or `checked`.
      - `count`: len(drifts) — 0 ⇒ CLEAN ⇒ the caller suppresses the line (SPEC-0119 debt-echo posture).
      - `drifts`: per drifting concern, `{concern, adopted, current, reason}` — `reason` is `un-adopted`
        (no adoption entry for a registry concern) or `behind` (an entry recorded against a stale version).

    PRECISION (SPEC-0143 binding, plan-check finding 2): the 'no line' is PER-CONCERN and holds ONLY when
    a CURRENT adopt/waive/na record exists (adopted.version == registry.version). A concern with NO entry
    is drift (`un-adopted`) — so a LEGACY consumer with no `adoption:` block surfaces ALL concerns once
    (bootstrap review, correct-not-a-bug). Version equality is the sole test regardless of status: a
    waive/na recorded against a moved contract is still drift (the waiver decision must be re-made)."""
    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (concern_conformance precedent)

    # version-by-section from the KERNEL-derived concern registry (card A / T-10170 added the `version`).
    versions = {c.get("section"): str(c.get("version")) for c in _load_concern_registry()
                if isinstance(c, dict) and c.get("section") and c.get("version")}
    try:
        ops = state.load_ops(ops_path) if ops_path.exists() else None
    except Exception:  # noqa: BLE001 — a report-only surface must never nag on a parse failure
        return {"status": "unreadable", "count": 0, "drifts": []}
    if ops is None:
        return {"status": "no-carrier", "count": 0, "drifts": []}
    if not isinstance(ops, dict):
        return {"status": "unreadable", "count": 0, "drifts": []}

    adopted: dict = {}
    if isinstance(ops.get("adoption"), list):
        for e in ops["adoption"]:
            if isinstance(e, dict) and e.get("concern"):
                adopted[str(e.get("concern"))] = e
    drifts: list = []
    for section in sorted(versions):
        current = versions[section]
        entry = adopted.get(section)
        if entry is None:
            drifts.append({"concern": section, "adopted": None, "current": current, "reason": "un-adopted"})
        elif str(entry.get("version")) != current:
            drifts.append({"concern": section, "adopted": str(entry.get("version")),
                           "current": current, "reason": "behind"})
    return {"status": "checked", "count": len(drifts), "drifts": drifts}


def unratified_adoptions(ops_path) -> dict:
    """REPORT-ONLY UNRATIFIED-ADOPTION view (SPEC-0119 rule 13, T-10508) — the third sibling of
    `concern_conformance` / `concern_drift`, and the RESIDUAL half of the T-10493 stance cross-check.
    Read-only, NEVER raises, NEVER gates (the debt-echo / nightly report-only contract). Returns
    `{"status", "count", "records"}`:

      - `status`: `no-carrier` (no yitc-ops.yaml — e.g. the engine kernel itself; count 0 → suppressed),
        `unreadable` (present but malformed mapping; count 0 → NOT nagged — the SPEC-0093 init sweep owns
        malformed-carrier errors), or `checked`.
      - `count`: len(records) — 0 ⇒ CLEAN ⇒ the caller suppresses the line.
      - `records`: per unratified concern, `{concern, status, owner, at}` — registry-walk ordered.

    THE RESIDUAL THIS PAYS (variant A, owner-approved 2026-07-13). `_adoption_stance_violations` blocks
    exactly ONE arm — a `waive`/`na` record over a section the carrier DECLARES (the record DENIES a live
    mechanism). The sibling case — a record reading `status: adopt` while still stamped with the BIRTH
    SENTINEL `owner: init` — is TRUTHFUL (the mechanism really is declared) but UNRATIFIED: the bootstrap
    ACT wrote it, no human ever reviewed it. Blocking that would fail-close consumers whose records are
    true, so variant A left it as DEBT with an explicit promise of this report-only line (the NOTE in
    `_adoption_stance_violations`; fu_4a0e0f4c5f05). Without this view the residual is INVISIBLE: the
    init sweep passes it by design and `concern_conformance` judges SECTIONS + waiver currency, never a
    record's OWNER.

    THE TRIGGER IS ENUMERATED, NEVER PROSE (`lessons/report-only-advisory-never-exempts-a-contradiction`
    rule 1). A concern counts iff ALL THREE hold:
      (i)   the carrier's stance for the section is `adopt` — resolved through the EXISTING
            `_mirror_adoption_status`, the SAME one stance reader the birth pre-seed, the T-10484 write
            gate and `_adoption_stance_violations` use (ONE stance home — CHARTER §P5). That reuse is
            load-bearing, not tidiness: it inherits `_ops_declared`'s rule that an EMPTY opt-in
            declare-key is NOT a declaration, the exact test the T-10415 hand-check got wrong by
            re-deriving it.
      (ii)  its `adoption:` record reads `status: adopt` — a NON-adopt record over a declared section is
            `_adoption_stance_violations`' BLOCKING arm, and must never be double-reported as debt here.
      (iii) that record's `owner` is the birth sentinel `_ADOPTION_INIT_SENTINEL` — the ONE carrier for
            "nobody reviewed this" (the pre-seed writes it, that sweep refuses it over a declared
            section, this view reports it). A record under ANY named owner is RATIFIED and contributes
            nothing — which is precisely the differential: re-record under a human owner and the row
            disappears.

    TWO NARROW EXCLUSIONS, each because the declaration records NO human answer to ratify — so counting
    it would leave an un-actionable row in every consumer's view forever:
      (iv)  `_themes_are_wholly_kernel_owned` (T-12053) — the section is declared, but the KERNEL
            declared it (the mandatory baseline `inspection` theme, no opt-out).
      (v)   `_section_values_are_wholly_kernel_rendered` (T-12165) — every value in the section is a
            DERIVED value `init` RENDERED (`security.audit.profile_snapshot.command`, the route to the
            one profile derivation site). SPEC-0198's doctrine is that a derived value is never asked
            as a question, so the section is ratified BY CONSTRUCTION. Narrow by derivation, never by a
            hand list: the born fragment is the reference, and a project value of its own restores the
            row (see the predicate's own docstring for the exact bound).
    Both are BOUNDED the same way — they exclude a section nobody was asked about, never a section
    somebody was asked about and did not answer.

    The unit is the CONCERN, not the carrier (`lessons/scope-the-trigger-not-the-view`): a ratified
    sibling can never clear an unratified row. `at`/`owner` are surfaced for the render, not judged —
    an ABSENT record is the SPEC-0143 Rule-3 drift reconcile's business (`concern_drift`), not ours.
    This view WRITES NOTHING and auto-ratifies nothing: ratification is the owner's act by construction
    (`lessons/a-stance-mirror-is-only-sound-at-birth` — a mirror stamped AFTER birth asserts an answer
    nobody gave, which is the very failure the sentinel exists to keep legible)."""
    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (concern_drift precedent)

    try:
        ops = state.load_ops(ops_path) if ops_path.exists() else None
    except Exception:  # noqa: BLE001 — a report-only surface must never nag on a parse failure
        return {"status": "unreadable", "count": 0, "records": []}
    if ops is None:
        return {"status": "no-carrier", "count": 0, "records": []}
    if not isinstance(ops, dict):
        return {"status": "unreadable", "count": 0, "records": []}

    by_concern: dict = {}
    for rec in (ops.get("adoption") if isinstance(ops.get("adoption"), list) else []):
        if isinstance(rec, dict) and rec.get("concern") and str(rec["concern"]) not in by_concern:
            by_concern[str(rec["concern"])] = rec    # first record wins (the upsert keeps one per concern
                                                     # — the `_adoption_stance_violations` index idiom)
    records: list = []
    for entry in _load_concern_registry():
        section = entry.get("section")
        if not (isinstance(section, str) and section.strip()):
            continue                                 # a mis-declared registry entry — skip (graph build flags it)
        rec = by_concern.get(section)
        if not rec:
            continue                                 # no record → `concern_drift`'s un-adopted business
        if _mirror_adoption_status(ops, entry) != "adopt":
            continue                                 # (i) the section is WAIVED or ABSENT — a record over it
                                                     # is honest in this direction; nothing to ratify
        if str(rec.get("status") or "") != "adopt":
            continue                                 # (ii) the T-10493 BLOCKING arm owns this row
        if str(rec.get("owner") or "") != _ADOPTION_INIT_SENTINEL:
            continue                                 # (iii) a NAMED owner ratified it — clean
        if _themes_are_wholly_kernel_owned(section, ops.get(section)):
            continue                                 # (iv) T-12053 — the section is declared, but the
                                                     # KERNEL declared it (the mandatory baseline theme,
                                                     # no opt-out): there is no project decision to
                                                     # ratify, so this is not owner debt. A project theme
                                                     # of its own makes the row appear normally.
        carrier_path = entry.get("carrier_path") or section
        cp_present, cp_val = ((False, None) if not isinstance(carrier_path, str)
                              else _ops_navigate(ops, carrier_path))
        if cp_present and _section_values_are_wholly_kernel_rendered(carrier_path, cp_val, ops_path.parent):
            continue                                 # (v) T-12165 — the section is declared, but every
                                                     # value in it is a value the KERNEL RENDERED at
                                                     # init (a derived route, not a stance): there is
                                                     # no answer here anybody gave, so nothing to
                                                     # ratify. A project value of its own makes the row
                                                     # appear normally.
        records.append({"concern": section, "status": "adopt",
                        "owner": _ADOPTION_INIT_SENTINEL, "at": rec.get("at")})
    return {"status": "checked", "count": len(records), "records": records}


def _ops_born_sections() -> dict:
    """Split the born carrier (the GENERATED graph/born-ops.yaml, T-10038) into {top_level_section_name:
    text_block}. The SINGLE source for each section's born text (P5 — no parallel section catalog: the
    update/merge below DERIVES its fragments from the SAME generated template). A section begins at a
    column-0 `<name>:` line and runs until the next such line (its indented comments/values belong to it);
    the leading all-`#` header block before the first section is NOT a section, and a COMMENTED opt-in
    section (a `# <name>:` example, e.g. startup_checks) is NOT a live section here (see
    `_ops_born_commented_sections`). Order-preserving (insertion = file order)."""
    import re
    blocks: dict = {}
    name = None
    buf: list = []
    for line in _born_ops_template().splitlines(keepends=True):
        m = re.match(r"^([A-Za-z_][\w-]*):", line)
        if m and not line[:1].isspace():            # a column-0 `<name>:` starts a new top-level section
            if name is not None:
                blocks[name] = "".join(buf)
            name = m.group(1)
            buf = [line]
        elif name is not None:                       # indented / comment line inside the current section
            buf.append(line)
    if name is not None:
        blocks[name] = "".join(buf)
    return blocks


# T-11366 — the born template's DECLARATION-GATED-CAPABILITY marker, the twin of `_GATED_CAP_MARKER`
# in bin/lib/graph.py (init.py back-imports NOTHING by design — the same cross-module-literal shape as
# `BORN_OPS_TERMINATOR` / `BORN_WAIVER_MARKER`, pinned the same way by a coherence probe).
GATED_CAP_MARKER = "# ── declaration-gated capabilities (generated from the concern registry) ──"


def _ops_born_disclosures() -> dict:
    """{top_level_section: disclosure_stanza_text} sliced out of the born template (T-11366).

    The stanza is the GENERATED declaration-gated-capability block `graph build` renders from a concern's
    `gated_capabilities:` — it names the OPT-IN keys that section gates a kernel capability on. It is
    always the TAIL of its section's born block, so the slice is «from the marker line to the end of the
    section». Read from `_born_ops_template()` — the SAME single source `_ops_born_sections()` and
    `_born_comment_anchors()` already treat as authoritative — so a NEW capability is delivered by
    declaring it on its concern, with no edit here (SPEC-0128 Rule 3). NEVER a hand list.

    A section with no marker contributes nothing; only column-0 sections are considered (a commented
    opt-in example block is not a delivery target — there is no section in the consumer's carrier to
    inject into)."""
    out: dict = {}
    for name, blockt in _ops_born_sections().items():
        lines = blockt.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.strip() == GATED_CAP_MARKER:
                out[name] = "".join(lines[i:])
                break
    return out


def _inject_section_disclosure(text: str, section: str, stanza: str) -> "str | None":
    """Insert the declaration-gated-capability `stanza` at the END of an EXISTING `section:` block in a
    consumer's carrier TEXT (T-11366) — the AC3 delivery: an already-init'd project receives the
    disclosure through the ordinary idempotent update path.

    WHY THIS ARM EXISTS AT ALL. `_update_ops_carrier` keys on SECTION PRESENCE: it appends a born section
    only to a carrier that LACKS it. A disclosure living inside the `verify:` born block would therefore
    reach every FUTURE project and NO existing one — precisely the projects that have been running the
    capability off by ignorance. So the disclosure is delivered per-SECTION, not per-section-arrival.

    NON-DESTRUCTIVE BY CONSTRUCTION, not by care: the stanza is entirely `#` comment lines, so no declared
    value can change and no answered stance can be overwritten — the strongest form of the update path's
    existing promise. Idempotent on the MARKER: a section already carrying it is skipped, so a re-run is a
    byte-identical no-op. Returns the new text, or None when the section is absent or already disclosed.
    Same section-boundary logic (and the same insert-before-the-next-column-0-line placement) as
    `_inject_nested_subfield`."""
    import re
    lines = text.splitlines(keepends=True)
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z_][\w-]*):", line)
        if m and not line[:1].isspace():
            if m.group(1) == section:
                start = i
            elif start is not None:
                end = i
                break
    if start is None:
        return None                                   # the consumer does not carry this section
    if any(ln.strip() == GATED_CAP_MARKER for ln in lines[start:end]):
        return None                                   # already disclosed — idempotent no-op
    head = "".join(lines[:end])
    sep = "" if (not head) or head.endswith("\n") else "\n"
    return head + sep + stanza + "".join(lines[end:])


def _ops_born_commented_sections() -> set:
    """The COMMENTED opt-in section names in the born template (T-10038) — a top-level `# <name>:` example
    block (the section key commented, NOTHING after the colon: `^#\\s*<name>:\\s*$`). Currently just
    `startup_checks`, born as a commented example (OPT-IN: absent-by-default, never fail-closed). This is
    DISTINCT from a header SUMMARY line (`# startup_checks: SECTION (SPEC-0093 …)` — text after the colon,
    so it does NOT match). The registry↔surface consistency check unions this with `_ops_born_sections()`
    so a registered opt-in concern whose born is a commented example (startup_checks) is NOT falsely flagged
    `concern-surface-inconsistency` — it DOES have a born surface, just a commented one."""
    import re
    out: set = set()
    for line in _born_ops_template().splitlines():
        m = re.match(r"^#\s*([A-Za-z_][\w-]*):\s*$", line)
        if m:
            out.add(m.group(1))
    return out


def _registry_mandatory_top_level() -> dict:
    """{section: declare_key} for every `presence_policy: mandatory` concern whose `carrier_path` is
    TOP-LEVEL (not dotted) — the set the T-10982 carrier-BACKFILL mode can deliver. Registry-derived
    (SPEC-0128 Rule 2 — the same concern-registry that drives the sweep and `_registry_mandatory_sections`),
    NO hand list, so a concern that BECOMES mandatory is backfillable with no code edit. A DOTTED
    mandatory concern is deliberately out of the backfill's scope: its parent block is the delivery site
    and the nested rule-11 injection already owns that seam — a missing one stays the ordinary sweep's
    fail-closed ERROR, which is honest, not a silent pass. Returned as a LOOKUP, not an order: the
    delivery iterates the BORN template order (as `_update_ops_carrier` does), so backfilled sections
    read in the same order a fresh consumer's carrier does."""
    return {e.get("section"): e.get("declare_key") for e in _load_concern_registry()
            if e.get("presence_policy") == "mandatory"
            and isinstance(e.get("section"), str)
            and isinstance(e.get("carrier_path"), str) and "." not in e.get("carrier_path")}


def _registry_nested_concerns() -> list:
    """The registry concerns whose `carrier_path` is DOTTED (a nested born SUBFIELD of a top-level
    section — `deploy.policy` / `deploy.host_config` at depth 2, `security.audit.profile_snapshot` at
    depth 3; the depth is NOT bounded, T-12165). Registry-derived (SPEC-0128 Rule 2 —
    the same concern-registry that drives the sweep/mandatory set), NO hand list. Order-preserving
    (registry order). Used by `_consumer_carrier_skew` / `_update_ops_carrier` to deliver a missing
    born nested subfield into an EXISTING consumer carrier (T-10031, closing the T-9439 gap)."""
    return [e.get("carrier_path") for e in _load_concern_registry()
            if isinstance(e.get("carrier_path"), str) and "." in e.get("carrier_path")]


def _ops_split_subfields_at(block: str, indent: int) -> dict:
    """Split a born block into the `<name>:` subfields sitting at EXACTLY `indent` spaces →
    {leaf_name: text_block}. A subfield begins at an exactly-`indent`-space `<name>:` line and runs
    until the next such line (its deeper-indented values/comments belong to it); the block's own
    HEADER line (line 0) is skipped, since it is the parent whose children these are.
    Order-preserving. Empty dict for a leaf-only block.

    THE ONE SPLITTER CONTRACT (CHARTER §P5). `_ops_born_sections` splits at column 0, this splits at
    any deeper indent, and `_ops_born_nested_fragment` / `_unanswered_mandatory_block` both defer to
    it rather than re-spelling the rule."""
    import re
    subs: dict = {}
    name = None
    buf: list = []
    pat = re.compile(r"^ {%d}([A-Za-z_][\w-]*):" % indent)
    for line in block.splitlines(keepends=True)[1:]:      # skip the parent's own header line
        m = pat.match(line)
        if m and line[indent:indent + 1] != " ":          # exactly-`indent` spaces starts a new subfield
            if name is not None:
                subs[name] = "".join(buf)
            name = m.group(1)
            buf = [line]
        elif name is not None:
            buf.append(line)
    if name is not None:
        subs[name] = "".join(buf)
    return subs


def _ops_born_nested_subfields(parent_name: str) -> dict:
    """Split a TOP-LEVEL born section's block (`_ops_born_sections()[parent_name]`) into its INDENT-2
    `<name>:` subfields → {leaf_name: text_block}. The depth-1 case of `_ops_split_subfields_at`, kept
    as its own name because that is the depth every caller of the ORIGINAL T-10031 seam wanted. Empty
    dict for an absent/leaf-only parent. The nested-subfield analog of `_ops_born_sections`."""
    block = _ops_born_sections().get(parent_name)
    if not block:
        return {}
    return _ops_split_subfields_at(block, 2)


def _ops_born_nested_fragment(carrier_path: str) -> "str | None":
    """The born TEXT BLOCK for a DOTTED carrier path, at ANY depth (T-12165) — `deploy.policy` (depth
    2) and `security.audit.profile_snapshot` (depth 3) resolve through the identical descent. Returns
    the leaf's verbatim born text (indented at its own carrier depth), or None when any segment of the
    path has no born surface.

    WHY THIS EXISTS AS A GENERALIZATION rather than a second helper (CHARTER §P1 F1/F2): the T-10031
    seam was written for the only nested concerns that existed then, both depth 2, and hard-bound the
    rule to a 2-space split. That was an UNSTATED CEILING, not a decision — a depth-3 concern was
    silently undeliverable: it appeared in no skew report and no init pass, so it would simply never
    reach a consumer. Descending segment by segment removes the ceiling without adding a delivery
    channel; depth 2 walks exactly one iteration and is byte-identical to the former behaviour."""
    parts = carrier_path.split(".")
    block = _ops_born_sections().get(parts[0])
    if not block:
        return None                                       # no top-level born surface → nothing nested
    for depth, leaf in enumerate(parts[1:], start=1):
        block = _ops_split_subfields_at(block, depth * 2).get(leaf)
        if not block:
            return None                                   # a segment with no born surface
    return block


def _consumer_carrier_skew(ops: dict) -> list:
    """READ-ONLY: the ordered born LABELS that a re-init `_update_ops_carrier` WOULD deliver into this
    already-parsed consumer carrier `ops` — the "consumer is behind the kernel schema" set. ONE source
    of truth shared by the WRITER (`_update_ops_carrier`, part a) and the report-only per-consumer
    born-schema-skew self-check (`session.born_skew_check_line`, part b — T-10077), so the two can
    never drift (T-10031 origin; the engine-side registry sweep it originally fed was retired T-10077).

    Two kinds, in this order:
      1. MISSING extensible TOP-LEVEL sections (every born top-level section that is NOT a slice-1
         mandatory one and is absent from `ops`) — the SPEC-0093 rule 11 top-level update set.
      2. MISSING born NESTED subfields (a dotted registry concern, e.g. `deploy.policy` at depth 2 or
         `security.audit.profile_snapshot` at depth 3) whose IMMEDIATE PARENT is PRESENT and A MAPPING
         but whose leaf key is absent (the T-9439 gap). A present-but-NON-mapping parent is NOT a
         deliverable skew (left to the sweep to fail closed — audit-pre finding; `_ops_navigate`
         already requires `isinstance(parent, dict)`). The parent is resolved by `_ops_navigate` at
         ANY depth (T-12165), not by taking the path's first segment.

    Returns [] for a fresh/current carrier (suppressed-when-clean). Pure inspection — never mutates."""
    if not isinstance(ops, dict):
        return []
    mandatory = _registry_mandatory_sections()
    labels: list = []
    for name in _ops_born_sections():
        if name in mandatory:
            continue
        if name not in ops:
            labels.append(name)
    for carrier_path in _registry_nested_concerns():
        parent_path = carrier_path.rsplit(".", 1)[0]       # T-12165: the IMMEDIATE parent at any depth
        parent_present, parent_val = _ops_navigate(ops, parent_path)
        if not (parent_present and isinstance(parent_val, dict)):
            continue                                       # parent absent OR non-mapping → not deliverable here
        present, _ = _ops_navigate(ops, carrier_path)
        if not present and _ops_born_nested_fragment(carrier_path):
            labels.append(carrier_path)
    return labels


def _update_ops_carrier(ops_path, write_text_atomic, cli_form: str = "bin/yitc-v2",
                        disclosed_out: "list | None" = None, *,
                        born_permissive_confirmations: "dict | None" = None,
                        withheld_out: "list | None" = None) -> list:
    """SPEC-0093 rule 11 (T-9375) — the UPDATE path: deliver any MISSING extensible top-level section into
    an EXISTING consumer carrier, born declare-or-waive, NON-DESTRUCTIVELY. This is how a consumer init'd
    BEFORE a section was added to the kernel schema later RECEIVES it (rule 4's extensibility, realized for
    existing consumers) — re-running `init` IS the update.

    SCOPE = the post-slice-1 EXTENSIBLE concern sections ONLY: every born top-level section that is NOT one
    of the slice-1 MANDATORY three (the registry `presence_policy: mandatory` set = deploy/rollback/live_probe). The slice-1
    three are NEVER auto-added — a missing one stays the sweep's fail-closed ERROR (rule 3), not silently
    re-seeded (T-9389 b/c).

    NESTED born SUBFIELDS (T-10031, closing the T-9439 gap): after the top-level pass, ALSO deliver a
    MISSING born nested subfield (a DOTTED registry concern, e.g. `deploy.policy` / `deploy.host_config`)
    whose PARENT section is PRESENT and a MAPPING but whose leaf key is absent — TEXT-injected at the end
    of the parent's block, non-destructively (a present-but-non-mapping parent is left to the sweep to
    fail closed). Scope is the ORIGINAL carrier's present-parent set: a top-level section PULLED this same
    run already carries its born nested subfields, so it is not re-injected. What is missing is computed
    ONCE by the shared `_consumer_carrier_skew` (same set the debt SKEW view reports). A candidate that
    would break the YAML is aborted (the nested injection is dropped, top-level delivery stands).

    Appends each missing section's born fragment as TEXT (not a yaml round-trip) so the consumer's
    hand-written declarations / comments / formatting are preserved verbatim. Keys on section PRESENCE: a
    section key already in the carrier is SKIPPED — an unanswered-but-present section is left for the sweep
    to fail-closed, and a declared/waived value is NEVER overwritten. Returns the section names pulled
    (empty for a fresh/current carrier → re-run stays a no-op / byte-identical). The optional
    `disclosed_out` out-parameter collects the sections that received a declaration-gated capability
    STANZA (T-11366) — a separate channel because a disclosure is not a section PULL and the return value
    is read as one (`"extensions" in ops_sections_pulled` decides `fresh_carrier`), so widening it would
    change an unrelated decision.

    THE SPEC-0189 RULE-8 GATE RUNS HERE TOO (T-12001, the second half of T-11985). This is the SECOND
    born-declaration write path: the first is the fresh-birth body `cmd_init` gates, and this one appends
    born fragments into an EXISTING consumer's carrier. Rule 8's consequence — «there is no state in which
    a relaxation exists un-ratified» — is a property of the SYSTEM, not of one call site, so the same
    `born_permissive_gate` runs over the `appended` text before it is written: a section whose relaxing
    declaration is UNCONFIRMED is neither appended nor reported PULLED, and is reported through
    `withheld_out` so the caller prints the SAME hint the birth path prints (one hint text,
    `_born_permissive_withheld_hint` — CHARTER §P5). `born_permissive_confirmations=None` means the same
    as `{}` — nothing confirmed, therefore nothing written; the default is FAIL-CLOSED, never a
    no-gate escape, because a caller that forgets the argument must get the PROTECTED outcome.

    THIS ALSO CLOSES THE BIRTH PATH'S OWN BACK DOOR, which is not obvious and is the reason the gate
    cannot live in `cmd_init` alone: at a FRESH birth the gate withholds the section from the body, so the
    just-written carrier LACKS it — and this function, running a few lines later on that same carrier, saw
    an "extensible section the consumer's carrier lacks" and re-appended it verbatim. Gating here is what
    makes the withhold hold.

    CONCERN-BLIND, and NOT NARROWED. Nothing here reads a concern's name, key or meaning — the section set
    is `born_permissive_gate`'s own registry stance walk. Delivery of every OTHER missing section,
    protective ones included, is byte-for-byte unchanged: rule 11 is gated, not narrowed. `_sweep_ops_carrier`
    still pulls the withheld concern's DOCUMENTATION stub afterwards; what is withheld is the DECLARATION
    (the same F-1/F-4 asymmetry the birth path documents). Self-contained (inline
    yaml + write_text_atomic passed by cmd_init) so cmd_init's injected-deps contract stays unchanged
    (see the module header)."""
    import yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)
    if not ops_path.exists():
        return []                                    # nothing to update — fresh seed is the scaffold loop's job
    text = ops_path.read_text(encoding="utf-8")
    try:
        ops = state.load_ops_str(text)
    except yaml.YAMLError:
        return []                                    # malformed (incl. a duplicate top-level key, T-10240) — the
                                                     # sweep fails-closed; don't append to a carrier we can't trust
    if not isinstance(ops, dict):
        return []
    mandatory = _registry_mandatory_sections()   # SPEC-0128 Rule 2 — registry-derived (retired the hand-maintained triple)
    pulled: list = []
    appended = ""
    for name, fragment in _ops_born_sections().items():
        if name in mandatory:
            continue                                 # slice-1 mandatory — never auto-added (fail-closed if missing)
        if name not in ops:                          # an EXTENSIBLE section the consumer's carrier lacks
            appended += fragment
            pulled.append(name)
    if appended:
        # SPEC-0189 rule 8 (T-12001) — gate the born-permissive DECLARATIONS out of what this path
        # WRITES, through the same function the birth path calls, over the same kind of text. A
        # withheld section leaves `appended` AND leaves `pulled`: it was not delivered, so reporting it
        # pulled would be a false receipt that the sweep and the debt views read.
        appended, _bp_update_written, _bp_update_withheld = born_permissive_gate(
            appended, born_permissive_confirmations)
        for _section in _bp_update_withheld:
            if _section in pulled:
                pulled.remove(_section)
                if withheld_out is not None:
                    withheld_out.append(_section)   # REPORTED, never silent (the caller prints the hint)

    new_text = text
    if appended:
        # Render the `__YITC_CLI__` token in any pulled section (e.g. the extensions comments) to the
        # actual verb-invocation form (T-9769) — a consumer has NO local bin/yitc-v2.
        sep = "" if (not new_text) or new_text.endswith("\n") else "\n"
        new_text = new_text + sep + appended.replace("__YITC_CLI__", cli_form)

    # NESTED born subfields (T-10031, closing T-9439) — deliver each DOTTED registry concern the shared
    # skew detector flags as missing (present-mapping parent, absent leaf) into the ORIGINAL carrier's
    # parent block. A top-level section pulled just above already carries its born subfields, so scoping
    # on the ORIGINAL `ops` (not the appended text) is what prevents a double-inject.
    nested_pulled: list = []
    nested_text = new_text
    for carrier_path in [l for l in _consumer_carrier_skew(ops) if "." in l]:
        parent_path = carrier_path.rsplit(".", 1)[0]      # T-12165: the IMMEDIATE parent at any depth
        fragment = _ops_born_nested_fragment(carrier_path)
        if not fragment:
            continue
        injected = _inject_nested_subfield(nested_text, parent_path,
                                           fragment.replace("__YITC_CLI__", cli_form))
        if injected is not None and injected != nested_text:
            nested_text = injected
            nested_pulled.append(carrier_path)
    if nested_pulled:
        # SAFETY (audit-pre): never write a carrier the injection would break — re-parse the candidate
        # and DROP the nested injection (top-level delivery still stands) if it no longer round-trips.
        try:
            if isinstance(state.load_ops_str(nested_text), dict):
                new_text = nested_text
                pulled.extend(nested_pulled)
        except yaml.YAMLError:
            pass

    # DECLARATION-GATED CAPABILITY DISCLOSURE (T-11366) — deliver the generated stanza into each
    # PRESENT top-level section that lacks it. Scoped to the ORIGINAL carrier's sections: a section
    # PULLED just above already carries its stanza (it came from the born template whole), so scoping
    # on `ops` is what prevents a double-inject — the same reasoning the nested pass uses. Comment-only,
    # so this arm can never change a declared value; marker-keyed, so a re-run is byte-identical.
    disclosed: list = []
    disclosure_text = new_text
    for section, stanza in _ops_born_disclosures().items():
        if section not in ops:
            continue
        injected = _inject_section_disclosure(disclosure_text, section,
                                              stanza.replace("__YITC_CLI__", cli_form))
        if injected is not None and injected != disclosure_text:
            disclosure_text = injected
            disclosed.append(section)
    if disclosed:
        # SAME safety posture as the nested pass: never write a carrier the injection would break.
        # A comment-only injection cannot, but the guard costs nothing and the invariant is what is
        # promised — re-parse the candidate and DROP the whole disclosure arm if it no longer parses.
        try:
            if isinstance(state.load_ops_str(disclosure_text), dict):
                new_text = disclosure_text
                if disclosed_out is not None:
                    disclosed_out.extend(disclosed)      # REPORTED, never silent (the caller prints it)
        except yaml.YAMLError:
            pass

    if new_text != text:
        write_text_atomic(ops_path, new_text)
    return pulled


# ── CARRIER-BACKFILL of a NEWLY-mandatory section (T-10982 / SPEC-0093 rule 11) ──────────────────
# The banner that opens every backfilled block. It is the DOCUMENTED half of the mode's contract: a
# reader opening the carrier must not be able to mistake this scaffold for an answer, and must learn —
# from the carrier itself, not from a terminal line that scrolled away — that the next ORDINARY init
# refuses until the section is answered.
_BACKFILL_BANNER = (
    "  # ── BACKFILLED UNANSWERED by `__YITC_CLI__ init --backfill-mandatory` (T-10982) ──\n"
    "  # This project was created BEFORE this section became MANDATORY, so an ordinary `init` could\n"
    "  # never hand it over (the rule-11 update path skips mandatory sections by construction). What\n"
    "  # follows is the SCAFFOLD ONLY — NOTHING BELOW IS AN ANSWER. The born template's example\n"
    "  # waiver was DELIBERATELY NOT delivered: it asserts a FACT about this project that nobody\n"
    "  # here verified, and auto-answering a mandatory question on a project's behalf is exactly what\n"
    "  # this delivery refuses to do. So where the guidance below says «replace the waiver below»,\n"
    "  # answer the EMPTY key at the END of this block instead — declare it, or write your OWN\n"
    "  # `waiver: {reason: <why>}`.\n"
    "  # UNTIL YOU DO, THE NEXT ORDINARY `init` WILL REFUSE — declare-or-waive is fail-closed\n"
    "  # (SPEC-0093 rule 3). That refusal is the POINT of this delivery, not a regression.\n"
)


def _born_unanswered_fragment(name: str, declare_key, cli_form: str = "bin/yitc-v2"):
    """Render the born block of MANDATORY section `name` in an UNANSWERED shape (T-10982) — the born
    GUIDANCE without the born ANSWER. Returns the text, or None when there is nothing to render.

    WHY THE ANSWER IS STRIPPED. The born template ships each mandatory section with a FILLED, plausible
    waiver ("no spike sandbox yet…"). That is honest AT BIRTH — a project born today genuinely has no
    spike stack. Back-delivered to an EXISTING project it is an unverified factual claim about someone
    else's system, and for at least one consumer it is demonstrably FALSE (boomrocket's refresh script
    restores production into its sandbox, X-0798). Delivering it would AUTO-ANSWER a mandatory question
    for nine projects at once — the `lessons/a-stance-mirror-is-only-sound-at-birth` class, one
    altitude down: a born ANSWER is only sound at birth, exactly as a stance MIRROR is.

    THE SHAPE, and why it fails closed. The block keeps the `<name>:` line, gains the `_BACKFILL_BANNER`,
    keeps every born guidance comment and every OTHER born subfield verbatim, DROPS the born answer
    blocks (`waiver` and any born `<declare_key>` block), and ends with a bare, VALUELESS
    `  <declare_key>:`. That parses as a present mapping whose declare-key is empty — so
    `_ops_carrier_violations` reports it `present but empty or wrong-typed … declare a non-empty
    <declare_key>: or waiver: {reason: <why>}` and the sweep FAILS CLOSED, naming the section AND the
    key to answer. Deliberately NOT a comment-only block (that parses to None → the blunter "present
    but not a mapping"), and deliberately NOT an invented marker key (the declare-key IS the question,
    and it is registry-derived, so this renders for ANY concern that becomes mandatory).

    The subfield split reuses `_ops_split_subfields_at`'s exact rule at INDENT 2 (one splitter contract,
    CHARTER §P5); the leading guidance comments — which that helper drops — are preserved here. This
    path stays TOP-LEVEL-only by contract (`_registry_mandatory_top_level` excludes dotted concerns),
    so it splits at depth 1 and never descends."""
    import re
    fragment = _ops_born_sections().get(name)
    if not fragment:
        return None                                    # no born surface → nothing to deliver
    if not (isinstance(declare_key, str) and declare_key.strip()):
        return None                                    # no declare-key → no unanswered shape to render
    lines = fragment.splitlines(keepends=True)
    header: list = []                                  # the guidance comments BEFORE the first subfield
    blocks: list = []                                  # [(subfield_name, text)] in born order
    cur, buf = None, []
    for line in lines[1:]:                             # skip the column-0 `<name>:` header line
        m = re.match(r"^  ([A-Za-z_][\w-]*):", line)
        if m and line[2:3] != " ":                     # exactly-2-space indent starts a new subfield
            if cur is not None:
                blocks.append((cur, "".join(buf)))
            cur, buf = m.group(1), [line]
        elif cur is not None:
            buf.append(line)
        else:
            header.append(line)
    if cur is not None:
        blocks.append((cur, "".join(buf)))
    body = _BACKFILL_BANNER + "".join(header) + "".join(
        t for n, t in blocks if n not in ("waiver", declare_key))
    if not body.endswith("\n"):
        body += "\n"
    head = lines[0] if lines[0].endswith("\n") else lines[0] + "\n"
    return (head + body + f"  {declare_key}:\n").replace("__YITC_CLI__", cli_form)


def _backfill_mandatory_sections(ops_path, write_text_atomic, cli_form: str = "bin/yitc-v2") -> list:
    """T-10982 / SPEC-0093 rule 11 — the CARRIER-BACKFILL delivery: hand an EXISTING consumer the
    top-level section(s) that became MANDATORY after it was init'ed, in an UNANSWERED shape. Returns
    the section names delivered (empty = nothing missing → the caller makes it a total no-op).

    WHY THIS IS NOT `_update_ops_carrier`. That path (rule 11) runs INSIDE the ordinary init, ahead of
    the fail-closed sweeps — and T-10688 wraps those sweeps so that ANY refusal calls
    `_restore_pre_sweep_delivery`, rewinding every pre-sweep carrier write. A section delivered
    UNANSWERED makes the sweep refuse BY CONSTRUCTION, so on that path the rollback ALWAYS fires and
    the delivery never survives the command (measured on a sandbox consumer, 2026-08-12: carrier
    byte-identical, tree clean). Hence a DEDICATED delivery-only seam that exits before any sweep. The
    atomicity invariant is untouched: this mode runs no sweep, so it has nothing to roll back, and the
    ordinary init still leaves a refused carrier byte-identical.

    NON-DESTRUCTIVE, keyed on section PRESENCE — the identical rule `_update_ops_carrier` uses. A
    section already in the carrier is SKIPPED whatever its stance: a DECLARED one keeps its
    declaration, a WAIVED one keeps its own reason, and an already-backfilled unanswered one is left
    for the sweep to fail closed. That is also what makes the mode IDEMPOTENT — the second run finds
    every section present, delivers nothing, writes nothing.

    REGISTRY-DERIVED end to end (SPEC-0128 Rule 2): the deliverable set is `_registry_mandatory_top_level()`
    and each block is rendered from `graph/born-ops.yaml` — no hand list, no second template, no parallel
    parser. Self-contained (inline yaml + `write_text_atomic` passed by the caller) so cmd_init's
    injected-deps contract stays unchanged (see the module header)."""
    import yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)
    if not ops_path.exists():
        return []                                    # no carrier — seeding one is the bare init's job
    text = ops_path.read_text(encoding="utf-8")
    try:
        ops = state.load_ops_str(text)
    except yaml.YAMLError:
        return []                                    # malformed (incl. a duplicate top-level key) — the
                                                     # sweep fails closed; don't append to an untrustworthy carrier
    if not isinstance(ops, dict):
        return []
    mandatory = _registry_mandatory_top_level()
    delivered: list = []
    appended = ""
    for name in _ops_born_sections():                # BORN order — the same iteration `_update_ops_carrier`
        if name not in mandatory:                    # uses, so a backfilled carrier reads like a fresh one
            continue                                 # extensible — the rule-11 update path owns it
        if name in ops:
            continue                                 # PRESENT — never overwritten (see the docstring)
        fragment = _born_unanswered_fragment(name, mandatory[name], cli_form)
        if not fragment:
            continue
        appended += fragment
        delivered.append(name)
    if not appended:
        return []
    sep = "" if (not text) or text.endswith("\n") else "\n"
    new_text = text + sep + appended
    # SAFETY — never write a carrier the delivery would break (the `_update_ops_carrier` nested-injection
    # precedent): re-parse the candidate and drop the whole delivery if it no longer round-trips.
    try:
        if not isinstance(state.load_ops_str(new_text), dict):
            return []
    except yaml.YAMLError:
        return []
    write_text_atomic(ops_path, new_text)
    return delivered


# ── THE MANDATORY-FLIP MIGRATION GUARD (T-10984 / SPEC-0128 Rule 6) ─────────────────────────────
# T-10982 delivered the MIGRATION (`init --backfill-mandatory`); this is the OBLIGATION to carry it.
# A concern becomes `presence_policy: mandatory` by a one-word edit to a `concern:` block, and until
# this guard nothing anywhere asked whether a carrier authored BEFORE that edit could ever receive the
# section. That silent accept is exactly how spike_sandbox + spike_data_safety became mandatory for
# nine already-existing consumers with no way to be asked (decisions/T-10982-audit-adhoc.yaml finding 3:
# "mandatory GROWTH was allowed without migration semantics distinct from the born-template answer").
# The guard is registry-DERIVED (no hand list, SPEC-0128 Rule 2) and it does not TRUST the mechanism —
# it EXECUTES it against a pre-change carrier and reads the result.
def _carrier_text_without_section(text: str, section: str) -> str:
    """The born carrier text with top-level `section` REMOVED — i.e. the carrier as it stood BEFORE the
    flip made that section mandatory. This is what makes the guard's evidence PRE-CHANGE (T-10984 AC3):
    a born-TODAY carrier already carries the section, so delivering to it proves nothing at all — the
    backfill would skip it and read green while the class recurs.

    Splits on the SAME contract `_ops_born_sections` uses (a column-0 `<name>:` line opens a top-level
    section and everything indented under it belongs to it), so "one section" means here exactly what it
    means there (CHARTER §P5 — one splitter, not two)."""
    import re
    out: list = []
    skipping = False
    for line in text.splitlines(keepends=True):
        m = re.match(r"^([A-Za-z_][\w-]*):", line)
        if m and not line[:1].isspace():
            skipping = (m.group(1) == section)
        if not skipping:
            out.append(line)
    return "".join(out)


def _mandatory_migration_probe(section: str, declare_key: str, cli_form: str = "bin/yitc-v2",
                               carrier_text: str | None = None):
    """RUN the shipped migration against a PRE-CHANGE carrier for ONE mandatory concern. Returns None
    when the concern proves it can migrate an old carrier, else the reason string (T-10984 AC2/AC3).

    Not a claim about the mechanism — an EXECUTION of it. Four things must hold, and each is asserted
    against the guard's own signature rather than against the world (lessons/a-negative-control-must-
    fail-without-the-intervention.md): the probe carrier must genuinely LACK the section; the shipped
    `_backfill_mandatory_sections` must NAME it delivered; the delivered carrier must re-parse and carry
    the section; and `_ops_carrier_violations` — the one stance evaluator init's fail-closed sweep uses —
    must then NAME the section unanswered. That last leg is the load-bearing one: it is what proves the
    scaffold ASKS the pre-change project rather than ANSWERING for it (lessons/a-stance-mirror-is-only-
    sound-at-birth.md — birth is the only licence to answer on an owner's behalf).

    Hermetic: writes only into a temp dir, reads only committed derived artifacts. `carrier_text`
    overrides the pre-change carrier the probe builds — the affordance that lets the AC3 arm hand this
    the BORN carrier and read the refusal, instead of asserting the pre-change property in prose."""
    import tempfile
    from pathlib import Path

    import yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)
    try:
        text = (carrier_text if carrier_text is not None
                else _carrier_text_without_section(_born_ops_template(), section))
        before = state.load_ops_str(text)
    except (SystemExit, yaml.YAMLError) as e:
        return f"could not build a pre-change carrier from the born template ({e.__class__.__name__})"
    if not isinstance(before, dict):
        return "the born template does not parse as a carrier mapping"
    if section in before:
        # AC3, stated as code: evidence from a carrier that ALREADY has the section is no evidence.
        return (f"the probe carrier still CARRIES `{section}` — a born-today carrier proves nothing; "
                f"the evidence must come from a carrier authored BEFORE the flip")
    with tempfile.TemporaryDirectory() as tmp:
        ops_path = Path(tmp) / "yitc-ops.yaml"
        ops_path.write_text(text, encoding="utf-8")
        delivered = _backfill_mandatory_sections(
            ops_path, lambda p, t: Path(p).write_text(t, encoding="utf-8"), cli_form)
        if section not in delivered:
            return (f"`{cli_form} init --backfill-mandatory` delivered nothing for `{section}` on a "
                    f"pre-change carrier (delivered: {sorted(delivered) or 'nothing'}) — an existing "
                    f"project could never receive it")
        try:
            after = state.load_ops_str(ops_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            return f"the backfilled carrier no longer parses ({e.__class__.__name__})"
    if not isinstance(after, dict) or section not in after:
        return f"the backfilled carrier does not carry `{section}` after delivery"
    if not any(section in v for v in _ops_carrier_violations(after)):
        return (f"the delivered `{section}` scaffold does NOT fail closed — the declare-or-waive sweep "
                f"does not ask for `{declare_key}:`, so the section was ANSWERED for the project rather "
                f"than asked of it (SPEC-0093 rule 3)")
    return None


def mandatory_migration_violations(entries: list | None = None, cli_form: str = "bin/yitc-v2") -> dict:
    """T-10984 / SPEC-0128 Rule 6 — the guard at the REGISTRY-CHANGE point: a concern may not be
    `presence_policy: mandatory` unless the same corpus supplies an UNANSWERED migration scaffold AND
    probe evidence that a PRE-CHANGE carrier receives it. Returns
    {"proven": [section, …], "violations": [{kind, detail}, …]} — the caller (the `graph conformance`
    host seam, the `_key_ownership_violations` precedent) prints the violations and folds them into the
    RED set. `entries` defaults to the live derived registry, and is a PARAMETER so a fixture flip can
    be evaluated without touching the corpus.

    Registry-DERIVED end to end (SPEC-0128 Rule 2 — no hand list): a concern that becomes mandatory is
    checked with no code edit, which is the whole point — the guard must be in place BEFORE the next
    flip, not written after it strands consumers again.

    Three refusal families, all naming the concern (never a bare count):
      • `concern-mandatory-no-migration-route` — a NESTED (dotted) mandatory concern. T-10982 left nested
        deliberately outside the backfill (its parent block is the delivery site), so a nested MANDATORY
        concern today has no way to reach an old carrier. Fail closed rather than exempt it silently:
        make it top-level, or build the nested delivery in the SAME change.
      • `concern-mandatory-no-scaffold` — no unanswered scaffold renders (no `born:` block, or no
        `declare_key` to leave empty), so there is nothing to hand an existing project.
      • `concern-mandatory-unproven-migration` — a scaffold renders but the shipped delivery does not
        actually land it, unanswered, on a pre-change carrier.
    `proven` is returned alongside so the check is never VACUOUSLY green: a clean run names which
    concerns it exercised, and an empty `proven` on a corpus that HAS mandatory concerns is visible."""
    if entries is None:
        entries = _load_concern_registry()
    proven: list = []
    viols: list = []
    seen: set = set()
    for entry in sorted(entries, key=lambda e: str(e.get("section") or "")):
        if entry.get("presence_policy") != "mandatory":
            continue
        section = entry.get("section")
        carrier_path = entry.get("carrier_path") or section
        if not (isinstance(section, str) and section.strip()) or section in seen:
            continue                     # a mis-declared entry — `concern-malformed` already flags it
        seen.add(section)
        spec_id = entry.get("spec") or "?"
        where = f"concern `{section}` (presence_policy: mandatory, declared on {spec_id})"
        if isinstance(carrier_path, str) and "." in carrier_path:
            viols.append({"kind": "concern-mandatory-no-migration-route",
                          "detail": f"{where} is NESTED (`{carrier_path}`) and the carrier-backfill "
                                    f"delivers TOP-LEVEL sections only — a project created before the "
                                    f"flip can never receive it. Make the concern top-level, or ship the "
                                    f"nested delivery in this same change (SPEC-0128 Rule 6)"})
            continue
        declare_key = entry.get("declare_key")
        if not _born_unanswered_fragment(section, declare_key, cli_form):
            viols.append({"kind": "concern-mandatory-no-scaffold",
                          "detail": f"{where} has no UNANSWERED migration scaffold — it needs a `born:` "
                                    f"block AND a `declare_key` so `{cli_form} init --backfill-mandatory` "
                                    f"can hand an existing project the question. A concern may not become "
                                    f"mandatory without one (SPEC-0128 Rule 6)"})
            continue
        reason = _mandatory_migration_probe(section, declare_key, cli_form)
        if reason:
            viols.append({"kind": "concern-mandatory-unproven-migration",
                          "detail": f"{where} has a scaffold but no working migration: {reason} "
                                    f"(SPEC-0128 Rule 6)"})
            continue
        proven.append(section)
    return {"proven": proven, "violations": viols}


def born_permissive_concerns(entries: list | None = None) -> list:
    """T-11968 (SPEC-0189 rules 1+8) — the registry-DERIVED set of concerns whose BORN value is declared
    PERMISSIVE, i.e. whose born declaration RELAXES a control. Returns the registry entries, sorted by
    section, that carry `born_stance: permissive`.

    THIS IS THE ONE READER OF BORN STANCE, and that is the point rather than a convenience. The born
    declaration WRITE path, the refusal below, and any later caller all ask THIS function — so the stance
    can never be re-derived two different ways and drift (CHARTER §P5). A later card makes its concern
    born-permissive by adding two lines to its OWN `concern:` block; nothing here changes.

    `entries` defaults to the live derived registry and is a PARAMETER for the `mandatory_migration_
    violations` reason — a fixture declaration can be evaluated without touching the corpus.

    FAIL-CLOSED ON THE ADMITTING SIDE: `graph build` carries `born_stance` only when it is one of the
    closed vocabulary's two words, so a typo'd stance arrives here ABSENT and the concern reads as
    declaring nothing. That direction is deliberate — an unreadable stance must never be able to admit an
    unwatched permissive default, and a protective-reading concern is refused nothing."""
    if entries is None:
        entries = _load_concern_registry()
    out = [e for e in entries
           if isinstance(e, dict) and e.get("born_stance") == "permissive"
           and isinstance(e.get("section"), str) and e["section"].strip()]
    out.sort(key=lambda e: (str(e.get("section") or ""), str(e.get("spec") or "")))
    return out


def _born_fragment_is_live(section: str) -> bool:
    """Does this concern's BORN fragment actually DECLARE something (T-11972)? Total, never raises.

    LIVE means `_mirror_adoption_status` reads the born text as `adopt` — the SAME stance reader
    `record_born_permissive_ratifications` consults before it will ratify anything, and the same one
    the declare-or-waive sweep mirrors. Reusing it is not tidiness: "the declaration is live" is
    exactly the condition ratification already turns on, so a second spelling here could drift from
    the one that decides whether a relaxation gets provenance (CHARTER §P5).

    PARSED THROUGH `state.load_ops_str`, the ONE parser library — never a bespoke local parse.
    Besides P5, a bespoke parse here would register as a NEW ops-carrier reader against the T-11280
    one-entry-point invariant (`tests/test_pinned_verify.py`), which is a real signal and not a
    formality: the born fragment and a consumer's carrier are the same shape, and every reading of
    that shape belongs to one entry point. (That checker matches on TEXT, so this note deliberately
    does not spell the parser call it forbids — naming it even in prose trips the guard.)

    A COMMENTED fragment parses to nothing declared and is NOT live — surface 1's state, and the
    state every unamended corpus must stay in. UNREADABLE => NOT LIVE; this helper answers only "is a
    relaxation actually written here", and the fail-closed judgement about what an unreadable CHARTER
    means belongs to its caller (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`)."""
    import yaml as _yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader
    name = str(section or "").strip()
    try:
        fragment = _ops_born_sections().get(name)
        if not fragment:
            return False
        parsed = state.load_ops_str(fragment)
    except (_yaml.YAMLError, OSError, SystemExit):
        return False
    if not isinstance(parsed, dict):
        return False
    entry = next((e for e in _load_concern_registry()
                  if isinstance(e, dict) and str(e.get("section") or "").strip() == name), None)
    if not entry:
        return False
    return _mirror_adoption_status(parsed, entry) == "adopt"


def _charter_authorizes_born_permissive(charter_text: "str | None" = None) -> bool:
    """Has the CHARTER amendment that authorizes a born relaxation landed (T-11972, SPEC-0189 r7+8)?

    Resolved through `debt.charter_amendment_state`, the ONE reader of the amendment's three elements
    — this adds no second spelling of "is the CHARTER amended" (CHARTER §P5). The CHARTER is read from
    the ENGINE root (resolved relative to THIS module, the `_load_concern_registry` idiom), never the
    consumer cwd: the born fragment a consumer receives is the KERNEL's, so the authorization for it
    lives in the KERNEL's CHARTER regardless of where the sweep runs.

    FAIL-CLOSED: an unreadable CHARTER, or a debt module that cannot be imported, returns False — an
    admission guard that cannot PROVE its precondition must refuse rather than admit."""
    from pathlib import Path

    try:
        from lib import debt as _debt
    except Exception:                       # noqa: BLE001 — cannot prove it => not authorized
        return False
    text = charter_text
    if text is None:
        try:
            text = (Path(__file__).resolve().parents[2] / "CHARTER.md").read_text(encoding="utf-8")
        except OSError:
            return False
    try:
        return bool(_debt.charter_amendment_state(text).get("amended"))
    except Exception:                       # noqa: BLE001 — same direction
        return False


def born_permissive_detector_violations(entries: list | None = None, *,
                                        charter_text: "str | None" = None) -> dict:
    """T-11968 / SPEC-0189 rule 1 — the guard at the DECLARATION point: a default may be born permissive
    ONLY if a detector for its absence is NAMED in the same corpus. Returns
    {"proven": [section, …], "violations": [{kind, detail}, …]} — the caller (the `graph conformance` host
    seam, the `mandatory_migration_violations` precedent) prints the violations and folds them into the
    RED set.

    A REFUSAL, NOT A WARNING, and the choice is the rule's own. SPEC-0189 rule 1 makes the PAIR — the
    permissive value AND its detector — the unit of admission: "a permissive birth without a detector is
    not admitted", binding at AUTHORING time. A warning would leave exactly the unenforced convention
    that rule forbids, and the failure it permits is silent by construction — a born-permissive default's
    whole cost is that nothing surfaces it on its own, so the review that would have caught it later is
    the very thing the missing detector disables.

    Registry-DERIVED end to end (SPEC-0128 Rule 2 — no hand list): the NEXT concern to be born permissive
    is checked with no code edit here, which is the whole point of shipping this guard BEFORE the cards
    that flip the defaults rather than after they have shipped unwatched.

    TWO refusal families, each naming the concern (never a bare count):
      • `concern-permissive-born-no-detector` — `born_stance: permissive` with no non-empty `detector:`.
      • `concern-permissive-born-unauthorized-by-charter` (T-11972, SPEC-0189 rules 7+8) — the concern's
        born fragment DECLARES something (it is LIVE, so a confirmed birth would actually write the
        relaxation) while the CHARTER §Project-declared audit-post exemption amendment has NOT landed.

    WHY THE SECOND FAMILY LIVES HERE, in the guard rule 1 already owns, rather than in the per-birth
    write path: this function IS the admission point — rule 1 makes the declaration's ADMISSION the
    question and binds it at AUTHORING time, which is exactly the altitude "the permissive default may
    not ACTIVATE before the amendment lands" is about. The write path (`born_permissive_gate`) answers a
    different question — whether THIS birth carries a confirmation (rule 8) — and wiring a corpus-wide
    authorization check into it would both put the rule at the wrong altitude and change concern-blind
    shared machinery that this card registers into rather than redefines. A card's own CHARTER
    authorization is a property of the corpus, so it is checked once, where admission is decided.

    A COMMENTED born fragment is NOT a violation, deliberately: it declares nothing, so no relaxation can
    be written and there is nothing for the amendment to authorize (this is precisely surface 1's state).
    The condition is the fragment being LIVE — the same `_ops_declared` reading `_mirror_adoption_status`
    uses, so "declares something" means here exactly what it means everywhere else (CHARTER §P5).

    FAIL-CLOSED ON THE CHARTER READ: an unreadable CHARTER cannot PROVE the authorization, and an
    admission guard that cannot prove its precondition must refuse, never admit.

    `proven` is returned alongside so the check is never VACUOUSLY green: a clean run names which
    permissive concerns it exercised, and an empty `proven` on a corpus that HAS permissive concerns is
    visible. On a corpus with no permissive concern at all both lists are empty, which is the honest
    reading of "there was nothing to check" — distinct from "everything checked out"."""
    proven: list = []
    viols: list = []
    seen: set = set()
    for entry in born_permissive_concerns(entries):
        section = entry["section"].strip()
        if section in seen:
            continue                     # a duplicate declaration — `concern-malformed` already flags it
        seen.add(section)
        spec_id = entry.get("spec") or "?"
        detector = entry.get("detector")
        if isinstance(detector, str) and detector.strip():
            # the PAIR is satisfied; the corpus-level AUTHORIZATION is the second, independent door
            if _born_fragment_is_live(section) and not _charter_authorizes_born_permissive(charter_text):
                viols.append({"kind": "concern-permissive-born-unauthorized-by-charter",
                              "detail": f"concern `{section}` (born_stance: permissive, declared on "
                                        f"{spec_id}) names a detector AND ships a LIVE born "
                                        f"declaration, but the CHARTER §Project-declared audit-post "
                                        f"exemption amendment has NOT landed — so nothing authorizes a "
                                        f"born relaxation. SPEC-0189 rules 7+8: the amendment is a "
                                        f"requires-ordered DELIVERABLE, not an intention, and the "
                                        f"permissive default may not ACTIVATE before it lands. Land "
                                        f"the amendment, or leave the born fragment COMMENTED"})
                continue
            proven.append(section)
            continue
        if _born_fragment_is_live(section) and not _charter_authorizes_born_permissive(charter_text):
            viols.append({"kind": "concern-permissive-born-unauthorized-by-charter",
                          "detail": f"concern `{section}` (born_stance: permissive, declared on "
                                    f"{spec_id}) ships a LIVE born declaration, but the CHARTER "
                                    f"§Project-declared audit-post exemption amendment has NOT landed "
                                    f"— so nothing authorizes a born relaxation. SPEC-0189 rules 7+8: "
                                    f"the amendment is a requires-ordered DELIVERABLE, not an "
                                    f"intention, and the permissive default may not ACTIVATE before it "
                                    f"lands. Land the amendment (it must SEPARATE «an absent "
                                    f"declaration reads fail-closed» from the born half, and state the "
                                    f"merit), or leave the born fragment COMMENTED"})
            continue
        viols.append({"kind": "concern-permissive-born-no-detector",
                      "detail": f"concern `{section}` (born_stance: permissive, declared on {spec_id}) "
                                f"names NO `detector:` — a default may be born permissive ONLY if a "
                                f"detector for its absence is named in the same corpus (SPEC-0189 rule "
                                f"1: the pair is the unit of admission). Name the detector on the "
                                f"concern block and register it in the kernel detector registry "
                                f"(bin/lib/debt.py), or do not declare the born value permissive"})
    return {"proven": proven, "violations": viols}


# ── SPEC-0189 rule 8 — the BIRTH-RATIFICATION write path (T-11985) ──────────────────────────────────
# The shared, CONCERN-BLIND mechanism the born-permissive surface cards register into. Rule 8 fixes the
# axis as the VALUE'S DIRECTION and is blind to WHICH gate is relaxed, so every function below takes the
# registry stance as its ONLY input: there is no concern name, no per-surface branch, and adding a
# surface is two lines on that surface's OWN `concern:` block (`born_stance: permissive` + `detector:`) —
# nothing here changes for the next registrant, which is the whole point of shipping it as a definer.
_BORN_PERMISSIVE_CONFIRM_FLAG = "--confirm-born-permissive"


def parse_born_permissive_confirmations(specs: list | None, entries: list | None = None) -> dict:
    """Parse `--confirm-born-permissive SECTION:OWNER` into {section: owner} (T-11985, SPEC-0189 rule 8).

    The grammar is the `--adopt-concern SECTION:STATUS:OWNER` grammar MINUS the status, because this
    mechanism FIXES the status: a confirmation ratifies the born declaration it admits, it never records
    some other stance. Reusing the shape (and its handle validation) keeps one idiom for the operator.

    FAIL-CLOSED AT THE PARSE, in three ways, each refusing rather than defaulting: a mal-shaped spec, an
    owner that is not a simple handle, and — the load-bearing one — a SECTION that is not a registry
    concern reading `born_stance: permissive`. That last refusal is what stops a confirmation from being
    a general-purpose admit: a confirmation for a concern with NO permissive born value would admit
    nothing and silently read as though the operator had confirmed something, which is precisely the
    unratified-relaxation state rule 8 exists to make unreachable.

    Resolved through `born_permissive_concerns` — the ONE reader of born stance (CHARTER §P5). Nothing
    here reads a concern NAME: the caller's own section string is matched against the registry walk."""
    import re
    import sys

    if not specs:
        return {}
    permissive = {e["section"].strip(): e for e in born_permissive_concerns(entries)}

    def _fail(msg: str) -> None:
        print(f"yitc-v2: {msg}", file=sys.stderr)
        raise SystemExit(1)

    out: dict = {}
    for raw in specs:
        parts = str(raw).split(":")
        if len(parts) != 2:
            _fail(f"init {_BORN_PERMISSIVE_CONFIRM_FLAG}: {raw!r} is not SECTION:OWNER (e.g. "
                  f"audit_scrutiny:sergey). The status is not yours to choose — a confirmation RATIFIES "
                  f"the born declaration it admits (SPEC-0189 rule 8).")
        section, owner = (x.strip() for x in parts)
        if section not in permissive:
            _fail(f"init {_BORN_PERMISSIVE_CONFIRM_FLAG}: {section!r} is not a concern whose BORN value "
                  f"is declared permissive (`born_stance: permissive` in graph/concern-registry.json), so "
                  f"there is no relaxing declaration for a confirmation to admit. Confirmable concerns: "
                  f"{', '.join(sorted(permissive)) or '(none declared)'}.")
        if not re.match(r"^[\w.@+-]+$", owner):
            _fail(f"init {_BORN_PERMISSIVE_CONFIRM_FLAG}: owner {owner!r} must be a simple handle "
                  f"([\\w.@+-]+, no spaces/colons) — it is recorded verbatim as the declaration's "
                  f"ratification provenance.")
        out[section] = owner
    return out


def born_permissive_gate(born_text: str, confirmations: dict | None, *, entries: list | None = None) -> tuple:
    """THE WRITE PATH (T-11985, SPEC-0189 rule 8). Returns `(text, written, withheld)`: the born carrier
    text with every UNCONFIRMED born-permissive concern's top-level section REMOVED, the sections a
    confirmation admitted, and the ones withheld.

    ONE RULE, AND THE DECLARATION IS WHAT IS WITHHELD (F-3). Rule 8 says a relaxing born declaration is
    written only against an explicit confirmation, and that where the confirmation is unavailable the
    declaration is NOT written. Withholding the whole SECTION from the born body is how that is achieved
    without a branch of its own — there is no per-concern surgery here, just "this section does not go
    into what init writes".

    WHAT THE OPERATOR ACTUALLY SEES, stated plainly because it is NOT "the section never appears":
    `_sweep_ops_carrier` afterwards PULLS the kernel's section stub for every registered concern, so a
    concern the kernel knows about arrives in the carrier as DOCUMENTATION — comments, and no relaxing
    declaration. That is the correct outcome and it is deliberately NOT suppressed: exempting the sweep
    for born-permissive concerns would be teaching shared machinery about this mechanism, which option F
    forbids (F-4). The load-bearing absence is the DECLARATION's, not the section's — an absent
    declaration reads the protective value (F-1), so automation supplying no confirmation cannot produce
    a project with a gate switched off, and no sweep, view or pre-seed had to be taught anything.

    ABSENCE IS UNTOUCHED (F-1 / rule 7). This function edits only what init WRITES. No reader of an
    absent declaration is touched here, which is the asymmetry rule 7 requires: moving both would
    silently re-declare every existing consumer.

    CONCERN-BLIND BY CONSTRUCTION (rule 8's own axis). The section set comes from the registry stance
    walk `born_permissive_concerns` and NOTHING here reads a concern's name, its declare-key or its
    meaning — two different concerns take byte-identical code paths. Removal reuses
    `_carrier_text_without_section`, the same top-level-section splitter `_ops_born_sections` uses (one
    splitter, CHARTER §P5), so "one section" means here exactly what it means everywhere else.

    `entries` (defaulting to the live registry) is the fixture seam: a declaration can be driven through
    this path without touching the corpus."""
    confirmations = confirmations or {}
    written: list = []
    withheld: list = []
    text = born_text
    for entry in born_permissive_concerns(entries):
        section = entry["section"].strip()
        if section in written or section in withheld:
            continue                       # a duplicate declaration — `concern-malformed` already flags it
        if confirmations.get(section):
            written.append(section)
            continue
        text = _carrier_text_without_section(text, section)
        withheld.append(section)
    return text, written, withheld


def _born_permissive_withheld_hint(section: str) -> str:
    """The one operator-facing sentence a WITHHELD born-permissive section prints (T-11985 / T-12001).

    ONE text, two write paths. The birth body and the rule-11 carrier UPDATE both withhold under the
    same rule, so they must say the same thing — two copies would be two texts the moment one is
    edited (CHARTER §P5). It states what was withheld (the DECLARATION, not the section), what that
    reads as (fail-closed), and the one flag that admits it."""
    return (f"yitc-v2: init: born-permissive concern `{section}` was NOT confirmed — its relaxing "
            f"declaration is NOT written, which reads fail-closed (SPEC-0189 rule 8). The section may "
            f"still arrive as DOCUMENTATION via the ordinary carrier sweep; what is withheld is the "
            f"declaration. Confirm it with `{_BORN_PERMISSIVE_CONFIRM_FLAG} {section}:<owner>`.")


def resolve_born_permissive_confirmations(flag_specs: list | None, *, interactive: bool,
                                          entries: list | None = None) -> tuple:
    """Resolve the confirmations for THIS birth: `{section: owner}` plus `{section: source}` provenance
    (T-11985, SPEC-0189 rule 8). Flags first (`--confirm-born-permissive`, source `flag`); then, ONLY
    when `interactive`, PROMPT once per still-unconfirmed permissive concern (source `prompt`).

    NO DEFAULT-YES ANYWHERE, and `interactive` is keyword-only with no default so every call site is a
    decision the test suite sees (`lessons/a-stance-mirror-is-only-sound-at-birth` trap 2). A
    NONINTERACTIVE birth that carries no flag confirms NOTHING — the declaration is withheld and the
    section reads fail-closed. That is rule 8's stated cost, not a regression to work around: scripted
    creation supplying neither gets a PROTECTED project.

    An EMPTY prompt answer DECLINES (the section is withheld); a non-empty one is the confirming HANDLE,
    validated by the same rule the flag uses, so a fat-fingered answer is refused rather than recorded as
    a human's ratification of a relaxed gate."""
    import re
    import sys

    confirmations = dict(parse_born_permissive_confirmations(flag_specs, entries))
    sources = {s: "flag" for s in confirmations}
    if not interactive:
        return confirmations, sources
    for entry in born_permissive_concerns(entries):
        section = entry["section"].strip()
        if section in confirmations:
            continue
        spec_id = entry.get("spec") or "?"
        print(f"\nyitc-v2: init — concern `{section}` (declared on {spec_id}) is born PERMISSIVE: its born "
              f"declaration RELAXES a control. SPEC-0189 rule 8 writes it ONLY against an explicit "
              f"confirmation, recorded as that declaration's ratification provenance.\n"
              f"  Leave EMPTY to DECLINE — the section is then left ABSENT, which reads fail-closed.",
              file=sys.stderr)
        try:
            answer = input(f"  confirming owner handle for `{section}`: ").strip()
        except EOFError:
            answer = ""
        if not answer:
            continue
        if not re.match(r"^[\w.@+-]+$", answer):
            print(f"yitc-v2: init: {answer!r} is not a simple handle ([\\w.@+-]+) — `{section}` NOT "
                  f"confirmed; the section is left absent (fail-closed).", file=sys.stderr)
            continue
        confirmations[section] = answer
        sources[section] = "prompt"
    return confirmations, sources


def record_born_permissive_ratifications(ops_path, confirmations: dict, sources: dict,
                                         write_text_atomic, _append_event, *,
                                         fresh_carrier: bool, pulled_sections: list | None = None,
                                         entries: list | None = None) -> list:
    """RATIFY IN THE SAME ACT (T-11985, SPEC-0189 rule 8 / plan option F-2). For each CONFIRMED
    born-permissive concern, record the confirmation as that declaration's ratification provenance
    through the EXISTING per-concern adoption-record writer (`_adopt_concerns`, the only sanctioned
    writer of an `adoption:` entry — prior art extended, not reinvented) under the CONFIRMING HANDLE,
    and emit `born_permissive_ratified` carrying the confirmation SOURCE. Returns the recorded sections.

    WHY THE HANDLE IS THE PROVENANCE, and why this needs no new field: the existing model already reads
    an adoption record's `owner` as the answer to "did a human review this" — `unratified_adoptions`
    counts a record iff its owner is the birth sentinel `init`. Writing the confirming handle therefore
    RECORDS the ratification in the one place every reader already looks, and does it BEFORE
    `_preseed_concern_adoptions` runs: the pre-seed is non-clobbering, so it leaves the confirmed record
    alone instead of stamping the sentinel over it. The consequence rule 8 states out loud follows by
    construction — there is no state in which the relaxation exists un-ratified, so the debt view is
    asked to carry nothing and NO shared machinery is exempted, taught or suppressed (F-4).

    BIRTH-ONLY, and the guard is `fresh_carrier` — the carrier was BORN THIS RUN — never "no record yet"
    (`lessons/a-stance-mirror-is-only-sound-at-birth`, copied WITHOUT its widening disjuncts: only the
    birth of the carrier licences writing an answer on the owner's behalf, and a confirmation given for
    THIS birth says nothing about a pre-existing consumer's stance).

    THE SECOND ADMISSION IS A BORN SECTION PULLED THIS RUN (T-12001), and it is the SAME licence, not a
    widening of it. A section the rule-11 update path delivered into an existing carrier THIS RUN arrived
    as born text against a confirmation given for THIS run — the birth of the SECTION, exactly as
    `fresh_carrier` is the birth of the CARRIER — so the confirmation ratifies it on identical terms.
    Without this, a confirmed update would write the relaxing declaration and leave it un-ratified, which
    is the state rule 8 says must not exist. The precedent is `_seed_catalog_waives`'
    `fresh_carrier=(... or "extensions" in ops_sections_pulled)`, applied PER SECTION rather than as one
    carrier-wide flag: a section NOT pulled this run is judged by `fresh_carrier` alone, so a pre-existing
    consumer's own stances stay untouched — which is precisely the widening the lesson forbids.

    THE RECORDED STATUS IS THE CARRIER'S OWN MIRROR STANCE, never a hardcoded `adopt` (T-12004): a
    live declaration mirroring `waive` is ratified `waive:<owner>`, one mirroring `adopt` as before,
    and only `na` (nothing live) is skipped — see the stance read below. And the ORDER of this call
    is load-bearing: it runs AHEAD of `_sweep_ops_carrier`, because the SPEC-0143 rule-2 stance
    cross-check EXITS on the stale `na@init` record a born-WITHHELD consumer carries once the update
    leg declares the section, which put this whole function downstream of a refusal. Its journal emit
    is BUFFERED by the caller and replayed only once the sweeps pass (the append-only journal has no
    rewind). Both rationales are written out in full at the call site in `cmd_init`."""
    import yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader
    pulled = set(pulled_sections or ())
    if not confirmations or not (fresh_carrier or pulled):
        return []
    by_section = {e["section"].strip(): e for e in born_permissive_concerns(entries)}
    # READ THE BORN CARRIER'S ACTUAL STANCE ONCE, through the SAME reader `_adopt_concerns`' own
    # stance-consistency gate uses (`_mirror_adoption_status`, T-10484 / SPEC-0143 Rule 2). A confirmation
    # admits a SECTION; whether that section's relaxing DECLARATION is live is the registering surface's
    # own business, and a surface may be registered onto this mechanism before its declaration goes live.
    # In that state there IS no relaxation, so there is nothing to ratify — and asking `_adopt_concerns`
    # to record one anyway would hit its gate, which EXITS the process and would kill the birth. So this
    # SKIPS such a section rather than bypassing the gate: the invariant "no relaxation exists
    # un-ratified" is untouched (a section declaring nothing relaxes nothing), and the ledger never
    # claims ADOPTED over a mechanism that tracks nothing — which is precisely what that gate protects.
    try:
        _text = ops_path.read_text(encoding="utf-8") if ops_path.exists() else ""
        _ops = state.load_ops_str(_text) if _text.strip() else None
    except (OSError, yaml.YAMLError):
        return []                           # the sweeps own an unreadable carrier, not this
    recorded: list = []
    for section in sorted(confirmations):
        owner = confirmations[section]
        if section not in by_section:
            continue                        # not a permissive concern — the parse already refuses this
        if not (fresh_carrier or section in pulled):
            continue                        # neither born-this-run nor pulled-this-run — not ours to answer
        # FOLLOW THE CARRIER'S OWN MIRROR STANCE — never a hardcoded `adopt` (T-12004, deviation
        # `born-permissive-ratification-skips-waiver-shaped-relaxations`). A surface may relax BY
        # WAIVER as legitimately as by a declared VALUE: the born fragment writes a `waiver:` block,
        # which `_mirror_adoption_status` reads as `waive`. The pre-T-12004 pair — skip anything that
        # is not `adopt`, then record `adopt` — was blind to exactly that shape, so a CONFIRMED birth
        # wrote the relaxing waiver with NO provenance at all (owner left at the `init` sentinel,
        # `born_permissive_ratified` empty): the un-ratified relaxation rule 8 forbids, measured on a
        # real init. So read the stance ONCE, through the SAME one reader, and RECORD IT: `waive` as
        # `waive:<owner>` — which is what `_adopt_concerns`' own refusal message names as the honest
        # exit over a waived section — and `adopt` as before. Only `na` is still skipped, and for the
        # unchanged reason: nothing is declared, so nothing relaxes and there is nothing to ratify.
        # Concern-BLIND by construction — the stance comes from the carrier, never from a name.
        stance = _mirror_adoption_status(_ops if isinstance(_ops, dict) else {}, by_section[section])
        if stance == "na":
            continue                        # section carried, declaration not live — nothing to ratify
        if not _adopt_concerns(ops_path, [f"{section}:{stance}:{owner}"], write_text_atomic):
            continue                        # already recorded identically (idempotent re-run)
        recorded.append(section)
        # MECHANICAL ARITY REPAIR (T-11972, deviation
        # `born-permissive-ratified-emit-arity-dead-on-arrival`; consult
        # `decisions/t11972-scope-fork-born-permissive-ratified-emit-arity-audit-adhoc.yaml`).
        # The injected host `_append_event` is `(event_type, task_id, data, *, ...)` and every other
        # call site in this module passes the `None` task_id positional; this one did not, so the
        # call raised TypeError and ABORTED the birth. It was DEAD ON ARRIVAL and unreachable by any
        # earlier card: the stance guard a few lines up skips a section whose declaration is not LIVE,
        # and surface 1's born fragment is COMMENTED — so T-11972, shipping the first LIVE
        # born-permissive fragment, is the first execution of this line.
        #
        # THE ROUTE KEY IS `confirmation_source`, NOT `source` (T-12004, deviation
        # `born-permissive-ratified-source-key-clobbered-by-envelope-writer`). `events.append_event`
        # stamps `data.source = <writer tag>` on EVERY row as WRITER provenance, so a payload key
        # named `source` is overwritten before it is ever read: the confirmation ROUTE (flag|prompt)
        # was silently replaced by `yitc-v2-cli`. The `owner` half always survived, so rule 8's
        # ratification RECORD was intact and this is a fidelity loss, not a correctness hole — but the
        # route is exactly what distinguishes a flag-driven ratification from a prompted one. The key
        # is renamed rather than the envelope changed: the writer tag belongs to every row and is not
        # this call site's to move (CHARTER §P5).
        _append_event("born_permissive_ratified", None, {
            "concern": section,
            "owner": owner,
            "confirmation_source": sources.get(section, "flag"),
            "spec": by_section[section].get("spec"),
        })
    return recorded


def _render_source_block(source: dict, indent: str) -> str:
    """Render an adopts entry's nested `source:` mapping as YAML TEXT (T-10775).

    Hand-rendered, never `yaml.dump` — this whole family exists to avoid the round-trip that gutted 436
    contract comments in trend-finder's carrier (X-0401). Scalars go through `_yaml_scalar` (JSON's string
    grammar is a subset of YAML's double-quoted style, so it is an exact escape-correct renderer); a bool
    or int is emitted bare; a list renders as a flow sequence of quoted scalars. Keys are emitted in the
    declared order, so the written carrier reads the way the operator typed it."""
    if not isinstance(source, dict) or not source:
        return ""
    out = f"{indent}source:\n"
    for k, v in source.items():
        if isinstance(v, list):
            rendered = "[" + ", ".join(_yaml_scalar(str(x)) for x in v) + "]"
        elif isinstance(v, bool) or isinstance(v, int):
            rendered = str(v).lower() if isinstance(v, bool) else str(v)
        else:
            rendered = _yaml_scalar("" if v is None else str(v))
        out += f"{indent}  {k}: {rendered}\n"
    return out


def _append_adopts_entries(text: str, spec_ids: list, sources: dict | None = None) -> str:
    """SPEC-0093 rule 13 — append `- spec: <id>` entries under `extensions.adopts`, preserving the carrier's
    comments/formatting (TEXT edit, NOT a yaml round-trip — same comment-preserving rationale as
    _update_ops_carrier). Handles BOTH the born inline-empty form `adopts: []` (converted to a block list)
    and an existing block list (appended after its last item). The `extensions:` section is the carrier's
    LAST section (init seeds it last), so anchoring on the `adopts:` key inside it is unambiguous.

    `sources` (T-10775, optional) maps a spec id to the nested `source:` mapping its residual demands
    (`_EXTENSION_SOURCE_SPECS`); an id absent from it keeps the plain one-line entry it always had, so
    every existing caller and carrier shape is byte-identical to before."""
    import re
    sources = sources or {}
    lines = text.splitlines(keepends=True)
    # items at the section-key indent (valid YAML block-seq); a nested `source:` rides the item's own indent
    new_items = "".join(f"  - spec: {s}\n" + _render_source_block(sources.get(s), "    ")
                        for s in spec_ids)
    # locate the `extensions:` section header (column-0 `extensions:`)
    ext_idx = next((i for i, ln in enumerate(lines)
                    if re.match(r"^extensions:\s*(#.*)?$", ln)), None)
    if ext_idx is None:                                  # defensive — init normally seeds the section first
        block = "extensions:\n  adopts:\n" + new_items
        sep = "" if (not text) or text.endswith("\n") else "\n"
        return text + sep + block
    # the section runs until the next column-0 key (or EOF); find the real `adopts:` line within it
    end_idx = len(lines)
    adopts_idx = None
    for j in range(ext_idx + 1, len(lines)):
        if re.match(r"^[A-Za-z_][\w-]*:", lines[j]) and not lines[j][:1].isspace():
            end_idx = j
            break
        if adopts_idx is None and re.match(r"^\s+adopts:", lines[j]):   # NOT a `  # adopts:` comment line
            adopts_idx = j
    if adopts_idx is None:                               # section present but no adopts: key — insert one
        return "".join(lines[:end_idx]) + "  adopts:\n" + new_items + "".join(lines[end_idx:])
    # Tolerate a TRAILING YAML COMMENT on the inline carrier (T-10715), the adopts-side twin of the
    # X-0508 waives bug at `_remove_waives_entries`: a hand-annotated carrier reads
    # `  adopts: []   # <note>`, and an id-anchored `\s*$` rejected it — so the inline branch was
    # skipped and the block-append branch below wrote `  - spec: X` on the line AFTER `adopts: []`,
    # a block-seq item dangling under a flow-list scalar, i.e. a carrier that no longer PARSES. The
    # comment must be SEPARATED by real whitespace: `adopts: []#x` is not a YAML comment at all, and
    # matching it would silently rewrite an already-invalid carrier into a valid-looking one.
    m_inline = re.match(r"^(\s*)adopts:\s*\[\s*\](?:[ \t]+(#.*?))?[ \t]*$", lines[adopts_idx])
    if m_inline:                                         # `adopts: []` → block list
        # Carry the comment onto the rewritten key line — dropping it would be the same contract-comment
        # loss (X-0401) this whole TEXT-edit-not-yaml-round-trip design exists to prevent. The newline is
        # forced (not the source line's own EOL): the appended items MUST start on their own line even
        # when the carrier ends at EOF without a trailing newline.
        comment = m_inline.group(2)
        replacement = f"{m_inline.group(1)}adopts:" + (f"   {comment}" if comment else "") + "\n" + new_items
        return "".join(lines[:adopts_idx]) + replacement + "".join(lines[adopts_idx + 1:])
    insert_at = adopts_idx + 1                           # block form → after the last contiguous list item
    for k in range(adopts_idx + 1, end_idx):
        m_item = re.match(r"^(\s*)-\s", lines[k])
        if m_item:
            insert_at = k + 1
            item_indent = len(m_item.group(1))
            continue
        if lines[k].strip() == "" or lines[k].lstrip().startswith("#"):
            continue
        # An item's own CONTINUATION lines (T-10775) — `    source:` and its nested keys — are part of
        # the item, NOT the end of the list. Treating them as a terminator spliced the new `- spec:` line
        # BETWEEN an entry and its continuation, silently RE-PARENTING that entry's `source:` onto the
        # newly appended spec: the previously-declared extension then read as source-LESS and the carrier
        # fail-closed on the very properties it had declared. The test for "still inside the item" is
        # INDENTATION (deeper than the item's own dash), the same structural test `_remove_waives_entries`
        # uses to sweep an item's continuation lines.
        if re.match(r"^\s+\S", lines[k]) and insert_at > adopts_idx + 1 \
                and len(lines[k]) - len(lines[k].lstrip()) > item_indent:
            insert_at = k + 1
            continue
        break
    return "".join(lines[:insert_at]) + new_items + "".join(lines[insert_at:])


def _remove_waives_entries(text: str, spec_ids: list) -> str:
    """Remove the `extensions.waives[]` entries for `spec_ids`, preserving the carrier's comments (TEXT
    edit, NOT a yaml round-trip — the `_append_waives_entries` sibling, same X-0401 rationale: this
    carrier's kernel contract is delivered THROUGH its comments, and a safe_load->dump round-trip gutted
    436 of them in trend-finder). Drops each matching `- spec: <id>` item AND its indented continuation
    lines (`reason:` …), stopping at the next sibling item / the section end. An id that is not waived is
    a no-op; when the last item goes, the now-empty `waives:` key is normalized to `waives: []` so the
    section keeps a well-typed list (`_hook_extensions` / `_extensions_coverage` read it either way, but a
    bare dangling `waives:` would parse as None and read as a shape change nobody asked for)."""
    import re
    if not spec_ids:
        return text
    targets = {s.strip() for s in spec_ids}
    lines = text.splitlines(keepends=True)
    ext_idx = next((i for i, ln in enumerate(lines)
                    if re.match(r"^extensions:\s*(#.*)?$", ln)), None)
    if ext_idx is None:
        return text
    end_idx = len(lines)
    waives_idx = None
    for j in range(ext_idx + 1, len(lines)):
        if re.match(r"^[A-Za-z_][\w-]*:", lines[j]) and not lines[j][:1].isspace():
            end_idx = j
            break
        if waives_idx is None and re.match(r"^\s+waives:\s*(#.*)?$", lines[j]):
            waives_idx = j
    if waives_idx is None:
        return text
    drop: set = set()
    k = waives_idx + 1
    kept_items = 0
    while k < end_idx:
        # Tolerate a TRAILING YAML COMMENT on the `- spec:` line (X-0508): a hand-annotated consumer
        # carrier (boomrocket's) waives entry reads `- spec: SPEC-XXXX   # <note>`. Without the `(?:#.*)?`
        # the id-anchored `\s*$` failed to match, so the waive was silently LEFT while `_extensions_coverage`
        # (a real yaml parse) still saw it — the both-states carrier the sweep then fail-closes on, the very
        # limbo the T-10475 un-waive exists to avoid. `(\S+)` is greedy and stops at whitespace, so the
        # comment never contaminates the captured id (a YAML `#` comment is space-separated by construction).
        m = re.match(r"^(\s*)-\s+spec:\s*(\S+)\s*(?:#.*)?$", lines[k])
        if not m:
            if re.match(r"^\s*\S", lines[k]) and not re.match(r"^\s*[-#]", lines[k]) \
               and not re.match(r"^\s+\w+:", lines[k]):
                break                                    # a sibling key ends the list
            k += 1
            continue
        item_start = k
        sid = m.group(2).strip().strip('"\'')
        k += 1
        while k < end_idx and not re.match(r"^\s*-\s", lines[k]) \
                and not re.match(r"^\s+waives:|^\s+adopts:", lines[k]):
            if lines[k].strip() and not re.match(r"^\s{3,}", lines[k]):
                break                                    # dedented out of the item
            k += 1
        if sid in targets:
            drop.update(range(item_start, k))
        else:
            kept_items += 1
    if not drop:
        return text
    out = [ln for i, ln in enumerate(lines) if i not in drop]
    if kept_items == 0:                                  # last waive removed — keep a well-typed empty list
        shift = sum(1 for i in drop if i < waives_idx)
        wi = waives_idx - shift
        # Rebuild the line rather than re.sub it: a `\s*` in the pattern eats the trailing NEWLINE, which
        # welds the following section onto it (`waives: []coverage:` — a carrier-corrupting parse error the
        # unit fixtures missed because they end at the section; the real born carrier does not).
        indent = re.match(r"^(\s*)", out[wi]).group(1)
        eol = "\n" if out[wi].endswith("\n") else ""
        out[wi] = f"{indent}waives: []{eol}"
    return "".join(out)


def _parse_extension_source(raw: str) -> tuple:
    """Parse ONE `--extension-source` flag value into `(spec_id, source_mapping)` (T-10775).

        SPEC-XXXX:key=value,key=value,...

    The `_parse_theme_spec` precedent — a flag-value grammar, parsed once, refused loudly when malformed
    (a mis-typed declaration must never read as a declaration). Two value shapes beyond a plain string:
    a `|`-separated list (`classes=code-defect|server-defect`) and a bare integer (`retention_days=90`),
    because the six-property contract asks for exactly those two. Values may contain `=` (a URL, a DSN);
    only the FIRST `=` splits, so nothing is silently truncated.

    Deliberately NOT a schema of its own: this parser knows only the flag's SHAPE. WHICH keys a source
    needs and whether it qualifies is answered by the spec's own evaluator (`_EXTENSION_SOURCE_SPECS`) —
    one home for the contract, so this grammar can never drift from it."""
    import re
    import sys
    text = (raw or "").strip()
    head, sep, tail = text.partition(":")
    spec_id = head.strip()
    if not sep or not re.match(r"^SPEC-\d{4,}$", spec_id):
        print(f"yitc-v2: init --extension-source {raw!r}: expected `SPEC-XXXX:key=value,key=value` "
              f"(the spec whose source this declares, then its properties).", file=sys.stderr)
        raise SystemExit(1)
    source: dict = {}
    for pair in tail.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, eq, value = pair.partition("=")
        key, value = key.strip(), value.strip()
        if not eq or not key:
            print(f"yitc-v2: init --extension-source {raw!r}: {pair!r} is not `key=value`.",
                  file=sys.stderr)
            raise SystemExit(1)
        if "|" in value:
            source[key] = [v.strip() for v in value.split("|") if v.strip()]
        elif value.lstrip("-").isdigit():
            source[key] = int(value)
        else:
            source[key] = value
    if not source:
        print(f"yitc-v2: init --extension-source {raw!r}: declares no properties — a source with nothing "
              f"in it cannot answer the qualifying contract (declare `key=value` pairs).", file=sys.stderr)
        raise SystemExit(1)
    return spec_id, source


def _adopt_extensions(ops_path, spec_ids: list, ENGINE_ROOT, write_text_atomic, sources=None) -> list:
    """SPEC-0093 rule 13 / SPEC-0101 §4 — the GOVERNED adopt path behind `init --adopt-extension SPEC-XXXX`.
    For each cited spec: RESOLVE it at the engine + REFUSE a missing or non-`adoptable` one (so a committed
    adoption's cite always resolves to a real adoptable node — never dangling; adoptability is enforced HERE,
    at write-time, NOT in the fail-closed carrier sweep), then idempotently append `{spec: SPEC-XXXX}` to
    `extensions.adopts`. Returns the spec ids NEWLY adopted (empty when all were already present / none asked).
    Self-contained (inline re/yaml/SystemExit; ENGINE_ROOT + write_text_atomic passed by cmd_init) so
    cmd_init's injected-deps contract stays unchanged (see the module header).

    `sources` (T-10775) carries the `--extension-source` declarations, spec id -> source mapping. For a
    spec in `_EXTENSION_SOURCE_SPECS` the adopt is GATED by that spec's own qualifying-source PREFLIGHT,
    evaluated HERE at write time — the same place adoptability is already enforced, and for the same
    reason. Without it the verb wrote a bare `- spec: SPEC-0170` that the very next sweep fail-closed on
    all six properties: a carrier WEDGED by the governed verb itself, with no verb-covered exit. Refusing
    at write time is the honest half; being ABLE to declare the source (the flag) is the other."""
    import re
    import sys
    import yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)
    if not spec_ids:
        return []

    def _fail(msg: str) -> None:
        print(f"yitc-v2: {msg}", file=sys.stderr)
        raise SystemExit(1)

    if not ops_path.exists():
        _fail(f"init --adopt-extension: {CONSUMER_OPS_CONTRACT} not found — cannot adopt into a missing carrier.")
    # VALIDATE + RESOLVE each cited spec at the engine (the adoptability gate — refuse a dangling/non-adoptable cite)
    for sid in spec_ids:
        sid = sid.strip()
        if not re.match(r"^SPEC-\d{4,}$", sid):
            _fail(f"init --adopt-extension: {sid!r} is not a SPEC-XXXX id.")
        matches = sorted((ENGINE_ROOT / "specs").glob(f"{sid}-*.yaml"))
        if not matches:
            _fail(f"init --adopt-extension: {sid} does not resolve to a spec under the engine — the cite would "
                  "be dangling. Adopt only an existing `adoptable` extension (discover via `graph query --extension`).")
        try:
            doc = state.load_str(matches[0].read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            _fail(f"init --adopt-extension: {sid} spec failed to parse ({e}).")
        marker = doc.get("extension") if isinstance(doc, dict) else None
        if marker != "adoptable":
            _fail(f"init --adopt-extension: {sid} is not an `adoptable` extension (extension={marker!r}); only "
                  "an adoptable extension has an adopt-path (SPEC-0101 §4). An internal-only extension is "
                  "discoverable but not consumer-adoptable.")
    # IDEMPOTENT append (skip ids already declared), preserving comments
    text = ops_path.read_text(encoding="utf-8")
    try:
        ops = state.load_ops_str(text) if text.strip() else None
    except yaml.YAMLError as e:
        _fail(f"init --adopt-extension: {CONSUMER_OPS_CONTRACT} failed to parse ({e}); re-run init to re-seed it.")
    existing: set = set()
    existing_sources: dict = {}
    if isinstance(ops, dict) and isinstance(ops.get("extensions"), dict):
        cur = ops["extensions"].get("adopts")
        if isinstance(cur, list):
            existing = {str((e or {}).get("spec")).strip() for e in cur if isinstance(e, dict)}
            existing_sources = {str(e.get("spec")).strip(): e.get("source")
                                for e in cur if isinstance(e, dict) and e.get("spec")}

    # ── The per-spec qualifying-source PREFLIGHT, at WRITE time (T-10775) ───────────────────────────
    sources = {k.strip(): v for k, v in (sources or {}).items()}
    # Never SILENTLY discard a requested write (the existing mixed-run idiom): a source declared for a
    # spec this invocation is not adopting would be parsed, validated and then dropped on the floor.
    asked = {s.strip() for s in spec_ids}
    for sid in sorted(set(sources) - asked):
        _fail(f"init --extension-source: {sid} has a source declaration but is not being adopted in this "
              f"run — add `--adopt-extension {sid}`, or drop the source. (A declaration this run would "
              f"otherwise be silently discarded.)")
    for sid in [s.strip() for s in spec_ids]:
        if sid not in _EXTENSION_SOURCE_SPECS:
            continue
        # The flag wins; otherwise the entry ALREADY in the carrier is what the adopt would stand on (so a
        # re-run over a consumer that declared its source by hand is not forced to re-type it). Absence is
        # NOT a pass — it is exactly the state that adopts the capability over an unreadable source.
        effective = sources.get(sid, existing_sources.get(sid))
        violations = _extension_source_violations(sid, effective, label=f"{sid} source")
        if violations:
            _fail("init --adopt-extension: " + sid + " requires a QUALIFYING source declaration and this "
                  "one does not qualify — refusing to write an adoption the carrier's own sweep would "
                  "then fail closed on:\n" + "\n".join(f"  • {v}" for v in violations)
                  + f"\nDeclare it with `--extension-source {sid}:kind=…,container=…,table=…,"
                    f"window_field=…,row_id_field=…,message_field=…,retention_days=…,"
                    f"classes=a|b|c` (one `--extension-source` per adopted spec).")
    # DEDUP both against what is already declared AND within this single invocation (repeated
    # `--adopt-extension SPEC-X --adopt-extension SPEC-X` must not append twice), preserving order.
    seen: set = set()
    to_add: list = []
    for s in spec_ids:
        s = s.strip()
        if s not in existing and s not in seen:
            seen.add(s)
            to_add.append(s)
    # ADOPTING RETIRES THE CONTRADICTED WAIVE (T-10475, fu_e0e14db83ac9). `_seed_catalog_waives` born-waives
    # every uncovered catalog member, so the ordinary waive->declare flip lands on a spec that IS waived;
    # leaving that waive in place published a carrier both declaring and refusing the same capability, which
    # no sweep saw. Computed over EVERY cited id, NOT just `to_add`: a carrier already contaminated (adopted
    # while still waived) yields an empty `to_add`, and without this it could never be healed by the verb —
    # the `_hook_extensions` gate would refuse it with no verb-covered exit. This is the owner's OWN explicit
    # adopt resolving the stance, never a mirror inferred on their behalf — the trap
    # `lessons/a-stance-mirror-is-only-sound-at-birth` names (that lesson forbids ANSWERING for the owner
    # after birth; here the owner just answered).
    _, waived_now = _extensions_coverage(ops if isinstance(ops, dict) else {})
    to_unwaive = [s.strip() for s in dict.fromkeys(spec_ids) if s.strip() in waived_now]
    if not to_add and not to_unwaive:
        return []
    new_text = _append_adopts_entries(text, to_add, sources) if to_add else text
    new_text = _remove_waives_entries(new_text, to_unwaive)
    # This governed adopt CHANGES the extensions stance (adopts: grows non-empty) — the SAME act
    # re-records the extensions adoption to MIRROR it (else the T-10481 stance-sweep refuses the
    # carrier this verb just wrote: the born `na@init` would sit over a now-DECLARED opt-in section).
    import re as _re
    new_text = _re.sub(r"(- concern: extensions\n(?:    [^\n]*\n)*?    status: )(?:waive|na)\b",
                       r"\1adopt", new_text, count=1)
    write_text_atomic(ops_path, new_text)
    return to_add


# ── Inspection-THEME declaration (SPEC-0093 rule 12) — the governed append path ──────────────────────
# T-10535 (X-0401): `inspection.themes[]` was the one carrier section a consumer could only grow by
# HAND-EDITING the carrier — no verb covered it. trend-finder's T-0141 did exactly that with a
# `yaml.safe_load` -> `yaml.dump` round-trip, which destroyed all 436 comment lines of its carrier: the
# kernel contract for this file is delivered THROUGH those comments (the declare-or-waive rules, the
# per-section semantics, the view-XOR-sweep rule), so the round-trip silently gutted the contract and
# broke their deploy-gates falsification self-test. They caught it only by luck.
#
# The fix EXTENDS the existing surface, inventing nothing (CHARTER §P1 F1/F2): the carrier already owns a
# comment-preserving surgical-TEXT-append family (`_append_adopts_entries` / `_append_waives_entries` —
# "TEXT edit, NOT a yaml round-trip"), and consumer carrier writes already ride an `-C init` extension
# flag, never a new verb and never a raw cross-repo edit (D-0019, `lessons/governed-consumer-config-
# write-via-init-extension`). So: one more flag on that family — `init --declare-theme` — appending as
# TEXT. F3 (what is removed): hand-editing `inspection.themes[]` ceases to be the only path.
_THEME_CADENCES = ("weekly", "monthly", "quarterly")

# ── The ONE kernel-owned seeded theme (SPEC-0160 rule 12, T-12053) ────────────────────────────────
# OWNER DIRECTIVE 2026-09-04 ("нет такого что отказаться — просто механизм по умолчанию"): the
# repeated-work sweep is a BASELINE mechanism in every consumer — seeded by default, no opt-out —
# because AI-authored code systematically produces this class (10 HIGH findings across 2 consumers in
# one read-only pass, X-1255 / X-1256). It is the ONE entry `inspection.themes[]` carries that the
# project does not own: a project `waiver:` covers only PROJECT-OWN themes, so it never reaches this
# entry, and an absent / de-owned / waiver-wrapped entry is a fail-closed sweep ERROR.
#
# ONE carrier for the literal, read by BOTH the seeder (`_seed_kernel_theme`) and the validator
# (`_hook_inspection`), so the two can never disagree about what the kernel entry IS (CHARTER §P5).
_KERNEL_THEME_SLUG = "repeated-work"
_KERNEL_THEME_OWNER = "kernel"
_KERNEL_THEME_CADENCE = "monthly"
# The checklist BODY lives single-SoT in the pattern (T-12051) — this entry POINTS at it and never
# restates it. The pointer is fixed by that card; it may dangle until T-12051 lands.
_KERNEL_THEME_AGAINST = "patterns/repeated-work-lens.md"
# A sensible PRODUCT-CODE default a project MAY narrow — deliberately NOT auto-detected (the kernel
# judges section SHAPE, never project layout: SPEC-0160 rule 12 / SPEC-0093 rule 3).
#
# ONE ROOT PER WHITESPACE TOKEN, each ending `/**/*` — the shape the READER provably matches, verified
# on a fixture rather than assumed (T-12062, cross X-1272/X-1271). The reader is
# `sweep_payload_metrics` (bin/lib/inspection.py): it splits `surfaces:` on whitespace, runs
# `_expand_braces` per token (ONE brace group per token — its own documented bound) and keeps
# `p.is_file()`. In pathlib `X/**` yields DIRECTORIES ONLY, so the retired value below matched
# ZERO files on every real product repo while the review-due semaphore read green — a monthly sweep
# that inspected NOTHING. Change this literal only against a measured fixture.
_KERNEL_THEME_SURFACES = "backend/**/* app/**/* frontend/src/**/* scripts/**/* workers/**/*"
# Every literal this kernel has ever SEEDED and has since retired. It is the ONE carrier of "what a
# kernel re-seed is allowed to overwrite" (`_upgrade_kernel_theme`): an entry that is BOTH
# `owner: kernel` AND byte-equal to one of these was never touched by the project, so correcting it
# is a RE-SEED, not an overwrite of the project's own work. A project that NARROWED the default fails
# the byte-equality test and is left alone — the distinction is mechanical, never a judgement of
# intent. A tuple so a future correction APPENDS a literal instead of growing a second predicate.
_KERNEL_THEME_SURFACES_RETIRED = (
    "backend/** app/** frontend/src/** scripts/** workers/**",   # T-12053 seed; 0 files (T-12062)
)
# The seven classes of repeated work (labels only — each class's detection heuristic, severity rubric
# and remedy shape live in the pattern named by `against:`).
_KERNEL_THEME_CHECKS = (
    "n-plus-one-queries-in-loops",
    "same-file-config-or-row-re-read-per-request-or-iteration",
    "remote-resource-re-fetched-or-pagination-restarted",
    "unbounded-loops-retries-or-polls",
    "whole-table-or-whole-dir-scans-repeated-per-lookup",
    "frontend-refetch-and-effect-retrigger-loops",
    "worker-or-cron-reprocessing-without-a-watermark",
)


def _kernel_seeded_theme() -> dict:
    """The kernel-owned `repeated-work` entry, in the same shape `_parse_theme_spec` produces (plus the
    `owner:` key that marks it as NOT the project's to remove). Built fresh per call so no caller can
    mutate the module-level literal."""
    return {
        "theme": _KERNEL_THEME_SLUG,
        "owner": _KERNEL_THEME_OWNER,
        "probe": {"sweep": {"surfaces": _KERNEL_THEME_SURFACES,
                            "checks": list(_KERNEL_THEME_CHECKS),
                            "against": _KERNEL_THEME_AGAINST}},
        "cadence": _KERNEL_THEME_CADENCE,
    }


def _yaml_scalar(s: str) -> str:
    """Render one string as a YAML double-quoted scalar (hand-rendered — never `yaml.dump`, which is the
    very round-trip this whole family exists to avoid). JSON's string grammar is a subset of YAML's
    double-quoted style, so `json.dumps` is an exact, escape-correct renderer here."""
    import json
    return json.dumps(s, ensure_ascii=False)


def _parse_theme_spec(raw: str) -> dict:
    """Parse ONE `--declare-theme` flag value into a SPEC-0093 rule-12 theme entry.

        SLUG:CADENCE:view=<graph-query-lens>
        SLUG:CADENCE:sweep=<surfaces>|<check>[|<check>...][|against=<x>]

    Every refusal is a WRITE-TIME gate (the `_adopt_extensions` precedent — refuse a malformed cite at
    write time, never let the fail-closed carrier sweep discover it later). The shape enforced here is
    exactly the one `_hook_inspection` validates, so a theme this verb writes always passes that sweep."""
    import re
    import sys

    def _fail(msg: str) -> None:
        print(f"yitc-v2: init --declare-theme: {msg}", file=sys.stderr)
        raise SystemExit(1)

    parts = (raw or "").split(":", 2)
    if len(parts) != 3:
        _fail(f"{raw!r} is not SLUG:CADENCE:PROBE — e.g. "
              "`ui-drift:monthly:view=ui-surfaces` or "
              "`secret-leak:weekly:sweep=bin/**|no plaintext secret|no .env committed`")
    slug, cadence, probe_spec = (p.strip() for p in parts)
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", slug):
        _fail(f"{slug!r} is not a theme slug (lowercase alphanumeric + dashes, e.g. `ui-drift`).")
    if cadence not in _THEME_CADENCES:
        _fail(f"cadence {cadence!r} must be one of {'|'.join(_THEME_CADENCES)} (SPEC-0093 rule 12).")

    if probe_spec.startswith("view="):
        lens = probe_spec[len("view="):].strip()
        if not lens:
            _fail("`view=` needs a non-empty `graph query <view>` lens name (SPEC-0093 rule 12).")
        probe = {"view": lens}
    elif probe_spec.startswith("sweep="):
        segs = [s.strip() for s in probe_spec[len("sweep="):].split("|")]
        surfaces, checks, against = (segs[0] if segs else ""), [], None
        for seg in segs[1:]:
            if seg.startswith("against="):
                against = seg[len("against="):].strip()
                if not against:
                    _fail("`against=` is present but empty (SPEC-0093 rule 12 — a non-empty string).")
            elif seg:
                checks.append(seg)
        if not surfaces:
            _fail("`sweep=` needs a non-empty `surfaces` glob first — "
                  "`sweep=<surfaces>|<check>[|<check>...]` (SPEC-0093 rule 12).")
        if not checks:
            _fail("`sweep=` needs at least one non-empty `check` after the surfaces — "
                  "`sweep=<surfaces>|<check>[|<check>...]` (SPEC-0093 rule 12).")
        sweep: dict = {"surfaces": surfaces, "checks": checks}
        if against:
            sweep["against"] = against
        probe = {"sweep": sweep}
    else:
        # BOTH kinds together is a rule-12 contradiction and NEITHER is fail-closed — the flag grammar
        # makes both unrepresentable by construction (exactly one `view=`/`sweep=` prefix per value).
        _fail(f"probe {probe_spec!r} must declare EXACTLY ONE KIND — `view=<lens>` OR "
              "`sweep=<surfaces>|<check>...` (SPEC-0093 rule 12).")
    return {"theme": slug, "probe": probe, "cadence": cadence}


_THEME_ITEM_INDENT = 2   # the ONE list-item indent this family renders theme entries at (T-12064
                         # reads it back to refuse splicing a rendered entry over a differently
                         # indented one — see `_replace_theme_entry`).


def _render_theme_entry(entry: dict) -> str:
    """Render ONE rule-12 theme as a YAML block-seq item at the section-key indent (hand-rendered TEXT —
    the whole point of this family is that no part of the carrier ever goes through a yaml round-trip)."""
    probe = entry["probe"]
    out = [f"{' ' * _THEME_ITEM_INDENT}- theme: {entry['theme']}\n"]
    if entry.get("owner"):                               # kernel-owned entries only (T-12053); a
        out.append(f"    owner: {entry['owner']}\n")     # project theme carries none and renders as before
    out.append("    probe:\n")
    if "view" in probe:
        out.append(f"      view: {_yaml_scalar(probe['view'])}\n")
    else:
        sweep = probe["sweep"]
        out.append("      sweep:\n")
        out.append(f"        surfaces: {_yaml_scalar(sweep['surfaces'])}\n")
        out.append("        checks:\n")
        out.extend(f"          - {_yaml_scalar(c)}\n" for c in sweep["checks"])
        if sweep.get("against"):
            out.append(f"        against: {_yaml_scalar(sweep['against'])}\n")
    out.append(f"    cadence: {entry['cadence']}\n")
    return "".join(out)


def _append_theme_entries(text: str, entries: list, *, retire_waiver: bool = True) -> str:
    """Append rule-12 theme entries under `inspection.themes`, preserving the carrier's comments +
    formatting (TEXT edit, NOT a yaml round-trip — the `_append_adopts_entries` shape, same rationale).

    Two carrier shapes, because the BORN carrier declares NO `themes:` key at all — it ships
    `inspection: {waiver: {reason: …}}`. So:
      (a) `themes:` already present — append after its last item (converting the inline `themes: []`
          form to a block list, exactly as `_append_adopts_entries` does for `adopts: []`);
      (b) no `themes:` — insert `themes:` + the items, at the `waiver:` position when there is one.
    In BOTH arms every COMMENT line is preserved — including any comment sitting INSIDE a retired
    waiver block, which is re-emitted above the new `themes:` key rather than dropped. Comment
    preservation is this verb's entire reason to exist (X-0401); it must not leak a single line.

    `retire_waiver` (T-12053) — WHO the appended themes belong to decides the waiver's fate, because
    the rule-12 XOR is now REFINED rather than absolute: a project `waiver:` covers only PROJECT-OWN
    themes, and the ONE kernel-owned seeded entry sits OUTSIDE it.
      * True (default — PROJECT-OWN themes, `--declare-theme`): the project has now DECLARED, so its
        waiver would be the rule-12 contradiction — RETIRE it (the pre-T-12053 behaviour, unchanged).
        It is retired in BOTH arms now, not just (b): a carrier can reach arm (a) already carrying the
        kernel entry beside its born waiver, and leaving that waiver standing beneath a project-own
        theme would author exactly the contradiction the sweep refuses.
      * False (the KERNEL-owned seed): the waiver is the project's stance on its OWN themes and is
        untouched — the seeded entry is inserted ABOVE it, both keys coexisting legitimately."""
    import re
    lines = text.splitlines(keepends=True)
    new_items = "".join(_render_theme_entry(e) for e in entries)

    insp_idx = next((i for i, ln in enumerate(lines)
                     if re.match(r"^inspection:\s*(#.*)?$", ln)), None)
    if insp_idx is None:                                 # defensive — init normally seeds the section
        block = "inspection:\n  themes:\n" + new_items
        sep = "" if (not text) or text.endswith("\n") else "\n"
        return text + sep + block

    # the section runs until the next column-0 key (or EOF)
    end_idx = len(lines)
    themes_idx = waiver_idx = None
    for j in range(insp_idx + 1, len(lines)):
        if re.match(r"^[A-Za-z_][\w-]*:", lines[j]) and not lines[j][:1].isspace():
            end_idx = j
            break
        if themes_idx is None and re.match(r"^\s+themes:", lines[j]):     # NOT a `  # themes:` comment
            themes_idx = j
        if waiver_idx is None and re.match(r"^\s+waiver:", lines[j]):
            waiver_idx = j

    if themes_idx is not None:                           # (a) grow the existing list
        m_inline = re.match(r"^(\s*)themes:\s*\[\s*\]\s*$", lines[themes_idx])
        if m_inline:                                     # `themes: []` → block list
            replacement = f"{m_inline.group(1)}themes:\n" + new_items
            out = lines[:themes_idx] + [replacement] + lines[themes_idx + 1:]
        else:
            insert_at = themes_idx + 1                   # block form → after the last contiguous item
            for k in range(themes_idx + 1, end_idx):
                if re.match(r"^\s*-\s", lines[k]) or re.match(r"^\s{4,}", lines[k]):
                    insert_at = k + 1                    # a list item, or one of its nested child lines
                elif lines[k].strip() == "" or lines[k].lstrip().startswith("#"):
                    continue
                else:
                    break
            out = lines[:insert_at] + [new_items] + lines[insert_at:]
        if not (retire_waiver and waiver_idx is not None):
            return "".join(out)
        # A project-own declaration beside a still-standing waiver IS the rule-12 contradiction — retire
        # it here too (T-12053). Re-locate the waiver in `out`: the insertion above shifted the indices.
        return _retire_waiver_text("".join(out))

    if waiver_idx is None:                               # neither key — append at the section's end
        return "".join(lines[:end_idx]) + "  themes:\n" + new_items + "".join(lines[end_idx:])

    # (b) insert `themes:` at the waiver's position. RETIRE the waiver (dropping its key line + its
    # deeper-indented NON-comment children) only when these entries are the project's OWN; a
    # kernel-owned seed leaves the project's waiver standing beside it (`retire_waiver=False`).
    if not retire_waiver:
        return "".join(lines[:waiver_idx]) + "  themes:\n" + new_items + "".join(lines[waiver_idx:])
    return _retire_waiver_text(
        "".join(lines[:waiver_idx]) + "  themes:\n" + new_items + "".join(lines[waiver_idx:]))


def _retire_waiver_text(text: str) -> str:
    """Drop the `inspection.waiver:` block (its key line + deeper-indented NON-comment children),
    preserving every comment line inside it by re-emitting it in the block's place. Split out of
    `_append_theme_entries` arm (b) so arm (a) can retire a waiver too (T-12053) without duplicating
    the span logic. A section with no `waiver:` is returned unchanged."""
    import re
    lines = text.splitlines(keepends=True)
    insp_idx = next((i for i, ln in enumerate(lines)
                     if re.match(r"^inspection:\s*(#.*)?$", ln)), None)
    if insp_idx is None:
        return text
    end_idx = len(lines)
    waiver_idx = None
    for j in range(insp_idx + 1, len(lines)):
        if re.match(r"^[A-Za-z_][\w-]*:", lines[j]) and not lines[j][:1].isspace():
            end_idx = j
            break
        if waiver_idx is None and re.match(r"^\s+waiver:", lines[j]):
            waiver_idx = j
    if waiver_idx is None:
        return text
    w_indent = len(lines[waiver_idx]) - len(lines[waiver_idx].lstrip())
    kept_comments: list = []
    drop_end = waiver_idx + 1
    for k in range(waiver_idx + 1, end_idx):
        ln = lines[k]
        if ln.strip() == "":
            break
        if (len(ln) - len(ln.lstrip())) <= w_indent:
            break
        if ln.lstrip().startswith("#"):
            kept_comments.append(ln)
        drop_end = k + 1
    return "".join(lines[:waiver_idx]) + "".join(kept_comments) + "".join(lines[drop_end:])


def _theme_probe_signature(entry: dict) -> tuple:
    """The comparable (probe, cadence) signature of ONE theme entry — the thing T-12064 compares to
    decide UPDATE vs total no-op.

    It normalises BOTH shapes to the same tuple: an entry as `state.load_ops_str` parsed it out of the
    carrier, and an entry as `_parse_theme_spec` just built it from a `--declare-theme` flag. That
    symmetry is the whole point — an IDENTICAL re-declare must compare EQUAL, so it writes nothing and
    the carrier stays byte-identical (the AC1 differential). Missing/empty keys normalise to `""`
    rather than raising, because this reads a carrier a human may have hand-written.

    `owner:` is deliberately NOT part of the signature: it is not something a declaration can express
    (the flag grammar has no owner field), so a difference there is never a reason to rewrite — it is
    carried forward by `_merge_theme_update` instead."""
    probe = entry.get("probe") if isinstance(entry.get("probe"), dict) else {}
    if "view" in probe:
        shape: tuple = ("view", str(probe.get("view") or "").strip())
    else:
        sweep = probe.get("sweep") if isinstance(probe.get("sweep"), dict) else {}
        checks = sweep.get("checks") if isinstance(sweep.get("checks"), list) else []
        shape = ("sweep",
                 str(sweep.get("surfaces") or "").strip(),
                 tuple(str(c).strip() for c in checks),
                 str(sweep.get("against") or "").strip())
    return (shape, str(entry.get("cadence") or "").strip())


def _merge_theme_update(cur: dict, new: dict, fail) -> dict:
    """Merge a re-declaration (`new`, from `_parse_theme_spec`) onto the entry already in the carrier
    (`cur`, as parsed) — returning the entry to WRITE. T-12064.

    KERNEL-OWNED ENTRIES ARE THE WHOLE DIFFICULTY, and SPEC-0160 rule 12 draws the line for us. A
    project MAY narrow the kernel entry's `surfaces:`/`checks:` (T-12053 scope) — that is exactly the
    X-1262 correction this verb now serves. It may NOT, through a declaration, change what
    `_kernel_theme_violations` pins: `owner:`, the `sweep:` probe KIND, `sweep.against`, `cadence`.
    Writing any of those would AUTHOR a carrier the fail-closed rule-12 sweep then REFUSES — the verb
    would hand the operator a broken carrier and call it an update.

    So a declaration that would change one of them is REFUSED BY NAME, never silently dropped. The
    silent drop is the alternative worth naming: the flag grammar cannot express `owner`, so a merge
    that just ignored the mismatch would quietly discard half of what the operator typed — the same
    class of loss the mixed-flag guard in `_declare_theme_only` already fails closed on.

    THE FAIL-CLOSED BELT ON THIS CARRY-FORWARD LIVES AT THE WRITER, not here — deliberately. A
    re-check placed after the line above could never fire (that line has just set the owner), so it
    would be dead code masquerading as a guard. `_replace_theme_entry` checks the entry it is about
    to RENDER against the span it is about to REPLACE, which is the only place the check can catch a
    de-owning rewrite arriving by any route."""
    merged = dict(new)
    owner = str(cur.get("owner") or "").strip()
    if owner:
        sig_cur, sig_new = _theme_probe_signature(cur), _theme_probe_signature(new)
        pinned = []
        if sig_new[1] != sig_cur[1]:
            pinned.append(f"cadence ({sig_cur[1]!r} -> {sig_new[1]!r})")
        if sig_new[0][0] != sig_cur[0][0]:
            pinned.append(f"probe kind ({sig_cur[0][0]} -> {sig_new[0][0]})")
        elif sig_new[0][0] == "sweep" and sig_new[0][3] != sig_cur[0][3]:
            pinned.append(f"sweep.against ({sig_cur[0][3]!r} -> {sig_new[0][3]!r})")
        if pinned:
            fail(f"init --declare-theme: `{cur.get('theme')}` is the OWNER-{owner.upper()} entry — a "
                 f"declaration may narrow its `surfaces:`/`checks:`, but not " + ", ".join(pinned)
                 + f". Those are pinned by SPEC-0160 rule 12, and a carrier carrying any other value "
                   f"is REFUSED by the fail-closed inspection sweep. Re-declare with the pinned "
                   f"values, or change nothing.")
        merged["owner"] = owner
    return merged


def _replace_theme_entry(text: str, slug: str, entry: dict, fail=None):
    """Rewrite the `- theme: <slug>` item IN PLACE with `entry`, preserving every comment byte. T-12064.

    THE SAME TEXT DISCIPLINE AS THE REST OF THIS FAMILY: line surgery over the located span, never a
    yaml round-trip (which gutted 436 comment lines in X-0401). It reuses the T-12059 span locator
    `_theme_entry_span` rather than re-deriving the item's extent.

    Comments sitting INSIDE the replaced span are re-emitted ABOVE the rewritten entry — the
    `_retire_waiver_text` `kept_comments` precedent, for the same reason: a comment the project wrote
    about this theme must survive an edit that rewrites the lines around it. The span deliberately
    excludes trailing comments below the last child, so a comment belonging to the NEXT entry is never
    dragged upward.

    THE OWNER BELT (SPEC-0160 rule 12). This is the ONE seam every in-place rewrite passes through,
    so it is where the de-owning check belongs: if the span being replaced carries an `owner:` child
    and the entry about to be rendered does not, `fail` is called rather than the entry written.
    Dropping the owner does not make the kernel-owned entry the project's to remove — it is the
    tampering shape `_kernel_theme_violations` reports and `_upgrade_kernel_theme` refuses to repair,
    and authoring it here would be this verb producing a carrier its own sweep then refuses.

    Returns the new text, or None when the entry is present to the parser but NOT addressable as TEXT
    (an inline/flow mapping, say). None means «left untouched» — the caller drops it from the updated
    set, so the verb never reports an update it did not make."""
    import re
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(r"^inspection:\s*(#.*)?$", ln)), None)
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^[A-Za-z_][\w-]*:", lines[j]) and not lines[j][:1].isspace():
            end = j
            break
    span = _theme_entry_span(lines, start, end, slug)
    if span is None:
        return None
    item, span_end, item_indent, _child_indent = span
    if item_indent != _THEME_ITEM_INDENT:
        # `_render_theme_entry` writes at ONE fixed indent (the shape `_append_theme_entries` appends
        # at). Splicing it over an item a carrier indented differently would re-indent that item alone
        # and could break the list. Fail-closed: leave it untouched rather than write a carrier this
        # family cannot render — same posture as the not-addressable-as-TEXT return above.
        return None
    span_owner = next((ln for ln in lines[item:span_end]
                       if re.match(r"^\s+owner:", ln) and not ln.lstrip().startswith("#")), None)
    if span_owner is not None and not str(entry.get("owner") or "").strip():
        msg = (f"init --declare-theme: refusing to rewrite `{slug}` without its "
               f"`{span_owner.strip()}` — dropping the owner does not make the entry the project's "
               f"to remove (SPEC-0160 rule 12, no opt-out).")
        if fail is None:
            raise SystemExit(msg)                        # no seam given — still fail closed, never write
        fail(msg)
    kept_comments = [ln for ln in lines[item:span_end] if ln.lstrip().startswith("#")]
    return ("".join(lines[:item]) + "".join(kept_comments) + _render_theme_entry(entry)
            + "".join(lines[span_end:]))


def _declare_themes(ops_path, raws: list, write_text_atomic, *, repo_root=None,
                    updated_out: list = None) -> list:
    """SPEC-0093 rule 12 — the GOVERNED declare path behind `init --declare-theme SLUG:CADENCE:PROBE`.
    Parses + validates each theme at WRITE time, idempotently appends the ones not already declared
    (preserving every comment byte), and MIRRORS the resulting adoption stance. Returns the theme slugs
    NEWLY declared (empty when all were already present / none asked).

    UPDATE-IN-PLACE (T-12064, X-1262 second half). A re-declare of an ALREADY-DECLARED slug whose probe
    (surfaces / checks / against / cadence) DIFFERS rewrites that entry IN PLACE instead of the
    by-slug no-op it used to be. MEASURED on aiseller: a theme declared with a wrong `surfaces:` could
    not be corrected by ANY verb — the re-declare printed «already declared — no-op» and the only fix
    left was a hand-edit of the governed carrier, exactly the off-verb write AGENTS §Verb-execution
    discipline exists to prevent. This is the SAME verb, one branch wider — no new verb, no new flag
    (CHARTER §P1 F1: extend the verb that is already «before X»).

    AN IDENTICAL RE-DECLARE IS STILL A TOTAL NO-OP: the update fires on a DIFFERING signature
    (`_theme_probe_signature`), never on presence, so a repeat run writes nothing, leaves the carrier
    byte-identical and journals nothing — the idempotence every caller of this verb already relies on.

    `updated_out` (keyword-only, optional) collects the slugs UPDATED this run. It is an accumulator
    rather than a second return value ON PURPOSE: this function's `-> list` of NEWLY-DECLARED slugs is
    asserted by equality across the sibling suites (test_t10535_declare_theme_comment_preserving), so
    widening the return would break callers that have nothing to do with the update. A caller that
    passes nothing keeps today's behaviour exactly.

    THE STANCE MIRROR IS LOAD-BEARING, not tidiness: the born carrier WAIVES `inspection:` and its born
    adoption record reads `waive@init`. Declaring a theme makes the section DECLARED, so that record
    would now DENY a mechanism the project actively runs — precisely the `_adoption_stance_violations`
    ERROR arm (T-10415 / X-0088), which fails the carrier sweep CLOSED. Writing a declaration without
    re-recording the stance would therefore leave the consumer's carrier refusing its own init. Same act,
    same fix as `_adopt_extensions` does for `extensions` (identical regex re-record).

    `repo_root` (T-12063, X-1262) is the CHECKOUT the declared surfaces are expanded against for the
    report-only zero-match WARN below. It is PASSED, never derived from `ops_path.parent`: under
    `init --dry-run` this function is handed a SCRATCH OVERLAY COPY of the carrier (see the call
    site's own docstring), whose parent directory holds no project files at all — so deriving the root
    from the path would WARN `matched: 0` on every dry-run declaration, including correct ones. It
    defaults None, and the check is SKIPPED entirely when absent, so a caller that has no root simply
    keeps today's behaviour.

    Self-contained (inline re/yaml/SystemExit; `write_text_atomic` passed by the caller) so `cmd_init`'s
    injected-deps contract stays byte-identical — the `_adopt_concerns` / `_adopt_extensions` precedent."""
    import re
    import sys

    import yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader
    if not raws:
        return []

    def _fail(msg: str) -> None:
        print(f"yitc-v2: {msg}", file=sys.stderr)
        raise SystemExit(1)

    if not ops_path.exists():
        _fail(f"init --declare-theme: {CONSUMER_OPS_CONTRACT} not found — cannot declare a theme in a "
              "missing carrier. Run a bare `init` first.")
    entries = [_parse_theme_spec(r) for r in raws]       # write-time validation (refuses before any write)

    text = ops_path.read_text(encoding="utf-8")
    try:
        ops = state.load_ops_str(text) if text.strip() else None
    except yaml.YAMLError as e:
        _fail(f"init --declare-theme: {CONSUMER_OPS_CONTRACT} failed to parse ({e}); re-run init to re-seed it.")
    # slug -> the entry AS DECLARED (not just the slug set it used to be): the update branch below
    # has to compare probes and carry `owner:` forward, and both need the whole entry (T-12064).
    existing: dict = {}
    if isinstance(ops, dict) and isinstance(ops.get("inspection"), dict):
        cur = ops["inspection"].get("themes")
        if isinstance(cur, list):
            existing = {str((x or {}).get("theme")).strip(): x for x in cur if isinstance(x, dict)}
    # DEDUP against what is already declared AND within this single invocation (a repeated
    # `--declare-theme x:... --declare-theme x:...` must not append twice), preserving order.
    seen: set = set()
    to_add: list = []
    to_update: list = []
    for e in entries:
        slug = e["theme"]
        if slug in seen:
            continue
        seen.add(slug)
        if slug not in existing:
            to_add.append(e)
        elif _theme_probe_signature(existing[slug]) != _theme_probe_signature(e):
            to_update.append(_merge_theme_update(existing[slug], e, _fail))
    if not to_add and not to_update:
        return []                                        # nothing new, nothing differs — byte-stable

    # T-12063 (X-1262) — REPORT-ONLY zero-match WARN, at the one moment the author is still here.
    # A `sweep=` declaration whose `surfaces:` glob matches NOTHING is well-formed, so every gate
    # above accepts it; what it produces is a run that records matched 0 / surfaces_bytes 0 forever.
    # Catching it HERE costs one glob expansion against the checkout the theme will actually sweep,
    # and it is caught while the person who typed the glob can still read their own typo. NOT a new
    # refusal: the declaration is written exactly as before and the return value is unchanged
    # (SPEC-0057 §2 — an inspection surface reports, it does not block). The recorded half of the
    # same defence is the `semaphore_counted` marker on the run itself.
    if repo_root is not None:
        from lib import inspection      # function-local, like this file's `state`/`debt`/`deploy`
        for e in to_add + to_update:    # reaches — init.py's MODULE import boundary stays stdlib-only
            # BOTH sets, deliberately (T-12064): a CORRECTED glob that still matches nothing is the
            # very mistake this WARN exists to catch, and the update path is where a correction
            # arrives. Report-only on both, exactly as on the append.
            sweep = (e.get("probe") or {}).get("sweep")
            if inspection.sweep_matched_zero(repo_root, sweep):
                print(f"yitc-v2: WARN init --declare-theme {e['theme']}: `surfaces: "
                      f"{sweep.get('surfaces')}` matched: 0 files in {repo_root} — the theme IS "
                      f"declared, but a sweep over it inspects NOTHING: every `inspect record` run "
                      f"would record 0 bytes and would NOT count as a review (the subject stays "
                      f"DUE, T-12063/X-1262). Check the glob against this checkout.", file=sys.stderr)

    new_text = _append_theme_entries(text, to_add) if to_add else text
    updated: list = []
    for e in to_update:                                  # in-place rewrites, after any append
        replaced = _replace_theme_entry(new_text, e["theme"], e, _fail)
        if replaced is None:
            continue                                     # not addressable as TEXT — left untouched,
        new_text = replaced                              # and NOT reported as updated
        updated.append(e["theme"])
    if new_text == text:
        return []                                        # every update was declined — no write, no event
    new_text = re.sub(r"(- concern: inspection\n(?:    [^\n]*\n)*?    status: )(?:waive|na)\b",
                      r"\1adopt", new_text, count=1)
    write_text_atomic(ops_path, new_text)
    if updated_out is not None:
        updated_out.extend(updated)
    return [e["theme"] for e in to_add]


def _kernel_theme_previously_seeded(repo_root) -> bool:
    """Has THIS repo's `repeated-work` baseline already been seeded, per its OWN journal? (T-12053)

    The durable previously-stamped marker. `_seed_kernel_theme` records `themes_declared:
    [repeated-work]` and `_upgrade_kernel_theme` records `themes_upgraded: [repeated-work]` on the
    `consumer_init` event they trigger, and the journal is append-only — so the
    row survives every later edit of the carrier, which is exactly the property the carrier itself
    cannot offer (a deleted entry leaves no trace in the file).

    WHY NOT THE ADOPTION RECORD (rejected at Execution — the reason is worth keeping): the
    `concern: inspection` stance reading `adopt` was the first candidate, and it is a sound
    previously-seeded proof for a carrier that was born WAIVED. It is UNSOUND in general: a project
    that already declares themes of its OWN (the boomrocket shape) reads `adopt` because of ITS OWN
    declaration, so the stance would refuse to seed the baseline into precisely the consumers that
    already use the section. The journal row means one thing only — the kernel seeded this repo.

    Segment-aware (SPEC-0190 rule 4): the journal is ONE logical history across bounded physical
    segments, so a raw read of the live path alone would answer "never seeded" for a repo whose seed
    row has since rotated into an archive segment — a false-eligible that re-seeds a tampered carrier.
    FAIL-CLOSED on an unreadable journal: `True` (treat as already seeded), because declining to seed
    is recoverable by a re-run while a wrongly-permitted re-seed silently repairs tampering."""
    import json
    from pathlib import Path

    from lib import journal as journal_mod   # the INSTRUMENTED segment-streaming primitive
    # Deferred imports, per this module's header rationale: importing `init` must stay dependency-free.
    # SPEC-0190-VERDICT: segment-aware — the question here is NOT live-segment presence: it is "has this
    # repo EVER been seeded?", and by rule 1 an archive segment IS this journal, so a seed row that has
    # since rotated out of the live segment still answers YES. A live-only read would report `never
    # seeded` for an old consumer and re-seed a tampered carrier. Read through `journal.segment_lines`,
    # the instrumented streaming primitive (T-12034): it folds the whole logical journal segment by
    # segment WITHOUT materialising one, so this reader adds no raw scan of its own.
    journal = Path(repo_root) / "events.jsonl"
    try:
        for line in journal_mod.segment_lines(journal, errors="replace"):
            if _KERNEL_THEME_SLUG not in line:
                continue                                 # cheap pre-filter before the json parse
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            data = (row or {}).get("data") or {}
            # EITHER stamp counts (T-12059): a SEED and an in-place UPGRADE both mean the same thing —
            # the kernel has stamped THIS repo's entry — so an upgraded carrier whose `owner: kernel` is
            # later stripped reads as tampering and stays the sweep's fail-closed ERROR, exactly as a
            # seeded one does. Reading only `themes_declared` would have reopened the no-opt-out hole
            # for every consumer that arrived through the upgrade branch.
            if _KERNEL_THEME_SLUG in ((data.get("themes_declared") or [])
                                      + (data.get("themes_upgraded") or [])):
                return True
    except OSError:
        return True                                      # fail-closed: unreadable == treat as seeded
    return False


def _kernel_theme_seed_eligible(ops: dict, section_text: str, previously_seeded: bool,
                                fresh_section: bool = False) -> bool:
    """Is this carrier's `inspection:` section in the NEVER-SEEDED state (T-12053)?

    SEEDING AND TAMPER-REPAIR MUST NOT BE THE SAME ACT. `init` seeds BEFORE the fail-closed sweep, so a
    seeder that healed every entry-absent carrier would make the no-opt-out ERROR unreachable by
    construction — the carrier would be silently repaired a moment before the sweep could refuse it, and
    "no opt-out" would mean nothing. This is the `_seed_catalog_waives` discipline (seed a never-answered
    section; NEVER backfill a present one, which stays the sweep's fail-closed concern), applied to the
    one kernel-owned entry.

    BOTH conjuncts must hold (fail-closed — any doubt reads as already-seeded):
      1. the slug appears NOWHERE in the section TEXT. That single test covers three states at once: the
         entry already declared (an idempotent re-run), the entry present but DE-OWNED, and the entry
         WRAPPED IN THE WAIVER — none of which is a first seed.
      2. the section is NEW: either this repo's own journal records no prior seed
         (`_kernel_theme_previously_seeded` — the durable marker for the one state the carrier text
         cannot show, an entry seeded and then DELETED) OR `fresh_section` — the carrier was BORN this
         run, or its `inspection:` section was just PULLED born-waived by the rule-11 carrier update.
         A freshly born section has no history to tamper with, so the journal marker does not speak to
         it; this is the `_seed_catalog_waives` fresh-carrier arm, for the same reason and on the same
         absent-vs-present boundary. It does NOT reopen the no-opt-out hole: DELETING the entry leaves
         the `inspection:` section itself PRESENT, so nothing is pulled, nothing is fresh, and the
         carrier is refused exactly as before.

    Deliberately NOT conditioned on the section being waived or on a `themes:` key: a carrier that
    already declares themes of its OWN has simply never been seeded, and it is as much the directive's
    rollout target as a born-waived one."""
    if previously_seeded and not fresh_section:
        return False
    return _KERNEL_THEME_SLUG not in section_text


def _inspection_section_text(text: str) -> str:
    """The raw `inspection:` section slice of a carrier (key line through the next column-0 key), or ""
    when the section is absent. TEXT, deliberately: conjunct 1 above must see the slug ANYWHERE in the
    section — including inside a waiver mapping or a comment — which a parsed view of `themes[]` alone
    would miss. Reading a comment as "present" is the fail-CLOSED direction (it declines to seed)."""
    import re
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(r"^inspection:\s*(#.*)?$", ln)), None)
    if start is None:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^[A-Za-z_][\w-]*:", lines[j]) and not lines[j][:1].isspace():
            end = j
            break
    return "".join(lines[start:end])


def _seed_kernel_theme(ops_path, write_text_atomic, *, previously_seeded: bool,
                       fresh_section: bool = False) -> list:
    """SPEC-0160 rule 12 (T-12053) — SEED the ONE kernel-owned `repeated-work` sweep theme into a
    consumer's `inspection.themes[]`, on the owner directive that it is a BASELINE mechanism in every
    consumer (no opt-out). Shaped on `_seed_catalog_waives`: it seeds a never-seeded section and NEVER
    backfills a tampered one (`_kernel_theme_seed_eligible` — read its docstring, the eligibility IS the
    no-opt-out guarantee). Returns the slugs seeded ([] = not eligible / already present ⇒ a byte-stable
    no-op re-run, no write and no event).

    UNLIKE `_seed_catalog_waives` there is NO `fresh_carrier` gate: the born-WAIVED carrier every
    EXISTING consumer holds today — and the carrier of a consumer that already declares themes of its
    OWN — are precisely the directive's rollout targets, and both are never-seeded by the conjuncts above.

    The append is a surgical TEXT edit through the T-10535 family, so every comment byte of the carrier
    survives (X-0401 — the kernel contract for this file is delivered THROUGH its comments), and it
    passes `retire_waiver=False`: the project's `waiver:` is its stance on its OWN themes and the
    kernel-owned entry sits outside it, so both keys legitimately coexist (the refined rule-12 XOR).

    THE STANCE MIRROR IS LOAD-BEARING, exactly as in `_declare_themes`: the section becomes DECLARED, so
    a born `waive@init` adoption record would then DENY a mechanism the project runs — the
    `_adoption_stance_violations` ERROR arm (T-10415 / X-0088), which fails the carrier sweep CLOSED."""
    import yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader
    if not ops_path.exists():
        return []
    text = ops_path.read_text(encoding="utf-8")
    try:
        ops = state.load_ops_str(text) if text.strip() else None
    except yaml.YAMLError:
        return []                                        # malformed carrier — the sweep reports it; don't seed blind
    if not isinstance(ops, dict):
        return []
    section_text = _inspection_section_text(text)
    if not _kernel_theme_seed_eligible(ops, section_text, previously_seeded, fresh_section):
        # NOTHING TO APPEND — but say so TRUTHFULLY when this very run is what delivered the entry. A
        # carrier BORN this run (or one whose `inspection:` section was just PULLED) already carries the
        # entry from the BORN TEMPLATE, so there was nothing left to append; it is still THIS init that
        # seeded it, and the seed fact must reach the journal either way. Without this the marker is
        # blind to every FRESH consumer: its first init would record nothing, so a later DELETION of the
        # entry would read as never-seeded and be silently re-seeded — the no-opt-out guarantee would
        # hold only for consumers older than this change.
        if fresh_section and _KERNEL_THEME_SLUG in section_text:
            return [_KERNEL_THEME_SLUG]
        return []
    import re
    new_text = _append_theme_entries(text, [_kernel_seeded_theme()], retire_waiver=False)
    new_text = re.sub(r"(- concern: inspection\n(?:    [^\n]*\n)*?    status: )(?:waive|na)\b",
                      r"\1adopt", new_text, count=1)
    write_text_atomic(ops_path, new_text)
    return [_KERNEL_THEME_SLUG]


def _theme_entry_span(lines: list, start: int, end: int, slug: str = None):
    """Locate the `- theme: <slug>` list item inside `lines[start:end]` (the `inspection:` section
    slice). Returns `(item_idx, last_child_idx + 1, item_indent, child_indent)`, or None when absent.

    `slug` defaults to the kernel-owned entry — the ONE caller this locator was born for
    (`_upgrade_kernel_theme`, T-12059). It is a PARAMETER rather than a second locator because the
    T-12064 in-place UPDATE addresses an arbitrary declared theme by exactly the same span rules
    (CHARTER §P1 F1 — extend the existing analog; a second copy of this scan is what would drift).

    The span ends at the LAST substantive child line, deliberately: a trailing comment or blank line
    below the item belongs to whatever comes NEXT, and an insertion made after it would migrate the
    project's own comment onto the wrong entry. Comment preservation is this family's reason to exist
    (X-0401) — placing one wrongly is the same class of loss as dropping it."""
    import re
    slug = _KERNEL_THEME_SLUG if slug is None else slug
    item = item_indent = None
    for i in range(start, end):
        m = re.match(r"^(\s*)-\s+theme:\s*[\"\']?" + re.escape(slug) + r"[\"\']?\s*$",
                     lines[i])
        if m:
            item, item_indent = i, len(m.group(1))
            break
    if item is None:
        return None
    last, child_indent = item, None
    for j in range(item + 1, end):
        ln = lines[j]
        if ln.strip() == "" or ln.lstrip().startswith("#"):
            continue
        ind = len(ln) - len(ln.lstrip())
        if ind <= item_indent:
            break
        if child_indent is None:
            child_indent = ind
        last = j
    return item, last + 1, item_indent, (child_indent if child_indent is not None else item_indent + 2)


def _upgrade_kernel_theme(ops_path, write_text_atomic, *, previously_seeded: bool) -> list:
    """SPEC-0160 rule 12 (T-12059) — UPGRADE IN PLACE a `repeated-work` sweep theme a project declared
    BY HAND, so the consumer that adopted the lens EARLY is stamped kernel-owned rather than locked out.

    THE INCIDENT (rollout 2026-09-04, `repeated-work-seed-refuses-a-project-that-pre-declared-the-slug-
    without-owner-kernel`): aiseller had already answered the kernel cross by declaring its OWN
    `repeated-work` sweep — own surfaces, own check labels, `against:` the pattern, monthly — but with no
    `owner: kernel`. The T-12053 seeder correctly skips it (the slug is present, so it is not a
    never-seeded section) and the rule-12 sweep then REFUSES the carrier for the missing owner. Every
    consumer that seeded cleanly had done NOTHING; the one that acted early was the one `init` rejected.

    THE UPGRADE IS NOT A REPAIR — the distinction the no-opt-out guarantee rests on. It is admitted ONLY
    when this repo has never been stamped by the kernel (`previously_seeded` False, which now covers an
    upgrade as well as a seed — `_kernel_theme_previously_seeded`). An entry the kernel HAS stamped and
    someone later de-owned is TAMPERING, and stays the sweep's fail-closed ERROR: the `_seed_kernel_theme`
    seeding-is-not-tamper-repair discipline, applied to the second branch so it cannot be the hole in the
    first.

    THE SECOND ARM — RE-SEEDING A RETIRED KERNEL LITERAL (T-12062, cross X-1272/X-1271). The upgrade
    above is admitted only on a NEVER-STAMPED carrier, which is why it could not reach the consumers
    that took a BAD seed: the kernel's own `surfaces:` default matched ZERO files (pathlib `X/**`
    yields directories only), and it was seeded into three consumers before anyone measured it. Those
    carriers ARE stamped, so `previously_seeded` is True for exactly the case needing the fix. The arm
    is therefore admitted THROUGH that gate without opening it: when `previously_seeded`, the ONLY
    admitted edit is rewriting `surfaces:` on an entry that is BOTH `owner: kernel` AND byte-equal to a
    literal in `_KERNEL_THEME_SURFACES_RETIRED`; `owner:`/`against:`/`cadence:` stay refused there, so a
    de-owned or re-pointed entry remains the fail-closed sweep ERROR it is today. Byte-equality — not
    "differs from the current value" — is what keeps this a re-seed of the kernel's OWN retired bytes
    rather than an overwrite: an entry the project narrowed by hand fails it and is left untouched.

    THE ARM IS ADMITTED ON A NEVER-STAMPED CARRIER TOO, and that is deliberate — read it before
    "tightening" it to `previously_seeded` only. NEITHER conjunct of the arm's authority mentions the
    stamp: `owner: kernel` and byte-equality with a retired literal hold identically either way. What
    the stamp gates is the OTHER three keys, in the block above. Gating the arm on it as well
    permanently misses a never-stamped carrier that is otherwise fully kernel-shaped (owner, against
    and cadence all already correct) but holds the retired literal: nothing there needs upgrading, so
    this returns [] and never stamps, so `previously_seeded` stays False forever and the arm never
    becomes admissible — while `_kernel_theme_violations` passes it, because the sweep does not inspect
    `surfaces:` at all. That carrier would keep a zero-match value permanently: X-1272/X-1271 re-created
    silently, in the one shape the published pattern example made plausible (a hand-copied entry).
    So the T-12059 guarantee is the NARROWER one, stated exactly: on a never-stamped carrier the
    owner/against/cadence upgrade is bit-for-bit unchanged, and the re-seed is ADDITIONAL.
    (audit-post RED 2026-09-04 -> `audit consult --on-demand` GREEN, single survivor.)

    WHAT IT WRITES: `owner: kernel`, plus `against:`/`cadence:` when they are absent or name something
    other than the kernel values, plus `surfaces:` on the re-seed arm just described. The project's own
    `surfaces:` and `checks:` are otherwise left BYTE-IDENTICAL — a project MAY narrow the default
    (T-12053 scope), and this branch exists to keep that work, not to overwrite it. The edit is line-surgical through this family's TEXT discipline, never a yaml
    round-trip, so every comment byte and the entry order survive (X-0401).

    WHAT IT REFUSES TO TOUCH: an entry carrying the slug whose probe is NOT a `sweep:` (a `view:` lens,
    say). Rewriting a project's probe into a different KIND is not an upgrade, it is a silent
    substitution — so this returns [] and the entry is refused BY NAME by `_kernel_theme_violations`,
    which already says the kernel entry is a `sweep:` probe. No second refusal path is added (CHARTER §P1).

    Returns the slugs upgraded ([] = nothing to do ⇒ a byte-stable no-op re-run, no write, no event)."""
    import re

    import yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader
    if not ops_path.exists():
        return []
    text = ops_path.read_text(encoding="utf-8")
    try:
        ops = state.load_ops_str(text) if text.strip() else None
    except yaml.YAMLError:
        return []                                        # malformed carrier — the sweep reports it
    if not isinstance(ops, dict):
        return []
    sec = ops.get("inspection")
    themes = sec.get("themes") if isinstance(sec, dict) else None
    entries = [x for x in themes if isinstance(x, dict)] if isinstance(themes, list) else []
    found = next((x for x in entries
                  if str(x.get("theme") or "").strip() == _KERNEL_THEME_SLUG), None)
    if found is None:
        return []                                        # nothing declared — that is the SEED's case
    probe = found.get("probe")
    sweep = probe.get("sweep") if isinstance(probe, dict) else None
    if not isinstance(sweep, dict):
        return []                                        # wrong SHAPE — refused by name, never rewritten
    needs_owner = str(found.get("owner") or "").strip() != _KERNEL_THEME_OWNER
    needs_against = str(sweep.get("against") or "").strip() != _KERNEL_THEME_AGAINST
    needs_cadence = str(found.get("cadence") or "").strip() != _KERNEL_THEME_CADENCE
    # T-12062 — the RE-SEED arm. BOTH conjuncts are load-bearing, and together they are what makes
    # this a re-seed rather than an overwrite: `owner: kernel` says the entry is the kernel's to
    # correct, and byte-equality with a RETIRED literal says the project never touched it. An entry a
    # project NARROWED fails the second conjunct and keeps its bytes.
    needs_surfaces = (str(found.get("owner") or "").strip() == _KERNEL_THEME_OWNER
                      and str(sweep.get("surfaces") or "").strip() in _KERNEL_THEME_SURFACES_RETIRED)
    if previously_seeded:
        # THE T-12059 DISCIPLINE, PRESERVED — not weakened, only narrowed to the one edit that needs
        # it. On a carrier this kernel HAS stamped, a missing/changed `owner:`, `against:` or
        # `cadence:` is TAMPERING and stays the fail-closed sweep ERROR; seeding is not tamper-repair.
        # The surfaces re-seed is admitted here precisely BECAUSE it is not a repair of someone's
        # edit: the value being replaced is one the kernel itself wrote and has since retired, which
        # is why the arm above tests byte-equality rather than merely "not the current value".
        needs_owner = needs_against = needs_cadence = False
    if not (needs_owner or needs_against or needs_cadence or needs_surfaces):
        return []                                        # already kernel-shaped — idempotent no-op

    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(r"^inspection:\s*(#.*)?$", ln)), None)
    if start is None:
        return []
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^[A-Za-z_][\w-]*:", lines[j]) and not lines[j][:1].isspace():
            end = j
            break
    span = _theme_entry_span(lines, start, end)
    if span is None:
        return []                                        # parsed present but not addressable as TEXT
    item, span_end, _item_indent, child_indent = span
    entry = lines[item:span_end]
    pad = " " * child_indent

    if needs_against or needs_surfaces:                  # INSIDE the sweep block — done first, so the
        sw = next((k for k, ln in enumerate(entry)       # direct-child edits below re-locate cleanly
                   if re.match(r"^\s+sweep:\s*$", ln)), None)
        if sw is None:
            return []
        sw_indent = len(entry[sw]) - len(entry[sw].lstrip())
        sw_last, sw_child = sw, None
        for k in range(sw + 1, len(entry)):
            ln = entry[k]
            if ln.strip() == "" or ln.lstrip().startswith("#"):
                continue
            ind = len(ln) - len(ln.lstrip())
            if ind <= sw_indent:
                break
            if sw_child is None:
                sw_child = ind
            sw_last = k
        sw_child = sw_child if sw_child is not None else sw_indent + 2
        # Both sweep-direct-child keys through ONE writer — no second line-surgery path (CHARTER §P1).
        for key, value, wanted in (("against", _KERNEL_THEME_AGAINST, needs_against),
                                   ("surfaces", _KERNEL_THEME_SURFACES, needs_surfaces)):
            if not wanted:
                continue
            line = f"{' ' * sw_child}{key}: {_yaml_scalar(value)}\n"
            at = next((k for k in range(sw + 1, sw_last + 1)
                       if re.match(r"^ {%d}%s:" % (sw_child, key), entry[k])), None)
            if at is None:
                entry.insert(sw_last + 1, line)
                sw_last += 1                             # keep the insertion point valid for the next
            else:
                entry[at] = line
    if needs_cadence:
        line = f"{pad}cadence: {_KERNEL_THEME_CADENCE}\n"
        at = next((k for k, ln in enumerate(entry) if re.match(r"^ {%d}cadence:" % child_indent, ln)),
                  None)
        if at is None:
            entry.append(line)
        else:
            entry[at] = line
    if needs_owner:                                      # stamped directly under `- theme:`, the shape
        line = f"{pad}owner: {_KERNEL_THEME_OWNER}\n"    # `_render_theme_entry` writes for a fresh seed
        at = next((k for k, ln in enumerate(entry) if re.match(r"^ {%d}owner:" % child_indent, ln)),
                  None)
        if at is None:
            entry.insert(1, line)
        else:
            entry[at] = line

    new_text = "".join(lines[:item]) + "".join(entry) + "".join(lines[span_end:])
    # THE STANCE MIRROR IS LOAD-BEARING, exactly as in `_seed_kernel_theme`: this entry is now a
    # kernel-owned mechanism the project runs, so a `waive@init` adoption record would DENY it — the
    # `_adoption_stance_violations` ERROR arm (T-10415 / X-0088) that fails the carrier sweep CLOSED.
    new_text = re.sub(r"(- concern: inspection\n(?:    [^\n]*\n)*?    status: )(?:waive|na)\b",
                      r"\1adopt", new_text, count=1)
    write_text_atomic(ops_path, new_text)
    return [_KERNEL_THEME_SLUG]


def _declare_theme_only(repo_root, args, *, _append_event, _run_git_cap, write_text_atomic,
                        ops_path=None, plan=None) -> None:
    """`init --declare-theme SLUG:CADENCE:PROBE` as a PURE carrier-write (the `_adopt_concern_only` shape).

    It takes the SAME early-return path as `--adopt-concern`, for the SAME reason (T-10265 / X-0251): the
    flag declares ONE job — append a theme to the carrier — and reaching it through the scaffold-delivering
    bare-init body would ALSO re-deliver every if-absent born scaffold, silently re-materializing files a
    consumer deliberately deleted (the X-0239 hazard). Scaffold delivery stays single-homed on the bare
    init path. (`--adopt-extension` rides that body; a theme declaration must not.)

    NOTHING-DECLARED = TOTAL NO-OP: an idempotent re-declare writes no file, emits NO event, makes no
    commit and leaves a clean tree — same emit-only-on-change shape as `_adopt_concern_only`."""
    import sys

    # FAIL-CLOSED on a mixed run — never SILENTLY drop a requested write. Every member of this family
    # has an early return of its own (`--adopt-extension` too, since T-11189) and only ONE of them can
    # run, so a combined invocation would honour one flag and discard the other. The ops are independent
    # and repeatable, so running them separately costs nothing.
    if getattr(args, "adopt_extension", None):
        print("yitc-v2: init --declare-theme cannot be combined with --adopt-extension — both are pure "
              "carrier writes with their own early-return path, so one would be silently dropped. Run them as two "
              "separate ops: `init --adopt-extension …`, then `init --declare-theme …`.", file=sys.stderr)
        raise SystemExit(1)
    # …and for `--backfill-mandatory` (T-10982): THIS early return runs before the backfill one, so a
    # combined invocation would silently drop the delivery. Same fail-closed rule, third member.
    if getattr(args, "backfill_mandatory", False):
        print("yitc-v2: init --declare-theme cannot be combined with --backfill-mandatory — both are "
              "pure carrier writes with their own early-return path, so one would be silently dropped. "
              "Run them as two separate ops: `init --backfill-mandatory`, then `init --declare-theme …`.",
              file=sys.stderr)
        raise SystemExit(1)

    # --dry-run SAFETY (why this single call is correct for BOTH modes, and writes nothing when previewing):
    # `cmd_init` has ALREADY swapped the mutation seams before this early return — under `--dry-run`,
    # `write_text_atomic` IS the plan's RECORDER and `ops_path` IS a SCRATCH overlay copy of the carrier.
    # So the op below runs UNCHANGED and its write lands on scratch, never on REPO_ROOT/yitc-ops.yaml (the
    # same contract `_adopt_concern_only` relies on — see its docstring). Pinned by test AC7, after an
    # audit-post reviewer read this call in isolation and reasonably mistook it for a real write.
    ops_path = ops_path if ops_path is not None else repo_root / CONSUMER_OPS_CONTRACT
    updated: list = []
    declared = _declare_themes(ops_path, args.declare_theme, write_text_atomic, repo_root=repo_root,
                               updated_out=updated)

    # T-12064: the no-op arm now tests BOTH outcomes. A re-declare that CHANGED a declared theme's
    # probe wrote the carrier, so reporting «already declared — no-op» there would deny a write that
    # happened. The arm still fires — byte-identically — for the identical re-declare it was written
    # for, which is the case that genuinely changed nothing.
    if not declared and not updated:
        prefix = "init --dry-run" if plan is not None else "consumer init"
        print(f"{prefix} ({repo_root.name}): inspection theme(s) already declared — no-op")
        if plan is not None:
            plan.cleanup()
        return

    if plan is not None:
        plan.render()
        plan.cleanup()
        return

    _append_event("consumer_init", None, {
        "path": str(repo_root),
        "mode": "declare-theme",      # the pure carrier-write run (no scaffold delivery)
        "created": [],                # by construction: this path delivers no scaffold
        "skipped": [],
        "themes_declared": declared,  # SPEC-0093 rule 12 — the inspection themes appended this run
        "themes_updated": updated,    # …and the already-declared ones REWRITTEN in place (T-12064)
    })

    # SCOPED COMMIT — the declaration reaches the consumer's own `main` via a GOVERNED commit, not a loose
    # dirty tree (the `_adopt_concern_only` posture), staging ONLY the carrier + the journal: never the
    # `managed` scaffold list, never `git add -A`. Off `main` it commits nothing and leaves the two paths
    # dirty for the next `land` to fold (D-0049).
    cur = _run_git_cap(["symbolic-ref", "--quiet", "--short", "HEAD"], repo_root)
    if cur.returncode == 0 and cur.stdout.strip() == "main":
        # SPEC-0190-VERDICT: segment-aware — this set is NOT a liveness/presence QUERY, it is the
        # pathspec list of a scoped `git add --`, so the question it asks is "which physical paths of
        # this consumer's journal must this commit carry?" and by rule 1 an archive segment IS that
        # journal. A rotated consumer would otherwise leave one uncommitted (the X-0274 wedge). The
        # `.exists()` filter is kept verbatim: `journal_pathspecs` returns the LIVE segment
        # unconditionally, so that filter still decides its fate, and the archives it adds are
        # glob-derived (present by construction).
        present = [p for p in (CONSUMER_OPS_CONTRACT,
                               *_journal_pathspecs(repo_root / "events.jsonl", repo_root))
                   if (repo_root / p).exists()]
        if present:
            _run_git_cap(["add", "--", *present], repo_root)
        if _run_git_cap(["diff", "--cached", "--quiet"], repo_root).returncode != 0:
            _run_git_cap(["commit", "-q", "-m", (
                "chore: declare/update inspection theme(s) (yitc-v2 init --declare-theme)\n\n"
                "Governed ops-carrier write — a SURGICAL TEXT append that preserves every existing byte,\n"
                "incl. the kernel contract delivered through the carrier's comments (never a YAML\n"
                "round-trip, which gutted 436 comment lines in X-0401). Stages the carrier + journal\n"
                "ONLY; delivers no scaffold (T-10535).\n\n"
                "from: SPEC-0093 rule 12 — the inspection themes[] declaration\n")],
                repo_root)

    parts = ([f"declared inspection theme(s) {', '.join(declared)}"] if declared else []) + \
            ([f"updated inspection theme(s) in place {', '.join(updated)}"] if updated else [])
    print(f"consumer init ({repo_root.name}): " + "; ".join(parts))


def _backfill_mandatory_only(repo_root, args, *, _append_event, _run_git_cap, write_text_atomic,
                             cli_form="bin/yitc-v2", ops_path=None, plan=None) -> None:
    """`init --backfill-mandatory` as a PURE carrier-write (the `_adopt_concern_only` shape) — T-10982.

    THE ONE JOB: deliver a top-level section that became MANDATORY after this consumer was init'ed,
    UNANSWERED, and EXIT. It is the third member of the pure-carrier-write family and takes the same
    early-return path for the same X-0251 reason (reaching it through the scaffold-delivering bare-init
    body would re-materialize files a consumer deliberately deleted) — PLUS a second, stronger reason
    unique to this mode: the bare-init body ENDS in the two fail-closed sweeps, and T-10688 rewinds
    every pre-sweep carrier delivery on refusal. An UNANSWERED section makes that sweep refuse BY
    CONSTRUCTION, so on the ordinary path this delivery would be rolled back before init exits — the
    measured finding that reshaped this card. Exiting BEFORE the sweeps is what makes it persist.

    DELIVERY-ONLY — NOT a second successful meaning of `init`. It seeds no scaffold, runs NO sweep,
    makes no bootstrap commit, and answers nothing. A zero-exit here does NOT mean the consumer is
    conformant: it means the QUESTION is now on disk. The mode says so out loud on stdout, and the
    delivered block says so in the carrier itself (`_BACKFILL_BANNER`) — the terminal line scrolls
    away, the carrier does not. The next ORDINARY `init` still refuses until each section is answered,
    and that refusal is the contract, not a regression.

    NOTHING-DELIVERED = TOTAL NO-OP: an idempotent re-run writes no file, emits NO event, makes no
    commit and leaves a clean tree — the same emit-only-on-change shape as its two siblings."""
    import sys

    # FAIL-CLOSED on a mixed run — never SILENTLY drop a requested write. This early return skips the
    # early return of `--adopt-extension` (a pure carrier write of its own since T-11189), so a combined
    # invocation would honour one flag and discard the other. (The `--adopt-concern` / `--declare-theme`
    # early returns run BEFORE this one and refuse `--backfill-mandatory` on their own side, so every
    # pair is covered.) The ops are independent and repeatable, so running them separately costs nothing.
    if getattr(args, "adopt_extension", None):
        print("yitc-v2: init --backfill-mandatory cannot be combined with --adopt-extension — both are pure "
              "carrier writes with their own early-return path, so one would be silently dropped. Run them as two "
              "separate ops: `init --adopt-extension …`, then `init --backfill-mandatory`.",
              file=sys.stderr)
        raise SystemExit(1)

    # --dry-run SAFETY: `cmd_init` has ALREADY swapped the mutation seams before this early return, so
    # under `--dry-run` `write_text_atomic` IS the plan's recorder and `ops_path` IS a scratch overlay
    # copy of the carrier. The delivery below therefore runs UNCHANGED and writes to scratch, never to
    # REPO_ROOT/yitc-ops.yaml — the same contract both siblings rely on (see `_declare_theme_only`).
    ops_path = ops_path if ops_path is not None else repo_root / CONSUMER_OPS_CONTRACT
    delivered = _backfill_mandatory_sections(ops_path, write_text_atomic, cli_form)

    if not delivered:
        prefix = "init --dry-run" if plan is not None else "consumer init"
        print(f"{prefix} ({repo_root.name}): no MANDATORY ops section is missing — no-op "
              f"(nothing to backfill; an already-present section is never rewritten)")
        if plan is not None:
            plan.cleanup()
        return

    if plan is not None:
        plan.render()
        plan.cleanup()
        return

    _append_event("consumer_init", None, {
        "path": str(repo_root),
        "mode": "backfill-mandatory",     # T-10982: the pure carrier-BACKFILL run (no scaffold, no sweep)
        "created": [],                    # by construction: this path delivers no scaffold
        "skipped": [],
        "sections_backfilled": delivered,  # SPEC-0093 rule 11 — delivered UNANSWERED, never born-answered
    })

    # SCOPED COMMIT — the backfilled scaffold reaches the consumer's own `main` via a GOVERNED commit,
    # not a loose dirty tree (the `_adopt_concern_only` posture), staging ONLY the carrier + the
    # journal: never the `managed` scaffold list, never `git add -A`. Off `main` it commits nothing and
    # leaves the two paths dirty for the next `land` to fold (D-0049).
    cur = _run_git_cap(["symbolic-ref", "--quiet", "--short", "HEAD"], repo_root)
    if cur.returncode == 0 and cur.stdout.strip() == "main":
        # SPEC-0190-VERDICT: segment-aware — this set is NOT a liveness/presence QUERY, it is the
        # pathspec list of a scoped `git add --`, so the question it asks is "which physical paths of
        # this consumer's journal must this commit carry?" and by rule 1 an archive segment IS that
        # journal. A rotated consumer would otherwise leave one uncommitted (the X-0274 wedge). The
        # `.exists()` filter is kept verbatim: `journal_pathspecs` returns the LIVE segment
        # unconditionally, so that filter still decides its fate, and the archives it adds are
        # glob-derived (present by construction).
        present = [p for p in (CONSUMER_OPS_CONTRACT,
                               *_journal_pathspecs(repo_root / "events.jsonl", repo_root))
                   if (repo_root / p).exists()]
        if present:
            _run_git_cap(["add", "--", *present], repo_root)
        if _run_git_cap(["diff", "--cached", "--quiet"], repo_root).returncode != 0:
            _run_git_cap(["commit", "-q", "-m", (
                "chore: backfill newly-mandatory ops section(s) UNANSWERED "
                "(yitc-v2 init --backfill-mandatory)\n\n"
                "Governed ops-carrier write — delivers a section that became MANDATORY after this\n"
                "consumer was init'ed, as the born GUIDANCE without the born ANSWER. The born waiver is\n"
                "deliberately NOT delivered: back-delivered to an existing project it is an unverified\n"
                "factual claim about that project. Delivery-only: no scaffold, no sweep, nothing\n"
                "answered. The next ordinary init REFUSES until each section is answered.\n\n"
                "from: SPEC-0093 rule 11 — the UPDATE path, mandatory-section carrier-backfill (T-10982)\n")],
                repo_root)

    print(f"consumer init ({repo_root.name}): BACKFILLED mandatory ops section(s) UNANSWERED — "
          + ", ".join(delivered))
    print("  Nothing was answered on this project's behalf: the born waiver was NOT delivered, only "
          "the question.")
    print(f"  THE NEXT ORDINARY `init` WILL REFUSE until each section above is answered in "
          f"{CONSUMER_OPS_CONTRACT} (declare it, or write your own `waiver: {{reason: <why>}}`). "
          f"That refusal is this delivery's POINT — a zero exit here does NOT mean conformant.")


# ── Per-concern ADOPTION record (SPEC-0093 / SPEC-0143 Rule 2) ───────────────────────────────────────
# Card B (T-10171): a consumer records, PER concern, an adoption entry in its OWN yitc-ops.yaml —
# {status: adopt|waive|na, version: <the adopted concern-version>, owner, at}. Written ONLY through this
# EXISTING `-C` init op behind the opt-in `--adopt-concern SECTION:STATUS:OWNER` flag (never a new verb,
# never a new file, never a kernel push, never a raw cross-repo edit — D-0019 / lesson
# governed-consumer-config-write-via-init-extension). OPT-IN-shaped: a concern with NO adoption entry
# reads as not-yet-adopted (surfaced later as drift by SPEC-0143 Rule 3), NOT a fail-closed
# declare-or-waive. The `version` is looked up from the KERNEL-derived concern registry (Card A / T-10170
# added the field), so a committed adoption always records the concern-version it was made against; a
# later kernel version bump then surfaces as drift.
_ADOPTION_STATUSES = ("adopt", "waive", "na")


def _canon_adoption_at(v) -> str:
    """Canonical serialization of an `adoption[].at` value: the bare ISO-Z form the writers mint
    (`%Y-%m-%dT%H:%M:%SZ`). Both writers re-render EVERY entry from a YAML round-trip, and PyYAML's
    timestamp resolver parses `2026-07-09T03:03:40Z` into a `datetime` — so a plain f-string re-emits
    an UNRELATED entry as `2026-07-09 03:03:40+00:00`, dirtying every record on a one-record write and
    mixing two serializations in one list (X-0252). Canonicalizing at this single render chokepoint
    makes an already-Z value round-trip byte-stable and normalizes a datetime-form one. A naive
    datetime is assumed UTC (that is how the writers mint it); a non-temporal scalar passes through."""
    from datetime import date, datetime, timezone
    if isinstance(v, datetime):
        dt = v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, date):                              # a date-only scalar → midnight UTC, same form
        return v.strftime("%Y-%m-%dT00:00:00Z")
    return str(v).strip()


def _parse_adoption_extras(block_lines: list) -> dict:
    """From the raw lines of an existing `adoption:` section (its header line PLUS the indented body),
    return {concern -> [comment lines]} — the annotation lines a consumer attached to each entry
    (provenance, audit citations). The 5 machine fields (concern/status/version/owner/at) are
    machine-owned and REGENERATED, so they are NOT carried here; every OTHER indented comment line under
    an entry IS, keyed by that entry's concern, so a full-block regenerate carries the annotations forward
    (X-0286 / T-10322). Comment lines before the first entry are keyed under None (the header extras)."""
    import re
    extras: dict = {None: []}
    cur = None
    field = re.compile(r"^\s+(concern|status|version|owner|at):")
    for ln in block_lines:
        m = re.match(r"^\s+-\s+concern:\s*(\S+)", ln)
        if m:
            cur = m.group(1)
            extras.setdefault(cur, [])
            continue
        if field.match(ln):
            continue
        # any OTHER indented comment line within the block — preserve under the current entry (or the
        # header, before the first entry). Blank / column-0 lines are dropped (formatting, not annotation).
        if ln[:1].isspace() and ln.lstrip().startswith("#"):
            extras[cur].append(ln if ln.endswith("\n") else ln + "\n")
    return extras


def _render_adoption_block(entries: list, extras: dict | None = None) -> str:
    """Render the machine-owned `adoption:` section (a block list of {concern,status,version,owner,at}
    mappings) from an ordered list of dicts, in the carrier's 2-space block style. TEXT-rendered (not a
    yaml dump): the 5 fields are machine-written data, regenerated every run. `at` is a bare ISO-Z
    timestamp (a valid plain scalar), canonicalized through `_canon_adoption_at` so a YAML round-trip
    cannot re-serialize an untouched entry (X-0252); owner is validated to a simple handle at write-time
    so no quoting is needed. `extras` (from `_parse_adoption_extras`) carries any consumer COMMENT
    annotation lines forward, keyed by concern — appended after each entry's fields — so a rewrite no
    longer erases a consumer's provenance / audit-citation comments (X-0286 / T-10322)."""
    extras = extras or {}
    out = ["adoption:\n"]
    out.extend(extras.get(None, []))
    for e in entries:
        out.append(f"  - concern: {e['concern']}\n")
        out.append(f"    status: {e['status']}\n")
        out.append(f"    version: {e['version']}\n")
        out.append(f"    owner: {e['owner']}\n")
        out.append(f"    at: {_canon_adoption_at(e['at'])}\n")
        out.extend(extras.get(str(e['concern']), []))
    return "".join(out)


def _replace_adoption_block(text: str, entries: list) -> str:
    """Replace an existing column-0 `adoption:` section IN PLACE (or, if none exists yet, append a freshly
    rendered one at EOF). The 5 machine fields are machine-owned (only this op writes them) so they are
    regenerated in full, but any consumer COMMENT annotations inside the block are PRESERVED across the
    rewrite (parsed by `_parse_adoption_extras`, re-emitted per-concern by `_render_adoption_block`) — a
    full-block re-dump used to erase them (X-0286 / T-10322). The rest of the carrier stays byte-stable.
    The section runs from its column-0 `adoption:` header until the next column-0 key (or EOF).

    IN-PLACE splice, not remove-and-append-at-EOF (X-0442 / T-10594): the old path lifted the block out of
    its on-disk position and re-appended it at EOF, so ANY section sitting AFTER `adoption:` (e.g. a 76-line
    `outcome_invariants:`) shifted upward — a 5-line adoption append presented as a ~150-line section move,
    burying the actual change under a spurious relocation diff. Splicing the rendered block back at its
    original span keeps every other section's byte position stable, so the diff is exactly the append."""
    import re
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(r"^adoption:\s*(#.*)?$", ln)), None)
    if start is not None:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if re.match(r"^[A-Za-z_][\w-]*:", lines[j]) and not lines[j][:1].isspace():
                end = j
                break
        extras = _parse_adoption_extras(lines[start:end])
        block = _render_adoption_block(entries, extras)
        # splice the freshly rendered block back into the SAME span — `before` ends with a newline (or is
        # empty when adoption: is the first line) and every rendered line is newline-terminated, so no
        # separator juggling is needed and sections before/after keep their byte positions.
        return "".join(lines[:start]) + block + "".join(lines[end:])
    # no existing `adoption:` section — first-ever adoption on this carrier: append at EOF.
    body = text
    block = _render_adoption_block(entries, {})
    sep = "" if (not body) or body.endswith("\n") else "\n"
    return body + sep + block


def _adopt_concerns(ops_path, specs: list, write_text_atomic) -> list:
    """SPEC-0093 / SPEC-0143 Rule 2 — the GOVERNED per-concern adoption-record path behind
    `init --adopt-concern SECTION:STATUS:OWNER`. For each request: parse SECTION:STATUS:OWNER, RESOLVE the
    concern SECTION in the KERNEL-derived registry + read its derived `version` (refuse an unknown section,
    a bad status, or a mal-shaped owner — a committed adoption always cites a REAL concern at a REAL
    version, enforced HERE at write-time), CHECK the requested status against the carrier's ACTUAL stance
    (T-10484 — an `adopt` over a section the carrier does not declare is REFUSED; see the gate below), then
    UPSERT {concern,status,version,owner,at} into the carrier's
    `adoption:` section. IDEMPOTENT: a request whose (status,version,owner) already matches the recorded
    entry is a no-op (the original `at` is kept), so a re-run makes NO spurious commit. Returns the concern
    sections newly recorded/updated this run (empty when nothing changed / none asked). Self-contained
    (inline re/sys/yaml/datetime; reads only the already-injected `write_text_atomic` + the module-level
    `_load_concern_registry`) so cmd_init's injected-deps contract stays unchanged (SPEC-0077 pinned
    last-green verify asserts injected-deps by `==`; module header + lesson watch-out)."""
    import re
    import sys
    import yaml
    from datetime import datetime, timezone

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)
    if not specs:
        return []

    def _fail(msg: str) -> None:
        print(f"yitc-v2: {msg}", file=sys.stderr)
        raise SystemExit(1)

    if not ops_path.exists():
        _fail(f"init --adopt-concern: {CONSUMER_OPS_CONTRACT} not found — cannot record an adoption into a missing carrier.")
    # the KERNEL-derived concern registry, by section (Card A / T-10170 added the `version` field). The
    # whole ENTRY is kept — not just its version — because the stance gate below needs the concern's
    # `carrier_path` / `declare_key` / `declare_type` to read the carrier's ACTUAL stance (T-10484).
    entries_by_section = {c.get("section"): c for c in _load_concern_registry() if isinstance(c, dict)}

    # READ the carrier ONCE, up front: the stance gate validates against it, and the upsert below reuses
    # the same parse (one read, one parse — no second load of the same file).
    text = ops_path.read_text(encoding="utf-8")
    try:
        ops = state.load_ops_str(text) if text.strip() else None
    except yaml.YAMLError as e:
        _fail(f"init --adopt-concern: {CONSUMER_OPS_CONTRACT} failed to parse ({e}); re-run init to re-seed it.")

    # PARSE + VALIDATE each request (the write-time resolution gate — refuse a dangling/mal-shaped adoption)
    requests = []
    for raw in specs:
        parts = str(raw).split(":")
        if len(parts) != 3:
            _fail(f"init --adopt-concern: {raw!r} is not SECTION:STATUS:OWNER (e.g. coverage:adopt:sergey).")
        section, status, owner = (p.strip() for p in parts)
        entry = entries_by_section.get(section)
        if not entry or not entry.get("version"):
            _fail(f"init --adopt-concern: {section!r} is not a kernel concern section (or carries no derived "
                  f"version) — the adoption would be dangling. Discover the concerns in graph/concern-registry.json.")
        if status not in _ADOPTION_STATUSES:
            _fail(f"init --adopt-concern: status {status!r} must be one of {'/'.join(_ADOPTION_STATUSES)}.")
        if not re.match(r"^[\w.@+-]+$", owner):
            _fail(f"init --adopt-concern: owner {owner!r} must be a simple handle ([\\w.@+-]+, no spaces/colons).")
        # STANCE-CONSISTENCY GATE (T-10484, SPEC-0143 Rule 2) — an `adopt` record must MIRROR a section the
        # carrier ACTUALLY declares. Rule 2 already says the record mirrors the declare-or-waive stance, but
        # only the birth pre-seed derived it; this explicit path recorded the requested status verbatim, so
        # `coverage:adopt:<owner>` over `coverage: {load_bearing: []}` wrote ADOPTED while `_coverage_opt_in`
        # reads that empty list as NOT-opted-in — the ledger asserting a mechanism that tracks nothing
        # (boomrocket, 2026-07-12). Reuse the SAME `_mirror_adoption_status` the pre-seed uses (one stance
        # reader, CHARTER §P5) — here to REFUSE a false claim, never to answer for the owner (the
        # `lessons/a-stance-mirror-is-only-sound-at-birth` trap is WRITING a mirrored stance; this gate
        # writes none, and the question stays the owner's). Only `adopt` is gated: `waive`/`na` assert no
        # active mechanism, so they cannot lie in this direction.
        # Fail-CLOSED on a non-mapping carrier: an empty/degenerate carrier declares nothing, so an
        # `adopt` over it is exactly the unsubstantiated claim this gate exists to refuse.
        if status == "adopt" and _mirror_adoption_status(ops if isinstance(ops, dict) else {}, entry) != "adopt":
            dk = entry.get("declare_key") or "the declaration key"
            _fail(f"init --adopt-concern: cannot record {section!r} as `adopt` — {CONSUMER_OPS_CONTRACT} does "
                  f"not DECLARE that concern (its `{dk}:` is absent, empty, or wrong-typed, or the section is "
                  f"waived). An `adopt` record over an undeclared section says ADOPTED while the mechanism "
                  f"tracks NOTHING (SPEC-0143 Rule 2 — the record MIRRORS the declare-or-waive stance). Two "
                  f"honest exits: (a) DECLARE a non-empty `{section}.{dk}:` in {CONSUMER_OPS_CONTRACT}, then "
                  f"re-run this adopt; or (b) WAIVE the concern (`{section}.waiver: {{reason: <why>}}`) and "
                  f"record `--adopt-concern {section}:waive:{owner}`.")
        requests.append((section, status, owner, str(entry["version"])))

    # UPSERT by concern into the existing adoption records (preserving order)
    order: list = []
    by_concern: dict = {}
    if isinstance(ops, dict) and isinstance(ops.get("adoption"), list):
        for e in ops["adoption"]:
            if isinstance(e, dict) and e.get("concern"):
                key = str(e.get("concern"))
                if key not in by_concern:
                    order.append(key)
                by_concern[key] = dict(e)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    recorded: list = []
    for section, status, owner, version in requests:
        cur = by_concern.get(section)
        # IDEMPOTENT: identical (status,version,owner) already recorded → no-op (keep the original `at`)
        if cur and str(cur.get("status")) == status and str(cur.get("version")) == version and str(cur.get("owner")) == owner:
            continue
        if section not in by_concern:
            order.append(section)
        by_concern[section] = {"concern": section, "status": status, "version": version, "owner": owner, "at": now}
        recorded.append(section)
    if not recorded:
        return []
    write_text_atomic(ops_path, _replace_adoption_block(text, [by_concern[c] for c in order]))
    return recorded


def _adopt_concern_only(repo_root, args, *, _append_event, _run_git_cap, write_text_atomic,
                        ops_path=None, plan=None) -> None:
    """`init --adopt-concern SECTION:STATUS:OWNER` as a PURE adoption-record write (T-10265 / X-0251).

    The flag declares ONE job — record one per-concern adoption entry (SPEC-0143 Rule 2, the only
    sanctioned writer of that record). Before this split it reached `_adopt_concerns` only by falling
    through the WHOLE of `cmd_init`, so it ALSO re-delivered every if-absent born scaffold: the born
    files, the MEMORY.md station pointers, the vendor adapter, the security-audit cadence scaffold, the
    engine templates. On a consumer that had deliberately DELETED a scaffold, recording an adoption
    silently re-materialized it — so social-parser could not record its `security` adoption without
    re-creating the X-0239 silent-pass hazard (bin/security-audit colliding on the findings path its own
    producer owns). Scaffold delivery is the BARE init's job and stays single-homed there, byte-unchanged.

    So this path does EXACTLY the record: no scaffold write, no rematerialization, no folder marker, no
    retired-surface sweep, no `managed`-list bootstrap staging. It runs BEFORE the legacy-CROSS-TASKS
    guard, which exists to protect SCAFFOLD delivery from orphaning un-migrated content — an adoption
    record delivers no scaffold, so it no longer inherits that guard (the deviation
    `adopt-op-inherits-legacy-cross-tasks-guard`, `lessons/governed-consumer-config-write-via-init-extension`).

    Module-level + explicit args (never a `cmd_init` parameter): the SPEC-0077 pinned last-green asserts
    cmd_init's injected-deps by `==`, so its host signature stays byte-identical (same reason
    `_adopt_concerns` is module-level).

    NOTHING-RECORDED = TOTAL NO-OP: an idempotent re-record writes no file, emits NO event, makes no
    commit and leaves a clean tree — a record-write that recorded nothing must leave zero trace (an
    unconditional `consumer_init` append would dirty `events.jsonl`). Same emit-only-on-change shape as
    `onboarding_seeded` / `retired_surface_swept` in `cmd_init`.

    `ops_path` + `plan` carry the T-10271 `--dry-run` preview: the caller has already swapped the three
    mutation seams for `plan`'s recorders and pointed `ops_path` at its scratch overlay, so this op runs
    UNCHANGED and simply reports what it would record. Both default to the real-run behaviour."""
    import sys

    # FAIL-CLOSED on a mixed run — never SILENTLY drop a requested write. Since T-11189
    # `--adopt-extension` is a pure carrier write with an early return of its OWN, and THIS one runs
    # first, so a combined invocation would honour one flag and discard the other: trading the side
    # effect this task removes for a silent omission. Refuse; the ops are independent and repeatable,
    # so running them separately costs nothing.
    if getattr(args, "adopt_extension", None):
        print("yitc-v2: init --adopt-concern cannot be combined with --adopt-extension — both are "
              "pure carrier writes with their own early-return path, so one would be silently dropped. "
              "Run them as two separate ops: `init --adopt-extension …`, then `init --adopt-concern …`.",
              file=sys.stderr)
        raise SystemExit(1)
    # …and the same fail-closed refusal for `--declare-theme` (T-10535): THIS early return runs FIRST, so
    # a combined invocation would silently discard the theme declaration. Same rationale, other direction.
    if getattr(args, "declare_theme", None):
        print("yitc-v2: init --adopt-concern cannot be combined with --declare-theme — both are pure "
              "carrier writes with their own early-return path, so one would be silently dropped. Run "
              "them as two separate ops: `init --declare-theme …`, then `init --adopt-concern …`.",
              file=sys.stderr)
        raise SystemExit(1)
    # …and again for `--backfill-mandatory` (T-10982), the third member of this family. Same rationale,
    # same direction: THIS early return runs first, so a combined invocation would silently drop the
    # backfill delivery.
    if getattr(args, "backfill_mandatory", False):
        print("yitc-v2: init --adopt-concern cannot be combined with --backfill-mandatory — both are "
              "pure carrier writes with their own early-return path, so one would be silently dropped. "
              "Run them as two separate ops: `init --backfill-mandatory`, then `init --adopt-concern …` "
              "(backfill FIRST — an adoption record over a section that is not on disk yet is a record "
              "about nothing).", file=sys.stderr)
        raise SystemExit(1)

    # THE write. `_adopt_concerns` owns every write-time refusal (missing carrier / dangling concern /
    # bad status / mal-shaped owner) and is idempotent — a re-record at the same (status,version,owner)
    # returns [] and leaves the carrier byte-identical.
    ops_path = ops_path if ops_path is not None else repo_root / CONSUMER_OPS_CONTRACT
    recorded = _adopt_concerns(ops_path, args.adopt_concern, write_text_atomic)

    if not recorded:
        prefix = "init --dry-run" if plan is not None else "consumer init"
        print(f"{prefix} ({repo_root.name}): concern adoption already recorded — no-op")
        if plan is not None:
            plan.cleanup()
        return

    if plan is not None:
        plan.render(concerns_preseeded=recorded,
                    adoption_records=_preseeded_adoption_records(
                        ops_path.read_text(encoding="utf-8"), recorded))
        plan.cleanup()
        return

    _append_event("consumer_init", None, {
        "path": str(repo_root),
        "mode": "adopt-concern",      # T-10265: the pure adoption-record run (no scaffold delivery)
        "created": [],                # by construction: this path delivers no scaffold
        "skipped": [],
        "concerns_adopted": recorded,  # SPEC-0143 Rule 2 — the concern sections recorded/updated this run
    })

    # SCOPED COMMIT — the adoption record reaches the consumer's own `main` via a GOVERNED commit, not a
    # loose dirty tree (the same posture as the bootstrap commit, and the same on-main precondition), but
    # it stages ONLY the carrier + the journal: never the `managed` scaffold list, never `git add -A`.
    # Off `main` (a divergence/normalization case) it commits nothing and leaves the two paths dirty for
    # the next `land` to fold (D-0049) — exactly what cmd_init does there today.
    cur = _run_git_cap(["symbolic-ref", "--quiet", "--short", "HEAD"], repo_root)
    if cur.returncode == 0 and cur.stdout.strip() == "main":
        # SPEC-0190-VERDICT: segment-aware — this set is NOT a liveness/presence QUERY, it is the
        # pathspec list of a scoped `git add --`, so the question it asks is "which physical paths of
        # this consumer's journal must this commit carry?" and by rule 1 an archive segment IS that
        # journal. A rotated consumer would otherwise leave one uncommitted (the X-0274 wedge). The
        # `.exists()` filter is kept verbatim: `journal_pathspecs` returns the LIVE segment
        # unconditionally, so that filter still decides its fate, and the archives it adds are
        # glob-derived (present by construction).
        present = [p for p in (CONSUMER_OPS_CONTRACT,
                               *_journal_pathspecs(repo_root / "events.jsonl", repo_root))
                   if (repo_root / p).exists()]
        if present:
            _run_git_cap(["add", "--", *present], repo_root)
        if _run_git_cap(["diff", "--cached", "--quiet"], repo_root).returncode != 0:
            _run_git_cap(["commit", "-q", "-m", (
                "chore: record per-concern adoption (yitc-v2 init --adopt-concern)\n\n"
                "Governed per-consumer adoption record — the only sanctioned writer of the ops-carrier\n"
                "`adoption:` block. Stages the carrier + journal ONLY; delivers no scaffold (T-10265).\n\n"
                "from: SPEC-0143 Rule 2 — per-consumer adoption record, written only by the consumer\n")],
                repo_root)

    print(f"consumer init ({repo_root.name}): recorded concern adoption(s) " + ", ".join(recorded))


def _adopt_extension_only(repo_root, args, *, ENGINE_ROOT, _append_event, _run_git_cap,
                          write_text_atomic, ops_path=None, plan=None) -> None:
    """`init --adopt-extension SPEC-XXXX` as a PURE carrier-write (T-11189 / X-0941) — the FOURTH member
    of the `_adopt_concern_only` family, closing the one gap that family still had.

    THE DEFECT. The flag declares ONE job — append one `- spec: SPEC-XXXX` entry under
    `extensions.adopts` (SPEC-0093 rule 13 / SPEC-0101 §4). It had no early return of its own, so it
    reached its write only by falling through the bare-init body as far as the `_adopt_extensions` call
    site — and everything that body does BEFORE that point ran too. In particular the SPEC-0093 rule-11
    update `_update_ops_carrier`, which delivers every MISSING extensible born top-level section into the
    carrier. That is exactly right for a BARE init (re-running init IS the schema update) and exactly
    wrong for a one-record append. social-scraper's worker adopted ONE extension and received
    `sandbox_entry` (born WAIVER stance) and `audit_scrutiny` — the declared surface of a HELD sibling
    card — then HAND-REVERTED both sections as text to keep its diff inside its own card. Hand-undoing a
    governed verb's write is precisely the hand-work the verb-execution discipline exists to prevent, and
    it leaves the undo invisible to every later session. The verb that forces it is the defect.

    THE SHAPE is the family's, unchanged: an early return at the top of `cmd_init` BEFORE any filesystem
    write; the write itself; a scoped commit staging ONLY {carrier, journal}; a `consumer_init` event
    carrying its own `mode`; and NOTHING-WRITTEN = a total no-op. Scaffold delivery stays single-homed on
    the bare-init path, byte-unchanged (`--adopt-extension` never was its delivery trigger — it merely
    rode past it). Module-level + explicit injected args for the same reason `_adopt_concerns` is: the
    SPEC-0077 pinned last-green asserts `cmd_init`'s injected-deps by `==`, so its host signature must
    stay byte-identical.

    WHY NO SWEEP RUNS HERE, and why that is safe rather than a hole. `_adopt_extensions` is WRITE-TIME
    gated by construction (T-10775 says it outright): it refuses a dangling or non-`adoptable` cite, a
    `--extension-source` for a spec this run is not adopting, and any adoption whose qualifying source
    would not pass the carrier's own residual — "refusing to write an adoption the carrier's own sweep
    would then fail closed on". It also retires the contradicted born waive (T-10475) and mirrors the
    extensions stance (T-10481) in the SAME act. So there is nothing this path could write that the
    skipped sweeps were the last line of defence against — the identical posture the three siblings take.

    WHY THERE ARE NO MIXED-FLAG REFUSALS IN THIS FUNCTION. All three siblings' branches run BEFORE this
    one in `cmd_init` and each already refuses a combination with `--adopt-extension`, so by the time
    control reaches here `--adopt-concern` / `--declare-theme` / `--backfill-mandatory` are all absent by
    construction. Re-asserting that here would be unreachable code (CHARTER §P1). Their refusal TEXT was
    updated by this task: the reason is no longer "it rides the scaffold-delivering bare-init path" — it
    is now the same one the siblings give each other, that both are pure carrier writes with their own
    early return so one would be silently dropped.

    `ops_path` + `plan` carry the `--dry-run` preview exactly as they do for the siblings: `cmd_init` has
    ALREADY swapped the mutation seams, so `write_text_atomic` is the plan's recorder and `ops_path` a
    scratch overlay. The op below therefore runs UNCHANGED and writes nothing to the real carrier."""
    ops_path = ops_path if ops_path is not None else repo_root / CONSUMER_OPS_CONTRACT

    # CHANGE is read from the CARRIER BYTES, not from the return value. `_adopt_extensions` returns the
    # ids NEWLY appended, which is not the same question: a carrier already contaminated (a spec adopted
    # while still waived) yields an EMPTY return while the T-10475 heal still rewrites the file. Keying
    # the no-op on the return value would then skip the commit and strand that heal as a dirty tree —
    # the exact class of invisible residue this task exists to remove. The byte-compare is valid under
    # `--dry-run` too: the plan's recorder ALSO writes the scratch overlay for real (its read-back chain).
    before = ops_path.read_text(encoding="utf-8") if ops_path.exists() else None
    adopted = _adopt_extensions(
        ops_path,
        [s for s in (getattr(args, "adopt_extension", None) or [])],
        ENGINE_ROOT, write_text_atomic,
        dict(_parse_extension_source(raw) for raw in (getattr(args, "extension_source", None) or [])))
    after = ops_path.read_text(encoding="utf-8") if ops_path.exists() else None

    if not adopted and after == before:
        prefix = "init --dry-run" if plan is not None else "consumer init"
        print(f"{prefix} ({repo_root.name}): extension adoption already recorded — no-op")
        if plan is not None:
            plan.cleanup()
        return

    if plan is not None:
        plan.render()
        plan.cleanup()
        return

    _append_event("consumer_init", None, {
        "path": str(repo_root),
        "mode": "adopt-extension",       # T-11189: the pure adoption-record run (no scaffold delivery)
        "created": [],                   # by construction: this path delivers no scaffold
        "skipped": [],
        "extensions_adopted": adopted,   # SPEC-0093 rule 13 — the extensions adopted this run
    })

    # SCOPED COMMIT — the adoption reaches the consumer's own `main` via a GOVERNED commit, not a loose
    # dirty tree (the `_adopt_concern_only` posture), staging ONLY the carrier + the journal: never the
    # `managed` scaffold list, never `git add -A`. Off `main` it commits nothing and leaves the two paths
    # dirty for the next `land` to fold (D-0049).
    cur = _run_git_cap(["symbolic-ref", "--quiet", "--short", "HEAD"], repo_root)
    if cur.returncode == 0 and cur.stdout.strip() == "main":
        # SPEC-0190-VERDICT: segment-aware — this set is NOT a liveness/presence QUERY, it is the
        # pathspec list of a scoped `git add --`, so the question it asks is "which physical paths of
        # this consumer's journal must this commit carry?" and by rule 1 an archive segment IS that
        # journal. A rotated consumer would otherwise leave one uncommitted (the X-0274 wedge). The
        # `.exists()` filter is kept verbatim: `journal_pathspecs` returns the LIVE segment
        # unconditionally, so that filter still decides its fate, and the archives it adds are
        # glob-derived (present by construction).
        present = [p for p in (CONSUMER_OPS_CONTRACT,
                               *_journal_pathspecs(repo_root / "events.jsonl", repo_root))
                   if (repo_root / p).exists()]
        if present:
            _run_git_cap(["add", "--", *present], repo_root)
        if _run_git_cap(["diff", "--cached", "--quiet"], repo_root).returncode != 0:
            _run_git_cap(["commit", "-q", "-m", (
                "chore: adopt kernel extension(s) (yitc-v2 init --adopt-extension)\n\n"
                "Governed ops-carrier write — a SURGICAL TEXT append under `extensions.adopts` that\n"
                "preserves every existing byte (never a YAML round-trip). Stages the carrier + journal\n"
                "ONLY; delivers no scaffold and pulls no born section (T-11189).\n\n"
                "from: SPEC-0093 rule 13 / SPEC-0101 §4 — the consumer extension-adoption record\n")],
                repo_root)

    if adopted:
        print(f"consumer init ({repo_root.name}): adopted extension(s) " + ", ".join(adopted))
    else:
        # The T-10475 heal with nothing new to append: the carrier CHANGED (a contradicted waive was
        # retired / the stance re-recorded) but no id was added. Say so rather than printing an empty list.
        print(f"consumer init ({repo_root.name}): extension stance reconciled (no new adoption)")


def _mirror_adoption_status(ops: dict, entry: dict) -> str:
    """The pre-seed MIRROR of the just-made declare-or-waive stance for ONE registry concern (T-10190):
    a DECLARED section → `adopt`, a WAIVED section → `waive`, an absent/not-applicable section → `na`.
    Reuses the SAME `_ops_navigate` + `_ops_declared` primitives as `_ops_carrier_violations` so the
    mirror can never drift from the sweep verdict (CHARTER §P5). Called only AFTER the fail-closed sweep
    has PASSED, so every mandatory concern is present+declared/waived and a checked-if-present/opt-in one
    is either that or a valid absence (→ `na`).

    SELF-CARRIED concerns (T-10241, X-0237): a concern whose carrier LEAF *is* its `declare_key` (today
    `startup_checks:`, a bare list) holds the declaration in the leaf value itself — there is no wrapping
    mapping to look inside. A dict-only reading bucketed such a LIVE declaration as `na`, recording a
    project whose checks actively run as not-applicable — a false stance record. (X-0237 further claimed
    that `na` SILENCED the concern's drift; it does not — `concern_drift` tests version equality alone,
    whatever the status. The defect is the false record, not a silenced signal.) The stance still comes
    from `_ops_declared`, so the mirror cannot drift from the sweep verdict. A self-carried concern that
    is instead WAIVED carries a mapping (`startup_checks: {waiver: …}`) and takes the mapping branch."""
    cp = entry.get("carrier_path") or entry.get("section")
    present, val = _ops_navigate(ops, cp) if isinstance(cp, str) else (False, None)
    declare_key = entry.get("declare_key")
    if present and isinstance(declare_key, str) and cp.split(".")[-1] == declare_key \
            and not isinstance(val, dict):
        return "adopt" if _ops_declared(val, entry.get("declare_type")) else "na"
    if present and isinstance(val, dict):
        if isinstance(declare_key, str) and declare_key in val and _ops_declared(val.get(declare_key),
                                                                                 entry.get("declare_type")):
            return "adopt"
        if "waiver" in val:
            return "waive"
    return "na"


def _preseed_concern_adoptions(ops_path, write_text_atomic, *, fresh_carrier: bool) -> list:
    """SPEC-0143 Rule 2 PRE-SEED (T-10190) — after the declare-or-waive sweep validates the carrier, write
    a per-concern `adoption:` record at each concern's CURRENT registry version, MIRRORING the just-made
    decision (declared → adopt; waived → waive; absent/not-applicable → na), for every registry concern
    that has NO adoption entry yet. This makes a freshly-init'd consumer start DRIFT-QUIET: the SPEC-0143
    Rule-3 reconcile compares recorded `adoption.version` to the registry `version`, so a full set of
    current-version records means 0 `concern_drift_surfaced` at birth. The init declare-or-waive sweep IS
    the birth review (SPEC-0128 territory); the drift reconcile is for LATER contract moves only (a real
    version bump then still surfaces drift). IDEMPOTENT + NON-CLOBBERING: a concern already carrying an
    adoption entry (an owner `--adopt-concern` this run, or a prior run's committed record) is LEFT
    UNTOUCHED, so a re-init is byte-stable and an explicit owner decision is never overwritten. Written
    through the EXISTING init carrier path (the bootstrap commit to the consumer's OWN main) — no new verb,
    no kernel push, no cross-repo edit (D-0019). Owner is the sentinel `init` (the bootstrap act, not a
    human decision). Returns the concern sections newly pre-seeded this run ([] when none / no carrier).
    Self-contained (inline yaml/datetime; reuses the module-level registry + render helpers) so cmd_init's
    injected-deps contract is unchanged (the `_adopt_concerns` precedent).

    NEWBORN-ONLY (T-10262, X-0240) — `fresh_carrier` is the WHOLE gate: pre-seed IFF the ops-carrier was
    BORN THIS RUN. The birth review the pre-seed mirrors is the declare-or-waive sweep over a carrier init
    itself just wrote; a carrier that ALREADY EXISTED carries stances its owner authored against the OLD
    concern definitions, and the mirror copies the SHAPE of that old answer — which is silent about the NEW
    question. Pre-seeding it records `adopt`/`waive` @current for a contract nobody re-read, and the drift
    goes quiet: the signal SPEC-0143 exists to raise gets consumed by the TOOL instead of by the owner
    (observed live in social-parser: 14 report-only drift lines silenced by a bare `init`). So a legacy
    consumer's drift STANDS. Note the per-concern `section in by_concern` guard below CANNOT do this job —
    "no adoption entry yet" is equally true of a newborn and of a legacy consumer with real pending drift;
    at pre-seed time both read as all-un-adopted. Only "the carrier did not exist a moment ago" separates
    them, and it is exactly equivalent to "this consumer cannot have accumulated drift history". This is
    the `_seed_catalog_waives` born-this-run discriminator (the T-9596 consult's absent-vs-present
    boundary: a fresh born section is a migration; a PRESENT one is never auto-healed) — REUSED, not
    re-invented. Sibling `concern_drift` already documents the outcome restored here: a legacy consumer
    with no `adoption:` block surfaces ALL concerns once (bootstrap review, correct-not-a-bug).

    OWNER = the literal sentinel `init` (NOT a human handle): the v2 model is deliberately solo-author with
    NO ambient owner-identity plumbing (no owner-register / git-user resolver), so there is no human `init
    owner` to thread. The sentinel is the honest marker — it says the DECISION here was made by init's
    birth declare-or-waive mirror, not by an owner's explicit `--adopt-concern <sec>:<status>:<owner>` (which
    DOES carry a real handle). This is a MEANINGFUL provenance distinction: a later reader can tell a
    machine-defaulted birth record apart from an owner-decided one (audit-pre YELLOW absorbed with this
    rationale — a fabricated git-user handle would FALSELY imply a human made the call). Under the
    newborn-only gate the sentinel now ALSO carries a stronger guarantee: an `owner: init` record can only
    ever describe a stance made at birth, never a legacy stance the tool re-affirmed on the owner's behalf."""
    import yaml
    from datetime import datetime, timezone

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)
    if not fresh_carrier:
        return []            # a pre-existing carrier = a consumer with history — its drift is the OWNER's to review
    if not ops_path.exists():
        return []
    # version-by-section from the KERNEL-derived concern registry (Card A / T-10170 added the `version`)
    entries = [e for e in _load_concern_registry()
               if isinstance(e, dict) and e.get("section") and e.get("version")]
    if not entries:
        return []
    text = ops_path.read_text(encoding="utf-8")
    try:
        ops = state.load_ops_str(text) if text.strip() else None
    except yaml.YAMLError:
        return []                                        # a malformed carrier is the sweep's problem, not this
    if not isinstance(ops, dict):
        return []
    order: list = []
    by_concern: dict = {}
    if isinstance(ops.get("adoption"), list):
        for e in ops["adoption"]:
            if isinstance(e, dict) and e.get("concern"):
                key = str(e.get("concern"))
                if key not in by_concern:
                    order.append(key)
                by_concern[key] = dict(e)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    preseeded: list = []
    for entry in entries:
        section = str(entry.get("section"))
        if section in by_concern:
            continue                                     # already recorded (explicit or prior run) — never clobber
        status = _mirror_adoption_status(ops, entry)
        order.append(section)
        by_concern[section] = {"concern": section, "status": status,
                               "version": str(entry.get("version")), "owner": "init", "at": now}
        preseeded.append(section)
    if not preseeded:
        return []
    write_text_atomic(ops_path, _replace_adoption_block(text, [by_concern[c] for c in order]))
    return preseeded


# ── Extension-catalog declare-or-waive COMPLETENESS (SPEC-0112, T-9596) ─────────────────────────────
# SPEC-0112 rule-1 narrows SPEC-0093 rule-13: NON-catalog opt-in is unchanged (absence = adopts nothing),
# but for the ACTIVE+ADOPTABLE catalog set (SPEC-0101 rule-2) every member is declare-or-waive fail-closed —
# silence on a catalog member is an ERROR at init / consumer-read, never a silent "adopts nothing". A waive
# is FORWARD-AWARE (rule-2): a non-empty reason naming the waive->declare re-entry path (reuses the SPEC-0093
# rule-6 loose waiver policy). Adds NO new store/parser/node-type — it READS the engine catalog (the SAME
# derivation as views._view_extensions_catalog) and the EXISTING `extensions:` record; the refusal rides the
# EXISTING journal path (`_append_event`). The brownfield-compat boundary (absent-section backfill vs
# present-section fail-closed) is the rule-11 update precedent (see _seed_catalog_waives), settled by the
# T-9596 ceiling-convergence consult (decisions/T-9596-audit-consult-pre.yaml, option 1).
_CATALOG_WAIVE_REASON = (
    "born forward-aware waive (SPEC-0112 rule-2): this project has not adopted {sid}; to adopt (the "
    "waive->declare re-entry path) run `__YITC_CLI__ init --adopt-extension {sid}`.")


def _engine_catalog_members(engine_root) -> list:
    """SPEC-0112 rule-1 authoritative set — the active+adoptable extension catalog members, the SAME
    derivation as views._view_extensions_catalog (status==active AND extension==adoptable), read from the
    ENGINE's built graph index (single source of truth, SPEC-0101 rule-3 — NOT a parallel hand-list).
    FAIL-SOFT: returns [] when the index is absent/unreadable, so consumer-read never blocks on a missing
    engine artifact (an empty authoritative set = nothing to complete)."""
    import json
    idx_path = engine_root / "graph" / "index.json"
    if not idx_path.exists():
        return []
    try:
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    specs = (idx or {}).get("specs") or {}
    return sorted(sid for sid, node in specs.items()
                  if isinstance(node, dict)
                  and node.get("status") == "active" and node.get("extension") == "adoptable")


def _extensions_coverage(ops) -> tuple:
    """Return (declared:set, waived:dict[spec->reason]) from a parsed ops mapping. declared = the non-empty
    `extensions.adopts[].spec` ids; waived = the `extensions.waives[]` {spec, reason} mappings (reason kept
    verbatim, possibly empty — the caller distinguishes a forward-aware waive from a bare one)."""
    declared: set = set()
    waived: dict = {}
    ext = ops.get("extensions") if isinstance(ops, dict) else None
    if isinstance(ext, dict):
        for a in (ext.get("adopts") or []):
            if isinstance(a, dict) and isinstance(a.get("spec"), str) and a["spec"].strip():
                declared.add(a["spec"].strip())
        for w in (ext.get("waives") or []):
            if isinstance(w, dict) and isinstance(w.get("spec"), str) and w["spec"].strip():
                waived[w["spec"].strip()] = str(w.get("reason") or "").strip()
    return declared, waived


def _append_waives_entries(text: str, entries: list) -> str:
    """Append forward-aware `- spec: <id>` / `reason: <...>` entries under `extensions.waives`, preserving
    the carrier's comments (TEXT edit, NOT a yaml round-trip — same rationale as _append_adopts_entries).
    `entries` = list of (spec, reason). Handles: (a) NO `extensions:` section -> append a full
    `extensions:\\n  adopts: []\\n  waives:\\n` block at EOF (brownfield backfill); (b) section present, no
    `waives:` key -> insert one before the section end; (c) `waives:` present -> append after its last item.
    Reasons are emitted as one-line double-quoted scalars (the born reason carries no embedded double-quote)."""
    import re
    if not entries:
        return text

    def _items(es) -> str:
        out = ""
        for sid, reason in es:
            out += f"  - spec: {sid}\n    reason: \"{reason}\"\n"
        return out

    lines = text.splitlines(keepends=True)
    ext_idx = next((i for i, ln in enumerate(lines)
                    if re.match(r"^extensions:\s*(#.*)?$", ln)), None)
    if ext_idx is None:                                  # (a) no section — append a complete born block
        block = "extensions:\n  adopts: []\n  waives:\n" + _items(entries)
        sep = "" if (not text) or text.endswith("\n") else "\n"
        return text + sep + block
    # the section runs until the next column-0 key (or EOF); find an existing `waives:` line within it
    end_idx = len(lines)
    waives_idx = None
    for j in range(ext_idx + 1, len(lines)):
        if re.match(r"^[A-Za-z_][\w-]*:", lines[j]) and not lines[j][:1].isspace():
            end_idx = j
            break
        if waives_idx is None and re.match(r"^\s+waives:\s*(#.*)?$", lines[j]):
            waives_idx = j
    if waives_idx is None:                               # (b) section present, no waives: key — insert one
        return "".join(lines[:end_idx]) + "  waives:\n" + _items(entries) + "".join(lines[end_idx:])
    insert_at = waives_idx + 1                           # (c) append after the last contiguous list block
    for k in range(waives_idx + 1, end_idx):
        if re.match(r"^\s*-\s", lines[k]) or re.match(r"^\s+\w+:", lines[k]):
            insert_at = k + 1
        elif lines[k].strip() == "" or lines[k].lstrip().startswith("#"):
            continue
        else:
            break
    return "".join(lines[:insert_at]) + _items(entries) + "".join(lines[insert_at:])


# SIBLING-ASSESSMENT (T-10506, the T-10493 fallout sweep): does this born-mirror waive need the analogous
# read-time cross-check that T-10493 (`_adoption_stance_violations`) added for the SPEC-0143 adoption
# records? lessons/a-stance-mirror-is-only-sound-at-birth flags both as the same "a mirror is only sound at
# birth" family. ASSESSED CONCLUSION: NO analogous cross-check is needed here (P1 — record why-not, don't
# add a mechanism). Three grounds:
#   (1) TWO-HOME vs SINGLE-HOME. The T-10415/X-0088 bug was a two-carrier DRIFT: a concern's declare-or-waive
#       stance lives in SECTION keys (deploy.services, tests.classes) while its adoption RECORD lives in a
#       SEPARATE `adoption[]` list, so growing a section silently falsified the record. The SPEC-0112
#       extension record is SINGLE-HOME: the waive (`extensions.waives[]`) and the declare
#       (`extensions.adopts[]`) are the SAME list, and adopting IS moving the entry across it (see
#       `_extensions_coverage`) — there is NO independent "this extension is in use" carrier for a stale
#       waive to contradict. The drift shape that motivated the cross-check cannot form.
#   (2) DOWNSTREAM IS ALREADY FAIL-CLOSED AND RE-RUN EVERY init. `_sweep_extension_catalog_completeness`
#       re-reads this same single home on EVERY init and fails closed on any member missing a declare-or-
#       waive — whereas the adoption record was validated ONLY at write time, which is precisely the gap
#       T-10493 closed. A born waive here is re-examined every init, not written-and-forgotten.
#   (3) THE ONE OVERLAP IS ALREADY COVERED. The sole current active+adoptable catalog member is SPEC-0094
#       (deploy), whose actual USE is expressed as the `deploy:` CONCERN section — and that overlap is
#       already caught by `_adoption_stance_violations` (exactly aiseller's deploy.convergence case). So the
#       residual "extension in use while its record waives" surfaces through the CONCERN cross-check, not a
#       missing extension one. (Cites: SPEC-0112, SPEC-0143, T-10493, T-10415.)
def _seed_catalog_waives(ops_path, members: list, write_text_atomic, *, fresh_carrier: bool,
                         cli_form: str = "bin/yitc-v2") -> list:
    """SPEC-0112 brownfield-compat seed (T-9596; consult option 1) — backfill the `extensions:` record
    born-COMPLETE so a fresh consumer AND a pre-SPEC-0112 brownfield consumer (one with NO `extensions:`
    section) pass the completeness sweep, WITHOUT silently auto-healing a CONSCIOUS gap. Seeds a forward-
    aware waive for every catalog member not already declared/waived IFF `fresh_carrier` (the carrier was
    just born this run OR its `extensions:` section was just PULLED by the rule-11 update — both are a fresh
    born section) OR the carrier's `extensions:` section is WHOLLY ABSENT (the rule-11 update precedent: a
    missing section is pulled born-waived; a PRESENT section — incomplete OR present-but-wrong-typed — is
    NEVER backfilled, it fails closed in the sweep, rule-1). The eligibility test is KEY-ABSENCE, not
    well-typed-presence (audit-post T-9596: a present-but-wrong-typed `extensions:` must NOT be treated as
    "absent" and mutated — it is a present section and stays the sweep's fail-closed concern). Returns the
    spec ids newly waived (empty = nothing to seed / not in a seed-eligible state). Idempotent."""
    import yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)
    if not members or not ops_path.exists():
        return []
    text = ops_path.read_text(encoding="utf-8")
    try:
        ops = state.load_ops_str(text) if text.strip() else None
    except yaml.YAMLError:
        return []                                        # malformed carrier — the sweep reports it; don't seed blind
    # KEY-absence (NOT well-typed-presence): the `extensions:` key truly missing is the wholly-absent
    # brownfield case; a present key (even wrong-typed) is a present section -> never backfill, fail closed.
    ext_key_present = isinstance(ops, dict) and "extensions" in ops
    if not (fresh_carrier or not ext_key_present):       # present (any shape) & not fresh -> fail-closed, never backfill
        return []
    declared, waived = _extensions_coverage(ops if isinstance(ops, dict) else {})
    uncovered = [m for m in members if m not in declared and m not in waived]
    if not uncovered:
        return []
    # Render the `__YITC_CLI__` token in the waive reason to the actual verb-invocation form (T-9769):
    # a consumer has NO local bin/yitc-v2, so the born re-entry command must be the engine `-C` form.
    entries = [(m, _CATALOG_WAIVE_REASON.format(sid=m).replace("__YITC_CLI__", cli_form))
               for m in uncovered]
    write_text_atomic(ops_path, _append_waives_entries(text, entries))
    return uncovered


def _sweep_extension_catalog_completeness(ops_path, members: list, _append_event, repo_root,
                                          cli_form: str = "bin/yitc-v2") -> None:
    """SPEC-0112 rule-1/2 — the fail-closed completeness sweep over the active+adoptable catalog set. For
    every catalog `member`, the consumer's `extensions:` record MUST carry an explicit DECLARE (a non-empty
    `adopts[].spec`) OR a FORWARD-AWARE WAIVE (a `waives[]` {spec, reason} with a NON-EMPTY reason). A
    MISSING member or a BARE/empty-reason waive is an ERROR (SystemExit non-zero) — never a silent pass.
    On refusal it emits `extension_catalog_completeness_refused` THROUGH the injected `_append_event` (the
    same governed journal path cmd_init uses for `consumer_init`; written BEFORE the exit, not a manual side
    effect). DISTINCT from the graph-free `_sweep_ops_carrier` — this one READS the engine catalog (via the
    pre-computed `members`). Self-contained (inline yaml/SystemExit) so cmd_init's injected-deps contract
    stays unchanged."""
    import sys
    import yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)
    if not members:                                      # empty authoritative set — nothing to complete
        return
    try:
        ops = state.load_ops(ops_path) if ops_path.exists() else None
    except yaml.YAMLError:
        ops = None                                       # a parse failure is the ops-sweep's error to report, not this one
    declared, waived = _extensions_coverage(ops if isinstance(ops, dict) else {})
    missing = [m for m in members if m not in declared and m not in waived]
    bare_waive = [m for m in members if m not in declared and m in waived and not waived[m]]
    if not missing and not bare_waive:
        return
    _append_event("extension_catalog_completeness_refused", None, {
        "spec": "SPEC-0112",
        "gate": "extension-catalog-completeness",
        "path": str(repo_root),
        "catalog": list(members),
        "missing": missing,
        "bare_waive": bare_waive,
    })
    lines = []
    if missing:
        lines.append("  • no declare-or-waive entry for active+adoptable catalog member(s): "
                     + ", ".join(missing))
    if bare_waive:
        lines.append("  • waive present but reason EMPTY — a waive must be FORWARD-AWARE (name the "
                     "waive->declare re-entry path) for: " + ", ".join(bare_waive))
    print(f"yitc-v2: {CONSUMER_OPS_CONTRACT} FAILS extension-catalog completeness (SPEC-0112 rule-1/2, "
          "fail-closed) — every active+adoptable catalog member needs an explicit DECLARE "
          "(`extensions.adopts: - spec: SPEC-XXXX`) OR a forward-aware WAIVE (`extensions.waives: "
          "- {spec: SPEC-XXXX, reason: <names the re-entry path>}`).\n" + "\n".join(lines)
          + "\nDiscover the catalog: `" + cli_form + " graph query extensions-catalog`.", file=sys.stderr)
    raise SystemExit(1)


# ── Truthful born-verify stance when a consumer already ships tests (T-9518 / X-0085; T-9719 retarget) ──
# The blanket "no land-verify layer yet" waiver reason the born carrier `verify:` section seeds is a LIE
# for a consumer that already ships a test suite (the social-scraper case: backend/tests/, 6 files) — it
# hides that a hermetic land-verify COMMAND should be wired into `verify.layers`. So at init, if a test
# dir is present, swap the verify-section reason for a truthful tests-EXIST-wire-a-command stance. A
# no-tests repo is UNCHANGED (carrier body == the generated born template). Purely a born-content honesty refinement:
# `verify` is single-home in the carrier `verify.layers` (SPEC-0152 rule 5/16) and the F-025 hermeticity
# contract is unchanged — no new mechanism, no new standing rule. T-9719 RETARGETED this from the retired
# standalone yitc-verify.yaml onto the carrier verify section (the migrated home).
# The exact reason VALUE the carrier template seeds — kept as a module constant so the swap is a targeted,
# FAIL-LOUD `.replace()` of a known semantic unit (raises on template drift via the assert in
# `_ops_carrier_body`), NOT a brittle positional newline-split (audit-pre T-9518 finding 1).
_BORN_VERIFY_SECTION_NO_LAYERS_REASON = (
    "Initialized via `bin/yitc-v2 init` — no land-verify layer declared yet; declare a `layers:` list "
    "(each {layer, command} or per-layer {layer, waiver:{reason}}) as this project's land-verify layers "
    "settle (SPEC-0152 rule 16).")

# The exact `deploy:` born-waiver reason VALUE the carrier template seeds (T-9772) — kept as a module
# constant so the migration-aware swap in `_ops_carrier_body` is a targeted, FAIL-LOUD `.replace()` of a
# known semantic unit (raises on template drift via the assert there), NOT a brittle positional split —
# the same pattern as `_BORN_VERIFY_SECTION_NO_LAYERS_REASON`. Carries BORN_WAIVER_MARKER, which the
# migration-aware swap PRESERVES (so the nightly born-waiver-freshness check still surfaces it, SPEC-0105
# rule 1).
_BORN_DEPLOY_WAIVER_NO_COMMAND_REASON = (
    "Initialized via `bin/yitc-v2 init` — no deploy command yet; replace with `command: <cmd>` once a "
    "deploy exists.")

# Candidate test-dir locations probed at init, in order (the two the social-scraper migration hit).
_TEST_DIR_CANDIDATES = ("tests", "backend/tests")

# Candidate DB-migrations dir locations probed at init (T-9772, X-0145) — the common alembic/django/rails
# layouts. Presence flips the born `deploy:` waiver reason to a migration-AWARE placeholder so a fresh
# consumer that HAS migrations is reminded up front that its deploy command must APPLY them (the boomrocket
# near-miss: a v2-native deploy path with no `alembic upgrade` step, prod ~10 migrations behind code).
_MIGRATIONS_DIR_CANDIDATES = ("migrations", "backend/migrations", "alembic", "backend/alembic", "db/migrate")


def _detect_test_dir(repo_root):
    """Return the first relative test-dir path under repo_root that is an existing NON-EMPTY directory
    (`tests/` or `backend/tests/`), else None. Non-empty so a stray empty `tests/` folder does not
    flip the stance. Pure read; no host dep (operates on the already-injected REPO_ROOT Path, so it
    adds no injected param to cmd_init — the pinned injected-deps contract stays unchanged, init.py
    module header)."""
    for rel in _TEST_DIR_CANDIDATES:
        d = repo_root / rel
        try:
            if d.is_dir() and any(d.iterdir()):
                return rel
        except OSError:
            continue
    return None


def _all_tests_script_runnable(test_dir) -> bool:
    """Is the kernel's bare `python3 <test_file>` sweep a VALID verify for this test dir? (T-10531 / X-0392)

    The sweep (`_run_verify_tests` — the mode-"probes" path a consumer takes when it declares no
    `verify.layers`) runs each `test_*.py` as a SCRIPT and reads exit 0 as pass. That is the ENGINE's own
    suite convention (tests/README §Run all), and it is sound ONLY for script-runnable tests. Against a
    PYTEST-layout file it is unsound in BOTH directions:
      * FALSE-RED — running a test as a script puts `tests/` on sys.path[0], not the repo root, so a test
        importing its own package dies `ModuleNotFoundError` (the X-0392 newborn: a suite that is GREEN
        under pytest RED-fails the land, and the consumer is born unlandable);
      * FALSE-GREEN — when the package IS importable (an installed consumer), the file exits 0 having run
        ZERO assertions, because there is no `__main__` block to run them (observed on ai-safety: all 3
        test files exit 0 under the sweep while pytest runs 65 tests).

    EVERY file must be script-runnable, not merely one (audit-pre F3): a single pytest-only file in a
    MIXED dir is enough to make the sweep unsound, and it is exactly the file that would be silently
    skipped. So: True iff every `test_*.py` carries an `if __name__ == "__main__"` block.

    FAIL-CLOSED to today's behavior: an empty glob or ANY read/decode error returns True ("the sweep is
    fine"), so `init` seeds nothing and the born state is byte-identical. Pure read; no host dep (keeps
    cmd_init's pinned injected-deps contract unchanged — see the module header).
    """
    import re as _re
    from pathlib import Path   # function-local, matching this module's import idiom

    _MAIN_RE = _re.compile(r"^if\s+__name__\s*==\s*['\"]__main__['\"]\s*:", _re.M)
    try:
        files = sorted(Path(test_dir).glob("test_*.py"))
    except OSError:
        return True
    if not files:
        return True
    for f in files:
        try:
            if not _MAIN_RE.search(f.read_text(encoding="utf-8")):
                return False          # a pytest-layout file — the bare sweep cannot validly run it
        except (OSError, UnicodeDecodeError):
            return True               # unreadable — prove nothing, change nothing
    return True


def _pytest_importable() -> bool:
    """Can the interpreter that will RUN the seeded command actually import pytest? (T-10531, audit-pre F2)

    The command `init` seeds is `python3 -m pytest …`, so the only proof that it will run is that `python3`
    can import pytest RIGHT HERE. A pyproject/requirements MENTION is not an installation (audit-pre F2) —
    seeding a command we cannot show is runnable would trade the wedge for a permanently-broken gate, which
    is worse. False => seed nothing. Never raises."""
    import subprocess

    try:
        return subprocess.run(["python3", "-c", "import pytest"],
                              capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _born_verify_layers_seed(repo_root, ops_verify) -> "dict | None":
    """The born `verify:` section for a consumer whose tests the bare sweep CANNOT validly run (T-10531).

    Returns the replacement `verify:` mapping (a covering `layers:` list), or None to leave the born
    carrier exactly as it is today. This is BORN-CONTENT HONESTY, not a new mechanism: the kernel already
    ships the machinery a pytest consumer needs — `_consumer_tests_delegation` (bin/lib/worktree.py,
    SPEC-0152 rule 16 / T-10438 / X-0297) SKIPS the bare sweep for any layer whose `covers:` names the
    tests dir, because that layer IS the verify for that surface. The newborn's only gap was that it was
    never BORN with such a layer, so the sweep ran and the consumer was born unlandable (X-0392).

    Seeding it into init's sanctioned direct-to-main bootstrap commit means the consumer's `main` carries
    a WORKING verify from birth, so its very first land — even a pure task-filing batch, which touches
    none of the verify-implementation globs and thus never trips the SPEC-0077 pinned re-run — passes the
    governed gate with NO `--no-tests` and NO `--rebaseline`. Nothing is weakened: the first land is still
    fully gated, by a verify that finally tells the truth about the consumer's tests (SPEC-0103 rule 2).

    SCOPED TO THE BROKEN PREDICATE — a ROOT `tests/test_*.py` dir, and nothing else. That glob is EXACTLY
    the one `_consumer_zero_probe_guard` short-circuits on, so it is the ONLY layout where the unsound bare
    sweep actually RUNS. A suite elsewhere (`backend/tests/`, the T-9518 shape) does NOT trip that
    short-circuit: the guard honors the born section waiver (mode "waiver"), the tests are not run at land,
    and there is no wedge and no false-green to fix. Seeding a command THERE would newly START running a
    possibly non-hermetic suite (a backend suite may need a DB / ports — the very F-025 concern the born
    waiver's truthful stance exists to raise) — a behavior change with no incident behind it (CHARTER §P1
    F4). So those consumers keep the born waiver + the T-9518 nudge, byte-identical. We mirror the guard's
    own predicate rather than `_detect_test_dir` precisely so the fix cannot reach past the defect.

    FAIL-CLOSED on every conjunct — any doubt returns None (byte-identical to today):
      * no ROOT tests/test_*.py, or the bare sweep is valid for it (every test is script-runnable);
      * pytest not importable by the seeding interpreter;
      * the consumer already ANSWERED: any declared `layers:`, or a waiver that is NOT the kernel-born
        placeholder. The discriminator is the EXISTING single-SoT `BORN_WAIVER_MARKER` (carried by every
        born reason, and PRESERVED by the T-9518/T-9772 truthful swaps) — a waiver reason WITHOUT it is a
        consumer-authored ANSWER and is never overwritten (audit-pre F1); one WITH it is a kernel
        placeholder this seed legitimately replaces (waiver XOR layers — the init sweep enforces
        exclusivity, so the placeholder is REPLACED, never left alongside).
    """
    from pathlib import Path   # function-local, matching this module's import idiom

    test_dir = "tests"                                # the guard's own predicate — see SCOPED, above
    root_tests = Path(repo_root) / test_dir
    try:
        if not sorted(root_tests.glob("test_*.py")):
            return None                               # the bare sweep never fires here — nothing to fix
    except OSError:
        return None
    if _all_tests_script_runnable(root_tests):
        return None                                   # the bare sweep is a valid verify here — leave it
    if isinstance(ops_verify, dict):
        if ops_verify.get("layers"):                  # the consumer already declared its layers
            return None
        waiver = ops_verify.get("waiver")
        if isinstance(waiver, dict):
            reason = str(waiver.get("reason") or "")
            if BORN_WAIVER_MARKER not in reason:      # a CONSUMER-AUTHORED waiver — never overwrite
                return None
    if not _pytest_importable():
        return None                                   # cannot prove the command runs — seed nothing
    return {"layers": [{
        "layer": "tests",
        "command": f"python3 -m pytest {test_dir}/ -q",
        "covers": [f"{test_dir}/**"],
    }]}


def _detect_migrations_dir(repo_root):
    """Return the first relative DB-migrations dir under repo_root that is an existing NON-EMPTY directory
    (`_MIGRATIONS_DIR_CANDIDATES`), else None (T-9772, X-0145). Non-empty so a stray empty folder does not
    flip the stance — the EXACT mirror of `_detect_test_dir` (same pure-read, no-injected-dep contract, so
    cmd_init's pinned injected-deps contract stays unchanged). Used ONLY to make the born `deploy:` waiver
    reason more truthful (a born-content honesty refinement, NOT a gate)."""
    for rel in _MIGRATIONS_DIR_CANDIDATES:
        d = repo_root / rel
        try:
            if d.is_dir() and any(d.iterdir()):
                return rel
        except OSError:
            continue
    return None


def _swap_born_verify_waiver_for_layers(body: str, seed: dict) -> str:
    """FAIL-LOUD swap of the born `verify:` section's KERNEL waiver for a covering `layers:` list (T-10531).

    The born template's verify section is structurally exactly:
        verify:
          waiver:
            reason: "<_BORN_VERIFY_SECTION_NO_LAYERS_REASON>"
    (plus the section's guidance comments, which are PRESERVED). Replacing the waiver mapping with the
    seeded layers keeps the carrier's `layers` XOR `waiver` exclusivity (the init sweep enforces it), so
    the placeholder is REPLACED, never left alongside. Same FAIL-LOUD posture as its sibling swaps: if the
    generated template's shape drifted, raise rather than silently mis-render (audit-pre T-9518 finding 1).
    """
    assert _BORN_VERIFY_SECTION_NO_LAYERS_REASON in body, (
        "init: generated born template verify-section reason drifted from _BORN_VERIFY_SECTION_NO_LAYERS_REASON — "
        "cannot seed verify.layers safely; run `yitc-v2 graph build` (T-10531).")
    lines = body.splitlines(keepends=True)
    ri = next(i for i, ln in enumerate(lines) if _BORN_VERIFY_SECTION_NO_LAYERS_REASON in ln)
    assert lines[ri - 1].rstrip("\n") == "  waiver:" and lines[ri].rstrip().endswith('"'), (
        "init: born template verify-waiver SHAPE drifted (expected a `  waiver:` line directly above a "
        "single-line `    reason: \"...\"`) — cannot seed verify.layers safely; run `yitc-v2 graph build` "
        "(T-10531).")
    ly = seed["layers"][0]
    block = ("  layers:\n"
             f"    - layer: {ly['layer']}\n"
             f"      command: {ly['command']}\n"
             "      covers:\n"
             + "".join(f"        - {c}\n" for c in ly["covers"]))
    return "".join(lines[:ri - 1] + [block] + lines[ri + 1:])


def _ops_carrier_body(repo_root) -> str:
    """Compose the born yitc-ops.yaml carrier body from repo contents — INDEPENDENT, COMPOSABLE
    born-content honesty refinements (each a targeted FAIL-LOUD `.replace()` of a known reason constant;
    neither is a gate — a no-tests, no-migrations repo returns the generated born template byte-identical):

    - VERIFY LAYERS (T-10531 / X-0392): when the repo ships tests the kernel's bare `python3 <file>` sweep
      CANNOT validly run (a pytest layout — see `_all_tests_script_runnable`), SEED the covering
      `verify.layers` command in place of the born waiver, so the consumer is BORN LANDABLE. Without it a
      newborn pytest consumer is born unlandable: the sweep false-REDs its actually-green suite, and every
      governed escape (declare-layers-then-land, `--rebaseline`) is itself blocked — only the owner-gated
      `--no-tests` unwedged it. Takes PRECEDENCE over the VERIFY-reason swap below: once the command is
      wired FOR the consumer, the "wire a command yourself" nudge is obsolete (and the two are mutually
      exclusive — layers XOR waiver).
    - VERIFY reason (T-9518 / X-0085, retargeted onto the carrier by T-9719): when tests exist but we could
      NOT safely seed a command, swap the `verify:` born-waiver reason to a truthful
      tests-EXIST-wire-a-`verify.layers`-command stance.
    - DEPLOY (T-9772 / X-0145): swap the `deploy:` born-waiver reason to a migration-AWARE placeholder when
      repo_root ships a DB-migrations dir — so a fresh consumer that HAS migrations is reminded up front
      that its deploy command must APPLY them (the boomrocket near-miss: a deploy path with no migrate step).

    FAIL-LOUD if any template reason value drifted (so a swap can never silently mis-render — audit-pre
    T-9518 finding 1). Each truthful reason KEEPS the BORN_WAIVER_MARKER so the nightly born-waiver-freshness
    check still surfaces it (SPEC-0105 rule 1)."""
    body = _born_ops_template()
    test_dir = _detect_test_dir(repo_root)
    # T-10531: the born carrier has no consumer-authored answer by construction (we are generating it), so
    # pass `None` — the seed's own conjuncts (test dir + sweep-unsound + pytest importable) still gate it.
    verify_seed = _born_verify_layers_seed(repo_root, None)
    if verify_seed is not None:
        body = _swap_born_verify_waiver_for_layers(body, verify_seed)
    elif test_dir is not None:
        assert _BORN_VERIFY_SECTION_NO_LAYERS_REASON in body, (
            "init: generated born template verify-section reason drifted from _BORN_VERIFY_SECTION_NO_LAYERS_REASON — "
            "the concern born (specs) must still carry it; run `yitc-v2 graph build` (T-9518/T-9719/T-10038).")
        truthful = (
            "Initialized via `bin/yitc-v2 init` — tests EXIST (" + test_dir + "/) but no hermetic land-verify "
            "command is wired yet; replace this waiver with a `layers:` list whose `command:` per layer runs "
            "them HERMETICALLY (isolated project, ephemeral ports — may need a DB) AND CONCURRENCY-SAFELY — "
            "`land` runs the verify command and dispatch runs Build workers in PARALLEL (D-0037), so two "
            "concurrent worker `land`s each run it at once; it MUST use unique-per-run resource names (a "
            "random/ephemeral host port, an isolated per-run DB name / container — no fixed port and no shared "
            "DB name) so concurrent runs never collide, per the F-025 hermeticity contract (SPEC-0152 rule 16).")
        body = body.replace(_BORN_VERIFY_SECTION_NO_LAYERS_REASON, truthful)
    migrations_dir = _detect_migrations_dir(repo_root)
    if migrations_dir is not None:
        assert _BORN_DEPLOY_WAIVER_NO_COMMAND_REASON in body, (
            "init: generated born template deploy-section reason drifted from _BORN_DEPLOY_WAIVER_NO_COMMAND_REASON — "
            "the concern born (specs) must still carry it; run `yitc-v2 graph build` (T-9772/T-10038).")
        deploy_truthful = (
            "Initialized via `bin/yitc-v2 init` — DB migrations EXIST (" + migrations_dir + "/) but no deploy "
            "command is wired yet; replace this waiver with `command: <cmd>` — and that command MUST APPLY the "
            "migrations (e.g. `alembic upgrade head` / `python manage.py migrate`) before/as it serves the new "
            "revision. A deploy that ships schema-dependent code WITHOUT applying its migrations will break prod "
            "(the boomrocket near-miss, X-0145); a migration-bearing deploy is deploy-class C1 (SPEC-0097 §2).")
        body = body.replace(_BORN_DEPLOY_WAIVER_NO_COMMAND_REASON, deploy_truthful)
    return body


def _legacy_verify_to_section(legacy: dict) -> dict:
    """T-9719 (SPEC-0152 rule 5/16) — map a parsed legacy yitc-verify.yaml contract → the carrier
    `verify:` section dict. The single `command:` becomes ONE `default` layer (a per-layer hermetic
    command, F-025); a `waiver: true` (+ reason) becomes a section-level waiver. A born/malformed
    contract (neither a usable command nor a reasoned waiver) falls back to a section waiver carrying a
    migration reason — never an UNANSWERED section (the sweep would then fail closed). The kernel maps
    shape, never command correctness (rule 3)."""
    cmd = legacy.get("command") if isinstance(legacy, dict) else None
    if isinstance(cmd, str) and cmd.strip():
        return {"layers": [{"layer": "default", "command": cmd.strip()}]}
    reason = ""
    if isinstance(legacy, dict) and legacy.get("waiver") is True:
        reason = str(legacy.get("reason") or "").strip()
    if not reason:
        reason = ("Migrated from a legacy yitc-verify.yaml with no usable command (SPEC-0152 rule 5/16, "
                  "T-9719); declare a `verify.layers` list once a hermetic land-verify command settles.")
    return {"waiver": {"reason": reason}}


def _replace_ops_section(ops_text: str, section: str, new_block: str) -> str:
    """Replace the top-level `<section>:` block in a carrier text with `new_block`. The block spans from
    the column-0 `<section>:` line to the next column-0 `<name>:` line (or EOF) — the SAME section-boundary
    logic as `_ops_born_sections`. `new_block` must itself start at column 0 and end with a newline. Returns
    ops_text UNCHANGED if the section is absent (the caller guarantees init seeded/pulled it first)."""
    import re
    lines = ops_text.splitlines(keepends=True)
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z_][\w-]*):", line)
        if m and not line[:1].isspace():
            if m.group(1) == section:
                start = i
            elif start is not None:
                end = i
                break
    if start is None:
        return ops_text
    return "".join(lines[:start]) + new_block + "".join(lines[end:])


def _inject_nested_subfield(text: str, parent_path: str, fragment: str) -> "str | None":
    """T-10031, depth-generalized by T-12165 — insert a born subfield `fragment` at the END of the
    block named by the DOTTED `parent_path` (after its existing deeper-indented content, BEFORE the
    next sibling at the parent's own indent, or the end of the enclosing block, or EOF),
    non-destructively. `fragment` is verbatim born text already indented at its own carrier depth and
    newline-terminated. Returns the new text, or None if any segment of the parent path is absent
    (caller skips — the parent-present precondition is enforced upstream by `_consumer_carrier_skew`).

    `parent_path` is `deploy` for `deploy.policy` and `security.audit` for
    `security.audit.profile_snapshot`; a single segment walks exactly one iteration and reproduces the
    original column-0 behaviour byte-for-byte. Each segment narrows the search window to its own
    block, which is what keeps a deeper descent from running past its parent into an unrelated
    section: a shallower line cannot match the segment's indent pattern, but it also cannot be
    REACHED, because the window already ended. Same section-boundary logic as `_ops_born_sections` /
    `_replace_section_block`, applied per level."""
    import re
    lines = text.splitlines(keepends=True)
    start, end = 0, len(lines)
    for depth, segment in enumerate(parent_path.split(".")):
        indent = depth * 2
        pat = re.compile(r"^ {%d}([A-Za-z_][\w-]*):" % indent)
        seg_start = None
        seg_end = end
        for i in range(start, end):
            line = lines[i]
            m = pat.match(line)
            if m and line[indent:indent + 1] != " ":
                if m.group(1) == segment:
                    seg_start = i
                elif seg_start is not None:
                    seg_end = i
                    break
        if seg_start is None:
            return None                                   # this segment is not in the carrier
        start, end = seg_start, seg_end
    head = "".join(lines[:end])
    sep = "" if (not head) or head.endswith("\n") else "\n"
    return head + sep + fragment + "".join(lines[end:])


def _migrate_legacy_verify_yaml(repo_root, legacy_name, ops_name, write_text_atomic, _run_git_cap,
                                *, ops_path=None, apply: bool = True) -> "dict | None":
    """T-9719 (SPEC-0152 rule 5/16, X-0140) — the one-time MIGRATION of the RETIRED single-command
    yitc-verify.yaml into the carrier `verify.layers` section. There must never be two live verify homes
    (rule 5); `land` REFUSES a present yitc-verify.yaml (bin/lib/worktree.py guard), so init folds it.

    If a legacy `<legacy_name>` is present: parse it, fold its contract into the `<ops_name>` `verify:`
    section (command → a `default` layer; waiver → a section waiver — via `_legacy_verify_to_section`),
    REPLACE the carrier's `verify:` block in TEXT (preserving every other section's comments/values), then
    REMOVE the legacy file (unlink + `git rm --cached --ignore-unmatch` so the bootstrap commit records a
    TRACKED file's deletion; mirrors `_sweep_retired_surfaces`). Returns `{'mode','removed'}` (mode ∈
    layers|waiver) or None (no legacy file → no-op). The carrier MUST already carry a `verify:` section
    (init seeds/pulls it before this runs); if it somehow does not, the legacy section is still APPENDED
    so the migrated stance is never lost. Self-contained (inline yaml + already-injected deps) so cmd_init's
    injected-deps contract stays unchanged (init.py module header — the pinned == assertion, lesson
    `governed-consumer-config-write-via-init-extension`).

    `ops_path` overrides the carrier location (the T-10271 `--dry-run` scratch overlay; it defaults to the
    re-derived `repo_root/ops_name`, so a real run is byte-unchanged) — the carrier is written HERE and
    re-read by the sweeps AFTER, so a dry-run must fold into the same overlay copy the rest of the chain
    reads. `apply=False` skips the legacy file's unlink (the other write that bypasses the seam)."""
    import yaml

    from lib import state  # CHARTER §P5 one parser library — the legacy-carrier reader (T-9740)
    legacy_path = repo_root / legacy_name
    if not legacy_path.exists():
        return None
    try:
        legacy = state.load_str(legacy_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        legacy = {}
    section = _legacy_verify_to_section(legacy if isinstance(legacy, dict) else {})
    # Serialize the verify section with proper YAML quoting, then prepend ONE migration comment line.
    body = yaml.safe_dump({"verify": section}, default_flow_style=False, sort_keys=False, width=4096)
    block = ("verify:\n"
             "  # MIGRATED from the retired yitc-verify.yaml by `bin/yitc-v2 init` (SPEC-0152 rule 5/16,\n"
             "  # T-9719) — the SOLE land-verify home is now this carrier `verify.layers` section.\n"
             + "".join(body.splitlines(keepends=True)[1:]))   # drop the dumped `verify:\n` (replaced above)
    ops_path = ops_path if ops_path is not None else repo_root / ops_name
    ops_text = ops_path.read_text(encoding="utf-8") if ops_path.exists() else ""
    if "\nverify:" in ("\n" + ops_text):
        new_text = _replace_ops_section(ops_text, "verify", block)
    else:
        new_text = ops_text + ("" if ops_text.endswith("\n") or not ops_text else "\n") + block
    # The fold CHANGES the verify stance (a legacy contract becomes a live `layers:` declaration) — so the
    # SAME act re-records the verify adoption to MIRROR the stance it just created, else the T-10481
    # stance-sweep (which runs AFTER this fold in the init chain) refuses init's own result: the record
    # would still read the born `waive`/`na` over a now-DECLARED section. Mirroring here is honest — the
    # decision was made by THIS fold (owner stays the `init` sentinel; variant A does not gate adopt@init).
    if "layers" in section and "\nadoption:" in ("\n" + new_text):
        import re as _re
        new_text = _re.sub(
            r"(- concern: verify\n(?:    [^\n]*\n)*?    status: )(?:waive|na)\b",
            r"\1adopt", new_text, count=1)
    write_text_atomic(ops_path, new_text)
    # REMOVE the retired file (stage the deletion so the bootstrap commit records it — see _sweep_retired_surfaces).
    if apply:
        legacy_path.unlink()
        _run_git_cap(["rm", "--cached", "--quiet", "--ignore-unmatch", "--", legacy_name], repo_root)
    return {"mode": "layers" if "layers" in section else "waiver", "removed": legacy_name}


# Born .gitattributes (T-9519 / X-0086): the kernel .gitattributes carries `events.jsonl merge=union`
# (SPEC-0002 concurrent-merge design). A consumer rides the SAME concurrent-worktree + journal-union
# model (D-0037), so WITHOUT this attribute a concurrent worker `land` hits a non-union events.jsonl
# conflict (this REALLY happened — project T-0015 forced a manual merge). Replicate the kernel line +
# its rationale comment so the consumer's union-merge works out of the box. MODULE-LEVEL (not host-
# injected) by the same injected-deps-contract reasoning as the ops carrier above.
_BORN_GITATTRIBUTES_LINE = "events.jsonl merge=union"
# T-11446 (SPEC-0190 rules 1+3): the journal's ARCHIVE SEGMENTS are physical units of the SAME logical
# journal, so a consumer must be born with `merge=union` on them too — the line above is a LITERAL PATH
# and cannot match `archive/events-2026-08-16.jsonl`. The pattern is `bin/lib/events.py#archive_glob`'s
# (`<stem>-*<suffix>`) under `events.ARCHIVE_DIRNAME`; it is RE-SPELLED here rather than imported,
# because this module's born constants are deliberately module-level and import-free (the injected-deps
# contract above). `tests/test_t11446_archive_admission.py` asserts these literals still equal what
# `lib.events` derives, so the re-spelling cannot drift silently.
_BORN_GITATTRIBUTES_ARCHIVE_LINE = "archive/events-*.jsonl merge=union"

# (line, block) pairs — PLURAL, because the append path must backfill EACH MISSING line INDEPENDENTLY.
# A consumer initialised before T-11446 already carries the live line; an idempotency check keyed on
# that one line alone would report "nothing to do" and the archive line would never arrive (the
# admission has to reach EXISTING consumers, not just new ones). Order is the write order.
_BORN_GITATTRIBUTES_BLOCKS = (
    (_BORN_GITATTRIBUTES_LINE,
     "# events.jsonl is an append-only journal (SPEC-0002). Under parallel writing-session worktrees\n"
     "# (D-0037), two branches each append distinct rows; the built-in `union` merge driver keeps BOTH\n"
     "# sides instead of raising a conflict, so a concurrent worker `land` never hits a journal conflict.\n"
     "# Physical line order is NO LONGER chronology — order by `ts`. Seeded by `yitc-v2 -C <path> init`.\n"
     f"{_BORN_GITATTRIBUTES_LINE}\n"),
    (_BORN_GITATTRIBUTES_ARCHIVE_LINE,
     "\n"
     "# An ARCHIVE SEGMENT of that journal (SPEC-0190 rule 1) is the same logical journal in another\n"
     "# physical file, so it inherits the same union driver. The line above is a literal path and does\n"
     "# NOT match it; without this one every landing branch that rotates would conflict on its own copy.\n"
     f"{_BORN_GITATTRIBUTES_ARCHIVE_LINE}\n"),
)
_BORN_GITATTRIBUTES = "".join(block for _line, block in _BORN_GITATTRIBUTES_BLOCKS)


# ── born agent SCRATCH path (T-11308 / X-1009) ────────────────────────────────────────────────────
# WHY a scratch path at all: a sandboxed agent commonly cannot write to /tmp (the external V1
# scope-guard hook confines writes to the owned project root — see patterns/onboarding-onto-yitc-
# runbook.md), and a long YAML block scalar cannot ride argv without the shell executing its own
# backticks (the E-0054 class). That leaves the repo CHECKOUT as the only writable place — which is
# exactly where the shared commit core's verb-owned `git add -A` sweeps (`cli.py#_commit_worktree`,
# whose contract explicitly delegates ephemera exclusion to `.gitignore`). So an agent's working
# file rode into a governance commit with no refusal and no warning. The runbook ALREADY prescribes
# "a gitignored `.scratch/`" as the supported workaround; nothing delivered it. This does.
#
# The `.scratch/*` + `!.scratch/.gitkeep` pair is load-bearing, not decoration. The exclude must
# name the dir CONTENTS (`.scratch/*`), never the DIRECTORY (`.scratch/`): git cannot re-include a
# path below an EXCLUDED directory, so the directory form would make the negation dead and the
# marker untracked — and an untracked marker does not materialize in a `worktree new` checkout,
# which is precisely where the card needs the path to exist.
#
# DELIBERATELY NOT a member of `_BORN_GITIGNORE_LINES`. That tuple is single-SoT for TWO things: the
# born ignore lines AND the `git rm --cached` untrack pathspecs derived from them. A consumer that
# already TRACKS files under `.scratch/` must not have them untracked by an init re-run (that would
# silently remove their content from the tree), and a `!`-negated entry would derive a nonsense
# pathspec in that loop. Module-level beside its sole consumer — the same injected-deps reasoning as
# `_BORN_GITATTRIBUTES_LINE` above.
_BORN_SCRATCH_DIR = ".scratch"
_BORN_SCRATCH_IGNORE_LINES = (".scratch/*", "!.scratch/.gitkeep")

# ── born UNDECLARED DOT-DIRECTORY deny (T-11913) — the CONSUMER side of T-11882 ────────────────────
# T-11882 inverted the polarity in the ENGINE's own .gitignore: default-DENY a dot-prefixed DIRECTORY
# (`.*/`) and require an explicit DECLARATION (`!/<dir>/`) to re-include one, so an UNDECLARED scratch
# dir is visibly absent from `git status` the moment its author creates it instead of riding
# `_commit_worktree`'s verb-owned `git add -A` into a ship diff. That rule lived ONLY in the engine.
# MEASURED (2026-08-20..2026-08-30 window): 7 of the 9 stray scratch files that reached a commit
# across the fleet landed in CONSUMERS — `.rl/*.log` + `.tmpwork/absorb.yaml` (kupiclub),
# `.yitc-tmp/{fix,msg}.txt` (aiseller) — every one dot-prefixed, i.e. exactly the shape the rule denies.
#
# WHY THE ENGINE'S PAIR CANNOT BE SHIPPED VERBATIM (the correctness point, not a symmetry point).
# `!/.claude/` is EXACT for the engine because the engine's census is exact FOR THE ENGINE: `.claude/`
# is its only tracked dot-prefixed directory. It is WRONG for a consumer. Re-derived per repo with
# `git ls-files` on 2026-09-01: aiseller TRACKS `.github/`; boomrocket TRACKS `.claude/` AND
# `.deploy-state/`; kupiclub TRACKS `.rl/` and `.scratch/`. A verbatim born `.*/` + `!/.claude/` would
# leave `.github/` under the deny in aiseller and SILENTLY DENY a new file under `.github/workflows` —
# hiding real work, which is strictly worse than the junk the rule removes. So the allowlist is
# DERIVED PER CONSUMER from the dot-directories that consumer ALREADY TRACKS, never copied: the
# engine's `!/.claude/` is simply what this builder HAPPENS to derive for a repo whose only tracked
# dot-dir is `.claude/`.
#
# WHY DERIVING FROM TRACKED PATHS IS THE RIGHT SIGNAL. A `.gitignore` never applies to a path git
# already tracks, so this can never drop committed work either way; what it protects is the NEXT file
# added under a directory the consumer has already declared-by-tracking. Tracking IS that declaration,
# and it is machine-readable — no per-consumer hand list to drift.
#
# WHAT THE DENY EXCLUDES (the cohort complement, stated rather than silently widened). The rule
# selects dot-prefixed DIRECTORIES. A new undeclared scratch dir with a NON-dot name (`scratchpad/`)
# stays unignored and still rides an add-all — the residual T-11882 recorded and left deliberately,
# because a blanket deny on all new directories would break the load-bearing negative (a legitimate
# new source dir must still land). It is NOT widened here.
#
# INTERACTION with `_BORN_SCRATCH_IGNORE_LINES`. A consumer that tracks `.scratch/.gitkeep` derives
# `!/.scratch/`, which re-includes the DIRECTORY. Its CONTENTS stay ignored by the `.scratch/*` line
# above — that denial is the deliberate T-11308 declaration, not this deny, and is unaffected here.
#
# DELIBERATELY NOT a member of `_BORN_GITIGNORE_LINES` — the same reason recorded at
# `_BORN_SCRATCH_IGNORE_LINES` above and at `_BORN_ATOMIC_TMP_IGNORE_LINES` below. That tuple is
# single-SoT for TWO things: the born ignore lines AND the `git rm --cached` untrack pathspecs derived
# from each member. A `!`-negated line derives a nonsense pathspec, and git rejecting it makes the
# whole `ls-files --ignored --cached` call non-zero — silently disabling the untracking of the real
# `.yitc/` churn that loop exists for.
_BORN_DOT_DIR_DENY_LINE = ".*/"


def _born_dot_dir_ignore_lines(tracked_paths, denied_dot_dirs=()) -> tuple:
    """Build the born undeclared-dot-directory deny + THIS consumer's derived re-include allowlist.

    PURE by construction (its purity is what T-11913 AC3 tests against fixtures reproducing the three
    measured tracked sets): `tracked_paths` is an iterable of repo-relative tracked file paths, e.g.
    the output of `git ls-files`. Returns `(".*/", "!/<dir>/", ...)` with the re-includes sorted.

    EVERY dot-prefixed directory PREFIX in a path's chain is emitted, not merely the first: a tracked
    `.github/.foo/x` yields BOTH `!/.github/` and `!/.github/.foo/`, because `.*/` matches a
    dot-prefixed directory at ANY depth, so re-including only the outer one would leave the inner one
    denied. Sorted order puts the shallower prefix first and gitignore's last-match-wins then resolves
    the nesting correctly. A repo that tracks no dot-directory gets the bare deny — correct: it has
    declared nothing.

    NOTHING IS RE-INCLUDED THAT THE INPUT DOES NOT CARRY. There is no constant in the allowlist: the
    sanctioned `.scratch/` re-include exists because `cmd_init` feeds this builder the born marker
    `.scratch/.gitkeep` ALONGSIDE `git ls-files` — that marker is a path init itself TRACKS in its
    bootstrap commit, so `.scratch/` is a tracked dot-directory by the same rule as every other entry,
    just one whose tracking this very run establishes. It has to be in the set: `.*/` excludes the
    DIRECTORY and git cannot re-include a path below an excluded directory, which killed the
    `!.scratch/.gitkeep` marker T-11308 needs TRACKED for the path to materialize in a fresh worktree
    (measured at T-11913 Stage-6: `test_t11308_scratch_path.py` AC1 failed). Re-including the
    DIRECTORY restores traversal; its CONTENTS stay ignored by the earlier `.scratch/*` line, so
    T-11308's design is unchanged.

    THE ONE SUBTRACTION. `denied_dot_dirs` — dot-directories the OTHER born rules deny ON PURPOSE,
    passed in by `cmd_init` from the single-SoT `_BORN_GITIGNORE_LINES` rather than re-listed here. A
    consumer that TRACKED `.yitc/` before init ran would otherwise derive `!/.yitc/`, which un-ignores
    the very churn T-9310's `git rm --cached` loop exists to untrack — that loop selects on `ls-files
    --ignored`, so re-including the dir silently disables it (measured at T-11913 Stage-6:
    `test_t9310_gitignore_first_untrack.py` failed with "init did not untrack pre-existing churn:
    ['.yitc/scratch.txt']"). It only ever REMOVES a re-include, so it cannot widen what is allowed.
    Both terms are pinned by their own arms in tests/test_t11884_consumer_dot_dir_deny.py.
    """
    denied = tuple(str(d).strip("/") for d in denied_dot_dirs if str(d).strip("/"))
    dirs = set()
    for path in tracked_paths:
        parts = [seg for seg in str(path).strip().split("/") if seg]
        for i, seg in enumerate(parts[:-1]):          # directory components only, never the file
            if not seg.startswith("."):
                continue
            prefix = "/".join(parts[:i + 1])
            if any(prefix == d or prefix.startswith(f"{d}/") for d in denied):
                continue
            dirs.add(prefix)
        # NB: no `break` — the whole chain is walked (see the docstring's nested-dot-dir case).
    return (_BORN_DOT_DIR_DENY_LINE, *(f"!/{d}/" for d in sorted(dirs)))
# ── born ATOMIC-WRITE TEMP rules (T-10992) — the consumer side of the T-10330/T-10887/T-10755/
# T-10988/T-11448 family ───────────────────────────────────────────────────────────────────────────
# `write_text_atomic` writes via `mkstemp(prefix=f".{name}.", suffix=".tmp")` + `os.replace`, so a
# process KILLED mid-write (concurrent land / timeout) strands that dot-prefixed scratch file NEXT TO
# its target. In the kernel repo those strands rode `_commit_worktree`'s verb-owned `git add -A` into
# ship diffs until the .gitignore entries above closed each scope. T-10988 enumerated the CONSUMER
# side and explicitly waived it with "the fix would be _BORN_GITIGNORE_LINES — routed to a followup";
# THIS is that followup. A consumer runs the SAME verbs under `-C <path>` — REPO_ROOT is its tree —
# so it receives the same strand shapes with no rule of its own to catch them.
#
# THE ENUMERATION (AC1). Every scope a consumer's tree can receive an atomic write into, labelled:
#   COVERED BY A RULE BELOW
#     <repo root>   init.py (yitc-ops.yaml, MEMORY.md, AGENTS.md, CLAUDE.md, .gitignore,
#                   .gitattributes) + v1_quiesce.py:134 (.no-v1-hooks)  -> /.*.tmp
#     bin/          init.py (the SPEC-0154 security-audit runner + its .trigger)  -> /bin/**/.*.tmp
#     lessons/      init.py (the born README.md)                      -> /lessons/**/.*.tmp
#     patterns/     init.py (the born .gitkeep)                       -> /patterns/**/.*.tmp
#     graph/        init.py (the born .gitkeep) + graph.py (index.json, floor-trigger-map.md,
#                   activation-checklist.md, concern-registry.json, born-ops.yaml, seed views)
#                                                                     -> /graph/**/.*.tmp
#     specs/        init.py (_REMATERIALIZE_TEMPLATES) + spec.py      -> /specs/**/.*.tmp
#     tasks/        init.py (_REMATERIALIZE_TEMPLATES) + task.py      -> /tasks/**/.*.tmp
#     decisions/    audit.py / plan.py (the audit YAMLs)              -> /decisions/**/.*.tmp
#     errors/       error.py / audit.py                               -> /errors/**/.*.tmp
#     plans/        plan.py (_write_draft)                            -> /plans/**/.*.tmp
#     ideas/        plan.py (the plan->idea demote)                   -> /ideas/**/.*.tmp
#     tests/        verify_runner.py (tests/verify-durations.json)    -> /tests/**/.*.tmp
#     archive/      events.py (rotate_journal — each archive segment)  -> /archive/**/.*.tmp
#
#   ALREADY COVERED — no rule of its own; the covering rule IS the waive
#     events.jsonl  worktree.py / evidence_custody.py / events.py (the journal rewrites, the fold,
#                   the pre-ff unwind, rotation's live-segment rewrite). The kernel needs its own
#                   `.events.jsonl.*.tmp` because ITS root scope rule is not the only thing in play
#                   there; a CONSUMER's root strand is already matched by `/.*.tmp` below, and the
#                   second foldable journal at `.yitc/events.jsonl` sits under a dir that is
#                   born-ignored WHOLE. A born copy of the kernel rule would match nothing the
#                   consumer set does not already match — measured, not assumed: the differential
#                   arm of tests/test_t10992_born_gitignore_tmp_scopes.py could not find an input
#                   the rule changed, which is what removed it from this tuple (CHARTER §P1).
#
#   PROVABLY CANNOT STRAND IN A CONSUMER (4) — no rule added; the reason IS the waive
#     release-view/        ENGINE-ONLY. `_write_release_view` writes under ENGINE_ROOT behind a
#                          `not _is_consumer_build()` guard, so the directory never exists here.
#     .yitc/               the WHOLE dir is born-ignored (`_BORN_GITIGNORE_LINES[0]`), and the
#                          unanchored journal rule below also matches `.yitc/.events.jsonl.*.tmp`.
#     journal-sync-state/  the WHOLE dir is born-ignored (`_BORN_GITIGNORE_LINES`).
#     .scratch/            its CONTENTS are born-ignored (`_BORN_SCRATCH_IGNORE_LINES`).
#
# NOT a CHARTER §P5 breach (derived artifacts are COMMITTED, never gitignored): each rule matches ONLY
# the dot-prefixed in-flight scratch shape, which SPEC-0131 Rule 3 classifies as a normal transient and
# never a derived view — a consumer's real task/decision/spec/error/plan/idea YAMLs, its graph views
# and its root handbook docs are never dot-prefixed with a `.tmp` suffix, so they keep shipping.
# DELIBERATELY NOT the blanket `.*.tmp`, which would silently drop them. `**` is load-bearing on the
# directory rules (a gitignore `*` does not cross `/`); each leading `/` anchors the rule to the
# consumer's OWN repo root, never an unrelated nested dir. `/.*.tmp` is the ROOT scope and the widest
# of the set — bounded by being root-anchored (no subdirectory reach), dot-prefixed and
# `.tmp`-suffixed; none of the dotfiles init delivers to a consumer root carries a `.tmp` suffix.
#
# DELIBERATELY NOT a member of `_BORN_GITIGNORE_LINES` — the same reason recorded at
# `_BORN_SCRATCH_IGNORE_LINES` above. That tuple is single-SoT for TWO things: the born ignore lines
# AND the `git rm --cached` untrack pathspecs derived from each member (`_ln.rstrip("/")` ->
# `<name>/` + `:(glob)**/<name>/**`). A rooted glob rule would derive a nonsense pathspec, and git
# rejecting it makes the whole `ls-files --ignored --cached` call non-zero — silently disabling the
# untracking of the real `.yitc/` churn that loop exists for. Module-level beside its sole consumer
# (no new injected `cmd_init` kwarg: `test_t9380_init_extraction_adoption.py` asserts that set by
# `==` and `test_t10171` AC6 forbids growing it) — the same injected-deps reasoning as above.
_BORN_ATOMIC_TMP_IGNORE_LINES = (
    "/archive/**/.*.tmp",
    "/tasks/**/.*.tmp",
    "/decisions/**/.*.tmp",
    "/specs/**/.*.tmp",
    "/errors/**/.*.tmp",
    "/plans/**/.*.tmp",
    "/ideas/**/.*.tmp",
    "/graph/**/.*.tmp",
    "/lessons/**/.*.tmp",
    "/patterns/**/.*.tmp",
    "/bin/**/.*.tmp",
    "/tests/**/.*.tmp",
    "/.*.tmp",
)

# ── born MKTEMP PAYLOAD-FILE rule (T-11947) — the CONSUMER side of the X-1226 strand ──────────────
# The kernel PRESCRIBES this ephemeral file: two sites in bin/lib/cli.py tell a session to compose an
# over-long event payload under a WORKTREE-LOCAL per-invocation temp file, `f=$(mktemp -p .)`, rather
# than a fixed shared name (T-11676 / X-1132). `mktemp -p .` with no template yields a NON-dot
# `tmp.XXXXXXXXXX` at the repo ROOT, which `_commit_worktree`'s verb-owned `git add -A` — whose
# contract delegates ephemera exclusion entirely to `.gitignore` — then sweeps into the ship diff.
# MEASURED, not assumed: that is exactly what happened in aiseller (X-1226), where the stray rode into
# commit 2cf2dbd as a 4th file where 3 were intended. THE REPORTER IS A CONSUMER, so an engine-only
# `.gitignore` entry does not reach the repo the defect was observed in — this is the half that does.
#
# THE PAIR, and why the second line is load-bearing. `/tmp.??????????` is root-anchored, carries the
# literal `tmp.` prefix and EXACTLY TEN `?` (mktemp's template length; a gitignore `?` never crosses
# `/`), so it matches the prescribed shape and nothing else — never `tmp_helper.py`, `tmpdir_notes.md`,
# `bin/tmp.py` or `tmp.data/`, which is what keeps it off the blanket `tmp*` that CHARTER §P5 forbids
# (derived artifacts are COMMITTED, never gitignored). `!/tmp.??????????/` follows it because a pattern
# with no trailing slash matches a DIRECTORY too: the dir-only negation, placed AFTER the deny
# (last-match-wins), re-includes a root directory of that shape while leaving the FILE ignored, so this
# rule never reaches the non-dot scratch-DIRECTORY residual T-11882 recorded and left deliberately open.
#
# DELIBERATELY NOT a member of `_BORN_GITIGNORE_LINES` — the same reason recorded at
# `_BORN_SCRATCH_IGNORE_LINES`, `_BORN_ATOMIC_TMP_IGNORE_LINES` and `_BORN_DOT_DIR_DENY_LINE` above,
# and MEASURED again for this shape: that tuple is single-SoT for BOTH the born ignore lines AND the
# `git rm --cached` untrack pathspecs derived per member (`_ln.rstrip("/")` -> `<name>/` +
# `:(glob)**/<name>/**`). For a rooted glob those derive `/tmp.??????????/`, and
# `git ls-files --ignored --cached` then exits 128 (`fatal: Invalid path '/tmp.??????????'`), which
# silently disables the untracking of the real `.yitc/` churn that loop exists for. Hence a fourth
# separate tuple with its own idempotent append, exactly like the three siblings.
_BORN_MKTEMP_IGNORE_LINES = ("/tmp.??????????", "!/tmp.??????????/")

_BORN_SCRATCH_GITKEEP = (
    "# Agent scratch space (yitc-v2, T-11308). Anything you write in THIS directory is gitignored\n"
    "# and will never be swept into a governance commit by a verb's `git add -A`. Use it for the\n"
    "# working files a sandbox will not let you put in /tmp. Only this .gitkeep is tracked — it\n"
    "# exists so the directory is present in every checkout and every `worktree new` worktree.\n"
    "# Nothing here is durable: it is not read by any verb and it never travels.\n")


# ── consumer vendor-adapter doctrine (SPEC-0125) — thin CLAUDE.md + provider-neutral home ─────────────
# A consumer's CLAUDE.md is a Claude-vendor-specific filename other providers won't read, so it is born
# THIN (adapter-only: the engine `-C` verb form + a pointer to the provider-neutral home) and the
# substantive project operating-context lives provider-neutrally, never accreting into the vendor file
# (SPEC-0125 Rule 2/3). The `__YITC_CLI__` token renders to the engine `-C` form like every other born
# scaffold (T-9769); `__NEUTRAL_HOME__` renders to the ONE declared home (SPEC-0125 Rule 1);
# `__PROJECT__` renders to the project's own identity (its repo-root dir name — T-10690 / X-0528), so the
# delivered adapter carries a REAL project name, never a literal placeholder the conformance path can't fix.
_BORN_CLAUDE_MD = """\
# __PROJECT__ — YITC-v2 consumer (vendor adapter)

This file exists ONLY because some AI tools auto-read this exact filename. It is a THIN adapter — no
product rules live here (SPEC-0125). This project runs the YITC-v2 methodology provided by the kernel
(engine); this repo has NO local `bin/yitc-v2`, so run every yitc verb through the engine binary in
`-C` mode, targeting THIS repo:

    __YITC_CLI__ <verb>      # e.g. __YITC_CLI__ session start

Read the kernel methodology handbook at the engine — the files named, in order, by `session start`'s
read-order echo (the generated HANDBOOK_READ_ORDER; not listed here so this scaffold cannot drift).

Project operating-context (safety bans / integration constraints / PII policy / profile) lives in this
project's PROVIDER-NEUTRAL home, NOT here — see `__NEUTRAL_HOME__`.
"""

# The born project AGENTS.md stub — the provider-neutral home when a consumer has no product CHARTER.md
# (SPEC-0125 Rule 1). This is the consumer's OWN product operating-context, DISTINCT from the ENGINE's
# methodology AGENTS.md (the handbook, read at the engine path — never this file).
_BORN_PROJECT_AGENTS_MD = """\
# __PROJECT__ — project operating-context (provider-neutral home)

This is this project's PROVIDER-NEUTRAL operating-context home (SPEC-0125): the durable, any-provider
place for the product profile, module map, integration constraints, safety bans, and PII policy an AI
must know to work this repo safely. The vendor adapter (`CLAUDE.md`) points here.

NOTE: this is the PROJECT's own context, NOT the yitc-v2 methodology handbook — that lives at the
engine (the methodology handbook named by `session start`'s read-order echo, read via the `-C` engine binary).

## Product operating-context
<fill in: safety bans / integration constraints / PII policy / module + profile notes>
"""


def _ensure_consumer_vendor_adapter(REPO_ROOT, cli_form, write_text_atomic,
                                    *, project_name, refresh=False) -> tuple:
    """SPEC-0125 (consumer vendor-adapter doctrine) — born a THIN consumer `CLAUDE.md` (adapter-only)
    and ensure the ONE declared neutral home EXISTS so the adapter pointer always resolves: the product
    `CHARTER.md` if present, else a born project `AGENTS.md` stub (Rule 1). If-absent + idempotent
    (skips any file that already exists — it NEVER thins an existing content-bearing CLAUDE.md; that is
    X-0164's per-consumer migration). CONSUMER-ONLY — the caller gates on `_is_consumer_build()`, so the
    engine's own CLAUDE.md/AGENTS.md (the handbook) are never touched.

    T-10690 (X-0528): the `__PROJECT__` token renders to `project_name` (the consumer's own repo-root dir
    name) at DELIVERY, so a fresh adapter/home carries a REAL project identity, never the literal
    placeholder the prescribed conformance path could not fix (consumers used to keep the placeholder title
    or hand-edit and drift from the scaffold — the X-0293(2) residual).

    GOVERNED RE-STAMP (AC2) — an EXISTING adapter/home born BEFORE this fix still carries the leaked
    `<project>` placeholder in its title. It is re-stamped to `project_name` ONLY under `refresh`
    (`init --refresh-scaffolds`), mirroring the T-10498 born-vs-present boundary (PRESENT is never
    auto-healed silently; the doctrine `a-stance-mirror-is-only-sound-at-birth`). Keyed STRICTLY on the
    born placeholder signature in a heading line, so a consumer-authored real title is never touched.

    Returns `(created, restamped, pending, restamp_writes)` — created relative paths, re-stamped paths
    (to be rewritten this run under refresh), pending paths (leaked placeholder present, NOT rewritten —
    reported), and the DEFERRED-WRITE dict `{path: text}` the caller applies at the bootstrap-commit seam.
    The re-stamp WRITE is deferred (not done here) because it MODIFIES a tracked file: doing it early would
    strand a dirty CLAUDE.md/AGENTS.md if init then ran off-main or aborted at a sweep (the X-0332 hazard,
    the same discipline the baked-engine-path refresh follows). Fresh CREATE writes stay early — a new
    untracked file never wedges a later land."""
    created: list = []
    restamped: list = []
    pending: list = []
    restamp_writes: dict = {}

    def _placeholder_in_heading(text: str) -> bool:
        # the born placeholder leaks in the H1 TITLE line only — key on a heading line so a stray mention
        # of `<project>` in prose (never in the born template) can never trip the re-stamp.
        return any(ln.lstrip().startswith("#") and ADAPTER_TITLE_PLACEHOLDER in ln
                   for ln in text.splitlines())

    def _restamp(path, rel):
        try:
            body = path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001 — an undecodable existing file is out of scope for a re-stamp
            return
        if not _placeholder_in_heading(body):
            return
        if refresh:
            restamp_writes[path] = body.replace(ADAPTER_TITLE_PLACEHOLDER, project_name)
            restamped.append(rel)
        else:
            pending.append(rel)

    if (REPO_ROOT / "CHARTER.md").exists():
        neutral_home = "CHARTER.md"
    else:
        neutral_home = "AGENTS.md"
        agents_path = REPO_ROOT / "AGENTS.md"
        if not agents_path.exists():
            write_text_atomic(agents_path, _BORN_PROJECT_AGENTS_MD.replace("__PROJECT__", project_name))
            created.append("AGENTS.md")
        else:
            _restamp(agents_path, "AGENTS.md")   # re-stamp a pre-fix born AGENTS.md home
    claude_path = REPO_ROOT / "CLAUDE.md"
    if not claude_path.exists():
        body = (_BORN_CLAUDE_MD.replace("__YITC_CLI__", cli_form)
                .replace("__NEUTRAL_HOME__", neutral_home).replace("__PROJECT__", project_name))
        write_text_atomic(claude_path, body)
        created.append("CLAUDE.md")
    else:
        _restamp(claude_path, "CLAUDE.md")        # re-stamp a pre-fix born CLAUDE.md adapter
    return created, restamped, pending, restamp_writes


# The ONE declared neutral home, in SPEC-0125 Rule-1 ORDER (product CHARTER.md first, else the born
# project AGENTS.md). Single-SoT with `_ensure_consumer_vendor_adapter` above — the born carrier and the
# check below resolve the home by the SAME order, so they can never disagree (CHARTER §P5). `README.md`
# is deliberately NOT a home (Rule 1: it is public/product-facing, a different audience).
NEUTRAL_HOME_ORDER = ("CHARTER.md", "AGENTS.md")

# The born neutral-home PLACEHOLDER signature (the `<fill in: …>` stub in `_BORN_PROJECT_AGENTS_MD`).
# The `unfilled-home` check keys on THIS signature — never on a length/word heuristic — so a short but
# genuinely filled home passes (T-10480 R1).
NEUTRAL_HOME_PLACEHOLDER = "<fill in:"

# The born ADAPTER-TITLE placeholder signature (the `# <project>` H1 title an adapter/home was born with
# BEFORE T-10690 rendered `__PROJECT__`). The `unfilled-adapter-title` conformance check + the governed
# re-stamp key on THIS literal — so a pre-fix consumer that still carries it is SURFACED (a signal the
# residual exists) and the `init --refresh-scaffolds` re-stamp is the fix (X-0528). Both the leaked
# `<project>` and a mis-rendered `__PROJECT__` count as unfilled (defence-in-depth on a render bug).
ADAPTER_TITLE_PLACEHOLDER = "<project>"
ADAPTER_TITLE_PLACEHOLDERS = ("<project>", "__PROJECT__")


def _neutral_home_resolution(repo, *, adapter_text=None) -> tuple:
    """The ONE resolution of a consumer's DECLARED SPEC-0125 operating-context home (T-10912).

    Returns `(pointed, resolved, home, basis)`:
      * `pointed`  — the NEUTRAL_HOME_ORDER entries the vendor adapter (`CLAUDE.md`) NAMES;
      * `resolved` — those that also exist on disk;
      * `home`     — the DECLARED home (first of `resolved` in Rule-1 order), or None;
      * `basis`    — how it was declared: `adapter-pointer` | `rule-1-order` | `none`.

    Two declaration sources, straight from SPEC-0125 and in this precedence:
      1. **adapter PRESENT** — the declared home is what the adapter POINTS at and that EXISTS
         (Rule 2c "the adapter MUST point at the ONE declared home" + Rule 3 "the adapter's pointer
         MUST resolve"). An INCIDENTAL `AGENTS.md`/`CHARTER.md` the adapter does not point at is NOT
         a declaration — this is the distinction a bare presence check cannot make (audit-pre finding).
      2. **adapter ABSENT** (a consumer not yet `-C init`ed, so no pointer exists to read) — Rule 1's
         own binding default ORDER is the declaration rule: product `CHARTER.md` if present, else
         `AGENTS.md`. Same order `_ensure_consumer_vendor_adapter` borns by, so the two agree.
    Neither resolving → `(…, None, "none")`; the CALLER decides what an absent home MEANS for it
    (`adapter_conformance` reports a violation; the session-start echo states the absence).
    Read-only and never raises — an undecodable adapter is handled by the caller that read it."""
    from pathlib import Path

    repo = Path(repo)
    if adapter_text is None:
        claude = repo / "CLAUDE.md"
        if claude.is_file():
            try:
                adapter_text = claude.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001 — an undecodable adapter declares nothing readable
                adapter_text = ""
    if adapter_text is not None:
        pointed = [h for h in NEUTRAL_HOME_ORDER if h in adapter_text]
        resolved = [h for h in pointed if (repo / h).is_file()]
        home = next((h for h in NEUTRAL_HOME_ORDER if h in resolved), None)
        return pointed, resolved, home, ("adapter-pointer" if home else "none")
    # No adapter at all — Rule 1's binding default order IS the declaration.
    home = next((h for h in NEUTRAL_HOME_ORDER if (repo / h).is_file()), None)
    return [], ([home] if home else []), home, ("rule-1-order" if home else "none")


def declared_neutral_home(repo) -> tuple:
    """`(home, basis)` — the consumer's DECLARED SPEC-0125 operating-context home as a relative
    filename (`CHARTER.md` / `AGENTS.md`), or `(None, "none")` when the consumer declares none.
    The reader-facing face of `_neutral_home_resolution` (T-10912); used by the consumer
    session-start backbone echo so the echo and `adapter_conformance` resolve the SAME home."""
    _pointed, _resolved, home, basis = _neutral_home_resolution(repo)
    return home, basis


def adapter_conformance(repo_path) -> dict:
    """REPORT-ONLY consumer vendor-adapter conformance view (SPEC-0125 VP1/VP2) — the REUSABLE promotion
    of the hand-built T-10416 probe (its load-bearing AC2': the adapter→neutral-home CHAIN an AI consumer
    session actually reads must RESOLVE end-to-end). Read-only, NEVER raises, NEVER gates — the same
    report-only contract its `concern_conformance` sibling holds for the debt-echo + nightly callers.

    Returns `{"status", "count", "violations"}`:
      - `status`: `no-adapter` (no CLAUDE.md — e.g. the engine kernel itself, or a not-yet-initialized
        repo; count 0 → the caller SKIPs, since surfacing an uninitialized project is the SPEC-0093 init
        sweep's job), `unreadable` (present but undecodable), or `checked`.
      - `count`: len(violations) — 0 ⇒ CLEAN ⇒ the caller suppresses the line.
      - `violations`: `{"kind", "detail"}` records, the 3 kinds promoted VERBATIM from the T-10416
        mutation-tested negative controls:
          * `fat-adapter`             (N1 transform-never-ran) — VP1: the adapter carries a rule SECTION
            beyond its own title. The born adapter has exactly ONE heading, so ANY additional heading —
            at any level — is a product/methodology/deploy section. Keying on the heading COUNT (not on
            a keyword list) catches BOTH origin incidents: aiseller's `# Team Mode` H1 (an H1-level
            section a `##`-only rule would miss) and trend-finder's `## Deploy` over-scope (T-0049).
          * `pointer-to-missing-home` (N2) — VP1/VP2 chain: the adapter's neutral-home pointer does not
            RESOLVE — it names no legal home at all, or names one absent on disk. (SPEC-0125 Rule 3:
            "the adapter's pointer MUST resolve".)
          * `unfilled-home`           (N3 lossy drain) — VP2: the declared home EXISTS but is still the
            born `<fill in: …>` stub (or is empty), so the operating-context the adapter promises is not
            actually reachable there.
          * `unfilled-adapter-title`  (T-10690 / X-0528) — the adapter title still carries the born
            `<project>` placeholder (or a mis-rendered `__PROJECT__`), so the delivered scaffold never
            got a real project identity. The fix is the governed `init --refresh-scaffolds` re-stamp,
            NOT a hand-edit (which would drift the adapter from the scaffold).

    Fail-closed judgement belongs to the READER, not here (lessons/fail-closed-belongs-to-the-reader-not-
    the-parser): this view reports `unreadable` faithfully and each caller decides what that MEANS for it
    (the nightly grades it an ALERT, never a silent skip — the T-10292/T-10337 fail-open it forbids)."""
    from pathlib import Path

    repo = Path(repo_path)
    claude = repo / "CLAUDE.md"
    if not claude.is_file():
        return {"status": "no-adapter", "count": 0, "violations": []}
    try:
        text = claude.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 — a report-only surface must never nag/raise on an undecodable file
        return {"status": "unreadable", "count": 0, "violations": []}

    violations: list = []

    # T-10690 (X-0528) — the adapter title carries a REAL project identity, not the born placeholder.
    # Keyed on a HEADING line so a stray prose mention never trips it (mirrors the re-stamp's own gate).
    title_ph = next((ph for ph in ADAPTER_TITLE_PLACEHOLDERS
                     for ln in text.splitlines()
                     if ln.lstrip().startswith("#") and ph in ln), None)
    if title_ph is not None:
        violations.append({
            "kind": "unfilled-adapter-title",
            "detail": f"CLAUDE.md title still carries the born `{title_ph}` placeholder — the delivered "
                      f"adapter never got a real project name; re-stamp it with the governed "
                      f"`init --refresh-scaffolds` (never a hand-edit, which drifts from the scaffold) "
                      f"(SPEC-0125, T-10690/X-0528)",
        })

    # VP1 (Rule 2) — the adapter carries ONLY the thin adapter: its own title and nothing else.
    headings = [ln.strip() for ln in text.splitlines() if ln.lstrip().startswith("#")]
    if len(headings) > 1:
        extra = [h for h in headings[1:]]
        violations.append({
            "kind": "fat-adapter",
            "detail": f"CLAUDE.md carries {len(extra)} rule section(s) beyond the adapter title "
                      f"({', '.join(repr(h) for h in extra[:3])}{' …' if len(extra) > 3 else ''}) — "
                      f"product/methodology/deploy content belongs in the provider-neutral home "
                      f"(SPEC-0125 Rule 1/2), never in the vendor adapter",
        })

    # VP1/VP2 chain (Rule 3) — the adapter's neutral-home pointer must RESOLVE. Resolution itself is
    # the shared `declared_neutral_home` home (T-10912) — this reader only JUDGES what it returns.
    pointed, resolved, home, _basis = _neutral_home_resolution(repo, adapter_text=text)
    if not pointed:
        violations.append({
            "kind": "pointer-to-missing-home",
            "detail": f"CLAUDE.md points at no legal neutral home — it names none of "
                      f"{', '.join(NEUTRAL_HOME_ORDER)} (SPEC-0125 Rule 2c: the adapter MUST point at "
                      f"the ONE declared provider-neutral home)",
        })
    elif not resolved:
        violations.append({
            "kind": "pointer-to-missing-home",
            "detail": f"CLAUDE.md points at neutral home {', '.join(pointed)}, which does not exist on "
                      f"disk — the adapter's pointer does not resolve (SPEC-0125 Rule 3)",
        })

    # VP2 (Rule 1) — the DECLARED home (resolved above, restricted to what the adapter actually points
    # at) carries real operating-context, not the born placeholder.
    if home is not None:
        try:
            body = (repo / home).read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001 — an undecodable HOME is a real break, not a crash
            violations.append({
                "kind": "unfilled-home",
                "detail": f"the declared neutral home {home} is present but undecodable — the "
                          f"operating-context the adapter points at is not readable (SPEC-0125 Rule 1)",
            })
        else:
            if NEUTRAL_HOME_PLACEHOLDER in body or not body.strip():
                violations.append({
                    "kind": "unfilled-home",
                    "detail": f"the declared neutral home {home} still carries the born "
                              f"`{NEUTRAL_HOME_PLACEHOLDER} …>` placeholder (or is empty) — the "
                              f"operating-context was never filled in / was lost in the drain "
                              f"(SPEC-0125 Rule 1, VP2)",
                })

    return {"status": "checked", "count": len(violations), "violations": violations}


# ── ADOPTION-COMPLETENESS conformance (SPEC-0122 R6, T-10694 / X-0543) ──────────────────────────────
# A pinned external-shared-library dependency proves CODE IDENTITY (R2 no-local-diff) but NOT SURFACE
# COVERAGE: boomrocket's ticket-review adoption ran 6/15 endpoints, 0 UI, 0 ops checks INVISIBLY for
# weeks (X-0543). This report-only view is the CONSUMER side of the leg — it reads the LIBRARY-shipped
# consumer-integration MANIFEST (declared surfaces; authored by the library-side siblings X-0537/X-0542,
# never by this reader — P5) and reports the surfaces DECLARED-but-not-INTEGRATED as a LOUD gap. It is
# the sibling of `adapter_conformance`: read-only, NEVER raises, NEVER gates.

# External-territory root for a shared library (SPEC-0122 R1: code in a git repo OUTSIDE every yitc
# project's territory, depended on at runtime). The apify worked case names exactly this shape:
# `<host-home>/lib/apify-client`, `pip install -e`'d + bind-mounted read-only into consumer containers.
def _external_lib_root() -> str:
    """The external-shared-library root on THIS machine — `<host-home>/lib/` (T-12024).

    DERIVED, NOT LITERAL: an engine copied to another machine must look under THAT machine's home, not
    inherit this one's (the code-side half of SPEC-0074 rule 4; deviation
    `engine-code-host-path-unchecked-while-release-view-strips-docs`). On this host the derived value
    is byte-identical to the literal it replaces.

    A FUNCTION rather than a module constant, and THE IMPORT IS DEFERRED INTO THE CALL, for exactly the
    reason `_journal_pathspecs` above states: this module is imported DIRECTLY by the verify sandbox,
    where `lib` is not an importable package and a module-level `from lib import ...` takes the whole
    file down at import. By the time any caller RUNS, the real entry point has set `sys.path`.
    """
    from lib import host_paths
    return str(host_paths.host_home() / "lib") + "/"
# Bounded set of the consumer's OWN in-territory pin records (SPEC-0122 R2a) a pinned external-shared-lib
# leaves a signal in — its dependency manifest(s) + its container mounts. Kept small ON PURPOSE (P1): the
# detector answers "does an applicable pinned external-shared-lib exist?" independently of the ops section,
# closing the fail-open where omitting the section dodges the declare-or-waive obligation (audit-pre F1).
_PIN_RECORD_GLOBS = ("requirements*.txt", "requirements/*.txt", "pyproject.toml",
                     "docker-compose*.yml", "docker-compose*.yaml")


def _detect_pinned_shared_libs(repo_path) -> list:
    """Detect applicable pinned EXTERNAL-SHARED-LIBRARY dependencies (SPEC-0122 R1/R2) from the
    consumer's OWN in-territory pin records, INDEPENDENTLY of the `adoption_completeness` section — so a
    consumer cannot dodge the declare-or-waive obligation by simply omitting the section (audit-pre F1).

    Returns a sorted list of detected library NAMES (the last path segment of the `<host-home>/lib/<pkg>`
    reference — the apify worked case's shape). Read-only, never raises: an unreadable/absent pin record
    contributes nothing (a missing dependency manifest is not an alert here — that is the SPEC-0093 init
    sweep's concern). The signal is the EXTERNAL-territory root `_external_lib_root()` a pin record REFERS
    to: a `pip install -e <host-home>/lib/<pkg>` editable install OR a `- <host-home>/lib/<pkg>...:...:ro`
    read-only bind-mount — the exact two shapes SPEC-0122's Worked case names."""
    from pathlib import Path
    import re

    repo = Path(repo_path)
    names: set = set()
    # match the external-lib root followed by a package segment: <host-home>/lib/<pkg>
    pat = re.compile(re.escape(_external_lib_root()) + r"([A-Za-z0-9_.\-]+)")
    seen: set = set()
    for glob in _PIN_RECORD_GLOBS:
        for rec in sorted(repo.glob(glob)):
            if not rec.is_file() or rec in seen:
                continue
            seen.add(rec)
            try:
                text = rec.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001 — a report-only detector never raises on an odd file
                continue
            for m in pat.finditer(text):
                names.add(m.group(1))
    return sorted(names)


def _manifest_surface_ids(manifest_path) -> tuple:
    """Read a library-shipped consumer-integration MANIFEST and return `(status, surface_ids)`.
    `status` is `ok` (a `surfaces:` list was parsed), `unresolved` (missing / undecodable / unparseable
    / not a mapping / no `surfaces:` list). Each surface id is `"<kind>/<id>"` when the entry carries a
    `kind:` (endpoint|ui|ops|automation|upgrade-step), else the bare `id`. Read-only, never raises — the
    library authors the manifest (P5); this reader only consumes it."""
    from pathlib import Path
    import yaml

    p = Path(manifest_path)
    if not p.is_file():
        return ("unresolved", [])
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — an undecodable/unparseable manifest is unresolved, never a crash
        return ("unresolved", [])
    if not isinstance(doc, dict):
        return ("unresolved", [])
    surfaces = doc.get("surfaces")
    if not isinstance(surfaces, list):
        return ("unresolved", [])
    ids: list = []
    for s in surfaces:
        if isinstance(s, dict) and s.get("id") is not None:
            kind = s.get("kind")
            ids.append(f"{kind}/{s['id']}" if kind else str(s["id"]))
        elif isinstance(s, str):
            ids.append(s)
    return ("ok", ids)


def adoption_completeness(repo_path) -> dict:
    """REPORT-ONLY consumer ADOPTION-COMPLETENESS conformance view (SPEC-0122 R6, T-10694 / X-0543) —
    the surface-coverage leg of the pinned-dependency-contract. A pinned dep proves CODE IDENTITY, not
    SURFACE COVERAGE; this view reports the library-declared surfaces a consumer has NOT integrated (and
    has not waived) as a LOUD gap. Read-only, NEVER raises, NEVER gates — the same report-only contract
    its `adapter_conformance` sibling holds for the debt-echo + nightly callers.

    SHOULD-grade DECLARE-OR-WAIVE (mirror SPEC-0093): a consumer without a manifest yet records a bare
    `waiver.reason` — a recorded waive with re-entry, not a hard block. But the obligation is FAIL-CLOSED
    over the DETECTED pinned-dep set (`_detect_pinned_shared_libs`, audit-pre F1): an applicable pinned
    external-shared-lib that carries NO declaration/waiver is a LOUD `undeclared-dependency`, so omitting
    the section cannot dodge the leg.

    Returns `{"status", "count", "violations"}`:
      - `status`: `no-section` (no `adoption_completeness` section AND no detected pinned dep → skip-class,
        the SPEC-0093 init sweep's concern), `waived` (bare section `waiver.reason`, no detected-dep gap),
        `unreadable` (yitc-ops.yaml present but undecodable), or `checked`.
      - `count`: len(violations) — 0 ⇒ CLEAN ⇒ the caller suppresses the line.
      - `violations`: `{"kind", "dep"?, "surface"?, "detail"}` records; kinds:
          * `undeclared-dependency` — an applicable DETECTED pinned external-shared-lib with no manifest
            pointer and no waiver (the section is absent, the dep is uncovered, or its entry declares
            neither) — the declare-or-waive fail-closed miss.
          * `unanswered`            — the section is PRESENT but declares neither `waiver` nor
            `dependencies` (a declare-or-waive section left blank).
          * `manifest-unresolved`   — a declared dep points at a manifest that is missing / undecodable /
            carries no `surfaces:` list.
          * `surface-not-integrated`— a surface the manifest DECLARES that the consumer neither integrated
            nor waived (the X-0543 invisible-partial-adoption gap, named LOUD).

    Fail-closed judgement belongs to the READER, not here (lessons/fail-closed-belongs-to-the-reader-not-
    the-parser): this view reports `unreadable` faithfully and each caller decides what that MEANS for it
    (the nightly grades it an ALERT, never a silent skip)."""
    from pathlib import Path
    from lib import state  # lazy — the single yitc-ops.yaml read+parse path (SPEC-0093)

    repo = Path(repo_path)
    detected = _detect_pinned_shared_libs(repo)
    ops_path = repo / CONSUMER_OPS_CONTRACT

    section = None
    if ops_path.is_file():
        try:
            ops = state.load_ops(ops_path)
        except Exception:  # noqa: BLE001 — a report-only surface never raises on a broken carrier
            return {"status": "unreadable", "count": 0, "violations": []}
        if isinstance(ops, dict):
            section = ops.get("adoption_completeness")

    violations: list = []

    def _undeclared(dep, detail):
        violations.append({"kind": "undeclared-dependency", "dep": dep, "detail": detail})

    # SECTION ABSENT — declare-or-waive fail-closed over the DETECTED set (audit-pre F1).
    if section is None:
        if not detected:
            return {"status": "no-section", "count": 0, "violations": []}
        for dep in detected:
            _undeclared(dep, f"a pinned external-shared-library dependency ({dep}, under "
                             f"{_external_lib_root()}) is depended on, but {CONSUMER_OPS_CONTRACT} declares "
                             f"no `adoption_completeness` section for it — declare a consumer-integration "
                             f"manifest + integrated surfaces, or record a waiver (SPEC-0122 R6, SPEC-0093)")
        return {"status": "checked", "count": len(violations), "violations": violations}

    if not isinstance(section, dict):
        # a present-but-malformed section is an unanswered declare-or-waive (fail-closed).
        return {"status": "checked", "count": 1,
                "violations": [{"kind": "unanswered",
                                "detail": f"{CONSUMER_OPS_CONTRACT} `adoption_completeness` is present but "
                                          f"is not a mapping — declare `dependencies:` or a `waiver:` "
                                          f"(SPEC-0122 R6, SPEC-0093 declare-or-waive)"}]}

    waiver = section.get("waiver")
    deps = section.get("dependencies")

    # BARE WHOLE-SECTION WAIVER (SPEC-0093 rule 6 loose waiver) — a recorded waive with re-entry.
    if not deps:
        if isinstance(waiver, dict) and str(waiver.get("reason") or "").strip():
            return {"status": "waived", "count": 0, "violations": []}
        return {"status": "checked", "count": 1,
                "violations": [{"kind": "unanswered",
                                "detail": f"{CONSUMER_OPS_CONTRACT} `adoption_completeness` declares "
                                          f"neither `dependencies:` nor a `waiver: {{reason}}` — a "
                                          f"declare-or-waive section left blank (SPEC-0122 R6, SPEC-0093)"}]}

    if not isinstance(deps, list):
        return {"status": "checked", "count": 1,
                "violations": [{"kind": "unanswered",
                                "detail": f"{CONSUMER_OPS_CONTRACT} `adoption_completeness.dependencies` "
                                          f"is present but is not a list (SPEC-0122 R6)"}]}

    # DECLARED dependencies — per-dep declare-or-waive + surface conformance.
    covered: set = set()
    for entry in deps:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if name is not None:
            covered.add(str(name))
        entry_waiver = entry.get("waiver")
        manifest = entry.get("manifest")
        if isinstance(entry_waiver, dict) and str(entry_waiver.get("reason") or "").strip():
            continue  # per-dep waiver — explicit waive with re-entry
        if not manifest:
            _undeclared(name, f"the declared dependency {name!r} carries neither a `manifest:` pointer "
                              f"nor a `waiver: {{reason}}` (SPEC-0122 R6 declare-or-waive)")
            continue
        status, declared_surfaces = _manifest_surface_ids(repo / str(manifest))
        if status != "ok":
            violations.append({"kind": "manifest-unresolved", "dep": name,
                               "detail": f"the consumer-integration manifest {manifest!r} for {name!r} "
                                         f"is missing, undecodable, or carries no `surfaces:` list "
                                         f"(SPEC-0122 R6 — the library ships the manifest, X-0537/X-0542)"})
            continue
        integrated = {str(s) for s in (entry.get("integrated") or []) if s is not None}
        surface_waived = {str(s) for s in (entry.get("waived") or []) if s is not None}
        for surface in declared_surfaces:
            if surface in integrated or surface in surface_waived:
                continue
            violations.append({"kind": "surface-not-integrated", "dep": name, "surface": surface,
                               "detail": f"{name!r} declares surface {surface!r} in its integration "
                                         f"manifest, but the consumer neither integrated nor waived it "
                                         f"— an INVISIBLE partial adoption (SPEC-0122 R6, X-0543)"})

    # DETECTED-but-uncovered pinned deps — an applicable dep with no declared entry AND no per-dep waive.
    for dep in detected:
        if dep not in covered:
            _undeclared(dep, f"the pinned external-shared-library dependency {dep!r} (under "
                             f"{_external_lib_root()}) is depended on, but no `adoption_completeness."
                             f"dependencies` entry declares or waives it (SPEC-0122 R6, SPEC-0093)")

    return {"status": "checked", "count": len(violations), "violations": violations}


# ── NO-LOCAL-DIFF: the pin-identity leg (SPEC-0122 R2 HEALTH invariant / SPEC-0172 rule 3, T-10863) ──
# The IDENTITY sibling of `adoption_completeness` above: that leg keeps the ADOPTION honest (no invisible
# partial surface); this one keeps the PINNED COPY honest. SPEC-0122's HEALTH invariant states it —
# "a pinned copy is READ-ONLY locally: never edited in place, fixed only upstream + re-pinned. The health
# check is a no-local-diff check — the consumer's pinned copy must equal its upstream pin" — and SPEC-0172
# rule 3 applies it to the spike bridge: "every neutral bridge symbol resolves from that pin: a surviving
# local copy of a neutral module is a violation, not an optimisation ... a needed fix goes UPSTREAM to the
# library and the project re-pins — it is never patched in place". Until T-10863 that check was DESCRIBED
# and not CARRIED; this is the carrier. Report-only, NEVER raises, NEVER gates — same contract as its
# sibling. Real incident: the pre-extraction state was a copy of the bridge in EVERY consuming repo (the
# duplication the pin retires), and the X-0565 canary that deleted nine local modules on re-pinning.
#
# TWO CUTS BOUND THE SELECTOR so ordinary product runtime code can never be flagged (the scope bound —
# a check every project learns to ignore is worse than no check):
#   CUT 1 — it runs ONLY for a consumer that DECLARED `spike_sandbox.bridge` as a mapping (the T-10860
#           concern). An absent section, a waiver, or a non-mapping `bridge:` is `not-declared`. A project
#           that never opted into a spike bridge is never examined. (The UNANSWERED-question debt is a
#           DIFFERENT claim with its own home — T-10862 — not folded in here.)
#   CUT 2 — the candidate set is EXACTLY the modules the LIBRARY DECLARES NEUTRAL (`neutral_modules:` on
#           the library-shipped consumer-integration manifest R6 already reads), matched PACKAGE-QUALIFIED.
#           Which modules are neutral is a library MECHANIC (SPEC-0172 rule 1), so the kernel READS that
#           declaration and never infers it from the release's directory tree — inference would sweep in
#           unrelated shared modules (audit-pre F1). A basename collision is not a match either.
#           When that surface cannot be read the leg reports which of TWO causes it was, because their
#           OWNERS are opposite (T-11824): no manifest POINTER declared by this consumer
#           (`neutral-surface-unpointed`, consumer-reachable) vs a manifest that WAS reached and ships
#           no `neutral_modules:` list (`neutral-surface-undeclared`, library-owned and unreachable
#           from here). Both stay LOUD — the split makes the report ADDRESSED, never quieter.

# Directories never scanned for a local copy: a vendored/installed tree is not the consumer's own copy.
_NO_LOCAL_DIFF_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "site-packages",
                            "build", "dist", "__pycache__", ".tox", ".mypy_cache"}


def _bridge_declaration(repo_path, section="spike_sandbox", key="bridge"):
    """THE ops-carrier SECTION reader for the pinned-dependency family — return the DECLARED
    `<section>.<key>` mapping, or None. Defaults to `spike_sandbox.bridge` (CUT 1, its original and
    still its main caller); `kernel.engine` (SPEC-0195 rule 3) rides the SAME reader.

    THE PARAMETERS ARE WHY THIS IS ONE FUNCTION AND NOT TWO (T-12044). The T-11280 one-entry-point
    invariant — pinned by `tests/test_pinned_verify.py`, which counts the functions in this file that
    open the carrier — says a second reading of the carrier is a second place for the reading to
    drift, and the kernel pin reads the carrier in exactly the shape this function already reads it.
    So the kernel section widened the ONE reader rather than adding a sibling. The name is
    HISTORICAL — the spike bridge is simply what needed a pinned-dependency reader first — and is
    kept deliberately: renaming it would register as a new reader against that same guard, for no
    behavioural gain.

    None means "this consumer declared nothing here" for EVERY non-declaring shape: the section
    absent, a `waiver:` instead of a declaration, or a `<key>:` that is not a mapping (a half-written
    section must not read as declared — which is exactly why T-10860 made `declare_type: mapping`).
    Returns `False` when the ops carrier is present but undecodable, so the caller can report `unreadable`
    faithfully rather than conflating it with "not declared" (fail-closed belongs to the READER)."""
    from pathlib import Path
    from lib import state  # lazy — the single yitc-ops.yaml read+parse path (SPEC-0093)

    ops_path = Path(repo_path) / CONSUMER_OPS_CONTRACT
    if not ops_path.is_file():
        return None
    try:
        ops = state.load_ops(ops_path)
    except Exception:  # noqa: BLE001 — a report-only surface never raises on a broken carrier
        return False
    if not isinstance(ops, dict):
        return None
    sec = ops.get(section)
    if not isinstance(sec, dict):
        return None
    declared = sec.get(key)
    return declared if isinstance(declared, dict) else None


# Where a TAG-declared release is materialised (see `_materialize_tagged_release`). CONTENT-ADDRESSED
# by the peeled commit sha, so a cached directory can never be stale: a different commit is a different
# directory, and the same commit is the same bytes.
_TAG_RELEASE_CACHE = "yitc-pinned-release"


def _pinned_release_integrity_ok(root, anchor):
    """Does the release tree at `root` verify against the OUT-OF-BAND `anchor`? (T-12043, SPEC-0195
    rule 3: pinned resolution ADDS integrity.)

    THE DECLARED ANCHOR IS THE SWITCH, and it is the ONLY switch. No anchor declared -> the check is
    skipped and the pin resolves exactly as it always has: that is what keeps this INERT for the
    SPEC-0122 shared-library bridges, which publish no manifest by design. An anchor declared -> the
    tree MUST verify, and a tree carrying no release manifest REFUSES rather than skipping. Keying
    the skip on the manifest's absence as well was the hole audit-post finding 3 named: it let a
    bridge that HAD declared an anchor accept an unmanifested tag, which is the unverified tree the
    declaration exists to exclude.

    It WRITES NOTHING, which is what lets the caller run it on a staging tree before the tree is
    published, and on a cached tree before it is handed back.
    """
    from pathlib import Path

    from lib import release  # stdlib + the one parser library — no cycle (the lib.deploy precedent)

    if not str(anchor or "").strip():
        return True                       # no anchor declared: an ordinary SPEC-0122 library pin
    root = Path(root)
    if not (root / release.MANIFEST_FILENAME).is_file():
        # AN ANCHOR IS A DECLARATION THAT THIS PIN IS A SIGNED RELEASE, so a tree with no manifest
        # REFUSES rather than skips (audit-post finding 3). Skipping here was the hole: a bridge
        # that declared an anchor still accepted an unmanifested tag, which is precisely the
        # unverified tree the declaration exists to exclude. The skip survives only where no anchor
        # is declared — the shared-library pins that have no manifest by design.
        return False
    try:
        return bool(release.verify_release(root, str(anchor).strip()).ok)
    except Exception:  # noqa: BLE001 — a gate that cannot run REFUSES; it never resolves by crashing
        return False


def _materialize_tagged_release(repo_decl, ref, anchor=None):
    """Resolve a pin declared as a git TAG in a declared sibling repo (T-11758, X-1161) — return the
    release ROOT holding that tag's bytes, or None.

    WHY THIS SHAPE EXISTS. SPEC-0172 rule 3 asks a consumer to record "the EXACT release ref of the
    bridge library it runs". For a consumer whose bridge library is a sibling GIT repo, that ref is a
    TAG (`v0.5.0`) — and a tag is not a path, so the two shapes `_resolve_pinned_release` accepted
    below could not read the honest declaration at all: it reported `pin-unresolved` LOUD forever, and
    the only way to satisfy the resolver was to declare an absolute path to a GITIGNORED materialised
    checkout — a declaration true only AFTER someone ran an ensure script, which is a worse carrier
    than the honest one. So the bridge mapping may name its release REPOSITORY separately from its
    ref, and the ref is then read as a tag in it.

    THE BYTES ARE THE TAG'S, never the sibling's working tree — a checkout sitting on some other
    branch must not be mistaken for the pinned release. The tag is PEELED to its commit
    (`refs/tags/<ref>^{commit}`: an ANNOTATED tag's own object sha is not the commit's) and that
    commit is extracted read-only via `git archive` into a cache keyed BY THE PEELED SHA. Nothing is
    ever written into the sibling repo.

    ATOMIC MATERIALISATION: the extraction runs in a UNIQUE temp dir and is `os.rename`d onto the
    cache path only after it SUCCEEDED, so an interrupted extraction can never leave a partial tree a
    later run would read as complete. A pre-existing cache path is therefore always a completed one,
    and a lost rename race simply uses the winner — both hold the same commit's bytes by construction.

    FAIL-CLOSED: `refs/tags/` ONLY (a branch name or a raw sha is not a release TAG), and a repo that
    is missing, is not a git repo, or does not carry the tag returns None so the caller reports
    `pin-unresolved` LOUD. Every git/tar failure and timeout is likewise None — a widening that let an
    unresolvable pin read as resolved would turn a loud honest state into a silent false one."""
    import os
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    repo = Path(repo_decl)
    if not ref or not repo.is_dir() or not (repo / ".git").exists():
        return None
    if any(c in ref for c in " \t\n~^:?*[\\") or ref.startswith("-"):
        return None                       # not a plausible tag name — never handed to git
    try:
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify",
                              f"refs/tags/{ref}^{{commit}}"],
                             capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:  # noqa: BLE001 — git missing/failing is UNRESOLVED, never a crash
        return None
    if len(sha) != 40 or not all(c in "0123456789abcdef" for c in sha):
        return None                       # no such tag in that repo — LOUD, per the caller

    cache = Path(tempfile.gettempdir()) / _TAG_RELEASE_CACHE / f"{repo.name}-{sha}"
    if cache.is_dir():
        # Completed by construction (the atomic rename below) — but NOT necessarily verified: this
        # cache entry may have been published by an EARLIER call that declared no anchor, so handing
        # it back unchecked would let an unverified tree be read as pinned through a warm cache.
        # The re-check is read-only and cheap next to the extraction it skips (T-12043).
        return cache if _pinned_release_integrity_ok(cache, anchor) else None
    cache.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=str(cache.parent), prefix=f".{repo.name}-{sha}."))
    try:
        proc = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", sha],
                              capture_output=True, timeout=300)
        if proc.returncode != 0:
            return None
        tar = subprocess.run(["tar", "-x", "-C", str(staging)], input=proc.stdout, timeout=300)
        if tar.returncode != 0:
            return None
        # VERIFY BEFORE THE PUBLISHING WRITE (T-12043, SPEC-0195 rule 6 read literally). The
        # extraction above landed in `staging` — a unique throwaway path that is never the resolved
        # root and is removed by the `finally` below on every failure — so the only write that makes
        # a tree consumer-visible is the atomic rename, and it is now reached ONLY by a verified
        # tree. Verifying after the rename (the shape audit-pre caught) would have published first
        # and judged second, which is not what "before any write" means.
        if not _pinned_release_integrity_ok(staging, anchor):
            return None
        try:
            os.rename(str(staging), str(cache))   # ATOMIC publish — partial trees never appear
            staging = None
        except OSError:
            if not cache.is_dir():                # a real failure, not a lost race
                return None
        return cache if cache.is_dir() else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        if staging is not None:
            shutil.rmtree(str(staging), ignore_errors=True)


def _resolve_pinned_release(repo_path, bridge):
    """Resolve the PINNED RELEASE ROOT the neutral modules must equal, and the recorded ref.

    Returns `(root_or_None, ref)`. The declared `pin:` is the release ref (SPEC-0122 R2a); it may name
    the release ROOT directly (an absolute path, optionally `<path>@<ref>`). It may instead be a git
    TAG in a sibling repo the bridge mapping NAMES as `release_repo: <absolute path>` — the shape a
    repo-shipped bridge library actually has (T-11758 / X-1161); see `_materialize_tagged_release`.
    Otherwise the root is resolved from the consumer's OWN in-territory pin records through the
    EXISTING detector (`_detect_pinned_shared_libs` + `_external_lib_root()`) — no second resolution
    path (CHARTER §P5).

    INTEGRITY RIDES THIS RESOLVER, IT DOES NOT SIT BESIDE IT (T-12043, SPEC-0195 rule 3: pinned
    resolution "ADDS integrity — the resolved tree verifies against the signed release manifest
    before the engine is used"). When the bridge declares an out-of-band `anchor:` fingerprint, the
    tag branch verifies the release BEFORE the tree becomes consumer-visible, and a failed
    verification resolves to None — so the existing caller reports LOUD rather than reading an
    unverified tree as pinned. Inert for a shared-library pin (no manifest, no anchor); live for a
    kernel-release pin, which resolves through this same function rather than a second one."""
    from pathlib import Path

    ref = str(bridge.get("pin") or "").strip()
    candidate = ref.split("@", 1)[0].strip() if ref else ""
    if candidate.startswith("/"):
        root = Path(candidate)
        return (root if root.is_dir() else None, ref)
    release_repo = str(bridge.get("release_repo") or "").strip()
    if release_repo.startswith("/"):
        # A NAMED release repo is an ANSWER about where this pin lives, so it is the ONLY place looked
        # at: falling through to the shared-library detector could resolve the pin to an UNRELATED
        # root under the external-lib root — a silent FALSE resolution, worse than the loud unresolved
        # state this whole change exists to cure.
        return (_materialize_tagged_release(release_repo, ref,
                                            anchor=bridge.get("anchor")), ref)
    for name in _detect_pinned_shared_libs(repo_path):
        root = Path(_external_lib_root()) / name
        if root.is_dir():
            return (root, ref)
    return (None, ref)


# ── SPEC-0195 rules 3-4: the consumer's KERNEL pin (the ENGINE carrier) ───────────────────────────
# The SHARED pin-resolution surface for the `kernel:` ops-carrier section (T-12044). It is a READER
# plus ONE delegation to `_resolve_pinned_release` above — never a second resolver (CHARTER §P5): the
# tag-only admission, the peel to the annotated tag's commit, the sha-keyed cache, the
# verify-before-publish and the loud-None-on-every-failure all come from that function unchanged. What
# is added here is the KERNEL-section reading of it, and a status vocabulary a caller can act on.


def _kernel_declaration(repo_path):
    """Return the DECLARED `kernel.engine` mapping, or None / False — SPEC-0195 rule 3's carrier.

    A THIN WRAPPER, deliberately parsing nothing itself: the read goes through `_bridge_declaration`,
    the ONE ops-carrier section reader in this module (T-11280's one-entry-point invariant, pinned by
    `tests/test_pinned_verify.py`). Its three return states are that reader's, unchanged — None =
    declared nothing (section absent / a waiver / a non-mapping `engine:`), False = the carrier is
    present but undecodable, a mapping = the declaration. This exists only to give the kernel pin's
    callers a name that says what they are asking for."""
    return _bridge_declaration(repo_path, section="kernel", key="engine")


def _names_moving_ref(release_repo, ref) -> bool:
    """Does `ref` name a BRANCH (a moving ref) rather than a tag in `release_repo`? DIAGNOSTIC ONLY.

    The REFUSAL of a moving ref is already guaranteed upstream and by construction:
    `_materialize_tagged_release` resolves `refs/tags/<ref>` and nothing else, so a branch name
    resolves to None exactly as a nonexistent tag does. This helper does not add that refusal — it
    only lets the message NAME the cause, because "v0.5.0 is not a tag in that repo" and "you pinned
    a branch" are the same refusal with very different next actions, and a caller told only the
    generic one goes looking for a missing tag that was never the problem.

    FAIL-CLOSED TOWARD THE GENERIC MESSAGE: every git failure, timeout, or implausible ref returns
    False, so an unanswerable question degrades to `pin-unresolved` rather than asserting a branch
    that may not exist. A ref that is BOTH a tag and a branch reads as a tag (the tag is what
    resolves, so naming the branch would misreport the state the resolver is actually in)."""
    import subprocess
    from pathlib import Path

    repo = Path(release_repo)
    if not ref or not repo.is_dir() or not (repo / ".git").exists():
        return False
    if any(c in ref for c in " \t\n~^:?*[\\") or ref.startswith("-"):
        return False                      # not a plausible ref name — never handed to git
    def _has(full_ref):
        try:
            return subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", full_ref],
                                  capture_output=True, text=True, timeout=60).returncode == 0
        except Exception:  # noqa: BLE001 — an unanswerable question is not evidence of a branch
            return False
    return _has(f"refs/heads/{ref}") and not _has(f"refs/tags/{ref}")


def resolve_engine_pin(repo_path) -> dict:
    """Resolve the ENGINE the consumer at `repo_path` PINS — SPEC-0195 rule 3 (the engine carrier) and
    rule 4 (engine-by-pin, not engine-by-host-path). The shared surface `-C` consults (T-12044).

    Returns `{"status", "root", "ref", "detail"}` where `root` is the resolved release root (a
    `Path`) only on `resolved`, and `detail` is a message a caller may print verbatim. Statuses:

      `not-declared`   — no `kernel:` section, or no `engine:` mapping in it. `root` None. This is the
                         state of EVERY consumer until the first release is published, and it is what
                         keeps the caller's behaviour unchanged for them: the existing
                         invoking-path engine stands. It is NOT an error.
      `unreadable`     — the ops carrier is present but undecodable. Distinct from `not-declared`
                         because a project whose carrier will not parse has not answered anything, and
                         reading it as "declared nothing" would let a broken file silently restore the
                         host-path behaviour this contract retires.
      `moving-ref`     — `release` names a branch in `release_repo`. Rule 3: the pin is an EXACT,
                         IMMUTABLE ref; a moving one is REFUSED.
      `pin-unresolved` — declared but unresolvable: a missing `release_repo`/`release`, a `release`
                         given as an absolute PATH (which is the retired host-path assumption wearing
                         the pin's clothes — refused HERE, before `_resolve_pinned_release`'s
                         absolute-path arm could accept it as a release root), or the resolver
                         returning None (no such tag, a repo that is not a repo, a failed integrity
                         check against a declared `anchor:`).
      `resolved`       — `root` holds the PEELED COMMIT's bytes for the declared tag.

    THIS FUNCTION NEVER RAISES AND NEVER DIES. It reports; the CALLER decides what a status means —
    which is what lets `-C` refuse loudly while a report-only view (a later card's) prints the same
    fact without stopping anything."""
    from pathlib import Path

    from lib import release  # the T-12045 floor check — same lazy import as `_pinned_release_integrity_ok`

    engine = _kernel_declaration(repo_path)
    if engine is False:
        return {"status": "unreadable", "root": None, "ref": "",
                "detail": f"{CONSUMER_OPS_CONTRACT} is present but could not be parsed, so whether "
                          f"this project declares a `kernel.engine` pin cannot be determined at all"}
    if not isinstance(engine, dict):
        return {"status": "not-declared", "root": None, "ref": "",
                "detail": f"{CONSUMER_OPS_CONTRACT} declares no `kernel.engine` pin"}

    ref = str(engine.get("release") or "").strip()
    release_repo = str(engine.get("release_repo") or "").strip()
    if not ref or not release_repo:
        missing = " and ".join(k for k, v in (("release_repo", release_repo), ("release", ref)) if not v)
        return {"status": "pin-unresolved", "root": None, "ref": ref,
                "detail": f"`kernel.engine` is declared but incomplete — {missing} missing. The engine "
                          f"carrier is BOTH: the local clone of the published mirror AND the exact "
                          f"release tag in it (SPEC-0195 rule 3)"}
    if ref.startswith("/"):
        return {"status": "pin-unresolved", "root": None, "ref": ref,
                "detail": f"`kernel.engine.release` is {ref!r} — an absolute PATH, not a release tag. "
                          f"A path is the host-path assumption SPEC-0195 rule 4 retires, so it is "
                          f"refused here rather than accepted as a release root: name the exact "
                          f"release TAG, and `release_repo:` the clone that carries it"}
    if not release_repo.startswith("/"):
        return {"status": "pin-unresolved", "root": None, "ref": ref,
                "detail": f"`kernel.engine.release_repo` is {release_repo!r} — not an absolute path. A "
                          f"relative value resolves against whatever cwd the command was typed in, so "
                          f"the same declaration would name a different repo per caller"}

    root, _ref = _resolve_pinned_release(
        Path(repo_path), {"pin": ref, "release_repo": release_repo, "anchor": engine.get("anchor")})
    if root is not None:
        # THE VERSION FLOOR AT THE PINNED `-C` SEAM (T-12045, SPEC-0195 rule 9). The pin resolved to
        # an engine; the remaining question is whether this project's CONTENT will run on it.
        #
        # WHY THE REFUSAL IS SHAPED AS `pin-unresolved` RATHER THAN A NEW STATUS. This function's
        # `-C` caller (`cli.py#_rebind_repo_root`, T-12044) dies on `("moving-ref", "pin-unresolved")`
        # and falls THROUGH on anything else — so a new status would pass silently, which is the one
        # outcome a floor must never have, and widening that caller is T-12044's surface, not this
        # card's. The reuse is honest as well as available: the pin's contract (rule 3) is "the engine
        # this project RUNS", so a pinned engine the content refuses has not yielded a usable engine —
        # the pin is unresolved AS A PIN. Dying there is what makes this a HARD FAIL BEFORE ANY
        # MUTATION: the rebind runs from `main()` before any verb dispatches, so a `-C <project>`
        # invocation of ANY mutating verb — not just `init` — stops here, which the alternative of
        # deferring to the init seam would not have covered (audit-pre RED, absorbed).
        #
        # The structured fact rides beside the prose in `floor:`, so the report-only reader T-12046
        # adds reads a field instead of parsing a message.
        floor = release.check_root_pair(repo_path, root)
        if not floor.ok:
            return {"status": "pin-unresolved", "root": None, "ref": ref, "floor": floor.status,
                    "detail": f"the pinned engine {release_repo} @ {ref} resolved, but this "
                              f"project's content will not run on it — {floor.detail}"}
        return {"status": "resolved", "root": root, "ref": ref, "floor": floor.status,
                "detail": f"engine resolved from the pin: {release_repo} @ {ref} -> {root} "
                          f"(version floor: {floor.status})"}
    if _names_moving_ref(release_repo, ref):
        return {"status": "moving-ref", "root": None, "ref": ref,
                "detail": f"`kernel.engine.release` is {ref!r}, which is a BRANCH in {release_repo} — a "
                          f"moving ref. The pin is an EXACT, immutable release ref (SPEC-0195 rule 3): "
                          f"pin the annotated release TAG, which resolves to one peeled commit"}
    return {"status": "pin-unresolved", "root": None, "ref": ref,
            "detail": f"`kernel.engine` pins {ref!r} in {release_repo}, but that pin does not resolve — "
                      f"no `refs/tags/{ref}` there, the path is not a git repository, or the release "
                      f"failed its integrity check against the declared `anchor:`. This reports LOUD "
                      f"rather than falling through to the invoking engine (SPEC-0195 rules 3-4)"}


def refuse_out_of_floor(content_root, engine_root, _die=None, *, seam: str) -> None:
    """THE ENTRY-SEAM CALL (T-12045, SPEC-0195 rule 9) — hard-fail `seam` if the engine is below the
    floor this project's content declares. Returns normally on every OK status; never returns on a
    refusal.

    ONE call site shape for every entry seam, so `init`, `update` (T-12046) and any later entrypoint
    refuse identically instead of each growing its own comparison. The judgement itself is NOT here:
    it is `release.check_root_pair`, and this function only turns a not-ok verdict into the seam's
    refusal — the report/decide split `resolve_engine_pin` already draws.

    IT MUST BE CALLED BEFORE THE SEAM'S FIRST WRITE, which is a property of the CALL SITE and cannot
    be enforced from in here: rule 9 says "before any mutation", so a caller that runs it after
    touching the tree satisfies the letter and loses the point.
    """
    from lib import release

    floor = release.check_root_pair(content_root, engine_root)
    if not floor.ok:
        message = (f"{seam}: REFUSED on the engine/content version floor — nothing was written.\n"
                   f"  {floor.detail}")
        # `_die` when the caller has one (the CLI verbs do); otherwise the SystemExit `cmd_init`
        # itself raises. Either way the seam stops — the exit CHANNEL is the caller's, the refusal
        # is not optional.
        if _die is not None:
            _die(message)
        raise SystemExit(message)


def _consumer_manifest_pointer(repo_path, release_root):
    """Locate the library-shipped consumer-integration MANIFEST through the consumer's EXISTING
    `adoption_completeness.dependencies[].manifest` pointer (SPEC-0122 R6) — no new pointer, no new file
    convention, no second reader (CHARTER §P5). When several deps are declared, the one whose `name:`
    matches the pinned release's directory name wins; otherwise the single declared manifest is used.
    Returns an absolute Path or None."""
    from pathlib import Path
    from lib import state

    repo = Path(repo_path)
    ops_path = repo / CONSUMER_OPS_CONTRACT
    if not ops_path.is_file():
        return None
    try:
        ops = state.load_ops(ops_path)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(ops, dict):
        return None
    section = ops.get("adoption_completeness")
    if not isinstance(section, dict):
        return None
    deps = section.get("dependencies")
    if not isinstance(deps, list):
        return None
    wanted = release_root.name if release_root is not None else None
    fallback = None
    for entry in deps:
        if not isinstance(entry, dict) or not entry.get("manifest"):
            continue
        manifest = repo / str(entry["manifest"])
        if wanted is not None and str(entry.get("name") or "") == wanted:
            return manifest
        if fallback is None:
            fallback = manifest
    return fallback


def _neutral_module_ids(manifest_path) -> tuple:
    """CUT 2 — read the library-DECLARED neutral-module surface. The sibling of `_manifest_surface_ids`,
    over the SAME library-shipped manifest: `(status, ids)` where status is `ok` (a `neutral_modules:`
    list was parsed) or `unresolved` (missing / undecodable / not a mapping / no such list). Each id is a
    PACKAGE-QUALIFIED path relative to the release root (`ticket_bridge/channels.py`). The library
    authors this list (SPEC-0172 rule 1 — which modules are neutral is a library MECHANIC); this reader
    only consumes it, and never guesses when it is absent."""
    from pathlib import Path
    import yaml

    p = Path(manifest_path) if manifest_path is not None else None
    if p is None or not p.is_file():
        return ("unresolved", [])
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — an undecodable manifest is unresolved, never a crash
        return ("unresolved", [])
    if not isinstance(doc, dict):
        return ("unresolved", [])
    mods = doc.get("neutral_modules")
    if not isinstance(mods, list):
        return ("unresolved", [])
    ids = []
    for m in mods:
        if isinstance(m, dict) and m.get("id") is not None:
            ids.append(str(m["id"]).strip().lstrip("/"))
        elif isinstance(m, str) and m.strip():
            ids.append(m.strip().lstrip("/"))
    return ("ok", sorted(set(ids)))


def _neutral_modules(release_root, module_ids) -> dict:
    """Map each DECLARED neutral module id to its absolute source path under the pinned release. A
    declared id that does not resolve under the release root is skipped (report-only: a manifest naming
    a module the release does not ship is the library's own drift, not the consumer's local copy)."""
    from pathlib import Path

    root = Path(release_root)
    resolved = {}
    for mid in module_ids:
        src = root / mid
        if src.is_file():
            resolved[mid] = src
    return resolved


def _local_copies(repo_path, release_root, module_id):
    """Every file in the consumer repo whose path ENDS WITH the package-qualified `module_id` — the
    package-qualified match that keeps a mere BASENAME collision (a product `app/services/channels.py`
    vs a neutral `ticket_bridge/channels.py`) out of the candidate set. The pinned release itself is
    excluded (a bind-mounted release living under the repo is the pin, not a local copy), as are the
    vendored/installed trees in `_NO_LOCAL_DIFF_SKIP_DIRS`."""
    from pathlib import Path

    repo = Path(repo_path).resolve()
    root = Path(release_root).resolve() if release_root is not None else None
    suffix = "/" + module_id.strip("/")
    basename = module_id.rstrip("/").rsplit("/", 1)[-1]
    hits = []
    for cand in repo.rglob(basename):
        if not cand.is_file():
            continue
        rc = cand.resolve()
        if any(part in _NO_LOCAL_DIFF_SKIP_DIRS for part in rc.parts):
            continue
        if root is not None:
            try:
                rc.relative_to(root)
                continue      # inside the pinned release — that IS the pin
            except ValueError:
                pass
        if str(rc).endswith(suffix):
            hits.append(rc)
    return sorted(hits)


def no_local_diff(repo_path) -> dict:
    """REPORT-ONLY NO-LOCAL-DIFF view (SPEC-0122 R2 HEALTH / SPEC-0172 rule 3, T-10863) — the pin-identity
    leg of the pinned-dependency-contract. For a consumer that DECLARED the spike bridge, every neutral
    bridge symbol must resolve FROM the pinned release: a surviving local copy of a neutral module is a
    violation, not an optimisation, and a LOCALLY PATCHED one is caught the same way — that in-place patch
    is precisely the drift the pin exists to prevent (a needed fix goes UPSTREAM and the project re-pins).
    Read-only, NEVER raises, NEVER gates — the `adoption_completeness` contract verbatim.

    Returns `{"status", "count", "violations"}`:
      - `status`: `not-declared` (CUT 1 — no `spike_sandbox.bridge` mapping, nothing to check),
        `unreadable` (yitc-ops.yaml present but undecodable), or `checked`.
      - `count`: len(violations) — 0 ⇒ CLEAN ⇒ the caller suppresses the line.
      - `violations`: `{"kind", "module"?, "path"?, "pin"?, "detail"}` records; kinds:
          * `surviving-local-copy`      — a package-qualified local copy BYTE-IDENTICAL to the pinned
            original: the copy the pin retires (SPEC-0172 rule 3).
          * `modified-local-copy`       — the same match with DIVERGENT bytes: the in-place patch. Caught
            exactly as the surviving copy is; the two kinds differ only in what to do next, and neither
            is clean.
          * `pin-unresolved`            — declared, but the pinned release root cannot be resolved. LOUD,
            because a silent clean here would let deleting the pin record silence the check while the
            local copy survived (the anti-dodge audit-pre F1 closed for the sibling leg).
          * `neutral-surface-unpointed`  — declared, but THIS REPO names no manifest pointer for the
            pinned library (`adoption_completeness.dependencies[].manifest`), so no library manifest was
            reached at all. CONSUMER-owned and consumer-REACHABLE. LOUD.
          * `neutral-surface-undeclared`— declared, the manifest WAS reached, and it ships no readable
            `neutral_modules:` list. LIBRARY-owned and consumer-UNREACHABLE: nothing the consumer
            declares can clear it, only the library shipping the surface. LOUD.
            These two were ONE kind until T-11824, whose detail asserted the library case
            unconditionally — so a consumer that had merely not declared its POINTER was told its
            library was at fault, and neither reading named an owner or a reachable action. They are
            split by CAUSE because their owners are opposite; both stay LOUD, and neither is inferred
            (SPEC-0172 rule 1) nor read clean.

    Fail-closed judgement belongs to the READER, not here (lessons/fail-closed-belongs-to-the-reader-not-
    the-parser): this view reports `unreadable` faithfully and each caller decides what that MEANS."""
    from pathlib import Path

    repo = Path(repo_path)
    bridge = _bridge_declaration(repo)
    if bridge is False:
        return {"status": "unreadable", "count": 0, "violations": []}
    if bridge is None:
        # CUT 1 — not declared: a project that never opted into a spike bridge is never examined.
        return {"status": "not-declared", "count": 0, "violations": []}

    violations = []
    release_root, ref = _resolve_pinned_release(repo, bridge)
    if release_root is None:
        violations.append({
            "kind": "pin-unresolved", "pin": ref,
            "detail": f"{CONSUMER_OPS_CONTRACT} declares `spike_sandbox.bridge` with pin {ref!r}, but the "
                      f"pinned release cannot be resolved (no release root at that path, no git TAG "
                      f"{ref!r} in a `spike_sandbox.bridge.release_repo:` — name the sibling repo that "
                      f"ships the release and the ref is read as a tag in it — and no pin record under "
                      f"{_external_lib_root()}) — the no-local-diff check cannot run, so this reports "
                      f"LOUD rather than clean (SPEC-0122 R2, SPEC-0172 rule 3)",
        })
        return {"status": "checked", "count": len(violations), "violations": violations}

    manifest = _consumer_manifest_pointer(repo, release_root)
    if manifest is None:
        # CONSUMER-OWNED: no manifest POINTER was declared, so no library manifest was ever reached
        # and nothing about the library's neutral surface is known. Naming the library here would be
        # a misattribution — the reachable action is the consumer's own R6 declaration (T-11824).
        violations.append({
            "kind": "neutral-surface-unpointed", "pin": ref,
            "detail": f"this repo declares no `adoption_completeness.dependencies[].manifest` pointer "
                      f"for the pinned release {release_root.name!r}, so the library's "
                      f"consumer-integration manifest was never reached and its neutral-module surface "
                      f"is unknown — the candidate set is unpointed rather than guessed. THIS ONE IS "
                      f"YOURS: declare the dependency's `manifest:` in {CONSUMER_OPS_CONTRACT} (the "
                      f"same pointer the adoption-completeness leg already reads) and the check runs "
                      f"(SPEC-0122 R6, SPEC-0172 rule 3)",
        })
        return {"status": "checked", "count": len(violations), "violations": violations}

    status, module_ids = _neutral_module_ids(manifest)
    if status != "ok":
        # LIBRARY-OWNED: the manifest WAS reached and ships no `neutral_modules:` list. Which modules
        # are neutral is a library MECHANIC (SPEC-0172 rule 1), so nothing the consumer declares can
        # clear this — say so, rather than leaving a reader hunting a fix that does not exist. Still
        # LOUD: inferring the surface is what rule 1 forbids, and reading clean re-opens the silence
        # the leg exists to remove (T-11824).
        violations.append({
            "kind": "neutral-surface-undeclared", "pin": ref,
            "detail": f"the pinned release {release_root.name!r} ships its consumer-integration "
                      f"manifest {str(manifest)!r} but that manifest declares no readable "
                      f"`neutral_modules:` list — which modules are NEUTRAL is a library mechanic the "
                      f"kernel READS, never infers, so the candidate set is undeclared rather than "
                      f"guessed. NOT YOURS TO FIX: no consumer-side declaration can clear this — the "
                      f"library must SHIP the `neutral_modules:` surface and this project re-pins "
                      f"(SPEC-0172 rule 1/3, SPEC-0122 R6)",
        })
        return {"status": "checked", "count": len(violations), "violations": violations}

    for module_id, src in sorted(_neutral_modules(release_root, module_ids).items()):
        try:
            pinned_bytes = src.read_bytes()
        except Exception:  # noqa: BLE001 — an unreadable pinned original contributes nothing
            continue
        for copy in _local_copies(repo, release_root, module_id):
            try:
                local_bytes = copy.read_bytes()
            except Exception:  # noqa: BLE001
                continue
            rel = str(copy.relative_to(repo.resolve())) if str(copy).startswith(str(repo.resolve())) \
                else str(copy)
            if local_bytes == pinned_bytes:
                violations.append({
                    "kind": "surviving-local-copy", "module": module_id, "path": rel, "pin": ref,
                    "detail": f"the neutral bridge module {module_id!r} also lives in this repo at {rel!r}, "
                              f"byte-identical to the pinned release {ref or release_root.name!r} — a "
                              f"surviving local copy is a violation, not an optimisation: every neutral "
                              f"bridge symbol must resolve FROM the pin (SPEC-0172 rule 3, SPEC-0122 R2)",
                })
            else:
                violations.append({
                    "kind": "modified-local-copy", "module": module_id, "path": rel, "pin": ref,
                    "detail": f"the neutral bridge module {module_id!r} lives in this repo at {rel!r} and "
                              f"DIVERGES from the pinned release {ref or release_root.name!r} — a patched "
                              f"local module is exactly the drift the pin exists to prevent: the fix goes "
                              f"UPSTREAM and the project re-pins, never patched in place "
                              f"(SPEC-0172 rule 3, SPEC-0122 R2c)",
                })

    return {"status": "checked", "count": len(violations), "violations": violations}


def _render_init_concern_sweep(engine_root) -> str:
    """SPEC-0096 rule 8 (T-9529) — the owner-visible born-waiver/default SWEEP printed at `init`.
    READS the engine's already-generated graph/activation-checklist.md (the SPEC-0096 derived SET — no new
    derivation) and renders its Init-walk SET rows as a sweep block: EVERY init-defaultable concern (not
    only deploy), each flagged to be explicitly declared on-plan OR explicitly owner-waived, never a silent
    default (closing the X-0088 silent-born-waiver class generically; SPEC-0097 deploy-autonomy is the first
    concrete row). A NON-INTERACTIVE surfacing (a report) — NOT the T-9375 interactive declare-or-waive
    collection: it prints the SET, collects no answer, writes no carrier section. (There is NO separate
    `migration` verb: brownfield migration RUNS `bin/yitc-v2 -C <repo> init` as its import-completeness
    gate — runbook B2 — so wiring the sweep into cmd_init covers BOTH greenfield init and the migration
    gate; audit-pre F1.) Never crashes init: a MISSING engine artifact must not SILENTLY suppress the sweep
    (that would itself be a silent default — the very failure this closes, audit-pre F2), so the absent case
    returns an EXPLICIT owner-visible "unavailable" notice; only a present-but-empty SET (no concern declared
    yet) returns "" — there is genuinely nothing to surface (SPEC-0096 r8)."""
    acpath = engine_root / "graph" / "activation-checklist.md"
    try:
        text = acpath.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ("\nborn-waiver/default sweep: UNAVAILABLE — the engine's generated "
                "graph/activation-checklist.md was not found (run `bin/yitc-v2 graph build`).\n"
                "  the baseline-concern roster could not be surfaced; decide each kernel baseline "
                "concern manually (SPEC-0096) — do NOT leave any a silent default.")
    rows, in_set = [], False
    for line in text.splitlines():
        if line.startswith("## Init-walk SET"):
            in_set = True
            continue
        if in_set:
            if line.startswith("## "):                       # next section ends the SET
                break
            if line.startswith("- **SPEC"):                  # a real concern row (skip the empty-set note)
                rows.append(line[2:].strip())                # drop the leading "- "
    if not rows:
        return ""
    out = [
        "",
        f"born-waiver/default sweep ({len(rows)} kernel baseline concern(s) — SPEC-0096 r8 / SPEC-0097):",
        "  each concern below can default/waive owner-significant behaviour — decide EACH explicitly",
        "  (declare on-plan OR owner-waive with a real reason), never leave it a silent default:",
    ]
    out += [f"  - {r}" for r in rows]
    return "\n".join(out)


# ── SECURITY-AUDIT CADENCE SCAFFOLD (T-10186, SPEC-0145 §6 init_concern + SPEC-0142 trigger-shape) ───
# init SCAFFOLDS a security-audit cadence into a fresh consumer (seed-and-grow): the deterministic
# runner (T-10185's `bin/security-audit`, copied so the consumer can EXTEND it) + a provider-independent
# SYSTEM-trigger unit TEMPLATE carrying the born `security.audit` carrier declaration/waiver. It RECORDS
# the trigger for the owner-gated host-apply seam (the `consumer_init` event's `cadence_scaffold` field) —
# it does NOT install a host-wide cron (a host mutation belongs to that separate governed seam, T-10187).
# This delivers scaffold FILES only: it does NOT register the concern into graph/born-ops.yaml / the
# registry (the separate activation seam owns that). SPEC-0145's own status is read from the spec
# (`graph query SPEC-0145`), never pinned in a comment — a pinned status goes stale the moment the spec
# moves, and shipped a false claim into every consumer (T-10276 / X-0241). `__YITC_RUNNER__` is rendered
# to the delivered runner's repo-relative path at write time.
_BORN_SECURITY_TRIGGER = """\
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# SECURITY-AUDIT CADENCE — provider-independent SYSTEM-trigger unit TEMPLATE (scaffolded by `yitc-v2 init`)
#
# SPEC-0142 (provider-independence): a governed recurring obligation runs on a SYSTEM trigger
#   (cron / systemd timer) — NEVER a provider/AI scheduler. AI judgement (finding triage) is separable
#   and non-gating; the deterministic runner + the evidence gate carry the obligation.
# SPEC-0145 (cadence concern, §5 evidence schema / §6 declare-or-waive): the runner `__YITC_RUNNER__`
#   writes an evidence-rich report to `.yitc/findings/<date>-security.yaml`; the deploy gate
#   (`bin/v2-security-gate`) rejects a report that is stale-by-SLA OR incomplete-by-evidence.
#
# ⚠ THIS IS A TEMPLATE — NOT AN INSTALLED TRIGGER. `init` RECORDS it for the owner-gated host-apply
#   seam; it does NOT install a host-wide cron. Install it yourself (or via the governed host-apply
#   seam) once you have DECLARED your `security.audit` cadence in yitc-ops.yaml (block at the bottom).
# ─────────────────────────────────────────────────────────────────────────────────────────────────

# ── OPTION A — crontab line (cadence: every 3rd day at 03:00, the social-parser provenance shape). ──
# Install with `crontab -e` (or drop into /etc/cron.d/, prefixing a run-as user). Adjust the cadence to
# your declared `security.audit.cadence`. Use an ABSOLUTE path to the runner on the target host.
#
#   0 3 */3 * *  cd /ABS/PATH/TO/REPO && ./__YITC_RUNNER__ >> .yitc/findings/cron.log 2>&1

# ── OPTION B — systemd .service + .timer (equivalent, provider-independent). ──
# Write these two units under /etc/systemd/system/ (or a user unit dir), then
# `systemctl enable --now yitc-security-audit.timer`.
#
# --- yitc-security-audit.service ---
#   [Unit]
#   Description=YITC deterministic security-audit evidence producer (SPEC-0145)
#   [Service]
#   Type=oneshot
#   WorkingDirectory=/ABS/PATH/TO/REPO
#   ExecStart=/ABS/PATH/TO/REPO/__YITC_RUNNER__
#
# --- yitc-security-audit.timer ---
#   [Unit]
#   Description=Run the YITC security-audit on a provider-independent cadence (SPEC-0142)
#   [Timer]
#   OnCalendar=*-*-01/3 03:00:00
#   Persistent=true
#   [Install]
#   WantedBy=timers.target

# ─────────────────────────────────────────────────────────────────────────────────────────────────
# BORN `security.audit` CARRIER DECLARATION / WAIVER (SPEC-0145 §6 — paste into yitc-ops.yaml, under a
# top-level `security:` mapping, when you activate your cadence). DECLARE `cadence:` + `freshness_sla:`
# + `runner:` once this project has a security surface, OR keep the STRICT waiver below (reason +
# compensating_control + a real-ISO-date expiry are ALL required — SPEC-0093 rule 6).
# ─────────────────────────────────────────────────────────────────────────────────────────────────
#
#   security:
#     audit:
#       # DECLARE (replace the waiver) once you have a security surface to audit on a cadence:
#       #   cadence: "0 3 */3 * *"          # the SYSTEM-trigger schedule (this template's OPTION A)
#       #   freshness_sla: "P3D"            # the gate window — a report older than this is REJECTED
#       #   runner: "./__YITC_RUNNER__"     # the deterministic evidence producer (extend it for your surface)
#       waiver:
#         reason: "Scaffolded via `yitc-v2 init` — no project-specific security-audit cadence yet; declare cadence:/freshness_sla:/runner: once this project has a security surface (SPEC-0145)."
#         compensating_control: "Kernel always-on security baseline: prompt-injection protection, the `security-review` skill, secrets-out-of-git, the host-leak canary."
#         expiry: "2026-12-31"   # review-by date — REPLACE with your real security-review date.
"""


_SCAFFOLD_PRODUCER_ID = "bin/security-audit"   # the GENERIC kernel scaffold's self-declared identity (SPEC-0145 §9)


def _report_producer(path) -> str:
    """The TOP-LEVEL `produced_by:` of a findings report, or "" when absent/unreadable/unparseable.
    Reuses the already-imported YAML parser (no new parser path, CHARTER §P5). "" reads as FOREIGN at
    every call site — an unattributable or malformed report is never assumed to be the scaffold's own
    (SPEC-0145 §9, fail-closed)."""
    import yaml
    from pathlib import Path

    from lib import state  # CHARTER §P5 one parser library — the findings-report reader (T-9740)
    try:
        rec = state.load_str(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return ""
    return str(rec.get("produced_by") or "") if isinstance(rec, dict) else ""


def _foreign_security_producer(REPO_ROOT) -> str:
    """SPEC-0145 §9a — does a FOREIGN security producer already own this consumer's findings path?
    Returns "" when the path is unowned (or owned by the generic scaffold itself), else a human-readable
    REASON naming the offender. Same shape as host_apply.py `_collision_violation` (SPEC-0111 §2c,
    incident X-0097): an apply seam refuses pre-write when a foreign owner also claims the resource.

    Two deterministic, IN-REPO detectors (init never probes or mutates the host crontab —
    test_init_cadence_scaffold pins that it leaves it byte-unchanged, and the production cron lives on
    another host, so the carrier declaration is the deterministic source of truth for "a trigger exists"):
      D1  the LATEST-by-date `.yitc/findings/*-security.yaml` (the `<date>-security.yaml` naming
          convention, so the lexicographically-last file is the newest report) whose top-level
          `produced_by` != the scaffold id (ABSENT or unparseable → FOREIGN, fail-closed). Ownership is
          judged by CURRENT state, not by ANY historical report (X-0321): an older foreign report sitting
          alongside a newer core-owned latest is history, not ownership — so it no longer blocks the
          scaffold FOREVER. Fail-closed keeps its bite where the LATEST report is foreign/absent.
      D2  `yitc-ops.yaml` `security.audit.runner:` declares a runner that is not the scaffolded one."""
    import glob as _glob
    import os as _os
    import yaml
    from pathlib import Path

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)

    findings = sorted(_glob.glob(_os.path.join(str(REPO_ROOT), ".yitc", "findings", "*-security.yaml")))
    if findings:
        latest = findings[-1]
        producer = _report_producer(latest)
        if producer != _SCAFFOLD_PRODUCER_ID:
            rel = _os.path.relpath(latest, str(REPO_ROOT))
            return (f"{rel} is authored by `{producer or '<absent>'}`, not the generic kernel scaffold "
                    f"`{_SCAFFOLD_PRODUCER_ID}` — a foreign security producer already owns this findings path")

    ops_path = _os.path.join(str(REPO_ROOT), "yitc-ops.yaml")
    if _os.path.isfile(ops_path):
        try:
            ops = state.load_ops(Path(ops_path))
        except (OSError, yaml.YAMLError):
            ops = None
        if isinstance(ops, dict):
            security = ops.get("security")
            audit = security.get("audit") if isinstance(security, dict) else None
            runner = audit.get("runner") if isinstance(audit, dict) else None
            if runner and str(runner).strip() and str(runner).strip() != _SCAFFOLD_PRODUCER_ID:
                return (f"yitc-ops.yaml declares `security.audit.runner: {str(runner).strip()}` — a foreign "
                        f"security producer, not the generic kernel scaffold `{_SCAFFOLD_PRODUCER_ID}`")
    return ""


def _scaffold_owned_security_producer(REPO_ROOT) -> bool:
    """SPEC-0154 rule 5 — does the consumer's findings producer identity POSITIVELY match the kernel
    scaffold? True iff a findings report declares `produced_by: bin/security-audit`, or the carrier
    declares `security.audit.runner: bin/security-audit`.

    POSITIVE match, deliberately STRICTER than `not _foreign_security_producer(...)`. The two answer
    different questions and gate different writes: the §9a foreign check licenses an INSTALL (creating an
    absent file — safe when the path is merely unowned), while this licenses an UPDATE (CLOBBERING an
    existing file), which needs the consumer to have positively claimed the scaffold as its producer.
    Silence is not consent: a repo with no report and no declaration but a hand-forked `bin/security-audit`
    on disk is INDETERMINATE, and is left untouched (fail-closed). Reuses `_report_producer` — no new
    parser path (CHARTER §P5)."""
    import glob as _glob
    import os as _os
    import yaml
    from pathlib import Path

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)

    for report in sorted(_glob.glob(_os.path.join(str(REPO_ROOT), ".yitc", "findings", "*-security.yaml"))):
        if _report_producer(report) == _SCAFFOLD_PRODUCER_ID:
            return True

    ops_path = _os.path.join(str(REPO_ROOT), "yitc-ops.yaml")
    if _os.path.isfile(ops_path):
        try:
            ops = state.load_ops(Path(ops_path))
        except (OSError, yaml.YAMLError):
            return False
        if isinstance(ops, dict):
            security = ops.get("security")
            audit = security.get("audit") if isinstance(security, dict) else None
            runner = audit.get("runner") if isinstance(audit, dict) else None
            if runner and str(runner).strip() == _SCAFFOLD_PRODUCER_ID:
                return True
    return False


def _deliver_cadence_scaffold(REPO_ROOT, ENGINE_ROOT, write_text_atomic, *, apply: bool = True,
                              refresh: bool = False, accept_loss=()) -> tuple:
    """T-10186 (SPEC-0145 §6 init_concern / SPEC-0142 trigger-shape) — deliver the security-audit cadence
    scaffold into a fresh consumer. Returns `(created, updated, pending, reason, diverged)`: the created
    repo-relative paths (for `created` + the bootstrap `managed` stage + the `consumer_init` event), the
    UPDATED ones, the PENDING-refresh ones (drifted, deliberately NOT written — T-10498), the
    SPEC-0145 §9a foreign-producer refusal reason ("" when the path is unowned), and the T-10886
    DIVERGED ones as `(rel, hunks)` — refused because re-deriving would delete consumer-authored lines.

    T-10886 (X-0713) — `refresh` says the operator WANTS the re-derive; it does not say the re-derive is
    SAFE. A consumer copy that has diverged AHEAD of the kernel loses landed work when it is overwritten
    (aiseller T-0121: a 24-line deletion of a guard that consumer had landed, silently). So under
    `refresh` the write is now asked `_scaffold_refresh_refusal` first: acknowledged, or provably a
    previous kernel release, or non-deleting → write; otherwise WITHHOLD and return the hunks. The
    absent→INSTALL branch is untouched (nothing can be lost where nothing exists).

    T-10498 (X-0358 / X-0365) — `refresh` GATES THE UPDATE, never the install. An EXISTING runner whose
    bytes drifted from the engine is NO LONGER rewritten silently: it is returned as `pending` (the
    caller reports it — the staleness signal X-0365 found missing) and re-derived only when the operator
    passes `--refresh-scaffolds`. Silently rewriting it dragged a +31-line runner refresh into an
    unrelated task's diff when an init sweep ran inside a task worktree (X-0358, boomrocket T-0170).
    The `refresh` gate is the LAST condition, so it NARROWS the SPEC-0154 rule-5 identity gate below and
    never widens it: an update still requires the producer identity to positively match the scaffold.
    The absent→INSTALL branch is untouched (a fresh consumer bootstraps flag-free — T-9463), matching
    `lessons/a-stance-mirror-is-only-sound-at-birth`: born is a migration, PRESENT is never auto-healed.

    SPEC-0154 rule 5 — PRODUCER-IDENTITY-GATED INSTALL/UPDATE. The runner is the kernel's GENERIC probe
    and rule 1 makes the unmodified core "the sole report assembler, delivered + updated by `init`" — so
    if-absent alone would strand every landed consumer on the runner it was born with, which is the
    divergence SPEC-0154 exists to end (the social-parser fork already lags the §5 schema). The runner is
    therefore UPDATED in place (overwrite-if-different against the ENGINE copy — the same shape as
    cmd_init's `_REMATERIALIZE_TEMPLATES` loop), but ONLY when the consumer's findings producer identity
    POSITIVELY matches the scaffold (`_scaffold_owned_security_producer`). An existing renamed fork stays
    the declared runner, untouched, until the project opts into core+hook: the §9a refusal below fires
    first and returns before any write, and an INDETERMINATE identity fails closed to no-update.

    The TRIGGER template stays IF-ABSENT (seed-and-grow, never clobbered): it carries the consumer's own
    grown `security.audit` declaration/waiver, so it is a seed the consumer owns — not a kernel-owned
    generic probe that should track the engine.

    SPEC-0145 §9a — REFUSE, fail-closed: when a foreign producer already owns the findings path, deliver
    NEITHER the runner NOR the trigger template (the template invites installing a cron onto that same
    path) and return `([], reason)`. The check runs BEFORE either write, so the refusal is fail-closed by
    construction, never a post-hoc rollback. `init` itself does NOT hard-fail — a brownfield consumer
    keeping its own producer is the CORRECT outcome; the caller surfaces the refusal and delivers every
    other scaffold. No waive flag: the remedy is to keep your producer, or retire it and declare the
    scaffold as your `runner:` (a forced install would still be refused by the §9b runner-side guard).

    Delivers two born files under `bin/` (so the runner's `dirname(BASH_SOURCE)/..` resolves the CONSUMER
    repo root — the runner audits ITSELF, not the engine):
      • `bin/security-audit` — a byte-copy of the engine's deterministic runner (T-10185), chmod +x
        (write_text_atomic lands 0o644; cron/systemd need it executable). Read ENGINE_ROOT explicitly —
        territory-safe (reads the engine, writes only the consumer).
      • `bin/security-audit.trigger` — the provider-independent cron+systemd trigger TEMPLATE
        (`_BORN_SECURITY_TRIGGER`) carrying the born `security.audit` declaration/waiver, with
        `__YITC_RUNNER__` rendered to the runner's repo-relative path.

    NO host mutation (no crontab/systemctl), NO born-ops/registry change, NO SPEC-0145 activation — this
    is scaffold DELIVERY only; the recorded-for-host-apply signal is the caller's `consumer_init` event.

    `apply=False` (the T-10271 `--dry-run` preview) computes the WOULD-create list while skipping the two
    writes that bypass the `write_text_atomic` seam — the `bin/` mkdir and the runner's chmod +x."""
    import os
    from pathlib import Path
    created: list = []
    updated: list = []
    pending: list = []
    diverged: list = []
    runner_rel = "bin/security-audit"
    trigger_rel = "bin/security-audit.trigger"
    # SPEC-0145 §9a — fail-closed BEFORE any write: never take a findings path a foreign producer owns.
    # This ALSO gates the update path (SPEC-0154 rule 5): a renamed fork returns here, untouched.
    reason = _foreign_security_producer(REPO_ROOT)
    if reason:
        return [], [], [], reason, []
    eng_runner = ENGINE_ROOT / runner_rel
    dst_runner = REPO_ROOT / runner_rel
    # Runner (byte-copy the engine source-of-truth, executable): INSTALL if-absent, else — when the bytes
    # drifted from the engine AND the producer identity positively matches the scaffold — REPORT it as a
    # pending refresh (T-10498), applying it only under `refresh` (`--refresh-scaffolds`).
    if eng_runner.exists():
        kernel_text = eng_runner.read_text(encoding="utf-8")
        if not dst_runner.exists():
            if apply:
                dst_runner.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(dst_runner, kernel_text)
            if apply:
                os.chmod(dst_runner, 0o755)
            created.append(runner_rel)
        elif (dst_runner.read_text(encoding="utf-8") != kernel_text
                and _scaffold_owned_security_producer(REPO_ROOT)):
            if refresh:
                # T-10886: WANTED is not SAFE — never overwrite away lines this consumer landed.
                loss = _scaffold_refresh_refusal(ENGINE_ROOT, runner_rel,
                                                 dst_runner.read_text(encoding="utf-8"), kernel_text,
                                                 accept_loss)
                if loss:
                    diverged.append((runner_rel, loss))
                else:
                    write_text_atomic(dst_runner, kernel_text)
                    if apply:
                        os.chmod(dst_runner, 0o755)
                    updated.append(runner_rel)
            else:
                pending.append(runner_rel)
    # Trigger template (if-absent) — render the runner path token. Never a refresh candidate: it carries
    # the consumer's OWN grown `security.audit` declaration, so it is a seed the consumer owns.
    dst_trigger = REPO_ROOT / trigger_rel
    if not dst_trigger.exists():
        if apply:
            dst_trigger.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(dst_trigger, _BORN_SECURITY_TRIGGER.replace("__YITC_RUNNER__", runner_rel))
        created.append(trigger_rel)
    return created, updated, pending, "", diverged


# ── `init --dry-run` — the read-only PREVIEW seam (T-10271, X-0243) ──────────────────────────────────
# A bare init on an existing consumer commits its born-scaffold + adoption-record set straight to `main`
# (the sanctioned bootstrap-commit exception) with no way to see that set beforehand. The verb is already
# idempotent + non-clobbering, so the preview is a PURE READ-PATH over the SAME planning code — never a
# second planner (CHARTER §P1 F2: a view over the existing entity, not a new one). It is realized by
# SWAPPING cmd_init's three injected mutation seams (`write_text_atomic` / `_append_event` /
# `_run_git_cap`) for recorders, so the plan is whatever the real body computes. Prior art: the same
# compute-through-the-real-path-then-suppress-the-write shape as `nightly --dry-run` / `inspect record
# --dry-run` (T-10125) / `triage sweep --dry-run` / `worktree sweep --dry-run`.
#
# NO new injected dep on cmd_init: the SPEC-0077 pinned last-green (test_t9380) asserts its injected-deps
# list by `==`, so the seams are REBOUND inside the body and the host signature stays byte-identical
# (module header; lesson `governed-consumer-config-write-via-init-extension`).
#
# THE CHAINED-FILE SUBTLETY: two files are written and then READ BACK within one init run — `yitc-ops.yaml`
# (scaffold seed → _update_ops_carrier → _adopt_extensions → _seed_catalog_waives →
# _migrate_legacy_verify_yaml → the two fail-closed sweeps → _preseed_concern_adoptions) and `MEMORY.md`
# (scaffold seed → _seed_onboarding). A writer that merely DISCARDS writes leaves those readers looking at
# the pre-init file — or, on a fresh consumer, at no file at all, so `_sweep_ops_carrier` SystemExits — and
# the plan silently diverges from the apply. So the two chained paths are redirected into a scratch tempdir
# pre-seeded with their current content (absent stays absent, so the `path.exists()` create-vs-skip
# classification is bit-identical); the real chain runs there, every OTHER write is recorded, and the repo
# is never touched.
class _DryRunPlan:
    """Recorder for `init --dry-run`: captures what a real init WOULD write / remove / emit, performing
    none of it. Instances stand in for cmd_init's three mutation seams. The scratch tempdir is removed at
    interpreter exit too, so a fail-closed `SystemExit` from one of init's sweeps leaks nothing."""

    # git subcommands that only READ — everything else is treated as a mutation (fail-closed: an unknown
    # subcommand is suppressed, never let through to touch the consumer's repo).
    # `worktree` here is ONLY ever `worktree list --porcelain` (the read the T-10530/T-10533 engine-install
    # resolver makes) — init never mutates worktrees. It MUST pass through so a dry run resolves the true
    # install root; suppressing it fails the resolver OPEN to the invoking worktree, which flips the
    # T-10533 baked-path refresh into a spurious material delivery and breaks the no-op preview (X-0243).
    _READ_SUBCOMMANDS = frozenset({"ls-files", "show-ref", "rev-parse", "diff", "status", "log", "worktree"})

    def __init__(self, repo_root):
        import atexit
        import tempfile
        from pathlib import Path
        self.repo_root = repo_root
        self._dir = Path(tempfile.mkdtemp(prefix="yitc-init-dry-run-"))
        self.writes: dict = {}          # repo-relative path -> the text a real init would write
        self.events: list = []          # (event_type, task, data) a real init would append
        self.git_suppressed: list = []  # the mutating git argv lists a real init would run
        self._head = None               # SIMULATED HEAD: a suppressed checkout / symbolic-ref still has to
        self._cleaned = False           # be visible to the LATER `symbolic-ref --short HEAD` read, else the
        atexit.register(self.cleanup)   # on_main / seeded_main verdicts would diverge from the real run.

    # ── the scratch overlay for the two written-then-read-back files ──
    def scratch(self, name: str):
        """The scratch Path standing in for `repo_root/name`, pre-seeded from the repo copy IFF that copy
        exists — so `.exists()` mirrors reality and the create-vs-skip classification cannot drift."""
        p = self._dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        real = self.repo_root / name
        if real.exists():
            p.write_text(real.read_text(encoding="utf-8"), encoding="utf-8")
        return p

    def _rel(self, path) -> str:
        from pathlib import Path
        path = Path(path)
        for base in (self._dir, self.repo_root):
            try:
                return str(path.relative_to(base))
            except ValueError:
                continue
        return str(path)

    def _in_scratch(self, path) -> bool:
        from pathlib import Path
        try:
            Path(path).relative_to(self._dir)
            return True
        except ValueError:
            return False

    # ── the three seams ──
    def write_text_atomic(self, path, content: str) -> None:
        """Record the planned write. A scratch path is ALSO written for real — that is the read-back chain
        (a later helper re-reads the carrier this run just changed). Recording under the repo-relative name
        means the LAST write in a chain is the text the apply would leave on disk."""
        self.writes[self._rel(path)] = content
        if self._in_scratch(path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def append_event(self, event_type, task, data) -> None:
        self.events.append((event_type, task, data))

    def run_git_cap(self, real_run_git_cap):
        """Wrap the real git runner: READ subcommands pass through (the plan must see the true repo state),
        mutations are recorded + suppressed. Suppressed mutations return rc 0 — the preview models a
        SUCCESSFUL apply, so `seeded_main` and the material-delivery gate read exactly as they would."""
        import subprocess

        def _capped(argv: list, cwd):
            sub = argv[0] if argv else ""
            positionals = [a for a in argv[1:] if not a.startswith("-")]
            # `symbolic-ref --quiet --short HEAD` READS; `symbolic-ref HEAD refs/heads/main` MUTATES.
            reads_head = sub == "symbolic-ref" and positionals == ["HEAD"]
            if reads_head and self._head is not None:
                return subprocess.CompletedProcess(argv, 0, stdout=f"{self._head}\n", stderr="")
            if sub in self._READ_SUBCOMMANDS or reads_head:
                return real_run_git_cap(argv, cwd)
            self.git_suppressed.append(list(argv))
            if sub == "checkout" and positionals:                       # the branch a real init lands on
                self._head = positionals[0]
            elif sub == "symbolic-ref" and len(positionals) == 2:       # unborn HEAD -> refs/heads/<x>
                self._head = positionals[1].rsplit("/", 1)[-1]
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        return _capped

    def cleanup(self) -> None:
        import shutil
        if not self._cleaned:
            self._cleaned = True
            shutil.rmtree(self._dir, ignore_errors=True)

    # ── the owner-facing render ──
    def render(self, *, untracked_paths=None, retired_swept=None, legacy_removed=None,
               concerns_preseeded=None, adoption_records=None, would_bootstrap=False) -> None:
        """Print the FULL planned state change — both halves. Showing only the WRITE half would mis-preview
        a consumer carrying a born-empty retired surface or a legacy yitc-verify.yaml, whose init state
        change is a REMOVAL (audit-pre finding, absorbed mode-a). Every path is named individually; a
        removal is never reported as a bare count."""
        name = self.repo_root.name
        writes = sorted(self.writes)
        removes: list = []
        for p in (retired_swept or []):
            removes.append((p, "unlink", "retired per-repo surface"))
        if legacy_removed:
            removes.append((legacy_removed, "unlink", "migrated into yitc-ops.yaml verify.layers"))
        for p in sorted(untracked_paths or []):
            removes.append((p, "untrack", "git rm --cached; the file stays on disk"))

        if not (writes or removes or concerns_preseeded or would_bootstrap):
            print(f"init --dry-run ({name}): PLAN — no-op (already initialized; nothing to deliver)")
            return

        print(f"init --dry-run ({name}): PLAN — nothing below has been written")
        if writes:
            print("  write:")
            for rel in writes:
                action = "rewrite" if (self.repo_root / rel).exists() else "create"
                print(f"    {action:<7} {rel}")
        if removes:
            print("  remove:")
            for rel, action, why in removes:
                print(f"    {action:<7} {rel}  ({why})")
        if concerns_preseeded:
            # The per-line `owner:` distinguishes a machine-defaulted birth record (`init`) from an
            # owner's explicit `--adopt-concern` handle — so the header stays neutral.
            print(f"  adoption records (yitc-ops.yaml `adoption:`) — {len(concerns_preseeded)}:")
            for rec in (adoption_records or []):
                print(f"    {rec}")
        if would_bootstrap:
            print("  commit: would bootstrap-commit the staged scaffolds directly to `main`")
        print(f"  (re-run without --dry-run to apply; {len(self.events)} journal event(s) would be emitted)")


def _preseeded_adoption_records(ops_text: str, concerns: list) -> list:
    """The `concern:status@version (owner)` lines for the concerns a dry-run WOULD pre-seed, read back from
    the planned carrier text. The volatile `at:` stamp is deliberately EXCLUDED: it is a write timestamp,
    not a decision, and including it would make a plan/apply comparison spuriously unstable."""
    import yaml

    from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)
    try:
        ops = state.load_ops_str(ops_text) or {}
    except yaml.YAMLError:
        return []
    if not isinstance(ops, dict) or not isinstance(ops.get("adoption"), list):
        return []
    want = set(concerns or [])
    out = []
    for e in ops["adoption"]:
        if isinstance(e, dict) and str(e.get("concern")) in want:
            out.append(f"{e.get('concern')}:{e.get('status')}@{e.get('version')} "
                       f"(owner: {e.get('owner')})")
    return sorted(out)


def _engine_install_root(engine_root, _run_git_cap):
    """The engine's DURABLE INSTALL root — the main checkout — NEVER the invoking worktree (T-10530).

    A path BAKED into a born scaffold OUTLIVES the invocation that wrote it, so it must name a
    location that still exists tomorrow. `ENGINE_ROOT` is the INVOKING binary's checkout
    (`Path(__file__).parent.parent`): when a kernel session runs `-C <consumer> init` from an
    ephemeral `task/T-XXXX` worktree, ENGINE_ROOT is that worktree — and git REMOVES it at the kernel
    `land`, leaving the newborn consumer pointing at a deleted engine binary (X-0393: ai-safety was
    born naming `/home/dev/projects/yitc-v2-wt/T-10455/bin/yitc-v2`).

    Resolution mirrors the host's `_main_worktree` (bin/yitc-v2) — the same `git worktree list
    --porcelain` parse, one technique with two readers (the documented `_git_common_dir` /
    `_id_reservation_dir` precedent). It is re-stated here rather than injected because init.py holds
    a deliberate no-lib-import shape and `cmd_init`'s injected-deps are pinned by `==`
    (tests/test_t9380), so a new host dep would be structurally un-landable; this reads only the
    already-injected `_run_git_cap`.

    FAIL-OPEN to `engine_root` (= today's behavior, never worse) when the install is not a git
    checkout (a release copy) or no worktree is on `main` (a detached main).

    SCOPE: the BAKED PATH only. Every ENGINE_ROOT *content* read (the specs glob, the catalog members,
    the rematerialized templates, the cadence runner) MUST keep resolving against the INVOKING
    checkout — that is the code under test in a worktree and in the hermetic verify sandbox.
    """
    from pathlib import Path   # function-local, matching this module's import idiom

    r = _run_git_cap(["worktree", "list", "--porcelain"], engine_root)
    if r.returncode != 0:
        return engine_root
    cur = None
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            cur = line[len("worktree "):].strip()
        elif line.strip() == "branch refs/heads/main" and cur:
            return Path(cur)
    return engine_root


# The three born scaffolds that bake the `__YITC_CLI__`-rendered engine invocation
# (`<engine>/bin/yitc-v2 -C <consumer>`) into their delivered text. Single-SoT list for the
# stale-baked-path refresh below — MEMORY.md, the ops carrier, and the CLAUDE.md vendor adapter.
_ENGINE_PATH_BAKED_SCAFFOLDS = ("MEMORY.md", "yitc-ops.yaml", "CLAUDE.md")


def _refresh_baked_engine_path(REPO_ROOT, install_root, *, memory_override=None) -> tuple:
    """REPAIR a STALE baked engine path in an ALREADY-initialized consumer's scaffolds (T-10533).

    The X-0393 sibling: T-10530 fixed the SOURCE (a fresh consumer is now born with the DURABLE
    install path), but init's scaffold delivery is if-absent/idempotent — so an ALREADY-initialized
    consumer whose scaffolds still carry a DEAD engine path (baked before the T-10530 fix, or by a run
    from an ephemeral worktree) is NEVER rewritten and stays permanently stuck (no self-heal). This
    gives init a TARGETED refresh: when the baked engine binary path no longer resolves to the current
    install root, substitute JUST that path string.

    PATH-ONLY, never a re-render. MEMORY.md is a LIVE consume-once buffer (SPEC-0039) — a blanket
    re-render of the born template would DESTROY its entries. So the substitution is anchored on the
    stable ` -C <REPO_ROOT>` tail (the consumer path never changes) and rewrites ONLY the engine
    `<root>/bin/yitc-v2` prefix in front of it, leaving every other byte — buffer entries, ops
    declarations, the adapter's neutral-home pointer — untouched. The CLAUDE.md adapter change is thus
    re-issued through init (SPEC-0125 Rule 3), path-scoped.

    COMPUTE-ONLY (reads disk, returns the rewrites) — the WRITE is deferred to the bootstrap-commit
    seam so a refresh can never outlive an abort as a dirty tracked file (the X-0332 discipline the
    onboarding seed also follows). Returns `(refreshed_rels, writes)` where `writes` maps the target
    Path to its new text; `refreshed_rels` is the list of relative names that changed (empty when every
    baked path is already current → idempotent: a re-run stays byte-identical and makes no commit).
    """
    import re   # module-local idiom: init.py imports per-function, never at module level

    install = str(install_root)
    # Anchor on the stable ` -C <REPO_ROOT>` tail; capture the engine-root prefix before `/bin/yitc-v2`.
    # `root` is PATH characters only (`[\w./~-]`) — never a greedy `\S+`, which would swallow a leading
    # Markdown/code delimiter (a backtick, quote, paren) into `root` and DELETE it on rewrite (audit-pre
    # finding). `\b` after the escaped consumer path stops a longer sibling path (…/kupiclub2) matching.
    pat = re.compile(r"(?P<root>[\w./~-]+)/bin/yitc-v2(?P<tail> -C " + re.escape(str(REPO_ROOT)) + r"\b)")

    def _sub(m):
        if m.group("root") == install:
            return m.group(0)                    # already the install root — unchanged
        return f"{install}/bin/yitc-v2{m.group('tail')}"

    refreshed_rels: list = []
    writes: dict = {}
    for name in _ENGINE_PATH_BAKED_SCAFFOLDS:
        path = REPO_ROOT / name
        # For MEMORY.md, refresh the FINAL to-be-committed text (the onboarding-seeded superset when the
        # seed fired this run) so the deferred seed write at the seam does not re-strand the dead path.
        if name == "MEMORY.md" and memory_override is not None:
            text = memory_override
        elif path.exists():
            text = path.read_text(encoding="utf-8")
        else:
            continue                             # not yet delivered (fresh consumer) — nothing to refresh
        new_text = pat.sub(_sub, text)
        if new_text != text:
            refreshed_rels.append(name)
            writes[path] = new_text
    return refreshed_rels, writes


# ── Fail-closed sweep ATOMICITY (T-10688 / SPEC-0112 / SPEC-0093) ────────────────────────────────────
# init delivers its born scaffolds + carrier mutations to the WORKING TREE, then runs two FAIL-CLOSED
# sweeps (`_sweep_ops_carrier`, the SPEC-0112 catalog-completeness sweep) BEFORE its one bootstrap
# commit. A sweep that raised SystemExit used to leave every PRE-SWEEP delivery STRANDED on the
# consumer's `main` — a modified yitc-ops.yaml (the rule-11 section pull / the legacy-verify fold) or a
# freshly-created scaffold — and a dirty/untracked non-bookkeeping path there WEDGES every later `land`
# (the X-0527 wedge cluster: roots X-0530/X-0534/X-0535, consequences X-0527/X-0531/X-0532). The
# refused init must strand NOTHING but the durable journal refusal event (D-0049 — the capture is the
# whole point). No new mechanism: this snapshots the SAME init-managed paths the bootstrap commit's
# `managed` list stages, and on a sweep refusal restores them to their pre-delivery bytes + unstages the
# two index-only untracks (churn `rm --cached`, legacy-verify `rm --cached`) — the bootstrap-commit /
# scoped-self-commit seams (SPEC-0039/0147) run in reverse.
#
# WHY these seven: they are the only paths init may WRITE before the sweeps — .gitignore/.gitattributes
# (append-or-create), the three born scaffolds (MEMORY.md, the carrier, .no-v1-hooks), and the consumer
# vendor adapter (CLAUDE.md, AGENTS.md). Every OTHER delivery (folders, cadence, rematerialize, the
# concern pre-seed, the deferred onboarding-seed / baked-path refresh) happens AFTER the sweeps, so a
# refusal never reaches it — nothing to roll back. events.jsonl is DELIBERATELY excluded: the refusal
# event is the durable D-0049 capture and must survive.
_PRE_SWEEP_MANAGED_PATHS = (".gitignore", ".gitattributes", "MEMORY.md", CONSUMER_OPS_CONTRACT,
                            ".no-v1-hooks", "CLAUDE.md", "AGENTS.md")


def _restore_pre_sweep_delivery(repo_root, snapshot, index_untracked, write_text_atomic,
                                _run_git_cap) -> None:
    """Restore the working tree + index to their PRE-DELIVERY state after a fail-closed sweep refusal
    (T-10688). `snapshot` maps each init-managed relative path to its pre-init bytes (or None when the
    path did not exist), captured before the first write; `index_untracked` names the paths init
    `git rm --cached`-ed this run (churn + a migrated legacy yitc-verify.yaml) whose index entry must be
    restored. Pure rewind — it re-materializes an absent-then-created scaffold's ABSENCE and a
    modified-then-mutated carrier's ORIGINAL bytes, so a refused init leaves zero delivery trace."""
    for rel, orig in snapshot.items():
        p = repo_root / rel
        if orig is None:                                     # created this run → un-create it
            if p.exists():
                p.unlink()
        elif not p.is_file() or p.read_text(encoding="utf-8") != orig:
            write_text_atomic(p, orig)                       # mutated this run → restore original bytes
    if index_untracked:
        # Undo the index-only `git rm --cached` (the working files were never removed): reset each path's
        # index entry back to HEAD so the tree reads clean again.
        _run_git_cap(["reset", "-q", "--", *sorted(set(index_untracked))], repo_root)


def cmd_init(args: argparse.Namespace, *, CONSUMER_VERIFY_CONTRACT, ENGINE_ROOT, REPO_ROOT, _BORN_GITIGNORE_LINES, _BORN_LESSONS_README, _BORN_MEMORY_MD, _BORN_NO_V1_HOOKS, _BORN_PATTERNS_GITKEEP, _BORN_GRAPH_GITKEEP, _BORN_VERIFY_YAML, _REMATERIALIZE_TEMPLATES, _append_event, _is_consumer_build, _run_git_cap, write_text_atomic, _seed_onboarding=None) -> None:
    """`bin/yitc-v2 -C <path> init` — idempotently deliver a consumer its born-empty scaffolds (T-0995).

    Ensures the .gitignore covering the transient `.yitc` churn FIRST (F-008), then UNTRACKS any
    `.yitc/` / journal-sync-state/ a prior session already committed (a .gitignore does not untrack
    already-tracked files; T-9310), then creates IF-ABSENT: MEMORY.md (SPEC-0039),
    yitc-ops.yaml (the SPEC-0093 ops-contract carrier — deploy/rollback/live_probe/verify born
    declare-or-waive, then SWEPT fail-closed; the land-verify home is its `verify.layers` section,
    SPEC-0152 rule 16 — yitc-verify.yaml is RETIRED, T-9719, and a legacy one is MIGRATED + removed),
    .no-v1-hooks (host V1-hook opt-out marker,
    F-017), and the two DISTRIBUTED-ARCHITECTURE folders (T-9346, SPEC-0090): a born-empty `lessons/`
    (PROJECT realm — the consumer's own local-craft home; `lessons/README.md` born helper) + a read-only
    `patterns/` surface (`patterns/.gitkeep`; the general patterns are DISTRIBUTED — content resolves
    from the engine via the C3 carrier, never copied; read-only by construction).
    REMATERIALIZES the engine-owned scaffold templates (specs/_template.yaml,
    tasks/_template.yaml) from the kernel so a consumer's copy cannot drift (F-023). Finally, if the
    consumer repo has no `main` branch, SEEDS one (F-004) AND — the T-9463 extension — ensures `main` is
    the checked-out branch (switching a just-seeded non-main checkout to main) then makes a sanctioned
    ONE-TIME BOOTSTRAP COMMIT of the delivered scaffolds + journal directly to `main`, so the bootstrap
    reaches main via a governed commit (NOT a loose dirty working tree) and a subsequent worktree→land
    flow starts from a clean main. Re-run is idempotent TOWARD THE CURRENT KERNEL SCHEMA — a no-op for a
    fresh/current consumer (no duplicate writes / no duplicate .gitignore lines / nothing to untrack /
    main already seeded), EXCEPT it delivers the UPDATE path (T-9375 / SPEC-0093 rule 11): an EXISTING
    carrier missing an extensible top-level section the kernel has since added (security/ui/tests/inspection) has it
    PULLED in, born declare-or-waive, non-destructively. Targets REPO_ROOT, which the `-C <path>` global
    flag rebinds to the consumer checkout.

    DELIBERATE worktree-gate exception (T-0995 audit-pre F1; commit half added T-9463): unlike
    source/artifact mutations, init does NOT call _require_writing_worktree AND it commits its scaffolds
    directly to `main` (the bootstrap commit above) rather than riding worktree→land. It is a
    CONSUMER-SIDE BOOTSTRAP — a fresh consumer has no task/work worktree workflow yet and cannot even
    `land` until init delivers its verify contract (chicken-and-egg). The durable journal capture is the
    `consumer_init` event (capture-not-isolation, the same rationale as the D-0049
    journal-append-from-anywhere exception). The exception is documented at its canonical home, AGENTS
    §"Writes happen in a worktree" (alongside the D-0049 / SPEC-0084 no-worktree exceptions)."""
    # THE VERSION FLOOR (T-12045, SPEC-0195 rule 9) — the FIRST thing this verb does, above the
    # dry-run seams and above every early-return mode, because "before any mutation" is a statement
    # about POSITION and this is the only position that satisfies it for all of them: each mode below
    # writes, and a check placed inside one of them would leave the others unguarded.
    #
    # The CONTENT is the consumer's own tree, the ENGINE is the one about to scaffold into it. Inert
    # for every consumer today — neither side ships a release manifest, so the verdict is
    # `engine-unknown`/`not-declared` and init proceeds byte-unchanged; it bites only once a project
    # actually installs released content, which is the pair rule 9 is about. It runs on the DRY-RUN
    # path too, deliberately: a dry run reports what a real run would do, and a real run would refuse.
    refuse_out_of_floor(REPO_ROOT, ENGINE_ROOT, seam="init")

    # DRY-RUN (T-10271 / X-0243) — swap the three mutation seams for recorders and redirect the two
    # written-then-read-back files into a scratch overlay. Everything below then runs UNCHANGED: the plan
    # is exactly what the real body computes, because it IS the real body (see `_DryRunPlan`). Must precede
    # the `--adopt-concern` branch so that op previews too (it uses only these same seams).
    dry = bool(getattr(args, "dry_run", False))
    plan = _DryRunPlan(REPO_ROOT) if dry else None
    if dry:
        write_text_atomic = plan.write_text_atomic
        _append_event = plan.append_event
        _run_git_cap = plan.run_git_cap(_run_git_cap)
    ops_path = plan.scratch(CONSUMER_OPS_CONTRACT) if dry else REPO_ROOT / CONSUMER_OPS_CONTRACT
    memory_path = plan.scratch("MEMORY.md") if dry else REPO_ROOT / "MEMORY.md"
    _chained = {CONSUMER_OPS_CONTRACT: ops_path, "MEMORY.md": memory_path}

    # PURE ADOPTION-RECORD MODE (T-10265 / X-0251) — at the TRUE TOP of cmd_init, before the legacy
    # CROSS-TASKS guard and therefore before ANY filesystem write. `--adopt-concern` declares one job
    # (record one adoption entry, SPEC-0143 Rule 2); running it through the bootstrap body below
    # re-delivered every if-absent born scaffold as a silent side effect — re-materializing files a
    # consumer had deliberately deleted (social-parser: bin/security-audit + .trigger, the X-0239 hazard).
    # Scaffold delivery stays single-homed on the BARE init path below, unchanged.
    if getattr(args, "adopt_concern", None):
        return _adopt_concern_only(REPO_ROOT, args, ops_path=ops_path, plan=plan,
                                   _append_event=_append_event,
                                   _run_git_cap=_run_git_cap, write_text_atomic=write_text_atomic)

    # PURE CARRIER-WRITE MODE (T-10535 / X-0401) — the same early return, for the same X-0251 reason:
    # `--declare-theme` appends ONE inspection theme (SPEC-0093 rule 12) as a surgical TEXT edit, and
    # must not re-deliver the born scaffolds the bare-init body below would.
    if getattr(args, "declare_theme", None):
        return _declare_theme_only(REPO_ROOT, args, ops_path=ops_path, plan=plan,
                                   _append_event=_append_event,
                                   _run_git_cap=_run_git_cap, write_text_atomic=write_text_atomic)

    # The actual verb-invocation form for THIS repo, computed ONCE up front (T-9796; the render at the
    # born-scaffold seed below reuses it). A consumer has NO local `bin/yitc-v2`, so a bare `bin/yitc-v2
    # <verb>` in a consumer-facing stderr is command-not-found — every operator-facing failure message
    # below (the legacy-CROSS-TASKS guard, the extension-catalog completeness sweep) must name the engine
    # `-C` form (`<engine>/bin/yitc-v2 -C <path>`) for a consumer, else the bare `bin/yitc-v2` for the
    # engine self-init. Single-SoT for the born-content render at the tail of cmd_init too.
    # T-10530 (X-0393): the engine path BAKED into a born scaffold must name the DURABLE INSTALL root
    # (the main checkout), never the invoking — possibly ephemeral — worktree, which dies at the kernel
    # `land`. Content reads keep using ENGINE_ROOT (the invoking checkout); only this outliving STRING
    # resolves to the install. See `_engine_install_root`.
    # T-10982 — hoisted ABOVE the `--backfill-mandatory` early return below (it was under `created`/
    # `skipped`): the backfilled block BAKES this same string into the carrier, and duplicating the
    # expression inside the mode would give it a second home to drift from (CHARTER §P5). Both reads are
    # pure (`_engine_install_root` runs `git worktree list`), so the pure-carrier-write modes stay
    # side-effect-free before their write.
    _engine_install = _engine_install_root(ENGINE_ROOT, _run_git_cap)
    _cli_form = f"{_engine_install}/bin/yitc-v2 -C {REPO_ROOT}" if _is_consumer_build() else "bin/yitc-v2"

    # PURE CARRIER-BACKFILL MODE (T-10982 / SPEC-0093 rule 11) — the third early return of this family,
    # for the X-0251 reason above PLUS one unique to it: the bare-init body ENDS in the two fail-closed
    # sweeps, and T-10688 rewinds every pre-sweep carrier delivery on refusal. A section delivered
    # UNANSWERED makes that sweep refuse BY CONSTRUCTION, so on the ordinary path this delivery would
    # ALWAYS be rolled back before init exits (measured 2026-08-12). Returning BEFORE the sweeps is what
    # makes the scaffold persist — and the mode answers nothing, so the sweep it skips still refuses on
    # the very next ordinary init. Scaffold delivery stays single-homed on the BARE init path below.
    if getattr(args, "backfill_mandatory", False):
        return _backfill_mandatory_only(REPO_ROOT, args, ops_path=ops_path, plan=plan,
                                        cli_form=_cli_form, _append_event=_append_event,
                                        _run_git_cap=_run_git_cap, write_text_atomic=write_text_atomic)

    # PURE EXTENSION-ADOPTION MODE (T-11189 / X-0941) — the FOURTH early return of this family, for the
    # X-0251 reason exactly: `--adopt-extension` appends ONE `extensions.adopts` entry, but reached that
    # write only by falling through to the `_adopt_extensions` call site deep in the bare-init body, so
    # the rule-11 update above it ALSO delivered every missing born top-level section. social-scraper's
    # worker adopted one extension, received `sandbox_entry` + `audit_scrutiny` (a HELD sibling card's
    # declared surface), and had to HAND-REVERT both as text to keep its diff card-scoped. Placed LAST of
    # the four so every mixed-flag combination is still caught by whichever sibling branch is reached
    # first — none of them can be silently dropped. Still before any filesystem write. Scaffold delivery
    # stays single-homed on the BARE init path below, unchanged.
    if getattr(args, "adopt_extension", None):
        return _adopt_extension_only(REPO_ROOT, args, ops_path=ops_path, plan=plan,
                                     ENGINE_ROOT=ENGINE_ROOT, _append_event=_append_event,
                                     _run_git_cap=_run_git_cap, write_text_atomic=write_text_atomic)

    created: list = []
    skipped: list = []

    # LEGACY CROSS-TASKS.md GUARD (T-9492 / X-0083) — runs at the TRUE TOP of cmd_init, BEFORE any
    # filesystem write or other stateful action, so a refusal is guaranteed side-effect-free (audit-pre
    # finding 1). CROSS-TASKS.md is the RETIRED per-repo cross surface (SPEC-0075/SPEC-0079, superseded
    # at the T-9293 cutover). A brownfield consumer can carry a PRE-EXISTING non-empty one holding an
    # un-migrated feature-request as orphan prose; the scaffold loop below would SKIP it silently (the
    # X-0083 silent-orphan failure on a now-stale premise). So on detecting a real un-migrated CROSS ITEM,
    # init does NOT proceed silently — it requires EITHER migration of the orphan content
    # (re-file it as cross items via `cross request` / tasks) OR a CONSCIOUS explicit waive carrying a
    # reason (`--waive-legacy-cross-tasks "<reason>"`, recorded into the consumer_init event). An empty /
    # born-template CROSS-TASKS.md (any kernel era) — and, since T-10906/X-0712, a correctly MIGRATED
    # T-10434 TOMBSTONE (markup only, zero items) — is unaffected. Transitional brownfield migration-safety
    # guard over a retired surface — justified spec-less (no active spec governs it; SPEC-0093 on init.py
    # is the unrelated ops carrier; the cross-surface specs are superseded — see T-9492 analysis).
    legacy_cross_tasks_waived = None
    _legacy_ct_path = REPO_ROOT / "CROSS-TASKS.md"
    _legacy_ct_found = _legacy_cross_tasks_first_content_line(
        _legacy_ct_path.read_text(encoding="utf-8")) if _legacy_ct_path.exists() else None
    if _legacy_ct_found is not None:
        _waive_reason = str(getattr(args, "waive_legacy_cross_tasks", None) or "").strip()
        if not _waive_reason:
            # T-10906 / AC3: NAME what was found (line + kind + the text), so an operator tells an
            # un-migrated item from a tombstone without reading this guard's source. Composed INTO the
            # one refusal string — never printed above a generic fall-through
            # (lessons/carving-an-exception-into-a-fail-closed-gate.md §2).
            _fl_no, _fl_kind, _fl_text = _legacy_ct_found
            _fl_shown = _fl_text if len(_fl_text) <= 120 else _fl_text[:117] + "..."
            raise SystemExit(
                f"init: {_legacy_ct_path} carries content beyond the born-empty template — a pre-existing "
                "LEGACY cross surface (CROSS-TASKS.md, RETIRED at the T-9293 cutover; live surface = the "
                "shared coordination log, `cross request`/`cross inbox`). Refusing to proceed silently "
                "(it would orphan the un-migrated content).\n"
                f"  found: line {_fl_no} ({_fl_kind}): {_fl_shown}\n"
                "Either:\n"
                "  • MIGRATE the content — re-file each item as a cross request (`" + _cli_form + " cross "
                "request …`) or a task, then empty CROSS-TASKS.md back to the born template; OR\n"
                "  • CONSCIOUSLY WAIVE — re-run init with `--waive-legacy-cross-tasks \"<reason>\"` "
                "(the reason is recorded in the consumer_init journal event).")
        legacy_cross_tasks_waived = _waive_reason

    # SNAPSHOT the pre-delivery bytes of every init-managed path BEFORE the first write (T-10688) — the
    # rewind target if a fail-closed sweep below refuses. Real-run only: under --dry-run nothing touches
    # the real tree (writes are recorded / redirected to the scratch overlay), so there is nothing to
    # roll back. Captured HERE, after the side-effect-free legacy-CROSS-TASKS guard and before the first
    # scaffold write, so it faithfully records "as if init never ran". See `_restore_pre_sweep_delivery`.
    _pre_sweep_snapshot = None
    if not dry:
        _pre_sweep_snapshot = {}
        for _rel in _PRE_SWEEP_MANAGED_PATHS:
            _sp = REPO_ROOT / _rel
            _pre_sweep_snapshot[_rel] = _sp.read_text(encoding="utf-8") if _sp.is_file() else None

    # .gitignore FIRST (T-9310 / F-008): the ignore contract for the transient `.yitc` churn must be
    # established BEFORE anything else, so a fresh consumer never starts tracking `.yitc/` /
    # journal-sync-state/. Create if absent, else append ONLY the missing born lines (idempotent).
    gitignore_path = REPO_ROOT / ".gitignore"
    gitignore_added: list = []
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")
        existing_lines = {ln.strip() for ln in existing.splitlines()}
        to_add = [ln for ln in _BORN_GITIGNORE_LINES if ln not in existing_lines]
        if to_add:
            sep = "" if existing.endswith("\n") or not existing else "\n"
            block = sep + "\n# YITC consumer transient operational churn (F-008) — added by `init`\n" \
                + "\n".join(to_add) + "\n"
            write_text_atomic(gitignore_path, existing + block)
            gitignore_added = to_add
    else:
        write_text_atomic(
            gitignore_path,
            "# YITC consumer transient operational churn (F-008) — added by `init`\n"
            + "\n".join(_BORN_GITIGNORE_LINES) + "\n")
        created.append(".gitignore")
        gitignore_added = list(_BORN_GITIGNORE_LINES)

    # BORN AGENT SCRATCH IGNORE (T-11308 / X-1009) — its OWN idempotent append, kept SEPARATE from the
    # F-008 churn block above for the reason recorded at `_BORN_SCRATCH_IGNORE_LINES`: these lines must
    # NOT feed the `git rm --cached` untrack loop below. Same membership test as the block above
    # (`ln not in existing_lines`), so a re-run adds nothing and a line the consumer already wrote by
    # hand is never duplicated or clobbered. What it wrote is appended to the SAME `gitignore_added`
    # reporting accumulator — one reporting carrier, two content sources — so the summary line, the
    # `consumer_init` payload and the `material_delivery` bootstrap gate all pick it up with no new field.
    _scratch_existing = {ln.strip() for ln in
                         (gitignore_path.read_text(encoding="utf-8").splitlines()
                          if gitignore_path.exists() else [])}
    _scratch_to_add = [ln for ln in _BORN_SCRATCH_IGNORE_LINES if ln not in _scratch_existing]
    if _scratch_to_add:
        _cur = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
        _sep = "" if _cur.endswith("\n") or not _cur else "\n"
        write_text_atomic(
            gitignore_path,
            _cur + _sep
            + "\n# YITC agent scratch space (T-11308) — a sanctioned in-checkout working dir a verb's\n"
              "# `git add -A` will never sweep. `.scratch/*` (contents, not the dir) so the marker\n"
              "# below can be re-included; the tracked marker is what makes the path exist in a worktree.\n"
            + "\n".join(_scratch_to_add) + "\n")
        gitignore_added = list(gitignore_added) + _scratch_to_add

    # BORN ATOMIC-WRITE TEMP IGNORES (T-10992) — its OWN idempotent append, for the same two reasons
    # the scratch block above is separate: these lines must NOT feed the `git rm --cached` untrack loop
    # below (a rooted glob would derive a nonsense pathspec and could fail the whole `ls-files` call),
    # and keeping the block distinct lets a consumer read WHY each rule is there. Same membership test
    # (`ln not in existing_lines`), so a re-run adds nothing (AC3) and an already-bootstrapped consumer
    # is backfilled on its next init with no separate mechanism. Same `gitignore_added` reporting
    # accumulator — one carrier, now three content sources.
    _tmp_existing = {ln.strip() for ln in
                     (gitignore_path.read_text(encoding="utf-8").splitlines()
                      if gitignore_path.exists() else [])}
    _tmp_to_add = [ln for ln in _BORN_ATOMIC_TMP_IGNORE_LINES if ln not in _tmp_existing]
    if _tmp_to_add:
        _cur = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
        _sep = "" if _cur.endswith("\n") or not _cur else "\n"
        write_text_atomic(
            gitignore_path,
            _cur + _sep
            + "\n# YITC atomic-write in-flight scratch files (T-10992) — `write_text_atomic` writes a\n"
              "# dot-prefixed `.<name>.<rand>.tmp` beside its target and renames; a process killed\n"
              "# mid-write STRANDS one, which a verb's `git add -A` would otherwise sweep into a ship\n"
              "# diff. Narrow by design (never a blanket `.*.tmp`): every real artifact keeps shipping.\n"
            + "\n".join(_tmp_to_add) + "\n")
        gitignore_added = list(gitignore_added) + _tmp_to_add

    # BORN MKTEMP PAYLOAD-FILE IGNORE (T-11947 / X-1226) — its OWN idempotent append, for the same two
    # reasons the two blocks above are separate: these lines must NOT feed the `git rm --cached` untrack
    # loop below (a rooted glob derives `/tmp.??????????/`, which makes the whole `ls-files` call exit
    # 128 — measured — and a `!`-negated line derives a nonsense pathspec), and a distinct block lets a
    # consumer read WHY the rule is there. Same membership test (`ln not in existing_lines`), so a re-run
    # adds nothing and an already-bootstrapped consumer is backfilled on its next init with no separate
    # mechanism. Placed BEFORE the dot-dir deny block so that block stays LAST (its `!` re-includes must
    # remain the last matching patterns for a dot-dir path); the two rule sets are disjoint — `.*/`
    # selects dot-prefixed DIRECTORIES and never matches `tmp.<10 chars>`. Same `gitignore_added`
    # reporting accumulator — one carrier, now four content sources.
    _mktemp_existing = {ln.strip() for ln in
                        (gitignore_path.read_text(encoding="utf-8").splitlines()
                         if gitignore_path.exists() else [])}
    _mktemp_to_add = [ln for ln in _BORN_MKTEMP_IGNORE_LINES if ln not in _mktemp_existing]
    if _mktemp_to_add:
        _cur = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
        _sep = "" if _cur.endswith("\n") or not _cur else "\n"
        write_text_atomic(
            gitignore_path,
            _cur + _sep
            + "\n# YITC mktemp payload file (T-11947 / X-1226) — the kernel's own guidance tells a\n"
              "# session to compose an over-long event payload under `f=$(mktemp -p .)`, which yields a\n"
              "# NON-dot `tmp.<10 chars>` at the repo ROOT that a verb's `git add -A` would sweep into a\n"
              "# ship diff (observed in a consumer: it rode into a commit as a 4th file where 3 were\n"
              "# intended). Narrow by design — exactly ten `?`, root-anchored, never the blanket `tmp*`:\n"
              "# `tmp_helper.py` / `tmpdir_notes.md` / `bin/tmp.py` / `tmp.data/` all keep shipping. The\n"
              "# `!` line re-includes a root DIRECTORY of that shape (a pattern with no trailing slash\n"
              "# matches a dir too), so this denies the FILE the kernel prescribes and nothing wider.\n"
            + "\n".join(_mktemp_to_add) + "\n")
        gitignore_added = list(gitignore_added) + _mktemp_to_add

    # BORN UNDECLARED DOT-DIRECTORY DENY (T-11913) — its OWN idempotent append, LAST of the four
    # .gitignore blocks so its `!` re-includes are the last matching patterns for a dot-dir path.
    # Separate for the same two reasons the two blocks above are separate: these lines must NOT feed
    # the `git rm --cached` untrack loop below (a `!`-negated line derives a nonsense pathspec and can
    # fail the whole `ls-files` call), and a distinct block lets a consumer read WHY the rule is there.
    # The allowlist is DERIVED from what THIS consumer already tracks — never the engine's literal
    # `!/.claude/`, which is exact for the engine and would silently deny a new file under, e.g.,
    # aiseller's tracked `.github/workflows` (see `_born_dot_dir_ignore_lines`). Same membership test
    # (`ln not in existing_lines`), so a re-run adds nothing and an already-bootstrapped consumer is
    # backfilled on its next init; a consumer that TRACKS a new dot-directory later gains its
    # re-include on the next init too, since the derivation re-reads `git ls-files` every run. Same
    # `gitignore_added` reporting accumulator — one carrier, now four content sources.
    _tracked_ls = _run_git_cap(["ls-files", "-z"], REPO_ROOT)
    _dot_dir_lines = _born_dot_dir_ignore_lines(
        # `git ls-files` PLUS the born scratch marker this same init run tracks in its bootstrap
        # commit (staged in the `managed` list below) — so `.scratch/` is derived like every other
        # entry, from a path this repo tracks, rather than hard-coded into the allowlist.
        ([_p for _p in _tracked_ls.stdout.split("\0") if _p] if _tracked_ls.returncode == 0 else [])
        + [f"{_BORN_SCRATCH_DIR}/.gitkeep"],
        # The dot-prefixed DIRECTORY rules the F-008 churn block denies on purpose — passed from the
        # single-SoT tuple, never re-listed, so the two can never drift apart.
        denied_dot_dirs=[_ln for _ln in _BORN_GITIGNORE_LINES
                         if _ln.startswith(".") and _ln.endswith("/")])
    _dot_existing = {ln.strip() for ln in
                     (gitignore_path.read_text(encoding="utf-8").splitlines()
                      if gitignore_path.exists() else [])}
    _dot_to_add = [ln for ln in _dot_dir_lines if ln not in _dot_existing]
    if _dot_to_add:
        _cur = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
        _sep = "" if _cur.endswith("\n") or not _cur else "\n"
        write_text_atomic(
            gitignore_path,
            _cur + _sep
            + "\n# YITC undeclared dot-directory deny (T-11913, carrying T-11882 to consumers) — a\n"
              "# dot-prefixed DIRECTORY is denied by default so an UNDECLARED scratch dir cannot ride a\n"
              "# verb's `git add -A` into a ship diff; re-including one is the DECLARATION this requires.\n"
              "# The `!` lines below are DERIVED from the dot-directories this repo already TRACKS (git\n"
              "# tracking IS that declaration) — never copied from the engine. A tracked path is never\n"
              "# affected by .gitignore, so this cannot drop committed work; a NON-dot new directory is\n"
              "# untouched by it. Add one `!/<dir>/` line to declare a new legitimate dot-directory.\n"
            + "\n".join(_dot_to_add) + "\n")
        gitignore_added = list(gitignore_added) + _dot_to_add

    # UNTRACK pre-existing churn (T-9310 / F-008): a .gitignore does NOT untrack files a prior session
    # already committed. If the consumer tracked `.yitc/` / journal-sync-state/ before init ran, those
    # paths keep producing non-union merge conflicts that block `land`. Scope DOUBLY-narrow: pathspecs
    # derived from the single-SoT _BORN_GITIGNORE_LINES (the OUR-churn names — a bare-dir rule matches at
    # any depth, so top-level + `**/` glob) AND `--ignored --cached` (only tracked files git actually
    # ignores). The intersection untracks ONLY our bootstrap churn — never the consumer's OWN
    # ignored-but-tracked content, and never an unrelated path. No-op on a clean repo / re-run.
    untracked = 0
    untracked_paths: list = []   # T-10271: the dry-run names each untracked path (never a bare count)
    _churn_specs: list = []
    for _ln in _BORN_GITIGNORE_LINES:
        _name = _ln.rstrip("/")
        # DIRECTORY-content pathspecs (the born rules are trailing-slash DIR-only ignores): match the
        # CONTENTS of a `<name>/` dir at the root AND at any depth — never a plain FILE named `<name>`.
        _churn_specs += [f"{_name}/", f":(glob)**/{_name}/**"]
    tracked = _run_git_cap(
        ["ls-files", "-z", "--ignored", "--cached", "--exclude-standard", "--", *_churn_specs],
        REPO_ROOT)
    if tracked.returncode == 0 and tracked.stdout:
        churn = [p for p in tracked.stdout.split("\0") if p]
        untracked = len(churn)
        untracked_paths = list(churn)
        _run_git_cap(["rm", "--cached", "--quiet", "--ignore-unmatch", "--", *churn], REPO_ROOT)

    # .gitattributes (T-9519 / X-0086): seed the consumer's `events.jsonl merge=union` attribute so its
    # concurrent-worktree journal union-merge works out of the box (SPEC-0002; replicate the kernel line).
    # Same idempotent if-absent / append-if-missing shape as .gitignore above — create if absent, else
    # append ONLY the line when missing, NEVER clobbering the consumer's OWN existing attributes. The
    # append-if-missing path ALSO backfills an already-bootstrapped consumer (migrated before T-9519) on
    # its next init — no separate backfill mechanism (anti-cx F1). Bare-token membership (the line, not
    # the comment) keeps it idempotent across re-runs.
    gitattributes_path = REPO_ROOT / ".gitattributes"
    gitattributes_added = []   # T-11446: the born line(s) THIS run added (was a bool; still falsy when empty)
    if gitattributes_path.exists():
        existing_ga = gitattributes_path.read_text(encoding="utf-8")
        # T-11446: PER-LINE backfill. Each born line is appended only if ABSENT, so a consumer that
        # already carries the live-journal line still gains the archive-segment one on the next init
        # (a whole-block check keyed on the first line would skip it forever). `gitattributes_added`
        # becomes the LIST of lines this run actually wrote — falsy when there was nothing to add,
        # so every truthiness test on it below is unchanged.
        present = {ln.strip() for ln in existing_ga.splitlines()}
        missing = [(line, block) for line, block in _BORN_GITATTRIBUTES_BLOCKS if line not in present]
        if missing:
            sep = "" if existing_ga.endswith("\n") or not existing_ga else "\n"
            write_text_atomic(gitattributes_path,
                              existing_ga + sep + "".join(block for _line, block in missing))
            gitattributes_added = [line for line, _block in missing]
    else:
        write_text_atomic(gitattributes_path, _BORN_GITATTRIBUTES)
        created.append(".gitattributes")
        gitattributes_added = [line for line, _block in _BORN_GITATTRIBUTES_BLOCKS]

    # T-9469 (extended to ALL delivered scaffolds by T-9769): render the born command examples to the
    # actual verb-invocation form. A consumer has NO local bin/yitc-v2, so a bare `bin/yitc-v2 <verb>`
    # is command-not-found; render the `__YITC_CLI__` token to the engine `-C` form
    # (`<engine>/bin/yitc-v2 -C <path>`) for a consumer, else the bare `bin/yitc-v2` for the engine
    # self-init. Modeled on the polished kupiclub MEMORY.md. ONE shared render value for MEMORY.md,
    # the ops-carrier extensions comments, the ops-carrier UPDATE fragments, and the born catalog waives.
    # `_cli_form` is computed ONCE at the top of cmd_init (T-9796) — reused here (no recompute).
    _born_memory = _BORN_MEMORY_MD.replace("__YITC_CLI__", _cli_form)

    # T-9518 (RETARGETED by T-9719): seed a TRUTHFUL verify-section stance when this consumer already ships
    # a test suite — the born "no land-verify layer yet" waiver is a lie for a tests-bearing repo (X-0085 /
    # social-scraper). A no-tests repo gets the generated born template byte-identical (no regression). yitc-verify.yaml
    # is RETIRED (rule 5) — it is NO LONGER seeded; the verify home is the carrier `verify.layers`. A legacy
    # yitc-verify.yaml from a pre-T-9719 consumer is MIGRATED + removed below (_migrate_legacy_verify_yaml).
    # Render the `__YITC_CLI__` token in the born ops-carrier comments (extensions section) too (T-9769).
    _ops_body = _ops_carrier_body(REPO_ROOT).replace("__YITC_CLI__", _cli_form)

    # SPEC-0189 rule 8 BIRTH-RATIFICATION GATE (T-11985) — a born declaration that RELAXES a control is
    # written ONLY against an explicit owner confirmation; every unconfirmed one is WITHHELD, leaving the
    # section ABSENT (which reads fail-closed) — or, where the concern is presence-mandatory, letting the
    # EXISTING fail-closed sweep below refuse the birth. Concern-blind: the section set is the registry
    # stance walk, never a name. Interactive = a real TTY on BOTH ends and not a --dry-run preview (a
    # read-only preview must never block on a prompt); a noninteractive birth therefore confirms nothing
    # unless `--confirm-born-permissive SECTION:OWNER` carries it.
    import sys   # module-local idiom: init.py imports per-function, never at module level
    _bp_interactive = bool(not dry and sys.stdin.isatty() and sys.stdout.isatty())
    _bp_confirmations, _bp_sources = resolve_born_permissive_confirmations(
        getattr(args, "confirm_born_permissive", None), interactive=_bp_interactive)
    _ops_body, _bp_written, _bp_withheld = born_permissive_gate(_ops_body, _bp_confirmations)
    for _section in _bp_withheld:
        print(_born_permissive_withheld_hint(_section), file=sys.stderr)

    # Born scaffolds (if-absent): delivered AFTER the ignore contract is in place.
    scaffolds = [
        ("MEMORY.md", _born_memory),
        (CONSUMER_OPS_CONTRACT, _ops_body),   # SPEC-0093: the ops-contract carrier (declare-or-waive)
        (".no-v1-hooks", _BORN_NO_V1_HOOKS),
    ]
    for name, body in scaffolds:
        # `_chained` redirects yitc-ops.yaml + MEMORY.md to the dry-run scratch overlay (identity map on a
        # real run). Both are re-READ later this same run, so a discarded write would diverge the plan.
        path = _chained.get(name, REPO_ROOT / name)
        if path.exists():
            skipped.append(name)
        else:
            write_text_atomic(path, body)
            created.append(name)

    # T-10275 (SPEC-0147 §7): seed the project OWNER's onboarding station pointers into the buffer.
    # COMPUTE-ONLY HERE — the WRITE + EMIT are DEFERRED to the bootstrap-commit seam below (T-10470).
    #
    # Why deferred (X-0332, social-parser, twice on 2026-07-12): this fold used to WRITE MEMORY.md right
    # here, while init's ONLY commit is the bootstrap commit at the very END — behind two FAIL-CLOSED
    # sweeps (`_sweep_ops_carrier`, the SPEC-0112 catalog-completeness sweep) and the on_main gate. So an
    # init run that seeded a station and THEN aborted at a sweep (or ran off `main`, where no commit fires)
    # left MEMORY.md DIRTY on the consumer's main — and a dirty MEMORY.md sits in land's non-bookkeeping
    # set and wedges EVERY later land there (the X-0274 class). The write now happens ONLY where it is
    # immediately committed: an init seed write either RIDES the bootstrap commit or DOES NOT HAPPEN.
    #
    # The compute stays HERE (not at the seam) so the DRY-RUN plan keeps forecasting the seed faithfully
    # (T-10271 / X-0243 — every accumulator must be what a real run would do) and so `material_delivery`
    # below still counts a seed-ONLY delivery (buffer already existed, pointers did not) as material and
    # fires the commit. Pure text->text (the SAME `memory.seed_pointers` fold the `memory seed` verb uses —
    # one seed-write path), keeping init.py's no-lib-import shape. Nothing between here and the seam re-reads
    # MEMORY.md, so deferring the write cannot diverge a later reader.
    # IDEMPOTENT: a re-run re-seeds nothing (`onboarding_seeded == []`) → no write, no event, no commit.
    onboarding_seeded: list = []
    _onboarding_seeded_text = ""
    if _seed_onboarding is not None and memory_path.is_file():
        _onboarding_seeded_text, onboarding_seeded = _seed_onboarding(
            memory_path.read_text(encoding="utf-8"))

    # CONSUMER vendor-adapter doctrine (SPEC-0125): born a THIN CLAUDE.md + ensure the neutral home
    # exists. Consumer-only — the engine's own CLAUDE.md/AGENTS.md ARE the handbook, never re-born.
    # T-10690 (X-0528): the `__PROJECT__` token renders to the consumer's own repo-root dir name at
    # delivery (a real project identity, not a placeholder). A pre-fix consumer still carrying the leaked
    # `<project>` placeholder is re-stamped ONLY under `--refresh-scaffolds` (the T-10498 born-vs-present
    # boundary — PRESENT is never auto-healed silently); otherwise it is REPORTED as a pending refresh.
    adapter_restamped: list = []
    adapter_pending: list = []
    adapter_restamp_writes: dict = {}
    if _is_consumer_build():
        _adapter_refresh = bool(getattr(args, "refresh_scaffolds", False))
        adapter_created, adapter_restamped, adapter_pending, adapter_restamp_writes = (
            _ensure_consumer_vendor_adapter(
                REPO_ROOT, _cli_form, write_text_atomic,
                project_name=REPO_ROOT.name, refresh=_adapter_refresh))
        created.extend(adapter_created)

    # UPDATE the ops-contract carrier (T-9375 / SPEC-0093 rule 11) — the "pull a new kernel section into
    # an EXISTING consumer" path. For a carrier the scaffold loop SKIPPED (it already existed), deliver any
    # MISSING extensible top-level section the kernel has since added (security/ui/tests/inspection), born declare-or-
    # waive, non-destructively. A FRESH carrier just written above already carries every current section,
    # so this is a no-op there (re-run stays byte-identical). The slice-1 three stay mandatory — a missing
    # one is the sweep's fail-closed error below, NOT auto-added. Runs BEFORE the sweep so a pulled section
    # is validated this same run. Also delivers a MISSING born NESTED subfield (deploy.policy /
    # deploy.host_config) whose parent section is present (T-10031, closing the T-9439 gap).
    #
    # SPEC-0189 rule 8 ALSO APPLIES HERE (T-12001, the second half of T-11985). This path appends born
    # fragments into an EXISTING carrier, so it is the SECOND born-declaration write path and takes THIS
    # RUN's already-resolved confirmations through the SAME `born_permissive_gate` — an unconfirmed
    # relaxing declaration is neither appended nor reported pulled. The withheld set comes back through
    # `ops_bp_withheld` so the hint is printed HERE, beside the birth-path hint above, and a fresh birth
    # (whose carrier legitimately lacks the withheld section, so this path re-offers it) does not print
    # the identical sentence twice.
    ops_capability_disclosures: list = []
    ops_bp_withheld: list = []
    ops_sections_pulled = _update_ops_carrier(ops_path, write_text_atomic, _cli_form,
                                              disclosed_out=ops_capability_disclosures,
                                              born_permissive_confirmations=_bp_confirmations,
                                              withheld_out=ops_bp_withheld)
    for _section in ops_bp_withheld:
        if _section not in _bp_withheld:
            print(_born_permissive_withheld_hint(_section), file=sys.stderr)

    # RATIFY THE CONFIRMED BORN-PERMISSIVE DECLARATIONS (T-11985 / T-12001, SPEC-0189 rule 8 / option
    # F-2) — the confirmation is recorded as the declaration's ratification provenance through the
    # EXISTING adoption-record writer, under the CONFIRMING HANDLE. `pulled_sections` is the T-12001
    # leg: a born-permissive section the rule-11 update path delivered into an EXISTING carrier this
    # run arrived against THIS run's confirmation, so it is ratified on the same terms as a born
    # carrier's — per SECTION, so a pre-existing consumer's other stances are untouched (the
    # `_seed_catalog_waives` precedent, narrowed to the section that actually arrived).
    #
    # WHY IT RUNS HERE, AHEAD OF THE SWEEPS — the ORDER is load-bearing (T-12004, deviation
    # `born-permissive-withheld-then-later-ratified-stance-contradiction`). A consumer born WITHHELD
    # carries the pre-seed record `<concern>: na@init` while the section itself is absent. Re-running
    # init WITH the confirmation — the natural remediation path for every project born unconfirmed —
    # makes the rule-11 update leg above append the LIVE declaration; the SPEC-0143 rule-2 stance
    # cross-check inside `_sweep_ops_carrier` then reads stance `adopt` against that stale `na` record,
    # calls it a contradiction and EXITS THE PROCESS. Downstream of that exit nothing runs, so while
    # this call sat after the sweeps the lift was unreachable and an unconfirmed birth was effectively
    # IRREVERSIBLE through init (reproduced end-to-end on the live `audit_scrutiny` concern). Running
    # it HERE lifts the record to the live stance under the NAMED owner before the sweep judges it, so
    # the sweep sees a truthful ledger and passes. The sweep itself is UNTOUCHED — the contradiction is
    # removed, never excused. The lift stays bounded to a declaration that went LIVE THIS RUN by the
    # function's own `fresh_carrier or section in pulled` admission, unchanged, so the
    # `lessons/a-stance-mirror-is-only-sound-at-birth` widening stays forbidden.
    #
    # THE CARRIER WRITE IS PRE-SWEEP; THE JOURNAL EMIT IS NOT. The T-10688 rewind restores the carrier
    # if a later sweep refuses, but the journal is APPEND-ONLY — so emitting here would leave a durable
    # `born_permissive_ratified` row asserting a ratification whose birth was then REFUSED. (That is
    # NOT the D-0049 kept-refusal case: a refusal row records something that really happened; this one
    # would record something that did not.) So the emit seam handed to the ratifier BUFFERS, and the
    # rows are replayed through the real `_append_event` only once both sweeps have PASSED — the
    # deferred-write idiom this function already uses for `refreshed` (X-0332: a write must never
    # outlive an abort). The emit site, row shape, payload and order are unchanged.
    _bp_pending_rows: list = []
    born_permissive_ratified = record_born_permissive_ratifications(
        ops_path, _bp_confirmations, _bp_sources, write_text_atomic,
        (lambda _etype, _task, _data: _bp_pending_rows.append((_etype, _task, _data))),
        fresh_carrier=(CONSUMER_OPS_CONTRACT in created),
        pulled_sections=ops_sections_pulled)

    # NOTE — extension ADOPTION (`--adopt-extension`, SPEC-0093 rule 13 / SPEC-0101 §4) is NOT recorded
    # here any more (T-11189 / X-0941). It used to be: the flag had no early return, so it reached
    # `_adopt_extensions` only by falling through to a call site RIGHT HERE — below the rule-11 update
    # above, which therefore delivered every missing born top-level section as a silent side effect of a
    # one-record append (social-scraper received a HELD sibling card's `sandbox_entry` + `audit_scrutiny`
    # and hand-reverted both as text). It is now a PURE carrier write, `_adopt_extension_only`, taking the
    # same early return as its three siblings at the top of this function. A bare init therefore never
    # touches the `extensions.adopts` list — the birth-COMPLETE catalog seed below is the one thing it
    # writes into that section. `--extension-source` rides the narrow path with it (T-10775: a MODIFIER of
    # `--adopt-extension`, never a mode of its own), so it is not parsed here either.
    #
    # NOTE — per-concern ADOPTION (`--adopt-concern`, SPEC-0093 / SPEC-0143 Rule 2) is NOT recorded here.
    # It is a PURE adoption-record write handled by `_adopt_concern_only` at the top of this function
    # (T-10265 / X-0251): reaching it through this scaffold-delivering body silently re-materialized every
    # if-absent born scaffold. A bare init therefore never touches the `adoption:` section, and a concern
    # with no entry reads as not-yet-adopted (drift), NOT fail-closed declare-or-waive. The birth-only
    # PRE-SEED below is the one thing a bare init writes into that section.

    # SEED extension-catalog completeness (SPEC-0112, T-9596) — backfill the `extensions:` record
    # born-COMPLETE so a FRESH consumer (and a pre-SPEC-0112 brownfield consumer whose carrier has NO
    # `extensions:` section) carries an explicit declare-or-waive entry for every active+adoptable catalog
    # member, WITHOUT auto-healing a CONSCIOUS gap in a present section (rule-11 update precedent; the
    # absent-vs-present boundary settled by the T-9596 ceiling-convergence consult, option 1). Runs after
    # adopt (so an owner-adopted member is not also waived) and BEFORE the completeness sweep below (so a
    # backfilled born-waive is validated this same run). `fresh_carrier` = the carrier was just created
    # this run; a present-but-incomplete section is NOT seeded → it fails closed in the sweep.
    # `fresh_carrier` is TRUE when the carrier was just born this run OR its `extensions:` section was just
    # PULLED by the rule-11 update above (a pre-SPEC-0112 brownfield carrier missing the section): in both
    # the section is a fresh born `adopts: []`, so backfilling it born-complete is the migration, NOT
    # auto-healing a conscious gap. A carrier whose extensions section was already present (not pulled) is
    # NOT backfilled → it fails closed on any gap (rule-1; consult option 1).
    catalog_members = _engine_catalog_members(ENGINE_ROOT)
    catalog_waived = _seed_catalog_waives(
        ops_path, catalog_members, write_text_atomic,
        fresh_carrier=(CONSUMER_OPS_CONTRACT in created or "extensions" in ops_sections_pulled),
        cli_form=_cli_form)

    # SEED the ONE kernel-owned `repeated-work` sweep theme (SPEC-0160 rule 12, T-12053) — the BASELINE
    # inspection mechanism every consumer carries by owner directive (2026-09-04), no opt-out. Placed
    # beside the catalog-waive seed and for the same reasons: AFTER the carrier seed/update (so the
    # `inspection:` section exists) and BEFORE the fail-closed sweeps below (so a freshly seeded entry is
    # VALIDATED this same run, and the pre-sweep rewind still covers the write on a refusal).
    # It seeds only a NEVER-SEEDED section and never backfills a tampered one, so this ordering heals the
    # rollout case WITHOUT making the no-opt-out ERROR unreachable — see `_kernel_theme_seed_eligible`.
    # `fresh_section` mirrors the `_seed_catalog_waives` fresh-carrier expression above: the carrier was
    # BORN this run, or its `inspection:` section was just PULLED born-waived by the rule-11 update. In
    # both the section is freshly born, so the journal's previously-seeded marker does not speak to it.
    # ONE fold of this repo's journal, read by BOTH branches (it streams the whole logical history).
    kernel_theme_stamped = _kernel_theme_previously_seeded(REPO_ROOT)
    kernel_themes_seeded = _seed_kernel_theme(
        ops_path, write_text_atomic,
        previously_seeded=kernel_theme_stamped,
        fresh_section=(CONSUMER_OPS_CONTRACT in created or "inspection" in ops_sections_pulled))

    # UPGRADE IN PLACE a `repeated-work` theme the project declared BY HAND before the kernel seeded it
    # (SPEC-0160 rule 12, T-12059). Same seam, same ordering rationale as the seed above: after the
    # carrier seed/update, before the fail-closed sweeps, so the stamped entry is VALIDATED this same run
    # and the pre-sweep rewind still covers the write. The two branches are DISJOINT by construction —
    # the seeder is eligible only when the slug is absent from the section, the upgrade only when it is
    # present — so at most one of them writes, and the no-opt-out ERROR stays reachable in both
    # (see `_upgrade_kernel_theme`: an entry the kernel already stamped is never re-stamped).
    kernel_themes_upgraded = _upgrade_kernel_theme(
        ops_path, write_text_atomic,
        previously_seeded=kernel_theme_stamped)

    # MIGRATE a legacy yitc-verify.yaml into the carrier `verify.layers` (T-9719 / SPEC-0152 rule 5/16,
    # X-0140). The single-command verify home is RETIRED — there must never be two live homes (rule 5);
    # `land` REFUSES a present yitc-verify.yaml, so a pre-T-9719 consumer's contract is folded into the
    # carrier verify section + the legacy file removed here. No legacy file → no-op (fresh consumers never
    # had one). Runs AFTER the carrier seed/update/catalog-seed (so the `verify:` section it replaces
    # exists) and BEFORE the sweep (so the migrated section is validated this same run).
    legacy_verify_migrated = _migrate_legacy_verify_yaml(
        REPO_ROOT, CONSUMER_VERIFY_CONTRACT, CONSUMER_OPS_CONTRACT, write_text_atomic, _run_git_cap,
        ops_path=ops_path, apply=not dry)

    # SWEEP the ops-contract carrier declare-or-waive (T-9389 / SPEC-0093 rule 3 — fail-closed). The
    # carrier is born all-WAIVED (answered), so a fresh seed always passes; this catches a carrier the
    # owner later left a section UNANSWERED (declaration removed AND no reasoned waiver), deleted, or
    # wrong-typed. Runs on EVERY init (idempotent — born default passes). Self-contained (see header).
    #
    # ATOMICITY (T-10688): both fail-closed sweeps raise SystemExit on refusal. Without a rewind, every
    # PRE-SWEEP delivery above (a rule-11 carrier section pull, the legacy-verify fold, a freshly-created
    # scaffold) would be left STRANDED dirty/untracked on the consumer's main and wedge every later
    # `land` (X-0527 cluster). Wrap the sweeps: on refusal, restore the working tree + index to their
    # pre-delivery state (the durable journal refusal event, already appended by the catalog sweep, is
    # DELIBERATELY kept — D-0049), then re-raise the SAME SystemExit so init still exits non-zero.
    try:
        _sweep_ops_carrier(ops_path)

        # SWEEP extension-catalog completeness (SPEC-0112 rule-1/2 — fail-closed; T-9596). For every
        # active+adoptable catalog member the `extensions:` record MUST carry an explicit declare OR a
        # forward-aware waive; a missing member or a bare (empty-reason) waive is a HARD error here (emits
        # `extension_catalog_completeness_refused`, then exits non-zero) — never a silent "adopts nothing".
        # Runs after the born-complete seed above and BEFORE the bootstrap commit below, so a gap fails
        # closed before anything is committed. NON-catalog opt-in adoption stays governed by rule-13.
        _sweep_extension_catalog_completeness(
            ops_path, catalog_members, _append_event, REPO_ROOT, _cli_form)
    except SystemExit:
        if not dry:
            _index_untracked = list(untracked_paths)                 # churn `rm --cached` (index-only)
            _legacy_removed = (legacy_verify_migrated or {}).get("removed")
            if _legacy_removed:
                _index_untracked.append(_legacy_removed)             # legacy-verify `rm --cached`
            _restore_pre_sweep_delivery(REPO_ROOT, _pre_sweep_snapshot, _index_untracked,
                                        write_text_atomic, _run_git_cap)
        raise

    # PRE-SEED per-concern ADOPTION at the CURRENT registry version (SPEC-0143 Rule 2 pre-seed / T-10190).
    # Runs AFTER the declare-or-waive sweeps have PASSED (the carrier is now stance-valid) and BEFORE the
    # bootstrap commit below, so the mirror records ride the SAME governed bootstrap commit to the
    # consumer's own main. For every registry concern with NO adoption entry yet, it writes a record at the
    # concern's current version MIRRORING the just-made decision (declared → adopt; waived → waive; absent →
    # na). The init declare-or-waive sweep IS the birth review (SPEC-0128); recording adoption at current
    # makes the SPEC-0143 Rule-3 drift reconcile SILENT for a brand-new consumer (0 concern_drift_surfaced)
    # while a LATER real version bump still surfaces drift. NON-CLOBBERING: a record written by a prior run
    # — or by the separate `--adopt-concern` op (T-10265) — is left untouched, so a re-init is byte-stable.
    #
    # NEWBORN-ONLY (T-10262 / X-0240): gated on the carrier being BORN THIS RUN, because only then is the
    # sweep above a genuine BIRTH review. A pre-existing carrier holds stances authored against the OLD
    # concern definitions; mirroring them @current would silence real pending drift under the `init` sentinel
    # (social-parser: 14 lines) — the tool consuming the signal that is the owner's to consume. Deliberately
    # NOT the `_seed_catalog_waives` fresh_carrier expression below/above: its `or "<section>" in
    # ops_sections_pulled` disjunct (and its wholly-absent-section fallback) would re-admit exactly that
    # case — a concern section freshly PULLED into a LEGACY carrier, and a legacy carrier with no
    # `adoption:` block, ARE the drift the owner must review. Birth is the only pre-seed licence.
    # REPLAY the buffered ratification rows — the sweeps have PASSED, so the ratifications they
    # record are the ones that will actually reach the consumer's main (see the deferral rationale at
    # the ratifier call above `_sweep_ops_carrier`). A refused init reaches neither this line nor the
    # rewind's restored carrier carrying a ratification claim.
    for _etype, _task, _data in _bp_pending_rows:
        _append_event(_etype, _task, _data)

    concerns_preseeded = _preseed_concern_adoptions(
        ops_path, write_text_atomic,
        fresh_carrier=(CONSUMER_OPS_CONTRACT in created))

    # REFRESH A STALE BAKED ENGINE PATH (T-10533 / X-0393 sibling) — an ALREADY-initialized consumer
    # whose scaffolds carry a DEAD engine path is NEVER rewritten by the if-absent delivery above, so it
    # is permanently stuck. COMPUTE the path-only rewrites HERE — AFTER every carrier mutation (the rule-11
    # update, the catalog-waive seed, the concern pre-seed all write yitc-ops.yaml), so reading it now sees
    # the FINAL to-be-committed carrier and the deferred write cannot clobber those mutations. The
    # substitution touches ONLY the engine `<root>/bin/yitc-v2` prefix in front of the stable ` -C
    # <consumer>` tail, preserving the MEMORY.md buffer (SPEC-0039) + every other byte. A scaffold just
    # CREATED this run already carries the current install path → no-op. For MEMORY.md, base the rewrite on
    # the onboarding-seeded text when the seed also fired this run, so the deferred seed write (which
    # supersedes MEMORY.md at the seam) does not re-strand the dead path. Consumer-only: the engine
    # self-init has no baked `-C` engine path (`_cli_form == "bin/yitc-v2"`). Deferred write at the commit
    # seam (X-0332 discipline — a refresh must never outlive an abort as a dirty tracked file).
    refreshed: list = []
    _refresh_writes: dict = {}
    if _is_consumer_build():
        refreshed, _refresh_writes = _refresh_baked_engine_path(
            REPO_ROOT, _engine_install,
            memory_override=(_onboarding_seeded_text if onboarding_seeded else None))

    # DISTRIBUTED-ARCHITECTURE FOLDERS (T-9346, SPEC-0090 §3/§3a): a consumer gets a born-EMPTY
    # `lessons/` (PROJECT realm — it authors its OWN local-craft notes; kernel lessons NEVER travel)
    # and a read-only `patterns/` SURFACE (the post-split GENERAL patterns are DISTRIBUTED, their
    # content RESOLVES from the engine via the C3/T-9345 carrier — NOT copied). Each folder is born
    # with ONE marker (so it is present + git-tracked) and EMPTY of content files: `lessons/README.md`
    # (a docs helper the lesson walk excludes) and `patterns/.gitkeep` (a non-`*.md` the pattern walk
    # never indexes). NO pattern file is delivered ON PURPOSE — a copy would own-WINS+freeze (defeat
    # refresh) and be a shadow-authoring home (break the read-only invariant), the REJECTED
    # "vendor-a-copy" failure mode of SPEC-0090 §3a. Idempotent: mkdir is exist_ok and the marker is
    # if-absent, so a re-run (or a consumer that already authored lessons) is a no-op for the marker.
    # `graph/.gitkeep` (E-0038 finding 2): keep the derived-graph dir TRACKED from birth so a manual
    # `-C graph build` before the first land leaves its derived files as INDIVIDUAL allowlisted entries
    # (foldable) instead of a wholly-untracked `graph/` dir that aborts the fold. Same if-absent marker
    # shape as the two surfaces above; a no-op for the engine self-init (graph/.gitkeep already tracked).
    folder_deliveries = [
        ("lessons", "README.md", _BORN_LESSONS_README),
        ("patterns", ".gitkeep", _BORN_PATTERNS_GITKEEP),
        ("graph", ".gitkeep", _BORN_GRAPH_GITKEEP),
        # T-11308 / X-1009: the born agent scratch home. Identical if-absent marker shape as the
        # three surfaces above, so a re-run — or a consumer that already made `.scratch/` and put
        # work in it — is a no-op and nothing is clobbered. The marker is TRACKED (the `.gitignore`
        # negation above re-includes it) so the directory materializes in every `worktree new`
        # checkout, which is where a dispatched worker actually needs it.
        (_BORN_SCRATCH_DIR, ".gitkeep", _BORN_SCRATCH_GITKEEP),
    ]
    folders_created: list = []
    for sub, fname, body in folder_deliveries:
        if not dry:                       # T-10271: mkdir bypasses the write seam — a preview creates nothing
            (REPO_ROOT / sub).mkdir(parents=True, exist_ok=True)
        marker = REPO_ROOT / sub / fname
        rel = f"{sub}/{fname}"
        if marker.exists():
            skipped.append(rel)
        else:
            write_text_atomic(marker, body)
            created.append(rel)
            folders_created.append(sub)

    # SECURITY-AUDIT CADENCE SCAFFOLD (T-10186, SPEC-0145 §6 / SPEC-0142): deliver the deterministic
    # runner + the provider-independent system-trigger unit TEMPLATE (carrying the born `security.audit`
    # declaration/waiver) into the consumer, if-absent (seed-and-grow). RECORD the trigger for the
    # owner-gated host-apply seam via `cadence_scaffold` in the consumer_init event below — init does NOT
    # install a host cron (no host mutation). SPEC-0145 is CITED, not activated (no born-ops/registry
    # change here — that is T-10188). CONSUMER-ONLY (the `_REMATERIALIZE_TEMPLATES` precedent): the engine
    # authors + owns its OWN security-audit setup directly and must not gain a spurious trigger template
    # from its self-init; a fresh CONSUMER is the onboarding audience this scaffold serves.
    # T-10498: `refresh` (the opt-in `--refresh-scaffolds`) decides WHAT a run rewrites; `apply` (the
    # inverse of `--dry-run`) decides WHETHER it writes at all. Orthogonal by construction — a refresh
    # write still rides the injected `write_text_atomic` seam, which a dry run swaps for the recorder.
    refresh = bool(getattr(args, "refresh_scaffolds", False))
    # T-10886 (X-0713) — the PER-FILE acknowledgement that a named scaffold's local lines may be lost.
    # Refuse-by-default is the rule; this is the operator's read-the-diff-then-adopt-anyway escape, so a
    # consumer can still converge on the kernel copy without init ever performing a SILENT deletion.
    accept_loss = set(getattr(args, "accept_scaffold_loss", None) or ())
    cadence_created, cadence_updated, cadence_pending, cadence_foreign, cadence_diverged = (
        _deliver_cadence_scaffold(REPO_ROOT, ENGINE_ROOT, write_text_atomic, apply=not dry,
                                  refresh=refresh, accept_loss=accept_loss)
        if _is_consumer_build() else ([], [], [], "", []))
    created.extend(cadence_created)
    # SPEC-0154 rule 5 — the generic runner tracked the kernel (producer identity positively matched).
    # Surface it VISIBLY: a consumer must be able to see that its probe was re-derived from the engine.
    if cadence_updated:
        import sys   # module-local idiom: init.py imports sys per-function, never at module level
        for rel in cadence_updated:
            print(f"  ↻ {rel} updated from the kernel scaffold (SPEC-0154 rule 5)", file=sys.stderr)
    # SPEC-0145 §9a — the scaffold REFUSED to install over a foreign producer. Surface it VISIBLY (an
    # owner-facing stderr notice), record BOTH withheld paths as `skipped`, and carry the reason on the
    # EXISTING `consumer_init` event (no new event type). init still exits 0 and delivers every other
    # scaffold: a brownfield consumer keeping its own producer is the CORRECT outcome, not a failure.
    if cadence_foreign:
        import sys   # module-local idiom: init.py imports sys per-function, never at module level
        skipped.extend(["bin/security-audit", "bin/security-audit.trigger"])
        print(f"  ⚠ security-audit cadence scaffold WITHHELD — {cadence_foreign}", file=sys.stderr)
        print("    Neither bin/security-audit nor bin/security-audit.trigger was delivered "
              "(SPEC-0145 §9a, fail-closed).", file=sys.stderr)
        print("    Remedy: keep your own producer (run IT on your cadence), or retire it and declare "
              "`security.audit.runner: bin/security-audit` in yitc-ops.yaml.", file=sys.stderr)
    cadence_scaffold = {
        "runner": "bin/security-audit" if "bin/security-audit" in cadence_created else None,
        "trigger": "bin/security-audit.trigger" if "bin/security-audit.trigger" in cadence_created else None,
        "recorded_for_host_apply": True,   # RECORDED for the owner-gated host-apply seam — NOT installed
        "foreign_producer": cadence_foreign or None,   # SPEC-0145 §9a refusal reason (None when clear)
        "updated": cadence_updated or None,   # SPEC-0154 rule 5 — paths re-derived from the kernel scaffold
        "pending_refresh": cadence_pending or None,   # T-10498: drifted, reported, NOT rewritten (no --refresh-scaffolds)
    }

    # REMATERIALIZE engine-owned scaffold templates from the kernel (T-9312 / F-023): the templates a
    # consumer reads via `_kernel_content_file` are OWN-WINS, so a consumer's hand-copied + DRIFTED
    # template (e.g. specs/_template.yaml lacking the SPEC-0073 `travels:` placeholder) own-wins and
    # makes `spec new --travels` refuse. Re-DERIVE them from the ENGINE source-of-truth each run
    # (overwrite-if-different) so they track the kernel. Read ENGINE_ROOT/rel EXPLICITLY — NOT the
    # own-wins `_kernel_content_file`, which would return the drifted copy this is replacing. Reading the
    # engine + writing the consumer is territory-safe (never writes the engine). Consumer-only; the
    # engine self-build (ENGINE_ROOT == REPO_ROOT) skips → byte-unchanged. Idempotent (writes on diff).
    #
    # T-10498 (X-0358/X-0365): an ABSENT template is still installed flag-free (bootstrap unchanged), but
    # a PRESENT-and-drifted one is no longer rewritten silently — it becomes a reported PENDING refresh,
    # applied only under `--refresh-scaffolds`. Same born-vs-present boundary as the cadence runner above.
    rematerialized: list = []
    templates_pending: list = []
    templates_diverged: list = []
    if _is_consumer_build():
        for rel in _REMATERIALIZE_TEMPLATES:
            eng = ENGINE_ROOT / rel
            if not eng.exists():
                continue
            kernel_text = eng.read_text(encoding="utf-8")
            dst = REPO_ROOT / rel
            if dst.exists() and dst.read_text(encoding="utf-8") == kernel_text:
                continue                  # already kernel-current — nothing to do
            if dst.exists() and not refresh:
                templates_pending.append(rel)   # drifted: REPORT it, never a silent rewrite
                continue
            if dst.exists():
                # T-10886: same safety question as the cadence runner — a template a consumer has grown
                # lines into is destroyed by an unconditional re-derive just as a runner is.
                _loss = _scaffold_refresh_refusal(ENGINE_ROOT, rel, dst.read_text(encoding="utf-8"),
                                                  kernel_text, accept_loss)
                if _loss:
                    templates_diverged.append((rel, _loss))
                    continue
            if not dry:                   # T-10271: mkdir bypasses the write seam — a preview creates nothing
                dst.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(dst, kernel_text)
            rematerialized.append(rel)

    # THE STALENESS SIGNAL (X-0365) — one ordered list across both refresh-class sources, reported
    # report-only. It never fails init and never enters `material_delivery` below: nothing was written,
    # so nothing is committed. Printed even on an otherwise no-op re-init — that is the whole point (a
    # consumer must be able to SEE that its kernel-delivered producer is stale).
    pending_refresh = list(cadence_pending) + templates_pending + adapter_pending
    if pending_refresh:
        import sys   # module-local idiom: init.py imports sys per-function, never at module level
        print(_render_pending_scaffold_refresh(pending_refresh, _cli_form), file=sys.stderr)

    # THE DIVERGENCE REFUSAL (T-10886 / X-0713) — one ordered list across both re-derivation sources.
    # Printed HERE (with the other scaffold signals) but ACTED ON at the very end of cmd_init: the refusal
    # is a TERMINAL VERDICT of the run, never an early abort. Every additive delivery of this same run —
    # the born sections `_update_ops_carrier` pulled, each absent scaffold bootstrapped — completes and is
    # committed; only the deleting overwrite is withheld. That is what keeps the safe half reachable when
    # the destructive half must not proceed (the bundling half of X-0713).
    diverged_scaffolds = list(cadence_diverged) + templates_diverged
    if diverged_scaffolds:
        import sys   # module-local idiom: init.py imports sys per-function, never at module level
        print(_render_diverged_scaffold_refusal(diverged_scaffolds, _cli_form), file=sys.stderr)

    # SWEEP retired per-repo surfaces (T-9610 / X-0110) — ACTIVELY remove a lingering born-empty / tombstone
    # CROSS-TASKS.md (the retired per-repo cross log, RETIRED at the T-9293 cutover). Runs AFTER the T-9492
    # content-bearing hard-fail guard at the top of cmd_init, so any CROSS-TASKS.md still present here is
    # empty/tombstone (the helper fail-closes on content either way). A content-bearing file is OUT OF SCOPE
    # — handled by that hard-fail guard; this sweep adds NO behavior for it. Emits a dedicated
    # `retired_surface_swept` event when it removes something (the X-0110 probe), so the removal is durable
    # in the journal regardless of whether the bootstrap commit fires this run.
    retired_surfaces_swept = _sweep_retired_surfaces(REPO_ROOT, _run_git_cap, apply=not dry)
    if retired_surfaces_swept:
        _append_event("retired_surface_swept", None, {
            "path": str(REPO_ROOT),
            "surfaces": retired_surfaces_swept,   # e.g. ["CROSS-TASKS.md"] — born-empty/tombstone retired surfaces removed
        })

    _append_event("consumer_init", None, {
        "path": str(REPO_ROOT),
        "created": created,
        "retired_surfaces_swept": retired_surfaces_swept,   # T-9610: born-empty/tombstone retired per-repo surfaces removed this run ([] = none)
        "skipped": skipped,
        "gitignore_added": gitignore_added,
        "gitattributes_added": gitattributes_added,   # T-9519/T-11446: the born merge=union line(s) seeded/backfilled (SPEC-0002 live + SPEC-0190 archive)
        "untracked": untracked,
        "rematerialized": rematerialized,
        # T-10533: engine_path_refreshed is NOT reported here — this payload is assembled BEFORE on_main
        # is known and BEFORE the off-main skip, so it would over-claim a refresh that the on-main-gated
        # seam ultimately skips. The AUTHORITATIVE record is the dedicated `engine_path_refreshed` event
        # emitted at the commit seam, which fires ONLY when the refresh was actually written.
        "pending_refresh": pending_refresh,   # T-10498: kernel-managed scaffolds STALE vs the engine, REPORTED not rewritten ([] = none; apply via --refresh-scaffolds)
        "refresh_scaffolds": refresh,   # T-10498: was the opt-in refresh flag passed on this run?
        # T-10886 (X-0713): scaffolds whose re-derive was REFUSED because it would delete consumer-landed
        # lines. Rides the EXISTING consumer_init event (no new event type — the §9a foreign-producer
        # precedent); paths only, the hunks are the stderr surface.
        "diverged_refused": [rel for rel, _ in diverged_scaffolds],
        "folders": folders_created,   # T-9346: born lessons/ + read-only patterns/ surfaces
        "ops_capability_disclosures": ops_capability_disclosures,  # T-11366: sections that received the gated-capability stanza
        "ops_sections_pulled": ops_sections_pulled,   # T-9375: extensible sections pulled into an existing carrier (update)
        "onboarding_seeded": onboarding_seeded,   # T-10275: station pointers seeded for the project owner this run (SPEC-0147 §7; [] = none)
        "born_permissive_ratified": born_permissive_ratified,   # T-11971: concern sections whose RELAXING born declaration was written this run against a named human confirmation, with its ratification provenance (SPEC-0189 rule 8; [] = none, the unratified/noninteractive birth)
        "concerns_preseeded": concerns_preseeded,   # T-10190: concern sections pre-seeded to current version (mirroring declare-or-waive) so a new consumer starts drift-quiet (SPEC-0143 Rule 2; [] = none)
        "catalog_waived": catalog_waived,   # T-9596: catalog members born forward-aware-waived this run (SPEC-0112; [] = none)
        "themes_upgraded": kernel_themes_upgraded,   # T-12059: the project-declared theme(s) UPGRADED IN PLACE to kernel-owned this run (SPEC-0160 rule 12; [] = nothing to upgrade). Beside `themes_declared`, never instead of it: seeded and upgraded are different histories and the adoption evidence for the rollout names THIS key
        "themes_declared": kernel_themes_seeded,   # T-12053: the kernel-owned baseline inspection theme(s) SEEDED this run (SPEC-0160 rule 12; [] = already present / not a never-seeded section). SAME key + meaning as the `--declare-theme` payload — one event key, one meaning
        "legacy_cross_tasks_waived": legacy_cross_tasks_waived,   # T-9492: conscious-waive reason for a non-empty legacy CROSS-TASKS.md (None = not waived)
        "legacy_verify_migrated": legacy_verify_migrated,   # T-9719: {mode,removed} when a legacy yitc-verify.yaml was folded into verify.layers + removed (None = none)
        "cadence_scaffold": cadence_scaffold,   # T-10186: {runner,trigger,recorded_for_host_apply} — the security-audit cadence scaffold RECORDED for host-apply (NOT installed)
    })

    # SEED MAIN + BOOTSTRAP-COMMIT (T-9311 / F-004 + T-9463): a fresh consumer must reach `main` through
    # a GOVERNED path, not a loose dirty working tree. init is the consumer-bootstrap verb that already
    # delivers the first scaffolds WITHOUT a worktree (the documented worktree-gate exception above); by
    # the SAME chicken-and-egg basis it also COMMITS them — the sanctioned ONE-TIME bootstrap exception
    # (T-9463). A fresh consumer cannot ride worktree+land until init delivers its verify contract, so the
    # scaffolds + journal are committed directly to `main`. This dissolves the T-9458 cascade (scaffolds
    # left uncommitted on main → a manual git-clean / .gitignore-revert / dir-move dance before any land).
    # The exception is homed in AGENTS §"Writes happen in a worktree" alongside the D-0049 (journal-append)
    # and SPEC-0084 (cross-append) no-worktree exceptions — NOT a new spec (SPEC-0005 rule 8: a documented
    # exception to a handbook write-path rule is homed in that handbook section, not a parallel spec).
    #
    # Step 1 — ensure `refs/heads/main` exists AND is the checked-out branch (so the commit lands on main,
    # never a non-main default like master). Detect the LOCAL `main` explicitly (a bare `main` could
    # resolve a remote-tracking ref and wrongly skip seeding a missing local main — audit-pre F1).
    seeded_main = False
    local_main = _run_git_cap(["show-ref", "--verify", "--quiet", "refs/heads/main"], REPO_ROOT).returncode == 0
    head_exists = _run_git_cap(["rev-parse", "--verify", "--quiet", "HEAD"], REPO_ROOT).returncode == 0
    if not local_main:
        if head_exists:
            # Commits exist on a non-main default branch (e.g. master) → create `main` at HEAD, then
            # CHECK OUT main. The switch is CONTENT-NEUTRAL (main == HEAD, identical tree), so the staged
            # untrack removals + the unstaged scaffold writes carry over with no conflict, and the
            # bootstrap commit below lands them on main and leaves a clean tree. (Retiring the now-stale
            # source branch + the honor-the-consumer's-declared-default alternative are T-9465, which
            # requires this task — this task only guarantees the bootstrap reaches main + a clean tree.)
            if _run_git_cap(["branch", "main"], REPO_ROOT).returncode == 0:
                _run_git_cap(["checkout", "main"], REPO_ROOT)
                seeded_main = True
        else:
            # UNBORN HEAD (no commits): point HEAD at `main` so the bootstrap commit below creates it.
            _run_git_cap(["symbolic-ref", "HEAD", "refs/heads/main"], REPO_ROOT)
            seeded_main = True

    # Step 2 — the sanctioned one-time BOOTSTRAP COMMIT. Fires only when HEAD is on `main` (the unborn /
    # seeded / already-on-main cases) AND this run actually DELIVERED something material (a scaffold,
    # .gitignore line, untrack, main-seed, rematerialization, ops-section pull, or a cadence-scaffold
    # update — the SPEC-0154 rule-5 runner re-derived from the kernel, T-10457). A PRE-EXISTING main
    # while HEAD sits on a non-main branch is a divergence / normalization case left to T-9465 — no
    # auto-switch, no commit. The material-delivery gate keeps init IDEMPOTENT: a pure re-run delivers
    # nothing, so it makes NO commit — the `consumer_init` event it appended is ordinary journal dirt that
    # the next `land` folds (D-0049), exactly the post-bootstrap behavior. Stage ONLY the init-MANAGED
    # paths (NEVER `git add -A`, which would sweep the consumer's own files / transient churn into the
    # methodology bootstrap commit) + the already-staged `git rm --cached` untrack removals; staging the
    # `.gitignore` here COMMITS the `.yitc/` + journal-sync-state/ ignore contract on main so a subsequent
    # `land` does not refuse on that transient churn (deviation #4 / AC bullet 3). Commit IFF the index
    # then differs from HEAD.
    bootstrapped = False
    material_delivery = bool(created or gitignore_added or gitattributes_added or untracked or seeded_main
                             or rematerialized or ops_sections_pulled or ops_capability_disclosures or catalog_waived
                             or concerns_preseeded or retired_surfaces_swept
                             or legacy_verify_migrated or onboarding_seeded or cadence_updated
                             or refreshed or adapter_restamped)
    cur = _run_git_cap(["symbolic-ref", "--quiet", "--short", "HEAD"], REPO_ROOT)
    on_main = cur.returncode == 0 and cur.stdout.strip() == "main"

    # DRY-RUN EXIT (T-10271 / X-0243) — every accumulator above is now exactly what a real init would do,
    # computed by the real body. Render the plan and stop: no journal emit, no staging, no bootstrap
    # commit, no success wording. `would_bootstrap` mirrors the gate on the very next line.
    if dry:
        plan.render(untracked_paths=untracked_paths,
                    retired_swept=retired_surfaces_swept,
                    legacy_removed=(legacy_verify_migrated or {}).get("removed"),
                    concerns_preseeded=concerns_preseeded,
                    adoption_records=_preseeded_adoption_records(
                        ops_path.read_text(encoding="utf-8") if ops_path.exists() else "",
                        concerns_preseeded),
                    would_bootstrap=bool(on_main and material_delivery))
        # T-12094 (X-1267) — the SPEC-0096 r8 born-waiver/default sweep is a READ (it renders the
        # engine's already-generated checklist and writes nothing), so the read-only PREVIEW must
        # print it too. Before this, the dry-run exit sat ABOVE the sweep call at the tail of a real
        # run, so `--dry-run` printed NO sweep at all and the only way to READ the sweep was a BARE
        # (writing) init — exactly the incident. Same renderer, same call, both arms.
        _sweep = _render_init_concern_sweep(ENGINE_ROOT)
        if _sweep:
            print(_sweep)
        plan.cleanup()
        return

    if not on_main and onboarding_seeded:
        # OFF-main (the T-9465 divergence / normalization case): NO commit fires below, so performing the
        # seed write here would strand dirty MEMORY.md on the consumer's checkout — exactly the X-0332
        # wedge. The rule is "the write rides a scoped commit or it does not happen" (T-10470): SKIP it,
        # report it, and let the next on-main init deliver the pointers. Nothing is lost (the seed is
        # idempotent + recomputed every run); nothing is stranded.
        import sys   # module-local idiom: init.py imports sys per-function, never at module level
        onboarding_seeded = []
        print(f"consumer init ({REPO_ROOT.name}): onboarding seed SKIPPED — HEAD is not on `main`, so "
              f"init's bootstrap commit cannot carry the write and leaving it dirty would wedge the next "
              f"land (T-10470/X-0332). Re-run init on `main` to deliver the station pointers.",
              file=sys.stderr)

    if not on_main and refreshed:
        # OFF-main (T-9465): same X-0332 discipline as the onboarding seed — the deferred refresh write
        # below only fires on-main, so writing the refreshed scaffolds here would strand them dirty on the
        # consumer's checkout and wedge the next land. SKIP + report; the next on-main init re-computes and
        # applies the identical path refresh (idempotent — nothing is lost).
        import sys   # module-local idiom: init.py imports sys per-function, never at module level
        refreshed = []
        _refresh_writes = {}
        print(f"consumer init ({REPO_ROOT.name}): stale baked engine-path refresh SKIPPED — HEAD is not "
              f"on `main`, so init's bootstrap commit cannot carry the write (T-10533/X-0332). Re-run init "
              f"on `main` to repair the baked engine path.", file=sys.stderr)

    if not on_main and adapter_restamped:
        # OFF-main (T-10690 / X-0332): the adapter re-stamp write below is deferred + on-main-gated for the
        # SAME reason as the baked-path refresh — writing a modified tracked CLAUDE.md/AGENTS.md off-main
        # would strand it dirty and wedge the next land. SKIP + report; the next on-main `init
        # --refresh-scaffolds` re-computes and applies the identical re-stamp (idempotent — nothing lost).
        import sys   # module-local idiom: init.py imports sys per-function, never at module level
        adapter_restamped = []
        adapter_restamp_writes = {}
        print(f"consumer init ({REPO_ROOT.name}): adapter re-stamp SKIPPED — HEAD is not on `main`, so "
              f"init's bootstrap commit cannot carry the write (T-10690/X-0332). Re-run "
              f"`init --refresh-scaffolds` on `main` to re-stamp the adapter with the real project name.",
              file=sys.stderr)

    if on_main and material_delivery:
        # DEFERRED ONBOARDING SEED WRITE (T-10470 / X-0332) — performed HERE, immediately before the scoped
        # staging, so it is impossible for the write to outlive an abort: every fail-closed sweep and the
        # dry-run exit are already BEHIND us, and the `git add` + commit are the very next statements.
        # MEMORY.md + events.jsonl are already in `managed` below, so the write + its receipt ride THIS
        # governed commit (no second commit, no new mechanism — the T-9463 bootstrap seam, reused).
        if onboarding_seeded:
            write_text_atomic(memory_path, _onboarding_seeded_text)
            _append_event("onboarding_seeded", None, {
                "path": str(REPO_ROOT),
                "stations": onboarding_seeded,   # seeded THIS run; [] (no event) on an idempotent re-run
            })                                   # recipient = init's own OS user, carried on the pointer lines

        # DEFERRED STALE-BAKED-PATH REFRESH WRITE (T-10533 / X-0332) — same seam + discipline as the seed
        # write above: computed after every carrier mutation, applied HERE so it can never outlive an abort
        # as a dirty tracked file. Path-only rewrites (MEMORY.md / yitc-ops.yaml / CLAUDE.md are already in
        # `managed` below, so they ride THIS bootstrap commit). Written AFTER the onboarding seed write: for
        # MEMORY.md the refresh text was computed from the onboarding-seeded superset, so this final write
        # carries BOTH the station pointers and the repaired path (no re-stranding).
        for _rpath, _rtext in _refresh_writes.items():
            write_text_atomic(_rpath, _rtext)

        # DEFERRED ADAPTER RE-STAMP WRITE (T-10690 / X-0332) — same seam + discipline as the path refresh
        # above: CLAUDE.md / AGENTS.md are already in `managed` below, so the re-stamped bytes ride THIS
        # bootstrap commit and can never outlive an abort as a dirty tracked file. Written AFTER the path
        # refresh so a file touched by both carries both (the path-refresh dict never targets these titles).
        for _apath, _atext in adapter_restamp_writes.items():
            write_text_atomic(_apath, _atext)
        if adapter_restamped:
            # Surface the re-stamp VISIBLY — reported HERE (after the off-main skip cleared it, so it only
            # names writes actually applied this run, never a notice the off-main gate then contradicts).
            import sys   # module-local idiom: init.py imports sys per-function, never at module level
            for rel in adapter_restamped:
                print(f"  ↻ {rel} re-stamped with the real project name (SPEC-0125, T-10690/X-0528)",
                      file=sys.stderr)
            _append_event("adapter_restamped", None, {
                "path": str(REPO_ROOT),
                "scaffolds": adapter_restamped,   # adapter/home whose leaked `<project>` title was re-stamped
                "project_name": REPO_ROOT.name,
            })

        if refreshed:
            _append_event("engine_path_refreshed", None, {
                "path": str(REPO_ROOT),
                "scaffolds": refreshed,   # scaffolds whose stale baked engine path was repaired to the install root
                "install_root": str(_engine_install),
            })

        # NOTE: yitc-verify.yaml is RETIRED (T-9719) — no longer seeded, so it is NOT in `managed`; a
        # legacy one's DELETION is already staged by `_migrate_legacy_verify_yaml` (git rm --cached), so
        # the `git diff --cached` below picks it up and the bootstrap commit records the removal.
        # T-10498 — the REFRESH-CLASS paths (the two scaffolds init may re-derive from the engine) are
        # staged ONLY when THIS run actually wrote them. They used to be staged unconditionally-if-present,
        # which was harmless only because init ALWAYS rewrote them; now that a drifted one is merely
        # REPORTED, staging it anyway would sweep the consumer's OWN uncommitted edit of that path into
        # init's bootstrap commit — committing a refresh init did not write. Every other managed path is
        # if-absent-or-append and is unchanged. Staging stays scoped — never `git add -A`.
        _written = set(created) | set(cadence_updated) | set(rematerialized)
        _refresh_class = ("bin/security-audit", "bin/security-audit.trigger", *_REMATERIALIZE_TEMPLATES)
        # SPEC-0190-VERDICT: segment-aware — same judgement as the four carrier commits above, for the
        # same reason: `managed` is a scoped staging pathspec list, not a presence query. A first-run
        # bootstrap has no archive to add (the view returns the live segment alone, byte-identical to
        # the literal it replaces); a RE-RUN against a long-lived rotated consumer does, and that is
        # the case the literal got wrong.
        managed = [".gitignore", ".gitattributes",
                   *_journal_pathspecs(REPO_ROOT / "events.jsonl", REPO_ROOT), "MEMORY.md",
                   CONSUMER_OPS_CONTRACT, ".no-v1-hooks", "CLAUDE.md", "AGENTS.md",
                   "lessons/README.md", "patterns/.gitkeep", "graph/.gitkeep",
                   f"{_BORN_SCRATCH_DIR}/.gitkeep",   # T-11308: tracked, so the dir exists in every worktree
                   *(p for p in _refresh_class if p in _written)]
        present = [p for p in managed if (REPO_ROOT / p).exists()]
        if present:
            _run_git_cap(["add", "--", *present], REPO_ROOT)
        if _run_git_cap(["diff", "--cached", "--quiet"], REPO_ROOT).returncode != 0:
            _bootstrap_msg = (
                "chore: bootstrap consumer methodology scaffolds (yitc-v2 init)\n\n"
                "One-time governed bootstrap commit — the init worktree-gate exception (T-9463): a fresh\n"
                "consumer cannot ride worktree+land until init delivers its verify contract, so init\n"
                "commits its born scaffolds + journal directly to main (the .gitignore committed here\n"
                "also lets a subsequent land ignore the transient .yitc/ + journal-sync-state/ churn).\n\n"
                "from: SPEC-0051 — canonical write-flow + its no-worktree exceptions "
                "(AGENTS §Writes-happen-in-a-worktree EXCEPTION); consumer-bootstrap exception, T-9463\n")
            if _run_git_cap(["commit", "-q", "-m", _bootstrap_msg], REPO_ROOT).returncode == 0:
                bootstrapped = True

    if created or gitignore_added or gitattributes_added or untracked or seeded_main or bootstrapped or rematerialized or ops_sections_pulled or ops_capability_disclosures or catalog_waived or concerns_preseeded or born_permissive_ratified or retired_surfaces_swept or onboarding_seeded or refreshed or adapter_restamped:
        parts = []
        if created:
            parts.append("created " + ", ".join(created))
        if gitignore_added and ".gitignore" not in created:
            parts.append(".gitignore += " + ", ".join(gitignore_added))
        if gitattributes_added and ".gitattributes" not in created:
            # T-11446: name the line(s) this run actually added, not a fixed single literal.
            parts.append(".gitattributes += " + ", ".join(gitattributes_added))
        if untracked:
            parts.append(f"untracked {untracked} pre-existing churn path(s)")
        if ops_sections_pulled:
            parts.append("pulled ops section(s) " + ", ".join(ops_sections_pulled))
        if ops_capability_disclosures:
            parts.append("disclosed declaration-gated capabilit(ies) in " +
                         ", ".join(ops_capability_disclosures))
        if onboarding_seeded:
            parts.append(f"seeded {len(onboarding_seeded)} onboarding station pointer(s)")
        if born_permissive_ratified:
            parts.append("ratified born-permissive declaration(s) for " + ", ".join(
                f"{s} ({_bp_confirmations.get(s)})" for s in born_permissive_ratified))
        if concerns_preseeded:
            parts.append("pre-seeded concern adoption(s) @current " + ", ".join(concerns_preseeded))
        if catalog_waived:
            parts.append("born-waived catalog member(s) " + ", ".join(catalog_waived))
        if seeded_main:
            parts.append("seeded main")
        if bootstrapped:
            parts.append("bootstrap-committed scaffolds to main")
        if rematerialized:
            parts.append("rematerialized " + ", ".join(rematerialized))
        if refreshed:
            parts.append("refreshed stale baked engine path in " + ", ".join(refreshed))
        if adapter_restamped:
            parts.append("re-stamped project name in " + ", ".join(adapter_restamped))
        if retired_surfaces_swept:
            parts.append("swept retired surface(s) " + ", ".join(retired_surfaces_swept))
        print(f"consumer init ({REPO_ROOT.name}): " + "; ".join(parts))
        # T-12094 (X-1267) — DISCOVERABILITY. This branch is the WRITING report; name the read-only
        # form here exactly once, where the owner/worker who just wrote is looking. Deliberately NOT
        # on the no-op tail (nothing was written, so there is nothing to have previewed) and NOT under
        # `--dry-run` (that arm returns far above — the reader is already using the form).
        print(f"  (read-only preview of the same run: `bin/yitc-v2 -C {REPO_ROOT.name} init --dry-run` "
              f"— computes this report without writing, journaling or committing)")
    else:
        print(f"consumer init ({REPO_ROOT.name}): already initialized — no-op")

    # SPEC-0096 rule 8 (T-9529) — owner-visible born-waiver/default sweep: surface the generated SET of
    # init-defaultable concerns so EACH is decided explicitly (declare-or-waive), never a silent default.
    # Printed on every init (incl. the no-op re-init) — fail-soft empty when the engine artifact is absent.
    sweep = _render_init_concern_sweep(ENGINE_ROOT)
    if sweep:
        print(sweep)

    # T-10886 (X-0713) — THE TERMINAL VERDICT. A run that refused a deleting overwrite did NOT do what
    # `--refresh-scaffolds` was asked to do, so it must not exit 0 and be read as a completed refresh.
    # Placed LAST on purpose: everything additive above already ran, printed and committed, so the
    # non-zero exit reports the withheld half WITHOUT taking the safe half down with it. The notice
    # itself was printed with the other scaffold signals; this is only the exit code.
    if diverged_scaffolds:
        import sys   # module-local idiom: init.py imports sys per-function, never at module level
        sys.exit(1)

