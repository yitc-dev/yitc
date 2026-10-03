---
name: anchor-a-fixture-where-two-authorities-disagree
class: technique
sourced_from: <project> `lessons/anchor-a-fixture-where-the-two-authorities-disagree.md` (read-only provenance — the local lesson keeps its project-specific HOW; SPEC-0090 §2b outcome 2 promote-as-a-SPLIT) + <project> (the defect a sibling card's noon anchor had made its own probe blind to) + <project> (the same class recurring in a second file — a `datetime.now(timezone.utc) - timedelta(days=N)` fixture asserting a bare `.date` against a Moscow-dated product, blocking EVERY land in that repo from 21:00 to 24:00 UTC nightly)
applies_to: any test whose fixture passes a value between two authorities that can disagree about it — two timezones, two clocks, two rounding rules, two ID spaces, two encodings, two serializers. The worked examples are calendar-day/timezone ones because that is where it has been measured twice, and §The grep-able smell is calendar-day-specific by construction; the rule in §Solution is authority-agnostic. Read it when writing OR reviewing such a fixture, and before "stabilizing" a fixture that goes red only at certain hours
---

# Anchor a fixture where the two authorities disagree

## Problem

A value passes between two authorities that can disagree about it — the product dates an axis in
Moscow while the test reads the same instant's UTC `.date`; one side rounds half-up and the other
half-even; one side encodes as UTF-8 and the other as latin-1. **The fixture's anchor decides whether
the test can see that disagreement at all.**

Anchored where the two authorities AGREE, the correct implementation and the broken one emit
byte-identical output. The probe then passes on both, and it passes *for the same reason it would
pass if the subject were deleted*. No number of added assertions fixes this: the input, not the
assertion, is what blinded it.

Two measured instances, one project:

- **<project>.** `_daily_series` dated each day's increment with a bare `.date` on a tz-aware
  instant (the UTC calendar day) while `_window_bounds` dated the AXIS those increments key into in
  Moscow. Two calendars, one chart: for the three hours from 21:00 UTC they name different days, so
  every increment landed one slot left. The sibling card, fenced to the test file, had done the
  sensible thing for its own scope and anchored every fixture at **noon Moscow** — where the two
  calendars agree — so the suite would stop going red nightly. From that anchor the broken product and
  a correct one are indistinguishable. **That card was looking directly at the bug and was, by
  construction, blind to it.**
- **<project>.** A second file, months later: the fixture built its publication instant as
  `datetime.now(timezone.utc) - timedelta(days=PUBLISHED_DAYS_AGO)` and asserted that instant's bare
  `.date`, while the product dated the same axis in Moscow. Here the anchor failed the other way —
  a probe that was about something *else* sat inside the ambiguity, so it went red from 21:00 UTC
  every night. Its layer was a declared verify layer, so **no branch in that repo could land for
  three hours a night**, whatever it changed.

The two instances are the same rule pointing in opposite directions, which is why the rule is not
"use an unambiguous anchor" or "use an ambiguous one": **match the anchor to what the probe is
about.**

## Solution

**1. Put the disagreement in the FIXTURE, not the clock.** For a probe that is ABOUT the ambiguity,
pick an instant that has two different dates at *every* hour the suite runs — 01:00 local, which is
22:00 UTC of the previous day, for a UTC-vs-Moscow pair. No frozen clock, no simulated process time,
no lucky run hour, nothing to skip under CI. Freezing the clock would work too, and would make the
probe's sensitivity depend on machinery instead of on the data; prefer the data.

**2. A convenience anchor is a real decision, so say what it costs — and keep it BESIDE the sensitive
one, never replace it.** An unambiguous anchor (noon Moscow) is the right default for every probe
that is about something else; say so in its own docstring. Add the sensitive anchor as a SIBLING
helper (`_msk_small_hours` beside `_msk_noon`) so the six probes that want an unambiguous day keep
it and the one probe that is about the ambiguity gets what it needs. Moving the default instead
trades one blind spot for another.

**3. Check EVERY instant the fixture derives, not just the one you anchored.** A derived value can
re-introduce the ambiguity one field over. In the attach offset was 3 days 12 hours, so
anchoring `published` at noon Moscow put `attached` at **midnight** Moscow — the exact ambiguity
being removed, one field away. Print both the UTC and the local date of every instant the fixture
computes, and choose an anchor hour that leaves all of them far from the boundary.

**4. Read the differential before you believe the probe.** Run it against the unfixed subject and
record what it says, verbatim. The reading that mattered in was
`got [10, 20, 30, 40, 50, None], expected [None, 10, 20, 30, 40, 50]` — the defect's own shape, not
"1 failed". A probe that passes before and after proves nothing. The differential-tripwire rule and
its baseline discipline are homed in **SPEC-0165**; this pattern adds only the fixture-anchor half of
it and does not restate the rest.

**5. The recognition question — ask it of any fixture, in authoring and in review:**

> **Is there an input for which the correct and the broken implementations would print the same
> thing?**

If the fixture sits at such an input, the probe is decoration whatever it asserts. The tell in review
is a fixture comment explaining that the anchor was chosen to make the test **stable**: stability
against a real ambiguity is bought by moving out of the region where the ambiguity lives, which is
exactly the region a probe about that ambiguity has to sit in.

## The grep-able smell

The recurring shape is narrow enough to grep: a fixture computing an instant RELATIVE to now and then
asserting its calendar day. One line, run from the repo root:

```
grep -rnE '(now\([^)]*\)|utcnow\(\)|today\(\))[[:space:]]*[-+][[:space:]]*timedelta' tests/
```

**What a hit means: context to read, never an automatic defect.** A `now`-relative anchor is often
the RIGHT choice (a dated literal fixture is a time bomb). The hit is a question, and it is a defect
only when BOTH halves answer yes:

1. **Does the value reach a calendar-day assertion?** — a `.date`, a `%Y-%m-%d` format, an
   `.isoformat` on a date, a "today"/"day N" comparison. A value used as an absolute DURATION
   (an age in seconds/minutes/hours, a freshness window) never touches a calendar and is not this
   class.
2. **Is there a SECOND authority that dates the same value differently?** — the product converting to
   a display timezone, a DB dating in UTC while the app dates locally, a report and a card reading
   one aggregate through two calendars. With a single authority on both sides there is nothing to
   disagree, and the fixture is fine.

Two yeses mean the fixture's anchor is load-bearing: apply §Solution. The count itself is not a bar —
no threshold, no gate, nothing to drive to zero. This is a reviewer's grep, not a check. (Wiring it
into the external-auditor lens is deliberately deferred until a third project hits the class —
CHARTER §Principle 1 filter 4.)

