import { useCallback, useEffect, useState, type JSX } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import {
  claimsApi,
  presignedUploadApi,
  type Claim,
  type DamageClaimStatus,
  type InspectionMethod,
  type ResolutionType,
  type ResolveClaimInput,
} from '../../api/claims'
import {
  canResolveClaim,
  canStartInspection,
  CLAIM_STATUS_ORDER,
  isTerminalClaimStatus,
} from '../../api/claimsRules'
import { useSession } from '../../auth/useSession'
import { Action, Badge, Banner, Button, Card, Field, Kvp, Mono, type BadgeVariant } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import { EvidenceUploader } from './EvidenceUploader'
import styles from './ClaimDetail.module.css'

const STATUS_VARIANT: Record<DamageClaimStatus, BadgeVariant> = {
  filed: 'warning',
  under_inspection: 'warning',
  inspection_complete: 'warning',
  pending_resolution: 'warning',
  resolved: 'success',
  closed: 'neutral',
}

function statusLabel(s: DamageClaimStatus): string {
  switch (s) {
    case 'filed': return 'Filed'
    case 'under_inspection': return 'Under inspection'
    case 'inspection_complete': return 'Inspection complete'
    case 'pending_resolution': return 'Pending resolution'
    case 'resolved': return 'Resolved'
    case 'closed': return 'Closed'
  }
}

// ---------------------------------------------------------------------------
// StartInspectionModal
// ---------------------------------------------------------------------------

interface StartInspectionModalProps {
  onCancel: () => void
  onSuccess: (updated: Claim) => void
  claimId: string
}

const INSPECTION_METHODS: { value: InspectionMethod; label: string }[] = [
  { value: 'delegate_visit', label: 'Delegate visit — staff inspects in person' },
  { value: 'customer_evidence', label: 'Customer evidence — photos/video provided' },
]

