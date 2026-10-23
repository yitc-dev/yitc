"""Argparse vocabulary — the enum/regex constants `build_parser` reads on EVERY invocation (T-11320).

WHY THIS LEAF EXISTS. `bin/yitc-v2` builds its whole parser before it knows the verb, and the
`choices=` / help text of several subparsers came off `lib/task.py` and `lib/worktree.py` — the two
heaviest hubs in `bin/lib` (task pulls 16 modules transitively, worktree 18). Reading one tuple off
them imported both, so EVERY invocation — and every test that merely loads the CLI — dragged in the
whole library graph whatever verb it exercised (T-11318 measured the resulting coupling: 84.7% of
tests import 33 of 34 modules independently of the verb under test). Homing the vocabulary in a leaf
that imports nothing but `re` is what lets the entry defer those hubs.

SINGLE HOME, NOT A COPY (CHARTER §Principle 5). The constants MOVED here; their previous owners
import them back and re-export under the identical names, so `task.TASK_CLASSES` /
`worktree.REBASELINE_KINDS` and every `yitc.<NAME>` test contract resolve the SAME object as before.
Nothing is duplicated, and nothing here states a rule — this module is plumbing: the meaning of each
value lives with the code that enforces it.

ADMISSION BOUND: only a constant that (a) is read while the parser is being CONSTRUCTED and (b) owns
no behaviour belongs here. A constant a verb reads at RUN time stays with its verb — moving it would
buy nothing and would scatter the domain.
"""
from __future__ import annotations

import re

# --- task vocabulary (moved from lib/task.py — re-exported there) ---
TASK_ID_RE = re.compile(r"^(T-\d{4,}|D-\d{4,}|SPEC-\d{4,}|phase-[\w-]+|[a-z0-9_-]+)$")
TASK_CLASSES = ("feature", "fix", "refactor", "docs", "infra", "hygiene")
TASK_PRIORITIES = ("high", "medium", "low")
TASK_FILING_STATUSES = ("ready", "parked", "wont-do")
TASK_OPEN_STATUSES = ("ready", "in-progress", "blocked")
TASK_LIST_STATUSES = ("ready", "in-progress", "blocked", "parked", "done", "wont-do")
PAUSE_REASONS = ("owner-wait", "audit-ceiling", "auditor-abort",
                 "batch-remainder", "session-end", "land-conflict",
                 # T-12304: a Controller-cued clean STOP (a re-plan-only / align-only brief step).
                 # Terminal + resumable: `--dispatch-status` reads it as `paused(controller-wait)`
                 # (never `working`), the dispatch in-flight guard yields to it without `--force`,
                 # and `dispatch --resume` relaunches from the recorded resume contract.
                 "controller-wait",
                 # T-12407 (<project> X-1322): a wait on a DECLARED artifact whose arrival a reader
                 # can DECIDE — the awaited item is named on the card (`task pause --awaits`), not
                 # inferred from prose. It exists because `owner-wait` was the only park available
                 # for an artifact wait and the session-start echo reads that reason ALONE: T-0422
                 # sat resumable for 8 days while three sessions were told it was waiting on the
                 # owner. This reason's card carries the awaited ref, so the echo can say RESUMABLE
                 # the moment the item closes instead of asserting a wait it cannot check.
                 "artifact-wait")
EFFORT_TIERS = ("normal", "critical")
EFFORT_TIER_DEFAULT = "normal"
HOST_CONFIG_KINDS = ("nginx-vhost", "cron", "systemd-unit", "other")

# --- plan vocabulary (moved from lib/plan.py — re-exported there) ---
PLAN_TERMINAL = ("realized", "partial", "rejected", "cancelled")

# --- worktree vocabulary (moved from lib/worktree.py — re-exported there) ---
REBASELINE_KINDS = ("broken", "unrunnable-here", "environmental")

# --- help-text vocabulary ---
# T-12930 (<project> X-1578): the ONE prescribed shape for a per-invocation temp file that feeds a verb
# (an over-long `event --data` payload, a `--from-stdin` mapping). It lives under the gitignored agent
# scratch dir `.scratch/` (T-11308), never the checkout ROOT: `_commit_worktree`'s verb-owned add-all
# stages every root file the narrow `/tmp.??????????` ignore (T-11947) does not match, so a templated
# `mktemp -p . msg-XXXXXX.yaml` rode into <project> commit b934c386. `mkdir -p` because the engine ignores
# the whole dir with no tracked marker, so a fresh engine worktree has no `.scratch/` yet.
SCRATCH_TEMPFILE_RECIPE = "mkdir -p .scratch && f=$(mktemp -p .scratch)"


