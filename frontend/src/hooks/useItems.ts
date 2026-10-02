import { missingItemsApi, seizedItemsApi, type ItemListParams } from '../api/claims'
import { missingItemKeys, seizedItemKeys } from '../api/keys'
import { useCursorPagination } from './useCursorPagination'

export function useMissingItemList(params: ItemListParams = {}) {
  return useCursorPagination(
    missingItemKeys.list(params as Record<string, unknown>),
    (cursor) => missingItemsApi.list({ ...params, cursor }),
  )
}

export function useSeizedItemList(params: ItemListParams = {}) {
  return useCursorPagination(
    seizedItemKeys.list(params as Record<string, unknown>),
    (cursor) => seizedItemsApi.list({ ...params, cursor }),
  )
}
