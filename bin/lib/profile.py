"""Project growth profile — THE ONE derivation site (SPEC-0198, T-12080).

Every seam that renders a profile-derived line CALLS this module; none re-derives. That is not a
style preference — it is SPEC-0198 rule 3 ("Exactly ONE kernel library resolves the profile") and
the property the AC2 tripwire in `tests/test_t12080_profile_resolver.py` enforces mechanically by
AST-scanning every other `bin/lib/*.py` for a literal collection naming three or more dimensions.
A second copy of the table below is a defect the test names, not a judgement call.

WHAT IT READS, and nothing else (SPEC-0198 rule 2):
  * the repo TREE — a bounded, pruned, sorted walk, so the answer is a pure function of the checkout;
  * `yitc-ops.yaml` — the SPEC-0093 ops carrier, for the `profile:` override section (rule 4) and
    for the `deploy:` liveness signal;
  * migrations / ORM schema files — for the PII and statefulness signals;
  * dependency manifests — for the framework / payment / auth / DB / API-client signals;
  * journal ROWS THE CALLER PASSES IN — never a path this module resolves. That is the
    `views.project_growth` precedent (T-11969): the fold takes its events as an input so it can ride
    the caller's existing request-scoped read scope instead of opening a second reader (CHARTER §P5,
    and SPEC-0190 rule 10 — the debt residue already owns ONE ReadScope; this module adds no cache).

WHAT IT NEVER READS (SPEC-0198 rule 2, "signals that are NEVER sufficient alone"): README claims,
comments/TODOs, UI copy, package popularity, generic HTTP-client usage, uncommitted dashboards.
They are excluded BY CONSTRUCTION — no detector below opens a README or a comment.

POSTURE: pure, read-only, best-effort. It writes nothing, emits no event, and never raises out of
`resolve_profile` — a report-only surface that breaks a session-start seam would be worse than a
conservative answer, so every read failure degrades to the dimension's conservative default.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Rule 1 — the ten dimensions. A dimension exists ONLY if at least one derived check changes with
# its value; the check-set table (rule 6, `required_check_set`) is where that is visible — every
# name below appears there, so none is kept "for later" (CHARTER §P1 F3).
# ---------------------------------------------------------------------------

DIMENSIONS = (
    "surface",
    "input_trust",
    "data_sensitivity",
    "money",
    "users_roles_tenancy",
    "external_integrations",
    "statefulness",
    "operational_criticality",
    "traffic_scale",
    "collaborator_rights",
)

#: Per dimension, the values it may take. An OVERRIDE outside this vocabulary is ignored
#: (fail-closed to the derived value — rule 4: never narrower than derived-conservative).
VOCABULARY = {
    "surface": ("public", "internal", "unknown"),
    "input_trust": ("untrusted", "trusted", "unknown"),
    "data_sensitivity": ("pii", "sensitive", "none", "unknown"),
    "money": ("present", "absent", "unknown"),
    "users_roles_tenancy": ("multi", "single", "none", "unknown"),
    "external_integrations": ("present", "absent", "unknown"),
    "statefulness": ("stateful", "stateless", "unknown"),
    "operational_criticality": ("live-critical", "live", "prototype", "unknown"),
    "traffic_scale": ("low", "medium", "high", "unknown"),
    "collaborator_rights": ("solo", "named-collaborators", "unknown"),
}

#: The CONSERVATIVE DEFAULT each dimension falls to when no signal resolves (rule 2). For eight of
#: the ten that is `unknown`, which rule 2 treats as WIDE — "surface -> public/unknown activates
#: public-boundary checks", so an unknown never buys a narrower check-set than a known-bad value.
#:
#: `operational_criticality` is the one deliberate exception and it is narrow BY CONTRACT, not by
#: oversight: rule 7 states that a `prototype` criticality receives only the constant floor, and the
#: Scenario states "a prototype with no users hears only the constant floor". A repo with no live
#: signal at all IS that prototype. Widening happens on a live-deploy signal, which is exactly the
#: crossing rule 6 names ("first live deploy class -> operational_criticality").
CONSERVATIVE_DEFAULTS = {
    "surface": "unknown",
    "input_trust": "unknown",
    "data_sensitivity": "unknown",
    "money": "unknown",
    "users_roles_tenancy": "unknown",
    "external_integrations": "unknown",
    "statefulness": "unknown",
    "operational_criticality": "prototype",
    "traffic_scale": "unknown",
    "collaborator_rights": "unknown",
}

#: Rule 2 — `traffic_scale` and `collaborator_rights` are NOT derived from the checkout ("a
#: commit-author count is not a permission proof"). They read `unknown` until DECLARED in the
#: `profile.override` section, and no detector below touches them.
DECLARED_ONLY = ("traffic_scale", "collaborator_rights")

#: Rule 7 — the HYSTERESIS/LATCH set, verbatim: "a dimension widens on one crossing and NARROWS
#: only by an explicit owner override (latch-until-owner-downgrade for surface / money /
#: data_sensitivity / users)". These four and NOTHING WIDER. Every other dimension — including
#: `external_integrations` — falls to its conservative default the moment its signal goes, which is
#: the ordinary rule-2 behaviour and is what keeps this latch a bounded exception rather than a
#: general "values never go down" rule.
LATCHED_DIMENSIONS = ("surface", "data_sensitivity", "money", "users_roles_tenancy")

#: The rule-7 WIDENING RELATION, widest first — the total order the latch compares against.
#:
#: WHY AN ORDER AND NOT A BOOLEAN "does it activate a lens" TEST. A boolean test permits
#: ACTIVE-TO-ACTIVE narrowing: `data_sensitivity: pii -> sensitive` keeps the `data-retention` lens
#: activated, so a boolean test sees no narrowing at all — while rule 7 forbids exactly that
#: downgrade. The order expresses the resolution the boolean cannot.
#:
#: WHERE `unknown` SITS, and why it is not arbitrary: directly BELOW the values that activate the
#: dimension's lens and ABOVE the definitively narrow ones. That is rule 2's "an unknown never buys
#: a narrower check-set than a known-bad value" applied per dimension — an unknown is wide, but it
#: is not a positive high-risk reading.
#:
#: This table REFINES `_ACTIVATION`, it does not compete with it: `_ACTIVATION` stays the single
#: source of truth for WHICH values activate a lens, and the MONOTONICITY INVARIANT below is pinned
#: by `test_rule7_the_latch_order_agrees_with_the_activation_table` — for each dimension here, every
#: activating value ranks strictly above every non-activating one. If the two ever disagree, that
#: test fails rather than the disagreement going unnoticed.
_LATCH_ORDER = {
    "surface":             ("public", "unknown", "internal"),
    "data_sensitivity":    ("pii", "sensitive", "unknown", "none"),
    "money":               ("present", "unknown", "absent"),
    "users_roles_tenancy": ("multi", "unknown", "single", "none"),
}


def _is_wider(dim: str, candidate, current) -> bool:
    """True when `candidate` is STRICTLY WIDER than `current` for `dim` (rule 7's relation).

    FAIL-CLOSED: a dimension with no order, or a value absent from its order (a snapshot recording
    something outside the vocabulary, a future value nobody ranked), yields False — NO latch. The
    derived answer then stands, which is the answer this module would have given anyway.
    """
    order = _LATCH_ORDER.get(dim)
    if not order or candidate not in order or current not in order:
        return False
    return order.index(candidate) < order.index(current)


# ---------------------------------------------------------------------------
# Signal tokens — the raw evidence vocabulary. Kept as module constants so the derivation is ONE
# readable table rather than predicates scattered through the resolver.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Signal tokens — the raw evidence vocabulary. Kept as module constants so the derivation is ONE
# readable table rather than predicates scattered through the resolver.
#
# EVERY token below is matched against a NORMALIZED, STRUCTURALLY PARSED coordinate — a declared
# dependency name, a schema table name, an env KEY name — never against a raw substring of a file.
# A substring scan cannot tell `stripe` from `notstripe`, a dependency from a description, or a
# declaration from a comment about one; three separate false-positive classes the exhaustive review
# of 2026-09-05 named on exactly that mechanism. `_dep_matches` is the boundary rule.
# ---------------------------------------------------------------------------

_WEB_FRAMEWORK_TOKENS = (
    "flask", "fastapi", "django", "starlette", "tornado", "bottle", "sanic", "falcon",
    "express", "koa", "nestjs", "hono", "fastify", "hapi", "next", "nuxt", "sveltekit",
    "gin-gonic", "gin", "fiber", "echo", "chi", "actix-web", "axum", "rocket", "rails",
    "sinatra", "hanami", "laravel", "symfony", "spring-boot", "ktor",
)
#: DUAL-USE libraries — an HTTP toolkit that is a server OR just a client. Rule 2: "generic
#: HTTP-client usage" is NEVER sufficient alone, so these count towards `surface` ONLY when the
#: tree ALSO carries route evidence. `aiohttp` sat in the framework list above and made a
#: client-only project read `public` off its dependency alone (exhaustive review, 2026-09-05).
_DUAL_USE_HTTP_TOKENS = ("aiohttp", "httpx", "requests", "urllib3", "axios", "node-fetch", "got")
_PAYMENT_TOKENS = (
    "stripe", "paddle", "yookassa", "yoomoney", "paypal", "braintree", "adyen", "checkout-sdk",
    "cloudpayments", "tinkoff", "robokassa", "lemonsqueezy", "razorpay", "square", "squareup",
    "mollie", "klarna", "chargebee", "recurly", "midtrans", "payme", "wompi",
)
_AUTH_TOKENS = (
    "authlib", "oauthlib", "python-jose", "pyjwt", "jsonwebtoken", "passport", "next-auth",
    "flask-login", "django-allauth", "passlib", "bcrypt", "argon2", "supertokens", "keycloak",
    "auth0", "auth0-python", "clerk", "devise", "warden", "omniauth", "spring-security",
    "identity", "casbin",
)
_DB_TOKENS = (
    "sqlalchemy", "alembic", "psycopg", "psycopg2", "asyncpg", "pymysql", "mysqlclient",
    "prisma", "sequelize", "typeorm", "mongoose", "pymongo", "redis", "django", "peewee",
    "tortoise-orm", "knex", "drizzle-orm", "gorm", "pg", "mysql2", "sqlite3", "better-sqlite3",
    "activerecord", "diesel", "sqlx", "ent", "mikro-orm", "objection",
)
_API_CLIENT_TOKENS = (
    "boto3", "aws-sdk", "google-cloud", "googleapis", "openai", "anthropic", "twilio", "sendgrid",
    "telebot", "python-telegram-bot", "aiogram", "slack-sdk", "sentry-sdk", "firebase-admin",
    "cloudflare", "digitalocean", "mailgun", "smsc", "algolia", "elasticsearch", "datadog",
    "newrelic", "posthog", "segment", "mixpanel", "resend", "postmark", "s3",
)

#: Route / handler markers in the TREE (path fragments, matched case-insensitively on the POSIX
#: relative path of a SOURCE file — never a document; see `_is_document`). A bare `package.json` is
#: deliberately NOT a marker — a Node backend declares one too.
_ROUTE_PATH_TOKENS = (
    "/routes/", "/route/", "/api/", "/controllers/", "/controller/", "/handlers/",
    "/endpoints/", "/app/api/", "urls.py", "wsgi.py", "asgi.py", "nginx.conf",
)
#: Request-INTAKE markers — the rule-6 "first request body/form/upload/webhook" crossing.
_INTAKE_PATH_TOKENS = ("/webhook", "webhook", "/upload", "upload", "/forms/", "/form/", "/intake/")

#: Migration / ORM schema LOCATIONS. A path token alone is not enough any more: the file must also
#: be a schema-CLASS file (`_SCHEMA_SUFFIXES`). `migrations/README.md` is a README, and rule 2 says
#: a README claim is never sufficient alone — reading it as schema let one prose file resolve
#: statefulness, PII and multi-user at once (exhaustive review, 2026-09-05).
_SCHEMA_PATH_TOKENS = (
    "/migrations/", "/migration/", "/migrate/", "/alembic/", "/schema/", "schema.sql",
    "schema.prisma", "schema.rb", "/models/", "models.py", "/entities/", "structure.sql",
)
#: The file classes that CAN carry a schema declaration. Prose extensions are absent by design.
_SCHEMA_SUFFIXES = (".sql", ".prisma", ".rb", ".py", ".ts", ".js", ".go", ".kt", ".java", ".php",
                    ".cs", ".ex", ".exs", ".rs")
#: Extensions that are DOCUMENTS, never evidence — rule 2's "README claims, UI copy, uncommitted
#: dashboards" exclusion, applied by construction at path-classification time.
_DOCUMENT_SUFFIXES = (".md", ".markdown", ".rst", ".txt", ".adoc", ".org", ".pdf", ".csv",
                      ".png", ".jpg", ".jpeg", ".svg", ".gif")
#: Directories whose contents are documentation / dashboards / examples, never a live surface.
_DOCUMENT_DIR_TOKENS = ("/docs/", "/doc/", "/dashboards/", "/dashboard/", "/examples/",
                        "/example/", "/samples/", "/fixtures/", "/notes/", "/design/")

#: PII-shaped column / field names, matched as WHOLE `_`-delimited parts of a declared column name
#: (so `rebirth_count` is not a `birth` field). Read from SCHEMA FILES ONLY.
_PII_FIELD_TOKENS = (
    "email", "e_mail", "phone", "mobile", "msisdn", "passport", "birth", "birthday", "birthdate",
    "dob", "ssn", "sin", "nin", "national_id", "inn", "snils", "address", "postcode",
    "postal_code", "zip", "full_name", "first_name", "last_name", "middle_name", "surname",
    "password", "password_hash", "card_number", "pan", "cvv", "iban", "tax_id", "license_number",
    "ip_address", "geolocation", "latitude", "longitude", "biometric", "health",
)
#: Auth / user TABLE names — matched against a parsed table name, never against free identifiers
#: (`user_agent` is a column, not a users table).
_AUTH_SCHEMA_TOKENS = ("users", "user", "accounts", "account", "sessions", "session", "roles",
                       "role", "permissions", "permission", "tenants", "tenant", "memberships",
                       "credentials", "auth_users")

#: Rule 2 — "external -> present on a provider/key signal". An env key is a credential declaration
#: when its name ENDS in one of these parts (or equals it). A SUFFIX rule, not a substring one:
#: `PRIMARY_KEY_FIELD` contains `key` and declares no credential (exhaustive review, 2026-09-05).
_CREDENTIAL_KEY_SUFFIXES = (
    "key", "api_key", "apikey", "secret", "token", "credential", "credentials", "access_key",
    "private_key", "client_secret", "auth_key", "webhook_secret", "dsn", "password", "passwd",
    "sid", "certificate", "cert",
)

_MANIFEST_NAMES = (
    "requirements.txt", "pyproject.toml", "Pipfile", "setup.py", "setup.cfg",
    "package.json", "go.mod", "Gemfile", "Cargo.toml", "composer.json", "build.gradle",
    "pom.xml", "mix.exs",
)
_ENV_EXAMPLE_NAMES = (".env.example", ".env.sample", ".env.template", "env.example",
                      ".env.dist", ".env.defaults")

#: Load-test / SLO artifacts — the rule-6 `traffic_scale` CROSSING. It activates the performance
#: lens; it does NOT set the dimension, which rule 2 keeps declared-only ("the kernel cannot read
#: real traffic from a checkout").
_LOAD_ARTIFACT_TOKENS = ("k6", "locustfile", "/load/", "loadtest", "load-test", "slo.yaml",
                         "slo.yml", "/benchmarks/", "jmeter", "gatling", "artillery")

#: Storage artefacts in the tree — the rule-6 "first DB/migration/storage" crossing.
_STORAGE_PATH_TOKENS = ("/storage/", "/data/", ".sqlite", ".sqlite3", ".db", "/var/lib/",
                        "docker-compose", "/volumes/")

#: Journal event types that PROVE a live deploy happened. Read off rows the caller hands in.
_LIVE_EVENT_TYPES = ("deploy_completed", "live_probe_recorded", "host_apply_confirmed")
#: Row keys that, WHEN PRESENT, must identify THIS repo for the row to count. A row that names
#: another project is not this project's liveness evidence (exhaustive review, 2026-09-05).
_EVENT_REPO_KEYS = ("repo", "repo_root", "project", "repo_path", "root")

# Bounded tree walk — a report-only surface must be cheap at every seam it rides.
_WALK_DIR_SKIP = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache",
    "dist", "build", ".next", ".yitc", "vendor", "target", ".tox", "site-packages", ".idea",
}
_WALK_ENTRY_CAP = 20000
_READ_BYTE_CAP = 262144
#: The content scanners (routes / intake) ride three seams that already run, so their bound is a
#: COST bound, not just a safety one: at 400 files x 256 KiB this module took ~3 s per resolution on
#: this repo, which a session-start seam cannot pay (CHARTER §P5). A route or a body read is
#: declared at the TOP of a handler and handlers live near the top of a tree, so the scan is bounded
#: three ways — shallow paths only, a file count, and a small per-file prefix — and reports
#: INCOMPLETE when a bound cuts it short rather than asserting absence.
_SOURCE_SCAN_CAP = 40
_SOURCE_READ_CAP = 8192
_SOURCE_MAX_DEPTH = 3
_SOURCE_SUFFIXES = (".py", ".js", ".ts", ".jsx", ".tsx", ".rb", ".go", ".php", ".rs", ".java",
                    ".kt", ".ex", ".exs", ".cs")


# ---------------------------------------------------------------------------
# Reads — each one bounded, sorted, fenced and failure-tolerant.
#
# EVERY reader returns its TRUNCATION / FAILURE state alongside its content. A cap that silently
# returns less than the file said is a cap that manufactures ABSENCE, and absence is a profile
# answer here: a 256 KiB `requirements.txt` whose payment SDK sat past the cap read `money=unknown`
# with nothing to say it had stopped looking (exhaustive review, 2026-09-05). `Evidence` carries
# the flag; `_derive` turns it into an honest `unknown`, never a narrow default.
# ---------------------------------------------------------------------------

def _is_document(rel: str) -> bool:
    """True for a path that is documentation / a dashboard / an example — never evidence (rule 2)."""
    low = "/" + rel.lower()
    if low.endswith(_DOCUMENT_SUFFIXES):
        return True
    return any(tok in low for tok in _DOCUMENT_DIR_TOKENS)


def _git_tracked(root: Path):
    """The CHECKED-IN inventory (`git ls-files`), or None when this is not a usable git checkout.

    Rule 2 excludes "uncommitted dashboards": a file nobody committed is not evidence about the
    project. Where git can answer, its answer is the inventory; where it cannot (a plain directory,
    no git binary), the walk below is the fallback and the distinction is recorded, never guessed.
    """
    if not (root / ".git").exists():
        return None
    try:
        import subprocess
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                              capture_output=True, timeout=20)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    out = [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]
    return sorted(out)


def _walk_paths(root: Path):
    """`(paths, truncated)` — POSIX-relative paths under `root`, pruned and SORTED.

    Sorted is what makes the whole resolution a pure function of the checkout. `truncated` is True
    when `_WALK_ENTRY_CAP` cut the walk short, so a caller can say "I stopped looking" instead of
    "there is nothing there".
    """
    out: list = []
    truncated = False
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in _WALK_DIR_SKIP
                                 and not d.startswith(".git"))
            rel_dir = os.path.relpath(dirpath, root)
            prefix = "" if rel_dir == "." else rel_dir.replace(os.sep, "/") + "/"
            for name in sorted(filenames):
                out.append(prefix + name)
                if len(out) >= _WALK_ENTRY_CAP:
                    return sorted(out), True
    except OSError:
        pass
    return sorted(out), truncated


def _inventory(root: Path):
    """`(paths, truncated, tracked)` — the checkout inventory the whole derivation reads."""
    tracked = _git_tracked(root)
    if tracked is not None:
        if len(tracked) >= _WALK_ENTRY_CAP:
            return tracked[:_WALK_ENTRY_CAP], True, True
        return tracked, False, True
    paths, truncated = _walk_paths(root)
    return paths, truncated, False


def _safe_path(root: Path, rel: str):
    """The absolute path of `rel` — or None when it escapes the checkout through a symlink.

    Rule 3 makes the resolution a function of the CHECKOUT. A committed `requirements.txt ->
    /tmp/deps.txt` would let a file nobody can see change both hashes while the checkout is
    unchanged, which is that property broken (exhaustive review, 2026-09-05).
    """
    try:
        base = os.path.realpath(str(root))
        target = os.path.realpath(str(root / rel))
        if target == base or target.startswith(base + os.sep):
            return Path(target)
    except OSError:
        return None
    return None


#: BOM prefixes -> the encoding they declare. A UTF-16 manifest decoded as UTF-8 becomes
#: NUL-interleaved and every token miss is silent (exhaustive review, 2026-09-05).
_BOMS = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)


def _decode(raw: bytes) -> str:
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            try:
                return raw.decode(enc, "replace").lstrip("\ufeff")
            except (LookupError, UnicodeError):
                break
    return raw.decode("utf-8", "replace").lstrip("\ufeff")


def _read_file(root: Path, rel: str, cap: int = _READ_BYTE_CAP):
    """`(text, truncated, ok)` — a bounded, BOM-aware, symlink-fenced read of one checkout file."""
    path = _safe_path(root, rel)
    if path is None:
        return "", False, False
    try:
        with open(path, "rb") as fh:
            raw = fh.read(cap + 1)
    except OSError:
        return "", False, False
    truncated = len(raw) > cap
    return _decode(raw[:cap]), truncated, True


def _read_text(path: Path) -> str:
    """Bounded, encoding-tolerant read of an absolute path. Any failure is the empty string.

    Kept for callers that already hold a resolved path; the checkout readers use `_read_file`,
    which also reports truncation and fences symlinks.
    """
    try:
        with open(path, "rb") as fh:
            return _decode(fh.read(_READ_BYTE_CAP))
    except OSError:
        return ""


#: Returned in place of the ops mapping when the carrier EXISTS but could not be read. It is a
#: distinct answer from `{}` on purpose — see `_load_ops`.
_OPS_UNREADABLE = "unreadable"


def _load_ops(root: Path, ops=None):
    """The SPEC-0093 ops carrier as a mapping — or `_OPS_UNREADABLE`.

    `ops` (already-parsed) wins, so a caller holding the carrier does not re-read it. An ABSENT or
    empty carrier is `{}`.

    AN UNPARSEABLE CARRIER IS NOT `{}`, AND THE DISTINCTION IS LOAD-BEARING. `{}` says "the carrier
    was read and declares nothing" — from which `_derive` may conclude that no deploy is declared.
    An unparseable carrier supports no such conclusion: it says the file exists and we could not
    read it, so every carrier-borne signal is UNKNOWN, not ABSENT. Collapsing the two let a single
    stray character in `yitc-ops.yaml` silently drop `operational_criticality` from `live-critical`
    to `prototype` and, with it, every lens rule 7 gates behind a non-prototype reading — malformation
    NARROWING the profile, which is exactly what AC3 forbids.

    THE SENTINEL IS FOR A FAILED READ, NEVER FOR AN EMPTY ONE. An ABSENT carrier and an EMPTY but
    perfectly readable one are both `{}`: we read them and they declare nothing, so concluding "no
    deploy is declared" is warranted. Only an OSError or a parse failure withholds that conclusion.

    THE CARRIER IS LOADED EXACTLY ONCE PER RESOLUTION (`resolve_profile` threads the result through
    both `_derive` and `_overrides`). Loading it twice let a carrier rewritten between the two reads
    produce a snapshot corresponding to NEITHER file (exhaustive review, 2026-09-05).

    A CARRIER LARGER THAN THE READ CAP IS UNREADABLE, NOT PARTIAL. The read is bounded like every
    other one here, but a bounded read of a STRUCTURED carrier is not a smaller carrier: truncating
    `yitc-ops.yaml` mid-file can still yield a perfectly parseable mapping that is MISSING every
    declaration after the cap — a `deploy:` block near the end silently vanishes and
    `operational_criticality` narrows from `live-critical` to `prototype`. That is the capped read
    MANUFACTURING ABSENCE, the same class the unparseable case above exists to prevent, so it takes
    the same answer: read one byte past the cap to DETECT the overrun, and report `_OPS_UNREADABLE`
    rather than a partial mapping (consult, 2026-09-05).
    """
    if isinstance(ops, dict):
        return ops
    if ops is _OPS_UNREADABLE:
        return ops
    path = root / "yitc-ops.yaml"
    try:
        with open(path, "rb") as fh:
            raw = fh.read(_READ_BYTE_CAP + 1)          # +1 byte: DETECTS the overrun, never uses it
    except FileNotFoundError:
        return {}                                      # absent: read successfully as "not there"
    except OSError:
        return _OPS_UNREADABLE                         # a genuine read failure
    if len(raw) > _READ_BYTE_CAP:
        return _OPS_UNREADABLE                         # over the cap: a PARTIAL carrier answers nothing
    text = _decode(raw)
    if not text.strip():
        return {}                                      # present and EMPTY: it declares nothing
    try:
        import yaml                                    # deferred: only when a carrier has content
        data = yaml.safe_load(text)
    except Exception:
        return _OPS_UNREADABLE
    return data if isinstance(data, dict) else _OPS_UNREADABLE


# ---------------------------------------------------------------------------
# Structural parsing — declarations, not substrings.
# ---------------------------------------------------------------------------

_LINE_COMMENT_MARKERS = {
    "requirements": ("#",), "pyproject.toml": ("#",), "Pipfile": ("#",), "setup.cfg": ("#",),
    "setup.py": ("#",), "Cargo.toml": ("#",), "Gemfile": ("#",), "mix.exs": ("#",),
    "go.mod": ("//",), "build.gradle": ("//",), "package.json": (), "composer.json": (),
    "pom.xml": (),
}
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_XML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_SQL_LINE_COMMENT_MARKERS = ("--", "#")


def _strip_line_comments(text: str, markers, block=False) -> str:
    """`text` with its COMMENT REGIONS removed — the region only, never the whole line.

    Dropping a whole line that merely CONTAINED the word `todo` deleted real declarations
    (`{"stripe":"file:../todo/stripe"}`), which is the opposite error from the one comment
    stripping exists to prevent. Comments are removed because they are comments; a TODO written
    inside one goes with it, and a TODO written as prose in a manifest is not a valid declaration
    and is dropped by the STRUCTURAL parse below, not by a substring rule.
    """
    if block:
        text = _BLOCK_COMMENT_RE.sub(" ", text)
    if not markers:
        return text
    kept = []
    for line in text.splitlines():
        for marker in markers:
            idx = line.find(marker)
            if idx != -1:
                line = line[:idx]
        kept.append(line)
    return "\n".join(kept)


def _normalize_dep(name: str) -> str:
    """A dependency coordinate normalized for comparison: lowercased, `@scope/` kept, extras cut."""
    name = (name or "").strip().strip("'\"").lower()
    name = name.split("[", 1)[0]
    if name.startswith("@"):
        name = name[1:]
    return name.strip().strip("/")


def _dep_matches(name: str, token: str) -> bool:
    """Boundary-aware match of a normalized dependency coordinate against a signal token.

    Equality, or the token as a WHOLE segment of the coordinate under `-`, `_`, `/`, `.`. So
    `stripe-go`, `github.com/stripe/stripe-go` and `stripe` all match `stripe`, while `notstripe`
    and `expressions` match nothing — the substring class the review named (finding 17).
    """
    if not name or not token:
        return False
    if name == token:
        return True
    parts = re.split(r"[/._-]", name)
    tok_parts = re.split(r"[/._-]", token)
    if len(tok_parts) == 1:
        return token in parts
    n = len(tok_parts)
    return any(parts[i:i + n] == tok_parts for i in range(0, max(0, len(parts) - n + 1)))


def _deps_match(deps, tokens) -> bool:
    return any(_dep_matches(dep, tok) for dep in deps for tok in tokens)


_REQ_LINE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*"
                          r"([<>=!~;@].*)?$")


def _parse_requirements(text: str) -> set:
    """Declared distributions of a `requirements*.txt` / `requirements*.in` file.

    A line must BE a requirement specifier. `TODO add stripe` is prose, not a specifier, and is
    dropped here rather than by a substring rule (finding 37).
    """
    out = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("-", "#")):
            continue
        m = _REQ_LINE_RE.match(line)
        if m:
            out.add(_normalize_dep(m.group(1)))
    return out


def _parse_json_manifest(text: str) -> set:
    """Declared dependency NAMES of `package.json` / `composer.json` — the coordinates only.

    Whole-file scanning made a `description` field ("our next release uses stripe-coloured
    buttons") a payment signal (finding 14). Only the dependency maps are read.
    """
    out = set()
    try:
        data = json.loads(text)
    except Exception:
        return out
    if not isinstance(data, dict):
        return out
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies",
                "require", "require-dev"):
        block = data.get(key)
        if isinstance(block, dict):
            out |= {_normalize_dep(k) for k in block if isinstance(k, str)}
        elif isinstance(block, list):
            out |= {_normalize_dep(k) for k in block if isinstance(k, str)}
    return out


_TOML_KEY_RE = re.compile(r"^\s*([A-Za-z0-9@._/-]+)\s*=")
#: The whole quoted string, not a name-shaped prefix of it: a requirement is written `"stripe>=8"`
#: and a Gradle coordinate `"com.stripe:stripe-java:20.0"`, and the COORDINATE HEAD is split out
#: below. Anchoring the pattern on a name shape silently dropped both.
_TOML_STR_RE = re.compile(r"[\"']([^\"']+)[\"']")
_SECTION_RE = re.compile(r"^\s*\[+([^\]]+)\]+\s*$")

#: A TOML/INI SECTION that declares dependencies. Everything else in the file — `[project]`'s own
#: metadata, `[tool.<anything>]` configuration, `keywords`, a description — is NOT a dependency
#: declaration, and reading it as one made package METADATA a payment signal, which rule 2 excludes
#: by name ("package popularity"). Section-agnostic extraction was the defect the convergence
#: consult named on 2026-09-05 (`keywords = ["stripe"]`, `[tool.example] stripe = "disabled"`).
_DEP_SECTION_TOKENS = ("dependencies", "dev-dependencies", "build-dependencies", "packages",
                       "dev-packages", "requires", "dependency")
#: A dependency-declaring KEY, wherever it appears — `[project] dependencies = [...]` (PEP 621),
#: `[options] install_requires = ...` (setup.cfg), a Gradle `dependencies { … }` block.
_DEP_KEYS = ("dependencies", "install_requires", "setup_requires", "tests_require",
             "requires", "requires-dist", "libraryDependencies".lower())


def _is_dep_section(name: str) -> bool:
    parts = [p.strip().lower() for p in (name or "").split(".")]
    return any(p in _DEP_SECTION_TOKENS for p in parts)


def _dep_regions(text: str):
    """The lines of a TOML/INI manifest that sit inside a DEPENDENCY declaration.

    A line qualifies when it is inside a dependency SECTION, or inside the value of a dependency
    KEY (a bracketed array, or an indented continuation as `setup.cfg` writes it), or inside a
    Gradle `dependencies { … }` block. Nothing else is read at all.
    """
    out = []
    section = ""
    key_depth = 0
    in_key = False
    brace_block = 0
    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            section = m.group(1)
            in_key = False
            continue
        stripped = line.strip()
        if brace_block:
            brace_block += line.count("{") - line.count("}")
            if brace_block > 0:
                out.append(line)
            continue
        if re.match(r"^\s*dependencies\s*\{", line):
            brace_block = 1
            continue
        if in_key:
            if key_depth > 0:
                key_depth += line.count("[") - line.count("]")
                out.append(line)
                if key_depth <= 0:
                    in_key = False
                continue
            if stripped and (line[:1].isspace()):
                out.append(line)
                continue
            in_key = False
        km = _TOML_KEY_RE.match(line)
        if km and km.group(1).strip().lower().replace("_", "-").rstrip("-") in (
                k.replace("_", "-").rstrip("-") for k in _DEP_KEYS):
            value = line.split("=", 1)[1]
            out.append(value)
            depth = value.count("[") - value.count("]")
            in_key = True
            key_depth = depth if depth > 0 else 0
            continue
        if _is_dep_section(section):
            out.append(line)
    return out


def _parse_toml_like(text: str) -> set:
    """Declared names of a TOML/INI-shaped manifest (`pyproject.toml`, `Pipfile`, `Cargo.toml`,
    `setup.cfg`, `build.gradle`) — read ONLY from dependency sections and dependency keys."""
    out = set()
    for line in _dep_regions(text):
        stripped = line.strip()
        if not stripped:
            continue
        m = _TOML_KEY_RE.match(line)
        if m:
            out.add(_normalize_dep(m.group(1)))
        for s in _TOML_STR_RE.findall(line):
            head = re.split(r"[<>=!~;\s,:\[]", s, 1)[0]
            if re.match(r"^[A-Za-z0-9@][A-Za-z0-9@._/-]*$", head or ""):
                out.add(_normalize_dep(head))
        if "=" not in stripped and not stripped.startswith(("'", '"')):
            head = re.split(r"[<>=!~;\s,]", stripped, 1)[0]
            if re.match(r"^[A-Za-z0-9@][A-Za-z0-9@._/-]*$", head or ""):
                out.add(_normalize_dep(head))
    out.discard("")
    return out


_MIX_DEP_RE = re.compile(r"\{\s*:([a-z0-9_]+)\s*,")


def _parse_mix_exs(text: str) -> set:
    """Elixir `mix.exs` — the `{:name, "~> x"}` tuples of the deps list, nothing else."""
    return {_normalize_dep(m.group(1)) for m in _MIX_DEP_RE.finditer(text)}


_GO_REQUIRE_RE = re.compile(r"^\s*(?:require\s+)?([a-z0-9][a-z0-9._/-]*\.[a-z]{2,}/[^\s]+)\s+v",
                            re.I)


def _parse_go_mod(text: str) -> set:
    out = set()
    for line in text.splitlines():
        m = _GO_REQUIRE_RE.match(line)
        if m:
            out.add(_normalize_dep(m.group(1)))
    return out


_GEMFILE_RE = re.compile(r"^\s*gem\s+[\"']([^\"']+)[\"']")
_SETUP_PY_STR_RE = re.compile(r"[\"']([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:[<>=!~].*?)?[\"']")


def _parse_gemfile(text: str) -> set:
    return {_normalize_dep(m.group(1)) for m in
            (_GEMFILE_RE.match(l) for l in text.splitlines()) if m}


_SETUP_ARG_RE = re.compile(
    r"(?:install_requires|setup_requires|tests_require|extras_require|requires)\s*=\s*[\[\{]",
    re.I)


def _parse_setup_py(text: str) -> set:
    """Requirement strings of a `setup.py` — read ONLY from the requirement-bearing ARGUMENTS.

    Scanning every quoted string in the file made `description="stripe"` a payment declaration
    (convergence consult, 2026-09-05) — the same package-metadata class rule 2 excludes.
    """
    out = set()
    for m in _SETUP_ARG_RE.finditer(text):
        depth = 0
        i = m.end() - 1
        start = i
        while i < len(text):
            if text[i] in "[{":
                depth += 1
            elif text[i] in "]}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        out |= {_normalize_dep(s) for s in _SETUP_PY_STR_RE.findall(text[start:i])}
    out.discard("")
    return out


def _parse_xml_manifest(text: str) -> set:
    return {_normalize_dep(s) for s in re.findall(r"<artifactId>([^<]+)</artifactId>", text)}


def _manifest_class(base: str):
    """`(class, comment markers, block?)` for a manifest filename — or None when it is not one."""
    if base in ("package.json", "composer.json"):
        return "json", (), False
    if base == "go.mod":
        return "go", ("//",), True
    if base == "Gemfile":
        return "gem", ("#",), False
    if base == "setup.py":
        return "setup.py", ("#",), False
    if base == "mix.exs":
        return "mix", ("#",), False
    if base in ("pyproject.toml", "Pipfile", "Cargo.toml", "setup.cfg"):
        return "toml", ("#",), False
    if base in ("build.gradle", "build.gradle.kts"):
        return "toml", ("//",), True
    if base == "pom.xml":
        return "xml", (), False
    if base.startswith("requirements") and base.endswith((".txt", ".in")):
        return "requirements", ("#",), False
    return None


def _manifest_deps(root: Path, paths: list):
    """`(deps, truncated)` — every DECLARED dependency coordinate in the checkout, normalized.

    One set because every manifest signal is a membership question ("is a payment SDK declared?").
    Each file is parsed by its own format: JSON manifests structurally, requirement files line by
    line, `go.mod` by its require lines. No file is substring-scanned, and each format's own
    comment syntax is removed first (`//` for `go.mod`, `#` for requirement files, none for JSON,
    which has none — applying every marker everywhere would delete a real dependency URL).
    """
    deps: set = set()
    truncated = False
    for rel in paths:
        base = rel.rsplit("/", 1)[-1]
        kind = _manifest_class(base)
        if kind is None:
            continue
        cls, markers, block = kind
        text, trunc, ok = _read_file(root, rel)
        if not ok:
            continue
        truncated = truncated or trunc
        text = _strip_line_comments(text, markers, block=block)
        if cls == "xml":
            text = _XML_COMMENT_RE.sub(" ", text)
        if cls == "json":
            deps |= _parse_json_manifest(text)
        elif cls == "requirements":
            deps |= _parse_requirements(text)
        elif cls == "toml":
            deps |= _parse_toml_like(text)
        elif cls == "go":
            deps |= _parse_go_mod(text)
        elif cls == "gem":
            deps |= _parse_gemfile(text)
        elif cls == "setup.py":
            deps |= _parse_setup_py(text)
        elif cls == "mix":
            deps |= _parse_mix_exs(text)
        elif cls == "xml":
            deps |= _parse_xml_manifest(text)
    deps.discard("")
    return deps, truncated


_CREATE_TABLE_RE = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?[`\"\[]?([a-z0-9_.]+)", re.I)
_RAILS_TABLE_RE = re.compile(r"create_table\s+[:\"']([a-z0-9_]+)", re.I)
_PRISMA_MODEL_RE = re.compile(r"^\s*model\s+([A-Za-z0-9_]+)\s*\{", re.M)
_ORM_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z0-9_]+)\s*\(", re.M)
_TABLENAME_RE = re.compile(r"__tablename__\s*=\s*[\"']([a-z0-9_]+)[\"']", re.I)
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _split_parts(ident: str) -> list:
    ident = ident.lower()
    parts = [p for p in re.split(r"[._-]", ident) if p]
    return parts


def _ident_matches(ident: str, token: str) -> bool:
    """Whole-part match of a declared identifier against a field token (`user_agent` is not `user`,
    `rebirth_count` is not `birth`). A multi-part token matches a consecutive part run."""
    parts = _split_parts(ident)
    tok = _split_parts(token)
    if not tok:
        return False
    if len(tok) == 1:
        return tok[0] in parts
    n = len(tok)
    return any(parts[i:i + n] == tok for i in range(0, max(0, len(parts) - n + 1)))


def _schema_evidence(root: Path, paths: list):
    """`(tables, fields, has_schema_file, truncated)` read from SCHEMA-CLASS FILES ONLY.

    `tables` are parsed table/model names; `fields` are the identifiers declared inside them.
    Comments (`--`, `#`, `//`, `/* */`) are removed first, and no prose file is opened at all —
    the two mechanisms that let a comment and a README each assert a schema (findings 8 and 18).
    """
    tables: set = set()
    fields: set = set()
    has_file = False
    truncated = False
    for rel in paths:
        low = "/" + rel.lower()
        if _is_document(rel) or not low.endswith(_SCHEMA_SUFFIXES):
            continue
        if not any(tok in low for tok in _SCHEMA_PATH_TOKENS):
            continue
        text, trunc, ok = _read_file(root, rel)
        if not ok:
            continue
        has_file = True
        truncated = truncated or trunc
        markers = _SQL_LINE_COMMENT_MARKERS if low.endswith(".sql") else ("#", "--", "//")
        text = _strip_line_comments(text, markers, block=True)
        tables |= {m.group(1).rsplit(".", 1)[-1].lower() for m in _CREATE_TABLE_RE.finditer(text)}
        tables |= {m.group(1).lower() for m in _RAILS_TABLE_RE.finditer(text)}
        tables |= {m.group(1).lower() for m in _PRISMA_MODEL_RE.finditer(text)}
        tables |= {m.group(1).lower() for m in _ORM_CLASS_RE.finditer(text)}
        tables |= {m.group(1).lower() for m in _TABLENAME_RE.finditer(text)}
        fields |= {ident.lower() for ident in _IDENT_RE.findall(text)}
    return tables, fields, has_file, truncated


def _env_entries(root: Path, paths: list):
    """`(entries, truncated)` — the `(KEY, value)` pairs an `.env.example`-class file DECLARES.

    A BARE key line (`STRIPE_SECRET_KEY` with no `=`) is a declaration too; requiring `=` dropped
    it and lost the provider signal (finding 20). Values are carried but no dimension is derived
    from a value alone — `NOTE=stripe` declares no payment provider (finding 15).
    """
    entries = []
    truncated = False
    for rel in paths:
        if rel.rsplit("/", 1)[-1] not in _ENV_EXAMPLE_NAMES:
            continue
        text, trunc, ok = _read_file(root, rel)
        if not ok:
            continue
        truncated = truncated or trunc
        for line in _strip_line_comments(text, ("#",)).splitlines():
            line = line.strip()
            if line.lower().startswith("export "):
                line = line[7:].strip()
            if not line:
                continue
            if "=" in line:
                key, val = line.split("=", 1)
            else:
                key, val = line, ""
            key = key.strip().strip('"\'')
            if key and re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", key):
                entries.append((key.lower(), val.strip().strip('"\'').lower()))
    return entries, truncated


def _is_credential_key(key: str) -> bool:
    """True when an env key NAME declares a credential — by SUFFIX, so `PRIMARY_KEY_FIELD` is not
    one and `STRIPE_SECRET_KEY` is (finding 15)."""
    parts = _split_parts(key)
    if not parts:
        return False
    for suffix in _CREDENTIAL_KEY_SUFFIXES:
        tok = _split_parts(suffix)
        if parts[-len(tok):] == tok:
            return True
    return False


def _names_provider(key: str) -> bool:
    return any(_ident_matches(key, tok) for tok in _API_CLIENT_TOKENS + _PAYMENT_TOKENS)


def _has_provider_key(entries) -> bool:
    """Rule 2's "provider/key signal" on the committed env template: a key that NAMES A PROVIDER or
    whose name declares a credential. A file of plain runtime settings reads False."""
    return any(_names_provider(k) or _is_credential_key(k) for k, _v in entries)


def _env_payment_signal(entries) -> bool:
    """A payment provider named in an env KEY (never in a value — finding 15)."""
    return any(any(_ident_matches(k, tok) for tok in _PAYMENT_TOKENS) for k, _v in entries)


#: Ops-carrier sections that may carry an operational SIGNAL. Everything else in `yitc-ops.yaml`
#: — and `profile:` itself, and every prose key below — is NOT signal-bearing: a whole-document
#: substring scan made `notes: "we do not use stripe"` a payment signal and let a malformed
#: `profile: stripe` seed money+external (findings 5 and 16).
_OPS_SIGNAL_SECTIONS = ("deploy", "billing", "payments", "payment", "integrations", "services",
                        "providers", "secrets", "env", "auth", "database", "db", "storage")
_OPS_PROSE_KEYS = ("notes", "note", "description", "reason", "comment", "comments", "rationale",
                   "waiver", "title", "summary", "why", "readme", "doc", "docs")
_PUBLIC_DEPLOY_KEYS = ("url", "urls", "domain", "domains", "host", "hostname", "public",
                       "public_url", "endpoint", "surface", "ingress")


def _ops_pairs(section) -> list:
    """Every `(key, scalar)` under a signal-bearing ops section, prose keys pruned."""
    out = []

    def walk(node, key):
        if key and key.lower() in _OPS_PROSE_KEYS:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str):
                    walk(v, k)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v, key)
        elif node is not None and not isinstance(node, bool):
            out.append((str(key or "").lower(), str(node).lower()))
        elif isinstance(node, bool):
            out.append((str(key or "").lower(), "true" if node else "false"))

    walk(section, "")
    return out


def _ops_signals(ops_map) -> dict:
    """The TYPED signals of the ops carrier — never a whole-document substring scan.

    Returns `{deploy_declared, deploy_public, payment, provider_key, auth}`. Only the sections
    `_OPS_SIGNAL_SECTIONS` names are read, `profile:` is excluded entirely, and prose keys are
    pruned before any token is matched.
    """
    sig = {"deploy_declared": False, "deploy_public": False, "payment": False,
           "provider_key": False, "auth": False}
    if not isinstance(ops_map, dict):
        return sig
    deploy = ops_map.get("deploy")
    if isinstance(deploy, dict):
        sig["deploy_declared"] = bool(deploy.get("command"))
        for key, val in _ops_pairs(deploy):
            if key in _PUBLIC_DEPLOY_KEYS and val not in ("", "false", "none", "internal"):
                sig["deploy_public"] = True
            if val.startswith("http://") or val.startswith("https://"):
                sig["deploy_public"] = True
    auth = ops_map.get("auth")
    if isinstance(auth, dict) and any(v for _k, v in _ops_pairs(auth)):
        sig["auth"] = True
    for name in _OPS_SIGNAL_SECTIONS:
        section = ops_map.get(name)
        if section is None:
            continue
        for key, val in _ops_pairs(section):
            if any(_ident_matches(key, tok) or _ident_matches(val, tok)
                   for tok in _PAYMENT_TOKENS):
                sig["payment"] = True
            if (_names_provider(key) or _is_credential_key(key)
                    or any(_ident_matches(val, tok) for tok in _API_CLIENT_TOKENS)):
                sig["provider_key"] = True
    return sig


#: Route / mutable-endpoint / intake DECLARATIONS in source content. Rule 2 names the repo tree as
#: a signal source and rule 6 names "mutable endpoints"; a path-name-only reader saw neither a real
#: route in `server.py` nor a request body read (findings 2 and 11).
_ROUTE_DECL_RE = re.compile(
    r"@(?:app|router|blueprint|bp)\.(?:route|get|post|put|patch|delete)\b"
    r"|@(?:Get|Post|Put|Patch|Delete|Controller)\s*\("
    r"|\b(?:app|router|server)\.(?:get|post|put|patch|delete|use)\s*\("
    r"|\bhttp\.HandleFunc\s*\(|\bmux\.Handle(?:Func)?\s*\("
    r"|\burlpatterns\b|\bpath\s*\(\s*[\"']|\bget\s+[\"']/|\bpost\s+[\"']/"
    r"|\brouter\.(?:HandleFunc|Route)\b|\bresources\s+:", re.I)
_MUTABLE_DECL_RE = re.compile(
    r"@(?:app|router|blueprint|bp)\.(?:post|put|patch|delete)\b"
    r"|@(?:Post|Put|Patch|Delete)\s*\("
    r"|\b(?:app|router|server)\.(?:post|put|patch|delete)\s*\("
    r"|methods\s*=\s*\[[^\]]*[\"'](?:POST|PUT|PATCH|DELETE)", re.I)
_INTAKE_DECL_RE = re.compile(
    r"request\.(?:get_json|json|form|files|data|body)\b|req\.(?:body|files|file)\b"
    r"|multipart/form-data|\bUploadFile\b|\bFormData\b|body_parser|bodyParser", re.I)


def _source_signals(root: Path, paths: list, need=None):
    """`(signals, truncated)` — route / mutable-endpoint / intake DECLARATIONS found in source.

    Bounded three ways (see `_SOURCE_SCAN_CAP`): shallow paths, a file count, a per-file prefix.
    Documents are never opened. Hitting a bound sets `truncated`, so the resolver says "I stopped
    looking" rather than "there is nothing there".

    `need` is the set of questions still OPEN — the cheap path-token legs answer some of them, and
    a question already answered YES is not worth a single file read. An empty `need` skips the scan
    entirely, and skipping a scan nobody needed is not incomplete evidence.
    """
    sig = {"route": False, "mutable": False, "intake": False}
    truncated = False
    scanned = 0
    if need is not None and not need:
        return sig, False
    for rel in paths:
        low = "/" + rel.lower()
        if _is_document(rel) or not low.endswith(_SOURCE_SUFFIXES):
            continue
        if rel.count("/") >= _SOURCE_MAX_DEPTH:
            truncated = True
            continue
        if scanned >= _SOURCE_SCAN_CAP:
            truncated = True
            break
        text, trunc, ok = _read_file(root, rel, _SOURCE_READ_CAP)
        if not ok:
            continue
        scanned += 1
        truncated = truncated or trunc
        if _ROUTE_DECL_RE.search(text):
            sig["route"] = True
        if _MUTABLE_DECL_RE.search(text):
            sig["mutable"] = True
        if _INTAKE_DECL_RE.search(text):
            sig["intake"] = True
        if all(sig.get(k) for k in (need if need is not None else sig)):
            truncated = False if need is not None else truncated
            break
    return sig, truncated


def _document_free_paths(paths: list) -> list:
    """The lowercased, `/`-prefixed paths that are NOT documents — computed ONCE per resolution.

    Every path-token question below asks it of the same list, and re-deriving it per question cost
    more than every file read in this module put together (measured, 2026-09-05).
    """
    return ["/" + rel.lower() for rel in paths if not _is_document(rel)]


def _payment_webhook_path(lows: list) -> bool:
    """True when the TREE carries a payment WEBHOOK handler — a path that is BOTH an intake marker
    and a payment-provider name (`webhooks/stripe.py`). Either half alone is a different signal:
    a bare webhook is rule 2's input_trust intake, a bare provider name is not a handler. Documents
    are excluded by `_document_free_paths`, so `dashboards/api/TODO-stripe-webhook.md` is not a
    handler (finding 9)."""
    for low in lows:
        if any(tok in low for tok in _INTAKE_PATH_TOKENS) and any(
                _ident_matches(low.replace("/", "_"), tok) for tok in _PAYMENT_TOKENS):
            return True
    return False


def _has_path_token(lows: list, tokens) -> bool:
    """True when a NON-DOCUMENT path carries one of `tokens` (rule 2 excludes docs/dashboards)."""
    for low in lows:
        if any(tok in low for tok in tokens):
            return True
    return False


def _has_schema_path(lows: list) -> bool:
    """True when a SCHEMA-CLASS FILE (not merely a schema-shaped directory holding a README) exists."""
    for low in lows:
        if not low.endswith(_SCHEMA_SUFFIXES):
            continue
        if any(tok in low for tok in _SCHEMA_PATH_TOKENS):
            return True
    return False


def _live_event_seen(events, root: Path) -> bool:
    """True when the caller's journal rows carry a deploy/live-probe row FOR THIS REPO.

    A row that NAMES a repository must name this one: a `deploy_completed` from another project
    made this checkout live off the type alone (finding 30). A row that names none is the caller's
    already-scoped read (the module docstring's contract) and counts.
    """
    try:
        base = os.path.realpath(str(root))
        names = {base, os.path.basename(base)}
        for row in events or ():
            if not isinstance(row, dict) or row.get("type") not in _LIVE_EVENT_TYPES:
                continue
            claimed = [str(row[k]) for k in _EVENT_REPO_KEYS if row.get(k)]
            if not claimed:
                return True
            for value in claimed:
                if value in names or os.path.basename(value.rstrip("/")) in names:
                    return True
    except Exception:
        pass
    return False


#: The journal row type that RECORDS a resolved profile. Read off the rows the CALLER hands in —
#: this module never resolves a journal path (the module docstring's contract), exactly as
#: `_live_event_seen` reads liveness.
PROFILE_SNAPSHOT_EVENT_TYPES = ("profile_snapshot_recorded",)


def _row_repo_matches(row, payload, names) -> bool:
    """Shared repo-scoping for a caller-supplied row: a row that NAMES a repository must name THIS
    one; a row that names none is the caller's already-scoped read and counts (`_live_event_seen`'s
    rule, applied to the snapshot reader so another project's profile can never latch this repo)."""
    claimed = [str(h[k]) for h in (row, payload) if isinstance(h, dict)
               for k in _EVENT_REPO_KEYS if h.get(k)]
    if not claimed:
        return True
    return any(v in names or os.path.basename(v.rstrip("/")) in names for v in claimed)


def _snapshot_values(payload) -> dict:
    """The `{dim: value}` mapping carried by a recorded-snapshot payload.

    FAIL-CLOSED at every step, the same discipline `_overrides` applies: an unknown dimension key
    and an out-of-vocabulary value are DROPPED. A malformed snapshot therefore latches nothing
    rather than latching junk — and since a dropped entry leaves the derived value standing, the
    failure direction is the conservative one.

    Both payload shapes are accepted because both occur: `{"money": "present"}` and the resolution's
    own `{"money": {"value": "present", ...}}`.
    """
    raw = payload.get("dimensions") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return {}
    out = {}
    for dim, entry in raw.items():
        if dim not in VOCABULARY:
            continue
        value = entry.get("value") if isinstance(entry, dict) else entry
        if isinstance(value, str) and value.strip() in VOCABULARY[dim]:
            out[dim] = value.strip()
    return out


def _prior_snapshot(events, root: Path):
    """The LAST recorded profile snapshot FOR THIS REPO, as `({dim: value}, identity)`.

    NEWEST FIRST, THEN VALIDATE — and that order is the whole point, not an implementation detail.
    Validating during selection and skipping what fails would let a MALFORMED newest snapshot fall
    through to an OLDER valid one, which then latches values the project has since moved on from.
    Rule 7's subject is *the last recorded snapshot*: if that one cannot be read, the honest answer
    is NO LATCH, not a stale substitute.

    SELECTION IS ORDER-INDEPENDENT AND DETERMINISTIC ACROSS PROCESSES. The newest `ts` wins; ties at
    that `ts` are broken by the row's CANONICAL JSON, so two rows sharing a timestamp still order
    the same way whatever order the caller listed them in. A tied candidate that is not
    JSON-canonicalizable — a set, or any object whose `repr` carries identity — is REJECTED FAIL-
    CLOSED (no latch) rather than ordered by something that varies between processes. A `repr`
    fallback would have made the selected snapshot, and therefore the latched profile and its hash,
    depend on object identity; refusing is the only answer that keeps rule 3's determinism honest,
    and it never reaches past the newest snapshot to an older one.

    IDENTITY IS RETURNED WITH THE VALUES, not discarded: the latched dimension's `signal` has to
    name WHICH snapshot holds it, or the reader cannot audit the latch.

    NEVER RAISES — like `_live_event_seen`, any failure yields `({}, None)`, i.e. no latch.
    """
    try:
        base = os.path.realpath(str(root))
        names = {base, os.path.basename(base)}
        candidates = []
        for row in events or ():
            if not isinstance(row, dict) or row.get("type") not in PROFILE_SNAPSHOT_EVENT_TYPES:
                continue
            payload = row.get("data") if isinstance(row.get("data"), dict) else row
            if not _row_repo_matches(row, payload, names):
                continue
            candidates.append((str(row.get("ts") or payload.get("ts") or ""), row, payload))
        if not candidates:
            return {}, None

        newest_ts = max(ts for ts, _row, _payload in candidates)
        tied = [c for c in candidates if c[0] == newest_ts]
        keyed = []
        for ts, row, payload in tied:
            try:
                keyed.append((_canonical(row), row, payload, ts))
            except Exception:
                # A newest-snapshot candidate we cannot canonicalize deterministically. Refuse the
                # whole selection rather than order it unstably or skip past it to an older row.
                return {}, None
        _key, row, payload, ts = max(keyed, key=lambda k: k[0])

        values = _snapshot_values(payload)       # the WINNER is validated — see the docstring
        if not values:
            return {}, None
        identity = (payload.get("snapshot_hash") or row.get("snapshot_hash")
                    or ts or "an unidentified recorded snapshot")
        return values, str(identity)
    except Exception:
        return {}, None


def _apply_latch(dimensions: dict, prior_values: dict, identity) -> None:
    """Rule 7 — the hysteresis fold, applied ON TOP of the derived answer at the single site.

    "A dimension widens on one crossing and NARROWS only by an explicit owner override." So a
    latched dimension whose recorded value is STRICTLY WIDER than what this resolution derived
    keeps the recorded value — a signal that disappears (a deleted manifest, a moved migration, a
    reader that came back truncated) can no longer silently downgrade a high-risk dimension.

    THE OVERRIDE IS SKIPPED, DELIBERATELY: rule 4's `profile.override` is the ONE explicit narrowing
    path, so an owner declaration always defeats the latch. Every other source (`signal`, `derived`,
    `default`) is subject to it.

    Mutates `dimensions` in place, BEFORE the check-set and the two hashes are computed — a latched
    value is part of the profile, not an annotation on it.
    """
    if not prior_values:
        return
    for dim in LATCHED_DIMENSIONS:
        info = dimensions.get(dim)
        if not isinstance(info, dict) or info.get("source") == "override":
            continue
        prior = prior_values.get(dim)
        if prior is None or not _is_wider(dim, prior, info.get("value")):
            continue
        dimensions[dim] = {
            "value": prior,
            "source": "latched",
            "signal": (f"latched by SPEC-0198 rule 7 from the last recorded profile snapshot "
                       f"({identity}); narrows only by an explicit profile.override"),
        }

# ---------------------------------------------------------------------------
# Rule 4 — the owner override. Resolved BEFORE the dependent derivations that read it.
# ---------------------------------------------------------------------------

def _section_is_stale(section: dict) -> bool:
    """True when the `profile:` section declares an expiry that has passed (rule 4: "stale …
    = derived profile, conservative"). A stale section is dropped WHOLE, so a narrowing override
    cannot outlive the declaration that justified it."""
    for holder in (section, section.get("waiver") if isinstance(section.get("waiver"), dict) else {}):
        if not isinstance(holder, dict):
            continue
        raw = holder.get("until") or holder.get("expires") or holder.get("valid_until")
        if raw is None:
            continue
        text = str(raw).strip()[:10]
        try:
            from datetime import date
            y, m, d = (int(x) for x in text.split("-"))
            if date(y, m, d) < date.today():
                return True
        except Exception:
            continue
    return False


def _overrides(ops_map) -> dict:
    """The `profile.override` mapping, filtered to known dimensions and legal values.

    FAIL-CLOSED at every step, because rule 4 says an absent/stale/unparseable section reads
    "derived profile, conservative" and AC3 requires a MALFORMED section to read derived-conservative
    and NEVER narrower: a non-mapping `profile:`, a non-mapping `override:`, an unknown dimension key,
    an out-of-vocabulary value and an EXPIRED section are each simply dropped. A dropped override
    leaves the derived value standing, which is the conservative one — so malformation can only ever
    widen, never narrow.
    """
    if not isinstance(ops_map, dict):
        return {}                       # an unreadable carrier declares no override (rule 4)
    section = ops_map.get("profile")
    if not isinstance(section, dict):
        return {}
    if _section_is_stale(section):
        return {}
    raw = section.get("override")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for dim, val in raw.items():
        if dim not in VOCABULARY or not isinstance(val, str):
            continue
        v = val.strip()
        if v in VOCABULARY[dim]:
            out[dim] = v
    return out


# ---------------------------------------------------------------------------
# Rule 2 — the derivation table. THE one site.
# ---------------------------------------------------------------------------

_OVERRIDE_SIGNAL = "declared in yitc-ops.yaml"


def _apply_override(out: dict, dim: str, overrides: dict) -> None:
    """Rule 4 AT THE DAG NODE: the owner's value replaces the derived one BEFORE any dimension
    that depends on it is derived.

    Applying overrides only at the end left the dependents reading the pre-override upstream —
    `override.surface: public` on a stateful checkout still resolved `data_sensitivity=unknown`,
    and `override.money: present` on a live public app still resolved `live` rather than
    `live-critical` (finding 4). The override is a fact about the project, so every rule-2
    propagation must see it.
    """
    if dim in overrides:
        out[dim] = (overrides[dim], "override", _OVERRIDE_SIGNAL)


def _derive(root: Path, events=(), ops=None, overrides=None) -> dict:
    """Resolve every dimension from the signals, returning {dim: (value, source, signal)}.

    `source` is `signal` when a detector fired, `derived` when rule 2 propagates one dimension into
    another (surface -> input_trust, stateful+public -> pii-candidate, public+risk -> live-critical),
    `override` when the owner declared it (rule 4), and `default` when nothing resolved. A fifth,
    `latched`, is written by `_apply_latch` AFTER this function returns to its caller in
    `resolve_profile` (rule 7 — a recorded snapshot holding a high-risk dimension wide). Keeping the
    four apart is what lets the `profile` verb and the debt line say WHY a value reads as it does.

    EVIDENCE COMPLETENESS. Every reader reports truncation, and an incomplete read never buys a
    NARROW answer: the one narrow default in the table (`operational_criticality: prototype`) is
    withheld when the inventory or a signal file was cut short, exactly as it is when the ops
    carrier is unreadable. An `unknown` there is wide, and wide is the conservative direction.
    """
    overrides = overrides or {}
    paths, inv_truncated, tracked = _inventory(root)
    raw_ops = _load_ops(root, ops)
    ops_unreadable = raw_ops is _OPS_UNREADABLE
    ops_map = {} if ops_unreadable else raw_ops
    deps, dep_truncated = _manifest_deps(root, paths)
    tables, fields, has_schema_content, schema_truncated = _schema_evidence(root, paths)
    env_entries, env_truncated = _env_entries(root, paths)
    # The CHEAP path-token legs first: each question they answer YES is one the content scan below
    # does not have to open a single file to ask (the scan is this module's whole cost).
    lows = _document_free_paths(paths)
    route_path = _has_path_token(lows, _ROUTE_PATH_TOKENS)
    intake_path = _has_path_token(lows, _INTAKE_PATH_TOKENS)
    stateful_path = _has_schema_path(lows) or _has_path_token(lows, _STORAGE_PATH_TOKENS)
    need = {k for k, answered in (("route", route_path), ("intake", intake_path),
                                  ("mutable", stateful_path)) if not answered}
    src, src_truncated = _source_signals(root, paths, need)
    ops_sig = _ops_signals(ops_map)
    live_event = _live_event_seen(events, root)
    evidence_incomplete = any((inv_truncated, dep_truncated, schema_truncated, env_truncated,
                               src_truncated))

    deploy_declared = ops_sig["deploy_declared"]
    deploy_public = ops_sig["deploy_public"]
    route_evidence = src["route"] or route_path

    out: dict = {}

    # surface — a web framework, a route/handler declaration, a PUBLIC deploy, or a live deploy row.
    # A dual-use HTTP library counts ONLY beside route evidence (rule 2: a generic HTTP client is
    # never sufficient alone), and a bare `deploy.command` is liveness, not public reachability.
    if _deps_match(deps, _WEB_FRAMEWORK_TOKENS):
        out["surface"] = ("public", "signal", "web framework in a dependency manifest")
    elif route_evidence:
        out["surface"] = ("public", "signal", "route/handler declarations in the tree")
    elif deploy_public or live_event:
        out["surface"] = ("public", "signal",
                          "a publicly-addressed deploy" if deploy_public else "a deploy journal row")
    else:
        out["surface"] = ("unknown", "default", "no public-surface signal")
    _apply_override(out, "surface", overrides)

    # input_trust — an intake declaration/marker, else rule 2's propagation from surface.
    if src["intake"] or intake_path:
        out["input_trust"] = ("untrusted", "signal", "request-intake declarations (body/form/upload/webhook)")
    elif out["surface"][0] in ("public", "unknown"):
        out["input_trust"] = ("untrusted", "derived", "rule 2: untrusted if public or unknown")
    else:
        out["input_trust"] = ("unknown", "default", "no intake signal on a non-public surface")
    _apply_override(out, "input_trust", overrides)

    # statefulness — migrations/ORM in the tree, a DB dependency, a MUTABLE ENDPOINT, a storage
    # artefact, or a live app (rule 2: "stateful when mutable endpoints or a live app").
    if _has_schema_path(lows) or _deps_match(deps, _DB_TOKENS):
        out["statefulness"] = ("stateful", "signal", "migrations/ORM or a database dependency")
    elif src["mutable"] or _has_path_token(lows, _STORAGE_PATH_TOKENS):
        out["statefulness"] = ("stateful", "signal", "a mutable endpoint or a storage artefact")
    elif live_event or deploy_declared:
        out["statefulness"] = ("stateful", "derived", "rule 2: stateful for a live app")
    else:
        out["statefulness"] = ("unknown", "default", "no persistence signal")
    _apply_override(out, "statefulness", overrides)

    # users_roles_tenancy — an auth dependency, a user/role/session TABLE, or a declared ops auth
    # provider (rule 2 names `yitc-ops.yaml` among the sources for every derivable dimension).
    if _deps_match(deps, _AUTH_TOKENS):
        out["users_roles_tenancy"] = ("multi", "signal", "an auth dependency")
    elif any(_ident_matches(t, tok) for t in tables for tok in _AUTH_SCHEMA_TOKENS):
        out["users_roles_tenancy"] = ("multi", "signal", "a user/role/session table")
    elif ops_sig["auth"]:
        out["users_roles_tenancy"] = ("multi", "signal", "an auth provider declared in the ops carrier")
    else:
        out["users_roles_tenancy"] = ("unknown", "default", "no auth signal")
    _apply_override(out, "users_roles_tenancy", overrides)

    # data_sensitivity — PII-shaped schema fields; else rule 6's auth/user-table crossing (account
    # data IS personal data); else rule 2's stateful+public pii-candidate.
    if has_schema_content and any(_ident_matches(f, tok) for f in fields
                                  for tok in _PII_FIELD_TOKENS):
        out["data_sensitivity"] = ("pii", "signal", "PII-shaped fields in the schema")
    elif out["users_roles_tenancy"][0] == "multi":
        out["data_sensitivity"] = ("pii", "derived", "rule 6: authentication/account data is personal data")
    elif out["statefulness"][0] == "stateful" and out["surface"][0] == "public":
        out["data_sensitivity"] = ("pii", "derived", "rule 2: pii-candidate for a stateful public app")
    else:
        out["data_sensitivity"] = ("unknown", "default", "no PII signal")
    _apply_override(out, "data_sensitivity", overrides)

    # money — rule 2: "present on ANY payment signal", read across EVERY source rule 2 names.
    if _deps_match(deps, _PAYMENT_TOKENS) or _env_payment_signal(env_entries):
        out["money"] = ("present", "signal", "a payment SDK or key declaration")
    elif ops_sig["payment"]:
        out["money"] = ("present", "signal", "a payment provider named in the ops carrier")
    elif _payment_webhook_path(lows):
        out["money"] = ("present", "signal", "a payment webhook handler in the tree")
    else:
        out["money"] = ("unknown", "default", "no payment signal")
    _apply_override(out, "money", overrides)

    # external_integrations — an API-client dependency, a declared provider key, an ops provider
    # signal, or MONEY (rule 6: a payment SDK/key/webhook activates money AND external).
    if _deps_match(deps, _API_CLIENT_TOKENS):
        out["external_integrations"] = ("present", "signal", "an API-client dependency")
    elif _has_provider_key(env_entries):
        out["external_integrations"] = ("present", "signal", "declared provider keys (.env example)")
    elif ops_sig["provider_key"]:
        out["external_integrations"] = ("present", "signal",
                                        "a provider/key signal in the ops carrier")
    elif out["money"][0] == "present":
        out["external_integrations"] = ("present", "derived",
                                        "rule 6: a payment provider IS an external integration")
    else:
        out["external_integrations"] = ("unknown", "default", "no provider/key signal")
    _apply_override(out, "external_integrations", overrides)

    # operational_criticality — a live signal widens; absent one, rule 7's prototype bound holds,
    # but ONLY on evidence we actually finished reading.
    if deploy_declared or deploy_public or live_event:
        risky = (out["data_sensitivity"][0] == "pii" or out["money"][0] == "present"
                 or out["users_roles_tenancy"][0] == "multi")
        if out["surface"][0] == "public" and risky:
            out["operational_criticality"] = (
                "live-critical", "derived", "rule 2: live + public + PII/money/auth")
        else:
            out["operational_criticality"] = (
                "live", "signal",
                "a declared deploy command" if deploy_declared else "a deploy journal row")
    elif ops_unreadable:
        # The carrier exists and could not be read, so we cannot say a deploy is NOT declared.
        out["operational_criticality"] = (
            "unknown", "default", "yitc-ops.yaml unreadable — liveness unknown, never assumed absent")
    elif evidence_incomplete:
        # A cap stopped the read. `prototype` would assert an absence the evidence never showed.
        out["operational_criticality"] = (
            "unknown", "default", "evidence incomplete (a read cap was hit) — absence never assumed")
    else:
        out["operational_criticality"] = ("prototype", "default", "no live-deploy signal")
    _apply_override(out, "operational_criticality", overrides)

    # Declared-only dimensions (rule 2) — no detector, ever. A load-test/SLO artefact and a
    # caller-supplied collaborator proof are CROSSINGS that activate a lens (`_evidence` below);
    # neither sets a value here, because rule 2 says the checkout cannot prove either.
    for dim in DECLARED_ONLY:
        out[dim] = ("unknown", "default", "declared only — the checkout cannot prove it")
        _apply_override(out, dim, overrides)

    out["_evidence"] = {
        "load_artifact": _has_path_token(lows, _LOAD_ARTIFACT_TOKENS),
        "incomplete": evidence_incomplete,
        "tracked_inventory": tracked,
    }
    return out


# ---------------------------------------------------------------------------
# Rule 6 — the activation table, bounded by rule 7.
# ---------------------------------------------------------------------------

#: The constant floor every project hears, at every stage (rule 7).
CONSTANT_FLOOR = ("dependency-hygiene", "secrets")

#: (dimension, activating values) -> lens id. This IS rule 6's table; the rule names the crossings,
#: this names the lens each crossing activates. A lens's CONTENT is out of scope for T-12080.
_ACTIVATION = (
    ("surface", ("public", "unknown"), "public-boundary"),
    ("input_trust", ("untrusted",), "input-validation"),
    ("data_sensitivity", ("pii", "sensitive"), "data-retention"),
    ("money", ("present",), "payment-integrity"),
    ("users_roles_tenancy", ("multi",), "authz"),
    ("external_integrations", ("present",), "key-rotation"),
    ("statefulness", ("stateful",), "backup-restore"),
    # `unknown` activates alongside the two live values: rule 2 treats an unresolved dimension as
    # WIDE, and only a POSITIVE `prototype` reading (rule 7) narrows.
    ("operational_criticality", ("live", "live-critical", "unknown"), "deploy-readiness"),
    ("traffic_scale", ("low", "medium", "high"), "performance"),
    ("collaborator_rights", ("named-collaborators",), "shared-repo-floor"),
)

#: The rule-6 crossings whose DIMENSION stays declared-only (rule 2) but whose ARTEFACT is real
#: evidence: "a load-test/SLO artifact appears -> traffic_scale -> perf lens", "collaborator
#: proof/declaration -> collaborator_rights -> land-time shared floor". The lens activates off the
#: artefact; the dimension still reads `unknown` until someone DECLARES it (finding 6).
_EVIDENCE_ACTIVATION = (
    ("load_artifact", "performance"),
    ("collaborator_proof", "shared-repo-floor"),
)


def required_check_set(dimensions: dict, evidence=None) -> tuple:
    """The lens set this profile activates — SORTED, so it hashes deterministically.

    RULE 7'S BOUND IS APPLIED HERE, not left to each caller: a `prototype` criticality collapses the
    set to `CONSTANT_FLOOR` alone ("a prototype with no users hears only the constant floor").
    Putting it at the single derivation site is what makes it unskippable.

    `dimensions` is the resolved mapping {dim: {"value": …}} (or {dim: value}); both shapes are
    accepted. `evidence` is the optional crossing-artefact mapping (`_EVIDENCE_ACTIVATION`).
    """
    def _val(dim):
        v = dimensions.get(dim)
        if isinstance(v, dict):
            return v.get("value")
        return v

    if _val("operational_criticality") == "prototype":
        return tuple(sorted(CONSTANT_FLOOR))
    lenses = set(CONSTANT_FLOOR)
    for dim, activating, lens in _ACTIVATION:
        if _val(dim) in activating:
            lenses.add(lens)
    for key, lens in _EVIDENCE_ACTIVATION:
        if (evidence or {}).get(key):
            lenses.add(lens)
    return tuple(sorted(lenses))


# ---------------------------------------------------------------------------
# Rule 3 — the two hashes.
# ---------------------------------------------------------------------------

def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def profile_snapshot(dimensions: dict) -> str:
    """`snapshot_hash` — sha256 over the resolved VALUES and their SOURCES (rule 3: "covers the
    resolved values (+ overrides)"). The source is inside the hash on purpose: a value that flips
    from derived to owner-overridden is a different profile even at the same value, and a consumer
    that recorded the hash it acted under must see that change.

    The `signal` prose is deliberately OUTSIDE the hash — it is explanatory text, and hashing it
    would make a reworded explanation read as a profile crossing.
    """
    payload = {dim: [(dimensions.get(dim) or {}).get("value"),
                     (dimensions.get(dim) or {}).get("source")]
               for dim in DIMENSIONS}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def check_set_hash(dimensions: dict, evidence=None) -> str:
    """`check_set_hash` — sha256 over the DERIVED required check-set (rule 3). Separate from the
    snapshot because the two answer different questions: the snapshot says "is this the same
    project I judged?", the check-set hash says "is this the same set of checks I owed?"."""
    return hashlib.sha256(
        _canonical(list(required_check_set(dimensions, evidence))).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The public entry point.
# ---------------------------------------------------------------------------

def resolve_profile(root, *, events=(), ops=None, collaborator_proof=False) -> dict:
    """Resolve the project growth profile for the checkout at `root` (SPEC-0198 rules 2-4, 6-7).

    Rule 7's hysteresis latch is folded here too: a high-risk dimension (`LATCHED_DIMENSIONS`) that
    a RECORDED snapshot holds WIDER than this resolution derived keeps the recorded value with
    source `latched`. An owner `profile.override` still defeats it — rule 4 remains the one explicit
    narrowing path.

    Returns::

        {"dimensions": {dim: {"value", "source", "signal"}},
         "check_set": (lens, …),
         "evidence": {"load_artifact", "collaborator_proof", "incomplete", "tracked_inventory"},
         "snapshot_hash": <hex>,
         "check_set_hash": <hex>}

    `events` is the caller's journal rows (see the module docstring — this module never resolves a
    journal path). `ops` is an already-parsed `yitc-ops.yaml` mapping when the caller holds one.
    `collaborator_proof` is the PROVIDER-BACKED collaborator fact rule 2 says the checkout cannot
    prove: the caller supplies it or nobody does.

    THE CARRIER IS READ ONCE and threaded into both the derivation and the override read, so a
    resolution can never mix two versions of `yitc-ops.yaml` (finding 29).

    NEVER RAISES. A read that fails leaves its dimension at the conservative default, and a total
    derivation failure returns the conservative profile THROUGH THE SAME DEPENDENT RULES (rule 2
    still says untrusted-if-unknown, and an unreadable derivation is not a proven prototype).
    """
    root = Path(root)
    # NO CHECKOUT, NO PROFILE — a land tears its REPO_ROOT down at step 7 and `_debt_echo_lines()`
    # MUST go mute once it has. `resolved: False` is the honest report; `echo_line` suppresses on it.
    if not root.is_dir():
        return {"dimensions": {dim: {"value": CONSERVATIVE_DEFAULTS[dim], "source": "default",
                                     "signal": "no checkout at this path"}
                               for dim in DIMENSIONS},
                "check_set": (), "evidence": {}, "snapshot_hash": "", "check_set_hash": "",
                "resolved": False}
    try:
        ops_map = _load_ops(root, ops)
        overrides = _overrides(ops_map)
    except Exception:
        ops_map, overrides = _OPS_UNREADABLE, {}
    try:
        derived = _derive(root, events=events, ops=ops_map, overrides=overrides)
    except Exception:
        # The conservative FALLBACK, built through rule 2's own dependent rules rather than from
        # the raw defaults: an unknown surface is untrusted, and a derivation we could not run is
        # not evidence of a prototype (finding 31).
        derived = {dim: (CONSERVATIVE_DEFAULTS[dim], "default", "derivation unavailable")
                   for dim in DIMENSIONS}
        derived["input_trust"] = ("untrusted", "derived", "rule 2: untrusted if public or unknown")
        derived["operational_criticality"] = (
            "unknown", "default", "derivation unavailable — liveness never assumed absent")
        for dim, value in overrides.items():
            derived[dim] = (value, "override", _OVERRIDE_SIGNAL)

    evidence = dict(derived.pop("_evidence", {}) or {})
    evidence["collaborator_proof"] = bool(collaborator_proof)

    dimensions = {}
    for dim in DIMENSIONS:
        value, source, signal = derived.get(
            dim, (CONSERVATIVE_DEFAULTS[dim], "default", "no signal"))
        dimensions[dim] = {"value": value, "source": source, "signal": signal}

    # RULE 7 — the hysteresis latch, folded ON TOP of the derived answer and BEFORE the check-set
    # and the two hashes, so a latched value is part of the profile the caller acts on (and of both
    # hashes) rather than an annotation beside it. The prior snapshot comes off the rows the CALLER
    # handed in — this module still resolves no journal path.
    prior_values, prior_identity = _prior_snapshot(events, root)
    _apply_latch(dimensions, prior_values, prior_identity)

    check_set = required_check_set(dimensions, evidence)
    return {
        "dimensions": dimensions,
        "check_set": check_set,
        "evidence": evidence,
        "snapshot_hash": profile_snapshot(dimensions),
        "check_set_hash": check_set_hash(dimensions, evidence),
        "resolved": True,
    }


# ---------------------------------------------------------------------------
# Rendering — the ONE line the seams show, and the verb's full readout.
# ---------------------------------------------------------------------------

def echo_line(resolution: dict):
    """The ONE report-only line the debt echo renders: snapshot hash + activated lens set.

    SUPPRESSED-WHEN-CLEAN — returns None on a checkout with NOTHING TO SAY, which is the card's
    "entirely unknown AND no lens activates" read against the seam this line actually rides.

    WHY THE READING IS THIS ONE, stated because the naive reading is wrong here. The card's
    conjunction, taken as "every value is literally `unknown` and the lens tuple is empty", can never
    fire: the constant floor is unconditional, so the tuple is never empty. A line that always
    renders would be fine on a surface of its own — but this line rides `views._render_debt_echo`,
    whose two callers are INDISTINGUISHABLE from inside it (session start and the `debt` re-fold
    both call the bare `_debt_echo_lines()`, and `test_t11353::test_d5` pins exactly that), while
    `test_t9754` requires the `debt` command to print NOTHING on a clean fixture. So the honest
    reading of both documents together is:

      * "entirely unknown" = no dimension resolved from EVIDENCE — every value is a default or a
        rule-2 propagation, none is a `signal` and none is an owner `override`;
      * "no lens activates" = nothing activated BEYOND the constant floor, which no crossing
        activates because it is constant (SPEC-0198 rule 5 speaks of what a CROSSING activates).

    A bare checkout therefore stays silent and a project with any real signal speaks — which is also
    what the card wants substantively: the profile becomes visible when the project has a profile.
    The full resolution is always available on demand from `bin/yitc-v2 profile`, which states its
    answer rather than falling silent.

    Report-only always: nothing here gates, blocks or auto-acts.
    """
    if not (resolution or {}).get("resolved"):
        return None                     # no checkout was read — see `resolve_profile`
    dims = (resolution or {}).get("dimensions") or {}
    check_set = tuple((resolution or {}).get("check_set") or ())
    # `latched` counts as evidence alongside `signal`/`override`: a dimension held wide by a
    # recorded snapshot (rule 7) is a project that HAS a profile, and falling silent about it would
    # hide exactly the high-risk reading the latch exists to preserve.
    no_evidence = all((dims.get(d) or {}).get("source") not in ("signal", "override", "latched")
                      for d in DIMENSIONS)
    nothing_beyond_floor = set(check_set) <= set(CONSTANT_FLOOR)
    if no_evidence and nothing_beyond_floor:
        return None
    shown = []
    for dim in DIMENSIONS:
        info = dims.get(dim) or {}
        if info.get("value") in (None, "unknown"):
            continue
        mark = " (override)" if info.get("source") == "override" else ""
        shown.append(f"{dim}={info.get('value')}{mark}")
    profile_txt = ", ".join(shown) if shown else "every dimension unknown"
    # THE PREFIX IS `profile:`, NOT `debt:`, AND THAT IS A CORRECTNESS PROPERTY, NOT A LABEL CHOICE.
    # This line RIDES the debt echo's seams but is not a debt item: SPEC-0119's debt lines are
    # SUPPRESSED-WHEN-CLEAN, and `test_t9754_proactive_debt_echo` pins that a clean session start
    # emits no `debt:` line at all. A profile readout that always renders — which is what SPEC-0198's
    # own suppression rule asks for — would have broken that pinned contract had it worn the `debt:`
    # prefix. Wearing its own prefix keeps both promises intact: the debt discipline is untouched,
    # and the profile is readable at every seam. (Caught by that test, 2026-09-04.)
    return (f"profile: {(resolution or {}).get('snapshot_hash', '')[:12]} — {profile_txt}; "
            f"lenses active: {', '.join(check_set) if check_set else 'none'}. "
            f"Report-only (SPEC-0198): derived from the checkout + this repo's journal, nothing is "
            f"gated, filed or deployed by it. Read the full resolution with `bin/yitc-v2 profile`; "
            f"declare only what the kernel cannot derive under `profile.override` in yitc-ops.yaml.")


def render(resolution: dict) -> list:
    """The `profile` verb's readout — one line per dimension, then the two hashes and the lens set.
    An `override` is rendered AS an override (rule 4: "a present override … is rendered as
    `override`"), which is what makes an owner declaration visibly the owner's."""
    dims = (resolution or {}).get("dimensions") or {}
    lines = ["profile (SPEC-0198) — derived, read-only; nothing here is written or emitted:"]
    width = max(len(d) for d in DIMENSIONS)
    for dim in DIMENSIONS:
        info = dims.get(dim) or {}
        value = info.get("value", "unknown")
        source = info.get("source", "default")
        rendered = f"{value} (override)" if source == "override" else f"{value} ({source})"
        lines.append(f"  {dim.ljust(width)}  {rendered}   [{info.get('signal', '')}]")
    lines.append(f"  snapshot_hash   {(resolution or {}).get('snapshot_hash', '')}")
    lines.append(f"  check_set_hash  {(resolution or {}).get('check_set_hash', '')}")
    lines.append(f"  lenses active   {', '.join((resolution or {}).get('check_set') or ()) or 'none'}")
    return lines


# ---------------------------------------------------------------------------
# The single-derivation-site tripwire (AC2) — homed HERE, beside what it protects.
# ---------------------------------------------------------------------------

#: Every value a dimension may take, minus `unknown` (which is ordinary prose everywhere). A file
#: that names dimensions AND assigns their values is deriving; one that names dimensions only is
#: consuming — a renderer's `COLUMNS = ("surface", "input_trust", "money")` is not a second
#: derivation table, and flagging it was a false positive (finding 33).
_DIMENSION_VALUES = frozenset(
    v for vals in VOCABULARY.values() for v in vals if v != "unknown")


def _dimension_value_constants(tree) -> set:
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value in _DIMENSION_VALUES}


def _assigned_dimension_keys(tree) -> dict:
    """Per enclosing function, the dimension names ASSIGNED as subscript/attribute keys.

    `out["surface"] = …; out["money"] = …` IS a derivation table written statement by statement —
    the shape a literal-collection scan cannot see and which returned a clean bill of health on a
    hand-rolled copy (finding 32).
    """
    found: dict = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            continue
        names = set()
        for node in ast.walk(fn):
            targets = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for tgt in targets:
                if isinstance(tgt, ast.Subscript) and isinstance(tgt.slice, ast.Constant):
                    if tgt.slice.value in DIMENSIONS:
                        names.add(tgt.slice.value)
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and key.value in DIMENSIONS:
                        names.add(key.value)
        if names:
            found[getattr(fn, "name", "<module>")] = names
    return found


def second_derivation_sites(paths) -> list:
    """Files that appear to carry a SECOND copy of the derivation table (SPEC-0198 rule 3, AC2).

    A copy of the table is recognized by EITHER shape, and both require evidence of DERIVATION —
    dimension names together with the values they are being given:

      * a LITERAL COLLECTION naming three or more dimensions in a file that also spells at least
        two dimension VALUES (a table written as data);
      * a FUNCTION that assigns three or more dimension keys (a table written as statements).

    It lives in THIS module, not only in the test, for the reason rule 3 exists: the property is the
    resolver's, so the check belongs beside the thing it protects. The test supplies the
    differential — a planted copy of each shape the tripwire must flag, and a pure CONSUMER it must
    not — which is what proves it is not vacuous (SPEC-0165).

    `paths` is an iterable of files to scan; the caller decides the scope (the test scans the whole
    governed `bin/` tree other than this module). A file that will not parse is skipped.
    """
    flagged = []
    for path in paths:
        p = Path(path)
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        value_constants = _dimension_value_constants(tree)
        hit = False
        for fn, names in _assigned_dimension_keys(tree).items():
            if len(names) >= 3:
                hit = True
                break
        if not hit and len(value_constants) >= 2:
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Tuple, ast.List, ast.Set, ast.Dict)):
                    continue
                elts = list(node.keys) if isinstance(node, ast.Dict) else list(node.elts)
                names = {e.value for e in elts
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                if len(names & set(DIMENSIONS)) >= 3:
                    hit = True
                    break
        if hit:
            flagged.append(str(p))
    return sorted(set(flagged))
