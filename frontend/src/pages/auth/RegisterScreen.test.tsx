/**
 * Bare `/register` (no company slug) must NOT dead-end — it routes the two
 * audiences apart: customers use their company link/invite; shipping companies
 * go to `/get-started`. A slugged `/register/:slug` is the real customer form.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
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
})
