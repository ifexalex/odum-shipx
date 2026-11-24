/**
 * Breadcrumbs (audit FD-45/FD-46). Walks every route in the route table and checks its trail against the table the
 * brief set out: where the page lives, every crumb but the last a link, no sidebar group names, the same for every
 * role. A route added without an expected trail fails here.
 */
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { UserRole } from '../auth/types'
import { Breadcrumb } from './Breadcrumb'
import { breadcrumbTrail, matchRoute, type Crumb } from './breadcrumbs'
import { routeTable } from './routeTable'

const ALL_ROLES: UserRole[] = [
  'platform_admin',
  'tenant_admin',
  'china_office_staff',
  'nigeria_office_staff',
  'warehouse_attendant',
  'customer',
]

/** Fill `:id`, `:code`, `:token`, `:slug` with a sample value so a pattern becomes a real URL. */
const sample = (path: string): string => path.replace(/:(\w+)/g, (_, name: string) => `${name.toUpperCase()}1`)

/** Expected trail per route: `[label, link]` for each ancestor, then the current page's label. Absent = no trail. */
const EXPECTED: Record<string, (string | [string, string])[]> = {
  '/platform/tenants/new': [['Tenants', '/platform/tenants'], 'New tenant'],
  '/platform/tenants/:id': [['Tenants', '/platform/tenants'], 'Tenant'],
  '/platform/settings/notifications': [['Settings', '/platform/settings'], 'Notifications'],
  '/platform/settings/plans': [['Settings', '/platform/settings'], 'Plans'],
  '/admin/users/:id': [['Staff', '/admin/users'], 'Staff member'],
  '/admin/customers/:id': [['Customers', '/admin/customers'], 'Customer'],
  '/admin/config/dollar-rate': [['Settings', '/admin/config'], 'Dollar rate'],
  '/admin/config/cbm-rate': [['Settings', '/admin/config'], 'CBM rate'],
  '/admin/config/charge-types': [['Settings', '/admin/config'], 'Charge types'],
  '/admin/config/container-capacities': [['Settings', '/admin/config'], 'Container capacities'],
  '/admin/config/warehouses': [['Settings', '/admin/config'], 'Warehouses'],
  '/admin/config/notifications': [['Settings', '/admin/config'], 'Notification templates'],
  '/admin/config/webhooks': [['Settings', '/admin/config'], 'Webhooks'],
  '/admin/config/payments': [['Settings', '/admin/config'], 'Payments'],
  '/containers/new': [['Containers', '/containers'], 'New container'],
  '/containers/:id': [['Containers', '/containers'], 'Container'],
  '/packing-lists/new': [['Packing lists', '/packing-lists'], 'New packing list'],
  '/packing-lists/import': [['Packing lists', '/packing-lists'], 'Import from Excel'],
  '/packing-lists/:id': [['Packing lists', '/packing-lists'], 'Packing list'],
  '/packing-lists/:id/edit': [['Packing lists', '/packing-lists'], ['Packing list', '/packing-lists/ID1'], 'Edit'],
  '/manifests/:id': [['Manifests', '/manifests'], 'Manifest'],
  '/billing/:id': [['Billing', '/billing'], 'Invoice'],
  '/billing/disputes': [['Billing', '/billing'], 'CBM disputes'],
  '/billing/disputes/:id': [['Billing', '/billing'], ['CBM disputes', '/billing/disputes'], 'Dispute'],
  '/billing/carryovers': [['Billing', '/billing'], 'Carryover ledger'],
  '/claims/:id': [['Damage claims', '/claims'], 'Claim'],
  '/refunds/:id': [['Refunds', '/refunds'], 'Refund'],
  '/release-notes/:id': [['Release notes', '/release-notes'], 'Release note'],
  '/my-shipments/:code': [['My shipments', '/my-shipments'], 'Shipment'],
  '/my-billing/:id': [['Billing', '/my-billing'], 'Invoice'],
  '/my-billing/:id/payment-success': [['Billing', '/my-billing'], ['Invoice', '/my-billing/ID1'], 'Payment received'],
  '/my-billing/:id/refund-request': [['Billing', '/my-billing'], ['Invoice', '/my-billing/ID1'], 'Request a refund'],
  '/payment-failed': [['Billing', '/my-billing'], 'Payment failed'],
  '/my-release-notes/:id': [['My shipments', '/my-shipments'], 'Release note'],
  '/my-claims/new': [['Claims', '/my-claims'], 'New claim'],
  '/my-claims/:id': [['Claims', '/my-claims'], 'Claim'],
}

const asCrumbs = (spec: (string | [string, string])[]): Crumb[] =>
  spec.map((part) => (typeof part === 'string' ? { label: part } : { label: part[0], to: part[1] }))

