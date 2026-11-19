/**
 * Public shipment tracking — no auth required.
 *
 * Both /track and /track/:code render this component.
 * :code pre-fills the tracking code field; the user must still enter
 * their phone number before any data is shown (security requirement).
 */

import { useState, type JSX } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { publicTrackingApi, stageLabelFor, type PublicTrackingResult } from '../../api/customer'
import { Banner, Button, Field, PhoneField } from '../../design/components'
import styles from './customer.module.css'
import { formatDate } from '../../lib/format'

function TrackingTimeline({ result }: { result: PublicTrackingResult }): JSX.Element {
  return (
    <div className={styles.trackResult}>
      <div className={styles.trackResultHeader}>
        <div>
          <p className={styles.trackCode}>{result.tracking_code}</p>
          {result.company_name && (
            <p className={styles.trackCompany}>{result.company_name}</p>
          )}
        </div>
        <div style={{
          background: 'var(--color-primary-muted)',
          color: 'var(--color-primary)',
          padding: 'var(--space-2) var(--space-4)',
          borderRadius: 20,
          fontWeight: 700,
          fontSize: 'var(--text-md)',
          flexShrink: 0,
        }}>
          {stageLabelFor(result.current_stage)}
        </div>
      </div>

      {result.stage_history.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-md)' }}>
          No tracking events recorded yet. Check back soon.
        </p>
      ) : (
        <div className={styles.timeline}>
          {result.stage_history.map((ev, i) => {
            const isCurrent = i === result.stage_history.length - 1
            return (
              <div key={i} className={styles.timelineItem}>
                <div className={[
                  styles.timelineDot,
                  isCurrent ? styles.timelineDotCurrent : styles.timelineDotDone,
                ].join(' ')} />
                <div className={styles.timelineContent}>
                  <p className={styles.timelineStage}>{stageLabelFor(ev.stage)}</p>
                  <p className={styles.timelineDate}>{formatDate(ev.occurred_at)}</p>
                  {ev.notes && <p className={styles.timelineNotes}>{ev.notes}</p>}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
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

  async function handleTrack(): Promise<void> {
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

  return (
    <div className={styles.trackPage}>
      <h1 className={styles.trackTitle}>Track your shipment</h1>
      <p className={styles.trackSub}>Enter your tracking code and phone number to see your delivery status.</p>

      <div className={styles.trackForm}>
        <Field
          label="Tracking code"
          name="tracking_code"
          required
          placeholder="e.g. ACME-TRK-20260704-0001"
          value={trackingCode}
          onChange={(e) => { setTrackingCode(e.target.value); setResult(null) }}
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

        <Button
          variant="primary"
          loading={loading}
          disabled={!trackingCode.trim() || !phone.trim()}
          onClick={() => void handleTrack()}
        >
          Track shipment
        </Button>
      </div>

      {result && <TrackingTimeline result={result} />}
    </div>
  )
}
