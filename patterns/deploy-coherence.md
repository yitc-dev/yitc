---
name: deploy-coherence
class: discipline
sourced_from: decisions/runtime-delivery-fleet-standard-audit-adhoc.yaml (GREEN, owner-ratified 2026-07-16) + decisions/x0448-restart-coherence-fork-audit-adhoc.yaml (GREEN, owner-ratified 2026-07-16) + X-0367 (coherence guard) + X-0370 (half-deploy outage) + X-0448 (boomrocket restart crash-loop)
applies_to: any Docker consumer whose runtime_delivery is source-mounted / hot-reload / hybrid (a BYPASSABLE model, SPEC-0093 rule 22) — i.e. the code that runs is NOT a deploy-time-baked artifact. Read when a restart-after-land crash-loops, when splitting dev vs prod compose, or when planning a migration to an image-baked runtime.
---

# Deploy-coherence — the mounted-runtime doctrine (traveling pattern)

> **Doctrine (normative home: SPEC-0093 rule 22).** Image-baked is the normative production
> default for Docker consumers. A source-mounted / hot-reload / hybrid PROD runtime survives only
> as an explicit WAIVER off that default, naming its compensating controls: (1) the
> `runtime_delivery` declaration, (2) X-0367 coherence-guard coverage, (3) a documented restart /
> recovery procedure. This doc is that documented procedure — so every hybrid consumer stops
> re-deriving it (X-0448 asked exactly this).

## Basis

Two GREEN owner-ratified consults (2026-07-16) settle the doctrine — cited, not re-derived here:

- `decisions/runtime-delivery-fleet-standard-audit-adhoc.yaml` — **image-baked = normative prod
  default** for Docker consumers; bypassable prod runtimes are explicit waivers with named
  compensating controls. Prescribes the aiseller dev/prod compose split as the standard shape and a
  measure-first migration for boomrocket.
- `decisions/x0448-restart-coherence-fork-audit-adhoc.yaml` — for today's bind-mounted runtime the
  X-0367 restart-coherence guard's **fail-closed REFUSE is the INTENDED failure mode** (option 2, a
  fall-back-to-last-deployed-code path, has no real target because last-deployed code is not
  materialized under a bind mount); the structural snapshot-runtime fix is filed SEPARATELY.

Real incidents behind it: X-0367 (the coherence guard), X-0370 (a container recreate shipped HALF a
paired change → 8h outage), X-0448 (a hybrid consumer with a hot fleet — 31 lands / 35 min —
crash-looped on the guard when `restart: unless-stopped` re-ran a restart while `main` had drifted
past `.deploy-state/deployed-code-hash`).

## 1. Fail-closed intent — the restart REFUSE is the feature, not the bug

On a bind-mounted / hybrid runtime the container runs the SOURCE TREE, so any `docker compose up` /
recreate / daemon restart ships whatever sits on `main` — with no deploy gate, no class check, no
`deploy_completed`. The X-0367/SPEC-0050 code-coherence guard closes that hole: on start it compares
the checked-out code hash against `.deploy-state/deployed-code-hash`; if `main` has DRIFTED past the
last governed deploy, the guard **REFUSES to start (exit 3)**.

That refuse is the INTENDED failure mode, not a defect to soften. It preserves X-0367's
never-half-deploy semantics: a service that is DOWN is safer than a service silently serving
undeployed drift (the Class-S down-safer-than-exposed posture — partial precedent; here it also
carries an availability-regression dimension from ordinary post-land restarts). Do NOT "fix" the
crash-loop by weakening the guard, adding `--no-verify`, or falling back to live drift. Under a
bind mount there is no materialized last-deployed artifact to fall back TO, so a fallback would
either serve drift or require building the snapshot construct first (the separate structural fix).

## 2. One-command recovery — re-pin the deployed-code-hash

