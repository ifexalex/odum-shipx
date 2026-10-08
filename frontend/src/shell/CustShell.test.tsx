import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CustShell } from './CustShell'

describe('CustShell', () => {
  it('renders the topnav slot and children content', () => {
    render(
      <CustShell topnav={<div>Top nav</div>}>
        <div>Page content</div>
      </CustShell>,
    )
    expect(screen.getByText('Top nav')).toBeInTheDocument()
    expect(screen.getByText('Page content')).toBeInTheDocument()
  })
})
