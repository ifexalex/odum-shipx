import type { JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { homePathForRole } from '../auth/roleHome'
import { useSession } from '../auth/useSession'
import { Button } from '../design/components'
import styles from './NotFoundPage.module.css'

// Catch-all for any path not in routeTable.ts — a real page, not a blank
// screen (06_routing_rbac_and_navigation.md AC).
export function NotFoundPage(): JSX.Element {
  const { session, status } = useSession()
  const navigate = useNavigate()
  const target = status === 'authenticated' && session ? homePathForRole(session.role) : '/login'

  return (
    <div className={styles.shell}>
      <div className={styles.code}>404</div>
      <h1 className={styles.title}>Page not found</h1>
      <p className={styles.subtitle}>The page you're looking for doesn't exist or may have moved.</p>
      <Button variant="primary" onClick={() => navigate(target, { replace: true })}>
        Go back home
      </Button>
    </div>
  )
}
