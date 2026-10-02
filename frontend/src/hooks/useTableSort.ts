import { useState } from 'react'
import type { TableSort } from '../design/components'

export interface SortableColumn {
  /** Index into the Table's `columns` array — matches `onSort(columnIndex)`. */
  index: number
  /** API `sort` query param value — must be in shared/pagination.py's ALLOWED_SORT_FIELDS. */
  field: string
  /** Direction applied the first time this column becomes the active sort. */
  defaultDirection: 'asc' | 'desc'
}

export interface UseTableSortResult {
  /** Pass straight through to `<Table sort={sort} onSort={onSort} />`. */
  sort: TableSort | undefined
  onSort: (columnIndex: number) => void
  /** API `sort` param — undefined when no column is actively sorted (server default applies). */
  sortField: string | undefined
  /** API `direction` param. */
  sortDirection: 'asc' | 'desc' | undefined
}

/**
 * Drives a paginated list page's column-sort UI + the `sort`/`direction`
 * query params sent to the API. Clicking an inactive sortable column
 * activates it in its configured `defaultDirection`; clicking the
 * already-active column toggles asc <-> desc.
 *
 * Convention used across ContainerList/BillingList/ClaimList: text/reference
 * columns default asc (alphabetical); "when this record was created/billed/
 * filed" timestamp columns default desc (newest first); a forward-looking
 * scheduling date (e.g. container ETA) defaults asc (soonest first).
 *
 * Usage:
 *   const { sort, onSort, sortField, sortDirection } = useTableSort([
 *     { index: 0, field: 'container_number', defaultDirection: 'asc' },
 *     { index: 6, field: 'estimated_arrival_date', defaultDirection: 'asc' },
 *   ])
 *   const { items } = useContainerList({ sort: sortField, direction: sortDirection })
 *   <Table sort={sort} onSort={onSort} .../>
 */
export function useTableSort(columns: SortableColumn[]): UseTableSortResult {
  const [sort, setSort] = useState<TableSort | undefined>(undefined)

  function onSort(columnIndex: number): void {
    const column = columns.find((c) => c.index === columnIndex)
    if (!column) return
    setSort((prev) =>
      prev?.columnIndex === columnIndex
        ? { columnIndex, direction: prev.direction === 'asc' ? 'desc' : 'asc' }
        : { columnIndex, direction: column.defaultDirection },
    )
  }

  const activeColumn = sort ? columns.find((c) => c.index === sort.columnIndex) : undefined

  return {
    sort,
    onSort,
    sortField: activeColumn?.field,
    sortDirection: sort?.direction,
  }
}
