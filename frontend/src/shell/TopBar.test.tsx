import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
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

  it('opens the account menu: my profile, a switch to each other role, sign out (FD-15)', async () => {
    const onProfile = vi.fn()
    const onLogout = vi.fn()
    const onRoleChange = vi.fn()
    render(
      <TopBar
        role="nigeria"
        user={{ name: 'Adaeze Eze', role: 'Nigeria Office Staff' }}
        onProfile={onProfile}
        onLogout={onLogout}
        roleOptions={[
          { value: 'nigeria_office_staff', label: 'Nigeria Office Staff' },
          { value: 'warehouse_attendant', label: 'Warehouse Attendant' },
        ]}
        activeRole="nigeria_office_staff"
        onRoleChange={onRoleChange}
      />,
    )
    const account = screen.getByRole('button', { name: /Adaeze Eze/ })
    expect(account).toHaveAttribute('aria-haspopup', 'menu')
    await userEvent.click(account)
    expect(screen.getAllByRole('menuitem').map((i) => i.textContent)).toEqual([
      'My profile',
      'Work as Warehouse Attendant',
      'Sign out',
    ])
    await userEvent.click(screen.getByRole('menuitem', { name: 'Work as Warehouse Attendant' }))
    expect(onRoleChange).toHaveBeenCalledWith('warehouse_attendant')
    await userEvent.click(account)
    await userEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }))
    expect(onLogout).toHaveBeenCalledOnce()
    await userEvent.click(account)
    await userEvent.click(screen.getByRole('menuitem', { name: 'My profile' }))
    expect(onProfile).toHaveBeenCalledOnce()
  })

  it('offers no role switch to a single-role user', async () => {
    render(<TopBar role="nigeria" user={{ name: 'A', role: 'R' }} roleOptions={[{ value: 'x', label: 'X' }]} activeRole="x" onLogout={() => undefined} />)
    await userEvent.click(screen.getByRole('button', { name: /^A/ }))
    expect(screen.getAllByRole('menuitem').map((i) => i.textContent)).toEqual(['Sign out'])
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
