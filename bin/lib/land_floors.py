"""land_floors — the ANY-AUTHOR land-time FLOOR atoms (SPEC-0163 policy · SPEC-0093 `verify.floor`
shape), extracted byte-identical from `bin/lib/worktree.py` (T-12695, card C3 of plan
`extract-the-13-over-budget-bin-lib-modules-into-le`).

WHAT IS IN HERE. The 26-symbol `_floor_*` family of plan §Extraction map C3 — the declaration-read
refusals, the tracked-inventory / changed-paths / added-line readers, the secrets, dependencies and
probes atoms with their carrier-history and requirements-pinning helpers, the declared-command env /
keys / drift readers, the trusted-executable check and the project-command runner — plus the nine
`_FLOOR_*` constants exclusive to them — module-local here, AND handed to each reader as a keyword-only
inject whose DEFAULT is that module-local value: a direct call reads the leaf's constant, while the host
residue re-supplies the HOST alias at call time, so `monkeypatch.setattr(worktree, "_FLOOR_X", ...)`
still reaches the moved body exactly as it reached the original (audit-post r1 finding 1 of this card —
a static alias alone would have silently retired that rebind path; `tests/test_t12695_land_floors_residue_rebinding.py`
is the differential).

NOT IN HERE, AND THIS IS THE SEAM DECISION RATHER THAN AN OMISSION: `_any_author_land_floor` (the
layer's orchestrator — the CALLER of these atoms), the `_base_*` trusted-base readers, and the two
post-baseline defs `_floor_command_program` / `_floor_bootstrap_verdict` (T-12688) — the frozen
manifest is EXACT, so they STAY in the host and reach this module by injection where a mover needs
them. `KERNEL_FLOOR_LAYER`, `_FLOOR_COMMAND_TIMEOUT_S` and `_FLOOR_INTERPRETERS` also stay: each is
read by a host stayer.

SEAM (the T-9340 / T-9341 / T-11519 / T-11522 / T-11523 / T-11524 full inject-residue shape,
`lessons/library-extraction.md` §AST-freeze generator): bodies and signatures are spliced VERBATIM
from the original source — never `ast.unparse`, which reformats and loses byte-identity — and every
non-stdlib free name (host stayers, host globals, AND moved siblings via their host residue) arrives
as a keyword-only injected parameter, computed with `symtable` over each function's scope SUBTREE.
The host keeps a `functools.wraps` residue under every historical name, so the tests and every
`worktree.<sym>` reader keep resolving and stay out of this diff — and `inspect.getsource(worktree.<sym>)`
unwraps to the REAL body here. `_floor_scan_files` is a generator, so its residue forwards with
`yield from` (`inspect.isgeneratorfunction` contract).

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports only stdlib and the lower
leaves `lib.state` / `lib.journal`; it NEVER back-imports the host. Intentionally spec-less
(SPEC-0005 admission test): a byte-identical relocation mints no standing rule — the governing specs
keep their homes.
"""
from __future__ import annotations

import datetime
import hashlib
import io
import json
import os
import re
from pathlib import Path

from lib import events as events_mod    # the ONE segment-set / archive-naming resolver
from lib import journal as journal_mod  # the shared bounded tail-scan journal reader
from lib import state


#: NAMED, HIGH-CONFIDENCE credential shapes only — no entropy heuristics (CHARTER non-goal «no
#: scanner platform»; the zero-false-positive stance). Each entry is (label, compiled pattern). A
#: shape here must be one whose match is a credential essentially by construction, because this
#: gate REFUSES a land: a false positive costs a human a blocked ship, which is the failure mode
#: that gets a security gate disabled.
_FLOOR_SECRET_PATTERNS = (
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Stripe secret key", re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("OpenAI/Anthropic API key", re.compile(r"\b(?:sk-ant-|sk-proj-)[A-Za-z0-9_-]{20,}\b")),
    ("PostgreSQL URL with password",
     re.compile(r"\bpostgres(?:ql)?://[^\s:/@]+:(?P<secret>[^\s:/@]{6,})@")),
)

#: The five INTERPOLATION shapes a configuration TEMPLATE writes where a credential would go. A
#: token of this shape is not a credential by construction — there is nothing to remove and nothing
#: to rotate, so a refusal naming it states an unsatisfiable remedy (X-1358/X-1359: <project>'s land
#: was refused on `postgresql://${PG_USER}:${PG_PASSWORD}@...`, a line unchanged on main since
#: 2026-08-13, and rule 4a leaves a consumer no relief at all).
_FLOOR_INTERPOLATION = re.compile(r"""
      \$\{[^{}]*\}                 # ${VAR} / ${VAR:-default} — POSIX shell expansion
    | \$[A-Za-z_][A-Za-z0-9_]*     # $VAR — bare shell expansion
    | \{\{[^{}]*\}\}               # {{var}} — jinja / handlebars / go template
    | %\([^()]*\)[A-Za-z]         # %(var)s — python percent-format
    | <[^<>]*>                    # <placeholder> — the documentation convention
""", re.VERBOSE)

