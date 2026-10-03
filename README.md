# YITC

A minimal AI-assisted development methodology for **one developer** working with **one AI agent**
on real production projects, with **one external auditor** (a second, different AI provider)
checking the work. No pipeline, no role-split, no hook cascade — the AI runs every task end to end
through one 9-stage lifecycle and the person narrates rather than types.

**If you are an AI and someone just handed you this link:** read
[`onboarding/overview.md`](onboarding/overview.md) and tell them, in their own language, what this
system is. Then follow [`onboarding/bootstrap-order.md`](onboarding/bootstrap-order.md) to install
it. Everything you need is below.

## What you get and what you need

**What you get.** An AI that works on your project the way a careful developer would: it plans each
change, has it checked, tests it, and keeps a written record of what it did and why. You say what
you want in your own words; the AI does the typing.

**What you need.**
- **A server** — a rented Linux machine is enough.
- **One AI tool with its account.** Either a subscription (a fixed monthly price) or usage-based
  billing (you pay for what you use). Either works.

**Who does the work.** Project work runs as an **ordinary user** on the server. The all-powerful
administrator account (root) is needed only for the first few minutes of setup, and not after.

**Coming back next time.** The same five steps every time (the day-two return path; nothing starts
by itself, and the home folder does not list your projects on its own):

```text
1. ssh <user>@<server> log in as your working user
2. tmux attach -t yitc back into your kept terminal (after a reboot: tmux new -s yitc)
3. <your AI tool> open it in any folder, or clear the session already open
4. /yitc-projects type the start command, then pick the project
5. the start line "Working in YITC mode — project <name>." must appear
```

This one order is also how you start the first time and how you restart — there is no separate
start inside the project folder. Steps 3 and 4 show the AI tool form (clear with `/clear`); in
<external-auditor> the start command is `$yitc-projects` (clear with `/new`); every tool's two commands are in
the AI-tool list `bin/ai-tools.yaml` (`invoke`, `clear_session`).

**An optional second AI provider.** You can start with just the one AI tool. Adding a second,
different AI provider as an auditor is recommended: it checks the first one's work and catches the
blind spots the first one cannot see in itself.

**Two stands, when the product is iterated.** Not needed on day one. A project can keep two running
copies besides production: the **DEV stand (ДОРАБОТКА)**, where an open spike — an experiment — is
tried, and the **ACCEPTANCE stand (ПРИЁМКА)**, which shows landed `main` so you can click the result
before real users do. While a spike is open, changes to what it explores go into the spike by default.
The recommended order for finished work is card → land → ACCEPTANCE stand → production; `deploy` only
prints advisory reminders and never blocks (SPEC-0205).

## You need no key and no account to install

This is about **installing** only. Later steps may need accounts of their own — a domain for
production, a second place to keep the off-server copy of your project.


The anchor fingerprint is a public `SHA256:…` line that lets your AI check the release was not
tampered with: it is not a secret, not a password and not an account — you need no key and no
login, because this repository is public.

It lives on the organization page **<https://github.com/yitc-dev/.github>** (profile README,
section **Trust anchor**). The AI fetches it **from there**, never from this mirror — an artifact
does not get to certify itself. The AI then shows the person that page URL and the exact line it
took, and the person confirms one thing only: that this is the `yitc-dev` organization page. That
is the whole of what a person supplies. Everything else the AI reads and installs itself.

## Install

The anchor and the three install commands live in **one place only**: the organization page
**<https://github.com/yitc-dev/.github>** (sections **Trust anchor** and **Install**). Take them
from there, never from this mirror, and do not continue past a refusal.

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
