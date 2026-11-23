import { useEffect, useRef, type JSX, type ReactNode, type RefObject } from 'react'
import { useInRouterContext, useLocation } from 'react-router-dom'
import { ShellDrawerProvider, useDrawerState } from './ShellDrawer'
import styles from './CustShell.module.css'

export interface CustShellProps {
  topnav: ReactNode
  children: ReactNode
}

function ScrollReset({ targetRef }: { targetRef: RefObject<HTMLElement | null> }): null {
  const { pathname } = useLocation()
  useEffect(() => {
    const el = targetRef.current
    if (!el) return
    if (typeof el.scrollTo === 'function') {
      el.scrollTo({ top: 0, left: 0 })
    } else {
      el.scrollTop = 0
    }
  }, [pathname, targetRef])
  return null
}

// Customer-portal equivalent of PageShell — top nav + centered scrollable
// content, no sidebar (see CustomerTopNav.tsx, which owns the mobile
// drawer's overlay/panel markup — this component only provides the shared
// ShellDrawer context so CustomerTopNav's hamburger has something to
// toggle, the same way PageShell provides it for TopBar).
export function CustShell({ topnav, children }: CustShellProps): JSX.Element {
  const drawer = useDrawerState()
  const mainRef = useRef<HTMLElement>(null)
  const inRouter = useInRouterContext()

  return (
    <ShellDrawerProvider value={drawer}>
      {inRouter && <ScrollReset targetRef={mainRef} />}
      <div className={styles.shell}>
        {topnav}
        <main ref={mainRef} className={styles.main} onClickCapture={drawer.open ? drawer.close : undefined}>
          <div className={styles.inner}>{children}</div>
        </main>
      </div>
    </ShellDrawerProvider>
  )
}
