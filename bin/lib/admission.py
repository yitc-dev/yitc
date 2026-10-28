"""SPEC-1045 — the resource-admission queue: ONE bounded queue per repo that decides WHEN an already
started Stage-6 run, own-tests check or land takes the repo's verify resources, never WHICH work.

PORTED, NOT REDESIGNED (SPEC-1045 rule 2). The source is cryptochart's settled `ops/deploy/
wait-for-room.py`, gist 46ed5855919802e2217424f8db92d42e revision 541a3834dd4a1ff5147514471de36e31b0c20c12
(sha256 5f379acdd458a12a05aefeeae34cc250091357cf0077238002daa9fe81141f3b). Its rules are kept section
for section; the section banners below carry the source's own headings, in the source's words where
a rule is unchanged, so a reader holds the two side by side. What rule 2 changes is marked `rule 2
(x)` where it is applied:
  (a) the engine's own code, entered by `task test --run` / `--own` FIRST (THE ENTRY, at the end);
  (b) the engine's own deciders, called in-process (A NO-LAYER RUN, A LIGHT RUN, THE PLACES);
  (c) the logical journal — rows named by timestamp and row sha, never a file offset (THE GREEN HOLD);
  (e) every pass, wait, step and leave is a row on the MAIN checkout's journal (THE PASS LOG);
  (g) work is alive while its flock is held — the work's children inherit BUSY (BUSY);
  (h) the kernel's own placement (THE PLACES); (i) no CPU set, no pinning (THE WINDOW);
  (j) the switch is read once, by the caller, at its start;
  (o) «runs nothing» is the whole verify: layers AND the test sweep (A NO-LAYER RUN, A LIGHT RUN).
NOT PORTED (rule 2): the release lock and its gate, land groups (one land passes at a time — a fixed
rule; BATCH_MAX is 1, REFUSAL_SPAN gone), the switch-transition steps, the ungated-work scan, the bare
form, and A SCRIPT CHANGED ON DISK — the ticket and state formats carry FORMAT, every engine version
reads every version, so a waiter keeps its place across an engine change with no re-exec.

THE CARRIERS T-14196 (the land side) and T-14197 (the admission steps, the hold's setting) use
UNCHANGED: the RUNNING entry (`register_running`), the green hold (`hold_read` / `set_hold` /
`hold_now` / `hold_row` / `landed`), the run-plus-land unit (`unit_runs` / `unit_ended` /
`unit_holds` / `unit_moving` / `land_unit_wait`), the land hold probe (`land_holding`), the light core
path, and the step row writer (`log_step`)."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

FORMAT = 1                      # the ticket / entry / hold format version; a reader takes any version
SOURCE = ("gist 46ed5855919802e2217424f8db92d42e rev 541a3834 wait-for-room.py "
          "sha256 5f379acdd458a12a05aefeeae34cc250091357cf0077238002daa9fe81141f3b")
PREFIX = "admission"
_said: set = set()


def say(text: str) -> None:
    """One line of the queue's own output (the source's `room:` / `wait:` lines), on stderr so the
    verb's stdout stays its own."""
    print(f"{PREFIX}: {text}", file=sys.stderr, flush=True)


def say_once(key, text: str) -> None:
    if key not in _said:
        _said.add(key)
        say(text)


# ═══ THE SETTINGS ═════════════════════════════════════════════════════════════════════════════
# Every number and CPU set is a machine setting and every class list a project DECLARATION
# (SPEC-1045 rule 4, rule 2 (f)); each default and its provenance lives ONLY in
# `machine_settings.INVENTORY` (SPEC-1031 rule 9). The source's names stay the keys of a check.
MACHINE = {
    "THRESHOLD": "YITC_ADMISSION_THRESHOLD_PCT",
    "WINDOW": "YITC_ADMISSION_WINDOW_S",
    "SAMPLE": "YITC_ADMISSION_SAMPLE_S",
    "POLL": "YITC_ADMISSION_POLL_S",
    "SPACING": "YITC_ADMISSION_SPACING_S",
    "STEP": "YITC_ADMISSION_STEP_S",
    "RUNS_AHEAD": "YITC_ADMISSION_RUNS_AHEAD",
    "PIN": "YITC_ADMISSION_PIN",
    "EMPTY_SAMPLE": "YITC_ADMISSION_EMPTY_SAMPLE_S",
    "LAND_TAIL_THRESHOLD": "YITC_ADMISSION_LAND_TAIL_THRESHOLD_PCT",
    "REMOTE_SLOTS": "YITC_ADMISSION_REMOTE_SLOTS",
    "LOCAL_RUNS": "YITC_ADMISSION_LOCAL_RUNS",
    "LIGHT_PIN": "YITC_ADMISSION_LIGHT_PIN",
    "GREEN_HOLD_S": "YITC_ADMISSION_GREEN_HOLD_S",
    "QUICK_LOCK_BOUND": "YITC_ADMISSION_QUICK_LOCK_BOUND_S",
    "QUICK_RUN_BOUND": "YITC_ADMISSION_QUICK_RUN_BOUND_S",
    "SYNC_BOUND": "YITC_ADMISSION_SYNC_BOUND_S",
    "LAND_SET_BOUND": "YITC_ADMISSION_LAND_SET_BOUND_S",
    "LAND_SET_FILE_BOUND": "YITC_ADMISSION_LAND_SET_FILE_BOUND_S",
}
DECLARED = {
    "ORDER": "admission.order",
    "AT_ONCE": "admission.at_once",
    "LIGHT_LAYERS": "admission.light_layers",
    "PLANNING_PATHS": "admission.planning.paths",
    "PLANNING_BRANCHES": "admission.planning.branches",
    "PLANNING_LANDS": "admission.planning_lands",
    "GREEN_HOLD_ON": "admission.green_hold",
    "RUN_LAND_UNIT_ON": "admission.run_land_unit",
}
BATCH_MAX = 1   # rule 2: ONE land at a time — a fixed rule, not a setting (the source's BATCH_MAX=1 trial)
# the classes of a queued ticket, in the order they pass by default, and those a class list may name
QUEUE_CLASSES = ("light", "land-mark", "run-mark", "run-light", "run", "land")
FAST_CLASSES = ("bookkeeping", "credit", "no-layer", "own-tests")


def parse_cpus(text):
    """The CPUs of a taskset list (`2-15,18-31`) as a frozenset, the empty set for an empty value,
    or None when it is not one."""
    text = "" if text is None else str(text)
    if not text.strip():
        return frozenset()
    cpus = set()
    for part in text.split(","):
        m = re.fullmatch(r"\s*([0-9]+)(?:-([0-9]+))?\s*", part)
        if not m or (m.group(2) and int(m.group(2)) < int(m.group(1))):
            return None
        cpus.update(range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1))
    return frozenset(cpus)


def fmt_cpus(cpus):
    out, run = [], []
    for c in sorted(cpus or ()):
        if run and c == run[-1] + 1:
            run.append(c)
        else:
            if run:
                out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
            run = [c]
    if run:
        out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ",".join(out)


def _load_ops(main):
    from lib import profile             # the one carrier reader (SPEC-1031 rule 4: from the main checkout)
    try:
        return profile._load_ops(Path(main))
    except Exception:                  # noqa: BLE001 — an unreadable carrier reads as such
        return profile._OPS_UNREADABLE


def settings(main) -> dict:
    """Every setting now, under the source's names, plus `_config` — the FULL applied configuration,
    every key with its value and its source (rule 2 (e)) — and `_hash`, a content hash of it. Read
    again at each check, as the source re-reads SETTINGS: a change reaches every waiter at its next
    check. A value a source refuses is the inventory's business (`coerce`): the next source holds."""
    from lib import machine_settings as ms
    ops = _load_ops(main)
    out: dict = {}
    config: list = []
    msources: dict = {}
    for name, key in MACHINE.items():
        rec = machine_value(ms, key)
        value = rec["value"]
        if name in ("PIN", "LIGHT_PIN"):
            cpus = parse_cpus(value)
            if cpus is None:
                say_once(("cpus", name, value), f"{key} {value!r} is not a CPU list; read as none")
                cpus = frozenset()
            value = cpus
        out[name] = value
        msources[name] = rec["source"]
    values, sources, notes = ms.admission_settings(ops)
    for note in notes:
        say_once(("note", note), note)
    for name, key in DECLARED.items():
        value = values[key]
        out[name] = tuple(value) if isinstance(value, (list, tuple)) else value
        config.append({"key": key, "value": list(value) if isinstance(value, (list, tuple)) else value,
                       "source": sources[key]})
    switches, vnotes = ms.verify_switches(ops)
    for name in ms.VERIFY_SWITCHES:
        config.append({"key": f"verify.{name}", "value": switches[name], "source": "yitc-ops.yaml"
                       if isinstance((ops or {}).get("verify") if isinstance(ops, dict) else None, dict)
                       and name in ops["verify"] else "built-in"})
    # the quick set the two switches act on is part of the applied configuration too (T-14198): a run and
    # a land under different quick sets carry different configuration hashes
    vsec = (ops or {}).get("verify") if isinstance(ops, dict) else None
    quick = vsec.get("post_sync_set") if isinstance(vsec, dict) else None
    config.append({"key": "verify.post_sync_set", "value": quick,
                   "source": "yitc-ops.yaml" if quick is not None else "built-in"})
    out["SYNC_IN_RUN"] = switches["sync_at_stage6_admission"]
    out["QUICK_FIRST"] = switches["post_sync_set_first"]
    out["GREEN_HOLD"] = float(out["GREEN_HOLD_S"]) if out["GREEN_HOLD_ON"] == "on" else 0.0
    out["RUN_LAND_UNIT"] = 1 if out["RUN_LAND_UNIT_ON"] == "on" else 0
    # LIGHT_PIN takes CPUs out of PIN, or lies wholly outside it (the shelf); one meeting PIN partially,
    # or equal to it, is said and read as none — the source's rule, unchanged
    light, pin = out["LIGHT_PIN"], out["PIN"]
    if light and pin and not light.isdisjoint(pin) and (not light <= pin or light == pin):
        say_once(("LIGHT_PIN", fmt_cpus(light), fmt_cpus(pin)),
                 f"LIGHT_PIN {fmt_cpus(light)} is not inside PIN {fmt_cpus(pin)} with a CPU of PIN left for "
                 "the other commands; read as none: every command on PIN")
        out["LIGHT_PIN"] = frozenset()
        msources["LIGHT_PIN"] = f"{msources['LIGHT_PIN']}, read as none (not inside PIN)"
    # the configuration as APPLIED (audit-post F5): every machine value after the checks above
    config[:0] = [{"key": key, "value": fmt_cpus(out[name]) if isinstance(out[name], frozenset) else out[name],
                   "source": msources[name]} for name, key in MACHINE.items()]
    out["_config"] = config
    out["_hash"] = config_hash(config)
    return out


def machine_value(ms, key) -> dict:
    """THE READ SITE of one SPEC-1045 machine key (SPEC-1031 rule 4: the environment layer of a
    PERFORMANCE knob is applied by its own read site): the environment, then the machine file, then the
    inventoried default — `in_force` answers the last two. An environment value `coerce` refuses is said
    once and the next source holds (the source's rule)."""
    raw = os.environ.get(key)
    if raw is not None and str(raw).strip() != "":
        try:
            return {"value": ms.coerce(ms.BY_NAME[key], str(raw).strip()), "source": "env"}
        except ms.SettingsRefused as e:
            say_once(("env", key, raw), f"{key} {raw!r} in the environment is not a valid value ({e}); the next "
                     "source holds")
    rec = ms.in_force(key)
    return {"value": rec["value"], "source": rec["source"]}


def config_hash(config) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def _module_revision() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "unknown"


_REVISION = _module_revision()   # the code THIS process runs: read once, at import
_CREDIT_CODE = ("land_report_arm", "_land_stage6_credit",   # the engine's credit answer the queue calls (T-14196)
                "_land_verify_skip_judge", "_land_verify_request")   # T-14272: the one judge it asks
_FULL_REVISION: list = [None]


def _code_digest(code, h) -> None:
    """Feed `h` the code object `code` as LOADED — its bytecode, constants (nested code included), names
    and variable names; never its file name or line numbers, so one code reads one digest wherever its
    checkout lies."""
    h.update(code.co_code)
    for c in code.co_consts:
        if hasattr(c, "co_code"):
            _code_digest(c, h)
        else:
            h.update(repr(c).encode())
    h.update(repr((code.co_names, code.co_varnames)).encode())


def _credit_code_bytes() -> bytes:
    """A digest of the credit code the queue calls (worktree.land_report_arm and the land's own
    `_land_stage6_credit`) as this process LOADED it — the code it runs, not the file on disk now."""
    from lib import worktree as engine_worktree
    h = hashlib.sha256()
    for name in _CREDIT_CODE:
        fn = getattr(engine_worktree, name)
        _code_digest(getattr(fn, "__wrapped__", fn).__code__, h)
    return h.hexdigest().encode()


def revision() -> str:
    """The queue revision (rule 2 (e)): a content hash of this module as it was when this process loaded
    it AND of the credit code it calls (T-14196) — the code that decides, not the file on disk now (an
    engine promoted under a waiter does not change what the waiter runs). Read once per process.
    Unreadable: `unknown`."""
    if _FULL_REVISION[0] is None:
        try:
            credit = _credit_code_bytes()
        except Exception:              # noqa: BLE001 — unreadable credit code: the revision says so
            credit = None
        _FULL_REVISION[0] = ("unknown" if _REVISION == "unknown" or credit is None else
                             hashlib.sha256(_REVISION.encode() + b"\0" + credit).hexdigest())
    return _FULL_REVISION[0]


CUR: dict = {}


def cur(main=None) -> dict:
    """The settings of the last check, read now when there was none (or when `main` is given)."""
    global CUR
    if main is not None or not CUR:
        CUR = settings(main if main is not None else _MAIN[0])
    return CUR


_MAIN: list = [None]


def affinity():
    """The CPUs this process may use (rule 2 (i): the window's read set with no PIN)."""
    try:
        return frozenset(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return frozenset(range(os.cpu_count() or 1))


def pins(s):
    """(run set, light set) of the settings `s`, as the CPUs a command is PINNED to — the empty set
    pins nothing (rule 2 (i)). With LIGHT_PIN set, PIN less LIGHT_PIN for every command but a light
    one's; a LIGHT_PIN outside PIN takes nothing from it."""
    pin, light = frozenset(s["PIN"]), frozenset(s["LIGHT_PIN"])
    if not light:
        return pin, pin
    return pin - light, light


def read_set(s):
    """The CPUs the window reads: the run set, or with no PIN the process's own CPUs (rule 2 (i))."""
    base = frozenset(s["PIN"]) or affinity()
    light = frozenset(s["LIGHT_PIN"])
    return (base - light) or base


def fmt_settings(s) -> str:
    """The settings as a pass row names them: NAME=value;… (the source's form)."""
    parts = []
    for name in (*MACHINE, *DECLARED):
        v = s.get(name)
        if isinstance(v, frozenset):
            v = fmt_cpus(v)
        elif isinstance(v, (list, tuple)):
            v = ",".join(v)
        parts.append(f"{name}={v}")
    return ";".join(parts)


# ═══ THE PLACES ON DISK ═══════════════════════════════════════════════════════════════════════
# LOCK, STAMP, QUEUE, BUSY, RUNNING, LANDHOLD, LIGHTCORE and HOLD under <git-common-dir>/yitc/
# admission/ (rule 1: all of it under the repo's git common directory, beside the land reservation),
# so a run from any task worktree shares them.
def state_dir(main) -> Path:
    from lib import git_env as _git_env
    out = subprocess.run(["git", "-C", str(main), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         capture_output=True, text=True, env=_git_env._git_child_env(None))
    if out.returncode != 0 or not out.stdout.strip():
        raise OSError(f"{main} is not inside a git checkout: {(out.stderr or '').strip()[:200]}")
    return Path(out.stdout.strip()) / "yitc" / "admission"


def paths(main) -> dict:
    d = state_dir(main)
    return {"dir": d, "lock": d / "lock", "stamp": d / "last-start", "queue": d / "queue",
            "busy": d / "busy.lock", "running": d / "running", "landhold": d / "land.lock",
            "lightcore": d / "light-core.lock", "hold": d / "green-hold", "main": Path(main)}


def _group_writable(target, mode) -> None:
    """Rule 1: the state is group-writable, whatever the process's umask — `mode` applied to a path or
    an open descriptor this process may change (another user's file is left as its owner made it)."""
    with contextlib.suppress(OSError):
        if isinstance(target, int):
            os.fchmod(target, mode)
        else:
            os.chmod(target, mode)


def _mkdirs(d) -> None:
    """`d` and its missing parents, each made group-writable (setgid, so the group is kept)."""
    d = Path(d)
    missing = []
    while not d.exists():
        missing.append(d)
        d = d.parent
    for m in reversed(missing):
        with contextlib.suppress(FileExistsError):
            m.mkdir()
        _group_writable(m, 0o2775)


def ensure(p) -> None:
    """The state directory exists, group-writable, and can be written, else OSError naming it."""
    for d in (p["dir"], p["queue"], p["running"]):
        _mkdirs(d)
        if not d.is_dir():
            raise OSError(f"{d} is not a directory")
    probe = p["dir"] / f".probe-{os.getpid()}"
    probe.write_text("", encoding="utf-8")
    probe.unlink()


class Locked:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.fd = _open_lockfile(self.path)
        fcntl.flock(self.fd, fcntl.LOCK_EX)

    def __exit__(self, *a):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)


def _open_lockfile(path) -> int:
    """A lock file opened for a flock, created group-writable (0664 whatever the umask)."""
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o664)
    _group_writable(fd, 0o664)
    return fd


def alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (TypeError, ValueError, OverflowError):
        return False


def write_json(path, data) -> None:
    """Write `data` to `path` whole: a temporary beside it (a name no reader takes for a ticket or an
    entry), renamed over it."""
    path = Path(path)
    tmp = path.parent / f".tmp-{path.name}-{os.getpid()}"
    tmp.write_text(json.dumps(data) + "\n", encoding="utf-8")
    _group_writable(tmp, 0o664)
    os.replace(tmp, path)


def read_json(path):
    """The JSON object at `path`, or None when it is absent, unreadable or not an object. Unknown keys
    are kept and ignored by the readers; a missing key reads as its default — the format-tolerant
    read every engine version makes of every other's files."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


# ═══ THE TICKETS ══════════════════════════════════════════════════════════════════════════════
# Each waiter files a ticket in QUEUE (its name: arrival time in ns, pid, kind land|run, mark 1|0, and
# a fifth part `x` for an exclusive run, `l` for a light land or a light run, `p` for a planning land;
# its content: cwd, the card, for a land the runs that passed ahead of it, for a light run its reason,
# and the wait row that named it); dead waiters' tickets are swept under the lock.
def kind_mark(name):
    """(kind, mark) of a ticket name; an old ticket <ns>-<pid> is an unmarked run."""
    parts = name.split("-")
    return (parts[2] if len(parts) > 2 else "run"), (parts[3] if len(parts) > 3 else "0")


def is_exclusive(name) -> bool:
    parts = name.split("-")
    return len(parts) > 4 and parts[4] == "x"


def land_class(name) -> str:
    parts = name.split("-")
    return {"l": "light", "p": "planning"}.get(parts[4] if len(parts) > 4 else "", "land")


def is_light(name) -> bool:
    return kind_mark(name)[0] == "land" and land_class(name) == "light"


def land_ticket(ns, pid, cls, mark) -> str:
    if cls == "light":
        return f"{ns}-{pid}-land-0-l"
    if cls == "planning":
        return f"{ns}-{pid}-land-1-p"
    return f"{ns}-{pid}-land-{1 if mark else 0}"


def run_ticket(ns, pid, mark, exclusive=False, light=False) -> str:
    return f"{ns}-{pid}-run-{1 if mark else 0}" + ("-x" if exclusive else "-l" if light else "")


def ticket_class(name) -> str:
    """`light`, `land-mark` (a land its card marks, or a planning land), `run-mark`, `run-light`, `run`
    (an exclusive run among them) or `land`."""
    kind, mark = kind_mark(name)
    if kind == "land":
        return "light" if land_class(name) == "light" else "land-mark" if mark == "1" else "land"
    if mark == "1":
        return "run-mark"
    parts = name.split("-")
    return "run-light" if len(parts) > 4 and parts[4] == "l" else "run"


def class_in(name, names) -> str:
    """The class of a ticket as the class list `names` reads it: a run-light the list does not name
    reads as a run."""
    cls = ticket_class(name)
    return "run" if cls == "run-light" and cls not in names else cls


# ═══ THE ORDER ════════════════════════════════════════════════════════════════════════════════
# The classes in the order ORDER names them, read at each check; a class it leaves out comes after
# the named ones, in the default order; within each, arrival.
def order(name):
    named = tuple(cur()["ORDER"])
    rank = (named + tuple(c for c in QUEUE_CLASSES if c not in named)).index(class_in(name, named))
    return (rank, int(name.split("-")[0]))


def tickets(queue) -> list:
    """The live tickets in their order of passing; dead waiters' tickets are removed (under LOCK)."""
    live = []
    try:
        names = os.listdir(queue)
    except FileNotFoundError:
        return live
    for name in names:
        try:
            pid = int(name.split("-")[1])
            order(name)
        except Exception:              # noqa: BLE001 — not a ticket (a temporary, a stray file)
            continue
        if alive(pid):
            live.append(name)
        else:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(os.path.join(queue, name))
    return sorted(live, key=order)


def runs_ahead(queue, name) -> int:
    """The runs that passed while the land of ticket `name` waited; a count that cannot be read reads
    RUNS_AHEAD: the lands go before the next run, never the run before them."""
    data = read_json(os.path.join(queue, name)) or {}
    n = data.get("runs_ahead")
    return n if type(n) is int and n >= 0 else cur()["RUNS_AHEAD"]


