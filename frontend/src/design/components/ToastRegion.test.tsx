/**
 * FD-21: toasts confirm that an action worked, then go away; a screen reader hears each once.
 */
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOAST_DURATION_MS, resetToasts, toast } from '../toast'

describe('toasts (FD-21)', () => {
  beforeEach(() => resetToasts())
  afterEach(() => vi.useRealTimers())

  it('shows what happened and to which record, in a polite live region', () => {
    act(() => {
      toast.success('Payment recorded', 'ACM-INV-0042')
    })
    expect(screen.getByText('Payment recorded')).toBeInTheDocument()
    expect(screen.getByText('ACM-INV-0042')).toBeInTheDocument()
    expect(screen.getByText('Payment recorded').closest('[aria-live]')).toHaveAttribute(
      'aria-live',
      'polite',
    )
  })

  it('goes away after four seconds', () => {
    vi.useFakeTimers()
    act(() => {
      toast.success('Capacity added')
    })
    act(() => vi.advanceTimersByTime(TOAST_DURATION_MS - 1))
    expect(screen.getByText('Capacity added')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(1))
    expect(screen.queryByText('Capacity added')).toBeNull()
  })

  it('can be dismissed, and never stacks more than three', async () => {
    act(() => {
      for (const n of [1, 2, 3, 4]) toast.info(`Toast ${n}`)
    })
    expect(screen.queryByText('Toast 1')).toBeNull()
    expect(screen.getAllByText(/^Toast [234]$/)).toHaveLength(3)
    await userEvent.click(screen.getAllByRole('button', { name: 'Dismiss' })[0]!)
    expect(screen.queryByText('Toast 2')).toBeNull()
  })

  it('renders nothing extra when there is nothing to say', () => {
    render(<div data-testid="page" />)
    expect(screen.queryByRole('button', { name: 'Dismiss' })).toBeNull()
  })
})
