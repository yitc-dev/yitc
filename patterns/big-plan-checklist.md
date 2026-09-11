---
name: big-plan-checklist
class: discipline
sourced_from: <v1-archive>/core/pm-protocol/21-plan-authoring-prevention-checklist.md (v1 §21)
applies_to: substantive plans (foundational decisions, multi-step proposals, plans touching 3+ canonical files, plans containing quantitative claims)
---

# Big Plan Checklist — 7 probes

Seven probes for a substantive plan/proposal. AI consults before finalizing a big plan.

> **Status (owner-directed 2026-06-04 — the «later» trigger fired).** This checklist stops being purely
> an «optional reference»: its formal integration via SPEC + LIFECYCLE is being **codified** in the
> plan-lifecycle stage-model — for a **big** plan the big-plan discipline becomes MANDATORY at
> `plan check`, which gates entry into the `executing` stage (a filled `checklist_pass` + a fresh `plan check
> --full` + a dry-run if the rules are new). Design + deliverable:
> `plans/plan-lifecycle-delivery-parity-redesign-lifecycle-` §Stage model. Until that plan is
> realized, the rule stays advisory; `plan check --full` already auto-applies this checklist for big
> plans (`big_plan_checklist: true` in the verdict) + a structural pre-pass mechanizes P7.

Adapted from v1 §21.

## When to apply

A substantive plan — if **at least one** of:
- Decision class = `foundational`
- Plan touches ≥ 3 canonical files (CHARTER + AGENTS + LIFECYCLE + QUEUE + GRAPH)
- Plan contains quantitative claims (LOC estimate, cost, throughput, multiplier)
- Plan introduces a new principle, mechanism or node type
- Plan multi-step with ≥ 3 commits expected

**Does NOT apply** to:
- Routine task (T-XXXX) execution via the 9-stage lifecycle
- Hygiene fast-path tasks (see LIFECYCLE §3)
- Small fixes / refactor / single-file changes

## Seven probes

### Probe 1 — Traverse parked tasks

Open the `tasks/` directory, filter `status: parked`. For each parked entry answer explicitly: does `return_trigger` fall within the current plan's window?

- If **no** → document inline: `[T-XXXX parked] not in scope: {reason}`
- If **yes** → document inline: `[T-XXXX parked] in scope: included as {task-ref or milestone}`

Without inline documentation per parked entry — the plan is not considered complete.

**Slip example (v1 B-985):** B-985 (subagent-rollout) was DEFERRED with trigger «when pipeline foundation ships». D-131 shipped — trigger fired — B-985 did not appear in the launch plan because the author skipped the DEFERRED traverse. Owner discovered the gap by asking about B-985 directly.

### Probe 2 — Audit decisions by layer

For **each D-XXXX reference** in the plan body: open the decision YAML, traverse all sub-deliverables/acceptance criteria, record each status explicitly as `SHIPPED / PARTIAL / NOT_STARTED`.

**Inline format:** `D-XXXX Layer N ({name}): SHIPPED|PARTIAL|NOT_STARTED`

**Forbidden:** `D-XXXX SHIPPED` — the summary form without a per-layer breakdown is forbidden if **not all** layers are SHIPPED.

**Slip example (v1 D-140):** The launch plan wrote `D-140 SHIPPED` without a per-layer breakdown. D-140 (cite-honesty) promised Layers 1+2+3. Layers 1 and 2 were in fact NOT shipped — grep in bin/hooks/ and checks/pre-commit/ returned NOT_FOUND. The false SHIPPED claim passed undetected until the spec-author ran the P2 probe.

### Probe 3 — Align on «done» with the owner

Before finalizing the plan: explicitly ask the owner «Do we define done the same way? What exactly do you expect to see in production?». Record the answer in the plan's opening section:

```yaml
done_definition:
  owner_confirmed: true
  definition: "{owner's answer verbatim or accurate paraphrase}"
  includes_public_readiness: true|false
  date: "YYYY-MM-DD"
```

Finalization without this block is forbidden.

**Slip example:** Developer shipped a feature: API returns 200, all tests green. Owner expected a user-visible change on a specific UI screen. Different «done» understandings discovered at acceptance. Rework ≥1 day. P3 forces alignment before implementation starts.

### Probe 4 — External independent review

Before shipping the plan: request an external independent review via the external auditor with an open-ended question: «What is missing in this plan? What did I not ask that bears on real readiness?». Record the response under `external_review`.

**Inline format (reviewed):**

```yaml
external_review:
  agent: external-auditor
  question: "What is missing? What was not asked but bears on real readiness?"
  summary: "{1-3 sentence summary of external findings}"
  gaps_addressed: ["{gap1}", "{gap2}"]
```

