---
name: working-with-mcp-in-v2
class: discipline
applies_to: every YITC session (kernel or consumer) that connects or uses an external tool-provider (an MCP server) — the provider-NEUTRAL governance for connecting, keeping the connected set clean, and capturing external writes
---

# Working with MCP in v2 — the provider-neutral discipline

> **Provider-NEUTRAL by construction (CHARTER §Principle 4b).** This pattern carries ONLY
> provider-neutral governance, in abstractions — «the project's committed MCP config», «the session's
> MCP-list command», «disable an unused server». It names NO provider brand and NO concrete command.
> The concrete commands for a specific client live in a SEPARATE per-client `class: adapter` runbook
> (provider-named; it links back UP to this pattern — the neutral home does not privilege one client by
> hardcoding its path). That runbook is non-normative and is NOT a governance source. On any conflict
> the canonical handbook + active specs WIN (P7).
>
> **Delivered (SPEC-0118).** This discipline is surfaced at the two moments it is needed — the
> session-start reconcile rides the always-loaded `binding:[seed]` seed; the connect/use guidance rides
> the `before-mcp-use` floor trigger (`graph/floor-trigger-map.md`). SPEC-0118 is the delivery contract;
> THIS pattern is the single home for the prose (SoT — the spec does not restate it, P5).

## Problem

A session needs an external tool-provider — an MCP server — to do its work: a design backend, a chat
service, a third-party API surface. Three questions recur and v2 had no documented stance (cross
X-0138): **(1) connect** — where does MCP config live, and when does a server launch? **(2) hygiene** —
how do you avoid an ever-growing pile of half-forgotten one-off servers? **(3) govern** — when an MCP
tool changes the outside world, what must the session record? Without a stance, each project re-derives
the answers, and an MCP-mediated external write slips by uncaptured (the kupiclub DesignSync incident,
2026-06-30 — a real external write that left no journal line).

## Solution — the two-shelf model

Sort every MCP server a session uses onto one of two shelves. The shelf decides where its config lives
and how long it stays; it never changes the capture rule (§Capture).

### Shelf 1 — standing MCP (project-explicit)

