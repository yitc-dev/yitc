---
name: cli-line-directive-vs-reference
class: discipline
sourced_from: plan lifecycle-path-and-verb-sequencing-coherence-who-a §First-named task (owner directive 2026-06-07/08);
applies_to: authoring or editing ANY AI-facing string the `bin/yitc-v2` CLI prints — verb output, stage/seed deliveries, "read X" pointers, "next:" hints, refusal messages, advisories
binding: []
---

# CLI line — DIRECTIVE or REFERENCE (every AI-facing line, unambiguously one)

> The human-readable twin of the `_require_reads` read-gate (SPEC-0050): the gate makes a required
> read **enforced**; this convention makes it **legible**. Together they close "pointer ≠
> consumption" from both sides — legible intent + enforced read.

## Problem

An AI-facing CLI line can carry an **obligation** (do this, or something breaks) or be **information**
(here is context, act only if relevant). When the words don't say which, the AI guesses — and the
cheap guess is "it's just a pointer." Load-bearing reads then get skipped **silently**.

Real incident (the root this convention closes): `plan file` printed `read before acting: SPEC-0034`.
The wording read like a **reference**, but it was an **action** — the author never fetched SPEC-0034,
and the `postcheck-to-realized` plan went on to re-design a procedure SPEC-0034 had already. A
pointer that is really an action MUST announce itself as one.

## Solution

Every AI-facing CLI line is **exactly one** of two classes, distinguished **by its words** — no line
may sit silently between them.

### DIRECTIVE (ACTION) — "read & act"
The AI MUST perform it; not-doing-it is a defect. Three required parts:

  **imperative verb** + **WHAT** (the specific object) + **CONSEQUENCE** (what fails / is gated / is
  invisible if skipped).

Template:
```
ACTION — <imperative> <WHAT> (yitc-v2 graph query <SPEC>); <verb> refuses / <bad outcome> without it.
```
The **CONSEQUENCE is the teeth.** A bare `read X` with no stated consequence is the exact ambiguous
shape that caused the incident — it is NOT a complete DIRECTIVE.

### REFERENCE (informational note) — "available, optional"
Information only; no action required. Two required parts:

  **what is available** + an **explicit "nothing is gated on it."**

Template:
```
REFERENCE — <X> available for context; reading optional, nothing is gated on it.
```
Stating "nothing gated" is what stops the AI from treating optional context as a hidden obligation
(the inverse failure).

### Rules
1. **No line silently ambiguous.** A line that *looks* informational but is actually required is a
   DIRECTIVE — reword it with the imperative and the consequence.
2. **A DIRECTIVE always names its consequence.** "read X" alone is incomplete.
3. **A REFERENCE always says "nothing gated."** Otherwise it reads as a hidden obligation.
4. **DEFAULT = clarify by WORDS (reuse existing phrasing).** Do **NOT** introduce an `[ACTION]`/`[REF]`
   marker or prefix syntax. A token syntax is a *mechanism* — it must pass the anti-complexity 4
   filters AND earn owner approval FIRST (CHARTER §When-NOT-to-add). Phrasing clarity is the cheap
   default; a marker is the expensive one that must justify itself.
5. **Where an action is also enforced by a verb gate** (the SPEC-0050 read-gate), the **refusal text
   IS the DIRECTIVE line** — it already names exactly what to fetch and that the verb refused. The
   gate and this convention reinforce each other; the refusal is the model DIRECTIVE.

## Example

The classification audit of the **fixed roster** of AI-facing surfaces (2026-06-08). One row
per emitted line. Verdict = **clear** (words already match its class) / **clarify** (right class,
wording incomplete — fix shown). NEW surfaces found later are separate follow-up units, not this audit.

### Surface 1 — `bin/yitc-v2 --help` + `task` / `audit` / `graph --help`
Every emitted line of every `--help` output is **REFERENCE** — argparse help is an availability
listing; nothing is gated on reading it, and no line carries an imperative-with-consequence. Enumerated
per emitted line (the verdict is uniform, but the roster is covered line-by-line, not collapsed):

| emitted line | class | verdict |
|---|---|---|
| `usage: yitc-v2 …` (each sub-help `usage:` line) | REFERENCE | clear |
| the `positional arguments:` / `options:` section headers | REFERENCE | clear |
| top-level subcommand rows — one per line: `event`, `task`, `stage`, `audit`, `triage`, `graph`, `error`, `journal`, `session`, `plan`, `decision`, `land`, `worktree`, `work`, `dispatch`, `spec` (each `<verb> <description>`) | REFERENCE | clear (each describes an available verb) |
| `task --help` rows — one per line: `file`, `close`, `pick`, `execute`, `test`, `plan`, `commit`, `list`, `update`, `pause`, `resume` | REFERENCE | clear |
| `audit --help` rows — one per line: `pre`, `post`, `adhoc`, `consult`, `run` | REFERENCE | clear |
| `graph --help` rows — one per line: `build`, `conformance`, `query` | REFERENCE | clear |
| option rows: `-h, --help`, `-C/--directory`, and every per-verb flag row (e.g. `--full`, `--owner-reset`, `--evidence`, `--finalize`) | REFERENCE | clear (a flag description; gates nothing on being read) |