**Inline format (skipped):**

```yaml
external_review:
  skipped: true
  reason: "{reason}"
  owner_approved: true
```

Skip only with `owner_approved: true` and an explicit reason.

### Probe 5 — Run against existing patterns

Before writing any proposal or spec:

```bash
ls patterns/
grep -rl '{topic_keywords}' patterns/
```

A matching pattern found **must** be referenced and built upon — not reinvented. Document checked patterns inline even if nothing suitable is found.

**Inline format:**

- Found: `cross_checked_patterns: [{pattern_name}: {how_it_applies}]`
- Not found: `cross_checked_patterns: none_found (search_terms: {terms})`

**Slip example:** A spec author wrote a custom plan-completeness checklist not knowing that `knowledge/patterns/pre-commit-regression-gates.md` covers an analogous pre-ship gate pattern. Work duplicated and diverged from the existing one without rationale.

### Probe 6 — Quantitative-claims discipline

**Applies when** the plan contains a quantitative impact claim (cost reduction, throughput delta, multiplier, LOC estimate, savings per period).

Classify the stakes and apply the required rules per tier:

| Tier | Triggers | Required |
|---|---|---|
| **high** | cost > $500/day OR > 5 roles OR public-facing | probe-before-claim + steel-man-alternatives + evidence/inference separation + cost-band + confidence-bias check |
| **medium** | cost $100-500/day OR 2-4 roles OR multi-day effort | evidence/inference separation + cost-band + 1 alternative canvassed |
| **low** | cost < $100/day OR single-file change OR small LOC est | qualifier «approximate» — no probe required |

**Inline format (claim in the plan):**

```yaml
quantitative_claims:
  - claim: "~310 LOC implementation cost for graph build + query CLI"
    stakes_tier: medium
    evidence:
      source: prior_estimate
      artifact_ref: " §implementation_plan_day_4 ~280 LOC"
    inference: "extension adds ~30 LOC for rule extraction"
    second_pass:
      completed: true
      assumptions: ["build script stays single Python module"]
      denominators: ["LOC counted without tests"]
      alternatives_canvassed: ["could split rule extraction in separate script (~50 LOC overhead)"]
    cost_band: "~280-340 LOC"
```

**Inline format (no quantitative claims):**

```yaml
quantitative_claims: none
```

Finalization with unannotated high- or medium-magnitude claim forbidden.

**Slip example (v1 origin):** Session #19 2026-05-14 — AI estimated «$1500/day cost reduction from backlog archive» without the probe-before-claim step. Owner corrected ( had already moved roles to excerpts, real ~$200-400/day). P6 would have surfaced the stale-state assumption before the utterance.

### Probe 7 — Deliverable→artifact completeness (judgement-only; the grep-able checks are mechanized)

**The id/path-resolution and prose-only-deferral checks of this probe are now MECHANIZED** by the
`plan check` structural pre-pass — they are recorded in the verdict automatically and no longer rely on
this manual memo (the incident: a manual checklist item is skippable). The SINGLE normative home
of the standing rule + the mechanized-validator scope is **`specs/SPEC-0040`** (supersedes SPEC-0037, ex-SPEC-0012); `patterns/plan-lifecycle.md`
carries only a pointer there.

**What `plan check` now checks for you** (report-not-block; recorded in `structural_findings:`):
- every referenced `T-`/`SPEC-`/`D-XXXX` id and every "Depends on" code-path resolves against the tree;
- every fixed-phrase deferral ("deferred to Part N" / "doctrinal-only-until" / "until tooling") is
  carried by a tracked id in the SAME bullet/paragraph or a `deliverables_mapping` block — never prose.

**What stays a JUDGEMENT item here (the tool cannot decide these — delegate to external audit-pre):**
- **enumerate-halves (completeness).** The tool only checks what is WRITTEN; YOU must enumerate that
  EVERY half of a carve appears at all — a deliverable simply omitted is invisible to a resolver.
- **probe-quality.** Each part's `adoption_probe` must be genuinely observable (event / state /
  measurable), not a probe in name only. "Has a probe field" is mechanizable; "is it a good probe" is not.
  The deeper plan-time probe-quality discipline (calibrate to OBSERVED behaviour, enumerate the
  state-space, back purity claims, root-rewrite a ≥2×-hit area — the **E-0016** planning-quality root)
  lives single-sourced in **SPEC-0046 red-flag (c)** (P5 one-home — pointer, not a copy).
