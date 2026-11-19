/**
 * Cancelling an invoice gives back the credit it used and reopens the balances it carried over (migration 070);
 * the dialog says so before staff confirm.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CancelBillingModal } from './ChargeModals'

vi.mock('../../../api/billing', () => ({ billingApi: { cancel: vi.fn() } }))
vi.mock('../../../hooks/useConfig', () => ({ useChargeTypes: () => ({ data: [] }) }))

function renderModal(props: { creditsNgn?: number; carryoverNgn?: string }): void {
  render(
    <CancelBillingModal
      billingId="b1"
      error={null}
      onCancel={vi.fn()}
      onSuccess={vi.fn()}
      {...props}
    />,
  )
}

describe('CancelBillingModal', () => {
  it('says the credit goes back and the carried-over balance is owed again', () => {
    renderModal({ creditsNgn: 20000, carryoverNgn: '8000.00' })
    expect(screen.getByText('What cancelling gives back')).toBeInTheDocument()
    expect(screen.getByText(/20,000.* of credit goes back to the customer/)).toBeInTheDocument()
    expect(
      screen.getByText(/8,000.* carried over from earlier invoices is owed again/),
    ).toBeInTheDocument()
  })

  it('says nothing when the invoice used no credit and carried nothing over', () => {
    renderModal({ creditsNgn: 0, carryoverNgn: '0' })
    expect(screen.queryByText('What cancelling gives back')).not.toBeInTheDocument()
  })
})
