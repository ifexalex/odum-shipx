import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { IconButton } from './IconButton'
import { Pressable } from './Pressable'

describe('IconButton (FD-07)', () => {
  it('is named by its label, which is also its tooltip', async () => {
    const onClick = vi.fn()
    render(<IconButton icon="x" label="Close" onClick={onClick} />)
    const button = screen.getByRole('button', { name: 'Close' })
    expect(button).toHaveAttribute('title', 'Close')
    expect(button).toHaveAttribute('type', 'button')
    await userEvent.click(button)
    expect(onClick).toHaveBeenCalledOnce()
  })
})

describe('Pressable (FD-07)', () => {
  it('is a button that never submits a form by accident and keeps the page class', () => {
    render(
      <Pressable className="tile" aria-pressed>
        Starter plan
      </Pressable>,
    )
    const tile = screen.getByRole('button', { name: 'Starter plan' })
    expect(tile).toHaveAttribute('type', 'button')
    expect(tile.className).toContain('tile')
  })
})
