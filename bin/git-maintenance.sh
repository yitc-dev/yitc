#!/usr/bin/env bash
# Scheduled, SERIALIZED git maintenance for the yitc-v2 kernel repo.
#
# WHY THIS EXISTS (all figures measured 2026-08-21, git 2.43.0 — analysis (b) on the card):
# auto-gc is NOT a viable cleanup policy on this repo.
# * `gc.autoDetach` defaults TRUE, and the shared `.git/gc.pid` lock is DELETED at the daemonize
# fork: polled once a second, gc.pid was held at t=1 and EMPTY at t=2..t=40 while three gc
# processes ran on. So auto-gc is structurally UNSERIALIZED across the fleet's 15 worktrees —
# the mechanism behind the 2026-08-21 concurrent-repack incident (~55GB RSS, load 60,
# deviation fingerprint `concurrent-auto-gc-overlap-on-kernel-repo`).
# * `gc.pruneExpire` defaulting to 2 weeks keeps unreachable objects alive, so every collection
# ends with «too many unreachable loose objects», that stderr becomes a `gc.log`, and a present
# gc.log SUPPRESSES auto-gc in that gitdir until it expires — the 34-day silent block of
# 2026-07-10 (E-0059) and the 2026-08-16 recurrence.
# Frequency tuning cannot break that loop; it only re-arms it sooner. This script is the collector.
#
# PRIOR-ART REUSED, not a new mechanism class (CHARTER §P1 F1): `bin/verify-backup.sh` — a v2-owned
# deterministic script on an OS cron line under `cron-notify.sh`, exit 0 = OK / exit 1 = failure,
# resolving its shared path through the ONE python site that owns it rather than re-deriving it in
# shell (the X-0663 second-source-of-truth defect).
#
# THE LOCK. This does NOT invent a maintenance lock: it takes the repo's EXISTING land reservation
# (`worktree._land_reservation_path` — the one repo-level exclusive flock). Direction is
# deliberate: MAINTENANCE YIELDS TO `land`, never the reverse. Held (a land is mid-flight, or a peer
# maintenance run is) -> the full collection defers, exit 0, the next window retries. Free -> HELD
# across the whole gc, so an arriving land parks in the existing `_await_land_reservation`.
# — A DEFERRAL IS NO LONGER A NO-OP, AND NEVER SILENT. Under back-to-back lands the reservation
# is almost never free at :25: 2026-09-28..30 every window deferred and the loose pile reached 36596
# objects / 81.9 GiB with no journal row to show it. So (1) a deferred window runs the object-SAFE
# loose-pack leg (see (b2) below — it deletes nothing, so it needs no reservation); (2) both legs take
# ONE non-blocking collection lock so they never run at once; (3) EVERY window journals
# `git_maintenance_run` with `outcome: ran|deferred|failed` + its loose count, and consecutive windows
# without a full collection surface on `bin/yitc-v2 debt` (`debt.git_maintenance_deferrals`).
# git's own `gc.pid` cannot be that lock: nothing outside git honours it, and git releases it one
# second into a run that mutates for minutes (lessons/land-critical-section-locks-every-journal-it-folds).
# NAMED RESIDUAL, sanctioned by owner decision 2026-08-22 (owner_decision_recorded):
# `_await_land_reservation` is BOUNDED — past the park limit a waiting land degrades to the optimistic
# path and proceeds anyway. Making it unbounded for a maintenance holder would reinstate the exact
# defect shipped the bound to close (an flock releases on process DEATH but not on HANG; a
# wedged reservation measured 2026-08-21 froze ALL landing repo-wide for 78 minutes with 8 branches
# queued on an idle 32-core host). So AC2 is object-SAFETY under degraded concurrency, and it holds by
# construction: `--cruft --prune=7.days` packs unreachable objects with PRESERVED mtimes and drops only
# those older than the horizon, so an object a concurrent land wrote seconds ago can never be removed.
# NEVER a bare `git prune` here — the external consult rejects it on this remote-less repo.
#
# THE TRIGGER, and the ONE WAY TO INVOKE IT WRONG. This script does not schedule itself. Its
# trigger is the hourly `25 * * * *` OS cron line `yitc-v2-git-maintenance` on the `dev` crontab, under
# `cron-notify.sh` — classified COMPLIANT in the SPEC-0142 §6 sweep register, which is where the choice
# and its reason are recorded rather than in anyone's memory.
# THE INVOCATION MUST CARRY A SESSION REF. Call this script BARE from cron and the gc works perfectly and
# the journal row is LOST: cron's env has no session carrier, so the `yitc-v2 event git_maintenance_run`
# below fails SPEC-0137 Rule 5 fail-closed with `session_ref undetermined`, and the emit WAS a WARNING that
# did NOT change the exit code — so the loss was SILENT (since it exits 1). That is what the entry did
# for its first 64 windows (2026-08-22..29), collecting real garbage on the real repo the whole time while
# the journal still showed one row from a /tmp fixture. The working form (same shape as the yitc-v2-nightly
# and yitc-v2-worktree-sweep entries) wraps the call:
# bash -c "cd <checkout> && bin/yitc-v2 session start >/dev/null && YITC_SESSION_REF=<label> bin/git-maintenance.sh"
# If you re-point, re-host or hand-copy this cadence, carry that wrapper with it.
#
# Usage: git-maintenance.sh [--repo <path>] [--emit-to <yitc-checkout>]
# --repo the repository to maintain (default: the checkout this script lives in)
# --emit-to yitc checkout whose journal receives the `git_maintenance_run` event. Default: the
# maintained repo itself when it IS a yitc checkout, otherwise NO event is emitted —
# which is what keeps fixture runs out of a live journal without any test-only knob.
# Env (probe control arms only): YITC_MAINTENANCE_NO_LOCK=1 skips the reservation entirely — the
# negative control the AC2 differentials need; never set it in production.
# YITC_MAINTENANCE_NO_INCREMENTAL=1 skips the deferred window's loose-pack leg — the control
# arm (the pre- behaviour); never set it in production.
# YITC_GC_PRUNE_EXPIRE (default 7.days), YITC_GC_LOOSE_THRESHOLD (default 256 = one gc.auto quantum).
# YITC_DISPATCH_LOG_RETENTION_DAYS (default 30) — REPORT-ONLY knob: files under
# `<repo>/.yitc/dispatch-logs` older than this are removed each run and the value is printed (# measured 958 MB / 4105 files, 1876 past 30 days, 2026-09-13, with no retention rule at all).
set -uo pipefail

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO=""
EMIT_TO=""
while [ $# -gt 0 ]; do
    case "$1" in
        --repo) REPO="$2"; shift 2;;
        --emit-to) EMIT_TO="$2"; shift 2;;
        *) echo "git-maintenance: unknown argument: $1" >&2; exit 1;;
    esac
