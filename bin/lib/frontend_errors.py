"""Frontend-error triage conveyor — the read-only FOLD half (SPEC-0170, T-10773).

A consumer project captures its frontend errors in its OWN store (project realm — the kernel never
writes it). This module is the PROCESS half (kernel realm): it READS a qualifying project-side
source and folds it by fingerprint into CONFIRMED clusters. Clusters are a DERIVED VIEW — nothing is
copied or stored, kernel-side or consumer-side; every value below is settled by the plan's trial
(`events.jsonl` `trial_run` run_ref=run-1..run-6), not chosen here.

The three rules that carry the design (SPEC-0170 §Parameters):

  * the confirm gate is the error KIND, never volume — on the real stream the noisiest class is also
    the most frequent (transport = 94% of rows), so a count threshold ranks noise first at every
    setting. Transport NEVER confirms.
  * the fingerprint is `kind | normalized message`, with HTTP status codes and error codes EXEMPT
    from digit-normalization (blanket digit-stripping merged 502+504 and ate React `#31`). The
    ENDPOINT is cluster METADATA, never part of the key (keying on it split one transport
    fingerprint into 20).
  * a 30-day rolling window, confirm-threshold 2.

Seam per lessons/library-extraction.md: the engine bodies live here, the argparse `cmd_*` verb stays
in the host `bin/yitc-v2`.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Settled parameters (SPEC-0170 §Parameters — NOT knobs) ──────────────────────────────────────
# Both are SET by the trial and deliberately NOT exposed as CLI flags. `--as-of` / `--all-time` only
# POSITION the same window; they do not resize it.
WINDOW_DAYS = 30            # SET(run-1): 30 days, rolling
CONFIRM_THRESHOLD = 2       # POLICY CHOICE(run-1) inside the observed safe band (2/3/5 equivalent)
SEVERITY_CUT = "error"      # SET(run-1): `error` only; `warning` excluded
LABEL_MAX = 38              # the observed label bound (run-5: 0 labels exceeded it)

# ── The kind cut — the confirm gate (SPEC-0170 §Parameters, "kind cut") ─────────────────────────
KIND_TRANSPORT = "transport"                 # never confirmable
KIND_SERVER_OPAQUE = "server-opaque"         # a bare HTTP 500 carries no signature — not actionable
KIND_OTHER = "other"                         # the fail-SAFE bucket for unfamiliar shapes
KIND_CODE_DEFECT = "code-defect"
KIND_SERVER_DEFECT = "server-defect"
KIND_UNHANDLED_REJECTION = "unhandled-rejection"
KIND_HTTP_CLIENT_ERROR = "http-client-error"

#: The kinds eligible to confirm at all. Everything else can never reach the line, whatever its
#: volume. run-5 proved the cut fails SAFE: 207 rows of shapes the rules were never designed against
#: all classified `other` rather than being mis-binned into a confirmable kind.
CONFIRMABLE_KINDS = frozenset({
    KIND_CODE_DEFECT,
    KIND_SERVER_DEFECT,
    KIND_UNHANDLED_REJECTION,
    KIND_HTTP_CLIENT_ERROR,
})

_TRANSPORT_SIGNATURES = ("failed to fetch", "load failed", "networkerror", "network request failed")
_TRANSPORT_STATUSES = frozenset({"502", "503", "504"})
_OPAQUE_500_BODIES = frozenset({"internal server error", "request failed", ""})

_HTTP_RE = re.compile(r"\bHTTP\s+(\d{3})\s*:\s*(.*)", re.IGNORECASE | re.DOTALL)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_WS_RE = re.compile(r"\s+")


def classify_kind(message: str | None) -> str:
    """Return the SPEC-0170 kind for one raw message. The single confirm gate.

    Ordering matters: transport is tested FIRST (a `Failed to fetch` is transport whatever else the
    message carries), then the HTTP-status branch, then the frontend markers.
    """
    msg = _WS_RE.sub(" ", (message or "")).strip()
    low = msg.lower()

    if any(sig in low for sig in _TRANSPORT_SIGNATURES):
        return KIND_TRANSPORT

    m = _HTTP_RE.search(msg)
    if m:
        status, body = m.group(1), m.group(2).strip()
        if status in _TRANSPORT_STATUSES:
            return KIND_TRANSPORT
        if status == "500":
            # A bare 500 carries no signature the owner can act on; a 500 that names its cause does.
            return KIND_SERVER_OPAQUE if body.lower() in _OPAQUE_500_BODIES else KIND_SERVER_DEFECT
        if status.startswith("4"):
            return KIND_HTTP_CLIENT_ERROR
        if status.startswith("5"):
            return KIND_SERVER_OPAQUE
        return KIND_OTHER

    if low.startswith("[unhandledrejection]"):
        return KIND_UNHANDLED_REJECTION
    if low.startswith("[react render]") or low.startswith("uncaught"):
        return KIND_CODE_DEFECT
    return KIND_OTHER


# ── Fingerprint (SPEC-0170 §Parameters, "fingerprint shape") ────────────────────────────────────
# Digit runs are masked so per-row identifiers do not split a cluster — but HTTP status codes and
# error codes are EXEMPT, because masking them merged 502+504 into one fingerprint and turned
# `React error #31` into `React error #N` (run-1's over-collapse finding, re-verified in run-2).
_EXEMPT_RE = re.compile(r"(\bHTTP\s+\d{3}\b|#\d+\b)", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\d+")


def normalize_message(message: str | None) -> str:
    """Collapse a raw message to its identity: whitespace folded, UUIDs and free numbers masked,
    HTTP status codes and error codes preserved verbatim."""
    msg = _WS_RE.sub(" ", (message or "")).strip()
    msg = _UUID_RE.sub("<uuid>", msg)
    parts = _EXEMPT_RE.split(msg)
    # split() with one capturing group alternates non-match / match / non-match / ...
    return "".join(
        part if i % 2 else _DIGITS_RE.sub("<n>", part)
        for i, part in enumerate(parts)
    )


def fingerprint(message: str | None, kind: str | None = None) -> str:
    """`kind | normalized message`. The endpoint is NEVER part of the key — it rides the cluster as
    metadata (keying on it split one transport fingerprint into 20 — run-1's under-collapse)."""
    k = kind if kind is not None else classify_kind(message)
    return f"{k}|{normalize_message(message)}"


# ── Label extraction — what makes a cluster readable ────────────────────────────────────────────
_LABEL_RULES = (
    re.compile(r"\(\s*[\w.]*errors?\.(?P<v>\w+)\s*\)"),                  # (psycopg2.errors.UniqueViolation)
    re.compile(r"(?P<v>React error #\d+)", re.IGNORECASE),               # React error #31
    re.compile(r"type object '(?P<v>[^']+)' has no attribute"),          # PhraseFunnelSnapshot
    re.compile(r"(?P<v>[\w'\". ]{1,%d}?) is not defined" % LABEL_MAX),   # setHelpOpen / name 'ln'
)
_PREFIX_RE = re.compile(r"^(\[[^\]]+\]\s*)?(HTTP\s+\d{3}\s*:\s*)?(Uncaught\s+\w+(Error)?\s*:\s*)?",
                        re.IGNORECASE)


def extract_label(message: str | None) -> str:
    """A short human signature for a cluster — the ROOT error class where the message carries one.

    run-2 observed the point of this: `This Session's transaction has been rolled back ...` labels as
    its CAUSE, `UniqueViolation`, rather than as the symptom.
    """
    msg = _WS_RE.sub(" ", (message or "")).strip()
    for rule in _LABEL_RULES:
        m = rule.search(msg)
        if m:
            return m.group("v").strip()
    payload = _PREFIX_RE.sub("", msg, count=1).strip() or msg
    payload = _UUID_RE.sub("<uuid>", payload)
    return payload[:LABEL_MAX].rstrip()


# ── The fold ────────────────────────────────────────────────────────────────────────────────────
def _parse_ts(raw) -> "datetime | None":
    """Parse an ISO-8601 timestamp (or pass a datetime through), naive → UTC. None if unreadable.

    FAITHFUL, never fail-closed (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): it
    reports only what the value literally says, and each READER decides what None means — `_row_time`
    drops the row from the window, `fold_acks` drops the ack (so the cluster stays VISIBLE, the safe
    direction: an unreadable ack must never suppress anything).
    """
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, str) and raw.strip():
        txt = raw.strip()
        txt = txt.replace(" ", "T", 1) if " " in txt[:11] else txt
        try:
            dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _row_time(row: dict) -> datetime | None:
    """The row's occurrence time. Timestamp parsing has ONE home — `_parse_ts` (T-10777, CHARTER §P5):
    the ack fold compares an event `ts` against a cluster's `last_seen`, so the two must be read by the
    same parser or the comparison that carries the whole ack contract would rest on two rules."""
    return _parse_ts(row.get("occurred_at"))


