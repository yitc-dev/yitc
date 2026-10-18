---
name: restating-an-active-spec-across-cards
class: discipline
sourced_from: 'public issue #81 (2026-10-12) — a consumer project''s five-point recipe for a plan that restated an active spec across six cards; each point read against <workshop-spec>, SPEC-0046, SPEC-0070 and SPEC-0083 by '
applies_to: 'cutting a plan at its `decomposition` stage when a plan spec restates an ACTIVE spec (its `supersedes:` names one) and more than one card builds the change'
---

# Restating an active spec across several cards — how the cut meets the owner-card clause

> **How-to, not a rule.** This file adds no rule, gate, field or check. Every step below names the
> spec that holds the rule it applies; where this file and a spec disagree, the spec wins
> (`patterns/doc-conventions.md` §Authority boundary). The clause this how-to serves is SPEC-0070 §3
> «Anchor wiring carried by the cut», which is read here exactly as written. A session meets the
> pointer to this file beside that clause, in the text the `decomposition` plan stage delivers.

## Problem

A plan carries a `proposed` spec whose `supersedes:` names an ACTIVE spec (below: the successor and
the predecessor), and several cards build the change. Two facts of the corpus pull the cut in
opposite directions:

- **The owner card comes last.** SPEC-0070 §3: the successor's `activation_owner_task` card is
  `requires:`-ordered after every implementing card. A cut that activates the successor with its
  FIRST card is reported by the decomposition-fidelity gate.
- **Until that card closes, the predecessor is the only rule.** `active` is the only normative
  status and a `proposed` spec governs nothing (<workshop-spec> rule 4). A card that lands, before the
  activation, behaviour the predecessor forbids contradicts an accepted artifact (SPEC-0046 §A,
  red-flag (b)). A cut that activates LAST and lets earlier cards carry such behaviour builds that
  contradiction in.

Neither spec says how one cut satisfies both, so a plan learned it from the gates. Reported cost on
one installation: seven RED gate rounds over two plans (one accept RED and two fidelity REDs on the
plan that activated first; four accept REDs on the plan before it, which landed behaviour against
the still-active predecessor), and two features dropped from a plan to get through.

## Solution

**Before the cut — sort the changed sentences.** List every sentence of the predecessor that the
successor changes, removes or adds to. For each, ask one question about the RESULT a card would land
if it built that change while the predecessor is still active: does that result meet the predecessor
as it stands today?

- **YES — the change is OPEN.** The predecessor is silent on it, admits it, or asks for less than
  the successor does. Example: the predecessor asks for at least one audit record per request and the
  successor for exactly one; a result that writes exactly one meets both, so the change is OPEN
  although the two texts differ.
- **NO — the change is CLOSED.** The result would do what the predecessor forbids, or leave out what
  it requires.

The question is about the built result, not about how far the two wordings differ. The probe of
<workshop-spec> rule 7 (does an edit change what a consumer does to comply in an already-covered case)
answers a different question — which route a change of spec text takes — and a YES there does not
make a change CLOSED: a tightening the predecessor already admits is OPEN.

Keep the list in the plan body or the cut cards, where the fidelity gate reads the cut. Then cut by
the five points below. Each point is marked with what the kernel's own rules say about it.

### 1. The owner card is the LAST implementer — ADOPTED

Set the successor's `activation_owner_task` to the card that implements it last, and give that card
a `requires:` edge to every other card that implements the successor.

- Basis: the SPEC-0070 §3 clause itself; <workshop-spec> rule 5 (one activation owner, the other
  implementing cards `cite` the spec); the SPEC-0083 P5 template («`requires:` ordering encoded, not
  prose»).
- Name the other implementing cards on the owner card directly instead of chaining them one behind
  another: SPEC-0046 §A keeps the transitive depth of a `requires:` chain at 3 or less.

### 2. Earlier cards add only what the active predecessor admits — ADOPTED

A card ordered before the owner card builds OPEN changes only. Each such card names, in its scope or
acceptance, the predecessor sentence its result still meets.

- Basis: <workshop-spec> rule 4 (the predecessor is the rule until the activation); SPEC-0046 §A red-flag
  (b) (a unit that contradicts an accepted artifact is mis-cut); SPEC-0046 §A execution-readiness
  rule, part (1) (a unit names the accepted artifact it aligns with — here the ACTIVE predecessor,
  since the successor is not yet an accepted rule).

### 3. Closed changes go into the owner card, or out of the plan — ADOPTED IN PART

**Adopted.** Every CLOSED change is built by the owner card. The close of that card is the one
write that activates the successor and flips the predecessor to `superseded` (<workshop-spec> rule 4), so
the behaviour and the text that admits it reach `main` in one land. Several closed changes in one
owner card are the keep-atomic side of SPEC-0046 §A «Bidirectional cut»: splitting them would leave
a contradictory interim state. A reviewer's recommendation to split that card is advisory
(SPEC-0070 §3). A closed change the plan will not build now leaves the plan as a tracked task with
its return trigger, not as a sentence (SPEC-0046 §B).

