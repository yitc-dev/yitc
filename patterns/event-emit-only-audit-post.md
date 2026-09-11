---
name: event-emit-only-audit-post
class: discipline
sourced_from: <durable artifact> closure (commit 5ec3114) — first observed case 2026-05-28; codified
applies_to: Stage 8 audit-post on tasks where ship = single events.jsonl emission (adoption probe per CHARTER §Principle 8), not accompanying code diff
---

# Pattern: event-emit-only audit-post category mismatch

Stage 8 audit-post template assumes ship = substantive code/spec diff
auditable in isolation. **Event-emit-only ships** (1-line `events.jsonl`
addition where the emission IS the substance, not accompanying code) trigger
auditor structural-incompleteness flag — closure-metadata absence misread
as defect.

## First observed case

**** (CHARTER §Principle 8 adoption probe for `AGENTS.md§After
/compact`):

- Ship commit `7333dba` = 1 line to events.jsonl (`consumer_read_evidence` event)
- Audit-post verdict: RED (high) — «shipped diff emits event but does not
  perform the required Stage 9 closure»
- Auditor's own notes field explicitly validated AC1+AC2 satisfied by event
  content: «AC1 appears satisfied... AC2 appears satisfied... the blocker is
  missing adoption/closure, not the event content itself»
- Finding type = category mismatch: Stage 9 work absence flagged as Stage 8
  ship defect

## When this pattern applies

All three must hold:

1. Ship = single event emission to `events.jsonl` (or ≤3 events bound
   semantically as «the probe»)
2. Task class = `infra` or `docs` (NOT `feature` or `fix` with code diff)
3. Adoption-evidence IS the substance per CHARTER §Principle 8 (consumer-read
   or live-trigger evidence)

## When this pattern does NOT apply

- Code diff exists in ship commit → audit-post evaluates diff normally; closure-
  absence finding would be valid drift signal
- Multi-event or event+code ships → whole-ship evaluation appropriate
- Hygiene fast-path tasks (skip audit-post entirely per LIFECYCLE §Hygiene
  Fast-Path) — adoption-probe events are NOT hygiene by semantics; lifecycle
  Stage 8 still applies

## Resolution paths

### (PRIMARY) The `--event-emit-only` audit-post flag (SHIPPED —)

The standing mechanism. When a task's adoption probe IS a single Stage-9-recorded
P8 event (event-emit-only ship), run audit-post with the flag:

```
bin/yitc-v2 audit post --task T-XXXX --event-emit-only
```

The flag (option (i) of the reopen design) adds a carve-out paragraph to the
audit-post overlay (`_build_audit_prompt`): the P8 event lands in a SEPARATE
Stage-9 commit AFTER this audit, so its absence at audit-post is EXPECTED and is
NEVER a finding / RED — the auditor judges ONLY diff-drift / non-adoption AC /
coherence. This operationalizes the contract's own "closure-time emission would
post-date you" exemption (SPEC-0036 audit-post overlay). The flag is:

- `--task`-scoped (rejected for `--decision` / `--plan`);
- registered ONLY on the `post` subparser (parse-rejected on `audit pre`);
- the explicit per-task opt-in signal (same trust model as `--owner-reset` /
  `--focus`) — recorded as `event_emit_only: true` in the saved audit YAML for a
  durable trail of which verdicts were carve-out-gated.

### (a) Plan-time absorption — DOCUMENTED FALLBACK (was primary for first-N observations)

Use only when the flag is unavailable (degraded/emergency mode) or the auditor
RED-flags despite the overlay. Task plan explicitly states: «audit-post may
RED-flag closure absence as defect — this is category mismatch per
`patterns/event-emit-only-audit-post.md`; absorbed via Stage 9 execution per
plan». Then:

1. Run audit-post normally — accept RED verdict
2. In `decisions/T-XXXX-audit-post.yaml`: set `absorbed=[finding-idx]`,
   `absorption_notes` explicit that finding = category mismatch
3. Close via LIFECYCLE Stage 9 hand-edit fallback (CLI blocks on RED audit-
   post precondition — this is a known edge case)
4. Commit closure separately per atomic-commit pattern

### (b) Hygiene fast-path — NOT applicable

Adoption-probe events enforce CHARTER §Principle 8 substantively. Skipping
audit-post via fast-path bypasses the verification intent.

### (c) Future mechanism (reopen trigger)

If pattern recurs **≥3 times across distinct tasks** still RED-flagging
closure absence — reopen for mechanism design:

- Option (i): `bin/yitc-v2 audit post --task T-XXXX --event-emit-only` CLI
  flag that adds prompt overlay instructing auditor: «expect closure
  metadata to follow in separate Stage 9 commit; do not flag absence as
  defect»
