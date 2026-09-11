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

The **anchor fingerprint** is taken by the PERSON from the org-profile README on the independent
channel and handed to the AI. The AI never fetches the anchor from the mirror it is about to check —
an artifact does not get to certify itself.

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

## Step 6 — The external auditor

**Required, and a DIFFERENT provider from the primary AI** (CHARTER §P4a). The auditor exists to
catch the primary AI's blind spots; an auditor that is the same model reviewing its own work catches
nothing. Without a bound auditor every `audit pre` / `audit post` ABORTs, and the lifecycle cannot
reach `land`.

The AI PROPOSES this step and, with the person's agreement, carries it out:

1. **Choose the second provider.** The AI asks which other AI provider the person already has or
   wants. This doc names none — the choice is the person's (CHARTER §P4b).
2. **Install that provider's CLI** per **that provider's own documentation**, so its binary lands on
   `PATH`.
3. **Log in** with the person's own account for that provider, per the same documentation.
4. **Bind it** (in this order):
   - the configured binary name (by default `<external-auditor>`) is on `PATH` — nothing further to do; or
   - `export YITC_CODEX_AUDIT_BIN=<absolute-path-to-binary>` in the environment the AI runs in.

   The kernel config file is the LAST RESORT only. There is no machine-setting `config set` for this
   key — it is GATE-class and `config set` refuses it.
5. **Smoke-verify the binding** with an `bin/yitc-v2 audit adhoc --help`-class call. If the binary
   cannot be resolved the engine answers with a NAMED refusal telling you exactly which of the three
   lookups failed — never a silent success.

## Step 7 — Open the AI tool in the project and start a session

The person opens their AI tool with `<project>` as the working directory; the AI then runs

```bash
<engine-dir>/bin/yitc-v2 -C <project> session start
```

and follows the seed it is handed. From here the ordinary session protocol applies and this doc is
done.
