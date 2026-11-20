import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { withQuery } from '../../test/queryWrapper'
import { ApiError } from '../../api/client'
import { warehousesApi, type Warehouse } from '../../api/warehouses'
import { TopBarTestWrapper } from '../../test/TopBarTestWrapper'
import { Warehouses } from './Warehouses'

vi.mock('../../api/warehouses', () => ({
  warehousesApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    setDefault: vi.fn(),
    remove: vi.fn(),
    deactivate: vi.fn(),
  },
}))

const DEFAULT_WH: Warehouse = {
  id: 'wh1',
  name: 'Lagos — Trade Fair',
  address: null,
  city: 'Lagos',
  state: 'Lagos',
  phone: '08012345678',
  is_default: true,
}
const OTHER_WH: Warehouse = {
  id: 'wh2',
  name: 'Aba — Ariaria',
  address: null,
  city: 'Aba',
  state: 'Abia',
  country: 'Nigeria',
  phone: null,
  is_default: false,
}

function renderPage() {
  return render(
    withQuery(
      <MemoryRouter>
        <TopBarTestWrapper>
          <Warehouses />
        </TopBarTestWrapper>
      </MemoryRouter>,
    ),
  )
}

describe('Warehouses', () => {
  beforeEach(() => {
    vi.mocked(warehousesApi.list).mockReset()
    vi.mocked(warehousesApi.create).mockReset()
    vi.mocked(warehousesApi.update).mockReset()
    vi.mocked(warehousesApi.setDefault).mockReset()
    vi.mocked(warehousesApi.remove).mockReset()
    vi.mocked(warehousesApi.deactivate).mockReset()
    vi.mocked(warehousesApi.list).mockResolvedValue([DEFAULT_WH, OTHER_WH])
  })

  it('lists warehouses with a Default badge on the default', async () => {
    renderPage()
    expect(await screen.findByText('Lagos — Trade Fair')).toBeInTheDocument()
    expect(screen.getByText('Aba — Ariaria')).toBeInTheDocument()
    expect(screen.getByText('Default')).toBeInTheDocument()
  })

  it('offers Set default and Delete only on non-default warehouses', async () => {
    renderPage()
    await screen.findByText('Aba — Ariaria')
    // Only the one non-default row exposes these actions.
    expect(screen.getAllByRole('button', { name: 'Set default' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Delete' })).toHaveLength(1)
    const defaultRow = screen.getByText('Lagos — Trade Fair').closest('tr')!
    expect(within(defaultRow).queryByRole('button', { name: 'Delete' })).toBeNull()
    expect(within(defaultRow).queryByRole('button', { name: 'Set default' })).toBeNull()
  })

  it('creates a warehouse', async () => {
    vi.mocked(warehousesApi.create).mockResolvedValue({ ...OTHER_WH, id: 'wh3', name: 'Kano — Sabon Gari' })
    renderPage()
    await screen.findByText('Lagos — Trade Fair')
    await userEvent.click(screen.getByRole('button', { name: /add warehouse/i }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/^Name/, { selector: 'input' }), 'Kano — Sabon Gari')
    await userEvent.type(within(dialog).getByLabelText(/^City/, { selector: 'input' }), 'Kano')
    await userEvent.click(within(dialog).getByRole('button', { name: /add warehouse/i }))
    await waitFor(() =>
      expect(warehousesApi.create).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Kano — Sabon Gari', city: 'Kano' }),
      ),
    )
  })

  it('edits a warehouse', async () => {
    vi.mocked(warehousesApi.update).mockResolvedValue({ ...OTHER_WH, phone: '09098765432' })
    renderPage()
    await screen.findByText('Aba — Ariaria')
    const row = screen.getByText('Aba — Ariaria').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: 'Edit' }))
    const dialog = screen.getByRole('dialog')
    const phone = within(dialog).getByLabelText(/^Phone/, { selector: 'input' })
    await userEvent.clear(phone)
    await userEvent.type(phone, '09098765432')
    await userEvent.click(within(dialog).getByRole('button', { name: /save changes/i }))
    await waitFor(() =>
      expect(warehousesApi.update).toHaveBeenCalledWith(
        'wh2',
        // Submitted as E.164, not as typed: PhoneField assembles the dial code
        // so the stored value matches what the database holds. The trunk 0 the
        // user typed is dropped, not doubled onto the +234.
        expect.objectContaining({ phone: '+2349098765432' }),
      ),
    )
  })

  it('submits the warehouse country and state chosen from the pickers', async () => {
    vi.mocked(warehousesApi.update).mockResolvedValue(OTHER_WH)
    renderPage()
    await screen.findByText('Aba — Ariaria')
    const row = screen.getByText('Aba — Ariaria').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: 'Edit' }))
    const dialog = screen.getByRole('dialog')
    // The stored country/state round-trip through the pickers untouched.
    await userEvent.click(within(dialog).getByRole('button', { name: /save changes/i }))
    await waitFor(() =>
      expect(warehousesApi.update).toHaveBeenCalledWith(
        'wh2',
        expect.objectContaining({ country: 'Nigeria', state: 'Abia' }),
      ),
    )
  })

  it('clears the state when the country changes', async () => {
    // A state belongs to one country's list, so keeping "Abia" after switching
    // to China would submit a mismatched pair the picker cannot even display.
    vi.mocked(warehousesApi.update).mockResolvedValue(OTHER_WH)
    renderPage()
    await screen.findByText('Aba — Ariaria')
    const row = screen.getByText('Aba — Ariaria').closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: 'Edit' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByLabelText('Country'))
    await userEvent.click(await screen.findByText('China'))
    await userEvent.click(within(dialog).getByRole('button', { name: /save changes/i }))
    await waitFor(() =>
      expect(warehousesApi.update).toHaveBeenCalledWith(
        'wh2',
        expect.objectContaining({ country: 'China', state: undefined }),
      ),
    )
  })

  it('sets a non-default warehouse as default', async () => {
    vi.mocked(warehousesApi.setDefault).mockResolvedValue({ ...OTHER_WH, is_default: true })
    renderPage()
    await screen.findByText('Aba — Ariaria')
    await userEvent.click(screen.getByRole('button', { name: 'Set default' }))
    await waitFor(() => expect(warehousesApi.setDefault).toHaveBeenCalledWith('wh2'))
  })

  // ── Reported live, 2026-11-02 ──────────────────────────────────────────────
  // "When I delete a warehouse it should be deleted completely, not soft
  // deleted" — and separately, clicking Set default appeared to do nothing.

  it('really deletes a non-default warehouse, after confirming in the dialog', async () => {
    vi.mocked(warehousesApi.remove).mockResolvedValue({ ...OTHER_WH, is_active: false })
    renderPage()
    await screen.findByText('Aba — Ariaria')
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    // Nothing happens until the dialog is confirmed.
    const dialog = await screen.findByRole('dialog', { name: 'Delete this warehouse?' })
    expect(warehousesApi.remove).not.toHaveBeenCalled()
    expect(within(dialog).getByText('Aba — Ariaria')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete warehouse' }))
    await waitFor(() => expect(warehousesApi.remove).toHaveBeenCalledWith('wh2'))
    // A real delete, not a flag flip.
    expect(warehousesApi.deactivate).not.toHaveBeenCalled()
    await screen.findByText('Aba — Ariaria was deleted.')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('refreshes the list after a delete', async () => {
    // The list is cached for five minutes; a delete that skipped the cache left the row on screen.
    vi.mocked(warehousesApi.remove).mockResolvedValue({ ...OTHER_WH, is_active: false })
    renderPage()
    await screen.findByText('Aba — Ariaria')
    vi.mocked(warehousesApi.list).mockResolvedValue([DEFAULT_WH])
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete warehouse' }))
    await waitFor(() => expect(screen.queryByRole('cell', { name: 'Aba — Ariaria' })).not.toBeInTheDocument())
    expect(warehousesApi.list).toHaveBeenCalledTimes(2)
  })

  it('does not delete when the dialog is cancelled', async () => {
    renderPage()
    await screen.findByText('Aba — Ariaria')
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(warehousesApi.remove).not.toHaveBeenCalled()
  })

  it('does not delete when the dialog is dismissed with Escape', async () => {
    renderPage()
    await screen.findByText('Aba — Ariaria')
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await screen.findByRole('dialog')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(warehousesApi.remove).not.toHaveBeenCalled()
  })

  it('offers to retire instead when the warehouse is referenced', async () => {
    // The backend refuses with rule_id WAREHOUSE_IN_USE rather than orphaning a
    // release note; the page must offer the retire path instead of dead-ending.
    vi.mocked(warehousesApi.remove).mockRejectedValue(
      new ApiError(
        {
          type: 'about:blank',
          title: 'Business Rule Violation',
          status: 422,
          detail: 'This warehouse is referenced by 2 release notes',
          error_code: 'BUSINESS_RULE_VIOLATION',
          rule_id: 'WAREHOUSE_IN_USE',
        },
        null,
      ),
    )
    vi.mocked(warehousesApi.deactivate).mockResolvedValue({ ...OTHER_WH, is_active: false })
    renderPage()
    await screen.findByText('Aba — Ariaria')
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete warehouse' }))
    // The same dialog now explains why, with the server's reason, and offers to retire.
    const dialog = await screen.findByRole('dialog', { name: 'Retire this warehouse instead?' })
    expect(within(dialog).getByText('This warehouse is referenced by 2 release notes')).toBeInTheDocument()
    expect(warehousesApi.deactivate).not.toHaveBeenCalled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Retire warehouse' }))
    await waitFor(() => expect(warehousesApi.deactivate).toHaveBeenCalledWith('wh2'))
    await screen.findByText(/was retired/)
  })

  it('keeps the warehouse when retiring is declined', async () => {
    vi.mocked(warehousesApi.remove).mockRejectedValue(
      new ApiError(
        {
          type: 'about:blank',
          title: 'Business Rule Violation',
          status: 422,
          detail: 'This warehouse is referenced by 2 release notes',
          error_code: 'BUSINESS_RULE_VIOLATION',
          rule_id: 'WAREHOUSE_IN_USE',
        },
        null,
      ),
    )
    renderPage()
    await screen.findByText('Aba — Ariaria')
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete warehouse' }))
    const dialog = await screen.findByRole('dialog', { name: 'Retire this warehouse instead?' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(warehousesApi.deactivate).not.toHaveBeenCalled()
  })

  it('confirms in the UI that the default moved', async () => {
    // Previously the only signal was a badge changing further down the page,
    // which read as "nothing happened".
    vi.mocked(warehousesApi.setDefault).mockResolvedValue({ ...OTHER_WH, is_default: true })
    renderPage()
    await screen.findByText('Aba — Ariaria')
    await userEvent.click(screen.getByRole('button', { name: 'Set default' }))
    await screen.findByText(/is now the default warehouse/i)
  })

  it('surfaces a set-default failure instead of failing silently', async () => {
    vi.mocked(warehousesApi.setDefault).mockRejectedValue(
      new ApiError(
        {
          type: 'about:blank',
          title: 'Server Error',
          status: 500,
          detail: 'Internal server error',
          error_code: 'INTERNAL_ERROR',
        },
        null,
      ),
    )
    renderPage()
    await screen.findByText('Aba — Ariaria')
    await userEvent.click(screen.getByRole('button', { name: 'Set default' }))
    await screen.findByText('Something went wrong on our side. Try again; if it keeps happening, contact support.')
  })

  it('can create a warehouse already marked as the default', async () => {
    vi.mocked(warehousesApi.create).mockResolvedValue({ ...OTHER_WH, id: 'wh3', name: 'Kano' })
    renderPage()
    await screen.findByText('Aba — Ariaria')
    await userEvent.click(screen.getAllByRole('button', { name: /add warehouse/i })[0]!)
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/^Name/), 'Kano')
    await userEvent.click(within(dialog).getByRole('checkbox'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add warehouse' }))
    await waitFor(() =>
      expect(warehousesApi.create).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Kano', is_default: true }),
      ),
    )
  })
})
