import type { JSX } from 'react'
import { Banner } from '../design/components'
import { pctUsed, useQuota } from '../hooks/useQuota'

/**
 * Shell-level quota warning banner.
 *
 * Renders:
 *  - Nothing when all dimensions are below 80%.
 *  - A warning banner when any dimension is 80–99% used.
 *  - An error banner when any dimension is at or over 100%.
 *
 * Mounted once in StaffLayout so it appears on every staff page.
 */
export function QuotaWarningBanner(): JSX.Element | null {
  const { quota, nearingLimit, atLimit } = useQuota()

  if (!quota || (!nearingLimit && !atLimit)) return null

  const dims = [
    { label: 'Users', dim: quota.limits.users },
    { label: 'Containers this month', dim: quota.limits.containers_per_month },
    { label: 'Storage', dim: quota.limits.storage_gb },
  ]

  const atLimitDim = dims.find((d) => pctUsed(d.dim) >= 1)
  const nearingDim = dims.find((d) => pctUsed(d.dim) >= 0.8)

  if (atLimitDim) {
    const { label, dim } = atLimitDim
    return (
      <div style={{ padding: '0 0 0 0' }}>
        <Banner variant="error" title={`${label} limit reached`}>
          {label} ({dim.used}/{dim.max}) — you have reached your {quota.subscription_tier} plan limit.
          Contact support or upgrade your plan to continue.
        </Banner>
      </div>
    )
  }

  if (nearingDim) {
    const { label, dim } = nearingDim
    const pct = Math.round(pctUsed(dim) * 100)
    return (
      <div style={{ padding: '0 0 0 0' }}>
        <Banner variant="warning" title={`Approaching ${label.toLowerCase()} limit`}>
          {label}: {dim.used} of {dim.max} used ({pct}%). Upgrade your plan before the limit is reached.
        </Banner>
      </div>
    )
  }

  return null
}
