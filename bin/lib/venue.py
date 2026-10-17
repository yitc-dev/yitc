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

import base64
import io
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
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


def record_transition_lock(env=None):
    """T-13976 (SPEC-1032 rule 6) — the ONE machine-wide lock over a publish's transition: held from
    its authoritative read of the record through its write. Two publishers of DIFFERENT repositories
    each hold only their own repository's land reservation, so without this both could pass the
    check and the later write silently replace the earlier record. An exclusive flock on a file
    beside the record (the record's own directory), released when the context exits."""
    import contextlib
    import fcntl

    @contextlib.contextmanager
    def _held():
        path = resolve_record_path(env)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path.parent / ".verify-venue.lock"), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)
    return _held()


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
                 ssh_identity=None, serves=None) -> dict:
    """Rule 1's field list (with SPEC-1032's `serves`), and ONLY it: discovery/config state, never a
    verdict or a result.
    `cores` + `legs` are lifted out of the fingerprint because rule 5's `derive_remote_w` consumes
    them (T-12195) and a reader must not have to re-open the fingerprint to find the W inputs.
    `serves` (T-13976, SPEC-1032 rule 6) — the real path of the consumer repository's git common dir
    — is written only for a venue published for a consumer; a kernel record carries no such key."""
    fp = fingerprint or {}
    if ssh_identity is None:
        ssh_identity = (binding() or {}).get("ssh_key")
    return {
        **({"serves": serves} if serves else {}),
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
                  location: "str | None" = None, ssh_key: "str | None" = None,
                  user_data: "str | None" = None, labels: "dict | None" = None) -> dict:
    """POST /servers from the seed SNAPSHOT (rule 3: a bare image is for seeding only, never a pass).

    `user_data` and `labels` are given ONLY by the image build (`build_consumer_image`, T-13977),
    which raises a BARE image to SEED it — the recipe's `create_box ... WITH_USER_DATA` — and tags the
    box with its run's own label, so a box whose create response is lost can still be found and
    deleted. This stays the ONE creation path, so the build meets the same quota refusal.

    On HTTP 403 `resource_limit_exceeded` raises `VenueQuotaRefused` carrying the recipe's exact
    snapshot -> delete -> raise order and does NOT retry: a retry cannot succeed while a box of this
    class is live, so retrying only spends time inside a billed hour."""
    b = _require_binding(env)
    server_type, location = server_type or b["server_type"], location or b["location"]
    key_id = ssh_key_id(env=env, name=ssh_key or b["ssh_key"])
    body = {
        "name": name, "server_type": server_type, "image": image, "location": location,
        "ssh_keys": [key_id],
        "labels": {"purpose": "remote-verify-venue", "recipe": "venue-verb", **(labels or {})},
    }
    if user_data is not None:
        body["user_data"] = user_data
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


# ── The consumer image build (SPEC-1032 rule 6 image, T-13977) ────────────────────────────────
# WHAT THIS IS. `venue seed --build -C <consumer> --provision <script>`: the kernel's TRAVELING build
# of a consumer's first seed snapshot. The kernel's own image recipe (its seed-recipe script) is
# v2-self and never travels, so an install had no way to build its first image. The
# build is the recipe's `seed` shape PORTED (not shared — the recipe file is untouched and keeps its
# behaviour): a BARE image with the recipe's base setup, then the project's own provisioning script,
# a FULL-HISTORY bare clone of the consumer, the host's engine release at the host's absolute path,
# fstrim, a quiesced snapshot — and the box deleted on EVERY exit (a started hour is billed whole).
# The CLI host (`cmd_venue_seed`) owns the journal rows and the seed record write, as for every verb.

#: The base package set of a build box — the recipe's `SEED_PACKAGES`, PORTED: the recipe is v2-self
#: and never travels, this build does. `tests/test_t13977_venue_seed_build.py` pins the two equal so
#: neither moves alone. The consumer's OWN environment is its provisioning script's business.
BUILD_BASE_PACKAGES = ("git", "python3", "python3-venv", "python3-pip", "python3-pytest",
                       "python3-yaml", "curl", "ca-certificates", "rsync", "jq")
#: The bare image a build box starts from — the recipe's `BARE_IMAGE` default (pinned equal), and
#: the OS the readiness probe expects (`PROBE_EXPECTATIONS`: Ubuntu 24.04).
BUILD_BARE_IMAGE = "ubuntu-24.04"


def build_base_setup(*, user: str = BOX_USER, nofile: "int | None" = None,
                     packages=BUILD_BASE_PACKAGES) -> str:
    """The build box's cloud-init `user_data` — the recipe's `cloud_init`, line for line (comments
    aside): the package set, the fd limits the venue pins (`remote_verify.VENUE_NOFILE`, SPEC-1029
    rule 5) with pam_limits on for ssh, the box user with sudo and the root ssh keys, and the
    CLOUD-INIT-DONE marker `wait_ready` polls. `flock` is checked after it, by the `base-check` step."""
    nofile = remote_verify.VENUE_NOFILE if nofile is None else int(nofile)
    return "\n".join((
        "#!/bin/bash",
        "set -euxo pipefail",
        "export DEBIAN_FRONTEND=noninteractive",
        "apt-get update -q",
        f"apt-get install -y -q {' '.join(packages)}",
        f"printf '* soft nofile {nofile}\\n* hard nofile {nofile}\\nroot soft nofile {nofile}\\n"
        f"root hard nofile {nofile}\\n' > /etc/security/limits.d/90-yitc-venue.conf",
        "grep -q pam_limits /etc/pam.d/sshd || echo 'session required pam_limits.so' >> /etc/pam.d/sshd",
        f"useradd -m -d /home/{user} -s /bin/bash {user} || true",
        f"mkdir -p /home/{user}/.ssh && cp /root/.ssh/authorized_keys /home/{user}/.ssh/",
        f"chown -R {user}:{user} /home/{user}/.ssh && chmod 700 /home/{user}/.ssh",
        f"echo '{user} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{user}",
        f"chown -R {user}:{user} /home/{user}",
        f"touch /home/{user}/CLOUD-INIT-DONE && chown {user}:{user} /home/{user}/CLOUD-INIT-DONE",
        ""))


