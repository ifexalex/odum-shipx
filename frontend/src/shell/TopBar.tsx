import type { JSX, ReactNode } from 'react'
import { Avatar, Icon, ThemeToggle } from '../design/components'
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
  title?: string
  /** One-line descriptive subtitle shown under the title (list pages). */
  subtitle?: string
  /** Where the page lives (`breadcrumbTrail`); every crumb but the last is a link. */
  breadcrumb?: Crumb[]
  user?: TopBarUser
  /** The global search box (<GlobalSearch>). A slot rather than markup so this bar stays presentational. */
  search?: ReactNode
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
  search,
  actions,
  notifications = 0,
  notificationsPanel,
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
          {breadcrumb && <Breadcrumb trail={breadcrumb} />}
          {title && <h1 className={styles.title}>{title}</h1>}
          {title && subtitle && <p className={styles.subtitle}>{subtitle}</p>}
        </div>
      </div>
      <div className={styles.right}>
        {search}
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
