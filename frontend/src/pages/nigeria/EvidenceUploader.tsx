import { useRef, type JSX } from 'react'
import { Banner, Button } from '../../design/components'
import { useFileUpload, UPLOAD_ALLOWED_TYPES, type PresignedResponse } from '../../hooks/useFileUpload'
import styles from './EvidenceUploader.module.css'

export interface UploadedEvidence {
  evidence_id: string | null
  file_key: string
  filename: string
}

interface EvidenceUploaderProps {
  /** Resolves a presigned S3 POST for the chosen file. Lets the same uploader
   *  serve claims evidence, manifest verification photos, etc. */
  getPresignedUrl: (file: File) => Promise<PresignedResponse>
  onUploaded: (evidence: UploadedEvidence) => void
  disabled?: boolean
}

export function EvidenceUploader({ getPresignedUrl, onUploaded, disabled }: EvidenceUploaderProps): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null)
  const pendingFilename = useRef<string>('')

  const { upload, progress, status, errorMessage, reset } = useFileUpload({
    getPresignedUrl: (file) => {
      pendingFilename.current = file.name
      return getPresignedUrl(file)
    },
    onSuccess: (result) => {
      onUploaded({
        evidence_id: result.evidenceId,
        file_key: result.key,
        filename: pendingFilename.current,
      })
      if (inputRef.current) inputRef.current.value = ''
    },
  })

  const uploading = status === 'uploading' || status === 'validating'
  const showProgress = uploading && progress > 0

  return (
    <div className={styles.uploader}>
      <input
        ref={inputRef}
        type="file"
        accept={UPLOAD_ALLOWED_TYPES.join(',')}
        className={styles.hiddenInput}
        disabled={disabled || uploading}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) {
            reset()
            void upload(file)
          }
        }}
      />

      <div className={styles.uploadRow}>
        <Button
          variant="secondary"
          size="sm"
          icon="upload"
          loading={uploading}
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
        >
          {uploading ? 'Uploading…' : 'Attach file'}
        </Button>
        <span className={styles.hint}>JPEG, PNG or PDF · max 10 MB</span>
      </div>

      {/* Determinate progress bar — only shown for files above the threshold */}
      {showProgress && (
        <div className={styles.progressWrap}>
          <div className={styles.progressTrack}>
            <div className={styles.progressBar} style={{ width: `${progress}%` }} />
          </div>
          <span className={styles.progressLabel}>{progress}%</span>
        </div>
      )}

      {errorMessage && (
        <div className={styles.error}>
          <Banner variant="error">{errorMessage}</Banner>
        </div>
      )}

      {status === 'done' && (
        <div className={styles.fileList}>
          <span className={styles.fileItem}>
            ✓ {pendingFilename.current}
          </span>
        </div>
      )}
    </div>
  )
}
