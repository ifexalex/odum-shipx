import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { missingItemsApi, type MissingItem, type MissingItemStatus, type UpdateMissingItemInput } from '../../api/claims'
import { canUpdateItem } from '../../api/claimsRules'
import { useMissingItemList } from '../../hooks/useItems'
import { useSession } from '../../auth/useSession'
import { Badge, Banner, Button, Card, Chip, Field, Mono, Table, ListFooter, DialogGuard, type BadgeVariant } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './ItemList.module.css'
import { formatDate } from '../../lib/format'

const STATUS_FILTERS: MissingItemStatus[] = [
  'reported', 'investigating', 'found_and_shipping', 'confirmed_lost', 'resolved',
]

const STATUS_VARIANT: Record<MissingItemStatus, BadgeVariant> = {
  reported: 'warning',
  investigating: 'warning',
  found_and_shipping: 'warning',
  confirmed_lost: 'error',
  resolved: 'success',
}

function statusLabel(s: MissingItemStatus): string {
  switch (s) {
    case 'reported': return 'Reported'
    case 'investigating': return 'Investigating'
    case 'found_and_shipping': return 'Found & shipping'
    case 'confirmed_lost': return 'Confirmed lost'
    case 'resolved': return 'Resolved'
  }
}

// ---------------------------------------------------------------------------
// UpdateStatusModal
// ---------------------------------------------------------------------------

interface UpdateModalProps {
  item: MissingItem
  onCancel: () => void
  onSuccess: (updated: MissingItem) => void
}

function UpdateModal({ item, onCancel, onSuccess }: UpdateModalProps): JSX.Element {
  const [status, setStatus] = useState<MissingItemStatus>(item.status)
  const [notes, setNotes] = useState('')
  const [compensation, setCompensation] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Compensation is owed when the item is confirmed lost; the other statuses carry none.
  const offersCompensation = status === 'confirmed_lost'
  const compensationAmount = compensation.trim() === '' ? null : Number(compensation)
  const compensationInvalid =
    offersCompensation && compensationAmount !== null && !(Number.isFinite(compensationAmount) && compensationAmount > 0)

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const body: UpdateMissingItemInput = { status }
      if (notes.trim()) body.notes = notes
      if (offersCompensation && compensationAmount !== null) body.refund_amount_ngn = compensation.trim()
      const updated = await missingItemsApi.update(item.id, body)
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update missing item.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.overlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div className={styles.panel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.panelTitle}>Update missing item</h3>
        {error && <div className={styles.panelBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}
        <div className={styles.selectField}>
          <label className={styles.selectLabel}>New status <span className={styles.required}>*</span></label>
          <select className={styles.select} value={status} onChange={(e) => setStatus(e.target.value as MissingItemStatus)}>
            {STATUS_FILTERS.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
          </select>
        </div>
        {offersCompensation && (
          <Field label="Compensation (₦)" name="refund_amount_ngn" type="number" optional placeholder="e.g. 25000"
            value={compensation} onChange={(e) => setCompensation(e.target.value)}
            error={compensationInvalid ? 'Enter an amount greater than 0.' : undefined}
            helper="Opens a refund request for the customer, pending review. Leave blank to confirm the loss without compensation." />
        )}
        <Field label="Notes" name="notes" multiline placeholder="Add any notes about this update…"
          value={notes} onChange={(e) => setNotes(e.target.value)} />
        <div className={styles.panelActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} disabled={compensationInvalid} onClick={() => void handleSubmit()}>Save update</Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function MissingItemList(): JSX.Element {
  const { session } = useSession()
  const role = session?.role ?? 'nigeria_office_staff'

  const [statusFilter, setStatusFilter] = useState<MissingItemStatus | null>(null)
  const [editing, setEditing] = useState<MissingItem | null>(null)
  const { items, isLoading: loading, error, hasMore, loadMore, isFetchingMore, refetch, totalCount } = useMissingItemList(
    statusFilter ? { status: statusFilter } : {},
  )

  function handleUpdated(): void {
    setEditing(null)
    refetch()
  }

  const r = role as Parameters<typeof canUpdateItem>[0]

  useTopBarSlot({ subtitle: 'Cargo reported missing during manifest inspection.' })

  return (
    <div>

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't load missing items">{error.message}</Banner>
        </div>
      )}

      <Card padding={16}>
        <div className={styles.chips}>
          <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>All</Chip>
          {STATUS_FILTERS.map((s) => (
            <Chip key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>{statusLabel(s)}</Chip>
          ))}
        </div>
      </Card>

      <div className={styles.tableWrap}>
        <Card padding={0}>
          <Table
            columns={[
              { title: 'Description' },
              { title: 'Carton tags' },
              { title: 'Status' },
              { title: 'Reported' },
              { title: '', width: '80px' },
            ]}
            rows={items.map((item) => ({
              cells: [
                <span key="desc">{item.description}</span>,
                <Mono key="tags">{item.carton_tags.join(', ') || '—'}</Mono>,
                <Badge key="status" variant={STATUS_VARIANT[item.status]}>{statusLabel(item.status)}</Badge>,
                <span key="date">{formatDate(item.created_at)}</span>,
                canUpdateItem(r) && item.status !== 'resolved' ? (
                  <Button key="edit" variant="ghost" size="sm" onClick={() => setEditing(item)}>Update</Button>
                ) : <span key="noop" />,
              ],
            }))}
            loading={loading}
            emptyState={!loading && items.length === 0 ? <span>✓ No missing items on record.</span> : undefined}
          />
        </Card>
        <ListFooter
        shown={items.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="missing items"
      />
      </div>

      {editing && (
        <UpdateModal item={editing} onCancel={() => setEditing(null)} onSuccess={handleUpdated} />
      )}
    </div>
  )
}
