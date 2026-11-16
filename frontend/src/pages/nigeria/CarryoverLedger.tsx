/**
 * 7.4 — Carryover Ledger (Section 7 of the prototype, billing-screens.jsx).
 *
 * Cross-customer view of outstanding balances rolled forward from
 * released-with-outstanding billings. tenant_admin can exempt an entry
 * (the backend rolls the debt forward as a new outstanding row).
 */
import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { carryoverApi, type Carryover, type CarryoverStatus } from '../../api/billing'
import { billingKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { ApiError } from '../../api/client'
import { useSession } from '../../auth/useSession'
import { Badge, Banner, Button, Card, Chip, Field, Mono, StatCard, Table, UserCell, DialogGuard, type BadgeVariant } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './BillingList.module.css'
import { formatDate, formatNgn } from '../../lib/format'

const STATUS_VARIANT: Record<CarryoverStatus, BadgeVariant> = {
  outstanding: 'warning',
  applied: 'purple',
  exempted: 'neutral',
  expired: 'neutral',
}

const STATUS_FILTERS: { key: CarryoverStatus; label: string }[] = [
  { key: 'outstanding', label: 'Outstanding' },
  { key: 'applied', label: 'Applied' },
  { key: 'exempted', label: 'Exempted' },
]

function ExemptModal({ carryover, onCancel, onSuccess }: { carryover: Carryover; onCancel: () => void; onSuccess: () => void }): JSX.Element {
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      await carryoverApi.exempt(carryover.id, notes || undefined)
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not exempt this carryover.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(11,47,13,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200, padding: 16 }}
      onClick={onCancel}
    >
      <DialogGuard onClose={onCancel} />
      <div
        style={{
          background: 'var(--color-surface)', borderRadius: 14, padding: 24, width: '100%', maxWidth: 480,
          display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '90vh', overflowY: 'auto',
        }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>Exempt carryover</h3>
        {error && <Banner variant="error" title="Action failed">{error}</Banner>}
        <Banner variant="warning" title={`${formatNgn(carryover.amount_ngn)} from ${carryover.source_container_number ?? 'source billing'}`}>
          Exempting removes this debt from the next billing. The amount is rolled forward as a new
          outstanding ledger entry for audit — it is not written off.
        </Banner>
        <Field
          label="Reason"
          name="exempt_notes"
          multiline
          optional
          placeholder="Why is this carryover being exempted?"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Button variant="ghost" size="lg" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="danger" size="lg" loading={submitting} onClick={() => void handleSubmit()}>
            Exempt carryover
          </Button>
        </div>
      </div>
    </div>
  )
}

export function CarryoverLedger(): JSX.Element {
  const navigate = useNavigate()
  const { session } = useSession()
  const [statusFilter, setStatusFilter] = useState<CarryoverStatus | null>(null)
  const [exempting, setExempting] = useState<Carryover | null>(null)

  const canExempt = session?.role === 'tenant_admin'

  // The status filter is part of the key, so switching it swaps cached pages
  // instead of refetching into shared state.
  const listParams = statusFilter ? { status: statusFilter } : {}
  const { data: page, isLoading: loading, error: loadError } = useQuery({
    queryKey: billingKeys.carryovers(listParams),
    queryFn: () => carryoverApi.list(listParams),
    staleTime: STALE_30S,
  })
  const carryovers = page?.data ?? []

  const error = loadError
    ? loadError instanceof ApiError
      ? loadError.message
      : 'Could not load the carryover ledger.'
    : null


  const outstandingTotal = carryovers
    .filter((c) => c.status === 'outstanding')
    .reduce((s, c) => s + Number(c.amount_ngn), 0)

  useTopBarSlot({ subtitle: 'Outstanding balances rolled forward from released-with-outstanding billings, across all customers.' })

  return (
    <div>

      {error && <div style={{ marginBottom: 16 }}><Banner variant="error" title="Couldn't load">{error}</Banner></div>}

      <div className={styles.statsRow ?? ''} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 20 }}>
        <StatCard label="Outstanding total" value={formatNgn(outstandingTotal)} />
        <StatCard label="Outstanding entries" value={carryovers.filter((c) => c.status === 'outstanding').length} />
        <StatCard label="All entries" value={carryovers.length} />
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>All</Chip>
        {STATUS_FILTERS.map(({ key, label }) => (
          <Chip key={key} active={statusFilter === key} onClick={() => setStatusFilter(key)}>{label}</Chip>
        ))}
      </div>

      <Card padding={0}>
        <Table
          columns={[
            { title: 'Customer' },
            { title: 'Source' },
            { title: 'Amount (₦)', align: 'right' },
            { title: 'Status' },
            { title: 'Created' },
            { title: '', width: '100px' },
          ]}
          rows={carryovers.map((c) => ({
            cells: [
              <UserCell key="cust" name={c.customer_name ?? c.customer_id} email="" />,
              <button
                key="src"
                type="button"
                style={{ background: 'none', border: 0, padding: 0, cursor: 'pointer', color: 'var(--color-primary)', fontWeight: 600, fontSize: 13 }}
                onClick={() => navigate(`/billing/${c.source_billing_id}`)}
              >
                <Mono color="var(--color-primary)">{c.source_container_number ?? c.source_billing_id.slice(0, 8)}</Mono>
              </button>,
              <Mono key="amt">{formatNgn(c.amount_ngn)}</Mono>,
              <Badge key="status" variant={STATUS_VARIANT[c.status]}>{c.status}</Badge>,
              <span key="created" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>{formatDate(c.created_at)}</span>,
              c.status === 'outstanding' && canExempt ? (
                <Button key="exempt" variant="ghost" size="sm" onClick={() => setExempting(c)}>Exempt</Button>
              ) : (
                <span key="exempt" />
              ),
            ],
          }))}
          emptyState={
            <span style={{ color: 'var(--color-ink-3)', fontSize: 13 }}>
              {loading ? 'Loading carryovers…' : 'No carryover entries match this filter.'}
            </span>
          }
        />
      </Card>

      {exempting && (
        <ExemptModal
          carryover={exempting}
          onCancel={() => setExempting(null)}
          onSuccess={() => {
            setExempting(null)
          }}
        />
      )}
    </div>
  )
}
