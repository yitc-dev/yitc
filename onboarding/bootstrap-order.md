# Bootstrap order on a clean machine — the order the primary AI reads (English SoT)

Governing cards: **SPEC-0147**
(kernel-provided seed content). Placement: **kernel** — it travels in
every release, because the machine it is needed on has nothing else on it yet.

**Who does what.** The person installs ONE thing by hand — their AI tool (any AI coding tool that
can run commands) — opens it, and hands over the mirror link. Everything below is then read and
DRIVEN by the AI as a **concierge script**: at each stage it CHECKS what the stage names and SAYS, in
plain words and in the person's language, what it found and what comes next. It proposes each missing
piece and, with the person's agreement, installs it. The person agrees; the person does not type the
commands. The stages run in this fixed order: I0 briefing · I1 root hand-off · I2 working-user checks
· I3 verify and install · I4 first project · I5 install receipt and first start · I6 auditor
offer · I7 deploy (later).

## TRUST — how to read this file (not a stage; I0 is still the first thing that happens)

**This file is a REPRODUCTION until `release verify` has passed, and is load-bearing only after
it.** You are reading it inside a mirror whose signature has not been checked yet, so nothing in
stages I0–I3 may be trusted from HERE: take the **anchor fingerprint** and the **three commands**
(clone → `release verify` → `release install`) from the **org-profile README** — the independent
channel — and never from this file or from anywhere else in the mirror. I3 below repeats them
only so a reader sees the whole order in one place. From **I4 onward** the release has been
verified against the out-of-band anchor and this doc is the order to follow.

**The trust transition, stage by stage.** I0–I2 execute NOTHING taken from the mirror: they are a
talk (I0) and ordinary account and machine checks (I1, I2) that the AI performs with the machine's
own standard tools (creating a user, SSH keys, the system package manager); the I1 steps are
taken from the org-profile README — this file only names their ORDER, and the person can check each step on its own merits. No
mirror-sourced command ever runs as root. The first mirror-sourced commands are the three in I3, and
they are taken from the org-profile README, not from here. Only after `release verify` passes does
this file become the order to follow.

**TRUST and I0 do not compete.** TRUST is a reading rule, not a step: it runs no command and asks the
person nothing, so the order of what HAPPENS still starts at I0. The I0 briefing points and the I2
prerequisites are published on the org-profile README before its **Install** section, so the AI can
voice I0 and run the I2 checks from the independent channel; the I0 and I2 text below is the same
content, recapped here.

## I0 — Briefing, before installing anything

Nothing is cloned or installed until this briefing is done and the person says to go on.

- **What to check:** that the person knows what they are agreeing to. Nothing on the machine changes yet.
- **What to say:**
  - *What it is:* a way of working in which the AI does the work in small, checked, recorded steps,
    so the person can always see what was done and why ([`overview.md`](overview.md) has the long
    answer).
  - *What it costs:* the person's own AI subscription, plus the time and usage each check takes —
    slower and more expensive than a bare agent, in exchange for work that is checked and remembered.
  - *How you come back next time — and how you start and restart:* ONE order, every time (the **day-two return path**,
    written out below). Nothing starts by itself and the home folder does not list your projects on
    its own — you reattach, open the AI tool in any folder (or clear the session already open), type
    the start command and pick the project.
  - *Why a second provider:* a second, different AI provider can later check the first one's work,
    because each misses things the other catches. It is recommended, never required — work runs from
    day one on the one provider the person already has (see I6).
  - *What only you can do:* the list below, said upfront so nothing surprises the person later.

**What only you can do — the human-only steps.** The AI does the rest; these need the person's own
hands, eyes or accounts:

1. **Log in to your AI tool — twice:** once as root (for I1 only) and once as the working user
   (from I2 on). Each account signs in to the AI tool separately.
2. **Open a second SSH window** when asked, to prove the new login works before root is left.
3. **Approve commands** the AI proposes, once, when the AI tool asks for its permission setting.
4. **The sudo password — decide at I1.** Say whether the working user gets `sudo` (admin rights) and,
   if so, keep its password yourself; the AI never asks for it in chat.
5. **A password-only server:** if you log in with a password today, the AI sets up an SSH key for the
   working user at I1 — you keep the key file on your own computer.
6. **The deploy permission:** before the first production deploy you write one line by hand in the
   server's host registry, granting yourself the deploy right (I7). The AI may never write it.