def count_run(queue, q) -> None:
    """A run passes: one more run ahead of each waiting ordinary land, in its own ticket (under LOCK)."""
    for name in q:
        if kind_mark(name) != ("land", "0") or is_light(name):
            continue
        path = os.path.join(queue, name)
        data = read_json(path)
        n = (data or {}).get("runs_ahead")
        if data is not None and type(n) is int and n >= 0:
            data["runs_ahead"] = n + 1
            write_json(path, data)


def group(q, land_held=False, tail=False) -> list:
    """The ticket that passes next (under LOCK; `q` in its order). While a land holds (`land_held`)
    none: nothing passes into a land's tail — but with `tail` (one land holds alone) the ticket that
    would pass with no land holding, when it is one run that is not exclusive. Else a light land alone;
    else a marked or planning land alone; else the oldest ordinary land when BATCH_MAX (1) of them wait
    or the oldest has let RUNS_AHEAD runs pass; else the first run; else the ordinary land. Rule 2: one
    land at a time, so a land group is always one land."""
    if not q:
        return []
    if land_held:
        g = group(q) if tail else []
        return g if len(g) == 1 and kind_mark(g[0])[0] == "run" and not is_exclusive(g[0]) else []
    head = ticket_class(q[0])
    if head in ("light", "land-mark"):
        return q[:1]
    lands = [t for t in q if ticket_class(t) == "land"][:BATCH_MAX]
    if head == "land" or (lands and (len(lands) == BATCH_MAX
                                     or runs_ahead(_P[0]["queue"], lands[0]) >= cur()["RUNS_AHEAD"])):
        return lands[:1]
    return q[:1]


def remark(p, s=None) -> None:
    """Each waiting ticket's mark read again from its card (T-14266, yitc#197: a fact that decides a
    ticket's place is read at each check from durable state, never kept from its arrival). Under LOCK,
    before the queue is read: a run or an ordinary land whose card's live queue-jump mark (the engine's
    own reader, `queue_jump`) differs from the mark in its name is renamed in place — its arrival, pid
    and suffix kept — and one `mark` step row is written. A light or planning land carries no mark of
    its own (`land_ticket`) and is left as it is; its owner finds its ticket again by `own_ticket`."""
    try:
        names = os.listdir(p["queue"])
    except FileNotFoundError:
        return
    for name in names:
        parts = name.split("-")
        if len(parts) < 4 or parts[2] not in ("run", "land") or parts[3] not in ("0", "1"):
            continue
        if parts[2] == "land" and land_class(name) != "land":
            continue
        task = ticket_task(p, name)
        now = queue_jump(p["main"], task)
        if now == (parts[3] == "1"):
            continue
        new = "-".join(parts[:3] + ["1" if now else "0"] + parts[4:])
        try:
            os.rename(Path(p["queue"]) / name, Path(p["queue"]) / new)
        except FileNotFoundError:
            continue
        log_step(p, task, "mark", "set" if now else "cleared", 0.0, f"{task}:{ticket_class(new)}", ticket=new, s=s)
        say(f"queue-jump mark {'set' if now else 'cleared'} on {task}'s card: its ticket is now {ticket_class(new)}, "
            "keeping its arrival")


def own_ticket(queue, ns, pid):
    """The name of the ticket of arrival `ns` and pid `pid` in `queue` as it stands now (a `remark` may
    have renamed it), or None."""
    head = f"{ns}-{pid}-"
    try:
        return next((n for n in os.listdir(queue) if n.startswith(head)), None)
    except FileNotFoundError:
        return None


def carried_arrival(p, card):
    """The arrival (ns) a NEW run ticket of `card` keeps (T-14273, SPEC-1045 rule 2 (d)): when the card's
    newest run ticket was admitted and its sync at admission stopped on a merge conflict, the next run
    ticket of that card takes the stopped ticket's arrival, so it re-enters at its old place. Read from
    the main journal only (rule 2 (c)), never from process memory: the card's admission rows since its
    card's `created_at` (the horizon). The newest of the card's run `wait` rows and its `sync` step rows
    decides — a sync step with outcome `conflict` carries, anything else (a wait row: that next ticket
    was already filed; a clean or failed sync) carries nothing; the arrival is the ticket name of the
    newest pass row of the same pid before that step. Anything unclear (no card, no horizon, an
    unreadable journal, no such pass) reads None: a fresh arrival, as before."""
    since = _card_created(p["main"], card)
    if since is None:
        return None
    return _conflict_arrival(card, Path(p["main"]) / "events.jsonl", since)


def _card_created(main, card):
    """The `created_at` of `card`'s card on the main checkout (the glob the engine's queue-jump reader
    uses), as an ISO string, or None."""
    if not card:
        return None
    try:
        import yaml
        cards = sorted((Path(main) / "tasks").glob(f"{card}-*.yaml"))
        doc = yaml.safe_load(cards[0].read_text(encoding="utf-8")) if len(cards) == 1 else None
        at = doc.get("created_at") if isinstance(doc, dict) else None
    except Exception:                  # noqa: BLE001 — an unreadable card carries nothing
        return None
    if hasattr(at, "timestamp"):
        return iso(at.timestamp())
    return at if isinstance(at, str) and len(at) >= 10 else None


def _conflict_arrival(card, journal, since):
    """The arrival ns of `card`'s run ticket stopped by a sync conflict, per `carried_arrival`, read
    from `journal` through the engine's segment-aware reader in the journal's own order; or None."""
    from lib import journal as journal_mod
    try:
        got = journal_mod.segment_rows_since(Path(journal), since[:10], types=(WAIT, PASS, STEP))
    except Exception:                  # noqa: BLE001 — an unreadable journal carries nothing
        return None
    passes, last = {}, None
    for r in got:
        if not isinstance(r, dict) or r.get("task_id") != card or str(r.get("ts", "")) < since:
            continue
        d = r.get("data") if isinstance(r.get("data"), dict) else {}
        if r.get("type") == PASS and kind_mark(str(d.get("ticket") or "x-x"))[0] == "run":
            passes[d.get("pid")] = d.get("ticket")
        elif r.get("type") == WAIT and d.get("kind") in ("run", "run-mark", "run-exclusive"):
            last = None
        elif r.get("type") == STEP and d.get("kind") == "sync":
            last = passes.get(d.get("pid")) if d.get("outcome") == "conflict" else None
    try:
        return int(str(last).split("-")[0]) if last else None
    except ValueError:
        return None


_P: list = [None]   # the paths of this process's queue (set at the entry)


def last_start(p):
    """(time, who) of the last head's pass (STAMP); no stamp reads (0, '-')."""
    try:
        t, who = Path(p["stamp"]).read_text(encoding="utf-8").split(" ", 1)
        return float(t), who.strip()
    except (OSError, ValueError):
        return 0.0, "-"


# ═══ BUSY ═════════════════════════════════════════════════════════════════════════════════════
# Every queued pass takes a SHARED flock on BUSY (an exclusive run: EXCLUSIVE), and so does every fast
# pass — an own-tests check and a no-layer run included (rule 2 (g)) — and keeps it while its work
# runs; the work's children inherit the descriptor (`inherit`), so the flock stands until the work
# and whatever of it keeps the descriptor have ended, also when the owner is killed. Whatever waits
# for work to end reads those flocks, never a pid entry (rule 2 (g)).
def try_flock(path, how):
    """The descriptor of a flock `how` on `path` taken without waiting, or None when it is held."""
    _mkdirs(Path(path).parent)
    fd = _open_lockfile(path)
    try:
        fcntl.flock(fd, how | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def take_busy(p, exclusive=False):
    return try_flock(p["busy"], fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)


def _probe(path, how) -> bool:
    """Whether a flock `how` on `path` could NOT be taken now (it is held against it)."""
    fd = try_flock(path, how)
    if fd is None:
        return True
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    return False


def busy_exclusive(p) -> bool:
    """Whether BUSY is held exclusive (an exclusive run, also one whose owner is gone)."""
    return _probe(p["busy"], fcntl.LOCK_SH)


def busy_held(p) -> bool:
    """Whether BUSY is held at all — a passed command's work, also after its owner is gone."""
    return _probe(p["busy"], fcntl.LOCK_EX)


def land_holding(p) -> bool:
    """Whether a land holds (the shared flock on LANDHOLD its command keeps until it ends)."""
    return _probe(p["landhold"], fcntl.LOCK_EX)


_INHERIT: list = []
_POPEN_INIT = [None]


def inherit(fds) -> None:
    """Rule 2 (g): from now on every child this process starts holds `fds` (BUSY, a land hold): the
    descriptors are made inheritable and added to the `pass_fds` of every `subprocess.Popen` — the
    engine's spawns pass no descriptor of their own, so without this a layer would run free of the
    flock its run took. Undone by `inherit(())`."""
    _INHERIT[:] = [fd for fd in fds if fd is not None]
    for fd in _INHERIT:
        os.set_inheritable(fd, True)
    if _INHERIT and _POPEN_INIT[0] is None:
        orig = subprocess.Popen.__init__

        def __init__(self, *args, **kwargs):
            if _INHERIT and kwargs.get("close_fds", True) is not False:
                kwargs["pass_fds"] = tuple(sorted({*tuple(kwargs.get("pass_fds") or ()), *_INHERIT}))
            return orig(self, *args, **kwargs)
        _POPEN_INIT[0] = orig
        subprocess.Popen.__init__ = __init__


def uninherit() -> None:
    _INHERIT[:] = []
    if _POPEN_INIT[0] is not None:
        subprocess.Popen.__init__ = _POPEN_INIT[0]
        _POPEN_INIT[0] = None


# ═══ THE HOST: RUNNING ═════════════════════════════════════════════════════════════════════════
KINDS = ("run", "land", "exclusive", "credit", "bookkeeping", "no-layer", "remote", "own-tests")
UNIT_KINDS = ("run", "exclusive", "remote")   # the RUNNING kinds of a run the queue let pass


def running_kinds(p) -> dict:
    """{pid: kind} of the owners that passed and run their work (a kind of KINDS; an entry whose kind
    cannot be read reads land); dead entries are removed."""
    live: dict = {}
    try:
        names = os.listdir(p["running"])
    except FileNotFoundError:
        return live
    for name in names:
        if not name.isdigit():
            continue
        if alive(int(name)):
            entry = read_json(Path(p["running"]) / name) or {}
            kind = entry.get("kind")
            live[int(name)] = kind if kind in KINDS else "land"
        else:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(os.path.join(p["running"], name))
    return live


def running_entry(p, pid):
    return read_json(Path(p["running"]) / str(pid))


def register_running(p, kind, *, alone=False, side=None, task=None, stage6=False, journals=None,
                     since_ts=None, extra=None) -> Path:
    """Record this owner in RUNNING (under LOCK, at its pass): its cwd, kind, for a land whether it
    passed alone, for a pinned command its side, the CPUs and the LIGHT_PIN of its pass, the card it
    runs for, for a run whether it is a card's Stage-6 run (`stage6`) and then the journals a pause or
    halt row of its card is read from and the timestamp of its pass (`since_ts` — rule 2 (c): a row
    at or after it ends the unit; no journal size). Returns the entry's path; `drop_running` removes it."""
    _mkdirs(p["running"])
    mine = Path(p["running"]) / str(os.getpid())
    entry = {"v": FORMAT, "cwd": os.getcwd(), "kind": kind, "alone": bool(alone), "task": task,
             "at": time.time(), "since_ts": since_ts}
    if kind in UNIT_KINDS:
        entry["stage6"] = bool(stage6)
        if stage6:
            js = [str(j) for j in (journals or ())]
            entry.update(journals=js, since_ts=since_ts,
                         seen=seen_at(task, js, since_ts) if task and since_ts else [])
    if side:
        s = cur()
        entry.update(side=side, cpus=sorted(pins(s)[side == "light"]), light_pin=sorted(s["LIGHT_PIN"]))
    entry.update(extra or {})
    write_json(mine, entry)
    return mine


def drop_running(p) -> None:
    with contextlib.suppress(FileNotFoundError, OSError):
        os.unlink(Path(p["running"]) / str(os.getpid()))


def running_tasks(p) -> dict:
    out = {}
    for pid, kind in running_kinds(p).items():
        task = (running_entry(p, pid) or {}).get("task")
        out[pid] = (kind, task if isinstance(task, str) else None)
    return out


def side_of(p, pid) -> str:
    return "light" if (running_entry(p, pid) or {}).get("side") == "light" else "run"


def crossing(p, side, s) -> list:
    """Under LOCK: the live commands of the other side placed under a LIGHT_PIN other than that of `s`
    whose CPUs meet the CPUs a pass of `side` takes under `s`. An entry of older code (no side) reads
    side run, on PIN, placed under no LIGHT_PIN."""
    mine = pins(s)[side == "light"]
    out = []
    for pid, kind in sorted(running_kinds(p).items()):
        entry = running_entry(p, pid) or {}
        try:
            theirs = set(int(c) for c in entry.get("cpus", s["PIN"]))
            placed = frozenset(int(c) for c in entry.get("light_pin", ()))
        except (TypeError, ValueError):
            theirs, placed = set(s["PIN"]), frozenset()
        if entry.get("side", "run") != side and placed != s["LIGHT_PIN"] and theirs & mine:
            out.append(f"{kind} pid {pid} (placed under LIGHT_PIN {fmt_cpus(placed) or '(none)'})")
    return out


def land_alone(p) -> bool:
    """Whether the land hold is held by one land alone (under LOCK): exactly one live RUNNING entry of
    kind land or credit, and it can be read. Rule 2 has no land groups, so the one entry is alone;
    none (a land whose owner is gone) or two read as not alone."""
    lands = [pid for pid, kind in running_kinds(p).items() if kind in ("land", "credit")]
    if len(lands) != 1:
        return False
    return running_entry(p, lands[0]) is not None


def holds(p, beside=()) -> list:
    """What the queue holds now (under LOCK): [] when nothing is held. Held: a live RUNNING entry of any
    kind (an own-tests check on the light side excepted); the land hold; BUSY held by anyone (a queued
    command keeps its shared flock also when its owner is gone). A live entry whose kind is in
    `beside` is not held either (a land head leaves a running bookkeeping land out)."""
    out = [f"{kind} pid {pid}" for pid, kind in sorted(running_kinds(p).items())
           if not (kind == "own-tests" and side_of(p, pid) == "light") and kind not in beside]
    if land_holding(p):
        out.append("the land hold")
    # rule 2 (g): an own-tests check holds BUSY shared too, and a flock does not name its holder — so a
    # light-side own-tests check, whose RUNNING entry is not held above, is held here (fail-closed: the
    # busy hold of a killed owner's children reads the same)
    if busy_held(p):
        out.append("a passed command's busy hold")
    return out


def credit_running(p) -> list:
    return [pid for pid, kind in running_kinds(p).items() if kind == "credit"]


def exclusive_running(p) -> list:
    return sorted(pid for pid, kind in running_kinds(p).items() if kind == "exclusive")


# ═══ THE GREEN HOLD AND THE RUN-PLUS-LAND UNIT — the carriers (definer for T-14196 / T-14197) ═══
# A green end of card X's Stage-6 run sets the green hold of X: the file HOLD naming X, its worktree,
# the time and the journals a pause or halt row of X is read from. One of X already standing is
# renewed; one of another card is kept and none set (one owner, never handed over). It ends: (1) when
# a land of X ends with 0 (`landed`) — or a land_completed ok row of task/X is on a journal at or after
# its set, whatever path landed X (T-14266) —; (2) GREEN_HOLD s after its set (`expired`); (3) at a
# task_paused or bg_dispatch_halted row of X in either journal at or after its set — read over the
# LOGICAL journal (rule 2 (c): every segment, an archived one included; the row named by its
# timestamp and row sha, never a byte offset). (2) and (3) wait while a live RUNNING entry of X stands
# (the fence). A HOLD that cannot be read holds every card and ends only by (2), dated by the file's
# time. A unit (admission.run_land_unit) opens at the pass of a card's Stage-6 run and ends with its
# run (its RUNNING entry goes), at a pause or halt row of the card at or after its pass, or, after a
# green end, with the green hold's ends.
HOLD_TYPES = ("task_paused", "bg_dispatch_halted")
LAND_TYPE = "land_completed"


def iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def row_sha(row) -> str:
    """The name of a journal row beside its timestamp (rule 2 (c)): a content hash of its type, task,
    timestamp and data — the `source` the engine's writer stamps into the data left out, so the name the
    queue gives a row it writes is the name a reader computes from the stored row."""
    data = row.get("data") if isinstance(row.get("data"), dict) else row.get("data")
    if isinstance(data, dict):
        data = {k: v for k, v in data.items() if k != "source"}
    core = {"type": row.get("type"), "task_id": row.get("task_id"), "ts": row.get("ts"), "data": data}
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()[:16]


def journals_of(main, wt) -> list:
    """The journals a card's pause or halt row is read from: the main checkout's and its worktree's."""
    out = [str(Path(main) / "events.jsonl")]
    if wt and Path(wt).resolve() != Path(main).resolve():
        out.append(str(Path(wt) / "events.jsonl"))
    return out


def _card_end_rows(card, journals, since, land=False):
    """The task_paused / bg_dispatch_halted rows of `card` in `journals` with a timestamp at or after
    `since`, each as (row, journal), read through the engine's segment-aware reader (SPEC-0190 rule 1):
    a row rotated into an archive segment is read like any other; a journal that cannot be read
    contributes nothing. With `land` also the card's ok land: a `land_completed` row of branch
    task/<card> with status ok, by whatever path it landed (T-14266, yitc#197)."""
    from lib import journal as journal_mod
    types = HOLD_TYPES + (LAND_TYPE,) if land else HOLD_TYPES
    out = []
    for path in journals or ():
        try:
            got = journal_mod.segment_rows_since(Path(path), since[:10], types=types)
        except Exception:              # noqa: BLE001 — an unreadable journal names no end
            continue
        for r in got:
            if not isinstance(r, dict) or r.get("type") not in types:
                continue
            d = r.get("data") if isinstance(r.get("data"), dict) else {}
            if r["type"] == LAND_TYPE:
                mine = d.get("branch") == f"task/{card}" and d.get("status") == "ok"
            else:
                mine = card in (r.get("task_id"), d.get("task"))
            if mine and str(r.get("ts", "")) >= since:
                out.append((r, str(path)))
    return sorted(out, key=lambda rj: (str(rj[0].get("ts", "")), row_sha(rj[0]), rj[1]))   # a total order


def seen_at(card, journals, ts, land=False) -> list:
    """The row shas of `card`'s end rows already written in the second `ts` names, recorded when a hold
    is set or a unit opens: rows of that same second are told apart by name (rule 2 (c)), never by a
    byte offset — a row in the set's own second that was already there does not end what is set."""
    return sorted({row_sha(r) for r, _j in _card_end_rows(card, journals, ts, land) if str(r.get("ts")) == ts})


def hold_row(h, land=False):
    """(`paused` | `halted`, {ts, sha, journal}) when a task_paused or bg_dispatch_halted row of the
    card `h["card"]` lies in one of `h["journals"]` at or after `h["set_ts"]` and is not one the set
    already saw (`h["seen"]`, the rows of its own second), else None; with `land` also (`land`, ...)
    for the card's ok `land_completed` row (T-14266)."""
    since, card = h.get("set_ts"), h.get("card")
    if not isinstance(since, str) or not card:
        return None
    seen = set(h.get("seen") or ())
    for r, path in _card_end_rows(card, h.get("journals"), since, land):
        sha = row_sha(r)
        if str(r.get("ts")) == since and sha in seen:
            continue
        why = {"task_paused": "paused", LAND_TYPE: "land"}.get(r["type"], "halted")
        return (why, {"ts": r.get("ts"), "sha": sha, "journal": path})
    return None


def hold_read(p):
    """The green hold as its file holds it: {card, worktree, set_at, set_ts, pid, journals}, or None.
    A file that cannot be read or parsed is a hold of no card dated by the file's time: it holds every
    card and ends only by its bound (fail-closed). An older format's keys are read where they mean the
    same; a missing set_ts reads from set_at."""
    try:
        st = os.stat(p["hold"])
    except FileNotFoundError:
        _UNREADABLE_SINCE.pop(str(p["hold"]), None)
        return None
    except OSError:
        # its metadata cannot be read either: dated by when THIS process first found it so (a stable
        # date, audit-post F1), so the bound ends it within GREEN_HOLD of that sight
        since = _UNREADABLE_SINCE.setdefault(str(p["hold"]), time.time())
        return {"card": None, "set_at": since, "set_ts": iso(since), "journals": [], "unreadable": True}
    h = read_json(p["hold"])
    try:
        if h is None or not isinstance(h.get("card"), str):
            raise ValueError("no card")
        h["set_at"] = float(h["set_at"])
        h.setdefault("set_ts", iso(h["set_at"]))
        j = h.get("journals")
        h["journals"] = list(j) if isinstance(j, (list, tuple, dict)) else []
        return h
    except (ValueError, TypeError, KeyError):
        return {"card": None, "set_at": st.st_mtime, "set_ts": iso(st.st_mtime), "journals": [],
                "unreadable": True}


_UNREADABLE_SINCE: dict = {}   # hold path -> when this process first found its metadata unreadable


def hold_says(h, s) -> str:
    return (f"a green hold stands for {h['card'] or 'no card (an unreadable hold file)'} "
            f"({time.time() - h['set_at']:.0f} s of GREEN_HOLD {s['GREEN_HOLD']:g} s; it ends at that card's land)")


def hold_now(p, s):
    """The green hold standing now (under LOCK), or None. GREEN_HOLD 0 (admission.green_hold off): none,
    and the file is left as it is. A hold past its bound, or whose card has a pause or halt row since
    its set, ends — the file is removed and one step row written — but while a live RUNNING entry of
    its card stands it is kept (the fence)."""
    if not s["GREEN_HOLD"]:
        return None
    h = hold_read(p)
    if h is None:
        return None
    age = time.time() - h["set_at"]
    why = ("expired", f"GREEN_HOLD {s['GREEN_HOLD']:g} s", None) if age >= s["GREEN_HOLD"] else None
    if why is None and h["card"]:
        row = hold_row(h, land=True)
        why = ("cleared", row[0], row[1]) if row else None
    if why is None:
        return h
    live = sorted((pid, kind) for pid, (kind, task) in running_tasks(p).items() if h["card"] and task == h["card"])
    if live:
        say_once(("fence", h["card"], h["set_at"], tuple(live)),
                 f"the green hold of {h['card']} is due to end ({why[0]}: {why[1]}), but its "
                 f"{', '.join(f'{k} pid {pid}' for pid, k in live)} still runs: it stands until that has ended")
        return h
    try:
        os.unlink(p["hold"])
    except FileNotFoundError:
        return None
    except OSError as e:
        # it ended (its bound or its card's row) but cannot be removed: an ended hold holds nothing
        say_once(("hold-unlink", h["set_at"]), f"the green hold ended ({why[0]}) but its file cannot be removed "
                 f"({e}); it holds nothing")
        return None
    log_step(p, h["card"], "hold", why[0], age, f"{h['card'] or 'unreadable'}:{why[1]}", row=why[2])
    say(f"the green hold of {h['card'] or 'no card (an unreadable hold file)'} {why[0]} ({why[1]}) after {age:.0f} s")
    return None


def held_q(p, q, h, s=None) -> list:
    """The tickets that may pass while the hold `h` stands: those of its card; all of them with none.
    Under `admission.planning_lands: immediately` (SPEC-1045 rule 2 (l), T-14196) a planning land's
    ticket also may (`planning_free`)."""
    s = s if s is not None else CUR
    return q if h is None else [t for t in q if (h["card"] and ticket_task(p, t) == h["card"])
                                or planning_free(t, s)]


def planning_free(name, s) -> bool:
    """SPEC-1045 rule 2 (l): whether the ticket `name` is a planning land that passes another card's
    green hold and unit (`admission.planning_lands: immediately`). `after-run` is the source's planning
    land, held by both like any queued land. It still waits for a land in flight, its merge checks,
    SPACING and its reading — nothing else is exempted."""
    return (kind_mark(name)[0] == "land" and land_class(name) == "planning"
            and (s or {}).get("PLANNING_LANDS") == "immediately")


def ticket_task(p, name):
    task = (read_json(Path(p["queue"]) / name) or {}).get("task")
    return task if isinstance(task, str) else None


def set_hold(p, card, wt, s=None) -> str:
    """After a green end of card `card`'s Stage-6 run (T-14197 calls it): with GREEN_HOLD on, the hold
    for that card, written under LOCK; one standing for the same card is renewed; one standing for
    another card is kept and this one not set. Under RUN_LAND_UNIT a run whose unit a pause or halt of
    its card ended sets no hold. Each outcome is one step row; returns it (set | renewed | refused |
    off)."""
    s = s if s is not None else cur(p["main"])
    if not s["GREEN_HOLD"]:
        return "off"
    journals = journals_of(p["main"], wt)
    with Locked(p["lock"]):
        ended = None
        if s["RUN_LAND_UNIT"]:
            entry = running_entry(p, os.getpid())
            ended = unit_ended(entry, card) if entry else None
        if ended:
            log_step(p, card, "hold", "refused", 0.0, f"{ended[0]}-in-run:{card}", row=ended[1])
            say(f"no green hold set for {card}: its unit ended at a {'pause' if ended[0] == 'paused' else 'halt'} "
                "row of the card during the run (admission.run_land_unit)")
            return "refused"
        h = hold_now(p, s)
        if h is not None and h["card"] != card:
            log_step(p, card, "hold", "refused", 0.0, f"held-by:{h['card'] or 'unreadable'}")
            say(f"no green hold set for {card}: {hold_says(h, s)}")
            return "refused"
        now = time.time()
        write_json(p["hold"], {"v": FORMAT, "card": card, "worktree": str(wt), "set_at": now, "set_ts": iso(now),
                               "seen": seen_at(card, journals, iso(now), land=True), "pid": os.getpid(),
                               "journals": journals})
        outcome = "renewed" if h is not None else "set"
        log_step(p, card, "hold", outcome, s["GREEN_HOLD"], card)
    say(f"green hold {outcome} for {card}: no Stage-6 run and no land whose changes run a layer passes "
        f"until its land ends with 0, its pause, or GREEN_HOLD {s['GREEN_HOLD']:g} s")
    return outcome


def landed(p, card, code, s=None):
    """A land of `card` ended with `code` (T-14196 calls it): 0 ends that card's green hold (step row
    `cleared` land); any other end leaves it standing. Returns `code`."""
    s = s if s is not None else cur(p["main"])
    if code == 0 and card and s["GREEN_HOLD"]:
        with Locked(p["lock"]):
            h = hold_read(p)
            if h is not None and h["card"] == card:
                try:
                    os.unlink(p["hold"])
                except FileNotFoundError:
                    h = None
                if h is not None:
                    log_step(p, card, "hold", "cleared", time.time() - h["set_at"], f"{card}:land")
                    say(f"the green hold of {card} cleared: its land ended with 0")
    return code


def unit_ended(entry, card):
    """(`paused` | `halted`, row) when the unit of the RUNNING `entry` of `card` has ended by a pause or
    halt row of the card at or after its pass (hold_row over the journals and since_ts it recorded),
    else None; an entry with none recorded (older code) has not."""
    if not isinstance(entry, dict) or not entry.get("journals") or not isinstance(entry.get("since_ts"), str):
        return None
    return hold_row({"card": card, "set_ts": entry["since_ts"], "journals": entry["journals"],
                     "seen": entry.get("seen")})


def unit_runs(p, s) -> list:
    """[(pid, card)] of the live RUNNING entries that open a unit, [] while RUN_LAND_UNIT is off. A unit
    is a card's Stage-6 run the queue let pass (kind run, exclusive or remote with `stage6` true; an
    entry of older code with no `stage6` when it names a card). An entry that cannot be read is a unit
    of no card (None): it holds every card's land until its owner is gone (fail-closed)."""
    if not s["RUN_LAND_UNIT"]:
        return []
    out = []
    for pid, kind in sorted(running_kinds(p).items()):
        entry = running_entry(p, pid)
        if entry is None or "kind" not in entry:
            out.append((pid, None))
            continue
        if kind not in UNIT_KINDS:
            continue
        task = entry.get("task") if isinstance(entry.get("task"), str) else None
        if entry.get("stage6") is True or ("stage6" not in entry and task):
            if task and unit_ended(entry, task):
                continue
            out.append((pid, task))
    return out


def unit_holds(p, s, card):
    """The words of a wait for the units of other cards than `card` (under LOCK), or None."""
    others = [(pid, c) for pid, c in unit_runs(p, s) if c is None or c != card]
    if not others:
        return None
    return ", ".join(f"{c or 'no card (an unreadable entry)'} (its Stage-6 run, pid {pid})" for pid, c in others)


def unit_moving(p) -> list:
    """The lands that can move main and run now (under LOCK): the live RUNNING entries of kind land,
    credit or bookkeeping, and the land hold, which a land's work keeps after its owner is gone."""
    live = sorted((pid, k) for pid, k in running_kinds(p).items() if k in ("land", "credit", "bookkeeping"))
    out = [f"{k} pid {pid}" for pid, k in live]
    if land_holding(p) and not any(k in ("land", "credit") for _pid, k in live):
        out.append("the land hold")
    return out


def land_unit_wait(p, s, card, name):
    """Why the queued land of ticket `name`, of card `card`, waits for a unit (under LOCK), or None."""
    if not s["RUN_LAND_UNIT"]:
        return None
    why = unit_holds(p, s, card)
    if why:
        return f"a run-plus-land unit of {why} stands"
    if is_light(name):
        runs = [f"{k} pid {pid}" for pid, k in sorted(running_kinds(p).items()) if k in ("run", "exclusive")]
        if runs:
            return f"a run runs on this host ({', '.join(runs)}), and a light land does not start beside a run"
    return None


def exclusive_ahead(p, owner=None, past=None):
    """Under LOCK: why a fast pass must wait for an exclusive run (one runs, BUSY is held exclusive —
    also by a command whose owner is gone — or one is the queue's next to pass), or None. With `owner`
    (a credit-ready land's card) an exclusive head does not stop it while a green hold of that card
    stands; the head's ticket is appended to `past`."""
    xs = exclusive_running(p)
    if xs:
        return f"an exclusive run runs (pid {xs[0]})"
    if busy_exclusive(p):
        return "BUSY is held exclusive (an exclusive run, also one whose owner is gone)"
    q = tickets(p["queue"])
    g = group(q, land_holding(p))
    if g and is_exclusive(g[0]):
        h = hold_now(p, CUR) if owner else None
        if h is not None and h["card"] and h["card"] == owner:
            if past is not None:
                past.append(g[0])
            return None
        return f"an exclusive run is the head of the queue ({g[0]})"
    return None


# ═══ THE PLACES ═══════════════════════════════════════════════════════════════════════════════
# While the engine says a venue is published for the run's repository, the head of the run order
# passes to the box or to this host's local place: `remote` — a box slot is free (fewer runs the queue
# let pass to the box still run than the box's slots: the engine's Stage-6 cap, or REMOTE_SLOTS when
# lower); `local` — no box slot is free, only when fewer than LOCAL_RUNS local runs still run and no
# land holds, the run then forced to this host. Rule 2 (h): THE PLACES ask the routing decision with
# the repo's REAL identity, and a KERNEL run is never forced local — with the box full it waits for a
# box slot. With no venue published, or a reader that fails, every run is local, LOCAL_RUNS at once.
def local_cap(s, published) -> int:
    return s["LOCAL_RUNS"] if published else max(1, s["LOCAL_RUNS"])


def venue_state(root, *, kernel, placement="auto"):
    """Where the engine would run this Stage-6 pass, read through the engine (rule 2 (b)):
    {"published", "token", "why", "slots", "box", "forced_local"}. published is True when the engine's
    own routing decision (remote_verify.venue_decision over the venue record, the checkout's consumer
    declaration, its repository and the sandbox carve-out) answers remote. Any failure: not published,
    token reader-failed."""
    try:
        from lib import init as engine_init, remote_verify as rv, venue as engine_venue
        from lib import git_env as _git_env
        common = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, env=_git_env._git_child_env(None))
        repo = (os.path.realpath(common.stdout.strip()) if common.returncode == 0 and common.stdout.strip()
                else None)
        with contextlib.redirect_stdout(sys.stderr):
            rec, note = engine_venue.routing_record()
            kw = dict(kind=rv.STAGE6_KIND, record=rec, record_note=note, full_suite=True,
                      sandbox=bool(rec) and rv.sandbox_repo(root))
            if not kernel:
                decl = engine_venue.consumer_declaration_of(root, engine_init.CONSUMER_OPS_CONTRACT)
                if decl.get("state") == "absent":      # the engine's own early answer (task._stage6_consumer_venue)
                    return {"published": False, "token": "consumer", "box": None, "slots": None,
                            "forced_local": False, "why": "the engine runs it here (consumer)"}
                kw.update(declaration=decl, repo_common_dir=repo, placement="auto")
            dec = rv.venue_decision(kernel=kernel, **kw)
            slots = rv.venue_stage6_max_concurrent(default=1) if dec.get("remote") else None
        if not dec.get("remote"):
            reason = str(dec.get("reason") or "no-venue")
            return {"published": False, "token": reason, "box": None, "slots": None, "forced_local": False,
                    "why": f"the engine runs it here ({reason}{': ' + str(dec.get('note')) if dec.get('note') else ''})"}
        box = (rec or {}).get("box")
        return {"published": True, "token": "venue", "box": box, "slots": int(slots),
                "forced_local": placement == "local",
                "why": f"a venue is published for this repository ({box}), {int(slots)} Stage-6 slot(s) by the engine"}
    except Exception as e:             # noqa: BLE001 — any failure: no venue for the queue
        return {"published": False, "token": "reader-failed", "box": None, "slots": None, "forced_local": False,
                "why": f"the venue reader failed ({type(e).__name__}: {e}); every run here, as with no venue"}


