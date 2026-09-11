"""Grant-state READER — validation, read-only reporting, and REACH (SPEC-0169; T-10759, T-10762).

WHAT THIS IS. The kernel-owned half of the collaborator grant contract: the governed system VALIDATES
and REPORTS grant state, and — by construction — CANNOT write it. SPEC-0169 rule 5 puts grant WRITES
with the owner (separation of duties: the component whose behaviour is gated by grants must not be
able to widen them), and rule 6 keeps the obligation that removing the write does not remove: schema
and semantic validation plus read-only inspection must exist IN OUR OWN CODE, or the contract is a
document telling the owner to edit a file correctly.

SECOND HALF — THE PROVENANCE BOUNDARY (SPEC-0169 rules 3 + 4, T-10760). Rule 3 is the contract's
load-bearing clause: for a gated operation the acting identity is derived EXCLUSIVELY from the
server-issued session / OS identity, and a caller-supplied actor argument or environment fallback is
REFUSED — not merely overridden, not merely logged. While ANY caller-assertable source remains an
accepted authority, the authenticated path is decoration and the authorization check runs over an
unverified name. Rule 4 pairs with it: a missing, unmapped or unissued identity is a REFUSAL, never
an open door. See `acting_identity` (identity) + `bind_identity_to_grants` (the grant-set leg).

THIRD HALF — REACH (rule 8, T-10762). "Reach" is how much a grant list can actually CLAIM against a
given actor, and it is a fact about the HOST, not about this code: a grant can only refuse an actor
who cannot ASSUME another identity. So this module MEASURES each actor's escalation capability
read-only, CLASSIFIES the reach from that measurement (`enforcement` / `advisory-audit`), COMPARES it
against what the carrier DECLARES, and REPORTS any disagreement. Where declaration and fact disagree,
THE FACT WINS and the disagreement is itself the report's subject. Deriving reach from a registry
LABEL (a `role`, a `restrictions:` entry) is exactly the false claim rule 8 names — the label states
INTENT, the host states FACT — so no reach path in this module ever reads those keys.

FOURTH HALF — THE AUTHORIZATION DECISION (rules 1 + 2 + 4 + 7, T-10761). The allow/deny verdict the
three halves above deliberately withheld. A request is PERMITTED iff the validated grant set names
THIS person on THIS project holding THIS right — the explicit triple of rule 1 — and is REFUSED
otherwise. Rule 2's rights are decided SEPARATELY, each by its own membership: holding `deploy-code`
decides nothing about
`apply-prod-data`, and holding `decide-authority` decides nothing about either. Rule 1 makes
"the owner only" NOT EXPRESSIBLE, so no path here reads a `role`, an
owner flag, or any other label — a named non-owner with a grant is permitted, and an owner without
one is refused. Rule 7 falls out of the same shape: removing a name flips the same request from
permitted to refused, which is what makes a revocation PROVABLE rather than merely performed. See
`decide_authorization` (the pure decision) + `authorize` (the composed gate).

A grant's PROJECT leg may be written as one NAMED project or as the DECLARED SCOPE CLASS
`SCOPE_ALL_REGISTRY_PROJECTS` (T-10793) — "all projects present in the registry at authorization read
time", whose membership `resolve_scope_class` computes on EVERY read and never at write. The class
widens WHICH PROJECTS a known grant covers; it never widens WHO is admitted (rules 3-4 above are
untouched) and never reaches past the registry universe. See the constant for the distinction the
whole design rests on, and `_row_covers_project` for the single place it is honoured.

SIXTH HALF — THE POLICY SWITCH (T-10765). The five halves above are a mechanism nothing calls: a
gated operation derived an identity and then stopped, never asking whether that identity HOLDS the
right. This section is the moment the contract becomes NORMATIVE — and it is deliberately gated on
its OWN evidence path, because activating a policy before the thing that can observe it exists is
how a rule degrades into a claim. `policy_enabled` REFUSES to report enabled while any capability
the five halves ship is absent; `enforce_gated_operation` is the composed switch a host gated verb
calls, and it composes only landed pieces (`exercise_right` = authorize + the rule-9 record).

WHAT THIS IS NOT (owned by sibling cards of the same plan — do not grow this module into them):
any grant WRITE, ever (rule 5 — `refuse_carrier_write` is the single named write path and
it always refuses). The reach half likewise REPORTS and never enforces: it writes no carrier, narrows
nobody's privileges, and does not "fix" a registry — a mismatch is a finding for the owner, not an
action taken here (rule 5). Nothing in the authorization half consumes reach: a refusal's REACH (rule
8 — whether it genuinely refuses an escalation-capable actor) is a separate report, and conflating
the two would let a measured reach silently widen or narrow a decision.

THE CARRIER IS AN INSTALLATION PARAMETER (rule 10), never hard-coded here: the caller passes the
path. The host default is the already-existing `REPO_ROOT`-independent `REGISTRY_PATH`
(`$YITC_REGISTRY` else the server registry) — reusing that knob rather than inventing a second
config mechanism (CHARTER §P1 filter 1). Pointing it at a fixture changes what is validated with no
code edit.

FAIL-CLOSED IS THE READER'S JOB, NOT THE PARSER'S (`lessons/fail-closed-belongs-to-the-reader-not-
the-parser.md`). `read_grant_state` reports what the carrier LITERALLY says and judges nothing —
an absent `rights:` key means "this person declares no grant", which is NOT a malformation and is
NOT reported as a problem here. The AUTHORIZATION reader (T-10761) is the caller that must treat
that same absence as a REFUSAL per rule 4. One parse, two correctly-different absence judgements.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine): stdlib +
yaml only, no back-import of the host, no REPO_ROOT / env / identity coupling. The host keeps the
thin argparse residue `cmd_grants_report` and injects its collaborators.
"""
from __future__ import annotations

import json
import os
import pwd
import re
import shlex
from pathlib import Path

import yaml
from lib import journal as journal_mod  # T-11444: the SPEC-0190 segment-aware journal folds

# SPEC-0169 rule 2 — the CLOSED set of separately-grantable rights. They are separate because their
# blast radius differs; an implementation that collapses them into one privilege violates the rule
# even if every individual grant happens to be correct today. ADDING A FIFTH IS A SPEC CHANGE, not
# an edit here — that is why this is a closed constant and not an open string space.
#
# The FOURTH member arrived through exactly that path (T-11683, owner directive 2026-08-27): rule 2
# was amended in place first, and this line follows it. `decide-authority` carries the authority to
# DECIDE a cause otherwise reserved to the owner, on the project the grant names — and NO execution
# capability. That separation is not a convention here: it is a property of the two literals below.
# `GATED_OPERATIONS` maps verbs to rights by literal and `EXERCISABLE_HERE` names one right by
# literal, so a member added to THIS tuple gates no verb and makes nothing exercisable by itself.
RIGHTS = ("deploy-code", "apply-prod-data", "dry-run-readonly", "decide-authority")

# The carrier key a person's grants live under (SPEC-0169 rule 1 — the grant is the triple
# person × project × rights, so the value is a mapping project -> [rights], never a flat list).
RIGHTS_KEY = "rights"

# ─────────────────────────────────────────────────────────────────────────────────────────────────
# SPEC-0169 rule 1 — THE ALL-REGISTRY-PROJECTS SCOPE CLASS (T-10793). The reserved key a rights row
# may be written under INSTEAD OF a project name.
# ─────────────────────────────────────────────────────────────────────────────────────────────────
#
# WHAT IT IS, AND THE ONE DISTINCTION THE WHOLE THING RESTS ON. This token DECLARES A SCOPE CLASS —
# "all projects present in the registry at authorization read time" — and its MEMBERSHIP is RESOLVED
# at read time, every read. It is NOT sugar that expands into a project list when the grant is
# written. What is DECLARED is the RULE; the list is merely its resolution, which is exactly what
# keeps this inside rule 8's declared-never-implied (external FULL consult, verdict GREEN —
# `decisions/grants-all-projects-carrier-audit-adhoc.yaml`). An implementation that expanded on write
# would look correct on the headline behaviour today and rot back into the decay this removes the
# moment a project is registered: an enumeration written to MEAN all silently STOPS meaning all at
# the 26th project, nothing flags it, and the only symptom is a person refused on a project the owner
# believes they hold.
#
# THE OWNER-AUTHORIZED MEANING (recorded 2026-08-08, load-bearing): "all projects" means ALL PROJECTS
# IN THE REGISTRY, INCLUDING PROJECTS REGISTERED LATER. That is a value/authority decision, not a
# technical one, and the consult made settling it a precondition of implementing — so it is recorded
# in SPEC-0169 rule 1 where the rule lives, not only here.
#
# WHAT IT DOES NOT DO. It widens WHICH PROJECTS a KNOWN grant covers. It never widens WHO is
# admitted: rules 3-4 are untouched, a missing/unmapped/unissued identity is still a refusal, and a
# person holding no grant row holds nothing. Nor does it widen past the registry — a project absent
# from the universe is NOT covered, so the resolution is BOUNDED by the registry rather than open.
SCOPE_ALL_REGISTRY_PROJECTS = "all-registry-projects"

# Problem kinds `validate_grant_state` can report. Named constants so a caller (and a test) can
# assert on a stable token instead of matching prose.
P_CARRIER_UNREADABLE = "carrier-unreadable"
P_CARRIER_MALFORMED = "carrier-malformed"
P_PERSON_NOT_A_MAPPING = "person-not-a-mapping"
P_RIGHTS_NOT_A_MAPPING = "rights-not-a-mapping"
P_RIGHTS_NOT_A_LIST = "rights-not-a-list"
P_RIGHTS_EMPTY = "rights-empty"
P_RIGHT_UNKNOWN = "unknown-right"
P_RIGHT_DUPLICATED = "duplicate-right"
P_PROJECT_UNKNOWN = "unknown-project"
P_PROJECT_NOT_SCOPED = "project-not-scoped"
# The two scope-class problems (T-10793). BOTH emit NO grant row — the widening needs POSITIVE
# evidence on every axis, never an absence of objections (`lessons/carving-an-exception-into-a-
# fail-closed-gate.md` §1: the discriminator is the whole risk).
P_SCOPE_CLASS_SHADOWED = "scope-class-shadowed-by-project"    # a REAL project bears the reserved name
P_SCOPE_CLASS_NOT_SCOPED_ALL = "scope-class-without-all-scope"  # `projects:` contradicts the class

# ─────────────────────────────────────────────────────────────────────────────────────────────────
# SPEC-0169 rule 8 — REACH (T-10762). Reach is DECLARED, never IMPLIED; and where the declaration
# and the measured host fact disagree, THE FACT WINS and the disagreement is reportable.
# ─────────────────────────────────────────────────────────────────────────────────────────────────

# The carrier key a person's reach is DECLARED under. Present-or-absent is the whole test: nothing
# else in a carrier row (role, restrictions, methodology) is a reach declaration, however suggestive.
REACH_KEY = "reach"

# The two reaches rule 8 defines, verbatim in meaning:
REACH_ENFORCEMENT = "enforcement"        # the actor cannot escalate — a refusal genuinely refuses
REACH_ADVISORY_AUDIT = "advisory-audit"  # the actor CAN escalate — intent + accident-prevention only
REACH_UNKNOWN = "unknown"                # the actor could not be measured — NOT a reach, an absence
REACHES = (REACH_ENFORCEMENT, REACH_ADVISORY_AUDIT)

# Groups that ARE a measured escalation path on a Linux host — membership means this actor can assume
# another identity, so every refusal aimed at them is bypassable BY THEM. Each entry says why.
#
# This is a CLOSED, conservative set: a group listed here is one whose escalation is a property of
# the software itself, not of a site's file permissions. Anything NOT listed is reported as
# UNMEASURED rather than silently classified — see `UNMEASURED_GROUP_NOTE`.
ESCALATION_GROUPS = {
    "root": "the superuser's own group",
    "sudo": "may run commands as any user (Debian/Ubuntu sudoers default)",
    "wheel": "may run commands as any user (RHEL/BSD sudoers default)",
    "admin": "legacy sudoers group on Debian-derived hosts",
    "docker": "may start a container mounting the host filesystem as root — equivalent to root",
    "lxd": "may start a privileged container — equivalent to root",
    "podman": "container control comparable to the docker group where configured rootful",
}

UNMEASURED_GROUP_NOTE = (
    "group membership was read, but this group's INDIRECT escalation implication (whether it grants "
    "write access to a path another identity executes) is NOT measurable by group interrogation "
    "alone and was NOT measured; rule 8 forbids asserting it either way without measuring"
)

# Comparison outcomes between what the carrier DECLARES and what the host MEASURES.
R_MATCH = "match"                              # declared, and the declaration is true
R_MISMATCH = "mismatch"                        # declared, and the host says otherwise — fact wins
R_UNDECLARED = "undeclared-inference"          # the carrier declares no reach; ours is an INFERENCE
R_UNDETERMINABLE = "undeterminable"            # the actor could not be measured — no claim is made
R_DECLARED_UNKNOWN_VALUE = "declared-unknown-value"  # a `reach:` outside the closed set of rule 8

# ── INTENT-vs-FACT tension (rule 8: "the label states INTENT, the host states FACT ... where the two
# disagree the fact wins, and the disagreement is itself reportable"). ────────────────────────────
#
# These carrier keys express a RESTRICTIVE INTENT about a person. They are emphatically NOT a reach
# declaration and are never promoted into one — reading them as a reach is the exact false claim rule
# 8 forbids, and no classification path in this module touches them. They are read HERE, in a
# separate observation channel, for the one thing rule 8 does ask for: when the carrier's intent says
# "restricted" and the host measures an escalation path, that disagreement must be VISIBLE rather
# than left for a reader to notice. The tension is reported; it decides nothing.
INTENT_RESTRICTION_KEYS = ("restrictions", "methodology", "allowed_commands")

# Values under those keys that read as a restrictive intent. Substring match, deliberately loose:
# this channel only ever RAISES A QUESTION, so a false positive costs a sentence and a false negative
# hides the thing the channel exists for.
INTENT_RESTRICTIVE_MARKERS = ("readonly", "read-only", "restricted", "scope_limited", "scope-limited")

# How a reported reach came to be. Rendered on EVERY row, because rule 8's whole subject is the
# difference between a carrier STATEMENT and a reader's INFERENCE.
SOURCE_DECLARED = "declared by carrier"
SOURCE_INFERRED = "INFERRED by measurement (carrier declares no reach)"

# The interpretation note rule 8 attaches to itself, carried onto the report so no reader can take a
# mismatch finding as either an enforcement action or as weakening the fail-closed defaults.
REACH_INTERPRETATION_NOTE = (
    "This report REPORTS; it enforces nothing, writes no carrier and narrows nobody's privileges "
    "(rule 5 — grant writes are an OWNER action). Rule 8 bounds only what a reach may CLAIM: the "
    "fail-closed defaults of rules 3-4 keep their FULL value under BOTH reaches — they stop the "
    "accident, the wrong flag and the unmapped identity, which is the larger part of the real risk "
    "surface. What they do not stop is a determined escalation-capable actor, so no surface may "
    "present them as though they did."
)


class ReachUnmeasurable(RuntimeError):
    """The host could not be interrogated for an actor at all (no passwd/group database)."""


def _stdlib_resolve_groups(actor: str):
    """Default read-only group resolution: stdlib `pwd` + `grp` only (reads /etc/passwd, /etc/group).

    Deliberately NOT a subprocess and NOT a login: acceptance criterion 3 requires the measurement to
    start ZERO processes as any other user and to touch ZERO paths under any other home. Shelling out
    to `id -nG`, running `sudo -l`, or reading `~<actor>/…` would each break that — and `sudo -l` for
    another user additionally requires being root, i.e. it would need the very escalation it measures.

    Returns a sorted list of group names (primary group included), or raises `KeyError` when the
    actor is unknown to the host — an unknown actor is an ABSENCE of fact, never a reach.
    """
    import grp
    import pwd

    record = pwd.getpwnam(actor)  # raises KeyError when the host does not know this actor
    names = {grp.getgrgid(record.pw_gid).gr_name}
    names.update(g.gr_name for g in grp.getgrall() if actor in g.gr_mem)
    return sorted(names)


def measure_escalation_capability(actor: str, *, resolve_groups=None) -> dict:
    """MEASURE, read-only, whether `actor` can assume another identity on THIS host (rule 8).

    The measurement is group membership, because that is the escalation surface the host states as a
    FACT. `resolve_groups` is injectable purely so a test can measure a fixture host instead of this
    one; the default is `_stdlib_resolve_groups` — no subprocess, no other home, no login.

    Returns `{actor, resolved, groups, escalation_paths, unmeasured_groups, error}`:
      resolved          — False when the host does not know the actor. Then NOTHING is claimed.
      escalation_paths  — `[{group, why}]` for each measured escalation group held.
      unmeasured_groups — groups held that are neither in `ESCALATION_GROUPS` nor the actor's own
                          eponymous group. These are reported, NOT resolved: a shared group may or
                          may not be an indirect escalation path depending on what it can write, and
                          rule 8 forbids asserting either way without measuring it.
    """
    result = {
        "actor": actor,
        "resolved": False,
        "groups": [],
        "escalation_paths": [],
        "unmeasured_groups": [],
        "error": None,
    }
    resolver = resolve_groups or _stdlib_resolve_groups
    try:
        groups = sorted(str(g) for g in resolver(actor))
    except KeyError:
        result["error"] = f"host does not know actor {actor!r} — no group membership to measure"
        return result
    except Exception as exc:  # noqa: BLE001 — any host-interrogation failure is an absence of fact
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["resolved"] = True
    result["groups"] = groups
    for group in groups:
        if group in ESCALATION_GROUPS:
            result["escalation_paths"].append({"group": group, "why": ESCALATION_GROUPS[group]})
        elif group != actor:
            result["unmeasured_groups"].append(group)
    return result


