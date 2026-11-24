import { logoFileProblem, uploadSizeProblem } from '../lib/uploadLimits'
import { excelApi, XLSX_CONTENT_TYPE } from './excel'
import { configApi, type BrandingConfig } from './tenantManagement'

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

  await putToStorage({ upload_url, upload_method, upload_headers }, file, contentType)
  return file_key
}

/** PUT `file` to a presigned upload (cloud-neutral: the method and headers come from the API). */
async function putToStorage(
  ticket: { upload_url: string; upload_method?: string; upload_headers?: Record<string, string> },
  file: File,
  contentType: string,
): Promise<void> {
  const response = await fetch(ticket.upload_url, {
    method: ticket.upload_method ?? 'PUT',
    headers: ticket.upload_headers ?? { 'Content-Type': contentType },
    body: file,
  })
  if (!response.ok) {
    throw new UploadFailedError(response.status)
  }
}

/** The file cannot be the logo (type or size); nothing was sent. */
export class LogoFileError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'LogoFileError'
  }
}

/**
 * Upload `file` as the tenant's logo (FD-29): check it here, presign, PUT it to storage, then tell the API to use it.
 * Returns the branding with its new `logo_url`.
 */
export async function uploadTenantLogo(file: File): Promise<BrandingConfig> {
  const problem = logoFileProblem(file)
  if (problem) throw new LogoFileError(problem)
  const ticket = await configApi.getLogoUploadUrl({ filename: file.name, content_type: file.type, size_bytes: file.size })
  await putToStorage(ticket, file, file.type)
  return configApi.setLogo(ticket.file_key)
}