def box_slots(s, v) -> int:
    rs = str(s["REMOTE_SLOTS"]).strip()
    return v["slots"] if rs == "engine" else min(int(rs), v["slots"])


# ═══ THE WINDOW ═══════════════════════════════════════════════════════════════════════════════
# Every waiter samples the read set every SAMPLE s while it waits (each sample: the CPUs' cumulative
# busy and total time, so the mean between two samples is exact whatever the gap). The head's reading
# is the mean from the newest sample that is at least WINDOW s old and was taken after the last head's
# pass, to the latest sample. Rule 2 (i): with no PIN the set read is the CPUs the process may use.
PROC_STAT = "/proc/stat"


def snap(path=None) -> dict:
    out = {}
    with open(path or PROC_STAT, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("cpu") and len(line) > 3 and line[3].isdigit():
                a = line.split()
                n = int(a[0][3:])
                v = list(map(int, a[1:]))
                out[n] = (sum(v), v[3] + v[4])
    return out


class Samples:
    """The samples a waiter takes while it waits. Bounded: samples older than WINDOW and two SAMPLE
    intervals are dropped, all but the newest of them. A /proc/stat that cannot be read clears them,
    so no window is full on it."""

    def __init__(self):
        self.rows: list = []

    def take(self):
        now = time.time()
        try:
            self.rows.append((now, snap()))
        except (OSError, ValueError, IndexError):
            self.rows = []
        self.prune()

    def prune(self):
        s = cur()
        keep_from = time.time() - s["WINDOW"] - 2 * min(s["SAMPLE"], s["WINDOW"])
        old = [r for r in self.rows if r[0] < keep_from]
        self.rows = old[-1:] + [r for r in self.rows if r[0] >= keep_from]

    def due(self) -> bool:
        s = cur()
        return not self.rows or time.time() - self.rows[-1][0] >= min(s["SAMPLE"], s["WINDOW"])

    def mean(self, since, window, pin):
        """(mean busy percent, start of its span, seconds sampled since `since`); the mean is None while
        no sample at or after `since` lies `window` s before the latest one (the window is not full)."""
        rows = [r for r in self.rows if r[0] >= since]
        if not rows:
            return None, None, 0.0
        b = rows[-1]
        starts = [r for r in rows if r[0] <= b[0] - window]
        if not starts:
            return None, None, b[0] - rows[0][0]
        a = starts[-1]
        tot = sum(b[1][n][0] - a[1][n][0] for n in pin if n in a[1] and n in b[1])
        idle = sum(b[1][n][1] - a[1][n][1] for n in pin if n in a[1] and n in b[1])
        return round(100 * (1 - idle / max(1, tot)), 3), a[0], b[0] - rows[0][0]


def load1_now() -> str:
    try:
        value = os.getloadavg()[0]
    except OSError:
        return "-"
    return f"{value:.2f}" if math.isfinite(value) and value >= 0 else "-"


# ═══ THE PASS LOG ═════════════════════════════════════════════════════════════════════════════
# Rule 2 (e): every pass, every wait, every leave and every step is a row on the MAIN checkout's
# journal — not a file of the queue's own. A ticket's rows: `admission_wait` when it is filed (its
# class, its arrival, what it stands behind), then exactly ONE terminal row — `admission_pass` or
# `admission_left` (the reason). A fast pass, which files no ticket, writes its pass row only. What
# follows a pass is a step row (`admission_step`: sync, quick-first, hold, land-set, land-preview) of
# that pass. A pass row carries the source's pass-log fields and the FULL applied configuration, its
# hash and the queue revision; what the OS locks held at that instant is recorded as observed
# (rule 5). A row that cannot be written is said once and stops no pass.
WAIT, PASS, LEFT, STEP = "admission_wait", "admission_pass", "admission_left", "admission_step"
RESULT_TYPES = ("tests_passed", "tests_failed", "tests_cancelled")   # the Stage-6 result rows it stamps
_EMIT: list = [None]


def emit(etype, task, data, *, s=None, ticket=None, ts=None) -> "dict | None":
    """Append one queue row to the MAIN journal through the engine's journal writer; returns the row's
    {ts, sha} name. EVERY queue row carries the common context (rule 2 (e)): admission: engine, the
    queue revision, the full applied configuration and its hash, the owner's pid and the ticket. A
    failure is said once and stops nothing."""
    writer = _EMIT[0]
    if writer is None:
        return None
    s = s if s is not None else CUR
    data = {"admission": "engine", "revision": revision(), "config": s.get("_config"),
            "config_hash": s.get("_hash"), "pid": os.getpid(), "ticket": ticket, **data}
    ts = ts or iso(time.time())
    try:
        writer(etype, task, data, events_path=Path(_P[0]["main"]) / "events.jsonl", ts=ts)
    except Exception as e:             # noqa: BLE001 — a lost row never blocks the queue
        say_once(("emit", type(e).__name__), f"the queue's {etype} row was not written ({type(e).__name__}: {e}); "
                 "the queue goes on")
        return None
    return {"ts": ts, "sha": row_sha({"type": etype, "task_id": task, "ts": ts, "data": data})}


def observed(p) -> dict:
    """What the OS locks and entries hold at this instant (rule 5), as observed — never re-derived."""
    return {"running": {str(pid): kind for pid, kind in sorted(running_kinds(p).items())},
            "busy_held": busy_held(p), "busy_exclusive": busy_exclusive(p), "land_hold": land_holding(p)}


def log_pass(p, task, kind, *, s, limit=None, window=None, rule=None, place=None, ticket=None,
             busy=None, light=None, arrival=None, ts=None):
    """The pass row: the source's fields (pid, task, kind, limit, window, settings, rule, place,
    arrival, wait, runs-ahead, group (one land at a time: none), load1, busy, light reason), the full
    applied configuration, its hash, the queue revision and what was held."""
    now = time.time()
    ahead = None
    if ticket:
        try:
            arrival = int(ticket.split("-")[0]) / 1e9
        except ValueError:
            arrival = None
        if ticket_class(ticket) == "land":
            n = (read_json(Path(p["queue"]) / ticket) or {}).get("runs_ahead")
            ahead = n if type(n) is int and n >= 0 else None
    data = {"kind": kind, "limit": limit, "window": window,
            "settings": fmt_settings(s), "rule": rule, "place": place,
            "arrival": None if arrival is None else round(arrival, 3),
            "wait_s": None if arrival is None else round(max(0.0, now - arrival), 3),
            "runs_ahead": ahead, "group": None, "load1": load1_now(),
            "busy": None if busy is None else round(busy, 3), "light": light, "held": observed(p)}
    return emit(PASS, task, data, s=s, ticket=ticket, ts=ts)


def log_step(p, task, kind, outcome, secs, detail=None, row=None, ticket=None, s=None):
    """A step row of a pass (T-14196 / T-14197 call it): sync, quick-first, hold, land-set or
    land-preview, its outcome, seconds and detail; `row` names a journal row it read (ts, sha)."""
    data = {"kind": kind, "outcome": outcome, "secs": round(max(0.0, secs), 3), "detail": detail}
    if row:
        data["row"] = row
    return emit(STEP, task, data, s=s, ticket=ticket)


class PinFailed(Exception):
    """The admitted work cannot take its CPUs: the ticket leaves (pin-failed), exit 127."""


def commit_pass(p, fd, *, entry_kind, side, s, task, log_kind, state, ticket=None, stage6=False,
                journals=None, alone=False, **log_kw):
    """The pass, in the one order that leaves a ticket ONE terminal row (audit-pre F3): BUSY is held
    (`fd`) -> the process takes its CPUs -> its RUNNING entry -> the pass row, last (its writer never
    raises). A pin or an entry that fails releases BUSY and raises, so the caller's terminal row is
    `admission_left`. Call under LOCK."""
    ts = iso(time.time())
    try:
        pin_self(side, s)
    except OSError as e:
        _release(fd)
        raise PinFailed(f"cannot pin to the {side} CPUs {fmt_cpus(pins(s)[side == 'light'])}: {e}") from e
    try:
        register_running(p, entry_kind, alone=alone, side=side, task=task, stage6=stage6, journals=journals,
                         since_ts=ts)
    except OSError:
        _release(fd)
        raise
    state["passed"] = True
    state["pass"] = log_pass(p, task, log_kind, s=s, ticket=ticket, ts=ts, **log_kw) or {"ts": ts}
    return state["pass"]


def _release(fd) -> None:
    if fd is not None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


# ═══ THE RULE ═════════════════════════════════════════════════════════════════════════════════
# Each check of the head takes one of three rules, named on its pass row:
#   empty      nothing the queue let pass is held: the head passes when the mean of the read set over
#              the last EMPTY_SAMPLE s (at most WINDOW), every sample taken after the last pass, is at
#              most THRESHOLD; SPACING does not hold it.
#   land-tail  a run (not exclusive) while one land holds alone: it passes, when the queue's next
#              ticket with no land holding would be that run, under SPACING and the mean over WINDOW
#              at most LAND_TAIL_THRESHOLD. No land starts into any land's tail.
#   window     anything else held: a run or a land starts under SPACING when the mean of the read set
#              over the last WINDOW s is at most THRESHOLD and no land holds.
def rule_of(p, lh, kind, exclusive, skip=()):
    what = holds(p, skip)
    if not what:
        return "empty", [f"{k} pid {pid}" for pid, k in sorted(running_kinds(p).items()) if k in skip]
    if lh and kind == "run" and not exclusive and land_alone(p):
        return "land-tail", what
    return "window", what


# ═══ THE HEAD ═════════════════════════════════════════════════════════════════════════════════
# The first ticket (the head) makes the checks, and passes only when all of these hold (an at-once
# head: all but SPACING and the reading): no exclusive run runs and BUSY is not held exclusive; an
# exclusive head: no RUNNING entry is live AND no BUSY holder is left (rule 2 (g): the flock, never a
# pid entry); for a land, no credit-ready land runs and no other land holds; the last head's pass is
# SPACING s ago or more, except under the empty rule; and the reading of its rule, all of it sampled
# after that pass, is at most the rule's limit. The reading is taken outside the lock; the checks are
# made again, the rule taken again and the group recomputed (both must be the same) and the pass
# recorded, inside it. (Not ported: the release lock and gate, land groups, the ungated scan.)
class Refused(Exception):
    """The queue stops this work before it runs (a refusing recheck); `code` is the exit."""

    def __init__(self, code, why):
        super().__init__(why)
        self.code, self.why = code, why


def admit(p, kind, mark, *, task=None, log_kind="run", exclusive=False, info=None, recheck=None,
          land_cls=None, reclassify=None, venue=None, placed=None, fast=None, light=None, unit=None,
          kernel=False, state=None, carry=None):
    """Wait for this waiter's turn and for room, then pass. Returns (busy, land hold) descriptors: a
    flock on BUSY kept for the work (shared; exclusive with `exclusive`); a land takes the land hold
    shared at its pass, when no other land holds it. `info` is written into the ticket; `recheck` (a
    land, T-14196) is called by the head whose reading passed, just before its pass, with its class:
    a Refused ends the waiter with no work run. `land_cls`/`reclassify` (a land, T-14196) name and
    re-decide its class. `venue` -> venue_state() is read at each check and again under the lock at
    the pass (THE PLACES); `placed` is filled with the place the pass took. `fast` (class, check) is the
    fast path of a waiter AT_ONCE left out. `light` (reason, why) of a run classed run-light at its
    arrival. `unit` (worktree, card) of a card's Stage-6 run, which opens a unit at its pass. `state`
    (a dict) receives the ticket name and the wait row, for the caller's terminal row. `carry` () -> ns
    or None (a run, T-14273): the arrival its ticket keeps instead of now, asked under LOCK in the same
    hold that writes the wait row, so a second ticket of the card filed after it reads that row."""
    state = {} if state is None else state
    _mkdirs(p["queue"])
    s0 = cur(p["main"])
    with Locked(p["lock"]):
        ns = (carry() if carry else None) or time.time_ns()
        if land_cls is not None:
            me_name = land_ticket(ns, os.getpid(), land_cls, mark)
        else:
            me_name = run_ticket(ns, os.getpid(), mark, exclusive, bool(light))
        q_before = tickets(p["queue"])
        write_json(Path(p["queue"]) / me_name,
                   {"v": FORMAT, "cwd": os.getcwd(), "runs_ahead": 0, **(info or {}), "task": task,
                    **({"light": list(light)} if light else {})})
        q_now = tickets(p["queue"])
        ahead = q_now[:q_now.index(me_name)] if me_name in q_now else q_before
        wrow = emit(WAIT, task, {"class": ticket_class(me_name), "arrival": round(ns / 1e9, 3), "kind": log_kind,
                                 "behind": [{"ticket": t, "class": ticket_class(t), "task": ticket_task(p, t)}
                                            for t in ahead]},
                    s=s0, ticket=me_name)
        if wrow:
            data = read_json(Path(p["queue"]) / me_name) or {}
            data.update(wait_ts=wrow["ts"], wait_sha=wrow["sha"])
            write_json(Path(p["queue"]) / me_name, data)
    state.update(ticket=me_name, wait=wrow)
    me = Path(p["queue"]) / me_name
    pid0 = os.getpid()

    def light_now():
        """The run-light reason while this ticket's class is run-light — read from its name as it stands
        now, so a mark set later (`remark`) ends it (T-14266)."""
        return light[0] if light and ticket_class(me_name) == "run-light" else None

    def light_says():
        return f"; class run-light ({light[0]}: {light[1]})" if light_now() else ""
    u_main = p["main"] if unit else None

    def resync():
        """Under LOCK: this waiter's ticket as it stands now (a `remark` of any waiter may have renamed
        it) and, for a run or an ordinary land, the mark its name carries (T-14266)."""
        nonlocal me_name, me, mark
        now = own_ticket(p["queue"], ns, pid0)
        if now is None:
            return
        me_name, me = now, Path(p["queue"]) / now
        state["ticket"] = me_name
        if kind_mark(now)[0] == "run" or land_class(now) == "land":
            mark = kind_mark(now)[1] == "1"

    def drop():
        """Remove this waiter's ticket under whatever name it has now (called under LOCK)."""
        with contextlib.suppress(FileNotFoundError):
            os.unlink(Path(p["queue"]) / (own_ticket(p["queue"], ns, pid0) or me_name))

    def drop_locked():
        with Locked(p["lock"]):
            drop()
    state["drop"] = drop_locked

    def retitle(cls):
        nonlocal me_name, me
        with Locked(p["lock"]):
            resync()
            new = land_ticket(ns, pid0, cls, mark)
            if new == me_name:
                return
            try:
                os.rename(me, Path(p["queue"]) / new)
            except FileNotFoundError:
                write_json(Path(p["queue"]) / new, {"v": FORMAT, "cwd": os.getcwd(), "runs_ahead": 0,
                                                     **(info or {}), "task": task})
            me_name, me = new, Path(p["queue"]) / new
            state["ticket"] = me_name

    def pass_kind():
        if kind == "land" and land_cls is not None:
            return {"light": "light", "planning": "planning"}.get(land_class(me_name), "land-mark" if mark else "land")
        if light_now():
            return "run-light"
        return ("run-mark" if mark else "run") if log_kind in ("run", "run-mark") else log_kind

    samples, said = Samples(), {"key": None, "at": 0.0}
    skip = ("bookkeeping",) if kind == "land" else ()

    def nap(seconds, watch=False):
        """Sleep `seconds` in STEP steps, taking a sample whenever one is due; with `watch` wake when
        nothing is held any more, read at each sample (the empty host's decision comes within one
        SAMPLE of the last command's end)."""
        end = time.time() + seconds
        step = min(CUR["STEP"], CUR["SAMPLE"], CUR["WINDOW"])
        while time.time() < end:
            time.sleep(min(step, max(0.0, end - time.time())))
            if samples.due():
                samples.take()
                if watch:
                    with Locked(p["lock"]):
                        if not holds(p, skip):
                            return

    def wait_line(key, text):
        if said["key"] != key or time.time() - said["at"] >= CUR["POLL"]:
            say(text)
            said["key"], said["at"] = key, time.time()

    t0 = time.time()
    while True:
        s = cur(p["main"])
        if fast is not None and fast[0] in s["AT_ONCE"]:
            answer = fast[1]()
            if answer[0]:
                if placed is not None:
                    placed.update(fast=(fast[0], answer), ticket=me_name)
                say(f"AT_ONCE holds {fast[0]} again ({answer[1]}): it passes at once")
                return None, None
        v = venue() if venue is not None else None
        pub = bool(v and v["published"])
        if kernel and v is not None and v["token"] == "reader-failed":
            # audit-pre F1: a failed read is not a confirmed absence — a kernel run is never forced to
            # this host (rule 2 (h)), so it reads the venue again at its next check
            wait_line(f"venue-{v['why']}", f"wait: {v['why']}; a kernel run is never forced to this host, so it "
                      f"reads the venue again at its next check")
            nap(s["POLL"]); continue
        with Locked(p["lock"]):
            remark(p, s)
            resync()
            q = tickets(p["queue"])
            lh = land_holding(p)
            rule, what = rule_of(p, lh, kind, exclusive, skip)
            green = hold_now(p, s)
            qh = held_q(p, q, green, s)
            free = planning_free(me_name, s)
            u_wait = land_unit_wait(p, s, task, me_name) if kind == "land" and not free else None
            u_move = unit_moving(p) if unit and s["RUN_LAND_UNIT"] else []
            u_run = unit_holds(p, s, task) if unit and s["RUN_LAND_UNIT"] else None
            g_free = group(qh) if pub else []
            g = group(qh, lh, rule == "land-tail")
            pos = q.index(me_name) + 1 if me_name in q else 0
            prev, who = last_start(p)
            places = running_kinds(p)
        remote_n = sum(1 for k in places.values() if k == "remote")
        local_n = sum(1 for k in places.values() if k in ("run", "exclusive"))
        slots = box_slots(s, v) if pub else 0
        watch = rule != "empty"
        waited = round(time.time() - t0)
        load1 = load1_now()
        if (reclassify is not None and kind == "land" and not mark and land_class(me_name) == "land"):
            now_cls, lines = reclassify()
            if now_cls != "land":
                retitle(now_cls)
                say(f"now a {now_cls} land at its check; queued as {pass_kind()}")
                for line in lines:
                    say(line)
                continue
        since = time.time() - prev
        if green is not None and green["card"] != task and not free:
            wait_line(f"hold-{green['card']}-{green['set_at']}", f"wait: {hold_says(green, s)}; this {kind} of "
                      f"{task or 'no card'} waits ({waited} s, load1 {load1})")
            nap(s["POLL"]); continue
        if u_wait:
            wait_line(f"unit-{u_wait}", f"wait: {u_wait} (admission.run_land_unit); this {pass_kind()} land of "
                      f"{task or 'no card'} waits for the gap ({waited} s, load1 {load1})")
            nap(s["POLL"]); continue
        if u_run and me_name in g[:1] + g_free[:1]:
            wait_line(f"unit-run-{u_run}", f"wait: head of queue, a run-plus-land unit of {u_run} stands: one "
                      f"card's unit at a time, so this Stage-6 run of {task or 'no card'} waits for its end "
                      f"({waited} s, load1 {load1})")
            nap(s["POLL"], watch); continue
        if u_move and me_name in g[:1] + g_free[:1]:
            wait_line(f"drain-{','.join(u_move)}", f"wait: head of queue, a land that can move main runs "
                      f"({', '.join(u_move)}): a card's Stage-6 run starts only once it has ended ({waited} s, "
                      f"load1 {load1})")
            nap(s["POLL"], watch); continue
        # THE PLACES, the remote place: the head of the order the queue would pass with no land holding,
        # a free box slot: it passes at once, with no load reading and no SPACING, a land holding or not
        if pub and not exclusive and not v.get("forced_local") and g_free[:1] == [me_name] and remote_n < slots:
            fd = None
            with Locked(p["lock"]):
                remark(p, s)
                resync()
                q = tickets(p["queue"])
                held = running_kinds(p)
                confirmed = cur(p["main"])
                v_now = venue()
                h_now = hold_now(p, confirmed)
                if (group(held_q(p, q, h_now, confirmed)) == g_free and v_now["published"]
                        and (h_now is None or h_now["card"] == task)
                        and all(confirmed[k] == s[k] for k in ("REMOTE_SLOTS", "LOCAL_RUNS", "LIGHT_PIN", "ORDER"))
                        and not crossing(p, "run", confirmed) and not busy_exclusive(p)
                        and sum(1 for k in held.values() if k == "remote") < box_slots(confirmed, v_now)
                        and "exclusive" not in held.values()
                        and not (unit and confirmed["RUN_LAND_UNIT"]
                                 and (unit_moving(p) or unit_holds(p, confirmed, task)))):
                    fd = take_busy(p)
                if fd is not None:
                    count_run(p["queue"], q)
                    commit_pass(p, fd, entry_kind="remote", side="run", s=confirmed, task=task, log_kind="remote",
                                state=state, ticket=me_name, stage6=bool(unit),
                                journals=journals_of(u_main, unit[0]) if unit else None, place="remote",
                                light=light_now())
                    drop()
            if fd is None:
                say("wait: a remote pass did not hold under the lock; a new check")
                nap(min(1.0, s["POLL"])); continue
            if placed is not None:
                placed.update(place="remote", why=v_now["why"], append=False)
            say(f"remote place: box slot {remote_n + 1} of {slots} (REMOTE_SLOTS {s['REMOTE_SLOTS']}), passes at "
                f"once with no load reading and no spacing after {waited} s (load1 {load1}); {v_now['why']}{light_says()}")
            return fd, None
        # the local place: LOCAL_RUNS local runs at once, and while a venue is published none while a land
        # holds. Rule 2 (h): a KERNEL run never takes the local place while a venue is published — with
        # the box full it waits for a box slot.
        cap = local_cap(s, pub)
        if kernel and pub and not exclusive and g_free[:1] == [me_name]:
            wait_line(f"box-{remote_n}-{slots}", f"wait: head of queue, the box's {slots} slot(s) are taken "
                      f"({remote_n} remote run(s)); a kernel run is never forced to this host (SPEC-1032), so it "
                      f"waits for a box slot ({waited} s, load1 {load1})")
            nap(s["POLL"], watch); continue
        if venue is not None and not exclusive and g[:1] == [me_name] and (local_n >= cap or (pub and lh)):
            read = "" if cap == s["LOCAL_RUNS"] else f", read as {cap} with no venue published"
            why = (f"the local place is taken ({local_n} local run(s), LOCAL_RUNS {s['LOCAL_RUNS']:g}{read})"
                   if local_n >= cap else "a land holds, and the local place waits for it")
            where = (f"the box's {slots} slot(s) are taken ({remote_n} remote run(s))" if pub else
                     f"no venue published ({v['token']})")
            wait_line(f"local-{local_n}-{lh}", f"wait: head of queue, {where}; {why} ({waited} s, load1 {load1})")
            nap(s["POLL"], watch); continue
        if g[:1] != [me_name]:
            held_land = (("; a land holds, and lands pass one at a time" if kind == "land" else
                          "; a land holds, and no run starts beside it") if lh else "")
            wait_line(f"queue-{pos}-{len(q)}-{lh}", f"wait: queue {pos} of {len(q)}{held_land} ({waited} s, "
                      f"load1 {load1})")
            nap(s["POLL"], watch); continue
        if kind == "land" and lh:
            wait_line("land-held", f"wait: head of queue, a land holds, and lands pass one at a time "
                      f"({waited} s, load1 {load1})")
            nap(s["POLL"], watch); continue
        held = running_kinds(p)
        if exclusive and (held or busy_held(p)):
            names = ", ".join(f"{k} pid {pid}" for pid, k in sorted(held.items())) or (
                "no live owner, but BUSY is still held — the work of an owner that is gone")
            wait_line(f"excl-{names}", f"wait: head of queue, an exclusive run waits until no admitted work "
                      f"runs: {names} ({waited} s, load1 {load1})")
            nap(s["POLL"], watch); continue
        xs = exclusive_running(p)
        if not exclusive and xs:
            wait_line(f"xs-{xs[0]}", f"wait: head of queue, an exclusive run runs (pid {xs[0]}) ({waited} s, "
                      f"load1 {load1})")
            nap(s["POLL"], watch); continue
        side = "light" if kind == "land" and land_class(me_name) == "light" and not s["RUN_LAND_UNIT"] else "run"
        with Locked(p["lock"]):
            busy_x = busy_exclusive(p)
            cross = crossing(p, side, s)
        if busy_x:
            wait_line("busy-x", f"wait: head of queue, BUSY is held exclusive by a passed command ({waited} s, "
                      f"load1 {load1})")
            nap(s["POLL"], watch); continue
        if cross:
            wait_line(f"cross-{cross}", f"wait: head of queue, a command placed under another LIGHT_PIN runs on "
                      f"CPUs this pass takes: {', '.join(cross)} ({waited} s, load1 {load1})")
            nap(s["POLL"], watch); continue
        if kind == "land" and credit_running(p):
            wait_line("credit", f"wait: head of queue, a credit-ready land runs (pid {credit_running(p)[0]}) "
                      f"({waited} s, load1 {load1})")
            nap(s["POLL"], watch); continue
        if reclassify is not None and land_class(me_name) in ("light", "planning"):
            now_cls, lines = reclassify()
            if now_cls != land_class(me_name):
                was = land_class(me_name)
                retitle(now_cls)
                say(f"no longer a {was} land at its turn; queued as {pass_kind()}")
                for line in lines:
                    say(line)
                continue
        light_head = kind == "land" and land_class(me_name) == "light"
        at_once = not exclusive and class_in(me_name, s["AT_ONCE"]) in s["AT_ONCE"]
        if not at_once and rule != "empty" and since < s["SPACING"]:
            wait_line("spacing", f"wait: head of queue, last start {since:.0f} s ago ({who}), spacing "
                      f"{s['SPACING']:g} s ({waited} s, load1 {load1})")
            nap(max(1.0, s["SPACING"] - since), watch); continue
        sample = min(s["SAMPLE"], s["WINDOW"])
        limit = s["LAND_TAIL_THRESHOLD"] if rule == "land-tail" else s["THRESHOLD"]
        window = min(s["EMPTY_SAMPLE"], s["WINDOW"]) if rule == "empty" else s["WINDOW"]
        where = {"empty": ", nothing held", "land-tail": ", into a single land's tail", "window": ""}[rule]
        if rule == "empty" and what:
            where = f", nothing held but a bookkeeping land ({', '.join(what)}), which a land does not wait for"
        busy, start = None, None
        if at_once:
            limit, window = None, None
        elif window > 0:
            samples.take()
            busy, start, have = samples.mean(prev, window, read_set(s))
            if busy is None:
                wait_line(f"window-{rule}", f"wait: head of queue, {have:.0f} s of samples since the last pass, "
                          f"the window is {window:g} s{where} ({waited} s, load1 {load1})")
                nap(sample if rule == "empty" else min(s["POLL"], max(sample, window - have)), watch); continue
            if busy > limit:
                wait_line(f"busy-{rule}", f"wait: busy {busy:.0f}% > {limit:g}% over the last {window:g} s{where} "
                          f"({waited} s, load1 {load1})")
                nap(sample, watch); continue
        if recheck is not None:
            recheck(land_class(me_name))      # raises Refused: no work runs
        fd, land, moved, local_ok = None, None, None, True
        place_token = None if v is None else (
            f"local:{('exclusive' if exclusive else 'placement-local' if v.get('forced_local') else 'box-full') if pub else v['token']}")
        with Locked(p["lock"]):
            remark(p, s)
            resync()
            prev, _ = last_start(p)
            since = time.time() - prev
            q = tickets(p["queue"])
            held = running_kinds(p)
            confirmed = cur(p["main"])
            changed = [k for k in ("THRESHOLD", "WINDOW", "PIN", "SPACING", "RUNS_AHEAD", "EMPTY_SAMPLE",
                                   "LAND_TAIL_THRESHOLD", "REMOTE_SLOTS", "LOCAL_RUNS", "LIGHT_PIN", "ORDER", "AT_ONCE",
                                   "PLANNING_BRANCHES", "PLANNING_LANDS", "RUN_LAND_UNIT") if confirmed[k] != s[k]]
            lh = land_holding(p)
            now_rule, now_what = rule_of(p, lh, kind, exclusive, skip)
            moved = None if now_rule == rule else f"{rule} -> {now_rule}"
            placed_moved = None
            if venue is not None:
                v_pass = venue()
                pub_now = v_pass["published"]
                if kernel and v_pass["token"] == "reader-failed":
                    placed_moved = "the venue read failed at the pass"
                elif pub_now != pub:
                    placed_moved = f"venue {'published' if pub_now else 'gone'} since the check"
                elif (pub and not exclusive and not v.get("forced_local")
                      and sum(1 for k in held.values() if k == "remote") < box_slots(confirmed, v)):
                    placed_moved = "a box slot came free since the check"
            moved = moved or placed_moved
            local_ok = (venue is None or exclusive or (not (pub and lh) and not (kernel and pub) and sum(
                1 for k in held.values() if k in ("run", "exclusive")) < local_cap(confirmed, pub)))
            h_now = hold_now(p, confirmed)
            free = planning_free(me_name, confirmed)
            hold_ok = h_now is None or h_now["card"] == task or free
            cross = crossing(p, side, confirmed)
            unit_ok = not ((kind == "land" and not free and land_unit_wait(p, confirmed, task, me_name))
                           or (unit and confirmed["RUN_LAND_UNIT"] and (unit_moving(p) or unit_holds(p, confirmed, task))))
            if (((at_once and class_in(me_name, confirmed["AT_ONCE"]) in confirmed["AT_ONCE"]
                  and not placed_moved and "RUN_LAND_UNIT" not in changed)
                 or (not at_once and not changed and not moved))
                    and hold_ok and group(held_q(p, q, h_now, confirmed), lh, rule == "land-tail") == g
                    and (at_once or rule == "empty" or since >= s["SPACING"])
                    and (at_once or start is None or start >= prev)
                    and not (kind == "land" and credit_running(p)) and local_ok and not cross and unit_ok
                    and ((not held and not busy_held(p)) if exclusive else "exclusive" not in held.values())):
                fd = take_busy(p, exclusive)
            if fd is not None and kind == "land":
                land = try_flock(p["landhold"], fcntl.LOCK_SH) if not lh else None
                if land is None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                    fd = None
            if fd is not None:
                if kind == "run":
                    count_run(p["queue"], q)
                if not light_head:
                    tmp = Path(str(p["stamp"]) + f".tmp-{os.getpid()}")
                    tmp.write_text(f"{time.time():.3f} {os.getcwd()} {pass_kind()}\n", encoding="utf-8")
                    _group_writable(tmp, 0o664)
                    os.replace(tmp, p["stamp"])
                try:
                    commit_pass(p, fd, entry_kind="exclusive" if exclusive else kind, side=side, s=confirmed,
                                task=task, log_kind=pass_kind(), state=state, ticket=me_name, stage6=bool(unit),
                                journals=journals_of(u_main, unit[0]) if unit else None, alone=(kind == "land"),
                                limit=limit, window=window, rule=None if at_once else rule, place=place_token,
                                busy=busy, light=light_now())
                except BaseException:
                    _release(land)
                    raise
                drop()
                if placed is not None and kind == "land":
                    placed["cls"] = land_class(me_name)
        if fd is None:
            if cross:
                say(f"wait: a command placed under another LIGHT_PIN runs on CPUs this pass takes: {', '.join(cross)}; "
                    "a new check")
                nap(s["POLL"], watch)
            elif not unit_ok:
                say("wait: a run-plus-land unit opened, or a land that can move main passed, under the lock; a new check")
            elif at_once:
                say(f"wait: an at-once pass ({ticket_class(me_name)}) did not hold under the lock; a new check")
            elif changed:
                say(f"wait: the settings changed since the reading ({', '.join(changed)}); a new check")
            elif moved:
                say(f"wait: the rule changed since the reading ({moved}); a new check")
            elif not local_ok:
                say("wait: the local place was taken, or a land holds, under the lock; a new check")
            elif not hold_ok:
                say("wait: a green hold of another card stands under the lock; a new check")
            else:
                nap(min(1.0, s["POLL"]), watch)
            continue
        if at_once:
            what_ = "light land passes" if light_head else f"{ticket_class(me_name)} passes at once (AT_ONCE)"
            here = ""
            if v is not None:
                here = f"; place local ({v['why']}" + ("; placement local)" if pub else ")")
                if placed is not None:
                    placed.update(place="local", why=v["why"], append=pub)
            say(f"{what_}: no load reading, no spacing, after {waited} s (load1 {load1}){here}{light_says()}")
            return fd, land
        if rule == "empty":
            where = (f", nothing held but a bookkeeping land ({', '.join(now_what)}), which a land does not wait for"
                     if now_what else ", nothing held")
        gap = "none before" if prev == 0 else f"last start {since:.0f} s ago"
        alone = "; exclusive: nothing else runs, nothing passes while it runs" if exclusive else ""
        reading = (f"no reading (EMPTY_SAMPLE {s['EMPTY_SAMPLE']:g}){where}" if busy is None else
                   f"busy {busy:.0f}% <= {limit:g}% over the last {window:g} s{where}")
        here = ""
        if v is not None:
            stays = "an exclusive run stays here" if exclusive else f"the box's {slots} slot(s) are taken"
            here = f"; place local ({stays}; {v['why']}; placement local)" if pub else f"; place local ({v['why']})"
            if placed is not None:
                placed.update(place="local", why=v["why"], append=pub)
        say(f"{reading} after {waited} s (load1 {load1}); {gap}{alone}; rule {rule}{here}{light_says()}")
        return fd, land


# ═══ AT ONCE — the fast passes (the source's lock_only_plain, its release lock and gate not ported) ═══
# A bookkeeping land, a credit-ready land (both T-14196), a no-layer run and an own-tests check that
# AT_ONCE names start at once, with no ticket, no load reading and no busy check — only an exclusive
# run (it runs, BUSY is held exclusive, or one is the head) and a command placed under another
# LIGHT_PIN on the CPUs it takes hold them. Rule 2 (g): the run kinds take BUSY shared at the pass.
FAST = {"bookkeeping": "bookkeeping land", "credit": "credit-ready land", "no-layer": "no-layer run",
        "own-tests": "own-tests check"}


def fast_pass(p, kind, *, pin, task=None, ticket=None, recheck=None, state=None, busy=True, credit=None):
    """The fast pass of `kind` (no-layer / own-tests; a bookkeeping land with `busy` False — it holds no
    land, card T-0714; a credit-ready land with `credit`, the pin of its check, and `busy` False — its
    work holds the land hold instead): wait while an exclusive run is ahead; the pass row and the RUNNING
    entry under the lock; BUSY shared for the work when `busy`. Returns (busy fd, side, land
    hold fd), or None when after a wait the kind is no longer admitted (AT_ONCE leaves it out, or its own
    check no longer holds) and the caller queues it. `pin` own reads its side at each check: light while
    LIGHT_PIN is set, else run.
    A CREDIT-READY LAND (the source's lock_only_plain, T-14196) passes only while no green hold of
    another card stands and no other land that can move main runs (no live entry of kind land or
    credit, no land hold) and neither main nor its branch has moved since its check, all read under the
    lock in one step, and it takes the land hold there; else None, and it is queued. While a green hold
    of its own card stands it passes an exclusive head (rule `hold-owner`)."""
    state = {} if state is None else state
    waited = False
    while True:
        s = cur(p["main"])
        side = ("light" if s["LIGHT_PIN"] else "run") if pin == "own" else pin
        if waited and kind not in s["AT_ONCE"]:
            say(f"a {FAST.get(kind, kind)} after its wait, but AT_ONCE leaves it out: queued")
            return None
        if waited and recheck is not None:
            ok, why, again = recheck()
            if not ok:
                say(f"no longer a {FAST.get(kind, kind)} after its wait ({why})")
                return None
            credit = again if kind == "credit" else credit
            waited = False
        fd, land, moving, stale, past = None, None, [], None, []
        with Locked(p["lock"]):
            ahead = exclusive_ahead(p, owner=task if kind == "credit" else None, past=past)
            if not ahead and side:
                cross = crossing(p, side, s)
                if cross:
                    ahead = f"a command placed under another LIGHT_PIN runs on CPUs it takes: {', '.join(cross)}"
            if not ahead and kind == "credit":
                # a credit-ready land moves main: a green hold of another card holds it
                h = hold_now(p, s)
                if h is not None and h["card"] != task:
                    ahead = hold_says(h, s)
            if not ahead and kind == "credit":
                moving = [f"{k} pid {pid}" for pid, k in sorted(running_kinds(p).items()) if k in ("land", "credit")]
                if not moving and land_holding(p):
                    moving = ["a land that holds the land hold"]
                stale = None if moving else moved_since(credit)
                if not moving and not stale:
                    land = try_flock(p["landhold"], fcntl.LOCK_SH)
                    if land is None:
                        moving = ["a land that holds the land hold"]
            if not ahead and not moving and not stale:
                if busy:
                    fd = take_busy(p)
                    if fd is None:
                        ahead = "BUSY is held exclusive"
            if not ahead and not moving and not stale:
                if past:
                    say(f"the land of {task} passes ahead of the exclusive run at the head of the queue ({past[0]}): "
                        f"the green hold of {task} stands, and the exclusive waits for it to end")
                try:
                    commit_pass(p, fd, entry_kind=kind, side=side, s=s, task=task, log_kind=kind, state=state,
                                ticket=ticket, arrival=None if ticket else state.get("arrival"),
                                alone=(kind == "credit"), rule="hold-owner" if past else None)
                except BaseException:
                    _release(land)
                    raise
                if ticket:
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(Path(p["queue"]) / ticket)
        if moving or stale:
            say(f"not credit-ready: {'a land that can move main runs (' + ', '.join(moving) + ')' if moving else stale}")
            return None
        if not ahead:
            return fd, side, land
        say(f"wait: a {FAST.get(kind, kind)} passes at once, but {ahead}")
        time.sleep(s["POLL"])
        waited = True


# ═══ A NO-LAYER RUN and A LIGHT RUN — the engine's own decision (rule 2 (b), (o)) ═════════════
# A NO-LAYER RUN passes at once: a run (not exclusive) for which the engine's own decision of what it
# would execute runs NOTHING — no declared verify layer by the skip decision taken over the working
# tree (worktree._subject_scoping_skip_layers, with the engine's own exception after it: a layer whose
# `adapter.sources` holds a changed path runs) AND no test sweep (rule 2 (o): the sweep the engine
# runs where a test directory exists and no declared layer covers it). A LIGHT RUN (basis (a)) is a
# queued run whose every layer the engine runs is in admission.light_layers, at least one, AND no
# test sweep (the plan check residual, SPEC-1045 rule 2 (o)). Decided once, at its arrival. Any
# failure of a reading is not no-layer / not light, and its line says why.
def _git_cap(args, cwd, env=None, input=None):
    from lib import git_env as _git_env
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          env=_git_env._git_child_env(env), input=input)


