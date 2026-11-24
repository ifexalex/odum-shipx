import { useMemo, useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { missingItemsApi, type MissingItem, type MissingItemStatus, type UpdateMissingItemInput } from '../../api/claims'
import { canCompensateMissingItem, canUpdateMissingItem, missingItemStatusesFor } from '../../api/claimsRules'
import { useMissingItemList } from '../../hooks/useItems'
import { useSession } from '../../auth/useSession'
import type { UserRole } from '../../auth/types'
import { Banner, Button, Chip, Field, Kvp, ListFooter, Modal, Mono, SearchField, StatusBadge, Table, Select, EmptyState, ErrorState } from '../../design/components'
import styles from './ItemList.module.css'
import { formatDate } from '../../lib/format'
import { statusLabel } from '../../design/status'
import { toast } from '../../design/toast'
import { FilterBar } from '../../shell/FilterBar'
import { ListPage } from '../../shell/ListPage'
import { PageHeader } from '../../shell/PageHeader'

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
      toast.success('Missing item updated')
      onSuccess(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update missing item.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open
      onClose={onCancel}
      title="Update missing item"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>Cancel</Button>
          <Button variant="primary" loading={submitting} disabled={compensationInvalid} onClick={() => void handleSubmit()}>Save update</Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {error && <Banner variant="error" title="Action failed">{error}</Banner>}
        <div className={styles.itemContext}>
          {item.customer_name && <Kvp label="Customer" value={item.customer_name} />}
          {item.container_number && <Kvp label="Container" value={<Mono>{item.container_number}</Mono>} />}
          <Kvp label="Carton tags" value={<Mono>{item.carton_tags.join(', ') || '—'}</Mono>} />
          <Kvp label="Description" value={item.description || '—'} divider={false} />
        </div>
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
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function MissingItemList(): JSX.Element {
  const { session } = useSession()
  const role: UserRole = session?.role ?? 'nigeria_office_staff'

  const [statusFilter, setStatusFilter] = useState<MissingItemStatus | null>(null)
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<MissingItem | null>(null)
  const { items, isLoading: loading, error, hasMore, loadMore, isFetchingMore, refetch, totalCount } = useMissingItemList(
    statusFilter ? { status: statusFilter } : {},
  )

  const filteredItems = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return items
    return items.filter((item) =>
      [item.customer_name, item.container_number, item.description, ...item.carton_tags]
        .filter(Boolean)
        .some((v) => v!.toLowerCase().includes(q)),
    )
  }, [items, search])

  function handleUpdated(): void {
    setEditing(null)
    refetch()
  }

  return (
    <>
      <ListPage
        header={
          <PageHeader
            title="Missing items"
            meta={
              role === 'china_office_staff'
                ? 'Cargo reported missing in Nigeria. Record the supply and loading check.'
                : 'Cargo reported missing during manifest inspection.'
            }
          />
        }
        notices={
          <>
            {error && (
              <ErrorState
                compact
                title="Couldn't load missing items"
                error={error}
                onRetry={() => void refetch()}
              />
            )}
          </>
        }
        filters={
          <FilterBar
            label="Filter missing items"
            status={
              <>
                <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
                  All
                </Chip>
                {STATUS_FILTERS.map((s) => (
                  <Chip key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>
                    {statusLabel('missingItem', s)}
                  </Chip>
                ))}
              </>
            }
            search={
              <SearchField
                label="Search missing items"
                placeholder="Customer, container, tag, item…"
                value={search}
                onChange={setSearch}
              />
            }
          />
        }
        footer={
          <ListFooter
            shown={filteredItems.length}
            total={search.trim() ? filteredItems.length : totalCount}
            hasMore={!search.trim() && hasMore}
            loading={isFetchingMore}
            onLoadMore={loadMore}
            noun="missing items"
            nounOne="missing item"
          />
        }
      >
        <Table
          columns={[
            { title: 'Customer' },
            { title: 'Container', type: 'reference' },
            { title: 'Description' },
            { title: 'Carton tags', type: 'reference' },
            { title: 'Status', type: 'status' },
            { title: 'Reported', type: 'date' },
            { title: '', type: 'action', width: '80px' },
          ]}
          rows={filteredItems.map((item) => ({
            cells: [
              <span key="customer">{item.customer_name ?? '—'}</span>,
              <Mono key="container">{item.container_number ?? '—'}</Mono>,
              <span key="desc">{item.description}</span>,
              <Mono key="tags">{item.carton_tags.join(', ') || '—'}</Mono>,
              <StatusBadge key="status" kind="missingItem" status={item.status} />,
              <span key="date">{formatDate(item.created_at)}</span>,
              canUpdateMissingItem(role, item.status) ? (
                <Button key="edit" variant="ghost" size="sm" onClick={() => setEditing(item)}>
                  Update
                </Button>
              ) : (
                <span key="noop" />
              ),
            ],
          }))}
          loading={loading}
          emptyState={
            !loading && filteredItems.length === 0 ? (
              <EmptyState compact title="No missing items on record" />
            ) : undefined
          }
        />
      </ListPage>
      {editing && (
        <UpdateModal
          item={editing}
          role={role}
          onCancel={() => setEditing(null)}
          onSuccess={handleUpdated}
        />
      )}
    </>
  )
}
