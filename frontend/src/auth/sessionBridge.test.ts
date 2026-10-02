import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { getSessionActions, registerSessionActions, useRegisterSessionActions } from './sessionBridge'

describe('sessionBridge', () => {
  it('throws if nothing has registered actions yet', () => {
    expect(() => getSessionActions()).toThrow(/before calling the API/)
  })

  it('returns the most recently registered actions', () => {
    const first = { refreshNow: vi.fn(), logout: vi.fn(), exitImpersonation: vi.fn() }
    const second = { refreshNow: vi.fn(), logout: vi.fn(), exitImpersonation: vi.fn() }
    registerSessionActions(first)
    registerSessionActions(second)
    expect(getSessionActions()).toBe(second)
  })

  it('useRegisterSessionActions registers on mount and on every re-render', () => {
    const actionsA = { refreshNow: vi.fn(), logout: vi.fn(), exitImpersonation: vi.fn() }
    const actionsB = { refreshNow: vi.fn(), logout: vi.fn(), exitImpersonation: vi.fn() }
    const { rerender } = renderHook(({ actions }) => useRegisterSessionActions(actions), {
      initialProps: { actions: actionsA },
    })
    expect(getSessionActions()).toBe(actionsA)

    rerender({ actions: actionsB })
    expect(getSessionActions()).toBe(actionsB)
  })
})
