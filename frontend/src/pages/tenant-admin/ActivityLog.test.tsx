/**
 * Ground-truth gap found live, reported directly by the user: "we need to
 * ensure that we have log trail for everything... so that the tenant admin
 * can see every activity going on." Only an 8-row dashboard widget with no
 * filtering and no before/after detail existed before this page.
 *
 * Follow-up (2026-09-07): a single "Record type" dropdown wasn't real
 * filtering — no category grouping, no action filter, no search, no date
 * range, no sort. These tests cover the real filter set, not just render.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { configApi } from '../../api/tenantManagement'
import { ActivityLog } from './ActivityLog'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return { ...original, configApi: { ...original.configApi, activity: vi.fn() } }
})

const ENTRY = {
  id: 'a1',
  action: 'UPDATE' as const,
  entity_type: 'payment_claim',
  entity_id: 'claim-1',
  actor_id: 'staff-1',
  actor_role: 'nigeria_office_staff',
  actor_name: 'Emeka Eze',
  before_state: { status: 'pending' },
  after_state: { status: 'confirmed', payment_record_id: 'pay-1' },
  created_at: '2026-09-07T10:00:00Z',
}

function emptyResult() {
  return { data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } }
}

describe('ActivityLog — tenant-admin audit trail', () => {
  it('renders activity rows with actor and action', async () => {
    vi.mocked(configApi.activity).mockResolvedValue({
      data: [ENTRY],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    render(<ActivityLog />)

    expect(await screen.findByText('payment claim')).toBeInTheDocument()
    expect(screen.getByText('Emeka Eze')).toBeInTheDocument()
    expect(screen.getByText('UPDATE')).toBeInTheDocument()
  })

  it('expanding Details shows the real before/after state, not just that something changed', async () => {
    vi.mocked(configApi.activity).mockResolvedValue({
      data: [ENTRY],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    render(<ActivityLog />)

    await screen.findByText('payment claim')
    await userEvent.click(screen.getByRole('button', { name: /details/i }))

    expect(screen.getByText(/"status": "pending"/)).toBeInTheDocument()
    expect(screen.getByText(/"status": "confirmed"/)).toBeInTheDocument()
    expect(screen.getByText(/"payment_record_id": "pay-1"/)).toBeInTheDocument()
  })

  it('a row with no before/after state has no Details button', async () => {
    vi.mocked(configApi.activity).mockResolvedValue({
      data: [{ ...ENTRY, before_state: null, after_state: null }],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
    render(<ActivityLog />)

    await screen.findByText('payment claim')
    expect(screen.queryByRole('button', { name: /details/i })).toBeNull()
  })

  it('choosing a category sends every entity_type in that category', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(emptyResult())
    render(<ActivityLog />)

    await screen.findByText('No activity matches these filters')
    await userEvent.click(screen.getByRole('button', { name: /^Money/ }))

    await waitFor(() =>
      expect(configApi.activity).toHaveBeenLastCalledWith(
        expect.objectContaining({
          entityTypes: expect.arrayContaining(['billing', 'payment_claim', 'payment_record', 'refund_request']),
        }),
      ),
    )
  })

  it('picking a specific record type within a category narrows to just that one', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(emptyResult())
    render(<ActivityLog />)

    await screen.findByText('No activity matches these filters')
    await userEvent.click(screen.getByRole('button', { name: /^Money/ }))
    await userEvent.selectOptions(screen.getByLabelText('Record type'), 'payment_claim')

    await waitFor(() =>
      expect(configApi.activity).toHaveBeenLastCalledWith(
        expect.objectContaining({ entityTypes: ['payment_claim'] }),
      ),
    )
  })

  it('switching category clears a record-type selection that no longer applies', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(emptyResult())
    render(<ActivityLog />)

    await screen.findByText('No activity matches these filters')
    await userEvent.click(screen.getByRole('button', { name: /^Money/ }))
    await userEvent.selectOptions(screen.getByLabelText('Record type'), 'payment_claim')
    await userEvent.click(screen.getByRole('button', { name: /^Goods & shipments/ }))

    expect(screen.getByLabelText('Record type')).toHaveValue('')
    await waitFor(() =>
      expect(configApi.activity).toHaveBeenLastCalledWith(
        expect.objectContaining({
          entityTypes: expect.arrayContaining(['container', 'packing_list', 'manifest']),
        }),
      ),
    )
  })

  it('filters by action', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(emptyResult())
    render(<ActivityLog />)

    await screen.findByText('No activity matches these filters')
    await userEvent.selectOptions(screen.getByLabelText('Action'), 'STATUS_CHANGE')

    await waitFor(() =>
      expect(configApi.activity).toHaveBeenLastCalledWith(expect.objectContaining({ action: 'STATUS_CHANGE' })),
    )
  })

  it('searches by actor name or record id, debounced', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(emptyResult())
    render(<ActivityLog />)

    await screen.findByText('No activity matches these filters')
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search the activity log' }), 'Emeka')

    await waitFor(() => expect(configApi.activity).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Emeka' })), {
      timeout: 1000,
    })
  })

  it('toggling sort order sends the new direction', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(emptyResult())
    render(<ActivityLog />)

    await screen.findByText('No activity matches these filters')
    expect(configApi.activity).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'desc' }))

    await userEvent.selectOptions(screen.getByLabelText('Sort'), 'asc')
    await waitFor(() => expect(configApi.activity).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'asc' })))
  })

  it('Clear filters resets category, record type, action, search, and date range together', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(emptyResult())
    render(<ActivityLog />)

    await screen.findByText('No activity matches these filters')
    await userEvent.click(screen.getByRole('button', { name: /^Money/ }))
    await userEvent.selectOptions(screen.getByLabelText('Action'), 'CREATE')
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search the activity log' }), 'Emeka')
    await userEvent.click(screen.getByRole('button', { name: /^When:/ }))
    await userEvent.type(screen.getByLabelText('From'), '2026-09-01')

    await userEvent.click(await screen.findByRole('button', { name: /clear filters/i }))

    expect(screen.getByLabelText('Action')).toHaveValue('')
    expect(screen.getByRole('searchbox', { name: 'Search the activity log' })).toHaveValue('')
    expect(screen.getByLabelText('From')).toHaveValue('')
    // Category cleared → Record type offers all types again, and the query
    // goes back to an unfiltered entityTypes (proves the category reset).
    expect(screen.getByLabelText('Record type')).toContainHTML('All types')
    await waitFor(() =>
      expect(configApi.activity).toHaveBeenLastCalledWith(
        expect.objectContaining({ entityTypes: undefined, action: undefined, q: undefined, createdAfter: undefined }),
      ),
    )
  })

  it('a custom From/To date range is sent as createdAfter/createdBefore', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(emptyResult())
    render(<ActivityLog />)

    await screen.findByText('No activity matches these filters')
    await userEvent.click(screen.getByRole('button', { name: /^When:/ }))
    await userEvent.type(screen.getByLabelText('From'), '2026-09-01')
    await userEvent.type(screen.getByLabelText('To'), '2026-09-07')

    await waitFor(() =>
      expect(configApi.activity).toHaveBeenLastCalledWith(
        expect.objectContaining({ createdAfter: '2026-09-01', createdBefore: '2026-09-07' }),
      ),
    )
  })

  it('a custom From date overrides and clears the preset "When" selector', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(emptyResult())
    render(<ActivityLog />)

    await screen.findByText('No activity matches these filters')
    await userEvent.click(screen.getByRole('button', { name: /all time/i }))
    await userEvent.click(await screen.findByRole('option', { name: /last 7 days/i }))
    await waitFor(() =>
      expect(configApi.activity).toHaveBeenLastCalledWith(expect.objectContaining({ createdAfter: expect.any(String) })),
    )

    await userEvent.click(screen.getByRole('button', { name: /^When:/ }))

    await userEvent.type(screen.getByLabelText('From'), '2026-01-01')

    await waitFor(() =>
      expect(configApi.activity).toHaveBeenLastCalledWith(expect.objectContaining({ createdAfter: '2026-01-01' })),
    )
    // The button now names the custom range, not the preset it replaced.
    expect(screen.getByRole('button', { name: /^When: Since 1 Jan 2026/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /last 7 days/i })).toBeNull()
  })

  it('does not offer impersonation as a filterable record type — platform-only, not a tenant business record', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(emptyResult())
    render(<ActivityLog />)

    await screen.findByText('No activity matches these filters')
    // Category is a chip set; none of the chips name impersonation.
    expect(screen.queryByRole('button', { name: /imperson/i })).toBeNull()

    const recordTypeOptions = screen.getByLabelText('Record type').querySelectorAll('option')
    expect(Array.from(recordTypeOptions).some((o) => /imperson/i.test(o.textContent ?? ''))).toBe(false)
  })
})
