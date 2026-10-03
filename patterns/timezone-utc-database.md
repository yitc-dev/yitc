---
name: timezone-utc-database
class: architecture
sourced_from: <host-home>/knowledge/patterns/timezone-utc-database.md
applies_to: any project storing timestamps in a database; mandatory for systems with users in multiple timezones or where reports cross DST boundaries
---

# UTC in the Database

## Problem

Timezone drift on storage + display. Typical symptoms:
- Timestamps shift by hours after reading
- `created_at` shows different time depending on client
- Comparisons break because of naive vs aware datetime
- Migrating the server to another timezone «moves» every existing date

## Solution

All timestamps in the database are stored in UTC, with timezone-aware columns. Conversion to local time happens ONLY at the display layer (frontend). The backend never works with local time.

Key rules:
1. **DB:** `TIMESTAMP WITH TIME ZONE` (PostgreSQL canonicalizes to UTC)
2. **Backend:** every `datetime` is timezone-aware UTC
3. **API:** ISO 8601 with `Z` suffix (``)
4. **Frontend:** convert to user's local zone at render time only

## Example

**SQLAlchemy `TimestampMixin`:**

```python
from datetime import datetime
from sqlalchemy import DateTime, text
from sqlalchemy.orm import Mapped, mapped_column

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now"),
        nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now"),
        onupdate=text("now"),
        nullable=False)
```

Critical details:
- `DateTime(timezone=True)` → `TIMESTAMP WITH TIME ZONE` in PostgreSQL
- `server_default=text("now")` — DB-side default; one source of truth for time
- `onupdate=text("now")` — `updated_at` refreshes on any change

**PostgreSQL config check:**

```sql
SHOW timezone; -- should be 'UTC'
ALTER DATABASE mydb SET timezone TO 'UTC';
```

**Frontend conversion:**

```typescript
const utcDate = new Date(item.created_at);
const localString = utcDate.toLocaleString;
// or with explicit zone:
const userZoneTime = utcDate.toLocaleString('en-US', { timeZone: 'America/New_York' });
```

## Anti-pattern

| Wrong | Why | Right |
|---|---|---|
| `DateTime` without `timezone=True` | naive timestamp, loses zone info | `DateTime(timezone=True)` |
| `default=datetime.utcnow` | Python-side default — drifts if app/DB clocks differ | `server_default=text("now")` |
| `default=datetime.now` | local server time, not UTC | `server_default=text("now")` |
| Convert to local in backend | backend doesn't know user's zone | convert in frontend |
| `TIMESTAMP WITHOUT TIME ZONE` | drops timezone awareness | `TIMESTAMP WITH TIME ZONE` |

## Adoption checklist

- [ ] PostgreSQL `timezone = 'UTC'`
- [ ] All `DateTime` columns use `timezone=True`
- [ ] Defaults via `server_default=text("now")`, never Python `default=`
- [ ] API returns ISO 8601 UTC (`Z` suffix)
- [ ] Frontend converts to local at display time
- [ ] `SoftDeleteMixin.deleted_at` same `timezone=True` shape
- [ ] Tests assert returned datetimes are timezone-aware

## Cites

- v1 source: `TimestampMixin` + `SoftDeleteMixin` in a production CMS project
- Related: `soft-delete` (same `DateTime(timezone=True)` rule applies to `deleted_at`)
