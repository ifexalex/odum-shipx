/**
 * B7 — rate trend chart on the rate pages. The shared RateHistoryTable fetches
 * history once and renders both the trend chart (≥2 points) and the table.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { configApi, type RateHistoryEntry } from '../../api/tenantManagement'
import { RateHistoryTable } from './DollarRateConfig'
import { withQuery } from '../../test/queryWrapper'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return { ...original, configApi: { ...original.configApi, rateHistory: vi.fn() } }
})

function entry(rate: number, prev: number | null, date: string): RateHistoryEntry {
  return {
    id: `r-${date}`,
    rate_type: 'dollar_rate',
    rate_value: { rate },
    previous_value: prev == null ? null : { rate: prev },
    changed_by: 'Amara',
    effective_from: date,
    created_at: date,
  }
}

// Newest-first, as the endpoint returns.
const HISTORY = [
  entry(1650, 1600, '2026-07-01T00:00:00Z'),
  entry(1600, 1550, '2026-06-01T00:00:00Z'),
  entry(1550, null, '2026-05-01T00:00:00Z'),
]

describe('RateHistoryTable + trend chart (B7)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders the trend chart with a net-change summary when there are ≥2 points', async () => {
    vi.mocked(configApi.rateHistory).mockResolvedValue({
      data: HISTORY,
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 3 } },
    } as never)

    render(withQuery(<RateHistoryTable rateType="dollar_rate" valueKey="rate" prefix="₦" />))

    await waitFor(() => expect(screen.getByRole('img', { name: /rate trend/i })).toBeInTheDocument())
    // Net change 1550 → 1650 = +₦100, over 3 changes
    expect(screen.getByText('+₦100')).toBeInTheDocument()
    expect(screen.getByText(/over 3 changes/)).toBeInTheDocument()
    // Table still present (Current badge on the newest row)
    expect(screen.getByText('Current')).toBeInTheDocument()
  })

  it('hides the chart when there is only one data point (no trend)', async () => {
    vi.mocked(configApi.rateHistory).mockResolvedValue({
      data: [entry(1550, null, '2026-05-01T00:00:00Z')],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    } as never)

    render(withQuery(<RateHistoryTable rateType="dollar_rate" valueKey="rate" prefix="₦" />))

    await waitFor(() => expect(screen.getByText('Current')).toBeInTheDocument())
    expect(screen.queryByRole('img', { name: /rate trend/i })).toBeNull()
  })
})
