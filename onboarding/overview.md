# Overview — "explain this system to me" (English SoT, voiced by the AI on demand)

Governing cards: **SPEC-0147** (person-onboarding, whose reading contract
this doc reuses) · **SPEC-0195** (release/pin). Placement: **kernel** — it travels in every
release, because the person who needs it has nothing else on the machine yet.

Two reading contracts govern every use of this file — the same two that govern
`onboarding/newcomer-stations.md`, reused rather than restated in a second form:

1. **English SoT, delivered in the person's language.** This body is the canonical single source,
   authored in English. The AI reads the section the person asked about and **voices it in the
   person's own language** — localize at voicing. The raw body is never pasted at the person.
2. **Exact tokens stay verbatim, glossed in-language.** `worktree` · `land` · `deploy` · `spec` ·
   `plan` · `followup` are never translated or renamed; each is paired with a plain gloss in the
   surrounding sentence (precise token, plain sentence).

This doc **points**; it never copies. Where a rule lives elsewhere, the pointer is the content.

## What this is and why

A way of building real software with **one developer, one AI agent, and one external auditor**.

- The **developer** (the owner) says what they want, in ordinary words.
- The **AI agent** does the work — reads, plans, writes code, runs tests, ships.
- The **external auditor** is a second AI from a *different* provider. It reviews the plan before
  the work and the finished change after it. Two providers catch each other's blind spots. It is
  recommended, not required: work runs from day one on the one provider you already have, and any
  review done by the same provider is honestly stamped as such.

There is no pipeline, no team of AI roles, no approval chain. One agent carries one task from
beginning to end. The reason the system has rules at all is the opposite of bureaucracy: an AI
forgets, drifts, and quietly skips steps, so the rules are the few places where that becomes
visible instead of silent.

## What a working day looks like

**The person narrates; the AI operates.** You never type a command. You say what you want; the AI
proposes, you agree, it acts, it reports.

A single piece of work is a **task** and it runs through nine stages, in order:

1. **Analysis** — what already exists, what changes, what the smallest edit is.
2. **Filing** — the task is written down as a card with acceptance criteria.
3. **Plan** — the concrete implementation plan, before any code is touched.
4. **Audit-pre** — the external auditor reviews the *plan*.
5. **Execution** — the code is written.
6. **Tests** — the test suite must pass.
7. **Commit** — the change is committed.
8. **Audit-post** — the external auditor reviews the *shipped change*.
9. **Closure** — the task closes only with evidence it actually works.

Then `land` — the token for integrating the finished branch into the main line, after the tests
re-run — and, for anything user-facing, `deploy` — the token for putting it live.

Two things this ordering buys you. Nothing ships that a second mind has not seen. And "done" means
*adopted*, never "the code is written": a task cannot close without evidence that the thing it
built actually ran.

## Your first project

Start with an **empty directory** and your AI tool open in it. The AI does all of the following;
you answer and agree.

1. `init` — the AI runs the setup verb. This creates the project's scaffolding.
2. **The mandatory answers** — `init` walks you through a short set of questions about the project
   (what it is, where it deploys, where secrets live). Each one may be answered or explicitly
   waived; nothing is guessed for you.
3. **The first scenario** — a `scenario` is a plain-language description of one user path
   ("a visitor signs up and gets a confirmation e-mail"). You narrate it; the AI writes it down.
4. **The first plan** — a `plan` is the token for a piece of work too big for one task. The AI cuts
   it into task cards, each with its own acceptance criteria.
5. **The first task** — the AI claims one card and runs the nine stages above.

The full install order that precedes all of this — prerequisites, verifying the download, the
kernel pin, binding the auditor — is [`bootstrap-order.md`](bootstrap-order.md).

## The sandbox

Five things sound alike here. Only a running copy of your project is a **sandbox** (a PLACE); a
spike is an EXPERIMENT, and the venue is not a sandbox at all. This short glossary keeps them apart:

