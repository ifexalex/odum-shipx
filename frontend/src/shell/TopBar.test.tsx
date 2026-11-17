import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { TopBar } from './TopBar'

describe('TopBar', () => {
  it('renders the title and a breadcrumb whose crumbs link back up (FD-45)', () => {
    render(
      <MemoryRouter>
        <TopBar
          role="nigeria"
          title="INV-0042"
          breadcrumb={[{ label: 'Billing', to: '/billing' }, { label: 'INV-0042' }]}
        />
      </MemoryRouter>,
    )
    expect(screen.getByText('INV-0042', { selector: 'h1' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(nav.querySelectorAll('ol a[href="/billing"]')).toHaveLength(1)
    expect(nav.querySelector('[aria-current="page"]')).toHaveTextContent('INV-0042')
  })

  it('shows no breadcrumb for an empty trail (a top-level page)', () => {
    render(<TopBar role="nigeria" title="Containers" breadcrumb={[]} />)
    expect(screen.queryByRole('navigation', { name: 'Breadcrumb' })).toBeNull()
  })

  it('shows the unread notification count', () => {
    render(<TopBar role="nigeria" notifications={5} />)
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('renders notificationsPanel inside the bell\'s own positioning wrapper', () => {
    render(
      <TopBar
        role="nigeria"
        notifications={2}
        notificationsPanel={<div data-testid="notif-panel">panel content</div>}
      />,
    )
    const panel = screen.getByTestId('notif-panel')
    expect(panel).toBeInTheDocument()
    // Same parent as the bell button — that's what anchors the dropdown.
    expect(screen.getByRole('button', { name: /notifications/i }).parentElement).toContainElement(panel)
  })

  it('renders the user menu and calls onUserMenuClick', async () => {
    const onUserMenuClick = vi.fn()
    render(
      <TopBar
        role="nigeria"
        user={{ name: 'Adaeze Eze', role: 'Nigeria Office Staff' }}
        onUserMenuClick={onUserMenuClick}
      />,
    )
    await userEvent.click(screen.getByText('Adaeze Eze'))
    expect(onUserMenuClick).toHaveBeenCalledOnce()
  })
})

describe('TopBar search slot', () => {
  it('renders no search box unless one is passed', () => {
    render(<TopBar role="nigeria" />)
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('renders whatever search control it is given, ahead of the actions', () => {
    render(<TopBar role="nigeria" search={<input aria-label="Find" />} actions={<button type="button">Create</button>} />)
    const find = screen.getByLabelText('Find')
    const create = screen.getByRole('button', { name: 'Create' })
    expect(find.compareDocumentPosition(create) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})
