/**
 * Section (FD-19): one titled part of a record's page, its heading always inside its card (on some pages it sat
 * above the card, on others in it). A `<section>` named by its heading, so it is a region a screen reader can jump to.
 *
 *   <Section title="Carton tags" sub="12 tags on this note">…</Section>
 *   <Section title="Payments" flush>…a table, edge to edge…</Section>
 */
import { useId, type JSX, type ReactNode } from 'react'
import { Card } from '../design/components'
import styles from './Section.module.css'
import { SectionHead } from './SectionHead'

export interface SectionProps {
  title: string
  sub?: string
  /** A button for the section (Download invoice, Add charge). */
  action?: ReactNode
  /** The content runs to the card's edge (a table): the heading keeps its padding, the content does not. */
  flush?: boolean
  children: ReactNode
}

export function Section({ title, sub, action, flush = false, children }: SectionProps): JSX.Element {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className={styles.section}>
      <Card padding={flush ? 'none' : 'default'}>
        <div className={flush ? styles.flushHead : undefined}>
          <SectionHead title={title} sub={sub} action={action} headingId={headingId} />
        </div>
        {children}
      </Card>
    </section>
  )
}
