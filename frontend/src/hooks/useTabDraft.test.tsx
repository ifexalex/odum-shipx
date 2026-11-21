import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionContext, type SessionContextValue } from '../auth/SessionContext'
import { readTabDraft, useTabDraft } from './useTabDraft'

const ME = { tenantId: 't1', userId: 'u1' }

function wrapper({ children }: { children: ReactNode }) {
  return <SessionContext.Provider value={{ session: ME } as unknown as SessionContextValue}>{children}</SessionContext.Provider>
}

describe('useTabDraft', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('keeps changed input in the tab, for this tenant and user only', () => {
    const { result } = renderHook(() => useTabDraft('form', { name: 'Ada' }, { name: '' }), { wrapper })
    act(() => vi.advanceTimersByTime(500))
    expect(result.current.savedAt).not.toBeNull()
    expect(readTabDraft('form', ME)).toEqual({ name: 'Ada' })
    expect(readTabDraft('form', { tenantId: 't1', userId: 'u2' })).toBeNull()
    expect(readTabDraft('form', { tenantId: 't2', userId: 'u1' })).toBeNull()
  })

  it('stores nothing while the input matches an untouched form', () => {
    const { result } = renderHook(() => useTabDraft('form', { name: '' }, { name: '' }), { wrapper })
    act(() => vi.advanceTimersByTime(500))
    expect(result.current.savedAt).toBeNull()
    expect(readTabDraft('form', ME)).toBeNull()
  })

  it('stores nothing when disabled', () => {
    renderHook(() => useTabDraft('form', { name: 'Ada' }, { name: '' }, false), { wrapper })
    act(() => vi.advanceTimersByTime(500))
    expect(readTabDraft('form', ME)).toBeNull()
  })

  it('forgets the draft on clear, even with a write pending', () => {
    const { result } = renderHook(() => useTabDraft('form', { name: 'Ada' }, { name: '' }), { wrapper })
    act(() => result.current.clear())
    act(() => vi.advanceTimersByTime(500))
    expect(readTabDraft('form', ME)).toBeNull()
    expect(result.current.savedAt).toBeNull()
  })
})