function StartInspectionModal({ onCancel, onSuccess, claimId }: StartInspectionModalProps): JSX.Element {
  const [method, setMethod] = useState<InspectionMethod>('delegate_visit')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [evidenceUploaded, setEvidenceUploaded] = useState(false)

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const updated = await claimsApi.startInspection(claimId, { inspection_method: method })
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start inspection.')
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit = method === 'delegate_visit' || evidenceUploaded

  return (
    <div className={styles.overlay} onClick={onCancel}>
      <div className={styles.panel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.panelTitle}>Start inspection</h3>
        {error && <div className={styles.panelBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}
        <div className={styles.selectField}>
          <label className={styles.selectLabel}>Inspection method <span className={styles.required}>*</span></label>
          <select className={styles.select} value={method} onChange={(e) => setMethod(e.target.value as InspectionMethod)}>
            {INSPECTION_METHODS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </div>
        {method === 'customer_evidence' && (
          <div className={styles.evidenceSection}>
            <label className={styles.selectLabel}>Evidence files <span className={styles.required}>*</span></label>
            <EvidenceUploader
              getPresignedUrl={(f) => presignedUploadApi.getUrl(claimId, f.name, f.type)}
              onUploaded={() => setEvidenceUploaded(true)}
              disabled={submitting}
            />
          </div>
        )}
        <div className={styles.actions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            Start inspection
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ResolveClaimModal
// ---------------------------------------------------------------------------

interface ResolveClaimModalProps {
  onCancel: () => void
  onSuccess: (updated: Claim) => void
  claimId: string
  role: string
}

// Prototype 8.2 ResolutionPick — 2×2 radio-card grid, not a dropdown.
const RESOLUTION_TYPES: { value: ResolutionType; title: string; sub: string }[] = [
  { value: 'refund', title: 'Refund', sub: 'Cash refund to customer' },
  { value: 'discount', title: 'Discount', sub: 'Reduce next billing' },
  { value: 'compensation', title: 'Compensation', sub: 'Goodwill payment' },
  { value: 'no_action', title: 'No action', sub: 'Claim not actionable' },
]

function ResolutionPick({ title, sub, current, onClick }: { title: string; sub: string; current: boolean; onClick: () => void }): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 10, textAlign: 'left',
        border: `${current ? 2 : 1}px solid ${current ? 'var(--color-primary)' : 'var(--color-line-soft)'}`,
        borderRadius: 10, padding: 12, cursor: 'pointer',
        background: current ? 'var(--color-primary-tint)' : 'var(--color-surface)',
      }}
    >
      <span style={{
        width: 18, height: 18, borderRadius: '50%', flexShrink: 0, marginTop: 1,
        border: `${current ? 5 : 1.5}px solid ${current ? 'var(--color-primary)' : 'var(--color-line)'}`,
        background: 'var(--color-surface)',
      }} />
      <span>
        <span style={{ display: 'block', fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 13 }}>{title}</span>
        <span style={{ display: 'block', fontSize: 11, color: 'var(--color-ink-3)', marginTop: 2 }}>{sub}</span>
      </span>
    </button>
  )
}

// Threshold fetched from tenant config at runtime; use backend's default as UI hint.
const _STAFF_LIMIT_HINT_NGN = 25_000

function ResolveClaimModal({ onCancel, onSuccess, claimId, role }: ResolveClaimModalProps): JSX.Element {
  const [resolutionType, setResolutionType] = useState<ResolutionType>('no_action')
  const [amountNgn, setAmountNgn] = useState('')
  const [discountPct, setDiscountPct] = useState('')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const needsAmount = resolutionType === 'refund' || resolutionType === 'compensation'
  const needsDiscount = resolutionType === 'discount'

  const isStaff = role === 'nigeria_office_staff'
  const enteredAmount = Number(amountNgn)
  const likelyNeedsAdminApproval =
    isStaff && needsAmount && enteredAmount > 0 && enteredAmount > _STAFF_LIMIT_HINT_NGN

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const body: ResolveClaimInput = { resolution_type: resolutionType, reason }
      if (needsAmount && amountNgn) body.amount_ngn = amountNgn
      if (needsDiscount && discountPct) body.discount_percentage = discountPct
      const updated = await claimsApi.resolve(claimId, body)
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not resolve claim.')
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit = reason.trim().length > 0 && !submitting

  return (
    <div className={styles.overlay} onClick={onCancel}>
      <div className={styles.panel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.panelTitle}>Resolve claim</h3>
        {error && <div className={styles.panelBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}
        {likelyNeedsAdminApproval && (
          <div className={styles.panelBanner}>
            <Banner variant="warning">
              This amount exceeds the staff approval limit — a tenant admin must resolve refunds above the
              configured threshold. Submit anyway and the server will enforce the rule.
            </Banner>
          </div>
        )}
        <div>
          <label className={styles.selectLabel}>Resolution type <span className={styles.required}>*</span></label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10, marginTop: 8, marginBottom: 4 }}>
            {RESOLUTION_TYPES.map((r) => (
              <ResolutionPick
                key={r.value}
                title={r.title}
                sub={r.sub}
                current={resolutionType === r.value}
                onClick={() => setResolutionType(r.value)}
              />
            ))}
          </div>
        </div>
        {needsAmount && (
          <Field label="Amount (₦)" name="amount_ngn" type="number" placeholder="e.g. 25000"
            value={amountNgn} onChange={(e) => setAmountNgn(e.target.value)} />
        )}
        {resolutionType === 'refund' && enteredAmount > 0 && (
          <Banner variant="info" title="Refund record generated automatically">
            Confirming creates a refund of ₦{enteredAmount.toLocaleString()} in <strong>Pending Accounts Review</strong> status.
          </Banner>
        )}
        {needsDiscount && (
          <Field label="Discount (%)" name="discount_pct" type="number" placeholder="e.g. 10"
            value={discountPct} onChange={(e) => setDiscountPct(e.target.value)} />
        )}
        <Field label="Resolution reason" name="reason" required multiline
          placeholder="Explain the resolution decision…"
          value={reason} onChange={(e) => setReason(e.target.value)} />
        <div className={styles.actions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} disabled={!canSubmit} onClick={() => void handleSubmit()}>
            Resolve claim
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Status stepper
// ---------------------------------------------------------------------------

function StatusStepper({ current }: { current: DamageClaimStatus }): JSX.Element {
  const currentIdx = CLAIM_STATUS_ORDER.indexOf(current)
  return (
    <div className={styles.stepper}>
      {CLAIM_STATUS_ORDER.map((s, i) => (
        <div key={s} className={[
          styles.step,
          i < currentIdx ? styles.stepDone : '',
          i === currentIdx ? styles.stepActive : '',
        ].join(' ')}>
          <div className={styles.stepDot} />
          <span className={styles.stepLabel}>{statusLabel(s)}</span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function ClaimDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const { session } = useSession()
  const role = session?.role ?? 'nigeria_office_staff'

  const stateClaim = (location.state as { claim?: Claim } | null)?.claim ?? null
  const [claim, setClaim] = useState<Claim | null>(stateClaim)
  const [loading, setLoading] = useState(stateClaim === null)
  const [error, setError] = useState<string | null>(null)
  const [showInspect, setShowInspect] = useState(false)
  const [showResolve, setShowResolve] = useState(false)

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const result = await claimsApi.get(id)
      setClaim(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load this claim.')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    if (stateClaim === null) void load()
  }, [load, stateClaim])

  if (loading) return <div className={styles.loadingState}>Loading claim…</div>
  if (error || !claim) {
    return (
      <div className={styles.loadingState}>
        <Banner variant="error" title="Couldn't load this claim">{error ?? 'Not found.'}</Banner>
      </div>
    )
  }

  const r = role as Parameters<typeof canStartInspection>[1]

  return (
    <div>
      {/* Hero */}
      <div className={styles.hero}>
        <div className={styles.heroLeft}>
          <div>
            <div className={styles.heroTitleRow}>
              <h1 className={styles.heroTitle}>Damage claim</h1>
              <Badge variant={STATUS_VARIANT[claim.status]}>{statusLabel(claim.status)}</Badge>
            </div>
            <div className={styles.heroMeta}>
              <Mono>{claim.id}</Mono>
              <span className={styles.dot}>·</span>
              <span>Filed {claim.created_at.slice(0, 10)}</span>
            </div>
          </div>
        </div>
        {!isTerminalClaimStatus(claim.status) && (
          <div className={styles.heroActions}>
            {canStartInspection(claim, r) && (
              <Action variant="primary" onClick={() => setShowInspect(true)}>
                Start inspection
              </Action>
            )}
            {canResolveClaim(claim, r) && (
              <Action variant="success" onClick={() => setShowResolve(true)}>
                Resolve claim
              </Action>
            )}
          </div>
        )}
      </div>

      {/* Status stepper */}
      <div className={styles.section}>
        <SectionHead title="Progress" />
        <Card padding={20}>
          <StatusStepper current={claim.status} />
        </Card>
      </div>

      {/* Claim context */}
      {(claim.description || claim.container_id || claim.customer_id) && (
        <div className={styles.section}>
          <SectionHead title="Claim details" />
          <Card padding={20}>
            {claim.description && <Kvp label="Description" value={claim.description} />}
            {claim.container_id && <Kvp label="Container ID" value={<Mono>{claim.container_id}</Mono>} />}
            {claim.customer_id && <Kvp label="Customer ID" value={<Mono>{claim.customer_id}</Mono>} divider={false} />}
          </Card>
        </div>
      )}

      {/* Cartons affected */}
      <div className={styles.section}>
        <SectionHead title="Cartons affected" />
        <Card padding={20}>
          {claim.cartons_affected.length > 0 ? (
            <div className={styles.cartonList}>
              {claim.cartons_affected.map((tag) => (
                <span key={tag} className={styles.cartonTag}><Mono>{tag}</Mono></span>
              ))}
            </div>
          ) : (
            <span className={styles.emptyNote}>No specific carton tags recorded.</span>
          )}
        </Card>
      </div>

      {/* Evidence upload — available while claim is not terminal */}
      {!isTerminalClaimStatus(claim.status) && (
        <div className={styles.section}>
          <SectionHead title="Attach evidence" sub="Upload photos, videos, or PDF documents (JPEG · PNG · PDF, max 10 MB each)" />
          <Card padding={20}>
            <EvidenceUploader getPresignedUrl={(f) => presignedUploadApi.getUrl(claim.id, f.name, f.type)} onUploaded={() => { /* evidence logged server-side */ }} />
          </Card>
        </div>
      )}

      <div className={styles.backLink}>
        <Button variant="ghost" icon="arrowleft" onClick={() => navigate('/claims')}>Back to claims</Button>
      </div>

      {showInspect && (
        <StartInspectionModal
          claimId={claim.id}
          onCancel={() => setShowInspect(false)}
          onSuccess={(updated) => { setShowInspect(false); setClaim(updated) }}
        />
      )}
      {showResolve && (
        <ResolveClaimModal
          claimId={claim.id}
          role={role}
          onCancel={() => setShowResolve(false)}
          onSuccess={(updated) => { setShowResolve(false); setClaim(updated) }}
        />
      )}
    </div>
  )
}
