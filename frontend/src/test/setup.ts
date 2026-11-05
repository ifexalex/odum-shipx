import '@testing-library/jest-dom/vitest'

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
