"""verify_wiring — the CLI-side VERIFY-LEG BINDER, moved out of `bin/lib/cli.py` (T-12438, SPEC-0181 R1).

WHAT IS IN HERE. Four symbols, moved verbatim from cli.py, and nothing else:
  * `_VERIFY_IMPLEMENTATION_GLOBS` — the SPEC-0077 verifier-surface constant, still the ONE home of that
    file set (SPEC-0077 §1 points here);
  * `_is_verify_implementation_touch` — the predicate bound to it (a SPEC-0181 selection root);
  * `_run_verify_tests` / `_run_pinned_verify` — the thin residues that bind the CLI's collaborators into
    the runner (`bin/lib/verify_runner.py`) and the pinned driver (`bin/lib/rebaseline_currency.py`),
    through `bin/lib/worktree.py`'s own residues.

WHY THIS BOUNDARY. `bin/lib/cli.py` was refused on BOTH limbs of the T-11654 membership test
(tests/test_t11511_bin_periphery_allowlist.py) for exactly these four definitions plus one forwarded
keyword, while almost every edit to it touched argparse wiring that runs no verify leg and steers no
selection. Moving them OUT frees cli.py from rung R1 without freeing a verify participant: every future
edit to this wiring lands HERE, and this module refuses R1 on both limbs BY CONSTRUCTION (it defines both
verify-leg roots and the selection root). The card's two named homes could not take them —
bin/lib/verify_runner.py and bin/lib/worktree.py already define all four names (they are this chain's
downstream homes) and are `_SELECTION_ROOT_MODULES`, whose source feeds the reachability derivation for
every freed member.

SEAM — THE ONE CHANGE THE MOVE NEEDED. A residue's whole job is to bind the CLI's collaborators
(`_verify_test_timeout_seconds`, `_run_git_cap`, ...), which live in cli.py's module scope. They arrive here
as `_host_globals` — the CALLING cli module's `globals()` — read at CALL time, so a `-C` rebind or a test's
patch of that module is honoured. It is REQUIRED, and there is deliberately no `from lib import cli`
fallback: tests load cli.py as a SEPARATE module instance and patch ITS globals, so a back-import would
silently read the wrong instance. A missing argument fails loud. Names, positional signatures, defaults
and forwarded keywords are otherwise unchanged; cli.py re-exports nothing (its callers were re-pointed).
The two sites that load an engine tree themselves and call its runner by attribute — the pinned driver
(`worktree.py#_PINNED_VERIFY_DRIVER`) and the shipped PYRUN leg script (`remote_verify.py`) — resolve
BOTH vintages, this module first and a pre-move cli.py second.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). NOT in `_SELECTION_PERIPHERY_FREED_PATHS`:
a diff touching it still forces the full suite.
"""
from __future__ import annotations

import functools
from pathlib import Path

from lib import worktree as worktree_mod


