import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useIdleTimeout } from './useIdleTimeout'

const IDLE = 30 * 60_000
const WARN = 60_000

function setup(enabled = true) {
  const onWarn = vi.fn()
  const onTimeout = vi.fn()
  const view = renderHook(() => useIdleTimeout({ idleMs: IDLE, warningMs: WARN, enabled, onWarn, onTimeout }))
  return { onWarn, onTimeout, view }
}

describe('useIdleTimeout', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('warns after the idle period, then times out after the warning', () => {
    const { onWarn, onTimeout } = setup(true)
    expect(onWarn).not.toHaveBeenCalled()
    act(() => void vi.advanceTimersByTime(IDLE))
    expect(onWarn).toHaveBeenCalledTimes(1)
    expect(onTimeout).not.toHaveBeenCalled()
    act(() => void vi.advanceTimersByTime(WARN))
    expect(onTimeout).toHaveBeenCalledTimes(1)
  })

  it('activity before the warning resets the idle countdown', () => {
    const { onWarn } = setup(true)
    act(() => void vi.advanceTimersByTime(IDLE - 1_000))
    act(() => window.dispatchEvent(new Event('keydown')))
    act(() => void vi.advanceTimersByTime(2_000))
    expect(onWarn).not.toHaveBeenCalled() // reset pushed it out
    act(() => void vi.advanceTimersByTime(IDLE))
    expect(onWarn).toHaveBeenCalledTimes(1)
  })

  it('ignores activity once the warning is showing (must explicitly reset)', () => {
    const { onWarn, onTimeout } = setup(true)
    act(() => void vi.advanceTimersByTime(IDLE))
    expect(onWarn).toHaveBeenCalledTimes(1)
    act(() => window.dispatchEvent(new Event('mousedown')))
    act(() => void vi.advanceTimersByTime(WARN))
    expect(onTimeout).toHaveBeenCalledTimes(1)
  })

  it('reset() dismisses the warning and re-arms without logging out', () => {
    const { onWarn, onTimeout, view } = setup(true)
    act(() => void vi.advanceTimersByTime(IDLE))
    expect(onWarn).toHaveBeenCalledTimes(1)
    act(() => view.result.current.reset())
    act(() => void vi.advanceTimersByTime(WARN))
    expect(onTimeout).not.toHaveBeenCalled() // reset cancelled the hard logout
    act(() => void vi.advanceTimersByTime(IDLE))
    expect(onWarn).toHaveBeenCalledTimes(2) // re-armed
  })

  it('does nothing while disabled', () => {
    const { onWarn } = setup(false)
    act(() => void vi.advanceTimersByTime(IDLE + WARN))
    expect(onWarn).not.toHaveBeenCalled()
  })
})
