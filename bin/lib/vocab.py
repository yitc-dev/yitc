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
                 "controller-wait")
EFFORT_TIERS = ("normal", "critical")
EFFORT_TIER_DEFAULT = "normal"
HOST_CONFIG_KINDS = ("nginx-vhost", "cron", "systemd-unit", "other")

# --- plan vocabulary (moved from lib/plan.py — re-exported there) ---
PLAN_TERMINAL = ("realized", "partial", "rejected", "cancelled")

# --- worktree vocabulary (moved from lib/worktree.py — re-exported there) ---
REBASELINE_KINDS = ("broken", "unrunnable-here", "environmental")
