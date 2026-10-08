import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ShipxWordmark } from './ShipxWordmark'

describe('ShipxWordmark', () => {
  it('renders the shipx wordmark', () => {
    render(<ShipxWordmark />)
    expect(screen.getByText('ship')).toBeInTheDocument()
    expect(screen.getByText('x')).toBeInTheDocument()
  })

  it('does not render the "by Odum" co-mark by default', () => {
    render(<ShipxWordmark />)
    expect(screen.queryByText('by Odum')).toBeNull()
  })

  it('renders the "by Odum" co-mark when showBy is set', () => {
    render(<ShipxWordmark showBy />)
    expect(screen.getByText('by Odum')).toBeInTheDocument()
  })
})
