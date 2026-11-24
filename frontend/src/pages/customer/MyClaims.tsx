import { useMemo, useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { type DamageClaimStatus } from '../../api/claims'
import { CLAIM_STATUS_ORDER } from '../../api/claimsRules'
import { useClaimList } from '../../hooks/useClaims'
import { Banner, Button, Card, Chip, EmptyState, Icon, Mono, StatusBadge, LinesSkeleton } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import styles from './customer.module.css'
import { formatDate, plural } from '../../lib/format'

type ClaimFilter = 'all' | 'open' | 'done'

function isDoneStatus(status: DamageClaimStatus): boolean {
  return status === 'resolved' || status === 'closed'
}

function ClaimProgressBar({ status }: { status: DamageClaimStatus }): JSX.Element {
  const done = isDoneStatus(status)
  const idx = CLAIM_STATUS_ORDER.indexOf(status)
  const step = idx >= 0 ? idx + 1 : 1
  const total = CLAIM_STATUS_ORDER.length
  const pct = done ? 100 : Math.round((step / total) * 100)
  return (
    <div className={styles.progressWrap}>
      <div className={styles.progressHead}>
        <span>{done ? 'Claim completed' : `Step ${step} of ${total}`}</span>
        <span>{pct}%</span>
      </div>
      <div className={styles.progressTrack}>
        <div
          className={[styles.progressFill, done ? styles.progressFillSuccess : ''].filter(Boolean).join(' ')}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export function MyClaims(): JSX.Element {
  const navigate = useNavigate()
  const [filter, setFilter] = useState<ClaimFilter>('all')

  // `useClaimList` already existed and this page hand-rolled the same fetch.
  // The backend scopes GET /v1/claims to the caller's own customer record for
  // the customer role, so no client-side filtering is needed here.
  const { items: claims, isLoading: loading, error: loadError } = useClaimList()

  const error = loadError
    ? loadError instanceof ApiError
      ? loadError.message
      : 'Could not load your claims.'
    : null

  const { openCount, doneCount } = useMemo(() => {
    let open = 0
    let done = 0
    for (const c of claims) {
      if (isDoneStatus(c.status)) done += 1
      else open += 1
    }
    return { openCount: open, doneCount: done }
  }, [claims])

  const visibleClaims = useMemo(() => {
    if (filter === 'open') return claims.filter((c) => !isDoneStatus(c.status))
    if (filter === 'done') return claims.filter((c) => isDoneStatus(c.status))
    return claims
  }, [claims, filter])

  return (
    <div className={styles.page}>
      <PageHeader
        title="My claims"
        meta="Track damage claims you've filed."
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

      {loading && <LinesSkeleton label="Loading" />}

      {!loading && claims.length === 0 && (
        <Card padding="default">
          <EmptyState
            icon="shield"
            title="No claims yet"
            body="If you received damaged goods, file a claim and we'll investigate."
            action={{ label: 'File a claim', to: '/my-claims/new' }}
          />
        </Card>
      )}

      {!loading && claims.length > 1 && (
        <div className={styles.filterRow} role="group" aria-label="Filter claims">
          <Chip active={filter === 'all'} count={claims.length} onClick={() => setFilter('all')}>
            All
          </Chip>
          <Chip active={filter === 'open'} count={openCount} onClick={() => setFilter('open')}>
            In progress
          </Chip>
          <Chip active={filter === 'done'} count={doneCount} onClick={() => setFilter('done')}>
            Completed
          </Chip>
        </div>
      )}

      <div className={styles.cardList}>
        {visibleClaims.map((c) => (
          // The whole card opens the claim. A link role and Enter/Space keep it usable from the keyboard.
          <div
            key={c.id}
            className={styles.card}
            role="link"
            tabIndex={0}
            aria-label={`Open claim ${c.reference ?? ''}`.trim()}
            onClick={() => navigate(`/my-claims/${c.id}`)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                navigate(`/my-claims/${c.id}`)
              }
            }}
          >
            <div className={styles.cardLeft}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 'var(--space-3)' }}>
                <div style={{ minWidth: 0 }}>
                  <p className={styles.cardTitle} style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-md)' }}>
                    {c.reference ?? `${c.id.slice(0, 8)}…`}
                  </p>
                  {c.description && <p className={styles.cardSub}>{c.description}</p>}
                </div>
                <StatusBadge kind="claim" status={c.status} audience="customer" />
              </div>
              <div className={styles.cardMeta}>
                <span>Filed {formatDate(c.created_at)}</span>
                {c.container_number && (
                  <span>· Container <Mono>{c.container_number}</Mono></span>
                )}
                {c.cartons_affected.length > 0 && (
                  <span>· {plural(c.cartons_affected.length, 'carton')} affected</span>
                )}
              </div>
              <ClaimProgressBar status={c.status} />
            </div>
            <Icon name="chevright" size={16} color="var(--color-ink-4)" />
          </div>
        ))}
      </div>
    </div>
  )
}
