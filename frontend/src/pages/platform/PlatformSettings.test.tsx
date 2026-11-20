/**
 * PlatformSettings' three panels read through React Query (audit FE-05). Each used to fetch in an effect and had no
 * tests. These pin what the effects did: fill the form from the server, report a failed read, and show a save at once.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { platformSettingsApi } from '../../api/tenantManagement'
import { withQuery } from '../../test/queryWrapper'
import { PlatformSettings } from './PlatformSettings'

vi.mock('../../api/tenantManagement', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/tenantManagement')>()
  return {
    ...original,
    platformSettingsApi: {
      get: vi.fn(), update: vi.fn(), getGateways: vi.fn(), updateGateway: vi.fn(), testGateway: vi.fn(), getPlans: vi.fn(), updatePlan: vi.fn(),
    },
  }
})

const PLANS = {
  starter: { users: 5, containers_per_month: 10, storage_gb: 5 },
  business: { users: 25, containers_per_month: 50, storage_gb: 50 },
  enterprise: { users: 999999, containers_per_month: 999999, storage_gb: 999999 },
}
const failure = (detail: string) =>
  new ApiError({ type: 'about:blank', title: 'Server Error', status: 500, detail, error_code: 'INTERNAL' }, null)

function renderAt(path: string) {
  return render(withQuery(<MemoryRouter initialEntries={[path]}><PlatformSettings /></MemoryRouter>))
}

beforeEach(() => {
  for (const fn of Object.values(platformSettingsApi)) vi.mocked(fn).mockReset()
})

describe('PlatformSettings — General', () => {
  it('fills the form from the saved settings', async () => {
    vi.mocked(platformSettingsApi.get).mockResolvedValue({ platform_email_from: 'ops@shipx.test', max_tenants: 40, maintenance_mode: false })
    renderAt('/platform/settings')
    expect(await screen.findByDisplayValue('ops@shipx.test')).toBeInTheDocument()
    expect(screen.getByDisplayValue('40')).toBeInTheDocument()
  })

  it('says so when the settings cannot be read', async () => {
    vi.mocked(platformSettingsApi.get).mockRejectedValue(failure('settings store unavailable'))
    renderAt('/platform/settings')
    expect(await screen.findByText('settings store unavailable')).toBeInTheDocument()
    expect(screen.queryByText('Loading settings…')).toBeNull()
  })

  it('saves what was edited and confirms it', async () => {
    vi.mocked(platformSettingsApi.get).mockResolvedValue({ platform_email_from: 'ops@shipx.test', max_tenants: 40, maintenance_mode: false })
    vi.mocked(platformSettingsApi.update).mockResolvedValue({ platform_email_from: 'ops@shipx.test', max_tenants: 60, maintenance_mode: false })
    renderAt('/platform/settings')
    const max = await screen.findByDisplayValue('40')
    await userEvent.clear(max)
    await userEvent.type(max, '60')
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    await waitFor(() =>
      expect(platformSettingsApi.update).toHaveBeenCalledWith({ platform_email_from: 'ops@shipx.test', max_tenants: 60, maintenance_mode: false }),
    )
    expect(await screen.findByText('Platform settings saved')).toBeInTheDocument()
    expect(screen.getByDisplayValue('60')).toBeInTheDocument()
  })

  it('keeps the form and reports a failed save', async () => {
    vi.mocked(platformSettingsApi.get).mockResolvedValue({ platform_email_from: 'ops@shipx.test', max_tenants: 40, maintenance_mode: false })
    vi.mocked(platformSettingsApi.update).mockRejectedValue(failure('max_tenants is below the current tenant count'))
    renderAt('/platform/settings')
    await screen.findByDisplayValue('40')
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    expect(await screen.findByText('max_tenants is below the current tenant count')).toBeInTheDocument()
    expect(screen.getByDisplayValue('ops@shipx.test')).toBeInTheDocument()
  })
})

describe('PlatformSettings — Notification providers', () => {
  it('shows a card per provider with its saved values', async () => {
    vi.mocked(platformSettingsApi.getGateways).mockResolvedValue({ sms: { sender_id: 'ShipX' }, whatsapp: {}, email: {} })
    renderAt('/platform/settings/notifications')
    expect(await screen.findByDisplayValue('ShipX')).toBeInTheDocument()
    expect(platformSettingsApi.getGateways).toHaveBeenCalledTimes(1)
  })

  it('says so when the providers cannot be read', async () => {
    vi.mocked(platformSettingsApi.getGateways).mockRejectedValue(failure('gateway config unavailable'))
    renderAt('/platform/settings/notifications')
    expect(await screen.findByText('gateway config unavailable')).toBeInTheDocument()
  })
})

describe('PlatformSettings — Plans & limits', () => {
  it('shows each tier with its limits', async () => {
    vi.mocked(platformSettingsApi.getPlans).mockResolvedValue({ plans: PLANS })
    renderAt('/platform/settings/plans')
    expect(await screen.findByRole('button', { name: 'Save starter limits' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save business limits' })).toBeInTheDocument()
    expect(screen.getByDisplayValue('25')).toBeInTheDocument()
  })

  it('says so when the plans cannot be read', async () => {
    vi.mocked(platformSettingsApi.getPlans).mockRejectedValue(failure('plans unavailable'))
    renderAt('/platform/settings/plans')
    expect(await screen.findByText('plans unavailable')).toBeInTheDocument()
  })

  it('saves a tier and keeps the page showing the plans', async () => {
    vi.mocked(platformSettingsApi.getPlans).mockResolvedValue({ plans: PLANS })
    vi.mocked(platformSettingsApi.updatePlan).mockResolvedValue({ plans: { ...PLANS, starter: { ...PLANS.starter, users: 8 } } })
    renderAt('/platform/settings/plans')
    await userEvent.click(await screen.findByRole('button', { name: 'Save starter limits' }))
    await waitFor(() => expect(platformSettingsApi.updatePlan).toHaveBeenCalledWith('starter', { users: 5, containers_per_month: 10, storage_gb: 5 }))
    expect(screen.getByRole('button', { name: 'Save enterprise limits' })).toBeInTheDocument()
  })
})
