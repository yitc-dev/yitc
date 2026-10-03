---
name: time-decay-scoring
class: technique
sourced_from: <host-home>/knowledge/patterns/time-decay-scoring.md
applies_to: ranking / scoring problems where a high-score stale item should not permanently outrank a fresh medium-score one (trends, alerts, recommendations)
---

# Time-Decay Scoring

## Problem

When ranking content by quality (score) without a time factor, old high-score items occupy the top forever, crowding out fresh content. A simple sort-by-score loop produces stagnant feeds and stale recommendation surfaces.

## Solution

Multiply raw score by an exponential decay tied to a **semantic event timestamp** (not the recompute time):

```
display_score = raw_score × 0.5^(days_since_event / half_life)
```

Where:
- `raw_score` — base score (quality, engagement, votes)
- `days_since_event` — days from the entity's semantic event time
- `half_life` — half-life in days (tunable)

**Critical:** anchor decay to the **event** timestamp (`published_at`, `created_at`), not to the **recompute** timestamp (`calculated_at`). Batch recompute will reset `calculated_at` for all rows and «resurrect» everything from zero days old.

## Example

```python
import math
from datetime import datetime, timezone

def display_score(raw_score: float, event_ts: datetime, half_life_days: float) -> float:
    age_days = (datetime.now(timezone.utc) - event_ts).total_seconds / 86400
    return raw_score * (0.5 ** (age_days / half_life_days))
```

**Settings table:**

| Param | Example | Purpose |
|---|---|---|
| `half_life` | 3 days (viral), 7 days (general) | decay speed |
| `min_score_threshold` | 0.01 | hide-below cutoff |

Store `half_life` as a **dynamic setting** (DB JSONB or settings table), not a code constant — lets you tune without a deploy.

## Anti-pattern

- Decay anchored to `calculated_at` / `updated_at` — batch recompute resurrects old items as «fresh»
- Hard-coded `half_life` constant — every tuning iteration requires a deploy
- No `min_score_threshold` — long tail of effectively-zero items lingers in the result set
- Mix decay into raw score persistence — store raw score, compute decay at read time only

## When to apply

- Trending lists, recommendation feeds, viral dashboards
- Alert prioritization (older alerts decay if not actioned)
- Any ranking where freshness and quality both matter

## Cites

- v1 source: viral dashboard in a production data-ingest project (B-126, half-life selection and event-anchored fix)
- v1 mistake log: «batch recalc resurrects old items» — 2026-03-30
