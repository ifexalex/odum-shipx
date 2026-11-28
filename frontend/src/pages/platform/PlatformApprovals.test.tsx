/**
 * Approvals (platform audit Phase 1, C-30): who may approve, reject or cancel each request.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { platformSecurityApi, type PlatformApproval, type PlatformMe } from '../../api/platformSecurity'
import { withQuery } from '../../test/queryWrapper'
import { PlatformApprovals } from './PlatformApprovals'

const me = vi.hoisted(() => ({ value: null as unknown }))
vi.mock('../../hooks/usePlatformSecurity', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../hooks/usePlatformSecurity')>()
  return {
    ...original,
    usePlatformMe: () => ({ data: me.value }),
    useCanPlatform: (p: string) => ((me.value as PlatformMe | null)?.permissions ?? []).includes(p as never),
  }
})
vi.mock('../../api/platformSecurity', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/platformSecurity')>()
  return {
    ...original,
    platformSecurityApi: {
      ...original.platformSecurityApi,
      listApprovals: vi.fn(),
      approve: vi.fn(),
      reject: vi.fn(),
      cancel: vi.fn(),
    },
  }
})

function approval(overrides: Partial<PlatformApproval>): PlatformApproval {
  return {
    id: 'ap-1',
    action: 'offboard_tenant',
    target_tenant_id: 't-1',
    target_tenant_name: 'Acme Logistics',
    target_label: 't-1',
    payload: { summary: 'Offboard Acme Logistics' },
    reason: 'Contract ended',
    status: 'pending',
    requested_by: 'pu-requester',
    requested_by_name: 'Ada',
    requested_at: '2026-11-28T09:00:00Z',
    decided_by: null,
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
    expires_at: '2026-11-29T09:00:00Z',
    execute_after: null,
    executed_at: null,
    error: null,
    ...overrides,
  }
}

function meAs(id: string, permissions: string[]): PlatformMe {
  return { id, permissions } as unknown as PlatformMe
}

function renderPage() {
  return render(withQuery(<MemoryRouter><PlatformApprovals /></MemoryRouter>))
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(platformSecurityApi.listApprovals).mockResolvedValue([approval({})])
})

describe('PlatformApprovals', () => {
  it('lets a second admin approve, with a note', async () => {
    me.value = meAs('pu-other', ['read', 'approve'])
    vi.mocked(platformSecurityApi.approve).mockResolvedValue({ approval: approval({ status: 'executed' }) })
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Approve' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Note/), 'Checked with sales')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Approve and run' }))
    expect(platformSecurityApi.approve).toHaveBeenCalledWith('ap-1', 'Checked with sales')
    expect(platformSecurityApi.listApprovals).toHaveBeenCalledWith('open')
  })

  it('never offers the requester their own approval, only a cancel', async () => {
    me.value = meAs('pu-requester', ['read', 'approve'])
    renderPage()
    expect(await screen.findByText('Offboard Acme Logistics')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(screen.getByText('Waiting for another admin')).toBeInTheDocument()
  })

  it('offers a read-only role nothing to press', async () => {
    me.value = meAs('pu-finance', ['read'])
    renderPage()
    expect(await screen.findByText('Offboard Acme Logistics')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull()
  })

  it('shows when a sole admin offboarding will run', async () => {
    me.value = meAs('pu-requester', ['read', 'approve', 'admins'])
    vi.mocked(platformSecurityApi.listApprovals).mockResolvedValue([
      approval({ status: 'scheduled', execute_after: '2026-11-29T09:00:00Z' }),
    ])
    renderPage()
    expect(await screen.findByText(/unless cancelled/)).toBeInTheDocument()
    expect(screen.getByText('Scheduled')).toBeInTheDocument()
  })
})
