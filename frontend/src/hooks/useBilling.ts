import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { billingApi, disputeApi, type BillingListParams, type DisputeListParams, type FileDisputeInput, type RecordPaymentInput, type ResolveCBMDisputeInput } from '../api/billing'
import { billingKeys, disputeKeys } from '../api/keys'
import { useCursorPagination } from './useCursorPagination'

export function useBillingList(params: BillingListParams = {}) {
  return useCursorPagination(
    billingKeys.list(params as Record<string, unknown>),
    (cursor) => billingApi.list({ ...params, cursor }),
  )
}

export function useDisputeList(params: DisputeListParams = {}) {
  return useCursorPagination(
    disputeKeys.list(params as Record<string, unknown>),
    (cursor) => disputeApi.list({ ...params, cursor }),
  )
}

export function useBillingForCustomer(customerId: string) {
  return useQuery({
    queryKey: billingKeys.forCustomer(customerId),
    queryFn: () => billingApi.listForCustomer(customerId),
    enabled: !!customerId,
  })
}

export function useRecordPayment(billingId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ body, idempotencyKey }: { body: RecordPaymentInput; idempotencyKey: string }) =>
      billingApi.recordPayment(billingId, body, idempotencyKey),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: billingKeys.detail(billingId) })
      void qc.invalidateQueries({ queryKey: billingKeys.all })
    },
  })
}

export function useFileDispute(billingId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: FileDisputeInput) => disputeApi.file(billingId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: billingKeys.detail(billingId) })
      void qc.invalidateQueries({ queryKey: billingKeys.all })
    },
  })
}

export function useResolveDispute(disputeId: string, billingId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ResolveCBMDisputeInput) => disputeApi.resolve(disputeId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: billingKeys.detail(billingId) })
      void qc.invalidateQueries({ queryKey: billingKeys.all })
    },
  })
}
