import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { PageHeader } from './PageHeader'

describe('PageHeader (FD-14)', () => {
  it('is the page’s one top-level heading', () => {
    render(<PageHeader title="Invoice INV-A-002" />)
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.getByRole('heading', { level: 1, name: 'Invoice INV-A-002' })).toBeInTheDocument()
  })

  it('joins the facts of the meta line with middle dots and drops empty ones', () => {
    render(<PageHeader title="Invoice" meta={['Ngozi Adeyemi', null, '', false, 'MSCU1234567', undefined, 'Billed 9 Nov 2026']} />)
    const line = screen.getByText('Ngozi Adeyemi').closest('p')!
    expect(line).toHaveTextContent('Ngozi Adeyemi·MSCU1234567·Billed 9 Nov 2026')
    expect(line.querySelectorAll('[aria-hidden="true"]')).toHaveLength(2)
  })

  it('takes one sentence as its meta line', () => {
    render(<PageHeader title="Containers" meta="Every container, from loading to cleared." />)
    expect(screen.getByText('Every container, from loading to cleared.')).toBeInTheDocument()
  })

  it('shows the status beside the title, and actions in order: secondaries, primary, overflow', () => {
    render(
      <PageHeader
        title="Invoice"
        status={<span>Unpaid</span>}
        primary={<button type="button">Record payment</button>}
        actions={<button type="button">Export</button>}
        more={[{ label: 'Cancel invoice', tone: 'danger', onSelect: () => undefined }]}
      />,
    )
    expect(screen.getByText('Unpaid')).toBeInTheDocument()
    const buttons = screen.getAllByRole('button').map((b) => b.textContent || b.getAttribute('aria-label'))
    expect(buttons).toEqual(['Export', 'Record payment', 'More actions'])
  })

  it('folds further actions into an overflow menu', async () => {
    const cancel = vi.fn()
    render(<PageHeader title="Invoice" more={[{ label: 'Cancel invoice', onSelect: cancel }]} moreLabel="More invoice actions" />)
    await userEvent.click(screen.getByRole('button', { name: 'More invoice actions' }))
    await userEvent.click(within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Cancel invoice' }))
    expect(cancel).toHaveBeenCalledOnce()
  })

  it('renders no action row when there are no actions', () => {
    render(<PageHeader title="Reports" more={[]} primary={false} />)
    expect(screen.queryByRole('button')).toBeNull()
  })
})

describe('PageHeader title', () => {
  it('keeps a reference whole, so it moves to the next line instead of splitting at a hyphen', () => {
    render(<PageHeader title="Shipment PL-20261113-003" />)
    const heading = screen.getByRole('heading', { level: 1, name: 'Shipment PL-20261113-003' })
    const reference = within(heading).getByText('PL-20261113-003')
    expect(reference.tagName).toBe('SPAN')
    expect(reference.className).toMatch(/reference/)
  })
})