**Measured reach, so the grep's noise level is known.** Run over this kernel's own `tests/` on
2026-09-20 it returned **17 hits, none of them a defect**: **4** reach a calendar day (two
`date.today ± timedelta` waiver dates, two `.date.isoformat` report/expiry dates) but each is
read back by code using the SAME date authority the fixture used — half 1 yes, half 2 no; **8** are
absolute-duration age/freshness anchors in seconds, minutes, hours or days-as-a-timestamp — half 1
no; **5** are string literals inside one test's own teaching prose and generated fixture source, not
live fixtures at all. Expect to read a handful of hits per repo and discard most of them.

## Example

The fix: the probe about the ambiguity anchors at **01:00 МСК = 22:00 UTC of the previous
day** — two dates at every run hour — while `_msk_noon` stays put for the probes that are about
something else, its docstring naming this failure. The differential was recorded against the unfixed
subject before the fix was believed.

The fix, the mirror case: a probe about publication anchoring, not about calendars, gets an
hour where both the anchored AND the derived instant sit far from a local midnight (06:00 МСК →
attached 18:00 МСК), both verified by printing each instant's UTC and Moscow date. Its acceptance
additionally required the suite to be re-run against a deliberately broken subject, so the stabilized
fixture had to prove it could still fail.

## Anti-pattern

**Anchoring for STABILITY a probe that is ABOUT the ambiguity.** "The suite goes red for three hours
a night, so anchor the fixture where the calendars agree" is a correct instinct applied at the wrong
altitude: it silences the symptom by moving the experiment out of the region it exists to observe.
When a fixture goes red only at certain hours, first ask which of the two things the probe is about —
then stabilize it (§Solution 2, a sibling anchor) or sharpen it (§Solution 1), and never conclude
from the red that the anchor was the bug.

## Cites

- `SPEC-0090` — the patterns(travel)/lessons(local) boundary; §2b outcome 2 is the promote-as-a-SPLIT
  route that produced this pattern (the general WHY travels here; the project-specific HOW stays in
  <project>'s own lesson).
- `SPEC-0165` — the loud-failure / differential-tripwire doctrine. §Solution 4 points at it; the
  differential rules live there, not here.
- `SPEC-0011` (<project>) — store-UTC / display-Moscow, the two authorities in both worked examples.
- `patterns/timezone-utc-database.md` — the sibling at a different altitude: UTC in the database,
  convert only at the display layer. That pattern governs STORAGE and DISPLAY; this one governs the
  TEST FIXTURE that reads across the seam between them.
