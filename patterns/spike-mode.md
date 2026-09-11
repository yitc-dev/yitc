---
name: spike-mode
class: discipline
sourced_from: SPEC-0172 (spike-sandbox wiring contract) + SPEC-0175 (spike-sandbox data floor — the live-system axis, the actor split and the three strands §The safety floor teaches; incidents X-0798/X-0799) + its three-cycle trial at the pilot consumer (plan `rework-kit-in-the-kernel-spike-mode-as-a-methodolo`, cycle-3 clean 2026-08-09, claim NARROWED by owner ruling the same day) + the pilot's two cage CORRECTIONS (prose cage that had to be fixed twice) + incident X-0628 (sandbox entrance died on a stale router address, 2026-08-08) + two adopted shapes carried over from a consumer's own runs (live-code spike layer, on-screen environment marker — originating cards //, wanted independently by a second project at X-1004; shape only, no runtime code and no project named — SPEC-0073/SPEC-0090)
applies_to: you are about to open a THROWAWAY debugging exploration against a sandbox stack — reproducing a bug, measuring a behaviour, trying an approach — and you want the run to be caged and its exit to be knowledge. Read this INSTEAD of re-deriving the rules; you should not need to open SPEC-0172 to make a run. NOT for delivering a change (that is the ordinary Build lifecycle) and NOT for an emergency by-hand fallback (`patterns/emergency-mode.md`).
---

# Spike Mode — running a caged throwaway spike, end to end

> **Discipline pattern.** A spike is a **disposable exploration whose exit is knowledge, never
> landed code**. This doc is the RUNBOOK: read it and run one. The normative rule text lives in
> **SPEC-0172** (the STACK's wiring) and **SPEC-0175** (the DATA the copy carries); you should not
> have to open either to make a run, and if you did, that is a defect in this doc — say so
> (`bin/yitc-v2 event deviation_captured …`). Both are cited, never restated: where a wording here
> and a spec disagree, the spec wins.
>
> **This doc travels** (SPEC-0090): it is general methodology, so it names no project's paths,
> container names or instrument names. Where your project's specifics matter, they are read from
> YOUR `yitc-ops.yaml` declaration (§0) or belong in your own `lessons/` note — never here.

## §Problem

Two failures repeat whenever a debugging sandbox is opened without a mode around it.

**The cage is prose.** Somebody writes down "the spike stack must not touch production, must not
run the scheduler, must not send anything outbound" — and the rules hold exactly as long as
everyone remembers them. The pilot project shipped a prose cage and then had to CORRECT it twice.
**Prose describing a cage does not constitute a cage** (SPEC-0172 rule 4).

**The spike leaks into delivery.** The exploration produces a diff that is "nearly right", and the
diff becomes the delivery mechanism: it is landed, or tasks get filed from inside the loop, before
the owner has judged any of it. A disposable exploration has then converted itself into committed
work, which is what the mode exists to prevent.

A third failure is environmental and costs an hour every time it is met cold: the sandbox entrance
dies while every container reports healthy (§4).

## §Solution

### The safety floor — read this before the steps

**The axis is the LIVE SYSTEM — not "production data".** A static copy DERIVED from production is
the **sanctioned** data source of a spike sandbox; holding real data is the reason a spike sandbox is
worth having at all. What is forbidden is the spike RUNTIME touching the live production system, and
what is unsafe is working in a copy that still carries live values. The rules are **SPEC-0175** —
`bin/yitc-v2 graph query SPEC-0175`. This section is their RUNBOOK, not a second copy of their
authority; on any conflict the spec wins, and if you had to open it to make a run, that is a defect
here — capture it.

**Two obligations SPEC-0175 rule 2 puts on you — the ACTOR SPLIT. Both must be held, and neither half
follows from the other, so neither may be left to inference (the rule says so; this is where you read
it, not where it lives):**

- **The named refresh/export STEP MAY read live production, READ-ONLY**, for the sole purpose of
  producing a static copy. It writes nothing there and changes nothing there, and it is the ONLY
  actor holding this permission. So: **making the copy is permitted** — you are not smuggling
  anything, and you do not need to invent a way around the restore.
- **The spike RUNTIME NEVER connects to the live production system.** No process inside the spike
  stack is pointed at it, tunnelled to it, reading from it, or writing to it. This is the half with
  no exception and no per-run argument.

**A restored copy is not made safe by living in a sandbox.** It arrives carrying webhook URLs that
still route, tokens that still authenticate, people's addresses that are harmful the moment they are
read, and outbox rows that will send the moment a worker starts. So it is TREATED before the stack is
usable — on **three strands, each with its OWN verbs** (SPEC-0175 rule 3), and a strand answered with
another strand's verb is **not answered**:

- **REACHABILITY** — values that can route, authenticate, identify, schedule or trigger (incl.
  external resource IDs and object keys). Verb: **NEUTRALIZE**.
- **DISCLOSURE** — content harmful merely by being READ: personal, financial, regulated. Verbs:
  **MASK / MINIMIZE / EXCLUDE**, or explicitly **ACCEPT** under a recorded acceptance.
- **OPERATIONAL STATE** — state that DOES WORK when anything consumes it: outbox rows, queued jobs,
  scheduler entries, and executable schema (triggers, procedures, subscriptions). Verb: **DEFUSE**.

Two things this list is routinely misread on. **"Neutralize" is the REACHABILITY verb, not the
universal word for "handled"** — neutralizing a webhook URL does nothing about a person's address, and
no length of neutralize-list ever will. And **classification is MANY-TO-MANY**: one surface commonly
sits in two strands or all three (a customer email address is DISCLOSURE *and* REACHABILITY), and
every applicable strand must be treated and proven for it.

The obligation starts at the **first exported byte**, not at the restore: the dump, its temp files,
staging and backup copies, the step outputs, and the restored database are all untreated
production-derived artifacts, and the chain outside the sandbox is DESTROYED rather than left lying.
Which of YOUR surfaces carry which class is your project's own declaration — `spike_data_safety:` in
your `yitc-ops.yaml`, the sibling of §0's `spike_sandbox:` — and the treatment is proven by QUERYING
the copy, with a control per detector. Read SPEC-0175 rules 4-6 before you build a probe; do not
re-derive them from this paragraph.

Stated with the two-word vocabulary this doc uses everywhere, so you know exactly how much of the
floor stands on a machine and how much stands on you:

- **CHECKED — the stack-identity half.** A spike stack must be wholly its own (§2 atom 4a): a cage
  DECLARED sharing production's compose project, any of its ports, or any of its volumes is refused,
  and a declaration that is missing or mal-shaped is refused fail-closed rather than read as absence.
- **DISCIPLINE — the runtime's reach, and everything about what the copy CARRIES.** Atom 4a is a
  predicate over a stack's declared IDENTITY. It says nothing about what a process INSIDE that stack
  dials: point a config, a connection string or a tunnel at live production and nothing in §2 refuses
  you. Nothing refuses an untreated copy either — the data floor names the layer that owes each check
  and is honest where that layer does not carry it yet (SPEC-0175 rule 8). **You are the check** on
  both, and this is the half the floor above is asking you to hold.

Do not read the CHECKED half as covering the DISCIPLINE half. They are different claims, and the gap
between them is exactly where a careful reader talks themselves into "well, it is only a read". The
floor is: **the runtime never contacts the live system, and the copy is treated on all three strands
before the stack is usable.** Where a step below says a spike is "mutating", it means **it writes the
SANDBOX copy's data** — that word is never a licence to write the live system's.

### The steps

Six steps. Run them in order; each names what you can RELY on (a machine check refuses the
violation) and what is DISCIPLINE (recorded and taught, nothing refuses it).

**FIRST, a fork — does your spike raise a STACK AT ALL?** Not every spike does. A spike that only
READS — source, a log dump, a captured trace, a schema, a metrics export — raises nothing, and most
of this runbook is then about a thing you do not have:

- **NO-STACK, read-only spike:** steps **2, 3 and 4 DO NOT ARISE**. There is no stack, so there is
  no cage to declare (§2), no shared-or-own sandbox question to answer (§3 — you are not taking a
  sandbox at all), and no entrance to repair (§4). §0's declaration is likewise not your concern for
  this run: you are not bringing a bridge up. What DOES apply, unchanged: **§1** (open the worktree
  with the `spike-` prefix), **§5** (discard it; carry findings on the transfer list, file no tasks
  from inside the loop) and **§6** (record the run — say `stack=none` and name the sources you
  opened). That is the whole run: §1 → work → §5 → §6.
- **STACK spike:** all six steps, in order, as written below.

**What "only READS" means on the floor's axis, because this is where the old wording used to trip
people.** Those sources are production-DERIVED artifacts, and reading one is not the forbidden thing
— the forbidden thing is your spike dialling the LIVE system for it (§The safety floor). Two
consequences worth holding: a "read-only" spike that reaches into live production to fetch its trace
is not a no-stack read, it is the runtime prohibition being broken without a stack; and a raw,
untreated production-derived artifact (a dump, an unredacted log) is governed by SPEC-0175 rule 4
whether or not you raised a stack to open it — same treatment, same emission limits, same destruction
obligation.

If you are unsure which you are, you are a STACK spike the moment you bring anything up — decide
before you start rather than discovering it mid-run.

**Read the status word in each step literally.** CHECKED means something refuses the violating
input. DISCIPLINE means nothing does — you are the check. There is no third, softer word, and a
DISCIPLINE step must never be read as prevention (SPEC-0172 rule 4 C3 + its interpretation note).

### 0. Before the first spike — declare the sandbox wiring ONCE

Your project answers the bridge question in its `yitc-ops.yaml`, in the `spike_sandbox:` section.

**Where that section is, exactly — because "in your `yitc-ops.yaml`" is not an address in a file that
runs well over a thousand lines.** `spike_sandbox:` is a **TOP-LEVEL key**: it sits at column 0, not
nested under `extensions:` or under any other section. It is **GENERATED, and born-present in EVERY
project's carrier** — so it IS there to be found, and finding nothing means you have not found it
yet, not that your project skipped it. It is one of the LAST sections in the file (born sections are
emitted in a fixed order and this one is near the end), which is why scrolling from the top is the
slow way in. Go straight at it:

```
grep -n '^spike_sandbox:' yitc-ops.yaml
```

**Then read which of the TWO shapes you landed on, because both are real answers** (§declare-or-waive
below). A project that HAS a bridge carries the declaration:

```yaml
spike_sandbox:
  bridge:
    pin: <exact release ref of the shared bridge library this project runs>
    enabled: true
    cage_checks: <where the machine-checked cage rules live — something that RUNS>
```

A project that has NO bridge carries the born waiver, and that is a complete answer, not a blank:

```yaml
spike_sandbox:
  waiver:
    reason: >-
      no spike sandbox yet — this project runs no pinned bridge and keeps no caged spike stack.
```

If you found a `waiver:`, your pointer RESOLVED: this project has told you it runs no bridge. That is
a different situation from a missing section, and it is the answer to your question — you are not
looking at an incomplete file.

Three things about the declared block, all load-bearing:

- **DECLARE-OR-WAIVE, not opt-in.** Every project must ANSWER. A project with no spike bridge
  writes the waiver the born template ships with — one line, a legitimate answer. Answering
  NEITHER is debt and surfaces as such on the generated sweep.
- **`pin:` is a RELEASE REF, never a local copy.** A surviving local copy of a neutral bridge
  module is a violation, not an optimisation. A fix you need goes UPSTREAM to the library and you
  re-pin; it is never patched in place (SPEC-0172 rule 3).
- **`enabled:` is the switch, not the permission.** An outbound channel inside a spike stack still
  needs its own explicit per-case owner grant (§2, atom 4c).

You do not hand-write this section or invent its schema — it is generated from one declaration.
If it is missing from your carrier, run your project's `init` re-seed rather than typing it in.

### 1. Open the spike worktree

```
bin/yitc-v2 worktree new --work spike-<slug>
```

The `spike-` prefix is not cosmetic and not a convention you may vary: it is the literal token two
mechanisms read — the report-only spike-mode hint, and the land refusal in §5. A worktree named
anything else is not in spike mode, whatever you intended.

Creating it prints a report-only hint that a spike loop is live. It never blocks anything.

### 2. Bring the stack up inside the cage — four atoms, all four CHECKED

The cage is **four ATOMIC rules, not one clause**. Each is a refusal condition paired with a
positive control, because a check that refuses everything satisfies the refusal half perfectly and
is useless.

| Atom | REFUSED | PERMITTED | Status |
|---|---|---|---|
| **4a — isolated stack identity** | a spike stack sharing production's stack identity: its compose project, any port, or any volume | a stack whose identity is wholly its own | **CHECKED** |
| **4b — the scheduler is not started** | a spike stack with the scheduler started | a stack with no scheduler started | **CHECKED** |
| **4c — outbound channels dummy by default** | an outbound channel live without an explicit per-case owner grant | channels dummy by default; a channel live under its complete grant | **CHECKED** |
| **4d — the grant is recorded BEFORE the channel changes** | a channel enabled ahead of its record — a window in which it is live and unrecorded | the record written first, then the change | **CHECKED** |

**All four are CHECKED, but not at the same LAYER, and the layer is what tells you what the check
can.** 4a/4b/4c are checked at KERNEL + PROJECT, over your DECLARATION: a cage DECLARED in
violation of one of these atoms is refused, and a declaration that is missing, mal-shaped or
incomplete is refused fail-closed rather than read as absence. That says nothing about a running
stack whose declaration LIES — that refusal is your project's own layer, and it is what your
`cage_checks:` pointer must point at. All three were positively observed on a real caged stack
during the trial, with the positive control run FIRST so the refusals mean something.

**4d is CHECKED at LIBRARY MECHANICS — the pinned bridge library enforces the ordering, not the
kernel.** Do the thing anyway, in this order: when you enable a channel, WRITE THE RECORD FIRST,
then make the change. The failure it guards is asymmetric (a record without a change is harmless; a
change without a record is a live unrecorded channel), and the mechanic now matches: the grant
record is written BEFORE the compose rewrite, and a FAILED record aborts the toggle with zero
container mutation — so the window the rule names cannot open. Anchor you can check:
`cross:X-0757` content (b) — run `bin/yitc-v2 cross show X-0757` (SPEC-0172 rule 4e, row 4d).

**Why this row reads differently from older copies of this runbook, because the change is
instructive.** The trial did NOT converge 4d: the instrument measured there recorded the grant AFTER
rewriting the compose override and recreating the containers, so a real window existed, and this doc
carried 4d as DISCIPLINE for exactly as long as that was true. The pinned library then built the
mechanic and reported it through the shared log, and the row was re-marked against it. The status
word moved because the WORLD moved — not because the rule softened, and not because the wording was
tidied up.

**What CHECKED does NOT buy you here — and read the layer name literally, because it is not the
word you probably expect.** LIBRARY MECHANICS is one of SPEC-0172 rule 1's three LAYER names
(kernel · library mechanics · project); it names *the layer that owes the check*, and it does **not**
promise the check ships inside the pinned bridge release. Measured on the ground this row is anchored
to: the pinned release carried NEITHER this ordering mechanic NOR §3's sharing predicate — both live
in that project's OWN spike instruments, built there when the row was closed. So **the pin does not
carry these refusals to you.** Before you rely on 4d, look in your own toolchain for the thing that
refuses a channel flipped ahead of its record; if nothing does, you are holding the ordering
yourself, whatever this row says about somebody else's ground.

### 3. Decide the sandbox: shared or your own

**Read-only spikes MAY share one sandbox. A spike that MUTATES data gets its own.** The
distinction is the MUTATION, not the topic — two spikes on completely different subjects may share
a sandbox if neither writes, and two spikes on the same subject may not if either does.

**Status: CHECKED at LIBRARY MECHANICS, and the check keys on your DECLARATION.** A spike that
DECLARES it mutates is REFUSED a shared sandbox; two read-only spikes sharing one sandbox come up.
Anchor: `cross:X-0757` content (a) — `bin/yitc-v2 cross show X-0757` (SPEC-0172 rule 6).

**But know the condition the refusal keys on, or you will trust it in the case where it stays
silent.** The measured predicate refuses when your target is the DEFAULT stack name **and** the
ground carries **two or more live spike worktrees** — co-occupancy by construction, since concurrent
spikes that never set the knob all land on the same literal. With ONE spike worktree open — the
ordinary state, and the one you are most likely in — a spike declaring `mutating: yes` on the default
stack is **not refused**, because nobody else is in there to protect. That is defensible as a
predicate and dangerous as a habit: the second spike opens without asking your permission, and the
refusal you were relying on was never what stopped you writing. On that stretch **you are the
check** — take your own sandbox because you write, not because something objected.

**Why this reads differently from older copies, and what the history still teaches.** The trial
enumerated the full input surface of every spike instrument on the trial ground — flags and env
knobs both — and found that NONE could express read-only-vs-mutating and NONE could express
shared-vs-own-stack; the only stack knob named WHICH stack, never whether sharing it was permitted.
The toolchain could not state the predicate, so there was nothing for a violating input to hit, and
this rule was DISCIPLINE for as long as that held. The mechanics layer then gave the toolchain the
word — which is why the declaration below is now an INPUT to a refusal rather than only a note to
your future self. **Where that word lives is your project's own instruments, not the pinned release**
(the same reading §2's 4d paragraph spells out): on the ground this row is anchored to, the pin
carried neither predicate. Pinning the bridge does not import this refusal.

**So the declaration is the load-bearing part.** A check that keys on what you declared cannot save
you from a declaration that LIES: say `mutating: no` and write anyway, and nothing refuses you. Decide
mutating-or-not BEFORE you bring a stack up, say which you chose in your run record (§6), and take
your own sandbox the moment the answer is "it writes" — **on that half, you are still the check.**

**DECLARE mutating-or-not BEFORE the stack comes up — the same ordering §2 puts on a channel.** The
answer is not something you report on the way out; it is something you WRITE DOWN FIRST, in the same
place your run record will live (§6), and only then do you bring anything up. §6 is where you
CONFIRM the declaration you already made — never the first time it is mentioned. Same shape as atom
4d, and for the same reason: **the failure is asymmetric.** (Same shape, and now the same
disposition — both orderings are enforced at the library layer, and both are still yours to get
right in the moment the tooling hands you the choice.) A declaration with no mutation behind it
costs nothing and is thrown away with the spike; a mutation with no declaration in front of it is an
undeclared writer inside a sandbox somebody else may already be reading — and it is undeclared for
exactly the window in which the damage happens. Write it first and the window does not exist.

Concretely, before step 2: write `mutating: yes|no` and the sandbox you intend to take. If the
answer is `yes`, that same line is what commits you to your OWN sandbox — decide it here, where it
is cheap, rather than at the moment you are about to write.

### 4. When the entrance dies but everything reads healthy

**The property, stated plainly: RECREATING THE BACKEND INVALIDATES THE ROUTER'S CACHED ADDRESS.**
The sandbox router resolves its backend by container NAME and caches the address at config load,
so the FIRST time the backend container is recreated the entrance is dead while every container
reports HEALTHY — the app still serves 200 and only the API path 502s. The symptom points at the
application; the cause is one hop away. This is a property of the RECIPE, not of any one project:
every project building the same sandbox inherits it (source of record: incident X-0628,
2026-08-08).

**What to do: the NARROW repair — restart the ROUTER ALONE, no data path touched.** That is the
blessed exit. It is NOT the destructive full refresh, which also re-restores the sandbox database
and throws away the state you were mid-spike on. **And note what a re-restore costs beyond that
state: it brings in a fresh untreated production-derived copy, so the whole data floor re-arises —
treat all three strands and re-run the proof before the stack is usable again** (§The safety floor;
SPEC-0175). A refresh taken as a reflex for a dead router is how an untreated copy gets in through a
door nobody was watching.

**Read this honestly, because two things are true at once.** The narrow repair is the RIGHT move;
and at the kernel layer it is a stated REQUIREMENT on the mechanics layer, not yet a shipped
instrument everywhere (SPEC-0172 rule 8a: `narrow_entrance_repair` and `stale_upstream_check` are
both status **REQUIRED**, owed by LIBRARY MECHANICS). So if your toolchain has no narrow door, the
honest reading is that your implementation is OUT OF CONTRACT against a stated requirement — file
that, and do not take the destructive refresh just because it is the only blessed one. The
original reporter of X-0628 ran a hand container command instead: outside every verb, and so
unjournalled and unrepeatable. **A missing narrow door does not make operators wait; it makes them
leave.** Two related traps:

- Health asserted at the BACKEND's own port answers perfectly while the hop is dead. Probe
  entrance health THROUGH the router (200 vs 502) or you have not tested the entrance.
- This changes NO cage rule. Nothing in §2 is relaxed by an entrance repair.

### 5. Exit — the spike is DISCARDED, and knowledge is what crosses back

**Status: CHECKED, at the kernel layer.** `land` REFUSES a spike-named branch, proven against a
control branch differing only in the name. You cannot land a spike by forgetting not to.

```
bin/yitc-v2 worktree park --work spike-<slug>
# carrying uncommitted spike dirt (the normal case — sandbox editing IS the practice):
bin/yitc-v2 worktree park --work spike-<slug> --force --reason "<why this spike is disposable>"
```

What crosses back is a **TRANSFER LIST of findings, merged as ONE batch at the owner's ok-moment**.
The diff is a cross-check on that list, never the delivery mechanism — you carry the FINDINGS by
hand into the owner-approved batch, not the branch.

**Do not file tasks from inside the spike loop.** That is out of contract for the same reason
landing is: it converts a disposable exploration into committed work before the owner has judged
it. Tasks belong to the transfer moment.

**One standing caution, do not read past it:** CHECKED here is a claim about the kernel's EXIT PATH
only. It says nothing about your project's own cage (§2's layer), and it does not prevent an
escalation-capable actor from stepping around the refusal. That limit is discipline.

### 6. Record the run

Two lines in the journal, and they cost nothing:

- Which sandbox you took and **whether the spike was read-only or mutating** — this CONFIRMS the
  declaration you wrote before the stack came up (§3), it does not make it for the first time. A
  no-stack spike writes `stack=none` here and is done with the question.
- **Which sources you actually opened to make the run.** If you had to read SPEC-0172, ask the
  author, or reverse-engineer an instrument, this doc did not do its job — that is the differential
  this pattern is measured on, and a friction capture is the right response, not a silent
  workaround.

The journal means the EXISTING lifecycle journal. A spike-specific journal, ledger or evidence
store is forbidden; if one appears to be needed, escalate that as a dissonance (CHARTER §Principle
7) rather than adding it.

### Two shapes worth adopting — and NOT worth re-deriving

**Why they are here.** Neither is a rule you must obey; each is a shape you may ADOPT, and each was
independently wanted by a second project an hour before it started rebuilding it from scratch
(X-1004). Both are recorded with the LOAD-BEARING property first and the recipe second, because in
both cases the recipe is the easy half and the property is the half a re-derivation gets wrong.

*Provenance (shape, not code).* Both were built and RUN at a consumer project before they were
written down here — the live-code layer as a `spike-dev` wrapper script plus a `spike-dev` compose
overlay (cards ****, where the inode trap was caught on the first probe, and ****, where
the reload-uniformity trap was), the marker as an `environment` settings field plus one header badge
component (card ****). The originating repo is deliberately NOT named: a pattern travels and
therefore names no project (SPEC-0090), and the ids above plus cross-row **X-1004** resolve to it for
anyone who needs the working artifacts. What travels here is the PROPERTY and the shape.
The runtime lives in the project (SPEC-0073): this doc copies no compose body, no settings class and
no component source, and yours will not look like theirs.

**Shape 1 — the live-code layer over the spike stack.** A spike that rebuilds an image per edit is a
spike nobody runs twice. The fix is a LAST-overlaid compose layer that bind-mounts the source tree
and turns on the framework's reloader, composed only ever through a wrapper script.

- **The load-bearing half is the WRAPPER, not the mount.** The wrapper refuses any target that is
  not a throwaway spike worktree, so the layer has NO ROUTE into a production compose invocation.
  A mount file that any operator can overlay by hand is a different, worse artifact wearing the same
  name. State the boundary in the layer's own header, in one sentence: *a live-mounted source tree
  is a development convenience; production delivery stays image-only.*
- **Mount the whole DIRECTORY, never a single file.** A single-file bind mount keeps serving the OLD
  inode after an editor or `sed` rewrites the file by rename — the container reads a file that no
  longer exists, forever, while the tree on disk is correct. This is the trap a re-derivation ships:
  it costs nothing to avoid up front and reads as "the mount does not work" afterwards.
- **Live-code is NOT uniform across the cage, and say which services reload.** A reloading web
  process picks edits up in seconds; a queue worker reads the mounted task code ONCE at process
  start and never again. So an edit to worker code keeps running the OLD version and the symptom
  reads as *"the fix did not work"* — sending the operator to debug a fix that was never loaded.
  Print the non-reloading services and their restart command at the END of the wrapper's output,
  where the operator will be when it bites.

**Shape 2 — the on-screen environment marker.** A settings field defaulting to production, surfaced
read-only to the UI, where the default renders NOTHING; a sandbox sets it and an amber badge appears
in the header. Carries no behaviour — it is a label, and it must stay one.

- **The load-bearing half is the DIRECTION, and it is one-way.** Production DECLARES NOTHING and an
  unset variable MEANS production; the sandbox is what declares itself. That direction fails CLOSED:
  a production deploy cannot accidentally render a marker, because rendering one requires an
  affirmative declaration nobody made. **The inverse — production declaring itself in order to
  SUPPRESS a badge — fails OPEN:** the day that variable is missing, misspelled or dropped by a
  deploy, production quietly shows a sandbox badge, or worse, sandbox quietly shows none. Both
  directions produce a working screenshot on the day they are built, which is why picking is a
  coin-flip for anyone deriving it fresh, and why the direction is written down here.
- **Keep it to ONE guard.** One place decides "not production → render", and the badge plus any
  sandbox-only affordances hang off that single condition. Two guards is how one of them gets
  forgotten and a sandbox-only link ships to production.
- **Why the door is not enough** — the reason this shape exists at all. Both projects already
  distinguish the sandbox at the DOOR: a separate address plus an auth prompt. That suffices exactly
  as long as only tests go there, and stops sufficing the moment a HUMAN accepts a design there —
  because acceptance happens on the SCREEN, not in the address bar, and production and sandbox sit
  side by side in two tabs of the same browser.

**The direction question, answered so it is not re-opened.** The marker's fail-closed direction is
the one genuinely rule-shaped part of either shape, and it STAYS PATTERN PROSE here — it is not
promoted to a spec. A spec is a standing rule a project MUST obey and that the kernel can BIND and
REFUSE against; this one has no binding point and no verifier the kernel could ever run, because the
artifact it would constrain is a consumer's product runtime code, which the kernel does not see and
by SPEC-0073 must not carry. Promoting it would add an entity whose only enforcement is prose —
precisely the "writing the cage down and calling it caged" defect §Anti-pattern names. So it is
written above as a one-way rule with its failure mode attached, which is the strongest form
available without a refusal behind it. If a project wants a refusal, the project owns it: assert in
your own test suite that the production configuration renders no marker.

## §Example

A read-only spike, end to end, in the shape a run record takes:

```
# 0. the project's yitc-ops.yaml already declares spike_sandbox.bridge {pin, enabled, cage_checks}
# (top-level key — `grep -n '^spike_sandbox:' yitc-ops.yaml`)
# 3. DECLARED FIRST, before anything comes up: mutating=no → may share the standing sandbox
bin/yitc-v2 worktree new --work spike-slow-list-query
# ⚠ active spike loop — sandbox edit / keep a transfer list instead
# 2. stack up under the declared cage: own identity, no scheduler, channels dummy.
# No channel needed → no grant, so 4d never arises.
# 4. entrance 502s while containers read healthy → restart the router ALONE, not a full refresh
#... measure, read, learn...
# 5. discard
bin/yitc-v2 worktree park --work spike-slow-list-query --force --reason "spike done — findings on the transfer list"
# 6. run record: sandbox=shared, mutating=no, sources opened = patterns/spike-mode.md only
```

The NO-STACK sibling is shorter still, because three of the six steps do not arise:

```
# fork: reading a captured log dump — nothing comes up → steps 2, 3, 4 do not arise
bin/yitc-v2 worktree new --work spike-parse-the-crash-dump
#... read, measure, learn...
bin/yitc-v2 worktree park --work spike-parse-the-crash-dump --force --reason "spike done — findings on the transfer list"
# 6. run record: stack=none, sources opened = patterns/spike-mode.md only
```

The mutating sibling differs in exactly two places, and they are the two the mode cares about: at
step 3 it takes its OWN sandbox because it writes, and at step 2, if it needs a live outbound
channel, it obtains the explicit per-case owner grant and **writes the record BEFORE flipping the
channel** (§2 atom 4d — the pinned library enforces that order; a failed record aborts the toggle).

## §Anti-pattern

- **Writing the cage down and calling it caged.** A rule stated but not checked is outside the
  contract. If a rule matters and nothing refuses its violation, say so in the status word rather
  than in a stronger verb.
- **Re-inflating a DISCIPLINE rule into a claimed refusal.** Rewording a DISCIPLINE item as "the
  system prevents…" makes this doc lie about what was actually measured — the single misread risk
  this doc was audited against. No CAGE row is DISCIPLINE today (§2's four atoms and §3 are all
  CHECKED), so the live DISCIPLINE items here are the safety floor's two halves: what the spike
  RUNTIME reaches, and what the restored COPY carries (§The safety floor, SPEC-0175). The warning is
  not retired with atom 4d — it is a standing rule about the status word, and it binds whichever row
  is DISCIPLINE next.
- **The mirror of it: understating a check that EXISTS.** Leaving a row written as DISCIPLINE after
  something started refusing its violation is a defect of the same family, not the safe direction
  (SPEC-0172 rule 4). Both §2 atom 4d and §3 sat that way in earlier copies of this doc. When a
  status word here disagrees with the rule-4e table, the TABLE is the source — read it, do not
  reason from this paragraph.
- **Landing the spike branch, or "just filing a couple of tasks" from inside the loop.** Both
  convert the exploration into committed work ahead of the owner's judgement. The first is refused;
  the second is not, which is exactly why it needs naming.
- **Reading LIBRARY MECHANICS as "the pinned library", and concluding the pin brings the refusals
  with it.** It is a LAYER name — who OWES the check — and the CHECKED rows it carries (§2 atom 4d,
  §3) were closed in a project's own spike instruments, not inside the pinned release. Pin the
  bridge and you still have to look for the refusal in your own toolchain before relying on it.
- **Copying a neutral bridge module into your repo** because the pinned release is missing a fix.
  Fix upstream, re-pin.
- **Taking the destructive full refresh for a dead entrance** because it is the only door with a
  name. §4.
- **Sharing a sandbox with a spike that writes**, because the two spikes are "about different
  things". The distinction is mutation, not topic.
- **Answering "was it mutating?" on the way OUT.** The declaration belongs in front of the stack,
  not behind it (§3). Deciding at exit time is not deciding.
- **Reading the isolated-stack atom as "so the data is handled".** It covers the stack's declared
  IDENTITY, not what a process inside it dials and not what the copy inside it CARRIES (§The safety
  floor). Both of those halves are yours to hold.
- **Reading "it is only a copy, and it lives in the sandbox" as safe.** A restored copy is the
  sanctioned source AND untreated until it is treated on all three strands and the treatment is
  proven (SPEC-0175). Living in a sandbox changes nothing about a token that still authenticates.
- **Answering one strand and calling the copy treated** — most often by NEUTRALIZING what could
  route and saying nothing about what a reader would, or about the outbox that sends the moment
  a worker starts. Neutralize is the reachability verb only; disclosure is masked/minimized/excluded
  or explicitly accepted under a record, and operational state is defused.
- **Refusing the restore because it "touches production".** The named refresh/export step reading
  live production READ-ONLY is permitted and is the sanctioned way to fill a sandbox; it is the spike
  RUNTIME that never connects. Collapsing those two actors into one is a defect, not caution.
- **Bind-mounting a SINGLE FILE into a live-code spike stack.** The container keeps serving the old
  inode the moment an editor rewrites that file by rename, and the tree on disk stops being what is
  running. Mount the DIRECTORY.
- **Making production DECLARE itself in order to suppress an environment marker.** That direction
  fails OPEN — a missing or misspelled variable ships a lie on the screen. Unset MEANS production;
  only the sandbox declares.
- **Re-deriving all of the above from SPEC-0172 per project.** That is the state of the world this
  doc retires.

## §Cites

- **SPEC-0172** — the spike-sandbox wiring contract: the normative rule text (three layers, the
  declaration, pin discipline, the cage's four atoms and their layer table, the knowledge-not-code
  exit, sandbox sharing, the scope bound, the entrance requirements). This doc is its runbook, not
  a second copy of its authority; on any conflict the spec wins.
- **SPEC-0175** — the spike-sandbox DATA floor, and the normative home of everything §The safety
  floor teaches: the live-system axis, the actor split, the three strands and their verbs, the
  untreated-artifact window and its emission limits, the `spike_data_safety:` declaration and the
  prove-by-querying obligation. SPEC-0172's atoms are predicates over the STACK; these are predicates
  over what the COPY carries. This doc cites it and does not restate it — on any conflict, or any
  wording here that has fallen behind it, the spec wins.
- **SPEC-0090** — the patterns(travel) / lessons(local) boundary: why this doc names no project's
  paths or container names, and where the ones you need do belong.
- **SPEC-0073** — the placement contract: why §Two shapes carries the PRACTICE (the property, the
  trap, the direction) while the runtime that implements it stays in the project that runs it.
- **SPEC-0165** — the loud-failure doctrine: why the cage is split into ATOMS and why CHECKED /
  DISCIPLINE is a two-word vocabulary.
- **SPEC-0035** — plan-stage trial: the sibling bounded operating mode. Its runbook — the third
  member of this mode family — is `patterns/trial-methods.md`; read that one when you are running a
  PLAN's controlled practice run rather than a throwaway exploration.
- **SPEC-0077**, **SPEC-0093**, **SPEC-0122**, **SPEC-0128** — the ops-contract carrier the §0
  declaration lives in, the pinned-dependency rung §0's `pin:` extends, and the concern registry
  that generates the section.
- `patterns/emergency-mode.md` — the other bounded degraded mode; read that one when the TOOLING is
  broken, this one when you are exploring.
- `patterns/error-friction-tracking.md` — where a "I had to read the spec to run this" capture goes.
