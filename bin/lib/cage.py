"""SPEC-0172 rule 4 — the DECLARED-CAGE check: refuse a cage declared in violation of an atom.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT (SPEC-0172 rule 1, the layer boundary):
this reads a project's DECLARED cage mapping and returns the atom ids it refuses on. It never runs,
inspects, or brings up a stack — the instrument that refuses a violating RUNNING stack is library /
project MECHANICS and stays there. Same class as `bin/lib/grants.py`: a pure validator over a
declared carrier, no runtime, no subprocess, no I/O. A declaration that lies about the stack it
describes is out of this function's reach BY CONSTRUCTION, which is why the rule-4e table names the
PROJECT layer alongside KERNEL for atoms 4a-4c rather than claiming the whole check here.

ONE PREDICATE PER ATOM THE RULE-4E TABLE FILES **CHECKED AND NAMING KERNEL** — AND NONE FOR ANY
OTHER ROW (rule 4e / C6, read PER LAYER since T-10890). Two different rows earn the same silence
here, and the module owes the kernel's silence in both cases:

  * an atom CHECKED AT A LAYER THAT IS NOT THE KERNEL. 4d (grant-record-precedes-enablement) and
    rule 6 (sharing-follows-mutation) are both CHECKED at LIBRARY MECHANICS, anchored `cross:X-0757`.
    A kernel predicate for either would CLAIM another layer's check and hide it behind the kernel's
    name, leaving the layer that appears to owe it believing it is covered — C6's third arm refuses
    exactly that. Understating a check that exists is a defect of the same family as overstating one,
    which is why the answer is silence HERE rather than a predicate anywhere.
  * an atom filed DISCIPLINE, whose named layer carries no check YET. Enforcing one from the kernel
    would re-inflate a DISCIPLINE rule into a claimed refusal, which SPEC-0172 rule 4's
    interpretation note forbids. No cage row is DISCIPLINE as of 2026-08-11 (T-10929) — but the
    status is not retired, a row returns to it the moment its check stops resolving, and the
    prohibition is what keeps DISCIPLINE truthful when one does.

READ THE LAYER NAME LITERALLY: LIBRARY MECHANICS is one of rule 1's three layer names and says WHO
OWES the check. It does NOT say the check ships inside whatever the project pinned — on the ground
`cross:X-0757` is anchored to, those predicates live in that project's own spike instruments
(`patterns/spike-mode.md` §2/§3 measured it). Nothing above depends on where the check ended up:
the kernel is silent because the check is not ITS to make. `tests/test_spec0172_cage_contract.py`
asserts BOTH directions of the silence, and holds THIS paragraph against the shipped table.

FAIL-CLOSED on a mal-shaped declaration (the present-but-empty precedent, SPEC-0093 rule 23): a
missing, non-mapping, or field-incomplete cage is REFUSED, never read as "nothing declared, so
nothing to refuse" — an unreadable cage is exactly the silence the rule exists to end.

ATOM 4e — THE SERVED SOURCE (SPEC-0205 rule 3, T-12569) is a KERNEL-layer predicate over facts the
project-layer `cage_checks` instrument folds and passes in: this module still reads nothing itself.
Wiring atoms say the sandbox is caged; 4e says WHAT it serves is authenticated, and admits exactly
two sources — an ACTIVE spike worktree whose stamp agrees with its `worktree_created{spike:true}` row
(session ref + ts, row path == mounted path, not a `task/` branch, not parked), or a non-production
image built from a `main` SHA the caller resolved as landed. Anything else refuses on 4e.

The declared-cage shape (code-level by SPEC-0005 rule 3 — the spec states the RULE, this states the
FIELDS):

    stack_identity:      {compose_project: <str>, ports: [<port>...], volumes: [<name>...]}
    production_identity: {compose_project: <str>, ports: [<port>...], volumes: [<name>...]}
    scheduler:           {started: <bool>}
    outbound_channels:   {<name>: {mode: dummy|live, grant: {owner: <str>, at: <str>, case: <str>}}}
    served_source:       {kind: worktree, mounted_path: <str>, branch: <str>,
                          stamp: {spike: <bool>, declared_row: {ts: <str>, session_ref: <str>}},
                          rows: [{type: worktree_created, spike: <bool>, ts, session_ref, path}],
                          parked: <bool>}
                       | {kind: image, deploy_fact: {kind: deploy, revision: <sha>,
                          target: {production: <bool>}, build_source: <str>}, landed: <bool>}
"""
from __future__ import annotations

