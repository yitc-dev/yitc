---
name: error-boundary
class: architecture
sourced_from: <host-home>/knowledge/patterns/error-boundary.md
applies_to: every React app — wrap top-level App element so a render-tree crash shows a fallback UI instead of a white screen
---

# React ErrorBoundary

## Problem

Import error or runtime crash in React kills the whole app — user sees a white screen. In dev mode any module-load error becomes 500 on every request. The user has no idea what happened or what to do.

## Solution

A class component `ErrorBoundary` wraps `<App>` at the top level. On any unhandled error in the render tree it renders a «under maintenance» fallback with a «Reload» button. The fallback is plain inline styles, deliberately decoupled from the app's stylesheet (which might be the thing that failed to load).

## Example

```tsx
// src/components/ErrorBoundary.tsx
import { Component, ReactNode } from 'react'

interface Props { children: ReactNode }
interface State { hasError: boolean }

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError: State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    console.error('ErrorBoundary caught:', error, info.componentStack)
    // optional: POST to telemetry/webhook here
  }

  render {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          minHeight: '100vh', background: '#f8fafc',
        }}>
          <div style={{
            background: '#fff', borderRadius: '12px', padding: '3rem',
            boxShadow: '0 4px 6px rgba(0,0,0,0.07)', textAlign: 'center', maxWidth: '400px',
          }}>
            <h1>Under maintenance</h1>
            <p>Please refresh in a few minutes.</p>
            <button onClick={ => window.location.reload}>Reload</button>
          </div>
        </div>
)
    }
    return this.props.children
  }
}
```

**Usage in App.tsx:**

```tsx
import { ErrorBoundary } from '@/components/ErrorBoundary'

export function App {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        {/* routes */}
      </BrowserRouter>
    </ErrorBoundary>
)
}
```

## Anti-pattern

- No boundary at all — user sees white screen on any render crash
- Wrap a deep subtree instead of the App root — boundaries below the crash site don't catch
- Use the app's styled components in the fallback UI — if the stylesheet is the thing that failed, the fallback fails too
- Rely on the boundary alone — it doesn't catch event handlers, async errors, or SSR errors; pair with window.onerror or a logger

## Limitations

- Doesn't catch errors in event handlers (only render)
- Doesn't catch errors in async code (`setTimeout`, promises)
- Doesn't catch SSR errors

## Cites

- Pair with a delivery-side smoke test post-deploy: see `deploy-smoke-test`
- Optional companion: send `componentDidCatch` payload to a webhook for alerting
