import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { TopBar } from './TopBar'

describe('TopBar', () => {
  it('holds only global controls: no page title, breadcrumb or page actions (FD-14)', () => {
    render(<TopBar role="nigeria" user={{ name: 'Adaeze Eze', role: 'Staff' }} />)
    expect(screen.queryByRole('heading')).toBeNull()
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

  it('renders whatever search control it is given, ahead of the notifications', () => {
    render(<TopBar role="nigeria" search={<input aria-label="Find" />} />)
    const find = screen.getByLabelText('Find')
    const bell = screen.getByRole('button', { name: 'Notifications' })
    expect(find.compareDocumentPosition(bell) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})
