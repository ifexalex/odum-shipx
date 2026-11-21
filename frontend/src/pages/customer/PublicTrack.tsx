/**
 * Public shipment tracking — no auth required.
 *
 * Both /track and /track/:code render this component.
 * :code pre-fills the tracking code field; the user must still enter
 * their phone number before any data is shown (security requirement).
 *
 * FD-28: the page a customer reaches from an SMS link has a brand header and footer like the sign-in pages. It shows
 * ShipX until a lookup succeeds, then the shipping company's name and colour (returned only once the code and phone
 * match, so a code alone reveals nothing). The result is the shared Stepper, with a "Sign in for full details" link.
 */

import { useState, type FormEvent, type JSX } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { PUBLIC_STAGE_ORDER, publicTrackingApi, stageLabelFor, type PublicTrackingResult } from '../../api/customer'
import { loginUrlFor } from '../../auth/returnPath'
import { Banner, Button, Field, KolaMark, Mono, PhoneField, ShipxWordmark, Stepper } from '../../design/components'
import { ThemeProvider } from '../../design/ThemeProvider'
import { formatDate } from '../../lib/format'
import styles from './PublicTrack.module.css'

/** Where "Sign in for full details" lands: the customer's own shipments, after signing in. */
const SIGN_IN_FOR_DETAILS = loginUrlFor('/my-shipments')

function TrackingResult({ result }: { result: PublicTrackingResult }): JSX.Element {
  const currentIndex = PUBLIC_STAGE_ORDER.indexOf(result.current_stage as (typeof PUBLIC_STAGE_ORDER)[number])
  // The date each stage was reached, from the latest event for it.
  const reachedOn = new Map<string, string>()
  for (const event of result.stage_history) reachedOn.set(event.stage, event.occurred_at)
  const notes = result.stage_history.filter((event) => event.notes).slice(-3).reverse()

  return (
    <section className={styles.result} aria-labelledby="track-result-heading">
      <div className={styles.resultHead}>
        <div>
          <h2 id="track-result-heading" className={styles.resultTitle}>
            {stageLabelFor(result.current_stage)}
          </h2>
          <p className={styles.resultMeta}>
            <Mono>{result.tracking_code}</Mono>
            {result.company_name && <> · Shipped with {result.company_name}</>}
          </p>
        </div>
      </div>

      {currentIndex >= 0 ? (
        <Stepper
          label="Shipment progress"
          steps={PUBLIC_STAGE_ORDER.map((stage) => ({
            key: stage,
            label: stageLabelFor(stage),
            sub: reachedOn.has(stage) ? formatDate(reachedOn.get(stage)) : undefined,
          }))}
          current={currentIndex}
          complete={result.current_stage === 'picked_up'}
        />
      ) : (
        <p className={styles.muted}>No tracking events recorded yet. Check back soon.</p>
      )}

      {notes.length > 0 && (
        <ul className={styles.notes} aria-label="Latest updates">
          {notes.map((event) => (
            <li key={`${event.stage}-${event.occurred_at}`}>
              <span className={styles.noteDate}>{formatDate(event.occurred_at)}</span> {event.notes}
            </li>
          ))}
        </ul>
      )}

      <p className={styles.signIn}>
        Cartons, invoices and release notes are in your account. <Link to={SIGN_IN_FOR_DETAILS}>Sign in for full details</Link>
      </p>
    </section>
  )
}

export function PublicTrack(): JSX.Element {
  const { code: prefilledCode } = useParams<{ code?: string }>()
  const navigate = useNavigate()

  const [trackingCode, setTrackingCode] = useState(prefilledCode ?? '')
  const [phone, setPhone] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<PublicTrackingResult | null>(null)

  async function handleTrack(event?: FormEvent<HTMLFormElement>): Promise<void> {
    event?.preventDefault()
    if (!trackingCode.trim() || !phone.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await publicTrackingApi.lookup(trackingCode.trim(), phone.trim())
      setResult(data)
      // Update URL to /track/:code without re-mounting
      if (!prefilledCode) navigate(`/track/${encodeURIComponent(trackingCode.trim())}`, { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setError('No shipment found with that tracking code and phone number. Check both and try again.')
      } else {
        setError(err instanceof ApiError ? err.message : 'Could not fetch tracking data. Try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  const company = result?.company_name ?? null

  return (
    <ThemeProvider primaryColor={result?.brand_color ?? null}>
      <div className={styles.page}>
        <header className={styles.header}>
          {company ? (
            <span className={styles.company}>
              <span className={styles.companyMark} aria-hidden="true" />
              {company}
            </span>
          ) : (
            <Link to="/" className={styles.brand} aria-label="ShipX home">
              <KolaMark size={26} color="var(--color-primary-bright)" />
              <ShipxWordmark size={20} color="var(--color-ink)" />
            </Link>
          )}
          <Link to={SIGN_IN_FOR_DETAILS} className={styles.headerLink}>
            Sign in
          </Link>
        </header>

        <main className={styles.main}>
          <h1 className={styles.title}>Track your shipment</h1>
          <p className={styles.sub}>Enter your tracking code and phone number to see your delivery status.</p>

          <form className={styles.form} onSubmit={(e) => void handleTrack(e)}>
            <Field
              label="Tracking code"
              name="tracking_code"
              required
              placeholder="e.g. ACME-TRK-20260704-0001"
              value={trackingCode}
              onChange={(e) => {
                setTrackingCode(e.target.value)
                setResult(null)
              }}
            />
            <PhoneField
              label="Phone number"
              name="phone"
              required
              value={phone}
              onChange={setPhone}
              helper="The number your shipping company has on file for you."
            />

            {error && <Banner variant="error">{error}</Banner>}

            <Button type="submit" variant="primary" size="lg" full loading={loading} disabled={!trackingCode.trim() || !phone.trim()}>
              Track shipment
            </Button>
          </form>

          {result && <TrackingResult result={result} />}
        </main>

        <footer className={styles.footer}>
          <span>{company ? <>Tracking for {company}, powered by ShipX</> : <>ShipX · China to Nigeria cargo</>}</span>
          <nav aria-label="Footer" className={styles.footerLinks}>
            <Link to={SIGN_IN_FOR_DETAILS}>Sign in</Link>
            <Link to="/">About ShipX</Link>
          </nav>
        </footer>
      </div>
    </ThemeProvider>
  )
}
