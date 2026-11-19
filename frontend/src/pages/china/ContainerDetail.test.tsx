import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { useState, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { withQuery } from '../../test/queryWrapper'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import type { Session, UserRole } from '../../auth/types'
import { ApiError } from '../../api/client'
import { containerDocumentsApi, containersApi, uploadToPresignedUrl, type Container } from '../../api/tracking'
import { packingListApi, type PackingList } from '../../api/packingList'
import { TopBarContext } from '../../shell/TopBarContext'
import { ContainerDetail } from './ContainerDetail'

function TopBarWrapper({ children }: { children: ReactNode }) {
  const [suffix, setSuffix] = useState<string | null>(null)
  const [subtitle, setSubtitle] = useState<string | null>(null)
  const [actions, setActions] = useState<ReactNode | null>(null)
  return (
    <TopBarContext.Provider value={{ suffix, setSuffix, subtitle, setSubtitle, actions, setActions }}>
      {children}
    </TopBarContext.Provider>
  )
}

vi.mock('../../api/tracking', () => ({
  containersApi: { get: vi.fn(), updateStatus: vi.fn(), events: vi.fn() },
  containerDocumentsApi: { list: vi.fn(), presignUpload: vi.fn(), confirmUpload: vi.fn(), downloadUrl: vi.fn() },
  uploadToPresignedUrl: vi.fn(),
}))
vi.mock('../../api/packingList', () => ({
  packingListApi: { listByContainer: vi.fn() },
}))

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

const containerStub: Container = {
  id: 'c1',
  tenant_id: 't1',
  container_number: 'MSCU1234567',
  parcel_number: 'SHX-04891',
  origin: 'China',
  destination: 'Nigeria',
  ship_date: null,
  estimated_arrival_date: '2026-08-14',
  actual_arrival_date: null,
  status: 'loading',
  notes: null,
  created_by: 'staff-1',
  created_at: '2026-07-25',
  updated_at: '2026-07-25',
  vessel_name: null,
  voyage_number: null,
  shipping_line: null,
  seal_number: null,
  container_type: null,
  capacity_cbm: null,
  recommended_cbm: null,
  created_by_name: null,
}

const plStub: PackingList = {
  id: 'pl1',
  tenant_id: 't1',
  reference: 'PL-20260725-001',
  container_id: 'c1',
  container_number: 'ACME-001',
  customer_id: 'cust1',
  customer_name: 'CHRIS(GQL)',
  customer_phone: '081-62009462',
  status: 'approved',
  items: [],
  total_cbm: '0.093',
  total_weight_kg: '36.600',
  carton_count: 4,
  created_by: 'staff-1',
  approved_by: 'admin-1',
  approved_at: '2026-07-26',
  rejected_by: null,
  rejected_at: null,
  approval_comments: null,
  created_at: '2026-07-25',
  updated_at: '2026-07-26',
}

function renderPage(role: UserRole) {
  return render(
    withQuery(
      <SessionContext.Provider value={makeContextValue(role)}>
        <MemoryRouter initialEntries={['/containers/c1']}>
          <TopBarWrapper>
            <Routes>
              <Route path="/containers/:id" element={<ContainerDetail />} />
            </Routes>
          </TopBarWrapper>
        </MemoryRouter>
      </SessionContext.Provider>,
    ),
  )
}

describe('ContainerDetail', () => {
  beforeEach(() => {
    vi.mocked(containersApi.get).mockReset()
    vi.mocked(containersApi.updateStatus).mockReset()
    vi.mocked(containersApi.events).mockReset()
    vi.mocked(containersApi.events).mockResolvedValue([])
    vi.mocked(packingListApi.listByContainer).mockReset()
    vi.mocked(packingListApi.listByContainer).mockResolvedValue({
      data: [plStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
  })

  it('renders the container number and status', async () => {
    vi.mocked(containersApi.get).mockResolvedValue(containerStub)
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByRole('heading', { name: 'MSCU1234567' })).toBeInTheDocument())
    expect(screen.getAllByText('Loading').length).toBeGreaterThan(0)
  })

  it('shows the advance-status action for china_office_staff on a china-owned stage', async () => {
    vi.mocked(containersApi.get).mockResolvedValue(containerStub)
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByText('Advance to Sealed')).toBeInTheDocument())
  })

  it('hides the advance-status action for nigeria_office_staff on a china-owned stage', async () => {
    vi.mocked(containersApi.get).mockResolvedValue(containerStub)
    renderPage('nigeria_office_staff')
    await waitFor(() => expect(screen.getByRole('heading', { name: 'MSCU1234567' })).toBeInTheDocument())
    expect(screen.queryByText(/Advance to/)).not.toBeInTheDocument()
  })

  it('shows the cargo summary, top-shippers list, and utilization bar on the overview', async () => {
    vi.mocked(containersApi.get).mockResolvedValue({ ...containerStub, container_type: "40' HC" })
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByText('Cargo summary')).toBeInTheDocument())
    // Aggregated from the single approved packing list (4 cartons, 0.093 CBM, 1 customer).
    expect(screen.getByText('Total packages')).toBeInTheDocument()
    expect(screen.getByText('Top shippers by CBM')).toBeInTheDocument()
    expect(screen.getByText('CHRIS(GQL)')).toBeInTheDocument()
    // container_type "40' HC" → 76 CBM capacity → utilization bar shown, plus the hero type badge.
    expect(screen.getByText('Utilization')).toBeInTheDocument()
    // "40' HC" shows in both the hero badge and the Container-info row.
    expect(screen.getAllByText("40' HC").length).toBeGreaterThanOrEqual(2)
  })

  it('switches to the packing lists tab and lists them', async () => {
    vi.mocked(containersApi.get).mockResolvedValue(containerStub)
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByRole('heading', { name: 'MSCU1234567' })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('tab', { name: 'Packing lists' }))
    // The Packages cell names the unit rather than showing a bare row count.
    expect(screen.getAllByText(/cartons?|bales?|bags?|—/).length).toBeGreaterThan(0)
    expect(screen.getByText('approved')).toBeInTheDocument()
  })

  it('sorts the packing-lists sub-table by Ref # client-side, with no API param involved', async () => {
    vi.mocked(containersApi.get).mockResolvedValue(containerStub)
    vi.mocked(packingListApi.listByContainer).mockResolvedValue({
      data: [
        { ...plStub, id: 'pl1', reference: 'PL-20260725-002' },
        { ...plStub, id: 'pl2', reference: 'PL-20260725-001' },
      ],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 2 } },
    })
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByRole('heading', { name: 'MSCU1234567' })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('tab', { name: 'Packing lists' }))

    const refCellsInOrder = () => screen.getAllByText(/^PL-20260725-00[12]$/).map((el) => el.textContent)

    // Unsorted: renders in API return order (002 then 001).
    await waitFor(() => expect(refCellsInOrder()).toEqual(['PL-20260725-002', 'PL-20260725-001']))

    await userEvent.click(screen.getByText('Ref #'))
    expect(refCellsInOrder()).toEqual(['PL-20260725-001', 'PL-20260725-002'])

    await userEvent.click(screen.getByText('Ref #'))
    expect(refCellsInOrder()).toEqual(['PL-20260725-002', 'PL-20260725-001'])

    // Purely client-side — listByContainer is never called again for a sort.
    expect(packingListApi.listByContainer).toHaveBeenCalledTimes(1)
  })

  it('advances via the two-step flow: details form, then a silent-stage confirmation', async () => {
    vi.mocked(containersApi.get).mockResolvedValue({ ...containerStub, status: 'sealed' })
    vi.mocked(containersApi.updateStatus).mockResolvedValue({ ...containerStub, status: 'in_transit' })
    renderPage('china_office_staff')
    await waitFor(() => expect(screen.getByText('Advance to In Transit')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Advance to In Transit'))

    // Step 1 — Continue is gated on the required ship date
    const continueButton = screen.getByRole('button', { name: 'Continue' })
    expect(continueButton).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Ship date', { exact: false, selector: 'input' }), '2026-08-01')
    expect(continueButton).toBeEnabled()
    await userEvent.click(continueButton)

    // Step 2 — in_transit sends nothing to customers; the confirm says so
    expect(screen.getByText(/no customer notifications are sent at this stage/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => expect(containersApi.updateStatus).toHaveBeenCalledTimes(1))
    expect(containersApi.updateStatus).toHaveBeenCalledWith('c1', {
      new_status: 'in_transit',
      ship_date: '2026-08-01',
      notes: undefined,
    })
  })

  it('warns how many customers will be contacted before confirming a notifying stage (A5)', async () => {
    vi.mocked(containersApi.get).mockResolvedValue({ ...containerStub, status: 'customs_clearance' })
    vi.mocked(containersApi.updateStatus).mockResolvedValue({ ...containerStub, status: 'cleared' })
    renderPage('nigeria_office_staff')
    await waitFor(() => expect(screen.getByText('Advance to Cleared')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Advance to Cleared'))

    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))

    // One distinct customer on the container's packing lists (plStub)
    expect(screen.getByText('Customers will be contacted')).toBeInTheDocument()
    expect(screen.getByText(/billing will be generated for 1 customer\b/i)).toBeInTheDocument()

    // Back returns to the form without submitting
    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByRole('button', { name: 'Continue' })).toBeInTheDocument()
    expect(containersApi.updateStatus).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm & notify' }))
    await waitFor(() => expect(containersApi.updateStatus).toHaveBeenCalledWith('c1', {
      new_status: 'cleared',
      ship_date: undefined,
      notes: undefined,
    }))
  })

  it('shows the customer contact on the packing-list table', async () => {
    vi.mocked(containersApi.get).mockResolvedValue(containerStub)
    renderPage('china_office_staff')
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'MSCU1234567' })).toBeInTheDocument(),
    )

    // The overview's top-shippers list is a compact ranked view (no contact);
    // the phone belongs on the full per-customer breakdown so staff can call
    // without opening the customer record.
    await userEvent.click(screen.getByRole('tab', { name: 'Packing lists' }))
    expect(screen.getAllByText('081-62009462').length).toBeGreaterThan(0)
  })

  it('follows the cursor so cargo totals cover every packing list, not just page one', async () => {
    // Regression: the page fetched a single page (50) but aggregated it as if
    // it were the whole container, so a real manifest import (68 lists) showed
    // 50 customers and an understated CBM.
    const page1 = Array.from({ length: 50 }, (_, i) => ({
      ...plStub,
      id: `pl-a-${i}`,
      customer_id: `cust-a-${i}`,
      carton_count: 1,
      total_cbm: '1.000',
    }))
    const page2 = Array.from({ length: 18 }, (_, i) => ({
      ...plStub,
      id: `pl-b-${i}`,
      customer_id: `cust-b-${i}`,
      carton_count: 1,
      total_cbm: '1.000',
    }))
    vi.mocked(packingListApi.listByContainer)
      .mockResolvedValueOnce({
        data: page1,
        meta: { pagination: { has_more: true, next_cursor: 'CUR2', total_count: 68 } },
      })
      .mockResolvedValueOnce({
        data: page2,
        meta: { pagination: { has_more: false, next_cursor: null, total_count: 68 } },
      })
    vi.mocked(containersApi.get).mockResolvedValue(containerStub)

    renderPage('china_office_staff')
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'MSCU1234567' })).toBeInTheDocument(),
    )

    expect(vi.mocked(packingListApi.listByContainer)).toHaveBeenCalledTimes(2)
    // Totals reflect both pages, not the 50 of page one: the customers and
    // cartons tiles both read 68. Page one alone would have shown 50.
    expect(screen.getAllByText('68').length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText('50')).not.toBeInTheDocument()
  })

  it('shows a top-5 shippers-by-CBM list with a View-all to packing lists', async () => {
    const lists = Array.from({ length: 20 }, (_, i) => ({
      ...plStub,
      id: `pl-${i}`,
      customer_id: `cust-${i}`,
      customer_name: `Customer ${i}`,
      carton_count: 1,
      total_cbm: String(20 - i), // descending, so the top 5 are 0..4
    }))
    vi.mocked(packingListApi.listByContainer).mockResolvedValue({
      data: lists,
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 20 } },
    })
    vi.mocked(containersApi.get).mockResolvedValue(containerStub)

    renderPage('china_office_staff')
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'MSCU1234567' })).toBeInTheDocument(),
    )

    // Compact ranked list, not an uncapped table.
    expect(screen.getByText('Top shippers by CBM')).toBeInTheDocument()
    expect(screen.getByText('20 customers on this container')).toBeInTheDocument()
    // Only the top 5 by CBM show.
    expect(screen.getByText('Customer 0')).toBeInTheDocument()
    expect(screen.getByText('Customer 4')).toBeInTheDocument()
    expect(screen.queryByText('Customer 5')).not.toBeInTheDocument()

    // View-all switches to the full per-customer breakdown on the packing-lists tab.
    await userEvent.click(screen.getByRole('button', { name: 'View all →' }))
    expect(screen.getByText('Packing lists on this container')).toBeInTheDocument()
  })
})

