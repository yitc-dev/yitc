#!/usr/bin/env bash
# Backup + recovery round-trip verification for the SHARED coordination store (SPEC-0084 rule 3 / VP7).
#
# The shared coordination store (CROSS_LOG_PATH) is canonical coordination SoT — NOT a reconstructable
# cache (SPEC-0084 rule 1). So it must have working backup + a recovery path that round-trips the fold:
# STATE: a backup of the store exists (a timestamped snapshot is produced + retained).
# ROUND-TRIP: restoring the backup reproduces the identical status-fold.
#
# Backup posture (SPEC-0084 r3 "rides the existing server backup"): the store's canonical home
# lives UNDER <host-home>/, which <host-home>/bin/offsite-backup.sh §3 already
# rsyncs offsite every 4h — so the store is ALREADY backed up offsite without touching that host
# script (external read-only territory). This script ADDS a local, verifiable snapshot (the
# recovery source + the deterministic state-check) that rides the SAME offsite rsync.
#
# Prior-art reused (no new mechanism — CHARTER P1): the jsonl-file snapshot + restore-and-verify +
# nonzero-exit-on-failure pattern of <host-home>/bin/verify-backup.sh (host, pg dumps); and the EXISTING
# cross.fold/read_events (bin/lib/cross.py) for the fold — the SAME parser the journal uses
# (SPEC-0084 r4 one-parser contract), imported READ-ONLY. No `cross` verb: backup/restore here is ops
# infrastructure, not a governed protocol write.
#
# Exit 0 = OK (or pre-cutover no-store skip); exit 1 = failure (cron-notify pattern).
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The store path comes from the ONE resolution site — `cross.resolve_log_path`, which this
# script can reach because bin/ is already on sys.path for its heredoc below. A literal default here
# would be a second source of truth for "where the store lives", and a per-$HOME one would point this
# verifier at the invoking user's own empty store instead of the shared instance (X-0663).
STORE="$(REPO_ROOT="$REPO_ROOT" python3 - <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.environ["REPO_ROOT"], "bin"))
from lib import cross
print(cross.resolve_log_path)
PY
)"
BACKUP_DIR="${YITC_CROSS_BACKUP_DIR:-$(dirname "$STORE")/backups}"
RETAIN="${YITC_CROSS_BACKUP_RETAIN:-42}" # 7d × 6/day, matching offsite-backup.sh pg rotation

if [ ! -f "$STORE" ]; then
    echo "ℹ️ no coordination store at $STORE — nothing to back up yet (pre-cutover); skipping."
    exit 0
fi
mkdir -p "$BACKUP_DIR"

# Lock-safe snapshot + restore round-trip, delegated to python so it can (a) hold the SAME advisory
# flock the writers use (events.py LOCK_EX) → no torn-tail snapshot, and (b) reuse cross.fold.
OUT="$(REPO_ROOT="$REPO_ROOT" STORE="$STORE" BACKUP_DIR="$BACKUP_DIR" python3 - <<'PY'
import os, sys, json, fcntl, time, tempfile
sys.path.insert(0, os.path.join(os.environ["REPO_ROOT"], "bin"))
from lib import cross

store = os.environ["STORE"]
backup_dir = os.environ["BACKUP_DIR"]

# 1. Atomic snapshot: read the whole store under a SHARED flock on its own fd. Writers append complete
# lines under LOCK_EX (events.py), so a LOCK_SH read never observes a partial trailing line (the
# torn-backup hazard) — the snapshot is a clean, complete-line prefix.
with open(store, "rb") as fh:
    fcntl.flock(fh.fileno, fcntl.LOCK_SH)
    try:
        data = fh.read
    finally:
        fcntl.flock(fh.fileno, fcntl.LOCK_UN)

# 2. Write the backup atomically (tmp + os.replace). Collision-resistant name: ts + nanoseconds + pid,
# so two invocations in the same second cannot collide / rotate the wrong artifact.
stamp = time.strftime("%Y-%m-%d_%H-%M-%S") + "_%06d_%d" % (time.time_ns % 1_000_000, os.getpid)
backup = os.path.join(backup_dir, "coordination_%s.jsonl" % stamp)
fd, tmp = tempfile.mkstemp(dir=backup_dir, prefix=".bk-")
try:
    with os.fdopen(fd, "wb") as out:
        out.write(data)
        out.flush
        os.fsync(out.fileno)
    os.replace(tmp, backup)
except BaseException:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise

# STATE-CHECK: the snapshot exists.
if not os.path.exists(backup):
    print("ERROR backup snapshot was not created")
    sys.exit(1)

# 3. ROUND-TRIP: RESTORE the backup into a fresh location (a disaster-recovery simulation) and verify
# the recovered store yields the IDENTICAL status-fold as the backup. The fold is the canonical
# per-id status (cross.fold), order-independent + dedup'd — so a faithful restore round-trips it.
def fold_of(path):
    items = cross.fold(cross.read_events(path))
    return {iid: {k: it.get(k) for k in ("status", "kind", "from", "to", "contested")}
            for iid, it in sorted(items.items)}

restored = os.path.join(backup_dir, ".restore-probe-%d.jsonl" % os.getpid)
try:
    with open(backup, "rb") as b, open(restored, "wb") as r:
        r.write(b.read)
    fold_backup = fold_of(backup)
    fold_restored = fold_of(restored)
finally:
    try:
        os.unlink(restored)
    except OSError:
        pass

if fold_backup != fold_restored:
    print("ERROR round-trip MISMATCH: restored fold != backup fold")
    print("backup: " + json.dumps(fold_backup, sort_keys=True, ensure_ascii=False))
    print("restored: " + json.dumps(fold_restored, sort_keys=True, ensure_ascii=False))
    sys.exit(1)

print("BACKUP=%s" % backup)
print("ITEMS=%d" % len(fold_backup))
PY
)"
rc=$?

if [ "$rc" -ne 0 ]; then
    echo "$OUT"
    echo "❌ [$(date)] verify-backup FAILED for $STORE"
    exit 1
fi

backup_path="$(printf '%s\n' "$OUT" | sed -n 's/^BACKUP=//p')"
items="$(printf '%s\n' "$OUT" | sed -n 's/^ITEMS=//p')"
echo "✅ backup exists: $backup_path"
echo "✅ round-trip OK: restored fold == backup fold (${items:-0} coordination items)"

# Rotation: keep the last $RETAIN snapshots (same idiom as offsite-backup.sh §7).
ls -t "$BACKUP_DIR"/coordination_*.jsonl 2>/dev/null | tail -n +$((RETAIN + 1)) | xargs -r rm -f

echo "[$(date)] verify-backup OK"
exit 0
