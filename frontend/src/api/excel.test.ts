import { beforeEach, describe, expect, it, vi } from 'vitest'
import { registerSessionActions } from '../auth/sessionBridge'
import { clearActiveTokens, setActiveTokens } from '../auth/tokenStore'
import { excelApi } from './excel'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('excelApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.test.shipx.co')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    clearActiveTokens()
    setActiveTokens({ idToken: 'tok', tokenType: 'cognito' })
    registerSessionActions({ refreshNow: vi.fn(), logout: vi.fn(), exitImpersonation: vi.fn() })
  })

  it('importPackingList() POSTs container_id and file_key', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        data: { total_rows: 10, imported: 8, errors: 2, packing_lists_created: 3, error_details: [] },
      }),
    )
    const result = await excelApi.importPackingList('c1', 't1/imports/file.xlsx')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/packing-lists/import')
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify({ container_id: 'c1', file_key: 't1/imports/file.xlsx' }))
    expect(result.packing_lists_created).toBe(3)
  })

  it('getImportPresignedUrl() POSTs content_type to the presigned-url endpoint', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        data: { upload_url: 'https://logistics-assets.s3.amazonaws.com/t1/imports/x.xlsx', upload_method: 'PUT', upload_headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }, file_key: 't1/imports/x.xlsx' },
      }),
    )
    const result = await excelApi.getImportPresignedUrl(
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      20480,
    )
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/packing-lists/import/presigned-url')
    expect(init.method).toBe('POST')
    expect(init.body).toBe(
      JSON.stringify({ content_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', size_bytes: 20480 }),
    )
    expect(result.file_key).toBe('t1/imports/x.xlsx')
  })
})
