import { useState, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { formatCbm } from '../../api/decimal'
import { packingListApi, type BulkActionResult, type PackingListStatus } from '../../api/packingList'
import { canApproveOrReject, explainBulkFailure, formatPackageMix, groupBulkFailures, isSelfApproval } from '../../api/packingListRules'
import { useSession } from '../../auth/useSession'
import { usePackingListList } from '../../hooks/usePackingLists'
import { Banner, Button, Card, Chip, DialogGuard, Field, ListFooter, Mono, StatusBadge, Table, Pressable, SearchField, EmptyState } from '../../design/components'
import styles from './PackingListList.module.css'
import { formatDate } from '../../lib/format'
import { useStatusParam } from '../../lib/useStatusParam'
import { statusLabel } from '../../design/status'
import { toast } from '../../design/toast'
import { PageHeader } from '../../shell/PageHeader'

const STATUS_FILTERS: PackingListStatus[] = ['draft', 'pending_approval', 'approved', 'rejected']

interface BulkRejectModalProps {
  count: number
  onCancel: () => void
  onConfirm: (comments: string) => void
  submitting: boolean
  error: string | null
}

function BulkRejectModal({ count, onCancel, onConfirm, submitting, error }: BulkRejectModalProps): JSX.Element {
  const [comments, setComments] = useState('')
  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div className={styles.modalPanel} onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Reject {count} packing list(s)</h3>
        {error && (
          <div className={styles.banner}>
            <Banner variant="error" title="Action failed">{error}</Banner>
          </div>
        )}
        <Field
          label="Comments"
          name="bulkRejectComments"
          required
          multiline
          placeholder="Why are these being rejected?"
          value={comments}
          onChange={(event) => setComments(event.target.value)}
        />
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="danger"
            loading={submitting}
            disabled={!comments.trim()}
            onClick={() => onConfirm(comments)}
          >
            Confirm reject
          </Button>
        </div>
      </div>
    </div>
  )
}

function BulkResultPanel({
  result,
  onDismiss,
  labelFor,
}: {
  result: BulkActionResult
  onDismiss: () => void
  /** Human label for a packing list id — reference and customer, not a UUID. */
  labelFor: (id: string) => string
}): JSX.Element {
  const groups = groupBulkFailures(result.failed)
  return (
    <div className={styles.resultWrap}>
      <Card padding="none">
        <div className={styles.resultHead}>
          <span>
            {result.succeeded.length} succeeded · {result.failed.length} failed
          </span>
          <Button variant="ghost" size="sm" onClick={onDismiss}>
            Dismiss
          </Button>
        </div>
        {/* One block per cause. Fifty rows repeating the same machine code told
            the user nothing; the cause, what to do, and which lists it hit do. */}
        {groups.map((group) => {
          const { title, help } = explainBulkFailure(group.reason)
          return (
            <div key={group.reason} className={styles.failureGroup}>
              <div className={styles.failureTitle}>
                {title} <span className={styles.failureCount}>{group.ids.length}</span>
              </div>
              <div className={styles.failureHelp}>{help}</div>
              <div className={styles.failureList}>
                {group.ids.map((id) => (
                  <span key={id} className={styles.failureChip}>
                    {labelFor(id)}
                  </span>
                ))}
              </div>
            </div>
          )
        })}
      </Card>
    </div>
  )
}

// The values `?status=` may hold (useStatusParam); anything else reads as no filter.
const PACKING_LIST_STATUSES: readonly PackingListStatus[] = ['draft', 'pending_approval', 'approved', 'rejected']

