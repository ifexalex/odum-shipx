/**
 * Customer damage claim filing wizard — 3 steps: Details → Evidence → Review.
 *
 * Evidence upload uses EvidenceUploader (same component as staff ClaimDetail).
 * presignedUploadApi is wired AFTER the claim is created (we need a claim_id).
 *
 * Step 1 picks from the customer's own arrived shipments (a dropdown, not a
 * free-text container field) — damage/loss can't be assessed on cargo that's
 * still loading or at sea, so anything not yet arrived is never offered here.
 * `services/claims/service.py::file_claim` enforces the same rule server-side
 * (`_PRE_ARRIVAL_STATUSES`) — this is the UX half of that fix, found live
 * (2026-09-06) after a claim was filed against a container still `loading`.
 */

import { useEffect, useRef, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { claimsApi, presignedUploadApi, type FileDamageClaimInput } from '../../api/claims'
import { packingListApi, type PackingList } from '../../api/packingList'
import { type UploadedEvidence } from '../nigeria/EvidenceUploader'
import { Banner, Button, Field, Select, LinesSkeleton } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import { EvidenceUploader } from '../nigeria/EvidenceUploader'
import styles from './customer.module.css'
import { statusLabel } from '../../design/status'
import { toast } from '../../design/toast'

type Step = 'details' | 'evidence' | 'review'

// Mirrors services/claims/service.py's `_PRE_ARRIVAL_STATUSES` complement —
// a claim can only be filed once the container has physically arrived.
const ARRIVED_STATUSES: ReadonlySet<string> = new Set(['arrived', 'customs_clearance', 'cleared', 'at_warehouse', 'fully_released'])

export function MyClaimsNew(): JSX.Element {
  const navigate = useNavigate()
  const idempotencyKey = useRef(crypto.randomUUID())

  const [step, setStep] = useState<Step>('details')
  const [shipments, setShipments] = useState<PackingList[] | null>(null)
  const [shipmentsError, setShipmentsError] = useState<string | null>(null)
  const [selectedShipmentId, setSelectedShipmentId] = useState('')
  const [description, setDescription] = useState('')
  const [cartonsRaw, setCartonsRaw] = useState('')
  const [claimId, setClaimId] = useState<string | null>(null)
  const [uploadedEvidence, setUploadedEvidence] = useState<UploadedEvidence[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  useEffect(() => {
    let active = true
    packingListApi
      .list({ limit: 100 })
      .then((result) => {
        if (!active) return
        setShipments(result.data)
      })
      .catch((err: unknown) => {
        if (!active) return
        setShipmentsError(err instanceof ApiError ? err.message : 'Could not load your shipments.')
        setShipments([])
      })
    return () => {
      active = false
    }
  }, [])

  const arrivedShipments = (shipments ?? []).filter(
    (pl) => pl.container_status && ARRIVED_STATUSES.has(pl.container_status),
  )
  const selectedShipment = arrivedShipments.find((pl) => pl.id === selectedShipmentId) ?? null

  const cartonsAffected = cartonsRaw.split(/[\n,\s]+/).map((t) => t.trim()).filter(Boolean)

  async function handleCreateClaim(): Promise<void> {
    if (!selectedShipment?.container_number) return
    setSubmitting(true)
    setError(null)
    try {
      const body: FileDamageClaimInput = {
        container_id: selectedShipment.container_number,
        description,
        cartons_affected: cartonsAffected.length > 0 ? cartonsAffected : undefined,
      }
      const claim = await claimsApi.file(body, idempotencyKey.current)
      toast.success('Claim filed', claim.reference ?? undefined)
      setClaimId(claim.id)
      setStep('evidence')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not file your claim.')
    } finally {
      setSubmitting(false)
    }
  }

  function handleDone(): void {
    setDone(true)
    setTimeout(() => navigate('/my-claims'), 1500)
  }

  if (done) {
    return (
      <div className={styles.resultPage}>
        <div className={styles.resultIcon}>✓</div>
        <h1 className={styles.resultTitle}>Claim filed!</h1>
        <p className={styles.resultBody}>Our team will contact you once we begin the inspection.</p>
      </div>
    )
  }

  const STEP_LABELS: Record<Step, string> = {
    details: 'Step 1 of 3 — Details',
    evidence: 'Step 2 of 3 — Evidence',
    review: 'Step 3 of 3 — Review',
  }

  return (
    <div className={styles.page}>
      <PageHeader title="File a Damage Claim" />

      <p className={styles.stepIndicator}>{STEP_LABELS[step]}</p>

      {/* Step 1: Details */}
      {step === 'details' && (
        <div className={styles.formCard}>
          {error && <Banner variant="error" title="Could not file claim">{error}</Banner>}
          {shipmentsError && <Banner variant="error" title="Could not load your shipments">{shipmentsError}</Banner>}

          {shipments === null ? (
            <LinesSkeleton label="Loading your shipments" />
          ) : arrivedShipments.length === 0 ? (
            <Banner variant="info" title="Nothing to claim against yet">
              A claim can only be filed once a shipment has arrived in Nigeria — damage or loss
              can't be assessed while cargo is still loading or at sea. Check back once your
              shipment shows as arrived on{' '}
              <a href="/my-shipments" onClick={(e) => { e.preventDefault(); navigate('/my-shipments') }}>
                My Shipments
              </a>.
            </Banner>
          ) : (
            <div className={styles.selectField}>
              <Select label="Which shipment?"
                id="claim-shipment"
                value={selectedShipmentId}
                onChange={(e) => setSelectedShipmentId(e.target.value)}
              >
                <option value="" disabled>Select an arrived shipment…</option>
                {arrivedShipments.map((pl) => (
                  <option key={pl.id} value={pl.id}>
                    {pl.reference ?? pl.id.slice(0, 8)} — Container {pl.container_number ?? '—'}
                    {' '}({statusLabel('container', pl.container_status ?? '', 'customer')})
                  </option>
                ))}
              </Select>
            </div>
          )}

          {arrivedShipments.length > 0 && (
            <>
              <Field
                label="Description of damage"
                name="description"
                required
                multiline
                placeholder="Describe what was damaged, how it was found, and estimated extent…"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
              <Field
                label="Carton tags affected"
                name="cartons"
                multiline
                optional
                placeholder={'One per line, or comma-separated\ne.g. ACME-001-001, ACME-001-002'}
                value={cartonsRaw}
                onChange={(e) => setCartonsRaw(e.target.value)}
              />
            </>
          )}
          <div className={styles.formActions}>
            <Button variant="ghost" onClick={() => navigate('/my-claims')}>
              {arrivedShipments.length > 0 ? 'Cancel' : 'Back to My Shipments'}
            </Button>
            {arrivedShipments.length > 0 && (
              <Button
                variant="primary"
                loading={submitting}
                disabled={!selectedShipmentId || !description.trim()}
                onClick={() => void handleCreateClaim()}
              >
                Next: Add evidence
              </Button>
            )}
          </div>
        </div>
      )}

      {/* Step 2: Evidence */}
      {step === 'evidence' && claimId && (
        <div className={styles.formCard}>
          <Banner variant="info">
            Attach photos or videos of the damage to support your claim. You can attach up to 10 files.
          </Banner>
          <EvidenceUploader
            getPresignedUrl={(f) => presignedUploadApi.getUrl(claimId, f.name, f.type, f.size)}
            confirmUpload={(evidenceId) => presignedUploadApi.confirm(claimId, evidenceId)}
            onUploaded={(ev) => setUploadedEvidence((prev) => [...prev, ev])}
          />
          <div className={styles.formActions}>
            <Button variant="ghost" onClick={() => setStep('review')}>Skip — add later</Button>
            <Button
              variant="primary"
              onClick={() => setStep('review')}
            >
              {uploadedEvidence.length > 0 ? `Next: Review (${uploadedEvidence.length} file(s))` : 'Next: Review'}
            </Button>
          </div>
        </div>
      )}

      {/* Step 3: Review */}
      {step === 'review' && (
        <div className={styles.formCard}>
          <Banner variant="success">
            Your claim has been filed. Review the details below and submit.
          </Banner>
          <div style={{ fontSize: 'var(--text-md)', lineHeight: 'var(--leading-body)' }}>
            <p><strong>Shipment:</strong> {selectedShipment?.reference ?? selectedShipment?.id.slice(0, 8)} — Container {selectedShipment?.container_number ?? '—'}</p>
            <p><strong>Description:</strong> {description}</p>
            {cartonsAffected.length > 0 && (
              <p><strong>Cartons affected:</strong> {cartonsAffected.join(', ')}</p>
            )}
            <p><strong>Evidence files:</strong> {uploadedEvidence.length > 0 ? `${uploadedEvidence.length} file(s) uploaded` : 'None'}</p>
          </div>
          <div className={styles.formActions}>
            <Button variant="ghost" onClick={() => setStep('evidence')}>Back</Button>
            <Button variant="primary" onClick={handleDone}>
              Done — view my claims
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
