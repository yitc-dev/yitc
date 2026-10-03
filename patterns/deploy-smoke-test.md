---
name: deploy-smoke-test
class: discipline
sourced_from: <host-home>/knowledge/patterns/deploy-smoke-test.md
applies_to: any project with a web frontend deployed automatically; required when prod/staging split exists or when broken pages would not be immediately noticed
---

# Post-Deploy Smoke Test

## Problem

After a deploy, broken pages can stay broken until a user complains. White-screen errors, missing assets, JS console errors, ErrorBoundary fallbacks rendered — none of those surface in server logs. The longer the silence, the worse the perception.

## Solution

Two complementary layers, both fired automatically:

**Layer 1: post-deploy headless-browser smoke run.** After deploy succeeds, a short script walks the project's critical pages in a headless browser and asserts:
- Page returns 200 — necessary, never sufficient: a 200 with a black or white page is still a broken deploy
- **Render check:** the page's main content appears — wait for a project-chosen main-content selector to become visible, and fail on timeout
- No uncaught script error (`pageerror`) and no console.error
- No white screen / no ErrorBoundary fallback
- On failure → notification (Telegram webhook, Slack, etc.)

**Context parity (web UI).** Run e2e and the smoke in the SAME browser context class as production:
secure (HTTPS, or loopback — `localhost` names and `<ip>/8` / `::1`, which browsers treat as
potentially trustworthy even over plain HTTP) vs non-secure (plain HTTP on a non-loopback IP or
hostname). Secure-context-only browser APIs (`crypto.randomUUID`, `navigator.clipboard`, service
workers, …) are simply absent on a non-secure origin. If production is plain HTTP by IP, point the
smoke at that real origin and run e2e against a non-loopback origin too — or serve production over
HTTPS so both sides are secure.

*Why (the test-server incident, newcomer soak 2026-09):* a deploy converged with its HTTP smoke
passing while the page rendered black. Over plain HTTP by IP the page was not a secure context, so
`crypto.randomUUID` was undefined and the app crashed on load; e2e had run on `localhost` (a secure
context) and never saw it. The owner reported it about seven minutes later and the deploy was rolled
back; the adopter's fix was a headless render check in the smoke gate — exactly the render check above.

The script is read-only — it does not mutate state, does not write artifacts, just reads pages.

**Layer 2: ErrorBoundary → webhook.** When ErrorBoundary catches an error in production, post the payload (page, error message, component stack) to a webhook. Catches errors that slipped past smoke (route the script doesn't cover, user-triggered code path).

## Example

**Smoke runner sketch (Playwright):**

```python
import asyncio
from playwright.async_api import async_playwright

PAGES = ["/", "/dashboard", "/settings"]
BASE = "https://app.example.com" # the REAL production origin — same secure/non-secure class
MAIN_SELECTOR = "main, #root > *" # project-chosen: an element only a rendered page has

async def smoke:
    failures = []
    async with async_playwright as pw:
        browser = await pw.chromium.launch
        for path in PAGES:
            ctx = await browser.new_context
            page = await ctx.new_page
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            resp = await page.goto(BASE + path)
            try: # render check: the main content must actually appear
                await page.locator(MAIN_SELECTOR).first.wait_for(state="visible", timeout=10_000)
            except Exception as e:
                errors.append(f"main content not rendered: {e}")
            if resp.status != 200 or errors:
                failures.append({"path": path, "status": resp.status, "errors": errors})
            await ctx.close
        await browser.close
    if failures:
        notify(failures) # webhook to Telegram/Slack/etc.
        return 1
    return 0

asyncio.run(smoke)
```

**ErrorBoundary → webhook tie-in:** see `error-boundary` pattern; add `fetch('/api/telemetry/error', {method:'POST', body: JSON.stringify(payload)})` inside `componentDidCatch`.

## Anti-pattern

- Skip smoke because «tests already pass» — unit tests don't see Vite bundle errors, missing env vars, broken CSP, or CDN cache misses
- Smoke runs against staging only — production has different env vars / domain / CSP / data; staging green ≠ prod green
- HTTP-200 / curl smoke as the render gate — it proves the server answered, not that the page rendered
- e2e on `localhost` while production is plain HTTP on a non-loopback origin — localhost is a secure context, so secure-only APIs pass in e2e and are missing in production
- Notify a channel nobody watches — alert must reach an owner who can roll back
- ErrorBoundary fallback without telemetry — user sees «under maintenance» and you don't know it happened

## Cites

- Companion: `error-boundary` (Layer 2 needs ErrorBoundary in place)
- Adjacent: post-deploy verification protocol — smoke is one probe; release notes / health endpoint check are others