done
[ -n "$REPO" ] || REPO="$SCRIPT_ROOT"

SCRIPT_ROOT="$SCRIPT_ROOT" REPO="$REPO" EMIT_TO="$EMIT_TO" python3 - <<'PY'
import json, os, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, os.path.join(os.environ["SCRIPT_ROOT"], "bin"))

REPO = os.environ["REPO"]
EMIT_TO = os.environ["EMIT_TO"]
PRUNE = os.environ.get("YITC_GC_PRUNE_EXPIRE", "7.days")
THRESHOLD = int(os.environ.get("YITC_GC_LOOSE_THRESHOLD", "256"))
NO_LOCK = os.environ.get("YITC_MAINTENANCE_NO_LOCK") == "1"
DISPATCH_LOG_DAYS = int(os.environ.get("YITC_DISPATCH_LOG_RETENTION_DAYS", "30"))


def git(*args, cwd=REPO):
    return subprocess.run(("git") + args, cwd=cwd, capture_output=True, text=True)


def fail(msg):
    print("git-maintenance: %s" % msg)
    sys.exit(1)


# ── (a) resolve the repo from ANY worktree ────────────────────────────────────────────────────
# gc.pid resolves to the COMMON dir while gc.log resolves PER-WORKTREE (measured: 1 gc.pid, 12
# gc.logs), so every path below is derived explicitly rather than assumed to be `<repo>/.git`.
r = git("rev-parse", "--path-format=absolute", "--git-common-dir")
if r.returncode != 0:
    fail("not a git repository: %s (%s)" % (REPO, r.stderr.strip))
