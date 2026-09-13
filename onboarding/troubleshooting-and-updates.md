# Troubleshooting and updates — "something is wrong" / "is there an update?" (English SoT, voiced by the AI)

Governing cards: **** (this doc) · **SPEC-0195** (release, pin, update) · **SPEC-0196** (the
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

Say "install the update". The AI first fetches the newer release into a local clone of the mirror,
then runs:

`yitc-v2 release update <clone> --into <engine> --anchor <fp> --from-release <old-clone>`

- `<clone>` is the new release, `<engine>` the existing install, `<fp>` the anchor fingerprint (the
  public `SHA256:…` line, see [`overview.md`](overview.md) §Trust and the anchor), `<old-clone>` the
  release you run today, used as the merge base.
- **Verify before write.** The signature and content check reach a verdict *before* the install is
  opened. A refused update prints `RELEASE UPDATE: REFUSED` with its reasons and changes nothing.
- **What it touches.** Kernel-owned files are replaced from the verified release; template files are
  merged three-way; files your project owns are **never written**.
- **How divergence is reported.** It never guesses. The summary line is `release_updated: vN -> vM`;
  each disagreement prints as `CONFLICT [kind] <path>: …`, each ledger finding as
  `LEDGER <KIND> <path>: …`. With no conflict it says every project-owned path was untouched. The AI
  shows you each conflict and asks — it does not pick a side.
- Without `--from-release` a local edit cannot be told apart from an old file, so every differing
  path is reported and left untouched — a useful read, but not an update.
- **Afterwards:** move the pin in `yitc-ops.yaml` to the new tag, then `yitc-v2 -C <project> init`
  back-fills any scaffold the new release added. `init` is idempotent: it adds what is missing and
  leaves what you have.

## Rolling back

Say "go back to the previous version". Nothing in your project is lost — tasks, specs, the log and
your code live in the project, not in the engine.

1. The AI checks out the previous release tag in a clone of the mirror.
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