def layers_run(worktree, base_ref="main", working_tree=True):
    """(the set of declared verify layers the engine runs for the changes of `worktree` against its
    merge-base with `base_ref`, why); (None, why) when that cannot be decided. With `working_tree` (a
    Stage-6 run) everything its working tree changes, committed or not, and the layers of its working
    yitc-ops.yaml; without it (a land, T-14196) the branch's commits and the layers of its COMMITTED
    yitc-ops.yaml — the source's two readings. A carrier that declares no runnable layer is the empty
    set — the engine runs no layer then (rule 2 (o))."""
    import yaml
    base = _git_cap(["merge-base", base_ref, "HEAD"], worktree)
    if base.returncode != 0 or not base.stdout.strip():
        return None, f"no merge-base with {base_ref}"
    if working_tree:
        try:
            ops_text = (Path(worktree) / "yitc-ops.yaml").read_text(encoding="utf-8")
        except FileNotFoundError:
            return set(), "the checkout has no yitc-ops.yaml: no verify layer"
        except OSError as e:
            return None, f"the checkout's yitc-ops.yaml is unreadable ({e})"
    else:
        listed = _git_cap(["ls-tree", "--name-only", "HEAD", "--", "yitc-ops.yaml"], worktree)
        if listed.returncode != 0:
            return None, f"the branch's tree cannot be read ({(listed.stderr or '').strip()[:200]})"
        if not listed.stdout.strip():
            return set(), "the branch has no yitc-ops.yaml: no verify layer"
        shown = _git_cap(["show", "HEAD:yitc-ops.yaml"], worktree)
        if shown.returncode != 0:
            return None, f"the branch's yitc-ops.yaml is unreadable ({(shown.stderr or '').strip()[:200]})"
        ops_text = shown.stdout
    try:
        doc = yaml.safe_load(ops_text) or {}
    except yaml.YAMLError as e:
        return None, f"the checkout's yitc-ops.yaml does not parse ({type(e).__name__})"
    ver = doc.get("verify") if isinstance(doc, dict) else None
    layers = ver.get("layers") if isinstance(ver, dict) else None
    if not isinstance(layers, list):
        return set(), "the checkout declares no verify layers"
    runnable = {str(ly.get("layer")) for ly in layers if isinstance(ly, dict) and not isinstance(ly.get("waiver"), dict)
                and str(ly.get("command") or "").strip()}
    if not runnable:
        return set(), "the checkout declares no runnable verify layer"
    from lib import worktree as engine_worktree   # the engine's own skip decision, never a copy of it
    facts: dict = {}
    with contextlib.redirect_stdout(sys.stderr):
        skip = set(engine_worktree._subject_scoping_skip_layers(Path(worktree), layers, base.stdout.strip(), _git_cap,
                                                                working_tree=working_tree, facts=facts) or ())
    changed = [str(x) for x in (facts.get("paths") or ())]
    for ly in layers:
        adapter = ly.get("adapter") if isinstance(ly, dict) else None
        if adapter is None or str(ly.get("layer")) not in skip:
            continue
        sources = adapter.get("sources") if isinstance(adapter, dict) else None
        if not isinstance(sources, list):
            skip.discard(str(ly.get("layer")))
            continue
        tops = [str(x).rstrip("/") for x in sources if str(x).strip()]
        if any(c == t or c.startswith(t + "/") for c in changed for t in tops):
            skip.discard(str(ly.get("layer")))
    left = runnable - skip
    return left, (f"layer(s) {', '.join(sorted(left))} run for its changes" if left else
                  "no verify layer runs for its changes")


