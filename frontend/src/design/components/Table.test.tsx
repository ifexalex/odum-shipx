import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Table, type TableColumn, type TableRow } from './Table'

const columns: TableColumn[] = [
  { title: 'Container', sortable: true },
  { title: 'Status' },
  { title: 'Weight', align: 'right' },
]

const rows: TableRow[] = [
  { cells: ['SHPX-001', 'In transit', '1,200kg'] },
  { cells: ['SHPX-002', 'Cleared', '900kg'], selected: true },
]

/** Table.tsx's mobile switch is ResizeObserver-driven, not a CSS query
 * (jsdom can't evaluate @container/@media at all) — it measures its own
 * wrapper via getBoundingClientRect() on mount, which jsdom always
 * reports as all-zero by default (the "stay in table view" default every
 * other test in this file relies on). Stubbing a nonzero, narrow width
 * here is what actually exercises the card view. */
function stubNarrowWidth(width: number): void {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    width,
    height: 100,
    top: 0,
    left: 0,
    right: width,
    bottom: 100,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
}

describe('Table', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders column headers and row cells', () => {
    render(<Table columns={columns} rows={rows} />)
    expect(screen.getByText('Container')).toBeInTheDocument()
    expect(screen.getByText('SHPX-001')).toBeInTheDocument()
    expect(screen.getByText('900kg')).toBeInTheDocument()
  })

  it('calls onSort with the column index when a sortable header is clicked', async () => {
    const onSort = vi.fn()
    render(<Table columns={columns} rows={rows} onSort={onSort} />)
    await userEvent.click(screen.getByText('Container'))
    expect(onSort).toHaveBeenCalledWith(0)
  })

  it('renders a select-all checkbox and per-row checkboxes when selectable', async () => {
    const onSelectRow = vi.fn()
    const onSelectAll = vi.fn()
    render(
      <Table
        columns={columns}
        rows={rows}
        selectable
        onSelectRow={onSelectRow}
        onSelectAll={onSelectAll}
      />,
    )
    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes).toHaveLength(rows.length + 1)
    await userEvent.click(checkboxes[1]!)
    expect(onSelectRow).toHaveBeenCalledWith(0, true)
    await userEvent.click(checkboxes[0]!)
    expect(onSelectAll).toHaveBeenCalledWith(true)
  })

  it('shows a select-all checkbox in the mixed state when some rows are selected', () => {
    render(<Table columns={columns} rows={rows} selectable />)
    expect(screen.getAllByRole('checkbox')[0]).toHaveAttribute('aria-checked', 'mixed')
  })

  it('renders skeleton rows while loading', () => {
    const { container } = render(<Table columns={columns} rows={[]} loading />)
    expect(container.querySelectorAll('tbody tr')).toHaveLength(5)
  })

  it('renders custom empty state when there are no rows', () => {
    render(<Table columns={columns} rows={[]} emptyState={<span>No shipments yet</span>} />)
    expect(screen.getByText('No shipments yet')).toBeInTheDocument()
  })

  it('applies dense padding to cells', () => {
    const { container } = render(<Table columns={columns} rows={rows} dense />)
    const firstRow = container.querySelectorAll<HTMLTableRowElement>('tbody tr')[0]!
    const firstCell = within(firstRow).getAllByRole('cell')[0]
    expect(firstCell?.className).toMatch(/tdDense/)
  })

  describe('mobile card view (width <= 860px)', () => {
    it('renders no <table> at all, and shows column 0 as each card header', () => {
      stubNarrowWidth(375)
      const { container } = render(<Table columns={columns} rows={rows} />)
      expect(container.querySelector('table')).not.toBeInTheDocument()
      expect(screen.getByText('SHPX-001')).toBeInTheDocument()
      expect(screen.getByText('SHPX-002')).toBeInTheDocument()
    })

    it('respects a custom cardBreakpoint — stays tabular above it', () => {
      // A ~776px dashboard column is below the 860px default (would card-ify)
      // but above a 600px override, so it must stay a real table.
      stubNarrowWidth(776)
      const { container } = render(<Table columns={columns} rows={rows} cardBreakpoint={600} />)
      expect(container.querySelector('table')).toBeInTheDocument()
    })

    it('respects a custom cardBreakpoint — cards below it (real phone width)', () => {
      stubNarrowWidth(375)
      const { container } = render(<Table columns={columns} rows={rows} cardBreakpoint={600} />)
      expect(container.querySelector('table')).not.toBeInTheDocument()
    })

    it('renders every other column as a label:value pair', () => {
      stubNarrowWidth(375)
      render(<Table columns={columns} rows={rows} />)
      expect(screen.getAllByText('Status')).toHaveLength(2) // one per card
      expect(screen.getByText('In transit')).toBeInTheDocument()
      expect(screen.getAllByText('Weight')).toHaveLength(2)
      expect(screen.getByText('900kg')).toBeInTheDocument()
    })

    it('renders a trailing empty-title column as the card action row, not a label:value pair', () => {
      stubNarrowWidth(375)
      const actionColumns: TableColumn[] = [...columns, { title: '', width: '40px' }]
      const actionRows: TableRow[] = [{ cells: [...rows[0]!.cells, <button key="a">View</button>] }]
      render(<Table columns={actionColumns} rows={actionRows} />)
      expect(screen.getByRole('button', { name: 'View' })).toBeInTheDocument()
      // No stray empty-string label rendered for the action column.
      expect(screen.getAllByText('Status')).toHaveLength(1)
    })

    it('omits a column marked hideInCard', () => {
      stubNarrowWidth(375)
      const withHidden: TableColumn[] = [columns[0]!, { ...columns[1]!, hideInCard: true }, columns[2]!]
      render(<Table columns={withHidden} rows={rows} />)
      expect(screen.queryByText('Status')).not.toBeInTheDocument()
      expect(screen.getAllByText('Weight')).toHaveLength(2)
    })

    it('still supports row selection', async () => {
      stubNarrowWidth(375)
      const onSelectRow = vi.fn()
      const onSelectAll = vi.fn()
      render(<Table columns={columns} rows={rows} selectable onSelectRow={onSelectRow} onSelectAll={onSelectAll} />)
      const checkboxes = screen.getAllByRole('checkbox')
      expect(checkboxes).toHaveLength(rows.length + 1) // "Select all" + one per card
      await userEvent.click(checkboxes[1]!)
      expect(onSelectRow).toHaveBeenCalledWith(0, true)
      await userEvent.click(checkboxes[0]!)
      expect(onSelectAll).toHaveBeenCalledWith(true)
    })

    it('renders skeleton cards while loading', () => {
      stubNarrowWidth(375)
      const { container } = render(<Table columns={columns} rows={[]} loading />)
      expect(container.querySelectorAll('[class*="card"]').length).toBeGreaterThan(0)
      expect(container.querySelector('table')).not.toBeInTheDocument()
    })

    it('renders the custom empty state', () => {
      stubNarrowWidth(375)
      render(<Table columns={columns} rows={[]} emptyState={<span>No shipments yet</span>} />)
      expect(screen.getByText('No shipments yet')).toBeInTheDocument()
    })
  })

  it('stays in table view at a wide measured width', () => {
    stubNarrowWidth(1200)
    const { container } = render(<Table columns={columns} rows={rows} />)
    expect(container.querySelector('table')).toBeInTheDocument()
  })
})
