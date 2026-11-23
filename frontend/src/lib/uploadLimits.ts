/**
 * The upload size limit, the same as the API's (`shared/uploads.py` `MAX_UPLOAD_BYTES`). Checked here first so an
 * over-size file is refused with a clear message before anything is sent; the API refuses it anyway.
 */
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024
export const MAX_UPLOAD_LABEL = '5 MB'

/** Why `file` cannot be uploaded because of its size, or null when it is within the limit. */
export function uploadSizeProblem(file: File): string | null {
  if (file.size === 0) return 'This file is empty. Choose another file.'
  if (file.size > MAX_UPLOAD_BYTES) {
    return `This file is ${(file.size / 1024 / 1024).toFixed(1)} MB. The limit is ${MAX_UPLOAD_LABEL}.`
  }
  return null
}
