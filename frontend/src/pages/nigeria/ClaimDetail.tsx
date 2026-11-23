import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import {
  claimsApi,
  presignedUploadApi,
  type Claim,
  type ClaimEvidenceFile,
  type DamageClaimStatus,
  type InspectionMethod,
  type ResolutionType,
  type ResolveClaimInput,
} from '../../api/claims'
import type { RefundStatus } from '../../api/refunds'
import {
  canResolveClaim,
  canStartInspection,
  isTerminalClaimStatus,
} from '../../api/claimsRules'
import { claimKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { useSession } from '../../auth/useSession'
import { Action, Banner, Button, DialogGuard, Field, Kvp, Mono, StatusBadge, Pressable, Select, Stepper, PageSkeleton, ErrorState } from '../../design/components'
import { EvidenceUploader } from './EvidenceUploader'
import styles from './ClaimDetail.module.css'
import { formatCount, formatDate, formatNgn } from '../../lib/format'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'
import { PageHeader } from '../../shell/PageHeader'
import { RecordLink } from '../../shell/RecordLink'
import { claimProgress, claimSteps } from '../../design/steps'
import { toast } from '../../design/toast'
import { Section } from '../../shell/Section'
import { DetailPage } from '../../shell/DetailPage'

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
      toast.success('Inspection started', updated.reference ?? undefined)
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
      <DialogGuard onClose={onCancel} />
      <div className={styles.panel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.panelTitle}>Start inspection</h3>
        {error && <div className={styles.panelBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}
        <div className={styles.selectField}>
          <Select label="Inspection method" value={method} onChange={(e) => setMethod(e.target.value as InspectionMethod)}>
            {INSPECTION_METHODS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </Select>
        </div>
        {method === 'customer_evidence' && (
          <div className={styles.evidenceSection}>
            <label className={styles.selectLabel}>Evidence files</label>
            <EvidenceUploader
              getPresignedUrl={(f) => presignedUploadApi.getUrl(claimId, f.name, f.type, f.size)}
              confirmUpload={(evidenceId) => presignedUploadApi.confirm(claimId, evidenceId)}
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
    <Pressable
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 'var(--space-3)', textAlign: 'left',
        border: `${current ? 2 : 1}px solid ${current ? 'var(--color-primary)' : 'var(--color-line-soft)'}`,
        borderRadius: 'var(--radius-lg)', padding: 'var(--space-3)', cursor: 'pointer',
        background: current ? 'var(--color-primary-tint)' : 'var(--color-surface)',
      }}
    >
      <span style={{
        width: 18, height: 18, borderRadius: '50%', flexShrink: 0, marginTop: 'var(--space-0-5)',
        border: `${current ? 5 : 1.5}px solid ${current ? 'var(--color-primary)' : 'var(--color-line)'}`,
        background: 'var(--color-surface)',
      }} />
      <span>
        <span style={{ display: 'block', fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 'var(--text-sm)' }}>{title}</span>
        <span style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)', marginTop: 'var(--space-0-5)' }}>{sub}</span>
      </span>
    </Pressable>
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
  const enteredDiscount = Number(discountPct)
  const amountError =
    needsAmount && amountNgn.trim() !== '' && (!Number.isFinite(enteredAmount) || enteredAmount <= 0)
      ? 'Enter an amount greater than 0.'
      : undefined
  const discountError =
    needsDiscount && discountPct.trim() !== '' && (!Number.isFinite(enteredDiscount) || enteredDiscount <= 0 || enteredDiscount > 100)
      ? 'Enter a percentage between 1 and 100.'
      : undefined
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
      toast.success('Claim resolved', updated.reference ?? undefined)
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not resolve claim.')
    } finally {
      setSubmitting(false)
    }
  }

  const amountValid = !needsAmount || (amountNgn.trim() !== '' && Number.isFinite(enteredAmount) && enteredAmount > 0)
  const discountValid =
    !needsDiscount || (discountPct.trim() !== '' && Number.isFinite(enteredDiscount) && enteredDiscount > 0 && enteredDiscount <= 100)
  const canSubmit = reason.trim().length > 0 && amountValid && discountValid && !submitting

  return (
    <div className={styles.overlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
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
          <label className={styles.selectLabel}>Resolution type</label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 'var(--space-3)', marginTop: 'var(--space-2)', marginBottom: 'var(--space-1)' }}>
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
          <Field label="Amount (₦)" name="amount_ngn" type="number" min="1" required placeholder="e.g. 25000"
            error={amountError}
            value={amountNgn} onChange={(e) => setAmountNgn(e.target.value)} />
        )}
        {resolutionType === 'refund' && enteredAmount > 0 && (
          <Banner variant="info" title="Refund record generated automatically">
            Confirming creates a refund of {formatNgn(enteredAmount)} in <strong>Pending Accounts Review</strong> status.
          </Banner>
        )}
        {needsDiscount && (
          <Field label="Discount (%)" name="discount_pct" type="number" min="1" max="100" required placeholder="e.g. 10"
            error={discountError}
            value={discountPct} onChange={(e) => setDiscountPct(e.target.value)} />
        )}
        {/* A decision against the customer is explained to them; otherwise the reason stays internal. */}
        <Field
          label={resolutionType === 'no_action' ? 'Reason (the customer will see this)' : 'Reason (internal, not shown to the customer)'}
          name="reason" required multiline
          placeholder={resolutionType === 'no_action' ? 'Tell the customer why the claim is closed without a payout…' : 'Explain the resolution decision…'}
          helper={resolutionType === 'no_action' ? 'Shown to the customer on their claim page, word for word.' : undefined}
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
  const progress = claimProgress(current)
  return <Stepper steps={claimSteps('staff')} current={progress.current} complete={progress.complete} label="Claim progress" />
}

