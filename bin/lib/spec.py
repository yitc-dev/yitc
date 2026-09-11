"""Spec verb family for the yitc-v2 CLI — `spec new|edit|reverify` (the specs/SPEC-XXXX.yaml graph
nodes, GRAPH §Schema / SPEC-0005 / SPEC-0006 / SPEC-0050 / SPEC-0073). The fourth layer-2 verb-family
extraction (after scenario.py / error.py).

bin/yitc-v2 keeps the thin argparse residue cmd_spec_* (the `set_defaults(func=…)` entrypoints, wiring
unchanged) which delegate here, injecting the host collaborators each verb needs — the audit.py
verb-family precedent (family bodies in lib, host thin residue + injected host deps), so a `-C` REPO_ROOT
rebind and every `monkeypatch.setattr(yitc, …)` stay honored at call time.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It imports only
the already-extracted lower leaf `lib.state` (canonical YAML load for the `spec edit` parse-validate) plus
stdlib; it NEVER back-imports the host. The shared signer `_reverify_spec_signature` (used by
`cmd_task_close --reverify` too — T-1177), its private `_strip_top_key`, and the scaffold toolkit
(`_scaffold_substitute` / `_scaffold_read_validate`) DELIBERATELY stay host-side and are injected here,
since they are cross-called or are a cohesive host-resident family. Behaviour is byte-identical to the
inline originals — the test suite is the oracle.
"""
from __future__ import annotations

import argparse
import re
import sys

from lib import state
from lib import graph as graph_lib   # T-11992: the shared SPEC-0092 retrieval-hint renderer (`spec_query_hint`) — graph.py imports only lib.state + stdlib, so this stays acyclic
from lib import textutil

# ── T-10159 — the at-the-moment spec-body-edit cue (single-SoT string) ────────────────────────────
# The one-line reminder surfaced at every spec-edit-touching moment (SPEC-0005 spec-edit chokepoint;
# SUPPORTS the T-10135 `spec edit --bless` PRIMARY path). Homed here in the spec-domain owner and
# re-used by worktree.py (the T-9730 land-block recovery text) and host cmd_stage (the Execution
# stage-entry) — the SYNC_TO_LAND_RULE-in-dispatch.py precedent, so the four surfaces never diverge.
SPEC_BODY_EDIT_CUE = (
    "amend spec bodies via `spec edit` (--from-file / --bless for multi-line); "
    "raw Edit of an active spec body hard-blocks at land (T-9730)."
)

# ── T-11717 — the STALE-BLESS remedy cue (single-SoT string, the SPEC_BODY_EDIT_CUE precedent) ────
# A bless is DIFF-BOUND (T-10135): the T-9730 land guard clears the spec only if the FINAL base..HEAD
# diff still matches the blessed fingerprint. MEASURED TWICE on 2026-08-27 (T-11700, fingerprint
# ae3698d80c43, invalidated by T-11706's edit to the SAME spec at 675c5007; T-11707 the same hour):
# the invalidator was not an author edit at all — it was the LAND'S OWN update-from-main. The author
# never performs that merge, so "re-bless if you edit further" (an AUTHOR action) does not describe
# it. This cue names the ORDER that converges, and is re-used by worktree.py's stale-fingerprint
# refusal so the diagnosis and the remedy never drift apart.
SPEC_STALE_BLESS_CUE = (
    "REMEDY (the working order): run `worktree sync` FIRST so the branch already carries main's "
    "version of the spec, THEN re-run `spec edit --bless` on the POST-MERGE body, THEN `land` — "
    "sync, then bless, then land. Blessing before the sync re-binds the fingerprint to a body the "
    "land is about to move again (T-11717)."
)

# T-10727 — the TRAVELS RE-PIN companion cue (single-SoT, the SPEC_BODY_EDIT_CUE precedent above).
# A `travels:` re-pin (the SPEC-0073 §3 explicit action at plan-accept) has a HAND-side consequence
# the re-pin path never said out loud: the §1 class column of kernel-vs-self-manifest.md is
# hand-maintained, and its auto-backfill (`graph._backfill_spec_placement_handrow`) runs ONLY at
# `spec new` — never on the edit path. So the row keeps the OLD realm's prefix, the manifest desyncs
# from the derived realm, and tests/test_t0890_placement_backfill.py probe (b2) fails at land verify
# → land ABORTs. The step is already KNOWN (SPEC-0166/0167/0168 carry re-pinned-at-plan-accept notes
# in that manifest — operators have done it by hand); only the cue at the moment of the re-pin was
# missing. Report-only prose: no gate, no event, no store, and no auto-write of the hand table.
SPEC_TRAVELS_REPIN_CUE = (
    "travels re-pin — COMPANION STEP REQUIRED: update this spec's row in the §1 HAND table of "
    "kernel-vs-self-manifest.md so its `class` column prefix matches the NEW realm (the prefix→realm "
    "key is that file's own «Reading the class column» section). The birth-time auto-backfill runs "
    "only at `spec new`, NOT on this edit path — leave the row stale and "
    "tests/test_t0890_placement_backfill.py probe (b2) fails at land verify and ABORTs land "
    "(SPEC-0073 §3)."
)

# ── T-10321 — body-composed `spec edit` matching (the indentation trap, X-0284) ───────────────────
# `spec edit` matches `old` against the RAW file text, but `--help` sells --from-file as a body
# replacement and `graph query <SPEC>` prints the body UNindented (YAML strips the block-scalar
# indent on parse). So an `old` composed from what the author READ can never match what is on DISK.
# These two helpers let the exact-match miss re-try at the body's own indentation before dying.

# The `body:` block-scalar header — `|`, `|-`, `>`, `|2+`, … (the indicator chars YAML allows after
# the style char). Anchored at line start: only the TOP-LEVEL `body:` key opens the spec body.
# The header may carry a TRAILING YAML COMMENT (T-10602 / X-0449): the `spec new` scaffold's own
# header does (`body: |    # fixed minimal section shape per D-0044 …`), so requiring a BARE header
# blinded this matcher to every fresh scaffold — the fallback below never fired and the governed
# `spec edit --from-file` path was unusable on a just-created spec. The comment must be space-
# separated: `body: |#x` is not a YAML comment (the `#` is glued to the indicator), so it must NOT
# match — a header this matcher cannot read must fail closed rather than guess an indent.
_BODY_BLOCK_RE = re.compile(r"^body:[ \t]*[|>][0-9+-]*(?:[ \t]+#[^\n]*)?[ \t]*$", re.MULTILINE)


def _body_block_indent(text: str) -> str | None:
    """The leading whitespace of a spec's `body:` block-scalar content, or None when there is no
    indented body block. Read off the first non-blank line after the header — that is the indent YAML
    strips on parse, so re-applying it maps parsed-body text back onto raw file text."""
    m = _BODY_BLOCK_RE.search(text)
    if m is None:
        return None
    for line in text[m.end():].split("\n")[1:]:
        if line.strip():
            indent = line[:len(line) - len(line.lstrip())]
            return indent or None
    return None


def _reindent(s: str, indent: str) -> str:
    """Prefix `indent` to every non-blank line. Blank lines stay blank — YAML block scalars carry no
    trailing indent on an empty line, so indenting them would fabricate text the file does not hold."""
    return "\n".join(indent + ln if ln.strip() else ln for ln in s.split("\n"))


