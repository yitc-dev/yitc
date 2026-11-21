"""T-14745 (SPEC-1063 rule 1) — THE HOST RESOURCE-ADMISSION AUTHORITY: one machine-wide start gate
for HEAVY starts (a Stage-6 run and a non-credited land), shared by every repository on the host.

It selects nothing and launches nothing: each repository's queue still picks its own head, and only a
head its own repository's rules let go asks here. The eligible heads of all repositories are ranked
(`rank`), and the first of them starts when the machine-wide start lag has passed since the newest
heavy start, the measured free usable threads reach the need, and the memory every live start holds
leaves room for this one. Nothing here resizes a running run, yields, pins or sets a quota.

Bounded live state, in ONE canonical directory per host — beside the machine settings file, the
host's group-shared coordination directory (a test isolates it by naming its own settings file):
  `.lock`         the host lock — taken for one read-decide-write only, never across a wait and never
                  while a repository's queue LOCK is held. A queue-less start asks it again with its
                  verify slot held, so the grant is taken at the instant the work starts (`grant=False`
                  readies the head without granting); the width a granted verify takes is reserved
                  under it from inside the width lock (the order: width lock, then host lock);
  `wait-*`        one entry per waiting head; its owner holds a flock on it while it lives. A probe that
                  TAKES that flock found a dead owner and removes the entry (the width registrations'
                  idiom, `worktree._width_registrations`); a live entry that cannot be read HOLDS the gate;
  `grant-*`       one per admitted start, its flock held by an INHERITABLE descriptor (the admitted
                  work's children and an in-place re-exec keep it, as BUSY is handed down) and its path
                  exported in GRANT_ENV. Its threads count with exp(-age/60) — the share a CPU reading
                  does not show yet (the width registrations' decay, `worktree._VERIFY_WIDTH_LAG_S`);
                  its memory counts whole until the grant ends;
  `last_start`    the time of the newest heavy start (the machine-wide start lag), kept after its run
                  ends; a grant cancelled before its work started gives it back.
A process whose environment carries GRANT_ENV is inside an admitted heavy run and never asks the gate.
Every number is a machine setting the caller reads (`admission.settings`, MACHINE keys HOST_*); the
built-in defaults live only in `machine_settings.INVENTORY`.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import time
import uuid
from pathlib import Path

DIRNAME = "host-admission"
GRANT_ENV = "YITC_HOST_GRANT"     # the grant an admitted heavy run holds, handed to its children
INSIDE_VERIFY = "inside-verify"    # GRANT_ENV's value in a verify's test child: part of an admitted run


def _source_digest() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "unknown"


SOURCE_DIGEST = _source_digest()   # this module as it was when THIS process loaded it (T-14749)


def host_dir(_dir=None) -> Path:
    """The ONE state directory of this host: beside the machine settings file."""
    if _dir is not None:
        return Path(_dir)
    from lib import machine_settings
    return machine_settings.resolve_settings_path().parent / DIRNAME


def inside_admitted() -> bool:
    """This process is part of an admitted heavy run (a child of it, its re-exec, a verify's test
    child): it asks the gate nothing."""
    return bool((os.environ.get(GRANT_ENV) or "").strip())


class Unreadable(Exception):
    """A live entry the gate cannot read: the gate holds, naming it (never a dropped commitment)."""


class Unverified(RuntimeError):
    """The grant this run holds cannot be verified: no worker starts on an unreserved width."""


def _open(path: Path) -> int:
    """Open (create) a state file group-writable whatever the umask: the directory is shared by the
    OS users of the machine (its setgid group)."""
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o664)
    try:
        os.fchmod(fd, 0o664)
    except OSError:
        pass                                   # another user's file stays as its owner made it
    return fd


def _flock_nb(path: Path):
    """An fd holding an exclusive flock on `path` (created), or None when another process holds it."""
    fd = _open(path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def _read(path: Path):
    """The entry's record, or None when it cannot be read as one."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, data: dict) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:6]}")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(tmp, 0o664)
    os.replace(tmp, path)


def _rewrite(path: Path, data: dict) -> None:
    """Rewrite a LIVE entry in place — never by replacing the file: its owner's flock is on this inode,
    and a new inode would read as an entry whose owner is gone. Under the host lock only, so no reader
    sees it half-written."""
    fd = os.open(str(path), os.O_RDWR)
    try:
        os.ftruncate(fd, 0)
        os.pwrite(fd, json.dumps(data).encode("utf-8"), 0)
    finally:
        os.close(fd)


