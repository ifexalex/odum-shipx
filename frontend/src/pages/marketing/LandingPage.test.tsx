import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { LandingPage } from './LandingPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>,
  )
}

describe('LandingPage sign-up entry points (FD-30)', () => {
  it('sends no button to the customer sign-up form', () => {
    renderPage()
    const toRegister = screen.getAllByRole('link').filter((link) => link.getAttribute('href')?.startsWith('/register'))
    expect(toRegister).toEqual([])
  })

  it('sends shipping companies to the access request', () => {
    renderPage()
    const requests = screen.getAllByRole('link', { name: 'Request access' })
    expect(requests.length).toBeGreaterThanOrEqual(4)
    for (const link of requests) expect(link).toHaveAttribute('href', '/get-started')
  })

  it('promises no self-serve trial the request flow does not offer', () => {
    const { container } = renderPage()
    expect(container.textContent).not.toMatch(/free trial|30-day|no card required/i)
  })
})
