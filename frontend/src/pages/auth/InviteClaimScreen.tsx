/**
 * Public claim page for a customer account-creation invite
 * (`GET /v1/invites/:token`, `POST /v1/invites/:token/accept`).
 *
 * Reached from the SMS/WhatsApp link sent when a customer is created
 * without a login — most often a manifest import, which only ever supplies
 * name + phone. The page shows the shipping company + customer name (the
 * only PII the public preview endpoint exposes), collects email + password,
 * and hands expired/used tokens a "contact your shipping company" message
 * rather than a raw error — the token itself is invisible to the visitor
 * either way; it lives only in the URL.
 */
import { useEffect, useState, type FormEvent, type JSX } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { inviteApi, type InviteDetail } from '../../api/customer'
import { Banner, Button, Field, Icon, IconButton, LinesSkeleton } from '../../design/components'
import { AuthShell, FormHead, meetsPasswordRequirements, PasswordRequirements, PasswordStrength } from './AuthShell'
import styles from './LoginScreen.module.css'

type LoadState = 'loading' | 'ready' | 'invalid'

export function InviteClaimScreen(): JSX.Element {
  const navigate = useNavigate()
  const { token } = useParams<{ token: string }>()
  // A missing token is known from the URL at render time, so it is the initial
  // state rather than an effect that immediately corrects itself.
  const [loadState, setLoadState] = useState<LoadState>(() => (token ? 'loading' : 'invalid'))
  const [invite, setInvite] = useState<InviteDetail | null>(null)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!token) return
    let cancelled = false
    inviteApi
      .get(token)
      .then((detail) => {
        if (cancelled) return
        setInvite(detail)
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
  const canSubmit = requirementsMet && password === confirm && email.trim().length > 0

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (!token) return
    setError(null)
    setSubmitting(true)
    try {
      await inviteApi.accept(token, { email, password })
      setDone(true)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setLoadState('invalid')
      } else if (err instanceof ApiError && err.status === 409) {
        setError('An account with this email already exists. Try signing in instead.')
      } else {
        setError(err instanceof ApiError ? err.message : 'Could not create your account. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (loadState === 'loading') {
    return (
      <AuthShell>
        <div style={{ textAlign: 'center', padding: 'var(--space-12) 0' }}>
          <LinesSkeleton label="Loading your invite" />
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
            It may have expired or already been used. Contact your shipping company to request a new one.
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
          <h1 className={styles.formTitle} style={{ marginBottom: 'var(--space-2)' }}>Account created.</h1>
          <p className={styles.formSub} style={{ marginBottom: 'var(--space-6)' }}>
            Sign in with <strong>{email}</strong> and the password you just chose to track your shipments.
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
        title={invite?.customer_name ? `Welcome, ${invite.customer_name}` : 'Create your account'}
        sub={
          invite?.company_name
            ? `${invite.company_name} invited you to track your shipments online. Choose an email and password to finish setting up your account.`
            : 'Choose an email and password to finish setting up your account.'
        }
      />

      {error && (
        <div style={{ marginBottom: 'var(--space-5)' }}>
          <Banner variant="error" title="Could not create account">{error}</Banner>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <Field
          label="Email address"
          type="email"
          icon="mail"
          name="email"
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          required
        />

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
          Create account
        </Button>
      </form>

      <p className={styles.footerLine} style={{ marginTop: 'var(--space-5)' }}>
        Already have an account?{' '}
        <Link to="/login" className={styles.footerLinkStrong}>Sign in <Icon name="arrowright" size={12} /></Link>
      </p>
    </AuthShell>
  )
}
