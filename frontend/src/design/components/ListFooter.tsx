import type { JSX } from 'react'
import { Button } from './Button'
import styles from './ListFooter.module.css'

export interface ListFooterProps {
  /** Rows currently rendered (e.g. items.length). */
  shown: number
  /** Total matching rows across all pages (meta.pagination.total_count). */
  total?: number
  /** Another page is available from the server. */
  hasMore: boolean
  /** A page fetch is in flight. */
  loading?: boolean
  onLoadMore: () => void
  /**
   * Once this many rows are loaded into the page, stop offering "Load more"
   * and steer the user to search/filter instead — the design goal is that a
   * dataset of tens of thousands is navigated by narrowing, never by loading
   * every row into the DOM. Default 500.
   */
  cap?: number
  /** Noun for the count line, e.g. "billing records". Defaults to "results". */
  noun?: string
}

/**
 * Consistent footer for every cursor-paginated list: a result count plus a
 * bounded "Load more". Past `cap` rows it replaces the button with a nudge to
 * refine the search, so the DOM never grows without limit on a large dataset.
 */
export function ListFooter({
  shown,
  total,
  hasMore,
  loading,
  onLoadMore,
  cap = 500,
  noun = 'results',
}: ListFooterProps): JSX.Element | null {
  if (shown === 0) return null

  const count =
    total != null && total > 0 ? (
      <span className={styles.count}>
        Showing <strong>{shown.toLocaleString()}</strong> of{' '}
        <strong>{total.toLocaleString()}</strong> {noun}
      </span>
    ) : (
      <span className={styles.count}>
        <strong>{shown.toLocaleString()}</strong> {noun}
      </span>
    )

  const capped = hasMore && shown >= cap
  const remaining = total != null && total > shown ? total - shown : null
  const loadLabel = remaining != null ? `Load more (${remaining.toLocaleString()} remaining)` : 'Load more'

  return (
    <div className={styles.footer}>
      {count}
      {hasMore && !capped && (
        <Button variant="secondary" onClick={onLoadMore} loading={loading}>
          {loadLabel}
        </Button>
      )}
      {capped && (
        <span className={styles.refine}>
          Showing the first {shown.toLocaleString()} — refine your search or filters to narrow the rest.
        </span>
      )}
    </div>
  )
}
