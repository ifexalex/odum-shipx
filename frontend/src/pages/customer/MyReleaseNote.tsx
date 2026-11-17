import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { releaseNoteKeys } from '../../api/keys'
import { releaseNotesApi } from '../../api/releaseNotes'
import { releaseNoteStatusLabel } from '../../api/releaseNotesRules'
import { Badge, Banner, Button, Card, Kvp, Mono, type BadgeVariant } from '../../design/components'
import { STALE_30S } from '../../lib/queryClient'
import { PageHeader } from '../../shell/PageHeader'
import styles from './customer.module.css'
import { formatDate, formatNgn } from '../../lib/format'
import { useBreadcrumbLabel } from '../../shell/breadcrumbs'

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  active: 'success',
  picked_up: 'neutral',
  expired: 'error',
  cancelled: 'neutral',
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

  if (isLoading) return <div style={{ padding: 32, color: 'var(--color-text-muted)' }}>Loading your release note…</div>

  if (error || !note) {
    const missing = error instanceof ApiError && error.status === 404
    return (
      <div className={styles.page}>
        <Banner variant="error">
          {missing || !error ? 'Release note not found.' : 'Could not load this release note. Please try again.'}
        </Banner>
      </div>
    )
  }

  const cartons = `${note.carton_count} of ${note.total_cartons_for_customer} cartons`
  const owing = Number(note.balance_ngn) > 0

  return (
    <div className={styles.page}>
      <PageHeader title="Release note" subtitle="Show this at the warehouse to collect your goods." />

      {note.status === 'active' && (
        <div className={styles.banner}>
          <Banner variant="info" title="Ready for collection">
            Show this page, or quote the reference below, at the warehouse. You can also download it as a PDF.
          </Banner>
        </div>
      )}
      {note.status === 'active' && note.pickup_code_required && (
        <div className={styles.banner}>
          <Banner variant={note.pickup_code_locked ? 'error' : 'warning'} title={note.pickup_code_locked ? 'Pickup code locked' : 'A pickup code is needed'}>
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

      <Card padding={24}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <Mono color="var(--color-ink)">{note.reference_number}</Mono>
          <Badge variant={STATUS_VARIANT[note.status] ?? 'neutral'}>{releaseNoteStatusLabel(note.status)}</Badge>
        </div>
        <div style={{ height: 16 }} />
        <Kvp label="Container" value={note.container_number ?? '—'} />
        <Kvp label="Cartons" value={cartons} />
        {note.is_partial_release && <Kvp label="Release" value="Partial: more cartons remain on your shipment" />}
        <Kvp label="Valid until" value={formatDate(note.valid_until)} />
        <Kvp label="Warehouse" value={note.warehouse_name ?? '—'} />
        {note.warehouse_address && <Kvp label="Address" value={note.warehouse_address} />}
        {note.warehouse_phone && <Kvp label="Phone" value={note.warehouse_phone} />}
        {note.carton_tags.length > 0 && <Kvp label="Carton tags" value={<Mono>{note.carton_tags.join(', ')}</Mono>} />}
      </Card>

      {downloadError && (
        <div className={styles.banner} style={{ marginTop: 16 }}>
          <Banner variant="error">{downloadError}</Banner>
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, marginTop: 20, flexWrap: 'wrap' }}>
        <Button variant="primary" icon="download" loading={downloading} onClick={() => void downloadPdf()}>
          Download PDF
        </Button>
      </div>
    </div>
  )
}