# Atom ids — the rule-4e table's first column. Kept as constants so a caller (and the conformance
# suite) names the same atom the contract does, never a re-spelled string.
ATOM_STACK_IDENTITY = "4a"
ATOM_SCHEDULER_NOT_STARTED = "4b"
ATOM_OUTBOUND_DUMMY_BY_DEFAULT = "4c"
ATOM_SERVED_SOURCE = "4e"

# The atoms this module carries a predicate for. The rule-4e table's cage atoms filed CHECKED **and
# naming KERNEL among their check layers** are this set exactly, both directions (C6 read per layer,
# T-10890) — a row CHECKED at another layer is not asked the question and owes nothing here. The
# conformance suite is what holds the two sides together.
CHECKED_ATOMS = (ATOM_STACK_IDENTITY, ATOM_SCHEDULER_NOT_STARTED, ATOM_OUTBOUND_DUMMY_BY_DEFAULT,
                 ATOM_SERVED_SOURCE)

# A malformed declaration is its own refusal id: it is not atom-specific (nothing was readable), and
# it must never collapse into "clean".
MALFORMED = "malformed-declaration"

_IDENTITY_FIELDS = ("compose_project", "ports", "volumes")
_GRANT_FIELDS = ("owner", "at", "case")


def _identity_shared(spike, production) -> bool:
    """True when the spike identity collides with production on ANY of the three axes.

    ANY, not all: sharing one port is enough to put a spike inside production's blast radius, so the
    axes are OR-ed. `compose_project` compares by equality; `ports`/`volumes` by set intersection.
    """
    if spike.get("compose_project") == production.get("compose_project"):
        return True
    for field in ("ports", "volumes"):
        if set(map(str, spike.get(field) or [])) & set(map(str, production.get(field) or [])):
            return True
    return False


def _grant_is_complete(grant) -> bool:
    """A per-case grant answers WHO, WHEN and FOR WHAT — a partial grant is not a grant.

    Rule 4c says "an explicit per-case owner grant"; a grant missing its owner, its moment, or its
    case cannot be checked against afterwards, so it is treated as absent rather than as weak
    evidence (fail-closed — the same choice as the mal-shaped declaration above).
    """
    if not isinstance(grant, dict):
        return False
    return all(isinstance(grant.get(f), str) and grant.get(f).strip() for f in _GRANT_FIELDS)


def _served_source_admitted(source) -> bool:
    """4e: True only for the two kernel-authenticated sources; every other shape is refused.

    Each comparison is exact (`is True` / `is False`, string equality) so a missing or mistyped fact
    reads as unauthenticated rather than as a pass — the stamp alone is forgeable, which is why the
    journal row must agree with it, and a tag lookup the caller could not make counts as `parked`
    only when it says so explicitly.
    """
    kind = source.get("kind")
    if kind == "worktree":
        stamp = source.get("stamp")
        branch = source.get("branch")
        mounted = source.get("mounted_path")
        if not isinstance(stamp, dict) or stamp.get("spike") is not True:
            return False
        declared = stamp.get("declared_row")
        if not isinstance(declared, dict) or not isinstance(branch, str) or branch.startswith("task/"):
            return False
        if not isinstance(mounted, str) or not mounted or source.get("parked") is not False:
            return False
        ts, session_ref = declared.get("ts"), declared.get("session_ref")
        if not ts or not session_ref:
            return False
        return any(
            isinstance(row, dict) and row.get("type") == "worktree_created" and row.get("spike") is True
            and row.get("ts") == ts and row.get("session_ref") == session_ref
            and row.get("path") == mounted
            for row in (source.get("rows") or [])
        )
    if kind == "image":
        fact = source.get("deploy_fact")
        if not isinstance(fact, dict) or fact.get("kind") != "deploy":
            return False
        revision, target = fact.get("revision"), fact.get("target")
        return (isinstance(revision, str) and bool(revision.strip())
                and isinstance(target, dict) and target.get("production") is False
                and fact.get("build_source") == "main" and source.get("landed") is True)
    return False


