import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ViewLink } from './ViewLink'

describe('ViewLink', () => {
  it('fires onClick', async () => {
    const onClick = vi.fn()
    render(<ViewLink onClick={onClick} />)
    await userEvent.click(screen.getByRole('button', { name: 'View' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
