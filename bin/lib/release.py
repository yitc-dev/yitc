#!/usr/bin/env python3
"""T-12042 — the release PUBLISH seam: cut the kernel realm at a governed tag into a
manifest-bound, reproducible, host-clean snapshot.

WHAT THIS IS. `work publish --tag <tag> --dest <path>` renders the SPEC-0073 `kernel` realm at a
governed release tag (created by `work tag`, journaled `release_tagged`) into a destination checkout
as a single history-free commit, beside a release MANIFEST that names what was cut, from where, and
how to re-derive it. It is the delivery seam of the identity-agnostic cut SPEC-0074 already governs
— not a second cut. ENGINE-ONLY, exactly like `graph release-view` (SPEC-0074 rule 1): a consumer
PINS a release, it never mints one.

THE ONE INVARIANT WORTH STATING TWICE. Every published byte is read from the tag's PEELED COMMIT
(`git ls-tree` + `git show <sha>:<path>`), never from the live checkout. That is what makes
`source_ref` an honest field rather than a label: publishing an OLD tag from a MOVED checkout yields
that tag's bytes. It is also what makes the digest reproducible — the cut is a pure function of the
commit, so the same tag always folds to the same `tree_digest` on the workshop. Stated exactly (T-13354,
SPEC-0195 rule 5): the CUT is a function of the commit alone; the PUBLISHED bytes are a function of the
commit plus the workshop's two host-derived strip inputs — its home path (T-12024) and its project
registry (SPEC-0074 rule 4b) — so `release_published` journals the registry operands' fingerprint, never
their names, and a rebuild proves it supplied the same input by matching it.

WHAT IS DELIBERATELY NOT REGENERATED HERE. The generated `release-view/**` is a COMMITTED derived
artifact (SPEC-0074 rule 3) kept fresh at every landed commit by land's derived-regen and the
`graph conformance` drift check (rule 6). So publish READS it out of the commit rather than
re-running the generator — regenerating would read the live tree, which is precisely the fidelity
defect the invariant above exists to prevent.

THIS MODULE IS THE DEFINER of the shared release surfaces (the manifest schema, the cut, the digest,
the host-literal refusal). Later cards in the off-server release plan — sign/verify, the version
floor, update + override ledger, policy emission — EXTEND it and must not redefine the schema.
"""
from __future__ import annotations

import ast
import fnmatch
import functools
import hashlib
import io
import json
import os
import pwd
import re
import subprocess
import tokenize
from pathlib import Path
from typing import NamedTuple

from lib import engine_route
from lib import graph as graph_lib
from lib import host_paths
from lib import state

# The manifest is the SIGNATURE TARGET (SPEC-0195 rule 5): signing one small file covers the whole
# artifact through the digest it carries. The sign/verify card writes a detached signature over
# exactly this filename; the name is therefore a shared surface, not a local detail.
MANIFEST_FILENAME = "release-manifest.yaml"
# Bumped 1 -> 2 by T-12045: the manifest's FIELD SET changed (it now carries the SPEC-0195 rule-9
# compatibility declaration below). A schema version that does not move when the schema does is a
# label, not a version. The change is backward-compatible BY CONSTRUCTION rather than by promise: a
# v1 manifest simply carries no floor, and `check_version_floor` reports that as `not-declared`
# rather than as a failure — so every release published before this card still verifies and installs.
MANIFEST_SCHEMA_VERSION = 2

# The SPEC-0195 rule-9 COMPATIBILITY DECLARATION — the ONE field the content uses to name the engine
# version it requires. One declaration in the content, one check in the engine (`check_version_floor`);
# there is deliberately no second carrier and no config file for it.
REQUIRES_ENGINE_FIELD = "requires_engine"

# ─────────────────────────────────────────────────────────────────────────────────────────────────
# T-12043 — SIGN EVERY RELEASE, VERIFY BEFORE ANY WRITE (SPEC-0195 rules 6 + 7).
#
# Everything below EXTENDS the publish seam above; nothing here redefines the manifest schema or
# adds a second resolver. The one contract: no byte reaches a consumer-visible location until a
# signature chained to an OUT-OF-BAND anchor has been verified over bytes that hash to the digest
# the manifest names.
#
# WHY THE FOUR CONCERNS ARE ONE UNIT. sign / verify / trust-root / revocation prove one claim, and
# splitting them would ship an interim state where a release is signed and nothing checks it — a
# signature nobody verifies is not a gate (SPEC-0046 §A bidirectional cut).
#
# PROVIDER-NEUTRALITY (CHARTER §P4b). The normative rule text — SPEC-0195 rule 7, the published
# SECURITY.md, this module's public names — never names a signing tool. The concrete binding lives
# in `_ssh_keygen` and its four wrappers, which are the ONLY code in this repo that knows which
# program signs. Swapping the primitive is a change to those five functions.
# ─────────────────────────────────────────────────────────────────────────────────────────────────

SIGNATURE_FILENAME = MANIFEST_FILENAME + ".sig"
TRUST_ROOT_FILENAME = "trust-root.yaml"
REVOCATION_FILENAME = "revoked-keys.yaml"
# The revocation list carries its OWN detached signature, made by the ANCHOR key (audit-post
# finding 1). Without it a revoked key that controls the mirror simply deletes its own revocation
# row and re-signs everything with itself — the revocation list would be authenticated by exactly
# the key it exists to disqualify. See `verify_release` for why the ANCHOR and not any valid key.
REVOCATION_SIGNATURE_FILENAME = "revoked-keys.yaml.sig"
SECURITY_POLICY_FILENAME = "SECURITY.md"
RELEASE_NOTES_FILENAME = "RELEASE-NOTES.md"
TRUST_ROOT_SCHEMA_VERSION = 1

# The signature NAMESPACE and PRINCIPAL: a signature made for one namespace does not verify under
# another, so a maintainer key reused for some other purpose cannot be replayed as a release
# signature. One principal for the whole trust root — the identity that matters here is "a currently
# valid yitc release key", and per-key identities would only invite a trust decision per name.
SIGNING_NAMESPACE = "yitc-release"
RELEASE_PRINCIPAL = "yitc-release"

# The ENUMERATED verifying entrypoint inventory (SPEC-0195 rule 6). Every supported install/update
# entrypoint verifies BEFORE any write, and the set of them is PUBLISHED with the release so it can
# be driven against a tampered artifact — "an unenumerated path is a gap in the inventory, which is
# findable". This tuple is the single carrier: `build_release_notes` renders it and
# `parse_entrypoint_inventory` reads it back, so a later card adding an entrypoint adds ONE row here
# and the published notes follow (CHARTER §P5 — no second list to keep in sync).
# T-12177 — the clean-machine bootstrap order, named in the published notes so an adopter finds
# it without reverse-engineering the sequence from code (the T-12049 probe had to).
BOOTSTRAP_ORDER_DOC = "onboarding/bootstrap-order.md"

ENTRYPOINT_INVENTORY = (
    ("release verify",
     "yitc-v2 release verify <dest> --anchor <fingerprint>",
     "Verify a published release in place. Never writes into the release being verified, and "
     "never creates a journal — it is the gate itself. (On a checkout that already has a governed "
     "journal it appends one `release_verified` provenance row there, on refusal as well as on "
     "success; on a clean adopter machine there is no such journal and it writes nothing at all.)"),
    ("release install",
     "yitc-v2 release install <dest> --into <path> --anchor <fingerprint>",
     "Install a verified release into <path>. A refused install writes no RELEASE CONTENT into "
     "<path> — the gate reaches its verdict before <path> is opened, and a refused install never "
     "creates <path> or a journal in it. (If <path> is a governed checkout that ALREADY has a "
     "journal, one `release_installed` provenance row is appended there, on refusal as well as on "
     "success; the release being installed FROM is never written to.)"),
    # T-12388 — the rule-8 UPDATE entrypoint. It belongs in this inventory for the same reason the
    # two above do: rule 6 says an entrypoint that is not enumerated is a GAP, and rule 8's update is
    # an entrypoint that WRITES into a consumer tree. `--from-release` is shown because an update
    # WITHOUT it is a legal but weaker run (it can no longer tell a local edit from an out-of-date
    # file, so it reports every differing path and changes none) — an adopter reading the inventory
    # should see the argument that makes the merge decidable, not discover it from a refusal.
    ("release update",
     "yitc-v2 release update <dest> --into <path> --anchor <fingerprint> "
     "[--from-release <pinned-release-N tree>]",
     "Move an EXISTING install at <path> from release N to N+1. The gate reaches its verdict BEFORE "
     "<path> is opened, so a refused update writes NOTHING into <path> and leaves it byte-identical "
     "(SPEC-0195 rule 6, 'BEFORE any write', read literally). On the SUCCESS path only "
     "upstream-owned and template-owned paths are written: consumer-owned paths — the project's own "
     "files, which no release shipped — are reported and never written, and a template-owned file "
     "both sides moved is reported as a CONFLICT rather than guessed (rule 8). A path the PREVIOUS "
     "release shipped and this one no longer carries is REMOVED when the `--from-release` tree "
     "verifies against the same anchor and the installed copy is still that release's bytes; it is "
     "KEPT and named when it was changed locally or that tree does not verify, and with no "
     "`--from-release` nothing is removed. (If <path> already has a "
     "journal, one `release_updated` provenance row is appended there, on refusal as well as on "
     "success; the release being updated FROM is never written to.)"),
)

# The four ORDERED steps of the lost-key recovery procedure (SPEC-0195 rule 7, loss recovery). The
# published SECURITY.md renders them and `security_policy_missing_steps` reads them back, so AC6 is
# a subject-mutation differential rather than a substring habit: removing a step from the rendered
# policy makes the checker name it.
LOST_KEY_RECOVERY_STEPS = (
    ("revoke", "REVOKE the lost or compromised key: add its fingerprint to the revocation list "
               "published beside the trust root, with the date and the reason. From that moment "
               "every release signed by it is refused on the ordinary install path, and so is "
               "every key it admitted."),
    ("issue", "ISSUE a replacement key and admit it by a ROTATION TRANSITION signed by a key that "
              "is still valid — never by editing the trust root in place. If no valid key remains, "
              "a NEW out-of-band anchor fingerprint must be published on the independent channel "
              "and every adopter re-pins it by hand; that is the cost of losing the last key, and "
              "it is why the overlap window exists."),
    ("re-sign", "RE-SIGN the current release with the replacement key and re-publish the manifest "
                "signature. The artifact bytes and their digest do not change — only the signature "
                "over the manifest does."),
    ("re-pin", "CONSUMERS RE-PIN: each installation pulls the rotated trust root, which verifies "
               "against the anchor it already holds through the signed transition chain, and "
               "re-runs its ordinary verifying install path."),
)

# A host absolute path: `/home/<user>`. Kept semantically IDENTICAL to the pattern in
# tests/test_engine_code_host_path_guard.py (T-12024) — the two are pinned equal by
# tests/test_release_publish.py so the guard and the publish seam can never silently diverge. The
# SPEC-0074 placeholders (`<host-home>`, `<repo>`) do not match by construction: `<` is not in the
# user-segment class, so an abstracted mention is clean.
HOST_PATH_RE = re.compile(r"/home/[A-Za-z0-9._][A-Za-z0-9._\-]*")
# The same pattern over BYTES, for a published file that does not decode as UTF-8. DERIVED from the
# source pattern rather than re-spelled, so the two can never drift apart.
_HOST_PATH_BYTES_RE = re.compile(HOST_PATH_RE.pattern.encode("ascii"))

# The template-owned surface (SPEC-0195 rule 2): the SMALL, explicitly enumerated set a release
# scaffolds into a project and may re-scaffold on update. Enumerated, never implied — a consumer must
# be able to read what the release claims the right to re-write. The update card consumes this field
# from the manifest; it is stated here because the manifest is written here.
TEMPLATE_OWNED_SURFACE = (
    "tasks/_template.yaml",
    "decisions/_template.yaml",
    "errors/_template.yaml",
    "graph/born-ops.yaml",
    # T-12979: the scaffolds `scenario new` / `spec new` read through the kernel-content resolution.
    "scenarios/_template.md",
    "specs/_template.yaml",
)


def _docstring_node_ids(tree: ast.AST) -> set:
    """The `id()` of every Constant that is a DOCSTRING (module / class / function first statement).

    Mirrors the guard test's helper: a docstring that CITES a host path is provenance (an incident
    quoted verbatim), while the same literal in a live string constant is an inherited default.
    """
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def host_literal_violations(tree: dict) -> list:
    """The publish-seam half of the T-12024 engine-code host-path guard (SPEC-0074 rule 4, code side).

    Walks every `bin/**` Python source IN THE CUT and returns `"<path>:<line>: <literal>"` rows for a
    host absolute path appearing in a NON-docstring string constant. Fail-closed: a module that will
    not parse is REFUSED, never skipped — an unparseable module is exactly where a literal would hide.

    `tree` is the {rel_path: bytes} cut. No I/O — it judges the bytes it is given, which is why it
    can judge a COMMIT's content without checking that commit out.

    Computed once per process for one engine-code content (T-13476): the answer is a function of the
    (path, bytes) of the `_is_engine_code` entries and of nothing else, so it is kept under a digest
    of exactly those and every caller gets its own list.
    """
    digest = hashlib.sha256()
    for rel in sorted(tree):
        if _is_engine_code(rel):
            digest.update(rel.encode("utf-8", "surrogateescape") + b"\0"
                          + hashlib.sha256(tree[rel]).digest())
    key = digest.digest()
    if key in _HOST_LITERAL_VERDICTS:
        return list(_HOST_LITERAL_VERDICTS[key])
    hits = []
    for rel in sorted(tree):
        if not _is_engine_code(rel):
            continue
        src = tree[rel].decode("utf-8", errors="replace")
        try:
            parsed = ast.parse(src, filename=rel)
        except SyntaxError as exc:
            hits.append(f"{rel}: REFUSED — unparseable module ({exc.__class__.__name__}: {exc})")
            continue
        skip = _docstring_node_ids(parsed)
        for node in ast.walk(parsed):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                for m in HOST_PATH_RE.findall(node.value):
                    hits.append(f"{rel}:{getattr(node, 'lineno', '?')}: host path {m!r} in a string constant")
    _HOST_LITERAL_VERDICTS[key] = tuple(hits)
    return hits


# T-13476 — `host_literal_violations` answers, by engine-code digest. Process-local: nothing is
# written to disk and nothing outlives the process.
_HOST_LITERAL_VERDICTS: dict = {}


# Which published paths are CODE (the refusal arm) versus published TEXT (the strip arm). The split
# is not cosmetic — it is the whole of §4a's asymmetry:
#
#   CODE (`bin/**`) is REFUSED, never rewritten. A host path compiled into an engine default is a
#   DEFECT in the source: the value must be DERIVED (`host_paths.host_home()`), and silently
#   laundering it at publish time would ship a working release while leaving the defect in the
#   workshop, to be re-inherited by the next thing that reads that module.
#
#   Other published TEXT (patterns, specs, views, the catalog index) is STRIPPED through the SAME
#   identity-agnostic ruleset SPEC-0074 §5 already applies to the handbook docs. That ruleset exists
#   precisely to abstract dev provenance out of travelling prose; it simply had never been applied to
#   the non-handbook text that also travels — which is why 38 published `patterns/` files carried this
#   host's literals. Refusing them instead would make the verb unusable over the real corpus without
#   making a single one of those files more correct.
def _is_engine_code(rel: str) -> bool:
    """True for a published path whose host literals are a CODE defect (refuse) rather than prose."""
    return rel.startswith("bin/") and (rel.endswith(".py") or rel == "bin/yitc-v2")


# Machine-read files (T-12942). A YAML/JSON file a loader parses carries VALUES code compares — an
# audit adapter name, a path — and the prose strip rewrote them: v2.0.4 shipped bin/audit-config.yaml
# with `provider: <external-auditor>`, a name no adapter answers to. So such a file has only its
# full-line comments stripped; value lines travel byte-identical. That is not laundering in reverse:
# a host literal left in a VALUE is still refused by `published_host_literals`, the same fail-closed
# asymmetry CODE gets. Two exemptions keep the full strip: specs/*.yaml, the governed PROSE corpus
# SPEC-0074 §5 was written to strip, and graph/index.json, the index built from that prose (T-12944 —
# its values are spec text, so it is stripped like the specs it mirrors).
def _is_machine_read(rel: str) -> bool:
    """True for a published YAML/JSON file whose values a loader parses and code compares."""
    if rel.startswith("specs/") or rel == "graph/index.json":
        return False
    return rel.endswith((".json", ".yaml", ".yml"))


def _strip_comment_lines(text: str, identity: "ProjectIdentity | None" = None) -> str:
    """Strip only full-line `#` comments of a YAML text; every other line is returned unchanged."""
    return "".join(abstract_project_identity(graph_lib._release_view_strip(line), identity)
                   if line.lstrip().startswith("#") else line
                   for line in text.splitlines(keepends=True))


def _strip_spec_values(text: str, identity: "ProjectIdentity | None" = None) -> str:
    """Strip a spec's PROSE per string value, keeping the YAML parseable (T-12942). The whole-text strip
    cut ids out of `- D-0030` / `proposed_by: T-0527` lines and multi-line scalars, so 23 published
    specs no longer loaded. Here each string is stripped on its own; a list item or value the strip
    empties is dropped / nulled — the same content the whole-text strip removed, as valid YAML.

    One spec text is stripped once per process under one identity (T-13476): a publish, and every
    test that drives the publish seam in-process, strips the same spec corpus again and again, and
    the re-dump through the pure-Python emitter is the cost. The emitter itself is untouched."""
    return _once(_strip_spec_values_once, text, identity, str(host_paths.host_home()))


def _once(memoized, *key):
    """`memoized(*key)`, computed directly when the key cannot be hashed (T-13476). An identity built
    with list fields is still a valid `ProjectIdentity`; it gets the answer it always got, uncached."""
    try:
        hash(key)
    except TypeError:
        return memoized.__wrapped__(*key)
    return memoized(*key)


@functools.lru_cache(maxsize=None)
def _strip_spec_values_once(text: str, identity: "ProjectIdentity | None", host_home: str) -> str:
    """The strip behind `_strip_spec_values`, kept per distinct argument triple for the life of the
    process. `host_home` is part of the key because the §5 ruleset reads it (`_release_view_strip`
    abstracts THIS host's home), so an answer computed under one home is never served under another.
    The result is an immutable `str`, so a caller cannot alter what the next caller gets."""
    def walk(node):
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            items = [walk(v) for v in node]
            return [v for v in items if v is not None]
        if isinstance(node, str):
            s = graph_lib._release_view_strip(node).strip() if "\n" not in node \
                else graph_lib._release_view_strip(node)
            s = abstract_project_identity(s, identity)
            return s if s.strip() else None
        return node
    return state.dump(walk(state.load_str(text)))


def strip_published_text(tree: dict, identity: "ProjectIdentity | None" = None) -> dict:
    """Apply the SPEC-0074 §5 identity-agnostic strip to every published NON-CODE text file.

    With `identity` (T-13354, SPEC-0074 rule 4b) the publishing host's project names and domains are
    abstracted too: in every text the §5 strip reaches (prose, spec values, the comment lines of a
    machine-read file) and in the comments + docstrings of engine code (`_abstract_code_provenance`).
    A VALUE — an engine-code string constant, a machine-read value — is never rewritten; whatever
    survives is refused by `published_project_identity`. Without it the transform is unchanged.

    Returns a new {rel_path: bytes} tree. The handbook's released twins under `release-view/` were
    already stripped when they were generated, and re-running the ruleset over them is harmless: §5 is
    idempotent by contract (its fixpoint loop only ever shrinks the string), so a second pass is a
    no-op and the digest stays reproducible.

    A non-UTF-8 blob passes through UNTOUCHED — the strip is a text transform and rewriting bytes it
    cannot decode would corrupt the file. That is not passing it UNCHECKED: `published_host_literals`
    judges such a blob at the BYTE level and refuses it, so between them no published file is
    unexamined.
    """
    out = {}
    for rel, blob in tree.items():
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            out[rel] = blob
            continue
        if _is_engine_code(rel):
            new = _abstract_code_provenance(text, identity)
            out[rel] = blob if new == text else new.encode("utf-8")
            continue
        if _is_machine_read(rel):
            out[rel] = (text if rel.endswith(".json")
                        else _strip_comment_lines(text, identity)).encode("utf-8")
            continue
        if rel.startswith("specs/") and rel.endswith((".yaml", ".yml")):
            out[rel] = _strip_spec_values(text, identity).encode("utf-8")
            continue
        out[rel] = abstract_project_identity(graph_lib._release_view_strip(text), identity).encode("utf-8")
    return reword_unpublished_spec_refs(out)


# T-12966 (SPEC-0074 §5c) — the published cite FIXPOINT over patterns/ and spec bodies. T-12945 closed
# the init + seed surfaces; a published spec or pattern still named 39 specs the release lacks (the
# adopter read SPEC-0189 → SPEC-0151 and found no file). Placement stands (a workshop-only spec is not
# re-pinned for a cite), so the cite is REWORDED here, where the published set is finally known: an id
# is DROPPED only from the pure graph-edge fields (`cites` / `requires` lists, a `supersedes` /
# `superseded_by` scalar — SPEC-0030); everywhere else it is replaced IN PLACE by the placeholder, so
# no non-edge value is ever deleted. Idempotent: the placeholder carries no id.
UNPUBLISHED_SPEC_PLACEHOLDER = "<workshop-spec>"
_EDGE_LIST_KEYS = ("cites", "requires")
_EDGE_SCALAR_KEYS = ("supersedes", "superseded_by")
_SPEC_ID_TEXT_RE = re.compile(r"\bSPEC-\d{4}\b")


def reword_unpublished_spec_refs(tree: dict) -> dict:
    """Reword every SPEC id the tree does not carry out of published specs/*.yaml + patterns/*.md."""
    published = {m.group(1) for rel in tree if (m := _SPEC_FILE_RE.match(rel))}

    def sub(text: str) -> str:
        return _SPEC_ID_TEXT_RE.sub(
            lambda m: m.group(0) if m.group(0) in published else UNPUBLISHED_SPEC_PLACEHOLDER, text)

    def walk(node):
        if isinstance(node, dict):
            # A KEY is reworded too (a `- SPEC-0079: …` item parses as a one-key mapping). A reword that
            # would COLLIDE with a sibling key keeps the original — merging would delete a value — and
            # the id is then left for the `unresolved_spec_refs` refusal to name.
            out = {}
            for k, v in node.items():
                nk = sub(k) if isinstance(k, str) else k
                out[k if nk != k and (nk in node or nk in out) else nk] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return sub(node) if isinstance(node, str) else node

    def dangling(v) -> bool:
        return isinstance(v, str) and bool(_SPEC_ID_TEXT_RE.fullmatch(v.strip())) \
            and v.strip() not in published

    out = {}
    for rel, blob in tree.items():
        is_spec = rel.startswith("specs/") and rel.endswith((".yaml", ".yml"))
        if not (is_spec or (rel.startswith("patterns/") and rel.endswith(".md"))):
            out[rel] = blob
            continue
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            out[rel] = blob               # left for the `unresolved_spec_refs` refusal to name
            continue
        if not any(m not in published for m in _SPEC_ID_TEXT_RE.findall(text)):
            out[rel] = blob               # nothing dangles — keep the bytes exactly
            continue
        if not is_spec:
            out[rel] = sub(text).encode("utf-8")
            continue
        data = state.load_str(text)
        if isinstance(data, dict):
            for k in _EDGE_LIST_KEYS:
                if isinstance(data.get(k), list):
                    data[k] = [v for v in data[k] if not dangling(v)]
            for k in _EDGE_SCALAR_KEYS:
                if dangling(data.get(k)):
                    data[k] = None
        out[rel] = state.dump(walk(data)).encode("utf-8")
    return out


def published_host_literals(tree: dict) -> list:
    """Host literals surviving anywhere in the FINAL published tree — the AC2 whole-tree assertion.

    The publish seam checks this AFTER the strip, so it asserts the property of what actually ships
    rather than of what was cut. A survivor here means the strip did not reach a travelling surface,
    which is a real gap and is worth refusing over: unlike the pre-strip state, there is no remaining
    mechanism that would have cleaned it.
    """
    hits = []
    for rel in sorted(tree):
        if _is_engine_code(rel):
            continue                      # judged by `host_literal_violations`, with its own semantics
        blob = tree[rel]
        try:
            for m in sorted(set(HOST_PATH_RE.findall(blob.decode("utf-8")))):
                hits.append(f"{rel}: host path {m!r} survived the identity-agnostic strip")
        except UnicodeDecodeError:
            # A blob that does not decode cannot be STRIPPED safely (see `strip_published_text`), so it
            # is matched at the BYTE level and REFUSED instead of rewritten — there is no safe
            # transform for bytes whose structure we do not know. Skipping it would leave exactly one
            # unchecked way for a host literal to travel, which is the hole this assertion closes.
            for m in sorted(set(_HOST_PATH_BYTES_RE.findall(blob))):
                hits.append(f"{rel}: host path {m.decode('ascii', 'replace')!r} in a NON-UTF-8 "
                            "published file — it cannot be stripped safely, so it is REFUSED")
    return hits


# A bare unix ACCOUNT NAME is a HOST LITERAL too (T-12354). SPEC-0195 rule 1a recorded the bound this
# closes: the host-path guard above matches `/home/<user>` only, so the SAME collaborator's name written
# bare in prose — "<name> cannot traverse", "e.g. <name>" in a help string — travelled unexamined, and the
# mirror is being opened to the PUBLIC. To a stranger it is a named individual's identifier; to an adopter
# it means nothing, because the prose is about A PROVISIONED COLLABORATOR, not about that person.
#
# TWO properties decide the shape of this guard, and both are load-bearing:
#
#   DERIVED FROM THE HOST, NEVER WRITTEN DOWN. A denylist of names spelled into this module would be
#   published BY the release it guards — the guard would leak exactly what it exists to catch. So the set
#   is read from the passwd database at publish time and never reaches the tree.
#
#   REFUSAL-ONLY, NEVER A REWRITE. This is the one place the account-name rule is deliberately NARROWER
#   than the host-path rule beside it. A host-derived STRIP would make the published BYTES a function of
#   the machine that ran `work publish` rather than of the tagged commit, which is precisely what rule 5's
#   reproducible digest forbids: publisher A, who has a `foo` account, would emit different bytes from
#   publisher B, who does not. A REFUSAL cannot do that — it only ever fails closed, so two publishers of
#   one tag either emit IDENTICAL bytes or one of them stops. The content fix therefore lives in the
#   SOURCES (scrubbed to role placeholders under T-12354) and this guard is the tripwire that keeps them
#   scrubbed, judging prose and engine code alike (a plain text scan, so comments and docstrings are in
#   scope — unlike the AST-based `host_literal_violations`, which by design lets a docstring CITATION of a
#   path stand as provenance; a person's name is not made publishable by sitting in a comment).
_ACCOUNT_NAME_MIN_LEN = 3
_SYSTEM_UID_FLOOR = 1000
_NOLOGIN_SHELLS = ("false", "nologin", "sync", "shutdown", "halt")


def local_account_names(*, _getpwall=None, _owner_uid=None) -> tuple:
    """The bare account names of the humans provisioned on THIS host: `(names, excluded)`.

    `names` is what a published tree may not contain. `excluded` is `[(name, reason)]` — every account
    this guard deliberately does NOT judge, carried out to the caller rather than dropped, because a
    silent exclusion is how a guarantee quietly narrows. Two exclusions, both DERIVED:

      * the account that OWNS the engine checkout — the workshop's own operating account, not a
        collaborator. Its home PATH is already abstracted by the SPEC-0074 §5 strip, and its bare name
        on this host is the ordinary word `dev`, occurring hundreds of times as vocabulary; refusing it
        would make the verb unusable without making one published file more correct. Where a workshop's
        publishing account IS a person's name, that name must be abstracted by the same route as any
        other collaborator's — this exclusion is about the SERVICE account, not about being the owner;
      * a name shorter than `_ACCOUNT_NAME_MIN_LEN` — a one- or two-character token cannot be matched on
        word boundaries without firing across ordinary prose, and it identifies nobody.

    Both are PINNED by tests/test_publish_surface_boundary.py at their measured counts, so an excluded
    class can shrink but never grow unseen, and a NEW short account name reddens the suite instead of
    silently widening what may travel.
    """
    getpwall = _getpwall or pwd.getpwall
    owner_uid = _owner_uid if _owner_uid is not None else Path(__file__).resolve().stat().st_uid
    names, excluded = [], []
    for entry in getpwall():
        uid = entry.pw_uid
        if uid < _SYSTEM_UID_FLOOR or uid >= 65534:
            continue                       # system + the `nobody` sentinel: not people
        if (entry.pw_shell or "").rsplit("/", 1)[-1] in _NOLOGIN_SHELLS:
            continue                       # a service account with no login shell
        name = entry.pw_name
        if uid == owner_uid:
            excluded.append((name, "owns the engine checkout — the workshop's own operating account"))
        elif len(name) < _ACCOUNT_NAME_MIN_LEN:
            excluded.append((name, f"shorter than {_ACCOUNT_NAME_MIN_LEN} characters — not identifying, "
                                   "and unmatchable without firing across ordinary prose"))
        else:
            names.append(name)
    return tuple(sorted(set(names))), tuple(sorted(set(excluded)))


def account_name_re(names) -> "re.Pattern | None":
    """Word-boundary matcher over `names`, or None when there is nothing to match."""
    if not names:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(names)) + r")\b")


def published_account_names(tree: dict, names) -> list:
    """Bare account names occurring ANYWHERE in the published tree — the refusal rows.

    Judges every path, engine code included (see the section header for why the code/prose asymmetry
    that governs host PATHS does not extend here). A blob that does not decode as UTF-8 is matched at the
    byte level for the same reason `published_host_literals` does: it is the one surface no text
    transform could clean, so leaving it unexamined would be the whole hole.
    """
    rx = account_name_re(names)
    if rx is None:
        return []
    rx_bytes = re.compile(rx.pattern.encode("utf-8"))
    hits = []
    for rel in sorted(tree):
        blob = tree[rel]
        try:
            found = sorted(set(rx.findall(blob.decode("utf-8"))))
        except UnicodeDecodeError:
            found = sorted({m.decode("utf-8", "replace") for m in rx_bytes.findall(blob)})
        for name in found:
            hits.append(f"{rel}: bare account name {name!r} is published")
    return hits


