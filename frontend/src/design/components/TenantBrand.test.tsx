import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TenantBrand } from './TenantBrand'

describe('TenantBrand', () => {
  it('renders the tenant display name and "on ShipX" tag', () => {
    render(<TenantBrand name="Acme Logistics" />)
    expect(screen.getByText('Acme Logistics')).toBeInTheDocument()
    expect(screen.getByText('on ShipX')).toBeInTheDocument()
  })

  it('falls back to initials when no logo is uploaded', () => {
    render(<TenantBrand name="Acme Logistics" />)
    expect(screen.getByText('AC')).toBeInTheDocument()
  })

  it('renders the uploaded logo image when provided', () => {
    render(<TenantBrand name="Acme Logistics" logoUrl="https://example.com/logo.png" />)
    expect(screen.getByRole('img', { name: 'Acme Logistics' })).toBeInTheDocument()
  })
})
