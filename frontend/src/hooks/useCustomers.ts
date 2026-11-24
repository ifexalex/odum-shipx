import { useQuery } from '@tanstack/react-query'
import { customersApi, type CustomerListParams } from '../api/tenantManagement'
import { customerKeys } from '../api/keys'
import { useCursorPagination } from './useCursorPagination'

export function useCustomerList(params: CustomerListParams = {}) {
  return useCursorPagination(
    customerKeys.list(params as Record<string, unknown>),
    (cursor) => customersApi.list({ ...params, cursor }),
  )
}

/** The signed-in customer's own record: for the customer role the list endpoint returns exactly that, or nothing. */
export const OWN_CUSTOMER_KEY = customerKeys.lookup({ own: true })

export function useOwnCustomer() {
  return useQuery({
    queryKey: OWN_CUSTOMER_KEY,
    queryFn: async () => (await customersApi.list()).data[0] ?? null,
  })
}

/** Every customer in one flat read, for a picker (not the paginated list screen). */
export function useCustomerLookup() {
  return useQuery({ queryKey: customerKeys.lookup({}), queryFn: () => customersApi.list() })
}