# PROJECT IDENTITY is dev provenance too (T-13354, SPEC-0074 rule 4b). The projects this host runs — their
# registry keys, their checkout directory names, their domains — were cited all over the travelling corpus
# as the source of an incident or a measurement, and every release carried them to a public mirror. To an
# adopter they mean nothing; to a stranger they map what runs where. The account-name arm above settles the
# two questions this arm shares, and it answers them the same way:
#
#   DERIVED FROM THE HOST, NEVER WRITTEN DOWN. The operands are read from the host project registry at
#   publish time — only its `projects:` map — and never reach the tree. A list in this module would be
#   published BY the release it guards.
#
#   VALUES ARE REFUSED; PROVENANCE IS ABSTRACTED. This is where the arm differs from the account arm, on
#   SPEC-0074 rule 4a's own asymmetry. A project name in an engine-code string VALUE (a help line, a
#   message, a template) or in a machine-read value is REFUSED — rewritten at the source, never laundered.
#   But the corpus cites projects as PROVENANCE about two thousand times (comments, docstrings, pattern
#   prose), and that record is worth keeping in the workshop: a source scrub would destroy it without
#   making one published file more correct. So provenance positions are ABSTRACTED at publish, exactly as
#   rule 5(a) abstracts a host path off an operand read from this host (T-12024). The cost is stated in
#   SPEC-0195 rule 5: the published bytes are a function of the tag AND the workshop's registry, so the
#   operand fingerprint is journaled with every publish (never the names) and a rebuild can prove it
#   supplied the same input.
PROJECT_PLACEHOLDER = "<project>"
PROJECT_DOMAIN_PLACEHOLDER = "<project-domain>"
# Ordinary words only — never a project's name. A registry key made ENTIRELY of these (`website`,
# `server-bot`, `dev-dashboard`) is used in running prose as the word it is, and abstracting every
# "website" in the corpus would damage the prose while identifying nobody. Its DOMAINS are still abstracted.
_GENERIC_NAME_WORDS = frozenset({"website", "server", "app", "bot", "dev", "dashboard", "n8n"})
_PLACEHOLDER_SPLIT_RE = re.compile(r"(<project(?:-domain)?>)")
_PLACEHOLDER_BYTES_RE = re.compile(_PLACEHOLDER_SPLIT_RE.pattern.encode("ascii"))
_CODING_COOKIE_RE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")   # PEP 263


class ProjectIdentity(NamedTuple):
    """The publish-time operands: `names` / `domains` to abstract and refuse, and `excluded` —
    `[(name, reason)]` for every registry name deliberately NOT judged, carried out rather than dropped."""
    names: tuple
    domains: tuple
    excluded: tuple


def project_identity_operands(registry_path, engine_repo) -> ProjectIdentity:
    """The project identity of THIS host, read from the registry's `projects:` map ONLY.

    Each entry contributes its key, the basename of its `path` (as registered, and as resolved), and
    every `domains:` value. Two
    exclusions, both reported: the entry whose resolved path is the engine repository (the methodology's
    own name travels by definition), and a GENERIC name — every `-` part an ordinary word. Raises
    ValueError when the registry is ABSENT, unreadable or carries no `projects:` mapping: a missing
    inventory must never read as "nothing to protect". A readable `projects: {}` is the one input that
    judges nothing, and it does so explicitly.
    """
    path = Path(registry_path)
    if not path.is_file():
        raise ValueError(f"no project registry at {path}")
    try:
        data = state.load_str(path.read_text(encoding="utf-8"))
    except Exception as exc:                       # noqa: BLE001 — any read/parse fault refuses
        raise ValueError(f"the project registry at {path} does not parse ({exc.__class__.__name__})")
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        raise ValueError(f"the project registry at {path} carries no `projects:` mapping")
    engine = Path(engine_repo).resolve()
    names, domains, excluded = set(), set(), set()
    for key, meta in projects.items():
        meta = meta if isinstance(meta, dict) else {}
        raw = str(meta.get("path") or "").strip()
        resolved = (Path(raw) if Path(raw).is_absolute() else path.parent / raw).resolve() if raw else None
        # The basename AS REGISTERED and the one it resolves to: a symlinked path names the project by
        # its registered spelling, and resolving first would drop exactly that name (audit-post fp2).
        candidates = {str(key)} | ({Path(raw).name, resolved.name} if resolved is not None else set())
        for d in meta.get("domains") or []:
            if isinstance(d, str) and d.strip():
                domains.add(d.strip().lower())
        for name in sorted(c for c in candidates if c):
            if resolved is not None and resolved == engine:
                excluded.add((name, "the engine's own entry — the methodology's name travels by definition"))
            elif all(part in _GENERIC_NAME_WORDS for part in name.lower().split("-")):
                excluded.add((name, "generic — every part an ordinary word, used in prose as that word"))
            else:
                names.add(name.lower())
    return ProjectIdentity(tuple(sorted(names)), tuple(sorted(domains)), tuple(sorted(excluded)))


def project_identity_fingerprint(identity: ProjectIdentity) -> str:
    """sha256 over the sorted operands — what a rebuild compares to prove the same registry input.
    Journaled, never published, and never the names themselves."""
    blob = json.dumps({"names": list(identity.names), "domains": list(identity.domains)}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _project_identity_res(identity: ProjectIdentity, *, binary: bool = False):
    """`(domain_rx, name_rx)` — either None when it has no operand. A domain matches with any subdomain
    labels in front of it, wildcard (`*.`) and service (`_acme-challenge.`) labels included, and after a
    leading dot (`.example.org` cookie/vhost form) — audit-post fp1; a name matches wherever no LETTER
    flanks it (T-13382): `_`, a digit, `-` and `/` are separators, so `name_x`, `name2`, `x-name` and
    `x/name2` all name the project — v2.2.0 shipped two names inside such compound tokens because the
    whole-token boundary treated `_` and digits as part of the word. A domain keeps its DNS-label
    boundary: `x-example.org` is a different domain, not a mention of `example.org`.
    Both case-insensitive, longest operand first. `binary=True` compiles the same patterns over the
    UTF-8 BYTES of the operands, for a blob no text decoding may be trusted with (fp3)."""
    def alt(ops):
        return "|".join(re.escape(o) for o in sorted(ops, key=lambda o: (-len(o), o)))

    def compile_(pattern):
        return re.compile(pattern.encode("utf-8") if binary else pattern, re.I)
    # `*` is a LABEL character (consumed by the prefix group) but never a left boundary: a host glob
    # `*shopfront.example` still names the domain (audit-post pass-2 fp1:92ab443b0257b5ff).
    domain_rx = compile_(r"(?<![A-Za-z0-9_-])(?:[A-Za-z0-9_*-]+\.)*(?:" + alt(identity.domains)
                         + r")(?![A-Za-z0-9_-])(?!\.[A-Za-z0-9])") if identity.domains else None
    name_rx = compile_(r"(?<![A-Za-z])(?:" + alt(identity.names) + r")(?![A-Za-z])") \
        if identity.names else None
    return domain_rx, name_rx


def abstract_project_identity(text: str, identity: "ProjectIdentity | None") -> str:
    """Abstract every project domain to `<project-domain>`, then every name to `<project>`. Pure and
    idempotent: only the two canonical placeholders are protected, so a name inside any other `<...>`
    is still abstracted."""
    if not identity:
        return text
    domain_rx, name_rx = _project_identity_res(identity)
    if domain_rx is None and name_rx is None:
        return text
    for rx, placeholder in ((domain_rx, PROJECT_DOMAIN_PLACEHOLDER), (name_rx, PROJECT_PLACEHOLDER)):
        if rx is None:
            continue
        # Re-split per pass, so a placeholder the DOMAIN pass just wrote is protected from the NAME pass
        # too (a project named `project` must not turn `<project-domain>` into `<<project>-domain>`, fp6).
        parts = _PLACEHOLDER_SPLIT_RE.split(text)
        parts[::2] = [rx.sub(placeholder, seg) for seg in parts[::2]]   # odd indexes = placeholders
        text = "".join(parts)
    return text


def _code_shape(parsed: ast.AST) -> str:
    """The module's AST with every docstring blanked — what must not move when provenance is rewritten."""
    docstrings = _docstring_node_ids(parsed)
    for node in ast.walk(parsed):
        if id(node) in docstrings:
            node.value = ""
    return ast.dump(parsed, include_attributes=False)


def _abstract_code_provenance(src: str, identity: "ProjectIdentity | None") -> str:
    """Abstract project identity in an engine module's COMMENTS and DOCSTRINGS only — its provenance
    positions (SPEC-0074 rule 4a). Every other byte is untouched, and the rewrite is KEPT only when the
    result parses to the same AST modulo docstrings; otherwise `src` comes back unchanged and the
    whole-tree refusal names what survived. A string VALUE is never rewritten here: it is refused.

    Pure in (src, identity), so one module text is judged once per process under one identity
    (T-13476); the result is an immutable `str`."""
    return _once(_abstract_code_provenance_once, src, identity)


@functools.lru_cache(maxsize=None)
def _abstract_code_provenance_once(src: str, identity: "ProjectIdentity | None") -> str:
    """The rewrite behind `_abstract_code_provenance`, kept per distinct (src, identity)."""
    if not identity or abstract_project_identity(src, identity) == src:
        return src
    try:
        parsed = ast.parse(src)
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (SyntaxError, ValueError, tokenize.TokenError):
        return src
    lines = src.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))

    def char_offset(lineno: int, col: int, *, byte_col: bool = False) -> int:
        if byte_col:                               # an AST col_offset counts UTF-8 bytes, not chars
            col = len(lines[lineno - 1].encode("utf-8")[:col].decode("utf-8", errors="ignore"))
        return starts[lineno - 1] + col

    docstrings = _docstring_node_ids(parsed)
    doc_spans = [(char_offset(node.lineno, node.col_offset, byte_col=True),
                  char_offset(node.end_lineno, node.end_col_offset, byte_col=True))
                 for node in ast.walk(parsed) if id(node) in docstrings]
    spans = list(doc_spans)
    for t in tokens:
        if t.type != tokenize.COMMENT:
            continue
        # A shebang and a PEP 263 coding cookie are not provenance: the OS and the parser READ them, so
        # they are values — never rewritten, refused if they name a project (audit-post fp4).
        if (t.start[0] == 1 and t.string.startswith("#!")) or \
                (t.start[0] <= 2 and _CODING_COOKIE_RE.match(t.string)):
            continue
        a, b = char_offset(*t.start), char_offset(*t.end)
        # A comment INSIDE an implicitly concatenated docstring is already covered by that docstring's
        # span; rewriting it twice would duplicate text (audit-post fp5).
        if not any(da <= a and b <= db for da, db in doc_spans):
            spans.append((a, b))
    out, pos = [], 0
    for a, b in sorted(spans):
        out.append(src[pos:a])
        out.append(abstract_project_identity(src[a:b], identity))
        pos = b
    out.append(src[pos:])
    new = "".join(out)
    try:
        if _code_shape(ast.parse(new)) != _code_shape(ast.parse(src)):
            return src
    except SyntaxError:
        return src
    return new


def published_project_identity(tree: dict, identity: "ProjectIdentity | None") -> list:
    """Project names / domains surviving ANYWHERE in the final published tree — the refusal rows.

    Each row names the file, the line and the token. Judges every path — engine code included, where a
    survivor is a VALUE the provenance pass did not (and must not) rewrite — plus any path that itself
    names a project. A blob that does not decode as UTF-8 is matched at the byte level, as the sibling
    arms do: it is the one surface no text transform could clean."""
    if not identity:
        return []
    hits = []
    for rel in sorted(tree):
        if abstract_project_identity(rel, identity) != rel:
            hits.append(f"{rel}: the published PATH names a project")
        blob = tree[rel]
        try:
            text = blob.decode("utf-8")
            res, blank, newline = _project_identity_res(identity), " ", "\n"
        except UnicodeDecodeError:
            # Matched on the operands' own UTF-8 BYTES — a text decoding of an undecodable blob would
            # turn a non-ASCII operand into different characters and miss it (audit-post fp3).
            text = blob
            res, blank, newline = _project_identity_res(identity, binary=True), b" ", b"\n"
        # The canonical placeholders are masked in BOTH forms, so an undecodable blob keeps the same
        # placeholder protection a text blob has (audit-post pass-2 fp1:9337438976b6d910).
        protected = (_PLACEHOLDER_SPLIT_RE if isinstance(text, str) else _PLACEHOLDER_BYTES_RE).sub(
            lambda m: blank * len(m.group(0)), text)
        for kind, rx in zip(("domain", "name"), res):
            if rx is None:
                continue
            for m in rx.finditer(protected):
                line = protected.count(newline, 0, m.start()) + 1
                token = m.group(0) if isinstance(m.group(0), str) else m.group(0).decode("utf-8", "replace")
                hits.append(f"{rel}:{line}: project {kind} {token!r} is published")
                protected = protected[:m.start()] + blank * len(m.group(0)) + protected[m.end():]
    return hits


# T-13382 (SPEC-0074 rule 4b, metadata) — the publish COMMIT and TAG travel with the tree, so their
# identity and messages are published surfaces too. They were judged by nobody: `git commit` took the
# host's global identity, whose email sat at a registered production domain, and only a hand
# re-commit kept it off the v2.2.0 mirror. So the release is authored by ONE fixed neutral identity,
# never the host's, and the metadata is judged by the same matcher as the tree before anything is
# written. `core.hooksPath=/dev/null` keeps a host hook (prepare-commit-msg included) from rewriting
# the checked message, and the signing switches keep an inherited `gpgSign` from appending a signature
# to it (the release is signed by its manifest signature, SPEC-0195 rule 6, not by git); the read-back
# after writing is the belt for anything else that could.
RELEASE_IDENTITY = ("yitc-release", "yitc-release@users.noreply.github.com")
_PUBLISH_GIT_CONFIG = ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false",
                       "-c", "tag.gpgSign=false", "-c", "tag.forceSignAnnotated=false"]


def publish_metadata(tag: str, digest: str) -> dict:
    """The commit and tag metadata a publish of `tag` writes — composed once, judged, then written."""
    name, email = RELEASE_IDENTITY
    return {"author": f"{name} <{email}>", "committer": f"{name} <{email}>", "tagger": f"{name} <{email}>",
            "commit message": f"release {tag} ({digest[:12]})", "tag": tag, "tag message": f"Release {tag}"}


def published_metadata_identity(metadata: dict, identity: "ProjectIdentity | None") -> list:
    """Registered names / domains carried by the publish metadata — `"<field>: project <kind> '<token>'"`
    rows, judged by the same rule-4b matcher as the tree."""
    if not identity:
        return []
    hits = []
    for field in sorted(metadata):
        for kind, rx in zip(("domain", "name"), _project_identity_res(identity)):
            if rx is not None:
                hits.extend(f"{field}: project {kind} {m.group(0)!r}" for m in rx.finditer(metadata[field]))
    return hits


def _publish_git_env(metadata: dict) -> dict:
    """The process environment for the dest commit and tag: the checked identity, overriding the host's."""
    name, email = RELEASE_IDENTITY
    return dict(os.environ, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email,
                GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email)


def written_metadata_mismatches(dest, metadata: dict, identity: "ProjectIdentity | None", *, _run_git_cap,
                                tagged: bool = True) -> list:
    """Read the dest's HEAD commit (and the annotated tag) back and compare them with the CHECKED
    metadata: what was written must be what was judged. Returns the mismatching fields, empty when clean."""
    objects = [("commit", "HEAD", ("author", "committer"), "commit message")]
    if tagged:
        objects.append(("tag", metadata["tag"], ("tagger",), "tag message"))
    out = []
    for kind, ref, people, message_field in objects:
        rp = _run_git_cap(["cat-file", kind, ref], Path(dest))
        if rp.returncode != 0:
            out.append(f"{kind} {ref}: unreadable after writing")
            continue
        header, _, message = rp.stdout.partition("\n\n")
        lines = {ln.split(" ", 1)[0]: ln.split(" ", 1)[1] for ln in header.splitlines() if " " in ln}
        for person in people:
            written = re.sub(r" \d+ [+-]\d{4}$", "", lines.get(person, ""))
            if written != metadata[person]:
                out.append(f"{kind} {person}: written {written!r}, checked {metadata[person]!r}")
        if message.strip() != metadata[message_field]:
            out.append(f"{kind} message: written {message.strip()!r}, checked {metadata[message_field]!r}")
        out.extend(f"{kind} object: {hit}" for hit in published_metadata_identity({"raw": rp.stdout}, identity))
    return out


def _git_out(_run_git_cap, main: Path, args: list, *, binary: bool = False):
    """`git -C main <args>` returning stdout, or None on a non-zero exit."""
    rp = _run_git_cap(args, main)
    if rp.returncode != 0:
        return None
    return rp.stdout


def _git_blob(main: Path, source_sha: str, rel: str) -> "bytes | None":
    """Read one path's content at a commit as RAW BYTES, or None if it cannot be read.

    Deliberately NOT routed through the injected `_run_git_cap`: that seam captures TEXT, so a
    published file that is not valid UTF-8 raises on decode before publish can judge it — which turned
    a binary in the kernel realm into a crash rather than a verdict. The other git calls here stay on
    the injected seam, where text is right and the seam's rebind/monkeypatch behaviour matters; only
    the CONTENT read needs bytes.
    """
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    rp = subprocess.run(["git", "-C", str(main), "cat-file", "blob", f"{source_sha}:{rel}"],
                        capture_output=True, env=_git_env._git_child_env())
    return rp.stdout if rp.returncode == 0 else None


def peel_tag(tag: str, *, _run_git_cap, main: Path):
    """Resolve a release TAG to its peeled COMMIT sha, or None when the tag does not resolve.

    `<tag>^{commit}` peels an annotated tag object through to its commit — the same resolution shape
    `work tag` creates and the SPEC-0172/SPEC-0122 pinned-release resolver uses (an exact, immutable
    ref; a moving ref is not what a release names).
    """
    out = _git_out(_run_git_cap, main, ["rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}"])
    return (out or "").strip() or None


def _spec_part_base(rel: str) -> "str | None":
    """The base spec's rel path when `rel` is a `specs/` continuation part, else None — the one
    base↔part name rule (`state._SPEC_PART_RE` + `state.is_spec_part`, what `state.spec_part_paths`
    walks on disk) applied to a commit's path list, which that disk walker cannot read."""
    if not rel.startswith("specs/") or not state.is_spec_part(rel):
        return None
    return f"specs/{state._SPEC_PART_RE.match(Path(rel).name).group(1)}.yaml"


def cut_release_tree(source_sha: str, *, _run_git_cap, main: Path, _resolve_placement,
                     raw_handbook_docs, _die, paths_under: str = "") -> tuple:
    """The kernel-realm slice at `source_sha`, as `(tree, exec_paths)`.

    `tree` is the ordered {rel_path: bytes} dict; `exec_paths` is the SIBLING set of those same
    rel_paths whose mode at the source commit is `100755` (T-12172). The mode travels BESIDE the
    bytes rather than inside them because git has exactly two blob modes, so a set of the
    executable paths carries the whole signal without changing the dict's value type — which every
    later transform in the publish seam (contribution surfaces, the strip, the trust surfaces, the
    digest) consumes unchanged. The DIGEST STAYS CONTENT-ONLY: `tree_digest` folds
    (rel_path, sha256(bytes)) pairs and never reads a mode, so preserving the executable bit
    cannot move the digest of an already-published release.

    EVERY BYTE COMES FROM THE COMMIT. The path+mode list is `git ls-tree -r <sha>` and each
    file's content is `git show <sha>:<path>`; the live checkout is never read. Three filters, each
    reusing an EXISTING carrier rather than introducing a second truth (CHARTER §P1 F1):

      1. REALM — keep a path only if `_resolve_placement` resolves it `kernel` (for a spec or a
         pattern, with its own `travels:` marker — T-13353). The v2-self realm
         (tasks/, decisions/, events.jsonl, plans/, ideas/, tests/, graph/, .yitc/ …) is therefore
         excluded BY CONSTRUCTION, not by a deny-list somebody has to remember to extend.
      2. SPEC STATUS — a spec file is kept only if its content AT THIS COMMIT says `status: active`.
         This is the `_release_view_spec_ids()` predicate (`status == active` ∧ placement == kernel,
         SPEC-0073 rule 8) applied to commit content instead of disk: the kernel's own evolution
         history — superseded / withdrawn / retired / rejected / draft — never travels.
         A SPEC-0120 §3 CONTINUATION PART (`SPEC-…partN.yaml`) is not a spec of its own — it carries
         no status and no `travels:` — so it is never judged on its own content: it travels exactly
         when its BASE travels (T-13505), linked by the one name rule `state.spec_part_paths` walks.
      3. RAW HANDBOOK SOURCE — every doc in `raw_handbook_docs` is dropped. Those files resolve
         `kernel` by class default, but a release carries the handbook RELEASE VIEW, never the
         workshop-entangled source (SPEC-0195 rule 1); publishing both would ship the stripped twin beside
         the thing it was stripped from. The names come from the single `_release_view_docs()` carrier,
         so a doc added to the handbook is excluded here and published as its release-view twin with
         no second list to keep in sync (CHARTER §P5).

    The generated `release-view/**` needs no special case: it is kernel-realm and COMMITTED
    (SPEC-0074 rule 3), so it rides filter 1 straight out of the commit — fresh by the land-regen +
    conformance drift check the spec's rule 6 already guarantees.

    `paths_under` (T-13629) narrows the cut to one directory prefix — the SAME three filters, applied
    to fewer paths — so a caller that needs only the travelling specs at a commit does not read every
    other file of it.
    """
    # `ls-tree -r` (not `--name-only`) so the MODE column comes back with the path: `<mode> <type>
    # <sha>\t<path>`. One listing, one truth — the mode is read from the same commit read the bytes
    # come from, never from the live checkout (the module's one invariant).
    listing = _git_out(_run_git_cap, main, ["ls-tree", "-r", source_sha])
    if listing is None:
        return {}, set()
    excluded_docs = set(raw_handbook_docs)
    tree = {}
    modes = {}
    for line in listing.splitlines():
        if "\t" not in line:
            continue
        meta, _, path = line.partition("\t")
        rel = path.strip()
        if rel:
            modes[rel] = meta.split()[0]
    exec_paths = set()
    parts = {}
    for rel in sorted(modes):
        if paths_under and not rel.startswith(paths_under):
            continue
        if rel in excluded_docs:
            continue
        if _resolve_placement(rel) != "kernel":
            continue
        blob = _git_blob(main, source_sha, rel)
        if blob is None:
            continue
        # T-13505 — a continuation part has no status to judge; its base decides (after the loop).
        if _spec_part_base(rel):
            parts[rel] = blob
            continue
        # A template-owned scaffold is not a spec: its illustrative `status: proposed` must not strip
        # it (T-12979 — `spec new` on an install found no specs/_template.yaml).
        if rel.startswith("specs/") and rel.endswith(".yaml") and rel not in TEMPLATE_OWNED_SURFACE:
            try:
                data = state.load_str(blob.decode("utf-8")) or {}
            except Exception as exc:
                # FAIL-CLOSED: a spec that will not parse cannot be judged active-or-not, and an
                # unjudgeable spec must never travel on a guess (SPEC-0073 rule 8 is a hard filter).
                _die(f"work publish: specs/{Path(rel).name} at {source_sha[:12]} does not parse "
                     f"({exc.__class__.__name__}) — refusing to judge its status. Fix the spec at "
                     "that commit and re-tag.")
                return {}, set()
            if data.get("status") != "active":
                continue
            # A per-item `travels:` marker may move an exception-capable spec out of the kernel realm.
            if _resolve_placement(rel, data.get("travels")) != "kernel":
                continue
        # T-13353 — a pattern is exception-capable too (SPEC-0073 rule 2): its frontmatter `travels:`
        # marker keeps a workshop-only note home, read through the ONE frontmatter parser.
        elif rel.startswith("patterns/") and rel.endswith(".md"):
            try:
                text = blob.decode("utf-8")
                fm, body = state.split_frontmatter_text(text)
                if text.startswith("---") and body == text:
                    # An opened block with no closing `---` parses as "no frontmatter" — a marker
                    # inside it would be silently ignored, so it is unreadable, not unmarked.
                    raise ValueError("frontmatter block is never closed")
            except (ValueError, UnicodeDecodeError) as exc:
                # FAIL-CLOSED, as for a spec: an unreadable marker must not travel on a guess.
                _die(f"work publish: {rel} at {source_sha[:12]} has unreadable frontmatter "
                     f"({exc.__class__.__name__}) — refusing to judge its placement. Fix it at "
                     "that commit, then re-tag with `bin/yitc-v2 work tag --tag <tag>`.")
                return {}, set()
            if _resolve_placement(rel, fm.get("travels")) != "kernel":
                continue
        tree[rel] = blob
        if modes[rel] == "100755":
            exec_paths.add(rel)
    for rel, blob in parts.items():
        if _spec_part_base(rel) not in tree:
            continue
        tree[rel] = blob
        if modes[rel] == "100755":
            exec_paths.add(rel)
    if parts:
        tree = {rel: tree[rel] for rel in sorted(tree)}   # a part sorts before its base
    return tree, exec_paths


# T-12945 — the published spec set must be CLOSED over the ids its init + seed surfaces name. v2.0.4
# shipped a concern registry and born template naming 8 specs absent from its specs/ (adopter report
# item 15: init asked about SPEC-0135, whose file the release lacked). The cut's placement filter is
# RIGHT (SPEC-0074: v2-self and non-active specs never travel), so the fix is at the SOURCE — a spec a
# published surface needs is re-pinned kernel, a surface naming a non-travelling spec is reworded —
# and this gate refuses a publish that regresses. It first read only the surfaces an
# adopter meets at init and session start. T-12966 extends it to published patterns/*.md + specs/*.yaml,
# whose ids `reword_unpublished_spec_refs` already rewords at the strip — so there it is the BACKSTOP
# for a blob the reword cannot reach (non-UTF-8), naming the id rather than shipping it.
CLOSURE_SURFACES = ("graph/concern-registry.json", "graph/born-ops.yaml")
_SPEC_ID_RE = re.compile(rb"\bSPEC-(\d{4})\b")
_SPEC_FILE_RE = re.compile(r"^specs/(SPEC-\d{4})[-.]")


def _is_closure_surface(rel: str) -> bool:
    # T-13389 — the bootstrap order is what an adopter reads before anything else exists; it cited
    # SPEC-0195 while the release shipped no such file, so it is held to the same closure.
    return (rel in CLOSURE_SURFACES or rel == BOOTSTRAP_ORDER_DOC
            or (rel.startswith("release-view/") and rel.endswith(".md"))
            or (rel.startswith("patterns/") and rel.endswith(".md"))
            or (rel.startswith("specs/") and rel.endswith((".yaml", ".yml"))))


def unresolved_spec_refs(tree: dict) -> dict:
    """{SPEC id: sorted closure surfaces naming it} for every id with no specs/ file in `tree`."""
    published = {m.group(1) for rel in tree if (m := _SPEC_FILE_RE.match(rel))}
    missing = {}
    for rel, blob in tree.items():
        if not _is_closure_surface(rel):
            continue
        for num in set(_SPEC_ID_RE.findall(blob)):
            sid = "SPEC-" + num.decode()
            if sid not in published:
                missing.setdefault(sid, set()).add(rel)
    return {sid: sorted(rels) for sid, rels in sorted(missing.items())}


# T-13427 — the PATH sibling of the id closure above. v2.2.0 shipped SPEC-0118 naming
# `patterns/the AI provider-code-mcp-runbook.md` (the brand pass rewrote a path), and SPEC-0120 named
# the v2-self rule-test ledger the cut never carries: an adopter following either found no file. So a
# `patterns/…` / `specs/…` path named in a published spec must be a file of the release. A placeholder
# template and an id-shaped `specs/SPEC-NNNN…` path are exempt — the id is closed by the gate above.
_PUBLISHED_PATH_RE = re.compile(
    r"(?<![\w/.<-])((?:patterns|specs)/[A-Za-z0-9._\-]+\.(?:md|yaml|yml))(?![\w.\-])")
_SPEC_ID_PATH_RE = re.compile(r"^specs/SPEC-\d{4}")


