import type { JSX, ReactNode } from 'react'
import { Avatar, Icon, ThemeToggle } from '../design/components'
import type { Role } from '../design/theme'
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
  title?: string
  /** One-line descriptive subtitle shown under the title (list pages). */
  subtitle?: string
  breadcrumb?: string[]
  user?: TopBarUser
  search?: boolean
  actions?: ReactNode
  /** Unread count for the notification bell — wired to GET /v1/notifications/staff/unread-count. */
  notifications?: number
  /**
   * Rendered inside the bell's own positioning wrapper (`position: relative`)
   * so a dropdown panel (`position: absolute; top: 100%; right: 0`) anchors
   * under the bell regardless of what else sits in the TopBar's right side —
   * see StaffLayout.tsx's StaffNotificationPanel for the real usage.
   */
  notificationsPanel?: ReactNode
  onSearch?: (query: string) => void
  onNotificationsClick?: () => void
  onUserMenuClick?: () => void
  /**
   * Multi-role active-role switch — rendered only when more than one option
   * is passed (i.e. `session.roles.length > 1`). Purely client-side: picking
   * an option calls `onRoleChange` and never fires a request of its own.
   */
  roleOptions?: RoleOption[]
  activeRole?: string
  onRoleChange?: (role: string) => void
}

export function TopBar({
  role,
  title,
  subtitle,
  breadcrumb,
  user,
  search = true,
  actions,
  notifications = 0,
  notificationsPanel,
  onSearch,
  onNotificationsClick,
  onUserMenuClick,
  roleOptions,
  activeRole,
  onRoleChange,
}: TopBarProps): JSX.Element {
  const drawer = useShellDrawer()
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
        <div className={styles.titleBlock}>
          {breadcrumb && breadcrumb.length > 0 && (
            <div className={styles.breadcrumb}>
              {breadcrumb.map((crumb, index) => (
                <span key={crumb} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  {index > 0 && <span className={styles.breadcrumbSep}>/</span>}
                  <span
                    className={index === breadcrumb.length - 1 ? styles.breadcrumbCurrent : styles.breadcrumbLink}
                  >
                    {crumb}
                  </span>
                </span>
              ))}
            </div>
          )}
          {title && <h1 className={styles.title}>{title}</h1>}
          {title && subtitle && <p className={styles.subtitle}>{subtitle}</p>}
        </div>
      </div>
      <div className={styles.right}>
        {search && (
          <div className={styles.searchBox}>
            <span className={styles.searchIcon}>
              <Icon name="search" size={15} />
            </span>
            <input
              className={styles.searchInput}
              placeholder="Search tenants, users, containers…"
              onChange={(event) => onSearch?.(event.target.value)}
            />
          </div>
        )}
        {actions}
        {roleOptions && roleOptions.length > 1 && (
          <select
            aria-label="Active role"
            className={styles.roleSwitch}
            value={activeRole}
            onChange={(event) => onRoleChange?.(event.target.value)}
          >
            {roleOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        )}
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
        <button type="button" className={styles.userMenu} onClick={onUserMenuClick}>
          <Avatar size={30} name={user?.name ?? role} roleColor={role} />
          {user && (
            <span className={styles.userMenuText}>
              <div className={styles.userMenuName}>{user.name}</div>
              <div className={styles.userMenuRole}>{user.role}</div>
            </span>
          )}
          <Icon name="chevdown" size={13} color="var(--color-ink-4)" />
        </button>
      </div>
    </header>
  )
}