> Note: a `--help` *description* may NARRATE a directive that lives elsewhere (e.g. `pick` is
> "read-only", `commit` "callable ×N") — but the help LINE itself is reference; the obligation is
> carried by the verb's own runtime output / refusal, classified in Surfaces 3–6.

### Surface 2 — `session start` echoes
| line | class | verdict / fix |
|---|---|---|
| `session_started emitted: type=build project=…` | REFERENCE | clear (status confirmation) |
| `read-order (topological — CHARTER first…): CHARTER.md → AGENTS.md → …` | DIRECTIVE | **clarify** — a bare arrow-list; add imperative + consequence: "ACTION — read these in order before acting; this is the mandatory session seed (you operate without the rules otherwise)." |
| `rescan CLI surface: bin/yitc-v2 --help` | DIRECTIVE | clarify — has the imperative; add the consequence ("…or you miss verbs shipped since last session — the adoption gap") |
| `also auto-read project buffer: MEMORY.md (non-authoritative…)` | DIRECTIVE | clarify — "auto-read" is the imperative; name the consequence (you miss bounded temporary instructions). The "non-authoritative" qualifier is good practice — it tells you the line's weight |
| `always-loaded seed also: graph/floor-trigger-map.md (… read before authoring/editing a spec)` | DIRECTIVE (conditional) | clear-ish — names WHAT + the conditional WHEN ("before … a spec") |
| `lifecycle-scoped content is delivered at STAGE-ENTRY : run \`yitc-v2 stage <NAME> --task T-XXXX\` …; re-run after /compact` | DIRECTIVE | clear — imperative "run" + WHAT + WHEN |
| `stage-agnostic general-verb seed (…): SPEC-0051 — <title> — fetch via \`graph query <SPEC>\`` | REFERENCE | **clarify** — an on-demand navigational pointer, but "fetch via" reads action-y; say "fetch when its surface is in scope; nothing is gated on it" |
| `build: RESUME in-progress T-XXXX — <title>` + `(read-only report — the verb did NOT resume/mutate; continue the task yourself)` | REFERENCE | clear — the parenthetical disambiguates the action-sounding "RESUME"; this IS the convention working |

