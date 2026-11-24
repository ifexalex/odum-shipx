import { useEffect, useRef, type JSX, type ReactNode, type RefObject } from 'react'
import { useInRouterContext, useLocation } from 'react-router-dom'
import { ShellDrawerProvider, useDrawerState } from './ShellDrawer'
import styles from './PageShell.module.css'

export interface PageShellProps {
  sidebar: ReactNode
  topbar: ReactNode
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

// Flex layout root every authenticated page renders inside: sidebar + (topbar + scrollable content).
// The root is a CSS container (container-name: sxapp) — all responsive rules in the
// shell, tables, and grids key off this container's width, not the viewport, per the
// prototype's .sx-appframe (Shipx_frontend_design/screens/shared/components.jsx).
export function PageShell({ sidebar, topbar, children }: PageShellProps): JSX.Element {
  const drawer = useDrawerState()
  const contentRef = useRef<HTMLElement>(null)
  const inRouter = useInRouterContext()

  return (
    <ShellDrawerProvider value={drawer}>
      {inRouter && <ScrollReset targetRef={contentRef} />}
      <div className={styles.shell}>
        <div className={styles.docked}>{sidebar}</div>
        {drawer.open && (
          <div className={styles.drawerOverlay} onClick={drawer.close}>
            <div className={styles.drawerPanel} onClick={(e) => e.stopPropagation()}>
              {sidebar}
            </div>
          </div>
        )}
        <div className={styles.main}>
          {topbar}
          <main ref={contentRef} className={styles.content} onClickCapture={drawer.open ? drawer.close : undefined}>
            {children}
          </main>
        </div>
      </div>
    </ShellDrawerProvider>
  )
}
