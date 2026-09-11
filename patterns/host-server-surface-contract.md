---
name: host-server-surface-contract
class: reference
sourced_from: <durable artifact> (document the kernel's host/server surface contract) + SPEC-0084 (coordination store authority) (V2 self-contained isolation — global host surfaces non-normative read-only provenance) (scope-boundary — territorial ownership) + patterns/onboarding-onto-yitc-runbook.md (the scattered prior-art these surfaces were noted in)
applies_to: working cleanly with the CURRENT server's host/kernel surfaces — read before maintaining/correcting registry.yaml, the <host-home> router, the host auto-committer, or the kernel-owned coordination store. The steady-state companion to the migration-focused onboarding runbook.
---

# Host/server surface contract — how to work cleanly with the CURRENT server's surfaces

> **What this is, in one line:** a single map of every server-level surface the kernel touches on
> THIS server — who OWNS each (kernel-owned vs host-owned/host-read), and how to work with / maintain
> / correct it NOW. It is a REFERENCE doc (a `pattern` graph node), not a new mechanism: it documents
> contracts that already exist, scattered across SPEC-0084, and the onboarding runbook.
>
> **Scope bound (anti-complexity — CHARTER §P1):** this documents the CURRENT server only. No
> installer script, no kernel-side project table, no new registry mechanism — clean-server AUTOMATION
> stays deferred to the distribution umbrella (`umbrella-contract-first-yitc-distribution-and-firs`).

## The ownership model in one paragraph (read this first)

V2 distinguishes ownership by **territory, not topic** : "it relates to the kernel" ≠ "the
kernel owns/edits it". Two ownership classes cover every server surface below:

- **kernel-owned** — the kernel governs its existence, schema, and maintenance. Today exactly ONE
  server-level surface is kernel-owned: the **shared coordination store** (SPEC-0084).
- **host-owned / host-read** — lives in **external territory** (`realpath` outside
  `<repo-root>/`): the `<host-home>` monorepo, `~/<provider-config>/`, `<host-home>/bin/`,
  `registry.yaml`. The kernel **reads** these as **non-normative read-only provenance** and
  NEVER edits them from a V2 Build session — a correction routes through the host's own mechanism
  (the auto-committer) or an owner-confirmed host edit, never a hand-commit of the monorepo.

## Surface map (the ≥4 server surfaces)

| # | Surface | Path | Owner | How the kernel relates |
|---|---|---|---|---|
| 1 | **Coordination store** | `<host-home>/.yitc-coordination/coordination.jsonl` | **kernel-owned** (SPEC-0084 r1) | The kernel governs it: created on first `cross` write, appended via the `cross` verbs, backed up + rotated by kernel tooling. |
| 2 | **Project registry** | `<host-home>/registry.yaml` | **host-read** | A non-normative HOST inventory. The kernel only READS it via the router + `/start` skill + the v2 nightly enumerator — `bin/yitc-v2` itself reads it ONLY for `nightly` (`REGISTRY_PATH`). The kernel never sets it up as truth. |
| 3 | **Router** | `<host-home>/<vendor-adapter>.md` + `~/<provider-config>/commands/yitc.md` | **host-owned** | The thin global router that `cd`s into the kernel and hands off to the project-local `/yitc` skill. Read-only provenance; the canonical protocol is the kernel's own `AGENTS.md` + `<provider-config>/commands/yitc.md`. |
| 4 | **Host auto-committer** | `<host-home>` monorepo (`chore(auto):` commits) | **host-owned** | Commits host-config edits (e.g. `registry.yaml`) on the `<host-home>` monorepo. The kernel never hand-commits the monorepo; host-config edits RIDE this committer. |

## 1. Coordination store — `<host-home>/.yitc-coordination/coordination.jsonl` (kernel-owned)

**What it is.** The single shared, append-only cross-project coordination log — every project (the
kernel + each `-C` consumer) appends to and reads the ONE instance instead of N per-repo
`CROSS-TASKS.md` files. It is the canonical SOURCE OF TRUTH for cross-project coordination state (the
status of an item = the fold of its events by id), NOT a disposable cache. Authority home: **SPEC-0084**
(`bin/yitc-v2 graph query SPEC-0084`); event FSM/protocol: SPEC-0085; the `cross` verbs: SPEC-0086.

**Where it lives.** ONE fixed absolute path — `<host-home>/.yitc-coordination/coordination.jsonl` —
OUTSIDE every project repo (neutral coordination infrastructure belonging to no repo) and, crucially,
IDENTICAL FOR EVERY OS USER. It is deliberately NOT `$HOME`-derived: a per-home default gives each
collaborator their own empty store, so inbound items are invisible, outbound requests never arrive,
and the two stores mint colliding ids (X-0663). The path is owner-tunable infra config via
the `YITC_CROSS_LOG` env var; the ONE code home that resolves it is `cross.resolve_log_path`
(`bin/lib/cross.py`), which `CROSS_LOG_PATH` in `bin/yitc-v2`, `bin/verify-backup.sh` and the
migration utility all delegate to. The directory also holds `backups/` and a `.coordination-id.lock`.

**Multi-user appendability.** Several OS users append to this ONE file, so the modes are part of the
contract, not incidental: the directory is `2775` (setgid, so a row created by any peer inherits the
store's group) and the store + lock are `0664`. `cross.ensure_shared_store` asserts this on every
write path, so a store touched under a restrictive umask cannot lock a peer out (the X-0226 class,
one layer up).

**How it is created.** There is no separate "create the store" step — it is born lazily on the first
governed `cross` append (the `cross` verbs create the file + parent dir on first write). Appending is
territory-IN-BOUNDS from any session (SPEC-0084 r5) and rides the no-worktree journal-append path
 — `bin/yitc-v2 cross request...` from anywhere, including the main checkout.

**How it is maintained / backed up.**
- **Backup + round-trip verification:** `bin/yitc-v2`'s `BACKUP_VERIFY_SH` → `bin/verify-backup.sh`
  takes a lock-safe timestamped snapshot into `<host-home>/.yitc-coordination/backups/`, then restores it into a
  fresh location and asserts the recovered status-fold is identical (a disaster-recovery simulation).
  Exit 0 = OK; exit 1 = failure. The canonical home is under `<host-home>/`, which `offsite-backup.sh` §3
  already rsyncs offsite every 4h — so the store is offsite-backed WITHOUT touching that host script.
  That is also WHY the store may not simply be relocated to an FHS-neutral path: `offsite-backup.sh` is
  external read-only territory, so moving the store would silently drop the backup SPEC-0084
  rule 3 requires.
  Retention: last 42 snapshots (`YITC_CROSS_BACKUP_RETAIN`, 7d × 6/day). The v2 nightly runs this
  round-trip once per run.
- **Rotation/archival:** the KERNEL ONLY rotates the store (a non-append rewrite moving terminal+old
  entries to an archive sibling) — a single archivist avoids the contention a concurrent rewrite would
  cause; appends stay concurrent-safe for everyone (SPEC-0084 r3, mechanics in SPEC-0085).

**How to correct it.** It is the SAME journal mechanism as `events.jsonl` (one format, one parser,
append + union-merge — the CHARTER §P5 one-journal amendment, a permitted SECOND INSTANCE). Read it
through the same journal parser via the `cross` fold verbs (`cross inbox` / `cross outbox`); never
hand-edit lines (append-only + union-merged). A genuine corruption is recovered from `backups/` via
the `verify-backup.sh` round-trip path.

## 2. `registry.yaml` — `<host-home>/registry.yaml` (host-read, non-normative)

**What it is.** The host's single project inventory: project metadata, paths, Team-Mode config, and
the `methodology:` field (`legacy | yitc | yitc_v2`) that routes each project. It is a **HOST**
artifact in external territory.

**The distinction (keep this crisp).** `registry.yaml` is a **non-normative HOST inventory the
kernel only READS via the router + `/start` + the v2 nightly** — the kernel never authors it as truth.
Contrast surface #1: the **coordination store is the kernel-OWNED** surface (the kernel governs its
existence and schema). `bin/yitc-v2` reads the registry ONLY for the `nightly` enumerator
(`REGISTRY_PATH`, env-tunable via `YITC_REGISTRY`); every other kernel use is mediated by the router.

**How to work with it.** A migrated consumer is made visible by setting `methodology: yitc_v2`
(underscore — the canonical family token; the dir uses the hyphen) on its registry entry. That flip is
LIVE-derived by `/start` and the v2 nightly (no further edit needed). Note: `methodology: yitc_v2`
ALSO excludes the consumer from all v1 machinery (the v1 enumerators skip it).

**How to correct it.** It is host territory — the kernel does NOT edit it from a V2 Build session. A
registry change is a host-config edit that rides the **host auto-committer** (surface #4): make the
edit and let the `chore(auto):` committer land it; never hand-commit the `<host-home>` monorepo (it
carries the owner's other pending changes).

## 3. The router — `<host-home>/<vendor-adapter>.md` + `~/<provider-config>/commands/yitc.md` (host-owned)

**What it is.** The thin global entry layer. `<host-home>/<vendor-adapter>.md` is a STRICT router (project-select +
routing + language + cross-project safety + owner prefs + pointers — never a notepad). `~/<provider-config>/
commands/yitc.md` is a 2-step pointer that `cd`s into the kernel and reads the project-local
`/yitc` skill verbatim.

**The distinction.** These are **non-normative read-only provenance** to the kernel — the
canonical V2 protocol lives single-SoT in `<v2>/<provider-config>/commands/yitc.md` + `AGENTS.md`. A V2 session
that has `cd`-ed into the kernel treats the global router as read-only.

**How to correct it.** Host territory — not edited from a V2 Build session. A router change is an
owner/host concern; if a routing defect is found during a kernel session, route it (a `cross request`
or surface it to the owner), don't edit `<host-home>/<vendor-adapter>.md` from inside the kernel repo.

## 4. Host auto-committer — `<host-home>` monorepo `chore(auto):` commits (host-owned)

**What it is.** The `<host-home>` monorepo carries a host auto-committer that produces `chore(auto):...`
commits (e.g. `chore(auto): update registry.yaml`). It is the host's OWN commit mechanism for
host-config drift.

**Why it matters to the kernel.** Host-config edits the kernel's surfaces depend on — notably
`registry.yaml` (#2) and the host `bin/` scripts (`offsite-backup.sh`, `session-scope-guard.sh`) — land
via THIS committer, NOT by hand. The rule (the onboarding runbook §B0 lesson): **a host
project's config edits land via the host's own commit mechanism; never hand-commit the monorepo.**

**How to correct it.** External territory — the kernel never edits/operates the committer. Treat its
output (`chore(auto):` commits) as the expected landing path for host-config changes.

## 5. Verify temp base — `YITC_VERIFY_TMPDIR` (host-read, opt-in PER INVOCATION)

**What it is.**. An environment variable read by
`bin/lib/verify_runner.py#_install_verify_tmpdir`. UNSET (the default, and what every other host and
every consumer sees) it does nothing at all. SET, it points the verify run's temp base at that root,
so BOTH the per-run hermetic sandbox `mkdtemp` AND the SPEC-0132 Rule 1 disk/inode `statvfs`
(`tempfile.gettempdir`) measure the SAME filesystem. It adds NO gate: a root too small for one
worker surfaces as the EXISTING Rule 1 headroom refusal, and an absent/unwritable root falls back to
the platform default with one reported line.

**Where it is set on THIS server, and why not anywhere more permanent.** `/dev/shm` here is a 62 GB
tmpfs (`rw,nosuid,nodev`, NOT `noexec`), usable as-is — no mount, no fstab, no host-config change.
The adoption is therefore a PER-INVOCATION export on the land / `task test` command:

```
YITC_VERIFY_TMPDIR=/dev/shm/yitc-verify bin/yitc-v2 land --task T-XXXX
YITC_VERIFY_TMPDIR=/dev/shm/yitc-verify bin/yitc-v2 task test T-XXXX --run
```

It is deliberately NOT pinned machine-wide. Two reasons, both structural: (a) a shell profile is
host-owned territory a V2 Build session does not edit (§the ownership model above); (b) the knob is
inventoried **GATE**-class in `bin/lib/machine_settings.py#INVENTORY` — because the filesystem it
selects feeds the SPEC-0132 admission refusal — and a GATE-class value is refused hard from the
machine settings file, so `config set` is not a route for it by design.

**Measured on this host (full 1390-file suite, 1390 of 1390, same tree, two PAIRED
repetitions run back-to-back in OPPOSITE orders so the sign is not an ordering artifact):**
445.47s unset → 421.77s on tmpfs (−5.3%), and 405.83s unset → 334.48s on tmpfs (−17.6%). Both legs of
both pairs green. Host load moves the absolute walls, which is why two pairs are reported and not one.
Peak run-root footprint 1665 MB against a MemAvailable-derived SPEC-0132 Rule-1 bound of ~165 workers
(ceiling 13), so the RAM cost does not move the bound. After each tmpfs leg `/dev/shm/yitc-verify` is
EMPTY and `df /dev/shm` is back at its pre-run baseline — nothing persists.

**One thing it deliberately does NOT move.** The cross-land SPEC-0132 admission slot pool
(`worktree._verify_slot_dir` + its nightly twin) hangs off `events.pre_lever_temp_base`, i.e. the
temp base as it stood BEFORE the lever installed. Two lands of the same repo must resolve the SAME
pool or each believes it holds slot 0 and the concurrency bound is silently broken — so a land WITH
the lever and a land WITHOUT it stay on one pool. The lever is likewise scrubbed from the hermetic
per-test child env, so a per-test box keeps the private TMPDIR SPEC-0131 Rule 1 gives it.

## Where this sits relative to the onboarding runbook

The migration-focused `patterns/onboarding-onto-yitc-runbook.md` touches several of these surfaces in
its frictions (registry flip, the `<host-home>` auto-committer, host path-coupling). THIS doc is the
steady-state COMPANION: it answers "how do I work with the current server's surfaces cleanly NOW",
where the runbook answers "how do I onboard a NEW project". The runbook §Shared core points here.