7. **Secrets:** tokens and passwords go in by the safe hand-over below (§Secrets — how to hand one
   over safely), never typed into the chat.
8. **Reconnect:** when the connection drops, you log in again and reattach (the day-two return path).

**The day-two return path — how you come back, every time.** Word for word:

```text
1. ssh <user>@<server> log in as your working user
2. tmux attach -t yitc back into your kept terminal (after a reboot: tmux new -s yitc)
3. <your AI tool> open it in any folder, or clear the session already open
4. /yitc-projects type the start command, then pick the project
5. the start line "Working in YITC mode — project <name>." must appear
```

There is no second order: no restart inside the project folder, no "open the tool in the project
folder next time". Step 4 shows the default tool's form; each AI tool's own start command and its
clear-the-session command are in the AI-tool list `bin/ai-tools.yaml` (`invoke`, `clear_session`). The engine finds its session record by session id
in any folder, so the folder the tool was opened in does not matter.

## I1 — From root to an ordinary user, before any mirror instruction

**The steps of this stage live on the org-profile README** (section «Before the install — from root
to an ordinary user»), the independent channel that also carries the anchor and the three commands —
never here. This is only a plain recap so the whole order reads in one place; if the two ever
differ, the org page wins. Nothing in this stage is a command taken from the mirror: the AI follows the org page
with the machine's own standard tools, and the mirror is not cloned until I3, by the working user.

- **Recap:** create an ordinary working user; decide whether it gets `sudo` (the person answers, and
  keeps the password); keep recovery access until the new login is proven; set up SSH for that user —
  on a password-only server this is where the SSH key is made; **PROVE a second login before leaving root**; then the person pastes ONE line
  (the org page link and «install») into the new session. There is **no hand-off file**.
- **What to say:** "I made you an everyday account and checked you can log in to it. Please open a new
  window as that account, start your AI tool there, and paste this ONE line."

If the person is already an ordinary user, I1 is skipped. From here on, every new window starts
with the kept terminal first (I2), then the AI tool inside it.

## I2 — Checks as the working user

Every check runs as the working user, never as root.

### First: a terminal that survives a disconnect

Before any other check and before anything is cloned or installed (I3), the AI sets up a **terminal
multiplexer** — a program (`tmux`) that keeps your terminal and the AI tool running on the server
when your connection drops. Without it a dropped connection kills the work in flight.

1. **Install and check:** `tmux -V` prints a version; if missing, Debian/Ubuntu `apt install tmux` ·
   Fedora/RHEL `dnf install tmux` · macOS `brew install tmux`.
2. **Start the kept terminal:** `tmux new -s yitc`, then start the AI tool INSIDE it.
3. **Prove the reattach once, now:** detach with `Ctrl-b` then `d` (or close the window), log in
   again, run `tmux attach -t yitc` — the same screen is back. Only after this works does the AI go on.
4. **After a server reboot** the kept terminal is gone (a reboot ends it): run `tmux new -s yitc`
   again and start the AI tool. Nothing is lost — the work state lives on disk, in the project, not
   in the terminal; the start command picks it up (the day-two return path).

Then the checks:

