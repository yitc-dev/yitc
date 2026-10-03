#!/usr/bin/env python3
"""T-12489 — fold ONE archived provider transcript into a provider-neutral usage digest.

The raw archive (`.yitc/transcript-archive/`, lessons/provider-transcript-archive.md) grows ~1 GB/week
while its only long-lived consumers (token-rollup / task-scorecard) read a handful of numbers from it.
This leaf folds one session file into `<digest_root>/<archive_relpath>.json` carrying exactly those
numbers plus an integrity fingerprint of the source (contract: SPEC-0206) — NO prompts, responses or tool payloads. Shape per
the external consult decisions/transcript-archive-retention-2026-09-13-audit-adhoc.yaml §1. Pruning
and the consumer switch are separate cards; this module decides neither.

Contract:
- by_model totals count each provider message ONCE: the provider writes one row per content block, all
  carrying the same `message.id` and the same usage, so a repeated id replaces its earlier row's
  contribution (last row wins, in the totals and in its span) and a row without an id counts once
  (T-13268). Split into the same five token classes
  as `views.usage_token_classes` (the parse home — kept byte-identical and pinned by a parity test, so
  this module stays a stdlib leaf without a second parse RULE). Cost is NOT stored: it is derived at read
  time from the pricing table (SPEC-0135 source-fact-vs-derived-cost), so `cost_usd` is always null.
- task_spans: a span opens at a line carrying a governed `--task T-NNNN` argument and runs until a line
  naming a DIFFERENT task. Usage rows before the first such marker land in `unattributed` — ownership is
  never invented.
- A line that is not a JSON object is a LOUD failure (`DigestError`, naming path:line) and no digest is
  written — never a partial digest.
- The write is atomic: tmp file in the target directory, fsync, `os.replace`; any failure before the
  rename removes the tmp and leaves the target untouched.

CLI (the fold entry the refresh craft calls):
  python3 bin/lib/transcript_digest.py <archive_root> <digest_root> <transcript.jsonl>...
exits 0 when every file folded, 2 on the first DigestError (printed as `path:line: reason`).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

SCHEMA = "yitc-transcript-digest/1"
PARSER_VERSION = "2"   # T-13268: usage counted once per message id
TOKEN_CLASSES = ("input_tokens", "output_tokens", "cache_read_tokens",
                 "cache_write_5m_tokens", "cache_write_1h_tokens")
TASK_MARKER = re.compile(r"--task[ =](T-\d{4,6})\b")


class DigestError(Exception):
    """A transcript that cannot be folded faithfully. `line` is 1-based (0 = whole file)."""

    def __init__(self, path, line: int, reason: str):
        super().__init__(f"{path}:{line}: {reason}")
        self.path, self.line, self.reason = path, line, reason


def _token_classes(u: dict) -> dict:
    # Mirrors views.usage_token_classes exactly (parity pinned in tests/test_t12489_transcript_digest.py).
    cc = u.get("cache_creation")
    if isinstance(cc, dict):
        w5 = cc.get("ephemeral_5m_input_tokens") or 0
        w1 = cc.get("ephemeral_1h_input_tokens") or 0
    else:
        w5 = u.get("cache_creation_input_tokens") or 0
        w1 = 0
    return {
        "input_tokens": u.get("input_tokens") or 0,
        "output_tokens": u.get("output_tokens") or 0,
        "cache_read_tokens": u.get("cache_read_input_tokens") or 0,
        "cache_write_5m_tokens": w5,
        "cache_write_1h_tokens": w1,
    }


def _add(bucket: dict, model: str, tok: dict) -> None:
    t = bucket.setdefault(model, {**{k: 0 for k in TOKEN_CLASSES}, "total_tokens": 0, "cost_usd": None})
    for k in TOKEN_CLASSES:
        t[k] += tok[k]
    t["total_tokens"] += sum(tok[k] for k in TOKEN_CLASSES)


def _sub(bucket: dict, model: str, tok: dict) -> None:
    """Undo one `_add`; drops the model entry when that leaves it holding nothing. An entry already
    dropped can only have held an all-zero contribution, so there is nothing left to undo."""
    t = bucket.get(model)
    if t is None:
        return
    for k in TOKEN_CLASSES:
        t[k] -= tok[k]
    t["total_tokens"] -= sum(tok[k] for k in TOKEN_CLASSES)
    if not any(t[k] for k in TOKEN_CLASSES):
        del bucket[model]


def _task_markers(rec: dict) -> list:
    """Task refs from the governed invocations ONLY: a `tool_use` item's `input.command` string.
    Prompt, response and tool-result text never count — quoting `--task T-1234` in chat must not
    open a span (audit-pre RED, T-12489)."""
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    marks: list = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                inp = item.get("input")
                cmd = inp.get("command") if isinstance(inp, dict) else None
                if isinstance(cmd, str):
                    marks.extend(TASK_MARKER.findall(cmd))
    return marks


def canonical_hash(digest: dict) -> str:
    body = {k: v for k, v in digest.items() if k != "digest_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def fold(path, archive_root) -> dict:
    """Fold one transcript into its digest dict. Raises DigestError on any malformed line."""
    path, archive_root = Path(path), Path(archive_root)
    try:
        relpath = path.resolve().relative_to(archive_root.resolve()).as_posix()
    except ValueError:
        raise DigestError(path, 0, f"not under archive root {archive_root}") from None
    by_model: dict = {}
    unattributed: dict = {}
    spans: list = []
    current = None
    seen: dict = {}   # message id -> (model, tok, bucket) of the row currently counted for it
    ts_first = ts_last = None
    session_id = None
    sha = hashlib.sha256()
    size = line_count = 0
    fh = open(path, "rb")   # streamed: archive files run to hundreds of MB, never read whole
    for n, bline in enumerate(fh, 1):
        sha.update(bline)
        size += len(bline)
        line_count = n
        if not bline.strip():
            continue
        try:
            rec = json.loads(bline)
        except ValueError as exc:
            raise DigestError(path, n, f"malformed JSON ({exc.msg})") from None
        if not isinstance(rec, dict):
            raise DigestError(path, n, "line is not a JSON object")
        marks = _task_markers(rec)
        if marks and (current is None or current["task"] != marks[-1]):
            current = {"task": marks[-1], "first_line": n, "last_line": n, "by_model": {}}
            spans.append(current)
        if session_id is None and isinstance(rec.get("sessionId"), str):
            session_id = rec["sessionId"]
        ts = rec.get("timestamp") or rec.get("ts")
        if isinstance(ts, str):
            ts_first = ts if ts_first is None else min(ts_first, ts)
            ts_last = ts if ts_last is None else max(ts_last, ts)
        msg = rec.get("message")
        u = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(u, dict):
            continue
        model = msg.get("model") or "unknown"
        tok = _token_classes(u)
        mid = msg.get("id")
        if isinstance(mid, str) and mid in seen:   # another block of a counted message: last row wins
            pmodel, ptok, pbucket = seen[mid]
            _sub(by_model, pmodel, ptok)
            _sub(pbucket, pmodel, ptok)
        bucket = unattributed if current is None else current["by_model"]
        _add(by_model, model, tok)
        _add(bucket, model, tok)
        if current is not None:
            current["last_line"] = n
        if isinstance(mid, str):
            seen[mid] = (model, tok, bucket)
    fh.close()
    digest = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "session_id": session_id or path.stem,
        "archive_relpath": relpath,
        "source_sha256": sha.hexdigest(),
        "source_bytes": size,
        "source_lines": line_count,
        "ts_first": ts_first,
        "ts_last": ts_last,
        "by_model": by_model,
        "task_spans": spans,
        "unattributed": {"by_model": unattributed},
    }
    digest["digest_sha256"] = canonical_hash(digest)
    return digest


def digest_path(path, archive_root, digest_root) -> Path:
    rel = Path(path).resolve().relative_to(Path(archive_root).resolve())
    return Path(digest_root) / (rel.as_posix() + ".json")


def write_digest(path, archive_root, digest_root, *, _replace=os.replace) -> Path:
    """Fold + atomically write. A DigestError or any failure before the rename leaves no target file."""
    digest = fold(path, archive_root)
    target = digest_path(path, archive_root, digest_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(digest, fh, sort_keys=True, indent=1)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        _replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 3:
        print("usage: transcript_digest.py <archive_root> <digest_root> <transcript.jsonl>...",
              file=sys.stderr)
        return 2
    archive_root, digest_root, files = argv[0], argv[1], argv[2:]
    for f in files:
        try:
            print(write_digest(f, archive_root, digest_root))
        except DigestError as exc:
            print(f"transcript-digest: FAIL {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
