import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PageHeader } from './PageHeader'

describe('PageHeader', () => {
  it('renders eyebrow, title, subtitle, and actions', () => {
    render(
      <PageHeader
        eyebrow="China Office"
        title="Containers"
        subtitle="All active and historical containers"
        actions={<button>New container</button>}
      />,
    )
    expect(screen.getByText('China Office')).toBeInTheDocument()
    expect(screen.getByText('Containers')).toBeInTheDocument()
    expect(screen.getByText('All active and historical containers')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New container' })).toBeInTheDocument()
  })
})