def dead_published_paths(tree: dict) -> dict:
    """{path: sorted published specs naming it} for every patterns/ or specs/ path no file in `tree` has."""
    def strings(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from strings(v)
        elif isinstance(node, list):
            for v in node:
                yield from strings(v)
        elif isinstance(node, str):
            yield node

    dead = {}
    for rel, blob in tree.items():
        if not (rel.startswith("specs/") and rel.endswith((".yaml", ".yml"))):
            continue
        try:
            doc = state.load_str(blob.decode("utf-8"))
        except Exception:                         # noqa: BLE001 — an unparseable spec is judged elsewhere
            continue
        for text in strings(doc):
            for path in _PUBLISHED_PATH_RE.findall(text):
                if _SPEC_ID_PATH_RE.match(path) or re.search(r"XXXX|NNNN", path) or path in tree:
                    continue
                dead.setdefault(path, set()).add(rel)
    return {path: sorted(rels) for path, rels in sorted(dead.items())}


# T-13505 — the COMPLETENESS sibling of the two closures above. v2.2.2 shipped six split specs as
# their base alone (the tester report this card answers): each base body ends in a pointer to a part
# the release lacked. So every continuation part the SOURCE carries for a base the release ships must
# be a file of the release.
def missing_spec_parts(tree: dict, source_paths) -> dict:
    """{shipped base: sorted parts the source has and `tree` lacks}. A base that does not ship owes
    no part."""
    missing = {}
    for rel in source_paths:
        base = _spec_part_base(rel)
        if base and base in tree and rel not in tree:
            missing.setdefault(base, set()).add(rel)
    return {base: sorted(rels) for base, rels in sorted(missing.items())}


def tree_digest(tree: dict, *, excludes=None) -> str:
    """A deterministic sha256 over the ARTIFACT TREE — every cut file, EXCLUDING the manifest.

    NON-CIRCULAR BY CONSTRUCTION, and that exclusion is the whole point: the manifest DESCRIBES the
    digest, so it can never be an input to it. A verifier recomputes this over the published tree
    minus `release-manifest.yaml` and gets the same value.

    `excludes` (T-12043) generalises that ONE exclusion to the SET the manifest already declares in
    its `digest_excludes` field — which since T-12043 also holds the manifest's DETACHED SIGNATURE,
    for exactly the same non-circularity reason: the signature is made over the manifest, which names
    the digest, so a digest over the signature could never be computed at all. The default is
    unchanged, so every existing caller keeps its old behaviour; the verifier passes the set it reads
    out of the manifest it has already authenticated, so what is excluded is signed rather than
    assumed.

    The fold is over sorted (rel_path, sha256(bytes)) pairs — path-order independent of filesystem
    iteration, content-exact, and free of any timestamp, host or randomness, so the same commit always
    folds to the same digest.
    """
    skip = set(excludes) if excludes is not None else {MANIFEST_FILENAME}
    h = hashlib.sha256()
    for rel in sorted(tree):
        if rel in skip:
            continue
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(hashlib.sha256(tree[rel]).hexdigest().encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def build_manifest(*, tag: str, source_sha: str, digest: str, file_count: int) -> dict:
    """The release MANIFEST (SPEC-0195 rule 5) — provenance as a property of the RELEASE.

    Names the SOURCE ref it was cut from, the DIGEST of the artifact tree, the SIGNATURE TARGET (what
    exactly is signed — this file), the REBUILD command that re-derives the artifact from the source
    ref, and the enumerated template-owned surface. Pure: same inputs → same mapping, no timestamp, so
    a manifest is as reproducible as the tree it describes.
    """
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source_ref": tag,
        # SPEC-0195 rule 9 (T-12045). DERIVED from the tag being cut, never operator-supplied — the
        # module's stated invariant is that the cut is a pure function of the peeled commit, and an
        # operator flag would make the artifact a function of the INVOCATION instead (the same reason
        # `render_release_notes` has no `--answers` option). Content cut at a tag requires an engine
        # at least that tag because engine and content are cut from ONE commit: older engine code was
        # never run against this content, so the floor is exactly where the pair stops being tested.
        REQUIRES_ENGINE_FIELD: requires_engine_floor(tag),
        "source_sha": source_sha,
        "tree_digest": digest,
        # BOTH the manifest and its detached signature are excluded — see `tree_digest`. This stays
        # the ONE carrier of what the digest does not cover: the verifier reads THIS list rather than
        # re-deriving the rule, so the two can never disagree (CHARTER §P5).
        "digest_excludes": [MANIFEST_FILENAME, SIGNATURE_FILENAME],
        "signature_target": MANIFEST_FILENAME,
        "signature_file": SIGNATURE_FILENAME,
        "rebuild": f"yitc-v2 work publish --tag {tag} --dest <path>",
        "template_owned": list(TEMPLATE_OWNED_SURFACE),
        "file_count": file_count,
    }


def render_manifest(manifest: dict) -> str:
    """The manifest's on-disk YAML text — hand-rendered, deterministically ordered.

    Rendered rather than dumped so the field ORDER is the reading order a human wants (what it is,
    where it came from, what it hashes to, what is signed, how to rebuild it) and so the bytes do not
    move when a YAML library changes its formatting. A release artifact whose bytes depend on a
    library version is not reproducible.
    """
    lines = [
        "# Release manifest (SPEC-0195 rule 5) — GENERATED by `yitc-v2 work publish`; do not edit.",
        "# The signature target: signing this file covers the artifact tree through `tree_digest`.",
        f"schema_version: {manifest['schema_version']}",
        f"source_ref: {manifest['source_ref']}",
        f"source_sha: {manifest['source_sha']}",
        f"{REQUIRES_ENGINE_FIELD}: '{manifest[REQUIRES_ENGINE_FIELD]}'",
        f"tree_digest: {manifest['tree_digest']}",
        "digest_excludes:",
    ]
    lines += [f"  - {p}" for p in manifest["digest_excludes"]]
    lines += [
        f"signature_target: {manifest['signature_target']}",
        f"signature_file: {manifest.get('signature_file', SIGNATURE_FILENAME)}",
        f"rebuild: {manifest['rebuild']}",
        f"file_count: {manifest['file_count']}",
        "template_owned:",
    ]
    lines += [f"  - {p}" for p in manifest["template_owned"]]
    return "\n".join(lines) + "\n"


def _write_tree(dest: Path, tree: dict, manifest_text: str, signature: bytes = b"",
                exec_paths=()) -> None:
    """Write the cut + manifest into `dest`, removing whatever the previous release left behind.

    The destination is a DESTINATION only (SPEC-0195 rule 1): it carries no tasks, no journal, no
    lifecycle, and is regenerable from the workshop at any time. So a publish REPLACES its content
    rather than merging into it — a file the new release no longer ships must not survive as a stale
    leftover that the manifest's digest does not describe. `.git` is preserved (it is the destination's
    own history, not release content).

    MODE FIDELITY (T-12172). `exec_paths` names the cut paths that are `100755` at the source
    commit; every written cut path is chmod-ed EXPLICITLY — 0755 for those, 0644 for the rest — so
    the published mode is a function of the source commit alone and not of the publisher's umask.
    Without it `write_bytes` created every file non-executable and a published `bin/yitc-v2` could
    not be invoked, which is what the SPEC-0195 rule-6 entrypoint inventory promises. The manifest
    and the detached signature are written after the cut and keep the default: they are data, not
    part of the cut the modes are read from.
    """
    for child in sorted(dest.iterdir()):
        if child.name == ".git":
            continue
        if child.is_dir():
            import shutil
            shutil.rmtree(child)
        else:
            child.unlink()
    executable = set(exec_paths)
    for rel in sorted(tree):
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(tree[rel])
        out.chmod(0o755 if rel in executable else 0o644)
    (dest / MANIFEST_FILENAME).write_text(manifest_text, encoding="utf-8")
    if signature:
        # The detached signature is written LAST and is not part of the cut: it is made OVER the
        # manifest bytes above, so it cannot exist until they do (T-12043).
        (dest / SIGNATURE_FILENAME).write_bytes(signature)


def _add_trust_surfaces(tree: dict, *, tag: str, source_sha: str, trust_root_arg, revocations_arg,
                        answers, _die, changes=None, capabilities=None) -> dict:
    """Add the four published trust/policy surfaces to the cut, BEFORE the digest is taken.

    Two of them are OPERATOR-SUPPLIED and are copied verbatim — the trust root and the revocation
    list are maintainer-held key material, not something a build step may invent. Two are GENERATED
    from this module's own carriers: `SECURITY.md` (the loss-recovery procedure rule 7 requires be
    written down) and `RELEASE-NOTES.md` (the enumerated verifying-entrypoint inventory of rule 6).

    THE NOTES ARE ASSIGNED HERE AND NOWHERE ELSE. Two rules write into that one published filename
    — SPEC-0197 rule 4's link-back list and SPEC-0195 rule 6's inventory — so the value is COMPOSED
    once by `build_release_notes` and assigned once, here. `answers` is passed IN (collected at the
    publish seam, where its fail-closed card scan belongs) rather than re-derived, so the two rules
    share one writer instead of racing for the last assignment.

    A trust root that does not PARSE is refused here rather than shipped: an unreadable trust root
    reaches every adopter as a mirror that cannot be installed at all, and the cheapest place to
    learn that is the publisher's own terminal.
    """
    out = dict(tree)
    for arg, flag, filename, what in (
            (trust_root_arg, "--trust-root", TRUST_ROOT_FILENAME, "trust root"),
            (revocations_arg, "--revocations", REVOCATION_FILENAME, "revocation list")):
        value = (arg or "").strip()
        if not value:
            continue
        src = Path(value).expanduser()
        if not src.is_file():
            _die(f"work publish: {flag} {src} is not a readable file — the {what} is maintainer-held "
                 "key material a publish COPIES, never invents. Nothing was written.")
        blob = src.read_bytes()
        try:
            parsed = state.load_str(blob.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            parsed = None
            _die(f"work publish: the {what} at {src} does not parse ({exc.__class__.__name__}) — "
                 "refusing to publish a mirror no adopter could verify against. Nothing was written.")
        if not isinstance(parsed, dict):
            _die(f"work publish: the {what} at {src} is not a mapping — refusing to publish a mirror "
                 "no adopter could verify against. Nothing was written.")
        out[filename] = blob
        if filename == REVOCATION_FILENAME:
            # The revocation list travels WITH its anchor-made signature (audit-post finding 1). It
            # is published beside the source file rather than produced here on purpose: signing it
            # needs the ANCHOR private key, and a publish command is exactly the wrong place to
            # require the root of trust to be present. The maintainer signs the list once, out of
            # band, and publish copies both.
            sig_src = src.with_name(src.name + ".sig")
            if not sig_src.is_file():
                _die(f"work publish: the revocation list at {src} has no detached signature at "
                     f"{sig_src} — it must be signed by the ANCHOR key, or a revoked key that "
                     "controls the mirror could delete its own revocation row and re-sign the "
                     "release with itself. Sign it out of band, then re-run. Nothing was written.")
            out[REVOCATION_SIGNATURE_FILENAME] = sig_src.read_bytes()
    out[SECURITY_POLICY_FILENAME] = build_security_policy().encode("utf-8")
    out[RELEASE_NOTES_FILENAME] = build_release_notes(tag, source_sha, answers, changes,
                                                     capabilities).encode("utf-8")
    return out

# T-12944 — the published GRAPH INDEX. Every handbook "Retrieved — SPEC-XXXX" pointer routes through
# `graph query [--kernel]`, which on a `-C` consumer reads the ENGINE's `graph/index.json`. That file
# is v2-self by placement (the workshop's index spans tasks, plans and superseded history), so the cut
# never carried it and a fresh install refused every retrieval (adopter report, v2.0.4). The published
# release therefore carries an index built over ITS OWN cut, by ITS OWN engine: a pure function of the
# tagged commit, so it rides inside `tree_digest` and the manifest's rebuild command re-derives it
# byte-identically. The build runs in a child process against a staged copy, because
# the engine resolves its corpus from its own file location — the staged engine therefore indexes
# exactly the staged tree and nothing of the workshop.
GRAPH_INDEX_REL = "graph/index.json"

_GRAPH_INDEX_DRIVER = """
import sys
sys.path.insert(0, sys.argv[1] + "/bin")
from lib import cli
cli._write_graph_index(cli.graph_build_index())
"""


def build_published_graph_index(tree: dict) -> "bytes | None":
    """`graph/index.json` bytes built over `tree` by the engine `tree` carries, or None when it
    carries no engine (a fixture cut). Raises ValueError when the build fails or reports specs it
    could not parse — a release whose own engine cannot index its own specs is not publishable."""
    import os
    import sys
    import tempfile

    if "bin/yitc-v2" not in tree or "bin/lib/cli.py" not in tree:
        return None
    with tempfile.TemporaryDirectory(prefix="yitc-publish-index-") as tmp:
        stage = Path(tmp)
        for rel, blob in tree.items():
            out = stage / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(blob)
        # YITC_REPO_ROOT would re-point the staged engine at another checkout; the cache is keyed on a
        # git state a staged copy does not have. Bytecode is not written into the stage.
        env = {k: v for k, v in os.environ.items() if k != "YITC_REPO_ROOT"}
        env.update(YITC_GRAPH_CACHE="0", PYTHONDONTWRITEBYTECODE="1")
        run = subprocess.run([sys.executable, "-c", _GRAPH_INDEX_DRIVER, str(stage)], cwd=str(stage),
                             env=env, capture_output=True, text=True, timeout=600)
        index_path = stage / GRAPH_INDEX_REL
        if run.returncode != 0 or not index_path.is_file():
            tail = (run.stderr or run.stdout or "").strip().splitlines()[-3:]
            raise ValueError("the published engine could not build its graph index: "
                             + (" | ".join(tail) or f"exit {run.returncode}"))
        blob = index_path.read_bytes()
    errors = json.loads(blob).get("_parse_errors") or []
    if errors:
        raise ValueError("the published tree carries file(s) its own engine cannot parse: "
                         + "; ".join(str(e) for e in errors[:5]))
    return blob


def strip_and_index_published_tree(tree: dict, identity: "ProjectIdentity | None" = None) -> dict:
    """The published tree after the identity-agnostic strip, with `graph/index.json` built over THAT
    stripped tree (T-13428). Built before the strip (T-12944), the index kept every edge the strip's
    reword then removed from the shipped specs — v2.2.0 indexed SPEC-1004 `supersedes: SPEC-0114`
    while its shipped YAML said null and SPEC-0114 did not ship. Building over the stripped specs
    makes the index agree with every shipped source; the index alone is then stripped like before.
    Raises ValueError when the index cannot be built or the strip leaves it unloadable."""
    tree = strip_published_text(tree, identity)
    blob = build_published_graph_index(tree)
    if blob is None:
        return tree
    blob = strip_published_text({GRAPH_INDEX_REL: blob}, identity)[GRAPH_INDEX_REL]
    try:
        json.loads(blob)
    except ValueError as exc:
        raise ValueError(f"the identity-agnostic strip left {GRAPH_INDEX_REL} unloadable ({exc})")
    tree[GRAPH_INDEX_REL] = blob
    return tree


# T-12937 — the pre-publish INSTALL SMOKE. v2.0.4 shipped an init that refused on every fresh install
# (adopter report, events.jsonl#ts=2026-09-25T14:16:09Z): nothing in the publish path ever ran the
# PUBLISHED artifact the way an adopter does. So before any write, the FINAL candidate tree is staged
# into a temp dir and its own engine runs `-C <fresh git project> init` there; a nonzero exit refuses
# the publish. HERMETIC: HOME, TMPDIR, the shared coordination store (YITC_CROSS_LOG) and the project
# registry (YITC_REGISTRY) all point inside the temp dir, the session identity is a fixed smoke ref
# (every higher-precedence carrier scrubbed), and nothing of the publisher's environment is passed
# beyond PATH — so the smoke can touch neither the workshop journal nor the real shared store.
# Gated on the tree carrying init's inputs (the engine + the born template), exactly as the graph
# index above is gated on the engine: a fixture cut with no born template has no init to smoke.
SMOKE_SESSION_REF = "publish-smoke"
_SMOKE_INPUTS = ("bin/yitc-v2", "bin/lib/init.py", "graph/born-ops.yaml")
# The adopter's own first calls, in order: `session start` backs the carried identity (a bare `init`
# refuses «session_ref undetermined»), then `init` births the project.
SMOKE_VERBS = (("session", "start"), ("init",))


def smoke_install_init(tree: dict, exec_paths=()) -> "dict | None":
    """Stage `tree` as an install, `git init` a fresh project, run `<install>/bin/yitc-v2 -C <project>
    init` hermetically. Returns None when `tree` carries no init to smoke, else
    `{"ok": bool, "returncode": int, "tail": str}`. Never raises for a failed init — the caller refuses."""
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    import os
    import sys
    import tempfile

    if not all(rel in tree for rel in _SMOKE_INPUTS):
        return None
    with tempfile.TemporaryDirectory(prefix="yitc-publish-smoke-") as tmp:
        root = Path(tmp)
        install, proj, home = root / "install", root / "project", root / "home"
        executable = set(exec_paths)
        for rel, blob in tree.items():
            out = install / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(blob)
            out.chmod(0o755 if rel in executable else 0o644)
        home.mkdir()
        (root / "registry.yaml").write_text("projects: []\n", encoding="utf-8")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
               "TMPDIR": str(home), "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1",
               "YITC_SESSION_REF": SMOKE_SESSION_REF, "YITC_GRAPH_CACHE": "0",
               "YITC_CROSS_LOG": str(root / "cross" / "coordination.jsonl"),
               "YITC_REGISTRY": str(root / "registry.yaml"),
               "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "publish-smoke", "GIT_AUTHOR_EMAIL": "smoke@invalid",
               "GIT_COMMITTER_NAME": "publish-smoke", "GIT_COMMITTER_EMAIL": "smoke@invalid"}
        verb = ("git", "init")
        try:
            subprocess.run(["git", "init", "-q", "-b", "main", str(proj)], check=True, env=_git_env._git_child_env(env),
                           capture_output=True, timeout=60)
            for verb in SMOKE_VERBS:
                run = subprocess.run([sys.executable, str(install / "bin" / "yitc-v2"), "-C",
                                      str(proj), *verb], cwd=str(proj), env=env,
                                     capture_output=True, text=True, timeout=600)
                if run.returncode != 0:
                    break
        except (OSError, subprocess.SubprocessError) as exc:
            # `verb` is the step that was running, so a timeout in `init` names `init`.
            return {"ok": False, "returncode": -1, "verb": " ".join(verb),
                    "tail": f"{exc.__class__.__name__}: {exc}"}
        lines = (run.stderr.strip() or run.stdout.strip()).splitlines()
        return {"ok": run.returncode == 0, "returncode": run.returncode, "verb": " ".join(verb),
                "tail": " | ".join(lines[-6:]) or f"exit {run.returncode}"}


def cmd_work_publish(args, *, _append_event, _die, _run_git_cap, _main_worktree, _is_consumer_build,
                     _resolve_placement, _release_view_docs, REPO_ROOT) -> None:
    """`work publish --tag <tag> --dest <path>` — the engine-only publish entry.

    Ordered so that every refusal happens BEFORE any write to the destination (SPEC-0195's
    refuse-before-you-write posture): consumer check → dirty-tree check → tag resolution → cut →
    host-literal guard → commit/tag metadata guard → write → commit + tag (as RELEASE_IDENTITY) →
    read-back → emit. `--dry-run` stops before the write. A publish therefore either produces a complete,
    manifest-bound snapshot or leaves the destination exactly as it found it.
    """
    if _is_consumer_build():
        _die("work publish is ENGINE-ONLY (SPEC-0074 rule 1, the `graph release-view` precedent): a "
             "consumer PINS a published release, it never mints one. Refused under -C.")

    main = _main_worktree(REPO_ROOT) or REPO_ROOT
    tag = (getattr(args, "tag", None) or "").strip()
    dest_arg = (getattr(args, "dest", None) or "").strip()
    if not tag:
        _die("work publish: --tag <tag> required (the governed release tag created by `work tag`)")
    if not dest_arg:
        _die("work publish: --dest <path> required (the destination checkout the snapshot is written to)")

    # A workshop dirty IN THE KERNEL REALM is refused: the manifest describes a COMMIT, so publishing
    # beside uncommitted changes to files that TRAVEL would ship a snapshot whose provenance silently
    # omits what the operator is holding.
    #
    # SCOPED TO THE KERNEL REALM DELIBERATELY, not tightened to "any dirt". Uncommitted `events.jsonl`
    # on `main` is the NORMAL, sanctioned state of this system: a journal append needs no worktree
    # (D-0049) and is folded into main by the next `land`, so main is dirty with it most of the time.
    # A blanket dirty-check would therefore refuse almost every publish over dirt that CANNOT reach the
    # artifact — the same wedge shape X-0330 describes for a dirty MEMORY.md. Realm is exactly the right
    # boundary: a v2-self path never enters the cut, so its dirt cannot make the manifest wrong; a
    # kernel-realm path does, so its dirt can.
    dirty = _git_out(_run_git_cap, main, ["status", "--porcelain"])
    if dirty is None:
        _die(f"work publish: could not read the working-tree state of {main} — refusing.")
    dirty_kernel = []
    for line in dirty.splitlines():
        rel = line[3:].strip().strip('"')
        if " -> " in rel:                      # a rename entry: judge the DESTINATION path
            rel = rel.split(" -> ", 1)[1].strip().strip('"')
        if rel and _resolve_placement(rel) == "kernel":
            dirty_kernel.append(rel)
    if dirty_kernel:
        _die("work publish: the workshop checkout is DIRTY IN THE KERNEL REALM — a release is cut from "
             "a landed commit, so publishing beside uncommitted changes to files that TRAVEL would ship "
             "a snapshot the manifest does not describe. Land or stash them, then re-run. Dirty "
             "kernel-realm path(s):\n  " + "\n  ".join(sorted(dirty_kernel)))

    source_sha = peel_tag(tag, _run_git_cap=_run_git_cap, main=main)
    if not source_sha:
        _die(f"work publish: tag '{tag}' does not resolve to a commit in {main} — publish cuts a "
             "GOVERNED release tag (create it with `yitc-v2 work tag --tag <tag>`).")

    dest = Path(dest_arg).expanduser()
    if not dest.is_dir():
        _die(f"work publish: --dest {dest} is not an existing directory — create the destination "
             "checkout first (a release is written INTO a destination, never conjured as one).")

    # T-13354 (SPEC-0074 rule 4b): the project-identity operands, read off THIS host's registry before
    # anything is cut. An absent or unreadable inventory refuses here — it never reads as "nothing to
    # protect"; a readable `projects: {}` is the explicit way to say this host runs none.
    registry = engine_route.registry_path(main)
    try:
        identity = project_identity_operands(registry, main)
    except ValueError as exc:
        _die(f"work publish: {exc} — the project-identity guard (SPEC-0074 rule 4b) cannot judge a "
             "release without this host's project inventory, and publishing unjudged would ship every "
             "project name the source cites. Point YITC_REGISTRY at the registry (an explicit "
             "`projects: {}` declares that the host runs none), then re-run "
             f"`bin/yitc-v2 work publish --tag {tag} --dest {dest}`. Nothing was written.")
        return

    tree, exec_paths = cut_release_tree(source_sha, _run_git_cap=_run_git_cap, main=main,
                                       _resolve_placement=_resolve_placement, _die=_die,
                                       raw_handbook_docs=_release_view_docs())
    if not tree:
        _die(f"work publish: the kernel-realm cut at {source_sha[:12]} is EMPTY — refusing to publish "
             "an empty release (a cut with no files means the source ref is not a yitc checkout).")

    # T-12048 (SPEC-0197): the contribution POLICY joins the cut HERE — BEFORE the host-literal
    # guard and the strip, not merely before the digest. Being in the tree at digest time is what
    # stops the release from shipping committed bytes the manifest does not describe; being in it
    # before the guard is what stops it from being a published surface nobody checks. It is a
    # function of `source_sha` alone, so the reproducibility invariant holds either way — see the
    # T-12048 section header.
    tree = attach_contribution_surfaces(tree)
    # The link-back ids are SCANNED here, at the same point in the seam they always were, so a card
    # whose `answers:` will not parse still refuses before any write. They are not rendered here:
    # SPEC-0197 rule 4's list and SPEC-0195 rule 6's entrypoint inventory share ONE published file,
    # so the value is composed once (`build_release_notes`) and assigned once, with the trust
    # surfaces below. Passing `answers` through keeps this scan's position and that single writer.
    answers = collect_answered_proposals(source_sha, main=main, _die=_die)

    violations = host_literal_violations(tree)
    if violations:
        _die("work publish: the engine code in this cut carries HOST ABSOLUTE PATHS — a release is not "
             "cut from a tree the engine-code host-path guard fails (SPEC-0074 rule 4, code side; the "
             "guard is tests/test_engine_code_host_path_guard.py). Offending file(s):\n  "
             + "\n  ".join(violations)
             + "\nDerive the value off `host_paths.host_home()` instead of spelling the literal.")

    # The identity-agnostic strip over the published prose, then the graph index built over its
    # result (T-13428), then the WHOLE-TREE assertions below — so what is digested, signed and
    # shipped is what was checked.
    try:
        tree = strip_and_index_published_tree(tree, identity)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        _die(f"work publish: {exc} — `graph query --kernel` would refuse on every install of this "
             "release. Nothing was written.")
        return

    # T-12945 — refuse a release whose init/seed surfaces name a spec it does not carry.
    unresolved = unresolved_spec_refs(tree)
    if unresolved:
        _die("work publish: the published surfaces name spec(s) the release does NOT carry — an "
             "adopter would be pointed at rules they cannot read. Re-pin a spec the surface genuinely "
             "needs to the kernel realm at source, or reword the surface (SPEC-0074 placement stands). "
             "Nothing was written. Unresolved:\n  "
             + "\n  ".join(f"{sid}  ← {', '.join(rels)}" for sid, rels in unresolved.items()))
        return

    # T-13427 — refuse a release whose shipped specs name a patterns/ or specs/ file it does not carry.
    dead_paths = dead_published_paths(tree)
    if dead_paths:
        rows = "\n  ".join(f"{path}  ← {', '.join(rels)}" for path, rels in dead_paths.items())
        _die(f"work publish: published spec(s) name file path(s) the release does NOT carry — an adopter "
             f"following the path finds no file. Fix the path at source (`bin/yitc-v2 spec edit <SPEC>`) "
             f"or ship the file. Nothing was written. Missing:\n  {rows}")
        return

    # T-13505 — refuse a release that ships a split spec's base without one of its continuation parts.
    source_specs = _git_out(_run_git_cap, main, ["ls-tree", "-r", "--name-only", source_sha, "specs/"])
    if source_specs is None:
        _die(f"work publish: could not list specs/ at {source_sha[:12]} — refusing to publish a release "
             "whose split specs cannot be checked for completeness. Nothing was written. Confirm the "
             f"tag still resolves (`git rev-parse {tag}^{{commit}}`), then re-run "
             f"`bin/yitc-v2 work publish --tag {tag} --dest {dest}`.")
        return
    lost_parts = missing_spec_parts(tree, [ln.strip() for ln in source_specs.splitlines()])
    if lost_parts:
        rows = "\n  ".join(f"{part}  ← continues {base}" for base, rels in lost_parts.items()
                           for part in rels)
        _die(f"work publish: the release ships a split spec WITHOUT its continuation part(s) — the base "
             f"body ends in a pointer to a file an adopter would not have (SPEC-0120 §3: a part travels "
             f"with its base). Nothing was written. The cut admits a part with its base by "
             f"construction, so this is a defect of the cut, not of the source: confirm the file is in "
             f"the tagged commit (`git ls-tree -r --name-only {tag} specs/`) and do not publish this "
             f"tag until the cut carries it. Missing:\n  {rows}")
        return

    # T-12043 — the TRUST + POLICY surfaces join the cut HERE, between the strip and the whole-tree
    # assertion, and the position is deliberate on BOTH sides:
    #
    #   AFTER the strip, because these files are maintainer-supplied key material and generated
    #   policy. The strip's job is to launder DEV PROVENANCE out of travelling prose; silently
    #   rewriting a trust root or a security policy is not laundering provenance, it is editing the
    #   thing an adopter is about to trust.
    #
    #   BEFORE the whole-tree assertion, because SPEC-0074 rule 4 covers EVERY released file and
    #   these four travel like any other. A host literal in them is therefore REFUSED — loudly, for
    #   the publisher to fix at the source — which is the same asymmetry this module already applies
    #   to engine code: refuse what must not be rewritten, strip what may be.
    tree = _add_trust_surfaces(tree, tag=tag, source_sha=source_sha,
                               trust_root_arg=getattr(args, "trust_root", None),
                               revocations_arg=getattr(args, "revocations", None),
                               answers=answers, _die=_die,
                               changes=collect_change_list(tag, source_sha, main=main,
                                                           _resolve_placement=_resolve_placement,
                                                           _die=_die),
                               capabilities=collect_capabilities(
                                   tag, source_sha, main=main, _run_git_cap=_run_git_cap,
                                   _resolve_placement=_resolve_placement,
                                   raw_handbook_docs=_release_view_docs(), _die=_die))

    survivors = published_host_literals(tree)
    if survivors:
        _die("work publish: host absolute paths SURVIVED the identity-agnostic strip in the published "
             "tree — a release must be host-clean on every travelling surface (SPEC-0074 rule 4, "
             "extended by §4a). This is a gap in the strip ruleset, not a value to launder. "
             "Surviving literal(s):\n  " + "\n  ".join(survivors))

    # The account-name arm of the same whole-tree assertion (T-12354, SPEC-0195 rule 1a). Placed HERE,
    # beside its sibling, so the two host-literal classes are judged at one seam over the same final
    # tree — and REFUSING rather than stripping, so the published bytes stay a function of the tagged
    # commit alone (see the `local_account_names` section header).
    account_names, _account_exclusions = local_account_names()
    published_names = published_account_names(tree, account_names)
    if published_names:
        _die("work publish: a bare unix ACCOUNT NAME of a collaborator provisioned on this host is "
             "published in this cut — a name is a HOST LITERAL (SPEC-0195 rule 1a) and it identifies a "
             "real person to every stranger who reads the mirror. It is REFUSED, never stripped: a "
             "host-derived rewrite would make the published bytes depend on WHO published, breaking the "
             "reproducible digest (rule 5). Abstract it AT THE SOURCE to a role placeholder such as "
             "`<collaborator>` — the prose is about a provisioned collaborator, not about that person. "
             "Occurrence(s):\n  " + "\n  ".join(published_names))

    # The project-identity arm (T-13354, SPEC-0074 rule 4b) over the same final tree. The strip above
    # already abstracted every PROVENANCE position (prose, comments, docstrings), so a survivor here is a
    # VALUE — an engine-code string, a machine-read value, a non-UTF-8 blob — or a path: refused, never
    # rewritten, for the publisher to fix at the source.
    leaked = published_project_identity(tree, identity)
    if leaked:
        rows = "\n  ".join(leaked[:100] + ([f"... and {len(leaked) - 100} more"] if len(leaked) > 100 else []))
        _die("work publish: a PROJECT of this host is named by a VALUE in the published tree — a project "
             "name or domain is dev provenance (SPEC-0074 rule 4b). Prose, comments and docstrings were "
             "abstracted to `<project>` / `<project-domain>`; what remains is an engine-code string, a "
             "machine-read value or a path, which is REFUSED, never rewritten. Rewrite it at the source "
             "to a role word (\"a consumer\") or `<project>`, land it, re-tag, then re-run "
             f"`bin/yitc-v2 work publish --tag <new-tag> --dest {dest}`. Nothing was written. "
             f"Occurrence(s):\n  {rows}")
        return

    # T-12937 — the install smoke runs over the FINAL tree (strip, trust surfaces and index all in), so
    # what an adopter installs is what was smoked; still before the digest and every write.
    smoke = smoke_install_init(tree, exec_paths)
    if smoke is not None and not smoke["ok"]:
        _die(f"work publish: the pre-publish INSTALL SMOKE failed — the candidate, installed into a temp "
             f"dir, could not run `-C <fresh project> {smoke['verb']}` (exit {smoke['returncode']}). "
             "Every adopter's first calls would fail the same way (the v2.0.4 class). Fix the source "
             f"and re-tag. Nothing was written. Last output: {smoke['tail']}")
        return

    # The digest is taken over the tree WITH the trust surfaces in it, so the signed manifest covers
    # them: a mirror whose trust root, revocation list, security policy or entrypoint inventory was
    # edited after publication fails the digest check like any other tampered byte. (The bootstrap
    # anchor is what makes the trust root trustworthy at FIRST install, when there is no verified
    # digest yet; the digest is the second, independent lock on the same files.)
    digest = tree_digest(tree, excludes=[MANIFEST_FILENAME, SIGNATURE_FILENAME])
    manifest = build_manifest(tag=tag, source_sha=source_sha, digest=digest, file_count=len(tree))
    manifest_text = render_manifest(manifest)

    # T-13382 (SPEC-0074 rule 4b, metadata) — the commit and tag this publish will write are published
    # surfaces too: judged here, before any write, by the same matcher as the tree.
    metadata = publish_metadata(tag, digest)
    leaked_meta = "\n  ".join(published_metadata_identity(metadata, identity))
    if leaked_meta:
        _die(f"work publish: the release COMMIT or TAG would carry a project of this host — commit and tag "
             f"metadata travel with the release (SPEC-0074 rule 4b). A tag naming a project: cut a new one "
             f"with `bin/yitc-v2 work tag --tag <new-tag>`; the identity: fix RELEASE_IDENTITY at the source "
             f"and land it. Then re-run `bin/yitc-v2 work publish --tag <new-tag> --dest {dest}`. Nothing "
             f"was written. Occurrence(s):\n  {leaked_meta}")
        return

    # SIGN the manifest bytes BEFORE they are written, so a publish that cannot sign never leaves a
    # half-signed destination behind (the same refuse-before-you-write posture as every check above).
    signing_key = (getattr(args, "signing_key", None) or "").strip()
    signature = b""
    if signing_key:
        key_path = Path(signing_key).expanduser()
        if not key_path.is_file():
            _die(f"work publish: --signing-key {key_path} is not a readable key file — a release is "
                 "SIGNED (SPEC-0195 rule 6) and an artifact nothing signed is installable by no "
                 "entrypoint. Nothing was written.")
        signature = sign_blob(manifest_text.encode("utf-8"), key_path)
        if not signature:
            _die(f"work publish: signing the manifest with {key_path} FAILED — refusing to publish an "
                 "artifact whose signature could not be made. Nothing was written.")

    # `--dry-run` (T-13382): every guard above has run — cut, strip, the tree and metadata refusals, the
    # install smoke, signing — and nothing is written or journaled. An in-process caller gets what a
    # real publish would have written, so it can be measured without a destination being touched.
    if getattr(args, "dry_run", False):
        print(f"dry run: {tag} -> {source_sha[:12]} | {len(tree)} file(s) | digest {digest[:12]} | "
              f"commit+tag as {metadata['committer']} | nothing written to {dest}, nothing journaled")
        return {"tree": tree, "metadata": metadata, "digest": digest, "manifest": manifest_text}

    _write_tree(dest, tree, manifest_text, signature, exec_paths=exec_paths)

    # A single HISTORY-FREE commit: the destination carries the release, never the workshop's history
    # (the >100MB journal blobs never travel). Each publish is one self-contained commit.
    # `--force`: the cut ships its own `.gitignore` (`.*/`, T-11882), which would silently drop a
    # kernel-placed dot-dir file (.github/ISSUE_TEMPLATE/…) from the index the cut still writes —
    # the manifest/tree digest split that refused v2.0.5 (T-13100). Commit and tag are written as
    # RELEASE_IDENTITY with host hooks off, then read back (T-13382).
    # `--allow-empty`: EVERY publish writes its own neutral commit — an unchanged re-publish never
    # re-tags a HEAD some earlier, unchecked commit wrote. The commit is read back BEFORE the tag is
    # (re)pointed at it, so a mismatch refuses with the staging tag untouched.
    git_env = _publish_git_env(metadata)
    added = _run_git_cap(["add", "-A", "--force"], dest)
    if added.returncode != 0:      # never `--allow-empty` over a failed stage (audit-post fp1:389a554d317aabc2)
        _die(f"work publish: staging the release into {dest} failed — "
             f"{added.stderr.strip() or added.stdout.strip()}. Nothing was committed; fix the destination "
             f"checkout, then re-run `bin/yitc-v2 work publish --tag {tag} --dest {dest}`.")
    made = _run_git_cap([*_PUBLISH_GIT_CONFIG, "commit", "--allow-empty", "-m", metadata["commit message"],
                         "--no-verify"], dest, env=git_env)
    if made.returncode != 0:
        _die(f"work publish: writing the release commit into {dest} failed — "
             f"{made.stderr.strip() or made.stdout.strip()}. Fix the destination checkout, then re-run "
             f"`bin/yitc-v2 work publish --tag {tag} --dest {dest}`.")
    mismatches = "\n  ".join(written_metadata_mismatches(dest, metadata, identity, _run_git_cap=_run_git_cap,
                                                         tagged=False))
    if mismatches:
        _die(f"work publish: the commit written into {dest} is NOT the metadata that was checked — "
             f"something on this host rewrote it after the check; the tag was NOT written. Do NOT push "
             f"this destination; discard it and re-publish into a fresh one: `bin/yitc-v2 work publish "
             f"--tag {tag} --dest <fresh-dir>`. Mismatch(es):\n  {mismatches}")
    # `-f`: the dest is the LOCAL staging checkout, and a re-publish of the same tag into it (the
    # UNSIGNED notice below asks for one) re-points the staging tag at the new release commit. The
    # published mirror's own tag is never moved by this — a push of a moved tag is refused there.
    tagged = _run_git_cap([*_PUBLISH_GIT_CONFIG, "tag", "-a", "-f", tag, "-m", metadata["tag message"]],
                          dest, env=git_env)
    if tagged.returncode != 0:
        _die(f"work publish: tagging the release commit '{tag}' in {dest} failed — "
             f"{tagged.stderr.strip() or tagged.stdout.strip()}. Fix the destination checkout, then re-run "
             f"`bin/yitc-v2 work publish --tag {tag} --dest {dest}`.")
    mismatches = "\n  ".join(written_metadata_mismatches(dest, metadata, identity, _run_git_cap=_run_git_cap))
    if mismatches:
        _die(f"work publish: the commit/tag written into {dest} is NOT the metadata that was checked — "
             f"something on this host rewrote it after the check. Do NOT push this destination; discard it "
             f"and re-publish into a fresh one: `bin/yitc-v2 work publish --tag {tag} --dest <fresh-dir>`. "
             f"Mismatch(es):\n  {mismatches}")

    _append_event("release_published", None, {
        "tag": tag,
        "source_sha": source_sha,
        "tree_digest": digest,
        "destination": str(dest),
        "file_count": len(tree),
        # T-13354 — counts + the operand FINGERPRINT, never the names: a rebuild of this tag compares it
        # to prove it supplied the same registry input (SPEC-0195 rule 5).
        "project_identity": {"names": len(identity.names), "domains": len(identity.domains),
                             "excluded": len(identity.excluded),
                             "fingerprint": project_identity_fingerprint(identity)},
        "install_smoke": ("skipped (no init in the cut)" if smoke is None
                          else "passed: " + ", ".join(" ".join(v) for v in SMOKE_VERBS)),
    })
    print(f"release_published: {tag} -> {source_sha[:12]} | {len(tree)} file(s) | "
          f"digest {digest[:12]} | dest {dest}")
    print(f"  commit + annotated tag {tag} written as {metadata['committer']} (host identity and hooks "
          "not used; read back and matched)")
    print(f"  project identity: {len(identity.names)} name(s) + {len(identity.domains)} domain(s) "
          f"abstracted or refused, {len(identity.excluded)} excluded (registry {registry}; fingerprint "
          f"{project_identity_fingerprint(identity)[:12]})")
    if signature:
        print(f"  signed: {SIGNATURE_FILENAME} over {MANIFEST_FILENAME} | trust root "
              f"{TRUST_ROOT_FILENAME} | policy {SECURITY_POLICY_FILENAME} | notes "
              f"{RELEASE_NOTES_FILENAME}")
    else:
        # LOUD, and it says what the consequence IS rather than merely noting an omission: the
        # verifying entrypoints refuse an unsigned artifact (SPEC-0195 rule 6 has no shortcut), so
        # this snapshot is publishable but NOT installable by anybody, the publisher included.
        print("  UNSIGNED — no --signing-key was given, so this artifact carries no "
              f"{SIGNATURE_FILENAME}. Every verifying entrypoint REFUSES an unsigned release "
              "(SPEC-0195 rule 6), so it cannot be installed by anybody, including this machine. "
              "Re-publish with --signing-key <path> before announcing it.")


def _ssh_keygen(argv: list, *, stdin: "bytes | None" = None, timeout: int = 60):
    """The ONE process seam to the signing primitive — no other function here spawns it.

    Returns the CompletedProcess, or None when the tool is missing, times out, or otherwise cannot
    run. Never raises: an unavailable primitive is a REFUSAL to verify, which the callers turn into
    a named reason — it is never a crash and never a silent pass.
    """
    import shutil
    if not shutil.which("ssh-keygen"):
        return None
    try:
        return subprocess.run(["ssh-keygen", *argv], input=stdin, capture_output=True,
                              timeout=timeout)
    except Exception:  # noqa: BLE001 — an unusable primitive is UNVERIFIED, never an exception
        return None


def signing_primitive_available() -> bool:
    """True when the signing primitive can actually SIGN AND VERIFY — the honest skip condition.

    A FUNCTIONAL round trip (generate a throwaway key, sign a byte, verify it), not a
    `which ssh-keygen`: a binary that exists but whose build lacks the signature subcommands would
    pass a presence check and then fail every real call, which is the false-green a skip guard exists
    to prevent. A suite that cannot sign must SAY it is silent rather than read green (SPEC-0165
    item 11 — absence is not evidence).
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        key = Path(td) / "probe"
        rp = _ssh_keygen(["-t", "ed25519", "-N", "", "-C", "probe", "-f", str(key), "-q"],
                         timeout=30)
        if rp is None or rp.returncode != 0 or not key.is_file():
            return False
        sig = sign_blob(b"probe", key)
        if not sig:
            return False
        pub = key.with_suffix(".pub").read_text(encoding="utf-8")
        return verify_blob(b"probe", sig, f"{RELEASE_PRINCIPAL} {pub.strip()}\n")


def key_fingerprint(public_key_text: str) -> "str | None":
    """The `SHA256:…` fingerprint of a public key, or None when it cannot be read.

    Fail-closed by return type: a caller that cannot compute a fingerprint must not proceed as if
    the key matched. Every use below compares this against a DECLARED fingerprint, which is what
    catches a trust-root entry whose key body was swapped while its fingerprint line was left alone.
    """
    text = (public_key_text or "").strip()
    if not text:
        return None
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        pub = Path(td) / "k.pub"
        pub.write_text(text + "\n", encoding="utf-8")
        rp = _ssh_keygen(["-l", "-f", str(pub)])
    if rp is None or rp.returncode != 0:
        return None
    for token in rp.stdout.decode("utf-8", "replace").split():
        if token.startswith("SHA256:"):
            return token
    return None


def sign_blob(blob: bytes, key_path: Path) -> "bytes | None":
    """Detached signature over EXACTLY `blob`, made by the private key at `key_path`.

    Reads the key from the given FILE and nothing else — no agent, no ambient keyring, no
    `~/.ssh` lookup — which is what lets the tests generate a throwaway key under a temp dir and
    sign with it without touching the operator's real keys.
    """
    rp = _ssh_keygen(["-Y", "sign", "-q", "-f", str(key_path), "-n", SIGNING_NAMESPACE, "-"],
                     stdin=blob)
    if rp is None or rp.returncode != 0 or not rp.stdout.strip():
        return None
    return rp.stdout


def signing_key_fingerprint(blob: bytes, signature: bytes) -> "str | None":
    """The fingerprint of the key that made `signature` over `blob` — WITHOUT trusting it.

    This is the check-only reading: it proves the signature is well-formed and internally consistent
    and says WHICH key made it, while deciding nothing about whether that key is trusted. That
    separation is what makes "refused, NAMING the revocation" possible: a revoked key's signature is
    cryptographically fine, and the refusal has to be able to say whose it is.

    Returns None when the signature does not check out at all — an unreadable signature names no key.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        sig = Path(td) / "m.sig"
        sig.write_bytes(signature)
        rp = _ssh_keygen(["-Y", "check-novalidate", "-n", SIGNING_NAMESPACE, "-s", str(sig)],
                         stdin=blob)
    if rp is None or rp.returncode != 0:
        return None
    out = (rp.stdout + rp.stderr).decode("utf-8", "replace")
    for token in out.replace("\n", " ").split():
        if token.startswith("SHA256:"):
            return token.strip().rstrip(".")
    return None


def allowed_signers_text(entries) -> str:
    """The verifier's key set, rendered in the primitive's allowed-signers form.

    Built FRESH from an already-validated key set at each use — never read from a file in the
    artifact. A verifier that read the mirror's own signer list would be letting the artifact name
    its own authority, which is exactly what the bootstrap anchor exists to prevent.
    """
    return "".join(f"{RELEASE_PRINCIPAL} {str(e.get('public_key') or '').strip()}\n"
                   for e in entries if str(e.get("public_key") or "").strip())


def verify_blob(blob: bytes, signature: bytes, signers_text: str) -> bool:
    """True iff `signature` is a valid signature over `blob` by SOME key in `signers_text`.

    The namespace is pinned, so a signature made for another purpose by the same key does not
    verify here. Any failure — bad signature, wrong namespace, key not listed, primitive missing —
    is False; there is no third value, because every caller has already resolved WHICH key it is
    dealing with through `signing_key_fingerprint`.
    """
    if not signers_text.strip() or not signature:
        return False
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        signers = Path(td) / "allowed_signers"
        signers.write_text(signers_text, encoding="utf-8")
        sig = Path(td) / "m.sig"
        sig.write_bytes(signature)
        rp = _ssh_keygen(["-Y", "verify", "-f", str(signers), "-I", RELEASE_PRINCIPAL,
                          "-n", SIGNING_NAMESPACE, "-s", str(sig)], stdin=blob)
    return rp is not None and rp.returncode == 0


# ── The TRUST MODEL (SPEC-0195 rule 7) ───────────────────────────────────────────────────────────

def transition_record(entry: dict) -> bytes:
    """The canonical BYTES a rotation transition signs (SPEC-0195 rule 7, rotation).

    A rotation is "a new key entering by a transition signed by a still-valid key". These bytes are
    what that transition covers, so all of it is bound at once: re-pointing `admitted_by` at a
    different admitter, swapping the key body, renaming the principal or back-dating `valid_from`
    each change these bytes and invalidate the signature. Rendered field-by-field rather than dumped
    so the bytes do not move when a YAML library changes its formatting — a transition that
    re-verifies only under one library version is not a transition.

    THE VALIDITY WINDOW IS INSIDE THE SIGNATURE, and it has to be (audit-post finding 2): the
    verifier ENFORCES `valid_until`, so leaving it outside the signed bytes would let the holder of
    an expired key extend or delete its own expiry in the published file and sign an accepted
    release. A field that is enforced but unauthenticated is not a control — it is a suggestion the
    attacker also gets to edit. `overlap_until` rides along for the same reason: rule 7 requires the
    window to be DECLARED, and a declaration anyone can rewrite declares nothing.
    """
    return (
        "yitc-trust-transition\n"
        f"schema_version: {TRUST_ROOT_SCHEMA_VERSION}\n"
        f"fingerprint: {str(entry.get('fingerprint') or '').strip()}\n"
        f"principal: {str(entry.get('principal') or '').strip()}\n"
        f"public_key: {str(entry.get('public_key') or '').strip()}\n"
        f"valid_from: {str(entry.get('valid_from') or '').strip()}\n"
        f"valid_until: {str(entry.get('valid_until') or '').strip()}\n"
        f"overlap_until: {str(entry.get('overlap_until') or '').strip()}\n"
        f"admitted_by: {str(entry.get('admitted_by') or '').strip()}\n"
    ).encode("utf-8")


def _expired(entry: dict, now: str) -> bool:
    """True when this key's RECORDED validity end has passed.

    `valid_until` is ENFORCED, not decorative: rule 7 requires the retired key's validity END to be
    recorded, and a recorded expiry nothing honours is a field pretending to be a control. The clock
    is the ADOPTER's — the signature carries no trusted timestamp, so verify time is the only time
    available. Said out loud because it has a consequence: a release signed while the key was valid
    stops verifying once the key expires, which is the intended, standard behaviour (re-sign with a
    current key) rather than an oversight.
    """
    until = str(entry.get("valid_until") or "").strip()
    return bool(until) and until <= now


def admission_window_covers(admitter: dict, entry: dict, *, anchor_fp: str) -> bool:
    """Did the ADMITTER's own recorded validity cover the moment the admitted key entered?

    THE AUTHENTICATED TRANSITION-FRESHNESS MECHANISM (audit-post finding 2). Without it an EXPIRED
    key still admits fresh signers forever: the walk checked only that the admitter was admitted and
    unrevoked, so a key whose validity ended in 2020 could sign in a new signing key today and that
    key would verify releases.

    WHY NOT THE LITERAL "REFUSE IF THE ADMITTER IS EXPIRED AT VERIFY TIME" — it would break the very
    thing rule 7 exists to enable. Rotation IS the old key retiring: it admits the successor, its
    overlap window closes, its `valid_until` passes. Under the literal rule the successor's admission
    would evaporate on that date and the release would stop verifying, so every rotation would be a
    scheduled outage. The auditor's own fix line offers this alternative ("or add an authenticated
    transition-freshness mechanism") and it is the one that holds both properties at once.

    BOTH SIDES ARE AUTHENTICATED, which is what makes it a control rather than a hint: the admitted
    key's `valid_from` and the admitter's `valid_until` each sit inside the bytes ITS OWN transition
    signs (`transition_record`), so neither can be moved without invalidating a signature.

    Fail-closed: an admission that carries no `valid_from` cannot be placed in time at all, so a
    bounded admitter cannot vouch for it. The ANCHOR is exempt — nothing signs its entry, so its
    `valid_until` is unauthenticated file content and enforcing it would let whoever controls the
    mirror expire the root of trust (the same reason the walk does not expire the anchor).
    """
    if str(admitter.get("fingerprint") or "").strip() == (anchor_fp or "").strip():
        return True
    until = str(admitter.get("valid_until") or "").strip()
    if not until:
        return True                       # no recorded end: an unbounded key vouches at any time
    entered = str(entry.get("valid_from") or "").strip()
    if not entered:
        return False
    return entered <= until


def read_trust_root(tree: dict) -> "dict | None":
    """The published trust root AS PARSED FROM THE SNAPSHOT, or None when absent/unparseable.

    Takes the SNAPSHOT rather than a directory: every fact the gate decides on must come from the one
    read whose bytes are also digested and installed. None is a THIRD value, distinct from "an empty
    key set" — an unreadable trust root must never read as "no keys are valid, carry on"
    (SPEC-0165 item 11 — absence is not evidence).
    """
    return _parse_yaml_blob(tree.get(TRUST_ROOT_FILENAME))


def read_revocations(tree: dict) -> "dict | None":
    """The published revocation list AS PARSED FROM THE SNAPSHOT, or None when absent/unparseable.

    An unreadable revocation list is NOT an empty one, and the caller refuses on it: a verifier that
    silently treated an unparseable revocation file as "nothing is revoked" would hand an attacker a
    one-byte revocation bypass.
    """
    return _parse_yaml_blob(tree.get(REVOCATION_FILENAME))


def _parse_yaml_blob(blob) -> "dict | None":
    if not blob:
        return None
    try:
        data = state.load_str(blob.decode("utf-8"))
    except Exception:  # noqa: BLE001 — missing/unreadable/unparseable are all "cannot answer"
        return None
    return data if isinstance(data, dict) else None


def revoked_fingerprints(revocations: dict) -> dict:
    """{fingerprint: revocation entry} — the map a refusal reads to NAME the revocation."""
    out = {}
    for row in (revocations or {}).get("revocations") or []:
        if isinstance(row, dict):
            fp = str(row.get("fingerprint") or "").strip()
            if fp:
                out[fp] = row
    return out


def resolve_anchor_entry(trust_root: dict, anchor: str):
    """Resolve the ONE `role: anchor` entry the out-of-band fingerprint pins. `(entry, errors)`.

    Split out of the full walk (audit-post finding 1) because the ORDER matters: the revocation list
    must be authenticated BEFORE it is used, the key that authenticates it is the anchor, and the
    anchor is established here without consulting any revocation. That is the only acyclic ordering
    — using the revocation list to decide who may sign the revocation list is the circularity the
    finding named.

    Two checks, both fail-closed: exactly one anchor entry whose fingerprint EQUALS the out-of-band
    value, and a key body that actually hashes to the fingerprint it declares (the substitution a
    fingerprint-only check misses).
    """
    keys = [k for k in (trust_root or {}).get("keys") or [] if isinstance(k, dict)]
    anchors = [k for k in keys if str(k.get("role") or "").strip() == "anchor"]
    if len(anchors) != 1:
        return None, [f"trust root must carry EXACTLY ONE `role: anchor` entry (found "
                      f"{len(anchors)}) — the out-of-band anchor is what the whole chain hangs from"]
    entry = anchors[0]
    declared = str(entry.get("fingerprint") or "").strip()
    if declared != (anchor or "").strip():
        return None, [f"the mirror's trust root is anchored on {declared or '<unset>'} but the "
                      f"OUT-OF-BAND anchor pinned for this install is {anchor!r} — REFUSED at the "
                      "first-install boundary (SPEC-0195 rule 7): the mirror cannot vouch for itself"]
    actual = key_fingerprint(str(entry.get("public_key") or ""))
    if actual is None or actual != declared:
        return None, [f"the trust root's anchor entry declares fingerprint {declared} but its public "
                      f"key hashes to {actual or '<unreadable>'} — the key body was substituted "
                      "under an untouched fingerprint line"]
    return entry, []


def validate_trust_root(trust_root: dict, anchor: str, revoked: dict, *, now: str):
    """Walk the trust root from the OUT-OF-BAND anchor. Returns `(valid_keys, errors)`.

    THE BOOTSTRAP PROBLEM THIS SOLVES. The mirror cannot vouch for itself at the first install
    boundary — an attacker who can rewrite the artifact can rewrite the key list beside it. So the
    adopter pins ONE fingerprint out of band (rule 7, first-install trust ANCHOR) and this walk
    admits every other key only by a chain of signed transitions leading back to it. The trust root
    is therefore DATA the anchor authorises, never authority in its own right.

    Five checks, each fail-closed, in order:

      (a) EXACTLY ONE `role: anchor` entry, whose fingerprint EQUALS the caller's out-of-band
          anchor. Zero, several, or a different one is a refusal — this is the whole bootstrap.
      (b) Every entry's DECLARED fingerprint must equal the one recomputed from its own
          `public_key`. This is what catches a key body swapped under an untouched fingerprint
          line, which is otherwise the cheapest tamper in the file.
      (c) Non-anchor entries are admitted by FIXPOINT: an entry enters only when its `admitted_by`
          is already admitted and its `transition_signature` verifies over `transition_record()`
          against that admitter ALONE. Anything still unadmitted when the fixpoint settles is an
          error naming it — appearing in the file admits nothing, which is precisely how a rogue
          key appended to a mirror's trust root is refused.
      (d) REVOCATION CASCADES; RETIREMENT DOES NOT. A key admitted by a REVOKED key is itself
          refused: revocation means compromise, and a compromised key's issuances are suspect. A
          key that merely reached its `valid_until` keeps what it admitted — a planned retirement
          is not a compromise, and cascading it would break the ordinary overlap-window rotation
          rule 7 requires. The two are recorded distinctly because they mean opposite things.
      (e) An admitted key that is REVOKED or EXPIRED is excluded from the returned VALID set. It
          stays in the admission graph (so what it lawfully admitted before is judged by (d)), but
          nothing it signs verifies.
    """
    errors: list = []
    keys = [k for k in (trust_root or {}).get("keys") or [] if isinstance(k, dict)]
    if not keys:
        return {}, ["trust root declares no keys — an empty trust root trusts nothing (it is not "
                    "an absent constraint)"]

    by_fp: dict = {}
    for entry in keys:
        declared = str(entry.get("fingerprint") or "").strip()
        actual = key_fingerprint(str(entry.get("public_key") or ""))
        if not declared or actual is None:
            errors.append(f"trust-root entry {declared or '<unnamed>'!r}: its public key does not "
                          f"read as a key, so its identity cannot be established")
            continue
        if declared != actual:
            errors.append(f"trust-root entry declares fingerprint {declared} but its public key "
                          f"hashes to {actual} — the key body was substituted under an untouched "
                          f"fingerprint line")
            continue
        by_fp[declared] = entry

    anchor_entry, anchor_errors = resolve_anchor_entry(trust_root, anchor)
    if anchor_entry is None:
        return {}, errors + anchor_errors
    anchor_fp = str(anchor_entry.get("fingerprint") or "").strip()
    if anchor_fp not in by_fp:
        return {}, errors + [f"the anchor entry {anchor_fp} did not survive the per-entry key checks"]

    admitted = {anchor_fp: by_fp[anchor_fp]}
    pending = {fp: e for fp, e in by_fp.items() if fp != anchor_fp}
    progressed = True
    while pending and progressed:
        progressed = False
        for fp in sorted(pending):
            entry = pending[fp]
            admitter_fp = str(entry.get("admitted_by") or "").strip()
            if admitter_fp not in admitted:
                continue
            if admitter_fp in revoked:
                errors.append(f"trust-root key {fp} was admitted by {admitter_fp}, which is REVOKED "
                              f"({revoked[admitter_fp].get('reason') or 'no reason recorded'}) — a "
                              "compromised key's issuances are refused with it (revocation cascades; "
                              "an ordinary retirement does not)")
                pending.pop(fp)
                progressed = True
                break
            admitter = admitted[admitter_fp]
            if not admission_window_covers(admitter, entry, anchor_fp=anchor_fp):
                errors.append(
                    f"trust-root key {fp} claims to have entered at "
                    f"{str(entry.get('valid_from') or '') or '<unset>'}, but its admitter "
                    f"{admitter_fp} had already reached its recorded validity end "
                    f"{str(admitter.get('valid_until') or '')} — a key whose validity has lapsed does "
                    "not go on admitting fresh signers (SPEC-0195 rule 7: a transition is signed by a "
                    "STILL-VALID key)")
                pending.pop(fp)
                progressed = True
                break
            signature = str(entry.get("transition_signature") or "").encode("utf-8")
            ok = verify_blob(transition_record(entry), signature,
                             allowed_signers_text([admitter]))
            if not ok:
                errors.append(f"trust-root key {fp} carries no valid rotation transition signed by "
                              f"{admitter_fp} — a key does not enter the trust root by appearing in "
                              "the file (SPEC-0195 rule 7, rotation)")
                pending.pop(fp)
                progressed = True
                break
            admitted[fp] = entry
            pending.pop(fp)
            progressed = True
            break
    for fp in sorted(pending):
        errors.append(f"trust-root key {fp} chains to no admitted key (`admitted_by: "
                      f"{str(pending[fp].get('admitted_by') or '') or '<unset>'}`) — it reaches the "
                      "out-of-band anchor through no signed transition")

    valid = {}
    for fp, entry in admitted.items():
        if fp in revoked:
            continue
        # THE ANCHOR'S OWN `valid_until` IS NOT ENFORCED, deliberately (audit-post finding 2's
        # corollary). Nothing signs the anchor entry — it is the root, admitted by the adopter's
        # out-of-band fingerprint — so a `valid_until` on it is UNAUTHENTICATED file content, and
        # enforcing an unauthenticated field would let whoever controls the mirror expire the root
        # of trust. The anchor is retired the only way a pinned-out-of-band value can be: the
        # adopter pins a new one (the procedure the published policy states).
        if fp != anchor_fp and _expired(entry, now):
            continue
        valid[fp] = entry
    return valid, errors


# ── The GATE: verify before any write (SPEC-0195 rule 6) ─────────────────────────────────────────

class ReleaseVerdict:
    """The gate's answer: `ok` plus the REASONS it refused — never a bare boolean.

    A refusal that cannot say why is the same defect as a silent pass one layer down: the operator
    then guesses, and the cheapest guess is "try again without the check".
    """

    __slots__ = ("ok", "reasons", "manifest", "signing_key", "tree", "exec_paths")

    def __init__(self, ok: bool, reasons: list, manifest=None, signing_key=None, tree=None,
                 exec_paths=None):
        self.ok = ok
        self.reasons = reasons
        self.manifest = manifest
        self.signing_key = signing_key
        # THE EXACT BYTES THAT WERE VERIFIED (audit-post finding 4). An installer that re-read the
        # mirror after verifying would write bytes nobody checked — a source that can change between
        # the two reads makes "verify before any write" verify a DIFFERENT tree from the one that
        # lands. So the gate hands back its own snapshot and the installer writes that.
        self.tree = tree
        # THE MODES OF THAT SAME SNAPSHOT (T-12316) — the rel-paths that were executable when the
        # bytes above were read, collected in the same pass. It rides the verdict for the same
        # reason `tree` does: the installer must not have to ask the mirror a second question.
        # NONE MEANS "NOT CAPTURED", AND THE FAIL-SAFE READING IS AN EMPTY SET — a verdict built
        # without it installs everything non-executable, i.e. degrades to the pre-T-12316 behaviour
        # rather than to an elevated mode nobody vouched for.
        self.exec_paths = exec_paths

    def __bool__(self):
        return self.ok


# The ONE set of path components that are NEVER release content (T-12174). It is the sibling of
# `tree_digest`'s `excludes` one layer out: `excludes` names the published files a digest must not
# fold (the manifest describes the digest, so it cannot be in it), and this names the things that
# are not published files at all — the destination's own history, and whatever an interpreter
# dropped there. It lives beside its ONLY consumer, the non-git fallback read below, rather than
# beside `excludes`, so that adding it does not disturb the code span an unrelated spec anchors.
# A git checkout never consults it: the index answers the same question exactly.
NON_ARTIFACT_COMPONENTS = (".git", "__pycache__", "*.pyc")


def _is_non_artifact(rel: str) -> bool:
    """True when any COMPONENT of `rel` is one of NON_ARTIFACT_COMPONENTS (leaf globs included)."""
    return any(fnmatch.fnmatch(part, pat)
               for part in rel.split("/") for pat in NON_ARTIFACT_COMPONENTS)


def read_tracked_release_tree(root: Path, *, exec_paths: "set | None" = None) -> "dict | None":
    """The TRACKED tree of the git checkout at `root` as {rel_path: bytes}, or None if it is not one.

    Deliberately NOT routed through `_run_git_cap`: the same bytes-not-text reason `_git_blob` gives,
    plus `ls-files -z` output is NUL-delimited.

    The path LIST comes from the INDEX (`git ls-files`) and the CONTENT from the WORKING TREE, and
    both halves of that are load-bearing:

      * the index is what makes an ADDED-and-`git add`-ed file part of the tree, so planting a file
        in the release is refused rather than ignored;
      * the working tree is what makes a MODIFIED tracked file visible at all — digesting HEAD's
        blobs instead would re-derive the published bytes no matter what the destination actually
        holds, i.e. it would verify the wrong thing. A tracked path missing from the working tree
        (deleted) simply drops out, which moves the digest and refuses just the same.

    What this REMOVES is only what was never published: an untracked or ignored file — `__pycache__`
    written by merely running the engine from inside a clone — no longer enters the digest and can no
    longer invalidate an intact artifact (the measured 27ce33926fa8-vs-066d7e75b855 refusal on the
    v2.0.0 mirror, 2026-09-05).

    `exec_paths`, when given, collects the rel-paths that are EXECUTABLE (T-12316) — filled IN THIS
    SAME PASS, from the path already in hand, so the mode is part of the same snapshot as the bytes.
    See `read_release_tree` for why that matters; the return contract is unchanged either way.
    """
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    root = Path(root)
    top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, env=_git_env._git_child_env())
    if top.returncode != 0:
        return None
    # The toplevel must be `root` ITSELF. A plain unpacked copy sitting anywhere inside an unrelated
    # repository would otherwise be read through THAT repository's index — a tree with nothing to do
    # with the artifact under the path we were handed.
    try:
        if Path(top.stdout.strip()).resolve() != root.resolve():
            return None
    except OSError:
        return None
    listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True,
                            env=_git_env._git_child_env())
    if listed.returncode != 0:
        return None
    tree = {}
    for raw in listed.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "surrogateescape")
        path = root / rel
        if path.is_symlink() or not path.is_file():
            continue
        tree[rel] = path.read_bytes()
        if exec_paths is not None and path.stat().st_mode & 0o111:
            exec_paths.add(rel)
    return tree


