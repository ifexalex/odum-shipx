import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Button } from './Button'

describe('Button', () => {
  it('renders children and responds to clicks', async () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Save</Button>)
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('disables the button and ignores clicks while loading', async () => {
    const onClick = vi.fn()
    render(
      <Button loading onClick={onClick}>
        Save
      </Button>,
    )
    const button = screen.getByRole('button', { name: 'Save' })
    expect(button).toBeDisabled()
    await userEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('renders every variant without throwing', () => {
    const variants = [
      'primary',
      'accent',
      'secondary',
      'ghost',
      'danger',
      'danger-ghost',
    ] as const
    for (const variant of variants) {
      const { unmount } = render(<Button variant={variant}>{variant}</Button>)
      expect(screen.getByRole('button', { name: variant })).toBeInTheDocument()
      unmount()
    }
  })

  it('is type="button" unless told otherwise, so it never submits a form by accident', () => {
    render(<Button>Add row</Button>)
    expect(screen.getByRole('button', { name: 'Add row' })).toHaveAttribute('type', 'button')
  })

  it('shows direction as a trailing icon, not a typed arrow', () => {
    render(<Button trailingIcon="arrowright">View all</Button>)
    const button = screen.getByRole('button', { name: 'View all' })
    expect(button.textContent).toBe('View all')
    expect(button.querySelector('svg')).not.toBeNull()
  })
})
