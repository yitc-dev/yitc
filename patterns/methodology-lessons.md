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

## Lessons — owner-request intake (distilled from the <project>-pilot meta-analysis of <project> + <project>)

These four lessons RECORD how owner-request intake went wrong (or right) in two predecessor consumer
practices, so the kernel does not re-cross them. Each is **cap-excluded, non-normative** (a recorded
lesson, never a rule) — they legislate nothing. They are appended here, NOT authored as a new intake
spec / gate / ledger: the positive «owner states a want → AI classifies-and-files in one motion →
execute on go» intake-flow-as-spec is explicitly LEFT TO KERNEL TRIAGE (extend-not-create / anti-cx
F1). Refs to predecessor reports/decisions (`reports/methodologist/*`, `D-169`, `D-075`) are
**read-only provenance pointers** from the originating <project>-pilot context — citations, not
maintenance obligations, and not necessarily present in this checkout.

### Lesson 2 — OVER-PROCESS: accumulation queues + auto/nightly re-emit manufacture owner-questions when the owner is disengaged

**The lesson.** A standing accumulation queue paired with an automatic/nightly re-emit loop will
**manufacture** owner-questions on autopilot: when the owner is disengaged, the same unanswered
question is re-surfaced cycle after cycle instead of being resolved or dropped. In <project> the
**same owner-question was re-emitted 6× over 24–45 cycles with zero code commits** — pure process
churn, no progress. The defect is structural (a re-emit loop with no owner-presence gate and no
burn-down), not a one-off. **Why it matters here:** it is the same failure class CHARTER §6 retirements
forbid — auto-launch / autopilot-FSM / a stateful queue that runs without an owner cue. Do NOT
re-introduce an intake queue + auto re-emit; intake stays owner-cued.
**Refs (provenance):** `D-169`, `reports/methodologist/2026-06-19.yaml` (<project>). **Adjacent guard:** CHARTER §6 retirements (no auto-launch / batch-bounded / no stateful orchestrator).

### Lesson 3 — UNDER-RESOLVE: writer outpaces resolver, requests/decisions idle with no burn-down

**The lesson.** The mirror failure of Lesson 2: when the rate of RECORDING requests/decisions
outpaces the rate of RESOLVING them, items pile up and idle with no burn-down discipline. In <project>
this produced **~54-day-idle items** — recorded, never closed. Recording is cheap; resolving is the
scarce step, so an intake practice must pace the writer to the resolver (or it silently accretes a
dead backlog). **Why it matters here:** it argues AGAINST a frictionless accumulation list (Lesson 5) —
a low-friction recorder with no resolution cadence is exactly what produces the idle pile.
**Refs (provenance):** `reports/methodologist/2026-06-17.yaml` (<project>). **Adjacent guard:** QUEUE §Re-review triggers (the burn-down / re-review discipline).

### Lesson 4 — RECORD-THEN-CORRECT over proposal-first / ask-first

**The lesson.** For owner-request intake the owner prefers **recorded-then-corrected** over a
round-trip-per-trigger: the AI records its classification/filing and proceeds, and the owner corrects
afterward if needed — rather than blocking on a proposal/ask before every action. A round-trip per
trigger drains owner decision-energy (the same fatigue AGENTS §Recommendation Default guards against);
record-then-correct keeps the owner in a low-frequency correcting role, not a high-frequency approving
one. In <project> this was settled as **D-075**. **Why it matters here:** it aligns intake with the
existing «lead with a recommended default + proceed; owner can redirect» posture — NOT a new ask-gate.
**Refs (provenance):** `D-075` (<project>). **Adjacent:** AGENTS §Recommendation Default (lead-with-default, owner redirects; «delai» ("do it") → proceed).

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

SPEC PROSE SHAPE — REVISIT TRIGGER, armed on the external auditor's own wording (decisions/spec-prose-shape-audit-adhoc.yaml, YELLOW, 2026-08-22). DECIDED: frontmatter is the better shape for governed prose; we KEEP body-in-YAML because the migration cost (175 files, ~36k prose lines, 138 spec-referencing test files, and proving semantic identity across graph indexing/citations/status/signatures/query output) exceeds the measured benefit. This is a decision, not an omission. FIRE THIS when EITHER: (a) a planned spec-parser consolidation or graph-node storage rewrite ALREADY touches the canonical spec reader/writer - migrate then, because the expensive half is already being paid; or (b) one more CONFIRMED body-in-YAML production incident occurs that is NOT fixable at a narrower argv/audit boundary. Clause (b) is the honest half: the two known incidents ARE fixable narrowly and are carded as (machine-refute a disprovable audit finding) and (refuse a content-free capture), so neither counts. A third that neither would have caught DOES. If it fires, the migration needs a single graph API, generated conversion, parity probes over pre/post graph products (ids, statuses, bindings, cites, implements, anchors, query output, normalized body text, staleness verdicts) and a short-lived completion gate - never an indefinite dual-canonical corpus. Origin: <project> X-1067. [relates: X-1067]

### Lesson 8 — the cross re-entry predicate stays English-marker-only; a measured widening was DECLINED