# ── T-11109 — the FLOW-SCALAR sibling of the indentation trap (X-0882) ───────────────────────────
# A spec `body:` need not be a BLOCK scalar. kupiclub's SPEC-0042 stores it as a double-quoted FLOW
# scalar: one physical line whose interior newlines are carried as literal `\n` escapes. There
# `_body_block_indent` reads None, so the T-10321 fallback above could never fire and every
# body-composed `old` refused — while `yaml.safe_load(spec)["body"]` contained that very text.
#
# WHY THE NARROW FIX (the trade-off, recorded where the code lives). The reported suggestion was to
# match the PARSED body and RE-SERIALIZE, so storage style stops being load-bearing. Rejected: the
# emitter would rewrite the WHOLE scalar, normalizing every edited spec's storage style and making
# the diff the entire body instead of the edit — for a verb whose whole value is that its diff IS
# the edit. Adopted instead: encode the CANDIDATE into the file's own stored form and re-count.
# Storage style stops being load-bearing FOR THE AUTHOR (the actual complaint) and not a byte
# outside the replacement site moves.
_BODY_FLOW_RE = re.compile(r"^body:[ \t]*(['\"])", re.MULTILINE)


def _body_flow_quote(text: str) -> str | None:
    """The quote character of a spec's top-level `body:` QUOTED FLOW scalar, or None when the body
    is not stored that way (a block scalar, an unquoted plain scalar, or no body at all).

    Anchored at line start like `_BODY_BLOCK_RE`: only the TOP-LEVEL `body:` key opens the body."""
    m = _BODY_FLOW_RE.search(text)
    return m.group(1) if m else None


# The candidate encoder now lives in `lib/textutil.py` (T-11166): `task update`'s field-edit hit the
# SAME root on a WRAPPED single-quoted scalar, so the encoder was hoisted to the one shared home and
# both verbs call it. Behaviour here is unchanged BY CONSTRUCTION — this name is a thin alias to the
# moved function, not a copy (CHARTER §P1 F1: extend the analog, never fork a second matcher).
_flow_encode_variants = textutil.flow_encode_variants


# ── T-10298 / SPEC-0151 — the active-behavioral-mandate ANCHOR RULE (report-only) ────────────────
# An ACTIVE spec that tells the system to BEHAVE somehow must answer "who executes this?" with a code
# anchor, a binding-delivered human obligation, or an honest not-executed marker. The real incident:
# SPEC-0097 §5 said "execution lives in tasks T-9416/17/18"; the tasks closed; no code existed. A task
# id is PROVENANCE, never an execution carrier (SPEC-0151 §Internal 2).

# A behavioral MANDATE, detected by the RFC-2119 uppercase modal the v2 corpus uses for normative
# emphasis. This is the rule's SCOPING half: a documentary spec that merely describes a shape carries
# none of these, so it is out of scope BY CONSTRUCTION (§Internal 3) rather than by an exception list.
_MANDATE_RE = re.compile(r"\b(?:MUST NOT|MUST|SHALL|REQUIRED)\b")

# A bare artifact id is provenance, NOT a code anchor — the defect this rule exists to name. Anchored
# at both ends so a real anchor that merely CONTAINS an id (`bin/yitc-v2#_t9416_gate`) still counts.
_PROVENANCE_ID_RE = re.compile(r"^(?:T|D|E|X|SPEC)-\d+$", re.IGNORECASE)

# `code-enforced` is a marker CLAIMING code enforcement — it reaches no person at a moment of use, so
# it is not a satisfier on the human-obligation leg; it must pay the `implements:` leg instead. Every
# other binding token (`spec-new`, `commit`, `close`, `stage-entry:*`, `floor`, `before-*`) IS a
# delivery trigger: it puts the rule in front of a human before the gated action.
_NON_DELIVERING_BINDING = frozenset({"code-enforced"})

# The honest third answer: "nothing executes this; a person owns it." A DECLARATION, never a mention:
# the marker is a line-anchored `execution: not-executed|operator-owned` directive (optionally quoted /
# bolded / block-quoted, as a markdown body allows). A bare substring search is what SPEC-0151 itself
# first failed — its own body DESCRIBES the two tokens while defining satisfier (c), which silenced the
# check on the very spec that defines it. Same class the sibling SPEC-0150 chain-check names: a prose or
# log mention (`print("restore_drill")`) is not a read site. Prose about a marker is not a marker.
# The trailing `(?![\w-])` is a token boundary, not decoration: without it the match is a PREFIX, so a
# malformed `execution: not-executedness` (or `operator-owned-ish`) would silence the rule — a satisfier
# must be the exact token (audit-post finding, T-10298 pass 1).
_NOT_EXECUTED_MARKER_RE = re.compile(
    r"^\s*(?:>\s*)?\**execution\**\s*:\s*[`'\"]?(?:not-executed|operator-owned)(?![\w-])",
    re.IGNORECASE | re.MULTILINE)

_ANCHOR_RULE_STATUSES = ("active",)


def _is_code_anchor(entry) -> bool:
    """An `implements:` entry that names CODE, not an artifact id (SPEC-0151 §Internal 2)."""
    text = str(entry or "").strip()
    return bool(text) and not _PROVENANCE_ID_RE.match(text)


def anchor_rule_violation(rec, *, statuses: tuple = _ANCHOR_RULE_STATUSES):
    """SPEC-0151 §Internal 1 — pure f(spec record) → a reason string, or None when the rule holds.

    A spec in `statuses` whose `body:` carries a behavioral mandate must name AT LEAST ONE of:
      (a) an `implements:` CODE anchor (a bare task/spec id does not count — provenance != execution);
      (b) a `binding:`-delivered HUMAN obligation (a delivery trigger; `code-enforced` claims code and
          so pays leg (a) instead — it reaches nobody);
      (c) an explicit `not-executed` / `operator-owned` body marker.

    REPORT-ONLY by contract (§Internal 3): callers WARN, never refuse. Hardening to a hard gate needs
    its own incident (CHARTER §P1 F4) — a WARN that provably fails to change behaviour.

    `statuses` widens the check for the AUTHORING surfaces: the RULE governs `active` specs (what the
    conformance sweep walks), but a `proposed` head is the pre-image of an active spec, and catching a
    missing anchor at authoring is the entire point of an authoring-time warning — by the time it
    activates at `task close`, the author has moved on. Pure: no I/O, no host deps."""
    if not isinstance(rec, dict):
        return None
    if (rec.get("status") or "").strip() not in statuses:
        return None
    body = rec.get("body")
    if not isinstance(body, str) or not _MANDATE_RE.search(body):
        return None                                  # documentary / no mandate — out of scope
    if _NOT_EXECUTED_MARKER_RE.search(body):
        return None                                  # (c) an honest "nothing executes this"
    if any(_is_code_anchor(a) for a in (rec.get("implements") or [])):
        return None                                  # (a) a code anchor
    binding = [str(b).strip() for b in (rec.get("binding") or []) if str(b).strip()]
    if any(b not in _NON_DELIVERING_BINDING for b in binding):
        return None                                  # (b) a binding-delivered human obligation
    impl = [str(a).strip() for a in (rec.get("implements") or []) if str(a).strip()]
    if impl:
        detail = (f"names only provenance in `implements:` ({', '.join(impl)}) — a task/spec id records "
                  f"WHO shipped it, not WHAT executes it")
    elif binding:
        detail = (f"carries `binding: [{', '.join(binding)}]`, which claims code enforcement but names "
                  f"no `implements:` anchor")
    else:
        detail = "names no `implements:` anchor and no `binding:` delivery"
    return (f"body carries a behavioral mandate but {detail}. Name a code anchor, a binding-delivered "
            f"human obligation, or an explicit not-executed/operator-owned marker (SPEC-0151 §Internal 1)")


