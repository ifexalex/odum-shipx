import { beforeEach, describe, expect, it, vi } from 'vitest'
import { excelApi } from './excel'
import { UploadFailedError, uploadImportFile } from './uploads'

vi.mock('./excel', async () => {
  const actual = await vi.importActual<typeof import('./excel')>('./excel')
  return { ...actual, excelApi: { ...actual.excelApi, getImportPresignedUrl: vi.fn() } }
})

function makeFile(): File {
  return new File(['a,b,c'], 'import.xlsx', {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

describe('uploadImportFile', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.mocked(excelApi.getImportPresignedUrl).mockReset()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  it('requests a presigned URL, PUTs the file body with signed headers, and returns the file_key', async () => {
    vi.mocked(excelApi.getImportPresignedUrl).mockResolvedValue({
      upload_url: 'https://logistics-assets.s3.amazonaws.com/t1/imports/abc.xlsx?sig=1',
      upload_method: 'PUT',
      upload_headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
      file_key: 't1/imports/abc.xlsx',
    })
    fetchMock.mockResolvedValue(new Response(null, { status: 200 }))

    const fileKey = await uploadImportFile(makeFile())

    expect(excelApi.getImportPresignedUrl).toHaveBeenCalledWith(
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      makeFile().size,
    )
    expect(fetchMock).toHaveBeenCalledWith(
      'https://logistics-assets.s3.amazonaws.com/t1/imports/abc.xlsx?sig=1',
      expect.objectContaining({
        method: 'PUT',
        headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
      }),
    )
    const body = fetchMock.mock.calls[0]?.[1]?.body
    expect(body).toBeInstanceOf(File)
    expect(fileKey).toBe('t1/imports/abc.xlsx')
  })

  it('throws UploadFailedError when storage rejects the upload', async () => {
    vi.mocked(excelApi.getImportPresignedUrl).mockResolvedValue({
      upload_url: 'https://logistics-assets.s3.amazonaws.com/',
      upload_method: 'PUT',
      upload_headers: {},
      file_key: 't1/imports/abc.xlsx',
    })
    fetchMock.mockResolvedValue(new Response(null, { status: 403 }))

    await expect(uploadImportFile(makeFile())).rejects.toBeInstanceOf(UploadFailedError)
  })

  it('refuses a file over 5 MB before asking for an upload URL', async () => {
    const big = makeFile()
    Object.defineProperty(big, 'size', { value: 5 * 1024 * 1024 + 1 })
    await expect(uploadImportFile(big)).rejects.toThrow('The limit is 5 MB.')
    expect(excelApi.getImportPresignedUrl).not.toHaveBeenCalled()
  })
})