- Option (ii): audit-post prompt template gains conditional section based
  on task class or ship-commit-diff size heuristic

Until N≥3 reached, mechanism = imagined necessity per CHARTER §Principle 1
F4. Plan-time absorption sufficient.

## Reopen tracker

| Date | Task | Verdict | Pattern applies? |
|---|---|---|---|
| 2026-05-28 | | RED | Yes — first observed case |
| 2026-06-05 | | RED | Yes — AC2 adoption is a `consumer_read_evidence` event; ship diff carried the spec edit (AC1 GREEN), RED only on the event-not-in-diff |
| 2026-06-05 | | RED | Yes — AC2 adoption is a `consumer_read_evidence` event recorded at Stage-9; ship diff is the reader code (AC1 GREEN 10/10), RED only on event-not-yet-emitted. **3rd «Yes» → reopen trigger N≥3 REACHED; mechanism follow-up filed** |

**REOPEN TRIGGERED (2026-06-05): 3 «Yes» rows reached.** Mechanism design
deferred-no-longer per CHARTER §P1 F4 (the incident threshold is now real, not imagined). Follow-up
filed for the `audit post --event-emit-only` overlay (option i/ii above).

**REOPEN CLOSED (2026-06-06):** mechanism SHIPPED — option (i) `bin/yitc-v2 audit post
--task X --event-emit-only` (see §Resolution paths PRIMARY). Plan-time absorption (resolution (a))
is now the documented fallback, no longer the standing mechanism.

## Sibling carve-out — serve/deploy (SPEC-0094 §5)

The SAME deferred-adoption family has a sibling flag, `audit post --task T-XXXX --serve-deploy`,
for a serve/deploy task whose ship is a live deploy (an ACTION, not a code diff): live-adoption is
proven at the deploy seam + recorded at Stage-9 Closure (the per-change `live_probe` evidence), so adoption-absent at the diff-only audit-post is EXPECTED, never RED. It removes the
X-0039 owner-reset/ceiling-burn. Same overlay/recording shape as `--event-emit-only`
(records `serve_deploy: true` in the saved verdict YAML). Home: SPEC-0036 §SERVE/DEPLOY carve-out
+ LIFECYCLE §Stage 8.

## Sibling carve-out — land-emitted non-P8 acceptance event (SPEC-0036 / X-0188)

The GENERALIZATION of `--event-emit-only` to a NON-P8 event. `--event-emit-only` exempts ONLY a
Stage-9-recorded **P8** closure event (`consumer_read_evidence` / `live_trigger_evidence`). But a
task's acceptance probe can instead be a NON-P8 event **emitted by `land` at Stage 9** — e.g.
`verify_layer_prep` (a layer-prep event the `land` verb records). At the diff-only, pre-land Stage-8
audit-post that event legitimately does not exist yet, and because the event-emit-only overlay text
is P8-closure-event-specific, the auditor does NOT extend the exemption to it → the base audit-post
false-REDs "acceptance probe not satisfied" (the X-0188 gap — burned 2 RED passes + a
convergence consult on this structural false-RED).

The standing mechanism is the sibling flag:

```
bin/yitc-v2 audit post --task T-XXXX --land-emitted-event
```

It adds a carve-out paragraph telling the auditor a declared land-emitted NON-P8 acceptance event's
absence at audit-post is EXPECTED (the event is recorded when `land` runs at Stage 9, AFTER the
audit), never a finding / RED — the auditor judges ONLY diff-drift / any non-deferred AC / coherence.
Same overlay/recording shape as `--event-emit-only` (`--task`-scoped, registered ONLY on the `post`
subparser, records `land_emitted_event: true` in the saved verdict YAML). Home: SPEC-0036
§LAND-EMITTED-EVENT carve-out + LIFECYCLE §Stage 8.

## References

- CHARTER §Principle 8 (Adoption Verification Strength for Infrastructure)
- LIFECYCLE Stage 8 (Audit-post)
- LIFECYCLE Stage 9 (Closure) — hand-edit fallback path
- closure (commit `5ec3114`) — first absorption example
- AGENTS §audit-prompt-principles — per-stage overlays section (future mechanism location)

## Status

**Active — mechanism SHIPPED (2026-06-06).** The `bin/yitc-v2 audit post --task X
--event-emit-only` flag (§Resolution paths PRIMARY) is the standing mechanism: it adds an
audit-post overlay carve-out so a Stage-9-recorded P8 adoption event is not RED-flagged as a
Stage-8 ship defect. Plan-time absorption (resolution (a)) is DEMOTED to a documented fallback
(degraded/emergency mode, or auditor-REDs-despite-overlay). Reopen trigger (N≥3:) is CLOSED.
