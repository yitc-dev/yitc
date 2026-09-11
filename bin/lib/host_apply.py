"""cmd_host_apply verb — the safety-railed HOST-config apply seam (SPEC-0111).

GOVERNING SPEC: SPEC-0111 ("Host-config apply — safety-railed apply helper, server-wide health sweep +
auto-rollback, repo-conf-vs-live reconciliation"). That spec is `proposed`; this card (T-9595) is its
`activation_owner_task` — closing it flips SPEC-0111 proposed → active (the work-first pattern, T-0199).

`bin/yitc-v2 [-C <path>] hostapply --task T-XXXX --conf <src>[:<target>] [--confirm]
[--confirmed-by <ref>]` performs a HOST
nginx vhost change SAFELY BY CONSTRUCTION. The system NEVER holds autonomous sudo (SPEC-0111 §1): the
worker ships the repo conf + this VETTED helper, and the owner runs/approves it. The helper does, IN
ORDER (any failure ABORTS — no later step runs, old config stays live):
  (a) auto-BACKUP every target vhost file (§2a) into a per-run dir OUTSIDE the nginx tree (X-0116 — a
      backup left in sites-enabled/ would be re-included as live config); privileged ops escalate via
      sudo only where /etc/nginx is not user-writable (X-0114),
  (b) shared/foreign-vhost collision REFUSAL pre-write (§2c — the X-0097 guard),
  (b2) WRITE the shipped conf into the target (so -t/reload verify+apply the NEW config),
  (c) enable/include + `nginx -t` over the EFFECTIVE config (§2b — the conf must be included so -t sees it),
  (d) BASELINE server-wide health sweep of every registry.yaml domain (§3),
  (e) APPLY (the carrier `apply` reload recipe),
  (f) AFTER sweep → AUTO-ROLLBACK if any baseline-healthy domain regressed (§3),
  (g) repo-conf-vs-live RECONCILIATION via `nginx -T` (§4).
On full success it emits THREE task-scoped evidence events the SPEC-0094 §3 close-gate requires —
`host_reconciliation_recorded`, `host_health_sweep_passed`, and (with --confirm) `apply_confirmed` —
each carrying the PROVENANCE TAG `emitter: "hostapply"` (in normal governed operation only this helper
emits these three tagged types; the tag blocks ABSENT/INCIDENTAL evidence at the close-gate — it rests on
the operator-trusted journal, NOT forgery-resistance, SPEC-0094 §3 / SPEC-0025). `emitter` names the
emitting TOOL; `apply_confirmed.confirmed_by` names the AUTHORIZING DIRECTIVE (SPEC-0111 §1) — on the
controller-dispatched path `--confirmed-by` is REQUIRED with `--confirm` (a background session may not
self-authorize; refused before any write), interactively it defaults to `owner-interactive`.

Like cmd_deploy / cmd_live_probe, this module back-imports NOTHING from the host: every host global /
helper it needs is INJECTED as a keyword-only param by the host residue wrapper at call time, so a
monkeypatch on the host names stays honored. The privileged nginx invocation (`--nginx`), the domain
inventory (`--registry`), and the source→target conf mapping (`--conf`) are explicit inputs, so a TEST
drives a throwaway SANDBOX nginx (own --prefix + high port) that can never reach /etc/nginx or 80/443
(the SPEC-0035 trial safety envelope).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)

CONSUMER_OPS_CONTRACT = "yitc-ops.yaml"   # SPEC-0093 rule 1 — one carrier file at the repo root
HOST_APPLY_EMITTER = "hostapply"         # the helper-generated-evidence marker (SPEC-0094 §3 / SPEC-0025)
_HEALTH_TIMEOUT_S = 10                     # bounded sweep GET; a hung domain must not block the apply
_RELOAD_SETTLE_S = 1.5                     # wait for an async `nginx -s reload` to swap workers before re-probing
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})  # 3xx = healthy (SPEC-0111 §3, trial finding)

# The three task-scoped evidence events the apply seam produces (SPEC-0025 / SPEC-0094 §3). The close-gate
# requires ALL THREE for a host_config task, each carrying `emitter: "hostapply"`.
EVIDENCE_EVENTS = ("apply_confirmed", "host_health_sweep_passed", "host_reconciliation_recorded")


# ── Pure decision helpers (no I/O — unit-testable in isolation, the deploy.py _GateDecision idiom) ──

def _classify_health(status) -> str:
    """A domain's health from its immediate HTTP status (SPEC-0111 §3): a 2xx OR 3xx response is
    "healthy" (a 3xx redirect is healthy — the trial finding: else every intended redirect would
    false-trigger its own rollback); a 4xx / 5xx / connection-fail / timeout (status None) is "broken"."""
    if status is None:
        return "broken"
    return "healthy" if 200 <= int(status) < 400 else "broken"


def _regressed_domains(baseline: dict, after: dict) -> list:
    """The domains that REGRESSED across the apply (SPEC-0111 §3): a domain healthy in the BASELINE that
    is broken AFTER. A domain already broken in the baseline NEVER triggers (no false rollback on
    pre-existing breakage); a domain absent from `after` is treated as broken (could not be re-checked)."""
    regressed = []
    for domain, base_health in baseline.items():
        if base_health == "healthy" and after.get(domain, "broken") != "healthy":
            regressed.append(domain)
    return sorted(regressed)


def _confirm_authority_violation(confirm: bool, confirmed_by: str, dispatched: bool):
    """The refusal reason for a `--confirm` that names NO authorizing directive, else None (SPEC-0111 §1).

    `emitter: hostapply` proves WHICH TOOL emitted the attestation, never WHO AUTHORIZED it. §1 requires
    the apply-confirmation to carry the authority: on the CONTROLLER-DISPATCHED path the confirming
    session is NOT the owner, so it MUST name the owner directive that authorized the apply
    (`--confirmed-by <ref>`) — a background session may never self-authorize. On the INTERACTIVE path
    the owner IS at the terminal, so a bare `--confirm` stays sufficient (the caller records
    `owner-interactive` as the provenance); `--confirmed-by` is still honored there.
    """
    if not confirm:
        return None            # no attestation ⇒ no authority claim to substantiate
    if confirmed_by:
        return None            # authority named — admissible on either path
    if dispatched:
        return ("--confirm from a controller-dispatched session names no authorizing directive. A "
                "background session is not the owner and may never self-authorize a host-config apply "
                "(SPEC-0111 §1) — re-run with --confirmed-by <owner directive / journal ref>.")
    return None                # interactive owner-at-the-terminal — the unchanged manual path


def _strip_nginx_comments(text: str) -> str:
    """Remove nginx `#` comments — a `#` to end-of-line that is NOT inside a quoted string (X-0115: a
    commented-out `# server_name x;` must never be scanned as a live directive, else it false-triggers a
    collision / reconciliation). Quote-aware so a `#` inside a quoted literal (e.g. `return 200 "a#b";`) is
    PRESERVED. Newlines are kept (so directive boundaries stay intact); backslash-escapes inside quotes are
    not modelled — nginx vhost server_name values do not use them (kept deliberately simple, CHARTER §P1)."""
    out: list = []
    quote = None          # the open quote char (' or "), or None outside any string
    in_comment = False
    for ch in text:
        if in_comment:
            if ch == "\n":
                in_comment = False
                out.append(ch)
            continue
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            in_comment = True
            continue
        out.append(ch)
    return "".join(out)


def _parse_server_names(conf_text: str) -> "tuple[set, str | None]":
    """Parse an nginx conf snippet into (server_names, parse_error).

    Replaces the original `re.finditer(r"server_name\\s+([^;]+);")` scan, which had TWO composed
    defects that together wrote PROSE SPLIT INTO WORDS as vhost names on kupiclub's first real-host
    run (X-1193, fingerprint hostapply-server-names-regex-parses-prose-not-vhosts): (a) `[^;]+`
    matches NEWLINES, so a `server_name` mentioned in running text swallowed every following line up
    to the next `;` anywhere in the file, and (b) the scan was not block-aware, so a mention in prose
    was indistinguishable from a directive. Entries such as `#`, `(SPEC-0111)`, `Exists`,
    `NON-canonical`, `a`, `collides` reached a `host_reconciliation_recorded` event that read as if it
    had succeeded — a §4 record unusable as evidence, and a §2c collision check poisoned in BOTH
    directions (spurious clash, or a real clash hidden in the noise).

    TWO SEPARATE CONCERNS, deliberately not fused — extraction is TOLERANT of prose, the error leg is
    reserved for genuinely unreadable structure:

    (A) EXTRACTION. A name is harvested ONLY from a `server_name` word at DIRECTIVE-HEAD position (the
        first word of a `;`-terminated directive) whose enclosing block is a `server` block. Because
        `{`/`}`/`;` terminate a directive, a value can no longer cross lines or blocks. The enclosing
        block is identified by the LAST word before its `{` — last, not first, so an UNTERMINATED
        PROSE RUN preceding `server {` cannot poison the block head (exactly the kupiclub shape). A
        `server_name` mention at any NON-HEAD index is PROSE: ignored, never harvested, NOT an error —
        so a conf whose prose mentions server_name-like words still yields its REAL vhost set.
        `location /x {` heads as `/x` and `http {` as `http`, so a `server_name` nested in a
        NON-server block is not harvested either. A directive at TOP LEVEL is admitted — the helper
        accepts a bare conf SNIPPET, not only a whole file (the T-9595 contract), and refusing one
        would fail UNSAFE by blinding the §2c collision check. `_` (the catch-all) stays excluded —
        it owns nothing exclusively, so it never constitutes a collision.

    (B) UNPARSEABILITY. `(set(), reason)` — never a partial list — for structure that genuinely cannot
        be read: an unterminated quoted string, an unbalanced `}`, an unclosed `{` at EOF, or a
        directive of ANY name not terminated by `;` before `}`/EOF. A conf carrying only prose mentions is
        READABLE and returns `(names, None)`. The caller turns a reason into a REFUSAL or an
        empty-with-reason record, never a confident garbage list (`_reconciliation_record`).

    `#` comments are stripped FIRST (X-0115, `_strip_nginx_comments` reused unchanged) so a
    commented-out directive is never counted."""
    names: set = set()
    ctx: list = []        # enclosing block heads, outermost first
    words: list = []      # words of the directive/block-head being accumulated
    cur: list = []        # the word being accumulated
    quote = None          # the open quote char inside a value, or None
    for ch in _strip_nginx_comments(conf_text):
        if quote:
            if ch == quote:
                quote = None
            else:
                cur.append(ch)
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch in "{};":
            if cur:
                words.append("".join(cur))
                cur = []
            if ch == "{":
                # The block head is the LAST word before `{` (see (A)) — an unterminated prose run
                # preceding `server {` must not shift the head off `server`.
                ctx.append(words[-1] if words else "")
                words = []
            elif ch == "}":
                if not ctx:
                    return set(), "unbalanced '}' — the conf is not parseable as an nginx config"
                if words:
                    return set(), (f"directive {words[0]!r} is not terminated by ';' before '}}' — the "
                                   f"conf is not parseable as an nginx config")
                ctx.pop()
            else:   # ';' — a complete directive
                # HEAD POSITION is what defeats the prose class (a mention is never a directive's
                # first word); the BLOCK check then rejects a `server_name` nested in a NON-server
                # block. TOP LEVEL (ctx empty) is admitted: `_server_names` is documented to accept a
                # bare conf SNIPPET, not only a whole file (the T-9595 contract), and refusing one
                # would fail UNSAFE — a §2c collision the check no longer sees.
                if words and words[0] == "server_name" and (not ctx or ctx[-1] == "server"):
                    names.update(w for w in words[1:] if w and w != "_")
                words = []
            continue
        if ch.isspace():
            if cur:
                words.append("".join(cur))
                cur = []
            continue
        cur.append(ch)
    if quote:
        return set(), "unterminated quoted string — the conf is not parseable as an nginx config"
    if ctx:
        return set(), "unclosed '{' block at end of conf — the conf is not parseable as an nginx config"
    if cur:
        words.append("".join(cur))
    if words:
        # ANY unterminated trailing directive, not just a `server_name` one (audit-post pass-1 HIGH):
        # a conf that runs off the end mid-directive is unreadable as a whole, so the names parsed
        # from its earlier lines must not be reported as a confident set either.
        return set(), (f"directive {words[0]!r} is not terminated by ';' at end of conf — the conf is "
                       f"not parseable as an nginx config")
    return names, None


def _server_names(conf_text: str) -> set:
    """Every `server_name` declared by a real directive in an nginx conf snippet (the §2c collision
    check + the §4 reconciliation). `server_name a.test b.test;` inside a `server {}` block yields
    {a.test, b.test}; `_` is excluded. Thin extraction view over `_parse_server_names` — an
    UNPARSEABLE conf yields the empty set here, and callers that must be HONEST about that (the §4
    record) read the reason from `_parse_server_names` directly rather than from this set."""
    return _parse_server_names(conf_text)[0]


def _collision_violation(target_file: str, shipped_names: set, other_vhosts: dict) -> str:
    """Shared/foreign-vhost collision check (SPEC-0111 §2c). `other_vhosts` maps {file_path -> server_name
    set} for every OTHER vhost file present on the host (NOT the target). REFUSE (return a non-empty
    reason) if any server_name the shipped conf claims is ALSO declared by a DIFFERENT file — the change
    would silently fight another site for that name (the X-0097 overwrite-the-canonical-vhost class).
    Returns "" when the change exclusively owns every name it declares."""
    target = str(target_file)
    for other_file, other_names in other_vhosts.items():
        if str(other_file) == target:
            continue
        clash = shipped_names & set(other_names)
        if clash:
            return (f"server_name(s) {sorted(clash)} are ALSO declared by {other_file} — the change does "
                    f"not exclusively own them (shared/foreign vhost). Refusing the write (SPEC-0111 §2c).")
    return ""


def _parse_nginx_dump(dump: str) -> dict:
    """Parse `nginx -T` output into {config_file_path: file_content}. `nginx -T` prints each INCLUDED
    config file (across ALL included directories) as a `# configuration file <path>:` header followed by
    that file's verbatim content — so this is the AUTHORITATIVE full effective-config view (used by both
    the server-wide collision scan and the reconciliation, audit-post absorbs)."""
    sections: dict = {}
    cur, buf = None, []
    for line in dump.splitlines():
        m = re.match(r"#\s*configuration file\s+(.+?):\s*$", line)
        if m:
            if cur is not None:
                sections[cur] = "\n".join(buf)
            cur, buf = m.group(1).strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        sections[cur] = "\n".join(buf)
    return sections


def _norm(text: str) -> str:
    """Normalize for the shipped==live EQUALITY check (audit-consult pass-4 HIGH). `nginx -T` echoes a
    config file VERBATIM, so a genuine shipped==live apply differs only by section-extraction artifacts —
    line endings + leading/trailing blank lines + per-line TRAILING whitespace. Normalize ONLY those:
    PRESERVE all internal + leading whitespace, so a content difference inside a quoted literal
    (`return 200 "A  B";` vs `"A B";`) is NOT collapsed (the prior `" ".join(text.split())` collapsed ALL
    whitespace → a false reconcile match). True equality, robust only to the dump's framing."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _reconciliation_record(shipped_text: str, target_path: str, live_dump: str) -> dict:
    """Repo-conf-vs-live reconciliation (SPEC-0111 §4 — audit-post HIGH absorb): verify shipped-conf ==
    live-conf at the TARGET, and compute real clobber state — NOT a bare "names appear somewhere".
      match     — the target file's LIVE effective content (its `nginx -T` section) reflects the shipped
                  content: every shipped server_name AND the normalized shipped body are present there.
      clobbered — some OTHER live config file now declares a server_name the shipped conf owns (a foreign
                  file fighting for the name AFTER apply — the post-apply clobber, computed not assumed).
      parse_error — set (and everything else empty/False) when the SHIPPED conf cannot be parsed as an
                  nginx config at all: an honest empty-with-reason record instead of a confident
                  garbage server_names list (X-1193). None on the clean path.
    Returns {match, clobbered, missing, clobbered_by, parse_error}."""
    sections = _parse_nginx_dump(live_dump)
    target_live = sections.get(str(target_path), "")
    shipped_names, parse_error = _parse_server_names(shipped_text)
    if parse_error:
        # HONEST about a parse it cannot make (X-1193): no name set is computed, so no confident
        # garbage list can be recorded. Empty-with-reason — never `match: true`, never a populated
        # `missing`/`clobbered_by` derived from tokens we could not read. The caller REFUSES on it.
        return {"match": False, "clobbered": False, "missing": [], "clobbered_by": [],
                "parse_error": parse_error}
    live_names_in_target = _server_names(target_live)
    missing = sorted(n for n in shipped_names if n not in live_names_in_target)
    # EQUALITY, not containment (audit-post pass-3 HIGH): the target's live section must EXACTLY equal the
    # shipped body (nginx -T echoes a file verbatim, so a true shipped==live apply yields equal normalized
    # text). Substring `in` would let EXTRA live directives in the target still pass — a false reconcile.
    body_reflected = bool(target_live) and _norm(shipped_text) == _norm(target_live)
    clobbered_by = sorted(p for p, c in sections.items()
                          if str(p) != str(target_path) and (shipped_names & _server_names(c)))
    return {"match": (not missing) and body_reflected, "clobbered": bool(clobbered_by),
            "missing": missing, "clobbered_by": clobbered_by, "parse_error": None}


