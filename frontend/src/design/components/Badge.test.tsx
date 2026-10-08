import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Badge } from './Badge'

describe('Badge', () => {
  it('renders children with a dot by default', () => {
    const { container } = render(<Badge variant="success">Paid</Badge>)
    expect(screen.getByText('Paid')).toBeInTheDocument()
    expect(container.querySelector('span > span')).not.toBeNull()
  })

  it('omits the dot when dot={false}', () => {
    const { container } = render(
      <Badge variant="success" dot={false}>
        Paid
      </Badge>,
    )
    expect(container.querySelector('span > span')).toBeNull()
  })

  it('renders every variant without throwing', () => {
    const variants = [
      'success',
      'warning',
      'error',
      'info',
      'accent',
      'purple',
      'neutral',
      'primary',
    ] as const
    for (const variant of variants) {
      const { unmount } = render(<Badge variant={variant}>{variant}</Badge>)
      expect(screen.getByText(variant)).toBeInTheDocument()
      unmount()
    }
  })
})
