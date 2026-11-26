import type { JSX } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { homePathForRole } from '../auth/roleHome'
import { useSession } from '../auth/useSession'
import { Button } from '../design/components'
import { useDocumentTitle } from './documentTitle'
import { PageHeader } from './PageHeader'
import { nearestList } from './nearestList'
import styles from './NotFoundPage.module.css'

/**
 * An address that matches no route (FD-55). A signed-in user sees it inside their own layout, menu and all, with a way
 * to their home page and to the nearest list; a signed-out visitor gets the bare page and a way to sign in.
 */
export function NotFoundPage({ inLayout = false }: { inLayout?: boolean }): JSX.Element {
  const { session, status } = useSession()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const signedIn = status === 'authenticated' && !!session

  if (inLayout && session) {
    const home = homePathForRole(session.role)
    const list = nearestList(pathname, session.roles, home)
    return (
      <PageHeader
        title="Page not found"
        meta="This address doesn't match a page. The link may be out of date, or the page may have moved."
        primary={
          <Button variant="primary" icon="home" onClick={() => navigate(home)}>
            Go to your home page
          </Button>
        }
        actions={
          list && (
            <Button variant="secondary" onClick={() => navigate(list.to)}>
              Open {list.label.toLowerCase()}
            </Button>
          )
        }
      />
    )
  }

  return <BarePage signedIn={signedIn} target={signedIn && session ? homePathForRole(session.role) : '/'} />
}

function BarePage({ signedIn, target }: { signedIn: boolean; target: string }): JSX.Element {
  const navigate = useNavigate()
  useDocumentTitle([])
  return (
    <div className={styles.shell}>
      <div className={styles.code}>404</div>
      <h1 className={styles.title}>Page not found</h1>
      <p className={styles.subtitle}>The page you're looking for doesn't exist or may have moved.</p>
      <div className={styles.actions}>
        <Button variant="primary" onClick={() => navigate(target, { replace: true })}>
          {signedIn ? 'Go back home' : 'Go to home page'}
        </Button>
        {!signedIn && (
          <Button variant="secondary" onClick={() => navigate('/login', { replace: true })}>
            Sign in
          </Button>
        )}
      </div>
    </div>
  )
}
