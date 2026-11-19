import { type JSX } from 'react'
import { type StorageFeeEntry } from '../../../api/billing'
import { Action, Banner, Card, Mono, Table } from '../../../design/components'
import { formatDate, formatNgn } from '../../../lib/format'
import { fmtDate } from './status'

// ---------------------------------------------------------------------------
// StorageFeeBanner — 3 states matching gapfix-screens-b.jsx B3
// ---------------------------------------------------------------------------

const GRACE_PERIOD_DAYS = 14
const ENDING_SOON_THRESHOLD = 3 // days left before "ending soon" state kicks in

export interface StorageFeeBannerProps {
  billing: { storage_fees_ngn: string | number; release_note_issued_at?: string | null }
  storageFees: StorageFeeEntry[]
  canWaive: boolean
  onWaive: () => void
  waiving: boolean
}

export function StorageFeeBanner({
  billing,
  storageFees,
  canWaive,
  onWaive,
  waiving,
}: StorageFeeBannerProps): JSX.Element | null {
  const storageFeesNgn = Number(billing.storage_fees_ngn)
  const releaseNoteIssuedAt = billing.release_note_issued_at

  // No release note yet — no grace period to track
  if (!releaseNoteIssuedAt && storageFeesNgn <= 0) return null

  const now = new Date()
  const issued = releaseNoteIssuedAt ? new Date(releaseNoteIssuedAt) : null
  const graceEnds = issued
    ? new Date(issued.getTime() + GRACE_PERIOD_DAYS * 24 * 60 * 60 * 1000)
    : null
  const daysLeft = graceEnds
    ? Math.ceil((graceEnds.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
    : null
  const daysPastGrace = daysLeft !== null && daysLeft < 0 ? Math.abs(daysLeft) : 0

  // Derive per-carton daily rate from first fee row (most accurate source)
  const dailyRatePerCarton = storageFees[0] ? Number(storageFees[0].daily_rate_ngn) : 500
  const cartonCount = storageFees[0] ? storageFees[0].carton_count : null
  const totalAccrued = storageFees.reduce((s, r) => s + Number(r.fee_amount_ngn), 0)

  const waiveBtn = canWaive ? (
    <Action variant="danger-outline" size="sm" loading={waiving} onClick={onWaive}>
      Waive fees
    </Action>
  ) : undefined

  // ① Grace — accruing but no fees yet logged (within grace period)
  if (daysLeft !== null && daysLeft > ENDING_SOON_THRESHOLD && storageFeesNgn <= 0) {
    return (
      <Banner variant="info" icon="clock" title={`Free storage until ${fmtDate(graceEnds!)}`}>
        Pickup is free for <strong>{daysLeft} more days</strong>. After the grace period, storage
        accrues at {formatNgn(dailyRatePerCarton)}/day per carton
        {cartonCount ? ` (${cartonCount} cartons)` : ''}.
      </Banner>
    )
  }

  // ② Grace — ending soon (≤3 days left)
  if (daysLeft !== null && daysLeft > 0 && daysLeft <= ENDING_SOON_THRESHOLD) {
    const dailyTotal = cartonCount ? dailyRatePerCarton * cartonCount : dailyRatePerCarton
    return (
      <Banner
        variant="warning"
        icon="warn"
        title={
          daysLeft === 1 ? 'Storage fees begin tomorrow' : `Storage fees begin in ${daysLeft} days`
        }
        action={waiveBtn}
      >
        Grace period ends <strong>{fmtDate(graceEnds!)}</strong>. From day {GRACE_PERIOD_DAYS + 1},
        {formatNgn(dailyTotal)}/day will accrue
        {cartonCount ? ` (${cartonCount} cartons × ${formatNgn(dailyRatePerCarton)})` : ''}. A
        reminder was sent to the customer today.
      </Banner>
    )
  }

  // ③ Accruing (past grace period, fees accumulating)
  if (storageFeesNgn > 0 || daysPastGrace > 0) {
    const dailyTotal = cartonCount ? dailyRatePerCarton * cartonCount : storageFeesNgn
    return (
      <Banner variant="error" icon="alert" title="Storage fees are accruing" action={waiveBtn}>
        <strong>{formatNgn(totalAccrued || storageFeesNgn)}</strong> accrued so far
        {daysPastGrace > 0 ? ` (${daysPastGrace} days × ${formatNgn(dailyTotal)})` : ''}. This is
        added to the outstanding balance daily until pickup.
      </Banner>
    )
  }

  return null
}

// ---------------------------------------------------------------------------
// StorageFeeLog — accrual log table
// ---------------------------------------------------------------------------

export function StorageFeeLog({ fees }: { fees: StorageFeeEntry[] }): JSX.Element | null {
  if (fees.length === 0) return null
  return (
    <Card padding={0}>
      <Table
        dense
        columns={[
          { title: 'Day' },
          { title: 'Date' },
          { title: 'Cartons', align: 'right' },
          { title: 'Rate', align: 'right' },
          { title: 'Fee', align: 'right' },
        ]}
        rows={fees.map((f) => ({
          cells: [
            <span key="day" style={{ fontSize: 12, color: 'var(--color-ink-3)' }}>
              Day {f.day_number}
            </span>,
            <Mono key="date" color="var(--color-ink-2)">
              {formatDate(f.accrual_date, 'short')}
            </Mono>,
            <Mono key="cartons">{f.carton_count}</Mono>,
            <Mono key="rate">{formatNgn(f.daily_rate_ngn)}</Mono>,
            <Mono key="fee" color="var(--color-error)">
              {formatNgn(f.fee_amount_ngn)}
            </Mono>,
          ],
        }))}
      />
    </Card>
  )
}
