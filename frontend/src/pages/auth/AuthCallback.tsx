/**
 * Entra interactive-login callback (`/auth/callback`).
 *
 * The backend-configured redirect URI. Entra lands the browser here with
 * `?code=…&state=…` after the user authenticates; this hands them to the
 * backend (`completeLogin` → POST /v1/auth/callback), which validates state
 * against the httpOnly transaction cookie, exchanges the code, and sets the
 * session cookie. On success we build the session and redirect by role; on
 * failure we send the user back to /login with a message. No tokens or PKCE
 * secrets are ever handled here — only the opaque code + state from the URL.
 */
import { useEffect, useRef, useState, type JSX } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { homePathForRole } from '../../auth/roleHome'
import { useSession } from '../../auth/useSession'
import { Banner, Button } from '../../design/components'
import { AuthShell, FormHead } from './AuthShell'

export function AuthCallback(): JSX.Element {
  const navigate = useNavigate()
  const { completeLogin } = useSession()
  const [params] = useSearchParams()
  // Derived during render rather than set from an effect that would correct
  // itself one frame later: these three refusals depend only on the URL and on
  // whether this build has interactive sign-in at all.
  const code = params.get('code')
  const state = params.get('state')
  const entraError = params.get('error_description') || params.get('error')
  const initialError = entraError
    ? entraError
    : !code || !state
      ? 'This sign-in link is missing its authorization code. Please start again.'
      : !completeLogin
        ? 'Interactive sign-in is not enabled for this build.'
        : null

  // Seeded from the above; only the token exchange can change it afterwards.
  const [error, setError] = useState<string | null>(initialError)
  // React 18 StrictMode double-invokes effects in dev; the code is single-use,
  // so guard against a second exchange that would fail with invalid_grant.
  const ran = useRef(false)

  useEffect(() => {
    if (ran.current) return
    ran.current = true

    // Every reason to refuse is already known from the URL at render time and
    // is the initial error above, so there is nothing to set here — only the
    // exchange itself, whose failure is genuinely asynchronous.
    if (initialError || !code || !state || !completeLogin) return

    completeLogin(code, state)
      .then((session) => navigate(homePathForRole(session.role), { replace: true }))
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Sign-in could not be completed. Please try again.')
      })
    // Run once on mount — params/completeLogin are stable for this navigation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) {
    return (
      <AuthShell>
        <FormHead title="Sign-in failed" sub="We couldn't complete your sign-in." />
        <Banner variant="error" title="Couldn't sign in">
          {error}
        </Banner>
        <div style={{ marginTop: 24 }}>
          <Button variant="primary" size="lg" full onClick={() => navigate('/login', { replace: true })}>
            Back to sign in
          </Button>
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell>
      <FormHead title="Signing you in…" sub="Completing your Microsoft Entra sign-in." />
      <div style={{ display: 'flex', justifyContent: 'center', padding: '24px 0' }}>
        <div
          aria-label="Signing in"
          role="status"
          style={{
            width: 36,
            height: 36,
            borderRadius: '50%',
            border: '3px solid var(--color-line)',
            borderTopColor: 'var(--color-primary)',
            animation: 'spin 0.8s linear infinite',
          }}
        />
        <style>{'@keyframes spin{to{transform:rotate(360deg)}}'}</style>
      </div>
    </AuthShell>
  )
}
