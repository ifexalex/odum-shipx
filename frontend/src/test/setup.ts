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
