import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Kvp } from './Kvp'

describe('Kvp', () => {
  it('renders label and value', () => {
    render(<Kvp label="Container #" value="MSCU1234567" />)
    expect(screen.getByText('Container #')).toBeInTheDocument()
    expect(screen.getByText('MSCU1234567')).toBeInTheDocument()
  })

  it('accepts a ReactNode value', () => {
    render(<Kvp label="Status" value={<span data-testid="custom">Approved</span>} />)
    expect(screen.getByTestId('custom')).toBeInTheDocument()
  })
})
