import { QueryClientProvider } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { BrowserRouter, createBrowserRouter, RouterProvider } from 'react-router-dom'
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
import { ToastRegion } from './design/components/ToastRegion'

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

// Defense in depth: LocalAuthProvider and RoleSwitcher must NEVER be compiled into
// production builds even if a .env.local file or CI variable sets VITE_ENVIRONMENT=local.
const IS_LOCAL = import.meta.env.DEV && import.meta.env.VITE_ENVIRONMENT === 'local'

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
          <ToastRegion />
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
        <ToastRegion />
      </SessionProvider>
    </QueryClientProvider>
  )
}

// A data router (FD-54), so a form can hold navigation while it has unsaved input (`shell/UnsavedChangesGuard`, which
// needs `useBlocker`). One catch-all route renders the same tree as before: `AppRoutes` still declares every path with
// <Routes>, and each layout keeps its own error boundary. The app-level boundary sits inside the route as well as
// around the router, so a render error reaches it rather than the router's default error screen.
function MainApp(): JSX.Element {
  // Created on mount, not at import: the dev preview pages above run without it.
  const [router] = useState(() =>
    createBrowserRouter([
      {
        path: '*',
        element: (
          <ErrorBoundary variant="app">
            <AppProviders>
              <AppRoutes />
            </AppProviders>
          </ErrorBoundary>
        ),
      },
    ]),
  )
  return <RouterProvider router={router} />
}

// Router + providers root. The dev-only path checks below are a temporary
// stand-in for design/component preview tooling, kept outside the real
// route tree on purpose — AppRoutes (Task 06) owns every production path.
function App(): JSX.Element {
  if (import.meta.env.DEV && window.location.pathname === '/design-preview') {
    return <DesignPreview />
  }
  if (import.meta.env.DEV && window.location.pathname === '/component-catalog') {
    return (
      <BrowserRouter>
        <ComponentCatalog />
      </BrowserRouter>
    )
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
      <MainApp />
    </ErrorBoundary>
  )
}

export default App
