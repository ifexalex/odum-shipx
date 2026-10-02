import { beforeEach, describe, expect, it, vi } from 'vitest'
import { claimsApi, missingItemsApi, seizedItemsApi } from './claims'

vi.mock('./client', () => ({
  apiRequest: vi.fn(),
  apiRequestList: vi.fn(),
}))

import { apiRequest, apiRequestList } from './client'

beforeEach(() => {
  vi.mocked(apiRequest).mockReset()
  vi.mocked(apiRequestList).mockReset()
})

describe('claimsApi', () => {
  it('list() calls GET /v1/claims with status filter', async () => {
    vi.mocked(apiRequestList).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    await claimsApi.list({ status: 'filed' })
    expect(apiRequestList).toHaveBeenCalledWith({ method: 'GET', path: '/v1/claims', query: { status: 'filed' } })
  })

  it('get() calls GET /v1/claims/{id}', async () => {
    vi.mocked(apiRequest).mockResolvedValue({})
    await claimsApi.get('c1')
    expect(apiRequest).toHaveBeenCalledWith({ method: 'GET', path: '/v1/claims/c1' })
  })

  it('startInspection() calls PATCH /v1/claims/{id}/inspect', async () => {
    vi.mocked(apiRequest).mockResolvedValue({})
    await claimsApi.startInspection('c1', { inspection_method: 'delegate_visit' })
    expect(apiRequest).toHaveBeenCalledWith({ method: 'PATCH', path: '/v1/claims/c1/inspect', body: { inspection_method: 'delegate_visit' } })
  })

  it('resolve() calls PATCH /v1/claims/{id}/resolve', async () => {
    vi.mocked(apiRequest).mockResolvedValue({})
    await claimsApi.resolve('c1', { resolution_type: 'no_action', reason: 'Not warranted' })
    expect(apiRequest).toHaveBeenCalledWith({ method: 'PATCH', path: '/v1/claims/c1/resolve', body: { resolution_type: 'no_action', reason: 'Not warranted' } })
  })
})

describe('missingItemsApi', () => {
  it('list() calls GET /v1/claims/missing-items', async () => {
    vi.mocked(apiRequestList).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    await missingItemsApi.list({ status: 'reported' })
    expect(apiRequestList).toHaveBeenCalledWith({ method: 'GET', path: '/v1/claims/missing-items', query: { status: 'reported' } })
  })

  it('update() calls PATCH /v1/claims/missing-items/{id}', async () => {
    vi.mocked(apiRequest).mockResolvedValue({})
    await missingItemsApi.update('m1', { status: 'investigating', notes: 'Checking warehouse' })
    expect(apiRequest).toHaveBeenCalledWith({ method: 'PATCH', path: '/v1/claims/missing-items/m1', body: { status: 'investigating', notes: 'Checking warehouse' } })
  })
})

describe('seizedItemsApi', () => {
  it('list() calls GET /v1/claims/seized-items', async () => {
    vi.mocked(apiRequestList).mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
    await seizedItemsApi.list({ status: 'seized' })
    expect(apiRequestList).toHaveBeenCalledWith({ method: 'GET', path: '/v1/claims/seized-items', query: { status: 'seized' } })
  })

  it('update() calls PATCH /v1/claims/seized-items/{id}', async () => {
    vi.mocked(apiRequest).mockResolvedValue({})
    await seizedItemsApi.update('s1', { recovery_status: 'recovery_in_progress' })
    expect(apiRequest).toHaveBeenCalledWith({ method: 'PATCH', path: '/v1/claims/seized-items/s1', body: { recovery_status: 'recovery_in_progress' } })
  })
})
