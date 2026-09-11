---
name: design-tool-roundtrip
class: discipline
sourced_from: kupiclub the AI provider Design dogfood 2026-06-30 (cross X-0135 + task — 2 presentational deltas absorbed as ONE followup-batch hygiene task) + the design-from-outside intake deviations (kupiclub 2026-06-20 init-intake-design-not-only-scenarios, design-bundle-no-staging-home) + the DesignSync design-SYSTEM round-trip dogfood (cross X-0136 — kupiclub project c95f02ff) + the bc-community screen-canvas correction (cross X-0230 — owner-verified that the SCREEN.dc.html round-trip REQUIRES the declared claude_design MCP, not the built-in tool)
applies_to: any consumer app whose UI / screens are authored or edited in an EXTERNAL design tool (e.g. the AI provider Design) and then pulled back into the repo as an edit-set
---

# Design-tool roundtrip — absorbing a pulled design edit-set onto v2 carriers

> **Discipline pattern — strictly NON-NORMATIVE.** This is a reference procedure, not an
> enforced rule. The canonical handbook (CHARTER / AGENTS / LIFECYCLE / QUEUE / GRAPH) and the
> active specs OWN every normative rule. On any conflict — **canonical wins** (mirrors the
> authority boundary of `ui-enhancement.md` / `owner-list-intake-working-order.md`). It
> establishes no gate, no new mechanism, and no obligation; it tells you where the pieces of a
> pulled design edit-set land, and which carrier each delta rides.

## Problem

You design or edit a screen in an external design tool (a the AI provider Design canvas, a design file),
then pull the edit-set back into the repo — typically as a diff (`get_file` and friends). That
pull arrives as a **mixed bundle**: a few spacing/label nudges, maybe a behavior change, perhaps a
genuine new rule or a whole new screen, all at once. Two failure modes recur:

- **Over-coarse** — file the whole bundle as one task. It mixes claims AND classes (a presentational
  trim and an audited behavior change cannot honestly be one task — different claims, different
  classes), so the carrier is wrong from the start.
- **Over-fine** — mint a task per tiny nudge. Ten cosmetic tweaks become ten tasks, ten lifecycles,
  ten closures. That is the cost the owner flagged: *"when absorbing design work, it somehow needs to be
  measured, to save working time"* — a pack of small design tweaks should cost **one batch,
  not N tasks**.

And a third drift: **where does the design source itself live in the model?** It is tempting to make
the design tool / design project a graph node. It is not one — the repo's specs and scenarios are
*derived from* the design (a rules←code inversion, see `sourced_from`), but the design surface stays
outside the graph.

## Solution — the roundtrip absorption model

A pulled design edit-set is **not a new kind of work** — it is an existing intake seen from a new
input. Three rules place every piece; none of them is a new mechanism.

### 1 — The design source is INPUT / PROVENANCE, never a graph node

The design tool and the design project (the the AI provider Design canvas, the design file, the pulled diff's
origin) are the **origin** of the change. Record them as provenance — a commit `from:`, a task /
pattern `sourced_from:`, or a `cites` to the design artifact's locator — **never** as a `spec` /
`scenario` / `pattern` node. The repo's scenarios + specs are authored/updated *from* the design, but
the design surface itself is read-only provenance (the same boundary `patterns/*` `sourced_from:`
provenance already follows — AGENTS §Scope-boundary → Legitimate cross-territory references).

### 2 — The pulled diff is a LIST-INTAKE — hand it to the owner-list working-order

A roundtrip pull is exactly «the owner states a LIST of changes to process in one go». So it routes
straight into **`patterns/owner-list-intake-working-order.md`** — verify each delta by fact →
classify → decompose + batch + order → one owner checkpoint → execute → verify-on-land. This pattern
does **not** restate that order (P5 single-home); it only names the design pull as one of its inputs
and adds the design-specific KIND table below as the classify-step's specialization.

> **Verify-by-fact matters doubly here (owner-list step 1).** A design canvas can be *ahead of* or
> *behind* the live code. Re-read the current code per delta before acting — never absorb a design
> diff against a stale mental model of the screen.

### 3 — Triage each delta by KIND, not by count (the economy lever)

The classify step (owner-list step 2), specialized for design deltas. **The KIND decides the carrier;
the count never does** — ten presentational nudges are still one batch, one genuine rule is still a
spec.

