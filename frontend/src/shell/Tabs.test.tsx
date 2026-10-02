import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Tabs } from './Tabs'

const items = [
  { key: 'overview', label: 'Overview' },
  { key: 'history', label: 'History' },
]

describe('Tabs', () => {
  it('marks the active tab as selected', () => {
    render(<Tabs items={items} active="history" onChange={vi.fn()} />)
    expect(screen.getByRole('tab', { name: 'History' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'false')
  })

  it('calls onChange with the clicked tab key', async () => {
    const onChange = vi.fn()
    render(<Tabs items={items} active="overview" onChange={onChange} />)
    await userEvent.click(screen.getByRole('tab', { name: 'History' }))
    expect(onChange).toHaveBeenCalledWith('history')
  })
})
