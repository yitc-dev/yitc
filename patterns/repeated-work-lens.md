---
name: repeated-work-lens
class: discipline
sourced_from: read-only repeated-work audits of two consumer products, 2026-09-04 — kupiclub (cross X-1255) + aiseller (cross X-1256); 10 HIGH findings in one pass
applies_to: TWO moments — (1) DETECTION, the recurring `repeated-work` sweep over a project's own product code (declared in `yitc-ops.yaml` `inspection.themes[]`, recorded via `inspect record --theme repeated-work`); (2) PREVENTION, at a task's Plan stage when the change adds a read, a loop, a poll or a fetch
---

# The repeated-work lens — the seven classes of doing the same work twice

## Problem

AI-authored code systematically produces repeated work. Each function is written self-contained:
it fetches what it needs, loops over what it was given, and returns. Read alone, every one of them
is correct and cheap. Composed — a handler that calls it per row, a nightly sync that calls it per
item, a component that mounts it per navigation — the same read runs N times, the same page is
re-fetched, the same already-processed rows are re-scanned forever.

Nothing catches this. Tests pass (the results are right). Review passes (each function is fine).
The cost is invisible until a table grows or a customer's payload gets large, and by then it is
spread across a dozen files that each look reasonable. Two read-only audits on 2026-09-04 found
**10 HIGH findings across two products in a single pass** — including a retention sweep whose
scanned set grows forever and a nightly sync issuing ~56k avoidable SELECTs per cabinet.

This is a **class**, not a set of bugs. A class needs a lens on a cadence, not another one-off
audit. And a hand-written checklist pasted into each project's request diverges the moment the
second project is asked.

## Solution

**This document is the single home of the lens.** A project declares it as a recurring sweep theme
and runs it against the seven classes below; a spec or a seed may POINT here, but never restates
the classes (CHARTER §Principle 5).

### Two uses — the same seven classes, at two different moments

**1. DETECTION — the recurring sweep (the standing use).** The project declares a `repeated-work`
theme in its `yitc-ops.yaml` `inspection.themes[]` (the snippet in §Example is ready to paste), runs
it by hand on cadence, and records the run with
`bin/yitc-v2 -C <repo> inspect record --theme repeated-work`. Recording is what makes the cadence
real: the SPEC-0119 rule-10 review-due semaphore folds consumer-declared themes and surfaces this one
in the session-start debt echo once it is past its own cadence tier AND substantive work has landed
since the last run — activity-gated, so a quiet month never nags. Manual-first is unchanged
(SPEC-0057 §2): running the sweep and recording it IS the mechanism. There is no runner, no cron, no
classifier, no second finding sink.

**2. PREVENTION — the Plan-stage cue (cheaper than any sweep).** When a task's plan adds **a read, a
loop, a poll, or a fetch**, answer one question before writing it:

> **Which NEIGHBOURING mechanism at this same seam already folds, caches, batches or watermarks this
> — and what am I reusing from it?**

Name it, or say plainly that none exists. Almost every finding in the two audits had its own remedy
already present a few lines or one file away: aiseller's `sync_inventory.py` builds a
`barcode_to_size` map at line 129 for the stocks path while the orders path two functions up queries
per row (X-1256 #5); its Ozon gateway does the cursor-advanced check and page cap (`ozon_inventory.py:115-117`)
that the WB gateway's `while True` lacks (X-1256 #8). The prevention question is only "look at your
neighbour" — a **cue held while planning**, not a gate. (This is the product-code counterpart of the
kernel-side read contract for composed seams, being designed in plan
`read-contract-for-composed-seams-and-a-quiet-lane-`; that one is measured by kernel counters, which
product code does not have — so on this side the lens is hand-run by construction.)

### Severity rubric (one rubric, all seven classes)

