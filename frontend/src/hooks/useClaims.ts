import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { claimsApi, type ClaimListParams, type FileDamageClaimInput } from '../api/claims'
import { claimKeys } from '../api/keys'
import { useCursorPagination } from './useCursorPagination'

export function useClaimList(params: ClaimListParams = {}) {
  return useCursorPagination(
    claimKeys.list(params as Record<string, unknown>),
    (cursor) => claimsApi.list({ ...params, cursor }),
  )
}

export function useClaim(id: string) {
  return useQuery({
    queryKey: claimKeys.detail(id),
    queryFn: () => claimsApi.get(id),
    enabled: !!id,
  })
}

export function useFileClaim() {
  const qc = useQueryClient()
  return useMutation({
    meta: { successToast: 'Claim filed' },
    mutationFn: ({ body, idempotencyKey }: { body: FileDamageClaimInput; idempotencyKey: string }) =>
      claimsApi.file(body, idempotencyKey),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: claimKeys.all })
    },
  })
}
