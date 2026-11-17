import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useSeedOnce } from './useSeedOnce'

interface Source {
  data: { value: number } | undefined
  isFetchedAfterMount: boolean
}

describe('useSeedOnce', () => {
  it('does not seed from a cached copy that has not been re-read yet', () => {
    const seed = vi.fn()
    renderHook(({ source }: { source: Source }) => useSeedOnce(source, seed), {
      initialProps: { source: { data: { value: 1 }, isFetchedAfterMount: false } },
    })
    expect(seed).not.toHaveBeenCalled()
  })

  it('seeds once the fresh value arrives', () => {
    const seed = vi.fn()
    const { rerender } = renderHook(({ source }: { source: Source }) => useSeedOnce(source, seed), {
      initialProps: { source: { data: { value: 1 }, isFetchedAfterMount: false } as Source },
    })
    rerender({ source: { data: { value: 2 }, isFetchedAfterMount: true } })
    expect(seed).toHaveBeenCalledTimes(1)
    expect(seed).toHaveBeenCalledWith({ value: 2 })
  })

  it('never overwrites the form again when a later refetch brings new data', () => {
    const seed = vi.fn()
    const { rerender } = renderHook(({ source }: { source: Source }) => useSeedOnce(source, seed), {
      initialProps: { source: { data: { value: 1 }, isFetchedAfterMount: true } as Source },
    })
    rerender({ source: { data: { value: 99 }, isFetchedAfterMount: true } })
    rerender({ source: { data: { value: 100 }, isFetchedAfterMount: true } })
    expect(seed).toHaveBeenCalledTimes(1)
    expect(seed).toHaveBeenCalledWith({ value: 1 })
  })

  it('waits when the read failed and there is nothing to seed from', () => {
    const seed = vi.fn()
    renderHook(() => useSeedOnce({ data: undefined, isFetchedAfterMount: true }, seed))
    expect(seed).not.toHaveBeenCalled()
  })
})