| Severity | Meaning |
|---|---|
| **HIGH** | on a production hot path (per request / per page view / per tick), OR **unbounded** — the repeated work grows with the data or never terminates |
| **MEDIUM** | wasteful but bounded — a background job, an admin path, or a loop with a known small ceiling |
| **LOW** | cosmetic — measurable but not on any path anyone waits for |

"Unbounded" beats "not hot": a nightly sweep whose scanned set grows forever is HIGH even though
nobody is watching it, because its cost has no ceiling.

### The seven classes

#### 1. N+1 database queries in a loop

- **Detect:** a query call inside a `for`/`while`, inside a list comprehension, or inside a function
  the caller invokes per row — `.filter.first`, `db.get(Model, id)`, `SELECT... WHERE id = %s`.
  Grep for a query primitive and read one screen upward for the enclosing loop. Also look for a
  **lazy attribute access** on a relation the base query joined but did not select — same N+1 with no
  visible query call.
- **Severity:** HIGH when the loop is in a request handler or the row count follows external data;
  MEDIUM in a bounded background sync.
- **Remedy shape:** one bulk load keyed by id (`WHERE id = ANY(%s)` / `.in_(ids)`), or select the
  entities the base query already joins (`contains_eager` / `joinedload`); build a dict once and look
  up in the loop.