| Delta KIND | Carrier | Why |
|---|---|---|
| a new / changed **enforced RULE** (a checkable «must/always/never») | a **`spec`** (SPEC-0005 admission) | only a rule that could be checked earns a spec |
| a **behavior** change (user-path logic, a new/changed affordance) | a **`task`** (a scenario step) | a work unit through the 9 stages — where its deltas live = `ui-enhancement.md` |
| a **presentational** nudge (spacing, position, label copy, color/token) | a **`followup`** (SPEC-0095), drained as **ONE batch** | many small same-class nudges = one followup-batch hygiene task, **not N tasks** — the economy lever |
| a whole **new screen / flow** | a **`scenario`** (a `plan` if it needs a new spec corpus) | a user-path is a scenario (SPEC-0076); a multi-spec feature escalates to a plan (LIFECYCLE §Routing) |

The presentational lane is the one that saves the owner's time: stage each cosmetic delta with
`bin/yitc-v2 followup add` (a journaled, no-worktree one-liner — SPEC-0095), then drain the
homogeneous batch through ONE hygiene task (one lifecycle, one close) per `owner-list` step 3's
claim-shape rule (same-claim / homogeneous → one task).

### CAVEAT — repos that PIN the canon to the code (rendered / conformance tests)

**The condition.** Some repos pin the design canon (the checked-in canonical HTML) to the rendered
components with **pixel-perfect and/or source-conformance tests**. In such a repo the canon is not a
free-standing artifact: it is one half of an asserted equality, and the tests exist precisely to
report when the two halves diverge.

**What follows.** Under that pin, **a canon overwrite ALONE cannot land.** Refreshing the canon
without the synchronous code change makes candidate-verify **genuinely fail** — the code still
renders the old screen, so the pinned tests are reporting a real divergence.

**That RED is a TRUE failure, NOT a re-baseline candidate, and it must NOT be forced.** This is the
part worth stating out loud, because the shape is deceptive: a large canon-only diff going RED looks
from the outside exactly like a stale-pinned-canon re-baseline case, and a re-baseline route does
exist. It does not apply here. Re-baselining would overwrite a correct assertion with a canon the
code does not produce, converting a working guard into a silent one. The failing tests are right.

**The route.** In a pinned-canon repo, a redesign of an **ALREADY-IMPLEMENTED** screen is routed as a
**`task`** — one that carries **canon + code + tests together**, so the pinned equality holds at every
landed commit. **Never** as a bulk canon batch. This is the KIND table above applied, not an exception
to it: a redesign of an implemented screen is a *behavior* change (its row already says `task`); the
caveat only makes explicit WHY the bulk-canon shortcut is unavailable, which is invisible at the
moment it matters — when you are holding a 26-screen pull and reaching for one batch.

**The discriminator is implementation status, not screen count.** Unimplemented and brand-new screens
are not pinned to anything yet, so they still batch normally.

> **Incident (bc-community, 2026-08-12 — cross X-0836).** A bulk 26-screen redesign pull went RED at
> land on exactly this. Resolution: the **15** unimplemented / new screens landed as the batch; the
> **11** implemented screens were split out into per-screen tasks carrying canon + code + tests
> together. That split is the rule in action.

## The DesignSync surface — capability matrix + project-type axis

The «pull the edit-set (`get_file`/equivalent)» step above is concrete, and **WHICH surface serves it
depends on the project type** (the axis below). Two surfaces exist — a **built-in / harness-native
design-sync tool** and a **declared design MCP capability** (an explicitly connected design-backend
MCP server) — and they do **NOT** cover the same project types. This section documents them at
**roundtrip altitude only** (what reads a screen out, what writes a correction back, on which project
shapes) — it is NOT an API reference and invents no internals.

> **Current implementation facts (non-normative).** The built-in tool is **DesignSync**; the declared
> design MCP is **`claude_design`** (`api.the provider.com/v1/design/mcp`); both auth via **`/design-login`**.
> These are the *current* concrete bindings, named here as facts — the RULE below is stated
> **provider-neutrally** (CHARTER §Principle 4b).

### Capability matrix — which surface round-trips which project type

