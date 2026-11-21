/**
 * How an invoice's total was reached (FD-19), the one breakdown staff and customers both read: shipping (CBM and
 * rate, per package type where the tenant prices that way), the exchange rate, every charge by its own description,
 * storage, carryovers and adjustments, then total, paid and outstanding. The staff and customer invoices each had their
 * own, with different words and styles for the same rows.
 *
 * It is the body of a `Section`; the page gives it its title and any action (the customer's "Download invoice").
 */
import type { JSX } from 'react'
import type { Billing } from '../../api/billing'
import { Mono } from '../../design/components'
import { formatCbm, formatDateTime, formatNgn, formatUsd } from '../../lib/format'
import styles from './InvoiceBreakdown.module.css'

function Row({ label, value, tone, total = false, indent = false }: {
  label: string
  value: string
  tone?: 'paid' | 'owed' | 'credit'
  total?: boolean
  indent?: boolean
}): JSX.Element {
  return (
    <div className={[styles.row, total ? styles.total : '', tone ? styles[tone] : ''].join(' ')}>
      <span className={indent ? styles.indent : undefined}>{label}</span>
      <Mono>{value}</Mono>
    </div>
  )
}

export function InvoiceBreakdown({ billing }: { billing: Billing }): JSX.Element {
  const perPackage = billing.cbm_rate_mode === 'per_package_type' && billing.cbm_breakdown
  const rateMoney = billing.cbm_rate_currency === 'NGN' ? formatNgn : formatUsd
  const outstanding = Number(billing.outstanding_ngn)
  return (
    <div className={styles.breakdown}>
      <Row
        label="Shipping: CBM × rate"
        value={`${formatCbm(billing.total_cbm)} CBM × ${formatUsd(billing.cbm_rate_usd)} = ${formatUsd(billing.subtotal_usd)}`}
      />
      {/* Priced per package type: the rates actually charged, not only the blended one above. */}
      {perPackage &&
        (['carton', 'bag', 'bale'] as const).map((bucket) => {
          const item = billing.cbm_breakdown![bucket]
          if (Number(item.cbm) <= 0) return null
          return (
            <Row
              key={bucket}
              indent
              label={`${bucket[0]!.toUpperCase()}${bucket.slice(1)}s`}
              value={`${formatCbm(item.cbm)} CBM × ${rateMoney(item.rate)} = ${rateMoney(item.subtotal)}`}
            />
          )
        })}
      <Row label="Exchange rate" value={`${formatNgn(billing.dollar_rate)} / $`} />
      {billing.exchange_rate_source === 'last_known' && (
        // The market feed was down when this invoice was issued (audit BE-11).
        <div className={styles.rateNotice} role="note">
          Last known market rate
          {billing.exchange_rate_fetched_at ? `, fetched ${formatDateTime(billing.exchange_rate_fetched_at)}` : ''}. The
          live rate could not be fetched when this invoice was issued.
        </div>
      )}
      <Row label="Shipping cost" value={formatNgn(billing.subtotal_ngn)} />
      {/* Every charge by its own description, never a lump "Misc fees". */}
      {billing.misc_fees.map((fee, i) => (
        <Row key={i} label={fee.description} value={formatNgn(fee.amount_ngn)} />
      ))}
      {Number(billing.storage_fees_ngn) > 0 && <Row label="Storage fees" value={formatNgn(billing.storage_fees_ngn)} />}
      {Number(billing.carryover_ngn) > 0 && (
        <Row label="Carried over from an earlier shipment" value={`+${formatNgn(billing.carryover_ngn)}`} />
      )}
      {Number(billing.adjustments_ngn) !== 0 && (
        <Row
          label="CBM dispute adjustment"
          tone="credit"
          value={`−${formatNgn(Math.abs(Number(billing.adjustments_ngn)))}`}
        />
      )}
      <Row label="Total due" total value={formatNgn(billing.total_due_ngn)} />
      <Row label="Paid" tone="paid" value={`−${formatNgn(billing.total_paid_ngn)}`} />
      <Row label="Outstanding" total tone={outstanding > 0 ? 'owed' : undefined} value={formatNgn(billing.outstanding_ngn)} />
    </div>
  )
}
