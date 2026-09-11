"""The verify venue — the record, the provider client and the readiness probe (SPEC-0203, T-12197).

WHAT THIS IS. The module the four `venue raise|publish|unpublish|delete` verbs are a thin residue
over. It owns three things and nothing else: rule 1's machine-scoped record, the provider client
that RAISES and DELETES the box, and the readiness probe that decides whether a box may be
published at all. The CLI host (`bin/lib/cli.py`) owns argparse and the journal emits — the same
split `lib/machine_settings.py` has with `cmd_config_*`, and for the same reason: the record lives
OUTSIDE every checkout, so these verbs need no worktree and belong to no lifecycle stage.

WHAT IT IS NOT. No verdict, no result, no attempt ever reaches the record (SPEC-0203 rule 1;
CHARTER §P5 — those live in the journal and in the transient per-attempt envelope). There is no
daemon, no poll loop and no second store here: the idle-condition DELETE is a durable-state read the
compute-controller session makes (rule 6), not a watcher this module runs.

THE PROVIDER CODE IS PORTED, NOT REINVENTED. `dev-utilities/venue-seed-recipe.sh` (T-12193) carries
the measured raise-from-image / readiness-probe / delete against the Hetzner API, the quota refusal
and the bounded-wait primitive. This is that shape in Python/urllib.

THE TOKEN. Read from `/home/dev/secrets/hetzner-api-token` at the request seam ONLY, never returned
to a caller, never formatted into a message, never journaled. Unlike the recipe's curl there is no
argv exposure to defend against at all: the value travels as an `Authorization` HEADER on a urllib
Request, and `ps` cannot see a header. Every exception this module raises is built from the
provider's status/code/message, so no refusal path can carry it either (AC4).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from lib import host_paths  # T-12024: the stdlib-only host-home leaf (no cycle)
from lib import remote_verify

# ── The record (rule 1) ───────────────────────────────────────────────────────────────────────
RECORD_SCHEMA = "yitc.verify-venue/1"
RECORD_FILENAME = "verify-venue.json"
RECORD_ENV = "YITC_VENUE_RECORD"

# ── The provider (rule 6) ─────────────────────────────────────────────────────────────────────
API_BASE = "https://api.hetzner.cloud/v1"
TOKEN_FILE_ENV = "VENUE_TOKEN_FILE"
# DERIVED, NOT LITERAL (T-12024, SPEC-0074 rule 4 code side). The secrets home is resolved by
# `host_paths.host_home()` rather than spelled out, so an engine copied to another machine reads
# THAT machine's secrets dir instead of inheriting this one's path. On this host the derived value
# is byte-identical to the literal it replaces. `VENUE_TOKEN_FILE` remains the per-value override.
TOKEN_FILE_DEFAULT = str(host_paths.host_home() / "secrets" / "hetzner-api-token")
SERVER_TYPE = "ccx63"
LOCATION = "hel1"
SSH_KEY_NAME = "yitc-verify-experiment-dev"
BOX_USER = "dev"
API_TIMEOUT = 60

#: Bounded waits — the recipe's measured bands. There is no unbounded loop in this module.
WAIT_READY_INTERVAL = 5


def wait_ready_interval() -> float:
    """T-12219 — the readiness-probe cadence, machine file first, `WAIT_READY_INTERVAL` otherwise.

    Pure latency: the readiness VERDICT is the probe itself, and how long the wait may last is the
    separate `WAIT_READY_TIMEOUT`, which stays GATE-class and unsettable."""
    try:
        from lib import machine_settings      # deferred: keeps the hot import graph unchanged
        return float(machine_settings.resolve("lib.venue.WAIT_READY_INTERVAL",
                                              WAIT_READY_INTERVAL))
    except Exception:            # noqa: BLE001 — the settings STACK is never a
                                 # prerequisite either (SPEC-0193 rule 6 — the
                                 # `remote_workers_override` precedent)
        return WAIT_READY_INTERVAL

WAIT_READY_TIMEOUT = 300          # snapshot raise->ready measured 47-62 s


class VenueError(RuntimeError):
    """A venue refusal. Its message is built from status/code/message only — never the token."""


class VenueQuotaRefused(VenueError):
    """The provider's dedicated-core quota is exhausted (rule 6: snapshot -> delete -> raise)."""


def _die_msg(*parts) -> str:
    return " ".join(str(p) for p in parts if p)


