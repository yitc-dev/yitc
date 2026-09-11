---
name: the AI provider-code-mcp-runbook
class: adapter
applies_to: the AI provider Code sessions only — the concrete provider mechanics for connecting/using MCP servers, the implementation binding for the provider-neutral patterns/working-with-mcp-in-v2.md
sourced_from: official the AI provider Code MCP docs (code<provider-config>.com/docs/en/mcp.md, mcp-quickstart, managed-mcp), verified 2026-06-30 (plan external-system-interaction-governance-capture-doc §MCP connection mechanics)
---

# the AI provider Code MCP runbook — concrete commands (ADAPTER, NON-NORMATIVE)

> **`class: adapter` — NON-NORMATIVE, NOT a governance source.** This file is a provider binding: the
> concrete the AI provider Code commands that implement the provider-neutral discipline. It establishes NO rule,
> gate, or obligation. The governance lives in **`patterns/working-with-mcp-in-v2.md`** (neutral) and
> **SPEC-0116** (capture); on any conflict, those WIN. Provider commands change upstream — when they do,
> THIS file is updated, the neutral pattern is not. (Same boundary CHARTER §Principle 4b draws:
> methodology text stays provider-neutral; provider bindings live in adapters/runbooks like this one and
> the root `<vendor-adapter>.md` vendor adapter.)

This runbook makes the neutral pattern's abstractions concrete for one client (the AI provider Code). Read the
neutral pattern FIRST for the WHY (the two-shelf model, the session-start reconcile, capture, the
delivery axis); this file is only the HOW-to-type-it.

## Register a server

```
the AI provider mcp add --transport <http|stdio|sse> <name> <url-or-command>
# stdio (a spawned local process):
the AI provider mcp add --transport stdio <name> -- <command> <args...>
# auth header / env:
the AI provider mcp add --transport http <name> <url> --header "Authorization: Bearer <token>"
the AI provider mcp add --transport stdio <name> --env KEY=VAL -- <command>
```

Newer builds also expose `the AI provider mcp login <name>` / `the AI provider mcp logout <name>` for interactive auth.

## Scopes — the project-vs-host axis (maps to the two-shelf model)

| Scope | Config carrier | Visibility | Maps to (neutral pattern) |
|---|---|---|---|
| **local** (default) | `~/<provider-config>.json` under the project entry | you only, this project | a **one-off** (uncommitted) |
| **project** | `.mcp.json` in the repo root — **committed** | the team, on first-load approval | the **standing** committed config |
| **user** | `~/<provider-config>.json` top-level `mcpServers` | you, ALL projects | a personal always-on |

- Share a set with a team/repo → **project scope** (`.mcp.json`, the standing shelf's source of truth).
- Make a server available everywhere for yourself → **user scope**.
- A throwaway server for one session → **local scope** (the one-off shelf; drop it at the reconcile).

> **Standing-shelf SoT (neutral pattern §Shelf 1):** the committed **`.mcp.json`** IS «what this project
> connects». A `lessons/` note may name the servers + why, as a pointer only.

## Launch lifecycle

- **stdio** servers are spawned/owned/terminated by the AI provider Code at session start/end. No auto-reconnect
  on crash → restart the session.
- **http/sse** servers connect lazily/in-background with retry.
- A **new `.mcp.json` entry needs a session restart**; an already-configured server can be
  enabled/authed mid-session via `/mcp`.

## Work with them

- `/mcp` (in-session) — list / auth / reconnect / disable per server. This is the **reconcile surface**
  (neutral pattern §session-start reconcile): use it at session start to disable any extra one-off.
- `the AI provider mcp list` / `the AI provider mcp get <name>` (shell) — inspect configured servers.
- Tools surface as **`mcp__<server>__<tool>`**.

## Built-in tool vs external MCP (the delivery axis, concretely)

A harness-native tool (e.g. DesignSync) is wired into the AI provider Code directly — no server, always present.
An external MCP server exposes equivalent verbs for clients WITHOUT the built-in tool. **With** the
the AI provider Code binding the built-in tool wins (the external MCP is redundant); **without** it, connect the
MCP. (The general rule + the design-backend instance: `patterns/working-with-mcp-in-v2.md §Delivery
axis` + `patterns/design-tool-roundtrip.md §Delivery axis`.)

## Worked example — verified real connect→use

A real, reproduced end-to-end round-trip proving the connection/launch doctrine (X-0138) — not a
built-in tool, an **external MCP server** registered + connected + a tool invoked + a real result.
Reproduced live 2026-06-30 (plan `external-system-interaction-governance-capture-doc`, card).

**1. Connection evidence** — `the AI provider mcp list` (the shell inspect surface) shows the http server
connected:

```
$ the AI provider mcp list
the AI provider.ai the AI provider Code Remote: https://api.the provider.com/v1/code/mcp/meta - ✔ Connected
```

**2. Invoke one of its tools** — the server's verbs surface as `mcp__<server>__<tool>`; here
`mcp__claude_ai_Claude_Code_Remote__list_environments`.

**3. Real result** — the call returned live data, not a stub:

```json
{"environments":[{"environment_id":"env_01GFnAxgFPsEcfgKorp4SJtT","name":"Default",
  "kind":"anthropic_cloud","state":"active"}],"has_more":false}
```

This closes the loop the runbook describes: **register/connect → discover the `mcp__…` tool →
call it → get a real result.** Two boundaries the example also pins:

- **It is a READ, so NO capture fires.** `list_environments` only reads — the SPEC-0116
  `external_action` floor excludes reads (the spec's negative probe), so this round-trip emits no
  `external_action` event. A *write* through such a tool would (see §Capture reminder).
- **A built-in harness tool is NOT this proof.** The harness-native `DesignSync` tool is the
  delivery axis only (X-0136) — it is wired in directly, no server to connect; it cannot stand in
  for the external-server connect→use doctrine this example verifies.

## Capture reminder (the one rule that is NOT optional)

A substantive external WRITE through any `mcp__<server>__<tool>` tool incurs the SPEC-0116
`external_action` capture floor — emit:

```
bin/yitc-v2 event external_action --data '{"channel":"mcp:<server>","target":"<external-object>","action":"<what>","from":"<task/plan/spec id>"}'
```

Reads need nothing. This is governance (SPEC-0116), reproduced here only as an operational reminder —
the rule's home is the spec, not this adapter.

## See also

- `patterns/working-with-mcp-in-v2.md` — the provider-neutral discipline this runbook implements.
- **SPEC-0116** — the `external_action` capture floor (`bin/yitc-v2 graph query SPEC-0116`).
- Upstream depth: the official the AI provider Code MCP docs (code<provider-config>.com/docs/en/mcp.md, mcp-quickstart,
  managed-mcp) — the authoritative, version-current command reference.
