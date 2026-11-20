/**
 * PageHeader (FD-14): the one way a page is titled. Every page renders exactly one, at the top of its content:
 *
 *   <PageHeader
 *     title="Invoice INV-A-002"
 *     status={<StatusBadge kind="invoice" status={invoice.payment_status} />}
 *     meta={[invoice.customer_name, <Mono>{invoice.container_number}</Mono>, `Billed ${formatDate(invoice.billed_at)}`]}
 *     primary={<Action variant="primary">Record payment</Action>}
 *     actions={<ExportButton … />}
 *     more={[{ label: 'Cancel invoice', tone: 'danger', onSelect: … }]}
 *   />
 *
 * After an in-app navigation, keyboard focus moves to its heading (FD-48). It holds the page's only top-level heading (FD-49), so a page never writes its own `<h1>`, and the page's actions,
 * so the top bar keeps only global controls. The breadcrumb above it comes from the layout (FD-45), which renders it
 * even while the page is still loading.
 */
import { Fragment, useRef, type JSX, type ReactNode } from 'react'
import { MenuButton, type MenuItem } from '../design/components'
import { useFocusOnNavigate } from './headingFocus'
import styles from './PageHeader.module.css'

export interface PageHeaderProps {
  /** The page or record: "Containers", "Invoice INV-A-002". Sentence case, no full stop. */
  title: string
  /** The record's status badge, beside the title. */
  status?: ReactNode
  /**
   * One line under the title. A list of facts is joined with middle dots and empty facts are dropped, so a record
   * page can pass `[customer, container, date]` without guarding each one. A list page passes one sentence.
   */
  meta?: ReactNode | readonly ReactNode[]
  /** The page's one primary action. */
  primary?: ReactNode
  /** Secondary actions, shown beside the primary one. Keep to two or three; fold the rest into `more`. */
  actions?: ReactNode
  /** Further actions, in an overflow menu. */
  more?: MenuItem[]
  /** The overflow button's accessible name; defaults to "More actions". */
  moreLabel?: string
}

/**
 * The title, with each reference ("INV-A-002", "PL-20261113-003") kept whole: it moves to the next line rather than
 * splitting at a hyphen, and breaks inside only if it is wider than the column.
 */
function titleWords(title: string): ReactNode[] {
  return title.split(/(\s+)/).map((word, index) =>
    /\d/.test(word) && /[-/]/.test(word) ? (
      <span key={index} className={styles.reference}>
        {word}
      </span>
    ) : (
      word
    ),
  )
}

const isShown = (fact: ReactNode): boolean => fact !== null && fact !== undefined && fact !== false && fact !== ''

export function PageHeader({ title, status, meta, primary, actions, more, moreLabel }: PageHeaderProps): JSX.Element {
  const facts = (Array.isArray(meta) ? meta : [meta]).filter(isShown)
  const hasActions = isShown(primary) || isShown(actions) || (more?.length ?? 0) > 0
  const heading = useRef<HTMLHeadingElement>(null)
  useFocusOnNavigate(heading)
  return (
    <div className={styles.header} data-page-start="">
      <div className={styles.titleBlock}>
        <div className={styles.titleRow}>
          <h1 ref={heading} tabIndex={-1} className={styles.title}>
            {titleWords(title)}
          </h1>
          {status}
        </div>
        {facts.length > 0 && (
          <p className={styles.meta}>
            {facts.map((fact, index) => (
              <Fragment key={index}>
                {index > 0 && (
                  <span className={styles.dot} aria-hidden="true">
                    ·
                  </span>
                )}
                <span className={styles.fact}>{fact}</span>
              </Fragment>
            ))}
          </p>
        )}
      </div>
      {hasActions && (
        <div className={styles.actions}>
          {actions}
          {isShown(primary) && (
            // On a phone the primary action is a bar fixed to the bottom of the screen, always in reach (FD-35).
            <div className={styles.primary} data-sticky-action="">
              {primary}
            </div>
          )}
          {more && more.length > 0 && <MenuButton items={more} label={moreLabel} />}
        </div>
      )}
    </div>
  )
}
