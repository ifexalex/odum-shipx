import type { JSX, ReactNode } from 'react'
import { ShellDrawerProvider, useDrawerState } from './ShellDrawer'
import styles from './CustShell.module.css'

export interface CustShellProps {
  topnav: ReactNode
  children: ReactNode
}

// Customer-portal equivalent of PageShell — top nav + centered scrollable
// content, no sidebar (see CustomerTopNav.tsx, which owns the mobile
// drawer's overlay/panel markup — this component only provides the shared
// ShellDrawer context so CustomerTopNav's hamburger has something to
// toggle, the same way PageShell provides it for TopBar).
export function CustShell({ topnav, children }: CustShellProps): JSX.Element {
  const drawer = useDrawerState()

  return (
    <ShellDrawerProvider value={drawer}>
      <div className={styles.shell}>
        {topnav}
        <main className={styles.main} onClickCapture={drawer.open ? drawer.close : undefined}>
          <div className={styles.inner}>{children}</div>
        </main>
      </div>
    </ShellDrawerProvider>
  )
}