def _live(d: Path, prefix: str, own=()) -> list:
    """(path, record) of every live `prefix-*` entry; an entry whose owner is gone is removed. Liveness
    is the flock only: a live entry that cannot be read raises Unreadable. Under the host lock only.
    `own` — paths this process holds the flock of (a probe from here would not see them as held)."""
    out = []
    for f in sorted(d.glob(f"{prefix}-*")):
        if f in own:
            rec = _read(f)
        else:
            fd = _flock_nb(f)
            if fd is not None:
                try:
                    f.unlink(missing_ok=True)         # its owner is gone
                except OSError:
                    pass
                finally:
                    os.close(fd)
                continue
            rec = _read(f)
        if rec is None or not _valid(prefix, rec):
            raise Unreadable(f"the live entry {f.name} cannot be read as a {prefix} record")
        out.append((f, rec))
    return out


_FIELDS = {"wait": ("arrival", "checked_at"), "grant": ("ts", "threads", "mem_mb")}


def _finite(v) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def _last_start(d: Path) -> float:
    """The newest heavy start: 0.0 when none was ever recorded (no file); an existing record must carry
    a finite timestamp, else it cannot be read and the gate holds (never read as an expired lag)."""
    path = d / "last_start"
    if not path.exists():
        return 0.0
    stamp = _read(path)
    if stamp is None or not _finite(stamp.get("ts")):
        raise Unreadable("the last start cannot be read")
    return float(stamp["ts"])


def _valid(prefix, rec) -> bool:
    """A live record carries every field its reader counts, each a finite number (never read as 0)."""
    return all(_finite(rec.get(k)) for k in _FIELDS.get(prefix, ()))


class _HostLock:
    def __init__(self, d: Path):
        self.d = d

    def __enter__(self):
        if not self.d.exists():
            self.d.mkdir(parents=True, exist_ok=True)
            os.chmod(self.d, 0o2775)
        self.fd = _open(self.d / ".lock")
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        os.close(self.fd)


def rank(rec: dict, now: float, aging: float) -> tuple:
    """The machine-wide order. Tier 0: a queue-jump mark, and a run that has waited `aging` s or more;
    tier 1: a land; tier 2: a run. Inside a tier the longest-waiting first — so an aged run is passed
    by no later arrival, marked or not, and a mark still goes before every entry that is not aged."""
    arrival = float(rec.get("arrival") or now)
    if rec.get("mark") or (rec.get("kind") != "land" and now - arrival >= aging):
        tier = 0
    else:
        tier = 1 if rec.get("kind") == "land" else 2
    return (tier, arrival)


def usable_and_need(s: dict, nproc: int) -> tuple:
    usable = max(1, int(nproc) - int(s["HOST_RESERVE"]))
    return usable, min(int(s["HOST_NEED"]), usable)


def per_worker_mem_mb() -> int:
    from lib import worktree
    return int(worktree._VERIFY_PER_WORKER_MEM_MB)


def mem_available_mb():
    from lib import verify_runner
    return verify_runner._mem_available_mb()


def busy_threads(samples, s, nproc):
    """The busy threads of the whole host over the last EMPTY_SAMPLE s of the waiter's own samples
    (admission.Samples — no second sampler), or None while that window is not full or /proc/stat
    cannot be read (never a zero)."""
    samples.take()
    if not samples.rows:
        return None
    cpus = sorted(samples.rows[-1][1].keys())
    busy, _start, _have = samples.mean(0.0, float(s["EMPTY_SAMPLE"]), cpus)
    return None if busy is None else busy / 100.0 * nproc


def _decay(rec, now):
    from lib import worktree
    return math.exp(-max(0.0, now - float(rec.get("ts", now))) / float(worktree._VERIFY_WIDTH_LAG_S))


