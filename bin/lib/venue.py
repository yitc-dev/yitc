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

THE PROVIDER IS A CONFIG BINDING, NOT CODE (T-13000, CHARTER §P4b). WHICH hosting provider rents
the box — its API endpoint, token secret name, box class, location and ssh key — is read from the
venue binding (`bin/venue-config.yaml`, `YITC_VENUE_CONFIG` overrides) at CALL time. The binding is
placed v2-self, so a release carries none: with no binding the venue is OPTIONAL and NOT CONFIGURED,
every provider call refuses by name, and routing ignores any record (`routing_record`) so every
verify runs locally. The client shape is ported from `dev-utilities/venue-seed-recipe.sh` (T-12193):
raise-from-image / readiness-probe / delete, the quota refusal and the bounded-wait primitive.

THE TOKEN. Read from the binding's `token_secret` under the host's secrets dir at the request seam ONLY, never returned
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

# ── The seed record (rule 1's sibling, T-12668) ───────────────────────────────────────────────
#: The ONE recorded home of the canonical seed-snapshot id `venue raise` raises from when no
#: `--from-image` is given. It sits BESIDE the venue record (same home, same override — there is
#: deliberately NO second env knob: `YITC_VENUE_RECORD` already moves the home, so a test's temp dir
#: carries both files) and OUTLIVES it: the venue record is cleared at every unpublish, while the
#: seed id must survive a teardown to be read by the next raise. It is written ONLY by `venue seed`
#: — promotion is an explicit operator act after a raise from the new snapshot verified, never a
#: side effect of publish and never a pick among provider snapshots by description (the 2026-09-16
#: archaeology this record exists to end: three candidates, one an obsolete trial, one a broken
#: crash-consistent image).
SEED_SCHEMA = "yitc.verify-seed/1"
SEED_FILENAME = "verify-seed.json"
#: How the raise names the source of an id that did not come from the record.
SEED_SOURCE_FLAG = "--from-image"

# ── The provider (rule 6) — a CONFIG BINDING, never a constant (T-13000) ────────────────────────
TOKEN_FILE_ENV = "VENUE_TOKEN_FILE"
CONFIG_ENV = "YITC_VENUE_CONFIG"
#: The engine's own binding file. Resolved beside THIS module's bin/, so it is the ENGINE's binding
#: whichever repo a `-C` session reads; `YITC_VENUE_CONFIG` overrides (a test's temp file).
CONFIG_DEFAULT = Path(__file__).resolve().parent.parent / "venue-config.yaml"
BINDING_KEYS = ("provider", "api_base", "token_secret", "server_type", "location", "ssh_key")
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

#: THE ONE STALENESS BOUND (SPEC-0203 rule 6, T-12669): a seed snapshot whose delta push to the box
#: takes longer than this many seconds is STALE — refresh it at the next teardown. It is a refresh
#: TRIGGER, derived as ~2.5x the measured fresh-snapshot delta-push band of 42-48 s (T-12193 AC2),
#: deliberately far below the 900 s transport ceiling past which the rule-3 mirror cannot heal a lag
#: at all (`remote_verify.SHIP_PUSH_TIMEOUT_S`). The DECLARATION of record is the recipe script's
#: `REFRESH_BOUND_S` (`dev-utilities/venue-seed-recipe.sh`), which is what measures it; this copy
#: exists so `venue publish` can STATE the bound in its lag WARN, and
#: `tests/test_t12193_venue_seed_recipe.py` pins the two (and the doc + the spec) equal, so no
#: surface can be edited alone. `publish` WARNS on it and never refuses: since T-12804 it MEASURES
#: the mirror push itself, and a push past this bound means the SNAPSHOT is stale, not that the box is
#: (the clone is already healed). The refuse-gate is the transport ceiling (SPEC-0203 rule 6).
REFRESH_BOUND_S = 120


class VenueError(RuntimeError):
    """A venue refusal. Its message is built from status/code/message only — never the token."""


class VenueQuotaRefused(VenueError):
    """The provider's dedicated-core quota is exhausted (rule 6: snapshot -> delete -> raise)."""


