/**
 * Public shipping-company onboarding (lead) form — distinct from customer
 * sign-up: no password, no account, a plain POST /v1/onboarding-requests.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { companyOnboardingApi } from '../../api/customer'
import { RequestOnboardingScreen } from './RequestOnboardingScreen'

vi.mock('../../api/customer', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/customer')>()
  return { ...original, companyOnboardingApi: { ...original.companyOnboardingApi, requestOnboarding: vi.fn() } }
})

function renderScreen() {
  return render(
    <MemoryRouter initialEntries={['/get-started']}>
      <Routes>
        <Route path="/" element={<div>Landing page</div>} />
        <Route path="/get-started" element={<RequestOnboardingScreen />} />
        <Route path="/login" element={<div>Login page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RequestOnboardingScreen', () => {
  beforeEach(() => vi.clearAllMocks())

  it('collects no password and frames this as a demo request, not an account', () => {
    renderScreen()
    expect(screen.getByRole('heading', { level: 1, name: 'Book a demo' })).toBeInTheDocument()
    expect(screen.queryByLabelText(/password/i)).toBeNull()
    expect(screen.getByText('Are you a customer?')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /back to home/i })).toHaveAttribute('href', '/')
  })

  it('submits the lead, shows the no-account-created confirmation, and links back to home', async () => {
    vi.mocked(companyOnboardingApi.requestOnboarding).mockResolvedValue({ id: 'req-1', status: 'new' })
    renderScreen()

    await userEvent.type(screen.getByLabelText('Company name', { exact: false, selector: 'input' }), 'Acme Freight Ltd')
    await userEvent.type(screen.getByLabelText('Your name', { exact: false, selector: 'input' }), 'Ada Obi')
    await userEvent.type(screen.getByLabelText('Work email', { exact: false, selector: 'input' }), 'ada@acme.com')
    await userEvent.click(screen.getByRole('button', { name: /book a demo/i }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Demo request received.' })).toBeInTheDocument()
    expect(screen.getByText(/No account has been created yet/i)).toBeInTheDocument()
    expect(companyOnboardingApi.requestOnboarding).toHaveBeenCalledWith(
      expect.objectContaining({
        company_name: 'Acme Freight Ltd',
        contact_name: 'Ada Obi',
        contact_email: 'ada@acme.com',
        origin_country: 'China',
        destination_country: 'Nigeria',
      }),
    )

    await userEvent.click(screen.getByRole('button', { name: /back to home/i }))
    expect(await screen.findByText('Landing page')).toBeInTheDocument()
  })
})
