import { useQueryClient } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { configKeys } from '../../api/keys'
import { configApi, type DollarRateConfig } from '../../api/tenantManagement'
import { useDollarRate, useRateHistory } from '../../hooks/useConfig'
import { useSeedOnce } from '../../hooks/useSeedOnce'
import { Banner, Button, Card, Kvp, Mono, Table, UserCell } from '../../design/components'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import styles from './admin.module.css'
import { formatDate, formatNgn, formatAmount } from '../../lib/format'

// B7 — rate trend line chart (prototype 4.2/4.3). Dependency-free SVG.
// Takes ascending-by-date points and draws a filled area + line + endpoint dot,
// with min/max/latest gridlines. Hidden by the caller when < 2 points (no trend).
function RateTrendChart({ points, prefix }: { points: { date: string; value: number }[]; prefix: string }): JSX.Element {
  const W = 640
  const H = 200
  const padX = 8
  const padTop = 16
  const padBottom = 28

  const values = points.map((p) => p.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1 // flat series → avoid /0; line sits mid-height

  const x = (i: number): number => padX + (i * (W - padX * 2)) / Math.max(1, points.length - 1)
  const y = (v: number): number => padTop + (1 - (v - min) / span) * (H - padTop - padBottom)

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join(' ')
  const areaPath = `${linePath} L ${x(points.length - 1).toFixed(1)} ${H - padBottom} L ${x(0).toFixed(1)} ${H - padBottom} Z`

  const last = points[points.length - 1]!
  const first = points[0]!
  const net = last.value - first.value

  return (
    <div style={{ padding: '4px 20px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 'var(--text-2xl)' }}>{prefix}{formatAmount(last.value)}</span>
        <span style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: net >= 0 ? 'var(--color-success)' : 'var(--color-error)' }}>
          {net >= 0 ? '+' : ''}{prefix}{formatAmount(net)}
        </span>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)' }}>over {points.length} changes</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{ overflow: 'visible' }} role="img" aria-label="Rate trend">
        <defs>
          <linearGradient id="rateTrendFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--color-primary)" stopOpacity="0.18" />
            <stop offset="1" stopColor="var(--color-primary)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* min / max reference lines */}
        <line x1={padX} x2={W - padX} y1={y(max)} y2={y(max)} stroke="var(--color-line-soft)" strokeDasharray="3 4" />
        <line x1={padX} x2={W - padX} y1={y(min)} y2={y(min)} stroke="var(--color-line-soft)" strokeDasharray="3 4" />
        <text x={padX} y={y(max) - 4} fontSize="10" fill="var(--color-ink-4)" fontFamily="var(--font-mono)">{prefix}{formatAmount(max)}</text>
        <text x={padX} y={y(min) + 12} fontSize="10" fill="var(--color-ink-4)" fontFamily="var(--font-mono)">{prefix}{formatAmount(min)}</text>
        <path d={areaPath} fill="url(#rateTrendFill)" />
        <path d={linePath} fill="none" stroke="var(--color-primary)" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={x(points.length - 1)} cy={y(last.value)} r="4.5" fill="var(--color-primary)" stroke="#fff" strokeWidth="2" />
        {/* first + last date labels */}
        <text x={padX} y={H - 8} fontSize="10" fill="var(--color-ink-4)" fontFamily="var(--font-mono)">{formatDate(first.date)}</text>
        <text x={W - padX} y={H - 8} fontSize="10" fill="var(--color-ink-4)" fontFamily="var(--font-mono)" textAnchor="end">{formatDate(last.date)}</text>
      </svg>
    </div>
  )
}

