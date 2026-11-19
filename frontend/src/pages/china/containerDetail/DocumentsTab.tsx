import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { ApiError } from '../../../api/client'
import { containerKeys } from '../../../api/keys'
import { STALE_30S } from '../../../lib/queryClient'
import {
  containerDocumentsApi,
  uploadToPresignedUrl,
  type ContainerDocument,
  type ContainerDocumentType,
} from '../../../api/tracking'
import { Banner, Button, Card, Mono, Table, DialogGuard } from '../../../design/components'
import { SectionHead } from '../../../shell/SectionHead'
import styles from '../ContainerDetail.module.css'
import { formatDate } from '../../../lib/format'
import { uploadSizeProblem } from '../../../lib/uploadLimits'

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

export function DocumentsTab({
  containerId,
  containerNumber,
}: {
  containerId: string
  containerNumber: string | null
}): JSX.Element {

  const {
    data: docs = [],
    isLoading: loading,
    error: loadError,
  } = useQuery({
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
    const sizeProblem = uploadSizeProblem(file)
    if (sizeProblem) {
      setUploadError(sizeProblem)
      return
    }
    setUploading(true)
    setUploadError(null)
    try {
      const presigned = await containerDocumentsApi.presignUpload(containerId, {
        filename: file.name,
        content_type: file.type,
        document_type: docType,
        size_bytes: file.size,
      })
      await uploadToPresignedUrl(presigned, file)
      if (!presigned.document_id) throw new Error('The upload could not be recorded. Please try again.')
      // The document is listed only once confirmed, and the confirm POST refreshes this list (api/client.ts
      // invalidates the container keys on it). A file over the limit is refused here with the API's message.
      await containerDocumentsApi.confirmUpload(containerId, presigned.document_id)
      setShowUpload(false)
      setFile(null)
    } catch (err) {
      setUploadError(err instanceof Error && err.message ? err.message : 'Upload failed. Please try again.')
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

  const docTypeLabel = (t: ContainerDocumentType): string =>
    DOC_TYPES.find((d) => d.value === t)?.label ?? t

  return (
    <>
      {error && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <Banner variant="error" title="Documents error">
            {error}
          </Banner>
        </div>
      )}
      <Card padding="none">
        <div className={styles.tableHead}>
          <SectionHead
            title="Documents"
            sub="Bill of lading, customs forms, inspection reports"
            action={
              <Button
                variant="primary"
                size="sm"
                icon="upload"
                onClick={() => {
                  setUploadError(null)
                  setFile(null)
                  setShowUpload(true)
                }}
              >
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
              <span key="type" style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>
                {docTypeLabel(doc.document_type)}
              </span>,
              <Mono key="name">{doc.filename}</Mono>,
              <span key="date" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-3)' }}>
                {formatDate(doc.created_at)}
              </span>,
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
            <span style={{ color: 'var(--color-ink-3)', fontSize: 'var(--text-sm)' }}>
              {loading ? 'Loading documents…' : 'No documents uploaded yet.'}
            </span>
          }
        />
      </Card>

      {showUpload && (
        <div className={styles.modalOverlay} onClick={() => !uploading && setShowUpload(false)}>
          <DialogGuard onClose={() => !uploading && setShowUpload(false)} />
          <div
            className={styles.modalPanel}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
          >
            <h3 className={styles.modalTitle}>Upload document</h3>
            <p className={styles.modalBody}>Container {containerNumber ?? containerId}</p>
            {uploadError && (
              <div className={styles.modalBanner}>
                <Banner variant="error">{uploadError}</Banner>
              </div>
            )}

            <div>
              <label
                style={{
                  fontWeight: 600,
                  fontSize: 'var(--text-md)',
                  display: 'block',
                  marginBottom: 'var(--space-2)',
                }}
              >
                Document type <span style={{ color: 'var(--color-error)' }}>*</span>
              </label>
              <select
                style={{
                  width: '100%',
                  padding: 'var(--space-2) var(--space-3)',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--color-line)',
                  background: 'var(--color-surface)',
                  fontSize: 'var(--text-md)',
                }}
                value={docType}
                onChange={(e) => setDocType(e.target.value as ContainerDocumentType)}
              >
                {DOC_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>

            <div style={{ marginTop: 'var(--space-3)' }}>
              <label
                style={{
                  fontWeight: 600,
                  fontSize: 'var(--text-md)',
                  display: 'block',
                  marginBottom: 'var(--space-2)',
                }}
              >
                File <span style={{ color: 'var(--color-error)' }}>*</span>
              </label>
              <input
                type="file"
                accept={DOC_ACCEPT}
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null)
                  setUploadError(null)
                }}
                style={{ fontSize: 'var(--text-sm)' }}
              />
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', marginTop: 'var(--space-2)' }}>
                Accepted: PDF, JPG, PNG, WebP · max 5 MB
              </div>
            </div>

            <div className={styles.modalActions}>
              <Button variant="ghost" onClick={() => setShowUpload(false)} disabled={uploading}>
                Cancel
              </Button>
              <Button
                variant="primary"
                icon="upload"
                loading={uploading}
                disabled={!file}
                onClick={() => void handleUpload()}
              >
                Upload
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
