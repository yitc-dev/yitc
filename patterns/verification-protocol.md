---
name: verification-protocol
class: discipline
sourced_from: chat directive 2026-05-26 (owner-articulated need); refined per external auditor 2026-05-26 (5 Pass 1 findings absorbed + owner additions)
applies_to: post-work / ratification verification — task closure, decision ratification, phase milestone, ad-hoc «prover' sdelannoe po protokolu» ("verify what was done per the protocol")
---

# Verification Protocol — self-check + independent external check

> Owner-invokable verification for **already-done** work (post-work or at-ratification).
> Two parallel tracks (AI self-check + external auditor) run **same matrix INDEPENDENTLY**.
> Compare AFTER both done. Divergence = meta-finding with **bounded escalation**.
>
> **Scope distinction (per external auditor finding F5 reframe):** post-work holistic verification across all
> principles. **NOT** generic discipline prompt; **NOT** pre-work planning gate (sister pattern
> `big-plan-checklist.md` covers plan authoring).

## Purpose — diagnostic lens (owner-articulated 2026-05-26)

Verification protocol = **base YITC audit for surfacing problems and causes of AI-development specifically.** Distinguishes 4 problem-class categories (owner framing):

| Category | What catches | Source dimensions |
|---|---|---|
| **«Wrong-thing»** (wrong scope/target) | AI worked on wrong scope or wrong target | D6 (no role-split creep) + D11 failure class #6 Scope creep |
| **«Wrong-way»** (wrong method/sequence) | AI used wrong approach or skipped stages | D9 LIFECYCLE conformance + D11 #11 audit-loop / #14 multi-variable |
| **«Wrong-time»** (wrong time/order) | Action taken too early or too late in lifecycle/queue | D9 queue state transitions + D10 decision status transitions |
| **«Not-told-the-AI»** (missing instruction/context) | AI didn't have right context or instruction (or didn't read what was told); owner didn't articulate | **D13 events.jsonl forensic analytics** — instruction_injected events scan (what AI consulted) + owner_directive events (what AI was told) = trace gap WHO failed (AI miss or owner missing brief) |

**Niche distinction from sibling mechanisms:**
- `audit-pre / audit-post` (AGENTS contract) = catches code/diff drift per specific change
- `big-plan-checklist` = catches plan-authoring drift pre-finalization
- **`verification-protocol` = catches AI-instruction-execution-loop drift** — layer above code and plan, holistic across all V2 principles

## When invoked

Owner says: «prover' sdelannoe po protokolu» ("verify what was done per the protocol") / «verify X» / similar. Applies to:
- Task closure verification (after Stage 9 or for check before closure)
- Decision ratification check (Draft → Accepted or Accepted → Final)
- Phase milestone closure
- Ad-hoc «is this correctly done» query from owner

**NOT applies to:**
- Hygiene fast-path work (LIFECYCLE §Hygiene catalog)
- Routine in-progress status (`yitc status` or similar)
- Pre-work plan authoring (use `big-plan-checklist.md` instead)

## Two parallel tracks

| Track | Who performs | Artifact |
|---|---|---|
| **A — Self-check** | AI runs matrix on own work | `decisions/<scope>-self-check.yaml` |
| **B — External audit** | External auditor (full or mini per task tier) | `decisions/<scope>-external-verify.yaml` |

**Procedural independence rule:** AI completes self-check BEFORE seeing external output. Compare AFTER both done.

**Independence claim — honest scope (per external auditor finding F4):** this is procedural independence, not strong scientific objectivity. Both tracks see same files + same matrix + know comparison coming. Real signal narrower: **evidence asymmetry / missing-context asymmetry / interpretation drift detection**.

## Verification matrix — 13 dimensions

