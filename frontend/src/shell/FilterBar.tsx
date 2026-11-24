/**
 * FilterBar (FD-18): the filters of a list page, always in one order: status chips, search, date range, more filters.
 * A page fills the slots it has; it never arranges them itself, so the same control sits in the same place on every
 * list.
 *
 *   <FilterBar
 *     status={<>…<Chip>…</Chip></>}
 *     search={<SearchField … />}
 *     dateRange={<DateRangeFilter … />}
 *     more={<>…selects…</>}
 *     activeCount={applied}
 *     onClear={clearAll}
 *   />
 *
 * `more` holds the filters used less often; on a wide screen they open from a "More filters" button. Below 600 px of
 * its own width (FD-35) the bar shows only the search and a "Filters" button, which opens every other filter in a
 * sheet, so a phone is not handed four rows of controls before the first result.
 */
import { useRef, useState, type JSX, type ReactNode } from 'react'
import { Button, Card, Modal } from '../design/components'
import { useIsNarrow } from '../design/useIsNarrow'
import styles from './FilterBar.module.css'

export interface FilterBarProps {
  /** Status chips (`Chip`), "All" first. */
  status?: ReactNode
  /** The list's search box (`SearchField`). */
  search?: ReactNode
  /** A `DateRangeFilter`. */
  dateRange?: ReactNode
  /** Filters used less often (selects, multi-selects). */
  more?: ReactNode
  /** How many filters are applied besides the search, shown on the Filters / More filters button. */
  activeCount?: number
  /** Clears every filter; offered in the "More filters" panel and the phone sheet. */
  onClear?: () => void
  /** Names the bar for screen readers (a `search` landmark): "Filter containers". */
  label?: string
}

export const NARROW_BELOW = 600

export function FilterBar({
  status,
  search,
  dateRange,
  more,
  activeCount = 0,
  onClear,
  label = 'Filter the list',
}: FilterBarProps): JSX.Element {
  const ref = useRef<HTMLDivElement>(null)
  const narrow = useIsNarrow(ref, NARROW_BELOW)
  const [moreOpen, setMoreOpen] = useState(false)
  const [sheetOpen, setSheetOpen] = useState(false)
  const count = activeCount > 0 ? ` (${activeCount})` : ''

  if (narrow) {
    const inSheet = Boolean(status || dateRange || more)
    return (
      <div ref={ref} role="search" aria-label={label}>
        <Card padding="small">
          <div className={[styles.row, styles.narrowRow].join(' ')}>
            {search && <div className={styles.search}>{search}</div>}
            {inSheet && (
              <Button variant="secondary" icon="filter" onClick={() => setSheetOpen(true)}>
                {`Filters${count}`}
              </Button>
            )}
          </div>
        </Card>
        <Modal
          open={sheetOpen}
          onClose={() => setSheetOpen(false)}
          title="Filters"
          footer={
            <>
              {onClear && (
                <Button variant="ghost" onClick={onClear}>
                  Clear all
                </Button>
              )}
              <Button variant="primary" onClick={() => setSheetOpen(false)}>
                Show results
              </Button>
            </>
          }
        >
          <div className={styles.sheet}>
            {status && <div className={styles.chips}>{status}</div>}
            {dateRange}
            {more}
          </div>
        </Modal>
      </div>
    )
  }

  return (
    <div ref={ref} role="search" aria-label={label}>
      <Card padding="small">
        {status && <div className={styles.chips}>{status}</div>}
        {(search || dateRange || more) && (
          <div className={[styles.row, status ? styles.rowAfterChips : ''].join(' ')}>
            {search && <div className={styles.search}>{search}</div>}
            {dateRange}
            {more && (
              <div className={styles.moreWrap}>
                <Button
                  variant="secondary"
                  icon="filter"
                  aria-expanded={moreOpen}
                  onClick={() => setMoreOpen((o) => !o)}
                >
                  {`More filters${count}`}
                </Button>
                {moreOpen && (
                  <>
                    <div className={styles.moreOverlay} onClick={() => setMoreOpen(false)} />
                    <div className={styles.morePanel} role="dialog" aria-label="More filters">
                      {more}
                      {onClear && (
                        <Button variant="ghost" size="sm" onClick={onClear}>
                          Clear all filters
                        </Button>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
