import { render, screen } from '@testing-library/react'
import { useState } from 'react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Modal } from './Modal'

describe('Modal', () => {
  it('renders nothing when closed', () => {
    render(
      <Modal open={false} title="Confirm">
        body
      </Modal>,
    )
    expect(screen.queryByText('body')).toBeNull()
  })

  it('renders title, body, and footer when open', () => {
    render(
      <Modal open title="Confirm payment" footer={<button>Confirm</button>}>
        Are you sure?
      </Modal>,
    )
    expect(screen.getByText('Confirm payment')).toBeInTheDocument()
    expect(screen.getByText('Are you sure?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeInTheDocument()
  })

  it('calls onClose when the overlay backdrop is clicked', async () => {
    const onClose = vi.fn()
    render(
      <Modal open title="Confirm" onClose={onClose}>
        body
      </Modal>,
    )
    const dialog = screen.getByRole('dialog')
    await userEvent.click(dialog.parentElement!)
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('does not call onClose when clicking inside the panel', async () => {
    const onClose = vi.fn()
    render(
      <Modal open title="Confirm" onClose={onClose}>
        body content
      </Modal>,
    )
    await userEvent.click(screen.getByText('body content'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('calls onClose when the close button is clicked', async () => {
    const onClose = vi.fn()
    render(
      <Modal open title="Confirm" onClose={onClose}>
        body
      </Modal>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls onClose on Escape', async () => {
    const onClose = vi.fn()
    render(
      <Modal open title="Confirm" onClose={onClose}>
        body
      </Modal>,
    )
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })
})

// A trigger that opens a dialog, as every real caller does: focus must come back to it.
function Harness({ children, footer }: { children?: React.ReactNode; footer?: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}>Open</button>
      <Modal open={open} title="Record payment" onClose={() => setOpen(false)} footer={footer}>
        {children}
      </Modal>
    </>
  )
}

describe('Modal accessibility (FE-04)', () => {
  describe('focus moves in', () => {
    it('to the first form field, not the Close button that comes first in the markup', async () => {
      render(
        <Harness footer={<button>Save</button>}>
          <input aria-label="Amount" />
          <input aria-label="Reference" />
        </Harness>,
      )
      await userEvent.click(screen.getByRole('button', { name: 'Open' }))
      expect(screen.getByLabelText('Amount')).toHaveFocus()
    })

    it('to the first action when the body has nothing to type into', async () => {
      render(<Harness footer={<button>Confirm</button>}>Are you sure?</Harness>)
      await userEvent.click(screen.getByRole('button', { name: 'Open' }))
      expect(screen.getByRole('button', { name: 'Confirm' })).toHaveFocus()
    })

    it('to Close when that is all there is', async () => {
      render(<Harness>Just a notice.</Harness>)
      await userEvent.click(screen.getByRole('button', { name: 'Open' }))
      expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
    })

    it('to the dialog itself when it has nothing focusable, so Tab cannot start behind it', () => {
      render(
        <>
          <button>Behind</button>
          <Modal open>Nothing to press here.</Modal>
        </>,
      )
      expect(screen.getByRole('dialog').parentElement).toHaveFocus()
    })

    it('but not past a field that asked for focus itself', () => {
      render(
        <Modal open title="Edit" footer={<button>Save</button>}>
          <input aria-label="First" />
          {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
          <input aria-label="Second" autoFocus />
        </Modal>,
      )
      expect(screen.getByLabelText('Second')).toHaveFocus()
    })

    it('skips controls that are disabled or hidden', async () => {
      render(
        <Harness>
          <input aria-label="Locked" disabled />
          <input aria-label="Concealed" hidden />
          <input aria-label="Usable" />
        </Harness>,
      )
      await userEvent.click(screen.getByRole('button', { name: 'Open' }))
      expect(screen.getByLabelText('Usable')).toHaveFocus()
    })
  })

  describe('Tab stays inside', () => {
    function renderOpen() {
      render(
        <>
          <button>Behind</button>
          <Modal open title="Pay" footer={<button>Save</button>} onClose={() => {}}>
            <input aria-label="Amount" />
          </Modal>
        </>,
      )
    }

    it('wraps from the last control to the first', async () => {
      renderOpen()
      screen.getByRole('button', { name: 'Save' }).focus()
      await userEvent.tab()
      expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus() // first in the dialog
    })

    it('wraps from the first control back to the last on Shift+Tab', async () => {
      renderOpen()
      screen.getByRole('button', { name: 'Close' }).focus()
      await userEvent.tab({ shift: true })
      expect(screen.getByRole('button', { name: 'Save' })).toHaveFocus()
    })

    it('moves through the dialog in order, and never reaches the page behind', async () => {
      renderOpen()
      const seen: string[] = []
      for (let i = 0; i < 6; i++) {
        await userEvent.tab()
        seen.push((document.activeElement as HTMLElement).getAttribute('aria-label') ?? document.activeElement!.textContent ?? '')
      }
      expect(seen).not.toContain('Behind')
      expect(new Set(seen)).toEqual(new Set(['Close', 'Amount', 'Save']))
    })

    it('pulls focus back in if it was somewhere behind the dialog', async () => {
      renderOpen()
      screen.getByRole('button', { name: 'Behind' }).focus()
      await userEvent.tab()
      expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
    })
  })

  describe('focus goes back', () => {
    it('to the button that opened the dialog, when it closes', async () => {
      render(<Harness footer={<button>Save</button>}>Body</Harness>)
      const trigger = screen.getByRole('button', { name: 'Open' })
      await userEvent.click(trigger)
      expect(trigger).not.toHaveFocus()
      await userEvent.keyboard('{Escape}')
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(trigger).toHaveFocus()
    })

    it('also when closed with the Close button', async () => {
      render(<Harness>Body</Harness>)
      const trigger = screen.getByRole('button', { name: 'Open' })
      await userEvent.click(trigger)
      await userEvent.click(screen.getByRole('button', { name: 'Close' }))
      expect(trigger).toHaveFocus()
    })

    it('without error when the opener has left the page', async () => {
      function Gone() {
        const [state, setState] = useState<'closed' | 'open' | 'gone'>('closed')
        return (
          <>
            {state !== 'gone' && <button onClick={() => setState('open')}>Open</button>}
            <Modal open={state === 'open'} title="T" onClose={() => setState('gone')}>
              Body
            </Modal>
          </>
        )
      }
      render(<Gone />)
      await userEvent.click(screen.getByRole('button', { name: 'Open' }))
      await userEvent.click(screen.getByRole('button', { name: 'Close' }))
      expect(screen.queryByRole('dialog')).toBeNull()
    })
  })

  describe('background scroll', () => {
    it('is locked while the dialog is open and restored after', async () => {
      document.body.style.overflow = 'auto'
      render(<Harness>Body</Harness>)
      await userEvent.click(screen.getByRole('button', { name: 'Open' }))
      expect(document.body.style.overflow).toBe('hidden')
      await userEvent.keyboard('{Escape}')
      expect(document.body.style.overflow).toBe('auto')
      document.body.style.overflow = ''
    })

    it('stays locked until the last of two stacked dialogs closes', async () => {
      function Stacked() {
        const [outer, setOuter] = useState(true)
        const [inner, setInner] = useState(true)
        return (
          <>
            <Modal open={outer} title="Outer" onClose={() => setOuter(false)}>
              body
            </Modal>
            <Modal open={inner} title="Inner" onClose={() => setInner(false)}>
              body
            </Modal>
          </>
        )
      }
      render(<Stacked />)
      expect(document.body.style.overflow).toBe('hidden')
      await userEvent.keyboard('{Escape}') // closes the inner one only
      expect(document.body.style.overflow).toBe('hidden')
      await userEvent.keyboard('{Escape}')
      expect(document.body.style.overflow).toBe('')
    })
  })

  describe('stacked dialogs', () => {
    it('closes only the innermost on Escape', async () => {
      const outerClose = vi.fn()
      const innerClose = vi.fn()
      render(
        <>
          <Modal open title="Outer" onClose={outerClose}>
            body
          </Modal>
          <Modal open title="Inner" onClose={innerClose}>
            body
          </Modal>
        </>,
      )
      await userEvent.keyboard('{Escape}')
      expect(innerClose).toHaveBeenCalledOnce()
      expect(outerClose).not.toHaveBeenCalled()
    })

    it('traps Tab inside the innermost', async () => {
      render(
        <>
          <Modal open title="Outer" footer={<button>Outer action</button>}>
            <input aria-label="Outer field" />
          </Modal>
          <Modal open title="Inner" footer={<button>Inner action</button>}>
            <input aria-label="Inner field" />
          </Modal>
        </>,
      )
      for (let i = 0; i < 5; i++) {
        await userEvent.tab()
        expect(screen.getByRole('dialog', { name: 'Inner' })).toContainElement(document.activeElement as HTMLElement)
      }
    })
  })

  describe('labelling', () => {
    it('is named by its visible heading', () => {
      render(<Modal open title="Record payment">Body</Modal>)
      const dialog = screen.getByRole('dialog', { name: 'Record payment' })
      const heading = screen.getByRole('heading', { name: 'Record payment' })
      expect(dialog).toHaveAttribute('aria-labelledby', heading.id)
      expect(dialog).toHaveAttribute('aria-modal', 'true')
    })

    it('has no empty label when there is no title', () => {
      render(<Modal open>Body</Modal>)
      expect(screen.getByRole('dialog')).not.toHaveAttribute('aria-labelledby')
    })
  })
})