- **one-route.** Each deferral/capture routes to exactly ONE home (no duplicate owners).
- **one-regime-per-plan (plan-split, P7-adjacent).** Do ALL the plan's parts share ONE convergence
  regime / one fate — does a single accept/realize/reject verdict honestly cover them? Split signals
  (any YES → recommend separate plans with informational cross-refs — tracked ids, NO `requires:`
  between plans): different validation horizons (one part provable now, one needs accumulated real
  data) · independently rejectable fates · one part consumes the other's real-data output. Trial-FSM
  carve-out: a trial-eligible plan's own trial→executing sequence is ONE regime, NOT a split signal.
  Rule home: the active decomposition-discipline head `specs/SPEC-0040` §A2 (prior-art: the
  2026-06-05 soak-pair split).

**Inline format (the structured carrier the pre-pass reads):**

```yaml
deliverables_mapping:
  - deliverable: "Part A — meta-spec doctrine"
    artifact: SPEC-0005 # tracked id (task / spec / parked-task) — NOT prose
    adoption_probe: "SPEC-0005 status: active (state-check)"
prose_only_deferrals: none # any "deferred to Part N" with no id = a hole (now also auto-checked)
```

**Slip example (real V2 incident — deviation fingerprint
`carve-out-drops-base-layer-tooling-via-prose-only-deferral-no-task`, 2026-06-01):** carving Part A of
the doc-model-rework collapsed it to "author the meta-spec"; the TOOLING half lived as PROSE inside a
spec body ("doctrinal-only-until-tooling") with no tracked task, invisible to the picker until a later
take-into-work surfaced it as a blocked dependency. That prose-only deferral is now caught
deterministically by the `plan check` structural pre-pass (SPEC-0040) — not left to this manual memo.

## Filing format

After passing all 7 probes, add to the plan's opening section:

```yaml
checklist_pass:
  P1: documented # parked traverse: N entries checked, inline annotations
  P2: documented # per-layer breakdown for D-XXXX refs
  P3: documented # done_definition block with owner_confirmed: true
  P4: documented # external_review block (or skipped with owner_approved)
  P5: documented # cross_checked_patterns list
  P6: documented # quantitative_claims block (or «none»)
  P7: documented # deliverables_mapping block + prose_only_deferrals: none + per-part adoption_probe
```

Missing any probe = the plan is not final.

## Anti-pattern

«I'm a good AI, I already know what needs checking» — the checklist exists precisely because without mechanical traversal probes get skipped systematically. This discipline is not for smart agents, but for **complete agents** (smart + disciplined).

## Dry-run rehearsal — survives the plan contact with real material? (complementary method)

A **separate, complementary** validation method — NOT a numbered probe. The 7 probes above check a plan's
**internal quality** (completeness, honest claims, owner-aligned «done», deliverable→artifact mapping).
Dry-run rehearsal checks
something they cannot: whether the plan's **RULES survive contact with real material**. A model or
governance change can be internally coherent on paper and still break the moment it meets actual
artifacts. **This method stays OUTSIDE `checklist_pass`** — it adds no probe, no required field, and
changes the Filing format not at all; reach for it by judgement (see «When»), not as a gate.

**Codification, not invention — prior-art:** dry-run / tabletop exercise · specification-by-example
(execute the rule on a concrete example) · dogfooding · dual-independent-review.

**The 5 properties that make it work:**
1. **Real inputs, not hypotheticals** — apply the proposed rules to actual material (spec-by-example
   spirit); a walkthrough of imagined cases does not count.
2. **Dogfood** — the best material is the model's OWN artifacts (run the new doc-rule over the existing
   specs/decisions; run the new spec-doctrine over itself).
3. **Two independent passes** — a self pass AND a full-capability external pass, run **SEPARATELY then
   COMPARED**; divergence between them pinpoints the weakest spot (a lone pass is provably insufficient).
4. **Iterative + NON-PERSISTED** — apply → find a seam → refine the rule → re-apply; only the converged
   CONCLUSIONS are written down, the trial runs are not (they are scaffolding, not artifacts).
5. **Validates the MODEL/rules, not the output** — the yardstick is «do the rules hold?», not «is this
   one artifact good?».

**When to reach for it:** a model / governance change, OR a big plan whose **RULES** (not merely its
steps) are novel — where coherence-on-paper is insufficient and contact with real material is the only
honest test. For a plan that only sequences known steps, the 7 probes suffice.

**Worked application (do not duplicate — link only, P5):** the dual-run discipline in
`plans/doc-model-rework-retire-decision-unify-on-spec-spe.md` §«STANDING PROCESS RULE for Part F
migration» is ONE concrete application of this general method (it caught a materially wrong «resolve 19
Accepted» step that a lone self pass had). That rule's text lives there; this section is the
general method it instantiates.
