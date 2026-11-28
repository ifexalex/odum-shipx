import { useQuery } from '@tanstack/react-query'
import { platformAdminKeys, platformApprovalKeys, platformMeKeys } from '../api/keys'
import { platformSecurityApi, type ApprovalStatus, type PlatformPermission } from '../api/platformSecurity'
import { useSession } from '../auth/useSession'
import { STALE_30S, STALE_5_MIN } from '../lib/queryClient'

/** The signed-in platform admin's directory row and permissions. Off for every other role. */
export function usePlatformMe() {
  const { session } = useSession()
  return useQuery({
    queryKey: platformMeKeys.all,
    queryFn: () => platformSecurityApi.me(),
    enabled: session?.role === 'platform_admin',
    staleTime: STALE_5_MIN,
  })
}

/**
 * Whether the caller's platform role allows `permission`. False while `/me` loads: an action button appears once the
 * role is known rather than flashing and then vanishing. The API enforces the same rule on every request.
 */
export function useCanPlatform(permission: PlatformPermission): boolean {
  const { data } = usePlatformMe()
  return data?.permissions.includes(permission) ?? false
}

/** The platform admin directory. */
export function usePlatformAdmins() {
  return useQuery({
    queryKey: platformAdminKeys.list(),
    queryFn: () => platformSecurityApi.listAdmins(),
    staleTime: STALE_30S,
  })
}

/** Approvals; `open` means pending or scheduled. */
export function usePlatformApprovals(status?: 'open' | ApprovalStatus) {
  return useQuery({
    queryKey: platformApprovalKeys.list(status),
    queryFn: () => platformSecurityApi.listApprovals(status),
    staleTime: STALE_30S,
  })
}

/** How many approvals are open, for the sidebar badge. Off unless `enabled` (platform admins only). */
export function useOpenApprovalCount(enabled: boolean): number {
  const { data } = useQuery({
    queryKey: platformApprovalKeys.list('open'),
    queryFn: () => platformSecurityApi.listApprovals('open'),
    enabled,
    staleTime: STALE_30S,
  })
  return data?.length ?? 0
}
