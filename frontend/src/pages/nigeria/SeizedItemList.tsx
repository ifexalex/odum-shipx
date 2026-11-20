import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { seizedItemsApi, type SeizedItem, type SeizedItemStatus, type UpdateSeizedItemInput } from '../../api/claims'
import { canUpdateItem } from '../../api/claimsRules'
import { useSeizedItemList } from '../../hooks/useItems'
import { useSession } from '../../auth/useSession'
import { Banner, Button, Card, Chip, DialogGuard, Field, ListFooter, Mono, StatusBadge, Table, Select, EmptyState, ErrorState } from '../../design/components'
import styles from './ItemList.module.css'
import { formatDate } from '../../lib/format'
import { statusLabel } from '../../design/status'
import { toast } from '../../design/toast'
import { PageHeader } from '../../shell/PageHeader'

const STATUS_FILTERS: SeizedItemStatus[] = [
  'seized', 'recovery_in_progress', 'recovered', 'permanently_lost',
]

// ---------------------------------------------------------------------------
// UpdateStatusModal
// ---------------------------------------------------------------------------

interface UpdateModalProps {
  item: SeizedItem
  onCancel: () => void
  onSuccess: (updated: SeizedItem) => void
}

function UpdateModal({ item, onCancel, onSuccess }: UpdateModalProps): JSX.Element {
  const [status, setStatus] = useState<SeizedItemStatus>(item.status)
  const [notes, setNotes] = useState('')
  const [compensation, setCompensation] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Compensation is owed when the goods are permanently lost; the other statuses carry none.
  const offersCompensation = status === 'permanently_lost'
  const compensationAmount = compensation.trim() === '' ? null : Number(compensation)
  const compensationInvalid =
    offersCompensation && compensationAmount !== null && !(Number.isFinite(compensationAmount) && compensationAmount > 0)

  async function handleSubmit(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const body: UpdateSeizedItemInput = { recovery_status: status }
      if (notes.trim()) body.notes = notes
      if (offersCompensation && compensationAmount !== null) body.refund_amount_ngn = compensation.trim()
      const updated = await seizedItemsApi.update(item.id, body)
      toast.success('Seized item updated')
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update seized item.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.overlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div className={styles.panel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.panelTitle}>Update seized item</h3>
        {error && <div className={styles.panelBanner}><Banner variant="error" title="Action failed">{error}</Banner></div>}
        <div className={styles.selectField}>
          <Select label="Recovery status" value={status} onChange={(e) => setStatus(e.target.value as SeizedItemStatus)}>
            {STATUS_FILTERS.map((s) => <option key={s} value={s}>{statusLabel('seizedItem', s)}</option>)}
          </Select>
        </div>
        {offersCompensation && (
          <Field label="Compensation (₦)" name="refund_amount_ngn" type="number" optional placeholder="e.g. 25000"
            value={compensation} onChange={(e) => setCompensation(e.target.value)}
            error={compensationInvalid ? 'Enter an amount greater than 0.' : undefined}
            helper="Opens a refund request for the customer, pending review. Leave blank to record the loss without compensation." />
        )}
        <Field label="Notes" name="notes" multiline placeholder="Recovery notes, agency contact, reference…"
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

export function SeizedItemList(): JSX.Element {
  const { session } = useSession()
  const role = session?.role ?? 'nigeria_office_staff'

  const [statusFilter, setStatusFilter] = useState<SeizedItemStatus | null>(null)
  const [editing, setEditing] = useState<SeizedItem | null>(null)
  const { items, isLoading: loading, error, hasMore, loadMore, isFetchingMore, refetch, totalCount } = useSeizedItemList(
    statusFilter ? { status: statusFilter } : {},
  )

  function handleUpdated(): void {
    setEditing(null)
    refetch()
  }

  const r = role as Parameters<typeof canUpdateItem>[0]

  return (
    <div>
      <PageHeader
        title="Seized items"
        meta={'Cargo detained by customs or security authorities.'}
      />

      {error && (
        <div className={styles.banner}>
          <ErrorState compact title="Couldn't load seized items" error={error} onRetry={() => void refetch()} />
        </div>
      )}

      <Card padding="default">
        <div className={styles.chips}>
          <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>All</Chip>
          {STATUS_FILTERS.map((s) => (
            <Chip key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>{statusLabel('seizedItem', s)}</Chip>
          ))}
        </div>
      </Card>

      <div className={styles.tableWrap}>
        <Card padding="none">
          <Table
            columns={[
              { title: 'Reason / notes' },
              { title: 'Carton tags', type: 'reference' },
              { title: 'Status', type: 'status' },
              { title: 'Reported', type: 'date' },
              { title: '', type: 'action', width: '80px' },
            ]}
            rows={items.map((item) => ({
              cells: [
                <span key="reason">{item.reason || '—'}</span>,
                <Mono key="tags">{item.carton_tags.join(', ') || '—'}</Mono>,
                <StatusBadge key="status" kind="seizedItem" status={item.status} />,
                <span key="date">{formatDate(item.created_at)}</span>,
                canUpdateItem(r) && item.status !== 'recovered' && item.status !== 'permanently_lost' ? (
                  <Button key="edit" variant="ghost" size="sm" onClick={() => setEditing(item)}>Update</Button>
                ) : <span key="noop" />,
              ],
            }))}
            loading={loading}
            emptyState={!loading && items.length === 0 ? <EmptyState compact title="No seized items on record" /> : undefined}
          />
        </Card>
        <ListFooter
        shown={items.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun="seized items"
        nounOne="seized item"
      />
      </div>

      {editing && (
        <UpdateModal item={editing} onCancel={() => setEditing(null)} onSuccess={handleUpdated} />
      )}
    </div>
  )
}
