import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Banner } from './Banner'

describe('Banner', () => {
  it('renders the title and body', () => {
    render(<Banner variant="warning" title="Grace period ending">3 days left to clear storage fees</Banner>)
    expect(screen.getByText('Grace period ending')).toBeInTheDocument()
    expect(screen.getByText('3 days left to clear storage fees')).toBeInTheDocument()
  })

  it('calls onDismiss when the dismiss button is clicked', async () => {
    const onDismiss = vi.fn()
    render(
      <Banner variant="info" dismissible onDismiss={onDismiss}>
        Notice
      </Banner>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(onDismiss).toHaveBeenCalledOnce()
  })

  it('renders every variant without throwing', () => {
    const variants = ['info', 'success', 'warning', 'error'] as const
    for (const variant of variants) {
      const { unmount } = render(<Banner variant={variant}>{variant} message</Banner>)
      expect(screen.getByText(`${variant} message`)).toBeInTheDocument()
      unmount()
    }
  })
})