def resolve_config_path(env=None) -> Path:
    env = os.environ if env is None else env
    override = (env.get(CONFIG_ENV) or "").strip()
    return Path(os.path.realpath(override)) if override else CONFIG_DEFAULT


def binding(env=None) -> "dict | None":
    """The provider binding, or None when the venue is NOT CONFIGURED — a missing, empty,
    unparseable or incomplete file all read None (fail closed: a half binding never reaches the
    provider). Read at call time, never cached, so a test's `YITC_VENUE_CONFIG` is always honoured."""
    path = resolve_config_path(env)
    try:
        from lib import state         # deferred: the parser pulls in nothing the hot path needs
        data = state.load_str(path.read_text(encoding="utf-8")) or {}
    except Exception:                 # noqa: BLE001 — absent/unreadable/unparseable = not configured
        return None
    if not isinstance(data, dict):
        return None
    out = {k: str(data.get(k) or "").strip() for k in BINDING_KEYS}
    return out if all(out.values()) else None


def not_configured_message(env=None) -> str:
    return (f"the verify venue is OPTIONAL and NOT CONFIGURED on this machine (no complete provider "
            f"binding at {resolve_config_path(env)}) — every verify pass runs LOCALLY. To switch it "
            f"on, see patterns/verify-venue-when-it-pays.md.")


def _require_binding(env=None) -> dict:
    b = binding(env)
    if b is None:
        raise VenueError(not_configured_message(env))
    return b


def token_path(env=None) -> "str | None":
    """`VENUE_TOKEN_FILE` wins; else the binding's `token_secret` under the host's secrets dir
    (DERIVED via `host_paths.host_home()`, T-12024 — never a host literal); None when unbound."""
    env = os.environ if env is None else env
    override = (env.get(TOKEN_FILE_ENV) or "").strip()
    if override:
        return override
    b = binding(env)
    return str(host_paths.host_home() / "secrets" / b["token_secret"]) if b else None


def provider_configured(env=None) -> bool:
    """A machine has adopted the venue's provider half iff a binding exists AND its token file does."""
    if binding(env) is None:
        return False
    path = token_path(env)
    return bool(path) and Path(path).is_file()


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


def routing_record(env=None) -> tuple:
    """(record | None, note) for the ROUTING seams (Stage-6 + land) — `read_record` when the venue is
    configured, else (None, note): with NO binding the venue is optional and not configured, so a
    stale or hand-placed record is IGNORED and every pass runs locally (T-13000 AC2)."""
    if binding(env) is None:
        rec, _ = read_record(env)
        return None, (not_configured_message(env)
                      + (" A venue record is present and IGNORED." if rec is not None else ""))
    return read_record(env)


def write_record(record: dict, env=None) -> Path:
    """Atomic (tmp + os.replace) and 0600 — the record carries an ssh identity and a box address."""
    return _write_json_0600(resolve_record_path(env), record)


def _write_json_0600(path: Path, obj: dict) -> Path:
    """The ONE atomic 0600 JSON writer both machine-scoped venue files use (tmp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".venue-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, sort_keys=True)
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
                 ssh_identity=None) -> dict:
    """Rule 1's field list, and ONLY it: discovery/config state, never a verdict or a result.
    `cores` + `legs` are lifted out of the fingerprint because rule 5's `derive_remote_w` consumes
    them (T-12195) and a reader must not have to re-open the fingerprint to find the W inputs."""
    fp = fingerprint or {}
    if ssh_identity is None:
        ssh_identity = (binding() or {}).get("ssh_key")
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


# ── Seed record ───────────────────────────────────────────────────────────────────────────────
def resolve_seed_path(env=None) -> Path:
    """Beside the venue record, under the SAME override — derived, never a second literal."""
    return resolve_record_path(env).parent / SEED_FILENAME


def build_seed(*, snapshot_id, clone_main_sha, recorded_at, session_ref, task=None,
               note=None) -> dict:
    """The seed record: the canonical id + its provenance. No verdict, no result (rule 1)."""
    return {
        "schema": SEED_SCHEMA,
        "snapshot_id": str(snapshot_id),
        "clone_main_sha": clone_main_sha,
        "recorded_at": recorded_at,
        "recorded_by": {"session_ref": session_ref, "task": task},
        "note": note,
    }


def _seed_defect(obj) -> str:
    """'' when `obj` is a well-formed seed record, else the exact defect — so a malformed carrier
    is never confused with a missing one, and a caller's refusal can name what is wrong."""
    if not isinstance(obj, dict):
        return "is not a JSON object"
    if obj.get("schema") != SEED_SCHEMA:
        return f"carries schema {obj.get('schema')!r}, not {SEED_SCHEMA!r}"
    sid = obj.get("snapshot_id")
    if not isinstance(sid, str) or not sid.strip() or not sid.strip().isdigit():
        return f"carries snapshot_id {sid!r}, not a non-empty numeric id"
    return ""