# --- P8 evidence-ref grammar (moved from lib/task.py by T-13924 — re-exported there) ---
# Read while the parser is CONSTRUCTED (the `event` verb's help prints it, T-13924) and at run time by
# its other consumers through `task.P8_EVIDENCE_REF_GRAMMAR`, which is THIS object. The rationale and
# the consumer list stay beside the alias in `lib/task.py`; the forms' conditions live with their
# resolvers in `lib/task_closure_evidence.py`. A form added there is added here (T-12021).
P8_EVIDENCE_REF_GRAMMAR = (
    "ACCEPTED `evidence_events` REF FORMS (this is the WHOLE grammar — one example each): "
    "(1) `<event_type>` — a bare type, resolving only against a row of that type whose `task_id` is "
    "THIS task, e.g. `deploy_completed`; "
    "(2) `<event_type>@<iso-ts>` — the exact (type, ts) pin, for a mechanism row that carries no "
    "`task_id`, e.g. `deploy_completed@2026-09-03T05:58:57Z`; "
    "(3) `land_completed@<iso-ts>#<layer>` — a verify-LAYER row, e.g. "
    "`land_completed@2026-09-03T05:58:57Z#verify:default`; "
    "(4) `land_completed@<iso-ts>#branch=<branch>` — a land-time ABORT row, e.g. "
    "`land_completed@2026-09-03T05:58:57Z#branch=task/T-1234`; "
    "(5) `land_completed@<iso-ts>#refused=<test-node>&branch=<branch>` — a VERIFY-REFUSAL row (both "
    "halves required), e.g. `land_completed@2026-09-03T05:58:57Z#refused=tests/test_x.py::test_y"
    "&branch=task/T-1234`; "
    "(6) `land_completed@<iso-ts>#metric=<key>` — a post-ship `verify_metrics` payload-key reading, "
    "e.g. `land_completed@2026-09-03T05:58:57Z#metric=cache_hit_rate`; "
    "(7) `nightly_run_completed@<iso-ts>#surface=<verb>` — the bounded nightly (SPEC-0105) "
    "exercising a named surface, e.g. `nightly_run_completed@2026-09-03T05:58:57Z#surface=graph "
    "conformance`; "
    "(8) `exit:<verb>#seeded=<iso-ts>&clean=<iso-ts>` — an exit-status differential over a "
    "read-only conformance surface, e.g. `exit:graph conformance#seeded=2026-09-03T05:58:57Z"
    "&clean=2026-09-03T06:10:00Z`; "
    "(9) `test:<repo-relative test path>::<node>` — for code that emits IN-PROCESS and never a "
    "journal line, naming the executable test node that OBSERVED the emission. On a CONSUMER, one "
    "node, which the surface must carry: `test:tests/test_alerts.py::test_emits_on_threshold`. On "
    "the ENGINE the same form is admitted ONLY with a RED-CONTRAST node — "
    "`test:<repo-relative test path>::<node>&contrast=<node>` — naming a SECOND, DISTINCT node, "
    "where BOTH must be real "
    "`def` DEFINITIONS in that one surface, e.g. `test:tests/test_view.py::test_clause_fires"
    "&contrast=test_clause_silent_below_threshold`. It resolves for the ENGINE class that emits no "
    "journal row at all (a report-only STDOUT view; a committed-artifact reading); it proves the two "
    "nodes are DEFINED, never that they RAN or that the contrast failed — audit-post owns that. "
    "(10) `land_completed@<iso-ts>#gate=<test-file>` — a kernel-side land-verify GATE that journals "
    "nothing on PASS, proven by a REAL post-ship land on a branch OTHER than the citing task's own "
    "and LATER than its own last land, e.g. "
    "`land_completed@2026-09-03T05:58:57Z#gate=tests/test_event_catalog_completeness.py`. THREE "
    "conditions make it a MEMBERSHIP claim: the path matches the verify runner's OWN discovery glob "
    "`tests/test_*.py` (a file it would not discover never resolves); the file EXISTS AT THAT ROW'S "
    "LANDED REVISION (not merely in your checkout); and the row is a FULL, fail-closed run — a "
    "`verify_mode` saying the verify ran (never `candidate_policy_off`) and a `test_file_count` "
    "EQUAL to the number of `tests/test_*.py` files discoverable at that revision, so every "
    "discoverable file ran and the named one was among them. A SELECTED run, a count mismatch, a "
    "missing `verify_mode`/`test_file_count`, or an unresolvable sha does NOT resolve it. "
    "(11) `<project>:<form>` — ENGINE cards only: one of forms (2)-(6) read from the journal of a "
    "REGISTERED consumer instead of this one, for an engine mechanism whose only production run is on "
    "that consumer, e.g. `<project>:land_completed@2026-09-03T05:58:57Z#metric=cache_hit_rate`. "
    "`<project>` is that project's KEY in the host registry (a `yitc_v2` entry) — never a path — and "
    "the form keeps every condition it has without the prefix, applied to THAT journal's rows. Forms "
    "(1), (7)-(10) and (12) take no prefix, and the read is read-only. "
    "(12) `land_completed@<iso-ts>#adapter=<layer>` — a verify layer's SPEC-1035 ADAPTER, declared on a "
    "layer that already ran, proven by a land row (any branch, not earlier than the citing task's own "
    "FIRST successful land) whose `<layer>` row PASSED and carries an adapter record with `usable: true`, where some "
    "EARLIER land ran that layer WITHOUT one, e.g. "
    "`land_completed@2026-09-03T05:58:57Z#adapter=frontend`. "
    "NOT this grammar, and the look-alike that burns emissions (X-1245): the CHARTER §Principle-2 "
    "COMMIT locator `events.jsonl#ts=<ISO>` / `events.jsonl#source_ref=<locator>`. That spelling is "
    "correct for a `from:` trailer and resolves NOTHING here — it names no event type, so it can "
    "carry none of the correlation above. Use form (2) for the same row. "
    "Refs to the P8 types themselves, to tests_passed, or to closure bookkeeping "
    "(commit_landed/task_closed/land_completed WITHOUT one of the selectors (3)-(6), (10) or (12)) prove the task "
    "closed, never that its mechanism ran — they do not resolve."
)
