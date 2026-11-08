/**
 * 4.4 / audit gap B8 — charge-type settings: the "Times used" column surfaces
 * per-type usage counts (misc charges attributed via charge_type_id), and the
 * amount renders from the wire `amount_ngn` field (backend maps it from the
 * `default_amount_ngn` column).
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { withQuery } from '../../test/queryWrapper'
import { configApi, type ChargeType } from '../../api/tenantManagement'
import { ChargeTypes } from './ChargeTypes'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return { ...original, configApi: { ...original.configApi, listChargeTypes: vi.fn() } }
})

function type(overrides: Partial<ChargeType>): ChargeType {
  return {
    id: 'ct1', name: 'Customs exam', description: 'Port examination',
    amount_ngn: '15000', is_active: true, usage_count: 0, ...overrides,
  }
}

function renderPage() {
  return render(
    withQuery(
      <MemoryRouter>
        <ChargeTypes />
      </MemoryRouter>,
    ),
  )
}

describe('ChargeTypes usage counts (B8)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders the usage count and amount for each charge type', async () => {
    vi.mocked(configApi.listChargeTypes).mockResolvedValue([
      type({ id: 'ct1', name: 'Customs exam', amount_ngn: '15000', usage_count: 7 }),
      type({ id: 'ct2', name: 'Port handling', amount_ngn: '2500', usage_count: 0 }),
    ])
    renderPage()

    const customs = await screen.findByText('Customs exam')
    const customsRow = customs.closest('tr') as HTMLElement
    expect(within(customsRow).getByText('7×')).toBeInTheDocument()
    expect(within(customsRow).getByText('₦15,000')).toBeInTheDocument()

    const handlingRow = screen.getByText('Port handling').closest('tr') as HTMLElement
    expect(within(handlingRow).getByText('0×')).toBeInTheDocument()
  })

  it('falls back to 0× when usage_count is absent', async () => {
    vi.mocked(configApi.listChargeTypes).mockResolvedValue([
      type({ id: 'ct1', name: 'Legacy type', usage_count: undefined }),
    ])
    renderPage()

    await waitFor(() => expect(screen.getByText('Legacy type')).toBeInTheDocument())
    const row = screen.getByText('Legacy type').closest('tr') as HTMLElement
    expect(within(row).getByText('0×')).toBeInTheDocument()
  })
})
