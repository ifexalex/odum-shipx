/**
 * FD-12: a stray backdrop click or Escape no longer throws away what was typed in a dialog. Both kinds of dialog:
 * the shared Modal, and a page's own overlay with DialogGuard.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState, type JSX } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { DialogGuard, Modal } from './Modal'

function ModalForm({ onClose }: { onClose: () => void }): JSX.Element {
  const [open, setOpen] = useState(true)
  const close = (): void => {
    onClose()
    setOpen(false)
  }
  return (
    <Modal open={open} onClose={close} title="Add charge">
      <label htmlFor="desc">Description</label>
      <input id="desc" />
      <button type="button" onClick={close}>
        Cancel
      </button>
    </Modal>
  )
}

function HandRolled({ onClose }: { onClose: () => void }): JSX.Element {
  const [open, setOpen] = useState(true)
  if (!open) return <p>closed</p>
  const close = (): void => {
    onClose()
    setOpen(false)
  }
  return (
    <div data-testid="backdrop" onClick={close}>
      <DialogGuard onClose={close} />
      <div role="dialog" aria-modal="true" aria-label="Reject" onClick={(e) => e.stopPropagation()}>
        <label htmlFor="reason">Reason</label>
        <input id="reason" />
      </div>
    </div>
  )
}

const backdropOfModal = (): HTMLElement => screen.getByRole('dialog').parentElement!

describe('unsaved input in a dialog (FD-12)', () => {
  it('Modal: a backdrop click with typed input asks first, and the input is still there', async () => {
    const onClose = vi.fn()
    render(<ModalForm onClose={onClose} />)
    await userEvent.type(screen.getByLabelText('Description'), 'Forklift hire')
    fireEvent.click(backdropOfModal())

    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('alertdialog', { name: 'Discard your changes?' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
    expect(screen.getByLabelText('Description')).toHaveValue('Forklift hire')
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('Modal: Escape with typed input asks too, and Discard closes', async () => {
    const onClose = vi.fn()
    render(<ModalForm onClose={onClose} />)
    await userEvent.type(screen.getByLabelText('Description'), 'x')
    await userEvent.keyboard('{Escape}')
    expect(onClose).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Discard changes' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('Modal: with nothing typed, a backdrop click closes at once', () => {
    const onClose = vi.fn()
    render(<ModalForm onClose={onClose} />)
    fireEvent.click(backdropOfModal())
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('Modal: Cancel closes at once even with typed input — that is a decision, not an accident', async () => {
    const onClose = vi.fn()
    render(<ModalForm onClose={onClose} />)
    await userEvent.type(screen.getByLabelText('Description'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it("a page's own dialog: the backdrop click is caught before the page's handler, and the input survives", async () => {
    const onClose = vi.fn()
    render(<HandRolled onClose={onClose} />)
    await userEvent.type(screen.getByLabelText('Reason'), 'Wrong weight')
    fireEvent.click(screen.getByTestId('backdrop'))

    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Reason')).toHaveValue('Wrong weight')
    await userEvent.click(screen.getByRole('button', { name: 'Discard changes' }))
    expect(onClose).toHaveBeenCalledOnce()
    expect(screen.getByText('closed')).toBeInTheDocument()
  })

  it("a page's own dialog with nothing typed still closes on a backdrop click", () => {
    const onClose = vi.fn()
    render(<HandRolled onClose={onClose} />)
    fireEvent.click(screen.getByTestId('backdrop'))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
