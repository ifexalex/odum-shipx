import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState, type JSX } from 'react'
import { MemoryRouter, Route, Routes, Link } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import { ContentErrorBoundary, ErrorBoundary, QuietBoundary, redactPath } from './ErrorBoundary'

function Boom({ message = 'boom' }: { message?: string }): JSX.Element {
  throw new Error(message)
}

describe('ErrorBoundary', () => {
  let errors: ReturnType<typeof vi.spyOn>
  beforeEach(() => { errors = vi.spyOn(console, 'error').mockImplementation(() => undefined) })
  afterEach(() => errors.mockRestore())

  it('shows a fallback instead of a white screen when a child throws', () => {
    render(<ErrorBoundary><Boom /></ErrorBoundary>)
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong')
    expect(screen.getByRole('link', { name: 'Go home' })).toHaveAttribute('href', '/')
  })

  it('renders its children untouched when nothing throws', () => {
    render(<ErrorBoundary><p>fine</p></ErrorBoundary>)
    expect(screen.getByText('fine')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('Try again re-renders the children', async () => {
    function Flaky(): JSX.Element {
      const [ok] = useState(() => (Flaky as unknown as { ok?: boolean }).ok === true)
      if (!ok) throw new Error('first render fails')
      return <p>recovered</p>
    }
    render(<ErrorBoundary><Flaky /></ErrorBoundary>)
    ;(Flaky as unknown as { ok?: boolean }).ok = true
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByText('recovered')).toBeInTheDocument()
  })

  it('clears when the reset key changes', () => {
    const { rerender } = render(<ErrorBoundary resetKey="/a"><Boom /></ErrorBoundary>)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    rerender(<ErrorBoundary resetKey="/b"><p>other page</p></ErrorBoundary>)
    expect(screen.getByText('other page')).toBeInTheDocument()
  })

  it('logs the kind of error and the page, never the message or personal data', () => {
    window.history.pushState({}, '', '/my-billing/123e4567-e89b-12d3-a456-426614174000')
    const old = import.meta.env.DEV
    ;(import.meta.env as Record<string, unknown>).DEV = false
    render(<ErrorBoundary><Boom message="Ngozi Okonkwo ngozi@example.com" /></ErrorBoundary>)
    ;(import.meta.env as Record<string, unknown>).DEV = old
    const logged = errors.mock.calls.map((call: unknown[]) => JSON.stringify(call)).join(' ')
    expect(logged).toContain('Render error caught by ErrorBoundary')
    expect(logged).toContain('/my-billing/:id')
    expect(logged).not.toContain('Ngozi')
    expect(logged).not.toContain('123e4567')
    window.history.pushState({}, '', '/')
  })
})

describe('redactPath', () => {
  it('replaces ids and long numbers, keeps the page', () => {
    expect(redactPath('/billing/123e4567-e89b-12d3-a456-426614174000/charges')).toBe('/billing/:id/charges')
    expect(redactPath('/customers/123456')).toBe('/customers/:n')
    expect(redactPath('/containers')).toBe('/containers')
  })
})

describe('ContentErrorBoundary inside a layout', () => {
  beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => undefined) })
  afterEach(() => vi.restoreAllMocks())

  const ctx = { session: { role: 'customer' }, status: 'authenticated' } as unknown as SessionContextValue

  it('keeps the menu usable, and navigating away clears the error', async () => {
    render(
      <SessionContext.Provider value={ctx}>
        <MemoryRouter initialEntries={['/broken']}>
          <nav><Link to="/fine">Menu: fine page</Link></nav>
          <ContentErrorBoundary>
            <Routes>
              <Route path="/broken" element={<Boom />} />
              <Route path="/fine" element={<p>the fine page</p>} />
            </Routes>
          </ContentErrorBoundary>
        </MemoryRouter>
      </SessionContext.Provider>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go home' })).toHaveAttribute('href', '/my-shipments')

    await userEvent.click(screen.getByRole('link', { name: 'Menu: fine page' }))
    expect(screen.getByText('the fine page')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('QuietBoundary (optional chrome)', () => {
  beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => undefined) })
  afterEach(() => vi.restoreAllMocks())

  it('lets a broken banner disappear without taking the page down', () => {
    render(
      <div>
        <QuietBoundary><Boom /></QuietBoundary>
        <p>the rest of the page</p>
      </div>,
    )
    expect(screen.getByText('the rest of the page')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
