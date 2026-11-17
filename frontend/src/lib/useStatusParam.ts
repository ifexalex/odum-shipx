import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * A list page's status filter, kept in the URL as `?status=` so a link can open the list already filtered (the China
 * work queue's "View all", a dashboard queue) and the filter survives a reload or the back button.
 *
 * A value not in `allowed` reads as no filter, so a stale or hand-typed link shows everything rather than nothing.
 * Changing the filter replaces the history entry instead of adding one per click.
 */
export function useStatusParam<T extends string>(allowed: readonly T[]): [T | null, (next: T | null) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get('status')
  const value = raw !== null && (allowed as readonly string[]).includes(raw) ? (raw as T) : null

  const setValue = useCallback(
    (next: T | null) => {
      setParams(
        (current) => {
          const updated = new URLSearchParams(current)
          if (next === null) updated.delete('status')
          else updated.set('status', next)
          return updated
        },
        { replace: true },
      )
    },
    [setParams],
  )
  return [value, setValue]
}
