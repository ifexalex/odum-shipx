import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { configApi, type TenantPoliciesResponse } from '../../api/tenantManagement'
import { withQuery } from '../../test/queryWrapper'
import { PoliciesConfig } from './PoliciesConfig'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    configApi: {
      ...original.configApi,
      getPolicies: vi.fn(),
      updatePolicy: vi.fn(),
    },
  }
})

const SAMPLE_POLICIES: TenantPoliciesResponse = {
  policies: {
    storage_fee: { enabled: true, grace_period_days: 14, daily_fee_per_carton_ngn: 500 },
    refund_threshold_usd: { staff_limit: 50, requires_manager_above: 50 },
    credit_defaults: { default_credit_limit_ngn: 200000, default_credit_terms_days: 14 },
    dispute_escalation: { enabled: true, auto_escalate_days: 5 },
    reminder_days: { storage_first_reminder: 7, storage_final_reminder: 13 },
  },
  scheduled: {},
  history: [],
  default_effective_date: '2026-11-29',
}

describe('PoliciesConfig (TC-01)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(configApi.getPolicies).mockResolvedValue(SAMPLE_POLICIES)
  })

  it('renders all five policy sections and submits an effective-dated update', async () => {
    vi.mocked(configApi.updatePolicy).mockResolvedValue(SAMPLE_POLICIES)
    render(withQuery(<MemoryRouter><PoliciesConfig /></MemoryRouter>))

    expect(await screen.findByText('Storage fees')).toBeInTheDocument()
    expect(screen.getByText('Refund & claim approval limit')).toBeInTheDocument()
    expect(screen.getByText('Default customer credit')).toBeInTheDocument()
    expect(screen.getByText('Dispute auto-escalation')).toBeInTheDocument()
    expect(screen.getByText('Storage pickup reminders')).toBeInTheDocument()

    const limitInput = screen.getByLabelText(/staff approval limit/i)
    await userEvent.clear(limitInput)
    await userEvent.type(limitInput, '100')
    await userEvent.click(screen.getByRole('button', { name: /save refund & claim approval limit/i }))

    expect(configApi.updatePolicy).toHaveBeenCalledWith({
      policy_key: 'refund_threshold_usd',
      value: { staff_limit: 100 },
      effective_date: '2026-11-29',
    })
  })
})
