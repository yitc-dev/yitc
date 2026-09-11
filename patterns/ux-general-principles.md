---
name: ux-general-principles
class: discipline
sourced_from: <host-home>/knowledge/patterns/ux-general-principles.md
applies_to: any web app with a user-facing UI; principles are universal — apply when designing or reviewing screens, forms, and feedback flows
---

# Universal UX Principles for Web Apps

## Problem

Without a shared rule-set, UX decisions drift screen-by-screen — a consistent feel emerges only by accident. Reviewers spend their attention on the same recurring issues (missing empty states, silent actions, disabled buttons without tooltips) instead of higher-leverage feedback.

## Solution

A small portable rulebook. Use as a review checklist + as a default mental model when designing screens. Rules grouped by concern.

## Fundamentals

- **F1 — Three questions on every screen.** Every screen answers: **where am I** (title, breadcrumbs), **what can I do here** (CTA, actions), **what happens after I act** (feedback). Missing any answer = screen not ready.
- **F2 — Recognition beats recall.** Pick-from-list beats type-from-memory. Autocomplete, masks, defaults — anything that lowers cognitive load.
- **F3 — Progressive disclosure.** Main thing first; secondary on demand. Long forms → steps. Long lists → pagination (not infinite scroll).

## Mobile

- Touch targets ≥ 44×44px on every button, link, checkbox
- One key action per screen — primary CTA visible without scrolling
- Tables → cards on mobile (horizontal tables unreadable at 375px)
- «Paste from clipboard» button for URL fields (Clipboard API)
- Status = color **+** text **+** icon (never color-only — colorblindness, sunlight)
- Minimize manual input — anything autodetectable should be autodetected
- Offline tolerance — show «no connection» instead of white screen; forms don't reset on network error

## Desktop

- Navigation not overloaded — group by meaning, collapse inactive groups in sidebar
- Tables: sticky header on scroll
- Bulk actions — select multiple → action on group
- Keyboard navigation predictable: Tab, Enter, Escape work in forms + modals

## General

- **Empty states explain.** «You have no records yet» + what to do, not a blank table
- **Feedback on every action.** Click → loading → success/error. No silent actions. All five states: hover, pressed, loading, success, error.
- **One term = one word everywhere.** Glossary; no jargon.
- **Tooltips on metrics + abbreviations.** Every acronym → `(?)` icon with explanation

## Error prevention

- Delete = always confirm dialog, no exceptions (even «small» deletes) — see `ux-destructive-operation-safety`
- Unsaved changes — warning on navigation (`beforeunload` + router blocker)
- Soft-delete + restore by unique identifier (email, handle); URL → new record — see `soft-delete`
- Duplicate check on entry — strict for unique fields, soft warning otherwise
- Long lists (50+ items) → autocomplete with search, not `<select>`
- Hints on input fields — label + placeholder with format

## Navigation + search

- Breadcrumbs on nested pages (depth ≥ 2) — link to each level
- Human-readable error texts — what happened, how to fix, will data be lost; map common API errors
- Skeleton/shimmer on page load; progress bar for operations > 2s
- Filters + sorting in URL query params — state survives back-navigation; URL shareable

## Forms + controls

- Validation errors **under the field** (not in a top block); text + icon, not color only
- Buttons named by result — «Save profile», not «Submit»
- Irreversible + money → explicit warning with consequences spelled out
- Clickable looks clickable — `cursor: pointer`, link underlines, affordance
- Four states per control: focus, hover, active, disabled. Disabled = muted + `not-allowed`
- Toast priorities: success = quiet (3s), warning = longer (5s), error = until dismissed. One toast at a time.
- Safe defaults — dangerous options unchecked
- Title + one context line per page
- Modals don't break flow — Escape / outside-click closes safely without data loss; inline forms preferred where possible
- Undo > confirm when available; money/irreversible still goes through confirm
- Draft autosave — long forms → localStorage; restore on return
- Contextual row-actions in tables — frequent operations without a full detail-page hop

## Mobile details

- ≥ 8px spacing between tappable elements (misclick guard)
- Bottom tab bar for frequent sections (≤ 5); hamburger only for rare
- Form wizard with step indicator; correct `inputMode` per field type (numeric, url, email); autofocus first field
- Thumb zone — frequent actions in the lower third
- Destructive buttons far from primary action (different color, spacing, section)
- No hover dependency — tooltips on tap, submenus on tap
- Safe areas — `padding-bottom: env(safe-area-inset-bottom)`
- Vertical orientation default; landscape need not be required but must not break layout

## Data transparency

- FSM visualization on detail pages — mini-pipeline of all statuses, current highlighted (pair with `fsm-enum-whitelist`)
- Totals row in tables with numbers — sum / avg / count; user should not have to export for SUM
- Change log on entity — who, when, why (collapsible «History» section; pair with `audit-trail-field-level`)
- Disabled elements need a tooltip explaining why — see `ux-destructive-operation-safety`

## Data integrity

- Soft-deleted rows ALWAYS filtered out of lists, counts, aggregations, dropdowns: `WHERE deleted_at IS NULL` — see `soft-delete`
- Counts match lists: badge «4 records» = 4 rows in the filtered list (don't cache count separately from filters)
- API errors show backend `detail` field, not a generic message
- Testability — `data-testid` on key UI elements; don't tie automation to visible text

## Anti-pattern

- Color-only status (colorblindness, sunlight)
- Silent action with no feedback
- Disabled button without tooltip — user blames the system
- «Are you sure?» with no specifics — see `ux-destructive-operation-safety` for the proper pattern
- Hover-only affordance on mobile (no hover available)

## Cites

- Related: `ux-destructive-operation-safety` (deeper coverage of confirm/undo/disabled layers), `soft-delete` + `audit-trail-field-level` + `fsm-enum-whitelist` (the data-integrity rules above depend on these patterns)
