import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type JSX } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { type InvoiceResult } from '../../api/billing'
import { canGenerateInvoices } from '../../api/billingRules'
import { ApiError } from '../../api/client'
import {
  CONTAINER_STATUS_LABELS,
  canAdvanceContainerStatus,
  canCancelContainer,
  canDeleteContainer,
  containerAdvanceRequirementHint,
  containerCapacityCbm,
  nextContainerStatus,
  utilizationLevel,
} from '../../api/containerRules'
import { formatCbm } from '../../api/decimal'
import { containerKeys, packingListKeys } from '../../api/keys'
import { STALE_30S } from '../../lib/queryClient'
import { packingListApi, type PackingList } from '../../api/packingList'
import {
  containerDocumentsApi,
  containersApi,
  uploadToPresignedUrl,
  type Container,
  type ContainerDocument,
  type ContainerDocumentType,
  type ContainerEvent,
  type ContainerStatus,
  type ContainerStatusUpdate,
} from '../../api/tracking'
import { formatPackageMix } from '../../api/packingListRules'
import { useSession } from '../../auth/useSession'
import { useTopBarSlot } from '../../shell/TopBarContext'
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  Field,
  Icon,
  Kvp,
  Mono,
  Table,
  UserCell,
  ViewLink,
  DialogGuard,
  type BadgeVariant,
  type IconName,
  type TableSort,
} from '../../design/components'
import { SectionHead } from '../../shell/SectionHead'
import { Tabs } from '../../shell/Tabs'
import styles from './ContainerDetail.module.css'
import { InvoiceOutcomeBanner } from './InvoiceOutcomeBanner'
import { formatDate, formatTime } from '../../lib/format'

// Maps a status transition to a human-readable event label for the event log.
function eventLabel(from: string, to: string): string {
  if (!from) return 'Created'
  const labels: Record<string, string> = {
    sealed: 'Container sealed',
    in_transit: 'Loaded vessel',
    arrived: 'Arrived in Nigeria',
    customs_clearance: 'Customs clearance',
    at_warehouse: 'At warehouse',
    cleared: 'Cleared',
    fully_released: 'Fully released',
  }
  return labels[to] ?? `${from} → ${to}`
}

function eventBadgeVariant(toStatus: string): BadgeVariant {
  if (['cleared', 'fully_released'].includes(toStatus)) return 'success'
  if (['arrived', 'customs_clearance', 'at_warehouse'].includes(toStatus)) return 'warning'
  return 'info'
}

// Converts backend role keys to display labels for the Updated by column.
function humanRole(role: string | null): string {
  const map: Record<string, string> = {
    platform_admin: 'Platform Admin',
    tenant_admin: 'Admin',
    china_office_staff: 'China Office',
    nigeria_office_staff: 'Nigeria Office',
    warehouse_attendant: 'Warehouse',
    customer: 'Customer',
  }
  return role ? (map[role] ?? role) : '—'
}

const PL_STATUS_VARIANT: Record<PackingList['status'], BadgeVariant> = {
  draft: 'neutral',
  pending_approval: 'warning',
  approved: 'success',
  rejected: 'error',
}

// Stepper stage config — display labels/subs match the prototype exactly.
// Backend status keys are unchanged; only the visual pipeline uses these.
const STEPPER_STAGES: Array<{ status: ContainerStatus; label: string; sub: string; side: 'china' | 'ng' }> = [
  { status: 'loading',            label: 'Received',    sub: 'China warehouse', side: 'china' },
  { status: 'sealed',             label: 'Packed',      sub: 'Container sealed', side: 'china' },
  { status: 'in_transit',         label: 'In transit',  sub: 'At sea',           side: 'china' },
  { status: 'arrived',            label: 'Arrived NG',  sub: 'Tin Can Port',     side: 'ng' },
  { status: 'customs_clearance',  label: 'Customs',     sub: 'Clearance',        side: 'ng' },
  { status: 'cleared',            label: 'Cleared',     sub: 'Released',         side: 'ng' },
  { status: 'at_warehouse',       label: 'Ready',       sub: 'For pickup',       side: 'ng' },
  { status: 'fully_released',     label: 'Completed',   sub: 'Delivered',        side: 'ng' },
]