def read_release_tree(root: Path, *, exec_paths: "set | None" = None) -> dict:
    """The published tree under `root` as {rel_path: bytes} — what was RELEASED, nothing else.

    A git checkout (every mirror clone, and every destination `work publish` writes) answers that
    exactly: the TRACKED tree, read by `read_tracked_release_tree`. Anything else is an unpacked
    copy with no index to ask, so it falls back to walking the filesystem minus
    `NON_ARTIFACT_COMPONENTS` — the same answer, approximated by the only means available.

    `.git` is excluded on both paths: it is the DESTINATION's own history, not release content —
    publish never writes it and the digest never covered it, so a verifier that folded it in would
    fail every real mirror.

    MODE TRAVELS WITH THE SNAPSHOT (T-12316). `exec_paths`, when a caller passes a set, is filled
    with the rel-paths whose file is EXECUTABLE — read on BOTH legs in the SAME pass as the bytes,
    off the path already in hand. That co-location is the whole point rather than a convenience: an
    installer that asked the mirror about modes AFTER this read would be making a SECOND read of a
    subject that can change in between, which is exactly what `verify_release`'s one-read comment
    below says a verifier must not do. The mode is not in the digest and never was (T-12172 AC2), so
    it is not VERIFIED bytes — but it is at least the SAME snapshot's answer, taken once.

    The parameter is opt-in and the return contract is unchanged (`{rel: bytes}`): a caller that does
    not ask for modes reads exactly what it read before. `st_mode & 0o111` rather than
    `os.access(X_OK)` — the FILE's mode, not the calling process's permission on it, so the answer
    does not depend on who is running.
    """
    root = Path(root)
    tracked = read_tracked_release_tree(root, exec_paths=exec_paths)
    if tracked is not None:
        return tracked
    tree = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if _is_non_artifact(rel):
            continue
        tree[rel] = path.read_bytes()
        if exec_paths is not None and path.stat().st_mode & 0o111:
            exec_paths.add(rel)
    return tree