def _build_git(repo, *argv, timeout: float = 120):
    """ONE guarded git read of a host checkout for the build's pre-flight (the SPEC-0188 rule 7 child
    env). Returns the CompletedProcess, or None when git could not be run at all."""
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    try:
        return subprocess.run(["git", "-C", str(repo), *argv], text=True, capture_output=True,
                              timeout=timeout, env=_git_env._git_child_env())
    except Exception:                          # noqa: BLE001 — a launch fault is named by the caller
        return None


def _build_git_out(repo, *argv) -> "str | None":
    r = _build_git(repo, *argv)
    return r.stdout.strip() if r is not None and r.returncode == 0 else None


def _engine_release(engine: Path) -> dict:
    """The engine as a PUBLISHED RELEASE (SPEC-0195): its tracked tree, which must re-digest to the
    `tree_digest` its own `release-manifest.yaml` declares. Reuses the release module's ONE tree
    reader and ONE digest (`read_release_tree`, `tree_digest`) — the same pair `verify_release`
    runs — so what ships is provably the kernel-realm cut that was published, and a workshop
    checkout (no manifest; or v2-self files the manifest's digest does not cover) is refused. Returns
    {tree, exec_paths, source_ref, tree_digest}; raises `VenueError` naming the cause."""
    from lib import release as _release   # deferred: the release module is a cold path here
    exec_paths: set = set()
    try:
        tree = _release.read_release_tree(engine, exec_paths=exec_paths)
    except Exception as exc:              # noqa: BLE001 — an unreadable root is a refusal, not a crash
        raise VenueError(f"the engine root {engine} could not be read as a release tree "
                         f"({exc.__class__.__name__})") from None
    manifest = _release._parse_yaml_blob(tree.get(_release.MANIFEST_FILENAME))
    if not manifest:
        raise VenueError(f"the engine root {engine} is not a published release (no readable "
                         f"{_release.MANIFEST_FILENAME}) — the image carries the RELEASE this host "
                         f"runs, never a workshop checkout")
    excludes = [str(x) for x in (manifest.get("digest_excludes") or [_release.MANIFEST_FILENAME])]
    declared = str(manifest.get("tree_digest") or "")
    recomputed = _release.tree_digest(tree, excludes=excludes)
    if not declared or recomputed != declared:
        raise VenueError(f"the engine release at {engine} does not match its manifest — the manifest "
                         f"says {declared[:16] or '<unset>'}…, the tracked tree hashes to "
                         f"{recomputed[:16]}… (a modified or added file); the image ships only the "
                         f"release as published")
    return {"tree": tree, "exec_paths": exec_paths,
            "source_ref": str(manifest.get("source_ref") or "?"), "tree_digest": declared}


def build_preflight(*, repo_root, engine_root, provision, pinned: bool = False, env=None) -> dict:
    """Every refusal the build can decide BEFORE a provider call, so a refused build costs nothing.

    Returns {repo_root, engine_root, engine_path, engine, provision_path, provision_rel, main_sha};
    raises `VenueError` naming the one cause. The checks, in order: a complete binding; a CONSUMER
    (`-C`; the kernel's own image is the recipe's); the provisioning script is a FILE inside the
    consumer repository (a `..` or a symlink out of it is outside); `refs/heads/main` resolves; the
    repository is not shallow (SPEC-1032 rule 6: never shallow); the engine is not a declared pin's
    release cache (that tree lives under the temp dir, which a booted image does not keep); the
    engine root is a PUBLISHED RELEASE whose tracked tree matches its manifest (`_engine_release`)."""
    _require_binding(env)
    repo = Path(os.path.realpath(str(repo_root)))
    engine = Path(os.path.realpath(str(engine_root)))
    if repo == engine:
        raise VenueError("the image build is for a CONSUMER (`-C <consumer>`); this engine's own "
                         "image is built by its own seed recipe, which does not travel")
    if provision is None or not str(provision).strip():
        raise VenueError("no provisioning script was named (--provision <path in the consumer repo>)")
    raw = Path(str(provision))
    candidate = raw if raw.is_absolute() else repo / raw
    prov = Path(os.path.realpath(str(candidate)))
    if prov != repo and repo not in prov.parents:
        raise VenueError(f"the provisioning script {provision!r} resolves to {prov}, OUTSIDE the "
                         f"consumer repository {repo} — it must be the project's own file")
    if not prov.is_file():
        raise VenueError(f"the provisioning script {prov} is not a file")
    main_sha = _build_git_out(repo, "rev-parse", "--verify", "-q", "refs/heads/main^{commit}")
    if not main_sha:
        raise VenueError(f"the consumer repository {repo} has no refs/heads/main — nothing to clone")
    shallow = _build_git_out(repo, "rev-parse", "--is-shallow-repository")
    if shallow != "false":
        raise VenueError(f"the consumer repository {repo} is SHALLOW (or its depth could not be read: "
                         f"{shallow!r}) — the image needs its FULL history (SPEC-1032 rule 6)")
    if pinned:
        raise VenueError(f"this consumer declares an engine pin; the engine resolved to the release "
                         f"cache {engine}, which this build does not ship — run it from the install "
                         f"the pin names")
    return {"repo_root": repo, "engine_root": engine, "engine_path": str(engine),
            "engine": _engine_release(engine),
            "provision_path": prov, "provision_rel": str(prov.relative_to(repo)),
            "main_sha": main_sha}


def _q(value) -> str:
    import shlex
    return shlex.quote(str(value))


