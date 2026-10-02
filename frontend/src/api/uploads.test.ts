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

  it('requests a presigned URL, posts the file, and returns the file_key', async () => {
    vi.mocked(excelApi.getImportPresignedUrl).mockResolvedValue({
      upload_url: 'https://logistics-assets.s3.amazonaws.com/',
      fields: { key: 't1/imports/abc.xlsx', policy: 'p', signature: 's', AWSAccessKeyId: 'ak' },
      file_key: 't1/imports/abc.xlsx',
    })
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))

    const fileKey = await uploadImportFile(makeFile())

    expect(excelApi.getImportPresignedUrl).toHaveBeenCalledWith(
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    expect(fetchMock).toHaveBeenCalledWith('https://logistics-assets.s3.amazonaws.com/', expect.objectContaining({ method: 'POST' }))
    const body = fetchMock.mock.calls[0]?.[1]?.body as FormData
    expect(body.get('key')).toBe('t1/imports/abc.xlsx')
    expect(body.get('file')).toBeInstanceOf(File)
    expect(fileKey).toBe('t1/imports/abc.xlsx')
  })

  it('throws UploadFailedError when S3 rejects the upload', async () => {
    vi.mocked(excelApi.getImportPresignedUrl).mockResolvedValue({
      upload_url: 'https://logistics-assets.s3.amazonaws.com/',
      fields: {},
      file_key: 't1/imports/abc.xlsx',
    })
    fetchMock.mockResolvedValue(new Response(null, { status: 403 }))

    await expect(uploadImportFile(makeFile())).rejects.toBeInstanceOf(UploadFailedError)
  })
})
