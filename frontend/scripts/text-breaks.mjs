#!/usr/bin/env node
/**
 * FD-10 audit (2026-11-20): opens every route in src/shell/routeTable.ts, as a role allowed on it, with real records
 * from the local API, and reports
 *   - a word split across two lines ("OUTSTAN / DING"),
 *   - text cut off (an ellipsis or a line clamp hiding part of it),
 *   - a double frame: a bordered box whose edges sit on its bordered parent's edges,
 *   - at 1024 px and wider, a table that scrolls sideways (it should fit; columns wrap between words),
 *   - a page taller than what it shows: blank space to scroll into, from an absolutely positioned element that escaped
 *     the shell's scroll area (found 2026-11-20: the hidden "Optional" text of form fields stretched every long form).
 * IDs, emails, URLs and figures are allowed to wrap anywhere; only ordinary words count.
 *
 * Needs the local stack: the API on :3000 (`make dev`) and Vite on :5173 (`npm run dev`), local dev auth.
 *
 *   node scripts/text-breaks.mjs                 # 375 and 1280 px
 *   node scripts/text-breaks.mjs 375 /billing    # one width, routes containing "/billing"
 *
 * Exit code 1 when any page fails. `TEXT_BREAKS_INJECT_CSS='…'` adds a style to every page, to prove the checks catch a
 * defect (e.g. a border back on a table inside a card).
 */
import { chromium } from 'playwright'
import { APP, loadRoutes, sampleIds, sampleUrl } from './routeSamples.mjs'

const [widthArg, only] = process.argv.slice(2)
const WIDTHS = widthArg ? [Number(widthArg)] : [375, 1280]
const ids = await sampleIds()
const routes = loadRoutes()

