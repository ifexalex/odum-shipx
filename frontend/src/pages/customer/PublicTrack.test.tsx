import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { publicTrackingApi, type PublicTrackingResult } from '../../api/customer'
import { PublicTrack } from './PublicTrack'

const RESULT: PublicTrackingResult = {
  tracking_code: 'ACME-TRK-20260704-0001',
  current_stage: 'in_transit',
  company_name: 'Acme Cargo',
  brand_color: '#1d4ed8',
  stage_history: [
    { stage: 'packing', occurred_at: '2026-07-04T10:00:00Z', notes: null },
    { stage: 'in_transit', occurred_at: '2026-07-20T10:00:00Z', notes: 'Departed Guangzhou' },
  ],
  estimated_stages: null,
}

function renderPage(path = '/track') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/track" element={<PublicTrack />} />
        <Route path="/track/:code" element={<PublicTrack />} />
      </Routes>
    </MemoryRouter>,
  )
}

async function track(): Promise<void> {
  await userEvent.type(screen.getByLabelText(/^Phone number/, { selector: 'input' }), '08012345678')
  await userEvent.click(screen.getByRole('button', { name: 'Track shipment' }))
}

describe('PublicTrack (FD-28)', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('has a ShipX brand header and a footer before anything is looked up', () => {
    renderPage()
    expect(screen.getByRole('banner')).toContainElement(screen.getByRole('link', { name: 'ShipX home' }))
    expect(screen.getByRole('contentinfo')).toHaveTextContent('ShipX')
    expect(screen.getByRole('heading', { level: 1, name: 'Track your shipment' })).toBeInTheDocument()
  })

  it("shows the shipping company's name and colour once the lookup succeeds", async () => {
    vi.spyOn(publicTrackingApi, 'lookup').mockResolvedValue(RESULT)
    const { container } = renderPage('/track/ACME-TRK-20260704-0001')
    await track()
    expect(await screen.findByRole('heading', { name: 'In transit' })).toBeInTheDocument()
    expect(screen.getByRole('banner')).toHaveTextContent('Acme Cargo')
    expect(screen.getByRole('contentinfo')).toHaveTextContent('Tracking for Acme Cargo, powered by ShipX')
    const themed = container.querySelector<HTMLElement>('[data-tenant-theme]')
    expect(themed?.style.getPropertyValue('--color-primary')).toBe('#1d4ed8')
  })

  it('keeps ShipX colours when the company has none', async () => {
    vi.spyOn(publicTrackingApi, 'lookup').mockResolvedValue({ ...RESULT, brand_color: null })
    const { container } = renderPage('/track/ACME-TRK-20260704-0001')
    await track()
    await screen.findByRole('heading', { name: 'In transit' })
    expect(container.querySelector<HTMLElement>('[data-tenant-theme]')?.style.getPropertyValue('--color-primary')).toBe('')
  })

  it('shows progress on the shared stepper, the latest update and a sign-in link', async () => {
    vi.spyOn(publicTrackingApi, 'lookup').mockResolvedValue(RESULT)
    renderPage('/track/ACME-TRK-20260704-0001')
    await track()
    expect(await screen.findByRole('list', { name: 'Shipment progress' })).toBeInTheDocument()
    expect(screen.getByText(/Departed Guangzhou/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sign in for full details' })).toHaveAttribute(
      'href',
      '/login?next=%2Fmy-shipments',
    )
  })

  it('submits with Enter', async () => {
    const lookup = vi.spyOn(publicTrackingApi, 'lookup').mockResolvedValue(RESULT)
    renderPage('/track/ACME-TRK-20260704-0001')
    await userEvent.type(screen.getByLabelText(/^Phone number/, { selector: 'input' }), '08012345678{Enter}')
    expect(lookup).toHaveBeenCalledWith('ACME-TRK-20260704-0001', expect.any(String))
  })
})
