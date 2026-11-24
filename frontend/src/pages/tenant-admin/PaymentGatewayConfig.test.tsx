/**
 * Multi-tenant Paystack config (2026-07-19) — a tenant connects/replaces/
 * disconnects their own Paystack secret key. The real value is never sent
 * back by the API (only last4/environment), and Save is disabled until the
 * pasted key matches Paystack's sk_test_/sk_live_ shape.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { configApi } from '../../api/tenantManagement'
import { PaymentGatewayConfig } from './PaymentGatewayConfig'
import { withQuery } from '../../test/queryWrapper'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    configApi: {
      ...original.configApi,
      getConfig: vi.fn(),
      updatePaystackConfig: vi.fn(),
      testPaystackConnection: vi.fn(),
      deletePaystackConfig: vi.fn(),
    },
  }
})

const VALID_KEY = 'sk_test_1ca1d9f3f5278d5014396d126483ace85f2c3afb'

describe('PaymentGatewayConfig', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows "Not connected" and a disabled Connect button when no key is configured', async () => {
    vi.mocked(configApi.getConfig).mockResolvedValue({ webhook_config: null, paystack_config: null })
    render(withQuery(<PaymentGatewayConfig />))

    expect(await screen.findByText('Not connected')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect Paystack' })).toBeDisabled()
  })

  it('shows masked last4 and the environment badge when already configured', async () => {
    vi.mocked(configApi.getConfig).mockResolvedValue({
      webhook_config: null,
      paystack_config: { enabled: true, last4: 'c3afb'.slice(-4), environment: 'test', configured_by: 'u1', configured_at: '2026-07-19T00:00:00Z' },
    })
    render(withQuery(<PaymentGatewayConfig />))

    expect(await screen.findByText('Test mode')).toBeInTheDocument()
    expect(screen.getByText(/sk_test_.*3afb/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Disconnect' })).toBeInTheDocument()
  })

  it('rejects a malformed key before Save is even enabled', async () => {
    vi.mocked(configApi.getConfig).mockResolvedValue({ webhook_config: null, paystack_config: null })
    render(withQuery(<PaymentGatewayConfig />))
    await screen.findByText('Not connected')

    await userEvent.type(screen.getByLabelText('Secret key'), 'not-a-real-key')

    expect(screen.getByText('Invalid key format.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect Paystack' })).toBeDisabled()
    expect(configApi.updatePaystackConfig).not.toHaveBeenCalled()
  })

  it('saves a valid key and clears the input', async () => {
    vi.mocked(configApi.getConfig).mockResolvedValue({ webhook_config: null, paystack_config: null })
    vi.mocked(configApi.updatePaystackConfig).mockResolvedValue({
      enabled: true, last4: 'c3afb'.slice(-4), environment: 'test', configured_by: 'u1', configured_at: '2026-07-19T00:00:00Z',
    })
    render(withQuery(<PaymentGatewayConfig />))
    await screen.findByText('Not connected')

    await userEvent.type(screen.getByLabelText('Secret key'), VALID_KEY)
    await userEvent.click(screen.getByRole('button', { name: 'Connect Paystack' }))

    await waitFor(() => expect(configApi.updatePaystackConfig).toHaveBeenCalledWith(VALID_KEY))
    expect(await screen.findByText('Paystack key saved')).toBeInTheDocument()
  })

  it('runs a live test-connection check and shows the result', async () => {
    vi.mocked(configApi.getConfig).mockResolvedValue({
      webhook_config: null,
      paystack_config: { enabled: true, last4: 'c3afb'.slice(-4), environment: 'test', configured_by: 'u1', configured_at: '2026-07-19T00:00:00Z' },
    })
    vi.mocked(configApi.testPaystackConnection).mockResolvedValue({ success: true, environment: 'test' })
    render(withQuery(<PaymentGatewayConfig />))
    await screen.findByText('Test mode')

    await userEvent.click(screen.getByRole('button', { name: 'Test connection' }))

    expect(await screen.findByText(/connected.*paystack accepted the key/i)).toBeInTheDocument()
  })

  it('surfaces a rejected key from the live test as an error, not a crash', async () => {
    vi.mocked(configApi.getConfig).mockResolvedValue({
      webhook_config: null,
      paystack_config: { enabled: true, last4: 'c3afb'.slice(-4), environment: 'test', configured_by: 'u1', configured_at: '2026-07-19T00:00:00Z' },
    })
    vi.mocked(configApi.testPaystackConnection).mockRejectedValue(
      new ApiError(
        { type: 'about:blank', title: 'External Service Error', status: 502, detail: 'Paystack rejected this key — check it\'s correct and active', error_code: 'EXTERNAL_SERVICE_ERROR' },
        null,
      ),
    )
    render(withQuery(<PaymentGatewayConfig />))
    await screen.findByText('Test mode')

    await userEvent.click(screen.getByRole('button', { name: 'Test connection' }))

    expect(await screen.findByText(/paystack rejected this key/i)).toBeInTheDocument()
  })

  it('disconnects after confirming the warning modal', async () => {
    vi.mocked(configApi.getConfig).mockResolvedValue({
      webhook_config: null,
      paystack_config: { enabled: true, last4: 'c3afb'.slice(-4), environment: 'test', configured_by: 'u1', configured_at: '2026-07-19T00:00:00Z' },
    })
    vi.mocked(configApi.deletePaystackConfig).mockResolvedValue({ enabled: false })
    render(withQuery(<PaymentGatewayConfig />))
    await screen.findByText('Test mode')

    await userEvent.click(screen.getByRole('button', { name: 'Disconnect' }))
    // Confirm inside the warning modal (second "Disconnect" button)
    const modalConfirm = screen.getAllByRole('button', { name: 'Disconnect' })[1]!
    await userEvent.click(modalConfirm)

    await waitFor(() => expect(configApi.deletePaystackConfig).toHaveBeenCalled())
    expect(await screen.findByText('Not connected')).toBeInTheDocument()
  })

  it('reads the tenant config once for both panels (they used to fetch it separately)', async () => {
    vi.mocked(configApi.getConfig).mockResolvedValue({ webhook_config: null, paystack_config: null })
    render(withQuery(<PaymentGatewayConfig />))
    await screen.findByText('Not connected')
    expect(configApi.getConfig).toHaveBeenCalledTimes(1)
  })
})
