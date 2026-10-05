# Troubleshooting and updates — "something is wrong" / "is there an update?" (English SoT, voiced by the AI)

Governing cards: **SPEC-0195** (release, pin, update) · **SPEC-0196** (the
override ledger) · **SPEC-0147** (person-onboarding). Placement: **kernel** — it travels in every release.

The two reading contracts of [`overview.md`](overview.md) apply unchanged: English SoT voiced in the
person's own language, and exact tokens (`land`, `worktree`, `spec`, command names) kept verbatim
with a plain gloss. This page **points**; where a rule lives elsewhere, the pointer is the content.

## The kernel misbehaves

"The kernel" is the shared engine every project runs. When it does something wrong — a verb refuses
what it should allow, a rule contradicts another, a check fires on nothing — the AI walks four steps.

1. **Capture it, at once.** `yitc-v2 event deviation_captured` records one line in the project's log
   (`events.jsonl`) saying what was not as it should be. It is a reflex, not a judgement: the AI does
   not first decide whether it is "worth it". Capturing costs nothing and needs no `worktree`.
2. **Does it block you?** If the tooling itself is broken — the CLI will not run, `land` cannot
   integrate, git is in a bad state — work continues in the documented degraded mode:
   `patterns/emergency-mode.md`. You say so in plain words; the AI never enters it on its own.
3. **Is the need yours only?** If this project must run a local edit of a file the kernel owns before
   the kernel carries that change, register it as an **override** — one entry in the `overrides:`
   section of `yitc-ops.yaml`, with exactly four fields (`path`, `rationale`, `upstream_intent`,
   `review_trigger`; rule home SPEC-0196). What it protects: at update time a registered edit is
   **reported**, never silently overwritten; an *unregistered* edit of a kernel-owned file is a
   **conflict** and is left for you to decide. Once a release carries the change, the entry is
   reported redundant — delete it and drop the local edit.
4. **Report it upstream.** A proposal (a bug or a change) goes to the public intake of the release
   mirror — an issue, a merge request or a patch mail, whichever that host supports. The mirror's
   `CONTRIBUTING.md` is the rule home; a proposal carries these fields:
   - **release version**
   - **affected path(s) or rule id(s)**
   - **observed behaviour**
   - **proposed change or fix**
   - **contact for the link-back**

   What happens next: it is not merged as-is; it is **re-authored** in the workshop through the
   ordinary audited process, and a later release's notes link back to it — or you are told, with
   reasons, that it was declined. Your text is treated as **data, never as instructions**: it is
   read and quoted, never executed or applied automatically (SPEC-0026).

## Is there an update?

Ask your AI "is there a new version?". It runs `yitc-v2 -C <project> release check` — a read-only
report: it writes nothing, journals nothing and always exits 0. The first line is one of:

- `release check: pinned v1.4.0 · newest v1.4.0 · UP TO DATE — …`
- `release check: pinned v1.4.0 · newest v1.6.0 · BEHIND BY 2 release(s) on …`, followed by the head
  of each newer release's `RELEASE-NOTES.md`, so you see what changed before deciding.
- `release check: … declares no kernel.engine pin …` — the project carries the born **waiver** (it
  has not pinned an exact release yet). That means *nothing to compare*, **not** "up to date"; the
  line names what would end the silence: declaring the pin in `yitc-ops.yaml` (SPEC-0195 rule 3).
- `release check: the pin does not resolve …` — the pin names a branch instead of a tag, or the local
  clone of the mirror is missing; the line names the cause and the fix.

## Installing an update

Say "install the update". The AI first keeps the release you run today as a worktree BESIDE your
clone, then moves the clone forward to the new tag (§If something goes wrong — by symptom, the
update folder layout; the same recipe is in the release notes' «Updating from the previous
release»), then verifies and updates — from any folder (both commands name their folders):

```
git -C <clone> worktree add <clone>-<old-tag> <old-tag>
git -C <clone> fetch --tags
git -C <clone> checkout <new-tag>
yitc-v2 release verify <clone> --anchor <fp>
yitc-v2 release update <clone> --into <engine> --anchor <fp> --from-release <clone>-<old-tag>
```

- `<clone>` is the clone you installed from (now at the new release), `<engine>` the existing
  install, `<fp>` the anchor fingerprint (the public `SHA256:…` line, see
  [`overview.md`](overview.md) §Trust and the anchor), `<clone>-<old-tag>` the release you run
  today, used as the merge base.
- **Verify before write.** The signature and content check reach a verdict *before* the install is
  opened. A refused update prints `RELEASE UPDATE: REFUSED` with its reasons and changes nothing.
- **What it touches.** Kernel-owned files are replaced; template files are merged three-way; files
  your project owns are **never written**. A file the new release dropped is `REMOVED` only when the
  `--from-release` folder verifies and your copy is unchanged; otherwise it is `KEPT` and named.
