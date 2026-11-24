/**
 * DetailPage (FD-19): the one layout of a record's page, top to bottom: page header, notices, an optional progress
 * strip, then a main column of sections beside a side rail with the record's summary (the figures you look for first).
 * Below 1200 px the rail comes first, above the sections, so the summary is still the first thing after the header.
 *
 *   <DetailPage
 *     header={<PageHeader title="Release note ACM-RN-…" … />}
 *     progress={<Stepper … />}
 *     aside={<Section title="Summary">…</Section>}
 *   >
 *     <Section title="Release details">…</Section>
 *     <Section title="Carton tags">…</Section>
 *   </DetailPage>
 *
 * State each fact once: what the header says (customer, container, dates) is not repeated in the sections or the rail.
 */
import type { JSX, ReactNode } from 'react'
import { Card } from '../design/components'
import styles from './DetailPage.module.css'

export interface DetailPageProps {
  header: ReactNode
  /** Banners about the record: a lock, an expiry, a failed action. */
  notices?: ReactNode
  /** A `Stepper` for a record that moves through stages; it sits in a card of its own. */
  progress?: ReactNode
  /** The record's summary, as one or more `Section`s. */
  aside?: ReactNode
  /** The record's sections (`Section`), in reading order. */
  children: ReactNode
}

export function DetailPage({ header, notices, progress, aside, children }: DetailPageProps): JSX.Element {
  return (
    <div className={styles.page}>
      {header}
      {notices && <div className={styles.notices}>{notices}</div>}
      {progress && <Card padding="default">{progress}</Card>}
      <div className={[styles.body, aside ? styles.withAside : ''].join(' ')}>
        <div className={styles.main}>{children}</div>
        {aside && <aside className={styles.aside}>{aside}</aside>}
      </div>
    </div>
  )
}
