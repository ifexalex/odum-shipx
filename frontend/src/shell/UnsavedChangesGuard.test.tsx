import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState, type JSX } from 'react'
import { createMemoryRouter, Link, MemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { UnsavedChangesGuard } from './UnsavedChangesGuard'

function Form({ allow }: { allow?: (pathname: string) => boolean }): JSX.Element {
  const [value, setValue] = useState('')
  return (
    <div>
      <UnsavedChangesGuard when={value !== ''} allow={allow} />
      <label>
        Name
        <input value={value} onChange={(e) => setValue(e.target.value)} />
      </label>
      <Link to="/elsewhere">Elsewhere</Link>
      <Link to="/containers/new">Create a container</Link>
    </div>
  )
}

function renderInDataRouter(allow?: (pathname: string) => boolean) {
  const router = createMemoryRouter(
    [
      { path: '/form', element: <Form allow={allow} /> },
      { path: '/elsewhere', element: <p>Elsewhere page</p> },
      { path: '/containers/new', element: <p>New container page</p> },
    ],
    { initialEntries: ['/form'] },
  )
  render(<RouterProvider router={router} />)
  return router
}

describe('UnsavedChangesGuard (FD-54)', () => {
  it('lets an untouched form go without asking', async () => {
    renderInDataRouter()
    await userEvent.click(screen.getByRole('link', { name: 'Elsewhere' }))
    expect(await screen.findByText('Elsewhere page')).toBeInTheDocument()
  })

  it('asks before leaving with unsaved input, and keeps it on Keep editing', async () => {
    renderInDataRouter()
    await userEvent.type(screen.getByLabelText('Name'), 'Ada')
    await userEvent.click(screen.getByRole('link', { name: 'Elsewhere' }))
    const dialog = await screen.findByRole('dialog', { name: 'Leave without saving?' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Keep editing' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByLabelText('Name')).toHaveValue('Ada')
  })

  it('goes where the user was going on Leave', async () => {
    renderInDataRouter()
    await userEvent.type(screen.getByLabelText('Name'), 'Ada')
    await userEvent.click(screen.getByRole('link', { name: 'Elsewhere' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Leave' }))
    expect(await screen.findByText('Elsewhere page')).toBeInTheDocument()
  })

  it('asks on the browser back button too', async () => {
    const router = createMemoryRouter(
      [
        { path: '/start', element: <Link to="/form">Open form</Link> },
        { path: '/form', element: <Form /> },
      ],
      { initialEntries: ['/start'] },
    )
    render(<RouterProvider router={router} />)
    await userEvent.click(screen.getByRole('link', { name: 'Open form' }))
    await userEvent.type(await screen.findByLabelText('Name'), 'Ada')
    void router.navigate(-1)
    expect(await screen.findByRole('dialog', { name: 'Leave without saving?' })).toBeInTheDocument()
  })

  it('does not ask about a destination the form allows', async () => {
    renderInDataRouter((pathname) => pathname === '/containers/new')
    await userEvent.type(screen.getByLabelText('Name'), 'Ada')
    await userEvent.click(screen.getByRole('link', { name: 'Create a container' }))
    expect(await screen.findByText('New container page')).toBeInTheDocument()
  })

  it('asks the browser to confirm closing the tab only while there is unsaved input', async () => {
    renderInDataRouter()
    const before = new Event('beforeunload', { cancelable: true })
    fireEvent(window, before)
    expect(before.defaultPrevented).toBe(false)

    await userEvent.type(screen.getByLabelText('Name'), 'Ada')
    const after = new Event('beforeunload', { cancelable: true })
    fireEvent(window, after)
    expect(after.defaultPrevented).toBe(true)
  })

  it('works without a data router, with the tab-close prompt only', async () => {
    render(
      <MemoryRouter>
        <Form />
      </MemoryRouter>,
    )
    await userEvent.type(screen.getByLabelText('Name'), 'Ada')
    const event = new Event('beforeunload', { cancelable: true })
    fireEvent(window, event)
    expect(event.defaultPrevented).toBe(true)
  })
})
