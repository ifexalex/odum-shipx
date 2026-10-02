import type { JSX, ReactNode } from 'react'
import { ShellDrawerProvider, useDrawerState } from './ShellDrawer'
import styles from './PageShell.module.css'

export interface PageShellProps {
  sidebar: ReactNode
  topbar: ReactNode
  children: ReactNode
}

// Flex layout root every authenticated page renders inside: sidebar + (topbar + scrollable content).
// The root is a CSS container (container-name: sxapp) — all responsive rules in the
// shell, tables, and grids key off this container's width, not the viewport, per the
// prototype's .sx-appframe (Shipx_frontend_design/screens/shared/components.jsx).
export function PageShell({ sidebar, topbar, children }: PageShellProps): JSX.Element {
  const drawer = useDrawerState()

  return (
    <ShellDrawerProvider value={drawer}>
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
          <main className={styles.content} onClickCapture={drawer.open ? drawer.close : undefined}>
            {children}
          </main>
        </div>
      </div>
    </ShellDrawerProvider>
  )
}