def verify_decision(worktree, sweep):
    """(layers, sweep, why) — the engine's whole decision of what this run executes (rule 2 (o)):
    `layers` as layers_run answers it (None: undecided), `sweep` whether the engine's test sweep runs
    (the caller's in-process answer: a test directory exists and no declared layer covers it)."""
    try:
        left, why = layers_run(worktree)
    except Exception as e:             # noqa: BLE001 — any failure: undecided
        return None, sweep, f"the no-layer check failed ({type(e).__name__}: {e})"
    if sweep:
        why = f"{why}; the test sweep runs"
    return left, sweep, why


def no_layer_run(decision) -> "tuple[bool, str]":
    left, sweep, why = decision
    return (left is not None and not left and not sweep), why


def run_light(decision, s, *, mark, exclusive, full, eligible=None):
    """(reason, why) of a run classed run-light at its arrival: reason `a` when the engine runs at
    least one layer, every one of them in admission.light_layers, and no test sweep (rule 2 (o)); else
    `b` when verify.post_sync_set_first is on, the form is no full reading and `eligible()` — the
    engine's ONE post-sync predicate, its part that holds before the merge (rule 2 (b);
    worktree_lifecycle._post_sync_premise) — admits the card: a prediction for its order only, the
    admission still syncs it and takes the quick step (T-14197). A marked or an exclusive run is never
    classed; any failure of a reading is not light, and says why."""
    if exclusive:
        return None, "an exclusive run is never a run-light"
    if mark:
        return None, "a marked run stays run-mark"
    left, sweep, why = decision
    light_set = set(s["LIGHT_LAYERS"])
    if left is None:
        a = f"(a) {why}"
    elif not left:
        a = "(a) no verify layer runs for its changes"
    elif sweep:
        a = "(a) the test sweep runs beside its layers: not light (rule 2 (o))"
    elif left <= light_set:
        return "a", f"only layer(s) {', '.join(sorted(left))} of admission.light_layers run for its changes"
    else:
        a = f"(a) layer(s) {', '.join(sorted(left - light_set))} outside admission.light_layers run for its changes"
    if not s.get("QUICK_FIRST"):
        return None, f"{a}; (b) not read: verify.post_sync_set_first off"
    if full:
        return None, f"{a}; (b) not read: a full reading"
    if eligible is None:
        return None, f"{a}; (b) not read: not a card's Stage-6 run"
    try:
        ok, why_b = eligible()
    except Exception as e:             # noqa: BLE001 — any failure: not light by (b)
        return None, f"{a}; (b) the eligibility check failed ({type(e).__name__}: {e})"
    if ok:
        return "b", f"eligible for the post-sync proof at its admission ({why_b})"
    return None, f"{a}; (b) not eligible: {why_b}"


def queue_jump(main, task) -> bool:
    """The card's live queue-jump mark, read by the engine's own reader; anything unclear reads
    unmarked."""
    if not task:
        return False
    try:
        from lib import worktree as engine_worktree
        return bool(engine_worktree._land_queue_jump_reason(Path(main), f"task/{task}"))
    except Exception:                  # noqa: BLE001
        return False


# ═══ THE PINNED SET — the admitted process pins itself (its children inherit) ═════════════════
def pin_self(side, s) -> None:
    """Pin this process to the CPUs of `side` under `s`; an empty set pins nothing — no affinity call
    (rule 2 (i)). A pinning that fails raises OSError (the caller's exit 127)."""
    cpus = pins(s)[side == "light"] if side else frozenset()
    if cpus:
        os.sched_setaffinity(0, cpus)


# ═══ THE ADMISSION STEPS AND THE GREEN HOLD — the run side (T-14197) ══════════════════════════
# When the queue has admitted a card's Stage-6 run, before its command (here: before the temporary
# activation of the card's proposed specs, so its snapshot is taken after the sync — rule 2 (a)), under
# the settings of the pass:
# Both verify: switches act only once the project declares verify.post_sync_set (SPEC-0152 rule 16).
#   verify.sync_at_stage6_admission on: the engine's own `worktree sync --task <card>` merges main into
#     the card's worktree — the verb itself, run from the main checkout, its output passed on, its
#     process group killed past SYNC_BOUND (a BUDGET key: it stops started work). Not clean (a conflict,
#     a failure, the bound): no run, exit 5. The verb's own post-sync proof, its `worktree_synced`
#     carrier and the land's reading of it are untouched (rule 2 (d)); the steps read the proof's
#     outcome from THIS child's own output only, never from a row a concurrent hand sync of the same
#     card could have written. The child inherits the BUSY descriptor this run holds (THE ENTRY's
#     hand-down), so the repo stays busy while it lives, also when its parent is gone; HELD_ENV only
#     stops it taking BUSY a second time.
#   the land's preview (rule 2 (m)): the land's own predicates that need no run are asked and what each
#     would say is ONE report-only `land-preview` step row; nothing is stopped.
#   verify.post_sync_set_first on: if the sync's proof RAN the set, FAILED stops the run (exit 6) and
#     PASSED ends it (exit 0, the green hold set) only when the card's prior green run already covers
#     SPEC-1038 Closure-time coverage (task close's own check) — else the full run follows; if no set
#     ran, the quick set runs ONCE as a screen: RED stops the run (exit 6), anything else starts the full
#     run, and the screen is never a proof. A full reading (--exclusive, --full, --whole) takes no quick
#     step and never ends early.
# After a green full run: the land's credit answer as a `land-preview` step row, then the green hold
# (set_hold — set while this process still holds its place, before its RUNNING entry goes).
# Adaptations (the card's analysis): the source's record_quick row and its quick path before a ticket
# are not ported (the engine's proof rides its own carrier; the steps run only after a pass); the
# exclusive run's release gate hand-down is the BUSY hand-down (no gate, rule 2).
SYNC_STOPPED = 5    # the sync at a run's admission did not end clean; no run (a conflict: the card's next run keeps its place)
QUICK_STOPPED = 6   # the quick step ended RED; no full run, its place released
SIGNAL_GRACE = 5.0  # s a child of an admission step is given after a signal passed on, at the least
HELD_ENV = "YITC_ADMITTED_BUSY_HELD"   # set on the sync child: BUSY is already held for it (handed down)
REEXEC_ENV = "YITC_ADMITTED_REEXEC"    # set on this process's own re-exec: the pass it holds, its sync (T-14252)
_PROOF_LINE = re.compile(r"^\s*POST-SYNC PROOF: (passed|FAILED|not eligible|not needed)\b")
_PROOF_WORD = {"passed": "passed", "FAILED": "failed", "not eligible": "ineligible", "not needed": "not-needed"}
_ADMITTED: list = [None]   # the pass record while this process runs admitted (THE ENTRY sets it)


def admitted():
    """The pass record of this process's admitted Stage-6 run or own-tests check, else None."""
    return _ADMITTED[0]


def engine_argv() -> list:
    """The engine's own CLI, as this process runs it."""
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "yitc-v2")]


_RESUMED: list = [None]   # the sync record a re-exec of this process carried over (T-14252)


def engine_head(root=None):
    """The commit the engine checkout this process runs from (`root`, default its own) stands on, or
    None when it is no git checkout or the read fails."""
    r = _git_cap(["rev-parse", "HEAD"], root or Path(__file__).resolve().parents[2])
    return ((r.stdout or "").strip() or None) if r.returncode == 0 else None


def resumed(main, task, form):
    """T-14252 — the pass this process carried over its own engine re-exec, else None. The marker is
    taken out of the environment at once, so no child inherits it; it counts only for the same pid,
    card and run form and while this process's RUNNING entry still carries the marker's one-time token
    (`pass_token_holds`, the land re-exec's carrier — consumed here); only the descriptors still open in
    this process are kept."""
    raw = os.environ.pop(REEXEC_ENV, None)
    try:
        m = json.loads(raw) if raw else None
    except ValueError:
        return None
    if (not isinstance(m, dict) or m.get("pid") != os.getpid() or m.get("task") != task or form != "run"
            or not pass_token_holds(main, os.getpid(), m.get("token"))):
        return None
    fds = []
    for fd in m.get("fds") or ():
        with contextlib.suppress(OSError, TypeError):
            os.fstat(fd)
            fds.append(fd)
    return {"record": m.get("record") or {}, "fds": fds, "sync": m.get("sync")}


def reexec_on_engine_change(p, s, card, wt, r, argv=None) -> None:
    """T-14252 — after a clean sync at admission: when the sync moved the engine this process runs (its
    checkout IS the synced worktree `wt`) and the commits between the head it started on and the head
    now touch the engine's own directory, write one `engine-reexec` step row and re-execute this command
    in place (same pid, arguments, environment, CPUs and priority), handing over the BUSY descriptors,
    the pass record and the sync record `r` — so the re-executed process neither queues nor syncs again.
    Anything else, or an exec that fails, returns: the run goes on on the code it started with.
    `argv` replaces the re-exec command (the test seam)."""
    rec = _ADMITTED[0] or {}
    start, here = rec.get("engine_head"), Path(__file__).resolve().parents[1]
    root = here.parent
    if not start or r.get("outcome") != "merged" or Path(wt).resolve() != root:
        return
    now = engine_head(root)
    if not now or now == start:
        return
    d = _git_cap(["diff", "--name-only", start, now, "--", here.name], root)
    if d.returncode != 0:
        say(f"the engine change under {card}'s sync could not be read ({(d.stderr or '').strip()[:200]}); the "
            "run goes on on the engine code it started with")
        return
    changed = [x for x in (d.stdout or "").split("\n") if x]
    if not changed:
        return
    log_step(p, card, "engine-reexec", "reexec", 0.0,
             {"from": start, "to": now, "changed": len(changed), "paths": changed[:20]}, s=s)
    say(f"the sync of {card} moved the engine code this run started on ({len(changed)} path(s) under "
        f"{here.name}/, {start[:12]} -> {now[:12]}): re-executing on the current engine, keeping its pass")
    marker = {"pid": os.getpid(), "task": card, "fds": list(_INHERIT), "sync": r, "token": pass_token(p["main"]),
              "record": {k: rec.get(k) for k in ("pass_ts", "pass_sha", "kind", "place")}}
    cmd = list(argv) if argv else [sys.executable, *sys.orig_argv[1:]]
    with contextlib.suppress(Exception):
        sys.stdout.flush()
        sys.stderr.flush()
    try:
        os.execve(cmd[0], cmd, {**os.environ, REEXEC_ENV: json.dumps(marker, default=str)})
    except OSError as e:
        say(f"the re-exec of {card}'s run failed ({e}); the run goes on on the engine code it started with")