# ── Record ────────────────────────────────────────────────────────────────────────────────────
def resolve_record_path(env=None) -> Path:
    """The ONE resolution site for the venue record.

    `YITC_VENUE_RECORD` wins, realpath'd; otherwise the record sits BESIDE `machine-settings.json`
    in the machine-scoped coordination home — DERIVED from `machine_settings.resolve_settings_path`
    rather than restated, so no SECOND host literal is minted (that module derives its own default
    from `cross.resolve_log_path` for exactly this reason, and inheriting it inherits its overrides
    for free).
    """
    env = os.environ if env is None else env
    override = (env.get(RECORD_ENV) or "").strip()
    if override:
        return Path(os.path.realpath(override))
    from lib import machine_settings   # deferred: the settings module pulls in the cross/journal stack
    return Path(machine_settings.resolve_settings_path(env)).parent / RECORD_FILENAME


def read_record(env=None) -> tuple:
    """(record | None, reason). A MISSING file and an UNPARSEABLE one BOTH read ABSENT — the
    unparseable one with a reason string the caller reports once (SPEC-0203 rule 1: fail closed
    toward the known-good local path; the box is not yet trusted, so «absent» is the safe reading,
    and a record honoured because nobody looked at why it failed to parse is the unsafe one)."""
    path = resolve_record_path(env)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, ""
    except OSError as exc:
        return None, f"the venue record at {path} could not be read ({exc.__class__.__name__})"
    try:
        obj = json.loads(text)
    except ValueError as exc:
        return None, f"the venue record at {path} does not parse as JSON ({exc}) — read as ABSENT"
    if not isinstance(obj, dict):
        return None, f"the venue record at {path} is not a JSON object — read as ABSENT"
    return obj, ""


def write_record(record: dict, env=None) -> Path:
    """Atomic (tmp + os.replace) and 0600 — the record carries an ssh identity and a box address."""
    path = resolve_record_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".venue-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def clear_record(env=None) -> bool:
    """Idempotent — returns whether a record was actually there to remove."""
    path = resolve_record_path(env)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def build_record(*, box, server_id, snapshot_id, fingerprint, published_at,
                 session_ref, task=None, checkout_root=None, ssh_user=BOX_USER,
                 ssh_identity=SSH_KEY_NAME) -> dict:
    """Rule 1's field list, and ONLY it: discovery/config state, never a verdict or a result.
    `cores` + `legs` are lifted out of the fingerprint because rule 5's `derive_remote_w` consumes
    them (T-12195) and a reader must not have to re-open the fingerprint to find the W inputs."""
    fp = fingerprint or {}
    return {
        "schema": RECORD_SCHEMA,
        "box": box,
        "ssh_user": ssh_user,
        "ssh_identity": ssh_identity,
        "server_id": server_id,
        "snapshot_id": snapshot_id,
        "checkout_root": checkout_root or remote_verify.BOX_VENUE_DIR,
        "fingerprint": fp,
        "cores": fp.get("cores"),
        "legs": len(remote_verify.LEGS),
        "published_at": published_at,
        "published_by": {"session_ref": session_ref, "task": task},
    }


# ── Provider client ───────────────────────────────────────────────────────────────────────────
def _token(env=None) -> str:
    """Read at the request seam ONLY. The return value goes straight into a header and is never
    stored, printed, journaled or put into an exception message (AC4)."""
    env = os.environ if env is None else env
    path = (env.get(TOKEN_FILE_ENV) or "").strip() or TOKEN_FILE_DEFAULT
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise VenueError(f"cannot read the provider API token at {path} "
                         f"({exc.__class__.__name__}) — the token lives in secrets/ only") from None
    if not value:
        raise VenueError(f"the provider API token at {path} is empty")
    return value


