import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TenantBrand } from './TenantBrand'

describe('TenantBrand', () => {
  it('renders the tenant display name', () => {
    render(<TenantBrand name="Acme Logistics" />)
    expect(screen.getByText('Acme Logistics')).toBeInTheDocument()
  })

  it('optionally renders the "on ShipX" tag when showTag is true', () => {
    render(<TenantBrand name="Acme Logistics" showTag />)
    expect(screen.getByText('on ShipX')).toBeInTheDocument()
  })

  it('falls back to initials when no logo is uploaded', () => {
    render(<TenantBrand name="Acme Logistics" />)
    expect(screen.getByText('AL')).toBeInTheDocument()
  })

  it('renders the uploaded logo image when provided', () => {
    render(<TenantBrand name="Acme Logistics" logoUrl="https://example.com/logo.png" />)
    const img = screen.getByRole('img', { name: 'Acme Logistics logo' })
    expect(img).toHaveAttribute('src', 'https://example.com/logo.png')
  })

  it('hides the company name in compact mode', () => {
    render(<TenantBrand name="Acme Logistics" compact />)
    expect(screen.queryByText('Acme Logistics')).not.toBeInTheDocument()
  })
})
