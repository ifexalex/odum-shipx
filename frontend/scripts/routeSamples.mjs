/**
 * Every route in src/shell/routeTable.ts, with a real URL to open it at and a role that may open it.
 *
 * Shared by the scripts and specs that open the whole app with local dev auth: scripts/mobile-audit.mjs (phone widths)
 * and e2e/visual/visual.spec.ts (the screenshot baseline, FD-38). A route with a parameter is opened on the first
 * matching record the local API returns, so the page shows real data; one with no record falls back to "sample".
 *
 * Needs the local API (`make dev`, :3000). Reads routeTable.ts as text, so a new route is covered with no change here
 * unless it has a new kind of parameter: then add it to PARAM.
 */
import fs from 'node:fs'

export const API = process.env.API_URL ?? 'http://localhost:3000'
export const APP = process.env.APP_URL ?? 'http://localhost:5173'
export const TENANT = process.env.AUDIT_TENANT ?? '10000000-0000-0000-0000-000000000001'

/** The role a route is opened as: the first of these it allows. */
export const ROLE_PREF = [
  'tenant_admin',
  'nigeria_office_staff',
  'china_office_staff',
  'warehouse_attendant',
  'platform_admin',
  'customer',
]

async function firstId(role, path, tenant = TENANT) {
  const res = await fetch(`${API}/v1/${path}`, { headers: { 'X-Tenant-ID': tenant, 'X-Role': role } })
  const body = await res.json().catch(() => ({}))
  const data = Array.isArray(body.data) ? body.data[0] : body.data
  return data?.id ?? 'sample'
}

/** Route path pattern → the record ID its parameter is filled with. */
export async function sampleIds() {
  const [tenant, user, customer, container, pl, manifest, billing, claim, refund, rn, cpl, mybilling, myclaim] =
    await Promise.all([
      firstId('platform_admin', 'platform/tenants?limit=1', 'PLATFORM'),
      firstId('tenant_admin', 'tenant/users?limit=1'),
      firstId('tenant_admin', 'customers?limit=1'),
      firstId('china_office_staff', 'containers?limit=1'),
      firstId('china_office_staff', 'packing-lists?limit=1'),
      firstId('nigeria_office_staff', 'manifests?limit=1'),
      firstId('nigeria_office_staff', 'billing?limit=1'),
      firstId('nigeria_office_staff', 'claims?limit=1'),
      firstId('nigeria_office_staff', 'refunds?limit=1'),
      firstId('nigeria_office_staff', 'release-notes?limit=1'),
      firstId('customer', 'packing-lists?limit=1'),
      firstId('customer', 'billing?limit=1'),
      firstId('customer', 'claims?limit=1'),
    ])
  return {
    '/platform/tenants/:id': tenant,
    '/admin/users/:id': user,
    '/admin/customers/:id': customer,
    '/containers/:id': container,
    '/packing-lists/:id': pl,
    '/packing-lists/:id/edit': pl,
    '/manifests/:id': manifest,
    '/billing/:id': billing,
    '/claims/:id': claim,
    '/refunds/:id': refund,
    '/release-notes/:id': rn,
    '/my-shipments/:code': cpl,
    '/my-billing/:id': mybilling,
    '/my-billing/:id/payment-success': mybilling,
    '/my-billing/:id/refund-request': mybilling,
    '/my-release-notes/:id': rn,
    '/my-claims/:id': myclaim,
  }
}

/** Every route: `{ path, allow, role }`, where `role` is null for a public page. */
export function loadRoutes() {
  const table = fs.readFileSync(new URL('../src/shell/routeTable.ts', import.meta.url), 'utf8')
  return [...table.matchAll(/\{\s*path: '([^']+)',\s*(?:\/\/[^\n]*\n\s*)*allow: (\[[^\]]*\]|'public')/g)].map((m) => {
    const allow = m[2] === "'public'" ? 'public' : JSON.parse(m[2].replace(/'/g, '"'))
    return { path: m[1], allow, role: allow === 'public' ? null : ROLE_PREF.find((r) => allow.includes(r)) }
  })
}

/** The URL to open `path` at, its parameter filled from `ids` (or "sample"). */
export function sampleUrl(path, ids) {
  return ids[path] ? path.replace(/:(id|code)/, ids[path]) : path.replace(/:(\w+)/g, 'sample')
}