**Declined — the size bound.** The reported recipe adds «if the closed changes do not fit one card
of about two hours, split the plan». The kernel has no such bound and its cutting rule points the
other way: SPEC-0046 §A cuts by claim, and names size a secondary symptom, not the criterion. A PLAN
is split on the signals of SPEC-0046 §A2 (different validation horizons, independently rejectable
fates, a producer and a consumer over real data), and card size is not one of them. A project that
wants a size limit on its cards declares it as its own task-grouping preference (SPEC-0046 §A); it
then governs that project's cuts, this one included.

### 4. No before/after rule text — ADOPTED

Write the successor's rule text as the rule that holds once it is active. Do not write a two-state
text («until card X lands … afterwards …»): after the land one of its halves is dead wording that
every later reader still receives.

- Basis: <workshop-spec> rule 3 — the rule text keeps what the acting reader applies and states each
  acting rule once. The «before» half stops being applied at the land; rule 3 gives text about a
  route that is retired one line at most, and sends the history of which card or change produced a
  rule to the spec's `## Rationale`. No spec forbids a two-state text in so many words; the point is
  adopted as what rule 3 leads to.
- Where the rule depends on what ANOTHER spec decides, state it through a condition that holds
  whichever way that spec decides, and leave the decision in that spec. Basis: <workshop-spec> rule 8 (one
  home; a mention of a rule homed elsewhere is built so that a change at the home needs no edit
  here — the SPEC-0067 test). The reported example: «a key another handler has handled is not free»
  instead of naming which handler takes which key before and after the change.
- The same holds for a card's probe: a probe anchored to a state that the card's own landing ends is
  SPEC-0046 §A red-flag (e).

### 5. Cross-plan order — ADOPTED IN PART

**Adopted — between PLANS there is no `requires:`.** Plans carry no blocking dependency; order
between two plans lives in each plan's own entry gates and in the later plan's stated input
(SPEC-0046 §A2). So a later plan that needs an earlier plan's result says so in its body as its
input — for example «card X landed and spec Y is active on `main`» — which is where SPEC-0046 §A2
puts the order between two plans.

**Declined — «never a `requires:` edge onto another plan's card».** The corpus does not forbid a
card-level edge to a card of another plan: no rule limits a `requires:` target to cards of the same
plan, and the picker holds a card until every target is done (QUEUE.md §Picker logic). Two rules ask for exactly that
edge. SPEC-0046 §A3: a verifier's `requires:` names EVERY writer of its subject, machine-readable,
never prose or operator memory — whichever plan filed that writer. SPEC-0083 P5: every intended
precedence is carried by a `requires:` edge, so that no later writer can legally run before a card
it depends on. A sentence in a plan body is invisible to the picker, so on its own it holds no card
back.

Put together: order between two plans as wholes is the later plan's stated input; a CARD that
cannot run before one specific card carries a `requires:` edge to it, in whichever plan that card
was filed.

## Example

The successor S supersedes the active predecessor P. The sentence list finds four changes: c1 and c2
OPEN, c3 and c4 CLOSED.

| Card | Builds | `requires:` | Names |
|---|---|---|---|
| A | c1 | — | the sentence of P its result still meets |
| B | c2 | — | the sentence of P its result still meets |
| OWNER | c3, c4 and the code-anchor wiring of S | A, B | S, which its close activates |

`activation_owner_task` of S is OWNER. A and B may land in either order while P is active. OWNER
lands c3 and c4 together with the activation of S; P becomes `superseded` in the same step.

## Anti-pattern

- **Activating with the first card.** The owner card then precedes cards that implement the spec it
  activates; the fidelity gate reports the cut.
- **Activating last and letting an earlier card carry a closed change.** That card lands behaviour
  the active predecessor forbids.
- **Re-reading «implementing card» so that some implementers do not count.** This how-to does not
  interpret that term; the clause is applied as written.
- **A two-state rule text**, or a rule that restates what another spec decides.
- **Cross-plan order kept only in a plan sentence** when one card depends on one specific card.

## Bounds

- This how-to offers no cut that lands a CLOSED change before the activation. Where the closed
  changes cannot be built as one coherent card, that is a question about the shape of the plan for
  its author and owner (SPEC-0046 §A2 names the split signals), not something the cut can solve.
- The other two ways SPEC-0070 §3 names for the anchor wiring — the owner card `requires:` the card
  that wires, or the spec declares a SPEC-0151 `execution:` disposition — are unchanged and outside
  this how-to.
- The five points come from one project's two plans. A cut the gates reject while following them is
  a finding about this file: capture it.

## Cites

- SPEC-0070 §3 — the owner-card clause and the decomposition-fidelity gate.
- SPEC-0083 — the P5 fidelity template that asks the question.
- SPEC-0046 §A, §A2, §A3, §B — the cutting rules each point is read against.
- <workshop-spec> rules 3, 4, 5, 8 — rule-text content, spec status, the activation owner and the
  one-home rule.
- `patterns/big-plan-checklist.md` — the plan-level check that precedes the cut.