def reap(child, within) -> None:
    """Wait for `child` (the leader of its own process group) at most `within` s, then kill its group and
    wait for it: no wait without bound while a place is held."""
    try:
        child.wait(timeout=max(0.0, within))
        return
    except subprocess.TimeoutExpired:
        pass
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(child.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        child.kill()
    child.wait()


def proof_of(lines):
    """The post-sync proof outcome a sync child printed (its LAST proof line): passed | failed |
    ineligible | not-needed, or None when it printed none (no set declared, a no-op sync)."""
    out = None
    for line in lines or ():
        m = _PROOF_LINE.match(line)
        if m:
            out = _PROOF_WORD[m.group(1)]
    return out


def sync_step(main, wt, card, bound, argv=None) -> dict:
    """`<engine> -C <main> worktree sync --task <card>` (`argv` replaces `<engine>` — the test seam), its
    output passed on to stderr and kept, its process group killed past `bound` s; a signal to this
    process is passed to that group and this process exits 128+signal once it has ended. Returns
    {ok, outcome, secs, detail, proof}: ok with outcome `current` (HEAD unchanged) or `merged`; else
    `conflict` (the paths git leaves unmerged) or `failed` (the bound, the start failure or the verb's
    last line). `proof` is proof_of() over this child's own output."""
    head = list(argv) if argv else engine_argv()
    cmd = [*head, "-C", str(main), "worktree", "sync", "--task", card]
    before = (_git_cap(["rev-parse", "HEAD"], wt).stdout or "").strip()
    t0, box, lines = time.time(), {"child": None}, []
    env = {**os.environ, HELD_ENV: "1"}

    def forward(signum, _f):
        if box["child"] is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(box["child"].pid, signum)
            reap(box["child"], max(SIGNAL_GRACE, t0 + bound - time.time()))
        raise SystemExit(128 + signum)
    old = {}
    for signo in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        with contextlib.suppress(ValueError, OSError):
            old[signo] = signal.signal(signo, forward)
    try:
        try:
            box["child"] = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                            errors="replace", start_new_session=True, env=env)
        except (OSError, subprocess.SubprocessError) as e:
            return {"ok": False, "outcome": "failed", "secs": time.time() - t0,
                    "detail": f"not started: {type(e).__name__}: {e}", "proof": None}
        import threading

        def pump():
            for line in box["child"].stdout:
                print(line, end="", file=sys.stderr, flush=True)
                lines.append(line.rstrip("\n"))
        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        try:
            code = box["child"].wait(timeout=bound)
        except subprocess.TimeoutExpired:
            reap(box["child"], 0)
            reader.join(5)
            return {"ok": False, "outcome": "failed", "secs": time.time() - t0,
                    "detail": f"past SYNC_BOUND {bound:g} s; killed", "proof": None}
        reader.join(5)
        if reader.is_alive():
            # its output was not read whole (a process it left holds the pipe, or the pass-on blocks): the
            # proof line may be among what was not read, so the sync is not clean (fail-closed)
            return {"ok": False, "outcome": "failed", "secs": time.time() - t0,
                    "detail": f"exit {code}, but its output could not be read whole", "proof": None}
    finally:
        for signo, h in old.items():
            with contextlib.suppress(ValueError, OSError):
                signal.signal(signo, h if h is not None else signal.SIG_DFL)
    secs = time.time() - t0
    proof = proof_of(lines)
    if code == 0:
        after = (_git_cap(["rev-parse", "HEAD"], wt).stdout or "").strip()
        return {"ok": True, "outcome": "current" if after == before else "merged", "secs": secs,
                "detail": after[:12] or None, "proof": proof}
    unmerged = [x for x in (_git_cap(["diff", "--name-only", "--diff-filter=U"], wt).stdout or "").split("\n") if x]
    if unmerged:
        return {"ok": False, "outcome": "conflict", "secs": secs, "detail": ",".join(unmerged), "proof": proof}
    said = next((x for x in reversed(lines) if x.strip()), "")
    return {"ok": False, "outcome": "failed", "secs": secs,
            "detail": f"exit {code}" + (f": {said[-200:]}" if said else ""), "proof": proof}


def _asked(name, fn):
    """One predicate's answer for a step row: {check, says, detail}; an exception reads `unknown`."""
    try:
        refused, detail = fn()
    except Exception as e:             # noqa: BLE001 — a preview never stops a run
        return {"check": name, "says": "unknown", "detail": f"{type(e).__name__}: {e}"[:300]}
    out = {"check": name, "says": "refuses" if refused else "admits",
           "detail": (str(detail)[:600] if detail else None)}
    if isinstance(detail, dict) and isinstance(detail.get("request"), dict):
        out["request"] = detail["request"]   # T-14272: the FORECAST's judged inputs, whole (the land compares)
    return out


def preview_step(p, s, card, checks) -> list:
    """Rule 2 (m): ask each of the land's own predicates `checks` [(name, fn -> (refused, detail))] and
    write ONE report-only `land-preview` step row of what each would say; never stops the run."""
    t0 = time.time()
    answers = [_asked(name, fn) for name, fn in (checks or ())]
    refusing = [a["check"] for a in answers if a["says"] == "refuses"]
    log_step(p, card, "land-preview", "refuses" if refusing else "admits", time.time() - t0, answers, s=s)
    if refusing:
        say(f"land preview for {card} (report-only — the run goes on): the land would refuse on "
            f"{', '.join(refusing)}")
    return answers


def admission_steps(p, s, *, card, wt, forced, sync, screen, covered, preview, has_set):
    """THE ADMISSION STEPS of card `card`'s admitted Stage-6 run, after its pass and before its command.
    `sync()` -> sync_step's record; `screen()` -> (word, detail), word green | red | other; `covered()` ->
    whether the card's prior green run covers Closure; `preview` the land predicates of preview_step;
    `has_set` whether the project declares a quick set. Returns None (the full run goes on) or the exit
    code: SYNC_STOPPED, QUICK_STOPPED, or 0 when the sync's proof ended the run."""
    proof = None
    if s["SYNC_IN_RUN"] and has_set and _RESUMED[0]:
        proof = _RESUMED[0].get("proof")   # T-14252: the sync this process ran before its re-exec
    elif s["SYNC_IN_RUN"] and has_set:   # both verify: switches act only once a quick set is declared
        r = sync()
        log_step(p, card, "sync", r["outcome"], r["secs"], r["detail"], s=s)
        if not r["ok"]:
            what = f"conflicts on {str(r['detail']).replace(',', ', ')}" if r["outcome"] == "conflict" else r["detail"]
            kept = ("its next run keeps this ticket's place" if r["outcome"] == "conflict" else "its place released")
            say(f"the sync of {card} at its admission did not end clean ({what}): no run, {kept}; a "
                "merge left open is resolved with `worktree sync --resolved` and, as authored content, takes "
                f"audit-post before the next run (exit {SYNC_STOPPED})")
            return SYNC_STOPPED
        proof = r.get("proof")
        say(f"the sync of {card} at its admission: {r['outcome']} ({r['secs']:.1f} s)"
            + (f"; its post-sync proof {proof}" if proof else ""))
        reexec_on_engine_change(p, s, card, wt, r)   # T-14252: returns unless the engine moved
    preview_step(p, s, card, preview)
    if forced:
        say(f"a full reading of {card}: no quick step, the full run goes on")
        return None
    if not s["QUICK_FIRST"]:
        return None
    if proof == "failed":
        log_step(p, card, "quick-first", "red", 0.0, "sync-proof", s=s)
        say(f"no full run of {card}: the post-sync proof of its sync ended RED; its place released "
            f"(exit {QUICK_STOPPED})")
        return QUICK_STOPPED
    if proof == "passed":
        try:
            ok = bool(covered())
        except Exception:              # noqa: BLE001 — undecided: the full run follows
            ok = False
        if ok:
            log_step(p, card, "quick-first", "green", 0.0, "sync-proof:closure-covered", s=s)
            set_hold(p, card, wt, s)
            say(f"the post-sync proof of {card} passed and its prior green run covers Closure: no full run "
                "(the land credits the proof, SPEC-0065 §Bound)")
            return 0
        log_step(p, card, "quick-first", "pass", 0.0, "sync-proof:closure-not-covered", s=s)
        say(f"the post-sync proof of {card} passed, but its prior green run does not cover Closure "
            "(SPEC-1038): the full run goes on")
        return None
    if not has_set:
        return None
    t0 = time.time()
    try:
        word, detail = screen()
    except Exception as e:             # noqa: BLE001 — a screen that cannot run proves nothing either way
        word, detail = "other", f"{type(e).__name__}: {e}"
    log_step(p, card, "quick-first", word, time.time() - t0, (str(detail)[:300] if detail else None) or "screen", s=s)
    if word == "red":
        say(f"no full run of {card}: its quick set ended RED; its place released (exit {QUICK_STOPPED})")
        return QUICK_STOPPED
    say(f"the quick set of {card} ({word}; a screen, never a proof): the full run goes on")
    return None


def after_run(p, s, card, wt, credit) -> str:
    """After a green full run of card `card` (still admitted): the land's credit answer as a report-only
    `land-preview` step row, then the green hold. Returns set_hold's outcome."""
    t0 = time.time()
    answer = _asked("credit", credit)
    log_step(p, card, "land-preview", "credit-answer", time.time() - t0, [answer], s=s)
    return set_hold(p, card, wt, s)


@contextlib.contextmanager
def hand_set_busy(main):
    """While switched on, a set run outside an admitted run (a hand `worktree sync --task`'s proof)
    holds BUSY shared like any short on-host check, so an exclusive run excludes it (rule 2 (d)): waits
    while BUSY is held exclusive, at most QUICK_LOCK_BOUND s. Yields `off` (switched off), `held` (a
    child of an admitted run: BUSY already handed down), `busy` (taken), None (the bound passed), or
    `unreadable` (the switch or the queue's state cannot be read). On None and `unreadable` the caller
    runs no set (fail-closed: an unreadable switch never reads as off)."""
    if os.environ.get(HELD_ENV) == "1":
        yield "held"
        return
    try:
        sw = switch(main)
    except Exception as e:             # noqa: BLE001 — unreadable: no set runs
        say(f"the admission switch cannot be read ({type(e).__name__}: {e}); no set runs")
        yield "unreadable"
        return
    if not sw.get("on"):
        yield "off"
        return
    fd = None
    try:
        p = paths(main)
        ensure(p)
        s = settings(main)
        deadline, said = time.time() + float(s["QUICK_LOCK_BOUND"]), False
        while True:
            fd = take_busy(p)
            if fd is not None or time.time() >= deadline:
                break
            if not said:
                say("wait: BUSY is held exclusive (an exclusive run); this hand sync's set run waits for it")
                said = True
            time.sleep(max(0.05, min(float(s["POLL"]), max(0.0, deadline - time.time()))))
    except Exception as e:             # noqa: BLE001 — unreadable: no set runs
        _release(fd)
        say(f"the queue's state cannot be read ({type(e).__name__}: {e}); no set runs")
        yield "unreadable"
        return
    try:
        yield "busy" if fd is not None else None
    finally:
        _release(fd)


# ═══ THE ENTRY — `task test --run` / `--own` enter the queue FIRST (rule 2 (a)) ═══════════════
# Read by the caller once, at its start (rule 2 (j)): `switch(main)`. Switched off, the caller runs
# its own code and nothing here is touched. Switched on, `task_test_entry` is entered before the
# temporary activation of the card's proposed specs and before remote_verify.route: it files the
# ticket (or takes its fast pass), waits, passes, holds BUSY for the work and its children, pins the
# process, and yields the pass record the Stage-6 result rows are stamped with.
def switch(main) -> dict:
    """THE SWITCH (SPEC-1045 rule 3), read once: the project's admission.mode over the MAIN checkout's
    yitc-ops.yaml and the machine VETO. An unresolvable main checkout reads off, said."""
    if main is None:
        return {"on": False, "mode": "off", "why": "the main checkout could not be resolved; the queue is off"}
    from lib import machine_settings as ms
    rec = ms.admission_from_main(main)
    rec["why"] = (f"admission.mode {rec['mode']} ({rec['mode_source']}), {ms.ADMISSION_VETO} {rec['veto']} "
                  f"({rec['veto_source']})")
    return rec


def stamp(record) -> dict:
    """The fields every Stage-6 result row carries while switched on (rule 2 (e))."""
    return {"admission": "engine", "admission_revision": record.get("revision"),
            "admission_config_hash": record.get("config_hash"), "admission_pass_ts": record.get("pass_ts")}


def stamping(writer, record, types=RESULT_TYPES):
    """`writer` with the rows of `types` stamped by `record`: the Stage-6 result rows (RESULT_TYPES) for
    a run; `land_completed` for a land (T-14196) — rule 2 (e)."""
    def _write(etype, tid, data=None, *args, **kwargs):
        if etype in types and isinstance(data, dict):
            data = {**data, **stamp(record)}
        return writer(etype, tid, data, *args, **kwargs)
    return _write


@contextlib.contextmanager
def _waiting_signals(on_signal):
    """While a waiter waits, SIGTERM / SIGINT / SIGHUP end it with 128+signal (the source's held-form
    exit), its ticket dropped and its terminal row written by the caller; the prior dispositions are
    given back at the pass."""
    prior = {}

    def _handler(signo, _frame):
        on_signal(signo)
        raise SystemExit(128 + signo)
    try:
        for name in ("SIGTERM", "SIGINT", "SIGHUP"):
            signo = getattr(signal, name)
            try:
                if signal.getsignal(signo) == signal.SIG_IGN:
                    continue
                prior[signo] = signal.signal(signo, _handler)
            except (ValueError, OSError):
                pass
        yield
    finally:
        for signo, h in prior.items():
            with contextlib.suppress(ValueError, OSError):
                signal.signal(signo, h if h is not None else signal.SIG_DFL)


@contextlib.contextmanager
def task_test_entry(*, main, root, task, form, kernel, append_event, sweep=False, exclusive=False,
                    full=False, args=None, eligible=None):
    """The queue's entry for `task test` (`form` "run" or "own"), switched on. Yields the pass record
    {revision, config_hash, pass_ts, kind, place}; at exit the RUNNING entry goes and the descriptors
    this process holds are closed (its children keep theirs)."""
    p = paths(main)
    try:
        ensure(p)
    except OSError as e:
        say(f"the queue's state directory {p['dir']} cannot be written ({e}); the run does not start")
        raise SystemExit(1)
    _P[0], _MAIN[0], _EMIT[0] = p, Path(main), append_event
    s = cur(p["main"])
    state: dict = {"arrival": time.time()}
    fds: list = []
    record = {"revision": revision(), "config_hash": s["_hash"]}
    try:
        record["engine_head"] = engine_head()   # T-14252: the engine code this process started on
    except Exception:                  # noqa: BLE001 — unreadable: this run never re-executes
        record["engine_head"] = None
    again = resumed(main, task, form)
    _RESUMED[0] = again["sync"] if again else None

    def _left(reason, detail=None):
        if not state.get("passed") and not state.get("left"):
            state["left"] = True
            if state.get("drop"):
                state["drop"]()
            emit(LEFT, task, {"reason": reason, "detail": detail}, ticket=state.get("ticket"))

    side, kind, nice = "run", None, None
    try:
        with _waiting_signals(lambda signo: _left("signal", signal.Signals(signo).name)):
            if again:
                # T-14252: this process re-executed itself after its sync moved the engine — the pass
                # it took before the exec stands (its BUSY descriptors, its RUNNING entry, same pid)
                fds.extend(again["fds"])
                state["passed"] = True
                prior = again["record"]
                state["pass"] = {"ts": prior.get("pass_ts"), "sha": prior.get("pass_sha")}
                kind = prior.get("kind")
                record["place"] = prior.get("place")
                say(f"{task}'s run resumed on the current engine after its re-exec: its pass of "
                    f"{prior.get('pass_ts')} stands, no new ticket, no second sync")
            elif form == "own":
                kind, nice = "own-tests", 19
                if "own-tests" in s["AT_ONCE"]:
                    say("own-tests check (task test --own): no ticket, no load reading, no spacing, no local "
                        "place, no light core lock")
                    got = fast_pass(p, "own-tests", pin="own", task=task, state=state)
                    if got is not None:
                        fds.append(got[0])
                        side = got[1]
                if not state.get("passed"):
                    if "own-tests" not in cur()["AT_ONCE"]:
                        say("own-tests check (task test --own), but AT_ONCE leaves it out: queued")
                    fast = ("own-tests", lambda: (True, "task test --own", None))
                    while not state.get("passed"):
                        placed: dict = {}
                        got = admit(p, "run", False, task=task, log_kind="own-tests", fast=fast, placed=placed,
                                    state=state, kernel=kernel)
                        if placed.get("fast"):
                            got2 = fast_pass(p, "own-tests", pin="own", task=task, ticket=placed["ticket"],
                                             state=state)
                            if got2 is not None:
                                fds.append(got2[0])
                                side = got2[1]
                            else:
                                state["drop"]()        # back to the queue: this ticket goes, a new one is filed
                            continue
                        fds.extend(got)
                        side = "light" if cur()["LIGHT_PIN"] else "run"
            else:
                decision = verify_decision(root, sweep) if not exclusive else (None, sweep, "exclusive")
                ok, why = no_layer_run(decision) if not exclusive else (False, "an exclusive run")
                fast = None
                if ok:
                    check = lambda: (*no_layer_run(verify_decision(root, sweep)), None)  # noqa: E731
                    if "no-layer" in s["AT_ONCE"]:
                        say(f"no-layer run ({why}): no ticket, no load reading")
                        kind = "no-layer"
                        got = fast_pass(p, "no-layer", pin="run", task=task, recheck=check, state=state)
                        if got is not None:
                            fds.append(got[0])
                    else:
                        say(f"no-layer run ({why}), but AT_ONCE leaves it out: queued")
                        fast = ("no-layer", check)
                if not state.get("passed"):
                    say(f"run queued ({why})")
                    mark = queue_jump(main, task)
                    reason, light_why = run_light(decision, cur(), mark=mark, exclusive=exclusive, full=full,
                                                  eligible=eligible)
                    light = (reason, light_why) if reason else None
                    if light:
                        say(f"run-light run ({reason}: {light_why})")
                    elif not exclusive and not mark:
                        say(f"not a run-light run ({light_why})")
                    placement = getattr(args, "placement", "auto") if args is not None else "auto"
                    kept: dict = {}

                    def carry():
                        """Read once, under LOCK at this run's first filing (T-14273); a refiled ticket of
                        this run keeps what that read found."""
                        if "ns" not in kept:
                            kept["ns"] = carried_arrival(p, task)
                            if kept["ns"]:
                                say(f"{task}'s last run stopped at its admission sync on a merge conflict: "
                                    f"this run keeps that ticket's arrival ({iso(kept['ns'] / 1e9)}), its old place")
                        return kept["ns"]
                    while not state.get("passed"):
                        placed = {}
                        got = admit(p, "run", mark, task=task, exclusive=exclusive, carry=carry,
                                    log_kind="run-exclusive" if exclusive else ("run-mark" if mark else "run"),
                                    venue=lambda: venue_state(root, kernel=kernel, placement=placement),
                                    placed=placed, fast=fast, light=light, unit=(str(root), task) if task else None,
                                    state=state, kernel=kernel)
                        if placed.get("fast"):
                            got2 = fast_pass(p, "no-layer", pin="run", task=task, ticket=placed["ticket"],
                                             recheck=fast[1], state=state)
                            if got2 is not None:
                                kind = "no-layer"
                                fds.append(got2[0])
                            else:
                                state["drop"]()        # back to the queue: this ticket goes, a new one is filed
                            continue
                        fds.extend(got)
                        kind = kind or ("exclusive" if exclusive else "run")
                        if placed.get("append") and args is not None and not kernel:
                            # THE PLACES: a local pass while a venue is published keeps the engine's
                            # pass on this host (the source's appended --placement local)
                            args.placement = "local"
                        record["place"] = placed.get("place")
        # the pass: the work's children inherit BUSY (rule 2 (g)), the process takes its CPUs (rule 2
        # (i): an empty set, no call) and an own-tests check its priority
        inherit(fds)
        if nice is not None:
            with contextlib.suppress(OSError):
                os.nice(max(0, nice - os.nice(0)))
        prow = state.get("pass") or {}
        record.update(pass_ts=prow.get("ts"), pass_sha=prow.get("sha"), kind=kind,
                      config_hash=cur()["_hash"])
        _ADMITTED[0] = record
        yield record
    except PinFailed as e:
        _left("pin-failed", str(e)[:300])
        say(f"{e}; the work does not run (exit 127)")
        raise SystemExit(127)
    except BaseException as e:
        if not state.get("passed"):
            _left("error" if not isinstance(e, SystemExit) else "exit",
                  f"{type(e).__name__}: {e}"[:300])
        raise
    finally:
        _ADMITTED[0] = None
        _RESUMED[0] = None
        uninherit()
        drop_running(p)
        for fd in fds:
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)


# ═══ A SCHEDULED PRE-DEPLOY RUN (SPEC-1045 rule 2 (p), SPEC-1047 rule 3; T-14203) ══════════════
# `deploy --scheduled-run` files a run ticket at its own start and is admitted as a run, in the declared
# order. It is tied to no card: no sync, no quick step, no land preview, no green hold, no run-plus-land
# unit, no credit answer. Its place is always this host's local place — it runs a fresh scratch checkout
# here and is never routed to a venue — so the local-place cap holds for it as for any local run. It
# holds BUSY shared while it runs, inherited by its children, and its ticket ends in one terminal row.
SCHEDULED_PLACE = {"published": False, "token": "scheduled-run", "box": None, "slots": None,
                   "forced_local": False, "why": "a scheduled pre-deploy run runs on this host (SPEC-1047 rule 4)"}


