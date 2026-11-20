import type { JSX } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useSession } from '../auth/useSession'
import { useOnboardingPendingCount } from '../hooks/useOnboardingRequests'
import { activeNavPath, navConfig, visualRoleFor, type NavLinkGroup } from './navConfig'
import { Sidebar, type NavGroup } from './Sidebar'

const ONBOARDING_REQUESTS_PATH = '/platform/onboarding-requests'

// Adapts the declarative, path-based navConfig into Sidebar's existing
// onClick/active contract via the router. `liveCounts` overrides a link's
// static `count` with a freshly-fetched value (e.g. pending onboarding leads).
function toNavGroups(
  groups: NavLinkGroup[],
  pathname: string,
  navigate: (path: string) => void,
  liveCounts: Record<string, number>,
): NavGroup[] {
  // Exactly one item is lit (FD-15): the longest one covering the page.
  const active = activeNavPath(
    pathname,
    groups.flatMap((group) => group.items.map((item) => item.path)),
  )
  return groups.map((group) => ({
    group: group.group,
    items: group.items.map((item) => ({
      icon: item.icon,
      label: item.label,
      count: liveCounts[item.path] ?? item.count,
      active: item.path === active,
      onClick: () => navigate(item.path),
    })),
  }))
}

export function AppSidebar(): JSX.Element | null {
  const { session } = useSession()
  const location = useLocation()
  const navigate = useNavigate()

  // Live pending-lead badge on the platform "Onboarding Requests" entry. The
  // hook short-circuits to a no-op query for every non-platform role, so the
  // call is unconditional (Rules of Hooks) but only fetches for platform admins.
  const pendingOnboarding = useOnboardingPendingCount(session?.role === 'platform_admin')

  if (!session) return null

  const liveCounts: Record<string, number> =
    pendingOnboarding > 0 ? { [ONBOARDING_REQUESTS_PATH]: pendingOnboarding } : {}
  const groups = toNavGroups(navConfig[session.role], location.pathname, navigate, liveCounts)

  return (
    <Sidebar
      role={visualRoleFor(session.role)}
      items={groups}
    />
  )
}
