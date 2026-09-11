# Onboarding a PERSON onto YITC — non-technical-user primer + operator runbook

> **Born:** 2026-06-29, owner directive (this Review session) — the owner is about to hand a
> production project to a **non-technical manager** (a scoped server user, project-only rights) who will
> carry ongoing development. Sibling of `onboarding-onto-yitc-runbook.md` — that one onboards a
> **project** (code → governed corpus, read by the OPERATOR); THIS one onboards a **person** (a
> non-technical human, read by the NEWCOMER). Same **live-capture discipline**: the §Primer is the
> deliverable now; the operator/automation/frictions logs grow one real onboarding at a time.
>
> **Anti-complexity (CHARTER §P1) — 4 filters, written down (§When-NOT-to-add):** (F1) analog = the
> project-onboarding runbook — REUSED its shape (one home, branch/section by need, live-capture log);
> but its material is a project, this one's is a person → a sibling file, not a fold (folding would
> mix two audiences and mud the readability). (F2) new artifact, not a view — a person-facing primer
> has no existing home (`patterns/` is operator methodology; `scenarios/` assume an inside reader;
> `README` is technical). (F3) removed: nothing — genuinely new need. (F4) real need: a named
> non-technical manager is about to take over a real project. Passes.
>
> **Placement (kernel|v2-self|project, `before-project-dimension-judgement`):** KERNEL realm — this is
> general traveling methodology (onboarding people onto yitc-v2 itself, reusable across consumer
> projects), exactly like its kernel sibling runbook. Not project-specific.

---

## §Primer — hand THIS to the non-technical user (the only part they read)

> Everything from here to the next `---` is written FOR the newcomer, in plain language. Give them
> this section (swap `<owner>` for the real name). Keep it ~1 page — do not grow it with machinery.

# Welcome — how we work here

## 1. Most important: don't be afraid to ask
- The best question is simple and short.
- Didn't understand the answer — **ask again**. That's the right thing to do, not "silly".
- Feel you were misunderstood — ask the AI to restate it in its own words.
- Completely stuck or something feels off — **call <owner>**. He knows the system and will help quickly. Asking is always better than guessing.

## 2. How this works — in a nutshell
You don't write code or manage the tech. Work goes like this:
1. You **describe in words** what you need.
2. The AI **does** the work.
3. **Shows** you the result.
4. You look and say **"yes, that works"** or **"redo this bit"**.

That's it. The *how* — exactly what order and which checks — the system runs on its own.

## 3. Four words you'll come across
- **Task** — one concrete thing you asked for. ("Add an order-cancel button.")
- **Plan** — a big thing broken into several task-steps. ("Build the returns section".)
- **Session** — one working conversation with the AI. Just start a conversation and say what you need.
- **Scenario** — a description of "how it should work for the user", in simple steps. Needed when you're explaining behavior, not one small detail.

## 4. What you do NOT need to know
Internally the system keeps a lot of records — stages, checks, history, links. **That's not your concern.** If you meet unfamiliar words (stages, audit, graph) — that's the AI's inner kitchen. If they get in the way — say "explain it simpler" or just skip them.

## 5. When you must call a human (rather than guess)
- The AI explained twice and it's still unclear.
- You're asked to do something **irreversible or risky** (delete data, send something outward).
- The AI offers a **choice of "how to do it"** and the options have different consequences — that's a fork, and you shouldn't choose it blindly.
- The result is clearly wrong and you can't explain the difference.
- Something breaks or behaves strangely.

→ Stop, and call **<owner>**.

## 6. How to ask so you're understood the first time
Three questions in mind:
- **What** do I want? (in one phrase)
- **Why** is it needed? (so the AI grasps the goal, not the letter)
- **How will I know it's done?** (what I'll see / check)

In ordinary words, not technical ones. Not sure — just say so: "I'll phrase it as best I can, correct me if it's unclear".

---

## §Operator notes — how to set up + support the user (grow by live-capture)

> What the OWNER/operator does to onboard a person. Stubs now; fill in as the first real onboarding runs.