def _read_seed_file(path: Path, what: str) -> tuple:
    """(seed | None, reason) for ONE seed-schema file — the shared fail-closed reader of the
    canonical record and the candidate (T-12885). MISSING reads ABSENT with no reason; unreadable,
    unparseable and MALFORMED read ABSENT with a reason naming the path and the defect."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, ""
    except OSError as exc:
        return None, f"the {what} at {path} could not be read ({exc.__class__.__name__})"
    try:
        obj = json.loads(text)
    except ValueError as exc:
        return None, f"the {what} at {path} does not parse as JSON ({exc})"
    defect = _seed_defect(obj)
    if defect:
        return None, f"the {what} at {path} {defect}"
    return obj, ""


def read_seed(env=None) -> tuple:
    """(seed | None, reason). MISSING, unreadable, unparseable and MALFORMED all read ABSENT, and
    every non-missing case carries a reason naming the path and the defect. Fail-closed in the
    direction that matters here: an absent/malformed seed means `venue raise` REFUSES, never picks."""
    return _read_seed_file(resolve_seed_path(env), "seed record")


def write_seed(seed: dict, env=None) -> Path:
    """Atomic + 0600, the venue record's own writer. Refuses a malformed seed at the door."""
    defect = _seed_defect(seed)
    if defect:
        raise VenueError(f"refusing to write a seed record that {defect}")
    return _write_json_0600(resolve_seed_path(env), seed)


# ── The seed CANDIDATE (T-12885) ──────────────────────────────────────────────────────────────
#: The teardown refresh leg's new image, recorded by `venue seed --candidate` and NOT yet verified.
#: A sibling of the canonical record in the same home (same schema, same writer, same override): a
#: bare `venue raise` raises FROM it, promotes it to canonical on a GREEN readiness probe, and on a
#: failed raise rejects it (journal row + file removed) and falls back to the canonical seed.
SEED_CANDIDATE_FILENAME = "verify-seed-candidate.json"


def resolve_seed_candidate_path(env=None) -> Path:
    return resolve_record_path(env).parent / SEED_CANDIDATE_FILENAME


def read_seed_candidate(env=None) -> tuple:
    """(candidate | None, reason) — the same fail-closed reader as the canonical record."""
    return _read_seed_file(resolve_seed_candidate_path(env), "seed candidate")


def write_seed_candidate(seed: dict, env=None) -> Path:
    defect = _seed_defect(seed)
    if defect:
        raise VenueError(f"refusing to write a seed candidate that {defect}")
    return _write_json_0600(resolve_seed_candidate_path(env), seed)


def clear_seed_candidate(env=None) -> bool:
    """Remove the candidate; True when one was removed (missing is not an error)."""
    try:
        resolve_seed_candidate_path(env).unlink()
        return True
    except FileNotFoundError:
        return False


def seed_record_hint(env=None) -> str:
    """WHAT to record and WHERE — the one sentence every seed refusal ends with."""
    return (f"record the canonical seed snapshot with `bin/yitc-v2 venue seed --snapshot-id <id>` "
            f"(writes {resolve_seed_path(env)}); an explicit `venue raise {SEED_SOURCE_FLAG} <id>` "
            f"overrides it for verifying a NEW snapshot before promoting it")


