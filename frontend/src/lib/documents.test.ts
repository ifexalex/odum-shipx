import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { runDocument } from './documents'

describe('runDocument (FD-44)', () => {
  it('says the document is being prepared, then clears the note when it opens', async () => {
    let finish: () => void = () => {}
    const pending = runDocument('the invoice', () => new Promise<void>((resolve) => (finish = resolve)))
    expect(await screen.findByText('Preparing the invoice…')).toBeInTheDocument()
    finish()
    expect(await pending).toBe(true)
    await vi.waitFor(() => expect(screen.queryByText('Preparing the invoice…')).toBeNull())
  })

  it('says why it failed, instead of doing nothing', async () => {
    const error = new ApiError(
      { type: 'about:blank', title: 'Not Found', status: 404, detail: 'Invoice not found.', error_code: 'RESOURCE_NOT_FOUND' },
      null,
    )
    expect(await runDocument('the invoice', () => Promise.reject(error))).toBe(false)
    expect(await screen.findByText("Couldn't prepare the invoice")).toBeInTheDocument()
  })

  it('names a network failure in plain words', async () => {
    expect(await runDocument('the export', () => Promise.reject(new TypeError('Failed to fetch')))).toBe(false)
    expect(await screen.findByText('Check your connection and try again.')).toBeInTheDocument()
  })
})
