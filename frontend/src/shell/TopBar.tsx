import type { JSX, ReactNode } from 'react'
import { Avatar, Icon, MenuButton, ThemeToggle, type MenuItem } from '../design/components'
import type { Role } from '../design/theme'
import { Breadcrumb } from './Breadcrumb'
import type { Crumb } from './breadcrumbs'
import { useShellDrawer } from './ShellDrawer'
import styles from './TopBar.module.css'

export interface TopBarUser {
  name: string
  role: string
}

export interface RoleOption {
  value: string
  label: string
}

export interface TopBarProps {
  role: Role
  user?: TopBarUser
  /** The global search box (<GlobalSearch>). A slot rather than markup so this bar stays presentational. */
  search?: ReactNode
  /** Unread count for the notification bell — wired to GET /v1/notifications/staff/unread-count. */
  notifications?: number
  /**
   * Rendered inside the bell's own positioning wrapper (`position: relative`)
   * so a dropdown panel (`position: absolute; top: 100%; right: 0`) anchors
   * under the bell regardless of what else sits in the TopBar's right side —
   * see StaffLayout.tsx's StaffNotificationPanel for the real usage.
   */
  notificationsPanel?: ReactNode
  onNotificationsClick?: () => void
  /** The account menu's "My profile". */
  onProfile?: () => void
  /** The account menu's "Sign out" (FD-15: the one place to sign out; the sidebar no longer repeats the user). */
  onLogout?: () => void
  /**
   * A multi-role user's roles: the account menu offers to switch to each one they are not working as (only when more
   * than one is passed). Purely client-side: picking one calls `onRoleChange` and fires no request of its own.
   */
  roleOptions?: RoleOption[]
  activeRole?: string
  onRoleChange?: (role: string) => void
}

/**
 * The staff top bar (FD-14): global controls only (menu, search, theme, notifications, and the account menu: profile,
 * role switch, sign out). The page's
 * title, breadcrumb and actions belong to the page (`PageHeader`), never to this bar.
 */
export function TopBar({
  role,
  user,
  search,
  notifications = 0,
  notificationsPanel,
  onNotificationsClick,
  onProfile,
  onLogout,
  roleOptions,
  activeRole,
  onRoleChange,
}: TopBarProps): JSX.Element {
  const drawer = useShellDrawer()
  const accountItems: MenuItem[] = [
    ...(onProfile ? [{ label: 'My profile', icon: 'user' as const, onSelect: onProfile }] : []),
    ...(roleOptions && roleOptions.length > 1
      ? roleOptions
          .filter((option) => option.value !== activeRole)
          .map((option) => ({ label: `Work as ${option.label}`, icon: 'refresh' as const, onSelect: () => onRoleChange?.(option.value) }))
      : []),
    ...(onLogout ? [{ label: 'Sign out', icon: 'logout' as const, onSelect: onLogout }] : []),
  ]
  return (
    <header className={styles.topbar}>
      <div className={styles.left}>
        {drawer && (
          <button
            type="button"
            aria-label="Open menu"
            className={styles.hamburger}
            onClick={drawer.toggle}
          >
            <Icon name="menu" size={18} stroke={2} />
          </button>
        )}
        {search}
      </div>
      <div className={styles.right}>
        <ThemeToggle />
        <div className={styles.bellWrap}>
          <button
            type="button"
            aria-label="Notifications"
            className={styles.bellButton}
            onClick={onNotificationsClick}
          >
            <Icon name="bell" size={17} stroke={2} />
            {notifications > 0 && <span className={styles.bellCount}>{notifications}</span>}
          </button>
          {notificationsPanel}
        </div>
        <MenuButton
          label="Account"
          items={accountItems}
          trigger={(props) => (
            <button type="button" className={styles.userMenu} {...props}>
              <Avatar size={30} name={user?.name ?? role} roleColor={role} />
              {user && (
                <span className={styles.userMenuText}>
                  <div className={styles.userMenuName}>{user.name}</div>
                  <div className={styles.userMenuRole}>{user.role}</div>
                </span>
              )}
              <Icon name="chevdown" size={13} color="var(--color-ink-4)" />
            </button>
          )}
        />
      </div>
    </header>
  )
}
