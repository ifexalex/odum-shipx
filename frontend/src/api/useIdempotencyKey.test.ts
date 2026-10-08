import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useIdempotencyKey } from './useIdempotencyKey'

describe('useIdempotencyKey', () => {
  it('stays stable across re-renders, simulating a network-level retry', () => {
    const { result, rerender } = renderHook(() => useIdempotencyKey())
    const first = result.current.key
    rerender()
    expect(result.current.key).toBe(first)
  })

  it('produces a new key only when regenerate() is called', () => {
    const { result } = renderHook(() => useIdempotencyKey())
    const first = result.current.key

    act(() => {
      result.current.regenerate()
    })

    expect(result.current.key).not.toBe(first)
  })
})