re-entry predicate is English-marker-only: X-0091's Russian conditional decline ('Вернёмся, если частота вырастет') and X-0387's 're-issue' both name a real come-back condition the marker set misses. Measured widening was DECLINED at (26 hits, ~2 genuine). If a receiver-side strand recurs, the remedy is a measured marker pass, not a naive widen. [relates: ]

### Lesson 9 — tightening the SPEC-0161 CATALOGUED predicate was measured at ZERO effect; re-read before proposing it again

 item (4) DEFERRED WITH THE NUMBER — the SPEC-0161 CATALOGUED predicate (bin/lib/debt.py#spec0161_payload_key_coverage, 'if t not in corpus') is a raw whole-corpus SUBSTRING and admits 216/216 journal event types, i.e. the conjunct filters nothing. MEASURED 2026-08-30 on 178 spec files (152 active): the ACTIVE-SPEC-HOMING requirement the card proposed is worth ZERO (word-homed 212 -> active-word-homed 212, no type is catalogued solely by a superseded/withdrawn/draft/proposed/retired spec), and the strictest variant leaves governing pairs at 55 and coverage at 0.9091 against the 0.80 floor — no movement. The ONLY real tightening is the WORD-BOUNDARY half, worth 4 types (ac_probe_evidence, acceptance_probe, disposition_recorded, probe_evidence, each admitted only as a substring of a longer identifier) and also 0 governing pairs. That is a DIFFERENT change from the one proposed and was not made: two readers share this predicate (the land-verify catalog gate and the rule-28 debt fold), so changing it for no measured downstream effect fails CHARTER P1 filter 3. RE-READ THIS BEFORE PROPOSING THE CHANGE AGAIN — what would make it worth doing is the numbers MOVING, not the predicate looking loose. [relates: ]

### Lesson 10 — the land reservation is NOT acquired by waiter seniority (FIFO) — owner-REJECTED, standing (2026-09-12, re-affirmed 2026-09-13)

REJECTED by owner ruling 2026-09-12 13:45:27Z («не делаем и не предлагай») and re-affirmed 2026-09-13 06:33:42Z (« (FIFO резервации) - не делаем. запиши. порядок лендов как сейчас») — ordering the land-reservation flock ( seam, `bin/lib/worktree.py`) by the waiter's recorded wait-start so an older waiter is never overtaken. The finding behind the proposal was real and measured (2026-09-12: task/ launched 11:52Z took the reservation while task/, waiting ~63 min, and four older waiters kept waiting; 36 park-limit evictions in 7 days waited 6058 min and shipped nothing — debt rule 27). The card was filed twice (2026-09-12, and on 2026-09-13 by a revizia run that had not seen the first ruling) and wont-do'd both times. WHY REJECTED: the owner keeps the land order AS IT IS — SPEC-0184 rule 9's cost ladder + the queue-jump mark (an explicit owner/controller act) + SPEC-0132's bounded park are the ONLY orderings; a seniority rule converts the flock from an age-blind race into a stateful queue (the forbidden stateful-orchestrator shape, CHARTER §6 / SPEC-0184 «this rule does not make either FIFO»), and starvation of a SPECIFIC branch is handled by the queue-jump mark, not by a global policy. STANDING: do not re-propose FIFO/seniority acquisition; a card carrying that shape fails premise-verify (SPEC-0060) against SPEC-0184's rule-9 note. If the eviction cost is the concern, the admitted levers are the park bound (SPEC-0132), the queue-jump mark and the cost classes — measure those first. [relates: wont-do;;;; SPEC-0184; SPEC-0132]

### Lesson 11 — plan-level audits carry NO pass-count ceiling — owner-REJECTED, standing (2026-09-13, re-affirmed 2026-09-28)

REJECTED by owner ruling 2026-09-13 08:50:02Z (archive/events-2026-09-13.jsonl#ts=: «кажется что правила потолка аудита для задачи не пригодны для плана - суть плана в том и есть что бы хорошо спланировать и если нужно много повторений - то пусть будет много повторений») and re-affirmed 2026-09-28 (events.jsonl#ts=: «Потолка на число проходов нет. - по планам мы решили что и не должно быть»; events.jsonl#ts=: «нужно про отсутствие потолка где-то записать в ядре чтобы не возвращаться случайно к этому вопросу») — a pass-count ceiling, trend-stop or pass limit on plan-level audits, covering BOTH the plan GATES and the on-demand `plan check` re-runs. The 2026-09-28 re-affirmation answered the newcomer test-server review (plan newcomer-adopter-journey-a-non-it-person-from-a-gi, «Postcheck soak findings — run 1», new finding 1), which read «7 consecutive full plan check passes, no ceiling» as a HIGH defect. WHY REJECTED: a plan converges by iteration — repeated checks are the plan doing its job, and the cost of another pass is the owner's to judge, not a counter's; the plan-gate budget is already decision-bounded by SPEC-0204 rule 9(f) (`audit.PLAN_GATE_BUDGET`), and the task audit-loop ceiling (2+1, SPEC-0204) stays for TASKS only. STANDING: do not file a card or a finding proposing a plan-check/plan-gate pass ceiling, trend-stop or pass limit; a card of that shape fails premise-verify (SPEC-0060) against this lesson and SPEC-0204 rule 9(f). NOT covered by this rejection (still open as ordinary ergonomics): keeping a separate record per pass instead of overwriting one audit file, mandatory `audit_finding_absorbed` rows, and delta-checking only changed sections. [relates:;; SPEC-0204; SPEC-0060; plan newcomer-adopter-journey-a-non-it-person-from-a-gi]

### Lesson 12 — a delta-only re-check is REJECTED as the sole re-check of a gate pass; the qualified delta scheme is owner-DEFERRED (2026-10-06)

REJECTED on measured evidence (the report is `patterns/delta-only-recheck-observation.md`, its per-finding table in the four `patterns/delta-only-recheck-observation-findings-*.md` parts): re-checking a gate after an absorbing edit by reading ONLY the changed text and what depends on it. The analysis covered 45 plans and 155 consecutive pass pairs on the four plan gates (2026-07-08 → 2026-10-05) and classified every later-pass finding: of 143 HIGH findings, 45% sat in the changed text, 11% in unchanged text that depends on the change, and 24% (up to 36% when every unclassifiable finding is counted that way) in unchanged text INDEPENDENT of the change — defects every earlier full read had missed (MEDIUM: 31%, up to 45%). That share does not decay with the pass number (24% at pass 2, 24% at pass 3, 27% at pass 4); 30 of the 35 such highs had sat in the text since the gate's FIRST pass; 24 of the 61 high-bearing pass pairs held at least one. A delta read that also re-checks the prior findings would have seen 64% of the highs. So a full read keeps finding about a quarter of its highs in text nobody changed, and a delta-only re-check would let those through.
DEFERRED by owner ruling 2026-10-06 (events.jsonl#ts=, option A: «да, берём A. пускай в работу») — the QUALIFIED scheme the report proposes: (1) the first pass at each gate is a full read; (2) a delta pass re-checks every prior finding and sweeps the whole subject for the same defect class; (3) any high or medium found by a delta escalates to a full read; (4) only a full read gives the closing GREEN. WHY DEFERRED: the closing GREEN must be a full read anyway, so the scheme saves time only in long absorb-and-recheck loops (the escalation rule would have fired in 54 of the 61 high-bearing pairs), and already removed the main time sink of a re-check. ADOPTED from it, as its own card : the cheap part — the same-class sweep (when a finding is absorbed, check every sibling instance of its defect class, not only the one named). STANDING: a re-check pass reads the whole subject; do not propose a delta-only re-check without new numbers. Re-open the qualified scheme only if re-check passes again become a measured time sink. This lesson is about WHAT a re-check reads; Lesson 11 (no pass ceiling on plan audits) is unchanged. [relates:;;; SPEC-0204; SPEC-0083; Lesson 11]

### Lesson 13 — a stage-delivery saving is taken from the cheapest NO-RULE-MOVE cut first; a relocation pilot does not grow mechanism its saving cannot pay for — owner ruling (2026-10-07)

CANCELLED by owner ruling 2026-10-07 («давай а», events.jsonl at that turn): plan
`restructure-heavy-specs-as-core-plus-index-plus-on`, whose pilot moved ~4.4 kB of SPEC-0015 (the settle procedure)
into a reference spec. To make that one move «provably safe» it grew a new read gate on the settle verb with
per-checkout, per-epoch credit, a seed cue in every startup read, one wording across four surfaces, nine test
rewrites and, in the end, a new «when is a probe due» duty — over 17 trial cycles, four convergence reads and two RED
accept-gate passes. Measured against that: the gate never fired in the converged cycles (agents found the reference
through the core's index line and the verb's help head), and the maintainer-only sections every stage entry renders
(`## Verification` ≈79 kB + `## Rationale` ≈13 kB per substantive task) were ~20× the pilot's saving while moving no
rule at all. STANDING: (1) take the no-rule-move cuts first (maintainer-only sections, retired provenance) and
measure; (2) a relocated rare branch keeps a plain index line + a pointer at the head of the verb's help — add a gate
only when a rule is shown to be lost without one; (3) a pre-existing gap a trial exposes (here: what to do with a
due deferred probe) is its own card, never folded into the pilot. The trial's findings stay valid evidence for
(2): the index line and the help head are what agents actually met. (4) before filing a card that moves or un-binds rule text, grep `tests/` for that text and for the binding, and name in the card the probe of each landed card that pins it (six cards were refused pre-claim on 2026-10-08 for missing this, deviation `events.jsonl#ts=`). [relates: plans/restructure-heavy-specs-as-core-plus-index-plus-on.md; <workshop-spec>; SPEC-0015; CHARTER §Principle 1]

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
- Read-only provenance pointers for Lessons 2–5 (<project>-pilot meta-analysis of <project> + <project> — NOT maintenance targets): `D-169`, `reports/methodologist/2026-06-19.yaml` (<project>); `reports/methodologist/2026-06-17.yaml`, `D-075` (<project>); cross `X-0043`.
