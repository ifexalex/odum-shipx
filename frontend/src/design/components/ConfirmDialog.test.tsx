import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ConfirmDialog } from './ConfirmDialog'

describe('ConfirmDialog (FD-24)', () => {
  it('names the record, says what happens and how to undo it, and commits with a danger button', async () => {
    const onConfirm = vi.fn()
    render(
      <ConfirmDialog
        open
        title="Deactivate Li Wei?"
        confirmLabel="Deactivate user"
        undo="You can reactivate them later."
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      >
        They will be signed out.
      </ConfirmDialog>,
    )
    expect(screen.getByRole('dialog', { name: 'Deactivate Li Wei?' })).toBeInTheDocument()
    expect(screen.getByText('They will be signed out.')).toBeInTheDocument()
    expect(screen.getByText('You can reactivate them later.')).toBeInTheDocument()
    const commit = screen.getByRole('button', { name: 'Deactivate user' })
    expect(commit.className).toMatch(/danger/)
    await userEvent.click(commit)
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('an irreversible action says so and waits for the record’s reference to be typed', async () => {
    const onConfirm = vi.fn()
    render(
      <ConfirmDialog
        open
        title="Delete container MSCU1234567?"
        confirmLabel="Delete container"
        undo={false}
        typeToConfirm="MSCU1234567"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      >
        It will be removed.
      </ConfirmDialog>,
    )
    expect(screen.getByText('This cannot be undone.')).toBeInTheDocument()
    const commit = screen.getByRole('button', { name: 'Delete container' })
    expect(commit).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Type MSCU1234567 to confirm'), 'MSCU123')
    expect(commit).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Type MSCU1234567 to confirm'), '4567')
    expect(commit).toBeEnabled()
    await userEvent.click(commit)
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('"Keep it" cancels without acting', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(
      <ConfirmDialog open title="Remove?" confirmLabel="Remove" undo={false} onConfirm={onConfirm} onCancel={onCancel}>
        Gone.
      </ConfirmDialog>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Keep it' }))
    expect(onCancel).toHaveBeenCalledOnce()
    expect(onConfirm).not.toHaveBeenCalled()
  })
})