- **What to check:**
  - the AI tool is installed and **on PATH** (the list of places the shell looks for programs), so
    it opens by name from any folder;
  - the AI tool is **authenticated** (logged in to the person's own account);
  - its **autonomous permissions** work: it can run commands without asking at every step (the
    person agrees to this setting once);
  - **git identity** is set (`git config user.name` and `user.email`);
  - the person's files are **user-owned** (nothing in their home belongs to root);
  - **disk** headroom: enough free space for the engine, the project and its history (a few GB);
  - the four prerequisite tools exist — install only what is missing:

| what | check command | if missing |
| --- | --- | --- |
| `git` | `git --version` | Debian/Ubuntu `apt install git` · Fedora/RHEL `dnf install git` · macOS `xcode-select --install` or `brew install git` |
| `python3` (3.9) | `python3 --version` | Debian/Ubuntu `apt install python3` · Fedora/RHEL `dnf install python3` · macOS `brew install python` |
| `PyYAML` (the YAML reader for `python3`) | `python3 -c "import yaml"` (silent when present) | Debian/Ubuntu `apt install python3-yaml` · Fedora/RHEL `dnf install python3-pyyaml` · macOS `python3 -m pip install --user pyyaml` |
| `ssh-keygen -Y` (OpenSSH 8.0+, signature verification) | `ssh-keygen -Y sign` (prints its usage/`missing`-argument error when supported; "unknown option" or "not found" means it is not) | Debian/Ubuntu `apt install openssh-client` · Fedora/RHEL `dnf install openssh-clients` · macOS ships it |

`ssh-keygen -Y` is not optional: it is what `release verify` uses to check the detached signature
over the manifest. Without it there is no trust step and nothing below may proceed. `PyYAML` is not
optional either: the engine reads its YAML state files with it, and without it the verify stops
with a Python error instead of a verdict.

- **What to say:** one short line per check — "ok", or what is missing and the fix the AI proposes.

## I3 — Anchor, verify, install — as the working user

The person hands over ONE link — this mirror — and nothing else. The **anchor fingerprint** is then
fetched by the AI, not by the person: the mirror's own README names the org-profile page
(<https://github.com/yitc-dev/.github>, section **Trust anchor**), the AI reads the anchor FROM THAT
PAGE — an independent repository, never the mirror it is about to check, because an artifact does
not get to certify itself — and then SHOWS the person the page URL and the exact line it took. The
person confirms one thing, in one word: that this is the `yitc-dev` organization page.

Verify and install run **as the working user**, from the directory the clone was made in; the engine
is invoked through the CLONE's own path, because on this machine there is no other copy of it yet.

**Default install layout.** Unless the person wants other places, use two folders in the working
user's home: `<mirror-dir>` = `~/yitc` (the clone of the mirror) and `<engine-dir>` = `~/yitc-engine`
(the installed engine every project runs). Projects live in their own folders beside them, never
inside either.

```bash
git clone <mirror-url> <mirror-dir>
<mirror-dir>/bin/yitc-v2 release verify <mirror-dir> --anchor <fingerprint>
<mirror-dir>/bin/yitc-v2 release install <mirror-dir> --into <engine-dir> --anchor <fingerprint>
```

- **What to check:** `release verify` writes nothing, ever — it is the gate itself. A refused
  `release install` writes NOTHING into `<engine-dir>`. Do not continue past a refusal; re-take the
  anchor from the independent channel and ask the person.
- **Keep the clone.** Do not delete `<mirror-dir>` after the install. An update first keeps the
  release you run today as a worktree BESIDE the clone, then moves the clone forward to the new tag;
  that kept tree, not the clone, is the `--from-release` merge base
  ([`troubleshooting-and-updates.md`](troubleshooting-and-updates.md) §Installing an update, and the
  release notes' «Updating from the previous release»):

  ```bash
  git -C <mirror-dir> worktree add <mirror-dir>-<old-tag> <old-tag>
  git -C <mirror-dir> fetch --tags
  git -C <mirror-dir> checkout <new-tag>
  <mirror-dir>/bin/yitc-v2 release update <mirror-dir> --into <engine-dir> --anchor <fingerprint> --from-release <mirror-dir>-<old-tag>
  ```

  Removing the clone forces a fresh clone at the next update.
- **What to say:** "The package is genuine (its signature matches the one published separately) and
  it is installed."
- **The start command comes with the install.** `release install` also installs, in the person's own
  AI tool, the home-folder command `/yitc-projects` (only if absent — an existing one is left as is),
  and its last output line names it as the next step. Typed in the AI tool opened in the home folder,
  it lists the projects and offers **new project**, which creates the first project in the I4 order.

## I4 — The first project, in a fixed order

The order is fixed: **session start → init → recommended answers → first-scenario interview.**

1. **Session start, then init** — open the AI tool with `<project>` as the working directory
   and run, in this order:

   ```bash
   mkdir -p <project> && cd <project> && git init
   <engine-dir>/bin/yitc-v2 -C <project> session start
   <engine-dir>/bin/yitc-v2 -C <project> init
   ```

   Session start comes first, so everything after it is recorded. `init` needs no worktree — it is
   the sanctioned bootstrap commit. It writes `yitc-ops.yaml`; pin the engine release there under
   `kernel:`:

   ```yaml
   kernel:
     engine: {release_repo: <mirror-dir-absolute>, release: <tag>}
     content: {release: <tag>, answers: <answers-tag-or-~>}
   ```

   `release_repo` is the ABSOLUTE path of the kept clone from I3 — the default `~/yitc` written out
   in full as `/home/<user>/yitc`, with no `~`. It is never the mirror's web address: a URL, a `~`
   path or a relative path is refused, and then every `-C` command for the project stops, `--help`
   included. The pin reads the release tag out of that clone, so the clone must be kept (I3).
2. **Recommended answers.** Where init asks questions, the AI offers the recommended answer for each,
   in plain words, and the person agrees or changes it. An AI has no terminal to answer prompts in,
   so init asks nothing: it prints a **born-permissive block** instead — each concern that starts
   strict, its recommended answer, and the exact `--confirm-born-permissive <section>:<owner>` flag.
   Relay that block to the person, then re-run init with the flags they agree to. Nothing confirmed
   stays strict.
3. **First-scenario interview.** The AI asks the person, in plain words, what the project should do
   for its first user, and writes that down as the first scenario.

- **What to say:** where we are in these four steps, one line each.

## I5 — Install receipt and the first start

- **What to say — the install receipt**, one short plain message:
  - what was installed and where;
  - how to start, restart and come back: the day-two return path from I0, word for word — reattach,
    open the AI tool in any folder (or clear the open session), type the start command, pick the
    project. That is the only order; there is **no restart** after init — the project already started
    through the start command;
  - **keep-alive across disconnects:** if the connection drops, the work must not die with it — the
    AI tool runs inside the kept terminal set up at I2 (`tmux`); reattach with `tmux attach -t yitc`
    after reconnecting (the day-two return path in I0);
  - no secrets in chat (see the privacy note below).
- **What to check — the first start:** after the start command started the project, the session shows
  the visible start line — "Working in YITC mode — project <name>." — and your first message quotes it.
  If that line does not appear, the start did not happen; run the start command again and pick the
  project (inside a project, the fallback phrase "start the project" runs the same start).
- **The install receipt names the start shortcut.** `release install` (I3) — and `init` again — has
  already installed, in the person's own AI tool, the home-folder command `/yitc-projects` (only if
  absent — an existing one is left as is). The receipt names it: typed in the AI tool opened in the
  home folder, it runs the read-only project picker (`<engine-dir>/bin/yitc-v2 session pick`) and then
  that project's session start; its **new project** entry asks the name and runs the I4 order (folder
  and `git init`, session start, then init). It is a shortcut to the same start, not a second way to
  start: no other steps, no second start lifecycle.

## I6 — Auditor offer, after install

Only now, with install done and the first start proven, the AI offers the second provider (the
recommendation from I0).


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

## I7 — First release: host actions wait for the first deploy

Host-level actions — opening **firewall** ports, enabling **linger** (letting the user's services keep
running after logout), choosing and exposing **ports** — are NOT done at install. They are proposed at
the first deploy, when there is a real service to expose, and the person agrees to each one then.

The first release is **two walks, in this order**. The concrete commands are the project's own
(its deploy recipe); this is the order and what the person checks.

### Walk A — an acceptance address you can open from your own browser

First, the result must be visible to the person before anything is called production:

1. The AI deploys the **landed** code (what is on `main`, never a half-done worktree) to a
   **non-production deploy target** — a separate running copy (the sandbox, see
   [`overview.md`](overview.md#the-sandbox)) with its own address.
2. That address is **reachable from outside the server**: the person opens it in the browser on
   their own computer or phone, not only through the server's terminal.
3. The person clicks through the first scenario there and says whether it does what they asked.
   Fixes go through ordinary tasks and land again; the acceptance address follows `main`.

### Walk B — production: domain, DNS, HTTPS

Only after Walk A is accepted:

1. **Domain and DNS.** The person owns (or buys) the domain; the AI says which DNS record to create
   and checks it resolves to the server before going on.
2. **The deploy permission — written by the person, then read back.** The server registry must name
   the working user under `users.<user>:` with that project in `projects:` and the `deploy-code`
   right in `rights:`. The person writes that line **by hand** — never the AI (SPEC-0169). The AI
   then reads it back and shows it; without it deploy is refused as `project-not-scoped`.
3. **Passwordless `sudo nginx -T`.** The host-apply step reads the live web-server configuration with
   `sudo nginx -T` and cannot type a password. The person (or the server administrator) allows that one
   command without a password for the working user; if nobody knows the sudo password, arrange it with
   whoever administers the machine before the deploy.
4. **HTTPS.** The AI sets up the certificate for the domain; the person opens `https://<domain>` in
   their own browser and sees the padlock.

### Before production counts as durable — the off-server recovery set

A production service whose only copy is on one server is one disk failure from gone. Before calling
production done:

- **The recovery set, kept OFF this server:** the **source** (the repository, pushed to a second
  place), the **database** (a regular dump), the **uploads** (files users added), and the
  **configuration** (the project's config files and the web-server site). **Secrets are recovered
  separately** — they are not copied into the recovery set; the person keeps where each one can be
  re-issued (the service that issued it) or a copy in their own password manager.
- **One restore, for real:** restore the recovery set once onto a **replacement server** (a fresh
  machine, or a scratch one) and open the result. Until one restore has worked, the backup is a hope,
  not a recovery set.

## What you may run into on a clean machine and what to do

This section is for the agent. Each item is a stumble a real first day met (field study, 2026-10-02),
with the right move. None of it is a new step: the stages above stay the order.

- **Two start orders.** Give the person ONE order, always the day-two return path in I0: open the AI
  tool in any folder (or clear the session already open), type the start command, pick the project.
  Never tell them to relaunch the tool in the project folder, and do not ask for a separate restart
  after init. The per-tool clear and start commands are in the AI-tool list `bin/ai-tools.yaml`
  (`clear_session`, `invoke`) — read the person's tool there instead of guessing.
- **Git name and email.** Ask for the git identity at I2, with the other checks — not later, when the
  first project is created and a commit would stop on it.
- **An existing tmux session.** If `tmux ls` already shows a session of the person's (for example
  `main`), reuse it instead of making a second one: say its name, and use its name in place of `yitc`
  in every reattach line you give them.
- **The second-provider auditor.** Test it with a question whose answer cannot be guessed (one it must read a
  file to answer), never with a trivial smoke that answers GREEN without reading. On stock Ubuntu
  24.04 an auditor that sandboxes with bubblewrap fails because the system has none: say the plain cause and give the fix
  for the person to run in their own terminal — `sudo apt install bubblewrap` — because sudo does not
  work from the chat and you never ask for a password in chat.
- **Reading the handbook.** Read each handbook file whole — page through a long file to its end, never
  stop at the first part — and scan `--help` right after `session start`, not later in the session.
- **Asking questions.** Ask in plain text, in the person's language, never a form or a set of buttons.
- **A secret pasted into the chat.** Treat it as leaked: say so plainly, have the person revoke or
  rotate it at its issuer, then hand the new one over the safe way (§Secrets — how to hand one over
  safely). Never repeat it back.
- **The start line.** Quote it exactly as `session start` printed it — "Working in YITC mode — project
  <name>." — in your first message after the start.

## Privacy note

After install, the chat with the AI is **journaled** — recorded in the project's history so work can be
resumed and checked. So: **no secrets in chat** — no passwords, keys or tokens. Secrets go in by the
safe hand-over below, never into the conversation.

## Secrets — how to hand one over safely

The AI names WHERE a secret goes; the person puts it there. Two safe ways:

1. **A hidden prompt.** The AI gives a command that reads the value without showing it and writes it
   to the file, e.g. `read -rs VALUE && printf '%s' "$VALUE" > <secret-file> && unset VALUE` — the
   person pastes the secret into the terminal (not the chat); nothing is echoed.
2. **A server-side secret file, outside the repository.** The person creates the file the AI names
   (for example under `~/secrets/`, never inside the project folder, so it can never be committed),
   and restricts it: `chmod 600 <secret-file>`.

**Verify without echoing.** The AI checks the secret arrived by its LENGTH and permissions only —
`wc -c <secret-file>` and `ls -l <secret-file>` — never by printing it.

**If a secret was pasted into the chat by accident:** treat it as leaked. First **revoke or rotate it
at the service that issued it** (make a new one, disable the old one), then put the new one in by the
safe hand-over. Removing it from the chat history comes after, and the journal's automatic redaction
of credential shapes is only a backstop — it can miss a shape, and it never un-leaks a value.

When the person asks what this system is, how a working day looks, how projects are made, or what
the sandbox is, the answer is [`overview.md`](overview.md) — read it and voice it in their language.
