import type { JSX } from 'react'
import { Button } from './Button'
import styles from './ListFooter.module.css'
import { formatCount } from '../../lib/format'

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
  /** The noun for exactly one row, e.g. "billing record". Defaults to `noun`. */
  nounOne?: string
}

/**
 * Consistent footer for every cursor-paginated list: a result count plus a
 * bounded "Load more". This is the list's only count (FD-13): a page does not repeat it above the table.
 * "of {total}" appears only when the total is more than the rows shown. Past `cap` rows it replaces the button with a nudge to
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
  nounOne,
}: ListFooterProps): JSX.Element | null {
  if (shown === 0) return null

  const counted = total != null && total > shown ? total : shown
  const word = counted === 1 ? (nounOne ?? noun) : noun
  const count = (
    <span className={styles.count}>
      Showing <strong>{formatCount(shown)}</strong>
      {counted > shown && (
        <>
          {' '}
          of <strong>{formatCount(total!)}</strong>
        </>
      )}{' '}
      {word}
    </span>
  )

  const capped = hasMore && shown >= cap
  const remaining = total != null && total > shown ? total - shown : null
  const loadLabel = remaining != null ? `Load more (${formatCount(remaining)} remaining)` : 'Load more'

  return (
    <div className={styles.footer}>
      {count}
      {hasMore && !capped && (
        <Button variant="secondary" size="sm" onClick={onLoadMore} loading={loading}>
          {loadLabel}
        </Button>
      )}
      {capped && (
        <span className={styles.refine}>
          Showing the first {formatCount(shown)} — refine your search or filters to narrow the rest.
        </span>
      )}
    </div>
  )
}