> **Scope of this matrix.** It answers **which surface round-trips which project type** — i.e. whether
> you can read a screen out and write a correction back at all. It does **NOT** answer whether the
> write you push back can **LAND**. In a repo that pins the canon to the code by rendered /
> conformance tests, a canon-only write round-trips fine and still cannot land: see
> **§3 → CAVEAT — repos that PIN the canon to the code** for the condition and the task route.

The design backend has two project types (design-SYSTEM vs design-PROJECT, defined below). The read +
write round-trip is served by a **DIFFERENT surface for each — they are NOT interchangeable**:

| Project type | Built-in design-sync tool (DesignSync) | Declared design MCP (claude_design) |
|---|---|---|
| **design-SYSTEM** (component / token catalog) | **yes** — full read + write round-trip | yes |
| **design-PROJECT** (SCREEN `.dc.html` canvas) | **NO** — does NOT round-trip the screen canvas | **yes — REQUIRED** (`/design-login` + `claude_design`) |

**RULE (provider-neutral).** The **design-system catalog** round-trips through the **built-in /
harness-native design-sync tool**. The **screen design-project canvas** does **NOT** round-trip
through the built-in tool — its round-trip **REQUIRES the declared design MCP capability** (an
explicitly connected design-backend MCP server, reached via the design-login auth). The built-in tool
covers the **design-system side ONLY**.

Within whichever surface serves the type, the read/write methods are the same shape (`list_projects` ·
`get_project` · `list_files` · `get_file` to read; `finalize_plan` → `write_files` / `delete_files`
to write) and the **ordering is `read → finalize_plan → write`** — read the current surface first
(`get_file`), then `finalize_plan` to stage the intended edit, then `write_files` (or `delete_files`)
to apply it. This is the same verify-by-fact discipline §2 already demands: never write back against a
stale read.

**Verified provenance:** the screen (`.dc.html`) round-trip via the declared design MCP is
**owner-verified on bc-community** (plan `correct-verify-the-full-project-user-collaboration` W8,
cross **X-0230**). This **CORRECTS** the earlier claim (cross **X-0136**, kupiclub `c95f02ff`) that one
built-in DesignSync tool round-tripped BOTH project types — that dogfood evidently exercised the
design-SYSTEM side; the screen canvas needs the declared MCP (CHARTER §Principle 7 dissonance — the
owner-verified fact wins; the X-0136 provenance is kept, its screen-round-trip conclusion is retired).

### The project-type axis — design-SYSTEM vs design-PROJECT

A design project is **one of two types, fixed at creation (immutable)** — the type decides what its
files MEAN **and which surface round-trips it** (per the matrix above: built-in tool for the
design-system catalog; the declared design MCP for the screen canvas):

- **design-SYSTEM** (`PROJECT_TYPE_DESIGN_SYSTEM`) — a reusable **component / token CATALOG**. Its
  reusable pieces are **cards** authored with the `@dsCard` marker and indexed into a
  `_ds_manifest.json`. This is the «shared vocabulary» surface (the tokens/components other screens
  draw from).
- **design-PROJECT** (`PROJECT_TYPE_PROJECT`) — a concrete-**screen** canvas. The hands-on surface a
  real screen is pulled from is a **`.dc.html`** file (see the format note below).

### The built-in tool covers the design-SYSTEM side only — the screen canvas REQUIRES the declared MCP

**The built-in design-sync tool does NOT cover the whole round-trip.** It round-trips the
**design-SYSTEM catalog** — for that side, when you hold the built-in tool there is NO need to also
connect a separate `claude_design` MCP (redundant on that side — same backend, same projects). But the
**SCREEN design-PROJECT (`.dc.html` canvas) round-trip is NOT served by the built-in tool** — it
**REQUIRES the declared design MCP capability** (`/design-login` + `claude_design`). So a session that
needs to pull/write a *screen* MUST connect the declared design MCP; the built-in tool alone is not
sufficient. This is owner-verified on bc-community (cross **X-0230**) and **corrects** the retired
X-0136 claim that one built-in tool round-tripped both types.

**So the split is by PROJECT TYPE, not just by client binding** — the delivery-axis note below covers
the design-system side, where built-in-vs-MCP is a binding choice; for the screen canvas the declared
MCP is not a *choice* but a *requirement*.

### Delivery axis — built-in DesignSync vs standalone `claude_design` MCP

