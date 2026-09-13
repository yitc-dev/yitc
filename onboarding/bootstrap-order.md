# Bootstrap order on a clean machine — the order the primary AI reads (English SoT)

Governing cards: **** (this doc) · **** (auditor-binary resolution) · **SPEC-0195**
(release/pin) · **SPEC-0147** (kernel-provided seed content). Placement: **kernel** — it travels in
every release, because the machine it is needed on has nothing else on it yet.

**Who does what.** The person installs ONE thing by hand — their AI tool (the AI provider Code or an
equivalent) — opens it in an empty directory, describes the project, and names the mirror and the
anchor. Everything below is then read and DRIVEN by the AI: it proposes each missing piece and, with
the person's agreement, installs it. The person agrees; the person does not type the commands.

## TRUST — read this before you read anything else

**This file is a REPRODUCTION until `release verify` has passed, and is load-bearing only after
it.** You are reading it inside a mirror whose signature has not been checked yet, so nothing in
Steps 1–3 may be trusted from HERE: take the **anchor fingerprint** and the **three commands**
(clone → `release verify` → `release install`) from the **org-profile README** — the independent
channel — and never from this file or from anywhere else in the mirror. Steps 1–3 below repeat them
only so a reader sees the whole order in one place. From **Step 4 onward** the release has been
verified against the out-of-band anchor and this doc is the order to follow.

## Step 1 — Prerequisites (the AI proposes, the person agrees, the AI installs)

Three tools must exist before anything else. Check each; install only what is missing.

| what | check command | if missing |
| --- | --- | --- |
| `git` | `git --version` | Debian/Ubuntu `apt install git` · Fedora/RHEL `dnf install git` · macOS `xcode-select --install` or `brew install git` |
| `python3` (3.9) | `python3 --version` | Debian/Ubuntu `apt install python3` · Fedora/RHEL `dnf install python3` · macOS `brew install python` |
| `ssh-keygen -Y` (OpenSSH 8.0+, signature verification) | `ssh-keygen -Y sign` (prints its usage/`missing`-argument error when supported; "unknown option" or "not found" means it is not) | Debian/Ubuntu `apt install openssh-client` · Fedora/RHEL `dnf install openssh-clients` · macOS ships it |

`ssh-keygen -Y` is not optional: it is what `release verify` uses to check the detached signature
over the manifest. Without it there is no trust step and nothing below may proceed.

## Step 2 — The anchor

The person hands over ONE link — this mirror — and nothing else. The **anchor fingerprint** is then
fetched by the AI, not by the person: the mirror's own README names the org-profile page
(<https://github.com/yitc-dev/.github>, section **Trust anchor**), the AI reads the anchor FROM THAT
PAGE — an independent repository, never the mirror it is about to check, because an artifact does
not get to certify itself — and then SHOWS the person the page URL and the exact line it took. The
person confirms one thing, in one word: that this is the `yitc-dev` organization page. Naming the
page inside the mirror is safe; taking the anchor from the mirror is not, and that is the whole
distinction this step turns on.

## Step 3 — Clone, verify, install

Run each command from the directory the clone was made in; the engine is invoked through the
CLONE's own path, because on this machine there is no other copy of it yet.

```bash
git clone <mirror-url> <mirror-dir>
<mirror-dir>/bin/yitc-v2 release verify <mirror-dir> --anchor <fingerprint>
<mirror-dir>/bin/yitc-v2 release install <mirror-dir> --into <engine-dir> --anchor <fingerprint>
```

`release verify` writes nothing, ever — it is the gate itself. A refused `release install` writes
NOTHING into `<engine-dir>`. Do not continue past a refusal; re-take the anchor from the independent
channel and ask the person.

## Step 4 — The project directory

```bash
mkdir -p <project> && cd <project> && git init
<engine-dir>/bin/yitc-v2 -C <project> init
```

`init` needs no worktree — it is the sanctioned bootstrap commit.

## Step 5 — Pin the kernel

`init` writes `yitc-ops.yaml`. Declare the two keys under its `kernel:` section (SPEC-0195 rule 3),
so the project records WHICH engine release it runs against:

```yaml
kernel:
  engine: {release_repo: <mirror-url>, release: <tag>}
  content: {release: <tag>, answers: <answers-tag-or-~>}
```

## Step 6 — The external auditor (recommended, not a precondition)

Work runs from day one on the ONE provider the person already has — the primary AI. A second,
**different** provider is **recommended** because it catches the first one's blind spots (CHARTER
§P4a); it is not a precondition for anything. While none is bound, every `audit pre` / `audit post`
still RUNS, on the primary AI's own provider, and every such verdict is honestly stamped
`auditor_independence: same-provider` — the owner can always tell from a verdict whether a different
mind checked the work. Until an external provider is bound, one line at each `session start` reminds
the person of this recommendation (re-fold it on demand with `bin/yitc-v2 audit status`, which
prints the resolved auditor per tier and its independence); the line goes silent the moment one is
bound. Nothing waits, nothing is refused.

When the person agrees to bind one, the AI PROPOSES this step and carries it out:

1. **Choose the second provider.** The AI asks which other AI provider the person already has or
   wants. This doc names none — the choice is the person's (CHARTER §P4b).
2. **Install that provider's CLI and log in** per **that provider's own documentation**, with the
   person's own account. HOW is not prescribed here — the AI proposes, the person agrees.
3. **Bind it** — the whole binding is up to four lines written by `config set` into ONE file, the
   machine-settings file `~/.yitc-coordination/machine-settings.json` (per SPEC-0202; outside the
   engine tree, so `release verify` and `update` never touch it; `bin/yitc-v2 config list` prints
   its exact path):

   ```bash
   <engine-dir>/bin/yitc-v2 config set auditor.routine.provider <adapter>
   <engine-dir>/bin/yitc-v2 config set auditor.routine.binary <absolute-path-to-binary>
   <engine-dir>/bin/yitc-v2 config set auditor.routine.home <provider-auth-dir> # optional
   <engine-dir>/bin/yitc-v2 config set auditor.routine.model <model-id> # optional
   ```

   (`<adapter>` is a name the engine's adapter registry knows — `bin/audit-config.yaml` lists them;
   the same four keys exist for the `full` tier.)
4. **Check the binding** with `<engine-dir>/bin/yitc-v2 audit status`: the routine tier should read
   `independence=external` and name the bound binary and model; the session-start line is now silent.

## Step 7 — Open the AI tool in the project and start a session

The person opens their AI tool with `<project>` as the working directory; the AI then runs

```bash
<engine-dir>/bin/yitc-v2 -C <project> session start
```

and follows the seed it is handed. From here the ordinary session protocol applies and this doc is
done.

When the person asks what this system is, how a working day looks, how projects are made, or what
the sandbox is, the answer is [`overview.md`](overview.md) — read it and voice it in their language.