function inspectionMethodLabel(method: InspectionMethod | null): string {
  switch (method) {
    case 'delegate_visit':
      return 'Delegate visit — in-person inspection'
    case 'customer_evidence':
      return 'Customer evidence — photos/video'
    default:
      return 'Not started'
  }
}

function resolutionTypeLabel(type: ResolutionType): string {
  switch (type) {
    case 'refund':
      return 'Refund'
    case 'discount':
      return 'Discount'
    case 'compensation':
      return 'Compensation'
    case 'no_action':
      return 'No action'
  }
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null) return ''
  return bytes >= 1_048_576
    ? `${formatCount(Math.round(bytes / 1_048_576))} MB`
    : `${formatCount(Math.max(1, Math.round(bytes / 1024)))} KB`
}

function EvidenceFileList({ files }: { files: ClaimEvidenceFile[] }): JSX.Element {
  if (files.length === 0) {
    return <span className={styles.emptyNote}>No evidence files attached yet.</span>
  }
  return (
    <ul className={styles.evidenceList}>
      {files.map((file) => {
        const sizeLabel = formatFileSize(file.file_size_bytes)
        return (
          <li key={file.id} className={styles.evidenceItem}>
            <div className={styles.evidenceMeta}>
              <span className={styles.evidenceName}>{file.file_name}</span>
              <span className={styles.evidenceSub}>
                {[sizeLabel, file.file_type, `Uploaded ${formatDate(file.uploaded_at)}`].filter(Boolean).join(' · ')}
              </span>
            </div>
            {file.download_url ? (
              <a
                href={file.download_url}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.evidenceLink}
                aria-label={`Open ${file.file_name}`}
              >
                Open file
              </a>
            ) : (
              <span className={styles.emptyNote}>Link unavailable</span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function ClaimDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const { session } = useSession()
  const role = session?.role ?? 'nigeria_office_staff'

  const qc = useQueryClient()
  const [showInspect, setShowInspect] = useState(false)
  const [showResolve, setShowResolve] = useState(false)

  // Router state from ClaimList seeds the first paint, while GET /v1/claims/{id}
  // still fetches detail-only fields (evidence, resolution, refund).
  const stateClaim = (location.state as { claim?: Claim } | null)?.claim ?? null
  const { data: claim = null, isLoading: loading, error: loadError, refetch } = useQuery({
    queryKey: claimKeys.detail(id ?? ''),
    queryFn: () => claimsApi.get(id!),
    enabled: !!id,
    ...(stateClaim ? { placeholderData: stateClaim } : {}),
    staleTime: STALE_30S,
  })
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(claim?.reference)

  const error = loadError
    ? loadError instanceof ApiError
      ? loadError.message
      : 'Could not load this claim.'
    : null

  // Write the updated claim into cache immediately, then refetch so detail-only
  // fields (such as a newly generated refund record) stay in sync.
  const applyUpdated = (updated: Claim): void => {
    qc.setQueryData(claimKeys.detail(id ?? ''), updated)
    void qc.invalidateQueries({ queryKey: claimKeys.detail(id ?? '') })
  }

  if (loading && !claim) return <PageSkeleton kind="detail" label="Loading claim" />
  if ((error && !claim) || !claim) {
    return (
      <>
        <PageHeader title="Damage claim" />
        <ErrorState title="Couldn't load this claim" error={loadError} message="We couldn't find this record. It may have been removed, or the link is out of date." onRetry={() => void refetch()} />
      </>
    )
  }

  const r = role as Parameters<typeof canStartInspection>[1]
  const evidenceFiles = claim.evidence ?? []

  return (
    <DetailPage
      header={
        <PageHeader
          title={claim.reference ? `Damage claim ${claim.reference}` : 'Damage claim'}
          status={<StatusBadge kind="claim" status={claim.status} />}
          meta={[
            claim.customer_name && claim.customer_id && (
              <RecordLink to={`/admin/customers/${claim.customer_id}`}>
                {claim.customer_name}
              </RecordLink>
            ),
            claim.container_number && claim.container_id && (
              <RecordLink to={`/containers/${claim.container_id}`}>
                <Mono>{claim.container_number}</Mono>
              </RecordLink>
            ),
            `Filed ${formatDate(claim.created_at)}`,
          ]}
          primary={
            isTerminalClaimStatus(claim.status) ? null : canStartInspection(claim, r) ? (
              <Action variant="primary" onClick={() => setShowInspect(true)}>
                Start inspection
              </Action>
            ) : canResolveClaim(claim, r) ? (
              <Action variant="primary" onClick={() => setShowResolve(true)}>
                Resolve claim
              </Action>
            ) : null
          }
        />
      }
    >
      {/* Status stepper */}
      <Section title="Progress">
        <StatusStepper current={claim.status} />
      </Section>

      {/* Claim context */}
      {(claim.description || claim.inspection_method) && (
        <Section title="Claim details">
          {claim.description && (
            <Kvp label="Description" value={claim.description} divider={!!claim.inspection_method} />
          )}
          {claim.inspection_method && (
            <Kvp label="Inspection method" value={inspectionMethodLabel(claim.inspection_method)} divider={false} />
          )}
        </Section>
      )}

      {/* Resolution & linked refund */}
      {claim.resolution && (
        <Section title="Resolution">
          <Kvp label="Decision" value={resolutionTypeLabel(claim.resolution.resolution_type)} />
          {claim.resolution.amount_ngn !== null &&
            claim.resolution.resolution_type !== 'discount' &&
            claim.resolution.resolution_type !== 'no_action' && (
              <Kvp label="Amount" value={<Mono>{formatNgn(claim.resolution.amount_ngn)}</Mono>} />
            )}
          {claim.resolution.discount_percentage !== null && claim.resolution.resolution_type === 'discount' && (
            <Kvp label="Discount" value={`${Number(claim.resolution.discount_percentage)}%`} />
          )}
          <Kvp label="Resolved on" value={formatDate(claim.resolution.resolved_at)} divider={Boolean(claim.resolution.reason || claim.refund)} />
          {claim.resolution.reason && (
            <Kvp label="Reason" value={claim.resolution.reason} divider={Boolean(claim.refund)} />
          )}
          {claim.refund && (
            <Kvp
              label="Refund record"
              divider={false}
              value={
                <span className={styles.refundRow}>
                  <RecordLink to={`/refunds/${claim.refund.id}`}>
                    View refund
                  </RecordLink>
                  <StatusBadge kind="refund" status={claim.refund.status as RefundStatus} />
                  {claim.refund.amount_ngn !== null && (
                    <Mono>{formatNgn(claim.refund.amount_ngn)}</Mono>
                  )}
                </span>
              }
            />
          )}
        </Section>
      )}

      {/* Cartons affected */}
      <Section title="Cartons affected">
        {claim.cartons_affected.length > 0 ? (
          <div className={styles.cartonList}>
            {claim.cartons_affected.map((tag) => (
              <span key={tag} className={styles.cartonTag}>
                <Mono>{tag}</Mono>
              </span>
            ))}
          </div>
        ) : (
          <span className={styles.emptyNote}>No specific carton tags recorded.</span>
        )}
      </Section>

      {/* Evidence files + upload */}
      <Section
        title="Evidence"
        sub={!isTerminalClaimStatus(claim.status) ? 'Photos or PDF documents (JPEG · PNG · PDF, max 5 MB each)' : undefined}
      >
        <EvidenceFileList files={evidenceFiles} />
        {!isTerminalClaimStatus(claim.status) && (
          <div className={styles.uploaderWrap}>
            <EvidenceUploader
              getPresignedUrl={(f) => presignedUploadApi.getUrl(claim.id, f.name, f.type, f.size)}
              confirmUpload={(evidenceId) => presignedUploadApi.confirm(claim.id, evidenceId)}
              onUploaded={() => {
                void refetch()
              }}
            />
          </div>
        )}
      </Section>

      {showInspect && (
        <StartInspectionModal
          claimId={claim.id}
          onCancel={() => setShowInspect(false)}
          onSuccess={(updated) => {
            setShowInspect(false)
            applyUpdated(updated)
          }}
        />
      )}
      {showResolve && (
        <ResolveClaimModal
          claimId={claim.id}
          role={role}
          onCancel={() => setShowResolve(false)}
          onSuccess={(updated) => {
            setShowResolve(false)
            applyUpdated(updated)
          }}
        />
      )}
    </DetailPage>
  )
}
