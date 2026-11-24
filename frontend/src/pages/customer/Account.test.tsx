/**
 * P2-1 — customer notification language: the Notifications tab exposes an
 * EN / ZH picker and saves it as `locale` (customer.locale drives the EN/ZH
 * template set in the notification flow).
 *
 * Only what changed is sent. Saving `notification_consent` is what records that the
 * customer made a choice, so a language change must not drag the channel list along.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { customersApi, type Customer } from '../../api/tenantManagement'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { Account } from './Account'
import { withQuery } from '../../test/queryWrapper'

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
  return render(withQuery(
    <SessionContext.Provider value={ctx}>
      <MemoryRouter>
        <Account />
      </MemoryRouter>
    </SessionContext.Provider>,
  ))
}

function listOk(customer: Customer) {
  return { data: [customer], meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } } } as never
}

describe('Account — notification language (P2-1)', () => {
  beforeEach(() => vi.clearAllMocks())

  async function openNotifications(customer: Customer) {
    vi.mocked(customersApi.list).mockResolvedValue(listOk(customer))
    renderPage()
    await waitFor(() => expect(screen.getByText('Notifications')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Notifications'))
  }

  it('saves only the language when only the language changed', async () => {
    vi.mocked(customersApi.update).mockResolvedValue({ ...CUSTOMER, locale: 'zh' })
    await openNotifications(CUSTOMER)

    expect(screen.getByRole('group', { name: 'Message language' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: /中文/ }))
    await userEvent.click(screen.getByRole('button', { name: /Save preferences/ }))

    await waitFor(() => expect(customersApi.update).toHaveBeenCalledWith('cust1', { locale: 'zh' }))
  })

  it('does not record a channel choice the customer never made when they change language', async () => {
    // An imported customer: nothing recorded. Sending their empty default would opt them out of everything.
    const imported: Customer = { ...CUSTOMER, notification_consent: [], consent_given_at: null }
    vi.mocked(customersApi.update).mockResolvedValue({ ...imported, locale: 'zh' })
    await openNotifications(imported)

    await userEvent.click(screen.getByRole('radio', { name: /中文/ }))
    await userEvent.click(screen.getByRole('button', { name: /Save preferences/ }))

    await waitFor(() => expect(customersApi.update).toHaveBeenCalled())
    expect(vi.mocked(customersApi.update).mock.calls[0]?.[1]).not.toHaveProperty('notification_consent')
  })

  it('saves the channels when a channel changed', async () => {
    vi.mocked(customersApi.update).mockResolvedValue({ ...CUSTOMER, notification_consent: ['sms', 'email'] })
    await openNotifications(CUSTOMER)

    await userEvent.click(screen.getByRole('switch', { name: /email/i }))
    await userEvent.click(screen.getByRole('button', { name: /Save preferences/ }))

    await waitFor(() =>
      expect(customersApi.update).toHaveBeenCalledWith('cust1', { notification_consent: expect.arrayContaining(['sms', 'email']) }),
    )
    expect(vi.mocked(customersApi.update).mock.calls[0]?.[1]).not.toHaveProperty('locale')
  })

  it('says plainly which messages these choices cover', async () => {
    await openNotifications(CUSTOMER)
    expect(screen.getByText(/always sent/i)).toBeInTheDocument()
    expect(screen.getByText(/optional messages such as announcements and offers/i)).toBeInTheDocument()
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
