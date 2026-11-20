import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { type InvoiceResult } from '../../api/billing'
import { canGenerateInvoices } from '../../api/billingRules'
import { ApiError } from '../../api/client'
import { canAdvanceContainerStatus, canCancelContainer, canDeleteContainer, nextContainerStatus } from '../../api/containerRules'
import { containerKeys, packingListKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { containersApi } from '../../api/tracking'
import { useSession } from '../../auth/useSession'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'
import { PageHeader } from '../../shell/PageHeader'
import { Badge, Banner, Button, StatusBadge, PageSkeleton, ErrorState } from '../../design/components'
import { Tabs } from '../../shell/Tabs'
import styles from './ContainerDetail.module.css'
import { InvoiceOutcomeBanner } from './InvoiceOutcomeBanner'
import { AdvanceStatusModal } from './containerDetail/AdvanceStatusModal'
import { DocumentsTab } from './containerDetail/DocumentsTab'
import { OverviewTab } from './containerDetail/OverviewTab'
import { PackingListsTab, TrackingTab } from './containerDetail/Tabs'
import { fetchAllPackingLists } from './containerDetail/packingLists'
import { statusLabel } from '../../design/status'
import { toast } from '../../design/toast'
import { formatDate } from '../../lib/format'


export function ContainerDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { session } = useSession()
  const [tab, setTab] = useState<'overview' | 'packing-lists' | 'tracking' | 'documents'>('overview')
  // Per-customer invoice outcome from clearing (or the last "Generate missing invoices").
  // Session-local on purpose: it answers "what just happened", and a reload shows the
  // container as it now stands.
  const [invoiceResults, setInvoiceResults] = useState<InvoiceResult[]>([])
  const qc = useQueryClient()

  // Three queries where there was one Promise.all. containerKeys.detail(id) and
  // .events(id) are the slots the container list screens already use, and
  // fetchAllPackingLists walks every page for this container, so it gets its
  // own filtered list slot.
  const plParams = { container_id: id ?? '' }
  const containerQ = useQuery({
    queryKey: containerKeys.detail(id ?? ''),
    queryFn: () => containersApi.get(id!),
    enabled: !!id,
    staleTime: STALE_30S,
  })
  const packingListsQ = useQuery({
    queryKey: packingListKeys.lookup(plParams),
    queryFn: () => fetchAllPackingLists(id!),
    enabled: !!id,
    staleTime: STALE_30S,
  })
  const eventsQ = useQuery({
    queryKey: containerKeys.events(id ?? ''),
    queryFn: () => containersApi.events(id!),
    enabled: !!id,
    staleTime: STALE_30S,
  })

  const container = containerQ.data ?? null
  const packingLists = packingListsQ.data ?? []
  const events = eventsQ.data ?? []
  const loading = containerQ.isLoading || packingListsQ.isLoading || eventsQ.isLoading
  const firstError = containerQ.error ?? packingListsQ.error ?? eventsQ.error
  const error = firstError
    ? firstError instanceof ApiError
      ? firstError.message
      : 'Could not load this container.'
    : null

  const [showAdvanceModal, setShowAdvanceModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showCancelModal, setShowCancelModal] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)




  // Names the container in the breadcrumb and tab once loaded (Containers / MSCU1234567). Called before any early
  // return (a hook).
  useBreadcrumbLabel(container?.container_number)

  if (loading && !container) {
    return <PageSkeleton kind="detail" label="Loading container" />
  }

  if (error && !container) {
    return (
      <>
        <PageHeader title="Container" />
        <ErrorState title="Couldn't load this container" error={null} message={error ?? undefined} />
      </>
    )
  }

  if (!container) return <></>

  const target = nextContainerStatus(container.status)
  const canAdvance = session && target ? canAdvanceContainerStatus(session.role, container.status) : false
  const isChinaStaff = session?.role === 'china_office_staff'
  const canAddPackingList = isChinaStaff && container.status === 'loading'
  const plCount = packingLists.length
  const canDelete = session ? canDeleteContainer(session.role, container.status, plCount) : false
  const canCancel = session ? canCancelContainer(session.role, container.status) : false

  async function handleDelete(): Promise<void> {
    if (!id) return
    setActionBusy(true)
    setActionError(null)
    try {
      await containersApi.delete(id)
      toast.success('Container deleted')
      navigate('/containers')
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not delete this container.')
      setActionBusy(false)
    }
  }

  async function handleCancel(): Promise<void> {
    if (!id) return
    setActionBusy(true)
    setActionError(null)
    try {
      const updated = await containersApi.cancel(id)
      toast.success('Container cancelled', updated.container_number)
      qc.setQueryData(containerKeys.detail(id ?? ''), updated)
      setShowCancelModal(false)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not cancel this container.')
    } finally {
      setActionBusy(false)
    }
  }
  return (
    <div>
      <PageHeader
        title={`Container ${container.container_number}`}
        status={
          <>
            <StatusBadge kind="container" status={container.status} />
            {container.container_type && (
              <Badge variant="neutral" dot={false}>
                {container.container_type}
              </Badge>
            )}
          </>
        }
        meta={[
          container.vessel_name &&
            (container.voyage_number
              ? `${container.vessel_name}, voyage ${container.voyage_number}`
              : container.vessel_name),
          `${container.origin} → ${container.destination}`,
          container.estimated_arrival_date && `ETA ${formatDate(container.estimated_arrival_date)}`,
        ]}
        primary={
          canAdvance &&
          target && (
            <Button variant="primary" icon="arrowright" onClick={() => setShowAdvanceModal(true)}>
              Advance to {statusLabel('container', target)}
            </Button>
          )
        }
        actions={
          canAddPackingList && (
            <Button variant="secondary" icon="plus" onClick={() => navigate('/packing-lists/new')}>
              Add packing list
            </Button>
          )
        }
        more={[
          ...(canCancel
            ? [
                {
                  label: 'Cancel container',
                  icon: 'warn' as const,
                  tone: 'danger' as const,
                  onSelect: () => setShowCancelModal(true),
                },
              ]
            : []),
          ...(canDelete
            ? [
                {
                  label: 'Delete container',
                  icon: 'x' as const,
                  tone: 'danger' as const,
                  onSelect: () => setShowDeleteModal(true),
                },
              ]
            : []),
        ]}
        moreLabel="More container actions"
      />

      {invoiceResults.length > 0 && (
        <>
          <InvoiceOutcomeBanner
            containerId={container.id}
            results={invoiceResults}
            canGenerate={session ? canGenerateInvoices(session.role) : false}
            onResults={setInvoiceResults}
          />
          <div className={styles.gridSpacer} />
        </>
      )}

      <Tabs
        items={[
          { key: 'overview', label: 'Overview' },
          { key: 'packing-lists', label: 'Packing lists' },
          { key: 'tracking', label: 'Tracking' },
          { key: 'documents', label: 'Documents' },
        ]}
        active={tab}
        onChange={(key) => setTab(key as 'overview' | 'packing-lists' | 'tracking' | 'documents')}
      />
      <div className={styles.tabSpacer} />

      {tab === 'overview' && <OverviewTab container={container} packingLists={packingLists} events={events} onShowTab={setTab} />}

      {tab === 'packing-lists' && <PackingListsTab packingLists={packingLists} canAdd={canAddPackingList} />}

      {tab === 'tracking' && <TrackingTab container={container} events={events} />}

      {tab === 'documents' && (
        <DocumentsTab containerId={container.id} containerNumber={container.container_number} />
      )}

      {showAdvanceModal && target && (
        <AdvanceStatusModal
          container={container}
          target={target}
          customerCount={new Set(packingLists.map((pl) => pl.customer_id)).size}
          onClose={() => setShowAdvanceModal(false)}
          onAdvanced={(updated) => {
            const { billing_summary: summary, ...containerOnly } = updated
            qc.setQueryData(containerKeys.detail(id ?? ''), containerOnly)
            if (summary) setInvoiceResults(summary)
            setShowAdvanceModal(false)
          }}
        />
      )}

      {showDeleteModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalPanel}>
            <h3 className={styles.modalTitle}>Delete container?</h3>
            <p className={styles.modalBody}>
              <strong>{container.container_number}</strong> has no packing lists and will be permanently
              removed. This cannot be undone.
            </p>
            {actionError && (
              <div className={styles.modalBanner}>
                <Banner variant="error" title="Could not delete">{actionError}</Banner>
              </div>
            )}
            <div className={styles.modalActions}>
              <Button variant="ghost" onClick={() => setShowDeleteModal(false)} disabled={actionBusy}>
                Keep container
              </Button>
              <Button
                variant="primary"
                onClick={() => void handleDelete()}
                loading={actionBusy}
                style={{ background: 'var(--color-error)', borderColor: 'var(--color-error)' }}
              >
                Delete permanently
              </Button>
            </div>
          </div>
        </div>
      )}

      {showCancelModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalPanel}>
            <h3 className={styles.modalTitle}>Cancel container?</h3>
            <p className={styles.modalBody}>
              <strong>{container.container_number}</strong> will be marked as <strong>Cancelled</strong>.
              Existing packing lists are preserved for record-keeping but no further changes can be made.
            </p>
            {actionError && (
              <div className={styles.modalBanner}>
                <Banner variant="error" title="Could not cancel">{actionError}</Banner>
              </div>
            )}
            <div className={styles.modalActions}>
              <Button variant="ghost" onClick={() => setShowCancelModal(false)} disabled={actionBusy}>
                Keep container
              </Button>
              <Button
                variant="primary"
                onClick={() => void handleCancel()}
                loading={actionBusy}
                style={{ background: 'var(--color-error)', borderColor: 'var(--color-error)' }}
              >
                Cancel container
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
