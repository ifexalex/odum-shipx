import type { CSSProperties, JSX, ReactNode } from 'react'
import { Avatar, Icon, KolaMark, ShipxWordmark, type IconName } from '../design/components'
import { colors, type Role } from '../design/theme'
import styles from './Sidebar.module.css'

export interface NavBadge {
  color: string
  count: number
}

export interface NavItemDef {
  icon?: IconName
  label: string
  active?: boolean
  badge?: NavBadge
  count?: string | number
  onClick?: () => void
}

export interface NavGroup {
  group?: string
  items: NavItemDef[]
}

export interface SidebarUser {
  name: string
  role: string
}

export interface SidebarProps {
  role: Role
  brand?: ReactNode
  items: NavGroup[]
  user?: SidebarUser
  collapsed?: boolean
  onLogout?: () => void
}

const ROLE_LABEL: Partial<Record<Role, string>> = {
  platform: 'Platform',
  china: 'China Office',
  nigeria: 'Nigeria Office',
  warehouse: 'Warehouse',
}

// Matches the per-role accent used in screens/shared/app-shell.jsx's NavItem:
// platform/china/nigeria/warehouse get a distinct role tint; everything else
// (admin, customer) falls back to the universal bright-green accent.
function navAccentColor(role: Role): string {
  switch (role) {
    case 'platform':
      return colors.rolePlatform
    case 'china':
      return colors.roleChina
    case 'nigeria':
      return colors.accent
    case 'warehouse':
      return colors.warning
    default:
      return colors.primaryBright
  }
}

function DefaultBrand(): JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
      <KolaMark size={28} color={colors.primaryBright} />
      <ShipxWordmark size={22} />
    </div>
  )
}

function NavItem({ icon, label, active, badge, count, onClick, accent }: NavItemDef & { accent: string }): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[styles.navItem, active ? styles.navItemActive : ''].filter(Boolean).join(' ')}
    >
      {active && <span className={styles.navItemAccent} style={{ '--nav-accent': accent } as CSSProperties} />}
      {icon && <Icon name={icon} size={16} stroke={2} />}
      <span className={styles.navItemLabel}>{label}</span>
      {badge && (
        <span className={styles.navItemBadge} style={{ '--nav-badge-color': badge.color } as CSSProperties}>
          {badge.count}
        </span>
      )}
      {count != null && <span className={styles.navItemCount}>{count}</span>}
    </button>
  )
}

export function Sidebar({ role, brand, items, user, collapsed = false, onLogout }: SidebarProps): JSX.Element {
  const accent = navAccentColor(role)
  const roleLabel = ROLE_LABEL[role]

  return (
    <aside className={[styles.sidebar, collapsed ? styles.collapsed : ''].filter(Boolean).join(' ')}>
      <div className={styles.brandSlot}>{brand ?? <DefaultBrand />}</div>
      {roleLabel && !collapsed && (
        <div className={styles.roleBadge}>
          <span className={styles.roleBadgeTag} style={{ '--role-badge-bg': accent } as CSSProperties}>
            <Icon name="shield" size={10} fill={colors.surface} color={colors.surface} stroke={0} />
            {roleLabel}
          </span>
        </div>
      )}
      <nav className={styles.nav}>
        {items.map((section, index) => (
          <div key={section.group ?? index} className={styles.navGroup}>
            {section.group && !collapsed && <div className={styles.groupLabel}>{section.group}</div>}
            {section.items.map((item) => (
              <NavItem key={item.label} {...item} accent={accent} />
            ))}
          </div>
        ))}
      </nav>
      {(user || onLogout) && (
        <div className={styles.footer}>
          <div className={styles.userRow}>
            {user && <Avatar size={32} name={user.name} roleColor={role} />}
            {!collapsed && (
              <>
                {user && (
                  <div className={styles.userText}>
                    <div className={styles.userName}>{user.name}</div>
                    <div className={styles.userRole}>{user.role}</div>
                  </div>
                )}
                {onLogout && (
                  <button type="button" aria-label="Log out" className={styles.logoutButton} onClick={onLogout}>
                    <Icon name="logout" size={15} />
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </aside>
  )
}