def classify_reach(measurement: dict) -> dict:
    """Classify a measurement into the rule-8 reach. PER-ACTOR, from the FACT — never from a label.

    Returns `{reach, basis, certain, uncertainty}`.

    `advisory-audit` iff at least one escalation path was MEASURED; otherwise `enforcement`. An
    UNRESOLVED actor is `unknown` — a reach we decline to invent, not a default.

    `certain` is False whenever an unmeasured group was held — UNCONDITIONALLY, including for an
    actor already measured escalation-capable. It reports completeness of the MEASUREMENT, not
    confidence in the reach value: something about this actor was not measured, and that stays true
    however the reach came out. (An earlier pass reasoned that an unmeasured group could only ADD an
    escalation route to one already found, so the value was safe — true, but it answers a different
    question and made `certain` mean two things depending on the row. Audit-post finding, absorbed.)
    This is the honest half of the same discipline that makes a label-derived reach a false claim —
    the measurement bounds the claim, so where the measurement stops, so does the claim.
    """
    if not measurement.get("resolved"):
        return {
            "reach": REACH_UNKNOWN,
            "basis": measurement.get("error") or "actor could not be measured on this host",
            "certain": False,
            "uncertainty": ["the actor is unknown to the host, so NO reach is claimed for them"],
            "escalation_paths_present": False,
        }

    paths = measurement.get("escalation_paths") or []
    unmeasured = measurement.get("unmeasured_groups") or []
    if paths:
        reach = REACH_ADVISORY_AUDIT
        basis = ("measured escalation capability: " +
                 "; ".join(f"group {p['group']} — {p['why']}" for p in paths))
    else:
        reach = REACH_ENFORCEMENT
        basis = ("no escalation path measured: holds none of the escalation groups " +
                 f"{sorted(ESCALATION_GROUPS)}")

    uncertainty = [f"group {g}: {UNMEASURED_GROUP_NOTE}" for g in unmeasured]
    return {
        "reach": reach,
        "basis": basis,
        "certain": not unmeasured,
        "uncertainty": uncertainty,
        # Consumed ONLY by `intent_fact_tension` — a measured fact, never a reach in itself.
        "escalation_paths_present": bool(paths),
    }


def compare_reach(declared, classification: dict) -> str:
    """Compare the carrier's DECLARED reach against the classified measurement. The FACT wins.

    `declared` is the literal `reach_raw`, or `None` when the carrier declares none (which is not a
    malformation — rule 5 makes the carrier owner-written, and today's live carrier declares no reach
    at all). Returns one of `R_MATCH` / `R_MISMATCH` / `R_UNDECLARED` / `R_UNDETERMINABLE` /
    `R_DECLARED_UNKNOWN_VALUE`.

    Note the ordering: an UNDETERMINABLE measurement never produces a mismatch. Reporting a
    declaration "wrong" on the strength of a measurement that failed would be the same false-claim
    error in the opposite direction.
    """
    if classification.get("reach") == REACH_UNKNOWN:
        return R_UNDETERMINABLE
    if declared is None:
        return R_UNDECLARED
    value = str(declared)
    if value not in REACHES:
        return R_DECLARED_UNKNOWN_VALUE
    return R_MATCH if value == classification["reach"] else R_MISMATCH


class CarrierWriteRefused(RuntimeError):
    """Raised by `refuse_carrier_write` — the governed system may not write grant state (rule 5)."""


def refuse_carrier_write(carrier, *, intent: str = "") -> None:
    """The governed system's SINGLE named carrier-write path — and it ALWAYS refuses (rule 5).

    This exists as a chokepoint rather than as an absence: a refusal that is only "we did not write
    any code that writes" is invisible and un-testable, and the next author reaching for a grant
    write would simply open the file. Here they land on a loud, greppable refusal naming the rule.

    Grant writes are performed by the OWNER (or an authority outside the gated component). This is a
    security boundary, not a packaging convenience: any change making this function succeed
    invalidates SPEC-0169 rather than extending it.

    ALWAYS raises `CarrierWriteRefused`; never returns, and never touches the carrier — so the
    carrier's bytes are provably unchanged across an attempt (acceptance V8).

    The refusal NAMES AN APPLICABLE ROUTE (`patterns/verb-design.md` §5(d), T-10767): a refusal
    message IS recovery guidance, so the route must be executable FROM THE STATE THIS REFUSAL
    DETECTED. Here that state is "a non-owner path reached for a grant write", and the only route
    that exists from it is the owner editing this carrier out of band — so the message says that, and
    points at the read-only verb that shows what the reader currently sees. It deliberately names NO
    self-service route, because none exists and inventing one would be worse than silence: this
    system has no path that writes a grant, for a caller or for itself, and that is the point.
    """
    where = str(carrier) if carrier is not None else "<unset carrier>"
    what = f" ({intent})" if intent else ""
    raise CarrierWriteRefused(
        f"grant carrier write REFUSED{what}: {where} — SPEC-0169 rule 5 (separation of duties): the "
        f"component gated by grants must not be able to create, widen, or restore them. Grant writes "
        f"are an OWNER action; this system may only validate, enforce and report. "
        f"Route: ask the OWNER to edit {where} directly — that is the only path by which any grant, "
        f"including the {SCOPE_ALL_REGISTRY_PROJECTS} scope class, is created or widened. "
        f"`bin/yitc-v2 grants report --carrier {where}` shows the state this system reads, read-only."
    )


def read_grant_state(carrier) -> dict:
    """FAITHFUL read of the carrier — reports what it literally says, judges nothing.

    Returns `{carrier, readable, error, people, known_projects}` where `people` maps a person name to
    `{rights_raw, projects_raw, declares_rights, reach_raw, declares_reach}` exactly as written.
    Read-only by construction: the carrier is opened for reading and nothing else in this module ever
    opens it otherwise.

    `reach_raw` is the carrier's LITERAL `reach:` value and `declares_reach` whether the key is
    present at all — nothing else counts as a declaration (rule 8: reach is DECLARED, never implied).
    A `role:` or `restrictions:` entry is NOT read here and must never be promoted into a reach: it
    states intent, and inferring the host fact from it is the false claim rule 8 forbids.
    """
    path = Path(carrier)
    state = {
        "carrier": str(path),
        "readable": False,
        "error": None,
        "people": {},
        "known_projects": [],
    }
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        state["error"] = f"{type(exc).__name__}: {exc}"
        return state
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        state["readable"] = True
        state["error"] = f"unparseable YAML: {exc}"
        return state
    state["readable"] = True
    if not isinstance(doc, dict):
        state["error"] = f"carrier root is {type(doc).__name__}, expected a mapping"
        return state

    projects = doc.get("projects")
    if isinstance(projects, dict):
        state["known_projects"] = sorted(str(k) for k in projects)
    elif isinstance(projects, list):
        state["known_projects"] = sorted(str(p) for p in projects)

    users = doc.get("users")
    if isinstance(users, dict):
        for person, entry in users.items():
            if isinstance(entry, dict):
                state["people"][str(person)] = {
                    "rights_raw": entry.get(RIGHTS_KEY),
                    "projects_raw": entry.get("projects"),
                    "declares_rights": RIGHTS_KEY in entry,
                    "reach_raw": entry.get(REACH_KEY),
                    "declares_reach": REACH_KEY in entry,
                    # Faithful capture of the INTENT keys, for the separate intent-vs-fact channel
                    # only (see INTENT_RESTRICTION_KEYS). Recorded here, never classified here.
                    "intent_raw": {k: entry[k] for k in INTENT_RESTRICTION_KEYS if k in entry},
                }
            else:
                # Faithful: record the shape as-is; `validate_grant_state` decides what it means.
                state["people"][str(person)] = {
                    "rights_raw": None,
                    "projects_raw": None,
                    "declares_rights": False,
                    "reach_raw": None,
                    "declares_reach": False,
                    "intent_raw": {},
                    "entry_type": type(entry).__name__,
                }
    return state


def _scoped_projects(projects_raw):
    """What the carrier says this person's project scope is. Returns `"all"` or a SET.

    FAIL-CLOSED on an absent or malformed `projects:` (returns the empty set, i.e. scoped to
    nothing) — a grant whose holder has no readable scope is NOT silently in scope. Returning None
    here and skipping the check was the audit-post finding: it let a grant read clean by simply
    omitting the field, which is the opposite of what a validator is for.

    `SCOPE_ALL_REGISTRY_PROJECTS` is accepted here as a SECOND SPELLING of the pre-existing `all`
    (T-10793). They mean the identical thing, so accepting both cannot widen anything — it only
    spares the owner two vocabularies for one concept, since the rights side names the class in full.
    """
    if projects_raw in ("all", SCOPE_ALL_REGISTRY_PROJECTS):
        return "all"
    if isinstance(projects_raw, list):
        return {str(p) for p in projects_raw}
    return set()


def resolve_scope_class(known_projects) -> list:
    """RESOLVE the all-registry-projects scope class — the READ-TIME half of the declaration (rule 1).

    This is the whole mechanism by which the decay is removed, and it is deliberately a named
    function rather than an inline comprehension: the card's entire claim is about WHEN membership is
    computed, so the moment of computation must be greppable, injectable and testable on its own.

    `known_projects` is the carrier's declared `projects:` universe — which in this installation IS
    the registry, because the carrier parameter (rule 10) points at it. The registry therefore stays
    the SINGLE authority on which projects exist (CHARTER §Principle 5); nothing here maintains a
    second list, and no new store or parser is introduced.

    An EMPTY universe resolves to NO projects, so a scope-class grant read against a carrier that
    declares no projects covers nothing. That is fail-closed, and `render_report` states the resolved
    COUNT so the case is visible rather than silently inert.
    """
    return sorted(str(p) for p in (known_projects or ()))


def _row_covers_project(row, project: str) -> bool:
    """Does this validated grant row cover `project`? The ONE place the scope class is honoured.

    An ENUMERATED row covers exactly the project it names — unchanged. A SCOPE-CLASS row covers a
    project IFF that project is in the set the class RESOLVED to at read time.

    NOT `return True` for a scope-class row. The resolved set is the BOUND: a project absent from the
    registry universe is still refused, so the class widens coverage to the registry and no further.
    Collapsing this to an unconditional true would make a bare project NAME a sufficient credential,
    which is the exact shape of "the exception swallows the rule".
    """
    if row.get("scope_class") == SCOPE_ALL_REGISTRY_PROJECTS:
        return str(project) in {str(p) for p in (row.get("resolved_projects") or ())}
    return str(row.get("project")) == str(project)


def validate_grant_state(state: dict) -> dict:
    """Schema + SEMANTIC validation of read grant state against SPEC-0169 rules 1-2.

    Returns `{well_formed, problems, grants, people_with_grants, carrier}`. `problems` entries carry
    `{kind, person, project, detail}` — each names WHICH declaration is wrong and why, so a malformed
    set cannot read clean (acceptance V7).

    Deliberately NOT a problem: a person declaring no `rights:` at all. That is "no grant", which is
    the correct reading of today's live carrier — the absence judgement belongs to the authorization
    reader (rule 4, T-10761), not to this validator.

    A RULE-1 PROJECT-SCOPE CONTRADICTION GRANTS NOTHING, in either of its two forms — the scope class
    held by a partially-scoped person, and the enumerated grant naming a project the holder's
    `projects:` does not list (T-10807). Both are the same contradiction and both emit no row, so the
    two paths read as ONE rule rather than as two accidents. What is withheld is the PAIR, never the
    person: a holder's other, coherent rows are unaffected. Reporting is unchanged in both cases — the
    problem is named either way, so this narrows what is GRANTED and never what is SAID.

    A rights row keyed by `SCOPE_ALL_REGISTRY_PROJECTS` is the DECLARED SCOPE CLASS (T-10793), not a
    project name. It passes every rule-2 check unchanged and then yields ONE row that KEEPS the
    declaration (`scope_class`) alongside the membership this read resolved (`resolved_projects`) —
    never N anonymous per-project rows, because the declaration IS the rule and only the membership
    is its resolution. Two POSITIVE preconditions guard it, each emitting no row at all when unmet.
    """
    problems: list[dict] = []
    grants: list[dict] = []

    def problem(kind, detail, person=None, project=None):
        problems.append({"kind": kind, "person": person, "project": project, "detail": detail})

    if not state.get("readable"):
        problem(P_CARRIER_UNREADABLE, state.get("error") or "carrier could not be read")
        return _report(state, problems, grants)
    if state.get("error"):
        problem(P_CARRIER_MALFORMED, state["error"])
        return _report(state, problems, grants)

    known = set(state.get("known_projects") or [])
    for person, entry in sorted((state.get("people") or {}).items()):
        if entry.get("entry_type") is not None:
            problem(P_PERSON_NOT_A_MAPPING,
                    f"user entry is {entry['entry_type']}, expected a mapping", person=person)
            continue
        if not entry.get("declares_rights"):
            continue  # no grant declared — not a malformation (see docstring)
        rights_raw = entry.get("rights_raw")
        if not isinstance(rights_raw, dict):
            # Rule 1: a grant is (person, PROJECT, rights). A flat list or scalar under `rights:`
            # cannot name the project, so it is not expressible as a grant at all.
            problem(P_RIGHTS_NOT_A_MAPPING,
                    f"`{RIGHTS_KEY}:` is {type(rights_raw).__name__}, expected a mapping "
                    f"project -> [rights] (a grant is person x project x rights, rule 1)",
                    person=person)
            continue
        for project, held in sorted((str(k), v) for k, v in rights_raw.items()):
            if not isinstance(held, list):
                # Rule 2: a scalar collapses the separately-grantable rights into one privilege.
                problem(P_RIGHTS_NOT_A_LIST,
                        f"rights for project {project!r} are {type(held).__name__}, expected a list "
                        f"of separately-granted rights (rule 2)",
                        person=person, project=project)
                continue
            if not held:
                problem(P_RIGHTS_EMPTY,
                        f"rights list for project {project!r} is empty — a grant with no right is "
                        f"not a grant; omit the entry instead",
                        person=person, project=project)
                continue
            seen: set[str] = set()
            clean: list[str] = []
            for right in held:
                name = str(right)
                if name not in RIGHTS:
                    problem(P_RIGHT_UNKNOWN,
                            f"right {name!r} is not in the closed set {list(RIGHTS)} (rule 2 — "
                            f"adding a fifth right is a spec change)",
                            person=person, project=project)
                    continue
                if name in seen:
                    problem(P_RIGHT_DUPLICATED,
                            f"right {name!r} listed more than once for project {project!r}",
                            person=person, project=project)
                    continue
                seen.add(name)
                clean.append(name)
            if project == SCOPE_ALL_REGISTRY_PROJECTS:
                # THE SCOPE CLASS (T-10793). Reached only after the rule-2 checks above, so a
                # class-keyed row buys no exemption from the closed right set — it is the PROJECT leg
                # that differs, never the RIGHTS leg.
                if project in known:
                    # A real project bears the reserved name, so this key means two things at once.
                    # Report the ambiguity; resolve it NEITHER way. Reading it as the class would
                    # widen a grant the owner may have meant for one project; reading it as that
                    # project would silently narrow one they meant for all — and a validator that
                    # cannot tell must not assert either (the fall-through the lesson names).
                    problem(P_SCOPE_CLASS_SHADOWED,
                            f"the carrier declares a PROJECT named {project!r}, which is also the "
                            f"reserved all-registry-projects scope class — the key is ambiguous, so "
                            f"it grants nothing. Resolve it by renaming the project (rule 1: the "
                            f"scope class is DECLARED, and a declaration that could mean two things "
                            f"declares neither)",
                            person=person, project=project)
                    continue
                scope = _scoped_projects(entry.get("projects_raw"))
                if scope != "all":
                    # The carrier contradicts itself: rights on ALL projects for a person scoped to
                    # some. The widening needs POSITIVE evidence on every axis, so the contradiction
                    # grants nothing rather than resolving to the wider — or the narrower — reading.
                    problem(P_SCOPE_CLASS_NOT_SCOPED_ALL,
                            f"{person!r} holds the all-registry-projects scope class but `projects:` "
                            f"scopes them to {sorted(scope) or 'nothing'} — a grant on ALL projects "
                            f"for a person scoped to some is a rule-1 contradiction and grants "
                            f"nothing; declare `projects: all` to mean it",
                            person=person, project=project)
                    continue
                if clean:
                    grants.append({
                        "person": person,
                        # The DECLARATION, kept verbatim: this row says which RULE was written, and
                        # `resolved_projects` says what that rule resolved to on THIS read. A row
                        # that dropped the declaration and kept only the list would be the write-time
                        # expansion in disguise — green today, decayed at the next registration.
                        "project": project,
                        "rights": clean,
                        "scope_class": SCOPE_ALL_REGISTRY_PROJECTS,
                        "resolved_projects": resolve_scope_class(known),
                    })
                continue
            # FAIL-CLOSED, unconditionally: a granted project must be DECLARED in the carrier. The
            # earlier `if known and …` guard skipped the whole check when the carrier declared no
            # projects at all, so the least-configured carrier was the least validated one.
            if project not in known:
                problem(P_PROJECT_UNKNOWN,
                        f"project {project!r} is not declared in the carrier's `projects:`"
                        + ("" if known else " (the carrier declares NO projects at all)"),
                        person=person, project=project)
            scope = _scoped_projects(entry.get("projects_raw"))
            if scope != "all" and project not in scope:
                # Rule 1 contradiction: the grant names a project this person is not scoped to.
                # It GRANTS NOTHING — same as the two scope-class contradictions above, because it is
                # the same contradiction in its enumerated form (T-10807). The row used to be emitted
                # anyway, so an authorization could be decided off a declaration this reader had, in
                # the same pass, called contradictory; on the live carrier that was 19 problems, every
                # one of which still produced a grant row. The widening needs POSITIVE evidence on
                # every axis, never an absence of objections.
                #
                # The problem is still REPORTED — this narrows what is GRANTED, never what is SAID.
                # `well_formed` derives from `problems`, so the owner's signal that their carrier
                # contradicts itself is untouched; what is withheld is only the permit it would buy.
                # Withheld per PAIR, not per person: this person's OTHER, coherent rows still stand.
                problem(P_PROJECT_NOT_SCOPED,
                        f"{person!r} holds rights on project {project!r} but is not scoped to it "
                        f"(`projects:` does not list it)",
                        person=person, project=project)
                continue
            if clean:
                grants.append({"person": person, "project": project, "rights": clean})

    return _report(state, problems, grants)