def build_plan(pre: dict, *, box: str = "<box>", server_id="<server-id>", user: str = BOX_USER,
               nofile: "int | None" = None) -> list:
    """The ORDERED build steps — the ONE place the order lives (SPEC-1032 rule 6). Each step is
    {name, where, text} plus what the driver runs: `script` (box-side shell text fed to `bash -s`
    over ssh as `user`), `stdin_file` (the provisioning script, fed the same way), `argv` (a host
    git command) or nothing (a provider call the driver makes). `render_build_plan` prints `text`."""
    nofile = remote_verify.VENUE_NOFILE if nofile is None else int(nofile)
    repo, path, release = pre["repo_root"], pre["engine_path"], pre["engine"]
    main_sha = pre["main_sha"]
    clone = remote_verify.BOX_REPO_GIT
    url = f"ssh://{user}@{box}/home/{user}/venue/repo.git"
    base_check = (
        "set -eu\n"
        "test -f ~/CLOUD-INIT-DONE\n"
        f"test \"$(id -un)\" = {_q(user)}\n"
        "[ -n \"$(command -v flock)\" ] || { echo 'base setup: flock is missing'; exit 1; }\n"
        f"[ \"$(ulimit -Sn)\" -ge {nofile} ] && [ \"$(ulimit -Hn)\" -ge {nofile} ] "
        f"|| {{ echo \"base setup: nofile $(ulimit -Sn)/$(ulimit -Hn) < {nofile}\"; exit 1; }}\n"
        "echo 'base setup: user, nofile and flock present'\n")
    clone_init = (
        "set -eu\n"
        f"test ! -e {clone} || {{ echo 'the clone path already exists: the build owns it'; exit 1; }}\n"
        f"mkdir -p {remote_verify.BOX_VENUE_DIR} && git init -q --bare {clone}\n")
    push_argv = ["git", "-C", str(repo), "push", "-q", url,
                 f"{main_sha}:refs/heads/main", "refs/tags/*:refs/tags/*"]
    clone_verify = (
        "set -eu\n"
        f"cd {clone}\n"
        "test \"$(git rev-parse --is-shallow-repository)\" = false\n"
        f"test \"$(git rev-parse --verify -q 'refs/heads/main^{{commit}}')\" = {main_sha}\n"
        "git fsck --connectivity-only --no-dangling --no-progress\n"
        "sync\n"
        f"echo 'clone verified: full history, main@{main_sha[:12]}'\n")
    engine_dir = (
        "set -eu\n"
        f"sudo mkdir -p {_q(path)} && sudo chown {user}:{user} {_q(path)}\n"
        f"test -z \"$(ls -A {_q(path)})\" || {{ echo 'the engine path is not empty:' {_q(path)}; exit 1; }}\n")
    extract = f"tar -x -C {_q(path)}"
    engine_verify = (
        "set -eu\n"
        f"test -f {_q(path + '/bin/yitc-v2')} && test -f {_q(path + '/bin/lib/cli.py')}\n"
        f"echo 'engine release {release['source_ref']} installed at' {_q(path)}\n")
    fstrim = "set -eu\nsync\nsudo fstrim -av\nsync\n"
    ssh = f"ssh {user}@{box}"
    return [
        {"name": "base-setup", "where": "cloud-init (root, at raise)",
         "text": build_base_setup(user=user, nofile=nofile)},
        {"name": "base-check", "where": f"box as {user}", "text": base_check, "script": base_check,
         "timeout": 120},
        {"name": "provision", "where": f"box as {user}",
         "text": f"{ssh} 'bash -s' < {_q(pre['provision_path'])}   # the project's script, as {user}",
         "stdin_file": pre["provision_path"], "timeout": 7200},
        {"name": "clone-init", "where": f"box as {user}", "text": clone_init, "script": clone_init,
         "timeout": 120},
        {"name": "clone-push", "where": "host",
         "text": " ".join(_q(a) for a in push_argv) + "   # full history: no --depth",
         "argv": push_argv, "timeout": 5400},
        {"name": "clone-verify", "where": f"box as {user}", "text": clone_verify,
         "script": clone_verify, "timeout": 1800},
        {"name": "engine-dir", "where": f"box as {user}", "text": engine_dir, "script": engine_dir,
         "timeout": 120},
        {"name": "engine-install", "where": "host",
         "text": (f"tar of the release {release['source_ref']} as published ({len(release['tree'])} "
                  f"files, tree_digest {release['tree_digest'][:16]}…, verified against its manifest) "
                  f"| {ssh} {_q(extract)}"),
         "release": release, "extract": extract, "timeout": 900},
        {"name": "engine-verify", "where": f"box as {user}", "text": engine_verify,
         "script": engine_verify, "timeout": 120},
        {"name": "fstrim", "where": f"box as {user}", "text": fstrim, "script": fstrim,
         "timeout": 900},
        {"name": "poweroff", "where": "provider",
         "text": f"POST /servers/{server_id}/actions/poweroff   # quiesce: never snapshot a running box"},
        {"name": "snapshot", "where": "provider",
         "text": f"POST /servers/{server_id}/actions/create_image"},
    ]


def render_build_plan(steps: list) -> str:
    """The build as text, in order — what the driver runs, readable without a box."""
    return "\n".join(f"## {i}. {s['name']} [{s['where']}]\n{s['text'].rstrip()}\n"
                     for i, s in enumerate(steps, 1))


def _box_run(ip: str, payload: bytes, *, user: str = BOX_USER, timeout: float):
    """ONE ssh round to the build box: `bash -s` reading the step's text (or the project's
    provisioning script) on stdin, as `user`. Bytes in, bytes out — a script is never re-encoded."""
    return subprocess.run(remote_verify.ssh_argv(ip, "bash -s", user=user), input=payload,
                          capture_output=True, timeout=timeout)


def _push_clone(argv: list, *, timeout: float):
    """The full-history clone push (host git, the SPEC-0188 rule 7 child env + the venue ssh opts)."""
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    env = dict(os.environ, GIT_SSH_COMMAND="ssh " + " ".join(remote_verify.SSH_OPTS))
    return subprocess.run(argv, text=True, capture_output=True, timeout=timeout,
                          env=_git_env._git_child_env(env))


def _install_engine(release: dict, ip: str, extract: str, *, user: str = BOX_USER,
                    timeout: float):
    """The verified release tree (`_engine_release`) written as ONE tar and fed to `tar -x` on the
    box. The bytes are the snapshot the digest was computed over — never a second read of the root
    — and a file's executable bit travels (0755 for the release's exec paths, else 0644).
    Returns (rc, tail)."""
    import tarfile
    with tempfile.TemporaryFile() as tar_file:
        with tarfile.open(fileobj=tar_file, mode="w") as tar:
            for rel in sorted(release["tree"]):
                blob = release["tree"][rel]
                info = tarfile.TarInfo(rel)
                info.size = len(blob)
                info.mode = 0o755 if rel in release["exec_paths"] else 0o644
                info.mtime = int(time.time())
                tar.addfile(info, io.BytesIO(blob))
        tar_file.seek(0)
        unpack = subprocess.run(remote_verify.ssh_argv(ip, extract, user=user), stdin=tar_file,
                                capture_output=True, timeout=timeout)
    return unpack.returncode, (unpack.stderr or unpack.stdout or b"").decode("utf-8", "replace")


