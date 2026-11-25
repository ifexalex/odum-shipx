/**
 * Public account-activation page for operator-provisioned staff/admins
 * (`GET /v1/activate/:token`, `POST /v1/activate/:token`).
 *
 * Reached from the ShipX welcome email sent when a tenant admin or staff user
 * is provisioned (created in the IdP with a random password and no login). The
 * page shows the account email (fixed — not editable) and collects a new
 * password, which the backend sets in the IdP via the provisioning app. Expired
 * or used links get a "request a new one" message rather than a raw error.
 */
import { useEffect, useState, type FormEvent, type JSX } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { activationApi, type ActivationDetail } from '../../api/customer'
import { Banner, Button, Field, Icon, IconButton, LinesSkeleton } from '../../design/components'
import { AuthShell, FormHead, meetsPasswordRequirements, PasswordRequirements, PasswordStrength } from './AuthShell'
import styles from './LoginScreen.module.css'

type LoadState = 'loading' | 'ready' | 'invalid'

export function ActivateScreen(): JSX.Element {
  const navigate = useNavigate()
  const { token } = useParams<{ token: string }>()
  // A missing token is known from the URL at render time, so it is the initial
  // state rather than an effect that immediately corrects itself.
  const [loadState, setLoadState] = useState<LoadState>(() => (token ? 'loading' : 'invalid'))
  const [detail, setDetail] = useState<ActivationDetail | null>(null)

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!token) return
    let cancelled = false
    activationApi
      .get(token)
      .then((d) => {
        if (cancelled) return
        setDetail(d)
        setLoadState('ready')
      })
      .catch(() => {
        if (cancelled) return
        setLoadState('invalid')
      })
    return () => {
      cancelled = true
    }
  }, [token])

  const requirementsMet = meetsPasswordRequirements(password)
  const canSubmit = requirementsMet && password === confirm

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (!token) return
    setError(null)
    setSubmitting(true)
    try {
      await activationApi.activate(token, { password })
      setDone(true)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setLoadState('invalid')
      } else {
        setError(err instanceof ApiError ? err.message : 'Could not set your password. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (loadState === 'loading') {
    return (
      <AuthShell>
        <div style={{ textAlign: 'center', padding: 'var(--space-12) 0' }}>
          <LinesSkeleton label="Checking your activation link" />
        </div>
      </AuthShell>
    )
  }

  if (loadState === 'invalid') {
    return (
      <AuthShell>
        <div style={{ textAlign: 'center' }}>
          <div
            style={{
              width: 84,
              height: 84,
              borderRadius: '50%',
              background: 'var(--color-error-soft)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto var(--space-6)',
            }}
          >
            <Icon name="alert" size={42} color="var(--color-error)" stroke={2.5} />
          </div>
          <h1 className={styles.formTitle} style={{ marginBottom: 'var(--space-2)' }}>This link is no longer valid.</h1>
          <p className={styles.formSub} style={{ marginBottom: 'var(--space-6)' }}>
            It may have expired or already been used. Ask your administrator to resend your invitation.
          </p>
          <Button variant="primary" size="lg" full onClick={() => navigate('/login')}>
            Back to sign in
          </Button>
        </div>
      </AuthShell>
    )
  }

  if (done) {
    return (
      <AuthShell>
        <div style={{ textAlign: 'center' }}>
          <div
            style={{
              width: 84,
              height: 84,
              borderRadius: '50%',
              background: 'var(--color-success-soft)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto var(--space-6)',
            }}
          >
            <Icon name="check" size={42} color="var(--color-success)" stroke={2.5} />
          </div>
          <h1 className={styles.formTitle} style={{ marginBottom: 'var(--space-2)' }}>You&rsquo;re all set.</h1>
          <p className={styles.formSub} style={{ marginBottom: 'var(--space-6)' }}>
            Sign in with <strong>{detail?.email}</strong> and the password you just chose.
          </p>
          <Button variant="primary" size="lg" full trailingIcon="arrowright" onClick={() => navigate('/login')}>
            Sign in
          </Button>
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell>
      <FormHead
        title={detail?.full_name ? `Welcome, ${detail.full_name}` : 'Activate your account'}
        sub="Set a password to activate your ShipX account and sign in."
      />

      {error && (
        <div style={{ marginBottom: 'var(--space-5)' }}>
          <Banner variant="error" title="Could not set password">{error}</Banner>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <Field label="Email address" type="email" icon="mail" name="email" value={detail?.email ?? ''} readOnly disabled />

        <Field
          label="Password"
          type={showPassword ? 'text' : 'password'}
          icon="lock"
          name="password"
          placeholder="At least 12 characters"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
          required
          trailing={
            <IconButton
              className={styles.trailingButton}
              size="sm"
              icon={showPassword ? 'eyeoff' : 'eye'}
              label={showPassword ? 'Hide password' : 'Show password'}
              onClick={() => setShowPassword((v) => !v)}
            />
          }
        />
        <PasswordStrength password={password} />

        <div style={{ marginTop: 'var(--space-4)', marginBottom: 'var(--space-2)' }}>
          <Field
            label="Confirm password"
            type={showPassword ? 'text' : 'password'}
            icon="lock"
            name="confirm_password"
            placeholder="Re-enter password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            required
            error={confirm.length > 0 && confirm !== password ? "Passwords don't match." : undefined}
          />
        </div>

        <PasswordRequirements password={password} />

        <Button type="submit" variant="primary" size="lg" full loading={submitting} disabled={!canSubmit}>
          Activate account
        </Button>
      </form>

      <p className={styles.footerLine} style={{ marginTop: 'var(--space-5)' }}>
        Already activated?{' '}
        <Link to="/login" className={styles.footerLinkStrong}>Sign in <Icon name="arrowright" size={12} /></Link>
      </p>
    </AuthShell>
  )
}
