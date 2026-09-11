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

The declared-cage shape (code-level by SPEC-0005 rule 3 — the spec states the RULE, this states the
FIELDS):

    stack_identity:      {compose_project: <str>, ports: [<port>...], volumes: [<name>...]}
    production_identity: {compose_project: <str>, ports: [<port>...], volumes: [<name>...]}
    scheduler:           {started: <bool>}
    outbound_channels:   {<name>: {mode: dummy|live, grant: {owner: <str>, at: <str>, case: <str>}}}
"""
from __future__ import annotations

# Atom ids — the rule-4e table's first column. Kept as constants so a caller (and the conformance
# suite) names the same atom the contract does, never a re-spelled string.
ATOM_STACK_IDENTITY = "4a"
ATOM_SCHEDULER_NOT_STARTED = "4b"
ATOM_OUTBOUND_DUMMY_BY_DEFAULT = "4c"

# The atoms this module carries a predicate for. The rule-4e table's cage atoms filed CHECKED **and
# naming KERNEL among their check layers** are this set exactly, both directions (C6 read per layer,
# T-10890) — a row CHECKED at another layer is not asked the question and owes nothing here. The
# conformance suite is what holds the two sides together.
CHECKED_ATOMS = (ATOM_STACK_IDENTITY, ATOM_SCHEDULER_NOT_STARTED, ATOM_OUTBOUND_DUMMY_BY_DEFAULT)

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

    return sorted(found)
