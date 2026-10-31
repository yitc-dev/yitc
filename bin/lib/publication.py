"""The publication package of a public post (SPEC-1057) — its canonical form and hash, the scrub before
consent, the consent check, and the split of what cannot be cleaned.

A post to the community commons or a public forge names the PACKAGE the person consented to: content,
attachments, published metadata, destination and visibility. This module computes `package_sha256`
over the canonical form SPEC-1057's implementation notes define, refuses the consent text while any
string the package would publish still holds a secret shape, a private path, an unchosen project name
or something it cannot read, and cuts what cannot be cleaned out of the package so that only a
DESCRIPTION of it reaches the installation's internal channel — through the governed `cross request`
author verb (SPEC-0086); this module writes no store itself.

Reused, never forked: the secret shapes are the journal's write-time redaction
(`journal.redact_secrets`, SPEC-0163 §4e, over the land floor's patterns) and the private-path shape
is the release host-leak pattern (`release.HOST_PATH_RE`). Business detail is not mechanically
detectable: the person reads the consent text.

A package is a dict: `content` (bytes), `attachments` ({name: bytes}), `metadata` (a JSON object),
`destination` (str), `visibility` (str).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PARTS = ("content", "attachments", "metadata", "destination", "visibility")

#: An OPAQUE run — text the scrub cannot read, so cannot check: a maximal run of at least 32 characters
#: of the base64 / base64url / hex alphabet with at least one segment (split on + / = _ -) of 8 or more
#: characters mixing letters and digits. Hex and base64 blobs match; plain words, slugs of words and
#: numbers (`T-14379-activate-spec-1057`) and dotted URLs do not. A run shorter than 32 characters (an
#: abbreviated hash, an identifier) is read as text.
_OPAQUE_RUN_RE = re.compile(r"[A-Za-z0-9+/=_-]{32,}")
_OPAQUE_SEGMENT_RE = re.compile(r"(?=[A-Za-z0-9]*[0-9])(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{8,}")
#: The ONE known public shape an opaque run may take: the 43-character unpadded base64 body of an OpenSSH
#: key fingerprint written `SHA256:<body>` (a release trust anchor installers verify against). Only that
#: exact body after that exact prefix is read as text; the same body without the prefix, a 42- or
#: 44-character body, padding or another prefix stays an opaque run (T-14393).
_KEY_FINGERPRINT_PREFIX = "SHA256:"
_KEY_FINGERPRINT_BODY_RE = re.compile(r"[A-Za-z0-9+/]{43}")

#: A WHOLE PART that is nothing but base64 / hex characters, at ANY length (owner decision (A),
#: events.jsonl#ts=2026-10-30T20:10:02Z): the content, an attachment or a metadata string value whose
#: text, stripped of surrounding whitespace, is only that alphabet and holds a digit or one of + / =.
#: A word of letters, `-` and `_` (`public`, `my-label`) is text. A short token INSIDE prose is read as
#: text and stays visible: the consent text shows every remaining byte and the person classifies it.
_WHOLE_PART_RE = re.compile(r"[A-Za-z0-9+/=_-]+")
_ENCODING_MARK_RE = re.compile(r"[0-9+/=]")

PRIVATE_PATH_PLACEHOLDER = "<host-home>"
PROJECT_PLACEHOLDER = "<project>"


class PackageError(ValueError):
    """The package or its manifest is malformed — no hash can be computed."""


class PackageRefused(Exception):
    """The consent text is refused: the package still holds what must not be published.
    `findings` lists (kind, field) pairs — never the matched value."""

    def __init__(self, findings):
        self.findings = list(findings)
        super().__init__("the package is refused before consent until it is scrubbed: "
                         + "; ".join(f"{k} in {f}" for k, f in self.findings))


class PackageChanged(Exception):
    """The package changed after consent: the consent recorded for the old hash does not cover it."""


class PublicationError(RuntimeError):
    """The preparation could not route the uncleanable description to the internal channel."""


# ── the canonical form and its hash ─────────────────────────────────────────────────────────────

def _check(pkg) -> None:
    if not isinstance(pkg, dict):
        raise PackageError("a package is a mapping of " + ", ".join(PARTS))
    missing = [p for p in PARTS if p not in pkg]
    if missing:
        raise PackageError(f"the package lacks: {', '.join(missing)}")
    if not isinstance(pkg["content"], bytes):
        raise PackageError("content must be bytes")
    att = pkg["attachments"]
    if not isinstance(att, dict) or not all(isinstance(k, str) and k and isinstance(v, bytes)
                                            for k, v in att.items()):
        raise PackageError("attachments must map a non-empty name to bytes")
    if not isinstance(pkg["metadata"], dict):
        raise PackageError("metadata must be a JSON object")
    # Plain JSON only — objects with string keys, arrays, strings, numbers, booleans, null — so every
    # string the canonical form serializes is one the scan and the scrub walk (a tuple, a non-string
    # key or NaN would be serialized yet walked differently, or not at all).
    if json.loads(_metadata_bytes(pkg["metadata"])) != pkg["metadata"]:
        raise PackageError("metadata must be plain JSON: objects with string keys, arrays (lists), "
                           "strings, numbers, booleans and null")
    for p in ("destination", "visibility"):
        if not isinstance(pkg[p], str) or not pkg[p].strip():
            raise PackageError(f"{p} must be a non-empty string")


def _metadata_bytes(metadata: dict) -> bytes:
    try:
        return json.dumps(metadata, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PackageError(f"metadata is not JSON-serializable: {exc}") from exc


def part_list(pkg) -> list:
    """The canonical parts in their fixed order, as (name, bytes): content, one `attachment/<name>`
    per attachment sorted by name, metadata, destination, visibility."""
    _check(pkg)
    parts = [("content", pkg["content"])]
    parts += [(f"attachment/{name}", pkg["attachments"][name]) for name in sorted(pkg["attachments"])]
    parts += [("metadata", _metadata_bytes(pkg["metadata"])),
              ("destination", pkg["destination"].encode("utf-8")),
              ("visibility", pkg["visibility"].encode("utf-8"))]
    return parts


def canonical_form(pkg) -> bytes:
    """SPEC-1057 implementation notes: per part, the byte length of its name, LF, the name, LF, the
    byte length of its bytes, LF, the bytes, LF — lengths in decimal ASCII, names in UTF-8. Every
    field is length-prefixed, so no two packages share a form."""
    out = bytearray()
    for name, data in part_list(pkg):
        nb = name.encode("utf-8")
        out += str(len(nb)).encode("ascii") + b"\n" + nb + b"\n"
        out += str(len(data)).encode("ascii") + b"\n" + data + b"\n"
    return bytes(out)


def package_sha256(pkg) -> str:
    return hashlib.sha256(canonical_form(pkg)).hexdigest()


def package_parts_summary(pkg) -> list:
    """[[name, byte length], ...] in canonical order — what a journal row records beside the hash."""
    return [[name, len(data)] for name, data in part_list(pkg)]


def load_package(manifest_path) -> dict:
    """A package from a JSON manifest: {"content": <path>, "attachments": [<path>, ...], "metadata":
    {...}, "destination": "...", "visibility": "..."}. Paths resolve against the manifest's directory;
    an attachment is named by its file name. Every failure raises PackageError naming it."""
    mp = Path(manifest_path)
    try:
        manifest = json.loads(mp.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PackageError(f"the package manifest {mp} cannot be read: {exc}") from exc
    except ValueError as exc:
        raise PackageError(f"the package manifest {mp} is not JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PackageError(f"the package manifest {mp} is not a JSON object")
    missing = [p for p in PARTS if p not in manifest]
    if missing:
        raise PackageError(f"the package manifest {mp} lacks: {', '.join(missing)}")

    def _read(rel):
        if not isinstance(rel, str) or not rel:
            raise PackageError(f"a package file path must be a non-empty string, got {rel!r}")
        p = Path(rel) if Path(rel).is_absolute() else mp.parent / rel
        try:
            return p.name, p.read_bytes()
        except OSError as exc:
            raise PackageError(f"the package file {rel} cannot be read: {exc}") from exc

    if not isinstance(manifest["attachments"], list):
        raise PackageError("attachments must be a list of file paths")
    attachments = {}
    for rel in manifest["attachments"]:
        name, data = _read(rel)
        if name in attachments:
            raise PackageError(f"two attachments share the name {name!r}")
        attachments[name] = data
    pkg = {"content": _read(manifest["content"])[1], "attachments": attachments,
           "metadata": manifest["metadata"], "destination": manifest["destination"],
           "visibility": manifest["visibility"]}
    _check(pkg)
    return pkg


# ── what the package publishes, and what must not be in it ──────────────────────────────────────

def _meta_items(v, where):
    """(label, text, is_key) for every string in plain-JSON metadata, in a fixed order (keys sorted).
    Labels are POSITIONAL (`metadata[2][0]`, `metadata[2] key`): a label never carries the text of
    a key or a value, so a finding, a description or a refusal can never re-publish what it names."""
    if isinstance(v, str):
        yield where, v, False
    elif isinstance(v, dict):
        for i, k in enumerate(sorted(v)):
            yield f"{where}[{i}] key", k, True
            yield from _meta_items(v[k], f"{where}[{i}]")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _meta_items(x, f"{where}[{i}]")


def _strings(pkg) -> list:
    """(field, text-or-None, payload) for EVERY string the package publishes: the content and each
    attachment (None when not valid UTF-8), each attachment name, every metadata key and value, the
    destination and the visibility. `payload` marks the parts the scrub may cut (content, attachments,
    metadata values); names, keys, destination and visibility are addressing and are never cut.
    Fields are named by POSITION (`attachment 2`, `attachment 2 name`), never by their text."""
    names = sorted(pkg["attachments"])
    out = []
    for field, data in [("content", pkg["content"])] + [(f"attachment {i + 1}", pkg["attachments"][n])
                                                        for i, n in enumerate(names)]:
        try:
            out.append((field, data.decode("utf-8"), True))
        except UnicodeDecodeError:
            out.append((field, None, True))
    out += [(f"attachment {i + 1} name", n, False) for i, n in enumerate(names)]
    out += [(label, text, not is_key) for label, text, is_key in _meta_items(pkg["metadata"], "metadata")]
    out += [("destination", pkg["destination"], False), ("visibility", pkg["visibility"], False)]
    return out


def _whole_part_encoded(text) -> bool:
    """True when the whole part is nothing but base64 / hex characters (see `_WHOLE_PART_RE`)."""
    s = text.strip()
    return bool(s) and _WHOLE_PART_RE.fullmatch(s) is not None and _ENCODING_MARK_RE.search(s) is not None


def _name_re(names):
    names = [n for n in (names or ()) if isinstance(n, str) and n.strip()]
    if not names:
        return None
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9])",
                      re.IGNORECASE)


#: EXACTLY the tokens the scrub writes, nothing shaped like them: the journal's write-time redaction
#: mark (`journal.JOURNAL_REDACT_PLACEHOLDER` with atom `secrets` and a rid that is `sha256-` + 12 hex
#: or `journal.JOURNAL_WRITE_REDACT_UNHASHED`), `<host-home>` and `<project>`. Each is fixed vocabulary
#: and carries nothing of the project, so a project name is never looked for, or replaced, inside one
#: (a project named `project` or `host` must not make the scrub's own output read as a finding), while
#: a look-alike such as `<redacted:Acme>` is ordinary text and is scanned and scrubbed like any other.
_PLACEHOLDER_RE = re.compile(r"<redacted:secrets:(?:sha256-[0-9a-f]{12}|unhashed)>|"
                             + re.escape(PRIVATE_PATH_PLACEHOLDER) + "|" + re.escape(PROJECT_PLACEHOLDER))


def _outside_placeholders(text, fn):
    """`fn` applied to every span of `text` outside the scrub's placeholders; the placeholders kept."""
    out, last = [], 0
    for m in _PLACEHOLDER_RE.finditer(text):
        out += [fn(text[last:m.start()]), m.group(0)]
        last = m.end()
    out.append(fn(text[last:]))
    return "".join(out)


