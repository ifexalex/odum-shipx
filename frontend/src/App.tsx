import { QueryClientProvider } from '@tanstack/react-query'
import type { JSX } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { LocalAuthProvider } from './auth/LocalAuthProvider'
import { RoleSwitcher } from './auth/RoleSwitcher'
import { SessionProvider } from './auth/SessionProvider'
import { clearTenantBlocked } from './auth/tenantGate'
import { useSession } from './auth/useSession'
import { ComponentCatalog } from './design/ComponentCatalog'
import { DesignPreview } from './design/DesignPreview'
import { queryClient } from './lib/queryClient'
import { ErrorBoundary } from './shell/ErrorBoundary'
import { AppRoutes } from './shell/routes'

function AuthPreview(): JSX.Element {
  const { session, status } = useSession()
  return (
    <div style={{ padding: 'var(--space-8)', fontFamily: 'var(--font-body)' }}>
      <h1>Auth preview — local dev shim</h1>
      <p>Flip roles below; this is the same Session shape SessionProvider produces from a real Cognito login.</p>
      <p>
        status: <strong>{status}</strong>
      </p>
      <pre style={{ background: 'var(--color-surface-muted)', padding: 'var(--space-4)', borderRadius: 'var(--radius-md)' }}>
        {JSON.stringify(session, null, 2)}
      </pre>
      <RoleSwitcher />
    </div>
  )
}

const IS_LOCAL = import.meta.env.VITE_ENVIRONMENT === 'local'

// Against the Flask dev server (make stack/make up), skip Cognito entirely
// and drive the whole real route tree off LocalAuthProvider's role switcher
// — not just the isolated /auth-preview demo (04_auth_and_session.md).
function AppProviders({ children }: { children: JSX.Element }): JSX.Element {
  if (IS_LOCAL) {
    return (
      <QueryClientProvider client={queryClient}>
        <LocalAuthProvider>
          {children}
          <RoleSwitcher />
        </LocalAuthProvider>
      </QueryClientProvider>
    )
  }
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider
        onSessionChange={() => {
          queryClient.clear()
          // A tripped tenant-blocked gate (16.12) belongs to the old session —
          // a fresh login (possibly to a different, healthy tenant) starts clean.
          clearTenantBlocked()
        }}
      >
        {children}
      </SessionProvider>
    </QueryClientProvider>
  )
}

// Router + providers root. The dev-only path checks below are a temporary
// stand-in for design/component preview tooling, kept outside the real
// route tree on purpose — AppRoutes (Task 06) owns every production path.
function App(): JSX.Element {
  if (import.meta.env.DEV && window.location.pathname === '/design-preview') {
    return <DesignPreview />
  }
  if (import.meta.env.DEV && window.location.pathname === '/component-catalog') {
    return <ComponentCatalog />
  }
  if (import.meta.env.DEV && window.location.pathname === '/auth-preview') {
    return (
      <LocalAuthProvider>
        <AuthPreview />
      </LocalAuthProvider>
    )
  }

  // Outermost, so even a failure in the providers or the router shows a way back instead of a white screen.
  // Each layout has its own boundary around its routed content, which keeps the menu usable.
  return (
    <ErrorBoundary variant="app">
      <BrowserRouter>
        <AppProviders>
          <AppRoutes />
        </AppProviders>
      </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App