// F-C7 — Rate history (prototype 4.2): every change, who made it, and the delta.
// Shared by the Dollar and CBM rate pages. Also renders the B7 trend chart from
// the same fetched history (no extra request).
export function RateHistoryTable({ rateType, valueKey, prefix }: { rateType: 'dollar_rate' | 'cbm_rate'; valueKey: string; prefix: string }): JSX.Element {
  // Non-fatal: on failure the history table degrades to empty.
  const history = useRateHistory(rateType)
  const rows = history.data?.data ?? []
  const loading = history.isLoading

  const val = (v: Record<string, unknown> | null): number | null => {
    const n = v ? Number(v[valueKey]) : NaN
    return Number.isFinite(n) ? n : null
  }

  // Ascending-by-date points for the chart (rows come newest-first).
  const chartPoints = rows
    .map((r) => ({ date: r.effective_from, value: val(r.rate_value) }))
    .filter((p): p is { date: string; value: number } => p.value != null)
    .reverse()

  return (
    <Card padding={0} style={{ marginTop: 20 }}>
      <div style={{ padding: '18px 20px 4px' }}>
        <SectionHead title="Rate history" sub="Every change, who made it, and the delta (append-only, migration 025)" />
      </div>
      {chartPoints.length >= 2 && <RateTrendChart points={chartPoints} prefix={prefix} />}
      <Table
        columns={[
          { title: 'Rate' },
          { title: 'Change', align: 'right' },
          { title: 'Changed by' },
          { title: 'Effective from' },
        ]}
        rows={rows.map((r, i) => {
          const current = val(r.rate_value)
          const prev = val(r.previous_value)
          const delta = current != null && prev != null ? current - prev : null
          return {
            cells: [
              <span key="rate" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <Mono color={i === 0 ? 'var(--color-primary)' : undefined}>{prefix}{formatAmount(current)}</Mono>
                {i === 0 && <span style={{ fontSize: 'var(--text-xs)', fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-primary-deep)', background: 'var(--color-primary-soft)', borderRadius: 999, padding: '2px 8px' }}>Current</span>}
              </span>,
              delta == null ? (
                <span key="delta" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)' }}>—</span>
              ) : (
                <span key="delta" style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: delta >= 0 ? 'var(--color-success)' : 'var(--color-error)' }}>
                  {delta >= 0 ? '+' : ''}{prefix}{formatAmount(delta)}
                </span>
              ),
              <UserCell key="by" name={r.changed_by ?? 'system'} email="" />,
              <Mono key="from" color="var(--color-ink-3)">{r.effective_from.slice(0, 16).replace('T', ' ')}</Mono>,
            ],
          }
        })}
        emptyState={<span style={{ color: 'var(--color-ink-3)', fontSize: 'var(--text-sm)' }}>{loading ? 'Loading history…' : 'No rate changes recorded yet.'}</span>}
      />
    </Card>
  )
}

// Duplicated in a few other shell components (ActivityFeed.tsx,
// StaffNotificationPanel.tsx, CustomerNotificationPanel.tsx,
// PlatformDashboard.tsx) rather than centralized — matching that existing
// (imperfect) convention for this one small helper.
function relativeTime(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  if (days < 30) return `${days}d ago`
  return formatDate(iso)
}

function formatMarkup(markupType: 'percentage' | 'flat', markupValue: number): string {
  return markupType === 'flat' ? `${formatNgn(markupValue)} per $1` : `${markupValue}%`
}

type MarkupType = 'percentage' | 'flat'

/** " — updated 5 min ago", or what the base rate is when it was not fetched live (audit BE-11). */
function baseRateFreshness(rate: DollarRateConfig): string {
  if (rate.rate_source === 'hardcoded' || !rate.fetched_at) return ' — built-in default, never fetched'
  const when = relativeTime(rate.fetched_at)
  return rate.rate_source === 'last_known' ? ` — last known rate, fetched ${when}` : ` — updated ${when}`
}

