import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { claimsApi, type Claim } from '../../api/claims'
import { MyClaims } from './MyClaims'

vi.mock('../../api/claims', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/claims')>()),
  claimsApi: { get: vi.fn(), list: vi.fn() },
}))

function claim(overrides: Partial<Claim> = {}): Claim {
  return {
    id: 'aaaabbbb-cccc-dddd-eeee-111122223333',
    reference: 'DC-20261110-001',
    status: 'resolved',
    container_id: 'k1',
    container_number: 'MSCU1234567',
    customer_id: 'c1',
    customer_name: 'Ngozi',
    description: 'Soaked cartons',
    inspection_method: null,
    cartons_affected: ['T1'],
    upload_urls: null,
    created_at: '2026-11-10T10:00:00Z',
    ...overrides,
  }
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/my-claims']}>
        <Routes>
          <Route path="/my-claims" element={<MyClaims />} />
          <Route path="/my-claims/:id" element={<div>Detail for {location.pathname}</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(claimsApi.list).mockReset()
  vi.mocked(claimsApi.list).mockResolvedValue({
    data: [claim()],
    meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
  })
})

describe('MyClaims (UX-06, UX-07)', () => {
  it('identifies a claim by its reference, not a fragment of its id', async () => {
    renderPage()
    expect(await screen.findByText('DC-20261110-001')).toBeInTheDocument()
    expect(screen.queryByText(/aaaabbbb/)).toBeNull()
  })

  it('falls back to the id only when the claim has no reference', async () => {
    vi.mocked(claimsApi.list).mockResolvedValue({
      data: [claim({ reference: null })],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    renderPage()
    expect(await screen.findByText('aaaabbbb…')).toBeInTheDocument()
  })

  it('opens the claim when its card is clicked', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('link', { name: 'Open claim DC-20261110-001' }))
    expect(await screen.findByText(/Detail for/)).toBeInTheDocument()
  })

  it('opens the claim from the keyboard', async () => {
    renderPage()
    const card = await screen.findByRole('link', { name: 'Open claim DC-20261110-001' })
    card.focus()
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByText(/Detail for/)).toBeInTheDocument()
  })

  it('is reachable by Tab, like any link', async () => {
    renderPage()
    const card = await screen.findByRole('link', { name: 'Open claim DC-20261110-001' })
    expect(card).toHaveAttribute('tabindex', '0')
  })
})
