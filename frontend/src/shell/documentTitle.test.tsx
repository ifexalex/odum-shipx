import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { generatePath, Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { UserRole } from '../auth/types'
import { APP_NAME, documentTitle, useDocumentTitle } from './documentTitle'
import { PageHeader } from './PageHeader'
import { routeTable } from './routeTable'

const ALL_ROLES: UserRole[] = [
  'platform_admin',
  'tenant_admin',
  'china_office_staff',
  'nigeria_office_staff',
  'warehouse_attendant',
  'customer',
]
/** Routes that are one page under two addresses: they share a title on purpose. */
const SAME_PAGE = new Set(['/register/:slug', '/track/:code'])

const sample = (path: string): string =>
  generatePath(path, { id: 'r1', code: 'c1', token: 't1', slug: 'acme' } as Record<string, string>)

describe('tab titles (FD-48)', () => {
  it('name the record, then where it lives, then whose account it is', () => {
    expect(documentTitle('/billing/b1', ALL_ROLES, { '/billing/:id': 'INV-A-002' }, 'Acme Shipping')).toBe(
      'INV-A-002 · Billing · Acme Shipping',
    )
    expect(
      documentTitle('/packing-lists/p1/edit', ALL_ROLES, { '/packing-lists/:id': 'PL-0007' }, 'Acme Shipping'),
    ).toBe('Edit · PL-0007 · Packing lists · Acme Shipping')
  })

  it('name a record page by its route until the record has loaded', () => {
    expect(documentTitle('/billing/b1', ALL_ROLES, {}, 'Acme Shipping')).toBe('Invoice · Billing · Acme Shipping')
  })

  it('name a top-level page by its title, and end with ShipX when there is no tenant name', () => {
    expect(documentTitle('/containers', ALL_ROLES, {}, 'Acme Shipping')).toBe('Containers · Acme Shipping')
    expect(documentTitle('/login', [])).toBe(`Sign in · ${APP_NAME}`)
    expect(documentTitle('/my-shipments', ['customer'], {}, '  ')).toBe(`My shipments · ${APP_NAME}`)
    expect(documentTitle('/no/such/page', ALL_ROLES)).toBe(`Page not found · ${APP_NAME}`)
    expect(documentTitle('/', [])).toBe(APP_NAME)
  })

  // Each audience sees only its own pages, so titles must differ within one: staff, customer, and pages with no layout.
  const audiences = ['staff', 'customer', 'none'] as const
  it.each(audiences)('are distinct for every %s route', (layout) => {
    const routes = routeTable.filter(
      (r) => (layout === 'none' ? r.layout === 'none' : r.layout === layout) && !SAME_PAGE.has(r.path),
    )
    const roles = layout === 'none' ? [] : ALL_ROLES
    const titles = routes.map((r) => documentTitle(sample(r.path), roles))
    const repeated = titles.filter((t, i) => titles.indexOf(t) !== i)
    expect(repeated).toEqual([])
    expect(titles.every((t) => t !== APP_NAME && t.endsWith(` · ${APP_NAME}`))).toBe(true)
  })

  it('every route title is sentence case', () => {
    const titleCase = routeTable.filter((r) => /^\S+ [A-Z][a-z]/.test(r.title) && !/^\S+ (CBM|ShipX)\b/.test(r.title))
    expect(titleCase.map((r) => r.title)).toEqual([])
  })

  it('useDocumentTitle sets the tab title', () => {
    function Probe(): null {
      useDocumentTitle(ALL_ROLES, { '/billing/:id': 'INV-A-002' }, 'Acme Shipping')
      return null
    }
    render(
      <MemoryRouter initialEntries={['/billing/b1']}>
        <Probe />
      </MemoryRouter>,
    )
    expect(document.title).toBe('INV-A-002 · Billing · Acme Shipping')
  })
})

describe('focus after navigation (FD-48)', () => {
  function App(): React.JSX.Element {
    return (
      <Routes>
        <Route
          path="/a"
          element={
            <>
              <PageHeader title="Containers" />
              <Link to="/b">Open invoice</Link>
            </>
          }
        />
        <Route path="/b" element={<PageHeader title="Invoice INV-A-002" />} />
      </Routes>
    )
  }

  it('leaves focus alone on the first load, then moves it to the new page’s heading after a navigation', async () => {
    render(
      <MemoryRouter initialEntries={['/a']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { level: 1, name: 'Containers' })).not.toHaveFocus()
    await userEvent.click(screen.getByRole('link', { name: 'Open invoice' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Invoice INV-A-002' })).toHaveFocus()
  })
})