class Waiter:
    """One head's place at the host gate, from its first check to its grant or its end."""

    def __init__(self, *, repo, task, kind, mark=False, arrival=None, _dir=None):
        self.d = host_dir(_dir)
        self.rec = {"repo": str(repo), "task": task, "kind": "land" if kind == "land" else "run",
                    "mark": bool(mark), "arrival": float(time.time() if arrival is None else arrival),
                    "pid": os.getpid(), "checked_at": 0.0}
        self.path = None
        self.fd = None
        self.last = None            # the reason of the last answer, for a caller writing one row per change

    def _ensure(self) -> None:
        if self.path is not None and self.path.exists():
            return
        if self.fd is not None:
            os.close(self.fd)
        self.path = self.d / f"wait-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        _write(self.path, self.rec)
        self.fd = _flock_nb(self.path)

    def stand_down(self) -> None:
        """The head waits for its own repository again: not eligible, it blocks nobody."""
        if self.path is None or not self.rec.get("checked_at"):
            return
        self.rec["checked_at"] = 0.0
        try:
            with _HostLock(self.d):
                if self.path.exists():
                    _rewrite(self.path, self.rec)
        except OSError:
            pass

    def leave(self) -> None:
        if self.path is not None:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
        if self.fd is not None:
            os.close(self.fd)
        self.path, self.fd = None, None

    def check(self, s: dict, samples, *, mark=None, now=None, nproc=None, mem_mb=None, grant=True) -> dict:
        """Ask the gate once: {"ok": True, "grant": {...}, ...facts} with the start recorded, or
        {"ok": False, "reason": behind|lag|threads|memory|unreadable, ...facts}. The readings are taken
        outside the host lock; the decision and the grant inside it. `grant=False` answers the same
        question and records nothing: the head stays in the order (a queue-less start then takes its
        slot and asks again with `grant=True`, so its grant is never older than its start)."""
        now = time.time() if now is None else float(now)
        if mark is not None:
            self.rec["mark"] = bool(mark)
        nproc = os.cpu_count() if nproc is None else nproc
        if not isinstance(nproc, int) or nproc <= 0:
            return self._said({"ok": False, "reason": "unreadable", "what": "no processor count"})
        usable, need = usable_and_need(s, nproc)
        facts = {"usable_threads": usable, "need_threads": need, "nproc": nproc,
                 "need_mem_mb": need * per_worker_mem_mb()}
        busy = None
        if need > 0:
            busy = busy_threads(samples, s, nproc)
            if busy is None:
                return self._said({"ok": False, "reason": "unreadable", "what": "the CPU reading is not full",
                                   **facts})
            mem_mb = mem_available_mb() if mem_mb is None else mem_mb
            if mem_mb is None:
                return self._said({"ok": False, "reason": "unreadable", "what": "MemAvailable unreadable",
                                   **facts})
        try:
            with _HostLock(self.d):
                return self._said(self._decide(s, now, need, busy, mem_mb, usable, facts, grant))
        except Unreadable as e:
            return self._said({"ok": False, "reason": "unreadable", "what": str(e), **facts})
        except OSError as e:
            return self._said({"ok": False, "reason": "unreadable",
                               "what": f"host state: {type(e).__name__}: {e}", **facts})

    def _said(self, r):
        self.last = r.get("reason") if not r["ok"] else None
        return r

    def _decide(self, s, now, need, busy, mem_mb, usable, facts, grant=True):
        self._ensure()
        self.rec["checked_at"] = now
        _rewrite(self.path, self.rec)
        fresh = 2.0 * float(s["POLL"]) + float(s["EMPTY_SAMPLE"])
        waiters = [(p, r) for p, r in _live(self.d, "wait", own={self.path})
                   if p == self.path or now - float(r.get("checked_at") or 0) <= fresh]
        waiters.sort(key=lambda pr: rank(pr[1], now, float(s["HOST_AGING"])))
        if waiters and waiters[0][0] != self.path:
            r = waiters[0][1]
            return {"ok": False, "reason": "behind",
                    "ahead": {k: r.get(k) for k in ("repo", "task", "kind", "mark", "arrival")}, **facts}
        last = _last_start(self.d)
        if now - last < float(s["HOST_LAG"]):
            return {"ok": False, "reason": "lag", "since_s": round(now - last, 1), "lag_s": float(s["HOST_LAG"]),
                    **facts}
        if need > 0:
            grants = _live(self.d, "grant", own=_own_grant_paths())
            recent = sum(float(r.get("threads", 0)) * _decay(r, now) for _p, r in grants)
            held_mem = sum(float(r.get("mem_mb", 0)) for _p, r in grants)
            cap = usable - busy
            if need >= usable:
                # T-14749: the need clamped to every usable thread (a host smaller than RESERVE + NEED):
                # the reserve absorbs ordinary background load, so a lone start is not held by it forever
                cap = min(usable, usable + int(s["HOST_RESERVE"]) - busy)
            free = cap - recent
            facts.update(free_threads=round(free, 1), busy_threads=round(busy, 1),
                         granted_recent_threads=round(recent, 1))
            if free < need:
                return {"ok": False, "reason": "threads", **facts}
            free_mem = mem_mb - held_mem
            facts.update(free_mem_mb=int(free_mem), held_mem_mb=int(held_mem))
            if free_mem < facts["need_mem_mb"]:
                return {"ok": False, "reason": "memory", **facts}
        if not grant:
            return {"ok": True, **facts}
        return {"ok": True, "grant": self._grant(now, need, facts["need_mem_mb"], last), **facts}

    def _grant(self, now, need, mem, last) -> dict:
        """Under the host lock: hold the grant, record the start, leave the wait."""
        path = self.d / f"grant-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        fd = None
        try:
            _write(path, {"ts": now, "threads": need, "mem_mb": mem, "repo": self.rec["repo"],
                          "task": self.rec["task"], "kind": self.rec["kind"]})
            fd = _flock_nb(path)
            if fd is None:
                raise OSError("the new grant's lock could not be taken")
            os.set_inheritable(fd, True)
            _write(self.d / "last_start", {"ts": now, "repo": self.rec["repo"], "task": self.rec["task"]})
        except BaseException:
            # nothing is published until every write held: no grant, no lock, no env (the caller holds)
            if fd is not None:
                os.close(fd)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        _GRANTS[str(path)] = fd
        os.environ[GRANT_ENV] = str(path)
        self.leave()
        return {"path": str(path), "ts": now, "previous_start": last}


