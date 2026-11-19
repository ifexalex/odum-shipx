#!/usr/bin/env node
/**
 * Phone-width audit (2026-11-17): opens every route in src/shell/routeTable.ts at a phone width, as a role allowed on
 * it, with real records from the local API, and reports any page that scrolls sideways or has an element sticking out
 * past the right edge (clipped or scrolling the page). A row that is meant to scroll sideways inside itself (tabs, a
 * long pipeline: `ScrollStrip`) carries `data-scroll-strip` and is allowed.
 *
 * Needs the local stack: the API on :3000 (`make dev`) and Vite on :5173 (`npm run dev`), local dev auth.
 *
 *   node scripts/mobile-audit.mjs            # 375, 360 and 320 px
 *   node scripts/mobile-audit.mjs 360 /billing   # one width, routes containing "/billing"
 *
 * Exit code 1 when any page fails.
 */
import { chromium } from 'playwright'
import { APP, loadRoutes, sampleIds, sampleUrl } from './routeSamples.mjs'

const [widthArg, only] = process.argv.slice(2)
const WIDTHS = widthArg ? [Number(widthArg)] : [375, 360, 320]
const ids = await sampleIds()
const routes = loadRoutes()

const browser = await chromium.launch()
let failures = 0
for (const WIDTH of WIDTHS) {
  console.log(`== ${WIDTH} px`)
  for (const r of routes) {
    if (only && !r.path.includes(only)) continue
    const url = sampleUrl(r.path, ids)
    const role = r.role
    const page = await browser.newPage({ viewport: { width: WIDTH, height: 812 }, isMobile: true, hasTouch: true })
    if (role) await page.addInitScript((x) => sessionStorage.setItem('shipx_dev_identity', x), role)
    await page.goto(APP + url).catch(() => {})
    await page.waitForTimeout(3000)
  const found = await page.evaluate(() => {
    const vw = window.innerWidth
    const docOverflow = document.documentElement.scrollWidth - vw
    const scrollable = (el) => {
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const s = getComputedStyle(p)
        if ((s.overflowX === 'auto' || s.overflowX === 'scroll') && p.getBoundingClientRect().right <= vw + 1) return true
      }
      return false
    }
    const out = []
    for (const el of document.body.querySelectorAll('*')) {
      const rect = el.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) continue
      const s = getComputedStyle(el)
      if (s.visibility === 'hidden' || s.position === 'fixed' || s.textOverflow === 'ellipsis') continue
      if (rect.right > vw + 1 && rect.left < vw && !scrollable(el)) {
        // report the outermost offender only
        const parent = el.parentElement
        if (parent && parent.getBoundingClientRect().right > vw + 1 && !scrollable(parent) && parent !== document.body) continue
        const cls = (typeof el.className === 'string' ? el.className : '').split(' ').filter(Boolean).slice(0, 2).join('.')
        out.push({ el: `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}`, right: Math.round(rect.right), text: (el.innerText || '').replace(/\s+/g, ' ').slice(0, 50) })
      }
    }
    // Scroll containers that really scroll sideways: a table wrapper may, a page column must not.
    const sideways = []
    for (const el of document.body.querySelectorAll('*')) {
      const st = getComputedStyle(el)
      if (!(st.overflowX === 'auto' || st.overflowX === 'scroll')) continue
      if (el.hasAttribute('data-scroll-strip')) continue
      if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
        const cls = (typeof el.className === 'string' ? el.className : '').split(' ').filter(Boolean).slice(0, 2).join('.')
        const hasTable = !!el.querySelector(':scope > table, :scope > div > table')
        const edge = el.getBoundingClientRect().left + el.clientWidth
        const culprits = []
        const walk = (node) => {
          for (const child of node.children) {
            const r = child.getBoundingClientRect()
            if (r.width === 0) continue
            const cs = getComputedStyle(child)
            const scrolls = cs.overflowX === 'auto' || cs.overflowX === 'scroll'
            if (r.right > edge + 1 && !scrolls) {
              // descend while a single child is the one sticking out, to name the real culprit
              const wide = [...child.children].filter((c) => c.getBoundingClientRect().right > edge + 1)
              if (wide.length === 1 && wide[0].getBoundingClientRect().width > 0) { walk(child); continue }
              const c2 = (typeof child.className === 'string' ? child.className : '').split(' ').filter(Boolean).slice(0, 2).join('.')
              culprits.push(`${child.tagName.toLowerCase()}.${c2}(w${Math.round(r.width)}) "${(child.innerText || '').replace(/\s+/g, ' ').slice(0, 40)}"`)
            } else if (!scrolls) walk(child)
          }
        }
        walk(el)
        sideways.push({ el: `${el.tagName.toLowerCase()}.${cls}`, by: el.scrollWidth - el.clientWidth, table: hasTable, culprits: culprits.slice(0, 4) })
      }
    }
    return { docOverflow, offenders: out.slice(0, 8), sideways }
  })
    const bad = found.docOverflow > 1 || found.offenders.length || found.sideways.some((x) => !x.table)
    if (bad) {
      failures++
      console.log(`FAIL ${r.path} (${role ?? 'public'})`)
      for (const o of found.offenders) console.log(`     sticks out: ${o.el} to ${o.right}px "${o.text}"`)
      for (const x of found.sideways.filter((y) => !y.table)) console.log(`     scrolls sideways: ${x.el} +${x.by}px; ${(x.culprits || []).join('; ')}`)
    }
    await page.close()
  }
}
await browser.close()
console.log(failures ? `${failures} page(s) fail` : 'every page fits')
process.exit(failures ? 1 : 0)
