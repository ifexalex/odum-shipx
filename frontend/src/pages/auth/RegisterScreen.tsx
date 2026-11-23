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
 * The confirmation never says whether the email was already registered: the
 * backend answers both the same way (audit SEC-04), so a visitor cannot use this
 * form to find out who is a customer of a given company.
 *
 * Ground-truth fix: this used to resolve the tenant from the Host header,
 * which is unreachable in practice (the frontend calls a shared
 * VITE_API_BASE_URL, so the backend only ever sees API Gateway's own host).
 * The route is now company-specific — `/register/:slug` — and the slug is
 * sent explicitly; no more hostname guessing.
 */
import { useState, type FormEvent, type JSX } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { registerApi } from '../../api/customer'
import { Banner, Button, Check, Field, Icon, Modal, PhoneField, Pressable, CheckboxField } from '../../design/components'
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
  // Nothing ticked until the person ticks it: a pre-ticked box is not consent (FD-30, SEC-01).
  const [channels, setChannels] = useState<string[]>([])
  const [agreed, setAgreed] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [legalModal, setLegalModal] = useState<'terms' | 'privacy' | null>(null)

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
      // There is no "this email already exists" case to report: the backend answers a taken email
      // exactly like a new one (and emails its owner), so the form cannot be used to find out who
      // has an account.
      setError(err instanceof ApiError ? err.message : 'Registration failed. Please try again.')
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
          <h2 className={styles.formTitle} style={{ marginBottom: 'var(--space-2)' }}>Check your email.</h2>
          <p className={styles.formSub} style={{ marginBottom: 'var(--space-6)' }}>
            We&apos;ve sent a message to <strong>{email}</strong>. If this is your first time, it has a{' '}
            <strong>temporary password</strong>: sign in with it and you&apos;ll be asked to choose your own.
            If you already have an account, it tells you so, with a link to sign in.
          </p>
          <Banner variant="info" title="Didn't receive the email?">
            Check your spam folder. A temporary password expires in 7 days.
          </Banner>
          <div style={{ marginTop: 'var(--space-6)' }}>
            <Button variant="primary" size="lg" full onClick={() => navigate('/login')}>
              Back to sign in
            </Button>
          </div>
        </div>
      </AuthShell>
    )
  }

  if (!slug) {
    return (
      <AuthShell>
        <FormHead
          title="Create your customer account"
          sub="For customers of a shipping company: track your shipments and pay your invoices."
        />
        <div style={{ marginBottom: 'var(--space-6)' }}>
          {/* Only why the form cannot be sent from here; companies are no longer sent to this page (FD-30). */}
          <Banner variant="info" title="Use your shipping company's link">
            Sign up through the link your shipping company sent you, or wait for their invite. It connects your
            account to them.
          </Banner>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <Button variant="primary" size="lg" full onClick={() => navigate('/login')}>
            Back to sign in
          </Button>
          <Button variant="secondary" size="lg" full onClick={() => navigate('/track')}>
            Track a shipment without an account
          </Button>
        </div>
        <p className={styles.footerLine} style={{ marginTop: 'var(--space-5)' }}>
          Running a shipping company?{' '}
          <Link to="/get-started" className={styles.link}>Request access</Link>
        </p>
      </AuthShell>
    )
  }

  return (
    <AuthShell>
      <FormHead
        title="Create your customer account"
        sub="For customers of a shipping company: track your shipments and pay your invoices."
      />

      {error && (
        <div style={{ marginBottom: 'var(--space-5)' }}>
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

        <div style={{ marginBottom: 'var(--space-4)' }}>
          <span style={{ display: 'block', fontWeight: 500, fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)', marginBottom: 'var(--space-1)' }}>
            Send me optional messages via
          </span>
          <span style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)', marginBottom: 'var(--space-2)', lineHeight: 'var(--leading-body)' }}>
            Announcements and offers. Updates about your shipments, invoices and claims, and account emails, are always sent.
          </span>
          <div style={{ display: 'flex', gap: 'var(--space-4)' }}>
            {CHANNELS.map(({ key, label }) => (
              <CheckboxField key={key} className={styles.rememberLabel} label={label} checked={channels.includes(key)} onChange={() => toggleChannel(key)} />
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--space-2)', margin: 'var(--space-2) 0 var(--space-6)' }}>
          <Check label="I agree to the Terms of Service and Privacy Policy" checked={agreed} onChange={setAgreed} />
          <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)', lineHeight: 'var(--leading-body)' }}>
            I agree to the{' '}
            <Pressable className={styles.link} onClick={() => setLegalModal('terms')}>Terms of Service</Pressable>
            {' '}and{' '}
            <Pressable className={styles.link} onClick={() => setLegalModal('privacy')}>Privacy Policy</Pressable>.
          </span>
        </div>

        <Button type="submit" variant="accent" size="lg" full loading={submitting} disabled={!agreed}>
          Create account
        </Button>
      </form>

      <p className={styles.footerLine} style={{ marginTop: 'var(--space-5)' }}>
        Already have an account?{' '}
        <Link to="/login" className={styles.footerLinkStrong}>Sign in <Icon name="arrowright" size={12} /></Link>
      </p>
      <p className={styles.footerLine}>
        Running a shipping company?{' '}
        <Link to="/get-started" className={styles.link}>Request access</Link>
      </p>

      <Modal
        open={legalModal !== null}
        onClose={() => setLegalModal(null)}
        title={legalModal === 'terms' ? 'Terms of Service' : 'Privacy Policy'}
        size="sm"
        footer={
          <Button variant="primary" onClick={() => setLegalModal(null)}>
            Close
          </Button>
        }
      >
        {legalModal === 'terms' ? (
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)', lineHeight: 'var(--leading-body)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            <p style={{ margin: 0 }}>
              Your ShipX customer account gives you access to shipment tracking, invoices, release notes, and
              claims managed by your shipping company.
            </p>
            <p style={{ margin: 0 }}>
              Keep your sign-in credentials and warehouse pickup codes confidential. Freight rates, customs clearance,
              storage fees, and delivery terms are set directly by your shipping company.
            </p>
          </div>
        ) : (
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)', lineHeight: 'var(--leading-body)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            <p style={{ margin: 0 }}>
              We collect your name, email address, phone number, and optional WhatsApp number solely to manage
              your shipments, billing, release notes, and account security with your shipping company.
            </p>
            <p style={{ margin: 0 }}>
              Transactional shipment and invoice notifications are sent automatically. Optional announcements and
              offers are only sent via channels you explicitly opt into, and you may update your preferences or
              request data export/erasure (NDPR / GDPR) at any time.
            </p>
          </div>
        )}
      </Modal>
    </AuthShell>
  )
}