def resolve_seed_snapshot(explicit, env=None) -> tuple:
    """(snapshot_id, source, role) — the raise's ONE resolution site (T-12668 AC1-AC3, T-12885).

    An explicit id WINS (role `explicit`, source = the flag name); else a well-formed CANDIDATE
    (role `candidate`, source = its path — the raise verifies it and promotes it on GREEN); else the
    recorded canonical seed (role `canonical`, source = its path); else `VenueError` naming what to
    record and where. A MALFORMED candidate never blocks a raise: it is named in the source and the
    canonical seed is used. It never lists provider snapshots: choosing among them by description is
    exactly the archaeology that raised a broken clone on 2026-09-16."""
    env = os.environ if env is None else env
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip(), SEED_SOURCE_FLAG, "explicit"
    candidate, cand_reason = read_seed_candidate(env)
    if candidate is not None:
        return candidate["snapshot_id"], str(resolve_seed_candidate_path(env)), "candidate"
    seed, reason = read_seed(env)
    if seed is None:
        path = resolve_seed_path(env)
        lead = reason or f"no canonical seed snapshot is recorded (no seed record at {path})"
        raise VenueError(f"{lead} — REFUSING to pick a snapshot; {seed_record_hint(env)}")
    source = str(resolve_seed_path(env))
    if cand_reason:
        source += f"; IGNORED {cand_reason}"
    return seed["snapshot_id"], source, "canonical"


# ── Provider client ───────────────────────────────────────────────────────────────────────────
def _token(env=None) -> str:
    """Read at the request seam ONLY. The return value goes straight into a header and is never
    stored, printed, journaled or put into an exception message (AC4)."""
    path = token_path(env)
    if not path:
        raise VenueError(not_configured_message(env))
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
    api_base = _require_binding(env)["api_base"].rstrip("/")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(api_base + path, data=data, method=method)
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


def ssh_key_id(*, env=None, name: "str | None" = None):
    name = name or _require_binding(env)["ssh_key"]
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


def create_server(name: str, image: str, *, env=None, server_type: "str | None" = None,
                  location: "str | None" = None, ssh_key: "str | None" = None) -> dict:
    """POST /servers from the seed SNAPSHOT (rule 3: a bare image is for seeding only, never a pass).

    On HTTP 403 `resource_limit_exceeded` raises `VenueQuotaRefused` carrying the recipe's exact
    snapshot -> delete -> raise order and does NOT retry: a retry cannot succeed while a box of this
    class is live, so retrying only spends time inside a billed hour."""
    b = _require_binding(env)
    server_type, location = server_type or b["server_type"], location or b["location"]
    key_id = ssh_key_id(env=env, name=ssh_key or b["ssh_key"])
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
    ("jq", "true", None),
    ("clone_present", "true", None),
    ("clone_main", "contains", "refs/heads/main"),
)

#: The extra reads the shared fingerprint does not measure: cloud-init completion, the seeded bare
#: clone (rule 3) and `jq` — a host tool the suite needs (a recipe test sources the jq-using script);
#: unmeasured, a jq-less snapshot probed GREEN and was published (T-12962). Measured in ONE ssh round beside `probe_fingerprint`, never a second probe.
_CLONE_SCRIPT = r"""python3 - <<'PY'
import json, os, shutil, subprocess
def sh(c):
    return subprocess.run(c, shell=True, text=True, capture_output=True).stdout.strip()
clone = os.path.expanduser("~/venue/repo.git")
print(json.dumps({
 "cloud_init_done": os.path.exists(os.path.expanduser("~/CLOUD-INIT-DONE")),
 "jq": shutil.which("jq") is not None,
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
    `main` — the ref `remote_verify.ship_trees` now mirrors on every request. Since T-12804 `venue
    publish` reads it for the PRE-mirror lag only (`clone_main_behind_before`): the publish gate is the
    MEASURED mirror push, never this commit count (SPEC-0203 rule 6).

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