- **Handoff trigger — how/when the owner signals "introduce yourself to the user" (owner Q, 2026-06-29).**
  The crux: the owner and the user work in **separate sessions** (different scoped server users), so a cue
  the owner gives in HIS session does not reach the user's session live — it must become a **durable
  hand-off the user's FIRST session reads**. The agreed mechanism (recommendation A):
  - **Moment:** when the owner is ready to hand over ongoing dev — i.e. right before giving the user access.
  - **Owner's cue (in his own session):** one plain phrase, e.g. «peredayom proekt <imya>, gotov' onbording» ("handing over project <name>, prepare onboarding").
    On it the AI (1) tailors the §Primer to THIS project + fills in the name, and (2) writes a SHORT
    hand-off into the **project's `MEMORY.md`** (the auto-read cross-session buffer, SPEC-0039) — a
    `[instruction] [audience: next session — new non-technical user] [until: consume-once]` note: «the next
    human here is new + non-technical — greet plainly, walk the §Primer, do NOT dump machinery».
  - **What the owner gives the user:** access + one line — «nachni razgovor i skazhi, chto ty novenkiy» ("start a conversation and say you're new").
  - **User's first session:** the AI greets in plain language, **introduces itself** («I'm the AI that does
    the work; here's how we work together»), walks the §Primer's 6 points, invites questions. That self-intro
    IS the "tell the user about yourself".
  - **Interim caveat:** until the simplified entry exists (§Automation-candidates #1) the user's session
    still runs the normal heavy `/yitc` startup; the `MEMORY.md` hand-off is what makes the AI adopt the
    plain register anyway. The clean fix is automation #1.
- **Scoped server user** — give a project-only server user (rights limited to the user's project(s)), per
  the existing host scope-guard model. **Concrete provisioning runbook + verification checklist below
  (captured 2026-07-08 at the first real onboarding: `<collaborator-2>` → `bc-community`).**

### Provisioning runbook — concrete ordered steps (run as owner `dev`)

Each step names its host tool (glossed) + what it delivers. The host tools live OUTSIDE the kernel repo
(referenced read-only as provenance; they are host-territory, not V2-governed).

1. **OS user + groups** — `<host-home>/bin/provision-user.sh <user> developer <proj1,proj2> [<cmd1,cmd2>]`
   (the host script that creates the Linux account). It creates the user, puts them in group `dev` (so
   they can READ the shared project + engine files) and dev in their group, sets the `<provider-config>/projects`
   ACL for the dashboard collector, a secrets dir, SSH restrictions, a cleanup cron. **As of 2026-07-08 it
   ALSO writes the registry `users.<name>` entry** (projects + `allowed_commands`) and **no longer creates
   the legacy per-user git worktree** (yitc-v2 consumers work in the SHARED checkout).
2. **Registry entry** — done by step 1 now; VERIFY `users.<name>.projects` + `allowed_commands` in
   `<host-home>/registry.yaml` are correct — this exact entry IS what `/work` resolves the user's access
   from (`users.<whoami>.projects`). A missing entry → `/work` refuses («not registered»).
3. **the AI provider account + `<provider-config>` wiring** — assign the user a the AI provider account/slot and create the `<provider-config>`
   symlinks (`commands`, `plugins`, `settings.json`, `.credentials-account-N.json` → `<host-home>/<provider-config>/…`).
   This is a per-user account DECISION (which account), handled by the the AI provider-account tooling — canonical
   home `<host-home>/knowledge/the AI provider-accounts.md`. Without it the user's session has no shared
   commands/credentials. (Deliberately NOT folded into `provision-user.sh` — it is an account choice, not
   a blind symlink.) **The symlinked surfaces are shared and travel; the per-user COPIES do not.** The
   entry skills (`~/<provider-config>/commands/{start,work}.md`) and `permissions.allow` in the user's OWN
   `settings.json` are hand-made per-user copies that NO mechanism refreshes — they ROT silently after
   this step (X-0333/X-0334, §Lessons class 4). Verify both at the drill below, never at provisioning
   time only.
4. **Secrets** — `<host-home>/bin/grant-secrets.sh <user> developer <projects>` copies each project's
   filtered `.env` into the user's OWN secrets dir (`<host-home>/secrets/<user>/`). **GOTCHA (§Frictions):** a
   project's own scripts may HARDCODE the shared dev-only path (`<host-home>/secrets/<proj>.env`) instead of
   the user copy — the scoped user then cannot read it. Catch it at the verify step.
5. **Perms** — new projects are born correct (0664, group-readable) after the `write_text_atomic` mode-fix
; an EXISTING project may need a one-time normalize of any owner-only (0600) scaffolds the user
   must read (`MEMORY.md`, `yitc-ops.yaml`) AND the engine read-surfaces the `-C` session reads
   (`<engine>/graph/*`, `<engine>/release-view/*`).
6. **Cross-log routing** — nothing to set up since : the shared coordination log defaults to the
   ONE canonical path `<host-home>/.yitc-coordination/coordination.jsonl` for EVERY OS user (it is no longer
   `$HOME`-derived). `YITC_CROSS_LOG` remains the owner-tunable OVERRIDE, and the export in the shared
   `<host-home>/<provider-config>/settings.json` `env` block is now belt-and-braces rather than the fix — a session
   that never inherits that env still reaches the right store. Verify by running, AS the user,
   `<engine>/bin/yitc-v2 cross inbox` and confirming it is NOT empty.

### Verify access AS the user — MANDATORY (this is what catches the SILENT breakages)

Do **not** trust "the files are in place". Run each real operation AS the user (`sudo -u <user> …`) and
confirm it actually works. The failure mode of every access gap here is **SILENT** (fail-safe → empty /
"clean" / an orphan write), so only an end-to-end run AS the user reveals it. Checklist:

- **Repo read** — `sudo -u <user> test -r <host-home>/projects/<proj>/MEMORY.md` AND the engine seed —
  EVERY part of the chain, tested one file at a time (a single `test -r` on a glob checks only the FIRST
  match, so "part 1 readable but part 3 not" — the silent gap this checklist exists to catch — would pass):
  `for p in.../yitc-v2/release-view/graph/worker-seed*.md; do sudo -u <user> test -r "$p" || echo "UNREADABLE: $p"; done`
- **Methodology activates** — `sudo -u <user> <engine>/bin/yitc-v2 -C <host-home>/projects/<proj> session start`
  → prints `session_started` (exit 0), with NO permission-denied on any read-surface (e.g. `graph/born-ops.yaml`).
- **Cross-log → kernel** — after a `cross request` in the user's session, the row lands in
  `<host-home>/.yitc-coordination/coordination.jsonl` (the KERNEL log), NOT `/home/<user>/.yitc-coordination/`.
  Since this holds by default (not only when `YITC_CROSS_LOG` is exported) — check it with the env
  var UNSET to prove the default itself is right.
- **Secrets / data store** — run the project's ACTUAL tooling that needs secrets/DB as the user (e.g.
  `sudo -u <user> bash <proj>/bin/<check>.sh`) and confirm it returns REAL data, not a fail-safe empty;
  cross-check the count against a `dev` run.
- **Entry skills are CURRENT** — the user's `~/<provider-config>/commands/start.md` AND `work.md` are per-user
  COPIES nothing regenerates. Run the entry AS the user, headless, and confirm the session loads the
  CURRENT skill — not a v1-era one, and not a missing one (`Unknown command: /work`). A stale copy routes
  the user by rules that no longer exist; an absent one denies the entry outright (X-0333).
- **Engine binary allowlisted** — the user's OWN `~/<provider-config>/settings.json` `permissions.allow` covers
  `<engine>/bin/yitc-v2` plus the sandbox dirs the `-C` session reads. The engine path sits OUTSIDE a
  cwd-scoped sandbox, so an empty allowlist puts an approval gate on `session start` — the one step of the
  consumer flow that CANNOT be skipped (X-0334).
- **allowed_commands** — the user's registry `allowed_commands` cover what they need; the
  `slash-command-guard.sh` hook enforces default-deny.

A fully-green checklist = the person can actually work. Any red → fix at **SOURCE** (the path / perm / env),
never a per-user patch.

### Lessons — the silent-breakage classes (found ONLY by running AS the user)

**Classes 1–3 (2026-07-08, `<collaborator-2>`)** are three instances of ONE class — «a scoped user silently lacks
the access their work needs»:
1. **Home-relative path** — the coordination log defaulted to `$HOME/.yitc-coordination`; a non-dev home
   wrote to an ORPHAN log (the note never reached the kernel). Interim fix 2026-07-08: `YITC_CROSS_LOG` in
   shared settings — a per-user env workaround that only held where the env was inherited, so the split
   re-surfaced as X-0663 the day the collaborator lane went live. STRUCTURAL fix: made the default
   itself canonical (one absolute path, group-appendable), so the env var is an override, not a crutch.
2. **Owner-only file mode** — `mkstemp`-born 0600 scaffolds (via `write_text_atomic`) unreadable to a
   group-dev collaborator, which the AI then misread as «methodology is not my lane» and skipped activation.
   Fix: (mode-restore) + one-time chmod.
3. **Hardcoded shared secret path** — a project script points at the dev-only `<host-home>/secrets/<proj>.env`
   rather than the user's copy; the scoped user can't read it (worked only by accident via docker
   trust-auth). Fix: resolve secrets user-aware, or grant the copy (per-project decision).

**Class 4 — the per-user SURFACE is a stale/absent COPY** (2026-07-12, `<collaborator>` → aiseller; the first
multi-user migration). A DISTINCT class, not a fourth instance of the above: the access is FINE — what
rots is the per-user surface the session actually LOADS, so **the surface the runbook NAMED is not the one
that RAN**. Two evidenced faces, both hand-made copies no mechanism refreshes:
- **Entry skills rot.** <collaborator>'s `start.md` was a 2026-04-14 v1-era file (Build/Review picker, zero mention
  of `yitc_v2` / `-C`) and `work.md` was absent entirely — headless `/work` returned `Unknown command`
  (X-0333).