def verify_release(dest, anchor: str, *, now: "str | None" = None) -> ReleaseVerdict:
    """THE gate — the one function every install/update entrypoint calls before it writes anything.

    Ordered so that nothing is trusted before the thing that vouches for it, which is the only
    ordering the bootstrap problem admits:

      1. the manifest is present and parses;
      2. the trust root and the revocation list are present and parse (an unreadable revocation list
         REFUSES — treating it as "nothing revoked" would be a one-byte bypass);
      3. the trust root validates against the OUT-OF-BAND anchor (`validate_trust_root`) — the
         first-install boundary, and the only step whose authority comes from outside the mirror;
      4. the detached manifest signature exists; the key that made it is resolved WITHOUT trusting
         it, so a REVOKED signer can be refused BY NAME; then it must be in the valid set and the
         signature must verify over the manifest's exact bytes;
      5. the tree is re-digested and compared with the (now authenticated) `tree_digest`.

    An UNSIGNED release is refused at step 4. Rule 6 says every entrypoint verifies before any
    write and there is no internal shortcut — so an artifact with no signature is simply not
    installable, by anybody, including the workshop's own machines.

    PURE: it reads and judges. It writes nothing, which is what lets an entrypoint call it before
    touching its destination — and lets a caller re-verify an already-materialised tree for free.
    """
    dest = Path(dest)
    now = now or _utc_now()
    reasons: list = []

    # ONE READ, AND EVERYTHING BELOW DECIDES ON IT (audit-post finding 1, second pass). The gate used
    # to read the manifest, the trust root, the revocation list, both signatures and the tree as six
    # independent reads of a source that can change underneath it — so the manifest it verified was
    # not provably the manifest in the snapshot it digested, nor the snapshot the installer writes.
    # A verifier that reads its subject more than once is verifying a sequence of possibly-different
    # subjects; taking the snapshot first collapses that to a single object, and `verdict.tree` hands
    # the SAME object to the installer.
    # The modes ride along on that ONE read (T-12316), so the installer never has to ask the mirror
    # a second question — see `read_release_tree`.
    snapshot_exec: set = set()
    snapshot = read_release_tree(dest, exec_paths=snapshot_exec)

    manifest = _parse_yaml_blob(snapshot.get(MANIFEST_FILENAME))
    if manifest is None:
        return ReleaseVerdict(False, [
            f"{dest} carries no readable {MANIFEST_FILENAME} — an artifact with no manifest is not "
            "a release (SPEC-0195 rule 5), so there is nothing to verify AGAINST"])

    trust_root = read_trust_root(snapshot)
    if trust_root is None:
        reasons.append(f"{dest} carries no readable {TRUST_ROOT_FILENAME} — the set of currently "
                       "valid keys is published IN the mirror and verified against the anchor "
                       "(SPEC-0195 rule 7); without it nothing can be trusted")
    revocations = read_revocations(snapshot)
    if revocations is None:
        reasons.append(f"{dest} carries no readable {REVOCATION_FILENAME} — an unreadable "
                       "revocation list is NOT an empty one: reading it as 'nothing is revoked' "
                       "would make revocation a one-byte bypass")
    if reasons:
        return ReleaseVerdict(False, reasons, manifest=manifest)

    # THE REVOCATION LIST IS AUTHENTICATED BY THE ANCHOR, BEFORE IT IS USED — and specifically NOT
    # by "any currently valid key" (audit-post finding 1). The attack that forces this: a revoked
    # key that controls the mirror deletes its own revocation row and re-signs everything with
    # itself. Any rule that lets the release signer also vouch for the revocation list hands that
    # attacker the very statement that disqualifies them. The ANCHOR is the only key the adopter
    # knows independently of the mirror, so revocation is an anchor-level statement.
    #
    # THE BOUND, stated rather than hidden: this cannot revoke the ANCHOR itself — a compromised
    # root cannot sign its own disqualification. That case is not a gap here, it is the documented
    # lost-anchor path in the published policy (revoke -> issue -> re-sign -> re-pin, with a NEW
    # out-of-band fingerprint), and it is why the overlap window exists.
    anchor_entry, anchor_errors = resolve_anchor_entry(trust_root, anchor)
    if anchor_entry is None:
        return ReleaseVerdict(False, anchor_errors, manifest=manifest)
    revocation_signature = snapshot.get(REVOCATION_SIGNATURE_FILENAME) or b""
    revocation_bytes = snapshot.get(REVOCATION_FILENAME) or b""
    if not verify_blob(revocation_bytes, revocation_signature, allowed_signers_text([anchor_entry])):
        return ReleaseVerdict(False, [
            f"{REVOCATION_FILENAME} is not signed by the ANCHOR key {anchor} (its "
            f"{REVOCATION_SIGNATURE_FILENAME} is missing or does not verify) — the revocation list "
            "must be authenticated INDEPENDENTLY of whoever signed the release, or a revoked key "
            "that controls this mirror would simply delete its own revocation row and re-sign"],
            manifest=manifest)

    revoked = revoked_fingerprints(revocations)
    valid, errors = validate_trust_root(trust_root, anchor, revoked, now=now)
    if errors:
        return ReleaseVerdict(False, errors, manifest=manifest)
    if not valid:
        return ReleaseVerdict(False, [
            "the trust root chains correctly to the anchor but holds NO currently valid key — every "
            "admitted key is revoked or past its recorded validity end, so no signature can verify"],
            manifest=manifest)

    signature = snapshot.get(SIGNATURE_FILENAME) or b""
    if not signature.strip():
        return ReleaseVerdict(False, [
            f"{dest} carries no {SIGNATURE_FILENAME} — every release is SIGNED and every entrypoint "
            "verifies before any write, with no internal shortcut (SPEC-0195 rule 6). An unsigned "
            "artifact is not installable by anybody, including the publisher's own machines"],
            manifest=manifest)

    manifest_bytes = snapshot.get(MANIFEST_FILENAME) or b""
    signer = signing_key_fingerprint(manifest_bytes, signature)
    if signer is None:
        return ReleaseVerdict(False, [
            f"the signature in {SIGNATURE_FILENAME} does not check out against {MANIFEST_FILENAME} "
            "at all — it names no key, so the manifest was altered after signing or the signature "
            "was made over other bytes"], manifest=manifest)
    if signer in revoked:
        row = revoked[signer]
        return ReleaseVerdict(False, [
            f"this release is signed by REVOKED key {signer} — revoked "
            f"{row.get('revoked_at') or '(no date recorded)'}: "
            f"{row.get('reason') or '(no reason recorded)'}. Refused on the ordinary install path "
            "(SPEC-0195 rule 7, revocation)"], manifest=manifest, signing_key=signer)
    if signer not in valid:
        return ReleaseVerdict(False, [
            f"this release is signed by {signer}, which is not a currently valid key in the trust "
            "root chained to the anchor (it is absent, unadmitted, or past its recorded validity "
            "end)"], manifest=manifest, signing_key=signer)
    if not verify_blob(manifest_bytes, signature, allowed_signers_text(list(valid.values()))):
        return ReleaseVerdict(False, [
            f"the signature by {signer} does not verify over {MANIFEST_FILENAME}'s bytes"],
            manifest=manifest, signing_key=signer)

    excludes = [str(x) for x in (manifest.get("digest_excludes") or [MANIFEST_FILENAME])]
    recomputed = tree_digest(snapshot, excludes=excludes)
    declared = str(manifest.get("tree_digest") or "")
    if recomputed != declared:
        return ReleaseVerdict(False, [
            f"the published bytes do not match the signed manifest's digest — manifest says "
            f"{declared[:16] or '<unset>'}…, the tree hashes to {recomputed[:16]}…. A published "
            "artifact whose bytes do not match its manifest's digest is not a release "
            "(SPEC-0195 rule 5)"], manifest=manifest, signing_key=signer)

    return ReleaseVerdict(True, [], manifest=manifest, signing_key=signer, tree=snapshot,
                          exec_paths=snapshot_exec)


def _utc_now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── The PUBLISHED policy + notes text (SPEC-0195 rules 6 + 7) ────────────────────────────────────

def build_security_policy() -> str:
    """The mirror's SECURITY.md — the trust model in plain words, with the lost-key procedure.

    Rule 7 requires the loss-recovery procedure to be WRITTEN in the mirror's policy, "not
    improvised". The four ordered steps come from `LOST_KEY_RECOVERY_STEPS`, the single carrier
    `security_policy_missing_steps` reads back — so the published text and the check that it is
    complete cannot drift apart (CHARTER §P5).

    Provider-neutral by construction: it describes an anchor, a trust root, transitions and a
    revocation list, and names no signing tool (CHARTER §P4b).
    """
    steps = "\n".join(f"{i}. **{name.upper()}** — {text}"
                      for i, (name, text) in enumerate(LOST_KEY_RECOVERY_STEPS, start=1))
    return f"""# Security policy

GENERATED by `yitc-v2 work publish` (SPEC-0195 rules 6 + 7); do not edit in the mirror — the
workshop re-publishes it.

## What is signed

Every release is signed. The signature target is `{MANIFEST_FILENAME}`, and the manifest carries the
digest of the whole artifact tree — so signing one small file covers every published byte. The
detached signature is `{SIGNATURE_FILENAME}` beside it.

## Verify before you write

Every supported install or update entrypoint verifies the signature against the trust root BEFORE it
writes anything. There is no internal shortcut: the maintainer's own machines install through the
same verifying path an outsider uses. The supported entrypoints are enumerated in
`{RELEASE_NOTES_FILENAME}`; driving any of them with a tampered artifact refuses.

## First install — the out-of-band anchor

The mirror cannot vouch for itself. At the first install you pin an ANCHOR — the trust-root key
fingerprint, published on a channel INDEPENDENT of this mirror — and pass it by hand:

    yitc-v2 release install <mirror> --into <path> --anchor SHA256:<fingerprint>

`{TRUST_ROOT_FILENAME}` is then verified against that anchor before anything else is trusted. A
mirror whose trust root has been tampered with is refused at this boundary.

## Trust root, rotation, revocation

* `{TRUST_ROOT_FILENAME}` publishes the currently valid keys. Exactly one is the ANCHOR; every other
  key is admitted only by a ROTATION TRANSITION signed by a key that was still valid — a key does
  not become trusted by appearing in the file.
* A rotation declares an OVERLAP WINDOW and records the retired key's validity END (`valid_until`),
  which is enforced at verification, not merely recorded.
* `{REVOCATION_FILENAME}` publishes revocations, and is itself SIGNED BY THE ANCHOR KEY
  (`{REVOCATION_SIGNATURE_FILENAME}`) — deliberately not by whoever signed the release, because a
  revoked key that controls this mirror would otherwise delete its own revocation row and re-sign.
  A release signed by a revoked key is refused on the ordinary install path, and the refusal names
  the revocation. Revocation CASCADES — a key admitted by a revoked key is refused with it — while
  an ordinary retirement does not. The anchor cannot revoke ITSELF: a compromised root is handled by
  the recovery procedure below, which ends in a NEW out-of-band anchor.

## Lost or compromised key — the recovery procedure

{steps}

## Reporting

Report a suspected key compromise or a signature that fails to verify through the intake described
in this mirror's contribution policy. Do not install an artifact that failed verification.
"""


def security_policy_missing_steps(text: str) -> list:
    """Which lost-key recovery steps are ABSENT from a published security policy text.

    The checker AC6 drives, so the probe perturbs the SUBJECT (remove a step from the rendered
    policy and this names it) rather than deleting an assertion — the sound differential shape
    SPEC-0165 item 3 requires.
    """
    body = (text or "").lower()
    return [name for name, _ in LOST_KEY_RECOVERY_STEPS if f"**{name.upper()}**".lower() not in body]


_INVENTORY_HEADING = "## Verifying entrypoint inventory"
_INVENTORY_ROW_PREFIX = "- `"
_AUDITOR_SETUP_HEADING = "## External auditor setup"
_UPDATING_HEADING = "## Updating from the previous release"


def render_change_list(changes) -> str:
    """The «What changed» section (T-12391): one line per kernel-realm task closed since the last tag.

    `changes` is what `collect_change_list` returns — `None` for a first release, else a tuple of
    `(task_id, title, class, closed_at)` already in close order; each line ends with the card's
    `task_closed` locator so a reader can resolve the closure it cites (T-13001). The identity strip runs over the TITLE only:
    the strip erases task ids by design (it launders dev provenance out of prose), so running it over
    the whole line would publish a list with no ids in it. The id is printed verbatim instead.
    """
    lines = ["## What changed", ""]
    if changes is None:
        lines += ["This is the first release — there is no previous tag to compare against."]
        return "\n".join(lines) + "\n"
    changes = tuple(changes)
    if not changes:
        lines += ["No kernel task was closed since the previous release tag."]
        return "\n".join(lines) + "\n"
    lines += [f"{len(changes)} task(s) closed since the previous release tag, in close order:", ""]
    for tid, title, klass, closed_at in changes:
        clean = " ".join(graph_lib._release_view_strip(str(title or "")).split())
        lines.append(f"- {tid} — {clean} ({klass or 'unclassified'}) — events.jsonl#ts={closed_at}")
    return "\n".join(lines) + "\n"


def _active_specs(tree: dict) -> dict:
    """`{spec_id: parsed spec}` for every `status: active` spec file in a release-cut tree.

    A continuation part and the template-owned scaffold are not specs of their own (the same two
    exclusions `cut_release_tree` makes). A spec that will not parse raises `ValueError`: an
    unreadable spec cannot be judged new-or-not, and each caller says so rather than guessing.
    """
    out = {}
    for rel in sorted(tree):
        if not (rel.startswith("specs/") and rel.endswith(".yaml")) or rel in TEMPLATE_OWNED_SURFACE \
                or _spec_part_base(rel):
            continue
        try:
            data = state.load_str(tree[rel].decode("utf-8")) or {}
        except Exception as exc:
            raise ValueError(f"{rel} does not parse ({exc.__class__.__name__})") from exc
        if isinstance(data, dict) and data.get("status") == "active" and data.get("id"):
            out[str(data["id"])] = data
    return out


def _capability_turn_on(sid: str, data: dict) -> "str | None":
    """Where a project turns the capability on, read from the spec's own declarations, or `None`.

    In order: the spec's `turn_on` line (SPEC-0030); else the declaration key of each concern the
    spec hosts (`carrier_path` + `declare_key`, SPEC-0128); else, for an adoptable extension
    (SPEC-0101), its adoption entry. `None` when the spec declares none of them. That absence says
    nothing about whether a project must opt in — the renderer says the line is not declared and
    points at the contract, never that the capability applies on its own.
    """
    turn_on = data.get("turn_on")
    if isinstance(turn_on, str) and turn_on.strip():
        return " ".join(turn_on.split())
    blocks = data.get("concern")
    keys = []
    for b in (blocks if isinstance(blocks, list) else [blocks]):
        if isinstance(b, dict) and isinstance(b.get("carrier_path"), str) \
                and isinstance(b.get("declare_key"), str) and b["carrier_path"] and b["declare_key"]:
            keys.append(f"`{b['carrier_path']}.{b['declare_key']}`")
    if keys:
        return "yitc-ops.yaml " + ", ".join(keys)
    if data.get("extension") == "adoptable":
        return f"yitc-ops.yaml `extensions.adopts[]` — an entry naming {sid}"
    return None


def capabilities_to_consider(new_tree: dict, old_tree: dict) -> tuple:
    """The kernel specs that became active between two release cuts (T-13629) — the ONE derivation.

    `new_tree` and `old_tree` are release cuts (`cut_release_tree`, or two verified published
    releases, which are such cuts), so every spec in them already passed the release predicate:
    kernel realm and `status: active` at that commit. A spec is listed when it is active in the new
    cut and NOT active in the old one — absent there, or there under another status. Returns
    `(spec_id, title, turn_on)` rows in id order; the title is identity-stripped like the «What
    changed» titles. Both the release notes and the end of `release update` render THIS tuple.
    """
    new, old = _active_specs(new_tree), _active_specs(old_tree)
    return tuple((sid, " ".join(graph_lib._release_view_strip(str(new[sid].get("title") or "")).split()),
                  _capability_turn_on(sid, new[sid]))
                 for sid in sorted(set(new) - set(old)))


def capability_lines(caps, indent: str = "") -> list:
    """The per-capability lines both renderings print — one home for their wording."""
    lines = []
    for sid, title, turn_on in caps:
        lines.append(f"{indent}- {sid} — {title}")
        lines.append(f"{indent}  turn on: {turn_on}" if turn_on else
                     f"{indent}  turn on: not declared by the spec — read its contract for whether and how "
                     "a project opts in")
        lines.append(f"{indent}  read: `yitc-v2 graph query --kernel {sid}`")
    return lines


def render_capabilities(caps) -> str:
    """The «Capabilities to consider» section of RELEASE-NOTES.md (T-13629), above «What changed»."""
    lines = ["## Capabilities to consider", ""]
    if caps is None:
        lines += ["This is the first release — there is no previous tag to compare against."]
        return "\n".join(lines) + "\n"
    caps = tuple(caps)
    if not caps:
        lines += ["No kernel spec became active since the previous release tag."]
        return "\n".join(lines) + "\n"
    lines += [f"{len(caps)} kernel spec(s) became active since the previous release tag — capabilities "
              "this release adds. Each names where a project turns it on and how to read its contract:",
              ""]
    return "\n".join(lines + capability_lines(caps)) + "\n"


def build_release_notes(tag: str, source_sha: str, answers, changes=None, capabilities=None) -> str:
    """The mirror's RELEASE-NOTES.md — the ONE COMPOSED WRITER of that published file.

    TWO active rules land on this ONE published filename and BOTH sections are required, so one
    function composes them instead of each rule writing the file:

      SPEC-0197 rule 4  the `answers:` LINK-BACK list — rendered by `render_release_notes` (T-12048),
                        called here VERBATIM and used as the head of the file.
      T-13629           the CAPABILITIES TO CONSIDER section — the kernel specs that became active
                        since the previous tag (`capabilities_to_consider`), above «What changed».
      SPEC-0195 rule 6  the ENUMERATED VERIFYING-ENTRYPOINT INVENTORY — appended below it.
      T-13220           the UPDATING FROM THE PREVIOUS RELEASE section — the kept-tree layout an
                        update needs (the new clone AND the old tree as `--from-release`), last.
      T-12176           the EXTERNAL AUDITOR SETUP section — the per-machine auditor binding, which
                        this release deliberately ships NO path to, so an adopter has to be told how
                        to bind one. It sits AFTER the inventory: `parse_entrypoint_inventory` stops
                        at the next `## ` heading, so this section closes the inventory rather than
                        leaking rows into it.

    COMPOSED, not ordered. Two attachers each assigning `out[RELEASE_NOTES_FILENAME]` is a
    LAST-ONE-WINS clobber and it is SILENT: the publish succeeds, the digest covers the survivor,
    and the loser's rule ships in no mirror at all. Measured both orderings before writing this —
    each drops the other rule's test. So the cut takes exactly one assignment (in
    `_add_trust_surfaces`) of exactly one composed value, and `answers` is threaded in from the
    publish seam rather than re-derived here.

    The inventory is rendered from `ENTRYPOINT_INVENTORY` and read back by
    `parse_entrypoint_inventory`, so the published list and the code's list are one carrier. That is
    what lets AC4 read the inventory FROM THE NOTES instead of hard-coding it: the test drives
    whatever the release claims to support, which is the only reading under which "an unenumerated
    path is a gap in the inventory" is a findable statement.

    THE NOTES DO NOT REPEAT THE TREE DIGEST. The manifest is its single home (CHARTER §P5), and a
    second copy here would be both a drift risk and a self-reference — the notes are themselves
    inside the digested tree, so a digest printed in them could never describe the tree they are
    part of. They point at the manifest instead.
    """
    rows = "\n".join(f"- `{name}` — `{usage}`\n  {note}" for name, usage, note in ENTRYPOINT_INVENTORY)
    head = render_release_notes(tag=tag, source_sha=source_sha, answers=answers)
    return head + "\n" + render_capabilities(capabilities) + "\n" + render_change_list(changes) + f"""
## Trust surfaces

GENERATED by `yitc-v2 work publish`; do not edit in the mirror.

* artifact tree digest: see `tree_digest` in `{MANIFEST_FILENAME}` — its single home
* signature target: `{MANIFEST_FILENAME}` (detached signature: `{SIGNATURE_FILENAME}`)
* trust root: `{TRUST_ROOT_FILENAME}` · revocations: `{REVOCATION_FILENAME}` (anchor-signed:
  `{REVOCATION_SIGNATURE_FILENAME}`) · policy: `{SECURITY_POLICY_FILENAME}`

{_INVENTORY_HEADING}

Every entrypoint below verifies the signed manifest against the trust root — anchored out of band —
BEFORE it writes anything. Driving any of them with a tampered artifact refuses. A path that
installs or updates this release and is NOT listed here is a gap in this inventory (SPEC-0195
rule 6).

{rows}

### Running these on a clean machine

Both entrypoints run on a machine that has never used this system: no session, no journal, no
prior setup of any kind. Run them straight out of the clone, using the engine the release itself
ships:

```
python3 <dest>/bin/yitc-v2 release verify <dest> --anchor SHA256:<fingerprint>
python3 <dest>/bin/yitc-v2 release install <dest> --into <path> --anchor SHA256:<fingerprint>
```

`<dest>` is your local clone of this mirror; the anchor fingerprint comes from a channel
INDEPENDENT of the mirror. Nothing else needs to exist first.

What `release verify` writes, stated exactly: NOTHING into `<dest>`, and it never CREATES a
journal anywhere — so on a clean machine it writes nothing at all, which is what makes it safe to
run before you have decided to trust this release. The one thing it may write is a single
`release_verified` provenance row, appended on refusal as well as on success, and ONLY to a
governed journal that ALREADY EXISTS on some checkout OTHER than the release itself. A journal
found inside `<dest>` is never written to, whatever it contains — so running the command from
inside your clone, as above, still writes nothing into it. A clean adopter machine has no such
journal anywhere, so no row is written and the command says so on stderr.

These two are the only commands that run without any prior setup: every other command in this
engine requires a set-up working copy and will tell you so.

## Bootstrap order on a clean machine

`{BOOTSTRAP_ORDER_DOC}` (in this release) carries the order the primary AI reads on a machine that
has nothing on it yet: prerequisites with their check commands, clone -> `release verify` ->
`release install`, `init`, the `yitc-ops.yaml` kernel pin, the external-auditor install + binding,
and the first session. Take the anchor and the three commands above from the org-profile README --
the independent channel -- not from this mirror.

{_AUDITOR_SETUP_HEADING}

The lifecycle runs an EXTERNAL auditor at Audit-pre and Audit-post; `audit pre|post` refuses rather
than running unaudited when it cannot find one. The auditor binary is a PER-MACHINE binding — this
release ships no path to one — so bind it once on each machine, by whichever of these fits:

- install an external auditor CLI so its executable is on `PATH`, and log the CLI in to your own
  subscription. This is the ordinary route and needs no configuration in this release at all;
- point `YITC_CODEX_AUDIT_BIN` at the executable, for an auditor deliberately installed off `PATH`.

Both routes are MACHINE-scoped, and deliberately so. `bin/audit-config.yaml` also carries a
`codex_binary:` key, read as a last resort, but it is NOT the route to reach for: that file travels
in every release, so a path written there is inherited by everyone who adopts your copy of it — and
a per-user path is rejected by this release's own host-literal check.

Unbound, the resolver names both routes in its refusal rather than failing obscurely at spawn.
The tier bindings in `bin/audit-config.yaml` (which auditor, which model, which effort) are this
release's defaults and are yours to change; the lifecycle's normative text names no provider.

{_UPDATING_HEADING}

An update needs TWO trees on disk at once: this release, and the release you run today as the
`--from-release` merge base. One clone cannot be both, so keep the release you run today as a
worktree BESIDE the clone, then move the clone forward (rehearsed v2.0.5 -> v2.0.6 on a clean
environment):

```
git -C <dest> worktree add <dest>-<old-tag> <old-tag>
git -C <dest> fetch --tags
git -C <dest> checkout <new-tag>
python3 <dest>/bin/yitc-v2 release verify <dest> --anchor SHA256:<fingerprint>
python3 <dest>/bin/yitc-v2 release update <dest> --into <engine-dir> --anchor SHA256:<fingerprint> --from-release <dest>-<old-tag>
```

`<dest>` is the clone you installed from, `<old-tag>` the release you run today, `<new-tag>` this
release, `<engine-dir>` your existing install. Keep `<dest>-<old-tag>` until the update is settled:
it is the merge base and your way back. Afterwards move the `kernel:` pin in each project's
`yitc-ops.yaml` to `<new-tag>` and run `yitc-v2 -C <project> init`, which adds only what is missing.

What the version digits tell you (SPEC-0195 rule 10): LAST digit (v2.1.0 -> v2.1.1) = fixes only,
you do nothing on update; MIDDLE digit (v2.0.6 -> v2.1.0) = behaviour or what `init` writes changes,
or you are asked to act — read these notes first; FIRST digit = a new methodology generation.
"""


def parse_entrypoint_inventory(notes_text: str) -> list:
    """The entrypoint NAMES a published release claims to support, read out of its release notes.

    Reads the section `build_release_notes` writes, taking the first backticked token of each row.
    Returns [] when the section is absent — and the caller treats an EMPTY inventory as a failure
    rather than as "nothing to check", because a release that enumerates no verifying entrypoint has
    not satisfied rule 6 (SPEC-0165 item 11: absence is not evidence).
    """
    names, inside = [], False
    for line in (notes_text or "").splitlines():
        if line.startswith(_INVENTORY_HEADING):
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if inside and line.startswith(_INVENTORY_ROW_PREFIX):
            rest = line[len(_INVENTORY_ROW_PREFIX):]
            name = rest.split("`", 1)[0].strip()
            if name:
                names.append(name)
    return names


# ── The two CONSUMER ENTRYPOINTS (the enumerated inventory) ──────────────────────────────────────

def _print_refusal(verdict: ReleaseVerdict, dest) -> None:
    print(f"RELEASE VERIFY: REFUSED — {dest}")
    for reason in verdict.reasons:
        print(f"  - {reason}")


def cmd_release_verify(args, *, _append_event, _die) -> None:
    """`release verify <dest> --anchor <fingerprint>` — the gate, invoked on its own.

    Writes NOTHING under any outcome, which is why it is the cheapest way to answer "is this mirror
    good?" before committing to an install.
    """
    dest = Path((getattr(args, "dest", None) or "").strip()).expanduser()
    anchor = (getattr(args, "anchor", None) or "").strip()
    if not anchor:
        _die("release verify: --anchor SHA256:<fingerprint> required — the OUT-OF-BAND trust anchor, "
             "taken from a channel INDEPENDENT of this mirror (SPEC-0195 rule 7). Without it the "
             "mirror would be vouching for itself, which is the one thing the anchor exists to stop.")
    if not dest.is_dir():
        _die(f"release verify: {dest} is not an existing directory")

    verdict = verify_release(dest, anchor)
    _append_event("release_verified", None, {
        "destination": str(dest), "anchor": anchor, "ok": verdict.ok,
        "signing_key": verdict.signing_key,
        "tag": (verdict.manifest or {}).get("source_ref"),
        "reasons": verdict.reasons,
    })
    if not verdict.ok:
        _print_refusal(verdict, dest)
        _die("release verify: REFUSED (see the reasons above) — nothing was written.")
    m = verdict.manifest or {}
    print(f"RELEASE VERIFY: OK — {m.get('source_ref')} | digest "
          f"{str(m.get('tree_digest'))[:12]} | signed by {verdict.signing_key} | anchor {anchor}")


def cmd_release_install(args, *, _append_event, _die, _install_start_command=None) -> None:
    """`release install <dest> --into <path> --anchor <fp>` — verify FIRST, write only after.

    The refusal path touches `--into` in NO way: the gate runs to a verdict before the target is
    even opened, so a refused install leaves the destination byte-identical (SPEC-0195 rule 6 —
    "BEFORE any write", read literally). The ordering is the contract; the copy is incidental.
    """
    import shutil

    dest = Path((getattr(args, "dest", None) or "").strip()).expanduser()
    into = Path((getattr(args, "into", None) or "").strip()).expanduser()
    anchor = (getattr(args, "anchor", None) or "").strip()
    if not anchor:
        _die("release install: --anchor SHA256:<fingerprint> required — the OUT-OF-BAND trust "
             "anchor (SPEC-0195 rule 7); an install that let the mirror name its own authority "
             "would verify nothing.")
    if not dest.is_dir():
        _die(f"release install: {dest} is not an existing directory")
    if not str(into):
        _die("release install: --into <path> required (the directory the verified release is "
             "installed into)")

    verdict = verify_release(dest, anchor)
    # THE VERSION FLOOR (T-12045, SPEC-0195 rule 9) — evaluated HERE, between the signature gate and
    # the first write, because that is the only position where both facts exist and nothing has been
    # touched yet: the manifest is known only after the gate has authenticated it, and `into` is not
    # opened until below. So a floor refusal leaves the destination byte-identical for exactly the
    # same structural reason a signature refusal does — the ordering, not a cleanup path.
    #
    # The CONTENT is the mirror being installed; the ENGINE is the one running this command. Its
    # version is read from its OWN manifest, so an engine installed as a release knows its version
    # and a workshop engine honestly reports none (`engine-unknown`, which does not refuse).
    engine_manifest = read_manifest(running_engine_root())
    floor = check_version_floor(
        content_manifest=verdict.manifest,
        engine_version=str((engine_manifest or {}).get("source_ref") or ""),
        engine_manifest=engine_manifest)
    _append_event("release_installed", None, {
        "destination": str(dest), "into": str(into), "anchor": anchor,
        "ok": verdict.ok and floor.ok,
        "signing_key": verdict.signing_key,
        "tag": (verdict.manifest or {}).get("source_ref"),
        # The floor rides the EXISTING event rather than emitting a second one (CHARTER §P1 F2): the
        # question "did this install happen, and if not why" has one answer and one row.
        "floor_status": floor.status, "floor_required": floor.required,
        "reasons": verdict.reasons + ([] if floor.ok else [floor.detail]),
    })
    if not verdict.ok:
        _print_refusal(verdict, dest)
        _die(f"release install: REFUSED — NOTHING was written into {into}. A refused install leaves "
             "the destination exactly as it found it.")
    if not floor.ok:
        print(f"RELEASE INSTALL: REFUSED — {dest}")
        print(f"  - {floor.detail}")
        _die(f"release install: REFUSED on the version floor — NOTHING was written into {into}.")

    # The bytes written are the bytes VERIFIED: `verdict.tree` is the gate's own snapshot, so a
    # mirror that changes between the check and the copy cannot substitute what lands (finding 4).
    #
    # AND SO ARE THE MODES (T-12316). `write_bytes` creates 0644 and nothing chmod-ed afterwards, so
    # every installed file was non-executable and `<into>/bin/yitc-v2` exited 126 on the invocation
    # the README and the release notes tell an adopter to run — measured on the v2.0.1 clean-machine
    # proof, where the published clone beside it ran fine because `work publish` already carries the
    # source modes (T-12172). The set comes from the SAME snapshot as the bytes rather than from a
    # fresh look at the mirror, for the reason stated one layer down in `read_release_tree`.
    #
    # The chmod is EXPLICIT and two-valued, exactly as `_write_tree` writes the published tree: the
    # installed mode is then a function of the release alone, neither of the mirror's own permissions
    # (a 0600 mirror file would otherwise install unreadable) nor of the operator's umask. Mode is
    # not an input to `tree_digest` (T-12172 AC2), so none of this can move a published digest — the
    # gate above, the manifest and the digest are untouched.
    tree = verdict.tree or {}
    executable = verdict.exec_paths or set()
    into.mkdir(parents=True, exist_ok=True)
    for rel in sorted(tree):
        out = into / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(tree[rel])
        out.chmod(0o755 if rel in executable else 0o644)
    shutil.rmtree(into / "__pycache__", ignore_errors=True)
    m = verdict.manifest or {}
    print(f"release_installed: {m.get('source_ref')} -> {into} | {len(tree)} file(s) | "
          f"digest {str(m.get('tree_digest'))[:12]} | signed by {verdict.signing_key}")
    # T-13384 / T-13385 (SPEC-0086 rule 6f(d)) — the home start command, through init's ONE AI tool
    # list and writer — create, or refresh an engine-written file, T-13429 (injected by the host
    # residue; it reports and never raises), then
    # ONE plain next-step line naming each present tool's invocation, LAST, so a newcomer is never left
    # without a way to start.
    ready = _install_start_command(into) if _install_start_command is not None else None
    if ready:
        how = " or ".join(f"{invoke} in {label}" for label, invoke in ready)
        print(f"Next step: open your AI tool in your home folder and type {how} — it lists your "
              "projects and can create the first one.")


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# T-12048 — THE CONTRIBUTION SURFACES (SPEC-0197). A NEW, self-contained section: everything below
# is additive, and everything above is CONSUMED, never edited. In particular the manifest schema
# (`build_manifest` / `render_manifest` / `MANIFEST_FILENAME` / `TEMPLATE_OWNED_SURFACE`) and the
# digest (`tree_digest`) belong to T-12042 and are used here exactly as they are.
#
# WHAT THIS ADDS. Two published files, both written at the mirror's TOP LEVEL:
#
#   CONTRIBUTING.md   the plain-words contribution policy — what happens to a proposal somebody
#                     sends. SPEC-0197 rules 1-6, plus the SPEC-0195 rule 7 key-lifecycle SLOT.
#   RELEASE-NOTES.md  the per-release notes carrying the `answers:` LINK-BACK list (rule 4) — the
#                     proposals this release answers.
#
# WHY BOTH TRAVEL INSIDE THE DIGEST, which is the one design decision here worth stating. An
# earlier shape wrote them manifest-ADJACENT — beside `release-manifest.yaml`, outside
# `tree_digest`, on the reading that SPEC-0197 rule 4 calls the notes "a manifest-adjacent file".
# The audit-pre rejected it, correctly: those bytes ship inside the release commit, so leaving them
# out of the digest publishes content the manifest does not describe, and a verifier recomputing the
# digest over the published tree either mismatches or silently ignores them. Declaring them in
# `digest_excludes` would have been the other way out, but that field is the manifest schema, which
# is not this card's to change.
#
# So they go IN the tree, and the module's stated invariant — the cut is a pure function of the
# peeled commit, so the same tag always folds to the same digest — is what makes that safe. It is
# preserved BY CONSTRUCTION here, and that is a constraint on the content, not a comment about it:
#
#   * the policy is a CONSTANT (`render_contribution_policy()` takes no argument, reads no clock,
#     no host, no environment);
#   * the link-back list is DERIVED FROM THE SOURCE COMMIT — read off the governed task cards at
#     that commit, never from an operator flag. That is also why no `--answers` option exists: an
#     operator-supplied list would make the artifact a function of the INVOCATION rather than of the
#     source ref, and would make the manifest's own `rebuild:` command — which names only the tag —
#     unable to re-derive the release.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

