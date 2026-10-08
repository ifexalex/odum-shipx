import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { KebabBtn } from './KebabBtn'

describe('KebabBtn', () => {
  it('fires onClick and exposes an accessible label', async () => {
    const onClick = vi.fn()
    render(<KebabBtn onClick={onClick} label="Container actions" />)
    await userEvent.click(screen.getByRole('button', { name: 'Container actions' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