def refusals(declared_cage) -> list:
    """Return the sorted atom ids this DECLARED cage is refused on. Empty list == permitted.

    The empty return is the POSITIVE CONTROL half of every atom in rule 4: a check that refuses
    everything satisfies the refusal half perfectly and is useless, so a compliant declaration MUST
    come back clean.
    """
    if not isinstance(declared_cage, dict) or not declared_cage:
        return [MALFORMED]

    found = set()

    spike = declared_cage.get("stack_identity")
    production = declared_cage.get("production_identity")
    if not isinstance(spike, dict) or not isinstance(production, dict):
        found.add(MALFORMED)
    elif any(f not in spike or f not in production for f in _IDENTITY_FIELDS):
        found.add(MALFORMED)                       # an unreadable identity is not an isolated one
    elif _identity_shared(spike, production):
        found.add(ATOM_STACK_IDENTITY)

    scheduler = declared_cage.get("scheduler")
    if not isinstance(scheduler, dict) or not isinstance(scheduler.get("started"), bool):
        found.add(MALFORMED)                       # "the scheduler is not started" must be DECLARED
    elif scheduler["started"]:
        found.add(ATOM_SCHEDULER_NOT_STARTED)

    channels = declared_cage.get("outbound_channels")
    if not isinstance(channels, dict):
        found.add(MALFORMED)                       # no channel inventory == no dummy-by-default claim
    else:
        for spec in channels.values():
            if not isinstance(spec, dict) or spec.get("mode") not in ("dummy", "live"):
                found.add(MALFORMED)
            elif spec["mode"] == "live" and not _grant_is_complete(spec.get("grant")):
                found.add(ATOM_OUTBOUND_DUMMY_BY_DEFAULT)

    source = declared_cage.get("served_source")
    if not isinstance(source, dict):
        found.add(MALFORMED)                       # a cage silent on what it serves authenticates nothing
    elif not _served_source_admitted(source):
        found.add(ATOM_SERVED_SOURCE)

    return sorted(found)


# ---------------------------------------------------------------------------------------------------
# SPEC-0172 rule 9 — the HOST collision preflight's pure half (T-12458).
#
# NOT a cage atom and NOT in CHECKED_ATOMS: it judges a host STATE observed at one moment, not a
# declaration. The I/O half (the `docker ps` fold) lives with its verb in `cli.py`, so this module
# keeps its no-subprocess promise; everything here is a function of its two arguments.
# ---------------------------------------------------------------------------------------------------

HOST_REFUSE = "refuse"
HOST_REPORT = "report"


def _host_identity_collisions(declared, running) -> list:
    """Compare a DECLARED stack identity against the RUNNING stacks folded off the host.

    `declared`: {compose_project: str, ports: [int], own_projects: [str]} — own_projects are the
    caller's OWN production/spike compose projects; a running stack under one of them is never foreign.
    `running`:  [{compose_project: str ('' when unlabelled), ports: [int], holder: str}].

    REFUSE only an exact, non-empty compose-project-name match with a FOREIGN running stack (the
    data-loss class); REPORT each declared port a foreign holder publishes. Refusals first, then
    reports by port — deterministic, so the rendered lines diff cleanly.
    """
    own = {str(p) for p in (declared.get("own_projects") or []) if str(p)}
    name = str(declared.get("compose_project") or "")
    ports = {int(p) for p in (declared.get("ports") or [])}

    refusals, reports = [], []
    for stack in running:
        project = str(stack.get("compose_project") or "")
        if project and project in own:
            continue
        holder = stack.get("holder") or project
        if name and project == name:
            refusals.append({"kind": HOST_REFUSE, "compose_project": name, "holder": holder})
        for port in sorted(ports & {int(p) for p in (stack.get("ports") or [])}):
            reports.append({"kind": HOST_REPORT, "port": port, "holder": holder})
    return (sorted(refusals, key=lambda f: f["holder"])
            + sorted(reports, key=lambda f: (f["port"], f["holder"])))


def _host_preflight_lines(findings, n_stacks) -> list:
    """Render the preflight findings as the verb's stdout lines (one per finding, or one clean line)."""
    if not findings:
        return [f"host preflight: clean — no foreign collision among {n_stacks} running stack(s)"]
    lines = []
    for f in findings:
        if f["kind"] == HOST_REFUSE:
            lines.append(f"host preflight: REFUSE — compose project '{f['compose_project']}' is already "
                         f"held by a FOREIGN running stack ({f['holder']}); bringing the declared stack "
                         "up would operate on it")
        else:
            lines.append(f"host preflight: REPORT — port {f['port']} is published by foreign running "
                         f"holder '{f['holder']}' (report-only)")
    return lines
