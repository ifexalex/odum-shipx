/**
 * Bare `/register` (no company slug) must NOT dead-end — it routes the two
 * audiences apart: customers use their company link/invite; shipping companies
 * go to `/get-started`. A slugged `/register/:slug` is the real customer form.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { registerApi } from '../../api/customer'
import { RegisterScreen } from './RegisterScreen'

vi.mock('../../api/customer', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/customer')>()
  return { ...original, registerApi: { ...original.registerApi, selfRegister: vi.fn() } }
})

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/register" element={<RegisterScreen />} />
        <Route path="/register/:slug" element={<RegisterScreen />} />
        <Route path="/get-started" element={<div>Get started page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RegisterScreen', () => {
  it('shows the which-are-you chooser on bare /register and routes companies to /get-started', async () => {
    renderAt('/register')
    expect(screen.getByText('Which are you?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /get started here/i }))
    expect(await screen.findByText('Get started page')).toBeInTheDocument()
  })

  it('renders the customer account form (no chooser) on /register/:slug', () => {
    renderAt('/register/acme')
    expect(screen.getByText('Create your customer account')).toBeInTheDocument()
    expect(screen.queryByText('Which are you?')).toBeNull()
    expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument()
  })

  describe('submitting the form', () => {
    async function fillAndSubmit(): Promise<void> {
      await userEvent.type(screen.getByLabelText(/full name/i), 'Ngozi Okonkwo')
      await userEvent.type(screen.getByLabelText(/email address/i), 'ngozi@example.com')
      await userEvent.type(screen.getByLabelText(/^Phone number/, { selector: 'input' }), '8012345678')
      // The terms checkbox is the last one: the three before it are the notification channels.
      await userEvent.click(screen.getAllByRole('checkbox').at(-1)!)
      await userEvent.click(screen.getByRole('button', { name: /create account/i }))
    }

    it('confirms without saying whether the email already had an account', async () => {
      vi.mocked(registerApi.selfRegister).mockResolvedValue({ status: 'received' })
      renderAt('/register/acme')
      await fillAndSubmit()

      expect(await screen.findByText('Check your email.')).toBeInTheDocument()
      expect(screen.getByText('ngozi@example.com')).toBeInTheDocument()
      // The wording must cover both outcomes: it must not promise a password it may not have sent,
      // and must not announce "account created" (or "already exists") for either.
      expect(screen.queryByText(/account created/i)).toBeNull()
      expect(screen.queryByText(/already exists/i)).toBeNull()
      expect(screen.getByText(/if you already have an account/i)).toBeInTheDocument()
    })

    it('is honest that account and shipment messages are not optional', () => {
      renderAt('/register/acme')
      expect(screen.getByText(/Send me optional messages via/)).toBeInTheDocument()
      expect(screen.getByText(/are always sent/i)).toBeInTheDocument()
    })

    it('sends the request to the company in the link', async () => {
      vi.mocked(registerApi.selfRegister).mockResolvedValue({ status: 'received' })
      renderAt('/register/acme')
      await fillAndSubmit()

      await waitFor(() => expect(registerApi.selfRegister).toHaveBeenCalled())
      expect(vi.mocked(registerApi.selfRegister).mock.calls.at(-1)?.[0]).toBe('acme')
    })

    it('reports a real failure, but has no special case for a taken email', async () => {
      vi.mocked(registerApi.selfRegister).mockRejectedValue(
        new ApiError({ type: 'x', title: 'x', status: 422, detail: 'Phone number is not valid.', error_code: 'VALIDATION_ERROR' }, null),
      )
      renderAt('/register/acme')
      await fillAndSubmit()

      expect(await screen.findByText('Phone number is not valid.')).toBeInTheDocument()
      expect(screen.queryByText('Check your email.')).toBeNull()
    })
  })
})
