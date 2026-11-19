/**
 * 15.4A — tenant-facing plan-usage panel (audit gap B9, prototype
 * quota-screens.jsx QuotaBarRow). Per-dimension usage bars for the tenant
 * admin's dashboard — green under 80%, amber from 80%, red at the limit —
 * fed by the same GET /v1/tenants/me/quota the shell's warning banner uses.
 *
 * Only dimensions with real limits get bars; API-call and notification
 * counters (no max in the quota response) render as a plain meta line rather
 * than fabricated percentages.
 */
import type { JSX } from 'react'
import { Badge, Card, Mono } from '../design/components'
import { pctUsed, useQuota } from '../hooks/useQuota'
import { SectionHead } from './SectionHead'
import styles from './PlanUsagePanel.module.css'
import { formatCount } from '../lib/format'

function QuotaBarRow({ label, used, max, unit }: { label: string; used: number; max: number; unit?: string }): JSX.Element {
  const pct = Math.min(100, Math.round(pctUsed({ used, max }) * 100))
  const atLimit = pct >= 100
  const warning = pct >= 80 && !atLimit
  const color = atLimit ? 'var(--color-error)' : warning ? 'var(--color-warning)' : 'var(--color-primary)'

  return (
    <div className={styles.row}>
      <div className={styles.rowLabel}>{label}</div>
      <div className={styles.track}>
        <div className={styles.fill} style={{ width: `${pct}%`, background: color }} />
      </div>
      <Mono color="var(--color-ink-2)">
        {formatCount(used)} / {formatCount(max)}{unit ? ` ${unit}` : ''}
      </Mono>
      <div className={styles.pctCell}>
        {atLimit ? (
          <Badge variant="error" size="sm">At limit</Badge>
        ) : warning ? (
          <Badge variant="warning" size="sm">{pct}%</Badge>
        ) : (
          <span className={styles.pctQuiet}>{pct}%</span>
        )}
      </div>
    </div>
  )
}

export function PlanUsagePanel(): JSX.Element | null {
  const { quota } = useQuota()
  if (!quota) return null

  const tierLabel = quota.subscription_tier[0]!.toUpperCase() + quota.subscription_tier.slice(1)

  return (
    <Card padding="default">
      <SectionHead
        title={`Plan usage · ${tierLabel}`}
        sub={`Period ${quota.period} · limits reset monthly`}
      />
      <div style={{ height: 12 }} />
      <QuotaBarRow label="Active users" used={quota.limits.users.used} max={quota.limits.users.max} />
      <QuotaBarRow
        label="Containers / month"
        used={quota.limits.containers_per_month.used}
        max={quota.limits.containers_per_month.max}
      />
      <QuotaBarRow label="Storage" used={quota.limits.storage_gb.used} max={quota.limits.storage_gb.max} unit="GB" />
      <div className={styles.metaLine}>
        This period: {formatCount(quota.api_calls)} API calls · {formatCount(quota.notifications.sms_sent)} SMS
        · {formatCount(quota.notifications.whatsapp_sent)} WhatsApp · {formatCount(quota.notifications.emails_sent)} email
      </div>
    </Card>
  )
}
