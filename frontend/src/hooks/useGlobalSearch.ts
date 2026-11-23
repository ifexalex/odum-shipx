import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { searchApi, MIN_SEARCH_LENGTH, type SearchResult } from '../api/search'
import { searchKeys } from '../api/keys'
import { STALE_30S } from '../lib/queryClient'

const DEBOUNCE_MS = 250

/** `value`, but only once it has stopped changing for `delay` ms. */
function useDebounced(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export interface GlobalSearchState {
  /** The text the results are for (trimmed, debounced). */
  term: string
  /** Results for `term`. Empty while the text is shorter than the server's minimum. */
  results: SearchResult[]
  /** True while the user is still typing, or the request is in flight. */
  isSearching: boolean
  isError: boolean
}

/**
 * Debounced global search. Nothing is requested until the trimmed text reaches the server's minimum length, and
 * a previous term's results stay on screen while the next one loads so the list does not flash empty per keystroke.
 */
export function useGlobalSearch(text: string): GlobalSearchState {
  const typed = text.trim()
  const term = useDebounced(typed, DEBOUNCE_MS)
  const long = typed.length >= MIN_SEARCH_LENGTH
  const query = useQuery({
    queryKey: searchKeys.query(term),
    queryFn: () => searchApi.search(term),
    enabled: term.length >= MIN_SEARCH_LENGTH,
    staleTime: STALE_30S,
    placeholderData: (previous) => previous,
    retry: false,
  })
  return {
    term,
    // placeholderData would otherwise keep showing the last term's hits after the text is cut back below the minimum.
    results: long ? (query.data?.results ?? []) : [],
    isSearching: long && (typed !== term || query.isFetching),
    isError: long && query.isError,
  }
}
