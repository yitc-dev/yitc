---
name: inspection-triage-launch-runbook
class: discipline
sourced_from: owner-directive 2026-06-07 ( — "delaem review i triazh" ("we do review and triage") must deterministically launch a named procedure) + the 2026-06-07 manual dual-track inspection+triage run (the real incident — full 8-theme inspection + test triage orchestrated by hand with no named procedure) (established the inspection construct — provenance; live home SPEC-0057) + the inspection living criteria home patterns/inspection-criteria-roster.md (the single living roster + run-mode + per-theme lens-checklists; retargeted here by from the realized roster plan) + SPEC-0056 (triage routing/sink; established by §5) + SPEC-0055 (triage-run window + §Batch-run journal isolation) + SPEC-0052/ (displacement-retention sweep) (batch emit isolation) + patterns/background-session-operation.md (foreground-default / trial-background)
applies_to: an owner-invoked combined inspection + test-triage run — when the owner says the trigger phrase, this runbook is the named, repeatable LAUNCH procedure that sequences the existing pieces. This pattern is the SEQUENCING/navigation only — every rule it invokes homes elsewhere (it cites, it does not restate; SPEC-0005 rule 8 one-home). Provider-neutral by rule (CHARTER §P4b).
---

# Inspection + triage launch runbook — the owner-invoked how-to

> **What this IS:** a navigational/procedural VIEW that chains FOUR existing pieces into ONE named
> launch order so a single owner phrase runs the whole thing deterministically. It introduces **no
> new mechanism, verb, store, or rule** — each step's authority lives in its own home, cited inline.
> **Provider-neutral by rule (CHARTER §P4b):** the body names abstract roles only — "primary track",
> "external blind-first track". Concrete tool/provider bindings live ONLY in the cited run-mode /
> OPERATING-PLAN provenance, never in this normative procedure.

## §Problem

The inspection method + the triage method are both documented, and a one-off combined run was
performed by hand on 2026-06-07 (the full dual-track 8-theme inspection + a dual-track test triage,
orchestrated live in the interactive session). But there was **no named, repeatable owner-invoked
PROCEDURE** — so the owner phrase "delaem review i triazh" ("we do review and triage") did not deterministically launch it; each
run re-derived the orchestration from scratch. That ad-hoc re-orchestration is the cost this runbook
removes (CHARTER §P1 F3): the launch order becomes a named, grep-resolvable procedure instead of
session memory.

## §Solution — the named launch procedure

**Trigger phrase (owner-invoked):** the owner says **«reviziya+triazh»** (equivalently «delaem
reviziyu i triazh» / «delaem review i triazh») → run THIS procedure. Owner-invoked only — never
auto-scheduled, never a cron/hook (CHARTER §6/§7; the manual Review cadence in QUEUE.md is unchanged).

Run it in ONE `work/<slug>` worktree (the long-batch emit-isolation rule below). The four steps run
**in order**; step 4 (filing into work) is gated on an explicit owner go.

### STEP 1 — displacement-retention sweep FIRST

Run the displacement-retention sweep as the very first step (SPEC-0052; built by):

- `bin/yitc-v2 triage sweep` — archive closed-task audit YAMLs (idempotent; `--dry-run` to preview).
- `bin/yitc-v2 graph query displacement-retention` — the fired-unacted-trigger view: for EACH
  un-capped surface it measures the value AND looks up that surface's governing trigger, flagging
  `fired? / acted?`. A **fired-but-unacted** trigger is a flagged action — act on it (or capture it),
  do not report it as a clean number. A surface whose governing trigger has since been **RETIRED** is
  reported as a **report-only measurement** — `report_only: true`, no `fired`/`acted`/`flagged_action`
  keys, never in `flagged_actions` — because a permanently-lit flag on a withdrawn trigger only
  teaches you to skim the flag (the `tasks/` done-log count is the live example, retired by
). Read such a row as orientation, and raise its concern only on real observed friction.
  Authority for both shapes stays SPEC-0052 §1-2 — not restated here.

