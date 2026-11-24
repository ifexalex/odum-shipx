import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import * as rnModule from '../../api/releaseNotes'
import { SessionContext } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { ReleaseNoteList } from './ReleaseNoteList'

const SESSION: Session = {
  userId: 'u-001', tenantId: 't-001', role: 'nigeria_office_staff', roles: ['nigeria_office_staff'],
  name: 'Staff', email: 'staff@test.com',
  isPlatformAdmin: false,
  impersonatedBy: null,
  sessionId: null,
  readOnly: false,
  expiresAt: Date.now() + 60_000,
  tokenType: 'cognito',
}

function renderPage(stats?: Awaited<ReturnType<typeof rnModule.releaseNotesApi.stats>>) {
  vi.spyOn(rnModule.releaseNotesApi, 'list').mockResolvedValue({ data: [], meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } } })
  if (stats) {
    vi.spyOn(rnModule.releaseNotesApi, 'stats').mockResolvedValue(stats)
  } else {
    vi.spyOn(rnModule.releaseNotesApi, 'stats').mockRejectedValue(new Error('unavailable'))
  }
  return render(
    <QueryClientProvider client={__qc()}><MemoryRouter>
      <SessionContext.Provider value={{ session: SESSION, status: 'authenticated', login: vi.fn(), logout: vi.fn(), refreshNow: vi.fn(), setActiveRole: vi.fn(), startImpersonation: vi.fn(), exitImpersonation: vi.fn() }}>
        <><ReleaseNoteList /></>
      </SessionContext.Provider>
    </MemoryRouter></QueryClientProvider>,
  )
}

function __qc() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

describe('ReleaseNoteList', () => {
  it('renders page header', () => {
    renderPage()
    expect(screen.getByText(/Authorise and track carton pickups/)).toBeTruthy()
  })
  it('shows empty state when no notes', async () => {
    renderPage()
    expect(await screen.findByText(/No release notes match/)).toBeTruthy()
  })

  // P2-3 — §9.1 stats row from GET /v1/release-notes/stats
  it('renders the stats row from the stats endpoint', async () => {
    renderPage({ active: 11, partial_active: 3, picked_up_today: 14, picked_up: 132, expired: 1 })
    expect(await screen.findByText('Awaiting pickup')).toBeInTheDocument()
    expect(screen.getByText('11')).toBeInTheDocument()
    expect(screen.getByText('Partial pickups')).toBeInTheDocument()
    expect(screen.getByText('Expired, uncollected')).toBeInTheDocument()
    // Picked up today was history, not work (FD-18).
    expect(screen.queryByText('Picked up today')).toBeNull()
  })

  it('a stat applies its status filter, and a second click lifts it (FD-18)', async () => {
    renderPage({ active: 11, partial_active: 3, picked_up_today: 14, picked_up: 132, expired: 1 })
    const expired = await screen.findByRole('button', { name: /Expired, uncollected/ })
    await userEvent.click(expired)
    await waitFor(() => expect(rnModule.releaseNotesApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'expired' })))
    expect(expired).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(expired)
    await waitFor(() => expect(expired).toHaveAttribute('aria-pressed', 'false'))
  })

  it('hides the stats row when the stats endpoint fails', async () => {
    renderPage()
    await screen.findByText(/No release notes match/)
    expect(screen.queryByText('Awaiting pickup')).toBeNull()
  })
})