#: Dependency MANIFESTS and the lockfile(s) that pin them. A manifest present with NO lock is the
#: unpinned-dependency refusal.
#:
#: `requirements.txt` is DELIBERATELY NOT LISTED as a `pyproject.toml` lock (audit-post r2 finding
#: 3). It used to be, and because the generic "does any named lock EXIST?" test runs first and
#: `continue`s on a hit, an UNPINNED `requirements.txt` (`flask`, `requests>=2`) satisfied the lock
#: requirement outright — `_floor_requirements_fully_pinned` was never reached for the one input it
#: was written to refuse. A requirements file is its own lock only when EVERY requirement is `==`
#: pinned, so that PREDICATE is the whole test and it is applied separately, below, where an
#: existence check cannot short-circuit it.
_FLOOR_MANIFEST_LOCKS = (
    ("package.json", ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")),
    ("pyproject.toml", ("poetry.lock", "uv.lock", "pdm.lock")),
    ("Gemfile", ("Gemfile.lock",)),
    ("Cargo.toml", ("Cargo.lock",)),
    ("go.mod", ("go.sum",)),
    ("mix.exs", ("mix.lock",)),
    ("composer.json", ("composer.lock",)),
)

#: `verify.floor` atom names — the three the kernel runs. A project may declare a `command:` under
#: any of them (ALWAYS ADDITIVE), and `probes` additionally carries `max_age_days`.
_FLOOR_ATOMS = ("secrets", "dependencies", "probes")

#: Default freshness bound for a declared SPEC-0098 probe's latest passing verdict (days).
_FLOOR_PROBE_MAX_AGE_DAYS = 30

#: The LAUNCHING SESSION'S OWN STATE carriers a `verify.floor.<atom>.command` child does not see
#: (audit-post r3 finding 1). Same criterion as `hermetic_child_env`'s scrub half — an env var whose
#: value is the running session's identity or journal binding, which would make a candidate-declared
#: command's answer depend on WHO started the land. Spelled here rather than imported from the
#: `bin/yitc-v2` identity registry because `bin/lib/worktree.py` has no import of it and the T-11280
#: one-entry-point reader contract is not widened for a scrub list; the mirror is the same shape
#: `_pinned_verify_subprocess_env` already carries for the pinned re-run.
_FLOOR_COMMAND_SCRUBBED_CARRIERS = (
    "YITC_SESSION_REF", "YITC_EXPECTED_SESSION_REF", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID",
    "YITC_EVENTS_PATH_DEFAULT", "YITC_EVENTS_GUARD_ROOT", "YITC_EVENTS_SINK", "YITC_REPO_ROOT",
    "YITC_LAND_HELD_TURN_PID",
)

#: How far ahead of now a floor-read timestamp may sit before it stops being evidence about the
#: present (audit-post r3 finding 9). Generous enough to absorb ordinary clock skew between the box
#: that wrote a probe row and the one running the land; far short of the "sorts above everything"
#: values a malformed or forged timestamp reaches for.
_FLOOR_MAX_FUTURE_SKEW_DAYS = 1

#: `requirements.txt` directives that bring NO dependency of their own — index/link/format/hash-policy
#: knobs. `_floor_requirements_fully_pinned` skips exactly these and treats EVERY OTHER leading-`-`
#: line (`-r` / `--requirement`, `-c` / `--constraint`, `-e` / `--editable`) as dependency-bearing and
#: therefore UNPINNED (audit-post r3 finding 5). Enumerated rather than pattern-matched so the
#: admission criterion is visible: a directive joins this tuple only when it cannot add a requirement.
_FLOOR_REQUIREMENTS_INERT_OPTIONS = frozenset((
    "-i", "--index-url", "--extra-index-url", "-f", "--find-links", "--no-index",
    "--trusted-host", "--no-binary", "--only-binary", "--prefer-binary", "--require-hashes",
    "--pre", "--use-feature", "--use-deprecated", "--no-build-isolation",
))

#: A `-U0` hunk header. BOTH counts are OPTIONAL because git OMITS a count of 1 — `@@ -1,0 +2 @@` is
#: a valid one-line hunk, and reading it as unparseable would silently widen that path to a
#: whole-file scan (audit-pre finding 2). A `+c,0` hunk adds nothing at that point.
_FLOOR_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _floor_is_interpolation(token: "str | None", *, _FLOOR_INTERPOLATION=_FLOOR_INTERPOLATION) -> bool:
    """Is this captured secret token a WHOLE template interpolation rather than a credential?

    FULLMATCH, NOT SEARCH — the exemption covers the token ENTIRELY or not at all. That is the
    fail-closed direction and it is the whole safety argument for a negative clause on a security
    gate: `pw_${SUFFIX}` CONTAINS an interpolation while still carrying the literal `pw_`, so it is
    NOT exempt and still refuses. A partial exemption would let a real secret be hidden by
    concatenating a variable onto it, which would be a false green — the one failure a credential
    floor may not have. A false POSITIVE, by contrast, costs a human a blocked ship, which is the
    failure mode that gets a security gate disabled (the sibling comment on `_FLOOR_SECRET_PATTERNS`);
    this clause exists to remove exactly the false positives that are certain.

    `None` — a pattern that declares no `secret` group — is NEVER an interpolation. Seven of the
    eight named shapes are literal-prefixed runs (`AKIA`/`ASIA`, the PEM header, `gh[pousr]_`,
    `xox[abprs]-`, `sk_live_`, `AIza`, `sk-ant-`/`sk-proj-`) that cannot admit an interpolation
    character at all, so they declare no group and their verdicts are bit-for-bit unchanged. The
    group is a per-pattern OPT-IN, not a global weakening."""
    return bool(token) and bool(_FLOOR_INTERPOLATION.fullmatch(token))


def _floor_section(ops) -> dict:
    """The `verify.floor` mapping from an already-parsed carrier, or `{}`. Never raises."""
    ver = ops.get("verify") if isinstance(ops, dict) else None
    floor = ver.get("floor") if isinstance(ver, dict) else None
    return floor if isinstance(floor, dict) else {}


def _floor_declaration_refusals(ops, layers, *, CONSUMER_OPS_CONTRACT, KERNEL_FLOOR_LAYER, _FLOOR_ATOMS=_FLOOR_ATOMS, _declared_verify_infra_globs, _floor_section) -> list:
    """The DECLARATION-READ refusals (SPEC-0093 `verify.floor`): a project declares HOW, never
    WHETHER. Any `waiver:` at or under `verify.floor`, or a `verify.layers` entry wearing the
    reserved `KERNEL_FLOOR_LAYER` name, is REFUSED here — BEFORE any atom runs, so an attempt to
    waive the floor's EXISTENCE fails at the declaration rather than quietly producing a land with
    no floor."""
    out = []
    floor = _floor_section(ops)
    if "waiver" in floor:
        out.append(f"land(floor): {CONSUMER_OPS_CONTRACT} `verify.floor.waiver` is REFUSED — the "
                   f"any-author land floor is kernel-provided and UNWAIVABLE. A project declares HOW "
                   f"an atom runs (`verify.floor.<atom>.command`, always ADDITIVE to the kernel "
                   f"check), never WHETHER the floor exists (SPEC-0163 policy; SPEC-0093 shape).")
    for atom in _FLOOR_ATOMS:
        entry = floor.get(atom)
        if isinstance(entry, dict) and "waiver" in entry:
            out.append(f"land(floor): {CONSUMER_OPS_CONTRACT} `verify.floor.{atom}.waiver` is REFUSED "
                       f"— an atom of the any-author floor cannot be waived, only re-declared "
                       f"ADDITIVELY via `verify.floor.{atom}.command` (SPEC-0093 `verify.floor`).")
    for i, ly in enumerate(layers if isinstance(layers, list) else []):
        if isinstance(ly, dict) and str(ly.get("layer") or "").strip() == KERNEL_FLOOR_LAYER:
            out.append(f"land(floor): {CONSUMER_OPS_CONTRACT} `verify.layers[{i}]` uses the RESERVED "
                       f"layer name {KERNEL_FLOOR_LAYER!r} — that name belongs to the kernel floor, "
                       f"and a project layer wearing it would read as the floor without being it. "
                       f"Rename the layer (SPEC-0093 `verify.floor`).")
    # T-12587 — a SUBTRACTIVE `verify.infra_globs` declaration is the same class as a floor waiver: an
    # attempt to shrink a kernel guard. Refused at the declaration read, by name, on the same seam.
    out.extend(_declared_verify_infra_globs(ops)[1])
    return out


def _floor_tracked_inventory(worktree: Path, _run_git_cap) -> tuple:
    """`(relpaths, errors)` — the tracked-file inventory of the candidate tree, enumerated ONCE per
    floor invocation and THREADED into every atom that needs it (audit-post r3 finding 11).

    Both the secrets atom's whole-tree scan and the dependency atom's manifest discovery ask the same
    question of git — "what does this tree track?" — and each used to run its own `git ls-files -z`.
    On a large shared repo that is a second full index walk per land for an answer the first walk
    already produced. One resolution also removes a subtler hazard than the duplicated work: two
    enumerations are two SNAPSHOTS, so a tree mutating under a land could have the secrets atom and
    the dependency atom reasoning about different file sets and neither noticing.

    FAIL-CLOSED, and the failure is carried in `errors` rather than raised: `relpaths` is `None`
    exactly when the tree could NOT be enumerated, and every consumer then refuses rather than
    reporting a clean scan of a tree it never saw."""
    if _run_git_cap is None:
        return None, ["the tracked-file enumeration is unavailable (no git runner)"]
    r = _run_git_cap(["ls-files", "-z"], worktree)
    if r.returncode != 0:
        return None, [f"`git ls-files` failed (exit {r.returncode}) — the tracked tree could not be "
                      f"enumerated"]
    return [rel for rel in (p.strip() for p in r.stdout.split("\0")) if rel], []


def _floor_changed_paths(worktree: Path, base_ref, _run_git_cap) -> "list | None":
    """The tracked paths this ship ADDED or MODIFIED against `base_ref`. `None` when the diff cannot
    be resolved — the caller then falls back to the whole tracked tree, never to an empty scan.

    PATHS, NOT PATCH LINES (audit-post r3 finding 2). This used to return the `+` lines of
    `git diff --unified=0`, and that made the diff-scoped secrets scan false-green on any change git
    does not render as text: a NEW file containing a NUL byte is reported as `Binary files ... differ`
    with no `+` lines at all, and a path whose `.gitattributes` mark suppresses the diff produces none
    either. A tracked file holding a NUL prefix and a plain `AKIA...` further in therefore landed
    through a scan that reported clean — the same attacker-selectable bypass the whole-tree scan's own
    NUL exclusion had one layer down (r2 finding 2), reintroduced through the diff renderer instead of
    through a content test. Asking git for the changed PATHS and then scanning their CONTENT at the
    candidate makes the answer independent of how the diff renders."""
    if not base_ref or _run_git_cap is None:
        return None
    args = ["diff", "--name-only", "--diff-filter=ACMR", "-z"]
    r = _run_git_cap(args + [f"{base_ref}...HEAD"], worktree)
    if r.returncode != 0:
        r = _run_git_cap(args + [base_ref], worktree)
        if r.returncode != 0:
            return None
    return [rel for rel in (p.strip() for p in r.stdout.split("\0")) if rel]


def _floor_added_line_numbers(worktree: Path, base_ref, _run_git_cap, *, _FLOOR_HUNK_HEADER=_FLOOR_HUNK_HEADER) -> "dict | None":
    """`{rel: frozenset(line numbers this branch ADDED)}` for the diff-scoped secrets leg, or `None`
    when the diff cannot be rendered at all.

    WHY THIS EXISTS (X-1358 / X-1359 / X-1362, <project> 2026-09-09). The atom selected files from
    the diff by PATH and then scanned their WHOLE content, so merely TOUCHING a file re-armed every
    shape already sitting on `main` — landed, audited and unchanged. Every governed ship modifies
    `events.jsonl`, so one such shape quoted inside one journal row refused EVERY land in that
    consumer, and rule 4a leaves no consumer-side relief. A branch is answerable for the lines IT
    WROTE; the pre-existing rest of a file it touched is `main`'s, and the `shared-repo-floor` lens
    is what reaches that (`_floor_tracked_lines`, unchanged).

    HEADERS ONLY — THE CONTENT STILL COMES FROM THE FILE. This reads `diff --git` / `+++ b/` path
    headers and `@@` hunk headers, and NEVER a `+` content line. What it returns is a set of LINE
    NUMBERS, which `_floor_scan_files` applies while reading the file at the candidate — so the
    audit-post r3-finding-2 property is preserved BY CONSTRUCTION: a binary or attributes-suppressed
    change still has exactly the content-visibility a text change does, because such a path simply
    does not appear here and is scanned WHOLE.

    FAIL-CLOSED IN EVERY DIRECTION — an unresolved path is OMITTED, never guessed. A path renders as
    `Binary files … differ` (no `+++` header), a header will not parse, the diff command fails, or
    its output will not decode: in each case the path is absent from the map (or the whole map is
    `None`) and the caller widens it to the whole-file scan it has today. The gate only ever widens.

    THE REFSPEC MIRRORS `_floor_changed_paths` — `<base>...HEAD` first, then the working-tree form
    `<base>` — so the two reads describe the same comparison. If they ever disagreed, the ONLY
    reachable consequence is a path present in `changed` and absent here, which is the widening
    fallback again."""
    if not base_ref or _run_git_cap is None:
        return None
    out = None
    for spec in (f"{base_ref}...HEAD", str(base_ref)):
        try:
            r = _run_git_cap(["diff", "--unified=0", "--diff-filter=ACMR", spec], worktree)
        except Exception:                          # noqa: BLE001 — an undecodable patch, a git fault
            return None                            # unrenderable → the caller scans whole files
        if r.returncode == 0:
            out = r.stdout
            break
    if out is None:
        return None
    added: dict = {}
    rel = None
    for line in out.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            # `+++ /dev/null` is a deletion (filtered out above, but never assume); a quoted path is
            # one this parser declines to unquote — leaving `rel` None omits it, which widens.
            rel = path[2:] if path.startswith("b/") and not path.startswith('b/"') else None
            if rel is not None:
                added.setdefault(rel, set())
        elif line.startswith("diff --git "):
            rel = None                             # a new file entry — until its `+++` names it
        elif line.startswith("@@") and rel is not None:
            m = _FLOOR_HUNK_HEADER.match(line)
            if m is None:
                added.pop(rel, None)               # an unreadable hunk → this path is unresolved
                rel = None
                continue
            start = int(m.group(1))
            count = 1 if m.group(2) is None else int(m.group(2))
            added[rel].update(range(start, start + count))
    return {k: frozenset(v) for k, v in added.items()}


def _floor_scan_files(worktree: Path, rels, errors: list, added_lines=None):
    """Yield `(rel, lineno, line)` for the given relpaths — the ONE content reader both secrets
    scopes use.

    `added_lines` (T-12323) is the OPTIONAL per-path ADDED-LINE SELECTOR the diff-scoped leg supplies
    — `{rel: frozenset(line numbers this branch added)}`. It selects WHICH LINES are yielded; it
    never changes WHAT IS READ, so the content still comes from the file at the candidate through
    this one reader (the r3-finding-2 property is untouched — see `_floor_secrets_scan`). Three
    cases, and the third is the fail-closed one:
      - `rel` maps to a non-empty set → only those line numbers are yielded;
      - `rel` maps to an EMPTY set → the branch added nothing to it, so nothing is yielded (a
        deletion-only or metadata-only touch cannot arm a shape that was already on main);
      - `rel` is ABSENT from the map (or the map is `None`) → the WHOLE file is yielded, exactly as
        before. Every path whose added-line view could not be resolved lands here, so an unresolvable
        diff can only ever WIDEN the scan.
    A path IN scope is opened and streamed exactly as before, so the unreadable-scope refusal below
    is reached identically for everything the selector selects — a selector never turns an
    unreadable in-scope file into a clean one. A path the selector puts OUT of scope (the empty-set
    case) is not opened, and no readability claim is made about it: its content is `main`'s, which
    the tree-wide leg reads.

    A GENERATOR, AND GENUINELY STREAMING (T-12226). Each file is read in bounded blocks through the
    shared `journal.stream_lines` splitter — the SAME one the journal reader uses, so the floor and
    the journal cannot disagree about where a line ends — and the lines are yielded lazily, so
    `_floor_secret_hits` matches AS THEY STREAM. There is NO SIZE BOUND AND NO PER-FILE REFUSAL CAP:
    file size decides nothing here at all.

    WHY THE CAP IS GONE, not raised (X-1323 / X-1325, 2026-09-07). This reader used to `read_text` each
    file WHOLE and append an error for anything over a 2,000,000-byte cap, which the caller then
    refused on. Every governed ship modifies `events.jsonl`, whose LIVE segment holds the SPEC-0190
    7-day window, and on any active consumer that one file is bigger than the cap — so the atom refused
    EVERY land on every active consumer (<project>, <project> + 4 more) with no consumer-side remedy: the
    window is the kernel's, `verify.floor.<atom>.command` is additive-only, `verify.floor.waiver` is
    refused by construction (SPEC-0163), and untracking the journal is forbidden (CHARTER §P5). A
    RAISED cap would only be wrong again at the next repo, and a per-chunk cap that can still refuse
    would be the same defect one layer down. Streaming removes the dependency on file size entirely and
    scans 100 percent of the content — strictly MORE honest than refusing.

    THE MEMORY BOUND, EXACTLY — the longest logical LINE plus one block, never one block alone; a file
    with no newline at all is still held whole. Deliberate: cutting a long line at an arbitrary offset
    would let a credential straddle the cut and go unmatched, and a false green is the one failure a
    security floor may not have. The bound is the real win for the case that motivates it — the journal
    is newline-delimited, so its per-line bound is ONE row against a segment of any size. Full
    rationale lives with the splitter (`journal.stream_lines`), not restated here.

    Every file is DECODED WITH `errors="replace"` and scanned regardless of its bytes: a decoded view
    preserves every ASCII run, which is exactly what `_FLOOR_SECRET_PATTERNS` matches on, so there is
    NO CONTENT EXCLUSION AT ALL (audit-post r2 finding 2 — "contains a NUL early" is not "contains no
    ASCII").

    `errors` IS THE CALLER'S LIST AND IS APPENDED TO DURING ITERATION — so a caller MUST EXHAUST this
    generator before reading it (a generator cannot return a second value, and a half-consumed scan has
    not yet met the file that fails). It is NON-EMPTY whenever the scope could not be read WHOLE, and
    the caller REFUSES on it rather than reporting a clean scan of a partial scope: a scan that
    silently skipped the file holding the credential is a false green. That fail-closed contract is
    UNCHANGED by the streaming — only the size branch went away, never the unreadable one."""
    for rel in rels:
        wanted = None if added_lines is None else added_lines.get(rel)
        if wanted is not None and not wanted:
            # OUT OF SCOPE, so it is not opened at all: the branch added nothing here, and this
            # file's pre-existing content is `main`'s — already landed, already scanned, and reached
            # by the tree-wide leg when the `shared-repo-floor` lens is active. NO readability claim
            # is made about such a path, which is why it is skipped BEFORE the open rather than
            # opened-and-not-streamed: a half-read file would leave the caller's `errors` silent
            # about a read that never happened (audit-post finding 2).
            continue
        f = worktree / rel
        try:
            if not f.is_file():
                continue          # a submodule / deleted-but-tracked path holds no content to scan
            fh = f.open("r", encoding="utf-8", errors="replace")
        except OSError as e:
            errors.append(f"{rel} could not be read ({e}) — it was NOT scanned")
            continue
        try:
            with fh:
                for n, line in enumerate(journal_mod.stream_lines(fh), 1):
                    if wanted is None or n in wanted:
                        yield (rel, n, line)
        except OSError as e:
            # A read can fail AFTER a successful open (a vanished network mount, an I/O error). The
            # partial content already yielded stays scanned — it can only ADD hits — and the error
            # still refuses, because the REST of the file was not read.
            errors.append(f"{rel} could not be read ({e}) — it was NOT scanned")


def _floor_tracked_lines(worktree: Path, _run_git_cap, inventory, errors: list, *, _floor_scan_files, _floor_tracked_inventory):
    """Yield `(rel, line)` over every TRACKED file — the WIDENED scan scope, and FAIL-CLOSED.

    Used when the `shared-repo-floor` lens is active (a repo with named human collaborators: a
    credential may sit on a path THIS ship never touched, where the SPEC-0100 AI-authored triggers
    never looked), when the profile could not be resolved, and as the fallback when the diff cannot
    be resolved.

    A GENERATOR (T-12226), for the same reason `_floor_scan_files` is one — and `errors` is likewise
    the CALLER'S list, appended to DURING iteration, so the caller must EXHAUST this before reading
    it. `errors` is NON-EMPTY whenever the scope could not be read WHOLE — the enumeration failed, or
    an in-scope file could not be read. The caller REFUSES on a non-empty `errors` rather than
    reporting a clean scan of a partial tree (audit-post finding 2): a scan that silently skipped the
    file holding the credential is a false green, which is the one failure mode a security floor may
    not have.

    NO CONTENT EXCLUSION AT ALL (audit-post r2 finding 2). This scan used to skip a file whose first
    8192 bytes contained a NUL, on the reasoning that a binary blob cannot carry a TEXT credential.
    That reasoning is false in the direction that matters: "contains a NUL early" is not "contains no
    ASCII", and a tracked file with a NUL-bearing prefix and a plain `AKIA...` further in reads as
    binary to that test while carrying a perfectly matchable credential. The exclusion was therefore
    a silent, attacker-selectable bypass of the whole atom. Every tracked file is now DECODED WITH
    `errors="replace"` and scanned for the same named shapes regardless of its bytes — a decoded view
    preserves every ASCII run, which is exactly what `_FLOOR_SECRET_PATTERNS` matches on.

    SIZE IS NO LONGER A BOUND AT ALL (T-12226 — the streaming reader). The per-file byte cap that
    used to make an over-cap file an ERROR is RETIRED: it refused every land on every active consumer,
    because the tracked `events.jsonl` live segment is legitimately larger than any fixed cap. A huge
    tracked file is now simply SCANNED, whole, in bounded blocks. The rationale is homed on
    `_floor_scan_files`; what survives here is the unreadable-scope refusal, unchanged.

    `inventory` is the ONE per-land tracked-file enumeration threaded in by the caller (r3 finding
    11); pass `None` to resolve its own, so unit callers keep working unchanged."""
    if inventory is None:
        inventory, inv_errors = _floor_tracked_inventory(worktree, _run_git_cap)
        if inventory is None:
            errors.extend(f"{e} — so a whole-tree scan cannot be claimed" for e in inv_errors)
            return
    yield from _floor_scan_files(worktree, inventory, errors)


#: The PEM block's closing marker — the counterpart of the `private key block` opening shape in
#: `_FLOOR_SECRET_PATTERNS`. `_floor_secret_span` needs BOTH ends, because removing a BEGIN header
#: while leaving the base64 body would disarm the floor over live key material.
_FLOOR_PEM_END = re.compile(r"-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")


#: `_floor_journal_row_on_main`'s per-scan memo sentinels (deliberately NOT `_FLOOR_*`-named: the
#: T-12695 residue contract reserves that prefix for host-REBINDABLE constants, and a sentinel has
#: nothing to rebind). An UNREADABLE segment must be
#: distinguishable from a segment that was read and is EMPTY: caching the latter for the former is a
#: fail-open that survives the call that made it (audit-post r1 finding 2).
_MEMO_MISS = object()
_MEMO_UNREADABLE = object()


def _floor_is_journal_path(rel, *, journal_rel: str = "events.jsonl") -> bool:
    """Is this repo-RELATIVE path the root journal or one of its `archive/events-*.jsonl` segments?

    T-12779 (SPEC-0163 rule 4c). The `journal redact` route exists only for a JOURNAL row, so the
    floor and the verb both need one answer to "is this path the journal". It is decided through
    `events.is_archive_segment` + the root journal name — NO new constant family and no second
    membership rule (the class SPEC-0190 rule 3 names as dangerous).

    Relative paths only, matching what the diff reader and the scan yield. A `rel` that escapes the
    repo, or one that is not a path at all, is simply not the journal."""
    try:
        p = Path(rel)
    except TypeError:
        return False
    live = Path(journal_rel)
    return p == live or events_mod.is_archive_segment(p, live)


def _floor_journal_row_on_main(line, ts, worktree: Path, base_ref, _run_git_cap, memo,
                               *, journal_rel: str = "events.jsonl") -> "bool | None":
    """Is this row's EXACT BYTE IDENTITY already present in `main`'s LOGICAL journal at `base_ref`?

    T-12779 [R1] — PROVENANCE IS LOGICAL, NOT PATH-LOCAL, and that is the whole reason this exists.
    `_floor_added_line_numbers` answers a PATH-LOCAL question: which lines of THIS FILE does the
    diff add? A branch that ROTATES the journal writes a brand-new `archive/events-<date>.jsonl`
    every line of which is diff-ADDED — so the path-local test calls a row that has been on `main`
    for weeks "branch-written", and a redaction route keyed on it alone would rewrite `main`'s row
    at a new address. The logical journal is ONE history across its physical segments (SPEC-0190
    rule 1), so the honest question is whether these BYTES are in that history at the merge-base.

    THE SEGMENT SET AT `base_ref` COMES FROM `journal.revision_segment_paths` (SPEC-0190 rule 4b) —
    never a literal `git show <rev>:events.jsonl`, which reads the LIVE SEGMENT ALONE at any
    post-rotation revision and would look entirely healthy while missing most of the history. It is
    then narrowed by the SAME dated-label overlap rule `events.segment_paths_since` uses
    (`events.segment_label`; the live segment unconditional, an UNDATABLE label unskippable) to the
    row's own date +/- one day of skew margin.

    IDENTITY IS THE RAW LINE — what `events._dedup_identity` names as the strict read-back identity,
    deliberately STRICTER than land's canonical dedup key. A false NEGATIVE here would authorize
    rewriting a row that is on `main`, so the comparison admits no normalization at all.

    `memo` is the per-scan `{(base_ref, rel): frozenset(lines)}` read, so ten hits cost one pass over
    each segment rather than ten. It is caller-owned and scan-scoped: nothing survives the land.

    RETURNS `True` / `False` / `None`, and **every caller treats `None` as ON MAIN** — fail-closed in
    the direction that REFUSES. `None` means the question could not be answered (git unreadable, the
    revision unresolvable, an enumerated segment that would not read, output undecodable), and an
    unanswered provenance question must never admit a rewrite. `False` — the only answer that
    ADMITS a rewrite — is returned ONLY after the revision resolved AND every enumerated segment was
    read whole.

    ABSENCE IS PROVED BY A SUCCESSFUL ENUMERATION, NEVER BY AN EXIT CODE (T-12782 F4). Where this
    function must decide that a path is not in the merge-base tree, it asks `ls-tree` — which reads
    the TREE, not the blob — and only a SUCCESSFUL run that named nothing counts as absence. An
    exit-code existence test (`cat-file -e`) cannot carry that decision: its non-zero exit means BOTH
    «not in that tree» and «that object could not be read», so an object-database / I/O fault read as
    proven absence and answered False for a main-owned row. Every failure of the enumeration, and
    every failed object read, answers `None` instead — and a fault is NEVER memoized as an empty set.

    RESIDUAL, stated rather than hidden: `revision_segment_paths` degrades to `[journal_rel]` on a
    git fault of its own, which this function cannot distinguish from a revision that genuinely has
    no archive. The `rev-parse` guard above removes the reachable case (an unresolvable `base_ref`);
    what remains is a git that resolves the revision but fails the `ls-tree`, and that residual
    belongs to the shared rule-4b resolver's own contract, not to a second copy of it here."""
    if not line or not base_ref or _run_git_cap is None:
        return None
    if memo is None:
        memo = {}

    # F1 (audit-post r1 finding 1) — THE RESOLVER'S OWN DEGRADATION IS DETECTED, NOT INHERITED.
    # `revision_segment_paths` falls back to `[journal_rel]` when its `ls-tree` fails — right for a
    # reader that FOLDS (it degrades to the pre-segmentation behaviour rather than reading nothing),
    # and WRONG here: a base whose archive could not be enumerated would look like a base with no
    # archive, so a main-owned row that rotated into one would read as NOT on main, i.e. REDACTABLE.
    # This wrapper witnesses that failure and turns the whole answer UNANSWERABLE.
    enum_failed = []

    def _run(argv):
        r = _run_git_cap(list(argv), worktree)
        if getattr(r, "returncode", 1) != 0:
            enum_failed.append(tuple(argv))
        return r

    # THE REVISION MUST RESOLVE BEFORE ANY ABSENCE CLAIM IS MADE. `revision_segment_paths` degrades
    # to `[journal_rel]` on ANY git failure — its own documented fail-safe, which is right for a
    # reader that FOLDS but wrong for one that must distinguish «the row is not in this history»
    # from «this history could not be read». Without this guard an unresolvable `base_ref` read as
    # "not on main", i.e. REDACTABLE, which is the false green this whole predicate exists to
    # prevent (caught by the AC2 arm of tests/test_t11444_segment_aware_readers.py).
    try:
        rp = _run_git_cap(["rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}"], worktree)
    except Exception:                                  # noqa: BLE001 — git could not be run at all
        return None
    if getattr(rp, "returncode", 1) != 0 or not (rp.stdout or "").strip():
        return None

    try:
        rels = journal_mod.revision_segment_paths(base_ref, worktree, journal_rel, run=_run)
    except Exception:                                  # noqa: BLE001 — an unreadable revision
        return None
    if not rels or enum_failed:
        return None
    live = Path(journal_rel)
    date = (str(ts)[:10] if ts else "")
    floor_day = ceiling_day = None
    if len(date) == 10:
        try:
            day = datetime.date.fromisoformat(date)
            floor_day = (day - datetime.timedelta(days=1)).isoformat()
            ceiling_day = (day + datetime.timedelta(days=1)).isoformat()
        except ValueError:
            floor_day = ceiling_day = None
    for rel in rels:
        if rel != journal_rel:                         # the live segment is UNCONDITIONAL
            label = events_mod.segment_label(Path(rel), live)
            # An UNDATABLE label proves nothing about its contents, so it can never ground a skip.
            if label is not None and floor_day is not None and not (floor_day <= label <= ceiling_day):
                continue
        key = (str(base_ref), rel)
        seen = memo.get(key, _MEMO_MISS)
        # F2 (audit-post r1 finding 2) — an UNREADABLE segment is memoized as its own SENTINEL, never
        # as an empty line set. Caching `frozenset()` for a failed read made the failure survive only
        # in this call's local flag: a SECOND call sharing the memo read the cache as a successful
        # empty read and answered False — fail-open, from a cache entry.
        if seen is _MEMO_UNREADABLE:
            return None
        if seen is _MEMO_MISS:
            # The read itself must ANSWER, never RAISE: this was the one of the five git reads in
            # this function that could propagate an OSError out of a predicate whose whole contract
            # is three-valued, so a git that cannot be run at all bypassed «unanswerable» entirely.
            try:
                r = _run_git_cap(["show", f"{base_ref}:{rel}"], worktree)
            except Exception:                          # noqa: BLE001 — git could not be run at all
                memo[key] = _MEMO_UNREADABLE
                return None
            if getattr(r, "returncode", 1) != 0:
                if rel != journal_rel:
                    memo[key] = _MEMO_UNREADABLE
                    return None
                # THE LIVE journal is appended UNCONDITIONALLY by the resolver whether or not it
                # exists at the revision, so its absence is a genuine fact about that history (a
                # pre-journal commit) and contributes nothing. An ARCHIVE segment, by contrast, was
                # ENUMERATED by `ls-tree` at this very revision — if it will not read now, the
                # history could not be read WHOLE, and an absence claim over a partial read is
                # exactly the false green this predicate exists to prevent.
                #
                # F3 (audit-post r2 finding 1) — BUT «show failed» IS NOT «absent». The carve-out
                # above is sound ONLY for a live journal that genuinely is not in that tree; an
                # `events.jsonl` that EXISTS at the merge-base and merely fails to READ (a corrupt
                # blob, a filter/attribute fault, an undecodable object) took the same branch and
                # answered False = REDACTABLE for a row that is on `main` — the identical fail-open
                # F1/F2 closed for the archive side. So EXISTENCE IS SETTLED FIRST, and only a
                # positively-settled absence contributes nothing.
                #
                # F4 (T-12782, audit-post r3 fp1:0f255a145cca48a5) — AND THE SETTLE IS AN
                # ENUMERATION, NOT AN EXIT CODE. `cat-file -e` was the first shape of this settle
                # and it cannot carry it: a non-zero exit means «not in that tree» AND «that object
                # could not be read» — the two answers this branch must tell apart — so an
                # object-database / I/O fault took the absent limb, memoized `frozenset()` and
                # answered False = REDACTABLE for a main-owned row. `bin/lib/debt_adoption.py`
                # names the same ambiguity in its own comment and disambiguates by resolving the
                # SHA separately, which cannot help here: `base_ref` is ALREADY resolved by the
                # `rev-parse` guard above, so the residual ambiguity is precisely path-absent vs
                # object-unreadable AT a resolvable revision.
                #
                # `ls-tree` answers it because it reads the TREE OBJECTS, never the blob — the same
                # enumeration `journal.revision_segment_paths` already uses for the archive side
                # (SPEC-0190 rule 4b), applied to the live path. Read THREE-VALUED:
                #   * it could not RUN, or exited non-zero        -> the enumeration FAILED  -> None
                #   * exit 0 and it NAMED something at that path  -> the entry IS there, so the
                #     failed `show` above is a READ FAULT                                   -> None
                #   * exit 0 and it named NOTHING                 -> a SUCCESSFUL enumeration that
                #     found nothing PROVES the path is absent from that tree -> contributes nothing
                # So the ONLY route to a memoized empty set is a positive fact about the tree; a
                # FAULT is never memoized as an empty read (which is F2's rule, held on this limb
                # too).
                try:
                    ls = _run_git_cap(["ls-tree", "-r", "--name-only", "-z", str(base_ref),
                                       "--", rel], worktree)
                except Exception:                      # noqa: BLE001 — git could not be run
                    memo[key] = _MEMO_UNREADABLE
                    return None
                if getattr(ls, "returncode", 1) != 0:   # the ENUMERATION failed → unanswerable
                    memo[key] = _MEMO_UNREADABLE
                    return None
                if [n for n in (ls.stdout or "").split("\0") if n.strip()]:
                    memo[key] = _MEMO_UNREADABLE        # EXISTS but would not read → unreadable
                    return None
                memo[key] = frozenset()                 # PROVEN absent by a successful enumeration
                continue
            try:
                seen = frozenset(journal_mod.stream_lines(io.StringIO(r.stdout or "")))
            except Exception:                          # noqa: BLE001 — undecodable blob
                memo[key] = _MEMO_UNREADABLE
                return None
            memo[key] = seen
        if line in seen:
            return True
    # NOT FOUND, over a history that WAS read whole — every enumerated segment either yielded its
    # lines or returned `None` above, so this is an honest absence claim and the only answer that
    # ADMITS a rewrite.
    return False



def _floor_journal_allowlist(floor) -> tuple:
    """`(hashes, malformed)` from `verify.floor.secrets.journal_allowlist` (SPEC-0163 rule 4d,
    T-13121). An entry names ONE main-owned journal row by the sha256 of its scanned bytes and
    carries a `reason`, a `date` (YYYY-MM-DD) and a `rotation` note. STRICT: a missing, blank,
    null or wrong-typed field, an invalid date or a non-64-hex hash makes the entry MALFORMED, and a
    malformed entry admits nothing — a bare hash is never a reasoned record."""
    entry = floor.get("secrets") if isinstance(floor, dict) else None
    raw = entry.get("journal_allowlist") if isinstance(entry, dict) else None
    if raw is None:
        return frozenset(), []
    if not isinstance(raw, list):
        return frozenset(), ["`journal_allowlist` is not a list"]
    hashes, malformed = set(), []
    for i, e in enumerate(raw):
        bad = []
        if not isinstance(e, dict):
            bad = ["sha256", "reason", "date", "rotation"]
        else:
            h = e.get("sha256")
            if not (isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h.strip().lower())):
                bad.append("sha256")
            for k in ("reason", "rotation"):
                if not (isinstance(e.get(k), str) and e.get(k).strip()):
                    bad.append(k)
            d = e.get("date")
            try:
                if not (isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.strip())):
                    raise ValueError
                datetime.date.fromisoformat(d.strip())
            except ValueError:
                bad.append("date")
        if bad:
            malformed.append(f"journal_allowlist[{i}] (bad/missing: {', '.join(bad)})")
        else:
            hashes.add(e["sha256"].strip().lower())
    return frozenset(hashes), malformed


