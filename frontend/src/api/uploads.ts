import { uploadSizeProblem } from '../lib/uploadLimits'
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

/** The file is over the upload limit (or empty); nothing was sent. */
export class FileTooLargeError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'FileTooLargeError'
  }
}

/** Uploads `file` via a presigned PUT URL (cloud-neutral) and returns the resulting file_key. */
export async function uploadImportFile(file: File): Promise<string> {
  const sizeProblem = uploadSizeProblem(file)
  if (sizeProblem) throw new FileTooLargeError(sizeProblem)
  const contentType = file.type || XLSX_CONTENT_TYPE
  const { upload_url, upload_method, upload_headers, file_key } =
    await excelApi.getImportPresignedUrl(contentType, file.size)

  const response = await fetch(upload_url, {
    method: upload_method ?? 'PUT',
    headers: upload_headers ?? { 'Content-Type': contentType },
    body: file,
  })
  if (!response.ok) {
    throw new UploadFailedError(response.status)
  }
  return file_key
}