def _effective_vhosts(nginx_cmd: str, exclude: str = "") -> dict:
    """Build {config_file -> server_name set} from the CURRENT effective nginx config (`nginx -T`),
    across EVERY included directory — the server-wide collision scan source (audit-post MEDIUM absorb;
    a glob of one directory misses a conflicting vhost in another included dir). `exclude` drops the
    target's own file. Best-effort: a failed/empty dump returns {} and the caller falls back to a
    directory glob, so the local check is never LOST."""
    dump = _nginx(nginx_cmd, "-T")
    out: dict = {}
    for path, content in _parse_nginx_dump(dump.stdout or "").items():
        if path != str(exclude):
            out[path] = _server_names(content)
    return out


# ── I/O primitives (module-level so a sandbox test drives them, or monkeypatches them) ──

def _domain_to_url(domain: str) -> str:
    """Build the GET URL for a sweep domain. A domain already carrying a scheme is used as-is (the TEST
    registry points at `http://127.0.0.1:<port>` sandbox sites); a bare hostname becomes `https://<host>`
    (the production form, e.g. `kupiclub.glukonair.ru`)."""
    d = str(domain).strip()
    if d.lower().startswith(("http://", "https://")):
        return d
    return "https://" + d


def _http_status(url: str, *, opener_factory, timeout: int = _HEALTH_TIMEOUT_S):
    """Read-only GET → the IMMEDIATE HTTP status (no-follow, REUSING the SPEC-0094 no-follow opener so a
    3xx is reported as itself, not resolved to the final 200). Returns an int status, or None on any
    transport failure (unreachable / DNS / timeout) — None classifies as broken."""
    req = urllib.request.Request(url, method="GET")
    try:
        with opener_factory().open(req, timeout=timeout) as resp:  # noqa: S310 — declared http(s) GET
            return resp.getcode()
    except urllib.error.HTTPError as e:
        return e.code                      # a 3xx (no-follow) / 4xx / 5xx is a real status to classify
    except (urllib.error.URLError, OSError, ValueError):
        return None                        # transport failure → broken