function ContainerStepper({ current }: { current: ContainerStatus }): JSX.Element {
  const currentIndex = STEPPER_STAGES.findIndex((s) => s.status === current)
  return (
    <div className={styles.stepper}>
      {STEPPER_STAGES.map(({ status, label, sub, side }, index) => {
        const done = index < currentIndex
        const isCurrent = index === currentIndex
        const color = side === 'china' ? 'var(--color-info)' : 'var(--color-primary)'
        return (
          <div key={status} className={styles.step}>
            {/* Connecting line to previous step */}
            {index > 0 && (
              <div
                className={styles.stepLine}
                style={{ background: done ? color : 'var(--color-line)' }}
              />
            )}
            <div
              className={styles.stepDot}
              style={{
                background: done ? color : isCurrent ? '#fff' : 'var(--color-surface-muted)',
                border: `${isCurrent ? 3 : 2}px solid ${done || isCurrent ? color : 'var(--color-line-strong)'}`,
                boxShadow: isCurrent ? `0 0 0 6px ${color}22` : 'none',
              }}
            >
              {done
                ? <Icon name="check" size={14} color="#fff" stroke={3} />
                : isCurrent
                  ? <span className={styles.stepDotInner} style={{ background: color }} />
                  : null}
            </div>
            <div className={styles.stepText}>
              <div className={[styles.stepLabel, done || isCurrent ? styles.stepLabelActive : ''].join(' ')}>
                {label}
              </div>
              <div className={styles.stepSub}>{sub}</div>
              {isCurrent && (
                <div className={styles.stepNow} style={{ background: color }}>Now</div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// Utilization colour by *absolute* packed CBM (business rule, not % of
// capacity): ≥70 green, 65–69 yellow, <65 red. Shared level logic +
// capacity estimate live in api/containerRules.ts; this maps the level to this
// page's CSS-module fill classes. See 10_api_tracking.md.
function utilizationColorClass(packedCbm: number): string {
  const level = utilizationLevel(packedCbm)
  if (level === 'green') return styles.utilFillGreen!
  if (level === 'yellow') return styles.utilFillYellow!
  return styles.utilFillRed!
}

function SummaryTile({ label, value, sub, accent }: {
  label: string
  value: string | number
  sub?: string
  accent?: boolean
}): JSX.Element {
  return (
    <div className={styles.summaryTile}>
      <div className={styles.summaryLabel}>{label}</div>
      <div className={[styles.summaryValue, accent ? styles.summaryValueAccent : ''].join(' ')}>{value}</div>
      {sub && <div className={styles.summarySub}>{sub}</div>}
    </div>
  )
}

// Map container status transitions to meaningful icons + colors for the event log.
function eventIconForStatus(toStatus: string): { icon: IconName; color: string } {
  if (toStatus === 'in_transit') return { icon: 'ship',      color: 'var(--color-info)' }
  if (toStatus === 'sealed')     return { icon: 'package',   color: 'var(--color-success)' }
  if (toStatus === 'cleared' || toStatus === 'fully_released')
                                  return { icon: 'check',     color: 'var(--color-success)' }
  if (toStatus === 'arrived' || toStatus === 'at_warehouse')
                                  return { icon: 'map',       color: 'var(--color-warning)' }
  return                          { icon: 'arrowright',      color: 'var(--color-ink-3)' }
}

function EventRow({ event, last }: { event: ContainerEvent; last: boolean }): JSX.Element {
  const stage = STEPPER_STAGES.find((s) => s.status === event.to_status)
  const toLabel = stage?.label ?? CONTAINER_STATUS_LABELS[event.to_status as ContainerStatus] ?? event.to_status
  const { icon, color } = eventIconForStatus(event.to_status)
  const when = formatDate(event.created_at, 'short')
  return (
    <div className={[styles.eventRow, last ? styles.eventRowLast : ''].join(' ')}>
      <div className={styles.eventIcon} style={{ background: `${color}18`, color }}>
        <Icon name={icon} size={14} />
      </div>
      <div className={styles.eventBody}>
        <div className={styles.eventTitle}>{toLabel}</div>
        {event.notes && <div className={styles.eventSub}>{event.notes}</div>}
      </div>
      <div className={styles.eventWhen}>{when}</div>
    </div>
  )
}

interface AdvanceModalProps {
  container: Container
  target: ContainerStatus
  /** Distinct customers with cargo on this container (from its packing lists). */
  customerCount: number
  onClose: () => void
  onAdvanced: (updated: ContainerStatusUpdate) => void
}

/**
 * Customer-facing side effects per stage — mirrors services/tracking/service.py:
 * `at_warehouse` enqueues a container-arrived notification to every customer on
 * the container; `cleared` publishes PaymentDue per customer (billing +
 * payment-due notifications downstream). Every other stage is silent.
 */
function customerImpactFor(target: ContainerStatus, count: number): { variant: 'warning' | 'info'; text: string } | null {
  if (target === 'at_warehouse') {
    return {
      variant: 'warning',
      text: `${count} customer${count === 1 ? '' : 's'} on this container will be notified that their cargo has arrived, via their chosen channels (SMS · WhatsApp · Email).`,
    }
  }
  if (target === 'cleared') {
    return {
      variant: 'warning',
      text: `Billing will be generated for ${count} customer${count === 1 ? '' : 's'} on this container, and each will receive a payment-due notification.`,
    }
  }
  return null
}

// 6.4 / audit gap A5 — two-step flow: details form → confirmation that spells
// out the customer-facing side effects before anything is sent.
function AdvanceStatusModal({ container, target, customerCount, onClose, onAdvanced }: AdvanceModalProps): JSX.Element {
  const [step, setStep] = useState<'form' | 'confirm'>('form')
  const [shipDate, setShipDate] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requirementHint = containerAdvanceRequirementHint(target)
  const requiresShipDate = target === 'in_transit'
  const impact = customerImpactFor(target, customerCount)

  async function handleConfirm(): Promise<void> {
    setSubmitting(true)
    setError(null)
    try {
      const updated = await containersApi.updateStatus(container.id, {
        new_status: target,
        ship_date: shipDate || undefined,
        notes: notes || undefined,
      })
      onAdvanced(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update the container status.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <DialogGuard onClose={onClose} />
      <div className={styles.modalPanel} onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className={styles.modalTitle}>
          {step === 'form'
            ? `Advance to ${CONTAINER_STATUS_LABELS[target]}`
            : `Confirm — ${CONTAINER_STATUS_LABELS[target]}`}
        </h3>
        {error && (
          <div className={styles.modalBanner}>
            <Banner variant="error">{error}</Banner>
          </div>
        )}

        {step === 'form' && (
          <>
            {requirementHint && (
              <div className={styles.modalBanner}>
                <Banner variant="info">{requirementHint}</Banner>
              </div>
            )}
            {requiresShipDate && (
              <Field
                label="Ship date"
                name="shipDate"
                type="date"
                required
                value={shipDate}
                onChange={(event) => setShipDate(event.target.value)}
              />
            )}
            <Field
              label="Notes"
              name="advanceNotes"
              optional
              multiline
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
            <div className={styles.modalActions}>
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                trailingIcon="arrowright"
                disabled={requiresShipDate && !shipDate}
                onClick={() => setStep('confirm')}
              >
                Continue
              </Button>
            </div>
          </>
        )}

        {step === 'confirm' && (
          <>
            <div className={styles.advanceSummary}>
              <Mono>{container.container_number}</Mono>
              <span className={styles.advanceSummaryArrow}>
                {CONTAINER_STATUS_LABELS[container.status]} → <strong>{CONTAINER_STATUS_LABELS[target]}</strong>
              </span>
              {shipDate && <span className={styles.advanceSummaryMeta}>Ship date: {shipDate}</span>}
            </div>
            <div className={styles.modalBanner}>
              {impact ? (
                <Banner variant={impact.variant} icon="bell" title="Customers will be contacted">
                  {impact.text}
                </Banner>
              ) : (
                <Banner variant="info">
                  No customer notifications are sent at this stage — customers see the updated tracking
                  status only.
                </Banner>
              )}
            </div>
            <div className={styles.modalActions}>
              <Button variant="ghost" icon="arrowleft" onClick={() => setStep('form')} disabled={submitting}>
                Back
              </Button>
              <Button variant="primary" icon="check" loading={submitting} onClick={() => void handleConfirm()}>
                {impact ? 'Confirm & notify' : 'Confirm'}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Documents tab — prototype 5.3/14.4 (ContainerDocs + UploadDocumentModal).
// Upload: presigned S3 POST issued by the backend, which also registers the
// document row; the list refetches after the S3 upload completes.
// ---------------------------------------------------------------------------

const DOC_TYPES: { value: ContainerDocumentType; label: string }[] = [
  { value: 'bill_of_lading', label: 'Bill of Lading' },
  { value: 'customs_certificate', label: 'Customs Certificate' },
  { value: 'insurance', label: 'Insurance' },
  { value: 'inspection_report', label: 'Inspection Report' },
  { value: 'other', label: 'Other' },
]

const DOC_ACCEPT = 'application/pdf,image/jpeg,image/png,image/webp'

function DocumentsTab({ containerId, containerNumber }: { containerId: string; containerNumber: string | null }): JSX.Element {
  const qc = useQueryClient()

  const { data: docs = [], isLoading: loading, error: loadError } = useQuery({
    queryKey: containerKeys.documents(containerId),
    queryFn: () => containerDocumentsApi.list(containerId),
    enabled: !!containerId,
    staleTime: STALE_30S,
  })

  const [actionError, setActionError] = useState<string | null>(null)

  const error =
    actionError ??
    (loadError
      ? loadError instanceof ApiError
        ? loadError.message
        : 'Could not load documents.'
      : null)

  const [showUpload, setShowUpload] = useState(false)
  const [docType, setDocType] = useState<ContainerDocumentType>('bill_of_lading')
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  // Shown inside the upload dialog: the page's own banner sits behind the dialog's overlay, where a refused file or a
  // failed upload read as "nothing happened".
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [downloadingId, setDownloadingId] = useState<string | null>(null)


  async function handleUpload(): Promise<void> {
    if (!file) return
    // The server accepts only these types and signs the declared one into the upload URL. A file the browser cannot
    // type (no extension, an unusual one) used to be sent as application/octet-stream, which let anything through.
    if (!DOC_ACCEPT.split(',').includes(file.type)) {
      setUploadError('Choose a PDF, JPEG, PNG or WebP file.')
      return
    }
    setUploading(true)
    setUploadError(null)
    try {
      const presigned = await containerDocumentsApi.presignUpload(containerId, {
        filename: file.name,
        content_type: file.type,
        document_type: docType,
      })
      await uploadToPresignedUrl(presigned, file)
      setShowUpload(false)
      setFile(null)
      // Explicit, unlike the other pages in this migration: the automatic
      // invalidation in api/client.ts fires on the presign POST, which happens
      // *before* the bytes land, and the upload itself is a direct PUT to
      // storage that never passes through the API client. So nothing would
      // otherwise tell this list the new document exists.
      await qc.invalidateQueries({ queryKey: containerKeys.documents(containerId) })
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : 'Upload failed. Please try again.')
    } finally {
      setUploading(false)
    }
  }

  async function handleDownload(doc: ContainerDocument): Promise<void> {
    setDownloadingId(doc.id)
    try {
      const { download_url } = await containerDocumentsApi.downloadUrl(containerId, doc.id)
      window.open(download_url, '_blank', 'noopener')
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not generate download link.')
    } finally {
      setDownloadingId(null)
    }
  }

  const docTypeLabel = (t: ContainerDocumentType): string => DOC_TYPES.find((d) => d.value === t)?.label ?? t

  return (
    <>
      {error && (
        <div style={{ marginBottom: 16 }}>
          <Banner variant="error" title="Documents error">{error}</Banner>
        </div>
      )}
      <Card padding={0}>
        <div className={styles.tableHead}>
          <SectionHead
            title="Documents"
            sub="Bill of lading, customs forms, inspection reports"
            action={
              <Button variant="primary" size="sm" icon="upload" onClick={() => { setUploadError(null); setFile(null); setShowUpload(true) }}>
                Upload document
              </Button>
            }
          />
        </div>
        <Table
          columns={[
            { title: 'Type' },
            { title: 'Filename' },
            { title: 'Uploaded' },
            { title: '', width: '120px' },
          ]}
          rows={docs.map((doc) => ({
            cells: [
              <span key="type" style={{ fontWeight: 600, fontSize: 13 }}>{docTypeLabel(doc.document_type)}</span>,
              <Mono key="name">{doc.filename}</Mono>,
              <span key="date" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>{formatDate(doc.created_at)}</span>,
              <Button
                key="dl"
                variant="ghost"
                size="sm"
                icon="download"
                loading={downloadingId === doc.id}
                onClick={() => void handleDownload(doc)}
              >
                Download
              </Button>,
            ],
          }))}
          emptyState={
            <span style={{ color: 'var(--color-ink-3)', fontSize: 13 }}>
              {loading ? 'Loading documents…' : 'No documents uploaded yet.'}
            </span>
          }
        />
      </Card>

      {showUpload && (
        <div className={styles.modalOverlay} onClick={() => !uploading && setShowUpload(false)}>
          <DialogGuard onClose={() => !uploading && setShowUpload(false)} />
          <div className={styles.modalPanel} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
            <h3 className={styles.modalTitle}>Upload document</h3>
            <p className={styles.modalBody}>Container {containerNumber ?? containerId}</p>
            {uploadError && (
              <div className={styles.modalBanner}>
                <Banner variant="error">{uploadError}</Banner>
              </div>
            )}

            <div>
              <label style={{ fontWeight: 600, fontSize: '0.875rem', display: 'block', marginBottom: 6 }}>
                Document type <span style={{ color: 'var(--color-error)' }}>*</span>
              </label>
              <select
                style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--color-line)', background: 'var(--color-surface)', fontSize: '0.875rem' }}
                value={docType}
                onChange={(e) => setDocType(e.target.value as ContainerDocumentType)}
              >
                {DOC_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>

            <div style={{ marginTop: 12 }}>
              <label style={{ fontWeight: 600, fontSize: '0.875rem', display: 'block', marginBottom: 6 }}>
                File <span style={{ color: 'var(--color-error)' }}>*</span>
              </label>
              <input
                type="file"
                accept={DOC_ACCEPT}
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null)
                  setUploadError(null)
                }}
                style={{ fontSize: '0.8125rem' }}
              />
              <div style={{ fontSize: 11, color: 'var(--color-ink-4)', marginTop: 6 }}>
                Accepted: PDF, JPG, PNG, WebP
              </div>
            </div>

            <div className={styles.modalActions}>
              <Button variant="ghost" onClick={() => setShowUpload(false)} disabled={uploading}>Cancel</Button>
              <Button variant="primary" icon="upload" loading={uploading} disabled={!file} onClick={() => void handleUpload()}>
                Upload
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

/**
 * Fetch every packing list on a container, following the cursor to the end.
 *
 * The overview's cargo summary (customer count, cartons, CBM) and the
 * packing-lists tab both aggregate this list in memory, so a single page is not
 * enough: the endpoint returns 50 by default, and a real forwarder manifest
 * routinely exceeds that (the STL409 export alone creates 68). Fetching one
 * page made the page silently under-report its own totals — 50 customers and
 * 35.77 CBM against an actual 68 and 72.55.
 *
 * `_MAX_PAGES` is a guard against a malformed cursor looping forever, not an
 * expected ceiling; at 100 rows per page it covers 10k packing lists.
 */
const _MAX_PAGES = 100

async function fetchAllPackingLists(containerId: string): Promise<PackingList[]> {
  const all: PackingList[] = []
  let cursor: string | undefined
  for (let page = 0; page < _MAX_PAGES; page += 1) {
    const result = await packingListApi.listByContainer(containerId, { limit: 100, cursor })
    all.push(...result.data)
    const next = result.meta?.pagination?.next_cursor
    if (!result.meta?.pagination?.has_more || !next) break
    cursor = next
  }
  return all
}

export function ContainerDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { session } = useSession()
  const [tab, setTab] = useState<'overview' | 'packing-lists' | 'tracking' | 'documents'>('overview')
  // Per-customer invoice outcome from clearing (or the last "Generate missing invoices").
  // Session-local on purpose: it answers "what just happened", and a reload shows the
  // container as it now stands.
  const [invoiceResults, setInvoiceResults] = useState<InvoiceResult[]>([])
  // 'Ref #' sort on the packing-lists sub-table — this list is already fully
  // loaded in memory for one container (not a paginated endpoint), so sorting
  // is pure client-side: no query param, no backend change.
  const [plSortDirection, setPlSortDirection] = useState<TableSort['direction'] | null>(null)
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

  // Hooks must run unconditionally on every render — declared here, before
  // the loading/error/not-found early returns below, rather than alongside
  // the other packingLists-derived aggregates further down.
  const sortedPackingLists = useMemo(() => {
    if (!plSortDirection) return packingLists
    const sorted = [...packingLists].sort((a, b) =>
      (a.reference ?? '').localeCompare(b.reference ?? ''),
    )
    return plSortDirection === 'asc' ? sorted : sorted.reverse()
  }, [packingLists, plSortDirection])


  // Must be called unconditionally (before any early returns) — React hook rules.
  // The suffix is null until the container loads, then becomes the container number,
  // giving the TopBar breadcrumb: Operations / Containers / MSCU1234567.
  useTopBarSlot({ suffix: container?.container_number ?? null })

  if (loading && !container) {
    return <div className={styles.loadingState}>Loading container…</div>
  }

  if (error && !container) {
    return (
      <div className={styles.banner}>
        <Banner variant="error" title="Couldn't load this container">{error}</Banner>
      </div>
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
      qc.setQueryData(containerKeys.detail(id ?? ''), updated)
      setShowCancelModal(false)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Could not cancel this container.')
    } finally {
      setActionBusy(false)
    }
  }
  const approvedCount = packingLists.filter((pl) => pl.status === 'approved').length

  const plTableSort: TableSort | undefined =
    plSortDirection ? { columnIndex: 0, direction: plSortDirection } : undefined

  function togglePlSort(): void {
    setPlSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
  }

  // Cargo summary aggregates, derived from the container's packing lists.
  const distinctCustomers = new Set(packingLists.map((pl) => pl.customer_id)).size
  // Packages, not item rows: since a manifest row became a bulk quantity, a
  // row count under-reports what is physically in the container (STL409: 81
  // rows vs 437 actual packages).
  const totalCartons = packingLists.reduce((sum, pl) => sum + (pl.package_count ?? pl.carton_count), 0)
  const containerPackageMix = packingLists.reduce<Record<string, number>>((acc, pl) => {
    for (const [unit, count] of Object.entries(pl.package_mix ?? {})) {
      acc[unit] = (acc[unit] ?? 0) + count
    }
    return acc
  }, {})
  const totalCbm = packingLists.reduce((sum, pl) => sum + Number(pl.total_cbm ?? 0), 0)
  const capacityCbm =
    container.capacity_cbm != null && Number(container.capacity_cbm) > 0
      ? Number(container.capacity_cbm)
      : containerCapacityCbm(container.container_type)
  const recommendedCbm =
    container.recommended_cbm != null && Number(container.recommended_cbm) > 0
      ? Number(container.recommended_cbm)
      : null
  const utilizationPct = capacityCbm ? Math.min((totalCbm / capacityCbm) * 100, 100) : null

  // Group packing lists by customer for the "customers on this container" table.
  const customerGroups = Object.values(
    packingLists.reduce<
      Record<string, { name: string; phone: string | null; cartons: number; cbm: number; allApproved: boolean }>
    >(
      (acc, pl) => {
        const key = pl.customer_id
        acc[key] ??= {
          name: pl.customer_name ?? '—',
          phone: pl.customer_phone ?? null,
          cartons: 0,
          cbm: 0,
          allApproved: true,
        }
        acc[key].cartons += pl.package_count ?? pl.carton_count
        acc[key].cbm += Number(pl.total_cbm ?? 0)
        if (pl.status !== 'approved') acc[key].allApproved = false
        return acc
      },
      {},
    ),
  ).sort((a, b) => b.cbm - a.cbm)

  // The overview shows only the top shippers by CBM as a compact ranked list —
  // a container can hold 60–100+ customers (STL409 alone has 68), and an
  // uncapped table would bury the rest of the overview. The full per-customer
  // breakdown lives on the Packing lists tab (searchable/sortable).
  const TOP_SHIPPERS_CAP = 5
  const topShippers = customerGroups.slice(0, TOP_SHIPPERS_CAP)
  const hasMoreCustomers = customerGroups.length > TOP_SHIPPERS_CAP

  // Last 5 tracking events, newest first, for the overview.
  const recentEvents = [...events].reverse().slice(0, 5)

  return (
    <div>
      <div className={styles.hero}>
        <div className={styles.heroLeft}>
          <div className={styles.heroIcon}>
            <Icon name="container" size={28} stroke={2} />
          </div>
          <div>
            <div className={styles.heroTitleRow}>
              <h1 className={styles.heroTitle}>{container.container_number}</h1>
              <Badge variant="info">{CONTAINER_STATUS_LABELS[container.status]}</Badge>
              {container.container_type && (
                <Badge variant="neutral" dot={false}>{container.container_type}</Badge>
              )}
            </div>
            <div className={styles.heroMeta}>
              {container.vessel_name && (
                <span>
                  {container.vessel_name}
                  {container.voyage_number && <> · Voy {container.voyage_number}</>} ·{' '}
                </span>
              )}
              <span>
                {container.origin} <Mono>→</Mono> {container.destination}
              </span>
              {container.estimated_arrival_date && <span>· ETA {container.estimated_arrival_date}</span>}
            </div>
          </div>
        </div>
        <div className={styles.heroActions}>
          {canCancel && (
            <Button variant="ghost" icon="warn" onClick={() => setShowCancelModal(true)}>
              Cancel container
            </Button>
          )}
          {canDelete && (
            <Button variant="ghost" icon="x" onClick={() => setShowDeleteModal(true)}>
              Delete
            </Button>
          )}
          {canAddPackingList && (
            <Button variant="secondary" icon="plus" onClick={() => navigate('/packing-lists/new')}>
              Add packing list
            </Button>
          )}
          {canAdvance && target && (
            <Button variant="primary" icon="arrowright" onClick={() => setShowAdvanceModal(true)}>
              Advance to {CONTAINER_STATUS_LABELS[target]}
            </Button>
          )}
        </div>
      </div>

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

      {tab === 'overview' && (
        <>
          <Card>
            <SectionHead title="Tracking pipeline" sub="China-side stages in blue · Nigeria-side stages in green" />
            <div className={styles.stepperSpacer} />
            <ContainerStepper current={container.status} />
          </Card>
          <div className={styles.gridSpacer} />
          <div className={styles.grid2}>
            <Card>
              <SectionHead title="Container info" />
              <Kvp label="Container #" value={<Mono>{container.container_number}</Mono>} />
              <Kvp label="Container type" value={container.container_type ?? '—'} />
              <Kvp label="Seal #" value={container.seal_number ? <Mono>{container.seal_number}</Mono> : '—'} />
              <Kvp label="Vessel" value={container.vessel_name ?? '—'} />
              <Kvp label="Voyage" value={container.voyage_number ? <Mono>{container.voyage_number}</Mono> : '—'} />
              <Kvp label="Shipping line" value={container.shipping_line ?? '—'} />
              <Kvp
                label="Created by"
                value={
                  container.created_by_name
                    ? `${container.created_by_name} · ${formatDate(container.created_at)}`
                    : formatDate(container.created_at)
                }
                divider={false}
              />
            </Card>
            <Card>
              <SectionHead title="Cargo summary" sub="Aggregated from all packing lists" />
              <div className={styles.summaryGrid}>
                <SummaryTile label="Customers" value={distinctCustomers} sub="on this container" />
                <SummaryTile
                  label="Packing lists"
                  value={`${approvedCount} / ${packingLists.length}`}
                  sub="approved"
                  accent
                />
                <SummaryTile
                  label="Total packages"
                  value={totalCartons}
                  sub={formatPackageMix(containerPackageMix)}
                />
                <SummaryTile label="Total CBM" value={totalCbm.toFixed(2)} sub={capacityCbm ? `of ${capacityCbm} capacity` : 'packed'} />
              </div>
              {utilizationPct != null && (
                <div className={styles.utilBox}>
                  <div className={styles.utilHead}>
                    <span className={styles.utilLabel}>Utilization</span>
                    <span className={styles.utilPct}>{utilizationPct.toFixed(1)}%</span>
                  </div>
                  <div className={styles.utilTrack}>
                    <div
                      className={[styles.utilFill, utilizationColorClass(totalCbm)].join(' ')}
                      style={{ width: `${utilizationPct}%` }}
                    />
                  </div>
                  <div className={styles.utilSub}>
                    {totalCbm.toFixed(2)} of {capacityCbm} CBM packed · room for{' '}
                    {Math.max(capacityCbm! - totalCbm, 0).toFixed(2)} more
                    {recommendedCbm ? ` · recommended ${recommendedCbm} CBM` : ''}
                  </div>
                </div>
              )}
            </Card>
          </div>

          <div className={styles.gridSpacer} />
          <div className={styles.grid2}>
            <Card padding={0}>
              <div className={styles.tableHead}>
                <SectionHead title="Recent events" sub="Last 5 tracking events" />
                {events.length > 5 && (
                  <button type="button" className={styles.viewAllLink} onClick={() => setTab('tracking')}>
                    View all →
                  </button>
                )}
              </div>
              <div className={styles.eventList}>
                {recentEvents.length === 0 ? (
                  <div className={styles.eventEmpty}>No tracking events yet.</div>
                ) : (
                  recentEvents.map((event, index) => (
                    <EventRow key={event.id} event={event} last={index === recentEvents.length - 1} />
                  ))
                )}
              </div>
            </Card>

            <Card>
              <div className={styles.tableHead}>
                <SectionHead
                  title="Top shippers by CBM"
                  sub={`${distinctCustomers} customer${distinctCustomers === 1 ? '' : 's'} on this container`}
                />
                {hasMoreCustomers && (
                  <button
                    type="button"
                    className={styles.viewAllLink}
                    onClick={() => setTab('packing-lists')}
                  >
                    View all →
                  </button>
                )}
              </div>
              {topShippers.length === 0 ? (
                <div className={styles.shipperEmpty}>No customers yet.</div>
              ) : (
                <div className={styles.shipperList}>
                  {topShippers.map((group) => {
                    const share = totalCbm > 0 ? (group.cbm / totalCbm) * 100 : 0
                    return (
                      <div key={group.name} className={styles.shipperRow}>
                        <Avatar size={28} name={group.name} roleColor="nigeria" />
                        <div className={styles.shipperBody}>
                          <div className={styles.shipperTop}>
                            <span className={styles.shipperName} title={group.name}>{group.name}</span>
                            <span className={styles.shipperCbm}>
                              <Mono>{group.cbm.toFixed(2)}</Mono> CBM
                            </span>
                          </div>
                          <div className={styles.shipperBarRow}>
                            <div className={styles.shipperBarTrack}>
                              <div className={styles.shipperBarFill} style={{ width: `${share}%` }} />
                            </div>
                            <span className={styles.shipperPct}>{share.toFixed(0)}%</span>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </Card>
          </div>
        </>
      )}

      {tab === 'packing-lists' && (
        <Card padding={0}>
          <div className={styles.tableHead}>
            <SectionHead title="Packing lists on this container" sub={`${packingLists.length} list(s)`} />
            {canAddPackingList && (
              <Button variant="primary" size="sm" icon="plus" onClick={() => navigate('/packing-lists/new')}>
                Add packing list
              </Button>
            )}
          </div>
          <Table
            columns={[
              { title: 'Ref #', sortable: true },
              { title: 'Customer' },
              { title: 'Contact' },
              { title: 'Packages' },
              { title: 'CBM', align: 'right' },
              { title: 'Weight', align: 'right' },
              { title: 'Status' },
              { title: 'Submitted' },
              { title: '', width: '60px' },
            ]}
            rows={sortedPackingLists.map((pl) => ({
              cells: [
                <Mono key="ref" color="var(--color-ink)">{pl.reference ?? '—'}</Mono>,
                <span key="customer">{pl.customer_name ?? '—'}</span>,
                pl.customer_phone
                  ? <Mono key="phone">{pl.customer_phone}</Mono>
                  : <span key="phone" style={{ color: 'var(--color-ink-4)' }}>—</span>,
                <span key="cartons">{formatPackageMix(pl.package_mix)}</span>,
                <Mono key="cbm">{formatCbm(pl.total_cbm)}</Mono>,
                <Mono key="weight">{pl.total_weight_kg ? `${Number(pl.total_weight_kg).toFixed(1)} kg` : '—'}</Mono>,
                <Badge key="status" variant={PL_STATUS_VARIANT[pl.status]}>
                  {pl.status.replace('_', ' ')}
                </Badge>,
                <span key="submitted" className={styles.metaText}>
                  {formatDate(pl.created_at, 'short')}
                </span>,
                <ViewLink key="view" onClick={() => navigate(`/packing-lists/${pl.id}`)} />,
              ],
            }))}
            emptyState={<span>No packing lists yet — add one to get started.</span>}
            sort={plTableSort}
            onSort={togglePlSort}
          />
        </Card>
      )}

      {tab === 'tracking' && (
        <>
          <Card>
            <SectionHead
              title="Tracking timeline"
              sub={`All status events for ${container.container_number}`}
            />
            <div className={styles.stepperSpacer} />
            <ContainerStepper current={container.status} />
          </Card>
          <div className={styles.gridSpacer} />
          <Card padding={0}>
            <div className={styles.tableHead}>
              <SectionHead
                title="Event log"
                sub="All tracking events, newest first"
                action={
                  <Button variant="secondary" size="sm" icon="download">Export</Button>
                }
              />
            </div>
            <Table
              columns={[
                { title: 'Timestamp' },
                { title: 'Event' },
                { title: 'Status change' },
                { title: 'Updated by' },
                { title: 'Notes' },
              ]}
              rows={[...events].reverse().map((event) => ({
                cells: [
                  <Mono key="ts">
                    {formatDate(event.created_at, 'short')}
                    {' '}
                    {formatTime(event.created_at)}
                  </Mono>,
                  <Badge key="event" variant={eventBadgeVariant(event.to_status)}>
                    {eventLabel(event.from_status, event.to_status)}
                  </Badge>,
                  <span key="change" className={styles.statusChange}>
                    <span className={styles.statusFrom}>
                      {CONTAINER_STATUS_LABELS[event.from_status as ContainerStatus] ?? event.from_status}
                    </span>
                    <span className={styles.statusArrow}>→</span>
                    <strong className={styles.statusTo}>
                      {CONTAINER_STATUS_LABELS[event.to_status as ContainerStatus] ?? event.to_status}
                    </strong>
                  </span>,
                  event.actor_name
                    ? <UserCell key="actor" name={event.actor_name} email={humanRole(event.actor_role)} />
                    : <span key="actor" className={styles.eventNote}>—</span>,
                  <span key="notes" className={styles.eventNote}>{event.notes ?? '—'}</span>,
                ],
              }))}
              emptyState={<span>No tracking events yet.</span>}
            />
          </Card>
        </>
      )}

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