common = Path(r.stdout.strip)
main_wt = common.parent

# ── (a2) dispatch-log retention — plain files, no git objects, so it needs no lock ────────
dispatch_logs = main_wt / ".yitc" / "dispatch-logs"
horizon = time.time - DISPATCH_LOG_DAYS * 86400
pruned = 0
pruned_bytes = 0
if dispatch_logs.is_dir:
    for f in dispatch_logs.rglob("*"):
        try:
            st = f.lstat
            if f.is_file and not f.is_symlink and st.st_mtime < horizon:
                f.unlink
                pruned += 1
                pruned_bytes += st.st_size
        except OSError:
            pass
print("git-maintenance: dispatch-log retention=%d days (report-only knob YITC_DISPATCH_LOG_RETENTION_DAYS)"
      " — pruned %d file(s) / %.1f MiB from %s"
      % (DISPATCH_LOG_DAYS, pruned, pruned_bytes / 1048576.0, dispatch_logs))


def gitdirs:
    """The common dir plus every per-worktree gitdir — the complete set of places a gc.log can live."""
    dirs = [common]
    wt_root = common / "worktrees"
    if wt_root.is_dir:
        dirs.extend(sorted(p for p in wt_root.iterdir if p.is_dir))
    return dirs


def gc_logs:
    return [d / "gc.log" for d in gitdirs if (d / "gc.log").exists]


def loose_state:
    """Loose object count + bytes by walking objects/??/ directly — no git subprocess, so the
    measurement cannot itself trip an auto-gc while we are measuring."""
    count = 0
    size = 0
    objects = common / "objects"
    if objects.is_dir:
        for d in objects.iterdir:
            if not (d.is_dir and len(d.name) == 2):
                continue
            try:
                int(d.name, 16)
            except ValueError:
                continue
            for f in d.iterdir:
                if f.is_file:
                    count += 1
                    try:
                        size += f.stat.st_size
                    except OSError:
                        pass
    return count, size


def pack_state:
    packs = sorted((common / "objects" / "pack").glob("*.pack")) if (common / "objects" / "pack").is_dir else []
    return len(packs), sum(p.stat.st_size for p in packs)


def loose_shas:
    """Every loose object's sha — the same objects/??/ walk `loose_state` does, so the pack leg
    covers exactly the pile that measurement reports (reachable AND unreachable alike)."""
    shas = []
    objects = common / "objects"
    if objects.is_dir:
        for d in objects.iterdir:
            if not (d.is_dir and len(d.name) == 2):
                continue
            try:
                int(d.name, 16)
            except ValueError:
                continue
            for f in d.iterdir:
                if f.is_file and len(f.name) == 38:
                    shas.append(d.name + f.name)
    return shas


def emit(payload):
    """Journal ONE `git_maintenance_run` row for this window (skipped for a fixture repo, with no
    test-only knob). : EVERY window emits — ran, deferred or failed — so a starvation is read
    off the journal instead of discovered, and an emit failure EXITS 1 (cron-notify surfaces it):
    the silent-loss shape was exactly a warning with exit 0."""
    emit_to = EMIT_TO or (str(main_wt) if (main_wt / "events.jsonl").exists
                          and (main_wt / "bin" / "yitc-v2").exists else "")
    if not emit_to:
        return
    e = subprocess.run([str(Path(emit_to) / "bin" / "yitc-v2"), "-C", emit_to, "event",
                        "git_maintenance_run", "--task", "",
                        "--data", json.dumps(payload)],
                       capture_output=True, text=True)
    if e.returncode != 0:
        fail("could not journal git_maintenance_run (%s): %s" % (payload.get("outcome"), e.stderr.strip))
    print("git-maintenance: git_maintenance_run (%s) journalled to %s" % (payload.get("outcome"), emit_to))


