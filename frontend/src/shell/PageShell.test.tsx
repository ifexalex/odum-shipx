import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PageShell } from './PageShell'

describe('PageShell', () => {
  it('renders sidebar, topbar, and content children', () => {
    render(
      <PageShell sidebar={<div>Sidebar</div>} topbar={<div>TopBar</div>}>
        <div>Page content</div>
      </PageShell>,
    )
    expect(screen.getByText('Sidebar')).toBeInTheDocument()
    expect(screen.getByText('TopBar')).toBeInTheDocument()
    expect(screen.getByText('Page content')).toBeInTheDocument()
  })
})
