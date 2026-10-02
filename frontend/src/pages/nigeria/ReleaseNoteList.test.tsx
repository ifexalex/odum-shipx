import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import * as rnModule from '../../api/releaseNotes'
import { SessionContext } from '../../auth/SessionContext'
import type { Session } from '../../auth/types'
import { ReleaseNoteList } from './ReleaseNoteList'
import { TopBarTestWrapper } from '../../test/TopBarTestWrapper'

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
        <TopBarTestWrapper><ReleaseNoteList /></TopBarTestWrapper>
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
    expect(await screen.findByText('Active · awaiting pickup')).toBeInTheDocument()
    expect(screen.getByText('11')).toBeInTheDocument()
    expect(screen.getByText('Picked up today')).toBeInTheDocument()
    expect(screen.getByText('14')).toBeInTheDocument()
    expect(screen.getByText('Partial pickups')).toBeInTheDocument()
    expect(screen.getByText('Expired · uncollected')).toBeInTheDocument()
  })

  it('hides the stats row when the stats endpoint fails', async () => {
    renderPage()
    await screen.findByText(/No release notes match/)
    expect(screen.queryByText('Active · awaiting pickup')).toBeNull()
  })
})