def _floor_row_sha256(text) -> str:
    """The allowlist identity of a scanned row: sha256 of its bytes exactly as the scan saw them."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _floor_journal_row_redactable(rel, lineno, line, ts, added, worktree: Path, base_ref,
                                  _run_git_cap, memo, *, journal_rel: str = "events.jsonl",
                                  _floor_is_journal_path=_floor_is_journal_path,
                                  _floor_journal_row_on_main=_floor_journal_row_on_main) -> bool:
    """THE ADMISSION PREDICATE — is this journal row one `journal redact` may rewrite?

    TRUE iff it is a journal path (1a) AND the added-line view RESOLVED for it AND this line number
    is in it AND its bytes are NOT on `main` at the merge-base (1b). The added-line leg is kept as
    the cheap FIRST filter — it is already computed for the scan and it short-circuits the git reads
    — and the on-main leg is what closes the rotation hole [R1].

    THIS ONE FUNCTION IS SHARED BY BOTH SIDES, and that sharing is the point: the FLOOR uses it to
    decide whether to NAME the remedy, and `cmd_journal_redact` uses it to decide whether to ADMIT
    the row. So the floor can never recommend a route the verb refuses, and the verb can never
    rewrite a row the floor would not have named. Two predicates would drift; there is one.

    FAIL-CLOSED THROUGHOUT: an unresolved added-line view (`added is None`, or `rel` absent from it)
    is NOT branch-written evidence, and `_floor_journal_row_on_main` returning `None` is read as ON
    MAIN. Every uncertainty answers False."""
    if not _floor_is_journal_path(rel, journal_rel=journal_rel):
        return False
    if not added or rel not in added or lineno not in added[rel]:
        return False
    return _floor_journal_row_on_main(line, ts, worktree, base_ref, _run_git_cap, memo,
                                      journal_rel=journal_rel) is False


def _floor_secret_span(label, m, text, *, _FLOOR_PEM_END=_FLOOR_PEM_END) -> "tuple | None":
    """`(start, end)` of the material that must be REMOVED for a match of the named shape, or `None`
    when it cannot be determined.

    THREE CASES, and the third is the one that exists for safety:
      - a pattern declaring a `secret` group (the `_floor_is_interpolation` opt-in, REUSED here
        rather than given a second registry) -> that GROUP's span: the credential inside
        `postgresql://user:<pw>@host` is the password, and removing the URL's structure around it
        would destroy a row's meaning for no security gain;
      - the PEM shape -> the BEGIN marker THROUGH the matching `-----END ... PRIVATE KEY-----` on the
        SAME physical line (a JSON journal row carries its newlines ESCAPED, so the whole block is
        one line there). NO end marker -> `None`, which REFUSES: removing a header while leaving the
        base64 body would leave live key material in the row AND disarm the floor over it, which is
        a false green — the one failure a credential floor may not have;
      - every other (literal-prefixed, self-delimiting) shape -> the WHOLE match, which IS the token.

    Returning `None` rather than guessing is what lets the caller refuse with the row's bytes
    untouched."""
    if m is None:
        return None
    if (m.groupdict().get("secret") is not None) and m.start("secret") >= 0:
        return (m.start("secret"), m.end("secret"))
    if label == "private key block":
        end = _FLOOR_PEM_END.search(text or "", m.end())
        return (m.start(), end.end()) if end is not None else None
    return (m.start(), m.end())


def _floor_secret_hits(lines, *, hit_text=None, _FLOOR_SECRET_PATTERNS=_FLOOR_SECRET_PATTERNS, _floor_is_interpolation) -> list:
    """`[(path, lineno, label)]` for every named credential shape found, over `(path, lineno, text)`
    triples. De-duplicated per (path, label), keeping the FIRST line that matched.

    `hit_text` (T-12779) is an OPTIONAL caller-owned dict this fills `{(path, lineno): text}` for
    every recorded hit. The RETURN SHAPE IS UNCHANGED — it is a side-channel precisely so it is not
    one: the three-way remedy partition in `_floor_secrets_scan` needs the offending LINE (to read
    its `ts` and to test its bytes against `main`), and the alternative — re-opening the file to
    find the line again — would be a second read of content this generator already streamed past.
    `None` (the default) records nothing, so every existing caller is byte-identical.

    THE LINE NUMBER IS PART OF THE ANSWER, not decoration: a refusal that names only the file leaves
    the reader to search it, and on the diff-scoped leg it must be provable that the line named is
    one THIS BRANCH WROTE. The dedup key stays (path, label) — one credential shape reported once
    per file, as before — so a journal segment with a thousand matching rows still yields one hit.

    `finditer`, NOT `search` (the interpolation clause). A line may carry a TEMPLATE and a real
    credential; testing only the first match would let the template's exemption suppress the
    credential behind it. Each match is judged on its own and the scan continues.

    THE NEGATIVE CLAUSE IS A GUARDED LOOKUP — `m.groupdict().get("secret")`, never `m.group(...)`.
    Seven of the eight patterns declare no `secret` group, so they read `None`, which
    `_floor_is_interpolation` answers False for: their behaviour is bit-for-bit unchanged and no
    `IndexError` is reachable from a group-less pattern (audit-pre finding 1)."""
    seen, hits = set(), []
    for path, lineno, text in lines:
        for label, pat in _FLOOR_SECRET_PATTERNS:
            if (path, label) in seen:
                continue
            for m in pat.finditer(text):
                if _floor_is_interpolation(m.groupdict().get("secret")):
                    continue          # a template's placeholder — nothing to remove, nothing to rotate
                seen.add((path, label))
                hits.append((path, lineno, label))
                if hit_text is not None:
                    hit_text[(path, lineno)] = text
                break
    return hits


def _floor_requirements_fully_pinned(req: Path, *, _FLOOR_REQUIREMENTS_INERT_OPTIONS=_FLOOR_REQUIREMENTS_INERT_OPTIONS) -> bool:
    """A `requirements.txt` is its OWN lock exactly when every requirement line is `==`-pinned.

    Takes the FILE PATH rather than the worktree root: since dependency discovery walks nested
    manifests (audit-post r2 finding 4), the requirements file that may vouch for a `pyproject.toml`
    is the one BESIDE IT, not whatever sits at the repository root. A missing / unreadable file is
    `False` — absence never vouches.

    A LEADING-`-` LINE IS A DIRECTIVE, AND MOST DIRECTIVES BRING DEPENDENCIES THIS FILE DOES NOT PIN
    (audit-post r3 finding 5). Every such line used to be `continue`d as "an option, not a
    requirement", which made `-r unpinned.txt` and `-e .` invisible: a file holding one `==`-pinned
    package plus `-r unpinned.txt` answered fully-pinned while the actual dependency set sat unpinned
    in the included file. The vouching claim here is about the WHOLE resolved set, so the honest
    answer for a directive that pulls more of that set in — an include, a constraint, an editable
    install — is `False`. Resolving includes recursively was the alternative and is refused on
    CHARTER §P1 F1/F3 grounds: it adds a path resolver, a cycle guard and a containment check to a
    predicate whose whole job is to say whether ONE file is self-sufficient, for the benefit of a
    project that can instead commit a real lockfile or declare
    `verify.floor.dependencies.command`.

    `_FLOOR_REQUIREMENTS_INERT_OPTIONS` is the enumerated set of directives that bring NO dependency
    of their own (index / link / format / hash-policy knobs) — those stay skipped, so an ordinary
    pinned file carrying an `--index-url` header does not become unpinnable. Membership is by that
    criterion, not by taste; anything NOT enumerated is treated as dependency-bearing and refuses."""
    try:
        text = req.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    saw = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            opt = line.split("=", 1)[0].split(None, 1)[0].strip()
            if opt in _FLOOR_REQUIREMENTS_INERT_OPTIONS:
                continue
            return False          # an include / constraint / editable — the set is not pinned HERE
        saw = True
        if "==" not in line:
            return False
    return saw


def _floor_instant(ts, *, _FLOOR_MAX_FUTURE_SKEW_DAYS=_FLOOR_MAX_FUTURE_SKEW_DAYS) -> "object | None":
    """An RFC3339 timestamp as a timezone-AWARE UTC instant, or `None` when it is malformed or
    implausibly far in the future.

    RFC3339 IS NOT LEXICALLY ORDERED (audit-post r3 finding 9). Every timestamp comparison in the
    floor was a string `<` / `>`, which is only correct when both operands are UTC `Z` with the same
    field widths — and one class of operand here is NOT: `git log --format=%cI` emits the committer's
    OWN offset, so `2026-09-05T01:00:00-05:00` (06:00Z) sorts BEFORE `2026-09-05T05:00:00Z` although
    it is chronologically LATER. That is the wrong direction on both legs it feeds: a probe row can
    read fresh when it is stale, and a carrier commit that REDEFINED a probe after its last pass can
    read as predating it, so a redefined probe reads as still-vouched. Parsing to an instant removes
    the offset from the comparison entirely.

    A MALFORMED TIMESTAMP IS `None`, NEVER A SORTABLE STRING — the second half of the same finding.
    `"9999"` and `"tomorrow"` both sort ABOVE every real timestamp, so a malformed row won the
    latest-verdict selection AND passed the age check. The implausible-future bound catches the
    honestly-formatted version of the same trick: a row dated a century out is not evidence about
    now. Callers treat `None` as unusable and refuse; nothing here judges."""
    import datetime as _dt
    s = str(ts or "").strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        d = _dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)   # naive ⇒ read as UTC, the journal's own convention
    d = d.astimezone(_dt.timezone.utc)
    if d > _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=_FLOOR_MAX_FUTURE_SKEW_DAYS):
        return None                              # implausibly future — not evidence about now
    return d


def _floor_row_sort_key(row, *, _floor_instant):
    """Order probe verdict rows by their PARSED instant (`_floor_instant`), never by the raw string.

    `_floor_probe_rows` has already refused every row whose `ts` is absent, so the only rows reaching
    here carry one; a `ts` that is present but unparseable sorts OLDEST (`datetime.min`) so it can
    never win the latest-verdict selection by being lexically large. It is not thereby ignored — the
    reader refuses on it separately, this ordering just denies it the win in the meantime."""
    import datetime as _dt
    return _floor_instant(row.get("ts")) or _dt.datetime.min.replace(tzinfo=_dt.timezone.utc)


def _floor_probe_journals(worktree: Path) -> tuple:
    """The journal(s) a candidate worktree's probe verdicts can live in — the root journal and the
    interactive hook-tail. A PATH RESOLVER only: it obtains nothing, so the reading (and the census
    that enumerates readings) belongs to `_floor_probe_rows` below, which takes these as an
    argument and can therefore be driven against a fixture journal."""
    return (worktree / "events.jsonl", worktree / ".yitc" / "events.jsonl")


FLOOR_PROBE_NEEDLES = ("security_live_probe_passed", "security_live_probe_escalated",
                       "deploy_security_probe_passed")

# T-13439 — a governed Class-S deploy's passing security probe (`bin/lib/deploy.py`) is a verdict
# source too, but ONLY for the declared properties its row NAMES under `checked`, each bound to the
# definition digest it was proved under. It is expanded into one pass verdict per named property and
# marked with this source, so `_floor_declared_probes` can admit it on an exact digest match alone.
DEPLOY_PROBE_SOURCE = "deploy_security_probe_passed"


def _floor_probe_rows(journals, *, _floor_row_sort_key) -> tuple:
    """`(rows, errors)` — every SPEC-0098 probe VERDICT row in the given journal(s), ORDERED
    oldest-first by `ts`, ALONGSIDE every read/parse failure encountered getting them.

    Read straight off the durable record the probe runner already writes — no network call happens
    inside a land verify (F-025 hermeticity).

    THE ERRORS ARE RETURNED, NOT SWALLOWED (audit-post r3 finding 8). An unreadable journal and an
    unparseable line were both `continue`d, and the reader was then told only "here are the rows" —
    which is a claim about the WHOLE record that a partial read cannot make. The concrete false green:
    a property whose newest row is a malformed `security_live_probe_escalated` silently loses to the
    older VALID `security_live_probe_passed` beneath it, and the floor reports the property proved
    using the very evidence the newer row was superseding. The same holds one level up when one of
    the two journal loci is unreadable. So this parser now REPORTS what it could not read; the
    fail-closed JUDGEMENT still belongs to the reader
    (lessons/fail-closed-belongs-to-the-reader), which refuses on a non-empty `errors`.

    ORDER-INSENSITIVE BY CONSTRUCTION (SPEC-0190 rules 5/6): the answer is explicitly re-sorted on
    each row's OWN `ts`, so a legal re-partition of the same row multiset across segments cannot
    move it. `journals` is a PARAMETER rather than a resolved path so this reader is drivable
    against the pinned census fixture."""
    def _deploy_probe_verdicts(row: dict) -> list:  # nested: a helper, not a residue-bearing leaf
        """The per-property pass verdicts a `deploy_security_probe_passed` row vouches for — one per
        well-formed `checked` item (a non-blank `property` AND a non-blank `definition_digest`). A row
        that names no property (every deploy before T-13439, or a probe declaring none) yields NOTHING:
        an opaque command proved no NAMED property, so it refreshes no declared one."""
        data = row.get("data")
        checked = data.get("checked") if isinstance(data, dict) else None
        if not isinstance(checked, list):
            return []             # absent or malformed `checked` names no property — never a crash
        out = []
        for item in checked:
            if not isinstance(item, dict):
                continue
            prop = str(item.get("property") or "").strip()
            digest = str(item.get("definition_digest") or "").strip()
            if not prop or not digest:
                continue
            out.append({"ts": row.get("ts"), "type": "security_live_probe_passed",
                        "data": {"property": prop, "url": str(item.get("url") or ""),
                                 "definition_digest": digest, "source": DEPLOY_PROBE_SOURCE}})
        return out

    rows, errors = [], []
    for jp in journals:
        if not Path(jp).exists():
            continue          # a locus that does not exist held no rows — absence is not a read error
        try:
            # SEGMENT-AWARE (SPEC-0190 rule 4) — the same `journal_mod.segment_text` idiom the other
            # readers in this module use, so a rotated journal is read whole rather than truncated.
            # T-13139 — `needles` DECLARES the lines this reader keeps (below), so inside the debt seam's
            # one-pass scope an archive segment is served from that pass; strict decode is unchanged.
            text = journal_mod.segment_text(jp, encoding="utf-8", needles=FLOOR_PROBE_NEEDLES)
        except (OSError, ValueError) as e:
            errors.append(f"{jp} could not be read ({e}) — the probe verdict record is incomplete")
            continue
        for n, line in enumerate((text or "").splitlines(), 1):
            line = line.strip()
            if not line or not any(nd in line for nd in FLOOR_PROBE_NEEDLES):
                continue
            try:
                row = json.loads(line)
            except ValueError as e:
                errors.append(f"{jp}:{n} names a probe verdict but does not parse as JSON ({e}) — a "
                              f"verdict row that cannot be read cannot be ruled out as the newest one")
                continue
            if not isinstance(row, dict) or row.get("type") not in FLOOR_PROBE_NEEDLES:
                continue
            deploy_verdicts = (_deploy_probe_verdicts(row) if row.get("type") == DEPLOY_PROBE_SOURCE
                               else None)
            if deploy_verdicts == []:
                continue          # a deploy pass naming no property is no verdict for any property
            if not str(row.get("ts") or "").strip():
                errors.append(f"{jp}:{n} is a probe verdict with no `ts` — it cannot be ordered "
                              f"against the others, so 'the newest verdict' is undecidable")
                continue
            rows.extend(deploy_verdicts if deploy_verdicts is not None else [row])
    rows.sort(key=_floor_row_sort_key)
    return rows, errors


def _floor_probe_definition_digest(entry) -> "str | None":
    """The candidate's canonical digest for a declared probe entry — the SAME function
    `bin/lib/live_probe.py` watermarks a passing row with (imported, never re-spelled: two spellings
    of a digest are two digests)."""
    try:
        from lib import live_probe as _lp
    except Exception:                                  # noqa: BLE001 — no watermark ⇒ legacy path
        return None
    return _lp.probe_definition_digest(entry)


def _probe_entry_key(entry) -> tuple:
    """The identity of ONE declared `security.probes[]` entry: `(property, url)` (T-12981). Keyed by
    `property` alone, two entries proving one property on two paths collapsed into one, so the second
    could never land — the adopter report that filed this card."""
    return (str(entry.get("property") or "").strip(), str(entry.get("url") or "").strip())


def _probe_row_url_matches(row_url: str, entry_url: str) -> bool:
    """Does a verdict row's recorded `url` name this entry's declared `url`? Exact, or — for a
    relative declaration the runner joined onto `live_base_url` — the row url's path(+query)."""
    if not entry_url:
        return False
    if row_url == entry_url:
        return True
    if entry_url.startswith("/"):
        from urllib.parse import urlsplit
        parts = urlsplit(row_url)
        return (parts.path + (f"?{parts.query}" if parts.query else "")) == entry_url
    return False


