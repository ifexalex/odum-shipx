/**
 * 1.3 — Forgot Password (Section 1 of the prototype).
 *
 * Ground-truth divergence: the prototype copy says a reset *link* is emailed;
 * Cognito's ForgotPassword flow emails a numeric *code* which is entered on
 * the reset screen together with the new password. Copy adjusted accordingly.
 */
import { useState, type FormEvent, type JSX } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { forgotPassword } from '../../auth/authClient'
import { Banner, Button, Field, Icon, Pressable } from '../../design/components'
import { AuthShell, FormHead } from './AuthShell'
import styles from './LoginScreen.module.css'

export function ForgotPasswordScreen(): JSX.Element {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await forgotPassword(email)
      setSent(true)
    } catch (err) {
      // Do not reveal whether the address exists — same success UX on
      // UserNotFoundException (Cognito already behaves this way when the
      // pool's prevent-user-existence-errors setting is on).
      const code = err instanceof Error ? err.name : ''
      if (code === 'UserNotFoundException') {
        setSent(true)
      } else if (code === 'LimitExceededException') {
        setError('Too many attempts. Wait a few minutes and try again.')
      } else {
        setError('Could not start the password reset. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (sent) {
    return (
      <AuthShell>
        <Link to="/login" className={styles.link} style={{ marginBottom: 'var(--space-8)', display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <Icon name="arrowleft" size={14} /> Back to sign in
        </Link>
        <div style={{ textAlign: 'center' }}>
          <div
            style={{
              width: 84,
              height: 84,
              borderRadius: '50%',
              background: 'var(--color-primary-soft)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto var(--space-6)',
            }}
          >
            <Icon name="mail" size={38} color="var(--color-primary)" stroke={2} />
          </div>
          <h2 className={styles.formTitle} style={{ marginBottom: 'var(--space-2)' }}>Check your email</h2>
          <p className={styles.formSub}>We sent a verification code to</p>
          <p style={{ fontSize: 'var(--text-lg)', fontWeight: 600, color: 'var(--color-ink)', margin: '0 0 var(--space-6)' }}>{email}</p>
          <Banner variant="info" title="Code expires in 60 minutes">
            Enter the code on the next screen together with your new password.
          </Banner>
          <div style={{ marginTop: 'var(--space-6)' }}>
            <Button
              variant="accent"
              size="lg"
              full
              onClick={() => navigate(`/reset-password?email=${encodeURIComponent(email)}`)}
            >
              Enter code &amp; set new password
            </Button>
          </div>
          <p className={styles.footerLine} style={{ marginTop: 'var(--space-5)' }}>
            Didn&apos;t receive it?{' '}
            <Pressable className={styles.footerLinkStrong} onClick={() => setSent(false)}>
              Resend code
            </Pressable>
          </p>
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell>
      <Link to="/login" className={styles.link} style={{ marginBottom: 'var(--space-8)', display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <Icon name="arrowleft" size={14} /> Back to sign in
        </Link>
      <FormHead
        title="Reset your password"
        sub="Enter the email associated with your account. We'll send a verification code."
      />

      {error && (
        <div style={{ marginBottom: 'var(--space-5)' }}>
          <Banner variant="error" title="Something went wrong">{error}</Banner>
        </div>
      )}

      <form onSubmit={handleSubmit}>
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
        <Button type="submit" variant="accent" size="lg" full loading={submitting}>
          Send reset code
        </Button>
      </form>

      <p className={styles.footerLine} style={{ marginTop: 'var(--space-5)' }}>
        Remember your password?{' '}
        <Link to="/login" className={styles.footerLinkStrong}>Sign in <Icon name="arrowright" size={12} /></Link>
      </p>
    </AuthShell>
  )
}
