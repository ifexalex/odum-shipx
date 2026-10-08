import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Chip } from './Chip'

describe('Chip', () => {
  it('calls onClick when the label is clicked', async () => {
    const onClick = vi.fn()
    render(<Chip onClick={onClick}>In transit</Chip>)
    await userEvent.click(screen.getByText('In transit'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('renders the count badge', () => {
    render(<Chip count={4}>In transit</Chip>)
    expect(screen.getByText('4')).toBeInTheDocument()
  })

  it('calls onDismiss without triggering onClick', async () => {
    const onClick = vi.fn()
    const onDismiss = vi.fn()
    render(
      <Chip dismissible onClick={onClick} onDismiss={onDismiss}>
        In transit
      </Chip>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(onDismiss).toHaveBeenCalledOnce()
    expect(onClick).not.toHaveBeenCalled()
  })
})
