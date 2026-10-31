"""`external-read` — the kernel's address check before the AI tool's reader (T-14378, SPEC-1056).

A session reads external content only through the reader its AI tool provides, and runs this verb
on every address first (a redirect target included — it comes back as a new link). The rules are
SPEC-1056's (rule 2 the check, rule 2a what the kernel keeps, rule 5 the pending lines); this module
holds the one check function and the lines the verb prints, nothing else.

  external-read <address>                      OK <shown>            exit 0
                                                REFUSED <why> :: <shown>   exit 3
  external-read <path or text, no "://">        PENDING ...           exit 3
  external-read <address> --no-reader          PENDING ...           exit 3
  external-read <address> --reader-failed      PENDING ...           exit 3
  external-read <address> --keep-answer FILE   KEPT ...              exit 0

Every run journals ONE `external_read_routed` row through the host's journal write, whose existing
redaction (SPEC-0163 §4e) removes credential shapes from everything it stores — the kept answer
included. Nothing is written to stderr on these routes, so a refused address is never disclosed
there; an address that does not parse is not shown at all.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import sys
from urllib.parse import unquote_plus, urlsplit

from lib.journal import redact_secrets

EVENT_TYPE = "external_read_routed"

#: A query parameter NAMED for a secret: its value is masked in what is shown and the address is
#: refused. Over-matching is the safe direction — a refusal goes to the person, who decides.
SECRET_PARAM = re.compile(r"token|secret|passw|pwd|api[_-]?key|apikey|access[_-]?key|auth|session|"
                          r"signature|credential|private|^key$|^sig$", re.IGNORECASE)
#: A plain ASCII host name: dot-separated letter/digit/hyphen labels (urlsplit lowercases the host).
_PLAIN_HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")
#: IPv6 ranges that carry an IPv4 address inside them (IPv4-translated, NAT64, 6to4, Teredo,
#: IPv4-compatible): never public, whatever IPv4 address they embed (SPEC-1056 rule 2).
_IPV4_EMBEDDING = tuple(ipaddress.ip_network(n) for n in (
    "::ffff:0:0:0/96", "64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32", "::/96"))
_UNPARSABLE = "<address not shown: it does not parse>"
def _layers(text: str) -> list:
    """`text` and each successive percent-decoding of it, until it stops changing — so an encoded
    credential or key name is caught at whichever layer it surfaces (audit-post fp1:776693979fe9868d).
    Terminates: a decoding that changes the text shortens it or removes a `+`."""
    out = [text]
    while (nxt := unquote_plus(out[-1])) != out[-1]:
        out.append(nxt)
    return out


def _holds_shape(text: str) -> bool:
    return any(redact_secrets(t) != t for t in _layers(text))


def _secret_named(raw_key: str) -> bool:
    return any(SECRET_PARAM.search(t) for t in _layers(raw_key))


def _query_pairs(query: str) -> list:
    """The raw `key=value` pairs of a query, kept ENCODED (never decoded for display or rebuild)."""
    return [pair for pair in query.split("&") if pair]


def is_public(ip: str) -> bool:
    """True only for a global unicast address that embeds no IPv4 address."""
    a = ipaddress.ip_address(ip.split("%", 1)[0])
    if a.is_multicast:
        return False
    if a.version == 6 and (a.ipv4_mapped is not None or any(a in n for n in _IPV4_EMBEDDING)):
        return False
    return a.is_global


def _resolve(host: str, port: int) -> list:
    return [i[4][0] for i in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]


def check_address(url: str, resolve=None):
    """The reason `url` is refused, or None when the reader may open it (SPEC-1056 rule 2).

    `resolve(host, port) -> [ip, ...]` is injectable; the default asks the system resolver. May raise
    on input that does not parse — `safe_check` is the caller-facing form."""
    resolve = resolve or _resolve
    u = urlsplit(url)
    if u.scheme != "https" or not u.hostname:
        return "not an https address"
    host = u.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if (not u.netloc.isascii() or "%" in u.netloc
            or (literal is None and (not _PLAIN_HOST.fullmatch(host)
                                     or any(lab.startswith("xn--") for lab in host.split("."))))):
        return "the host is not a plain ASCII name or an address literal"
    if u.username is not None or u.password is not None or "@" in u.netloc:
        return "the address carries a user name or password"
    if _holds_shape(url):
        return "the address holds a credential shape"
    if any(_secret_named(pair.partition("=")[0]) for pair in _query_pairs(u.query)):
        return "the address carries a secret-named query parameter"
    port = u.port or 443
    try:
        ips = sorted(set(resolve(host, port)))
    except Exception:
        return "the host does not resolve"
    if not ips:
        return "the host does not resolve"
    bad = [ip for ip in ips if not is_public(ip)]
    if bad:
        return f"the host resolves to an address that is not public ({', '.join(bad)})"
    return None


def safe_check(url: str, resolve=None):
    try:
        return check_address(url, resolve)
    except Exception:
        return "the address does not parse"


def _printable(text: str) -> str:
    return "".join(ch if ch.isprintable() else "?" for ch in text)


def _scrub(text: str) -> str:
    """`text`, printable, holding no credential shape at ANY percent-decoding layer — the one display
    invariant. While a layer holds a shape, the SHALLOWEST such layer replaces the text under the
    kernel's redaction, so a shape is removed before a further decoding could break it and hide it from
    the redactor (`ghp_…%5F` decodes to `ghp_…_`, which no longer reads as a token). Terminates: each
    round removes a shape's characters and adds only redaction placeholders, which no decoding changes."""
    text = _printable(text)
    while (hit := next((t for t in _layers(text) if redact_secrets(t) != t), None)) is not None:
        text = _printable(redact_secrets(hit))
    return text


