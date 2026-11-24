/**
 * Visual baseline (audit FD-38): every route in src/shell/routeTable.ts, captured at 1366 px, at 390 px and in dark
 * mode, as a role allowed on it, with real records from the local stack.
 *
 * There are no committed reference images. Seed data, dates and counts differ from one machine and one day to the
 * next, so a stored image would fail for reasons that are not design. Instead the same run captures the base first
 * and compares the change against it, on one database:
 *
 *   npm run visual:baseline   # before the change: writes the images to visual-baseline/ (gitignored)
 *   npm run visual:compare    # after it: every screen that changed fails, with before, after and diff in the report
 *   npx playwright show-report
 *
 * CI does the same on a pull request that touches styles (frontend-ci.yml, job `visual`): base branch first, then the
 * pull request, and the report is uploaded as an artifact.
 *
 * Kept stable: the clock is fixed, animations and the text caret are off, and each capture waits until no API request
 * is in flight and nothing on screen says it is loading; Playwright then waits for two identical
 * frames. One capture per route and mode; `VISUAL_ONLY=/billing` narrows it.
 */
import { expect, test, type Page, type Request } from '@playwright/test'
// The shared route sampler (also used by scripts/mobile-audit.mjs). e2e/ is not type-checked.
import { loadRoutes, sampleIds, sampleUrl } from '../../scripts/routeSamples.mjs'

/** A fixed "now", so relative dates ("3 days ago") and date defaults are the same in both captures. */
const NOW = new Date('2026-11-19T09:00:00+01:00')

const MODES = [
  { name: 'desktop', viewport: { width: 1366, height: 900 }, scheme: 'light', isMobile: false },
  { name: 'mobile', viewport: { width: 390, height: 844 }, scheme: 'light', isMobile: true },
  { name: 'dark', viewport: { width: 1366, height: 900 }, scheme: 'dark', isMobile: false },
] as const

const only = process.env.VISUAL_ONLY
const routes = loadRoutes().filter((r: { path: string }) => !only || r.path.includes(only))
let ids: Record<string, string>

test.beforeAll(async () => {
  ids = await sampleIds()
})

/**
 * Count the page's API requests still waiting for an answer. Not `networkidle`: the app polls (notifications, the
 * session), so the network is never idle. A request counts as answered at its response, not at `requestfinished`: the
 * app never reads the body of a 401 session refresh, so that event never comes for it.
 */
function trackApi(page: Page): () => number {
  const pending = new Set<Request>()
  const isApi = (r: Request): boolean => new URL(r.url()).port === '3000'
  page.on('request', (r) => {
    if (isApi(r)) pending.add(r)
  })
  page.on('response', (res) => pending.delete(res.request()))
  page.on('requestfailed', (r) => pending.delete(r))
  return () => pending.size
}

/** Wait until no API request has been in flight for half a second and nothing on screen says it is loading. */
async function settle(page: Page, inFlight: () => number): Promise<void> {
  const deadline = Date.now() + 20_000
  let quietSince = 0
  while (Date.now() < deadline) {
    const loading = await page
      .evaluate(() => !!document.querySelector('[aria-busy="true"]') || /Loading…|Loading\.\.\./.test(document.body.innerText))
      .catch(() => true)
    if (inFlight() === 0 && !loading) {
      quietSince ||= Date.now()
      if (Date.now() - quietSince >= 500) break
    } else quietSince = 0
    await page.waitForTimeout(100)
  }
  await page.evaluate(() => document.fonts.ready)
}

for (const mode of MODES) {
  test.describe(mode.name, () => {
    test.use({ viewport: mode.viewport, isMobile: mode.isMobile, hasTouch: mode.isMobile, colorScheme: mode.scheme })

    for (const route of routes as { path: string; role: string | null }[]) {
      test(route.path, async ({ page }) => {
        await page.clock.setFixedTime(NOW)
        await page.addInitScript(
          ({ role, scheme }) => {
            if (role) sessionStorage.setItem('shipx_dev_identity', role)
            localStorage.setItem('shipx-color-scheme', scheme)
          },
          { role: route.role, scheme: mode.scheme },
        )
        const inFlight = trackApi(page)
        await page.goto(sampleUrl(route.path, ids))
        await settle(page, inFlight)
        const name = `${route.path.replace(/^\//, '').replace(/[/:]+/g, '_') || 'root'}--${mode.name}.png`
        await expect(page).toHaveScreenshot(name, { fullPage: true, animations: 'disabled', caret: 'hide' })
      })
    }
  })
}
