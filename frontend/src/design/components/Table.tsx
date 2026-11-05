import { useLayoutEffect, useRef, useState, type JSX, type ReactNode, type RefObject } from 'react'
import { Check } from './Check'
import { Icon } from './Icon'
import styles from './Table.module.css'

export interface TableColumn {
  title: string
  width?: string
  align?: 'left' | 'right' | 'center'
  sortable?: boolean
  /** Omit this column's label:value pair from the mobile card view — for a
   * column that's genuinely redundant once the identity column (index 0)
   * and the other fields are already shown as a card. */
  hideInCard?: boolean
}

export interface TableRow {
  cells: ReactNode[]
  selected?: boolean
  /** When false the row's checkbox is hidden even if the table is selectable. */
  selectable?: boolean
  /** Highlights the row with an error-tint background — used for failed/overdue rows. */
  suspended?: boolean
}

export interface TableSort {
  columnIndex: number
  direction: 'asc' | 'desc'
}

export interface TableProps {
  columns: TableColumn[]
  rows: TableRow[]
  selectable?: boolean
  dense?: boolean
  loading?: boolean
  emptyState?: ReactNode
  sort?: TableSort
  onSort?: (columnIndex: number) => void
  onSelectRow?: (rowIndex: number, selected: boolean) => void
  onSelectAll?: (selected: boolean) => void
  /** Width (px) at/below which the table collapses to the mobile card view.
   * Defaults to the app-wide 860px convention. Compact, few-column tables
   * embedded in a narrow desktop column (e.g. the dashboard's summary tables)
   * pass a smaller value so they stay tabular on desktop and only card-ify on
   * an actual phone — otherwise a ~776px dashboard column would render giant
   * cards on a 1440px screen, inconsistent with every full-width list. */
  cardBreakpoint?: number
}

const ALIGN_TH: Record<'left' | 'right' | 'center', string> = {
  left: '',
  right: styles.thRight!,
  center: styles.thCenter!,
}
const ALIGN_TD: Record<'left' | 'right' | 'center', string> = {
  left: '',
  right: styles.tdRight!,
  center: styles.tdCenter!,
}

const SKELETON_ROWS = 5

// Matches the app-wide 860px mobile convention (PageShell/TopBar/Sidebar's
// @container sxapp breakpoint) — see 02_design_tokens_and_theming.md.
const CARD_VIEW_BREAKPOINT = 860

/** True once this element's own measured width drops to/below `breakpoint`.
 *
 * A real ResizeObserver-driven measurement of the Table's own wrapper,
 * not a shared-ancestor container query — deliberately so a table nested
 * in a narrower column (e.g. a two-column detail layout) switches to the
 * card view at the width it actually has, not the full page's width.
 *
 * Defaults to `false` (table view) and only flips based on a genuine
 * nonzero measurement — jsdom has no layout engine and always reports 0
 * for getBoundingClientRect(), so every existing test that renders <Table>
 * keeps seeing the table markup unchanged unless it explicitly drives a
 * ResizeObserver callback itself.
 */
function useIsNarrow(ref: RefObject<HTMLDivElement | null>, breakpoint: number): boolean {
  const [isNarrow, setIsNarrow] = useState(false)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return

    const measure = (width: number): void => {
      if (width > 0) setIsNarrow(width <= breakpoint)
    }
    measure(el.getBoundingClientRect().width)

    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width
      if (width != null) measure(width)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref, breakpoint])

  return isNarrow
}