def _report(state, problems, grants) -> dict:
    return {
        "carrier": state.get("carrier"),
        "well_formed": not problems,
        "problems": problems,
        "grants": grants,
        "people_with_grants": len({g["person"] for g in grants}),
    }


def _render_grant_scope(grant: dict) -> str:
    """How a validated grant row NAMES its project scope, for human output.

    An enumerated row renders as its project. A scope-class row renders as the DECLARATION plus the
    COUNT it resolved to on this read — both halves, always. The count is what makes an inert grant
    visible: a class resolved against a carrier declaring no projects covers zero, and printing only
    "all registry projects" there would read as sweeping authority over nothing.
    """
    if grant.get("scope_class") != SCOPE_ALL_REGISTRY_PROJECTS:
        return str(grant.get("project"))
    resolved = grant.get("resolved_projects") or []
    return (f"{SCOPE_ALL_REGISTRY_PROJECTS} (declared scope class -> {len(resolved)} project(s) "
            f"resolved at read time)")


def render_report(report: dict) -> str:
    """Human rendering of a validation report — read-only output, no secrets (a grant names a person,
    a project and a right; the carrier holds no credential and none is echoed here)."""
    lines = [f"grant state: {report['carrier']}"]
    if report["well_formed"]:
        lines.append(f"  WELL-FORMED against SPEC-0169 rules 1-2 — "
                     f"{len(report['grants'])} grant(s), {report['people_with_grants']} person(s)")
    else:
        lines.append(f"  NOT WELL-FORMED — {len(report['problems'])} problem(s) against "
                     f"SPEC-0169 rules 1-2")
    for g in report["grants"]:
        lines.append(f"  grant: {g['person']} on {_render_grant_scope(g)}: {', '.join(g['rights'])}")
    for p in report["problems"]:
        who = p["person"] or "-"
        where = f"{who}/{p['project']}" if p["project"] else who
        lines.append(f"  PROBLEM [{p['kind']}] {where}: {p['detail']}")
    if not report["grants"] and report["well_formed"]:
        lines.append("  no grants declared — the carrier expresses no (person, project, rights) "
                     "triple yet; writing one is an OWNER action (rule 5)")
    lines.append("  read-only: this report wrote nothing to the carrier (rule 5)")
    # The REMOVAL half of the adopt-side safe.directory print (T-11918) — present only when the
    # caller computed it, so every existing caller of `render_report` renders exactly as before.
    if report.get("orphan_safe_directory") is not None:
        lines.append(render_orphan_safe_directory(report["orphan_safe_directory"]))
    return "\n".join(lines)


# ══ THE ORPHANED safe.directory ENTRY — the REMOVAL half of the adopt-side print (T-11918) ═══════
#
# THE GAP. The ADD has a prescribed path: `cmd_worktree_adopt` REFUSES on a foreign-owned worktree
# and PRINTS `git config --global --add safe.directory <wt>` for a HUMAN to run, precisely because
# SPEC-0111 §1 forbids the privileged write into another user's home. The REMOVAL had none — an
# entry outlives the worktree it was granted for and no surface names it. That is why 20 entries
# accumulated in one collaborator's ~/.gitconfig between 2026-08-12 and 2026-08-25.
#
# THIS IS A REPORTER, NOT A RECONCILER. It reads, it names, it PRINTS a command for the human. It
# never writes another user's gitconfig (SPEC-0111 §1) and never writes grant state (SPEC-0169
# rule 5) — the same read-only posture the rest of this module holds.
#
# TWO PROPERTIES CARRY THE SAFETY, and both are load-bearing:
#
# 1. THE EMITTED COMMAND IS ANCHORED. `git config --unset-all` treats its VALUE as a REGEX, not a
#    literal (fingerprint git-config-unset-all-value-is-a-regex-not-a-literal). On 2026-08-11 an
#    unanchored value destroyed 5 unrelated entries. So the path is regex-ESCAPED, wrapped in
#    `^...$`, and then SHELL-quoted — a path is not a regex and neither is it a shell token.
#
# 2. AN ORPHAN IS A POSITIVE FINDING, NEVER AN ABSENCE OF EVIDENCE. An entry is called dead only on
#    a stat that positively reports the path missing. An unreadable gitconfig, a permission error,
#    any other host fault → UNDETERMINABLE, reported as such and NEVER as an orphan. The failure
#    this guards is the expensive one: telling a collaborator to delete an entry their live worktree
#    still needs.

SD_LIVE = "live"
SD_ORPHAN = "orphan"
SD_UNDETERMINABLE = "undeterminable"

# Escaped for the regex `git config --unset-all` will compile out of the value we emit. Anchoring
# alone is not enough: an unescaped `.` matches any character, so `/home/x/a.b` would also match
# `/home/x/axb` — a sibling entry the human never meant to unset.
_REGEX_METACHARS = r".^$*+?()[]{}|\\"


def _escape_for_git_config_regex(path: str) -> str:
    return "".join("\\" + ch if ch in _REGEX_METACHARS else ch for ch in str(path))


def anchored_safe_directory_removal(path: str) -> str:
    """The removal command a HUMAN runs in their OWN home to drop ONE safe.directory entry.

    ANCHORED (`^...$`) and regex-ESCAPED around the path — see property 1 above; then shell-quoted,
    so a path carrying a quote or a space still yields a runnable command rather than a broken or
    re-interpreted one. This function EMITS A STRING. Nothing here runs it: executing the removal in
    another user's home is the privileged write SPEC-0111 §1 puts with the human.
    """
    return ("git config --global --unset-all safe.directory "
            + shlex.quote("^" + _escape_for_git_config_regex(path) + "$"))


def parse_safe_directory_entries(text: str) -> list:
    """Every `safe.directory` VALUE declared in gitconfig `text`, in file order, duplicates kept.

    A hand parser, not configparser: git config repeats the same key deliberately (one line per
    granted path) and configparser collapses duplicates — which would silently hide entries. Handles
    the `[safe]` section header and git's `[safe] directory = x` one-liner is NOT valid gitconfig, so
    only the section+key form is read.
    """
    entries = []
    in_safe = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("["):
            section = line[1:].split("]")[0].strip().strip('"').lower()
            in_safe = section == "safe"
            continue
        if not in_safe or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip().lower() == "directory":
            entries.append(value.strip())
    return entries


def _default_gitconfig_for(person: str):
    """`~<person>/.gitconfig` from the host passwd database, or None when the host does not know the
    person. Resolution only — the file is opened READ-only by the caller, never for write."""
    try:
        return str(Path(pwd.getpwnam(str(person)).pw_dir) / ".gitconfig")
    except (KeyError, TypeError):
        return None


def _classify_safe_directory_path(path: str, *, stat_path=None) -> tuple:
    """`(classification, detail)` for one entry — property 2 above.

    ONLY a stat that positively reports the path MISSING yields SD_ORPHAN. Every other failure is
    SD_UNDETERMINABLE with the reason attached: we would rather say "I could not tell" than hand a
    collaborator a removal command for an entry that may still be live.
    """
    stat = stat_path or os.stat
    if not path:
        return SD_UNDETERMINABLE, "empty entry — nothing to check"
    try:
        stat(path)
    except FileNotFoundError:
        return SD_ORPHAN, "path does not exist on disk"
    except OSError as exc:
        return SD_UNDETERMINABLE, f"{type(exc).__name__}: {exc} — no claim made about this entry"
    return SD_LIVE, "path exists on disk"


def orphan_safe_directory_report(carrier, *, gitconfig_for=None, stat_path=None,
                                 read_text=None) -> dict:
    """Per-collaborator orphaned-safe.directory report over the people the grant carrier names.

    Returns `{carrier, readable, people: [row]}` where each row carries `person`, `gitconfig`,
    `gitconfig_readable`, `error`, `entry_count`, `live`, `undeterminable` and `orphans`
    (`[{path, why, removal_command}]`).

    `gitconfig_for` / `stat_path` / `read_text` are injected exactly as `reach_report` injects
    `resolve_groups` — so the contract can be exercised against a FIXTURE gitconfig on a fixture
    host, never against a real collaborator's home. Read-only end to end.
    """
    locate = gitconfig_for or _default_gitconfig_for
    reader = read_text or (lambda p: Path(p).read_text(encoding="utf-8", errors="replace"))
    state = read_grant_state(carrier)
    report = {
        "carrier": state.get("carrier"),
        "readable": bool(state.get("readable")) and not state.get("error"),
        "error": state.get("error"),
        "people": [],
    }
    if not report["readable"]:
        return report

    for person in sorted((state.get("people") or {})):
        row = {
            "person": person,
            "gitconfig": None,
            "gitconfig_readable": False,
            "error": None,
            "entry_count": 0,
            "live": [],
            "undeterminable": [],
            "orphans": [],
        }
        path = locate(person)
        row["gitconfig"] = path
        if not path:
            row["error"] = "host does not know this person — no home to read"
            report["people"].append(row)
            continue
        try:
            text = reader(path)
        except OSError as exc:
            # An unreadable config states NOTHING. It is not evidence of zero entries and it is
            # certainly not evidence of an orphan.
            row["error"] = f"{type(exc).__name__}: {exc} — no entry is claimed for this person"
            report["people"].append(row)
            continue
        row["gitconfig_readable"] = True
        entries = parse_safe_directory_entries(text)
        row["entry_count"] = len(entries)
        for entry in entries:
            classification, why = _classify_safe_directory_path(entry, stat_path=stat_path)
            if classification == SD_LIVE:
                row["live"].append(entry)
            elif classification == SD_ORPHAN:
                row["orphans"].append({
                    "path": entry,
                    "why": why,
                    "removal_command": anchored_safe_directory_removal(entry),
                })
            else:
                row["undeterminable"].append({"path": entry, "why": why})
        report["people"].append(row)
    return report


def render_orphan_safe_directory(report: dict) -> str:
    """Human rendering of the orphan section. Names paths and prints one removal command per orphan —
    for the HUMAN to run in their own home; this process runs none of them."""
    lines = ["  safe.directory entries whose worktree is gone (read-only, SPEC-0111 §1):"]
    if not report.get("readable"):
        lines.append("    carrier unreadable — no entry is claimed for anyone")
        return "\n".join(lines)
    if not report.get("people"):
        lines.append("    the carrier names no person — nothing to check")
        return "\n".join(lines)
    total = 0
    for row in report["people"]:
        if row["error"]:
            lines.append(f"    {row['person']}: NOT CHECKED — {row['error']}")
            continue
        total += len(row["orphans"])
        lines.append(f"    {row['person']} ({row['gitconfig']}): {row['entry_count']} entry(ies), "
                     f"{len(row['live'])} live · {len(row['orphans'])} ORPHANED · "
                     f"{len(row['undeterminable'])} undeterminable")
        for orphan in row["orphans"]:
            lines.append(f"      ORPHAN {orphan['path']} — {orphan['why']}")
            lines.append(f"        run AS {row['person']}, in their own home: "
                         f"{orphan['removal_command']}")
        for unknown in row["undeterminable"]:
            lines.append(f"      UNDETERMINABLE {unknown['path']} — {unknown['why']} "
                         f"(NOT reported as an orphan)")
    if not total:
        lines.append("    no orphaned entry found")
    else:
        lines.append("    the removal command above is ANCHORED (^...$, metacharacters escaped): "
                     "`git config --unset-all` treats its value as a REGEX, and an unanchored one "
                     "unset 5 unrelated entries on 2026-08-11 (T-11835)")
    lines.append("    read-only: this section wrote nothing to any gitconfig — the privileged write "
                 "into another user's home stays the human's (SPEC-0111 §1)")
    return "\n".join(lines)


# ══ THE PROVENANCE BOUNDARY — SPEC-0169 rules 3 + 4 (T-10760) ════════════════════════════════════
#
# PLACEMENT IS PART OF THE CLAIM. The trial's cycle-2 finding: a good-faith implementation can place
# a rule-3 guard at a shared authority site where the caller-supplied and the session-derived value
# have both become a plain `actor: str` — and there it cannot refuse what it can no longer see. So
# the caller MUST hand these functions RAW argv + env, from a site that still has them (the CLI's
# pre-argparse boundary — `bin/yitc-v2#_gate_actor_provenance`). To make the misplacement hard rather
# than merely discouraged, NOTHING here takes an actor/identity parameter: there is no argument
# through which a caller could supply a name, so a call site cannot pass one even by mistake.

# The CLOSED set of caller-assertable actor sources. Argument tokens first: the flag spelling that
# produced the real incident is `--actor` (an operation took its actor from a command-line flag
# defaulting to the local user, so the person performing it supplied their own name — while a
# collaborator held production deploy rights). The rest are the same assertion under other names.
ACTOR_ARG_TOKENS = (
    "--actor", "--as-user", "--as", "--run-as", "--identity", "--on-behalf-of", "--user",
)

# The environment fallbacks. `BRIDGE_APPLY_ACTOR` is the trial's REAL one (the consumer path took
# its actor from a flag defaulting to this var, defaulting in turn to the local user).
ACTOR_ENV_VARS = (
    "YITC_ACTOR", "YITC_AS_USER", "YITC_IDENTITY", "YITC_RUN_AS",
    "BRIDGE_APPLY_ACTOR", "DEPLOY_ACTOR", "DEPLOY_USER",
)

# Which verbs are GATED operations, and by which rule-2 right. A gated verb pays the boundary; every
# other verb is untouched by it. Kept a closed mapping (not a predicate) so "is this gated?" has one
# greppable answer — and so extending the gate is a visible edit, never an emergent side-effect.
# Deliberately NOT widened by T-11683: `decide-authority` gates no verb, because deciding a cause
# and performing one are different rights (rule 2's separation, spec probe V12). Wiring a verb to it
# here would give the decision right an execution path and collapse the two.
GATED_OPERATIONS = {"deploy": "deploy-code"}

# Flags that make a gated verb's invocation PERFORM NOTHING — a pure delivery/inspection surface
# (T-10765). Closed, per-verb, and deliberately tiny.
#
# THIS IS NOT A CARVE-OUT IN A FAIL-CLOSED GATE, and the distinction matters (`lessons/carving-an-
# exception-into-a-fail-closed-gate.md` — the discriminator is the whole risk). Rule 2 defines
# `deploy-code` as "build and replace the running application". `deploy --print-guard` writes a text
# snippet to stdout and returns BEFORE any deploy machinery runs; it builds nothing and replaces
# nothing, so it is not an exercise of the right at all. Running it through the gate would not make
# anything safer — it would write a rule-9 record asserting a `deploy-code` exercise that never
# happened, i.e. make the trail report a thing that is false, exactly where rule 9 needs it probative.
#
# THE DISCRIMINATOR IS THE VERB'S OWN BEHAVIOUR, not a judgement about risk: `cmd_deploy` handles
# `--print-guard` first and RETURNS, so the flag's presence is precisely the condition under which
# nothing is performed. That coupling is asserted by a test, so the two cannot drift apart.
#
# The rule-3 + rule-4 IDENTITY boundary is untouched by this and still applies to these invocations,
# exactly as it did before the policy switched on — this narrows only what counts as an EXERCISE.
NON_PERFORMING_FLAGS = {"deploy": ("--print-guard",)}


def performs_nothing(argv, verb: str) -> bool:
    """Does this invocation of a gated `verb` perform nothing (`NON_PERFORMING_FLAGS`)?

    Read from RAW argv, matching both `--flag` and `--flag=value` spellings, because the gate that
    consults this runs pre-argparse. Fails toward PERFORMING: an unrecognised flag, or a verb with
    no entry, returns False, so the gate is paid unless a listed flag is positively present.
    """
    flags = NON_PERFORMING_FLAGS.get(verb) or ()
    return any(tok.split("=", 1)[0] in flags for tok in (argv or []))