# ── verify-implementation-touch predicate (SPEC-0077 §1) — the NARROW circular-trust trigger ──────
# T-1191 (plan harden-engine-pinned-verify-for-engine-lands-consu, CARD A). The predicate behind
# SPEC-0077's pinned last-green verify: does a change touch the VERIFIER'S OWN executable/config
# surface — the code+config that DECIDES a land's verdict? This is the FOUNDATION CARD B (T-1192)
# consumes to fire the pinned both-must-pass re-run; CARD A adds the predicate ONLY (no call-site wiring).
#
# DISTINCT from SPEC-0064's broad `observable` classifier (`_classify_inert_paths`, above): that answers
# "could this diff change the verify RESULT at all" (true for specs/, patterns/, ordinary product source).
# `observable ⊋ verify-implementation-touch`: a specs/-only or product-source land is observable but does
# NOT touch the verifier, so the circular-trust risk does not apply and the pinned re-run MUST NOT fire
# there (SPEC-0077 §4 negative contract). observable's file-class knowledge is a building block, NOT the
# trigger — this predicate is the one canonical home of the narrow set (with SPEC-0077 §1).
#
# COVERAGE OBLIGATION (SPEC-0077 §1) — cover the verifier's WHOLE executable/config surface, not only the
# named examples but EVERY executable or config input the verify path reads to reach its verdict:
#   • bin/**          — the engine CLI: the verify code path (_land_integrate / _run_verify_tests), the
#                       graph-build logic (cmd_graph_build / graph_build_index — there is NO separate
#                       graph-build script; it lives here), the test RUNNER, AND the config the
#                       verify-exercised features read (bin/*.yaml). Covers bin/lib/** (a future helper
#                       home, HYGIENE_EXCLUDED_SURFACES) by the prefix, so a new helper is in-scope.
#   • tests/**        — the test files the verify executes PLUS their imported helpers/fixtures
#                       (tests/_hermetic.py, tests/_read_gate.py, tests/_graph_build_sandbox.py): a change
#                       to a shared helper can flip every test's verdict, so it is verify surface.
#   • yitc-verify.yaml — the CONSUMER verify CONTRACT (`command:`/`waiver:`, T-0864). Under `-C` this file
#                       IS the verify — weakening it (a looser command, a waiver) weakens the verifier at
#                       the project level (SPEC-0077 §6b), the same circular-trust risk. Reuses the
#                       existing CONSUMER_VERIFY_CONTRACT constant (single-SoT — no re-hardcoded filename).
# This constant is the SOLE source-of-truth for the file set (SPEC-0005 rule 3 content-boundary — SPEC-0077
# §1 prose POINTS here and does NOT duplicate the list). Adding a NEW verify input obliges adding it here
# in the SAME change. fnmatch `*` spans `/`, so `bin/**` matches bin/yitc-v2 AND bin/lib/x.py AND bin/*.yaml;
# the whole pattern is anchored (fnmatch.translate adds \Z), so it matches only paths STARTING with the prefix.
#
# WHY bin/** (the whole dir), not an enumerated file list: bin/ is exclusively the engine's executable/
# config home — EVERY file under it is verifier surface (bin/yitc-v2 runs the verify + graph-build +
# conformance; the 3 config yamls are read by the verify TEST SUITE — e.g. test_effort_routing reads
# effort-routing-config.yaml, test_t0386_plan_gate_full_posture reads audit-config.yaml). An enumerated
# list would silently MISS a future bin/ verify input → a self-approval hole (the exact failure SPEC-0077
# closes). SPEC-0077 §3 is reliability-first: over-firing the pinned re-run costs one redundant verify
# (cheap, safe); under-firing is the circular-trust hole — so the predicate fires on the WHOLE verifier
# home and stays NARROW only against the §4 negative contract (specs/ · patterns/ · product src/ · docs/).
# T-9719 (SPEC-0152 rule 5/16): the consumer verify home MOVED from the retired yitc-verify.yaml to the
# carrier yitc-ops.yaml `verify.layers`, so the pinned-verify TRIGGER follows it — a consumer weakening its
# `verify.layers` must still fire the pinned last-green re-run (scenario D). Over-firing on any yitc-ops.yaml
# change is the safe side (cheap redundant verify); under-firing is the circular-trust hole.
# T-11461 (SPEC-0181): the `tests/**` arm is NARROWED at the SELECTION refusal only — a leaf test file
# (flat `tests/test_*.py`, present in the runner's own enumeration) no longer forces the full suite there,
# while shared test infrastructure, deletes and renames still do. The narrowing lives in the refusal
# predicate (`worktree.py#_selection_leaf_test_freed`), NOT in this tuple: this constant is also the
# SPEC-0077 pinned-verify TRIGGER above, which must keep firing on the WHOLE verifier home.
_VERIFY_IMPLEMENTATION_GLOBS = ("bin/**", "tests/**", "yitc-ops.yaml")


def _is_verify_implementation_touch(changed_files) -> bool:
    # Thin residue → worktree_mod._is_verify_implementation_touch (T-9340 inject seam; host-deps injected at call time).
    # T-12438: MOVED verbatim from bin/lib/cli.py — it binds no CLI collaborator (only the constant above), so no `_host_globals`.
    return worktree_mod._is_verify_implementation_touch(changed_files, _VERIFY_IMPLEMENTATION_GLOBS=_VERIFY_IMPLEMENTATION_GLOBS)


