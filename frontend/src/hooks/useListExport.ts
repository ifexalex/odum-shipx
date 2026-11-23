import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

export interface ListExport<F> {
  /** Hand this to `<ExportButton onExport>`. Its identity never changes, so it is safe to capture once. */
  onExport: (format: F) => Promise<void>
  /** Why the last export failed, in words for the user; null when it has not (or the last one worked). */
  error: string | null
  dismissError: () => void
}

/**
 * Wraps a list page's export call for `<ExportButton>`.
 *
 * Two things the page would otherwise get wrong:
 *
 * - **Stale filters.** A page puts its Export button in the TopBar through `useTopBarSlot`, which captures the
 *   button once, on mount. An `onExport` closing over the page's filter state would forever export the filters the
 *   page had when it opened. The returned `onExport` is stable and calls the *latest* `exporter`, so what is
 *   exported is what is on screen at the moment of the click.
 * - **Unhandled failures.** `ExportButton` does not catch. An export that is refused (for example 422 when the
 *   filter matches more than the export limit) is turned into a message for the page to show.
 */
export function useListExport<F>(exporter: (format: F) => Promise<void>): ListExport<F> {
  const latest = useRef(exporter)
  useEffect(() => {
    latest.current = exporter
  })
  const [error, setError] = useState<string | null>(null)

  const onExport = useCallback(async (format: F): Promise<void> => {
    setError(null)
    try {
      await latest.current(format)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The export failed. Try again.')
    }
  }, [])

  return { onExport, error, dismissError: () => setError(null) }
}
