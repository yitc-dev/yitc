---
name: methodology-lessons
class: discipline
sourced_from: V2 orchestrate-posture trial (2026-06) + the retired `decision new` rule→spec split (SPEC-0005 §rule 8 / §rule 3 content-boundary)
applies_to: at Stage-1 Analysis prior-art sweep (SPEC-0032 step 1) + plan currency-check — BEFORE re-proposing or re-litigating a methodological approach, consult this catalog for an already-rejected/withdrawn option + its why-rationale (anti-reinvention #5)
---

# Methodology Lessons — rejected/withdrawn approaches + the why-rationale

## Problem

When the `decision new` class was retired (a standing rule's text moves to a SPEC), the
**other half of a decision lost its home**: the *rejected alternatives* and the *why-it's-done-this-way*
rationale. A spec deliberately CANNOT hold that material — SPEC-0005 rule 3 (content boundary) forbids
rejected-alternatives narratives and deliberation chronology in a spec body, keeping specs pure
rule-text. MEMORY.md is a non-durable buffer (SPEC-0039), not a home. So a *settled methodological
lesson* — «we tried option X, rejected it, here's why» — had nowhere durable to live, and a later
session could silently **re-cross** it (anti-reinvention #5 fails): re-proposing an approach already
weighed and rejected, because the reasoning was invisible.

## Solution

ONE curated catalog doc — THIS file — under `patterns/`, V2's knowledge/reference catalog. It stores
**methodology lessons: rejected/withdrawn methodological options + the why-rationale**. It is appended
to over time (authored prose, accreted), and consulted at Stage-1 Analysis prior-art sweep
(SPEC-0032 step 1) + the plan currency-check.

**What it is NOT** (lane discipline — do not conflate):
- **NOT normative.** It lives in `patterns/` and is non-authoritative (per `doc-conventions` §Authority
  boundary). It RECORDS lessons; it never legislates. A standing *rule* is a SPEC or handbook prose.
- **NOT deviations.** A nonconformity / friction / incident is a `deviation_captured` event, promoted
  only to an `errors/E-XXXX` case file (`patterns/error-friction-tracking.md`). Different lane.
- **NOT instructions / a temporary buffer.** Bounded temporary instructions live in MEMORY.md
  (SPEC-0039); standing instructions are specs (kept pure rule-text).
- **NOT a new mechanism.** ONE doc — not a per-item folder, not a new journal, not a new format, not a
  new parser. It EXTENDS the existing `patterns/` catalog (anti-cx F1).

## Example

### Lesson 1 — background Build WORKERS dispatch as separate provider SUB-sessions, NOT in-process subagents

**The lesson (an example of this catalog's role).** An in-process subagent Build-WORKER fan-out
(the 2026-06-06 visible-mode candidate) was weighed as a trial probe and **REJECTED** on an
agent-identity collapse. The dispatch shape that replaced it — the rule, its WHY, and its SCOPE
(including the helper-role carve-out and the relation to CHARTER §6) — is homed single-SoT at
`patterns/background-session-dispatch.md §Dispatch mode`. This catalog only RECORDS that the
alternative was considered and rejected, so it is not re-litigated (Anti-pattern below); it does not
restate the rule.

**Governing provisionals (the authority — this catalog only RECORDS the lesson).** The CHARTER §6
AMENDMENT that elevates the orchestrate/dispatch posture is a SEPARATE, **in-trial** governance change
— NOT landed by this catalog entry. It is carried by:
- [[orchestrate-posture-for-the-main-session-6-amendme]] — §«Scope of the ban (owner-clarified
  2026-06-07)» (the §6-consistency clarification this entry records);
- [[dispatch-via-sub-sessions-only-subagents-forbidden]] — §Scope of the ban (the dispatch-design direction home);
- [[stage-entry-contract-unread-close-the-pointer-not-]] — §within-fleet (the `session_ref`-only identity gate deepening).

## Lessons — owner-request intake (distilled from the kupiclub-pilot meta-analysis of boomrocket + aiseller)

These four lessons RECORD how owner-request intake went wrong (or right) in two predecessor consumer
practices, so the kernel does not re-cross them. Each is **cap-excluded, non-normative** (a recorded
lesson, never a rule) — they legislate nothing. They are appended here, NOT authored as a new intake
spec / gate / ledger: the positive «owner states a want → AI classifies-and-files in one motion →
execute on go» intake-flow-as-spec is explicitly LEFT TO KERNEL TRIAGE (extend-not-create / anti-cx
F1). Refs to predecessor reports/decisions (`reports/methodologist/*`, `D-169`, `D-075`) are
**read-only provenance pointers** from the originating kupiclub-pilot context — citations, not
maintenance obligations, and not necessarily present in this checkout.

### Lesson 2 — OVER-PROCESS: accumulation queues + auto/nightly re-emit manufacture owner-questions when the owner is disengaged

**The lesson.** A standing accumulation queue paired with an automatic/nightly re-emit loop will
**manufacture** owner-questions on autopilot: when the owner is disengaged, the same unanswered
question is re-surfaced cycle after cycle instead of being resolved or dropped. In boomrocket the
**same owner-question was re-emitted 6× over 24–45 cycles with zero code commits** — pure process
churn, no progress. The defect is structural (a re-emit loop with no owner-presence gate and no
burn-down), not a one-off. **Why it matters here:** it is the same failure class CHARTER §6 retirements
forbid — auto-launch / autopilot-FSM / a stateful queue that runs without an owner cue. Do NOT
re-introduce an intake queue + auto re-emit; intake stays owner-cued.
**Refs (provenance):** `D-169`, `reports/methodologist/2026-06-19.yaml` (boomrocket). **Adjacent guard:** CHARTER §6 retirements (no auto-launch / batch-bounded / no stateful orchestrator).

### Lesson 3 — UNDER-RESOLVE: writer outpaces resolver, requests/decisions idle with no burn-down

**The lesson.** The mirror failure of Lesson 2: when the rate of RECORDING requests/decisions
outpaces the rate of RESOLVING them, items pile up and idle with no burn-down discipline. In aiseller
this produced **~54-day-idle items** — recorded, never closed. Recording is cheap; resolving is the
scarce step, so an intake practice must pace the writer to the resolver (or it silently accretes a
dead backlog). **Why it matters here:** it argues AGAINST a frictionless accumulation list (Lesson 5) —
a low-friction recorder with no resolution cadence is exactly what produces the idle pile.
**Refs (provenance):** `reports/methodologist/2026-06-17.yaml` (aiseller). **Adjacent guard:** QUEUE §Re-review triggers (the burn-down / re-review discipline).

### Lesson 4 — RECORD-THEN-CORRECT over proposal-first / ask-first

**The lesson.** For owner-request intake the owner prefers **recorded-then-corrected** over a
round-trip-per-trigger: the AI records its classification/filing and proceeds, and the owner corrects
afterward if needed — rather than blocking on a proposal/ask before every action. A round-trip per
trigger drains owner decision-energy (the same fatigue AGENTS §Recommendation Default guards against);
record-then-correct keeps the owner in a low-frequency correcting role, not a high-frequency approving
one. In aiseller this was settled as **D-075**. **Why it matters here:** it aligns intake with the
existing «lead with a recommended default + proceed; owner can redirect» posture — NOT a new ask-gate.
**Refs (provenance):** `D-075` (aiseller). **Adjacent:** AGENTS §Recommendation Default (lead-with-default, owner redirects; «delai» ("do it") → proceed).

### Lesson 5 — NO standing accumulation-list-processed-by-protocol for owner-request intake

**The lesson.** There is deliberately **no** standing accumulation list processed by a protocol for
owner-request intake. Today the only governing constraints are GENERIC, not intake-specific: the
`≤ 50` cap and «no new ledger/log». Lessons 2 and 3 are exactly WHY a dedicated intake accumulation
mechanism is rejected — it either churns (over-process) or rots (under-resolve). Intake rides the
existing surfaces (the queue, the cross coordination log, owner-cued filing), not a new
intake-specific accumulation structure. **Why it matters here:** this is the anti-complexity F1/F4
conclusion of the other three lessons — extend-not-create; a new intake ledger is the mechanism to NOT
add. **Adjacent:** SPEC-0008 (classification — distinct concern), AGENTS §Planning artifacts (`ideas/`-deferred notes — distinct lane), CHARTER §Principle 1 (anti-complexity F1 extend-not-create).

### Lesson 6 — legal/regulatory regimes are NOT encoded as a bound on the spike-sandbox ACCEPT verb (owner ruling 2026-08-11)

Record in patterns/methodology-lessons.md (drain batched, SPEC-0140 authored-note branch): REJECTED 2026-08-11 by owner ruling — encoding legal/regulatory regimes (card, personal-data, health) as a BOUND on SPEC-0175 rule 3's ACCEPT verb. The finding was real: an explicit ACCEPT records a business risk and cannot license what a regime forbids, so a project could comply with the floor's letter and still be in breach. REJECTED ANYWAY on CHARTER P1: the kernel would have to answer which regimes apply, who classifies the data and who verifies it — a compliance layer it has no business owning, and regime applicability is PROJECT-realm knowledge exactly like the class inventory (SPEC-0073). Delivered instead as one line in the wave memo (fu_50ddfd5c834a): compliance is the adopting project's. Cite this when a later gate or auditor re-raises the gap — it is answered, not missed. [relates: close-the-spike-mode-safety-floor-to-data-carried-]

### Lesson 7 — spec prose SHAPE: frontmatter is the better shape, body-in-YAML is KEPT (decided 2026-08-22, with a named revisit trigger)

SPEC PROSE SHAPE — REVISIT TRIGGER, armed on the external auditor's own wording (decisions/spec-prose-shape-audit-adhoc.yaml, YELLOW, 2026-08-22). DECIDED: frontmatter is the better shape for governed prose; we KEEP body-in-YAML because the migration cost (175 files, ~36k prose lines, 138 spec-referencing test files, and proving semantic identity across graph indexing/citations/status/signatures/query output) exceeds the measured benefit. This is a decision, not an omission. FIRE THIS when EITHER: (a) a planned spec-parser consolidation or graph-node storage rewrite ALREADY touches the canonical spec reader/writer - migrate then, because the expensive half is already being paid; or (b) one more CONFIRMED body-in-YAML production incident occurs that is NOT fixable at a narrower argv/audit boundary. Clause (b) is the honest half: the two known incidents ARE fixable narrowly and are carded as (machine-refute a disprovable audit finding) and (refuse a content-free capture), so neither counts. A third that neither would have caught DOES. If it fires, the migration needs a single graph API, generated conversion, parity probes over pre/post graph products (ids, statuses, bindings, cites, implements, anchors, query output, normalized body text, staleness verdicts) and a short-lived completion gate - never an indefinite dual-canonical corpus. Origin: kupiclub X-1067. [relates: X-1067]

### Lesson 8 — the cross re-entry predicate stays English-marker-only; a measured widening was DECLINED

re-entry predicate is English-marker-only: X-0091's Russian conditional decline ('Вернёмся, если частота вырастет') and X-0387's 're-issue' both name a real come-back condition the marker set misses. Measured widening was DECLINED at (26 hits, ~2 genuine). If a receiver-side strand recurs, the remedy is a measured marker pass, not a naive widen. [relates: ]

### Lesson 9 — tightening the SPEC-0161 CATALOGUED predicate was measured at ZERO effect; re-read before proposing it again

 item (4) DEFERRED WITH THE NUMBER — the SPEC-0161 CATALOGUED predicate (bin/lib/debt.py#spec0161_payload_key_coverage, 'if t not in corpus') is a raw whole-corpus SUBSTRING and admits 216/216 journal event types, i.e. the conjunct filters nothing. MEASURED 2026-08-30 on 178 spec files (152 active): the ACTIVE-SPEC-HOMING requirement the card proposed is worth ZERO (word-homed 212 -> active-word-homed 212, no type is catalogued solely by a superseded/withdrawn/draft/proposed/retired spec), and the strictest variant leaves governing pairs at 55 and coverage at 0.9091 against the 0.80 floor — no movement. The ONLY real tightening is the WORD-BOUNDARY half, worth 4 types (ac_probe_evidence, acceptance_probe, disposition_recorded, probe_evidence, each admitted only as a substring of a longer identifier) and also 0 governing pairs. That is a DIFFERENT change from the one proposed and was not made: two readers share this predicate (the land-verify catalog gate and the rule-28 debt fold), so changing it for no measured downstream effect fails CHARTER P1 filter 3. RE-READ THIS BEFORE PROPOSING THE CHANGE AGAIN — what would make it worth doing is the numbers MOVING, not the predicate looking loose. [relates: ]

## Anti-pattern

- **Re-litigating a settled lesson because its «why» had no home** — e.g. re-proposing in-process
  subagent fan-out for Build *workers* (the 2026-06-06 visible-mode candidate) without first consulting
  this catalog and seeing it was already weighed + rejected with the agent-identity reason.
- **Putting the rejected-option narrative in the wrong lane** — into a SPEC (violates SPEC-0005 rule 3
  content-boundary), or into MEMORY.md (a non-durable buffer, SPEC-0039), or treating it as a
  `deviation`/`errors` case (that lane is for nonconformities, not deliberation outcomes).
- **Growing this into a mechanism** — a per-lesson folder, a journal, a parser, or a normative
  gate. It is ONE non-normative reference doc. A standing *rule* belongs in a spec or handbook prose.

## Cites

- `SPEC-0005` — the spec doctrine; rule 3 (content boundary — why a spec cannot hold rejected-alternatives/why) + rule 8 (one home).
- `SPEC-0032` — Stage-1 Analysis procedure; step 1 prior-art sweep consults this catalog (anti-reinvention #5).
- `SPEC-0039` — MEMORY.md buffer (the non-durable lane this catalog is distinct from).
- `patterns/error-friction-tracking.md` — the deviations/`errors/E-XXXX` lane (distinct from methodology lessons).
- `patterns/doc-conventions.md` — §Artifact taxonomy + §Authority boundary (patterns/ is non-normative).
- `CHARTER.md §Principle 2` (patterns/ is the reference catalog), `§Principle 4b` (provider-neutrality).
- `plans/orchestrate-posture-for-the-main-session-6-amendme.md`, `plans/dispatch-via-sub-sessions-only-subagents-forbidden.md`, `plans/stage-entry-contract-unread-close-the-pointer-not-.md` — the governing in-trial provisionals for Lesson 1.
- `SPEC-0008` — request classification (distinct concern from the intake lessons 2–5; cited as adjacent, not duplicated).
- `CHARTER.md §Principle 6` — the orchestrate/auto-launch retirements (adjacent guard for Lesson 2 OVER-PROCESS).
- `QUEUE.md §Re-review triggers` (adjacent guard for Lesson 3 UNDER-RESOLVE), `AGENTS.md §Recommendation Default` (adjacent for Lesson 4 RECORD-THEN-CORRECT).
- Read-only provenance pointers for Lessons 2–5 (kupiclub-pilot meta-analysis of boomrocket + aiseller — NOT maintenance targets): `D-169`, `reports/methodologist/2026-06-19.yaml` (boomrocket); `reports/methodologist/2026-06-17.yaml`, `D-075` (aiseller); cross `X-0043`.
