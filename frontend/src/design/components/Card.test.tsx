import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Card } from './Card'

describe('Card', () => {
  it('renders children with default padding and radius', () => {
    render(<Card>content</Card>)
    const card = screen.getByText('content')
    expect(card).toHaveStyle({ padding: '24px', borderRadius: '10px' })
  })

  it('applies custom padding and radius', () => {
    render(<Card padding={12} radius={4}>content</Card>)
    expect(screen.getByText('content')).toHaveStyle({ padding: '12px', borderRadius: '4px' })
  })
})