### Surface 3 — stage-entry outputs (`yitc-v2 stage <NAME>`)
| line | class | verdict / fix |
|---|---|---|
| `<tid> -> stage=<name> (current_stage recorded)` | REFERENCE | clear (status confirmation) |
| `read before acting (fetch via \`yitc-v2 graph query <SPEC>\`): <SPEC…>` | DIRECTIVE | **clarify — the incident line.** Add the consequence: "ACTION — fetch & read <SPEC> before this stage's work-verb; for a gated stage the work-verb refuses without a recorded read (SPEC-0050); otherwise you act without the governing doctrine." |
| `no spec bound to stage-entry:<name> (… work-verb only).` | REFERENCE | clear (informational) |
| `consult pattern(s) for this stage (read \`patterns/<name>.md\`…): <name>` | REFERENCE | clarify — pattern reads are not gated; say "consult for guidance; nothing is gated on it" (today "consult" reads as a soft directive without a consequence) |
| `work-verb(s) for this stage: <verb>` | REFERENCE | clear (names the stage's verb inventory; the line itself gates nothing) |

### Surface 4 — refusal messages (the SPEC-0050 read-gate, `_require_reads`)
| line | class | verdict |
|---|---|---|
| `<verb>: required governing contract(s) not fetched this session — refusing.` + `Fetch each missing contract (one command per doc):` + `bin/yitc-v2 graph query <SPEC>` + `the gate checks delivery (fetch), not comprehension` + `After reading, verify your prepared <action>… re-invoke` | DIRECTIVE | **clear — the model DIRECTIVE.** imperative ("Fetch each") + WHAT (each missing doc, one command each) + CONSEQUENCE (the verb refused, exit nonzero) |
| fail-closed no-anchor: `<verb>: no session_started anchor … — refusing (fail-closed).` + `bin/yitc-v2 session start --type build` | DIRECTIVE | clear — imperative + WHAT + consequence (refused) |

### Surface 5 — `worktree new` advisories
| line | class | verdict / fix |
|---|---|---|
| `worktree new: branch task/T-XXXX at <path>`; `claimed T-XXXX -> in-progress \| stage=Analysis` | REFERENCE | clear (status) |
| `cites (read for context): <SPEC…>` | REFERENCE | clear — "read for context" is the explicit REFERENCE signal |
| `⚠ read-gate: FIRST, before any stage read or gated verb …, run: bin/yitc-v2 session start --type build` + `… \`graph query <SPEC>\` reads done BEFORE it are NOT credited.` | DIRECTIVE | **clear — model line.** imperative ("FIRST … run") + WHAT + CONSEQUENCE ("reads done BEFORE it are NOT credited") |
| `→ Stage-1 (Analysis) procedure … — work these IN ORDER before any edit:` (numbered list) | DIRECTIVE | clarify — "work these IN ORDER before any edit" is the imperative+when; add the consequence (you skip the Principle-1 prior-art filters) |
| `→ Analysis stage-entry delivers: <SPEC…> (\`graph query <SPEC>\`)` | DIRECTIVE | clarify — same class as the stage-entry "read before acting" line; name the consequence |
| `cd <worktree-path>` | DIRECTIVE | clear (a bare imperative command — unambiguous; you must enter the worktree) |
| `next: edit per plan, then … → \`land\`` | REFERENCE | clear — a "next:" roadmap; advisory sequencing, nothing gated on the line itself |

### Surface 6 — `land` output (in-scope as an "advisory" per the roster)
`land`'s `cd <main>` cue is an **advisory** and its `LAND:` token a **status line** — both fall under
the roster's named "advisories" category (task scope bullet 1), so they are in-scope, not drift.

| line | class | verdict |
|---|---|---|
| `cd <main-checkout>` cue after a successful land | DIRECTIVE | clear (imperative; consequence: the removed-cwd `getcwd` error if skipped) |
| `LAND: OK <sha>` / `LAND: ABORT <reason>` terminal token | REFERENCE | clear (a machine-readable status report). NB: for a *backgrounded / tool* caller it is additionally a **parse-contract** — that programmatic obligation lives in AGENTS §Writes-happen-in-a-worktree, not in the line itself |

### Summary of the audit
- **DIRECTIVE, clear (model lines to imitate):** the read-gate refusals (Surface 4) and the
  `worktree new` `⚠ read-gate` advisory (Surface 5) — each carries imperative + WHAT + CONSEQUENCE.
- **DIRECTIVE, clarify:** the stage-entry `read before acting: <SPEC>` line (Surface 3 — the incident
  shape), the `session start` `read-order` / `rescan` / `MEMORY.md` echoes (Surface 2), and the
  `worktree new` Stage-1-procedure / `Analysis stage-entry delivers` lines (Surface 5). All are the
  right CLASS already; they need the CONSEQUENCE made explicit.
- **REFERENCE, clarify:** the `stage-agnostic general-verb seed` line (Surface 2) and the `consult
  pattern(s)` line (Surface 3) — add "nothing is gated on it."
- **REFERENCE, clear:** `--help`, status confirmations, `cites (read for context)`, the read-only
  resume report, `next:` roadmaps, the `LAND:` token.
- **Already DONE on the piloted gates:** `task commit` / `task close` retired their pointer-only "read
  before acting" advisory (SPEC-0050) — delivery rides "refusal + ready `graph query` command", the
  DIRECTIVE shape realized. The remaining `clarify` items are the NON-piloted verb surface; this
  convention is the GUIDANCE that informs how those user-facing strings (and the plan's R5/R6/R7
  writer tasks) are worded — it is NOT itself an enforced gate.

## Anti-pattern

- `read before acting: SPEC-0034` — a bare pointer with no consequence. Reads as REFERENCE, is an
  ACTION. **The incident.** Fix: state the consequence (the verb refuses / you act on stale doctrine).
- `consult X for the details` with no statement of whether anything is gated — the reader cannot tell
  if skipping it is a defect.
- Inventing an `[ACTION]`/`[REF]` prefix to "solve" ambiguity without first passing the anti-complexity
  filters — that is adding a mechanism where clarified words suffice (CHARTER §Principle 1 / §When-NOT-to-add).

## Cites

- SPEC-0050 — the `_require_reads` read-gate (the enforced twin; its refusal is the model DIRECTIVE)
- SPEC-0059 — universal stage contract (entry DELIVERS doctrine; this convention makes that delivery legible)
- plan `lifecycle-path-and-verb-sequencing-coherence-who-a` §First-named task / §Wording convention
- CHARTER §Principle 1 (anti-complexity) / §When-NOT-to-add (no marker mechanism by default)
- (this audit)
