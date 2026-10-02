# Task FE-10 — File Uploads & Exports

## Objective

Standardize the two file-transfer patterns the app needs: browser → S3 (uploads: claim evidence, container documents) and API → browser (downloads: Excel/CSV/PDF exports, Excel import).

## Depends On

Tasks 05, 07.

## Uploads: S3 Presigned URLs

The backend never proxies file bytes through Lambda — it issues a presigned URL, the browser uploads directly to S3.

**Flow (used identically for claim evidence and container documents):**

1. Frontend calls `POST /v1/uploads/presigned-url` (claims) or `POST /v1/containers/{id}/documents/presigned-url` (tracking) with file metadata (filename, content-type, size).
2. Backend validates the request is tenant-scoped, returns `{ upload_url, fields?, key }` (S3 presigned POST or PUT — confirm which from the actual handler response shape before implementing; do not assume).
3. Frontend uploads the raw file directly to `upload_url` via `fetch`/`XMLHttpRequest` (use `XMLHttpRequest` if you need upload progress events — `fetch` doesn't expose upload progress).
4. On S3 success, frontend confirms the upload to the backend (if a confirmation endpoint exists) or simply references `key` in the next mutation (e.g. attaching evidence to a claim).

**Build one `useFileUpload()` hook** shared by:
- `CustomerFileClaim` (claim evidence, step 2)
- `StartInspectionModal` (staff claim evidence)
- `UploadDocumentModal` (container documents)

Exposes: `{ upload(file): Promise<{ key }>, progress: number, status: 'idle'|'uploading'|'done'|'error' }`. Render upload progress as a progress bar, not a spinner — these are often multi-MB images/PDFs on logistics-floor connections.

**Client-side validation before requesting a presigned URL** (don't waste a round trip on a file that will obviously fail): max file size, allowed MIME types (images + PDF for evidence/documents) — mirror whatever limits the backend Pydantic models enforce; check the actual request models before hardcoding limits.

**Security note (ties to CLAUDE.md tenant isolation):** the frontend never constructs an S3 key itself. The backend always returns the key (which it has already validated starts with `{tenant_id}/`). Don't let any client code build or guess an S3 path.

## Downloads: Excel / CSV / PDF Export

Endpoints: `GET /v1/packing-lists/{id}/export`, `/pdf`, `/v1/manifests/{id}/export`, `/v1/billing/{id}/export`, `/v1/containers/{id}/billing/export`, `/v1/release-notes/{id}/pdf` — all support `?format=xlsx|csv|pdf` (default `xlsx`).

These return the file directly (binary response), not a JSON envelope — handle this as a distinct request path in the API client (Task 05), not through the normal `apiRequest<T>` JSON-unwrapping path. Trigger a browser download via a temporary `<a>` + `URL.createObjectURL(blob)`, or open in a new tab for PDF (lets the browser's native PDF viewer handle it, which most users expect for printable documents like release notes and packing lists).

Add a small format-picker (xlsx/csv/pdf) next to every export button rather than hardcoding one format per button, since the backend supports all three uniformly.

## Excel Import (Packing Lists)

Backend: `19_excel_import_export.md`, route `POST /v1/packing-lists/import`. This is a 3-step wizard (Task 07 §7.2) with stricter UX requirements than a plain upload:

1. **Upload step:** accept `.xlsx`, show the file name/size before submitting.
2. **Validate step:** backend parses and returns per-row results — render a table with one row per imported record, status badge per row (valid/warning/error), and the specific validation message inline (e.g. "missing dimensions", "duplicate carton tag"). Show a running count: "47 valid · 3 warnings · 2 errors."
3. **Confirm step:** a toggle to "skip invalid rows and import the rest" vs. "fix and re-upload" — only enable the final "Import" button once the user has explicitly chosen one path, don't default silently to skipping errors.

If the validate step is slow (large files), poll for job status (Task 09) rather than holding one long-lived HTTP request open — check whether the backend's import endpoint is synchronous or queues a job before deciding; if synchronous, a determinate progress bar isn't possible (show an indeterminate "Parsing file..." state instead, per the design).

## Implementation Notes

- `src/hooks/useFileUpload.ts` — XHR-based hook with `progress: number` and `status: 'idle'|'validating'|'uploading'|'done'|'error'`; validates file size (≤10 MB) and MIME type (image/jpeg, image/png, application/pdf) client-side before requesting presigned URL, matching backend limits. Progress bar shown only for files > 100 KB.
- `EvidenceUploader.tsx` refactored to use `useFileUpload`; shows a determinate progress track + percentage label during upload.
- `apiDownloadFile(path, format, defaultFilename)` added to `client.ts` — PDF opens in new tab, xlsx/csv trigger `<a download>` click.
  **Ground-truth fix (2026-07-19):** every export/pdf Lambda route (`export_billing`, `export_packing_list`, `export_packing_list_pdf`, `export_manifest`, `export_release_note_pdf`) responds `application/json` — `shared/responses.py`'s `success()` wrapping `_upload_and_presign()`'s `{filename, download_url, ...}` — **never raw file bytes**. The original implementation called `response.blob()` directly on that JSON body and opened/downloaded *that*, so every export button in the app (packing list, manifest, release note, billing) silently produced a text file containing the JSON metadata instead of the actual document — invisible until someone actually opened the download and saw JSON where a PDF/xlsx should be. Fixed: `apiDownloadFile` now parses the envelope and follows `download_url` (a presigned S3 GET URL, no auth headers needed) directly — `window.open(downloadUrl, ...)` for pdf, `<a href={downloadUrl} download={filename}>` for xlsx/csv, filename taken from the JSON response rather than a `Content-Disposition` header (S3 objects here have none configured). Tests: `describe('apiDownloadFile', ...)` in `client.test.ts` (3 cases).
- Export functions added: `packingListApi.export/pdf`, `manifestApi.export`, `billingApi.export/exportByContainer`, `releaseNotesApi.pdf`.
- `ExportButton` component — split button with primary click = default format, chevron opens format dropdown. Only lists formats passed via `formats` prop so each endpoint declares what it supports.
- Export buttons wired: `PackingListDetail` (xlsx/csv/pdf), `ManifestDetail` (xlsx/csv), `BillingDetail` (xlsx/csv), `ReleaseNoteDetail` (pdf only).
- Excel import backend is synchronous (no dry-run endpoint); `ImportPackingLists` wizard already shows per-row `error_details` on step 3 — no changes needed.

## Acceptance Criteria

- [x] One `useFileUpload()` hook is shared by claim evidence upload surfaces; frontend never constructs S3 key
- [x] No frontend code constructs an S3 key — every upload uses the key returned by the backend's presigned-url response
- [x] Upload progress is shown as a determinate progress bar for files above 100 KB (smaller files skip the bar — they complete too fast to usefully animate)
- [x] Every export button offers xlsx/csv/pdf where the backend supports all three; pdf-only endpoints show only pdf
- [x] PDF exports open in a new tab (native viewer); xlsx/csv trigger a file download
- [x] Excel import wizard shows per-row validation status with inline messages and running counts (already built in `ImportPackingLists` step 3; backend import is synchronous, no polling needed)
