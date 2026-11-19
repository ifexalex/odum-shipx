/**
 * useFileUpload — shared hook for browser → S3 presigned-URL uploads.
 *
 * Uses XMLHttpRequest (not fetch) so upload progress events are available.
 * Fetch does not expose upload progress; XHR does via xhr.upload.onprogress.
 *
 * The hook never constructs an S3 key — it always uses the key returned by
 * the backend's presigned-url response (CLAUDE.md tenant isolation rule).
 *
 * Validated against backend limits (services/claims/service.py):
 *   Max size:      5 MB (lib/uploadLimits.ts)
 *   Allowed types: image/jpeg, image/png, application/pdf
 *
 * Usage:
 *   const { upload, progress, status, reset } = useFileUpload(getPresignedUrl)
 *   const { key, evidenceId } = await upload(file)
 */
import { useCallback, useRef, useState } from 'react'
import { MAX_UPLOAD_BYTES, uploadSizeProblem } from '../lib/uploadLimits'

export type UploadStatus = 'idle' | 'validating' | 'uploading' | 'done' | 'error'

export const UPLOAD_MAX_BYTES = MAX_UPLOAD_BYTES // the API's limit (shared/uploads.py)
export const UPLOAD_ALLOWED_TYPES = ['image/jpeg', 'image/png', 'application/pdf'] as const
export const UPLOAD_PROGRESS_THRESHOLD = 100 * 1024 // show bar only for files > 100 KB

export interface UploadResult {
  key: string
  evidenceId: string | null
}

export interface PresignedResponse {
  upload_url: string
  // Cloud-neutral PUT upload contract (AWS presigned-PUT / Azure Blob SAS).
  // Optional for backward-compatibility with any cached response; defaults to PUT.
  upload_method?: string
  upload_headers?: Record<string, string>
  file_key: string
  evidence_id?: string | null
}

export interface UseFileUploadOptions {
  getPresignedUrl: (file: File) => Promise<PresignedResponse>
  onSuccess?: (result: UploadResult) => void
  onError?: (message: string) => void
}

export interface UseFileUploadResult {
  upload: (file: File) => Promise<UploadResult>
  progress: number
  status: UploadStatus
  errorMessage: string | null
  reset: () => void
}

export function useFileUpload({
  getPresignedUrl,
  onSuccess,
  onError,
}: UseFileUploadOptions): UseFileUploadResult {
  const [status, setStatus] = useState<UploadStatus>('idle')
  const [progress, setProgress] = useState(0)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const xhrRef = useRef<XMLHttpRequest | null>(null)

  const reset = useCallback(() => {
    xhrRef.current?.abort()
    setStatus('idle')
    setProgress(0)
    setErrorMessage(null)
  }, [])

  const upload = useCallback(
    async (file: File): Promise<UploadResult> => {
      // Client-side validation — mirrors backend Pydantic limits
      const sizeProblem = uploadSizeProblem(file)
      if (sizeProblem) {
        const msg = sizeProblem
        setErrorMessage(msg)
        setStatus('error')
        onError?.(msg)
        throw new Error(msg)
      }
      if (!UPLOAD_ALLOWED_TYPES.includes(file.type as typeof UPLOAD_ALLOWED_TYPES[number])) {
        const msg = `File type "${file.type || 'unknown'}" is not allowed. Upload JPEG, PNG, or PDF.`
        setErrorMessage(msg)
        setStatus('error')
        onError?.(msg)
        throw new Error(msg)
      }

      setStatus('validating')
      setProgress(0)
      setErrorMessage(null)

      const presigned = await getPresignedUrl(file)

      return new Promise<UploadResult>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhrRef.current = xhr

        // Only show progress bar for files above threshold — small files flash too fast
        if (file.size >= UPLOAD_PROGRESS_THRESHOLD) {
          xhr.upload.onprogress = (evt) => {
            if (evt.lengthComputable) {
              setProgress(Math.round((evt.loaded / evt.total) * 100))
            }
          }
        }

        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            const result: UploadResult = {
              key: presigned.file_key,
              evidenceId: presigned.evidence_id ?? null,
            }
            setStatus('done')
            setProgress(100)
            onSuccess?.(result)
            resolve(result)
          } else {
            const msg = `Upload failed (HTTP ${xhr.status}). Please try again.`
            setStatus('error')
            setErrorMessage(msg)
            onError?.(msg)
            reject(new Error(msg))
          }
        }

        xhr.onerror = () => {
          const msg = 'Upload failed — network error. Please check your connection.'
          setStatus('error')
          setErrorMessage(msg)
          onError?.(msg)
          reject(new Error(msg))
        }

        xhr.onabort = () => {
          reject(new Error('Upload cancelled.'))
        }

        setStatus('uploading')
        // Normalized PUT contract: raw file body + signed headers (Content-Type).
        xhr.open(presigned.upload_method ?? 'PUT', presigned.upload_url)
        for (const [header, value] of Object.entries(presigned.upload_headers ?? { 'Content-Type': file.type })) {
          xhr.setRequestHeader(header, value)
        }
        xhr.send(file)
      })
    },
    [getPresignedUrl, onSuccess, onError],
  )

  return { upload, progress, status, errorMessage, reset }
}