Each dimension cites existing mechanism (1:1 mapping — no invention). For each: **PASS / FAIL / N/A with specific evidence or gap**. Skipping dimension = failure (class #8 False confidence).

| Dim | Principle / mechanism | Probe questions |
|---|---|---|
| **D1** | CHARTER P1 Anti-complexity | 4 filters applied? PASS each? F3 «what removes» concrete? |
| **D2** | CHARTER P2 Documentation-first | `from:` cite present + durable target + Bootstrap exception correctly applied? |
| **D3** | CHARTER P3 Done = Adopted | Probe evidence captured? adoption_probe.status = passed? Probes verifiable (shell command or state check)? **Hard sub-probe (per external auditor 2026-05-26 — operationalize failure class #8):** any claim of tests passed / reads done / audits run / probes passed / transitions made / adoption confirmed MUST point to visible artifact / output / event. Verbal claim without visible artifact = FAIL. |
| **D4** | CHARTER P4 AI Independence | Provider-neutral in normative text? External audit from different provider from primary? |
| **D5** | CHARTER P5 Single SoT | No parallel storage / parser? One format / one journal preserved? |
| **D6** | CHARTER P6 Build+Review only | No pipeline / role-split crept in? |
| **D7** | CHARTER P7 Dissonance | Contradictions filed as decisions or escalated? NOT silently chosen? |
| **D8** | CHARTER P8 Adoption Strength | Infra-class? If yes — consumer-read OR live-trigger evidence? Or «inaugural exempt»? |
| **D9** | LIFECYCLE conformance + queue transitions | **All 9 stages executed** (or Hygiene fast-path with explicit catalog match)? **No stages tacitly skipped** (any skip has explicit rationale)? Audit-pre + audit-post performed? **Queue state transitions explicit** (per QUEUE.md §State transitions — authoritative state list)? Stage 9 probe pass verified? |
| **D10** | Decision lifecycle conformance | Status transitions explicit (Draft → Accepted → Final / Superseded / Withdrawn)? `resolution:` filled at Accepted? `adoption_probe` defined with status transition path? |
| **D11** | AI failure classes scan + hallucinated-context evidence check | Which of the 20 classes were relevant to work? Watched during execution? Incidents observed? Pattern detected (≥ 2 instances) → file decision? **Hard sub-probe (per external auditor 2026-05-26 — operationalize failure class #7 Hallucinated context):** Did verifier confirm all material claims against cited files / diff / visible outputs? Or any claim based on uncited assumption? Uncited assumption = FAIL. |
| **D12** | Big-plan-checklist applicability | **Verifies WHETHER checklist was invoked + documented when required** — NOT re-runs checklist (per external auditor finding F3). Plan triggers checklist (substantive — foundational / ≥3 canonical files / quantitative / multi-step)? If yes — `checklist_pass` block present? If no — verified that work didn't qualify? |
| **D13** | Events.jsonl forensic analytics + manual read-completion fallback | **Owner-articulated 2026-05-26 — analyze cause of problems via journal.** Trace gap WHY: `instruction_injected` events (what AI told), `owner_directive` events (commands AI got), `failed_attempt`, `dissonance_detected`, missing-expected events. **Honest limitation (per external auditor 2026-05-26):** D13 detects injection presence + directive presence, **NOT read completion**. Until `instruction_read` events ship (deferred per AGENTS reverse-mapping query notes) — **manual fallback sub-probe for each MUST_READ_NOW or task-critical owner_directive:** check later AI response for content awareness (section citation / accurate paraphrase / rule-constrained action). If absent — mark «possible unread/unincorporated instruction; events insufficient to distinguish». **Owner-side root-cause classification** (per external auditor 2026-05-26) — for each gap found: classify as `AI missed despite adequate brief` / `brief ambiguous or incomplete` / `both`. Ask: «were scope + target + timing + success condition in durable artifacts before execution?» |

## Self-check format (Track A output)

AI emits YAML structured report:

```yaml
self_check:
  date: YYYY-MM-DD
  scope: <description of work being verified>
  verifier: ai-agent

  D1_anti_complexity:
    filters: [F1: PASS, F2: PASS, F3: PASS, F4: PASS]
    verdict: PASS
    notes: <one-line evidence or n/a>

  D2_documentation_first:
    from_cite: <path:line or «n/a»>
    durable_target_valid: yes
    bootstrap_exception_applied: yes | no | n/a
    verdict: PASS | FAIL

  # D3-D12 similar shape

  D13_events_forensic:
    instruction_injected_count: <N>
    owner_directive_captured: <count or n/a>
    failed_attempt_events: <count or list>
    dissonance_detected_resolved: yes | no | n/a
    missing_expected_events: [<list if any>]
    verdict: PASS | FAIL

  overall_verdict: GREEN | YELLOW | RED
  gaps_identified: []
  followups_proposed: []
  confidence: <0.0-1.0>
```

## External audit invocation (Track B)

Invoke external auditor (full-capability mode) with prompt:

```
# Verification audit — <scope>
Apply V2 verification matrix (13 dimensions D1-D13 per patterns/verification-protocol.md).
For each dimension: PASS / FAIL / N/A with specific evidence or gap.
Output: structured response per dimension + overall GREEN/YELLOW/RED verdict.

Files to review: <list>
Context: <description>
Scope being verified: <scope>
```

Save output: `decisions/<scope>-external-verify.yaml` — converted to V2 audit_verdict schema.

## Comparison + action (with bounded anti-recursion per external auditor finding F1)

After BOTH tracks complete — compare results inline (not separate artifact unless divergence):

| Self-check | External | Action |
|---|---|---|
| GREEN | GREEN | ✅ **Done verified** — no further action; comparison NOT saved as separate file (ephemeral per external auditor finding F2) |
| GREEN | YELLOW (medium) | Absorb external findings inline (max 2 absorption passes per audit-loop ceiling) |
| GREEN | RED | **Investigate divergence** — possible AI false confidence (failure class #8). File observation. **One targeted absorption cycle.** |
| YELLOW | GREEN | **Investigate divergence** — possible AI over-cautious or external missing context. **One targeted absorption cycle.** |
| YELLOW | YELLOW | Merge finding lists; absorb inline (max 2 passes) |
| RED | * | Escalate to owner; rethink |
| * | RED | Escalate to owner; rethink |

## **Bounded anti-recursion stop rule (per external auditor finding F1 — CRITICAL)**

**One comparison pass authoritative.** Unresolved divergence after one targeted absorption cycle → **escalate to owner**, not second full protocol run.

**Different gaps from two tracks (per external auditor 2026-05-26 clarification):** if self-check finds gap A and external finds different gap B — absorb union (A + B) in **ONE targeted absorption cycle**. This is OK and intended.

**Hard rule: NO verification-of-verification.** If comparison artifact itself disputed → escalate immediately. **Do NOT run verification-protocol on verification-protocol output.** If absorption itself creates new inconsistency about verification result → escalate immediately, NOT re-run full protocol.

This prevents accretion spiral exactly like CHARTER §Failure trigger guardrails.

## Save trail (minimal — per external auditor finding F2 absorption)

| Artifact | Saved when | Location |
|---|---|---|
| Self-check report | Always | `decisions/<scope>-self-check.yaml` |
| External audit verdict | Always | `decisions/<scope>-external-verify.yaml` |
| Comparison summary | **ONLY if divergence** (GREEN/YELLOW or GREEN/RED or YELLOW/GREEN) | `decisions/<scope>-verification-summary.yaml` |

GREEN/GREEN case = ephemeral comparison (mentioned in commit message; no separate file). Cuts artifact fan-out per external auditor finding.

These integrate with GRAPH audit_verdict node type — verification = extended-form audit, not new node type.

## Anti-pattern

"I checked, all fine" without structured matrix → unverifiable claim. **Each of 13 dimensions MUST be explicitly assessed**. Skipping dimension = failure class #8 (False confidence).

## Refs

- CHARTER §The 8 Principles (D1-D8)
- LIFECYCLE.md (D9 — stages + Hygiene fast-path + Resume contract)
- QUEUE.md (D9 — queue state transitions)
- CHARTER §Decision lifecycle (D10)
- CHARTER §AI failure classes anticipated (D11)
- patterns/big-plan-checklist.md (D12 — sibling pattern for plan authoring; verification-protocol verifies invocation, not re-runs)
- AGENTS.md §events.jsonl schema (D13 — forensic analytics source)
- AGENTS.md §External auditor invocation contract (audit mechanics)
- — codification decision