- **Permission allowlist excludes the engine.** <collaborator>'s `permissions.allow` was EMPTY → an approval gate on
  `<engine>/bin/yitc-v2 -C <proj> session start`, the one non-skippable step → no read-order echo, no
  anchors (X-0334).
The tell that this class is invisible from the owner's chair: aiseller shipped a technically-COMPLETE
migration whose second human collaborator could not run `/work` at all. Both faces are now rows in the
checklist above. (The migration-completion GATE over the same surfaces — «has every collaborator's row
been verified or created?» — is `patterns/onboarding-onto-yitc-runbook.md` §B5-check-3 rows 3+4; this doc
owns the per-person how-to, that one owns the gate.)

All four were INVISIBLE at "files exist" and surfaced only by the verify-as-user run — which is WHY that
step is mandatory, not optional.
- **What to hand them** — the §Primer above (name filled in).
- **Entry point** — the user gets the host command **`/work`** (NOT `/yitc`, NOT `/start`): a host-territory
  sibling of `/start` (`<host-home>/<provider-config>/commands/work.md`, gitignored like `/start`, owner-authored
  2026-06-29) that lists ONLY the projects the user's OS account can access and **auto-enters when exactly
  one is accessible** — so a scoped single-project manager lands straight in, no picker. It also honors the
  §Handoff-trigger `MEMORY.md` note (greet plainly, self-intro, walk the §Primer). This closes the
  scoped-ENTRY half of §Automation-candidates #1; the hide-the-machinery half (no heavy handbook dump, no
  Build/Review question for a non-technical user) is the remaining #1 work.
