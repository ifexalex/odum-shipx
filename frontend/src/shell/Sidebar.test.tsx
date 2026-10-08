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

  it('renders the user footer and calls onLogout', async () => {
    const onLogout = vi.fn()
    render(
      <Sidebar
        role="nigeria"
        items={items}
        user={{ name: 'Adaeze Eze', role: 'Nigeria Office Staff' }}
        onLogout={onLogout}
      />,
    )
    expect(screen.getByText('Adaeze Eze')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(onLogout).toHaveBeenCalledOnce()
  })

  it('renders just the logout button when onLogout is given without a user', async () => {
    const onLogout = vi.fn()
    render(<Sidebar role="nigeria" items={items} onLogout={onLogout} />)
    expect(screen.getByRole('button', { name: 'Log out' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(onLogout).toHaveBeenCalledOnce()
  })

  it('renders a custom brand slot in place of the default wordmark', () => {
    render(<Sidebar role="platform" items={items} brand={<div>Custom Brand</div>} />)
    expect(screen.getByText('Custom Brand')).toBeInTheDocument()
    expect(screen.queryByText('ship')).toBeNull()
  })
})
