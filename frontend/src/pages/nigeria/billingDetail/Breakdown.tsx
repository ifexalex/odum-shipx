import type { JSX } from 'react'
import { billingApi, type Billing } from '../../../api/billing'
import { paymentMethodLabel } from '../../../lib/paymentMethods'
import { Button, Mono, Table } from '../../../design/components'
import { formatDate, formatNgn } from '../../../lib/format'
import { Section } from '../../../shell/Section'
import { runDocument } from '../../../lib/documents'

/**
 * The payments recorded against the invoice; nothing when there are none. Staff and customer invoices share it.
 * Columns run date, reference, method, amount (FD-13), then each payment's receipt (FD-43): the date names the row in
 * the phone card.
 */
export function PaymentsTable({
  payments,
  title = 'Payments',
}: {
  payments: Billing['payments']
  title?: string
}): JSX.Element | null {
  if (payments.length === 0) return null
  return (
    <Section title={title} sub={`${payments.length} ${payments.length === 1 ? 'payment' : 'payments'} recorded`} flush>
      <Table
        columns={[
          { title: 'Confirmed', type: 'date' },
          { title: 'Reference', type: 'reference' },
          { title: 'Method' },
          { title: 'Amount (₦)', type: 'money' },
          { title: 'Receipt', type: 'action' },
        ]}
        rows={payments.map((p) => ({
          cells: [
            <span key="date">{formatDate(p.confirmed_at)}</span>,
            <Mono key="ref">{p.payment_reference ?? '—'}</Mono>,
            <span key="method">{paymentMethodLabel(p.payment_method)}</span>,
            <Mono key="amount">{formatNgn(p.amount_ngn)}</Mono>,
            // Proof of payment for each confirmed payment, for staff to hand over and customers to keep (FD-43).
            <Button
              key="receipt"
              variant="secondary"
              size="sm"
              icon="download"
              aria-label={`Download receipt for ${formatNgn(p.amount_ngn)} paid ${formatDate(p.confirmed_at)}`}
              onClick={() => void runDocument('the receipt', () => billingApi.receiptPdf(p.id))}
            >
              Receipt
            </Button>,
          ],
        }))}
      />

    </Section>
  )
}