def _api(method: str, path: str, body: dict | None = None, *, env=None, timeout=API_TIMEOUT):
    """(status, parsed). Raises VenueError on a transport fault; an HTTP error is RETURNED with its
    parsed body so the caller can classify it (the quota refusal needs the provider's error code)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(API_BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + _token(env))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except ValueError:
            parsed = {"error": {"code": "unparseable", "message": raw[:300]}}
        return exc.code, parsed
    except Exception as exc:            # transport: never carries the header, only the class + path
        raise VenueError(f"provider request {method} {path} failed "
                         f"({exc.__class__.__name__}: {str(exc)[:200]})") from None


def _error_of(parsed) -> tuple:
    err = (parsed or {}).get("error") or {}
    return str(err.get("code") or "unknown"), str(err.get("message") or "no message")


def ssh_key_id(*, env=None, name: str = SSH_KEY_NAME):
    status, parsed = _api("GET", f"/ssh_keys?name={name}", env=env)
    if status != 200:
        code, msg = _error_of(parsed)
        raise VenueError(f"cannot list ssh keys (HTTP {status}) — {code}: {msg}")
    keys = parsed.get("ssh_keys") or []
    if not keys:
        raise VenueError(f"ssh key {name!r} is not in the provider project — upload it first")
    return keys[0].get("id")


QUOTA_REFUSAL_ORDER = (
    "This provider project holds ONE {server_type} at a time. The order is SNAPSHOT -> DELETE -> RAISE:\n"
    "  1. bin/yitc-v2 venue delete            # destroy the live box (its clone survives in the snapshot)\n"
    "  2. bin/yitc-v2 venue raise --from-image <snapshot-id>\n"
    "NOT retrying into the limit — a retry cannot succeed while a box of this class is live."
)


def create_server(name: str, image: str, *, env=None, server_type: str = SERVER_TYPE,
                  location: str = LOCATION, ssh_key: str = SSH_KEY_NAME) -> dict:
    """POST /servers from the seed SNAPSHOT (rule 3: a bare image is for seeding only, never a pass).

    On HTTP 403 `resource_limit_exceeded` raises `VenueQuotaRefused` carrying the recipe's exact
    snapshot -> delete -> raise order and does NOT retry: a retry cannot succeed while a box of this
    class is live, so retrying only spends time inside a billed hour."""
    key_id = ssh_key_id(env=env, name=ssh_key)
    body = {
        "name": name, "server_type": server_type, "image": image, "location": location,
        "ssh_keys": [key_id],
        "labels": {"purpose": "remote-verify-venue", "recipe": "venue-verb"},
    }
    status, parsed = _api("POST", "/servers", body, env=env)
    if status != 201:
        code, msg = _error_of(parsed)
        if status == 403 and code == "resource_limit_exceeded":
            raise VenueQuotaRefused(
                f"the provider project's dedicated-core quota is exhausted — {code}: {msg}\n"
                + QUOTA_REFUSAL_ORDER.format(server_type=server_type))
        raise VenueError(f"server create failed (HTTP {status}) — {code}: {msg}")
    server = parsed.get("server") or {}
    ip = (((server.get("public_net") or {}).get("ipv4") or {}).get("ip")) or ""
    return {"server_id": server.get("id"), "ip": ip, "image": image, "name": name}


def delete_server(server_id, *, env=None) -> int:
    status, parsed = _api("DELETE", f"/servers/{server_id}", env=env)
    if status not in (200, 202, 204, 404):
        code, msg = _error_of(parsed)
        raise VenueError(f"server delete failed (HTTP {status}) — {code}: {msg}")
    return status


def list_servers(*, env=None, label: str = "purpose=remote-verify-venue") -> list:
    """A READ — used to see whether a box of this class is already live before raising into the
    quota. Not journaled: `external_action` is for MUTATIONS (SPEC-0116)."""
    status, parsed = _api("GET", f"/servers?label_selector={label}", env=env)
    if status != 200:
        code, msg = _error_of(parsed)
        raise VenueError(f"cannot list servers (HTTP {status}) — {code}: {msg}")
    return parsed.get("servers") or []


# ── Bounded wait + readiness probe ────────────────────────────────────────────────────────────
def wait_ready(ip: str, *, user: str = BOX_USER, interval: "float | None" = None,
               timeout: float = WAIT_READY_TIMEOUT, _sleep=time.sleep, _now=time.monotonic) -> float:
    """THE bounded wait — polls `test -f ~/CLOUD-INIT-DONE` over ssh until it succeeds or the
    deadline passes. Returns the elapsed seconds; raises `VenueError` at the bound. No unbounded
    loop and no silent retry exists in this module.

    T-12219 — `interval` (how often it asks) resolves through the machine settings, `timeout` (the
    bound whose expiry DECLARES the box not ready) deliberately does not: the first is a latency
    value, the second is the verdict, and SPEC-0193 rule 4 refuses the second by class. The
    resolution happens HERE rather than as a module-level default, which is bound once at import and
    would never observe a later `config set`."""
    if interval is None:
        interval = wait_ready_interval()
    t0 = _now()
    last = ""
    while True:
        try:
            r = subprocess.run(remote_verify.ssh_argv(ip, "test -f ~/CLOUD-INIT-DONE", user=user),
                               text=True, capture_output=True, timeout=max(10.0, interval * 4))
            if r.returncode == 0:
                return _now() - t0
            last = (r.stderr or r.stdout or "").strip()[:200]
        except subprocess.TimeoutExpired:
            last = "ssh probe timed out"
        if _now() - t0 >= timeout:
            raise VenueError(f"bounded wait exceeded at seam 'ready' — no success within {timeout:g}s "
                             f"(last observed: {last or '<no output>'})")
        _sleep(interval)


#: The readiness expectation table — ONE declaration (the recipe's, whose doc mirrors it). Operators:
#: `true` | `eq` | `contains` | `ge`. The fd rows are DELIBERATELY ABSENT: `nofile` is judged by
#: `remote_verify.fingerprint_admits_pin`, whose docstring names THIS caller as its second moment.
#: Two spellings of a threshold are two thresholds, and the drift here is silent (T-12183 F1).
PROBE_EXPECTATIONS = (
    ("cloud_init_done", "true", None),
    ("os", "contains", "Ubuntu 24.04"),
    ("arch", "eq", "x86_64"),
    ("python", "ge", 3.12),
    ("git", "contains", "git version 2."),
    ("pytest", "contains", "pytest"),
    ("cores", "ge", 16),
    ("ram_mb", "ge", 32000),
    ("tmpfs_shm_mb", "ge", 1024),
    ("rsync", "true", None),
    ("clone_present", "true", None),
    ("clone_main", "contains", "refs/heads/main"),
)

#: The extra reads the shared fingerprint does not measure: cloud-init completion and the seeded
#: bare clone (rule 3). Measured in ONE ssh round beside `probe_fingerprint`, never a second probe.
_CLONE_SCRIPT = r"""python3 - <<'PY'
import json, os, subprocess
def sh(c):
    return subprocess.run(c, shell=True, text=True, capture_output=True).stdout.strip()
