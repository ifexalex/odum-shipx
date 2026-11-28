/**
 * The cross-tenant audit log: its action filter offers only actions the backend writes (PA-05), each row names its
 * tenant from the server (PA-02) and shows who acted (PA-06).
 */
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PLATFORM_AUDIT_ACTIONS } from '../../api/platformAuditActions'
import { platformApi } from '../../api/tenantManagement'
import { withQuery } from '../../test/queryWrapper'
import { PlatformAuditLog } from './PlatformAuditLog'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return { ...original, platformApi: { ...original.platformApi, auditLog: vi.fn(), listAllTenants: vi.fn() } }
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(platformApi.listAllTenants).mockResolvedValue([])
  vi.mocked(platformApi.auditLog).mockResolvedValue({
    data: [
      {
        id: 'e1', action: 'IMPERSONATION_START', actor_id: 'f00dbabe-1234-4321-8888-000000000001',
        target_tenant_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', target_tenant_name: 'Acme Logistics',
        details: null, ip_address: '203.0.113.9', created_at: '2026-11-28T09:00:00Z',
      },
      {
        id: 'e2', action: 'TENANT_DATA_EXPORTED', actor_id: null, target_tenant_id: null, target_tenant_name: null,
        details: null, ip_address: null, created_at: '2026-11-28T08:00:00Z',
      },
      {
        id: 'e3', action: 'TENANT_SUSPENDED', actor_id: 'f00dbabe-1234-4321-8888-000000000002', actor_name: 'Ada Nwachukwu',
        actor_role: 'owner', target_tenant_id: null, target_tenant_name: 'Beta Cargo', details: { reason: 'Unpaid' },
        before_state: { status: 'active' }, after_state: { status: 'suspended' }, ip_address: null,
        created_at: '2026-11-28T07:00:00Z',
      },
    ],
    meta: { pagination: { has_more: false, next_cursor: null, total_count: 3 } },
  })
})

function renderPage() {
  return render(withQuery(<MemoryRouter initialEntries={['/platform/audit-log']}><PlatformAuditLog /></MemoryRouter>))
}

describe('PlatformAuditLog', () => {
  it('offers exactly the actions the backend writes', async () => {
    renderPage()
    const select = await screen.findByLabelText('Action')
    const options = within(select).getAllByRole('option').map((o) => o.getAttribute('value')).filter(Boolean)
    expect(options).toEqual([...PLATFORM_AUDIT_ACTIONS])
    expect(options).not.toContain('IMPERSONATION_STARTED')
  })

  it('names the tenant from the row and shows who acted', async () => {
    renderPage()
    expect(await screen.findByText('Acme Logistics')).toBeInTheDocument()
    expect(screen.getByText('f00dbabe…')).toBeInTheDocument()
    expect(screen.getByText('Platform job')).toBeInTheDocument()
  })

  it('names the actor from the directory and shows what changed (Phase 1)', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    renderPage()
    expect(await screen.findByText('Ada Nwachukwu')).toBeInTheDocument()
    const buttons = screen.getAllByRole('button', { name: 'Details' })
    await userEvent.click(buttons.at(-1)!)
    expect(await screen.findByText('Before')).toBeInTheDocument()
    expect(screen.getByText('After')).toBeInTheDocument()
    expect(screen.getByText(/"suspended"/)).toBeInTheDocument()
  })
})
