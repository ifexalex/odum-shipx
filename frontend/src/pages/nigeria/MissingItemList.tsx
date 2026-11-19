import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { missingItemsApi, type MissingItem, type MissingItemStatus, type UpdateMissingItemInput } from '../../api/claims'
import { canCompensateMissingItem, canUpdateMissingItem, missingItemStatusesFor } from '../../api/claimsRules'
import { useMissingItemList } from '../../hooks/useItems'
import { useSession } from '../../auth/useSession'
import type { UserRole } from '../../auth/types'
import { Banner, Button, Card, Chip, DialogGuard, Field, ListFooter, Mono, StatusBadge, Table, Select } from '../../design/components'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './ItemList.module.css'
import { formatDate } from '../../lib/format'
import { statusLabel } from '../../design/status'

const STATUS_FILTERS: MissingItemStatus[] = [
  'reported', 'investigating', 'found_and_shipping', 'confirmed_lost', 'resolved',
]

// ---------------------------------------------------------------------------
// UpdateStatusModal
// ---------------------------------------------------------------------------

interface UpdateModalProps {
  item: MissingItem
  role: UserRole
  onCancel: () => void
  onSuccess: (updated: MissingItem) => void
}

function UpdateModal({ item, role, onCancel, onSuccess }: UpdateModalProps): JSX.Element {
  // The China office records the investigation; deciding a loss, and any compensation, stay with the Nigeria office.
  const statuses = missingItemStatusesFor(role)
  const [status, setStatus] = useState<MissingItemStatus>(statuses.includes(item.status) ? item.status : statuses[0]!)
  const [notes, setNotes] = useState('')
  const [compensation, setCompensation] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Compensation is owed when the item is confirmed lost; the other statuses carry none.
  const offersCompensation = status === 'confirmed_lost' && canCompensateMissingItem(role)
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
          <Select label="New status" value={status} onChange={(e) => setStatus(e.target.value as MissingItemStatus)}>
            {statuses.map((s) => <option key={s} value={s}>{statusLabel('missingItem', s)}</option>)}
          </Select>
        </div>
        {!canCompensateMissingItem(role) && (
          <p className={styles.panelNote}>
            Record what the supply and loading check found. Deciding an item is lost, and any compensation, is done by the Nigeria office.
          </p>
        )}
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
  const role: UserRole = session?.role ?? 'nigeria_office_staff'

  const [statusFilter, setStatusFilter] = useState<MissingItemStatus | null>(null)
  const [editing, setEditing] = useState<MissingItem | null>(null)
  const { items, isLoading: loading, error, hasMore, loadMore, isFetchingMore, refetch, totalCount } = useMissingItemList(
    statusFilter ? { status: statusFilter } : {},
  )

  function handleUpdated(): void {
    setEditing(null)
    refetch()
  }

  useTopBarSlot({
    subtitle:
      role === 'china_office_staff'
        ? 'Cargo reported missing in Nigeria. Record the supply and loading check.'
        : 'Cargo reported missing during manifest inspection.',
  })

  return (
    <div>

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't load missing items">{error.message}</Banner>
        </div>
      )}

      <Card padding="default">
        <div className={styles.chips}>
          <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>All</Chip>
          {STATUS_FILTERS.map((s) => (
            <Chip key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>{statusLabel('missingItem', s)}</Chip>
          ))}
        </div>
      </Card>

      <div className={styles.tableWrap}>
        <Card padding="none">
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
                <StatusBadge key="status" kind="missingItem" status={item.status} />,
                <span key="date">{formatDate(item.created_at)}</span>,
                canUpdateMissingItem(role, item.status) ? (
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
        <UpdateModal item={editing} role={role} onCancel={() => setEditing(null)} onSuccess={handleUpdated} />
      )}
    </div>
  )
}