| Name | What it is | When you need it | When you do not |
| --- | --- | --- | --- |
| **sandbox — a running copy** | a separately deployed running copy of the project on a non-production deploy target, with its own data, in one of two roles: the **ACCEPTANCE stand (ПРИЁМКА)** — acceptance mode — shows landed code at its own address; the **DEV stand (ДОРАБОТКА)** — spike mode — serves the open spike (`patterns/spike-mode.md`, SPEC-0205 rule 7) | you want to see and click the result before production, or try an idea on a running system | day one — it pays off once the product is being iterated |
| **spike data copy** (formerly "spike-sandbox data floor") | a restored copy of production data, cleaned before use, that a spike runs against (SPEC-0172, SPEC-0175) | a spike has to see real-shaped data to answer its question | the idea can be tested on made-up data, or the project has no production data yet |
| **spike and plan trial** | bounded ways to try something before committing to it: a `spike` is an experiment (never lands; parked as tag `spike/<slug>`, which a real card cites as `prototype_ref`); **spike by default** — while a spike is open, a change to what it explores goes into the spike, with no card, unless you say to do it as a card («задачей»), the change is not about what the spike explores (an urgent production fix), or, in doubt, the AI asks you one question; finished work follows card → land → ACCEPTANCE stand → production, and `deploy` only prints advisory lines that never block (SPEC-0205 rules 7, 10, 11; walk-through incl. handing off part of a spike: [Station R](newcomer-stations.md)); a plan trial soaks a plan against real data before it is accepted (`patterns/spike-mode.md`, `patterns/trial-methods.md`) | you are not sure an idea or a new mechanism will work | the change is small and clear — just do it as a normal task |
| **sandbox for another person** | the separate place where a collaborator you let in does their work, so they never touch your main copy (`sandbox_entry`, SPEC-0169) | you give someone else access to the project | you work on the project alone |
| **the venue ("box")** | a separate computer that runs the project's test checks when this machine is too small or too busy (SPEC-0203) | a project's checks outgrow the machine it lives on | almost always at the start — a new project runs its checks on its own machine |

**The venue is neither a sandbox nor an accelerator.** It is not a place to try things, and it is not
a way to make your work go faster. It is a capability a project may need later, when its checks grow
too big for one machine — nothing to set up on day one.

**The venue is optional.** Without it every check runs on your own machine; switch it on only if it pays (`patterns/verify-venue-when-it-pays.md`).

A spike and a plan trial are *bounded*: they end, they are recorded, and neither is a way around the
tests, the audits or the deploy gate. Ask your AI to read the pattern before you use either.

## Why not just a bare agent

You could simply open an AI agent and ask it to build things, with no method around it. That works
for small things. On real projects, a bare agent fails in three quiet ways: it **forgets** what was
decided once the session ends, it **silently skips steps** (the test it meant to run, the case it
meant to check), and it **calls work done that nobody verified**.

What this method adds, one answer per failure:

- **A card per task, with acceptance criteria** — every piece of work is written down with what
  "finished" must prove, so nothing depends on the agent remembering.
- **A second opinion, twice** — the auditor (a second provider when you have one; else the same
  provider, stamped as such) checks the plan before any code and the result after it ships.
- **Done means proven working** — a task closes only with evidence that the thing actually ran,
  never on "the code is written".
- **One journal** — `events.jsonl`, the single record of what each task set out to do and what was
  actually done, so the next session picks up where the last one stopped instead of from memory.
- **Isolated working copies** — each task writes in its own `worktree`, so tasks running at the same
  time cannot overwrite each other's work in progress, and your main copy only changes at `land`
  (where two changes to the same lines still have to be reconciled).

**The cost, honestly.** Every task takes more steps and more time than just asking an agent: a card,
a plan, two reviews, a test run, a land. For a five-minute edit that is overkill — for a change you
could check at a glance, a bare agent is faster. The method pays off where the work matters: code
you will keep, ship to real people, or come back to next month. Bounded examples: [`troubleshooting-and-updates.md`](troubleshooting-and-updates.md).

