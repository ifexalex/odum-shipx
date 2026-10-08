import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { CustShell } from './CustShell'
import { CustomerTopNav } from './CustomerTopNav'

const links = [
  { icon: 'package' as const, label: 'My Shipments', path: '/my-shipments' },
  { icon: 'coin' as const, label: 'Billing', path: '/my-billing', count: 1 },
]

// The hamburger/drawer only do anything when CustomerTopNav is rendered
// inside a CustShell (the ShellDrawer context provider) — mirrors exactly
// how TopBar's own hamburger needs a PageShell ancestor, per
// ShellDrawer.tsx's "null outside a provider" contract.
function renderWithDrawer(initialPath = '/my-shipments') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <CustShell topnav={<CustomerTopNav links={links} />}>
        <div>page content</div>
      </CustShell>
    </MemoryRouter>,
  )
}

describe('CustomerTopNav', () => {
  it('marks the link matching the current path as active', () => {
    render(
      <MemoryRouter initialEntries={['/my-billing/123']}>
        <CustomerTopNav links={links} />
      </MemoryRouter>,
    )
    expect(screen.getByText('Billing').closest('button')?.className).toMatch(/navLinkActive/)
    expect(screen.getByText('My Shipments').closest('button')?.className).not.toMatch(/navLinkActive/)
  })

  it('shows a count badge when provided', () => {
    render(
      <MemoryRouter initialEntries={['/my-shipments']}>
        <CustomerTopNav links={links} />
      </MemoryRouter>,
    )
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('calls onLogout when the logout button is clicked', async () => {
    const onLogout = vi.fn()
    render(
      <MemoryRouter initialEntries={['/my-shipments']}>
        <CustomerTopNav links={links} onLogout={onLogout} />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(onLogout).toHaveBeenCalledOnce()
  })

  it('renders notificationsPanel inside the bell\'s own positioning wrapper', () => {
    render(
      <MemoryRouter initialEntries={['/my-shipments']}>
        <CustomerTopNav
          links={links}
          notifications={2}
          notificationsPanel={<div data-testid="notif-panel">panel content</div>}
        />
      </MemoryRouter>,
    )
    const panel = screen.getByTestId('notif-panel')
    expect(panel).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /notifications/i }).parentElement).toContainElement(panel)
  })

  it('omits the logout button when onLogout is not given', () => {
    render(
      <MemoryRouter initialEntries={['/my-shipments']}>
        <CustomerTopNav links={links} />
      </MemoryRouter>,
    )
    expect(screen.queryByRole('button', { name: 'Log out' })).toBeNull()
  })

  it('does not render a hamburger button when there is no ShellDrawer context (standalone)', () => {
    render(
      <MemoryRouter initialEntries={['/my-shipments']}>
        <CustomerTopNav links={links} />
      </MemoryRouter>,
    )
    expect(screen.queryByRole('button', { name: 'Open menu' })).toBeNull()
  })

  describe('mobile drawer (inside a CustShell)', () => {
    it('opens on hamburger click and shows the same links again in the drawer panel', async () => {
      renderWithDrawer()
      await userEvent.click(screen.getByRole('button', { name: 'Open menu' }))
      // Now present twice — once in the (CSS-hidden-on-mobile, still-in-DOM)
      // horizontal bar, once in the drawer panel.
      expect(screen.getAllByText('Billing')).toHaveLength(2)
    })

    it('closes when a link inside the drawer is clicked (and still navigates)', async () => {
      renderWithDrawer('/my-shipments')
      await userEvent.click(screen.getByRole('button', { name: 'Open menu' }))
      const billingLinks = screen.getAllByText('Billing')
      await userEvent.click(billingLinks[billingLinks.length - 1]!)
      expect(screen.getAllByText('Billing')).toHaveLength(1)
      expect(screen.getByText('Billing').closest('button')?.className).toMatch(/navLinkActive/)
    })

    it('closes on overlay click', async () => {
      const { container } = renderWithDrawer()
      await userEvent.click(screen.getByRole('button', { name: 'Open menu' }))
      expect(screen.getAllByText('Billing')).toHaveLength(2)
      const overlay = container.querySelector('[class*="drawerOverlay"]')
      expect(overlay).toBeTruthy()
      await userEvent.click(overlay!)
      expect(screen.getAllByText('Billing')).toHaveLength(1)
    })

    it('closes on Escape', async () => {
      renderWithDrawer()
      await userEvent.click(screen.getByRole('button', { name: 'Open menu' }))
      expect(screen.getAllByText('Billing')).toHaveLength(2)
      await userEvent.keyboard('{Escape}')
      expect(screen.getAllByText('Billing')).toHaveLength(1)
    })
  })
})
