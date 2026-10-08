import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import type { Session } from '../auth/types'
import { announcementsApi } from '../api/announcements'
import { ComposeAnnouncementModal } from './ComposeAnnouncementModal'

vi.mock('../api/announcements', () => ({
  announcementsApi: { send: vi.fn() },
}))

function makeSession(role: Session['role']): Session {
  return {
    tenantId: 't1',
    userId: 'u1',
    name: null,
    role,
    roles: [role],
    isPlatformAdmin: false,
    impersonatedBy: null,
    sessionId: null,
    readOnly: false,
    expiresAt: Date.now() + 60_000,
    tokenType: 'cognito',
  }
}

function makeContextValue(session: Session | null): SessionContextValue {
  return {
    session,
    status: session ? 'authenticated' : 'unauthenticated',
    login: vi.fn(),
    logout: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
    refreshNow: vi.fn(),
    setActiveRole: vi.fn(),
  }
}

function renderModal(open = true, onClose = vi.fn(), session: Session | null = makeSession('tenant_admin')) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={makeContextValue(session)}>
        <ComposeAnnouncementModal open={open} onClose={onClose} />
      </SessionContext.Provider>
    </QueryClientProvider>,
  )
  return { onClose }
}

beforeEach(() => {
  vi.mocked(announcementsApi.send).mockReset()
})

describe('ComposeAnnouncementModal — tenant_admin', () => {
  it('renders nothing when closed', () => {
    renderModal(false)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('defaults to "All staff" audience and disables send until a title is entered', () => {
    renderModal()

    const staffChip = screen.getByRole('button', { name: 'All staff' }).parentElement
    const customersChip = screen.getByRole('button', { name: 'All customers' }).parentElement
    expect(staffChip?.className).toMatch(/active/)
    expect(customersChip?.className).not.toMatch(/active/)

    expect(screen.getByRole('button', { name: /send announcement/i })).toBeDisabled()
  })

  it('enables send once a title is entered, and submits title/body/audience', async () => {
    vi.mocked(announcementsApi.send).mockResolvedValue({
      status: 'sent',
      audience: 'all_staff',
      notifications_created: 4,
    })
    renderModal()

    await userEvent.type(
      screen.getByPlaceholderText(/office closed for the holidays/i),
      'Office closed for the holidays',
    )
    await userEvent.type(screen.getByPlaceholderText(/optional details/i), 'Back on Monday.')

    const sendBtn = screen.getByRole('button', { name: /send announcement/i })
    expect(sendBtn).not.toBeDisabled()
    await userEvent.click(sendBtn)

    await waitFor(() =>
      expect(announcementsApi.send).toHaveBeenCalledWith({
        title: 'Office closed for the holidays',
        body: 'Back on Monday.',
        audience: 'all_staff',
      }),
    )
  })

  it('switches audience to "All customers" when that chip is clicked', async () => {
    vi.mocked(announcementsApi.send).mockResolvedValue({
      status: 'sent',
      audience: 'all_customers',
      notifications_created: 1,
    })
    renderModal()

    await userEvent.type(screen.getByPlaceholderText(/office closed for the holidays/i), 'Warehouse notice')
    await userEvent.click(screen.getByRole('button', { name: 'All customers' }))
    await userEvent.click(screen.getByRole('button', { name: /send announcement/i }))

    await waitFor(() =>
      expect(announcementsApi.send).toHaveBeenCalledWith(
        expect.objectContaining({ audience: 'all_customers' }),
      ),
    )
  })

  it('sends an undefined body when the message field is left blank', async () => {
    vi.mocked(announcementsApi.send).mockResolvedValue({
      status: 'sent',
      audience: 'all_staff',
      notifications_created: 4,
    })
    renderModal()

    await userEvent.type(screen.getByPlaceholderText(/office closed for the holidays/i), 'Title only')
    await userEvent.click(screen.getByRole('button', { name: /send announcement/i }))

    await waitFor(() =>
      expect(announcementsApi.send).toHaveBeenCalledWith(
        expect.objectContaining({ body: undefined }),
      ),
    )
  })

  it('closes and resets the form on successful submit', async () => {
    vi.mocked(announcementsApi.send).mockResolvedValue({
      status: 'sent',
      audience: 'all_staff',
      notifications_created: 4,
    })
    const { onClose } = renderModal()

    await userEvent.type(screen.getByPlaceholderText(/office closed for the holidays/i), 'Title only')
    await userEvent.click(screen.getByRole('button', { name: /send announcement/i }))

    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('shows an error banner when the send fails, without closing the modal', async () => {
    vi.mocked(announcementsApi.send).mockRejectedValue(new Error('Network error'))
    const { onClose } = renderModal()

    await userEvent.type(screen.getByPlaceholderText(/office closed for the holidays/i), 'Title only')
    await userEvent.click(screen.getByRole('button', { name: /send announcement/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/network error/i)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('calls onClose without submitting when Cancel is clicked', async () => {
    const { onClose } = renderModal()

    await userEvent.type(screen.getByPlaceholderText(/office closed for the holidays/i), 'Draft never sent')
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))

    expect(onClose).toHaveBeenCalled()
    expect(announcementsApi.send).not.toHaveBeenCalled()
  })
})

describe('ComposeAnnouncementModal — nigeria_office_staff', () => {
  it('never shows the "All staff" choice — only tenant_admin can reach that audience', () => {
    renderModal(true, vi.fn(), makeSession('nigeria_office_staff'))

    expect(screen.queryByRole('button', { name: 'All staff' })).toBeNull()
    expect(screen.getByRole('button', { name: 'All customers' }).parentElement?.className).toMatch(/active/)
  })

  it('labels the submit button "Submit announcement" and explains the review step', () => {
    renderModal(true, vi.fn(), makeSession('nigeria_office_staff'))

    expect(screen.getByRole('button', { name: /submit announcement/i })).toBeInTheDocument()
    expect(screen.getByText(/need tenant admin approval/i)).toBeInTheDocument()
  })

  it('submits with audience locked to all_customers', async () => {
    vi.mocked(announcementsApi.send).mockResolvedValue({
      status: 'pending',
      request_id: 'req1',
      audience: 'all_customers',
    })
    renderModal(true, vi.fn(), makeSession('nigeria_office_staff'))

    await userEvent.type(screen.getByPlaceholderText(/office closed for the holidays/i), 'Customs delay')
    await userEvent.click(screen.getByRole('button', { name: /submit announcement/i }))

    await waitFor(() =>
      expect(announcementsApi.send).toHaveBeenCalledWith(
        expect.objectContaining({ audience: 'all_customers' }),
      ),
    )
  })
})