> **This is the DESIGN-SPECIFIC INSTANCE of a general rule.** The general «a built-in
> harness-native tool vs an external MCP server reach the same backend; with the binding the built-in
> wins, without it connect the MCP» rule now lives in **`patterns/working-with-mcp-in-v2.md §Delivery
> axis`** (delivered via SPEC-0118). This section is its design-backend instance — kept here for the
> concrete DesignSync/`claude_design` specifics; the general rule is NOT restated there-and-here (P5).

**This delivery-axis choice applies to the design-SYSTEM side ONLY** — where both surfaces round-trip
the catalog, so which one you use is a binding choice. **For the screen design-PROJECT canvas there is
NO choice:** the built-in tool does not round-trip it, so the declared MCP is REQUIRED (§capability
matrix above). With that scope fixed, the design-system backend is reachable **TWO ways for the SAME
capability** — the choice is a *delivery axis*, not two different backends:

| Path | What it is | Endpoint / wiring | Auth | When to use |
|---|---|---|---|---|
| **(1) built-in DesignSync** | a **harness-native tool** wired directly into the AI provider Code — **NOT** an MCP server | in-harness (no server URL) | `/design-login` (token handled inside DesignSync) | the design-SYSTEM side, binding case — you are in the AI provider Code with DesignSync present |
| **(2) standalone `claude_design` MCP** | an external **MCP server** exposing equivalent read/write verbs | `api.the provider.com/v1/design/mcp` | same `/design-login` | the no-binding case (any client WITHOUT the built-in tool) **AND** every SCREEN (design-PROJECT) round-trip regardless of binding |

**RULE (binding-conditional — design-SYSTEM side):**

- **WITH the the AI provider-Code + Design binding** → for the **design-system catalog** the `claude_design`
  MCP is **REDUNDANT** — use the built-in **DesignSync** (this reconciles the §above line: no MCP
  needed *on that side* because you already hold the built-in tool).
- **WITHOUT the binding** (another client / bare agent / raw API) → **connect the `claude_design`
  MCP** — it IS the path to the same backend and the same projects.
- **SCREEN (design-PROJECT `.dc.html`) round-trip — REQUIRED regardless of binding** → **connect the
  `claude_design` MCP**; the built-in tool does not serve it, so the «no MCP needed» conclusion does
  **not** apply to screens even under the binding.

Same backend, same `/design-login` auth, same projects — only the transport differs (and, for the
screen canvas, only the declared MCP transport reaches it at all).

> **Provenance (honesty marker).** The screen (`.dc.html`) round-trip via the declared `claude_design`
> MCP is now **owner-verified on bc-community** (cross **X-0230**) — this is what established that the
> built-in tool does NOT round-trip the screen canvas. Earlier (cross X-0136) this pattern INFERRED the
> two paths equivalent across both types and treated one built-in tool as sufficient end-to-end; the
> bc-community verification **corrects** that for the screen case (CHARTER §Principle 7 — owner-verified
> fact wins). The design-SYSTEM equivalence (path 1 ⇄ path 2) remains as documented.

### `.dc.html` (`x-dc` / DCLogic) — a roundtrip-altitude note

A design-PROJECT screen lives in a **`.dc.html`** file (an `x-dc` / DCLogic document). At this
pattern's altitude that is all you need: a `.dc.html` is **read via `get_file` and written via
`write_files` like any other project file** — the round-trip treats it as an opaque edit-set carrier.
**Do NOT over-specify DCLogic internals here** — there is no verified format spec for them, and this
pattern is about *absorbing* a pulled edit-set, not about the file format. If a DCLogic-internals
reference is ever needed, it is a separate artifact, sourced from a verified format spec, not invented
in this discipline note.

## Procedure

1. **Record provenance.** Note the design source (tool + canvas/file locator) as the change's origin
   — `from:` / `sourced_from:` / `cites`. Do not create a node for it.
2. **Pull the edit-set** (`get_file`/equivalent) into a staging surface; treat the diff as the list.
3. **Hand to `owner-list-intake-working-order`:** verify each delta by fact against current code,
   then classify each by KIND (the table above), decompose + batch + order. **If the repo PINS the
   canon to the code** (rendered / conformance tests), apply **§3 → CAVEAT** at this step: split the
   already-implemented screens out of any bulk canon batch and route each as its own task carrying
   canon + code + tests together — a canon-only batch over them cannot land, and that RED is a true
   failure, not a re-baseline.
