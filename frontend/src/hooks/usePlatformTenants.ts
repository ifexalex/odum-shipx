import { useQuery } from '@tanstack/react-query'
import { platformApi } from '../api/tenantManagement'
import { platformTenantKeys } from '../api/keys'
import { STALE_5_MIN } from '../lib/queryClient'

/** Platform tenant list — a plain array endpoint (not cursor-paginated). */
export function usePlatformTenantList() {
  return useQuery({
    queryKey: platformTenantKeys.list(),
    queryFn: () => platformApi.listTenants(),
    staleTime: STALE_5_MIN,
  })
}
