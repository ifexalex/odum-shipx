import { useEffect, useRef } from 'react'

/**
 * Options for a settings form's read: fetch again every time the form opens.
 *
 * Config queries are otherwise cached for a long time (rates never change without a Save on this client). A form
 * must not be filled from a copy that another admin has since changed, so its read ignores the cache's age.
 */
export const FRESH_ON_OPEN = { staleTime: 0, refetchOnMount: 'always' } as const

/** What a query hook returns, as far as seeding a form is concerned. */
interface SeedSource<T> {
  data: T | undefined
  /** True once this mount has fetched, so `data` is the server's current value and not an older cached copy. */
  isFetchedAfterMount: boolean
}

/**
 * Copy a query's data into a form's own editable state, once, when the freshly fetched value arrives.
 *
 * This is how a page that used to `fetch` in an effect and `setState` the result keeps its editable fields while the
 * read itself moves to React Query. Once, not on every change: a later background refetch must not overwrite what the
 * user is typing. After a save the page sets its fields from the response itself, as it always did.
 */
export function useSeedOnce<T>(source: SeedSource<T>, seed: (data: T) => void): void {
  const seeded = useRef(false)
  const { data, isFetchedAfterMount } = source
  useEffect(() => {
    if (seeded.current || !isFetchedAfterMount || data === undefined) return
    seeded.current = true
    seed(data)
    // `seed` is the page's own setter calls; depending on it would re-run this for every render's new closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, isFetchedAfterMount])
}