def _run_verify_tests(test_dir: Path, cwd: Path, workers: int | None = None,
                      timeout: "float | None" = None, journal_path=None, metrics_out: "dict | None" = None, monotonic=None, fail_fast: bool = True, selection_diff_paths=None, selection_diff_error=None, _reap_sandbox_residents=None, *, selection_reachability_freed=None, selection_tripwire_inert_paths=None, only: "set[str] | None" = None, select: bool = False, _selection_tripwire=None, durations_out: "list | None" = None, land_verify: bool = False, _host_globals) -> list:
    # Thin residue → worktree_mod._run_verify_tests (T-9340 inject seam; host-deps injected at call time).
    # T-12438: MOVED verbatim from bin/lib/cli.py. The CLI collaborators it binds arrive in `_host_globals`
    # (the calling cli module's globals(), REQUIRED — see the module docstring), read at CALL time.
    # T-10075: forward the optional injectable `monotonic` deadline clock (default None → real
    # time.monotonic in the module); production callers pass nothing → byte-identical behaviour.
    # T-10071: forward the optional `metrics_out` dict (SPEC-0132 Rule 2 per-land verify-metrics); default
    # None → not populated → byte-identical for callers that omit it (the pinned/nested drivers).
    # T-11476: forward `selection_tripwire_inert_paths` — the SPEC-0064 inert classification the
    # TRIPWIRE's needle set excludes. It has to exist HERE and not only on the module: this residue
    # IS the `_run_verify_tests` the land injects into `_land_integrate`, so a module-only parameter
    # is a TypeError on every land (measured at Stage 6, not guessed). Keyword-only + defaulted None
    # on the T-11316 terms, so the pinned driver capability-probing this signature never passes it
    # and a last-green engine predating the parameter is never handed an unknown argument.
    # T-10977: forward `fail_fast` (default True → the unchanged fast-abort). This residue is the entry
    # point the PINNED driver calls on the materialized last-green engine, so the parameter has to exist
    # HERE, not only on the module — the driver capability-probes THIS signature.
    # T-10080 (SPEC-0181): forward `selection_diff_paths` + the self-guard globs for the SHADOW
    # selection record. Default None → the selector's fail-closed R2 rung → a full-suite decision, so
    # every caller that omits it (the pinned/nested drivers) is byte-identical. The pinned driver
    # capability-probes this signature and never passes the new kwarg, so a last-green engine
    # predating it is never handed an unknown argument.
    # T-11118: forward `selection_diff_error` on the same terms — the reason a diff could NOT be
    # computed, so the record can say `diff-unresolvable:<error>` instead of the `no-diff` a
    # genuinely empty diff also produces. Default None → the empty/absent-diff reading is unchanged,
    # so every caller that omits it (the pinned/nested drivers, which capability-probe THIS
    # signature) stays byte-identical.
    # T-11463: forward `selection_reachability_freed` on the SAME terms — keyword-only + defaulted
    # None, so the pinned driver capability-probing THIS signature never passes it and a last-green
    # engine predating the parameter is never handed an unknown argument. Default None means the
    # verifier fence is judged by the path glob alone, i.e. exactly today's refusal.
    return worktree_mod._run_verify_tests(test_dir, cwd, workers, timeout, journal_path, metrics_out, fail_fast, selection_diff_paths, selection_diff_error, selection_reachability_freed=selection_reachability_freed, selection_tripwire_inert_paths=selection_tripwire_inert_paths, _VERIFY_IMPLEMENTATION_GLOBS=_VERIFY_IMPLEMENTATION_GLOBS, _emit_verify_timeout_deviation=_host_globals["_emit_verify_timeout_deviation"], _terminate_process_group=_host_globals["_terminate_process_group"], _verify_test_timeout_seconds=_host_globals["_verify_test_timeout_seconds"], _process_group_cpu_seconds=_host_globals["_process_group_cpu_seconds"], _reap_sandbox_residents=_reap_sandbox_residents, _emit_sandbox_survivor_deviation=_host_globals["_emit_sandbox_survivor_deviation"], _timeout_timing_phrase=_host_globals["_timeout_timing_phrase"], _verify_timeout_grace_seconds=_host_globals["_verify_timeout_grace_seconds"], EXPECTED_SESSION_REF_ENV=_host_globals["EXPECTED_SESSION_REF_ENV"], SESSION_REF_ENV_VARS=_host_globals["SESSION_REF_ENV_VARS"], SUBENV_SCRUB_CARRIERS=_host_globals["_SUBENV_SCRUB_CARRIERS"], _VERIFY_TIMEOUT_MARKER=_host_globals["_VERIFY_TIMEOUT_MARKER"], monotonic=monotonic, only=only, select=select, _selection_tripwire=_selection_tripwire, durations_out=durations_out, land_verify=land_verify)   # T-11462: forward the SPEC-0181 governing opt-in + its tripwire seam on the SAME keyword-only + defaulted-False terms — the pinned driver capability-probes THIS signature, so a last-green engine predating the parameter is never handed an unknown argument, and every caller that does not ask for it keeps the full enumeration; T-11456: forward the two-sided spawn-priority declaration on the SAME T-11316 terms — keyword-only + defaulted False, so the pinned driver capability-probing THIS signature never passes it and a last-green engine predating it is never handed an unknown argument. Default False is the SAFE default HERE: this residue is `task test --run`'s entry point (the path that SHOULD yield under the dispatched-worker marker), while the land declares itself True at its own call sites in worktree.py. T-11335: keyword-only + defaulted, on the T-11316 terms below — the red-batch isolation oracle's named subset; T-11316: keyword-only + defaulted, so the pinned driver capability-probing THIS signature never passes it and a last-green engine predating it is never handed an unknown argument