# ── Provider calls the build adds (ported from the recipe's `seed`; each is a READ or a MUTATION) ─
def poweroff_server(server_id, *, env=None) -> None:
    status, parsed = _api("POST", f"/servers/{server_id}/actions/poweroff", {}, env=env)
    if status != 201:
        code, msg = _error_of(parsed)
        raise VenueError(f"poweroff of server {server_id} failed (HTTP {status}) — {code}: {msg}")


def server_status(server_id, *, env=None) -> str:
    status, parsed = _api("GET", f"/servers/{server_id}", env=env)
    if status != 200:
        code, msg = _error_of(parsed)
        raise VenueError(f"cannot read server {server_id} (HTTP {status}) — {code}: {msg}")
    return str(((parsed or {}).get("server") or {}).get("status") or "")


def create_image(server_id, description: str, *, env=None, labels: "dict | None" = None) -> str:
    body = {"type": "snapshot", "description": description,
            "labels": {"purpose": "remote-verify-venue-seed", **(labels or {})}}
    status, parsed = _api("POST", f"/servers/{server_id}/actions/create_image", body, env=env)
    if status != 201:
        code, msg = _error_of(parsed)
        raise VenueError(f"create_image of server {server_id} failed (HTTP {status}) — {code}: {msg}")
    image_id = ((parsed or {}).get("image") or {}).get("id")
    if image_id in (None, ""):
        raise VenueError(f"create_image of server {server_id} returned no image id")
    return str(image_id)


def image_status(image_id, *, env=None) -> str:
    status, parsed = _api("GET", f"/images/{image_id}", env=env)
    if status != 200:
        code, msg = _error_of(parsed)
        raise VenueError(f"cannot read image {image_id} (HTTP {status}) — {code}: {msg}")
    return str(((parsed or {}).get("image") or {}).get("status") or "")


def wait_status(read, want: str, *, seam: str, interval: float, timeout: float,
                _sleep=time.sleep, _now=time.monotonic) -> float:
    """The bounded provider poll — `read()` until it returns `want` or ONE absolute deadline passes
    (a read fault refuses at once: the box is deleted by the caller's finally, never retried into)."""
    t0 = _now()
    last = ""
    while True:
        last = read()
        if last == want:
            return _now() - t0
        if _now() - t0 >= timeout:
            raise VenueError(f"bounded wait exceeded at seam {seam!r} — no {want!r} within "
                             f"{timeout:g}s (last observed: {last or '<empty>'})")
        _sleep(interval)


def _tail(raw, limit: int = 600) -> str:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
    text = text.strip()
    return text[-limit:] if len(text) > limit else text


#: The provider label every build box AND its snapshot carry, valued with the run's own nonce: the
#: one handle a box (or image) whose create response was LOST can still be found by.
BUILD_LABEL_KEY = "yitc-build"