describe('ContainerDetail document upload (audit BE-12)', () => {
  beforeEach(() => {
    vi.mocked(containersApi.get).mockResolvedValue(containerStub)
    vi.mocked(containersApi.events).mockResolvedValue([])
    vi.mocked(packingListApi.listByContainer).mockResolvedValue({
      data: [],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 0 } },
    })
    vi.mocked(containerDocumentsApi.list).mockResolvedValue([])
    vi.mocked(containerDocumentsApi.presignUpload).mockReset()
    vi.mocked(uploadToPresignedUrl).mockReset()
    vi.mocked(containerDocumentsApi.confirmUpload).mockReset()
  })

  async function openUpload(): Promise<HTMLElement> {
    renderPage('china_office_staff')
    await userEvent.click(await screen.findByRole('tab', { name: /Documents/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Upload document' }))
    return screen.findByRole('dialog')
  }

  function pick(dialog: HTMLElement, file: File): Promise<void> {
    const input = dialog.querySelector('input[type="file"]') as HTMLInputElement
    // userEvent.upload would drop a file that does not match `accept`; a real browser lets "All files" through.
    return userEvent.upload(input, file, { applyAccept: false })
  }

  it('refuses a file the browser could not type, in the dialog, without asking the server', async () => {
    const dialog = await openUpload()
    await pick(dialog, new File(['x'], 'scan', { type: '' }))
    await userEvent.click(screen.getByRole('button', { name: 'Upload' }))
    expect(await screen.findByText('Choose a PDF, JPEG, PNG or WebP file.')).toBeInTheDocument()
    expect(dialog).toContainElement(screen.getByText('Choose a PDF, JPEG, PNG or WebP file.'))
    expect(containerDocumentsApi.presignUpload).not.toHaveBeenCalled()
  })

  it('sends the real type, never application/octet-stream', async () => {
    vi.mocked(containerDocumentsApi.presignUpload).mockResolvedValue({
      upload_url: 'https://storage.test/put',
      document_id: 'd1',
      s3_key: 't1/containers/c1/bl.pdf',
      expires_in_seconds: 900,
    } as never)
    const dialog = await openUpload()
    await pick(dialog, new File(['%PDF'], 'bl.pdf', { type: 'application/pdf' }))
    await userEvent.click(screen.getByRole('button', { name: 'Upload' }))
    await waitFor(() =>
      expect(containerDocumentsApi.presignUpload).toHaveBeenCalledWith('c1', {
        filename: 'bl.pdf',
        content_type: 'application/pdf',
        document_type: 'bill_of_lading',
        size_bytes: 4,
      }),
    )
  })

  it('shows a server refusal inside the dialog, not behind it', async () => {
    vi.mocked(containerDocumentsApi.presignUpload).mockRejectedValue(
      new ApiError(
        {
          type: 'about:blank',
          title: 'Business Rule Violation',
          status: 422,
          detail: "content_type 'image/png' is not allowed.",
          error_code: 'BUSINESS_RULE_VIOLATION',
          rule_id: 'INVALID_CONTENT_TYPE',
        },
        null,
      ),
    )
    const dialog = await openUpload()
    await pick(dialog, new File(['x'], 'a.png', { type: 'image/png' }))
    await userEvent.click(screen.getByRole('button', { name: 'Upload' }))
    const message = await screen.findByText("content_type 'image/png' is not allowed.")
    expect(dialog).toContainElement(message)
  })

  const presigned = {
    upload_url: 'https://storage.test/put',
    document_id: 'd1',
    s3_key: 't1/containers/c1/x-bl.pdf',
    expires_in_seconds: 900,
  } as never

  it('confirms the upload after the file lands, then closes the dialog', async () => {
    vi.mocked(containerDocumentsApi.presignUpload).mockResolvedValue(presigned)
    vi.mocked(uploadToPresignedUrl).mockResolvedValue()
    vi.mocked(containerDocumentsApi.confirmUpload).mockResolvedValue({} as never)
    const dialog = await openUpload()
    await pick(dialog, new File(['%PDF'], 'bl.pdf', { type: 'application/pdf' }))
    await userEvent.click(screen.getByRole('button', { name: 'Upload' }))
    await waitFor(() => expect(containerDocumentsApi.confirmUpload).toHaveBeenCalledWith('c1', 'd1'))
    expect(vi.mocked(uploadToPresignedUrl).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(containerDocumentsApi.confirmUpload).mock.invocationCallOrder[0]!,
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('shows a file refused at confirmation (over the limit on Azure) inside the dialog', async () => {
    vi.mocked(containerDocumentsApi.presignUpload).mockResolvedValue(presigned)
    vi.mocked(uploadToPresignedUrl).mockResolvedValue()
    vi.mocked(containerDocumentsApi.confirmUpload).mockRejectedValue(
      new ApiError(
        {
          type: 'about:blank',
          title: 'Business Rule Violation',
          status: 422,
          detail: 'The file is larger than 5 MB.',
          error_code: 'BUSINESS_RULE_VIOLATION',
          rule_id: 'FILE_TOO_LARGE',
        },
        null,
      ),
    )
    const dialog = await openUpload()
    await pick(dialog, new File(['%PDF'], 'bl.pdf', { type: 'application/pdf' }))
    await userEvent.click(screen.getByRole('button', { name: 'Upload' }))
    expect(dialog).toContainElement(await screen.findByText('The file is larger than 5 MB.'))
  })

  it('refuses a file over 5 MB in the dialog, without asking the server', async () => {
    const dialog = await openUpload()
    const big = new File(['x'], 'scan.pdf', { type: 'application/pdf' })
    Object.defineProperty(big, 'size', { value: 6 * 1024 * 1024 })
    await pick(dialog, big)
    await userEvent.click(screen.getByRole('button', { name: 'Upload' }))
    expect(await screen.findByText('This file is 6.0 MB. The limit is 5 MB.')).toBeInTheDocument()
    expect(containerDocumentsApi.presignUpload).not.toHaveBeenCalled()
  })
})

