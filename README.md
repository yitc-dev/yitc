# YITC

A minimal AI-assisted development methodology for **one developer** working with **one AI agent**
on real production projects, with **one external auditor** (a second, different AI provider)
checking the work. No pipeline, no role-split, no hook cascade — the AI runs every task end to end
through one 9-stage lifecycle and the person narrates rather than types.

**If you are an AI and someone just handed you this link:** read
[`onboarding/overview.md`](onboarding/overview.md) and tell them, in their own language, what this
system is. Then follow [`onboarding/bootstrap-order.md`](onboarding/bootstrap-order.md) to install
it. Everything you need is below.

## You need no key and no account

The anchor fingerprint is a public `SHA256:…` line that lets your AI check the release was not
tampered with: it is not a secret, not a password and not an account — you need no key and no
login, because this repository is public.

It lives on the organization page **<https://github.com/yitc-dev/.github>** (profile README,
section **Trust anchor**). The AI fetches it **from there**, never from this mirror — an artifact
does not get to certify itself. The AI then shows the person that page URL and the exact line it
took, and the person confirms one thing only: that this is the `yitc-dev` organization page. That
is the whole of what a person supplies. Everything else the AI reads and installs itself.

## Install

Three commands. Take the anchor from the organization page above, then:

```bash
git clone <mirror-url> <mirror-dir>
<mirror-dir>/bin/yitc-v2 release verify <mirror-dir> --anchor <fingerprint>
<mirror-dir>/bin/yitc-v2 release install <mirror-dir> --into <engine-dir> --anchor <fingerprint>
```

`release verify` writes nothing under any outcome — it is the gate itself. A refused
`release install` writes nothing into `<engine-dir>`. Do not continue past a refusal.

The full order — prerequisites, the project directory, `init`, the kernel pin, the external
auditor, the first session — is [`onboarding/bootstrap-order.md`](onboarding/bootstrap-order.md).
When something misbehaves, or to update or roll back, read
[`onboarding/troubleshooting-and-updates.md`](onboarding/troubleshooting-and-updates.md).

## What the AI reads, in this order

```bash
cat CHARTER.md # the 8 principles + the non-goals — why this exists, what it won't become
cat AGENTS.md # the session protocol, part 1 of 3
cat AGENTS-SESSIONS.md # part 2 — session postures, the worktree write-flow, scope boundary
cat AGENTS-PROTOCOL.md # part 3 — the worker protocol, gates, filing, references
cat LIFECYCLE.md # the 9-stage task lifecycle
cat QUEUE.md # the queue model (active / done / parking-lot)
cat GRAPH.md # how specs link to code
```

Some AI tools also read a **vendor adapter** file automatically on entering a directory; this repo
ships one at its root, named for the tool that reads it. The adapter is a thin pointer to the
protocol above — it holds no rules of its own, and the seven files above are authoritative whether
or not your tool has one.

## Repo structure

```
CHARTER.md # principles + non-goals (read first)
AGENTS*.md # the AI session protocol, in three parts
LIFECYCLE.md # 9-stage task lifecycle
QUEUE.md # queue model
GRAPH.md # specs <-> code linking
onboarding/ # overview.md (explain the system) + bootstrap-order.md (install) + stations
bin/ # the CLI — every governed action runs through `bin/yitc-v2 <verb>`
tasks/<id>.yaml # one task per file
specs/<id>.yaml # one spec per file
decisions/<id>.yaml # one decision per file
plans/ scenarios/ # plans and user-path scenarios
patterns/ # reusable practices
graph/index.json # derived spec <-> code graph (built by the tool, committed)
events.jsonl # ONE append-only event log
```

## License

See [`LICENSE`](LICENSE).