def _is_opaque(text, m):
    """an `_OPAQUE_RUN_RE` match of `text` the scrub cannot read: it holds a letter+digit segment and is not
    the body of a `SHA256:` key fingerprint"""
    run = m.group(0)
    if not _OPAQUE_SEGMENT_RE.search(run):
        return False
    return not (text[max(0, m.start() - len(_KEY_FINGERPRINT_PREFIX)):m.start()] == _KEY_FINGERPRINT_PREFIX
                and _KEY_FINGERPRINT_BODY_RE.fullmatch(run))


def _opaque_runs(text):
    return [m for m in _OPAQUE_RUN_RE.finditer(text) if _is_opaque(text, m)]


def findings(pkg, *, project_names=(), name_project=False) -> list:
    """(kind, field) per finding over every published string: `secret` (a floor credential shape),
    `private path` (a host home path), `project name` (a name or domain of the project the person did
    not choose to name), `uncleanable` (bytes that are not valid UTF-8, an opaque run, or a whole
    content / attachment / metadata value that is nothing but base64 / hex characters). A field is
    named by position, never by its text."""
    from lib import journal, release   # noqa: PLC0415 — lazy: both are large hosts
    _check(pkg)
    name_re = None if name_project else _name_re(project_names)
    found = []
    for field, text, payload in _strings(pkg):
        if text is None:
            found.append(("uncleanable", field))
            continue
        if journal.redact_secrets(text) != text:
            found.append(("secret", field))
        if release.HOST_PATH_RE.search(text):
            found.append(("private path", field))
        if name_re is not None and name_re.search(_PLACEHOLDER_RE.sub(" ", text)):
            found.append(("project name", field))
        if _opaque_runs(text) or (payload and _whole_part_encoded(text)):
            found.append(("uncleanable", field))
    return found


