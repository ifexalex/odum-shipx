import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { useListExport } from './useListExport'

function apiError(detail: string): ApiError {
  return new ApiError({ type: 'about:blank', title: 'x', status: 422, detail, error_code: 'BUSINESS_RULE_VIOLATION' }, null)
}

describe('useListExport', () => {
  it('has a stable onExport, so a button captured once keeps working', () => {
    const { result, rerender } = renderHook(({ exporter }) => useListExport(exporter), {
      initialProps: { exporter: vi.fn().mockResolvedValue(undefined) },
    })
    const first = result.current.onExport
    rerender({ exporter: vi.fn().mockResolvedValue(undefined) })
    expect(result.current.onExport).toBe(first)
  })

  it('calls the latest exporter, not the one it was first given', async () => {
    const stale = vi.fn().mockResolvedValue(undefined)
    const fresh = vi.fn().mockResolvedValue(undefined)
    const { result, rerender } = renderHook(({ exporter }) => useListExport(exporter), { initialProps: { exporter: stale } })
    const captured = result.current.onExport // what a button placed in the top bar on mount would hold
    rerender({ exporter: fresh })

    await act(() => captured('csv'))

    expect(fresh).toHaveBeenCalledWith('csv')
    expect(stale).not.toHaveBeenCalled()
  })

  it('turns a refusal into a message instead of an unhandled rejection', async () => {
    const { result } = renderHook(() => useListExport(vi.fn().mockRejectedValue(apiError('More than 10,000 invoices match.'))))
    await act(() => result.current.onExport('xlsx'))
    expect(result.current.error).toBe('More than 10,000 invoices match.')
  })

  it('does not leak the text of an unexpected error', async () => {
    const { result } = renderHook(() => useListExport(vi.fn().mockRejectedValue(new Error('connect ECONNREFUSED 10.0.3.4:5432'))))
    await act(() => result.current.onExport('xlsx'))
    expect(result.current.error).toBe('The export failed. Try again.')
  })

  it('clears the message when the next export starts, or when dismissed', async () => {
    const exporter = vi.fn().mockRejectedValueOnce(apiError('nope')).mockResolvedValueOnce(undefined).mockRejectedValueOnce(apiError('again'))
    const { result } = renderHook(() => useListExport(exporter))
    await act(() => result.current.onExport('xlsx'))
    expect(result.current.error).toBe('nope')
    await act(() => result.current.onExport('xlsx'))
    expect(result.current.error).toBeNull()
    await act(() => result.current.onExport('xlsx'))
    expect(result.current.error).toBe('again')
    act(() => result.current.dismissError())
    expect(result.current.error).toBeNull()
  })
})
