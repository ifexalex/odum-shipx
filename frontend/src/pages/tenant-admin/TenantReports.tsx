import { useQuery } from '@tanstack/react-query'
import { useMemo, type JSX } from 'react'
import { billingApi } from '../../api/billing'
import { billingKeys } from '../../api/keys'
import { STALE_5_MIN } from '../../lib/queryClient'
import { Banner, Card, DateRangeFilter, ExportButton, Icon, Mono, StatCard, Table, PageSkeleton, EmptyState } from '../../design/components'
import { useDateRangeFilter } from '../../hooks/useDateRangeFilter'
import { useListExport } from '../../hooks/useListExport'
import { SectionHead } from '../../shell/SectionHead'
import styles from './TenantReports.module.css'
import { formatCbm, formatNgn, formatUsd } from '../../lib/format'
import { PageHeader } from '../../shell/PageHeader'
import { NEUTRAL_SERIES_COLOR, statusLabel, statusSeriesColors } from '../../design/status'

/** How many containers GET /v1/billing/report lists (REPORT_CONTAINER_ROWS in services/billing/repository.py). */
const REPORT_CONTAINER_ROWS = 200

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

const DONUT_INVOICE_STATUSES = ['paid', 'partially_paid', 'unpaid', 'released_with_outstanding', 'waived'] as const

