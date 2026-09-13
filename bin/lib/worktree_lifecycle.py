"""worktree_lifecycle — the WORKTREE-LIFECYCLE verbs and their exclusive mechanism, extracted
byte-identical from `bin/lib/worktree.py` (T-11522, plan
`split-worktree-py-along-its-own-spec-seams-runner-`).

WHAT IS IN HERE, AND WHY THE BOUNDARY IS THE ONE IT IS. The move-set is the TRANSITIVE-EXCLUSIVE
closure rooted at this subject's OWN entry points — the six worktree-lifecycle verbs
`cmd_worktree_new` / `adopt` / `park` / `sweep` / `sync` / `recover_land` — where a helper moves iff
EVERY top-level caller of it is already in the move-set. Rooting at the subject rather than at a
borrowed discriminator is the expensive lesson of the runner cut that preceded this one
(`lessons/library-extraction.md` §"Root the closure at the SUBJECT's own entry point"); requiring
exclusivity is what leaves the land path's shared helpers — `_scan_procs`, `_proc_start_age_sec`,
`_main_checkout_state_note` and the rest of `cmd_land`'s tree — in the host BY CONSTRUCTION, rather
than by an exclusion list someone has to remember to write.

NOT IN HERE, and each falls out of that same construction rather than by a judgement: `cmd_land` and
its batch-landing tree (SPEC-0184), the rebaseline/audit-currency block (SPEC-0077), evidence custody
(SPEC-0168), and `cmd_blocked_on_land` — the worker's POST-claim escalation, which is a land-seam
verb, not a worktree-lifecycle one.

SEAM (the T-9340 / T-9341 / T-11519 full inject-residue shape, `lessons/library-extraction.md`
§AST-freeze generator): bodies and signatures are spliced VERBATIM from the original source — never
`ast.unparse` — and every non-stdlib free name (host stayers, host globals, AND moved siblings via
their host residue) arrives as a keyword-only injected parameter, computed with `symtable` over each
function's scope SUBTREE. A defaulted parameter whose default NAMED a host symbol carries `None` here
and is re-supplied by the host residue at call time, so the value bound is the same host object it
was before the move. The host keeps a residue under every historical name, so the tests and the eight
`bin/lib` modules that reach these symbols through `worktree.<sym>` keep resolving and stay out of
this diff.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports only stdlib; it NEVER
back-imports the host.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants moved WITH their readers: each is referenced from a moved signature DEFAULT, which is
# evaluated at def time in THIS module, so it cannot arrive by injection. The host keeps a re-export
# alias under each historical name, which also preserves the `is`-sentinel identity of
# `_DERIVE_WT_PARENT` (`cmd_worktree_sweep` compares against it with `is`).
# ---------------------------------------------------------------------------
_DERIVE_WT_PARENT = object()
_SANDBOX_PREFIX_GLOB = "/tmp/yitc-verify-sandbox-*"


def _self_proc_ancestry(pid: "int | None" = None) -> "set[int]":
    """THIS process plus its ancestor chain (T-10885) — so a holder READ never counts the reader.

    The verbs below ask "does a LIVE process hold this worktree path?" while THEY may themselves be
    running from inside it (a worker parking its own worktree, a shell that `cd`-ed in). Excluding
    only `os.getpid()` is not enough: the invoking SHELL — this process's parent — carries the same
    cwd and would answer the question with the asker. Walks `/proc/<pid>/status` PPid to pid 1;
    an unreadable entry simply ends the walk (best-effort, and the narrow direction: a shorter
    ancestry can only ever make the guard MORE likely to refuse, never less)."""
    seen: "set[int]" = set()
    cur = os.getpid() if pid is None else int(pid)
    while cur and cur not in seen:
        seen.add(cur)
        try:
            txt = Path(f"/proc/{cur}/status").read_text(encoding="utf-8", errors="replace")
        except OSError:
            break
        m = re.search(r"^PPid:\s*(\d+)", txt, re.M)
        if not m:
            break
        cur = int(m.group(1))
    return seen



def _live_path_holders(path, *, _ancestry=None, _self_proc_ancestry=None) -> "list[dict]":
    """LIVE processes whose working directory IS `path`, or lies UNDER it (T-10885). `[{pid, cwd}]`.

    THE INCIDENT THIS READS FOR (2026-08-10, T-10826): a worktree was torn down and RECREATED at the
    same path while the session holding it was still alive, resetting its tracked files and destroying
    its untracked audit records permanently. Liveness here is a READ of evidence that ALREADY exists
    (`/proc/<pid>/cwd`, the same signal `_live_held_paths` uses to spare a running verify's sandbox) —
    NOT a lease, TTL, registry or FSM (CHARTER §P1: the smallest edit is a new read, not a new store).

    THE `(deleted)` FORM IS LOAD-BEARING, not an edge case. When a worktree is `git worktree
    remove --force`d out from under a live holder, the kernel renders that holder's cwd link as
    `<path> (deleted)` — which is precisely the window in which a recreate destroys work. Matching
    only the plain form would blind the guard to the exact sequence it exists to stop.

    PRECISION over breadth (the `_sandbox_prefix_arg` positive-discriminator posture): ONLY the cwd
    link is read — never argv, never env. A dispatched worker carries its whole preamble, naming many
    paths, as ONE argv element, so a substring scan over argv false-positives on any booting worker
    (the T-10053 footgun). A cwd is an unambiguous, per-process fact.

    FAIL-OPEN by construction, and deliberately so: no `/proc` (non-Linux) or an unreadable entry
    yields NO holder, so the guard simply does not fire and the pre-existing gates (branch-existence,
    own-stamp, card-status) still govern. This read only ever ADDS a refusal; it never removes one."""
    p = str(path).rstrip(os.sep)
    if not p:
        return []
    skip = _ancestry if _ancestry is not None else _self_proc_ancestry()
    holders: "list[dict]" = []
    try:
        pids = [d for d in os.listdir("/proc") if d.isdigit()]
    except OSError:
        return []
    for pid in pids:
        if int(pid) in skip:
            continue
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            continue   # per-pid race / permission — contributes nothing, never a global failure.
        # The kernel appends " (deleted)" to an unlinked target; strip it and keep the fact.
        deleted = cwd.endswith(" (deleted)")
        real = cwd[: -len(" (deleted)")] if deleted else cwd
        if real == p or real.startswith(p + os.sep):
            holders.append({"pid": int(pid), "cwd": real, "deleted": deleted})
    return holders



_REAP_TERM_WAIT_S = 5.0          # SIGTERM -> bounded wait -> SIGKILL; the escalation window per pid.

# The ONLY pid outcomes that mean the holder is GONE. `_reap_holders` classifies against THIS set, so an
# outcome absent from it — `survived-SIGKILL`, either `SIG*-failed`, or anything added later — counts as
# a failed reap and REFUSES the teardown (audit-post finding fp1:d899c6b7db3ea2f2). Positive by
# construction: a failure-matching list would fail OPEN on the case nobody anticipated.
_REAP_SUCCESS_OUTCOMES = ("terminated", "killed", "already-gone")
_REAP_DOCKER_STOP_TIMEOUT_S = 30  # the wall this verb gives `docker stop` itself (it has its own -t grace).


def _docker_cwd_holders(path, *, _run=None, client_held: bool = False, _readlink=None) -> "tuple[list, str | None]":
    """CONTAINERS whose OWN WORKING DIRECTORY is `path` or lies under it. `([{container, name, workdir}],
    error)`.

    THE CONTAINER ANALOG OF `_live_path_holders`, AND DELIBERATELY NOT A MOUNT SCAN. X-1350 (aiseller,
    2026-09-09) left two `docker run` land-verify containers holding a dead worker's worktree at 18:05;
    the pid `_live_path_holders` sees there is the docker CLIENT, and killing it leaves the container
    running — so the container needs its own id to be torn down. But a container that merely MOUNTS the
    worktree while working elsewhere is NOT a holder, and stopping it would tear down something this
    verb was never asked about (the audit-pre finding fp1:7ae318458932e95b on this card's own plan).
    So the qualifying question is the SAME one asked of a process: is your working directory inside
    this worktree? Answered off the container's RUNTIME cwd, never its configured one: take
    `State.Pid` — the container's init process as the HOST numbers it — and read `/proc/<pid>/cwd`
    (`_container_runtime_cwd`), the same per-process kernel fact `_live_path_holders` reads for every
    other holder. `Config.WorkingDir` is NOT consulted (audit-pre fp1:2e290f19277b56f2): it records
    where the container was TOLD to start, and the process may have `chdir`ed in either direction
    since — into the worktree (a holder the configured read misses: the X-1350 shape) or out of it (a
    non-holder it would have us stop). The runtime link is resolved by `_container_cwd_host_path`: a
    host path already under `path` qualifies directly; a container-namespace path is mapped back
    through the mount whose `Destination` is its longest prefix and must land on `path` or under it.
    A runtime cwd under no mount is container-private and cannot be this worktree; one that maps
    outside is not a holder. (The runtime-CWD differential tests hold both drift directions.)

    THE TWO FAILURE DIRECTIONS ARE DIFFERENT, and that asymmetry is the whole point of returning an
    error separately from the list. NO DOCKER BINARY is not a failure — a host without docker has no
    containers to find, so the answer is an honest empty. Any docker call that RUNS AND FAILS, or an
    inspect payload that cannot be resolved, IS an error: the container question went unanswered, and
    the caller must refuse rather than reap the pids and leave a container holding the path (a
    half-teardown reads as a completed one, which is the failure mode this whole card exists to end).
    `client_held` IS THE THIRD LEG, and it is the one a mount scan structurally cannot see. It says
    "a docker CLIENT process holds this worktree as its cwd" (computed by `_docker_client_holders` off
    the SAME holder list the reap is about to signal). An UNRESOLVABLE container is unanswered when
    EITHER it mounts this worktree OR that is true: a `docker run` whose mounts this read cannot resolve
    still leaves its client pid in the holder list, so calling it "not a holder" reaps the client while
    the container keeps running — the X-1350 shape by a second route (the ceiling-round residual on
    fp1:5611c4257bc4b9e3). The attribution is WORKTREE-WIDE, not per-container, and deliberately so: a
    client's argv does not reliably name the container id, so while a docker client holds this worktree
    EVERY unresolvable container is unanswered. That is narrow — it fires only on unresolvable
    containers, only while a client holds this path — and it fails in the refusing direction.

    READ-ONLY: it never stops anything — `_reap_holders` does, and only on a proven-dead holder."""
    run = _run if _run is not None else _docker_run
    p = str(path).rstrip(os.sep)
    if not p:
        return [], None
    ids, err = run(["ps", "-q"])
    if err == "docker-absent":
        return [], None            # no docker on this host — nothing to find, not a failure.
    if err:
        return [], f"`docker ps -q` failed: {err}"
    cids = [c.strip() for c in (ids or "").splitlines() if c.strip()]
    if not cids:
        return [], None
    raw, err = run(["inspect", *cids])
    if err:
        return [], f"`docker inspect` failed: {err}"
    try:
        payload = json.loads(raw or "[]")
    except (ValueError, TypeError) as e:
        return [], f"`docker inspect` output was not JSON ({e})"
    if not isinstance(payload, list):
        return [], "`docker inspect` output was not a JSON list"
    found = []
    for c in payload:
        if not isinstance(c, dict):
            return [], "`docker inspect` returned a non-object container entry"
        cid = c.get("Id") or ""
        host, resolvable = _container_cwd_host_path(c, p, _readlink=_readlink)
        if not resolvable and (client_held or _container_touches(c, p)):
            # UNRESOLVED, AND IT TOUCHES THIS WORKTREE -> an ERROR, never a quiet "not a holder"
            # (audit-pre finding fp1:5611c4257bc4b9e3). This is the half that matters: a container we
            # cannot judge, which nonetheless has this worktree mounted into it, is exactly the
            # X-1350 shape — and skipping it would let the pid reap proceed while that container kept
            # running, the half-teardown reading as a whole one that this verb exists to prevent.
            # An unresolvable container that does NOT touch this worktree is a different thing: an
            # empty `WorkingDir` is the DEFAULT for most images, so treating every idle container on
            # the host as an unanswered question would refuse every teardown everywhere. The question
            # this read asks is about THIS worktree, so only containers that touch it can leave it
            # unanswered.
            why = ("mounts " + p if _container_touches(c, p)
                   else "is unresolvable while a docker CLIENT process holds " + p + " as its cwd")
            return [], (f"container {cid[:12] or cid} {why} but its working directory could not "
                        f"be resolved to a host path — cannot tell whether it HOLDS the worktree")
        if not resolvable or host is None:
            # `not resolvable` = unanswerable but unrelated — NEITHER error leg above applies (it does
            # not touch this worktree AND no docker client holds it). `host is None` with resolvable =
            # answered: container-private, never here.
            continue
        if host == p or host.startswith(p + os.sep):
            found.append({"container": cid[:12] or cid,
                          "name": str((c.get("Name") or "")).lstrip("/"),
                          "workdir": host})
    return found, None


_DOCKER_CLIENT_EXES = ("docker", "docker-compose")


def _docker_client_holders(holders: list, *, _exe_name=None) -> "list[dict]":
    """The subset of `holders` (from `_live_path_holders`) that are DOCKER CLIENT processes — a
    `docker run` / `docker compose` pid whose cwd is inside this worktree. `[{pid, cwd, exe}]`.

    THE LEG A MOUNT SCAN CANNOT SEE (the ceiling-round residual on fp1:5611c4257bc4b9e3). When a
    container's working directory is UNRESOLVABLE, the mount list is the only evidence
    `_docker_cwd_holders` has that the container is about this worktree — and a `docker run` whose
    mounts that read cannot resolve leaves NO such evidence, while its client pid sits right there in
    the holder list the reap is about to SIGTERM. Killing that client while the container keeps running
    is X-1350 reached by a second route, so a docker client holding this path makes every unresolvable
    container an unanswered question rather than a quiet "not a holder".

    IT MATCHES THE EXECUTABLE, NEVER AN ARGV SUBSTRING. `/proc/<pid>/exe` resolves to one basename per
    process — an unambiguous per-process fact, the same class of evidence as the cwd link
    `_live_path_holders` reads and for the same reason: a dispatched worker carries its whole preamble
    as ONE argv element naming many paths and commands, so a substring scan over argv false-positives
    on any booting worker (the T-10053 footgun that docstring names). A pid whose exe cannot be read
    (permission, a race) contributes nothing — this read only ever ADDS a refusal, so a blind spot
    costs a missed refusal, never a wrongful reap."""
    def _default_exe_name(pid):
        try:
            return Path(os.readlink(f"/proc/{pid}/exe")).name
        except OSError:
            return ""
    exe_name = _exe_name if _exe_name is not None else _default_exe_name
    out = []
    for h in holders or []:
        name = (exe_name(h.get("pid")) or "").split(" (deleted)")[0]
        if name in _DOCKER_CLIENT_EXES:
            out.append({**h, "exe": name})
    return out


def _container_touches(c: dict, p: str) -> bool:
    """Does this container have `p` (or a path under it) MOUNTED into it? Not a holder test — the
    holder test is the RUNTIME working directory (`_container_cwd_host_path`). This answers the narrower
    question "could this container possibly be about this worktree?", which is what decides whether an
    UNRESOLVABLE container is an unanswered question or simply an unrelated one. A mounts list that
    cannot be parsed makes the container unjudgeable, which counts as touching: fail-closed."""
    mounts = c.get("Mounts")
    if mounts is None:
        return False
    if not isinstance(mounts, list):
        return True                # unparseable — we cannot rule it out, so we do not.
    for m in mounts:
        if not isinstance(m, dict):
            return True            # same, per entry.
        src = str(m.get("Source") or "").rstrip(os.sep)
        if src and (src == p or src.startswith(p + os.sep) or p.startswith(src + os.sep)):
            return True
    return False


def _docker_run(argv) -> "tuple[str | None, str | None]":
    """Run one read-only `docker <argv>` and return `(stdout, error)`. `error == "docker-absent"` is the
    ONE non-failure error the caller treats as an honest empty (see `_docker_cwd_holders`)."""
    try:
        r = subprocess.run(["docker", *argv], capture_output=True, text=True,
                           timeout=_REAP_DOCKER_STOP_TIMEOUT_S)
    except FileNotFoundError:
        return None, "docker-absent"
    except OSError as e:
        return None, f"{type(e).__name__}: {e}"
    except subprocess.TimeoutExpired:
        return None, "timed out"
    if r.returncode != 0:
        return None, (r.stderr or r.stdout or f"exit {r.returncode}").strip().splitlines()[0][:200]
    return r.stdout, None


def _container_runtime_cwd(c: dict, *, _readlink=None) -> "str | None":
    """The container init process's ACTUAL working directory RIGHT NOW, or None when it cannot be read.

    WHY NOT `Config.WorkingDir` (audit-pre finding fp1:2e290f19277b56f2). The configured value records
    where the container was TOLD to start; a container process may `chdir` afterwards in EITHER
    direction — INTO the worktree (a holder the configured read reports as absent, so the reap proceeds
    around a live container: the X-1350 shape exactly) or OUT of it (a non-holder the configured read
    would have us `docker stop`, tearing down something this verb was never asked about). A signal
    wrong in both directions is not a weaker answer to the holder question, it is an answer to a
    DIFFERENT question, so it is not consulted at all.

    THE EVIDENCE IS THE SAME ONE EVERY OTHER HOLDER IS ANSWERED BY. `State.Pid` is the container's init
    process AS THE HOST NUMBERS IT, so `/proc/<pid>/cwd` is the identical per-process kernel fact
    `_live_path_holders` reads for a bare process. Containers and processes are therefore judged on one
    evidence class rather than two, and the ` (deleted)` suffix is stripped here for the reason that
    sibling documents at length: a teardown already in flight is precisely the window that matters."""
    readlink = _readlink if _readlink is not None else os.readlink
    state = c.get("State") if isinstance(c.get("State"), dict) else {}
    try:
        pid = int(state.get("Pid") or 0)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        cwd = readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None
    if not cwd:
        return None
    return cwd[: -len(" (deleted)")] if cwd.endswith(" (deleted)") else cwd


def _container_cwd_host_path(c: dict, p: str, *, _readlink=None) -> "tuple[str | None, bool]":
    """The HOST path a container's RUNTIME working directory resolves to, plus WHETHER the question was
    ANSWERABLE: `(host_path, resolvable)`. `(None, True)` is a real answer — "answered, and it is not a
    host path under any mount, so it cannot be this worktree"; `(None, False)` is "unanswerable". The
    second element is not decoration — the caller must distinguish "resolved, and it is not this
    worktree" from "could not be resolved", because only the second can leave a container's holder
    status unanswered (audit-pre finding fp1:5611c4257bc4b9e3).

    TWO RESOLUTIONS, IN ORDER, because the kernel renders `/proc/<pid>/cwd` in the READER's mount
    namespace. (i) For the bind-mounted worktree this card is about, the link is ALREADY a host path,
    so it is compared against `p` directly. (ii) Otherwise it is a container-namespace path, mapped
    through the mount whose `Destination` is its LONGEST matching prefix (the standard nested-mount
    rule: a mount at `/repo/wt` wins over one at `/repo`), substituting that mount's host `Source`.

    A runtime cwd that cannot be read at all yields `(None, False)` — unresolvable, routed by the
    caller's three-way fail-closed split. An ABSOLUTE container path under no mount is a DEFINITE
    answer, not an unresolved one: it is container-private, so it cannot be this worktree. Collapsing
    those two would leave every container merely working in `/tmp` unanswered, which is the ordinary
    case on any host running containers, not the X-1350 one."""
    cwd = _container_runtime_cwd(c, _readlink=_readlink)
    if cwd is None:
        return None, False
    cwd = cwd.rstrip(os.sep) or "/"
    if cwd == p or cwd.startswith(p.rstrip(os.sep) + os.sep):
        return cwd, True           # (i) already a host path, and it IS under the worktree.
    if not cwd.startswith("/"):
        return None, False
    best = None
    for m in (c.get("Mounts") or []):
        if not isinstance(m, dict):
            continue
        dest = str(m.get("Destination") or "").rstrip(os.sep)
        src = str(m.get("Source") or "").rstrip(os.sep)
        if not dest or not src:
            continue
        if cwd == dest or cwd.startswith(dest + os.sep):
            if best is None or len(dest) > len(best[0]):
                best = (dest, src)
    if best is None:
        return None, True
    dest, src = best
    rest = cwd[len(dest):]
    return ((src + rest).rstrip(os.sep) or src), True


def _resolve_holder_sessions(holders: list, containers: list, stamp, *,
                             _session_proc_alive, _proc_scan_is_takeable,
                             _session_terminally_over=None) -> dict:
    """WHICH SESSION do these holders belong to, and IS it alive? `{session_ref, verdict, holders,
    containers}` where `verdict` is `"live"` / `"dead"` / `"unknown"`.

    THE ATTRIBUTION IS THE WORKTREE STAMP, AND THAT IS STATED RATHER THAN DISGUISED. There is no
    per-pid session lookup to be had: a process holding a worktree as its cwd carries no session id,
    and the T-10053 footgun forbids scanning its argv for one. What DOES exist is the worktree's own
    stamp (T-0362), which names the session that created it — so every holder of THIS worktree is
    attributed to THAT session. The refusal text says so in those terms, so an operator reading it
    knows it is an attribution and not a probe of each pid.

    A `dead` VERDICT NEEDS POSITIVE EVIDENCE, on THREE conjunctive conditions: no live process, a
    TAKEABLE scan (so that negative is definite), AND the journal's last row for this session ref being
    a terminal marker (`_default_session_terminally_over`). The third is the one that matters most and
    the one a first pass omits: without it a session the probe simply cannot SEE reads as dead, and the
    reap becomes the 2026-08-10 loss with a signal handler.

    THE VERDICT IS TRI-STATE BECAUSE `_session_proc_alive` IS NOT. That predicate is fail-closed to
    False, so a False means "not found OR the scan failed" — and reaping on the second reading would
    kill a LIVE holder's children on an unreadable `/proc`, which is the 2026-08-10 loss with extra
    steps. So a DEAD verdict requires BOTH a negative probe AND `_proc_scan_is_takeable()` (T-11925,
    the ref-independent "was that negative definite?" companion, reused rather than re-derived). No
    stamp ref at all (an unstamped raw-git worktree) is likewise `unknown`, never dead: there is no
    holder to have proven dead. Only `dead` ever admits a teardown of live processes."""
    ref = (stamp or {}).get("session_ref")
    if not ref:
        verdict = "unknown"
    elif _session_proc_alive(ref):
        verdict = "live"
    elif not _proc_scan_is_takeable():
        verdict = "unknown"
    elif _session_terminally_over is not None and _session_terminally_over(ref):
        verdict = "dead"
    else:
        # No live process, a takeable scan — and STILL not dead, because nothing on the record says
        # this session ended. See `_default_session_terminally_over` for why the absence of a positive
        # liveness reading is not a death: read (a) can be blind, which is why read (b) exists at all.
        verdict = "unknown"
    return {"session_ref": ref, "verdict": verdict,
            "holders": list(holders or []), "containers": list(containers or [])}


def _reap_holders(resolution: dict, *, _run=None, _kill=None, _alive=None, _sleep=None) -> dict:
    """TERMINATE the resolved holders — containers first by id, then pids. `{containers, pids}` with a
    per-target outcome. CALLED ONLY on a `verdict == "dead"` resolution under `--confirm-dead`.

    CONTAINERS BEFORE PIDS, deliberately: the pid is usually the `docker run` CLIENT of one of these
    containers (X-1350), and stopping the container is what actually ends the work — killing the
    client first leaves a container holding the path with nobody left to name it.

    PIDS ESCALATE, they are not SIGKILLed on sight: SIGTERM, a bounded wait, then SIGKILL only for the
    survivors. A land-verify child that can flush and exit should be allowed to; the escalation exists
    because an orphan that ignores SIGTERM is exactly the X-1350 shape and must not leave the operator
    back at a hand kill. An ALREADY-GONE pid (ESRCH) is a normal outcome, not an error — the holder set
    was read a moment ago and processes exit. Every outcome is recorded per target, including failures,
    so the journal row names what did NOT die rather than implying a clean sweep.

    A FAILED `docker stop` ABORTS THE REAP RIGHT HERE, before a single pid is signalled, and comes back
    with `stop_failures` for the caller to REFUSE on (audit-pre ceiling residual fp1:5f78ac788ddf6c9b).
    Recording the failure per target was not enough on its own: the caller proceeded with the park, so a
    container that would not stop kept holding the worktree while the worktree was removed around it —
    the half-teardown-reading-as-a-whole-one that condition (c) already refuses for an UNANSWERED
    container question, which an answered-but-unstoppable one is simply the other face of. This is also
    the whole point of doing containers BEFORE pids: the failure lands while the pids are still alive to
    be refused over, instead of after we have destroyed the only processes that named the container.

    THE PID SIDE IS REFUSED ON THE SAME TERMS (`reap_failures`, audit-post finding fp1:d899c6b7db3ea2f2).
    A pid that SURVIVED SIGKILL, or that could not be signalled at all, is a holder that is still there —
    no different from a container that would not stop — so it comes back in `reap_failures` and the
    caller REFUSES rather than marking the reap complete. Unlike the container leg this one cannot abort
    early: the surviving pid is only knowable after the escalation has run, so every holder is attempted
    and the FAILURES are reported, rather than stopping at the first one and leaving the rest unnamed."""
    run = _run if _run is not None else _docker_run
    kill = _kill if _kill is not None else os.kill
    sleep = _sleep if _sleep is not None else time.sleep

    def _default_alive(pid):
        """Is `pid` still RUNNABLE? A ZOMBIE IS DEAD, and that distinction is load-bearing rather than
        pedantic: `kill(pid, 0)` succeeds for a terminated process until someone reaps it, so a
        signal-0 probe reads an already-dead child as alive — and this verb's own escalation then
        records `survived-SIGKILL` for a process it definitively killed (measured by this card's
        tripwire, where the holder is the test's own child). The reap can be called from a session
        that is the holder's parent, so the state field is read rather than assumed."""
        try:
            st = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False          # gone, or no procfs to answer with — either way not a live holder.
        try:
            return st.rsplit(") ", 1)[1].split()[0] != "Z"
        except IndexError:
            return False
    alive = _alive if _alive is not None else _default_alive

    out = {"containers": [], "pids": [], "stop_failures": [], "reap_failures": []}
    for c in resolution.get("containers") or []:
        cid = c.get("container")
        _, err = run(["stop", cid])
        out["containers"].append({"container": cid, "name": c.get("name"),
                                  "outcome": "stopped" if not err else f"stop-failed: {err}"})
        if err:
            out["stop_failures"].append({"container": cid, "name": c.get("name"), "error": str(err)})
    if out["stop_failures"]:
        # ABORT BEFORE THE PIDS — see the docstring. Returning here is what makes "no pid was signalled"
        # a property of the code rather than a claim in the journal row the caller is about to write.
        return out
    for h in resolution.get("holders") or []:
        pid = int(h.get("pid"))
        rec = {"pid": pid, "cwd": h.get("cwd"), "signals": []}
        try:
            kill(pid, signal.SIGTERM)
            rec["signals"].append("SIGTERM")
        except OSError as e:
            if getattr(e, "errno", None) == errno.ESRCH:
                rec["outcome"] = "already-gone"
                out["pids"].append(rec)
                continue
            rec["outcome"] = f"SIGTERM-failed: {type(e).__name__}: {e}"
            out["pids"].append(rec)
            continue
        deadline = time.monotonic() + _REAP_TERM_WAIT_S
        while time.monotonic() < deadline and alive(pid):
            sleep(0.05)
        if not alive(pid):
            rec["outcome"] = "terminated"
            out["pids"].append(rec)
            continue
        try:
            kill(pid, signal.SIGKILL)
            rec["signals"].append("SIGKILL")
            rec["outcome"] = "killed" if not alive(pid) else "survived-SIGKILL"
        except OSError as e:
            rec["outcome"] = ("already-gone" if getattr(e, "errno", None) == errno.ESRCH
                              else f"SIGKILL-failed: {type(e).__name__}: {e}")
        out["pids"].append(rec)
    # THE PID SIDE OF THE SAME QUESTION (audit-post finding fp1:d899c6b7db3ea2f2). Recording a per-pid
    # outcome was not enough, exactly as recording a per-container one was not: `survived-SIGKILL` and
    # both `SIG*-failed` outcomes sat in `pids` while `stop_failures` stayed empty, so the caller read
    # the reap as COMPLETE and removed the worktree around a process still holding it — the
    # half-teardown-reading-as-a-whole-one this verb exists to end, arriving by the one route the
    # container fix did not cover.
    #
    # CLASSIFIED BY A POSITIVE SUCCESS SET, never by matching failure strings: the three outcomes below
    # are the only ones that mean "this holder is gone", so ANY future outcome — including one nobody
    # has written yet — is a failure by default. A failure-substring test would fail OPEN on exactly the
    # outcome nobody anticipated, which is the direction that tears down a live holder.
    out["reap_failures"] = [r for r in out["pids"] if r.get("outcome") not in _REAP_SUCCESS_OUTCOMES]
    return out


def _holder_detail_lines(resolution: dict) -> str:
    """The one-line-per-holder detail BOTH refusals print (AC2): every pid, every container id, and the
    session each resolved to WITH that session's verdict. Homed once so the pre-gate foreign-stamp
    refusal and the live-holder gate cannot drift into two differently-detailed accounts of one read."""
    ref = resolution.get("session_ref") or "UNKNOWN (unstamped / raw-git)"
    v = resolution.get("verdict")
    bits = []
    for h in resolution.get("holders") or []:
        bits.append(f"pid {h['pid']} (cwd {h.get('cwd')}"
                    + ("; cwd unlinked — a teardown is ALREADY in flight" if h.get("deleted") else "")
                    + f") -> session {ref} [{v}]")
    for c in resolution.get("containers") or []:
        bits.append(f"container {c.get('container')}"
                    + (f" ({c['name']})" if c.get("name") else "")
                    + f" (workdir {c.get('workdir')}) -> session {ref} [{v}]")
    if not bits:
        return ""
    return (" HOLDERS, each named with the session it resolved to (the worktree STAMP is the "
            "attribution — a cwd carries no session id): " + "; ".join(bits) + ".")


def _refusal_holder_detail(wt, stamp, main_wt, *, _live_path_holders, _session_proc_alive=None,
                           _proc_scan_is_takeable=None, _session_terminally_over=None,
                           _docker_cwd_holders=None, _docker_client_holders=None,
                           _resolve_holder_sessions=None) -> str:
    """The AC2 holder detail for the NO-`--confirm-dead` refusal, resolved off the SAME two reads the
    live-holder gate uses — pids AND containers (audit-post fp1:c1e3256bbd16acce).

    The pre-gate refusal is the one an operator meets FIRST, so it is where "which holder is dead?"
    must be answerable in full. Passing an EMPTY container list here made that refusal name a docker
    CLIENT pid and its session but never the CONTAINER holding the path — the X-1350 shape exactly,
    the container being the thing the operator then had to go find by hand. So the docker resolver
    runs on this path too, with the same `client_held` leg the gate computes, off the holder list
    already in hand. READ-ONLY: nothing is stopped or signalled here, with or without the flag.

    FAIL-CLOSED IN THE ONLY DIRECTION A REFUSAL CAN: a refusal already refuses, so what "closed" means
    here is that an UNANSWERED container question is SAID rather than rendered as "no containers" —
    the detail carries the docker error verbatim, so a reader cannot take a silent absence for a
    clean read (SPEC-0165 item 11: absence is not evidence). Homed once so the park and work-discard
    twins cannot drift into two differently-detailed accounts of one read."""
    if _live_path_holders is None:
        return ""
    holders = _live_path_holders(wt)
    containers, docker_err = (_docker_cwd_holders or globals()["_docker_cwd_holders"])(
        wt, client_held=bool((_docker_client_holders or globals()["_docker_client_holders"])(holders)))
    res = (_resolve_holder_sessions or globals()["_resolve_holder_sessions"])(
        holders, containers, stamp,
        # The REAL default probe, never a `lambda r: False` (audit-post fp1:b3fcd947c0b5ec59):
        # a constant-False liveness would print a LIVE stamped session whose journal ends in a
        # terminal marker as [dead] — AC2 is the operator SEEING which holder is dead, so the
        # display leg answers with the same probe the reap leg re-verifies with.
        _session_proc_alive=(_session_proc_alive or _default_session_proc_alive),
        _proc_scan_is_takeable=(_proc_scan_is_takeable or _default_proc_scan_is_takeable),
        _session_terminally_over=(_session_terminally_over
                                  or (lambda r: _default_session_terminally_over(
                                      r, main_wt / "events.jsonl"))))
    detail = _holder_detail_lines(res)
    if docker_err:
        detail += (f" CONTAINER READ FAILED ({docker_err}) — container holders, if any, are NOT listed "
                   f"above; this is an unanswered question, not an empty answer.")
    return detail


def _live_holder_refusal(kind: str, path, holders: list, stamp_ref: "str | None",
                         live_session: bool, own_cwd: "str | None" = None,
                         resolution: "dict | None" = None) -> str:
    """The ONE refusal text shared by the three live-holder gates (T-10885) — so park, work-discard and
    `worktree new` cannot drift into three differently-worded accounts of the same invariant.

    NAMES THE CALLER'S OWN SHELL AS A CANDIDATE (T-11210). The guard is right and unchanged — what was
    wrong is that the text pointed AWAY from the commonest cause. A shell's working directory PERSISTS
    between tool calls, so once a session has `cd`-ed into a worktree, every later invocation inherits
    a cwd inside the worktree being torn down and the CALLER becomes a holder of the very thing it is
    removing. `_self_proc_ancestry` keeps this process and its ancestors OUT of the pid list, so the
    caller can never recognise itself in a bare list of pids — the pids printed are typically its OWN
    session's other shells. Measured twice: kupiclub 2026-08-16 (two refusals before the cause was
    found) and reproduced in the kernel on 2026-08-17. So when THIS process's cwd lies inside the
    target, the refusal says so FIRST, and says what to do about it. It still refuses exactly what it
    refused before: no auto-`cd`, no auto-kill, no relaxed decision."""
    who = []
    if own_cwd is None:
        try:
            own_cwd = os.getcwd()
        except OSError:
            own_cwd = None
    tgt = str(path).rstrip(os.sep)
    inside = bool(own_cwd) and (own_cwd == tgt or own_cwd.startswith(tgt + os.sep))
    if inside:
        who.append(f"THIS shell (pid {os.getpid()}) is itself a CANDIDATE holder — its own working "
                   f"directory {own_cwd} is inside the target")
    if live_session and stamp_ref:
        who.append(f"its stamped holder session {stamp_ref} is a LIVE process")
    if holders:
        who.append("live process(es) " + ", ".join(
            f"pid {h['pid']}{' (cwd unlinked — a teardown is ALREADY in flight)' if h['deleted'] else ''}"
            for h in holders[:4]) + " hold it as their working directory")
    return (f"{kind}: REFUSED — {path} has a LIVE holder ({'; '.join(who)}). Tearing it down or "
            f"recreating over it RESETS the holder's tracked files and destroys its UNTRACKED work "
            f"PERMANENTLY — on 2026-08-10 exactly this sequence lost two of T-10826's audit records "
            f"(the holder was mid-Stage-6, misclassified as dead). A live holder is NEVER torn down: "
            f"`--confirm-dead` is an ASSERTION, and this in-code read overrules a mistaken one "
            f"(the `worktree recover-land` posture). Wait for the holder to finish or die, then "
            f"re-invoke. If you believe it IS dead, verify first: "
            f"`bin/yitc-v2 journal query --dispatch-status`."
            + (f" CHECK YOUR OWN SHELL FIRST (T-11210): a shell's working directory PERSISTS between "
               f"calls, so once you `cd`-ed into {path} every later invocation runs from inside the "
               f"worktree you are tearing down — and the pid(s) above are most likely your OWN "
               f"session's shells, not a foreign worker. Confirm with "
               f"`readlink /proc/<pid>/cwd` per listed pid, then `cd` OUT to the main checkout "
               f"(`cd $(git -C {path} rev-parse --path-format=absolute --git-common-dir)/..` or simply "
               f"your main repo root) and re-invoke. Do NOT kill a pid you have not identified."
               if inside else "")
            # T-12375 (AC2) — NAME EACH HOLDER AND THE SESSION IT RESOLVED TO. A bare pid list cannot
            # tell an operator WHICH holder is the dead worker's orphan and which is a live session's
            # own work, so it left `--confirm-dead` as the only lever and a hand kill as the only
            # remedy (X-1350 / X-1346). The detail is appended, never substituted: everything this
            # refusal said before, it still says.
            + (_holder_detail_lines(resolution) if resolution else "")
            + ("" if not resolution or resolution.get("verdict") != "dead" else
               f" The holder session RESOLVED DEAD, so re-invoking with `--confirm-dead` will TEAR "
               f"DOWN the holder(s) named above (SIGTERM -> bounded wait -> SIGKILL; `docker stop` "
               f"for containers) and journal `worktree_children_reaped`. Nothing has been terminated "
               f"by THIS invocation."))



def cmd_worktree_adopt(args: argparse.Namespace, *, _append_event, _die, _main_worktree, _read_worktree_stamp, _stamp_is_own, _worktree_path_for_branch, REPO_ROOT, _write_worktree_stamp, _worktree_stamp_path, _session_proc_alive=None, _live_path_holders=None, _assert_no_live_holder=None, _default_session_proc_alive=None) -> None:
    """`worktree adopt (--task T-XXXX | --work <slug>) --confirm-dead` — the VERB-ASSISTED controller
    takeover of a CONFIRMED-DEAD holder's orphan worktree (T-1117), replacing the ad-hoc hand
    overwrite of the stamp file that §Controller-takeover previously prescribed. It re-stamps the
    worktree with THIS session's provenance (the explicit adoption RECORD, T-0362) via the SAME
    `_write_worktree_stamp` used at creation, then emits one `worktree_adopted` control-point event
    (SPEC-0025 catalog) to MAIN's journal so the takeover is cross-session visible (D-0035/D-0049).

    FAIL-CLOSED by design (CHARTER §P1 / non-goal #7): `--confirm-dead` is REQUIRED — the controller
    ASSERTS it ran the §Abnormal «Confirmed-dead GATE» (journal-quiescent AND no live `--session-id`
    process). A foreign worktree is never auto-adopted; adoption is this EXPLICIT, journaled act. After
    adoption the work verbs (`audit` / `stage` / `task commit` / `task close` / `land`) do not gate on
    the (now-own) stamp, so the adopter resumes from `current_stage` → close → land.

    T-10985 — THE ASSERTION IS NO LONGER THE ENFORCER. The flag stays as the controller's provenance
    assertion, but liveness is now RE-VERIFIED IN CODE before the re-stamp, via the SAME
    `_assert_no_live_holder` gate park / work-discard already carry (T-10885): a LIVE holder is refused
    even when `--confirm-dead` is passed, so a mistaken (or merely optimistic) assertion cannot take a
    worktree out from under a running worker. This closes the last hole in the recovery route the
    dispatch-side preserving re-dispatch opens (the T-10985 deadlock): unblocking the launch is only
    safe because the takeover itself DETERMINES death rather than accepting it. It also makes the code
    satisfy what SPEC-0134 rule 2 already asserts — that «adoption is the DEATH path» is enforced by
    «the existing `worktree adopt --confirm-dead` liveness guard» — a guard the verb did not in fact
    have (the docstrings of this verb and of `worktree recover-land` both recorded its absence). Same
    posture as `recover-land`: the flag is provenance, the in-code read is the enforcer.

    T-11284 — TWO SHAPES, ONE GUARD BODY. The verb was fenced to `--task T-XXXX`, so a `work/<slug>`
    filing batch had NO governed way back in: on 2026-08-17 the sweeper removed a batch worktree whose
    branch still carried unlanded commits (three filed task cards), and every door was shut —
    `land --branch` needs the worktree, raw-git recreation leaves the tree UNSTAMPED so the next verb
    refuses «carrier session not confirmed», and the verb the refusal NAMED as the route took only
    `--task`. The session escaped by creating a fresh batch and copying files, losing provenance. The
    fix is the FENCE, not a second adopt path: `--work <slug>` resolves `work/<slug>` and runs the
    IDENTICAL body below. Precedent for the pair in this same file: `cmd_worktree_park` (--task /
    --work, T-10589) and the `worktree new` control-point park inverses (D-0051). Every guard is
    SHARED, not duplicated — the `--confirm-dead` assertion, the own-stamp short-circuit, the
    `_assert_no_live_holder` re-verification (so the widening opens no T-0362 double-claim door), the
    admin-dir resolution refusal and the verify-after-write re-read all apply to both shapes. Only the
    branch name, the event's task-id tie (a batch has no card ⇒ None) and the next-step prose differ.
    Orthogonal to SPEC-0134 rule 2: the death-path invariant is unchanged, now over one more shape."""
    task, work = getattr(args, "task", None), getattr(args, "work", None)
    # Defensive both/neither (argparse's mutually-exclusive group already enforces it) — mirrors the
    # identical guard in cmd_worktree_new / cmd_worktree_park.
    if bool(task) == bool(work):
        _die("worktree adopt: pass exactly one of --task T-XXXX or --work <slug>")
    if task:
        if not re.fullmatch(r"T-\d{4,}", task or ""):
            _die(f"worktree adopt: invalid --task id {task!r} (expected T-NNNN)")
        branch = f"task/{task}"
        absent_hint = (f"(an absent worktree may mean already-LANDED; a dead worker with NO worktree is "
                       f"the `silent_stop` re-bootstrap case, not adoption). Read `journal query "
                       f"--dispatch-status --task {task}` first.")
    else:
        # SAME kebab-case slug contract the park/discard sibling uses (`_discard_work_batch`).
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", (work or "").strip()):
            _die(f"worktree adopt: --work slug must be kebab-case [a-z0-9-], got {work!r}")
        work = work.strip()
        branch = f"work/{work}"
        absent_hint = (f"(an absent worktree means already-landed, discarded, or SWEPT — a swept batch "
                       f"whose branch still carries unlanded commits is the worktree-GONE re-entry case, "
                       f"which adoption cannot serve: adoption re-stamps an EXISTING worktree). Read "
                       f"`git log main..{branch}` to see what the branch still holds.")
    wt = _worktree_path_for_branch(branch)
    if wt is None or not wt.exists():
        _die(f"worktree adopt: no live worktree on branch {branch} — nothing to adopt {absent_hint}")
    main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT
    prior = _read_worktree_stamp(wt)
    if _stamp_is_own(prior):
        _die(f"worktree adopt: {branch} is ALREADY stamped to THIS session — it is yours, "
             f"`cd {wt}` and continue (no adoption needed).")
    if not getattr(args, "confirm_dead", False):
        prior_ref = (prior or {}).get("session_ref") or "UNKNOWN (unstamped / raw-git)"
        _die("worktree adopt: REFUSED — pass --confirm-dead to assert you ran the §Abnormal "
             "«Confirmed-dead GATE» FIRST (BOTH: dispatch-status `quiescent: true` AND no live "
             f"`--session-id {prior_ref}` process, self-excluded). A foreign worktree is NEVER "
             "auto-adopted (T-0362): confirm the original worker is GONE, then re-invoke with "
             "--confirm-dead. (patterns/background-session-operation.md §Controller-takeover.)")
    # T-10985 — LIVE-HOLDER GATE: the assertion above is provenance; THIS is the enforcement. Reuses
    # the T-10885 two-read gate verbatim (stamped holder proc + live cwd holders), so a live worker is
    # never adopted out from under itself however confidently `--confirm-dead` was passed. Runs AFTER
    # the own-stamp short-circuit above, so a session's own worktree is unaffected. It emits its own
    # `deviation_captured` before refusing (the gate's journal-before-die posture).
    _assert_no_live_holder("worktree adopt", wt, prior, _append_event=_append_event, _die=_die,
                           main_wt=main_wt,
                           _session_proc_alive=(_session_proc_alive or _default_session_proc_alive),
                           _live_path_holders=_live_path_holders, task=task,
                           extra="Nothing was adopted and the worktree stamp is unchanged.")
    # ORDERED fail-closed check (T-10520 / X-0377): admin-dir resolve → stamp write → stamp re-read,
    # BEFORE any success line. A CROSS-USER (foreign-owned) worktree trips git's "dubious ownership"
    # guard, so `rev-parse --absolute-git-dir` returns non-zero → `_worktree_stamp_path` is None →
    # `_write_worktree_stamp` only WARNs yet still returns a stamp dict. The old code then printed the
    # re-stamped confirmation UNCONDITIONALLY — a contradictory output whose stamp write silently
    # failed, leaving the worktree held-by-UNKNOWN across sessions (aiseller deviation
    # adopt-cross-user-stamp-unresolved-2026-07-13). Resolve the admin dir FIRST and refuse with the
    # safe.directory step it needs rather than emit a false success.
    if _worktree_stamp_path(wt) is None:
        _die(f"worktree adopt: REFUSED — cannot resolve the git admin dir for {wt}. A cross-user / "
             f"foreign-owned worktree trips git's 'dubious ownership' guard, so the session stamp "
             f"cannot be written and adoption would silently leave {branch} held-by-UNKNOWN. Grant "
             f"this user a safe.directory exception FIRST, then re-invoke `worktree adopt`:\n"
             f"  git config --global --add safe.directory {wt}\n"
             f"(the main checkout {main_wt} may need the same exception.)")
    new_stamp = _write_worktree_stamp(wt)   # re-stamp = the adoption RECORD (caller's session_ref)
    # VERIFY-AFTER-WRITE (T-10520): re-READ the stamp and confirm it carries THIS session's ref before
    # any success line — a write that silently failed (perms / a race / an unresolved admin dir the
    # check above missed) must NOT print a re-stamped confirmation.
    reread = _read_worktree_stamp(wt)
    if not _stamp_is_own(reread):
        _die(f"worktree adopt: REFUSED — the re-stamp of {wt} did NOT take (re-read stamp "
             f"{(reread or {}).get('session_ref') or 'UNKNOWN'} ≠ this session "
             f"{new_stamp['session_ref']}); {branch} remains held-by-UNKNOWN. If this is a cross-user "
             f"worktree, grant the safe.directory exception FIRST, then re-invoke:\n"
             f"  git config --global --add safe.directory {wt}")
    # The event carries the SLUG on the work shape (T-11284) so the record names WHAT was adopted; the
    # task-id tie stays None there (a batch has no card, and the fleet-verdict consumer keys strictly
    # on a dispatch task id — the `work_batch_discarded` precedent, T-10589).
    payload = {"branch": branch, "path": str(wt),
               "prior_session_ref": (prior or {}).get("session_ref"),
               "session_ref": new_stamp["session_ref"], "started_at": new_stamp["started_at"]}
    if work:
        payload["work"] = work
    _append_event("worktree_adopted", task, payload, events_path=main_wt / "events.jsonl")
    print(f"worktree adopt: {branch} adopted by this session "
          f"(prior holder {(prior or {}).get('session_ref') or 'UNKNOWN'} confirmed dead)")
    print(f"  re-stamped {wt} → session_ref {new_stamp['session_ref']}; worktree_adopted emitted")
    print(f"cd {wt}")
    if work:
        # A batch has no card to close — its exit is the batch land (AGENTS §Writes happen in a worktree).
        print(f"next: the batch is yours again — finish/commit its filing work, then "
              f"`land --branch {branch}` from the main checkout.")
    else:
        print(f"next: resume from current_stage (the work verbs do not gate on the stamp) → "
              f"`task close {task}` → `land`. If a ship commit already exists, `land --task {task}` may suffice.")



def _recover_land_work_batch(work: str, *, _append_event, _die, _main_worktree,
                             _worktree_path_for_branch, _cli_path, REPO_ROOT, _run_git_cap,
                             _work_land_proc_alive, _subprocess, _RECOVER_LAND_WORK_SLUG_RE=None) -> None:
    """`worktree recover-land --work <slug>` — recover a `work/<slug>` batch branch that carries
    commits `main` does not have, INCLUDING the case its worktree is GONE (the one no other verb can
    take). Ordered: observe → fail-closed liveness → restore the worktree via the covering verb →
    land. IDEMPOTENT at both ends: nothing to recover is a no-op SUCCESS, and a re-run after a
    successful recovery finds the branch merged (or absent) and says so.

    THE RESTORE IS A DELEGATION, NEVER A RAW `git worktree add` (AGENTS §Verb-execution discipline).
    `worktree new --work <slug>` already RE-ATTACHES a worktree to an existing work branch (T-11286,
    `_work_resume_candidate`) — so the missing half of this recovery is a verb that SHIPPED, and the
    honest fix is to CALL it rather than re-implement its `worktree add`. That also means this arm
    inherits every guard that verb carries — the live-holder gate (T-10885), the branch double-claim
    refusal, and the T-0362 session stamp — instead of opening a second, unguarded creation path. A
    raw recreation would leave the locus UNSTAMPED, which is precisely the dead end that made the
    incident's session hand-copy files into a fresh batch and lose the provenance.

    LIVENESS IS FAIL-CLOSED, and its one answerable axis is stated rather than assumed. A work batch
    carries no dispatch record, so there is no `session_ref` to probe — the task arm's axis 2 has no
    counterpart here and is NOT silently treated as satisfied. What IS answerable is axis 1, the one
    that matters for a torn tree: `_work_land_proc_alive(slug)` (T-11137, the work-axis sibling of
    `_land_proc_alive`) — a live `land` on this branch means recovery would RACE it (E-0035), so it
    REFUSES. The other liveness question — is someone holding this worktree right now — is answered
    by the delegated `worktree new`'s own gate, in code, at the moment it would create.
    """
    if not re.fullmatch(_RECOVER_LAND_WORK_SLUG_RE, (work or "").strip()):
        _die(f"worktree recover-land: --work slug must be kebab-case [a-z0-9-], got {work!r}")
    work = work.strip()
    branch = f"work/{work}"
    if _run_git_cap is None or _work_land_proc_alive is None:
        _die(f"worktree recover-land: REFUSED — the git reader / work-land liveness probe was not "
             f"injected, so neither what {branch} carries nor whether a land is in flight on it can "
             f"be established. Fail-closed: nothing was created and nothing was landed.")
    main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT

    # OBSERVE (1/2) — the branch must EXIST. An absent branch is the already-landed/deleted end of the
    # idempotence range, not an error: re-running a successful recovery must be a quiet success.
    if _run_git_cap(["rev-parse", "--verify", "--quiet", branch], main_wt).returncode != 0:
        print(f"worktree recover-land: no branch {branch} — already landed/deleted; nothing to "
              f"recover (idempotent no-op).")
        return
    # OBSERVE (2/2) — the branch must carry commits `main` does not have. This IS the admission
    # observation on this axis, the direct analog of the task arm's closure-record-on-branch read: a
    # batch has no card and therefore no status, so what the branch itself CARRIES is the only
    # evidence there is (the same ground `_work_resume_candidate` and the SPEC-0119 rule-24 view
    # stand on). A branch with nothing ahead has nothing to recover — no-op SUCCESS, never a land.
    r = _run_git_cap(["rev-list", "--count", f"main..{branch}"], main_wt)
    raw = (r.stdout or "").strip()
    if r.returncode != 0 or not raw.isdigit():
        _die(f"worktree recover-land: REFUSED — cannot count what {branch} carries "
             f"(`git rev-list --count main..{branch}` exited {r.returncode}: "
             f"{(r.stderr or r.stdout or '').strip() or 'no output'}). An unreadable count is not a "
             f"zero: refusing rather than guessing. Nothing was created and nothing was landed.")
    ahead = int(raw)
    if ahead == 0:
        print(f"worktree recover-land: {branch} carries no commits main lacks — already integrated; "
              f"nothing to recover (idempotent no-op).")
        return
    head = ((_run_git_cap(["rev-parse", "--short", branch], main_wt).stdout) or "").strip() or None

    # FAIL-CLOSED — never race a live land on this branch (E-0035, the task arm's axis 1).
    if _work_land_proc_alive(work):
        _die(f"worktree recover-land: REFUSED — a LIVE `land` proc for {branch} is in flight "
             f"(land-alive). Firing recovery would RACE it (the E-0035 torn-tree class). Leave it; "
             f"re-check after it terminates.")

    wt = _worktree_path_for_branch(branch)
    if wt is not None and wt.exists():
        # AC4 — THE SIBLING CASE, AND IT IS DELIBERATELY UNTOUCHED. A batch that still HAS its worktree
        # is not the dead end this arm exists for: it already recovers by a plain land, and that path
        # must stay exactly what it was. So nothing is re-created, nothing is re-stamped (re-stamping a
        # foreign worktree is `adopt --work`'s job and its own `--confirm-dead` decision, T-11284), and
        # no recovery record is emitted — the land below is the SAME land the operator would have run.
        print(f"worktree recover-land: {branch} still HAS its worktree ({wt}) — nothing to restore; "
              f"this is the plain-land case, and it is unchanged. Landing it as-is.")
    else:
        # THE CASE THIS ARM EXISTS FOR — the worktree is GONE. Restore it through the covering verb.
        print(f"worktree recover-land: {branch} carries {ahead} commit(s) main lacks and has NO "
              f"worktree — restoring it via `yitc-v2 -C {REPO_ROOT} worktree new --work {work}` ...")
        rc = _subprocess.run([sys.executable, str(_cli_path), "-C", str(REPO_ROOT),
                              "worktree", "new", "--work", work], env=os.environ.copy())
        if rc.returncode != 0:
            _die(f"worktree recover-land: the delegated `worktree new --work {work}` did NOT succeed "
                 f"(exit {rc.returncode}); its refusal is above. NOTHING was landed and {branch} is "
                 f"untouched — resolve the cause and re-run (this verb is idempotent).")
        wt = _worktree_path_for_branch(branch)
        if wt is None or not wt.exists():
            _die(f"worktree recover-land: REFUSED — `worktree new --work {work}` reported success but "
                 f"no worktree resolves on {branch}. Refusing to land a branch whose write locus "
                 f"cannot be named; {branch} is untouched.")
        # THE RECOVERY RECORD (AC2) — the EXISTING `worktree_adopted` event, no new type. It names the
        # BRANCH and WHAT was recovered (the commit count + the tip), so a governed recovery is visible
        # across sessions exactly as the task arm's re-stamp record is. The task-id tie is None: a batch
        # has no card, the `work_batch_discarded` / `adopt --work` precedent. Emitted ONLY here — on the
        # sibling path above nothing was recovered, and a record of a non-event is noise.
        _append_event("worktree_adopted", None,
                      {"branch": branch, "work": work, "path": str(wt),
                       "recovery": "recover-land --work", "recovered_commits": ahead,
                       "recovered_head": head},
                      events_path=main_wt / "events.jsonl")
        print(f"worktree recover-land: restored the worktree for {branch} at {wt} "
              f"(recovered {ahead} commit(s), tip {head or 'unknown'}); worktree_adopted emitted.")

    # LAND — the `--branch` form the work axis takes, run FROM main (never `cd` into the worktree), so
    # the exit code is reliable (T-9600) and the `LAND: OK/ABORT` token streams through. Delegated with
    # `-C REPO_ROOT` + inherited env so the repo binding survives under -C (the task arm's finding-0).
    cmd = [sys.executable, str(_cli_path), "-C", str(REPO_ROOT), "land", "--branch", branch]
    print(f"worktree recover-land: integrating via `yitc-v2 -C {REPO_ROOT} land --branch {branch}` ...")
    lr = _subprocess.run(cmd, env=os.environ.copy())
    if lr.returncode != 0:
        _die(f"worktree recover-land: the delegated `land --branch {branch}` did NOT succeed "
             f"(exit {lr.returncode}); its `LAND: ABORT <reason>` is above. The worktree is left "
             f"intact for inspection — resolve the cause and re-run.")
    print(f"worktree recover-land: {work} recovered — work batch {branch} integrated to main (LAND: OK).")



def cmd_worktree_recover_land(args: argparse.Namespace, *, _append_event, _die, _main_worktree,
                              _read_worktree_stamp, _stamp_is_own, _worktree_path_for_branch,
                              _write_worktree_stamp, _dispatch_status_events, _classify_dispatch,
                              _session_proc_alive, _land_proc_alive, _cli_path, REPO_ROOT,
                              _read_yaml, _dispatch_events_tail_first=None, _run_git_cap=None,
                              _work_land_proc_alive=None, _recover_land_work_batch=None,
                              _recover_land_batch_residue=None,
                              _land_batch_foreign_merges=None,
                              _land_contamination_advisory=None, _segment_lines=None,
                              _events_path=None, _RECOVER_LAND_WORK_SLUG_RE=None,
                              _stamp_is_own_tolerant=None) -> None:
    """`worktree recover-land (--task T-XXXX | --work <slug>) [--confirm-dead]` — the GOVERNED, FAIL-CLOSED, IDEMPOTENT
    recovery of a CONFIRMED-DEAD worker's completed-but-UNLANDED build (the `closed_pending_land`
    class): a worker `task close`d in its worktree but its `land` was lost to a turn-yield/proc-death
    before integrating (the T-10130 death class). ADMISSION is keyed on the OBSERVED worktree state
    (a closure record on the branch), with the dispatch class as corroboration — so an ESCALATED
    worker whose class reads TERMINAL(halt) is still recoverable (T-10813). It MECHANIZES the §Recovery-trigger doctrine
    (patterns/background-session-monitoring.md §Abnormal — grace-wait → land-dead → confirm-dead →
    adopt → land) into ONE verb, so the controller/watcher enacts recovery WITHOUT the hand-executed
    multi-step dance the incident lost the build to.

    IMPROVES on blind `worktree adopt --confirm-dead` (which does NO process walk and TRUSTS the
    assertion): this verb RE-VERIFIES liveness IN-CODE against the SPEC-0133 substrate (the same
    `_classify_dispatch` + `_land_proc_alive` + `_session_proc_alive` the fleet-verdict reads), so a
    mistaken invocation on a LIVE worker or a live self-land FAILS CLOSED. `--confirm-dead` is kept as
    the controller's optional provenance assertion; the in-code gate — NOT the flag — is the true
    enforcer. §6-safe: CONTROLLER-INVOKED + confirmed-dead-gated, never auto-fires (the exact
    `worktree adopt` / `_redispatch_dead_orphan` posture). SPEC-LESS by the SPEC-0005 admission test —
    the safety-invariant lives wholly here + in tests (precedent worktree park/adopt/sweep, T-9532);
    cites SPEC-0132 (admission/land-lock) / SPEC-0133 (liveness verdict) / SPEC-0134 (adoption =
    death-path, live workers inviolate). Reuses the `worktree_adopted` + `land_completed` events (no
    new event). The land is delegated to the existing `land` verb, invoked with `-C REPO_ROOT` +
    inherited env so the repo binding survives under -C consumer execution (audit-pre finding-0).

    T-11385 — TWO SHAPES, ONE DEAD END CLOSED. The verb was fenced to `--task T-XXXX`, so the WORK axis
    had no one-verb recovery at all: a `work/<slug>` branch carrying real unlanded commits whose
    WORKTREE IS GONE (a sweep, a hand `git worktree remove`, a land that died after the tear-down)
    could be handed to NO single governed verb — `land --branch` resolves the branch THROUGH its
    worktree and dies "no linked worktree found on branch", and `worktree adopt --work` (T-11284)
    RE-STAMPS an EXISTING worktree, so it has nothing to adopt when the worktree is exactly what is
    missing (its own absent-hint says so in as many words). The reported instance isolated the
    variable: a SIBLING branch in the same state except that it still HAD its worktree recovered
    cleanly with a plain land. So the gap is the missing WORKTREE, not the dead land. `--work <slug>`
    is that arm — the same observe → fail-closed-liveness → restore → land shape, differing only in
    WHAT is observed and WHAT is delegated to — and it EXTENDS this verb rather than adding a second
    one (CHARTER §P1 filter 1; the precedent pair in this same file: `cmd_worktree_adopt` (T-11284)
    and `cmd_worktree_park` (T-10589), both --task/--work). The task arm is UNCHANGED."""
    import subprocess
    task, work = getattr(args, "task", None), getattr(args, "work", None)
    # Defensive both/neither (argparse's mutually-exclusive group already enforces it) — the identical
    # guard `cmd_worktree_adopt` / `cmd_worktree_new` / `cmd_worktree_park` carry.
    if bool(task) == bool(work):
        _die("worktree recover-land: pass exactly one of --task T-XXXX or --work <slug>")
    # T-11559 — the KILLED-LAND arm (body: `bin/lib/worktree_batch_recovery.py#cmd_batch_residue`,
    # injected by cli.py — it lives beside the SPEC-0184 land concern it is about, per that module's
    # own header). Placed ABOVE the two shape arms because `--batch-residue`
    # selects on the branch's STATE (a half-formed batch), not on its NAME: the same residue can sit
    # on either a task/ or a work/ branch (SPEC-0184 rule 1 is actor-agnostic — an interactive
    # Controller landing a work/<slug> batch is an ordinary member), so it composes with whichever
    # of --task/--work names the branch instead of being a third value of that choice.
    if getattr(args, "batch_residue", False):
        if _recover_land_batch_residue is None:
            _die("worktree recover-land: --batch-residue is unavailable — its body "
                 "(`bin/lib/worktree_batch_recovery.py#cmd_batch_residue`) was not injected by the "
                 "host residue, so this recovery cannot run (fail-closed).")
        return _recover_land_batch_residue(
            work or task, is_work=bool(work), _append_event=_append_event, _die=_die,
            _main_worktree=_main_worktree, _worktree_path_for_branch=_worktree_path_for_branch,
            REPO_ROOT=REPO_ROOT, _run_git_cap=_run_git_cap, _land_proc_alive=_land_proc_alive,
            _work_land_proc_alive=_work_land_proc_alive,
            _land_batch_foreign_merges=_land_batch_foreign_merges,
            _land_contamination_advisory=_land_contamination_advisory,
            _segment_lines=_segment_lines, _events_path=_events_path,
            _RECOVER_LAND_WORK_SLUG_RE=_RECOVER_LAND_WORK_SLUG_RE)
    if work:
        return _recover_land_work_batch(
            work, _append_event=_append_event, _die=_die, _main_worktree=_main_worktree,
            _worktree_path_for_branch=_worktree_path_for_branch, _cli_path=_cli_path,
            REPO_ROOT=REPO_ROOT, _run_git_cap=_run_git_cap,
            _work_land_proc_alive=_work_land_proc_alive, _subprocess=subprocess)
    if not re.fullmatch(r"T-\d{4,}", task or ""):
        _die(f"worktree recover-land: invalid --task id {task!r} (expected T-NNNN)")
    branch = f"task/{task}"
    wt = _worktree_path_for_branch(branch)
    main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT
    # IDEMPOTENT — no live task worktree ⇒ already landed/removed ⇒ no-op SUCCESS (never a double-land).
    if wt is None or not wt.exists():
        print(f"worktree recover-land: no live worktree on {branch} — already landed/removed; "
              f"nothing to recover (idempotent no-op).")
        return
    # GATE — reuse the SPEC-0133 dispatch classification (NO new liveness logic). T-10398: read the
    # events TAIL-FIRST when the host injects the reader (this was the LAST unbounded caller of the
    # dispatch fold after T-10397 — a full ~90MB journal scan per invocation). The soundness argument
    # lives at its ONE home, `journal._dispatch_events_tail_first`: a tail POSITIVE carries the whole
    # newest-launch epoch and classifies BIT-IDENTICALLY, a tail NEGATIVE is inconclusive and re-reads
    # FULL. Un-injected -> the plain full reader, byte-identical to pre-T-10398 (the T-10396/T-10397
    # `=None` precedent). This is a LATENCY route, not a correctness one: every degradation of this
    # gate is a REFUSAL (a missed launch row cannot produce `closed_pending_land`), never a false
    # permit — the fallback is what keeps the verdict identical, not what keeps it safe.
    if _dispatch_events_tail_first is None:
        _evs = _dispatch_status_events(task_id=task)
    else:
        _evs, _allev, _launch_ts = _dispatch_events_tail_first(task_id=task)
    cls, detail, _last_ts, sref = _classify_dispatch(_evs, task)
    # ADMISSION (T-10813) — key on the OBSERVED WORKTREE STATE, with the dispatch class as
    # CORROBORATION rather than the gate. A worker that ESCALATED (blocked-on-land) before dying
    # classifies TERMINAL(halt) even though its branch IS closed-but-unlanded — the class then
    # SHADOWED the real state and made the one-verb recovery unreachable for exactly the case it
    # exists to serve (hit live on T-10746 / T-10817 / T-10811, each costing a manual adopt+land
    # dance). The observation is the closure record ON THE BRANCH: the worktree's own task card
    # (the worktree checkout IS `task/T-XXXX`) reads `status: done`, which `task close` writes and
    # only `land` carries to main. The CURRENT status is the observation; `closed_at` is only
    # corroboration in the diagnostics (audit-pre absorption: a stale `closed_at` left on a REOPENED
    # card would otherwise admit a worktree whose status is no longer closed). That observation is the SOLE admission
    # path — the class is NEVER an OR-branch into it (audit-pre absorption: an
    # `or cls == closed_pending_land` would re-instate the classification as a gate and could admit
    # a worktree with no closure record at all). Every liveness check below stays fail-closed and
    # runs AFTER admission, so a LIVE worker (or a live self-land) is still REFUSED (E-0035 race).
    _wt_tasks = wt / "tasks"
    _matches = sorted(_wt_tasks.glob(f"{task}-*.yaml")) if _wt_tasks.exists() else []
    _card = (_read_yaml(_matches[0]) or {}) if _matches else {}
    _status_on_branch = _card.get("status")
    closed_on_branch = (_status_on_branch == "done")
    if not closed_on_branch:
        _die(f"worktree recover-land: REFUSED — the OBSERVED state of {branch} is NOT "
             f"closed-but-unlanded: its on-branch card reads "
             f"`{_status_on_branch or 'no card / no status'}`, not `done` — no closure record "
             f"(corroborating: closed_at {_card.get('closed_at') or '-'}, dispatch class `{cls}`, "
             f"detail: {detail or '-'}). This verb recovers ONLY a "
             f"built+closed-but-UNLANDED worker; read `journal query --dispatch-status --task {task}` "
             f"and use that class's route (hang_suspect → adopt + resume; silent_stop → re-bootstrap).")
    # FAIL-CLOSED axis 1 — the worker's OWN self-land must be DEAD (never race a live land, E-0035).
    if _land_proc_alive(task):
        _die(f"worktree recover-land: REFUSED — a LIVE `land` proc for {task} is in flight "
             f"(land-alive). The worker's own self-land is running; firing recovery would RACE it "
             f"(the E-0035 torn-tree class). Leave it; re-check after it terminates.")
    # FAIL-CLOSED axis 2 — the worker SESSION proc must be VERIFIABLY DEAD, or the live session it
    # names must be the CALLER'S OWN (T-11916, below). A MISSING session_ref is
    # UNVERIFIABLE (the worker's death cannot be confirmed) → REFUSE, never proceed (a bare `sref and …`
    # would fail OPEN on a missing ref — audit-post finding). This check stays FIRST, so no absent
    # identity ever reaches the own-session carve-out.
    if not sref:
        _die(f"worktree recover-land: REFUSED — {task} carries NO identifiable worker session_ref, so "
             f"its death is UNVERIFIABLE. Recovery acts ONLY on a CONFIRMED-DEAD worker (SPEC-0134 "
             f"death-path); read `journal query --dispatch-status --task {task}` and resolve manually.")
    if _session_proc_alive(sref):
        # T-11916 — the ONE carve-out: the live session found IS the CALLER'S OWN. Sibling workers in
        # one fleet inherit a single provider session id, so their stamps share a session_ref (T-0412,
        # an accepted bounded scope) — a controller that RE-DISPATCHED the worker therefore shares that
        # ref, the probe finds this very process, and the verb reported the OPERATOR TO THEMSELVES as
        # the reason recovery is impossible (captured 2026-08-21, fingerprint
        # recover-land-refuses-naming-the-callers-own-session-as-the-live-holder). The only route left
        # was the hand `worktree adopt --confirm-dead` + `land` dance this verb exists to replace.
        # SAME SHAPE AS T-11210, which taught the LIVE-HOLDER refusal to name the caller's own shell as
        # a candidate holder — the guard is right, it just could not see that what it found was YOU.
        # NO SECOND IDENTITY COMPARISON: it asks the EXISTING own-check about a synthetic stamp. The
        # TOLERANT twin, deliberately: the strict `_stamp_is_own` DIES when this session's identity is
        # unestablishable, which would replace an informative ALIVE/UNVERIFIABLE refusal with an
        # identity abort on FOREIGN input. The tolerant twin runs the SAME equality against the SAME
        # resolver and merely yields not-own where strict dies, so its error direction is ONE-WAY — it
        # can answer "not yours" more often than strict, NEVER "yours" where strict would not — and it
        # therefore cannot admit a recovery the strict check would refuse. An unresolvable identity, and
        # an un-injected collaborator, both read NOT-OWN and take the refusal below BYTE-UNCHANGED.
        # WIDTH: this is the whole carve-out. A FOREIGN live session is still refused (the E-0035
        # torn-tree class this guard exists to prevent), the missing-ref refusal above still runs FIRST
        # so an absent identity can never reach here, axis 1 (a live self-land) is untouched, and
        # `--confirm-dead` stays an ASSERTION that this in-code read still overrules. No new flag, no
        # widened authority.
        _own_live = bool(_stamp_is_own_tolerant) and bool(
            _stamp_is_own_tolerant({"session_ref": sref}))
        if not _own_live:
            _die(f"worktree recover-land: REFUSED — worker session {sref} is still ALIVE. Recovery acts "
                 f"ONLY on a CONFIRMED-DEAD worker (SPEC-0134 death-path); wait for it to finish or die.")
        print(f"worktree recover-land: the only LIVE session found for {task} is {sref} — which is THIS "
              f"caller's OWN resolved session ref, not a live worker (sibling workers in one fleet share "
              f"a provider session id, T-0412). Proceeding under your `--confirm-dead` assertion "
              f"(`confirm_dead={bool(getattr(args, 'confirm_dead', False))}`); a FOREIGN live session "
              f"would still be refused here.")
    # CONFIRMED closed_pending_land + land-dead + proc-dead → adopt (re-stamp = the visible recovery
    # record; prior_session_ref = the dead worker) then delegate to the existing land engine.
    prior = _read_worktree_stamp(wt)
    if not _stamp_is_own(prior):
        new_stamp = _write_worktree_stamp(wt)
        _append_event("worktree_adopted", task,
                      {"branch": branch, "path": str(wt),
                       "prior_session_ref": (prior or {}).get("session_ref"),
                       "session_ref": new_stamp["session_ref"], "started_at": new_stamp["started_at"],
                       "recovery": "recover-land",
                       "confirm_dead_asserted": bool(getattr(args, "confirm_dead", False))},
                      events_path=main_wt / "events.jsonl")
        print(f"worktree recover-land: adopted dead {branch} (prior holder "
              f"{(prior or {}).get('session_ref') or 'UNKNOWN'} confirmed dead + land-dead).",
              flush=True)
    # Delegate to the existing `land` verb — pass `-C REPO_ROOT` + inherit env so the repo binding
    # survives under -C consumer execution (audit-pre finding-0). Run FROM main (never cd into the
    # worktree), so the exit code is reliable (T-9600) and the `LAND: OK/ABORT` token streams through.
    cmd = [sys.executable, str(_cli_path), "-C", str(REPO_ROOT), "land", "--task", task]
    # T-12108 — FLUSH BEFORE THE CHILD, and this is the whole fix. The child below INHERITS this
    # process's stdout fd, but under a pipe capture (every tool/harness invocation) our own stdout is
    # BLOCK-buffered: without the flush the two announcements above sit in this process's userspace
    # buffer while the child writes its entire run — INCLUDING its contracted `LAND:` token — straight
    # to the shared fd, and they are flushed only at interpreter exit, AFTER the child is gone. The
    # captured stream then ENDS at `integrating via ...` with the child's token sitting ABOVE it,
    # where it reads as the PREVIOUS command's output. That inversion is what made the 2026-08-31
    # T-11857 recovery read as "adopted, announced integration, then stopped with no LAND: ABORT":
    # the delegated land had in fact aborted on the repeated-abort backstop
    # (events.jsonl#ts=2026-08-31T07:18:08Z, cause `verify-failed#ec7ed56fff5d`) and `_die` below DID
    # fire — the signal was never missing, only mis-ORDERED.
    #
    # NO TOKEN IS MINTED HERE, deliberately. This verb stays a pure CONSUMER of the T-0269 token
    # contract, so it needs no SPEC-0180 `implements` anchor. SPEC-0180 rule 2c states terminality as
    # TOKEN-OR-EXIT and prescribes capturing WIDE (`2>&1`, `^(LAND:|yitc-v2:)`) while gating NARROW:
    # the `_die` below already emits a `yitc-v2:` refusal naming the child's exit code, and this
    # process exits non-zero. Both halves were always present; ordering is what hid them.
    print(f"worktree recover-land: integrating via `yitc-v2 -C {REPO_ROOT} land --task {task}` ...",
          flush=True)
    r = subprocess.run(cmd, env=os.environ.copy())
    if r.returncode != 0:
        _die(f"worktree recover-land: the delegated `land --task {task}` did NOT succeed "
             f"(exit {r.returncode}); its `LAND: ABORT <reason>` is above. The worktree is left intact "
             f"for inspection — resolve the cause and re-run.")
    print(f"worktree recover-land: {task} recovered — completed build integrated to main (LAND: OK).",
          flush=True)



def _default_session_proc_alive(session_ref: "str | None") -> bool:
    """The module default for the injected `_session_proc_alive` (T-10885) — the SAME targeted
    `--session-id <ref>` existence probe the fleet-verdict classifier reads (`lib/journal.py`), NOT a
    second liveness model. Imported LAZILY so this module keeps back-importing nothing at import time.
    Fail-closed toward the JOURNAL classification exactly as the original: an unreadable /proc returns
    False, i.e. it declines to assert liveness rather than fabricating it."""
    from lib import journal as _journal
    return _journal._session_proc_alive(session_ref)



def _default_proc_scan_is_takeable() -> bool:
    """The module default for the injected `_proc_scan_is_takeable` (T-12375) — the SAME ref-independent
    "was that negative liveness reading DEFINITE?" probe the fleet-verdict reader uses
    (`lib/journal.py#_proc_scan_is_takeable`, T-11925), NOT a second model of the same question. Lazy
    import, exactly as `_default_session_proc_alive` above.

    IT IS THE HALF THAT MAKES A DEAD VERDICT PROVABLE. `_session_proc_alive` is fail-closed to False,
    so a bare False means "not found OR the scan could not be taken"; reaping on the second reading
    would kill a LIVE holder's children whenever `/proc` was unreadable — the 2026-08-10 loss again,
    with a signal handler. Pairing the two is what lets the resolution answer `unknown` and refuse."""
    from lib import journal as _journal
    return _journal._proc_scan_is_takeable()



# T-12375 — POSITIVE death evidence. The terminal dispatch markers, held identically to
# `DISPATCH_TERMINAL_TYPES` (bin/lib/cli.py, T-0378/T-0588) plus the row-terminal `worker_parked` the
# fleet reader already treats as ending a chain (T-10378) — the same discrimination dispatch does.
_SESSION_TERMINAL_TYPES = ("task_closed", "bg_dispatch_halted", "task_wont_do", "worker_parked")


def _default_session_terminally_over(session_ref: "str | None", events_path) -> bool:
    """Did the JOURNAL record this session ENDING? The positive half of the dead-holder discrimination.

    WHY A NEGATIVE PROBE IS NOT ENOUGH, and this is the whole reason this reader exists. A negative
    `_session_proc_alive` says only "no process runs `--session-id <ref>`" — and a session may be very
    much alive without matching that argv: an interactive session, a worker launched by a different
    path, or any holder whose launch shape the probe cannot see. The T-10885 gate was built on exactly
    that awareness: its cwd read (b) exists BECAUSE read (a) can be blind, so treating read (a)'s
    negative as proof of death and then reaping would tear down a LIVE holder's children — the
    2026-08-10 T-10826 loss, re-opened with a signal handler. Its own AC3 tripwire pins this: a stamped
    holder whose session probe comes back blind must still be refused.

    So a reap requires DEATH TO BE ON THE RECORD, not merely un-witnessed: the journal's LAST row for
    this session ref is a terminal marker (`_SESSION_TERMINAL_TYPES`). That is what made X-1350
    actionable — the worker HALTED at 17:56 and its containers outlived it by 43 minutes — and it is
    what the 2026-08-10 holder did not have. A session the journal never knew, or one whose last row is
    ordinary work, is `unknown` and REFUSED. Read-only; a missing or unreadable journal returns False,
    fail-closed toward refusing.

    SEGMENT-AWARE (SPEC-0190 rules 1+4), and NOT a formality here. The journal is ONE logical history
    over an ordered set of physical segments; a raw open of `events.jsonl` reads the LIVE segment
    ALONE. This reader is LATEST-WINS over a session ref, so on a rotated journal a holder whose
    terminal marker had aged into an archive segment would read as «the journal never knew this
    session» — `unknown`, REFUSED. That failure is in the SAFE direction, which is exactly why it
    would go unnoticed: the operator is simply back at the hand kill this card exists to remove, on
    the older orphans most likely to need it. Reading the whole segment set is what keeps the answer
    the same before and after a rotation."""
    if not session_ref:
        return False
    from lib import journal as _journal   # lazy, exactly as the sibling defaults do.
    last = None
    try:
        # `segment_lines` is the STREAMING segment-aware primitive (T-12226) and a T-12034 physical-read
        # counter site — so this reader is instrumented by construction rather than allowlisted out of
        # the census, and it never materialises a ~175 MB journal to answer one boolean.
        for line in _journal.segment_lines(events_path, errors="replace"):
            line = line.strip()
            if not line or session_ref not in line:
                continue          # cheap prefilter; the field check below is the real one.
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("session_ref") == session_ref:
                last = row.get("type")
    except OSError:
        return False
    return last in _SESSION_TERMINAL_TYPES


def _default_park_carries_work(wt, task: str, *, _run_git_cap) -> "tuple[bool, str]":
    """T-11330 — the module default for `_park_worktree`'s injected `_carries_work` discriminator: the
    SAME `_orphan_carries_work` (T-11289) the DISPATCH-side confirmed-dead teardown already consults, NOT
    a second reading of "is this worktree empty". Lazy import, exactly as `_default_session_proc_alive`
    above lazy-imports `journal`, so this module still back-imports nothing at import time.

    WHY IT IS THE MODULE DEFAULT AND NOT AN OPTIONAL INJECTION: the branch it guards is DESTRUCTIVE, so
    an unwired injection would be fail-OPEN — a caller that forgot the kwarg would silently get the
    pre-T-11330 blind teardown back. Defaulting it here makes the guard reachable from every call site
    by construction; a test overrides it explicitly (which is what gives the AC2 mutation its teeth).

    Deliberately NOT `_classify_inert_paths`, though this file's `--work` sibling `_discard_work_batch`
    uses that one: `_orphan_carries_work`'s own docstring records the rejection and the reason — the
    SPEC-0064 allowlist holds `decisions/` INERT, which is the OPPOSITE polarity for this question and
    would declare a task's PAID external-auditor verdicts worthless. The two gates ask different
    questions ("can this change alter a verify verdict?" vs "would destroying this lose work?")."""
    from lib import dispatch as _dispatch
    return _dispatch._orphan_carries_work(wt, task, _run_git_cap=_run_git_cap)



def _park_discarded_volume(wt, *, _run_git_cap, _PARK_SHA_CAP=None) -> dict:
    """T-11330 — what a park is ABOUT TO DISCARD, as counts: `{discarded_files, discarded_commits}`.

    A pure REPORT, and deliberately NOT part of the discriminator above: it decides nothing, so it
    carries no polarity risk, and keeping it separate leaves `_orphan_carries_work`'s settled 2-tuple
    contract (and its three existing consumers) untouched. Its job is candidate (d) of the T-11330
    analysis — make the loss VISIBLE on `worker_parked` rather than silent, including on the genuine
    pre-Execution park where the honest answer is a small number, not zero.

    Fail-SOFT (the inverse of the discriminator, and correct here): an unreadable count reports `None`
    rather than refusing, because a report must never be able to block a teardown the GUARD admitted.

    T-11298 — the counts are made ACTIONABLE by naming the commits: `discarded_commit_shas` carries the
    torn-down branch's un-landed commits HEAD-FIRST, so recovery after a `--force` teardown is a
    state-read of the park record rather than a dangling-object hunt that expires at the next gc (the
    X-0998 / X-1000 recoveries survived on luck, and the pointer had to be hand-carried in
    coordination-log prose). Derived from ONE `rev-list main..HEAD` that yields BOTH the count and the
    shas, so the two can never disagree; capped, with `discarded_commits` staying authoritative for the
    true total.

    THE KEY IS ABSENT WHEN THERE IS NOTHING TO NAME, deliberately: a park of a worktree carrying no
    un-landed commits — the genuine pre-Execution outage §3a was written for — emits a record of
    exactly the shape it emitted before this change. That is the cohort-complement bound (T-11298 AC4)
    held BY CONSTRUCTION rather than by an empty-list convention a later reader could mistake for a
    measurement."""
    def _count_lines(*args) -> "int | None":
        r = _run_git_cap(list(args), wt)
        if r.returncode != 0:
            return None
        return len([ln for ln in (r.stdout or "").splitlines() if ln.strip()])

    files = _count_lines("status", "--porcelain")
    ahead = _run_git_cap(["rev-list", "main..HEAD"], wt)
    shas = ([ln.strip() for ln in (ahead.stdout or "").splitlines() if ln.strip()]
            if ahead.returncode == 0 else None)
    commits = len(shas) if shas is not None else None
    out = {"discarded_files": files, "discarded_commits": commits}
    if shas:
        out["discarded_commit_shas"] = shas[:_PARK_SHA_CAP]
    return out



def _park_default_reason(card_died: bool, landed_done: bool) -> str:
    """T-11414 / X-1080 — the `reason` a `--task` park records when the operator gave none.

    A default that ASSERTS a specific cause the verb cannot know writes a FALSE statement into an
    append-only journal, which is worse than recording none: the reported park was blocked by a
    SPEC-0175 data-floor refusal and its `worker_parked` row says `auditor-outage`, because that was
    the standing default on the `ready` branch. So the asserted default is GONE — an unexplained park
    now reads `unspecified`, which is exactly what the verb knows.

    The other two defaults STAY, and the distinction is the whole point: they are DERIVED from the card
    status this verb has already READ AND VERIFIED on main (`wont-do` ⇒ the card died under the worker;
    `done` ⇒ the claim landed and this is a retirement), so each is a restatement of checked evidence
    rather than a guess about a cause. The genuine auditor outage is likewise unaffected — the auto-park
    (`_auditor_outage_park`, bin/lib/cli.py) passes `reason="auditor-outage"` EXPLICITLY, from the code
    path that OBSERVED the outage."""
    if card_died:
        return "card-died"
    if landed_done:
        return "landed-done"
    return "unspecified"



def _assert_no_live_holder(kind: str, wt, stamp, *, _append_event, _die, main_wt,
                           _session_proc_alive, _live_path_holders, task=None, extra=None, _live_holder_refusal=None,
                           reap: bool = False, _proc_scan_is_takeable=None, _docker_cwd_holders=None,
                           _resolve_holder_sessions=None, _reap_holders=None,
                           _session_terminally_over=None, _docker_client_holders=None) -> None:
    """THE LIVE-HOLDER GATE (T-10885) — refuse a destructive teardown while the holder is ALIVE.

    Called ONLY on the `--confirm-dead` (foreign-holder) branch of park / work-discard: an OWN-stamped
    teardown is this very session tearing down its own worktree, where "the holder is alive" is
    trivially true and refusing would break every legitimate self-park (the auditor-outage auto-park
    runs FROM inside the worktree it parks).

    TWO INDEPENDENT READS, either of which refuses — deliberately fail-CLOSED toward keeping, the same
    direction the sweep's own liveness guard takes:
      (a) the stamped holder session has a LIVE `--session-id <ref>` process — the incident's exact
          signature (`worker_parked` carried `parked_by: 8bcc461e` while that session was running);
      (b) a live process holds the worktree path as its cwd — the ONLY evidence available when the
          worktree is UNSTAMPED (raw-git created), where (a) has no ref to probe.

    It emits a `deviation_captured` BEFORE refusing (the journal-before-die posture of
    `_discard_work_batch`): a near-miss that leaves no journal row is indistinguishable from one that
    never happened, and this class was invisible for exactly that reason. Reused type, no new one."""
    stamp_ref = (stamp or {}).get("session_ref")
    live_session = bool(stamp_ref) and bool(_session_proc_alive(stamp_ref))
    holders = _live_path_holders(wt)
    if not live_session and not holders:
        return
    # T-12375 — RESOLVE the holders before deciding, so both the refusal and the reap speak about the
    # same read. Containers are looked up ONLY when there is something to decide (this branch), and
    # only when a reap is even on the table: a refusal-only caller must not pay a docker round-trip.
    containers, docker_err = ([], None)
    if reap:
        # The default is the REAL reader, never a skip: an uninjected dep must not silently turn the
        # container question into "no containers" and license a half-teardown.
        # `client_held` carries the THIRD unresolvable-container leg: a docker CLIENT pid among these
        # very holders means an unresolvable container cannot be dismissed as unrelated, because the
        # reap would kill the client and leave the container holding the path (X-1350 by a second
        # route). Computed off the holder list already in hand — no second scan.
        containers, docker_err = (_docker_cwd_holders or globals()["_docker_cwd_holders"])(
            wt, client_held=bool((_docker_client_holders or globals()["_docker_client_holders"])(holders)))
    resolution = ((_resolve_holder_sessions or globals()["_resolve_holder_sessions"])(
        holders, containers, stamp,
        _session_proc_alive=_session_proc_alive,
        _proc_scan_is_takeable=(_proc_scan_is_takeable or _default_proc_scan_is_takeable),
        _session_terminally_over=(_session_terminally_over
                                  or (lambda r: _default_session_terminally_over(
                                      r, main_wt / "events.jsonl")))))
    # THE REAP LEG (X-1350 / X-1346). A DEAD holder with LIVE children is the one case this gate had no
    # answer for: refusing was right for a mid-Stage-6 holder and wrong for an orphan, so the only lever
    # left was a hand kill — the manual fallback the verb-execution discipline exists to remove. It is
    # admitted on THREE conjunctive conditions, every one of them PROVEN rather than asserted:
    #   (a) the caller opted in (`reap`, which the park path sets from `--confirm-dead`);
    #   (b) the holder session resolved DEAD — a negative liveness probe AND a takeable scan, so an
    #       unreadable `/proc` reads `unknown` and REFUSES rather than killing a live holder's children;
    #   (c) the container question was ANSWERED. An unanswered one refuses, because reaping the pids
    #       while a container keeps holding the path is a half-teardown that reads as a whole one.
    # A LIVE holder session is refused BEFORE any of this — the 2026-08-10 fence is untouched.
    # AND THE ANSWER CAN STILL GO WRONG AT THE STOP (fp1:5f78ac788ddf6c9b): a container we READ fine and
    # then could not STOP holds the path exactly as an unread one does, so the reap's OWN result is a
    # fourth condition, checked after the fact because it can only be known by trying. `_reap_holders`
    # aborts before signalling any pid in that case, so the refusal below costs the holder nothing.
    # THE SAME IS TRUE OF THE PIDS (fp1:d899c6b7db3ea2f2): a holder that SURVIVED SIGKILL, or that could
    # not be signalled at all, is still holding the path — indistinguishable, for the purpose of tearing
    # the worktree down around it, from a container that would not stop. So the fourth condition reads
    # BOTH failure lists. Without this the escalation's own failure outcomes were recorded and then
    # ignored, and the teardown proceeded on the strength of a `reap_complete` computed from the
    # container list alone.
    if reap and resolution["verdict"] == "dead" and not docker_err:
        reaped = (_reap_holders or globals()["_reap_holders"])(resolution)
        stop_failures = reaped.get("stop_failures") or []
        reap_failures = reaped.get("reap_failures") or []
        # JOURNAL BOTH LEGS, DISCRIMINATED BY `reap_complete` — the posture this file holds elsewhere: a
        # reap that half-ran is precisely what a later reader must be able to see, and an unmarked row on
        # the failing leg would read as the completed teardown it is not.
        _append_event("worktree_children_reaped", task,
                      {"path": str(wt), "kind": kind,
                       "dead_session_ref": resolution["session_ref"],
                       "holder_verdict": resolution["verdict"],
                       "pids": reaped["pids"], "containers": reaped["containers"],
                       "reap_complete": not (stop_failures or reap_failures),
                       "stop_failures": stop_failures,
                       "reap_failures": reap_failures,
                       "term_wait_s": _REAP_TERM_WAIT_S, "actor": "ai-agent"},
                      events_path=main_wt / "events.jsonl")
        if not stop_failures and not reap_failures:
            return
        if stop_failures:
            why = (", ".join(f"`docker stop {f['container']}` failed ({f['error']})"
                             for f in stop_failures)
                   + " — so this teardown is REFUSED and NO holder pid was signalled: removing the "
                     "worktree while that container keeps holding it would be a half-teardown reading "
                     "as a whole one. Stop the container by hand or fix the docker fault, then "
                     "re-invoke.")
        else:
            # The pid leg names the SURVIVOR and its outcome, because that is the one thing the operator
            # needs and the one thing X-1350 left them to find by hand. Unlike the container leg, the
            # other holders WERE signalled — say so plainly rather than implying nothing happened.
            why = (", ".join(f"pid {f['pid']} {f.get('outcome')}"
                             f"{' (signals ' + '+'.join(f['signals']) + ')' if f.get('signals') else ''}"
                             for f in reap_failures)
                   + " — so this teardown is REFUSED: the holder(s) named above are STILL HOLDING "
                     f"{wt}, and removing it around them would be a half-teardown reading as a whole "
                     "one. The other holders WERE signalled (see `worktree_children_reaped`). "
                     "Investigate the survivor — an unkillable process is usually in uninterruptible "
                     "I/O or a zombie whose parent has not reaped it — then re-invoke.")
        extra = ((extra + " ") if extra else "") + "The holder session resolved DEAD, but " + why
    _append_event("deviation_captured", task,
                  {"relates_to": task or str(wt), "fingerprint": "live-holder-teardown-refused",
                   "impact": f"{kind} refused a teardown of {wt}: holder session {stamp_ref or 'UNKNOWN'} "
                             f"live={live_session}, cwd-holders={[h['pid'] for h in holders]}. Without "
                             f"this gate the teardown would have destroyed the holder's uncommitted and "
                             f"untracked work (the 2026-08-10 T-10826 loss).",
                   "captured_via": "live-holder-gate", "actor": "ai-agent",
                   "holder_verdict": resolution["verdict"],
                   "container_read_error": docker_err},
                  events_path=main_wt / "events.jsonl")
    _die(_live_holder_refusal(kind, wt, holders, stamp_ref, live_session, resolution=resolution)
         + (f" The container holders could NOT be read ({docker_err}), so this teardown is refused even "
            f"though the holder session resolved DEAD: reaping the pids while a container kept holding "
            f"the path would be a half-teardown reading as a whole one. Fix the docker read, then "
            f"re-invoke." if docker_err and resolution["verdict"] == "dead" else "")
         + (f" {extra}" if extra else ""))



def _park_worktree(task: str, reason: str, *, _append_event, _die, _main_worktree, _read_yaml,
                   _read_worktree_stamp, _stamp_is_own, _worktree_path_for_branch, _run_git_cap,
                   REPO_ROOT, confirm_dead: bool = False, force: bool = False,
                   _session_proc_alive=None,
                   _live_path_holders=None,
                   _carries_work=None, _assert_no_live_holder=None, _park_default_reason=None, _park_discarded_volume=None,
                   _proc_scan_is_takeable=None, _docker_cwd_holders=None,
                   _resolve_holder_sessions=None, _reap_holders=None,
                   _session_terminally_over=None, _docker_client_holders=None) -> "dict":
    """T-9583 — the GRACEFUL-PARK core (shared by `worktree park` AND the cmd_audit auto-park on an
    auditor-OUTAGE ABORT). Tear down a dispatched worker's `task/T-XXXX` worktree + branch so the task
    is cleanly re-dispatchable, instead of leaving a dead-but-unlanded ORPHAN the controller must hand
    `git worktree remove` + `branch -D` + re-dispatch (the X-0098 incident, twice in one session).

    KEY INVARIANT (cite the proof — bin/lib/worktree.py `_claim_task`): `worktree new --task` writes the
    ready→in-progress CLAIM only INSIDE the worktree branch; it reaches `main` ONLY via `land`. A worker
    blocked at an audit gate (pre/post) parks BEFORE `land`, so on `main` the task is STILL `ready`. So
    PARK = teardown + event; main's task status is `ready` BY CONSTRUCTION (no main task-YAML write — that
    would be a forbidden direct-to-main write, and none is needed). The verb VERIFIES this rather than
    assuming it: it reads MAIN's task YAML and REFUSES on any status outside the three below (a claim that
    somehow LANDED `in-progress` is out of the auditor-outage-fresh-claim scope — use the normal recovery
    path: `worktree adopt` → resume → land). So acceptance #1 `status=ready` is a CHECKED postcondition on
    the ready branch, and each sibling branch is likewise gated on a status this verb has READ.

    THREE LEGAL MAIN-STATUSES — the SAME teardown, three different POST-CONDITIONS (T-10565 / X-0420,
    then T-11414 / X-1079):
      • `ready`   → the auditor-outage park: the task stays re-dispatchable (`redispatchable: True`).
      • `wont-do` → the CARD-DIED orphan: the card went terminal under a live worker, so the claim is
        moot and the worktree is DISCARDED (`redispatchable: False`). Before this, NO verb could remove
        it (sweep skips every task/T-XXXX; adopt/recover-land continue-or-land a build that must be
        discarded; park's `ready`-only gate refused it), leaving raw `git worktree remove` — the
        sanctioned escape hatch, but journal-EVIDENCE-FREE, which is what these verbs exist to prevent.
      • `done`    → the LANDED-DONE retirement (T-11414): the card's claim, diff and closure record ALL
        reached main and the branch is 0 ahead and clean, so there is nothing to adopt, resume or land —
        yet sweep skips every task/T-XXXX and park's own `ready`-only gate refused `done` as "landed
        state", leaving raw git as the only exit (X-1079, measured on four worktrees at once). Retired,
        never re-dispatchable (`redispatchable: False`). STRICTLY NARROWER than its two siblings: the
        work-in-flight guard below is the ONLY thing that opens it and `--force` is NOT admitted, so it
        can tear down a PROVABLY EMPTY worktree and nothing else.
    Every OTHER status (in-progress / parked / blocked / absent / unreadable) stays REFUSED — an in-flight
    claim is never discarded.

    OWNERSHIP: the worker parks its OWN claim — require an OWN stamp UNLESS `confirm_dead` (the controller
    parking a CONFIRMED-DEAD foreign orphan; symmetry with `worktree adopt --confirm-dead`). A foreign
    worktree is never auto-torn-down (T-0362) — that would race a live worker.

    WORK-IN-FLIGHT BOUND (T-11330 / SPEC-0103 §3a, the X-0998 / X-1000 mechanism): the card-status read
    above proves only that the CLAIM never landed — it says nothing about what the worktree HOLDS. The
    9-stage order commits at Stage 7, AFTER Tests, so a worker carries its whole diff UNCOMMITTED across
    Execution and Tests, and for a large change that window is hours. Measured 2026-08-19: T-11319 held
    684 modified files with zero commits ahead of main when the auditor-outage auto-park fired, three
    times; a later run lost a fully converged build (audit-pre GREEN, suite green, commit made) to a
    TRANSIENT auditor exit-1. So the teardown is now PRECONDITIONED on the worktree being empty of work,
    via the SAME `_orphan_carries_work` discriminator the dispatch-side teardown consults. It returns
    `{parked: False}` INSTEAD of tearing down when work is held — the caller then routes to SPEC-0103
    §3's worktree-INTACT escalation (auto-park) or refuses with a `--force --reason` override (the
    verb). `--force` is the explicit discard, mirroring the `--work` sibling's dirt gate exactly.

    Returns the `worker_parked` event data dict (also emitted to MAIN's journal) — or, on the preserved
    path, a `{parked: False, preserved: True, ...}` dict with NOTHING torn down and NO `worker_parked`
    emitted. Raises via `_die` on any refusal. SPEC-LESS by the SPEC-0005 admission test — the
    safety-invariant lives wholly here, code + test enforced (identical posture to `worktree sweep`,
    T-9532)."""
    if not re.fullmatch(r"T-\d{4,}", task or ""):
        _die(f"worktree park: invalid --task id {task!r} (expected T-NNNN)")
    branch = f"task/{task}"
    wt = _worktree_path_for_branch(branch)
    if wt is None or not wt.exists():
        _die(f"worktree park: no live worktree on branch {branch} — nothing to park (an absent worktree "
             f"means already-LANDED or never-claimed; not the orphan case).")
    main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT
    stamp = _read_worktree_stamp(wt)
    if not _stamp_is_own(stamp) and not confirm_dead:
        holder = (stamp or {}).get("session_ref") or "UNKNOWN (unstamped / raw-git)"
        # T-12375 (AC2) — NAME THE HOLDERS AND THE SESSION THEY RESOLVED TO, right here, BEFORE any
        # `--confirm-dead` is spent. This is the refusal an operator meets FIRST, so it is where the
        # "which holder is dead?" question has to be answerable: X-1350 and X-1346 both ended in a hand
        # kill because the only way to see the holders was to go look in /proc yourself. Read-only —
        # nothing is terminated on this path, with or without the flag.
        _detail = _refusal_holder_detail(
            wt, stamp, main_wt, _live_path_holders=_live_path_holders,
            _session_proc_alive=_session_proc_alive, _proc_scan_is_takeable=_proc_scan_is_takeable,
            _session_terminally_over=_session_terminally_over, _docker_cwd_holders=_docker_cwd_holders,
            _docker_client_holders=_docker_client_holders, _resolve_holder_sessions=_resolve_holder_sessions)
        _die(f"worktree park: REFUSED — {branch} is held by session {holder}, not THIS session. A foreign "
             f"worktree is never auto-torn-down (T-0362). If the original worker is CONFIRMED DEAD, re-invoke "
             f"with --confirm-dead; otherwise leave it for the live worker." + _detail)
    # LIVE-HOLDER GATE (T-10885) — `--confirm-dead` is an ASSERTION; re-verify it IN CODE before any
    # destructive step, so a mistaken assertion FAILS CLOSED (the `worktree recover-land` posture,
    # which this generalizes from land-recovery to teardown). Runs BEFORE the card-status read and the
    # removal, so a refusal costs nothing and destroys nothing.
    if confirm_dead and not _stamp_is_own(stamp):
        _assert_no_live_holder("worktree park", wt, stamp, _append_event=_append_event, _die=_die,
                               main_wt=main_wt, _session_proc_alive=_session_proc_alive,
                               _live_path_holders=_live_path_holders, task=task,
                               reap=confirm_dead, _proc_scan_is_takeable=_proc_scan_is_takeable,
                               _docker_cwd_holders=_docker_cwd_holders,
                               _resolve_holder_sessions=_resolve_holder_sessions,
                               _reap_holders=_reap_holders,
                               _session_terminally_over=_session_terminally_over,
                               _docker_client_holders=_docker_client_holders)
    # VERIFY-READY (FAIL-CLOSED, audit-post hardening): main's task YAML must RESOLVE and be explicitly
    # `status: ready` (the unlanded-claim invariant). Read from MAIN, never the worktree (whose branch
    # carries the in-progress claim that never landed). REFUSE if the card is missing OR carries no/absent
    # status OR a non-`ready` status — a worktree is destructive to tear down, so never park on an
    # unverifiable main state; escalate / use the normal recovery instead.
    main_task_path = main_wt / "tasks"
    matches = sorted(main_task_path.glob(f"{task}-*.yaml")) if main_task_path.exists() else []
    if not matches:
        _die(f"worktree park: REFUSED — no task card for {task} found under {main_task_path} on main; "
             f"cannot VERIFY the unlanded-claim `ready` invariant. Refusing to tear down a worktree on an "
             f"unverifiable main state — escalate to the controller (`blocked-on-land {task} ...`).")
    card = _read_yaml(matches[0]) or {}
    status_on_main = card.get("status")
    # T-11526 — CARRY THE READ'S SOURCE, so any refusal that ASSERTS a main-status can name the file it
    # read it from. The 2026-08-25 incident cost three deviation captures precisely because the operator
    # could not tell which surface the verb believed: the message said `done` on main while three
    # independent surfaces said `ready`, and only reading the code settled it. One field, set at the one
    # place the read happens — never re-derived downstream, which is how a "source" claim goes stale.
    status_source = str(matches[0])
    if status_on_main not in ("ready", "wont-do", "done"):
        _die(f"worktree park: REFUSED — task {task} is `{status_on_main}` on main, none of `ready`, "
             f"`wont-do` or `done` (its claim reached main mid-flight e.g. via a prior land/adopt, or the "
             f"card lacks a status). Park is for the not-yet-landed fresh-claim auditor-outage case "
             f"(`ready`), the card-died orphan (`wont-do`) or the LANDED-DONE retirement (`done`, and only "
             f"with nothing left to lose) ONLY — use the normal recovery (`worktree adopt` → resume → "
             f"land) instead of discarding an in-flight claim.")
    # CARD-DIED branch (T-10565 / X-0420) — the card went terminal `wont-do` UNDER a live worker, so the
    # claim is moot and its worktree+branch are an orphan NO verb could remove: sweep's fail-closed
    # allowlist skips every task/T-XXXX; adopt/recover-land both exist to CONTINUE or LAND a build that
    # here must be DISCARDED; and park's own `ready`-only gate above refused it. The teardown mechanics are
    # IDENTICAL to the ready-branch park (the claim never landed either way ⇒ nothing on main is lost), so
    # this EXTENDS park rather than adding a parallel discard verb (CHARTER §P1 F1). Only the
    # POST-CONDITION differs — discarded, NOT re-dispatchable — which is why `redispatchable` is carried in
    # the event + drives the caller's output (a "ready → re-dispatchable" line here would be FALSE).
    # NARROW BY CONSTRUCTION: `wont-do` is the ONLY status this branch admits (the X-0420 fingerprint
    # verbatim), and a MISSING card stays refused above (absence is UNVERIFIABLE and teardown is
    # destructive). `done` is admitted by its OWN branch below, on strictly tighter terms — never here.
    card_died = status_on_main == "wont-do"
    # LANDED-DONE branch (T-11414 / X-1079) — the card is `done` on main, so its claim, its diff and its
    # closure record ALL landed; what survives is a worktree whose branch is 0 ahead and clean. Before
    # this, THREE verbs formed a closed ring around exactly that shape: `worktree sweep` skips every
    # task/T-XXXX by construction, `worktree adopt` / `recover-land` exist to CONTINUE or LAND a build
    # that here has nothing left to continue or land, and park's own status gate refused `done` as
    # "landed state". The named recovery could not serve, so the only exit was raw `git worktree remove`
    # + `branch -D` — journal-EVIDENCE-FREE, which is the very thing these verbs exist to prevent (the
    # X-0438 / X-0420 class; measured on four worktrees at once by kupiclub).
    # SAME teardown spine, THIRD post-condition: RETIRED — the claim landed, so nothing is discarded and
    # nothing is re-dispatchable (`redispatchable: False`, as on the card-died branch, for the opposite
    # reason). Extends park a third time rather than adding a parallel retire verb (CHARTER §P1 F1),
    # exactly as T-10565 and T-10589 did.
    # NARROW BY CONSTRUCTION — the ONE thing that opens this branch is the EXISTING work-in-flight
    # discriminator below proving the worktree empty; `--force` is NOT admitted here (see the guard).
    landed_done = status_on_main == "done"
    # ── WORK-IN-FLIGHT GUARD (T-11330) — the LAST check before anything destructive happens ──────────
    # Placed AFTER every other verify and BEFORE `os.chdir`/teardown, so a refusal costs nothing and
    # destroys nothing (the `_assert_no_live_holder` placement rule, same file). POSITIVE-EVIDENCE-FOR-
    # EMPTY: `_orphan_carries_work` returns True (preserve) on every uncertain answer — an unreadable
    # tree, an unparseable count, any path outside the re-derivable claim footprint — so the only thing
    # that opens the destructive path is a PROVABLY empty worktree
    # (`lessons/carving-an-exception-into-a-fail-closed-gate` §1). The genuine pre-Execution park the
    # rule was built for (X-0098 / X-0092) is UNAFFECTED: a fresh claim's footprint is exactly
    # `events.jsonl` + `tasks/<task>-*.yaml`, which that discriminator excludes by name.
    carries_work, carries_why = (_carries_work(wt, task, _run_git_cap=_run_git_cap)
                                 if _carries_work else (False, ""))
    # T-11414 — `--force` is NOT admitted on the LANDED-DONE branch. A done card whose worktree still
    # holds un-landed work is NOT a retirement at all: it is the QUEUE §Prematurely-closed shape
    # (rework-in-place, or recover-land for a land that died mid-flight), where the surviving work is the
    # whole point. Suppressing the override here keeps the new branch strictly narrower than the two it
    # joins — it can ONLY ever tear down a provably empty worktree — so the retirement can never become
    # a second, quieter route to discarding a build (the T-11330 loss class).
    force_admitted = bool(force) and not landed_done
    if carries_work and not force_admitted:
        # JOURNAL-BEFORE-RETURN, the `_assert_no_live_holder` posture: a near-miss that leaves no
        # journal row is indistinguishable from one that never happened, and THIS class was invisible
        # for exactly that reason across three teardowns of T-11319 on 2026-08-19. Reused event type.
        _append_event("deviation_captured", task,
                      {"relates_to": task, "fingerprint": "autopark-teardown-preserved-work-in-flight",
                       "impact": f"worktree park refused a teardown of {wt}: {carries_why}. Without this "
                                 f"bound the teardown would have destroyed the worker's un-landed work "
                                 f"(T-11330; the 2026-08-19 T-11319 loss, X-0998 / X-1000).",
                       "captured_via": "work-in-flight-guard", "actor": "ai-agent"},
                      events_path=main_wt / "events.jsonl")
        # NO `worker_parked`: `journal.py` reads it as ROW-TERMINAL (T-10378), so emitting one over an
        # INTACT worktree would tell `--fleet-verdict` this worker parked when it did not.
        return {"task": task, "branch": branch, "parked": False, "preserved": True,
                "worktree": str(wt), "carries_work_why": carries_why,
                "status_on_main": status_on_main or "ready",
                "status_source": status_source,  # T-11526 — the file that status was read from
                # T-11414 — WHICH exits the refusal may honestly name. On the landed-done branch
                # `--force` is suppressed, so pointing at it would offer an exit that does not exist.
                "force_admitted": force_admitted,
                "reason": reason or _park_default_reason(card_died, landed_done)}
    forced = bool(force_admitted and carries_work)
    volume = _park_discarded_volume(wt, _run_git_cap=_run_git_cap)
    # TEARDOWN — out of the worktree first, then force-remove + delete the branch + prune (the land-cleanup
    # idiom; force is safe — the branch is being DISCARDED, and nothing on main is lost either way: on the
    # ready/wont-do branches the claim never landed, and on the landed-done branch everything already did).
    os.chdir(str(main_wt))
    rm = _run_git_cap(["worktree", "remove", "--force", str(wt)], main_wt)
    if rm.returncode != 0:
        _die(f"worktree park: `git worktree remove --force {wt}` failed: {rm.stderr.strip()} — remove it "
             f"manually, then `git branch -D {branch}`.")
    bd = _run_git_cap(["branch", "-D", branch], main_wt)
    _run_git_cap(["worktree", "prune"], main_wt)
    # FAIL-CLOSED on a `branch -D` failure (T-9590): the worktree is ALREADY removed, but a leftover
    # branch would BLOCK re-dispatch (`worktree new --task` refuses an existing branch). Refuse to emit a
    # clean `worker_parked` over a half-torn-down state — surface a DEGRADED outcome that names the manual
    # `git branch -D` (the worktree-remove failure above already follows this same fail-closed posture).
    if bd.returncode != 0:
        _die(f"worktree park: DEGRADED — worktree {wt} removed, but `git branch -D {branch}` failed: "
             f"{bd.stderr.strip()}. The leftover branch would BLOCK re-dispatch (`worktree new --task "
             f"{task}` refuses an existing branch), so this is NOT a clean park — no worker_parked emitted. "
             f"Delete the branch manually: `git branch -D {branch}` (then the task is re-dispatchable).")
    data = {"task": task, "branch": branch,
            "reason": reason or _park_default_reason(card_died, landed_done),
            "status_on_main": status_on_main or "ready",
            # T-11526 — `status_source` is DELIBERATELY NOT carried here. It exists so a refusal that
            # ASSERTS a main-status can name the file it read; this is the SUCCESS path, which reports
            # the status it actually took and never had a diagnosis problem. Widening the emitted
            # `worker_parked` payload would also break the key set T-11298 AC3/AC4 pin exactly — a
            # pinned baseline that is historical literal, correctly not rewritable to suit a later card.
            # T-10565: the machine-readable POST-CONDITION — the ONE thing that differs between the two
            # branches. Reusing `worker_parked` is correct for BOTH: fleet-verdict already consumes it as
            # ROW-TERMINAL (bin/lib/journal.py, T-10378), which a discarded card needs exactly as much as a
            # parked one. No new event type (CHARTER §P1 F2).
            "redispatchable": not (card_died or landed_done),
            "parked_by": (stamp or {}).get("session_ref"), "confirm_dead": bool(confirm_dead),
            # T-11330 — the machine-readable VOLUME of what this teardown discarded, so a loss is
            # VISIBLE on the row rather than silent. Reported on EVERY park, including the genuine
            # pre-Execution one where the honest answer is the small claim footprint, not zero.
            # `parked: True` is the positive counterpart of the preserved return above.
            "parked": True, "forced": forced, **volume}
    if forced:
        data["forced_over"] = carries_why
    _append_event("worker_parked", task, data, events_path=main_wt / "events.jsonl")
    return data



def _discard_work_batch(slug: str, reason: "str | None", *, force: bool, confirm_dead: bool,
                        _append_event, _classify_inert_paths, _die, _main_worktree,
                        _read_worktree_stamp, _stamp_is_own, _worktree_path_for_branch, _run_git_cap,
                        REPO_ROOT, _acting_session_ref,
                        _session_proc_alive=None,
                        _live_path_holders=None, _assert_no_live_holder=None,
                        _proc_scan_is_takeable=None, _docker_cwd_holders=None,
                        _resolve_holder_sessions=None, _reap_holders=None,
                        _session_terminally_over=None, _docker_client_holders=None) -> "dict":
    """T-10589 — the `worktree park --work <slug>` core: the SIBLING of `_park_worktree` for a NON-task
    `work/<slug>` batch. Tear the batch worktree+branch down GOVERNED, so abandoning a batch (the
    duplicate-discovered-post-filing exit) stops falling back to raw `git worktree remove` + `branch -D`
    — hand-work outside the verbs and JOURNAL-INVISIBLE (X-0438).

    WHY PARK AND NOT A NEW VERB: park is the inverse of the `worktree new` control-point (D-0051), and
    `worktree new` already carries the SAME --task/--work pair — the missing --work here was the
    asymmetry X-0438 fell through. Park's meaning ALREADY spans discard: its `wont-do` branch (T-10565)
    tears down with `redispatchable: False`. A batch is simply ALWAYS the discard side (no card ⇒ never
    re-dispatchable). T-10565 hit this exact fork and EXTENDED park rather than adding a parallel discard
    verb (CHARTER §P1 F1); same filter, same answer.

    THE SAFETY-GATE MAPPING (the one real difference from `_park_worktree`): park --task proves "teardown
    loses nothing" by reading MAIN's CARD STATUS (the unlanded-claim invariant). A batch HAS NO CARD, so
    that evidence source does not exist. The SAME invariant, over the evidence a batch DOES have, is
    working-tree state: no uncommitted SUBSTANTIVE dirt. So this verb substitutes the card-status verify
    with a DIRT verify — identical fail-closed-on-unverifiable-or-lossy-state posture, different evidence
    source. SUBSTANTIVE is not re-derived here: it is `_classify_inert_paths`, the single SPEC-0064
    inert authority (verdict `observable` ⇒ substantive). `--force` overrides, but only WITH `--reason`,
    so a forced discard is journal-EVIDENCED rather than silent.

    OWN-STAMP (T-0362) is unchanged from park: a foreign batch worktree is never auto-torn-down without
    `--confirm-dead`. Emits `work_batch_discarded` to MAIN's journal — a NEW type, not a reused
    `worker_parked`, whose {task, redispatchable, status_on_main} fields would all be lies for a batch
    (no worker, no card) and whose fleet-verdict consumer (bin/lib/journal.py, T-10378) keys strictly on
    a dispatch task id. SPEC-0025/D-0009 sanction the additive type (unknown types read as an opaque
    triple, never fail). SPEC-LESS by the SPEC-0005 admission test — the invariant lives wholly here,
    code + test enforced (identical posture to park T-9583 / sweep T-9532).

    WHO DESTROYED IT vs WHO HELD IT (T-12331, X-1341). The row records an IRREVERSIBLE act, so its two
    load-bearing facts are the ACTOR and whether a guard was OVERRIDDEN — and both were wrong here until
    T-12331: `discarded_by` was read off the batch's own STAMP (the holder being torn down, not the
    session doing the tearing), and `forced` was `force and verdict == "observable"` (so a `--force` the
    dirt gate did not happen to need read as false). Measured on aiseller 2026-09-09: controller
    `0a3435e6` forced a `--confirm-dead` discard of a batch held by DEAD `e95ef355`, and the only
    durable record of that act named the dead session as the destroyer and denied the override. Now:
    `discarded_by` = the ACTING session (injected `_acting_session_ref`), `held_by` = the stamp's holder
    (the fact the old key was silently carrying, under its true name), `forced` = `bool(force)`.
    NOTHING IS LOST by widening `forced`: `_classify_inert_paths` returns `dirt_class` non-None IFF the
    verdict is `observable`, and `dirt_class` is on the row — so the OLD meaning is exactly
    `forced and dirt_class is not None`, still derivable from the same row.

    `_acting_session_ref` is REQUIRED (no default) and is resolved by the HOST residue: this module is
    identity-agnostic and never back-imports the host (SPEC-0073 bin/ HARD class), so the resolver
    crosses the existing injection seam exactly as `cmd_worktree_new` receives `_resolve_session_ref`.
    The host injects `_resolve_session_ref_for_envelope` — the SAME function `_append_event`'s default
    uses (SPEC-0137 Rule 2 best-effort envelope role: it never `_die`s, the right posture for a record
    that must survive a destructive step) — which makes it structurally impossible for `discarded_by` to
    disagree with the row's own top-level `session_ref`.

    Returns the `work_batch_discarded` event data dict. Raises via `_die` on any refusal."""
    # WIRING CHECK (audit-pre finding 1) — required kwarg AND callable, verified BEFORE any destructive
    # step, so an unwired call site is a named refusal with nothing torn down rather than a bare
    # `TypeError: 'NoneType' object is not callable` raised from inside a half-completed teardown.
    if not callable(_acting_session_ref):
        _die("worktree park: internal wiring error — `_acting_session_ref` was not injected as a "
             f"callable (got {type(_acting_session_ref).__name__}). The acting session is the WHO of "
             "an irreversible discard record (T-12331); refusing to tear down a batch we could not "
             "attribute. The host residue `cmd_worktree_park` must inject it.")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", (slug or "").strip()):
        _die(f"worktree park: --work slug must be kebab-case [a-z0-9-], got {slug!r}")
    slug = slug.strip()
    branch = f"work/{slug}"
    wt = _worktree_path_for_branch(branch)
    if wt is None or not wt.exists():
        _die(f"worktree park: no live worktree on branch {branch} — nothing to discard (an absent "
             f"worktree means already-landed or never-created).")
    # FORCED-WITH-REASON (scope): --force is the substantive-dirt override, so it may never be silent.
    # Checked BEFORE the destructive work so a malformed invocation costs nothing.
    if force and not (reason or "").strip():
        _die("worktree park: --force requires --reason — a forced discard of SUBSTANTIVE work must be "
             "journal-evidenced, never silent.")
    main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT
    # T-12331 — resolve the ACTING session HERE: before the `os.chdir(main_wt)` below, so the ref is
    # read from the invocation's own locus rather than the post-chdir one, and before anything
    # destructive, so the record's WHO is in hand no matter which teardown step fails.
    acting = _acting_session_ref()
    stamp = _read_worktree_stamp(wt)
    if not _stamp_is_own(stamp) and not confirm_dead:
        holder = (stamp or {}).get("session_ref") or "UNKNOWN (unstamped / raw-git)"
        # T-12375 (AC2) — NAME THE HOLDERS AND THE SESSION THEY RESOLVED TO, right here, BEFORE any
        # `--confirm-dead` is spent. This is the refusal an operator meets FIRST, so it is where the
        # "which holder is dead?" question has to be answerable: X-1350 and X-1346 both ended in a hand
        # kill because the only way to see the holders was to go look in /proc yourself. Read-only —
        # nothing is terminated on this path, with or without the flag.
        _detail = _refusal_holder_detail(
            wt, stamp, main_wt, _live_path_holders=_live_path_holders,
            _session_proc_alive=_session_proc_alive, _proc_scan_is_takeable=_proc_scan_is_takeable,
            _session_terminally_over=_session_terminally_over, _docker_cwd_holders=_docker_cwd_holders,
            _docker_client_holders=_docker_client_holders, _resolve_holder_sessions=_resolve_holder_sessions)
        _die(f"worktree park: REFUSED — {branch} is held by session {holder}, not THIS session. A foreign "
             f"worktree is never auto-torn-down (T-0362). If the original owner is CONFIRMED DEAD, "
             f"re-invoke with --confirm-dead; otherwise leave it for the live session." + _detail)
    # LIVE-HOLDER GATE (T-10885) — the park sibling, on the SAME terms: `--confirm-dead` is re-verified
    # in code before any destructive step. A batch's uncommitted work is protected by the dirt gate
    # below, but its UNTRACKED work under a LIVE holder is what the dirt gate cannot save from a
    # teardown racing the writer; this closes that.
    if confirm_dead and not _stamp_is_own(stamp):
        _assert_no_live_holder("worktree park", wt, stamp, _append_event=_append_event, _die=_die,
                               main_wt=main_wt, _session_proc_alive=_session_proc_alive,
                               _live_path_holders=_live_path_holders,
                               reap=confirm_dead, _proc_scan_is_takeable=_proc_scan_is_takeable,
                               _docker_cwd_holders=_docker_cwd_holders,
                               _resolve_holder_sessions=_resolve_holder_sessions,
                               _reap_holders=_reap_holders,
                               _session_terminally_over=_session_terminally_over,
                               _docker_client_holders=_docker_client_holders)
    # DIRT GATE — the --work counterpart of park's VERIFY-READY card-status check. FAIL-CLOSED: an
    # unreadable tree is UNVERIFIABLE state and teardown is destructive, so refuse rather than guess
    # (the same posture as sweep's unreadable-inventory ABORT).
    st = _run_git_cap(["status", "--porcelain"], wt)
    if st.returncode != 0:
        _die(f"worktree park: REFUSED — `git status --porcelain` failed in {wt} "
             f"(rc={st.returncode}): {(st.stderr or st.stdout or '').strip()[:200]}. Cannot VERIFY the "
             f"no-substantive-dirt invariant; refusing to tear down a worktree on unverifiable state.")
    dirty = [ln[3:].strip() for ln in st.stdout.splitlines() if ln.strip()]
    # A rename porcelain line is `R  old -> new`; classify the DESTINATION (the path that would be lost).
    dirty = [p.split(" -> ")[-1].strip().strip('"') for p in dirty]
    verdict, dirt_class = _classify_inert_paths(dirty)
    if verdict == "observable" and not force:
        _die(f"worktree park: REFUSED — {branch} carries UNCOMMITTED SUBSTANTIVE work (offending "
             f"path-class: {dirt_class}). Discarding it would destroy unlanded work. Land it "
             f"(`bin/yitc-v2 land --branch {branch}`), or — if it is genuinely disposable — re-invoke "
             f"with `--force --reason <why>`.")
    # T-12331 — `forced` records WHETHER THE GUARD WAS OVERRIDDEN, as passed, not whether the dirt gate
    # happened to need the override. The narrower old reading (`force and verdict == "observable"`) is
    # still derivable from this row as `forced and dirt_class is not None` — `_classify_inert_paths`
    # sets `dirt_class` non-None IFF the verdict is `observable`.
    forced = bool(force)
    # TEARDOWN — out of the worktree first, then force-remove + delete the branch + prune (the park/land
    # cleanup idiom; force is safe here only because the dirt gate above already proved nothing
    # substantive is lost, or the operator forced it with a recorded reason).
    os.chdir(str(main_wt))
    rm = _run_git_cap(["worktree", "remove", "--force", str(wt)], main_wt)
    if rm.returncode != 0:
        # NOTHING destroyed yet ⇒ nothing to journal; the batch is intact and the operator can retry.
        _die(f"worktree park: `git worktree remove --force {wt}` failed: {rm.stderr.strip()} — remove it "
             f"manually, then `git branch -D {branch}`.")
    bd = _run_git_cap(["branch", "-D", branch], main_wt)
    _run_git_cap(["worktree", "prune"], main_wt)
    data = {"slug": slug, "branch": branch, "reason": (reason or "").strip() or "abandoned",
            "forced": forced, "dirt_class": dirt_class,
            # T-12331 (X-1341) — the two DISTINCT sessions this row must keep apart: the one that
            # DESTROYED the batch, and the one that HELD it. `discarded_by` carried the holder until
            # now, so a `--confirm-dead` discard of a dead session's batch credited the destruction to
            # the corpse. `held_by` is additive (SPEC-0025/D-0009: an unknown key reads as an opaque
            # triple), and `work_batch_discarded` has no pinned key-set test — unlike `worker_parked`,
            # whose T-11298 AC3/AC4 pin is why the task arm's identical defect is a separate card.
            "discarded_by": acting, "held_by": (stamp or {}).get("session_ref"),
            "confirm_dead": bool(confirm_dead),
            "degraded": False, "branch_deleted": True}
    if bd.returncode != 0:
        # JOURNAL-BEFORE-DIE (audit-pre HIGH, T-10589). The worktree is ALREADY destroyed, so dying
        # silently here — park --task's T-9590 shape — would leave that destruction JOURNAL-INVISIBLE:
        # precisely the X-0438 defect this verb exists to end, reproduced inside it. So record the
        # destructive step that DID complete, THEN refuse. The refusal is unchanged (still fail-closed,
        # still non-zero) — only the journal blindness is fixed. `degraded`/`branch_deleted` are the
        # machine-readable clean-vs-partial discriminator (additive, D-0009).
        data.update({"degraded": True, "branch_deleted": False,
                     "degraded_reason": f"branch -D failed: {(bd.stderr or bd.stdout).strip()[:200]}"})
        _append_event("work_batch_discarded", None, data, events_path=main_wt / "events.jsonl")
        _die(f"worktree park: DEGRADED — worktree {wt} removed, but `git branch -D {branch}` failed: "
             f"{bd.stderr.strip()}. The leftover branch would BLOCK a re-`worktree new --work {slug}`, so "
             f"this is NOT a clean discard (work_batch_discarded emitted with degraded=true — the "
             f"teardown is journalled, not invisible). Delete the branch manually: `git branch -D {branch}`.")
    _append_event("work_batch_discarded", None, data, events_path=main_wt / "events.jsonl")
    return data



# `worktree park --from-stdin` (T-12369): the stdin mapping carries the free-text reason ALONE — the
# `task refuse` shape (bin/lib/task.py REFUSE_STDIN_CONFLICTING_ARGV_FLAGS), stated here beside its
# one reader so this kernel module stays free of a host import for a one-row constant.
PARK_STDIN_CONFLICTING_ARGV_FLAGS = (
    ("reason", "--reason", "reason", None),
)
PROSE_BEARING_PARK_FIELDS = ("reason",)


def cmd_worktree_park(args: argparse.Namespace, *, _append_event, _die, _main_worktree, _read_yaml,
                      _read_worktree_stamp, _stamp_is_own, _worktree_path_for_branch, _run_git_cap,
                      _classify_inert_paths, REPO_ROOT,
                      _session_proc_alive=None,
                      _acting_session_ref=None,
                      _live_path_holders=None, _discard_work_batch=None, _park_worktree=None,
                      _proc_scan_is_takeable=None, _docker_cwd_holders=None,
                      _resolve_holder_sessions=None, _reap_holders=None,
                      _session_terminally_over=None, _docker_client_holders=None) -> None:
    """`worktree park (--task T-XXXX | --work <slug>) [--reason ...] [--force] [--confirm-dead]` — the
    GRACEFUL-TEARDOWN verb, in TWO shapes mirroring the `worktree new` control-point it inverses (D-0051):

      --task T-XXXX (T-9583) — tear down a dispatched worker's `task/T-XXXX` worktree+branch so the task
        is cleanly re-dispatchable instead of orphaned; the manual sibling of the cmd_audit auto-park on
        an auditor-OUTAGE ABORT (both call `_park_worktree`). Since T-11414 it ALSO retires the worktree
        of a card that is `done` on main — clean, 0 ahead, nothing to adopt/resume/land — which no verb
        could remove (X-1079). See `_park_worktree` for the unlanded-claim invariant, the three legal
        main-statuses + the VERIFY-READY postcondition. Emits `worker_parked`.
      --work <slug> (T-10589) — DISCARD a non-task `work/<slug>` batch (the duplicate-discovered-post-
        filing exit that used to fall back to raw `git worktree remove` + `branch -D`, X-0438). See
        `_discard_work_batch` for the dirt gate that stands in for the card-status verify a batch has no
        card to satisfy. Emits `work_batch_discarded`.

    Both shapes share the teardown spine, the own-stamp gate (T-0362) and the fail-closed posture; they
    differ only in the evidence each uses to prove the teardown loses nothing.

    `_acting_session_ref` is REQUIRED at the --work arm and DEFAULTED on the verb (T-12331): the --work
    arm's record must name WHO destroyed the batch, and that requirement is enforced by the wiring check
    in `_discard_work_batch` (callable-or-named-refusal, BEFORE any destructive step) — so an unwired
    --work call is still a named refusal with the batch intact, never a bare TypeError. The `=None`
    default exists because the --task arm never touches it: making the kwarg required on the OUTER verb
    broke every direct caller of the --task arm that passes no resolver (the T-0362 suite drives it
    without the cli host residue — land ABORT 2026-09-11). `worker_parked`'s emitted key set is pinned
    by T-11298 AC3/AC4, so the --task arm's identical holder-not-actor defect is its own card (followup
    fu_596f1532bb7e)."""
    task, work = getattr(args, "task", None), getattr(args, "work", None)
    # Defensive both/neither (argparse's mutually-exclusive group already enforces it) — mirrors
    # cmd_worktree_new's identical guard.
    if bool(task) == bool(work):
        _die("worktree park: pass exactly one of --task T-XXXX or --work <slug>")
    # T-12369 (E-0054, X-1340): the `--from-stdin` INGEST, BEFORE either shape reads `args.reason`.
    # The park reason is the only durable record of why a build was discarded (aiseller lost the
    # backticked fragment of a 16-commit teardown to shell substitution on argv). Same shared
    # ingest + one-row conflict table as `task refuse` (T-11165); lazy leaf import, as the other
    # `lib` reads in this module (it never back-imports the host).
    if getattr(args, "from_stdin", False):
        from lib import textutil as _textutil
        _stdin_fields = _textutil.stdin_mapping_ingest(
            args, PARK_STDIN_CONFLICTING_ARGV_FLAGS, stdin_text=sys.stdin.read(), die=_die,
            carries="the park reason", recognised=PROSE_BEARING_PARK_FIELDS,
            argv_dests=set(vars(args)), verb="worktree park")
        for _pk in PROSE_BEARING_PARK_FIELDS:
            _pv = _stdin_fields.get(_pk)
            if _pv is not None:
                setattr(args, _pk, str(_pv))
    if work:
        data = _discard_work_batch(
            work, getattr(args, "reason", None),
            force=bool(getattr(args, "force", False)),
            confirm_dead=bool(getattr(args, "confirm_dead", False)),
            _append_event=_append_event, _classify_inert_paths=_classify_inert_paths, _die=_die,
            _main_worktree=_main_worktree, _read_worktree_stamp=_read_worktree_stamp,
            _stamp_is_own=_stamp_is_own, _worktree_path_for_branch=_worktree_path_for_branch,
            _run_git_cap=_run_git_cap, REPO_ROOT=REPO_ROOT,
            _acting_session_ref=_acting_session_ref,
            _session_proc_alive=_session_proc_alive, _live_path_holders=_live_path_holders,
            _proc_scan_is_takeable=_proc_scan_is_takeable,
            _docker_cwd_holders=_docker_cwd_holders,
            _resolve_holder_sessions=_resolve_holder_sessions,
            _reap_holders=_reap_holders,
            _session_terminally_over=_session_terminally_over,
            _docker_client_holders=_docker_client_holders)
        main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT
        # T-12331 — `forced` no longer implies dirt (it is now `bool(--force)`), so the over-dirt
        # clause is keyed on `dirt_class` instead; keying it on `forced` would print the nonsense
        # "FORCED over None dirt" for a --force the dirt gate never needed.
        _forced_over = (f"; FORCED over {data['dirt_class']} dirt" if data["forced"] and data["dirt_class"]
                        else "; FORCED (no substantive dirt to override)" if data["forced"] else "")
        print(f"worktree park: {data['branch']} discarded (reason: {data['reason']}"
              f"{_forced_over}); "
              f"work_batch_discarded emitted")
        print(f"  work batch {data['slug']} is DISCARDED (a batch has no card — never re-dispatchable); "
              f"worktree removed + branch deleted, no orphan")
        print(f"cd {main_wt}")
        return
    # FORCED-WITH-REASON (T-11330) — the --task shape now carries the work-in-flight bound, so its
    # override takes the SAME pairing the --work sibling has always required: a forced discard of
    # substantive work must be journal-evidenced, never silent. Checked BEFORE any destructive work.
    if bool(getattr(args, "force", False)) and not (getattr(args, "reason", None) or "").strip():
        _die("worktree park: --force requires --reason — a forced teardown over a worker's un-landed "
             "work must be journal-evidenced, never silent (T-11330).")
    # Pass the reason through UNCOERCED (T-10565): `_park_worktree` picks the branch-appropriate default
    # (`auditor-outage` on the ready branch / `card-died` on the wont-do branch). Defaulting it to
    # `auditor-outage` HERE would mislabel every card-died teardown as an auditor outage.
    data = _park_worktree(task, getattr(args, "reason", None),
                          force=bool(getattr(args, "force", False)),
                          _append_event=_append_event, _die=_die, _main_worktree=_main_worktree,
                          _read_yaml=_read_yaml, _read_worktree_stamp=_read_worktree_stamp,
                          _stamp_is_own=_stamp_is_own, _worktree_path_for_branch=_worktree_path_for_branch,
                          _run_git_cap=_run_git_cap, REPO_ROOT=REPO_ROOT,
                          confirm_dead=bool(getattr(args, "confirm_dead", False)),
                          _session_proc_alive=_session_proc_alive,
                          _live_path_holders=_live_path_holders,
                          _proc_scan_is_takeable=_proc_scan_is_takeable,
                          _docker_cwd_holders=_docker_cwd_holders,
                          _resolve_holder_sessions=_resolve_holder_sessions,
                          _reap_holders=_reap_holders,
                          _session_terminally_over=_session_terminally_over,
                          _docker_client_holders=_docker_client_holders)
    main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT
    # T-11330 — the WORK-IN-FLIGHT refusal. ONE complete message per branch, never a distinct diagnosis
    # printed above a shared generic tail (`lessons/carving-an-exception-into-a-fail-closed-gate` §2):
    # this composes the whole refusal, so the operator cannot receive it alongside a contradicting
    # "torn down" line. It names the three real exits rather than only forbidding the teardown.
    if data.get("parked") is False and data.get("status_on_main") == "done":
        # T-11414 — the LANDED-DONE refusal. `--force` is suppressed on that branch, so this message must
        # NOT offer it: a `done` card whose worktree still holds work is the QUEUE §Prematurely-closed
        # shape, where the surviving work is the point. Its own complete message, never a shared tail with
        # a contradicting exit (`lessons/carving-an-exception-into-a-fail-closed-gate` §2).
        #
        # T-11526 — DISCRIMINATE ON THE BRANCH THE VERB TOOK, never on `force_admitted`. That field is
        # `bool(force) and not landed_done`, so it is False for TWO structurally different reasons: the
        # landed-done branch WITHHOLDING --force (its job), and --force simply NOT HAVING BEEN PASSED (the
        # ordinary case). Keying the message on it therefore routed EVERY plain park over a worktree
        # holding work — on ANY of the three legal main-statuses — into this landed-done text, telling the
        # operator a closure had landed when the verb had just read `ready` (measured twice against
        # T-11519 on 2026-08-25; the SUCCESS path prints `status_on_main` and so contradicted it). The
        # status the verb ACTUALLY READ is the only honest discriminator, and it is already carried.
        # `force_admitted` is unchanged and keeps its real job: deciding which exits a message may name.
        _die(f"worktree park: REFUSED — {data['branch']} is `done` on main but its worktree carries "
             f"UN-LANDED WORK ({data['carries_work_why']}), so this is NOT the landed-done retirement — "
             f"the closure landed while the worktree kept working, which is the QUEUE §Prematurely-closed "
             f"shape. That `done` was read from {data.get('status_source', 'main’s task card')} (main's "
             f"checkout) — if that contradicts what you see, say so with the path, because a wrong "
             f"diagnosis here is otherwise indistinguishable from a right one (T-11526). The worktree at "
             f"{data['worktree']} and its branch are INTACT, and `--force` is NOT "
             f"admitted here. Finish it in place (`bin/yitc-v2 work commit` → `audit post --task "
             f"{data['task']} --reaudit-after-close` → `land`), recover a land that died mid-flight "
             f"(`bin/yitc-v2 worktree recover-land`), or escalate (`bin/yitc-v2 blocked-on-land "
             f"{data['task']} <reason>`). Re-run this park once the worktree is genuinely empty.")
    if data.get("parked") is False:
        _die(f"worktree park: REFUSED — {data['branch']} carries UN-LANDED WORK ({data['carries_work_why']}). "
             f"Tearing it down would destroy work no re-dispatch can re-derive: the 9-stage order commits "
             f"at Stage 7, so a worker holds its whole diff uncommitted across Execution and Tests "
             f"(T-11330; the 2026-08-19 T-11319 loss, X-0998 / X-1000). The worktree at {data['worktree']} "
             f"and its branch are INTACT. Land it (`bin/yitc-v2 land --task {data['task']}`), escalate it "
             f"(`bin/yitc-v2 blocked-on-land {data['task']} <reason>`, SPEC-0103 §3 — worktree intact), or "
             f"— if the work is genuinely disposable — re-invoke with `--force --reason <why>`.")
    # T-11414 — on the landed-done retirement nothing is DISCARDED (the work is on main and the guard
    # proved the worktree empty), so the volume is REMOVED, not discarded; the numbers are identical.
    _verb = "removed" if data["status_on_main"] == "done" else "discarded"
    _vol = (f"{_verb} {data.get('discarded_files')} working-tree entr"
            f"{'y' if data.get('discarded_files') == 1 else 'ies'} + "
            f"{data.get('discarded_commits')} commit(s) above main"
            + (f"; FORCED over {data.get('forced_over')}" if data.get("forced") else ""))
    print(f"worktree park: {data['branch']} torn down (reason: {data['reason']}; {_vol}); "
          f"worker_parked emitted")
    # T-11298 — the RECOVERY POINTER, on the operator's screen at the moment of loss and not only in
    # the journal. Printed only when commits were actually discarded, so the ordinary pre-Execution
    # park keeps its two-line output unchanged.
    _shas = data.get("discarded_commit_shas") or []
    if _shas:
        print(f"  RECOVERABLE: the discarded commits are still reachable by sha until the next gc — "
              f"head {_shas[0]}"
              + (f" (predecessors: {', '.join(_shas[1:])})" if len(_shas) > 1 else "")
              + f". Restore with `git checkout {_shas[0]} -- <path>` or `git branch "
                f"{data['branch']}-recovered {_shas[0]}`; the same shas are on the worker_parked row.")
    # The post-condition line MUST match the branch actually taken (T-10565): claiming "`ready` on main →
    # re-dispatchable" over a card-died teardown would be a FALSE statement about a discarded task.
    if data["redispatchable"]:
        print(f"  task {data['task']} is `ready` on main (its claim never landed) → cleanly re-dispatchable; "
              f"worktree removed + branch deleted, no orphan")
    elif data["status_on_main"] == "done":
        # T-11414 — the THIRD post-condition. Both existing lines would be FALSE here: the card is not
        # `ready` and nothing was discarded — its work is ON main.
        print(f"  task {data['task']} is `done` on main (claim, diff and closure all landed; the worktree "
              f"was clean and 0 ahead) → RETIRED, not re-dispatchable; worktree removed + branch deleted, "
              f"no orphan, and the retirement is on the journal instead of invisible")
    else:
        print(f"  task {data['task']} is `wont-do` on main (its card died under the worker; the claim never "
              f"landed) → DISCARDED, not re-dispatchable; worktree removed + branch deleted, no orphan")
    print(f"cd {main_wt}")



# ── the census-coverage pre-flight (T-11711) ─────────────────────────────────────────────────────
#: The SINGLE HOME of the journal-reader census coverage computation — its population, its driven
#: matrix and all three exemption registries. Both pinned census gates already read every one of
#: those from THIS module (`tests/test_t11449_reader_multiset_identity.py` imports it as `_a2`), so
#: the pre-flight below reads them from there too rather than growing a fourth reader of the same
#: facts. A re-implemented enumeration would drift from the gate it mirrors, and a pre-flight that
#: disagrees with the gate is worse than no pre-flight — it teaches operators to ignore it.
_CENSUS_HOME_RELPATH = "tests/test_t11444_segment_aware_readers.py"


def _load_census_module(repo_root):
    """Import the census single home out of `repo_root`, or None when it cannot be imported.

    Returns None in BOTH the not-applicable case (a consumer checkout has no such file) and the
    could-not-load case; the caller distinguishes them by asking whether the file EXISTS, so a
    consumer never sees a line about an engine-only gate while a broken import in the engine is
    reported rather than rendered as clean.
    """
    import importlib.util
    home = Path(repo_root) / _CENSUS_HOME_RELPATH
    if not home.exists():
        return None
    tests_dir = str(home.parent)
    added = tests_dir not in sys.path
    if added:
        sys.path.insert(0, tests_dir)
    try:
        name = "yitc_census_home_" + home.stem
        if name in sys.modules:
            return sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, home)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                      # noqa: BLE001 — report-only, never fatal
        sys.modules.pop("yitc_census_home_" + home.stem, None)
        return None


def _census_uncovered_readers(repo_root, *, _load_census=None):
    """The journal readers the census enumerates that NO coverage list covers, or None when the
    question could not be answered here.

    THE ANSWER IS THE CENSUS'S OWN, never a second copy: the population, the driven matrix and the
    three exemption registries are read off the single home, and the set expression is the same one
    both pinned gates compute. Building the matrix does NOT drive any reader — the matrix's third
    element is a callable this never calls — so the whole answer costs an import and a set
    difference: no test suite, no verify-admission slot, no queue position.
    """
    census = (_load_census or _load_census_module)(repo_root)
    if census is None:
        return None
    try:
        recorded = set(census.POPULATION)
        driven = {key for key, _ordered, _fn in census._reader_matrix(census.SLICE)}
        uncovered = (recorded - driven - set(census._AC2_DRIVEN)
                     - set(census._NOT_DRIVEN) - set(census._LOCK_EXEMPT))
    except Exception:                                      # noqa: BLE001 — report-only, never fatal
        return None
    return sorted(uncovered)


def _land_preflight_census_lines(repo_root, *, _uncovered=None, _home_exists=None):
    """The census-coverage phase's output lines — REPORT-ONLY, and that bound is the point.

    It NAMES an uncovered reader and refuses nothing: the pinned census gate at `land` is unchanged
    and remains the single enforcement point. What this removes is only the WAIT — a branch that
    adds a journal reader without covering it learns of it here, off-queue, instead of at the front
    of the land queue after paying a full verify (and, inside a batch, making its peers pay too).

    SAY WHICH SILENCE THIS IS, exactly as the currency phase does (T-11349): a clean tree and a
    phase that never ran are otherwise the same observable. The one silence that stays silent is
    NOT-APPLICABLE — a checkout with no census home has no such gate to be blocked on, so a line
    about it would be noise in every consumer.
    """
    uncovered = (_uncovered or _census_uncovered_readers)(repo_root)
    if uncovered is None:
        exists = ((Path(repo_root) / _CENSUS_HOME_RELPATH).exists() if _home_exists is None
                  else _home_exists(repo_root))
        if not exists:
            return []
        return ["  census-coverage pre-flight: SKIPPED — not run at all, so this line is NOT a "
                f"clean verdict: {_CENSUS_HOME_RELPATH} is present but could not be read here. "
                "Treat this branch's census coverage as UNKNOWN and expect `land` to judge it."]
    if not uncovered:
        return ["  census-coverage pre-flight: RAN and found no journal reader outside the census "
                "coverage lists — this branch is not currently blocked on the census gate."]
    lines = [f"  census-coverage pre-flight: {len(uncovered)} journal reader(s) enumerated by the "
             f"census that NO coverage list covers — the pinned gate ({_CENSUS_HOME_RELPATH}) will "
             f"RED on this at `land`. Cover each below (a driver in the matrix, or a recorded "
             f"exemption) while you are still OFF the queue. REPORT-ONLY: nothing here refuses."]
    lines += [f"      uncovered: {f}#{fn}" for f, fn in uncovered]
    return lines


def modified_pinned_tests_hint(name_status_text, *, limit=3) -> "str | None":
    """T-11801 — the PRE-FAILURE ASK: text for a branch that MODIFIES an existing `tests/` file, or
    None for one that does not. PURE: `git diff --name-status` text in, text out. No git, no I/O, no
    journal, no clock — so the caller's fail-open wrapper is a belt, not the only line of defence.

    WHAT IT IS FOR. `--expect-rebaseline` (T-11801) lets a branch declare a rebaseline with no waive
    token and no prior failure, so it can be verified alone instead of reddening a batch first. A
    flag nobody knows to type is an adoption gap (CHARTER §AI failure classes #17), so this OFFERS
    the declaration at `worktree sync` — the one seam that is both BEFORE the queue and already
    mandatory before a first land (T-11313).

    IT ASKS. IT NEVER EXCLUDES, AND THAT IS A MEASURED CONSTRAINT, NOT A STYLE CHOICE. Over 7 days
    and 283 branches carrying `land_member_verdict` rows (fu_74b26470c694) the predicate scored
    RECALL 94% (30 of 32 culprits), FALSE-POSITIVE 43% (69 of 161 non-culprits), PRECISION 30%.
    Acting on that by EXCLUSION would drop about half the queue and disable batching — the failure
    mode the external audit named as its FIRST finding
    (`decisions/prefailure-supersession-signal-audit-adhoc.yaml`, YELLOW). Acting on it by ASKING
    costs one question, and a wrong question costs nothing: no exclusion, no event, no durable mark.
    Nothing in the admission path reads this function, and no caller may branch on its result.

    WHY `M` AND NOT "TOUCHES tests/". The wider predicate is a CONSTANT in this repo — 16 of 16 live
    branches match — because SPEC-0165's loud-failure doctrine makes every card ship a tripwire. So a
    branch that only ADDS its own new test file (`A`) selects NOTHING, which is what keeps the hint
    off the branches that are merely doing their job. `R`/`D`/`C` are not selected either: a rename or
    a deletion supersedes no assertion this hint can speak to, and a confident wrong hint is worse
    than none (X-0685).

    SILENCE IS NOT PROOF, and the text says so. The signal MISSES source-only supersessions — a
    branch that breaks a pinned test WITHOUT touching it, because it changed the source that test
    greps. That case needs a pinned-test-to-source coverage map and is explicitly out of scope here,
    so this must never be read (or written up) as closing the circularity completely.

    FAIL-CLOSED ON MALFORMED INPUT: a line this cannot parse into `<status>\t<path>` selects nothing,
    rather than being guessed at."""
    hits = []
    for line in (name_status_text or "").splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 2:
            continue                       # unparseable — select nothing, never guess
        status, path = parts[0].strip(), parts[1].strip()
        # EXACTLY `M`. A status with a similarity score (`R100`, `C90`) or any other letter is a
        # different fact about the file and is deliberately not this hint's subject.
        if status == "M" and path.startswith("tests/"):
            hits.append(path)
    if not hits:
        return None
    out = ["NOTICE: this branch MODIFIES %d existing file(s) under tests/ (as opposed to only adding "
           "its own new one) — the available PRE-FAILURE hint that a change may supersede a pinned "
           "last-green assertion (T-11801, SPEC-0184 rule 4):" % len(hits)]
    for path in hits[:limit]:
        out.append(f"  {path}")
    if len(hits) > limit:
        out.append(f"  ... and {len(hits) - limit} more.")
    out.append(
        "  IF THIS CHANGE DOES SUPERSEDE A PINNED ASSERTION, say so NOW and you will be verified "
        "ALONE instead of reddening a batch and costing every peer a shared verify pass:\n"
        "    bin/yitc-v2 land --task T-XXXX --expect-rebaseline\n"
        "  That takes NO waive token and needs no prior failure, and it GRANTS NOTHING: the full "
        "candidate verify and the pinned last-green suite still run, and a pinned assertion that "
        "fails still REFUSES the land. You then read the authoritative token off your OWN solo "
        "refusal and re-land with --rebaseline — having cost no peer anything. It is attempt-scoped, "
        "so a later land that omits it is batched normally.")
    out.append(
        "  IF IT DOES NOT: land normally and ignore this. Nothing is recorded AGAINST this branch "
        "either way — this line EXCLUDES nothing, refuses nothing and changes no exit code, and "
        "nothing anywhere acts on it. T-11870: for the record, the sync row does now note WHETHER "
        "this phase spoke (`preflight.supersession_ask`, false when it did not) — so that whether "
        "the hint is worth keeping can be measured later. It is report-only: no gate reads it.")
    out.append(
        "  ADVISORY ONLY, AND A HINT RATHER THAN A VERDICT: measured over 283 branches in 7 days it "
        "is right about 3 times in 10 (recall 94%, false-positive 43%). It is deliberately never "
        "acted on by exclusion — at that precision doing so would drop about half the land queue and "
        "disable batching. And SILENCE HERE IS NOT PROOF: it cannot see a SOURCE-ONLY supersession, "
        "where a branch breaks a pinned test without touching the test at all.")
    return "\n".join(out) + "\n"

def _sync_supersession_ask_lines(W, branch, *, _run_git_cap) -> list:
    """T-11801 — `worktree sync`'s FOURTH report-only phase: the PRE-FAILURE ASK.

    THE GAP IT CLOSES. Batch formation already EXCLUDES a branch that has DECLARED a rebaseline, and
    `--expect-rebaseline` (T-11801) now lets a branch declare one with no waive token and no prior
    failure. What was still missing is that nobody knows to type it — an adoption gap (CHARTER §AI
    failure classes #17). This is the seam where the answer is worth having: `worktree sync` is
    already the mandatory pre-land preflight (T-11313), it runs BEFORE the branch takes a queue
    position or a verify-admission slot, and its three existing phases are already report-only prints.

    A PRINT, AND NOTHING ELSE. It returns LINES. It excludes nothing, refuses nothing, emits no
    event of its own and moves no exit code; `land`, `_land_batch_members` and every
    `_land_preflight_*` gate are untouched, and no admission path anywhere reads the predicate. That

    T-11870 — "AND WRITES NO DURABLE STATE" USED TO STAND IN THAT LIST, AND NO LONGER DOES. The
    CALLER now carries this phase's verdict as a boolean on the `worktree_synced` row it already
    writes (`preflight.supersession_ask` / `supersession_ask_measured`). This function is unchanged —
    it still returns lines and is still handed no emitter, which is a structural absence rather than
    a promise — but the sentence above described the SYSTEM, not just the function, so it would now
    be false as written. Amended deliberately, with the T-11801 AC4 guard, on an external adversarial
    consult (`decisions/T-11870-audit-consult-post.yaml`).
    WHAT THE AMENDMENT DOES NOT TOUCH is the part that matters: at 30% precision NOTHING may ACT on
    this hint, and nothing does. The record is report-only, no gate reads it, and for a branch the
    hint stays silent about, the recorded value is `false` — nothing against it. What it buys is the
    only thing that made the adoption question answerable: while the sole copy of the verdict was a
    terminal line, "did anyone see this hint, and did they act on it?" had no answer, and an
    unevaluable advisory is the shipped-but-never-adopted shape CHARTER §Principle 8 exists to catch.
    is a REQUIREMENT, not a posture: the hint's measured precision is 30% (recall 94%,
    false-positive 43%, 283 branches / 7 days, fu_74b26470c694), so excluding on it would drop about
    half the queue and disable batching — the external audit's first finding.

    THE JUDGEMENT LIVES IN ONE PLACE. The predicate and all of its text are
    `modified_pinned_tests_hint` just above, a pure function; this reads the diff and hands
    it over. A second inline copy of the predicate is exactly the drift CHARTER §P5 forbids.

    FAIL-CLOSED TO `[]`: no merge-base, a failing git call, or an unreadable diff all yield "say
    nothing" rather than a guess. The caller wraps this fail-open too — belt and braces, because an
    advisory heuristic must never be able to break a sync."""
    try:
        mb = _run_git_cap(["merge-base", "HEAD", "main"], W)
        base = mb.stdout.strip() if mb.returncode == 0 else ""
        if not base:
            return []
        d = _run_git_cap(["diff", "--name-status", base, "HEAD", "--", "tests/"], W)
        if d.returncode != 0:
            return []
        notice = modified_pinned_tests_hint(d.stdout)
    except Exception:      # noqa: BLE001 — advisory heuristic; never fatal to a sync
        return []
    return notice.rstrip("\n").splitlines() if notice else []


def _preflight_blocker_record(conflict_sink: "dict | None",
                             currency_lines: "list[str] | None",
                             census_lines: "list[str] | None" = None,
                             supersession_lines: "list[str] | None" = None) -> dict:
    """T-11697 — the pre-flight blocker set as DATA, for the `worktree_synced` payload.

    WHY IT EXISTS. The T-11313 pre-flight is PRINTS ONLY, so the blocker set the operator was shown
    existed for the length of one stdout write. T-11313's own AC4 asks whether a resumption cost ONE
    land attempt instead of one per blocker, and states the signal as zero `land_aborted` rows naming
    a blocker the preceding `worktree_synced` pre-flight had ALREADY REPORTED. No reader can make
    that join: the already-reported side has no durable record. This turns the set the operator saw
    into the set a later reader can read.

    IT IS A RENDERER, NOT A SECOND ORACLE. It computes nothing and asks nothing: both inputs are the
    values the two phases ALREADY produced on their way to stdout, handed in. So the journalled set
    is the printed set by construction — it cannot drift from what the operator was shown, which is
    the only property that makes the join trustworthy.

    THREE STATES PER PHASE, NOT TWO — the distinction the card's AC1 turns on. `absent` and `empty`
    must be distinguishable, so the key is ALWAYS present and carries an explicit empty set; the
    third state, MEASURED-vs-NOT, is what keeps the empty set honest:
      `conflict_sink is None`  — the phase did not run at all (the `behind == 0` path never probes
                                 for conflicts, because there is no merge to conflict).
      `conflict_sink == {}`    — it ran and COULD NOT ANSWER (fail-open).
      populated                — it answered; `unresolved` may legitimately be empty.
    The same for `currency_lines`: None = the phase was skipped (its injections were unavailable in
    this process), `[]` = it ran and reported no blocker, non-empty = a re-audit will be required.
    Without the `*_measured` pair a not-run phase and a clean phase would both journal `false`, and a
    later reader would count a silence as a clean verdict — the exact confusion T-11349 removed from
    this verb's STDOUT, kept out of its journal here for the same reason.

    ALL FOUR PHASES, NOT TWO (T-11870). The verb prints FOUR report-only phases and this record
    carried the first two. The census-coverage phase (`_land_preflight_census_lines`) and the
    pre-failure supersession ASK (`_sync_supersession_ask_lines`, T-11801) were print-and-discard:
    each verdict existed for the length of one stdout write, which is the very gap this record was
    built to close for the other two. That mattered most for the ask, whose whole purpose is an
    ADOPTION question — nobody knows to type `--expect-rebaseline` — and adoption is the one thing
    that cannot be measured from a stdout line nobody kept. Both are added on the SAME three-state
    terms as the pair above, so a phase that did not run and a phase that ran clean stay
    distinguishable, and the renderer property is preserved: these are still the values the phases
    ALREADY produced on their way to stdout, handed in, so the journalled set cannot drift from the
    set the operator was shown.
    STILL A RENDERER, STILL NOT A SECOND ORACLE — the two new arguments default to `None`, which
    journals `*_measured: false` (the phase did not run), so any caller that hands over neither is
    byte-identical to before and no not-run phase can read as a clean verdict.
    BOOLEANS, NOT THE LINES. What a later reader joins on is WHETHER a phase reported a blocker, the
    same shape `re_audit_required` already has; carrying the prose would put an advisory paragraph
    that is free to be reworded into an append-only record, where a wording change would read as a
    verdict change.
    """
    measured = isinstance(conflict_sink, dict) and "unresolved" in conflict_sink
    return {
        "conflicts": sorted((conflict_sink or {}).get("unresolved") or []),
        "conflicts_auto_resolvable": sorted((conflict_sink or {}).get("resolved") or []),
        "conflicts_measured": measured,
        "re_audit_required": bool(currency_lines),
        "re_audit_measured": currency_lines is not None,
        "census_blocked": bool(census_lines),
        "census_measured": census_lines is not None,
        "supersession_ask": bool(supersession_lines),
        "supersession_ask_measured": supersession_lines is not None,
    }


def _merged_main_tip(W: "Path", main_sha: str, *, _run_git_cap) -> str:
    """T-12020 (X-1242) — the main tip this worktree ACTUALLY MERGED, for the currency pre-flight to
    measure against. Returns `main_sha` unchanged whenever the derivation cannot be obtained.

    THE DEFECT THIS EXISTS FOR. `cmd_worktree_sync` snapshots `main_sha = git rev-parse main` at
    ENTRY, but `_update_from_main` merges the LIVE `main` ref (`git merge --no-edit main`). A sibling
    land that advances `main` inside that window makes the snapshot STALE — and the currency phase
    then measures the branch against a main tip it did NOT merge. Every path the newer main imported
    is (i) present in `_merged_tree_delta_paths`'s delta, because it differs from the STALE tip,
    (ii) new relative to the audited commit, and (iii) absent from the clean re-merge of the audited
    commit with that stale tip — so it lands in `own_post_audit` and FORCES A RE-AUDIT for content
    the branch never authored. Measured on kupiclub T-0579 (X-1242): one merge-imported
    `specs/SPEC-0065-*.yaml` cost an audit-post pass against the ceiling while
    `git diff main HEAD -- <path>` was EMPTY, and the run's 34 OTHER merge imports — the ones already
    in the snapshot — classified correctly. That asymmetry is the stale window, not a leg order.

    WHY `merge-base`, AND NOT A RE-READ OF `rev-parse main`. A re-read races too: `main` can advance
    again between the merge and the re-read, which just moves the window rather than closing it.
    `git merge-base HEAD main` is the NEWEST main commit CONTAINED IN HEAD, so a later advance of
    `main` cannot move it — the answer is race-free BY CONSTRUCTION rather than by timing. It is also
    an ancestor of HEAD BY DEFINITION, which is exactly the precondition `_merged_tree_delta_paths`
    fail-closed RAISES on, so this can never hand that helper a base it must reject. Same discipline
    the currency gate already states for `land` (T-10014: the main HEAD actually merged, never the
    live ref) — this brings `worktree sync` onto it, it does not invent a second rule.

    FAIL-SAFE, NEVER FAIL-OPEN. Every failure — git would not run, an unparsable or empty answer, a
    value that is not a sha — returns `main_sha`, i.e. TODAY'S EXACT BEHAVIOUR. The derivation can
    only ever narrow a false blocker; it can never widen an admission, because a base it could not
    prove is a base it does not use. Pure: never raises."""
    try:
        r = _run_git_cap(["merge-base", "HEAD", "main"], W)
    except Exception:                          # noqa: BLE001 — git could not run: keep the snapshot
        return main_sha
    if getattr(r, "returncode", 1) != 0:
        return main_sha
    tip = (getattr(r, "stdout", "") or "").strip()
    return tip if re.fullmatch(r"[0-9a-f]{7,64}", tip) else main_sha


#: T-12365 — the conflict-marker tokens, matched LINE-ANCHORED. A prose mention of the token inside a
#: paragraph (this module is full of them) is not a marker; a line that STARTS with one is.
_CONFLICT_MARKER_PREFIXES = ("<<<<<<< ", "=======", ">>>>>>> ")


def _merge_in_progress(W: "Path", *, _run_git_cap) -> bool:
    """T-12365 — is a merge IN PROGRESS in `W`? `MERGE_HEAD` resolves iff git is mid-merge.

    Pure; never raises. Any failure answers False, which routes the caller to its ordinary arm — the
    fail-safe direction, since the ordinary arm's own guards then apply unchanged."""
    try:
        return _run_git_cap(["rev-parse", "--verify", "--quiet", "MERGE_HEAD"], W).returncode == 0
    except Exception:                          # noqa: BLE001 — git could not run: not mid-merge
        return False


def _hand_resolved_merge_paths(W: "Path", *, _run_git_cap) -> "tuple[list, str]":
    """T-12365 — the set of paths THIS merge conflicted on, plus the SOURCE the answer came from.

    PRIMARY SOURCE IS GIT'S OWN RECORD, not a re-derivation. When a merge conflicts, `git merge`
    writes a `# Conflicts:` comment block into `MERGE_MSG` naming every conflicted path, and that
    block survives the operator's `git add` — which is exactly what makes it readable HERE, after the
    resolution, when the index no longer carries a single unmerged entry to read the set from. Using
    it means this function introduces NO second oracle: the set is the one git recorded for this very
    merge.

    THE FALLBACK IS A SUPERSET, DELIBERATELY. When the block is absent or unreadable (an older git, a
    hand-edited message, an unreadable git dir) the answer is the STAGED MERGE DELTA
    (`git diff --cached --name-only HEAD`) — every path this merge is about to commit. That is a
    strict superset of the conflicted set, so every check built on this answer becomes at least as
    STRICT, never less: the marker scan looks at more files, the unstaged-edit check covers more
    files. Degrading toward more scrutiny is the fail-closed direction.

    THE SOURCE IS RETURNED, NOT SWALLOWED, and it rides the journal row. A reader asking "which paths
    did a human resolve" must be able to tell the exact answer from the superset — otherwise the row
    would quietly claim precision it does not have on the fallback path.

    Resolves the message file via `git rev-parse --git-path MERGE_MSG`: a LINKED worktree's git dir is
    not `W/.git`, so a hardcoded path would read the wrong file (or none) for every worktree this verb
    actually runs in. Pure; never raises."""
    try:
        r = _run_git_cap(["rev-parse", "--git-path", "MERGE_MSG"], W)
        if r.returncode == 0 and (r.stdout or "").strip():
            mm = Path((r.stdout or "").strip())
            if not mm.is_absolute():
                mm = Path(W) / mm
            if mm.is_file():
                out, seen = [], False
                for ln in mm.read_text(encoding="utf-8", errors="replace").splitlines():
                    if ln.strip().lower().startswith("# conflicts:"):
                        seen = True
                        continue
                    if not seen:
                        continue
                    if not ln.startswith("#"):
                        break                  # the block ended — never read past it
                    p = ln[1:].strip()
                    if p:
                        out.append(p)
                if seen and out:
                    return (sorted(set(out)), "merge-msg")
    except Exception:                          # noqa: BLE001 — unreadable record ⇒ take the superset
        pass
    try:
        # `-z` rather than a line read: it is NUL-separated AND UNQUOTED, so a path with a space or a
        # non-ASCII byte arrives verbatim instead of in git's `"...\303..."` escaped form — which
        # would then match no blob and no pathspec. This module imports only stdlib (see its header),
        # so asking git not to quote is the right fix here, not importing an unquoter.
        d = _run_git_cap(["diff", "--cached", "--name-only", "-z", "HEAD"], W)
        if d.returncode == 0:
            return (sorted({q.strip() for q in (d.stdout or "").split("\0") if q.strip()}),
                    "staged-delta")
    except Exception:                          # noqa: BLE001
        pass
    return ([], "unavailable")


def _staged_conflict_marker_paths(W: "Path", paths, *, _run_git_cap) -> list:
    """T-12365 — the subset of `paths` whose STAGED content still carries a conflict marker.

    THE STAGED CONTENT, NEVER THE WORKING TREE. `git show :0:<path>` reads stage 0 of the index —
    which is precisely what the commit would record. Scanning the working tree instead would answer a
    question about a file that is not the one about to be committed, and the two differ exactly when
    the operator has an unstaged edit on top — the case the caller's own separate check is for.

    LINE-ANCHORED (`_CONFLICT_MARKER_PREFIXES`): a line that STARTS with a marker token. This module,
    the specs and the tests all discuss these tokens in prose, and a substring match would name every
    such file as a half-resolution.

    UNREADABLE CONTENT IS SKIPPED, NOT GUESSED AT — a binary blob or a failed read yields no claim in
    EITHER direction. That is a MISSED refusal, never a false one: the caller's remaining checks and
    `land`'s own conflict proof are both still ahead of it. Pure; never raises."""
    out = []
    for raw in paths or ():
        p = str(raw).strip()
        if not p:
            continue
        try:
            b = _run_git_cap(["show", f":0:{p}"], W)
        except Exception:                      # noqa: BLE001
            continue
        if getattr(b, "returncode", 1) != 0:
            continue
        try:
            for ln in (b.stdout or "").splitlines():
                if ln.startswith(_CONFLICT_MARKER_PREFIXES):
                    out.append(raw)
                    break
        except Exception:                      # noqa: BLE001 — undecodable ⇒ no claim either way
            continue
    return out


def cmd_worktree_sync(args: argparse.Namespace, *, _append_event, _die, _main_worktree,
                      _worktree_path_for_branch, _run_git_cap, _BOOKKEEPING_ALLOWLIST,
                      _is_yitc_session_state, _DERIVED_MERGE_ARTIFACTS,
                      _dedup_events, write_text_atomic, REPO_ROOT,
                      _classify_inert_paths=None, EVENTS_PATH=None,
                      _anchor_signature_of_text=None, _fold_trailing_bookkeeping=None, _land_preflight_conflict_lines=None, _land_preflight_currency_lines=None, _update_from_main=None,
                      _main_checkout_state_note=None, _no_main_worktree_detail=None) -> None:
    """`worktree sync (--task T-XXXX | --work <slug>)` — bring a writing worktree UP TO DATE with
    `main` IN PLACE, and stop there (T-10821, resolving X-0681).

    WHY IT EXISTS. SPEC-0094 / LIFECYCLE Stage-8(b) put the deploy seam BETWEEN audit-post and Stage-9
    closure, so a card recording `live_probe_passed` must deploy BEFORE it closes. A consumer that
    deploys the checkout it runs in then deploys its TASK BRANCH — and kupiclub's was 18 commits behind
    main, so that deploy would have shipped stale code for every file the task did not touch, reporting
    success while doing it. Before this verb the only two doors were a hand `git merge main` (the
    manual fallback kupiclub correctly recorded as a genuine gap) or a `land`, which integrates and
    then REMOVES the worktree the seam still needs.

    IT IS A SYNC, NOT A LAND — and that is the load-bearing property. This function contains no
    fast-forward, no `_with_repo_lock`, no verify, no `_land_integrate`, no `land_completed`, and no
    worktree teardown: it merges `main` INTO the branch and returns with the worktree intact. `main`
    is never written. That is a structural absence, not an assertion — and the paired probe checks
    main's sha is byte-identical across the call.

    NO SECOND IMPLEMENTATION. Both steps are the ones `land` already runs, called here directly:
    `_fold_trailing_bookkeeping` (land's step 1 — without it git refuses to merge over the locally
    modified `events.jsonl` every governed verb leaves behind) and `_update_from_main` (land's step 2 —
    the merge plus its fail-closed per-path auto-resolve classification). A second update-from-main
    would be exactly the parallel path CHARTER §Principle 5 forbids.

    ALREADY-CURRENT IS A CLEAN NO-OP, NOT AN ERROR: 0 commits behind -> say so, emit
    `worktree_synced{noop: true}`, exit 0, change nothing. Re-running the verb is always safe.

    `--resolved` — THE HAND-RESOLVED ARM (T-12365). The ordinary path above stops on a non-union
    conflict (`_update_from_main` aborts the merge; `land` refuses on the same class BEFORE the
    queue), and the resolution itself was RAW GIT: open the merge, edit, `git add`, `git commit` —
    done by hand three times on 2026-09-10 alone, each leaving NO journal row naming what was
    resolved. AGENTS §Verb-execution discipline forbids hand-doing what a verb covers; nothing
    covered this. This arm does, and it is an ARM of the verb that already owns the seam rather than
    a new verb (CHARTER §P1 F1).
    It runs INSIDE the worktree with the merge IN PROGRESS, after the operator resolved and staged:
    fail-closed checks (nothing unmerged, no conflict marker in the STAGED content, no unstaged edit
    on a resolved path — each refuses naming the path, commits nothing, emits nothing, and leaves the
    merge in place so nothing is lost) -> `git commit --no-edit`, i.e. git's OWN prepared merge
    message -> ONE `merge_resolved_by_hand` row -> the SAME conflict proof `land` runs, re-run and
    reported.
    TWO BOUNDS, both load-bearing. It RESOLVES NOTHING ITSELF — the resolution is the operator's, and
    automatic resolution of anything is explicitly out of scope. And it is NOT an audit-currency
    exemption: a hand resolution is AUTHORED CONTENT, so SPEC-0077 §3a demands the re-audit exactly
    as it did before this arm existed. The row makes the shift ATTRIBUTABLE, not excused.
    FAILURE ORDERING ACROSS THE COMMIT: the commit is the last act that can strand state; a failed
    emit exits NONZERO, prints no success line, names the commit and prints the paste-ready
    `event merge_resolved_by_hand` recovery; and the commit is never rolled back, because it carries
    work that exists nowhere else. The re-proof is report-only and three-state, so it can never be
    what claims completion. Raw git stays the recovery escape hatch (D-0054), never the primary path.

    IT IS ALSO THE RESUMED-LAND PRE-FLIGHT (T-11313). It already ran land's steps 1 and 2 and produced
    the real post-merge tree, so it is where the COMPLETE blocker set of a resumed land is computable
    without a reservation, a verify slot or an advance of main — and it now REPORTS that set instead of
    letting the operator discover it one wasted attempt at a time. Two phases, in this order and only
    this order: `_land_preflight_conflict_lines` BEFORE `_update_from_main` (so a merge that cannot run
    still yields ONE output naming every blocker, with the merge's own abort text following
    byte-identical), and `_land_preflight_currency_lines` AFTER it — including on the `behind == 0`
    no-op path, which is the T-11309 case. Both are PRINTS: no gate is added, removed, weakened or
    re-ordered, no exit code changes, no event changes, and `land` is untouched.

    A THIRD PHASE, on the same terms (T-11711): CENSUS COVERAGE, printed last on both paths. A
    branch that adds a journal reader without covering it in the census is refused by a PINNED gate
    at `land` — after the branch has queued and paid a full verify, and inside a batch after its
    peers paid too — yet the check itself is cheap enough to answer here (an import and a set
    difference; no suite run, no verify-admission slot). So it is answered here, from the census's
    OWN single home rather than a second copy of its enumeration, and it NAMES the uncovered reader
    and refuses nothing: report-only, the pinned gate stays the enforcement point.

    THE BLOCKER SET IS ALSO JOURNALLED (T-11697), on the existing `worktree_synced` row rather than a
    new event type: the phases above were prints only, so the set the operator was shown lasted one
    stdout write and T-11313's own AC4 join — did a `land_aborted` name a blocker this pre-flight had
    ALREADY REPORTED — had no already-reported side to join against. The `preflight` key carries what
    the phases already computed (see `_preflight_blocker_record`); it is always present, so an empty
    set is distinguishable from an absent one, and a phase that did not run is distinguishable from
    one that ran clean. The only behavioural consequence is that each `_append_event` moved BELOW the
    phases it records — same row, same path, same exit code.
    """
    task, work = getattr(args, "task", None), getattr(args, "work", None)
    # Defensive both/neither (argparse's mutually-exclusive group already enforces it) — mirrors
    # cmd_worktree_new / cmd_worktree_park's identical guard.
    if bool(task) == bool(work):
        _die("worktree sync: pass exactly one of --task T-XXXX or --work <slug>")
    if task and not re.fullmatch(r"T-\d{4,}", task):
        _die(f"worktree sync --task: invalid id {task!r} (expected T-NNNN)")
    branch = f"task/{task}" if task else f"work/{work}"

    W = _worktree_path_for_branch(branch)
    if W is None:
        _die(f"worktree sync: no linked worktree found on branch {branch!r} — nothing to sync. "
             f"Create one with `yitc-v2 worktree new --task T-XXXX` (or `--work <slug>`).")
    main_wt = _main_worktree(REPO_ROOT) or _main_worktree(W)
    if main_wt is None:
        # T-11619 (SPEC-0188 element 5 — RECIPIENT OF FAILURE) — the refusal is CORRECT and stays
        # exactly as it is; only what it TELLS the branch changes. This is the site where a detached
        # or moved shared main checkout is met FIRST: `worktree sync` is the pre-flight a worker runs
        # BEFORE its first land (T-11313), so the operator reaches this sentence one step earlier
        # than `cmd_land`'s twin, which T-11382 already fixed. Naming only what was MISSING sent the
        # branch hunting in its own diff for a state its own diff cannot cause.
        # THE SAME CLAUSE, not a second one: `_no_main_worktree_detail` is the land site's own
        # formatter, injected here by the T-11522 residue — so the two refusals cannot drift.
        # Message-only: the condition, the exit point and the fact that nothing is repaired on the
        # operator's behalf (no verb may fix a shared checkout it does not own) are untouched.
        detail = ""
        if _main_checkout_state_note is not None and _no_main_worktree_detail is not None:
            # FAIL-SOFT on an unwired process (the injections are optional kwargs, and a caller that
            # forgot them must still get the refusal, never a NameError instead of a diagnosis).
            # The blast-radius sentence rides WITH the detail and only with it: an unwired caller
            # then falls back to EXACTLY the pre-card bare refusal, byte for byte, so the fallback
            # adds nothing of its own to a message it could not diagnose (audit-post finding).
            detail = _no_main_worktree_detail(_main_checkout_state_note(W, _run_git_cap),
                                              verb="worktree sync") + \
                " Worktree intact, main untouched."
        _die("worktree sync: could not locate the main worktree (no worktree on refs/heads/main)"
             + detail)
    if W.resolve() == main_wt.resolve():
        # Structurally impossible for a `task/`/`work/` branch, but stated so the refusal is explicit
        # rather than a confusing merge-into-itself.
        _die("worktree sync: refusing to sync the main checkout onto itself — `main` IS the sync source.")
    # The same not-a-linked-worktree guard `land` applies, for the same reason: a merge run in the main
    # checkout would move `main` itself, which is precisely what this verb must never do.
    if _run_git_cap(["rev-parse", "--git-dir"], W).stdout.strip() == \
       _run_git_cap(["rev-parse", "--git-common-dir"], W).stdout.strip():
        _die(f"worktree sync: {W} is not a linked worktree — refusing.")
    head_branch = _run_git_cap(["symbolic-ref", "--quiet", "--short", "HEAD"], W).stdout.strip()
    if head_branch != branch:
        _die(f"worktree sync: worktree {W} is on {head_branch or 'a detached HEAD'!r}, not {branch!r} — "
             f"refusing to sync a worktree that is not on the branch you named.")

    # ── T-12365 — THE HAND-RESOLVED ARM ────────────────────────────────────────────────────────────
    # Placed HERE: after every worktree/branch validation above (all of which apply unchanged — the
    # linked-worktree guard, the not-the-main-checkout guard, the on-the-named-branch guard) and
    # BEFORE the behind-count, because the ordinary path cannot run at all with a merge in progress.
    resolved_arm = bool(getattr(args, "resolved", False))
    in_merge = _merge_in_progress(W, _run_git_cap=_run_git_cap)
    if resolved_arm and not in_merge:
        _die(f"worktree sync --resolved: no merge is in progress in {W} — nothing to finish. This arm "
             f"COMMITS a merge from main whose conflicts YOU have already resolved and staged; it "
             f"does not START one. To get INTO the merge, run `yitc-v2 worktree sync "
             f"{('--task ' + task) if task else ('--work ' + str(work))}` — it folds the trailing "
             f"bookkeeping and runs the merge (no raw git needed for that either). If it stops on a "
             f"non-union conflict, resolve the named files, `git add` them, and re-run this arm.")
    if in_merge and not resolved_arm:
        # The ordinary arm's own fail-closed guard: it would otherwise fold bookkeeping and merge on
        # TOP of an unfinished merge. It is also the arm's discovery surface — the operator holding a
        # half-finished merge is told the verb that finishes it, at the moment they are holding it.
        _die(f"worktree sync: a merge from main is IN PROGRESS in {W} — refusing to sync on top of it "
             f"(worktree intact, main untouched, your resolution untouched). If you have resolved the "
             f"conflicted files and `git add`ed them, finish the merge with the covering verb: "
             f"`yitc-v2 worktree sync --resolved "
             f"{('--task ' + task) if task else ('--work ' + str(work))}` — it records WHICH paths "
             f"you resolved on a `merge_resolved_by_hand` row instead of leaving a raw `git commit` "
             f"the journal never saw. To abandon the merge instead: `git merge --abort`.")
    if resolved_arm:
        merge_head = _run_git_cap(["rev-parse", "MERGE_HEAD"], W).stdout.strip()
        head_before = _run_git_cap(["rev-parse", "HEAD"], W).stdout.strip()
        conflicted, conflicted_source = _hand_resolved_merge_paths(W, _run_git_cap=_run_git_cap)

        # ── THE FAIL-CLOSED SET. Every check runs BEFORE the commit and before any emit, so a refusal
        # here commits nothing and emits nothing (AC2). None of them runs `merge --abort`: the
        # operator's resolution is content that exists nowhere else, so a refusal PRESERVES it and the
        # verb is simply re-runnable once the named path is fixed.
        unmerged = [q.strip() for q in
                    (_run_git_cap(["diff", "--name-only", "--diff-filter=U", "-z"], W).stdout or "")
                    .split("\0") if q.strip()]
        if unmerged:
            _die("worktree sync --resolved: the merge is NOT fully resolved — these path(s) are still "
                 "unmerged (resolve them, then `git add` each one):\n  " + "\n  ".join(sorted(unmerged))
                 + "\nNothing was committed and no `merge_resolved_by_hand` row was written; your "
                   "merge and your resolution are intact.",
                 abort_class="hand-resolution-incomplete")
        marked = _staged_conflict_marker_paths(W, conflicted, _run_git_cap=_run_git_cap)
        if marked:
            _die("worktree sync --resolved: a CONFLICT MARKER is still present in the STAGED content "
                 "of these path(s) — they were staged mid-resolution (edit them, then `git add` "
                 "again):\n  " + "\n  ".join(sorted(marked))
                 + "\nNothing was committed and no `merge_resolved_by_hand` row was written; your "
                   "merge and your resolution are intact.",
                 abort_class="hand-resolution-incomplete")
        # An UNSTAGED edit sitting on top of a staged resolution would silently commit LESS than the
        # operator resolved. Scoped to the previously-conflicted paths ONLY — an unrelated dirty file
        # is none of this arm's business and must never block it.
        if conflicted:
            dirty = [q.strip() for q in
                     (_run_git_cap(["diff", "--name-only", "-z", "--", *conflicted], W).stdout or "")
                     .split("\0") if q.strip()]
            if dirty:
                _die("worktree sync --resolved: these resolved path(s) carry UNSTAGED changes on top "
                     "of what is staged — committing now would record LESS than you resolved (`git "
                     "add` them, then re-run):\n  " + "\n  ".join(sorted(dirty))
                     + "\nNothing was committed and no `merge_resolved_by_hand` row was written; your "
                       "merge and your resolution are intact.",
                     abort_class="hand-resolution-incomplete")

        # ── THE COMMIT — the LAST act that can strand state (STEP 3a(a)). `--no-edit` takes the
        # message git ITSELF prepared for this merge, which is the same message the mechanical
        # `_update_from_main` path produces: no second message format is introduced.
        cc = _run_git_cap(["commit", "--no-edit"], W)
        if cc.returncode != 0:
            _die("worktree sync --resolved: could not commit the resolved merge (worktree intact, "
                 "main untouched, your resolution intact):\n" + (cc.stderr or cc.stdout or "").strip(),
                 abort_class="hand-resolution-commit-failed")
        merge_commit = _run_git_cap(["rev-parse", "HEAD"], W).stdout.strip()

        payload = {"branch": branch, "main_sha": merge_head, "merge_commit": merge_commit,
                   "head_before": head_before, "resolved": conflicted,
                   "resolved_source": conflicted_source, "worktree": str(W)}
        try:
            _append_event("merge_resolved_by_hand", task, payload)
        except Exception as e:                 # noqa: BLE001 — STEP 3a(b): FAIL LOUD, NEVER claim success
            # The commit is NEVER rolled back (STEP 3a(c)): it carries the operator's hand resolution,
            # content that exists nowhere else. Destroying unrecoverable work to make this verb look
            # atomic would be the worse failure — so instead the record is made RECOVERABLE in one
            # pasted command (`event` needs no worktree, D-0049) and the verb exits NONZERO without
            # printing its success line, so nobody is told this completed when it did not.
            _die("worktree sync --resolved: the merge WAS COMMITTED as " + merge_commit[:12] +
                 " but its `merge_resolved_by_hand` row could NOT be written: " + str(e) +
                 "\nThe resolution is safe — only its RECORD is missing. Recover it with (needs no "
                 "worktree, D-0049):\n  bin/yitc-v2 event merge_resolved_by_hand"
                 + (f" --task {task}" if task else "") + " --data "
                 # shlex-quoted, so the pasted argument reaches `event` as the JSON OBJECT itself
                 # (a double-quoted JSON-of-JSON form is readable by a shell too, but only after
                 # its escapes, and it lets `$`/backticks in a path expand — the auditor's finding).
                 + shlex.quote(json.dumps(payload, sort_keys=True))
                 + "\nThen re-run `land` as usual.",
                 abort_class="hand-resolution-unrecorded")

        print(f"worktree sync --resolved: merge from main COMMITTED as {merge_commit[:12]} on "
              f"{branch} (main {merge_head[:12]}). Worktree intact at {W}; main was NOT advanced — "
              f"this is a SYNC, not a land.")
        if conflicted:
            print(f"  resolved BY HAND ({len(conflicted)} path(s), recorded on this run's "
                  f"`merge_resolved_by_hand` row, source: {conflicted_source}):")
            for _p in conflicted:
                print(f"    {_p}")
        else:
            print("  no previously-conflicted path could be named (source: "
                  f"{conflicted_source}) — the row records the merge, not a path list.")

        # ── THE RE-PROOF — REPORT-ONLY and THREE-STATE (STEP 3a(d)). It is the SAME conflict proof
        # `land` runs before the queue, called directly — never a second checker — and it GATES
        # NOTHING here: `land` remains the enforcement point. A proof that could not RUN is stated as
        # unknown, never rendered as proved (the T-11349 say-which-silence-this-is discipline this
        # verb already applies to its currency phase).
        if _land_preflight_conflict_lines is not None:
            _sink: dict = {}
            _lines = _land_preflight_conflict_lines(
                branch, main_wt, task, _run_git_cap=_run_git_cap,
                _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS, _dedup_events=_dedup_events,
                EVENTS_PATH=EVENTS_PATH, _classify_inert_paths=_classify_inert_paths,
                _blockers_out=_sink)
            for ln in _lines:
                print(ln)
            if not _lines:
                print("  conflict re-proof: RAN and reported no blocker — the same check `land` runs "
                      "before the queue no longer refuses on the conflict you just resolved.")
        else:
            print("  conflict re-proof: SKIPPED — not run at all, so this line is NOT a clean "
                  "verdict: the phase's injected helper is unavailable in this process. Treat the "
                  "branch's merge-cleanliness as UNKNOWN and expect `land` to judge it.")

        print("  CUSTODY UNCHANGED: a hand resolution is AUTHORED CONTENT, so SPEC-0077 §3a still "
              "requires the re-audit it required before this verb existed. The row makes the shift "
              "ATTRIBUTABLE — it does not excuse it.")
        # `return None`, not a bare `return`: this arm is TERMINAL and sits ABOVE the ordinary path,
        # so a bare one would read as the already-current NO-OP path's return to anything scanning
        # this function top-down for it (tests/test_t11711_census_preflight.py splits the source on
        # exactly that token to prove the census pre-flight runs on the no-op path too). Same
        # semantics, unambiguous marker.
        return None
    # ── end of the hand-resolved arm ───────────────────────────────────────────────────────────────

    main_sha = _run_git_cap(["rev-parse", "main"], W).stdout.strip()
    head_before = _run_git_cap(["rev-parse", "HEAD"], W).stdout.strip()
    # BEHIND-count = commits reachable from main but not from this branch. This is the number the
    # X-0681 report is about (kupiclub's was 18).
    behind_out = _run_git_cap(["rev-list", "--count", "HEAD..main"], W)
    if behind_out.returncode != 0:
        _die(f"worktree sync: could not compute how far {branch} is behind main: "
             f"{behind_out.stderr or behind_out.stdout}")
    behind = int((behind_out.stdout.strip() or "0"))

    if behind == 0:
        # The PAIRED probe's no-op half — already current is a clean no-op, never a refusal, so the
        # verb is safe to run unconditionally at the deploy seam without first checking anything.
        # T-11697 — the append moved BELOW the pre-flight phases (it used to sit here): the row now
        # carries the blocker set those phases produce, so it cannot be written before they run. Same
        # row, same path, same exit code; only its position relative to stdout moved.
        print(f"worktree sync: {branch} is already current with main (0 commits behind) — nothing to "
              f"sync. Worktree intact at {W}.")
        # T-11349 — SAY WHICH SILENCE THIS IS. `_land_preflight_currency_lines` returns `[]` when
        # nothing is reportable, and the guard below skips the phase outright when an injection is
        # absent: both rendered as the ABSENCE of a line, so "measured and clean" and "never ran"
        # were the same observable and the docstring's promise that currency reports even here was
        # unfalsifiable from outside. One verdict line per branch, textually distinct. This is a
        # PRINT only — the currency gate computes exactly what it computed before, and `land` is
        # untouched.
        cur_lines = None                       # T-11697 — bound BEFORE the guard, the same shape the
                                               # merged path below uses. Both arms below assign it, so
                                               # this changes no behaviour; it removes the reader's
                                               # need to prove that from two branches (audit-post
                                               # finding, absorbed) and it fails SAFE if a future arm
                                               # is added: None journals re_audit_measured false — the
                                               # phase did not run — never a clean verdict it did not
                                               # earn.
        if _classify_inert_paths is not None and EVENTS_PATH is not None:
            # T-12020 — the SAME currency base as the merged arm below. Here `behind == 0` means main
            # is already an ancestor of HEAD, so this is PROVABLY `main_sha`; it is derived anyway so
            # ONE rule states the base for both arms, and so the line below names the sha actually
            # measured rather than a separately-read one that could drift from it.
            cur_base = _merged_main_tip(W, main_sha, _run_git_cap=_run_git_cap)
            cur_lines = _land_preflight_currency_lines(
                W, branch, cur_base, _run_git_cap=_run_git_cap, EVENTS_PATH=EVENTS_PATH,
                _classify_inert_paths=_classify_inert_paths,
                _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
                _anchor_signature_of_text=_anchor_signature_of_text)
            for ln in cur_lines:
                print(ln)
            if not cur_lines:
                print("  audit-currency pre-flight: RAN and reported no blocker (SPEC-0077 §3a "
                      "audited-diff currency, measured against main "
                      f"{cur_base[:12]}) — this branch is not currently blocked on a re-audit.")
        else:
            cur_lines = None                   # the phase was SKIPPED — not a clean verdict (T-11697)
            print("  audit-currency pre-flight: SKIPPED — not run at all, so this line is NOT a "
                  "clean verdict: the phase's injected helpers are unavailable in this process. "
                  "Treat the branch's audit currency as UNKNOWN and expect `land` to judge it.")
        # T-11870 — BOUND, not printed straight through: the record below carries these verdicts,
        # and binding them here is what keeps the journalled set the PRINTED set by construction.
        census_lines = _land_preflight_census_lines(REPO_ROOT)
        for ln in census_lines:
            print(ln)
        sup_lines = _sync_supersession_ask_lines(W, branch, _run_git_cap=_run_git_cap)
        for ln in sup_lines:
            print(ln)                       # T-11801 — the fourth phase; see the helper's docstring
        # No conflict phase runs here — there is no merge to conflict — so its sink is None, which
        # the record renders as conflicts_measured: false rather than as a clean empty set.
        _append_event("worktree_synced", task,
                      {"branch": branch, "behind_before": 0, "noop": True,
                       "main_sha": main_sha, "head_before": head_before, "head_after": head_before,
                       "worktree": str(W),
                       # T-11907 — present on BOTH paths, so an empty set always means "resolved
                       # nothing" and never "this arm forgot to say". A no-op ran no merge, so it
                       # can only ever be empty here.
                       "resolved": [], "resolved_kinds": {},
                       "preflight": _preflight_blocker_record(None, cur_lines,
                                                              census_lines, sup_lines)})
        return

    _fold_trailing_bookkeeping(W, branch, refuse_nonfoldable=False, msg_prefix="worktree sync",
                               _run_git_cap=_run_git_cap, _die=_die,
                               _BOOKKEEPING_ALLOWLIST=_BOOKKEEPING_ALLOWLIST,
                                 _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
                               _is_yitc_session_state=_is_yitc_session_state)
    conflict_sink: dict = {}                   # T-11697 — stays {} when the probe could not answer
    for ln in _land_preflight_conflict_lines(branch, main_wt, task, _run_git_cap=_run_git_cap,
                                             _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
                                             _dedup_events=_dedup_events, EVENTS_PATH=EVENTS_PATH,
                                             _classify_inert_paths=_classify_inert_paths,
                                             _blockers_out=conflict_sink):
        print(ln)
    # T-11907 — the RESOLUTION sink. `_update_from_main` already carries the fail-closed per-path
    # auto-resolve classification (the ONE admission authority), so `worktree sync` already RESOLVES
    # a mechanical conflict in place; what it could not do was SAY SO. The sink stays `{}` unless a
    # resolution was actually applied, so an absent key is distinguishable from an empty set — the
    # same distinction the `preflight` record makes.
    resolved_sink: dict = {}
    _update_from_main(W, label="worktree sync", _run_git_cap=_run_git_cap, _die=_die,
                      _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
                      _dedup_events=_dedup_events, write_text_atomic=write_text_atomic,
                      _anchor_signature_of_text=_anchor_signature_of_text,
                      _resolved_out=resolved_sink)

    head_after = _run_git_cap(["rev-parse", "HEAD"], W).stdout.strip()
    behind_after = int((_run_git_cap(["rev-list", "--count", "HEAD..main"], W).stdout.strip() or "0"))
    # T-11697 — the append moved BELOW the currency phase (it used to sit here), because the row now
    # carries a set the phase-2 verdict is half of, and phase 2 is judgeable only AFTER the merge.
    if resolved_sink.get("paths"):
        print(f"  merge conflict(s) RESOLVED mechanically by the governed verb on {branch} "
              f"({len(resolved_sink['paths'])} path(s)) — recorded on this run's `worktree_synced` "
              f"row, not hand-merged:")
        for _p in resolved_sink["paths"]:
            print(f"    {_p}  [{resolved_sink['kinds'][_p]}]")
    print(f"worktree sync: {branch} brought up to date with main IN PLACE — merged {behind} commit(s) "
          f"(main {main_sha[:12]}); now {behind_after} behind. Worktree intact at {W}.")
    print(f"  main was NOT advanced — this is a SYNC, not a land. Integrate with "
          f"`yitc-v2 land --task {task}`." if task else
          f"  main was NOT advanced — this is a SYNC, not a land. Integrate with "
          f"`yitc-v2 land --branch {branch}`.")
    cur_lines = None                           # None = the phase was SKIPPED, [] = ran and clean
    if _classify_inert_paths is not None and EVENTS_PATH is not None:
        # T-12020 (X-1242) — measure against the main tip `_update_from_main` ACTUALLY merged, NOT
        # the `main_sha` snapshot taken at entry: that merge takes the LIVE `main` ref, so a sibling
        # land inside the window leaves the snapshot stale and every path the newer main imported
        # reads as this branch's own unaudited content. See `_merged_main_tip`. `main_sha` is
        # UNCHANGED everywhere else it is used (the behind-count, the human line, the journal field)
        # — it still means "the main tip observed at sync entry".
        cur_base = _merged_main_tip(W, main_sha, _run_git_cap=_run_git_cap)
        cur_lines = _land_preflight_currency_lines(
                W, branch, cur_base, _run_git_cap=_run_git_cap, EVENTS_PATH=EVENTS_PATH,
                _classify_inert_paths=_classify_inert_paths,
                _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
                _anchor_signature_of_text=_anchor_signature_of_text)
        for ln in cur_lines:
            print(ln)
    census_lines = _land_preflight_census_lines(REPO_ROOT)   # T-11870 — bound; see the noop arm
    for ln in census_lines:
        print(ln)
    sup_lines = _sync_supersession_ask_lines(W, branch, _run_git_cap=_run_git_cap)
    for ln in sup_lines:
        print(ln)                           # T-11801 — the fourth phase; see the helper's docstring
    _append_event("worktree_synced", task,
                  {"branch": branch, "behind_before": behind, "behind_after": behind_after,
                   "noop": False, "main_sha": main_sha, "head_before": head_before,
                   "head_after": head_after, "worktree": str(W),
                   # T-11907 (AC3) — the paths this sync RESOLVED, on the existing row rather than a
                   # new event type. Always present, so "resolved nothing" is distinguishable from
                   # "a version that did not record it"; the branch is already on the row beside it.
                   "resolved": resolved_sink.get("paths", []),
                   "resolved_kinds": resolved_sink.get("kinds", {}),
                   "preflight": _preflight_blocker_record(conflict_sink, cur_lines,
                                                          census_lines, sup_lines)})



def _sandbox_prefix_arg(argv, glob: str = _SANDBOX_PREFIX_GLOB) -> "str | None":
    """T-10857 — the SOLE identification of a verify-sandbox process: the value of a `-p` option (either
    `-p <path>` or the joined `-p<path>`) whose path matches `glob`; None when there is none.

    POSITIVE-DISCRIMINATOR by construction (`lessons/carving-an-exception-into-a-fail-closed-gate.md` §1,
    inverted for a KILL path): a process is selected only by what it POSITIVELY carries, never by failing
    to look like something we meant to spare. The process NAME / comm / exe is NEVER read — so a HOST
    nginx, which carries no sandbox prefix, is untouchable by CONSTRUCTION rather than by a denylist that
    a rename or a new binary could slip past. Element-matching (not a flattened `pgrep -f` line) keeps a
    prefix that merely appears INSIDE some other argument from ever being read as this process's own.

    THE SETPROCTITLE SHAPE (T-11088 — why the element scan ALONE reaped nothing in production). nginx
    rewrites its argv AREA with a status title, so `/proc/<pid>/cmdline` for a real sandbox master is ONE
    NUL-FREE blob — measured verbatim on the host:
        `nginx: master process /usr/sbin/nginx -p /tmp/yitc-verify-sandbox-<id>/box<N>/tmp/tmp<X>/sb -c …`
    `_scan_procs` NUL-splits that into a SINGLE element, so no element ever equals `-p` and the scan above
    returns None for every one of them: the shipped reaper reported `0 orphan sandbox process(es)` while 13
    such orphans (PPID=1, up to 4.1 days old) were alive. T-10857's probe passed anyway because it planted
    its fixture with a NORMAL argv, which /proc records as separate elements — it reproduced the ARGUMENT
    but not the SHAPE (`lessons/a-synthetic-probe-must-reproduce-the-production-shape.md`).
    So the same `-p`+glob predicate is ALSO applied to argv[0] tokenized on whitespace. Bounded to argv[0]
    DELIBERATELY: a title rewrite overwrites the argv area starting at argv[0], while a genuine
    multi-element argv keeps its own elements — so a dispatched worker whose whole preamble is one element
    (argv[6], not argv[0]) is still never tokenized, and the E-0035 / T-10053 flattened-scan false-positive
    class stays shut. The discriminator is unchanged in kind: still a POSITIVE `-p` VALUE matching the
    sandbox glob, still never the process name."""
    import fnmatch as _fnmatch

    def _scan(elements) -> "str | None":
        for i, a in enumerate(elements):
            val = None
            if a == "-p" and i + 1 < len(elements):
                val = elements[i + 1]
            elif a.startswith("-p") and len(a) > 2:
                val = a[2:]
            if val and _fnmatch.fnmatch(val, glob):
                return val
        return None

    hit = _scan(argv)
    if hit is not None:
        return hit
    if argv and len(argv[0].split()) > 1:
        return _scan(argv[0].split())
    return None



def _sandbox_resident_root(path, glob: str = _SANDBOX_PREFIX_GLOB) -> "str | None":
    """T-11088 — the SANDBOX ROOT `path` lives under, or None when it lives under none.

    Walks the ancestors SHALLOWEST-FIRST and returns the first that matches `glob`, so the answer is the
    ROOT and not some deeper directory: `fnmatch`'s `*` crosses `/`, so `<root>/box1/tmp/x/sb` matches the
    glob just as well as `<root>` does — walking deepest-first would return the path itself and the fence
    below would be no wider than the `-p` value it is meant to widen. Two callers, both
    fail-OPEN (a match means SPARE / REPORT, never kill): the Category-C occupancy fence, which must fence
    on the ROOT rather than on the deep `-p` value (a RUNNING verify's fleet sits at
    `<root>/box<N>/tmp/tmp<X>/…`, NOT inside the nginx `-p` dir `<root>/…/sb`, so a root-blind check finds
    no holder and leaves an ACTIVE run protected by the age floor alone); and the unclassified-resident
    report below."""
    import fnmatch as _fnmatch
    if not path:
        return None
    p = Path(path)
    for cand in (*reversed(p.parents), p):
        s = str(cand)
        if _fnmatch.fnmatch(s, glob):
            return s
    return None



def _sandbox_root_absent(root, *, stat_of=os.stat) -> bool:
    """T-11217 — is sandbox ROOT `root` PROVABLY gone from disk? The ONE signal that turns a
    report-only sandbox resident into a reapable orphan, so it has to answer "provably absent", never
    "I could not tell".

    THE THREE-VALUED REALITY (`lessons/carving-an-exception-into-a-fail-closed-gate.md` §1, the
    KILL-path inversion). A directory query has three outcomes, not two: PRESENT, provably ABSENT, and
    COULD-NOT-TELL (an EACCES on a parent, an EIO, an ESTALE on a dead NFS mount). Only ABSENT may open
    the exception. `os.path.exists()` is exactly the bypass that lesson names — it collapses ABSENT and
    COULD-NOT-TELL into one `False`, so OUR OWN plumbing failing would read as "reap it", and a /tmp we
    momentarily cannot stat would turn every burner on the host into a target. Hence the hand-written
    prover: only ENOENT / ENOTDIR — the kernel POSITIVELY saying "there is no such path" — returns True.
    Every other OSError returns False and the process is spared and merely reported, which is the
    fail-closed direction for a kill.

    WHY ABSENCE IS PROOF AND NOT A GUESS (the card's whole argument). A verify sandbox root is an
    `mkdtemp` created at run start and `rmtree`d at the END of `_run_verify_tests` — after the tests
    have finished and, since T-11206/T-11231, after that run's own residents have been reaped. So for
    the entire window in which a run has live children, its root EXISTS. A process still resident under
    a root that is GONE therefore cannot be serving a live run: it is a survivor, by construction. That
    is a positive fact about the world, unlike the cwd-shape guess the owner's fence rightly forbids.

    `stat_of` is the injection seam the COULD-NOT-TELL arm is tested through (a real EACCES is awkward
    to stage as the same uid that owns /tmp)."""
    if not root:
        return False
    try:
        stat_of(str(root))
    except (FileNotFoundError, NotADirectoryError):
        return True                  # the kernel POSITIVELY says there is no such path.
    except OSError:
        return False                 # COULD-NOT-TELL → spare. Never a kill on our own plumbing fault.
    return False



def select_orphan_sandbox_procs(procs, *, retention_sec: float, globs, self_pid: int, uid: int,
                                age_of=None, age_label: "str | None" = None, absent_of=None,
                                orphan_retention_sec: "float | None" = None,
                                orphan_age_label: "str | None" = None, _proc_start_age_sec=None, _sandbox_prefix_arg=None, _sandbox_resident_root=None, _sandbox_root_absent=None) -> dict:
    """T-11089 — THE orphan-sandbox-process predicate, in ONE place: given a `/proc` snapshot, decide
    which processes are orphan sandbox holders, which are spared and why, and which are unclassifiable
    residents. PURE SELECTION — it opens nothing, signals nothing, and removes nothing.

    WHY IT IS A FUNCTION AND NOT AN INLINE BLOCK (the card's acceptance criterion). This selection was
    inline in `cmd_worktree_sweep`'s Category C, where it had exactly one caller — the REAPER. The
    nightly's host-sandbox axis (`nightly._check_host_sandbox`) is a SECOND reader of the same
    population, and it exists precisely because the reaper failed SILENTLY: for four days `worktree
    sweep` printed `0 orphan sandbox process(es)` while 16 were alive (T-11088). A belt that answers
    "how many orphans are there?" with its OWN copy of the predicate would be free to drift from the
    reaper's, and then the two numbers disagree with nobody able to say which is right. So the reader
    and the reaper resolve to the SAME function object; `nightly._orphan_selector()` returns THIS
    function, and the T-11089 suite asserts that identity rather than resemblance.

    WHAT IS SHARED AND WHAT IS NOT. The predicate — identity (`_sandbox_prefix_arg`, the POSITIVE `-p`
    value; never a process name), the age fence, the uid fence, and the `_sandbox_resident_root`
    ACTIVE-RUN occupancy fence — is shared and unchanged. The COHORT is a parameter: `globs` is a
    tuple, applied one pattern at a time (first match wins), so the sweep passes its single
    `_SANDBOX_PREFIX_GLOB` and keeps a byte-identical KILL cohort, while the nightly passes the full
    derived tmp cohort (incl. `yitc-pinned-verify-*`) and REPORTS wider than the reaper reaps. That
    asymmetry is deliberate and safe in one direction only: reporting a class nobody reaps is the whole
    point of a belt; reaping a class nobody vetted is not, which is why widening lives at the call site
    and never in the fences.

    THE ONE CARVE-OUT IN THE RESIDENT REPORT (T-11217). The `residents` fence above spares a
    no-`-p` process because from OUTSIDE, cwd alone cannot tell a survivor of a finished run from a
    live verify's own child — and selecting on cwd would put every child of a live verify one guard
    away from a kill. There is exactly ONE signal that removes that ambiguity without guessing at
    identity: the process's own sandbox ROOT IS GONE FROM DISK (`_sandbox_root_absent` — provably
    absent, never merely unstatable). A root is removed only at the END of the run that made it, so a
    process still resident under a vanished root cannot be serving anything. Those become
    `orphan_residents`, and NOTHING else moves: a resident whose root is still present, or whose
    absence cannot be PROVEN, stays report-only exactly as before. The carve-out is strictly NARROWER
    than the population it is taken from — it inherits the age, uid, self-pid and ACTIVE-RUN holder
    fences unchanged — so the "widening can only ever SPARE more, never kill more" property still
    holds for every untouched case. MEASURED: on 2026-08-17 two orphaned burner trees survived 68 and
    65 minutes past their sandbox removal and four more had pinned four of this box's 32 cores for
    19–20 hours; all were visible here, all were spared, and all were cleared by hand because no verb
    would take them (T-11087 / E-0059).

    TWO AGE FLOORS, CHOSEN BY ONE FACT, FOR BOTH COHORTS (T-11234, widened to the resident cohort by
    T-11538). `retention_sec` is the shared floor and stays the default for everything.
    `orphan_retention_sec` — when a caller supplies it — is a
    SHORTER floor applied to a candidate whose sandbox ROOT is PROVABLY GONE
    (`_sandbox_root_absent` on the resolved root, never on the raw `-p` value, and never on a merely
    unstatable path). The split is what the classes' evidence actually supports: for a leaked temp
    DIRECTORY age is essentially the only abandonment signal, so its long floor is prudent, while a
    PROCESS whose own sandbox root has vanished is orphaned POSITIVELY, from that moment. A candidate
    whose root still EXISTS keeps the shared floor unchanged, because for it age IS still the only
    evidence. Omitting the parameter reproduces the pre-T-11234 behaviour EXACTLY, which is how the
    nightly belt (`nightly._check_host_sandbox`, the second reader of this predicate) stays
    byte-unaffected while continuing to resolve to this same function object.

    WHAT THE SHORT FLOOR REACHES, AND WHAT IT STILL DOES NOT (T-11538, closing followup
    fu_60d56377f43b). It reaches BOTH cohorts: the `-p` class and the identity-less RESIDENT class
    below (the T-11217 carve-out, selected on the cwd-root fact rather than a `-p` value). T-11234
    opened it for the `-p` class alone on SCOPE grounds — the resident cohort was the sibling card's
    axis — and recorded the widening as a followup rather than doing it there; that fence is now
    lifted deliberately, by this card, and only because the same proven-orphan argument applies to
    that cohort verbatim on the merits. What the short floor STILL does not reach is anything whose
    orphanhood is not PROVEN: a root that still exists, a root that is merely unstatable, or a
    process under no resolvable root at all keeps the shared floor in EITHER cohort. That is the
    fence that matters — proven absence, never the class — and it is asserted in both directions by
    probes, not merely intended.

    THE ABANDONED-BUT-LIVE ANSWER, AND ITS REASON (T-11701 — the question this predicate had never
    actually answered). Is a process whose owning run is long GONE but which is still ALIVE an orphan?
    THE ANSWER IS: YES, EXACTLY WHEN ITS ORPHANHOOD IS PROVEN — its own resolved sandbox ROOT is
    provably gone from disk — AND NOT OTHERWISE. Neither always-reap nor never-reap. LIVENESS OF THE
    PROCESS IS NOT EVIDENCE OF AN OWNER; PRESENCE OF THE ROOT IS. This is not a new rule: it is the
    same discriminator `_floor_for` and the T-11217 resident carve-out already turn on, finally applied
    to the one arm that was still exempt from it.

    WHAT WAS EXEMPT, AND THE MEASUREMENT THAT EXPOSED IT. The ACTIVE-RUN fence (`_holder`, T-11088)
    spares on TWO signals: a live process whose CWD is under the watched root (OCCUPANCY), and a live
    process that merely NAMES the root in its ARGV (a REFERENCE). Against a root that still EXISTS both
    are real evidence of an owner. Against a root that is provably GONE the argv arm is evidence of
    NOTHING, and it does not merely fail to help — it FIRES, permanently, because the reasons people
    write a sandbox path down outlive the sandbox. MEASURED 2026-08-29: pid 1685044 had been alive
    11 days 6 hours under `-p /tmp/yitc-verify-sandbox-t11234live-gone6/box1/tmp/tmpF/sb`, a fixture
    process whose root vanished with the test that made it. Every one of ~530 half-hourly sweeps found
    it and spared it, and running the predicate against a live `/proc` snapshot named the holder: a
    dispatched worker carrying THE TASK CARD ABOUT THIS VERY PROCESS in its argv. The card describing
    the orphan was keeping the orphan alive; a `grep`, a `ps`, a dispatch brief or an operator's own
    shell history does the same. So the predicate did not answer "no" to the abandoned-but-live
    question — it answered "spared by a READER", which is not an answer about ownership at all.

    THE CONSEQUENCE FOR THE RESIDENT COHORT, STATED RATHER THAN LEFT TO BE FOUND. For the T-11217
    identity-less cohort the mention arm was the ONLY holder signal that could fire at all: a live
    process whose cwd is under the gone root is a CO-RESIDENT and is deliberately subtracted by
    `except_pids`, and a process outside the root cannot reference it any other way. So under this
    decision `_holder` is VACUOUS for that cohort. The call is KEPT rather than deleted — both cohorts
    must keep resolving the question through the one expression, or the two definitions AC3 forbids
    grow back the first time the rule changes — but nobody should later read the empty fence as an
    oversight. It is sound because that cohort never rested on the fence: what stands between its
    decision and a signal is proven absence of the RESOLVED root, the age floor, the uid fence, and
    `_reap_proc`'s cwd-root RE-PROOF taken immediately before the kill. The `-p` cohort, where a
    non-co-resident occupant CAN exist, keeps a live occupancy arm.

    THEREFORE, IN ONE EXPRESSION FOR BOTH COHORTS (`_argv_mention_counts`, deliberately the same shape
    as `_floor_for`): when the watched root is PROVABLY ABSENT, an argv MENTION no longer counts as a
    holder. Everything else is untouched — the CWD arm, the age floors, the uid fence, the self-pid and
    `candidate_pids` exclusions, the `except_pids` co-resident subtraction, and the fail-OPEN direction
    (a hit still means SPARE, never kill). The argument is the resident cohort's own, verbatim: a live
    run's root EXISTS BY CONSTRUCTION, so nothing that references a vanished root can be the active run
    the fence protects. And the proof obligation is unchanged and load-bearing: `absent_of` must PROVE
    absence on the RESOLVED root. A root that still exists, a root that is merely UNSTATABLE, and a
    `-p` value under no resolvable root at all ALL keep the FULL fence, argv arm included — so a sandbox
    under a LIVE verify (T-11088's whole purpose) is still left completely alone, and this can only ever
    reach a process already proven orphaned. That pairing is the differential the suite asserts in both
    directions: a predicate widened to always-reap passes the reap case and FAILS the live-run case.

    Returns `{"candidates": [(pid, prefix, age)], "skipped": [(label, reason)],
    "residents": [(label, reason)], "orphan_residents": [(pid, root, age)]}` — `candidates` is the
    unchanged `-p` kill cohort (byte-identical to before T-11217, which is what keeps the nightly's
    reading of it comparable); `skipped` carries each spare with its reason, in the sweep's original
    wording (`age_label` supplies the "< Nh" text so the sweep's output is unchanged); `residents` is
    the fail-open report of sandbox-RESIDENT processes carrying no `-p` identity, which are never
    killed on a guess; `orphan_residents` is the one carve-out above, reaped by `_reap_proc`'s
    `cwd_root` re-proof rather than by the `-p` one. They are SEPARATE keys and not one list because
    the two classes are re-validated at the signal by different positive facts — folding them would
    either lie in the sweep's printed `[-p …]` line or abort every new reap at re-validation."""
    age_of = age_of or _proc_start_age_sec
    absent_of = absent_of or _sandbox_root_absent
    globs = tuple(globs)
    label = age_label if age_label is not None else f"{retention_sec / 3600:.1f}h"
    # T-11234 — both default to the shared floor, so a caller that passes neither (the nightly belt)
    # gets byte-identical behaviour and there is no second floor to reason about.
    orphan_sec = retention_sec if orphan_retention_sec is None else float(orphan_retention_sec)
    if orphan_age_label is not None:
        orphan_label = orphan_age_label
    elif orphan_retention_sec is None:
        # NO second floor was supplied, so there is no second LABEL either: reuse the caller's own
        # `label` verbatim. Deriving one here would silently reword an existing caller's skip reason
        # ("24.0h" -> "24.00h") — the collapse has to be total, not merely numeric (caught by
        # test_omitting_the_process_floor_reproduces_the_pre_change_predicate).
        orphan_label = label
    else:
        orphan_label = f"{orphan_sec / 3600:.2f}h"

    def _prefix(argv):
        for g in globs:
            hit = _sandbox_prefix_arg(argv, g)
            if hit:
                return hit
        return None

    def _root(path):
        for g in globs:
            hit = _sandbox_resident_root(path, g)
            if hit:
                return hit
        return None

    def _floor_for(root):
        """WHICH AGE FLOOR APPLIES, in ONE expression for BOTH cohorts (T-11538).

        The rule is T-11234's and is unchanged: a sandbox process whose own resolved ROOT is PROVABLY
        GONE from disk is orphaned POSITIVELY from that moment, so it takes the SHORT floor; anything
        whose root still EXISTS — or whose absence cannot be PROVEN, or that lies under no resolvable
        root at all — keeps the SHARED floor, because for it age is still the only evidence.

        What T-11538 changed is not the rule but WHERE it is applied. T-11234 opened it for the `-p`
        cohort only and fenced itself out of the identity-less RESIDENT cohort on scope grounds
        (carried as followup fu_60d56377f43b), so the two populations disagreed about the same fact.
        Lifting the choice into one helper called from both loops is what makes that a single rule
        rather than two thresholds — a second tunable for the resident class would have been exactly
        the accretion CHARTER §Principle 1 forbids. `absent_of` is still the ONLY thing that can
        shorten a wait, and it is still read on the RESOLVED root, never on a raw `-p` value.

        The collapse property is preserved verbatim: a caller supplying no `orphan_retention_sec`
        gets `orphan_sec is retention_sec` and `orphan_label is label`, so BOTH branches return the
        same pair and the pre-T-11234 predicate is reproduced exactly — including its wording."""
        if root is not None and absent_of(root):
            return (orphan_sec, orphan_label)
        return (retention_sec, label)

    def _argv_mention_counts(root) -> bool:
        """DOES AN ARGV MENTION OF `root` STILL COUNT AS AN ACTIVE-RUN HOLDER? (T-11701.)

        The SAME shape and the SAME discriminator as `_floor_for` above — proven absence of the
        RESOLVED root, never the cohort, never a raw `-p` value, never a merely-unstatable path — so
        the two questions the predicate asks about a vanished root ("which floor?" and "does a
        reference still spare?") are answered by ONE fact rather than drifting apart. A second knob
        for this would have been exactly the accretion CHARTER §Principle 1 forbids.

        Returns False ONLY for a root PROVEN gone. `root is None` (no resolvable root) returns True,
        which is what keeps the fence FULL for every shape whose orphanhood is not established."""
        return not (root is not None and absent_of(root))

    skipped: list = []
    residents: list = []
    orphan_residents: list = []
    candidates = []
    for pr in procs:
        if pr.get("pid") == self_pid:
            continue
        pref = _prefix(pr.get("argv") or [])
        if pref:
            candidates.append((pr, pref))
    candidate_pids = {pr.get("pid") for pr, _ in candidates}

    def _holder(watched: str, *, except_pids=frozenset(), argv_arm: bool = True) -> "int | None":
        """The ACTIVE-RUN occupancy fence, in ONE place (T-11217 factored it out of the `-p` loop so
        the new orphan-resident class inherits the IDENTICAL check rather than growing a second copy
        free to drift). Returns the pid of a live process referencing `watched` — by argv substring or
        by cwd at/under it — or None. Fail-OPEN: a hit means SPARE, never kill.

        `except_pids` — WHO CANNOT COUNT AS A HOLDER — is where the two cohorts legitimately differ,
        and it is load-bearing in both directions.
          · The `-p` cohort passes nothing extra: its candidates are already excluded via
            `candidate_pids`, so a candidate never spares itself.
          · The RESIDENT cohort must exclude the judged pid AND its CO-RESIDENTS under the same root,
            which is not an optimisation but the card's whole population. The `pre_burn.py` orphans
            come in PAIRS sharing one sandbox root (measured 2026-08-17: two orphaned burner TREES).
            Judged against each other they are mutual holders, the fence reads true for both, and the
            carve-out silently spares exactly the processes it was written to take — a dead branch
            that still passes every refusal arm. This exclusion is sound ONLY because the resident
            cohort has already established the root is provably GONE: a live run's root exists by
            construction, so no process sitting inside a vanished root can be the active run the
            fence protects. What the scan still catches there — and the reason it is not simply
            skipped — is an OUTSIDE process that NAMES the root in its argv (a verify mid-teardown,
            an operator's own command) — real evidence of an owner WHEN THE ROOT STILL EXISTS, and gated
        on exactly that by `argv_arm` since T-11701.

        `argv_arm` — WHETHER A MENTION IS EVIDENCE — is supplied by `_argv_mention_counts` at both call
        sites and is False only for a root PROVEN gone. It disables the MENTION arm alone; the CWD
        arm, the exclusions and the fail-open direction are identical either way, so switching it off
        can never spare LESS than occupancy already would, and can never reach a root that still
        exists. See the DECISION section of the enclosing docstring for why a mention of a vanished
        root is evidence of nothing."""
        root = watched.rstrip("/") + os.sep
        for other in procs:
            opid = other.get("pid")
            if opid in candidate_pids or opid == self_pid or opid in except_pids:
                continue
            ocwd = other.get("cwd") or ""
            if argv_arm and any(watched in a for a in (other.get("argv") or [])):
                return opid
            if ocwd == watched.rstrip("/") or ocwd.startswith(root):
                return opid
        return None

    selected = []
    for pr, pref in candidates:
        pid = pr.get("pid")
        age = age_of(pid)
        # The ACTIVE-RUN fence: watch the sandbox ROOT (T-11088), falling back to the `-p` value when the
        # prefix lies under no root at all (an injected test glob, or a shape we cannot resolve).
        # HOISTED ABOVE THE AGE FENCE by T-11234 (a pure computation, so the move changes nothing on its
        # own) because WHICH age floor applies is now a question about the root.
        root = _root(pref)
        watched = root or pref
        # T-11234 — the class-specific floor, and it is opened by a POSITIVE fact only. The resolved
        # ROOT must exist as a concept (`_root` matched) AND be provably gone from disk; a `-p` value
        # that lies under no root at all, or a root that is merely unstatable, falls back to the shared
        # floor. So this can only ever shorten the wait for a process already PROVEN orphaned, never
        # reach one whose sandbox is still there.
        # T-11538 — that decision is now `_floor_for`, the SAME expression the resident loop below
        # calls. This branch is behaviourally unchanged; it stopped being the only place the rule lives.
        floor, floor_label = _floor_for(root)
        if age < floor:
            skipped.append((f"pid {pid}", f"sandbox process too young ({age / 3600:.1f}h < {floor_label})"))
            continue
        if pr.get("uid") != uid:
            skipped.append((f"pid {pid}", f"sandbox process owned by uid {pr.get('uid')} (not this user) — never signalled"))
            continue
        # T-11701 — `watched` is the resolved ROOT when one resolved, else the raw `-p` value; the
        # helper returns True for the latter (nothing proven), so that shape keeps the FULL fence.
        holder = _holder(watched, argv_arm=_argv_mention_counts(root))
        if holder is not None:
            skipped.append((f"pid {pid}", f"sandbox {watched} still referenced by live pid {holder} "
                                          f"(ACTIVE run — never touched)"))
            continue
        selected.append((pid, pref, age))

    # Who lives under which sandbox root, from the SAME snapshot — the co-resident sets the carve-out's
    # occupancy fence subtracts (see `_holder`). Built once rather than rescanned per process.
    co_residents: dict = {}
    for pr in procs:
        r = _root(pr.get("cwd") or "")
        if r:
            co_residents.setdefault(r, set()).add(pr.get("pid"))

    # The fail-open REPORT (T-11088): sandbox-RESIDENT processes carrying no `-p` identity. Read from
    # the SAME snapshot — no second scan — and never signalled. The age fence applies to the report
    # too, so a live verify's own busy children do not fill the output every 30 minutes.
    # T-11538 — THIS LOOP NOW APPLIES `_floor_for`, THE SAME RULE AS THE `-p` LOOP ABOVE. T-11234
    # deliberately kept the shared `retention_sec` here and said so: the short floor belonged to the
    # positively-identified `-p` class, and this identity-less cohort was the sibling card T-11217's,
    # so widening it from there would have been that card reaching into this one's axis. It recorded
    # the option as followup fu_60d56377f43b precisely so a later card could decide it on the merits.
    # This IS that card. The merits were never in doubt — a process whose sandbox root has vanished is
    # orphaned positively whether or not it carries a `-p` value, and the two cohorts disagreeing
    # about the same fact is the defect, not the floor value. So the discriminator is unchanged
    # (proven absence of the resolved root) and the floors are unchanged (0.25h / 24h); only the
    # population the existing rule reaches has widened, by REUSING the one expression rather than
    # adding a second threshold for this class.
    # THE AGE FENCE THEREFORE MOVES BELOW THE ROOT RESOLUTION, which is what lets the floor depend on
    # the root's state. Everything the age fence used to protect still holds: the report of an
    # identity-less resident under a PRESENT root is still gated at the shared floor (its `_floor_for`
    # returns exactly that), so a live verify's busy children still do not fill the output.
    for pr in procs:
        pid = pr.get("pid")
        if pid == self_pid or pid in candidate_pids or pr.get("uid") != uid:
            continue
        resident = _root(pr.get("cwd") or "")
        if not resident:
            continue
        age = age_of(pid)
        if age < _floor_for(resident)[0]:
            continue
        # T-11217 — the ONE carve-out. A resident whose own sandbox root is PROVABLY gone is no longer
        # unclassifiable: the run that owned that root has ended (the root outlives every live child by
        # construction), so this process is a survivor and not somebody's live worker. It still has to
        # clear the same ACTIVE-RUN fence as the `-p` class — an absent root can have no legitimate
        # holder, so this can only ever spare, never widen — and it is reaped by the cwd-root re-proof.
        # T-11701 — this branch has ALREADY established the root is provably gone, so
        # `_argv_mention_counts(resident)` is False here by construction; it is called rather than
        # hardcoded so the two cohorts keep resolving the question through the ONE expression.
        if absent_of(resident) and _holder(resident, except_pids=co_residents.get(resident, frozenset()),
                                           argv_arm=_argv_mention_counts(resident)) is None:
            orphan_residents.append((pid, resident, age))
            continue
        residents.append((f"pid {pid}", f"sandbox-resident under {resident} but carries no `-p` identity — "
                                        f"NOT classifiable, left running (reported, never killed on a guess)"))
    return {"candidates": selected, "skipped": skipped, "residents": residents,
            "orphan_residents": orphan_residents}



def _mount_roots(mounts_path="/proc/mounts", *, _PSEUDO_FSTYPES=None) -> "tuple[list, str | None]":
    """Every non-pseudo mount point in THIS namespace, as the keep-set's scan roots (T-11062).

    Returns `(roots, error)`; a non-None `error` means the universe could not be established and the
    caller MUST reap nothing. Read from `/proc/mounts` rather than hand-listed for the T-10855
    reason: a mount that appears later must be covered without editing the cleanup site."""
    roots, seen = [], set()
    try:
        raw = Path(mounts_path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [], f"{mounts_path} unreadable ({e.strerror or e})"
    for line in raw.splitlines():
        f = line.split()
        if len(f) < 3 or f[2] in _PSEUDO_FSTYPES:
            continue
        # `/proc/mounts` octal-escapes the separators inside a mount point.
        mp = f[1].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
        if mp not in seen:
            seen.add(mp)
            roots.append(mp)
    if not roots:
        return [], f"no non-pseudo mount point found in {mounts_path}"
    return roots, None



def live_journal_lock_keys(*, mounts_path="/proc/mounts", uid=None, journal_name="events.jsonl",
                           _access=os.access, _walk=os.walk, _stat=os.stat, _mount_roots=None, events=None) -> dict:
    """THE KEEP-SET: the sidecar key of every live journal this uid could be appending to (T-11062).

    Orphanhood is DERIVED, and only one direction is available: the key is `sha256(resolved journal
    path)[:16]` and cannot be inverted, so the reaper must know which keys are ALIVE. This is the
    same method the 2026-08-13 hand pass used to remove 800338 of 808615 stranded locks while keeping
    24 live keys — that pass is this function's reference implementation, now inside the verb.

    THE UNIVERSE MATCHES THE RULE ("no live journal on this host"), or the scan says so and nothing is
    reaped. That equivalence is the whole audit-pre axis of this card (two RED passes, resolved by the
    ceiling-convergence consult `decisions/T-11062-audit-consult-pre.yaml` — GREEN, single survivor of
    four framed options). A convenient subset (`$HOME` plus the repo) is NOT acceptable: a journal
    anywhere else would have its live sidecar reaped.

    The set is deliberately OVER-inclusive — every `events.jsonl` found is kept, ephemeral or not,
    since an extra key can only ever SPARE a lock, never cause one to be removed.

    PERMISSION-DENIED DIRECTORIES, the axis the consult settled (option C of four). A denied directory
    is classified, never waved through:
      • NOT TRAVERSABLE by this uid ⇒ PROVABLY irrelevant. POSIX requires X on every ancestor to open
        a file, so no path below it is reachable by this uid at all, so it holds no journal this uid
        appends to — and the reap cohort is uid-fenced on the other side. Counted, not fatal. (This is
        the 53 root-owned docker overlay mount roots on the measured host.)
      • TRAVERSABLE BUT UNLISTABLE (mode 0711) AND WRITABLE by this uid ⇒ genuinely reachable and
        invisible ⇒ the scan IS partial ⇒ `error` is set and the caller reaps NOTHING.
      • TRAVERSABLE BUT UNLISTABLE AND NOT WRITABLE ⇒ dismissed, but NAMED in `unlistable` so the
        sweep reports it on EVERY run and the assumption never goes silent. The argument: a journal of
        ours directly in it was impossible while those permissions held; one deeper would require the
        owner to have deliberately created a subtree writable by this uid beneath a directory it
        deliberately made unlistable. Measured on this host: 10 such dirs (`/run/sudo`,
        `/run/containerd`, `/opt/containerd`, `/var/lib/snapd/void` + its snap copies), all
        root-owned and non-writable.
    The two REJECTED alternatives, recorded so they are not silently reinvented: failing closed on ANY
    permission error makes this category inert on this host FOREVER while reporting itself healthy —
    the exact T-10857 silent-zero class this card was filed after; and reaping on a longer age horizon
    when the scan is partial is UNSOUND, because an O_CREAT re-open never touches the lock's mtime, so
    a lock's age says nothing about its journal's liveness.

    FAIL CLOSED on anything else that makes the scan untrustworthy: `/proc/mounts` unreadable, zero
    roots, ZERO journals found (the state in which the predicate would authorise deleting all of
    them), or ANY non-permission walk error.

    Returns `{"keys": set, "error": str|None, "journals": int, "roots": int,
    "unreachable": int, "unlistable": [path]}`."""
    uid = os.geteuid() if uid is None else uid
    roots, err = _mount_roots(mounts_path)
    if err:
        return {"keys": set(), "error": err, "journals": 0, "roots": 0,
                "unreachable": 0, "unlistable": [], "vanished": 0}
    keys, unlistable, hard = set(), [], []
    unreachable = [0]

    vanished = [0]

    def _onerror(e):
        d = getattr(e, "filename", None)
        if getattr(e, "errno", None) == errno.ENOENT:
            # BENIGN, and measured: a busy host churns temp directories constantly, and a walk of the
            # whole namespace races them by construction (23 such directories vanished during the
            # first real run of this scan). A directory that no longer exists cannot hold a LIVE
            # journal, so it cannot be one whose sidecar we would wrongly orphan — the very question
            # this scan asks. Treating it as a hard fault would abort the category on every run of a
            # busy host, i.e. reproduce the silent-zero this card exists to fix, in a new place.
            vanished[0] += 1
            return
        if getattr(e, "errno", None) != errno.EACCES:
            hard.append(f"{d}: {getattr(e, 'strerror', None) or e}")
            return
        if not d or not _access(d, os.X_OK):
            unreachable[0] += 1          # provably unreachable by this uid — see the docstring.
        elif _access(d, os.W_OK):
            hard.append(f"{d}: reachable but unlistable AND writable by this uid — scan is partial")
        else:
            unlistable.append(d)

    for root in roots:
        try:
            dev = _stat(root).st_dev
        except OSError as e:
            _onerror(e if getattr(e, "filename", None) else type(e)(e.errno, e.strerror, root))
            continue
        for dirpath, dirnames, filenames in _walk(root, onerror=_onerror):
            try:
                if _stat(dirpath).st_dev != dev:
                    dirnames[:] = []      # another mount — walked as its own root, never twice.
                    continue
            except OSError as e:
                # Audit-post MEDIUM absorption: this stat is part of the scan, so its failures obey
                # the SAME contract as the walk's — routed through the one classifier, so the benign
                # ENOENT vanish-race and the fail-closed device fault are decided in ONE place rather
                # than twice with two chances to disagree.
                _onerror(e if getattr(e, "filename", None) else OSError(e.errno, e.strerror, dirpath))
                dirnames[:] = []
                continue
            if journal_name in filenames:
                try:
                    keys.add(events.journal_lock_key(Path(dirpath, journal_name).resolve()))
                except OSError:
                    continue              # vanished mid-walk — contributes nothing, never fatal.
    if hard:
        return {"keys": keys, "error": "; ".join(hard[:3]) + (f" (+{len(hard) - 3} more)" if len(hard) > 3 else ""),
                "journals": len(keys), "roots": len(roots), "unreachable": unreachable[0],
                "unlistable": unlistable, "vanished": vanished[0]}
    if not keys:
        return {"keys": keys, "error": "scan found ZERO journals — refusing to treat every lock as an "
                                       "orphan", "journals": 0, "roots": len(roots),
                "unreachable": unreachable[0], "unlistable": unlistable, "vanished": vanished[0]}
    return {"keys": keys, "error": None, "journals": len(keys), "roots": len(roots),
            "unreachable": unreachable[0], "unlistable": unlistable, "vanished": vanished[0]}



def select_orphan_journal_locks(lock_paths, *, live_keys, scan_error, retention_sec: float, uid: int,
                                age_of, stat_of=os.lstat, age_label: "str | None" = None, events=None) -> dict:
    """T-11062 — THE orphan-journal-sidecar predicate, in ONE place. PURE SELECTION: it opens nothing,
    unlinks nothing, and walks nothing (the keep-set is passed IN, already computed).

    A function and not an inline block for the T-11089 reason: a predicate with one caller is free to
    be re-spelled by the next reader, and then two numbers disagree with nobody able to say which is
    right. Sharing the FUNCTION is what makes a second reader's count mean the same thing as the
    reaper's.

    A lock is a candidate ONLY when EVERY guard passes — fail-OPEN toward keeping, at every step:
      • `scan_error` set (an untrustworthy keep-set) ⇒ `abort`, and NOTHING is a candidate. An empty
        or partial keep-set is precisely the state in which this predicate would authorise deleting
        every lock on the host, so it is the one that must never be trusted.
      • NAME — matches the CREATOR's published `events.PERSISTENT_LOCK_NAME_RE`, never a shape
        re-spelled here.
      • a REGULAR FILE, not a symlink or directory (`stat_of` = `os.lstat`).
      • KEY IS NOT LIVE — the key is absent from `live_keys`.
      • AGE ≥ `retention_sec` — the sweep's own clamped retention, so the hard SWEEP_MIN_AGE_HOURS
        floor applies. Load-bearing for a DIFFERENT reason than in the other categories: an O_CREAT
        open never updates mtime, so age is NOT a liveness proxy here (the keep-set is that). This
        fence exists solely so a journal being created CONCURRENTLY — one that may post-date the
        keep-set scan — cannot have its sidecar reaped out from under it. An unreadable mtime reads
        as YOUNG (-1.0) and is kept, as everywhere else in this verb.
      • OWNED BY THIS UID — matching Category C. Another user's lock belongs to a journal in a subtree
        our scan may not be able to list, and it is also what makes the docstring's permission
        argument sound.

    Returns `{"candidates": [(path, key, age)], "skipped": [(label, reason)], "abort": reason|None,
    "considered": int}`. `skipped` is the FULL reasoned list; the sweep caps what it PRINTS, because
    this population is measured in the tens of thousands and the verb runs 48x/day into a cron log."""
    label = age_label if age_label is not None else f"{retention_sec / 3600:.1f}h"
    if scan_error or not live_keys:
        # BOTH halves, in the PREDICATE itself (audit-post HIGH absorption). The enumerator already
        # refuses a zero-journal scan, but this function is the thing that authorises deletion, and
        # it must not inherit its own safety from whoever supplied the keep-set: an empty set reaching
        # here — from a future caller, an injected seam, or a refactor of the enumerator — means
        # "every lock on this host is an orphan", which is never a conclusion worth trusting.
        return {"candidates": [], "skipped": [],
                "abort": scan_error or "keep-set is EMPTY — refusing to treat every lock as an orphan",
                "considered": 0}
    candidates, skipped, considered = [], [], 0
    for path in lock_paths:
        name = os.path.basename(str(path))
        m = events.PERSISTENT_LOCK_NAME_RE.match(name)
        if m is None:
            skipped.append((str(path), "not a persistent journal sidecar name — never touched"))
            continue
        considered += 1
        try:
            st = stat_of(path)
        except OSError:
            skipped.append((str(path), "unreadable — fail-closed, kept"))
            continue
        if not stat.S_ISREG(st.st_mode):
            skipped.append((str(path), "not a regular file (symlink/dir) — fail-closed, kept"))
            continue
        key = m.group(1)
        if key in live_keys:
            skipped.append((str(path), "journal is LIVE (key in the keep-set)"))
            continue
        age = age_of(path)
        if age < retention_sec:
            skipped.append((str(path), f"too young ({age / 3600:.1f}h < {label}) — a journal may be "
                                       f"under creation right now"))
            continue
        if st.st_uid != uid:
            skipped.append((str(path), f"owned by uid {st.st_uid} (not this user) — never removed"))
            continue
        candidates.append((str(path), key, age))
    return {"candidates": candidates, "skipped": skipped, "abort": None, "considered": considered}



def _reap_proc(pid: int, prefix: str, glob: str = _SANDBOX_PREFIX_GLOB, *, grace_sec: float = 3.0,
               cwd_root: "str | None" = None, _sandbox_prefix_arg=None, _sandbox_resident_root=None, _sandbox_root_absent=None) -> bool:
    """T-10857 — terminate ONE selected orphan, RE-VALIDATING its identity immediately before EVERY
    signal. Returns True when the pid is gone afterwards.

    THE PID-REUSE RACE this closes (audit-pre finding): the `/proc` scan that selected this pid is a
    SNAPSHOT. A candidate may exit between selection and the kill — and the kernel may hand its pid to an
    UNRELATED process of the same uid, which would then receive our signal. So before SIGTERM, and again
    before the escalating SIGKILL (the grace poll is a second reuse window), we re-read
    `/proc/<pid>/cmdline` and require `_sandbox_prefix_arg` to still return the SAME prefix value. Any
    mismatch — a different prefix, no prefix, or an unreadable/absent cmdline — ABORTS the signal:
    fail-closed toward NOT killing. A pid that has simply vanished is a SUCCESS (the orphan is gone),
    never a retry target.

    TWO POSITIVE FACTS, ONE KILL LOOP (T-11217). `cwd_root` selects WHICH fact is re-proven, and
    nothing else changes — same SIGTERM, same grace poll, same escalation, same fail-closed grammar.
      · `cwd_root=None` (default) — the `-p` class, exactly as above and byte-unchanged.
      · `cwd_root=<root>` — the orphan-RESIDENT class, which carries no `-p` to re-read. Its identity
        is re-proven from `/proc/<pid>/cwd`: the link must STILL resolve to the same sandbox root AND
        that root must STILL be provably absent. Both halves are load-bearing. The first is the
        PID-reuse guard (a reused pid is overwhelmingly not sitting in a deleted sandbox, and never in
        THIS one). The second closes the reverse race that only this class has — if the root REAPPEARS
        between selection and signal, the fact that justified the reap is no longer true, so the
        signal is ABORTED. Neither half reads a process NAME or infers identity from shape; the kill
        still rests on positive evidence re-checked immediately before every signal.
    Note on `(deleted)`: Linux appends that marker to the readlink of a removed cwd, tailing the LEAF
    of the path. `_sandbox_resident_root` walks ancestors shallowest-first, so the extracted ROOT is
    unaffected by the marker — asserted directly in the T-11217 suite rather than assumed."""
    import signal as _signal

    def _still_the_resident() -> "bool | None":
        """The `cwd_root` re-proof. Same tri-state contract as `_still_the_orphan`."""
        try:
            link = os.readlink(f"/proc/{int(pid)}/cwd")
        except (FileNotFoundError, ProcessLookupError):
            return None                      # the process exited — the reap goal is already met.
        except OSError:
            return False                     # unreadable → cannot prove identity → never signal.
        if _sandbox_resident_root(link, glob) != cwd_root:
            return False                     # pid reused, or it chdir'd out — not provably ours.
        return _sandbox_root_absent(cwd_root)  # the root came back ⇒ the justification is gone.

    def _still_the_orphan() -> "bool | None":
        """True = same orphan, still there · False = pid reused by something else · None = already gone."""
        if cwd_root is not None:
            return _still_the_resident()
        try:
            raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
        except FileNotFoundError:
            return None                      # the process exited — the reap goal is already met.
        except OSError:
            return False                     # unreadable → cannot prove identity → never signal.
        if not raw.strip(b"\x00"):
            # An EMPTY cmdline is never the orphan (it had argv when we selected it): the entry is now a
            # ZOMBIE awaiting its parent's wait(), or a kernel thread that inherited the pid. Either way
            # the process we meant to reap is gone — and signalling an empty-argv entry could never be
            # proven safe, so this is both the correct and the fail-closed reading.
            return None
        argv = [a.decode("utf-8", "surrogateescape") for a in raw.split(b"\x00") if a]
        return _sandbox_prefix_arg(argv, glob) == prefix

    state = _still_the_orphan()
    if state is None:
        return True
    if state is False:
        return False
    try:
        os.kill(int(pid), _signal.SIGTERM)
    except OSError:
        return _still_the_orphan() is None
    deadline = time.time() + max(grace_sec, 0.0)
    while time.time() < deadline:
        if _still_the_orphan() is None:
            return True
        time.sleep(0.1)
    if _still_the_orphan() is not True:       # gone, or no longer provably ours → do NOT escalate.
        return _still_the_orphan() is None
    try:
        os.kill(int(pid), _signal.SIGKILL)
    except OSError:
        pass
    time.sleep(0.2)
    return _still_the_orphan() is None



def _worktree_parent_dir(main_worktree: Path) -> Path:
    """The sibling dir `worktree new` places linked worktrees in: `<main>.parent / <main-name>-wt`
    (T-0840 — the SAME formula as `bin/yitc-v2#_worktree_parent_leaf`, which cannot be imported here
    without a cycle; a divergence is caught by `test_wt_parent_matches_worktree_new_placement`).

    Anchored to the resolved MAIN checkout, NOT to REPO_ROOT: a sweep invoked from inside a LINKED
    worktree has REPO_ROOT == that worktree, and the REPO_ROOT formula would then name
    `<repo>-wt/T-XXXX-wt` — a directory the fleet never uses. Identical to the REPO_ROOT formula for
    the ordinary main-checkout / `-C <consumer>` invocations (there main IS the repo root)."""
    p = Path(main_worktree)
    return p.parent / f"{p.name}-wt"



def _created_tmp_prefixes(repo_root: Path, *, _TMP_BASELINE_PREFIXES=None, _TMP_CREATOR_APIS=None, _TMP_CREATOR_SOURCES=None) -> "tuple[str, ...]":
    """DERIVE the set of `yitc-*` temp-dir prefixes the codebase CREATES in the SYSTEM tempdir (T-10855).

    Reads the creation sites (`_TMP_CREATOR_APIS` — the directory-creating tempfile calls) rather than
    trusting a hand-kept list at the cleanup site. Three deliberate exclusions, all narrowing to what a
    /tmp sweep may own:
      • a FILE-creating call (`mkstemp`, `NamedTemporaryFile`) makes no directory to sweep;
      • a call passing `dir=…` does NOT land in the system tempdir (e.g. the host-apply backup root lives
        under its own base) — its lifetime is that subsystem's, never this sweep's;
      • a prefix that is not `yitc-`-namespaced is not ours to remove.
    A `prefix=` given as a module-level constant (`prefix=_VERIFY_SANDBOX_PREFIX`) is resolved through the
    scanned files' own `NAME = <yitc-NAME->` assignments; an f-string prefix is truncated at its first
    interpolation. Result is UNIONED with `_TMP_BASELINE_PREFIXES` and an unreadable source is skipped, so
    the derivation can only widen the cohort — a broken scan degrades to the old hand-listed behaviour."""
    import glob as _glob
    consts: dict = {}
    bodies = []
    for pat in _TMP_CREATOR_SOURCES:
        for path in sorted(_glob.glob(str(repo_root / pat))):
            try:
                bodies.append(Path(path).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue   # unreadable source → contributes nothing; the baseline still holds.
    if not bodies:
        # LOUD, not silent (audit-pre HIGH absorption): discovery that read NOTHING cannot prove the
        # created-prefix set, so say so. The run still proceeds on the known-leak baseline — degrading to
        # today's behaviour is safe (it only ever removes less), but it must never look like coverage.
        print("worktree sweep: WARN — no creator source readable under "
              f"{repo_root}; /tmp cohort falls back to the known-leak baseline {_TMP_BASELINE_PREFIXES}")
    for body in bodies:
        for m in re.finditer(r'^\s*(_?[A-Za-z]\w*)\s*=\s*["\'](yitc-[\w.-]*)["\']', body, re.M):
            consts[m.group(1)] = m.group(2)
    found = set(_TMP_BASELINE_PREFIXES)
    for body in bodies:
        api = "|".join(_TMP_CREATOR_APIS)
        for m in re.finditer(rf"\b(?:{api})\(([^()]*(?:\([^()]*\)[^()]*)*)\)", body):
            call = m.group(1)
            if re.search(r"\bdir\s*=", call):
                continue   # not the system tempdir — out of this sweep's ownership.
            pm = re.search(r"prefix\s*=\s*(?:f?[\"']([^\"'{]*)|(_?[A-Za-z]\w*))", call)
            if not pm:
                continue
            prefix = pm.group(1) if pm.group(1) is not None else consts.get(pm.group(2), "")
            # VALIDATE, never trust: the scan reads raw source text (prose in a docstring/comment can
            # look like a call), and an over-broad token would widen the glob to `yitc-*` — i.e. to temp
            # dirs no creator here owns. Only a well-formed, namespaced prefix with a real name after
            # `yitc-` is admitted; anything else is dropped rather than guessed.
            if re.fullmatch(r"yitc-[A-Za-z0-9_.-]*[A-Za-z0-9][A-Za-z0-9_.-]*", prefix):
                found.add(prefix)
    return tuple(sorted(found))



def _live_held_paths() -> "tuple[list, str]":
    """Best-effort inventory of filesystem paths a LIVE process is currently holding (T-10855).

    The PAIRED half of widening the sweep's cohort: a verify sandbox is the TMPDIR of a running test
    fleet and, unlike a pinned-verify temp, can legitimately outlive the age floor (a land can sit
    queued behind the SPEC-0132 verify-admission gate). Deleting a RUNNING verify's sandbox is far worse
    than leaking one, so age stops being the only liveness proxy for unstamped temp dirs — this adds the
    signal the 2026-08-09 hand cleanup used, which spared every in-use directory.

    Returns (paths, argv_blob): per-process `cwd` targets plus the path-valued env vars a sandboxed child
    carries (TMPDIR/HOME/XDG_*/GIT_CONFIG_*), and one concatenated argv blob for substring matching (a
    sandbox path reaches a child as an argument, e.g. `git -C <box>/…`). Every read is best-effort:
    a process that exits mid-scan or an unreadable `/proc` entry simply contributes nothing."""
    paths, argv = [], []
    try:
        pids = [d for d in os.listdir("/proc") if d.isdigit()]
    except OSError:
        return [], ""   # no /proc (non-Linux): no liveness signal available; the age floor still governs.
    for pid in pids:
        try:
            paths.append(os.readlink(f"/proc/{pid}/cwd"))
        except OSError:
            pass
        for name in ("environ", "cmdline"):
            try:
                with open(f"/proc/{pid}/{name}", "rb") as fh:
                    raw = fh.read(131072)
            except OSError:
                continue
            if name == "cmdline":
                argv.append(raw.replace(b"\0", b" ").decode("utf-8", "replace"))
                continue
            for kv in raw.split(b"\0"):
                if kv.startswith((b"TMPDIR=", b"HOME=", b"XDG_", b"GIT_CONFIG_")):
                    paths.append(kv.split(b"=", 1)[1].decode("utf-8", "replace"))
    return paths, " ".join(argv)



def _rmtree_collect(path, errnos: list) -> None:
    """`shutil.rmtree` that COLLECTS each failure's errno instead of discarding it (T-10891).

    The pre-change call passed `ignore_errors=True`, which throws away the one datum a classifier
    needs. Removal is still best-effort — nothing is raised; the caller decides what a survivor MEANS
    by re-testing `Path(path).exists()` exactly as before. `onexc` is the 3.12+ spelling (`onerror`
    is deprecated there and removed in 3.14); the older spelling is kept for a pre-3.12 interpreter."""
    import shutil

    def _note(_func, _p, exc):
        errnos.append(getattr(exc, "errno", None))

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_note)
    else:   # pragma: no cover - this host runs 3.12; kept so an older interpreter still collects.
        shutil.rmtree(path, onerror=lambda f, p, ei: _note(f, p, ei[1]))



def _removal_failure_is_expected_residue(path, errnos, *, _lstat=os.lstat, _euid=os.geteuid) -> bool:
    """Is a FAILED removal the ONE permanently-impossible class — a foreign-owned path the sweeping
    user cannot unlink because its parent carries the sticky bit (T-10891)?

    TRUE demands FIVE positively-proven facts, all conditions on that SINGLE POSIX class:
      (1) an EPERM among the collected errnos — the kernel's own "you may never unlink this" answer
          (an EACCES means merely unreadable/unwritable, which is NOT unlinkable-forever);
      (2) the entry is owned by a DIFFERENT uid;
      (3) its parent carries S_ISVTX — under the sticky bit only the entry's owner, the directory's
          owner, or root may unlink;
      (4) the sweeping user does NOT own that sticky parent — MEASURED: when it does, the identical
          foreign-owned entry removes CLEANLY, so an EPERM there is anomalous, not impossible
          (audit-pre HIGH absorption);
      (5) we are not root — root unlinks regardless, so an EPERM as uid 0 is likewise anomalous.

    FAIL-CLOSED IN ONE DIRECTION ONLY: anything unproven — an unreadable stat, a missing EPERM, a
    self-owned entry or parent — returns False, i.e. UNEXPECTED, i.e. LOUD. A cause this predicate
    does not positively recognise must never be assumed harmless; that is what keeps a future failure
    mode from going silent behind today's one known exception."""
    if errno.EPERM not in [e for e in errnos if e is not None]:
        return False
    euid = _euid()
    if euid == 0:
        return False
    try:
        entry = _lstat(str(path))
        parent = _lstat(str(Path(path).parent))
    except OSError:
        return False   # cannot PROVE the class → unexpected → loud.
    return (entry.st_uid != euid
            and bool(parent.st_mode & stat.S_ISVTX)
            and parent.st_uid != euid)



def _errno_names(errnos) -> str:
    """The NAMES of the errnos a failed removal actually produced (T-11750, X-1139 half 1).

    `_rmtree_collect` already keeps every failure's errno; before this the sweep consumed them only
    inside the sticky-parent recogniser and threw them away on every other path, so an operator read
    `cause not recognised` for a plain EPERM — and could not tell that the remedy was chown/sudo
    rather than a corrupt worktree. Returns a comma-joined `errno.errorcode` name list, deduplicated,
    in first-seen order; '' when NOTHING was captured (a removal that failed with no recorded errno
    must never have one fabricated for it). An errno with no `errorcode` entry is rendered as its
    number, so an exotic platform errno degrades to a fact rather than to silence."""
    names, seen = [], set()
    for e in errnos or []:
        if e is None or e in seen:
            continue
        seen.add(e)
        names.append(errno.errorcode.get(e, str(e)))
    return ", ".join(names)


def _removal_left_partial(path, kind, *, _exists=None) -> bool:
    """Did this FAILED removal nonetheless make IRREVERSIBLE progress — an UNREGISTERED worktree with
    files still on disk (T-11750, X-1139 half 2, the load-bearing one)?

    THE REPORTED STATE: `git worktree remove --force` (or the `_rmtree_collect` that follows it) tore
    down the leaf's `.git` file and emptied the tree down to one surviving subdir, yet the run said
    only `removal failure` — which a reader takes as «nothing happened». It is not nothing: a tree
    whose `.git` is gone can no longer be entered as a worktree, and the `git worktree prune` this
    verb ALREADY runs unregisters it. Naming that state is the whole point of this predicate.

    THE DISCRIMINATOR is a POSITIVE proof of progress, in the same fail-closed direction as
    `_removal_failure_is_expected_residue`: a linked worktree carries `.git` as a FILE, so
    «leaf still exists AND its `.git` is gone» proves the removal got past the registration and
    stopped inside the tree. If `.git` is still there, nothing irreversible happened and the caller
    keeps today's plain-failure verdict. Only `kind == "worktree"` can be partial — a temp-dir or
    sandbox leaf has no registration to lose, so its failure is a plain failure by construction.
    Anything unproven ⇒ False ⇒ the LOUD pre-change path, never quieter."""
    if kind != "worktree":
        return False
    ex = _exists if _exists is not None else (lambda q: Path(q).exists())
    return bool(ex(path)) and not ex(Path(path) / ".git")


def _acl_protected_archive_leftover(path, *, _chmod=os.chmod, _rmtree_collect=None) -> "str | None":
    """Is this FAILED removal the leftover `land` DELIBERATELY leaves — and can the sweep finish it?
    (T-10976, the second recognised class; the producer is `_recover_unremovable_worktree_leftover`.)

    CLOSED THREE-VALUED ANSWER, never a boolean — "did not recognise" must be distinguishable from
    "recognised and still there", or the caller cannot keep the loud path loud:
      None      → NOT this shape. The caller's remaining paths (the sticky-bit classifier, then LOUD)
                  decide, exactly as before this function existed.
      "cleared" → was this shape AND the leftover is now GONE (the caller counts it as removed).
      "left"    → was this shape AND it is still on disk (recognised, reported, exit unaffected).

    THE ARCHIVE IS LOCATED ANYWHERE UNDER `<path>`, NOT ONLY AT ITS IMMEDIATE ROOT (T-11400). The
    original discriminator keyed on `<path>/.yitc/transcript-archive`; in a stale verify SANDBOX the
    identical shape sits several levels DEEPER — `<sandbox>/box<N>/tmp/tmp<X>/wt-detached/.yitc/
    transcript-archive` (the pinned suite's own `test_land_e0004_cleanup` plants it, and inside a box
    `tempfile.mkdtemp()` resolves under `box<N>/tmp`). At the sandbox root the old condition was
    false, so the run fell into the loud unexpected branch and the */30 cron exited 1: MEASURED
    2026-08-21, 102 FAILED runs over 3 distinct sandbox paths (58 + 22 + 18) — the class RECURS per
    sandbox, it was never one stranded directory.

    The discriminator is POSITIVE and proven, never inferred from "the removal failed":
      (a) at least ONE archive root exists under `<path>` — an entry named `transcript-archive` whose
          parent is named `.yitc`, that is a real directory and NOT a symlink. `<path>`'s own
          `.yitc/transcript-archive` is simply the depth-0 member of that set, so the pre-T-11400
          shape is recognised unchanged;
      (b) EVERY surviving entry under `<path>` — dir or file — is an archive root, is under one, or is
          an ancestor DIRECTORY (real, not a symlink) that exists only to hold one. This is the SAME
          survivor test the producer applies on land's side, generalised from the two fixed ancestors
          (`<path>`, `<path>/.yitc`) to the ancestor CHAIN. Any other survivor, INCLUDING an empty
          unrelated directory, means this is a genuine failure wearing the right hat → None. That
          refusal is the load-bearing half: a matcher widened until every failure is quiet would
          satisfy the nested case while destroying the only signal that the sweep is stuck.
    An OSError anywhere in the walk also returns None — a shape we cannot PROVE is a shape we do not
    recognise (the fail-closed direction the T-10891 classifier already takes).

    THE BOUND (the card's whole point — no blanket chmod-then-delete power) IS UNCHANGED BY THE
    WIDENING: the write bit is restored ONLY on a PROVEN archive root and the directories UNDER it,
    walked from each archive root. No ancestor — including `<path>` itself and every intermediate dir
    the deeper nesting introduced — is ever chmod'd, and neither is any parent or symlink. So when the
    protection sits OUTSIDE an archive the retry legitimately fails and this returns "left" — the
    sweep reports the leftover instead of unlocking its way out. The archive is write-stripped ON
    PURPOSE by the acl-watcher; a sweep that stripped protection wherever it met it would defeat the
    very mechanism it is here to cooperate with.
    """
    W = Path(path)
    try:
        entries = list(W.rglob("*"))
        archives = [p for p in entries
                    if p.name == "transcript-archive" and p.parent.name == ".yitc"
                    and p.is_dir() and not p.is_symlink()]
        if not archives:
            return None
        # The ancestor chain: every dir between `<path>` (inclusive) and a proven archive root. These
        # exist only to hold the archive — accepted as survivors, NEVER chmod'd.
        ancestors = {W}
        for a in archives:
            for anc in a.parents:
                if anc == W:
                    break
                ancestors.add(anc)
        for p in entries:
            if p in archives or any(a in p.parents for a in archives):
                continue
            if p in ancestors and p.is_dir() and not p.is_symlink():
                continue
            return None   # a non-archive survivor — a genuine failure, never this class
        subdirs = [d for a in archives
                   for d in [a] + [p for p in a.rglob("*") if p.is_dir() and not p.is_symlink()]]
    except OSError:
        return None       # cannot PROVE the shape → not recognised → the caller stays loud
    for d in subdirs:
        try:
            _chmod(d, os.stat(d).st_mode | stat.S_IWUSR)
        except OSError:
            pass          # best-effort: an un-chmod-able dir just means the retry below leaves it
    _rmtree_collect(W, [])
    return "left" if W.exists() else "cleared"



def _cure_self_owned_eacces(path, errnos, *, _rmtree_collect, _chmod=os.chmod,
                            _lstat=os.lstat, _euid=os.geteuid) -> bool:
    """Is this FAILED removal a CURABLE one — a directory the sweeping user OWNS but stripped of its
    own write bit — and did restoring that bit finish the removal? (T-11855.)

    THE CLASS, MEASURED not inferred (2026-08-30): `shutil.rmtree` cannot unlink inside a directory
    lacking the owner write bit, so a leftover at mode 0o555 holding a file produces exactly EACCES
    then ENOTEMPTY, and `chmod u+wx` + one retry removes the tree cleanly. That sequence appears
    verbatim in the `yitc-v2-worktree-sweep` cron rows across distinct `/tmp/yitc-verify-sandbox-*`
    paths: each run removed everything else and then failed the WHOLE run on one such path, reported
    as `cause not recognised`. It is not unrecognisable — it is curable, and the sweep is the durable
    place to cure it (the producer is a verify process killed between a test's `chmod(0o555)` and its
    non-`finally` restore, which no edit to that test can make crash-proof).

    THIS IS A CURE ATTEMPTED BEFORE CLASSIFICATION, NOT A WIDENING OF WHAT COUNTS AS EXPECTED.
    `_removal_failure_is_expected_residue` is untouched: a self-owned EACCES still present after this
    retry is still UNEXPECTED and still reddens the run. Nothing becomes quiet that was not removed.

    THE PRECONDITION IS THE CALLER'S: it calls this only when the path SURVIVED and EACCES is among
    the collected errnos, so a removal that failed for any other reason never reaches the chmod.

    TWO BOUNDS, both of which keep an EXISTING invariant true rather than merely being cautious:
      (1) ONLY directories AT-OR-UNDER `<path>`, owned by the sweeping euid, that are not symlinks.
          No ancestor is ever chmod'd — so a removal blocked by a non-writable PARENT legitimately
          stays a failure, and a foreign-owned entry is never touched (that is the sticky-parent
          class's business, and it is EPERM, not EACCES, so it does not arrive here anyway).
      (2) NEVER inside a `.yitc/transcript-archive` subtree. `_acl_protected_archive_leftover`
          documents that the archive is write-stripped ON PURPOSE by the acl-watcher and that "a
          sweep that stripped protection wherever it met it would defeat the very mechanism it is
          here to cooperate with". A blanket self-owned-dir cure would do exactly that; excluding
          archive subtrees leaves that class's own bounded arm the sole route into an archive.

    FAIL-CLOSED IN ONE DIRECTION ONLY, like both existing recognisers: an OSError from the WALK
    aborts the cure and returns False (a shape we cannot prove is a shape we do not cure); a
    per-directory chmod failure is swallowed, which simply means the retry below leaves that dir.
    Returns True IFF `<path>` is now GONE. The retry's errnos are appended to the CALLER'S OWN list
    (the `errnos` parameter), so classification and `_errno_names` still read the complete record."""
    W = Path(path)
    try:
        euid = _euid()
        targets = []
        for dirpath, dirnames, _files in os.walk(str(W), topdown=True, followlinks=False):
            for d in [dirpath] + [os.path.join(dirpath, n) for n in dirnames]:
                dp = Path(d)
                # Bound (2): an archive root or anything under one is never unlocked from here.
                if any(a.name == "transcript-archive" and a.parent.name == ".yitc"
                       for a in [dp] + list(dp.parents)):
                    continue
                st = _lstat(d)
                # Bound (1): real directories, self-owned, never a symlink.
                if stat.S_ISDIR(st.st_mode) and st.st_uid == euid:
                    targets.append((d, st.st_mode))
    except OSError:
        return False      # cannot PROVE the shape → not cured → the caller stays loud.
    for d, mode in targets:
        try:
            _chmod(d, mode | stat.S_IWUSR | stat.S_IXUSR)
        except OSError:
            pass          # best-effort: an un-chmod-able dir just means the retry leaves it.
    _rmtree_collect(str(W), errnos)
    return not W.exists()



def _record_residue_once(events_path: Path, paths: list, _append_event, *, _RESIDUE_FINGERPRINT=None, _RESIDUE_SCAN_BYTES=None, journal_mod=None) -> bool:
    """Record the recognised residue DURABLY, but exactly ONCE — not once per run (T-10891).

    The condition is permanent, and the verb runs every 30 minutes: an unconditional emit would add
    48 identical journal lines a day. So the record reuses the EXISTING `deviation_captured` event
    (no new event type) keyed by a CONSTANT fingerprint, and is skipped when that fingerprint is
    already present in the journal this verb already writes to. Best-effort read: an unreadable
    journal falls through to emitting — a duplicate record is harmless, a missing one is not.
    Returns True when a record was written.

    The already-recorded test DECIDES ON PARSED FIELDS over a BOUNDED tail (T-10897), via the shared
    `journal.tail_scan_events` reader: the raw-substring test it replaces matched the fingerprint
    ANYWHERE in the file, so any line merely WRITING ABOUT this mechanism (a deviation capture, a
    task card echoed into an event) silenced the real record permanently — a guard built for loudness
    muted by describing it — and it re-read the whole 125MB journal on EVERY sweep run (48/day under
    the crontab, the T-10832 class). The byte-substring prescan survives only as a cheap SUPERSET
    filter; the envelope type + `data.fingerprint` pair below is what decides."""
    try:
        for ev in journal_mod.tail_scan_events(events_path, _RESIDUE_FINGERPRINT,
                                               max_bytes=_RESIDUE_SCAN_BYTES):
            data = ev.get("data")
            if (ev.get("type") == "deviation_captured" and isinstance(data, dict)
                    and data.get("fingerprint") == _RESIDUE_FINGERPRINT):
                return False
    except OSError:
        pass
    _append_event("deviation_captured", None,
                  {"relates_to": "bin/lib/worktree.py#cmd_worktree_sweep",
                   "impact": "worktree sweep cannot remove foreign-owned paths under the sticky-bit "
                             "system tempdir; permanently unreclaimable by this user, so it is "
                             "recorded once and never alerted on (T-10891)",
                   "fingerprint": _RESIDUE_FINGERPRINT,
                   "first_seen_paths": list(paths)},
                  events_path=events_path)
    return True



def cmd_worktree_sweep(args: argparse.Namespace, *, _append_event, _live_claimed_task_ids, _main_worktree,
                       _read_worktree_stamp, _run_git_cap, _session_proc_alive, _stamp_is_own, REPO_ROOT,
                       _tmp_glob_patterns=None, _tmp_base=None, _wt_parent=_DERIVE_WT_PARENT,
                       _sandbox_prefix_glob=_SANDBOX_PREFIX_GLOB, _proc_scan=None,
                       _proc_age_sec=None, _reap=None,
                       _classify_residue=None, _partial_removal=_removal_left_partial,
                       _cure_removal=_cure_self_owned_eacces,
                       _acl_leftover=None, _acl_chmod=os.chmod,
                       _lstat=os.lstat, _euid=os.geteuid,
                       _lock_root=None, _journal_keys=None, SWEEP_ORPHAN_PROC_MIN_AGE_HOURS=None, _RESIDUE_FINGERPRINT=None, _created_tmp_prefixes=None, _land_commits_not_in_base=None, _live_held_paths=None, _record_residue_once=None, _rmtree_collect=None, _worktree_parent_dir=None, events=None, select_orphan_journal_locks=None, select_orphan_sandbox_procs=None) -> None:
    """`worktree sweep [--dry-run] [--max-age-hours N]` (T-9532) — the v2-NATIVE hygiene backstop for
    STALE worktrees + leaked pinned-verify temp dirs (the inverse of `worktree new` / sibling of `land`,
    D-0050/D-0051). OWN v2 mechanism, NO dependence on the v1 stale-worktree cleaner (D-0026 isolation).

    SPEC-LESS by the SPEC-0005 admission test (T-9532 analysis): the safety invariant lives wholly in THIS
    verb — it is code-enforced + test-covered, not a cross-artifact standing rule others must follow.

    SAFETY INVARIANT (a worktree/dir is swept ONLY when EVERY guard passes — fail-CLOSED toward keeping):
      • NEVER the main checkout (branch==main / the resolved main worktree path);
      • FAIL-CLOSED ALLOWLIST among registered worktrees (audit-post HIGH, T-9532): a worktree is a
        sweep candidate ONLY when its KIND is POSITIVELY a sweepable one — an abandoned `work/<slug>`
        batch (branch `work/...`) OR a DETACHED pinned-verify temp (path under `/tmp/yitc-pinned-*`).
        EVERYTHING else is SKIPPED: any `task/T-XXXX` worktree, a DETACHED non-pinned worktree (could be
        a task worktree in detached HEAD), and any unknown/renamed branch — all may hold UNLANDED work,
        so recovery is `worktree adopt` / dispatch-recovery, NEVER a hygiene sweep. (Classifying by
        branch text ALONE was the defect: the stamp carries only {session_ref, started_at}, no task
        provenance, so a detached/renamed task worktree slipped a `task/T-XXXX`-only denylist and could
        be swept — data loss. The allowlist closes it without a new provenance store.);
      • NEVER a `work/<slug>` worktree whose BRANCH is AHEAD of `main` (T-11285) — the protection the
        allowlist's ONE positively-sweepable worktree kind never had. An abandoned filing batch is
        exactly where a newly filed card lives before its first land, so being ON the allowlist says
        only that the KIND is reclaimable, never that THIS one is spent. Age is a proxy; merge state
        is the fact (`lessons/an-age-based-sweep-must-read-merge-state.md`), so the last question
        asked before removal is git's — `_land_commits_not_in_base(p, "main")` — and BOTH non-zero
        answers keep the worktree: a positive count is unlanded work, and `None` ("the question was
        not ANSWERED") is an UNKNOWN, never a proven zero. Recovery is `worktree adopt --work <slug>`,
        the same adopt-not-sweep rule the task arm above gets;
      • NEVER an own-session-stamped worktree, NEVER one whose stamped owner session is still proc-alive
        (`_session_proc_alive`, the dispatch-status liveness model — no new store);
      • NEVER anything younger than --max-age-hours (default 24h), and an UNREADABLE mtime counts as YOUNG.
        A HARD 1h floor (SWEEP_MIN_AGE_HOURS) clamps a too-low --max-age-hours so an unstamped pinned temp
        dir / detached worktree can never be swept while its land is still in-flight (audit-post safety floor);
      • NEVER a temp dir a LIVE process still HOLDS (T-10855, `_live_held_paths`) — a running verify's
        sandbox is its fleet's TMPDIR and may legitimately outlive the age floor while its land waits for a
        SPEC-0132 admission slot. Age alone was a sufficient liveness proxy only for the short-lived pinned
        temps; widening the cohort must not widen the blast radius.
    The /tmp cohort itself is DERIVED from the creation sites (`_created_tmp_prefixes`), never hand-listed
    here: every `tempfile.mkdtemp(prefix=<yitc-NAME->)` that lands in the system tempdir is swept, so a newly
    added creator cannot be silently missed (T-10855 — exactly how `yitc-verify-sandbox-*` was missed).
      • (T-11062) an orphan PERSISTENT journal sidecar lock (`<temp-root>/yitc-journal-<key>.lock`, a
        FILE no other category can see) is removed only when its key is in NO live journal's keep-set,
        it is past the SAME age fence + floor, it is a regular file owned by THIS uid, and the
        keep-set scan itself was TRUSTWORTHY — an untrustworthy or partial scan reaps NOTHING
        (`live_journal_lock_keys` / `select_orphan_journal_locks` carry the full contract).
      • (T-10857) an orphan verify-sandbox PROCESS is reaped only when it POSITIVELY carries a
        `-p /tmp/yitc-verify-sandbox-*` argument (never by process name — a host nginx is untouchable BY
        CONSTRUCTION), is past its age floor, is owned by THIS uid, and its sandbox root is
        referenced by NO live non-candidate process; the kill re-validates identity before each signal.
      • (T-11234) that PROCESS class has its OWN, much shorter floor —
        `SWEEP_ORPHAN_PROC_MIN_AGE_HOURS` (15 min) instead of the 24h directory retention — and it
        applies ONLY when the process's own sandbox ROOT is PROVABLY GONE from disk. That is the one
        fact that establishes orphanhood positively rather than by elapsed time, so the long floor
        (which is correct for a DIRECTORY, whose only abandonment evidence IS age) buys nothing here:
        four leaked nginx masters sat 16-20h behind it on 2026-08-17 with their sandbox directories
        already deleted, blocking `worktree adopt` recovery for that whole time. A `-p` process whose
        root still EXISTS keeps the full floor, and every other fence is unchanged.
    Swept: stale (age>max-age, not-live) DETACHED pinned-verify worktrees + abandoned `work/<slug>`
    worktrees (`git worktree remove --force` + `worktree prune`); orphan plain <tmp>/yitc-* dirs of the
    derived cohort that are NOT registered worktrees and are held by no live process (`shutil.rmtree`) —
    the residual leak the at-source `finally` cannot catch under a killed/timed-out land or an OOM-kill;
    and (T-10928) UNREGISTERED leftover dirs directly under the worktree parent `<repo>-wt/` that carry
    NO `.git` — de-registered residue git can neither track nor land from, previously covered by NOTHING.
    NOT swept, and DOCUMENTED here as the contract's stated exclusion (T-10928 audit-pre, AC1 second
    horn): an unregistered dir under that parent that DOES carry a `.git`, and any dot-dir there. The
    `.git` carrier is ambiguous — a pruned-but-ADOPTABLE worktree, or a nested repo — and it is not this
    hygiene sweep's to resolve: recovery is `worktree adopt` (or manual cleanup once adoption is ruled
    out), the SAME adopt-not-sweep rule registered worktrees get. A dot-dir is sibling STATE, never a
    worktree leaf. (Measured on the real fleet 2026-08-12: the exclusion costs NOTHING today — all 14
    leftovers carry no `.git`, and every `.git` carrier under that parent is a REGISTERED worktree.)
    --dry-run lists WOULD-remove + skip-reasons, acts on nothing.
    Emits one `worktree_swept` event (SPEC-0025 additive, no upfront enum) on ACTUAL removal only.
    EXIT CODE (T-10891): 0 when every removal succeeded OR failed only in the ONE recognised
    permanently-impossible class (`_removal_failure_is_expected_residue` — recorded once, reported
    every run, never alerted); NON-ZERO the moment ANY removal fails for a cause that class does not
    positively cover, incl. a mixed run where a recognised residue is present too. --dry-run removes
    nothing and therefore never exits non-zero.
    FAIL-CLOSED: if `git worktree list` cannot be read, the whole sweep ABORTS (removes nothing) — without
    the inventory a live registered worktree cannot be told from an orphan temp dir."""
    import glob as _glob
    import shutil
    import fnmatch as _fnmatch
    import tempfile
    if _tmp_glob_patterns is None:
        # DERIVED, not listed (T-10855). `_tmp_base` is injectable so a test can drive the REAL derived
        # cohort inside its own sandbox instead of polluting (or trusting) the host's /tmp.
        base = Path(_tmp_base) if _tmp_base is not None else Path(tempfile.gettempdir())
        _tmp_glob_patterns = tuple(str(base / f"{p}*") for p in _created_tmp_prefixes(Path(REPO_ROOT)))
    dry = bool(getattr(args, "dry_run", False))
    requested_hours = float(getattr(args, "max_age_hours", None) or 24.0)
    # HARD SAFETY FLOOR (audit-post absorption, T-9532): the pinned temp dirs + detached pinned-verify
    # worktrees carry NO session stamp, so for them age is the ONLY liveness proxy. A land's pinned verify
    # lives FAR under an hour (the per-file verify timeout is 300s; a whole pinned re-run is bounded well
    # below 1h), so NOTHING younger than this floor can be a dead leftover — clamping below it would risk
    # racing an in-flight land. So the effective retention is never below SWEEP_MIN_AGE_HOURS, regardless
    # of a (mis)configured lower --max-age-hours. The stamp/proc-liveness checks above are the FINER signal
    # for stamped worktrees; this floor is the unstamped-dir safety guarantee.
    SWEEP_MIN_AGE_HOURS = 1.0
    max_age_hours = max(requested_hours, SWEEP_MIN_AGE_HOURS)
    retention_sec = max_age_hours * 3600.0
    now = time.time()

    def _age_sec(p) -> float:
        try:
            return now - os.path.getmtime(p)
        except OSError:
            return -1.0   # unreadable mtime → negative → treated as YOUNG (never swept), fail-closed.

    main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT

    swept, skipped = [], []   # swept: (path, kind, label, age) ; skipped: (path, reason)

    # PAIRED liveness probe for UNSTAMPED temp dirs (T-10855). Computed ONCE, lazily — only a run that
    # actually has a temp-dir candidate pays the /proc walk; a run with none never touches it.
    _held: list = []

    def _in_use(path: str) -> bool:
        if not _held:
            _held.append(_live_held_paths())
        paths, argv = _held[0]
        pref = str(path).rstrip(os.sep) + os.sep
        return any(p == str(path) or p.startswith(pref) for p in paths) or str(path) in argv

    # ── Category A: registered git worktrees ──────────────────────────────────────────────────────
    r = _run_git_cap(["worktree", "list", "--porcelain"], REPO_ROOT)
    if r.returncode != 0:
        # FAIL-CLOSED (audit-post HIGH absorption, T-9532): without a readable worktree inventory we
        # cannot tell a LIVE registered worktree from an orphan temp dir, so removing ANYTHING (incl. a
        # /tmp/yitc-pinned-* path that may actually BE a live registered worktree) could delete live work.
        # Abort the whole sweep — never fall through to an empty-inventory sweep.
        print(f"worktree sweep: ABORT — `git worktree list` failed (rc={r.returncode}); cannot classify "
              f"orphans safely, swept NOTHING: {(r.stderr or r.stdout or '').strip()[:200]}")
        return
    entries, cur, br, det = [], None, None, False
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            if cur is not None:
                entries.append((cur, br, det))
            cur, br, det = line[len("worktree "):].strip(), None, False
        elif line.startswith("branch "):
            m = re.fullmatch(r"branch refs/heads/(.*)", line.strip())
            br = m.group(1) if m else None
        elif line.strip() == "detached":
            det = True
    if cur is not None:
        entries.append((cur, br, det))

    for path, branch, _detached in entries:
        p = Path(path)
        if branch == "main" or p == main_wt:
            continue   # NEVER the integration target.
        # FAIL-CLOSED ALLOWLIST (audit-post HIGH absorption, T-9532): sweep ONLY a worktree whose KIND
        # is POSITIVELY sweepable; skip anything else. The stamp carries no task provenance (only
        # {session_ref, started_at}), so a task worktree that is DETACHED or on a renamed branch would
        # NOT match `task/T-XXXX` by branch text — a denylist would sweep it and lose UNLANDED work.
        is_work_batch = bool(branch) and re.fullmatch(r"work/.+", branch) is not None
        is_pinned_detached = _detached and any(_fnmatch.fnmatch(str(p), pat) for pat in _tmp_glob_patterns)
        if not (is_work_batch or is_pinned_detached):
            if branch and re.fullmatch(r"task/T-\d{4,}", branch):
                reason = "task/T-XXXX worktree — recover via `worktree adopt`, never swept"
            elif _detached:
                reason = "detached non-pinned worktree — may be a task worktree (detached HEAD); fail-closed, never swept"
            else:
                reason = (f"unrecognized branch {branch!r} — not a sweepable kind "
                          f"(work/<slug> or pinned-verify temp); fail-closed, never swept")
            skipped.append((path, reason))
            continue
        age = _age_sec(p)
        if age < retention_sec:
            skipped.append((path, f"too young ({age / 3600:.1f}h < {max_age_hours}h)"))
            continue
        stamp = _read_worktree_stamp(p)
        if _stamp_is_own(stamp):
            skipped.append((path, "own-session stamp"))
            continue
        ref = (stamp or {}).get("session_ref")
        if ref and _session_proc_alive(ref):
            skipped.append((path, f"owner session {ref} still alive"))
            continue
        if is_pinned_detached and _in_use(path):
            # An UNSTAMPED temp worktree carries no session_ref, so the proc-alive check above cannot
            # speak for it — the held-path probe is its only liveness signal (T-10855).
            skipped.append((path, "in use by a live process"))
            continue
        if is_work_batch:
            # THE MERGE-STATE FENCE (T-11285). Every guard above reads a PROXY for "spent" — an
            # mtime, a stamp, a pid. None of them can see the one fact that decides whether removing
            # this directory destroys anything: does the BRANCH carry commits `main` does not? A
            # `work/<slug>` batch is precisely where a newly filed card lives before its first land,
            # so for this kind the proxy and the fact routinely disagree.
            # MEASURED (2026-08-17, fingerprint worktree-sweep-removes-a-work-batch-whose-branch-
            # still-carries-unlanded-commits): this verb removed `work/cross-triage-round-2` while its
            # branch carried 5 unlanded commits including three freshly filed task cards. Nothing was
            # lost from git — the branch survived — but every view of "what still needs landing" in
            # this repo derives from `git worktree list`, so the pending land silently dropped out of
            # all of them and its absence was indistinguishable from having landed. The loss surfaced
            # 16 hours later, by accident, via an unrelated file-overlap hint.
            # ASKED OF GIT, NEVER OF A STORED MARKER, and THREE-VALUED on purpose: a stored "has
            # unlanded work" flag would be exactly as stale as the mtime it replaced, and a bare
            # `int(out or 0)` would read every plumbing failure as 0 == "not ahead" == sweep — the
            # two-valued-over-a-three-valued-reality shape `lessons/carving-an-exception-into-a-fail-
            # closed-gate` §1 names. `_land_commits_not_in_base` (REUSED, CHARTER §P1 F1 — the
            # module's existing ahead-count primitive, not a second one) reserves `None` for "the
            # question was not ANSWERED" (nonzero git exit / missing rev / non-integer output), so
            # only a PROVEN zero can reach the removal below.
            # Placed LAST among the guards deliberately: this is the only one that costs a
            # subprocess, and the verb runs 48x/day under the crontab, so a candidate already spared
            # by age, stamp or liveness never pays for it.
            ahead = _land_commits_not_in_base(p, "main", _run_git_cap=_run_git_cap)
            if ahead is None:
                skipped.append((path, f"unlanded-commit count for {branch} UNREADABLE (git could not "
                                      f"answer) — fail-closed, never swept"))
                continue
            if ahead > 0:
                skipped.append((path, f"branch {branch} is {ahead} commit(s) ahead of main — carries "
                                      f"UNLANDED work; recover via `worktree adopt --work`, never swept"))
                continue
        swept.append((path, "worktree", branch or "(detached)", age))

    # ── Category B: orphan /tmp pinned temp dirs that are NOT registered worktrees ────────────────
    registered = set()
    for p, _b, _d in entries:
        try:
            registered.add(Path(p).resolve())
        except OSError:
            pass
    for pat in _tmp_glob_patterns:
        for path in _glob.glob(pat):
            try:
                if Path(path).resolve() in registered:
                    continue   # a live/handled worktree — classified in Category A, not here.
            except OSError:
                pass
            age = _age_sec(path)
            if age < retention_sec:
                skipped.append((path, f"too young ({age / 3600:.1f}h < {max_age_hours}h)"))
                continue
            if _in_use(path):
                skipped.append((path, "in use by a live process"))
                continue
            swept.append((path, "tmpdir", "(yitc temp)", age))

    # ── Category D: UNREGISTERED leftover dirs under the worktree parent (T-10928) ────────────────
    # THE GAP this closes: Category A covers only worktrees git still KNOWS about, and Category B only
    # the /tmp cohort — so a directory left under `<repo>.parent/<repo>-wt/` AFTER git stopped tracking
    # it (a pruned/partially-removed worktree) was covered by NOTHING. 14 had accumulated by 2026-08-10,
    # the oldest 68 days, and each one keeps firing `task file`'s in-flight-intent-overlap advisory for a
    # card that reads done on main — a real recurring duplicate-check cost, not a hypothetical.
    #
    # POSITIVE-IDENTIFICATION (the same fail-closed shape as the Category A allowlist — reclaim only a
    # kind we can PROVE is spent, skip everything else):
    #   • DIRECT CHILD of the worktree parent only — no recursion, so a nested dir inside a live
    #     worktree can never be reached;
    #   • NOT in the `git worktree list` inventory (a registered worktree stays adopt-not-sweep, ALWAYS —
    #     sweeping one would destroy an in-flight worker's uncommitted work);
    #   • carries NO `.git` entry. This is the load-bearing guard and the whole safety argument: without
    #     a `.git` the directory is not a worktree to git at all — it has no branch, no index, no object
    #     store, so NOTHING in it can ever be committed or landed. Its content is unrecoverable-by-git
    #     residue. A dir that DOES have a `.git` yet is absent from the inventory is AMBIGUOUS (a pruned
    #     but adoptable worktree, or a nested repo) → skipped, recovery is `worktree adopt`;
    #   • past the SAME clamped retention (so the hard SWEEP_MIN_AGE_HOURS floor applies) — an unreadable
    #     mtime reads as YOUNG and is kept, so a dir being created right now can never be raced;
    #   • held by NO live process, and not own-session-stamped / not owned by a still-alive session —
    #     the same liveness pair the other categories use, no new store.
    if _wt_parent is not None:
        parent = Path(_worktree_parent_dir(main_wt) if _wt_parent is _DERIVE_WT_PARENT else _wt_parent)
        try:
            children = sorted(parent.iterdir())
        except OSError:
            children = []   # no parent dir yet (or unreadable) → nothing to reclaim, never an error.
        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            if child.name.startswith("."):
                # NOT a worktree leaf. A worktree's leaf name is a BRANCH leaf (`T-XXXX` or a `--work`
                # slug) and is never dot-prefixed, so a dot-dir here is sibling STATE, not residue —
                # `<parent>/.yitc/` holds the pending discussion drafts, whose own mtime reads old
                # (1617h on 2026-08-12) while its CONTENTS are live. Caught by this card's own
                # pre-merge dry-run; without the guard the first real sweep would have deleted them.
                skipped.append((str(child), "dot-dir — sibling state, not a worktree leaf; never swept"))
                continue
            try:
                resolved = child.resolve()
            except OSError:
                continue
            if resolved in registered or resolved == Path(main_wt).resolve():
                continue   # registered (Category A) or the main checkout — never reclaimed here.
            if (child / ".git").exists():
                skipped.append((str(child), "unregistered but carries .git — ambiguous (adoptable "
                                            "worktree or nested repo); fail-closed, recover via `worktree adopt`"))
                continue
            age = _age_sec(child)
            if age < retention_sec:
                skipped.append((str(child), f"too young ({age / 3600:.1f}h < {max_age_hours}h)"))
                continue
            stamp = _read_worktree_stamp(child)
            if _stamp_is_own(stamp):
                skipped.append((str(child), "own-session stamp"))
                continue
            ref = (stamp or {}).get("session_ref")
            if ref and _session_proc_alive(ref):
                skipped.append((str(child), f"owner session {ref} still alive"))
                continue
            if _in_use(str(child)):
                skipped.append((str(child), "in use by a live process"))
                continue
            swept.append((str(child), "leftover-dir", "(unregistered, no .git)", age))

    # ── Category C: orphan verify-sandbox PROCESSES (T-10857) ────────────────────────────────────
    # The residual leak neither category above can reach: a land-verify sandbox run may leave an nginx
    # master alive holding its `-p /tmp/yitc-verify-sandbox-*` root — 27 of them had accumulated on the
    # shared host by 2026-08-09, the oldest 23 DAYS, each holding ephemeral ports the next sandbox's
    # allocator must route around. The sandbox DIR sweep and the at-source teardown fix are separate
    # concerns (peer tasks); this reaps the PROCESS.
    #
    # SAME TWO-PART FENCE as the dir sweep above, and a reap happens only when EVERY guard passes:
    #   • IDENTITY — a candidate is selected ONLY by POSITIVELY carrying a `-p <sandbox root>` argument
    #     (`_sandbox_prefix_arg`). The process NAME is never read, so a HOST nginx is untouchable by
    #     construction. Our own pid is excluded.
    #   • AGE — TWO floors since T-11234, chosen per candidate by a fact about the world. A candidate
    #     whose sandbox ROOT is PROVABLY GONE from disk takes the class's own short floor
    #     (`SWEEP_ORPHAN_PROC_MIN_AGE_HOURS`, 15 min — since T-11538 in the identity-less resident
    #     cohort too, on the identical fact); one whose root still exists — or cannot be
    #     proven absent — keeps the shared clamped `retention_sec` (so the hard SWEEP_MIN_AGE_HOURS
    #     floor still applies to it). The split is the classes' evidence, not a loosening: age is the
    #     only abandonment signal a leaked DIRECTORY has, whereas a root that has vanished proves the
    #     owning run is over (it is `rmtree`d only after the run's own residents are reaped), so the
    #     process is orphaned from that moment and another 20 hours of waiting adds nothing. In BOTH
    #     cases a LIVE verify's nginx is seconds old and can never be reached, and an unreadable
    #     start-time reads as YOUNG (-1.0) and is kept.
    #   • OWNERSHIP — a process owned by another uid is skipped (this is a SHARED host; `os.kill` would
    #     EPERM anyway, so signalling it could only ever be noise or harm).
    #   • OCCUPANCY — the sandbox is still referenced by a live process (some NON-candidate pid whose
    #     argv mentions it, or whose cwd is inside it) ⇒ the sandbox is still in use, keep. Other
    #     CANDIDATES are excluded from the occupant set on purpose: a master's own prefixed workers must
    #     not make the cohort self-blocking.
    #     T-11088 — this fence is evaluated against the sandbox ROOT, not only the `-p` value. It is the
    #     ACTIVE-RUN fence (the owner's hard fence: a live run is NEVER touched), and the `-p` value alone
    #     cannot carry it: a RUNNING verify's nginx is given `<root>/box<N>/tmp/tmp<X>/sb` while the fleet
    #     holding the sandbox lives elsewhere under `<root>` (measured: cwd `<root>/box97/tmp/tmp…/main`),
    #     so a root-blind check finds NO holder and leaves an active run standing on the age floor alone —
    #     and a verify queued behind the SPEC-0132 admission gate can legitimately outlive that floor (the
    #     same reason `_live_held_paths` exists for the dir sweep). Widening the fence can only ever SPARE
    #     more processes, never kill more.
    # The kill itself re-validates identity immediately before each signal (`_reap`, the PID-reuse race).
    #
    # NOT A KILL — the fail-open REPORT (T-11088). A process that resides in a sandbox but carries NO `-p`
    # identity (the `pre_burn.py` CPU-burn pairs of E-0059 / T-11087 are this shape: cwd inside
    # `<root>/box*/tmp/tmp*/`, no `-p` anywhere) is a DIFFERENT population, which this positive
    # discriminator does not and must not match — cwd-based selection would put every child of a live
    # verify one guard away from a kill. Per the owner's fence such a process is left alone and REPORTED,
    # never killed on a guess, so it stops being invisible without becoming a target.
    #
    # A SIBLING extension of this verb (T-11062, orphan journal sidecar locks) composes rather than
    # collides: each category only APPENDS to the shared `skipped` / `removed` accumulators under its own
    # `kind`, and this block reads nothing another category writes.
    try:
        procs = _proc_scan() or []
    except Exception:
        procs = []          # a scan failure reaps NOTHING — fail-closed, never a fall-through to blind kills.
    # The SELECTION (identity + age + uid + the ACTIVE-RUN occupancy fence) lives in the shared
    # `select_orphan_sandbox_procs` (T-11089), which the nightly's read-only host axis calls too — ONE
    # orphan definition, so the reaper and the reader can never drift apart. What stays HERE is what
    # only the sweep owns: the kill and the printing. The KILL cohort is deliberately the single
    # `_sandbox_prefix_glob` it has always been — the nightly REPORTS wider, this reaps exactly as before.
    # T-11234 — the sandbox-PROCESS class gets its OWN, much shorter floor, and the DIRECTORY floor
    # above is untouched. `min(...)`, never `max(...)`: this floor may only ever SHORTEN the wait, so
    # an explicitly LOWER `--max-age-hours` is honoured rather than raised back up to 15 minutes. It
    # is passed for BOTH cohorts since T-11538 — the identity-less resident class is selected on the
    # same proven-absent-root fact, so it takes the same floor; see the predicate's `_floor_for`, the
    # one expression that decides this for either cohort.
    orphan_proc_hours = min(max_age_hours, SWEEP_ORPHAN_PROC_MIN_AGE_HOURS)
    _sel = select_orphan_sandbox_procs(
        procs, retention_sec=retention_sec, globs=(_sandbox_prefix_glob,),
        self_pid=os.getpid(), uid=os.geteuid(), age_of=_proc_age_sec,
        age_label=f"{max_age_hours}h",
        orphan_retention_sec=orphan_proc_hours * 3600.0,
        orphan_age_label=f"{orphan_proc_hours}h (proven-orphan process floor)")
    proc_swept = _sel["candidates"]
    # T-11217 — the SECOND reap cohort: residents whose own sandbox root is PROVABLY gone. Kept as its
    # own list all the way to the signal because it is re-validated by a different positive fact (the
    # cwd root, not a `-p` value), and printed under its own STALE label so the run's output never
    # claims a `-p` that does not exist. What remains in `residents` is the untouched owner fence.
    resident_swept = _sel["orphan_residents"]
    skipped.extend(_sel["skipped"])
    skipped.extend(_sel["residents"])

    # ── Category E: orphan PERSISTENT journal sidecar locks (T-11062) ─────────────────────────────
    # THE GAP: a sidecar is a FILE in the temp ROOT, so no category above can see it — Category B
    # globs the DERIVED `mkdtemp` prefix cohort, and `yitc-journal-` is not a mkdtemp prefix. 808615
    # of them had accumulated by 2026-08-13, growing ~130K/day, while this verb ran every 30 minutes
    # and reported itself healthy. The MINTER is fixed (T-11061 co-locates a scratch container's
    # sidecar), and systemd-tmpfiles expires them far slower than they are minted; this is the
    # BACKSTOP that reaps what is already stranded and whatever a future path still strands.
    #
    # The GLOB comes FIRST and the keep-set is built only if it found something — two reasons, both
    # load-bearing: (1) a run with no candidate locks never pays the namespace walk at all, so the
    # steady state after the backlog drains costs nothing; (2) any journal that existed at glob time
    # is then GUARANTEED to be in the keep-set, and the age fence covers anything created after.
    lock_root = Path(_lock_root) if _lock_root is not None else events.persistent_lock_root()
    try:
        lock_paths = sorted(_glob.glob(str(lock_root / events.PERSISTENT_LOCK_GLOB)))
    except OSError:
        lock_paths = []
    lock_scan: dict = {}
    lock_sel: dict = {"candidates": [], "skipped": [], "abort": None, "considered": 0}
    if lock_paths:
        lock_scan = _journal_keys()
        lock_sel = select_orphan_journal_locks(
            lock_paths, live_keys=lock_scan["keys"], scan_error=lock_scan["error"],
            retention_sec=retention_sec, uid=_euid(), age_of=_age_sec, stat_of=_lstat,
            age_label=f"{max_age_hours}h")

    # ── report + act ──────────────────────────────────────────────────────────────────────────────
    label = "DRY-RUN — would remove" if dry else "removing"
    print(f"worktree sweep ({label}; max-age {max_age_hours}h): {len(swept)} stale, "
          f"{len(proc_swept) + len(resident_swept)} orphan sandbox process(es), {len(skipped)} skipped")
    removed = []
    residue, unexpected = [], []   # T-10891: the ONE recognised permanent class vs everything else.
    partial = []                  # T-11750: unregistered-but-not-empty — its OWN outcome.
    archive_residue = []           # T-10976: the recognised TRANSIENT class, still on disk this run.
    cured = []                     # T-11855: a curable self-owned EACCES the sweep FIXED and removed.
    for path, kind, lbl, age in swept:
        print(f"  STALE {kind}: {path}  [{lbl}, age {age / 3600:.1f}h]")
        if dry:
            continue
        errnos: list = []
        if kind == "worktree":
            _run_git_cap(["worktree", "remove", "--force", path], REPO_ROOT)
            if Path(path).exists():
                _rmtree_collect(path, errnos)
        else:
            _rmtree_collect(path, errnos)
        if not Path(path).exists():
            removed.append({"path": path, "kind": kind, "label": lbl})
        elif (acl := _acl_leftover(path, _chmod=_acl_chmod)) is not None:
            # T-10976: the leftover `land` leaves BY DESIGN. Evaluated BEFORE the sticky-bit class
            # (it is the more specific shape; the two are disjoint — a foreign-owned path under the
            # system tempdir carries no `.yitc/transcript-archive`). Each arm composes its COMPLETE
            # message here: nothing falls through to the loud text below, so an operator reading this
            # run never gets a recognised-residue line and a "cause not recognised" line for one path.
            if acl == "cleared":
                removed.append({"path": path, "kind": kind, "label": lbl})
                print(f"    ACL-protected .yitc/transcript-archive leftover cleared: {path} "
                      f"(left by `land` by design; the acl-watcher had already unlocked it)")
            else:
                archive_residue.append(path)
                print(f"    ! could not remove {path} — EXPECTED: an ACL-protected "
                      f".yitc/transcript-archive left by `land` by design, still write-stripped by the "
                      f"acl-watcher (transient; reported every run, exit unaffected)")
        elif (errno.EACCES in [e for e in errnos if e is not None]
                and _cure_removal(path, errnos, _rmtree_collect=_rmtree_collect, _euid=_euid)):
            # T-11855 — CURE BEFORE THE CLASSIFIERS. A removal that failed with EACCES may simply be
            # a directory this user OWNS but stripped of its own write bit (the measured
            # `/tmp/yitc-verify-sandbox-*` class, reported as `cause not recognised` on 161 cron
            # runs): restore the bit on the self-owned dirs under it and retry ONCE. Gated on a
            # CAPTURED EACCES, so no other failure ever reaches the chmod.
            #
            # WHY IT SITS *AFTER* THE ACL ARM AND *BEFORE* THE CLASSIFIERS — specific shape first,
            # generic cure second. Running it earlier would let it delete the NON-archive survivors
            # that are the only thing making `_acl_protected_archive_leftover` REFUSE a near-miss, so
            # a shape that is stuck today could become recognised-and-cleared by way of the cure.
            # That would widen an existing recogniser's reach, which this card explicitly does not
            # do. Here the cure changes nothing about what the recognisers accept: it only converts
            # failures that would have fallen through to the LOUD branch into real removals, and a
            # path still present after the retry falls through to those classifiers unchanged.
            cured.append(path)
            removed.append({"path": path, "kind": kind, "label": lbl})
            # Named, never silent: an operator must be able to see that the sweep FIXED something,
            # rather than that a failing path quietly stopped failing.
            print(f"    CURED {path} — a self-owned directory had lost its own write bit "
                  f"[{_errno_names(errnos)}]; owner write+execute restored and the removal retried")
        elif _classify_residue(path, errnos, _lstat=_lstat, _euid=_euid):
            # The one permanently-impossible class: say so plainly (a reader must not mistake this
            # for the loud line), keep exit 0, and record it once below.
            residue.append(path)
            print(f"    ! could not remove {path} — EXPECTED residue: foreign-owned under a sticky "
                  f"parent, unremovable by this user (permanent; recorded once, not alerted)")
        elif _partial_removal(path, kind):
            # T-11750 — the THIRD outcome: not a success (files survive) and not a plain failure
            # (the registration is already gone, so `worktree prune` below will unregister it). Said
            # in its own words so a reader cannot read it as «nothing happened»; still LOUD on exit.
            partial.append((path, _errno_names(errnos)))
            print(f"    ! PARTIAL removal of {path} — the worktree registration is GONE (`.git` "
                  f"removed; `worktree prune` will unregister it) but files SURVIVE on disk"
                  + (f" [{_errno_names(errnos)}]" if _errno_names(errnos) else ""))
        else:
            unexpected.append((path, _errno_names(errnos)))
            print(f"    ! could not fully remove {path} (left in place)"
                  + (f" [{_errno_names(errnos)}]" if _errno_names(errnos) else ""))
    if not dry:
        _run_git_cap(["worktree", "prune"], REPO_ROOT)
    # Category C act + report (T-10857). A host-level kill is NEVER silent: every reaped pid is named
    # with its age and the prefix that selected it, so the reap is reconstructible from the run's output
    # alone — and folded into the SAME `worktree_swept` event as the dirs (no second event type).
    if proc_swept:
        print(f"worktree sweep: {len(proc_swept)} orphan verify-sandbox process(es) "
              f"{'would be reaped' if dry else 'to reap'}")
    for pid, pref, age in proc_swept:
        print(f"  STALE sandbox-process: pid {pid}  [-p {pref}, age {age / 3600:.1f}h]")
        if dry:
            continue
        if _reap(pid, pref, _sandbox_prefix_glob):
            removed.append({"kind": "sandbox-process", "pid": pid, "prefix": pref})
        else:
            print(f"    ! could not reap pid {pid} (left running)")
    # T-11217 — the orphan-RESIDENT cohort, same reporting discipline: every reaped pid is named with
    # its age and the ABSENT root that selected it, so the reap is reconstructible from the run's
    # output alone, and it folds into the SAME `worktree_swept` event under its own `kind`.
    if resident_swept:
        print(f"worktree sweep: {len(resident_swept)} orphan sandbox resident(s) whose sandbox is GONE "
              f"{'would be reaped' if dry else 'to reap'}")
    for pid, sroot, age in resident_swept:
        print(f"  STALE sandbox-orphan-resident: pid {pid}  [cwd-root {sroot} GONE, age {age / 3600:.1f}h]")
        if dry:
            continue
        if _reap(pid, None, _sandbox_prefix_glob, cwd_root=sroot):
            removed.append({"kind": "sandbox-orphan-resident", "pid": pid, "prefix": sroot})
        else:
            print(f"    ! could not reap pid {pid} (left running)")
    # Category E act + report (T-11062). AGGREGATED on purpose, unlike every category above: this
    # cohort is measured in the TENS OF THOUSANDS (48476 present when this shipped) and the verb runs
    # 48x/day into a cron log, so a per-path line — and a per-path `removed` entry in the emitted
    # event — would be a denial-of-service on its own observability. What survives is what a reader
    # actually needs: the counts, the keep-set the decision rested on, a bounded sample, and every
    # assumption the scan had to make, printed EVERY run rather than silently held.
    if lock_sel["abort"]:
        # Not a removal failure, so the T-10891 exit contract is untouched: this run REFUSED to try.
        print(f"worktree sweep: journal-lock reap SKIPPED — keep-set untrustworthy, removed nothing: "
              f"{lock_sel['abort']}")
    elif lock_paths:
        lock_swept = lock_sel["candidates"]
        buckets: dict = {}
        for _p, reason in lock_sel["skipped"]:
            buckets[reason.split(" (")[0].split(" —")[0]] = buckets.get(reason.split(" (")[0].split(" —")[0], 0) + 1
        note = (f"keep-set {lock_scan.get('journals', 0)} live journal(s) over "
                f"{lock_scan.get('roots', 0)} mount root(s); "
                f"{lock_scan.get('unreachable', 0)} unreachable subtree(s) dismissed by proof; "
                f"{lock_scan.get('vanished', 0)} vanished mid-walk")
        unlistable = lock_scan.get("unlistable") or []
        if unlistable:
            # NAMED every run — the one assumption the consult let stand must never go silent.
            note += (f"; {len(unlistable)} unlistable-but-non-writable subtree(s) ASSUMED journal-free: "
                     + ", ".join(unlistable[:5]) + (f" (+{len(unlistable) - 5} more)" if len(unlistable) > 5 else ""))
        print(f"worktree sweep: {len(lock_swept)} orphan journal sidecar lock(s) of "
              f"{lock_sel['considered']} considered {'would be removed' if dry else 'to remove'} ({note})")
        for path, key, age in lock_swept[:5]:
            print(f"  STALE journal-lock: {path}  [key {key}, age {age / 3600:.1f}h]")
        if len(lock_swept) > 5:
            print(f"  … and {len(lock_swept) - 5} more orphan journal sidecar lock(s) (not listed)")
        for reason, n in sorted(buckets.items(), key=lambda kv: -kv[1]):
            print(f"  skip {n} journal-lock(s): {reason}")
        lock_failed = []
        if not dry:
            for path, _key, _age in lock_swept:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass          # already gone (a concurrent sweep) — the goal is met, not a failure.
                except OSError as e:
                    lock_failed.append(f"{path}: {e.strerror or e}")
            done = len(lock_swept) - len(lock_failed)
            if done:
                removed.append({"kind": "journal-lock", "count": done,
                                "oldest_age_hours": round(max((a for _p, _k, a in lock_swept), default=0.0) / 3600, 1),
                                "sample": [p for p, _k, _a in lock_swept[:5]]})
            if lock_failed:
                # Named, but NOT routed into the T-10891 exit contract: that contract classifies
                # DIRECTORY-removal failures, whose recognised classes (sticky-parent, ACL archive)
                # do not describe a sidecar file. A lock we could not unlink is simply reported and
                # retried next run — 48 chances a day — rather than paging on a cohort this size.
                print(f"worktree sweep: {len(lock_failed)} journal sidecar lock(s) could not be "
                      f"removed (reported, retried next run): {'; '.join(lock_failed[:3])}"
                      + (f" (+{len(lock_failed) - 3} more)" if len(lock_failed) > 3 else ""))
    for path, reason in skipped:
        print(f"  skip {path}: {reason}")
    # T-11750 — `partial` ALONE is enough to emit: a run that removed nothing but left a worktree
    # UNREGISTERED-with-files-behind has changed durable state, and a printed-only record of it would
    # vanish with the cron log. `removed` may legitimately be empty on such a run.
    if cured:
        # T-11855 — reported in its own words BEFORE the residue/failure lines: these paths would
        # have been the run's `cause not recognised` failures before the cure existed.
        print(f"worktree sweep: {len(cured)} curable removal failure(s) CURED (self-owned directory "
              f"missing its own write bit; owner write+execute restored, removal retried): "
              + ", ".join(cured))
    if (removed or partial) and not dry:
        _append_event("worktree_swept", None,
                      {"removed": removed, "count": len(removed), "max_age_hours": max_age_hours,
                       # T-11750: the partial state is DURABLE, not merely printed — a half-removed
                       # unregistered worktree must be reconstructible from the journal alone.
                       **({"partial": [{"path": p, "errnos": n} for p, n in partial]} if partial else {}),
                       # T-11855: the cure is DURABLE, not merely printed — it is this task's
                       # live-trigger adoption evidence and must survive the cron log.
                       **({"cured": list(cured)} if cured else {})},
                      events_path=main_wt / "events.jsonl")
        print(f"worktree_swept emitted ({len(removed)} removed"
              + (f", {len(partial)} partial)" if partial else ")"))
    print("host-completion step (X-0090 model): wire a host crontab line — "
          "`*/30 * * * * cd <repo> && bin/yitc-v2 worktree sweep` "
          "(host territory, NOT edited from a v2 worktree per D-0019).")
    # ── removal-failure loudness (T-10891) ───────────────────────────────────────────────────────
    # Recognised residue is QUIET (exit 0) but not invisible: recorded durably once, then reported
    # every run as plain text. Everything else is LOUD — a non-zero exit, which the host
    # `cron-notify.sh` wrapper already alerts off, so no second notification path is built here.
    if residue:
        print(f"worktree sweep: {len(residue)} permission-impossible residue path(s) left in place "
              f"(expected, exit unaffected): {', '.join(residue)}")
        if _record_residue_once(main_wt / "events.jsonl", residue, _append_event):
            print(f"deviation_captured emitted once (fingerprint {_RESIDUE_FINGERPRINT})")
    if archive_residue:
        # T-10976: quiet on the EXIT code, never quiet in the OUTPUT — every such path is named every
        # run, because a leftover that never clears must stay observable (eight of them accumulated
        # unnoticed under the crontab before the cron alert surfaced them, 2026-08-12). No journal
        # record: unlike the permanent class above this one ENDS when the acl-watcher unlocks.
        print(f"worktree sweep: {len(archive_residue)} ACL-protected transcript-archive leftover(s) "
              f"left in place (expected — `land` leaves them by design, exit unaffected): "
              f"{', '.join(archive_residue)}")
    if partial:
        # T-11750 — reported BEFORE the failure line and in its own words: this is the state the
        # reporter found unnamed (X-1139). Loud on the exit code like any survivor, but never
        # rendered as a plain failure, because «unregistered with files left» is a different
        # operator action (finish the removal by hand) than «nothing could be touched».
        print(f"worktree sweep: {len(partial)} PARTIAL removal(s) — worktree UNREGISTERED but files "
              f"left on disk (distinct from both success and failure; finish by hand): "
              + ", ".join(f"{p} [{n}]" if n else p for p, n in partial))
    if unexpected:
        # NOT masked by any expected residue above: an unrecognised failure is the whole point of
        # the exit code, so it is evaluated on its own list and named again here. T-11750 — the
        # summary now carries the ERRNO NAMES the run captured, so the load-bearing line can never
        # say less than the run knows (audit-pre finding absorbed). The phrase `cause not
        # recognised` is retained deliberately: it means «not one of the RECOGNISED CLASSES»
        # (sticky-parent, ACL-archive), which is orthogonal to whether an errno was captured, and it
        # is the pinned token the host cron-notify wrapper and the T-10891/T-10976 probes match on.
        print(f"worktree sweep: FAILED — {len(unexpected)} unexpected removal failure(s), cause not "
              f"recognised: " + ", ".join(f"{p} [{n}]" if n else p for p, n in unexpected))
    if partial or unexpected:
        sys.exit(1)



def _orphan_resume_task(tid: str, *, _find_task_yaml, state=None) -> "dict | None":
    """T-9317 (F-019) + T-10544 (X-0406): read the MAIN-checkout task YAML; return it iff it is
    IN-PROGRESS — the orphan-resume CANDIDATE that `worktree new --task` should RECREATE-a-worktree-
    for + resume, rather than refuse-to-claim (a non-`ready` task fails `_assert_task_claimable`).
    None otherwise (the normal claim path). Read-only; the resume itself is applied in the new
    worktree.

    THE NO-LIVE-WORKTREE PRECONDITION IS THE CALL SITE'S, NOT THIS FN'S — `cmd_worktree_new` consults
    this ONLY once `_worktree_path_for_branch(branch)` is None/absent. So the effective rule is
    «in-progress + NO live worktree → re-enter», and this fn answers only the CANDIDATE half.

    T-10544 dropped an `and task.get("paused_at")` conjunct that made the whole path unreachable for
    the case it was built for. `paused_at` was never the safety property (the absent worktree is), and
    requiring it excluded the very shape that cannot write it: a session KILLED after landing its ship
    commit mid-task (`land` removes worktree+branch at stage=Commit) — in-progress on main, no pause
    metadata, no worktree, and therefore NO governed way back in (boomrocket T-0165: `worktree new`
    refused the non-ready task, `task resume` refused for want of a writing worktree; the only exit was
    raw git + `worktree adopt`). Both admitted shapes are orphans by the same evidence:
      • paused with the worktree torn down at pause/land      — T-9317 / F-019
      • died after a mid-task land (no pause metadata)        — T-10544 / X-0406
    WHY WIDENING IS SAFE — the other in-progress states cannot reach here: `worktree park` flips the
    task back to `ready`; a `blocked-on-land` escalation keeps its worktree LIVE (so the call site
    short-circuits, and the claim path's T-0362 own/foreign-stamp guards still fire); and a CONCURRENT
    UNLANDED claim by a live peer leaves main-side status `ready` (a claimant's flip lives only in its
    worktree until land), so it can never be misread as an orphan. Main-side in-progress therefore
    PROVES the claim already landed, and the absent worktree proves that session is gone."""
    path = _find_task_yaml(tid)
    if path is None:
        return None
    task = state.load_str(path.read_text(encoding="utf-8")) or {}
    if task.get("status") == "in-progress":
        return task
    return None



def _work_resume_candidate(branch: str, main_wt: "Path", *, _run_git_cap) -> "dict | None":
    """T-11286 — the WORK-axis mirror of `_orphan_resume_task`: return the `work/<slug>` branch's tip
    iff the branch EXISTS — the re-entry CANDIDATE that `worktree new --work` should RE-ATTACH a
    worktree to, rather than refuse. None otherwise (the normal fresh-batch path). Read-only; the
    re-attach itself happens at the call site.

    THE NO-LIVE-WORKTREE PRECONDITION IS THE CALL SITE'S, NOT THIS FN'S — exactly as for
    `_orphan_resume_task`: `cmd_worktree_new` consults this ONLY once `_worktree_path_for_branch(branch)`
    is None/absent. So the effective rule is «branch exists + NO live worktree → re-enter», and this fn
    answers only the CANDIDATE half. Keeping the two halves split the same way on both axes is what
    stops them drifting apart.

    WHY A WORK BATCH NEEDS ONE AT ALL (measured 2026-08-18, fingerprint
    `worktree-sweep-removes-a-work-batch-whose-branch-still-carries-unlanded-commits`): after a sweep
    removed the worktree, the branch's commits survived in git but every governed door was shut —
    `land --branch work/<slug>` resolves the branch THROUGH its worktree and dies "no linked worktree
    found on branch"; a raw `git worktree add` recreation leaves the locus UNSTAMPED, which the
    identity guard then refuses (T-0362 / SPEC-0137); and `worktree adopt --work` (T-11284) RE-STAMPS
    an existing worktree, so it has nothing to adopt when the worktree is what is missing. The exit
    actually taken was a fresh batch plus a hand file copy, which loses provenance. The TASK axis has
    had this door since T-9317 and had it WIDENED once (T-10544 / X-0406) after the same class of dead
    end; this is that door on the other axis of the same verb.

    WHY THIS IS SAFE WITHOUT A STATUS-LIKE CONJUNCT — a work batch has no card, so there is no status
    to read; the branch's own existence IS the evidence, and the safety property is the SAME one the
    task axis relies on: the ABSENT worktree. A LIVE batch never reaches here (the call site
    short-circuits on `_worktree_path_for_branch`, and the branch-exists double-claim refusal still
    fires), and a branch freed while its holder is still running is caught DOWNSTREAM of this read by
    the unchanged live-holder gate (stamp-liveness + cwd holders, T-10885) — this fn adds no bypass to
    either."""
    r = _run_git_cap(["rev-parse", "--verify", "--quiet", branch], main_wt)
    head = (r.stdout or "").strip()
    if r.returncode != 0 or not head:
        return None
    return {"branch": branch, "head": head}



def _claim_task(tid: str, tasks_dir: "Path", events_path: "Path", *, _append_event, _die, _governing_contract_for, _requires_incomplete, _task_decomposed_from_pre_executing_plan, _write_task_transition, CLAIM_DELIVERY_MARKER, extra_event_data: "dict | None" = None, state=None, task_mod=None) -> dict:
    """Claim a task ready → in-progress (Stage 1) by writing into a SPECIFIC tasks_dir +
    events_path — the single claim mutator (per T-0124 / D-0037 option B). The CLAIM (status
    flip + current_stage=Analysis + task_picked event) is written where the WORK happens — the
    writing worktree — so it reaches main only via `land`, never as a direct-to-main write.
    `requires:` is validated against the module-global tasks/decisions (the main checkout the
    worktree was just branched from — identical content at creation). Returns the claimed task.

    `extra_event_data` (T-11307) merges extra keys into the emitted `task_picked` — the ONLY reason
    it exists is so a SECOND ENTRY to this one mutator stays discriminable in the journal without
    minting a new event family (CHARTER §P1 F2/F3). `None` (every `worktree new --task` call) is
    byte-identical to the pre-T-11307 emit. It may NOT overwrite the claim's own keys: the merge is
    applied UNDER them, so `current_stage` / `trigger` / `governing_contract` are un-forgeable."""
    import yaml
    path = next(tasks_dir.glob(f"{tid}-*.yaml"), None)
    if path is None:
        legacy = tasks_dir / f"{tid}.yaml"
        path = legacy if legacy.exists() else None
    if path is None:
        _die(f"{tid}: task YAML not found in {tasks_dir}")
    task = state.load_str(path.read_text(encoding="utf-8"))
    if not isinstance(task, dict):
        _die(f"{tid}: task YAML did not parse as a mapping")
    status = task.get("status")
    if status != "ready":
        _die(f"{tid} status={status!r} — claim requires status=ready (QUEUE §Picker logic)")
    blocked = _requires_incomplete(task.get("requires") or [])
    if blocked:
        lines = "; ".join(f"{r} {why}" for r, why in blocked)
        _die(f"{tid} has incomplete requires: {lines} — cannot claim (QUEUE §Picker logic)")
    # SPEC-0166: dispatchability gate (write-time re-validate). An imported card is claimable ONLY
    # when premise == 'verified'; the refusal derives ONLY from the two card fields (no ledger). Emit
    # the EXISTING claim_refused marker (reason=premise-unverified) — no new event family (P1 F3).
    premise_block = task_mod._premise_dispatch_block(task)
    if premise_block:
        _append_event("claim_refused", tid, {"reason": "premise-unverified",
                                             "premise": task.get("premise")}, events_path=events_path)
        _die(f"{tid} NOT claimable — {premise_block} (SPEC-0166 dispatchability gate).")
    pre = _task_decomposed_from_pre_executing_plan(task)   # SPEC-0070 §5 write-time re-validate (mirror
    if pre:                                                # of _assert_task_claimable — pre-create read-check)
        slug, pst = pre
        _append_event("claim_refused", tid,
                      {"reason": "plan-pre-executing", "plan": slug, "plan_status": pst},
                      events_path=events_path)
        _die(f"{tid} is decomposed_from plan {slug!r} at status={pst!r} (pre-`executing`) — not claimable "
             f"until the plan reaches `executing` (SPEC-0070 §5 claim-block, keyed on `decomposed_from`; "
             f"cut audited at decomposition→executing).")
    task["status"] = "in-progress"
    _write_task_transition(yaml, path, task, "Analysis")
    # T-0279/T-0291: the claim-time DELIVERY record of the Analysis stage-entry. `trigger` is the
    # ALWAYS-present, activation-independent marker that the Stage-1 procedure was surfaced at this
    # claim. T-0291 MIGRATED the marker value `before-analysis` → CLAIM_DELIVERY_MARKER
    # (`stage-entry:Analysis`) so claim-delivery evidence speaks ONE vocabulary with the delivery axis
    # (post-T-0289 the Analysis delivery axis IS stage-entry:Analysis); historical rows still carry the
    # legacy value (back-compat read via `_is_claim_delivery_marker`). `governing_contract` is the standard
    # active-only delivery-observability projection (mirror of task_filed / commit / close — SPEC-0013),
    # resolving through the SAME marker to the bound spec once it is active.
    _append_event("task_picked", tid, {
        **(extra_event_data or {}),
        "current_stage": "Analysis", "trigger": CLAIM_DELIVERY_MARKER,
        "governing_contract": _governing_contract_for(CLAIM_DELIVERY_MARKER)}, events_path=events_path)
    return task



def _resume_orphan_in_worktree(tid: str, tasks_dir: "Path", events_path: "Path", *, _apply_task_resume, _die, state=None) -> dict:
    """T-9317 (+ T-10544): apply the resume INSIDE a freshly-recreated worktree (mirror of
    `_claim_task` but for an already in-progress task). Loads the task YAML from `tasks_dir`,
    re-validates the orphan-resume invariant, then clears any pause metadata + emits `task_resumed`
    into the worktree journal (reaches main only via `land`). NO status flip (resume ≠ claim) — which
    is precisely what preserves chain-of-custody: the ORIGINAL `task_picked` (already on main with the
    landed claim) stands, and no second one is ever written.

    T-10544 widened the re-validation to match `_orphan_resume_task` (in-progress; `paused_at` no
    longer required — see that fn for why). Clearing the pause metadata is a harmless NO-OP for the
    never-paused shape (a session killed after a mid-task land), which is exactly what makes the same
    core serve both orphan kinds without a branch."""
    import yaml
    path = next(tasks_dir.glob(f"{tid}-*.yaml"), None)
    if path is None:
        legacy = tasks_dir / f"{tid}.yaml"
        path = legacy if legacy.exists() else None
    if path is None:
        _die(f"{tid}: task YAML not found in {tasks_dir}")
    task = state.load_str(path.read_text(encoding="utf-8"))
    if not isinstance(task, dict):
        _die(f"{tid}: task YAML did not parse as a mapping")
    if task.get("status") != "in-progress":
        _die(f"{tid}: not a resumable orphan (status={task.get('status')!r}) — expected in-progress "
             f"(paused or not: T-10544 admits a session killed after a mid-task land, which never "
             f"wrote pause metadata)")
    _apply_task_resume(yaml, path, task, events_path)
    return task



def _own_open_work_batches(main_wt, self_branch, *, _run_git_cap, _read_worktree_stamp,
                           _stamp_is_own) -> "list[tuple[str, str]]":
    """T-11197: the LIVE `work/<slug>` batches held by THIS session, excluding `self_branch`.

    Substrate = `git worktree list --porcelain` + the T-0362 worktree stamp — the two things
    `worktree new` already consults (no new store, no session-level counter: CHARTER §Principle 1
    view-over-new-entity, and the counter was weighed and NOT taken in the card).

    OWN-ONLY, and `work/`-ONLY, is the whole discrimination this helper exists for. The repo
    routinely carries 4-6 live worktrees from concurrent sessions; a hint that counted a peer's
    batch — or a `task/T-XXXX` lifecycle worktree, which is not a filing batch at all — would fire
    on essentially every creation and therefore mean nothing. The stamp answers WHOSE, and
    `_stamp_is_own` is the same fail-closed own-check the claim/resume/park gates use: an
    unstamped or foreign worktree is NOT own, so it is silently skipped.

    Returns [(branch, path), ...] sorted by branch. Fail-OPEN → [] on any git/stamp/identity
    error: this backs a report-only hint (CHARTER non-goal #7) and must never break a creation.
    """
    # The enumeration itself is inside the fail-open boundary, not just its RETURN CODE: this
    # helper's contract is "[] on any git/stamp/identity error", and a `_run_git_cap` that RAISES
    # (rather than returning nonzero) would otherwise escape it and lean entirely on the call
    # site's catch — a contract that is true only because of a caller is not the contract stated
    # in the docstring, and the next caller would inherit an unguarded helper (audit-post low).
    try:
        r = _run_git_cap(["worktree", "list", "--porcelain"], main_wt)
    except Exception:  # noqa: BLE001 — advisory substrate; a git fault is silence, never a break
        return []
    if r.returncode != 0:
        return []
    out, cur_path = [], None
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            cur_path = line[len("worktree "):].strip()
        elif line.startswith("branch ") and cur_path:
            br = line[len("branch "):].strip()
            if br.startswith("refs/heads/"):
                br = br[len("refs/heads/"):]
            if br.startswith("work/") and br != self_branch:
                try:
                    if _stamp_is_own(_read_worktree_stamp(Path(cur_path))):
                        out.append((br, cur_path))
                except Exception:  # noqa: BLE001 — advisory; an unreadable stamp is simply not-own
                    pass
            cur_path = None
    return sorted(out)



def _open_work_batch_hint_lines(batches: "list[tuple[str, str]]") -> "list[str]":
    """T-11197: the report-only lines telling a session it ALREADY holds an open filing batch.

    NOT «batch more». A `work/<slug>` batch is to be landed PROMPTLY and is explicitly not a
    long-lived misc branch, and a card cannot be dispatched until it is on main — so batching
    longer DELAYS dispatch. The discipline this states is ONE OPEN FILING BATCH AT A TIME, landed
    when you are READY TO DISPATCH FROM IT, not when you finish typing it.

    Why it is worth saying at all (measured 2026-08-16, one day of controller traffic): 42 `work/`
    lands cost 6188s = 103 minutes of pure queue wait before any of them started, at a
    near-CONSTANT 170-220s per land REGARDLESS of content — the cost is ADMISSION, not volume. A
    batch of one card and a batch of eight pay the same entry price, so a second batch opened out
    of tidiness rather than need buys a second full entry price for nothing.

    Returns [] for no open own batch (the common path prints nothing)."""
    if not batches:
        return []
    lines = [f"⚠ open work batch: this session already holds {len(batches)} un-landed "
             f"`work/` batch(es) — a second one is a DECISION, not a default:"]
    for br, p in batches:
        lines.append(f"    - {br} (slug: {br[len('work/'):]}) at {p}")
    lines.append("  Land admission costs the same per land whatever the batch holds (measured "
                 "2026-08-16: 170-220s each, 42 lands = 103 min of pure queue wait), so a batch "
                 "opened for tidiness buys a second full entry price for nothing.")
    lines.append("  This is NOT «batch more» — a `work/` batch lands PROMPTLY, and a card cannot "
                 "be dispatched until it is on main. It is ONE OPEN BATCH AT A TIME: land the "
                 "open one when you are READY TO DISPATCH FROM IT, not when you finish typing it.")
    lines.append("  Report-only, never blocks (CHARTER non-goal #7) — the batch above WAS created; "
                 "two open batches are legal when you mean them (T-11197).")
    return lines



def cmd_worktree_new(args: argparse.Namespace, *, _analysis_procedure_reminder, _append_event, _die, _foreign_hold_report, _format_task_verdict_line, _live_claimed_task_ids, _main_worktree, _plan_structural_findings, _print_cross_territory_routing_hint, _print_scenario_impact_warn, _read_worktree_stamp, _report_graft_parse_errors, _run_git_cap, _stamp_is_own, _task_safety_verdict, _with_live_nodes, _with_repo_lock, _worktree_parent_leaf, _worktree_path_for_branch, graph_build_index, REPO_ROOT, _assert_task_claimable, _claim_task, _orphan_resume_task, _resume_orphan_in_worktree, _write_worktree_stamp, _session_started_lower_bound, _resolve_session_ref, _BOOKKEEPING_ALLOWLIST, _inflight_worktree_intents=None, _print_inflight_intent_overlap=None, _print_spike_mode_hint=lambda: None, _live_path_holders=None, _session_proc_alive=None, _work_resume_candidate=None, _print_scenario_staleness_warn=lambda **k: None, SPIKE_BRANCH_PREFIX=None, _is_journal_archive_dirt=None, _live_holder_refusal=None, _open_work_batch_hint_lines=None, _own_open_work_batches=None, _unclassified_dirt=None, _filing_read_gate_hint_lines=None) -> None:
    """`worktree new` creation control-point (D-0051 — inverse of `land`, a CLI verb per D-0033,
    NOT a hook). Create a writing worktree + branch off `main` and print the `cd <path>` (a CLI
    cannot change the parent shell's cwd). Narrow by design: only --task / --work — no
    session-state / templates / registry. NOT autosync: it must not run the AUTO-SYNC session-log
    materialization on main (the contract D-0051 set). It DOES emit ONE deterministic
    `worktree_created` control-point event (T-0109/D-0054) — bound explicitly to the MAIN checkout's
    journal so the verb-vs-raw-git signal is durable regardless of where the verb is invoked. The
    event is folded into a commit by the next `land` (allowlisted bookkeeping dirt, T-0099)."""
    task = getattr(args, "task", None)
    work = getattr(args, "work", None)
    spike = bool(getattr(args, "spike", False))
    if bool(task) == bool(work):
        _die("worktree new: pass exactly one of --task T-XXXX or --work <slug>")
    # T-11071 (SPEC-0172 rule 5): `--spike` DECLARES a disposable exploration, and a `task/T-XXXX`
    # flow is by definition landing work — its whole 9-stage contract ends in `land`. Declaring one
    # disposable is incoherent, and accepting it silently would create a task that can never close.
    # Refuse loudly and name the shape that IS a spike (a `--work` batch).
    if task and spike:
        _die(f"worktree new: --spike is invalid with --task ({task}) — a task worktree runs the "
             f"9-stage lifecycle and ENDS in `land`, so it cannot be a disposable exploration "
             f"(SPEC-0172 rule 5). A spike is a `--work` batch: "
             f"`bin/yitc-v2 worktree new --work <slug> --spike`.")
    if task:
        if not re.fullmatch(r"T-\d{4,}", task):
            _die(f"worktree new: invalid --task id {task!r} (expected T-NNNN)")
        branch, leaf = f"task/{task}", task
    else:
        slug = work.strip()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            _die(f"worktree new: --work slug must be kebab-case [a-z0-9-], got {work!r}")
        branch, leaf = f"work/{slug}", slug
    main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT
    # T-0841 (F-004): unborn-main bootstrap guard. `worktree new` branches off `main` (the sole
    # integration branch, D-0037) and does NOT seed it — a fresh consumer repo with no `main`
    # (no commits, or a non-main default branch) would otherwise hit a cryptic raw git error
    # ("fatal: invalid reference: main") and be forced off-verb for its first commit. Refuse with
    # a CLEAR actionable bootstrap step instead (refuse-with-guidance over an auto-seed affordance —
    # P1: the verb does not author the consumer's first commit for it).
    if not _run_git_cap(["rev-parse", "--verify", "--quiet", "main"], main_wt).stdout.strip():
        _die("worktree new: no `main` branch in this checkout "
             f"({main_wt}) — a fresh consumer repo has no `main` to branch from, and `worktree "
             "new` branches off `main` (it does not seed it). Bootstrap `main` once, then re-run:\n"
             f"  git -C {main_wt} checkout -b main      # if not already on main\n"
             f"  git -C {main_wt} commit --allow-empty -m 'chore: seed main'   # or your real initial commit\n"
             "then `bin/yitc-v2 worktree new --work <slug>` (a `--work` batch is the path for the "
             "first governed commit — `--task` needs a filed task id, which filing allocates inside "
             "the worktree). `main` is the sole V2 integration branch (D-0037).")
    # T-10596 (E-0015 pre-claim seam): REFUSE to open a worktree while the MAIN checkout carries
    # substantive (non-bookkeeping) uncommitted dirt. `worktree new` branches from `main`'s COMMITTED
    # HEAD, so any pre-claim edit made on the main checkout stays STRANDED on main — invisible to the
    # new worktree and only surfacing (late) at the eventual `land` main-dirt refusal (worktree.py
    # `nonbk` block). This is the EARLIEST governed chokepoint after the still-unguarded subclass
    # `worker-edited-main-checkout-before-worktree-claim`: catch it HERE, before a branch/worktree or
    # `worktree_created` event is minted (mirror of T-0124's no-orphan ordering). Reuses the existing
    # dirt definition (`git status --porcelain` minus `_BOOKKEEPING_ALLOWLIST`) shared by land's fold
    # and `_require_writing_worktree` — NOT a new membrane, the pre-claim face of the D-0037/D-0051 one.
    # Escape hatch mirrors `_require_writing_worktree` (T-0125): `YITC_ALLOW_MAIN_WRITE=1` bypasses for
    # recovery/bootstrap + sandboxed tests that legitimately stage main dirt.
    if os.environ.get("YITC_ALLOW_MAIN_WRITE") != "1":
        main_dirty = {ln[3:].strip()
                      for ln in _run_git_cap(["status", "--porcelain"], main_wt).stdout.splitlines()
                      if ln.strip()}
        # T-11827: "substantive" = a path with NO fold policy, asked of the ONE resolver
        # (`worktree.py#unclassified_dirt`), INJECTED by the host rather than imported: `worktree.py`
        # imports THIS module, so importing back would be a cycle — the same reason
        # `_is_journal_archive_dirt` arrives injected. Absent (an un-injected in-process caller) ⇒ fall
        # back to the pre-T-11827 expression, so behaviour is unchanged rather than fail-open.
        if _unclassified_dirt is not None:
            substantive = _unclassified_dirt(main_dirty)
        else:
            substantive = sorted(p for p in main_dirty - _BOOKKEEPING_ALLOWLIST
                                 if not _is_journal_archive_dirt(p))
        if substantive:
            _die("worktree new: refusing to claim — the MAIN checkout "
                 f"({main_wt}) has uncommitted non-bookkeeping changes that a new worktree branches "
                 f"AWAY from (they would strand on main, D-0037/D-0051): {', '.join(substantive)}. "
                 "Move them into a worktree first (edit inside the worktree, not on main), or commit / "
                 "stash them on main, then re-run. Recovery/bootstrap bypass: YITC_ALLOW_MAIN_WRITE=1.")
    path = main_wt.parent / _worktree_parent_leaf() / leaf   # T-0840: consumer-relative leaf
    # T-0138 / D-0083 §3d: serialize the claimability-check + per-task-id double-claim guard +
    # branch-create across concurrent sessions under the cross-session repo lock, so two sessions
    # racing to claim the SAME id cannot both pass the guard. Brief — only the check + create.
    pre_claim_frontier: "set[str] | None" = None   # T-0439: FULL pre-claim snapshot (frontier+index)
    pre_claim_index: "dict | None" = None
    resume_mode = False   # T-9317 (F-019): orphan-resume path — recreate a removed worktree + resume
    work_resume = None    # T-11286: the WORK-axis mirror — re-attach a work/<slug> branch whose
                          # worktree is gone (the task axis's `resume_mode`, one axis over)
    with _with_repo_lock(main_wt):
        if task:
            # T-9317 (F-019): an in-progress + paused task whose worktree was removed at a prior
            # pause/land has NO live worktree to `task resume` into and is not `ready`, so the claim
            # path below would refuse it — the dead-end that forced raw git + `worktree adopt`. Detect
            # it (in-progress + paused on main, no live worktree on `branch`) and RECREATE+re-stamp the
            # worktree + RESUME instead of claim. The check is read-only; the resume is applied in the
            # new worktree after creation.
            _wt_live = _worktree_path_for_branch(branch)
            if _wt_live is None or not _wt_live.exists():
                resume_mode = _orphan_resume_task(task) is not None
        else:
            # T-11286: the SAME shape for a `work/<slug>` batch. A sweep (or a hand `git worktree
            # remove`) can take the worktree while the branch keeps its unlanded commits, and then
            # `land --branch` — which resolves the branch THROUGH its worktree — has no door left.
            # Read the candidate under the SAME repo lock as the task axis, so two sessions racing on
            # one slug are serialized identically. Read-only; the re-attach happens below.
            _wt_live = _worktree_path_for_branch(branch)
            if _wt_live is None or not _wt_live.exists():
                work_resume = _work_resume_candidate(branch, main_wt, _run_git_cap=_run_git_cap)
        if task and not resume_mode:
            # T-0124 audit-post F1: validate claimability BEFORE creating the worktree / emitting
            # worktree_created — a blocked / non-ready task must NOT leave an orphan branch+worktree
            # + misleading journal event. (Under concurrent UNLANDED claims the MAIN-side status is
            # still `ready` — the first claimant's flip lives only in its worktree until land — so
            # the AUTHORITATIVE per-task-id guard is the branch-existence check below, not status.)
            _assert_task_claimable(task)
            # T-0439 (audit-consult GREEN option 1): freeze the FULL pre-claim carve-out snapshot —
            # BOTH the live frontier AND the graph index (ready set + projection) — BEFORE the claim
            # mutates state. The claim flips ready→in-progress + adds a live worktree, so a post-claim
            # snapshot would re-classify this id as CLAIMED and drop it from the ready set, silently
            # degrading a real WAIT/CLASH to SAFE. The WARN below screens against THIS frozen snapshot.
            pre_claim_frontier = _live_claimed_task_ids()
            # ADVISORY snapshot — fail-open: the WARN is report-not-block (non-goal #7), so a graph
            # index that cannot be built MUST NOT break the claim (mirror of _live_claimed_task_ids'
            # fail-open posture). A None index simply suppresses the WARN below.
            try:
                # T-0503: thread parse_errors through the graft so a malformed authored task/decision
                # YAML hit while freezing the claim-screen snapshot is OBSERVABLE (mirror of
                # cmd_graph_query, T-0491) — not silently graft-skipped. Blocking-by-omission is
                # unchanged; this ADDS the report. Inside the fail-open try (the WARN is report-not-block
                # — a graft hiccup must never break the claim).
                _claim_parse_errors: list = []
                pre_claim_index = _with_live_nodes(graph_build_index(), errors=_claim_parse_errors)
                _report_graft_parse_errors(_claim_parse_errors)
            except Exception:  # noqa: BLE001 — advisory; never fatal to a claim
                pre_claim_index = None
        # Per-task-id (task) / per-slug (work) double-claim guard (AC2): the branch already existing
        # means a session has claimed this id/slug. `git worktree add -b` would also fail, but with
        # a raw "branch already exists" — give a CLEAR session-level message instead. OWN-vs-FOREIGN
        # (T-0362): the resume cue is given ONLY when the holder's stamp is THIS session; a foreign
        # or unstamped hold gets the BLOCK report — never an invitation to resume (the old
        # unconditional «cd into its worktree to continue it» is exactly what masked the 2026-06-05
        # T-0351 live-hold collision as a resumable orphan).
        branch_exists = bool(_run_git_cap(["branch", "--list", branch], main_wt).stdout.strip())
        # T-11286: `work_resume is None` keeps this refusal EXACTLY as it was for every other work
        # batch — it is exempted only in the one state where the guard has nothing left to protect:
        # the branch exists but NO worktree holds it (the live-batch case never sets `work_resume`,
        # so AC3's LIVE arm still lands here).
        if branch_exists and not resume_mode and work_resume is None:
            holder_wt = _worktree_path_for_branch(branch)
            stamp = _read_worktree_stamp(holder_wt)
            label = task if task else f"work slug {work}"
            if _stamp_is_own(stamp):
                _die(f"worktree new: {label} already claimed by THIS session (branch {branch} "
                     f"exists) — `cd {holder_wt}` to continue it (own-stamp resume), don't re-claim")
            journals = [(holder_wt / "events.jsonl") if holder_wt else None,
                        main_wt / "events.jsonl"]
            _die("worktree new: " + _foreign_hold_report(label, stamp, journals, holder_wt))
        # T-9317 (F-019): on the orphan-resume path, an EXISTING branch (worktree removed but branch
        # retained, e.g. a hand `git worktree remove`) is RE-ATTACHED — preserving its in-worktree
        # commits. Otherwise (a fresh claim, or a resume whose branch `land` already deleted) branch
        # off `main` with -b (post-land the paused state already lives on main).
        # LIVE-HOLDER GATE (T-10885) — the SECOND half of the guard, and the one that closes the
        # incident SEQUENCE rather than one of its steps. The branch-existence check above is the
        # per-id double-claim guard; it cannot see the case where the branch was ALREADY DELETED by a
        # teardown while the previous holder is STILL RUNNING (2026-08-10: park at 01:02:03Z, recreate
        # at 01:07:31Z — the live worker's own recorded "reset"). At that moment nothing on the git
        # side objects: no branch, no directory. The only surviving evidence is the live holder's cwd,
        # still pointing at this path (rendered `<path> (deleted)`), which is what this reads.
        # Belt-and-braces with the park gate, NOT a duplicate of it: park refuses the teardown a
        # GOVERNED verb performs; this refuses the overwrite regardless of HOW the path was freed —
        # including a raw `git worktree remove`, which no verb gate can reach.
        # TWO liveness reads, not one (audit-pre MEDIUM absorption). A cwd read alone has a blind
        # spot: a holder whose session is ALIVE but whose processes are not currently cwd-INSIDE the
        # worktree (it `cd`-ed elsewhere, or works it via `git -C`). Whenever the target path still
        # EXISTS it carries the T-0362 stamp naming its owner, so read that too and probe the owner
        # with the SAME `_session_proc_alive` substrate the park gate uses. The two are complementary,
        # each covering the other's blind spot: the stamp answers WHO for a path that still exists,
        # the cwd answers WHO for a path already unlinked (where the stamp died with the admin dir).
        _holders = _live_path_holders(path)
        _stamp_ref, _stamp_live = None, False
        if path.exists():
            _st = _read_worktree_stamp(path)
            _stamp_ref = (_st or {}).get("session_ref")
            _stamp_live = bool(_stamp_ref) and bool(_session_proc_alive(_stamp_ref))
        if _stamp_live:
            _append_event("deviation_captured", task,
                          {"relates_to": task or leaf,
                           "fingerprint": "live-holder-worktree-overwrite-refused",
                           "impact": f"worktree new refused to create {path}: its T-0362 stamp names "
                                     f"session {_stamp_ref}, which is a LIVE process.",
                           "captured_via": "live-holder-gate", "actor": "ai-agent"},
                          events_path=main_wt / "events.jsonl")
            _die(_live_holder_refusal("worktree new", path, _holders, _stamp_ref, True)
                 + " No branch or worktree was created.")
        if _holders:
            _append_event("deviation_captured", task,
                          {"relates_to": task or leaf, "fingerprint": "live-holder-worktree-overwrite-refused",
                           "impact": f"worktree new refused to create {path}: live cwd-holders "
                                     f"{[h['pid'] for h in _holders]}. Creating over a live holder is the "
                                     f"second half of the 2026-08-10 T-10826 data loss.",
                           "captured_via": "live-holder-gate", "actor": "ai-agent"},
                          events_path=main_wt / "events.jsonl")
            _die(_live_holder_refusal("worktree new", path, _holders, None, False)
                 + " No branch or worktree was created.")
        if (resume_mode or work_resume is not None) and branch_exists:
            # T-11286: the work leg re-attaches through this SAME add (no `-b`), so the branch's
            # unlanded commits are preserved rather than a second branch being born beside them.
            r = _run_git_cap(["worktree", "add", str(path), branch], main_wt)
        else:
            r = _run_git_cap(["worktree", "add", "-b", branch, str(path), "main"], main_wt)
        if r.returncode != 0:
            _die(f"worktree new: git worktree add failed: {(r.stderr or r.stdout).strip()}")
        # T-0362: stamp the new worktree with its owner session's provenance (dumb marker — the
        # canonical resume-decision input; lives in the worktree's private git admin dir).
        # T-11071: the `--spike` DECLARATION rides this same stamp (see `_write_worktree_stamp`) —
        # written at creation, read by `land`'s spike guard, deleted with the worktree. Not written
        # when absent, so an ordinary worktree's stamp is unchanged.
        stamp = _write_worktree_stamp(path, spike=spike)
        # D-0054: one deterministic control-point event, bound to MAIN's journal (not the global
        # EVENTS_PATH, which would follow REPO_ROOT into a linked worktree). Makes verb-vs-raw-git
        # worktree creation observable; absence of this event = "missing control-point evidence".
        # T-0362 (audit-pre F1/F2): data carries the stamp fields {session_ref, started_at} — so the
        # AC1 probe verifies both from the event alone — and nothing more (no stamp_path; the path
        # is derivable via _worktree_stamp_path).
        _append_event("worktree_created", None,
                      {"branch": branch, "path": str(path), "leaf": leaf,
                       "session_ref": stamp["session_ref"], "started_at": stamp["started_at"]},
                      events_path=main_wt / "events.jsonl")
    print(f"worktree new: branch {branch} at {path}")
    if work_resume is not None:
        # T-11286: name WHICH locus was repaired and at WHAT commit (lessons/a-refusal-remedy-must-
        # name-which-locus-it-repairs — a report a session acts on under load must be unambiguous
        # about whether it re-entered existing work or started fresh).
        print(f"  RE-ATTACHED {branch} at {work_resume['head'][:12]} (worktree was gone; its "
              f"unlanded commits are intact + the worktree is freshly stamped to this session) | "
              f"integrate with: bin/yitc-v2 land --branch {branch}")
    # T-0124 / D-0037 option B: for a --task worktree, CLAIM the task HERE (inside the new
    # worktree), not via a prior `task pick` on main. The claim (ready→in-progress + Analysis +
    # task_picked) is written into the worktree's tasks/ + events.jsonl, so it travels to main
    # only through `land` — eliminating the pick-on-main / worktree-from-committed-HEAD desync.
    if task and resume_mode:
        # T-9317 (F-019): RESUME the in-progress + paused task in the recreated worktree (clear pause
        # metadata + emit task_resumed) — the one-verb resume, replacing the raw git + `worktree adopt`
        # dead-end. NO claim (the task is already in-progress).
        resumed = _resume_orphan_in_worktree(task, path / "tasks", path / "events.jsonl")
        print(f"  RESUMED {task} (in-progress, worktree recreated + re-stamped) | "
              f"stage={resumed.get('current_stage') or '?'} | class={resumed.get('class')}")
        # read-gate ANCHOR cue — the recreated worktree is a fresh checkout needing its own anchor
        # (same requirement as a claim; T-0569). Surfaced before the resume-contract continue-from.
        print("  ⚠ read-gate: FIRST, before any stage read or gated verb in THIS worktree, run:")
        print("      bin/yitc-v2 session start")
        print("    it writes this checkout's read-gate anchor (and, for a dispatched worker, runs the")
        print("    T-0561 self-check). `graph query <SPEC>` reads done BEFORE it are NOT credited.")
        if resumed.get("resume_from"):
            print(f"  resume_from={resumed.get('resume_from')}")
        if resumed.get("next_action"):
            print(f"  next: {resumed.get('next_action')}")
        print(f"cd {path}")
        print(f"next: continue from current_stage={resumed.get('current_stage') or '?'} "
              f"(re-enter the stage bundle via `yitc-v2 stage {resumed.get('current_stage') or '<STAGE>'} "
              f"--task {task}`), then proceed to `task close` → `land`")
    elif task:
        claimed = _claim_task(task, path / "tasks", path / "events.jsonl")
        print(f"  claimed {task} -> in-progress | stage=Analysis | class={claimed.get('class')}")
        cites = claimed.get("cites") or []
        if cites:
            print("  cites (read for context): " + ", ".join(str(c) for c in cites))
        # T-0569: read-gate ANCHOR cue — surfaced HERE (after the claim, BEFORE the Stage-1 / next
        # guidance below) so the operator/worker learns the checkout-local anchor requirement at claim
        # time, not at a later commit/close fail-closed refusal (the T-0565 discoverability friction).
        # SPEC-0032 (the Stage-1 Analysis PROCEDURE) is UNAFFECTED: its content is delivered UNCHANGED
        # by `_analysis_procedure_reminder()` below; this cue is a SEPARATE read-gate concern printed
        # ahead of it (the coverage staleness flag is only the symbol-region hash moving, not a contract
        # change — audit-post LOW justification).
        # CUE-ONLY, fail-closed (design C, ceiling-convergence consult GREEN): worktree new does NOT
        # auto-emit any session_started — env-ABSENCE is NOT authenticated "interactive" and is never
        # auto-anchored (an auto-anchor here would let a miswired keyless worker bypass the read-gate
        # backstop — the audit-pre HIGH). The anchor stays emitted by `session start` (which also runs
        # the T-0561 worker self-check). The content-rule is SPEC-0042 §2 / SPEC-0050 §2 (the designed
        # recovery); this only surfaces it earlier. Reads done BEFORE the anchor are not credited.
        # T-10091: SUPPRESS the advisory when a committed HEAD anchor is already inherited. A fresh
        # worktree is checked out from committed HEAD, so its journal carries the session's committed
        # session_started (the claim appends only task_picked, never a session_started) — the read-gate
        # is already satisfied and the cue over-fires (the common post-land case). REUSE the read-gate's
        # own primitive `_session_started_lower_bound` (non-None ⇒ a committed anchor exists for this
        # ref). FAIL-OPEN: any resolution error prints the cue — never silently hide a genuinely-needed
        # anchor requirement.
        _has_committed_anchor = False
        try:
            _sref = _resolve_session_ref()
            if _sref and _session_started_lower_bound(_sref, events_path=path / "events.jsonl") is not None:
                _has_committed_anchor = True
        except Exception:  # noqa: BLE001 — advisory gate; fail-open (print the cue) on any error
            _has_committed_anchor = False
        if not _has_committed_anchor:
            print("  ⚠ read-gate: FIRST, before any stage read or gated verb in THIS worktree, run:")
            print("      bin/yitc-v2 session start")
            print("    it writes this checkout's read-gate anchor (and, for a dispatched worker, runs the")
            print("    T-0561 self-check). `graph query <SPEC>` reads done BEFORE it are NOT credited.")
        # T-0279 (before-analysis floor trigger): SURFACE the ordered Stage-1 procedure at the claim
        # moment (replaces the 2 ad-hoc hint lines) + run the EXISTING structural pre-pass over the
        # claimed task's scope+acceptance — the decomposition step's mechanical half (reuse, NOT a
        # parallel validator — CHARTER §1 F1). Report-not-block: surfaces + reports, never gates.
        print(_analysis_procedure_reminder(task))   # T-9741: pass the real tid so the per-stage sequence shows concrete commands
        # T-1050 (SPEC-0076 §6c): Analysis impact-WARN — scenarios passing through the specs this
        # task touches. Read-only, never blocks (the claim already happened above).
        _print_scenario_impact_warn(claimed)
        # T-11420 (X-1077): the staleness-WARN rides the SAME claim seam — a scenario citing a spec
        # that is no longer active is exactly what this reader can still fix, before any editing.
        # Report-only, never blocks (the claim already happened above).
        _print_scenario_staleness_warn(label="claim")
        # T-1272 (SPEC-0032 / SPEC-0079): report-only cross-territory routing hint — if the claimed
        # task's forecast paths reach OUTSIDE own territory, surface the cross-log route. Never blocks.
        _print_cross_territory_routing_hint(claimed.get("expected_touch") or [])
        # T-10696 (SPEC-0051, X-0548): report-only spike-mode hint — if the target project has a LIVE
        # work/spike-* worktree, surface ONCE that it is mid spike-loop. Never blocks; the claim stands.
        _print_spike_mode_hint()
        _payload = "\n".join(f"- {s}" for s in (claimed.get("scope") or []) + (claimed.get("acceptance") or []))
        _structural = _plan_structural_findings("", _payload)
        if _structural:
            print(f"  structural pre-pass: {len(_structural)} WARN finding(s) (report-not-block, SPEC-0012):")
            for _f in _structural:
                print(f"    - [{_f['source']}] {_f['what']} — fix: {_f['fix']}")
        # T-0439: the per-task safety verdict (SPEC-0044 screen), computed against the FROZEN
        # pre-claim snapshot so the just-created claim does not contaminate it. REPORT-not-block
        # (non-goal #7): a WAIT/CLASH is surfaced as ONE WARN line; the claim already happened and
        # is NEVER refused on this basis. SAFE prints nothing extra (no noise on the common path).
        # Fail-open: a None snapshot (graph index unbuildable) or any computation error simply
        # suppresses the advisory WARN — the claim is NEVER broken by an advisory line.
        if pre_claim_index is not None:
            try:
                _verdict = _task_safety_verdict(task, pre_claim_index, live_claimed=pre_claim_frontier)
                if _verdict["verdict"] in ("WAIT", "CLASH"):
                    # column-0 `WARN:` (no indent) so a strict stdout probe matches it.
                    print("WARN: " + _format_task_verdict_line(_verdict)
                          + " (report-not-block, SPEC-0044 / non-goal #7 — the claim stands)")
            except Exception:  # noqa: BLE001 — advisory; never fatal to a claim
                pass
        # T-10579 (X-0430): the CROSS-SESSION in-flight-intent advisory. The verdict above screens vs
        # the LANDED index + the task/ claim frontier; it never saw a concurrent live controller's
        # un-landed filed card / work/<slug> batch on the SAME concern (the X-0430 duplicate-build class).
        # Scan the OTHER live worktrees (excluding this just-created task/T-XXXX branch) and surface an
        # advisory when one overlaps this task's title / expected_touch. Report-only, fail-open: the claim
        # already happened above and is NEVER refused on this basis.
        if _inflight_worktree_intents and _print_inflight_intent_overlap:
            try:
                _intents = _inflight_worktree_intents(self_branch=f"task/{task}")
                _print_inflight_intent_overlap(claimed.get("title") or "",
                                               claimed.get("expected_touch") or [], _intents)
            except Exception:  # noqa: BLE001 — advisory; never fatal to a claim
                pass
        print(f"cd {path}")
        print(f"next: edit per plan, then (substantive) `yitc-v2 task plan --finalize {task}` "
              f"→ `audit pre` → `task execute` → tests → `task commit` → `audit post` → `task close` → `land`")
    else:
        print(f"cd {path}")
        # T-10782 (SPEC-0051, X-0616): the SAME report-only spike-mode hint the task-claim branch
        # above prints — DUPLICATED here (one existing call, no new text/mechanism) because the
        # `--work <slug>` path is precisely the one that CREATES a `work/spike-*` worktree, i.e. the
        # moment a spike loop BEGINS. T-10696 wired the hint into the claim branch only, so the
        # creation path was silent — and a report-only hint that does not print fails SILENTLY by
        # construction (its absence is indistinguishable from "no live spike loop"), which is why
        # the defect survived until the SPEC-0172 trial went looking. Called AFTER the worktree is
        # created, so the just-created spike worktree is itself live in `git worktree list`.
        # Report-not-block, unchanged (CHARTER non-goal #7): the creation already happened above and
        # is never refused on this basis.
        _print_spike_mode_hint()
        # T-11197: the OPEN-OWN-BATCH hint. `worktree new` already enumerates the live worktrees to
        # reach this point, so at the exact moment a second filing batch is opened the fact that one
        # of THIS session's own is still un-landed is in hand — extend the verb that is BEFORE X
        # (D-0033) rather than add a startup line (which would cost the CHARTER §Principle 2 seed
        # budget and is the demonstrably weakest carrier — X-0908 is a consumer reporting a
        # Controller ignoring a rule already delivered at startup).
        # HINT, NEVER A GATE (CHARTER non-goal #7): the worktree + branch already exist above, the
        # exit code is unchanged, and no flag suppresses or enables it. There are legitimate reasons
        # for two open batches — the point is that the session should know it is CHOOSING one.
        # Fail-OPEN, like every other advisory on this path.
        try:
            for _ln in _open_work_batch_hint_lines(
                    _own_open_work_batches(main_wt, branch, _run_git_cap=_run_git_cap,
                                           _read_worktree_stamp=_read_worktree_stamp,
                                           _stamp_is_own=_stamp_is_own)):
                print(_ln)
        except Exception:  # noqa: BLE001 — advisory; never fatal to a creation
            pass
        # T-11071 (SPEC-0172 rule 5, X-0857): the slug prefix is now a HINT and nothing more. Until
        # this card it WAS the gate — a `work/spike-*` name alone made `land` refuse — which refused a
        # governed batch merely NAMED after the kernel's own mandatory `spike_sandbox` declare-or-waive
        # ask and told its author to discard committed work. So the name no longer decides; `--spike`
        # does. This line is the other half of that move: without it the gate would be unreachable in
        # practice (nobody declares a flag they were never told about), and a spike author who kept the
        # habit of NAMING the batch would silently lose the guard the rule exists to provide.
        # Report-only, and printed only in the exact ambiguous case (spike-named, undeclared).
        if branch.startswith(SPIKE_BRANCH_PREFIX) and not spike:
            print(f"  note: {branch} is NAMED like a spike but is NOT declared one — it will land "
                  f"normally. If it IS a disposable exploration, re-create it with `--spike` (the "
                  f"declaration `land` reads); if it is ordinary work that merely answers the "
                  f"`spike_sandbox` ask, nothing to do (T-11071, SPEC-0172 rule 5).")
        # T-9578 (resolves X-0094): the --work filing flow needs the SAME checkout-local read-gate
        # anchor as the --task path — a `work/<slug>` worktree is a fresh checkout, so `task file`
        # (and any other gated verb) fail-closed-refuses until THIS worktree emits its own
        # session_started (SPEC-0050 §2 / gates._session_started_lower_bound). Without this cue the
        # consumer filing flow dead-ended at `task file`'s refusal with no forewarn (X-0094). Same
        # CUE-ONLY, fail-closed posture as the --task path (worktree new does NOT auto-anchor —
        # design C: an auto-anchor would let a miswired keyless worker bypass the read-gate backstop);
        # this only surfaces the existing requirement earlier for the filing flow.
        # T-11845: the cue now prints the READY-TO-RUN command set — the anchor AND the Filing
        # contract fetches the `task file` read-check demands (`_filing_read_gate_hint_lines`,
        # derived from the same Filing bundle the gate reads) — plus the one fact that was nowhere
        # stated: the receipt is recorded in the checkout where the command RAN. Measured 2026-08-30:
        # a first filing cost three refusal round-trips, the silent one being a fetch run in MAIN
        # while filing from the worktree — a worktree's events.jsonl is a branch copy, so a main-side
        # append reaches it only at `land`, and only the CHECKOUT arm had neither diagnostic nor
        # forewarning. CUE-ONLY and fail-closed as before: nothing here auto-anchors or auto-fetches,
        # and nothing changes what the gate CREDITS.
        _hint_lines = _filing_read_gate_hint_lines(path) if _filing_read_gate_hint_lines else []
        print("  ⚠ read-gate: FIRST, before `task file` / `spec new` or any gated verb in THIS")
        print("    worktree (e.g. when filing from a Review session), run THESE, here:")
        for _cmd in (_hint_lines or ["bin/yitc-v2 session start"]):
            print(f"      {_cmd}")
        print("    The read receipt is recorded in the checkout where the command RAN — a run in")
        print("    ANOTHER checkout of the same repo (e.g. main) does NOT count here, because this")
        print("    worktree's events.jsonl is a branch copy that main's appends reach only at `land`.")
        print("    Reads/filings before them are refused.")



def _write_worktree_stamp(wt: Path, *, _resolve_session_ref, _utc_now_iso, _worktree_stamp_path,
                          spike: bool = False) -> dict:
    """Stamp a worktree at creation with its OWNER session's provenance (T-0362) — a DUMB marker:
    {session_ref, started_at} (+ the optional T-11071 `spike` DECLARATION below). NO TTL / NO lease
    / NO heartbeat (the liveness-registry non-goal, AGENTS §What-is-NOT-in-V2) — liveness stays
    ADVISORY from the existing journal (`_session_last_event_ts`). The stamp FILE is the canonical
    probe source and the sole resume-decision input (audit-pre F1). Returns the stamp dict.

    T-11071 (SPEC-0172 rule 5, X-0857) — `spike: true` is the DECLARED spike marker the land guard
    reads INSTEAD of the branch NAME. It rides THIS existing per-worktree marker file rather than a
    store of its own: rule 7 forbids a new store, and CHARTER §P1 F1/F2 prefers a field on an
    existing carrier over a new entity. Lifetime is exactly right by construction — the stamp lives
    in the worktree's private git admin dir and `git worktree remove` deletes it with the worktree,
    so a declaration cannot outlive the spike it describes. Written ONLY when true, so an ordinary
    worktree's stamp is byte-identical to the pre-T-11071 shape."""
    stamp = {"session_ref": _resolve_session_ref(), "started_at": _utc_now_iso()}
    if spike:
        stamp["spike"] = True
    p = _worktree_stamp_path(wt)
    if p is None:
        # Should not happen right after a successful `git worktree add`; surface loudly — an
        # unstamped worktree reads as FOREIGN/UNKNOWN to every session (fail-closed).
        print(f"WARN: worktree session stamp NOT written (git admin dir unresolved for {wt}) — "
              f"this worktree will read as held-by-UNKNOWN to all sessions (T-0362)")
        return stamp
    p.write_text(json.dumps(stamp) + "\n", encoding="utf-8")
    return stamp



def _assert_task_claimable(tid: str, *, _append_event, _die, _find_task_yaml, _requires_incomplete, _task_decomposed_from_pre_executing_plan, state=None, task_mod=None) -> None:
    """Read-only claimability check against the module-global TASKS_DIR/DECISIONS_DIR (main checkout):
    the task exists, is status=ready, has no incomplete `requires:`, and (SPEC-0070 §5) does not cite a
    pre-`executing` plan. Dies otherwise. Used by `worktree new --task` to fail BEFORE creating the
    worktree (T-0124 audit-post F1 — no orphan worktree/branch/event for a non-claimable task).
    _claim_task re-validates at write time."""
    import yaml
    path = _find_task_yaml(tid)
    if path is None:
        _die(f"worktree new: task {tid} not found — cannot claim a non-existent task")
    task = state.load_str(path.read_text(encoding="utf-8")) or {}
    status = task.get("status")
    if status != "ready":
        _die(f"worktree new: {tid} status={status!r} — only a ready task can be claimed "
             f"(if it's in-progress, its worktree already exists; just `cd` in)")
    blocked = _requires_incomplete(task.get("requires") or [])
    if blocked:
        lines = "; ".join(f"{r} {why}" for r, why in blocked)
        _die(f"worktree new: {tid} has incomplete requires: {lines} — not claimable (QUEUE §Picker logic)")
    # SPEC-0166: dispatchability gate (pre-create read-check — fail BEFORE creating a worktree for a
    # non-verified imported card, mirroring the plan-pre-executing block below). Same pure predicate +
    # existing claim_refused marker as the write-time re-validate in `_claim_task` (P1 F1/F3).
    premise_block = task_mod._premise_dispatch_block(task)
    if premise_block:
        _append_event("claim_refused", tid, {"reason": "premise-unverified", "premise": task.get("premise")})
        _die(f"worktree new: {tid} NOT claimable — {premise_block} (SPEC-0166 dispatchability gate).")
    pre = _task_decomposed_from_pre_executing_plan(task)
    if pre:
        slug, pst = pre
        # emit-then-die (worker_identity_refused precedent, :1414): a DEDICATED claim-refusal event,
        # NOT read_gate_refused (whose kind enum is LOCKED — SPEC-0025/0059). Main-checkout journal
        # append is sanctioned (D-0049). Additive on the open SPEC-0025 event enum (no new store/hook).
        _append_event("claim_refused", tid,
                      {"reason": "plan-pre-executing", "plan": slug, "plan_status": pst})
        _die(f"worktree new: {tid} is decomposed_from plan {slug!r} at status={pst!r} (pre-`executing`) — its "
             f"cut is not yet decomposition-fidelity-audited, so no card is claimable until the plan reaches "
             f"`executing` (SPEC-0070 §5 claim-block, keyed on the `decomposed_from` cut-membership marker — "
             f"NOT `cites:`). The cut is audited at decomposition→executing BEFORE any card is built — even "
             f"across concurrent sessions.")



def _land_preflight_conflict_lines(branch: str, main_wt: Path, tid: "str | None", *, _run_git_cap,
                                   _DERIVED_MERGE_ARTIFACTS=None, _dedup_events=None,
                                   EVENTS_PATH=None, _classify_inert_paths=None,
                                   _probe=None, _git_rev=None, _land_merge_probe=None, _land_preflight_conflict_audit_lines=None,
                                   _blockers_out: "dict | None" = None) -> "list[str]":
    """T-11313 — PHASE 1 of the resumed-land pre-flight: the blockers provable BEFORE the merge, in
    ONE output. Returns `[]` when nothing is proven blocking.

    `_blockers_out`, when a dict is supplied, is UPDATED with the conflict split this call already
    computed — `{"unresolved": [...], "resolved": [...]}` (T-11697). It is the SAME machine-record
    sink the phase-2 sibling `_land_preflight_currency_lines` carries as `_split_out` (T-11391), for
    the same reason: a consumer needs the verdict as DATA, and re-deriving it beside the call would
    be the second computation this file exists to prevent. It is written at the ONE point the probe
    has answered — BEFORE the not-proven-blocking early return — so a MEASURED-EMPTY conflict set
    (`unresolved == []`) is written and is therefore distinguishable from an UNTOUCHED sink, which
    means the probe COULD NOT ANSWER (fail-open: an unreadable ref, a git that would not run, an
    unparsable stream). The distinction is the whole point of the sink for a journalled record;
    collapsing the two would republish "did not answer" as "clean". Report-only, exactly as the
    return value is: nothing here refuses, and the fail-open polarity is unchanged.

    THE MEASURED CLASS (2026-08-19, four instances in one session, never a projection). Resuming an
    unlanded branch surfaces its blockers SERIALLY, one wasted attempt each: task/T-11291 refused on
    merge conflicts, then AGAIN on audit currency once they were resolved; task/T-11285 the same, and
    it needed a paid re-audit; task/T-11309 refused on audit currency alone; and task/T-11309 was then
    evicted from a batch on 7 spec YAMLs whose conflicts task/T-11291 had created 55 SECONDS earlier —
    a pre-check computed before that land had already answered COMPATIBLE and was wrong by the time
    the batch formed. That last one is why nothing here is cached: the answer is computed at the
    MOMENT IT IS USED, from the live oracles, every run.

    ONE ORACLE, NOT A SECOND FEED. The conflict set comes from `_land_merge_probe` — the same
    authority the pre-queue refusal and the batch eviction read, whose `detail` is
    `_classify_land_merge_conflicts`'s own blocking / auto-resolvable split. FAIL-OPEN, the T-11218
    polarity: a blocker is reported ONLY on a PROVEN non-empty `unresolved` set; an unreadable ref, a
    git that would not run, an unparsable stream or a classifier that raised all report NOTHING, so
    this never invents a refusal it could not prove. It refuses nothing itself either — it prints, and
    `_update_from_main`'s own abort text follows BYTE-IDENTICAL.

    THE SECOND BLOCKER IS PROVED WITH THE CURRENCY GATE'S OWN COMPARISON, NOT INFERRED FROM
    CONFLICTEDNESS (audit-pre pass-2 RED + the SPEC-0124 consult, survivor option 2). When the merge
    cannot run, currency cannot be MEASURED — so the naive move is to DERIVE it from the mere existence
    of a conflict, and that is an overclaim: a conflicted path is not yet proof that its resolution
    enters `own_post_audit`. Three conjuncts, all necessary, together sufficient:
      (i)   the path is UNRESOLVED for the branch (the oracle above);
      (ii)  it is OBSERVABLE — `_classify_inert_paths([p])[0] == "observable"`, the ONE inert authority
            (SPEC-0064 §4), called exactly as `_land_integrate` calls it. An inert conflicted path (a
            bookkeeping ledger, a derived artifact) reaches no blocking bucket, so it earns no line;
      (iii) it is CONFLICT-MARKED in `merge-tree --write-tree <audit_commit> <main_tip>` — the clean
            3-way re-merge of the AUDITED commit with main, which is the EXACT comparison
            `_land_audited_footprint_split` buckets against: a path lands in `own_post_audit` when
            HEAD goes BEYOND that tree. Computable HERE, in the conflict case, precisely because
            `--write-tree` prints its tree even when it conflicts, checks nothing out and moves no
            ref — so no merge has to succeed and no second oracle is introduced.
    For a path satisfying (iii) the re-merge is itself conflict-marked, so ANY resolution the branch
    writes necessarily DIFFERS from it and is therefore BEYOND it — which IS the gate's blocking test,
    not a proxy for it. A path failing (iii) has a CLEAN re-merge, so the gate could still bucket its
    resolution as `merge_inherited`; it is reported as a conflict ONLY, with no audit claim.

    A recorded GREEN/YELLOW `audit_post_completed` is a NECESSARY conjunct too, read through the ONE
    reader `_last_audit_post_for_task`. Every failure inside the audit half is silent (fail-open): the
    conflict is still reported alone.
    """
    try:
        probe = _probe if _probe is not None else _land_merge_probe
        main_rev = _git_rev("main", main_wt, _run_git_cap=_run_git_cap)
        branch_rev = _git_rev(branch, main_wt, _run_git_cap=_run_git_cap) if branch else None
        if not main_rev or not branch_rev:
            return []
        _outcome, _tree, detail = probe(main_rev, branch, main_wt, _run_git_cap=_run_git_cap,
                                        _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
                                        _dedup_events=_dedup_events)
        unresolved = list((detail or {}).get("unresolved") or [])
        resolved = list((detail or {}).get("resolved") or [])
        if _blockers_out is not None:
            # The probe ANSWERED — publish the split before the fail-open return below, so an empty
            # answer is recorded as empty rather than as silence (see the docstring).
            _blockers_out.update({"unresolved": list(unresolved), "resolved": list(resolved)})
        if not unresolved:
            return []                          # not PROVEN blocking → say nothing (fail-open)
        lines = [f"worktree sync: PRE-FLIGHT BLOCKER — MERGE CONFLICTS with main {main_rev[:12]} "
                 f"({branch} {branch_rev[:12]}). These must be resolved by hand:"]
        lines.extend(f"    {p}" for p in unresolved)
        if resolved:
            lines.append("  (auto-resolvable, NOT blocking: " + ", ".join(sorted(resolved)) + ")")
    except Exception:                          # noqa: BLE001 — a REPORT that raises must not abort
        return []
    # AUDIT-HALF FAILURES ARE SCOPED TO THE AUDIT HALF (audit-post finding, absorbed). The blanket
    # try above used to cover this call too, so an exception while PROVING the second blocker threw
    # away the FIRST one — already proven, already rendered. Fail-open must lose only the claim it
    # could not prove; a wider catch here would recreate the exact one-blocker-per-attempt defect
    # this card exists to remove.
    try:
        audit = _land_preflight_conflict_audit_lines(
            unresolved, main_rev, tid, main_wt,
            _run_git_cap=_run_git_cap, EVENTS_PATH=EVENTS_PATH,
            _classify_inert_paths=_classify_inert_paths)
    except Exception:                          # noqa: BLE001
        audit = []
    return lines + audit



def _land_preflight_conflict_audit_lines(unresolved: "list[str]", main_rev: str, tid: "str | None",
                                         main_wt: Path, *, _run_git_cap, EVENTS_PATH=None,
                                         _classify_inert_paths=None, _last_audit_post_for_task=None, _merge_tree_conflict_stages=None) -> "list[str]":
    """T-11313 — the AUDIT half of phase 1: conjuncts (ii) and (iii) of the proof described above.
    Returns `[]` unless at least one unresolved path is BOTH observable AND conflict-marked in the
    audited-commit-vs-main re-merge. Every unprovable edge returns `[]` (fail-open)."""
    if not tid or EVENTS_PATH is None or _classify_inert_paths is None:
        return []
    verdict, commit = _last_audit_post_for_task(tid, EVENTS_PATH)
    if verdict not in ("GREEN", "YELLOW") or not commit:
        return []                              # no standing audit claim ⇒ nothing to invalidate
    # (ii) the ONE inert authority, per path, called exactly as `_land_integrate` calls it.
    observable = [p for p in unresolved if _classify_inert_paths([p])[0] == "observable"]
    if not observable:
        return []
    # (iii) the gate's OWN comparison — the clean 3-way re-merge of the AUDITED commit with the main
    # tip. `-z` is the machine-readable form of the same command `_land_audited_footprint_split` runs;
    # it is parsed by the ONE existing parser, so no second conflict reader appears here.
    try:
        mt = _run_git_cap(["merge-tree", "--write-tree", "-z", commit, main_rev], main_wt)
    except Exception:                          # noqa: BLE001
        return []
    tree, marked, _stages = _merge_tree_conflict_stages(getattr(mt, "stdout", "") or "")
    if not tree:
        return []                              # the re-merge did not answer → claim nothing
    claim = [p for p in observable if p in set(marked)]
    if not claim:
        return []
    return [f"worktree sync: PRE-FLIGHT BLOCKER — A RE-AUDIT WILL BE REQUIRED. {tid}'s standing "
            f"audit-post ({verdict} @ {str(commit)[:7]}) does not cover these paths' resolution:",
            *(f"    {p}" for p in claim),
            f"  Why, proved not guessed: each is conflict-marked in the clean re-merge of the AUDITED "
            f"commit {str(commit)[:7]} with main {main_rev[:12]} — the SAME comparison the SPEC-0077 "
            f"§3a currency gate buckets against — so ANY resolution you write goes BEYOND that tree "
            f"and lands in `own_post_audit`, which land refuses.",
            f"  Resolve the conflicts, then re-run `yitc-v2 audit post --task {tid}` BEFORE `land` — "
            f"this is the second attempt you would otherwise have spent discovering it."]
