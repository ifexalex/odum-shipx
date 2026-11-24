import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { configApi } from '../../api/tenantManagement'
import { withQuery } from '../../test/queryWrapper'
import { CustomerSignupLink } from './CustomerSignupLink'

function renderLink() {
  return render(withQuery(<CustomerSignupLink />))
}

vi.mock('../../api/tenantManagement', () => ({
  configApi: { getRegistrationLink: vi.fn(), setRegistrationLinkEnabled: vi.fn() },
}))

describe('CustomerSignupLink', () => {
  beforeEach(() => {
    vi.mocked(configApi.getRegistrationLink).mockReset()
    vi.mocked(configApi.setRegistrationLinkEnabled).mockReset()
    vi.mocked(configApi.getRegistrationLink).mockResolvedValue({
      enabled: true,
      slug: 'acme-shipping',
      updated_at: null,
    })
  })

  it('builds the link from the slug and the current origin', async () => {
    // Built from window.location rather than a configured host: this is the
    // address a customer will visit, and a hardcoded one would hand out a link
    // to the wrong environment the moment either moved.
    renderLink()

    expect(await screen.findByTestId('signup-url')).toHaveTextContent(
      `${window.location.origin}/register/acme-shipping`,
    )
  })

  it('says the link is active, and that invites still work', async () => {
    renderLink()

    expect(await screen.findByText('Active')).toBeInTheDocument()
    expect(screen.getByText(/inviting individual customers still works/i)).toBeInTheDocument()
  })

  it('shows a QR only when asked, so the card stays compact', async () => {
    renderLink()
    await screen.findByTestId('signup-url')

    // Asserted through the download affordance rather than by looking for an
    // <svg>: the card already contains icon SVGs, so a bare svg query passes
    // before the QR exists and proves nothing.
    expect(screen.queryByRole('button', { name: /download svg/i })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /show qr/i }))

    expect(await screen.findByRole('button', { name: /download svg/i })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: /hide qr/i })).toBeInTheDocument())
  })

  it('turns the link off through the API and reflects the new state', async () => {
    vi.mocked(configApi.setRegistrationLinkEnabled).mockResolvedValue({
      enabled: false,
      slug: 'acme-shipping',
      updated_at: null,
    })
    renderLink()
    await screen.findByTestId('signup-url')

    await userEvent.click(screen.getByRole('button', { name: /turn off/i }))

    await waitFor(() => expect(configApi.setRegistrationLinkEnabled).toHaveBeenCalledWith(false))
    expect(await screen.findByText('Off')).toBeInTheDocument()
  })

  it('warns that a disabled link turns visitors away, and says what is unaffected', async () => {
    vi.mocked(configApi.getRegistrationLink).mockResolvedValue({
      enabled: false,
      slug: 'acme-shipping',
      updated_at: null,
    })
    renderLink()

    expect(await screen.findByText(/not accepting new registrations/i)).toBeInTheDocument()
    expect(screen.getByText(/existing customers and invites are unaffected/i)).toBeInTheDocument()
  })

  it('explains itself rather than showing a broken link when there is no slug', async () => {
    vi.mocked(configApi.getRegistrationLink).mockResolvedValue({
      enabled: true,
      slug: null,
      updated_at: null,
    })
    renderLink()

    expect(await screen.findByText(/no URL slug yet/i)).toBeInTheDocument()
    expect(screen.queryByTestId('signup-url')).not.toBeInTheDocument()
  })
})
