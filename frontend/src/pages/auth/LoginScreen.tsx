import { useContext, useState, type FormEvent, type JSX } from 'react'
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import {
  authProvider,
  hasPlatformPool,
  isInteractiveLogin,
  MfaCodeRequiredError,
  MfaSetupRequiredError,
} from '../../auth/authClient'
import { LocalRoleContext } from '../../auth/LocalRoleContext'
import { safeNextPath } from '../../auth/returnPath'
import { homePathForRole } from '../../auth/roleHome'
import { useSession } from '../../auth/useSession'
import { Banner, Button, Field, Icon, IconButton } from '../../design/components'
import { AuthShell, FormHead } from './AuthShell'
import styles from './LoginScreen.module.css'
import { rememberNext } from './returnPath'

// Cognito-side errors only — tenant suspension is a backend/RLS concern
// surfaced on the first real API call after login, not at the Cognito IdP
// boundary (login never touches our backend, see 04_auth_and_session.md).
function loginErrorMessage(err: unknown): string {
  const code = err instanceof Error ? err.name : undefined
  const message = err instanceof Error ? err.message : ''
  // Entra errors come from EntraClient / the backend login proxy already phrased
  // for the user (bad credentials, server/config faults) — surface them directly
  // rather than collapsing every Entra failure into the generic Cognito fallback.
  if (authProvider === 'entra') {
    return message || 'Something went wrong signing you in. Please try again.'
  }
  // Cognito reports a deactivated account as NotAuthorizedException("User is disabled.")
  if (code === 'NotAuthorizedException' && /disabled/i.test(message)) {
    return 'Your account has been deactivated. Contact your tenant administrator to restore access.'
  }
  if (code === 'NotAuthorizedException' || code === 'UserNotFoundException') {
    return 'Check your credentials and try again. After 5 failed attempts, your account locks for 15 minutes.'
  }
  if (code === 'UserNotConfirmedException') {
    return 'Your account is not yet verified. Check your email for a verification link.'
  }
  return 'Something went wrong signing you in. Please try again.'
}

/** The second step of a platform admin's sign-in (platform audit Phase 1b): a code, or setting up the app first. */
export interface MfaStep {
  step: 'code' | 'setup'
  secret?: string
  otpauthUri?: string
}

function mfaStepFrom(err: unknown): MfaStep | null {
  if (err instanceof MfaSetupRequiredError) return { step: 'setup', secret: err.secret, otpauthUri: err.otpauthUri }
  if (err instanceof MfaCodeRequiredError) return { step: 'code' }
  return null
}

