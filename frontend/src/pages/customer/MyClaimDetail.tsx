import { type JSX } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import type { Claim, ClaimEvidenceFile, DamageClaimStatus } from '../../api/claims'
import {
  customerInspectionLabel,
  customerRefundLabel,
  customerResolutionLabel,
} from '../../api/claimsRules'
import { Banner, Card, Kvp, Mono, StatusBadge, Stepper, PageSkeleton } from '../../design/components'
import { useClaim } from '../../hooks/useClaims'
import { formatCount, formatDate, formatNgn } from '../../lib/format'
import { PageHeader } from '../../shell/PageHeader'
import styles from './customer.module.css'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'
import { claimProgress, claimSteps } from '../../design/steps'

/** What the customer is waiting for, by where the claim is. */
function waitingNote(status: DamageClaimStatus): string | null {
  switch (status) {
    case 'filed':
      return 'We have your claim and will start looking at it shortly.'
    case 'under_inspection':
      return 'We are checking your claim now.'
    case 'inspection_complete':
    case 'pending_resolution':
      return 'We have finished checking and are deciding the outcome. We will tell you as soon as it is decided.'
    default:
      return null
  }
}

function fileSize(bytes: number | null): string {
  if (bytes === null) return ''
  return bytes >= 1_048_576 ? `${formatCount(Math.round(bytes / 1_048_576))} MB` : `${formatCount(Math.max(1, Math.round(bytes / 1024)))} KB`
}

function ProgressSteps({ status }: { status: DamageClaimStatus }): JSX.Element {
  const progress = claimProgress(status)
  return <Stepper steps={claimSteps('customer')} current={progress.current} complete={progress.complete} label="Claim progress" />
}

function EvidenceList({ files }: { files: ClaimEvidenceFile[] }): JSX.Element {
  if (files.length === 0) return <p style={{ margin: 0, color: 'var(--color-ink-4)' }}>No files were attached to this claim.</p>
  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      {files.map((file) => (
        <li key={file.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-3)', alignItems: 'center', flexWrap: 'wrap' }}>
          <span>
            {file.file_name}
            {file.file_size_bytes !== null && <span style={{ color: 'var(--color-ink-4)' }}> · {fileSize(file.file_size_bytes)}</span>}
          </span>
          {file.download_url ? (
            // The link is short-lived and points at private storage: no referrer, and no access to this page.
            <a href={file.download_url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${file.file_name}`}>
              Open
            </a>
          ) : (
            <span style={{ color: 'var(--color-ink-4)' }}>Unavailable</span>
          )}
        </li>
      ))}
    </ul>
  )
}

function Outcome({ claim }: { claim: Claim }): JSX.Element | null {
  const { resolution, refund } = claim
  const waiting = waitingNote(claim.status)

  if (!resolution) {
    return waiting ? (
      <div className={styles.banner}>
        <Banner variant="info" title="No decision yet">
          {waiting}
        </Banner>
      </div>
    ) : null
  }

  return (
    <Card padding="large">
      <h2 style={{ margin: '0 0 var(--space-3)', fontSize: 'var(--text-lg)' }}>Outcome</h2>
      <Kvp label="Decision" value={customerResolutionLabel(resolution)} />
      {resolution.amount_ngn !== null && resolution.resolution_type !== 'discount' && resolution.resolution_type !== 'no_action' && (
        <Kvp label="Amount" value={<Mono>{formatNgn(resolution.amount_ngn)}</Mono>} />
      )}
      <Kvp label="Decided on" value={formatDate(resolution.resolved_at)} />
      {resolution.reason && <Kvp label="Why" value={resolution.reason} />}
      {refund && (
        <>
          <Kvp label="Refund status" value={customerRefundLabel(refund.status)} />
          {refund.amount_ngn !== null && <Kvp label="Refund amount" value={<Mono>{formatNgn(refund.amount_ngn)}</Mono>} />}
        </>
      )}
    </Card>
  )
}

/**
 * A customer's own damage claim: what they said, the evidence they gave, how it was checked, what was decided and
 * where the refund stands. The list showed a status badge and a progress bar and nothing opened (audit UX-07).
 *
 * The backend scopes `GET /v1/claims/{id}` to the owner and answers 404 for anyone else's, and its outcome carries
 * only the decision and the refund's status, never staff's notes or who approved it.
 */
export function MyClaimDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const { data: claim, isLoading, error } = useClaim(id ?? '')
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(claim?.reference)

  if (isLoading) return <PageSkeleton kind="detail" label="Loading your claim" />

  if (error || !claim) {
    const missing = error instanceof ApiError && error.status === 404
    return (
      <div className={styles.page}>
        <PageHeader title="Claim" />
        <Banner variant="error">
          {missing || !error ? 'Claim not found.' : 'Could not load this claim. Please try again.'}
        </Banner>
      </div>
    )
  }

  return (
    <div className={styles.page}>
      <PageHeader title={`Claim ${claim.reference ?? ''}`.trim()} meta={`Filed ${formatDate(claim.created_at)}`} />

      <div className={styles.banner} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
        <StatusBadge kind="claim" status={claim.status} audience="customer" />
      </div>
      <ProgressSteps status={claim.status} />

      <div style={{ height: 16 }} />
      <Outcome claim={claim} />

      <div style={{ height: 16 }} />
      <Card padding="large">
        <h2 style={{ margin: '0 0 var(--space-3)', fontSize: 'var(--text-lg)' }}>Your claim</h2>
        <Kvp label="Container" value={<Mono>{claim.container_number ?? '—'}</Mono>} />
        {claim.cartons_affected.length > 0 && <Kvp label="Cartons affected" value={<Mono>{claim.cartons_affected.join(', ')}</Mono>} />}
        <Kvp label="What you told us" value={claim.description ?? '—'} />
        <Kvp label="How it was checked" value={customerInspectionLabel(claim.inspection_method)} />
      </Card>

      <div style={{ height: 16 }} />
      <Card padding="large">
        <h2 style={{ margin: '0 0 var(--space-3)', fontSize: 'var(--text-lg)' }}>Evidence you provided</h2>
        <EvidenceList files={claim.evidence ?? []} />
      </Card>

    </div>
  )
}
