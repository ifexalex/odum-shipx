import type { JSX } from 'react'
import type { Billing } from '../../../api/billing'
import { Card, Mono, Table } from '../../../design/components'
import { formatCbm, formatDate, formatDateTime, formatNgn, formatUsd } from '../../../lib/format'
import { SectionHead } from '../../../shell/SectionHead'
import styles from '../BillingDetail.module.css'

/** How the total was reached: CBM and rate, exchange rate, charges, carryovers, adjustments, paid and outstanding. */
export function BillingBreakdown({ billing }: { billing: Billing }): JSX.Element {
  return (
    <div className={styles.section}>
      <SectionHead title="Billing breakdown" />
      <Card padding="default">
        <div className={styles.breakdown}>
          <div className={styles.breakdownRow}>
            <span>CBM × rate</span>
            <span>
              {formatCbm(billing.total_cbm)} CBM × {formatUsd(billing.cbm_rate_usd)} ={' '}
              <Mono>{formatUsd(billing.subtotal_usd)}</Mono>
            </span>
          </div>
          {/* Per-package-type detail — only worth showing when the tenant
              actually priced this invoice by package type; a flat-rate
              invoice's single line above already says everything. */}
          {billing.cbm_rate_mode === 'per_package_type' && billing.cbm_breakdown && (
            <>
              {(['carton', 'bag', 'bale'] as const).map((bucket) => {
                const item = billing.cbm_breakdown![bucket]
                if (Number(item.cbm) <= 0) return null
                const money = billing.cbm_rate_currency === 'NGN' ? formatNgn : formatUsd
                return (
                  <div className={styles.breakdownRow} key={bucket}>
                    <span style={{ paddingLeft: 'var(--space-4)', textTransform: 'capitalize' }}>{bucket}s</span>
                    <span>
                      {formatCbm(item.cbm)} CBM × {money(item.rate)} ={' '}
                      <Mono>{money(item.subtotal)}</Mono>
                    </span>
                  </div>
                )
              })}
            </>
          )}
          <div className={styles.breakdownRow}>
            <span>Exchange rate</span>
            <Mono>{formatNgn(billing.dollar_rate)} / $</Mono>
          </div>
          {billing.exchange_rate_source === 'last_known' && (
            // The market feed was down when this invoice was issued (audit BE-11).
            <div className={styles.rateNotice} role="note">
              Last known market rate
              {billing.exchange_rate_fetched_at
                ? `, fetched ${formatDateTime(billing.exchange_rate_fetched_at)}`
                : ''}
              . The live rate could not be fetched when this invoice was issued.
            </div>
          )}
          <div className={styles.breakdownRow}>
            <span>CBM subtotal</span>
            <Mono>{formatNgn(billing.subtotal_ngn)}</Mono>
          </div>
          {/* Itemized by real description inline — not a lump "Misc fees"
              figure a staff member has to scroll down to decode against
              the separate "Miscellaneous charges" table below. */}
          {billing.misc_fees.map((fee, i) => (
            <div className={styles.breakdownRow} key={i}>
              <span>{fee.description}</span>
              <Mono>{formatNgn(fee.amount_ngn)}</Mono>
            </div>
          ))}
          {Number(billing.storage_fees_ngn) > 0 && (
            <div className={styles.breakdownRow}>
              <span>Storage fees</span>
              <Mono>{formatNgn(billing.storage_fees_ngn)}</Mono>
            </div>
          )}
          {Number(billing.carryover_ngn) > 0 && (
            <div className={styles.breakdownRow}>
              <span>Carryover applied</span>
              <Mono>+{formatNgn(billing.carryover_ngn)}</Mono>
            </div>
          )}
          {Number(billing.adjustments_ngn) !== 0 && (
            <div className={styles.breakdownRow}>
              <span style={{ color: 'var(--color-success)', fontWeight: 600 }}>
                CBM dispute adjustment
              </span>
              <Mono color="var(--color-success)">
                −{formatNgn(Math.abs(Number(billing.adjustments_ngn)))}
              </Mono>
            </div>
          )}
          <div className={`${styles.breakdownRow} ${styles.breakdownTotal}`}>
            <span>Total due</span>
            <Mono>{formatNgn(billing.total_due_ngn)}</Mono>
          </div>
          <div className={styles.breakdownRow}>
            <span style={{ color: 'var(--color-success)' }}>Total paid</span>
            <Mono color="var(--color-success)">−{formatNgn(billing.total_paid_ngn)}</Mono>
          </div>
          <div className={`${styles.breakdownRow} ${styles.breakdownTotal}`}>
            <span
              style={{
                color: Number(billing.outstanding_ngn) > 0 ? 'var(--color-error)' : undefined,
              }}
            >
              Outstanding
            </span>
            <Mono color={Number(billing.outstanding_ngn) > 0 ? 'var(--color-error)' : undefined}>
              {formatNgn(billing.outstanding_ngn)}
            </Mono>
          </div>
        </div>
      </Card>
    </div>
  )
}

/** The payments recorded against the invoice; nothing when there are none. */
export function PaymentsTable({ payments }: { payments: Billing['payments'] }): JSX.Element | null {
  if (payments.length === 0) return null
  return (
    <div className={styles.section}>
      <SectionHead title="Payments" sub={`${payments.length} payment(s) recorded`} />
      <Card padding="none">
        <Table
          columns={[
            { title: 'Amount (₦)', align: 'right' },
            { title: 'Method' },
            { title: 'Reference' },
            { title: 'Confirmed' },
          ]}
          rows={payments.map((p) => ({
            cells: [
              <Mono key="amount">{formatNgn(p.amount_ngn)}</Mono>,
              <span key="method">{p.payment_method ?? '—'}</span>,
              <Mono key="ref">{p.payment_reference ?? '—'}</Mono>,
              <span key="date">{formatDate(p.confirmed_at)}</span>,
            ],
          }))}
        />
      </Card>
    </div>
  )
}
