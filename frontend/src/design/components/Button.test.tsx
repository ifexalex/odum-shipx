import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
      'danger-outline',
      'success',
    ] as const
    for (const variant of variants) {
      const { unmount } = render(<Button variant={variant}>{variant}</Button>)
      expect(screen.getByRole('button', { name: variant })).toBeInTheDocument()
      unmount()
    }
  })

  describe('accent dev-warning', () => {
    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('warns when more than one accent button is mounted at once', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
      render(
        <>
          <Button variant="accent">Confirm payment</Button>
          <Button variant="accent">Generate release note</Button>
        </>,
      )
      expect(warn).toHaveBeenCalledWith(expect.stringContaining('variant="accent"'))
    })

    it('does not warn for a single accent button', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
      render(<Button variant="accent">Confirm payment</Button>)
      expect(warn).not.toHaveBeenCalled()
    })
  })
})