export function DollarRateConfig(): JSX.Element {
  const qc = useQueryClient()
  const rate = useDollarRate({ freshOnOpen: true })
  const current: DollarRateConfig | null = rate.isFetchedAfterMount ? (rate.data ?? null) : null
  const loading = !rate.isFetchedAfterMount
  const [markupType, setMarkupType] = useState<MarkupType>('percentage')
  const [markupValue, setMarkupValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  useSeedOnce(rate, (data) => {
    setMarkupType(data.markup_type)
    setMarkupValue(String(data.markup_value))
  })

  const loadError = rate.error ? (rate.error instanceof ApiError ? rate.error.message : 'Could not load rate.') : null
  const error = saveError ?? loadError

  async function handleSave(): Promise<void> {
    setSaving(true)
    setSaveError(null)
    setSuccess(false)
    try {
      const updated = await configApi.updateDollarRate({ markup_type: markupType, markup_value: Number(markupValue) })
      // Show the saved value at once; the write also invalidates every config query (api/cacheInvalidation.ts).
      qc.setQueryData(configKeys.dollar(), updated)
      setSuccess(true)
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Could not update markup.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <PageHeader title="Dollar Rate" subtitle="USD → NGN exchange rate used for all billing calculations." />

      {error && <div className={styles.banner}><Banner variant="error">{error}</Banner></div>}
      {success && <div className={styles.banner}><Banner variant="success">Markup updated successfully.</Banner></div>}

      {!loading && current && (
        <>
          <SectionHead title="Current rate" />
          <Card padding={20}>
            <Kvp
              label="Base rate (Bybit P2P)"
              value={<Mono>{formatNgn(current.base_rate)} per $1{baseRateFreshness(current)}</Mono>}
            />
            {current.rate_source !== 'live' && (
              <div className={styles.banner}>
                <Banner variant="warning">
                  {current.rate_source === 'hardcoded'
                    ? 'No market rate has been fetched yet, so this is a built-in default. Invoices are not issued until a market rate is available.'
                    : 'The live market rate cannot be fetched right now, so invoices use the last known rate shown here.'}
                </Banner>
              </div>
            )}
            <Kvp label="Your markup" value={<Mono>{formatMarkup(current.markup_type, current.markup_value)}</Mono>} />
            <Kvp
              label="Effective rate charged to customers"
              value={<Mono color="var(--color-primary)">{formatNgn(current.rate)} per $1 USD</Mono>}
              divider={false}
            />
          </Card>

          <Banner variant="warning" title="Heads up">
            The base rate tracks Bybit's live P2P market and refreshes automatically — you only control the markup on top of it.
            Existing billing records keep the rate they were created with; this change affects <strong>new</strong> records only.
          </Banner>

          <SectionHead title="Update markup" />
          <div className={styles.formCard}>
            <div>
              <label style={{ fontWeight: 600, fontSize: 'var(--text-md)', display: 'block', marginBottom: 6 }}>
                Markup type
              </label>
              <div style={{ display: 'flex', gap: 8 }}>
                <Button
                  variant={markupType === 'percentage' ? 'primary' : 'ghost'}
                  onClick={() => setMarkupType('percentage')}
                >
                  Percentage
                </Button>
                <Button
                  variant={markupType === 'flat' ? 'primary' : 'ghost'}
                  onClick={() => setMarkupType('flat')}
                >
                  Flat ₦ per $1
                </Button>
              </div>
            </div>
            <div>
              <label style={{ fontWeight: 600, fontSize: 'var(--text-md)', display: 'block', marginBottom: 6 }}>
                {markupType === 'percentage' ? 'Markup (%)' : 'Markup (₦ per $1)'} <span style={{ color: 'var(--color-error)' }}>*</span>
              </label>
              <input
                type="number"
                value={markupValue}
                onChange={(e) => setMarkupValue(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--color-border)', background: 'var(--color-surface)', fontSize: 'var(--text-lg)' }}
                placeholder={markupType === 'percentage' ? 'e.g. 2' : 'e.g. 15'}
                min="0"
                step={markupType === 'percentage' ? '0.1' : '1'}
              />
            </div>
            <div className={styles.formActions}>
              <Button
                variant="primary"
                loading={saving}
                disabled={markupValue === '' || Number(markupValue) < 0}
                onClick={() => void handleSave()}
              >
                Update markup
              </Button>
            </div>
          </div>

          <RateHistoryTable rateType="dollar_rate" valueKey="rate" prefix="₦" />
        </>
      )}
    </div>
  )
}
