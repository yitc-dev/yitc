---
name: verify-venue-when-it-pays
class: runbook
sourced_from: SPEC-0203 (the remote verify venue) rules 2 + 6, made an OPTIONAL adopter capability by (owner decision events.jsonl#ts=). The costs quoted are the ones `patterns/compute-controller-session.md` measured; none is restated as a rule here.
applies_to: deciding whether a project needs the remote verify venue at all, and switching it on when it does
cites:
  - SPEC-0203
---

# The verify venue — when it pays, and how to switch it on

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

## Without it

Nothing changes. `land` and `task test --run` verify locally; a record left behind on a machine with no
binding is ignored. The venue changes WHERE checks run, never whether they pass.
