import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

  it('sends shipping companies to Book a demo (/get-started)', () => {
    renderPage()
    const requests = screen.getAllByRole('link', { name: 'Book a demo' })
    expect(requests.length).toBeGreaterThanOrEqual(4)
    for (const link of requests) expect(link).toHaveAttribute('href', '/get-started')
  })

  it('offers direct tracking links and has no dead # footer anchors', () => {
    renderPage()
    const trackLinks = screen.getAllByRole('link').filter((link) => link.getAttribute('href') === '/track')
    expect(trackLinks.length).toBeGreaterThanOrEqual(2)
    const deadLinks = screen.getAllByRole('link').filter((link) => link.getAttribute('href') === '#')
    expect(deadLinks).toEqual([])
  })

  it('opens the legal modal from footer legal buttons', async () => {
    renderPage()
    await userEvent.click(screen.getByRole('button', { name: 'Terms of service' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Terms of Service')).toBeInTheDocument()
  })

  it('promises no self-serve trial the demo flow does not offer', () => {
    const { container } = renderPage()
    expect(container.textContent).not.toMatch(/free trial|30-day|no card required/i)
  })
})
