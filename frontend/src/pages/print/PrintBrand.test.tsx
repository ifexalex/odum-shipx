/**
 * Tenant branding on printed documents (4.1 consumers): tenant identity when
 * branding_config is set, ShipX platform lockup as the fallback, and the
 * document-footer boilerplate.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PrintBrandFoot, PrintBrandHead } from './PrintBrand'

describe('PrintBrandHead', () => {
  it('renders the tenant name, tagline, and initials tile when branding is set', () => {
    render(
      <PrintBrandHead
        branding={{ display_name: 'Kola Cargo Hub', tagline: 'Aba to the world', primary_color: '#0a6ed1' }}
      />,
    )
    expect(screen.getByText('Kola Cargo Hub')).toBeInTheDocument()
    expect(screen.getByText('Aba to the world')).toBeInTheDocument()
    expect(screen.getByText('KC')).toBeInTheDocument()
  })

  it('falls back to the ShipX lockup when no display name is set', () => {
    render(<PrintBrandHead branding={null} />)
    // ShipxWordmark renders "ship" + "x" as separate spans
    expect(screen.getByText('ship')).toBeInTheDocument()
  })
})

describe('PrintBrandFoot', () => {
  it('renders each footer line', () => {
    render(<PrintBrandFoot branding={{ document_footer: 'Line one\nRC 1842519' }} />)
    expect(screen.getByText('Line one')).toBeInTheDocument()
    expect(screen.getByText('RC 1842519')).toBeInTheDocument()
  })

  it('renders nothing without a footer', () => {
    const { container } = render(<PrintBrandFoot branding={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})
