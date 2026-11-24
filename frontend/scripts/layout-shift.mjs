#!/usr/bin/env node
/**
 * Layout-shift check (FD-20): loads sampled record and list pages with real data and reports their cumulative layout
 * shift (CLS) while the page loads. Skeletons are shaped like the final layout, so a page should stay under 0.1
 * ("good" by Web Vitals). Needs the local stack (API on :3000, Vite on :5173). Exit 1 when a page is over.
 *
 *   node scripts/layout-shift.mjs
 */
import { chromium } from 'playwright'
import { APP, sampleIds, sampleUrl } from './routeSamples.mjs'
const ids = await sampleIds()
const pages = [['/billing/:id','nigeria_office_staff'],['/containers/:id','china_office_staff'],['/packing-lists/:id','china_office_staff'],['/billing','nigeria_office_staff'],['/claims/:id','nigeria_office_staff'],['/release-notes/:id','nigeria_office_staff']]
const b = await chromium.launch()
let over = 0
for (const [path, role] of pages) {
  const p = await b.newPage({ viewport: { width: 1280, height: 900 } })
  await p.addInitScript((r) => {
    sessionStorage.setItem('shipx_dev_identity', r)
    window.__cls = 0
    new PerformanceObserver((list) => { for (const e of list.getEntries()) if (!e.hadRecentInput) window.__cls += e.value }).observe({ type: 'layout-shift', buffered: true })
  }, role)
  await p.goto(APP + sampleUrl(path, ids)).catch(() => {})
  await p.waitForTimeout(4000)
  const cls = await p.evaluate(() => window.__cls)
  if (cls > 0.1) over++
  console.log(path.padEnd(22), 'CLS', cls.toFixed(3), cls > 0.1 ? 'OVER' : '')
  await p.close()
}
await b.close()
process.exit(over ? 1 : 0)
