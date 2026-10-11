import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { onboardingRequestKeys } from '../api/keys'
import {
  platformApi,
  type OnboardingRequest,
  type OnboardingRequestStatus,
} from '../api/tenantManagement'
import { STALE_5_MIN } from '../lib/queryClient'

/** Shipping-company onboarding leads for the platform review queue. */
export function useOnboardingRequests(status?: OnboardingRequestStatus) {
  return useQuery({
    queryKey: onboardingRequestKeys.list(status),
    queryFn: () => platformApi.listOnboardingRequests(status),
    staleTime: STALE_5_MIN,
  })
}

// Statuses that still need an admin's attention — these drive the sidebar badge.
const PENDING_STATUSES: OnboardingRequestStatus[] = ['new', 'contacted', 'approved']

/**
 * Count of leads still awaiting action, for the platform sidebar badge.
 *
 * `enabled` gates the fetch to platform admins — for every other role the query
 * never runs and the count is 0, so the hook is safe to call unconditionally.
 */
export function useOnboardingPendingCount(enabled: boolean): number {
  const { data } = useQuery({
    queryKey: onboardingRequestKeys.list(),
    queryFn: () => platformApi.listOnboardingRequests(),
    staleTime: STALE_5_MIN,
    enabled,
  })
  if (!data) return 0
  return data.filter((r) => PENDING_STATUSES.includes(r.status)).length
}

interface UpdateOnboardingVars {
  id: string
  status: OnboardingRequestStatus
  rejectionReason?: string
}

/** Mark-contacted / reject a lead; invalidates every cached lead list. */
export function useUpdateOnboardingRequest() {
  const queryClient = useQueryClient()
  return useMutation<OnboardingRequest, Error, UpdateOnboardingVars>({
    mutationFn: ({ id, status, rejectionReason }) =>
      platformApi.updateOnboardingRequest(id, status, rejectionReason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: onboardingRequestKeys.all })
    },
  })
}