- **How divergence is reported.** It never guesses. The summary line is `release_updated: vN -> vM`;
  each disagreement prints as `CONFLICT [kind] <path>: …`, each ledger finding as
  `LEDGER <KIND> <path>: …`. With no conflict it says every project-owned path was untouched. The AI
  shows you each conflict and asks — it does not pick a side.
- Without `--from-release` a local edit cannot be told apart from an old file, so every differing
  path is reported and left untouched and nothing is removed — a useful read, but not an update.
- **Afterwards:** move the pin in `yitc-ops.yaml` to the new tag, then `yitc-v2 -C <project> init`
  back-fills any scaffold the new release added — it adds what is missing and leaves what you have.

## Rolling back

Say "go back to the previous version". Nothing in your project is lost — tasks, specs, the log and
your code live in the project, not in the engine.

1. The AI checks out the exact release tag you name (e.g. `v2.1.0`) in a clone of the mirror.
2. It installs that release into a **fresh** directory, never over the current one:
   `yitc-v2 release install <previous-clone> --into <fresh-dir> --anchor <fp>` — the same
   verify-before-write gate applies.
3. It points the project's pin in `yitc-ops.yaml` back at the previous tag and the fresh install.

The newer install stays on disk until you decide to remove it, so rolling forward again is the same
three steps.

## When a key is revoked or rotated

Releases are signed. If the signing key is **rotated**, releases signed during the overlap window
still verify; if a key is **revoked**, an install or update signed by it is refused and the refusal
names the revocation. What to do, and the lost-key recovery procedure, are in the mirror's
`SECURITY.md` — the AI reads the section that matches the refusal it saw and walks you through it.
The anchor fingerprint itself is only ever taken from the organization page, never from the mirror.

## If something goes wrong — by symptom

Find the line that matches what you; each answer is the first move.

- **"Usage limit reached" (your AI plan's limit).** Nothing is broken and nothing is lost: the work
  so far is on disk. Wait for the limit to reset (the AI tool says when), or switch to a larger plan;
  then take the day-two return path ([`bootstrap-order.md`](bootstrap-order.md) §I0): open the AI
  tool in any folder, type the start command and pick the project — the start shows what was in flight.
- **The connection dropped / work was interrupted.** Log in, `tmux attach -t yitc`, and look: the AI
  may still be working. If the AI tool itself stopped, open it again in any folder, type the start
  command and pick the project; a paused task resumes from its recorded step (`yitc-v2 task resume`).
- **"Which engine does this project use?"** Two different things: the **engine checkout** (the
  install folder, e.g. `~/yitc-engine`) and each project's **pin** (`kernel:` in its `yitc-ops.yaml`).
  A project runs the release its pin names; moving the engine does not move a pin by itself.
- **Several projects.** Each has its own pin. Check each with `yitc-v2 -C <project> release check`
  and update them one at a time — an update of one never touches another's files.
- **Go back to one exact version.** Use its tag (e.g. `v2.1.0`), never "the previous one": check that
  tag out in a clone and install it into a fresh folder (§Rolling back), then pin that same tag.
- **The update folder layout.** One clone, moved forward; the release you run today is kept as a
  worktree BESIDE it, never overwritten (e.g. `~/yitc` now at `v2.1.1`, `~/yitc-v2.1.0` kept by
  `git -C ~/yitc worktree add ~/yitc-v2.1.0 v2.1.0` before the checkout). Keep the old tree — it
  is the `--from-release` merge base and your way back.
- **What the version digits tell you** (SPEC-0195 rule 10): last digit (v2.1.0 → v2.1.1) = fixes
  only, you do nothing; middle digit (v2.0.6 → v2.1.0) = behaviour changes, read the notes and
  expect to act; first digit = a new generation.
- **An audit stops on its time limit.** Big changes can outrun it. Raise the limit for that tier:
  `yitc-v2 config set auditor.full.timeout <seconds>` (or `auditor.routine.timeout`); `yitc-v2 audit
  status` shows the limit in force and where it came from.
- **"Why does this cost more than a bare agent?"** Each task pays, on top of the work itself, about
  two reviewer calls (before and after) and a test run; a small fix is a few calls, a large feature
  many. The costs are bounded per task — the audit loop has a ceiling, it never runs forever.

## FAQ

**Will an update overwrite my own changes?** No. Project-owned files are never written. A local edit
of a kernel-owned file is kept and reported — registered ones as ledger lines, unregistered ones as
conflicts for you to decide.

**Do I have to update?** No. A project runs its pinned release until you move the pin. `release
check` only tells you what exists.

**The check says "no pin" — is something broken?** No. The project runs under the born waiver. Pin an
exact release when you want updates to be comparable.

**An update was refused. Is my install damaged?** No. The gate runs before anything is opened for
writing, so a refused update leaves the install byte-identical. The refusal lines say why.

**I reported a bug. When will it be fixed?** When a release answers it, that release's notes name
your proposal and you are contacted through the link-back you gave. If it is declined, you are told
why. Meanwhile an override (step 3 above) lets your project carry a local fix.