def _map_strings(pkg, fn_text) -> dict:
    """A NEW package with `fn_text` applied to every published string (bytes parts decoded; an
    undecodable part is left as it is). Two attachment names, or two keys of one metadata object,
    that become the same after cleaning are refused (PackageError), never merged."""
    def on_bytes(data):
        try:
            return fn_text(data.decode("utf-8")).encode("utf-8")
        except UnicodeDecodeError:
            return data

    def on_meta(v, where):
        if isinstance(v, str):
            return fn_text(v)
        if isinstance(v, dict):
            out = {}
            for i, k in enumerate(sorted(v)):
                nk = fn_text(k)
                if nk in out:
                    raise PackageError(f"two keys of {where} become the same after cleaning "
                                       f"(key {i}): rename one before consent")
                out[nk] = on_meta(v[k], f"{where}[{i}]")
            return out
        if isinstance(v, list):
            return [on_meta(x, f"{where}[{i}]") for i, x in enumerate(v)]
        return v

    attachments = {}
    for i, n in enumerate(sorted(pkg["attachments"])):
        nn = fn_text(n)
        if nn in attachments:
            raise PackageError(f"two attachment names become the same after cleaning (attachment {i + 1}): "
                               f"rename one before consent")
        attachments[nn] = on_bytes(pkg["attachments"][n])
    return {"content": on_bytes(pkg["content"]), "attachments": attachments,
            "metadata": on_meta(pkg["metadata"], "metadata"), "destination": fn_text(pkg["destination"]),
            "visibility": fn_text(pkg["visibility"])}


