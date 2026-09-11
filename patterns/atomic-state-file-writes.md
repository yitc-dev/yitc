---
name: atomic-state-file-writes
class: technique
sourced_from: <host-home>/knowledge/patterns/atomic-state-file-writes.md
applies_to: any state file (settings, lock, cursor, audit YAML) read by other code; mandatory for files where a partial/empty write breaks downstream consumers
---

# Atomic State-File Writes

## Problem

`open(path, "w")` **truncates** the file at open. If the process dies between open and write completion (SIGTERM on terminal close, OOM-killer, short hook timeout, SIGPIPE) the file is left **empty or partial**. The next reader picks up garbage.

Risk classes:
- **Global settings** — a partial write breaks all sessions
- **Audit trails** (closed-findings, events.jsonl) — history disappears; findings re-surface as «regressions»
- **Lock files** — empty lock = «unknown holder» = false-positive blocking
- **Cursor files** (probe state, watermark markers) — re-processed or skipped data

## Solution

Write to a sibling tempfile in the **same directory**, fsync, then `os.replace(tmp, dst)`. POSIX guarantees `os.replace` atomicity within one filesystem. Crash before replace → tempfile is an orphan (cleaned in except), original file untouched.

## Example

**Python helper:**

```python
import os, tempfile
from pathlib import Path

def write_text_atomic(path, content):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp hardcodes 0600 and os.replace PRESERVES the tmp file's mode — so without an explicit
    # chmod every atomic write lands owner-only, invisible to a group-read collaborator. Restore the
    # intended mode: preserve a pre-existing target's mode (a deliberately-private file stays private),
    # else the umask-respecting default for a new file.
    try:
        existing_mode = os.stat(p).st_mode & 0o777
    except FileNotFoundError:
        existing_mode = None
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush
            os.fsync(f.fileno)
        if existing_mode is not None:
            os.chmod(tmp, existing_mode) # rewrite: keep the target's own mode
        else:
            cur = os.umask(0); os.umask(cur) # new file: umask-respecting default
            os.chmod(tmp, 0o666 & ~cur)
        os.replace(tmp, p) # chmod BEFORE replace → atomicity unchanged
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise
```

Key points:
- `.` prefix on tempfile — hidden from `ls`, won't match accidental globs
- Tempfile in **same directory** as target — `os.replace` across filesystem boundaries is not atomic
- `fsync` before replace — guards against power loss for critical files
- Cleanup in `except` — no orphaned `.target.XXXXXX.tmp` files
- **Restore the mode** — `mkstemp` creates 0600 and `os.replace` preserves it, so a naive atomic
  writer silently makes every state file owner-only (: `-C init` scaffolds became unreadable to
  a scoped group-dev collaborator in bc-community). Preserve an existing target's mode on rewrite; apply
  the umask-default for a new file. Chmod the tmp fd BEFORE `os.replace` so atomicity is unaffected.

**Bash equivalent:**

```bash
TMP=$(mktemp "${TARGET}.XXXXXX") || exit 0
trap 'rm -f "$TMP"' EXIT
if command_that_generates_content > "$TMP"; then
    mv -f "$TMP" "$TARGET"
    trap - EXIT
fi
```

## Anti-pattern

- `with open(path, "w")` — truncates at open; partial write on crash
- `path.write_text` — same problem under the hood
- `json.dump(data, open(path, "w"))` — leaks fd on error + partial file
- Tempfile in `/tmp` — cross-filesystem; `os.replace` falls back to copy+unlink with no atomicity guarantee
- Forgetting cleanup in `except` — orphaned tempfiles accumulate in the target directory
- **Forgetting to restore the mode** — leaving the mkstemp 0600 in place ships owner-only state files (a scoped collaborator gets «Permission denied»)

## When NOT to apply

- Append-only logs (events.jsonl, hook logs) — `O_APPEND` does not truncate; partial-write problem doesn't exist
- Temp files only written + read by one author
- Deterministic + cheap-to-regenerate files (just rebuild on crash)

## Combine with flock

Atomic-write protects against **crash mid-write**. It does NOT protect against **concurrent overwrite** (two writers racing). If serialization is needed:

```python
with open(f"{path}.lock", "a") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    data = load(path)
    data.update
    write_yaml_atomic(path, data)
```

Flock and atomic-write are orthogonal: flock = ordering, atomic = single-write integrity.

## Cites

- v1 incident sources: B-278 (first application — session-autolock 5s timeout truncated lock file silently), B-310 (propagation to 4 additional writers)
- Related: append-only-journals (e.g. `events.jsonl`), file-locking patterns