POLICY_FILENAME = "CONTRIBUTING.md"
# RELEASE_NOTES_FILENAME is declared once, at the top of this module beside the other published
# filenames — the two rules that write into it (SPEC-0197 rule 4, SPEC-0195 rule 6) share the name
# as they share the file.

# The SPEC-0197 rule-2 proposal field set: FORGE-NEUTRAL — the minimum a proposal must carry,
# stated so it can be satisfied by an issue, a merge request or a patch mail alike. The hosting
# service that happens to be used first is an ADAPTER documented in the pattern named below; it is
# deliberately absent from here and from the spec body (rule 2 / CHARTER §Principle 4b).
PROPOSAL_FIELDS = (
    ("release version", "the exact release you have installed (the tag your pin names)"),
    ("affected path(s) or rule id(s)", "what the proposal is about — a file path, a SPEC id, a rule"),
    ("observed behaviour", "what actually happens today, concretely enough to reproduce"),
    ("proposed change or fix", "what you think should happen instead"),
    ("contact for the link-back", "where to reach you when the change ships, or is declined"),
)

ADAPTER_PATTERN = "patterns/contribution-intake-adapter.md"

# A conservative single-line proposal-id grammar. The link-back ids are rendered into a YAML-shaped
# list, so an id carrying a newline or a structural character could restructure the notes; the
# grammar refuses that at the source rather than escaping around it. Deliberately narrow — an id is a
# reference (an issue number, a proposal slug), not free text.
#
# `#` IS admitted, and leading, because an issue reference (`#417`) is the commonest real id shape.
# That is exactly why `render_release_notes` SINGLE-QUOTES every id: `- #417` unquoted is a YAML
# COMMENT, so the list item would render empty. The two halves are a pair — the grammar excludes the
# quote and the backslash, which is what makes single-quoting total (nothing admitted here needs
# escaping inside single quotes), and the quoting is what makes admitting `#` safe.
ANSWER_ID_RE = re.compile(r"\A[A-Za-z0-9#][A-Za-z0-9._/#+-]{0,63}\Z")

# T-13484: an ISSUE REFERENCE must name its tracker. An intake repo that is archived and re-created
# restarts its numbering at 1, so a bare `#417` (or `417`) stops naming the issue the card answered
# and starts naming whatever the new tracker filed under that number — and two trackers' `#1` fold
# into ONE entry of the link-back set. The grammar above stays as it is: `release_notes_answers`
# must keep reading the bare ids in notes that were signed before this rule and cannot be re-cut.
# What is refused is WRITING and PUBLISHING one, at the two doors that call the predicate below.
QUALIFIED_ISSUE_REF_RE = re.compile(r"\A[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#[0-9]+\Z")
QUALIFIED_ISSUE_REF_FORM = "owner/repo#N"


def unqualified_answer_id(aid: str) -> bool:
    """True when `aid` is an issue reference that does not say WHICH tracker (T-13484).

    Two shapes: an id carrying `#` that is not exactly `owner/repo#N`, and a number alone. A slug
    with no `#` (`proposal-2026-09`) is not an issue number, cannot collide across a re-created
    tracker, and stays admitted. Pure; the caller has already matched `ANSWER_ID_RE`.
    """
    if "#" in aid:
        return not QUALIFIED_ISSUE_REF_RE.match(aid)
    return aid.isdigit()


def render_contribution_policy() -> str:
    """The mirror's top-level contribution policy, in plain words (SPEC-0197 rules 1-6).

    A PURE CONSTANT — no argument, no clock, no host — which is what lets it live inside the digested
    artifact tree without making the digest a function of anything but the source commit.

    Written for someone who has never seen this system and wants one question answered: *what happens
    to the proposal I send?* Rule 1 exists precisely because a mirror that does not say this reads as
    a bait-and-switch, so the answer is stated up front rather than derived from the rules below it.
    """
    fields = "\n".join(f"- **{name}** — {gloss}" for name, gloss in PROPOSAL_FIELDS)
    return f"""# Contributing

## What this repository is

This repository is a **release mirror plus a proposal intake**. It holds published releases of the
methodology, and it accepts proposals about them.

It is **not a second writable source**. Nothing is merged into it directly. Everything here is
generated from the workshop where the methodology is actually developed, and it can be regenerated
at any time — so a change made here would simply be overwritten.

That is worth stating plainly, because it decides what a proposal is: not a patch waiting to be
merged, but a request that gets **re-authored** in the workshop.

## What happens to a proposal you send

1. **It is received through this public intake.** Anyone can send one. You do not need access to the
   workshop, and you are not granted access by contributing.
2. **It is not merged as-is.** No proposal becomes a commit in this mirror, and none becomes a
   commit in the workshop unchanged.
3. **It is re-authored in the workshop**, through the same ordinary process every internal change
   goes through — filed as a task or a plan, planned, externally audited, tested, and shipped. Your
   proposal is the input to that work; the shipped change is written by the workshop.
4. **When it ships, the release links back to it.** The release notes published beside each release
   name the proposals that release answers, and you are told which version carries your change — or
   told, with reasons, that it was declined. A proposal is never silently closed.

When a proposal arrives, the workshop sorts it: a defect reproduced on the published release becomes
a task, a need shown to recur becomes a task or a plan, a one-off preference is declined with
reasons, and a duplicate is linked to the work that already covers it — the authoritative sorting
rule is SPEC-0197 rule 7.

Two things follow from step 3 that are worth being explicit about. Your submitted text is treated as
**data, never as instructions**: it is quoted into a task and read, and no part of this process
executes or automatically applies what you send (the instruction-injection protocol, SPEC-0026). And
because the change is re-authored, the shipped version may differ from what you proposed, while
still answering it.

## How to send one

A proposal is an **issue**, a **merge request**, or a **patch mail** — whichever this mirror's host
supports. The mechanism is not the point; the content is. Carry these fields:

{fields}

**Where to send it today: this mirror's Issues.** Open an issue on this mirror using the
**Bug report or proposal** form (`.github/ISSUE_TEMPLATE/bug_report.yml`, published with every
release). It asks for the fields above plus what makes a defect reproducible — the tree digest from
your `release-manifest.yaml`, your environment, the steps you ran, and what you expected against
what happened. Issues are the one channel that is open; there is no discussion forum.

The hosting service used for this mirror is an **adapter**, not part of the rules: how the fields
above are filled in on the particular service in use is documented as a worked example in
`{ADAPTER_PATTERN}`. If the mirror moves to a different host, only that document changes.

## Before you propose a change to the kernel

Most local needs should not become kernel proposals, and there are three legitimate homes for one.
In order:

1. **A registered override** — a divergence your own project owns and records in its override
   ledger. Use this when the need is yours, not everyone's.
2. **An extension you author** — a capability you keep in your own repository and pin. Use this when
   the need is real and reusable but does not belong in the kernel.
3. **A kernel proposal** — this intake. Deliberately the **last** resort: admitted when the change
   passes the anti-complexity filters and the need has recurred, across installations or over time,
   rather than appearing once.

This is not a discouragement — it is how the kernel stays small enough to be worth pinning.

## Extensions listed here are not endorsements

The published catalog of extensions is a **discovery** surface. Listing is **not endorsement**.
A third-party extension is runnable code, and reviewing it before installing it is the installer's
responsibility, not the catalog's.

Extension pins name an **exact** version. A moving reference — a branch, a floating tag — is
refused, because a pin that can change underneath you is not a pin.

## Security — key lifecycle

Releases are signed, and every install and update verifies the signature before writing anything.

**Lost or compromised signing key — recovery procedure:** *(published here; see the release's
security documentation for the current procedure.)*

## Where the rules actually live

This document states, in plain words, a contract that is written in full in the methodology's own
specifications — the contribution policy (SPEC-0197) and the release contract (SPEC-0195), both
published in this mirror. Where this page and those specifications differ, the specifications are
authoritative; a difference is a defect in this page and is itself worth a proposal.
"""


def collect_answered_proposals(source_sha: str, *, main: Path, _die) -> tuple:
    """The link-back list (SPEC-0197 rule 4), DERIVED FROM THE SOURCE COMMIT.

    A re-authored proposal is a task card, and the card is where the workshop records which proposal
    it answers — an `answers:` list on the card. This reads those cards AT THE COMMIT, so the notes a
    release publishes are a property of the release, reproducible from the tag alone.

    ONE subprocess, not a walk. `git grep -l` over `tasks/` at the commit finds the handful of cards
    that carry the field; only those are then read. The alternative — opening every card — is ~2000
    blob reads for a field almost none of them have, which is the repeated-work shape this seam has
    no reason to introduce.

    ONLY A CARD THAT IS `done` AT THE COMMIT COUNTS (T-13564). Rule 4 names a proposal "when a
    re-authored change ships"; a card that is ready, parked, in progress or declined at the source
    commit has shipped nothing in the release cut from it, so its ids stay out. The `status` is read
    from the SAME blob that is already parsed for `answers:` — no second read. A proposal named by
    several cards is listed once, as soon as one of them is done.

    FAIL-CLOSED on every arm. A card whose `answers:` will not parse, and on a done card an id that
    fails `ANSWER_ID_RE` or an issue reference that names no tracker (`unqualified_answer_id`,
    T-13484), all REFUSE the publish naming the card. Skipping any would drop a proposal from the
    link-back silently, or publish a number that points at a different issue once the intake repo is
    re-created — which is precisely the "never silently closed" promise the policy above makes,
    broken by the code that is supposed to keep it. The parse refusal stands WHATEVER the card's
    state, because a card that does not parse has no readable `status` to excuse it. The id checks
    apply to a done card ONLY: an invalid id on a card that is not done goes with the card — it
    contributes nothing to these notes, so it can neither drop nor mis-name a proposal here, and it
    is judged at the release whose commit carries the card done. The ids fold into a SET, so two
    trackers' `#1` stay two entries only because each carries its tracker.
    """
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    rp = subprocess.run(["git", "-C", str(main), "grep", "-l", "-E", r"^answers:", source_sha,
                         "--", "tasks/"], capture_output=True, text=True, env=_git_env._git_child_env())
    # `git grep` exits 1 for "no matches" — a release that answers no proposal is ordinary, not an
    # error. Any OTHER non-zero exit is a real failure and must not read as an empty list.
    if rp.returncode not in (0, 1):
        _die(f"work publish: could not scan {source_sha[:12]} for link-back answers "
             f"({rp.stderr.strip() or 'git grep failed'}) — refusing rather than publishing release "
             "notes that silently claim to answer nothing.")
        return ()
    ids = set()
    for line in rp.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        rel = line.split(":", 1)[1] if line.startswith(source_sha + ":") else line
        blob = _git_blob(main, source_sha, rel)
        if blob is None:
            continue
        try:
            data = state.load_str(blob.decode("utf-8")) or {}
        except Exception as exc:
            _die(f"work publish: {rel} at {source_sha[:12]} does not parse "
                 f"({exc.__class__.__name__}) — it carries an `answers:` link-back that cannot be "
                 "read, and publishing would drop the proposal it names from the release notes.")
            return ()
        raw = data.get("answers")
        if raw is None:
            continue
        # Only a card that is `done` AT THIS COMMIT has shipped in the release cut from it. One that
        # is ready, parked, in progress or declined has shipped nothing here, so its ids are neither
        # listed nor judged; a proposal several cards name is listed as soon as one of them is done.
        if data.get("status") != "done":
            continue
        if not isinstance(raw, (list, tuple)):
            raw = [raw]
        for item in raw:
            aid = str(item).strip()
            # A host literal inside an id is refused HERE, not left to the publish-seam guard. The
            # guard would not catch it: `strip_published_text` runs first and REWRITES the literal to
            # a placeholder, so the survivor assertion sees a clean tree and the notes ship a link-back
            # naming a proposal that does not exist. Silently rewriting a proposer's id is precisely
            # the "never silently closed" promise broken by the code that renders it (measured — the
            # test that pins this ordering failed exactly this way before the check was added).
            if HOST_PATH_RE.search(aid):
                _die(f"work publish: {rel} carries the link-back id {aid!r}, which contains a host "
                     "absolute path. It cannot be published as-is (a release is host-clean) and it "
                     "must not be rewritten (that would publish a link-back naming a proposal that "
                     "does not exist). Fix the card and re-tag.")
                return ()
            if not ANSWER_ID_RE.match(aid):
                _die(f"work publish: {rel} carries the link-back id {aid!r}, which is not a valid "
                     "proposal id (a single line of letters, digits and `. _ / # + -`, 64 chars "
                     "max). The notes render these as a list, so an id with a newline or a "
                     "YAML-significant character would corrupt them. Fix the card and re-tag.")
                return ()
            if unqualified_answer_id(aid):
                _die(f"work publish: {rel} carries the link-back id {aid!r}, an issue reference "
                     f"that names no tracker. Write it as `{QUALIFIED_ISSUE_REF_FORM}` (an archived "
                     "tracker under its archive name): an intake repo that is re-created restarts "
                     "its numbering, so a bare number would publish a link-back to a different "
                     "issue. Fix the card (`bin/yitc-v2 task update <id> --set-field answers "
                     "--from-file <file>`) and re-tag.")
                return ()
            ids.add(aid)
    return tuple(sorted(ids))


def render_release_notes(*, tag: str, source_sha: str, answers) -> str:
    """The release notes (SPEC-0195 rule 5 / SPEC-0197 rule 4) — the LINK-BACK surface.

    Carries the release identity and the `answers:` list naming the proposals this release answers.
    An empty list renders EXPLICITLY, with a sentence saying so: a proposer reading notes with no
    `answers:` key at all cannot tell "answered nothing" from "the link-back was forgotten", and the
    difference is the whole of rule 4.

    It deliberately does NOT carry the tree digest. These notes live INSIDE the digested tree, so
    naming the digest here would be circular — the digest is published in the manifest, which is
    where a verifier reads it from anyway.
    """
    answers = tuple(answers)
    lines = [
        f"# Release {tag}",
        "",
        f"Source commit: `{source_sha}`",
        "",
        "## Proposals this release answers",
        "",
    ]
    if answers:
        lines += [
            "The proposals below were re-authored in the workshop and ship in this release "
            "(the contribution policy, `CONTRIBUTING.md`, step 4).",
            "",
            "```yaml",
            "answers:",
        ]
        # SINGLE-QUOTED, always — see ANSWER_ID_RE: an unquoted `- #417` is a YAML comment, and the
        # grammar guarantees no admitted id contains a quote or backslash to escape.
        lines += [f"  - '{aid}'" for aid in answers]
        lines += ["```"]
    else:
        lines += [
            "This release answers no outside proposal.",
            "",
            "```yaml",
            "answers: []",
            "```",
            "",
            "An empty list is stated rather than omitted, so that it reads as an answer and not as "
            "a missing link-back.",
        ]
    lines += [
        "",
        "See `CONTRIBUTING.md` for what happens to a proposal, and "
        f"`{MANIFEST_FILENAME}` for this release's provenance and digest.",
    ]
    return "\n".join(lines) + "\n"


# A commit subject NAMES the task it ships in exactly the three positions main actually uses
# (measured on v2.0.4..HEAD, T-13001): `<type>(T-XXXX): ...`, a bare leading `T-XXXX: ...`, and a
# trailing `... (T-XXXX)`. An id anywhere else in the subject is a passing mention, not a ship.
_CHANGE_SUBJECT_RES = (
    re.compile(r"\A[A-Za-z][\w-]*\((T-\d+)\)"),
    re.compile(r"\A(T-\d+)\b"),
    re.compile(r"\((T-\d+)\)\s*\Z"),
)


def change_subject_task_id(subject: str):
    """The task id a commit subject ships under, or `None` when it only mentions ids in passing."""
    for rx in _CHANGE_SUBJECT_RES:
        m = rx.search(subject)
        if m:
            return m.group(1)
    return None


def journal_task_closed_rows(since, *, main: Path, _die) -> list:
    """`task_closed` rows with `ts >= since` (every row when `since` is None), read through the governed `journal query` verb.

    The verb is the segment-aware reader (SPEC-0190 rule 4), so the publish seam reads the one
    logical journal across every segment rather than growing a second raw reader of its own. It is
    FAIL-CLOSED: a query that cannot run, or prints a line that is not a JSON row, REFUSES the
    publish — an empty list here would publish notes claiming nothing changed.
    """
    import json
    import sys
    argv = [sys.executable, str(Path(__file__).resolve().parent.parent / "yitc-v2"), "-C", str(main),
            "journal", "query", "--type", "task_closed", *(["--since", since] if since else []),
            "--limit", "0", "--json"]
    try:
        rp = subprocess.run(argv, cwd=str(main), capture_output=True, text=True)
    except OSError as exc:
        _die(f"work publish: could not run `journal query` for the change list ({exc}) — refusing "
             "rather than publishing notes that silently list no change.")
        return []
    if rp.returncode != 0:
        _die("work publish: `journal query --type task_closed` failed "
             f"({rp.stderr.strip() or rp.returncode}) — refusing rather than publishing notes that "
             "silently list no change.")
        return []
    rows = []
    for line in rp.stdout.splitlines():
        # A checkout with no journal at all is answered by the verb's own `(no events.jsonl)` line
        # (exit 0): nothing was ever closed there, which is an honest empty list, not a bad read.
        if not line.strip() or line.strip() == "(no events.jsonl)":
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            _die(f"work publish: `journal query --json` printed a non-JSON line ({line[:80]!r}) — "
                 "refusing to guess the change list.")
            return []
    return rows


def previous_release_tag(tag: str, *, main: Path, _die):
    """The highest release tag in `main` older than `tag`, or `None` for a first release.

    The ONE answer to "which release came before this one" for the notes: the «What changed» list
    (T-12391) and the «Capabilities to consider» list (T-13629) both compare against it.
    """
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    this_v = parse_release_version(tag)
    rp = subprocess.run(["git", "-C", str(main), "tag", "--list"], capture_output=True, text=True,
                        env=_git_env._git_child_env())
    if rp.returncode != 0:
        _die(f"work publish: could not list tags in {main} for the release notes — refusing. Check "
             f"`git -C {main} tag --list`, then re-run `bin/yitc-v2 work publish`.")
        return None
    older = [(v, t) for t, v in ((t.strip(), parse_release_version(t.strip()))
                                 for t in rp.stdout.splitlines() if t.strip())
             if v is not None and this_v is not None and _compare(v, this_v) < 0]
    if not older:
        return None
    return max(older, key=functools.cmp_to_key(lambda a, b: _compare(a[0], b[0])))[1]


def collect_capabilities(tag: str, source_sha: str, *, main: Path, _run_git_cap, _resolve_placement,
                         raw_handbook_docs, _die):
    """The «Capabilities to consider» list (T-13629) for the release cut at `source_sha`.

    `None` for a first release, else what `capabilities_to_consider` derives from the travelling
    specs of TWO cuts: this one and the previous release tag's. Both sides are `cut_release_tree`
    itself, narrowed to `specs/`, so "travels in a release" has one predicate (kernel realm and
    `status: active` at that commit, SPEC-0073 rule 8) and this list cannot disagree with what the
    two releases actually ship.
    """
    prev_tag = previous_release_tag(tag, main=main, _die=_die)
    if prev_tag is None:
        return None
    prev_sha = _git_out(_run_git_cap, main, ["rev-parse", f"{prev_tag}^{{commit}}"])
    if not prev_sha or not prev_sha.strip():
        _die(f"work publish: could not resolve the previous release tag {prev_tag} — refusing "
             "rather than publishing notes that silently list no new capability. Check "
             f"`git -C {main} rev-parse {prev_tag}^{{commit}}`, then re-run `bin/yitc-v2 work publish`.")
        return None
    cuts = [cut_release_tree(sha, _run_git_cap=_run_git_cap, main=main,
                             _resolve_placement=_resolve_placement,
                             raw_handbook_docs=raw_handbook_docs, _die=_die, paths_under="specs/")[0]
            for sha in (source_sha, prev_sha.strip())]
    try:
        return capabilities_to_consider(cuts[0], cuts[1])
    except ValueError as exc:
        _die(f"work publish: {exc} — refusing to guess the capabilities list. Fix the spec at that "
             "commit, then re-tag with `bin/yitc-v2 work tag --tag <tag>`.")
        return None


def collect_change_list(tag: str, source_sha: str, *, main: Path, _resolve_placement, _die,
                        _task_closed_rows=None):
    """The «What changed» list (T-12391): kernel-realm tasks whose work first enters this tag's history.

    Returns `None` when there is no previous release tag, else a tuple of
    `(task_id, title, class, closed_at)` in close order — `closed_at` is the `ts` of the card's
    `task_closed` row, printed as its `events.jsonl#ts=` locator (T-13001). Three existing carriers, no new store:

      GIT          decides MEMBERSHIP, by ancestry — a task qualifies only when a commit in
                   `<prev>..<source>` whose subject names it (`change_subject_task_id`) touches
                   a path `_resolve_placement` resolves `kernel` (SPEC-0073), so a
                   workshop-only task never appears;
      the CARD     at the source commit supplies title and class and must say `done`, and the same
                   card at the previous tag's commit must NOT say `done` — a card an earlier release
                   already listed is never listed again;
      the JOURNAL  says WHEN a task closed — its `task_closed` rows, via `journal_task_closed_rows`
                   (injectable for tests) — and is ONLY the sort key and the printed locator, never a
                   filter (T-13595): a tag may point at a branch commit, so close time and ancestry
                   disagree in both directions, and a time window dropped cards that shipped.
    """
    prev_tag = previous_release_tag(tag, main=main, _die=_die)
    if prev_tag is None:
        return None

    def git(*argv, env=None):
        from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
        r = subprocess.run(["git", "-C", str(main), *argv], capture_output=True, text=True, env=_git_env._git_child_env(env))
        if r.returncode != 0:
            _die(f"work publish: `git {' '.join(argv[:3])}` failed while composing the change list "
                 f"({r.stderr.strip()}) — refusing.")
            return None
        return r.stdout

    import os

    def commit_time(sha):
        return (git("show", "-s", "--format=%cd", "--date=format-local:%Y-%m-%dT%H:%M:%SZ", sha,
                    env=dict(os.environ, TZ="UTC")) or "").strip()

    prev_sha = (git("rev-parse", f"{prev_tag}^{{commit}}") or "").strip()
    # Only the locator choice reads THIS tag's commit time: when a card has several task_closed
    # rows, the latest one at or before it is printed (a later re-close or settle row is not).
    until = commit_time(source_sha)
    log = git("log", "--format=%x00%s", "--name-only", f"{prev_sha}..{source_sha}") or ""
    kernel_ids = set()
    for chunk in log.split("\x00"):
        lines = [ln for ln in chunk.splitlines() if ln.strip()]
        if not lines:
            continue
        tid = change_subject_task_id(lines[0])
        if tid and any(_resolve_placement(p.strip()) == "kernel" for p in lines[1:]):
            kernel_ids.add(tid)

    # The whole journal is read: a card's closure may predate the previous tag's commit time while
    # its commit is still outside that tag's history (T-13595).
    reader = _task_closed_rows or (lambda s: journal_task_closed_rows(s, main=main, _die=_die))
    rows_by_tid = {}
    for row in reader(None) or ():
        tid, ts = row.get("task_id"), str(row.get("ts") or "")
        if row.get("type", "task_closed") == "task_closed" and tid in kernel_ids and ts:
            rows_by_tid.setdefault(tid, []).append(ts)
    closed_at = {tid: max([t for t in tss if t <= until] or tss) for tid, tss in rows_by_tid.items()}

    def card_paths(sha):
        found = {}
        for rel in (git("ls-tree", "--name-only", sha, "tasks/") or "").splitlines():
            name = Path(rel.strip()).name
            tid = name.split("-", 2)
            if len(tid) >= 2 and name.endswith(".yaml"):
                found.setdefault(f"{tid[0]}-{tid[1].split('.')[0]}", rel.strip())
        return found

    cards, prev_cards = card_paths(source_sha), card_paths(prev_sha)
    out = []
    for tid in closed_at:
        # The card at THIS tag's commit, then at the previous tag's — `{}` where it is absent.
        parsed = []
        for sha, paths in ((source_sha, cards), (prev_sha, prev_cards)):
            blob = _git_blob(main, sha, paths[tid]) if tid in paths else None
            try:
                parsed.append((state.load_str(blob.decode("utf-8")) or {}) if blob is not None else {})
            except Exception as exc:
                _die(f"work publish: {paths[tid]} at {sha[:12]} does not parse "
                     f"({exc.__class__.__name__}) — refusing to guess its title for the change list.")
                return None
        data, before = parsed
        if data.get("status") != "done" or before.get("status") == "done":
            continue
        out.append((closed_at[tid], tid, str(data.get("title") or ""), str(data.get("class") or "")))
    return tuple((tid, title, klass, ts) for ts, tid, title, klass in sorted(out))


def attach_contribution_surfaces(tree: dict) -> dict:
    """Add the contribution POLICY to the cut, BEFORE the digest is taken over it.

    Returns a new tree; the input is not mutated. The policy is a function of nothing but this
    module's own text, so attaching it leaves the cut a pure function of the commit and the digest
    reproducible.

    THE RELEASE NOTES ARE NOT ASSIGNED HERE. They were, until SPEC-0195 rule 6 put a second required
    section (the verifying-entrypoint inventory) into the SAME published filename — two attachers
    assigning `out[RELEASE_NOTES_FILENAME]` is a silent last-one-wins clobber, not a merge. Rule 4's
    link-back list is still rendered by `render_release_notes`, unchanged; it is now the HEAD of the
    one composed value `build_release_notes` builds and `_add_trust_surfaces` assigns. The `answers`
    scan that feeds it still runs at the same point in the publish seam (see `cmd_work_publish`), so
    a card whose link-back cannot be read still refuses before anything is written.
    """
    out = dict(tree)
    out[POLICY_FILENAME] = render_contribution_policy().encode("utf-8")
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# T-12045 — THE VERSION FLOOR (SPEC-0195 rule 9). ONE compatibility declaration in the published
# content (`requires_engine`, written by `build_manifest` above), ONE check here, called at the
# entry seams — and the check HARD-FAILS BEFORE ANY MUTATION.
#
# WHAT THIS RETIRES. Until now a consumer ran whatever engine its path named against whatever
# content it held: undeclared and unchecked, so a mismatched pair corrupted a project with no
# message at all. The floor replaces that silence with a refusal that names the required version and
# the command that satisfies it.
#
# THE HOUSE STYLE THIS FOLLOWS, and it is the load-bearing design decision here: this module
# REPORTS, the CALLER refuses. `check_version_floor` never raises and never dies — exactly like
# `init.resolve_engine_pin` (T-12044), and for the same reason: it lets ONE function serve both a
# hard-failing entry seam and the report-only reader T-12046 adds, instead of growing a second
# comparison that could disagree with this one.
#
# WHERE IT IS DELIBERATELY INERT. Absence is never read as failure, because a missing declaration is
# not a mismatch — it is the absence of an answer, and guessing one would refuse the entire current
# population of consumers for a defect nobody has. So a pre-floor manifest reports `not-declared`
# and a manifest-less engine reports `engine-unknown`, both OK. What is NOT inert is a declaration
# that EXISTS and will not parse: that fails closed (`unreadable`), on the same grounds the
# revocation-list reader refuses an undecodable list rather than reading it as "nothing revoked".
# ═══════════════════════════════════════════════════════════════════════════════════════════════

# A release version: an optional `v`, then dotted numeric components. DELIBERATELY NARROW — the tags
# this contract admits are the ones `work tag` cuts, and a permissive parser here would have to
# invent an ordering for shapes nobody publishes. Anything else is `None`, which the caller reports
# as `unreadable` rather than ordering by guess.
_VERSION_RE = re.compile(r"\Av?(\d+(?:\.\d+)*)\Z")
# The floor grammar: `>=<version>`. One operator, because rule 9 asks for a FLOOR — "the engine
# version range it requires" bounded from below. A range language would be a second thing to specify,
# and nothing has asked for one (CHARTER §P1 F4).
_FLOOR_RE = re.compile(r"\A>=\s*(v?\d+(?:\.\d+)*)\Z")


def requires_engine_floor(tag: str) -> str:
    """The compatibility declaration for content cut at `tag` — the value `build_manifest` writes."""
    return f">={tag}"


def parse_release_version(ref):
    """`v1.2.3` -> `(1, 2, 3)`; anything that is not a release version -> None.

    Returned as a tuple so comparison is the language's own, not a hand-rolled one. Components are
    compared left to right and a shorter version is zero-extended by `_compare` below, so `v1.2` and
    `v1.2.0` order equal rather than by length — the reading every operator expects.
    """
    m = _VERSION_RE.match(str(ref or "").strip())
    return tuple(int(part) for part in m.group(1).split(".")) if m else None


