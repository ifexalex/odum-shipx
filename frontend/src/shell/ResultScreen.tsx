/**
 * ResultScreen (FD-14): the page shown at the end of a flow, such as "Payment successful" or "Claim filed". It is the
 * one other component that titles a page: it holds the page's only top-level heading, so a result page never writes
 * its own `<h1>`.
 *
 *   <ResultScreen tone="success" title="Payment successful" actions={<Button>View invoice</Button>}>
 *     Your payment has been confirmed.
 *   </ResultScreen>
 */
import { useRef, type JSX, type ReactNode } from 'react'
import { Icon, type IconName } from '../design/components'
import { useFocusOnNavigate } from './headingFocus'
import styles from './ResultScreen.module.css'

export interface ResultScreenProps {
  tone: 'success' | 'warning' | 'error'
  title: string
  /** One or two sentences: what happened and what happens next. */
  children?: ReactNode
  actions?: ReactNode
}

const ICON: Record<ResultScreenProps['tone'], IconName> = { success: 'check', warning: 'alert', error: 'x' }

export function ResultScreen({ tone, title, children, actions }: ResultScreenProps): JSX.Element {
  const heading = useRef<HTMLHeadingElement>(null)
  useFocusOnNavigate(heading)
  return (
    <div className={styles.page}>
      <div className={[styles.icon, styles[tone]].join(' ')} aria-hidden="true">
        <Icon name={ICON[tone]} size={32} stroke={2.4} />
      </div>
      <h1 ref={heading} tabIndex={-1} className={styles.title}>
        {title}
      </h1>
      {children && <p className={styles.body}>{children}</p>}
      {actions && <div className={styles.actions}>{actions}</div>}
    </div>
  )
}