# Global options that precede the verb token, with whether they consume the NEXT argv item.
_GLOBAL_OPTS = {"-C": True, "--directory": True}

# The verbs whose rule-3 refusal the PRE-ARGPARSE gate must deliver (`grants identity`, `grants
# authorize`, `grants exercise`). The first two are READ-ONLY inspections and the third exercises the
# one no-write right (T-10763) — none is a gated operation in `GATED_OPERATIONS` — but each must
# still be able to REFUSE caller-supplied
# actor input, or its documented refusal would be unreachable: argparse rejects `--actor` as an
# unknown option before the verb function runs, so the caller would get an argparse usage error
# instead of the rule-3 refusal (audit-post finding, absorbed). Hence the same pre-argparse gate
# covers them, with rule 3 ONLY. `grants report` is NOT here: it reads grant state and derives no
# identity, so it has no actor input to refuse.
BOUNDARY_INSPECTIONS = (("grants", "identity"), ("grants", "authorize"), ("grants", "exercise"))

# The instrument (SPEC-0169 rule 3 ordering evidence). A count, not a log: the acceptance differential
# asks "did a derivation happen on this path at all", and the cycle-2 review rejected an instrument
# that injects a SUBSTITUTE identity source — proving the ordering for the substitute, never for the
# real derivation. So this counter lives INSIDE the real `derive_server_identity` and nowhere else.
_DERIVATIONS = 0


class ActorInputRefused(RuntimeError):
    """Rule 3 — a caller-supplied actor argument or environment fallback was supplied and REFUSED."""


class IdentityRefused(RuntimeError):
    """Rule 4 — the acting identity is missing, unmapped, unissued, or holds no readable grant."""


# Which grant-set fact refused (the `GrantSetRefused.reason` vocabulary). Split apart because an
# INSTALLATION-level absence and a PER-PERSON one are different facts: only the second is what a
# revocation produces, and rule 7 makes that difference something to demonstrate, not infer.
GS_CARRIER_UNREADABLE = "carrier-unreadable"
GS_CARRIER_DECLARES_NO_GRANT = "carrier-declares-no-grant"
GS_NO_GRANT_FOR_IDENTITY = "no-grant-for-identity"


class GrantSetRefused(IdentityRefused):
    """Rule 4's GRANT-SET leg specifically — the carrier is unreadable/malformed/empty, or declares
    no grant for this identity (raised by `bind_identity_to_grants`).

    A SUBCLASS, not a sibling: every existing `except IdentityRefused` keeps catching it unchanged
    (T-10760's `cmd_grants_identity` distinguishes the two legs by call site and is untouched). It
    exists so a caller that runs both legs in ONE call — `authorize` — can still tell "the server
    does not know you" from "the server knows you and its grant state says nothing about you", which
    are different exit codes. The alternative, matching on the message text, would make an exit-code
    contract depend on prose (T-10761).

    `reason` names WHICH grant-set fact refused: `carrier-unreadable` / `carrier-declares-no-grant` /
    `no-grant-for-identity`. Carried for the same reason — `authorize` must be able to tell an
    installation-level absence (nothing is configured) from a per-person one (this NAME is not in the
    grant set), because only the second is what a REVOCATION produces, and rule 7 requires that
    difference to be demonstrable rather than inferred from a message.

    `identity` carries the ALREADY-DERIVED server-issued identity this refusal was about (T-10765).
    Every raise site below runs AFTER `acting_identity` has succeeded, so the name is known — and
    rule 9 says the record names WHICH identity acted. Without this the INSTALLATION-level branch
    (an unreadable carrier, or one declaring no grant at all) recorded `identity: null` for a
    refusal whose identity had in fact been derived a line earlier, which is a trail that cannot
    answer the one question it exists for. Found by the real gated path the policy switch turned on.
    """

    def __init__(self, message: str, reason: str = "", identity=None):
        super().__init__(message)
        self.reason = reason
        self.identity = identity


def derivation_count() -> int:
    """How many times the REAL derivation has run in this process (the rule-3 ordering instrument)."""
    return _DERIVATIONS


def reset_derivation_count() -> None:
    """Zero the instrument — for a differential that measures ONE path's derivations."""
    global _DERIVATIONS
    _DERIVATIONS = 0


def gated_operation(argv) -> str | None:
    """Which rule-2 right this invocation's VERB is gated by, or None when the verb is not gated.

    Resolves the verb from RAW argv, skipping the global `-C <path>` / `--directory <path>` pair (and
    its `--directory=<path>` spelling). Unknown leading options are skipped WITHOUT consuming a value:
    guessing arity would let a crafted `--foo deploy` hide the verb, and this must fail toward
    RECOGNISING a gated verb, never away from it.
    """
    for i, tok in enumerate(argv or []):
        if not tok.startswith("-"):
            return GATED_OPERATIONS.get(tok)
        if tok in _GLOBAL_OPTS and _GLOBAL_OPTS[tok]:
            # Skip this option AND its value by scanning from the item after next.
            return gated_operation(list(argv)[i + 2:])
    return None


def is_boundary_inspection(argv) -> bool:
    """Is this invocation one of the READ-ONLY inspections of this boundary (`BOUNDARY_INSPECTIONS`)?

    Same verb resolution as `gated_operation` (global `-C <path>` skipped), plus the subcommand — so
    the pre-argparse gate can deliver rule 3's refusal for a verb that performs nothing but must
    still be able to refuse an assertion. `grants report` is NOT included: it reads grant state and
    derives no identity, so it has no actor input to refuse.
    """
    return boundary_inspection_name(argv) is not None


def boundary_inspection_name(argv):
    """WHICH boundary inspection this invocation is, as a `(verb, subcommand)` tuple, or None.

    Split out from the boolean so the pre-argparse gate can name the ACTUAL inspection in its refusal
    and its journal event. Hard-coding one name there was correct while there was one inspection and
    becomes a silent mislabel the moment there are two — a refusal of `grants authorize` recorded as
    `grants identity` is a wrong fact in an append-only journal.
    """
    rest = list(argv or [])
    while rest and rest[0].startswith("-"):
        opt = rest[0]
        rest = rest[2:] if _GLOBAL_OPTS.get(opt) else rest[1:]
    head = tuple(rest[:2])
    return head if head in BOUNDARY_INSPECTIONS else None


def caller_supplied_actor_sources(argv, env) -> list[dict]:
    """FAITHFUL detector — reports every caller-assertable actor source it can see, and judges nothing.

    The judgement is the REFUSAL's, one layer up (`lessons/fail-closed-belongs-to-the-reader-not-the-
    parser.md`): the same faithful report serves a refusal and a read-only inspection, which must
    describe what it sees without dying.

    An env var present with an EMPTY value asserts no actor, so it is not reported — there is nothing
    to refuse. This is not a fail-open crack: the derivation below reads NO environment variable at
    all under any value, so an empty var can no more supply an identity than an absent one.
    """
    found: list[dict] = []
    for tok in argv or []:
        name = tok.split("=", 1)[0]
        if name in ACTOR_ARG_TOKENS:
            found.append({"kind": "argument", "name": name})
    for var in ACTOR_ENV_VARS:
        if str((env or {}).get(var) or "").strip():
            found.append({"kind": "environment", "name": var})
    return found


def refuse_caller_supplied_actor(argv, env, *, operation: str = "") -> None:
    """Rule 3's REFUSAL — raises `ActorInputRefused` when any caller-assertable actor source is present.

    REFUSED, not overridden and not merely logged: an operation that quietly ignored the flag and
    proceeded on the correct identity would leave the caller believing the assertion was accepted,
    and would leave the next reader believing the flag is honoured somewhere.

    Runs BEFORE any derivation, so with a source present the derivation is UNREACHABLE rather than
    merely unused — that ordering is what the instrument measures.
    """
    found = caller_supplied_actor_sources(argv, env)
    if not found:
        return
    what = ", ".join(f"{f['name']} ({f['kind']})" for f in found)
    where = f" for {operation}" if operation else ""
    raise ActorInputRefused(
        f"caller-supplied acting identity REFUSED{where}: {what} — SPEC-0169 rule 3: the acting "
        f"identity is derived EXCLUSIVELY from the server-issued session/OS identity. "
        f"Route: re-run the same command with that argument and/or variable REMOVED — it will then "
        f"act as the identity you logged in as. To act as someone else, log in as them; provisioning "
        f"an identity and granting it rights is an OWNER action (rule 5), never a caller argument."
    )


def derive_server_identity(*, session_identity) -> str:
    """The ONLY producer of an acting identity — the server-issued session/OS identity, nothing else.

    Takes a zero-argument CALLABLE, never a name: there is no parameter through which a caller could
    supply an identity, which is the placement obligation made structural rather than documented.

    THIS BODY reads no argv and no environment variable — but that is a property of the FUNCTION, and
    rule 3 is a property of the COMPOSITION. The identity arrives through `session_identity`, so the
    promise is only as good as the producer the call site binds, and it was once false in exactly that
    way (T-11376): every gate site bound `lib/memory.py#current_user`, i.e. `getpass.getuser()`, which
    consults LOGNAME/USER/LNAME/USERNAME before the passwd database. Measured with `USER=<collaborator>
    LOGNAME=<collaborator>` set against the real uid name `dev`, this function returned `<collaborator>` — and because
    `<collaborator>` is a provisioned user, rule 4's vocabulary check admitted it.

    So the contract is on the CALLER: **`session_identity` MUST be a producer that reads no
    environment.** `lib/memory.py#os_identity` (`pwd.getpwuid(os.getuid()).pw_name`) is that producer
    and is what every shipped gate site binds; `lib/memory.py#current_user` is NOT, and must never be
    bound here — it remains the test monkeypatch seam and the SPEC-0039 audience filter. A test may
    inject any callable it likes; a SHIPPED call site may not. That obligation is checked
    mechanically, not trusted to this docstring, by the STRUCT-CALLSITE leg of
    tests/test_spec0169_identity_derivation.py.

    An empty / unresolvable identity RAISES (rule 4 — a missing identity is a refusal, never an open
    door), unlike the sibling attribution path `lib/memory.py#resolve_actor`, which deliberately fails
    OPEN to the `ai-agent` default because attribution is a record and this is a gate.
    """
    global _DERIVATIONS
    _DERIVATIONS += 1
    identity = str(session_identity() or "").strip()
    if not identity:
        raise IdentityRefused(
            "acting identity REFUSED: the server issued no session/OS identity for this process — "
            "SPEC-0169 rule 4 (a missing identity is a refusal, never an open door). "
            "Route: run the operation from a real login session of a provisioned user (an ssh/login "
            "shell has one; a detached process with no passwd entry does not)."
        )
    return identity


def acting_identity(*, argv, env, session_identity, registry_text, operation: str = "") -> dict:
    """THE GATE — rules 3 + 4, in the one order that makes rule 3 load-bearing.

    (1) REFUSE every caller-supplied actor source; (2) DERIVE from the server-issued identity;
    (3) REFUSE an identity the server did not issue — i.e. one absent from the host's provisioned
    `users:` vocabulary. Step 1 precedes step 2 unconditionally, so a refused call performs ZERO
    derivations and "a correct identity cannot reach around it".

    Returns `{identity, source, operation}`. Reaches NO grant state and returns NO allow/deny verdict
    — WHICH rights the identity holds is the authorization card's claim (T-10761); the grant-set
    fail-closed leg of rule 4 is its own function (`bind_identity_to_grants`), so this gate cannot
    express an authorization decision even by accident.
    """
    refuse_caller_supplied_actor(argv, env, operation=operation)
    identity = derive_server_identity(session_identity=session_identity)
    known = _provisioned_users(registry_text)
    if identity not in known:
        raise IdentityRefused(
            f"acting identity {identity!r} REFUSED: this server did not issue it — it is not a "
            f"provisioned user in the host registry ({'no users are declared there' if not known else 'declared: ' + ', '.join(sorted(known))}). "
            f"SPEC-0169 rule 4 (an unmapped identity is a refusal). "
            f"Route: run the operation as a provisioned user; provisioning one is an OWNER action "
            f"(rule 5). To see the state this refusal read, run `bin/yitc-v2 grants report`."
        )
    return {"identity": identity, "source": "server-issued", "operation": operation or None}


def _provisioned_users(registry_text: str) -> set[str]:
    """The host's provisioned identity VOCABULARY — the registry `users:` keys.

    Parsed with the SAME block scan the audience/attribution path already uses
    (`lib/memory.py#registry_users`), imported lazily so this module stays importable stand-alone; a
    failure to import or parse degrades to the EMPTY set, which fails CLOSED here (every identity is
    then unmapped and refused) — the opposite of `memory`'s own fail-open default, which is correct
    for attribution and wrong for a gate.
    """
    try:
        from lib import memory  # noqa: PLC0415 — lazy: keeps this module a stdlib+yaml leaf
        return set(memory.registry_users(registry_text or ""))
    except Exception:
        return set()


def bind_identity_to_grants(identity: str, carrier) -> list[dict]:
    """Rule 4's GRANT-SET leg — an empty or unreadable grant set is a REFUSAL, never an open door.

    CONSUMES the T-10759 reader above rather than re-reading the carrier (one parse, one validator).
    Refuses when the carrier is unreadable or malformed, when it declares no grant at all, and when it
    declares none for THIS identity. Returns that identity's grant ROWS as the carrier states them.

    NOT an authorization decision: it answers "does the server have anything to say about this
    person", never "may they do X" — the right-level allow/deny is T-10761's. A misconfigured
    installation therefore denies work; it never grants it.
    """
    report = validate_grant_state(read_grant_state(carrier))
    kinds = {p["kind"] for p in report["problems"]}
    if kinds & {P_CARRIER_UNREADABLE, P_CARRIER_MALFORMED}:
        detail = "; ".join(p["detail"] for p in report["problems"])
        raise GrantSetRefused(
            f"grant set REFUSED: {report['carrier']} could not be read as grant state ({detail}) — "
            f"SPEC-0169 rule 4 (an unreadable grant set is a refusal, never an open door). "
            f"Route: `bin/yitc-v2 grants report --carrier {report['carrier']}` shows what the reader "
            f"sees; repairing the carrier is an OWNER action (rule 5).",
            reason=GS_CARRIER_UNREADABLE, identity=identity,
        )
    if not report["grants"]:
        raise GrantSetRefused(
            f"grant set REFUSED: {report['carrier']} declares NO grant at all — SPEC-0169 rule 4 "
            f"(an empty grant set is a refusal, never an open door). "
            f"Route: `bin/yitc-v2 grants report` shows the live state; writing a (person, project, "
            f"rights) grant into it is an OWNER action (rule 5), not something this system can do.",
            reason=GS_CARRIER_DECLARES_NO_GRANT, identity=identity,
        )
    mine = [g for g in report["grants"] if g["person"] == identity]
    if not mine:
        holders = sorted({g["person"] for g in report["grants"]})
        raise GrantSetRefused(
            f"acting identity {identity!r} REFUSED: the grant set declares no grant for it "
            f"(declared holders: {', '.join(holders)}) — SPEC-0169 rule 4. "
            f"Route: `bin/yitc-v2 grants report` shows the live state; granting rights to an identity "
            f"is an OWNER action (rule 5).",
            reason=GS_NO_GRANT_FOR_IDENTITY, identity=identity,
        )
    return mine


def cmd_grants_identity(args, *, argv, env, session_identity, registry_text, default_carrier,
                        append_event, out=print) -> int:
    """`grants identity [--carrier PATH] [--json]` — READ-ONLY inspection of the provenance boundary.

    SPEC-0169 rule 6 obliges identity binding + refusal on an unissued identity to exist IN OUR OWN
    CODE, and read-only inspection of live grant state alongside it. This verb is that inspection for
    the identity half: it runs the SAME `acting_identity` + `bind_identity_to_grants` a gated
    operation runs, and reports the outcome instead of performing anything.

    Exit codes are LOUD (SPEC-0165): 0 proceed · 2 caller-supplied actor input refused · 3 identity
    refused (missing / unmapped) · 4 grant-set refused (unreadable / empty / none for this identity).

    Note on where code 2 fires from: for an actor ARGUMENT the host's pre-argparse gate raises it
    (argparse would otherwise reject the unknown option first — `BOUNDARY_INSPECTION`), for an actor
    ENV var this body does. Same refusal text either way, and this body's check is what an in-process
    caller (and the module-level differential) exercises.
    """
    carrier = getattr(args, "carrier", None) or default_carrier
    as_json = getattr(args, "json", False)

    def _refused(kind: str, code: int, message: str, identity=None) -> int:
        append_event("acting_identity_refused", None, {
            "kind": kind, "operation": "grants identity", "identity": identity,
            "derivations": derivation_count(), "spec": "SPEC-0169",
        })
        if as_json:
            out(json.dumps({"refused": kind, "identity": identity, "carrier": str(carrier),
                            "detail": message}, indent=2, sort_keys=True))
        else:
            out(f"acting identity: REFUSED [{kind}]\n  {message}")
        return code

    reset_derivation_count()
    try:
        derived = acting_identity(argv=argv, env=env, session_identity=session_identity,
                                  registry_text=registry_text, operation="grants identity")
    except ActorInputRefused as exc:
        return _refused("caller-supplied-actor", 2, str(exc))
    except IdentityRefused as exc:
        return _refused("identity", 3, str(exc))

    identity = derived["identity"]
    try:
        mine = bind_identity_to_grants(identity, carrier)
    except IdentityRefused as exc:
        return _refused("grant-set", 4, str(exc), identity=identity)

    append_event("acting_identity_derived", None, {
        "identity": identity, "identity_source": derived["source"],
        "operation": "grants identity",
        "derivations": derivation_count(), "grant_count": len(mine), "spec": "SPEC-0169",
    })
    if as_json:
        out(json.dumps({"identity": identity, "source": derived["source"],
                        "carrier": str(carrier), "grants": mine}, indent=2, sort_keys=True))
    else:
        out(f"acting identity: {identity} (server-issued — SPEC-0169 rule 3; no caller input accepted)")
        for g in mine:
            out(f"  grant: {_render_grant_scope(g)}: {', '.join(g['rights'])}")
        out("  read-only: this verb decided no authorization and wrote nothing to the carrier")
    return 0


