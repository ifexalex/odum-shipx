import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { warehousesApi, type Warehouse } from '../../api/warehouses'
import { TopBarTestWrapper } from '../../test/TopBarTestWrapper'
import { Warehouses } from './Warehouses'

vi.mock('../../api/warehouses', () => ({
  warehousesApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    setDefault: vi.fn(),
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
  phone: null,
  is_default: false,
}

function renderPage() {
  return render(
    <MemoryRouter>
      <TopBarTestWrapper>
        <Warehouses />
      </TopBarTestWrapper>
    </MemoryRouter>,
  )
}

describe('Warehouses', () => {
  beforeEach(() => {
    vi.mocked(warehousesApi.list).mockReset()
    vi.mocked(warehousesApi.create).mockReset()
    vi.mocked(warehousesApi.update).mockReset()
    vi.mocked(warehousesApi.setDefault).mockReset()
    vi.mocked(warehousesApi.deactivate).mockReset()
    vi.mocked(warehousesApi.list).mockResolvedValue([DEFAULT_WH, OTHER_WH])
  })

  it('lists warehouses with a Default badge on the default', async () => {
    renderPage()
    expect(await screen.findByText('Lagos — Trade Fair')).toBeInTheDocument()
    expect(screen.getByText('Aba — Ariaria')).toBeInTheDocument()
    expect(screen.getByText('Default')).toBeInTheDocument()
  })

  it('offers Set default and Remove only on non-default warehouses', async () => {
    renderPage()
    await screen.findByText('Aba — Ariaria')
    // Only the one non-default row exposes these actions.
    expect(screen.getAllByRole('button', { name: 'Set default' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Remove' })).toHaveLength(1)
    const defaultRow = screen.getByText('Lagos — Trade Fair').closest('tr')!
    expect(within(defaultRow).queryByRole('button', { name: 'Remove' })).toBeNull()
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
        expect.objectContaining({ phone: '09098765432' }),
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

  it('deactivates a non-default warehouse', async () => {
    vi.mocked(warehousesApi.deactivate).mockResolvedValue({ ...OTHER_WH, is_active: false })
    renderPage()
    await screen.findByText('Aba — Ariaria')
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(warehousesApi.deactivate).toHaveBeenCalledWith('wh2'))
  })
})