@contextlib.contextmanager
def scheduled_run_entry(*, main, append_event):
    """The queue's entry for a scheduled pre-deploy run (SPEC-1045 rule 2 (p)), switched on: one run
    ticket, the wait, the pass; yields the pass record its result rows are stamped with (`stamp`). At
    exit the RUNNING entry goes and the descriptors this process holds are closed (its children keep
    theirs)."""
    p = paths(main)
    try:
        ensure(p)
    except OSError as e:
        say(f"the queue's state directory {p['dir']} cannot be written ({e}); the run does not start")
        raise SystemExit(1)
    _P[0], _MAIN[0], _EMIT[0] = p, Path(main), append_event
    s = cur(p["main"])
    state: dict = {"arrival": time.time()}
    fds: list = []
    record = {"revision": revision(), "config_hash": s["_hash"]}

    def _left(reason, detail=None):
        if not state.get("passed") and not state.get("left"):
            state["left"] = True
            if state.get("drop"):
                state["drop"]()
            emit(LEFT, None, {"reason": reason, "detail": detail}, ticket=state.get("ticket"))

    try:
        with _waiting_signals(lambda signo: _left("signal", signal.Signals(signo).name)):
            say("scheduled pre-deploy run queued (SPEC-1047): tied to no card — no sync, no quick step, no land "
                "preview, no green hold, no unit, no credit answer")
            fds.extend(admit(p, "run", False, task=None, log_kind="scheduled-run", venue=lambda: SCHEDULED_PLACE,
                             state=state))
        inherit(fds)
        prow = state.get("pass") or {}
        record.update(pass_ts=prow.get("ts"), pass_sha=prow.get("sha"), kind="scheduled-run",
                      config_hash=cur()["_hash"])
        yield record
    except PinFailed as e:
        _left("pin-failed", str(e)[:300])
        say(f"{e}; the work does not run (exit 127)")
        raise SystemExit(127)
    except BaseException as e:
        if not state.get("passed"):
            _left("error" if not isinstance(e, SystemExit) else "exit", f"{type(e).__name__}: {e}"[:300])
        raise
    finally:
        uninherit()
        drop_running(p)
        for fd in fds:
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)


# ═══ THE LAND SIDE (T-14196) — the source's lock_only, its land classes and its checks ════════
# A land enters the queue in `land` itself (cli.py#cmd_land) BEFORE it asks for the land reservation
# (SPEC-0184 rule 1): the reservation, the SPEC-0184 formation and member checks, the shared merge,
# verify and ff run unchanged behind the pass. Rule 2: ONE land at a time (BATCH_MAX 1, no groups, no
# group spec check), no release lock, no gate. The engine's deciders are handed in by the caller in
# the land target `t` (rule 2 (b): called, never re-implemented):
#   t["main"], t["worktree"], t["branch"], t["card"], t["flags"] (the flags on the land command),
#   t["merge_probe"](tip, branch) -> (outcome, tree, detail)   the land's own conflict oracle
#   t["mergeable"]                                              the outcomes it calls mergeable
#   t["credit"](worktree, branch) -> {credit, reason, ref, main} the land's own Stage-6 credit answer
#   t["inert_class"](path) -> "inert" | ...                     the engine's inert classifier
#   t["sweep"](root) -> bool                                    whether the engine's test sweep runs
#   t["layer_guard"](dir, names) -> the layer runner's record   the engine's layer runner
MERGE_REFUSED = 4      # a land whose branch the engine proves does not merge with main: exit 4, no land run
LAND_SET_REFUSED = 7   # a land whose candidate turns a layer of the quick set red: exit 7, no land run
CREDIT_REFUSING = ("merge_invalid_acceptance", "expect_rebaseline", "rebaseline", "no_tests")
SHA = re.compile(r"[0-9a-f]{40}")


def _git(at, *args):
    return _git_cap(list(args), at)


def _land_decision(t):
    """(layers, sweep, why) — the engine's whole decision of what this land's verify executes (rule 2
    (o)): the layers of the branch's committed changes (layers_run, the land's reading) and the test
    sweep of its checkout. A sweep the caller cannot read runs."""
    wt = t.get("worktree")
    try:
        left, why = layers_run(wt, "main", working_tree=False)
    except Exception as e:             # noqa: BLE001 — undecided
        left, why = None, f"the skip decision failed ({type(e).__name__}: {e})"
    try:
        sweep = bool(t["sweep"](Path(wt)))
    except Exception:                  # noqa: BLE001 — a sweep that cannot be read runs
        sweep = True
    if sweep:
        why = f"{why}; the test sweep runs"
    return left, sweep, why


# ═══ A BOOKKEEPING LAND ═══════════════════════════════════════════════════════════════════════
# A land whose branch's content is already in main (git merge-tree of main and the branch gives main's
# tree), or for which the engine's whole decision runs nothing — no layer AND no test sweep (rule 2
# (o)). It passes at once: no ticket, no load reading, no busy check, no BUSY and no land hold (it holds
# no land, card T-0714: a queued land passes beside it under the empty rule, a run still reads its entry
# as a land that can move main); only an exclusive run holds it. Any failure of the check queues the
# land, and says why.
def bookkeeping(t):
    try:
        wt = t.get("worktree")
        if not wt:
            return False, t.get("why") or "no worktree found for the land"
        base_tree = _git(wt, "rev-parse", "main^{tree}")
        merged = _git(wt, "merge-tree", "--write-tree", "main", "HEAD")
        if (base_tree.returncode == 0 and merged.returncode == 0
                and merged.stdout.split()[:1] == [base_tree.stdout.strip()]):
            return True, "its content is already in main"
        left, sweep, why = _land_decision(t)
        return (left is not None and not left and not sweep), why
    except Exception as e:             # noqa: BLE001 — any failure queues the land
        return False, f"the bookkeeping check failed ({type(e).__name__}: {e})"


# ═══ A LIGHT LAND and A PLANNING LAND ═════════════════════════════════════════════════════════
# A LIGHT LAND: not bookkeeping and not credit-ready, the engine's decision runs at least one layer,
# every one of them in admission.light_layers, and no test sweep (rule 2 (o)). A ticket of class light,
# never in a group; as the head no SPACING and no reading while AT_ONCE names light; on LIGHT_PIN (the
# run CPUs under RUN_LAND_UNIT); after its pass it takes the light core's lock for its work.
# A PLANNING LAND: the skip decision answered, the branch starts with one of admission.planning.branches,
# and every path its commits change since the merge-base with main — less the paths the engine's own
# classifier calls inert — lies under admission.planning.paths: the queue-jump place. Under
# admission.planning_lands it passes another card's unit and green hold (`planning_free`). Both are
# decided at the land's arrival and again at its checks (`classifier`).
def light(t):
    """(ok, why, layers) — `layers` the run set, or None when the skip decision gave no answer."""
    try:
        if not t.get("worktree"):
            return False, t.get("why") or "no worktree found for the land", None
        left, sweep, why = _land_decision(t)
        if left is None:
            return False, why, None
        if not left:
            return False, why, left
        if sweep:
            return False, f"{why}: the test sweep runs beside its layers, not light (rule 2 (o))", left
        outside = sorted(left - set(cur()["LIGHT_LAYERS"]))
        if outside:
            return False, f"layer(s) {', '.join(outside)} outside admission.light_layers run for its changes", left
        return True, f"only layer(s) {', '.join(sorted(left))} of admission.light_layers run for its changes", left
    except Exception as e:             # noqa: BLE001 — any failure: not light
        return False, f"the light check failed ({type(e).__name__}: {e})", None


def planning(t, layers, layers_why=""):
    """(ok, why): whether the land is a planning land (see the banner). Any failure: not planning."""
    if layers is None:
        return False, f"the skip decision failed: {layers_why}"
    try:
        branch, wt = t.get("branch"), t.get("worktree")
        if not branch or not wt:
            return False, t.get("why") or "no branch for the land"
        branches = cur()["PLANNING_BRANCHES"]
        if not branches:
            return False, "admission.planning.branches names no branch"
        if not any(branch.startswith(b) for b in branches):
            return False, f"{branch} is not a {' or '.join(branches)} branch"
        base = _git(wt, "merge-base", "main", "HEAD")
        if base.returncode != 0 or not base.stdout.strip():
            return False, "no merge-base with main"
        out = _git(wt, "diff", "--name-only", "-z", base.stdout.strip(), "HEAD")
        if out.returncode != 0:
            return False, f"git diff failed in {wt}: {out.stderr.strip()[:200]}"
        changed = [x for x in out.stdout.split("\0") if x]
        if not changed:
            return False, "its commits change no path"
        prefixes = cur()["PLANNING_PATHS"]
        with contextlib.redirect_stdout(sys.stderr):
            outside = [x for x in changed if t["inert_class"](x) != "inert"
                       and not any(x.startswith(pp) for pp in prefixes)]
        if outside:
            return False, f"{len(outside)} path(s) outside admission.planning.paths: {', '.join(outside[:3])}"
        return True, "every path its commits change lies under admission.planning.paths"
    except Exception as e:             # noqa: BLE001 — any failure: not planning
        return False, f"the planning check failed ({type(e).__name__}: {e})"


def classify(t):
    """(class, lines): light, planning or land (ordinary); one skip decision feeds both checks."""
    ok, why, layers = light(t)
    if ok:
        return "light", [f"light land ({why}): ahead of the runs, no load reading"]
    lines = [f"not a light land ({why})"]
    pok, pwhy = planning(t, layers, why)
    lines.append(f"planning land ({pwhy}): the queue-jump place, the window as a marked land" if pok else
                 f"not a planning land ({pwhy})")
    return ("planning" if pok else "land"), lines


def classifier(t):
    """classify() for a waiting land, kept for one answer: asked again at each check, it decides again
    only when admission.light_layers, .planning.paths, .planning.branches, main's tip or the branch's
    head moved (one git rev-parse). A key that cannot be read: no cache, the whole check."""
    last = {"key": None, "answer": None}

    def ask():
        key = None
        if t.get("branch") and t.get("main"):
            heads = _git(t["main"], "rev-parse", "main^{commit}", f"{t['branch']}^{{commit}}")
            if heads.returncode == 0 and len(heads.stdout.split()) == 2:
                s = cur()
                key = (s["LIGHT_LAYERS"], s["PLANNING_PATHS"], s["PLANNING_BRANCHES"], tuple(heads.stdout.split()))
        if key is None or key != last["key"]:
            last["key"], last["answer"] = key, classify(t)
        return last["answer"]
    return ask


# ═══ THE MERGE CHECKS ═════════════════════════════════════════════════════════════════════════
# A land's branch is checked against main by the engine's own conflict oracle at its arrival, before
# any fast path, and again by the head just before it passes; a conflict on a path the engine does not
# merge itself is exit 4 (MERGE_REFUSED), its paths named, with no land run and an `admission_left`
# row; any failure of the check changes nothing and the line says why.
def main_check(t):
    """('conflict' | 'merges' | 'unchecked', paths, why)."""
    try:
        branch = t.get("branch")
        if not branch:
            return "unchecked", [], t.get("why") or "no branch for the land"
        tip = _git(t["main"], "rev-parse", "--verify", "--quiet", "main^{commit}")
        if tip.returncode != 0 or not tip.stdout.strip():
            return "unchecked", [], f"main cannot be read in {t['main']}"
        tip = tip.stdout.strip()
        with contextlib.redirect_stdout(sys.stderr):
            outcome, _tree, detail = t["merge_probe"](tip, branch)
        unresolved = [str(x) for x in ((detail or {}).get("unresolved") or [])]
        if unresolved:
            return "conflict", unresolved, f"{branch} against main {tip[:12]}"
        if outcome in t["mergeable"]:
            return "merges", [], f"{branch} merges with main {tip[:12]} ({outcome})"
        return "unchecked", [], f"the engine's merge check of {branch} could not decide ({outcome})"
    except Exception as e:             # noqa: BLE001 — the land goes on as before the check
        return "unchecked", [], f"the merge check failed ({type(e).__name__}: {e})"


def refused_lines(t, paths, why):
    card, branch = t.get("card"), t.get("branch") or ""
    sync = (f"--task {card}" if card else f"--work {branch[len('work/'):]}" if branch.startswith("work/")
            else "--work <slug>")
    return [f"land not started: {why}, the branch conflicts on paths the engine does not merge itself: "
            f"{', '.join(paths)}",
            f"sync the branch with main (yitc-v2 worktree sync {sync}), resolve, and land again"]


# ═══ A CREDIT-READY LAND ══════════════════════════════════════════════════════════════════════
# A land the engine says will take its worker's Stage-6 credit, asked of the engine itself in-process
# (rule 2 (b): `land_report_arm("credit")`, the land's own SPEC-0065 §Bound predicate over main's tip
# now — the source asked it of `land --report credit` under a report bound; in-process no bound
# applies). The land itself still decides; this class only orders it. A flag that makes the engine
# verify the land alone reads not ready without asking; any failure reads not ready, and says why.
def moved_since(pin):
    """Why a credit-ready land's check no longer holds (main or the branch moved since it), or None."""
    tip = _git(pin["main"], "rev-parse", "main")
    if tip.returncode != 0 or tip.stdout.strip() != pin["tip"]:
        return f"main moved since the credit check (now {tip.stdout.strip()[:12]}, checked {pin['tip'][:12]})"
    head = _git(pin["worktree"], "rev-parse", "HEAD")
    if head.returncode != 0 or head.stdout.strip() != pin["head"]:
        return f"the branch moved since the credit check (now {head.stdout.strip()[:12]}, checked {pin['head'][:12]})"
    return None


def credit_ready(t, moved=None):
    """(True, why, pin) or (False, why, None). A refusal for main's advance (`main-moved`) fills `moved`
    with the answer's reason and ref (THE SET OF A LAND reads it)."""
    try:
        flags = [f for f in CREDIT_REFUSING if f in (t.get("flags") or ())]
        if flags:
            return False, f"--{flags[0].replace('_', '-')} on the land command", None
        wt, branch = t.get("worktree"), t.get("branch")
        if not wt or not branch:
            return False, t.get("why") or "no worktree found for the land", None
        head = _git(wt, "rev-parse", "HEAD")
        if head.returncode != 0 or not head.stdout.strip():
            return False, f"git rev-parse HEAD failed in {wt}", None
        with contextlib.redirect_stdout(sys.stderr):
            answer = t["credit"](Path(wt), branch)
        if not isinstance(answer, dict) or not isinstance(answer.get("credit"), bool):
            return False, f"the engine's credit answer is not readable: {str(answer)[:200]!r}", None
        reason = answer.get("reason") or "?"
        if not answer["credit"]:
            ref = answer.get("ref") if isinstance(answer.get("ref"), dict) else {}
            paths = ref.get("paths") or ref.get("moved") or []
            detail = (f" ({ref.get('class', '?')}: {', '.join(str(x) for x in paths[:3])})"
                      if reason == "main-moved" and paths else "")
            if reason == "main-moved" and moved is not None:
                moved.update({"reason": reason, "ref": ref})
            return False, f"the engine's credit answer: {reason}{detail}", None
        tip = answer.get("main")
        if not isinstance(tip, str) or not SHA.fullmatch(tip):
            return False, f"the engine's credit answer names no sha for main ({tip!r})", None
        return True, f"the engine's credit answer: {reason}", {"main": t["main"], "tip": tip, "worktree": wt,
                                                               "head": head.stdout.strip()}
    except Exception as e:             # noqa: BLE001 — not ready, the land is queued
        return False, f"the credit check failed ({type(e).__name__}: {e})", None


# ═══ THE SET OF A LAND ════════════════════════════════════════════════════════════════════════
# An ordinary land (marked or not) the credit does not take because main moved since its Stage-6 run
# (the engine's credit answer `main-moved`, its predicate having tried the post-sync-proof arm) takes
# the project's quick set on its candidate — main's tip merged with its branch by the land's own
# oracle — at its arrival, after the merge check, the credit check and its class, before any ticket,
# and again as the head just before it passes. The quick set is the project's verify.post_sync_set
# (rule 2 (d)); no set declared, no step. Its layers run through the engine's layer runner one at a
# time in a scratch checkout of the candidate under the queue's state directory (removed after), each
# within LAND_SET_FILE_BOUND and all within LAND_SET_BOUND (rule 2 (k): BUDGET). A layer red on the
# candidate and green on main's tip alone is exit 7 (LAND_SET_REFUSED), no land run; a failure main
# alone has too (main-red), and a check that cannot run (unrun), keep the land. One `land-set` step row
# each. Never for a credit-ready, bookkeeping, light or planning land.
def quick_set(main):
    """(declared, names, why) of the MAIN carrier's verify.post_sync_set: declared False when there is
    none (no quick step); names None when one is declared that cannot run as the set's one form on
    main, SPEC-0152 rule 16's list of declared layer names (`unrun`, said, never silently not due)."""
    ops = _load_ops(main)
    ver = ops.get("verify") if isinstance(ops, dict) else None
    names = ver.get("post_sync_set") if isinstance(ver, dict) else None
    if not names:
        return False, None, "the project declares no verify.post_sync_set: no quick set"
    layers = ver.get("layers")
    declared = ({str(ly.get("layer")) for ly in layers if isinstance(ly, dict)} if isinstance(layers, list) else set())
    if not (isinstance(names, list) and all(isinstance(n, str) and n.strip() for n in names)):
        return True, None, f"its verify.post_sync_set is not a list of layer names ({str(names)[:120]!r})"
    missing = sorted({n.strip() for n in names} - declared)
    if missing:
        return True, None, f"its verify.post_sync_set names {', '.join(missing)}, no declared verify layer"
    return True, sorted({n.strip() for n in names}), "the declared quick set"


def land_set_due(t, cls):
    """(True, names, why) when the land takes THE SET OF A LAND, else (False, None, why)."""
    if cls != "land":
        return False, None, f"a {cls} land takes no set"
    declared, names, why = quick_set(t["main"])
    if not declared:
        return False, None, why
    if names is None:
        names = why                    # due, but it cannot run here: `unrun`, said (land_set_gate)
    moved: dict = {}
    ok, cwhy, _ = credit_ready(t, moved)
    if ok:
        return False, None, f"credit-ready ({cwhy})"
    if not moved:
        return False, None, f"not credit-ready, not for main's advance ({cwhy})"
    return True, names, f"not credit-ready: {cwhy}"


def _set_layers_on(t, commit, names, deadline, p):
    """(failed layer names, error or None) of the quick set run on a scratch checkout of `commit`."""
    s = cur()
    d = Path(p["dir"]) / f"land-set-{os.getpid()}-{time.time_ns()}"
    made = _git(t["main"], "worktree", "add", "--detach", "--quiet", str(d), commit)
    try:
        if made.returncode != 0:
            return set(), f"the scratch checkout cannot be made ({(made.stderr or '').strip()[:200]})"
        failed = set()
        for name in names:
            left = deadline - time.time()
            if left <= 0:
                return set(), f"the set ran past LAND_SET_BOUND {s['LAND_SET_BOUND']:g} s"
            bound = min(float(s["LAND_SET_FILE_BOUND"]), left)
            prior = os.environ.get("YITC_VERIFY_TEST_TIMEOUT")
            os.environ["YITC_VERIFY_TEST_TIMEOUT"] = f"{bound:g}"
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    g = t["layer_guard"](d, [name])
            finally:
                if prior is None:
                    os.environ.pop("YITC_VERIFY_TEST_TIMEOUT", None)
                else:
                    os.environ["YITC_VERIFY_TEST_TIMEOUT"] = prior
            rows = {r.get("layer"): r.get("outcome") for r in ((g or {}).get("layers") or []) if isinstance(r, dict)}
            outcome = rows.get(name)
            if time.time() > deadline:
                return set(), f"the set ran past LAND_SET_BOUND {s['LAND_SET_BOUND']:g} s"
            if outcome == "passed":
                continue
            if outcome == "failed":
                failed.add(name)
                continue
            return set(), f"layer {name} did not run to a verdict ({outcome or (g or {}).get('mode')})"
        return failed, None
    finally:
        _git(t["main"], "worktree", "remove", "--force", str(d))
        _git(t["main"], "worktree", "prune")
        if d.exists():
            import shutil
            shutil.rmtree(d, ignore_errors=True)


def land_set_check(t, names, p):
    """{"outcome", "secs", "detail"}: clear | main-red | red | unrun."""
    t0 = time.time()

    def out(outcome, detail):
        return {"outcome": outcome, "secs": time.time() - t0, "detail": detail}
    try:
        branch = t.get("branch")
        if not branch:
            return out("unrun", f"not run: {t.get('why') or 'no branch'}")
        head = _git(t["main"], "rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}").stdout.strip()
        tip = _git(t["main"], "rev-parse", "--verify", "--quiet", "main^{commit}").stdout.strip()
        if not head or not tip:
            return out("unrun", f"not run: main or {branch} is unread")
        deadline = t0 + float(cur()["LAND_SET_BOUND"])
        with contextlib.redirect_stdout(sys.stderr):
            outcome, tree, _detail = t["merge_probe"](tip, branch)
        if outcome not in t["mergeable"] or not tree:
            return out("unrun", f"not run: no candidate tree ({outcome}: a conflict the land does not resolve)")
        made = _git(t["main"], "commit-tree", tree, "-p", tip, "-p", head, "-m", "admission land-set candidate")
        if made.returncode != 0 or not made.stdout.strip():
            return out("unrun", f"not run: the candidate cannot be committed ({(made.stderr or '').strip()[:200]})")
        failures, err = _set_layers_on(t, made.stdout.strip(), names, deadline, p)
        on_main = set()
        if err is None and failures:
            on_main, err = _set_layers_on(t, tip, names, deadline, p)
        if err is not None:
            return out("unrun", f"not run: {err}")
        if not failures:
            return out("clear", f"{len(names)} layer(s) green: {', '.join(names)}")
        if not failures - on_main:
            return out("main-red", f"every failure is main's alone too: {', '.join(sorted(failures))}")
        return out("red", f"the quick set's layer(s) {', '.join(sorted(failures - on_main))}")
    except Exception as e:             # noqa: BLE001 — not run, the land goes on
        return out("unrun", f"not run: the check failed ({type(e).__name__}: {e})")


