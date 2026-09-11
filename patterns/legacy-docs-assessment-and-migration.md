---
name: legacy-docs-assessment-and-migration
class: runbook
sourced_from: the 2026-07-18/19 aiseller + boomrocket legacy-docs semantic audits (kernel session; aiseller 243 claims / boomrocket 111 claims verified against code) + the external-audit consult `decisions/docs-legacy-governance-aiseller-audit-adhoc.yaml` (YELLOW — model confirmed, 4 refinements folded in) + owner directive 2026-07-19 «методику записать в ранбук». Routed to consumers as X-0516/X-0517/X-0518 (aiseller), X-0519/X-0520 (boomrocket).
applies_to: any brownfield project migrating onto v2 that carries a pre-v2 prose docs corpus (docs/*.md and kin) — and any already-migrated consumer that never assessed its corpus. Reached from patterns/onboarding-onto-yitc-runbook.md §Branch B (the brownfield path); self-runnable by a consumer on an owner cue.
---

# Legacy-docs assessment & migration — the measured path from a prose corpus to governed v2 homes

> **The problem this closes.** A migrated project inherits a legacy prose corpus that LOOKS
> authoritative and is measurably part-false. Measured on two real corpora (2026-07): aiseller —
> 50% of 243 checkable claims true, 12% direct lies, 23% never-built-described-as-existing;
> boomrocket — 63% of 111 true, 12% lies. An AI session that trusts such a corpus hallucinates
> WITH CITATIONS — the doc is the fuel. The fix is NOT a mass rewrite: it is measure → triage →
> banner → lazily promote into governed homes, with the dangerous docs fixed first.

## Phase 0 — Inventory (minutes, read-only)

1. Corpus map: files/lines per `docs/` subdir.
2. Age histogram: `git log -1 --format=%cs` per file, bucketed by month. The pre-migration bulk
   is your legacy candidate set; anything actively touched is a different animal.
3. Origin note: which dirs are DATED plans/archives BY NAME (honest historical framing) vs
   undated files claiming current reality. Dated-plan culture (boomrocket) measurably halves the
   asserting-lie surface vs intent-as-reality culture (aiseller).

## Phase 1 — Mechanical scan (cheap, ~1 hour, no agents)

Two greps with classification — they give the corpus-health HEADLINE before any semantic work:

1. **Dead path refs.** Extract path-like refs (adapt the prefix set to the repo: `backend/ frontend/
   bin/ scripts/ …`), check existence. Classify each DEAD ref by context: inside a plan-natured dir
   OR with future-markers in ±3 lines («будет/план/TODO/Phase/deferred/planned…») → **dead-plan**
   (honest); else → **dead-ASSERTING** (the lie signal). Report: alive % / dead-plan % /
   dead-asserting %. Calibration: aiseller 60/24/16, boomrocket 69/13/17.
2. **Ghost symbols.** Extract backticked code-like identifiers near alive path refs; check
   (a) in the named file, (b) anywhere in the codebase, (c) nowhere. Bucket (c) — the GHOSTS —
   is pure signal: names asserted that exist nowhere (aiseller's ghost list contained the
   documented-but-never-built money guard). Bucket (b) is mostly pairing noise — do NOT read it
   as drift without Phase 2.

**Stop-rule:** if dead-asserting < ~5% AND the corpus is small/young, a per-file LEGACY banner may
be skipped — go straight to Phase 3 triage of any dangerous docs found.

## Phase 2 — Semantic verification (agent fan-out, hours)

Mechanical scans cannot judge content. Fan out READ-ONLY analysis agents, one per load-bearing doc
set, priority-ordered by blast radius:

1. **Money / absolute-ban paths first** (pricing rules, guards, messaging bans) — strongest model.
2. **Operational docs** (deploy, testing, runbooks) — these kill when wrong.
3. **Product concept / architecture / user-flows** — volume tier.

Each agent: extract every CHECKABLE claim (path, symbol, number, described rule/behavior), verify
against code, verdict per claim: **верно / переехало / не-построено / ложь / непроверяемо**, each
with `file:line` evidence; flag `MONEY_RISK` / `BAN_RISK` / `DANGER` explicitly. Aggregate into one
table. ~10–15 docs ≈ 10 agents ≈ 100–250 verified claims — enough for a corpus verdict.

**Known false-positive traps (fold into agent prompts):** extension renames (.js→.jsx) read as
dead; symbols listed in tables get cross-paired with neighbouring files; config keys live outside
py/js; a guard may exist under another name/place — search by MEANING before verdicting
«не-построено» (aiseller's money lint existed as a CI pytest, not the documented script).

## Phase 3 — Triage into five classes (each with its own action)

1. **Actively-dangerous docs** (teach a harmful command: non-hermetic tests against live DB,
   obsolete manual deploy, false «hard guardrail» wording on a money path) → **FIX FIRST, now** —
   a banner does not defuse an instruction someone follows.
2. **Auto-generated docs that lie** (a generator re-asserting dropped tables/endpoints) → fix the
   GENERATOR or retire the automation. Automation must not mint lies — it out-crediblizes any
   banner.
3. **Money/ban-path claims** → promote CURRENT VERIFIED behavior + known hazards into specs NOW
   (not lazily); unsettled build-vs-redocument forks stay EXPLICIT owner decision points — never
   silently promote an unsettled choice as a rule.
4. **Honest historical** (dated plans, archives, superseded layers) → keep, ensure a per-file
   HISTORICAL header + pointer to the live successor. Verify the freeze claim is TRUE (boomrocket's
   «no longer edited» catalog was edited 3× after the freeze note — a false freeze header undermines
   every other header).
5. **Everything else** → per-file **LEGACY banner** in one mechanical commit («не источник истины;
   правила — в specs/, сверяй с кодом»), inserted after the title. Per-FILE, not per-dir — deep
   links skip a dir README.

## Phase 4 — Lazy promotion into governed v2 homes (MANDATORY, not advisory)

- **The rule (external-audit refinement 1):** any task that touches a legacy-documented topic MUST,
  in that same task, verify + promote the relevant section to its governed home — or tombstone /
  explicitly mark it. Advisory cleanup recreates the stale corpus.
- **Routing:** standing rules → `specs/` (with `implements:` links — the graph then watches
  freshness); user paths → `scenarios/`; local craft → `lessons/`; product intent → the product
  `CHARTER.md`/living concept. The promoted legacy section is deleted or left as a tombstone
  pointer.
- **Spec→docs pointers (refinement 2):** inventory every spec that points into `docs/`; label each
  `historical-context | migrate-normative-source | delete`. No spec may normatively depend on a
  LEGACY doc.
- **Never bulk-import** legacy prose into specs — that re-dresses unverified claims in governed
  clothing and spends the graph's trust.

## Phase 5 — Keep it honest (steady state)

- The Phase-1 mechanical scan is re-runnable and cheap — a consumer may wire it as a report-only
  debt-echo line; do NOT build a gate on it (report-only, CHARTER §P1).
- Every future migration runs this runbook at Branch-B time (the pointer lives in
  `patterns/onboarding-onto-yitc-runbook.md §Branch B`), so a corpus is measured BEFORE it starts
  feeding sessions.
- Calibration corpus for estimates: aiseller 2026-07-19 (243 claims: 50/10/23/12/5) ·
  boomrocket 2026-07-19 (111 claims: 63/14/4.5/12/7) — order: верно/переехало/не-построено/ложь/
  непроверяемо.