export function LoginScreen(): JSX.Element {
  const { session, login, beginLogin, completeMfa, status } = useSession()
  const isLocalDevShim = useContext(LocalRoleContext) !== null
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  // Where the visitor was heading before sign-in; refused unless it is a plain in-app path (auth/returnPath.ts).
  const next = safeNextPath(params.get('next'))
  // Platform admins sign in to their own Cognito pool, which requires MFA (platform audit Phase 1b).
  const platformMode = params.get('platform') === '1' && hasPlatformPool() && !isInteractiveLogin
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Arriving from the set-new-password screen mid-sign-in carries the MFA step in navigation state.
  const [mfa, setMfa] = useState<MfaStep | null>(
    () => ((location.state as { mfa?: MfaStep } | null)?.mfa ?? null),
  )
  const [mfaCode, setMfaCode] = useState('')
  const loading = status === 'loading'

  // Already signed in (in real auth) — send straight to the requested path or the role's home.
  // Keep /login reachable under LocalAuthProvider so developers and local-stack E2E tests can
  // switch from the default dev shim into a real Cognito session without logging out first.
  if (status === 'authenticated' && session && !isLocalDevShim) {
    return <Navigate to={next ?? homePathForRole(session.role)} replace />
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    setError(null)
    try {
      const nextSession = await login(email, password, { pool: platformMode ? 'platform' : 'tenant' })
      navigate(next ?? homePathForRole(nextSession.role), { replace: true })
    } catch (err) {
      // Temporary password (registration / staff invite): Cognito demands a
      // permanent one before issuing tokens — hand off to the reset screen.
      if (err instanceof Error && err.name === 'NewPasswordRequiredError') {
        navigate(`/reset-password?first=1&email=${encodeURIComponent(email)}${platformMode ? '&platform=1' : ''}`)
        return
      }
      const step = mfaStepFrom(err)
      if (step) {
        setMfa(step)
        return
      }
      if (import.meta.env.DEV) {
        console.error('[LoginScreen] signIn failed:', err)
      }
      setError(loginErrorMessage(err))
    }
  }

  async function handleMfaSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (!mfa || !completeMfa) return
    setError(null)
    try {
      const nextSession = await completeMfa(mfa.step, mfaCode)
      navigate(next ?? homePathForRole(nextSession.role), { replace: true })
    } catch (err) {
      const code = err instanceof Error ? err.name : ''
      setError(
        code === 'CodeMismatchException' || code === 'EnableSoftwareTokenMFAException'
          ? 'That code is not right. Check the time on your phone and try the newest code.'
          : code === 'NotAuthorizedException'
            ? 'This sign-in timed out. Start again with your email and password.'
            : 'Could not check the code. Try again.',
      )
    }
  }

  if (mfa) {
    return (
      <AuthShell>
        <FormHead
          title={mfa.step === 'setup' ? 'Set up your authenticator' : 'Enter your code'}
          sub={
            mfa.step === 'setup'
              ? 'Platform admins sign in with a second factor. Add ShipX to an authenticator app (Google Authenticator, 1Password, Authy…), then enter the 6-digit code it shows.'
              : 'Enter the 6-digit code from your authenticator app.'
          }
        />
        {error && (
          <div style={{ marginBottom: 'var(--space-5)' }}>
            <Banner variant="error" title="Couldn't sign in">
              {error}
            </Banner>
          </div>
        )}
        {mfa.step === 'setup' && mfa.secret && (
          <div style={{ marginBottom: 'var(--space-5)' }}>
            <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>Setup key</div>
            <code style={{ display: 'block', wordBreak: 'break-all', fontSize: 'var(--text-md)', margin: 'var(--space-2) 0' }}>
              {mfa.secret}
            </code>
            {mfa.otpauthUri && (
              <a href={mfa.otpauthUri} className={styles.link}>
                Open in an authenticator app on this device
              </a>
            )}
          </div>
        )}
        <form onSubmit={(e) => void handleMfaSubmit(e)}>
          <Field
            label="Authenticator code"
            name="mfa_code"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={mfaCode}
            onChange={(event) => setMfaCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
            required
          />
          <Button type="submit" variant="primary" size="lg" full loading={loading} disabled={mfaCode.length !== 6}>
            {mfa.step === 'setup' ? 'Finish setup' : 'Verify'}
          </Button>
        </form>
      </AuthShell>
    )
  }

  // Entra: no in-app credentials — redirect to Entra's hosted sign-in (the
  // interactive flow that triggers the custom-claims provider). beginLogin
  // navigates away on success, so this only returns on failure.
  async function handleEntraLogin(): Promise<void> {
    setError(null)
    // The sign-in leaves the app and returns to /auth/callback, which restores this.
    rememberNext(next)
    try {
      await beginLogin?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start sign-in. Please try again.')
    }
  }

  return (
    <AuthShell>
      <FormHead
        title={platformMode ? 'Platform admin sign-in' : 'Sign in to ShipX'}
        sub={
          platformMode
            ? 'For ShipX platform staff. You will be asked for a code from your authenticator app.'
            : isInteractiveLogin
              ? "You'll be redirected to our secure sign-in screen to access your portal."
              : 'Enter your credentials to access your portal.'
        }
      />

      {error && (
        <div style={{ marginBottom: 'var(--space-5)' }}>
          <Banner variant="error" title="Couldn't sign in">
            {error}
          </Banner>
        </div>
      )}

      {isInteractiveLogin ? (
        <Button
          variant="primary"
          size="lg"
          full
          trailingIcon="arrowright"
          loading={loading}
          onClick={() => void handleEntraLogin()}
        >
          Sign in
        </Button>
      ) : (
        <form onSubmit={handleSubmit}>
          <Field
            label="Email address"
            type="email"
            icon="mail"
            placeholder="you@company.com"
            name="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="username"
            required
          />
          <Field
            label="Password"
            type={showPassword ? 'text' : 'password'}
            icon="lock"
            placeholder="••••••••"
            name="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
            trailing={
              <IconButton
                className={styles.trailingButton}
                size="sm"
                icon={showPassword ? 'eyeoff' : 'eye'}
                label={showPassword ? 'Hide password' : 'Show password'}
                onClick={() => setShowPassword((value) => !value)}
              />
            }
          />
          <div className={styles.rowBetween} style={{ justifyContent: 'flex-end' }}>
            <Link to="/forgot-password" className={styles.link}>
              Forgot password?
            </Link>
          </div>
          <Button type="submit" variant="primary" size="lg" full loading={loading}>
            Sign in
          </Button>
        </form>
      )}

      <div className={styles.divider}>
        <span className={styles.dividerLine} />
        <span className={styles.dividerText}>or</span>
        <span className={styles.dividerLine} />
      </div>
      <p className={styles.footerLine}>
        Have a tracking code?{' '}
        <Link to="/track" className={styles.footerLinkStrong}>
          Track a shipment <Icon name="arrowright" size={12} />
        </Link>
      </p>
      <p className={styles.footerLine} style={{ marginTop: 'var(--space-2)' }}>
        Are you a shipping company?{' '}
        <Link to="/get-started" className={styles.footerLinkStrong}>
          Book a demo <Icon name="arrowright" size={12} />
        </Link>
      </p>
      <p className={styles.footerLine} style={{ marginTop: 'var(--space-2)', fontSize: 'var(--text-xs)' }}>
        New customer? Use the sign-up or invite link sent by your shipping company.
      </p>
      {hasPlatformPool() && !isInteractiveLogin && (
        <p className={styles.footerLine} style={{ marginTop: 'var(--space-2)', fontSize: 'var(--text-xs)' }}>
          {platformMode ? (
            <Link to="/login" className={styles.link}>
              Back to the standard sign-in
            </Link>
          ) : (
            <Link to="/login?platform=1" className={styles.link}>
              ShipX platform admin? Sign in here
            </Link>
          )}
        </p>
      )}
    </AuthShell>
  )
}