- **Example (HIGH):** `backend/app/api/routers/reviews.py:157-158` (aiseller, X-1256 #3) — per row
  `db.get(Listing, r.listing_id)` then `db.get(Product, listing.product_id)`, with `limit` up to 1000,
  **although the base query at :84-86 already joins Listing and Product**: up to 2000 extra SELECTs per
  request for rows already in hand.

#### 2. The same file / config / secret / row re-read per request or per iteration

- **Detect:** an `open` / `yaml.safe_load` / `json.loads` / secret fetch / single-row lookup inside a
  request handler or a loop body, where the source changes far more slowly than the caller runs. Ask
  "how often does this file actually change, and how often do we read it?"
- **Severity:** HIGH on a hot path or when the read is a network/secret round-trip; LOW-MEDIUM for an
  occasional endpoint.
- **Remedy shape:** read once into module state and validate with an mtime check (or a small TTL);
  for a per-request row, resolve it once per request rather than per use.
- **Example (LOW):** `app/main.py:282-286` (kupiclub, X-1255 #14) — `/health` re-opens and
  `json.loads` the deploy-facts file on **every probe**; remedy is an mtime check.
- **Example (MEDIUM, the connection variant):** `app/db.py:26` (kupiclub, X-1255 #6) — a fresh
  database connection per HTTP request including the most-hit redirect path (`main.py:831`), with no
  pool anywhere in the compose/deploy stack.

#### 3. The same remote resource re-fetched, or pagination that restarts

- **Detect:** two call sites fetching the same upstream resource in one request or one job; a new HTTP
  client constructed per call (a fresh TLS handshake each time), especially **inside a retry loop**; a
  paginator that re-reads its own page count from each response.
- **Severity:** HIGH when a retry loop multiplies it or when the fetch is per row; MEDIUM for a
  bounded per-job repeat.
- **Remedy shape:** cache per request (or per process for a long-lived client); one long-lived HTTP
  client per gateway; a cursor-advanced check plus a hard page cap (see class 4).
- **Example (LOW-MEDIUM):** `backend/app/gateways/marketplace/wb_base.py:398` (aiseller, X-1256 #17) —
  a **new `httpx.AsyncClient` per HTTP call**, constructed INSIDE `for attempt in range(MAX_RETRIES)`,
  so every retry re-handshakes; the same shape repeats across seven gateway modules.
- **Example (MEDIUM):** `backend/app/tasks/pipeline_supplies.py:98,113` (aiseller, X-1256 #11) — two
  serial remote calls per supply, unbatched, at a ~1 s throttle.

#### 4. Unbounded loops, retries and polls

- **Detect:** `while True` / `while page <= pages` / a shell `while true; do … sleep N; done` /
  `setTimeout(tick, …)` — then ask the three questions: is there an **attempt ceiling**, a **backoff**,
  and a **deadline**? A paginator additionally needs a **cursor-advanced check**: exiting only on a
  short page means a server whose cursor never advances loops forever.
- **Severity:** HIGH — non-termination has no ceiling by definition; MEDIUM only when an outer bound
  (a lock, a window, a supervisor) provably caps it.
- **Remedy shape:** attempt ceiling + exponential backoff + a wall-clock deadline; for pagination,
  `if new_cursor == cursor: break` plus a page cap; make the give-up state visible rather than silent.
- **Example (MEDIUM, the gateway pair that proves the remedy is in-repo):**
  `backend/app/gateways/marketplace/wb_catalog.py:29` and `:230` (aiseller, X-1256 #8) — `while True`
  with no page cap and no cursor-advanced check, while **the Ozon gateway in the same tree does it
  right** at `ozon_inventory.py:115-117` (`new_cursor == cursor` check + `page > 50` cap).
- **Example (MEDIUM, the ops variant):** `docker-compose.yml:196` and `:135` (kupiclub, X-1255 #11) —
  `while true; do python …; else sleep 10; done` collector/retention loops: no attempt ceiling, no
  backoff, no alert seam, so a database that never comes up forks an interpreter every 10 s forever.

#### 5. Whole-table / whole-directory scans repeated per lookup

- **Detect:** an aggregate or a full scan issued **per entity** rather than once for the set; a query
  with no `LIMIT` whose result is then paged in application code; a helper that re-computes a whole
  period to look up a handful of ids the caller already fetched; a closure that linearly re-scans a
  full list on every call.
- **Severity:** HIGH when the scan is per request and the table grows; MEDIUM for a bounded admin path.
- **Remedy shape:** one grouped query (`GROUP BY <entity_id>, …` over `id = ANY(%s)`) plus an index;
  bound the window; `LIMIT` at the SQL, not in Python; reuse the by-id fetch the caller already made;
  bulk-load and `bisect` instead of re-scanning.
- **Example (HIGH):** `app/videos.py:1614` (kupiclub, X-1255 #1) — `_window_aggregates` issues one
  GROUP-BY-day scan **per distinct article** over the whole article lifetime (`date_from=None`), and it
  is the entry point for **seven** statistics endpoints (`videos.py:1911,2025,2170,2254,3730,3917,4041,4191`).
  Remedy: one query `mapping_id = ANY(%s)` + `GROUP BY mapping_id, day`, with a bounded window.
- **Example (MEDIUM):** `backend/app/services/charts.py:65` (aiseller, X-1256 #9) — one PriceHistory
  SELECT per listing, and the returned `at` closure (`charts.py:70-77`) linearly re-scans the full
  rows list on every call, up to 26 buckets deep.

#### 6. Frontend effect / fetch re-trigger loops, uncleared timers, duplicate list fetches

- **Detect:** an effect whose dependency array contains something that changes on **every navigation,
  page turn, sort click or tick** (`location.pathname`, a full query string, a fresh object from
  `setState`); an interval or timeout with no cleanup on unmount/hidden and no attempt ceiling; the
  same endpoint fetched by a context provider AND by the components that consume it.
- **Severity:** HIGH when the re-trigger re-fires an expensive server computation per interaction;
  MEDIUM when it re-fires a cheap endpoint; LOW when it only restarts a timer.
- **Remedy shape:** stable dependencies (drop what does not change the result); clear on unmount and on
  hidden; bound the poll with max-ticks or a deadline plus a visible give-up state; fetch once in one
  provider and read it from context.
- **Example (HIGH):** `frontend/src/pages/StatisticsPage.jsx:818-831` + `:452` with `app/videos.py:4029,4041`
  (kupiclub, X-1255 #2) — the census effect keys on `searchParams.toString`, so **page turns, sort
  clicks and picking a video all re-fire** two endpoints that each recompute the identical whole-period
  section set.
- **Example (MEDIUM):** `frontend/src/components/Layout.jsx:271-284` (aiseller, X-1256 #13) —
  `location.pathname` in the deps tears down the 5-minute interval on **every in-app navigation** and
  fires an immediate refetch, so the endpoint is hit per page click instead of per 5 minutes.
- **Example (MEDIUM, the unbounded-poll variant):** `frontend/src/pages/pricing/promoMatrix.js:25`
  (aiseller, X-1256 #14) — `setTimeout(tick, 25000)` with no ceiling and no deadline, while sibling
  pages in the same tree poll with `POLL_MAX_ATTEMPTS=45` and a 600 s deadline.

#### 7. Workers / cron re-processing already-processed items (no watermark), or overlapping runs

- **Detect:** a periodic job whose selection predicate does **not exclude what it already did** — read
  the `WHERE` clause and ask "what does this job write that would make this row stop matching?" If the
  answer is "nothing", the scanned set grows forever. Also: no advisory lock or `nx` guard, so a slow
  run overlaps the next one and both redo the work.
- **Severity:** HIGH — a missing watermark is unbounded by construction, which is why it outranks its
  hot-path-ness.
- **Remedy shape:** a real watermark (a `processed_at` / `anonymized_at` column, a stored cursor, or a
  predicate that excludes the transformed shape) plus a run lock; a cost-backfill-style
  "last processed" marker in settings is the same remedy.
- **Example (HIGH):** `scripts/anonymize_ips.py:69` (kupiclub, X-1255 #4) — the retention sweep selects
  `WHERE ip IS NOT NULL AND created_at < now - interval`, but **a masked ip is still NOT NULL**, so it
  re-selects every already-truncated row forever; it runs daily (`docker-compose.yml:135`) and the
  scanned set grows linearly with the whole hit log. Remedy: an `anonymized_at` marker, or the predicate
  `ip <> masked(ip)`.
- **Counter-example worth copying (CLEAN):** aiseller's `tasks/cost_backfill_recompute.py` keeps a real
  watermark in `tenant.settings` with a bounded 180-day lookback (X-1256 CLEAN list).

### The report shape (so runs compare, run-to-run and project-to-project)

A run of this lens produces exactly three parts. All three are required — a report with findings but
no CLEAN list cannot be compared against the next one, because a class that was not checked reads
identically to a class that was checked and was fine.

1. **FINDINGS (ranked, most severe first).** Each: `SEVERITY file:line — ` a one-or-two-line quote or
   paraphrase of the offending code, **what repeats and how often** (per request / per row / per tick /
   per nightly cabinet — with the arithmetic when it is knowable: "~7k + ~49k SELECTs per cabinet per
   night"), and a one-line **remedy**.
2. **CLEAN (checked, no finding).** The named surfaces swept and found sound — file or module names,
   with the reason in a few words ("bulk-loaded maps", "page caps + cursor checks", "deadline-bounded,
   memoized"). This is what makes the sweep auditable and the next run cheaper.
3. **VERDICT (about two lines).** Where the waste lives, which costs compound, and which findings are
   genuine defects rather than debt.

Rank by severity, then by whether the remedy already exists elsewhere in the same repo — those are the
cheapest and they are common (both 2026-09-04 audits found the correct pattern already present in a
sibling file for most HIGH findings).

## Example

The ready-to-paste `yitc-ops.yaml` declaration — the canonical `repeated-work` entry, conforming to
the `inspection.themes[]` shape (SPEC-0160 rule 12: `theme:` + `probe:` with `view:` XOR `sweep:` +
`cadence:`; a `sweep:` carries required `surfaces:` and `checks:` plus an optional `against:`). Adjust
only the `surfaces:` glob to this project's own layout:

```yaml
inspection:
  themes:
  - theme: repeated-work
    owner: kernel # REQUIRED — the entry is KERNEL-OWNED and `init` seeds it into
                             # every consumer with no opt-out; stripping this is a fail-closed error
    probe:
      sweep:
        # ONE brace group per token, and every root ends `/**/*` — the shape the reader
        # matches (it splits on whitespace, expands ONE group per token, and keeps FILES:
        # in pathlib `X/**` yields directories only, so `X/**` and a two-group token each
        # match ZERO files). Verified on a fixture, not assumed —.
        surfaces: "backend/**/*.{py,js,jsx,ts,tsx} app/**/*.{py,js,jsx,ts,tsx} api/**/*.{py,js,jsx,ts,tsx} src/**/*.{py,js,jsx,ts,tsx} frontend/src/**/*.{py,js,jsx,ts,tsx} scripts/**/*.{py,js,jsx,ts,tsx} workers/**/*.{py,js,jsx,ts,tsx} tasks/**/*.{py,js,jsx,ts,tsx}"
        against: patterns/repeated-work-lens.md # the seven classes, severity rubric + report shape
        checks:
        - n-plus-one-queries-in-loops
        - file-config-row-re-read-per-request-or-iteration
        - remote-resource-re-fetched-or-pagination-restarted
        - unbounded-loops-retries-polls
        - repeated-whole-table-or-dir-scans-per-lookup
        - frontend-effect-fetch-re-trigger-loops
        - worker-cron-reprocessing-without-watermark
    cadence: monthly
```

Record each run against the same slug so the cadence is visible:

```
bin/yitc-v2 -C <repo> inspect record --theme repeated-work --tracks primary
```

## Anti-pattern

- **Running it once as an ad-hoc audit and calling the class handled.** The class regenerates with
  every new self-contained function; a one-off pass dates immediately. That is exactly what the
  cadence + the recorded run replace.
- **Rewriting the checklist per project.** The seven classes, the rubric and the report shape live
  HERE; a project's declaration points at this file with `against:`. A pasted private copy diverges by
  the second project — which is the drift this pattern was written to stop.
- **Reporting findings without the CLEAN list.** Then nobody can tell an unchecked class from a sound
  one, and the next run starts from zero.
- **Fixing an N+1 by adding a cache in front of it.** A per-call cache hides the shape and adds an
  invalidation problem; the remedy is the bulk load, the grouped query, the watermark — remove the
  repetition, do not memoize it. (Reach for a cache only when the repetition is genuinely irreducible.)
- **Treating "bounded but wasteful" as "must fix now".** The rubric exists so a nightly job's MEDIUM
  does not outrank a request path's HIGH; rank, then work the top.
- **Adding a runner, a cron, an event kind or a findings store for this.** The lens is hand-run
  (SPEC-0057 §2 manual-first); it rides the existing `inspection_completed` event and the existing
  `inspect record` verb, and nothing here is a gate.

## Cites

- `patterns/inspection-criteria-roster-navigation-map.md` §Consumer-local product-adaptation themes —
  the shelf this lens sits on; it adapts the T4 context-economy APPROACH to the product realm.
- `specs/SPEC-0160` **rule 12** — the `inspection.themes[]` declare-shape the §Example snippet conforms
  to (re-homed there from SPEC-0093 at the section-schema split; the carrier framework + declare-or-waive
  stance remain SPEC-0093's).
- `specs/SPEC-0057` §2 (manual-first) / §6 (the `inspection_completed` schema) / §9 (product-adaptation
  framing).
- `specs/SPEC-0119` **rule 10** — the review-due semaphore that surfaces a consumer-declared theme when
  it is past its own cadence tier and work has landed since.
- `plans/read-contract-for-composed-seams-and-a-quiet-lane-.md` — the kernel-side sibling of the
  PREVENTION cue (read amplification at composed seams, measured by counters rather than by hand).
- Cross items **X-1255** (kupiclub) and **X-1256** (aiseller), 2026-09-04 — the two audits every example
  above is quoted from; `bin/yitc-v2 cross show X-1255`.
