import type { JSX } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useSession } from '../auth/useSession'
import { PoweredByShipx, TenantBrand } from '../design/components'
import { useBranding, useTenantApprovalCount } from '../hooks/useConfig'
import { useOnboardingPendingCount } from '../hooks/useOnboardingRequests'
import { useOpenApprovalCount } from '../hooks/usePlatformSecurity'
import { activeNavPath, navConfig, visualRoleFor, type NavLinkGroup } from './navConfig'
import { Sidebar, type NavGroup } from './Sidebar'

const ONBOARDING_REQUESTS_PATH = '/platform/onboarding-requests'
const APPROVALS_PATH = '/platform/approvals'
const TENANT_APPROVALS_PATH = '/admin/approvals'

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

  const isPlatformShell = session?.role === 'platform_admin'
  const isTenantAdmin = session?.role === 'tenant_admin'
  // Live pending-lead badge on the platform "Onboarding Requests" entry. The
  // hook short-circuits to a no-op query for every non-platform role, so the
  // call is unconditional (Rules of Hooks) but only fetches for platform admins.
  const pendingOnboarding = useOnboardingPendingCount(isPlatformShell)
  // Open two-person approvals (platform audit Phase 1): same gating as the lead badge.
  const openApprovals = useOpenApprovalCount(isPlatformShell)
  // Open tenant admin approvals inbox count (Tenant Admin Phase 1, TC-02).
  const pendingTenantApprovals = useTenantApprovalCount(isTenantAdmin)
  // Reuses StaffLayout's cached tenant branding query (zero extra requests).
  const { branding } = useBranding(!!session && !isPlatformShell)

  if (!session) return null

  const liveCounts: Record<string, number> = {
    ...(pendingOnboarding > 0 ? { [ONBOARDING_REQUESTS_PATH]: pendingOnboarding } : {}),
    ...(openApprovals > 0 ? { [APPROVALS_PATH]: openApprovals } : {}),
    ...(pendingTenantApprovals > 0 ? { [TENANT_APPROVALS_PATH]: pendingTenantApprovals } : {}),
  }
  const groups = toNavGroups(navConfig[session.role], location.pathname, navigate, liveCounts)

  const tenantName = !isPlatformShell ? branding?.display_name?.trim() : undefined

  return (
    <Sidebar
      role={visualRoleFor(session.role)}
      brand={
        tenantName ? (
          <TenantBrand
            name={tenantName}
            logoUrl={branding?.logo_url}
            color={branding?.primary_color}
          />
        ) : undefined
      }
      footer={tenantName ? <PoweredByShipx surface="dark" /> : undefined}
      items={groups}
    />
  )
}
