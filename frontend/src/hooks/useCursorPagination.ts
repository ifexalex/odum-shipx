import { useInfiniteQuery } from '@tanstack/react-query'
import type { ListResponse } from '../api/client'

export interface CursorPaginationResult<T> {
  items: T[]
  hasMore: boolean
  totalCount: number
  loadMore: () => void
  isLoading: boolean
  isFetchingMore: boolean
  error: Error | null
  refetch: () => void
}

/**
 * useCursorPagination — wraps useInfiniteQuery for the ShipX cursor pagination pattern.
 *
 * Every list endpoint returns ListResponse<T> with meta.pagination.next_cursor.
 * This hook hides the page-array structure from callers — they see a flat `items` array
 * and call `loadMore()` to fetch the next page.
 *
 * Usage:
 *   const { items, hasMore, loadMore, isLoading } = useCursorPagination(
 *     containerKeys.list(filters),
 *     (cursor) => containersApi.list({ ...filters, cursor }),
 *   )
 */
export function useCursorPagination<T>(
  queryKey: readonly unknown[],
  fetchPage: (cursor: string | undefined) => Promise<ListResponse<T>>,
  options: { enabled?: boolean; staleTime?: number; refetchIntervalMs?: number } = {},
): CursorPaginationResult<T> {
  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => fetchPage(pageParam as string | undefined),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.meta.pagination.next_cursor ?? undefined,
    enabled: options.enabled ?? true,
    ...(options.staleTime !== undefined ? { staleTime: options.staleTime } : {}),
    // Polling: pause when the tab is backgrounded. The interval callback returns
    // `false` while `document.hidden` (no fetch scheduled), and React Query also
    // holds background intervals via its visibility focusManager
    // (refetchIntervalInBackground defaults to false). Together this guarantees
    // zero network traffic from a hidden tab — see 09_state_management doc.
    ...(options.refetchIntervalMs !== undefined
      ? {
          refetchInterval: () =>
            typeof document !== 'undefined' && document.hidden ? false : options.refetchIntervalMs,
          refetchIntervalInBackground: false,
        }
      : {}),
  })

  const items = query.data?.pages.flatMap((p) => p.data) ?? []
  const lastPage = query.data?.pages.at(-1)
  const hasMore = lastPage?.meta.pagination.has_more ?? false
  const totalCount = lastPage?.meta.pagination.total_count ?? 0

  return {
    items,
    hasMore,
    totalCount,
    loadMore: () => { void query.fetchNextPage() },
    isLoading: query.isLoading,
    isFetchingMore: query.isFetchingNextPage,
    error: query.error,
    refetch: () => { void query.refetch() },
  }
}
