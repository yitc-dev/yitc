# Overview — "explain this system to me" (English SoT, voiced by the AI on demand)

Governing cards: **** (this doc) · **SPEC-0147** (person-onboarding, whose reading contract
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

You can try things on real-ish data without touching production. Two bounded modes exist for this,
and each has its own home:

- **spike-mode** — a time-boxed exploration where the usual ceremony is deliberately relaxed so
  you can find out whether an idea works at all. What it relaxes and what it never relaxes:
  `patterns/spike-mode.md`.
- **trial** — a controlled run of a plan against real data before the plan is accepted, so the
  design is judged on evidence rather than on argument: `patterns/trial-methods.md`.

Both are *bounded*: they end, they are recorded, and neither is a way around the tests, the audits
or the deploy gate. Ask your AI to read the pattern before you use either.

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

You are not expected to read a manual. The system carries **17 short onboarding stations** — one
paragraph each, voiced by the AI at the exact moment the thing they explain first comes up (the
first time a `worktree` is created, the first time an audit runs, the first `land`, and so on).
Each is voiced once, then it is gone; nothing tracks your progress and there is no quiz.

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
reason and a note on how to resume, so nothing is lost. Say "refresh the session" when a
conversation has got long and it will hand off cleanly to a new one.

**What does the AI do without asking, and what does it always ask?** It proceeds on its own
whenever the path is clear — analysis, planning, code, tests, shipping. It always stops and asks
you about a genuine fork with no obvious default, ambiguous acceptance criteria, deleting data,
money, secrets, anything irreversible or public, and any new mechanism it wants to add.