The servers a project **always** needs are **declared in its committed, project-scope MCP config** —
the config carrier that travels with the repo. That committed config IS the source of truth for «what
this project connects». Keep the set INTENTIONAL, not cluttered: a project-local human-readable note
(the project's `lessons/` craft note) may NAME the standing servers and WHY, but that note is a
pointer, never a second source of truth (P5 — the committed config is the SoT). A teammate who clones
the repo inherits exactly the declared set.

### Shelf 2 — one-off MCP

A server added **ad-hoc for a single need** — session or local scope, **NOT committed**. It is
legitimate (you don't commit a server you needed for one investigation), but it carries one risk:
**forgetting to drop it**, so it lingers across sessions as connected-but-unaccounted clutter. The
reconcile below is the safety net for exactly that.

### The session-start reconcile (the «don't-forget-to-disable» safety net)

A **BEHAVIORAL discipline, NOT a new hook or gate** (CHARTER §When-NOT-to-add-a-mechanism — the harness
does not auto-disable anything). At **session start**, as one of the session's other start-of-session
reads:

1. **List** the currently connected MCP servers (the session's MCP-list surface).
2. **Compare** against the declared standing set (the committed config + any explicit always-on).
3. **Disable / remove** any extra one-off that is no longer needed.

This rides the always-loaded session-start seed (SPEC-0118 `binding:[seed]`), so it is surfaced every
session start and re-surfaced after `/compact`. It is a reconcile you RUN, not a guard that fires.

## Capture — a substantive MCP write incurs the external_action floor

A **substantive external WRITE performed through an MCP tool — on EITHER shelf — is governed by the
SPEC-0116 `external_action` capture floor**: it MUST emit one `external_action` journal event
(`channel` / `target` / `action` / `from`) at the time of the action, exactly as a write through any
other channel would. The shelf classification (standing vs one-off) does **not** change this. **READS
and trivial/no-effect calls are excluded** — the SPEC-0116 bright line. This pattern POINTS at
SPEC-0116; it does not restate the capture rule (`bin/yitc-v2 graph query SPEC-0116`). MCP is just one
transport for that channel-agnostic obligation — a harness-native tool or a raw API call in a shell
incur it equally.

## Territory — an MCP write is outside every repo

An MCP write to an external service (a design project, a chat channel, a third-party API) mutates a
system **OUTSIDE every repo** — it is **NOT a cross-repo write**, so it does not collide with
the scope-boundary discipline. This is the **same legality basis as the SPEC-0084 shared-store
carve-out** (appending the kernel-owned coordination store is in-bounds because that store belongs to
no project repo). What stays forbidden is unchanged: writing another project's REPO. The capture
obligation (§Capture) is what makes the external write accountable, not a territory edit.

## Delivery axis — a built-in tool vs an external MCP server

The same backend is often reachable **two ways for the same capability** — this is a *delivery axis*,
not two backends:

- a **harness-native tool** wired directly into the client (no server to connect; always present), and
- an **external MCP server** exposing equivalent verbs for clients WITHOUT that built-in tool.

**Rule (binding-conditional):** **WITH** the client↔tool binding, the external MCP is **redundant** —
use the built-in tool. **WITHOUT** the binding (another client, a bare agent, the raw API), **connect
the MCP server** — it is the path to the same backend.

This is the GENERAL rule. Its first concrete instance is the design backend (built-in design-sync tool
vs a standalone design MCP), documented in **`patterns/design-tool-roundtrip.md §Delivery axis`** —
which is now an INSTANCE of this rule and carries a back-cite here (P5 — the general rule lives here,
the design specifics stay there; do not duplicate).

## Procedure

1. **Classify the server** — standing (committed project config) or one-off (session/local, uncommitted).
2. **Connect** per your client's mechanics — the concrete commands are in your client's per-client
   `class: adapter` runbook (the provider-named adapter that links back here), never here.
3. **Use** the server's tools for the work.
4. **Capture every substantive external WRITE** with a SPEC-0116 `external_action` event (no worktree —
   the journal-append path); reads need nothing.
5. **At the next session start, reconcile** — drop any one-off you no longer need.

## What this pattern is NOT

- **NOT** a new gate, verb, hook, or auto-disable mechanism — the reconcile is a behavioral read, the
  capture reuses the existing `bin/yitc-v2 event` append (no new store/parser).
- **NOT** a provider reference — it names no commands; the runbook (adapter) carries those.
- **NOT** a second home for the capture rule (that is SPEC-0116) or the design round-trip
  (that is `design-tool-roundtrip.md`) — it POINTS at both.

## Anti-complexity check (CHARTER §Principle 1, four filters — written down)

1. **Existing analog?** Yes — `design-tool-roundtrip.md §Delivery axis` (the delivery axis, here
   GENERALIZED), SPEC-0116 (capture, here POINTED-at), SPEC-0084 (the territory carve-out, reused as the
   legality basis). Composed, not duplicated.
2. **New entity or new view?** A **view** — it adds the two-shelf + reconcile discipline as prose;
   delivery reuses the existing `binding` floor/seed mechanism (SPEC-0118), capture reuses
   `bin/yitc-v2 event`. No new node, parser, gate, or store.
3. **What gets RETIRED (named)?** The per-project re-derivation of «how does v2 work with MCP»; and
   `design-tool-roundtrip.md §Delivery axis` is DEMOTED from a standalone home to an INSTANCE of this
   general rule.
4. **Real incident?** Yes — the kupiclub DesignSync write into design-project `c95f02ff` that fired no
   journal line (2026-06-30, cross X-0138/X-0139). Not imagined.

## Why it travels

Every consumer that connects an external tool-provider faces the same connect/hygiene/capture
questions; the discipline carries no project specifics (SPEC-0090 §2 boundary → `patterns/`, traveling).
Provider-specific command mechanics stay in the per-client `class: adapter` runbook; project-local
craft (which servers THIS repo declares) stays in that repo's `lessons/`.

## See also

- **SPEC-0118** — this pattern's delivery contract (`bin/yitc-v2 graph query SPEC-0118`).
- **SPEC-0116** — the `external_action` external-mutation capture floor (`graph query SPEC-0116`).
- **SPEC-0084** — the shared-store append carve-out (the territory legality basis).
- the per-client `class: adapter` MCP command runbook(s) — the provider-named adapter(s) that carry
  the concrete commands and link back here (non-normative; discover them in the graph / `patterns/`).
- `patterns/design-tool-roundtrip.md` — the design-specific instance of the delivery axis + the
  pulled-edit-set absorption model.
- **cross X-0138 / X-0139** — the MCP-transport + external-interaction-governance seeds this answers.