This is the launch-time backstop that catches the exact gap the 2026-06-07 run exposed (it measured
`events.jsonl=13.1MB` twice but never checked it against the 10MB trigger). Authority +
classifier + invariant: **SPEC-0052** (`bin/yitc-v2 graph query SPEC-0052`) / ****.

### STEP 2 — full 8-theme DUAL-TRACK inspection (blind-first external)

Run the full inspection per the **pinned run-mode** — the canonical authority is the inspection
living criteria home: **`patterns/inspection-criteria-roster-run-and-lenses.md` §Run-mode** (part-2 of
the roster, SPEC-0120 split) (the unified roster map in
`patterns/inspection-criteria-roster-navigation-map.md` and the per-theme lens-checklists T1–T10 across
part-1 `patterns/inspection-criteria-roster.md` (T1 / T3 / T7 / T9 / T10) and part-3
`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md` (T2 / T4 / T5 / T6 / T8,
SPEC-0120 split); SPEC-0057 §3 names it the living home,
SPEC-0057 §9 the cadence model). Do not restate the lenses here — read them there.

**Before you build a theme's sweep, read the three CONSTRUCTION rules** ( — rule text lives in
§Run-mode + §Cross-theme method, NOT here): construct the sweep from the theme's DECLARED probe roster
so an absent instrument yields a NO-DATA line rather than a silent omission · derive every verb→event
map from the emitters in `bin/lib` rather than from recollection · order candidates by blast radius as
well as by count. They govern how a sweep is BUILT, so they bind before the first probe runs — and all
three exist because the 2026-08-13 run's misses were caught only by the blind external track, i.e. they
entered at construction and no amount of care reading the output could reach them. Executable form:
`dev-utilities/reference-revizia-sweep-constructor.py`.

The pinned discipline, in brief (full text in §Run-mode):