def window_bounds(as_of: datetime, *, all_time: bool = False) -> tuple[datetime | None, datetime]:
    """The rolling 30-day window ending `as_of` (start is None for the all-time positioning)."""
    end = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    return (None if all_time else end - timedelta(days=WINDOW_DAYS)), end


def fold(rows, *, as_of: datetime, all_time: bool = False):
    """Fold raw source rows into CONFIRMED clusters — a derived view, nothing stored.

    Returns `(clusters, stats)`. Each cluster is a dict carrying `fingerprint`, `kind`, `label`,
    `count`, `first_seen`, `last_seen`, `endpoints` (METADATA) and `row_ids` (the provenance chain
    back to the captured rows). Clusters sort by count desc, then label.
    """
    start, end = window_bounds(as_of, all_time=all_time)
    groups: dict[str, dict] = {}
    stats = {"scanned": 0, "in_window": 0, "severity_cut": 0, "kind_cut": 0, "candidates": 0}

    for row in rows:
        stats["scanned"] += 1
        ts = _row_time(row)
        if ts is None or ts > end or (start is not None and ts < start):
            continue
        stats["in_window"] += 1
        if str(row.get("severity") or "").strip().lower() != SEVERITY_CUT:
            stats["severity_cut"] += 1
            continue
        message = row.get("message")
        kind = classify_kind(message)
        if kind not in CONFIRMABLE_KINDS:
            stats["kind_cut"] += 1
            continue
        stats["candidates"] += 1
        fp = fingerprint(message, kind)
        g = groups.get(fp)
        if g is None:
            g = groups[fp] = {
                "fingerprint": fp,
                "kind": kind,
                "label": extract_label(message),
                "count": 0,
                "first_seen": ts,
                "last_seen": ts,
                "endpoints": [],
                "row_ids": [],
            }
        g["count"] += 1
        g["first_seen"] = min(g["first_seen"], ts)
        g["last_seen"] = max(g["last_seen"], ts)
        endpoint = _endpoint_of(row)
        if endpoint and endpoint not in g["endpoints"]:
            g["endpoints"].append(endpoint)
        rid = row.get("id")
        if rid is not None:
            g["row_ids"].append(str(rid))

    clusters = [g for g in groups.values() if g["count"] >= CONFIRM_THRESHOLD]
    clusters.sort(key=lambda g: (-g["count"], g["label"]))
    stats["fingerprints"] = len(groups)
    stats["confirmed"] = len(clusters)
    stats["window_start"] = None if start is None else start.isoformat()
    stats["window_end"] = end.isoformat()
    return clusters, stats


_PATH_SUFFIX_RE = re.compile(r"\s*\(fail-\d+ms\)\s*$")


def _endpoint_of(row: dict) -> str:
    """The endpoint as cluster METADATA: method + path with row ids and the timing/retry suffix
    normalized away (the raw `request_path` carries `(fail-11ms)` + UUIDs — run-1)."""
    path = str(row.get("request_path") or "").strip()
    if not path:
        return ""
    path = _PATH_SUFFIX_RE.sub("", path)
    path = _UUID_RE.sub("<uuid>", path)
    method = str(row.get("request_method") or "").strip()
    first = path.split(" ", 1)[0]
    if method and not (first.isupper() and first.isalpha()):
        return f"{method} {path}"
    return path


# ── The reader — the ONE source path, strictly read-only (AC2) ──────────────────────────────────
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_SELECT_COLUMNS = "id, occurred_at, severity, message, request_path, request_method"


class SourceError(RuntimeError):
    """The source could not be read (bad identifier, container down, psql failure)."""


def validate_table(table: str) -> str:
    """Fail-closed identifier check for the caller-supplied table.

    A table name is an IDENTIFIER, so it cannot be bound as a query parameter — it is validated
    against an explicit allowlist shape (optionally one `schema.` qualifier) and REFUSED otherwise.
    Anything carrying a quote, semicolon, space or comment marker never reaches the SQL text.
    """
    parts = (table or "").split(".")
    if len(parts) > 2 or not all(_IDENT_RE.match(p or "") for p in parts):
        raise SourceError(
            f"refusing table identifier {table!r}: expected [schema.]name matching "
            f"[A-Za-z_][A-Za-z0-9_]* (an identifier cannot be parameterized, so it is allowlisted)")
    return ".".join(parts)


