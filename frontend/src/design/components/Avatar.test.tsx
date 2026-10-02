import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Avatar } from './Avatar'

describe('Avatar', () => {
  it('renders initials from up to two name parts', () => {
    render(<Avatar name="Adaeze Eze" />)
    expect(screen.getByText('AE')).toBeInTheDocument()
  })

  it('renders a fallback when no name is given', () => {
    render(<Avatar />)
    expect(screen.getByText('?')).toBeInTheDocument()
  })

  it('renders an image when src is provided', () => {
    render(<Avatar name="Adaeze Eze" src="https://example.com/a.png" />)
    expect(screen.getByRole('img', { name: 'Adaeze Eze' })).toBeInTheDocument()
  })

  it('renders without throwing for every role tint', () => {
    const roles = ['platform', 'admin', 'china', 'nigeria', 'warehouse', 'customer'] as const
    for (const roleColor of roles) {
      const { unmount } = render(<Avatar name="Joe Operator" roleColor={roleColor} />)
      unmount()
    }
  })
})