## Where things live

Everything is plain files in your project's own git repository. Nothing lives in a database, a
cloud service, or an account somewhere.

| Where | What |
| --- | --- |
| `tasks/` | one file per task — the card, its acceptance criteria, its status |
| `specs/` | one file per `spec` — the token for a written-down standing rule |
| `plans/` | one file per `plan` — a piece of work cut into tasks |
| `scenarios/` | the user paths, in plain language |
| `patterns/` | reusable practices — the shelf of general how-we-do-it notes |
| `events.jsonl` | ONE append-only log of everything that happened, across all sessions |
| `MEMORY.md` | a short scratch buffer of notes-for-next-time; entries are used once and deleted |

And one more: a **`worktree`** — the token for a separate working copy of your project that one
task writes in, so several sessions can work at once without colliding. This is why your main
directory can look unchanged while work is in progress: the work is real, it is just in its own
worktree until `land` folds it in.

## Trust and the anchor

The anchor fingerprint is a public `SHA256:…` line that lets your AI check the release was not
tampered with: it is not a secret, not a password and not an account — you need no key and no
login, because this repository is public.

It lives on the organization page **<https://github.com/yitc-dev/.github>** (profile README,
section **Trust anchor**). The AI fetches it **from there**, never from the mirror it is about to
check — an artifact does not get to certify itself. The AI then shows you that page URL and the
exact line it took, and you confirm one thing only: that this is the `yitc-dev` organization page.

## When the AI will explain more

You are not expected to read a manual. The system carries **18 short onboarding stations** — one
paragraph each, voiced by the AI at the exact moment the thing they explain first comes up (the
first time a `worktree` is created, the first time an audit runs, the first `land`, and so on).
Each comes back a couple of times after a pause, so it sticks, then goes quiet; say "remind me what X
is" to hear one again, or "I know it" to stop its repeats. Nothing stores your progress and there is no quiz.

The station bodies live in [`newcomer-stations.md`](newcomer-stations.md). You never read that file
— your AI does, and tells you the one paragraph that is due.

When the kernel misbehaves, or you ask about an update or a rollback, your AI reads
[`troubleshooting-and-updates.md`](troubleshooting-and-updates.md).

## FAQ

**Do I need a key, an account or a licence?** No. The repository is public and the only extra piece
is the public anchor fingerprint described above.

**What if I have no second AI provider for the auditor?** Everything still works. Audits run on
your one provider and each such verdict is stamped `same-provider`, so you can always tell whether
a different mind checked the work. A reminder prints at each session start until you bind a second
one; nothing waits and nothing is refused.

**Can I use this for several projects?** Yes — that is what it is for. The engine is installed once
on the machine; each project is its own directory with its own tasks, specs and log.

**Where do my secrets go?** Never into the repository and never into a commit. `init` asks where
your secrets live on your machine and records the location, not the values.

**What is a `worktree`, and why does my main directory look stale?** A `worktree` is a separate
working copy one task writes in. Your main directory only moves forward at `land`. That is the
isolation working, not a bug — it is what lets several tasks run at the same time.

**How do I stop, or start fresh?** Say so in plain words. The AI parks the current task with its
reason and a note on how to resume, so nothing is lost. When a conversation has got
long, say «обновим сессию» ("refresh the session"): the AI saves a hand-off and names it H-N (a number, like H-12).
Open a new session in the same project — the startup report lists it — and say «берём H-N»; work
continues, with nothing for you to carry over.

**What does the AI do without asking, and what does it always ask?** It proceeds on its own
whenever the path is clear — analysis, planning, code, tests, shipping. It always stops and asks
you about a genuine fork with no obvious default, ambiguous acceptance criteria, deleting data,
money, secrets, anything irreversible or public, and any new mechanism it wants to add.