def scrub(pkg, *, project_names=(), name_project=False) -> dict:
    """A NEW package with every secret, private path and unchosen project name replaced in every
    published string: a credential by the journal's redaction placeholder, a host home path by
    `<host-home>`, a project name by `<project>` (never inside a placeholder already written)."""
    from lib import journal, release   # noqa: PLC0415
    _check(pkg)
    name_re = None if name_project else _name_re(project_names)

    def clean(text):
        text = release.HOST_PATH_RE.sub(PRIVATE_PATH_PLACEHOLDER, journal.redact_secrets(text))
        if name_re is None:
            return text
        return _outside_placeholders(text, lambda span: name_re.sub(PROJECT_PLACEHOLDER, span))
    return _map_strings(pkg, clean)


def _describe(field, reason, data: bytes) -> dict:
    return {"field": field, "reason": reason, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()[:12]}


def split_uncleanable(pkg) -> tuple:
    """(clean package, descriptions). A content or attachment part that is not valid UTF-8, or that is
    as a whole nothing but base64 / hex characters, is removed (content becomes empty); a metadata
    value that is such a whole part is replaced by a marker; an opaque run inside the content, an
    attachment or a metadata value is cut out and marked. Each description names the field BY
    POSITION in the draft (`attachment 2`, `metadata[1]`), the reason, the byte count and a short
    sha256 — never the bytes, never a name or a key. An opaque run in an attachment name, a metadata
    key, the destination or the visibility is not cut: `findings` still reports it, so the consent
    stays refused until the person changes that field."""
    _check(pkg)
    descriptions = []

    def cut_text(field, text):
        if _whole_part_encoded(text):
            descriptions.append(_describe(field, "encoded blob", text.encode("utf-8")))
            return None

        def cut(m):
            run = m.group(0)
            if not _is_opaque(text, m):
                return run
            descriptions.append(_describe(field, "encoded blob", run.encode("utf-8")))
            return f"[removed: encoded blob, {len(run)} chars — described on the internal channel]"
        return _OPAQUE_RUN_RE.sub(cut, text)

    def part(field, data):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            descriptions.append(_describe(field, "undecodable bytes", data))
            return None
        kept = cut_text(field, text)
        return None if kept is None else kept.encode("utf-8")

    def meta(v, where):
        if isinstance(v, str):
            kept = cut_text(where, v)
            return (f"[removed: encoded blob, {len(v)} chars — described on the internal channel]"
                    if kept is None else kept)
        if isinstance(v, dict):
            return {k: meta(v[k], f"{where}[{i}]") for i, k in enumerate(sorted(v))}
        if isinstance(v, list):
            return [meta(x, f"{where}[{i}]") for i, x in enumerate(v)]
        return v

    content = part("content", pkg["content"])
    attachments = {}
    for i, name in enumerate(sorted(pkg["attachments"])):
        kept = part(f"attachment {i + 1}", pkg["attachments"][name])
        if kept is not None:
            attachments[name] = kept
    return ({"content": content if content is not None else b"", "attachments": attachments,
             "metadata": meta(pkg["metadata"], "metadata"), "destination": pkg["destination"],
             "visibility": pkg["visibility"]}, descriptions)


