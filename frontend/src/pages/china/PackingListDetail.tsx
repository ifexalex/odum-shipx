import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { formatCbm } from '../../api/decimal'
import { packingListApi, type PackingList, type PackingListItem, type UpdatePackingListItemInput } from '../../api/packingList'
import { packingListKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { canApproveOrReject, canEditPackingList, computeCbm, formatPackageMix, formatPackageUnit } from '../../api/packingListRules'
import { useSession } from '../../auth/useSession'
import { Badge, Banner, Button, Card, DialogGuard, ExportButton, Field, Mono, StatusBadge, Table, IconButton, CellInput, PageSkeleton, EmptyState, ErrorState } from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import styles from './PackingListDetail.module.css'
import { formatDate } from '../../lib/format'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'
import { PageHeader } from '../../shell/PageHeader'
import { toast } from '../../design/toast'

interface RejectModalProps {
  onCancel: () => void
  onConfirm: (comments: string) => void
  submitting: boolean
  error: string | null
}

function RejectModal({ onCancel, onConfirm, submitting, error }: RejectModalProps): JSX.Element {
  const [comments, setComments] = useState('')
  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <DialogGuard onClose={onCancel} />
      <div className={styles.modalPanel} onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>Reject packing list</h3>
        {error && (
          <div className={styles.banner}>
            <Banner variant="error" title="Action failed">{error}</Banner>
          </div>
        )}
        <Field
          label="Comments"
          name="rejectComments"
          required
          multiline
          placeholder="What needs to change before this can be resubmitted?"
          value={comments}
          onChange={(event) => setComments(event.target.value)}
        />
        <div className={styles.modalActions}>
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="danger" loading={submitting} disabled={!comments.trim()} onClick={() => onConfirm(comments)}>
            Confirm reject
          </Button>
        </div>
      </div>
    </div>
  )
}

/**
 * "16 bags", or "1 BIG BALE · No. 2" for bale rows.
 *
 * Since a manifest row became a bulk quantity, the tag alone no longer says
 * what a line actually is — staff need to see bale vs carton on the row.
 * `quantity_raw` is shown when the source cell was compound (e.g.
 * "3bags2ctns1pallet" normalises to a mixed count) so nothing is lost.
 */
function PackageCell({ item }: { item: PackingListItem | undefined }): JSX.Element {
  if (!item) return <span>—</span>
  const unit = item.package_unit ?? null
  const qty = item.quantity ?? 1
  if (!unit && item.quantity == null) return <span className={styles.metaText}>—</span>
  return (
    <span>
      {item.bale_type ? `${qty} × ${item.bale_type}` : formatPackageUnit(unit, qty)}
      {item.bale_no && <span className={styles.metaText}> · No. {item.bale_no}</span>}
      {item.quantity_raw && unit === 'mixed' && (
        <span className={styles.metaText}> · {item.quantity_raw}</span>
      )}
    </span>
  )
}