const browser = await chromium.launch()
let failures = 0
for (const WIDTH of WIDTHS) {
  console.log(`== ${WIDTH} px`)
  for (const r of routes) {
    if (only && !r.path.includes(only)) continue
    const phone = WIDTH < 600
    const page = await browser.newPage({
      viewport: { width: WIDTH, height: 900 },
      isMobile: phone,
      hasTouch: phone,
    })
    if (r.role)
      await page.addInitScript((x) => sessionStorage.setItem('shipx_dev_identity', x), r.role)
    await page.goto(APP + sampleUrl(r.path, ids)).catch(() => {})
    await page.waitForTimeout(3000)
    if (process.env.TEXT_BREAKS_INJECT_CSS)
      await page.addStyleTag({ content: process.env.TEXT_BREAKS_INJECT_CSS })
    const found = await page.evaluate(() => {
      const root = document.querySelector('main') ?? document.body
      const visible = (el) => {
        const s = getComputedStyle(el)
        return s.visibility !== 'hidden' && s.display !== 'none' && el.getClientRects().length > 0
      }
      const where = (el) =>
        `${el.tagName.toLowerCase()}.${String(el.className).split(' ')[0] || ''}`

      // Words split across lines. Ordinary words only: letters, at least five of them.
      const splits = []
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
      for (let node = walker.nextNode(); node && splits.length < 6; node = walker.nextNode()) {
        const el = node.parentElement
        if (
          !el ||
          !visible(el) ||
          el.closest('[aria-hidden="true"], code, pre, [data-allow-break]')
        )
          continue
        for (const m of node.textContent.matchAll(/\p{L}{5,}/gu)) {
          // Judge the whole token: an email, URL, ID or figure ("ops@acmeshipping.com", "PL-2026") may wrap anywhere.
          const before = node.textContent.slice(0, m.index).split(/\s/).pop() ?? ''
          const after = node.textContent.slice(m.index + m[0].length).split(/\s/)[0] ?? ''
          if (/[@./_\d]/.test(before + after)) continue
          const range = document.createRange()
          range.setStart(node, m.index)
          range.setEnd(node, m.index + m[0].length)
          const tops = new Set(
            [...range.getClientRects()].filter((q) => q.width > 0).map((q) => Math.round(q.top)),
          )
          if (tops.size > 1) splits.push(`${where(el)} "${m[0]}"`)
        }
      }

      // Text cut off.
      const clipped = []
      for (const el of root.querySelectorAll('*')) {
        if (clipped.length >= 6 || !visible(el) || !el.textContent.trim()) continue
        const s = getComputedStyle(el)
        const clamps = s.webkitLineClamp !== 'none' && s.webkitLineClamp !== ''
        const ellipsis = s.textOverflow === 'ellipsis'
        if (!clamps && !ellipsis) continue
        if (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) {
          clipped.push(`${where(el)} "${el.textContent.trim().slice(0, 40)}"`)
        }
      }

      // Double frames: a fully bordered box on its bordered ancestor's edges (3 of 4 within 2 px).
      const bordered = (el) => {
        const s = getComputedStyle(el)
        return ['Top', 'Right', 'Bottom', 'Left'].every(
          (side) =>
            parseFloat(s[`border${side}Width`]) > 0 &&
            s[`border${side}Style`] !== 'none' &&
            !/^rgba\(.*,\s*0\)$/.test(s[`border${side}Color`]),
        )
      }
      const doubles = []
      for (const el of root.querySelectorAll('div, section, table')) {
        if (doubles.length >= 6 || !visible(el) || !bordered(el)) continue
        let parent = el.parentElement
        while (parent && parent !== root && !bordered(parent)) parent = parent.parentElement
        if (!parent || parent === root) continue
        const a = el.getBoundingClientRect()
        const b = parent.getBoundingClientRect()
        const near = [
          a.top - b.top,
          b.right - a.right,
          b.bottom - a.bottom,
          a.left - b.left,
        ].filter((d) => Math.abs(d) <= 2)
        if (near.length >= 3) doubles.push(`${where(el)} inside ${where(parent)}`)
      }
      const sideways = []
      if (window.innerWidth >= 1024) {
        for (const t of root.querySelectorAll('table')) {
          const box = t.parentElement
          if (visible(t) && box && box.scrollWidth > box.clientWidth + 1)
            sideways.push(`table +${box.scrollWidth - box.clientWidth}px`)
        }
      }
      // The document should be as tall as the page's own boxes. Taller means something positioned against the page,
      // outside the scroll area that should clip it, is pushing it down: blank space below the app.
      // What the page shows: every box of real size (not 1px hidden text) that no scroll area clips.
      const stretched = []
      const unclipped = (el) => {
        for (let a = el.parentElement; a && a !== document.body; a = a.parentElement)
          if (getComputedStyle(a).overflowY !== 'visible') return false
        return true
      }
      let shown = 0
      for (const el of document.body.querySelectorAll('*')) {
        const box = el.getBoundingClientRect()
        if (box.width > 1 && box.height > 1 && visible(el) && unclipped(el)) shown = Math.max(shown, box.bottom + scrollY)
      }
      const extra = document.documentElement.scrollHeight - Math.max(shown, window.innerHeight)
      if (extra > 2) stretched.push(`${extra}px of blank page below the app`)
      return { splits, clipped, doubles, sideways, stretched }
    })
    if (
      found.splits.length ||
      found.clipped.length ||
      found.doubles.length ||
      found.sideways.length ||
      found.stretched.length
    ) {
      failures++
      console.log(`FAIL ${r.path} (${r.role ?? 'public'})`)
      for (const x of found.splits) console.log(`     word split: ${x}`)
      for (const x of found.clipped) console.log(`     text cut off: ${x}`)
      for (const x of found.doubles) console.log(`     double frame: ${x}`)
      for (const x of found.sideways) console.log(`     scrolls sideways: ${x}`)
      for (const x of found.stretched) console.log(`     page stretched: ${x}`)
    }
    await page.close()
  }
}
await browser.close()
console.log(
  failures
    ? `${failures} page(s) fail`
    : 'no split words, cut-off text, double frames, sideways tables or stretched pages',
)
process.exit(failures ? 1 : 0)
