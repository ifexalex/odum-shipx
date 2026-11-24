import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { searchApi, type SearchResult } from '../api/search'
import { GlobalSearch } from './GlobalSearch'
import type { SearchAudience } from './searchRoutes'

vi.mock('../api/search', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/search')>()),
  searchApi: { search: vi.fn() },
}))

const CONTAINER: SearchResult = { kind: 'container', id: 'c1', title: 'MSCU1234567', subtitle: 'Lagos 1', status: 'in_transit' }
const INVOICE: SearchResult = { kind: 'invoice', id: 'b1', title: 'INV-0001', subtitle: 'Ada Obi · MSCU1234567', status: 'unpaid' }
const SHIPMENT: SearchResult = { kind: 'shipment', id: 'p1', title: 'PL-0001', subtitle: null, status: null }

function Where(): JSX.Element {
  const location = useLocation()
  return <div data-testid="where">{location.pathname}</div>
}

function renderSearch(audience: SearchAudience = 'staff') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <GlobalSearch audience={audience} placeholder="Search things…" />
        <Routes>
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const box = (): HTMLElement => screen.getByRole('combobox', { name: 'Search things…' })

beforeEach(() => {
  vi.mocked(searchApi.search).mockReset()
})

describe('GlobalSearch', () => {
  it('asks for more text instead of searching on a single character', async () => {
    renderSearch()
    await userEvent.type(box(), 'M')
    expect(await screen.findByText(/at least 2 characters/i)).toBeInTheDocument()
    expect(searchApi.search).not.toHaveBeenCalled()
  })

  it('makes one request for the settled text, not one per keystroke', async () => {
    vi.mocked(searchApi.search).mockResolvedValue({ query: 'MSCU12', results: [CONTAINER] })
    renderSearch()
    await userEvent.type(box(), 'MSCU12')
    await screen.findByRole('option')
    expect(searchApi.search).toHaveBeenCalledTimes(1)
    expect(searchApi.search).toHaveBeenCalledWith('MSCU12')
  })

  it('lists results with their kind, title, detail and a readable status', async () => {
    vi.mocked(searchApi.search).mockResolvedValue({ query: 'ms', results: [CONTAINER, INVOICE] })
    renderSearch()
    await userEvent.type(box(), 'ms')
    const options = await screen.findAllByRole('option')
    expect(options).toHaveLength(2)
    expect(options[0]).toHaveTextContent('Container')
    expect(options[0]).toHaveTextContent('MSCU1234567')
    expect(options[0]).toHaveTextContent('In transit')
    expect(options[1]).toHaveTextContent('Invoice')
    expect(options[1]).toHaveTextContent('Ada Obi · MSCU1234567')
  })

  it('opens a result on click and clears the box', async () => {
    vi.mocked(searchApi.search).mockResolvedValue({ query: 'ms', results: [CONTAINER, INVOICE] })
    renderSearch()
    await userEvent.type(box(), 'ms')
    await userEvent.click(await screen.findByRole('option', { name: /INV-0001/ }))
    expect(screen.getByTestId('where')).toHaveTextContent('/billing/b1')
    expect(box()).toHaveValue('')
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('opens the top (best) match on Enter when nothing is highlighted', async () => {
    vi.mocked(searchApi.search).mockResolvedValue({ query: 'ms', results: [CONTAINER, INVOICE] })
    renderSearch()
    await userEvent.type(box(), 'ms')
    await screen.findAllByRole('option')
    await userEvent.keyboard('{Enter}')
    expect(screen.getByTestId('where')).toHaveTextContent('/containers/c1')
  })

  it('moves a highlight with the arrow keys, wrapping, and exposes it to assistive tech', async () => {
    vi.mocked(searchApi.search).mockResolvedValue({ query: 'ms', results: [CONTAINER, INVOICE] })
    renderSearch()
    await userEvent.type(box(), 'ms')
    const options = await screen.findAllByRole('option')
    await userEvent.keyboard('{ArrowDown}')
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    expect(box()).toHaveAttribute('aria-activedescendant', options[0]!.id)
    await userEvent.keyboard('{ArrowDown}{ArrowDown}')
    expect(options[0]).toHaveAttribute('aria-selected', 'true') // wrapped past the last one
    await userEvent.keyboard('{ArrowUp}{Enter}')
    expect(screen.getByTestId('where')).toHaveTextContent('/billing/b1')
  })

  it('closes the list on Escape, then clears the text on a second Escape', async () => {
    vi.mocked(searchApi.search).mockResolvedValue({ query: 'ms', results: [CONTAINER] })
    renderSearch()
    await userEvent.type(box(), 'ms')
    await screen.findByRole('listbox')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(box()).toHaveValue('ms')
    await userEvent.keyboard('{Escape}')
    expect(box()).toHaveValue('')
  })

  it('says so, with a hint, when nothing matches', async () => {
    vi.mocked(searchApi.search).mockResolvedValue({ query: 'zzzz', results: [] })
    renderSearch()
    await userEvent.type(box(), 'zzzz')
    expect(await screen.findByText(/No matches for “zzzz”/)).toBeInTheDocument()
    expect(screen.getByText(/customer name/i)).toBeInTheDocument()
  })

  it('does not suggest a customer name to a customer', async () => {
    vi.mocked(searchApi.search).mockResolvedValue({ query: 'zzzz', results: [] })
    renderSearch('customer')
    await userEvent.type(box(), 'zzzz')
    await screen.findByText(/No matches for/)
    expect(screen.queryByText(/customer name/i)).toBeNull()
    expect(screen.getByText(/tracking code/i)).toBeInTheDocument()
  })

  it('reports a failed search instead of an empty result', async () => {
    vi.mocked(searchApi.search).mockRejectedValue(
      new ApiError({ type: 'x', title: 'Server Error', status: 500, detail: 'boom', error_code: 'INTERNAL' }, null),
    )
    renderSearch()
    await userEvent.type(box(), 'ms')
    expect(await screen.findByText(/Search is unavailable right now/)).toBeInTheDocument()
    expect(screen.queryByText(/No matches/)).toBeNull()
  })

  it('drops the previous results once the text is cut back below the minimum', async () => {
    vi.mocked(searchApi.search).mockResolvedValue({ query: 'ms', results: [CONTAINER] })
    renderSearch()
    await userEvent.type(box(), 'ms')
    await screen.findByRole('option')
    await userEvent.keyboard('{Backspace}')
    expect(screen.queryByRole('option')).toBeNull()
    expect(await screen.findByText(/at least 2 characters/i)).toBeInTheDocument()
  })

  it('sends a customer to their own portal routes', async () => {
    vi.mocked(searchApi.search).mockResolvedValue({ query: 'pl', results: [SHIPMENT] })
    renderSearch('customer')
    await userEvent.type(box(), 'pl')
    await userEvent.click(await screen.findByRole('option', { name: /PL-0001/ }))
    expect(screen.getByTestId('where')).toHaveTextContent('/my-shipments/p1')
  })

  it('focuses the box on Ctrl+K and Cmd+K', async () => {
    renderSearch()
    expect(box()).not.toHaveFocus()
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    await waitFor(() => expect(box()).toHaveFocus())
    box().blur()
    fireEvent.keyDown(window, { key: 'K', metaKey: true })
    await waitFor(() => expect(box()).toHaveFocus())
  })

  it('caps the text at the length the server accepts', () => {
    renderSearch()
    expect(box()).toHaveAttribute('maxlength', '64')
  })

  it('opens the phone-width bar from its icon button', async () => {
    renderSearch()
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(box()).toHaveFocus())
  })
})