def _sweep(domains, *, opener_factory) -> dict:
    """Server-wide health sweep (SPEC-0111 §3): GET every domain → {domain -> "healthy"|"broken"}."""
    return {d: _classify_health(_http_status(_domain_to_url(d), opener_factory=opener_factory))
            for d in domains}


def _registry_domains(registry_path: Path):
    """Every registered domain across ALL projects (SPEC-0111 §3 — the host nginx is SHARED, so the sweep
    is server-wide, not scoped to the changed site). Read-only over registry.yaml (D-0019 read-only).
    Returns the domain LIST on success, or **None** when the registry cannot be read/parsed or carries no
    `projects` mapping — so the caller FAILS CLOSED (audit-post pass-3 MEDIUM): a vacuous/zero-inventory
    sweep must NEVER count as a passing sweep that emits host_health_sweep_passed without validating
    sibling sites. A readable registry with zero domains returns []."""
    try:
        reg = state.load_str(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(reg, dict) or not isinstance(reg.get("projects"), dict):
        return None
    out: list = []
    for proj in reg["projects"].values():
        if isinstance(proj, dict):
            for d in (proj.get("domains") or []):
                if isinstance(d, str) and d.strip():
                    out.append(d.strip())
    return out


def _nginx(nginx_cmd: str, flag: str):
    """Run the configured nginx invocation with one control flag (`-t` validate / `-T` dump). `nginx_cmd`
    is the base invocation (`nginx`, or in a sandbox `<bin> -p <prefix> -c <conf>`). Returns the
    CompletedProcess (stdout+stderr captured) so the caller reads rc + the effective-config dump."""
    return subprocess.run(shlex.split(nginx_cmd) + [flag], capture_output=True, text=True)


# ── Privileged file ops (X-0114) — /etc/nginx is root-owned, so the in-process backup/write/restore must
#    escalate. We escalate via `sudo` ONLY when the location is not accessible to the invoking user, so a
#    SANDBOX test (its targets live under a user-owned tmp prefix) takes the plain path and never shells out.
#    Auto-adapts to both run modes: as-a-user-with-sudo (escalates) AND whole-verb-under-sudo (already root,
#    os.access reports writable → plain path, no double-sudo).

def _needs_priv(path) -> bool:
    """True when writing/removing `path` requires privilege escalation: an existing target not writable by
    us, OR its parent dir not writable (creating/replacing/removing a file is fundamentally a directory
    write). /etc/nginx (root-owned) → True; a user-owned tmp sandbox target → False."""
    p = Path(path)
    if p.exists() and not os.access(p, os.W_OK):
        return True
    parent = p.parent
    return parent.exists() and not os.access(parent, os.W_OK)


def _priv_copy(src, dst) -> None:
    """Copy src→dst, escalating via `sudo cp -p` when the SOURCE is unreadable by us OR the DEST location
    needs privilege (X-0114). Plain `shutil.copy2` (preserves mode+mtime, like `cp -p`) otherwise."""
    src, dst = Path(src), Path(dst)
    if (src.exists() and not os.access(src, os.R_OK)) or _needs_priv(dst):
        subprocess.run(["sudo", "cp", "-p", str(src), str(dst)], check=True)
    else:
        shutil.copy2(src, dst)


def _priv_remove(path) -> None:
    """Remove `path`, escalating via `sudo rm -f` when its location needs privilege (X-0114); else unlink."""
    p = Path(path)
    if _needs_priv(p):
        subprocess.run(["sudo", "rm", "-f", str(p)], check=True)
    elif p.exists():
        p.unlink()


# ── Out-of-nginx-tree backup location (X-0116) — a backup written next to the target in sites-enabled/ is
#    RE-INCLUDED by nginx's `*` glob and becomes LIVE config. Backups go to a per-run dir under an explicit
#    safe base, VALIDATED to sit outside every nginx-included directory before any backup is written.

def _backup_base() -> Path:
    """An explicitly-chosen base for out-of-nginx-tree backups (audit-pre absorb): prefer /var/tmp (FHS,
    persistent, never inside /etc/nginx), fall back to the system temp dir. NOT trusted blindly — the
    caller still VALIDATES the per-run dir against the live include set (`_within_any_dir`)."""
    for cand in ("/var/tmp", tempfile.gettempdir()):
        if cand and os.path.isdir(cand) and os.access(cand, os.W_OK):
            return Path(cand)
    return Path(tempfile.gettempdir())


def _included_dirs(nginx_cmd: str) -> "set | None":
    """The directories nginx INCLUDES config files from — the parent dir of every `nginx -T` config file.
    A backup dropped into any of these would be re-included as live config (X-0116). Returns **None** when
    `nginx -T` could not produce a usable dump (rc!=0 OR no config file parsed — a running nginx always has
    at least nginx.conf, so an empty parse means the dump FAILED): the caller then FAILS CLOSED rather than
    validating the backup dir against an empty set (audit-post: do not bypass the safety check exactly when
    the include set is most needed)."""
    dump = _nginx(nginx_cmd, "-T")
    if dump.returncode != 0:
        return None
    dirs = {str(Path(p).parent) for p in _parse_nginx_dump(dump.stdout or "")}
    return dirs or None


def _within_any_dir(path, dirs) -> bool:
    """True when `path` is equal to, or nested under, any directory in `dirs` (realpath-resolved, so a
    symlinked TMPDIR cannot defeat the check)."""
    rp = os.path.realpath(str(path))
    for d in dirs:
        rd = os.path.realpath(str(d))
        if rp == rd or rp.startswith(rd + os.sep):
            return True
    return False


def _backup_name(target: Path, stamp: str) -> str:
    """A collision-free, length-bounded backup filename for `target`: the basename (for legibility) + a
    short sha256 of the ABSOLUTE path. The hash — not a separator-flattened path — is what guarantees
    collision-freedom: flattening `/` to `__` ALIASES distinct paths whose components already contain `__`
    (audit-post finding), and a raw full path can approach NAME_MAX (audit-pre finding); a hash dodges
    both. Distinct targets → distinct hashes → no backup overwrites another's in the per-run dir."""
    digest = hashlib.sha256(os.path.abspath(str(target)).encode("utf-8")).hexdigest()[:16]
    return f"{target.name}.{digest}.bak.{stamp}"


def _parse_conf_arg(spec: str) -> "tuple[str, str | None]":
    """Parse one --conf value `src[:target]` → (src, target|None). When `:target` is omitted the target is
    resolved positionally from the carrier `vhost_files` by the caller (index order)."""
    if ":" in spec:
        src, target = spec.split(":", 1)
        return src.strip(), target.strip()
    return spec.strip(), None


def cmd_host_apply(args: argparse.Namespace, *, REPO_ROOT, REGISTRY_PATH, _append_event, _main_worktree,
                   _read_host_config, _no_redirect_opener, _die, _utc_now_iso) -> None:
    """Perform a safety-railed host-config apply + emit the three task-scoped evidence events (SPEC-0111).

    Exit codes (the trial-validated contract): 0 OK · 2 nginx -t ABORT (bad config) · 3 collision REFUSE ·
    4 server-wide regression AUTO-ROLLBACK. Any non-zero leaves the old config live and emits NO evidence.
    """
    tid = (getattr(args, "task", "") or "").strip()
    if not tid:
        _die("hostapply: --task T-XXXX is required (the three evidence events are task-scoped, SPEC-0111 §5).")
    conf_specs = list(getattr(args, "conf", None) or [])
    if not conf_specs:
        _die("hostapply: at least one --conf <src>[:<target>] is required (the shipped conf to apply).")
    nginx_cmd = (getattr(args, "nginx", None) or "nginx").strip()
    registry_path = Path(getattr(args, "registry", None) or REGISTRY_PATH)
    confirm = bool(getattr(args, "confirm", False))
    confirmed_by = (getattr(args, "confirmed_by", "") or "").strip()
    # The apply AUTHORITY gate (SPEC-0111 §1) — refuse BEFORE the carrier read, any backup, or any
    # write: a refusal must never leave a half-applied host. The dispatched-session signal is the
    # EXISTING dispatch env (bin/yitc-v2 EXPECTED_SESSION_REF_ENV — the same marker the audit L3
    # auto-consult keys off), never a new detector.
    dispatched = bool(os.environ.get("YITC_EXPECTED_SESSION_REF", "").strip())
    _violation = _confirm_authority_violation(confirm, confirmed_by, dispatched)
    if _violation:
        _die(f"hostapply: {_violation}")
    # The recorded authority: the named directive, or the owner at the terminal on the manual path.
    confirmed_by_recorded = confirmed_by or "owner-interactive"

    # Carrier host_config — the per-project values (SPEC-0093 rule 14 / SPEC-0111 §6). REUSE deploy's reader.
    ops_path = Path(REPO_ROOT) / CONSUMER_OPS_CONTRACT
    if not ops_path.exists():
        _die(f"hostapply: {CONSUMER_OPS_CONTRACT} not found at {REPO_ROOT} — declare a "
             f"`deploy.host_config` block (SPEC-0093) before applying.")
    try:
        ops = state.load_ops(ops_path)
    except yaml.YAMLError as e:  # noqa: BLE001 — fail-closed on an unparseable carrier
        _die(f"hostapply: {CONSUMER_OPS_CONTRACT} failed to parse ({e}); fix the carrier and retry.")
    host_config = _read_host_config(ops.get("deploy") if isinstance(ops, dict) else None)
    if not host_config:
        _die(f"hostapply: no declared `deploy.host_config` block in {CONSUMER_OPS_CONTRACT} (absent or "
             f"waived). Declare {{vhost_files, live_base_url, apply}} (SPEC-0093 rule 14) to apply.")
    targets_decl = [str(v) for v in (host_config.get("vhost_files") or [])]
    apply_recipe = str(host_config.get("apply") or "").strip()
    if not apply_recipe:
        _die("hostapply: carrier deploy.host_config declares no `apply` recipe — nothing to reload.")

    # Resolve each --conf to (src_path, target_path). An explicit `:target` wins; else pair positionally
    # to the carrier vhost_files (the declared owned targets). OWNERSHIP GATE (audit-post HIGH absorb): a
    # resolved target MUST be one the project DECLARED in deploy.host_config.vhost_files — so an explicit
    # `--conf src:/etc/nginx/.../canonical.conf` can NEVER back up + overwrite a vhost the change does not
    # provably own (the direct X-0097 guard; the §2c server_name collision check is a SECOND, independent
    # rail, not the ownership proof). Refuse BEFORE any backup/write.
    plan: list = []
    for i, spec in enumerate(conf_specs):
        src, target = _parse_conf_arg(spec)
        if target is None:
            if i >= len(targets_decl):
                _die(f"hostapply: --conf {spec!r} has no :target and the carrier vhost_files has no entry "
                     f"#{i} to pair it with. Give `src:target` or declare the target in vhost_files.")
            target = targets_decl[i]
        if str(target) not in targets_decl:
            _die(f"hostapply: target {target!r} is NOT declared in deploy.host_config.vhost_files "
                 f"{targets_decl} — the change does not provably OWN it; refusing to back up / overwrite a "
                 f"vhost the project did not declare (the X-0097 guard, SPEC-0111 §2c). Declare the target "
                 f"in vhost_files (proven ownership) before applying.")
        src_path = Path(src)
        if not src_path.exists():
            _die(f"hostapply: shipped conf {src!r} not found — nothing to apply.")
        plan.append((src_path, Path(target)))

    project = (_main_worktree(REPO_ROOT) or Path(REPO_ROOT)).name

    # (a) AUTO-BACKUP every target that already exists (§2a — no write without a recorded backup). A
    #     brand-new target (no prior file) records `None` (nothing to restore — rollback just removes it).
    #     Backups go to a per-run dir OUTSIDE every nginx-included directory (X-0116 — a backup written
    #     next to the target in sites-enabled/ would be re-included as LIVE config). The dir sits under an
    #     explicit safe base (/var/tmp), and is VALIDATED against the live include set before any write —
    #     fail closed if a redirected TMPDIR placed it inside an included tree. Privileged copies (X-0114)
    #     escalate via sudo only when /etc/nginx is not user-writable.
    stamp = _utc_now_iso().replace(":", "").replace("-", "")
    # Discover the live include set FIRST and fail closed if it is unknowable (audit-post: `_included_dirs`
    # returns None on a failed/empty `nginx -T` — never validate against an empty set, which would bypass
    # the X-0116 guard exactly when it is most needed). The whole apply needs a working `nginx -T` anyway
    # (the §4 reconciliation), so requiring it here is consistent, not an extra burden.
    included = _included_dirs(nginx_cmd)
    if included is None:
        _die(f"hostapply: {tid} REFUSED — cannot enumerate the nginx include set (`nginx -T` failed or "
             f"produced no config) via {nginx_cmd!r}; refusing to create backups without proving the "
             f"backup dir sits OUTSIDE the live config tree (X-0116 fail-closed). Fix the nginx invocation "
             f"(--nginx, likely needs sudo on the real host) and retry. No write performed; old config live.")
    backup_dir = Path(tempfile.mkdtemp(prefix=f"yitc-hostapply-{tid}-bak-", dir=str(_backup_base())))
    if _within_any_dir(backup_dir, included):
        _die(f"hostapply: {tid} REFUSED — the backup dir {backup_dir} is INSIDE an nginx-included "
             f"directory ({sorted(included)}); a backup there would be re-included as LIVE config "
             f"(SPEC-0111 §2a / X-0116). No write performed; old config live. Point TMPDIR/-base at a "
             f"location outside the nginx tree and retry.")
    print(f"hostapply-backup-dir: {backup_dir}")
    backups: list = []   # (target, backup_path|None, target_preexisted)
    for _src, target in plan:
        if target.exists():
            bak = backup_dir / _backup_name(target, stamp)
            _priv_copy(target, bak)
            backups.append((target, bak, True))
        else:
            backups.append((target, None, False))
    print(f"hostapply: {tid} — backed up {sum(1 for _t, b, _p in backups if b)} existing target(s) "
          f"(§2a → {backup_dir}); applying {len(plan)} conf(s) to {project}.")

    def _restore() -> None:
        """Roll the targets back to their pre-apply state: restore each backup (or remove a created file).
        Privileged ops (X-0114) escalate via sudo only when the target location is not user-writable."""
        for target, bak, preexisted in backups:
            if preexisted and bak is not None:
                _priv_copy(bak, target)
            elif not preexisted and target.exists():
                _priv_remove(target)

    # (b) COLLISION REFUSAL pre-write (§2c). Build the OTHER-vhost server_name map from the FULL effective
    #     nginx config (`nginx -T` — EVERY included directory, audit-post MEDIUM absorb), so a conflicting
    #     vhost in another included dir cannot slip past. Best-effort fallback: if the dump is empty/
    #     unavailable, scan the target's own directory (the local check is never LOST).
    for src_path, target in plan:
        shipped_names = _server_names(src_path.read_text(encoding="utf-8"))
        other_vhosts = _effective_vhosts(nginx_cmd, exclude=str(target))
        if not other_vhosts:
            for sib in target.parent.glob("*"):
                # Skip the target itself + any `*.bak.<stamp>` LEGACY stray — backups now live OUTSIDE the
                # nginx tree (X-0116), but a pre-fix run may have left one in here; it is not a live vhost.
                if sib.is_file() and sib != target and ".bak." not in sib.name:
                    try:
                        other_vhosts[str(sib)] = _server_names(sib.read_text(encoding="utf-8"))
                    except (OSError, UnicodeDecodeError):
                        continue
        violation = _collision_violation(str(target), shipped_names, other_vhosts)
        if violation:
            print(f"hostapply: {tid} REFUSED (collision) — {violation} No write performed; old config "
                  f"live (exit 3).", file=sys.stderr)
            _restore()   # no write happened yet, but keep the targets pristine (idempotent)
            sys.exit(3)

    # (b2) WRITE each shipped conf into its target (§2b — the rails must verify+apply the NEW config, so
    #      the shipped bytes land BEFORE -t/reload). The target is a path in an nginx-INCLUDED directory
    #      (conf.d/*.conf or sites-enabled/* — the carrier's owned vhost_files), so WRITING the file IS the
    #      §2b enable/include (its presence in the included glob makes it effective) and _restore() —
    #      removing a newly-created target OR reverting a modified one — is the matching DISABLE/UN-include.
    #      So any later fail-path (c / f) reverts the FULL change (content AND inclusion), not just bytes
    #      (the audit-pre HIGH absorb). A brand-new target had no prior file → _restore() removes it.
    for src_path, target in plan:
        target.parent.mkdir(parents=True, exist_ok=True)
        _priv_copy(src_path, target)   # X-0114 — /etc/nginx is root-owned; escalate only when needed

    # (c) nginx -t over the EFFECTIVE config (§2b). The targets are written into the included dir, so -t
    #     now sees the NEW config (the trial finding: a conf not yet included is invisible to -t). A FAIL
    #     ABORTS: _restore() reverts content + inclusion (old config live) and exit 2 — nothing reloaded.
    t = _nginx(nginx_cmd, "-t")
    if t.returncode != 0:
        print(f"hostapply: {tid} ABORT (nginx -t failed) — the proposed config is INVALID; old config "
              f"left live, backups restored (exit 2):\n{(t.stderr or t.stdout).strip()}", file=sys.stderr)
        _restore()
        sys.exit(2)

    # (d) BASELINE server-wide health sweep BEFORE the apply (§3) — the healthy/broken state to compare
    #     against. FAIL CLOSED on a missing inventory (audit-post pass-3 MEDIUM): the server-wide sweep IS
    #     the collateral-safety guarantee, so a None (unreadable/malformed registry) OR an empty domain set
    #     means we cannot validate sibling sites — REFUSE before applying, never a vacuous host_health_
    #     sweep_passed. The targets are written but not yet reloaded → restore + abort (old config live).
    domains = _registry_domains(registry_path)
    if not domains:
        why = ("unreadable/malformed" if domains is None else "readable but lists ZERO domains")
        _restore()
        _die(f"hostapply: {tid} REFUSED — the server-wide health sweep has NO domain inventory "
             f"({registry_path} {why}). A host-config apply's collateral-blast-radius guarantee is the "
             f"server-wide sweep (SPEC-0111 §3); refusing to apply without one (fail-closed). No write "
             f"performed; old config live. Fix/point --registry at the real inventory and retry.")
    baseline = _sweep(domains, opener_factory=_no_redirect_opener)
    print(f"hostapply: {tid} — baseline sweep of {len(domains)} domain(s): "
          f"{sum(1 for h in baseline.values() if h == 'healthy')} healthy.")

    # (e) APPLY — run the carrier `apply` reload recipe (the privileged activate+reload). Output inherited
    #     (the operator must see it live, the deploy.py idiom). A non-zero reload ABORTS like a bad -t.
    print(f"hostapply: {tid} — applying (reload): $ {apply_recipe}")
    reload_rc = subprocess.run(apply_recipe, cwd=str(REPO_ROOT), shell=True).returncode
    if reload_rc != 0:
        print(f"hostapply: {tid} ABORT — apply recipe exited {reload_rc}; restoring backups + reload "
              f"(exit 2).", file=sys.stderr)
        _restore()
        subprocess.run(apply_recipe, cwd=str(REPO_ROOT), shell=True)
        sys.exit(2)

    # SETTLE — `nginx -s reload` is ASYNC (it signals the master and RETURNS immediately; the master then
    # re-reads config + swaps workers). Probing instantly can hit the OLD workers and MISS a real
    # regression — so wait a bounded moment for the reload to take effect BEFORE the post-apply sweep
    # (reliable §3 regression detection; a host-config apply is a rare deliberate op, the settle is cheap).
    time.sleep(_RELOAD_SETTLE_S)

    # (f) AFTER sweep → AUTO-ROLLBACK on any baseline-healthy domain that regressed (§3 — the collateral
    #     blast-radius guard). A baseline-broken domain never triggers (no false rollback). The rollback
    #     restores the §a backups AND re-runs the reload, so the enable/include + file both revert
    #     (audit-pre HIGH absorb — the rollback undoes the FULL change, not just the file).
    after = _sweep(domains, opener_factory=_no_redirect_opener)
    regressed = _regressed_domains(baseline, after)
    if regressed:
        print(f"hostapply: {tid} AUTO-ROLLBACK — domain(s) regressed healthy→broken: {regressed}. "
              f"Restoring backups + reloading (exit 4).", file=sys.stderr)
        _restore()
        subprocess.run(apply_recipe, cwd=str(REPO_ROOT), shell=True)
        sys.exit(4)

    # (g) RECONCILIATION (§4, audit-post HIGH absorb): the live effective config (`nginx -T`) must REFLECT
    #     each shipped conf at its OWN target (shipped == live, per file), AND no other live file may have
    #     clobbered a shipped server_name. Computed per target, not "names appear somewhere".
    dump = _nginx(nginx_cmd, "-T")
    if dump.returncode != 0:
        # The effective-config dump itself failed — we cannot prove shipped==live → fail closed, roll back.
        print(f"hostapply: {tid} ABORT — `nginx -T` (effective-config dump) exited {dump.returncode}; "
              f"cannot reconcile shipped vs live → restoring + reload (exit 4):\n"
              f"{(dump.stderr or '').strip()}", file=sys.stderr)
        _restore()
        subprocess.run(apply_recipe, cwd=str(REPO_ROOT), shell=True)
        sys.exit(4)
    live_dump = dump.stdout or ""
    all_shipped_names: set = set()
    clobbered_by: list = []
    for src_path, target in plan:
        shipped_text = src_path.read_text(encoding="utf-8")
        shipped_names, shipped_parse_error = _parse_server_names(shipped_text)
        rec = _reconciliation_record(shipped_text, str(target), live_dump)
        if rec["parse_error"]:
            # REFUSE rather than record (X-1193): a conf we cannot parse must never reach
            # `host_reconciliation_recorded` as a confident server_names list. Roll back — the
            # reconciliation evidence SPEC-0111 §4 requires cannot be produced for this conf.
            print(f"hostapply: {tid} ABORT — reconciliation cannot parse the shipped conf {src_path}: "
                  f"{rec['parse_error']}. Refusing to record a server_names list read from an "
                  f"unparseable conf; restoring + reload (exit 4).", file=sys.stderr)
            _restore()
            subprocess.run(apply_recipe, cwd=str(REPO_ROOT), shell=True)
            sys.exit(4)
        all_shipped_names |= shipped_names
        if not rec["match"]:
            print(f"hostapply: {tid} ABORT — reconciliation FAILED for {target}: shipped conf not "
                  f"reflected in the live effective config (missing names {rec['missing']} / body mismatch); "
                  f"restoring + reload (exit 4).", file=sys.stderr)
            _restore()
            subprocess.run(apply_recipe, cwd=str(REPO_ROOT), shell=True)
            sys.exit(4)
        clobbered_by.extend(rec["clobbered_by"])
    if clobbered_by:
        # A foreign live file claims a shipped server_name post-apply — a real clobber. Never record a
        # false `clobbered: false`; roll back.
        print(f"hostapply: {tid} ABORT — reconciliation found a CLOBBER: foreign file(s) "
              f"{sorted(set(clobbered_by))} now declare a shipped server_name; restoring + reload (exit 4).",
              file=sys.stderr)
        _restore()
        subprocess.run(apply_recipe, cwd=str(REPO_ROOT), shell=True)
        sys.exit(4)

    # SUCCESS — emit the three task-scoped evidence events, each carrying the provenance tag
    # `emitter: hostapply` (the SPEC-0094 §3 close-gate counts only tagged events — blocks absent/incidental
    # evidence on the operator-trusted journal, not forgery-resistant by design).
    base = {"emitter": HOST_APPLY_EMITTER, "task": tid, "project": project}
    _append_event("host_reconciliation_recorded", tid,
                  {**base, "server_names": sorted(all_shipped_names), "clobbered": False})
    _append_event("host_health_sweep_passed", tid,
                  {**base, "domains_checked": len(domains),
                   "healthy": sum(1 for h in after.values() if h == "healthy")})
    if confirm:
        # `confirmed_by` records the AUTHORIZING DIRECTIVE (SPEC-0111 §1) — distinct from `emitter`,
        # which names only the emitting tool.
        _append_event("apply_confirmed", tid, {**base, "targets": [str(t) for _s, t in plan],
                                               "confirmed_by": confirmed_by_recorded})
    print(f"hostapply: {tid} OK — applied + server-wide sweep clean + reconciled. "
          f"host_reconciliation_recorded + host_health_sweep_passed"
          + (" + apply_confirmed" if confirm else "") + " emitted (SPEC-0111 §5).")
    if not confirm:
        print(f"hostapply: NOTE — apply_confirmed NOT emitted (no --confirm). The host-config close-gate "
              f"(SPEC-0094 §3) will REFUSE until the owner re-runs with --confirm (the human-apply "
              f"confirmation, SPEC-0111 §1).")
