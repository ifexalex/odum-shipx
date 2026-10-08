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
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { inviteApi, type InviteDetail } from '../../api/customer'
import { Banner, Button, Field, Icon } from '../../design/components'
import { AuthShell, FormHead, PasswordStrength } from './AuthShell'
import styles from './LoginScreen.module.css'

interface Requirement {
  label: string
  ok: (pw: string) => boolean
}

const REQUIREMENTS: Requirement[] = [
  { label: 'At least 12 characters', ok: (pw) => pw.length >= 12 },
  { label: 'Mix of upper & lowercase', ok: (pw) => /[a-z]/.test(pw) && /[A-Z]/.test(pw) },
  { label: 'At least one number', ok: (pw) => /\d/.test(pw) },
  { label: 'At least one special character', ok: (pw) => /[^A-Za-z0-9]/.test(pw) },
]

type LoadState = 'loading' | 'ready' | 'invalid'

export function InviteClaimScreen(): JSX.Element {
  const navigate = useNavigate()
  const { token } = useParams<{ token: string }>()
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [invite, setInvite] = useState<InviteDetail | null>(null)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!token) {
      setLoadState('invalid')
      return
    }
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

  const requirementsMet = REQUIREMENTS.every((r) => r.ok(password))
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
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <p className={styles.formSub}>Loading your invite…</p>
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
              margin: '0 auto 24px',
            }}
          >
            <Icon name="alert" size={42} color="var(--color-error)" stroke={2.5} />
          </div>
          <h2 className={styles.formTitle} style={{ marginBottom: 8 }}>This link is no longer valid.</h2>
          <p className={styles.formSub} style={{ marginBottom: 24 }}>
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
              margin: '0 auto 24px',
            }}
          >
            <Icon name="check" size={42} color="var(--color-success)" stroke={2.5} />
          </div>
          <h2 className={styles.formTitle} style={{ marginBottom: 8 }}>Account created.</h2>
          <p className={styles.formSub} style={{ marginBottom: 24 }}>
            Sign in with <strong>{email}</strong> and the password you just chose to track your shipments.
          </p>
          <Button variant="primary" size="lg" full onClick={() => navigate('/login')}>
            Sign in →
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
        <div style={{ marginBottom: 20 }}>
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
            <button
              type="button"
              className={styles.trailingButton}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              onClick={() => setShowPassword((v) => !v)}
            >
              <Icon name={showPassword ? 'eyeoff' : 'eye'} size={16} />
            </button>
          }
        />
        <PasswordStrength password={password} />

        <div style={{ marginTop: 16, marginBottom: 8 }}>
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

        <div
          style={{
            background: 'var(--color-surface-muted)',
            border: '1px solid var(--color-line-soft)',
            borderRadius: 8,
            padding: '12px 14px',
            margin: '8px 0 24px',
            fontSize: 12,
            lineHeight: 1.7,
          }}
        >
          <div style={{ fontWeight: 600, color: 'var(--color-ink-2)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Password requirements
          </div>
          {REQUIREMENTS.map((r) => {
            const met = r.ok(password)
            return (
              <div key={r.label} style={{ display: 'flex', alignItems: 'center', gap: 6, color: met ? 'var(--color-success)' : 'var(--color-ink-3)' }}>
                <Icon name={met ? 'check' : 'minus'} size={12} stroke={3} />
                {r.label}
              </div>
            )
          })}
        </div>

        <Button type="submit" variant="accent" size="lg" full loading={submitting} disabled={!canSubmit}>
          Create account
        </Button>
      </form>
    </AuthShell>
  )
}