def build_consumer_image(pre: dict, *, name: str, on_mutation=None, say=None, env=None,
                         ready_timeout: float = 900, poweroff_timeout: float = 300,
                         image_timeout: float = 1800, poll_interval: float = 5,
                         image_interval: float = 15, lookup_attempts: int = 3,
                         lookup_interval: float = 10) -> dict:
    """THE BUILD — raise a bare box under the install binding, run `build_plan` in order, quiesce,
    snapshot, and DELETE THE BOX ON EVERY EXIT (success, refusal, failure, interrupt).

    THE CREATE ITSELF IS INSIDE THE CLEANUP SCOPE. Every box carries `BUILD_LABEL_KEY=<nonce>`; when
    the create's outcome is unknown — a transport fault or an interrupt after the provider may have
    acted — the cleanup finds the box by that label and deletes it. Only a quota refusal (a
    DEFINITE "nothing was created") skips the cleanup.

    ONE ROW PER MUTATION, WHATEVER ITS OUTCOME (SPEC-0116). Each provider MUTATION the build attempts
    — create, poweroff, create_image, delete — calls `on_mutation(target, action)` exactly once, so
    the CLI host journals one `external_action` row each: the done row, or, when the call raised
    after the request may have reached the provider, ONE row saying the outcome is UNKNOWN (naming
    the run label). A quota refusal did nothing and writes none. The rows go through ONE writer that
    never raises: a row the journal refuses never stops a delete, and fails the build AFTER the
    cleanup, each such row named so it can be recorded by hand.

    THE CLEANUP IS ONE BOUNDED PHASE AN INTERRUPT DOES NOT CUT SHORT (`_cleanup_build_box`): an
    interrupt during it is held until its looks and deletes are done, the outcome is reported, and
    only then is the interrupt raised again.

    `pre` is `build_preflight`'s result. Returns {snapshot_id, server_id, ip, main_sha,
    engine_release, engine_tree_digest, engine_path, provision_rel, timings}. Raises
    `VenueQuotaRefused` or `VenueError`; a box that could not be deleted is named with
    `bin/yitc-v2 venue delete --server-id <id>`."""
    say = say or (lambda line: print(line, flush=True))
    mutated = on_mutation or (lambda target, action: None)
    b = _require_binding(env)
    provider = b.get("provider") or "venue-provider"
    nonce = uuid.uuid4().hex[:16]
    label = {BUILD_LABEL_KEY: nonce}
    box = {"id": None, "ip": ""}
    timings: dict = {}
    failure = interrupt = None
    image_id = None
    current = "create"
    faults: list = []

    def row(target, action) -> None:
        """THE one row writer — never raises; a refused row is kept for the end-of-build refusal."""
        try:
            mutated(target, action)
        except Exception as exc:               # noqa: BLE001 — the delete matters more than the row
            faults.append((target, action, f"{exc.__class__.__name__}: {_tail(str(exc), 200)}"))
            say(f"  WARNING: the external_action row could not be written ({exc}): {action}")

    def attempt(call, target, action):
        """ONE provider mutation. On a raise after the request may have reached the provider, its
        ONE row says the outcome is UNKNOWN; the done row is the caller's (it names the new id)."""
        try:
            return call()
        except VenueQuotaRefused:
            raise                              # DEFINITE: the provider did nothing
        except BaseException as exc:
            row(target, f"{action} — outcome UNKNOWN: the call raised {exc.__class__.__name__} "
                        f"({_tail(str(exc), 200)}), so the provider may have acted; the run label is "
                        f"{BUILD_LABEL_KEY}={nonce} (venue seed --build)")
            raise

    def journal_held() -> None:
        if faults:                             # stop now: a build whose rows are refused bills on
            raise VenueError("the journal refused an external_action row, so the build stops")

    try:
        created = attempt(lambda: create_server(name, BUILD_BARE_IMAGE, env=env,
                                                user_data=build_base_setup(), labels=label),
                          f"{provider}:server(label {BUILD_LABEL_KEY}={nonce})", "POST /servers")
        box["id"], box["ip"] = created["server_id"], created["ip"]
        server_id, ip = box["id"], box["ip"]
        target = f"{provider}:server({server_id})"
        row(target, f"POST /servers — {b['server_type']} {b['location']} raised from bare image "
                    f"{BUILD_BARE_IMAGE} with the base setup, label {BUILD_LABEL_KEY}={nonce} "
                    f"(venue seed --build)")
        journal_held()
        say(f"venue seed --build: server {server_id} at {ip} raised from {BUILD_BARE_IMAGE}")
        if not ip:
            raise VenueError(f"the provider created server {server_id} but reported no ipv4")
        current = "wait-ready"
        t0 = time.monotonic()
        wait_ready(ip, timeout=ready_timeout)
        timings["ready_s"] = round(time.monotonic() - t0, 1)
        for step in build_plan(pre, box=ip, server_id=server_id):
            t0 = time.monotonic()
            name_ = current = step["name"]
            if name_ == "base-setup":
                continue                                   # ran as cloud-init at the raise
            say(f"  {name_}: running ({step['where']})")
            if "script" in step or "stdin_file" in step:
                payload = (Path(step["stdin_file"]).read_bytes() if "stdin_file" in step
                           else step["script"].encode("utf-8"))
                r = _box_run(ip, payload, timeout=step["timeout"])
                if r.returncode != 0:
                    raise VenueError(f"step {name_!r} failed on the box (rc={r.returncode}): "
                                     f"{_tail(r.stderr or r.stdout)}")
            elif "argv" in step:
                r = _push_clone(step["argv"], timeout=step["timeout"])
                if r.returncode != 0:
                    raise VenueError(f"step {name_!r} failed (rc={r.returncode}): "
                                     f"{_tail(r.stderr or r.stdout)}")
            elif "release" in step:
                rc, tail = _install_engine(step["release"], ip, step["extract"],
                                           timeout=step["timeout"])
                if rc != 0:
                    raise VenueError(f"step {name_!r} failed (rc={rc}): {_tail(tail)}")
            elif name_ == "poweroff":
                attempt(lambda: poweroff_server(server_id, env=env), target,
                        f"POST /servers/{server_id}/actions/poweroff")
                row(target, f"POST /servers/{server_id}/actions/poweroff — quiesce before "
                            f"create_image (venue seed --build)")
                journal_held()
                wait_status(lambda: server_status(server_id, env=env), "off",
                            seam="server-powered-off", interval=poll_interval,
                            timeout=poweroff_timeout)
            elif name_ == "snapshot":
                desc = (f"yitc-venue-seed {pre['repo_root'].name} main@{pre['main_sha'][:8]} "
                        f"engine {pre['engine']['source_ref']} (SPEC-1032 rule 6 consumer image; "
                        f"T-13977)")
                try:
                    image_id = attempt(lambda: create_image(server_id, desc, env=env, labels=label),
                                       f"{provider}:image(label {BUILD_LABEL_KEY}={nonce})",
                                       f"POST /servers/{server_id}/actions/create_image")
                except VenueError as exc:
                    raise VenueError(f"{exc} — if the provider made the snapshot anyway it carries "
                                     f"the label {BUILD_LABEL_KEY}={nonce}") from None
                row(f"{provider}:image({image_id})",
                    f"POST /servers/{server_id}/actions/create_image — consumer seed snapshot of "
                    f"{pre['repo_root'].name} at main@{pre['main_sha'][:8]}, label "
                    f"{BUILD_LABEL_KEY}={nonce} (venue seed --build)")
                journal_held()
                wait_status(lambda: image_status(image_id, env=env), "available",
                            seam="snapshot-available", interval=image_interval,
                            timeout=image_timeout)
            else:
                raise VenueError(f"internal: build step {name_!r} has nothing to run")
            timings[f"{name_}_s"] = round(time.monotonic() - t0, 1)
            say(f"  {name_}: done ({timings[f'{name_}_s']}s)")
    except VenueQuotaRefused:
        raise                                  # DEFINITE: the provider created nothing
    except subprocess.TimeoutExpired as exc:
        failure = f"step {current!r} outlived its {exc.timeout:g}s bound"
    except VenueError as exc:
        failure = str(exc)
    except Exception as exc:                   # noqa: BLE001 — any fault is a refusal, box deleted
        failure = f"{exc.__class__.__name__}: {_tail(str(exc), 300)}"
    except BaseException as exc:               # an interrupt: clean up, then let it propagate
        interrupt = exc
    gone, cleanup, held = _cleanup_build_box(box["id"], nonce, provider, row, say, env=env,
                                             attempts=lookup_attempts, interval=lookup_interval)
    if interrupt is None and held:
        interrupt = held[0]
    if faults:
        cleanup += (f" {len(faults)} external_action row(s) could NOT be journaled; record each with "
                    f"`bin/yitc-v2 event external_action --task <id> --data <target, action>`: "
                    + "; ".join(f"[{t}] {a} ({why})" for t, a, why in faults))
        if failure is None:
            failure = "the journal refused an external_action row"
    if interrupt is not None:
        say(f"venue seed --build: INTERRUPTED at step {current!r} — {cleanup}")
        raise interrupt
    if failure is not None and image_id:
        failure += f" (snapshot {image_id} was requested and is NOT recorded)"
    if failure is not None:
        raise VenueError(f"the image build REFUSED — {failure}. {cleanup}")
    if not gone:
        raise VenueError(f"snapshot {image_id} is available but {cleanup} Then record the image "
                         f"with `bin/yitc-v2 venue seed --snapshot-id {image_id}`")
    return {"snapshot_id": image_id, "server_id": box["id"], "ip": box["ip"],
            "main_sha": pre["main_sha"], "engine_release": pre["engine"]["source_ref"],
            "engine_tree_digest": pre["engine"]["tree_digest"], "engine_path": pre["engine_path"],
            "provision_rel": pre["provision_rel"], "timings": timings}


