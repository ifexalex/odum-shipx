import { excelApi, XLSX_CONTENT_TYPE } from './excel'

// Backed by POST /v1/packing-lists/import/presigned-url
// (services/excel/service.py's generate_import_presigned_url) — added to
// unblock this wizard, since no generic upload endpoint existed before
// (see 07_domain_modules.md's 7.2 notes for why the two existing
// presigned-URL routes, claims evidence and container documents, weren't
// reusable here).
export class UploadFailedError extends Error {
  constructor(status: number) {
    super(`File upload to storage failed (status ${status}). Please try again.`)
    this.name = 'UploadFailedError'
  }
}

/** Uploads `file` via an S3 POST-policy presigned URL and returns the resulting file_key. */
export async function uploadImportFile(file: File): Promise<string> {
  const contentType = file.type || XLSX_CONTENT_TYPE
  const { upload_url, fields, file_key } = await excelApi.getImportPresignedUrl(contentType)

  const formData = new FormData()
  for (const [key, value] of Object.entries(fields)) {
    formData.append(key, value)
  }
  // The file field must be appended last — required by S3's POST policy contract.
  formData.append('file', file)

  const response = await fetch(upload_url, { method: 'POST', body: formData })
  if (!response.ok) {
    throw new UploadFailedError(response.status)
  }
  return file_key
}
