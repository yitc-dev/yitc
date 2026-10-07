"""The environment of every git child the engine spawns — ONE function, in a stdlib-only leaf.

WHY A LEAF. The policy is used by the two git runners in `lib/cli.py` AND by every direct git launch
across `bin/lib` (T-13587). A leaf module must not import its host (`tests/test_bin_lib_leaf_no_host_import.py`,
SPEC-0080), so the one implementation cannot live in `cli.py` and be reached from the leaves; it lives
here, importing nothing but `os`; `cli.py` reaches it lazily through a forwarder of the same name. Rule home:
SPEC-0188 rule 7 (the reader discipline). Kernel placement (SPEC-0073 bin/ HARD class).
"""
from __future__ import annotations

import os


def _git_child_env(env=None) -> dict:
    """T-13586 — THE environment of every git child the engine spawns — the two runners in `cli.py` and,
    since T-13587, every direct launch past them (`env=git_env._git_child_env(<its env>)`): a COPY of the
    effective caller environment (`env` when one is supplied — every key of it kept, the caller's own
    mapping never written — else this process's) with git's OPTIONAL locks switched off.

    WHY. A `git status` takes the repository's index lock only to SAVE the stat data it refreshed, and
    a git WRITE that meets that lock dies `Unable to create '.git/index.lock': File exists` (T-13566:
    28 of 1200 land-tail restores under a polling reader). With the switch off the read refreshes in
    memory and answers the same; it saves nothing, so it cannot fail a concurrent write. REQUIRED locks
    are untouched: checkout, add, commit, merge and an explicit update-index lock as before. The value
    is FORCED, not defaulted — a caller's own setting must not turn an engine read back into a lock
    taker. A supplied env may key by bytes (POSIX `subprocess` accepts both spellings and does not
    de-duplicate them), so BOTH spellings of the name are dropped before the one forced entry is set —
    otherwise the child would carry the name twice and git would read the caller's value. Rule home —
    what not saving costs, and who owns an explicit refresh: SPEC-0188 rule 7."""
    child = dict(os.environ if env is None else env)
    child.pop(b"GIT_OPTIONAL_LOCKS", None)
    child["GIT_OPTIONAL_LOCKS"] = "0"
    return child
