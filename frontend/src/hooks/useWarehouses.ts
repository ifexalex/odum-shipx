import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { warehouseKeys } from '../api/keys'
import { warehousesApi, type CreateWarehouseInput } from '../api/warehouses'

export function useWarehouses(enabled = true) {
  return useQuery({
    queryKey: warehouseKeys.all,
    queryFn: () => warehousesApi.list(),
    staleTime: 5 * 60 * 1000,
    enabled,
  })
}

export function useCreateWarehouse() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateWarehouseInput) => warehousesApi.create(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: warehouseKeys.all })
    },
  })
}

export function useSetDefaultWarehouse() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => warehousesApi.setDefault(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: warehouseKeys.all })
    },
  })
}
