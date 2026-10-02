import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { refundsApi, type ApproveRefundInput, type RefundListParams } from '../api/refunds'
import { refundKeys } from '../api/keys'
import { useCursorPagination } from './useCursorPagination'

export function useRefundList(params: RefundListParams = {}) {
  return useCursorPagination(
    refundKeys.list(params as Record<string, unknown>),
    (cursor) => refundsApi.list({ ...params, cursor }),
  )
}

export function useRefund(id: string) {
  return useQuery({
    queryKey: refundKeys.detail(id),
    queryFn: () => refundsApi.get(id),
    enabled: !!id,
  })
}

export function useApproveRefund(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ApproveRefundInput) => refundsApi.approve(id, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: refundKeys.detail(id) })
      void qc.invalidateQueries({ queryKey: refundKeys.all })
    },
  })
}
