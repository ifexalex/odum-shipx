import { customersApi, type CustomerListParams } from '../api/tenantManagement'
import { customerKeys } from '../api/keys'
import { useCursorPagination } from './useCursorPagination'

export function useCustomerList(params: CustomerListParams = {}) {
  return useCursorPagination(
    customerKeys.list(params as Record<string, unknown>),
    (cursor) => customersApi.list({ ...params, cursor }),
  )
}