export function PackingListList(): JSX.Element {
  const { session } = useSession()
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useStatusParam<PackingListStatus>(PACKING_LIST_STATUSES)
  const [search, setSearch] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [showRejectModal, setShowRejectModal] = useState(false)
  const [bulkSubmitting, setBulkSubmitting] = useState(false)
  const [bulkResult, setBulkResult] = useState<BulkActionResult | null>(null)

  const canApprove = session?.role === 'china_office_staff' || session?.role === 'tenant_admin'

  const {
    items: packingLists, isLoading: loading, error: listError,
    hasMore, loadMore, isFetchingMore, refetch, totalCount,
  } = usePackingListList({
    ...(statusFilter ? { status: statusFilter } : {}),
    ...(search ? { q: search } : {}),
  })
  const error = actionError ?? (listError ? listError.message : null)

  async function reload(): Promise<void> {
    setSelected(new Set())
    refetch()
  }

  function toggleRow(id: string, isSelected: boolean): void {
    setSelected((prev) => {
      const next = new Set(prev)
      if (isSelected) next.add(id)
      else next.delete(id)
      return next
    })
  }

  function toggleAll(isSelected: boolean): void {
    setSelected(isSelected ? new Set(packingLists.map((pl) => pl.id)) : new Set())
  }

  // How much of the current selection this user could actually approve. The
  // rules already existed (canApproveOrReject) but nothing consulted them
  // before firing the request, so staff selected everything, clicked approve,
  // and got a wall of failures explaining what the UI already knew.
  const selectedPls = packingLists.filter((pl) => selected.has(pl.id))
  const approvableCount = session
    ? selectedPls.filter((pl) => canApproveOrReject(pl, session.role, session.userId)).length
    : selectedPls.length
  const blockedByOwnership = session
    ? selectedPls.filter(
        (pl) => pl.status === 'pending_approval' && isSelfApproval(pl, session.userId),
      ).length
    : 0
  // bulk_submit_packing_lists (services/packing_list/service.py) accepts only
  // draft rows — mirrors approvableCount's job of telling staff, before they
  // click, how much of their selection an action will actually touch, rather
  // than firing a request every non-draft row is guaranteed to fail
  // (wrong_status:pending_approval etc.).
  const submittableCount = selectedPls.filter((pl) => pl.status === 'draft').length

  // A UUID means nothing to staff — show the reference and customer they see
  // in the table. Ids outside the current page fall back to a short suffix.
  function labelForPackingList(id: string): string {
    const pl = packingLists.find((candidate) => candidate.id === id)
    if (!pl) return `#${id.slice(0, 8)}`
    const reference = pl.reference ?? `#${id.slice(0, 8)}`
    return pl.customer_name ? `${reference} · ${pl.customer_name}` : reference
  }

  async function handleBulkSubmit(): Promise<void> {
    setBulkSubmitting(true)
    setActionError(null)
    try {
      const result = await packingListApi.bulkSubmit(Array.from(selected))
      if (result.succeeded.length) toast.success(`${result.succeeded.length} packing list${result.succeeded.length === 1 ? '' : 's'} submitted`)
      setBulkResult(result)
      await reload()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Bulk submit failed.')
    } finally {
      setBulkSubmitting(false)
    }
  }

  async function handleBulkApprove(): Promise<void> {
    setBulkSubmitting(true)
    setActionError(null)
    try {
      const result = await packingListApi.bulkApprove(Array.from(selected))
      if (result.succeeded.length) toast.success(`${result.succeeded.length} packing list${result.succeeded.length === 1 ? '' : 's'} approved`)
      setBulkResult(result)
      await reload()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Bulk approve failed.')
    } finally {
      setBulkSubmitting(false)
    }
  }

  async function handleBulkReject(comments: string): Promise<void> {
    setBulkSubmitting(true)
    setActionError(null)
    try {
      const result = await packingListApi.bulkReject(Array.from(selected), comments)
      if (result.succeeded.length) toast.success(`${result.succeeded.length} packing list${result.succeeded.length === 1 ? '' : 's'} rejected`)
      setBulkResult(result)
      setShowRejectModal(false)
      await reload()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Bulk reject failed.')
    } finally {
      setBulkSubmitting(false)
    }
  }


  return (
    <div>
      <PageHeader
        title="Packing lists"
        primary={
          session?.role === 'china_office_staff' && (
            <Button variant="primary" icon="plus" onClick={() => navigate('/packing-lists/new')}>
              Create packing list
            </Button>
          )
        }
        actions={
          session?.role === 'china_office_staff' && (
            <Button variant="secondary" icon="upload" onClick={() => navigate('/packing-lists/import')}>
              Import from Excel
            </Button>
          )
        }
      />
      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Something went wrong">{error}</Banner>
        </div>
      )}

      {bulkResult && (
        <BulkResultPanel
          result={bulkResult}
          onDismiss={() => setBulkResult(null)}
          labelFor={labelForPackingList}
        />
      )}

      {canApprove && selected.size > 0 && (
        <div className={styles.bulkBarWrap}>
          <div className={styles.bulkBar}>
            <span className={styles.bulkLabel}>
              {selected.size} packing list(s) selected
              {blockedByOwnership > 0 && (
                <span className={styles.bulkHint}>
                  {blockedByOwnership === selected.size
                    ? ' · you created all of these, so someone else must approve them'
                    : ` · ${blockedByOwnership} were created by you and need another approver`}
                </span>
              )}
            </span>
            <div className={styles.bulkActions}>
              <Pressable className={styles.bulkClearBtn} onClick={() => setSelected(new Set())}>
                Clear
              </Pressable>
              <Button
                variant="danger-ghost"
                size="sm"
                icon="x"
                onClick={() => {
                  setActionError(null)
                  setShowRejectModal(true)
                }}
              >
                Bulk reject
              </Button>
              <Button
                variant="secondary"
                size="sm"
                icon="arrowright"
                loading={bulkSubmitting}
                disabled={submittableCount === 0}
                onClick={() => void handleBulkSubmit()}
              >
                Submit for approval · {submittableCount}
              </Button>
              <Button
                variant="primary"
                size="sm"
                icon="check"
                loading={bulkSubmitting}
                disabled={approvableCount === 0}
                onClick={() => void handleBulkApprove()}
              >
                Bulk approve · {approvableCount}
              </Button>
            </div>
          </div>
        </div>
      )}

      <Card padding="default">
        <div className={styles.filterRow}>
          <div className={styles.chips}>
            <Chip active={statusFilter === null} onClick={() => setStatusFilter(null)}>
              All
            </Chip>
            {STATUS_FILTERS.map((status) => (
              <Chip key={status} active={statusFilter === status} onClick={() => setStatusFilter(status)}>
                {statusLabel('packingList', status)}
              </Chip>
            ))}
          </div>
          <SearchField label="Search packing lists" placeholder="Reference, customer name, container…" value={search} onChange={setSearch} />
        </div>
      </Card>

      <div className={styles.tableWrap}>
        {/* Without a total, a full page read as the whole result: searching a container showed 50 rows and looked
            like "this container has 50 packing lists" when it had 68. The footer states the total (FD-13: one count). */}
        <Card padding="none">
          <Table
            selectable={canApprove}
            columns={[
              { title: 'Customer' },
              { title: 'Container', type: 'reference' },
              { title: 'Packages', type: 'number' },
              { title: 'Volume (CBM)', type: 'number' },
              { title: 'Status', type: 'status' },
              { title: 'Submitted', type: 'date' },
            ]}
            rows={packingLists.map((pl) => ({
              selected: selected.has(pl.id),
              // pending_approval for bulk approve/reject, draft for bulk
              // submit (bulk_submit_packing_lists is draft-only) — these are
              // the only two bulk actions that exist, so any other status
              // (approved/rejected) has no bulk action to select it for.
              // A manifest import creates 68+ lists in draft specifically so
              // they can be bulk-submitted in one pass; excluding draft here
              // left "Submit for approval" permanently unreachable for the
              // one case it exists for.
              selectable: pl.status === 'pending_approval' || pl.status === 'draft',
              onOpen: () => navigate(`/packing-lists/${pl.id}`),
              cells: [
                <span key="customer">{pl.customer_name ?? '—'}</span>,
                <Mono key="container">{pl.container_number ?? pl.container_id}</Mono>,
                <span key="cartons">{formatPackageMix(pl.package_mix)}</span>,
                <Mono key="cbm">{formatCbm(pl.total_cbm)}</Mono>,
                <StatusBadge key="status" kind="packingList" status={pl.status} />,
                <span key="submitted" className={styles.submittedDate}>
                  {formatDate(pl.created_at, 'short')},{' '}
                  {pl.created_at.slice(11, 16)}
                </span>,
              ],
            }))}
            loading={loading}
            emptyState={!loading && packingLists.length === 0 ? <EmptyState compact title="No packing lists yet" /> : undefined}
            onSelectRow={(rowIndex, isSelected) => {
              const pl = packingLists[rowIndex]
              if (pl) toggleRow(pl.id, isSelected)
            }}
            onSelectAll={toggleAll}
          />
        </Card>
        <ListFooter
        shown={packingLists.length}
        total={totalCount}
        hasMore={hasMore}
        loading={isFetchingMore}
        onLoadMore={loadMore}
        noun={statusFilter ? 'packing lists in this status' : 'packing lists'}
        nounOne={statusFilter ? 'packing list in this status' : 'packing list'}
      />
      </div>

      {showRejectModal && (
        <BulkRejectModal
          count={selected.size}
          submitting={bulkSubmitting}
          error={error}
          onCancel={() => setShowRejectModal(false)}
          onConfirm={(comments) => void handleBulkReject(comments)}
        />
      )}
    </div>
  )
}