_GRANTS: dict = {}     # this process's grants: path -> the inheritable fd holding its flock


def _own_grant_paths() -> set:
    own = {Path(p) for p in _GRANTS}
    env = (os.environ.get(GRANT_ENV) or "").strip()
    if env and env != INSIDE_VERIFY:
        own.add(Path(env))          # held by this process's ancestor or its pre-exec self
    return own


def release(grant) -> None:
    """End this process's hold of `grant` (the work ended); its children may still hold it."""
    if not grant:
        return
    fd = _GRANTS.pop(grant["path"], None)
    if fd is not None:
        os.close(fd)
    if os.environ.get(GRANT_ENV) == grant["path"]:
        os.environ.pop(GRANT_ENV, None)


def cancel(grant, _dir=None) -> None:
    """The repository pass did not hold after the grant: drop the grant and give the start back (the
    last start is restored when no later start replaced it)."""
    if not grant:
        return
    d = Path(grant["path"]).parent if _dir is None else Path(_dir)
    try:
        with _HostLock(d):
            stamp = _read(d / "last_start") or {}
            if stamp.get("ts") == grant["ts"]:
                _write(d / "last_start", {"ts": grant.get("previous_start") or 0.0})
            Path(grant["path"]).unlink(missing_ok=True)
    except OSError:
        pass
    release(grant)


