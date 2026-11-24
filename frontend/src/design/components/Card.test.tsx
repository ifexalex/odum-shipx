import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Card } from './Card'

describe('Card', () => {
  it('renders children with the default padding and radius', () => {
    render(<Card>content</Card>)
    const card = screen.getByText('content')
    expect(card.className).toContain('padDefault')
    expect(card.style.borderRadius).toBe('var(--radius-lg)')
  })

  it('takes a named padding (FD-02) and a custom radius', () => {
    render(
      <Card padding="none" radius="xl">
        content
      </Card>,
    )
    const card = screen.getByText('content')
    expect(card.className).toContain('padNone')
    expect(card.style.borderRadius).toBe('var(--radius-xl)')
  })

  it('offers a large padding', () => {
    render(<Card padding="large">content</Card>)
    expect(screen.getByText('content').className).toContain('padLarge')
  })
})
