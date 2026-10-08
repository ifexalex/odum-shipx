/**
 * B6 — tenant activity feed: renders audit entries with action badges,
 * humanised entity + relative time; scopes to one actor via actorId; hides the
 * actor name on the staff-profile (showActor=false).
 */
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { configApi, type TenantActivityEntry } from '../api/tenantManagement'
import { ActivityFeed } from './ActivityFeed'

vi.mock('../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/tenantManagement')>()
  return { ...original, configApi: { ...original.configApi, activity: vi.fn() } }
})

function entry(overrides: Partial<TenantActivityEntry>): TenantActivityEntry {
  return {
    id: 'a1', action: 'CREATE', entity_type: 'packing_list', entity_id: 'pl1',
    actor_id: 'u1', actor_role: 'china_office_staff', actor_name: 'Kwame Asante',
    before_state: null, after_state: null,
    created_at: new Date(Date.now() - 3600_000).toISOString(),
    ...overrides,
  }
}

function ok(entries: TenantActivityEntry[]) {
  return { data: entries, meta: { pagination: { has_more: false, next_cursor: null, total_count: entries.length } } } as never
}

describe('ActivityFeed (B6)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders entries with action badge, humanised entity, and actor', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(ok([
      entry({ action: 'CREATE', entity_type: 'packing_list' }),
      entry({ id: 'a2', action: 'STATUS_CHANGE', entity_type: 'container', actor_name: 'Amara Okafor' }),
    ]))
    render(<ActivityFeed />)

    await waitFor(() => expect(screen.getByText('packing list')).toBeInTheDocument())
    expect(screen.getByText('container')).toBeInTheDocument()
    expect(screen.getByText('CREATE')).toBeInTheDocument()
    expect(screen.getByText('STATUS CHANGE')).toBeInTheDocument()
    expect(screen.getByText(/by Kwame Asante · 1h ago/)).toBeInTheDocument()
  })

  it('scopes the request to a single actor when actorId is given, and hides the actor name', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(ok([entry({})]))
    render(<ActivityFeed actorId="u1" showActor={false} />)

    await waitFor(() => expect(configApi.activity).toHaveBeenCalledWith({ actorId: 'u1', limit: 8 }))
    // Actor name suppressed on the staff profile
    expect(screen.queryByText(/by Kwame Asante/)).toBeNull()
  })

  it('shows an empty state when there is no activity', async () => {
    vi.mocked(configApi.activity).mockResolvedValue(ok([]))
    render(<ActivityFeed />)
    await waitFor(() => expect(screen.getByText('No recent activity.')).toBeInTheDocument())
  })
})
