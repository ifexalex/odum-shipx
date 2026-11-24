import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { billingApi } from '../../../api/billing'
import { PaymentsTable } from './Breakdown'

describe('PaymentsTable receipts (FD-43)', () => {
  const PAYMENTS = [
    { id: 'pay-1', amount_ngn: '100000', payment_method: 'bank_transfer', payment_reference: 'TRF-1', confirmed_at: '2026-11-20' },
    { id: 'pay-2', amount_ngn: '5000', payment_method: 'cash', payment_reference: null, confirmed_at: '2026-11-21' },
  ]

  it('offers a receipt for every payment, named by amount and date', async () => {
    const receipt = vi.spyOn(billingApi, 'receiptPdf').mockResolvedValue(undefined)
    render(<PaymentsTable payments={PAYMENTS} />)
    const buttons = screen.getAllByRole('button', { name: /^Download receipt for/ })
    expect(buttons).toHaveLength(2)
    await userEvent.click(screen.getByRole('button', { name: 'Download receipt for ₦5,000 paid 21 Nov 2026' }))
    expect(receipt).toHaveBeenCalledWith('pay-2')
  })

  it('says why a receipt could not be prepared', async () => {
    vi.spyOn(billingApi, 'receiptPdf').mockRejectedValue(new TypeError('Failed to fetch'))
    render(<PaymentsTable payments={PAYMENTS.slice(0, 1)} />)
    await userEvent.click(screen.getByRole('button', { name: /^Download receipt for/ }))
    expect(await screen.findByText("Couldn't prepare the receipt")).toBeInTheDocument()
  })
})
