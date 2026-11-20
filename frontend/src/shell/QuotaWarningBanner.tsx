/**
 * The plan-limit notice (FD-16): one line inside the content column, for the tenant admin only, saying which limit is
 * near or reached, with a link to the plan. Other roles meet a limit through the limit-reached dialog when an action is
 * blocked, so they are not shown a warning they cannot act on all day.
 *
 * The admin can dismiss it for the session. It comes back when the situation changes: another dimension, or a
 * warning that becomes a reached limit.
 */
import { useState, type JSX } from 'react'
import { Link } from 'react-router-dom'
import { Icon, IconButton } from '../design/components'
import { pctUsed, useQuota } from '../hooks/useQuota'
import { PLAN_ANCHOR } from './PlanUsagePanel'
import styles from './QuotaWarningBanner.module.css'

const DISMISSED_KEY = 'shipx_quota_notice_dismissed'

function readDismissed(): string | null {
  try {
    return sessionStorage.getItem(DISMISSED_KEY)
  } catch {
    return null
  }
}

export interface QuotaNotice {
  /** What it is about, for dismissal: a new key shows again. */
  key: string
  level: 'warning' | 'error'
  text: string
}

/** The notice to show the tenant admin, or null when every limit is under 80%. */
export function useQuotaNotice(): QuotaNotice | null {
  const { quota } = useQuota()
  if (!quota) return null
  const dims = [
    { key: 'users', label: 'Users', dim: quota.limits.users },
    { key: 'containers', label: 'Containers this month', dim: quota.limits.containers_per_month },
    { key: 'storage', label: 'Storage', dim: quota.limits.storage_gb },
  ]
  const tier = quota.subscription_tier[0]!.toUpperCase() + quota.subscription_tier.slice(1)
  const reached = dims.find((d) => pctUsed(d.dim) >= 1)
  if (reached) {
    return {
      key: `${reached.key}:reached`,
      level: 'error',
      text: `${reached.label}: ${reached.dim.used} of ${reached.dim.max}. You have reached your ${tier} plan’s limit.`,
    }
  }
  const near = dims.find((d) => pctUsed(d.dim) >= 0.8)
  if (near) {
    return {
      key: `${near.key}:near`,
      level: 'warning',
      text: `${near.label}: ${near.dim.used} of ${near.dim.max} used, close to your ${tier} plan’s limit.`,
    }
  }
  return null
}

export function QuotaWarningBanner({ notice }: { notice: QuotaNotice }): JSX.Element | null {
  const [dismissed, setDismissed] = useState(readDismissed)
  if (dismissed === notice.key) return null
  const dismiss = (): void => {
    try {
      sessionStorage.setItem(DISMISSED_KEY, notice.key)
    } catch {
      // Storage blocked: it still hides for this page view.
    }
    setDismissed(notice.key)
  }
  return (
    <div className={[styles.bar, styles[notice.level]].join(' ')} role="status">
      <Icon name={notice.level === 'error' ? 'alert' : 'warn'} size={16} stroke={2} />
      <span className={styles.text}>{notice.text}</span>
      <Link to={`/dashboard#${PLAN_ANCHOR}`} className={styles.link}>
        View plan
      </Link>
      <IconButton icon="x" label="Dismiss the plan-limit notice" size="sm" onClick={dismiss} />
    </div>
  )
}