def parse_engine_floor(declaration):
    """`'>=v1.2.0'` -> `(1, 2, 0)`; a declaration that is absent or unreadable -> None.

    The two Nones are distinguished by the CALLER (absence is `not-declared` and OK; an unreadable
    declaration is `unreadable` and refuses), which is why this returns the parse and judges nothing.
    """
    m = _FLOOR_RE.match(str(declaration or "").strip())
    return parse_release_version(m.group(1)) if m else None


def _compare(engine: tuple, required: tuple) -> int:
    """Order two parsed versions, zero-extending the shorter — `(1, 2)` vs `(1, 2, 0)` is equal."""
    width = max(len(engine), len(required))
    a = engine + (0,) * (width - len(engine))
    b = required + (0,) * (width - len(required))
    return (a > b) - (a < b)


def satisfying_command() -> str:
    """The command that satisfies an out-of-floor pair — READ FROM the published entrypoint
    inventory, never re-spelled here.

    Rule 9 requires the refusal to name a command that satisfies it, and rule 6 already publishes the
    supported entrypoints in ONE carrier. Reading that carrier is what keeps the refusal and the
    published inventory from drifting into naming different commands (CHARTER §P5) — and it makes the
    message falsifiable: remove the install row from the inventory and the refusal stops naming it.

    Returns "" if the inventory publishes no install entrypoint at all. Fail-closed toward saying
    nothing: naming an unsupported command would be worse than naming none.
    """
    for name, invocation, _description in ENTRYPOINT_INVENTORY:
        if name == "release install":
            return invocation
    return ""


def running_engine_root() -> Path:
    """The root of the engine EXECUTING this call — `bin/lib/release.py` -> the repo root above it.

    Derived from this file's own location rather than from a caller-supplied path, because the
    question the floor asks is "how old is the code that is about to run", and only the running
    module can answer that about itself. Note this is deliberately NOT `cli.ENGINE_ROOT`: under a
    `-C` rebind that global names the PINNED engine, which is the right answer for the pinned seam
    (where `init` passes the resolved root explicitly) and the wrong one here.
    """
    return Path(__file__).resolve().parent.parent.parent


def read_manifest(root):
    """Parse `<root>/release-manifest.yaml`, or None if it is absent or will not parse.

    Absent and undecodable collapse to one answer HERE and are separated by the caller, which is the
    same split `resolve_engine_pin` makes: a reader reports what it found, a judge decides what it
    means.
    """
    try:
        path = Path(root) / MANIFEST_FILENAME
        if not path.is_file():
            return None
        parsed = state.load_str(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — an unreadable manifest is "no manifest", never a crash
        return None
    return parsed if isinstance(parsed, dict) else None


def engine_version_line(root=None) -> str:
    """The ONE line naming the engine version THIS session runs (T-13258). Never raises.

    `root` defaults to `running_engine_root()` — the code executing now, not a pin — because an engine
    updated under a live session leaves that session on the OLD code (the test-server incident behind
    T-13234/T-13258). Order: the release manifest's `source_ref`, else `source checkout <short sha>`,
    else `unknown`. Printed at `session start` and by `release check` (its post-/compact re-fold).
    """
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    try:
        root = Path(root) if root is not None else running_engine_root()
        manifest = read_manifest(root)
        ref = str((manifest or {}).get("source_ref") or "").strip()
        if ref:
            return f"engine: this session runs release {ref} ({root})"
        import subprocess
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL,
                              env=_git_env._git_child_env())
        sha = proc.stdout.strip() if proc.returncode == 0 else ""
        if sha:
            return f"engine: this session runs source checkout {sha} ({root})"
    except Exception:  # noqa: BLE001 — a report-only line never fails its caller
        pass
    return "engine: this session runs unknown"


RESTART_REMINDER = (
    "restart: sessions already open on this engine keep running the OLD code until they are "
    "restarted — close and re-open each of them to run this release (nothing checked which are open).")
# T-13258: printed UNCONDITIONALLY after a successful `release update`. Deliberately names no session
# and runs no liveness check — per-session liveness is not reliably knowable (T-13234, closed RED).


class FloorVerdict:
    """The floor check's answer: `ok` plus the STATUS and the REASON — never a bare boolean.

    Same shape and same rationale as `ReleaseVerdict`: a refusal that cannot say why leaves the
    operator guessing, and the cheapest guess is "try again without the check".
    """

    __slots__ = ("ok", "status", "detail", "required", "engine_version")

    def __init__(self, ok: bool, status: str, detail: str, required="", engine_version=""):
        self.ok = ok
        self.status = status
        self.detail = detail
        self.required = required
        self.engine_version = engine_version

    def __bool__(self):
        return self.ok


def check_version_floor(*, content_manifest, engine_version, engine_manifest=None) -> FloorVerdict:
    """THE check (SPEC-0195 rule 9) — does `engine_version` satisfy what `content_manifest` requires?

    NEVER RAISES, NEVER DIES. It returns a verdict; the caller decides whether that verdict stops
    anything. Six statuses, each a distinct fact rather than a shade of failure:

      `embedded`       the content and the engine name the SAME `source_ref`. Satisfied BY
                       CONSTRUCTION and NO comparison is performed — an embedded release is engine
                       and content cut at one tag, so there is no pair to be mismatched. This arm is
                       what makes rule 9's "embedded releases satisfy the check by construction"
                       true of the code rather than merely of the intent.
      `not-declared`   the content declares no floor (a release published before this field, or a
                       tree that is not a release). OK: there is no declaration to judge.
      `engine-unknown` the engine ships no manifest, so its version is unknown. OK: the comparison
                       cannot be made, and this SAYS so instead of assuming either answer. This is
                       the state of the workshop engine and of every consumer today, which is why
                       wiring the floor changes nothing for them.
      `unreadable`     a floor IS declared, or an engine version IS present, and does not parse.
                       REFUSES — reading a declaration that exists but cannot be read as "no floor"
                       is a one-byte bypass.
      `below-floor`    the engine is older than the content requires. REFUSES, naming the required
                       version and the satisfying command.
      `ok`             satisfied.
    """
    content = content_manifest if isinstance(content_manifest, dict) else {}
    declared = content.get(REQUIRES_ENGINE_FIELD)
    engine_ref = str(engine_version or "").strip()

    # EMBEDDED FIRST, before the declaration is even read: engine and content at one tag are the same
    # artifact, and a parse failure in a floor that describes the very tree doing the checking must
    # not refuse a pair that cannot be mismatched.
    content_ref = str(content.get("source_ref") or "").strip()
    engine_manifest_ref = ""
    if isinstance(engine_manifest, dict):
        engine_manifest_ref = str(engine_manifest.get("source_ref") or "").strip()
    if content_ref and content_ref in (engine_ref, engine_manifest_ref):
        return FloorVerdict(True, "embedded",
                            f"engine and content are one release ({content_ref}) — the floor is "
                            f"satisfied by construction (SPEC-0195 rule 9)",
                            required=str(declared or ""), engine_version=engine_ref)

    if declared is None or not str(declared).strip():
        return FloorVerdict(True, "not-declared",
                            "the content declares no `requires_engine` floor, so there is no "
                            "compatibility claim to check (a release published before SPEC-0195 "
                            "rule 9, or a tree that is not a release)")

    required = parse_engine_floor(declared)
    if required is None:
        return FloorVerdict(False, "unreadable",
                            f"the content declares `{REQUIRES_ENGINE_FIELD}: {declared!r}`, which is "
                            f"not a readable floor (expected `>=<version>`, e.g. `>=v1.2.0`). A "
                            f"declaration that exists but cannot be read is REFUSED rather than "
                            f"treated as no floor — that reading would be a one-byte bypass",
                            required=str(declared))

    if not engine_ref:
        return FloorVerdict(True, "engine-unknown",
                            f"the content requires engine {declared}, but this engine ships no "
                            f"release manifest, so its version is unknown and the comparison cannot "
                            f"be made. Reported rather than assumed in either direction",
                            required=str(declared))

    engine_parsed = parse_release_version(engine_ref)
    if engine_parsed is None:
        return FloorVerdict(False, "unreadable",
                            f"this engine's release version {engine_ref!r} is not a readable version, "
                            f"so it cannot be checked against the required {declared}",
                            required=str(declared), engine_version=engine_ref)

    if _compare(engine_parsed, required) < 0:
        command = satisfying_command()
        fix = (f"\n  fix: install an engine at {declared} or newer:\n"
               f"    {command}" if command
               else "\n  fix: install an engine at that version or newer — but this release publishes "
                    "NO install entrypoint, so there is no supported command to name")
        return FloorVerdict(False, "below-floor",
                            f"ENGINE TOO OLD: this engine is {engine_ref}, and the content requires "
                            f"{declared} (SPEC-0195 rule 9). Refusing BEFORE any write — a mixed "
                            f"engine/content pair is the silent corruption this floor exists to "
                            f"replace with a message.{fix}",
                            required=str(declared), engine_version=engine_ref)

    return FloorVerdict(True, "ok",
                        f"engine {engine_ref} satisfies the content's required {declared}",
                        required=str(declared), engine_version=engine_ref)


def check_root_pair(content_root, engine_root) -> FloorVerdict:
    """The SEAM-FACING form: check the content tree at `content_root` against the engine at
    `engine_root`. ONE call per entry seam, and ONE place the two manifests are resolved.

    Both roots are read through `read_manifest`, so a tree that is not a release simply contributes
    no manifest and the verdict says which side was missing rather than failing obscurely.
    """
    engine_manifest = read_manifest(engine_root) if engine_root is not None else None
    return check_version_floor(
        content_manifest=read_manifest(content_root),
        engine_version=(str(engine_manifest.get("source_ref") or "").strip()
                        if engine_manifest else ""),
        engine_manifest=engine_manifest)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# T-12046 — UPDATE + THE OVERRIDE LEDGER (SPEC-0195 rule 8, SPEC-0196). A NEW, self-contained
# section: everything below is additive, and everything above is CONSUMED, never edited. In
# particular `verify_release` / `read_release_tree` / `TEMPLATE_OWNED_SURFACE` / `read_manifest`
# belong to T-12042/43/45 and are used here exactly as they are.
#
# WHY UPDATE AND THE LEDGER ARE ONE UNIT (SPEC-0046 §A bidirectional cut). A registered divergence
# and an unregistered one are the SAME BYTES; the only thing that tells them apart is the ledger. So
# an `update` shipped without the ledger cannot report the conflict rule 8 requires it to report —
# it would have to either overwrite every local edit or preserve every local edit, and both are the
# silent resolution rule 8 forbids. In the other direction a ledger with no `update` has no reader.
#
# WHAT THIS ADDS, and the ONE thing worth stating twice: every path a consumer holds falls into
# exactly one of THREE classes (SPEC-0195 rule 2), and the classification is DERIVED, never
# declared twice —
#
#   template-owned    the manifest's own enumerated `template_owned` list. THREE-WAY MERGED.
#   upstream-owned    everything else in the VERIFIED release tree. REPLACED WHOLESALE, unless it
#                     diverges locally, in which case the ledger decides preserve-vs-conflict.
#   consumer-owned    everything under the destination that is in NEITHER of the above. NEVER
#                     WRITTEN. Its bytes ARE read, once, by the classification below — the class is
#                     defined by SUBTRACTION (next paragraph), so it cannot be computed without
#                     enumerating what the destination holds. That read is where it ends: those
#                     bytes are compared against nothing and the path reaches the report by NAME
#                     alone. What SPEC-0195 guarantees, and what is kept structurally, is about
#                     MUTATION — "NEVER touches consumer-owned paths", "byte-identical".
#
# The consumer-owned class is defined by SUBTRACTION on purpose. A skip-LIST maintained anywhere
# would be a second declaration that drifts from the release the moment upstream adds a file, and it
# would fail in the direction that overwrites a project's own work. Subtraction cannot: a path the
# release does not ship is, by construction, not the release's to touch.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

# The ops-carrier section the ledger lives in (SPEC-0196 rule 1: ONE section of the existing
# `yitc-ops.yaml`, SPEC-0093 rule 1 — never a second file). Named here because this module's readers
# need it; the SHAPE of an entry is owned by the concern's kernel hook, not re-spelled here.
OVERRIDE_LEDGER_SECTION = "overrides"

# The finding kinds the report-only drift check emits (SPEC-0196 rules 3 + 4). A closed set, so a
# reader can switch on them; each is REPORT-ONLY and moves no exit code and no land gate.
LEDGER_FINDING_KINDS = ("malformed", "conflict", "redundant", "overdue")


def _entry_shape_errors(entry, index):
    """Delegate to the ONE entry-shape judgement — `init.override_entry_errors`, the same function
    the fail-closed init sweep dispatches through the concern's `shape_hook`.

    The import is deferred into the call rather than taken at module import, following this repo's
    `lib.init` convention (the nightly's lazy `from lib import init`): `init.py` is imported directly
    by the verify sandbox where `lib` is not an importable package, so keeping the edge lazy keeps
    both modules importable in isolation."""
    from lib import init as _init
    return _init.override_entry_errors(entry, index)


def read_override_ledger(ops_path) -> dict:
    """Read the `overrides:` ledger section off a consumer's ops carrier (SPEC-0196 rule 1).

    Returns `{"status": ..., "entries": [...]}` where status is one of `ok` (a section is present and
    is a mapping), `no-section` (absent — the commonest and healthiest state, since a project that
    diverges from nothing carries no ledger) or `unreadable` (the carrier is missing, unparseable, or
    the section is not a mapping).

    FAITHFUL, NOT FAIL-CLOSED. It reports what it read and never raises, because fail-closed belongs
    to the USE SITE, not the parser (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`):
    `update` treats an unreadable carrier as "no entry vouches for anything", which makes every local
    divergence a CONFLICT — the safe direction — while the nightly leg reports it as its own finding.
    Collapsing ABSENT and CORRUPTED into one answer here would take that choice away from both."""
    ops_path = Path(ops_path)
    if not ops_path.is_file():
        return {"status": "no-section", "entries": [], "reason": f"{ops_path.name} not present"}
    try:
        ops = state.load_ops(ops_path)
    except Exception as e:                                   # noqa: BLE001 — a faithful reader
        return {"status": "unreadable", "entries": [], "reason": f"{ops_path.name} unreadable ({e})"}
    if not isinstance(ops, dict):
        return {"status": "unreadable", "entries": [],
                "reason": f"{ops_path.name} is not a mapping"}
    if OVERRIDE_LEDGER_SECTION not in ops:
        return {"status": "no-section", "entries": [],
                "reason": "no `overrides:` section — this project registers no local divergence"}
    section = ops.get(OVERRIDE_LEDGER_SECTION)
    if not isinstance(section, dict):
        return {"status": "unreadable", "entries": [],
                "reason": f"`{OVERRIDE_LEDGER_SECTION}:` is present but not a mapping"}
    entries = section.get("entries")
    if entries is None:
        return {"status": "ok", "entries": []}
    if not isinstance(entries, list):
        return {"status": "unreadable", "entries": [],
                "reason": f"`{OVERRIDE_LEDGER_SECTION}.entries:` is present but not a list"}
    return {"status": "ok", "entries": entries}


def _trigger_fired(trigger, *, now: str, tasks_dir) -> str:
    """Has this entry's `review_trigger` fired (SPEC-0196 rule 4)? Returns a plain-language reason,
    or "" when it has not.

    TWO admitted trigger shapes, because rule 1 admits two: an ISO date, which has fired once the
    date has passed; and a NAMED ARTIFACT, whose CLOSE re-opens the entry. The artifact leg reads the
    project's own task cards — a `done` card is a fired trigger. An artifact the project does not
    carry is NOT reported as fired: an unresolvable name is a different defect from an expired one,
    and reporting it as OVERDUE would tell the owner to re-review something that may not have
    happened.

    `now` is passed IN rather than read from the clock, so the same ledger read at the same instant
    reports the same thing to `update` and to the nightly (and so a test can state its own today)."""
    import datetime

    if isinstance(trigger, datetime.datetime):
        return ""                                            # not a date-only value; the shape check owns it
    if isinstance(trigger, datetime.date):
        trigger = trigger.isoformat()
    if not isinstance(trigger, str) or not trigger.strip():
        return ""
    text = trigger.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return (f"its review date {text} has passed (today is {now[:10]})"
                if text < now[:10] else "")
    if tasks_dir is None:
        return ""
    tasks_dir = Path(tasks_dir)
    if not tasks_dir.is_dir():
        return ""
    for card in sorted(tasks_dir.glob(f"{text}*.yaml")):
        # `state.load_path` is the CANONICAL corpus reader (CHARTER §P5 — one parser library) and
        # returns {} rather than raising on a malformed card, which is the right shape here: an
        # unreadable card is not a fired trigger.
        data = state.load_path(card)
        if isinstance(data, dict) and str(data.get("status") or "") in ("done", "wont-do"):
            return (f"the artifact it names ({text}) is {data.get('status')} — its close re-opens "
                    f"this entry")
    return ""


def ledger_drift(ops_path, *, now=None, tasks_dir=None, redundant_paths=(), conflicts=()) -> dict:
    """THE report-only override-ledger drift check (SPEC-0196 rule 3) — the ONE implementation.

    `update` calls it with the two facts only an update knows (which registered paths the new release
    now CARRIES, and which unregistered divergences it found); the nightly leg calls it with neither
    and gets the ledger-INTRINSIC findings alone. That asymmetry is honest rather than a shortfall: a
    nightly sweep holds no verified release tree, so it cannot know whether a divergence is redundant,
    and inventing an answer would be worse than reporting the two it can read.

    Returns `{"status", "findings": [{kind, path, detail}], "entries": N}`. REPORT-ONLY, by contract:
    it adds no land gate, moves no exit code, and resolves nothing (rule 3). The four kinds:

      malformed  the entry does not carry rule 1's field set / vocabulary — DELEGATED entirely to
                 `init.override_entry_errors`, the same judgement the init sweep fails closed on.
      conflict   an UNREGISTERED local edit of an upstream-owned file (rule 3). Supplied by `update`.
      redundant  the pinned release now carries the divergence — the entry MUST be deleted and the
                 local edit dropped, and this reports it until that happens (rule 4).
      overdue    the entry's review trigger has fired and it was not re-reviewed (rule 4).

    A MALFORMED entry is reported and then SKIPPED for the other three kinds. Judging redundancy of
    an entry whose `path` may be absent or non-string would be reading a field the shape check has
    just said cannot be trusted; one finding that names the real defect beats three that follow from
    it."""
    now = now or _utc_now()
    read = read_override_ledger(ops_path)
    findings: list = []
    redundant = {str(p) for p in redundant_paths}

    for path in sorted({str(p) for p in conflicts}):
        findings.append({
            "kind": "conflict", "path": path,
            "detail": "an UNREGISTERED local edit of an upstream-owned file — left UNRESOLVED in "
                      "both directions (SPEC-0196 rule 3). Either register it as an override (with "
                      "a rationale, an upstream_intent and a review trigger) or drop the local edit."})

    if read["status"] == "unreadable":
        return {"status": "unreadable", "findings": findings, "entries": 0,
                "reason": read.get("reason")}
    if read["status"] == "no-section":
        return {"status": "no-section" if not findings else "checked", "findings": findings,
                "entries": 0, "reason": read.get("reason")}

    entries = read["entries"]
    for i, entry in enumerate(entries):
        shape = _entry_shape_errors(entry, i)
        if shape:
            findings.append({
                "kind": "malformed",
                "path": (entry.get("path") if isinstance(entry, dict) else None) or f"entries[{i}]",
                "detail": "; ".join(shape)})
            continue
        path = str(entry.get("path")).strip()
        if path in redundant:
            findings.append({
                "kind": "redundant", "path": path,
                "detail": "the pinned release now carries this divergence — DELETE the entry and "
                          "drop the local edit (SPEC-0196 rule 4, delete-on-merge). Reported until "
                          "the entry is gone."})
        fired = _trigger_fired(entry.get("review_trigger"), now=now, tasks_dir=tasks_dir)
        if fired:
            findings.append({
                "kind": "overdue", "path": path,
                "detail": f"the review trigger has fired — {fired}. A `temporary-patch` MUST become "
                          f"`forwarded` or `accepted-exception` by its trigger (SPEC-0196 rule 4); "
                          f"re-record the trigger to clear this."})
    return {"status": "checked", "findings": findings, "entries": len(entries)}


def _template_owned_surface(manifest) -> tuple:
    """The template-owned surface for THIS release — read from the manifest the gate authenticated,
    falling back to this module's own enumeration only when the manifest declares none.

    Read from the manifest rather than from the constant because the ENUMERATION IS A PROPERTY OF THE
    RELEASE (SPEC-0195 rule 2: "Enumerated in the release manifest, never implied"). A consumer must
    be able to read what the artifact IT INSTALLED claims the right to re-write; taking the running
    engine's constant instead would let a newer engine silently claim re-scaffold rights over a file
    the pinned release never declared."""
    declared = (manifest or {}).get("template_owned")
    if isinstance(declared, list):
        picked = tuple(str(p) for p in declared if isinstance(p, str) and p.strip())
        if picked:
            return picked
    return tuple(TEMPLATE_OWNED_SURFACE)


def _held_tree(root: Path) -> dict:
    """Every path the destination currently HOLDS, as {rel: bytes} — the same reader the gate uses.

    Reusing `read_release_tree` is not incidental: the update compares held bytes with released bytes,
    and two readers with different ideas about symlinks or `.git` would make that comparison lie."""
    return read_release_tree(root) if Path(root).is_dir() else {}


def update(dest, into, anchor, *, base=None, now=None) -> dict:
    """`update` from pinned release N to N+1 (SPEC-0195 rule 8) — never a silent overwrite.

    THE ORDERING IS THE CONTRACT, exactly as in `cmd_release_install`: `verify_release` runs to a
    verdict BEFORE the destination is opened, so a refused update leaves every consumer byte
    untouched (rule 6 — "BEFORE any write", read literally). The bytes written are the bytes VERIFIED
    (`verdict.tree`, the gate's own snapshot), so a mirror that changes between the check and the copy
    cannot substitute what lands.

    Then, per class (rule 2):

      * CONSUMER-OWNED — every held path NO release shipped (not the new one, and not the verified
        release N) — is never WRITTEN. It is listed in the report and nothing more. This is the
        class the whole verb exists to protect.
        Say it as WRITTEN, not "opened", because the weaker word is the true one and the stronger one
        would be a claim this function does not keep: `_held_tree` reads the destination through the
        SAME reader the gate uses, so a consumer-owned file's bytes ARE read. They have to be —
        "consumer-owned" is not a property of a path, it is `held minus what the releases ship`, so
        the only way to know a path belongs to that class is to enumerate what the destination holds.
        The read is CLASSIFICATION-ONLY and terminates there: those bytes are compared against
        nothing, never enter `writes`, and the path appears in the report by NAME alone. What
        SPEC-0195 guarantees is exactly this — "NEVER touches consumer-owned paths", "leaves
        consumer-owned files byte-identical" — a guarantee about MUTATION, which is kept structurally
        below. Overstating it as "never opened" would put a promise in this docstring that the code
        beneath it visibly breaks, and a comment that lies is worse than no comment.
      * UPSTREAM-OWNED is replaced wholesale where it is absent or already identical. Where it
        DIVERGES the ledger decides, and this is the one place the two specs meet: an entry in the
        override ledger makes the divergence REGISTERED, so the local bytes are PRESERVED and
        re-checked; no entry makes it a CONFLICT, reported and left exactly as it is. Never resolved
        silently in either direction — not by overwriting the project's fix, and not by keeping an
        edit nobody recorded.
      * TEMPLATE-OWNED is three-way merged against `base`, the pristine release-N tree: untouched
        locally → take the new one; unchanged upstream → keep the local one; both moved → CONFLICT.
      * DROPPED — a path release N shipped and release N+1 no longer carries (T-13506) — is REMOVED,
        but only on proof, because this is the one arm that deletes. The proof has two halves and
        both are required: `base` itself passes `verify_release` against the SAME anchor (so "release
        N shipped this path" is read from the tree its signed manifest's digest covers, never from
        whatever directory the operator pointed at — an unverified base may be a copy of the project,
        and then every project file equal to it would look dropped), and the held bytes EQUAL the
        release-N bytes (so nothing the project wrote is lost). Held bytes that differ → KEPT and
        named. A base that does not verify → nothing removed, each candidate KEPT and named with the
        reason. No base → no removal at all. Before this arm such a path fell into `skipped` and was
        reported as consumer-owned, so a file a release renamed stayed installed beside its
        replacement and the report read "no divergence".
        The base is NOT required to be the release the install's own manifest records: an install
        that an earlier engine already moved forward WITHOUT this arm still holds the stale files,
        and re-running the update with the release they came from is how they get cleaned up. The
        byte-equality with a VERIFIED release tree is what makes a removal safe, not the label.
        Removals are applied BEFORE writes, and a path that changed kind between the releases
        (file <-> directory) is settled at decision time: a write blocked by something this
        function will not delete is a `path-kind-collision` CONFLICT, never a mid-write exception.

    `base` IS WHAT MAKES ANY OF THIS DECIDABLE, and it is worth saying plainly. A divergence is
    `held != release N`, never `held != release N+1` — read the second way, every file N+1 changes
    looks like a local edit, so an ordinary version bump would report a tree full of conflicts and
    update nothing. The pinned release-N tree is the only thing that tells "the project edited this"
    apart from "the project is a version behind", and the destination cannot supply it: it holds the
    possibly-edited copy, and the manifest carries a whole-tree digest, not per-file hashes.

    So WITHOUT a `base` — or for a path the base does not carry — the comparison is not computable,
    and this REFUSES TO GUESS: the path is reported (`no-base` / `template-no-base`) and left exactly
    as it is. Guessing would either discard a project's work or freeze a stale file, and both are the
    silent resolution rule 8 forbids. An update run with a base is the ordinary path; one run without
    it is a report.

    Returns the report; it RAISES nothing and calls no `_die`, so both a verb and a test can read the
    same verdict. `cmd_release_update` is the thin shell that prints it and journals one row."""
    dest, into = Path(dest), Path(into)
    now = now or _utc_now()
    report = {
        "ok": False, "reasons": [], "destination": str(dest), "into": str(into),
        "replaced": [], "merged": [], "preserved": [], "skipped": [], "conflicts": [],
        "removed": [], "kept": [],
        "ledger": {"status": "not-read", "findings": []},
        "from_ref": None, "to_ref": None, "base": str(base) if base else None,
        # T-13629 — `capabilities` stays None unless a VERIFIED base lets the two releases be
        # compared; `capabilities_unread` then says why.
        "capabilities": None, "capabilities_from": None,
        "capabilities_unread": "no --from-release was given",
    }

    verdict = verify_release(dest, anchor, now=now)
    if not verdict.ok:
        report["reasons"] = list(verdict.reasons)
        return report
    # The version floor sits HERE for the same structural reason it does on the install path: it is
    # the only position where both facts exist and nothing has been touched yet.
    engine_manifest = read_manifest(running_engine_root())
    floor = check_version_floor(
        content_manifest=verdict.manifest,
        engine_version=str((engine_manifest or {}).get("source_ref") or ""),
        engine_manifest=engine_manifest)
    if not floor.ok:
        # The floor's status rides the refusal REASON, not a second report key — `floor.detail` names
        # the required version and the command that satisfies it, which is the whole actionable
        # content (SPEC-0195 rule 9).
        report["reasons"] = [floor.detail]
        return report

    new_tree = verdict.tree or {}
    manifest = verdict.manifest or {}
    report["to_ref"] = manifest.get("source_ref")
    report["from_ref"] = (read_manifest(into) or {}).get("source_ref")

    template_owned = set(_template_owned_surface(manifest))
    held = _held_tree(into)
    base_tree = _held_tree(Path(base)) if base else None

    ledger = read_override_ledger(into / "yitc-ops.yaml")
    # An entry vouches for a path only if it is WELL-FORMED. A malformed entry is reported (below,
    # by `ledger_drift`) and grants nothing — otherwise a typo in the vocabulary would be a way to
    # preserve a divergence without ever recording a valid one, which is the registration the whole
    # ledger exists to require.
    registered = {str(e.get("path")).strip()
                  for e in (ledger.get("entries") or [])
                  if isinstance(e, dict) and isinstance(e.get("path"), str)
                  and not _entry_shape_errors(e, None)}

    writes: dict = {}                                        # rel -> bytes, applied only at the end
    redundant_paths: list = []
    unregistered: list = []

    for rel in sorted(new_tree):
        theirs = new_tree[rel]
        ours = held.get(rel)
        # `was` — this path's bytes in the PINNED release N. It is the whole reason `base` exists:
        # divergence is `ours != was`, NEVER `ours != theirs`. Reading it the second way calls every
        # file the new release happens to change a local edit, which would report an ordinary
        # N -> N+1 bump as a tree full of conflicts and update nothing (caught by AC1's differential).
        was = base_tree.get(rel) if base_tree is not None else None
        undecidable = was is None and ours is not None and ours != theirs

        if rel in template_owned:
            if ours is None or ours == theirs:
                if ours != theirs:
                    writes[rel] = theirs
                    report["merged"].append(rel)
                continue
            if undecidable:
                report["conflicts"].append({
                    "path": rel, "kind": "template-no-base",
                    "detail": "a template-owned file differs from the new release and no pristine "
                              "release-N copy of it was supplied, so the three-way merge is not "
                              "computable — left untouched rather than guessed (SPEC-0195 rule 8)"})
                continue
            if ours == was:
                writes[rel] = theirs                         # untouched locally — take the new one
                report["merged"].append(rel)
            elif theirs == was:
                report["preserved"].append({"path": rel, "why": "template-owned, unchanged upstream"})
            else:
                report["conflicts"].append({
                    "path": rel, "kind": "template-both-modified",
                    "detail": "this template-owned file changed BOTH locally and upstream — left "
                              "unresolved in either direction (SPEC-0195 rule 8)"})
            continue

        # ── upstream-owned ──────────────────────────────────────────────────────────────────────
        if ours is None:
            writes[rel] = theirs                             # a file the release adds — nothing to lose
            report["replaced"].append(rel)
            continue
        if ours == theirs:
            if rel in registered:
                # The local bytes and the released bytes are now the SAME, and an entry still claims
                # a divergence: the release carries it (SPEC-0196 rule 4, delete-on-merge).
                redundant_paths.append(rel)
            continue
        if undecidable:
            # Held bytes differ from the new release and there is no release-N copy to compare them
            # with, so "the consumer edited this" and "the consumer is simply a version behind" are
            # indistinguishable. Both readings are guesses and one of them destroys a project's work,
            # so this reports and touches nothing (SPEC-0195 rule 8 — never resolved silently).
            report["conflicts"].append({
                "path": rel, "kind": "no-base",
                "detail": "this upstream-owned file differs from the new release and no pristine "
                          "release-N copy of it was supplied, so a local edit cannot be told apart "
                          "from an out-of-date file — left untouched rather than guessed. Supply the "
                          "pinned release-N tree to decide it."})
            continue
        if ours == was:
            writes[rel] = theirs                             # no local edit — just a version behind
            report["replaced"].append(rel)
            continue
        # A genuine LOCAL DIVERGENCE from the pinned release. This is the one place the two specs
        # meet: the ledger, and only the ledger, decides preserve-vs-conflict.
        if rel in registered:
            report["preserved"].append({
                "path": rel,
                "why": "a REGISTERED override — preserved and re-checked against its ledger entry "
                       "(SPEC-0196 rule 3)"})
        else:
            unregistered.append(rel)
            report["conflicts"].append({
                "path": rel, "kind": "unregistered-divergence",
                "detail": "an upstream-owned file was edited locally with NO override-ledger entry — "
                          "reported as a CONFLICT and never auto-resolved (SPEC-0195 rule 8 / "
                          "SPEC-0196 rule 3)"})

    # A registered path the new release no longer ships at all: the entry overrides nothing.
    for rel in sorted(registered - set(new_tree)):
        redundant_paths.append(rel)

    # ── DROPPED — release N shipped it, release N+1 does not (T-13506) ──────────────────────────
    # The one arm that DELETES, so it decides on the VERIFIED release-N snapshot (`base_verdict.tree`,
    # the gate's own read) and never on `base_tree`, which is whatever the operator's directory holds.
    removals: list = []
    proven_kept: set = set()
    if base is not None:
        base_verdict = verify_release(Path(base), anchor, now=now)
        if base_verdict.ok:
            old_tree = base_verdict.tree or {}
            # T-13629 — the kernel specs this update brings that release N did not have: the SAME
            # derivation the release notes render, over the two VERIFIED trees.
            try:
                report["capabilities"] = capabilities_to_consider(new_tree, old_tree)
                report["capabilities_from"] = (base_verdict.manifest or {}).get("source_ref")
                report["capabilities_unread"] = None
            except ValueError as exc:
                report["capabilities_unread"] = str(exc)
            for rel in sorted(set(old_tree) - set(new_tree)):
                ours = held.get(rel)
                if ours is None:
                    continue                                 # already gone — nothing to decide
                if ours == old_tree[rel]:
                    removals.append(rel)
                    report["removed"].append(rel)
                else:
                    proven_kept.add(rel)
                    report["kept"].append({
                        "path": rel,
                        "why": "the previous release shipped this path and the new one dropped it, "
                               "but it was changed locally — kept, not deleted"})
        else:
            unverified = "; ".join(base_verdict.reasons) or "no reason given"
            report["capabilities_unread"] = f"the --from-release tree did not verify: {unverified}"
            for rel in sorted(set(base_tree or {}) - set(new_tree)):
                if rel in held:
                    report["kept"].append({
                        "path": rel,
                        "why": "the --from-release tree did not verify against the anchor, so it "
                               "cannot prove the previous release shipped this path — kept, not "
                               f"deleted ({unverified})"})
    # Only a path the VERIFIED release-N tree proves was shipped leaves `skipped`. Under an
    # unverified base nothing is proven, so those candidates are NAMED in `kept` and still counted
    # where they were — a project's own file is never re-labelled on the word of an unverified tree.
    dropped = set(removals) | proven_kept

    # ── A PATH THAT CHANGED KIND between releases (file <-> directory) — decided HERE, never met as
    # an exception half-way through the writes. A release may drop the file `docs` and ship
    # `docs/index.md`, or the reverse. The removals below run BEFORE the writes, so an unchanged
    # dropped file (or a directory holding only such files) is already out of the way. What is NOT
    # out of the way is something this function will not delete: a dropped path that was KEPT, or
    # a project's own file. A write that would need to go through one of those is a CONFLICT —
    # reported, not written, and every other path of the update still lands.
    removal_set = set(removals)

    def _kind_collision(rel: str) -> "str | None":
        parts = rel.split("/")
        for i in range(1, len(parts)):
            anc = "/".join(parts[:i])
            p = into / anc
            if (p.is_symlink() or p.exists()) and not p.is_dir() and anc not in removal_set:
                return (f"the new release ships this path under `{anc}/`, but `{anc}` is a FILE "
                        "here that this update will not delete")
        p = into / rel
        if p.is_dir() and not p.is_symlink():
            for q in p.rglob("*"):
                if q.is_dir() and not q.is_symlink():
                    continue
                if q.relative_to(into).as_posix() not in removal_set:
                    return ("the new release ships this path as a FILE, but it is a DIRECTORY here "
                            f"holding `{q.relative_to(into).as_posix()}`, which this update will "
                            "not delete")
        return None

    for rel in sorted(writes):
        blocked = _kind_collision(rel)
        if blocked:
            del writes[rel]
            for key in ("replaced", "merged"):
                if rel in report[key]:
                    report[key].remove(rel)
            report["conflicts"].append({
                "path": rel, "kind": "path-kind-collision",
                "detail": f"{blocked} — left unwritten rather than forced (SPEC-0195 rule 8). Move "
                          "or remove what is in the way, then re-run the update."})

    report["skipped"] = sorted(rel for rel in held
                               if rel not in new_tree and rel not in template_owned
                               and rel not in dropped)

    report["ledger"] = ledger_drift(
        into / "yitc-ops.yaml", now=now, tasks_dir=into / "tasks",
        redundant_paths=redundant_paths, conflicts=unregistered)

    # THE ONLY MUTATIONS IN THIS FUNCTION, and they happen after every decision is made. Nothing is
    # written for a path the loop above classified as preserved, conflicted or consumer-owned — the
    # skip is structural (such a path never enters `writes`), not a cleanup pass.
    #
    # REMOVALS FIRST, THEN WRITES (T-13506). The order is load-bearing: a path that changed kind
    # between the releases needs the old file (or the old directory's files) gone before the new
    # path can be created. A directory a removal emptied goes with it (never `into` itself); one
    # still holding anything — a project file included — makes `rmdir` fail and is left as it is.
    for rel in removals:
        gone = into / rel
        gone.unlink(missing_ok=True)
        parent = gone.parent
        while parent != into:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    for rel in sorted(writes):
        out = into / rel
        if out.is_dir() and not out.is_symlink():
            # `_kind_collision` admitted this write, so no file is left under it — only empty
            # directories the pruning above did not reach. They hold nothing; clear them.
            for d in sorted((q for q in out.rglob("*")), reverse=True):
                d.rmdir()
            out.rmdir()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(writes[rel])

    report["ok"] = True
    return report