# ══ THE AUTHORIZATION DECISION — SPEC-0169 rules 1 + 2 + 4 + 7 (T-10761) ═════════════════════════
#
# THE ABSENCE JUDGEMENT LIVES HERE, NOT IN THE PARSER (`lessons/fail-closed-belongs-to-the-reader-
# not-the-parser.md`). `validate_grant_state` deliberately reports an absent `rights:` as "this
# person declares no grant" and calls it no malformation — correct for a validator. THIS is the
# reader rule 4 addresses: the same absence is a REFUSAL here. One parse, two correctly-different
# absence judgements; a parser that tried to be fail-closed for both callers would be wrong for one.

# Why a refusal REASON is a named token and not prose: a caller (and a test) asserts on the token, so
# the four fail-closed branches stay individually visible. Collapsing them to one "denied" would make
# the rule-2 separability branch indistinguishable from the rule-4 empty-set branch — which is
# exactly the confusion acceptance V4 exists to rule out (was the refusal about the NAME, or about
# the set being empty?).
A_PERMITTED = "permitted"
A_UNKNOWN_RIGHT = "unknown-right"                # not in the rule-2 closed set
A_NO_GRANT_FOR_IDENTITY = "no-grant-for-identity"  # this person holds no row on any project
A_NOT_SCOPED_TO_PROJECT = "not-scoped-to-project"  # rows exist, none on THIS project
A_RIGHT_NOT_HELD = "right-not-held"              # a row on THIS project, but not this right


class AuthorizationRefused(RuntimeError):
    """Rules 1-2 + 4 — the acting identity does not hold this right on this project."""

    def __init__(self, message: str, decision: dict):
        super().__init__(message)
        # Carried so a caller can report the REASON without re-deriving it from the message text.
        self.decision = decision


def decide_authorization(rows, identity: str, project: str, right: str) -> dict:
    """THE DECISION — permitted iff (identity, project, right) is named in `rows`. Pure, no I/O.

    `rows` are the validated grant rows `validate_grant_state` produces (`{person, project,
    rights}`) — this function never re-reads or re-validates the carrier, so there is exactly one
    parse and one validator in the module (CHARTER §P5).

    Returns `{permitted, reason, identity, project, right, rights_held, matched_grant}`. It returns
    rather than raises so a READ-ONLY inspection can report a refusal without dying; `authorize`
    below is the enforcing caller that turns a refusal into an exception.

    RULE 1 — "the owner only" is NOT EXPRESSIBLE, so there is no owner branch to write. Nothing here
    reads a `role`, an `owner` flag, a registry label, or any other property of the PERSON: the only
    question asked is whether the explicit triple is named. That is what makes a granted NON-OWNER
    permitted (acceptance V5) — an implementation that special-cased an owner would pass every
    refusal probe and fail exactly that one.

    RULE 2 — the rights are decided SEPARATELY, each by its own membership in the row's OWN list.
    Holding `deploy-code` decides nothing about `apply-prod-data` (acceptance V6), and holding
    `decide-authority` decides nothing about either (acceptance V12): this one function is the whole
    reason the decision right carries no execution — it asks about the ONE right it was handed and
    never widens to a neighbour.

    RULE 4 — fail closed in both directions: every non-match is a refusal with a named reason, and an
    unknown right is refused BEFORE the row scan, so a right outside the closed set can never match a
    literal string a carrier happens to contain.

    RULE 7 — revocation is provable as a consequence of the shape above, not as a separate mechanism:
    remove the person's row and the same request that matched now reports `no-grant-for-identity`,
    while a bystander's row still matches (acceptance V4).

    RULE 1's PROJECT LEG is asked through `_row_covers_project`, which is the single place the
    all-registry-projects scope class is honoured (T-10793). The class widens WHICH PROJECTS a row
    covers and nothing else: the PERSON filter above it and the RIGHT membership below it are
    untouched, so a class-bearing row can no more admit another identity than an enumerated one can.
    """
    identity = str(identity)
    project = str(project)
    right = str(right)

    def verdict(reason, matched=None, held=()):
        return {
            "permitted": reason == A_PERMITTED,
            "reason": reason,
            "identity": identity,
            "project": project,
            "right": right,
            "rights_held": sorted(held),
            "matched_grant": matched,
        }

    if right not in RIGHTS:
        # Refused ahead of the scan: the closed set of rule 2 is the WHOLE vocabulary, so an
        # unrecognised right is a refusal and never a pass-through to string matching.
        return verdict(A_UNKNOWN_RIGHT)

    mine = [r for r in (rows or []) if str(r.get("person")) == identity]
    if not mine:
        return verdict(A_NO_GRANT_FOR_IDENTITY)

    here = [r for r in mine if _row_covers_project(r, project)]
    if not here:
        return verdict(A_NOT_SCOPED_TO_PROJECT)

    held = {str(x) for r in here for x in (r.get("rights") or [])}
    if right not in held:
        # THE RULE-2 SEPARABILITY BRANCH. Reached only when the person DOES hold rights here — so the
        # refusal is about this one right, and `rights_held` says which ones they do hold.
        return verdict(A_RIGHT_NOT_HELD, held=held)

    matched = next(r for r in here if right in {str(x) for x in (r.get("rights") or [])})
    return verdict(A_PERMITTED, matched=matched, held=held)


# ══ THE AUTHORITY-CLASS GATE — SPEC-0191 §5a (T-11684) ═══════════════════════════════════════════
#
# WHAT THIS IS, AND WHY IT IS NOT THE READER BELOW IT. `authorize` answers "does this person hold
# this right here". That is a GRANT question, and it was already answered before this card. THIS
# function answers the DOCTRINE question SPEC-0191 §5 asks: "may this session DECIDE this
# AUTHORITY-class cause on this project, or does it stop at the owner?" Until T-11684 the answer was
# always "it stops", stated only as prose in the dispatch preamble and the land refusal — there was
# no gate to condition. This is that gate, and it is the ONE surface both the doctrine and its
# tripwire consume, so a test cannot pass by exercising the grant reader while the owner-only stop
# still governs.
#
# The decision right's literal, named ONCE. Everything that must agree — this gate, the refusal
# message's locus clause, the tripwire — reads it from here, so the doctrine arm and the carrier
# cannot drift apart.
DECISION_RIGHT = "decide-authority"

# The CLOSED authority-class vocabulary of SPEC-0191 §5. This is the SECOND copy of that list in the
# codebase (the first being the §5 body itself), which is a drift-CAPABLE mention by the SPEC-0067
# test — so it is drift-CHECKED: the T-11684 tripwire asserts this tuple against the ACTIVE lineage
# spec's body. A copy nobody checks is the failure mode; a checked copy is not.
#
# It is a CLOSED vocabulary rather than a predicate for the reason `lessons/carving-an-exception-
# into-a-fail-closed-gate` §1 gives: the discriminator is the whole risk. A cause this gate does not
# recognise is REFUSED, never admitted — so a typo, a renamed cause, or a caller inventing one denies
# the decision instead of opening it.
AUTHORITY_CLASS_CAUSES = (
    "data-deletion",
    "destructive-db-or-fs-mutation",
    "production-exposure",
    "scope-change",
    "money",
    "credentials-secrets",
    "legal-compliance-privacy-posture",
    "irreversible-external-mutation",
    "public-commitment",
)

# The refusal reason for a cause outside that vocabulary. Distinct from every `A_*` reason because it
# is a statement about the CAUSE, not about the person or their grant — conflating them would tell a
# caller their grant was wrong when their cause was.
AC_UNKNOWN_CAUSE = "unknown-authority-class-cause"


class AuthorityCauseRefused(RuntimeError):
    """SPEC-0191 §5a — the named cause is not in the closed authority-class vocabulary."""

    def __init__(self, message: str, cause: str):
        super().__init__(message)
        self.cause = cause
        self.reason = AC_UNKNOWN_CAUSE


def decide_authority_class_cause(*, cause, project, argv, env, session_identity, registry_text,
                                 carrier) -> dict:
    """MAY this session decide AUTHORITY-class `cause` on `project`? — the SPEC-0191 §5a gate.

    Returns the admitting decision dict (with `cause` recorded) or raises. It ADDS NO identity path,
    no second parse and no second carrier read: admission is delegated WHOLE to `authorize`, so
    SPEC-0169 rule 3 (server-issued identity, caller-supplied actor input refused) and rule 4 (fail
    closed in both directions — an unreadable or empty grant set REFUSES) govern here exactly as they
    govern a deploy. Takes no actor/identity parameter, for the same structural reason `authorize`
    takes none: there is no argument through which a caller could supply a name.

    THE THREE REFUSALS SPEC-0191 §5a MAKES NORMATIVE, and where each comes from:
      1. a person holding no `decide-authority` row -> `authorize` refuses `no-grant-for-identity`
         or `right-not-held`;
      2. a holder on a project their grant does not name -> `authorize` refuses
         `not-scoped-to-project` (the right is person x project, SPEC-0169 rule 1);
      3. a missing / unreadable / empty grant set -> `authorize` raises the rule-4 refusal.
    A surface exhibiting the admission WITHOUT all three has deleted §5's gate rather than
    conditioning it, which is the exact failure the tripwire's differential exists to catch.

    DECIDING IS NOT DOING. Admission here makes the caller the AUTHORITY for the cause and confers no
    capability whatsoever: `decide-authority` gates no verb (it is absent from `GATED_OPERATIONS`)
    and is not exercisable (`EXERCISABLE_HERE`), so an admitted holder still meets every execution
    gate unchanged. That is SPEC-0169 rule 2's separability, not a courtesy of this function.

    THE CAUSE IS CHECKED FIRST, and positively. An unrecognised cause is refused BEFORE any grant is
    read, so a broken or invented cause can never reach the admission path and be judged by a row
    that was never about it.
    """
    cause = str(cause)
    project = str(project)
    if cause not in AUTHORITY_CLASS_CAUSES:
        raise AuthorityCauseRefused(
            f"REFUSED [{AC_UNKNOWN_CAUSE}]: {cause!r} is not one of the AUTHORITY-class causes "
            f"{list(AUTHORITY_CLASS_CAUSES)} (SPEC-0191 §5). This gate decides only that closed "
            f"class; an unrecognised cause is refused rather than admitted, so a typo or a renamed "
            f"cause denies the decision instead of opening it. If the cause genuinely belongs to the "
            f"class, the vocabulary is part of the spec — widening it is a spec change, not a caller "
            f"argument.",
            cause)
    decision = authorize(right=DECISION_RIGHT, project=project, argv=argv, env=env,
                         session_identity=session_identity, registry_text=registry_text,
                         carrier=carrier)
    decision["cause"] = cause
    return decision


def authorize(*, right, project, argv, env, session_identity, registry_text, carrier) -> dict:
    """THE GATE — the whole SPEC-0169 chain, in the one order that keeps each clause load-bearing.

    (1) `acting_identity` — rules 3+4: caller-supplied actor input REFUSED, then the server-issued
    derivation, then refusal of an identity the server did not issue. (2) `bind_identity_to_grants`
    — rule 4's grant-set leg: unreadable / malformed / empty / no-grant-for-this-identity are
    refusals, never an open door. (3) `decide_authorization` — rules 1+2 over the resulting rows.

    Takes NO actor/identity parameter — the same structural placement obligation T-10760 established:
    there is no argument through which a caller could supply a name, so a call site cannot pass one
    even by mistake. The CARRIER and the host registry stay installation PARAMETERS (rule 10).

    Returns the decision dict on a permit. Raises `ActorInputRefused` (rule 3), `IdentityRefused`
    (rule 4, identity leg), `GrantSetRefused` (rule 4, grant-set leg) or `AuthorizationRefused`
    (rules 1-2 + 4) — four distinguishable refusals, because "you may not assert who you are", "the
    server does not know you", "the server's grant state says nothing about you" and "you do not
    hold this right" are different facts, and a caller that conflated them could act on none.

    Writes NOTHING: rule 5 is unaffected by this card, and the module still has exactly one named
    carrier-write path (`refuse_carrier_write`), which still always refuses.
    """
    derived = acting_identity(argv=argv, env=env, session_identity=session_identity,
                              registry_text=registry_text, operation=f"{right} on {project}")
    identity = derived["identity"]
    try:
        rows = bind_identity_to_grants(identity, carrier)
    except GrantSetRefused as exc:
        if exc.reason != GS_NO_GRANT_FOR_IDENTITY:
            # INSTALLATION-level absence — the carrier is unreadable, or declares no grant at all.
            # That is rule 4's own refusal and it stays one: a misconfigured installation denies
            # work, and calling it "not authorized" would read as a statement about the PERSON.
            raise
        # PER-PERSON absence. The grant set is readable and populated; it simply does not name this
        # identity. That is an AUTHORIZATION outcome, so it is decided here rather than left as the
        # grant-set refusal — which is what makes a REVOCATION provable (rule 7): after a name is
        # removed the same request reports `no-grant-for-identity` ABOUT THAT NAME, while a bystander
        # still passes, so the flip cannot be confused with the carrier having emptied.
        rows = []
    decision = decide_authorization(rows, identity, project, right)
    decision["identity_source"] = derived["source"]
    if not decision["permitted"]:
        raise AuthorizationRefused(_authorization_refusal_message(decision), decision)
    return decision


def _authorization_refusal_message(decision: dict) -> str:
    """The refusal text — names the clause, the facts, and an applicable route (verb-design §5(d))."""
    who, project, right = decision["identity"], decision["project"], decision["right"]
    held = ", ".join(decision["rights_held"]) or "none"
    detail = {
        A_UNKNOWN_RIGHT: (
            f"{right!r} is not one of the separately-grantable rights {list(RIGHTS)} — SPEC-0169 "
            f"rule 2 (the set is CLOSED; adding a fifth right is a spec change, not a carrier edit)"),
        A_NO_GRANT_FOR_IDENTITY: (
            f"the grant set names no (person, project, rights) triple for {who!r} — SPEC-0169 rule 1 "
            f"(a grant is explicit; being the owner, or anyone else, grants nothing by itself) with "
            f"rule 4 (fail closed)"),
        A_NOT_SCOPED_TO_PROJECT: (
            f"{who!r} holds grants, but none on project {project!r} — SPEC-0169 rule 1 (the grant "
            f"names its PROJECT explicitly) with rule 4"),
        A_RIGHT_NOT_HELD: (
            f"{who!r} holds [{held}] on project {project!r}, which does not include {right!r} — "
            f"SPEC-0169 rule 2: the rights are SEPARATELY grantable because their blast radius "
            f"differs, so holding one decides nothing about another"),
    }[decision["reason"]]
    # SPEC-0191 §5a — THE REFUSAL MUST NAME ITS REMEDY. When the refused right is the DECISION right,
    # the reader is a session that just hit an AUTHORITY-class stop, and a bare "not authorized"
    # sends them off asking for a BROADER grant — the unbounded-permission shape the 2026-08-20
    # restriction record warns against (`lessons/a-refusal-remedy-must-name-which-locus-it-repairs`:
    # a prescribed remedy must name WHICH locus it repairs). So the message names the locus exactly:
    # the cause class, the right, the project, and who may write it.
    #
    # ONE COMPOSED MESSAGE, never a specific diagnosis printed above a generic tail that contradicts
    # it (`lessons/carving-an-exception-into-a-fail-closed-gate` §2) — the locus clause is INSERTED
    # into the single sentence below, not appended after a competing conclusion.
    locus = ""
    if right == DECISION_RIGHT:
        locus = (
            f"This is an AUTHORITY-class cause (SPEC-0191 §5 — data deletion / destructive DB or FS "
            f"mutation / production exposure / scope change / money / credentials-secrets / legal-"
            f"compliance-privacy posture / irreversible external mutations / public commitments), so "
            f"it needs an AUTHORITY, and {DECISION_RIGHT!r} ON PROJECT {project!r} is the right that "
            f"carries it (SPEC-0191 §5a). No auditor verdict substitutes for it, and no other right "
            f"— broader or narrower — reaches it. "
        )
    return (
        f"NOT AUTHORIZED [{decision['reason']}]: {detail}. "
        f"{locus}"
        f"Route: `bin/yitc-v2 grants report` shows the grant state this decision read; granting "
        f"{who!r} {right!r} on {project!r} is an OWNER action (rule 5 — separation of duties), never "
        f"something this system can do for itself or a caller can assert."
    )