- **Support loop** — the user escalates per §Primer #5; the operator answers in plain language and
  captures any recurring confusion into the §Primer (a general lesson graduates IN).

## §Automation-candidates log — "what more can we hand to the AI" (grow live)

> The meta-product (owner framing 2026-06-29): the primer PROMISES "the machinery is not your concern".
> Every spot where the machinery still has to be SHOWN to / DONE BY a human is a candidate to hand to
> the AI / automate. Capture each here as it surfaces; this log is the input to a future plan
> «hand more to the AI». NOT built now (no incident yet per-candidate — anti-complexity F4).

1. **Session entry** — forces reading the 5-file handbook + choosing a type. A non-technical user can't
   do this. **TWO halves:** (a) *scoped entry* — show only the user's project + auto-enter → **DONE: the
   host command `/work`** (access-filtered `/start`, 2026-06-29; see §Operator notes → Entry point).
   (b) *hide-the-machinery* — STILL OPEN: the AI should run the heavy startup (handbook reads, the
   Build/Review choice, stages/audits) SILENTLY and greet in plain language, never surfacing it to a
   non-technical user. The `MEMORY.md` hand-off makes the AI adopt the plain register today; the clean
   fix is making the silent-startup behavior intrinsic.
2. **Build vs Review choice** — the user shouldn't have to pick → the AI infers from what they ask.
3. **Worktree / land / commit mechanics** — operator-triggered today → for this user the AI should do
   them automatically and never surface the words "worktree/land/commit".
