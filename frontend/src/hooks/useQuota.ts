import { useQuery } from '@tanstack/react-query'
import { quotaApi, type TenantQuota } from '../api/tenantManagement'
import { useSession } from '../auth/useSession'
import { STALE_5_MIN } from '../lib/queryClient'

/** Percentage of a quota dimension that triggers the warning banner. */
export const QUOTA_WARN_THRESHOLD = 0.8
/** Percentage that means the limit is fully reached (hard block). */
export const QUOTA_LIMIT_THRESHOLD = 1.0

export function pctUsed(dim: { used: number; max: number }): number {
  if (dim.max <= 0) return 0
  return dim.used / dim.max
}

export function useQuota(): {
  quota: TenantQuota | undefined
  isLoading: boolean
  nearingLimit: boolean
  atLimit: boolean
  overLimitDimension: string | null
} {
  const { session } = useSession()

  // Platform admins and customers don't have per-tenant quotas
  const skip = !session || session.isPlatformAdmin || session.role === 'customer'

  const { data: quota, isLoading } = useQuery({
    queryKey: ['quota', 'me'],
    queryFn: quotaApi.getMyQuota,
    staleTime: STALE_5_MIN,
    enabled: !skip,
  })

  if (!quota) return { quota: undefined, isLoading, nearingLimit: false, atLimit: false, overLimitDimension: null }

  const dims = [
    { key: 'users', dim: quota.limits.users },
    { key: 'containers this month', dim: quota.limits.containers_per_month },
    { key: 'storage', dim: quota.limits.storage_gb },
  ]

  const atLimitDim = dims.find((d) => pctUsed(d.dim) >= QUOTA_LIMIT_THRESHOLD)
  const nearingDim = dims.find((d) => pctUsed(d.dim) >= QUOTA_WARN_THRESHOLD)

  return {
    quota,
    isLoading,
    nearingLimit: !!nearingDim && !atLimitDim,
    atLimit: !!atLimitDim,
    overLimitDimension: atLimitDim?.key ?? null,
  }
}
