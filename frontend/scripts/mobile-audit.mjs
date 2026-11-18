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
import fs from 'node:fs'
import { chromium } from 'playwright'

const API = process.env.API_URL ?? 'http://localhost:3000'
const APP = process.env.APP_URL ?? 'http://localhost:5173'
const TENANT = process.env.AUDIT_TENANT ?? '10000000-0000-0000-0000-000000000001'
const [widthArg, only] = process.argv.slice(2)
const WIDTHS = widthArg ? [Number(widthArg)] : [375, 360, 320]

async function first(role, path, tenant = TENANT) {
  const res = await fetch(`${API}/v1/${path}`, { headers: { 'X-Tenant-ID': tenant, 'X-Role': role } })
  const body = await res.json().catch(() => ({}))
  const data = Array.isArray(body.data) ? body.data[0] : body.data
  return data?.id ?? 'sample'
}

const ids = {
  tenant: await first('platform_admin', 'platform/tenants?limit=1', 'PLATFORM'),
  user: await first('tenant_admin', 'tenant/users?limit=1'),
  customer: await first('tenant_admin', 'customers?limit=1'),
  container: await first('china_office_staff', 'containers?limit=1'),
  pl: await first('china_office_staff', 'packing-lists?limit=1'),
  manifest: await first('nigeria_office_staff', 'manifests?limit=1'),
  billing: await first('nigeria_office_staff', 'billing?limit=1'),
  claim: await first('nigeria_office_staff', 'claims?limit=1'),
  refund: await first('nigeria_office_staff', 'refunds?limit=1'),
  rn: await first('nigeria_office_staff', 'release-notes?limit=1'),
  cpl: await first('customer', 'packing-lists?limit=1'),
  mybilling: await first('customer', 'billing?limit=1'),
  myclaim: await first('customer', 'claims?limit=1'),
}
const PARAM = {
  '/platform/tenants/:id': ids.tenant, '/admin/users/:id': ids.user, '/admin/customers/:id': ids.customer,
  '/containers/:id': ids.container, '/packing-lists/:id': ids.pl, '/packing-lists/:id/edit': ids.pl,
  '/packing-lists/:id/print': ids.pl, '/manifests/:id': ids.manifest, '/billing/:id': ids.billing,
  '/claims/:id': ids.claim, '/refunds/:id': ids.refund, '/release-notes/:id': ids.rn, '/release-notes/:id/print': ids.rn,
  '/my-shipments/:code': ids.cpl, '/my-billing/:id': ids.mybilling, '/my-billing/:id/payment-success': ids.mybilling,
  '/my-billing/:id/refund-request': ids.mybilling, '/my-release-notes/:id': ids.rn, '/my-claims/:id': ids.myclaim,
}

const table = fs.readFileSync(new URL('../src/shell/routeTable.ts', import.meta.url), 'utf8')
const routes = [...table.matchAll(/\{\s*path: '([^']+)',\s*(?:\/\/[^\n]*\n\s*)*allow: (\[[^\]]*\]|'public')/g)].map((m) => ({
  path: m[1],
  allow: m[2] === "'public'" ? 'public' : JSON.parse(m[2].replace(/'/g, '"')),
}))
const ROLE_PREF = ['tenant_admin', 'nigeria_office_staff', 'china_office_staff', 'warehouse_attendant', 'platform_admin', 'customer']

const browser = await chromium.launch()
let failures = 0
for (const WIDTH of WIDTHS) {
  console.log(`== ${WIDTH} px`)
  for (const r of routes) {
    if (only && !r.path.includes(only)) continue
    const url = PARAM[r.path] ? r.path.replace(/:(id|code)/, PARAM[r.path]) : r.path.replace(/:(\w+)/g, 'sample')
    const role = r.allow === 'public' ? null : ROLE_PREF.find((x) => r.allow.includes(x))
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
