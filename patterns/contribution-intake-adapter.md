---
name: contribution-intake-adapter
class: runbook
sourced_from: SPEC-0197 rule 2 (proposals over forge-neutral primitives) + SPEC-0195 rule 5 (the manifest-adjacent release notes)
applies_to: standing up — or moving — the public intake of the release mirror, on one concrete hosting service
---

# Contribution Intake Adapter — the first hosting service, as a worked example

## Problem

The contribution policy (SPEC-0197) is deliberately **forge-neutral**: rule 2 says a proposal is
"an issue, a merge request, or a patch mail" carrying a named minimal field set, and the spec body
names no hosting provider at all. That neutrality is CHARTER §Principle 4b applied to hosting
mechanics — the same reason normative text never names an AI provider — and it is load-bearing: a
rule that names a host silently makes the host part of the methodology, and moving hosts then means
amending a spec.

But an intake has to actually run somewhere, and "somewhere" is a concrete service with concrete
mechanics. Somebody standing the mirror up needs to know how the abstract field set becomes a form
a stranger can fill in, and somebody moving it later needs to know exactly what they are allowed to
change.

## Solution

**One adapter document — this one — holds every provider-specific detail, and nothing else does.**

The split is the whole pattern:

| Layer | Home | Changes when |
|---|---|---|
| The rules (intake, no direct merge, re-authoring, link-back, field set, destinations, non-endorsement) | SPEC-0197 | the policy itself changes |
| The plain-words statement a contributor reads | the published `CONTRIBUTING.md` (rendered by `work publish`) | the policy changes |
| **The provider mechanics** | **this document** | **the mirror moves hosts** |

If the mirror changes hosting service, this file is rewritten and nothing above it moves. That is
the property the pattern exists to preserve; it is checked mechanically by
`tests/test_contribution_policy_publish.py::test_spec_body_forge_neutral`, which asserts that a
provider name appears here and **not** in the spec body.

### The current adapter: GitHub

The mirror is currently published to **GitHub**, so the intake is GitHub's issue tracker, and the
proposal field set is realised as an issue form.

**Issue template.** Place at `.github/ISSUE_TEMPLATE/proposal.yml` in the mirror. The five fields
are exactly SPEC-0197 rule 2's set — the labels below are the plain-words glosses the published
policy uses, so a contributor reads the same words in both places:

```yaml
name: Proposal
description: Report a defect or propose a change to the methodology you installed
body:
  - type: input
    id: release-version
    attributes:
      label: Release version
      description: The exact release you have installed (the tag your pin names)
    validations: {required: true}
  - type: input
    id: affected
    attributes:
      label: Affected path(s) or rule id(s)
      description: A file path, a SPEC id, a rule
    validations: {required: true}
  - type: textarea
    id: observed
    attributes:
      label: Observed behaviour
      description: What actually happens today, concretely enough to reproduce
    validations: {required: true}
  - type: textarea
    id: proposed
    attributes:
      label: Proposed change or fix
    validations: {required: true}
  - type: input
    id: contact
    attributes:
      label: Contact for the link-back
      description: Where to reach you when the change ships, or is declined
    validations: {required: true}
```

**The proposal id.** The issue number (`#417`) is the id recorded on the re-authoring task card's
`answers:` field, which is what the publish step reads to build the release notes' link-back list.
It must satisfy the conservative id grammar in `bin/lib/release.py` (`ANSWER_ID_RE`) — a GitHub
issue reference does, both as `#417` and as `owner/repo#417`.

**Pull requests.** GitHub will let anyone open one against the mirror. That is not a second path:
per SPEC-0197 rule 3 nothing is merged into the mirror, and the mirror is regenerated from the
workshop on every publish, so an accepted PR's commits would simply be overwritten. Treat an opened
PR as a proposal in a different envelope — read its diff as the "proposed change" field, re-author
it in the workshop, and close it with the link-back like any other proposal. Setting the mirror's
branch protection to refuse merges makes that behaviour a property of the repository rather than a
habit of the maintainer.

**Link-back mechanics.** When the re-authored change ships, the release notes name the issue (the
publish step does this automatically from the card), and the issue is closed with a comment naming
the release version that carries it — or, if declined, with the reasons. Never close one silently:
that is rule 4, and it is the only step here a tool does not enforce for you.

### The two fallbacks, unchanged

The field set is the contract, not the form. A proposal arriving as a **merge request** on another
service, or as a **patch mail**, is accepted on identical terms as long as it carries the five
fields — the re-authoring, the link-back and the destinations ladder are all unaffected. Keeping
these live is what stops the adapter from quietly becoming the rule.

### Moving to another host

1. Rewrite this document for the new service: how the five fields are collected, what shape the
   proposal id takes, and how a merge attempt against the mirror is refused.
2. Check the new id shape against `ANSWER_ID_RE`; if it genuinely cannot fit, that is a proposal
   against the grammar, not a reason to loosen it locally.
3. Change nothing else. If you find yourself editing SPEC-0197 or the published policy text to
   accommodate a host, the neutrality has already leaked — stop and treat that as the defect.

## Anti-pattern

**Naming the host in the rules.** The moment a spec, the published policy, or a test fixture says
"GitHub" outside this document, the hosting service has become part of the methodology: a host
migration turns into a spec amendment with its own audits, and an adopter reading the policy cannot
tell which parts are the contract and which are one maintainer's tooling.

**Treating the adapter as optional detail.** The opposite failure: leaving the mechanics
undocumented "because they are obvious" means the intake exists only in the maintainer's head, and
the first person to stand up a second mirror re-derives it differently.

## Refs

- `bin/yitc-v2 graph query SPEC-0197` — the contribution policy (the rules; names no provider)
- `bin/yitc-v2 graph query SPEC-0195` — the release contract (rule 5: the manifest-adjacent notes)
- `bin/lib/release.py` — the section: the policy text, the link-back derivation, `ANSWER_ID_RE`
- `tests/test_contribution_policy_publish.py` — the forge-neutrality probe with its positive control
