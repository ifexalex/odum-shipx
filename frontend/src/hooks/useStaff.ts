import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { staffKeys } from '../api/keys'
import { usersApi, type CreateUserInput, type UpdateUserInput } from '../api/tenantManagement'
import { STALE_5_MIN } from '../lib/queryClient'

export function useStaffList() {
  return useQuery({
    queryKey: staffKeys.list(),
    queryFn: () => usersApi.list(),
    staleTime: STALE_5_MIN,
  })
}

export function useStaffUser(id: string) {
  return useQuery({
    queryKey: staffKeys.detail(id),
    queryFn: () => usersApi.get(id),
    enabled: !!id,
    staleTime: STALE_5_MIN,
  })
}

export function useCreateStaffUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateUserInput) => usersApi.create(body),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: staffKeys.all }) },
  })
}

export function useUpdateStaffUser(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateUserInput) => usersApi.update(id, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: staffKeys.detail(id) })
      void qc.invalidateQueries({ queryKey: staffKeys.list() })
    },
  })
}

export function useUpdateMyLocale() {
  return useMutation({
    mutationFn: (locale: 'en' | 'zh') => usersApi.updateMe(locale),
  })
}