def cmd_grants_authorize(args, *, argv, env, session_identity, registry_text, default_carrier,
                         append_event, out=print) -> int:
    """`grants authorize --right R --project P [--carrier PATH] [--json]` — READ-ONLY inspection of
    the authorization decision (SPEC-0169 rule 6).

    Rule 6 obliges fail-closed AUTHORIZATION and fixture-based grant/revoke PROBES to exist IN OUR
    OWN CODE — a contract whose only artifact is documentation telling the owner to edit a carrier
    correctly does not satisfy the spec. This verb is that surface: it runs the SAME `authorize` a
    gated operation would, and REPORTS the verdict instead of performing anything. Wiring a gated
    operation to CALL it is the policy-switch card (T-10765), deliberately not this one.

    `--carrier` is what makes the probes fixture-based (the same installation-parameter knob
    `grants report` carries): the live carrier is owner-written and may be empty or half-written at
    any moment, so a probe that depended on it would be measuring the owner's typing, not the code.

    Exit codes are LOUD (SPEC-0165), continuing the `grants identity` numbering: 0 permitted ·
    2 caller-supplied actor input refused · 3 identity refused (missing / unmapped) · 4 grant-set
    refused at INSTALLATION level (the carrier is unreadable, or declares no grant at all) ·
    5 NOT AUTHORIZED (the decision refused — unknown right, not scoped to the project, right not
    held, or no grant naming this identity). 5 is distinct from 4 on purpose: "nothing is configured
    here" is a statement about the installation, "you do not hold this" is a statement about the
    person, and a revocation produces the second — which is what makes it provable (rule 7).

    `--cause` (SPEC-0191 §5a, T-11684) asks the DOCTRINE question instead: may this session DECIDE
    that AUTHORITY-class cause on this project? It routes through `decide_authority_class_cause`,
    which checks the cause against the closed §5 vocabulary FIRST and then delegates admission to the
    same `authorize` above, so rules 3-4 govern identically. Exit 6 is its own: a malformed REQUEST
    (an unrecognised cause, both flags, or neither) — distinct from 5, because "that is not a cause
    I decide" and "you do not hold this" are different facts and a caller acting on the wrong one
    would ask the owner for a grant that was never the problem.
    """
    carrier = getattr(args, "carrier", None) or default_carrier
    as_json = getattr(args, "json", False)
    right = getattr(args, "right", None)
    project = getattr(args, "project", None)
    # SPEC-0191 §5a — `--cause` switches this verb from the RIGHT question ("does this person hold
    # X here") to the DOCTRINE question ("may this session decide this AUTHORITY-class cause here").
    # The two are different questions and the second is the one §5 asks, so the flag routes through
    # `decide_authority_class_cause` rather than layering a second meaning onto `--right`.
    cause = getattr(args, "cause", None)

    def _refused(kind: str, code: int, message: str, identity=None, reason=None) -> int:
        append_event("authorization_refused", None, {
            "kind": kind, "reason": reason, "identity": identity, "project": project,
            "right": right, "cause": cause, "operation": "grants authorize",
            "spec": "SPEC-0191" if cause else "SPEC-0169",
        })
        if as_json:
            out(json.dumps({"permitted": False, "refused": kind, "reason": reason,
                            "identity": identity, "project": project, "right": right,
                            "cause": cause,
                            "carrier": str(carrier), "detail": message}, indent=2, sort_keys=True))
        else:
            out(f"authorization: REFUSED [{kind}]\n  {message}")
        return code

    # FAIL CLOSED ON THE ARGUMENTS THEMSELVES (SPEC-0169 rule 4's discipline applied one step
    # earlier). Exactly one question may be asked per invocation: neither flag leaves the verb with
    # no question, and both leave it with two whose answers can differ. Either is refused rather than
    # resolved to a guess — a guess here would silently answer the RIGHT question while the caller
    # believed they had asked the AUTHORITY one.
    if cause and right:
        # REFUSED whatever `right` says — INCLUDING `--right decide-authority`, which looks harmless
        # and is the reason this arm is unconditional. `--help` promises EXACTLY ONE of the two, and a
        # flag combination the help forbids but the code quietly accepts is a contract the next reader
        # will rely on and the next change will break. It is also not redundant: the two flags ask
        # DIFFERENT questions — "is this right held" vs "may this AUTHORITY-class cause be decided" —
        # and the second additionally validates the cause against the closed §5 vocabulary. Honouring
        # both would have to silently pick one answer.
        return _refused("bad-request", 6,
                        f"--cause and --right cannot be combined: they ask DIFFERENT questions, and "
                        f"exactly one may be asked per invocation. --cause {cause!r} asks whether this "
                        f"session may DECIDE that AUTHORITY-class cause (SPEC-0191 §5a; decided by "
                        f"{DECISION_RIGHT!r}, and the cause is checked against the closed §5 "
                        f"vocabulary first); --right {right!r} asks whether that right is held. Drop "
                        f"--right to decide the cause, or drop --cause to ask about the right.")
    if not cause and not right:
        return _refused("bad-request", 6,
                        "neither --right nor --cause was given, so there is no question to decide. "
                        "Pass --right <right> to ask whether a right is held, or --cause <cause> to "
                        "ask whether this session may decide an AUTHORITY-class cause (SPEC-0191 §5a).")
    if cause:
        right = DECISION_RIGHT

    try:
        if cause:
            decision = decide_authority_class_cause(
                cause=cause, project=project, argv=argv, env=env,
                session_identity=session_identity, registry_text=registry_text, carrier=carrier)
        else:
            decision = authorize(right=right, project=project, argv=argv, env=env,
                                 session_identity=session_identity, registry_text=registry_text,
                                 carrier=carrier)
    except AuthorityCauseRefused as exc:
        # The cause is not in the closed vocabulary — a statement about the CAUSE, not the person,
        # so it gets its own kind and exit code rather than reading as "you are not authorized".
        return _refused("unknown-cause", 6, str(exc), reason=exc.reason)
    except ActorInputRefused as exc:
        return _refused("caller-supplied-actor", 2, str(exc))
    except GrantSetRefused as exc:
        # Ordered BEFORE the IdentityRefused arm — it is a subclass, so a broader arm first would
        # swallow it and collapse exit 4 into 3.
        return _refused("grant-set", 4, str(exc))
    except IdentityRefused as exc:
        return _refused("identity", 3, str(exc))
    except AuthorizationRefused as exc:
        return _refused("not-authorized", 5, str(exc),
                        identity=exc.decision["identity"], reason=exc.decision["reason"])

    append_event("authorization_decided", None, {
        "permitted": True, "reason": decision["reason"], "identity": decision["identity"],
        "identity_source": decision["identity_source"], "project": project, "right": right,
        "cause": cause,
        "rights_held": decision["rights_held"], "operation": "grants authorize",
        "spec": "SPEC-0191" if cause else "SPEC-0169",
    })
    if as_json:
        out(json.dumps({**decision, "carrier": str(carrier)}, indent=2, sort_keys=True))
    else:
        if cause:
            out(f"authorization: PERMITTED — {decision['identity']} may DECIDE the AUTHORITY-class "
                f"cause {cause!r} on {project} (SPEC-0191 §5a)")
            out(f"  this is AUTHORITY, not capability: {DECISION_RIGHT!r} confers no execution "
                f"(SPEC-0169 rule 2) — every execution gate still applies unchanged")
        else:
            out(f"authorization: PERMITTED — {decision['identity']} may {right} on {project}")
        out(f"  identity: server-issued (SPEC-0169 rule 3; no caller input accepted)")
        out(f"  rights held on {project}: {', '.join(decision['rights_held'])}")
        out("  read-only: this verb performed no operation and wrote nothing to the carrier (rule 5)")
    return 0


def intent_fact_tension(intent_raw, classification: dict) -> list:
    """Where the carrier's restrictive INTENT and the measured FACT disagree, name the disagreement.

    Returns a list of `{key, value, note}` — empty when there is no tension. A tension exists only
    when BOTH a restrictive-intent marker is present AND an escalation path was measured, i.e. the
    carrier means to hold someone back while the host says they cannot be held back.

    This is NOT a reach declaration and never becomes one: it does not feed `classify_reach`, does
    not feed `compare_reach`, and does not move the mismatch count or the exit code. Rule 8 makes a
    label-derived reach a false claim AND makes this disagreement reportable — both at once, which is
    exactly why the label is read here and nowhere else.
    """
    if not (intent_raw and classification.get("escalation_paths_present")):
        return []
    tensions = []
    for key in INTENT_RESTRICTION_KEYS:
        if key not in intent_raw:
            continue
        value = intent_raw[key]
        haystack = str(value).lower()
        if not any(marker in haystack for marker in INTENT_RESTRICTIVE_MARKERS):
            continue
        tensions.append({
            "key": key,
            "value": value,
            "note": (f"the carrier's `{key}: {value!r}` states a RESTRICTIVE INTENT, but this actor "
                     f"MEASURES escalation-capable — the label states intent, the host states fact, "
                     f"and the fact wins (rule 8). This is reported, not resolved: it is neither a "
                     f"reach declaration nor a defect in the label, and nothing here narrows anyone's "
                     f"privileges or edits the carrier."),
        })
    return tensions


def reach_report(carrier, *, resolve_groups=None) -> dict:
    """Per-actor reach report: what the carrier DECLARES vs what the host MEASURES (rule 8, probe V9).

    Returns `{carrier, readable, error, actors, counts}`. Every actor row carries `declared`,
    `declares_reach`, `reach`, `source`, `comparison`, `basis`, `certain`, `uncertainty`,
    `escalation_paths` and `groups` — so a reader can see not only the verdict but what it rests on.

    Read-only end to end: the carrier is read, the host's group database is read, and nothing is
    written anywhere. The mismatch is REPORTED; acting on it is the owner's (rule 5).
    """
    state = read_grant_state(carrier)
    report = {
        "carrier": state.get("carrier"),
        "readable": bool(state.get("readable")) and not state.get("error"),
        "error": state.get("error"),
        "actors": [],
        "counts": {R_MATCH: 0, R_MISMATCH: 0, R_UNDECLARED: 0,
                   R_UNDETERMINABLE: 0, R_DECLARED_UNKNOWN_VALUE: 0},
        "note": REACH_INTERPRETATION_NOTE,
    }
    if not report["readable"]:
        return report

    for person, entry in sorted((state.get("people") or {}).items()):
        measurement = measure_escalation_capability(person, resolve_groups=resolve_groups)
        classification = classify_reach(measurement)
        declared = entry.get("reach_raw") if entry.get("declares_reach") else None
        comparison = compare_reach(declared, classification)
        report["counts"][comparison] = report["counts"].get(comparison, 0) + 1
        report["actors"].append({
            "actor": person,
            # What the carrier SAYS — `None` means it says nothing, which is a fact about the
            # carrier, never a licence to read our inference back as its statement.
            "declared": None if declared is None else str(declared),
            "declares_reach": bool(entry.get("declares_reach")),
            "reach": classification["reach"],
            "source": SOURCE_DECLARED if entry.get("declares_reach") else SOURCE_INFERRED,
            "comparison": comparison,
            "basis": classification["basis"],
            "certain": classification["certain"],
            "uncertainty": classification["uncertainty"],
            "escalation_paths": measurement["escalation_paths"],
            "groups": measurement["groups"],
            "resolved": measurement["resolved"],
            # A SEPARATE channel from `comparison` — reportable per rule 8, but never a declaration
            # and never counted as a mismatch (see `intent_fact_tension`).
            "intent_tension": intent_fact_tension(entry.get("intent_raw"), classification),
        })
    report["intent_tension_actors"] = sorted(
        r["actor"] for r in report["actors"] if r["intent_tension"])
    return report


def render_reach_report(report: dict) -> str:
    """Human rendering of a reach report. No secret is echoed — a row names a person, their groups
    and a reach, and the carrier holds no credential (SPEC-0169 §Parameters)."""
    lines = [f"actor reach vs SPEC-0169 rule 8: {report['carrier']}"]
    if not report["readable"]:
        lines.append(f"  CARRIER UNREADABLE — {report['error']}")
        lines.append("  no reach is claimed for anyone (an unreadable carrier states nothing)")
        return "\n".join(lines)

    counts = report["counts"]
    lines.append(
        f"  {len(report['actors'])} actor(s): {counts[R_MATCH]} match · "
        f"{counts[R_MISMATCH]} MISMATCH · {counts[R_UNDECLARED]} undeclared (inferred) · "
        f"{counts[R_UNDETERMINABLE]} undeterminable · "
        f"{counts[R_DECLARED_UNKNOWN_VALUE]} declared-unknown-value"
    )
    for row in report["actors"]:
        declared = row["declared"] if row["declares_reach"] else "(none declared)"
        lines.append(f"  {row['actor']}: measured={row['reach']} declared={declared} "
                     f"[{row['comparison']}]")
        lines.append(f"    source: {row['source']}")
        lines.append(f"    basis: {row['basis']}")
        if row["comparison"] == R_MISMATCH:
            lines.append(f"    MISMATCH: the carrier declares {row['declared']!r} but the host "
                         f"measures {row['reach']!r} — THE FACT WINS (rule 8). The declaration is "
                         f"reported wrong, not quietly honoured; correcting it is an OWNER action.")
        elif row["comparison"] == R_UNDECLARED:
            lines.append("    NOTE: the carrier declares NO reach for this actor. The value above is "
                         "this reader's INFERENCE from measured host capability — it is NOT a "
                         "carrier statement, and rule 8 requires reach to be DECLARED, never implied.")
        elif row["comparison"] == R_DECLARED_UNKNOWN_VALUE:
            lines.append(f"    the carrier declares {row['declared']!r}, which is not one of "
                         f"{list(REACHES)} — it states no reach rule 8 recognises.")
        elif row["comparison"] == R_UNDETERMINABLE:
            lines.append("    the host could not be interrogated for this actor, so no reach is "
                         "claimed and no declaration is called wrong.")
        for tension in row["intent_tension"]:
            lines.append(f"    INTENT vs FACT: {tension['note']}")
        if not row["certain"]:
            for gap in row["uncertainty"]:
                lines.append(f"    UNMEASURED: {gap}")
    lines.append(f"  {report['note']}")
    lines.append("  read-only: this report wrote nothing to the carrier and entered no account "
                 "(rule 5)")
    return "\n".join(lines)


def cmd_grants_reach(args, *, default_carrier, append_event, out=print, resolve_groups=None) -> int:
    """`grants reach [--carrier PATH] [--json]` — classify each actor's reach from MEASURED host
    escalation capability and report any disagreement with what the carrier declares (rule 8, V9).

    Exit codes are LOUD (SPEC-0165): 0 no mismatch · 1 at least one declared-vs-measured MISMATCH ·
    2 carrier unreadable. An all-undeclared carrier exits 0 deliberately — that is today's real state
    under rule 5 (the carrier is owner-written), and failing on it would drown the one signal this
    verb exists to make visible. The rows still say, loudly, that their reach is an inference.

    `resolve_groups` is the same injection point `reach_report` carries — the host is a PARAMETER of
    the measurement exactly as the carrier is a parameter of the read, so the exit-code contract can
    be exercised against a fixture host. The host never passes it; the default measures THIS host.
    """
    carrier = getattr(args, "carrier", None) or default_carrier
    report = reach_report(carrier, resolve_groups=resolve_groups)

    counts = report["counts"]
    append_event("grant_reach_reported", None, {
        "carrier": report["carrier"],
        "readable": report["readable"],
        "actor_count": len(report["actors"]),
        # Counts, not group lists: the host's group membership is detail, the disagreement is the
        # claim. `mismatch_actors` is named because a mismatch is exactly what must not stay invisible.
        "counts": counts,
        "mismatch_actors": sorted(r["actor"] for r in report["actors"]
                                  if r["comparison"] == R_MISMATCH),
        "uncertain_actors": sorted(r["actor"] for r in report["actors"] if not r["certain"]),
        "intent_tension_actors": report.get("intent_tension_actors", []),
        "spec": "SPEC-0169",
    })

    if getattr(args, "json", False):
        out(json.dumps(report, indent=2, sort_keys=True))
    else:
        out(render_reach_report(report))

    if not report["readable"]:
        return 2
    return 1 if counts[R_MISMATCH] else 0


def cmd_grants_report(args, *, default_carrier, append_event, out=print,
                      gitconfig_for=None, stat_path=None) -> int:
    """`grants report [--carrier PATH] [--json]` — read-only validation + inspection of live grant
    state (SPEC-0169 rule 6). The carrier defaults to the installation parameter the host passes in
    (`$YITC_REGISTRY` else the server registry); `--carrier` points it at a fixture for a single run.

    Exit codes are LOUD (SPEC-0165): 0 well-formed · 1 not well-formed · 2 carrier unreadable. The
    verb reports; it decides no authorization and it writes nothing but the journal event.
    """
    carrier = getattr(args, "carrier", None) or default_carrier
    state = read_grant_state(carrier)
    report = validate_grant_state(state)
    # Per-collaborator orphaned safe.directory entries (T-11918) — the REMOVAL half of the print the
    # adopt path already does for the ADD. Reported, never reconciled: the write into another user's
    # home stays the human's (SPEC-0111 §1), so this verb stays as read-only as it was.
    orphans = orphan_safe_directory_report(carrier, gitconfig_for=gitconfig_for,
                                           stat_path=stat_path)
    report["orphan_safe_directory"] = orphans
    orphan_people = sorted(r["person"] for r in orphans.get("people", []) if r["orphans"])

    kinds = sorted({p["kind"] for p in report["problems"]})
    append_event("grant_state_reported", None, {
        "carrier": report["carrier"],
        "well_formed": report["well_formed"],
        "grant_count": len(report["grants"]),
        "people_with_grants": report["people_with_grants"],
        "problem_count": len(report["problems"]),
        "problem_kinds": kinds,
        # Counts + the people named, not the paths: a path is detail, the fact that SOMEONE carries a
        # dead exception is the claim. Advisory — it moves no exit code (below).
        "orphan_safe_directory_people": orphan_people,
        "orphan_safe_directory_count": sum(len(r["orphans"]) for r in orphans.get("people", [])),
        "spec": "SPEC-0169",
    })

    if getattr(args, "json", False):
        out(json.dumps(report, indent=2, sort_keys=True))
    else:
        out(render_report(report))

    # The exit contract is UNCHANGED: an orphaned entry is ADVISORY (it is a fact about a
    # collaborator's home, not a defect in the carrier this verb validates), so it never turns a
    # well-formed carrier into a nonzero exit.
    if P_CARRIER_UNREADABLE in kinds or P_CARRIER_MALFORMED in kinds:
        return 2
    return 0 if report["well_formed"] else 1


