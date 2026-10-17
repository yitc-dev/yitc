---
name: verify-venue-when-it-pays
class: runbook
sourced_from: <workshop-spec> (the remote verify venue) rules 2 + 6, made an OPTIONAL adopter capability by (owner decision events.jsonl#ts=). The costs quoted are the ones `patterns/compute-controller-session.md` measured; none is restated as a rule here.
applies_to: deciding whether a project needs the remote verify venue at all, and switching it on when it does
cites:
  - <workshop-spec>
  - SPEC-1032
  - SPEC-0208
---

# The verify venue — when it pays, and how to switch it on

> **Catalog.** This page is one source of `patterns/verify-cost-playbook.md`, which lists every verify-cost
> technique with its measured case — read it there when choosing what to cut.

> **Plainly.** The venue is a separate, rented computer that runs your project's test checks. It is
> **optional**. Without it — the default for every new install — every check runs on your own
> machine, exactly as before. Most projects never need it.

## Who needs it

- Your full check suite takes long enough on your machine that waiting for it slows your work down,
  **and** you run many checks a day (several parallel sessions, frequent lands).
- Your machine is small or shared, so running the suite also makes everything else on it crawl.

If neither is true, stop here — do not switch it on.

## What it costs

- **Money:** the box is rented by the hour from a cloud provider, and a started hour is billed whole.
  It is raised for a working window and deleted when nothing is left running; a stored snapshot of the
  box costs a little per month.
- **Time:** raising a box from the snapshot takes about a minute; refreshing the snapshot at teardown
  takes about seven.
- **Attention:** one extra session owns the box for the window — raise, publish, watch, delete
  (`patterns/compute-controller-session.md`).

## How to switch it on

1. Write a provider binding file, `bin/venue-config.yaml`, with six keys: `provider`, `api_base`,
   `token_secret`, `server_type`, `location`, `ssh_key` (the file itself documents them). It is never
   shipped in a release, so each install writes its own. The token goes in your secrets dir under the
   file name `token_secret` names — never in the binding.
2. Prepare a box snapshot with the engine's test dependencies, and record it: `bin/yitc-v2 venue seed`.
3. For a working window: `bin/yitc-v2 venue raise`, then `bin/yitc-v2 venue publish`. Delete the box
   with `bin/yitc-v2 venue delete` when the window ends.

`bin/yitc-v2 venue show` tells you where you stand. With no binding it says the venue is optional and
not configured — that is a normal state, not an error, and it exits 0.

## For a project that adopted the engine — its own Stage-6 passes on its own box

The steps above put the engine's own checks on a box. A project that adopted the engine can send its
OWN Stage-6 passes (`task test --run`) to a box published for it; its lands still verify on its own
machine. The rules are SPEC-1032 (`bin/yitc-v2 graph query --kernel SPEC-1032`); the steps, on the
project's machine:

1. **Declare it.** In the project's `yitc-ops.yaml`, inside its `verify` section, add a
   `verify.venue` mapping: `stage6: on`, and under `environment` the checks the box must pass — each a
   `name`, a `cmd` run on the box, and the exact output it must print as `expect` (a font list, a tool
   version). A project that declares nothing sees no change. The binding file `bin/venue-config.yaml`
   stays where it is: the image build and the engine identity read past it, as they read past a root
   `events.jsonl` and `.yitc/` in your install.
2. **Build the box image:** `bin/yitc-v2 venue seed --build -C <project> --provision <script>`. Your
   script installs what your checks need (warm package caches, browsers, fonts); the build pushes a
   full-history clone, puts the engine release at the path it runs from on your machine, snapshots the
   box and records the image. Use a separate provider project with its own token: a provider token
   reaches the whole provider project.
3. **Raise and publish it for the project:** `bin/yitc-v2 venue raise`, then
   `bin/yitc-v2 venue publish -C <project>`. Publish refuses a box without atomic admission (`flock`),
   a shallow clone or a failing declared check, naming it, and records which repository the box
   serves. While it is published, the engine's own passes on that machine run locally.
4. **Set how many passes share the box.** A pass alone has the whole box; one runs at a time until
   you set `YITC_VENUE_STAGE6_MAX_CONCURRENT` on that machine
   (`bin/yitc-v2 config set YITC_VENUE_STAGE6_MAX_CONCURRENT <n>`). Measure what pays before you raise it.
   To have passes that run together share the box instead of each taking all of it, add
   `width: per-live-pass` to the `verify.venue` mapping: a pass admitted alone still gets every thread,
   one admitted beside other live passes gets the thread count divided among them. `width: whole`, or
   no `width`, keeps the whole box for every pass.
5. **Keep a pass at home when you need to:** `task test --run --placement local`.
   `bin/yitc-v2 venue show --leases` lists the passes admitted on the box. A layer with a deciding
   selection or credit whose `list` finds no unit on the box while it finds some on your machine (for
   example one that runs only under an environment variable of your machine) is named on the Stage-6
   row, and its land does not take that layer's verdict from the pass. Any other layer gated that way
   is not detected; run such a card with `--placement local`.

**The layer timeouts are not calibrated for the box.** They were set on your own machine; measure
them on the box under SPEC-0208 (its tuple, at the most passes you admit at once) before trusting a
timeout there.

## Without it

Nothing changes. `land` and `task test --run` verify locally; a record left behind on a machine with no
binding is ignored. The venue changes WHERE checks run, never whether they pass.
