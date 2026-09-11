# Newcomer stations — the person-onboarding station copy (English SoT)

Governing contract: **SPEC-0147** (person-onboarding — seeded, recipient-scoped, consume-on-encounter).
Placement: **kernel** — this is kernel-provided seed CONTENT that travels to consumers (SPEC-0073).

This file is the ONE home for the station bodies. Three reading contracts govern every use of it:

1. **English SoT, delivered in the person's language** (SPEC-0147 rule 6). The bodies below are the
   canonical single source, authored in English. At runtime the AI reads the body whose seam it has just
   reached and **voices it in the USER's language** — localize-at-voicing. The raw body is **never shown**
   to the person, and no per-language files are stored.
2. **Exact tokens stay verbatim, glossed in-language.** `worktree` · `land` · `deploy` · `spec` · `plan` ·
   `followup` are never translated or renamed; each is paired with a plain gloss in the surrounding
   sentence (precise token, plain sentence — AGENTS §Language register rule).
3. **`MEMORY.md` stays pointer-only** (SPEC-0147 rule 3 / VP6). The buffer carries ONLY a short
   consume-once pointer line per not-yet-seen station; the bodies live solely here.

**Delivery.** A station is voiced ONCE, when its seam is first reached, and its pointer is then deleted —
consume-on-encounter, never detect-on-mastery (SPEC-0147 rule 1). No state tracks progress or mastery.
Once the last pointer is gone the person carries zero onboarding footprint.

**The core mental model, shaping every station: the user NARRATES, the AI OPERATES.** The person never
types a command. Every station therefore ends with **what the user SAYS**, never a command to type, and
carries a safety-net tail so the person never dead-ends (SPEC-0147 rule 7).

## Station ↔ seam binding

