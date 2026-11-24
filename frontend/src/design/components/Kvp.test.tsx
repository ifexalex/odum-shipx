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

describe('Kvp optional (FD-17)', () => {
  it('leaves an optional row out when it has no value, rather than showing a dash', () => {
    const { container } = render(
      <>
        <Kvp optional label="Vessel" value={null} />
        <Kvp optional label="Voyage" value="" />
        <Kvp optional label="Seal #" value={false} />
        <Kvp optional label="Shipping line" value="Maersk" />
      </>,
    )
    expect(screen.queryByText('Vessel')).toBeNull()
    expect(screen.queryByText('Voyage')).toBeNull()
    expect(screen.queryByText('Seal #')).toBeNull()
    expect(screen.getByText('Maersk')).toBeInTheDocument()
    expect(container.childElementCount).toBe(1)
  })

  it('still shows a row that is not optional', () => {
    render(<Kvp label="Vessel" value="—" />)
    expect(screen.getByText('Vessel')).toBeInTheDocument()
  })
})
