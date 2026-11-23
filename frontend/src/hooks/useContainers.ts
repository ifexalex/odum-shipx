import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { containerKeys, packingListKeys } from '../api/keys'
import { containersApi, type ContainerListParams, type UpdateContainerStatusInput } from '../api/tracking'
import { useCursorPagination } from './useCursorPagination'

export function useContainerList(params: ContainerListParams = {}) {
  return useCursorPagination(
    containerKeys.list(params as Record<string, unknown>),
    (cursor) => containersApi.list({ ...params, cursor }),
  )
}

/** Containers in one flat read, for a picker or a dashboard table (not the paginated list screen). */
export function useContainerLookup(params: ContainerListParams = {}, enabled = true) {
  return useQuery({
    queryKey: containerKeys.lookup(params as Record<string, unknown>),
    queryFn: () => containersApi.list(params),
    enabled,
  })
}

export function useContainer(id: string) {
  return useQuery({
    queryKey: containerKeys.detail(id),
    queryFn: () => containersApi.get(id),
    enabled: !!id,
  })
}

export function useContainerEvents(id: string) {
  return useQuery({
    queryKey: containerKeys.events(id),
    queryFn: () => containersApi.events(id),
    enabled: !!id,
  })
}

export function useUpdateContainerStatus(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateContainerStatusInput) => containersApi.updateStatus(id, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: containerKeys.detail(id) })
      void qc.invalidateQueries({ queryKey: containerKeys.events(id) })
      void qc.invalidateQueries({ queryKey: containerKeys.all })
    },
  })
}

export function useCancelContainer(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (notes?: string) => containersApi.cancel(id, notes),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: containerKeys.detail(id) })
      void qc.invalidateQueries({ queryKey: containerKeys.all })
    },
  })
}

export function useDeleteContainer(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => containersApi.delete(id),
    onSuccess: () => {
      qc.removeQueries({ queryKey: containerKeys.detail(id) })
      void qc.invalidateQueries({ queryKey: containerKeys.all })
      // Packing lists that were in this container need to reflect the change
      void qc.invalidateQueries({ queryKey: packingListKeys.all })
    },
  })
}
