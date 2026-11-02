/**
 * 1.2 — Customer Self-Registration (Section 1 of the prototype).
 *
 * Ground-truth divergence from the prototype (see AUDIT_GAPS.md's
 * intentional-divergence register): the prototype mock shows password +
 * confirm-password fields, but the real backend (POST /v1/register/{slug} →
 * self_register_customer) provisions the Cognito user itself and Cognito
 * emails a TEMPORARY password. The customer signs in with it and is then
 * forced through the set-new-password flow (NEW_PASSWORD_REQUIRED).
 * So this screen collects profile + consent only — no password fields.
 *
 * Ground-truth fix: this used to resolve the tenant from the Host header,
 * which is unreachable in practice (the frontend calls a shared
 * VITE_API_BASE_URL, so the backend only ever sees API Gateway's own host).
 * The route is now company-specific — `/register/:slug` — and the slug is
 * sent explicitly; no more hostname guessing.
 */
import { useState, type FormEvent, type JSX } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { registerApi } from '../../api/customer'
import { Banner, Button, Check, Field, Icon, PhoneField } from '../../design/components'
import { AuthShell, FormHead } from './AuthShell'
import styles from './LoginScreen.module.css'

const CHANNELS = [
  { key: 'sms', label: 'SMS' },
  { key: 'whatsapp', label: 'WhatsApp' },
  { key: 'email', label: 'Email' },
] as const

export function RegisterScreen(): JSX.Element {
  const navigate = useNavigate()
  const { slug } = useParams<{ slug: string }>()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [whatsapp, setWhatsapp] = useState('')
  const [channels, setChannels] = useState<string[]>(['sms', 'whatsapp', 'email'])
  const [agreed, setAgreed] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  function toggleChannel(key: string): void {
    setChannels((prev) => (prev.includes(key) ? prev.filter((c) => c !== key) : [...prev, key]))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (!slug) {
      setError('This sign-up link is missing your shipping company. Use the link your shipping company gave you.')
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      await registerApi.selfRegister(slug, {
        name,
        email,
        phone,
        ...(whatsapp.trim() ? { whatsapp } : {}),
        notification_consent: channels,
      })
      setDone(true)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('An account with this email already exists. Try signing in instead.')
      } else {
        setError(err instanceof ApiError ? err.message : 'Registration failed. Please try again.')
      }
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
              margin: '0 auto 24px',
            }}
          >
            <Icon name="check" size={42} color="var(--color-success)" stroke={2.5} />
          </div>
          <h2 className={styles.formTitle} style={{ marginBottom: 8 }}>Account created.</h2>
          <p className={styles.formSub} style={{ marginBottom: 24 }}>
            We sent a <strong>temporary password</strong> to <strong>{email}</strong>. Sign in with it
            and you&apos;ll be asked to choose your own password.
          </p>
          <Banner variant="info" title="Didn't receive the email?">
            Check your spam folder. The temporary password expires in 7 days.
          </Banner>
          <div style={{ marginTop: 24 }}>
            <Button variant="primary" size="lg" full onClick={() => navigate('/login')}>
              Back to sign in
            </Button>
          </div>
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell>
      <FormHead
        title="Create your customer account"
        sub="For customers of a shipping company — track your shipments and manage billing. Not onboarding a company?"
      />

      {!slug && (
        <div style={{ marginBottom: 20 }}>
          <Banner variant="warning" title="Which are you?">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <span>
                <strong>A customer</strong> of a shipping company? Use the company-specific sign-up link your
                shipping company gave you, or wait for their invite.
              </span>
              <span>
                <strong>A shipping company</strong> wanting to run your operations on ShipX?{' '}
                <button type="button" className={styles.link} onClick={() => navigate('/get-started')}>
                  Get started here →
                </button>
              </span>
            </div>
          </Banner>
        </div>
      )}

      {error && (
        <div style={{ marginBottom: 20 }}>
          <Banner variant="error" title="Registration failed">{error}</Banner>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <Field
          label="Full name"
          name="name"
          placeholder="Ngozi Okonkwo"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
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
        <PhoneField
          label="Phone number"
          name="phone"
          value={phone}
          onChange={setPhone}
          required
        />
        <Field
          label="WhatsApp number"
          icon="phone"
          name="whatsapp"
          placeholder="If different from phone"
          value={whatsapp}
          onChange={(e) => setWhatsapp(e.target.value)}
          optional
        />

        <div style={{ marginBottom: 16 }}>
          <span style={{ display: 'block', fontWeight: 500, fontSize: 13, color: 'var(--color-ink-2)', marginBottom: 8 }}>
            Notify me via
          </span>
          <div style={{ display: 'flex', gap: 16 }}>
            {CHANNELS.map(({ key, label }) => (
              <label key={key} className={styles.rememberLabel}>
                <Check checked={channels.includes(key)} onChange={() => toggleChannel(key)} />
                {label}
              </label>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, margin: '8px 0 24px' }}>
          <Check checked={agreed} onChange={setAgreed} />
          <span style={{ fontSize: 13, color: 'var(--color-ink-2)', lineHeight: 1.5 }}>
            I agree to the <a className={styles.link} href="#terms">Terms of Service</a> and{' '}
            <a className={styles.link} href="#privacy">Privacy Policy</a>.
          </span>
        </div>

        <Button type="submit" variant="accent" size="lg" full loading={submitting} disabled={!agreed || !slug}>
          Create account
        </Button>
      </form>

      <p className={styles.footerLine} style={{ marginTop: 20 }}>
        Already have an account?{' '}
        <button type="button" className={styles.footerLinkStrong} onClick={() => navigate('/login')}>
          Sign in →
        </button>
      </p>
    </AuthShell>
  )
}
