import { useQuery } from '@tanstack/react-query'
import { useMemo, type CSSProperties, type JSX } from 'react'
import { billingApi } from '../../api/billing'
import { billingKeys } from '../../api/keys'
import { STALE_5_MIN } from '../../lib/queryClient'
import { Button, Card, DateRangeFilter, Icon, Mono, StatCard, Table } from '../../design/components'
import { useDateRangeFilter } from '../../hooks/useDateRangeFilter'
import { SectionHead } from '../../shell/SectionHead'
import { useTopBarSlot } from '../../shell/TopBarContext'
import styles from './TenantReports.module.css'
import { formatNgn } from '../../lib/format'

const dateInputStyle: CSSProperties = {
  height: 36,
  boxSizing: 'border-box',
  padding: '0 8px',
  background: 'var(--color-page)',
  border: '1px solid var(--color-line)',
  borderRadius: 'var(--radius-sm)',
  fontFamily: 'var(--font-body)',
  fontSize: 'var(--text-sm)',
  color: 'var(--color-ink)',
}

function fmtNgn(n: number): string {
  if (n >= 1_000_000) return `₦${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000)     return `₦${(n / 1_000).toFixed(0)}k`
  return formatNgn(n)
}

// ─── Pure-CSS Donut chart ─────────────────────────────────────────────────────
interface DonutSegment { label: string; value: number; color: string; amount: number }

function DonutChart({ segments, total }: { segments: DonutSegment[]; total: number }): JSX.Element {
  // Cumulative offsets computed without mutating a variable across the map:
  // reassigning a closed-over `let` during render is not safe when a render can
  // be replayed or discarded. Segment counts are tiny, so the repeated sum is
  // cheaper than the state it would otherwise need.
  const pcts = segments.map((s) => (total > 0 ? (s.value / total) * 100 : 0))
  const sumTo = (n: number): number => pcts.slice(0, n).reduce((sum, p) => sum + p, 0)
  const parts = segments.map((s, i) => `${s.color} ${sumTo(i).toFixed(1)}% ${sumTo(i + 1).toFixed(1)}%`)

  return (
    <div className={styles.donutWrap}>
      <div className={styles.donutOuter} style={{ background: `conic-gradient(${parts.join(', ')})` }}>
        <div className={styles.donutInner}>
          <div className={styles.donutLabel}>Total</div>
          <div className={styles.donutTotal}>{fmtNgn(total)}</div>
        </div>
      </div>
      <div className={styles.donutLegend}>
        {segments.map((s) => (
          <div key={s.label} className={styles.donutLegendRow}>
            <span className={styles.donutDot} style={{ background: s.color }} />
            <span className={styles.donutLegendLabel}>{s.label}</span>
            <Mono color="var(--color-ink)">{fmtNgn(s.amount)}</Mono>
            <span className={styles.donutPct}>{total > 0 ? ((s.value / total) * 100).toFixed(0) : 0}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Top customers horizontal bars ───────────────────────────────────────────
function TopCustomersChart({ data }: { data: Array<{ name: string; amount: number }> }): JSX.Element {
  const max = data[0]?.amount ?? 1
  return (
    <div>
      {data.slice(0, 7).map((c, i) => (
        <div key={c.name} className={styles.topCustRow}>
          <span className={styles.topCustName}>{c.name}</span>
          <div className={styles.topCustBar}>
            <div
              className={styles.topCustFill}
              style={{
                width: `${(c.amount / max) * 100}%`,
                background: i === 0 ? 'var(--color-accent)' : 'var(--color-primary)',
              }}
            />
          </div>
          <Mono color="var(--color-ink)">{fmtNgn(c.amount)}</Mono>
        </div>
      ))}
    </div>
  )
}

// ─── Container pipeline stacked bar chart (8 weeks) ──────────────────────────
// Weekly per-status-group counts are aggregated server-side (GET /v1/billing/report
// → container_pipeline) so this never needs every container row client-side.
type PipelineWeek = { week: string; cn: number; transit: number; arrived: number; released: number }

const PIPELINE_GROUPS = [
  { key: 'cn',       label: 'China',      color: 'var(--color-info)' },
  { key: 'transit',  label: 'In transit', color: 'var(--color-accent)' },
  { key: 'arrived',  label: 'Arrived',    color: 'var(--color-warning)' },
  { key: 'released', label: 'Released',   color: 'var(--color-success)' },
] as const

function ContainerPipelineChart({ data }: { data: PipelineWeek[] }): JSX.Element {
  const maxTotal = Math.max(
    ...data.map((d) => d.cn + d.transit + d.arrived + d.released),
    1,
  )

  return (
    <div className={styles.pipelineWrap}>
      <div className={styles.pipelineBars}>
        {data.map((wk) => {
          const total = wk.cn + wk.transit + wk.arrived + wk.released
          return (
            <div key={wk.week} className={styles.pipelineCol}>
              <div className={styles.pipelineBar} style={{ height: 100 }}>
                {PIPELINE_GROUPS.map((grp) => {
                  const v = wk[grp.key]
                  return v > 0 ? (
                    <div
                      key={grp.key}
                      title={`${grp.label}: ${v}`}
                      style={{
                        height: `${(v / maxTotal) * 100}%`,
                        background: grp.color,
                        opacity: 0.85,
                      }}
                    />
                  ) : null
                })}
              </div>
              <span className={styles.pipelineWeekLabel}>{wk.week}</span>
              {total > 0 && <span className={styles.pipelineTotal}>{total}</span>}
            </div>
          )
        })}
      </div>
      <div className={styles.pipelineLegend}>
        {PIPELINE_GROUPS.map((g) => (
          <div key={g.key} className={styles.pipelineLegendItem}>
            <span className={styles.pipelineDot} style={{ background: g.color }} />
            <span>{g.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Claims summary card ──────────────────────────────────────────────────────
type ClaimIconName = 'warn' | 'package' | 'coin'

function ClaimsSummaryCard({ iconName, color, title, stats }: {
  iconName: ClaimIconName; color: string; title: string
  stats: Array<[string, string]>
}): JSX.Element {
  return (
    <Card padding={20}>
      <div className={styles.claimCardHeader}>
        <div className={styles.claimIcon} style={{ background: color + '18', color }}>
          <Icon name={iconName} size={18} color={color} />
        </div>
        <span className={styles.claimCardTitle}>{title}</span>
      </div>
      <div className={styles.claimStats}>
        {stats.filter(([l]) => l).map(([label, val]) => (
          <div key={label}>
            <div className={styles.claimStatVal}>{val}</div>
            <div className={styles.claimStatLabel}>{label}</div>
          </div>
        ))}
      </div>
    </Card>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export function TenantReports(): JSX.Element {
  // "Billed/created/filed within" — null/'' means no date filter (the whole
  // report is "all time"), same opt-in-only rationale as every other list
  // page's date filter. Scopes billing, containers, and claims together;
  // `customerCount` stays an as-of-now total (registered customers), not a
  // per-period metric, so it's intentionally left unscoped.
  const reportRange = useDateRangeFilter()

  useTopBarSlot({
    actions: (
      <>
        <DateRangeFilter value={reportRange.daysBack} onChange={reportRange.handlePreset} />
        <input
          type="date"
          aria-label="From"
          style={dateInputStyle}
          value={reportRange.dateFrom}
          max={reportRange.dateTo || undefined}
          onChange={(e) => reportRange.handleCustomFrom(e.target.value)}
        />
        <input
          type="date"
          aria-label="To"
          style={dateInputStyle}
          value={reportRange.dateTo}
          min={reportRange.dateFrom || undefined}
          onChange={(e) => reportRange.handleCustomTo(e.target.value)}
        />
        <Button variant="secondary" icon="download">Export</Button>
      </>
    ),
  })

  const { createdAfter, createdBefore } = reportRange
  // One SQL-computed report endpoint — correct at scale (previously summed a
  // capped `limit: 500` sample of billing/containers/claims per period).
  const { data: report, isLoading: loading } = useQuery({
    queryKey: billingKeys.report({ createdAfter, createdBefore }),
    queryFn: () => billingApi.report({ created_after: createdAfter, created_before: createdBefore }),
    staleTime: STALE_5_MIN,
  })

  // ── Derived stats (from the report response) ──
  const totalRevenue = Number(report?.overview.total_revenue_ngn ?? 0)
  const totalCbm = Number(report?.overview.total_cbm ?? 0)
  const containersProcessed = report?.overview.containers_processed ?? 0
  const customerCount = report?.overview.active_customers ?? 0
  const claimCounts = report?.claims ?? { open: 0, resolved: 0, total: 0 }

  const avgCbmPerContainer = containersProcessed > 0
    ? (totalCbm / containersProcessed).toFixed(1)
    : '—'

  // Revenue donut segments
  const DONUT_STATUS: Array<{ key: keyof NonNullable<typeof report>['overview']; label: string; color: string }> = [
    { key: 'revenue_paid', label: 'Paid', color: 'var(--color-success)' },
    { key: 'revenue_partially_paid', label: 'Partially paid', color: 'var(--color-warning)' },
    { key: 'revenue_unpaid', label: 'Unpaid', color: 'var(--color-error)' },
    { key: 'revenue_released_with_outstanding', label: 'Released w/ outstanding', color: 'var(--color-role-platform)' },
    { key: 'revenue_waived', label: 'Waived', color: 'var(--color-ink-4)' },
  ]
  const donutSegments = useMemo(() => {
    if (!report) return []
    return DONUT_STATUS
      .map(({ key, label, color }) => {
        const value = Number(report.overview[key] ?? 0)
        return { label, value, color, amount: value }
      })
      .filter((s) => s.value > 0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report])

  // Top customers by amount billed (server-ranked, top 20).
  const topCustomers = useMemo(
    () => (report?.top_customers ?? []).map((c) => ({ name: c.name, amount: Number(c.amount) })),
    [report],
  )

  // CBM & billing table — server-aggregated per container (top 200 by billed).
  const containerBilling = useMemo(
    () => (report?.container_billing ?? []).map((r) => ({
      ctn: r.container_number,
      customers: r.customers,
      cbm: Number(r.cbm),
      billed: Number(r.billed),
      collected: Number(r.collected),
      outstanding: Number(r.outstanding),
      cbmRateUsd: Number(r.cbm_rate_usd),
      dollarRate: Number(r.dollar_rate),
    })),
    [report],
  )

  if (loading) return <div style={{ padding: 32, color: 'var(--color-ink-4)' }}>Loading reports…</div>

  return (
    <div>
      {/* Section A — Overview stats */}
      <div className={styles.statsRow}>
        <StatCard label="Containers processed" value={containersProcessed}   sublabel="cleared + released" icon="container" />
        <StatCard label="Total revenue"         value={fmtNgn(totalRevenue)} sublabel="billed this period"  icon="coin" />
        <StatCard label="Active customers"      value={customerCount}         sublabel="registered"          icon="users" />
        <StatCard label="Avg CBM / container"   value={avgCbmPerContainer}    sublabel="total CBM / processed" icon="package" />
      </div>

      {/* Section B — Revenue breakdown donut + top customers */}
      <div className={styles.grid2} style={{ marginBottom: 24 }}>
        <Card>
          <SectionHead title="Revenue by payment status" sub={`Total: ${fmtNgn(totalRevenue)}`} />
          <div style={{ height: 16 }} />
          {donutSegments.length > 0
            ? <DonutChart segments={donutSegments} total={totalRevenue} />
            : <p style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-sm)' }}>No billing data yet.</p>}
        </Card>
        <Card>
          <SectionHead title="Top customers by revenue" />
          <div style={{ height: 16 }} />
          {topCustomers.length > 0
            ? <TopCustomersChart data={topCustomers} />
            : <p style={{ color: 'var(--color-ink-4)', fontSize: 'var(--text-sm)' }}>No billing data yet.</p>}
        </Card>
      </div>

      {/* Section C — Container pipeline (weekly stacked bar) */}
      <Card style={{ marginBottom: 24 }}>
        <SectionHead title="Container pipeline" sub="Containers created per week by stage" />
        <div style={{ height: 16 }} />
        <ContainerPipelineChart data={report?.container_pipeline ?? []} />
      </Card>

      {/* Section D — CBM & billing table */}
      <Card padding={0} style={{ marginBottom: 24 }}>
        <div className={styles.tableHead}>
          <SectionHead title="CBM &amp; billing by container" sub="Every container processed this period" />
          <Button variant="secondary" size="sm" icon="download">Export</Button>
        </div>
        <Table
          columns={[
            { title: 'Container' },
            { title: 'Customers', align: 'right' },
            { title: 'Total CBM', align: 'right' },
            { title: 'CBM rate', align: 'right' },
            { title: 'FX rate', align: 'right' },
            { title: 'Billed', align: 'right' },
            { title: 'Collected', align: 'right' },
            { title: 'Outstanding', align: 'right' },
          ]}
          rows={containerBilling.map((row) => ({
            cells: [
              <Mono key="ctn">{row.ctn}</Mono>,
              <Mono key="cust">{row.customers}</Mono>,
              <Mono key="cbm">{Number(row.cbm).toFixed(2)}</Mono>,
              <Mono key="cbmrate" color="var(--color-ink-3)">{row.cbmRateUsd > 0 ? `$${row.cbmRateUsd.toFixed(2)}` : '—'}</Mono>,
              <Mono key="fx" color="var(--color-ink-3)">{row.dollarRate > 0 ? `₦${row.dollarRate.toFixed(0)}` : '—'}</Mono>,
              <Mono key="billed">{fmtNgn(row.billed)}</Mono>,
              <Mono key="collected" color="var(--color-success)">{fmtNgn(row.collected)}</Mono>,
              <Mono key="out" color={row.outstanding > 0 ? 'var(--color-warning)' : 'var(--color-ink-4)'}>
                {row.outstanding > 0 ? fmtNgn(row.outstanding) : '—'}
              </Mono>,
            ],
          }))}
          emptyState={<span>No billing records yet.</span>}
        />
      </Card>

      {/* Section E — Claims summary */}
      <SectionHead title="Claims summary" />
      <div style={{ height: 12 }} />
      <div className={styles.claimsGrid}>
        <ClaimsSummaryCard
          iconName="warn" color="var(--color-error)"
          title="Damage claims"
          stats={[['Open', String(claimCounts.open)], ['Resolved', String(claimCounts.resolved)], ['Total', String(claimCounts.total)]]}
        />
        <ClaimsSummaryCard
          iconName="package" color="var(--color-warning)"
          title="Missing items"
          stats={[['Filed', '—'], ['Found', '—'], ['Lost', '—']]}
        />
        <ClaimsSummaryCard
          iconName="coin" color="var(--color-success)"
          title="Refunds issued"
          stats={[['Approved', '—'], ['Total', '—'], ['', '']]}
        />
      </div>
    </div>
  )
}
