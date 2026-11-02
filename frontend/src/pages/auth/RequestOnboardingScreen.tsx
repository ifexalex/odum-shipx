/**
 * Shipping-company onboarding request — the public entry point for a LOGISTICS
 * COMPANY (a tenant) to partner with ShipX.
 *
 * This is deliberately NOT customer sign-up (RegisterScreen / `/register/:slug`):
 *   - it is for companies/operators, not their customers;
 *   - it creates NO account and NO password — it records a lead
 *     (POST /v1/onboarding-requests), and a platform admin provisions the tenant;
 *   - the copy + the "are you a customer?" off-ramp keep the two from being confused.
 */
import { useState, type FormEvent, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { companyOnboardingApi } from '../../api/customer'
import { Banner, Button, CountrySelect, Field, Icon, PhoneField } from '../../design/components'
import { AuthShell, FormHead } from './AuthShell'
import styles from './LoginScreen.module.css'

export function RequestOnboardingScreen(): JSX.Element {
  const navigate = useNavigate()
  const [companyName, setCompanyName] = useState('')
  const [contactName, setContactName] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [contactPhone, setContactPhone] = useState('')
  const [originCountry, setOriginCountry] = useState('China')
  const [destinationCountry, setDestinationCountry] = useState('Nigeria')
  const [monthlyVolume, setMonthlyVolume] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await companyOnboardingApi.requestOnboarding({
        company_name: companyName,
        contact_name: contactName,
        contact_email: contactEmail,
        ...(contactPhone.trim() ? { contact_phone: contactPhone } : {}),
        origin_country: originCountry,
        destination_country: destinationCountry,
        ...(monthlyVolume.trim() ? { monthly_volume: monthlyVolume } : {}),
        ...(notes.trim() ? { notes } : {}),
      })
      setDone(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not submit your request. Please try again.')
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
          <h2 className={styles.formTitle} style={{ marginBottom: 8 }}>Request received.</h2>
          <p className={styles.formSub} style={{ marginBottom: 24 }}>
            Thanks, <strong>{companyName}</strong>. Our team will review your details and reach out to{' '}
            <strong>{contactEmail}</strong> to set up your workspace. No account has been created yet —
            we&apos;ll provision it with you.
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
        title="Partner with ShipX"
        sub="For shipping &amp; logistics companies — request onboarding to run your China→Nigeria operations on ShipX. This is a request; our team will follow up to set you up."
      />

      <div style={{ marginBottom: 20 }}>
        <Banner variant="info" title="Are you a customer?">
          If you&apos;re a customer trying to track a shipment or access your account, this isn&apos;t the
          page — use the link your shipping company gave you, or{' '}
          <button type="button" className={styles.link} onClick={() => navigate('/login')}>sign in</button>.
        </Banner>
      </div>

      {error && (
        <div style={{ marginBottom: 20 }}>
          <Banner variant="error" title="Couldn't submit">{error}</Banner>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <Field
          label="Company name"
          name="company_name"
          placeholder="Acme Freight Ltd"
          value={companyName}
          onChange={(e) => setCompanyName(e.target.value)}
          required
        />
        <Field
          label="Your name"
          name="contact_name"
          placeholder="Ada Obi"
          value={contactName}
          onChange={(e) => setContactName(e.target.value)}
          required
        />
        <Field
          label="Work email"
          type="email"
          icon="mail"
          name="contact_email"
          placeholder="you@yourcompany.com"
          value={contactEmail}
          onChange={(e) => setContactEmail(e.target.value)}
          autoComplete="email"
          required
        />
        <PhoneField
          label="Phone number"
          name="contact_phone"
          value={contactPhone}
          onChange={setContactPhone}
          optional
        />
        <div style={{ display: 'flex', gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <CountrySelect
              label="Origin"
              name="origin_country"
              value={originCountry}
              onChange={setOriginCountry}
            />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <CountrySelect
              label="Destination"
              name="destination_country"
              value={destinationCountry}
              onChange={setDestinationCountry}
            />
          </div>
        </div>
        <Field
          label="Approx. monthly volume"
          name="monthly_volume"
          placeholder="e.g. 2 containers / 40 CBM"
          value={monthlyVolume}
          onChange={(e) => setMonthlyVolume(e.target.value)}
          optional
        />
        <Field
          label="Anything else?"
          name="notes"
          placeholder="Tell us about your operation"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          optional
        />

        <Button type="submit" variant="accent" size="lg" full loading={submitting}>
          Request onboarding
        </Button>
      </form>

      <p className={styles.footerLine} style={{ marginTop: 20 }}>
        Already set up?{' '}
        <button type="button" className={styles.footerLinkStrong} onClick={() => navigate('/login')}>
          Sign in →
        </button>
      </p>
    </AuthShell>
  )
}
