/**
 * useFileUpload: the PUT to storage, then the confirm call. The upload is done only once the API confirms it; the
 * API checks the stored size there (the only size check on Azure) and its refusal is the message shown.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useFileUpload, type PresignedResponse } from './useFileUpload'

class FakeXhr {
  static last: FakeXhr | null = null
  status = 0
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null
  open = vi.fn()
  setRequestHeader = vi.fn()
  abort = vi.fn()
  send = vi.fn(() => {
    FakeXhr.last = this
  })

  respond(status: number): void {
    this.status = status
    this.onload?.()
  }
}

const presigned: PresignedResponse = {
  upload_url: 'https://storage.test/put',
  upload_method: 'PUT',
  upload_headers: { 'Content-Type': 'image/png' },
  file_key: 't1/claims/c1/x-a.png',
  evidence_id: 'e1',
}
const file = (): File => new File(['png'], 'a.png', { type: 'image/png' })

beforeEach(() => {
  FakeXhr.last = null
  vi.stubGlobal('XMLHttpRequest', FakeXhr)
})
afterEach(() => vi.unstubAllGlobals())

async function startUpload(confirmUpload?: (p: PresignedResponse) => Promise<unknown>) {
  const onSuccess = vi.fn()
  const hook = renderHook(() =>
    useFileUpload({ getPresignedUrl: async () => presigned, confirmUpload, onSuccess }),
  )
  let result!: Promise<unknown>
  await act(async () => {
    result = hook.result.current.upload(file())
    result.catch(() => undefined)
    await vi.waitFor(() => expect(FakeXhr.last).not.toBeNull())
  })
  return { hook, result, onSuccess }
}

describe('useFileUpload confirmation', () => {
  it('confirms after the PUT succeeds, and only then reports the upload done', async () => {
    let release!: () => void
    const confirmUpload = vi.fn(() => new Promise<void>((resolve) => (release = resolve)))
    const { hook, result, onSuccess } = await startUpload(confirmUpload)

    await act(async () => FakeXhr.last!.respond(200))
    expect(confirmUpload).toHaveBeenCalledWith(presigned)
    expect(onSuccess).not.toHaveBeenCalled()
    expect(hook.result.current.status).toBe('uploading')

    await act(async () => release())
    await expect(result).resolves.toEqual({ key: presigned.file_key, evidenceId: 'e1' })
    expect(hook.result.current.status).toBe('done')
    expect(onSuccess).toHaveBeenCalledOnce()
  })

  it("shows the API's refusal when the confirmation fails", async () => {
    const confirmUpload = vi.fn(async () => {
      throw new Error('The file is larger than 5 MB.')
    })
    const { hook, result, onSuccess } = await startUpload(confirmUpload)

    await act(async () => FakeXhr.last!.respond(200))
    await expect(result).rejects.toThrow('The file is larger than 5 MB.')
    expect(hook.result.current.status).toBe('error')
    expect(hook.result.current.errorMessage).toBe('The file is larger than 5 MB.')
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('does not confirm a PUT that failed', async () => {
    const confirmUpload = vi.fn(async () => undefined)
    const { result } = await startUpload(confirmUpload)

    await act(async () => FakeXhr.last!.respond(403))
    await expect(result).rejects.toThrow('Upload failed (HTTP 403)')
    expect(confirmUpload).not.toHaveBeenCalled()
  })

  it('is done straight after the PUT when there is nothing to confirm', async () => {
    const { hook, result } = await startUpload()

    await act(async () => FakeXhr.last!.respond(200))
    await expect(result).resolves.toEqual({ key: presigned.file_key, evidenceId: 'e1' })
    expect(hook.result.current.status).toBe('done')
  })
})
