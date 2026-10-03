"""Lock-file open primitive for the yitc-v2 CLI — the ONE way to open an flock target.

Every advisory lock in this codebase coordinates on a file that is a **flock target ONLY**: nothing
ever writes bytes into it (an id counter lives in a sibling `<prefix>.max`, a journal's data lives in
the journal itself). Such a file must be opened WITHOUT `O_TRUNC` and WITHOUT demanding WRITE
permission — which is exactly what `open(path, "w")` does wrong, on two counts:

  1. `O_TRUNC` truncates the very file concurrent holders coordinate on, at open, BEFORE any flock
     is taken.
  2. `O_WRONLY` needs WRITE permission, so a second group-dev user opening a peer-owned 0644 lock
     file dies with `EACCES` *before* it can block on the lock. (`/tmp` is sticky and under
     `fs.protected_regular=2`, which additionally blocks an `O_CREAT` open of another user's
     existing regular file.) That is the **X-0226** class.

Identity-agnostic KERNEL leaf (SPEC-0073 `bin/` HARD class — travels with the engine). Stdlib-only
and imports no other `lib` module, so any module may import it without a cycle.

Provenance — this helper is NOT new mechanism. `journal_lock` (T-10189, X-0226) invented the idiom
for the journal sidecar; T-10250 hoisted it into a private `_open_flock_target` inside `bin/yitc-v2`
for `_id_alloc_lock` + `_with_repo_lock`. That private address was unreachable from `bin/lib/*` (the
dependency runs the other way), which is precisely how four more sites re-introduced `open(p, "w")`.
T-10336 relocated the ONE helper here — same body, reachable by every caller — so a fifth site
cannot re-introduce the bug. It is homed in its own leaf rather than in `events.py` because that
module is the single journal-WRITE path (SPEC-0091 route-by-purpose): a lock-file open is a
different purpose.
"""
from __future__ import annotations

import os
from pathlib import Path


def open_flock_target(path: "Path | str") -> int:
    """Open `path` as a pure flock target and return its fd — never truncating, cross-user safe.

    CREATE-if-first via `O_CREAT|O_EXCL` (forcing 0644 with `fchmod` so a restrictive umask cannot
    leave it unreadable to a peer); on `FileExistsError` (a peer created it) or `PermissionError`
    (it is the peer's file and we may not write it) fall back to a plain `O_RDONLY` open with NO
    `O_CREAT`. `flock(LOCK_EX)` holds on a read-only fd, so the shared-inode serialization every
    caller relies on is unchanged.

    The caller owns the fd: take the flock, then `os.close(fd)` in a `finally` (that releases the
    advisory lock). Not safe over NFS.
    """
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
        os.fchmod(fd, 0o644)   # defeat a restrictive umask — a peer MUST be able to open it
    except (FileExistsError, PermissionError):
        fd = os.open(str(path), os.O_RDONLY)
    return fd