def _probe_row_owner(row, peers: list, digests: list):
    """The ONE declared entry (an index into `peers`, all sharing the row's property) this verdict row
    belongs to, or None. A PARTITION, never a cross-binding (T-12981 audit-pre): a watermarked row whose
    digest equals a peer's CURRENT digest belongs to that peer only; otherwise the row binds by url.
    A property declared once keeps the pre-T-12981 behaviour — every row of it belongs to that entry."""
    if len(peers) == 1:
        return 0
    data = row.get("data") or {}
    digest = data.get("definition_digest")
    if digest and digest in digests:
        return digests.index(digest)
    row_url = str(data.get("url") or "").strip()
    for i, e in enumerate(peers):
        if _probe_row_url_matches(row_url, str(e.get("url") or "").strip()):
            return i
    return None


def _floor_carrier_entry_history(worktree: Path, _run_git_cap, since_ts, cur_entries, *, CONSUMER_OPS_CONTRACT, _floor_instant, _floor_probe_definition_digest) -> "dict | None":
    """`{(property, url): <aware UTC instant of the newest commit whose declaration of that probe DIFFERS
    from the candidate's>}` — the BOUNDED LEGACY fallback for rows written before the
    `definition_digest` watermark existed.

    THE VALUES ARE INSTANTS, NOT STRINGS (audit-post r3 finding 9). `git log --format=%cI` keeps the
    committer's own UTC OFFSET, so comparing those strings lexically against a `Z`-suffixed probe row
    put a chronologically LATER negative-offset redefinition BEFORE the pass it invalidates — and the
    caller then read a redefined probe as still vouched. `_floor_instant` normalizes both sides; a
    commit whose `%cI` will not parse fails the traversal CLOSED, exactly as an unreadable one does.

    ONE traversal per land, shared by ALL legacy properties (never one scan per property), and
    bounded to commits at or after `since_ts` — the oldest candidate row still inside the freshness
    window, beyond which the age bound already refuses so there is nothing older worth walking.
    `cur_entries` is `{(property, url): definition_digest}` as the CANDIDATE declares them, computed by the
    caller off the carrier it ALREADY parsed — this function never re-opens the ops carrier, so one
    resolution can never mix two versions of it (and the T-11280 one-entry-point reader contract,
    pinned by tests/test_pinned_verify.py, is not widened by a second reader here).

    `None` = the history could not be read; the caller treats that as "cannot prove unchanged" and
    REFUSES, rather than as "unchanged".

    FAIL-CLOSED PER COMMIT (audit-post r2 finding 5). The top-level `git log` failing already
    returned `None`, but each individual commit's read did not: a failed `git show`, a malformed log
    line, or a carrier that would not parse was `continue`d PAST, so that commit's declaration was
    silently treated as if it had never existed. A traversal in which every commit failed therefore
    returned `{}` — indistinguishable from "the entry never changed" — and the caller ACCEPTED a
    legacy pass it had proved nothing about. The whole answer here is "no commit in the window
    redefined this probe", and that is a claim about EVERY commit in the window: one unreadable
    commit makes the claim unmakeable, so ANY per-commit failure now returns `None` and refuses."""
    if _run_git_cap is None:
        return None
    args = ["log", "--format=%H %cI"]
    if since_ts:
        args.append(f"--since={since_ts.isoformat()}")
    args += ["--", CONSUMER_OPS_CONTRACT]
    r = _run_git_cap(args, worktree)
    if r.returncode != 0:
        return None
    changed: dict = {}
    for line in r.stdout.splitlines():
        if not line.strip():
            continue                                   # blank padding is not a commit record
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            return None                                # an unreadable log record — fail closed
        sha, raw_ts = parts
        ts = _floor_instant(raw_ts)
        if ts is None:
            return None                                # an unparseable commit date — fail closed
        blob = _run_git_cap(["show", f"{sha}:{CONSUMER_OPS_CONTRACT}"], worktree)
        if blob.returncode != 0:
            return None                                # that commit's carrier is unreadable — fail closed
        try:
            doc = state.load_ops_str(blob.stdout)
        except Exception:                              # noqa: BLE001
            return None                                # unparseable at that commit — fail closed
        dsec = doc.get("security") if isinstance(doc, dict) else None
        at_commit = {}
        for e in (dsec.get("probes") if isinstance(dsec, dict) else None) or []:
            if isinstance(e, dict) and str(e.get("property") or "").strip():
                at_commit[_probe_entry_key(e)] = _floor_probe_definition_digest(e)
        for key, cur_digest in cur_entries.items():
            prior = changed.get(key)
            if at_commit.get(key) != cur_digest and (prior is None or ts > prior):
                changed[key] = ts
    return changed