def land_set_gate(p, t, cls):
    """THE SET OF A LAND when due: its line, a `land-set` step row, and (LAND_SET_REFUSED, detail) for a
    red set, else None."""
    due, names, why = land_set_due(t, cls)
    if not due:
        return None
    r = (land_set_check(t, names, p) if isinstance(names, list) else
         {"outcome": "unrun", "secs": 0.0, "detail": f"not run: {names}"})
    say(f"quick set on main merged with the branch: {r['outcome']} in {r['secs']:.2f} s ({r['detail']}); {why}")
    log_step(p, t.get("card"), "land-set", r["outcome"], r["secs"], r["detail"])
    if r["outcome"] != "red":
        return None
    say(f"land not started: on main merged with the branch {r['detail']} red, green on main alone")
    say(f"sync the branch with main (yitc-v2 worktree sync --task {t.get('card') or '<card>'}), fix, and land again")
    return LAND_SET_REFUSED, r["detail"]


def take_lightcore(p):
    """The light core's lock, EXCLUSIVE, waited for (said once): a light land's work holds it."""
    fd = try_flock(p["lightcore"], fcntl.LOCK_EX)
    if fd is None:
        say("wait: the light core is held (a quick check after a sync); this light land waits for it")
        fd = _open_lockfile(p["lightcore"])
        fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


# ═══ THE LAND FORM — `land` enters the queue (the source's lock_only) ═════════════════════════
@contextlib.contextmanager
def land_entry(t, *, append_event):
    """The queue's entry for a land, switched on: the merge check, then a bookkeeping land or a
    credit-ready land passes at once (AT_ONCE), else the land is classed (light / planning / land), takes
    THE SET OF A LAND when due, and queues — one land at a time — with the head's recheck (the merge
    check and the set again). Yields the pass record {revision, config_hash, pass_ts, kind}; at exit the
    land's code reaches `landed` (0 ends its card's green hold), the RUNNING entry goes and the
    descriptors are closed (the work's children keep theirs)."""
    main = Path(t["main"])
    p = paths(main)
    try:
        ensure(p)
    except OSError as e:
        say(f"the queue's state directory {p['dir']} cannot be written ({e}); the land does not start")
        raise SystemExit(1)
    _P[0], _MAIN[0], _EMIT[0] = p, main, append_event
    s = cur(main)
    card = t.get("card")
    state: dict = {"arrival": time.time()}
    fds: list = []
    record = {"revision": revision(), "config_hash": s["_hash"]}
    kind = None

    def _left(reason, detail=None):
        if not state.get("passed") and not state.get("left"):
            state["left"] = True
            if state.get("drop"):
                state["drop"]()
            emit(LEFT, card, {"reason": reason, "detail": detail}, ticket=state.get("ticket"))

    def _refuse(code, reason, detail):
        _left(reason, detail)
        raise SystemExit(code)

    try:
        with _waiting_signals(lambda signo: _left("signal", signal.Signals(signo).name)):
            verdict, mpaths, mwhy = main_check(t)
            if verdict == "conflict":
                for line in refused_lines(t, mpaths, mwhy):
                    say(line)
                _refuse(MERGE_REFUSED, "merge-conflict", {"paths": mpaths, "why": mwhy})
            say(f"merge check: {mwhy}" if verdict == "merges" else
                f"no merge check against main ({mwhy}); the land goes on as before the check")
            fast = None

            def merge_again():
                # a fast land's own check after any wait makes the merge check again (the source's merge
                # check before every pass): a conflict that arose meanwhile refuses (exit 4)
                v, mp, mw = main_check(t)
                if v == "conflict":
                    for line in refused_lines(t, mp, mw):
                        say(line)
                    raise Refused(MERGE_REFUSED, ("merge-conflict", {"paths": mp, "why": mw}))

            check_bk = lambda: (merge_again(), *bookkeeping(t), None)[1:]     # noqa: E731
            check_credit = lambda: (merge_again(), *credit_ready(t))[1:]      # noqa: E731
            ok, why = bookkeeping(t)
            if ok:
                if "bookkeeping" in cur()["AT_ONCE"]:
                    say(f"bookkeeping land ({why}): no ticket, no load reading")
                    got = fast_pass(p, "bookkeeping", pin="run", task=card, recheck=check_bk, state=state, busy=False)
                    if got is not None:
                        kind = "bookkeeping"
                        fds.extend(got[0::2])
                    else:
                        ok, why = bookkeeping(t)
                else:
                    say(f"bookkeeping land ({why}), but AT_ONCE leaves it out: queued")
                if ok and not state.get("passed") and "bookkeeping" not in cur()["AT_ONCE"]:
                    fast = ("bookkeeping", check_bk)
            if not state.get("passed"):
                cok, cwhy, cpin = credit_ready(t)
                if cok:
                    if "credit" in cur()["AT_ONCE"]:
                        say(f"credit-ready land ({cwhy}): no ticket, no load reading")
                        got = fast_pass(p, "credit", pin="run", task=card, recheck=check_credit, state=state,
                                        busy=False, credit=cpin)
                        if got is not None:
                            kind = "credit"
                            fds.extend(got[0::2])
                    else:
                        say(f"credit-ready land ({cwhy}), but AT_ONCE leaves it out: queued")
                    if (not state.get("passed") and "credit" not in cur()["AT_ONCE"] and fast is None
                            and check_credit()[0]):
                        fast = ("credit", check_credit)
                else:
                    say(f"not credit-ready ({cwhy})")
            if not state.get("passed"):
                say(f"land queued ({why})")
                cls, lines = classify(t)
                for line in lines:
                    say(line)
                gate = land_set_gate(p, t, cls)
                if gate is not None:
                    _refuse(gate[0], "land-set-red", gate[1])
                mark = queue_jump(main, card)
                info = {"branch": t.get("branch"), "worktree": str(t.get("worktree") or "")}

                def recheck(cls_now):
                    v, mp, mw = main_check(t)
                    if v == "conflict":
                        for line in refused_lines(t, mp, mw):
                            say(line)
                        raise Refused(MERGE_REFUSED, ("merge-conflict", {"paths": mp, "why": mw}))
                    g_ = land_set_gate(p, t, cls_now)
                    if g_ is not None:
                        raise Refused(g_[0], ("land-set-red", g_[1]))
                reclassify = classifier(t)
                while not state.get("passed"):
                    placed: dict = {}
                    got = admit(p, "land", mark, task=card, log_kind="land-mark" if mark else "land", info=info,
                                recheck=recheck, land_cls=cls, reclassify=reclassify, placed=placed, fast=fast,
                                state=state)
                    if placed.get("fast"):
                        fkind, answer = placed["fast"]
                        got2 = fast_pass(p, fkind, pin="run", task=card, ticket=placed["ticket"], state=state,
                                         recheck=check_bk if fkind == "bookkeeping" else check_credit, busy=False,
                                         credit=answer[2] if fkind == "credit" else None)
                        if got2 is not None:
                            kind = fkind
                            fds.extend(got2[0::2])
                        else:
                            cls = land_class(placed["ticket"])
                            state["drop"]()        # back to the queue: this ticket goes, a new one is filed
                        continue
                    fds.extend(got)
                    kind = placed.get("cls") or "land"
                    if placed.get("cls") == "light":
                        fds.append(take_lightcore(p))
        inherit(fds)
        prow = state.get("pass") or {}
        record.update(pass_ts=prow.get("ts"), pass_sha=prow.get("sha"), kind=kind, config_hash=cur()["_hash"])
    except Refused as e:
        reason, detail = e.why if isinstance(e.why, tuple) else ("refused", e.why)
        _left(reason, detail)
        uninherit()
        drop_running(p)
        raise SystemExit(e.code)
    except PinFailed as e:
        _left("pin-failed", str(e)[:300])
        say(f"{e}; the land does not run (exit 127)")
        drop_running(p)
        raise SystemExit(127)
    except BaseException as e:
        if not state.get("passed"):
            _left("error" if not isinstance(e, SystemExit) else "exit", f"{type(e).__name__}: {e}"[:300])
        uninherit()
        drop_running(p)
        for fd in fds:
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
        raise
    code = 1
    try:
        yield record
        code = 0
    except SystemExit as e:
        code = 0 if e.code in (None, 0) else (e.code if isinstance(e.code, int) else 1)
        raise
    finally:
        with contextlib.suppress(Exception):
            landed(p, card, code)
        uninherit()
        drop_running(p)
        for fd in fds:
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)


LAND_PASS_ENV = "YITC_LAND_ADMITTED_PASS"   # the pass a `land --task` re-exec child inherits from its parent


def pass_token(main) -> str:
    """A one-time token for this process's admitted land, written on its RUNNING entry: the re-exec
    child it addresses takes the inherited pass only while the entry carries it (`pass_token_holds`)."""
    import secrets
    token = secrets.token_hex(16)
    p = paths(main)
    entry = running_entry(p, os.getpid())
    if entry is not None:
        entry["pass_token"] = token
        write_json(Path(p["running"]) / str(os.getpid()), entry)
    return token


def pass_token_holds(root, pid, token) -> bool:
    """Whether `pid` is alive and its RUNNING entry in the queue of `root`'s repository carries `token`
    — CONSUMED here, under the queue's lock: the first process to present it takes the pass, every later
    one reads False and queues itself."""
    try:
        if not token or not isinstance(pid, int) or not alive(pid):
            return False
        p = paths(root)
        with Locked(p["lock"]):
            entry = running_entry(p, pid)
            if not isinstance(entry, dict) or entry.get("pass_token") != token:
                return False
            entry.pop("pass_token", None)
            write_json(Path(p["running"]) / str(pid), entry)
            return True
    except Exception:                  # noqa: BLE001 — unreadable: not addressed
        return False


# ═══ THE COMPARISON PROTOCOL — the soak window, read-only (the plan's §Verification) ════════════
# The plan's comparison protocol, read the same way in every project from the MAIN journal's own rows:
# BASELINE — the last SOAK_SIZE ok task lands before the first queue pass row, fixed once; THE SOAK
# WINDOW — from a window start to its SOAK_SIZE-th ok task land, all under one applied configuration
# and one queue revision; a window starts at the first pass row, and again at the first pass row after
# a disqualifying event (a land or the run it credits failing SOAK PROOF, a changed configuration, a
# changed queue revision). Over that one window: CREDIT SHARE, CARDS PER HOUR, ABORT RATE, and beside
# them SIGNALS and UNKNOWN; a window with any UNKNOWN is unfit. Takes no lock and writes nothing.
# A queue row is a write attempt (rule 2 (e)): a result row naming a pass that has no row is UNKNOWN.
SOAK_SIZE = 20   # the plan's window: 20 consecutive ok task lands (its §Verification, «the protocol»)
SOAK_TYPES = (PASS, "land_completed", "land_terminated_externally", *RESULT_TYPES)
LAND_PASS_KINDS = ("land", "land-mark", "light", "planning", "bookkeeping", "credit")


def _soak_data(row) -> dict:
    d = row.get("data")
    return d if isinstance(d, dict) else {}


def _soak_task_land(row) -> bool:
    """A task land: its land_completed names a `task/` branch."""
    return str(_soak_data(row).get("branch") or "").startswith("task/")


def _soak_secs(ts):
    import calendar
    try:
        return calendar.timegm(time.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return None


def _soak_proof(row, key, runs, passes) -> "str | None":
    """SOAK PROOF of one land_completed under the window's (config hash, revision) `key`: None when it
    holds, else why not. The land must name, by `admission_pass_ts`, a pass; a pass row of `passes`
    (ts -> the keys of the pass rows at that ts) at that ts must be under the same key — a ts with no
    row at all is no restart but an UNKNOWN of the window (`_soak_gaps`, rule 2 (e)). A stage6-credit
    land's credited run (stage6_credit task + ts) must be found among `runs` and carry the same; a
    credited run that cannot be found fails (fail-closed)."""
    d = _soak_data(row)
    if d.get("admission") != "engine":
        return "land-not-admitted"
    pass_ts = d.get("admission_pass_ts")
    if not pass_ts or (pass_ts in passes and key not in passes[pass_ts]):
        return "land-names-no-admission-pass"
    if (d.get("admission_config_hash"), d.get("admission_revision")) != key:
        return "land-under-another-configuration-or-revision"
    if d.get("reverify_skip_reason") == "stage6-credit":
        c = d.get("stage6_credit") if isinstance(d.get("stage6_credit"), dict) else {}
        run = runs.get((c.get("task"), c.get("ts")))
        if run is None:
            return "credited-run-not-found"
        rd = _soak_data(run)
        if rd.get("admission") != "engine":
            return "credited-run-not-admitted"
        if (rd.get("admission_config_hash"), rd.get("admission_revision")) != key:
            return "credited-run-under-another-configuration-or-revision"
    return None


def _soak_gaps(rows, span) -> list:
    """The result rows of `span` — every land_completed and Stage-6 result row, and the run each land
    credits — that carry `admission: engine` and name a pass timestamp no `admission_pass` row has: its
    row was attempted and not written (rule 2 (e)), so the outcome is UNKNOWN. Each listed once."""
    have = {r.get("ts") for r in rows if r.get("type") == PASS}
    runs = {(r.get("task_id"), r.get("ts")): r for r in rows if r.get("type") in RESULT_TYPES}
    out, seen = [], set()

    def gap(r):
        d = _soak_data(r)
        pass_ts = d.get("admission_pass_ts")
        k = (r.get("type"), r.get("task_id"), r.get("ts"))
        if d.get("admission") != "engine" or not pass_ts or pass_ts in have or k in seen:
            return
        seen.add(k)
        out.append({"ts": r.get("ts"), "task": r.get("task_id"), "row": r.get("type"), "pass_ts": pass_ts,
                    "why": "admitting-pass-row-missing"})
    for r in span:
        if r.get("type") == "land_completed" or r.get("type") in RESULT_TYPES:
            gap(r)
        if r.get("type") == "land_completed" and isinstance(_soak_data(r).get("stage6_credit"), dict):
            c = _soak_data(r)["stage6_credit"]
            run = runs.get((c.get("task"), c.get("ts")))
            if run is not None:
                gap(run)
    return out


def _soak_measure(rows, lo, hi, *, alive_fn) -> dict:
    """The metrics over rows[lo..hi] (inclusive): credit share, cards per hour, abort rate, SIGNALS and
    UNKNOWN. An attempt is a land_completed that names the pass that admitted it (a refusal printed
    before the land starts is no attempt); the baseline, before any pass, counts every land_completed.
    UNKNOWN is a land pass row no land_completed names (by `admission_pass_ts`) whose pid is gone (a
    land still alive is not counted), and a result row naming a pass that has no row (`_soak_gaps`)."""
    span = rows[lo:hi + 1]
    ok = [r for r in span if r.get("type") == "land_completed" and _soak_task_land(r)
          and _soak_data(r).get("status") == "ok"]
    switched = any(r.get("type") == PASS for r in span)
    ended = [r for r in span if r.get("type") == "land_completed" and _soak_data(r).get("status") in ("ok", "abort")
             and (not switched or _soak_data(r).get("admission_pass_ts"))]
    aborts = [r for r in ended if _soak_data(r).get("status") == "abort"]
    named = {_soak_data(r).get("admission_pass_ts") for r in rows if r.get("type") == "land_completed"}
    unknown = []
    for r in span:
        d = _soak_data(r)
        if r.get("type") != PASS or d.get("kind") not in LAND_PASS_KINDS or r.get("ts") in named:
            continue
        pid = d.get("pid")
        if type(pid) is int and alive_fn(pid):
            continue
        unknown.append({"ts": r.get("ts"), "task": r.get("task_id"), "pid": pid})
    unknown.extend(_soak_gaps(rows, span))
    reasons: dict = {}
    for r in ok:
        why = _soak_data(r).get("reverify_skip_reason") or "verified"
        reasons[why] = reasons.get(why, 0) + 1
    cards = sorted({str(r.get("task_id") or _soak_data(r).get("branch")) for r in ok})
    t0, t1 = (_soak_secs(ok[0].get("ts")), _soak_secs(ok[-1].get("ts"))) if ok else (None, None)
    hours = (t1 - t0) / 3600.0 if t0 is not None and t1 is not None else None
    return {"ok_task_lands": len(ok),
            "credit_share": (reasons.get("stage6-credit", 0) / len(ok)) if ok else None,
            "skip_reasons": reasons,
            "cards_per_hour": (len(cards) / hours) if hours else None,
            "abort_rate": (len(aborts) / len(ended)) if ended else None,
            "signals": sum(1 for r in span if r.get("type") == "land_terminated_externally"),
            "unknown": unknown,
            "from": span[0].get("ts") if span else None, "to": span[-1].get("ts") if span else None}


def soak(rows, *, size=SOAK_SIZE, alive_fn=None) -> dict:
    """THE COMPARISON PROTOCOL over `rows` (the main journal's SOAK_TYPES rows, journal order): the
    baseline, the first complete soak window (else the window still filling) and its metrics, and every
    restart with its reason. `fit` = a complete window with no UNKNOWN. Pure over its input."""
    alive_fn = alive_fn or alive
    rows = [r for r in rows if isinstance(r, dict)]
    first = next((i for i, r in enumerate(rows) if r.get("type") == PASS), None)
    base_end = first if first is not None else len(rows)
    base_lands = [i for i in range(base_end) if rows[i].get("type") == "land_completed"
                  and _soak_task_land(rows[i]) and _soak_data(rows[i]).get("status") == "ok"][-size:]
    out: dict = {"size": size, "switched_on": first is not None,
                 "baseline": (_soak_measure(rows, base_lands[0], base_end - 1, alive_fn=alive_fn)
                              if base_lands else None),
                 "window": None, "complete": False, "fit": False, "restarts": []}
    if first is None:
        return out
    runs = {(r.get("task_id"), r.get("ts")): r for r in rows if r.get("type") == "tests_passed"}
    passes: dict = {}
    for r in rows:
        if r.get("type") == PASS:
            passes.setdefault(r.get("ts"), set()).add((_soak_data(r).get("config_hash"),
                                                      _soak_data(r).get("revision")))
    start, key, count, end, i = first, None, 0, None, first
    while i < len(rows):
        r, d = rows[i], _soak_data(rows[i])
        why = None
        if r.get("type") == PASS:
            k = (d.get("config_hash"), d.get("revision"))
            if start is None:
                start, key, count = i, k, 0
            elif key is None:
                key = k
            elif k != key or k[0] is None:
                why = "configuration-or-revision-changed"
        elif r.get("type") == "land_completed" and start is not None:   # every attempt, ok or abort
            why = _soak_proof(r, key, runs, passes)
            if why is None and d.get("status") == "ok" and _soak_task_land(r):
                count += 1
                if count == size:
                    end = i
                    break
        if why is not None:
            out["restarts"].append({"ts": r.get("ts"), "reason": why})
            if r.get("type") == PASS:       # this pass row starts the next window
                start, key, count = i, (d.get("config_hash"), d.get("revision")), 0
            else:                           # the next window starts at the next pass row
                start, key, count = None, None, 0
        i += 1
    if start is not None:
        hi = end if end is not None else len(rows) - 1
        m = _soak_measure(rows, start, hi, alive_fn=alive_fn)
        m.update(config_hash=key[0] if key else None, revision=key[1] if key else None)
        out.update(window=m, complete=end is not None, fit=end is not None and not m["unknown"])
    return out


def soak_rows(path) -> list:
    """The SOAK_TYPES rows of the LOGICAL journal at `path` (every segment, rule 2 (c)), journal order."""
    from lib import journal as journal_mod
    return journal_mod.segment_rows(Path(path), types=SOAK_TYPES)

# ═══ `journal query --admission` — the queue's state, read-only (rule 2 (e)) ═════════════════
def report(main) -> "dict | None":
    """The queue's state as it stands now while switched on, or None while off: the tickets in their
    order (position, ticket, class, task, pid, since), the RUNNING entries (kind, task, pid, since),
    the green hold and the flocks. Takes no lock and writes nothing; a state directory that cannot be
    read reads `unknown`, never empty."""
    sw = switch(main)
    if not sw.get("on"):
        return None
    out: dict = {"pool": "queue", "configured": True, "switch": sw.get("why"), "readable": True,
                 "waiters": [], "holders": [], "hold": None}
    try:
        p = paths(main)
        _P[0], _MAIN[0] = p, Path(main)
        cur(main)
        names = sorted((n for n in os.listdir(p["queue"]) if n.split("-")[1:2] and n.split("-")[1].isdigit()
                        and alive(int(n.split("-")[1]))), key=order) if Path(p["queue"]).is_dir() else []
        for pos, name in enumerate(names, 1):
            data = read_json(Path(p["queue"]) / name) or {}
            out["waiters"].append({"position": pos, "ticket": name, "class": ticket_class(name),
                                   "task": data.get("task") if isinstance(data.get("task"), str) else None,
                                   "pid": int(name.split("-")[1]),
                                   "since": iso(int(name.split("-")[0]) / 1e9)})
        if Path(p["running"]).is_dir():
            for name in sorted(os.listdir(p["running"])):
                if name.isdigit() and alive(int(name)):
                    e = read_json(Path(p["running"]) / name) or {}
                    out["holders"].append({"pid": int(name), "kind": e.get("kind") or "?",
                                           "task": e.get("task") if isinstance(e.get("task"), str) else None,
                                           "since": e.get("since_ts")})
        h = hold_read(p) if Path(p["hold"]).exists() else None
        out["hold"] = None if h is None else {"card": h.get("card"), "set_ts": h.get("set_ts"),
                                              "unreadable": bool(h.get("unreadable"))}
    except (OSError, ValueError) as e:
        out.update(readable=False, error=f"{type(e).__name__}: {e}")
    try:                               # the comparison protocol over the main journal (T-14198)
        out["soak"] = soak(soak_rows(Path(main) / "events.jsonl"))
    except Exception as e:             # noqa: BLE001 — an unreadable journal reads as such, never empty
        out["soak"] = {"error": f"{type(e).__name__}: {e}"}
    return out
