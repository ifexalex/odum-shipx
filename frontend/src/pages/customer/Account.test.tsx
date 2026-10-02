/**
 * P2-1 — customer notification language: the Notifications tab exposes an
 * EN / ZH picker and saves it as `locale` alongside channel consent
 * (customer.locale drives the EN/ZH template set in the notification flow).
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { customersApi, type Customer } from '../../api/tenantManagement'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { Account } from './Account'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    customersApi: { ...original.customersApi, list: vi.fn(), update: vi.fn() },
  }
})

const CUSTOMER: Customer = {
  id: 'cust1', tenant_id: 't1', name: 'Ngozi Okonkwo', phone: '+2348012345678',
  email: 'ngozi@example.com', whatsapp: null, address: null, anonymised_at: null,
  user_id: 'u1', consent_given_at: '2026-01-01T00:00:00Z',
  notification_consent: ['sms'], locale: 'en',
}

function makeSession(): Session {
  return {
    tenantId: 't1', userId: 'u1', name: 'Ngozi', role: 'customer', roles: ['customer'],
    isPlatformAdmin: false, impersonatedBy: null, sessionId: null,
    readOnly: false, expiresAt: Date.now() + 60_000, tokenType: 'cognito',
  }
}

function renderPage() {
  const ctx: SessionContextValue = {
    session: makeSession(), status: 'authenticated',
    login: vi.fn(), logout: vi.fn(), startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(),
  }
  return render(
    <SessionContext.Provider value={ctx}>
      <MemoryRouter>
        <Account />
      </MemoryRouter>
    </SessionContext.Provider>,
  )
}

function listOk(customer: Customer) {
  return { data: [customer], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } } as never
}

describe('Account — notification language (P2-1)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('saves the chosen language together with channel consent', async () => {
    vi.mocked(customersApi.list).mockResolvedValue(listOk(CUSTOMER))
    vi.mocked(customersApi.update).mockResolvedValue({ ...CUSTOMER, locale: 'zh' })
    renderPage()

    await waitFor(() => expect(screen.getByText('Notifications')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Notifications'))

    expect(screen.getByText('Message language')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: /中文/ }))
    await userEvent.click(screen.getByRole('button', { name: /Save preferences/ }))

    await waitFor(() =>
      expect(customersApi.update).toHaveBeenCalledWith('cust1', {
        notification_consent: ['sms'],
        locale: 'zh',
      }),
    )
  })

  it('save stays disabled while nothing changed', async () => {
    vi.mocked(customersApi.list).mockResolvedValue(listOk(CUSTOMER))
    renderPage()

    await waitFor(() => expect(screen.getByText('Notifications')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Notifications'))

    expect(screen.getByRole('button', { name: /Save preferences/ })).toBeDisabled()
    // English is pre-selected from the stored locale
    expect(screen.getByRole('radio', { name: /English/ })).toBeChecked()
  })
})
