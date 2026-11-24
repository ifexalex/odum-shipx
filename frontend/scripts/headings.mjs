#!/usr/bin/env node
/**
 * Heading audit (FD-49, 2026-11-20): opens every route in src/shell/routeTable.ts, as a role allowed on it, with real
 * records from the local API, and reports a page that
 *   - has no top-level heading, or more than one (`<h1>`), or an empty one,
 *   - skips a level going down (an `<h3>` straight under the `<h1>`), so a screen reader's outline has a hole.
 * Waits for loading skeletons (`aria-busy`) to clear first. Headings inside a dialog start their own outline and are
 * not counted; hidden headings are ignored. Prints each page's `<h1>` so a reviewer can see it names the page.
 *
 * Needs the local stack: the API on :3000 (`make dev`) and Vite on :5173 (`npm run dev`), local dev auth.
 *
 *   node scripts/headings.mjs             # every route at 1280 px
 *   node scripts/headings.mjs /billing    # routes containing "/billing"
 *
 * Exit code 1 when any page fails. `HEADINGS_INJECT='<h3>x</h3>'` adds markup at the top of every page's `main` (or
 * body), to prove the checks catch a defect.
 */
import { chromium } from 'playwright'
import { APP, loadRoutes, sampleIds, sampleUrl } from './routeSamples.mjs'

const [only] = process.argv.slice(2)
const ids = await sampleIds()
const routes = loadRoutes()

const browser = await chromium.launch()
let failures = 0
for (const r of routes) {
  if (only && !r.path.includes(only)) continue
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  if (r.role) await page.addInitScript((x) => sessionStorage.setItem('shipx_dev_identity', x), r.role)
  await page.goto(APP + sampleUrl(r.path, ids)).catch(() => {})
  await page.waitForTimeout(1500)
  // A page still loading shows a skeleton and no heading yet; wait for it to finish (or give up after 15 s).
  await page.waitForFunction(() => !document.querySelector('[aria-busy="true"]'), null, { timeout: 15000 }).catch(() => {})
  if (process.env.HEADINGS_INJECT)
    await page.evaluate((html) => {
      const host = document.querySelector('main') ?? document.body
      host.insertAdjacentHTML('afterbegin', html)
    }, process.env.HEADINGS_INJECT)
  const found = await page.evaluate(() => {
    const visible = (el) => {
      const s = getComputedStyle(el)
      return s.visibility !== 'hidden' && s.display !== 'none' && el.getClientRects().length > 0
    }
    const headings = [...document.querySelectorAll('h1, h2, h3, h4, h5, h6')].filter(
      (h) => visible(h) && !h.closest('[role="dialog"], [aria-modal="true"]'),
    )
    const h1s = headings.filter((h) => h.tagName === 'H1').map((h) => h.textContent.trim())
    const skips = []
    let previous = 0
    for (const h of headings) {
      const level = Number(h.tagName[1])
      if (level > previous + 1) skips.push(`h${level} "${h.textContent.trim().slice(0, 40)}" after h${previous}`)
      previous = level
    }
    return { h1s, skips }
  })
  const problems = []
  if (found.h1s.length !== 1) problems.push(`${found.h1s.length} top-level headings: ${JSON.stringify(found.h1s)}`)
  if (found.h1s.some((t) => !t)) problems.push('an empty top-level heading')
  for (const s of found.skips) problems.push(`skips a level: ${s}`)
  if (problems.length) {
    failures++
    console.log(`FAIL ${r.path} (${r.role ?? 'public'})`)
    for (const p of problems) console.log(`     ${p}`)
  } else {
    console.log(`ok   ${r.path.padEnd(38)} h1: ${found.h1s[0]}`)
  }
  await page.close()
}
await browser.close()
console.log(failures ? `${failures} page(s) fail` : 'one top-level heading per page, no skipped levels')
process.exit(failures ? 1 : 0)
