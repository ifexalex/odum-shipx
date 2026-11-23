import { useQuery } from '@tanstack/react-query'
import { useMemo, useState, type JSX } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { releaseNoteKeys } from '../../api/keys'
import { releaseNotesApi } from '../../api/releaseNotes'
import { Banner, Button, Card, Kvp, StatusBadge, PageSkeleton } from '../../design/components'
import { toast } from '../../design/toast'
import { encodeQrMatrix } from '../../lib/qrCode'
import { STALE_30S } from '../../lib/queryClient'
import { PageHeader } from '../../shell/PageHeader'
import styles from './customer.module.css'
import { formatDate, formatNgn } from '../../lib/format'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'
import { DetailPage } from '../../shell/DetailPage'

/** A scannable QR of the reference. Dark modules on a light tile, readable in both themes. */
function ReferenceQr({ value }: { value: string }): JSX.Element | null {
  const matrix = useMemo(() => encodeQrMatrix(value), [value])
  if (!matrix) return null
  const quiet = 2
  const size = matrix.length + quiet * 2
  return (
    <span className={styles.qrBox}>
      <svg
        role="img"
        aria-label={`QR code for ${value}`}
        viewBox={`0 0 ${size} ${size}`}
        width={132}
        height={132}
        shapeRendering="crispEdges"
      >
        <rect width={size} height={size} fill="var(--color-on-dark)" />
        {matrix.map((row, r) =>
          row.map((dark, c) =>
            dark ? <rect key={`${r}-${c}`} x={c + quiet} y={r + quiet} width={1} height={1} fill="var(--color-forest-dark)" /> : null,
          ),
        )}
      </svg>
    </span>
  )
}

/**
 * A customer's own release note: what they show, or quote, at the warehouse to collect their goods.
 *
 * The portal tells customers "your release note is issued once settled", and until this page existed they had
 * nothing to open. The backend already scopes `GET /v1/release-notes/{id}` and its PDF to the owner and answers
 * 404 for anyone else's.
 */
export function MyReleaseNote(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const { data: note, isLoading, error } = useQuery({
    queryKey: releaseNoteKeys.detail(id ?? ''),
    queryFn: () => releaseNotesApi.get(id!),
    enabled: !!id,
    staleTime: STALE_30S,
  })
  // Names this record in the breadcrumb once loaded (FD-46).
  useBreadcrumbLabel(note?.reference_number)

  async function downloadPdf(): Promise<void> {
    if (!note) return
    setDownloading(true)
    setDownloadError(null)
    try {
      await releaseNotesApi.pdf(note.id)
    } catch (err) {
      setDownloadError(err instanceof ApiError ? err.message : 'Could not download the PDF. Please try again.')
    } finally {
      setDownloading(false)
    }
  }

  async function copyReference(): Promise<void> {
    if (!note) return
    try {
      await navigator.clipboard?.writeText(note.reference_number)
      setCopied(true)
      toast.success('Reference copied', note.reference_number)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error('Could not copy', 'Select the reference and copy it manually.')
    }
  }

  if (isLoading) return <PageSkeleton kind="detail" label="Loading your release note" />

  if (error || !note) {
    const missing = error instanceof ApiError && error.status === 404
    return (
      <div className={styles.page}>
        <PageHeader title="Release note" />
        <Banner variant="error">
          {missing || !error ? 'Release note not found.' : 'Could not load this release note. Please try again.'}
        </Banner>
      </div>
    )
  }

  const cartons = `${note.carton_count} of ${note.total_cartons_for_customer} cartons`
  const owing = Number(note.balance_ngn) > 0
  const phoneHref = note.warehouse_phone ? `tel:${note.warehouse_phone.replace(/[^\d+]/g, '')}` : null

  return (
    <DetailPage
      header={
        <PageHeader
          title="Release note"
          meta="Show this at the warehouse to collect your goods."
          primary={
            <Button variant="primary" icon="download" loading={downloading} onClick={() => void downloadPdf()}>
              Download PDF
            </Button>
          }
        />
      }
    >
      {note.status === 'active' && (
        <div className={styles.banner}>
          <Banner variant="info" title="Ready for collection">
            Show this page, or quote the reference below, at the warehouse. You can also download it
            as a PDF.
          </Banner>
        </div>
      )}
      {note.status === 'active' && note.pickup_code_required && (
        <div className={styles.banner}>
          <Banner
            variant={note.pickup_code_locked ? 'error' : 'warning'}
            title={note.pickup_code_locked ? 'Pickup code locked' : 'A pickup code is needed'}
          >
            {note.pickup_code_locked
              ? 'Too many wrong codes were entered at the warehouse. Contact your shipping company for a new code.'
              : 'We sent you a pickup code by SMS or email. Whoever collects your goods must give it at the warehouse, so share it only with them. If you cannot find it, ask your shipping company to send a new one.'}
          </Banner>
        </div>
      )}
      {note.status === 'expired' && (
        <div className={styles.banner}>
          <Banner variant="warning" title="This release note has expired">
            Contact your shipping company to have it reissued.
          </Banner>
        </div>
      )}
      {note.is_on_credit && owing && (
        <div className={styles.banner}>
          <Banner variant="warning" title="Released on credit">
            A balance of <strong>{formatNgn(note.balance_ngn)}</strong> is still due
            {note.debt_due_date ? ` by ${formatDate(note.debt_due_date)}` : ''}.
          </Banner>
        </div>
      )}

      {downloadError && (
        <div className={styles.banner}>
          <Banner variant="error">{downloadError}</Banner>
        </div>
      )}

      <Card padding="large">
        <div className={styles.passHero}>
          <div className={styles.passRefBlock}>
            <span className={styles.passLabel}>Release note reference</span>
            <span className={styles.passRef}>{note.reference_number}</span>
            <div className={styles.passActions}>
              <StatusBadge kind="releaseNote" status={note.status} audience="customer" />
              <Button
                variant="secondary"
                size="sm"
                icon={copied ? 'check' : 'copy'}
                onClick={() => void copyReference()}
              >
                {copied ? 'Copied' : 'Copy reference'}
              </Button>
            </div>
          </div>
          <ReferenceQr value={note.reference_number} />
        </div>
        <Kvp optional label="Container" value={note.container_number} />
        <Kvp label="Cartons" value={cartons} />
        {note.is_partial_release && (
          <Kvp label="Release" value="Partial: more cartons remain on your shipment" />
        )}
        <Kvp label="Valid until" value={formatDate(note.valid_until)} />
        <Kvp optional label="Warehouse" value={note.warehouse_name} />
        {note.warehouse_address && <Kvp label="Address" value={note.warehouse_address} />}
        {note.warehouse_phone && phoneHref && (
          <Kvp
            label="Phone"
            value={<a className={styles.phoneLink} href={phoneHref}>{note.warehouse_phone}</a>}
          />
        )}
        {note.carton_tags.length > 0 && (
          <Kvp
            label="Carton tags"
            value={
              <span className={styles.tagPills}>
                {note.carton_tags.map((tag) => (
                  <span key={tag} className={styles.tagPill}>{tag}</span>
                ))}
              </span>
            }
          />
        )}
      </Card>
    </DetailPage>
  )
}
