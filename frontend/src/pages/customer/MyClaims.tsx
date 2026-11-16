import { type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { type DamageClaimStatus } from '../../api/claims'
import { CLAIM_STATUS_ORDER } from '../../api/claimsRules'
import { useClaimList } from '../../hooks/useClaims'
import { Badge, Banner, Button, type BadgeVariant } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import styles from './customer.module.css'
import { formatDate } from '../../lib/format'

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

function ClaimProgressBar({ status }: { status: DamageClaimStatus }): JSX.Element {
  const idx = CLAIM_STATUS_ORDER.indexOf(status)
  const pct = Math.round(((idx + 1) / CLAIM_STATUS_ORDER.length) * 100)
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ height: 4, borderRadius: 2, background: 'var(--color-border)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: status === 'resolved' || status === 'closed' ? 'var(--color-success)' : 'var(--color-primary)', borderRadius: 2 }} />
      </div>
    </div>
  )
}

export function MyClaims(): JSX.Element {
  const navigate = useNavigate()

  // `useClaimList` already existed and this page hand-rolled the same fetch.
  // The backend scopes GET /v1/claims to the caller's own customer record for
  // the customer role, so no client-side filtering is needed here.
  const { items: claims, isLoading: loading, error: loadError } = useClaimList()

  const error = loadError
    ? loadError instanceof ApiError
      ? loadError.message
      : 'Could not load your claims.'
    : null

  return (
    <div className={styles.page}>
      <PageHeader
        title="My Claims"
        subtitle="Track damage claims you've filed."
        actions={
          <Button variant="primary" icon="plus" onClick={() => navigate('/my-claims/new')}>
            File a claim
          </Button>
        }
      />

      {error && (
        <div className={styles.banner}>
          <Banner variant="error">{error}</Banner>
        </div>
      )}

      {loading && <p style={{ color: 'var(--color-text-muted)' }}>Loading…</p>}

      {!loading && claims.length === 0 && (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>No claims yet</p>
          <p>If you received damaged goods, file a claim and we'll investigate.</p>
        </div>
      )}

      <div className={styles.cardList}>
        {claims.map((c) => (
          <div key={c.id} className={[styles.card, styles.cardStatic].join(' ')}>
            <div className={styles.cardLeft} style={{ width: '100%' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <p className={styles.cardTitle} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.875rem' }}>
                    {c.reference ?? `${c.id.slice(0, 8)}…`}
                  </p>
                  {c.description && <p className={styles.cardSub}>{c.description}</p>}
                </div>
                <Badge variant={STATUS_VARIANT[c.status]}>{statusLabel(c.status)}</Badge>
              </div>
              <div className={styles.cardMeta}>
                <span>Filed {formatDate(c.created_at)}</span>
                {c.cartons_affected.length > 0 && (
                  <span>· {c.cartons_affected.length} carton(s) affected</span>
                )}
              </div>
              <ClaimProgressBar status={c.status} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
