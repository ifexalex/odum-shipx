import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SessionContext } from '../../auth/SessionContext'
import { MenuButton } from './MenuButton'

const ITEMS = (cancel = vi.fn(), print = vi.fn()) => [
  { label: 'Print view', onSelect: print },
  { label: 'Cancel invoice', tone: 'danger' as const, onSelect: cancel },
]

describe('MenuButton (FD-14)', () => {
  it('is a named button that opens a menu of further actions', async () => {
    render(<MenuButton label="More invoice actions" items={ITEMS()} />)
    const button = screen.getByRole('button', { name: 'More invoice actions' })
    expect(button).toHaveAttribute('aria-haspopup', 'menu')
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getAllByRole('menuitem').map((i) => i.textContent)).toEqual(['Print view', 'Cancel invoice'])
    expect(screen.getByRole('menuitem', { name: 'Print view' })).toHaveFocus()
  })

  it('runs the chosen action, closes and returns focus to the button', async () => {
    const cancel = vi.fn()
    render(<MenuButton items={ITEMS(cancel)} />)
    await userEvent.click(screen.getByRole('button', { name: 'More actions' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Cancel invoice' }))
    expect(cancel).toHaveBeenCalledOnce()
    expect(screen.queryByRole('menu')).toBeNull()
    expect(screen.getByRole('button', { name: 'More actions' })).toHaveFocus()
  })

  it('moves with the arrow keys, wraps, and closes on Escape', async () => {
    render(<MenuButton items={ITEMS()} />)
    screen.getByRole('button', { name: 'More actions' }).focus()
    await userEvent.keyboard('{ArrowUp}')
    expect(screen.getByRole('menuitem', { name: 'Cancel invoice' })).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: 'Print view' })).toHaveFocus()
    await userEvent.keyboard('{End}')
    expect(screen.getByRole('menuitem', { name: 'Cancel invoice' })).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
    expect(screen.getByRole('button', { name: 'More actions' })).toHaveFocus()
  })

  it('closes on a click outside', async () => {
    render(
      <>
        <MenuButton items={ITEMS()} />
        <p>Elsewhere</p>
      </>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'More actions' }))
    await userEvent.click(screen.getByText('Elsewhere'))
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('renders nothing with no items', () => {
    const { container } = render(<MenuButton items={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('disables a destructive item during a read-only session', async () => {
    const cancel = vi.fn()
    const session = { readOnly: true } as never
    render(
      <SessionContext.Provider value={{ session } as never}>
        <MenuButton items={ITEMS(cancel)} />
      </SessionContext.Provider>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'More actions' }))
    const item = screen.getByRole('menuitem', { name: 'Cancel invoice' })
    expect(item).toHaveAttribute('aria-disabled', 'true')
    await userEvent.click(item)
    expect(cancel).not.toHaveBeenCalled()
    expect(screen.getByRole('menuitem', { name: 'Print view' })).not.toHaveAttribute('aria-disabled')
  })
})
