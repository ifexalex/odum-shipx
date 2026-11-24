/**
 * A record named on another record's page, as a link to it (FD-17): "Ngozi Adeyemi" on a refund links to the customer,
 * "INV-A-002" to the invoice. Where the viewer's roles cannot open that page (Nigeria staff and the customer profile),
 * it is plain text rather than a link that bounces them home.
 */
import type { JSX, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useSession } from '../auth/useSession'
import { canOpen } from './breadcrumbs'
import styles from './RecordLink.module.css'

export function RecordLink({ to, children }: { to: string; children: ReactNode }): JSX.Element {
  const { session } = useSession()
  if (!session || !canOpen(to, session.roles)) return <>{children}</>
  return (
    <Link to={to} className={styles.link}>
      {children}
    </Link>
  )
}
