import { beforeEach, describe, expect, it, vi } from 'vitest'
import { billingApi, disputeApi, carryoverApi } from './billing'

vi.mock('./client', () => ({
  apiRequest: vi.fn(),
  apiRequestList: vi.fn(),
}))

import { apiRequest, apiRequestList } from './client'

beforeEach(() => {
  vi.mocked(apiRequest).mockReset()
  vi.mocked(apiRequestList).mockReset()
})

describe('billingApi', () => {
  it('list() calls GET /v1/billing with status filter', async () => {
    vi.mocked(apiRequestList).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    await billingApi.list({ status: 'unpaid' })
    expect(apiRequestList).toHaveBeenCalledWith({ method: 'GET', path: '/v1/billing', query: { status: 'unpaid' } })
  })

  it('recordPayment() calls POST /v1/payments/{id}/confirm', async () => {
    vi.mocked(apiRequest).mockResolvedValue({})
    await billingApi.recordPayment('b1', { amount_ngn: '50000' }, 'idem-1')
    expect(apiRequest).toHaveBeenCalledWith({
      method: 'POST',
      path: '/v1/payments/b1/confirm',
      body: { amount_ngn: '50000' },
      idempotencyKey: 'idem-1',
    })
  })

  it('cancel() calls PATCH /v1/billing/{id}/cancel', async () => {
    vi.mocked(apiRequest).mockResolvedValue({})
    await billingApi.cancel('b2', { cancel_reason: 'duplicate' })
    expect(apiRequest).toHaveBeenCalledWith({ method: 'PATCH', path: '/v1/billing/b2/cancel', body: { cancel_reason: 'duplicate' } })
  })

  it('applyCarryover() calls PATCH /v1/billing/{id}/apply-carryover', async () => {
    vi.mocked(apiRequest).mockResolvedValue({})
    await billingApi.applyCarryover('b3', 'co-1')
    expect(apiRequest).toHaveBeenCalledWith({ method: 'PATCH', path: '/v1/billing/b3/apply-carryover', body: { carryover_id: 'co-1' } })
  })
})

describe('disputeApi', () => {
  it('list() calls GET /v1/billing/disputes', async () => {
    vi.mocked(apiRequestList).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    await disputeApi.list({ status: 'submitted' })
    expect(apiRequestList).toHaveBeenCalledWith({ method: 'GET', path: '/v1/billing/disputes', query: { status: 'submitted' } })
  })

  it('acknowledge() calls PATCH /v1/billing/disputes/{id}/acknowledge', async () => {
    vi.mocked(apiRequest).mockResolvedValue({})
    await disputeApi.acknowledge('d1')
    expect(apiRequest).toHaveBeenCalledWith({ method: 'PATCH', path: '/v1/billing/disputes/d1/acknowledge', body: {} })
  })

  it('resolve() calls PATCH /v1/billing/disputes/{id}/resolve', async () => {
    vi.mocked(apiRequest).mockResolvedValue({})
    await disputeApi.resolve('d2', { status: 'resolved_no_change', resolution_notes: 'Measurement confirmed' })
    expect(apiRequest).toHaveBeenCalledWith({
      method: 'PATCH',
      path: '/v1/billing/disputes/d2/resolve',
      body: { status: 'resolved_no_change', resolution_notes: 'Measurement confirmed' },
    })
  })

  it('reject() calls PATCH /v1/billing/disputes/{id}/reject', async () => {
    vi.mocked(apiRequest).mockResolvedValue({})
    await disputeApi.reject('d3', 'Insufficient evidence')
    expect(apiRequest).toHaveBeenCalledWith({ method: 'PATCH', path: '/v1/billing/disputes/d3/reject', body: { reason: 'Insufficient evidence' } })
  })
})

describe('carryoverApi', () => {
  it('list() calls GET /v1/billing/carryovers', async () => {
    vi.mocked(apiRequestList).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    await carryoverApi.list({ status: 'outstanding' })
    expect(apiRequestList).toHaveBeenCalledWith({ method: 'GET', path: '/v1/billing/carryovers', query: { status: 'outstanding' } })
  })
})
