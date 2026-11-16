import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { TopBar } from './TopBar'

describe('TopBar', () => {
  it('renders the title and breadcrumb', () => {
    render(<TopBar role="nigeria" title="Containers" breadcrumb={['Nigeria Office', 'Containers']} />)
    expect(screen.getByText('Containers', { selector: 'h1' })).toBeInTheDocument()
    expect(screen.getByText('Nigeria Office')).toBeInTheDocument()
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