def _run_pinned_verify(W: Path, main_wt: Path, merged_base: str, branch: str, workers=None, admission_slots=None, admission_wait_out=None, only=None, excluded_out=None, skipped_out=None, *, _host_globals) -> list:
    # Thin residue → worktree_mod._run_pinned_verify (T-9340 inject seam; host-deps injected at call time).
    # T-12438: MOVED verbatim from bin/lib/cli.py; CLI collaborators arrive in `_host_globals` (REQUIRED), and the
    # runner it forwards is THIS module's `_run_verify_tests` bound to the SAME globals.
    # T-10074 (SPEC-0132 Rule 1): forward the land-admitted verify worker cap + concurrency slots.
    return worktree_mod._run_pinned_verify(W, main_wt, merged_base, branch, workers, admission_slots, _run_git_cap=_host_globals["_run_git_cap"], _consumer_zero_probe_guard=_host_globals["_consumer_zero_probe_guard"], _materialize_pinned_engine_bin=_host_globals["_materialize_pinned_engine_bin"], _run_verify_tests=functools.partial(_run_verify_tests, _host_globals=_host_globals), _read_worktree_stamp=_host_globals["_read_worktree_stamp"], _worktree_stamp_path=_host_globals["_worktree_stamp_path"], _utc_now_iso=_host_globals["_utc_now_iso"], SUBENV_SCRUB_CARRIERS=_host_globals["_SUBENV_SCRUB_CARRIERS"], _consumer_tests_delegation=_host_globals["_consumer_tests_delegation"], _delegated_tests_execution_gap=_host_globals["_delegated_tests_execution_gap"], admission_wait_out=admission_wait_out, _try_resolve_session_ref=_host_globals["_try_resolve_session_ref"], only=only, excluded_out=excluded_out, skipped_out=skipped_out)   # T-12307: the pinned-leg NARROWING sink (census-class / touched-by-this-branch), out to `verify_metrics.pinned_skipped` — same residue rule as `excluded_out` below: a keyword the impl grew and this residue does NOT carry dies TypeError at the land site before any leg runs. # T-12250: the prune's own names, out to `verify_metrics.pinned_excluded_not_pinned` — this THIN RESIDUE must carry every keyword the impl grew, or the land site's call dies TypeError before any leg runs. # T-11479: the file selection the step-4a waive-coverage preflight narrows to; None on every land path. # T-10972: the pinned re-run's own admission wait, into the land's per-attempt accumulator; T-11288: the NON-DYING keyer twin, so an UNSTAMPED source worktree stamps the pinned locus with THIS session's real ref instead of an invented marker (never the fail-closed `_resolve_session_ref` — it `_die`s here)