def _cleanup_build_box(server_id, nonce, provider, row, say, *, env=None, attempts: int = 3,
                       interval: float = 10, _sleep=time.sleep) -> tuple:
    """(gone, sentence, held) — delete the build box, as ONE bounded phase an interrupt does not cut
    short: EVERY call in it — provider calls, the waits, the journal rows and the progress lines —
    runs through `shielded`, so a fault is named and an interrupt is HELD (returned in
    `held` for the caller to raise once the outcome is reported) while the phase finishes its looks
    and deletes. With no id in hand (the create's response never arrived, or an interrupt hit it)
    the box is FOUND by the run's label. A create whose answer was lost may still be completing on
    the provider's side, so the lookup is repeated — `attempts` looks, `interval` seconds apart —
    and an empty result is reported as exactly that, never as proof that nothing was created. Each
    delete writes ONE row through `row` (the build's writer, which never raises)."""
    held: list = []

    def shielded(fn, *a, **kw) -> tuple:
        try:
            return True, fn(*a, **kw)
        except Exception as exc:               # noqa: BLE001 — named by the caller
            return False, exc
        except BaseException as exc:           # an interrupt: held, the phase runs on
            held.append(exc)
            return False, exc

    def why(exc) -> str:
        return f"{exc.__class__.__name__}: {_tail(str(exc), 200)}" if str(exc) else exc.__class__.__name__

    by_label = server_id is None
    if not by_label:
        ids = [server_id]
    else:
        ids, failed = [], []
        looks = max(1, int(attempts))
        for look in range(looks):
            if look:
                shielded(_sleep, interval)
            ok, found = shielded(list_servers, env=env, label=f"{BUILD_LABEL_KEY}={nonce}")
            if not ok:
                failed.append(found)
                continue
            ids = [s.get("id") for s in found if isinstance(s, dict) and s.get("id") is not None]
            if ids:
                break
        if not ids and failed:
            return False, (f"The create's outcome is unknown and {len(failed)} of {looks} lookup(s) by "
                           f"its label failed (last: {why(failed[-1])}): a box labelled "
                           f"{BUILD_LABEL_KEY}={nonce} may be live — find it in the provider project "
                           f"and delete it with `bin/yitc-v2 venue delete --server-id <id>`."), held
        if not ids:
            return True, (f"No box labelled {BUILD_LABEL_KEY}={nonce} was found after {looks} "
                          f"look(s); should the provider project show one later, delete it with "
                          f"`bin/yitc-v2 venue delete --server-id <id>`."), held
    how = f" (found by its label {BUILD_LABEL_KEY}={nonce})" if by_label else ""
    stuck = []
    for sid in ids:
        ok, status = shielded(delete_server, sid, env=env)
        if not ok:
            stuck.append(sid)
            shielded(row, f"{provider}:server({sid})",
                     f"DELETE /servers/{sid} — outcome UNKNOWN: the call raised {why(status)}; the "
                     f"build box{how} may still be live (venue seed --build)")
            shielded(say, f"  WARNING: delete of build box {sid} FAILED ({why(status)})")
            continue
        shielded(row, f"{provider}:server({sid})",
                 f"DELETE /servers/{sid} — build box{how} deleted (HTTP {status}) (venue seed --build)")
        shielded(say, f"  build box {sid} deleted (HTTP {status})")
    if stuck:
        return False, (f"The build box could NOT be deleted: finish with `bin/yitc-v2 venue delete "
                       f"--server-id {stuck[0]}`."), held
    return True, "The box was deleted.", held

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


