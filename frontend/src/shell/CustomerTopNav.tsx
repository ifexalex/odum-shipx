import type { JSX, ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Icon, KolaMark, ShipxWordmark, ThemeToggle } from '../design/components'
import type { NavLinkDef } from './navConfig'
import { useShellDrawer } from './ShellDrawer'
import styles from './CustomerTopNav.module.css'

export interface CustomerTopNavProps {
  links: NavLinkDef[]
  notifications?: number
  /**
   * Rendered inside the bell's own positioning wrapper (`position: relative`)
   * so a dropdown panel (`position: absolute; top: 100%; right: 0`) anchors
   * under the bell — see TopBar.tsx's identical `notificationsPanel` prop
   * and CustomerLayout.tsx for the real usage (CustomerNotificationPanel).
   */
  notificationsPanel?: ReactNode
  onNotificationsClick?: () => void
  onLogout?: () => void
  /** The global search box (<GlobalSearch>), rendered ahead of the icon buttons. */
  search?: ReactNode
}

function CustNavLink({ icon, label, path, count, onNavigate }: NavLinkDef & { onNavigate?: () => void }): JSX.Element {
  const location = useLocation()
  const navigate = useNavigate()
  const active = location.pathname === path || location.pathname.startsWith(`${path}/`)
  return (
    <button
      type="button"
      className={[styles.navLink, active ? styles.navLinkActive : ''].filter(Boolean).join(' ')}
      onClick={() => {
        navigate(path)
        onNavigate?.()
      }}
    >
      {icon && <Icon name={icon} size={15} stroke={2} />}
      {label}
      {count != null && <span className={styles.badge}>{count}</span>}
    </button>
  )
}

// Horizontal nav for the customer portal — deliberately not the staff
// Sidebar (06_routing_rbac_and_navigation.md AC: customer portal stays on
// this layout). It shows a notification bell and a plain logout button, and no
// user-name chip.
//
// Mobile drawer: below 860px `.links` hides and a hamburger (mirroring
// TopBar's staff-side one, same useShellDrawer() context — CustShell
// provides it) opens the same links as a full-height vertical panel,
// closing itself on navigation, overlay click, or Escape.
export function CustomerTopNav({
  links,
  notifications = 0,
  notificationsPanel,
  onNotificationsClick,
  onLogout,
  search,
}: CustomerTopNavProps): JSX.Element {
  const drawer = useShellDrawer()

  return (
    <header className={styles.topnav}>
      {drawer && (
        <button type="button" aria-label="Open menu" className={styles.hamburger} onClick={drawer.toggle}>
          <Icon name="menu" size={18} stroke={2} color="#fff" />
        </button>
      )}
      <div className={styles.brand}>
        <KolaMark size={28} color="#fff" />
        <ShipxWordmark size={20} color="#fff" />
      </div>
      <nav className={styles.links}>
        {links.map((link) => (
          <CustNavLink key={link.path} {...link} />
        ))}
      </nav>
      <div className={styles.right}>
        {search}
        <ThemeToggle className={styles.iconButton} />
        <div className={styles.bellWrap}>
          <button type="button" aria-label="Notifications" className={styles.iconButton} onClick={onNotificationsClick}>
            <Icon name="bell" size={17} stroke={2} />
            {notifications > 0 && <span className={styles.notifBadge}>{notifications}</span>}
          </button>
          {notificationsPanel}
        </div>
        {onLogout && (
          <button type="button" aria-label="Log out" className={styles.iconButton} onClick={onLogout}>
            <Icon name="logout" size={17} />
          </button>
        )}
      </div>
      {drawer?.open && (
        <div className={styles.drawerOverlay} onClick={drawer.close}>
          <nav className={styles.drawerPanel} onClick={(e) => e.stopPropagation()}>
            <div className={styles.drawerBrand}>
              <KolaMark size={26} />
              <ShipxWordmark size={18} />
            </div>
            {links.map((link) => (
              <CustNavLink key={link.path} {...link} onNavigate={drawer.close} />
            ))}
          </nav>
        </div>
      )}
    </header>
  )
}