def _warn_anchor_rule(sid: str, rec, *, verb: str) -> None:
    """Report-only WARN for the two authoring verbs. Never refuses, never touches the exit code — the
    authoring half of SPEC-0151 §Internal 3 (its other half is the graph-conformance sweep line).

    Widened to `proposed` for the reason in `anchor_rule_violation`. On `spec new` this is near-silent
    by construction (the scaffold's template body carries no mandate) — it stands as the symmetric
    guard the spec names, and it fires the moment a template or a `--from-file` birth carries one."""
    reason = anchor_rule_violation(rec, statuses=("active", "proposed"))
    if reason:
        print(f"⚠ anchor-rule (SPEC-0151) after `{verb}`: {sid} {reason}", file=sys.stderr)


def cmd_spec_new(args: argparse.Namespace, *, _require_writing_worktree, _die, _yaml_scalar,
                 _utc_now_iso, PLANS_DIR, _require_reads, PLACEMENT_REALMS, _SPEC_CLASS_DEFAULT,
                 _kernel_content_file, _scaffold_read_validate, _id_alloc_lock, SPECS_DIR, _slug,
                 _scaffold_substitute, write_text_atomic, _append_event, REPO_ROOT,
                 _governing_contract_for, _manifest_path, _backfill_spec_placement_handrow,
                 _is_consumer_build=None) -> None:
    """Allocate the next SPEC-NNNN under flock + scaffold from specs/_template.yaml. Emits
    spec_filed + а reminder. Filename convention: specs/SPEC-NNNN-<slug>.yaml (matches the corpus)."""
    _require_writing_worktree()
    title = (args.title or "").strip()
    if not title:
        _die("--title required (non-empty)")
    subs = {"title": _yaml_scalar(title), "created_at": _utc_now_iso()}
    # T-0186 Part A — `--draft` BIRTHS a draft spec (status: draft, below proposed in the FSM,
    # SPEC-0005 §4): plan-LOCAL, non-authoritative, governs nothing. A draft is owned by a plan,
    # so `--proposed-by <plan>` is MANDATORY with `--draft` and the plan MUST EXIST (audit-pre
    # F1/F2 — no dangling plan refs). NO draft→proposed verb here: that promotion is Part B's
    # `plan accept` / task-staging (part-b-narrow §3) — this verb only creates.
    if getattr(args, "draft", False):
        plan_slug = (getattr(args, "proposed_by", None) or "").strip()
        if not plan_slug:
            _die("--draft requires --proposed-by <plan-slug> (a draft is plan-local; SPEC-0005 §4 FSM)")
        if not (PLANS_DIR / f"{plan_slug}.md").exists():
            _die(f"--proposed-by: no such plan plans/{plan_slug}.md — reject dangling plan ref (audit-pre F2)")
        # T-0599 — read-check graduation onto the plan-axis `specs` work-verb (SPEC-0050 §6 / SPEC-0059):
        # `spec new --draft` composes a plan's draft specs (the plan `specs` stage), so it REFUSES — before
        # allocating an id — unless THIS session fetched the plan `specs` stage bundle
        # (plan-stage-entry:specs = [SPEC-0034]). The NON-draft `spec new` path below is UNTOUCHED — its
        # before-rule-change->SPEC-0005 floor trigger is the RESERVED kind=action path (T-0420 territory).
        _require_reads("stage", {"axis": "plan", "stage": "specs", "verb": "spec new --draft",
                                 "action": "compose a draft spec"})
        subs["status"] = "draft"
        subs["proposed_by"] = plan_slug
    elif getattr(args, "proposed_by", None):
        _die("--proposed-by is only valid with --draft (a proposed spec is born via its activation flow)")
    # T-0888 placement write-point. The placement decision is an explicit in-flow OUTPUT of `spec new`
    # (the external-audit HIGH hardening: capture at the governed authoring path, not audit-only).
    # `--travels {kernel|v2-self|project|default}` is REQUIRED for an authoritative NON-draft (proposed)
    # birth and FAILS CLOSED when omitted; `default` consciously affirms the spec class-default (kernel).
    # A `--draft` is plan-LOCAL and governs nothing (SPEC-0005 §4) → travels is OPTIONAL there (defaults
    # to class-default; the placement is pinned when the draft is promoted to proposed). Checked AFTER the
    # draft read-gate (so a draft's read-check still fires first) but BEFORE the template read /
    # `_id_alloc_lock`, so a missing decision burns no SPEC-id (F-011). Contract: SPEC-0073.
    is_draft = bool(getattr(args, "draft", False))
    travels_arg = (getattr(args, "travels", None) or "").strip().lower()
    if travels_arg and travels_arg not in (*PLACEMENT_REALMS, "default"):
        _die(f"--travels: invalid '{travels_arg}' — choose one of kernel | v2-self | project | default")
    if not is_draft and not travels_arg:
        _die("--travels {kernel|v2-self|project|default} required — the corpus-wide placement contract "
             "(SPEC-0073) fails closed: a new proposed spec MUST carry an explicit placement decision at "
             f"authoring (`{graph_lib.spec_query_hint('SPEC-0073', is_consumer=bool(_is_consumer_build and _is_consumer_build()), cli='')}`). "
             "`default` affirms the spec class-default (kernel).")
    if is_draft:
        # A DRAFT is plan-local (SPEC-0005 §4) and governs nothing; SPEC-0073 §8 requires a non-active
        # spec to NOT resolve the kernel export realm, so a draft DEFAULTS to v2-self — the §3↔§8
        # coherence fix (T-9285): a kernel-default draft otherwise fails `graph conformance` the moment
        # it is born. EXPLICITLY map only the documented kernel-aliases (omitted / `default` / `kernel`)
        # to v2-self; an explicit `v2-self`/`project` is HONORED (an out-of-set value cannot reach here —
        # the argparse `choices` above already fail-closed it). The kernel re-pin is an EXPLICIT action
        # at plan-accept, never a `_birth_plan_draft_specs` side-effect.
        resolved_realm = "v2-self" if (not travels_arg or travels_arg in ("default", "kernel")) else travels_arg
    else:
        resolved_realm = _SPEC_CLASS_DEFAULT if (not travels_arg or travels_arg == "default") else travels_arg
    # Body marker ONLY for a NON-default exception (default/kernel → no redundant marker; unmarked =
    # class-default). The decision itself is recorded DURABLY in the spec_filed event below. A draft's
    # resolved v2-self is a non-default exception, so the marker IS written (T-9285).
    if resolved_realm != _SPEC_CLASS_DEFAULT:
        subs["travels"] = resolved_realm
    # T-0860: resolve the template with an ENGINE_ROOT fallback for a -C consumer (F-010/F-012) AND read
    # + validate it BEFORE allocating the id (F-011 no-ID-burn — see _scaffold_read_validate). The id is
    # the OUTPUT of a successful scaffold precondition, not a cost paid up front.
    template = _kernel_content_file("specs/_template.yaml")
    template_text = _scaffold_read_validate(template, ["id", *subs.keys()])
    with _id_alloc_lock(SPECS_DIR, "SPEC") as sid:
        path = SPECS_DIR / f"{sid}-{_slug(title, die=_die)}.yaml"
        if path.exists():
            _die(f"collision (post-lock): {path.name} already exists")
        content = _scaffold_substitute(template_text, template.name, {"id": sid, **subs})
        write_text_atomic(path, content)
        _append_event("spec_filed", sid, {
            "path": str(path.relative_to(REPO_ROOT)), "title": title,
            "status": subs.get("status", "proposed"),
            "travels": resolved_realm,          # T-0888 — the DURABLE placement decision for EVERY new
            "travels_explicit": bool(travels_arg),  # spec (distinguishable from a legacy unmarked spec, even
                                                # when the body marker is omitted for the default case). True
                                                # iff --travels was passed (always for a non-draft; optional draft).
            "governing_contract": _governing_contract_for("spec-new")})  # delivery-observability (T-0272/SPEC-0013)
    # T-9497 — auto-backfill the kernel-vs-self manifest §1 HAND-table row IN-FLOW (E-0029), so a new
    # spec never discovers a missing §1 row late at land (test_t0890 §B2). Idempotent + fail-safe: an
    # absent manifest / hand table / unknown realm leaves the manifest untouched (a -C consumer with no
    # such manifest is the absent-file case). The §1-derived GEN block stays graph-build-regenerated.
    manifest = _manifest_path()
    if manifest.exists():
        before = manifest.read_text(encoding="utf-8")
        after = _backfill_spec_placement_handrow(before, sid, subs.get("status", "proposed"),
                                                 resolved_realm, title)
        if after != before:
            write_text_atomic(manifest, after)
    print(f"spec filed: {path.relative_to(REPO_ROOT)} (id={sid})")
    if is_draft and resolved_realm == "v2-self" and (not travels_arg or travels_arg in ("default", "kernel")):
        # teach the workflow only when a kernel-DESTINED draft was DEFAULTED to v2-self (the common
        # case); an explicit `--travels v2-self`/`project` is the author's deliberate choice, no notice.
        print("note: draft → travels:v2-self (plan-local, governs nothing); re-pin to kernel is an "
              "EXPLICIT action at plan-accept, not a birth side-effect (SPEC-0073 §3).")
    print("next: fill implements: durable anchors — PREFER <file>#<symbol> over a bare <file> "
          "(the code-decompose rule, SPEC-0088); NOT line ranges (D-0036) + body "
          "Statement/Rationale/Verification (GRAPH §Schema for specs).")
    print(f"cue: {SPEC_BODY_EDIT_CUE}")  # T-10159 (a-d single-SoT)
    # T-10298 (SPEC-0151) — report-only anchor-rule WARN on the born record. Parsed from the text just
    # written (never re-read from disk): the scaffold IS the record. A parse failure here must never
    # break the birth of a spec whose file is already on disk, so it degrades to silence.
    try:
        _warn_anchor_rule(sid, state.load_str(content), verb="spec new")
    except Exception:
        pass


