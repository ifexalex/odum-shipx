import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Mono } from './Mono'

describe('Mono', () => {
  it('renders its children', () => {
    render(<Mono>SHPX-2024-00012</Mono>)
    expect(screen.getByText('SHPX-2024-00012')).toBeInTheDocument()
  })

  it('applies a custom color', () => {
    render(<Mono color="#dc2626">-12,000.00</Mono>)
    expect(screen.getByText('-12,000.00')).toHaveStyle({ color: '#dc2626' })
  })
})
