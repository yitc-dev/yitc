---
name: compute-controller-session
class: discipline
sourced_from: SPEC-0203 rules 6+7 (box lifecycle + one executor), authored by under the plan [[remote-verify-venue-kernel-verify-passes-on-an-own]]. The measured numbers it quotes are (`dev-utilities/remote-verify-experiment-.md`) and the provider costs of the seed recipe — none is restated as a rule here.
applies_to: the ORDINARY owner-started Controller session that OWNS the machine's verify venue for the length of one compute window — raise, publish, watch, delete. It is a POSTURE of the one interactive Controller (CHARTER §6), never a third session type and never a daemon. The verbs are `venue raise|publish|unpublish|delete` (SPEC-0203 rule 6, `bin/lib/venue.py`); the watching is done through the EXISTING views (`bin/yitc-v2 debt` SPEC-0119, `dispatch --watch` SPEC-0133) — this pattern adds no view, no verb and no store.
cites:
  - SPEC-0203
  - SPEC-0105
  - SPEC-0119
---

# The compute-controller session — one cue up, one condition down

> **What this is, plainly.** The owner opens one extra chat window and says «поднимай вычисления».
> That window's whole job is the compute box: rent it, check it, announce it, watch the work that
> now runs on it, and give it back when nothing is left running. It does no thinking work of its
> own. Everything else — the tasks, the workers, the lands — happens in the other sessions exactly
> as before.

## §Problem

A rented compute box is billed by the started hour and the provider project holds exactly ONE box of
its class (`ccx63`). So the box has a real lifetime that somebody must own: raised at the start of a
work window, given back at its end. Two failure shapes bound the design:

- **Nobody owns it** → the box is raised for one land and then forgotten, billing whole hours over a
  night nobody was working. This is the expensive failure and it is silent.
- **Something automated owns it** → a daemon that watches the queue and raises/deletes on its own is
  precisely the stateful orchestrator CHARTER §6 names among its retirements. It would also be a
  second thing deciding when work runs.

The resolution is neither: an ORDINARY interactive Controller session owns the box, started by the
owner and authorized by the owner, whose standing batch is the land seam. That is the same shape
`dispatch --watch` already has — a session watching durable state across seams inside one
owner-authorized batch — and it is inside the fence for the same reason: the owner started it, the
owner authorized it, and it selects nothing.

## §Solution

### 1. One cue up

The owner says it once — «поднимай вычисления» / "raise the compute". That single cue authorizes the
whole window; there is no per-step confirmation afterwards, and no cue means no box.

```
bin/yitc-v2 venue raise # create from the SNAPSHOT, wait for ssh, run the readiness probe
bin/yitc-v2 venue publish # write the machine-scoped record — refused if the probe failed
```

**List before you raise.** The provider project holds ONE box of this class, so `venue raise`
refuses a quota error by naming the order — snapshot → delete → raise — rather than retrying into
the limit. Before raising, look at what is already live (`venue.list_servers`, the labelled read).
**A box you did not raise is not yours to delete.** The label `purpose=remote-verify-venue` narrows
the list; it does not license a delete. If a foreign box holds the quota, that is an owner question,
not a box to remove.

**Raise from the snapshot, never from a bare image.** The snapshot carries the seeded bare clone. A
bare-image raise re-pays the first push into an empty clone — measured at ~45 min for the engine —
on EVERY raise; from the snapshot a raise is ~1 min. The bare image is for seeding only.

**Publish is gated on the readiness probe, and that gate is the point.** An unpublished box costs
money and changes nothing; a published one becomes the executor of every kernel verify pass on this
machine (SPEC-0203 rule 2). Publishing a box whose environment was never measured would put a
verdict authority behind an unchecked host.

### 2. No accounts on the box — compute there, thinking here

The box runs test suites. It holds no provider account, no session, no credential beyond the ssh
identity that reaches it, and nothing is authored on it. Every judgement — what a verdict means,
what to fix, what to file — happens in the sessions on this machine. Concretely: do not log into the
box to "have a look and fix something"; a box that needs a fix is a fix CARD (§4), because the box
is disposable and a card is not.

### 3. Watch through the views that already exist

While the venue is published, the compute-controller session is a READER. It watches the passes now
running remotely through the EXISTING surfaces, and adds none:

- **`bin/yitc-v2 debt`** — the derived debt echo (SPEC-0119). It is where a land that queued, a
  land that died, and a stalled dispatch already surface, suppressed when clean.
- **`bin/yitc-v2 dispatch --watch`** — the blessed watcher for dispatched workers
  (`patterns/background-session-monitoring.md §Watcher`), token-keyed, whose recovery is read off
  the journal rather than off a wrapper's process lifetime.

There is deliberately no venue dashboard, no venue view verb and no venue watch loop. A venue fault
does not need its own reader: rule 4's abort classes name it in the land's own output and on the
journal, which the two views above already fold.

### 4. A venue fault is a CARD, not a workaround