export function Table({
  columns,
  rows,
  selectable = false,
  dense = false,
  loading = false,
  emptyState,
  sort,
  onSort,
  onSelectRow,
  onSelectAll,
  cardBreakpoint = CARD_VIEW_BREAKPOINT,
}: TableProps): JSX.Element {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const isNarrow = useIsNarrow(wrapperRef, cardBreakpoint)

  const colSpan = columns.length + (selectable ? 1 : 0)
  const selectedCount = rows.filter((row) => row.selected).length
  const allSelected = rows.length > 0 && selectedCount === rows.length
  const someSelected = selectedCount > 0 && !allSelected

  const lastIndex = columns.length - 1
  const hasTrailingAction = lastIndex >= 0 && columns[lastIndex]?.title === ''
  const cardFieldIndices = columns
    .map((_, i) => i)
    .filter((i) => i !== 0 && !(hasTrailingAction && i === lastIndex) && !columns[i]?.hideInCard)

  return (
    <div ref={wrapperRef} className={styles.wrapper}>
      {isNarrow ? (
        <div className={styles.cardList}>
          {selectable && rows.length > 0 && (
            <label className={styles.cardSelectAll}>
              <Check checked={allSelected} partial={someSelected} onChange={(checked) => onSelectAll?.(checked)} />
              <span>Select all</span>
            </label>
          )}
          {loading ? (
            Array.from({ length: SKELETON_ROWS }, (_, i) => (
              <div key={i} className={styles.card}>
                <div className={styles.skeletonBar} style={{ width: '50%', height: 16 }} />
                {cardFieldIndices.map((fi) => (
                  <div key={fi} className={styles.skeletonBar} />
                ))}
              </div>
            ))
          ) : rows.length === 0 ? (
            <div className={styles.emptyCell}>{emptyState}</div>
          ) : (
            rows.map((row, rowIndex) => (
              <div
                key={rowIndex}
                className={[styles.card, row.selected ? styles.cardSelected : '', row.suspended ? styles.cardSuspended : '']
                  .filter(Boolean)
                  .join(' ')}
              >
                <div className={styles.cardHeader}>
                  {selectable && row.selectable !== false && (
                    <Check checked={row.selected ?? false} onChange={(checked) => onSelectRow?.(rowIndex, checked)} />
                  )}
                  <div className={styles.cardHeaderValue}>{row.cells[0]}</div>
                </div>
                {cardFieldIndices.length > 0 && (
                  <div className={styles.cardBody}>
                    {cardFieldIndices.map((fi) => (
                      <div key={fi} className={styles.cardField}>
                        <span className={styles.cardLabel}>{columns[fi]!.title}</span>
                        <span className={styles.cardValue}>{row.cells[fi]}</span>
                      </div>
                    ))}
                  </div>
                )}
                {hasTrailingAction && <div className={styles.cardAction}>{row.cells[lastIndex]}</div>}
              </div>
            ))
          )}
        </div>
      ) : (
        <table className={styles.table} aria-busy={loading}>
          <thead>
            <tr>
              {selectable && (
                <th className={[styles.th, styles.thSelect].join(' ')}>
                  <Check
                    checked={allSelected}
                    partial={someSelected}
                    onChange={(checked) => onSelectAll?.(checked)}
                  />
                </th>
              )}
              {columns.map((column, index) => {
                const align = column.align ?? 'left'
                const isActive = sort?.columnIndex === index
                const headContent = (
                  <span
                    className={[styles.thHead, align === 'right' ? styles.thHeadRight : '']
                      .filter(Boolean)
                      .join(' ')}
                  >
                    {column.title}
                    {column.sortable && (
                      <Icon
                        name={isActive && sort?.direction === 'asc' ? 'chevup' : 'chevdown'}
                        size={11}
                        color={isActive ? 'var(--color-primary)' : 'var(--color-ink-4)'}
                      />
                    )}
                  </span>
                )
                return (
                  <th
                    key={column.title}
                    style={{ width: column.width }}
                    className={[styles.th, ALIGN_TH[align], isActive ? styles.sortActive : '']
                      .filter(Boolean)
                      .join(' ')}
                  >
                    {column.sortable ? (
                      <button type="button" className={styles.sortButton} onClick={() => onSort?.(index)}>
                        {headContent}
                      </button>
                    ) : (
                      headContent
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: SKELETON_ROWS }, (_, rowIndex) => (
                // Placeholder rows carry no information: hidden from assistive
                // tech (the table's aria-busy already announces the load), and
                // marked so tests can tell them apart from real data. They are
                // structurally identical to data rows otherwise, so anything
                // counting `tbody tr` reads five phantom rows mid-load.
                <tr key={rowIndex} className={styles.row} aria-hidden="true" data-skeleton-row="">
                  {selectable && (
                    <td className={dense ? styles.tdSelectDense : styles.tdSelect} />
                  )}
                  {columns.map((column) => (
                    <td key={column.title} className={dense ? styles.tdDense : styles.td}>
                      <div className={styles.skeletonBar} />
                    </td>
                  ))}
                </tr>
              ))
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={colSpan} className={styles.emptyCell}>
                  {emptyState}
                </td>
              </tr>
            ) : (
              rows.map((row, rowIndex) => (
                <tr key={rowIndex} className={[styles.row, row.selected ? styles.rowSelected : '', row.suspended ? styles.rowSuspended : ''].filter(Boolean).join(' ')}>
                  {selectable && (
                    <td className={dense ? styles.tdSelectDense : styles.tdSelect}>
                      {row.selectable !== false && (
                        <Check
                          checked={row.selected ?? false}
                          onChange={(checked) => onSelectRow?.(rowIndex, checked)}
                        />
                      )}
                    </td>
                  )}
                  {row.cells.map((cell, cellIndex) => {
                    const align = columns[cellIndex]?.align ?? 'left'
                    return (
                      <td
                        key={cellIndex}
                        className={[dense ? styles.tdDense : styles.td, ALIGN_TD[align]]
                          .filter(Boolean)
                          .join(' ')}
                      >
                        {cell}
                      </td>
                    )
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
