import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { withQuery } from '../../test/queryWrapper'
import { containerCapacitiesApi, type ContainerCapacity } from '../../api/tenantManagement'
import { TopBarTestWrapper } from '../../test/TopBarTestWrapper'
import { ContainerCapacities } from './ContainerCapacities'

vi.mock('../../api/tenantManagement', () => ({
  containerCapacitiesApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}))

const DEFAULT_ROW: ContainerCapacity = {
  id: "default:40' High Cube (HC)",
  name: "40' High Cube (HC)",
  capacity_cbm: 76,
  recommended_cbm: 70,
  is_custom: false,
}
const CUSTOM_ROW: ContainerCapacity = {
  id: 'cap-1',
  name: "53' Megabox",
  capacity_cbm: 95,
  recommended_cbm: 88,
  is_custom: true,
}

function renderPage() {
  return render(
    withQuery(
      <MemoryRouter>
        <TopBarTestWrapper>
          <ContainerCapacities />
        </TopBarTestWrapper>
      </MemoryRouter>,
    ),
  )
}

describe('ContainerCapacities', () => {
  beforeEach(() => {
    vi.mocked(containerCapacitiesApi.list).mockReset()
    vi.mocked(containerCapacitiesApi.create).mockReset()
    vi.mocked(containerCapacitiesApi.update).mockReset()
    vi.mocked(containerCapacitiesApi.remove).mockReset()
    vi.mocked(containerCapacitiesApi.list).mockResolvedValue([CUSTOM_ROW, DEFAULT_ROW])
  })

  it('lists default and custom presets with a source badge', async () => {
    renderPage()
    expect(await screen.findByText("53' Megabox")).toBeInTheDocument()
    expect(screen.getByText("40' High Cube (HC)")).toBeInTheDocument()
    expect(screen.getByText('Custom')).toBeInTheDocument()
    expect(screen.getByText('Default')).toBeInTheDocument()
  })

  it('only offers Remove on custom presets', async () => {
    renderPage()
    await screen.findByText("53' Megabox")
    // One custom row → exactly one Remove button.
    expect(screen.getAllByRole('button', { name: 'Remove' })).toHaveLength(1)
  })

  it('creates a custom capacity', async () => {
    vi.mocked(containerCapacitiesApi.create).mockResolvedValue(CUSTOM_ROW)
    renderPage()
    await screen.findByText("53' Megabox")
    await userEvent.click(screen.getByRole('button', { name: /add capacity/i }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/^Name/, { selector: 'input' }), "53' Megabox")
    await userEvent.type(within(dialog).getByLabelText(/Usable capacity/, { selector: 'input' }), '95')
    await userEvent.type(within(dialog).getByLabelText(/Recommended load/, { selector: 'input' }), '88')
    await userEvent.click(within(dialog).getByRole('button', { name: /add capacity/i }))
    await waitFor(() =>
      expect(containerCapacitiesApi.create).toHaveBeenCalledWith({
        name: "53' Megabox",
        capacity_cbm: 95,
        recommended_cbm: 88,
      }),
    )
  })

  it("edits a default's recommended CBM with name + capacity locked", async () => {
    vi.mocked(containerCapacitiesApi.update).mockResolvedValue({ ...DEFAULT_ROW, recommended_cbm: 72 })
    renderPage()
    await screen.findByText("40' High Cube (HC)")
    // The default row's Edit button (second row's Edit).
    const defaultRow = screen.getByText("40' High Cube (HC)").closest('tr')!
    await userEvent.click(within(defaultRow).getByRole('button', { name: 'Edit' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByLabelText(/^Name/, { selector: 'input' })).toBeDisabled()
    expect(within(dialog).getByLabelText(/Usable capacity/, { selector: 'input' })).toBeDisabled()
    const rec = within(dialog).getByLabelText(/Recommended load/, { selector: 'input' })
    await userEvent.clear(rec)
    await userEvent.type(rec, '72')
    await userEvent.click(within(dialog).getByRole('button', { name: /save changes/i }))
    await waitFor(() =>
      expect(containerCapacitiesApi.update).toHaveBeenCalledWith("default:40' High Cube (HC)", {
        recommended_cbm: 72,
      }),
    )
  })

  it('edits all fields of a custom preset', async () => {
    vi.mocked(containerCapacitiesApi.update).mockResolvedValue({ ...CUSTOM_ROW, recommended_cbm: 90 })
    renderPage()
    await screen.findByText("53' Megabox")
    const customRow = screen.getByText("53' Megabox").closest('tr')!
    await userEvent.click(within(customRow).getByRole('button', { name: 'Edit' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByLabelText(/^Name/, { selector: 'input' })).toBeEnabled()
    const rec = within(dialog).getByLabelText(/Recommended load/, { selector: 'input' })
    await userEvent.clear(rec)
    await userEvent.type(rec, '90')
    await userEvent.click(within(dialog).getByRole('button', { name: /save changes/i }))
    await waitFor(() =>
      expect(containerCapacitiesApi.update).toHaveBeenCalledWith('cap-1', {
        recommended_cbm: 90,
        name: "53' Megabox",
        capacity_cbm: 95,
      }),
    )
  })

  it('blocks submit when recommended load exceeds capacity', async () => {
    renderPage()
    await screen.findByText("53' Megabox")
    await userEvent.click(screen.getByRole('button', { name: /add capacity/i }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/^Name/, { selector: 'input' }), 'Bad')
    await userEvent.type(within(dialog).getByLabelText(/Usable capacity/, { selector: 'input' }), '30')
    await userEvent.type(within(dialog).getByLabelText(/Recommended load/, { selector: 'input' }), '50')
    expect(within(dialog).getByRole('button', { name: /add capacity/i })).toBeDisabled()
    expect(within(dialog).getByText(/cannot exceed capacity/i)).toBeInTheDocument()
  })
})
