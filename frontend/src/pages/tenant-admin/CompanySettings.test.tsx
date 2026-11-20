/**
 * 4.1 — Company Settings (audit gap A1): branding form hydrates from
 * GET /v1/tenant/config, saves via PUT {branding}, drives the live document
 * preview, and the config sub-nav preserves the old hub's navigation.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { configApi } from '../../api/tenantManagement'
import { CompanySettings } from './CompanySettings'
import { ConfigLayout } from './ConfigLayout'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    configApi: { ...original.configApi, getConfig: vi.fn(), updateConfig: vi.fn() },
  }
})

const BRANDING = {
  display_name: 'Acme Logistics Ltd',
  tagline: 'Trusted China-Nigeria cargo since 2019',
  primary_color: '#0a6ed1',
  warehouse_address: '12 Wharf Road, Apapa\nLagos',
  pickup_hours: 'Mon–Sat · 8:00 AM – 5:00 PM',
  pickup_phone: '+234 1 234 5678',
  support_email: 'support@acmelogistics.com',
  support_whatsapp: '+234 802 415 0922',
  document_footer: 'This document is an official record issued by Acme Logistics Ltd.',
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // Mirror routes.tsx: config screens render inside ConfigLayout's persistent
  // sub-nav rail, and section switches are route changes.
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/admin/config']}>
        <Routes>
          <Route path="/admin/config" element={<ConfigLayout><CompanySettings /></ConfigLayout>} />
          <Route path="/admin/config/dollar-rate" element={<ConfigLayout><div>Dollar rate page</div></ConfigLayout>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('CompanySettings (4.1)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(configApi.getConfig).mockResolvedValue({ webhook_config: null, branding_config: BRANDING })
    // Echo the saved branding back, like the real PUT does.
    vi.mocked(configApi.updateConfig).mockImplementation(async (body) => ({
      webhook_config: null,
      branding_config: body.branding ?? BRANDING,
    }))
  })

  it('hydrates the form from branding_config', async () => {
    renderPage()
    expect(await screen.findByDisplayValue('Acme Logistics Ltd')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Trusted China-Nigeria cargo since 2019')).toBeInTheDocument()
    expect(screen.getByDisplayValue('support@acmelogistics.com')).toBeInTheDocument()
  })

  it('live preview mirrors the company name and footer as typed', async () => {
    renderPage()
    const nameField = await screen.findByDisplayValue('Acme Logistics Ltd')

    await userEvent.clear(nameField)
    await userEvent.type(nameField, 'Kola Cargo Hub')

    const preview = screen.getByTestId('doc-preview')
    expect(preview).toHaveTextContent('Kola Cargo Hub')
    expect(preview).toHaveTextContent('KC') // initials tile
    expect(preview).toHaveTextContent('official record issued by Acme Logistics Ltd')
  })

  it('saves only non-empty fields via PUT {branding} and shows confirmation', async () => {
    renderPage()
    const nameField = await screen.findByDisplayValue('Acme Logistics Ltd')

    await userEvent.clear(nameField)
    await userEvent.type(nameField, 'Kola Cargo Hub')
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(configApi.updateConfig).toHaveBeenCalledWith({
        branding: expect.objectContaining({ display_name: 'Kola Cargo Hub', tagline: BRANDING.tagline }),
      })
    })
    expect(await screen.findByText('Company settings saved')).toBeInTheDocument()
  })

  it('save stays disabled until the form is dirty, and rejects a bad hex colour', async () => {
    renderPage()
    await screen.findByDisplayValue('Acme Logistics Ltd')
    const saveBtn = screen.getByRole('button', { name: /save changes/i })
    expect(saveBtn).toBeDisabled()

    const colorField = screen.getByRole('textbox', { name: 'Brand colour' })
    await userEvent.clear(colorField)
    await userEvent.type(colorField, 'not-a-colour')

    expect(screen.getByText(/use a hex colour/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled()
  })

  it('config sub-nav navigates to the other config pages (hub function preserved)', async () => {
    renderPage()
    await screen.findByDisplayValue('Acme Logistics Ltd')

    await userEvent.click(screen.getByText('Dollar rate'))
    expect(await screen.findByText('Dollar rate page')).toBeInTheDocument()
  })

  it('release-note preview shows the warehouse address', async () => {
    renderPage()
    await screen.findByDisplayValue('Acme Logistics Ltd')

    await userEvent.click(screen.getByRole('tab', { name: /release note/i }))
    expect(screen.getByTestId('doc-preview')).toHaveTextContent('12 Wharf Road, Apapa')
  })
})