def build_select(table: str) -> str:
    """The single read-only statement. The literal `source` value is NEVER interpolated: it is bound
    as the psql variable `src` and referenced as `:'src'`, which psql quotes and escapes itself."""
    safe = validate_table(table)
    return (
        "BEGIN READ ONLY; "
        f"SELECT coalesce(json_agg(t), '[]'::json) FROM (SELECT {_SELECT_COLUMNS} "
        f"FROM {safe} WHERE source = :'src') t; "
        "COMMIT;"
    )


def psql_invocation(container: str, table: str, source_value: str) -> tuple[list[str], str]:
    """The exact `(argv, sql)` pair.

    argv is a LIST run with NO shell, so neither the container name nor the source value can be
    word-split or expanded on the way out. The source value travels as a container ENV var
    (`docker exec -e`, itself an argv element) and is turned into a properly quoted SQL literal by
    psql's own `:'src'` variable interpolation — it is never spliced into the statement text.
    """
    argv = [
        "docker", "exec", "-i",
        "-e", f"YITC_FE_SRC={source_value}",
        container,
        "sh", "-c",
        'exec psql -X -q -t -A -v ON_ERROR_STOP=1 -v "src=$YITC_FE_SRC" '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -',
    ]
    return argv, build_select(table)


def read_rows(container: str, *, table: str = "system_errors", source_value: str = "frontend",
              timeout: int = 120) -> list[dict]:
    """Read the qualifying source READ-ONLY. The only source path in this module.

    There is no INSERT / UPDATE / DELETE / DDL path here at all: the statement is built by
    `build_select` and wrapped `BEGIN READ ONLY`, so the server itself refuses a write even if one
    were ever constructed.
    """
    argv, sql = psql_invocation(container, table, source_value)
    try:
        proc = subprocess.run(argv, input=sql, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:                      # pragma: no cover - environment fault
        raise SourceError(f"docker not available: {exc}") from exc
    except subprocess.TimeoutExpired as exc:              # pragma: no cover - environment fault
        raise SourceError(f"reading {container}:{table} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise SourceError(
            f"reading {container}:{table} failed (exit {proc.returncode}): "
            f"{(proc.stderr or '').strip()[:400]}")
    payload = "".join(ln for ln in proc.stdout.splitlines() if ln.strip().startswith(("[", "{", '"')))
    if not payload.strip():
        return []
    try:
        rows = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SourceError(f"source returned unparseable JSON: {exc}") from exc
    return list(rows or [])


# ── The qualifying-source PREFLIGHT (SPEC-0170 §Internal item 1, T-10774) ───────────────────────
# The six-property INPUT CONTRACT, evaluated MECHANICALLY over the source a consumer declares beside
# its `- spec: SPEC-0170` entry in the EXISTING SPEC-0093 declare-or-waive carrier. It rides that
# declaration and adds NO checker, store, FSM or config surface of its own (CHARTER §P1 F1/F2) — the
# refusals below are returned as plain strings and joined into the SAME `unanswered` list every other
# declare-or-waive violation rides (bin/lib/init.py `_hook_extensions`).
#
# WHAT IT REMOVES (F3): SILENT non-adoption. Today a consumer whose source the kernel cannot actually
# read would see exactly what a HEALTHY consumer sees — an empty line — so permanent silence is
# indistinguishable from health. The preflight makes that case say WHY, naming the failing property.
#
# The properties are not invented here: they are this module's own reader contract restated as an
# admission test. `read_rows` needs a consumer-owned store it can query for an arbitrary window and
# `fold` needs a row id (provenance), a message (the fingerprint input) and a timestamp — so a source
# that cannot answer those cannot be folded, whatever it promises.

PROP_CONSUMER_OWNED = "consumer-owned"
PROP_DURABLE = "durable"
PROP_QUERYABLE = "queryable-across-fold-window"
PROP_PROVENANCE = "provenance-preserving"
PROP_FINGERPRINTABLE = "fingerprintable"
PROP_COVERS = "covers-in-scope-classes"

#: The canonical six. Order is the contract's own (SPEC-0170 §Internal item 1).
QUALIFYING_PROPERTIES = (
    PROP_CONSUMER_OWNED, PROP_DURABLE, PROP_QUERYABLE,
    PROP_PROVENANCE, PROP_FINGERPRINTABLE, PROP_COVERS,
)

#: What a source KIND can attest STRUCTURALLY — a closed table, never a free-text claim. Measured
#: against the real consumers during the plan's trial: `postgres-table` is aiseller's `system_errors`
#: (run-3, 5 PASS + 1 PARTIAL — the ONE kind this module has a reader for); the other three are the
#: shapes boomrocket and social-parser actually capture into (run-2 / run-6). A source kind the kernel
#: has no reader for cannot attest queryability by declaring it.
_SOURCE_KIND_CAPABILITIES = {
    # kind:            (consumer-owned, durable, queryable)
    "postgres-table":  (True,  True,  True),
    "log-line":        (True,  False, False),   # unstructured, rotates, no window query
    "alert-forward":   (True,  False, False),   # fire-and-forget: forwarded, never persisted
    "external-saas":   (False, False, False),   # another party's store, outside kernel territory
}

_KIND_WHY = {
    "log-line": "an unstructured log line rotates away and cannot be queried for a window",
    "alert-forward": "a fire-and-forget forward to an alert channel persists nothing",
    "external-saas": "an external SaaS store is not the consumer's own and the kernel cannot read it",
}


def _declared(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def qualifying_source_violations(source, *, label: str = "source") -> list:
    """Evaluate the six-property contract. Returns ONE refusal string per FAILING property, each
    NAMING that property (empty list = the source qualifies). PURE: no I/O, no raise.

    FAIL-CLOSED throughout, and deliberately so: an ABSENT or empty declaration is REFUSED on every
    property rather than passed, because "nothing declared" is precisely the state that would adopt the
    conveyor over an unreadable source and then read permanent silence as health. Likewise an UNKNOWN
    `kind:` fails the three structural properties — the kernel can attest nothing about a shape it has
    no reader for.
    """
    # Reasons are COLLECTED per property and rendered once at the end — a property can fail for more
    # than one reason (a postgres-table missing BOTH its `window_field` and its `container` fails
    # `queryable` twice over), and emitting one line per REASON would read as more failing properties
    # than there are. One property, one refusal, every reason inside it.
    reasons: dict = {}

    def _refuse(prop: str, why: str) -> None:
        reasons.setdefault(prop, []).append(why)

    def _rendered() -> list:
        return [f"{label}: FAILS `{prop}` — {'; also '.join(reasons[prop])} (the six-property "
                f"qualifying-source contract, SPEC-0170 §Internal item 1)"
                for prop in QUALIFYING_PROPERTIES if prop in reasons]

    if not isinstance(source, dict) or not source:
        for prop in QUALIFYING_PROPERTIES:
            _refuse(prop, "no qualifying source is declared at all, so this property is unproven; "
                          "declare a `source:` mapping (kind/container/table/row_id_field/window_field/"
                          "message_field/retention_days/classes) or do not adopt SPEC-0170")
        return _rendered()

    kind = _declared(source.get("kind"))
    caps = _SOURCE_KIND_CAPABILITIES.get(kind)

    # (1)(2)(3) the STRUCTURAL properties — settled by the kind, not by a claim about it.
    if caps is None:
        why_tail = (f"source kind {kind!r} has no kernel reader" if kind
                    else "no `kind:` is declared")
        known = " | ".join(sorted(_SOURCE_KIND_CAPABILITIES))
        for prop in (PROP_CONSUMER_OWNED, PROP_DURABLE, PROP_QUERYABLE):
            _refuse(prop, f"{why_tail}, so the kernel can attest nothing about it (declare one of: "
                          f"{known})")
    else:
        owned, durable, queryable = caps
        why = _KIND_WHY.get(kind, f"source kind {kind!r} does not provide it")
        if not owned:
            _refuse(PROP_CONSUMER_OWNED, why)
        if not durable:
            _refuse(PROP_DURABLE, why)
        if not queryable:
            _refuse(PROP_QUERYABLE, why)

    # (2b) durability is ALSO a retention question: a store that keeps less than the fold window
    # cannot answer the window the conveyor folds over.
    if caps and caps[1]:
        retention = source.get("retention_days")
        if not isinstance(retention, int) or isinstance(retention, bool) or retention < WINDOW_DAYS:
            _refuse(PROP_DURABLE, f"`retention_days:` is {retention!r} — the fold window is "
                                  f"{WINDOW_DAYS} days, so a shorter (or undeclared) retention cannot "
                                  f"cover it")

    # (3b) queryability needs the timestamp column the window is a query OVER, plus — for the one
    # readable kind — the container + a table identifier this module can actually address. The
    # identifier rule has ONE home: `validate_table` (CHARTER §P5), reused here rather than restated.
    if caps and caps[2]:
        if not _declared(source.get("window_field")):
            _refuse(PROP_QUERYABLE, "no `window_field:` (the timestamp column) is declared, so the "
                                    "fold window cannot be expressed as a query")
        if kind == "postgres-table":
            if not _declared(source.get("container")):
                _refuse(PROP_QUERYABLE, "no `container:` is declared, so the kernel has no address to "
                                        "read the table from")
            table = _declared(source.get("table"))
            if not table:
                _refuse(PROP_QUERYABLE, "no `table:` is declared")
            else:
                try:
                    validate_table(table)
                except SourceError as exc:
                    _refuse(PROP_QUERYABLE, str(exc))

    # (4) provenance — the cluster→row chain `fold` carries in `row_ids`.
    if not _declared(source.get("row_id_field")):
        _refuse(PROP_PROVENANCE, "no `row_id_field:` is declared, so a confirmed cluster could not "
                                 "chain back to the rows that produced it")

    # (5) fingerprintable — the message IS the fingerprint input (`kind | normalized message`).
    if not _declared(source.get("message_field")):
        _refuse(PROP_FINGERPRINTABLE, "no `message_field:` is declared, and the fingerprint is "
                                      "`kind | normalized message` — without it there is nothing to "
                                      "fold on")

    # (6) coverage — the "not one narrow slice" half. The in-scope classes are the CONFIRMABLE kinds:
    # a source capturing only one of them (boomrocket captures React render crashes only — run-2)
    # silently hides the classes it never sees, which is a narrower failure than seeing nothing.
    classes = source.get("classes")
    declared_classes = {c.strip() for c in classes if isinstance(c, str) and c.strip()} \
        if isinstance(classes, list) else set()
    missing = sorted(CONFIRMABLE_KINDS - declared_classes)
    if missing:
        have = ", ".join(sorted(declared_classes)) or "none"
        _refuse(PROP_COVERS, f"declared classes cover {have}; the in-scope error classes this conveyor "
                             f"confirms also include {', '.join(missing)} — a source covering one narrow "
                             f"slice hides the classes it never captures")
    return _rendered()


# ── The DECLARED source — one home for "which source does this consumer adopt?" (T-10776) ───────
# The declaration ALREADY exists: the SPEC-0093 `extensions.adopts[] { spec: SPEC-0170, source: … }`
# entry T-10774/T-10775 gate. Nothing new is declared here — this is the READ of that same entry, so
# the echo and the bare re-fold verb address the source the carrier already names instead of asking
# their caller to re-type `--pg-container`/`--table` (which is what made the re-fold un-runnable in
# the shape a post-`/compact` re-fold has to take: bare, like `debt` / `cross outbox`).

EXTENSION_SPEC_ID = "SPEC-0170"


def declared_source(ops, *, spec_id: str = EXTENSION_SPEC_ID) -> tuple:
    """Return `(source, violations)` for THIS repo's adoption of the conveyor. PURE: no I/O, no raise.

    * not adopted at all (no carrier section, no matching `adopts[]` entry) → `(None, [])` — an
      absence, NOT a violation: a consumer that never adopted owes nothing.
    * adopted → `(source_mapping, qualifying_source_violations(source))`. A NON-EMPTY violations list
      is the SPEC-0171 §Scenario "scoped promise" case: this consumer must never be served the same
      silence a healthy one gets, so the caller REPORTS the reason instead of suppressing.
    """
    if not isinstance(ops, dict):
        return None, []
    ext = ops.get("extensions")
    adopts = ext.get("adopts") if isinstance(ext, dict) else None
    if not isinstance(adopts, list):
        return None, []
    for entry in adopts:
        if not isinstance(entry, dict):
            continue
        sp = entry.get("spec")
        if isinstance(sp, str) and sp.strip() == spec_id:
            source = entry.get("source")
            return source, qualifying_source_violations(source, label="frontend-errors source")
    return None, []


def read_kwargs(source) -> dict:
    """The declared source rendered as `read_rows` keyword arguments. Called ONLY after
    `declared_source` returned no violations, so the required keys are known present."""
    src = source if isinstance(source, dict) else {}
    kwargs = {"table": _declared(src.get("table")) or "system_errors"}
    value = _declared(src.get("source_value"))
    if value:
        # OPTIONAL and deliberately outside the six-property contract: it selects rows WITHIN an
        # already-qualifying store, so it can never make an unreadable source qualify.
        kwargs["source_value"] = value
    return dict(container=_declared(src.get("container")), **kwargs)


# ── The ACK marker (SPEC-0170 §Parameters "TTL / ack", T-10777) ─────────────────────────────────
# The trial MEASURED the need and nothing else: two clusters (`PhraseFunnelSnapshot`, `React error #31`)
# stayed confirmed on EVERY session start for the window's full 30 days, five more ran 21-25 days. Without
# an ack the only ways to silence a KNOWN-and-not-being-fixed cluster are to fix it or to wait a month —
# which is how a report-only line becomes noise its reader learns to skip.
#
# The whole risk of an ack is that it becomes a way to HIDE a live defect, so the suppression is NOT a
# stored state that could outlive its judgement. It is a COMPARISON, re-evaluated on every fold, against
# evidence that keeps arriving: an acked cluster is hidden only while `last_seen <= acked_at`. The first
# occurrence AFTER the ack moves `last_seen` past it and the cluster is back on the line, unasked. There
# is therefore no reachable state in which an acked cluster recurs and stays invisible.
#
# The marker rides the SPEC-0095 followup shape wholesale: APPEND-ONLY journal events + a derived fold,
# NO store, NO table, NO file, NO status field, NO FSM (CHARTER §P1 F1/F2 — the one journal mechanism,
# `bin/lib/followup.py#_fold` / `bin/lib/cross.py` are the two prior instances). The event name is
# namespaced because `cross_acked` already exists on the cross channel.

ACK_EVENT = "frontend_error_acked"


def fold_acks(events_path) -> dict:
    """Fold the journal into `{fingerprint: latest acked_at datetime}` — the SPEC-0095 derived-fold
    shape. LAST WRITE WINS (re-acking a recurred cluster moves its ack forward, which is the whole
    point of re-acking). P5-safe: a missing file, an unparseable line, a non-mapping event, a
    fingerprint-less or unreadable-timestamp ack are all SKIPPED, never raised — an informational
    surface must not break on a malformed journal line.

    The ack timestamp is the EVENT's own `ts` (the journal envelope), not a payload field a caller
    could set: an ack is stamped when it happens, so it cannot be back-dated into suppressing a
    recurrence that already arrived.
    """
    acks: dict = {}
    p = Path(events_path)
    if not p.exists():
        return acks
    from lib import journal as journal_mod   # T-11444: LOCAL import — this module is loaded
                                             # STANDALONE by its own tests (by file path, no
                                             # `bin/` on sys.path), so a module-level import
                                             # would break that load (the worktree.py idiom).
    for line in journal_mod.segment_lines(p, errors="replace"):  # T-11444: segment-aware fold (SPEC-0190 r4)
        line = line.strip()
        if not line or ACK_EVENT not in line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if not isinstance(ev, dict) or ev.get("type") != ACK_EVENT:
            continue
        data = ev.get("data")
        fp = (data or {}).get("fingerprint") if isinstance(data, dict) else None
        ts = _parse_ts(ev.get("ts"))
        if not isinstance(fp, str) or not fp.strip() or ts is None:
            continue
        prev = acks.get(fp.strip())
        if prev is None or ts > prev:
            acks[fp.strip()] = ts
    return acks


def apply_acks(clusters, acks) -> tuple:
    """Split confirmed clusters into `(visible, suppressed)`. PURE: no I/O, no raise.

    A cluster is SUPPRESSED iff it carries an ack AND has NOT recurred since it — `last_seen <=
    acked_at`. The comparison is the safety property: suppression is derived fresh on every fold from
    the cluster's own newest occurrence, so it can never outlive the judgement that produced it. A
    cluster whose newest occurrence is AFTER its ack is returned to `visible` with no further act.
    """
    visible, suppressed = [], []
    marks = acks if isinstance(acks, dict) else {}
    for c in clusters:
        at = marks.get(c.get("fingerprint"))
        last = c.get("last_seen")
        if at is not None and isinstance(last, datetime) and last <= at:
            suppressed.append({**c, "acked_at": at})
        else:
            visible.append(c)
    return visible, suppressed


def visible_clusters(rows, *, as_of: datetime, events_path=None, all_time: bool = False) -> tuple:
    """The WHOLE read path from raw source rows to what a reader is shown:
    `(visible, suppressed, stats)`.

    ONE HOME for the fold → ack-fold → ack-apply sequence (CHARTER §P5, T-10803). Before this, the
    on-demand verb, the session-start echo and (now) the cadence sweep each inlined the same three
    calls in the same order — three copies of a pipeline whose whole contract is that they AGREE. A
    cadence that reported a DIFFERENT confirmed set from the view its reader re-folds by hand would be
    worse than no cadence at all, so the agreement is made STRUCTURAL here rather than asserted by
    hope in three places.

    `events_path=None` means "no journal to read", which suppresses nothing — the safe direction (an
    unreadable ack must never hide a cluster). Pure composition: no new behaviour, no store."""
    clusters, stats = fold(rows, as_of=as_of, all_time=all_time)
    visible, suppressed = apply_acks(clusters, fold_acks(events_path) if events_path else {})
    return visible, suppressed, stats


def _match_clusters(pool, token: str) -> list:
    """Every cluster in `pool` whose FINGERPRINT or LABEL is exactly `token`.

    ONE matcher, shared by both resolvers below (CHARTER §P5): ack and promote differ only in WHICH
    clusters they admit, never in how a token is matched. A label is a short human signature and may
    legitimately be shared by two clusters — which is why both callers must handle >1 hit rather than
    silently take the first.
    """
    return [c for c in pool if c.get("fingerprint") == token or c.get("label") == token]


def resolve_ack_target(visible, suppressed, token: str) -> tuple:
    """Resolve an ack token to ONE cluster fingerprint. Returns `(fingerprint, error)` — exactly one is
    non-None. PURE: no I/O, no raise (the caller owns how to report a refusal).

    Resolution runs over the VISIBLE clusters ONLY (audit-pre finding 1): what the line SHOWS is what
    can be acked. Two things follow, and both matter — an already-acked cluster cannot be re-acked into
    a further-forward ack timestamp while it has produced nothing new (which would quietly stretch its
    mute), and a RECURRED cluster is visible again, so re-acking it is precisely the supported act.

    A token matching only a SUPPRESSED cluster gets that stated, not a bare "no such cluster": the two
    are different situations and only one of them is a mistake.
    """
    tok = (token or "").strip()
    if not tok:
        return None, "an ack needs a cluster to ack: pass its label or its fingerprint"
    hits = _match_clusters(visible, tok)
    if len(hits) == 1:
        return hits[0]["fingerprint"], None
    if len(hits) > 1:
        cands = "; ".join(sorted(c["fingerprint"] for c in hits))
        return None, (f"{tok!r} matches {len(hits)} confirmed clusters — ack by FINGERPRINT to pick "
                      f"one: {cands}")
    already = _match_clusters(suppressed, tok)
    if already:
        return None, (f"{tok!r} is already acked ({already[0]['acked_at'].date()}) and has not recurred "
                      f"since — it is not on the line, so there is nothing to ack. It returns by itself "
                      f"on its next occurrence")
    known = ", ".join(c["label"] for c in visible) or "(none — nothing is confirmed right now)"
    return None, f"no confirmed cluster matches {tok!r}. On the line: {known}"


# ── PROMOTION — a confirmed cluster becomes work (SPEC-0170 §Internal item 3, T-10779) ──────────
# The fence FIRST, because it is the whole design constraint: **the sweep triages and REPORTS; it
# never promotes work** (CHARTER §6 / SPEC-0170 §Internal item 3). So there is no promoting code on
# the fold path at all — `fold` / `echo_lines` / `render` cannot reach anything here. Promotion is
# reachable ONLY from an explicit argv act (`frontend-errors --promote <cluster>`), which is why it
# needs no threshold, no schedule and no "should I promote?" judgement anywhere: an act that must be
# typed cannot fire on its own.
#
# The CARRIER is the EXISTING `followup` (SPEC-0095) — the plan's own prior-art table names it, and
# it already owns the open->promoted leg into a task card with a MANDATORY `--into T-XXXX` (X-0165).
# Nothing here re-implements that leg: this half only turns a cluster into the followup's text plus
# ONE declared key, `fingerprint`.
#
# WHY THE FINGERPRINT TRAVELS AS ITS OWN KEY, never inside the prose: the promoted card's provenance
# is machine-checked at the promote leg, and routing a decision off free-text is the mistake
# `lessons/report-only-advisory-never-exempts-a-contradiction` rule 1 records (and `awaits` paid for
# in T-10335). Declared, never guessed.

def resolve_promote_target(visible, suppressed, token: str) -> tuple:
    """Resolve a promote token to ONE cluster. Returns `(cluster, error)` — exactly one is non-None.
    PURE: no I/O, no raise.

    The admission set is DELIBERATELY WIDER than the ack resolver's: visible AND acked clusters, in
    that order. An ack silences a cluster; it does not un-KNOW it, and "I muted this, now I am fixing
    it" is precisely the promote a reader of `--acked` is going to make. Ack, by contrast, resolves
    over the visible set only — because re-acking a suppressed cluster would stretch a mute over
    evidence that has not moved, which is a different act with a different hazard.
    """
    tok = (token or "").strip()
    if not tok:
        return None, ("promoting needs a cluster to promote: pass its label or its fingerprint "
                      "(`frontend-errors` lists what is confirmed; `--acked` lists what is muted)")
    pool = list(visible) + list(suppressed or [])
    hits = _match_clusters(pool, tok)
    if len(hits) == 1:
        return hits[0], None
    if len(hits) > 1:
        cands = "; ".join(sorted(c["fingerprint"] for c in hits))
        return None, (f"{tok!r} matches {len(hits)} confirmed clusters — promote by FINGERPRINT to "
                      f"pick one: {cands}")
    known = ", ".join(c["label"] for c in pool) or "(none — nothing is confirmed right now)"
    return None, (f"no confirmed cluster matches {tok!r}. Promotable (confirmed, incl. acked): "
                  f"{known}")


def promotion_capture(cluster) -> dict:
    """The followup this cluster becomes: `{"text": ..., "fingerprint": ..., "relates_to": ...}`.

    PURE — it builds the capture, it does not perform it (the host appends it through the EXISTING
    `followup add` body, so there is no second capture path). The text is what a reader sees months
    later in `followup list`, so it carries the cluster's own judgement evidence — label, kind, count
    and the window it recurred over — and the FINGERPRINT rides its own key, the handle that walks
    back to the cluster and (via `--json`) to its source `row_ids`.
    """
    c = cluster or {}
    fp = str(c.get("fingerprint") or "")
    seen = ""
    first, last = c.get("first_seen"), c.get("last_seen")
    if isinstance(first, datetime) and isinstance(last, datetime):
        seen = f", {first.date()}..{last.date()}"
    return {
        "text": (f"frontend error confirmed: {c.get('label')} ×{c.get('count')} "
                 f"[{c.get('kind')}{seen}] — fingerprint {fp}"),
        "fingerprint": fp,
        # PROVENANCE (`relates_to`) is the fingerprint too, so `followup list`'s existing `[relates:]`
        # column shows the chain without this module teaching that view a new field. It is never the
        # thing the promote gate reads — that reads the DECLARED `fingerprint` key (T-10335's lesson).
        "relates_to": fp,
    }


def render_promotion(cluster, followup_id: str, *, cli_hint: str) -> list:
    """The next-step lines printed after a capture. The hand-off is TWO governed verbs and this says
    so explicitly, because the card must be filed CARRYING THE FINGERPRINT — `followup promote` will
    refuse a card that does not, and a refusal the reader was never told how to avoid is a trap."""
    c = cluster or {}
    fp = c.get("fingerprint")
    return [
        f"promoted to a followup: {followup_id} — {c.get('label')} ×{c.get('count')}",
        f"  fingerprint: {fp}",
        "  next (promotion is a TWO-verb owner act — nothing files a task on your behalf):",
        f"    1. {cli_hint} task file …  — the card MUST carry the fingerprint above (put it in the "
        f"description/scope), else step 2 refuses: that string is how the card walks back to the "
        f"cluster and its source rows",
        f"    2. {cli_hint} followup promote {followup_id} --into T-XXXX",
        f"  the cluster and its source row ids stay resolvable: `{cli_hint} frontend-errors --json`",
    ]


# ── Rendering ───────────────────────────────────────────────────────────────────────────────────
def render(clusters, stats, *, all_time: bool = False, suppressed=None) -> list[str]:
    """Human view lines. NOTE the deliberate difference from the session-start ECHO (T-10776): an
    explicitly-invoked view states its silence instead of printing nothing, because a view verb that
    answers an explicit question with total silence is indistinguishable from a broken one.
    Suppressed-when-clean is the ECHO's contract, not this verb's.

    ACKED clusters (T-10777) are passed as `suppressed` and reported as a COUNTED TAIL, never dropped:
    the echo is where an ack buys silence, but an explicitly-invoked view that answered "0 confirmed"
    while holding acked clusters would be hiding them from the one reader who asked. `--acked` renders
    them in full."""
    scope = "all time" if all_time else f"the {WINDOW_DAYS}-day window ending {stats['window_end'][:10]}"
    muted = list(suppressed or [])
    tail = ([f"  ({len(muted)} acked, not recurred since — `--acked` to see them, they return by "
             f"themselves on their next occurrence)"] if muted else [])
    if not clusters:
        return [f"frontend-errors: (silent) — 0 confirmed clusters over {scope} "
                f"({stats['in_window']} row(s) scanned)"] + tail
    head = f"frontend-errors: {len(clusters)} confirmed over {scope}"
    lines = [head]
    for c in clusters:
        endpoints = ", ".join(c["endpoints"][:2]) or "-"
        lines.append(
            f"  {c['label']} ×{c['count']}  [{c['kind']}]  "
            f"{c['first_seen'].date()}..{c['last_seen'].date()}  {endpoints}")
    return lines + tail


def render_acked(suppressed) -> list[str]:
    """The `--acked` view: what an ack is currently silencing, and since when. Report-only.

    An ack the owner cannot LIST is a mute with no audit surface — the shape that turns "quiet" into
    "unaccountable". Each row states the ack date beside the cluster's own last occurrence, which is
    exactly the pair the suppression predicate compares."""
    muted = list(suppressed or [])
    if not muted:
        return ["frontend-errors: no acked clusters — nothing is being suppressed"]
    lines = [f"frontend-errors: {len(muted)} acked cluster(s), suppressed until they recur"]
    for c in muted:
        lines.append(f"  {c['label']} ×{c['count']}  [{c['kind']}]  acked {c['acked_at'].date()}  "
                     f"last seen {c['last_seen'].date()}  {c['fingerprint']}")
    return lines


#: How many clusters the ECHO names before it becomes noise (SPEC-0171 §Parameters, SET run-1):
#: with labels, top-1/2/3 measured 67/110/142 chars — 110 sits closest to the sibling one-line
#: `debt` / `cross-coord` echoes. The remainder rides as a `+K more` tail, never as more items.
ECHO_TOP_N = 2


def echo_lines(clusters, *, cli_hint: str) -> list[str]:
    """The SPEC-0171 session-start ECHO: at most ONE short line, SUPPRESSED-WHEN-CLEAN.

    REPORT-ONLY — derived at read time from the confirmed clusters; stores nothing, gates nothing,
    starts no work. Returns `[]` for an empty confirmed set, which is the whole point: an owner whose
    frontend is quiet gets a silent session. The items are LABELS, never raw fingerprints (rendering
    fingerprints ran 209 chars at top-3 and truncated mid-token — run-1), and the line closes on the
    pointer that RE-FOLDS it after a `/compact`.

    ACK (T-10777): the caller passes the VISIBLE clusters — `apply_acks`' first half. An acked cluster
    is off this line for exactly as long as it produces nothing new, which is the one thing an ack buys;
    a post-ack occurrence returns it here with no further act.
    """
    if not clusters:
        return []
    head = ", ".join(f"{c['label']} ×{c['count']}" for c in clusters[:ECHO_TOP_N])
    more = len(clusters) - min(len(clusters), ECHO_TOP_N)
    tail = f" +{more} more" if more > 0 else ""
    return [f"frontend-errors: {len(clusters)} confirmed cluster(s) over the last {WINDOW_DAYS}d — "
            f"{head}{tail}. Report-only (SPEC-0171). Re-fold: `{cli_hint} frontend-errors`."]


def not_qualifying_lines(violations, *, cli_hint: str) -> list[str]:
    """The SPEC-0171 §Scenario "scoped promise" arm: a consumer that DECLARED the conveyor over a
    source the kernel cannot read must NOT be served the healthy consumer's silence — that silence
    would read identically for "you are healthy" and "I can see nothing at all". One line, naming the
    failing properties, so non-adoption is never SILENT."""
    if not violations:
        return []
    return [f"frontend-errors: NOT reading this consumer's source — {len(violations)} qualifying "
            f"property(ies) fail: {'; '.join(str(v) for v in violations)}. Fix the `source:` under "
            f"`extensions.adopts[] spec: {EXTENSION_SPEC_ID}` in yitc-ops.yaml, or drop the adoption. "
            f"Report-only. Re-fold: `{cli_hint} frontend-errors`."]


# ── The CADENCE — the periodic fold and its liveness (SPEC-0142, T-10803) ───────────────────────
# The conveyor's on-demand half only ever runs when somebody asks. The CADENCE is the standing half:
# a periodic sweep that folds every ADOPTED, QUALIFYING source so a confirmed cluster surfaces
# without anyone thinking to look. Its rule home is SPEC-0142 — a governed recurring obligation names
# a PROVIDER-INDEPENDENT trigger — and the values below are that spec's §2 binding 1 made concrete:
#
#   * the CARRIER is the EXISTING SPEC-0105 nightly runner (`bin/lib/nightly.py`). No new scheduler,
#     no new store, no new FSM, no new config surface — the sweep is one more read-only per-project
#     check on a runner that already enumerates the registry's v2 projects and already reads each
#     `yitc-ops.yaml`, which IS the adoption declaration the sweep must enumerate.
#   * the TRIGGER is an OS scheduler (system cron) invoking that deterministic script. Nothing on the
#     trigger→run path resolves through an AI provider's scheduler or runtime — the §2 rule is that
#     the WHOLE path, not merely the first hop, must run without the provider.
#   * NO AI-judgement layer exists on this path at all. The sweep folds and REPORTS; no model verdict
#     fires it, gates it, or decides what it confirms (§2 binding 2, held vacuously and deliberately).
#
# The RECORD is the carrier's OWN per-run event — no event type is added. It carries the marker below,
# and that marker is load-bearing for liveness: see `cadence_liveness`.
CADENCE_CARRIER = "nightly"                    # the SPEC-0105 runner — reused, not invented
CADENCE_EVENT = "nightly_run_completed"        # its EXISTING per-run record
CADENCE_MARKER = "frontend_error_cadence"      # the run-row key proving THIS sweep ran in that run
CADENCE_TRIGGER = ("system cron (an OS scheduler) invoking the deterministic `bin/yitc-v2 nightly` "
                   "script — provider-independent end to end, SPEC-0142 §2")

#: How long the cadence may go unfired before it is REPORTED dead. The carrier is daily, so this
#: allows exactly one missed run of slack before the alarm — tight enough that a stopped cron is
#: caught the next day, loose enough that a single skipped night is not an alarm.
CADENCE_WINDOW_HOURS = 48


def cadence_liveness(carrier_events_path, *, as_of: datetime) -> dict:
    """Has the cadence actually FIRED lately? A derived read of the carrier's own journal — the same
    SPEC-0095 fold shape `fold_acks` uses, and like it: no store, no state file, nothing persisted.

    Returns `{carrier, trigger, window_hours, last_run, age_hours, fired}`. P5-safe: a missing file,
    an unparseable line, a non-mapping event or an unreadable `ts` are SKIPPED, never raised.

    A RUN ONLY COUNTS IF IT CARRIED THE SWEEP. The fold admits a carrier event only when its data
    holds `CADENCE_MARKER`, and that condition is the whole point rather than a detail: the carrier
    runs many checks, and a nightly that fired WITHOUT the frontend-error leg (every run from before
    this shipped — and every run after, should the leg ever be removed) is not a fold of this
    conveyor. Counting a bare carrier run as liveness would mean a live cron kept the alarm quiet
    while the delivery half was dead, which is precisely the masking this liveness exists to prevent.

    THE READER MUST BE HANDED THE CARRIER'S JOURNAL, not the journal of whatever repo it happens to
    be reading from (SPEC-0110 r3, the independence axis): the carrier writes its run record to the
    ENGINE's journal, so a consumer checkout's own journal holds no carrier runs at all and reading it
    would grade every healthy consumer dead. Resolving that path is the CALLER's job — this function
    only reads the one it is given.
    """
    end = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    last: datetime | None = None
    p = Path(carrier_events_path) if carrier_events_path else None
    if p is not None and p.exists():
        from lib import journal as journal_mod   # T-11444: LOCAL import — this module is loaded
                                                 # STANDALONE by its own tests (by file path, no
                                                 # `bin/` on sys.path), so a module-level import
                                                 # would break that load (the worktree.py idiom).
        for line in journal_mod.segment_lines(p, errors="replace"):  # T-11444: segment-aware fold (SPEC-0190 r4)
            line = line.strip()
            if not line or CADENCE_EVENT not in line or CADENCE_MARKER not in line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if not isinstance(ev, dict) or ev.get("type") != CADENCE_EVENT:
                continue
            data = ev.get("data")
            if not isinstance(data, dict) or not data.get(CADENCE_MARKER):
                continue          # a carrier run WITHOUT this sweep is not this cadence firing
            ts = _parse_ts(ev.get("ts"))
            if ts is None:
                continue
            if last is None or ts > last:
                last = ts
    age_hours = None if last is None else round((end - last).total_seconds() / 3600.0, 1)
    return {
        "carrier": CADENCE_CARRIER,
        "trigger": CADENCE_TRIGGER,
        "window_hours": CADENCE_WINDOW_HOURS,
        "last_run": last,
        "age_hours": age_hours,
        "fired": age_hours is not None and age_hours <= CADENCE_WINDOW_HOURS,
    }


def cadence_not_fired_lines(liveness, *, cli_hint: str) -> list[str]:
    """The LOUD-FAILURE tripwire's rendering (SPEC-0165): `[]` while the cadence is alive, ONE line
    naming it dead otherwise.

    The silent breakage this makes loud: A DEAD CADENCE READING AS «no errors found». Every other
    surface in this conveyor is suppressed-when-clean by design — the echo prints nothing when the
    fold is empty, the view says `(silent)`. Those are the RIGHT answers when the sweep is running and
    finding nothing, and they are indistinguishable from the answers a reader gets when the sweep
    stopped running months ago. That is not hypothetical: the plan's own trial found the delivery half
    had never once run on a live session, and nothing on any surface said so.

    So the line states the three things that distinguish the two cases — the carrier, its OS trigger,
    and how long it has been silent — and it is NOT suppressed by a clean fold, because a clean fold
    from a dead cadence is exactly the report that must never be trusted."""
    live = liveness or {}
    if live.get("fired"):
        return []
    age = live.get("age_hours")
    since = (f"nothing for {age}h" if age is not None
             else "NO recorded run at all")
    return [f"frontend-errors: CADENCE NOT FIRED — the `{live.get('carrier')}` carrier has recorded "
            f"{since} (window {live.get('window_hours')}h), so a quiet report here is NOT evidence "
            f"that the frontend is quiet. Trigger: {live.get('trigger')}. Check the OS scheduler, "
            f"then re-fold: `{cli_hint} frontend-errors`."]


def _json_cluster(c: dict) -> dict:
    """One cluster as JSON — datetimes rendered ISO, everything else verbatim (incl. `row_ids`, the
    provenance chain, and `acked_at` where the cluster carries one)."""
    stamps = ("first_seen", "last_seen", "acked_at")
    return {
        **{k: v for k, v in c.items() if k not in stamps},
        **{k: c[k].isoformat() for k in stamps if isinstance(c.get(k), datetime)},
    }


def to_json(clusters, stats, *, all_time: bool = False, suppressed=None) -> str:
    """The machine view — carries `row_ids`, so a confirmed cluster resolves back to its source rows
    (AC3: the provenance chain, walked end to end)."""
    payload = {
        "window": {
            "all_time": all_time,
            "days": None if all_time else WINDOW_DAYS,
            "start": stats["window_start"],
            "end": stats["window_end"],
        },
        "confirm_threshold": CONFIRM_THRESHOLD,
        "stats": {k: v for k, v in stats.items() if not k.startswith("window_")},
        "clusters": [_json_cluster(c) for c in clusters],
        # T-10777: acked clusters are REPORTED here, never silently absent — the machine view is the
        # provenance surface, so "suppressed" must be a visible fact with its ack timestamp attached.
        "acked": [_json_cluster(c) for c in (suppressed or [])],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