While a venue is published there is ONE executor (SPEC-0203 rule 7): a faulting venue is an
INDETERMINATE abort, not a silent fall-back to local. The compute-controller session resolves it one
of exactly two ways:

- **Fix it** — and file (or take) the card for whatever made it fault, so the next window does not
  re-discover it.
- **Break the glass** — `bin/yitc-v2 venue unpublish`. The record is removed, journaled whole, and
  every pass runs locally again exactly as before the venue existed.

What it never does is edit a gate, weaken a check, or half-publish a box to get one land through.
The break-glass is the sanctioned exit and it is one command.

### 5. One condition down — and why the buffer is 15 minutes

The delete condition is a READ of durable state, not a queue and not a timer a daemon holds: **no
task is `in-progress` in ANY repo on this machine** — the task cards across the registry's v2
projects, plus the live worktree list, because a claim lives only inside its worktree until it lands
— **for the idle buffer** (a machine-scoped `config` tunable, default 15 minutes).

```
bin/yitc-v2 venue unpublish # remove the record FIRST — journaled WHOLE, server_id included
bin/yitc-v2 venue delete # destroy the box + its key
```

The buffer is a COST shape, not a safety margin. A started hour is billed whole, and a re-raise from
the snapshot costs about a minute. So deleting too eagerly costs a minute and re-bills nothing
inside the hour already paid for; holding a box "just in case" across a quiet night costs whole
hours. Fifteen minutes is the pause after which a work window has plainly ended rather than paused
for coffee.

**Unpublish precedes delete, always.** `venue_unpublished` carries the whole record, `server_id`
included, and is emitted BEFORE the file is removed — so if the provider DELETE then fails, the
append-only journal is the tombstone the delete can be finished from
(`venue delete --server-id <id>`). Delete-then-unpublish would put a live billed box beyond the only
place its id was written.

### 6. The night belt — one report, not a watcher

A session can be closed with the box still up. The nightly (SPEC-0105) therefore carries ONE
report-only check: a published venue with nothing in-progress past the buffer, or a live box with no
publication record, is reported as a FORGOTTEN BOX — one line, suppressed when clean, never a fix
and never a delete. So a box can be forgotten for at most one night. The nightly reports; the
deleting stays this session's, on the owner's cue.

## §Example

A real window, end to end:

1. Owner: «поднимай вычисления». → `venue raise` (~1 min from the snapshot) → the readiness probe
   passes → `venue publish`. The record now names the box, its fingerprint, and this session's ref.
2. Other sessions dispatch and land as usual. Nothing about their verbs changes; their land verify
   now runs both legs in parallel on the box (~3 min against ~22 min locally, measured).
3. This session watches `debt` and `dispatch --watch`. A land aborts `venue-indeterminate`; the box
   is reachable but its clone is behind. The session fixes the box and files the card for why the
   push was skipped.
4. The last worker lands. Fifteen minutes later the task cards and the worktree list agree that
   nothing is in progress on this machine. → `venue unpublish` → `venue delete`. The next kernel
   pass runs locally, byte-identically to before.

## §Anti-pattern

- **A daemon, a poll loop, or a cron that raises/deletes the box.** That is the stateful
  orchestrator CHARTER §6 retires, and it would make an automation decide when compute exists.
  The condition is read by a session the owner started; the only automated thing is the nightly's
  report.
- **A second posture.** "The compute-controller" is a JOB a Controller session does for a window,
  not a session type, not a `--type`, and not a permission class. It holds the same gates every
  session holds.
- **A venue view / venue watch / venue status verb.** The debt echo and `dispatch --watch` already
  read what a venue fault produces; adding a third reader would be a parallel path to the same
  journal (CHARTER §P5).
- **Deleting a box you did not raise.** The label is a filter, not a title deed.
- **Raising from a bare image because the snapshot id was inconvenient to find.** It converts a
  one-minute raise into a three-quarter-hour one, every time.
- **Logging into the box to author or fix something durable.** The box is disposable; anything
  worth keeping belongs in a card, in this repo.
- **Leaving a box published while its executor is broken.** One executor means a faulting venue
  blocks; the sanctioned exit is `venue unpublish`, immediately, not a hand-forced local run.

## §Cites

- **SPEC-0203** — the venue spec; rule 6 owns the box lifecycle (raise → probe → publish → the idle
  delete condition + the buffer) and rule 7 owns one-executor / the unpublish break-glass. Every
  normative sentence about the venue lives there; this pattern is the operator recipe.
- **SPEC-0105** — the nightly runner that carries the report-only forgotten-box check (§6).
- **SPEC-0119** — the proactive-debt echo, one of the two existing views this session watches.
- `patterns/background-session-monitoring.md` §Watcher — the `dispatch --watch` shape this session
  mirrors, and the "key recovery off the journal" discipline it inherits.
- CHARTER §6 — the one interactive Controller + the named retirements this posture stays inside.
