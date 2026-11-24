/**
 * WebhookConfig reads the tenant config through React Query (audit FE-05) and copies it into its own editable form
 * once. These pin the two behaviours the old `useEffect` fetch had: the form is filled from the server, and a failed
 * read shows the empty form rather than an endless "Loading…".
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { configApi } from '../../api/tenantManagement'
import { withQuery } from '../../test/queryWrapper'
import { WebhookConfig } from './WebhookConfig'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return { ...original, configApi: { ...original.configApi, getConfig: vi.fn(), updateConfig: vi.fn() } }
})

const SAVED = { endpoint_url: 'https://erp.example.com/hooks/shipx', enabled: true, events: ['container.status_updated' as const], secret: '****' }

beforeEach(() => {
  vi.mocked(configApi.getConfig).mockReset()
  vi.mocked(configApi.updateConfig).mockReset()
})

describe('WebhookConfig', () => {
  it('fills the form from the saved configuration', async () => {
    vi.mocked(configApi.getConfig).mockResolvedValue({ webhook_config: SAVED, paystack_config: null })
    render(withQuery(<WebhookConfig />))
    expect(await screen.findByDisplayValue('https://erp.example.com/hooks/shipx')).toBeInTheDocument()
    expect(configApi.getConfig).toHaveBeenCalledTimes(1)
  })

  it('shows the empty form, not an endless Loading, when the read fails', async () => {
    vi.mocked(configApi.getConfig).mockRejectedValue(
      new ApiError({ type: 'about:blank', title: 'Server Error', status: 500, detail: 'boom', error_code: 'INTERNAL' }, null),
    )
    render(withQuery(<WebhookConfig />))
    expect(await screen.findByText('Outbound webhook')).toBeInTheDocument()
    expect(screen.queryByText('Loading…')).toBeNull()
  })

  it('keeps what the user is typing', async () => {
    vi.mocked(configApi.getConfig).mockResolvedValue({ webhook_config: SAVED, paystack_config: null })
    render(withQuery(<WebhookConfig />))
    const url = await screen.findByDisplayValue('https://erp.example.com/hooks/shipx')
    await userEvent.clear(url)
    await userEvent.type(url, 'https://new.example.com/h')
    await waitFor(() => expect(url).toHaveValue('https://new.example.com/h'))
  })

  it('saves the edited endpoint', async () => {
    vi.mocked(configApi.getConfig).mockResolvedValue({ webhook_config: SAVED, paystack_config: null })
    vi.mocked(configApi.updateConfig).mockResolvedValue({ webhook_config: { ...SAVED, endpoint_url: 'https://new.example.com/h' }, paystack_config: null })
    render(withQuery(<WebhookConfig />))
    const url = await screen.findByDisplayValue('https://erp.example.com/hooks/shipx')
    await userEvent.clear(url)
    await userEvent.type(url, 'https://new.example.com/h')
    await userEvent.click(screen.getByRole('button', { name: /^Save/ }))
    await waitFor(() =>
      expect(configApi.updateConfig).toHaveBeenCalledWith({
        webhook_config: { endpoint_url: 'https://new.example.com/h', enabled: true, events: ['container.status_updated'] },
      }),
    )
    expect(await screen.findByText('Webhook settings saved')).toBeInTheDocument()
  })
})
