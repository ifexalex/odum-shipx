import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { warehouseKeys } from '../api/keys'
import { warehousesApi, type CreateWarehouseInput, type UpdateWarehouseInput, type Warehouse } from '../api/warehouses'

export function useWarehouses(enabled = true) {
  return useQuery({
    queryKey: warehouseKeys.all,
    queryFn: () => warehousesApi.list(),
    staleTime: 5 * 60 * 1000,
    enabled,
  })
}

/**
 * A warehouse write that refreshes the list once it succeeds. Every change to a warehouse goes through one of these:
 * the list is cached for five minutes, so a write that skipped it left the page showing the old list (a deleted
 * warehouse still there, a new one missing) until something else reloaded it.
 */
function useWarehouseMutation<TVariables>(mutationFn: (variables: TVariables) => Promise<Warehouse>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: warehouseKeys.all })
    },
  })
}

export function useCreateWarehouse() {
  return useWarehouseMutation((body: CreateWarehouseInput) => warehousesApi.create(body))
}

export function useUpdateWarehouse() {
  return useWarehouseMutation(({ id, body }: { id: string; body: UpdateWarehouseInput }) => warehousesApi.update(id, body))
}

export function useSetDefaultWarehouse() {
  return useWarehouseMutation((id: string) => warehousesApi.setDefault(id))
}

/** Delete for real. Refused with `WAREHOUSE_IN_USE` while records point at the warehouse; retire it instead. */
export function useRemoveWarehouse() {
  return useWarehouseMutation((id: string) => warehousesApi.remove(id))
}

/** Retire: hidden from pickers, kept on the records issued against it, its name free to reuse. */
export function useDeactivateWarehouse() {
  return useWarehouseMutation((id: string) => warehousesApi.deactivate(id))
}
