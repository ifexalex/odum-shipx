import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Sidebar, type NavGroup } from './Sidebar'

const items: NavGroup[] = [
  {
    group: 'Operations',
    items: [
      { icon: 'container', label: 'Containers', active: true },
      { icon: 'package', label: 'Packing lists', count: 12 },
    ],
  },
]

describe('Sidebar', () => {
  it('renders the default brand and nav items', () => {
    render(<Sidebar role="nigeria" items={items} />)
    expect(screen.getByText('ship')).toBeInTheDocument()
    expect(screen.getByText('Containers')).toBeInTheDocument()
    expect(screen.getByText('Packing lists')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
  })

  it('renders the group label and role badge', () => {
    render(<Sidebar role="china" items={items} />)
    expect(screen.getByText('Operations')).toBeInTheDocument()
    expect(screen.getByText('China Office')).toBeInTheDocument()
  })

  it('hides labels and group headings when collapsed', () => {
    render(<Sidebar role="nigeria" items={items} collapsed />)
    expect(screen.queryByText('Operations')).toBeNull()
  })

  it('calls onClick for a nav item', async () => {
    const onClick = vi.fn()
    render(
      <Sidebar
        role="nigeria"
        items={[{ items: [{ label: 'Containers', onClick }] }]}
      />,
    )
    await userEvent.click(screen.getByText('Containers'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('does not repeat the signed-in user or offer sign-out: both live in the top bar’s account menu (FD-15)', () => {
    render(<Sidebar role="nigeria" items={items} />)
    expect(screen.queryByRole('button', { name: /log out|sign out/i })).toBeNull()
  })

  it('marks the active item as the current page', () => {
    render(<Sidebar role="nigeria" items={[{ items: [{ label: 'Billing', active: true }, { label: 'Refunds' }] }]} />)
    expect(screen.getByRole('button', { name: 'Billing' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'Refunds' })).not.toHaveAttribute('aria-current')
  })

  it('renders a custom brand slot in place of the default wordmark', () => {
    render(<Sidebar role="platform" items={items} brand={<div>Custom Brand</div>} />)
    expect(screen.getByText('Custom Brand')).toBeInTheDocument()
    expect(screen.queryByText('ship')).toBeNull()
  })
})
