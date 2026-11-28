/**
 * Step-up re-authentication (platform audit Phase 1, C-29): the token store, and the API client asking for a fresh
 * re-authentication when a dangerous platform request is refused with STEP_UP_REQUIRED, then retrying it once.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiRequest } from '../api/client'
import { registerSessionActions } from './sessionBridge'
import {
  clearStepUp,
  getStepUpToken,
  registerStepUpHandler,
  requestStepUp,
  resetStepUpForTests,
  setStepUpGrant,
} from './stepUp'
import { clearActiveTokens } from './tokenStore'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function stepUpRequired(): Response {
  return json(
    { type: 'about:blank', title: 'Forbidden', status: 403, detail: 'Re-authenticate to confirm this action.', error_code: 'STEP_UP_REQUIRED' },
    403,
  )
}

function headersOf(fetchMock: ReturnType<typeof vi.fn>, call: number): Record<string, string> {
  return (fetchMock.mock.calls[call] as [string, RequestInit & { headers: Record<string, string> }])[1].headers
}

const NOW = () => Date.now() / 1000

describe('the step-up token store', () => {
  beforeEach(() => resetStepUpForTests())

  it('hands out a token until shortly before it expires', () => {
    setStepUpGrant('tok', NOW() + 300)
    expect(getStepUpToken()).toBe('tok')
    setStepUpGrant('tok', NOW() + 5)
    expect(getStepUpToken()).toBeNull()
  })

  it('is cleared with the session', () => {
    setStepUpGrant('tok', NOW() + 300)
    clearActiveTokens()
    expect(getStepUpToken()).toBeNull()
  })

  it('shares one prompt between concurrent requests', async () => {
    const handler = vi.fn(() => Promise.resolve())
    registerStepUpHandler(handler)
    await Promise.all([requestStepUp(), requestStepUp()])
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('refuses when no dialog is mounted', async () => {
    await expect(requestStepUp()).rejects.toThrow()
  })
})

describe('the API client and STEP_UP_REQUIRED', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    resetStepUpForTests()
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.test.shipx.co')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    registerSessionActions({ refreshNow: vi.fn(), logout: vi.fn(), exitImpersonation: vi.fn() })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    clearStepUp()
  })

  it('prompts, then retries once with the new token', async () => {
    registerStepUpHandler(async () => setStepUpGrant('fresh-token', NOW() + 300))
    fetchMock.mockResolvedValueOnce(stepUpRequired()).mockResolvedValueOnce(json({ data: { ok: true } }))

    const result = await apiRequest<{ ok: boolean }>({ method: 'DELETE', path: '/v1/platform/tenants/t-1', body: {} })

    expect(result).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(headersOf(fetchMock, 0)['X-Step-Up-Token']).toBeUndefined()
    expect(headersOf(fetchMock, 1)['X-Step-Up-Token']).toBe('fresh-token')
  })

  it('reports the refusal when the admin cancels', async () => {
    registerStepUpHandler(() => Promise.reject(new Error('cancelled')))
    fetchMock.mockResolvedValueOnce(stepUpRequired())

    const err = await apiRequest({ method: 'DELETE', path: '/v1/platform/tenants/t-1', body: {} }).catch((e: unknown) => e)

    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).errorCode).toBe('STEP_UP_REQUIRED')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('sends a valid token straight away, and only to platform routes', async () => {
    setStepUpGrant('held', NOW() + 300)
    fetchMock.mockImplementation(() => Promise.resolve(json({ data: {} })))
    await apiRequest({ method: 'PUT', path: '/v1/platform/settings', body: {} })
    await apiRequest({ method: 'PUT', path: '/v1/tenant/config', body: {} })
    expect(headersOf(fetchMock, 0)['X-Step-Up-Token']).toBe('held')
    expect(headersOf(fetchMock, 1)['X-Step-Up-Token']).toBeUndefined()
  })

  it('leaves other 403s alone', async () => {
    const handler = vi.fn(() => Promise.resolve())
    registerStepUpHandler(handler)
    fetchMock.mockResolvedValueOnce(
      json({ type: 'x', title: 'Forbidden', status: 403, detail: 'No.', error_code: 'INSUFFICIENT_PERMISSIONS' }, 403),
    )
    await expect(apiRequest({ method: 'POST', path: '/v1/platform/admins', body: {} })).rejects.toBeInstanceOf(ApiError)
    expect(handler).not.toHaveBeenCalled()
  })
})