def reserve_width(width: int, *, mem_mb=None, _dir=None) -> int:
    """The width the run holding a grant may take: no more workers than the memory every OTHER live
    grant leaves free, and never fewer than its own grant already reserved; the grant's memory AND its
    threads are then rewritten to that width under the host lock (its reservation is the real capacity,
    so a later head's gate counts the width the run took, not the need it asked for). Fail-closed: when the memory or the
    host state cannot be read, the width stays within what the grant already reserved. A process
    holding no grant (its env names none) gets `width` unchanged."""
    path = (os.environ.get(GRANT_ENV) or "").strip()
    if not path or path == INSIDE_VERIFY:
        return width
    p = Path(path)
    d = p.parent if _dir is None else Path(_dir)
    per = per_worker_mem_mb()
    mem_mb = mem_available_mb() if mem_mb is None else mem_mb
    try:
        with _HostLock(d):
            mine = _read(p) if p.exists() else None
            if mine is None or not _valid("grant", mine):
                raise Unverified(f"the host grant {p.name} this run holds cannot be read or is gone: no "
                                 f"worker starts on an unreserved width")
            reserved = max(1, int(float(mine["mem_mb"]) // per))
            if mem_mb is None:
                return max(1, min(int(width), reserved))
            others = sum(float(r["mem_mb"]) for q, r in _live(d, "grant", own=_own_grant_paths()) if q != p)
            room = max(reserved, int((mem_mb - others) // per))
            width = max(1, min(int(width), room))
            mine["mem_mb"] = width * per
            mine["threads"] = width        # the CPU share the gate counts is the width the run takes
            mine["width"] = width
            _rewrite(p, mine)
    except (Unreadable, OSError):
        # the host state cannot be read: stay within what this run's own grant already reserved
        mine = _read(p) if p.exists() else None
        if mine is None or not _valid("grant", mine):
            raise Unverified(f"the host grant {p.name} this run holds cannot be verified")
        return max(1, min(int(width), int(float(mine["mem_mb"]) // per)))
    return width


def says(r: dict) -> str:
    """One line naming what holds a heavy start at the host gate."""
    why = r.get("reason")
    if why == "behind":
        a = r.get("ahead") or {}
        return (f"host gate: behind the {a.get('kind')} of {a.get('task') or 'no card'} in {a.get('repo')} "
                f"(the longest-waiting eligible head starts first)")
    if why == "lag":
        return f"host gate: the last heavy start was {r.get('since_s')} s ago, start lag {r.get('lag_s'):g} s"
    if why == "threads":
        return (f"host gate: free usable threads {r.get('free_threads')} < need {r.get('need_threads')} "
                f"(usable {r.get('usable_threads')} of {r.get('nproc')})")
    if why == "memory":
        return (f"host gate: free memory {r.get('free_mem_mb')} MB (live starts hold {r.get('held_mem_mb')} MB) "
                f"< need {r.get('need_mem_mb')} MB")
    return f"host gate: {r.get('what') or 'unreadable'}; it holds"


def settings_now(main=None) -> dict:
    """The admission settings a queue-less caller passes the gate: the repository's own when they
    read (`admission.cur`, which also primes the sampler's settings), else the machine values alone."""
    from lib import admission
    try:
        return admission.cur(main)
    except Exception:                      # noqa: BLE001 — an unreadable project contract: machine values
        from lib import machine_settings as ms
        s = {name: admission.machine_value(ms, key)["value"] for name, key in admission.MACHINE.items()}
        admission.CUR = s
        return s


def wait_for_grant(repo, task, *, kind, on_held=None, grant=True, waiter=None, _sleep=time.sleep, _dir=None,
                   _samples=None):
    """Wait at the host gate until it grants this start, for a caller with no queue of its own (a land
    of a repository whose admission queue is off). Returns the answer that granted, or None when this
    process is already inside an admitted heavy run. `on_held(answer)` is called on every held answer
    (the caller reports a change of reason); it may raise to stop the wait."""
    if inside_admitted():
        return None
    from lib import admission
    s = settings_now(repo)
    samples = _samples if _samples is not None else admission.Samples()
    w = waiter if waiter is not None else Waiter(repo=repo, task=task, kind=kind, _dir=_dir)
    try:
        while True:
            r = w.check(s, samples, grant=grant)
            if r["ok"]:
                return r
            if on_held is not None:
                on_held(r)
            _sleep(max(0.05, min(float(s["SAMPLE"]), float(s["WINDOW"]))))
            s = settings_now(repo)
    finally:
        if grant or waiter is None:
            w.leave()


class Hold:
    """The host gate behind the queue-less ordered Stage-6 admission (`task._stage6_ordered_admission`)
    in the interface it asks: `ready()` once per poll, `commit()` once it may start, `reading` the facts
    of the last answer."""

    def __init__(self, s: dict, *, repo, task, arrival=None, _dir=None, _samples=None, _nproc=None):
        from lib import admission
        self.s = s
        self.nproc = _nproc
        self.samples = _samples if _samples is not None else admission.Samples()
        self.w = Waiter(repo=repo, task=task, kind="run", arrival=arrival, _dir=_dir)
        self.reading: dict = {}
        self.grant = None

    def _ask(self, grant) -> bool:
        r = self.w.check(self.s, self.samples, nproc=self.nproc, grant=grant)
        if r["ok"] and grant:
            self.grant = r.pop("grant")
        self.reading = dict(r)
        if not r["ok"]:
            self.reading["says"] = says(r)
        return r["ok"]

    def ready(self) -> bool:
        """May this run start once it holds its slot? Asked before the slot: nothing is granted."""
        return self.grant is not None or self._ask(False)

    def commit(self) -> bool:
        """With its slot held: take the grant now (the start's instant), or refuse and wait on."""
        return self.grant is not None or self._ask(True)

    def close(self) -> None:
        self.w.leave()
