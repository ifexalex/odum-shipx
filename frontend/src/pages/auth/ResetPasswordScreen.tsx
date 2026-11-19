/**
 * 1.4 — Set New Password (Section 1 of the prototype).
 *
 * Two entry modes:
 *  - Code reset (`/reset-password?email=…`): from the forgot-password flow.
 *    Requires the emailed verification code + new password (Cognito
 *    ConfirmForgotPassword).
 *  - First login (`/reset-password?first=1&email=…`): sign-in hit the
 *    NEW_PASSWORD_REQUIRED challenge (temporary password from registration
 *    or staff invite). Completes the challenge, then signs in with the new
 *    password to establish the session.
 */
import { useState, type FormEvent, type JSX } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { completeNewPassword, confirmForgotPassword, hasPendingNewPasswordChallenge } from '../../auth/authClient'
import { homePathForRole } from '../../auth/roleHome'
import { useSession } from '../../auth/useSession'
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

export function ResetPasswordScreen(): JSX.Element {
  const navigate = useNavigate()
  const { login } = useSession()
  const [params] = useSearchParams()
  const firstLogin = params.get('first') === '1'
  const emailParam = params.get('email') ?? ''

  const [email, setEmail] = useState(emailParam)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const requirementsMet = REQUIREMENTS.every((r) => r.ok(password))
  const canSubmit =
    requirementsMet && password === confirm && (firstLogin || (email.trim() && code.trim()))

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      if (firstLogin) {
        if (!hasPendingNewPasswordChallenge()) {
          setError('Your sign-in session expired. Sign in again with your temporary password.')
          return
        }
        await completeNewPassword(password)
        // Challenge complete — establish the app session with the new password.
        const session = await login(email, password)
        navigate(homePathForRole(session.role), { replace: true })
        return
      }
      await confirmForgotPassword(email, code, password)
      setDone(true)
    } catch (err) {
      const codeName = err instanceof Error ? err.name : ''
      if (codeName === 'CodeMismatchException') setError('That code is incorrect. Check the email and try again.')
      else if (codeName === 'ExpiredCodeException') setError('That code has expired. Request a new one.')
      else if (codeName === 'InvalidPasswordException') setError('Password does not meet the account security policy.')
      else setError('Could not update the password. Please try again.')
    } finally {
      setSubmitting(false)
    }
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
          <h2 className={styles.formTitle} style={{ marginBottom: 'var(--space-2)' }}>Password updated.</h2>
          <p className={styles.formSub} style={{ marginBottom: 'var(--space-8)' }}>
            Your password has been changed. Sign in with your new password.
          </p>
          <Button variant="primary" size="lg" full onClick={() => navigate('/login')}>
            Back to sign in
          </Button>
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell>
      <FormHead
        title="Set a new password"
        sub={
          firstLogin
            ? "You're signing in with a temporary password — choose your own to continue."
            : 'Enter the verification code we emailed you, then choose a strong password.'
        }
      />

      {error && (
        <div style={{ marginBottom: 'var(--space-5)' }}>
          <Banner variant="error" title="Could not update password">{error}</Banner>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        {!firstLogin && (
          <>
            <Field
              label="Email address"
              type="email"
              icon="mail"
              name="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
            <Field
              label="Verification code"
              name="code"
              placeholder="6-digit code from your email"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoComplete="one-time-code"
              required
            />
          </>
        )}

        <Field
          label="New password"
          type={showPassword ? 'text' : 'password'}
          icon="lock"
          name="new_password"
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

        <div style={{ marginTop: 'var(--space-4)' }}>
          <Field
            label="Confirm new password"
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

        {/* Requirements checklist (prototype 1.4) */}
        <div
          style={{
            background: 'var(--color-surface-muted)',
            border: '1px solid var(--color-line-soft)',
            borderRadius: 'var(--radius-md)',
            padding: 'var(--space-3) var(--space-4)',
            margin: 'var(--space-2) 0 var(--space-6)',
            fontSize: 'var(--text-xs)',
            lineHeight: 'var(--leading-body)',
          }}
        >
          <div style={{ fontWeight: 600, color: 'var(--color-ink-2)', marginBottom: 'var(--space-2)', textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)' }}>
            Password requirements
          </div>
          {REQUIREMENTS.map((r) => {
            const met = r.ok(password)
            return (
              <div key={r.label} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: met ? 'var(--color-success)' : 'var(--color-ink-3)' }}>
                <Icon name={met ? 'check' : 'minus'} size={12} stroke={3} />
                {r.label}
              </div>
            )
          })}
        </div>

        <Button type="submit" variant="accent" size="lg" full loading={submitting} disabled={!canSubmit}>
          {firstLogin ? 'Set password & sign in' : 'Update password'}
        </Button>
      </form>
    </AuthShell>
  )
}
