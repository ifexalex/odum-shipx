import { useQuery } from '@tanstack/react-query'
import { platformApi } from '../api/tenantManagement'
import { platformAuditKeys, platformDashboardKeys, platformTenantKeys } from '../api/keys'
import { STALE_30S, STALE_5_MIN } from '../lib/queryClient'

/**
 * Every tenant, with the API's cursor followed to the end (audit PA-02: it used to stop silently at 50). For the
 * dashboard's health table and the audit log's tenant filter; the Tenants page pages on the server instead.
 */
export function usePlatformTenantList() {
  return useQuery({
    queryKey: platformTenantKeys.list(),
    queryFn: () => platformApi.listAllTenants(),
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

/** A tenant's staff users (platform tenant page, Users tab). */
export function usePlatformTenantUsers(tenantId: string) {
  return useQuery({
    queryKey: platformTenantKeys.users(tenantId),
    queryFn: () => platformApi.tenantUsers(tenantId),
    enabled: !!tenantId,
    staleTime: STALE_30S,
  })
}

/** A tenant's configuration, secrets masked by the server (platform tenant page, Configuration tab). */
export function usePlatformTenantConfig(tenantId: string) {
  return useQuery({
    queryKey: platformTenantKeys.config(tenantId),
    queryFn: () => platformApi.tenantConfig(tenantId),
    enabled: !!tenantId,
    staleTime: STALE_30S,
  })
}

/** The last 50 platform audit entries about one tenant (platform tenant page, Audit tab). */
export function usePlatformTenantAudit(tenantId: string) {
  return useQuery({
    queryKey: platformAuditKeys.forTenant(tenantId),
    queryFn: () => platformApi.auditLog({ tenant_id: tenantId, limit: 50 }),
    enabled: !!tenantId,
    staleTime: STALE_30S,
  })
}

/** How often to look again while the hourly job has an export queued or running. */
export const EXPORT_POLL_MS = 60_000

/** The offboarded tenant's data export (audit BE-10). Polls while one is queued or being written. */
export function useOffboardingExport(tenantId: string, enabled: boolean) {
  return useQuery({
    queryKey: platformTenantKeys.offboardingExport(tenantId),
    queryFn: () => platformApi.offboardingExport(tenantId),
    enabled: enabled && !!tenantId,
    staleTime: STALE_30S,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'pending' || status === 'running' || query.state.data?.retrying ? EXPORT_POLL_MS : false
    },
  })
}