_WORKAROUND_FINGERPRINT_RE = re.compile(r"fingerprint:\s*`?([A-Za-z0-9_.:/-]+)`?")


def open_workaround_lessons(into) -> list:
    """T-12952 (SPEC-1000 rule 4) — the OPEN project-local workarounds `release update` reminds about.

    DERIVED, never stored: a lesson (`lessons/*.md`, SPEC-0090) is an open workaround when its
    frontmatter cites SPEC-1000, it is not `status: retired`, its body names a `fingerprint: X`, AND
    the project's journal carries a `deviation_captured` with `realm: kernel` and that same fingerprint.
    The lesson is the open/closed authority (a `deviation_resolved` does not hide a non-retired lesson);
    the kernel-realm deviation is the required provenance join — a lesson with no such deviation is not reported. Returns
    `[{"lesson": slug, "path": "lessons/<file>", "fingerprint": X}]` sorted by slug; unreadable files are skipped."""
    from lib import state
    into = Path(into)
    lessons_dir = into / "lessons"
    if not lessons_dir.is_dir():
        return []
    candidates = []
    for p in state.scan_lessons(lessons_dir):
        if p.name.startswith("_") or p.name == "README.md":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        parts = text.split("---", 2) if text.startswith("---") else None
        try:
            fm = (state.load_str(parts[1]) if parts and len(parts) == 3 else None) or {}
        except Exception:
            continue
        if not isinstance(fm, dict) or str(fm.get("status") or "").strip() == "retired":
            continue
        if "SPEC-1000" not in [str(c) for c in (fm.get("cites") or [])]:
            continue
        m = _WORKAROUND_FINGERPRINT_RE.search(parts[2])
        if m:
            candidates.append({"lesson": str(fm.get("lesson") or p.stem), "path": f"lessons/{p.name}",
                               "fingerprint": m.group(1)})
    if not candidates:
        return []
    # The join reuses the land-time auto-file readers (whole logical journal + hook-tail, SPEC-0190)
    # and the ONE realm predicate — no second journal reader.
    from lib import cross, worktree
    kernel_fps = {str((e.get("data") or {}).get("fingerprint") or "").strip()
                  for e in worktree._journal_deviation_events(into)
                  if cross.deviation_realm(e.get("data") or {}) == cross.DEVIATION_REALM_KERNEL}
    kernel_fps.discard("")
    return sorted((c for c in candidates if c["fingerprint"] in kernel_fps), key=lambda c: c["lesson"])


def cmd_release_update(args, *, _append_event, _die, _install_start_command=None) -> None:
    """`release update <dest> --into <path> --anchor <fp> --from-release <path>` — the verifying
    update entrypoint (SPEC-0195 rules 6 + 8).

    The thin shell over `update()`: it validates the operator's arguments, prints the report a human
    reads, and journals ONE row. The report itself — what was replaced, merged, preserved, skipped and
    conflicted — is computed by `update`, which writes nothing until it has decided everything."""
    dest = Path((getattr(args, "dest", None) or "").strip()).expanduser()
    into = Path((getattr(args, "into", None) or "").strip()).expanduser()
    anchor = (getattr(args, "anchor", None) or "").strip()
    base = (getattr(args, "from_release", None) or "").strip()
    if not anchor:
        _die("release update: --anchor SHA256:<fingerprint> required — the OUT-OF-BAND trust anchor "
             "(SPEC-0195 rule 7); an update that let the mirror name its own authority would verify "
             "nothing.")
    if not dest.is_dir():
        _die(f"release update: {dest} is not an existing directory")
    if not into.is_dir():
        _die(f"release update: --into {into} is not an existing directory — the first install is "
             "`release install`, and back-filling newly-added scaffolds is `init`. There is no "
             "second scaffold path (SPEC-0195 rule 8).")

    if not base:
        # Not a refusal — an update with no base is still a legal, useful READ (it reports every
        # undecidable path by name). Saying so out loud is the point: silence here would let an
        # operator read "0 replaced" as "already current".
        print("release update: no --from-release given, so a local edit cannot be told apart from an "
              "out-of-date file. Every differing path will be REPORTED and left untouched; supply "
              "the pinned release-N tree to actually update.")
    report = update(dest, into, anchor, base=Path(base).expanduser() if base else None)
    # T-13506: the two dropped-path lists, read once and tolerantly — a refused update carries none.
    removed, kept = report.get("removed") or [], report.get("kept") or []
    _append_event("release_updated", None, {
        "destination": str(dest), "into": str(into), "anchor": anchor, "ok": report["ok"],
        "from_ref": report.get("from_ref"), "to_ref": report.get("to_ref"),
        "replaced": len(report["replaced"]), "merged": len(report["merged"]),
        "preserved": len(report["preserved"]), "skipped": len(report["skipped"]),
        "conflicts": len(report["conflicts"]),
        "removed": len(removed), "kept": len(kept),
        # The ledger drift rides the EXISTING event rather than emitting a second one (CHARTER §P1
        # F2): "did this update happen, and what did it find" has one answer and one row.
        "ledger_status": report["ledger"].get("status"),
        "ledger_findings": len(report["ledger"].get("findings") or []),
        "reasons": report["reasons"],
    })
    if not report["ok"]:
        print(f"RELEASE UPDATE: REFUSED — {dest}")
        for reason in report["reasons"]:
            print(f"  - {reason}")
        _die(f"release update: REFUSED — NOTHING was written into {into}. A refused update leaves "
             "the destination exactly as it found it.")

    print(f"release_updated: {report.get('from_ref') or '(unknown)'} -> "
          f"{report.get('to_ref')} | {into}")
    print(f"  replaced {len(report['replaced'])} upstream-owned | merged {len(report['merged'])} "
          f"template-owned | preserved {len(report['preserved'])} | "
          f"skipped {len(report['skipped'])} consumer-owned (never written)")
    # T-13506: a path the previous release shipped and this one dropped is named either way — one
    # line per path, so a removal is never silent and a kept file is never mistaken for a current one.
    if removed or kept:
        print(f"  removed {len(removed)} dropped by this release | "
              f"kept {len(kept)} dropped but not deleted")
    for rel in removed:
        print(f"  REMOVED {rel}: the previous release shipped it, this release no longer does, and "
              "the installed copy was unchanged")
    for k in kept:
        print(f"  KEPT {k['path']}: {k['why']}")
    for c in report["conflicts"]:
        print(f"  CONFLICT [{c['kind']}] {c['path']}: {c['detail']}")
    for f in report["ledger"].get("findings") or []:
        print(f"  LEDGER {f['kind'].upper()} {f['path']}: {f['detail']}")
    if (not report["conflicts"] and not kept
            and not (report["ledger"].get("findings") or [])):
        print("  no divergence and no ledger drift — every consumer-owned path untouched")
    print(RESTART_REMINDER)   # T-13258 — unconditional, no session named, no liveness check
    # T-13429: the home start command an earlier engine wrote is refreshed with this release's text (a
    # person-edited one is left and reported) — install's writer, reached only after a successful update.
    if _install_start_command is not None:
        _install_start_command(into)
    # T-12952 (SPEC-1000 rule 4): a new release may have fixed the kernel defect a project-local
    # workaround stands in for — remind, derived from the open lessons; silent when none is open.
    open_workarounds = open_workaround_lessons(into)
    if open_workarounds:
        print(f"open workarounds: {len(open_workarounds)} — this release may fix the kernel defect behind "
              "them; re-try the normal path, and if it now works remove the workaround and retire the "
              "lesson (SPEC-1000 rule 4):")
        for w in open_workarounds:
            print(f"  - {w['path']} (deviation {w['fingerprint']})")
    # T-13240 (SPEC-0197 rule 4): the notes of the release just installed name the proposals it
    # answers — an adopter's AI kept pasting workarounds for issues a release had already fixed.
    answered = release_notes_answers(dest)
    if answered:
        print(f"this release answers: {', '.join(answered)} — drop any local workaround you kept for "
              "these (an env override, an extra in a worker brief or prompt, a handoff note) and "
              "re-try the normal path (SPEC-0197 rule 4).")
    # T-13629: LAST — the kernel specs that became active between the two releases, rendered by the
    # same line helper as the notes' «Capabilities to consider» section.
    caps = report.get("capabilities")
    span = f"{report.get('capabilities_from') or '(unknown)'} and {report.get('to_ref') or '(unknown)'}"
    if caps is None:
        print("capabilities to consider: not computed — it compares this release with the previous "
              f"one, which needs a verified --from-release ({report.get('capabilities_unread')}).")
    elif not caps:
        print(f"capabilities to consider: none — no kernel spec became active between {span}.")
    else:
        print(f"capabilities to consider: {len(caps)} kernel spec(s) became active between {span} — "
              "capabilities this update adds; turn on the ones you want:")
        for line in capability_lines(caps, indent="  "):
            print(line)


def release_notes_answers(release_dir) -> tuple:
    """The `answers:` ids the release notes in `release_dir` name, or `()` (T-13240).

    Reads the fenced yaml block `render_release_notes` writes under its answers heading, from the
    tree `update()` has just verified. Report-only: a missing file, a missing block or one that will
    not parse reads as "nothing to say", never a refusal — the update itself already succeeded.
    """
    try:
        text = (Path(release_dir) / RELEASE_NOTES_FILENAME).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    m = re.search(r"^## Proposals this release answers\n.*?^```yaml\n(.*?)^```", text,
                  re.MULTILINE | re.DOTALL)
    if not m:
        return ()
    try:
        raw = (state.load_str(m.group(1)) or {}).get("answers")
    except Exception:  # noqa: BLE001 — unreadable notes are silence here, never a crash
        return ()
    if not isinstance(raw, (list, tuple)):
        return ()
    out = []
    for item in raw:
        aid = str(item).strip()
        if ANSWER_ID_RE.match(aid) and aid not in out:
            out.append(aid)
    return tuple(out)


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# T-12389 — `release check`: IS THERE AN UPDATE? A READ-ONLY REPORT, NEVER A GATE.
#
# The pin (SPEC-0195 rule 3) already says which engine release a consumer RUNS; nothing said whether
# a NEWER one exists. Answering it by hand meant knowing to list the mirror's tags and compare them
# with the pin — knowledge the verb now carries instead of the operator.
#
# THE ONE PREMISE EVERYTHING BELOW RESTS ON: `release_repo` IS A LOCAL PATH. Rule 3's born template
# spells it «<absolute path to the local clone of the published release mirror>», and
# `init.resolve_engine_pin` enforces exactly that — a value not starting with `/` is refused
# `pin-unresolved`, and `_materialize_tagged_release` refuses a directory without a `.git`. So the
# tags and the notes are read with `git -C <release_repo>` against a local clone and NOTHING here
# touches the network. Admitting a remote URL would be a change to rule 3 itself, not to this verb.
#
# WRITES NOTHING, on every path: no event is emitted (the verb is given no emit channel at all), no
# cache and no store is added, and the parser row carries `no_autosync=True` for the reason
# `release verify`/`release install` carry it (T-12173) — `_auto_sync` would materialise
# `events.jsonl` in the target checkout BEFORE the verb ran, a write performed on the behalf of a
# verb whose contract is that there are none.
# ─────────────────────────────────────────────────────────────────────────────────────────────────

CHECK_NOTES_HEAD_LINES = 12
# How much of a newer release's notes the report shows. A HEAD, not the whole file: the question
# being answered is "should I look at this release?", and a full RELEASE-NOTES.md per newer tag
# would bury the one line that answers it. The pointer to the full text is the tag itself.

_CHECK_GIT_TIMEOUT = 60   # the same bound `_names_moving_ref` / `_materialize_tagged_release` use


def _check_git(release_repo, argv: list):
    """Run one read-only `git -C <release_repo> …` and return its stdout, or None on ANY failure.

    THE REASON THIS EXISTS RATHER THAN INLINE `subprocess` CALLS: the verb's contract is that a
    branch pin or an unreachable mirror is «a plain error line, never a traceback». Routing every
    git call through one wrapper that swallows the failure into a None makes that property
    STRUCTURAL — a new call site cannot forget it — instead of a promise each call site keeps on its
    own. The CALLER turns a None into the named line, because only it knows what was being asked.
    """
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    import subprocess

    try:
        proc = subprocess.run(["git", "-C", str(release_repo)] + list(argv),
                              capture_output=True, text=True, timeout=_CHECK_GIT_TIMEOUT,
                              env=_git_env._git_child_env())
    except Exception:  # noqa: BLE001 — git missing/hanging/failing is UNANSWERABLE, never a crash
        return None
    return proc.stdout if proc.returncode == 0 else None


def release_tags(release_repo) -> list:
    """The mirror's RELEASE tags, ordered oldest → newest. `[]` when the repo cannot be read.

    ORDER COMES FROM `parse_release_version` + `_compare` — the SAME zero-extending tuple comparison
    the version floor already uses, so `v1.2` and `v1.2.0` order equal here exactly as they compare
    equal there, and `v1.10.0` sorts ABOVE `v1.9.0` where git's lexical tag order would not. A
    second ordering would be a second answer to one question (CHARTER §P5).

    A tag `parse_release_version` rejects is DROPPED rather than sorted last: the mirror may carry
    tags that are not releases, and guessing a version for one would let a non-release tag be
    reported as an available update.
    """
    out = _check_git(release_repo, ["tag", "--list"])
    if out is None:
        return []
    parsed = [(parse_release_version(line.strip()), line.strip()) for line in out.splitlines()
              if line.strip()]
    import functools
    return [tag for _v, tag in
            sorted(((v, t) for v, t in parsed if v is not None),
                   key=functools.cmp_to_key(lambda a, b: _compare(a[0], b[0])))]


def release_notes_head(release_repo, tag: str, lines: int = CHECK_NOTES_HEAD_LINES) -> list:
    """The first `lines` non-trivial lines of `RELEASE-NOTES.md` AS OF `tag`, or `[]`.

    READ FROM THE TAG'S BLOB (`git show <tag>:<file>`), never from the mirror's working tree: a
    clone parked on some other branch must not be able to present its checked-out notes as the
    notes of a release the operator has not got. This is the same "the bytes are the tag's"
    discipline `_materialize_tagged_release` keeps for the release tree itself.

    An empty list is a legitimate answer (a release that shipped no notes, or a mirror that will not
    answer) and the caller SAYS so — it never fabricates a summary.
    """
    out = _check_git(release_repo, ["show", f"{tag}:{RELEASE_NOTES_FILENAME}"])
    if out is None:
        return []
    head = []
    for line in out.splitlines():
        if line.strip():
            head.append(line.rstrip())
        if len(head) >= lines:
            break
    return head


def cmd_release_check(args, *, repo_path, _die=None) -> None:
    """`bin/yitc-v2 -C <project> release check` — does a NEWER release exist on this project's mirror?

    READ-ONLY and EXIT 0 ALWAYS. It is a REPORT, not a gate: `_die` is never called from here (the
    parameter is accepted for call-site symmetry with its `release verify` / `release install`
    siblings, and so that a future refusing sibling does not have to change the signature), every
    branch returns normally, and the two failure branches print one named line each.

    IT STATES ITS SILENCE — the `frontend-errors` precedent (SPEC-0171): an EXPLICITLY INVOKED view
    says why it has nothing to say, where a suppressed-when-clean session-start echo would print
    nothing. A project carrying the born `kernel:` WAIVER declares no `engine:` mapping, reads
    `not-declared`, and gets that sentence plus the one thing that would end the silence — because
    silent output from a verb the operator deliberately ran is indistinguishable from "up to date",
    which is the single worst answer this verb could give.

    TWO READERS, ZERO RE-PARSING (the card's constraint): `resolve_engine_pin` supplies the status
    vocabulary, the pinned ref and a printable `detail`; `_kernel_declaration` supplies
    `release_repo`, which the pin dict does not carry and which this verb needs to read the mirror.
    Both are `init`'s own carrier readers, so `yitc-ops.yaml` is parsed HERE not at all.
    """
    from lib import init as init_mod

    # T-13258: the running engine version first, on EVERY branch — the post-/compact re-fold of the
    # same line `session start` prints.
    print(engine_version_line())
    pin = init_mod.resolve_engine_pin(repo_path)
    status = pin.get("status")
    detail = (pin.get("detail") or "").strip()

    if status == "not-declared":
        print(f"release check: {repo_path} declares no `kernel.engine` pin, so there is no pinned "
              f"release to compare a mirror against — nothing to report, and that is a state, not a "
              f"failure.")
        print(f"  what would end this silence: declare `kernel: {{engine: {{release_repo, release}}}}` "
              f"in yitc-ops.yaml (SPEC-0195 rule 3) — an absolute path to the local clone of the "
              f"published mirror, plus the exact annotated release tag it runs.")
        return

    if status == "unreadable":
        # NEVER folded into `not-declared` above. "The carrier will not parse" and "the carrier
        # declares nothing" look alike in the output and have completely different next actions.
        print(f"release check: cannot tell — {detail}")
        return

    if status in ("moving-ref", "pin-unresolved"):
        # The two states AC3 names (a branch pin; an absent/unreachable `release_repo`). `detail`
        # already names the cause and the fix in the pin resolver's own words; re-wording it here
        # would give the same defect two descriptions that could drift apart.
        print(f"release check: the pin does not resolve, so no comparison is possible — {detail}")
        return

    engine = init_mod._kernel_declaration(repo_path)
    release_repo = str((engine or {}).get("release_repo") or "").strip()
    pinned_ref = str(pin.get("ref") or "").strip()
    pinned = parse_release_version(pinned_ref)

    tags = release_tags(release_repo)
    if not tags:
        print(f"release check: the pin resolves, but {release_repo} lists no release tags — the "
              f"mirror cannot be asked whether a newer release exists.")
        return
    if pinned is None:
        # The pin RESOLVED (so the tag exists) but is not a version this ordering understands, which
        # makes "newer" undefined rather than false. Saying so beats silently reporting the mirror's
        # newest tag as an available update.
        print(f"release check: pinned {pinned_ref} · newest {tags[-1]} — but {pinned_ref} is not a "
              f"`vN.N.N` release version, so how far behind it is cannot be computed.")
        return

    newer = [t for t in tags if _compare(parse_release_version(t), pinned) > 0]
    if not newer:
        print(f"release check: pinned {pinned_ref} · newest {tags[-1]} · UP TO DATE — "
              f"{release_repo} carries no release newer than the pin.")
        return

    print(f"release check: pinned {pinned_ref} · newest {tags[-1]} · BEHIND BY {len(newer)} "
          f"release(s) on {release_repo}")
    for tag in newer:
        print(f"\n  {tag} — {RELEASE_NOTES_FILENAME}:")
        head = release_notes_head(release_repo, tag)
        if not head:
            print(f"    (no {RELEASE_NOTES_FILENAME} at {tag}, or the mirror would not read it)")
            continue
        for line in head:
            print(f"    {line}")
    print(f"\n  this is a REPORT, not a gate — nothing was written. To move the pin, see "
          f"`release update`.")


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# T-13223 — the SESSION-START face of `release check`: tell a newcomer a newer release is published.
#
# `release check` answers only when someone knows to run it, and a non-IT newcomer never does (the
# onboarding gap analysis 2026-09-29; owner decision events.jsonl#ts=2026-09-29T06:16:07Z). So a
# `-C` consumer `session start` asks the SAME question — through the SAME pin reader and the SAME
# version order as the verb above, never a second answer — and prints ONE report-only line when the
# answer is "yes". Its post-/compact re-fold is `release check` itself (SPEC-0007 §5b).
#
# FOUR PROPERTIES, each a card constraint:
#   * AT MOST ONCE A DAY — the answer is cached per UTC day in a machine-local file under the
#     checkout's GIT DIR (never the working tree, so it can never read as dirt; the graph result
#     cache's placement, SPEC-0031). A concurrent start that loses the claim prints nothing.
#   * NEVER BLOCKS — the one network call is a read-only `git ls-remote --tags` of the mirror
#     clone's own remote, bounded by `_START_CHECK_TIMEOUT`; no fetch, no write to the mirror.
#   * NEVER FAILS THE START — every failure, offline included, is silence (`None`).
#   * NOTHING IS UPDATED — the line names the phrase to say; moving the pin stays `release update`.
# ─────────────────────────────────────────────────────────────────────────────────────────────────

START_CHECK_CACHE_NAME = "yitc-release-check.json"


_START_CHECK_TIMEOUT = 5   # seconds — short by design: a start must never wait on a network


def _start_check_timeout() -> float:
    """The mirror-contact bound: `YITC_RELEASE_START_TIMEOUT` if it parses, clamped to 0.1..30 s,
    else `_START_CHECK_TIMEOUT`. Clamped so no setting can turn a start into an unbounded wait."""
    import os

    try:
        return min(30.0, max(0.1, float(os.environ["YITC_RELEASE_START_TIMEOUT"])))
    except (KeyError, ValueError):
        return float(_START_CHECK_TIMEOUT)


def _mirror_release_tags(release_repo, timeout: float) -> "list | None":
    """The release tags the mirror clone KNOWS plus those its own remote PUBLISHES, oldest → newest.

    The local clone alone never learns of a newer tag (nothing fetches it), so the remote half is
    what makes this useful; it is `ls-remote` — a read — never a fetch. `None` when neither half
    answered, which the caller reads as "cannot tell" and turns into silence.
    """
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    import functools
    import os
    import subprocess

    names = set()
    answered = False
    local = _check_git(release_repo, ["tag", "--list"])
    if local is not None:
        answered = True
        names.update(line.strip() for line in local.splitlines() if line.strip())
    try:
        proc = subprocess.run(["git", "-C", str(release_repo), "ls-remote", "--tags"],
                              capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL,
                              env=_git_env._git_child_env(dict(os.environ, GIT_TERMINAL_PROMPT="0")))
        if proc.returncode == 0:
            answered = True
            for line in proc.stdout.splitlines():
                ref = line.split("\t", 1)[-1].strip()
                if ref.startswith("refs/tags/"):
                    names.add(ref[len("refs/tags/"):].removesuffix("^{}"))
    except Exception:  # noqa: BLE001 — offline / hanging remote is "cannot tell", never a crash
        pass
    if not answered:
        return None
    parsed = [(parse_release_version(n), n) for n in names]
    return [t for _v, t in sorted(((v, t) for v, t in parsed if v is not None),
                                  key=functools.cmp_to_key(lambda a, b: _compare(a[0], b[0])))]


_DIGIT_MEANING = (
    ("FIRST", "a new methodology generation"),
    ("MIDDLE", "behaviour or what `init` writes changes, and the update may ask you to act"),
    ("LAST", "fixes only — nothing to do on update"),
)


def moved_digit(installed: tuple, newest: tuple) -> tuple:
    """(name, meaning) of the MOST SIGNIFICANT component that moved, per SPEC-0195 rule 10.

    Most significant, not least: v2.1.9 → v2.2.0 moved the MIDDLE digit (and reset the last), so
    reading the first differing position from the LEFT is the rule's "the highest one wins".
    """
    a = (tuple(installed) + (0, 0, 0))[:3]
    b = (tuple(newest) + (0, 0, 0))[:3]
    for i in range(3):
        if a[i] != b[i]:
            return _DIGIT_MEANING[i]
    return _DIGIT_MEANING[2]


def session_release_line(repo_path, *, cache_dir, today=None, cli="bin/yitc-v2",
                         _mirror_tags=None) -> "str | None":
    """ONE report-only line when a release newer than the pin is published, else `None`. NEVER raises.

    `cache_dir` is the checkout's git dir. The cache holds the mirror's NEWEST tag for
    (day, release_repo) and which (pin -> newest) pair was already announced that day: a same-day
    start never contacts the mirror and never repeats the line; a pin moved during the day is
    compared afresh (the line disappears as soon as the update lands).
    """
    try:
        return _session_release_line(repo_path, cache_dir=cache_dir, today=today, cli=cli,
                                     _mirror_tags=_mirror_tags or _mirror_release_tags)
    except Exception:  # noqa: BLE001 — a start must never fail on a report-only notice
        return None


def _session_release_line(repo_path, *, cache_dir, today, cli, _mirror_tags):
    import datetime
    import fcntl
    import json
    import os
    from pathlib import Path

    from lib import init as init_mod

    engine = init_mod._kernel_declaration(repo_path)
    if not isinstance(engine, dict):
        return None
    pinned_ref = str(engine.get("release") or "").strip()
    release_repo = str(engine.get("release_repo") or "").strip()
    pinned = parse_release_version(pinned_ref)
    if pinned is None or not release_repo.startswith("/"):
        return None
    day = today or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    cache = Path(cache_dir) / START_CHECK_CACHE_NAME
    # ONE non-blocking claim covers both the daily mirror contact and the daily notice, so two
    # overlapping starts can neither both ask the mirror nor both print: the loser stays silent.
    with open(Path(cache_dir) / "yitc-release-check.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — absent / torn cache is a miss
            data = {}
        if data.get("day") != day or data.get("release_repo") != release_repo:
            tags = _mirror_tags(release_repo, _start_check_timeout())
            data = {"day": day, "release_repo": release_repo,
                    "newest": tags[-1] if tags else None, "notified": None}
        newest = data.get("newest")
        newest_v = parse_release_version(newest)
        due = newest_v is not None and _compare(newest_v, pinned) > 0
        told = f"{pinned_ref}->{newest}"
        if due and data.get("notified") == told:
            due = False   # this person was already told today — at most once a day
        elif due:
            data["notified"] = told
        tmp = cache.with_name(f"{cache.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, cache)
    if not due:
        return None
    digit, meaning = moved_digit(pinned, newest_v)
    return (f"release: a newer engine release is published — installed {pinned_ref} · newest "
            f"{newest} · the {digit} digit moved: {meaning} (SPEC-0195 rule 10). Nothing was "
            f"updated. To update, say «update the engine to {newest}»; its notes: "
            f"`{cli} -C {repo_path} release check`.")