def _floor_secrets_scan(worktree: Path, base_ref, _run_git_cap, *, tree_wide: bool,
                        inventory=None, KERNEL_FLOOR_LAYER, _floor_added_line_numbers, _floor_changed_paths, _floor_scan_files, _floor_secret_hits, _floor_tracked_lines,
                        _floor_is_journal_path=_floor_is_journal_path,
                        _floor_journal_row_redactable=_floor_journal_row_redactable,
                        floor=None) -> list:
    """ATOM 1 — the named-shape credential scan. Diff-scoped by default; WIDENED to the whole
    tracked tree when the `shared-repo-floor` lens is active. Never NARROWER than the every-branch
    floor, and fail-closed: an unresolvable diff widens to the tree rather than scanning nothing.

    BOTH SCOPES SCAN FILE CONTENT AT THE CANDIDATE, never patch text (audit-post r3 finding 2): the
    diff-scoped leg asks git only WHICH PATHS this ship touched and then reads those files through
    the SAME `_floor_scan_files` reader the whole-tree leg uses. A binary or attributes-suppressed
    change therefore has exactly the content-visibility a text one does, and the two scopes can no
    longer disagree about what a file contains.

    BOTH LEGS ARE STREAMING GENERATORS (T-12226), so THIS function owns the `errors` list and the
    ORDER BELOW IS LOAD-BEARING: `_floor_secret_hits` must run FIRST, because exhausting the generator
    is what appends the errors. Reading `errors` before the scan is consumed would read an EMPTY list
    and report a clean verdict over a scope whose unreadable file had not been reached yet — the exact
    false green the fail-closed refusal exists to prevent."""
    errors: list = []
    changed = None if tree_wide else _floor_changed_paths(worktree, base_ref, _run_git_cap)
    if changed is not None:
        added = _floor_added_line_numbers(worktree, base_ref, _run_git_cap)
        scope = ("the lines this ship ADDED to the files it touched (a path whose added-line view "
                 "could not be resolved — a binary or diff-suppressed change — is scanned WHOLE)"
                 if added is not None else
                 "the files this ship added or modified (its added-line view was unresolvable — "
                 "fail-closed widening to whole-file content)")
        lines = _floor_scan_files(worktree, changed, errors, added_lines=added)
    else:
        lines = _floor_tracked_lines(worktree, _run_git_cap, inventory, errors)
        scope = ("the WHOLE TRACKED TREE (shared-repo-floor lens ACTIVE, or the profile could not be "
                 "resolved — the gate only ever widens)" if tree_wide else
                 "the WHOLE TRACKED TREE (the candidate diff was unresolvable — fail-closed widening)")
    # T-13121 (SPEC-0163 rule 4d) — a JOURNAL row named by a well-formed allowlist entry is SET
    # ASIDE before the scan, never admitted after it: `_floor_secret_hits` keeps only the FIRST hit
    # per (path, label), so admitting a listed hit afterwards would let it hide a later unlisted row.
    # With no well-formed entry the scan is byte-for-byte the pre-T-13121 one.
    allow_hashes, allow_malformed = _floor_journal_allowlist(floor)
    set_aside: list = []
    if allow_hashes:
        def _unlisted(src):
            for path, lineno, text in src:
                if _floor_is_journal_path(path) and _floor_row_sha256(text) in allow_hashes:
                    set_aside.append((path, lineno, text))
                    continue
                yield path, lineno, text
        lines = _unlisted(lines)
    hit_text: dict = {}                  # T-12779 — the offending LINE, for the remedy partition
    hits = _floor_secret_hits(lines, hit_text=hit_text)  # EXHAUSTS the generator — this fills `errors`
    if set_aside:
        # ADMITTED only when its bytes are on `main` at the merge-base (True — `None` is NOT on
        # main here). A listed row the land ADDS rejoins the ordinary partition and keeps rule 4c.
        memo_aside: dict = {}
        rejoin = []
        for path, lineno, text in set_aside:
            try:
                row = json.loads(text)
                row_ts = row.get("ts") if isinstance(row, dict) else None
            except (ValueError, TypeError):
                row_ts = None
            if not (isinstance(row_ts, str) and row_ts and _floor_journal_row_on_main(
                    text, row_ts, worktree, base_ref, _run_git_cap, memo_aside) is True):
                rejoin.append((path, lineno, text))
        if rejoin:
            seen = {(h[0], h[2]) for h in hits}
            for h in _floor_secret_hits(rejoin, hit_text=hit_text):
                if (h[0], h[2]) not in seen:
                    hits.append(h)
    out = []
    if errors:
        # FAIL-CLOSED: the scope could not be read WHOLE, so a clean result would be a claim about
        # files nobody scanned (audit-post finding 2).
        out.append(f"land(floor): the {KERNEL_FLOOR_LAYER!r} SECRETS atom REFUSES this branch — its "
                   f"scan scope ({scope}) could NOT be read whole, so a clean verdict would be a "
                   f"claim about files nobody scanned: " + "; ".join(errors[:10]) + ". Make the "
                   f"named path(s) readable (or untrack them), then re-land.")
    if not hits:
        return out

    # T-12779 (SPEC-0163 rule 4c) — THE THREE-WAY REMEDY PARTITION, so no emitted remedy is one the
    # verb would refuse. It is computed ONLY here, on a land this atom is ALREADY refusing, and only
    # for JOURNAL paths: a PASSING land does exactly what it did before this card, byte for byte,
    # with zero added git processes. The added-line view below is resolved LAZILY (the diff-scoped
    # leg already holds it; the tree-wide leg resolves it only when a journal hit exists), and the
    # on-main reads are bounded three ways — by the <=10 named hits, by the dated-segment narrowing
    # inside `_floor_journal_row_on_main`, and by the per-scan `memo`.
    journal_hits = [h for h in hits if _floor_is_journal_path(h[0])]
    source_hits = [h for h in hits if not _floor_is_journal_path(h[0])]
    redactable, unredactable = [], []
    if journal_hits:
        added_view = added if changed is not None else _floor_added_line_numbers(worktree, base_ref, _run_git_cap)
        memo: dict = {}
        for path, lineno, label in journal_hits:
            text = hit_text.get((path, lineno)) or ""
            try:
                row = json.loads(text)
                row_ts = row.get("ts") if isinstance(row, dict) else None
            except (ValueError, TypeError):
                row_ts = None
            # THE VERB IS NAMED ONLY WHEN THE LOCATOR IT NEEDS IS IN HAND: a line that will not
            # parse, or carries no `ts`, falls to the NON-redactable wording rather than printing a
            # `--ts` nobody can pass.
            if isinstance(row_ts, str) and row_ts and _floor_journal_row_redactable(
                    path, lineno, text, row_ts, added_view, worktree, base_ref, _run_git_cap, memo):
                redactable.append((path, lineno, label, row_ts))
            else:
                unredactable.append((path, lineno, label))

    def _named(rows):
        return "; ".join(f"{p}:{n}: {label}" for p, n, label, *_rest in rows[:10])

    def _hashes(rows):
        return "; ".join(f"{p}:{n}: {_floor_row_sha256(hit_text.get((p, n)))}" for p, n, *_rest in rows[:10])

    if source_hits:
        out.append(f"land(floor): the {KERNEL_FLOOR_LAYER!r} SECRETS atom REFUSES this branch — a named "
            f"credential shape is present in {scope}: {_named(source_hits)}. The any-author land floor runs for "
            f"EVERY branch regardless of author and cannot be waived (SPEC-0163). Remove the "
            f"credential (and ROTATE it — it is in the branch history), then re-land. If the named "
            f"line is a configuration TEMPLATE and not a credential, the exemption for an "
            f"interpolation ({'${VAR}'} / $VAR / {'{{var}}'} / %(var)s / <placeholder>) covers only a "
            f"token that is WHOLLY one — a partially-interpolated token still carries a literal "
            f"fragment, so express the whole secret as a single interpolation.")
    for path, lineno, label, row_ts in redactable[:10]:
        out.append(f"land(floor): the {KERNEL_FLOOR_LAYER!r} SECRETS atom REFUSES this branch — a named "
            f"credential shape is present in {scope}: {path}:{lineno}: {label}. The any-author land "
            f"floor runs for EVERY branch regardless of author and cannot be waived (SPEC-0163). This "
            f"is a JOURNAL row THIS BRANCH WROTE, and the journal is append-only, so the generic "
            f"«remove it» is not performable on it — the governed route out is `bin/yitc-v2 journal "
            f"redact --ts {row_ts} --path {path} --line {lineno} --atom secrets`, which replaces the "
            f"credential in that row with a placeholder and journals one `journal_redacted` receipt "
            f"(SPEC-0163 rule 4c). ROTATE the credential itself as well — it is in the branch history.")
    if unredactable:
        # AC3 EXCLUSIVITY, read strictly (audit-post r1 finding 7): the branch-redaction verb is
        # NAMED in exactly ONE rendering — the one where it would ADMIT the row. Here it would
        # refuse, so today's rule-4a wording is kept BYTE-FOR-BYTE and the honest clause that
        # follows names no verb: a reader must not have to work out that the route printed beside
        # the refusal is one they cannot take.
        out.append(f"land(floor): the {KERNEL_FLOOR_LAYER!r} SECRETS atom REFUSES this branch — a named "
            f"credential shape is present in {scope}: {_named(unredactable)}. The any-author land floor runs for "
            f"EVERY branch regardless of author and cannot be waived (SPEC-0163). Remove the "
            f"credential (and ROTATE it — it is in the branch history), then re-land. If the named "
            f"line is a configuration TEMPLATE and not a credential, the exemption for an "
            f"interpolation ({'${VAR}'} / $VAR / {'{{var}}'} / %(var)s / <placeholder>) covers only a "
            f"token that is WHOLLY one — a partially-interpolated token still carries a literal "
            f"fragment, so express the whole secret as a single interpolation. NOTE: this is a "
            f"JOURNAL row that is NOT provably this branch's — its bytes are already on `main` at the "
            f"merge-base (a row this branch merely ROTATED is `main`'s row at a new address), or its "
            f"added-line provenance could not be resolved — so no branch-side redaction route reaches "
            f"it; `main` is never rewritten (SPEC-0163 rule 4c). If the row's bytes ARE on `main`, the "
            f"route is SPEC-0163 rule 4d: ROTATE the credential, then name that exact row in "
            f"`verify.floor.secrets.journal_allowlist` (yitc-ops.yaml) with its sha256 "
            f"({_hashes(unredactable)}), a reason, a date (YYYY-MM-DD) and a rotation note."
            + (f" IGNORED as malformed: {'; '.join(allow_malformed[:10])}." if allow_malformed else ""))
    return out


def _floor_dependency_manifests(worktree: Path, _run_git_cap, inventory=None, *, _FLOOR_MANIFEST_LOCKS=_FLOOR_MANIFEST_LOCKS, _floor_tracked_inventory) -> tuple:
    """`(manifests, errors)` — every TRACKED dependency manifest in the candidate tree, at the root
    AND NESTED, as `(relpath, dirpath, locks, tracked)` quadruples, where `tracked` is the SHARED
    tracked-path set (the same enumeration, handed on so the caller can ask whether a lockfile is
    COMMITTED rather than merely PRESENT — audit-post r3 findings 4 + 11).

    WHY NESTED (audit-post r2 finding 4): discovery used to test `(worktree / m).exists()` for each
    name in `_FLOOR_MANIFEST_LOCKS` — repository-ROOT manifests only. The common real shape is a
    polyglot repo whose JS dependencies live in `frontend/package.json` and whose Python ones live at
    the root; under root-only discovery the whole frontend dependency set landed with no lockfile and
    no advisory audit, and the atom reported clean. The manifest an attacker (or an ordinary tired
    human) adds is precisely the one in a subdirectory.

    THE WALK IS THE TRACKED-FILE ENUMERATION, not a filesystem walk — so it is BOUNDED by the index,
    honours `.gitignore` for free (an ignored `node_modules/**/package.json` is not tracked and is
    never considered), and needs no depth heuristic or exclusion list of its own. FAIL-CLOSED: an
    enumeration that cannot be run or that fails yields an `errors` entry, and the caller REFUSES —
    a discovery pass that could not see the tree must not report "no manifests"."""
    if inventory is None:
        inventory, inv_errors = _floor_tracked_inventory(worktree, _run_git_cap)
        if inventory is None:
            return [], [f"{e}, so 'no dependency manifest' cannot be claimed" for e in inv_errors]
    tracked = frozenset(inventory)
    by_name = dict(_FLOOR_MANIFEST_LOCKS)
    out = []
    for rel in inventory:
        name = rel.rsplit("/", 1)[-1]
        locks = by_name.get(name)
        if locks is None:
            continue
        out.append((rel, (worktree / rel).parent, locks, tracked))
    out.sort(key=lambda t: t[0])
    return out, []


def _floor_manifest_declares_dependencies(path: Path, name: str) -> bool:
    """Does this manifest declare a dependency SET at all? FAIL-CLOSED — anything this cannot read
    or does not understand is `True`.

    DECLARED IN SPEC-0093 rule 27 §THE DEPENDENCY ATOM'S KERNEL HALF, not single-homed here
    (audit-post r3 finding 6). This is the ONE exemption from the "a present manifest implies a
    committed lockfile AND a declared `dependencies.command`" contract, and an exemption a project
    cannot read is indistinguishable from the implementation quietly holding a different contract than
    its spec — which is what the auditor found. The spec now carries the exemption, its bound
    (`package.json` alone, read as JSON, fail-closed on anything else) and the reason; this docstring
    is the code-side pointer to it.

    The lockfile leg refuses "an unpinned dependency set"; a manifest that declares NO dependencies
    has no set to pin, and refusing it would be a false positive — the precise failure mode
    `_FLOOR_SECRET_PATTERNS`'s sibling comment names as the one that gets a security gate disabled.
    It only became reachable when discovery went NESTED: a local `file:` sub-package
    (`frontend/dep/package.json`, a real and ordinary npm shape) is a dependency-free manifest that
    root-only discovery never saw.

    Understood narrowly and on purpose — `package.json`'s four dependency maps, read as JSON. Every
    other manifest, and any manifest that will not parse, answers `True`, so no ecosystem's existing
    verdict moves."""
    if name != "package.json":
        return True
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not isinstance(doc, dict):
        return True
    return any(isinstance(doc.get(k), dict) and doc.get(k)
               for k in ("dependencies", "devDependencies",
                         "optionalDependencies", "peerDependencies"))