4. **Carrier choice (task vs plan) + filing** — an operator judgement today → the AI proposes; the user
   only confirms intent.
5. **Audit verdicts (YELLOW/RED handling)** — machinery → the AI resolves; surfaces to the human only
   when a genuine decision is needed, in plain words.
6. **Knowing when to escalate** — the primer puts this on the user; the AI could ALSO proactively flag
   «this is above my confidence — let's loop in <owner>» (esp. on architectural forks, per §Primer #5).

## §Frictions log (append live — newest last)

> One entry per friction/deviation/decision hit during a real person-onboarding. Small ones count.
> Generalise into the sections above during a periodic meta-analysis pass; keep the raw entry here.

- **2026-07-08 — `<collaborator-2>` → `bc-community` (first real person onboarding; owner-driven debug).** Five
  frictions, all of the ONE class «a scoped user silently lacks needed access», all invisible at "files
  exist" and found only by running AS the user:
  1. **Activation skipped on a false signal.** `/work` routed correctly but the AI hit permission-denied on
     owner-only `MEMORY.md`/`yitc-ops.yaml`, concluded «methodology is not my lane», and SKIPPED
     `session start` + the handbook + the anchors — activating YITC only much later, reactively, when a
     `cross request` fail-closed. Fixes: `/work` + `/start` now make `session start` the crisp first,
     separately-announced step + say permission-denied is EXPECTED-not-a-skip-signal.
  2. **0600 scaffolds.** The denied files were owner-only because `write_text_atomic` (`mkstemp` 0600,
     preserved by `os.replace`) left every atomic-written file owner-only. Fix (mode-restore) +
     one-time chmod of existing consumer + engine read-surfaces.
  3. **Cross-log orphaned.** Their `cross request` wrote to `/home/<collaborator-2>/.yitc-coordination/` (home-relative
     default), never reaching the kernel log. Fix: `YITC_CROSS_LOG` in shared settings.
  4. **`/work` observability.** The owner could not SEE that activation happened (it was bundled into a
     `cd && session start` bash line + the handbook reads as 3 assembled view-files). Fix: `/work` now runs
     `session start` visibly + prints a plain «methodology activated» confirmation.
  5. **Project secrets access (trend-finder cross-check).** A sibling project's ticket scripts hardcode the
     dev-only `<host-home>/secrets/<proj>.env`; the scoped owner (filev) can't read it (worked only via docker
     trust-auth). Per-project fix pending (user-aware secret resolution). Motivated the mandatory
     verify-as-user checklist above.
  - **Provisioning-runbook + verify-as-user checklist authored** (this doc, §Operator notes) from these.
  - **Also improved:** `provision-user.sh` now writes the registry `users.<name>` entry (the `/work` access
    source) + drops the legacy per-user worktree.
