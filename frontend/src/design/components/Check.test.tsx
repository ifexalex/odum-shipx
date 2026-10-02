import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Check } from './Check'

describe('Check', () => {
  it('reports aria-checked=mixed when partial', () => {
    render(<Check partial />)
    expect(screen.getByRole('checkbox')).toHaveAttribute('aria-checked', 'mixed')
  })

  it('calls onChange with the toggled value on click', async () => {
    const onChange = vi.fn()
    render(<Check checked={false} onChange={onChange} />)
    await userEvent.click(screen.getByRole('checkbox'))
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('toggles via the keyboard', async () => {
    const onChange = vi.fn()
    render(<Check checked onChange={onChange} />)
    const checkbox = screen.getByRole('checkbox')
    checkbox.focus()
    await userEvent.keyboard('{Enter}')
    expect(onChange).toHaveBeenCalledWith(false)
  })

  it('does not call onChange when disabled', async () => {
    const onChange = vi.fn()
    render(<Check disabled onChange={onChange} />)
    await userEvent.click(screen.getByRole('checkbox'))
    expect(onChange).not.toHaveBeenCalled()
  })
})
