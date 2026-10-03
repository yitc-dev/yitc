---
name: <external-auditor>-auditor-runbook
class: adapter
applies_to: this server's <external-auditor> CLI — the concrete install/update/login/troubleshoot mechanics for the OpenAI <external-auditor> CLI used both as the governed external auditor (bin/yitc-v2 audit / plan check) and as the owner's interactive `<external-auditor>` command. Paths are named by their setting / env (codex_home, CODEX_HOME, YITC_CODEX_AUDIT_BIN) wherever one exists; multi-user (scoped developer) setup in §Second unix user.
sourced_from: <durable artifact> (move governed audit to the official unconfined <external-auditor> + install bubblewrap) + bin/audit-config.yaml header (provider-binding SoT, CHARTER §P4b) + live host verification 2026-07-07 (this session) + <collaborator> second-login verification 2026-07-13 (events.jsonl#ts= external_action)
---

# <external-auditor> CLI runbook — install / update / login (ADAPTER, NON-NORMATIVE)

> **`class: adapter` — NON-NORMATIVE, NOT a governance source.** This file is the concrete HOW-to-run
> for the <external-auditor> CLI on this server. It establishes no rule/gate. The governance lives in
> **`bin/audit-config.yaml`** (the provider-binding SoT — CHARTER §Principle 4b: concrete model/binary/auth
> bindings live in config, not handbook prose), **SPEC-0036** (the external-auditor invocation contract),
> and **<workshop-spec>** (the role→provider binding policy). On any conflict, those WIN. <external-auditor> mechanics change
> upstream — when they do, update THIS file; the specs stay provider-neutral. History:.

## TL;DR (what is true on this server)

- The command **`<external-auditor>` = the OFFICIAL OpenAI build** (npm `@openai/<external-auditor>`), installed in a user-owned
  npm prefix (`~/.<external-auditor>-unconfined/`, the prefix `~/bin/<external-auditor>-update.sh` owns). Its version is whatever
  `<external-auditor> --version` prints — never written down here; the MINIMUM each auditor model needs is a setting,
  `bin/effort-routing-config.yaml` `worker_providers.<external-auditor>.min_version`, enforced before spawn.
- `<external-auditor>` resolves to that build through `~/.local/bin/<external-auditor>` (`~/.local/bin` is first on `PATH`, ahead
  of `/snap/bin`).
- Login is **ChatGPT subscription** (never an API key — no per-token billing). Auth + interactive config
  live in the home named by **`codex_home:`** in `bin/audit-config.yaml` (`auth.json` + `config.toml`).
  Interactive `<external-auditor>` finds the same home via **`CODEX_HOME`** exported in `~/.bashrc`.
- The **governed external auditor** (`bin/yitc-v2 audit` / `plan check`) uses the SAME binary + home:
  the binary resolves `YITC_CODEX_AUDIT_BIN` > `<external-auditor>` on PATH, the home is `codex_home:`
  (an already-set `CODEX_HOME` wins). One <external-auditor>, one login, for both.
- A **second unix user** (scoped developer, e.g. <collaborator>) audits via its **own INDEPENDENT ChatGPT login**
  in its own `codex_home:` — never a copy of dev's auth.json (§Second unix user).

## The two-<external-auditor> history (why it looks confusing)

<!-- cli-version-history -->
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
<!-- /cli-version-history -->

## Update the <external-auditor> CLI (the one command that matters)

Run **`~/bin/<external-auditor>-update.sh`** (`[<version>|latest]`, `--dry-run`, `--rollback`) — it installs into the
right prefix, backs up the package and the auth, and checks auth plus a real `<external-auditor> exec` before it
reports success. Do NOT run the bare `npm install -g @openai/<external-auditor>` the update banner / `<external-auditor> doctor`
suggests: on this host npm's global prefix is `/usr`, so it needs root AND installs a different copy
than the one `PATH` runs.

## Login / auth

Subscription (ChatGPT) mode is mandatory for the governed auditor — the preflight **refuses launch** if
`OPENAI_API_KEY` is set or `auth.json` is in apikey mode (would bill per token). Interactive use
should stay on the same subscription login.

```
<external-auditor> login status # -> "Logged in using ChatGPT"
<external-auditor> login # (re)authenticate if the subscription token ever expires
<external-auditor> doctor # full health: install / config / auth / sandbox / reachability
```

The login writes to whatever `CODEX_HOME` points at. Keep it on the home `codex_home:` names so the interactive `<external-auditor>` and the governed auditor share one login — two homes
**holding a COPY of one login** risk auth-token drift when one refreshes and rotates the refresh token.
(Two INDEPENDENT logins on one account are fine — see §Second unix user below.)

## Second unix user (scoped developer) — second INDEPENDENT login, never an auth.json copy

Verified live 2026-07-13 (<collaborator>, for <project> v2 audits; journal: `events.jsonl#ts=`):

- **The model = one ChatGPT account, N independent logins** (each unix user runs `<external-auditor> login` itself).
  Each home gets its OWN access/refresh token family; families rotate independently and do NOT
  invalidate each other (verified: `<external-auditor> exec` under dev did not touch <collaborator>'s tokens and vice versa).
  This mirrors the AI provider-accounts F3 finding (independent families coexist; the killer was always
  COPYING one token between homes — two refreshers on one family). **Never copy `auth.json` between
  users; never build a cred-sync for <external-auditor>.** Cost: the users share the one subscription's rate limits.
- **Per-user `CODEX_HOME`:** the governed `codex_home:` (bin/audit-config.yaml) is `~`-expanded PER
  USER — for a second user it resolves under THEIR home. Export `CODEX_HOME` to that same
  `codex_home:` value in the user's `~/.bashrc` (done for <collaborator> 2026-07-13)
  so an interactive `<external-auditor> login` lands where the auditor reads; without it the login goes to the
  default `~/.<external-auditor>` and the auditor keeps refusing.
- **Binary is shared:** `<host-home>/.<external-auditor>-unconfined/bin/<external-auditor>` is world-executable — a second user
  needs NO own install (<collaborator>'s PATH already prefers it via `<host-home>/.local/bin`).
- **The blocker this fixes:** a stale `auth_mode: apikey` auth.json (or an exported `OPENAI_API_KEY`)
  makes the subscription-only preflight refuse launch (rc126 «subscription preflight refused»).
  Check with `python3 -c "import json,os;print(json.load(open(os.environ['CODEX_HOME']+'/auth.json'))['auth_mode'])"`
  — must be `chatgpt`.
- **Headless login procedure** (OAuth server binds server-localhost:1455 regardless of user):
  `ssh -L 1455:localhost:1455 <anyone>@<server>`, then
  `sudo -u <user> -H env CODEX_HOME=<that user's codex_home> "$(readlink -f "$(which <external-auditor>)")" login`
  (run from a cwd the target user can read — a `<host-home>` cwd makes <external-auditor> fail on dev's project
  config), open the printed `http://localhost:1455/...` URL in the local browser, sign in to the
  ChatGPT account. Verify: `... <external-auditor> login status` → «Logged in using ChatGPT».

## Interactive vs governed — who reads what

| | Binary | Home (`CODEX_HOME`) | Model |
|---|---|---|---|
| **Interactive `<external-auditor>`** | `<external-auditor>` on PATH → official build | `CODEX_HOME` (via `~/.bashrc`) | from that home's `config.toml` |
| **Governed auditor** (`bin/yitc-v2 audit` / `plan check`) | `YITC_CODEX_AUDIT_BIN` > `<external-auditor>` on PATH | `codex_home:` in `bin/audit-config.yaml` | per-tier in `audit-config.yaml` (primary + reserve pair per tier) |

The auditor also runs sandboxed (`-s read-only`) via bubblewrap (`bwrap` + `/etc/apparmor.d/bwrap`,
installed). To change the auditor's model/effort/binary/home, edit **`bin/audit-config.yaml`**
(the SoT) through the normal lifecycle — never hardcode it elsewhere (CHARTER §P4b, <workshop-spec>).

## About "1M context" (set expectations)

gpt-5.5 (released 2026-04-23) is the first OpenAI model with a **1M-token context — but only in the API**.
**<external-auditor> caps gpt-5.5 at 400K tokens** (a deliberate OpenAI throughput/cost decision, tracked upstream at
`openai/<external-auditor>#19464`). So **updating the CLI does not unlock 1M in <external-auditor>** — 400K is the ceiling until
OpenAI lifts it, and we already run gpt-5.5 (i.e. already at that ceiling). Refs:
`openai.com/index/introducing-gpt-5-5/`, `github.com/openai/codex/issues/19464`.

## Troubleshooting

- **`<external-auditor> doctor` shows ✗ install / ✗ updates ("would update a different install").** EXPECTED and
  harmless. It compares the running package root (the user prefix) against npm's global root
  (`/usr/lib/node_modules/...`) and they differ by design (we use a rootless local prefix). Update via
  `~/bin/<external-auditor>-update.sh`; ignore the ✗.
- **`<external-auditor>` still launches the old snap / version looks stale.** New shell not picked up: open a fresh
  terminal or `source ~/.bashrc`, then `hash -r`. Verify with `readlink -f "$(which <external-auditor>)"` → the
  user prefix, not `/snap/...`.
- **Auditor aborts with a <external-auditor>-binary refusal (rc126) or auth error.** Check the binary resolves
  (`YITC_CODEX_AUDIT_BIN`, else `<external-auditor>` on PATH) and `codex_home:` points at a home with a valid
  subscription `auth.json`. `env YITC_CODEX_AUDIT_BIN=<path>` overrides the binary for a one-off.
- **Auditor refuses before spawn: <external-auditor> older than the model's minimum.** Update with
  `~/bin/<external-auditor>-update.sh`; the floor is `worker_providers.<external-auditor>.min_version`.
- **A full-tier (high-effort) audit times out (rc124 → ABORT + timeout_abort).** Not a ceiling burn. Downgrade
  effort or narrow the audit scope (`AUDIT_TIMEOUT_SECONDS`, default 300, is the cap).

## Refs

- `bin/audit-config.yaml` — provider-binding SoT (binary / home / per-tier model+effort), CHARTER §P4b.
- `bin/effort-routing-config.yaml` `worker_providers.<external-auditor>.min_version` — per-model minimum <external-auditor>.
- `SPEC-0036` — external-auditor invocation contract · `<workshop-spec>` — role→provider binding policy.
- `` — migration off the third-party snap onto the official unconfined <external-auditor> + bwrap.
- `patterns/claude-code-mcp-runbook.md` — sibling adapter-runbook shape (provider mechanics for a neutral rule).