The delivery SoT (SPEC-0147 rule 5). Every seam below is a juncture the system **already** crosses — the
`session start` read, a verb the AI itself invokes, or a moment the AI recognizes in its own reasoning
(station C's shape). Nothing detects a seam and nothing tracks progress: the crossing **is** the verb call
or the recognized moment. `bin/lib/memory.py#STATION_SEAMS` is this table in code, and
`tests/test_t10268_station_seam_bindings.py` pins the two together so they cannot drift apart.

| Station | Seam (existing) | Where it is emitted |
|---|---|---|
| A. Start | `session start` | the session-start pointer digest |
| B. Scenarios | `scenario` | `scenario new` |
| C. "How do we build this" fork | `design fork` | **no verb** — the AI recognizes its own Recommendation-Default moment |
| D. The project's mandatory answers (and secrets) | `init` | `init` (the declare-or-waive walk, SPEC-0096) |
| E. The first plan and its stages | `plan file` | `plan file` |
| F. Auditors and models | `audit` | `audit pre` / `audit post` / `audit adhoc` |
| G. Tasks, Workers — and the worktree at its moment | `worktree new` | `worktree new --task` (the claim) |
| H. Small things for later — followup | `followup` | `followup add` |
| I. Finishing: land and deploy | `land`, `deploy` | `land` / `deploy` — whichever is crossed first |
| J. Reviews, debt, coordination — and memory | `inspect` | `inspect record` (and the session-start debt/cross echo) |
| K. External shared libraries | `shared library` | **no verb** — the AI recognizes the topic (a shared/pinned dependency comes up) |
| L. Signalling a fix to the kernel | `kernel signal` | **no verb** — the AI recognizes it is about to mark a YITC-machinery bug/gap for the kernel |
| M. Parallel sessions | `parallel sessions` | **no verb** — the AI recognizes it (a foreign-worktree block, or several sessions at once) |
| N. Driving the plan to the end | `drive to the end` | **no verb** — the AI recognizes the owner's "run it to the end" cue (a plan/batch drive begins) |
| O. Plan trial and postcheck | `plan trial` | **no verb** — the AI recognizes the trial / postcheck fork while running plan stages |
| P. Session refresh and context | `session refresh` | **no verb** — the AI recognizes the context threshold, or the owner's "refresh the session" cue |
| Q. Dictating a list of wishes | `dictated list` | **no verb** — the AI recognizes an owner-dictated list of wishes/constraints |

## Delivery protocol

At session start the AI is told which stations this person still holds (recipient-scoped by
`[audience: user(<name>)]`); at each seam above, the verb prints the station due there, if any. Holding a
pointer, the AI then does exactly two things, once:

1. **Ask first, then voice** (the ask-first form, SPEC-0147 rule 5). At the station's occasion the AI
   FIRST asks the person, in their own language, whether the concept is already familiar (e.g. «знакомо ли
   тебе X / умеешь ли применять?»). If **yes** → skip the body (the person already knows it); if **no** →
   **voice** the station's body below in the **person's language** (localize-at-voicing, rule 6) — never
   paste the raw English body, never voice a station before its occasion has arrived, never several at
   once. **Station A is EXEMPT** — it is always voiced plainly, with no preceding question (asking a
   brand-new person whether YITC is already familiar is meaningless).
2. **Retire** it: `bin/yitc-v2 memory consume --station <id>` (a `-C` consumer invokes the engine CLI).
   The pointer is deleted whichever way the person answered — consume-once — and one
   `onboarding_station_consumed` event is written. There is no re-ask loop and no stored asked / learned /
   mastery state of any kind (rule 1 / VP2 / VP5 hold verbatim): the question is a per-occasion voicing
   choice that persists nothing.

Station C — and the AI-recognized stations K, M, N, O, P, Q (and L) — have no verb to ride: the AI voices
each when it first hands the person the matching real moment. A person holding no pointers (a seasoned
user) sees nothing at any seam — the zero-steady-state-cost guarantee (rule 2).

**Topic-mention fallback — the second occasion.** A station still pending may ALSO be voiced at the first
natural MENTION of its exact topic in conversation, judged the same way station C's fork moment is. This
exists so a station whose seam a person never crosses does not linger forever: a design-only collaborator
may never reach `init`, `plan file`, `audit`, `land`, or `inspect`, yet those topics still come up. The
seam stays the primary occasion; the mention is the narrow secondary one. It is an **occasion, not a
mechanism** — nothing watches the conversation, nothing tracks what the person has learned, and voicing
stays consume-once (rule 1). The bound is legislated in **SPEC-0147 rule 5**; read it there.

---

## [A] Start
*Seam: `session start`.*

YITC is a thin methodology: its only job is to make YOUR projects ship faster — it is not itself a
product. At session start I read all its rules; you don't need to hold them in your head. The key thing:
YOU narrate, I operate. You don't type commands or memorize terms — you say what you want in plain words
and I translate it into the system's actions and tell you what's happening. Steer me anytime: "stop",
"undo that", "show me what came out", "redo from point X". If a tool breaks, I'll say what's unavailable
and ask before taking any fallback path. Work on a new project starts not with code but with describing
what you're building.

-> You say: what shall we start with — what's the product?

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [B] Scenarios
*Seam: `scenario` — the first "what we're building" talk.*

A project starts not with code but by describing WHAT you build and how a person uses it. That's a
scenario — a user's path told in plain language. It becomes the anchor everything else (rules, checks)
attaches to, which is why we begin there. You don't format anything by hand — you tell me the user's
story and I record it as a scenario.

-> You say: describe how a person moves through your product, step by step, in your own words.

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [C] "How do we build this" fork
*Seam: `design fork` — the first structural fork (no verb; AI-recognized).*

> **The trigger moment, concretely** (operator note — not voiced to the person). Voice C when any of
> these first happens: **(1)** you are about to present a Recommend/Alternatives fork on how to structure
> something — the Recommendation-Default moment itself; **(2)** the person asks "how should we build
> this?" / "which way do we go?"; **(3)** two or more viable paths have just been named and one must be
> chosen. Judged by you, once, then consumed — no state, no detector (SPEC-0147 rules 1 + 5).

Sometimes the question isn't WHAT but HOW to build it, with several paths. You don't decide blind: I
always give ONE recommendation with a reason, and alternatives with their downsides — so the choice is
informed, not "here are three options, you figure it out". On a serious (architectural) fork you can call
in an external auditor — a different AI, not me; it looks at the idea from outside and catches my blind
spots. That's an option, not an obligation.

-> You say: which way you lean, or "show me the options", or "ask the auditor".

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [D] The project's mandatory answers (and secrets)
*Seam: `init` — the declare-or-waive walk.*

Before real work the project answers a few baseline questions: how to deploy, how to handle secrets, what
behavioral defaults. Each is "answer or explicitly waive" — so nothing important slips by silently. I'll
ask them one at a time, in plain words, and record your answers. Separately and up front, on safety:
never paste passwords, keys, or tokens into chat or code — there's a separate protected place for them;
if one's needed I'll tell you where to put it and ask you to do it yourself.

-> You say: just answer the questions when I bring them.

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [E] The first plan and its stages
*Seam: `plan file`.*

When something is bigger than a quick fix, we make a plan. A plan isn't free text — it's an intent that
moves through fixed stages: draft -> rules crystallize out of it (spec) -> intent confirmed -> cut into
tasks -> tasks run -> checked on real data and closed. I lead you through the stages and ask you at each
human decision point; you don't need to memorize the order — I say where we are and what's next. On heavy
transitions an external auditor checks the plan (see the next station).

-> You say: describe the larger task, or "let's make it a plan" — I take it from there.

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [F] Auditors and models
*Seam: `audit`.*

At important gates an independent external auditor checks the work — a different AI, not me; the point of
its independence is that it catches mistakes and blind spots I might miss on my own. For big and
architectural work — a full, thorough pass; for routine — a light one. How "heavy" the work is decides
which model is used; you don't need to pick a model.

-> You say: by default, trust the gates; want an extra check — "run it past the auditor".

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [G] Tasks, Workers — and the worktree at its moment
*Seam: `worktree new` — the task claim, at the first edit.*

A plan is cut into tasks (task) — concrete pieces of work. Each task runs through 9 stages (from analysis
to closure). Usually the work is done by a background Worker that I launch; you, in conversation with me,
are the Controller — the one directing. Want it done by me directly — say so. You don't manage this by
hand: you say "go" and I hand it out and watch. And exactly when I'm first about to change something, I'll
say in one line: "making a separate working copy — a worktree — so parallel edits don't collide; nothing
needed from you."

-> You say: "go" / "take this into work".

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [H] Small things for later — followup
*Seam: `followup` — the first mid-work adjacent discovery.*

While working you'll notice other things worth fixing. The rule is simple: we don't grow the current
task. I record such things as a followup — a short "should do, later" note — and we come back to it
separately when the time comes. That keeps the current work focused and finished, and the thought isn't
lost. These notes later surface as "debt" — the accumulated "should come back to" list.

-> You say: noticed something in passing — just say it, I'll record a followup and we continue.

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [I] Finishing: land and deploy
*Seam: `land`, `deploy` — whichever comes first.*

Two different "done"s, easy to confuse: land = merge the finished working copy (worktree — the separate
branch where edits happened) back into our main branch, running the real tests as it goes. That's the
local "accepted". deploy = ship to the live server, where real users see the change. A separate step,
with a risk assessment and confirmation. Before that I also run the change for real (verify), so "works"
means works, not "tests are green". I do all of this.

-> You say: "merge it" -> I do land; "ship it" -> I do deploy (I'll ask for confirmation).

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [J] Reviews, debt, coordination — and memory
*Seam: `inspect` — the first review/debt/cross surface.*

Three things run in the background and surface on their own — I show them when it's time: a review
(revizia) — a periodic self-inspection of the system; debt — accumulated followups, those "should come
back to"s; coordination — the log of communication between projects (if one touched another). And two
abilities you can use with words, no commands: ask "what did we decide about this before?" — every
directive and decision you give is journaled verbatim as we go, so nothing is ever lost, and I pull the
exact history back for you; and say "remember this for later" and I'll store it in the right place myself.

-> You say: when one of these surfaces — "let's deal with it" or "later".

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [K] External shared libraries
*Seam: `shared library` — the first time shared/pinned dependency code comes up (no verb; AI-recognized).*

Some code isn't yours — it's a shared library: a common piece several projects depend on, pinned to a
fixed version so an update never surprises you. The rule: we never patch a shared library in place here. If
it has a bug or a missing feature, the fix rides through the library's own owner (I route it there — you
don't chase it), and your project simply picks up the new pinned version. And if a shared piece grows big
enough to stand on its own, we register it as its own first-class project rather than letting it sprawl
inside yours.

-> You say: "this looks like shared code" or "that belongs to another library" — I route the fix the right way.

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [L] Signalling a fix to the kernel
*Seam: `kernel signal` — the first time the YITC machinery itself is at fault (no verb; AI-recognized).*

Sometimes what's wrong isn't your project — it's YITC itself, the shared machinery all the projects run
on. When I hit such a bug or gap, I mark it as belonging to the kernel (the core system), and at land — the
moment we merge finished work — it is sent to the kernel's own queue automatically, with no reminder needed
from you. One line to hold: a bug fix routes itself; a request for a NEW kernel feature I still bring to you
first, because that is a real decision. This is different from ordinary cross-project coordination (station
J) — here the target is the tool we all work on.

-> You say: nothing needed — just know "the tool itself is broken" gets routed on its own; I'll flag it when it happens.

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [M] Parallel sessions
*Seam: `parallel sessions` — a foreign-worktree block or a several-at-once note (no verb; AI-recognized).*

On a bigger project we don't have to work in a single conversation. Several sessions can run at once — this
one with you, plus background ones — each holding its own piece: a different plan, a different part of the
logic, its own set of tasks. They don't collide because each does its edits in a separate working copy (a
worktree — an isolated branch), and no two sessions can claim the same task at the same time. So parallel
work speeds things up without stepping on itself; you don't manage the split — I coordinate it.

-> You say: "can we run this part in parallel?" — I set up the separate sessions and keep them clear of each other.

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [N] Driving the plan to the end
*Seam: `drive to the end` — the owner hands over a plan/batch to run autonomously (no verb; AI-recognized).*

When a plan or a batch of tasks is already agreed, you can tell me "run it to the end yourself" (веди сам до
конца). Then I move from step to step on my own — I don't stop to ask between stages that carry no real
decision for you. If one task raises a genuine question, I set just that one aside (park it) and keep the
rest moving, instead of freezing everything. I stop only for a real decision that's yours to make, or when
the session is getting full — and then I hand off cleanly, losing nothing.

-> You say: "веди сам до конца" / "run it to the end" — and I drive it, surfacing only what truly needs you.

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [O] Plan trial and postcheck
*Seam: `plan trial` — the trial / postcheck fork surfaces while running plan stages (no verb; AI-recognized).*

For plans that build a new mechanism, we can prove them on real data before trusting them, not just on
paper. Two moments: a trial — before we lock the plan in, we let the design soak against real data to see
it actually holds together (you ask for this; it is for mechanism plans, not every plan); and a postcheck —
after the work is built, one more real-data soak before we call it truly done. Both catch "looked right,
behaved wrong" early. You don't run either — you just say when a plan feels risky enough to want one.

-> You say: "let's trial this first" or "run a postcheck before we call it done".

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [P] Session refresh and context
*Seam: `session refresh` — the context threshold, or the owner's refresh cue (no verb; AI-recognized).*

A conversation has a limited working memory (its context); as it fills, I get less sharp. When it nears the
limit I'll propose it myself: "let's refresh the session" — I write a clean hand-off and we continue in a
fresh one, losing nothing. It is not a goal in itself: you can also refresh earlier at any clean stopping
point, or say "not yet" and keep going — your call. You can trigger it anytime with the cue "обновим сессию"
("refresh the session"). And if you'd like, the tool can show a permanent context-usage indicator right in
its status line, so you always see how full we are — just ask me once to set it up.

-> You say: "обновим сессию" / "refresh the session", or "set up the context indicator".

(unclear or hard — say "explain it simpler"; no need to get stuck)

---

## [Q] Dictating a list of wishes
*Seam: `dictated list` — the owner dumps a raw list of wishes/constraints (no verb; AI-recognized).*

You don't have to hand me things one neat item at a time. Dump a raw list — wishes, constraints,
half-formed ideas, all at once. I take it from there: I check each item makes sense (its premise holds),
turn them into concrete tasks or a plan, and show you ONE checkpoint to confirm the shape — then I set the
work going (dispatch it to background workers). Nothing on your list is dropped or forgotten; the messy
list becomes organized work without you sorting it.

-> You say: just list everything you want, however rough — I'll organize it and show you one checkpoint.

(unclear or hard — say "explain it simpler"; no need to get stuck)
