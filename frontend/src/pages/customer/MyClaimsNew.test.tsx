/**
 * Regression guard for the 2026-09-06 fix: a claim used to be filable
 * against any container a customer typed, including one still `loading` or
 * `in_transit` — damage/loss can't be assessed before cargo arrives. Step 1
 * now picks from a dropdown of the customer's own arrived shipments instead
 * of a free-text container field, so a non-arrived one is never offered.
 * `services/claims/service.py::file_claim` enforces the same rule server-side.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { packingListApi } from '../../api/packingList'
import { MyClaimsNew } from './MyClaimsNew'

vi.mock('../../api/packingList', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/packingList')>()
  return { ...original, packingListApi: { ...original.packingListApi, list: vi.fn() } }
})
vi.mock('../../api/claims', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/claims')>()
  return { ...original, claimsApi: { ...original.claimsApi, file: vi.fn() } }
})

function shipment(id: string, reference: string, status: string) {
  return {
    id,
    reference,
    customer_id: 'c1',
    container_id: `cont-${id}`,
    container_number: `CONT-${id}`,
    container_status: status,
    status: 'approved',
    carton_count: 2,
    total_cbm: '0.051',
    created_at: '2026-09-01T11:42:00Z',
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <MyClaimsNew />
    </MemoryRouter>,
  )
}

describe('MyClaimsNew — only arrived shipments can be claimed against', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('offers no claim option and explains why when nothing has arrived', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [shipment('pl1', 'PL-001', 'loading'), shipment('pl2', 'PL-002', 'in_transit')],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    } as never)

    renderPage()

    expect(await screen.findByText('Nothing to claim against yet')).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.queryByRole('button', { name: /next: add evidence/i })).toBeNull()
  })

  it('lists only the arrived shipments, excluding ones still in transit', async () => {
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [
        shipment('pl1', 'PL-LOADING', 'loading'),
        shipment('pl2', 'PL-ARRIVED', 'at_warehouse'),
        shipment('pl3', 'PL-SEALED', 'sealed'),
      ],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 3 } },
    } as never)

    renderPage()

    const select = await screen.findByRole('combobox')
    const optionTexts = Array.from(select.querySelectorAll('option')).map((o) => o.textContent)
    expect(optionTexts.some((t) => t?.includes('PL-ARRIVED'))).toBe(true)
    expect(optionTexts.some((t) => t?.includes('PL-LOADING'))).toBe(false)
    expect(optionTexts.some((t) => t?.includes('PL-SEALED'))).toBe(false)
  })

  it('submits the arrived shipment container, not a free-text value', async () => {
    const { claimsApi } = await import('../../api/claims')
    vi.mocked(packingListApi.list).mockResolvedValue({
      data: [shipment('pl1', 'PL-ARRIVED', 'at_warehouse')],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)
    vi.mocked(claimsApi.file).mockResolvedValue({ id: 'claim1' } as never)

    renderPage()

    const select = await screen.findByRole('combobox')
    await userEvent.selectOptions(select, 'pl1')
    await userEvent.type(screen.getByLabelText(/description of damage/i), 'crushed carton')
    await userEvent.click(screen.getByRole('button', { name: /next: add evidence/i }))

    expect(await screen.findByText(/attach photos or videos/i)).toBeInTheDocument()
    expect(claimsApi.file).toHaveBeenCalledWith(
      expect.objectContaining({ container_id: 'CONT-pl1', description: 'crushed carton' }),
      expect.any(String),
    )
  })
})
