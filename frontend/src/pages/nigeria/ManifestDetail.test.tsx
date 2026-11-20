import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { withQuery } from '../../test/queryWrapper'
import { manifestApi, type Manifest } from '../../api/manifest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session, UserRole } from '../../auth/types'
import { ManifestDetail } from './ManifestDetail'

vi.mock('../../api/manifest', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/manifest')>()
  return {
    ...actual,
    manifestApi: {
      get: vi.fn(),
      verify: vi.fn(),
      resolveDiscrepancy: vi.fn(),
      getEvidenceUploadUrl: vi.fn(),
    },
  }
})

function makeSession(role: UserRole): Session {
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

function makeContextValue(role: UserRole): SessionContextValue {
  return {
    session: makeSession(role),
    status: 'authenticated',
    login: vi.fn(),
    logout: vi.fn(),
    startImpersonation: vi.fn(),
    exitImpersonation: vi.fn(),
    refreshNow: vi.fn(), setActiveRole: vi.fn(),
  }
}

function manifestStub(overrides: Partial<Manifest> = {}): Manifest {
  return {
    id: 'mf1',
    tenant_id: 't1',
    container_id: 'c1',
    container_number: 'HLBU9384712',
    container_status: 'loading',
    total_customers: 1,
    total_cartons: 22,
    total_weight_kg: '148.000',
    total_cbm: '2.140000',
    verification_status: 'pending',
    verified_by: null,
    verified_at: null,
    notes: null,
    customers: [
      {
        customer_id: 'cust1',
        customer_phone: '080-33259345',
      customer_name: 'Emeka Eze',
        packing_list_id: 'pl1',
        carton_count: 22,
        total_weight_kg: '148.000',
        total_cbm: '2.140000',
        carton_tags: ['SHX-00001', 'SHX-00002'],
      },
    ],
    created_at: '2026-07-28',
    updated_at: '2026-07-28',
    ...overrides,
  }
}

function renderPage(role: UserRole) {
  return render(
    withQuery(
      <SessionContext.Provider value={makeContextValue(role)}>
        <MemoryRouter initialEntries={['/manifests/mf1']}>
          <Routes>
            <Route path="/manifests/:id" element={<ManifestDetail />} />
          </Routes>
        </MemoryRouter>
      </SessionContext.Provider>,
    ),
  )
}

describe('ManifestDetail', () => {
  beforeEach(() => {
    vi.mocked(manifestApi.get).mockReset()
    vi.mocked(manifestApi.verify).mockReset()
    vi.mocked(manifestApi.resolveDiscrepancy).mockReset()
  })

  it('shows Verify manifest for china_office_staff on a pending manifest', async () => {
    vi.mocked(manifestApi.get).mockResolvedValue(manifestStub())
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByRole('button', { name: /Verify manifest/ })).toBeInTheDocument())
  })

  it('hides Verify manifest for tenant_admin (read-only role here)', async () => {
    vi.mocked(manifestApi.get).mockResolvedValue(manifestStub())
    renderPage('tenant_admin')
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Manifest HLBU9384712' })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Verify manifest/ })).not.toBeInTheDocument()
  })

  it('shows Resolve discrepancy for nigeria_office_staff when discrepancies_found', async () => {
    vi.mocked(manifestApi.get).mockResolvedValue(manifestStub({ verification_status: 'discrepancies_found' }))
    renderPage('nigeria_office_staff')
    await waitFor(() => expect(screen.getByRole('button', { name: /Resolve discrepancy/ })).toBeInTheDocument())
  })

  it('hides Resolve discrepancy for china_office_staff — verify-only, not resolve', async () => {
    vi.mocked(manifestApi.get).mockResolvedValue(manifestStub({ verification_status: 'discrepancies_found' }))
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Manifest HLBU9384712' })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Resolve discrepancy/ })).not.toBeInTheDocument()
  })

  it('submits a Verified outcome with no discrepancies', async () => {
    vi.mocked(manifestApi.get).mockResolvedValue(manifestStub())
    vi.mocked(manifestApi.verify).mockResolvedValue(manifestStub({ verification_status: 'verified' }))
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByRole('button', { name: /Verify manifest/ })).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /Verify manifest/ }))
    await userEvent.click(screen.getByRole('button', { name: /Submit verification/ }))

    await waitFor(() =>
      expect(manifestApi.verify).toHaveBeenCalledWith('mf1', { verification_status: 'verified', discrepancies: undefined }),
    )
  })

  it('builds a discrepancy payload from the customer + carton tag picker', async () => {
    vi.mocked(manifestApi.get).mockResolvedValue(manifestStub())
    vi.mocked(manifestApi.verify).mockResolvedValue(manifestStub({ verification_status: 'discrepancies_found' }))
    renderPage('nigeria_office_staff')
    await waitFor(() => expect(screen.getByRole('button', { name: /Verify manifest/ })).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /Verify manifest/ }))
    const dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /Discrepancies found/ }))

    await userEvent.selectOptions(within(dialog).getByLabelText('Customer'), 'cust1')
    await userEvent.click(within(dialog).getByText('SHX-00001'))

    const submitButton = within(dialog).getByRole('button', { name: /Submit verification/ })
    expect(submitButton).toBeEnabled()
    await userEvent.click(submitButton)

    await waitFor(() =>
      expect(manifestApi.verify).toHaveBeenCalledWith('mf1', {
        verification_status: 'discrepancies_found',
        discrepancies: [{ customer_id: 'cust1', carton_tags: ['SHX-00001'], type: 'missing', notes: undefined }],
      }),
    )
  })

  it('disables submit for a discrepancies outcome until a customer and tag are picked', async () => {
    vi.mocked(manifestApi.get).mockResolvedValue(manifestStub())
    renderPage('nigeria_office_staff')
    await waitFor(() => expect(screen.getByRole('button', { name: /Verify manifest/ })).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /Verify manifest/ }))
    await userEvent.click(screen.getByRole('button', { name: /Discrepancies found/ }))

    expect(screen.getByRole('button', { name: /Submit verification/ })).toBeDisabled()
  })

  it('resolves a discrepancy with resolution notes', async () => {
    vi.mocked(manifestApi.get).mockResolvedValue(manifestStub({ verification_status: 'discrepancies_found' }))
    vi.mocked(manifestApi.resolveDiscrepancy).mockResolvedValue(manifestStub({ verification_status: 'resolved' }))
    renderPage('nigeria_office_staff')
    await waitFor(() => expect(screen.getByRole('button', { name: /Resolve discrepancy/ })).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /Resolve discrepancy/ }))
    await userEvent.type(screen.getByLabelText('Resolution notes', { exact: false }), 'Recounted, all cartons found.')
    await userEvent.click(screen.getByRole('button', { name: /Confirm resolution/ }))

    await waitFor(() =>
      expect(manifestApi.resolveDiscrepancy).toHaveBeenCalledWith('mf1', {
        resolution_notes: 'Recounted, all cartons found.',
      }),
    )
  })

  it('shows weight discrepancies when present', async () => {
    vi.mocked(manifestApi.get).mockResolvedValue(
      manifestStub({
        weight_discrepancies: [
          {
            item_id: 'i1',
            carton_tag: 'SHX-00005',
            tracking_code: 'TRK-001',
            customer_id: 'cust1',
            weight_dispatch_kg: 12.5,
            weight_actual_kg: 14.2,
            difference_kg: 1.7,
          },
        ],
      }),
    )
    renderPage('nigeria_office_staff')
    await waitFor(() => expect(screen.getByText('Weight discrepancies')).toBeInTheDocument())
    expect(screen.getByText('SHX-00005')).toBeInTheDocument()
    expect(screen.getByText('+1.7')).toBeInTheDocument()
  })

  // F-D3 — manifest-verify photo upload
  it('renders the verification-evidence gallery with download links', async () => {
    vi.mocked(manifestApi.get).mockResolvedValue(
      manifestStub({
        evidence: [
          {
            id: 'ev1',
            file_name: 'carton-abc.jpg',
            file_type: 'image/jpeg',
            label: 'Damaged — Emeka Eze (SHX-00001)',
            download_url: 'https://s3.example/download/ev1',
            created_at: '2026-07-28T10:00:00Z',
          },
        ],
      }),
    )
    renderPage('nigeria_office_staff')
    await waitFor(() => expect(screen.getByText('Verification evidence')).toBeInTheDocument())
    const link = screen.getByRole('link', { name: /Damaged — Emeka Eze/ })
    expect(link).toHaveAttribute('href', 'https://s3.example/download/ev1')
  })

  it('offers a per-discrepancy photo uploader in the verify modal', async () => {
    vi.mocked(manifestApi.get).mockResolvedValue(manifestStub())
    renderPage('nigeria_office_staff')
    await waitFor(() => expect(screen.getByRole('button', { name: /Verify manifest/ })).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /Verify manifest/ }))
    await userEvent.click(screen.getByRole('button', { name: /Discrepancies found/ }))

    expect(screen.getByText('Photo evidence (optional)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Attach file/ })).toBeInTheDocument()
  })

  it('shows the customer contact beside the name, as the paper manifest does', async () => {
    vi.mocked(manifestApi.get).mockResolvedValue(manifestStub())
    renderPage('nigeria_office_staff')
    // Staff ring the customer when cargo lands — the number has to be on the
    // row, not one click away on the customer record.
    expect(await screen.findByText('080-33259345')).toBeInTheDocument()
  })
})