# ══ THE ATTRIBUTABLE TRAIL — SPEC-0169 rule 9 (T-10763) ══════════════════════════════════════════
#
# FIFTH HALF. Rule 9 is UNCONDITIONAL, not a fallback for the advisory case: every exercise of a
# rule-2 right — PERMITTED and REFUSED alike — is recorded with which identity acted, which right,
# on which project, when, and under which grant. Under ENFORCEMENT reach the record explains a
# refusal; under ADVISORY reach (a trusted developer holding sudo, where every refusal aimed at them
# is bypassable by them) it is the ONLY property that survives, and it is what makes that lane
# ACCOUNTABLE rather than merely trusted. A contract satisfying rules 1-8 that recorded nothing would
# leave the escalation-capable actor entirely unobserved.
#
# THE TRAIL IS THE JOURNAL — there is no second store. A trail record is ONE `right_exercised` event
# on the existing append-only journal, written through the existing single emission path. A dedicated
# trail file would be a parallel append-only store with its own writer, reader and format — exactly
# what CHARTER §Principle 5 ("one journal") and the sibling scope bound (no new store / no new
# journal / no new parser) forbid, and what CHARTER §P1 filter 2 answers with "a view over the
# existing entity, not a new entity".
#
# ─── WHAT THIS MAY CLAIM, AND WHAT IT MAY NOT (rule 9's interpretation note — do NOT delete or
# soften this, and do NOT let a later surface re-inflate it) ──────────────────────────────────────
# What is delivered is TAMPER-EVIDENCE against a named threat model, plus an ANCHOR held OUTSIDE the
# trail it anchors. It is NOT tamper-PROOFNESS against privileged host control: an actor able to
# rewrite a record, recompute its digest and every following link — or simply to truncate — leaves a
# consistent file, and nothing inside a single file closes that. Non-repudiation holds only SO LONG
# AS the external anchor is trusted; the anchor here rides the same journal, so it is subject to the
# same control, and its custody is external only to the extent the journal's own custody is (it is
# committed and union-merged, so an after-the-fact rewrite must survive git history too — a real but
# BOUNDED strengthening, never a proof). This is rule 8's discipline on a second axis: state what the
# mechanism may CLAIM. Every surface that speaks about the trail — this docstring, `grants trail`'s
# output, the ledger rows — says exactly this and no more.
#
# WHY "OUTSIDE THE TRAIL" AND NOT "OUTSIDE THE FILE". Rule 9 asks for an anchor held outside THE
# TRAIL IT ANCHORS. With the trail riding the journal there is no second file to hold it, so the
# anchor is a DIFFERENT EVENT TYPE (`grant_trail_anchored`) which is never a trail record and is
# never covered by the chain it digests — outside the trail, inside the journal. The trial prototype
# that proved this shape had its own trail file and could put the anchor in the journal; the honest
# kernel translation is the sentence above, and the strength difference is stated rather than glossed
# (deviation `trail-rides-journal-vs-anchor-outside-trail-file`).

# The two event types. They are DISJOINT by construction: `read_trail` selects the first and the
# anchor is the second, so an anchor can never be mistaken for a record it anchors.
TRAIL_EVENT = "right_exercised"
TRAIL_ANCHOR_EVENT = "grant_trail_anchored"

# The record fields the per-record digest covers, in a fixed set. `self_sha256` is EXCLUDED — a
# digest cannot cover itself — and so is anything the writer does not control.
TRAIL_DIGEST_FIELDS = (
    "attribution", "grant", "identity", "outcome", "prev", "project", "reason", "right", "ts",
)

# The two exercise outcomes. Both are RECORDED: a trail that held only permits would explain nothing
# about a refusal, which is precisely what rule 9 says the record is for under enforcement reach.
X_PERMITTED = "permitted"
X_REFUSED = "refused"

# Verification finding kinds. Each names WHAT was detected, so a caller (and a test) asserts on the
# token rather than on prose — the same reason the authorization refusal reasons are tokens.
F_RECORD_DIGEST = "record-digest-mismatch"      # a record's content no longer hashes to its own digest
F_BROKEN_LINK = "broken-link"                   # a `prev` naming no digest present before it
F_ANCHOR_PREFIX = "anchor-prefix-mismatch"      # the prefix an anchor anchored has been rewritten
F_ANCHOR_TRUNCATED = "anchor-truncated"         # the trail now holds fewer records than an anchor saw
F_UNPARSABLE_LINE = "unparsable-journal-line"   # reported, never fatal — the reader reports, the
                                                # verifier judges (`lessons/fail-closed-belongs-to-
                                                # the-reader-not-the-parser.md`)

TRAIL_CLAIM_NOTE = (
    "tamper-EVIDENCE against a named threat model, plus an anchor held outside the trail it anchors "
    "— NOT tamper-proofness: an actor with privileged host control can rewrite a record, recompute "
    "its digest and every following link, or truncate, and leave a consistent file. Non-repudiation "
    "holds only so long as that anchor is trusted (SPEC-0169 rule 9 interpretation note)."
)


class TrailWriteRefused(RuntimeError):
    """Rule 9 fail-closed — the exercise's record could not be written, so the exercise is REFUSED.

    NOT a warning and NOT a degraded mode. An exercise performed while its record failed to land is
    exactly the unobserved action rule 9 exists to make impossible, so the failure to record is
    promoted into a refusal of the thing being recorded. There is no carve-out here and adding one
    would invalidate the rule rather than extend it (`lessons/carving-an-exception-into-a-fail-
    closed-gate.md` — the discriminator would be the whole risk).
    """


