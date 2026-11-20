/**
 * FD-14: every page inside the app's layouts is titled by the shared `PageHeader` (or, at the end of a flow,
 * `ResultScreen`), which holds its only top-level heading. No page writes its own `<h1>`, and nothing reaches into the
 * top bar: it keeps only global controls.
 *
 * Outside the layouts, the sign-in flow, public tracking, the landing page and the print pages title themselves
 * (they have no app header); FD-49 covers their headings.
 */
import { describe, expect, it } from 'vitest'

const PAGES = import.meta.glob(['./**/*.tsx', '!./**/*.test.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<
  string,
  string
>
const AREAS = import.meta.glob(['../shell/areas/*.ts'], { query: '?raw', import: 'default', eager: true }) as Record<
  string,
  string
>

const OUTSIDE_THE_LAYOUTS = ['./auth/', './print/', './marketing/', './customer/PublicTrack.tsx']
/** Routed through ConfigLayout, which frames the settings page it wraps; the page inside has the header. */
const FRAMES = new Set(['./tenant-admin/ConfigLayout.tsx'])

const outside = (path: string): boolean => OUTSIDE_THE_LAYOUTS.some((prefix) => path.startsWith(prefix))

/** Every page file a route renders, from the area chunks that export them. */
const routedPages = Object.values(AREAS)
  .flatMap((source) => [...source.matchAll(/from '\.\.\/\.\.\/pages\/([^']+)'/g)].map((m) => `./${m[1]}.tsx`))
  .filter((path) => !outside(path) && !FRAMES.has(path))

describe('one page header per page (FD-14)', () => {
  it('finds the routed pages', () => expect(routedPages.length).toBeGreaterThan(60))

  it.each(routedPages)('%s is titled by PageHeader or ResultScreen', (path) => {
    expect(PAGES[path], `${path} is not a page file`).toBeDefined()
    expect(PAGES[path]).toMatch(/<(PageHeader|ResultScreen)\b/)
  })

  const inLayouts = Object.entries(PAGES).filter(([path]) => !outside(path))

  it.each(inLayouts)('%s writes no <h1> of its own', (_path, source) => {
    expect(source).not.toMatch(/<h1\b/)
  })

  it.each(inLayouts)('%s does not reach into the top bar', (_path, source) => {
    expect(source).not.toMatch(/useTopBarSlot|TopBarContext/)
  })
})
