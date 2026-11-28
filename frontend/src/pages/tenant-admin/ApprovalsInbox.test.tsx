import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { releaseNotesApi } from '../../api/releaseNotes'
import { configApi, type TenantApprovalsResponse } from '../../api/tenantManagement'
import { withQuery } from '../../test/queryWrapper'
import { ApprovalsInbox } from './ApprovalsInbox'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    configApi: {
      ...original.configApi,
      getApprovals: vi.fn(),
    },
  }
})

vi.mock('../../api/releaseNotes', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/releaseNotes')>()
  return {
    ...original,
    releaseNotesApi: {
      ...original.releaseNotesApi,
      approveCreditRequest: vi.fn(),
      rejectCreditRequest: vi.fn(),
    },
  }
})

const SAMPLE_INBOX: TenantApprovalsResponse = {
  counts: { credit_release: 1, refund: 0, claim: 0, announcement: 0, total: 1 },
  staff_limit_usd: 50,
  staff_limit_ngn: 75000,
  items: [
    {
      id: 'cr-1',
      type: 'credit_release',
      title: 'Credit release — Ibrahim Musa',
      summary: '2 carton(s) on invoice INV-001',
      amount_ngn: '250000',
      customer_id: 'cust-1',
      customer_name: 'Ibrahim Musa',
      customer_outstanding_ngn: '250000',
      customer_credit_limit_ngn: '100000',
      exceeds_credit_limit: true,
      requested_by: 'staff-1',
      requested_by_name: 'Amaka Nwachukwu',
      self_requested: false,
      reason: 'Trusted customer paying Friday',
      created_at: '2026-11-28T10:00:00Z',
      entity_id: 'cr-1',
      detail_path: '/billing/b-1',
      metadata: {},
    },
  ],
}

describe('ApprovalsInbox (TC-02)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(configApi.getApprovals).mockResolvedValue(SAMPLE_INBOX)
  })

  it('lists pending credit releases with over-limit badge and lets admin approve', async () => {
    vi.mocked(releaseNotesApi.approveCreditRequest).mockResolvedValue({
      credit_request: {} as never,
      release_note: { reference_number: 'RN-001' } as never,
    })
    render(withQuery(<MemoryRouter><ApprovalsInbox /></MemoryRouter>))

    expect(await screen.findByText('Credit release — Ibrahim Musa')).toBeInTheDocument()
    expect(screen.getByText('Over credit limit')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /^approve$/i }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /^approve$/i }))

    expect(releaseNotesApi.approveCreditRequest).toHaveBeenCalledWith('cr-1', undefined)
  })
})