def try_flock(path):
    """A NON-BLOCKING exclusive flock on `path` -> its fd, or None when held. Never waits."""
    fd = lockfile.open_flock_target(path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        os.close(fd)
        return None


def state(count_size):
    return {"loose_objects": count_size[0], "loose_bytes": count_size[1]}


# ── (b) THE LOCKS ─────────────────────────────────────────────────────────────────────────────
# RESERVATION: the repo's existing land reservation, taken NON-BLOCKING — it decides WHICH leg runs.
# COLLECTION LOCK : ONE non-blocking flock both legs take, so the unlocked loose-pack leg and
# a full gc can never run at once (audit-pre fp1:c9fd6233e34b9d16 — a gc.pid check would be a
# time-of-check race against a full run starting a moment later). Neither lock is ever WAITED on, so
# maintenance never parks a land.
import fcntl
from lib import lockfile, worktree
COLLECT_LOCK = common / "yitc-git-maintenance.lock"
lock_fd = None
collect_fd = None
defer_reason = None
if not NO_LOCK:
    target = worktree._land_reservation_path(main_wt)
    lock_fd = try_flock(target)
    if lock_fd is None:
        defer_reason = "land reservation HELD (%s)" % target
    else:
        collect_fd = try_flock(COLLECT_LOCK)
        if collect_fd is None:
            os.close(lock_fd)
            lock_fd = None
            defer_reason = "collection lock HELD (%s) — a loose-pack leg is mid-flight" % COLLECT_LOCK

if defer_reason is not None:
    # ── (b2) THE DEFERRED WINDOW — the loose-pack leg, OUTSIDE the reservation ────────
    # Before a held reservation was a pure no-op, and under back-to-back lands the
    # reservation is almost never free at :25 — 2026-09-28..30 deferred every window and the loose
    # pile reached 36596 objects / 81.9 GiB. So a deferred window still packs EVERY loose object
    # (reachable and unreachable) into a new ORDINARY pack, then `git prune-packed`. That deletes NO
    # object and NO pack — prune-packed removes only a loose copy whose bytes are now in a pack — so
    # it is safe beside a running land, and nothing unreachable can die earlier than under :
    # the next `gc --cruft` dates an object in an ordinary pack by that pack's mtime, which only
    # LENGTHENS its life. Memory is bounded (4 threads x 256m window) on a host that swaps under load.
    # The full cruft/prune collection still runs ONLY under the reservation.
    print("git-maintenance: %s — deferring the full collection; the next window retries." % defer_reason)
    before = loose_state
    leg = {"ran": False}
    failure = None
    if os.environ.get("YITC_MAINTENANCE_NO_INCREMENTAL") == "1":
        leg["skipped"] = "YITC_MAINTENANCE_NO_INCREMENTAL (control arm)"
    else:
        cfd = None if NO_LOCK else try_flock(COLLECT_LOCK)
        if not NO_LOCK and cfd is None:
            leg["skipped"] = "collection lock held — a peer collection is running"
        else:
            try:
                shas = loose_shas
                started = time.time
                if shas:
                    r = subprocess.run(["git", "-c", "pack.threads=4", "pack-objects", "-q",
                                        "--window-memory=256m",
                                        str(common / "objects" / "pack" / "pack")],
                                       cwd=REPO, input="\n".join(shas) + "\n",
                                       capture_output=True, text=True)
                    if r.returncode != 0:
                        failure = "git pack-objects FAILED (rc=%d): %s" % (r.returncode, r.stderr.strip)
                    else:
                        r = git("prune-packed")
                        if r.returncode != 0:
                            failure = "git prune-packed FAILED (rc=%d): %s" % (r.returncode, r.stderr.strip)
                leg.update({"ran": failure is None, "packed": len(shas),
                            "seconds": round(time.time - started, 1)})
            finally:
                if cfd is not None:
                    os.close(cfd)
    after = loose_state
    print("git-maintenance: loose-pack leg %s — loose %d -> %d objects (%.1f -> %.1f MiB)"
          % ("ran" if leg["ran"] else ("FAILED" if failure else "skipped (%s)" % leg.get("skipped")),
             before[0], after[0], before[1] / 1048576.0, after[1] / 1048576.0))
    payload = {"repo": str(main_wt), "outcome": "failed" if failure else "deferred",
               "reason": defer_reason, "loose_threshold": THRESHOLD,
               "loose_objects": after[0], "loose_bytes": after[1],
               "before": state(before), "loose_pack": leg}
    if failure:
        payload["error"] = failure
    emit(payload)
    if failure:
        fail(failure)
    print("git-maintenance: DEFERRED")
    sys.exit(0)

try:
    # ── (c) BEFORE state ──────────────────────────────────────────────────────────────────────
    before_count, before_size = loose_state
    before_packs, before_pack_size = pack_state
    before_logs = [str(p) for p in gc_logs]
    print("git-maintenance: repo=%s" % main_wt)
    print("git-maintenance: before loose=%d objects / %.1f MiB, packs=%d / %.1f MiB, gc.log files=%d"
          % (before_count, before_size / 1048576.0, before_packs,
             before_pack_size / 1048576.0, len(before_logs)))

    # ── (d) THE COLLECTION — foreground, so the lock spans the whole run ───────────────────────
    started = time.time
    r = git("-c", "gc.autoDetach=false", "gc", "--cruft", "--prune=%s" % PRUNE)
    elapsed = time.time - started
    if r.returncode != 0:
        # gc.log files are left in place on failure — they are the evidence.
        print(r.stdout)
        print(r.stderr)
        msg = "git gc FAILED (rc=%d) after %.1fs — gc.log left in place as evidence" % (r.returncode, elapsed)
        now = loose_state
        emit({"repo": str(main_wt), "outcome": "failed", "error": msg, "loose_threshold": THRESHOLD,
              "loose_objects": now[0], "loose_bytes": now[1],
              "before": state((before_count, before_size))})
        fail(msg)
    print("git-maintenance: git gc --cruft --prune=%s completed in %.1fs" % (PRUNE, elapsed))

    # ── (e) clear gc.log in EVERY gitdir, on success ONLY ──────────────────────────────────────
    cleared = []
    for log in gc_logs:
        try:
            log.unlink
            cleared.append(str(log))
        except OSError as exc:
            fail("could not remove %s: %s" % (log, exc))
    if cleared:
        print("git-maintenance: cleared %d gc.log file(s)" % len(cleared))

    # ── (f) EFFICACY, carried by the exit code ────────────────────────────────────────────────
    after_count, after_size = loose_state
    after_packs, after_pack_size = pack_state
    remaining = [str(p) for p in gc_logs]
    print("git-maintenance: after loose=%d objects / %.1f MiB, packs=%d / %.1f MiB, gc.log files=%d"
          % (after_count, after_size / 1048576.0, after_packs,
             after_pack_size / 1048576.0, len(remaining)))

    payload = {
        "repo": str(main_wt),
        "outcome": "ran",
        "prune_expire": PRUNE,
        "loose_threshold": THRESHOLD,
        "loose_objects": after_count,
        "gc_seconds": round(elapsed, 1),
        "before": {"loose_objects": before_count, "loose_bytes": before_size,
                   "packs": before_packs, "pack_bytes": before_pack_size,
                   "gc_log_files": before_logs},
        "after": {"loose_objects": after_count, "loose_bytes": after_size,
                  "packs": after_packs, "pack_bytes": after_pack_size,
                  "gc_log_files": remaining},
        "gc_logs_cleared": cleared,
        "serialized_by": ("none (YITC_MAINTENANCE_NO_LOCK)" if NO_LOCK
                          else "land-reservation flock + collection lock"),
    }

    problems = []
    if after_count >= THRESHOLD:
        problems.append("loose objects %d >= threshold %d — the repo still demands a collection"
                        % (after_count, THRESHOLD))
    if remaining:
        problems.append("gc.log still present in %d gitdir(s): %s" % (len(remaining), ", ".join(remaining)))
    payload["efficacy"] = "met" if not problems else "not-met"

    # ── the journal trace (skipped for a fixture repo, with no test-only knob) ─────────────────
    emit(payload)

    if problems:
        for p in problems:
            print("git-maintenance: EFFICACY NOT MET — %s" % p)
        sys.exit(1)
    print("git-maintenance: OK — loose %d -> %d, no gc.log in any gitdir" % (before_count, after_count))
finally:
    for fd in (collect_fd, lock_fd):
        if fd is not None:
            os.close(fd)
PY