describe('every route has the trail the brief sets out (FD-46)', () => {
  it.each(routeTable.map((route) => [route.path] as const))('%s', (path) => {
    const trail = breadcrumbTrail(sample(path), ALL_ROLES)
    expect(trail).toEqual(asCrumbs(EXPECTED[path] ?? []))
  })

  it('lists no expectation for a route that does not exist', () => {
    const paths = new Set(routeTable.map((route) => route.path))
    expect(Object.keys(EXPECTED).filter((path) => !paths.has(path))).toEqual([])
  })

  it('never uses a sidebar group name', () => {
    const groups = ['Operations', 'Billing & Disputes', 'Coordination', 'Packing lists group']
    for (const route of routeTable) {
      for (const crumb of breadcrumbTrail(sample(route.path), ALL_ROLES)) {
        expect(groups).not.toContain(crumb.label)
      }
    }
  })
})

describe('the trail (FD-45)', () => {
  it('links every crumb but the last', () => {
    for (const route of routeTable) {
      const trail = breadcrumbTrail(sample(route.path), ALL_ROLES)
      trail.slice(0, -1).forEach((crumb) => expect(crumb.to, `${route.path}: ${crumb.label}`).toBeTruthy())
      if (trail.length) expect(trail.at(-1)?.to).toBeUndefined()
    }
  })

  it('names a record page by its record once the page supplies it, and a parent record too', () => {
    expect(breadcrumbTrail('/billing/abc', ALL_ROLES, { '/billing/:id': 'ACM-INV-0042' })).toEqual([
      { label: 'Billing', to: '/billing' },
      { label: 'ACM-INV-0042' },
    ])
    expect(breadcrumbTrail('/packing-lists/p1/edit', ALL_ROLES, { '/packing-lists/:id': 'PL-0007' })).toEqual([
      { label: 'Packing lists', to: '/packing-lists' },
      { label: 'PL-0007', to: '/packing-lists/p1' },
      { label: 'Edit' },
    ])
  })

  it('is the same for every role that may open the page and the pages above it', () => {
    const byPath = new Map(routeTable.map((route) => [route.path, route]))
    const opens = (role: UserRole, path: string | undefined): boolean => {
      const route = path ? byPath.get(path) : undefined
      if (!route) return true
      return (route.allow === 'public' || route.allow.includes(role)) && opens(role, route.parent)
    }
    for (const route of routeTable) {
      if (route.allow === 'public') continue
      const roles = route.allow.filter((role) => opens(role, route.path))
      const trails = roles.map((role) => JSON.stringify(breadcrumbTrail(sample(route.path), [role])))
      expect(new Set(trails).size, route.path).toBeLessThanOrEqual(1)
    }
  })

  it('leaves out a parent the role cannot open, instead of a link that bounces them home', () => {
    // China staff can open CBM disputes but not billing.
    expect(breadcrumbTrail('/billing/disputes/d1', ['china_office_staff'])).toEqual([
      { label: 'CBM disputes', to: '/billing/disputes' },
      { label: 'Dispute' },
    ])
    // With nothing left above the page, there is no breadcrumb rather than a lone crumb repeating the title.
    expect(breadcrumbTrail('/billing/disputes', ['china_office_staff'])).toEqual([])
  })

  it('matches the literal route before a parameter one', () => {
    expect(matchRoute('/billing/disputes')?.route.path).toBe('/billing/disputes')
    expect(matchRoute('/claims/missing-items')?.route.path).toBe('/claims/missing-items')
    expect(matchRoute('/packing-lists/new')?.route.path).toBe('/packing-lists/new')
  })
})

describe('Breadcrumb', () => {
  const trail: Crumb[] = [
    { label: 'Billing', to: '/my-billing' },
    { label: 'ACM-INV-0042', to: '/my-billing/b1' },
    { label: 'Request a refund' },
  ]

  it('is a labelled navigation landmark with an ordered list of links and the current page', () => {
    render(
      <MemoryRouter>
        <Breadcrumb trail={trail} />
      </MemoryRouter>,
    )
    const nav = screen.getByRole('navigation', { name: 'Breadcrumb' })
    const list = within(nav).getByRole('list')
    expect(list.tagName).toBe('OL')
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(within(items[0]!).getByRole('link', { name: 'Billing' })).toHaveAttribute('href', '/my-billing')
    expect(within(items[1]!).getByRole('link', { name: 'ACM-INV-0042' })).toHaveAttribute('href', '/my-billing/b1')
    expect(within(items[2]!).queryByRole('link')).toBeNull()
    expect(within(items[2]!).getByText('Request a refund')).toHaveAttribute('aria-current', 'page')
  })

  it('carries a single back link to the parent for narrow screens', () => {
    render(
      <MemoryRouter>
        <Breadcrumb trail={trail} />
      </MemoryRouter>,
    )
    const links = screen.getAllByRole('link', { name: /ACM-INV-0042/ })
    // One in the trail, one as the back link (CSS shows one or the other by width).
    expect(links).toHaveLength(2)
    expect(links.every((a) => a.getAttribute('href') === '/my-billing/b1')).toBe(true)
  })

  it('renders nothing for a top-level page', () => {
    const { container } = render(
      <MemoryRouter>
        <Breadcrumb trail={[]} />
      </MemoryRouter>,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