# ── consent ─────────────────────────────────────────────────────────────────────────────────────

def consent_text(pkg, *, project_names=(), name_project=False, removed=()) -> str:
    """The text the person consents to: EVERY part in full — the content and each attachment's whole
    text, the metadata, the destination and the visibility — and the package_sha256 the consent covers,
    plus one `removed before consent` line per description in `removed` (never the removed bytes).
    Refused (PackageRefused) while any finding remains — scrub, uncleanable or project name."""
    found = findings(pkg, project_names=project_names, name_project=name_project)
    if found:
        raise PackageRefused(found)
    lines = [f"Publication package — consent covers package_sha256 {package_sha256(pkg)}",
             f"destination: {pkg['destination']}", f"visibility: {pkg['visibility']}",
             "metadata: " + _metadata_bytes(pkg["metadata"]).decode("utf-8"),
             "content:", pkg["content"].decode("utf-8")]
    if not pkg["attachments"]:
        lines.append("attachments: none")
    for name in sorted(pkg["attachments"]):
        data = pkg["attachments"][name]
        lines += [f"attachment {name} ({len(data)} bytes):", data.decode("utf-8")]
    lines += [f"removed before consent: the draft's {d['field']} — {d['reason']}, {d['bytes']} bytes "
              f"(described on the internal channel, not posted)" for d in removed]
    return "\n".join(lines) + "\n"


def consent_covers(consented_sha256, pkg) -> bool:
    """True only when the package is byte for byte the one whose hash the consent named."""
    return isinstance(consented_sha256, str) and consented_sha256 == package_sha256(pkg)


def require_consent(consented_sha256, pkg) -> None:
    if not consent_covers(consented_sha256, pkg):
        raise PackageChanged(f"the package changed after consent (consented {consented_sha256}, now "
                             f"{package_sha256(pkg)}): fresh consent is needed before posting")


# ── the internal channel and the one preparation entry point ────────────────────────────────────

def internal_channel_brief(descriptions) -> str:
    """The brief for `cross request --kind note`: a description per uncleanable part — its position
    in the draft, the reason, the byte count and a short sha256 — and nothing of the draft's own text
    (no content, name, key or destination). The cross log write applies the kernel's redaction on top."""
    items = "; ".join(f"the draft's {d['field']}: {d['reason']}, {d['bytes']} bytes, sha256 {d['sha256']}"
                      for d in descriptions)
    return (f"[publication] a draft publication held content that could not be cleaned; it was not "
            f"posted (SPEC-1057): {items}. The parts stay where the draft is; this note carries no part "
            f"of them.")


def route_to_internal_channel(brief: str, to: str, *, env=None) -> str:
    """Append the brief to the cross log through the governed `cross request` author verb of THIS
    engine (no second write path). Returns the allocated X-id; PublicationError on any failure."""
    cli = Path(__file__).resolve().parents[1] / "yitc-v2"
    r = subprocess.run([sys.executable, str(cli), "cross", "request", "--to", to, "--kind", "note",
                        "--brief", brief], env=dict(os.environ if env is None else env),
                       capture_output=True, text=True)
    m = re.search(r"\bX-\d{4,}\b", r.stdout)
    if r.returncode != 0 or not m:
        raise PublicationError(f"`cross request` did not record the description (exit {r.returncode}): "
                               + (r.stderr or r.stdout).strip()[-400:])
    return m.group(0)


def prepare_publication(draft, *, internal_to, project_names=(), name_project=False, route=None) -> dict:
    """The preparation of a post: cut what cannot be cleaned out and route its description to the
    internal channel, scrub, then build the consent text (refused while anything remains). Returns
    {package, consent_text, package_sha256, descriptions, routed}."""
    clean, descriptions = split_uncleanable(draft)
    routed = None
    if descriptions:
        routed = (route or route_to_internal_channel)(
            internal_channel_brief(descriptions), internal_to)
    clean = scrub(clean, project_names=project_names, name_project=name_project)
    text = consent_text(clean, project_names=project_names, name_project=name_project,
                        removed=descriptions)
    return {"package": clean, "consent_text": text, "package_sha256": package_sha256(clean),
            "descriptions": descriptions, "routed": routed}