def _canonical_record(record: dict) -> str:
    """The bytes a record digest is taken over — fixed field set, sorted keys, fixed separators.

    Canonicalization is the whole load-bearing part of a digest: two readers must agree byte-for-byte
    on what was hashed, or an honest record reads as tampered. Unknown/extra keys are EXCLUDED rather
    than hashed, so a later additive field cannot retroactively invalidate every existing record.
    """
    covered = {k: record.get(k) for k in TRAIL_DIGEST_FIELDS}
    return json.dumps(covered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_digest(record: dict) -> str:
    """sha256 over `_canonical_record` — the PER-RECORD digest, which is what covers the TAIL.

    A forward-only `prev` chain cannot see an in-place edit of the LAST record: there is nothing
    after it to disagree. The per-record digest covers every record including the last, which is why
    both exist and why neither is redundant.
    """
    import hashlib  # noqa: PLC0415 — lazy, keeps this module a stdlib+yaml leaf at import time
    return hashlib.sha256(_canonical_record(record).encode("utf-8")).hexdigest()


def _chain_digest(digests) -> str:
    """The prefix digest an ANCHOR records — sha256 over the ordered per-record digests."""
    import hashlib  # noqa: PLC0415
    return hashlib.sha256("\n".join(digests).encode("utf-8")).hexdigest()


def _read_journal(events_path):
    """(trail records, anchor observations, unparsable-line count) from the journal, in file order.

    FAITHFUL, judging nothing (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): a line
    that is not JSON is COUNTED and skipped, never raised. A journal is append-only and union-merged
    by concurrent writers, so a torn or foreign line is a finding for the verifier to weigh — a
    reader that died on it would make the whole trail unreadable because of one bad byte, which is
    the opposite of what an audit trail is for.
    """
    records: list[dict] = []
    anchors: list[dict] = []
    unparsable = 0
    for line in journal_mod.segment_lines(events_path, errors="replace"):  # T-11444: segment-aware fold (SPEC-0190 r4)
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            unparsable += 1
            continue
        if not isinstance(event, dict):
            unparsable += 1
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        if event.get("type") == TRAIL_EVENT:
            records.append(data)
        elif event.get("type") == TRAIL_ANCHOR_EVENT:
            anchors.append(data)
    return records, anchors, unparsable


def read_trail(events_path) -> list[dict]:
    """The trail — every `right_exercised` record in journal order. Empty when the journal is absent."""
    try:
        records, _anchors, _bad = _read_journal(events_path)
    except OSError:
        return []
    return records


def head_digest(events_path) -> dict:
    """THE ANCHOR VALUE — `{count, head, digest}` over the trail as it stands NOW.

    `head` is the last record's own digest (what the next record links to via `prev`); `digest` is
    the chain digest over every record's digest in order; `count` is how many records that covers.
    An anchor observation is this triple JOURNALLED — and it is a statement about a PREFIX AT AN
    INSTANT, never a claim about the head forever (see `verify_trail_integrity`).
    """
    records = read_trail(events_path)
    digests = [str(r.get("self_sha256") or "") for r in records]
    return {
        "count": len(records),
        "head": digests[-1] if digests else None,
        "digest": _chain_digest(digests),
    }


def append_trail_record(*, right, project, identity, attribution, grant, outcome, reason, ts,
                        events_path, append_event) -> dict:
    """THE ONE RECORD WRITER — chains, digests, appends, and READS THE RECORD BACK.

    Rule 9's attribution set is the whole point, so every field is written on every record: which
    identity acted (`identity`), which right (`right`), on which project (`project`), when (`ts`),
    and under which grant (`grant` — the matched (person, project, rights) triple, null on a
    refusal, since a refusal relied on no grant). `attribution` carries what the process could
    attribute WITHOUT asserting an identity — needed for the hard case rule 9 must still cover: a
    refusal that fires BEFORE identity derivation (rule 3 refuses caller-supplied actor input ahead
    of any derivation) records the attribution it does have rather than nothing. It is deliberately
    a SEPARATE field from `identity`: merging them would let an un-derived, un-verified process fact
    be read as a server-issued identity, which is the very substitution rule 3 exists to refuse.

    APPEND-ONLY, NEVER REWRITE (rule 5 applied to the trail as to the grants): this function only
    ever appends. There is no update path, no rewrite path and no delete path in this module — the
    acting component may append its own entry and can do nothing else to the trail.

    FAIL-CLOSED: the record is read back and its digest re-verified after the append; any failure —
    the write raising, the record not being found, its digest disagreeing — raises
    `TrailWriteRefused`, which the caller turns into a refusal of the exercise itself.
    """
    prior = head_digest(events_path)
    record = {
        "right": str(right) if right is not None else None,
        "project": str(project) if project is not None else None,
        "identity": str(identity) if identity else None,
        "attribution": str(attribution) if attribution else None,
        "grant": grant,
        "outcome": outcome,
        "reason": reason,
        "ts": ts,
        "prev": prior["head"],
    }
    record["self_sha256"] = record_digest(record)
    record["spec"] = "SPEC-0169"
    try:
        append_event(TRAIL_EVENT, None, dict(record))
    except Exception as exc:                                   # noqa: BLE001 — every failure is one
        raise TrailWriteRefused(
            f"EXERCISE REFUSED: its trail record could not be written to {events_path} ({exc}) — "
            f"SPEC-0169 rule 9: every exercise of a right is RECORDED, so an exercise that cannot be "
            f"recorded is refused rather than performed unrecorded. "
            f"Route: make the journal writable and re-run; nothing was performed."
        ) from exc
    written = read_trail(events_path)
    if not written or written[-1].get("self_sha256") != record["self_sha256"]:
        raise TrailWriteRefused(
            f"EXERCISE REFUSED: the trail record was not readable back from {events_path} after the "
            f"append — SPEC-0169 rule 9 (an exercise that cannot be recorded is refused). "
            f"Route: run `bin/yitc-v2 grants trail --verify` to see the trail this refusal read."
        )
    return record


def anchor_trail(*, events_path, append_event, note: str = "") -> dict:
    """Journal an ANCHOR — the head digest of the trail, held OUTSIDE the trail it anchors.

    Emits `grant_trail_anchored`, which is NOT a `right_exercised` record and is therefore never
    covered by the chain it digests. That is rule 9's "an anchor held outside the trail it anchors",
    translated to a trail that rides the journal (see the section header for why, and for the exact
    limit this does and does not buy — `TRAIL_CLAIM_NOTE`).
    """
    observation = head_digest(events_path)
    payload = {**observation, "note": note or TRAIL_CLAIM_NOTE, "spec": "SPEC-0169"}
    append_event(TRAIL_ANCHOR_EVENT, None, payload)
    return observation


def verify_trail_integrity(events_path) -> dict:
    """TAMPER-EVIDENCE — recompute every digest, resolve every link, check every anchored PREFIX.

    Returns `{ok, count, head, anchors, findings, unparsable}`; each finding is
    `{kind, index, ts, identity, detail}` so it NAMES the record it is about.

    THREE INDEPENDENT CHECKS, each covering what the others cannot:
      `record-digest-mismatch` — every record is re-digested from its own content. This is the check
        that covers the TAIL: a forward-only chain has nothing after the last record to disagree
        with an edit of it.
      `broken-link` — every non-null `prev` must name the digest of SOME record appearing before it.
        Resolved against the SET of earlier digests, never a positional predecessor: `events.jsonl`
        is appended by concurrent worktrees and UNION-MERGED at `land`, so a strict positional chain
        would report tampering after an ordinary merge — and a check that cries wolf gets disabled.
        It still catches what it is for: remove or substitute a record and some later `prev` names a
        digest that is no longer there.
      `anchor-prefix-mismatch` / `anchor-truncated` — each anchor is checked against THE PREFIX IT
        ANCHORED, never against the current tail: recompute the chain digest over the first `count`
        records as they stand now and compare. Ordinary appends after an anchor are expected and
        verify CLEAN — an anchor is a statement about a prefix at an instant, not a claim about the
        head forever; requiring the current head to equal a stale anchor would make every subsequent
        legitimate exercise read as tampering unless each one re-anchored (audit-pre finding,
        absorbed). This is the check that sees TRUNCATION, which nothing inside the record set can.

    HONEST BOUND: records appended after the last anchor are covered by their own digests and links
    only, not by an anchor, until the next anchor is taken — and the whole mechanism is
    tamper-EVIDENCE, never tamper-proofness (`TRAIL_CLAIM_NOTE`).
    """
    try:
        records, anchors, unparsable = _read_journal(events_path)
    except OSError as exc:
        return {"ok": False, "count": 0, "head": None, "anchors": 0, "unparsable": 0,
                "findings": [{"kind": "journal-unreadable", "index": None, "ts": None,
                              "identity": None, "detail": f"{events_path}: {exc}"}]}

    findings: list[dict] = []
    if unparsable:
        findings.append({"kind": F_UNPARSABLE_LINE, "index": None, "ts": None, "identity": None,
                         "detail": f"{unparsable} journal line(s) were not parsable JSON"})

    digests: list[str] = []
    seen: set[str] = set()
    for i, rec in enumerate(records):
        stored = str(rec.get("self_sha256") or "")
        actual = record_digest(rec)
        digests.append(stored)
        if stored != actual:
            findings.append({
                "kind": F_RECORD_DIGEST, "index": i, "ts": rec.get("ts"),
                "identity": rec.get("identity"),
                "detail": (f"record {i} ({rec.get('outcome')} {rec.get('right')} on "
                           f"{rec.get('project')}) states {stored or '<none>'} but its content "
                           f"hashes to {actual} — it was edited in place after it was written"),
            })
        prev = rec.get("prev")
        if prev and prev not in seen:
            findings.append({
                "kind": F_BROKEN_LINK, "index": i, "ts": rec.get("ts"),
                "identity": rec.get("identity"),
                "detail": (f"record {i} links back to {prev}, which is not the digest of any record "
                           f"before it — a record was removed or substituted"),
            })
        if stored:
            seen.add(stored)

    for anchor in anchors:
        try:
            anchored = int(anchor.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if anchored > len(records):
            findings.append({
                "kind": F_ANCHOR_TRUNCATED, "index": len(records), "ts": anchor.get("ts"),
                "identity": None,
                "detail": (f"an anchor observed {anchored} record(s); the trail now holds "
                           f"{len(records)} — records below that anchor were truncated"),
            })
            continue
        if _chain_digest(digests[:anchored]) != str(anchor.get("digest") or ""):
            findings.append({
                "kind": F_ANCHOR_PREFIX, "index": anchored - 1 if anchored else 0,
                "ts": anchor.get("ts"), "identity": None,
                "detail": (f"the first {anchored} record(s) no longer digest to the value an anchor "
                           f"recorded for them — that anchored prefix was rewritten"),
            })

    return {
        "ok": not findings,
        "count": len(records),
        "head": digests[-1] if digests else None,
        "anchors": len(anchors),
        "unparsable": unparsable,
        "findings": findings,
    }


def exercise_right(*, right, project, argv, env, session_identity, registry_text, carrier,
                   attribution, ts, events_path, append_event) -> dict:
    """THE RECORDED GATE — `authorize`, with rule 9's record written for EVERY outcome.

    Composes the landed chain (rule 3 caller-input refusal -> server-issued derivation -> rule 4
    identity + grant-set refusals -> rules 1+2 decision) and records the outcome — permitted AND
    each of the four distinguishable refusal classes. Both directions are recorded because rule 9
    says every exercise, and because a refusal is the case the record most needs to explain.

    THE HARD CASE, COVERED: a rule-3 refusal fires BEFORE any identity derivation, so there is no
    identity to attribute it to. That record is still written, with `identity: null` plus whatever
    `attribution` the process could supply — the attribution it DOES have rather than nothing.

    FAIL-CLOSED ORDERING: the record is written BEFORE a permit is returned, and `TrailWriteRefused`
    propagates unchanged, so an exercise whose record cannot be written is REFUSED rather than
    performed unrecorded. A refusal whose record cannot be written also raises — the caller was
    going to be refused anyway, and the stronger error is the honest one.

    Takes NO actor/identity parameter (the T-10760 structural placement obligation, unchanged) and
    writes nothing to the carrier: `refuse_carrier_write` remains the single named carrier-write
    path and still always refuses (rule 5, which governs the trail exactly as it governs the grants
    — this function appends and has no rewrite path).
    """
    identity = None
    grant = None
    outcome = X_REFUSED
    reason = None
    error: Exception | None = None
    try:
        decision = authorize(right=right, project=project, argv=argv, env=env,
                             session_identity=session_identity, registry_text=registry_text,
                             carrier=carrier)
        identity = decision["identity"]
        grant = decision.get("matched_grant")
        outcome, reason = X_PERMITTED, decision["reason"]
    except ActorInputRefused as exc:
        # BEFORE derivation — no identity exists to name, by design (rule 3 refuses ahead of it).
        reason, error = "caller-supplied-actor", exc
    except GrantSetRefused as exc:
        # The identity WAS derived before this refusal (rule 9 names WHICH identity acted), so it is
        # recorded even on the installation-level branch — see `GrantSetRefused.identity`.
        identity = exc.identity
        reason, error = exc.reason or "grant-set", exc
    except IdentityRefused as exc:
        reason, error = "identity", exc
    except AuthorizationRefused as exc:
        identity = exc.decision["identity"]
        reason, error = exc.decision["reason"], exc

    append_trail_record(right=right, project=project, identity=identity, attribution=attribution,
                        grant=grant, outcome=outcome, reason=reason, ts=ts,
                        events_path=events_path, append_event=append_event)
    if error is not None:
        raise error
    return decision


# ── The read-only inspections (rule 6 keeps the obligation rule 5 removes the write from) ─────────

def render_trail_verification(result: dict) -> str:
    """Human rendering — states the finding set AND the claim bound, never one without the other."""
    lines = [
        f"trail: {result['count']} record(s), {result.get('anchors', 0)} anchor observation(s)",
        f"  head: {result.get('head') or '<empty>'}",
    ]
    if result["ok"]:
        lines.append("  integrity: no tampering detected")
    else:
        lines.append(f"  integrity: {len(result['findings'])} FINDING(S)")
        for f in result["findings"]:
            lines.append(f"    [{f['kind']}] {f['detail']}")
    lines.append(f"  what this claims: {TRAIL_CLAIM_NOTE}")
    return "\n".join(lines)


def cmd_grants_trail(args, *, events_path, append_event, out=print) -> int:
    """`grants trail [--verify] [--anchor] [--json]` — read-only inspection of the rule-9 trail.

    Rule 6 obliges READ-ONLY inspection and reporting of the governed state to exist in our own
    code; this is that surface for the trail. `--anchor` is the one WRITE it performs, and it writes
    an OBSERVATION (`grant_trail_anchored`), never a trail record and never the grant carrier.

    Exit codes are LOUD (SPEC-0165), continuing the sibling numbering: 0 clean · 1 findings (the
    trail shows tampering) · 2 the journal could not be read at all.
    """
    as_json = getattr(args, "json", False)
    if getattr(args, "anchor", False):
        observation = anchor_trail(events_path=events_path, append_event=append_event)
        if as_json:
            out(json.dumps({"anchored": observation, "claim": TRAIL_CLAIM_NOTE},
                           indent=2, sort_keys=True))
        else:
            out(f"anchored: {observation['count']} record(s), digest {observation['digest']}")
            out(f"  held outside the trail it anchors, as a {TRAIL_ANCHOR_EVENT} observation")
            out(f"  what this claims: {TRAIL_CLAIM_NOTE}")
        return 0

    result = verify_trail_integrity(events_path)
    if as_json:
        out(json.dumps({**result, "claim": TRAIL_CLAIM_NOTE}, indent=2, sort_keys=True))
    else:
        out(render_trail_verification(result))
    if any(f["kind"] == "journal-unreadable" for f in result["findings"]):
        return 2
    return 0 if result["ok"] else 1


# The ONE right `grants exercise` may exercise. `dry-run-readonly` is defined by rule 2 as "execute
# the same path with no writes and no production row touched", so exercising it performs nothing —
# which is what lets this verb prove the trail RECORDS a real exercise without this card acquiring
# the ability to deploy or to write production data. Wiring a genuinely gated operation to the gate
# is the POLICY SWITCH (T-10765), deliberately not here.
EXERCISABLE_HERE = "dry-run-readonly"


def cmd_grants_exercise(args, *, argv, env, session_identity, registry_text, default_carrier,
                        attribution, ts, events_path, append_event, out=print) -> int:
    """`grants exercise --project P [--right dry-run-readonly]` — exercise a right THROUGH the gate,
    leaving the rule-9 record.

    This is the adoption surface for the trail (CHARTER §Principle 8: infrastructure closes on
    consumer-read or live-trigger evidence, never on "tests green"). Without it the trail would ship
    provable only against fixtures and never actually fired — which is the gap the proposing plan
    named for V10 (an audit trail "only incidentally suggested by observation metadata").

    Restricted to `EXERCISABLE_HERE`: any other right is refused, naming T-10765 as the owner of
    wiring a real gated operation. The restriction is what keeps this verb from becoming a way to
    perform a privileged action outside the policy switch.

    Exit codes are LOUD (SPEC-0165), continuing the sibling numbering: 0 permitted (and recorded) ·
    2 caller-supplied actor input refused · 3 identity refused · 4 grant-set refused · 5 NOT
    AUTHORIZED · 6 the record could not be written, so the exercise was REFUSED (rule 9 fail-closed).
    """
    carrier = getattr(args, "carrier", None) or default_carrier
    as_json = getattr(args, "json", False)
    project = getattr(args, "project", None)
    right = getattr(args, "right", None) or EXERCISABLE_HERE
    if right != EXERCISABLE_HERE:
        # Exit 7, NOT 2: "this surface does not perform that right" is a statement about the VERB,
        # while 2 is rule 3's caller-supplied-actor refusal. Collapsing them would make a scope
        # boundary indistinguishable from a security refusal in an exit-code contract.
        message = (
            f"exercise REFUSED: this verb exercises only {EXERCISABLE_HERE!r} — the one SPEC-0169 "
            f"rule-2 right defined as no writes and no production row touched. Performing "
            f"{right!r} is a GATED OPERATION; wiring one to the grant gate is the policy switch "
            f"(T-10765), not this surface. Route: `bin/yitc-v2 grants authorize --right {right} "
            f"--project {project}` decides it read-only.")
        if as_json:
            out(json.dumps({"permitted": False, "refused": "right-not-exercisable-here",
                            "right": right, "project": project, "detail": message},
                           indent=2, sort_keys=True))
        else:
            out(message)
        return 7

    def _report(payload: dict, human: str, code: int) -> int:
        if as_json:
            out(json.dumps({**payload, "carrier": str(carrier)}, indent=2, sort_keys=True))
        else:
            out(human)
        return code

    try:
        decision = exercise_right(right=right, project=project, argv=argv, env=env,
                                  session_identity=session_identity, registry_text=registry_text,
                                  carrier=carrier, attribution=attribution, ts=ts,
                                  events_path=events_path, append_event=append_event)
    except TrailWriteRefused as exc:
        return _report({"permitted": False, "refused": "trail-write", "detail": str(exc)},
                       f"exercise: REFUSED [trail-write]\n  {exc}", 6)
    except ActorInputRefused as exc:
        return _report({"permitted": False, "refused": "caller-supplied-actor", "detail": str(exc)},
                       f"exercise: REFUSED [caller-supplied-actor]\n  {exc}", 2)
    except GrantSetRefused as exc:
        return _report({"permitted": False, "refused": "grant-set", "detail": str(exc)},
                       f"exercise: REFUSED [grant-set]\n  {exc}", 4)
    except IdentityRefused as exc:
        return _report({"permitted": False, "refused": "identity", "detail": str(exc)},
                       f"exercise: REFUSED [identity]\n  {exc}", 3)
    except AuthorizationRefused as exc:
        return _report({"permitted": False, "refused": "not-authorized",
                        "reason": exc.decision["reason"], "detail": str(exc)},
                       f"exercise: REFUSED [not-authorized]\n  {exc}", 5)

    return _report(
        {**decision, "recorded": True},
        (f"exercise: {decision['identity']} exercised {right} on {project} — PERMITTED and RECORDED\n"
         f"  the record names identity, right, project, time and the grant relied on (rule 9)\n"
         f"  what the trail claims: {TRAIL_CLAIM_NOTE}"),
        0)


# ══ THE POLICY SWITCH — SPEC-0169 activation (T-10765) ═══════════════════════════════════════════
#
# SIXTH HALF, AND THE LAST. Everything above is a mechanism; this is the moment it becomes
# NORMATIVE. Until this section existed, `GATED_OPERATIONS` bought only rule 3 + the rule-4 identity
# leg: the host derived a server-issued identity for `deploy` and then STOPPED, never asking whether
# that identity HOLDS `deploy-code` on that project, and leaving no rule-9 record. `authorize` and
# `exercise_right` were reachable only through the READ-ONLY inspection verbs. The switch is what
# makes a real gated operation pay them.
#
# WHY THE SWITCH IS GUARDED BY ITS OWN EVIDENCE PATH (the plan's locked build order, step 5: "policy
# activation LAST — activating policy before instrumentation is how a rule becomes a claim"). A bare
# `POLICY_ENABLED = True` cannot express that ordering: it reads true whether or not anything can
# observe an exercise, so it would happily enable a contract whose refusals nothing records. So the
# flip is a CONSTANT plus a PREDICATE, and the predicate REFUSES — loudly, not silently False —
# when the constant is on while any evidence-path capability is missing.
#
# WHY THE CAPABILITIES ARE MEASURED ON THIS MODULE AND NOT ON THE TASK GRAPH. The alternative is to
# read each required card's `status:` at runtime and refuse while one is not `done`. That would put
# lifecycle bookkeeping inside a security gate, make an enforcement decision depend on a YAML edit,
# and be satisfiable by marking a card done without shipping its code — the exact substitution the
# ordering rule exists to prevent. What must exist is the CODE that OBSERVES an exercise, so the
# gate looks for that code, per card, by name.

# THE FLIP. One greppable constant; the card that turns the contract on is the one that changes it.
# `False` here is not a kill switch for an incident (a gate you can turn off under pressure is not a
# gate — `lessons/carving-an-exception-into-a-fail-closed-gate.md`); it is the pre-activation state
# this card leaves behind, kept nameable so the ordering differential has something to move.
POLICY_ENABLED = True

# THE EVIDENCE PATH — what must EXIST before the switch may be on, one entry per required card.
# `symbol` is the module attribute that IS that capability, so a missing capability is a missing
# name and not a matter of opinion. Named per card rather than as one boolean about "everything":
# the differential must be able to say WHICH half of the evidence path is absent.
EVIDENCE_PATH = (
    ("grant-state validation", "validate_grant_state", "T-10759"),
    ("server-issued identity derivation", "acting_identity", "T-10760"),
    ("the authorization decision", "authorize", "T-10761"),
    ("reach classification", "reach_report", "T-10762"),
    ("the attributable trail", "append_trail_record", "T-10763"),
    ("the all-registry-projects scope class", "resolve_scope_class", "T-10793"),
)


class PolicyEnableRefused(RuntimeError):
    """The policy is switched ON while its evidence path is incomplete — SPEC-0169 activation order.

    A REFUSAL and not a quiet `False`: a switch that silently reported "off" when it was configured
    ON would leave a gated operation running unguarded while the constant said otherwise, which is
    the same accepted-authority failure rule 3 refuses in another key. Raised by `policy_enabled`,
    so every path that consults the switch — including `enforce_gated_operation` — inherits it.
    """


def evidence_path_gaps(namespace=None) -> list:
    """Which evidence-path capabilities are ABSENT — `[{capability, symbol, card}]`, empty when whole.

    `namespace` is the module view to measure, defaulting to this module. It is injectable for the
    same reason the carrier is an installation parameter (rule 10): the ordering differential must
    be exercisable against a view with one capability REMOVED — i.e. against the state this module
    was in before that card landed — and there is no other honest way to reach that state from a
    checkout where every card has landed. It is a measurement parameter, never a way to widen
    anything: a namespace can only make the gate refuse MORE, never less.
    """
    import sys  # noqa: PLC0415 — lazy, keeps this module a stdlib+yaml leaf at import time
    ns = namespace if namespace is not None else sys.modules[__name__]
    return [{"capability": cap, "symbol": sym, "card": card}
            for cap, sym, card in EVIDENCE_PATH
            if getattr(ns, sym, None) is None]


def policy_enabled(*, namespace=None) -> bool:
    """IS the grant policy in force? — the switch, guarded by the ordering rule (build-order step 5).

    Returns False when `POLICY_ENABLED` is off — nothing to check, because an off switch enforces
    nothing and therefore claims nothing. Returns True when the switch is on AND every evidence-path
    capability is present. RAISES `PolicyEnableRefused` when the switch is on while any is missing:
    that is the differential this card exists for — with a required card unlanded, ENABLING IS
    REFUSED, so the contract cannot become normative at a moment when nothing could observe it.

    The refusal NAMES AN APPLICABLE ROUTE (`patterns/verb-design.md` §5(d), T-10767) — a fail-closed
    gate with no named door is how a gate becomes a trap, and this one has people on the other side.
    The route here is executable from the state the refusal detected: land the named card, or turn
    the constant off; nothing else resolves it, and the message says so rather than inventing a
    self-service escape.
    """
    ns = namespace
    if ns is None:
        import sys  # noqa: PLC0415
        ns = sys.modules[__name__]
    if not getattr(ns, "POLICY_ENABLED", POLICY_ENABLED):
        return False
    gaps = evidence_path_gaps(ns)
    if gaps:
        missing = "; ".join(f"{g['capability']} ({g['symbol']}, {g['card']})" for g in gaps)
        raise PolicyEnableRefused(
            f"grant policy ENABLE REFUSED: the switch is ON but its evidence path is incomplete — "
            f"missing {missing}. SPEC-0169's activation order (the plan's locked build order, step "
            f"5): no grant policy is switched on before the evidence path can OBSERVE it, because "
            f"activating a policy before the instrumentation that records its exercises is how a "
            f"rule becomes a claim — refusals nothing records explain nothing. "
            f"Route: land the card(s) named above (each ships the capability whose absence this "
            f"refusal detected), then re-run; or set `POLICY_ENABLED = False` in bin/lib/grants.py "
            f"to return the contract to its pre-activation, unenforced state. "
            f"`bin/yitc-v2 grants report` shows the grant state the enabled policy would read."
        )
    return True


def enforce_gated_operation(*, right, project, argv, env, session_identity, registry_text, carrier,
                            attribution, ts, events_path, append_event, namespace=None) -> dict:
    """THE SWITCH, COMPOSED — what a host GATED verb calls in place of a bare identity derivation.

    Order, and every step of it is landed code: (1) `policy_enabled` — so the ordering gate cannot
    be reached around by a caller that goes straight to the decision; (2) `exercise_right` — which
    is `authorize` (rule 3 caller-input refusal -> server-issued derivation -> rule 4 identity +
    grant-set refusals -> rules 1+2 decision) with rule 9's record written for EVERY outcome,
    permitted and refused alike.

    Adds NO decision logic of its own. That is the whole point of the smallest edit: the policy
    switch must not become a second place where an authorization is decided, because two deciders
    are two answers. Returns the permit decision, or `None` when the policy is OFF — and `None` is
    NOT a permit: the caller must treat it as "this gate is not in force" and fall back to the
    pre-activation behaviour, which is exactly what the host does.

    Raises whatever `exercise_right` raises (the four distinguishable refusals plus
    `TrailWriteRefused`), unchanged and with their landed messages — each already names its route,
    and restating them here would fork the wording of a refusal a person actually reads.
    """
    if not policy_enabled(namespace=namespace):
        return None
    return exercise_right(right=right, project=project, argv=argv, env=env,
                          session_identity=session_identity, registry_text=registry_text,
                          carrier=carrier, attribution=attribution, ts=ts,
                          events_path=events_path, append_event=append_event)
