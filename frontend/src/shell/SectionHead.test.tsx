import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SectionHead } from './SectionHead'

describe('SectionHead', () => {
  it('renders title, sub, and action', () => {
    render(<SectionHead title="Recent shipments" sub="Last 30 days" action={<button>View all</button>} />)
    expect(screen.getByText('Recent shipments')).toBeInTheDocument()
    expect(screen.getByText('Last 30 days')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View all' })).toBeInTheDocument()
  })
})
