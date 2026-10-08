import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { manifestKeys } from '../api/keys'
import { manifestApi, type ManifestListParams, type VerifyManifestInput } from '../api/manifest'
import { useCursorPagination } from './useCursorPagination'

export function useManifestList(params: ManifestListParams = {}) {
  return useCursorPagination(
    manifestKeys.list(params as Record<string, unknown>),
    (cursor) => manifestApi.list({ ...params, cursor }),
  )
}

export function useManifest(id: string) {
  return useQuery({
    queryKey: manifestKeys.detail(id),
    queryFn: () => manifestApi.get(id),
    enabled: !!id,
  })
}

export function useVerifyManifest(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: VerifyManifestInput) => manifestApi.verify(id, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: manifestKeys.detail(id) })
      void qc.invalidateQueries({ queryKey: manifestKeys.all })
    },
  })
}
