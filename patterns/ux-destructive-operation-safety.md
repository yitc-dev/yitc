---
name: ux-destructive-operation-safety
class: discipline
sourced_from: <host-home>/knowledge/patterns/ux-destructive-operation-safety.md
applies_to: any UI surface offering destructive actions (delete, cancel, irreversible state change) — especially when the action affects money, third-party data, or other users' records
---

# Three-Layer Defense for Destructive UI Actions

## Problem

Destructive actions (delete, cancel, irreversible state change) drive most user-reported incidents. A single confirm-dialog is not enough — users click «OK» without reading. The default «confirm-then-do» loop trains users to ignore the prompt.

## Solution

Three independent layers; combine them per operation type using the matrix below.

### Layer 1 — Confirmation dialog (before action)

A dialog with consequences spelled out **concretely**, not «are you sure».

Rules:
- Text describes effect with numbers: «Delete record? 12 linked items will be detached, 3 accruals reversed.»
- Money or third-party-data impact — list exactly what happens
- Confirm button labeled by **result**, not «OK»: «Delete record», «Reverse charge»
- Destructive button visually separated from primary CTA (color, spacing); on mobile not adjacent to primary

When to apply: every delete, every irreversible action, every money operation.

### Layer 2 — Undo (after action)

Instead of confirm — perform the action, show a toast with «Undo» button (5 second timer). Faster for user, softer UX.

Rules:
- Action implemented via soft-delete (not physical delete)
- Toast: result + «Undo» button + countdown
- After timeout — action finalized
- On «Undo» — `deleted_at` cleared, row restored

When to apply: tag removal, link detachment, small reversible operations where soft-delete is available. NOT for money/irreversible — those go through Layer 1.

### Layer 3 — Disabled state + tooltip (prevention)

If business logic disallows the action — render the button disabled with a tooltip explaining why.

Rules:
- Disabled = visually muted + `cursor: not-allowed`
- Tooltip names the specific reason: «Cannot delete: 3 pending payments»
- Without tooltip the user thinks the system is broken
- On mobile — tooltip on tap (no hover)

When to apply: business rule blocks action (dependent rows exist, wrong status, missing permission).

## Example

**Confirmation with consequences:**

```tsx
<ConfirmDialog
  title="Delete record?"
  description="3 related payments will be cancelled. This cannot be undone."
  confirmLabel="Delete record"
  confirmVariant="destructive"
  onConfirm={handleDelete}
/>
```

**Undo via toast:**

```tsx
const handleRemoveTag = async (tagId: string) => {
  await softDelete(tagId);
  toast({
    message: "Tag removed.",
    action: { label: "Undo", onClick: => restore(tagId) },
    duration: 5000,
  });
};
```

**Disabled with explanation:**

```tsx
<Tooltip content="Cannot delete: has pending payments">
  <Button disabled={hasPendingPayments} variant="destructive">
    Delete
  </Button>
</Tooltip>
```

## Application matrix

| Operation type | L1 Confirm | L2 Undo | L3 Disabled |
|---|:-:|:-:|:-:|
| Delete record with dependencies | ✓ | — | ✓ (if blockers) |
| Delete small element (tag, link) | — | ✓ | — |
| Money operation | ✓ (with amount) | — | ✓ (if no permission) |
| Irreversible action | ✓ (with consequences) | — | ✓ (if status disallows) |
| Status change (ordinary) | — | — | ✓ (if FSM forbids — see `fsm-enum-whitelist`) |

## Anti-pattern

- One-size confirm for every destructive button — users learn to click through; protection is theatre
- «Are you sure?» without consequences — meaningless prompt
- Confirm-then-also-undo — picks the worst of both worlds; double friction
- Disabled without tooltip — user assumes system is broken, files a bug
- Destructive button color = primary CTA color — misclick risk on mobile

## Adjacent safety

- Unsaved changes — `beforeunload` + router blocker on form pages
- Safe defaults — «Also delete data» checkbox unchecked by default; dangerous options never preselected
- Soft-delete as foundation — physical delete is a last resort; soft-delete enables Layer 2 and recovery by unique identifier

## Cites

- Related patterns: `soft-delete` (foundation for Layer 2), `fsm-enum-whitelist` (governs Layer 3 for status changes), `ux-general-principles` (covers the rest of the destructive-action UX rules)
