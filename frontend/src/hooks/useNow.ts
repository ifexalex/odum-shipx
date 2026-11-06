import { useEffect, useState } from 'react'

/**
 * useNow — a clock that is safe to read during render.
 *
 * `Date.now()` called while rendering is impure: the value changes between
 * renders for reasons React cannot see, so output is unstable and a component
 * that re-renders for an unrelated reason silently shows a different answer.
 *
 * Holding the timestamp in state makes render a pure function of that state,
 * and advancing it on an interval makes anything derived from it — a countdown,
 * an "overdue" badge — actually tick rather than waiting for an unrelated
 * re-render to refresh it.
 *
 * Call this once in the list that owns the rows and pass `now` down, rather
 * than once per row: one timer, and every row agrees on the time.
 *
 * @param intervalMs How often to advance the clock. Default one minute, which
 *   suits day/hour countdowns; pass a smaller value only if seconds are shown.
 */
export function useNow(intervalMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])

  return now
}
