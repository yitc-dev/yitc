---
name: <external-auditor>-auditor-runbook
class: adapter
applies_to: this server's <external-auditor> CLI — the concrete install/update/login/troubleshoot mechanics for the OpenAI <external-auditor> CLI used both as the governed external auditor (bin/yitc-v2 audit / plan check) and as the owner's interactive `<external-auditor>` command. Host-specific paths for <host-home>; multi-user (scoped developer) setup in §Second unix user.
sourced_from: <durable artifact> (move governed audit to the official unconfined <external-auditor> + install bubblewrap) + bin/audit-config.yaml header (provider-binding SoT, CHARTER §P4b) + live host verification 2026-07-07 (this session) + <collaborator> second-login verification 2026-07-13 (events.jsonl#ts= external_action)
---

# <external-auditor> CLI runbook — install / update / login (ADAPTER, NON-NORMATIVE)

> **`class: adapter` — NON-NORMATIVE, NOT a governance source.** This file is the concrete HOW-to-run
> for the <external-auditor> CLI on this server. It establishes no rule/gate. The governance lives in
> **`bin/audit-config.yaml`** (the provider-binding SoT — CHARTER §Principle 4b: concrete model/binary/auth
> bindings live in config, not handbook prose), **SPEC-0036** (the external-auditor invocation contract),
> and **SPEC-0102** (the role→provider binding policy). On any conflict, those WIN. <external-auditor> mechanics change
> upstream — when they do, update THIS file; the specs stay provider-neutral. History: ****.

## TL;DR (what is true on this server)

- The command **`<external-auditor>` = the OFFICIAL OpenAI build** (npm `@openai/<external-auditor>`), installed in a user-owned
  prefix at **`<host-home>/.<external-auditor>-unconfined/`** — currently **0.142.5**.
- `<external-auditor>` resolves to that build via the symlink **`~/.local/bin/<external-auditor> → <host-home>/.<external-auditor>-unconfined/bin/<external-auditor>`**
  (`~/.local/bin` is first on `PATH`, ahead of `/snap/bin`).
- Login is **ChatGPT subscription** (never an API key — no per-token billing). Auth + interactive config
  live in the shared home **`~/snap/<external-auditor>/current/`** (`auth.json` + `config.toml`). Interactive `<external-auditor>`
  finds it via **`export CODEX_HOME="$HOME/snap/<external-auditor>/current"`** in `~/.bashrc`.
- The **governed external auditor** (`bin/yitc-v2 audit` / `plan check`) uses the SAME binary + home,
  pinned in `bin/audit-config.yaml` (`codex_binary:` / `codex_home:`). One <external-auditor>, one login, for both.
- A **second unix user** (scoped developer, e.g. <collaborator>) audits via its **own INDEPENDENT ChatGPT login**
  in its own `~/snap/<external-auditor>/current` — never a copy of dev's auth.json (§Second unix user).

## The two-<external-auditor> history (why it looks confusing)

There used to be a second <external-auditor> on `PATH`: **`/snap/bin/<external-auditor>`**, a **THIRD-PARTY snap repackage**
(publisher `jcat-nysasounds`, NOT OpenAI; `latest/stable` frozen at **0.114.0** since 2026-03). It was too
old for gpt-5.5 (rejects it). (2026-06-29) moved the governed auditor onto the official npm build at
`<host-home>/.<external-auditor>-unconfined`. This session (2026-07-07) also made the **interactive** `<external-auditor>` resolve to
that same official build.

**The snap is retained ONLY as the auth/config home holder** (`~/snap/<external-auditor>/current` = its data dir, where
the ChatGPT login lives). It is no longer invoked as a binary. Do not `snap refresh <external-auditor>` expecting an
update to the tool you run — that channel is a stale third party. (Fully decoupling from the snap — moving
the login home to `~/.<external-auditor>` and `snap remove <external-auditor>` — is a separate future task; it touches the governed
`audit-config.yaml codex_home` and needs the normal lifecycle.)

## Update the <external-auditor> CLI (the one command that matters)

Our build lives in a **local prefix**, so update it WITHOUT root:

```
npm install -g --prefix <host-home>/.<external-auditor>-unconfined @openai/<external-auditor>@latest
# pin a version instead of @latest when you want determinism, e.g. @0.142.5
<host-home>/.<external-auditor>-unconfined/bin/<external-auditor> --version # verify
```

**Do NOT run the bare `npm install -g @openai/<external-auditor>`** that `<external-auditor> doctor` / the update nag suggests. On
this host npm's global prefix is `/usr` (needs sudo) AND it installs to `/usr/lib/node_modules` — a
DIFFERENT install than the one we run. That mismatch is exactly why the official update path "doesn't
work" here. Always pass `--prefix <host-home>/.<external-auditor>-unconfined`.

Check the latest published version: `npm view @openai/<external-auditor> version` (and `dist-tags` for alpha).

## Login / auth

Subscription (ChatGPT) mode is mandatory for the governed auditor — the preflight **refuses launch** if
`OPENAI_API_KEY` is set or `auth.json` is in apikey mode (would bill per token). Interactive use
should stay on the same subscription login.

```
<external-auditor> login status # -> "Logged in using ChatGPT"
<external-auditor> login # (re)authenticate if the subscription token ever expires
<external-auditor> doctor # full health: install / config / auth / sandbox / reachability
```

The login writes to whatever `CODEX_HOME` points at. Keep it on the shared home
(`~/snap/<external-auditor>/current`) so the interactive `<external-auditor>` and the governed auditor share one login — two homes
**holding a COPY of one login** risk auth-token drift when one refreshes and rotates the refresh token.
(Two INDEPENDENT logins on one account are fine — see §Second unix user below.)

## Second unix user (scoped developer) — second INDEPENDENT login, never an auth.json copy

Verified live 2026-07-13 (<collaborator>, for aiseller v2 audits; journal: `events.jsonl#ts=`):

- **The model = one ChatGPT account, N independent logins** (each unix user runs `<external-auditor> login` itself).
  Each home gets its OWN access/refresh token family; families rotate independently and do NOT
  invalidate each other (verified: `<external-auditor> exec` under dev did not touch <collaborator>'s tokens and vice versa).
  This mirrors the the AI provider-accounts F3 finding (independent families coexist; the killer was always
  COPYING one token between homes — two refreshers on one family). **Never copy `auth.json` between
  users; never build a cred-sync for <external-auditor>.** Cost: the users share the one subscription's rate limits.
- **Per-user `CODEX_HOME`:** the governed `codex_home: ~/snap/<external-auditor>/current` (bin/audit-config.yaml)
  is `~`-expanded PER USER — for a second user it resolves to THEIR `/home/<user>/snap/<external-auditor>/current`.
  Export `CODEX_HOME="$HOME/snap/<external-auditor>/current"` in the user's `~/.bashrc` (done for <collaborator> 2026-07-13)
  so an interactive `<external-auditor> login` lands where the auditor reads; without it the login goes to the
  default `~/.<external-auditor>` and the auditor keeps refusing.
- **Binary is shared:** `<host-home>/.<external-auditor>-unconfined/bin/<external-auditor>` is world-executable — a second user
  needs NO own install (<collaborator>'s PATH already prefers it via `<host-home>/.local/bin`).
- **The blocker this fixes:** a stale `auth_mode: apikey` auth.json (or an exported `OPENAI_API_KEY`)
  makes the subscription-only preflight refuse launch (rc126 «subscription preflight refused»).
  Check with `python3 -c "import json;print(json.load(open('/home/<user>/snap/<external-auditor>/current/auth.json'))['auth_mode'])"`
  — must be `chatgpt`.
- **Headless login procedure** (OAuth server binds server-localhost:1455 regardless of user):
  `ssh -L 1455:localhost:1455 <anyone>@<server>`, then
  `sudo -u <user> -H env CODEX_HOME=/home/<user>/snap/<external-auditor>/current <host-home>/.<external-auditor>-unconfined/bin/<external-auditor> login`
  (run from a cwd the target user can read — a `<host-home>` cwd makes <external-auditor> fail on dev's project
  config), open the printed `http://localhost:1455/...` URL in the local browser, sign in to the
  ChatGPT account. Verify: `... <external-auditor> login status` → «Logged in using ChatGPT».

## Interactive vs governed — who reads what

| | Binary | Home (`CODEX_HOME`) | Model |
|---|---|---|---|
| **Interactive `<external-auditor>`** | `~/.local/bin/<external-auditor>` → official build | `~/snap/<external-auditor>/current` (via `~/.bashrc`) | from that home's `config.toml` (gpt-5.5) |
| **Governed auditor** (`bin/yitc-v2 audit` / `plan check`) | `codex_binary:` in `bin/audit-config.yaml` | `codex_home:` in `bin/audit-config.yaml` | per-tier in `audit-config.yaml` (routine gpt-5.5@low · full gpt-5.5@xhigh) |

The auditor also runs sandboxed (`-s read-only`) via bubblewrap (bwrap 0.9.0 + `/etc/apparmor.d/bwrap`,
installed by). To change the auditor's model/effort/binary/home, edit **`bin/audit-config.yaml`**
(the SoT) through the normal lifecycle — never hardcode it elsewhere (CHARTER §P4b, SPEC-0102).

## About "1M context" (set expectations)

gpt-5.5 (released 2026-04-23) is the first OpenAI model with a **1M-token context — but only in the API**.
**<external-auditor> caps gpt-5.5 at 400K tokens** (a deliberate OpenAI throughput/cost decision, tracked upstream at
`openai/<external-auditor>#19464`). So **updating the CLI does not unlock 1M in <external-auditor>** — 400K is the ceiling until
OpenAI lifts it, and we already run gpt-5.5 (i.e. already at that ceiling). Refs:
`openai.com/index/introducing-gpt-5-5/`, `github.com/openai/<external-auditor>/issues/19464`.

## Troubleshooting

- **`<external-auditor> doctor` shows ✗ install / ✗ updates ("would update a different install").** EXPECTED and
  harmless. It compares the running package root (`<host-home>/.<external-auditor>-unconfined/...`) against npm's global
  root (`/usr/lib/node_modules/...`) and they differ by design (we use a rootless local prefix). Update via
  the `--prefix` command above; ignore the ✗.
- **`<external-auditor>` still launches the old snap / version looks stale.** New shell not picked up: open a fresh
  terminal or `source ~/.bashrc`, then `hash -r`. Verify with `readlink -f "$(which <external-auditor>)"` →
  `<host-home>/.<external-auditor>-unconfined/...`.
- **Auditor aborts with a <external-auditor>-binary refusal (rc126) or auth error.** Check `bin/audit-config.yaml`
  `codex_binary:` resolves to an executable and `codex_home:` points at a home with a valid subscription
  `auth.json`. `env YITC_CODEX_AUDIT_BIN=<path>` overrides the binary for a one-off.
- **A full gpt-5.5@xhigh audit times out (rc124 → ABORT + timeout_abort).** Not a ceiling burn. Downgrade
  effort or narrow the audit scope (`AUDIT_TIMEOUT_SECONDS`, default 300, is the cap).

## Refs

- `bin/audit-config.yaml` — provider-binding SoT (binary / home / per-tier model+effort), CHARTER §P4b.
- `SPEC-0036` — external-auditor invocation contract · `SPEC-0102` — role→provider binding policy.
- `` — migration off the third-party snap onto the official unconfined <external-auditor> + bwrap.
- `patterns/the AI provider-code-mcp-runbook.md` — sibling adapter-runbook shape (provider mechanics for a neutral rule).
