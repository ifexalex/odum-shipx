import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Billing } from '../../api/billing'
import { InvoiceBreakdown } from './InvoiceBreakdown'

const BILLING = {
  total_cbm: '2.5',
  cbm_rate_usd: '45',
  subtotal_usd: '112.5',
  dollar_rate: '1550',
  subtotal_ngn: '174375',
  misc_fees: [{ description: 'Customs examination', amount_ngn: '15000' }],
  storage_fees_ngn: '0',
  carryover_ngn: '0',
  adjustments_ngn: '0',
  total_due_ngn: '189375',
  total_paid_ngn: '89375',
  outstanding_ngn: '100000',
  cbm_rate_mode: 'flat',
  exchange_rate_source: 'live',
} as unknown as Billing

const row = (label: string): HTMLElement => screen.getByText(label).parentElement!

describe('InvoiceBreakdown (FD-19)', () => {
  it('shows how the total was reached, one row per line, in one wording for staff and customers', () => {
    render(<InvoiceBreakdown billing={BILLING} />)
    expect(row('Shipping: CBM × rate')).toHaveTextContent('2.500 CBM × $45.00 = $112.50')
    expect(row('Exchange rate')).toHaveTextContent('₦1,550 / $')
    expect(row('Shipping cost')).toHaveTextContent('₦174,375')
    expect(row('Customs examination')).toHaveTextContent('₦15,000') // each charge by its own description
    expect(row('Total due')).toHaveTextContent('₦189,375')
    expect(row('Paid')).toHaveTextContent('−₦89,375')
    expect(row('Outstanding')).toHaveTextContent('₦100,000')
  })

  it('shows storage, carryovers and adjustments only when there are some', () => {
    render(<InvoiceBreakdown billing={BILLING} />)
    expect(screen.queryByText('Storage fees')).toBeNull()
    expect(screen.queryByText(/Carried over/)).toBeNull()
    expect(screen.queryByText('CBM dispute adjustment')).toBeNull()
  })

  it('says when the exchange rate was the last one known', () => {
    render(<InvoiceBreakdown billing={{ ...BILLING, exchange_rate_source: 'last_known' } as Billing} />)
    expect(screen.getByRole('note')).toHaveTextContent('Last known market rate')
  })
})