When a restart is refused because `main` drifted, the recovery is a single governed action: **re-run
the project's governed deploy** for the current `main`. That re-pins `.deploy-state/deployed-code-hash`
to the now-checked-out revision (emitting `deploy_completed{revision}`), so the coherence guard's next
start comparison passes and the container comes up on coherent code.

```
# refused-to-start container after a land drifted main:
bin/yitc-v2 -C <consumer> deploy # re-pins deployed-code-hash to current main → guard passes
```

There is no per-project fork and no manual hash editing: the governed deploy verb is the ONE writer of
the deployed-code-hash, and re-running it is the whole recovery. (A hot fleet that lands frequently
should expect to re-pin after a batch, or move to image-baked per §4 to remove the drift window.)

## 3. Dev/prod compose split — the aiseller worked example

Keep bind mounts OUT of the production compose. The prescribed standard shape (aiseller):

- **`docker-compose.yml`** — the clean PROD compose. Services run the BAKED image; no source bind
  mounts of executable code. This is what a governed deploy brings up.
- **`docker-compose.dev.yaml`** — the DEV overlay. Source bind mounts, hot-reload, and any
  developer-only conveniences live HERE, layered on top for local work only:

```
# dev (mounts + reload):
docker compose -f docker-compose.yml -f docker-compose.dev.yaml up

# prod (baked image, no mounts):
docker compose -f docker-compose.yml up -d
```

The split means prod NEVER accidentally ships a bind-mounted source tree, while developers keep the
fast mount/reload loop. A hybrid prod runtime that cannot yet make this split is exactly the case that
needs the §1 guard coverage + this documented recovery as its waiver's compensating controls.

**Once you have made the split, the kernel reads it (X-0711).** The report-only source-mount
detector behind SPEC-0119 rule 16 draws its claim ONLY from the compose that runs in production, so the
dev overlay's mounts are silent — a project that did the split is not nagged, and, more importantly, is
never told the opposite of its own truth. aiseller was: every one of its 8 evidence rows came from
`docker-compose.dev.yaml` under a headline asserting it bind-mounts its source into 8 running services,
which steered its owner toward declaring the INVERSE runtime-delivery model.

Which compose counts as production is decided **declaration-first**: the `-f` / `--file` operands of your
`deploy.command` in `yitc-ops.yaml` (the prod line above — `docker compose -f docker-compose.yml up -d`)
ARE the production set — whatever they are named (`stack.deploy.yml` reads fine; what is checked is that
the file exists, not that its name looks compose-shaped). If your files are named something other than the
convention below, that declaration is how you say so — no extra field to fill in. Only when the deploy command names no compose
file does the kernel fall back to the filename convention (`dev` / `development` / `override` / `local`
segment = dev overlay; anything else reads PROD, because a false nag is correctable and a false silence
is not). Every reported row names the compose file it came from, so the claim can be checked, not trusted.

## 4. Migration shape — measure first, snapshot only on evidence

The target for a bypassable prod consumer (e.g. boomrocket) is to **bake the backend image with
Docker layer-cache optimization** — the ordinary path that makes the deploy verb the sole path to
prod again and removes the drift window entirely.

Do NOT reach for custom snapshot-mount machinery by default. The measure-first rule:

1. **Measure** the layer-cache-optimized image build time on the real project first (order deps →
   copy source last, so a code-only change rebuilds only the top layer).
2. If the measured build time is acceptable → migrate to `runtime_delivery: image-baked`, drop the
   prod bind mount, done.
3. **Only** if measured evidence proves the bake incompatible (build too slow to sustain the land
   tempo, or a genuine reason the artifact cannot be baked) does a custom snapshot-mounted runtime
   construct become justified — and that is a SEPARATE kernel design seed (an immutable code snapshot
   materialized at deploy, mounted read-only, restarts reproducing the deployed hash despite main
   drift), never a per-project fork under incident pressure.

No new gate ships with this doctrine: the report-only debt surface stays SPEC-0119 rule 16, and the
init/debt report-only advisory for an executable-code prod mount is the separate follow-up.