def probe_readiness(fingerprint: dict | None, declaration: "dict | None" = None) -> list:
    """The FAILURES, in table order: `[{field, op, expected, actual}]`. Empty list = GREEN.

    The fd row delegates to `remote_verify.fingerprint_admits_pin` — the ONE home of that predicate
    (rule 5) — and is reported under a synthetic `nofile` field so a refusal still names what failed.

    T-13974 — `declaration` is a consumer's `verify.venue` reading (`consumer_declaration`). Given,
    the box is judged for THAT consumer too, after the unchanged rows (SPEC-1032 rules 3 and 6): see
    `consumer_readiness_failures`. Omitted (every kernel caller), the result is exactly as before —
    a `consumer` part in the fingerprint is not read at all.
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
    if declaration is not None:
        failures.extend(consumer_readiness_failures(fp, declaration))
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
        from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
        try:
            return subprocess.run(["git", "-C", str(repo_root), *argv], text=True,
                                  capture_output=True, timeout=30, env=_git_env._git_child_env())
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


# ── The consumer declaration — `verify.venue` (SPEC-1032 rule 1, T-13972) ─────────────────────────
#: The reason a consumer pass reads when its `verify.venue` mapping is present but malformed: it runs
#: locally, and the reason is shown on its Stage-6 row (SPEC-1032 rules 1-2) — never a silent local run.
DECLARATION_INVALID_REASON = "venue-declaration-invalid"


def consumer_declaration(ops) -> dict:
    """The consumer's `verify.venue` opt-in, read off the ALREADY-PARSED `yitc-ops.yaml` carrier
    (SPEC-1032 rule 1; the carrier is SPEC-0093's, read and parsed by the caller). PURE: no I/O, no
    environment, never raises, never mutates `ops`. Returns exactly one of

      {"state": "absent"}
      {"state": "valid", "stage6": True, "environment": [{"name", "cmd", "expect"}, ...]}
      {"state": "invalid", "reason": DECLARATION_INVALID_REASON, "cause": "<field path>: <what>"}

    ABSENT is keyed off the KEY (the `verify.layer_worker_shares` stance): no carrier, no `verify`
    mapping, or no `venue` key reads absent — SPEC-1029's `consumer` branch, nothing below is read. A
    PRESENT key whose value is malformed is INVALID, never silently absent, so `venue: ~` is invalid.

    The checks run in a fixed order and the FIRST failure is the cause, so a cause names ONE field:
    the mapping; `stage6` (exactly `True` — YAML `on` — or the quoted string "on"; `1` is not on);
    `environment` (a list; an empty list is valid — what is not declared is not compared); then per
    check: a mapping, `name` / `cmd` / `expect` each present and a string, `name` and `cmd` non-blank
    (`expect` may be "" — a command that prints nothing), and no repeated `name` (a check is refused
    BY NAME at publish, rule 6). Unknown keys are ignored; the valid result carries only the three
    fields of each check, values verbatim.

    Read by the Stage-6 seam (`task._stage6_consumer_venue`) and by `venue publish -C`, both since
    T-13976 activated SPEC-1032."""
    def invalid(path, what):
        return {"state": "invalid", "reason": DECLARATION_INVALID_REASON, "cause": f"{path}: {what}"}

    ver = ops.get("verify") if isinstance(ops, dict) else None
    if not isinstance(ver, dict) or "venue" not in ver:
        return {"state": "absent"}
    mapping = ver.get("venue")
    if not isinstance(mapping, dict):
        return invalid("verify.venue", f"{mapping!r} is not a mapping")
    if "stage6" not in mapping:
        return invalid("verify.venue.stage6", "missing (the only routed pass class is `stage6: on`)")
    stage6 = mapping.get("stage6")
    if not (stage6 is True or stage6 == "on"):
        return invalid("verify.venue.stage6", f"{stage6!r} is not on")
    env_list = mapping.get("environment")
    if not isinstance(env_list, list):
        return invalid("verify.venue.environment",
                       "missing" if "environment" not in mapping else f"{env_list!r} is not a list")
    checks, seen = [], set()
    for i, entry in enumerate(env_list):
        at = f"verify.venue.environment[{i}]"
        if not isinstance(entry, dict):
            return invalid(at, f"{entry!r} is not a mapping of name, cmd, expect")
        for field in ("name", "cmd", "expect"):
            if field not in entry:
                return invalid(f"{at}.{field}", "missing")
            if not isinstance(entry[field], str):
                return invalid(f"{at}.{field}", f"{entry[field]!r} is not a string (quote it)")
        for field in ("name", "cmd"):
            if not entry[field].strip():
                return invalid(f"{at}.{field}", "empty")
        if entry["name"] in seen:
            return invalid(f"{at}.name", f"duplicate {entry['name']!r}")
        seen.add(entry["name"])
        checks.append({"name": entry["name"], "cmd": entry["cmd"], "expect": entry["expect"]})
    return {"state": "valid", "stage6": True, "environment": checks}


def consumer_declaration_of(repo_root, ops_contract) -> dict:
    """T-13976 — `consumer_declaration` over the carrier ON DISK: `repo_root`/`ops_contract` (the
    caller names the carrier, `init.CONSUMER_OPS_CONTRACT`). The ONE file read of `verify.venue`, used
    by the Stage-6 seam and by `venue publish -C`. No carrier reads absent; a carrier that does not
    parse reads INVALID naming the file, never silently absent."""
    from lib import state                      # deferred, as this module's other lib reads
    path = Path(repo_root) / ops_contract
    if not path.is_file():
        return {"state": "absent"}
    try:
        ops = state.load_ops(path)
    except Exception as e:                     # noqa: BLE001 — named, never absent
        return {"state": "invalid", "reason": DECLARATION_INVALID_REASON,
                "cause": f"{ops_contract}: does not parse ({type(e).__name__})"}
    return consumer_declaration(ops)


# ── The consumer box readiness — SPEC-1032 rules 3 and 6 (T-13974) ─────────────────────────────────
#: The consumer part of the box fingerprint, measured in ONE ssh round beside `measure_fingerprint`
#: (the `_CLONE_SCRIPT` precedent), never one round per check: whether the atomic admission primitive
#: (`flock`) is on the box, whether the seeded clone is SHALLOW (the consumer's tests read old git
#: objects, so a shallow clone is refused), and each declared check's exit code and stdout. The checks
#: travel base64-encoded JSON, so no command text can close the heredoc or need quoting. Each check
#: runs under `bash -c` in its OWN process group, and ONE invariant decides what was measured: a check
#: has an exit code only when its stdout reached EOF AND the process exited, both within ONE deadline
#: of `timeout_s` (60 s by default). Anything else — a hang, or a child left holding stdout open — is
#: rc None, which fails, and the whole group is killed whatever happened, so nothing the check
#: started outlives it and no partial output is ever judged. The checks run inside a temporary checkout
#: of the clone's `main`, as a pass runs them inside its own checkout (T-13976). stdout is read off the raw fd as it
#: arrives and only the first 65536 bytes are KEPT (a check that prints without end costs no memory
#: past that); past them the output is `truncated`, which never passes. stderr is discarded. The
#: 65536 is a literal on purpose: this one script's bound, not a machine setting.
_CONSUMER_PROBE_SCRIPT = r"""python3 - <<'PY'
import base64, json, os, select, shutil, signal, subprocess, time
checks = json.loads(base64.b64decode(%(checks)r).decode("utf-8"))

def run_check(cmd, cwd=None):
    try:
        p = subprocess.Popen(["bash", "-c", cmd], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, start_new_session=True, cwd=cwd)
    except OSError:
        return None, b"", False
    deadline = time.monotonic() + %(timeout)d
    fd, kept, seen, eof, rc = p.stdout.fileno(), bytearray(), 0, False, None
    while True:
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            break
        b = os.read(fd, 65536)
        if not b:
            eof = True
            break
        if seen <= 65536:
            kept += b
        seen += len(b)
    if eof:
        try:
            rc = p.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            rc = None
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        pass
    p.wait()
    p.stdout.close()
    return rc, bytes(kept[:65536]), seen > 65536
clone = os.path.expanduser("~/venue/repo.git")
try:
    r = subprocess.run(["git", "-C", clone, "rev-parse", "--is-shallow-repository"],
                       text=True, capture_output=True, timeout=30)
    shallow = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() in ("true", "false") else None
except Exception:
    shallow = None
# T-13976: the checks run inside a checkout of the clone's main, as every pass runs them inside its
# own checkout — a directory-dependent check answers the same at publish and on the pass. No checkout
# (no clone, no main) leaves them in the login directory; the clone rows above already fail then.
import tempfile
work = tempfile.mkdtemp(prefix="venue-readiness-")
co = os.path.join(work, "checkout")
try:
    made = subprocess.run(["git", "-C", clone, "worktree", "add", "-q", "--detach", co, "main"],
                          capture_output=True, timeout=120).returncode == 0
except Exception:
    made = False
out = []
try:
    for c in checks:
        rc, data, truncated = run_check(c["cmd"], co if made else None)
        out.append({"name": c["name"], "rc": rc, "stdout": data.decode("utf-8", "replace"),
                    "truncated": truncated})
finally:
    if made:
        subprocess.run(["git", "-C", clone, "worktree", "remove", "--force", co], capture_output=True)
    shutil.rmtree(work, ignore_errors=True)
print(json.dumps({"flock": shutil.which("flock") is not None, "clone_shallow": shallow,
                  "checks": out}))
PY"""


def consumer_probe_script(checks, *, timeout_s: int = 60) -> str:
    """The consumer probe TEXT for the declared `checks` ({name, cmd, expect}; `expect` is never
    shipped — the box measures, the host judges). Returned as text so a test runs the SAME script on
    this host that `measure_consumer_environment` sends to the box; `timeout_s` is the per-check
    bound (the shipped probe uses the default)."""
    payload = json.dumps([{"name": c["name"], "cmd": c["cmd"]} for c in checks or ()])
    return _CONSUMER_PROBE_SCRIPT % {"checks": base64.b64encode(payload.encode("utf-8")).decode("ascii"),
                                     "timeout": int(timeout_s)}


def measure_consumer_environment(ip: str, declaration: dict, *, user: str = BOX_USER,
                                 timeout: "float | None" = None) -> dict:
    """Run the consumer probe on the box: `{flock, clone_shallow, checks: [{name, rc, stdout,
    truncated}]}` — the fingerprint's `consumer` part (SPEC-1032 rule 1: the declared checks'
    outputs are the consumer part of the environment fingerprint). A declaration that is not a valid
    one is refused by name rather than probed; a probe that did not run or did not parse is a
    `VenueError`, never an empty reading that would judge as «no checks failed»."""
    if not isinstance(declaration, dict) or declaration.get("state") != "valid":
        raise VenueError("no valid verify.venue declaration to probe the box against"
                         + (f" — {declaration.get('cause')}" if isinstance(declaration, dict)
                            and declaration.get("cause") else ""))
    checks = declaration.get("environment") or []
    if timeout is None:
        timeout = 60 + 60 * len(checks)      # the script's own 60 s per check, plus the round
    # Through the ONE venue ssh launcher (`remote_verify._ssh`, the `probe_fingerprint` route), not a
    # second raw launch site; `check=False` so the refusal below is this module's named VenueError.
    r = remote_verify._ssh(ip, consumer_probe_script(checks), user=user, timeout=timeout, check=False)
    if r.returncode != 0:
        raise VenueError(f"the consumer probe did not run on the box (rc={r.returncode}): "
                         f"{(r.stderr or r.stdout)[:200]}")
    try:
        measured = json.loads(r.stdout)
    except ValueError:
        raise VenueError("the box returned an unparseable consumer probe") from None
    if not isinstance(measured, dict):
        raise VenueError("the box returned an unparseable consumer probe")
    return measured


def consumer_check_passes(rc, stdout, expect, truncated=False) -> bool:
    """THE ONE comparison of a declared check (SPEC-1032 rule 1): it exited 0 AND its stdout equals
    `expect`. «Equals» is the shell's `$(...)` reading — trailing newlines dropped, nothing else
    touched (the declaration keeps `expect` verbatim, surrounding spaces included). A `truncated`
    output never passes, whatever its prefix: the bytes past the cut are unknown. A non-integer exit
    (None = timed out or did not start; a bool) fails."""
    if truncated:
        return False
    # T-13976: the ONE comparison, the pass's own (`remote_verify.declared_check_passes`)
    return remote_verify.declared_check_passes({"exit": rc, "stdout": stdout}, {"expect": expect})


def consumer_readiness_failures(fingerprint: "dict | None", declaration: dict) -> list:
    """The consumer rows of the readiness verdict, in the `probe_readiness` shape, read off the
    fingerprint's `consumer` part (`measure_consumer_environment`). Each failure NAMES its cause:
      `verify.venue` — the declaration is not a valid one (its own cause is the actual);
      `flock`        — the atomic admission primitive is absent (or was not measured);
      `clone_shallow`— the clone is shallow, or its depth could not be told (None): fail-closed;
      `check:<name>` — one per declared check that did not exit 0 with stdout equal to `expect`,
                       or that has no measurement at all.
    An empty `environment` adds no check rows — what is not declared is not compared."""
    if not isinstance(declaration, dict) or declaration.get("state") != "valid":
        return [{"field": "verify.venue", "op": "valid", "expected": "",
                 "actual": (declaration or {}).get("cause") or (declaration or {}).get("state")
                 if isinstance(declaration, dict) else declaration}]
    measured = (fingerprint or {}).get("consumer")
    measured = measured if isinstance(measured, dict) else {}
    failures = []
    if measured.get("flock") is not True:
        failures.append({"field": "flock", "op": "true", "expected": "",
                         "actual": measured.get("flock")})
    if measured.get("clone_shallow") != "false":
        failures.append({"field": "clone_shallow", "op": "eq", "expected": "false",
                         "actual": measured.get("clone_shallow")})
    got = {}
    for m in measured.get("checks") or ():
        if isinstance(m, dict) and isinstance(m.get("name"), str):
            got.setdefault(m["name"], m)
    for check in declaration.get("environment") or ():
        m = got.get(check["name"])
        if m is not None and consumer_check_passes(m.get("rc"), m.get("stdout"), check["expect"],
                                                   m.get("truncated")):
            continue
        failures.append({"field": f"check:{check['name']}", "op": "exit 0 and stdout eq",
                         "expected": check["expect"],
                         "actual": None if m is None else {
                             "rc": m.get("rc"), "stdout": str(m.get("stdout") or "")[:200],
                             "truncated": bool(m.get("truncated"))}})
    return failures
