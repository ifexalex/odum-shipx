/**
 * Platform admins (platform audit Phase 1, C-28): owners invite and manage; nobody manages their own row.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { platformSecurityApi, type PlatformAdmin, type PlatformMe } from '../../api/platformSecurity'
import { withQuery } from '../../test/queryWrapper'
import { PlatformAdmins } from './PlatformAdmins'

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
    platformSecurityApi: { ...original.platformSecurityApi, listAdmins: vi.fn(), inviteAdmin: vi.fn(), updateAdmin: vi.fn() },
  }
})

function admin(overrides: Partial<PlatformAdmin>): PlatformAdmin {
  return {
    id: 'pu-1',
    email: 'ada@shipx.test',
    name: 'Ada',
    role: 'owner',
    status: 'active',
    last_seen_at: '2026-11-28T09:00:00Z',
    disabled_at: null,
    created_at: '2026-11-01T09:00:00Z',
    updated_at: '2026-11-01T09:00:00Z',
    invited_by_name: null,
    ...overrides,
  }
}

function renderPage() {
  return render(withQuery(<MemoryRouter><PlatformAdmins /></MemoryRouter>))
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(platformSecurityApi.listAdmins).mockResolvedValue([
    admin({}),
    admin({ id: 'pu-2', name: 'Tunde', email: 'tunde@shipx.test', role: 'support', invited_by_name: 'Ada' }),
  ])
})

describe('PlatformAdmins', () => {
  it('lets an owner invite an admin with a role', async () => {
    me.value = { id: 'pu-1', permissions: ['read', 'admins'] }
    vi.mocked(platformSecurityApi.inviteAdmin).mockResolvedValue(admin({ id: 'pu-3', name: 'Ngozi', status: 'invited' }))
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Invite admin' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Name/), 'Ngozi')
    await userEvent.type(within(dialog).getByLabelText(/Email/), 'ngozi@shipx.test')
    await userEvent.selectOptions(within(dialog).getByLabelText('Role'), 'finance')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Send invitation' }))
    expect(platformSecurityApi.inviteAdmin).toHaveBeenCalledWith({ email: 'ngozi@shipx.test', name: 'Ngozi', role: 'finance' })
  })

  it('offers Manage on everyone but the owner themselves', async () => {
    me.value = { id: 'pu-1', permissions: ['read', 'admins'] }
    renderPage()
    expect(await screen.findByText('(you)')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Manage' })).toHaveLength(1)
  })

  it('disables an admin', async () => {
    me.value = { id: 'pu-1', permissions: ['read', 'admins'] }
    vi.mocked(platformSecurityApi.updateAdmin).mockResolvedValue(admin({ id: 'pu-2', status: 'disabled' }))
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Manage' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Disable access' }))
    expect(platformSecurityApi.updateAdmin).toHaveBeenCalledWith('pu-2', { disabled: true })
  })

  it('shows a non-owner the list only', async () => {
    me.value = { id: 'pu-2', permissions: ['read', 'support'] }
    renderPage()
    expect(await screen.findByText('Tunde')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Invite admin' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Manage' })).toBeNull()
  })
})
