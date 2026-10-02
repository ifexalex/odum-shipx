import type { JSX } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useSession } from '../auth/useSession'
import { navConfig, visualRoleFor, type NavLinkGroup } from './navConfig'
import { Sidebar, type NavGroup, type SidebarUser } from './Sidebar'

// Adapts the declarative, path-based navConfig into Sidebar's existing
// onClick/active contract via the router.
function toNavGroups(groups: NavLinkGroup[], pathname: string, navigate: (path: string) => void): NavGroup[] {
  return groups.map((group) => ({
    group: group.group,
    items: group.items.map((item) => ({
      icon: item.icon,
      label: item.label,
      count: item.count,
      active: pathname === item.path || pathname.startsWith(`${item.path}/`),
      onClick: () => navigate(item.path),
    })),
  }))
}

export interface AppSidebarProps {
  /** Passed from StaffLayout once session.name is available (extracted from the JWT `name` claim). */
  user?: SidebarUser
}

export function AppSidebar({ user }: AppSidebarProps): JSX.Element | null {
  const { session, logout } = useSession()
  const location = useLocation()
  const navigate = useNavigate()

  if (!session) return null

  const groups = toNavGroups(navConfig[session.role], location.pathname, navigate)

  return (
    <Sidebar
      role={visualRoleFor(session.role)}
      items={groups}
      user={user}
      onLogout={logout}
    />
  )
}
