import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { UserCell } from './UserCell'

describe('UserCell', () => {
  it('renders name and meta text with an avatar', () => {
    render(<UserCell name="Ngozi Okonkwo" email="14 shipments lifetime" />)
    expect(screen.getByText('Ngozi Okonkwo')).toBeInTheDocument()
    expect(screen.getByText('14 shipments lifetime')).toBeInTheDocument()
  })
})
