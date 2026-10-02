import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { excelApi, type ImportResult, type ManifestImportResult } from '../../api/excel'
import { containersApi, type Container } from '../../api/tracking'
import { UploadFailedError, uploadImportFile } from '../../api/uploads'
import { ImportPackingLists } from './ImportPackingLists'

vi.mock('../../api/tracking', () => ({
  containersApi: { list: vi.fn() },
}))
vi.mock('../../api/excel', () => ({
  excelApi: { importPackingList: vi.fn(), importManifest: vi.fn() },
}))
vi.mock('../../api/uploads', async () => {
  const actual = await vi.importActual<typeof import('../../api/uploads')>('../../api/uploads')
  return { ...actual, uploadImportFile: vi.fn() }
})

const containerStub: Container = {
  id: 'c1',
  tenant_id: 't1',
  container_number: 'MSCU1234567',
  parcel_number: null,
  origin: 'China',
  destination: 'Nigeria',
  ship_date: null,
  estimated_arrival_date: null,
  actual_arrival_date: null,
  status: 'loading',
  notes: null,
  created_by: 'staff-1',
  created_at: '2026-01-01',
  updated_at: '2026-01-01',
  vessel_name: null,
  voyage_number: null,
  shipping_line: null,
  seal_number: null,
  container_type: null,
  capacity_cbm: null,
  recommended_cbm: null,
  created_by_name: null,
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ImportPackingLists />
    </MemoryRouter>,
  )
}

/** Value of the stat tile carrying `label`, read via its sibling node. */
function statValue(label: string): string | undefined {
  return screen.getByText(label).parentElement?.querySelector('div:nth-child(2)')?.textContent ?? undefined
}

