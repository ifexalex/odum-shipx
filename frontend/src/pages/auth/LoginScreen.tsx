import { useState, type FormEvent, type JSX } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { authProvider, isInteractiveLogin } from '../../auth/authClient'
import { safeNextPath } from '../../auth/returnPath'
import { homePathForRole } from '../../auth/roleHome'
import { rememberNext } from './returnPath'
import { useSession } from '../../auth/useSession'
import { Banner, Button, Check, Field, Icon, KolaMark, ShipxWordmark } from '../../design/components'
import { colors } from '../../design/theme'
import styles from './LoginScreen.module.css'

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

function BrandIllustration(): JSX.Element {
  return (
    <div className={styles.illustration}>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          opacity: 0.18,
        }}
      >
        <KolaMark size={280} color={colors.primaryBright} />
      </div>
      <svg viewBox="0 0 400 400" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
        <defs>
          <linearGradient id="routeGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor={colors.primaryBright} stopOpacity="0.2" />
            <stop offset="0.5" stopColor={colors.primaryBright} stopOpacity="1" />
            <stop offset="1" stopColor={colors.accentHover} stopOpacity="0.9" />
          </linearGradient>
        </defs>
        <circle cx="80" cy="130" r="10" fill={colors.primaryBright} />
        <circle cx="80" cy="130" r="22" fill={colors.primaryBright} fillOpacity="0.18" />
        <circle cx="320" cy="280" r="10" fill={colors.accentHover} />
        <circle cx="320" cy="280" r="22" fill={colors.accentHover} fillOpacity="0.22" />
        <path d="M80 130 Q200 60 320 280" fill="none" stroke="url(#routeGrad)" strokeWidth="3" strokeDasharray="6 6" />
        <g transform="translate(195 145) rotate(28)">
          <rect x="-22" y="-13" width="44" height="26" rx="6" fill={colors.primaryBright} />
          <rect x="-18" y="-9" width="36" height="2" fill={colors.forestDark} opacity="0.35" />
          <rect x="-18" y="-2" width="36" height="2" fill={colors.forestDark} opacity="0.35" />
          <rect x="-18" y="5" width="36" height="2" fill={colors.forestDark} opacity="0.35" />
        </g>
        <text x="80" y="105" textAnchor="middle" style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fill: colors.primaryBright, letterSpacing: '0.1em' }}>
          CN · GZG
        </text>
        <text x="320" y="312" textAnchor="middle" style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fill: colors.accentHover, letterSpacing: '0.1em' }}>
          NG · LOS
        </text>
      </svg>
    </div>
  )
}

export function LoginScreen(): JSX.Element {
  const { login, beginLogin, status } = useSession()
  const navigate = useNavigate()
  // Where the visitor was heading before sign-in; refused unless it is a plain in-app path (auth/returnPath.ts).
  const next = safeNextPath(useSearchParams()[0].get('next'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const loading = status === 'loading'

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    setError(null)
    try {
      const session = await login(email, password)
      navigate(next ?? homePathForRole(session.role), { replace: true })
    } catch (err) {
      // Temporary password (registration / staff invite): Cognito demands a
      // permanent one before issuing tokens — hand off to the reset screen.
      if (err instanceof Error && err.name === 'NewPasswordRequiredError') {
        navigate(`/reset-password?first=1&email=${encodeURIComponent(email)}`)
        return
      }
      setError(loginErrorMessage(err))
    }
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
    <div className={styles.shell}>
      <div className={styles.brandPanel}>
        <div className={styles.glow} />
        <div className={styles.brandTop}>
          <KolaMark size={26} color="#fff" />
          <ShipxWordmark size={22} showBy />
        </div>
        <div className={styles.tagline}>
          <BrandIllustration />
          <h1 className={styles.heroHeading}>
            Cargo logistics,
            <br />
            <span className={styles.heroAccent}>engineered to move.</span>
          </h1>
          <p className={styles.heroSub}>
            Guangzhou to Lagos. End-to-end. Unstoppable. Built for the operators, customers, and developers
            who lead every shipment.
          </p>
        </div>
        <div className={styles.brandFooter}>
          <div className={styles.footerCopy}>© 2026 ShipX Platform</div>
          <div className={styles.statusRow}>
            <span className={styles.statusDot} />
            <span className={styles.statusText}>All systems operational</span>
          </div>
        </div>
      </div>

      <div className={styles.formPanel}>
        <div className={styles.formWrap}>
          <div className={styles.formHead}>
            <h2 className={styles.formTitle}>Sign in to ShipX</h2>
            <p className={styles.formSub}>
              {isInteractiveLogin
                ? 'Sign in to access your portal.'
                : 'Enter your credentials to access your portal.'}
            </p>
          </div>

          {error && (
            <div style={{ marginBottom: 20 }}>
              <Banner variant="error" title="Couldn't sign in">
                {error}
              </Banner>
            </div>
          )}

          {isInteractiveLogin ? (
            <Button variant="accent" size="lg" full loading={loading} onClick={() => void handleEntraLogin()}>
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
                  <button
                    type="button"
                    className={styles.trailingButton}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    onClick={() => setShowPassword((value) => !value)}
                  >
                    <Icon name={showPassword ? 'eyeoff' : 'eye'} size={16} />
                  </button>
                }
              />
              <div className={styles.rowBetween}>
                <label className={styles.rememberLabel}>
                  <Check checked={rememberMe} onChange={setRememberMe} />
                  Remember me for 30 days
                </label>
                <button type="button" className={styles.link} onClick={() => navigate('/forgot-password')}>
                  Forgot password?
                </button>
              </div>
              <Button type="submit" variant="accent" size="lg" full loading={loading}>
                Sign In
              </Button>
            </form>
          )}

          <div className={styles.divider}>
            <span className={styles.dividerLine} />
            <span className={styles.dividerText}>or</span>
            <span className={styles.dividerLine} />
          </div>
          <p className={styles.footerLine}>
            Customer of a shipping company?{' '}
            <button type="button" className={styles.footerLinkStrong} onClick={() => navigate('/register')}>
              Create your account →
            </button>
          </p>
          <p className={styles.footerLine} style={{ marginTop: 8 }}>
            Are you a shipping company?{' '}
            <button type="button" className={styles.footerLinkStrong} onClick={() => navigate('/get-started')}>
              Onboard with ShipX →
            </button>
          </p>
        </div>
      </div>
    </div>
  )
}
