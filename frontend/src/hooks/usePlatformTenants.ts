import { useQuery } from '@tanstack/react-query'
import { platformApi } from '../api/tenantManagement'
import { platformAuditKeys, platformDashboardKeys, platformTenantKeys } from '../api/keys'
import { STALE_5_MIN } from '../lib/queryClient'

/** Platform tenant list — a plain array endpoint (not cursor-paginated). */
export function usePlatformTenantList() {
  return useQuery({
    queryKey: platformTenantKeys.list(),
    queryFn: () => platformApi.listTenants(),
    staleTime: STALE_5_MIN,
  })
}

/** Cross-tenant totals for the platform dashboard. Refreshed by any tenant write (api/cacheInvalidation.ts). */
export function usePlatformDashboardStats() {
  return useQuery({
    queryKey: platformDashboardKeys.summary(),
    queryFn: () => platformApi.dashboard(),
    staleTime: STALE_5_MIN,
  })
}

/** The newest platform audit events, for the dashboard's activity feed. Non-fatal: the dashboard renders without it. */
export function useRecentPlatformActivity(limit: number) {
  return useQuery({
    queryKey: platformAuditKeys.recent(limit),
    queryFn: () => platformApi.auditLog({ limit }),
  })
}