def governed_content_digest(rec: dict) -> str:
    """The GOVERNED-CONTENT digest of a parsed spec record — sha256 over `body:` + `implements:` only
    (T-11207 / X-0951). This is EXACTLY the T-9730 land guard's own trigger surface: that guard fires
    on an active spec whose `body:` OR `implements:` moved, and explicitly skips a status/metadata-only
    change. Fingerprinting the WHOLE spec-file blob (the original T-10135 basis) measured a strictly
    WIDER surface than the guard guards, so any write that touched the file WITHOUT touching either
    governed field silently invalidated a fresh bless.

    The measured burn (kupiclub task/T-0326, 2026-08-16): `spec edit --bless` at 13:30, then the
    `spec reverify` the engine's OWN anchor-drift WARN asks for — which rewrites ONLY the
    `implements_signature:` key — then land REJECTED at 14:33 naming the spec an off-path raw edit.
    Two engine recommendations, followed in the order the engine printed them, cost a full land cycle.
    The REFUSAL was correct and stays correct; what was wrong was the fingerprint's breadth.

    Both sides of the fingerprint (the bless emit + the land guard's recompute) call THIS one helper,
    so the thing signed and the thing guarded can never drift apart again. Takes the ALREADY-PARSED
    record — both call sites have one — so there is no re-parse and no unparseable-input branch."""
    import hashlib
    payload = state.dump({"body": rec.get("body"), "implements": rec.get("implements")}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cmd_spec_edit(args: argparse.Namespace, *, _require_writing_worktree, _die, _find_spec_path,
                  _read_yaml, SPEC_ABANDONED_TERMINAL, write_text_atomic, _governing_contract_for,
                  _append_event, REPO_ROOT, _run_git_cap=None,
                  _require_before_rule_change_read=None) -> None:
    """In-place chokepoint for editing an EXISTING active/proposed spec (T-0273) — the before-rule-change
    gate for MODIFYING a spec, the inverse of `spec new` (which gates CREATION). Resolves the spec by id,
    refuses superseded/retired (post-active frozen history), but ALLOWS a `draft` (plan-local, SPEC-0005
    §4 «draft governs NOTHING» — so a body/metadata edit is drift-safe, exactly parallel to the terminals
    carve-out; T-1164 closed E-0024's recurring no-verb-for-draft-spec-edit gap — the prior refusal
    pointed at a NON-existent «edit via plan flow» path, forcing journal-invisible hand-edits) AND the
    DELIBERATE never-active terminals withdrawn/rejected (SPEC_ABANDONED_TERMINAL, T-0627) so a
    deliberately-abandoned spec's NON-normative metadata (e.g. a `proposed_by` provenance re-attach) can
    be corrected via the verb instead of a forbidden hand-edit (a withdrawn/rejected spec governs nothing,
    so this is not a normative rule change — SPEC-0005 rule 7 in-place boundary). Performs
    an exact-string in-place replacement (mirrors the Edit
    primitive: single occurrence unless --replace-all; 0 or >1 matches die cleanly BEFORE any write),
    surfaces the before-rule-change contract (SPEC-0005) via the binding-derived forward-pointer, and
    emits `spec_edited` carrying the `governing_contract` DERIVED from the binding map (the delivery-
    observability projection, SPEC-0013 — so the gate's consumption is journal-visible, not transcript-
    only). V2 enforces by sanctioning + observing this path, NOT by hard-blocking raw Edit (a CHARTER
    non-goal — no hook-laden enforcement); an off-path raw edit shows up as a spec-file diff with NO
    spec_edited event, which is exactly what makes the bypass detectable (finding-3 no longer invisible)."""
    _require_writing_worktree()
    sid = (args.id or "").strip()
    if not sid:
        _die("spec id required (SPEC-NNNN)")
    path = _find_spec_path(sid)
    if path is None:
        _die(f"spec not found: {sid} (specs/{sid}-*.yaml)")
    rec = _read_yaml(path)
    status = rec.get("status")
    if status not in ("active", "proposed", "draft") and status not in SPEC_ABANDONED_TERMINAL:
        _die(f"`spec edit` is for active/proposed/draft specs (and the deliberate terminals "
             f"withdrawn/rejected, T-0627) only — {sid} is status={status!r}. "
             f"superseded/retired are frozen history (a post-active record is immutable).")
    if getattr(args, "bless", False):
        # T-10135: BLESS an ALREADY-MADE in-place edit of an ACTIVE spec. Derive its diff vs `main`
        # (the base the T-9730 land guard fingerprints against — worktree.py cmd_land passes
        # `merged_base = rev-parse main`), emit a DIFF-BOUND spec_edited, and let the guard clear THIS
        # spec ONLY when the final base..HEAD diff matches the recorded fingerprint. Without the
        # fingerprint bind, a stale bless event would clear a LATER raw edit — the loophole the auditor
        # flagged (spec-edit-ergonomics-audit-adhoc). Solves the rework: after a raw Edit, `spec edit`
        # (which re-performs the edit + rejects a no-op old==new) cannot ride the change; bless does.
        if args.old is not None or args.new is not None \
                or getattr(args, "from_file", None) or getattr(args, "from_stdin", False):
            _die("--bless blesses an ALREADY-MADE in-place edit — do NOT also pass "
                 "--old/--new/--from-file/--from-stdin")
        if status != "active":
            _die(f"--bless is for ACTIVE specs only ({sid} is status={status!r}); the T-9730 land guard "
                 f"governs only active specs (SPEC-0005 §4), so a non-active spec body edit needs no bless.")
        if _run_git_cap is None:
            _die("--bless unavailable: git runner not injected (host-wiring error)")
        # before-rule-change gate — the bless path ENFORCES the SPEC-0005 read receipt (the normal edit
        # path only prints an advisory pointer; bless is higher-risk — it clears a guard post-hoc).
        contract = _governing_contract_for("spec-edit")
        contract_specs = contract.get("specs") or []
        if _require_before_rule_change_read is not None:
            _require_before_rule_change_read("spec edit --bless", contract_specs)
        relpath = str(path.relative_to(REPO_ROOT))
        base_show = _run_git_cap(["show", f"main:{relpath}"], REPO_ROOT)
        if base_show.returncode != 0:
            _die(f"--bless cannot resolve {relpath} at `main` (the land-guard diff base) — a brand-new "
                 f"spec rides `spec new`, not bless ({base_show.stderr.strip()[:100]}).")
        base_blob, new_blob = base_show.stdout, path.read_text(encoding="utf-8")
        import hashlib
        try:
            base_rec = state.load_str(base_blob) or {}
            new_rec = state.load_str(new_blob) or {}
        except Exception as e:
            _die(f"--bless: cannot parse {relpath} at main/working ({str(e)[:120]})")
        body_moved = base_rec.get("body") != new_rec.get("body")
        impl_moved = base_rec.get("implements") != new_rec.get("implements")
        if not body_moved and not impl_moved:
            _die("--bless: neither `body:` nor `implements:` changed vs `main` — nothing to bless "
                 "(the T-9730 land guard fires only on a body/implements diff).")
        fields = [fld for fld, moved in (("body", body_moved), ("implements", impl_moved)) if moved]
        # T-11207 (X-0951): sign the GOVERNED CONTENT (`body:` + `implements:`), NOT the whole file
        # blob — the guard's trigger surface, so a write that moves neither governed field (the
        # `spec reverify` the drift WARN asks for, which rewrites only `implements_signature:`) no
        # longer invalidates this bless. A later raw edit of body/implements still moves the digest,
        # so the T-10135 stale-bless loophole stays closed. `fingerprint` derivation is unchanged.
        base_sha = governed_content_digest(base_rec)
        new_sha = governed_content_digest(new_rec)
        fingerprint = hashlib.sha256(f"{base_sha}:{new_sha}".encode("utf-8")).hexdigest()
        if contract_specs:
            print(f"→ `spec edit --bless` (before-rule-change): governed by "
                  f"{', '.join(contract_specs)} (read-receipt verified this session)")
        # Records the SAME base fields as a normal spec_edited (path/status/trigger/governing_contract/
        # binding_source — audit-pre mode-b absorption) PLUS the bless-specific diff-bound fields.
        _append_event("spec_edited", sid, {
            "path": relpath, "status": status,
            "replacements": 0, "trigger": "before-rule-change",
            "governing_contract": contract,
            "binding_source": "specs/*.yaml#binding (inverted via _build_binding_views)",
            "bless": True, "base_sha": base_sha, "new_sha": new_sha,
            "fingerprint": fingerprint, "fields": fields})
        print(f"spec blessed: {relpath} — diff-bound spec_edited emitted (fields: {', '.join(fields)}; "
              f"fingerprint {fingerprint[:12]}…).")
        print("The T-9730 land guard clears THIS spec only if the final base..HEAD diff matches this "
              "fingerprint. Commit the edit (+ this event); re-run `spec edit --bless` if you edit the "
              "spec BODY or IMPLEMENTS further before land.")
        # T-11717: the AUTHOR edit above is not the only invalidator, and it was the only one named —
        # the land's OWN update-from-main can move the diff out from under a perfectly valid bless.
        print("NOT ONLY YOUR OWN EDITS invalidate this (T-11717): the LAND'S OWN update-from-main "
              "does too — if a sibling branch lands an edit to THIS spec before you land, the merge "
              "changes the final diff and this fingerprint goes stale, without you touching "
              f"anything. {SPEC_STALE_BLESS_CUE}")
        print("Safe to run now (T-11207): `spec reverify` does NOT invalidate this bless — the "
              "fingerprint covers body+implements only, so re-signing `implements_signature:` (what "
              "the anchor-drift WARN asks for) leaves it intact. Order between the two does not matter.")
        return
    # Input resolution (T-10051): old/new may come flat via --old/--new OR — for the multi-line /
    # full-section body replacements the flat CLI cannot carry — as a YAML mapping {old, new,
    # replace_all?} from a file (--from-file) or stdin (--from-stdin), mirroring `task file
    # --from-stdin`. This lets a multi-line spec-body edit RIDE the verb (+ its spec_edited emit)
    # instead of being hand-edited into the YAML off-path (the bypass this task closes). getattr
    # keeps back-compat with callers (older tests) that pass a bare id/old/new/replace_all namespace.
    from_file = getattr(args, "from_file", None)
    from_stdin = getattr(args, "from_stdin", False)
    replace_all = getattr(args, "replace_all", False)
    if from_file or from_stdin:
        if args.old is not None or args.new is not None:
            _die("--from-file/--from-stdin carry old+new themselves — do not also pass --old/--new")
        if from_file and from_stdin:
            _die("pass --from-file OR --from-stdin, not both")
        if from_file:
            import sys as _sys  # noqa: F401 (kept symmetric; stdin path below uses it)
            from pathlib import Path as _Path
            src = _Path(from_file)
            try:
                raw = src.read_text(encoding="utf-8")
            except (FileNotFoundError, PermissionError, OSError) as e:
                _die(f"--from-file {from_file!r} unreadable: {e}")
        else:
            import sys as _sys
            raw = _sys.stdin.read()
        try:
            mapping = state.load_str(raw)
        except Exception as e:
            _die(f"input is not valid YAML ({str(e)[:160]})")
        if not isinstance(mapping, dict):
            _die("input must be a YAML mapping with `old:` and `new:` keys "
                 "(mirrors `task file --from-stdin`)")
        if "old" not in mapping or "new" not in mapping:
            _die("input mapping must carry both `old:` and `new:` keys")
        old, new = mapping["old"], mapping["new"]
        if not isinstance(old, str) or not isinstance(new, str):
            _die("`old:` and `new:` must be strings (use a YAML block scalar `|` for multi-line text)")
        m_ra = mapping.get("replace_all", False)
        if not isinstance(m_ra, bool):
            _die("`replace_all:` in the input must be a boolean (true/false)")
        # OR the two carriers — a CLI --replace-all must never be silently overridden by a mapping
        # that omits it or sets it false (audit-pre YELLOW absorption, T-10051).
        replace_all = bool(m_ra) or replace_all
    else:
        if args.old is None or args.new is None:
            _die("spec edit needs an input: either --old/--new (CLI) OR --from-file/--from-stdin "
                 "(a YAML mapping {old, new, replace_all?}, for multi-line body edits)")
        old, new = args.old, args.new
    if old == new:
        _die("old and new are identical (no-op)")
    text = path.read_text(encoding="utf-8")
    n = text.count(old)
    # T-11109 — the author's own pair, kept for the AC3 integrity check further down: the fallbacks
    # below REBIND old/new to storage-form candidates, and the round-trip must be judged against
    # what the author actually asked for, not against the candidate that happened to match.
    orig_old, orig_new = old, new
    if n == 0:
        # T-10321 (X-0284) — the indentation trap. The exact raw match above stays PRIMARY (every
        # currently-working call is byte-identical). Only on a miss: if `old` is a substring of the
        # PARSED body, the author composed it from the unindented body `graph query` prints, so
        # re-indent BOTH old and new to the block-scalar level and re-count. The `old in body` guard
        # is what keeps this honest — a genuinely absent `old` cannot be resurrected by re-indenting.
        indent = _body_block_indent(text)
        body = rec.get("body")
        if indent and isinstance(body, str) and old in body:
            cand_old, cand_new = _reindent(old, indent), _reindent(new, indent)
            cand_n = text.count(cand_old)
            if cand_n:
                print(f"note: `old` matched the parsed body, not the raw file — re-indented it (and "
                      f"`new`) by {len(indent)} space(s) to the `body:` block-scalar level (T-10321).")
                old, new, n = cand_old, cand_new, cand_n
    if n == 0:
        # T-11109 (X-0882) — the FLOW-scalar sibling of the branch above. Same shape, same honesty
        # guard: only when `old` is in the PARSED body do we look for its stored ESCAPED form, and
        # only a candidate actually present in the raw text is accepted. `old` and `new` are encoded
        # by the SAME emitter setting (paired by index), so a match can never mix encodings.
        quote = _body_flow_quote(text)
        body = rec.get("body")
        if quote and isinstance(body, str) and old in body:
            cand_olds = _flow_encode_variants(old, quote)
            cand_news = _flow_encode_variants(new, quote)
            for cand_old, cand_new in zip(cand_olds, cand_news):
                if cand_old is None or cand_new is None:
                    continue
                cand_n = text.count(cand_old)
                if cand_n:
                    print(f"note: `old` matched the parsed body, not the raw file — the `body:` is a "
                          f"quoted flow scalar, so `old` (and `new`) were encoded to its stored "
                          f"escaped form before matching (T-11109).")
                    old, new, n = cand_old, cand_new, cand_n
                    break
    if n == 0:
        # T-11109 defect (2) — the diagnostic is COMPUTED from the file in hand, not a fixed string.
        # The old wording asserted a block-scalar indentation trap unconditionally, so a flow-scalar
        # body (and a plainly absent `old`) both sent the reader to debug indentation that was never
        # the cause. A correct fix with a misleading refusal still costs the next reader a pass.
        body = rec.get("body")
        in_body = isinstance(body, str) and orig_old in body
        if not in_body:
            cause = (f"It is absent from BOTH the raw file and the parsed body of {sid} — so this is "
                     f"NOT an indentation or storage-style problem (text composed from the body is "
                     f"matched for you automatically). Re-check the text against `{path.name}` itself.")
        elif _body_block_indent(text):
            cause = (f"It IS present in the parsed body, and the `body:` is a block scalar — but "
                     f"re-indenting it to that block's own level still did not match the raw file "
                     f"(the T-10321 INDENTATION trap): the on-disk indentation is not what stripping "
                     f"the block indent implies. Compare the text against `{path.name}` directly.")
        elif _body_flow_quote(text):
            cause = (f"It IS present in the parsed body, which is stored as a QUOTED FLOW scalar — "
                     f"but no encoding of it matched the raw file's escaped form (T-11109). The "
                     f"scalar is most likely line-WRAPPED across physical lines, or escaped by an "
                     f"emitter setting this matcher does not reproduce. Compare against "
                     f"`{path.name}` directly, or narrow `old` to a single line.")
        else:
            cause = (f"It IS present in the parsed body, but the `body:` storage form in "
                     f"`{path.name}` is one this matcher cannot map onto — neither a block scalar "
                     f"nor a quoted flow scalar. Match against the raw file text instead.")
        _die(f"`old` not found in {path.name} (exact match required — like the Edit primitive). "
             f"{cause}")
    if n > 1 and not replace_all:
        _die(f"`old` matches {n} times in {path.name} — make it unique or pass --replace-all")
    count = n if replace_all else 1
    import yaml
    # T-11109 — the AC3 integrity guard for a QUOTED FLOW body: the flow analog of the T-10920
    # insert-side fix, and the nastier half of it. Inside a quoted scalar a verbatim `new` can break
    # the document (an embedded quote or backslash) OR — worse — still PARSE while meaning something
    # else: a real newline inside a quoted scalar FOLDS to a space, so the damage is SILENT, not a
    # refusal. So for a flow-stored body the RESULT is judged on the PARSED body against what the
    # AUTHOR asked for, and `new` is re-encoded to the scalar's stored form when the verbatim
    # insertion does not round-trip. Verification-driven, never a guess: a candidate is accepted only
    # if the reparsed body equals the expected body EXACTLY, so a wrong encoding cannot slip through.
    # Scoped to this storage style on purpose — block-scalar bodies keep the T-10321/T-10920
    # handling unchanged (widening that is a separate change with its own evidence).
    _flow_quote = _body_flow_quote(text)
    _pre_body = rec.get("body")
    _expected_body = None
    if _flow_quote and isinstance(_pre_body, str) and orig_old in _pre_body:
        _expected_body = (_pre_body.replace(orig_old, orig_new) if replace_all
                          else _pre_body.replace(orig_old, orig_new, 1))
    _FLOW_REENCODE_NOTE = (
        "note: `new` was encoded to the `body:` flow scalar's stored escaped form — inserting it "
        "verbatim would have changed the parsed body (a newline inside a quoted scalar folds to a "
        "space; a quote or backslash re-escapes) (T-11109).")

    def _flow_reencode_retry():
        """Retry the replacement with `new` encoded into the flow scalar's stored form. Returns
        `(updated_text, record)` only when the retry round-trips to the expected body, else None."""
        if _expected_body is None:
            return None
        for cand_new in _flow_encode_variants(new, _flow_quote):
            if cand_new is None:
                continue
            cand = (text.replace(old, cand_new) if replace_all
                    else text.replace(old, cand_new, 1))
            try:
                cand_rec = state.load_str(cand)
            except yaml.YAMLError:
                continue
            if isinstance(cand_rec, dict) and cand_rec.get("body") == _expected_body:
                return cand, cand_rec
        return None

    updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    # Failure-behaviour guard (audit-post F1): a spec file IS YAML — validate the RESULT parses before
    # writing, so a replacement that corrupts the document (or mangles a frontmatter field) clean-fails
    # with the file untouched, rather than landing a broken spec the graph would then choke on.
    try:
        updated_rec = state.load_str(updated)
    except yaml.YAMLError as e:
        # T-10920 (X-0727) — the INSERT-side half of the indentation trap. The T-10321 fallback above
        # normalizes BOTH halves, but only when `old` MISSES the raw text. When a dedented one-line
        # `old` RAW-matches mid-line inside an indented body line, that fallback never fires: `old` is
        # matched at column N while a multi-line `new` written at the same (dedented) altitude has its
        # CONTINUATION lines inserted at column 0 — they terminate the block scalar and the parse above
        # fails. The author's pair is correct; only the insertion column is not. So re-indent `new`'s
        # continuation lines to the match site's own indent and retry ONCE.
        #   Symmetry, made safe by WHERE it sits: this runs only in the branch that is already about to
        # die, and is accepted only if the retry PARSES. An author whose `new` is already correctly
        # indented never reaches here (their first attempt parsed), so nobody gets double-indented —
        # an unconditional re-indent would silently corrupt exactly that case, strictly worse than the
        # loud refusal it replaced. A genuinely invalid pair fails both attempts and still dies below.
        retried = None
        if count == 1 and "\n" in new:
            # `old` is the string actually counted in `text` (possibly the re-indented candidate), so
            # index() resolves the site that was replaced.
            start = text.index(old)
            line_start = text.rfind("\n", 0, start) + 1
            prefix = text[line_start:start]
            # The match must begin AFTER indentation only: a `new` continuation line inherits the
            # LINE's indent, which is meaningful only when the whole prefix is that indent. A match
            # that starts at column 0, or mid-content, is not the reported shape.
            if prefix and not prefix.strip():
                # First line stays where the match put it; only continuations gain the indent.
                cand_new = _reindent(new, prefix)[len(prefix):]
                cand_updated = text.replace(old, cand_new, 1)
                try:
                    retried = (cand_updated, state.load_str(cand_updated))
                except yaml.YAMLError:
                    retried = None
        if retried is None:
            # T-11109 — the flow-scalar sibling of the retry above: a `new` carrying the scalar's own
            # quote (or a backslash) terminates it, and the T-10920 re-indent cannot help because the
            # match site's prefix inside `body: "…"` is not pure indentation.
            flow_retried = _flow_reencode_retry()
            if flow_retried is None:
                _die(f"refusing to write — the replacement makes {path.name} invalid YAML "
                     f"({str(e)[:160]}). Narrow --old to the intended text (the file is untouched).")
            updated, updated_rec = flow_retried
            print(_FLOW_REENCODE_NOTE)
        else:
            updated, updated_rec = retried
            print(f"note: `new` was inserted at a matched line indented by {len(prefix)} space(s), so "
                  f"its continuation lines were re-indented to match — inserting them verbatim would "
                  f"have broken the `body:` block scalar (T-10920). Write both halves at the file's "
                  f"own body indent to skip this.")
    # T-11109 — the SILENT half: the result parsed, but for a flow-stored body "it parsed" is not
    # "it means the same". Judge the reparsed body against the author's intent and re-encode `new`
    # when it does not match; refuse if no encoding reproduces it, rather than writing a body that
    # quietly folded a newline into a space.
    if _expected_body is not None and isinstance(updated_rec, dict) \
            and updated_rec.get("body") != _expected_body:
        flow_retried = _flow_reencode_retry()
        if flow_retried is None:
            _die(f"refusing to write — inside `{path.name}`'s quoted flow `body:` scalar this "
                 f"replacement does not round-trip: the reparsed body would NOT equal the body you "
                 f"asked for (a newline inside a quoted scalar folds to a space; a quote or "
                 f"backslash re-escapes), and no encoding of `new` reproduced it (T-11109). The "
                 f"file is untouched.")
        updated, updated_rec = flow_retried
        print(_FLOW_REENCODE_NOTE)
    write_text_atomic(path, updated)
    # T-10298 (SPEC-0151) — report-only anchor-rule WARN on the POST-edit record (reusing the record the
    # write-guard above already parsed). Reads the updated record's OWN status, not the pre-edit `status`
    # captured from disk: an edit may itself change it. Report-only — the edit has already succeeded.
    _warn_anchor_rule(sid, updated_rec, verb="spec edit")
    # governing_contract carries the SINGLE documented shape `{specs, status}` (SPEC-0025 / T-9254 —
    # `_governing_contract_for`), NOT a bare list, so EVERY floor-gated emitter is uniform. The printed
    # forward-pointer reads the `specs` list off that dict (the same auditable binding derivation — not
    # graph/index.json, which audit-post excludes — T-0219; the audit-post finding objected to both).
    contract = _governing_contract_for("spec-edit")
    contract_specs = contract.get("specs") or []
    if contract_specs:
        print(f"→ before `spec edit` (before-rule-change): read the governing rule(s) "
              f"{', '.join(contract_specs)} (`yitc-v2 graph query <SPEC>`; always-loaded map: "
              f"graph/floor-trigger-map.md)")
    else:
        print("→ before `spec edit` (before-rule-change): read the before-rule-change rule — see the "
              "always-loaded floor trigger-map (graph/floor-trigger-map.md); no active spec bound yet")
    _append_event("spec_edited", sid, {
        "path": str(path.relative_to(REPO_ROOT)), "status": status,
        "replacements": count, "trigger": "before-rule-change",
        "governing_contract": contract,
        "binding_source": "specs/*.yaml#binding (inverted via _build_binding_views)"})
    print(f"spec edited: {path.relative_to(REPO_ROOT)} ({count} replacement"
          f"{'s' if count != 1 else ''}) — before-rule-change governing contract: "
          f"{', '.join(contract_specs) or '(none active-bound yet — run graph build)'}")
    print("next: `yitc-v2 graph build` to refresh rules/binding views if the body changed governing text.")
    print(f"cue: {SPEC_BODY_EDIT_CUE}")  # T-10159 (a-d single-SoT)
    # T-10727 — fire the re-pin companion cue ONLY when this edit actually CHANGED `travels:`. Both
    # records are already in hand (`rec` pre-edit from disk, `updated_rec` from the write-guard parse),
    # so the detection costs no extra read/parse and cannot fail the edit — it runs after the atomic
    # write, on the success path. Any realm change fires it: a DRAFT row desyncs exactly like an
    # active one. Report-only (SPEC-0073 §3 stays the rule's home; this only points at it).
    if (rec or {}).get("travels") != (updated_rec or {}).get("travels"):
        print(f"cue: {SPEC_TRAVELS_REPIN_CUE} "
              f"({(rec or {}).get('travels')!r} → {(updated_rec or {}).get('travels')!r})")


def cmd_spec_reverify(args: argparse.Namespace, *, _require_writing_worktree, _die,
                      _reverify_spec_signature, _append_event, REPO_ROOT,
                      _merge_base_with_main) -> None:
    """T-0506 (E-0019 kind-B): record the DURABLE freshness baseline — the content signature each
    `implements:` anchor was last VERIFIED-ACCURATE against. The author re-reads the spec against its
    anchored code, confirms the body still holds, and runs this to BLESS the current content; the
    freshness detector (`_anchor_drift_warning`) then fires `possibly-stale` only when an anchor's
    content later DIFFERS from this blessed signature — not from the non-durable git last-touch (the
    E-0019 recurrence root, where any commit touching the spec moved the baseline).

    SEPARATE from `spec edit` BY NECESSITY: re-verification frequently confirms accuracy with NO text
    change, and `spec edit` rejects a no-op (--old==--new) — so the bless cannot ride that verb. This
    writes `implements_signature: {<anchor>: <sha256>}` (one key per live anchor; symbol anchors hash
    `_symbol_region`, file anchors hash the whole file), then emits spec_reverified. Active/proposed
    specs only (a non-normative spec governs nothing). Anchors whose file/symbol cannot be signed
    (absent/unreadable) are reported and LEFT OUT of the map (they keep the legacy last-touch path) —
    the deliberate durable successor that retires the point-in-time re-touch ritual for symbol anchors
    (E-0019 prevention filter-3 removal).

    SCOPING (T-10324). A bare `reverify` re-signs the WHOLE spec, which silently re-baselined anchors
    the caller's diff never touched (T-10300, T-10318). So: `--anchor <a>` (repeatable) re-signs ONLY
    the named anchors, leaving every other baseline byte-identical; and by default (a bare, unscoped
    reverify) the signer is armed with this branch's merge-base, so it REFUSES to re-sign an
    already-drifted anchor whose content this branch never moved.

    UNTOUCHED-ANCHOR GUARD SCOPE (T-10374, fu_dc5550c88d16). The guard exists to stop a SILENT
    whole-spec re-baseline — so it arms ONLY for a bare (unscoped) reverify. Naming `--anchor <a>` is
    the OPPOSITE of silent: an explicit anchor set IS the human/AI assertion that you re-read the spec
    against exactly those anchors, so the guard is DISARMED for a scoped call (unnamed anchors still keep
    their baseline byte-identical via the signer's merge, so scoping loses no protection). This is what
    makes the escape the refusal recommends actually reachable — before this, a `--anchor` re-sign of a
    drifted-untouched anchor re-triggered the very refusal that named it, leaving a verification-only
    task (whose diff touches no code) no non-blanket way to bless an accuracy-verified drifted anchor.
    `--include-untouched` remains the explicit opt-in that keeps the whole-spec re-sign available for the
    author who really did re-read the spec against ALL of its anchored code; it stays mutually exclusive
    with `--anchor` (whole-spec vs scoped — pick one)."""
    _require_writing_worktree()
    sid = (args.id or "").strip()
    if not sid:
        _die("spec id required (SPEC-NNNN)")
    only_anchors = {a.strip() for a in (getattr(args, "anchor", None) or []) if a.strip()} or None
    if getattr(args, "include_untouched", False) and only_anchors:
        _die("`--anchor` and `--include-untouched` are contradictory: --anchor SCOPES the re-sign "
             "to what you verified, --include-untouched re-signs the whole spec. Pick one.")
    if getattr(args, "include_untouched", False) or only_anchors is not None:
        # Guard DISARMED. --include-untouched: the explicit whole-spec opt-in. --anchor (T-10374): the
        # named scope IS the verification assertion for exactly those anchors, so the anti-silent-
        # re-baseline guard does not apply — see the UNTOUCHED-ANCHOR GUARD SCOPE docstring above.
        base_rev = None
    else:
        base_rev = _merge_base_with_main()
        if base_rev is None:
            # Fail-closed, mirroring `_zero_ship_diff_extra_paths`'s convention: with no merge-base the
            # guard cannot PROVE an anchor was untouched, and running unguarded is the very defect this
            # flag-set exists to prevent.
            _die("cannot resolve this branch's merge-base with `main` (git failed, or no common base), "
                 "so `spec reverify` cannot tell which anchors your change actually moved.\n"
                 "  Re-run once the branch has a merge-base with `main`, or — having re-read the "
                 f"spec against its anchored code — re-sign explicitly: yitc-v2 spec reverify {sid} "
                 "--include-untouched")
    path, status, signed, unsignable, changed = _reverify_spec_signature(
        sid, only_anchors=only_anchors, base_rev=base_rev)
    _append_event("spec_reverified", sid, {
        "path": str(path.relative_to(REPO_ROOT)), "status": status,
        "signed": signed, "unsignable": unsignable, "changed": changed,
        "scoped_to": sorted(only_anchors) if only_anchors else None,
        "include_untouched": bool(getattr(args, "include_untouched", False))})
    scope = f" (scoped to {len(signed)} named anchor(s); others left unchanged)" if only_anchors else ""
    # T-11762 (X-1169) — report what was COMPUTED, not the guarantee it stands for (SPEC-0165). The
    # old single line printed "N anchor(s) signed (durable freshness baseline recorded)" for BOTH a
    # real re-sign and a run that wrote nothing, so a caller read a no-op as evidence it had cured a
    # drift it never touched. The two outcomes must not read the same.
    if changed:
        print(f"spec reverified: {path.relative_to(REPO_ROOT)} — {len(changed)} of {len(signed)} "
              f"anchor(s) re-signed (baseline updated); {len(signed) - len(changed)} already "
              f"current{scope}.")
    else:
        # "no signature changed" — NOT "nothing written": the signer rewrites the file
        # unconditionally (byte-identically here), so a nothing-written claim would be a
        # guarantee this line never computed (the SPEC-0165 error this card exists to fix).
        print(f"spec reverified: {path.relative_to(REPO_ROOT)} — 0 of {len(signed)} anchor(s) "
              f"re-signed; all {len(signed)} already current, no signature changed{scope}.")
    if unsignable:
        print(f"  ⚠ {len(unsignable)} anchor(s) un-signable (absent/unreadable), left on the legacy "
              f"last-touch path: {', '.join(unsignable)}")
    print("next: the freshness detector now fires only when a signed anchor's content DIFFERS from "
          "this baseline — re-run `yitc-v2 spec reverify` after a future legitimate re-verification.")
