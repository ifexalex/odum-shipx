import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

describe('App', () => {
  it('renders the public landing page at the apex path when signed out, without crashing', async () => {
    // App.tsx reads VITE_ENVIRONMENT === 'local' into a module-level
    // constant at import time, to decide whether to swap in
    // LocalAuthProvider — stub it before importing so this test doesn't
    // depend on whether the developer's own .env.local (gitignored, used
    // for make stack dev) happens to be present. vi.resetModules() +
    // dynamic import are required here since stubbing after a static
    // top-level import would be too late.
    vi.stubEnv('VITE_ENVIRONMENT', 'production')
    vi.resetModules()
    const { default: App } = await import('./App')

    render(<App />)
    // SessionProvider always attempts a silent session restore on mount
    // before deciding there's no session (RootRedirect renders <SessionLoading />
    // until that settles) — findByRole waits it out instead of racing it.
    expect(await screen.findByRole('heading', { name: /Run your entire cargo operation/ })).toBeInTheDocument()
  })
})
