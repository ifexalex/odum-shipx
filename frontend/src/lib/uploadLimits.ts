/**
 * The upload size limit, the same as the API's (`shared/uploads.py` `MAX_UPLOAD_BYTES`). Checked here first so an
 * over-size file is refused with a clear message before anything is sent; the API refuses it anyway.
 */
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024
export const MAX_UPLOAD_LABEL = '5 MB'

/** The logo's limit, the same as the API's (`shared/uploads.py` `TENANT_LOGO`). */
export const MAX_LOGO_BYTES = MAX_UPLOAD_BYTES
export const MAX_LOGO_LABEL = MAX_UPLOAD_LABEL
/** The logo types the API accepts. No SVG: it can carry script. */
export const LOGO_CONTENT_TYPES = ['image/png', 'image/jpeg', 'image/webp'] as const

/** Why `file` cannot be uploaded because of its size, or null when it is within the limit. */
export function uploadSizeProblem(file: File, maxBytes = MAX_UPLOAD_BYTES, maxLabel = MAX_UPLOAD_LABEL): string | null {
  if (file.size === 0) return 'This file is empty. Choose another file.'
  if (file.size > maxBytes) {
    return `This file is ${(file.size / 1024 / 1024).toFixed(1)} MB. The limit is ${maxLabel}.`
  }
  return null
}

/** Why `file` cannot be the logo (type or size), or null when it can. */
export function logoFileProblem(file: File): string | null {
  if (!(LOGO_CONTENT_TYPES as readonly string[]).includes(file.type)) return 'Use a PNG, JPEG or WebP image.'
  return uploadSizeProblem(file, MAX_LOGO_BYTES, MAX_LOGO_LABEL)
}
