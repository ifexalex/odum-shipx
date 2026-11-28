/**
 * The /auth/callback page inside a platform admin's step-up window (platform audit Phase 1b): the tab that opened the
 * window finishes the exchange, so this page must sign nobody in.
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../../auth/SessionContext'
import { AuthCallback } from './AuthCallback'

describe('AuthCallback in a step-up window', () => {
  it('leaves a step-up code alone', () => {
    const completeLogin = vi.fn()
    render(
      <SessionContext.Provider value={{ completeLogin } as unknown as SessionContextValue}>
        <MemoryRouter initialEntries={['/auth/callback?code=abc&state=su.xyz']}>
          <Routes>
            <Route path="/auth/callback" element={<AuthCallback />} />
          </Routes>
        </MemoryRouter>
      </SessionContext.Provider>,
    )
    expect(screen.getByText('Signed in')).toBeInTheDocument()
    expect(completeLogin).not.toHaveBeenCalled()
  })
})
