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
import { ContainerStepper } from './containerDetail/Timeline'
import { DetailPage } from '../../shell/DetailPage'
import { PageHeader } from '../../shell/PageHeader'
import { Badge, Button, ConfirmDialog, StatusBadge, PageSkeleton, ErrorState } from '../../design/components'
import { Tabs } from '../../shell/Tabs'
import { InvoiceOutcomeBanner } from './InvoiceOutcomeBanner'
import { AdvanceStatusModal } from './containerDetail/AdvanceStatusModal'
import { DocumentsTab } from './containerDetail/DocumentsTab'
import { OverviewTab } from './containerDetail/OverviewTab'
import { PackingListsTab, TrackingTab } from './containerDetail/Tabs'
import { fetchAllPackingLists } from './containerDetail/packingLists'
import { toast } from '../../design/toast'
import { formatDate } from '../../lib/format'
import { nextActionLabel } from '../../design/nextAction'


export function ContainerDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { session } = useSession()
  const [tab, setTab] = useState<'overview' | 'packing-lists' | 'tracking' | 'documents'>('overview')
  const [plSearchInit, setPlSearchInit] = useState('')
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
    <>
      <DetailPage
        header={
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
              container.estimated_arrival_date &&
                `ETA ${formatDate(container.estimated_arrival_date)}`,
            ]}
            primary={
              canAdvance &&
              target && (
                <Button
                  variant="primary"
                  icon="arrowright"
                  onClick={() => setShowAdvanceModal(true)}
                >
                  {nextActionLabel('container', container.status)}
                </Button>
              )
            }
            actions={
              canAddPackingList && (
                <Button
                  variant="secondary"
                  icon="plus"
                  onClick={() => navigate(`/packing-lists/new?container_id=${encodeURIComponent(container.id)}`)}
                >
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
        }
        notices={
          invoiceResults.length > 0 && (
            <InvoiceOutcomeBanner
              containerId={container.id}
              results={invoiceResults}
              canGenerate={session ? canGenerateInvoices(session.role) : false}
              onResults={setInvoiceResults}
            />
          )
        }
        // Where the container is, on every tab (FD-19); it was only on the Overview tab.
        progress={<ContainerStepper current={container.status} />}
      >
        <div>
          <Tabs
            items={[
              { key: 'overview', label: 'Overview' },
              { key: 'packing-lists', label: 'Packing lists' },
              { key: 'tracking', label: 'Tracking' },
              { key: 'documents', label: 'Documents' },
            ]}
            active={tab}
            onChange={(key) =>
              setTab(key as 'overview' | 'packing-lists' | 'tracking' | 'documents')
            }
          />

          {tab === 'overview' && (
            <OverviewTab
              container={container}
              packingLists={packingLists}
              events={events}
              onShowTab={(nextTab) => {
                setPlSearchInit('')
                setTab(nextTab)
              }}
              onSelectCustomer={(customerName) => {
                setPlSearchInit(customerName)
                setTab('packing-lists')
              }}
            />
          )}

          {tab === 'packing-lists' && (
            <PackingListsTab
              containerId={container.id}
              packingLists={packingLists}
              canAdd={canAddPackingList}
              initialSearch={plSearchInit}
              onChanged={() => {
                void qc.invalidateQueries({ queryKey: packingListKeys.all })
                void packingListsQ.refetch()
              }}
            />
          )}

          {tab === 'tracking' && <TrackingTab container={container} events={events} />}

          {tab === 'documents' && (
            <DocumentsTab containerId={container.id} containerNumber={container.container_number} />
          )}
        </div>
      </DetailPage>
      {showAdvanceModal && target && (
        <AdvanceStatusModal
          container={container}
          target={target}
          customerCount={new Set(packingLists.map((pl) => pl.customer_id)).size}
          approvedCount={packingLists.filter((pl) => pl.status === 'approved').length}
          onClose={() => setShowAdvanceModal(false)}
          onAdvanced={(updated) => {
            const { billing_summary: summary, ...containerOnly } = updated
            qc.setQueryData(containerKeys.detail(id ?? ''), containerOnly)
            if (summary) setInvoiceResults(summary)
            setShowAdvanceModal(false)
          }}
        />
      )}

      <ConfirmDialog
        open={showDeleteModal}
        title={`Delete container ${container.container_number}?`}
        confirmLabel="Delete container"
        undo={false}
        typeToConfirm={container.container_number}
        error={actionError}
        busy={actionBusy}
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteModal(false)}
      >
        It has no packing lists, and it will be removed from ShipX.
      </ConfirmDialog>

      <ConfirmDialog
        open={showCancelModal}
        title={`Cancel container ${container.container_number}?`}
        confirmLabel="Cancel container"
        undo={false}
        error={actionError}
        busy={actionBusy}
        onConfirm={handleCancel}
        onCancel={() => setShowCancelModal(false)}
      >
        It will be marked Cancelled. Its packing lists are kept for the record, but nothing on the container can be
        changed afterwards.
      </ConfirmDialog>
    </>
  )
}
