import '@testing-library/jest-dom/vitest'
import { configure, render } from '@testing-library/react'
import { createElement } from 'react'
import { beforeEach } from 'vitest'
import { ToastRegion } from '../design/components/ToastRegion'
import { resetToasts } from '../design/toast'

// findBy* / waitFor wait up to 3 s (default 1 s). A page's first render compiles its lazy chunk, which under the full
// suite's parallel load sometimes took just over a second, failing tests at random (routes, ActivityLog). A passing
// test is no slower; only a real failure takes longer to report.
configure({ asyncUtilTimeout: 3000 })

// jsdom has no layout engine and doesn't implement ResizeObserver at all —
// components that measure their own container (e.g. Table's mobile
// card-view switch) need the constructor to exist so `new ResizeObserver()`
// doesn't throw. This mock never actually fires a callback (there's no real
// box model to observe), which is the desired behavior in tests: components
// using it stay at whatever default state they render with initially,
// matching pre-existing test expectations rather than flipping into a
// "narrow" branch nothing asserts on.
class ResizeObserverMock {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
;(globalThis as unknown as { ResizeObserver: typeof ResizeObserverMock }).ResizeObserver = ResizeObserverMock

// jsdom doesn't implement matchMedia — the color-scheme provider calls it to
// resolve the 'system' preference. Default to light (matches: false); a test
// can override window.matchMedia to simulate a dark OS preference.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

// Restore a working window.localStorage / sessionStorage.
//
// jsdom provides both (a real Storage object, given a non-opaque origin — and
// the origin here is http://localhost:3000, so that is not the problem). Node
// 26 also defines a global `localStorage` of its own, which is `undefined`
// unless the process was started with --localstorage-file. Inside Vitest's
// jsdom environment that Node global shadows jsdom's, so `window.localStorage`
// reads back as undefined and anything touching it throws
// "Cannot read properties of undefined (reading 'setItem')".
//
// That is what broke src/auth/storage.test.ts, src/design/colorScheme.test.tsx
// and ThemeToggle.test.tsx — 7 failures with nothing wrong in the app code, on
// tests written before this Node version. `ci.yml` has no frontend job, so
// nothing caught it.
//
// Define a spec-shaped in-memory Storage when the global is missing, rather
// than reaching into jsdom internals. configurable/writable so tests can still
// spy on or replace individual methods (colorScheme.test.tsx swaps setItem).
class MemoryWebStorage implements Storage {
  private store = new Map<string, string>()

  get length(): number {
    return this.store.size
  }

  clear(): void {
    this.store.clear()
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null
  }

  removeItem(key: string): void {
    this.store.delete(key)
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value))
  }
}

for (const name of ['localStorage', 'sessionStorage'] as const) {
  if (!window[name]) {
    Object.defineProperty(window, name, {
      value: new MemoryWebStorage(),
      configurable: true,
      writable: true,
    })
  }
}

// jsdom does not implement Element.prototype.scrollIntoView — it is absent, not
// a no-op. Product code that calls it is correct in a browser; here the call
// throws `TypeError: ... is not a function`.
//
// That matters more than it looks. Warehouses.tsx scrolls its error banner into
// view from inside a requestAnimationFrame, so the throw happens AFTER the test's
// assertions have passed, in a callback nothing awaits. Vitest reports it as an
// unhandled error attributed to whichever file happened to be running, and only
// when the frame fires before the environment tears down — which is why it
// surfaced intermittently (1 error, then 4, then real test failures in
// App.test.tsx and CompanySettings.test.tsx that passed in isolation) and never
// reproduced on demand.
//
// Note `el?.scrollIntoView(...)` does NOT guard this: the optional chain tests
// the element, not the method.
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView(): void {
    /* no-op: layout is not simulated in jsdom */
  }
}

// Toasts (FD-21) appear in a region mounted once at the app root; mount it for every test too, so a page test sees
// "Payment recorded" exactly as a user would, and start each test with none.
beforeEach(() => {
  resetToasts()
  render(createElement(ToastRegion))
})

