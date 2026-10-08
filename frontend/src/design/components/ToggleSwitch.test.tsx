import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ToggleSwitch } from './ToggleSwitch'

describe('ToggleSwitch', () => {
  it('reflects the checked state via aria-checked', () => {
    render(<ToggleSwitch checked onChange={vi.fn()} label="Email notifications" />)
    expect(screen.getByRole('switch', { name: 'Email notifications' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
  })

  it('calls onChange with the toggled value', async () => {
    const onChange = vi.fn()
    render(<ToggleSwitch checked={false} onChange={onChange} label="SMS" />)
    await userEvent.click(screen.getByRole('switch', { name: 'SMS' }))
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('does not call onChange when disabled', async () => {
    const onChange = vi.fn()
    render(<ToggleSwitch checked={false} onChange={onChange} disabled label="SMS" />)
    await userEvent.click(screen.getByRole('switch', { name: 'SMS' }))
    expect(onChange).not.toHaveBeenCalled()
  })
})