4. **Drain by lane:** presentational → `followup add` ×N → one hygiene task; behavior → task (scenario step + `covers`, per `ui-enhancement.md`); rule → `spec`; new screen → scenario (plan).
5. **Each write rides its own worktree + lifecycle** (AGENTS §Writes happen in a worktree); the
   design source stays read-only provenance throughout.

## Worked example — the kupiclub dogfood (2026-06-30)

The owner edited the kupiclub design system in the AI provider Design, then pulled two deltas on the
article-create screen: (1) reposition the metadata fieldset legend; (2) drop the redundant
«(optional)» suffix from the 10 metadata field labels. **Both presentational** → the
presentational lane → absorbed as **ONE** hygiene task (`kupiclub `), not two. The design
canvas was recorded as provenance, never a node. This walk is the pattern's adoption evidence
(CHARTER §Principle 3 — done = adopted): the presentational route ran end-to-end on real deltas.

## What this pattern is NOT

- **NOT** a gate, verb, or new mechanism — it adds no stage, no parser, no node. The design tool does
  not become a graph node, and «design roundtrip» is not a new lifecycle.
- **NOT** a replacement for `owner-list-intake-working-order` — it **routes into** it (the pull is one
  of its inputs).
- **NOT** a replacement for `ui-enhancement.md` — it **reuses** that where-does-a-UI-delta-live model
  for the behavior/affordance lane.

## Anti-complexity check (CHARTER §Principle 1, four filters — written down)

1. **Existing analog?** Yes — `owner-list-intake-working-order` (the LIST order) + `ui-enhancement`
   (where a UI delta lives) + `followup`/SPEC-0095 (the small-follow-up batch). REUSED and composed,
   not duplicated.
2. **New entity or new view?** A **view** — it composes existing carriers. No new node, edge, verb,
   format, or gate.
3. **What gets removed?** The per-project re-litigation of «how do I absorb a design pull», and the
   two named drifts (N-tasks-per-nudge; design-tool-as-a-graph-node).
4. **Real incident / prior-art?** The kupiclub the AI provider Design dogfood 2026-06-30 (cross X-0135,
   task) + the 2026-06-20 design-from-outside intake deviations + the DesignSync
   round-trip on kupiclub project `c95f02ff` (cross X-0136 — the design-SYSTEM round-trip) + the
   bc-community screen-canvas correction (cross X-0230 — owner-verified that the screen round-trip
   REQUIRES the declared design MCP, not the built-in tool). So the §surface note documents reality,
   invents nothing.

## Why it travels

This is general YITC methodology — any consumer that authors/edits UI in an external design tool and
pulls it back faces the same absorption question; it carries no project specifics (SPEC-0090 §2
boundary: needed for the kernel's own work across projects → `patterns/`, not a per-repo `lessons/`
note). Project-local craft about one codebase's design pipeline (which files a pull touches, that
project's token set) stays in that repo's `lessons/`.

## See also

- `patterns/owner-list-intake-working-order.md` — the LIST intake working-order this routes into.
- `patterns/working-with-mcp-in-v2.md` — the GENERAL MCP discipline; §Delivery axis here is its design-specific instance.
- `patterns/ui-enhancement.md` — where a UI delta (affordance / template / label) lives in the model.
- `patterns/ux-general-principles.md` — universal screen-craft rulebook (design the delta against it).
- **SPEC-0095** — the `followup` capture mechanism (`bin/yitc-v2 graph query SPEC-0095`).
- **SPEC-0076** — the scenario node + `covers` edge (`bin/yitc-v2 graph query SPEC-0076`).
- **cross X-0136** — the DesignSync **design-SYSTEM** round-trip (kupiclub project `c95f02ff`): the
  provenance behind the §surface project-type axis + `.dc.html` note (its «both types» conclusion is
  retired — see X-0230).
- **cross X-0137** — the delivery-axis intake (built-in DesignSync vs standalone `claude_design` MCP):
  the provenance behind the §Delivery axis note (design-SYSTEM binding choice).
- **cross X-0230** — the bc-community owner-verified correction: the SCREEN (design-PROJECT `.dc.html`)
  round-trip REQUIRES the declared design MCP (`/design-login` + `claude_design`); the built-in tool
  round-trips the design-SYSTEM side ONLY. Provenance behind the §capability matrix correction.