- Each theme runs **DUAL-TRACK**: a **primary track** and an **external track**, independently, on
  the **same matrix** (the theme's lens-checklist in the roster); finding sets are compared
  **AFTER both tracks finish** (comparing during run lets anchoring eat the independence).
- **The first external pass of each theme is BLIND** (raw data, no primary candidates — its own
  analysis); verify/refute mode only from the second pass (method-lesson T3 run-1). The blind track
  **re-measures independently** and capture-sourced findings are **currency-verified before severity** —
  rule home: **SPEC-0057 §10** (this doc only SEQUENCES; §Anti-pattern no-duplication).
- **Track divergence on a theme = a weakness in the LIST** (a single-track finding is a blind spot of
  the checklist) → amend the checklist → re-run, until the finding sets converge.
- Findings flow into the **one nonconformity sink** as real captures: `captured_via: inspection`,
  with `inspection_theme`, source-independent `fingerprint` (SPEC-0056). Each theme run emits exactly
  **one `inspection_completed`** event (`criteria_ref` = the run-checklist hash) — record it with
  **`bin/yitc-v2 inspect record --theme T<n> --tracks primary,external`**, naming the tracks that
  ACTUALLY ran (`--tracks primary` alone for a single-track theme). The `--tracks` flag is what makes
  a half-run readable as one; omit it and the run records as coverage NOT RECORDED (full text +
  the flag's contract in §Run-mode / `inspect record --help`). Inspection is
  read-only observation, not a gate (SPEC-0057 — the inspection-construct normative home; established by
) — the run mutates neither corpus nor code.

#### STEP 2 addendum — external-track LAUNCH recipe (fit the wrapper, keep it read-only)

Two how-to rules for actually launching the **external track** (they add no new mechanism — they
capture two launch mistakes that produced ABORTed runs; the concrete tool/timeout binding lives in
the cited run-mode / OPERATING-PLAN provenance, kept OUT of this provider-neutral body per CHARTER
§P4b):

- **Split per-theme (or small batch), never one consolidated prompt.** Launch the external track
  **one theme (or a small batch of themes) per invocation** so each prompt fits the external
  wrapper's **per-invocation timeout budget**. A single consolidated all-theme prompt overruns that
  budget and the whole run ABORTs on timeout (real incident). Re-join the per-theme finding sets
  **after all invocations finish** — unchanged from the compare-after-both-tracks-finish rule above.
  **HEAVY repo-walk themes go STRICTLY ONE per invocation (owner directive 2026-07-16).** A theme
  whose probes make the auditor WALK the corpus (T6 operational-integrity, T7 durable-doc sweeps,
  the Architecture-drift lens) exhausts the timeout budget on WORK, not prompt size — a 3-theme
  T6+T7+arch batch ABORTed on the 300s timeout even with a small prompt (revizia 2026-07-16,
  fingerprint `external-track-3theme-batch-timeout-abort`), while the same themes re-launched one
  per consult with PRE-MECHANIZED sweeps all completed clean. So: light interpret-the-sweep themes
  MAY batch 2-3; heavy repo-walk themes ride solo, with the mechanical walking pre-computed into
  `--sweep-file` data first.
- **Budget the INLINE PAYLOAD too — size is an axis independent of theme count.** Splitting
  per-theme bounds how MANY themes ride one prompt; it does **not** bound how many BYTES the
  `--sweep-file` / `--read-corpus` channels inline into that same prompt. A **single-theme** consult
  with two large sweeps (80838B inlined) overran the very same per-invocation timeout the split
  recipe exists to prevent — so the recipe can be followed literally and still ABORT (real incident,
  X-0275). Keep total inlined bytes under the **~64 KiB budget**: pre-filter each sweep and narrow
  `--read-corpus` references to the **relevant functions or regions**, not whole files; when a theme
  genuinely needs more, split it into several smaller consults. `audit adhoc` **WARNs report-only**
  before invoking the auditor once corpus+sweep bytes reach that budget (never a gate — it proceeds;
  tune or disable via `YITC_ADHOC_PAYLOAD_WARN_BYTES`, `<=0` disables), so an oversized launch fails
  loud **before** it burns a full-model invocation rather than after the timeout wall.
- **Read-only prompt template — "may read, must not mutate", not "do not touch".** Phrase the
  external prompt as **"MAY run read-only commands to inspect surfaces; only do NOT mutate / edit /
  commit"**. A bare **"READ-ONLY: do not edit/write/commit"** reads as *do not run anything* → the
  external auditor refuses to READ the surfaces at all and returns no findings (real incident). The
  intent is a read-permitted, write-forbidden pass; say so explicitly.

#### STEP 2 addendum — include the consumer's DECLARED local themes (a `-C` consumer run)

When this runbook runs against a CONSUMER (`bin/yitc-v2 -C <path> …`), STEP 2 covers BOTH the kernel's
traveling T1–T9 themes AND the consumer's own project-local themes. This addendum adds **no new
mechanism** — the local themes are pure DECLARED config the consumer already carries; this is the
manual how-to for folding them into the same run. Per theme, by hand:

1. **Read the declared section** — open the consumer's `inspection:` section in its `yitc-ops.yaml` (the
   declare-or-waive carrier, shape governed by **SPEC-0093 rule 12**). A `waiver:` (no local themes) →
   run kernel T1–T9 only. A `themes:` list → each entry is `{ theme, probe: { view }, cadence }`.
2. **Run each theme's probe by hand** — execute its `view:` lens: `bin/yitc-v2 -C <path> graph query
   <view>`. (`view:` is the only probe kind in slice-1 — it reuses the existing `graph query` surface,
   no new runner.) Run it on the same DUAL-TRACK / blind-first discipline as the kernel themes above.
3. **Emit one `inspection_completed` per theme** — the SAME per-theme schema as the kernel themes
   (SPEC-0057 §6, theme-primary §3); a consumer cycle covering kernel + local themes leaves the SET of
   per-theme events, never one aggregate event. Same recording form, same flag:
   `bin/yitc-v2 -C <path> inspect record --theme <declared-slug> --tracks primary,external` — a
   local theme runs the same dual-track discipline (item 2), so its coverage is recorded the same way.

**Finding-sink routing — two sinks by KIND (rule home: SPEC-0057 §9 — read it there, not restated):**
a project-LOCAL-theme finding (the project's own domain health) routes to the CONSUMER's OWN journal +
triage; a methodology-ADHERENCE finding (the consumer's conformance to kernel methodology) routes to
the SHARED `cross` coordination log. Each sink has a CONCRETE observable carrier so a run's deliveries
are provable without interpreting prose:

- **local-theme finding → consumer journal** (project territory): captured as a
  `deviation_captured` event carrying `captured_via: inspection` + `inspection_theme: <local-theme>`
  in the consumer's OWN `events.jsonl` (the SPEC-0056 sink). **Observable carrier:** `bin/yitc-v2 -C
  <path> journal query --type deviation_captured` (the segment-aware reader — a raw grep of
  `<path>/events.jsonl` sees the live segment only, SPEC-0190 rule 4) filtered on
  `inspection_theme`, alongside the per-theme `inspection_completed` event the run emitted.
- **adherence finding → shared `cross` log:** filed with `bin/yitc-v2 cross request to:<kernel>` (the
  author verb — allocates the immutable id, emits `cross_requested`). **Observable carrier:**
  `bin/yitc-v2 cross outbox` (the author-side fold) / `bin/yitc-v2 cross inbox` on the kernel side —
  the filed item is the durable, queryable delivery.

**`-C` migration-complete blind-spot note (grounding: trend-finder B5, run_ref
migration-b5-baseline-2026-06-28).** On a `-C` consumer MIGRATION-complete (§B5) revizia the blind
external track has repeatedly caught residue the primary's own pass rationalized away — so the blind
track specifically probes: **per-land verify-status** (a backbone land with `consumer_verify: waiver`),
**waiver-vs-real-command coherence** (a `yitc-ops.yaml` waiver contradicting a present command), and
**deploy-still-on-v1** (the deploy path still sourcing the v1 framework). These are the roster lenses
T3/T6/T7 §B5-delta — pointer only, the lens bodies live there (P5 / SPEC-0005 rule 8).

### STEP 3 — DUAL-TRACK test triage of the resulting fresh window

Triage the fresh capture window the inspection just produced — **dual-track** (primary track +
external track), convergence-assessed, **no filing in this step**:

- `bin/yitc-v2 triage run` sweeps the un-routed `deviation_captured` captures **since the last
  `triage_run_completed` watermark** and prints the routes + the §5 checklist. Each capture routes to
  exactly ONE of the four routes: `event-only` · `linked` · `promote-to-fix-task` ·
  `promote-to-E-XXXX`. Authority: **SPEC-0056** (sink + four routes; established by §5) +
  **SPEC-0055** (`bin/yitc-v2 graph query SPEC-0055`).
- Run the routing assessment on **both tracks** and compare for convergence (the same dual-track
  discipline as step 2 — divergence is worked, not silently chosen; CHARTER §P7).
- **Convergence record = existing surfaces, no new store:** the routes + the watermark
  (`triage_run_completed`, emitted by `triage run --complete`) are the durable record of what was
  routed; the dual-track convergence comparison is written into the **run REPORT** (step 4), the same
  deliverable the 2026-06-07 run produced. There is no separate convergence store.

### STEP 4 — report convergence + INTO-WORK (filing gated on owner go)

Report: the convergence outcome (both inspection findings and the triage routing) + the proposed
**INTO-WORK** set — the convergent items that warrant becoming tasks/fixes. **File the convergent
into-work ONLY on an explicit owner go** — step 4 surfaces the recommendation; the owner decides what
enters the queue (CHARTER §When-to-ask-owner; lead with the recommended set + rationale, never a
menu).

### Emit discipline — one isolation rule for the whole run

This is a **long owner-invoked batch run** → it MUST emit ALL its journal events (captures,
`inspection_completed`, `triage_run_completed`, audit events) **from its own `work/<slug>` worktree**
and **fold them into `main` with ONE `land`** at the end — `main`'s `events.jsonl` stays clean across
the whole window. One isolation rule covers all three batch families (inspection, triage, ad-hoc
audit). The single from-anywhere ad-hoc `deviation_captured` reflex is the EXCLUDED case and stays
emittable from anywhere ( — preserved, not banned). Authority + the load-bearing invocation
form (`bin/yitc-v2 -C <wt> event …` — `REPO_ROOT` is binary-derived, so a bare `cd <wt> && bin/yitc-v2`
still writes to MAIN): **SPEC-0055 §Batch-run journal isolation** (`bin/yitc-v2 graph query SPEC-0055`)
/ ****.

### Execution shape — foreground default (procedural); background dispatch is ratified

- **DEFAULT (in force now): foreground tracks in the interactive session** — exactly as the
  2026-06-07 run was done (the session orchestrates the tracks live, one batch worktree, fold at land).
- **Background dispatch is RATIFIED, not trial-gated — the choice here is procedural, not a gate.**
  The orchestrate posture (an interactive controller selecting + dispatching independent background
  workers) is the Controller's **DEFAULT** posture per the **ratified CHARTER §6** ("Orchestrate
  posture — the bounded controller-selector"); the amendment landed via plan
  `orchestrate-posture-for-the-main-session-6-amendme` (`status: realized`, `closed_into: `).
  It stays **owner-invoked** — the owner starts the session and authorizes the batch (§6 named
  retirement (a)), journaled per `patterns/background-session-operation.md` §Guard-rails. So for
  THIS runbook, foreground is a **procedural preference** (the tracks are short, comparison is
  after-the-fact, and one batch worktree keeps the fold simple), NOT a governance precondition:
  running it via dispatched workers needs no trial to conclude, only the same owner go this runbook
  already requires.

## §Anti-pattern

- **Re-deriving the orchestration each run** from session memory instead of following this named
  order — the exact friction (2026-06-07) this runbook removes.
- **Duplicating any step's rule here.** This doc SEQUENCES; the rules home elsewhere (run-mode,
  SPEC-0056, SPEC-0055, SPEC-0052). A change to a step's rule is made in its home, not here
  (SPEC-0005 rule 8 one-home — a copy here would drift, P5).
- **Comparing tracks during the run** (anchoring) instead of after both finish; **a non-blind first
  external pass** (verify-first under-counts independence).
- **Auto-scheduling this run** (cron/hook) or **filing into-work without an explicit owner go** — both
  break the owner-invoked contract (CHARTER §6/§7).
- **Naming concrete tools in this body** (provider lock-in, CHARTER §P4b) — keep the body abstract;
  tool bindings live in the cited run-mode / OPERATING-PLAN provenance.
- **Emitting the batch's many events from `main`** (prolongs the dirty-window, feeds the E-0010
  land-abort family) instead of from the run worktree.

## §Cites

- `patterns/inspection-criteria-roster.md` (its part-2 `…-run-and-lenses.md`, SPEC-0120 split,
  its part-3 `…-themes-delivery-outcome-adoption.md`, SPEC-0120 split, and the navigation-map
  companion `…-navigation-map.md`)
  — the SINGLE living map across co-equal parts: the unified roster (every check
  → theme → cadence → how-to-run → rule-home) + the per-theme lens-checklists T1–T10 split across
  part-1 (T1 / T3 / T7 / T9 / T10) and part-3 (T2 / T4 / T5 / T6 / T8), and §Run-mode
  (SPEC-0057 §3 names it the living criteria home, §9 the cadence model; STEP 2 authority + the launch
  routing edge for the trigger phrase; retargeted here by from the realized roster plan).
- **SPEC-0093** rule 12 — the `inspection:` carrier section shape (the consumer's DECLARED local themes;
  STEP 2 addendum). **SPEC-0057 §9** — the finding-sink routing rule home (local→consumer journal,
  adherence→shared `cross`) the STEP 2 addendum points at (never restates — P5).
- **SPEC-0056** — nonconformity sink + the four triage routes (STEP 3 authority; established by §5).
- **SPEC-0055** — triage-run window + link rule (`triage run`) + §Batch-run journal isolation
  (STEP 3 + emit discipline).
- **SPEC-0052** / **** — displacement-retention sweep + fired-unacted-trigger view (STEP 1).
- **** — long-batch emit isolation (emit from the run worktree, fold once at land).
- `patterns/background-session-operation.md` — the controller's background-dispatch how-to (guard-rails + working order); the posture is ratified per CHARTER §6, owner-invoked, no longer trial-gated.
- **SPEC-0057** — the inspection construct normative home (read-only observation, not a gate; one sink;
  theme-primary; findings-not-color). Established by **** (provenance/history).