clone = os.path.expanduser("~/venue/repo.git")
print(json.dumps({
 "cloud_init_done": os.path.exists(os.path.expanduser("~/CLOUD-INIT-DONE")),
 "clone_present": os.path.isdir(clone),
 "clone_main": sh("git -C %s for-each-ref --format='%%(refname)' refs/heads/main" % clone),
 "clone_main_sha": sh("git -C %s rev-parse refs/heads/main 2>/dev/null" % clone)}))
PY"""


def measure_fingerprint(ip: str, *, user: str = BOX_USER, timeout: float = 60) -> dict:
    """The venue's fingerprint = `remote_verify.probe_fingerprint` (REUSED, not re-spelled) plus the
    clone/cloud-init rows that reader does not measure."""
    fp = dict(remote_verify.probe_fingerprint(ip, user=user, timeout=timeout))
    r = subprocess.run(remote_verify.ssh_argv(ip, _CLONE_SCRIPT, user=user),
                       text=True, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise VenueError(f"the clone probe did not run on the box (rc={r.returncode}): "
                         f"{(r.stderr or r.stdout)[:200]}")
    try:
        fp.update(json.loads(r.stdout))
    except ValueError:
        raise VenueError("the box returned an unparseable clone probe") from None
    return fp


def _version_tuple(value):
    """The leading dotted-number run of `value` as a tuple of ints, or None when there is none.
    Component-wise so 3.9 < 3.12 (the float reading has it backwards), and equal-length-padded so
    "3.12.3" >= "3.12" holds. A bare number ("16", 32000) is the one-component case."""
    m = re.match(r"\s*(-?\d+(?:\.\d+)*)", str(value))
    if m is None:
        return None
    return tuple(int(part) for part in m.group(1).split("."))


def _holds(actual, op, expected) -> bool:
    if op == "true":
        return actual is True or str(actual).lower() == "true"
    if op == "eq":
        return str(actual) == str(expected)
    if op == "contains":
        return str(expected) in str(actual or "")
    if op == "ge":
        # DOTTED-VERSION comparison, deliberately: the measured values are version strings as often
        # as they are numbers ("3.12.3"), and a strict float() reads every one of them as a failure —
        # which fails CLOSED in the wrong direction, refusing a perfectly ready box. But reading the
        # leading number as ONE float is worse than either: it fails OPEN, because float("3.9") is
        # GREATER than float("3.12") while python 3.9 is BELOW the declared 3.12 floor. So each side
        # is compared COMPONENT-WISE as a tuple of ints — "3.12.3" >= "3.12" and "3.9.7" does NOT.
        a, e = _version_tuple(actual), _version_tuple(expected)
        if a is None or e is None:
            return False
        return a >= e
    raise VenueError(f"unknown probe operator {op!r}")


def probe_readiness(fingerprint: dict | None) -> list:
    """The FAILURES, in table order: `[{field, op, expected, actual}]`. Empty list = GREEN.

    The fd row delegates to `remote_verify.fingerprint_admits_pin` — the ONE home of that predicate
    (rule 5) — and is reported under a synthetic `nofile` field so a refusal still names what failed.
    """
    fp = fingerprint or {}
    failures = []
    for field, op, expected in PROBE_EXPECTATIONS:
        actual = fp.get(field)
        if not _holds(actual, op, expected):
            failures.append({"field": field, "op": op,
                             "expected": "" if expected is None else expected,
                             "actual": actual})
    if not remote_verify.fingerprint_admits_pin(fp):
        failures.append({"field": "nofile", "op": "ge", "expected": remote_verify.VENUE_NOFILE,
                         "actual": {"nofile_soft": fp.get("nofile_soft"),
                                    "nofile_hard": fp.get("nofile_hard")}})
    return failures


def describe_failure(failure: dict) -> str:
    return (f"field {failure['field']!r} — expected [{failure['op']} {failure['expected']}], "
            f"got [{failure['actual']}]")


def main_mirror_state(fingerprint: dict | None, *, repo_root, main_ref: str = "main") -> dict:
    """REPORT-ONLY (T-12296): what the box clone's `refs/heads/main` holds versus the host's current
    `main` — the ref `remote_verify.ship_trees` now mirrors on every request.

    WHY THIS IS NOT A READINESS ROW. `PROBE_EXPECTATIONS` asserts only that `clone_main` CONTAINS
    `refs/heads/main` (that the ref EXISTS), never what it points at, and that stays right: a stale
    clone main is not an UNREADY box, it is a box the mirror ship heals on its first request. Making
    it a gate would REFUSE a box the fix repairs — failing closed in the wrong direction. What was
    missing was not a gate but VISIBILITY: the staleness was already measured at publish and thrown
    away, so it was first met as a failing pinned test on someone else's land (T-12287).

    `behind` is THREE-VALUED, like every other reader in this module: `0` when the two agree, a
    positive int when the clone's sha is a resolvable ANCESTOR of the host's main (how many commits
    it trails by), and `None` when we COULD NOT TELL — an unresolvable `main`, an unreadable clone
    sha, or a clone sha this host does not have (a re-seeded or foreign snapshot). "Not behind" and
    "we do not know" are different facts and only one of them is a number.

    Never raises. A report that can fail the verb it reports on is worse than the fact it reports."""
    fp = fingerprint or {}
    clone_sha = (fp.get("clone_main_sha") or "").strip() or None

    def _run(*argv):
        try:
            return subprocess.run(["git", "-C", str(repo_root), *argv], text=True,
                                  capture_output=True, timeout=30)
        except Exception:                     # noqa: BLE001 — a reporter never raises past its caller
            return None

    def _git(*argv):
        r = _run(*argv)
        return (r.stdout.strip() or None) if r is not None and r.returncode == 0 else None

    host_sha = _git("rev-parse", main_ref)
    behind = None
    if clone_sha and host_sha:
        if clone_sha == host_sha:
            behind = 0
        else:
            # ANCESTRY FIRST, DISTANCE SECOND — they are different questions and `rev-list --count`
            # answers only the second. `rev-list --count <clone>..<host>` counts what is reachable
            # from the host main but not from the clone's, which is POSITIVE for a DIVERGED history
            # too: a clone sha on an independent line that the host merely happens to have in its
            # object database would be reported as "N commits behind" when it is not behind at all.
            # So `merge-base --is-ancestor` decides whether "behind" is even the right word, and the
            # count is taken only once it is. Anything else — diverged, ahead, or an unknown sha —
            # is `None`, "we could not tell", never a number.
            anc = _run("merge-base", "--is-ancestor", clone_sha, host_sha)
            if anc is not None and anc.returncode == 0:
                count = _git("rev-list", "--count", f"{clone_sha}..{host_sha}")
                try:
                    behind = int(count) or None
                except (TypeError, ValueError):
                    behind = None
    return {"clone_main_sha": clone_sha, "host_main_sha": host_sha, "behind": behind}