export function PackingListDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { session } = useSession()
  const qc = useQueryClient()

  const { data: pl = null, isLoading: loading, error: loadError, refetch } = useQuery({
    queryKey: packingListKeys.detail(id ?? ''),
    queryFn: () => packingListApi.get(id!),
    enabled: !!id,
    staleTime: STALE_30S,
  })
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(pl?.reference)

  const [actionError, setActionError] = useState<string | null>(null)

  const error =
    actionError ??
    (loadError
      ? loadError instanceof ApiError
        ? loadError.message
        : 'Could not load this packing list.'
      : null)

  // Each mutation returns the updated packing list, so it goes straight into
  // the cache. api/cacheInvalidation.ts also invalidates packingListKeys.all
  // for /v1/packing-lists writes, which reconciles against the server.
  const setPl = (updated: PackingList): void => {
    qc.setQueryData(packingListKeys.detail(id ?? ''), updated)
  }
  const [showRejectModal, setShowRejectModal] = useState(false)
  const [actionSubmitting, setActionSubmitting] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editItems, setEditItems] = useState<UpdatePackingListItemInput[]>([])

  function emptyEditItem(): UpdatePackingListItemInput {
    return { description: '' }
  }


  async function handleApprove(): Promise<void> {
    if (!pl) return
    setActionSubmitting(true)
    setActionError(null)
    try {
      const updated = await packingListApi.approve(pl.id)
      toast.success('Packing list approved', updated.reference ?? undefined)
      setPl(updated)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not approve this packing list.')
    } finally {
      setActionSubmitting(false)
    }
  }

  async function handleReject(comments: string): Promise<void> {
    if (!pl) return
    setActionSubmitting(true)
    setActionError(null)
    try {
      const updated = await packingListApi.reject(pl.id, { comments })
      toast.success('Packing list rejected', updated.reference ?? undefined)
      setPl(updated)
      setShowRejectModal(false)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not reject this packing list.')
    } finally {
      setActionSubmitting(false)
    }
  }

  function startEditing(): void {
    if (!pl) return
    setActionError(null)
    setEditItems(pl.items.map((item) => ({
      id: item.id,
      description: item.description,
      weight_actual_kg:    item.weight_actual_kg    != null ? Number(item.weight_actual_kg)    : undefined,
      length_cm:           item.length_cm           != null ? Number(item.length_cm)           : undefined,
      width_cm:            item.width_cm            != null ? Number(item.width_cm)            : undefined,
      height_cm:           item.height_cm           != null ? Number(item.height_cm)           : undefined,
      declared_value_usd:  item.declared_value_usd  != null ? Number(item.declared_value_usd)  : undefined,
    })))
    setEditing(true)
  }

  function updateEditItem(index: number, patch: Partial<UpdatePackingListItemInput>): void {
    setEditItems((prev) => prev.map((it, i) => (i === index ? { ...it, ...patch } : it)))
  }

  function removeEditItem(index: number): void {
    setEditItems((prev) => prev.filter((_, i) => i !== index))
  }

  async function handleSubmitForApproval(): Promise<void> {
    if (!pl) return
    setActionSubmitting(true)
    setActionError(null)
    try {
      const submitted = await packingListApi.submit(pl.id)
      toast.success('Packing list submitted for approval', submitted.reference ?? undefined)
      setPl(submitted)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not submit this packing list for approval.')
    } finally {
      setActionSubmitting(false)
    }
  }

  async function handleResubmit(): Promise<void> {
    if (!pl) return
    setActionSubmitting(true)
    try {
      const updated = await packingListApi.update(pl.id, { items: editItems })
      const resubmitted = await packingListApi.submit(updated.id)
      toast.success('Packing list resubmitted', resubmitted.reference ?? undefined)
      setPl(resubmitted)
      setEditing(false)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not resubmit this packing list.')
    } finally {
      setActionSubmitting(false)
    }
  }

  if (loading && !pl) return <PageSkeleton kind="detail" label="Loading packing list" />
  if (error && !pl) {
    return (
      <>
        <PageHeader title="Packing list" />
        <ErrorState title="Couldn't load this packing list" error={loadError} message="We couldn't find this record. It may have been removed, or the link is out of date." onRetry={() => void refetch()} />
      </>
    )
  }
  if (!pl) return <></>

  const canAct = session ? canApproveOrReject(pl, session.role, session.userId) : false
  const canEdit = canEditPackingList(pl) && pl.status === 'rejected'
  const canSubmitDraft = pl.status === 'draft' && pl.items.length > 0 && canEditPackingList(pl)
  const lastRejection = pl.approval_comments?.[pl.approval_comments.length - 1] ?? null
  const rejectedItemIds = new Set(lastRejection?.item_rejections?.map((r) => r.item_id) ?? [])
  // "cartons" was hardcoded, so a list of bales read "2 cartons". Derive the
  // real mix from the items instead of assuming a unit.
  const itemPackageMix = pl.items.reduce<Record<string, number>>((acc, item) => {
    const unit = item.package_unit || 'unspecified'
    acc[unit] = (acc[unit] ?? 0) + (item.quantity ?? 1)
    return acc
  }, {})
  const packageSummary = formatPackageMix(itemPackageMix)

  const showFlagColumn = pl.status === 'rejected' && !editing

  return (
    <div>
      <PageHeader
        title={pl.reference ? `Packing list ${pl.reference}` : 'Packing list'}
        status={<StatusBadge kind="packingList" status={pl.status} />}
        meta={[
          pl.customer_name,
          <Mono>{pl.container_number ?? pl.container_id}</Mono>,
          `${packageSummary}, ${formatCbm(pl.total_cbm)} CBM`,
          pl.arrival_warehouse_name && `To ${pl.arrival_warehouse_name}`,
          `Submitted ${formatDate(pl.created_at)}`,
        ]}
        primary={
          editing ? null : canAct ? (
            <Button variant="primary" icon="check" loading={actionSubmitting} onClick={() => void handleApprove()}>
              Approve
            </Button>
          ) : canSubmitDraft ? (
            <Button variant="primary" icon="check" loading={actionSubmitting} onClick={() => void handleSubmitForApproval()}>
              Submit for approval
            </Button>
          ) : canEdit ? (
            <Button variant="primary" icon="edit" onClick={startEditing}>
              Edit &amp; resubmit
            </Button>
          ) : null
        }
        actions={
          <>
            {canAct && !editing && (
              <Button
                variant="danger-ghost"
                icon="x"
                onClick={() => {
                  setActionError(null)
                  setShowRejectModal(true)
                }}
              >
                Reject
              </Button>
            )}
            {pl.status === 'draft' && !editing && (
              <Button variant="secondary" icon="edit" onClick={() => navigate(`/packing-lists/${pl.id}/edit`)}>
                Edit
              </Button>
            )}
            <ExportButton
              formats={['xlsx', 'csv', 'pdf']}
              onExport={(fmt) => (fmt === 'pdf' ? packingListApi.pdf(pl.id) : packingListApi.export(pl.id, fmt))}
            />
          </>
        }
        more={[{ label: 'Print view', icon: 'file', onSelect: () => navigate(`/packing-lists/${pl.id}/print`) }]}
        moreLabel="More packing list actions"
      />

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Action failed">{error}</Banner>
        </div>
      )}

      {pl.status === 'approved' && pl.approved_by && (
        <div className={styles.banner}>
          <Banner variant="success" title={
            pl.approved_by_name
              ? `Approved by ${pl.approved_by_name}${pl.approved_at ? ` on ${pl.approved_at.slice(0, 16).replace('T', ' at ')}` : ''}`
              : `Approved on ${pl.approved_at?.slice(0, 16).replace('T', ' at ') ?? ''}`
          }>
            This packing list is locked. Cartons are attached to{' '}
            <strong>{pl.container_number ?? 'this container'}</strong>. To make changes,
            contact your admin to revoke approval first.
          </Banner>
        </div>
      )}
      {pl.status === 'rejected' && lastRejection && (
        <div className={styles.banner}>
          <Banner variant="error" title={
            pl.rejected_by_name
              ? `Rejected by ${pl.rejected_by_name}${pl.rejected_at ? ` on ${pl.rejected_at.slice(0, 16).replace('T', ' at ')}` : ''}`
              : 'Rejected'
          }>
            Comments: &ldquo;{lastRejection.comments}&rdquo;
          </Banner>
        </div>
      )}

      <Card padding="none">
        <div className={styles.itemsHead}>
          <SectionHead
            title="Items"
            sub={editing
              ? `${editItems.length} item(s)`
              : `${packageSummary} · ${pl.total_weight_kg} kg · ${formatCbm(pl.total_cbm)} CBM`}
          />
          {editing && (
            <Button
              variant="primary"
              size="sm"
              icon="plus"
              onClick={() => setEditItems((prev) => [...prev, emptyEditItem()])}
            >
              Add item
            </Button>
          )}
        </div>

        <Table
          columns={[
            { title: 'Tag', type: 'reference' as const },
            { title: 'Description' },
            { title: 'Packages', type: 'number' as const },
            { title: 'Weight (kg)', type: 'number' as const },
            { title: 'L × W × H (cm)', align: 'center' },
            { title: 'Volume (CBM)', type: 'number' as const },
            { title: 'Declared ($)', type: 'money' as const },
            ...(showFlagColumn ? [{ title: 'Flag' }] : []),
            ...(editing ? [{ title: '', type: 'action' as const, width: '40px' }] : []),
          ]}
          rows={editing
            ? editItems.map((item, index) => {
                const liveCbm =
                  item.length_cm != null && item.width_cm != null && item.height_cm != null
                    ? computeCbm(item.length_cm, item.width_cm, item.height_cm)
                    : null
                return {
                  cells: [
                    <span key="tag" className={styles.tagReadOnly}>
                      {pl.items[index]?.carton_tag ?? <em className={styles.newItemTag}>New</em>}
                    </span>,
                    <CellInput
                        label={`Description, item ${index + 1}`}
                      key="desc"
                      className={styles.cellInput}
                      value={item.description}
                      placeholder="Description"
                      onChange={(e) => updateEditItem(index, { description: e.target.value })}
                    />,
                    <PackageCell key="pkg" item={pl.items[index]} />,
                    <CellInput
                        label={`Actual weight (kg), item ${index + 1}`}
                      key="weight"
                      className={styles.cellInputNumber}
                      type="number"
                      value={item.weight_actual_kg ?? ''}
                      onChange={(e) => updateEditItem(index, { weight_actual_kg: Number(e.target.value) || undefined })}
                    />,
                    <div key="dim" className={styles.dimRow}>
                      <CellInput
                        label={`Length (cm), item ${index + 1}`}
                        className={styles.dimInput}
                        type="number"
                        value={item.length_cm ?? ''}
                        onChange={(e) => updateEditItem(index, { length_cm: Number(e.target.value) || undefined })}
                      />
                      <span>×</span>
                      <CellInput
                        label={`Width (cm), item ${index + 1}`}
                        className={styles.dimInput}
                        type="number"
                        value={item.width_cm ?? ''}
                        onChange={(e) => updateEditItem(index, { width_cm: Number(e.target.value) || undefined })}
                      />
                      <span>×</span>
                      <CellInput
                        label={`Height (cm), item ${index + 1}`}
                        className={styles.dimInput}
                        type="number"
                        value={item.height_cm ?? ''}
                        onChange={(e) => updateEditItem(index, { height_cm: Number(e.target.value) || undefined })}
                      />
                    </div>,
                    <Mono key="cbm" color="var(--color-success)">
                      {liveCbm != null ? liveCbm.toFixed(3) : '—'}
                    </Mono>,
                    <CellInput
                        label={`Declared value (USD), item ${index + 1}`}
                      key="usd"
                      className={styles.cellInputNumber}
                      type="number"
                      value={item.declared_value_usd ?? ''}
                      onChange={(e) => updateEditItem(index, { declared_value_usd: Number(e.target.value) || undefined })}
                    />,
                    <IconButton
                      key="remove"
                      icon="x"
                      variant="danger-ghost"
                      size="sm"
                      label={`Remove item ${index + 1}`}
                      disabled={editItems.length === 1}
                      onClick={() => removeEditItem(index)}
                    />,
                  ],
                }
              })
            : pl.items.map((item) => ({
                cells: [
                  <Mono key="tag">{item.carton_tag ?? '—'}</Mono>,
                  <span key="desc">{item.description}</span>,
                  <PackageCell key="pkg" item={item} />,
                  <Mono key="weight">{item.weight_actual_kg != null ? `${item.weight_actual_kg} kg` : '—'}</Mono>,
                  <Mono key="dim">
                    {item.length_cm != null && item.width_cm != null && item.height_cm != null
                      ? `${item.length_cm} × ${item.width_cm} × ${item.height_cm}`
                      : '—'}
                  </Mono>,
                  <Mono key="cbm" color="var(--color-success)">{formatCbm(item.cbm)}</Mono>,
                  <Mono key="usd">{item.declared_value_usd != null ? `$${item.declared_value_usd}` : '—'}</Mono>,
                  ...(showFlagColumn
                    ? [rejectedItemIds.has(item.id)
                        ? <Badge key="flag" variant="error" size="sm">Re-check</Badge>
                        : <span key="flag" className={styles.flagOk}>OK</span>]
                    : []),
                ],
              }))
          }
          emptyState={<EmptyState compact title="No carton items" />}
        />

        {!editing && (
          <div className={styles.totalsRow}>
            <span>{packageSummary}</span>
            <span>· <span className={styles.totalsLabel}>Weight:</span> <Mono>{pl.total_weight_kg} kg</Mono></span>
            <span>· <span className={styles.totalsLabel}>CBM:</span> <Mono color="var(--color-success)">{formatCbm(pl.total_cbm)}</Mono></span>
          </div>
        )}

        {editing && (
          <div className={styles.editActions}>
            <Button variant="ghost" onClick={() => setEditing(false)} disabled={actionSubmitting}>
              Cancel
            </Button>
            <Button
              variant="primary"
              icon="check"
              loading={actionSubmitting}
              disabled={editItems.length === 0 || editItems.some((it) => !it.description.trim())}
              onClick={() => void handleResubmit()}
            >
              Save &amp; resubmit
            </Button>
          </div>
        )}
      </Card>

      {showRejectModal && (
        <RejectModal
          submitting={actionSubmitting}
          error={error}
          onCancel={() => setShowRejectModal(false)}
          onConfirm={(comments) => void handleReject(comments)}
        />
      )}
    </div>
  )
}
