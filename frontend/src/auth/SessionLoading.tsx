import type { JSX } from 'react'

// Rendered by RoleGuard and RootRedirect while SessionProvider's mount-time
// silent-restore is in flight (status === 'loading') — the whole point of
// that restore attempt is to avoid a flash of the login screen on every page
// reload, so this must never itself redirect or render route content early.
export function SessionLoading(): JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        background: 'var(--color-page)',
      }}
      aria-busy="true"
      aria-live="polite"
    >
      <span
        style={{
          width: 28,
          height: 28,
          borderRadius: '50%',
          border: '3px solid var(--color-line-soft)',
          borderTopColor: 'var(--color-primary)',
          animation: 'sx-session-loading-spin 0.7s linear infinite',
        }}
      />
      <style>{'@keyframes sx-session-loading-spin { to { transform: rotate(360deg) } }'}</style>
    </div>
  )
}
