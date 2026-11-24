import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { packingListKeys } from '../api/keys'
import { packingListApi, type PackingListListParams, type RejectPackingListInput, type UpdatePackingListInput } from '../api/packingList'
import { useCursorPagination } from './useCursorPagination'
import { FRESH_ON_OPEN } from './useSeedOnce'

export function usePackingListList(params: PackingListListParams = {}) {
  return useCursorPagination(
    packingListKeys.list(params as Record<string, unknown>),
    (cursor) => packingListApi.list({ ...params, cursor }),
  )
}

export function usePackingList(id: string) {
  return useQuery({
    queryKey: packingListKeys.detail(id),
    queryFn: () => packingListApi.get(id),
    enabled: !!id,
  })
}

/**
 * A packing list for the edit form: read again every time the form opens, so the form is never filled from a cached
 * copy that someone has since approved or changed (FRESH_ON_OPEN). Disabled without an id (the create form).
 */
export function usePackingListForEdit(id: string | undefined) {
  return useQuery({
    queryKey: packingListKeys.detail(id ?? ''),
    queryFn: () => packingListApi.get(id!),
    enabled: !!id,
    ...FRESH_ON_OPEN,
  })
}

export function useApprovePackingList(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (comments?: string) => packingListApi.approve(id, comments),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: packingListKeys.detail(id) })
      void qc.invalidateQueries({ queryKey: packingListKeys.all })
    },
  })
}

export function useRejectPackingList(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: RejectPackingListInput) => packingListApi.reject(id, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: packingListKeys.detail(id) })
      void qc.invalidateQueries({ queryKey: packingListKeys.all })
    },
  })
}

export function useUpdatePackingList(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdatePackingListInput) => packingListApi.update(id, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: packingListKeys.detail(id) })
      void qc.invalidateQueries({ queryKey: packingListKeys.all })
    },
  })
}
