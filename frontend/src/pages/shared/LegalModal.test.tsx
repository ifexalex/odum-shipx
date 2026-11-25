import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { LegalModal } from './LegalModal'

describe('LegalModal', () => {
  it('renders nothing when kind is null', () => {
    render(<LegalModal kind={null} onClose={vi.fn()} />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it.each([
    ['terms', 'Terms of Service', /warehouse pickup codes/i],
    ['privacy', 'Privacy Policy (NDPR)', /NDPR \/ GDPR/i],
    ['dpa', 'Data Processing Addendum', /row-level database/i],
  ] as const)('renders %s content and closes when Close is clicked', async (kind, title, bodyMatch) => {
    const onClose = vi.fn()
    render(<LegalModal kind={kind} onClose={onClose} />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(title)).toBeInTheDocument()
    expect(screen.getByText(bodyMatch)).toBeInTheDocument()

    await userEvent.click(screen.getAllByRole('button', { name: 'Close' }).at(-1)!)
    expect(onClose).toHaveBeenCalledOnce()
  })
})