def shown_address(url: str) -> str:
    """`url` as shown to the person and recorded: user info and secret-named values masked, the
    fragment dropped, every other part kept in its own encoding — so an OK line shows the very address
    that was checked (audit-post fp1:9774ef1ced51cfe5). ONE invariant on top, `_scrub`: the result
    holds no credential shape at ANY percent-decoding layer — it changes only a refused address, since
    a shape refuses (fp1:776693979fe9868d, fp1:2d1ea0b1f67bfc3c). An address that does not parse is
    not shown."""
    try:
        u = urlsplit(url)
        netloc = u.netloc
        if "@" in netloc:
            netloc = "<user-info masked>@" + netloc.rsplit("@", 1)[1]
        parts = [f"{pair.partition('=')[0]}=<masked>" if _secret_named(pair.partition("=")[0]) else pair
                 for pair in _query_pairs(u.query)]
        out = f"{u.scheme}://{netloc}{u.path}" + (f"?{'&'.join(parts)}" if parts else "")
    except Exception:
        return _UNPARSABLE
    return _scrub(out)


def shown_name(target: str) -> str:
    """A target with no address (a local file or a copy): its base name under `_scrub`."""
    return _scrub(os.path.basename(target.rstrip("/")) or target)


def cmd_external_read(args, *, _append_event, _die) -> None:
    target = args.target
    answer_problem = None
    if args.keep_answer:
        try:
            with open(args.keep_answer, encoding="utf-8", errors="replace") as fh:
                answer = fh.read()
        except OSError as e:
            answer, answer_problem = "", f"cannot be read ({e.__class__.__name__})"
        if answer_problem is None and not answer.strip():
            answer_problem = "is empty"
        if answer_problem is None:
            shown = shown_address(target)
            _append_event(EVENT_TYPE, None, {"route": "kept", "address": shown, "answer": answer,
                                             "answer_chars": len(answer)})
            print(f"KEPT the reader's answer for {shown} in the journal "
                  f"({len(answer)} characters; credential shapes redacted on write)")
            return
    if answer_problem is not None:
        why, shown, route = (f"the answer file {shown_name(args.keep_answer)} {answer_problem} — nothing "
                             f"kept; save the reader's answer to a file and re-run with --keep-answer"), \
            shown_address(target), "pending"
    elif "://" not in target:
        why, shown = ("the text has no public address (a local file or a copy) — it is not read; "
                      "tell the person what is waiting"), shown_name(target)
        route = "pending"
    elif args.no_reader:
        why, shown, route = ("this AI tool provides no reader — the address is not read another way; "
                             "tell the person"), shown_address(target), "pending"
    elif args.reader_failed:
        why, shown, route = ("the reader failed — the address is not read another way; "
                             "tell the person"), shown_address(target), "pending"
    else:
        why, shown = safe_check(target), shown_address(target)
        route = "read" if why is None else "refused"
    data = {"route": route, "address": shown}
    if why is not None:
        data["reason"] = why
    _append_event(EVENT_TYPE, None, data)
    if route == "read":
        print(f"OK {shown} — read it only through the AI tool's reader")
        return
    if route == "refused":
        print(f"REFUSED {why} :: {shown}")
        print("  the person decides: open this address only after their yes for it, "
              "and then only through the AI tool's reader")
    else:
        print(f"PENDING {why} :: {shown}")
    sys.stdout.flush()
    sys.exit(3)   # REFUSED / PENDING: the person decides; never a crash code
