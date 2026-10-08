import { render, screen } from '@testing-library/react'
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
