import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

const RETRY_DELAY_MS = 600

/**
 * `import()` that tries a second time before giving up.
 *
 * A chunk fails to load for two ordinary reasons: a phone loses signal for a moment, or the app was deployed while
 * this tab was open and the old chunk's file is gone. The first is fixed by trying again; the second is not, but it
 * costs one extra request to find out, and then the error boundary's retry offers a clean reload.
 */
async function importWithRetry<T>(load: () => Promise<T>): Promise<T> {
  try {
    return await load()
  } catch {
    await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS))
    return load()
  }
}

/**
 * Lazy-load one named export of an area module (`shell/areas/*`).
 *
 * `load` is the area's `() => import('./areas/china')`; every page of that area shares the one chunk, which the
 * bundler fetches once however many of its pages are visited. Pages are named exports, `React.lazy` wants a default.
 * The result is typed as the export itself, so a page's props (a layout's `children`) are still checked.
 */
// `any` is React.lazy's own constraint (ComponentType<any>): a page's props are whatever it declares.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function lazyNamed<M extends Record<string, ComponentType<any>>, K extends keyof M & string>(
  load: () => Promise<M>,
  name: K,
): LazyExoticComponent<M[K]> {
  return lazy<M[K]>(async () => {
    const module = await importWithRetry(load)
    return { default: module[name] as M[K] }
  })
}
