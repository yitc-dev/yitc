"""test_discovery — the ONE home of the `test_*.py` discovery glob (T-12694, plan
`extract-the-13-over-budget-bin-lib-modules-into-le` C1).

WHY THIS LEAF EXISTS. The 2026-09-13 architecture lens found the idiom
`sorted(<dir>.glob("test_*.py"))` inlined at 17 code sites across seven `bin/lib` modules — the
land's candidate leg, the pinned last-green leg, the Stage-6 runner, the remote venue route, the
duration table, the land-tail tripwire readers, the `init` born-layer seed. Seventeen copies of one
rule ("a test file is a flat `test_*.py` under the tests dir") is seventeen places for that rule to
drift: one site recursing, one filtering, one sorting differently, and two legs of the same verify
would silently disagree about what the suite IS. Plumbing for one rule has one home (CHARTER §P5).

CONTRACT — fixed, and pinned by `tests/test_test_discovery_contract.py`: FLAT (non-recursive — a
`sub/test_c.py` is not a member), SORTED (by path, which for one directory is by name), the pattern
FIXED at `test_*.py`, and UNFILTERED (no runnable/skip/marker judgement — that is the caller's).
Each call site was literally this expression before the rewrite, so the equivalence is static.
The `.name` projection a caller wants is `[p.name for p in test_files(d)]`; sorting paths of one
directory and sorting their names agree, so no site re-sorts.

Identity-agnostic KERNEL leaf (SPEC-0073 bin/ HARD class): stdlib-only, imports nothing from `lib`.
`tests/test_test_discovery_single_home.py` is the RULE tripwire — an AST scan of `bin/lib/*.py` +
`bin/yitc-v2` that fails on ONE re-inlined `.glob("test_*.py")` call outside this file.
"""
from __future__ import annotations

from pathlib import Path


def test_files(test_dir) -> list[Path]:
    """The test files of ONE directory: `sorted(Path(test_dir).glob("test_*.py"))` — flat, sorted,
    pattern fixed, unfiltered. A missing directory yields `[]` (glob on an absent path is empty),
    exactly as the inlined idiom did."""
    return sorted(Path(test_dir).glob("test_*.py"))