function makeFile(name = 'import.xlsx'): File {
  return new File(['col,a,b'], name, { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
}

describe('ImportPackingLists', () => {
  beforeEach(() => {
    vi.mocked(containersApi.list).mockReset()
    vi.mocked(excelApi.importPackingList).mockReset()
    vi.mocked(excelApi.importManifest).mockReset()
    vi.mocked(uploadImportFile).mockReset()
    vi.mocked(containersApi.list).mockResolvedValue({
      data: [containerStub],
      meta: { pagination: { has_more: false, next_cursor: null, total_count: 1 } },
    })
  })

  it('disables Next until a container and file are both chosen', async () => {
    renderPage()
    await userEvent.click(screen.getByRole('radio', { name: /ShipX packing-list template/ }))
    await waitFor(() => expect(screen.getByText('MSCU1234567')).toBeInTheDocument())
    expect(screen.getByText('Next: Confirm')).toBeDisabled()

    await userEvent.selectOptions(screen.getByLabelText(/Container/), 'c1')
    expect(screen.getByText('Next: Confirm')).toBeDisabled()

    const fileInput = screen.getByLabelText('Choose .xlsx file', { exact: false })
    await userEvent.upload(fileInput, makeFile())
    expect(screen.getByText('Next: Confirm')).toBeEnabled()
  })

  it('shows an upload-failed error when S3 rejects the upload', async () => {
    vi.mocked(uploadImportFile).mockRejectedValue(new UploadFailedError(403))
    renderPage()
    await userEvent.click(screen.getByRole('radio', { name: /ShipX packing-list template/ }))
    await waitFor(() => expect(screen.getByText('MSCU1234567')).toBeInTheDocument())
    await userEvent.selectOptions(screen.getByLabelText(/Container/), 'c1')
    await userEvent.upload(screen.getByLabelText('Choose .xlsx file', { exact: false }), makeFile())
    await userEvent.click(screen.getByText('Next: Confirm'))

    await userEvent.click(screen.getByText('Confirm & import'))
    await waitFor(() => expect(screen.getByText(/upload to storage failed/i)).toBeInTheDocument())
    expect(excelApi.importPackingList).not.toHaveBeenCalled()
  })

  it('shows per-row results once upload + import succeed', async () => {
    vi.mocked(uploadImportFile).mockResolvedValue('t1/imports/file.xlsx')
    const result: ImportResult = {
      total_rows: 10,
      imported: 8,
      errors: 2,
      packing_lists_created: 3,
      error_details: [{ row: 4, field: 'Customer Name', value: 'Unknown Corp', error: 'Customer not found' }],
    }
    vi.mocked(excelApi.importPackingList).mockResolvedValue(result)

    renderPage()
    await userEvent.click(screen.getByRole('radio', { name: /ShipX packing-list template/ }))
    await waitFor(() => expect(screen.getByText('MSCU1234567')).toBeInTheDocument())
    await userEvent.selectOptions(screen.getByLabelText(/Container/), 'c1')
    await userEvent.upload(screen.getByLabelText('Choose .xlsx file', { exact: false }), makeFile())
    await userEvent.click(screen.getByText('Next: Confirm'))
    await userEvent.click(screen.getByText('Confirm & import'))

    await waitFor(() => expect(screen.getByText('Import complete')).toBeInTheDocument())
    expect(excelApi.importPackingList).toHaveBeenCalledWith('c1', 't1/imports/file.xlsx')
    expect(screen.getByText('Customer not found')).toBeInTheDocument()
    expect(screen.getByText('Unknown Corp')).toBeInTheDocument()
  })

  // --- Manifest mode (the forwarder's own export) -------------------------

  const manifestResultStub: ManifestImportResult = {
    total_rows: 81,
    imported: 81,
    errors: 0,
    containers_created: 1,
    customers_created: 68,
    packing_lists_created: 68,
    items_created: 81,
    items_skipped_duplicate: 0,
    error_details: [],
  }

  it('defaults to manifest mode and asks for no container', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({ data: [containerStub] } as never)
    renderPage()

    expect(screen.getByRole('radio', { name: /Forwarder manifest/ })).toHaveAttribute('aria-checked', 'true')
    // The container is read from the file's PARTIAL NO heading, so the picker
    // must not be shown at all in this mode.
    expect(screen.queryByLabelText(/Container/)).not.toBeInTheDocument()
  })

  it('enables Next with only a file chosen (no container needed)', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({ data: [containerStub] } as never)
    renderPage()

    const next = screen.getByRole('button', { name: /Next: Confirm/ })
    expect(next).toBeDisabled()
    await userEvent.upload(screen.getByLabelText('Choose .xlsx file', { selector: 'input' }), makeFile())
    expect(next).toBeEnabled()
  })

  it('imports via the manifest endpoint and reports what was auto-created', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({ data: [containerStub] } as never)
    vi.mocked(uploadImportFile).mockResolvedValue('t1/imports/abc.xlsx')
    vi.mocked(excelApi.importManifest).mockResolvedValue(manifestResultStub)

    renderPage()
    await userEvent.upload(screen.getByLabelText('Choose .xlsx file', { selector: 'input' }), makeFile('STL409.xlsx'))
    await userEvent.click(screen.getByRole('button', { name: /Next: Confirm/ }))
    await userEvent.click(screen.getByRole('button', { name: /Confirm & import/ }))

    await waitFor(() => expect(screen.getByText('Import complete')).toBeInTheDocument())
    // Manifest import must not go through the container-scoped endpoint.
    expect(excelApi.importManifest).toHaveBeenCalledWith('t1/imports/abc.xlsx')
    expect(excelApi.importPackingList).not.toHaveBeenCalled()
    // Several tiles can share a number, so read each by its own label.
    expect(statValue('Customers')).toBe('68')
    expect(statValue('Items added')).toBe('81')
    expect(statValue('Containers')).toBe('1')
  })

  it('explains a fully-duplicate re-import instead of looking like a failure', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({ data: [containerStub] } as never)
    vi.mocked(uploadImportFile).mockResolvedValue('t1/imports/abc.xlsx')
    vi.mocked(excelApi.importManifest).mockResolvedValue({
      ...manifestResultStub,
      imported: 0,
      containers_created: 0,
      customers_created: 0,
      packing_lists_created: 0,
      items_created: 0,
      items_skipped_duplicate: 81,
    })

    renderPage()
    await userEvent.upload(screen.getByLabelText('Choose .xlsx file', { selector: 'input' }), makeFile())
    await userEvent.click(screen.getByRole('button', { name: /Next: Confirm/ }))
    await userEvent.click(screen.getByRole('button', { name: /Confirm & import/ }))

    await waitFor(() => expect(screen.getByText('Nothing new to add')).toBeInTheDocument())
  })

  it('shows the source sheet on skipped manifest rows', async () => {
    vi.mocked(containersApi.list).mockResolvedValue({ data: [containerStub] } as never)
    vi.mocked(uploadImportFile).mockResolvedValue('t1/imports/abc.xlsx')
    vi.mocked(excelApi.importManifest).mockResolvedValue({
      ...manifestResultStub,
      errors: 1,
      error_details: [
        { row: 12, field: 'Name', value: '', error: 'Customer name is required', sheet: 'Master-BALES' },
      ],
    })

    renderPage()
    await userEvent.upload(screen.getByLabelText('Choose .xlsx file', { selector: 'input' }), makeFile())
    await userEvent.click(screen.getByRole('button', { name: /Next: Confirm/ }))
    await userEvent.click(screen.getByRole('button', { name: /Confirm & import/ }))

    await waitFor(() => expect(screen.getByText('Skipped rows')).toBeInTheDocument())
    // Real exports span several sheets, so the row number alone is ambiguous.
    expect(screen.getByText('Master-BALES')).toBeInTheDocument()
  })
})
