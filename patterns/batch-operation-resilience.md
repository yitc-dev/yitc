---
name: batch-operation-resilience
class: technique
sourced_from: <host-home>/knowledge/patterns/batch-operation-resilience.md
applies_to: any loop that processes a list of items (sync, import/export, batch API calls, background jobs); mandatory when items hit paid external APIs
---

# Batch Operation Resilience

## Problem

Naive `for item in items: process(item)` loops silently lose data:
- One exception stops the loop; remaining items never processed
- No per-item visibility — operators see only the first failure
- Audit recorded in the same transaction as business logic → rollback erases proof the call was made (cost charged externally, no internal record)
- Sync scripts using plain INSERT create duplicates on rerun

## Solution

Four rules applied together:

### 1. Per-item isolation

Each item processed inside its own try/except. Failure of one item does NOT stop the loop. Aggregate counts collected by category (`success / error / skip`).

### 2. Audit BEFORE business logic

The fact of calling an external API (cost, run_id) is committed in a **separate transaction** BEFORE processing the response. If business logic rolls back, the audit row survives — operators can reconcile cost.

### 3. Sync = upsert, not INSERT

Sync scripts use `INSERT... ON CONFLICT DO UPDATE` keyed on the business unique constraint. Repeated runs are safe.

### 4. Mandatory end-of-batch report

Operation returns/logs: «X of Y ok, Z errors, W skipped», with per-error item-id and cause. Without a report, lost data is invisible.

## Example

```python
results = {"success": 0, "error": 0, "skip": 0, "errors": []}

for item in items:
    try:
        process(item)
        results["success"] += 1
    except DuplicateError:
        results["skip"] += 1
    except Exception as e:
        results["error"] += 1
        results["errors"].append({"item_id": item.id, "error": str(e)})

log.info(
    "Batch complete: %d/%d ok, %d errors, %d skipped",
    results["success"], len(items), results["error"], results["skip"]
)
return results
```

**Three-source reconciliation** for paid external APIs: cross-check (a) provider invoice, (b) internal DB audit, (c) user-facing dashboard. Any gap = data loss en route.

## Anti-pattern

- `for x in xs: process(x)` without try/except — one bad item kills the batch
- Audit INSERT in the same transaction as business logic — rollback erases the audit trail; external cost charged anyway
- Sync via plain INSERT — rerun creates duplicates (one production CMS project shipped 17 699 dupes this way)
- Catch-all `except Exception: pass` without logging — silent data loss
- No end-of-batch report — operators discover loss weeks later via billing reconciliation

## Cites

- v1 incident sources: a production CMS project B-631 (795 of 1133 external runs lost to rollback, ≈$200/wk), B-283 (17 699 sync duplicates); a production data-ingest project B-190 (audit row killed by transaction rollback)
- Related: external-API wrappers should pair this with rate-limit / retry / circuit-breaker patterns
