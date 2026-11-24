import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StatCard } from '../design/components'
import { FilterBar } from './FilterBar'
import { ListPage, StatRow } from './ListPage'

describe('ListPage (FD-18)', () => {
  it('lays a list out in one order: header, notices, stats, filters, table, footer', () => {
    render(
      <ListPage
        header={<h1>Billing</h1>}
        notices={<p>Notice</p>}
        stats={<p>Stats</p>}
        filters={<p>Filters</p>}
        footer={<p>Footer</p>}
      >
        <p>Table</p>
      </ListPage>,
    )
    const order = ['Billing', 'Notice', 'Stats', 'Filters', 'Table', 'Footer'].map((text) => screen.getByText(text))
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1]!.compareDocumentPosition(order[i]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
  })

  afterEach(() => vi.restoreAllMocks())

  it('warns when a page shows more than four stats', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    render(
      <StatRow>
        {[1, 2, 3, 4, 5].map((n) => (
          <StatCard key={n} label={`Stat ${n}`} value={n} />
        ))}
      </StatRow>,
    )
    expect(error).toHaveBeenCalledWith(expect.stringContaining('at most 4'))
  })

  it('a stat card that applies a filter is a toggle button', async () => {
    const onSelect = vi.fn()
    render(<StatCard label="Overdue" value={3} selected onSelect={onSelect} />)
    const button = screen.getByRole('button', { name: /Overdue/ })
    expect(button).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(button)
    expect(onSelect).toHaveBeenCalledOnce()
  })
})

describe('FilterBar (FD-18)', () => {
  const bar = (props: Partial<Parameters<typeof FilterBar>[0]> = {}) =>
    render(
      <FilterBar
        label="Filter invoices"
        status={<button type="button">All</button>}
        search={<input aria-label="Search invoices" />}
        dateRange={<button type="button">Billed: all time</button>}
        more={<label>Status <select /></label>}
        activeCount={2}
        onClear={vi.fn()}
        {...props}
      />,
    )

  it('is a named search landmark with its controls in the fixed order: status, search, date range, more', () => {
    bar()
    const region = screen.getByRole('search', { name: 'Filter invoices' })
    const [status, search, date, more] = [
      within(region).getByRole('button', { name: 'All' }),
      within(region).getByRole('textbox', { name: 'Search invoices' }),
      within(region).getByRole('button', { name: 'Billed: all time' }),
      within(region).getByRole('button', { name: 'More filters (2)' }),
    ]
    for (const [a, b] of [[status, search], [search, date], [date, more]] as const) {
      expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
  })

  it('opens the less-used filters from More filters, with a clear-all', async () => {
    const onClear = vi.fn()
    bar({ onClear })
    expect(screen.queryByRole('dialog', { name: 'More filters' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'More filters (2)' }))
    const panel = screen.getByRole('dialog', { name: 'More filters' })
    expect(within(panel).getByLabelText('Status')).toBeInTheDocument()
    await userEvent.click(within(panel).getByRole('button', { name: 'Clear all filters' }))
    expect(onClear).toHaveBeenCalledOnce()
  })

  it('shows no More filters button when there are none', () => {
    bar({ more: undefined, activeCount: 0 })
    expect(screen.queryByRole('button', { name: /More filters/ })).toBeNull()
  })
})