def _floor_dependency_hygiene(worktree: Path, floor: dict, _run_git_cap=None, inventory=None, *, CONSUMER_OPS_CONTRACT, KERNEL_FLOOR_LAYER, _floor_dependency_manifests, _floor_manifest_declares_dependencies, _floor_requirements_fully_pinned) -> list:
    """ATOM 2 — a present dependency MANIFEST implies (a) a committed lockfile and (b) a declared
    `verify.floor.dependencies.command` carrying the frozen install + advisory audit.

    Discovery is the TRACKED-TREE walk (`_floor_dependency_manifests`), so a NESTED manifest counts
    exactly as a root one does. The lock question is asked PER MANIFEST DIRECTORY: a lockfile beside
    `frontend/package.json` pins `frontend/package.json`, and a root lockfile does not — UNLESS that
    root is a WORKSPACE whose tracked declaration lists the member (`_floor_workspace_root_pins`).

    FAIL-CLOSED ON ABSENCE, never delegated-and-forgotten: the kernel cannot itself run a frozen
    install (network — F-025), so for this leg the project's command IS the implementation, and its
    ABSENCE is its own refusal exactly as its non-zero exit (an unwaived critical/high advisory)
    is."""
    # THE WORKSPACE-ROOT CASE (T-13166) — helpers NESTED here, not leaf-level, so the host-residue
    # contract of this leaf (T-12695: every top-level function has a `worktree` residue) is untouched.
    def _floor_workspace_glob_match(pattern, reldir: str) -> bool:
        """Does one workspace-declaration glob select `reldir` (a member directory relative to the
        workspace root)? A STATED CONSERVATIVE BOUNDARY (T-13166, SPEC-0093 rule 27), not a
        re-implementation of any tool's matcher: a leading `./` and a trailing `/` are stripped;
        non-nested brace sets `{a,b}` (two or more alternatives) expand; `**` spans directories;
        `*` and `?` stay inside one segment; `[...]` / `[!...]` are character classes. Anything
        else — a singleton or nested brace, an unclosed `{`/`[`, an extglob `@(` `+(` `!(` `*(`
        `?(` — answers NO MATCH. That direction is the fail-closed one: an unrecognised pattern
        leaves the member refused (it commits its own lockfile), never admits an unpinned one."""
        if not isinstance(pattern, str):
            return False
        pat = pattern.strip()
        while pat.startswith("./"):
            pat = pat[2:]
        pat = pat.rstrip("/")
        if not pat or any(x in pat for x in ("@(", "+(", "!(", "*(", "?(")):
            return False
        lb = pat.find("{")
        if lb != -1:
            rb = pat.find("}", lb)
            if rb == -1 or "{" in pat[lb + 1:rb] or "," not in pat[lb + 1:rb]:
                return False          # a singleton `{a}` is NOT a brace set — it stays literal
            return any(_floor_workspace_glob_match(pat[:lb] + alt + pat[rb + 1:], reldir)
                       for alt in pat[lb + 1:rb].split(","))
        if "}" in pat:
            return False
        rx, i = [], 0
        while i < len(pat):
            c = pat[i]
            if pat.startswith("**/", i):
                rx.append("(?:.*/)?"); i += 3
            elif pat.startswith("**", i):
                rx.append(".*"); i += 2
            elif c == "*":
                rx.append("[^/]*"); i += 1
            elif c == "?":
                rx.append("[^/]"); i += 1
            elif c == "[":
                j = pat.find("]", i + 2)
                if j == -1:
                    return False
                body = pat[i + 1:j]
                neg = body[:1] in ("!", "^")
                if neg:
                    body = body[1:]
                if not body:
                    return False
                rx.append("[" + ("^/" if neg else "")
                          + "".join(ch if ch == "-" else re.escape(ch) for ch in body) + "]")
                i = j + 1
            else:
                rx.append(re.escape(c)); i += 1
        try:
            return re.fullmatch("".join(rx), reldir) is not None
        except re.error:
            return False

    def _floor_workspace_declarations(worktree: Path, tracked) -> dict:
        """`{root_dir: [patterns]}` — every WORKSPACE ROOT in the tracked snapshot whose lockfile and
        declaration are BOTH tracked there: pnpm (`pnpm-lock.yaml` + `pnpm-workspace.yaml` `packages`),
        npm/yarn (a `("package-lock.json", "npm-shrinkwrap.json", "yarn.lock")` lock + `package.json` `workspaces`, a list or a mapping's
        `packages`). Computed ONCE per dependency-floor invocation, so each declaration file is read and
        parsed once however many members it lists. FAIL-CLOSED: a root whose declaration will not read
        or parse, or is not a list of strings, contributes nothing — its members stay refused."""
        out: dict = {}
        for rel in tracked:
            name = rel.rsplit("/", 1)[-1]
            root = rel.rsplit("/", 1)[0] if "/" in rel else ""
            pre = f"{root}/" if root else ""
            try:
                if name == "pnpm-workspace.yaml" and f"{pre}pnpm-lock.yaml" in tracked:
                    doc = state.load_str((worktree / rel).read_text(encoding="utf-8"))
                    pats = doc.get("packages") if isinstance(doc, dict) else None
                elif name == "package.json" and any(f"{pre}{lk}" in tracked
                                                    for lk in ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock")):
                    doc = json.loads((worktree / rel).read_text(encoding="utf-8"))
                    pats = doc.get("workspaces") if isinstance(doc, dict) else None
                    if isinstance(pats, dict):
                        pats = pats.get("packages")
                else:
                    continue
            except Exception:
                continue
            if isinstance(pats, list) and pats and all(isinstance(x, str) for x in pats):
                out.setdefault(root, []).extend(pats)
        return out

    def _floor_workspace_root_pins(rel: str, decls: dict) -> bool:
        """Is the nested `package.json` at `rel` a MEMBER of a workspace whose root (a STRICT ancestor)
        holds the tracked lockfile? It is when some positive pattern of that root's declaration selects
        the member directory and no `!`-negated one does (SPEC-0093 rule 27, the workspace-root case)."""
        if rel.rsplit("/", 1)[-1] != "package.json" or "/" not in rel:
            return False
        mdir = rel.rsplit("/", 1)[0]
        for root, pats in decls.items():
            if root and not mdir.startswith(f"{root}/"):
                continue
            sub = mdir[len(root) + 1:] if root else mdir
            if (any(_floor_workspace_glob_match(p, sub) for p in pats if not p.startswith("!"))
                    and not any(_floor_workspace_glob_match(p[1:], sub) for p in pats if p.startswith("!"))):
                return True
        return False

    manifests, errors = _floor_dependency_manifests(worktree, _run_git_cap, inventory)
    out = []
    if errors:
        out.append(f"land(floor): the {KERNEL_FLOOR_LAYER!r} DEPENDENCY atom REFUSES this branch — "
                   f"its manifest discovery could not read the tracked tree, so a clean verdict "
                   f"would be a claim about manifests nobody looked for: " + "; ".join(errors[:10]))
        return out
    if not manifests:
        return out
    declaring = []
    decls = None
    for rel, d, locks, tracked in manifests:
        if not _floor_manifest_declares_dependencies(worktree / rel, rel.rsplit("/", 1)[-1]):
            continue          # no dependency SET to pin — see the predicate's docstring
        declaring.append(rel)
        # COMMITTED, not merely PRESENT (audit-post r3 finding 4). This asked `(d / lk).exists()`,
        # which a `.gitignore`d or simply un-added `package-lock.json` satisfies — so a lockfile that
        # reaches NO other checkout, and which the reviewer of this branch never sees, vouched for the
        # dependency set. The claim the refusal text makes is "a COMMITTED lockfile", so the test is
        # membership in the SAME tracked-file snapshot the manifests were discovered from: one
        # inventory, one snapshot, no window in which a file is tracked for one question and not the
        # other. `prefix` is "" at the repository root, so the root case needs no branch of its own.
        prefix = f"{rel.rsplit('/', 1)[0]}/" if "/" in rel else ""
        if any(f"{prefix}{lk}" in tracked for lk in locks):
            continue
        # THE WORKSPACE-ROOT CASE (T-13166): a pnpm/npm/yarn workspace commits ONE lockfile at its
        # root, and that lock pins every member its declaration lists. Declarations are resolved once
        # per invocation from the same tracked snapshot; an unlisted member still needs its own lock.
        if decls is None:
            decls = _floor_workspace_declarations(worktree, tracked)
        if _floor_workspace_root_pins(rel, decls):
            continue
        # The `requirements.txt`-as-its-own-lock leg, applied AFTER the existence test rather than
        # inside it (r2 finding 3): the file vouches only when every requirement line is `==`-pinned.
        # It must itself be TRACKED, on the same reasoning as the named locks above.
        if (rel.rsplit("/", 1)[-1] == "pyproject.toml"
                and f"{prefix}requirements.txt" in tracked
                and _floor_requirements_fully_pinned(d / "requirements.txt")):
            continue
        out.append(f"land(floor): the {KERNEL_FLOOR_LAYER!r} DEPENDENCY atom REFUSES this branch — "
                   f"{rel} declares dependencies but NO committed lockfile is tracked beside it "
                   f"(looked for: {', '.join(locks)}). An unpinned dependency set cannot be audited "
                   f"for advisories, so it cannot land (SPEC-0163). A lockfile that exists on disk "
                   f"but is untracked or ignored does NOT satisfy this — it reaches no other "
                   f"checkout and no reviewer of this branch.")
    # THE COMMAND-ABSENCE LEG FIRES ON EVERY DISCOVERED DEPENDENCY-DECLARING MANIFEST, root or nested
    # (audit-post r3 finding 3). It was scoped to ROOT manifests on the reasoning that widening it
    # imposes a NEW MANDATORY DECLARATION rather than closing a bypass — but that reasoning does not
    # survive the shape it leaves behind: a repo whose ONLY manifest is `frontend/package.json` got
    # its lockfile checked and its advisory audit silently waived, which is the ordinary polyglot
    # shape, not an edge. The plan and SPEC-0093 rule 27 both state the obligation over a PRESENT
    # manifest with no root qualifier, so the narrowing was also the implementation quietly holding a
    # different contract than its spec. The obligation is one declaration per PROJECT, not per
    # manifest, and a project with no dependency-declaring manifest at all still owes nothing.
    entry = floor.get("dependencies") if isinstance(floor.get("dependencies"), dict) else {}
    cmd = str(entry.get("command") or "").strip()
    if declaring and not cmd:
        out.append(f"land(floor): the {KERNEL_FLOOR_LAYER!r} DEPENDENCY atom REFUSES this branch — "
                   f"a dependency manifest is present ({', '.join(declaring[:10])}) "
                   f"but {CONSUMER_OPS_CONTRACT} declares no `verify.floor.dependencies.command`. The "
                   f"kernel cannot run a frozen install or an advisory audit itself (F-025 "
                   f"hermeticity), so the project's command IS that leg — and its ABSENCE is its own "
                   f"refusal, never a silent pass (SPEC-0093 `verify.floor`).")
    return out


def _floor_declared_probes(worktree: Path, ops, floor: dict, _run_git_cap, *, _now=None, CONSUMER_OPS_CONTRACT, KERNEL_FLOOR_LAYER, _FLOOR_PROBE_MAX_AGE_DAYS=_FLOOR_PROBE_MAX_AGE_DAYS, _floor_carrier_entry_history, _floor_instant, _floor_probe_definition_digest, _floor_probe_journals, _floor_probe_rows, base_doc=None, pending_out=None) -> list:
    """ATOM 3 — every declared SPEC-0098 `security.probes[]` entry must carry a verdict that is
    DEFINITION-BOUND, CANDIDATE-BOUND and AGE-BOUND.

    (i) DEFINITION-BOUND via the WATERMARK, the primary mechanism: the latest
        `security_live_probe_passed` row for the property carries a `definition_digest`, and it must
        equal the CANDIDATE's canonical digest of that entry. One equality; NO history is read, and
        this is the steady state the mechanism decays to.
    (ii) LEGACY FALLBACK, bounded and traversed ONCE, for a row written before the watermark: the
        row's own recorded `url`/`expect` must equal the candidate's declaration, AND the entry must
        not have CHANGED since the row (one shared `git log` over the carrier, bounded to the
        freshness window). A pass predating the change reads NOT-PASSED.
    (iii) AGE-BOUND: the row must be newer than `verify.floor.probes.max_age_days` (default 30).

    STATED BOUND — the kernel cannot fire a live URL inside a land verify (F-025), so what this
    certifies is DEFINITION-BOUND HISTORICAL LIVENESS EVIDENCE, not a live re-probe. What it rules
    out is a pass vouching for a definition it never exercised.

    NEWLY-DECLARED ADMISSION (T-12982, SPEC-0093 rule 27). A probe for code this very branch ships
    can only pass AFTER the land deploys that code, so refusing it closes a loop no branch can exit.
    When `base_doc` (the trusted base's parsed carrier) is a mapping, a refused entry whose
    `property` the base does NOT declare is instead appended to `pending_out` — "awaiting its first
    post-deploy check" — unless its latest verdict is `security_live_probe_escalated` (a recorded
    negative is never admitted). `base_doc=None` (base unknown/unreadable) admits nothing, and a
    property already on the base keeps today's refusal, so the pending state cannot outlive the next
    land. The debt fold passes `base_doc={}` to ask the SAME predicate which declared probes are
    not currently vouched (`debt.probes_awaiting_first_check`)."""
    def _probe_vouch_route(entry: dict) -> str:  # nested: a helper, not a residue-bearing leaf
        """The GOVERNED way out of a probes-atom refusal, spelled for THIS entry (T-13231 / yitc#35). The
        refusal used to name no route, so an adopter recovered only by hand-editing a card. The verdict
        the atom reads is written by exactly one producer — `liveprobe` running a card's security
        `live_probe` — and that card field has exactly one writer, `task update --live-probe-*`."""
        prop = str(entry.get("property") or "").strip() or "<property>"
        url = str(entry.get("url") or "").strip() or "<url>"
        return (f" GOVERNED ROUTE to vouch for it: declare the same probe on a task card — `yitc-v2 task "
                f"update <T-ID> --live-probe-url {url} --live-probe-expect-status <status> "
                f"--live-probe-property {prop} --live-probe-assert-header-present <Header>` (or "
                f"--live-probe-assert-header-absent / --live-probe-assert-cookie-flags) — then run "
                f"`yitc-v2 liveprobe --task <T-ID>` against the deployed site, which records "
                f"`security_live_probe_passed`, and re-land; or, if the probe no longer applies, remove "
                f"the entry from `security.probes` in yitc-ops.yaml.")

    sec = ops.get("security") if isinstance(ops, dict) else None
    declared = [e for e in ((sec.get("probes") if isinstance(sec, dict) else None) or [])
                if isinstance(e, dict) and str(e.get("property") or "").strip()]
    if not declared:
        return []
    pentry = floor.get("probes") if isinstance(floor.get("probes"), dict) else {}
    raw_age = pentry.get("max_age_days", _FLOOR_PROBE_MAX_AGE_DAYS)
    # STRICTLY A NON-BOOLEAN INT (audit-post r3 finding 10). `int(raw_age)` accepted `True` (⇒ 1 day,
    # so a declaration that is obviously not a day count silently became the tightest possible bound),
    # `"30"` and `30.9` (⇒ 30, truncating a value the project wrote deliberately). The key is
    # DOCUMENTED as a positive whole number of days, and a carrier that does not say that should be
    # told so rather than coerced into something adjacent — a malformed declaration is a refusal, the
    # same fail-closed stance every other declaration read in this floor takes. `bool` is excluded
    # explicitly because it is an `int` subclass and would otherwise pass the isinstance test.
    if isinstance(raw_age, bool) or not isinstance(raw_age, int) or raw_age <= 0:
        return [f"land(floor): {CONSUMER_OPS_CONTRACT} `verify.floor.probes.max_age_days` is "
                f"malformed ({raw_age!r}) — declare a positive whole number of days (an integer, not "
                f"a string, boolean or fraction) or omit the key for the default of "
                f"{_FLOOR_PROBE_MAX_AGE_DAYS} (SPEC-0093 `verify.floor`)."]
    max_age = raw_age
    import datetime as _dt
    now = _now or _dt.datetime.now(_dt.timezone.utc)
    cutoff = now - _dt.timedelta(days=max_age)
    rows, row_errors = _floor_probe_rows(_floor_probe_journals(worktree))
    if row_errors:
        # FAIL-CLOSED PER SOURCE/ROW (audit-post r3 finding 8): a verdict record that could not be
        # read whole cannot answer "what is the NEWEST verdict for this property", and the answer it
        # would otherwise give is the older row underneath — the one the unreadable newer row exists
        # to supersede.
        return [f"land(floor): the {KERNEL_FLOOR_LAYER!r} PROBES atom REFUSES this branch — the "
                f"SPEC-0098 verdict record could not be read whole, so the latest verdict for a "
                f"declared probe cannot be determined: " + "; ".join(row_errors[:10]) + ". Repair or "
                f"remove the named source/row, then re-land."]
    # KEYED BY (property, url), not property (T-12981): each row is folded onto the ONE declared entry
    # it belongs to (`_probe_row_owner`), so two entries proving one property on two paths each keep
    # their own latest verdict instead of the last row of the property shadowing the other.
    cur_entries = {_probe_entry_key(e): _floor_probe_definition_digest(e) for e in declared}
    peers: dict = {}
    for e in declared:
        peers.setdefault(str(e["property"]).strip(), []).append(e)
    peer_digests = {p: [_floor_probe_definition_digest(e) for e in es] for p, es in peers.items()}
    latest: dict = {}
    for row in rows:
        prop = str((row.get("data") or {}).get("property") or "").strip()
        if prop not in peers:
            continue
        owner = _probe_row_owner(row, peers[prop], peer_digests[prop])
        if owner is None:
            continue
        # T-13439 — a governed-deploy verdict counts ONLY under the SAME definition it was proved
        # under: a digest that is not this candidate entry's current one refreshes nothing, and it
        # must not shadow an older verdict that does vouch (nor ever reach the legacy fallback).
        if ((row.get("data") or {}).get("source") == DEPLOY_PROBE_SOURCE
                and row["data"].get("definition_digest") != peer_digests[prop][owner]):
            continue
        latest[_probe_entry_key(peers[prop][owner])] = row
    # The single bounded carrier traversal, computed ONCE for every entry that needs the legacy
    # fallback — and NOT AT ALL when every latest row carries a watermark.
    needs_history = [e for e in declared
                     if not ((latest.get(_probe_entry_key(e)) or {}).get("data") or {}
                             ).get("definition_digest")]
    history = (_floor_carrier_entry_history(worktree, _run_git_cap, cutoff, cur_entries)
               if needs_history else {})
    out = []
    for entry in declared:
        prop = str(entry["property"]).strip()
        key = _probe_entry_key(entry)
        row = latest.get(key)
        head = (f"land(floor): the {KERNEL_FLOOR_LAYER!r} PROBES atom REFUSES this branch — declared "
                f"security probe {prop!r}" + (f" at {key[1]!r}" if len(peers[prop]) > 1 else ""))
        if row is None:
            out.append(f"{head} has NO recorded SPEC-0098 verdict in this checkout's journal. A "
                       f"declared probe with no evidence is unvouched, not passing (SPEC-0163).")
            continue
        if row.get("type") != "security_live_probe_passed":
            out.append(f"{head} last recorded `security_live_probe_escalated` — the property could "
                       f"not be proved, so it does not vouch for this land (SPEC-0098 §2).")
            continue
        data = row.get("data") or {}
        raw_ts = str(row.get("ts") or "")
        ts = _floor_instant(raw_ts)
        if ts is None:
            # `_floor_probe_rows` already refused an ABSENT `ts`; this is one that is present and
            # unparseable-or-implausibly-future (r3 finding 9). Such a value used to sort ABOVE every
            # real timestamp AND pass a lexical age check, so it both won the latest-verdict selection
            # and read as fresh.
            out.append(f"{head} last passed at {raw_ts!r}, which is not a usable timestamp (malformed, "
                       f"or implausibly far in the future). A verdict that cannot be placed in time "
                       f"cannot be shown to be fresh. Re-run the probe, then re-land.")
            continue
        if ts < cutoff:
            out.append(f"{head} last passed at {raw_ts}, which is older than the declared "
                       f"freshness bound of {max_age} day(s). Re-run the probe, then re-land.")
            continue
        digest = data.get("definition_digest")
        if digest:
            if digest != _floor_probe_definition_digest(entry):
                out.append(f"{head} last passed under a DIFFERENT definition (the row's "
                           f"`definition_digest` does not match this candidate's declaration). A "
                           f"pass cannot vouch for a probe definition it never exercised — re-run "
                           f"the probe against the current declaration, then re-land.")
            continue
        # LEGACY row (pre-watermark): row-equality AND the bounded history conjunct.
        if str(data.get("url") or "") != str(entry.get("url") or ""):
            out.append(f"{head} last passed against url {data.get('url')!r}, but this candidate "
                       f"declares {entry.get('url')!r} — the pass exercised a different definition.")
            continue
        # The `expect` half of the promised row-equality. DOCUMENTED AT ITS HOME, not here: SPEC-0093
        # rule 27 states row-equality as TWO conjuncts (`url`, and a declared `expect`) — until r2
        # finding 6 the spec described the `url` equality alone while this code also refused on a
        # declared-`expect` mismatch, which single-homed a REFUSAL RULE in the implementation.
        # Checked ONLY when the candidate entry DECLARES an `expect` to compare against: the row's `expect` is DERIVED by
        # the probe runner from the entry's `assertion`, and the kernel cannot re-derive it inside a
        # hermetic verify — so an entry that declares only a free-text `assertion` has its change
        # caught by the history conjunct below (which is what the AC3c differential isolates), and an
        # entry that DOES declare `expect` is compared here, where the comparison is real.
        if entry.get("expect") is not None and str(data.get("expect") or "") != str(entry["expect"]):
            out.append(f"{head} last passed with expectation {data.get('expect')!r}, but this "
                       f"candidate declares {entry['expect']!r} — the pass exercised a different "
                       f"definition.")
            continue
        if history is None:
            out.append(f"{head} has a pre-watermark verdict and the carrier history could not be "
                       f"read, so the definition cannot be proved unchanged since that pass. "
                       f"Re-run the probe (its row will carry a `definition_digest`), then re-land.")
            continue
        changed_at = history.get(key)
        if changed_at and changed_at > ts:
            out.append(f"{head} was REDEFINED at {changed_at.isoformat()} — after its last pass at {raw_ts}. A "
                       f"probe whose definition changed after its last pass is NOT passing; re-run "
                       f"it against the current declaration, then re-land.")
    # T-13231 — every per-entry refusal ends with the governed route out, spelled for its entry. Each
    # message STARTS WITH its entry's head (property quoted, url too when the property has peers), so
    # the mapping is exact; the admission allowlist below matches by prefix/substring and is unmoved.
    heads = [(f"land(floor): the {KERNEL_FLOOR_LAYER!r} PROBES atom REFUSES this branch — declared "
              f"security probe {str(e['property']).strip()!r}"
              + (f" at {_probe_entry_key(e)[1]!r}" if len(peers[str(e['property']).strip()]) > 1
                 else ""), e) for e in declared]
    for i, msg in enumerate(out):
        owner = next((e for h, e in heads if msg.startswith(h + " ")), None)
        if owner is not None:
            out[i] = msg + _probe_vouch_route(owner)
    if not isinstance(base_doc, dict):
        return out
    bsec = base_doc.get("security")
    base_props = {str(e.get("property") or "").strip()
                  for e in ((bsec.get("probes") if isinstance(bsec, dict) else None) or [])
                  if isinstance(e, dict)}
    # ADMISSIBLE = a STRUCTURALLY COMPLETE new entry (a non-empty `url` and `assertion` — something the
    # first post-deploy run can actually execute) whose latest row is not an escalation, refused ONLY
    # for want of a vouching pass. The reasons are an explicit ALLOWLIST (audit-post r1): an
    # unreadable history, an unusable timestamp or any future refusal stays a refusal by default.
    fresh = [str(e["property"]).strip() for e in declared
             if str(e["property"]).strip() not in base_props
             and all(str(e.get(k) or "").strip() for k in ("url", "assertion"))
             and (latest.get(_probe_entry_key(e)) or {}).get("type")
             != "security_live_probe_escalated"]
    admissible = ("has NO recorded SPEC-0098 verdict", "older than the declared freshness bound",
                  "last passed under a DIFFERENT definition", "the pass exercised a different definition",
                  " was REDEFINED at ")
    kept = []
    for msg in out:
        prop = next((p for p in fresh if msg.startswith(
            f"land(floor): the {KERNEL_FLOOR_LAYER!r} PROBES atom REFUSES this branch — declared "
            f"security probe {p!r}")), None)
        if prop is None or pending_out is None or not any(a in msg for a in admissible):
            kept.append(msg)                          # no out-param = no recorded admission
        elif prop not in pending_out:
            pending_out.append(prop)
    return kept


def _floor_command_env(*, _FLOOR_COMMAND_SCRUBBED_CARRIERS=_FLOOR_COMMAND_SCRUBBED_CARRIERS, _HERMETIC_AUDITOR_ENV_OVERRIDES, _HERMETIC_HOME_ROOTED_OVERRIDES) -> dict:
    """The environment a `verify.floor.<atom>.command` child sees — the launching land's env with the
    session-identity carriers, the auditor knobs and the HOME-rooted tooling overrides REMOVED.

    ONE criterion, the same one `hermetic_child_env` states and for the same reason: a var is scrubbed
    iff it carries the LAUNCHING SESSION'S OWN STATE or REDIRECTS a host tool's per-user state
    directory. Both classes make the child's answer depend on who started the land rather than on the
    branch under test — and this child, unlike a test subprocess, is DECLARED BY THE CANDIDATE, so
    what it can read is a property of the branch's author. The carrier tuples are REUSED from their
    existing homes above rather than re-spelled (a second list of secrets to scrub drifts from the
    first). PATH / PYTHONPATH and the rest of the ambient env stay, exactly as they do for a verify
    child: they override nothing sandboxed and they are how the command reaches its own toolchain."""
    scrub = set(_HERMETIC_AUDITOR_ENV_OVERRIDES) | set(_HERMETIC_HOME_ROOTED_OVERRIDES)
    scrub |= set(_FLOOR_COMMAND_SCRUBBED_CARRIERS)
    return {k: v for k, v in os.environ.items() if k not in scrub}


def _floor_command_keys(floor, *, _FLOOR_ATOMS=_FLOOR_ATOMS) -> dict:
    """`{atom: command}` for every atom of `floor` declaring a non-empty `command`. `{}` for a
    non-mapping. Pure — the comparable projection both sides of the drift report are taken through,
    so a difference in some OTHER floor key (e.g. `probes.max_age_days`, which is a knob and not an
    executable) is not reported as a command change."""
    out = {}
    if not isinstance(floor, dict):
        return out
    for atom in _FLOOR_ATOMS:
        entry = floor.get(atom)
        cmd = str((entry or {}).get("command") or "").strip() if isinstance(entry, dict) else ""
        if cmd:
            out[atom] = cmd
    return out


def _floor_command_drift(candidate_floor, base_floor, *, CONSUMER_OPS_CONTRACT, _floor_command_keys) -> list:
    """REPORT-ONLY (never a refusal): the floor commands the CANDIDATE declares that differ from the
    TRUSTED BASE's, named by key. The candidate's copy of the section is IGNORED for EXECUTION, so
    without this line a legitimate floor change would be silently dropped and a reviewer would have
    no way to see that the command they read on the branch is not the command that ran. Reporting it
    is what keeps the trust boundary auditable rather than merely quiet (SPEC-0163 §4b policy;
    SPEC-0093 rule 27 shape).

    `base_floor is None` = the base contract could not be read at all: every command the candidate
    declares is then untrusted, and that is said out loud rather than inferred from silence."""
    cand = _floor_command_keys(candidate_floor)
    if base_floor is None:
        if not cand:
            return []
        keys = ", ".join(f"verify.floor.{a}.command" for a in sorted(cand))
        return [f"land(floor): WARN — the TRUSTED BASE {CONSUMER_OPS_CONTRACT} could not be read, so "
                f"NO declared floor command was executed ({keys}). Floor commands are read only from "
                f"the merge-base with main; this land ran the kernel atoms alone. Report-only — the "
                f"land is not refused for this (SPEC-0163 §4b)."]
    base = _floor_command_keys(base_floor)
    diff = sorted(k for k in set(cand) | set(base) if cand.get(k) != base.get(k))
    if not diff:
        return []
    lines = []
    for atom in diff:
        if atom not in base:
            what = f"ADDED by this branch ({cand[atom]!r}) — NOT executed"
        elif atom not in cand:
            what = f"REMOVED by this branch — the base's {base[atom]!r} WAS executed"
        else:
            what = f"ALTERED by this branch ({cand[atom]!r}) — the base's {base[atom]!r} WAS executed"
        lines.append(f"land(floor): WARN — `verify.floor.{atom}.command` is {what}. A floor command "
                     f"is read ONLY from the trusted base (the merge-base with main), so a candidate "
                     f"branch can neither add nor alter one; land the floor-section change on main "
                     f"through its own reviewed card and the NEXT land trusts it. Report-only — the "
                     f"land is not refused for this (SPEC-0163 §4b).")
    return lines


def _floor_trusted_executable(worktree: Path, argv: list, base_ref, _run_git_cap, tmpdir, *, _floor_command_program) -> tuple:
    """Resolve a floor command's PROGRAM to something read from the TRUSTED BASE. Returns
    `(rewritten_argv, refusal_or_None)`.

    SCOPE: only the ONE in-repo program `_floor_command_program` names — argv[0] when it is a path
    inside the worktree, or argv[1] behind a `_FLOOR_INTERPRETERS` argv[0] (T-12688 closed the
    interpreter route: `bash bin/x.sh` used to run the CANDIDATE's `bin/x.sh` because only argv[0]
    was materialized). Host tooling passes through unchanged; it is not candidate-authored to begin
    with.

    THE COMMAND STRING WAS ONLY HALF THE TRUST BOUNDARY (r4 consult finding 2). Reading the command
    from the base fixes WHICH program runs; it does not fix WHOSE BYTES that program is. A
    base-declared `./scripts/dependency-audit.sh` still executed the CANDIDATE worktree's copy of
    that script — the candidate is the cwd — so a collaborator branch could rewrite the script body
    and have the kernel run it. That is exactly the "trusting candidate-authored scripts" the owner
    ruling REJECTED (option C), reached by a second route.

    So an IN-REPO program is MATERIALIZED FROM THE BASE: its bytes are read with
    `git show <base_ref>:<rel>` into a temp file outside the worktree, made executable, and THAT is
    what runs. A path that does not exist at the base cannot be judged from trusted content and is a
    REFUSAL, never a fallback to the candidate's copy.

    RESIDUAL, STATED RATHER THAN HIDDEN: a trusted-base script may itself invoke an in-repo target
    (`python3 ./tool.py` from INSIDE the script), which executes candidate bytes. That reach is
    decided by BASE-reviewed code — the candidate cannot introduce it — which is the same boundary
    `verify.layers` holds, and is what the ruling's «lands through its OWN reviewed path» buys."""
    argv = list(argv)
    hit = _floor_command_program(worktree, argv)
    if hit is None:
        return argv, None                              # host tooling — not candidate-authored
    idx, rel = hit
    if _run_git_cap is None or not base_ref:
        return None, (f"land(floor): the declared floor command names the IN-REPO program {rel!r}, "
                      f"but there is no trusted base to read it from — a candidate-authored script "
                      f"is never executed, so the atom cannot be judged and the land is refused "
                      f"(fail-closed; SPEC-0163 §4b).")
    r = _run_git_cap(["show", f"{base_ref}:{rel}"], worktree)
    if r.returncode != 0:
        return None, (f"land(floor): the declared floor command names the IN-REPO program {rel!r}, "
                      f"which does NOT exist at the trusted base (the merge-base with main). A "
                      f"floor-declared script is read only from the base, never from the candidate "
                      f"branch, so there is nothing trusted to run: land the script on main through "
                      f"its own reviewed card first (SPEC-0163 §4b).")
    dest = Path(tmpdir) / "floor-program"
    try:
        dest.write_text(r.stdout, encoding="utf-8")
        dest.chmod(0o700)
    except Exception as e:                             # noqa: BLE001
        return None, (f"land(floor): the trusted-base copy of {rel!r} could not be materialized "
                      f"({e}) — the floor atom cannot be judged, so the land is refused "
                      f"(fail-closed).")
    argv[idx] = str(dest)
    return argv, None


def _floor_repair_kind(worktree: Path, atom: str, base_cmd: str, base_argv: list, base_bytes: "bytes | None",
                       candidate_floor, *, _floor_command_program) -> tuple:
    """T-12728 (X-1486) — the ONE «does this candidate REPAIR the failing leg» predicate. PURE over
    inputs the runner already holds (the base's command string + argv, the base's materialized bytes,
    the candidate's `verify.floor` section); the only reads are two `is_file` + one `read_bytes` of
    the candidate's program. Returns `(kind, rel)` — `kind` ∈ {'program-altered', 'command-altered'}
    with `rel` the candidate-side program the repair rides on (None for host tooling) — or
    `(None, None)`: not a repair — or `(None, rel)`: not a repair EITHER, the named deleted-program
    shape (the base's program `rel` is absent on the candidate under an unchanged declaration). BOTH seams read this (the runner's carve-out and the work-batch
    gate's `_floor_repair_programs`), so a shape cannot be carried under one reading and refused
    under another.

    THE TWO SHAPES. (i) `program-altered`: the base's failing command names an in-repo program, the
    candidate's copy of it EXISTS and its bytes DIFFER from the trusted-base bytes that just failed.
    (ii) `command-altered`: the candidate's command string for the atom differs from the base's AND
    the in-repo program it resolves to (if any) EXISTS on the candidate — a swap to `scripts/fixed.sh`
    must ship `scripts/fixed.sh` — and this is judged FIRST, so an absent replacement refuses even
    when the old program's bytes were also altered (audit-post r1 F1: the next land would name the
    missing replacement regardless). A DELETED program under an UNCHANGED declaration is NOT a repair
    (audit-pre r1 F1): the next land would still name a missing program, so nothing is repaired —
    the runner refuses that shape by name. A candidate that leaves the failing leg untouched is
    `(None, None)` and refuses exactly as before this card."""
    import shlex
    # THE COMMAND SWAP IS JUDGED FIRST (audit-post r1 F1): when the candidate re-points the atom at
    # a program that is ABSENT, the next land would name a missing program whatever happened to the
    # OLD program's bytes — so an absent replacement refuses before `program-altered` can admit.
    entry = candidate_floor.get(atom) if isinstance(candidate_floor, dict) else None
    cand_cmd = str((entry or {}).get("command") or "").strip() if isinstance(entry, dict) else ""
    swapped = bool(cand_cmd) and cand_cmd != str(base_cmd or "").strip()
    if swapped:
        try:
            cargv = shlex.split(cand_cmd)
        except ValueError:
            return None, None                          # the runner refuses an unparseable command
        chit = _floor_command_program(worktree, cargv)
        if chit is None:
            return "command-altered", None             # host tooling — nothing in-repo to ship
        if (worktree / chit[1]).is_file():
            return "command-altered", chit[1]
        return None, None                              # replacement ABSENT — not a repair
    hit = _floor_command_program(worktree, list(base_argv or []))
    if hit is None:
        return None, None
    rel = hit[1]
    cand = worktree / rel
    try:
        if not cand.is_file():
            return None, rel                           # the deleted-program shape, named
        if base_bytes is not None and cand.read_bytes() != base_bytes:
            return "program-altered", rel
    except OSError:
        pass
    return None, None


def _floor_project_commands(worktree: Path, floor: dict, _verify_test_timeout_seconds,
                            base_ref=None, _run_git_cap=None, candidate_floor=None, repairs_out=None,
                            passed_out=None, *, _FLOOR_ATOMS=_FLOOR_ATOMS, _floor_command_env, _floor_trusted_executable,
                            _floor_repair_kind) -> list:
    """Every declared `verify.floor.<atom>.command` — run BESIDE its kernel check, on every branch
    and under every profile. ADDITIVE BY CONSTRUCTION: a command exiting 0 rescues nothing (the
    kernel atoms above have already spoken), and a non-zero exit is its own refusal.

    `floor` HERE IS THE TRUSTED BASE'S SECTION, never the candidate's (owner ruling 2026-09-06,
    option A — `_base_floor_section`). What this runner executes is therefore a command that already
    landed on main through its own reviewed card; the candidate's copy of the section is IGNORED for
    execution and any difference is REPORTED by `_floor_command_drift`. The trust boundary is the
    SOURCE of the command; the two bounds below are defence in depth on top of it, not instead of it.

    NO SHELL, AND A SCRUBBED ENV (audit-post r3 finding 1). This ran `subprocess.run(cmd, shell=True)`
    with the land's inherited environment — the same shape the project-declared `verify.layers` runner
    uses, which is exactly why it needed changing HERE first: unlike a layer, this command runs on
    EVERY branch regardless of author, so on a shared repo it is a candidate-authored string the
    kernel promises to execute. Under a shell that string is not a command but a program —
    `; curl …`, `$(…)`, a redirect — and it read the launching session's whole environment, including
    its identity carriers.

    The command is now parsed with `shlex` into an ARGV and executed with `shell=False`, so a
    metacharacter is an ARGUMENT rather than syntax, and its environment comes from
    `_floor_command_env`. An UNPARSEABLE command is a REFUSAL, not a fallback to the shell: falling
    back would make the shell reachable by writing a command that fails to parse, which is the
    opposite of a bound. This is a real narrowing of what a declared command can express (no pipes, no
    `&&`); a project needing those puts them in a SCRIPT and declares the script, which is also the
    form a reviewer of that branch can actually read.

    THE CWD/MOUNT CONTRACT, STATED WHERE IT BITES (T-12728, X-1486). The command runs with
    `cwd=str(worktree)` — the REPO ROOT, whatever the launching process's cwd was — and a
    materialized in-repo program runs DETACHED from a temp path OUTSIDE the repo. So a script that
    resolves the repo root from `$0` / `BASH_SOURCE[0]` (`$(dirname "$0")/..`) resolves `/tmp`, and a
    `docker run -v "$PWD":/w` issued after such a `cd` mounts the wrong tree — <project>'s `uv` reported
    «No pyproject.toml found» from inside its own container on every land. The contract is: ANCHOR ON
    CWD. A failing materialized program gets that contract appended to its refusal, so the next
    reader of the abort is told the cause instead of re-diagnosing it.

    THE NAMED EXIT — the `floor-repair` carve-out (T-12728, AC2), sibling of T-12688's bootstrap. A
    broken base leg is executed on EVERY branch, including the one carrying its repair, so without
    an exit the repair is unlandable (<project>'s only way out was a raw emergency commit to main).
    When the base leg FAILS — a materialized program, host tooling, a program not found, or a
    shell-syntax refusal (T-13164) — and the candidate REPAIRS it (`_floor_repair_kind`: its bytes
    or its command string differ, with any in-repo program present), the atom's execution is
    SKIPPED for this ONE land — the candidate's bytes are NEVER run (owner ruling 2026-09-06 option A
    intact), the admission is named on stdout, and `{atom, program, base_exit, kind, executed:
    False}` is appended to `repairs_out` for the land row. The NEXT land runs the repaired program
    from main. A candidate that does not alter the failing leg refuses exactly as before.

    `passed_out` (T-13168) — every declared command that RAN and exited 0 is appended as
    `{atom, command, exit: 0}`, so the land row can prove (CHARTER §P8) that a declared floor ran.
    A failing, refused or repair-skipped atom is never appended."""
    import shlex
    import shutil
    import subprocess
    import tempfile
    env = _floor_command_env()
    out = []

    def _floor_shell_operators(cmd: str) -> list:
        """T-13164 — the shell operators a declared floor command carries as SYNTAX (`&&`, `||`, `|`,
        `;`, `&`, redirects, subshell parens), which the no-shell runner would pass through as plain
        ARGUMENTS. Scanned PER CHARACTER with the shell's own quoting (audit-pre r1+r2): an operator
        is found adjacent (`true&&false`) as well as spaced, while a character inside single or
        double quotes, or one escaped by a backslash outside single quotes, is a literal — so
        `'&&'` and `\\&\\&` do not count and the half-escaped `\\&&` yields its unescaped `&`."""
        ops, run, quote, i = [], "", None, 0
        while i < len(cmd):
            c = cmd[i]
            if quote == "'":
                quote = None if c == "'" else quote
            elif c == "\\":
                i += 1                                 # the next character is literal
            elif quote == '"':
                quote = None if c == '"' else quote
            elif c in "'\"":
                quote = c
            elif c in "();<>|&":
                run += c
                i += 1
                continue
            if run and run not in ops:
                ops.append(run)
            run = ""
            i += 1
        if run and run not in ops:
            ops.append(run)
        return ops

    for atom in _FLOOR_ATOMS:
        entry = floor.get(atom) if isinstance(floor.get(atom), dict) else None
        cmd = str((entry or {}).get("command") or "").strip()
        if not cmd:
            continue
        try:
            argv = shlex.split(cmd)
        except ValueError as e:
            argv = []
            out.append(f"land(floor): `verify.floor.{atom}.command` could not be parsed as a command "
                       f"line ({e}): {cmd!r} — the floor runs declared commands as an ARGV with NO "
                       f"shell, so an unparseable declaration is refused rather than handed to one "
                       f"(SPEC-0093 `verify.floor`).")
        if not argv:
            if cmd:
                out.append(f"land(floor): `verify.floor.{atom}.command` is empty after parsing: "
                           f"{cmd!r} — declare an executable command (SPEC-0093 `verify.floor`).")
            continue
        base_argv = list(argv)

        def _admit_repair(base_exit, base_bytes=None):
            # THE REPAIR CARVE-OUT (T-12728, widened by T-13164 to EVERY failing base leg — host
            # tooling, a not-found program, a shell-operator refusal — not only a materialized
            # in-repo program): the base's leg fails and this branch alters it — execution
            # SKIPPED for this one land, candidate bytes never run.
            kind, rel = _floor_repair_kind(worktree, atom, cmd, base_argv, base_bytes,
                                           candidate_floor)
            if kind is None:
                return False, rel
            print(f"land(floor): REPAIR — the trusted base's `verify.floor.{atom}.command` "
                  f"FAILED (exit {base_exit}) and this branch ALTERS that leg "
                  f"({kind}: {rel or cmd!r}). The atom's execution is SKIPPED for this ONE "
                  f"land so the repair can reach main; the candidate's bytes were NOT run "
                  f"(a floor command runs only from the trusted base — the NEXT land runs "
                  f"the repaired leg from main, SPEC-0163 §4b). Recorded as "
                  f"`floor_repair` on this land's row (T-12728, X-1486, T-13164).")
            if repairs_out is not None:
                repairs_out.append({"atom": atom, "program": rel, "kind": kind,
                                    "base_exit": base_exit, "executed": False})
            return True, rel

        ops = _floor_shell_operators(cmd)
        if ops:
            # NO-SHELL RULE, NAMED (T-13164 AC2): an operator here would run as a plain ARGUMENT —
            # `true && false` exits 0 without ever running `false` — so it is refused before
            # execution rather than judged by an exit code it cannot honestly produce.
            if _admit_repair(None)[0]:
                continue
            out.append(f"land(floor): `verify.floor.{atom}.command` contains shell syntax "
                       f"({', '.join(repr(o) for o in ops)}): {cmd!r} — the floor runs a declared "
                       f"command as an ARGV with NO SHELL (SPEC-0163 §4b, SPEC-0093 "
                       f"`verify.floor`), so `&&`, `|`, `;` and redirects would be passed as plain "
                       f"arguments, not executed. Put the steps in a SCRIPT and declare the script "
                       f"— and land that script on main first, since a floor-declared script's "
                       f"BYTES are read from the trusted base.")
            continue
        # THE PROGRAM'S BYTES COME FROM THE TRUSTED BASE TOO (r4 consult finding 2): an in-repo
        # program is materialized from `base_ref`, so a candidate-rewritten script body is never
        # what runs. Host tooling on PATH passes through unchanged.
        tmpdir = tempfile.mkdtemp(prefix="yitc-floor-prog-")
        materialized = None                            # the temp path the base program ran from
        base_bytes = None                              # its trusted-base bytes, for the repair test
        try:
            argv, refusal = _floor_trusted_executable(worktree, argv, base_ref, _run_git_cap,
                                                      tmpdir)
            if refusal:
                out.append(refusal)
                continue
            materialized = next((a for a in argv if isinstance(a, str) and a.startswith(tmpdir)), None)
            r = subprocess.run(argv, cwd=str(worktree), capture_output=True, text=True, env=env,
                               timeout=_verify_test_timeout_seconds(None))
            if materialized and r.returncode != 0:
                try:
                    base_bytes = Path(materialized).read_bytes()
                except OSError:
                    base_bytes = None
        except FileNotFoundError:
            if _admit_repair(127)[0]:
                continue
            out.append(f"land(floor): `verify.floor.{atom}.command` names a program that does not "
                       f"exist on PATH: {cmd!r} — the floor atom cannot be judged, so the land is "
                       f"refused (fail-closed). Shell syntax (pipes, `&&`, redirects) is NOT "
                       f"available here; put it in a SCRIPT and declare the script — and land that "
                       f"script on main first, since a floor-declared script's BYTES are read from "
                       f"the trusted base, never from the candidate branch (SPEC-0163 §4b).")
            continue
        except OSError as e:
            out.append(f"land(floor): `verify.floor.{atom}.command` could not be executed ({e}): "
                       f"{cmd!r} — the floor atom cannot be judged, so the land is refused "
                       f"(fail-closed).")
            continue
        except subprocess.TimeoutExpired:
            out.append(f"land(floor): `verify.floor.{atom}.command` TIMED OUT: {cmd!r} — the floor "
                       f"atom cannot be judged, so the land is refused (fail-closed).")
            continue
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        if r.returncode != 0:
            tail = (r.stdout + r.stderr).strip()[-500:]
            admitted, rel = _admit_repair(r.returncode, base_bytes)
            if admitted:
                continue
            if materialized:
                contract = (f"\nDETACHED-EXECUTION CONTRACT (T-12728): this in-repo program ran from "
                            f"a trusted-base copy at {materialized!r}, OUTSIDE the repo, with cwd = "
                            f"the repo root {str(worktree)!r}. A script that resolves the repo root "
                            f"from `$0` / `BASH_SOURCE[0]` therefore resolves OUTSIDE the repo (and a "
                            f"`docker run -v \"$PWD\":/w` after such a `cd` mounts the wrong tree) — "
                            f"anchor on cwd (`$PWD`) instead. To repair it, land a branch that alters "
                            f"this program's bytes or its declared command: that land is ADMITTED as "
                            f"a `floor-repair` (execution skipped once, the next land runs the fix).")
                if rel:                                # `(None, rel)` — the deleted-program shape
                    contract += (f"\nNOT A REPAIR: this branch DELETES {rel!r} but leaves "
                                 f"`verify.floor.{atom}.command` unchanged — the next land would "
                                 f"still name a missing program. Alter the program, or alter the "
                                 f"declaration to a program that exists.")
                tail += contract
            out.append(f"land(floor): `verify.floor.{atom}.command` FAILED (exit {r.returncode}): "
                       f"{cmd!r}\n{tail}")
        elif passed_out is not None:
            passed_out.append({"atom": atom, "command": cmd, "exit": r.returncode})
    return out