// ─── Top customers horizontal bars ───────────────────────────────────────────
function TopCustomersChart({ data }: { data: Array<{ name: string; amount: number }> }): JSX.Element {
  const max = data[0]?.amount ?? 1
  return (
    <div>
      {data.slice(0, 7).map((c) => (
        <div key={c.name} className={styles.topCustRow}>
          <span className={styles.topCustName}>{c.name}</span>
          <div className={styles.topCustBar}>
            <div
              className={styles.topCustFill}
              style={{
                width: `${(c.amount / max) * 100}%`,
                // One series of amounts, not statuses: one neutral colour (the first bar is not special) (FD-52).
                background: NEUTRAL_SERIES_COLOR,
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

// Each stage group is coloured as the container status it stands for (FD-52): sealed in China, in transit, arrived,
// fully released, with the registry's badge colours (in transit shares sealed's blue, so it takes the darker shade).
const PIPELINE_STATUSES = ['sealed', 'in_transit', 'arrived', 'fully_released'] as const
const PIPELINE_COLORS = statusSeriesColors('container', PIPELINE_STATUSES)
const PIPELINE_GROUPS = [
  { key: 'cn', label: 'China', color: PIPELINE_COLORS[0]! },
  { key: 'transit', label: 'In transit', color: PIPELINE_COLORS[1]! },
  { key: 'arrived', label: 'Arrived', color: PIPELINE_COLORS[2]! },
  { key: 'released', label: 'Released', color: PIPELINE_COLORS[3]! },
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
    <Card padding="default">
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

  const { createdAfter, createdBefore } = reportRange
  // The table's Export downloads every container billed in the period on screen; the table itself shows the top 200.
  const exportReport = useListExport((format: 'xlsx' | 'csv') =>
    billingApi.exportReport(
      {
        ...(createdAfter ? { created_after: createdAfter } : {}),
        ...(createdBefore ? { created_before: createdBefore } : {}),
      },
      format,
    ),
  )
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
    ? formatCbm(totalCbm / containersProcessed)
    : '—'

  // Revenue donut segments
  // Each slice is an invoice status: its words and colour come from the status registry, so "Released, balance owed"
  // is the amber of its badge, not purple (FD-52). Colours are picked for the slices on screen, so a status keeps its
  // badge's own shade unless another slice shares it.
  const donutSegments = useMemo(() => {
    if (!report) return []
    const present = DONUT_INVOICE_STATUSES.map((status) => ({
      status,
      value: Number(report.overview[`revenue_${status}` as keyof typeof report.overview] ?? 0),
    })).filter((s) => s.value > 0)
    const colors = statusSeriesColors(
      'invoice',
      present.map((s) => s.status),
    )
    return present.map((s, i) => ({ label: statusLabel('invoice', s.status), value: s.value, color: colors[i]!, amount: s.value }))
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

  // The header holds the period filter, so it stays on screen while a new period loads; only the figures wait.
  const header = <PageHeader title="Reports" actions={<DateRangeFilter label="Period" range={reportRange} />} />
  if (loading) {
    return (
      <div>
        {header}
        <PageSkeleton kind="list" label="Loading reports" />
      </div>
    )
  }

  return (
    <div>
      {header}
      {/* Section A — Overview stats */}
      <div className={styles.statsRow}>
        <StatCard label="Containers processed" value={containersProcessed}   sublabel="cleared + released" icon="container" />
        <StatCard label="Total revenue"         value={fmtNgn(totalRevenue)} sublabel="billed this period"  icon="coin" />
        <StatCard label="Active customers"      value={customerCount}         sublabel="registered"          icon="users" />
        <StatCard label="Avg CBM / container"   value={avgCbmPerContainer}    sublabel="total CBM / processed" icon="package" />
      </div>

      {/* Section B — Revenue breakdown donut + top customers */}
      <div className={styles.grid2} style={{ marginBottom: 'var(--space-6)' }}>
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
      <Card style={{ marginBottom: 'var(--space-6)' }}>
        <SectionHead title="Container pipeline" sub="Containers created per week by stage" />
        <div style={{ height: 16 }} />
        <ContainerPipelineChart data={report?.container_pipeline ?? []} />
      </Card>

      {/* Section D — CBM & billing table */}
      <Card padding="none" style={{ marginBottom: 'var(--space-6)' }}>
        <div className={styles.tableHead}>
          <SectionHead
            title="CBM &amp; billing by container"
            sub={
              containerBilling.length >= REPORT_CONTAINER_ROWS
                ? `The ${REPORT_CONTAINER_ROWS} containers billed most this period. Export for every container.`
                : 'Every container billed this period'
            }
          />
          <ExportButton size="sm" formats={['xlsx', 'csv']} onExport={exportReport.onExport} />
        </div>
        {exportReport.error && (
          <div className={styles.exportError}>
            <Banner variant="error" title="Couldn't export the report" dismissible onDismiss={exportReport.dismissError}>
              {exportReport.error}
            </Banner>
          </div>
        )}
        <Table
          columns={[
            { title: 'Container', type: 'reference' },
            { title: 'Customers', type: 'number' },
            { title: 'Volume (CBM)', type: 'number' },
            { title: 'CBM rate ($)', type: 'money' },
            { title: 'FX rate (₦ per $)', type: 'money' },
            { title: 'Billed (₦)', type: 'money' },
            { title: 'Collected (₦)', type: 'money' },
            { title: 'Outstanding (₦)', type: 'money' },
          ]}
          rows={containerBilling.map((row) => ({
            cells: [
              <Mono key="ctn">{row.ctn}</Mono>,
              <Mono key="cust">{row.customers}</Mono>,
              <Mono key="cbm">{formatCbm(row.cbm)}</Mono>,
              <Mono key="cbmrate" color="var(--color-ink-3)">{row.cbmRateUsd > 0 ? formatUsd(row.cbmRateUsd) : '—'}</Mono>,
              <Mono key="fx" color="var(--color-ink-3)">{row.dollarRate > 0 ? `₦${row.dollarRate.toFixed(0)}` : '—'}</Mono>,
              <Mono key="billed">{fmtNgn(row.billed)}</Mono>,
              <Mono key="collected" color="var(--color-success)">{fmtNgn(row.collected)}</Mono>,
              <Mono key="out" color={row.outstanding > 0 ? 'var(--color-warning)' : 'var(--color-ink-4)'}>
                {row.outstanding > 0 ? fmtNgn(row.outstanding) : '—'}
              </Mono>,
            ],
          }))}
          emptyState={<EmptyState compact title="No billing records yet" />}
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
