/**
 * ListPage (FD-18): the one layout of a list page, top to bottom: page header, notices (a failed load, a failed
 * export), at most four stat cards, the filter bar, the table, its footer. Every list page fills these slots instead of
 * stacking its own, so the order and the spacing are the same everywhere.
 *
 *   <ListPage
 *     header={<PageHeader title="Billing" … />}
 *     stats={<StatRow><StatCard … onSelect={…} /></StatRow>}
 *     filters={<FilterBar status={…} search={…} dateRange={…} />}
 *     footer={<ListFooter … />}
 *   >
 *     <Table … />
 *   </ListPage>
 */
import { Children, type JSX, type ReactNode } from 'react'
import { Card } from '../design/components'
import styles from './ListPage.module.css'

export interface ListPageProps {
  header: ReactNode
  /** Banners about the page itself: a failed load, a failed export. */
  notices?: ReactNode
  /** A `StatRow`. */
  stats?: ReactNode
  /** A `FilterBar`. */
  filters?: ReactNode
  /** The table. It sits in a card of its own, edge to edge (FD-10). */
  children: ReactNode
  /** A `ListFooter`. */
  footer?: ReactNode
}

export function ListPage({ header, notices, stats, filters, children, footer }: ListPageProps): JSX.Element {
  return (
    <div className={styles.page}>
      {header}
      {notices && <div className={styles.notices}>{notices}</div>}
      {stats}
      {filters}
      <div className={styles.table}>
        <Card padding="none">{children}</Card>
        {footer}
      </div>
    </div>
  )
}

/** The most stat cards a list page shows (FD-18): each a number worth acting on, not filler. */
export const MAX_STATS = 4

/**
 * The row of stat cards on a list page: at most four, each a number worth acting on, ideally one that applies its
 * filter when clicked (`StatCard onSelect`). Four or fewer share the row equally; on a phone they wrap two by two.
 */
export function StatRow({ children }: { children: ReactNode }): JSX.Element {
  const count = Children.toArray(children).filter(Boolean).length
  if (import.meta.env.DEV && count > MAX_STATS) {
    console.error(`StatRow: ${count} stat cards; a list page shows at most ${MAX_STATS} (FD-18).`)
  }
  return <div className={styles.stats}>{children}</div>
}
